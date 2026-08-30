"""
Classification stage adapter.

Pipeline position:
    ccr_sa_ccr -> classifier -> crm_processor

Key responsibilities:
- Run ``ExposureClassifier.classify`` over the resolved hierarchy bundle
  (the classifier seals its own exit — ``classifier_exit`` or
  ``classifier_exit_ccr``, brand-selected by its input).
- Forward classification errors (CLS*, DQ008) to the STAGE_ERRORS channel
  verbatim — original code/severity/category preserved into
  ``AggregatedResultBundle.errors`` (error-channel slice, P2.21).
- Opt-in audit cache: sink the per-exposure classification reason trail.

References:
- CRR Art. 112: SA exposure classes; CRR Art. 147: IRB exposure classes
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import (
    CLASSIFIED,
    COMPONENTS,
    RESOLVED_HIERARCHY,
    append_stage_errors,
)
from rwa_calc.observability.audit_cache import sink_audit

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
    """Run the classification stage."""
    resolved = ctx.get(RESOLVED_HIERARCHY)
    components = ctx.get(COMPONENTS)

    result = components.classifier.classify(resolved, run_config, pack=rulepack.pack)

    # Unified error channel: classification errors reach the result
    # verbatim — original code/severity/category preserved, never PIPELINE_*.
    ctx = append_stage_errors(ctx, *result.classification_errors)

    # Opt-in audit cache: per-exposure classification reason trail.
    if result.classification_audit is not None:
        sink_audit(result.classification_audit, run_config, "classification_audit")

    return ctx.put(CLASSIFIED, result)
