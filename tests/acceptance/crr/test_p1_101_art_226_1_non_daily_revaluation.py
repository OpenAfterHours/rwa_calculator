"""
P1.101: CRR Art. 226(1) Non-Daily Revaluation Haircut Adjustment.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario (CRR-D-REVAL):
    A repo loan (is_sft=True) to an unrated GB corporate (CP_CRM_REVAL) is
    secured by a GBP 800k corporate bond (CQS 1, residual maturity 4.5y).
    The collateral is revalued every 5 days (revaluation_frequency_days=5).

    Step 1 — base 10-day haircut (CRR Art. 224 Table 1):
        corp_bond CQS 1, 1–5y band  -> H_n = 4.0%

    Step 2 — scale to SFT 5-day holding period (Art. 226(2)):
        H_m = H_n × sqrt(T_m / 10) = 0.04 × sqrt(5/10) ≈ 0.028284271

    Step 3 — non-daily revaluation adjustment (Art. 226(1)):
        H = H_m × sqrt((N + T_m - 1) / T_m)
          = H_m × sqrt((5 + 5 - 1) / 5)
          = H_m × sqrt(1.8)
          ≈ 0.037947332

    Step 4 — adjusted collateral value (CRR Art. 220):
        C* = 800,000 × (1 − 0.037947332) ≈ 769,642.13

    Step 5 — EAD (net exposure):
        E* = max(0, 1,000,000 − 769,642.13) ≈ 230,357.87

    Step 6 — SA risk weight (CRR Art. 122, unrated corporate):
        RW = 1.00

    Step 7 — RWA:
        RWA = 230,357.87

    Counterfactual (engine ignores revaluation_frequency_days — current bug):
        H = H_m ≈ 0.028284271  (Art. 226(1) scaling NOT applied)
        C* ≈ 777,372.58
        E* ≈ 222,627.42
        RWA ≈ 222,627.42   (delta ≈ −£7,730 vs correct value)

    The test fails today because the engine does not yet consume
    ``revaluation_frequency_days`` when building the adjusted haircut.

Isolation strategy:
    Primary assertions are on ead_final and rwa_final vs the post-fix values.
    A regression assertion confirms the pre-fix counterfactual no longer holds
    once the engine fix lands.

References:
    - CRR Art. 226(1): non-daily mark-to-market / non-daily-remargining scaling
    - CRR Art. 226(2): liquidation-period scaling formula
    - CRR Art. 224 Table 1: supervisory haircut schedule (corp_bond CQS 1, 1–5y)
    - CRR Art. 220: adjusted exposure / collateral value formula
    - CRR Art. 122: unrated corporate SA risk weight (100%)
    - tests/fixtures/p1_101/p1_101.py: fixture hand-calc constants
"""

from __future__ import annotations

import math as _math
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.conftest import find_exposure_rows, total_field
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_101"

# ---------------------------------------------------------------------------
# Hand-calc constants (mirrored from tests/fixtures/p1_101/p1_101.py)
# ---------------------------------------------------------------------------

_H_N: float = 0.04  # Base 10-day haircut: corp_bond CQS 1, 1–5y band
_T_M: int = 5  # SFT holding period (days)
_N: int = 5  # Revaluation frequency (days) — the new field

_H_M: float = _H_N * _math.sqrt(_T_M / 10)  # Art. 226(2)
_H_REVAL: float = _H_M * _math.sqrt((_N + _T_M - 1) / _T_M)  # Art. 226(1)

_MARKET_VALUE: float = 800_000.0
_DRAWN_AMOUNT: float = 1_000_000.0

_ADJUSTED_COLLATERAL: float = _MARKET_VALUE * (1.0 - _H_REVAL)
_EAD_EXPECTED: float = max(0.0, _DRAWN_AMOUNT - _ADJUSTED_COLLATERAL)
_RWA_EXPECTED: float = _EAD_EXPECTED  # RW = 1.00 for unrated corporate

# Counterfactual: Art. 226(1) scaling NOT applied (current engine behaviour)
_ADJUSTED_COLLATERAL_PREFIX: float = _MARKET_VALUE * (1.0 - _H_M)
_EAD_PREFIX: float = max(0.0, _DRAWN_AMOUNT - _ADJUSTED_COLLATERAL_PREFIX)
_RWA_PREFIX: float = _EAD_PREFIX

_REPORTING_DATE = date(2025, 12, 31)

# Tolerance: £0.50 on a 6-figure number (~0.0002% relative error)
_ABS_TOL = 0.50


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_reval() -> object:
    """Run the CRR SA pipeline with P1.101 scenario inputs.

    Loads counterparty, loan, and collateral from the p1_101 parquet fixtures.
    The collateral parquet carries the ``revaluation_frequency_days=5`` column
    that the engine-implementer will wire up for Art. 226(1) scaling.
    """
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )

    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    # Load collateral directly from the p1_101 directory — the main global
    # collateral fixture does NOT carry revaluation_frequency_days.
    collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

    bundle = make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        collateral=collateral,
    )

    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1101Art2261NonDailyRevaluation:
    """
    P1.101 — CRR Art. 226(1): non-daily collateral revaluation haircut scaling.

    When ``revaluation_frequency_days`` > 1 the engine must apply the Art. 226(1)
    formula to scale the liquidation-period haircut upwards:

        H = H_m × sqrt((N + T_m - 1) / T_m)

    where N = revaluation_frequency_days and T_m = holding-period days.

    For this scenario (corp_bond CQS 1, SFT 5-day, reval every 5 days):
        H_n = 4.0%  (base 10-day haircut per Art. 224 Table 1)
        H_m = 4.0% × sqrt(5/10) ≈ 2.8284%  (Art. 226(2))
        H   = H_m × sqrt(1.8)   ≈ 3.7947%  (Art. 226(1))
        EAD ≈ 230,357.87  (= 1M − 800k × (1 − H))
        RWA ≈ 230,357.87  (unrated corporate: RW = 100%)

    Pre-fix (Art. 226(1) ignored):
        H = H_m ≈ 2.8284%
        EAD ≈ 222,627.42   (the current engine output — test fails here)
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_reval()

    # ------------------------------------------------------------------
    # Primary assertions — EAD and RWA with Art. 226(1) scaling applied
    # ------------------------------------------------------------------

    def test_ead_final_reflects_art226_1_reval_scaling(self, result) -> None:
        """
        EAD must use the Art. 226(1) non-daily-revaluation adjusted haircut.

        Arrange: £1M repo loan (is_sft=True) to unrated corporate, £800k corp
                 bond collateral (CQS 1, residual 4.5y, reval_freq=5 days).
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 230,357.87 (Art. 226(1) scaling applied).

        Post-fix:  ead_final ≈ 230,357.87
        Pre-fix:   ead_final ≈ 222,627.42  (Art. 226(1) not applied)
        """
        # Arrange / Act (pipeline run happens in fixture)
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        # Assert
        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(_EAD_EXPECTED, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {_EAD_EXPECTED:,.2f}. "
            f"If ead_final ≈ {_EAD_PREFIX:,.2f} the engine is ignoring "
            f"revaluation_frequency_days (Art. 226(1) scaling not applied)."
        )

    def test_rwa_final_reflects_art226_1_reval_scaling(self, result) -> None:
        """
        RWA = EAD × 1.00 (unrated corporate CRR Art. 122) after Art. 226(1).

        Arrange/Act: as above.
        Assert:  rwa_final ≈ 230,357.87.
        """
        # Arrange / Act
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        # Assert
        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(_RWA_EXPECTED, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {_RWA_EXPECTED:,.2f}. "
            f"Pre-fix counterfactual is {_RWA_PREFIX:,.2f}."
        )

    # ------------------------------------------------------------------
    # Regression guard — pre-fix counterfactual must NOT match post-fix
    # ------------------------------------------------------------------

    def test_rwa_final_not_equal_to_prefix_counterfactual(self, result) -> None:
        """
        RWA must NOT equal the pre-fix counterfactual (≈ 222,627.42).

        This assertion proves Art. 226(1) scaling fired: when revaluation_
        frequency_days=5 the haircut is larger than H_m, so EAD and RWA are
        higher than the counterfactual where the field is ignored.

        Arrange/Act: as above.
        Assert:  rwa_final ≉ 222,627.42 (within 0.1% relative tolerance).
        """
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa != pytest.approx(_RWA_PREFIX, rel=1e-3), (
            f"rwa_final {rwa:,.2f} equals the pre-fix counterfactual {_RWA_PREFIX:,.2f}. "
            f"Art. 226(1) revaluation scaling appears to have NOT been applied."
        )

    # ------------------------------------------------------------------
    # Directional sanity checks
    # ------------------------------------------------------------------

    def test_ead_final_greater_than_prefix_counterfactual(self, result) -> None:
        """
        Post-fix EAD must exceed the pre-fix EAD.

        Art. 226(1) increases the haircut (larger H → lower C* → higher EAD).
        If ead_final <= pre-fix value the reval adjustment was not applied.

        Assert: ead_final > 222,627.42.
        """
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead > _EAD_PREFIX, (
            f"ead_final {ead:,.2f} <= pre-fix value {_EAD_PREFIX:,.2f}. "
            f"Expected post-fix EAD to be higher (Art. 226(1) increases the haircut)."
        )

    def test_ead_final_less_than_unprotected(self, result) -> None:
        """
        EAD must be less than the unprotected £1M drawn amount.

        Even with Art. 226(1) applied, 800k collateral still reduces net exposure.

        Assert: ead_final < 1,000,000.
        """
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead < _DRAWN_AMOUNT, (
            f"ead_final {ead:,.2f} is not less than unprotected {_DRAWN_AMOUNT:,.0f}. "
            f"Collateral appears to provide no EAD reduction."
        )

    def test_ead_final_greater_than_zero(self, result) -> None:
        """
        EAD must be positive — the £800k collateral does not fully cover the £1M loan.

        Assert: ead_final > 0.
        """
        rows = find_exposure_rows(result, "LOAN_CRM_REVAL")
        assert rows, "LOAN_CRM_REVAL not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead > 0.0, (
            f"ead_final {ead:,.2f} is not positive. "
            f"Collateral appears to have over-collateralised the exposure."
        )
