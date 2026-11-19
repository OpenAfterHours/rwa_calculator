"""
CCP, default-fund, settlement-row and BA-CVA review items through the real pipeline.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator.run_with_data -> AggregatedResultBundle
    (hierarchy -> ccr_sa_ccr -> classifier -> crm -> calculators -> aggregator)

Key responsibilities:
- One end-to-end hand-calculated assertion per review item of the 2026-11
  product review's ``ccp_cva`` cluster, run under BOTH regimes wherever the rule
  applies to both (LESSONS C7): CRR at 2026-03-31, Basel 3.1 at 2027-03-31.
- CC-10: default-fund own funds per CCR (CRR) Part Art. 308(2) / 309(1) / 310.

The unit tests next to each module pin the arithmetic; these pin that the
arithmetic reaches ``rwa_final`` and the bundle roll-ups unchanged.

References:
- PRA Rulebook, Counterparty Credit Risk (CRR) Part Art. 307-310.
- PS1/26 Appendix 1, Annex R (re-states only Art. 308(3) / 309(2)).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    DF_CONTRIBUTION_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.loader import enforce_schema
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_REGIMES = ("crr", "b31")


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2026, 3, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 3, 31), permission_mode=PermissionMode.STANDARDISED
    )


def _frame(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.LazyFrame:
    if not rows:
        return pl.LazyFrame(schema=dtypes_of(schema))
    return enforce_schema(pl.LazyFrame(rows), schema, strict=False)


def _ccr_bundle(
    *,
    trades: list[dict[str, Any]] | None = None,
    netting_sets: list[dict[str, Any]] | None = None,
    default_fund_contributions: list[dict[str, Any]] | None = None,
) -> RawCCRBundle:
    return RawCCRBundle(
        trades=TradeBundle(trades=_frame(trades or [], TRADE_SCHEMA)),
        netting_sets=NettingSetBundle(netting_sets=_frame(netting_sets or [], NETTING_SET_SCHEMA)),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_frame([], MARGIN_AGREEMENT_SCHEMA)
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_frame([], CCR_COLLATERAL_SCHEMA)),
        default_fund_contributions=(
            _frame(default_fund_contributions, DF_CONTRIBUTION_SCHEMA)
            if default_fund_contributions
            else None
        ),
    )


def _run(regime: str, **bundle_kwargs: Any) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(make_raw_bundle(**bundle_kwargs), _config(regime))


def _by_ref(result: AggregatedResultBundle) -> dict[str, dict[str, Any]]:
    df = result.results.collect()
    return {row["exposure_reference"]: row for row in df.to_dicts()}


# ---------------------------------------------------------------------------
# CC-10 — default-fund own funds (Art. 308(2) / 309(1) / 310)
# ---------------------------------------------------------------------------

_CCP_COUNTERPARTIES = [
    {
        "counterparty_reference": "CCP_Q",
        "counterparty_name": "Qualifying CCP",
        "entity_type": "ccp",
        "country_code": "GB",
        "is_qccp": True,
    },
    {
        "counterparty_reference": "CCP_N",
        "counterparty_name": "Non-qualifying CCP",
        "entity_type": "ccp",
        "country_code": "GB",
        "is_qccp": False,
    },
]

_QCCP_COMMON = {
    "ccp_reference": "CCP_Q",
    "is_qccp_ccp": True,
    "df_i_contribution_amount": 10_000_000.0,
    "df_ccp_prefunded": 100_000_000.0,
    "df_cm_total_contributions": 500_000_000.0,
}

_DFC_ROWS = [
    # Art. 308(2): 20m x 10m / (100m + 500m) = 333,333.33 -> RWEA 4,166,666.67
    {**_QCCP_COMMON, "contribution_id": "Q", "k_ccp_published": 20_000_000.0},
    # Art. 308(2) floor: 0.5m x 10m / 600m = 8,333.33 < 8% x 2% x 10m = 16,000
    {**_QCCP_COMMON, "contribution_id": "QF", "k_ccp_published": 500_000.0},
    # Art. 310: unfunded contribution to a QCCP, 0% risk weight
    {
        **_QCCP_COMMON,
        "contribution_id": "QU",
        "k_ccp_published": 20_000_000.0,
        "is_unfunded_commitment": True,
    },
    # Art. 309(1): non-QCCP, K = DF = 10m -> RWEA 125m
    {
        "contribution_id": "NQ",
        "ccp_reference": "CCP_N",
        "is_qccp_ccp": False,
        "df_i_contribution_amount": 10_000_000.0,
        "df_cm_total_contributions": 500_000_000.0,
        "k_ccp_published": 50_000_000.0,
    },
]


@pytest.mark.parametrize("regime", _REGIMES)
class TestCC10DefaultFundBranches:
    """Each Art. 307 branch reaches ``rwa_final`` with its hand-calculated value."""

    @pytest.fixture
    def result(self, regime: str) -> AggregatedResultBundle:
        return _run(
            regime,
            counterparties=pl.LazyFrame(_CCP_COUNTERPARTIES),
            ccr=_ccr_bundle(default_fund_contributions=_DFC_ROWS),
        )

    def test_each_branch_rwa(self, result: AggregatedResultBundle) -> None:
        # Arrange
        rows = _by_ref(result)

        # Act
        rwa = {ref: rows[f"dfc__{ref}"]["rwa_final"] for ref in ("Q", "QF", "QU", "NQ")}

        # Assert (pre-fix: Q 5,000,000 / QF 125,000 / QU 5,000,000 / NQ 12,500,000)
        assert rwa["Q"] == pytest.approx(4_166_666.6666667, rel=1e-9)
        assert rwa["QF"] == pytest.approx(200_000.0, rel=1e-9)
        assert rwa["QU"] == pytest.approx(0.0, abs=1e-9)
        assert rwa["NQ"] == pytest.approx(125_000_000.0, rel=1e-9)

    def test_bundle_roll_up_sums_every_branch(self, result: AggregatedResultBundle) -> None:
        # Arrange
        expected = 4_166_666.6666667 + 200_000.0 + 0.0 + 125_000_000.0

        # Act / Assert
        assert result.rwa_ccr_default_fund == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# CC-15 / CC-16 — BA-CVA netting-set inputs and coverage (Basel 3.1 only)
# ---------------------------------------------------------------------------


def _irs(trade_id: str, netting_set_id: str) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": "interest_rate",
        "transaction_type": "derivative",
        "notional": 10_000_000.0,
        "currency": "GBP",
        "start_date": date(2026, 3, 31),
        "maturity_date": date(2031, 3, 31),
        "mtm_value": 2_000_000.0,
    }


_CVA_COUNTERPARTIES = [
    {
        "counterparty_reference": "CP_NFC",
        "counterparty_name": "Non-financial corporate",
        "entity_type": "corporate",
        "country_code": "GB",
        "counterparty_type": "non_financial",
    },
    {
        "counterparty_reference": "CP_FIN",
        "counterparty_name": "Financial corporate, no CVA input row",
        "entity_type": "corporate",
        "country_code": "GB",
        "counterparty_type": "financial",
    },
    {
        "counterparty_reference": "CCP_Q",
        "counterparty_name": "Qualifying CCP, no CVA input row",
        "entity_type": "ccp",
        "country_code": "GB",
        "is_qccp": True,
    },
]

_CVA_NETTING_SETS = [
    {
        "netting_set_id": "NS_NFC",
        "counterparty_reference": "CP_NFC",
        "is_legally_enforceable": True,
    },
    {
        "netting_set_id": "NS_FIN",
        "counterparty_reference": "CP_FIN",
        "is_legally_enforceable": True,
    },
    {"netting_set_id": "NS_CCP", "counterparty_reference": "CCP_Q", "is_legally_enforceable": True},
]

# Counterparty-level lending collateral on the NFC: it leaks into the derivative
# row's post-CRM ead_final (CC-07, open), which 4.3's EAD_NS must not read.
_NFC_CASH = {
    "collateral_reference": "C_NFC",
    "collateral_type": "cash",
    "currency": "GBP",
    "market_value": 1_000_000.0,
    "beneficiary_type": "counterparty",
    "beneficiary_reference": "CP_NFC",
    "is_eligible_financial_collateral": True,
}


def _run_cva(regime: str) -> AggregatedResultBundle:
    return _run(
        regime,
        counterparties=pl.LazyFrame(_CVA_COUNTERPARTIES),
        collateral=pl.LazyFrame([_NFC_CASH]),
        ccr=_ccr_bundle(
            trades=[_irs("T_NFC", "NS_NFC"), _irs("T_FIN", "NS_FIN"), _irs("T_CCP", "NS_CCP")],
            netting_sets=_CVA_NETTING_SETS,
        ),
        cva_counterparties=pl.LazyFrame(
            {
                "counterparty_reference": ["CP_NFC"],
                "cva_rw_sector": ["OTHER"],
                "cva_rw_rating_band": ["IG"],
                "cva_effective_maturity_years": [5.0],
                "cva_in_scope": [True],
            }
        ),
    )


class TestCC15BaCvaNettingSetInputs:
    """PS1/26 CVA Part 4.3: alpha and EAD_NS are the CCR Part's, per netting set."""

    def test_nfc_scva_uses_alpha_one_and_the_sa_ccr_exposure_value(self) -> None:
        # Arrange
        result = _run_cva("b31")
        nfc = _by_ref(result)["ccr__NS_NFC"]
        assert nfc["alpha_applied"] == 1.0, "adequacy: Annex R 274(2) NFC alpha must be 1"
        assert nfc["ead_final"] < nfc["ead_ccr"], (
            "adequacy: the lending collateral must cut ead_final, or the EAD_NS "
            "basis is not distinguished by this test"
        )
        df_5y = (1.0 - math.exp(-0.25)) / 0.25

        # Act
        expected = 0.65 * 12.5 * 0.05 * 5.0 * nfc["ead_ccr"] * df_5y / 1.0

        # Assert (pre-fix: ead_final / 1.4)
        assert result.cva_rwa == pytest.approx(expected, rel=1e-9)


class TestCC16BaCvaCoverage:
    """A derivative counterparty with no CVA input row is warned, never dropped silently."""

    def test_b31_warns_the_uncovered_counterparty_only(self) -> None:
        # Act
        result = _run_cva("b31")

        # Assert: CP_FIN warned; CP_NFC covered; the QCCP's derivatives are not
        # covered transactions (1.2 exclusion (1)(a)).
        warned = sorted(e.counterparty_reference for e in result.errors if e.code == "CCR030")
        assert warned == ["CP_FIN"]

    def test_b31_warns_when_no_cva_input_is_supplied_at_all(self) -> None:
        # Act
        result = _run(
            "b31",
            counterparties=pl.LazyFrame(_CVA_COUNTERPARTIES),
            ccr=_ccr_bundle(trades=[_irs("T_FIN", "NS_FIN")], netting_sets=_CVA_NETTING_SETS[1:2]),
        )

        # Assert (pre-fix: no error at all)
        warned = [e.counterparty_reference for e in result.errors if e.code == "CCR030"]
        assert warned == ["CP_FIN"]
        assert result.cva_rwa is None

    def test_crr_has_no_ba_cva_and_no_coverage_warning(self) -> None:
        # Act
        result = _run_cva("crr")

        # Assert: the cva_ba_cva Feature is Basel 3.1 only
        assert result.cva_rwa is None
        assert not [e for e in result.errors if e.code == "CCR030"]
