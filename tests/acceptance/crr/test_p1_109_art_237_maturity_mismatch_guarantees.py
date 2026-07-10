"""
P1.109: CRR Art. 237/238/239(3) maturity mismatch on unfunded protection.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a full-tenor guarantee (t == T) produces no mismatch adjustment and
  applies the guarantor's risk weight at face value: RWA = 200,000.
- Confirm that a maturity-mismatched guarantee (t < T) triggers the Art. 239(3)
  scaling formula, reducing the covered portion GA and blending borrower and
  guarantor risk weights.

Two scenarios (one pipeline run per parametrised case):

    GUAR_FULL_P1109: original_maturity_years=5.0, loan residual=5.0y
        t == T → no Art. 239(3) adjustment
        GA = 1,000,000  → RWA = 200,000

    GUAR_MM_P1109:   original_maturity_years=2.5, maturity_date=2028-07-01,
                     loan residual=5.0y
        CRR Art. 238(1): t is the RESIDUAL maturity of the credit protection,
        not its original maturity. GUAR_MM_P1109's maturity_date is 2028-07-01,
        and its Actual/365 residual from the 2026-01-01 reporting date straddles
        the 2028 leap year: 365 (2026) + 365 (2027) + 182 (2028-01-01 ->
        2028-07-01) = 912 days -> t = 912/365 = 2 + 182/365 = 2.4986301369863014y
        (fractionally short of the 2.5y `original_maturity_years` field).
        t < T=5.0y → Art. 239(3) applies:
            m  = (t − 0.25) / (5.0 − 0.25) ≈ 0.4733958183129056
            GA = 1,000,000 × m             ≈   473,395.8183129056
            guaranteed RWA   = GA × 0.20   ≈    94,679.1636625811
            unguaranteed RWA = (1,000,000 − GA) × 1.00 ≈ 526,604.1816870945
            total RWA                                  ≈ 621,283.3453496756

P1.219 fix note:
    Pre-P1.219, the CRM processor read `t` from the guarantee's
    `original_maturity_years` field (2.5y) rather than computing the residual
    maturity to the guarantee's `maturity_date` per Art. 238(1). Because
    GUAR_MM_P1109's `maturity_date` residual (2.4986301369863014y) differs
    fractionally from `original_maturity_years` (2.5y exactly, across the 2028
    leap year), the pre-fix and post-fix RWA/GA figures diverge in the 5th
    significant digit. This test is re-pinned to the residual-based (post-fix)
    figures; see the constants block below for the derivation.

References:
    - CRR Art. 237(2)(a): minimum residual maturity of protection >= 1 year
    - CRR Art. 238(1): maturity of credit protection (t = residual maturity)
    - CRR Art. 239(3): maturity mismatch adjustment formula
    - tests/fixtures/p1_109/p1_109.py: fixture builder and scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.crr.conftest import (
    aggregate_sa_rows_by_parent,
    run_single_guarantee_sa_pipeline,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_109" / "data"

# ---------------------------------------------------------------------------
# Constants from the fixture builder
# ---------------------------------------------------------------------------

from tests.fixtures.p1_109.p1_109 import (  # noqa: E402
    GUAR_FULL_REF,
    GUAR_MM_REF,
    GUARANTOR_REF,
    LOAN_EAD,
    LOAN_REF,
)

# ---------------------------------------------------------------------------
# Reporting date: 2026-01-01 == LOAN_VALUE_DATE, so loan residual = exactly 5y.
# ---------------------------------------------------------------------------
_REPORTING_DATE = date(2026, 1, 1)

# ---------------------------------------------------------------------------
# Expected outputs (hand-calculated per architect proposal)
# ---------------------------------------------------------------------------

# Scenario A — full-tenor guarantee (no mismatch)
_EXPECTED_A_EAD = 1_000_000.0
_EXPECTED_A_GUARANTEED_PORTION = 1_000_000.0
_EXPECTED_A_UNGUARANTEED_PORTION = 0.0
_EXPECTED_A_RWA = 200_000.0

# ---------------------------------------------------------------------------
# Scenario B — maturity-mismatched guarantee (Art. 239(3))
#
# CRR Art. 238(1): t is the RESIDUAL maturity of the credit protection, not its
# original maturity. GUAR_MM_P1109 carries original_maturity_years=2.5 *and* a
# maturity_date of 2028-07-01; the Actual/365 residual from the 2026-01-01
# reporting date straddles the 2028 leap year, so it comes out fractionally
# short of 2.5y: 365 (2026) + 365 (2027) + 182 (2028-01-01 -> 2028-07-01) = 912
# days -> t = 912 / 365 years.
#
# P1.219 corrected the engine to compute t from this residual (Art. 238(1))
# rather than reading original_maturity_years directly. The constants below
# are derived from that residual rather than pasted as magic literals, so they
# stay self-documenting and remain correct if the fixture's reporting-date
# arithmetic ever changes.
# ---------------------------------------------------------------------------
_GUAR_MM_RESIDUAL_MATURITY_YEARS = 2.0 + 182.0 / 365.0  # t ≈ 2.4986301369863014y
_LOAN_RESIDUAL_MATURITY_YEARS = 5.0  # T
_MATURITY_FLOOR_YEARS = 0.25  # Art. 239(3) floor

_MATURITY_MISMATCH_FACTOR = (_GUAR_MM_RESIDUAL_MATURITY_YEARS - _MATURITY_FLOOR_YEARS) / (
    _LOAN_RESIDUAL_MATURITY_YEARS - _MATURITY_FLOOR_YEARS
)  # m = (t − 0.25) / (T − 0.25) ≈ 0.4733958183129056

_GA_MISMATCH_RESIDUAL = LOAN_EAD * _MATURITY_MISMATCH_FACTOR  # ≈ 473,395.8183129056
_GA_UNGUARANTEED_RESIDUAL = LOAN_EAD - _GA_MISMATCH_RESIDUAL  # ≈ 526,604.1816870945

_EXPECTED_B_EAD = 1_000_000.0
_EXPECTED_B_GUARANTEED_PORTION = _GA_MISMATCH_RESIDUAL  # ≈ 473,395.81831290555
_EXPECTED_B_UNGUARANTEED_PORTION = _GA_UNGUARANTEED_RESIDUAL  # ≈ 526,604.1816870945
_EXPECTED_B_RWA = (
    _GA_MISMATCH_RESIDUAL * 0.20 + _GA_UNGUARANTEED_RESIDUAL * 1.00
)  # ≈ 621,283.3453496756
_EXPECTED_B_EFFECTIVE_RW = _EXPECTED_B_RWA / _EXPECTED_B_EAD  # ≈ 0.6212833453496757


# ---------------------------------------------------------------------------
# Acceptance tests — P1.109 CRR Art. 239(3) maturity mismatch adjustment
# ---------------------------------------------------------------------------


class TestP1109Art237MaturityMismatchGuarantees:
    """
    P1.109: CRR Art. 239(3) — maturity mismatch reduces the covered portion GA
    when protection residual maturity t < exposure residual maturity T.

    Two scenarios driven by a class-scoped pipeline fixture each:
      - GUAR_FULL  (t == T = 5.0y): no mismatch → GA = 1,000,000 → RWA = 200,000
      - GUAR_MM    (residual t ≈ 2.4986301369863014y < T = 5.0y):
                   Art. 239(3) scaling → RWA ≈ 621,283.35
    """

    # -----------------------------------------------------------------------
    # Class-scoped pipeline results — one run per guarantee scenario
    # -----------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def guar_full_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1109 under GUAR_FULL_P1109 (5.0y, no mismatch).

        Aggregates all guarantee sub-rows by parent ref.
        """
        df = run_single_guarantee_sa_pipeline(_FIXTURES_DIR, _REPORTING_DATE, GUAR_FULL_REF)
        return aggregate_sa_rows_by_parent(df, LOAN_REF)

    @pytest.fixture(scope="class")
    def guar_mm_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1109 under GUAR_MM_P1109 (2.5y, mismatched).

        Aggregates all guarantee sub-rows by parent ref.
        """
        df = run_single_guarantee_sa_pipeline(_FIXTURES_DIR, _REPORTING_DATE, GUAR_MM_REF)
        return aggregate_sa_rows_by_parent(df, LOAN_REF)

    # -----------------------------------------------------------------------
    # Scenario A — GUAR_FULL (no mismatch) — should PASS today (regression pin)
    # -----------------------------------------------------------------------

    def test_p1_109_full_tenor_guarantee_ead_equals_loan_ead(self, guar_full_results: dict) -> None:
        """
        Full-tenor guarantee: aggregated ead_final == 1,000,000.

        Arrange: LOAN_001_P1109 (GBP 1M) + GUAR_FULL_P1109 (t=T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  total ead_final == 1,000,000 (no EAD change from guarantee).
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_A_EAD, rel=1e-6), (
            f"P1.109 GUAR_FULL: expected ead_final={_EXPECTED_A_EAD:,.0f}, "
            f"got {row['ead_final']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_covered_portion_equals_full_ead(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: guaranteed_portion == 1,000,000 (full coverage, no scaling).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion == 1,000,000.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["guaranteed_portion"] == pytest.approx(
            _EXPECTED_A_GUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_FULL: expected guaranteed_portion={_EXPECTED_A_GUARANTEED_PORTION:,.0f}, "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_unguaranteed_portion_is_zero(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: unguaranteed_portion == 0 (entire exposure is covered).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  unguaranteed_portion == 0.0.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["unguaranteed_portion"] == pytest.approx(
            _EXPECTED_A_UNGUARANTEED_PORTION, abs=1e-2
        ), (
            f"P1.109 GUAR_FULL: expected unguaranteed_portion=0.0, "
            f"got {row['unguaranteed_portion']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_rwa_equals_guarantor_rw_times_ead(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: rwa_final == 200,000 (guarantor CQS 1 at 20% × EAD 1M).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 200,000.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_A_RWA, rel=1e-6), (
            f"P1.109 GUAR_FULL: expected rwa_final={_EXPECTED_A_RWA:,.0f} "
            f"(guarantor 20% × 1,000,000 — no mismatch scaling), "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_guarantor_reference(self, guar_full_results: dict) -> None:
        """
        Full-tenor guarantee: guarantor_reference on the guaranteed sub-row == CP_GUARANTOR_P1109.

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109.
        Act:     full CRR SA pipeline.
        Assert:  guarantor_reference == 'CP_GUARANTOR_P1109'.

        This test should PASS today — retained as regression pin.
        """
        # Arrange / Act (fixture provides aggregated first-row values for non-additive fields)
        df = run_single_guarantee_sa_pipeline(_FIXTURES_DIR, _REPORTING_DATE, GUAR_FULL_REF)
        guaranteed_sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == LOAN_REF) & (pl.col("is_guaranteed") == True)  # noqa: E712
        )

        # Assert
        assert guaranteed_sub_rows.height > 0, (
            "Expected at least one guaranteed sub-row for GUAR_FULL_P1109"
        )
        assert guaranteed_sub_rows["guarantor_reference"][0] == GUARANTOR_REF, (
            f"P1.109 GUAR_FULL: expected guarantor_reference='{GUARANTOR_REF}', "
            f"got '{guaranteed_sub_rows['guarantor_reference'][0]}'"
        )

    # -----------------------------------------------------------------------
    # Scenario B — GUAR_MM (maturity mismatch), Art. 239(3) scaling
    #
    # P1.219 corrected the engine's `t` to the residual protection maturity
    # (Art. 238(1)) rather than the guarantee's `original_maturity_years` field.
    # GUAR_MM_P1109's residual t = 912/365 ≈ 2.4986301369863014y (fractionally
    # short of the 2.5y original_maturity_years, across the 2028 leap year) —
    # see the constants block above for the derivation.
    # -----------------------------------------------------------------------

    def test_p1_109_maturity_mismatch_ead_unchanged(self, guar_mm_results: dict) -> None:
        """
        Maturity-mismatched guarantee: total ead_final == 1,000,000 (EAD is not reduced).

        Arrange: LOAN_001_P1109 (GBP 1M, 5y) + GUAR_MM_P1109 (residual t < T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  total ead_final == 1,000,000 (Art. 239(3) scales GA, not EAD).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_B_EAD, rel=1e-6), (
            f"P1.109 GUAR_MM: expected ead_final={_EXPECTED_B_EAD:,.0f}, "
            f"got {row['ead_final']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_guaranteed_portion_is_scaled(
        self, guar_mm_results: dict
    ) -> None:
        """
        CRR Art. 239(3): maturity mismatch reduces guaranteed_portion below face value.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (residual t≈2.4986301369863014y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion ≈ 473,395.81831290555
                 (= 1,000,000 × (t − 0.25) / (5.0 − 0.25), t = residual maturity
                 per Art. 238(1)).

        Pre-P1.219, the engine read t from original_maturity_years (2.5y exactly)
        rather than the residual to maturity_date, applying the Art. 239(3) scaling
        factor (2.25 / 4.75) instead of the correct one (t-0.25) / 4.75.
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["guaranteed_portion"] == pytest.approx(
            _EXPECTED_B_GUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_MM: expected guaranteed_portion={_EXPECTED_B_GUARANTEED_PORTION:,.10f} "
            f"(Art. 239(3): 1,000,000 × (t−0.25)/(5.0−0.25), t=residual maturity), "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_unguaranteed_portion(self, guar_mm_results: dict) -> None:
        """
        CRR Art. 239(3): unguaranteed_portion == EAD − scaled GA.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (residual t≈2.4986301369863014y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  unguaranteed_portion ≈ 526,604.1816870945
                 (= 1,000,000 − 473,395.81831290555).

        Pre-P1.219, the engine returned unguaranteed_portion = 0.0 (treated the
        full face-value guarantee as 100% covering the exposure, ignoring the
        Art. 239(3) scaling).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["unguaranteed_portion"] == pytest.approx(
            _EXPECTED_B_UNGUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_MM: expected unguaranteed_portion={_EXPECTED_B_UNGUARANTEED_PORTION:,.10f} "
            f"(= EAD − scaled GA), "
            f"got {row['unguaranteed_portion']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_rwa_blends_borrower_and_guarantor_rw(
        self, guar_mm_results: dict
    ) -> None:
        """
        CRR Art. 239(3): total rwa_final blends guarantor RW on covered and borrower RW
        on uncovered portion.

        Arrange: LOAN_001_P1109 (corp CQS 4, 100% RW) + GUAR_MM_P1109 (inst CQS 1, 20% RW).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final ≈ 621,283.3453496756
                 (= 473,395.82 × 0.20 + 526,604.18 × 1.00).

        Pre-P1.219, the engine returned rwa_final = 200,000.0 (applied the full
        guarantee at face value, ignoring the Art. 239(3) scaling).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_B_RWA, rel=1e-6), (
            f"P1.109 GUAR_MM: expected rwa_final={_EXPECTED_B_RWA:,.10f} "
            f"(Art. 239(3): {_EXPECTED_B_GUARANTEED_PORTION:,.4f} × 0.20 + "
            f"{_EXPECTED_B_UNGUARANTEED_PORTION:,.4f} × 1.00), "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_effective_rw(self, guar_mm_results: dict) -> None:
        """
        CRR Art. 239(3): effective post-CRM risk weight == rwa_final / ead_final ≈ 0.621283.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (residual t≈2.4986301369863014y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final / ead_final ≈ 0.6212833453496757.

        Pre-P1.219, rwa_final = 200,000 → effective RW = 0.20 (guarantee applied
        at face value, no Art. 239(3) scaling).
        """
        # Arrange
        row = guar_mm_results
        ead = row["ead_final"]
        rwa = row["rwa_final"]

        # Assert
        effective_rw = rwa / ead
        assert effective_rw == pytest.approx(_EXPECTED_B_EFFECTIVE_RW, rel=1e-6), (
            f"P1.109 GUAR_MM: expected effective RW = rwa_final/ead_final "
            f"≈ {_EXPECTED_B_EFFECTIVE_RW:.10f}, "
            f"got {effective_rw:.10f} (rwa={rwa:,.2f}, ead={ead:,.2f})"
        )

    def test_p1_109_maturity_mismatch_guarantor_reference(self, guar_mm_results: dict) -> None:
        """
        Maturity-mismatched guarantee: guaranteed sub-row has guarantor_reference == CP_GUARANTOR_P1109.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109.
        Act:     full CRR SA pipeline.
        Assert:  the guaranteed sub-row has guarantor_reference == 'CP_GUARANTOR_P1109'.

        This sub-assertion should pass even before the mismatch fix is applied.
        """
        # Arrange / Act
        df = run_single_guarantee_sa_pipeline(_FIXTURES_DIR, _REPORTING_DATE, GUAR_MM_REF)
        guaranteed_sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == LOAN_REF) & (pl.col("is_guaranteed") == True)  # noqa: E712
        )

        # Assert
        assert guaranteed_sub_rows.height > 0, (
            "Expected at least one guaranteed sub-row for GUAR_MM_P1109"
        )
        assert guaranteed_sub_rows["guarantor_reference"][0] == GUARANTOR_REF, (
            f"P1.109 GUAR_MM: expected guarantor_reference='{GUARANTOR_REF}', "
            f"got '{guaranteed_sub_rows['guarantor_reference'][0]}'"
        )
