"""
Output floor application and impact analysis (Basel 3.1).

Internal module — not part of the public API.

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation
"""

from __future__ import annotations

import polars as pl

from rwa_calc.engine.aggregator._schemas import FLOOR_IMPACT_SCHEMA, IRB_APPROACHES
from rwa_calc.engine.aggregator._utils import col_or_default, empty_frame, resolve_rwa_col


def apply_floor_with_impact(
    combined: pl.LazyFrame,
    sa_results: pl.LazyFrame,
    floor_pct: float,
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """
    Apply output floor and generate impact analysis.

    Args:
        combined: Combined results with ``rwa_final`` column.
        sa_results: SA results to derive floor RWA from.
        floor_pct: Floor percentage (e.g. 0.5 for 50%).

    Returns:
        Tuple of (floored results, floor impact analysis).
    """
    # Ensure combined has rwa_final column
    combined_cols = set(combined.collect_schema().names())
    if "rwa_final" not in combined_cols:
        rwa_col = resolve_rwa_col(combined_cols)
        if rwa_col:
            combined = combined.with_columns([pl.col(rwa_col).alias("rwa_final")])
        else:
            combined = combined.with_columns([pl.lit(0.0).alias("rwa_final")])

    # Store pre-floor RWA for impact calculation
    combined = combined.with_columns([pl.col("rwa_final").alias("rwa_pre_floor")])

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
            return combined, empty_frame(FLOOR_IMPACT_SCHEMA)

        sa_rwa = sa_results.select(
            [
                pl.col("exposure_reference"),
                pl.col(sa_rwa_col).alias("sa_rwa"),
            ]
        )
        result = combined.join(sa_rwa, on="exposure_reference", how="left", suffix="_sa")

    # Apply floor only to IRB exposures
    irb_approaches = list(IRB_APPROACHES)
    result = (
        result.with_columns(
            [
                (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
                pl.lit(floor_pct).alias("output_floor_pct"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("approach_applied").is_in(irb_approaches))
                .then(pl.col("floor_rwa") > pl.col("rwa_pre_floor"))
                .otherwise(pl.lit(False))
                .alias("is_floor_binding"),
                pl.when(pl.col("approach_applied").is_in(irb_approaches))
                .then(pl.max_horizontal(pl.col("rwa_pre_floor"), pl.col("floor_rwa")))
                .otherwise(pl.col("rwa_pre_floor"))
                .alias("rwa_final"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("is_floor_binding"))
                .then(pl.col("floor_rwa") - pl.col("rwa_pre_floor"))
                .otherwise(pl.lit(0.0))
                .alias("floor_impact_rwa"),
            ]
        )
    )

    # Generate floor impact analysis
    result_cols = set(result.collect_schema().names())
    floor_impact = result.select(
        [
            pl.col("exposure_reference"),
            pl.col("approach_applied"),
            col_or_default("exposure_class", result_cols),
            pl.col("rwa_pre_floor"),
            pl.col("floor_rwa"),
            pl.col("is_floor_binding"),
            pl.col("floor_impact_rwa"),
            pl.col("rwa_final").alias("rwa_post_floor"),
            pl.col("output_floor_pct"),
        ]
    ).filter(pl.col("approach_applied").is_in(irb_approaches))

    return result, floor_impact
