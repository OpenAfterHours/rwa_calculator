"""
Fold orchestrator for the RWA pipeline (migration Phase 4).

Pipeline position:
    PipelineOrchestrator (engine/pipeline.py facade) -> run_stages over the
    literal stage registry (engine/registry.py) -> stage adapter modules
    (engine/stages/*)

Key responsibilities:
- ``run_stages``: a pure fold — thread one immutable ``PipelineContext``
  through the registered stages, wrapping each in ``stage_timer`` and
  applying the stage's declared failure policy. No domain logic lives here.
- ``StageSpec`` / ``StageFn``: the final uniform stage shape,
  ``Stage(ctx, rulepack, run_config) -> PipelineContext``.
- Artifact keys for every cross-stage handoff (the typed replacement for
  the orchestrator's former ``self._*`` scratch attributes).
- ``StageComponents`` / ``build_components``: adapter-era dependency wiring
  for today's class-shaped stages. Components are built per run — never
  cached across runs — so the historical stale-``CRMProcessor`` failure
  mode (framework switch on a reused orchestrator) is unrepresentable.
- The error channels: ``STAGE_ERRORS`` carries stage data-quality
  ``CalculationError``s verbatim (original code/severity/category/context
  preserved — the unified channel, P2.21); ``PipelineError`` +
  ``convert_pipeline_error`` record stage CRASHES only, as
  ``PIPELINE_<STAGE>`` codes (a crash has no original code).

References:
- CRR Art. 92: Own funds requirements (the 8% multiplier the pipeline serves)
- CRR Art. 107: Approaches to credit risk (selects SA vs IRB stage wiring)
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.context import ArtifactKey, PipelineContext
from rwa_calc.observability import stage_timer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import polars as pl

    from rwa_calc.contracts.bundles import (
        ClassifiedExposuresBundle,
        CRMAdjustedBundle,
        EquityResultBundle,
        RawDataBundle,
        ResolvedHierarchyBundle,
    )
    from rwa_calc.contracts.config import CalculationConfig, RunConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.contracts.protocols import (
        ClassifierProtocol,
        CRMProcessorProtocol,
        EquityCalculatorProtocol,
        HierarchyResolverProtocol,
        IRBCalculatorProtocol,
        OutputAggregatorProtocol,
        RealEstateSplitterProtocol,
        SACalculatorProtocol,
        SecuritisationAllocatorProtocol,
        SlottingCalculatorProtocol,
    )
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


# =============================================================================
# Error types (the stage-CRASH channel — PIPELINE_<STAGE> codes)
# =============================================================================


@dataclass
class PipelineError:
    """A stage crash (unexpected exception) during pipeline execution.

    Crash-only since the error-channel unification slice (P2.21): stage
    data-quality ``CalculationError``s travel the STAGE_ERRORS channel
    verbatim and are never converted into this type.
    """

    stage: str
    error_type: str
    message: str
    context: dict = field(default_factory=dict)


def convert_pipeline_error(error: PipelineError) -> CalculationError:
    """Convert a stage-crash PipelineError to the standard error format.

    Crashes have no original code, so the ``PIPELINE_<STAGE>`` code is
    minted here. Real data-quality CalculationErrors never pass through
    this function — they reach the result verbatim via STAGE_ERRORS.
    """
    from rwa_calc.contracts.errors import CalculationError, ErrorCategory, ErrorSeverity

    return CalculationError(
        code=f"PIPELINE_{error.stage.upper()}",
        message=f"[{error.stage}] {error.error_type}: {error.message}",
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.CALCULATION,
    )


def create_error_result(errors: Sequence[PipelineError]) -> AggregatedResultBundle:
    """Create the error result returned when the pipeline halts.

    The empty results frame comes from the aggregator-exit contract so the
    error bundle satisfies the same sealed-field registration as a
    successful run (schema-complete, zero rows).
    """
    from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE

    return AggregatedResultBundle(
        results=AGGREGATOR_EXIT_EDGE.empty_frame(),
        errors=[convert_pipeline_error(e) for e in errors],
    )


# =============================================================================
# Artifact keys — the typed cross-stage handoffs
# =============================================================================

# Whole-bundle artifacts (adapter-era grain: stages still exchange Phase 3
# sealed bundles; later slices decompose these into per-frame keys as each
# stage converts to the uniform anatomy).
RAW_DATA: ArtifactKey[RawDataBundle] = ArtifactKey("raw_data")
RESOLVED_HIERARCHY: ArtifactKey[ResolvedHierarchyBundle] = ArtifactKey("resolved_hierarchy")
CLASSIFIED: ArtifactKey[ClassifiedExposuresBundle] = ArtifactKey("classified")
CRM_ADJUSTED: ArtifactKey[CRMAdjustedBundle] = ArtifactKey("crm_adjusted")
EQUITY_RESULT: ArtifactKey[EquityResultBundle | None] = ArtifactKey("equity_result")
RESULT: ArtifactKey[AggregatedResultBundle] = ArtifactKey("result")

# Side artifacts (formerly orchestrator ``self._*`` scratch).
SECURITISATION_RESOLVED: ArtifactKey[pl.LazyFrame | None] = ArtifactKey("securitisation_resolved")

# Eager branch results (branch-edge branded DataFrames from the shared
# calculator collect).
SA_RESULTS: ArtifactKey[pl.DataFrame] = ArtifactKey("sa_results")
IRB_RESULTS: ArtifactKey[pl.DataFrame] = ArtifactKey("irb_results")
SLOTTING_RESULTS: ArtifactKey[pl.DataFrame] = ArtifactKey("slotting_results")

# Error channels, merged in a fixed order by the facade:
# - STAGE_ERRORS: stage data-quality CalculationErrors, verbatim — original
#   code/severity/category and all reference fields preserved (the unified
#   channel, P2.21).
# - PIPELINE_ERRORS: stage crashes only (converted to PIPELINE_<STAGE>).
# - BRANCH_ERRORS: calculator-branch warnings, merged by the aggregate
#   stage ahead of the facade merge (original codes).
PIPELINE_ERRORS: ArtifactKey[tuple[PipelineError, ...]] = ArtifactKey("pipeline_errors")
STAGE_ERRORS: ArtifactKey[tuple[CalculationError, ...]] = ArtifactKey("stage_errors")
BRANCH_ERRORS: ArtifactKey[tuple[CalculationError, ...]] = ArtifactKey("branch_errors")

# Set by the fold when a stage raised; value is the failed StageSpec's halt
# policy ("immediate" | "merged"). Absent on a clean run.
HALTED: ArtifactKey[str] = ArtifactKey("halted")


# =============================================================================
# Stage shape — the final signature (Phase 4 freeze)
# =============================================================================

if TYPE_CHECKING:
    StageFn = Callable[[PipelineContext, "RulepackV0", "RunConfig"], PipelineContext]


@dataclass(frozen=True)
class StageSpec:
    """One registered pipeline stage.

    Attributes:
        name: ``stage_timer`` label (pinned by the observability tests).
        fn: the stage function — ``Stage(ctx, rulepack, run_config)``.
        error_type: ``PipelineError.error_type`` recorded when ``fn`` raises.
        halt: failure policy when ``fn`` raises. ``"immediate"`` — the run
            returns the bare error result (no downstream error merge);
            ``"merged"`` — the error result still flows through the facade's
            error merge (loader/CCR/branch channels appended). Both policies
            are verbatim ports of the pre-fold per-stage behaviour.
    """

    name: str
    fn: StageFn
    error_type: str
    halt: Literal["immediate", "merged"] = "immediate"


def run_stages(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    run_config: RunConfig,
    stages: Sequence[StageSpec],
) -> PipelineContext:
    """Fold the context through the registered stages.

    Each stage runs under its own ``stage_timer``. A raising stage appends
    a ``PipelineError`` to the PIPELINE_ERRORS channel, marks the context
    HALTED with the stage's halt policy, and stops the fold — the facade
    owns turning a halted context into the error result. Stages whose
    failure policy is "swallow and continue" (securitisation allocator,
    equity) implement it inside their own stage body.
    """
    for spec in stages:
        try:
            with stage_timer(logger, spec.name):
                ctx = spec.fn(ctx, rulepack, run_config)
        except Exception as exc:  # noqa: BLE001 — per-stage failure policy, never silent
            ctx = append_pipeline_error(
                ctx,
                PipelineError(stage=spec.name, error_type=spec.error_type, message=str(exc)),
            )
            return ctx.put(HALTED, spec.halt)
    return ctx


def append_pipeline_error(ctx: PipelineContext, error: PipelineError) -> PipelineContext:
    """Append one stage-crash PipelineError to the PIPELINE_ERRORS channel."""
    return ctx.put(PIPELINE_ERRORS, (*ctx.get_or(PIPELINE_ERRORS, ()), error))


def append_stage_errors(ctx: PipelineContext, *errors: CalculationError) -> PipelineContext:
    """Append stage data-quality CalculationErrors to STAGE_ERRORS, verbatim.

    The unified error channel (error-channel slice, P2.21): bundle-attached
    errors keep their original code, severity, category, and every reference
    field all the way to ``AggregatedResultBundle.errors`` — they are never
    rewritten to ``PIPELINE_<STAGE>`` codes.
    """
    if not errors:
        return ctx
    return ctx.put(STAGE_ERRORS, (*ctx.get_or(STAGE_ERRORS, ()), *errors))


# =============================================================================
# Adapter-era component wiring
# =============================================================================


@dataclass(frozen=True)
class StageComponents:
    """The class-shaped stage implementations the adapters invoke.

    Adapter-era scaffolding: as each stage converts to the uniform
    function-module anatomy its slot here is deleted; the dataclass goes
    with the last class-shaped stage.
    """

    securitisation_allocator: SecuritisationAllocatorProtocol
    hierarchy_resolver: HierarchyResolverProtocol
    classifier: ClassifierProtocol
    crm_processor: CRMProcessorProtocol
    re_splitter: RealEstateSplitterProtocol
    sa_calculator: SACalculatorProtocol
    irb_calculator: IRBCalculatorProtocol
    slotting_calculator: SlottingCalculatorProtocol
    equity_calculator: EquityCalculatorProtocol
    output_aggregator: OutputAggregatorProtocol


COMPONENTS: ArtifactKey[StageComponents] = ArtifactKey("components")


def build_components(
    config: CalculationConfig,
    *,
    securitisation_allocator: SecuritisationAllocatorProtocol | None = None,
    hierarchy_resolver: HierarchyResolverProtocol | None = None,
    classifier: ClassifierProtocol | None = None,
    crm_processor: CRMProcessorProtocol | None = None,
    re_splitter: RealEstateSplitterProtocol | None = None,
    sa_calculator: SACalculatorProtocol | None = None,
    irb_calculator: IRBCalculatorProtocol | None = None,
    slotting_calculator: SlottingCalculatorProtocol | None = None,
    equity_calculator: EquityCalculatorProtocol | None = None,
    output_aggregator: OutputAggregatorProtocol | None = None,
) -> StageComponents:
    """Build per-run stage components, honouring injected overrides.

    Defaults are constructed fresh every run. ``CRMProcessor`` no longer carries
    constructor regime-state: it reads the framework per-method from the
    *effective* config (post FX-rate sync) each entry point already receives, so
    a single instance is framework-correct under either regime. The per-run
    rebuild still isolates frameworks for any component that does cache state.
    """
    from rwa_calc.engine.aggregator import OutputAggregator
    from rwa_calc.engine.crm.processor import CRMProcessor
    from rwa_calc.engine.equity.calculator import EquityCalculator
    from rwa_calc.engine.irb.calculator import IRBCalculator
    from rwa_calc.engine.sa.calculator import SACalculator
    from rwa_calc.engine.securitisation.allocator import SecuritisationAllocator
    from rwa_calc.engine.slotting.calculator import SlottingCalculator
    from rwa_calc.engine.stages.classify import ExposureClassifier
    from rwa_calc.engine.stages.hierarchy import HierarchyResolver
    from rwa_calc.engine.stages.re_split import RealEstateSplitter

    return StageComponents(
        securitisation_allocator=securitisation_allocator or SecuritisationAllocator(),
        hierarchy_resolver=hierarchy_resolver or HierarchyResolver(),
        classifier=classifier or ExposureClassifier(),
        crm_processor=crm_processor or CRMProcessor(),
        re_splitter=re_splitter or RealEstateSplitter(),
        sa_calculator=sa_calculator or SACalculator(),
        irb_calculator=irb_calculator or IRBCalculator(),
        slotting_calculator=slotting_calculator or SlottingCalculator(),
        equity_calculator=equity_calculator or EquityCalculator(),
        output_aggregator=output_aggregator or OutputAggregator(),
    )
