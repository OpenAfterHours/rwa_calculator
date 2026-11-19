"""
CCP, default-fund, settlement-row and BA-CVA review items through the real pipeline.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator.run_with_data -> AggregatedResultBundle
    (hierarchy -> ccr_sa_ccr -> classifier -> crm -> calculators -> aggregator)

Key responsibilities:
- One end-to-end hand-calculated assertion per review item of the 2026-11
  product review's ``ccp_cva`` cluster, run under BOTH regimes wherever the rule
  applies to both (LESSONS C7): CRR at 2026-03-31, Basel 3.1 at 2027-03-31.
- CC-08: settlement-risk and default-fund rows are own-funds amounts, not credit
  exposures — always SA (RW 12.5), never reduced by collateral, guarantees,
  provisions or a supporting factor, and never a sink for another row's CRM.
- CC-10: default-fund own funds per CCR (CRR) Part Art. 308(2) / 309(1) / 310.
- CC-15 / CC-16: BA-CVA netting-set inputs and coverage (Basel 3.1 only).

The unit tests next to each module pin the arithmetic; these pin that the
arithmetic reaches ``rwa_final`` and the bundle roll-ups unchanged.

References:
- CRR Art. 378-380 and Art. 92(3)(ca) (PS1/26 Art. 92(3)(ca) identical).
- PRA Rulebook, Counterparty Credit Risk (CRR) Part Art. 307-310.
- PS1/26 Appendix 1, Annex R (re-states only Art. 308(3) / 309(2)).
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    CCRCollateralBundle,
    FailedTradesBundle,
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
    FAILED_TRADE_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.loader import enforce_schema
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_irb1 import (
    CCR_IRB1_COUNTERPARTY_REF,
    build_raw_data_bundle_ccr_irb1,
    create_ccr_irb1_model_permission,
)
from tests.fixtures.raw_bundle import make_raw_bundle, seal_raw_table

_REGIMES = ("crr", "b31")


def _config(
    regime: str, permission_mode: PermissionMode = PermissionMode.STANDARDISED
) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2026, 3, 31), permission_mode=permission_mode
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 3, 31), permission_mode=permission_mode
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
    failed_trades: list[dict[str, Any]] | None = None,
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
        failed_trades=(
            FailedTradesBundle(failed_trades=_frame(failed_trades, FAILED_TRADE_SCHEMA))
            if failed_trades
            else None
        ),
    )


def _run(
    regime: str,
    permission_mode: PermissionMode = PermissionMode.STANDARDISED,
    **bundle_kwargs: Any,
) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(
        make_raw_bundle(**bundle_kwargs), _config(regime, permission_mode)
    )


def _by_ref(result: AggregatedResultBundle) -> dict[str, dict[str, Any]]:
    df = result.results.collect()
    return {row["exposure_reference"]: row for row in df.to_dicts()}


# ---------------------------------------------------------------------------
# CC-08 — settlement-risk / default-fund rows are own-funds amounts
# ---------------------------------------------------------------------------
#
# CRR Art. 378: "multiply that price difference by the appropriate factor in
# column A of Table 1 in order to calculate the institution's own funds
# requirement for settlement risk"; Art. 92(3)(ca) (PS1/26 identical): "the own
# funds requirements for settlement risk calculated in accordance with Articles
# 378 and 380 of CRR"; CCR (CRR) Part Art. 308(3) / 309(2): RWEA = own funds
# requirement x 12.5. Neither admits an IRB formula or credit risk mitigation on
# the own-funds amount, so FT1 (DvP, agreed 1.0m, market value 0.9m, 20 working
# days -> 100,000 x 50% = 50,000 own funds) is RWEA 625,000 however the
# counterparty's lending book is mitigated or rated.

_FT1 = {
    "failed_trade_id": "FT1",
    "counterparty_reference": "CP_SME",
    "settlement_type": "dvp",
    "working_days_past_due": 20,
    "instrument_class": "equity",
    "agreed_settlement_price": 1_000_000.0,
    "current_market_value": 900_000.0,
}
_FT1_RWA = 50_000.0 * 12.5

_SME_COUNTERPARTIES = [
    {
        "counterparty_reference": "CP_SME",
        "counterparty_name": "SME corporate with lending and a failed trade",
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": 5_000_000.0,
    },
    {
        "counterparty_reference": "GOV",
        "counterparty_name": "UK sovereign",
        "entity_type": "sovereign",
        "country_code": "GB",
    },
]

_LOAN = {
    "loan_reference": "L1",
    "counterparty_reference": "CP_SME",
    "product_type": "term_loan",
    "drawn_amount": 1_000_000.0,
    "currency": "GBP",
    "value_date": date(2026, 1, 1),
    "maturity_date": date(2030, 1, 1),
    "seniority": "senior",
}

_CP_CASH = {
    "collateral_reference": "C1",
    "collateral_type": "cash",
    "currency": "GBP",
    "market_value": 1_000_000.0,
    "beneficiary_type": "counterparty",
    "beneficiary_reference": "CP_SME",
    "is_eligible_financial_collateral": True,
}

_CP_GUARANTEE = {
    "guarantee_reference": "G1",
    "guarantor": "GOV",
    "currency": "GBP",
    "amount_covered": 1_000_000.0,
    "beneficiary_type": "counterparty",
    "beneficiary_reference": "CP_SME",
    "guarantee_type": "guarantee",
}

_CP_PROVISION = {
    "provision_reference": "P1",
    "provision_type": "scra",
    "currency": "GBP",
    "amount": 100_000.0,
    "beneficiary_type": "counterparty",
    "beneficiary_reference": "CP_SME",
}


def _sme_run(regime: str, **crm: Any) -> dict[str, dict[str, Any]]:
    return _by_ref(
        _run(
            regime,
            counterparties=pl.LazyFrame(_SME_COUNTERPARTIES),
            loans=pl.LazyFrame([_LOAN]),
            ccr=_ccr_bundle(failed_trades=[_FT1]),
            **crm,
        )
    )


@pytest.mark.parametrize("regime", _REGIMES)
class TestCC08OwnFundsRowsTakeNoCreditRiskMitigation:
    """Counterparty-level CRM belongs to the credit exposures, not the own-funds row."""

    def test_counterparty_cash_collateral(self, regime: str) -> None:
        # Act
        rows = _sme_run(regime, collateral=pl.LazyFrame([_CP_CASH]))

        # Assert: pre-fix the pool was pro-rated over the loan (1m) and FT1 (50k):
        # FT1 RWA 29,761.90 and the loan kept 47,619.05 of unmitigated EAD.
        assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)
        assert rows["L1"]["ead_final"] == pytest.approx(0.0, abs=1e-6)

    def test_counterparty_guarantee(self, regime: str) -> None:
        # Act
        rows = _sme_run(regime, guarantees=pl.LazyFrame([_CP_GUARANTEE]))

        # Assert: pre-fix FT1 was split into a guaranteed leg at the guarantor's
        # weight (RWA 50,000 in total); now one unsplit row at 12.5.
        ft_rows = [ref for ref in rows if ref.startswith("ft__")]
        assert ft_rows == ["ft__FT1"]
        assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)

    def test_counterparty_provision(self, regime: str) -> None:
        # Act
        rows = _sme_run(regime, provisions=pl.LazyFrame([_CP_PROVISION]))

        # Assert: pre-fix 100,000 x 50k / 1.05m = 4,761.90 came off FT1's EAD.
        assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)
        assert rows["L1"]["provision_allocated"] == pytest.approx(100_000.0, rel=1e-9)

    def test_no_supporting_factor(self, regime: str) -> None:
        # Act
        rows = _sme_run(regime)

        # Assert: an own-funds amount is not an exposure to an SME (CRR Art. 501).
        assert rows["ft__FT1"]["supporting_factor"] == 1.0
        assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)

    def test_defaulted_counterparty_keeps_the_12_5_pin(self, regime: str) -> None:
        # Arrange: the same SME, now in default. Art. 127 weights the unsecured
        # part of a defaulted EXPOSURE; an own-funds amount is not one.
        defaulted = [{**_SME_COUNTERPARTIES[0], "default_status": True}, _SME_COUNTERPARTIES[1]]

        # Act
        rows = _by_ref(
            _run(
                regime,
                counterparties=pl.LazyFrame(defaulted),
                ccr=_ccr_bundle(failed_trades=[_FT1]),
            )
        )

        # Assert (pre-fix: Art. 127 150% replaced the pin -> RWA 75,000)
        assert rows["ft__FT1"]["risk_weight"] == 12.5
        assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_cc08_own_funds_rows_are_never_irb(regime: str) -> None:
    """An F-IRB-permissioned, internally rated counterparty still gets 12.5 x own funds."""
    # Arrange
    base = build_raw_data_bundle_ccr_irb1()
    ft1 = {**_FT1, "counterparty_reference": CCR_IRB1_COUNTERPARTY_REF}
    bundle = dataclasses.replace(
        base,
        ccr=dataclasses.replace(
            base.ccr, failed_trades=_ccr_bundle(failed_trades=[ft1]).failed_trades
        ),
        model_permissions=seal_raw_table(create_ccr_irb1_model_permission(), "model_permissions"),
    )

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, _config(regime, PermissionMode.IRB))
    rows = _by_ref(result)

    # Assert: the netting set itself IS IRB-routed (adequacy); the own-funds row is not.
    # Pre-fix: FT1 routed foundation_irb, RWA 45,764 (CRR) / 265,881 (B31).
    assert rows["ccr__NS_IRB_001"]["approach_applied"] == "foundation_irb"
    assert rows["ft__FT1"]["approach_applied"] == "standardised"
    assert rows["ft__FT1"]["rwa_final"] == pytest.approx(_FT1_RWA, rel=1e-9)


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


# ---------------------------------------------------------------------------
# CC-11 — Art. 107(2): the 2% / 4% pin is for TRADE exposures to a QCCP only
# ---------------------------------------------------------------------------
#
# CRR Art. 107(2) = PS1/26 Art. 107(2): "For trade exposures and for default fund
# contributions to a central counterparty, institutions shall apply the treatment
# set out in Section 9 ... For all other types of exposures to a central
# counterparty, institutions shall treat those exposures as follows: (a) as
# exposures to an institution for other types of exposures to a qualifying CCP;
# (b) as exposures to a corporate for other types of exposures to a
# non-qualifying CCP." CCR (CRR) Part Art. 306(1)(b): non-QCCP trade exposures
# take "the risk weight ... as set out in Article 107(2)(b)" — a corporate's.

_CCP_RATED = [
    {**_CCP_COUNTERPARTIES[0]},  # CCP_Q, QCCP
    {**_CCP_COUNTERPARTIES[1]},  # CCP_N, non-QCCP
]

_CCP_RATINGS = [
    {
        "rating_reference": "R_Q",
        "counterparty_reference": "CCP_Q",
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": 2,
        "rating_date": date(2026, 1, 1),
    },
    {
        "rating_reference": "R_N",
        "counterparty_reference": "CCP_N",
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": 3,
        "rating_date": date(2026, 1, 1),
    },
]

_QCCP_LOAN = {**_LOAN, "loan_reference": "L_QCCP", "counterparty_reference": "CCP_Q"}


def _ccp_run(regime: str) -> dict[str, dict[str, Any]]:
    return _by_ref(
        _run(
            regime,
            counterparties=pl.LazyFrame(_CCP_RATED),
            ratings=pl.LazyFrame(_CCP_RATINGS),
            loans=pl.LazyFrame([_QCCP_LOAN]),
            ccr=_ccr_bundle(
                trades=[_irs("T_Q", "NS_Q"), _irs("T_N", "NS_N")],
                netting_sets=[
                    {
                        "netting_set_id": "NS_Q",
                        "counterparty_reference": "CCP_Q",
                        "is_legally_enforceable": True,
                    },
                    {
                        "netting_set_id": "NS_N",
                        "counterparty_reference": "CCP_N",
                        "is_legally_enforceable": True,
                    },
                ],
            ),
        )
    )


# (CRR, B31) risk weights. Institution CQS 2 (Art. 120 Table 3): 50% / ECRA 30%.
# Corporate CQS 3 (Art. 122 Table 6): 100% / 75%.
_QCCP_LOAN_RW = {"crr": 0.50, "b31": 0.30}
_NON_QCCP_TRADE_RW = {"crr": 1.00, "b31": 0.75}


@pytest.mark.parametrize("regime", _REGIMES)
class TestCC11CcpExposureTreatment:
    """Only trade exposures to a QCCP are pinned; other CCP exposures follow Art. 107(2)."""

    def test_qccp_trade_exposure_keeps_the_two_percent_pin(self, regime: str) -> None:
        # Act / Assert (control: Art. 306(1)(a) unchanged)
        assert _ccp_run(regime)["ccr__NS_Q"]["risk_weight"] == pytest.approx(0.02)

    def test_loan_to_a_qccp_is_an_institution_exposure(self, regime: str) -> None:
        # Act
        row = _ccp_run(regime)["L_QCCP"]

        # Assert (pre-fix: pinned at 2%)
        assert row["exposure_class"] == "institution"
        assert row["risk_weight"] == pytest.approx(_QCCP_LOAN_RW[regime])

    def test_non_qccp_trade_exposure_is_a_corporate_exposure(self, regime: str) -> None:
        # Act
        row = _ccp_run(regime)["ccr__NS_N"]

        # Assert (pre-fix: institution CQS 3 -> 50% in both regimes)
        assert row["exposure_class"] == "corporate"
        assert row["risk_weight"] == pytest.approx(_NON_QCCP_TRADE_RW[regime])
