"""
Equity calculation stage adapter (separate path).

Pipeline position:
    calculators -> equity_calculator -> aggregator

Key responsibilities:
- Run ``EquityCalculator.get_equity_result_bundle`` on the CRM-adjusted
  bundle's equity side frames (equity is not in the unified frame; its
  results rejoin the main flow only inside the aggregator).
- Forward ``EquityResultBundle.errors`` to the STAGE_ERRORS channel
  verbatim (error-channel slice, P2.21). Those errors are plain
  ``CalculationError`` objects — the bundle field is declared
  ``list[CalculationError]`` and the calculator's accumulator is typed the
  same (empty in practice today; the package-local ``EquityCalculationError``
  dataclass is never instantiated) — so no shape mapping is needed and
  code/severity/category pass through untouched.
- Swallow stage exceptions: equity is dropped (EQUITY_RESULT = None) and
  the run continues with a PIPELINE_EQUITY_CALCULATOR crash diagnostic
  (verbatim pre-fold policy — a crash has no original code).
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
    """Run the equity calculation stage."""
    crm_adjusted = ctx.get(CRM_ADJUSTED)
    components = ctx.get(COMPONENTS)
    try:
        result = components.equity_calculator.get_equity_result_bundle(
            crm_adjusted, run_config, pack=rulepack.pack
        )

        # Unified error channel: equity errors (CalculationErrors) reach
        # the result verbatim — original code/severity/category preserved.
        ctx = append_stage_errors(ctx, *result.errors)

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
