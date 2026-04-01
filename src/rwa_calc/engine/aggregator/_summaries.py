"""
Summary generation by exposure class and approach.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl


def generate_summary_by_class(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate RWA summary by exposure class.

    Uses post-CRM reporting columns when available, so guaranteed
    portions are counted under the guarantor's exposure class.
    """
    cols = set(results.collect_schema().names())

    # Use post-CRM reporting columns when available, otherwise fall back
    has_reporting = "reporting_exposure_class" in cols and "reporting_ead" in cols
    ead_col = "reporting_ead" if has_reporting else ("ead_final" if "ead_final" in cols else None)
    rw_col = (
        "reporting_rw"
        if (has_reporting and "reporting_rw" in cols)
        else ("risk_weight" if "risk_weight" in cols else None)
    )
    group_col = (
        "reporting_exposure_class"
        if has_reporting
        else ("exposure_class" if "exposure_class" in cols else None)
    )

    # Build aggregation expressions
    agg_exprs: list[pl.Expr] = [
        pl.col(ead_col).sum().alias("total_ead") if ead_col else pl.lit(0.0).alias("total_ead"),
        pl.len().alias("exposure_count"),
    ]

    # RWA: use reporting_ead * reporting_rw for post-CRM, else rwa_final
    if has_reporting and rw_col:
        agg_exprs.append((pl.col(ead_col) * pl.col(rw_col)).sum().alias("total_rwa"))
    elif "rwa_final" in cols:
        agg_exprs.append(pl.col("rwa_final").sum().alias("total_rwa"))
    else:
        agg_exprs.append(pl.lit(0.0).alias("total_rwa"))

    # Add weighted average risk weight if possible
    if ead_col and rw_col:
        agg_exprs.append((pl.col(rw_col) * pl.col(ead_col)).sum().alias("_weighted_rw"))

    # Add floor binding count if applicable
    if "is_floor_binding" in cols:
        agg_exprs.append(
            pl.col("is_floor_binding").sum().cast(pl.UInt32).alias("floor_binding_count")
        )

    # Group by exposure class
    if group_col:
        summary = results.group_by(group_col).agg(agg_exprs)
        if group_col != "exposure_class":
            summary = summary.rename({group_col: "exposure_class"})
    else:
        summary = results.select(agg_exprs).with_columns([pl.lit("ALL").alias("exposure_class")])

    # Calculate average risk weight
    if ead_col and rw_col:
        summary = summary.with_columns(
            [
                pl.when(pl.col("total_ead") > 0)
                .then(pl.col("_weighted_rw") / pl.col("total_ead"))
                .otherwise(pl.lit(0.0))
                .alias("avg_risk_weight"),
            ]
        ).drop("_weighted_rw")

    return summary


def generate_summary_by_approach(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate RWA summary by calculation approach.

    Uses post-CRM reporting columns when available, so guaranteed
    portions are counted under the guarantor's approach.
    """
    cols = set(results.collect_schema().names())

    # Use post-CRM reporting columns when available
    has_reporting = "reporting_approach" in cols and "reporting_ead" in cols
    ead_col = "reporting_ead" if has_reporting else ("ead_final" if "ead_final" in cols else None)
    rw_col = "reporting_rw" if (has_reporting and "reporting_rw" in cols) else None
    group_col = (
        "reporting_approach"
        if has_reporting
        else ("approach_applied" if "approach_applied" in cols else None)
    )

    # Build aggregation expressions
    agg_exprs: list[pl.Expr] = [
        pl.col(ead_col).sum().alias("total_ead") if ead_col else pl.lit(0.0).alias("total_ead"),
        pl.len().alias("exposure_count"),
    ]

    # RWA: use reporting_ead * reporting_rw for post-CRM, else rwa_final
    if has_reporting and rw_col:
        agg_exprs.append((pl.col(ead_col) * pl.col(rw_col)).sum().alias("total_rwa"))
    elif "rwa_final" in cols:
        agg_exprs.append(pl.col("rwa_final").sum().alias("total_rwa"))
    else:
        agg_exprs.append(pl.lit(0.0).alias("total_rwa"))

    if "floor_impact_rwa" in cols:
        agg_exprs.append(pl.col("floor_impact_rwa").sum().alias("total_floor_impact"))
    if "expected_loss" in cols:
        agg_exprs.append(pl.col("expected_loss").sum().alias("total_expected_loss"))
    if "el_shortfall" in cols:
        agg_exprs.append(pl.col("el_shortfall").sum().alias("total_el_shortfall"))
    if "el_excess" in cols:
        agg_exprs.append(pl.col("el_excess").sum().alias("total_el_excess"))

    # Group by approach
    if group_col:
        summary = results.group_by(group_col).agg(agg_exprs)
        if group_col != "approach_applied":
            summary = summary.rename({group_col: "approach_applied"})
    else:
        summary = results.select(agg_exprs).with_columns(
            [pl.lit("ALL").alias("approach_applied")]
        )

    return summary
