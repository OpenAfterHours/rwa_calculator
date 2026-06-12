"""
CRM processing stage adapter.

Pipeline position:
    classifier -> crm_processor -> re_splitter

Key responsibilities:
- Run ``CRMProcessor.get_crm_unified_bundle`` over the classified bundle
  (the processor owns its intra-stage checkpoints — ``crm_post_ead`` and
  ``crm_pre_guarantee_unified`` — and its exit seal, ``crm_exit`` /
  ``crm_exit_ccr``).
- Copy CRM errors onto the PIPELINE_ERRORS channel using the error's own
  code as the error_type (verbatim pre-fold behaviour; the error-channel
  slice unifies this).

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
    """Run CRM processing on the unified exposure frame."""
    classified = ctx.get(CLASSIFIED)
    components = ctx.get(COMPONENTS)

    result = components.crm_processor.get_crm_unified_bundle(classified, run_config)

    for error in result.crm_errors:
        ctx = append_pipeline_error(
            ctx,
            PipelineError(
                stage="crm_processor",
                error_type=error.code,
                message=error.message,
            ),
        )

    return ctx.put(CRM_ADJUSTED, result)
