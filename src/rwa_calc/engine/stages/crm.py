"""
CRM processing stage adapter.

Pipeline position:
    classifier -> crm_processor -> re_splitter

Key responsibilities:
- Run ``CRMProcessor.get_crm_unified_bundle`` over the classified bundle
  (the processor owns its intra-stage checkpoints — ``crm_post_ead`` and
  ``crm_pre_guarantee_unified`` — and its exit seal, ``crm_exit`` /
  ``crm_exit_ccr``).
- Keep CRM off the CCR stage's own-funds lines (CC-08): when the CCR input can
  mint settlement-risk or default-fund rows, run the processor twice — once on
  the credit exposures with every CRM input, once on the own-funds lines with
  none — and re-join the two sealed outputs (``engine/crm/own_funds_lines.py``).
  The own-funds half runs FIRST so the credit half's opt-in ``crm_audit``
  artefact is the one left on disk.
- Forward CRM errors (CRM*) to the STAGE_ERRORS channel verbatim —
  original code/severity/category preserved into
  ``AggregatedResultBundle.errors`` (error-channel slice, P2.21).

References:
- CRR Art. 192-241: Credit risk mitigation
- CRR Art. 92(3)(ca), 378-380; CCR (CRR) Part Art. 307-310 (own-funds lines)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.crm.own_funds_lines import (
    carries_own_funds_lines,
    merge_crm_bundles,
    partition_own_funds_lines,
)
from rwa_calc.engine.orchestrator import (
    CLASSIFIED,
    COMPONENTS,
    CRM_ADJUSTED,
    RAW_DATA,
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
    processor = ctx.get(COMPONENTS).crm_processor

    halves = (
        partition_own_funds_lines(classified)
        if carries_own_funds_lines(ctx.get_or(RAW_DATA, None))
        else None
    )
    if halves is None:
        result = processor.get_crm_unified_bundle(classified, run_config, pack=rulepack.pack)
    else:
        credit, own_funds = halves
        own_funds_result = processor.get_crm_unified_bundle(
            own_funds, run_config, pack=rulepack.pack
        )
        credit_result = processor.get_crm_unified_bundle(credit, run_config, pack=rulepack.pack)
        result = merge_crm_bundles(credit_result, own_funds_result)

    # Unified error channel: CRM errors reach the result verbatim —
    # original code/severity/category preserved, never PIPELINE_*.
    ctx = append_stage_errors(ctx, *result.crm_errors)

    return ctx.put(CRM_ADJUSTED, result)
