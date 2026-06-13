"""
CRM processing stage adapter.

Pipeline position:
    classifier -> crm_processor -> re_splitter

Key responsibilities:
- Run ``CRMProcessor.get_crm_unified_bundle`` over the classified bundle
  (the processor owns its intra-stage checkpoints — ``crm_post_ead`` and
  ``crm_pre_guarantee_unified`` — and its exit seal, ``crm_exit`` /
  ``crm_exit_ccr``).
- Forward CRM errors (CRM*) to the STAGE_ERRORS channel verbatim —
  original code/severity/category preserved into
  ``AggregatedResultBundle.errors`` (error-channel slice, P2.21).

References:
- CRR Art. 192-241: Credit risk mitigation
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import (
    CLASSIFIED,
    COMPONENTS,
    CRM_ADJUSTED,
    append_stage_errors,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run CRM processing on the unified exposure frame."""
    classified = ctx.get(CLASSIFIED)
    components = ctx.get(COMPONENTS)

    result = components.crm_processor.get_crm_unified_bundle(
        classified, run_config, pack=rulepack.pack
    )

    # Unified error channel: CRM errors reach the result verbatim —
    # original code/severity/category preserved, never PIPELINE_*.
    ctx = append_stage_errors(ctx, *result.crm_errors)

    return ctx.put(CRM_ADJUSTED, result)
