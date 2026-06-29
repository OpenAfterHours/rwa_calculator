"""
Summary generation by exposure class and approach.

Internal module — not part of the public API.
"""

from __future__ import annotations

from typing import cast

import polars as pl

# UI methodology labels (presentation strings, not regulatory values). The
# calculation approaches collapse into the three methodology families the
# results page groups by — standardised -> STD, foundation IRB -> FIRB, advanced
# IRB -> AIRB (retail A-IRB included) — with slotting and equity surfaced under
# their own labels when present.
_METHOD_STD = "STD"
_METHOD_FIRB = "FIRB"
_METHOD_AIRB = "AIRB"
_METHOD_SLOTTING = "SLOTTING"
_METHOD_EQUITY = "EQUITY"


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


def generate_summary_by_class_method(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate RWA summary by exposure class AND methodology (STD / FIRB / AIRB / …).

    The two-dimensional twin of ``generate_summary_by_class``: groups the same
    post-CRM reporting rows by ``(exposure_class, method)`` so the UI can show
    RWA per methodology within each exposure class. It reuses the identical
    reporting columns and aggregation expressions, so summing ``total_rwa`` over
    methods within a class reconciles exactly with ``generate_summary_by_class``
    (guarantee splits and the output-floor add-on are already folded in).

    Output columns: ``exposure_class``, ``method``, ``total_ead``, ``total_rwa``,
    ``exposure_count``, ``avg_risk_weight``.
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
        class_col: str | None = "reporting_exposure_class"
    elif "exposure_class" in cols:
        class_col = "exposure_class"
    else:
        class_col = None

    if has_reporting and "reporting_approach" in cols:
        approach_col: str | None = "reporting_approach"
    elif "approach_applied" in cols:
        approach_col = "approach_applied"
    else:
        approach_col = None

    agg_exprs = _build_class_agg_exprs(cols, ead_col, rw_col, has_reporting)

    if class_col and approach_col:
        summary = (
            results.with_columns(_method_expr(approach_col).alias("method"))
            .group_by([class_col, "method"])
            .agg(agg_exprs)
        )
        if class_col != "exposure_class":
            summary = summary.rename({class_col: "exposure_class"})
    else:
        summary = results.select(agg_exprs).with_columns(
            [pl.lit("ALL").alias("exposure_class"), pl.lit(_METHOD_STD).alias("method")]
        )

    return _with_avg_risk_weight(summary, ead_col, rw_col)


# =============================================================================
# Private helpers
# =============================================================================


def _method_expr(approach_col: str) -> pl.Expr:
    """Map a calculation approach to a UI methodology label (STD/FIRB/AIRB/…).

    Presentation grouping for the results page: the standardised approach maps to
    STD, foundation IRB to FIRB, advanced IRB to AIRB (retail A-IRB folded in),
    with slotting and equity under their own labels. The match is
    case-insensitive and accepts both the ``ApproachType`` values
    ("standardised"/"foundation_irb"/"advanced_irb"/…) and the short aliases
    (SA/FIRB/AIRB/SLOTTING) that appear on branch frames; anything unrecognised
    falls through to its own upper-cased label rather than being dropped.
    """
    # A null approach yields null through every str op, so it falls through the
    # when-chain to the ``otherwise`` (-> "OTHER") — no leading fill is needed.
    approach = pl.col(approach_col).cast(pl.String).str.to_lowercase()
    return (
        pl.when(approach.str.starts_with("standard") | approach.is_in(["sa", "std"]))
        .then(pl.lit(_METHOD_STD))
        .when(approach.str.contains("foundation", literal=True) | (approach == "firb"))
        .then(pl.lit(_METHOD_FIRB))
        .when(approach.str.contains("advanced", literal=True) | (approach == "airb"))
        .then(pl.lit(_METHOD_AIRB))
        .when(approach.str.contains("slotting", literal=True))
        .then(pl.lit(_METHOD_SLOTTING))
        .when(approach.str.contains("equity", literal=True))
        .then(pl.lit(_METHOD_EQUITY))
        .otherwise(pl.col(approach_col).cast(pl.String).fill_null("OTHER").str.to_uppercase())
    )


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
