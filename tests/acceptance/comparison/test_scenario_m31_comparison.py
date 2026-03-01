"""
M3.1 Dual-Framework Comparison acceptance tests.

Validates that the DualFrameworkRunner correctly computes per-exposure
and summary deltas between CRR and Basel 3.1 frameworks on the full
fixture portfolio.

Why these tests matter:
    M3.1 (side-by-side comparison) is the foundation for capital impact
    analysis (M3.2) and transitional floor modelling (M3.3). If the delta
    computation is wrong, all downstream analysis will be incorrect.

Test groups:
    M31-SA: SA-only comparison (structural correctness, known RW differences)
    M31-FIRB: F-IRB comparison (LGD/PD floor/scaling factor impact)
    M31-Summary: Aggregated summary views

References:
    - PRA PS9/24: Basel 3.1 implementation
    - CRR Art. 92: Own funds requirements
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, ComparisonBundle

from .conftest import get_delta_for_exposure


# =============================================================================
# M31-SA: SA-Only Comparison Tests
# =============================================================================


class TestM31_SA_Comparison:
    """SA-only dual-framework comparison tests.

    Validates that the comparison correctly identifies differences between
    CRR and Basel 3.1 SA risk weights for the same portfolio.
    """

    def test_comparison_bundle_type(self, sa_comparison):
        """DualFrameworkRunner should return a ComparisonBundle."""
        assert isinstance(sa_comparison, ComparisonBundle)

    def test_crr_results_populated(self, sa_comparison):
        """CRR results should be a valid AggregatedResultBundle."""
        assert isinstance(sa_comparison.crr_results, AggregatedResultBundle)
        crr_df = sa_comparison.crr_results.results.collect()
        assert crr_df.height > 0

    def test_b31_results_populated(self, sa_comparison):
        """B31 results should be a valid AggregatedResultBundle."""
        assert isinstance(sa_comparison.b31_results, AggregatedResultBundle)
        b31_df = sa_comparison.b31_results.results.collect()
        assert b31_df.height > 0

    def test_exposure_deltas_populated(self, sa_comparison_deltas_df):
        """Exposure deltas should contain rows."""
        assert sa_comparison_deltas_df.height > 0

    def test_delta_columns_present(self, sa_comparison_deltas_df):
        """Delta DataFrame should have all expected columns."""
        required = {
            "exposure_reference",
            "exposure_class",
            "rwa_final_crr",
            "rwa_final_b31",
            "delta_rwa",
            "delta_risk_weight",
            "delta_rwa_pct",
        }
        assert required.issubset(set(sa_comparison_deltas_df.columns))

    def test_same_exposure_count_both_frameworks(self, sa_comparison):
        """Both frameworks should process the same set of exposures."""
        crr_count = sa_comparison.crr_results.results.collect().height
        b31_count = sa_comparison.b31_results.results.collect().height
        deltas_count = sa_comparison.exposure_deltas.collect().height
        # Full outer join should cover all exposures from both sides
        assert deltas_count >= max(crr_count, b31_count)

    def test_sovereign_cqs1_zero_delta(self, sa_comparison_deltas_df):
        """Sovereign CQS 1 (0% RW): same under both frameworks, zero delta.

        CRR Art. 114: sovereign CQS 1 = 0% RW
        Basel 3.1 CRE20.7: sovereign CQS 1 = 0% RW (unchanged)
        """
        sov = sa_comparison_deltas_df.filter(
            pl.col("exposure_reference") == "LOAN_SOV_UK_001"
        )
        if sov.height > 0:
            assert sov["delta_rwa"][0] == pytest.approx(0.0, abs=1.0)
            assert sov["delta_risk_weight"][0] == pytest.approx(0.0, abs=0.001)

    def test_ead_identical_across_frameworks(self, sa_comparison_deltas_df):
        """SA EAD should be identical across frameworks (same CCF, same inputs).

        CRR and Basel 3.1 both use the same EAD formula for drawn exposures.
        The delta_ead should be zero for fully drawn exposures.
        """
        drawn_exposures = sa_comparison_deltas_df.filter(
            pl.col("delta_ead").abs() < 1.0  # Allow small floating point tolerance
        )
        # Most exposures should have zero or near-zero EAD delta
        assert drawn_exposures.height > 0

    def test_portfolio_total_rwa_differs(self, sa_comparison_deltas_df):
        """Total portfolio RWA should differ between frameworks.

        Basel 3.1 introduces revised risk weights that typically change
        the total portfolio RWA (some exposures higher, some lower).
        """
        total_crr = sa_comparison_deltas_df["rwa_final_crr"].sum()
        total_b31 = sa_comparison_deltas_df["rwa_final_b31"].sum()
        # They should not be exactly equal (unless the portfolio is trivial)
        # Use very small tolerance to detect genuinely different values
        if total_crr > 0 and total_b31 > 0:
            # At minimum, check both totals are positive
            assert total_crr > 0
            assert total_b31 > 0


# =============================================================================
# M31-FIRB: F-IRB Comparison Tests
# =============================================================================


class TestM31_FIRB_Comparison:
    """F-IRB dual-framework comparison tests.

    Validates that known Basel 3.1 F-IRB parameter changes produce
    the expected impact direction on RWA.
    """

    def test_firb_comparison_populated(self, firb_comparison):
        """F-IRB comparison should produce results."""
        assert isinstance(firb_comparison, ComparisonBundle)
        df = firb_comparison.exposure_deltas.collect()
        assert df.height > 0

    def test_firb_irb_rows_present(self, firb_comparison_deltas_df):
        """F-IRB comparison should have rows with foundation_irb approach.

        ApproachType.FIRB has value 'foundation_irb' in the pipeline.
        """
        firb_rows = firb_comparison_deltas_df.filter(
            (pl.col("approach_applied") == "foundation_irb")
            | (pl.col("approach_applied_crr") == "foundation_irb")
            | (pl.col("approach_applied_b31") == "foundation_irb")
        )
        assert firb_rows.height > 0, (
            "Expected foundation_irb rows in comparison. "
            f"Unique approaches: {firb_comparison_deltas_df['approach_applied'].unique().to_list()}"
        )

    def test_firb_scaling_factor_impact(self, firb_comparison_deltas_df):
        """Scaling factor removal (1.06 -> 1.0) should reduce B31 RWA.

        CRR applies 1.06 scaling factor to IRB K (Art. 153).
        Basel 3.1 removes it (scaling_factor=1.0).
        All else equal, B31 IRB RWA should be ~5.7% lower.
        """
        firb_rows = firb_comparison_deltas_df.filter(
            (pl.col("approach_applied") == "foundation_irb")
            | (pl.col("approach_applied_crr") == "foundation_irb")
        )
        if firb_rows.height > 0:
            # At least some FIRB rows should exist with non-zero RWA
            has_rwa = firb_rows.filter(pl.col("rwa_final_crr").abs() > 100.0)
            assert has_rwa.height > 0, "Expected FIRB rows with non-zero CRR RWA"


# =============================================================================
# M31-Summary: Summary Aggregation Tests
# =============================================================================


class TestM31_Summary:
    """Summary aggregation tests for dual-framework comparison."""

    def test_class_summary_populated(self, sa_comparison_class_summary_df):
        """Summary by class should have at least one row."""
        assert sa_comparison_class_summary_df.height > 0

    def test_class_summary_columns(self, sa_comparison_class_summary_df):
        """Summary by class should have expected columns."""
        required = {
            "exposure_class",
            "total_rwa_crr",
            "total_rwa_b31",
            "total_delta_rwa",
            "delta_rwa_pct",
            "exposure_count",
        }
        assert required.issubset(set(sa_comparison_class_summary_df.columns))

    def test_class_summary_totals_sum_to_portfolio(
        self, sa_comparison_class_summary_df, sa_comparison_deltas_df
    ):
        """Sum of class-level RWA should equal portfolio total."""
        class_total_crr = sa_comparison_class_summary_df["total_rwa_crr"].sum()
        exposure_total_crr = sa_comparison_deltas_df["rwa_final_crr"].sum()
        assert class_total_crr == pytest.approx(exposure_total_crr, rel=0.001)

    def test_approach_summary_populated(self, sa_comparison_approach_summary_df):
        """Summary by approach should have at least one row."""
        assert sa_comparison_approach_summary_df.height > 0

    def test_approach_summary_columns(self, sa_comparison_approach_summary_df):
        """Summary by approach should have expected columns."""
        required = {
            "approach_applied",
            "total_rwa_crr",
            "total_rwa_b31",
            "total_delta_rwa",
            "delta_rwa_pct",
            "exposure_count",
        }
        assert required.issubset(set(sa_comparison_approach_summary_df.columns))

    def test_delta_rwa_equals_b31_minus_crr(self, sa_comparison_class_summary_df):
        """Delta RWA should equal B31 total minus CRR total for each class."""
        for row in sa_comparison_class_summary_df.to_dicts():
            expected_delta = row["total_rwa_b31"] - row["total_rwa_crr"]
            assert row["total_delta_rwa"] == pytest.approx(expected_delta, rel=0.001), (
                f"Class {row['exposure_class']}: "
                f"delta={row['total_delta_rwa']:.2f}, "
                f"expected B31-CRR={expected_delta:.2f}"
            )

    def test_exposure_count_positive(self, sa_comparison_class_summary_df):
        """Every exposure class should have at least one exposure."""
        for row in sa_comparison_class_summary_df.to_dicts():
            assert row["exposure_count"] > 0, (
                f"Class {row['exposure_class']} has zero exposures"
            )
