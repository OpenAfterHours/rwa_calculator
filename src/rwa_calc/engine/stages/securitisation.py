"""
Securitisation allocator stage adapter.

Pipeline position:
    (loader) -> securitisation_allocator -> hierarchy_resolver

Key responsibilities:
- Resolve ``data.securitisation_allocations`` into a per-exposure lookup
  carrying residual_pct + pool_allocations (SECURITISATION_RESOLVED
  artifact, consumed by the hierarchy stage wiring).
- Append SEC001-SEC005 validation errors to the bundle's error list
  verbatim — the loader-validation channel — so the original codes survive
  into the final ``AggregatedResultBundle`` (the PIPELINE_* channel would
  rewrite them).
- Swallow stage exceptions: the run continues with the original data and a
  PIPELINE_SECURITISATION_ALLOCATOR diagnostic (verbatim pre-fold policy).

References:
- CRR Art. 247-270: Securitisation framework (pool allocation inputs)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import (
    COMPONENTS,
    RAW_DATA,
    SECURITISATION_RESOLVED,
    PipelineError,
    append_pipeline_error,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,  # noqa: ARG001 — uniform stage signature (Phase 4)
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run the securitisation pool allocator stage."""
    data = ctx.get(RAW_DATA)
    components = ctx.get(COMPONENTS)
    try:
        new_data, resolved, errors = components.securitisation_allocator.allocate(data, run_config)
        if errors:
            # Attach to the bundle's errors list so the SEC### codes survive
            # verbatim into AggregatedResultBundle.errors.
            combined = list(new_data.errors) + errors
            new_data = replace(new_data, errors=combined)
        return ctx.put(RAW_DATA, new_data).put(SECURITISATION_RESOLVED, resolved)
    except Exception as exc:  # noqa: BLE001 — verbatim pre-fold policy: swallow and continue
        ctx = append_pipeline_error(
            ctx,
            PipelineError(
                stage="securitisation_allocator",
                error_type="allocation_error",
                message=str(exc),
            ),
        )
        return ctx.put(SECURITISATION_RESOLVED, None)
