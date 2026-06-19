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
- BA-CVA roll-up (P8.60): when BA-CVA counterparty inputs are present AND the
  ``cva_ba_cva`` pack Feature is enabled (Basel 3.1 only), compute the
  portfolio RWEA_CVA off the SA-CCR synthetic rows already on the aggregated
  results frame and surface it on ``AggregatedResultBundle.cva_rwa``. No-op
  (``cva_rwa`` stays None) otherwise — same post-aggregation enrichment shape
  as the ``rwa_ccr_default_fund`` roll-up.

References:
- CRR Art. 92(3a) / PRA PS1/26: output floor application at aggregation
- PRA PS1/26 Credit Valuation Adjustment Risk Part Ch.4 (BA-CVA reduced)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.orchestrator import (
    BRANCH_ERRORS,
    COMPONENTS,
    CRM_ADJUSTED,
    EQUITY_RESULT,
    IRB_RESULTS,
    RAW_DATA,
    RESULT,
    SA_RESULTS,
    SLOTTING_RESULTS,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)

# SA-CCR synthetic rows the BA-CVA charge reads EAD_NS from carry this
# exposure_reference prefix (one per netting set; see engine/ccr).
_CCR_EXPOSURE_PREFIX: str = "ccr__"


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

    cva_rwa = _ba_cva_roll_up(ctx, rulepack, result.results)
    if cva_rwa is not None:
        result = replace(result, cva_rwa=cva_rwa)

    return ctx.put(RESULT, result)


def _ba_cva_roll_up(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    results: pl.LazyFrame,
) -> float | None:
    """Compute the portfolio BA-CVA RWEA, or None when out of scope.

    No-op when the firm supplies no BA-CVA counterparty inputs (every existing
    portfolio) or the regime disables the ``cva_ba_cva`` pack Feature (CRR) —
    the regime gate is a cited pack Feature, never a ``config.is_basel_3_1``
    branch.

    References:
        PRA PS1/26 Credit Valuation Adjustment Risk Part Ch.4.
    """
    data = ctx.get(RAW_DATA)
    if data.cva_counterparties is None:
        return None
    if not rulepack.pack.feature("cva_ba_cva"):
        logger.debug("cva_ba_cva feature disabled for regime - skipping BA-CVA roll-up")
        return None

    from rwa_calc.engine.cva import compute_ba_cva_rwa

    ccr_rows = results.filter(
        pl.col("exposure_reference").str.starts_with(_CCR_EXPOSURE_PREFIX)
    )
    cva_rwa = compute_ba_cva_rwa(data.cva_counterparties, ccr_rows, rulepack.pack)
    if cva_rwa is not None:
        logger.info("BA-CVA RWEA computed: %.2f", cva_rwa)
    return cva_rwa
