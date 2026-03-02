"""
Acceptance tests for M3.2 Capital Impact Analysis.

Validates the CapitalImpactAnalyzer's driver-level attribution of
CRR vs Basel 3.1 RWA deltas using the standard fixture portfolio.

Tests verify:
- Additivity invariant: 4 drivers sum to total delta for every exposure
- SA exposures: zero scaling/floor impact, supporting factor and methodology
- IRB exposures: negative scaling impact, supporting factor, methodology, floor
- Portfolio waterfall: 4 steps, cumulative ends at B31 RWA
- Summary aggregation: driver totals by class and approach

Why these tests matter:
    Capital impact analysis is the primary analytical output for Basel 3.1
    transition planning. These acceptance tests validate that the waterfall
    decomposition is mathematically correct (additivity) and directionally
    correct (scaling removal reduces RWA, supporting factor removal increases
    it) on realistic portfolio data. Incorrect attribution would lead to
    wrong capital planning decisions.

References:
    - CRR Art. 153(1): 1.06 scaling factor for IRB
    - CRR Art. 501/501a: SME and infrastructure supporting factors
    - PRA PS9/24 Ch.12: Output floor
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CapitalImpactBundle


# =============================================================================
# M3.2 SA Comparison — Capital Impact
# =============================================================================


class TestM32_SA_Attribution:
    """SA exposures should have no scaling or floor impact."""

    def test_m32_sa_attribution_has_exposures(
        self, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-S1: Attribution should contain at least one exposure."""
        assert sa_impact_attribution_df.height > 0

    def test_m32_sa_required_columns_present(
        self, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-S2: Attribution must have all driver columns."""
        required = {
            "exposure_reference", "exposure_class", "approach_applied",
            "rwa_crr", "rwa_b31", "delta_rwa",
            "scaling_factor_impact", "supporting_factor_impact",
            "output_floor_impact", "methodology_impact",
        }
        assert required.issubset(set(sa_impact_attribution_df.columns))

    def test_m32_sa_scaling_impact_is_zero(
        self, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-S3: SA exposures have no 1.06 scaling factor — impact must be 0."""
        scaling_total = sa_impact_attribution_df["scaling_factor_impact"].sum()
        assert scaling_total == pytest.approx(0.0, abs=1.0)

    def test_m32_sa_floor_impact_is_zero(
        self, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-S4: SA exposures are not subject to the output floor."""
        floor_total = sa_impact_attribution_df["output_floor_impact"].sum()
        assert floor_total == pytest.approx(0.0, abs=1.0)

    def test_m32_sa_additivity_invariant(
        self, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-S5: For every SA exposure, 4 drivers must sum to delta_rwa."""
        for row in sa_impact_attribution_df.to_dicts():
            driver_sum = (
                row["scaling_factor_impact"]
                + row["supporting_factor_impact"]
                + row["output_floor_impact"]
                + row["methodology_impact"]
            )
            assert driver_sum == pytest.approx(row["delta_rwa"], abs=1.0), (
                f"Additivity failed for SA exposure {row['exposure_reference']}: "
                f"drivers sum to {driver_sum}, delta is {row['delta_rwa']}"
            )


# =============================================================================
# M3.2 F-IRB Comparison — Capital Impact
# =============================================================================


class TestM32_FIRB_Attribution:
    """F-IRB exposures should decompose into all 4 driver categories."""

    def test_m32_firb_attribution_has_exposures(
        self, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-F1: Attribution should contain at least one exposure."""
        assert firb_impact_attribution_df.height > 0

    def test_m32_firb_scaling_impact_is_negative(
        self, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-F2: Removing the 1.06x scaling factor should reduce total RWA.

        CRR Art. 153(1) applies a 1.06 supervisory scaling factor to IRB
        capital requirements. Basel 3.1 removes this. The net effect is
        a reduction of approximately 5.66% of CRR IRB RWA.
        """
        irb_rows = firb_impact_attribution_df.filter(
            pl.col("approach_applied").is_in(["foundation_irb", "advanced_irb", "FIRB"])
        )
        if irb_rows.height > 0:
            total_scaling = irb_rows["scaling_factor_impact"].sum()
            assert total_scaling < 0, (
                f"IRB scaling impact should be negative (removing 1.06x reduces RWA), "
                f"got {total_scaling}"
            )

    def test_m32_firb_additivity_invariant(
        self, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-F3: For every exposure, 4 drivers must sum to delta_rwa."""
        for row in firb_impact_attribution_df.to_dicts():
            driver_sum = (
                row["scaling_factor_impact"]
                + row["supporting_factor_impact"]
                + row["output_floor_impact"]
                + row["methodology_impact"]
            )
            assert driver_sum == pytest.approx(row["delta_rwa"], abs=1.0), (
                f"Additivity failed for {row['exposure_reference']}: "
                f"drivers sum to {driver_sum}, delta is {row['delta_rwa']}"
            )

    def test_m32_firb_sa_exposures_have_zero_scaling(
        self, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-F4: Even in F-IRB comparison, SA-approach rows get zero scaling."""
        sa_rows = firb_impact_attribution_df.filter(
            pl.col("approach_applied") == "standardised"
        )
        if sa_rows.height > 0:
            total = sa_rows["scaling_factor_impact"].sum()
            assert total == pytest.approx(0.0, abs=1.0)

    def test_m32_firb_floor_impact_non_negative(
        self, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-F5: Output floor can only add RWA, never reduce it."""
        min_floor = firb_impact_attribution_df["output_floor_impact"].min()
        assert min_floor >= -1.0  # Tolerance for floating point


# =============================================================================
# M3.2 Waterfall Tests
# =============================================================================


class TestM32_Waterfall:
    """Portfolio-level waterfall from CRR baseline to B31 total."""

    def test_m32_waterfall_has_four_steps(
        self, sa_impact_waterfall_df: pl.DataFrame
    ) -> None:
        """M3.2-W1: Waterfall should have exactly 4 driver steps."""
        assert sa_impact_waterfall_df.height == 4

    def test_m32_waterfall_steps_sequential(
        self, sa_impact_waterfall_df: pl.DataFrame
    ) -> None:
        """M3.2-W2: Waterfall steps should be numbered 1-4."""
        assert sa_impact_waterfall_df["step"].to_list() == [1, 2, 3, 4]

    def test_m32_waterfall_has_driver_labels(
        self, sa_impact_waterfall_df: pl.DataFrame
    ) -> None:
        """M3.2-W3: Each step should have a descriptive driver label."""
        drivers = sa_impact_waterfall_df["driver"].to_list()
        assert all(len(d) > 5 for d in drivers)

    def test_m32_sa_waterfall_cumulative_matches_b31(
        self, sa_impact_waterfall_df: pl.DataFrame, sa_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-W4: Final cumulative RWA should equal total B31 RWA."""
        total_b31 = sa_impact_attribution_df["rwa_b31"].sum()
        final_cumulative = sa_impact_waterfall_df["cumulative_rwa"][-1]
        assert final_cumulative == pytest.approx(total_b31, rel=0.001)

    def test_m32_firb_waterfall_cumulative_matches_b31(
        self, firb_impact_waterfall_df: pl.DataFrame, firb_impact_attribution_df: pl.DataFrame
    ) -> None:
        """M3.2-W5: F-IRB waterfall final cumulative should equal total B31 RWA."""
        total_b31 = firb_impact_attribution_df["rwa_b31"].sum()
        final_cumulative = firb_impact_waterfall_df["cumulative_rwa"][-1]
        assert final_cumulative == pytest.approx(total_b31, rel=0.001)

    def test_m32_firb_waterfall_scaling_step_negative(
        self, firb_impact_waterfall_df: pl.DataFrame
    ) -> None:
        """M3.2-W6: Scaling factor removal step should have negative impact."""
        scaling_row = firb_impact_waterfall_df.filter(
            pl.col("driver").str.contains("Scaling")
        )
        if scaling_row.height > 0:
            assert scaling_row["impact_rwa"][0] < 0


# =============================================================================
# M3.2 Summary Tests
# =============================================================================


class TestM32_Summary:
    """Attribution summary aggregation tests."""

    def test_m32_sa_summary_by_class_has_rows(
        self, sa_impact_class_summary_df: pl.DataFrame
    ) -> None:
        """M3.2-U1: Summary should have at least one exposure class."""
        assert sa_impact_class_summary_df.height > 0

    def test_m32_sa_summary_has_all_driver_columns(
        self, sa_impact_class_summary_df: pl.DataFrame
    ) -> None:
        """M3.2-U2: Summary should contain all driver total columns."""
        required = {
            "total_scaling_factor_impact", "total_supporting_factor_impact",
            "total_output_floor_impact", "total_methodology_impact",
            "total_delta_rwa", "exposure_count",
        }
        assert required.issubset(set(sa_impact_class_summary_df.columns))

    def test_m32_sa_summary_drivers_sum_to_delta(
        self, sa_impact_class_summary_df: pl.DataFrame
    ) -> None:
        """M3.2-U3: In each class, driver totals should sum to total_delta_rwa."""
        for row in sa_impact_class_summary_df.to_dicts():
            driver_sum = (
                row["total_scaling_factor_impact"]
                + row["total_supporting_factor_impact"]
                + row["total_output_floor_impact"]
                + row["total_methodology_impact"]
            )
            assert driver_sum == pytest.approx(row["total_delta_rwa"], abs=1.0), (
                f"Summary additivity failed for class {row['exposure_class']}"
            )

    def test_m32_firb_summary_by_class_has_irb_entries(
        self, firb_impact_class_summary_df: pl.DataFrame
    ) -> None:
        """M3.2-U4: F-IRB summary should contain IRB exposure classes."""
        assert firb_impact_class_summary_df.height > 0

    def test_m32_firb_summary_exposure_count_positive(
        self, firb_impact_class_summary_df: pl.DataFrame
    ) -> None:
        """M3.2-U5: Every class should have a positive exposure count."""
        for row in firb_impact_class_summary_df.to_dicts():
            assert row["exposure_count"] > 0


# =============================================================================
# M3.2 Bundle Structure Tests
# =============================================================================


class TestM32_BundleStructure:
    """Validate CapitalImpactBundle structure and immutability."""

    def test_m32_bundle_type(self, sa_capital_impact) -> None:
        """M3.2-B1: analyze() should return a CapitalImpactBundle."""
        assert isinstance(sa_capital_impact, CapitalImpactBundle)

    def test_m32_bundle_is_frozen(self, sa_capital_impact) -> None:
        """M3.2-B2: CapitalImpactBundle should be immutable (frozen dataclass)."""
        with pytest.raises(AttributeError):
            sa_capital_impact.exposure_attribution = pl.LazyFrame()  # type: ignore[misc]

    def test_m32_bundle_all_fields_populated(self, firb_capital_impact) -> None:
        """M3.2-B3: All bundle fields should be non-None."""
        assert firb_capital_impact.exposure_attribution is not None
        assert firb_capital_impact.portfolio_waterfall is not None
        assert firb_capital_impact.summary_by_class is not None
        assert firb_capital_impact.summary_by_approach is not None
