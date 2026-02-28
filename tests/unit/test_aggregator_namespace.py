"""Unit tests for the Aggregator Polars namespace.

Tests cover:
- Namespace registration and availability
- Result combination
- Output floor application
- Summary generation by class
- Summary generation by approach
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine import AggregatorLazyFrame  # noqa: F401

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration (no output floor)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration (with output floor)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def sa_results() -> pl.LazyFrame:
    """Return SA calculation results."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002"],
            "exposure_class": ["CORPORATE", "RETAIL"],
            "ead_final": [1_000_000.0, 500_000.0],
            "risk_weight": [0.50, 0.75],
            "rwa_post_factor": [500_000.0, 375_000.0],
        }
    )


@pytest.fixture
def irb_results() -> pl.LazyFrame:
    """Return IRB calculation results."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP003", "EXP004"],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "ead_final": [2_000_000.0, 1_500_000.0],
            "risk_weight": [0.40, 0.35],
            "rwa": [800_000.0, 525_000.0],
            "approach": ["FIRB", "FIRB"],
            "expected_loss": [20_000.0, 15_000.0],
        }
    )


@pytest.fixture
def slotting_results() -> pl.LazyFrame:
    """Return Slotting calculation results."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP005"],
            "exposure_class": ["SPECIALISED_LENDING"],
            "ead_final": [1_000_000.0],
            "risk_weight": [0.70],
            "rwa": [700_000.0],
        }
    )


@pytest.fixture
def combined_results() -> pl.LazyFrame:
    """Return combined results with approach."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "exposure_class": ["CORPORATE", "RETAIL", "CORPORATE"],
            "ead_final": [1_000_000.0, 500_000.0, 2_000_000.0],
            "risk_weight": [0.50, 0.75, 0.40],
            "rwa_final": [500_000.0, 375_000.0, 800_000.0],
            "approach_applied": ["SA", "SA", "FIRB"],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestAggregatorNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, combined_results: pl.LazyFrame) -> None:
        """LazyFrame should have .aggregator namespace available."""
        assert hasattr(combined_results, "aggregator")

    def test_namespace_methods_available(self, combined_results: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        aggregator = combined_results.aggregator
        expected_methods = [
            "combine_approach_results",
            "apply_output_floor",
            "calculate_floor_impact",
            "generate_summary_by_class",
            "generate_summary_by_approach",
            "generate_supporting_factor_impact",
        ]
        for method in expected_methods:
            assert hasattr(aggregator, method), f"Missing method: {method}"


# =============================================================================
# Result Combination Tests
# =============================================================================


class TestCombineApproachResults:
    """Tests for result combination."""

    def test_combines_sa_and_irb(
        self,
        combined_results: pl.LazyFrame,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
    ) -> None:
        """Should combine SA and IRB results."""
        result = combined_results.aggregator.combine_approach_results(
            sa=sa_results,
            irb=irb_results,
        ).collect()

        # Should have results from both approaches
        approaches = result["approach_applied"].unique().to_list()
        assert "SA" in approaches
        assert "FIRB" in approaches

    def test_combines_all_approaches(
        self,
        combined_results: pl.LazyFrame,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
    ) -> None:
        """Should combine all three approaches."""
        result = combined_results.aggregator.combine_approach_results(
            sa=sa_results,
            irb=irb_results,
            slotting=slotting_results,
        ).collect()

        approaches = result["approach_applied"].unique().to_list()
        assert "SA" in approaches
        assert "FIRB" in approaches
        assert "SLOTTING" in approaches


# =============================================================================
# Output Floor Tests
# =============================================================================


class TestApplyOutputFloor:
    """Tests for output floor application."""

    def test_crr_no_floor_applied(
        self,
        combined_results: pl.LazyFrame,
        sa_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR should not apply output floor."""
        result = combined_results.aggregator.apply_output_floor(
            sa_results,
            crr_config,
        ).collect()

        # Should return unchanged (output floor disabled for CRR)
        assert result.shape[0] == combined_results.collect().shape[0]

    def test_basel31_floor_applied(
        self,
        sa_results: pl.LazyFrame,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 should apply output floor to IRB exposures."""
        # Create IRB results with lower RWA than floor would require
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.20],  # Low IRB RW
                "rwa_final": [200_000.0],  # Low IRB RWA
                "approach_applied": ["FIRB"],
            }
        )

        result = irb_results.aggregator.apply_output_floor(
            sa_results,
            basel31_config,
        ).collect()

        # Should have floor-related columns
        assert "floor_rwa" in result.columns
        assert "is_floor_binding" in result.columns


# =============================================================================
# Summary Generation Tests
# =============================================================================


class TestGenerateSummaryByClass:
    """Tests for summary by exposure class."""

    def test_summary_by_class_aggregates(self, combined_results: pl.LazyFrame) -> None:
        """Should aggregate by exposure class."""
        result = combined_results.aggregator.generate_summary_by_class().collect()

        # Should have exposure_class column
        assert "exposure_class" in result.columns

        # Should have aggregation columns
        assert "total_rwa" in result.columns or "total_ead" in result.columns
        assert "exposure_count" in result.columns

    def test_summary_by_class_correct_counts(self, combined_results: pl.LazyFrame) -> None:
        """Should have correct exposure counts."""
        result = combined_results.aggregator.generate_summary_by_class().collect()

        # CORPORATE should have 2 exposures, RETAIL should have 1
        corporate = result.filter(pl.col("exposure_class") == "CORPORATE")
        retail = result.filter(pl.col("exposure_class") == "RETAIL")

        assert corporate["exposure_count"][0] == 2
        assert retail["exposure_count"][0] == 1


class TestGenerateSummaryByApproach:
    """Tests for summary by approach."""

    def test_summary_by_approach_aggregates(self, combined_results: pl.LazyFrame) -> None:
        """Should aggregate by approach."""
        result = combined_results.aggregator.generate_summary_by_approach().collect()

        # Should have approach_applied column
        assert "approach_applied" in result.columns

        # Should have aggregation columns
        assert "total_rwa" in result.columns or "total_ead" in result.columns
        assert "exposure_count" in result.columns

    def test_summary_by_approach_correct_counts(self, combined_results: pl.LazyFrame) -> None:
        """Should have correct exposure counts."""
        result = combined_results.aggregator.generate_summary_by_approach().collect()

        # SA should have 2 exposures, FIRB should have 1
        sa = result.filter(pl.col("approach_applied") == "SA")
        firb = result.filter(pl.col("approach_applied") == "FIRB")

        assert sa["exposure_count"][0] == 2
        assert firb["exposure_count"][0] == 1
