"""
Hierarchy resolution stage adapter.

Pipeline position:
    securitisation_allocator -> hierarchy_resolver -> ccr_sa_ccr

Key responsibilities:
- Run ``HierarchyResolver.resolve`` over the raw data bundle.
- Join the resolved securitisation lookup onto the unified exposures frame
  so residual_pct + pool_allocations ride through CRM and the calculators
  (canonical defaults are injected when no allocations were supplied).
- Materialise + seal the stage exit against the ``hierarchy_exit`` contract
  (the resolver's ``hierarchy_resolved`` pure-plan seal plus the
  securitisation lookup columns attached here).
- On a solo / sub-consolidated run (``GROUP_POPULATION`` present), resolve the
  whole reporting group's population too and publish what the rest of the
  group adds to each obligor's retail-threshold aggregate and Art. 501 E*
  (``GROUP_OBLIGOR_INCREMENTS``); the threshold half rides on the exposures as
  ``out_of_scope_group_adjusted_exposure``. The group pass's own diagnostics
  are not forwarded — they describe rows outside the run.
- Forward hierarchy errors (HIE*, DQ004/DQ005) to the STAGE_ERRORS channel
  verbatim — original code/severity/category/context preserved into
  ``AggregatedResultBundle.errors`` (error-channel slice, P2.21).
- Opt-in audit cache: sink the dual-track rating-inheritance frame.

References:
- CRR Art. 4(1)(39): Group of connected clients (hierarchy resolution)
- CRR Art. 123(c) / 501(1); PS1/26 Art. 123A(1)(b)(ii): group-wide "amount owed"
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from rwa_calc.contracts.edges import HIERARCHY_EXIT_EDGE
from rwa_calc.engine.hierarchy.group_obligor import (
    attach_out_of_scope_threshold,
    whole_group_increments,
)
from rwa_calc.engine.materialise import materialise_sealed_edge
from rwa_calc.engine.orchestrator import (
    COMPONENTS,
    GROUP_OBLIGOR_INCREMENTS,
    GROUP_POPULATION,
    RAW_DATA,
    RESOLVED_HIERARCHY,
    SECURITISATION_RESOLVED,
    append_stage_errors,
)
from rwa_calc.engine.securitisation.allocator import attach_securitisation_lookup
from rwa_calc.observability.audit_cache import sink_audit

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,  # noqa: ARG001 — uniform stage signature (Phase 4)
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run hierarchy resolution and attach the securitisation lookup."""
    data = ctx.get(RAW_DATA)
    components = ctx.get(COMPONENTS)
    securitisation_resolved = ctx.get(SECURITISATION_RESOLVED)

    result = components.hierarchy_resolver.resolve(data, run_config)

    # Join the resolved securitisation lookup onto the unified exposures
    # frame. When no allocations were supplied, the helper still adds the
    # columns at their canonical defaults (1.0, []), keeping the downstream
    # contract uniform.
    new_exposures = attach_securitisation_lookup(result.exposures, securitisation_resolved)

    # Solo / sub-consolidated run: the retail threshold and E* count what the
    # obligor owes the WHOLE banking group (CRR Art. 123(c) / 501(1); PS1/26
    # Art. 123A(1)(b)(ii)). Resolve the whole group's population with the same
    # resolver and publish the per-obligor increments. Absent on an unscoped
    # run, None on a whole-group run: the exposures are then untouched.
    group_population = ctx.get_or(GROUP_POPULATION, None)
    increments: pl.LazyFrame | None = None
    if group_population is not None:
        whole_group = components.hierarchy_resolver.resolve(group_population, run_config)
        increments = whole_group_increments(result.exposures, whole_group.exposures)
        new_exposures = attach_out_of_scope_threshold(new_exposures, increments)
    result = replace(
        result,
        # Stage-exit edge: hierarchy output crosses to the CCR stage /
        # Classifier as an eager-backed frame, sealed against the full
        # hierarchy_exit contract.
        exposures=materialise_sealed_edge(new_exposures, run_config, HIERARCHY_EXIT_EDGE),
        securitisation_audit=securitisation_resolved,
    )

    # Unified error channel: hierarchy errors reach the result verbatim —
    # original code/severity/category preserved, never PIPELINE_*.
    ctx = append_stage_errors(ctx, *result.hierarchy_errors)

    # Opt-in audit cache: dual-track best-rating resolution per CP.
    sink_audit(
        result.counterparty_lookup.rating_inheritance,
        run_config,
        "rating_inheritance",
    )

    ctx = ctx.put(RESOLVED_HIERARCHY, result)
    if increments is None:
        return ctx
    return ctx.put(GROUP_OBLIGOR_INCREMENTS, increments)
