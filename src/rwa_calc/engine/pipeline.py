"""
Pipeline Orchestrator for RWA Calculator.

Orchestrates the complete RWA calculation pipeline, wiring together:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA/IRB/Slotting Calculators -> OutputAggregator

Pipeline position:
    Entry point for full pipeline execution

Key responsibilities:
- Wire all pipeline components in correct order
- Handle component dependencies and data flow
- Accumulate errors from all stages
- Support both full pipeline (with loader) and pre-loaded data execution

Usage:
    from rwa_calc.engine.pipeline import create_pipeline

    pipeline = create_pipeline()
    result = pipeline.run(config)

    # Or with pre-loaded data:
    result = pipeline.run_with_data(raw_data, config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    SAResultBundle,
    IRBResultBundle,
    SlottingResultBundle,
)
from rwa_calc.contracts.protocols import (
    LoaderProtocol,
    HierarchyResolverProtocol,
    ClassifierProtocol,
    CRMProcessorProtocol,
    SACalculatorProtocol,
    IRBCalculatorProtocol,
    SlottingCalculatorProtocol,
    OutputAggregatorProtocol,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# Error Types
# =============================================================================


@dataclass
class PipelineError:
    """Error encountered during pipeline execution."""

    stage: str
    error_type: str
    message: str
    context: dict = field(default_factory=dict)


# =============================================================================
# Pipeline Orchestrator Implementation
# =============================================================================


class PipelineOrchestrator:
    """
    Orchestrate the complete RWA calculation pipeline.

    Implements PipelineProtocol for:
    - Full pipeline execution from data loading to final aggregation
    - Pre-loaded data execution (bypassing loader)
    - Component dependency management
    - Error accumulation across stages

    Pipeline stages:
    1. Loader: Load raw data from files/databases
    2. HierarchyResolver: Resolve counterparty and facility hierarchies
    3. Classifier: Classify exposures and assign approaches
    4. CRMProcessor: Apply credit risk mitigation
    5. SACalculator: Calculate SA RWA
    6. IRBCalculator: Calculate IRB RWA
    7. SlottingCalculator: Calculate Slotting RWA
    8. OutputAggregator: Combine results, apply floor, generate summaries

    Usage:
        orchestrator = PipelineOrchestrator(
            loader=ParquetLoader(base_path),
            hierarchy_resolver=HierarchyResolver(),
            classifier=ExposureClassifier(),
            crm_processor=CRMProcessor(),
            sa_calculator=SACalculator(),
            irb_calculator=IRBCalculator(),
            slotting_calculator=SlottingCalculator(),
            aggregator=OutputAggregator(),
        )
        result = orchestrator.run(config)
    """

    def __init__(
        self,
        loader: LoaderProtocol | None = None,
        hierarchy_resolver: HierarchyResolverProtocol | None = None,
        classifier: ClassifierProtocol | None = None,
        crm_processor: CRMProcessorProtocol | None = None,
        sa_calculator: SACalculatorProtocol | None = None,
        irb_calculator: IRBCalculatorProtocol | None = None,
        slotting_calculator: SlottingCalculatorProtocol | None = None,
        aggregator: OutputAggregatorProtocol | None = None,
    ) -> None:
        """
        Initialize pipeline with components.

        Components can be injected for testing or customization.
        If not provided, defaults will be created on first use.

        Args:
            loader: Data loader (optional - required for run())
            hierarchy_resolver: Hierarchy resolver
            classifier: Exposure classifier
            crm_processor: CRM processor
            sa_calculator: SA calculator
            irb_calculator: IRB calculator
            slotting_calculator: Slotting calculator
            aggregator: Output aggregator
        """
        self._loader = loader
        self._hierarchy_resolver = hierarchy_resolver
        self._classifier = classifier
        self._crm_processor = crm_processor
        self._sa_calculator = sa_calculator
        self._irb_calculator = irb_calculator
        self._slotting_calculator = slotting_calculator
        self._aggregator = aggregator
        self._errors: list[PipelineError] = []

    # =========================================================================
    # Public API
    # =========================================================================

    def run(self, config: CalculationConfig) -> AggregatedResultBundle:
        """
        Execute the complete RWA calculation pipeline.

        Requires a loader to be configured.

        Args:
            config: Calculation configuration

        Returns:
            AggregatedResultBundle with all results and audit trail

        Raises:
            ValueError: If no loader is configured
        """
        if self._loader is None:
            raise ValueError(
                "No loader configured. Use run_with_data() or provide a loader."
            )

        # Reset errors for new run
        self._errors = []

        # Stage 1: Load data
        try:
            raw_data = self._loader.load()
        except Exception as e:
            self._errors.append(PipelineError(
                stage="loader",
                error_type="load_error",
                message=str(e),
            ))
            return self._create_error_result()

        return self.run_with_data(raw_data, config)

    def run_with_data(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Execute pipeline with pre-loaded data.

        Bypasses the loader stage, useful for testing or
        when data is already available.

        Args:
            data: Pre-loaded raw data bundle
            config: Calculation configuration

        Returns:
            AggregatedResultBundle with all results and audit trail
        """
        # Reset errors for new run
        self._errors = []

        # Ensure components are initialized
        self._ensure_components_initialized()

        # Stage 2: Resolve hierarchies
        resolved = self._run_hierarchy_resolver(data, config)
        if resolved is None:
            return self._create_error_result()

        # Stage 3: Classify exposures
        classified = self._run_classifier(resolved, config)
        if classified is None:
            return self._create_error_result()

        # Stage 4: Apply CRM
        crm_adjusted = self._run_crm_processor(classified, config)
        if crm_adjusted is None:
            return self._create_error_result()

        # Stage 5-7: Run calculators in parallel (conceptually)
        sa_bundle = self._run_sa_calculator(crm_adjusted, config)
        irb_bundle = self._run_irb_calculator(crm_adjusted, config)
        slotting_bundle = self._run_slotting_calculator(crm_adjusted, config)

        # Stage 8: Aggregate results
        result = self._run_aggregator(
            sa_bundle,
            irb_bundle,
            slotting_bundle,
            config,
        )

        # Add pipeline errors to result
        if self._errors:
            all_errors = list(result.errors) + [
                self._convert_pipeline_error(e) for e in self._errors
            ]
            result = AggregatedResultBundle(
                results=result.results,
                sa_results=result.sa_results,
                irb_results=result.irb_results,
                slotting_results=result.slotting_results,
                floor_impact=result.floor_impact,
                supporting_factor_impact=result.supporting_factor_impact,
                summary_by_class=result.summary_by_class,
                summary_by_approach=result.summary_by_approach,
                errors=all_errors,
            )

        return result

    # =========================================================================
    # Private Methods - Component Initialization
    # =========================================================================

    def _ensure_components_initialized(self) -> None:
        """Ensure all required components are initialized."""
        from rwa_calc.engine.hierarchy import HierarchyResolver
        from rwa_calc.engine.classifier import ExposureClassifier
        from rwa_calc.engine.crm.processor import CRMProcessor
        from rwa_calc.engine.sa.calculator import SACalculator
        from rwa_calc.engine.irb.calculator import IRBCalculator
        from rwa_calc.engine.slotting.calculator import SlottingCalculator
        from rwa_calc.engine.aggregator import OutputAggregator

        if self._hierarchy_resolver is None:
            self._hierarchy_resolver = HierarchyResolver()
        if self._classifier is None:
            self._classifier = ExposureClassifier()
        if self._crm_processor is None:
            self._crm_processor = CRMProcessor()
        if self._sa_calculator is None:
            self._sa_calculator = SACalculator()
        if self._irb_calculator is None:
            self._irb_calculator = IRBCalculator()
        if self._slotting_calculator is None:
            self._slotting_calculator = SlottingCalculator()
        if self._aggregator is None:
            self._aggregator = OutputAggregator()

    # =========================================================================
    # Private Methods - Stage Execution
    # =========================================================================

    def _run_hierarchy_resolver(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle | None:
        """Run hierarchy resolution stage."""
        try:
            result = self._hierarchy_resolver.resolve(data, config)
            # Accumulate hierarchy errors
            if result.hierarchy_errors:
                for error in result.hierarchy_errors:
                    self._errors.append(PipelineError(
                        stage="hierarchy_resolver",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                        context=getattr(error, "context", {}),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="hierarchy_resolver",
                error_type="resolution_error",
                message=str(e),
            ))
            return None

    def _run_classifier(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle | None:
        """Run classification stage."""
        try:
            result = self._classifier.classify(data, config)
            # Accumulate classification errors
            if result.classification_errors:
                for error in result.classification_errors:
                    self._errors.append(PipelineError(
                        stage="classifier",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                        context=getattr(error, "context", {}),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="classifier",
                error_type="classification_error",
                message=str(e),
            ))
            return None

    def _run_crm_processor(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle | None:
        """Run CRM processing stage."""
        try:
            result = self._crm_processor.get_crm_adjusted_bundle(data, config)
            # Accumulate CRM errors
            if result.crm_errors:
                for error in result.crm_errors:
                    self._errors.append(PipelineError(
                        stage="crm_processor",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                        context=getattr(error, "context", {}),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="crm_processor",
                error_type="crm_error",
                message=str(e),
            ))
            return None

    def _run_sa_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle | None:
        """Run SA calculation stage."""
        try:
            # Check if there are SA exposures
            if not self._has_rows(data.sa_exposures):
                return SAResultBundle(
                    results=self._create_empty_sa_frame(),
                    calculation_audit=self._create_empty_sa_frame(),
                    errors=[],
                )

            result = self._sa_calculator.get_sa_result_bundle(data, config)
            # Accumulate SA errors
            if result.errors:
                for error in result.errors:
                    self._errors.append(PipelineError(
                        stage="sa_calculator",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="sa_calculator",
                error_type="sa_calculation_error",
                message=str(e),
            ))
            return SAResultBundle(
                results=self._create_empty_sa_frame(),
                calculation_audit=self._create_empty_sa_frame(),
                errors=[],
            )

    def _run_irb_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> IRBResultBundle | None:
        """Run IRB calculation stage."""
        try:
            # Check if there are IRB exposures
            if not self._has_rows(data.irb_exposures):
                return IRBResultBundle(
                    results=self._create_empty_irb_frame(),
                    expected_loss=self._create_empty_irb_frame(),
                    calculation_audit=self._create_empty_irb_frame(),
                    errors=[],
                )

            result = self._irb_calculator.get_irb_result_bundle(data, config)
            # Accumulate IRB errors
            if result.errors:
                for error in result.errors:
                    self._errors.append(PipelineError(
                        stage="irb_calculator",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="irb_calculator",
                error_type="irb_calculation_error",
                message=str(e),
            ))
            return IRBResultBundle(
                results=self._create_empty_irb_frame(),
                expected_loss=self._create_empty_irb_frame(),
                calculation_audit=self._create_empty_irb_frame(),
                errors=[],
            )

    def _run_slotting_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SlottingResultBundle | None:
        """Run Slotting calculation stage."""
        try:
            # Check if there are slotting exposures
            if data.slotting_exposures is None or not self._has_rows(data.slotting_exposures):
                return SlottingResultBundle(
                    results=self._create_empty_slotting_frame(),
                    calculation_audit=self._create_empty_slotting_frame(),
                    errors=[],
                )

            result = self._slotting_calculator.get_slotting_result_bundle(data, config)
            # Accumulate Slotting errors
            if result.errors:
                for error in result.errors:
                    self._errors.append(PipelineError(
                        stage="slotting_calculator",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="slotting_calculator",
                error_type="slotting_calculation_error",
                message=str(e),
            ))
            return SlottingResultBundle(
                results=self._create_empty_slotting_frame(),
                calculation_audit=self._create_empty_slotting_frame(),
                errors=[],
            )

    def _run_aggregator(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Run output aggregation stage."""
        try:
            result = self._aggregator.aggregate_with_audit(
                sa_bundle=sa_bundle,
                irb_bundle=irb_bundle,
                slotting_bundle=slotting_bundle,
                config=config,
            )
            # Accumulate aggregation errors
            if result.errors:
                for error in result.errors:
                    if isinstance(error, PipelineError):
                        self._errors.append(error)
                    else:
                        self._errors.append(PipelineError(
                            stage="aggregator",
                            error_type=getattr(error, "error_type", "unknown"),
                            message=getattr(error, "message", str(error)),
                        ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="aggregator",
                error_type="aggregation_error",
                message=str(e),
            ))
            return self._create_error_result()

    # =========================================================================
    # Private Methods - Utilities
    # =========================================================================

    def _has_rows(self, frame: pl.LazyFrame) -> bool:
        """Check if a LazyFrame has any rows."""
        try:
            schema = frame.collect_schema()
            if len(schema) == 0:
                return False
            return frame.head(1).collect().height > 0
        except Exception:
            return False

    def _create_error_result(self) -> AggregatedResultBundle:
        """Create error result when pipeline fails."""
        return AggregatedResultBundle(
            results=pl.LazyFrame({
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            }),
            errors=[self._convert_pipeline_error(e) for e in self._errors],
        )

    def _create_empty_sa_frame(self) -> pl.LazyFrame:
        """Create empty SA results frame."""
        return pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "risk_weight": pl.Series([], dtype=pl.Float64),
            "rwa_pre_factor": pl.Series([], dtype=pl.Float64),
            "supporting_factor": pl.Series([], dtype=pl.Float64),
            "rwa_post_factor": pl.Series([], dtype=pl.Float64),
        })

    def _create_empty_irb_frame(self) -> pl.LazyFrame:
        """Create empty IRB results frame."""
        return pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "pd_floored": pl.Series([], dtype=pl.Float64),
            "lgd_floored": pl.Series([], dtype=pl.Float64),
            "correlation": pl.Series([], dtype=pl.Float64),
            "k": pl.Series([], dtype=pl.Float64),
            "rwa": pl.Series([], dtype=pl.Float64),
        })

    def _create_empty_slotting_frame(self) -> pl.LazyFrame:
        """Create empty Slotting results frame."""
        return pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "slotting_category": pl.Series([], dtype=pl.String),
            "is_hvcre": pl.Series([], dtype=pl.Boolean),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "risk_weight": pl.Series([], dtype=pl.Float64),
            "rwa": pl.Series([], dtype=pl.Float64),
        })

    def _convert_pipeline_error(self, error: PipelineError) -> object:
        """Convert PipelineError to standard error format."""
        from rwa_calc.contracts.errors import CalculationError, ErrorSeverity, ErrorCategory

        return CalculationError(
            code=f"PIPELINE_{error.stage.upper()}",
            message=f"[{error.stage}] {error.error_type}: {error.message}",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.CALCULATION,
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_pipeline(
    data_path: str | Path | None = None,
    loader: LoaderProtocol | None = None,
) -> PipelineOrchestrator:
    """
    Create a pipeline orchestrator with default components.

    Args:
        data_path: Path to data directory (creates ParquetLoader)
        loader: Pre-configured loader (overrides data_path)

    Returns:
        PipelineOrchestrator ready for use

    Usage:
        # With data path (uses ParquetLoader)
        pipeline = create_pipeline(data_path="/path/to/data")

        # With custom loader
        pipeline = create_pipeline(loader=CSVLoader("/path/to/data"))

        # Without loader (use run_with_data)
        pipeline = create_pipeline()
    """
    from rwa_calc.engine.loader import ParquetLoader

    if loader is None and data_path is not None:
        loader = ParquetLoader(base_path=data_path)

    return PipelineOrchestrator(loader=loader)


def create_test_pipeline() -> PipelineOrchestrator:
    """
    Create a pipeline configured for test fixtures.

    Returns:
        PipelineOrchestrator with ParquetLoader pointing to test fixtures
    """
    from rwa_calc.engine.loader import create_test_loader

    return PipelineOrchestrator(loader=create_test_loader())
