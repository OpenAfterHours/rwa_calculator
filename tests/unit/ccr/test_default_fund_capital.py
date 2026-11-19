"""
Unit tests for the CCP default-fund own-funds calculator (review item CC-10).

Pipeline position:
    RawCCRBundle.default_fund_contributions -> compute_dfc_capital
    -> synthetic ``dfc__`` SA row (RW pinned to 12.5)

Key responsibilities under test — one test per Section 9 branch:
- Art. 308(2) QCCP pre-funded: the DF_CCP term in the denominator AND the
  8% x 2% x DF_i floor.
- Art. 309(1) non-QCCP: K = DF + UC — the contribution itself, NOT a K_CCP share.
- Art. 310 QCCP unfunded: 0% risk weight, so no own funds at all.

Rule text relied on (PRA Rulebook, Counterparty Credit Risk (CRR) Part, in force
until 31-12-2026; PS1/26 Annex R re-states only 308(3)/309(2) cross-references,
so the formulae carry into Basel 3.1 unchanged — both regimes, one test set):

- Art. 308(2) (formula image): "K_i = max{ K_CCP . DF_i / (DF_CCP + DF_CM) ,
  8% . 2% . DF_i }" where "DF_CCP = the pre-funded financial resources of the
  CCP" and "DF_CM = the sum of pre-funded contributions of all clearing members".
- Art. 309(1): "K = DF + UC where: K = the own funds requirement; DF = the
  pre-funded contributions to the default fund of a non-qualifying CCP; and
  UC = the unfunded contributions to the default fund of a non-qualifying CCP."
- Art. 310: "An institution shall apply a 0% risk weight to its unfunded
  contributions to the default fund of a QCCP."

Defect pinned (LESSONS C1): before the fix every branch computed
``K_CCP x DF_i / DF_CM`` — non-QCCP DF 10m gave K 1m (RWEA 12.5m) instead of
K 10m (RWEA 125m); the QCCP floor never bound; Art. 310 unfunded contributions
were charged.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    DF_CONTRIBUTION_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.ccr.default_fund import compute_dfc_capital
from rwa_calc.engine.loader import enforce_schema
from tests.fixtures.raw_bundle import make_raw_bundle

_CONFIGS = {
    "crr": CalculationConfig.crr(reporting_date=date(2026, 3, 31)),
    "b31": CalculationConfig.basel_3_1(reporting_date=date(2027, 3, 31)),
}


def _compute(rows: list[dict[str, object]], regime: str) -> pl.DataFrame:
    lf = enforce_schema(pl.LazyFrame(rows), DF_CONTRIBUTION_SCHEMA, strict=False)
    return compute_dfc_capital(lf, _CONFIGS[regime]).collect()


def _row(out: pl.DataFrame, contribution_id: str) -> dict[str, object]:
    return out.filter(pl.col("contribution_id") == contribution_id).row(0, named=True)


def _empty(schema: dict[str, object]) -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(schema))


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestArt308QccpPrefunded:
    """Art. 308(2): K_i = max(K_CCP . DF_i / (DF_CCP + DF_CM), 8% . 2% . DF_i)."""

    def test_df_ccp_enters_the_denominator(self, regime: str) -> None:
        # Arrange: K_CCP 20m, DF_i 10m, DF_CCP 100m, DF_CM 500m.
        # K = 20m x 10m / (100m + 500m) = 333,333.33 > floor 16,000.
        rows = [
            {
                "contribution_id": "Q",
                "ccp_reference": "CCP",
                "is_qccp_ccp": True,
                "df_i_contribution_amount": 10_000_000.0,
                "df_ccp_prefunded": 100_000_000.0,
                "df_cm_total_contributions": 500_000_000.0,
                "k_ccp_published": 20_000_000.0,
            }
        ]

        # Act
        row = _row(_compute(rows, regime), "Q")

        # Assert (pre-fix: K 400,000 / RWEA 5,000,000 — DF_CCP ignored)
        assert row["k_cm"] == pytest.approx(20_000_000.0 * 10 / 600, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(4_166_666.6666667, rel=1e-12)
        assert row["regulatory_band"] == "dfc_qccp_prefunded"

    def test_floor_binds_when_hypothetical_capital_share_is_small(self, regime: str) -> None:
        # Arrange: K_CCP 0.5m -> share 0.5m x 10m / 600m = 8,333.33
        # floor = 8% x 2% x 10m = 16,000 -> binds.
        rows = [
            {
                "contribution_id": "QF",
                "ccp_reference": "CCP",
                "is_qccp_ccp": True,
                "df_i_contribution_amount": 10_000_000.0,
                "df_ccp_prefunded": 100_000_000.0,
                "df_cm_total_contributions": 500_000_000.0,
                "k_ccp_published": 500_000.0,
            }
        ]

        # Act
        row = _row(_compute(rows, regime), "QF")

        # Assert (pre-fix: K 10,000 / RWEA 125,000 — floor absent)
        assert row["k_cm"] == pytest.approx(16_000.0, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(200_000.0, rel=1e-12)

    def test_absent_df_ccp_is_read_as_zero_which_is_conservative(self, regime: str) -> None:
        # Arrange: no DF_CCP supplied. Reading it as 0 can only shrink the
        # denominator, so K can only rise: 20m x 10m / 500m = 400,000.
        rows = [
            {
                "contribution_id": "QN",
                "ccp_reference": "CCP",
                "is_qccp_ccp": True,
                "df_i_contribution_amount": 10_000_000.0,
                "df_cm_total_contributions": 500_000_000.0,
                "k_ccp_published": 20_000_000.0,
            }
        ]

        # Act
        row = _row(_compute(rows, regime), "QN")

        # Assert
        assert row["k_cm"] == pytest.approx(400_000.0, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(5_000_000.0, rel=1e-12)


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestArt309NonQccp:
    """Art. 309(1): K = DF + UC — the contribution itself is the own funds."""

    def test_prefunded_contribution_is_charged_in_full(self, regime: str) -> None:
        # Arrange: DF 10m to a non-QCCP (K_CCP / DF_CM are irrelevant to 309).
        rows = [
            {
                "contribution_id": "NQ",
                "ccp_reference": "CCP",
                "is_qccp_ccp": False,
                "df_i_contribution_amount": 10_000_000.0,
                "df_cm_total_contributions": 500_000_000.0,
                "k_ccp_published": 50_000_000.0,
            }
        ]

        # Act
        row = _row(_compute(rows, regime), "NQ")

        # Assert (pre-fix: K 1,000,000 / RWEA 12,500,000)
        assert row["k_cm"] == pytest.approx(10_000_000.0, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(125_000_000.0, rel=1e-12)
        assert row["regulatory_band"] == "dfc_non_qccp_prefunded"

    def test_unfunded_contribution_is_charged_in_full(self, regime: str) -> None:
        # Arrange: UC 4m to a non-QCCP; K_CCP / DF_CM play no part in Art. 309.
        rows = [
            {
                "contribution_id": "NU",
                "ccp_reference": "CCP",
                "is_qccp_ccp": False,
                "is_unfunded_commitment": True,
                "df_i_contribution_amount": 4_000_000.0,
                "df_cm_total_contributions": 500_000_000.0,
                "k_ccp_published": 50_000_000.0,
            }
        ]

        # Act
        row = _row(_compute(rows, regime), "NU")

        # Assert
        assert row["k_cm"] == pytest.approx(4_000_000.0, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(50_000_000.0, rel=1e-12)
        assert row["regulatory_band"] == "dfc_non_qccp_unfunded"


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_art_310_qccp_unfunded_contribution_carries_no_own_funds(regime: str) -> None:
    """Art. 310: 0% risk weight on unfunded contributions to a QCCP."""
    # Arrange
    rows = [
        {
            "contribution_id": "QU",
            "ccp_reference": "CCP",
            "is_qccp_ccp": True,
            "is_unfunded_commitment": True,
            "df_i_contribution_amount": 10_000_000.0,
            "df_ccp_prefunded": 100_000_000.0,
            "df_cm_total_contributions": 500_000_000.0,
            "k_ccp_published": 20_000_000.0,
        }
    ]

    # Act
    row = _row(_compute(rows, regime), "QU")

    # Assert (pre-fix: K 400,000 / RWEA 5,000,000)
    assert row["k_cm"] == 0.0
    assert row["dfc_rwea"] == 0.0
    assert row["regulatory_band"] == "dfc_qccp_unfunded"


_QX = {
    "contribution_id": "QX",
    "ccp_reference": "CCP",
    "is_qccp_ccp": True,
    "df_i_contribution_amount": 10_000_000.0,
    "df_cm_total_contributions": 500_000_000.0,
    "k_ccp_published": 20_000_000.0,
}


@pytest.mark.parametrize("missing", ["k_ccp_published", "df_cm_total_contributions"])
class TestArt308AllocationInputMissing:
    """A QCCP pre-funded row Art. 308(2) cannot allocate: floor charged, CCR032 raised.

    The floor is one arm of the Art. 308(2) max, so it is a lower bound on K_i
    whatever K_CCP or DF_CM would have been. Before this, the missing input left
    ``k_cm`` null; the ccr stage minted a null drawn amount, the CRM chain made
    it EAD 0, and the row published RWEA 0 with no error at all — the null-EAD
    detector (OUT004) never saw a null. Measured end to end, both regimes.
    """

    def test_the_floor_is_charged(self, missing: str) -> None:
        # Arrange
        rows = [{**_QX, missing: None}]

        # Act
        row = _row(_compute(rows, "b31"), "QX")

        # Assert: 8% x 2% x 10m = 16,000 (RWEA 200,000), never null / zero.
        assert row["k_cm"] == pytest.approx(16_000.0, rel=1e-12)
        assert row["dfc_rwea"] == pytest.approx(200_000.0, rel=1e-12)

    def test_the_input_gate_names_the_contribution(self, missing: str) -> None:
        # Arrange: the missing row, an unfunded QCCP row and a non-QCCP row with
        # the same gap (neither reads K_CCP / DF_CM), and a complete row.
        rows = [
            {**_QX, missing: None},
            {**_QX, "contribution_id": "QU", missing: None, "is_unfunded_commitment": True},
            {**_QX, "contribution_id": "NQ", missing: None, "is_qccp_ccp": False},
            {**_QX, "contribution_id": "OK"},
        ]
        frame = enforce_schema(pl.LazyFrame(rows), DF_CONTRIBUTION_SCHEMA, strict=False)
        ccr = RawCCRBundle(
            trades=TradeBundle(trades=_empty(TRADE_SCHEMA)),
            netting_sets=NettingSetBundle(netting_sets=_empty(NETTING_SET_SCHEMA)),
            margin_agreements=MarginAgreementBundle(
                margin_agreements=_empty(MARGIN_AGREEMENT_SCHEMA)
            ),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=_empty(CCR_COLLATERAL_SCHEMA)),
            default_fund_contributions=frame,
        )

        # Act
        errors = [e for e in validate_bundle_values(make_raw_bundle(ccr=ccr)) if e.code == "CCR032"]

        # Assert
        assert [(e.exposure_reference, e.field_name) for e in errors] == [("dfc__QX", missing)]
        assert errors[0].severity is ErrorSeverity.ERROR
