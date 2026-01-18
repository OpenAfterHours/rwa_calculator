"""
Unit tests for the Output Aggregator.

Tests cover:
- Basic result aggregation (SA, IRB, Slotting)
- Output floor application (Basel 3.1)
- Supporting factor impact tracking (CRR)
- Summary generation by class and approach
- Edge cases and error handling
"""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    SAResultBundle,
    IRBResultBundle,
    SlottingResultBundle,
    AggregatedResultBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import (
    OutputAggregator,
    create_output_aggregator,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def aggregator() -> OutputAggregator:
    """Create an OutputAggregator instance."""
    return OutputAggregator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (supporting factors enabled, floor disabled)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration (floor enabled, supporting factors disabled)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))


@pytest.fixture
def basel31_transitional_config() -> CalculationConfig:
    """Basel 3.1 with transitional floor (60% in 2029)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2029, 6, 1))


@pytest.fixture
def sa_results() -> pl.LazyFrame:
    """Sample SA calculation results."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "counterparty_reference": ["CP001", "CP002", "CP003"],
        "exposure_class": ["CORPORATE", "RETAIL", "SOVEREIGN"],
        "ead_final": [1000000.0, 500000.0, 2000000.0],
        "risk_weight": [1.0, 0.75, 0.0],
        "rwa_pre_factor": [1000000.0, 375000.0, 0.0],
        "supporting_factor": [0.7619, 1.0, 1.0],
        "rwa_post_factor": [761900.0, 375000.0, 0.0],
        "supporting_factor_applied": [True, False, False],
        "is_sme": [True, False, False],
        "is_infrastructure": [False, False, False],
    })


@pytest.fixture
def irb_results() -> pl.LazyFrame:
    """Sample IRB calculation results."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP004", "EXP005"],
        "counterparty_reference": ["CP004", "CP005"],
        "exposure_class": ["CORPORATE", "CORPORATE"],
        "approach": ["FIRB", "AIRB"],
        "ead_final": [5000000.0, 3000000.0],
        "pd_floored": [0.01, 0.005],
        "lgd_floored": [0.45, 0.35],
        "correlation": [0.18, 0.15],
        "k": [0.08, 0.05],
        "maturity_adjustment": [1.1, 1.05],
        "risk_weight": [0.88, 0.525],
        "rwa": [4400000.0, 1575000.0],
        "expected_loss": [225000.0, 52500.0],
    })


@pytest.fixture
def slotting_results() -> pl.LazyFrame:
    """Sample Slotting calculation results."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP006"],
        "counterparty_reference": ["CP006"],
        "exposure_class": ["SPECIALISED_LENDING"],
        "slotting_category": ["STRONG"],
        "is_hvcre": [False],
        "ead_final": [10000000.0],
        "risk_weight": [0.7],
        "rwa": [7000000.0],
    })


@pytest.fixture
def sa_bundle(sa_results: pl.LazyFrame) -> SAResultBundle:
    """SA result bundle."""
    return SAResultBundle(
        results=sa_results,
        calculation_audit=None,
        errors=[],
    )


@pytest.fixture
def irb_bundle(irb_results: pl.LazyFrame) -> IRBResultBundle:
    """IRB result bundle."""
    return IRBResultBundle(
        results=irb_results,
        expected_loss=None,
        calculation_audit=None,
        errors=[],
    )


@pytest.fixture
def slotting_bundle(slotting_results: pl.LazyFrame) -> SlottingResultBundle:
    """Slotting result bundle."""
    return SlottingResultBundle(
        results=slotting_results,
        calculation_audit=None,
        errors=[],
    )


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateOutputAggregator:
    """Tests for the factory function."""

    def test_creates_instance(self) -> None:
        """Factory should create an OutputAggregator instance."""
        aggregator = create_output_aggregator()
        assert isinstance(aggregator, OutputAggregator)


# =============================================================================
# Basic Aggregation Tests
# =============================================================================


class TestBasicAggregation:
    """Tests for basic result aggregation."""

    def test_aggregate_sa_only(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should aggregate SA results only."""
        # Empty IRB frame with schema
        empty_irb = pl.LazyFrame(schema={
            "exposure_reference": pl.String,
            "rwa": pl.Float64,
        })

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=empty_irb,
            config=crr_config,
        )

        df = result.collect()
        assert len(df) == 3
        assert "approach_applied" in df.columns
        assert df["approach_applied"].to_list() == ["SA", "SA", "SA"]

    def test_aggregate_irb_only(
        self,
        aggregator: OutputAggregator,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should aggregate IRB results only."""
        # Empty SA frame with schema
        empty_sa = pl.LazyFrame(schema={
            "exposure_reference": pl.String,
            "rwa_post_factor": pl.Float64,
        })

        result = aggregator.aggregate(
            sa_results=empty_sa,
            irb_results=irb_results,
            config=crr_config,
        )

        df = result.collect()
        assert len(df) == 2
        assert set(df["approach_applied"].to_list()) == {"FIRB", "AIRB"}

    def test_aggregate_combined(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should combine SA and IRB results."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            config=crr_config,
        )

        df = result.collect()
        assert len(df) == 5  # 3 SA + 2 IRB
        approaches = set(df["approach_applied"].to_list())
        assert "SA" in approaches
        assert "FIRB" in approaches or "AIRB" in approaches

    def test_aggregate_with_audit_returns_bundle(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        irb_bundle: IRBResultBundle,
        slotting_bundle: SlottingResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """aggregate_with_audit should return AggregatedResultBundle."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=slotting_bundle,
            config=crr_config,
        )

        assert isinstance(result, AggregatedResultBundle)
        assert result.results is not None
        assert result.sa_results is not None
        assert result.irb_results is not None
        assert result.slotting_results is not None

    def test_aggregate_with_slotting(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        slotting_bundle: SlottingResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Should include slotting results in aggregation."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=None,
            slotting_bundle=slotting_bundle,
            config=crr_config,
        )

        df = result.results.collect()
        assert len(df) == 4  # 3 SA + 1 Slotting
        assert "SLOTTING" in df["approach_applied"].to_list()


# =============================================================================
# Output Floor Tests (Basel 3.1)
# =============================================================================


class TestOutputFloor:
    """Tests for output floor application."""

    def test_floor_not_applied_under_crr(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        irb_bundle: IRBResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Floor should not be applied under CRR."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=None,
            config=crr_config,
        )

        assert result.floor_impact is None

    def test_floor_applied_under_basel31(
        self,
        aggregator: OutputAggregator,
        irb_bundle: IRBResultBundle,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should be applied under Basel 3.1."""
        # Create SA results with high RWA for floor comparison
        sa_results = pl.LazyFrame({
            "exposure_reference": ["EXP004", "EXP005"],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "ead_final": [5000000.0, 3000000.0],
            "risk_weight": [1.0, 1.0],
            "rwa_post_factor": [5000000.0, 3000000.0],
        })
        sa_bundle = SAResultBundle(results=sa_results, errors=[])

        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=None,
            config=basel31_config,
        )

        assert result.floor_impact is not None

    def test_floor_binding_when_irb_below_floor(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should bind when IRB RWA < 72.5% SA RWA."""
        # IRB RWA = 50m, SA RWA = 100m, Floor = 72.5m
        # Floor binds: 50m < 72.5m
        sa_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "ead_final": [100000000.0],
            "risk_weight": [1.0],
            "rwa_post_factor": [100000000.0],  # 100m SA RWA
        })
        irb_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["FIRB"],
            "ead_final": [100000000.0],
            "risk_weight": [0.5],
            "rwa": [50000000.0],  # 50m IRB RWA
        })

        result = aggregator.aggregate_with_audit(
            sa_bundle=SAResultBundle(results=sa_results, errors=[]),
            irb_bundle=IRBResultBundle(results=irb_results, errors=[]),
            slotting_bundle=None,
            config=basel31_config,
        )

        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")

        # Final RWA should be floor (72.5m), not IRB (50m)
        assert irb_row["rwa_final"][0] == pytest.approx(72500000.0, rel=0.01)

        # Floor impact should show binding
        impact = result.floor_impact.collect()
        assert impact["is_floor_binding"][0] is True

    def test_floor_not_binding_when_irb_above_floor(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should not bind when IRB RWA > 72.5% SA RWA."""
        # IRB RWA = 80m, SA RWA = 100m, Floor = 72.5m
        # Floor does not bind: 80m > 72.5m
        sa_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "ead_final": [100000000.0],
            "risk_weight": [1.0],
            "rwa_post_factor": [100000000.0],  # 100m SA RWA
        })
        irb_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["FIRB"],
            "ead_final": [100000000.0],
            "risk_weight": [0.8],
            "rwa": [80000000.0],  # 80m IRB RWA
        })

        result = aggregator.aggregate_with_audit(
            sa_bundle=SAResultBundle(results=sa_results, errors=[]),
            irb_bundle=IRBResultBundle(results=irb_results, errors=[]),
            slotting_bundle=None,
            config=basel31_config,
        )

        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")

        # Final RWA should be IRB (80m), not floor (72.5m)
        assert irb_row["rwa_final"][0] == pytest.approx(80000000.0, rel=0.01)

        # Floor impact should show not binding
        impact = result.floor_impact.collect()
        assert impact["is_floor_binding"][0] is False

    def test_transitional_floor_percentage(
        self,
        aggregator: OutputAggregator,
        basel31_transitional_config: CalculationConfig,
    ) -> None:
        """Transitional floor should use scheduled percentage (60% in 2029)."""
        # IRB RWA = 50m, SA RWA = 100m, Floor = 60m (60%)
        sa_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "ead_final": [100000000.0],
            "risk_weight": [1.0],
            "rwa_post_factor": [100000000.0],
        })
        irb_results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "approach": ["FIRB"],
            "ead_final": [100000000.0],
            "risk_weight": [0.5],
            "rwa": [50000000.0],
        })

        result = aggregator.aggregate_with_audit(
            sa_bundle=SAResultBundle(results=sa_results, errors=[]),
            irb_bundle=IRBResultBundle(results=irb_results, errors=[]),
            slotting_bundle=None,
            config=basel31_transitional_config,
        )

        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")

        # Final RWA should be 60m floor (60% × 100m)
        assert irb_row["rwa_final"][0] == pytest.approx(60000000.0, rel=0.01)


# =============================================================================
# Supporting Factor Impact Tests (CRR)
# =============================================================================


class TestSupportingFactorImpact:
    """Tests for supporting factor impact tracking."""

    def test_supporting_factor_impact_generated(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate supporting factor impact for CRR."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=None,
            slotting_bundle=None,
            config=crr_config,
        )

        assert result.supporting_factor_impact is not None
        impact = result.supporting_factor_impact.collect()

        # Should only include rows where supporting factor was applied
        assert len(impact) == 1  # Only SME exposure
        assert impact["is_sme"][0] is True
        assert impact["supporting_factor"][0] == pytest.approx(0.7619, rel=0.01)

    def test_no_supporting_factor_impact_for_basel31(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        basel31_config: CalculationConfig,
    ) -> None:
        """No supporting factor impact should be generated for Basel 3.1."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=None,
            slotting_bundle=None,
            config=basel31_config,
        )

        # Basel 3.1 has supporting_factors.enabled = False
        assert result.supporting_factor_impact is None


# =============================================================================
# Summary Generation Tests
# =============================================================================


class TestSummaryGeneration:
    """Tests for summary generation."""

    def test_summary_by_class_generated(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        irb_bundle: IRBResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate summary by exposure class."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class is not None
        summary = result.summary_by_class.collect()

        # Should have rows for each exposure class
        classes = summary["exposure_class"].to_list()
        assert "CORPORATE" in classes
        assert "RETAIL" in classes
        assert "SOVEREIGN" in classes

    def test_summary_by_approach_generated(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        irb_bundle: IRBResultBundle,
        slotting_bundle: SlottingResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate summary by approach."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=slotting_bundle,
            config=crr_config,
        )

        assert result.summary_by_approach is not None
        summary = result.summary_by_approach.collect()

        # Should have rows for each approach
        approaches = summary["approach_applied"].to_list()
        assert "SA" in approaches
        assert any(a in approaches for a in ["FIRB", "AIRB"])
        assert "SLOTTING" in approaches

    def test_summary_totals_correct(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """Summary totals should be correct."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=None,
            slotting_bundle=None,
            config=crr_config,
        )

        # Check by approach (should be just SA)
        summary = result.summary_by_approach.collect()
        sa_row = summary.filter(pl.col("approach_applied") == "SA")

        # Total EAD = 1000000 + 500000 + 2000000 = 3500000
        assert sa_row["total_ead"][0] == pytest.approx(3500000.0, rel=0.01)

        # Exposure count = 3
        assert sa_row["exposure_count"][0] == 3


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_inputs(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle empty inputs gracefully."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=None,
            irb_bundle=None,
            slotting_bundle=None,
            config=crr_config,
        )

        assert isinstance(result, AggregatedResultBundle)
        df = result.results.collect()
        assert len(df) == 0

    def test_errors_accumulated(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should accumulate errors from all bundles."""
        sa_bundle = SAResultBundle(
            results=pl.LazyFrame({"exposure_reference": ["E1"], "rwa_post_factor": [100.0]}),
            errors=["SA Error 1", "SA Error 2"],
        )
        irb_bundle = IRBResultBundle(
            results=pl.LazyFrame({"exposure_reference": ["E2"], "rwa": [200.0]}),
            errors=["IRB Error 1"],
        )

        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=None,
            config=crr_config,
        )

        assert len(result.errors) == 3

    def test_floor_only_applies_to_irb(
        self,
        aggregator: OutputAggregator,
        sa_bundle: SAResultBundle,
        irb_bundle: IRBResultBundle,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should only apply to IRB exposures, not SA."""
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_bundle,
            irb_bundle=irb_bundle,
            slotting_bundle=None,
            config=basel31_config,
        )

        df = result.results.collect()

        # SA exposures should not have is_floor_binding
        sa_rows = df.filter(pl.col("approach_applied") == "SA")
        if "is_floor_binding" in sa_rows.columns:
            # All SA rows should have is_floor_binding = False
            assert all(not v for v in sa_rows["is_floor_binding"].to_list() if v is not None)


# =============================================================================
# Apply Output Floor Directly Tests
# =============================================================================


class TestApplyOutputFloorMethod:
    """Tests for apply_output_floor method."""

    def test_apply_output_floor_basic(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_output_floor should correctly calculate floor."""
        irb_rwa = pl.LazyFrame({
            "exposure_reference": ["E1", "E2"],
            "rwa": [50000000.0, 80000000.0],  # 50m, 80m
        })
        sa_rwa = pl.LazyFrame({
            "exposure_reference": ["E1", "E2"],
            "rwa": [100000000.0, 100000000.0],  # 100m each
        })

        result = aggregator.apply_output_floor(
            irb_rwa=irb_rwa,
            sa_equivalent_rwa=sa_rwa,
            config=basel31_config,
        )

        df = result.collect()

        # E1: 50m < 72.5m floor -> rwa_final = 72.5m
        e1 = df.filter(pl.col("exposure_reference") == "E1")
        assert e1["rwa_final"][0] == pytest.approx(72500000.0, rel=0.01)
        assert e1["is_floor_binding"][0] is True

        # E2: 80m > 72.5m floor -> rwa_final = 80m
        e2 = df.filter(pl.col("exposure_reference") == "E2")
        assert e2["rwa_final"][0] == pytest.approx(80000000.0, rel=0.01)
        assert e2["is_floor_binding"][0] is False

    def test_apply_output_floor_disabled(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_output_floor should return original frame when disabled."""
        irb_rwa = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "rwa": [50000000.0],
        })
        sa_rwa = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "rwa": [100000000.0],
        })

        result = aggregator.apply_output_floor(
            irb_rwa=irb_rwa,
            sa_equivalent_rwa=sa_rwa,
            config=crr_config,
        )

        df = result.collect()

        # Should return original IRB RWA unchanged
        assert df["rwa"][0] == pytest.approx(50000000.0, rel=0.01)
        # Should not have floor columns
        assert "rwa_final" not in df.columns
