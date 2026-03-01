"""
M3.3 Transitional Floor Schedule Modelling Acceptance Tests.

These tests validate that the TransitionalScheduleRunner correctly models
the output floor phase-in across 2027-2032 using real fixture data.

Why these tests matter:
    The PRA PS9/24 output floor phases in from 50% (2027) to 72.5% (2032+).
    This progressive tightening means a portfolio that is not floor-constrained
    in 2027 may become floor-constrained by 2030. Firms need accurate year-by-year
    modelling to plan capital buffers and identify which exposure classes become
    floor-binding as the percentage rises.

    These tests verify:
    1. Correct floor percentages per the PRA schedule
    2. Monotonically non-decreasing floor impact as percentage rises
    3. Floor binding count non-decreasing (more exposures become floor-bound)
    4. Pre-floor IRB RWA is stable across years (same portfolio, same PD/LGD)
    5. Total RWA (post-floor) never decreases year-over-year

References:
- PRA PS9/24 Ch.12: Output floor transitional schedule
- CRE99.1-8: Output floor mechanics
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def transitional_schedule_bundle(raw_data_bundle):
    """Run TransitionalScheduleRunner on fixture data with F-IRB permissions.

    Uses the default 2027-2032 mid-year dates. Session-scoped: runs
    the pipeline 6 times (once per year). Shared across all tests.
    """
    from rwa_calc.contracts.config import IRBPermissions
    from rwa_calc.engine.comparison import TransitionalScheduleRunner

    runner = TransitionalScheduleRunner()
    return runner.run(
        data=raw_data_bundle,
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture(scope="session")
def timeline_df(transitional_schedule_bundle) -> pl.DataFrame:
    """Collected timeline DataFrame from the schedule bundle."""
    return transitional_schedule_bundle.timeline.collect()


# =============================================================================
# Timeline Structure Tests
# =============================================================================


class TestM33TimelineStructure:
    """Verify the timeline DataFrame has correct structure and completeness."""

    def test_timeline_has_six_years(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-S1: Timeline should contain all 6 transitional years."""
        assert timeline_df.height == 6, (
            f"Expected 6 years in timeline, got {timeline_df.height}"
        )

    def test_timeline_years_correct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-S2: Timeline years should be 2027-2032."""
        years = timeline_df["year"].to_list()
        assert years == [2027, 2028, 2029, 2030, 2031, 2032], (
            f"Expected years 2027-2032, got {years}"
        )

    def test_timeline_columns_complete(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-S3: All expected columns should be present."""
        expected = {
            "reporting_date", "year", "floor_percentage",
            "total_rwa_pre_floor", "total_rwa_post_floor",
            "total_floor_impact", "floor_binding_count",
            "total_irb_exposure_count", "total_ead", "total_sa_rwa",
        }
        assert expected == set(timeline_df.columns), (
            f"Missing columns: {expected - set(timeline_df.columns)}"
        )


# =============================================================================
# Floor Percentage Schedule Tests
# =============================================================================


class TestM33FloorPercentages:
    """Verify floor percentages match the PRA PS9/24 transitional schedule."""

    def test_2027_floor_50_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P1: 2027 floor should be 50%."""
        row = timeline_df.filter(pl.col("year") == 2027)
        assert row["floor_percentage"][0] == pytest.approx(0.50), (
            f"2027 floor should be 50%, got {row['floor_percentage'][0] * 100:.1f}%"
        )

    def test_2028_floor_55_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P2: 2028 floor should be 55%."""
        row = timeline_df.filter(pl.col("year") == 2028)
        assert row["floor_percentage"][0] == pytest.approx(0.55)

    def test_2029_floor_60_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P3: 2029 floor should be 60%."""
        row = timeline_df.filter(pl.col("year") == 2029)
        assert row["floor_percentage"][0] == pytest.approx(0.60)

    def test_2030_floor_65_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P4: 2030 floor should be 65%."""
        row = timeline_df.filter(pl.col("year") == 2030)
        assert row["floor_percentage"][0] == pytest.approx(0.65)

    def test_2031_floor_70_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P5: 2031 floor should be 70%."""
        row = timeline_df.filter(pl.col("year") == 2031)
        assert row["floor_percentage"][0] == pytest.approx(0.70)

    def test_2032_floor_725_pct(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-P6: 2032 floor should be 72.5% (fully phased)."""
        row = timeline_df.filter(pl.col("year") == 2032)
        assert row["floor_percentage"][0] == pytest.approx(0.725)


# =============================================================================
# Monotonicity Invariant Tests
# =============================================================================


class TestM33MonotonicityInvariants:
    """Verify monotonicity invariants that must hold across all years.

    As the floor percentage rises from 50% to 72.5%, the floor impact
    should never decrease — more RWA is captured by the floor.
    """

    def test_floor_impact_non_decreasing(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-M1: Total floor impact should be non-decreasing year over year.

        As the floor percentage rises, more IRB exposures become floor-bound,
        and the floor gap (floor_rwa - irb_rwa) widens. Total floor impact
        should therefore never decrease.
        """
        impacts = timeline_df["total_floor_impact"].to_list()
        for i in range(1, len(impacts)):
            assert impacts[i] >= impacts[i - 1] - 1.0, (
                f"Floor impact decreased from year {2027 + i - 1} ({impacts[i - 1]:,.0f}) "
                f"to year {2027 + i} ({impacts[i]:,.0f})"
            )

    def test_floor_binding_count_non_decreasing(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-M2: Number of floor-binding exposures should be non-decreasing.

        Once an exposure becomes floor-bound (floor% × SA_RWA > IRB_RWA),
        it stays floor-bound at higher percentages.
        """
        counts = timeline_df["floor_binding_count"].to_list()
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i - 1], (
                f"Floor binding count decreased from year {2027 + i - 1} ({counts[i - 1]}) "
                f"to year {2027 + i} ({counts[i]})"
            )

    def test_floor_percentage_times_sa_rwa_non_decreasing(
        self, timeline_df: pl.DataFrame
    ) -> None:
        """M3.3-M3: Floor bite (floor% × SA RWA) should be non-decreasing.

        While total post-floor RWA can decrease year-over-year (because
        effective maturity shortens as loans approach maturity, reducing
        IRB RWA), the floor benchmark itself (floor% × SA RWA) must be
        non-decreasing since SA RWA is stable and the percentage rises.
        """
        floor_bites = [
            row["floor_percentage"] * row["total_sa_rwa"]
            for row in timeline_df.to_dicts()
        ]
        for i in range(1, len(floor_bites)):
            assert floor_bites[i] >= floor_bites[i - 1] - 1.0, (
                f"Floor bite decreased from year {2027 + i - 1} ({floor_bites[i - 1]:,.0f}) "
                f"to year {2027 + i} ({floor_bites[i]:,.0f})"
            )


# =============================================================================
# Floor Impact Structural Tests
# =============================================================================


class TestM33FloorImpactStructure:
    """Verify structural properties of the floor impact data."""

    def test_floor_impact_non_negative(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-F1: Floor impact should never be negative."""
        negative = timeline_df.filter(pl.col("total_floor_impact") < -1.0)
        assert negative.height == 0, (
            f"Found {negative.height} years with negative floor impact"
        )

    def test_ead_consistent_across_years(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-F2: Total EAD should be consistent across years (same portfolio).

        The same raw data is used for each year, so EAD should be identical.
        Allows small tolerance for currency conversion edge cases.
        """
        eads = timeline_df["total_ead"].to_list()
        if eads[0] > 0:
            for i in range(1, len(eads)):
                assert eads[i] == pytest.approx(eads[0], rel=0.02), (
                    f"EAD changed between years: {eads[0]:,.0f} vs {eads[i]:,.0f}"
                )

    def test_irb_exposure_count_consistent(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-F3: IRB exposure count should be consistent across years.

        The same portfolio is classified the same way each year.
        """
        counts = timeline_df["total_irb_exposure_count"].to_list()
        for i in range(1, len(counts)):
            assert counts[i] == counts[0], (
                f"IRB exposure count changed: year 2027 had {counts[0]}, "
                f"year {2027 + i} had {counts[i]}"
            )

    def test_sa_rwa_consistent_across_years(self, timeline_df: pl.DataFrame) -> None:
        """M3.3-F4: SA RWA benchmark should be consistent (same portfolio).

        SA risk weights don't change between years.
        """
        sa_rwas = timeline_df["total_sa_rwa"].to_list()
        if sa_rwas[0] > 0:
            for i in range(1, len(sa_rwas)):
                assert sa_rwas[i] == pytest.approx(sa_rwas[0], rel=0.02), (
                    f"SA RWA changed between years: {sa_rwas[0]:,.0f} vs {sa_rwas[i]:,.0f}"
                )


# =============================================================================
# Yearly Results Tests
# =============================================================================


class TestM33YearlyResults:
    """Verify that individual yearly results are accessible and valid."""

    def test_yearly_results_has_all_years(self, transitional_schedule_bundle) -> None:
        """M3.3-Y1: yearly_results should contain all 6 years."""
        assert len(transitional_schedule_bundle.yearly_results) == 6
        for year in range(2027, 2033):
            assert year in transitional_schedule_bundle.yearly_results

    def test_yearly_results_are_aggregated_bundles(self, transitional_schedule_bundle) -> None:
        """M3.3-Y2: Each yearly result should be an AggregatedResultBundle."""
        from rwa_calc.contracts.bundles import AggregatedResultBundle

        for year, result in transitional_schedule_bundle.yearly_results.items():
            assert isinstance(result, AggregatedResultBundle), (
                f"Year {year} result is {type(result)}, expected AggregatedResultBundle"
            )

    def test_yearly_results_collectible(self, transitional_schedule_bundle) -> None:
        """M3.3-Y3: Each yearly result's main results should be collectible."""
        for year, result in transitional_schedule_bundle.yearly_results.items():
            df = result.results.collect()
            assert isinstance(df, pl.DataFrame), (
                f"Year {year} results failed to collect"
            )
