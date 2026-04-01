"""
Supporting factor impact analysis (CRR only).

Internal module — not part of the public API.

References:
- CRR Art. 501/501a: SME and infrastructure supporting factors
"""

from __future__ import annotations

import polars as pl

from rwa_calc.engine.aggregator._schemas import SUPPORTING_FACTOR_SCHEMA
from rwa_calc.engine.aggregator._utils import col_or_default, empty_frame


def generate_supporting_factor_impact(sa_results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate supporting factor impact analysis.

    Shows the RWA reduction from SME and infrastructure factors.
    """
    cols = set(sa_results.collect_schema().names())

    has_sf = "supporting_factor" in cols
    has_pre = "rwa_pre_factor" in cols
    has_post = "rwa_post_factor" in cols

    if not (has_sf and has_pre and has_post):
        return empty_frame(SUPPORTING_FACTOR_SCHEMA)

    has_applied = "supporting_factor_applied" in cols
    return sa_results.select(
        [
            pl.col("exposure_reference"),
            col_or_default("exposure_class", cols),
            col_or_default("is_sme", cols, pl.lit(False)),
            col_or_default("is_infrastructure", cols, pl.lit(False)),
            col_or_default("ead_final", cols, pl.lit(0.0), pl.Float64),
            pl.col("supporting_factor"),
            pl.col("rwa_pre_factor"),
            pl.col("rwa_post_factor"),
            (pl.col("rwa_pre_factor") - pl.col("rwa_post_factor")).alias(
                "supporting_factor_impact"
            ),
            pl.col("supporting_factor_applied")
            if has_applied
            else (pl.col("supporting_factor") < 1.0).alias("supporting_factor_applied"),
        ]
    ).filter(pl.col("supporting_factor_applied"))
