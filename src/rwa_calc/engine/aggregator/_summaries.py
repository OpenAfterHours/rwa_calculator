"""
Summary generation by exposure class and approach.

Internal module — not part of the public API.
"""

from __future__ import annotations

from typing import cast

import polars as pl


def generate_summary_by_class(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate RWA summary by exposure class.

    Uses post-CRM reporting columns when available, so guaranteed
    portions are counted under the guarantor's exposure class.
    """
    cols = set(results.collect_schema().names())
    has_reporting = "reporting_exposure_class" in cols and "reporting_ead" in cols

    if has_reporting:
        ead_col: str | None = "reporting_ead"
    elif "ead_final" in cols:
        ead_col = "ead_final"
    else:
        ead_col = None

    if has_reporting and "reporting_rw" in cols:
        rw_col: str | None = "reporting_rw"
    elif "risk_weight" in cols:
        rw_col = "risk_weight"
    else:
        rw_col = None

    if has_reporting:
        group_col: str | None = "reporting_exposure_class"
    elif "exposure_class" in cols:
        group_col = "exposure_class"
    else:
        group_col = None

    agg_exprs = _build_class_agg_exprs(cols, ead_col, rw_col, has_reporting)

    if group_col:
        summary = results.group_by(group_col).agg(agg_exprs)
        if group_col != "exposure_class":
            summary = summary.rename({group_col: "exposure_class"})
    else:
        summary = results.select(agg_exprs).with_columns([pl.lit("ALL").alias("exposure_class")])

    return _with_avg_risk_weight(summary, ead_col, rw_col)


def generate_summary_by_approach(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate RWA summary by calculation approach.

    Uses post-CRM reporting columns when available, so guaranteed
    portions are counted under the guarantor's approach.
    """
    cols = set(results.collect_schema().names())
    has_reporting = "reporting_approach" in cols and "reporting_ead" in cols

    if has_reporting:
        ead_col: str | None = "reporting_ead"
    elif "ead_final" in cols:
        ead_col = "ead_final"
    else:
        ead_col = None

    rw_col = "reporting_rw" if (has_reporting and "reporting_rw" in cols) else None

    if has_reporting:
        group_col: str | None = "reporting_approach"
    elif "approach_applied" in cols:
        group_col = "approach_applied"
    else:
        group_col = None

    agg_exprs = _build_approach_agg_exprs(cols, ead_col, rw_col, has_reporting)

    if group_col:
        summary = results.group_by(group_col).agg(agg_exprs)
        if group_col != "approach_applied":
            summary = summary.rename({group_col: "approach_applied"})
    else:
        summary = results.select(agg_exprs).with_columns([pl.lit("ALL").alias("approach_applied")])

    return summary


# =============================================================================
# Private helpers
# =============================================================================


def _floor_addon_expr(cols: set[str], ead_col: str | None) -> pl.Expr:
    """Per-row output-floor add-on to fold into the reporting ``total_rwa``.

    The post-CRM reporting ``total_rwa`` is ``reporting_ead * reporting_rw``,
    which equals each row's PRE-floor RWA (the floor does not recompute
    ``reporting_rw``).  When the portfolio output floor binds, the per-row
    pro-rata add-on lands in ``floor_impact_rwa`` on the (possibly floored)
    combined frame.  We add it back here so the summed ``total_rwa`` reconciles
    with ``output_floor_summary.total_rwa_post_floor`` (PRA PS1/26 Art. 92(2A)).

    The add-on is allocated by each reporting row's ``reporting_ead`` share of
    the original ``ead_final`` so a guarantee-split exposure (two reporting
    rows summing to ``ead_final``) does not double-count the add-on.  Rows
    where the floor did not run, did not bind, or are not floor-eligible carry
    ``floor_impact_rwa = 0`` (or the column is absent), so this is a no-op.
    """
    if "floor_impact_rwa" not in cols:
        return pl.lit(0.0)

    addon = pl.col("floor_impact_rwa").fill_null(0.0)
    if ead_col and "ead_final" in cols and ead_col != "ead_final":
        share = (
            pl.when(pl.col("ead_final") != 0)
            .then(pl.col(ead_col) / pl.col("ead_final"))
            .otherwise(pl.lit(0.0))
        )
        return addon * share
    return addon


def _build_class_agg_exprs(
    cols: set[str],
    ead_col: str | None,
    rw_col: str | None,
    has_reporting: bool,
) -> list[pl.Expr]:
    """Build aggregation expressions for `generate_summary_by_class`."""
    agg_exprs: list[pl.Expr] = [
        pl.col(ead_col).sum().alias("total_ead") if ead_col else pl.lit(0.0).alias("total_ead"),
        pl.len().alias("exposure_count"),
    ]

    if has_reporting and rw_col:
        agg_exprs.append(
            (pl.col(cast("str", ead_col)) * pl.col(rw_col) + _floor_addon_expr(cols, ead_col))
            .sum()
            .alias("total_rwa")
        )
    elif "rwa_final" in cols:
        agg_exprs.append(pl.col("rwa_final").sum().alias("total_rwa"))
    else:
        agg_exprs.append(pl.lit(0.0).alias("total_rwa"))

    if ead_col and rw_col:
        agg_exprs.append((pl.col(rw_col) * pl.col(ead_col)).sum().alias("_weighted_rw"))

    if "is_floor_binding" in cols:
        agg_exprs.append(
            pl.col("is_floor_binding").sum().cast(pl.UInt32).alias("floor_binding_count")
        )

    return agg_exprs


def _build_approach_agg_exprs(
    cols: set[str],
    ead_col: str | None,
    rw_col: str | None,
    has_reporting: bool,
) -> list[pl.Expr]:
    """Build aggregation expressions for `generate_summary_by_approach`."""
    agg_exprs: list[pl.Expr] = [
        pl.col(ead_col).sum().alias("total_ead") if ead_col else pl.lit(0.0).alias("total_ead"),
        pl.len().alias("exposure_count"),
    ]

    if has_reporting and rw_col:
        agg_exprs.append(
            (pl.col(cast("str", ead_col)) * pl.col(rw_col) + _floor_addon_expr(cols, ead_col))
            .sum()
            .alias("total_rwa")
        )
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

    return agg_exprs


def _with_avg_risk_weight(
    summary: pl.LazyFrame,
    ead_col: str | None,
    rw_col: str | None,
) -> pl.LazyFrame:
    """Add `avg_risk_weight` column; no-op when ead/rw columns are unavailable."""
    if not (ead_col and rw_col):
        return summary

    return summary.with_columns(
        [
            pl.when(pl.col("total_ead") > 0)
            .then(pl.col("_weighted_rw") / pl.col("total_ead"))
            .otherwise(pl.lit(0.0))
            .alias("avg_risk_weight"),
        ]
    ).drop("_weighted_rw")
