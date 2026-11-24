"""
P1.130 — Aggregator summary views must reflect post-floor RWA when output floor binds.

Bug under test:
    In OutputAggregator.aggregate(), ``summary_by_class`` and ``summary_by_approach``
    are generated from ``post_crm_detailed`` (line 133-134 of aggregator.py) BEFORE the
    portfolio-level output floor is applied to ``combined`` (line 198).  The floor modifies
    ``rwa_final`` in-place on ``combined``, but the summary LazyFrames were captured from the
    pre-floor snapshot.  As a result, both summary views report the un-floored total
    (~54.6m for this scenario) instead of the post-floor total (~181.25m).

Why the floor BINDS here (hand-calc):
    Three corporate counterparties (ALL UNRATED — no external CQS):
        LN-P1130-IRB-1: EAD=100m, F-IRB, PD=0.10%, LGD=40%  → IRB RWA ≈ 2.1m
        LN-P1130-IRB-2: EAD=100m, F-IRB, PD=0.15%, LGD=40%  → IRB RWA ≈ 2.5m
        LN-P1130-SA-1:  EAD=50m,  SA (unrated corporate → 100%) → RWA = 50m

    S-TREA (PS1/26 Art. 92(3A): the whole book, SA control included — P1.367):
        Unrated corporate → 100% SA RW.
        S-TREA = 100m + 100m + 50m = 250m; U-TREA ≈ 59.6m + 50m = 109.6m (measured).

    Floor threshold (72.5% × 250m) = 181.25m >> U-TREA ≈ 109.6m  →  floor BINDS
    (OF-ADJ, an EL-shortfall CET1 deduction, takes 1.25m off: 180m measured).
    Floored modelled RWA = 131.25m; SA control = 50m; total_rwa_post_floor = 181.25m.

Primary assertion:
    sum(summary_by_approach.total_rwa) == result.output_floor_summary.total_rwa_post_floor
    i.e., the summary views must reflect 181.25m, not the buggy ~54.6m.

References:
    - PRA PS1/26 Art. 92(2A): TREA = max(U-TREA, x × S-TREA + OF-ADJ)
    - PRA PS1/26 Art. 92(5): floor factor 72.5% for reporting dates >= 2030
    - tests/fixtures/p1_130/p1_130.py: fixture constants and builder
    - src/rwa_calc/engine/aggregator/aggregator.py: bug site (lines 133-134 vs 198)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from tests.fixtures.acceptance_pipeline import run_parquet_pipeline
from tests.fixtures.p1_130.p1_130 import (
    EXPECTED_FLOOR_THRESHOLD,
    EXPECTED_S_TREA,
    EXPECTED_TOTAL_RWA_POST_FLOOR,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_130"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_REL_TOL = 1e-6  # tight relative tolerance for sum comparisons

# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p1130():
    """Run the Basel 3.1 pipeline with P1.130 scenario inputs.

    Loads counterparty, loan, rating, and model_permission parquet fixtures.
    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().

    Config:
        - CalculationConfig.basel_3_1(reporting_date=date(2030, 1, 1))
          gives fully-phased 72.5% floor factor (PRA PS1/26 Art. 92(5)).
        - permission_mode=IRB so model_permissions rows route IRB counterparties
          through Foundation IRB.
        - OF-ADJ inputs are all zero so floor threshold = 0.725 × S-TREA exactly.
    """
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2030, 1, 1),
        permission_mode=PermissionMode.IRB,
        gcra_amount=0.0,
        sa_t2_credit=0.0,
        art_40_deductions=0.0,
    )
    return run_parquet_pipeline(_FIXTURES_DIR, config)


# ---------------------------------------------------------------------------
# P1.130 acceptance test
# ---------------------------------------------------------------------------


class TestP1130SummariesReflectPostFloorRWA:
    """
    P1.130: summary_by_approach and summary_by_class must reflect post-floor RWA.

    Scenario: two unrated F-IRB corporates (EAD 100m each) + one unrated SA corporate
    (EAD 50m).  Output floor 72.5% (reporting_date=2030-01-01, fully phased).
    S-TREA = 250m → floor threshold ≈ 181.25m >> U-TREA ≈ 109.6m → floor BINDS.
    total_rwa_post_floor ≈ 181.25m.

    Bug: today the summaries are built pre-floor from the un-floored combined frame,
    so they report ≈54.6m instead of 181.25m.  All five assertions below will fail with
    an AssertionError (not an import/collection error) until the aggregator is fixed.
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the full pipeline once and return the AggregatedResultBundle."""
        return _run_pipeline_p1130()

    # ------------------------------------------------------------------
    # GUARD: floor must genuinely bind (otherwise the remaining
    # assertions are vacuous).
    # ------------------------------------------------------------------

    def test_p1_130_guard_floor_is_applicable_and_binding(self, result) -> None:
        """
        Guard: output_floor_summary must exist and portfolio_floor_binding must be True.

        If this guard fails the scenario is broken (fixture / config problem),
        not a bug in the summaries.

        Arrange: P1.130 fixtures + Basel 3.1 config, reporting_date=2030-01-01.
        Act:     full pipeline run.
        Assert:  output_floor_summary is not None; portfolio_floor_binding is True.
        """
        # Arrange / Act — via fixture

        # Assert — guard
        assert result.output_floor_summary is not None, (
            "P1.130: output_floor_summary must not be None for Basel 3.1 with floor-applicable config. "
            "Check that is_floor_applicable() returns True for default institution_type/reporting_basis."
        )
        assert result.output_floor_summary.portfolio_floor_binding is True, (
            f"P1.130: floor must bind for unrated F-IRB corporates. "
            f"u_trea={result.output_floor_summary.u_trea:,.0f}, "
            f"floor_threshold={result.output_floor_summary.floor_threshold:,.0f}. "
            f"Expected floor_threshold ≈ {EXPECTED_FLOOR_THRESHOLD:,.0f} >> u_trea ≈ 109.6m."
        )

    def test_p1_130_guard_s_trea_equals_250m(self, result) -> None:
        """
        Guard: S-TREA must equal 250m (unrated corporates → 100% SA RW, plus the
        50m SA control, which PS1/26 Art. 92(3A) puts in S-TREA too — P1.367).

        If S-TREA is wrong the floor threshold is wrong; this guard isolates
        the fixture data quality from the summary-level bug.

        Arrange: two IRB corporates at 100m EAD each, both unrated externally.
        Act:     full pipeline.
        Assert:  output_floor_summary.s_trea ≈ 250,000,000.
        """
        assert result.output_floor_summary is not None

        assert result.output_floor_summary.s_trea == pytest.approx(EXPECTED_S_TREA, rel=0.01), (
            f"P1.130: S-TREA should be {EXPECTED_S_TREA:,.0f} (two 100m unrated corporates × 100% "
            "RW plus the 50m SA control). "
            f"Got {result.output_floor_summary.s_trea:,.0f}. "
            "If S-TREA ≠ 250m check that the IRB counterparties have no external CQS "
            "(cqs=null → unrated → 100% SA RW under PS1/26 Art. 122(2) Table 6)."
        )

    # ------------------------------------------------------------------
    # PRIMARY: summary totals must equal total_rwa_post_floor
    # ------------------------------------------------------------------

    def test_p1_130_summary_by_approach_total_equals_post_floor(self, result) -> None:
        """
        PRIMARY: sum(summary_by_approach.total_rwa) == output_floor_summary.total_rwa_post_floor.

        BUG SITE: summary_by_approach is built from post_crm_detailed BEFORE the floor
        is applied (aggregator.py line 134 vs line 198).  The summaries therefore
        reflect the un-floored IRB RWA (~4.6m) + SA RWA (50m) ≈ 54.6m, not the
        floored total ≈ 181.25m.

        This test FAILS pre-fix because:
            sum(summary_by_approach.total_rwa) ≈ 54,600,000
            output_floor_summary.total_rwa_post_floor ≈ 181,250,000

        Arrange: P1.130 fixtures with floor-binding F-IRB + SA setup.
        Act:     full pipeline (uses class-scoped result fixture).
        Assert:  summary_by_approach total ≈ 181.25m (post-floor).
        """
        # Arrange
        assert result.output_floor_summary is not None
        assert result.summary_by_approach is not None, (
            "P1.130: summary_by_approach must not be None"
        )

        # Act
        summary_df = result.summary_by_approach.collect()
        summary_total = summary_df["total_rwa"].sum()
        expected_total = result.output_floor_summary.total_rwa_post_floor

        # Assert — PRIMARY
        assert summary_total == pytest.approx(expected_total, rel=_REL_TOL), (
            f"P1.130 BUG: summary_by_approach.total_rwa ({summary_total:,.0f}) "
            f"must equal output_floor_summary.total_rwa_post_floor ({expected_total:,.0f}). "
            f"Shortfall/delta: {expected_total - summary_total:,.0f}. "
            "The summary is built pre-floor; it reflects the un-floored modelled RWA "
            "instead of the floored total. "
            f"Expected post-floor total ≈ {EXPECTED_TOTAL_RWA_POST_FLOOR:,.0f}."
        )

    def test_p1_130_summary_by_class_total_equals_post_floor(self, result) -> None:
        """
        PRIMARY: sum(summary_by_class.total_rwa) == output_floor_summary.total_rwa_post_floor.

        Same bug as the approach summary: both views are generated from pre-floor data.

        This test FAILS pre-fix because:
            sum(summary_by_class.total_rwa) ≈ 54,600,000
            output_floor_summary.total_rwa_post_floor ≈ 181,250,000

        Arrange: P1.130 fixtures with floor-binding F-IRB + SA setup.
        Act:     full pipeline.
        Assert:  summary_by_class total ≈ 181.25m (post-floor).
        """
        # Arrange
        assert result.output_floor_summary is not None
        assert result.summary_by_class is not None, "P1.130: summary_by_class must not be None"

        # Act
        summary_df = result.summary_by_class.collect()
        summary_total = summary_df["total_rwa"].sum()
        expected_total = result.output_floor_summary.total_rwa_post_floor

        # Assert — PRIMARY
        assert summary_total == pytest.approx(expected_total, rel=_REL_TOL), (
            f"P1.130 BUG: summary_by_class.total_rwa ({summary_total:,.0f}) "
            f"must equal output_floor_summary.total_rwa_post_floor ({expected_total:,.0f}). "
            f"Shortfall/delta: {expected_total - summary_total:,.0f}. "
            "The summary is built pre-floor; it reflects the un-floored modelled RWA "
            "instead of the floored total. "
            f"Expected post-floor total ≈ {EXPECTED_TOTAL_RWA_POST_FLOOR:,.0f}."
        )

    # ------------------------------------------------------------------
    # RECONCILIATION: summary totals must equal results frame total
    # ------------------------------------------------------------------

    def test_p1_130_results_frame_total_equals_post_floor(self, result) -> None:
        """
        RECONCILIATION: sum(results['rwa_final']) == output_floor_summary.total_rwa_post_floor.

        The results LazyFrame (result.results) is the floored combined frame.
        It should reflect the post-floor rwa_final values.  This assertion checks
        that the results frame itself is correct (not a pre-floor snapshot).

        If this passes but the summary assertions fail, the bug is confirmed to be
        exclusively in the summary generation (summaries are pre-floor snapshots).

        Arrange: P1.130 fixtures with floor-binding F-IRB + SA setup.
        Act:     collect result.results['rwa_final'] and sum.
        Assert:  results total ≈ 181.25m.
        """
        # Arrange
        assert result.output_floor_summary is not None

        # Act
        results_df = result.results.collect()
        results_total = results_df["rwa_final"].sum()
        expected_total = result.output_floor_summary.total_rwa_post_floor

        # Assert — RECONCILIATION
        assert results_total == pytest.approx(expected_total, rel=_REL_TOL), (
            f"P1.130: result.results['rwa_final'] sum ({results_total:,.0f}) "
            f"must equal output_floor_summary.total_rwa_post_floor ({expected_total:,.0f}). "
            f"Delta: {expected_total - results_total:,.0f}."
        )

    # ------------------------------------------------------------------
    # UNDERSTATEMENT-CLOSED: summary must strictly exceed un-floored total
    # ------------------------------------------------------------------

    def test_p1_130_shortfall_is_reflected_in_summary(self, result) -> None:
        """
        UNDERSTATEMENT-CLOSED: the summary total must strictly exceed floored_modelled_rwa.

        This asserts the specific bug: the shortfall (floor add-on) must appear in the
        summary view.  floored_modelled_rwa = 131.25m (the modelled rows' share of
        max(u_trea, floor_threshold) = 181.25m); sa_rwa_total = 50m;
        total_rwa_post_floor = 181.25m.

        Post-fix invariant:
            sum(summary_by_approach.total_rwa) - floored_modelled_rwa == sa_rwa_total

        Pre-fix (buggy):
            summary_total ≈ 54.6m < floored_modelled_rwa + sa_rwa_total  →  shortfall NOT
            reflected.

        This test FAILED before P1.130 because the summary total (≈54.6m) was less
        than the post-floor total — the add-on was entirely absent from the summary.

        Arrange: P1.130 fixtures.
        Act:     full pipeline.
        Assert:  summary total − floored_modelled_rwa ≈ sa_rwa_total (50m).
        """
        # Arrange
        assert result.output_floor_summary is not None
        assert result.summary_by_approach is not None

        # Act
        summary_df = result.summary_by_approach.collect()
        summary_total = summary_df["total_rwa"].sum()
        floor_summary = result.output_floor_summary

        floored_modelled = floor_summary.floored_modelled_rwa  # = 131.25m
        sa_rwa_total = floor_summary.sa_rwa_total  # = 50m

        # Assert — UNDERSTATEMENT-CLOSED:
        # summary total should equal floored_modelled + SA = 181.25m
        assert summary_total == pytest.approx(floored_modelled + sa_rwa_total, rel=_REL_TOL), (
            f"P1.130 BUG: summary_by_approach total ({summary_total:,.0f}) should equal "
            f"floored_modelled_rwa ({floored_modelled:,.0f}) + sa_rwa_total ({sa_rwa_total:,.0f}) "
            f"= {floored_modelled + sa_rwa_total:,.0f}. "
            f"Actual delta: {(floored_modelled + sa_rwa_total) - summary_total:,.0f}. "
            "The shortfall (floor add-on) is not reflected in the summary view. "
            f"Expected shortfall ≈ {floor_summary.shortfall:,.0f}."
        )
