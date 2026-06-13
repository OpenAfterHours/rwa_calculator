"""
Pipeline Orchestrator facade for the RWA Calculator.

Orchestrates the complete RWA calculation pipeline by folding a
PipelineContext through the literal stage registry:
    Loader -> securitisation -> hierarchy -> CCR -> classifier -> CRM
        -> RE-split -> calculators -> equity -> aggregation

Pipeline position:
    Entry point for full pipeline execution. The stage fold itself lives in
    ``engine/orchestrator.py``; the ordered stage list in
    ``engine/registry.py``; per-stage adapters in ``engine/stages/``.

Key responsibilities:
- Run lifecycle: run_id binding, edge capture, stage timing surface,
  audit-artifact persistence — wrapped around the pure stage fold.
- EUR/GBP FX-rate sync: finalise the effective config (CRR-only) BEFORE
  components and the rulepack are built, so the fold sees one immutable
  config per run.
- Per-run component construction (injected overrides honoured) and the
  Rulepack-v0 build.
- Error-channel merge (unified, P2.21): loader/securitisation bundle
  errors, then stage data-quality errors (STAGE_ERRORS — original
  codes/severity/category preserved verbatim), then converted stage-crash
  PIPELINE_* errors; branch-calculator warnings are already on
  ``result.errors`` from the aggregate stage.

Usage:
    from rwa_calc.engine.pipeline import create_pipeline

    pipeline = create_pipeline()
    result = pipeline.run(config)

    # Or with pre-loaded data:
    result = pipeline.run_with_data(raw_data, config)

References:
- CRR Art. 92: Own funds requirements (the 8% multiplier the pipeline serves)
- CRR Art. 107: Approaches to credit risk (selects SA vs IRB stage wiring)
- CRR Art. 110: Treatment of credit risk adjustments (provision accumulation)
- PRA PS1/26 (Basel 3.1): Output floor wiring (CRR Art. 92(3a)) and revised
  SA/IRB stage order effective 1 Jan 2027
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rwa_calc.contracts.context import PipelineContext
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.fx_rate_sync import extract_eur_gbp_rate
from rwa_calc.engine.materialise import (
    begin_edge_capture,
    current_edge_events,
    end_edge_capture,
)
from rwa_calc.engine.orchestrator import (
    BRANCH_ERRORS,
    COMPONENTS,
    HALTED,
    PIPELINE_ERRORS,
    RAW_DATA,
    RESULT,
    SECURITISATION_RESOLVED,
    STAGE_ERRORS,
    PipelineError,
    build_components,
    convert_pipeline_error,
    create_error_result,
    run_stages,
)
from rwa_calc.engine.registry import PIPELINE_STAGES
from rwa_calc.observability import clear_run_id, new_run_id, stage_timer
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig
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
        SecuritisationAllocatorProtocol,
        SlottingCalculatorProtocol,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "PipelineError",
    "PipelineOrchestrator",
    "create_pipeline",
    "create_test_pipeline",
]


# =============================================================================
# Pipeline Orchestrator Facade
# =============================================================================


class PipelineOrchestrator:
    """
    Orchestrate the complete RWA calculation pipeline.

    Implements PipelineProtocol over the Phase 4 fold orchestrator: the
    stage sequence is the literal ``engine/registry.PIPELINE_STAGES`` list,
    folded by ``engine/orchestrator.run_stages``. This facade owns the run
    lifecycle (run_id, edge capture, FX-rate sync, error merge, audit
    persistence) and the per-run component wiring.

    Components can be injected for testing or customisation; defaults are
    built fresh every run from the effective config (never cached across
    runs — a framework switch on a reused orchestrator gets framework-fresh
    components).

    Usage:
        orchestrator = PipelineOrchestrator(loader=ParquetLoader(base_path))
        result = orchestrator.run(config)
    """

    def __init__(
        self,
        loader: LoaderProtocol | None = None,
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
    ) -> None:
        """
        Initialize the pipeline facade.

        Args:
            loader: Data loader (optional - required for run())
            securitisation_allocator: Securitisation pool allocator
            hierarchy_resolver: Hierarchy resolver
            classifier: Exposure classifier
            crm_processor: CRM processor
            re_splitter: Real estate loan-splitter (CRR Art. 125/126,
                B3.1 Art. 124F/H)
            sa_calculator: SA calculator
            irb_calculator: IRB calculator
            slotting_calculator: Slotting calculator
            equity_calculator: Equity calculator
            output_aggregator: Output aggregator
        """
        self._loader = loader
        self._securitisation_allocator = securitisation_allocator
        self._hierarchy_resolver = hierarchy_resolver
        self._classifier = classifier
        self._crm_processor = crm_processor
        self._re_splitter = re_splitter
        self._sa_calculator = sa_calculator
        self._irb_calculator = irb_calculator
        self._slotting_calculator = slotting_calculator
        self._equity_calculator = equity_calculator
        self._output_aggregator = output_aggregator

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

        try:
            with stage_timer(logger, "loader"):
                raw_data = self._loader.load()
        except Exception as e:  # noqa: BLE001 — loader failure becomes the error result
            return create_error_result(
                [PipelineError(stage="loader", error_type="load_error", message=str(e))]
            )

        return self.run_with_data(raw_data, config)

    def run_with_data(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
        *,
        rulepack: RulepackV0 | None = None,
    ) -> AggregatedResultBundle:
        """
        Execute pipeline with pre-loaded data.

        Folds a PipelineContext through the literal stage registry; all
        approach-specific calculators run sequentially on one unified
        LazyFrame, avoiding plan tree duplication and mid-pipeline
        materialisation.

        Args:
            data: Pre-loaded raw data bundle
            config: Calculation configuration
            rulepack: Pre-resolved rulepack used verbatim instead of
                ``RulepackV0.from_config(config)`` — for amendment overlays and
                tests that substitute a custom resolved pack (e.g. an overridden
                floor entry). The EUR/GBP FX-sync still runs on ``config``; an
                injected pack is not re-derived from the synced config.

        Returns:
            AggregatedResultBundle with all results and audit trail
        """
        run_id, run_id_token = new_run_id()
        edge_capture_token = begin_edge_capture()
        run_start = time.perf_counter()
        started_at = datetime.now(UTC)
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
            # Runs BEFORE components/rulepack are built — the fold sees one
            # immutable effective config per run.
            if config.is_crr and config.sync_eur_gbp_rate_from_fx_table:
                derived_rate = extract_eur_gbp_rate(data.fx_rates)
                if derived_rate is not None and derived_rate != config.eur_gbp_rate:
                    logger.warning(
                        "eur_gbp_rate auto-sync: replacing %s with %s from fx_rates table",
                        config.eur_gbp_rate,
                        derived_rate,
                    )
                    config = config.with_fx_rate(derived_rate)

            components = build_components(
                config,
                securitisation_allocator=self._securitisation_allocator,
                hierarchy_resolver=self._hierarchy_resolver,
                classifier=self._classifier,
                crm_processor=self._crm_processor,
                re_splitter=self._re_splitter,
                sa_calculator=self._sa_calculator,
                irb_calculator=self._irb_calculator,
                slotting_calculator=self._slotting_calculator,
                equity_calculator=self._equity_calculator,
                output_aggregator=self._output_aggregator,
            )
            rulepack = rulepack if rulepack is not None else RulepackV0.from_config(config)

            # IRB mode without model_permissions → all exposures fall back to
            # SA. The classifier forces all permission expressions to False
            # when has_model_permissions=False in IRB mode. Surface a
            # pipeline-level error so the user can see per-model gating is off.
            initial_errors: tuple[PipelineError, ...] = ()
            if config.permission_mode == PermissionMode.IRB and data.model_permissions is None:
                logger.warning(
                    "IRB permission mode selected but no model_permissions data provided. "
                    "All exposures will route to SA; supply a model_permissions table "
                    "to enable IRB."
                )
                initial_errors = (
                    PipelineError(
                        stage="pipeline",
                        error_type="missing_model_permissions",
                        message=(
                            "IRB permission mode selected but no model_permissions "
                            "data was provided. All exposures will route to SA. "
                            "Supply a model_permissions table to enable per-model "
                            "IRB approach routing."
                        ),
                    ),
                )

            ctx = (
                PipelineContext.empty()
                .put(RAW_DATA, data)
                .put(COMPONENTS, components)
                .put(SECURITISATION_RESOLVED, None)
                .put(PIPELINE_ERRORS, initial_errors)
                .put(STAGE_ERRORS, ())
            )

            ctx = run_stages(ctx, rulepack, config, PIPELINE_STAGES)

            pipeline_errors = list(ctx.get_or(PIPELINE_ERRORS, ()))
            halted = ctx.get_or(HALTED, "")
            if halted == "immediate":
                # Pre-calculator stage crash: bare error result, no merge
                # (verbatim pre-fold behaviour).
                return create_error_result(pipeline_errors)
            if halted == "merged":
                # Calculator/aggregator crash: the error result still flows
                # through the branch + channel merges below (verbatim
                # pre-fold behaviour, including its double-conversion of
                # pipeline errors).
                result = create_error_result(pipeline_errors)
                branch_errors = ctx.get_or(BRANCH_ERRORS, ())
                if branch_errors:
                    result = replace(result, errors=list(result.errors) + list(branch_errors))
            else:
                result = ctx.get(RESULT)

            # Unified error channel (P2.21): ``result.errors`` already
            # carries the branch-calculator warnings (merged by the
            # aggregate stage, original codes). Append, in order:
            # loader/securitisation bundle errors (DQ*, SEC*), stage
            # data-quality errors from STAGE_ERRORS (HIE*, CLS*, CCR*,
            # CRM*, RE*, equity — CalculationErrors verbatim, original
            # code/severity/category/context preserved), then converted
            # stage-CRASH PipelineErrors (PIPELINE_<STAGE> — a crash has
            # no original code).
            final_data = ctx.get(RAW_DATA)
            loader_errors = list(final_data.errors) if final_data.errors else []
            converted_errors = [convert_pipeline_error(e) for e in pipeline_errors]
            extra_errors = loader_errors + list(ctx.get(STAGE_ERRORS)) + converted_errors
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

            # Opt-in audit cache: persist aggregated summary frames and write
            # a manifest.json. No-op unless config.audit_cache_dir is set.
            _persist_audit_artifacts(
                result,
                config,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=total_ms,
            )

            return result
        finally:
            # Close the run's edge capture: deletes spill files and logs the
            # materialisation map (every stage-edge collect in one place).
            edge_events = end_edge_capture(edge_capture_token)
            if edge_events:
                logger.info(
                    "materialisation map: %s",
                    "; ".join(
                        f"{e.label}={e.rows}r/{e.estimated_bytes >> 20}MiB/{e.wall_ms}ms"
                        + ("/spill" if e.spilled else "")
                        for e in edge_events
                    ),
                    extra={"stage": "pipeline", "edge_count": len(edge_events)},
                )
            clear_run_id(run_id_token)


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


# =============================================================================
# Audit cache helpers
# =============================================================================


def _persist_audit_artifacts(
    result: AggregatedResultBundle,
    config: CalculationConfig,
    *,
    run_id: str,
    started_at: datetime,
    elapsed_ms: float,
) -> None:
    """Sink aggregated summary frames and write the per-run manifest.

    No-op when ``config.audit_cache_dir`` is None — the audit cache is opt-in.
    Mirrors the per-stage ``sink_audit`` calls in ``CRMProcessor`` so the
    final on-disk layout under ``<audit_cache_dir>/<run_id>/`` contains both
    CRM intermediates and the aggregator's pre/post-CRM summary views.

    Failures are logged at WARNING and swallowed — audit caching must never
    break a real run.
    """
    import json as _json

    from rwa_calc.observability.audit_cache import prune_audit_cache as _prune_audit_cache
    from rwa_calc.observability.audit_cache import sink_audit as _sink_audit

    if config.audit_cache_dir is None:
        return

    summary_frames: dict[str, pl.LazyFrame | None] = {
        "pre_crm_summary": result.pre_crm_summary,
        "post_crm_summary": result.post_crm_summary,
        "post_crm_detailed": result.post_crm_detailed,
        "summary_by_class": result.summary_by_class,
        "summary_by_approach": result.summary_by_approach,
        "results": result.results,
        # Pre-floor per-approach views — diff against ``results`` to attribute
        # output-floor uplift back to a specific approach branch.
        "sa_results": result.sa_results,
        "irb_results": result.irb_results,
        "slotting_results": result.slotting_results,
        "equity_results": result.equity_results,
        # Per-exposure output-floor impact (Basel 3.1 only; None under CRR).
        "floor_impact": result.floor_impact,
        # Per-exposure SME / infrastructure factor impact (CRR only).
        "supporting_factor_impact": result.supporting_factor_impact,
        # Securitisation per-pool summary + per-exposure reconciliation
        # (both None unless ``securitisation_allocations`` was supplied).
        "securitisation_summary": result.securitisation_summary,
        "securitisation_audit": result.securitisation_audit,
    }
    for name, frame in summary_frames.items():
        if frame is not None:
            _sink_audit(frame, config, name)

    run_dir = Path(config.audit_cache_dir) / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[dict[str, object]] = []
        if run_dir.exists():
            for parquet_path in sorted(run_dir.glob("*.parquet")):
                try:
                    artifacts.append(
                        {
                            "name": parquet_path.name,
                            "bytes": parquet_path.stat().st_size,
                        }
                    )
                except OSError:
                    continue

        finished_at = datetime.now(UTC)
        manifest = {
            "run_id": run_id,
            "framework": config.framework.value,
            "reporting_date": config.reporting_date.isoformat(),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_ms": elapsed_ms,
            "config": {
                "permission_mode": config.permission_mode.value,
                "base_currency": config.base_currency,
                "collect_engine": config.collect_engine,
                "crm_collateral_method": config.crm_collateral_method.value,
            },
            "artifacts": artifacts,
            "error_count": len(result.errors),
            # Every stage-edge collect of this run: label, rows, columns,
            # estimated bytes, wall ms, spill mode (migration Phase 1).
            "materialisation_map": [e.as_dict() for e in current_edge_events()],
        }
        manifest_path = run_dir / "manifest.json"
        tmp_path = run_dir / "manifest.json.tmp"
        tmp_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")
        tmp_path.replace(manifest_path)
        logger.info("wrote audit manifest %s", manifest_path)
    except Exception as exc:  # noqa: BLE001 — audit caching must never break a run
        logger.warning("audit manifest write failed: %s", exc)

    # Trim oldest runs AFTER this one's artifacts are committed so the cap
    # applies including the just-written run (max_runs total, not max_runs+1).
    _prune_audit_cache(config)
