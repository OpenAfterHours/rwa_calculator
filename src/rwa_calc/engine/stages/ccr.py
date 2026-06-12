"""
SA-CCR stage adapter (P8.20).

Pipeline position:
    hierarchy_resolver -> ccr_sa_ccr -> classifier

Key responsibilities:
- Translate the optional ``data.ccr`` bundle into one synthetic exposure
  row per netting set with ``drawn_amount = EAD_CCR`` (CRR Art. 274(2):
  EAD = alpha * (RC + PFE)) and append those rows to the resolved
  exposures via ``diagonal_relaxed`` concat, so the unified pipeline
  consumes them without CCR-aware special-casing downstream.
- Apply the Art. 272(4) legal-enforceability gate and the Art. 291(4)-(5)
  WWR gate before the EAD chain runs; forward their CCR001/CCR010/CCR011
  diagnostics to the STAGE_ERRORS channel verbatim — original
  code/severity/category preserved (error-channel slice, P2.21).
- Inherit resolved counterparty rating columns onto each synthetic row so
  the SA institution lookup (CRR Art. 120(1) Table 3) and IRB routing see
  the same ratings as traditional lending rows.
- Re-seal the stage exit against the ``ccr_exit`` contract (hierarchy_exit
  shape plus the SA-CCR provenance columns).
- No-op when ``data.ccr is None`` (firm has no derivatives book).

References:
- CRR Art. 271 (CCR scope); CRR Art. 272(4) (netting set)
- CRR Art. 274(2) (alpha * (RC + PFE)); CRR Art. 291(4)-(5) (WWR)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import CCR_EXIT_EDGE
from rwa_calc.engine.materialise import materialise_sealed_edge
from rwa_calc.engine.orchestrator import (
    RAW_DATA,
    RESOLVED_HIERARCHY,
    append_stage_errors,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,  # noqa: ARG001 — uniform stage signature (Phase 4)
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run the SA-CCR pipeline adapter over the resolved hierarchy."""
    data = ctx.get(RAW_DATA)
    if data.ccr is None:
        logger.debug("no CCR inputs - skipping SA-CCR stage")
        return ctx

    from rwa_calc.engine.ccr import (
        apply_legal_enforceability_gate,
        apply_wwr_gate,
        ccr_rows_to_exposures,
    )

    resolved = ctx.get(RESOLVED_HIERARCHY)

    # Apply the Art. 272(4) legal-enforceability gate first so
    # non-enforceable netting sets are split into single-trade synthetic
    # NSes before the EAD chain runs, then the Art. 291(4)-(5) WWR gate so
    # specific-WWR trades break out into their own synthetic netting sets
    # (LGD = 100%).
    raw_ccr_gated = apply_wwr_gate(apply_legal_enforceability_gate(data.ccr))
    # Unified error channel: the gates' CCR001/CCR010/CCR011 diagnostics
    # reach the result verbatim — original code/severity/category preserved.
    ctx = append_stage_errors(ctx, *raw_ccr_gated.errors)
    ccr_exposure_rows = ccr_rows_to_exposures(
        raw_ccr_gated,
        run_config.ccr,
        run_config.reporting_date,
        base_currency=run_config.base_currency,
        fx_rates=data.fx_rates,
        # CRR Art. 274(2): the counterparty frame carries the
        # ``counterparty_type`` discriminator that selects the per-NS
        # supervisory alpha (1.0 carve-out vs 1.4 default).
        counterparties=data.counterparties,
        # PRA PS1/26 Art. 274(2A): the transitional alpha add-on is
        # Basel 3.1 only — gate it on the framework so it never fires
        # under CRR.
        is_basel_3_1=run_config.is_basel_3_1,
    )
    # Inherit the resolved counterparty rating columns onto each CCR
    # synthetic row so the downstream SA Institution lookup (CRR
    # Art. 120(1) Table 3, keyed off ``cqs``) and any IRB routing (keyed
    # off ``internal_pd``) see the same rating that
    # ``hierarchy._attach_counterparty_rating`` joined onto traditional
    # lending rows. Without this enrichment, CCR rows arrive at the SA
    # calculator with ``cqs=None`` and fall through to the 100%
    # unrated-institution fallback.
    ccr_exposure_rows = _enrich_ccr_rows_with_ratings(
        ccr_exposure_rows, resolved.counterparty_lookup
    )
    new_exposures = pl.concat(
        [resolved.exposures, ccr_exposure_rows],
        how="diagonal_relaxed",
    )
    # Stage-exit edge (only when CCR rows were appended): the
    # hierarchy_exit shape plus the SA-CCR provenance columns — synthetic
    # rows may not otherwise reshape the frame.
    new_resolved = replace(
        resolved,
        exposures=materialise_sealed_edge(new_exposures, run_config, CCR_EXIT_EDGE),
    )
    return ctx.put(RESOLVED_HIERARCHY, new_resolved)


def _enrich_ccr_rows_with_ratings(
    ccr_exposure_rows: pl.LazyFrame,
    counterparty_lookup: CounterpartyLookup,
) -> pl.LazyFrame:
    """Join the resolved counterparty rating columns onto CCR rows.

    Mirrors the per-exposure rating attach performed by
    ``hierarchy._attach_counterparty_rating`` for traditional lending
    rows. The CCR pipeline adapter runs AFTER hierarchy resolution and
    appends synthetic rows via ``diagonal_relaxed`` concat, so without
    this enrichment those rows reach the SA calculator with ``cqs=None``
    / ``external_cqs=None`` / ``internal_pd=None`` and the institution
    risk-weight lookup falls through to its unrated 100% fallback
    (CRR Art. 121(1)) instead of the rated CQS table
    (CRR Art. 120(1) Table 3).
    """
    cp_schema = set(counterparty_lookup.counterparties.collect_schema().names())
    rating_cols = [c for c in ("cqs", "pd", "internal_pd", "external_cqs") if c in cp_schema]
    if not rating_cols:
        return ccr_exposure_rows
    cp_select = [pl.col("counterparty_reference"), *(pl.col(c) for c in rating_cols)]
    return ccr_exposure_rows.join(
        counterparty_lookup.counterparties.select(cp_select),
        on="counterparty_reference",
        how="left",
    )
