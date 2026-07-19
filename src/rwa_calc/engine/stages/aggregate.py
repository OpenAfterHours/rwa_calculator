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
- BA-CVA roll-up (P8.60/P8.62/P8.63): when BA-CVA counterparty inputs are
  present AND the ``cva_ba_cva`` pack Feature is enabled (Basel 3.1 only),
  compute the portfolio RWEA_CVA off the SA-CCR synthetic rows already on the
  aggregated results frame and surface it on ``AggregatedResultBundle.cva_rwa``
  alongside the descriptive ``cva_method`` (``"BA-CVA"`` for both the reduced
  and full sub-cases) and ``cva_hedges_recognised`` (``True`` when at least one
  eligible hedge fed the full-K path, ``False`` for the reduced path). The CVA
  RWEA is additive to the default-risk total (``Σ rwa_final`` over the results
  frame) — it is a standalone scalar, not folded into ``rwa_final``. No-op (all
  three fields stay None) otherwise — same post-aggregation enrichment shape as
  the ``rwa_ccr_default_fund`` roll-up.

References:
- CRR Art. 92(3a) / PRA PS1/26: output floor application at aggregation
- PRA PS1/26 Credit Valuation Adjustment Risk Part Ch.4.2-4.10 (BA-CVA reduced
  and full; CRR2 Art. 384 Basic Approach)
- PRA PS1/26 Own Funds Part 4(b): own-funds -> RWEA multiplier (x12.5)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, reseal_with
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
    from rwa_calc.engine.cva import BaCvaResult
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

    cva = _ba_cva_roll_up(ctx, rulepack, result.results)
    if cva is not None and cva.rwea is not None:
        # ``cva_rwa`` is additive to the default-risk total (Σ rwa_final); it is
        # not folded into ``rwa_final`` (PS1/26 Own Funds 4(b)). It is also
        # broadcast as a constant ``cva_rwa`` column on the (re-sealed) results
        # frame so the downstream COREP C 34.04 grid (P8.50) and the Pillar III
        # CCR2 disclosure (P8.51) can read the portfolio CVA RWEA from the
        # LazyFrame alone — the scalar is otherwise bundle-only. ``cva_rwa`` is a
        # declared optional column on ``AGGREGATOR_EXIT_EDGE``, so the re-seal
        # conforms and re-brands the frame without violating the producer-seal
        # contract. ``reseal_with`` is the single sanctioned mutate-and-rebrand
        # path — this is the second of the exit edge's two legitimate seal
        # points (the aggregator being the first).
        cva_results = reseal_with(
            result.results,
            {"cva_rwa": pl.lit(cva.rwea, dtype=pl.Float64)},
            AGGREGATOR_EXIT_EDGE,
        )
        result = replace(
            result,
            results=cva_results,
            cva_rwa=cva.rwea,
            cva_method="BA-CVA",
            cva_hedges_recognised=cva.hedges_recognised,
        )

    return ctx.put(RESULT, result)


def _ba_cva_roll_up(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    results: pl.LazyFrame,
) -> BaCvaResult | None:
    """Compute the portfolio BA-CVA result, or None when out of scope.

    No-op when the firm supplies no BA-CVA counterparty inputs (every existing
    portfolio) or the regime disables the ``cva_ba_cva`` pack Feature (CRR) —
    the regime gate is a cited pack Feature, never a ``config.is_basel_3_1``
    branch. The returned :class:`BaCvaResult` carries both the RWEA and the
    single ``hedges_recognised`` discriminator (``True`` when at least one
    eligible hedge fed the full-K path) so the roll-up never re-derives the
    full-vs-reduced condition.

    References:
        PRA PS1/26 Credit Valuation Adjustment Risk Part Ch.4.2-4.10;
        Own Funds Part 4(b).
    """
    data = ctx.get(RAW_DATA)
    if data.cva_counterparties is None:
        return None
    if not rulepack.pack.feature("cva_ba_cva"):
        logger.debug("cva_ba_cva feature disabled for regime - skipping BA-CVA roll-up")
        return None

    from rwa_calc.engine.cva import compute_ba_cva_rwa

    ccr_rows = results.filter(pl.col("exposure_reference").str.starts_with(_CCR_EXPOSURE_PREFIX))
    cva = compute_ba_cva_rwa(data.cva_counterparties, ccr_rows, rulepack.pack, data.cva_hedges)
    if cva.rwea is not None:
        logger.info(
            "BA-CVA RWEA computed: %.2f (hedges_recognised=%s)",
            cva.rwea,
            cva.hedges_recognised,
        )
    return cva
