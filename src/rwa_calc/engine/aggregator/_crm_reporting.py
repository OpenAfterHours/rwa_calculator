"""
Pre/post-CRM regulatory reporting views.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.engine.aggregator._schemas import (
    POST_CRM_DETAILED_SCHEMA,
    POST_CRM_SUMMARY_SCHEMA,
    PRE_CRM_SUMMARY_SCHEMA,
)
from rwa_calc.engine.aggregator._utils import col_or_default, empty_frame


def generate_pre_crm_summary(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate summary grouped by pre-CRM exposure class.

    Shows exposures under their ORIGINAL risk class (before guarantee substitution).
    """
    cols = set(results.collect_schema().names())

    if "pre_crm_exposure_class" not in cols:
        return empty_frame(PRE_CRM_SUMMARY_SCHEMA)

    ead_col = "ead_final" if "ead_final" in cols else "ead"
    rwa_col = "rwa_final" if "rwa_final" in cols else "rwa"

    agg_exprs: list[pl.Expr] = [
        pl.col(ead_col).sum().alias("total_ead"),
        pl.col(rwa_col).sum().alias("total_rwa_blended"),
        pl.len().alias("exposure_count"),
    ]

    if "pre_crm_risk_weight" in cols:
        agg_exprs.append(
            (pl.col(ead_col) * pl.col("pre_crm_risk_weight")).sum().alias("total_rwa_pre_crm")
        )
    if "is_guaranteed" in cols:
        agg_exprs.append(pl.col("is_guaranteed").sum().cast(pl.UInt32).alias("guaranteed_count"))

    return results.group_by("pre_crm_exposure_class").agg(agg_exprs)


def generate_post_crm_detailed(results: pl.LazyFrame) -> pl.LazyFrame:
    """
    Generate detailed view with guaranteed exposures split into two rows.

    For each guaranteed exposure:
      Row 1: Unguaranteed portion -> original counterparty, original exposure class
      Row 2: Guaranteed portion -> guarantor counterparty, guarantor exposure class

    For non-guaranteed exposures:
      Single row -> original counterparty, original exposure class
    """
    cols = set(results.collect_schema().names())

    ead_col = "ead_final" if "ead_final" in cols else ("ead" if "ead" in cols else None)
    exposure_class_col = "exposure_class" if "exposure_class" in cols else None

    if not ead_col or not exposure_class_col:
        return empty_frame(POST_CRM_DETAILED_SCHEMA)

    # Check if guarantee columns exist
    required_cols = {"is_guaranteed", "guaranteed_portion", "unguaranteed_portion"}
    if not required_cols.issubset(cols):
        return _build_original_only_rows(results, cols, ead_col, exposure_class_col)

    non_guaranteed = _build_non_guaranteed_rows(results, cols, ead_col, exposure_class_col)
    unguar_portion = _build_unguaranteed_portions(results, cols, ead_col, exposure_class_col)
    guar_portion = _build_guaranteed_portions(results, cols, ead_col, exposure_class_col)

    return pl.concat([non_guaranteed, unguar_portion, guar_portion], how="diagonal_relaxed")


def generate_post_crm_summary(detailed: pl.LazyFrame) -> pl.LazyFrame:
    """
    Aggregate post-CRM detailed view by exposure class.

    Shows RWA under POST-CRM exposure classes where guaranteed portions
    are reported under the guarantor's exposure class.
    """
    cols = set(detailed.collect_schema().names())

    if "reporting_exposure_class" not in cols:
        return empty_frame(POST_CRM_SUMMARY_SCHEMA)

    return detailed.group_by("reporting_exposure_class").agg(
        [
            pl.col("reporting_ead").sum().alias("total_ead"),
            (pl.col("reporting_ead") * pl.col("reporting_rw")).sum().alias("total_rwa"),
            pl.len().alias("exposure_count"),
            pl.col("crm_portion_type")
            .filter(pl.col("crm_portion_type") == "guaranteed")
            .len()
            .alias("guaranteed_portions"),
        ]
    )


# =============================================================================
# Private post-CRM detail helpers
# =============================================================================


def _build_original_only_rows(
    results: pl.LazyFrame,
    cols: set[str],
    ead_col: str,
    exposure_class_col: str,
) -> pl.LazyFrame:
    """Build reporting rows for data with no guarantee information."""
    rw_col = "risk_weight" if "risk_weight" in cols else None
    return results.with_columns(
        [
            col_or_default("counterparty_reference", cols).alias("reporting_counterparty"),
            pl.col(exposure_class_col).alias("reporting_exposure_class"),
            pl.col(ead_col).alias("reporting_ead"),
            (pl.col(rw_col) if rw_col else pl.lit(1.0)).alias("reporting_rw"),
            col_or_default("approach_applied", cols).alias("reporting_approach"),
            pl.lit("original").alias("crm_portion_type"),
        ]
    )


def _build_non_guaranteed_rows(
    results: pl.LazyFrame,
    cols: set[str],
    ead_col: str,
    exposure_class_col: str,
) -> pl.LazyFrame:
    """Build reporting rows for non-guaranteed exposures."""
    rw_col = "risk_weight" if "risk_weight" in cols else None
    return results.filter(~pl.col("is_guaranteed")).with_columns(
        [
            col_or_default("counterparty_reference", cols).alias("reporting_counterparty"),
            pl.col(exposure_class_col).alias("reporting_exposure_class"),
            pl.col(ead_col).alias("reporting_ead"),
            (pl.col(rw_col) if rw_col else pl.lit(1.0)).alias("reporting_rw"),
            col_or_default("approach_applied", cols).alias("reporting_approach"),
            pl.lit("original").alias("crm_portion_type"),
        ]
    )


def _build_unguaranteed_portions(
    results: pl.LazyFrame,
    cols: set[str],
    ead_col: str,
    exposure_class_col: str,
) -> pl.LazyFrame:
    """Build reporting rows for the unguaranteed portion of guaranteed exposures."""
    pre_crm_class_col = (
        "pre_crm_exposure_class" if "pre_crm_exposure_class" in cols else exposure_class_col
    )
    pre_crm_rw_col = "pre_crm_risk_weight" if "pre_crm_risk_weight" in cols else None
    rw_col = "risk_weight" if "risk_weight" in cols else None
    rw_expr = (
        pl.col(pre_crm_rw_col) if pre_crm_rw_col else (pl.col(rw_col) if rw_col else pl.lit(1.0))
    )

    return results.filter(pl.col("is_guaranteed")).with_columns(
        [
            col_or_default("counterparty_reference", cols).alias("reporting_counterparty"),
            pl.col(pre_crm_class_col).alias("reporting_exposure_class"),
            pl.col("unguaranteed_portion").alias("reporting_ead"),
            rw_expr.alias("reporting_rw"),
            col_or_default("approach_applied", cols).alias("reporting_approach"),
            pl.lit("unguaranteed").alias("crm_portion_type"),
        ]
    )


def _build_guaranteed_portions(
    results: pl.LazyFrame,
    cols: set[str],
    ead_col: str,
    exposure_class_col: str,
) -> pl.LazyFrame:
    """Build reporting rows for the guaranteed portion of guaranteed exposures."""
    guarantor_ref_col = "guarantor_reference" if "guarantor_reference" in cols else None
    post_crm_class_col = (
        "post_crm_exposure_class_guaranteed"
        if "post_crm_exposure_class_guaranteed" in cols
        else exposure_class_col
    )
    guarantor_rw_col = "guarantor_rw" if "guarantor_rw" in cols else None
    rw_col = "risk_weight" if "risk_weight" in cols else None
    rw_expr = (
        pl.col(guarantor_rw_col)
        if guarantor_rw_col
        else (pl.col(rw_col) if rw_col else pl.lit(1.0))
    )

    # For guaranteed portion: use "standardised" when guarantor is SA, else original
    has_approach = "approach_applied" in cols
    has_guarantor_approach = "guarantor_approach" in cols
    approach_expr = col_or_default("approach_applied", cols)
    if has_guarantor_approach and has_approach:
        guaranteed_approach_expr = (
            pl.when(pl.col("guarantor_approach") == "sa")
            .then(pl.lit("standardised"))
            .otherwise(pl.col("approach_applied"))
        )
    else:
        guaranteed_approach_expr = approach_expr

    return results.filter(pl.col("is_guaranteed")).with_columns(
        [
            (
                pl.col(guarantor_ref_col)
                if guarantor_ref_col
                else col_or_default("counterparty_reference", cols)
            ).alias("reporting_counterparty"),
            pl.col(post_crm_class_col).alias("reporting_exposure_class"),
            pl.col("guaranteed_portion").alias("reporting_ead"),
            rw_expr.alias("reporting_rw"),
            guaranteed_approach_expr.alias("reporting_approach"),
            pl.lit("guaranteed").alias("crm_portion_type"),
        ]
    )
