"""
Aggregation stage adapter.

Pipeline position:
    equity_calculator -> aggregator -> AggregatedResultBundle (terminal)

Key responsibilities:
- Run ``OutputAggregator.aggregate`` over the three collected branch
  DataFrames (re-wrapped ``.lazy()``), the equity bundle, and the
  securitisation audit pass-through. The aggregator owns the output-floor
  merge, the equity merge, and the ``aggregator_exit`` seal.
- Merge BRANCH_ERRORS into the result bundle with their original codes
  (verbatim pre-fold merge point — before the facade's loader/CCR/
  pipeline-error merge).

References:
- CRR Art. 92(3a) / PRA PS1/26: output floor application at aggregation
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import (
    BRANCH_ERRORS,
    COMPONENTS,
    CRM_ADJUSTED,
    EQUITY_RESULT,
    IRB_RESULTS,
    RESULT,
    SA_RESULTS,
    SLOTTING_RESULTS,
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
    """Aggregate the collected branch results into the final bundle."""
    components = ctx.get(COMPONENTS)
    crm_adjusted = ctx.get(CRM_ADJUSTED)

    result = components.output_aggregator.aggregate(
        sa_results=ctx.get(SA_RESULTS).lazy(),
        irb_results=ctx.get(IRB_RESULTS).lazy(),
        slotting_results=ctx.get(SLOTTING_RESULTS).lazy(),
        equity_bundle=ctx.get(EQUITY_RESULT),
        config=run_config,
        securitisation_audit=crm_adjusted.securitisation_audit,
        pack=rulepack.pack,
    )

    # Merge branch-path calculator warnings, codes preserved.
    branch_errors = ctx.get_or(BRANCH_ERRORS, ())
    if branch_errors:
        result = replace(result, errors=list(result.errors) + list(branch_errors))

    return ctx.put(RESULT, result)
