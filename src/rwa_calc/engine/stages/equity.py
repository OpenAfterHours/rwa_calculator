"""
Equity calculation stage adapter (separate path).

Pipeline position:
    calculators -> equity_calculator -> aggregator

Key responsibilities:
- Run ``EquityCalculator.get_equity_result_bundle`` on the CRM-adjusted
  bundle's equity side frames (equity is not in the unified frame; its
  results rejoin the main flow only inside the aggregator).
- Copy equity errors onto the PIPELINE_ERRORS channel (verbatim pre-fold
  behaviour; the error-channel slice unifies this).
- Swallow stage exceptions: equity is dropped (EQUITY_RESULT = None) and
  the run continues with a PIPELINE_EQUITY_CALCULATOR diagnostic
  (verbatim pre-fold policy).
- Opt-in audit cache: sink the CIU look-through vs fallback rationale.

References:
- CRR Art. 133 (SA equity); CRR Art. 155 (IRB equity approaches)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import (
    COMPONENTS,
    CRM_ADJUSTED,
    EQUITY_RESULT,
    PipelineError,
    append_pipeline_error,
)
from rwa_calc.observability.audit_cache import sink_audit

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
    """Run the equity calculation stage."""
    crm_adjusted = ctx.get(CRM_ADJUSTED)
    components = ctx.get(COMPONENTS)
    try:
        result = components.equity_calculator.get_equity_result_bundle(crm_adjusted, run_config)

        for error in result.errors:
            ctx = append_pipeline_error(
                ctx,
                PipelineError(
                    stage="equity_calculator",
                    error_type=getattr(error, "error_type", "unknown"),
                    message=getattr(error, "message", str(error)),
                ),
            )

        # Opt-in audit cache: CIU look-through vs fallback rationale per row.
        if result.calculation_audit is not None:
            sink_audit(result.calculation_audit, run_config, "equity_calculation_audit")

        return ctx.put(EQUITY_RESULT, result)
    except Exception as exc:  # noqa: BLE001 — verbatim pre-fold policy: drop equity, continue
        ctx = append_pipeline_error(
            ctx,
            PipelineError(
                stage="equity_calculator",
                error_type="equity_calculation_error",
                message=str(exc),
            ),
        )
        return ctx.put(EQUITY_RESULT, None)
