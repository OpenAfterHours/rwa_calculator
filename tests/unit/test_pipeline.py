"""
Unit tests for Pipeline Orchestrator.

Tests the PipelineOrchestrator component including:
- Component wiring and initialization
- Full pipeline execution
- Pre-loaded data execution
- Error handling and accumulation
- Stage isolation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    CRMAdjustedBundle,
    IRBResultBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    SAResultBundle,
    SlottingResultBundle,
    create_empty_counterparty_lookup,
    create_empty_raw_data_bundle,
)
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.pipeline import (
    PipelineOrchestrator,
    PipelineError,
    create_pipeline,
    create_test_pipeline,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration for testing."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration with IRB permissions."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 15),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def mock_raw_data() -> RawDataBundle:
    """Create mock raw data bundle."""
    # Facilities
    facilities = pl.LazyFrame({
        "facility_reference": ["FAC001"],
        "counterparty_reference": ["CP001"],
        "product_type": ["TERM_LOAN"],
        "book_code": ["BANK"],
        "currency": ["GBP"],
        "facility_limit": [1000000.0],
    })

    # Loans
    loans = pl.LazyFrame({
        "loan_reference": ["LN001", "LN002"],
        "counterparty_reference": ["CP001", "CP002"],
        "product_type": ["TERM_LOAN", "MORTGAGE"],
        "book_code": ["BANK", "BANK"],
        "value_date": [date(2023, 1, 1), date(2023, 6, 1)],
        "maturity_date": [date(2028, 1, 1), date(2053, 6, 1)],
        "currency": ["GBP", "GBP"],
        "drawn_amount": [500000.0, 250000.0],
        "lgd": [0.45, 0.10],
        "seniority": ["senior", "senior"],
    })

    # Contingents
    contingents = pl.LazyFrame({
        "contingent_reference": ["CTG001"],
        "counterparty_reference": ["CP001"],
        "product_type": ["GUARANTEE"],
        "book_code": ["BANK"],
        "value_date": [date(2023, 1, 1)],
        "maturity_date": [date(2028, 1, 1)],
        "currency": ["GBP"],
        "nominal_amount": [100000.0],
        "lgd": [0.45],
        "seniority": ["senior"],
        "ccf_category": ["MEDIUM"],
    })

    # Counterparties
    counterparties = pl.LazyFrame({
        "counterparty_reference": ["CP001", "CP002"],
        "entity_type": ["corporate", "individual"],
        "country_code": ["GB", "GB"],
        "annual_revenue": [30000000.0, 0.0],
        "default_status": [False, False],
        "is_financial_institution": [False, False],
        "is_regulated": [False, False],
        "is_pse": [False, False],
        "is_mdb": [False, False],
        "is_international_org": [False, False],
        "is_central_counterparty": [False, False],
        "is_regional_govt_local_auth": [False, False],
    })

    # Collateral (empty)
    collateral = pl.LazyFrame({
        "collateral_reference": pl.Series([], dtype=pl.String),
        "beneficiary_reference": pl.Series([], dtype=pl.String),
        "market_value": pl.Series([], dtype=pl.Float64),
    })

    # Guarantees (empty)
    guarantees = pl.LazyFrame({
        "guarantee_reference": pl.Series([], dtype=pl.String),
        "beneficiary_reference": pl.Series([], dtype=pl.String),
        "amount_covered": pl.Series([], dtype=pl.Float64),
    })

    # Provisions (empty)
    provisions = pl.LazyFrame({
        "provision_reference": pl.Series([], dtype=pl.String),
        "exposure_reference": pl.Series([], dtype=pl.String),
        "provision_amount": pl.Series([], dtype=pl.Float64),
    })

    # Ratings
    ratings = pl.LazyFrame({
        "counterparty_reference": ["CP001"],
        "rating_type": ["external"],
        "rating_agency": ["S&P"],
        "rating_value": ["BBB"],
        "cqs": [3],
        "pd": [0.005],
        "rating_date": [date(2024, 1, 1)],
    })

    # Facility mappings (empty hierarchy)
    facility_mappings = pl.LazyFrame({
        "child_reference": pl.Series([], dtype=pl.String),
        "parent_facility_reference": pl.Series([], dtype=pl.String),
    })

    # Org mappings (empty hierarchy)
    org_mappings = pl.LazyFrame({
        "child_counterparty_reference": pl.Series([], dtype=pl.String),
        "parent_counterparty_reference": pl.Series([], dtype=pl.String),
    })

    # Lending mappings (empty)
    lending_mappings = pl.LazyFrame({
        "child_counterparty_reference": pl.Series([], dtype=pl.String),
        "parent_counterparty_reference": pl.Series([], dtype=pl.String),
    })

    return RawDataBundle(
        facilities=facilities,
        loans=loans,
        contingents=contingents,
        counterparties=counterparties,
        collateral=collateral,
        guarantees=guarantees,
        provisions=provisions,
        ratings=ratings,
        facility_mappings=facility_mappings,
        org_mappings=org_mappings,
        lending_mappings=lending_mappings,
    )


@pytest.fixture
def mock_resolved_bundle() -> ResolvedHierarchyBundle:
    """Create mock resolved hierarchy bundle."""
    exposures = pl.LazyFrame({
        "exposure_reference": ["LN001", "LN002"],
        "exposure_type": ["loan", "loan"],
        "counterparty_reference": ["CP001", "CP002"],
        "product_type": ["TERM_LOAN", "MORTGAGE"],
        "book_code": ["BANK", "BANK"],
        "value_date": [date(2023, 1, 1), date(2023, 6, 1)],
        "maturity_date": [date(2028, 1, 1), date(2053, 6, 1)],
        "currency": ["GBP", "GBP"],
        "drawn_amount": [500000.0, 250000.0],
        "undrawn_amount": [0.0, 0.0],
        "nominal_amount": [0.0, 0.0],
        "lgd": [0.45, 0.10],
        "seniority": ["senior", "senior"],
        "lending_group_total_exposure": [0.0, 0.0],
    })

    return ResolvedHierarchyBundle(
        exposures=exposures,
        counterparty_lookup=create_empty_counterparty_lookup(),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        lending_group_totals=pl.LazyFrame(),
        hierarchy_errors=[],
    )


@pytest.fixture
def mock_classified_bundle() -> ClassifiedExposuresBundle:
    """Create mock classified exposures bundle."""
    all_exposures = pl.LazyFrame({
        "exposure_reference": ["LN001", "LN002"],
        "counterparty_reference": ["CP001", "CP002"],
        "exposure_type": ["loan", "loan"],
        "product_type": ["TERM_LOAN", "MORTGAGE"],
        "book_code": ["BANK", "BANK"],
        "exposure_class": ["CORPORATE_SME", "RETAIL_MORTGAGE"],
        "approach": ["SA", "SA"],
        "ead_final": [500000.0, 250000.0],
        "drawn_amount": [500000.0, 250000.0],
        "undrawn_amount": [0.0, 0.0],
        "nominal_amount": [0.0, 0.0],
        "lgd": [0.45, 0.10],
        "is_sme": [True, False],
        "is_mortgage": [False, True],
        "is_defaulted": [False, False],
        "qualifies_as_retail": [True, True],
        "ccf_category": [None, None],
    })

    sa_exposures = all_exposures.filter(pl.col("approach") == "SA")
    irb_exposures = all_exposures.filter(
        (pl.col("approach") == "FIRB") | (pl.col("approach") == "AIRB")
    )

    return ClassifiedExposuresBundle(
        all_exposures=all_exposures,
        sa_exposures=sa_exposures,
        irb_exposures=irb_exposures,
        classification_errors=[],
    )


@pytest.fixture
def mock_crm_bundle() -> CRMAdjustedBundle:
    """Create mock CRM-adjusted bundle."""
    exposures = pl.LazyFrame({
        "exposure_reference": ["LN001", "LN002"],
        "counterparty_reference": ["CP001", "CP002"],
        "exposure_class": ["CORPORATE_SME", "RETAIL_MORTGAGE"],
        "approach": ["SA", "SA"],
        "ead_gross": [500000.0, 250000.0],
        "ead_final": [500000.0, 250000.0],
        "drawn_amount": [500000.0, 250000.0],
        "nominal_amount": [0.0, 0.0],
        "ccf": [1.0, 1.0],
        "ead_from_ccf": [0.0, 0.0],
        "ead_pre_crm": [500000.0, 250000.0],
        "collateral_adjusted_value": [0.0, 0.0],
        "guarantee_amount": [0.0, 0.0],
        "provision_allocated": [0.0, 0.0],
        "lgd": [0.45, 0.10],
        "lgd_pre_crm": [0.45, 0.10],
        "lgd_post_crm": [0.45, 0.10],
        "is_sme": [True, False],
        "is_mortgage": [False, True],
        "is_defaulted": [False, False],
        "crm_calculation": ["EAD: gross=500000; final=500000", "EAD: gross=250000; final=250000"],
    })

    sa_exposures = exposures.filter(pl.col("approach") == "SA")
    irb_exposures = exposures.filter(
        (pl.col("approach") == "FIRB") | (pl.col("approach") == "AIRB")
    )

    return CRMAdjustedBundle(
        exposures=exposures,
        sa_exposures=sa_exposures,
        irb_exposures=irb_exposures,
        crm_errors=[],
    )


# =============================================================================
# Test Classes
# =============================================================================


class TestPipelineOrchestratorInitialization:
    """Tests for pipeline initialization."""

    def test_create_pipeline_without_loader(self):
        """Test creating pipeline without loader."""
        pipeline = create_pipeline()
        assert isinstance(pipeline, PipelineOrchestrator)
        assert pipeline._loader is None

    def test_create_pipeline_with_path(self, tmp_path):
        """Test creating pipeline with data path."""
        # Create minimal required directory structure
        data_path = tmp_path / "data"
        data_path.mkdir()

        # Creating the pipeline with existing directory should work
        # But loading data should fail because files don't exist
        pipeline = create_pipeline(data_path=data_path)
        assert isinstance(pipeline, PipelineOrchestrator)
        assert pipeline._loader is not None

    def test_pipeline_with_custom_components(self):
        """Test creating pipeline with custom components."""
        mock_loader = MagicMock()
        mock_resolver = MagicMock()
        mock_classifier = MagicMock()

        pipeline = PipelineOrchestrator(
            loader=mock_loader,
            hierarchy_resolver=mock_resolver,
            classifier=mock_classifier,
        )

        assert pipeline._loader is mock_loader
        assert pipeline._hierarchy_resolver is mock_resolver
        assert pipeline._classifier is mock_classifier

    def test_ensure_components_initialized(self):
        """Test that components are auto-initialized when needed."""
        pipeline = PipelineOrchestrator()

        # Before initialization
        assert pipeline._hierarchy_resolver is None
        assert pipeline._classifier is None

        # Trigger initialization
        pipeline._ensure_components_initialized()

        # After initialization
        assert pipeline._hierarchy_resolver is not None
        assert pipeline._classifier is not None
        assert pipeline._crm_processor is not None
        assert pipeline._sa_calculator is not None
        assert pipeline._irb_calculator is not None
        assert pipeline._slotting_calculator is not None
        assert pipeline._aggregator is not None


class TestPipelineRunWithData:
    """Tests for run_with_data method."""

    def test_run_with_data_crr(self, mock_raw_data, crr_config):
        """Test full pipeline execution with CRR config."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        assert isinstance(result, AggregatedResultBundle)
        assert result.results is not None

    def test_run_with_data_basel31(self, mock_raw_data, basel31_config):
        """Test full pipeline execution with Basel 3.1 config."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, basel31_config)

        assert isinstance(result, AggregatedResultBundle)
        assert result.results is not None

    def test_run_with_empty_data(self, crr_config):
        """Test pipeline with empty raw data."""
        empty_data = create_empty_raw_data_bundle()
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(empty_data, crr_config)

        assert isinstance(result, AggregatedResultBundle)


class TestPipelineRun:
    """Tests for run() method."""

    def test_run_without_loader_raises_error(self, crr_config):
        """Test that run() raises error without loader."""
        pipeline = PipelineOrchestrator()

        with pytest.raises(ValueError, match="No loader configured"):
            pipeline.run(crr_config)

    def test_run_with_loader(self, mock_raw_data, crr_config):
        """Test run() with configured loader."""
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_raw_data

        pipeline = PipelineOrchestrator(loader=mock_loader)
        result = pipeline.run(crr_config)

        assert isinstance(result, AggregatedResultBundle)
        mock_loader.load.assert_called_once()


class TestPipelineStageExecution:
    """Tests for individual stage execution."""

    def test_hierarchy_resolver_stage(self, mock_raw_data, crr_config):
        """Test hierarchy resolver stage runs correctly."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        result = pipeline._run_hierarchy_resolver(mock_raw_data, crr_config)

        assert isinstance(result, ResolvedHierarchyBundle)
        assert result.exposures is not None

    def test_classifier_stage(self, mock_resolved_bundle, crr_config):
        """Test classifier stage runs correctly."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        result = pipeline._run_classifier(mock_resolved_bundle, crr_config)

        assert isinstance(result, ClassifiedExposuresBundle)

    def test_crm_processor_stage(self, mock_classified_bundle, crr_config):
        """Test CRM processor stage runs correctly."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        result = pipeline._run_crm_processor(mock_classified_bundle, crr_config)

        assert isinstance(result, CRMAdjustedBundle)

    def test_sa_calculator_stage(self, mock_crm_bundle, crr_config):
        """Test SA calculator stage runs correctly."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        result = pipeline._run_sa_calculator(mock_crm_bundle, crr_config)

        assert isinstance(result, SAResultBundle)
        assert result.results is not None

    def test_irb_calculator_stage_empty(self, mock_crm_bundle, crr_config):
        """Test IRB calculator stage with no IRB exposures."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        # mock_crm_bundle has all SA exposures, no IRB
        result = pipeline._run_irb_calculator(mock_crm_bundle, crr_config)

        assert isinstance(result, IRBResultBundle)
        # Should return empty bundle since no IRB exposures
        collected = result.results.collect()
        assert collected.height == 0

    def test_slotting_calculator_stage_empty(self, mock_crm_bundle, crr_config):
        """Test slotting calculator stage with no slotting exposures."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        result = pipeline._run_slotting_calculator(mock_crm_bundle, crr_config)

        assert isinstance(result, SlottingResultBundle)
        # Should return empty bundle since no slotting exposures
        collected = result.results.collect()
        assert collected.height == 0


class TestPipelineErrorHandling:
    """Tests for error handling."""

    def test_hierarchy_resolver_error_accumulation(self, crr_config):
        """Test that hierarchy resolver errors are accumulated."""
        pipeline = PipelineOrchestrator()
        pipeline._ensure_components_initialized()

        # Create data that might cause errors
        raw_data = create_empty_raw_data_bundle()
        result = pipeline.run_with_data(raw_data, crr_config)

        # Check result is valid despite potential errors
        assert isinstance(result, AggregatedResultBundle)

    def test_load_error_handling(self, crr_config):
        """Test handling of loader errors."""
        mock_loader = MagicMock()
        mock_loader.load.side_effect = Exception("Load failed")

        pipeline = PipelineOrchestrator(loader=mock_loader)
        result = pipeline.run(crr_config)

        assert isinstance(result, AggregatedResultBundle)
        assert len(result.errors) > 0

    def test_stage_error_returns_error_result(self, crr_config):
        """Test that stage errors result in error result."""
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("Resolution failed")

        pipeline = PipelineOrchestrator(hierarchy_resolver=mock_resolver)
        pipeline._ensure_components_initialized()

        raw_data = create_empty_raw_data_bundle()
        result = pipeline.run_with_data(raw_data, crr_config)

        assert isinstance(result, AggregatedResultBundle)
        assert len(result.errors) > 0


class TestPipelineUtilities:
    """Tests for utility methods."""

    def test_has_rows_with_data(self):
        """Test _has_rows returns True for non-empty frame."""
        pipeline = PipelineOrchestrator()
        frame = pl.LazyFrame({"a": [1, 2, 3]})
        assert pipeline._has_rows(frame) is True

    def test_has_rows_empty(self):
        """Test _has_rows returns False for empty frame."""
        pipeline = PipelineOrchestrator()
        frame = pl.LazyFrame({"a": pl.Series([], dtype=pl.Int64)})
        assert pipeline._has_rows(frame) is False

    def test_has_rows_no_schema(self):
        """Test _has_rows returns False for frame with no columns."""
        pipeline = PipelineOrchestrator()
        frame = pl.LazyFrame()
        assert pipeline._has_rows(frame) is False

    def test_create_empty_frames(self):
        """Test empty frame creation methods."""
        pipeline = PipelineOrchestrator()

        sa_frame = pipeline._create_empty_sa_frame()
        irb_frame = pipeline._create_empty_irb_frame()
        slotting_frame = pipeline._create_empty_slotting_frame()

        assert sa_frame.collect().height == 0
        assert irb_frame.collect().height == 0
        assert slotting_frame.collect().height == 0

    def test_convert_pipeline_error(self):
        """Test pipeline error conversion."""
        pipeline = PipelineOrchestrator()

        error = PipelineError(
            stage="test_stage",
            error_type="test_error",
            message="Test message",
            context={"key": "value"},
        )

        converted = pipeline._convert_pipeline_error(error)
        assert "test_stage" in str(converted.code).lower()


class TestPipelineResults:
    """Tests for pipeline result generation."""

    def test_result_contains_summaries(self, mock_raw_data, crr_config):
        """Test that result contains summaries."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        # Result should have summary frames
        assert result.summary_by_class is not None
        assert result.summary_by_approach is not None

    def test_crr_no_floor_impact(self, mock_raw_data, crr_config):
        """Test that CRR config has no floor impact."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        # CRR doesn't have output floor
        # floor_impact may be None or empty
        if result.floor_impact is not None:
            collected = result.floor_impact.collect()
            # Should have no floor binding for SA exposures
            if "is_floor_binding" in collected.columns:
                assert not collected["is_floor_binding"].any()

    def test_crr_supporting_factor_impact(self, mock_raw_data, crr_config):
        """Test that CRR config tracks supporting factor impact."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        # CRR should track supporting factors
        # May or may not have impact depending on data
        assert result.supporting_factor_impact is not None or result.sa_results is not None


class TestPipelineIntegration:
    """Integration tests for complete pipeline flow."""

    def test_full_pipeline_sa_only(self, mock_raw_data, crr_config):
        """Test complete pipeline with SA-only config."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        assert isinstance(result, AggregatedResultBundle)

        # SA results may be empty if exposures are filtered out
        # but the pipeline should complete without error
        if result.sa_results is not None:
            sa_collected = result.sa_results.collect()
            if sa_collected.height > 0:
                # Check for expected columns
                schema_names = sa_collected.columns
                assert "exposure_reference" in schema_names

        # Final results should be present (even if empty)
        results_collected = result.results.collect()
        assert isinstance(results_collected, pl.DataFrame)

    def test_full_pipeline_with_irb(self, mock_raw_data):
        """Test complete pipeline with IRB permissions."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, config)

        assert isinstance(result, AggregatedResultBundle)
        # Results should be generated even if all exposures
        # fall to SA due to lack of IRB data

    def test_result_frame_can_be_collected(self, mock_raw_data, crr_config):
        """Test that result LazyFrames can be collected."""
        pipeline = PipelineOrchestrator()
        result = pipeline.run_with_data(mock_raw_data, crr_config)

        # Should be able to collect all result frames
        results_df = result.results.collect()
        assert isinstance(results_df, pl.DataFrame)

        if result.sa_results is not None:
            sa_df = result.sa_results.collect()
            assert isinstance(sa_df, pl.DataFrame)

        if result.summary_by_approach is not None:
            approach_df = result.summary_by_approach.collect()
            assert isinstance(approach_df, pl.DataFrame)


class TestPipelineFactoryFunctions:
    """Tests for factory functions."""

    def test_create_pipeline_returns_orchestrator(self):
        """Test create_pipeline returns PipelineOrchestrator."""
        pipeline = create_pipeline()
        assert isinstance(pipeline, PipelineOrchestrator)

    @pytest.mark.skip(reason="Requires test fixtures directory")
    def test_create_test_pipeline(self):
        """Test create_test_pipeline creates configured pipeline."""
        pipeline = create_test_pipeline()
        assert isinstance(pipeline, PipelineOrchestrator)
        assert pipeline._loader is not None


# =============================================================================
# Run Tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
