"""
Calculator stage adapter — split-once with shared branch collect.

Pipeline position:
    re_splitter -> calculators -> equity_calculator -> aggregator

Key responsibilities:
- Compute CRR Art. 501 E* (SME tier threshold input) across the full
  unified frame so SA / IRB / slotting siblings in the same lending group
  all contribute (no-op when supporting factors are disabled — Basel 3.1).
- Basel 3.1 output floor: run ``calculate_unified`` for the SA-equivalent
  RW on all rows pre-split; the SA branch then only aliases
  ``approach -> approach_applied`` / ``rwa_post_factor -> rwa_final``.
- Split once by approach and run each branch calculator on its subset
  (all still lazy).
- Collect all branches via ``materialise_sealed_branches`` (conform each
  to its edge contract before the shared collect_all, brand after).
- Accumulate calculator data-quality warnings (SA004/SA005/SF001, EL
  diagnostics) on the BRANCH_ERRORS channel with their ORIGINAL codes.

References:
- CRR Art. 501 (SME supporting factor E*); CRR Art. 92(3a)/PS1/26 (output
  floor S-TREA)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import CALC_BRANCH_EDGES
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.materialise import materialise_sealed_branches
from rwa_calc.engine.orchestrator import (
    BRANCH_ERRORS,
    COMPONENTS,
    CRM_ADJUSTED,
    IRB_RESULTS,
    SA_RESULTS,
    SLOTTING_RESULTS,
)
from rwa_calc.engine.supporting_factors import compute_e_star_group_drawn

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run the split-once branch calculation with a shared collect."""
    crm_adjusted = ctx.get(CRM_ADJUSTED)
    components = ctx.get(COMPONENTS)

    # Eager-backed via the re_split_exit stage edge; the only lazy work
    # below this point is e_star + (floor-enabled) unified SA + the
    # per-branch calculator chains, collected at materialise_branches.
    exposures = crm_adjusted.exposures

    # Branch-path error channel: calculator data-quality warnings merge
    # into the result bundle with their ORIGINAL codes — the PipelineError
    # channel would rewrite them to PIPELINE_*.
    branch_errors: list[CalculationError] = []

    # Compute Art. 501 E* across the full unified frame so SA / IRB /
    # slotting siblings in the same lending group all contribute. Without
    # this, each branch's apply_factors would compute the window sum on
    # its own subset and under-count E* whenever a group spans multiple
    # approaches. No-op when supporting factors are disabled (Basel 3.1).
    exposures = compute_e_star_group_drawn(
        exposures, run_config, errors=branch_errors, pack=rulepack.pack
    )

    # For Basel 3.1 output floor: SA-equivalent RW needed on all rows
    if rulepack.pack.feature("output_floor"):
        exposures = components.sa_calculator.calculate_unified(
            exposures, run_config, errors=branch_errors, pack=rulepack.pack
        )

    # Split once by approach
    is_irb = (pl.col("approach") == ApproachType.FIRB.value) | (
        pl.col("approach") == ApproachType.AIRB.value
    )
    is_slotting = pl.col("approach") == ApproachType.SLOTTING.value

    sa_branch = exposures.filter(~is_irb & ~is_slotting)
    irb_branch = exposures.filter(is_irb)
    slotting_branch = exposures.filter(is_slotting)

    # Process each branch (all still lazy)
    if rulepack.pack.feature("output_floor"):
        # SA already calculated by calculate_unified above — add
        # aggregator columns that calculate_branch normally provides
        sa_result = sa_branch.with_columns(
            pl.col("approach").alias("approach_applied"),
            pl.col("rwa_post_factor").alias("rwa_final"),
        )
    else:
        sa_result = components.sa_calculator.calculate_branch(
            sa_branch, run_config, errors=branch_errors, pack=rulepack.pack
        )

    irb_result = components.irb_calculator.calculate_branch(
        irb_branch, run_config, errors=branch_errors, pack=rulepack.pack
    )
    slotting_result = components.slotting_calculator.calculate_branch(
        slotting_branch, run_config, errors=branch_errors, pack=rulepack.pack
    )

    # Collect all branches. In cpu mode, uses collect_all with CSE so
    # shared upstream computes once. In spill mode, sinks each branch to
    # disk sequentially (peak memory = 1 branch at a time). Each branch is
    # conformed to its edge contract before the shared collect and branded
    # after (Phase 3 branch-exit seal).
    sa_df, irb_df, slotting_df = materialise_sealed_branches(
        [sa_result, irb_result, slotting_result],
        run_config,
        [
            CALC_BRANCH_EDGES["sa_branch"],
            CALC_BRANCH_EDGES["irb_branch"],
            CALC_BRANCH_EDGES["slotting_branch"],
        ],
    )
    sa_rows = sa_df.height
    irb_rows = irb_df.height
    slotting_rows = slotting_df.height
    logger.info(
        "calculators materialised %d rows (sa=%d, irb=%d, slotting=%d)",
        sa_rows + irb_rows + slotting_rows,
        sa_rows,
        irb_rows,
        slotting_rows,
        extra={
            "stage": "calculators",
            "row_count": sa_rows + irb_rows + slotting_rows,
        },
    )

    return (
        ctx.put(SA_RESULTS, sa_df)
        .put(IRB_RESULTS, irb_df)
        .put(SLOTTING_RESULTS, slotting_df)
        .put(BRANCH_ERRORS, tuple(branch_errors))
    )
