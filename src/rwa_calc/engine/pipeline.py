"""
Pipeline Orchestrator for RWA Calculator.

Orchestrates the complete RWA calculation pipeline, wiring together:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA/IRB/Slotting Calculators -> Aggregation

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

import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    EquityResultBundle,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.protocols import (
    ClassifierProtocol,
    CRMProcessorProtocol,
    EquityCalculatorProtocol,
    HierarchyResolverProtocol,
    IRBCalculatorProtocol,
    LoaderProtocol,
    OutputAggregatorProtocol,
    RealEstateSplitterProtocol,
    SACalculatorProtocol,
    SlottingCalculatorProtocol,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.fx_rate_sync import extract_eur_gbp_rate
from rwa_calc.engine.materialise import (
    cleanup_spill_files,
    materialise_barrier,
    materialise_branches,
)
from rwa_calc.observability import clear_run_id, new_run_id, stage_timer

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


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
    8. Aggregation: Combine results, apply floor, generate summaries

    Usage:
        orchestrator = PipelineOrchestrator(
            loader=ParquetLoader(base_path),
            hierarchy_resolver=HierarchyResolver(),
            classifier=ExposureClassifier(),
            crm_processor=CRMProcessor(),
            sa_calculator=SACalculator(),
            irb_calculator=IRBCalculator(),
            slotting_calculator=SlottingCalculator(),
        )
        result = orchestrator.run(config)
    """

    def __init__(
        self,
        loader: LoaderProtocol | None = None,
        hierarchy_resolver: HierarchyResolverProtocol | None = None,
        classifier: ClassifierProtocol | None = None,
        crm_processor: CRMProcessorProtocol | None = None,
        re_splitter: RealEstateSplitterProtocol | None = None,
        sa_calculator: SACalculatorProtocol | None = None,
        irb_calculator: IRBCalculatorProtocol | None = None,
        slotting_calculator: SlottingCalculatorProtocol | None = None,
        equity_calculator: EquityCalculatorProtocol | None = None,
        output_aggregator: OutputAggregatorProtocol | None = None,
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
            output_aggregator: Output aggregator
            re_splitter: Real estate loan-splitter (CRR Art. 125/126,
                B3.1 Art. 124F/H). When None, a default
                ``RealEstateSplitter`` is created.
        """
        self._loader = loader
        self._hierarchy_resolver = hierarchy_resolver
        self._classifier = classifier
        self._crm_processor = crm_processor
        self._re_splitter = re_splitter
        self._sa_calculator = sa_calculator
        self._irb_calculator = irb_calculator
        self._slotting_calculator = slotting_calculator
        self._equity_calculator = equity_calculator
        self._output_aggregator = output_aggregator
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
            raise ValueError("No loader configured. Use run_with_data() or provide a loader.")

        # Reset errors for new run
        self._errors = []

        # Stage 1: Load data
        try:
            with stage_timer(logger, "loader"):
                raw_data = self._loader.load()
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="loader",
                    error_type="load_error",
                    message=str(e),
                )
            )
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

        run_id, run_id_token = new_run_id()
        run_start = time.perf_counter()
        try:
            logger.info(
                "pipeline run starting (framework=%s, permission_mode=%s)",
                config.framework.value,
                config.permission_mode.value,
                extra={
                    "stage": "pipeline",
                    "framework": config.framework.value,
                    "permission_mode": config.permission_mode.value,
                    "run_id": run_id,
                },
            )
            # Keep eur_gbp_rate in step with the loaded fx_rates table so
            # IRB SME correlation and RegulatoryThresholds use the same rate
            # as FX amount conversion. CRR-only: B3.1 thresholds are GBP-native.
            if config.is_crr and config.sync_eur_gbp_rate_from_fx_table:
                derived_rate = extract_eur_gbp_rate(data.fx_rates)
                if derived_rate is not None and derived_rate != config.eur_gbp_rate:
                    logger.warning(
                        "eur_gbp_rate auto-sync: replacing %s with %s from fx_rates table",
                        config.eur_gbp_rate,
                        derived_rate,
                    )
                    config = config.with_fx_rate(derived_rate)

            # Ensure components are initialized (config needed for framework-specific CRM)
            self._ensure_components_initialized(config)

            # IRB mode without model_permissions → all exposures fall back to SA.
            # The classifier forces all permission expressions to False when
            # has_model_permissions=False in IRB mode. We surface a pipeline-level
            # error so the user can see that per-model gating is off.
            if config.permission_mode == PermissionMode.IRB and data.model_permissions is None:
                logger.warning(
                    "IRB permission mode selected but no model_permissions data provided. "
                    "All exposures will route to SA; supply a model_permissions table "
                    "to enable IRB."
                )
                self._errors.append(
                    PipelineError(
                        stage="pipeline",
                        error_type="missing_model_permissions",
                        message=(
                            "IRB permission mode selected but no model_permissions "
                            "data was provided. All exposures will route to SA. "
                            "Supply a model_permissions table to enable per-model "
                            "IRB approach routing."
                        ),
                    )
                )

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

            # Stage 4b: Real estate loan-splitter (CRR Art. 125/126,
            # B3.1 Art. 124F/H). Materialises the secured RE row and the
            # uncollateralised residual row for property-collateralised SA
            # exposures. No-op when no rows carry re_split_mode.
            crm_adjusted = self._run_re_splitter(crm_adjusted, config)
            if crm_adjusted is None:
                return self._create_error_result()

            # Stages 5-8: Calculation and aggregation
            result = self._run_calculators(crm_adjusted, config)

            # Add loader validation errors and pipeline errors to result
            loader_errors = list(data.errors) if data.errors else []
            pipeline_errors = [self._convert_pipeline_error(e) for e in self._errors]
            extra_errors = loader_errors + pipeline_errors
            if extra_errors:
                all_errors = list(result.errors) + extra_errors
                result = replace(result, errors=all_errors)

            total_ms = round((time.perf_counter() - run_start) * 1000.0, 2)
            logger.info(
                "pipeline run finished in %.1f ms (%d errors)",
                total_ms,
                len(result.errors),
                extra={
                    "stage": "pipeline",
                    "elapsed_ms": total_ms,
                    "error_count": len(result.errors),
                },
            )
            return result
        finally:
            # Clean up any temp parquet files created during materialization
            cleanup_spill_files()
            clear_run_id(run_id_token)

    # =========================================================================
    # Private Methods - Component Initialization
    # =========================================================================

    def _ensure_components_initialized(self, config: CalculationConfig | None = None) -> None:
        """Ensure all required components are initialized.

        Args:
            config: Calculation config, used to create framework-specific CRM processor
        """
        from rwa_calc.engine.classifier import ExposureClassifier
        from rwa_calc.engine.crm.processor import CRMProcessor
        from rwa_calc.engine.equity.calculator import EquityCalculator
        from rwa_calc.engine.hierarchy import HierarchyResolver
        from rwa_calc.engine.irb.calculator import IRBCalculator
        from rwa_calc.engine.re_splitter import RealEstateSplitter
        from rwa_calc.engine.sa.calculator import SACalculator
        from rwa_calc.engine.slotting.calculator import SlottingCalculator

        if self._hierarchy_resolver is None:
            self._hierarchy_resolver = HierarchyResolver()
        if self._classifier is None:
            self._classifier = ExposureClassifier()
        if self._crm_processor is None:
            is_b31 = config.is_basel_3_1 if config else False
            self._crm_processor = CRMProcessor(is_basel_3_1=is_b31)
        if self._re_splitter is None:
            self._re_splitter = RealEstateSplitter()
        if self._sa_calculator is None:
            self._sa_calculator = SACalculator()
        if self._irb_calculator is None:
            self._irb_calculator = IRBCalculator()
        if self._slotting_calculator is None:
            self._slotting_calculator = SlottingCalculator()
        if self._equity_calculator is None:
            self._equity_calculator = EquityCalculator()
        if self._output_aggregator is None:
            from rwa_calc.engine.aggregator import OutputAggregator

            self._output_aggregator = OutputAggregator()

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
            with stage_timer(logger, "hierarchy_resolver"):
                result = self._hierarchy_resolver.resolve(data, config)
            # Accumulate hierarchy errors
            if result.hierarchy_errors:
                for error in result.hierarchy_errors:
                    self._errors.append(
                        PipelineError(
                            stage="hierarchy_resolver",
                            error_type=getattr(error, "error_type", "unknown"),
                            message=getattr(error, "message", str(error)),
                            context=getattr(error, "context", {}),
                        )
                    )
            return result
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="hierarchy_resolver",
                    error_type="resolution_error",
                    message=str(e),
                )
            )
            return None

    def _run_classifier(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle | None:
        """Run classification stage."""
        try:
            with stage_timer(logger, "classifier"):
                result = self._classifier.classify(data, config)
            # Accumulate classification errors
            if result.classification_errors:
                for error in result.classification_errors:
                    self._errors.append(
                        PipelineError(
                            stage="classifier",
                            error_type=getattr(error, "error_type", "unknown"),
                            message=getattr(error, "message", str(error)),
                            context=getattr(error, "context", {}),
                        )
                    )
            return result
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="classifier",
                    error_type="classification_error",
                    message=str(e),
                )
            )
            return None

    def _run_equity_calculator(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle | None:
        """Run Equity calculation stage."""
        try:
            with stage_timer(logger, "equity_calculator"):
                result = self._equity_calculator.get_equity_result_bundle(data, config)
            # Accumulate Equity errors
            if result.errors:
                for error in result.errors:
                    self._errors.append(
                        PipelineError(
                            stage="equity_calculator",
                            error_type=getattr(error, "error_type", "unknown"),
                            message=getattr(error, "message", str(error)),
                        )
                    )
            return result
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="equity_calculator",
                    error_type="equity_calculation_error",
                    message=str(e),
                )
            )
            return None

    # =========================================================================
    # Private Methods - Calculation
    # =========================================================================

    def _run_crm_processor(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle | None:
        """Run CRM processing on the unified exposure frame."""
        try:
            with stage_timer(logger, "crm_processor"):
                result = self._crm_processor.get_crm_unified_bundle(data, config)
            if result.crm_errors:
                for error in result.crm_errors:
                    self._errors.append(
                        PipelineError(
                            stage="crm_processor",
                            error_type=error.code,
                            message=error.message,
                        )
                    )
            return result
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="crm_processor",
                    error_type="crm_error",
                    message=str(e),
                )
            )
            return None

    def _run_re_splitter(
        self,
        crm_adjusted: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle | None:
        """Run the real estate loan-splitter stage."""
        try:
            with stage_timer(logger, "re_splitter"):
                result = self._re_splitter.split(crm_adjusted, config)
            if result.crm_errors:
                # Splitter accumulates errors into the CRM bucket so existing
                # error reporting continues to capture them.
                for error in result.crm_errors:
                    if error in crm_adjusted.crm_errors:
                        # Already accounted for upstream — skip duplicates.
                        continue
                    self._errors.append(
                        PipelineError(
                            stage="re_splitter",
                            error_type=error.code,
                            message=error.message,
                        )
                    )
            return result
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="re_splitter",
                    error_type="re_split_error",
                    message=str(e),
                )
            )
            return None

    def _run_calculators(
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
            with stage_timer(logger, "calculators"):
                exposures = crm_adjusted.exposures  # Lazy (shallow plan on materialised data)

                # Materialise CRM output before calculator split.
                # Even though CRM now materialises inputs before guarantee joins,
                # the guarantee plan (joins + finalize + audit) is still deep enough
                # that collect_all would re-evaluate it per branch without this.
                # In streaming mode, spills to disk instead of loading into memory.
                exposures = materialise_barrier(exposures, config, "pipeline_pre_branch")

                # For Basel 3.1 output floor: SA-equivalent RW needed on all rows
                if config.output_floor.enabled:
                    exposures = self._sa_calculator.calculate_unified(exposures, config)

                # Split once by approach
                is_irb = (pl.col("approach") == ApproachType.FIRB.value) | (
                    pl.col("approach") == ApproachType.AIRB.value
                )
                is_slotting = pl.col("approach") == ApproachType.SLOTTING.value

                sa_branch = exposures.filter(~is_irb & ~is_slotting)
                irb_branch = exposures.filter(is_irb)
                slotting_branch = exposures.filter(is_slotting)

                # Process each branch (all still lazy)
                if config.output_floor.enabled:
                    # SA already calculated by calculate_unified above —
                    # add aggregator columns that calculate_branch normally provides
                    sa_result = sa_branch.with_columns(
                        pl.col("approach").alias("approach_applied"),
                        pl.col("rwa_post_factor").alias("rwa_final"),
                    )
                else:
                    sa_result = self._sa_calculator.calculate_branch(sa_branch, config)

                irb_result = self._irb_calculator.calculate_branch(irb_branch, config)
                slotting_result = self._slotting_calculator.calculate_branch(
                    slotting_branch, config
                )

                # Collect all branches. In cpu mode, uses collect_all with CSE so
                # shared upstream computes once. In streaming mode, sinks each
                # branch to disk sequentially (peak memory = 1 branch at a time).
                sa_df, irb_df, slotting_df = materialise_branches(
                    [sa_result, irb_result, slotting_result],
                    config,
                    ["sa_branch", "irb_branch", "slotting_branch"],
                )
                sa_rows = sa_df.height
                irb_rows = irb_df.height
                slotting_rows = slotting_df.height
                logger.info(
                    "calculators materialised %d rows (sa=%d, irb=%d, slotting=%d)",
                    sa_rows + irb_rows + slotting_rows,
                    sa_rows,
                    irb_rows,
                    slotting_rows,
                    extra={
                        "stage": "calculators",
                        "row_count": sa_rows + irb_rows + slotting_rows,
                    },
                )

                # Equity — separate path (not in unified frame)
                equity_bundle = self._run_equity_calculator(crm_adjusted, config)

                # Aggregate from already-collected DataFrames
                return self._aggregate_results(sa_df, irb_df, slotting_df, equity_bundle, config)
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="calculators",
                    error_type="calculation_error",
                    message=str(e),
                )
            )
            return self._create_error_result()

    def _aggregate_results(
        self,
        sa_df: pl.DataFrame,
        irb_df: pl.DataFrame,
        slotting_df: pl.DataFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Aggregate results from collect_all DataFrames."""
        try:
            with stage_timer(logger, "aggregator"):
                return self._output_aggregator.aggregate(
                    sa_results=sa_df.lazy(),
                    irb_results=irb_df.lazy(),
                    slotting_results=slotting_df.lazy(),
                    equity_bundle=equity_bundle,
                    config=config,
                )
        except Exception as e:
            self._errors.append(
                PipelineError(
                    stage="aggregator",
                    error_type="aggregation_error",
                    message=str(e),
                )
            )
            return self._create_error_result()

    # =========================================================================
    # Private Methods - Utilities
    # =========================================================================

    def _create_error_result(self) -> AggregatedResultBundle:
        """Create error result when pipeline fails."""
        return AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": pl.Series([], dtype=pl.String),
                    "approach_applied": pl.Series([], dtype=pl.String),
                    "exposure_class": pl.Series([], dtype=pl.String),
                    "ead_final": pl.Series([], dtype=pl.Float64),
                    "risk_weight": pl.Series([], dtype=pl.Float64),
                    "rwa_final": pl.Series([], dtype=pl.Float64),
                }
            ),
            errors=[self._convert_pipeline_error(e) for e in self._errors],
        )

    def _convert_pipeline_error(self, error: PipelineError) -> object:
        """Convert PipelineError to standard error format."""
        from rwa_calc.contracts.errors import CalculationError, ErrorCategory, ErrorSeverity

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
