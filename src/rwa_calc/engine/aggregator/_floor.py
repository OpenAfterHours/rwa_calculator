"""
Output floor application and impact analysis (Basel 3.1).

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator (floor) -> AggregatedResultBundle

Key responsibilities:
- Portfolio-level output floor: TREA = max(U-TREA, x * S-TREA)
- Pro-rata shortfall distribution across floor-eligible exposures
- Per-exposure floor impact analysis for COREP reporting
- OutputFloorSummary with U-TREA, S-TREA, and shortfall

The output floor compares total modelled RWA (U-TREA) against total
SA-equivalent RWA scaled by the floor percentage (S-TREA * x). When the
floor binds at portfolio level, the shortfall is distributed pro-rata
to each floor-eligible exposure proportional to its SA-equivalent RWA.

References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
- PRA PS1/26 Art. 122(8): IRB institutions choose 100% flat or 65%/135%
  IG assessment for unrated corporates in S-TREA (via use_investment_grade_assessment)
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.engine.aggregator._schemas import FLOOR_ELIGIBLE_APPROACHES, FLOOR_IMPACT_SCHEMA
from rwa_calc.engine.aggregator._utils import col_or_default, empty_frame, resolve_rwa_col


def apply_floor_with_impact(
    combined: pl.LazyFrame,
    sa_results: pl.LazyFrame,
    floor_pct: float,
) -> tuple[pl.LazyFrame, pl.LazyFrame, OutputFloorSummary]:
    """
    Apply portfolio-level output floor and generate impact analysis.

    The floor is applied at portfolio level per PRA PS1/26 Art. 92 para 2A:
    ``TREA = max(U-TREA, x * S-TREA)``. When the floor binds, the shortfall
    (``x * S-TREA - U-TREA``) is distributed pro-rata across floor-eligible
    exposures (IRB + slotting) proportional to each exposure's ``sa_rwa``.

    This replaces the prior per-exposure ``max(irb_rwa, floor_pct * sa_rwa)``
    approach which systematically overstated capital for portfolios near but
    above the aggregate floor threshold.

    Args:
        combined: Combined results with ``rwa_final`` column.
        sa_results: SA results to derive floor RWA from.
        floor_pct: Floor percentage (e.g. 0.725 for 72.5%).

    Returns:
        Tuple of (floored results, floor impact analysis, portfolio summary).
    """
    # Ensure combined has rwa_final column
    combined_cols = set(combined.collect_schema().names())
    if "rwa_final" not in combined_cols:
        rwa_col = resolve_rwa_col(combined_cols)
        if rwa_col:
            combined = combined.with_columns(pl.col(rwa_col).alias("rwa_final"))
        else:
            combined = combined.with_columns(pl.lit(0.0).alias("rwa_final"))

    # Store pre-floor RWA for impact calculation
    combined = combined.with_columns(pl.col("rwa_final").alias("rwa_pre_floor"))

    # Get SA RWA for each exposure. If calculate_unified already stored
    # sa_rwa inline (single-pass path), use it directly. Otherwise join
    # from the separate SA results frame (aggregate_with_audit path).
    combined_cols = set(combined.collect_schema().names())
    if "sa_rwa" in combined_cols:
        result = combined
    else:
        sa_cols = set(sa_results.collect_schema().names())
        sa_rwa_col = resolve_rwa_col(sa_cols)
        if not sa_rwa_col:
            summary = OutputFloorSummary(
                u_trea=0.0,
                s_trea=0.0,
                floor_pct=floor_pct,
                floor_threshold=0.0,
                shortfall=0.0,
                portfolio_floor_binding=False,
                total_rwa_post_floor=0.0,
            )
            return combined, empty_frame(FLOOR_IMPACT_SCHEMA), summary

        sa_rwa = sa_results.select(
            pl.col("exposure_reference"),
            pl.col(sa_rwa_col).alias("sa_rwa"),
        )
        result = combined.join(sa_rwa, on="exposure_reference", how="left", suffix="_sa")

    # --- Portfolio-level output floor (Art. 92 para 2A) ---
    #
    # 1. Compute portfolio totals: U-TREA and S-TREA for floor-eligible
    #    exposures (IRB + slotting). SA exposures cancel out (same RWA
    #    in both U-TREA and S-TREA) so we only need the modelled subset.
    #
    # 2. If floor binds (floor_pct * S-TREA > U-TREA), distribute the
    #    shortfall pro-rata by each exposure's sa_rwa share.
    #
    # 3. Per-exposure columns: floor_rwa, floor_impact_rwa, is_floor_binding,
    #    rwa_final (post-floor), output_floor_pct for COREP reporting.
    floor_eligible_approaches = list(FLOOR_ELIGIBLE_APPROACHES)
    is_eligible = pl.col("approach_applied").is_in(floor_eligible_approaches)
    sa_rwa_filled = pl.col("sa_rwa").fill_null(0.0)

    result = (
        result
        # Step 1: Portfolio-level totals (broadcast as scalar to every row)
        .with_columns(
            pl.when(is_eligible)
            .then(pl.col("rwa_pre_floor"))
            .otherwise(0.0)
            .sum()
            .alias("_u_trea"),
            pl.when(is_eligible)
            .then(sa_rwa_filled)
            .otherwise(0.0)
            .sum()
            .alias("_s_trea"),
        )
        # Step 2: Floor threshold and shortfall
        .with_columns(
            (pl.col("_s_trea") * floor_pct).alias("_floor_threshold"),
            pl.max_horizontal(
                pl.col("_s_trea") * floor_pct - pl.col("_u_trea"),
                pl.lit(0.0),
            ).alias("_shortfall"),
            (pl.col("_s_trea") * floor_pct > pl.col("_u_trea")).alias(
                "_portfolio_floor_binds"
            ),
        )
        # Step 3: Each eligible exposure's share of total S-TREA
        .with_columns(
            pl.when(is_eligible & (pl.col("_s_trea") > 0))
            .then(sa_rwa_filled / pl.col("_s_trea"))
            .otherwise(0.0)
            .alias("_sa_share"),
        )
        # Step 4: Per-exposure floor columns
        .with_columns(
            (sa_rwa_filled * floor_pct).alias("floor_rwa"),
            pl.lit(floor_pct).alias("output_floor_pct"),
            # Pro-rata add-on: shortfall × this exposure's S-TREA share
            pl.when(is_eligible)
            .then(pl.col("_shortfall") * pl.col("_sa_share"))
            .otherwise(0.0)
            .alias("floor_impact_rwa"),
            # Portfolio-level binding flag (same for all eligible rows)
            pl.when(is_eligible)
            .then(pl.col("_portfolio_floor_binds"))
            .otherwise(pl.lit(False))
            .alias("is_floor_binding"),
        )
        # Step 5: Final RWA = pre-floor + pro-rata add-on
        .with_columns(
            pl.when(is_eligible)
            .then(pl.col("rwa_pre_floor") + pl.col("floor_impact_rwa"))
            .otherwise(pl.col("rwa_pre_floor"))
            .alias("rwa_final"),
        )
    )

    # Extract portfolio-level summary (requires one collect — acceptable at
    # the aggregator boundary per project convention).  fill_null handles
    # the edge case of zero-row input (all sums are null → 0.0).
    summary_row = result.select(
        pl.col("_u_trea").first().fill_null(0.0),
        pl.col("_s_trea").first().fill_null(0.0),
        pl.col("_floor_threshold").first().fill_null(0.0),
        pl.col("_shortfall").first().fill_null(0.0),
        pl.col("_portfolio_floor_binds").first().fill_null(False),
    ).collect()

    u_trea = float(summary_row["_u_trea"][0])
    s_trea = float(summary_row["_s_trea"][0])
    floor_threshold = float(summary_row["_floor_threshold"][0])
    shortfall = float(summary_row["_shortfall"][0])
    binding = bool(summary_row["_portfolio_floor_binds"][0])

    summary = OutputFloorSummary(
        u_trea=u_trea,
        s_trea=s_trea,
        floor_pct=floor_pct,
        floor_threshold=floor_threshold,
        shortfall=shortfall,
        portfolio_floor_binding=binding,
        total_rwa_post_floor=u_trea + shortfall,
    )

    # Drop internal columns
    result = result.drop(
        ["_u_trea", "_s_trea", "_floor_threshold", "_shortfall",
         "_portfolio_floor_binds", "_sa_share"],
        strict=False,
    )

    # Generate floor impact analysis (floor-eligible rows only)
    result_cols = set(result.collect_schema().names())
    floor_impact = result.select(
        pl.col("exposure_reference"),
        pl.col("approach_applied"),
        col_or_default("exposure_class", result_cols),
        pl.col("rwa_pre_floor"),
        pl.col("floor_rwa"),
        pl.col("is_floor_binding"),
        pl.col("floor_impact_rwa"),
        pl.col("rwa_final").alias("rwa_post_floor"),
        pl.col("output_floor_pct"),
    ).filter(pl.col("approach_applied").is_in(floor_eligible_approaches))

    return result, floor_impact, summary
