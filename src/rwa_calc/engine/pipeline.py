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
    EquityResultBundle,
)
from rwa_calc.contracts.protocols import (
    LoaderProtocol,
    HierarchyResolverProtocol,
    ClassifierProtocol,
    CRMProcessorProtocol,
    SACalculatorProtocol,
    IRBCalculatorProtocol,
    SlottingCalculatorProtocol,
    EquityCalculatorProtocol,
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
        equity_calculator: EquityCalculatorProtocol | None = None,
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
            equity_calculator: Equity calculator
            aggregator: Output aggregator
        """
        self._loader = loader
        self._hierarchy_resolver = hierarchy_resolver
        self._classifier = classifier
        self._crm_processor = crm_processor
        self._sa_calculator = sa_calculator
        self._irb_calculator = irb_calculator
        self._slotting_calculator = slotting_calculator
        self._equity_calculator = equity_calculator
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

        Uses single-pass architecture: all approach-specific calculators
        run sequentially on one unified LazyFrame, avoiding plan tree
        duplication and mid-pipeline materialisation.

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

        # Validate input data values
        self._validate_input_data(data)

        # Stage 2: Resolve hierarchies
        resolved = self._run_hierarchy_resolver(data, config)
        if resolved is None:
            return self._create_error_result()

        # Stage 3: Classify exposures
        classified = self._run_classifier(resolved, config)
        if classified is None:
            return self._create_error_result()

        # Stage 4: Apply CRM (unified — no fan-out split)
        crm_adjusted = self._run_crm_processor_unified(classified, config)
        if crm_adjusted is None:
            return self._create_error_result()

        # Stages 5-8: Single-pass calculation and aggregation
        result = self._run_single_pass(crm_adjusted, config)

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
                equity_results=result.equity_results,
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
        from rwa_calc.engine.equity.calculator import EquityCalculator
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
        if self._equity_calculator is None:
            self._equity_calculator = EquityCalculator()
        if self._aggregator is None:
            self._aggregator = OutputAggregator()

    # =========================================================================
    # Private Methods - Stage Execution
    # =========================================================================

    def _validate_input_data(self, data: RawDataBundle) -> None:
        """Validate input data values against column constraints."""
        try:
            from rwa_calc.contracts.validation import validate_bundle_values

            validation_errors = validate_bundle_values(data)
            for error in validation_errors:
                self._errors.append(PipelineError(
                    stage="input_validation",
                    error_type="invalid_value",
                    message=error.message,
                ))
        except Exception as e:
            self._errors.append(PipelineError(
                stage="input_validation",
                error_type="validation_error",
                message=f"Value validation failed: {e}",
            ))

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
            return None

    def _run_irb_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> IRBResultBundle | None:
        """Run IRB calculation stage."""
        try:
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
            return None

    def _run_slotting_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SlottingResultBundle | None:
        """Run Slotting calculation stage."""
        try:
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
            return None

    def _run_equity_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle | None:
        """Run Equity calculation stage."""
        try:
            result = self._equity_calculator.get_equity_result_bundle(data, config)
            # Accumulate Equity errors
            if result.errors:
                for error in result.errors:
                    self._errors.append(PipelineError(
                        stage="equity_calculator",
                        error_type=getattr(error, "error_type", "unknown"),
                        message=getattr(error, "message", str(error)),
                    ))
            return result
        except Exception as e:
            self._errors.append(PipelineError(
                stage="equity_calculator",
                error_type="equity_calculation_error",
                message=str(e),
            ))
            return None

    def _run_aggregator(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Run output aggregation stage."""
        try:
            result = self._aggregator.aggregate_with_audit(
                sa_bundle=sa_bundle,
                irb_bundle=irb_bundle,
                slotting_bundle=slotting_bundle,
                config=config,
                equity_bundle=equity_bundle,
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
    # Private Methods - Single-Pass Pipeline
    # =========================================================================

    def _run_crm_processor_unified(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle | None:
        """Run CRM processing without fan-out split (single-pass mode)."""
        try:
            result = self._crm_processor.get_crm_unified_bundle(data, config)
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

    def _run_single_pass(
        self,
        crm_adjusted: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Split-once calculation with parallel collect.

        Splits the CRM-adjusted frame by approach, runs each calculator
        on its subset, then collects all three branches in parallel via
        pl.collect_all(). CSE (Common Subplan Elimination) ensures the
        shared CRM upstream computes only once.
        """
        from rwa_calc.domain.enums import ApproachType

        try:
            exposures = crm_adjusted.exposures  # Lazy (materialised at init_ead)

            # Materialise CRM plan before calculator split.
            # CRM output is a deep lazy plan; without this, collect_all
            # re-optimizes it 3× (once per SA/IRB/Slotting branch).
            exposures = exposures.collect().lazy()

            # For Basel 3.1 output floor: SA-equivalent RW needed on all rows
            if config.output_floor.enabled:
                exposures = self._sa_calculator.calculate_unified(exposures, config)

            # Split once by approach
            is_irb = (
                (pl.col("approach") == ApproachType.FIRB.value)
                | (pl.col("approach") == ApproachType.AIRB.value)
            )
            is_slotting = pl.col("approach") == ApproachType.SLOTTING.value

            sa_branch = exposures.filter(~is_irb & ~is_slotting)
            irb_branch = exposures.filter(is_irb)
            slotting_branch = exposures.filter(is_slotting)

            # Process each branch (all still lazy)
            if config.output_floor.enabled:
                # SA already calculated by calculate_unified above
                sa_result = sa_branch
            else:
                sa_result = self._sa_calculator.calculate_branch(sa_branch, config)

            irb_result = self._irb_calculator.calculate_branch(irb_branch, config)
            slotting_result = self._slotting_calculator.calculate_branch(
                slotting_branch, config
            )

            # Standardize output columns on each branch
            sa_result = self._standardize_branch_output(sa_result)
            irb_result = self._standardize_branch_output(irb_result)
            slotting_result = self._standardize_branch_output(slotting_result)

            # Collect all in parallel — CSE computes shared upstream once.
            # Force cpu engine: streaming doesn't support CSE, so each branch
            # would re-execute the full CRM plan independently (~9x slower).
            sa_df, irb_df, slotting_df = pl.collect_all(
                [sa_result, irb_result, slotting_result],
            )

            # Equity — separate path (not in unified frame)
            equity_bundle = self._run_equity_calculator(crm_adjusted, config)

            # Aggregate from already-collected DataFrames
            return self._aggregate_single_pass(
                sa_df, irb_df, slotting_df, equity_bundle, config
            )
        except Exception as e:
            self._errors.append(PipelineError(
                stage="single_pass",
                error_type="single_pass_error",
                message=str(e),
            ))
            return self._create_error_result()

    @staticmethod
    def _standardize_branch_output(exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Add approach_applied and rwa_final columns for aggregation."""
        schema = exposures.collect_schema()
        cols = []

        if "approach" in schema.names():
            cols.append(pl.col("approach").alias("approach_applied"))

        if "rwa_post_factor" in schema.names():
            cols.append(
                pl.coalesce(
                    pl.col("rwa_post_factor"),
                    pl.col("rwa") if "rwa" in schema.names() else pl.lit(0.0),
                ).alias("rwa_final")
            )
        elif "rwa" in schema.names():
            cols.append(pl.col("rwa").alias("rwa_final"))

        if cols:
            exposures = exposures.with_columns(cols)

        return exposures

    def _aggregate_single_pass(
        self,
        sa_df: pl.DataFrame,
        irb_df: pl.DataFrame,
        slotting_df: pl.DataFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Aggregate results from collect_all DataFrames."""
        try:
            # Per-approach results — already separated, no filtering needed
            sa_results = sa_df.lazy()
            irb_results = irb_df.lazy()
            slotting_results = slotting_df.lazy()

            # Combine for summaries (data already materialised — cheap concat)
            combined = pl.concat(
                [sa_df, irb_df, slotting_df], how="diagonal_relaxed"
            ).lazy()

            # Concat equity if present
            equity_results = None
            if equity_bundle and equity_bundle.results is not None:
                equity_prepared = equity_bundle.results.with_columns([
                    pl.lit("EQUITY").alias("approach_applied"),
                    pl.col(
                        "rwa" if "rwa" in equity_bundle.results.collect_schema().names()
                        else "rwa_final"
                    ).alias("rwa_final"),
                ])
                schema = equity_prepared.collect_schema()
                if "exposure_class" not in schema.names():
                    equity_prepared = equity_prepared.with_columns(
                        pl.lit("equity").alias("exposure_class")
                    )
                combined = pl.concat(
                    [combined, equity_prepared], how="diagonal_relaxed"
                )
                equity_results = equity_bundle.results

            # Generate summaries using the aggregator's methods
            pre_crm_summary = self._aggregator._generate_pre_crm_summary(combined)
            post_crm_detailed = self._aggregator._generate_post_crm_detailed(combined)
            post_crm_summary = self._aggregator._generate_post_crm_summary(
                post_crm_detailed
            )
            summary_by_class = self._aggregator._generate_summary_by_class(
                post_crm_detailed
            )
            summary_by_approach = self._aggregator._generate_summary_by_approach(
                post_crm_detailed
            )

            # Apply output floor if enabled
            floor_impact = None
            if config.output_floor.enabled:
                combined, floor_impact = self._aggregator._apply_floor_with_impact(
                    combined,
                    combined,  # SA-equivalent RW already joined by SA calculator
                    config,
                )

            # Supporting factor impact
            supporting_factor_impact = None
            if config.supporting_factors.enabled:
                supporting_factor_impact = (
                    self._aggregator._generate_supporting_factor_impact(combined)
                )

            return AggregatedResultBundle(
                results=combined,
                sa_results=sa_results,
                irb_results=irb_results,
                slotting_results=slotting_results,
                equity_results=equity_results,
                floor_impact=floor_impact,
                supporting_factor_impact=supporting_factor_impact,
                summary_by_class=summary_by_class,
                summary_by_approach=summary_by_approach,
                pre_crm_summary=pre_crm_summary,
                post_crm_detailed=post_crm_detailed,
                post_crm_summary=post_crm_summary,
                errors=[],
            )
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
