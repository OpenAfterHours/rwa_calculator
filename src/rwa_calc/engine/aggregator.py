"""
Output Aggregator for RWA Calculations.

Pipeline position:
    SACalculator/IRBCalculator/SlottingCalculator -> OutputAggregator -> Pipeline output

Key responsibilities:
- Canonical constants (IRB approach identifiers, empty-frame schemas)
- RWA column resolution with consistent fallback chains
- Result preparation per approach (SA, IRB, Slotting, Equity)
- Output floor application and impact analysis (Basel 3.1 only)
- Supporting factor tracking (CRR only)
- Summary generation by exposure class and approach
- Pre/post-CRM regulatory reporting views
- Portfolio-level EL summary with T2 credit cap

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation
- CRR Art. 501/501a: SME and infrastructure supporting factors
- CRR Art. 62(d): T2 credit cap (0.6% of IRB RWA)
- CRR Art. 158-159: EL shortfall/excess treatment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    ELPortfolioSummary,
    EquityResultBundle,
    IRBResultBundle,
    SAResultBundle,
    SlottingResultBundle,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# Constants
# =============================================================================

# Canonical IRB approach identifiers — union of ApproachType enum values and
# aggregator fallback labels. Used for output floor application.
IRB_APPROACHES: frozenset[str] = frozenset(
    {
        "foundation_irb",
        "advanced_irb",  # ApproachType enum values
        "FIRB",
        "AIRB",
        "IRB",  # Aggregator fallback labels
    }
)

# T2 credit cap rate per CRR Art. 62(d): 0.6% of IRB credit-risk RWA.
T2_CREDIT_CAP_RATE = 0.006

# =============================================================================
# Empty-frame schemas
# =============================================================================

RESULT_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "approach_applied": pl.String,
    "exposure_class": pl.String,
    "ead_final": pl.Float64,
    "risk_weight": pl.Float64,
    "rwa_final": pl.Float64,
}

FLOOR_IMPACT_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "approach_applied": pl.String,
    "exposure_class": pl.String,
    "rwa_pre_floor": pl.Float64,
    "floor_rwa": pl.Float64,
    "is_floor_binding": pl.Boolean,
    "floor_impact_rwa": pl.Float64,
    "rwa_post_floor": pl.Float64,
    "output_floor_pct": pl.Float64,
}

POST_CRM_DETAILED_SCHEMA: dict[str, pl.DataType] = {
    "reporting_counterparty": pl.String,
    "reporting_exposure_class": pl.String,
    "reporting_ead": pl.Float64,
    "reporting_rw": pl.Float64,
    "reporting_approach": pl.String,
    "crm_portion_type": pl.String,
}

POST_CRM_SUMMARY_SCHEMA: dict[str, pl.DataType] = {
    "reporting_exposure_class": pl.String,
    "total_ead": pl.Float64,
    "total_rwa": pl.Float64,
    "exposure_count": pl.UInt32,
}

PRE_CRM_SUMMARY_SCHEMA: dict[str, pl.DataType] = {
    "pre_crm_exposure_class": pl.String,
    "total_ead": pl.Float64,
    "total_rwa_blended": pl.Float64,
    "exposure_count": pl.UInt32,
}

SUPPORTING_FACTOR_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "supporting_factor": pl.Float64,
    "rwa_pre_factor": pl.Float64,
    "rwa_post_factor": pl.Float64,
    "supporting_factor_impact": pl.Float64,
    "supporting_factor_applied": pl.Boolean,
}


# =============================================================================
# Utility functions
# =============================================================================


def resolve_rwa_col(col_names: frozenset[str] | list[str] | set[str]) -> str | None:
    """
    Resolve which RWA column to use with a consistent fallback chain.

    Order: rwa_post_factor -> rwa_final -> rwa.

    Returns:
        Column name, or None if no RWA column found.
    """
    names = col_names if isinstance(col_names, (frozenset, set)) else set(col_names)
    if "rwa_post_factor" in names:
        return "rwa_post_factor"
    if "rwa_final" in names:
        return "rwa_final"
    if "rwa" in names:
        return "rwa"
    return None


def col_or_default(
    name: str,
    cols: frozenset[str] | set[str],
    default: pl.Expr | None = None,
    dtype: pl.DataType = pl.String,
) -> pl.Expr:
    """
    Return ``pl.col(name)`` if the column exists, otherwise a default expression.

    Args:
        name: Column name to look for.
        cols: Available column names.
        default: Default expression. If None, uses ``pl.lit(None).cast(dtype)``.
        dtype: Data type for the null literal when no default is provided.
    """
    if name in cols:
        return pl.col(name)
    if default is not None:
        return default.alias(name)
    return pl.lit(None).cast(dtype).alias(name)


def empty_frame(schema: dict[str, pl.DataType]) -> pl.LazyFrame:
    """Create an empty LazyFrame from a schema dict."""
    return pl.LazyFrame({name: pl.Series([], dtype=dtype) for name, dtype in schema.items()})


# =============================================================================
# Result preparation functions
# =============================================================================


def prepare_sa_results(sa_results: pl.LazyFrame) -> pl.LazyFrame:
    """Add SA approach tag and normalize RWA column."""
    cols = set(sa_results.collect_schema().names())
    rwa_col = "rwa_post_factor" if "rwa_post_factor" in cols else "rwa"
    return sa_results.with_columns(
        [
            pl.lit("SA").alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ]
    )


def prepare_irb_results(irb_results: pl.LazyFrame) -> pl.LazyFrame:
    """Add IRB approach tag (with guarantee-based substitution) and normalize RWA."""
    cols = set(irb_results.collect_schema().names())

    # Determine base approach expression
    base_approach_expr = pl.col("approach") if "approach" in cols else pl.lit("FIRB")

    # Post-CRM: fully SA-guaranteed IRB exposures report as "standardised"
    if "guarantor_approach" in cols and "guarantee_ratio" in cols:
        approach_expr = (
            pl.when((pl.col("guarantor_approach") == "sa") & (pl.col("guarantee_ratio") >= 1.0))
            .then(pl.lit("standardised"))
            .otherwise(base_approach_expr)
        )
    else:
        approach_expr = base_approach_expr

    rwa_col = "rwa" if "rwa" in cols else "rwa_post_factor"
    return irb_results.with_columns(
        [
            approach_expr.alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ]
    )


def prepare_slotting_results(slotting_results: pl.LazyFrame) -> pl.LazyFrame:
    """Add SLOTTING approach tag and normalize RWA column."""
    cols = set(slotting_results.collect_schema().names())
    rwa_col = "rwa" if "rwa" in cols else "rwa_post_factor"
    return slotting_results.with_columns(
        [
            pl.lit("SLOTTING").alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ]
    )


def prepare_equity_results(equity_results: pl.LazyFrame) -> pl.LazyFrame:
    """Add EQUITY approach tag, ensure exposure_class exists, and normalize RWA."""
    cols = set(equity_results.collect_schema().names())
    rwa_col = "rwa" if "rwa" in cols else "rwa_final"

    result = equity_results
    if "exposure_class" not in cols:
        result = result.with_columns([pl.lit("equity").alias("exposure_class")])

    return result.with_columns(
        [
            pl.lit("EQUITY").alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ]
    )


def combine_results(
    sa_results: pl.LazyFrame | None = None,
    irb_results: pl.LazyFrame | None = None,
    slotting_results: pl.LazyFrame | None = None,
    equity_results: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """
    Combine SA, IRB, Slotting, and Equity results into a unified LazyFrame.

    Adds approach identification and standardizes column names.
    """
    frames: list[pl.LazyFrame] = []
    if sa_results is not None:
        frames.append(prepare_sa_results(sa_results))
    if irb_results is not None:
        frames.append(prepare_irb_results(irb_results))
    if slotting_results is not None:
        frames.append(prepare_slotting_results(slotting_results))
    if equity_results is not None:
        frames.append(prepare_equity_results(equity_results))

    if not frames:
        return empty_frame(RESULT_SCHEMA)
    if len(frames) == 1:
        return frames[0]
    return pl.concat(frames, how="diagonal_relaxed")


# =============================================================================
# Output floor
# =============================================================================


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


# =============================================================================
# Supporting factor impact
# =============================================================================


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


# =============================================================================
# Summary generation
# =============================================================================


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
        summary = results.select(agg_exprs).with_columns([pl.lit("ALL").alias("approach_applied")])

    return summary


# =============================================================================
# Pre/Post CRM reporting
# =============================================================================


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
# EL Portfolio Summary
# =============================================================================


def compute_el_portfolio_summary(
    irb_results: pl.LazyFrame | None,
) -> ELPortfolioSummary | None:
    """
    Compute portfolio-level EL summary with T2 credit cap.

    Aggregates per-exposure EL shortfall/excess across all IRB exposures
    and applies the T2 credit cap per CRR Art. 62(d).
    """
    if irb_results is None:
        return None

    cols = set(irb_results.collect_schema().names())
    if "el_shortfall" not in cols or "el_excess" not in cols:
        return None

    rwa_col = resolve_rwa_col(cols)
    if not rwa_col:
        return None

    has_el = "expected_loss" in cols
    has_provisions = "provision_allocated" in cols

    agg_exprs: list[pl.Expr] = [
        pl.col("el_shortfall").sum().alias("total_el_shortfall"),
        pl.col("el_excess").sum().alias("total_el_excess"),
        pl.col(rwa_col).sum().alias("total_irb_rwa"),
    ]
    if has_el:
        agg_exprs.append(pl.col("expected_loss").sum().alias("total_expected_loss"))
    if has_provisions:
        agg_exprs.append(pl.col("provision_allocated").sum().alias("total_provisions_allocated"))

    agg_df: pl.DataFrame = irb_results.select(agg_exprs).collect()

    total_el_shortfall = float(agg_df["total_el_shortfall"][0] or 0.0)
    total_el_excess = float(agg_df["total_el_excess"][0] or 0.0)
    total_irb_rwa = float(agg_df["total_irb_rwa"][0] or 0.0)
    total_expected_loss = float(agg_df["total_expected_loss"][0] or 0.0) if has_el else 0.0
    total_provisions = (
        float(agg_df["total_provisions_allocated"][0] or 0.0) if has_provisions else 0.0
    )

    # T2 credit cap: 0.6% of total IRB RWA (CRR Art. 62(d))
    t2_credit_cap = total_irb_rwa * T2_CREDIT_CAP_RATE
    t2_credit = min(total_el_excess, t2_credit_cap)

    # EL shortfall deduction: 50% CET1 + 50% T2 (CRR Art. 159)
    cet1_deduction = total_el_shortfall * 0.5
    t2_deduction = total_el_shortfall * 0.5

    return ELPortfolioSummary(
        total_expected_loss=total_expected_loss,
        total_provisions_allocated=total_provisions,
        total_el_shortfall=total_el_shortfall,
        total_el_excess=total_el_excess,
        total_irb_rwa=total_irb_rwa,
        t2_credit_cap=t2_credit_cap,
        t2_credit=t2_credit,
        cet1_deduction=cet1_deduction,
        t2_deduction=t2_deduction,
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


# =============================================================================
# Output Aggregator class
# =============================================================================


class OutputAggregator:
    """
    Aggregate final RWA results from all calculators.

    Implements OutputAggregatorProtocol for:
    - Combining SA, IRB, and Slotting results
    - Applying output floor (Basel 3.1)
    - Tracking supporting factor impact (CRR)
    - Generating summaries by exposure class and approach

    Usage:
        aggregator = OutputAggregator()
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_results,
            irb_bundle=irb_results,
            slotting_bundle=slotting_results,
            config=config,
        )
    """

    def __init__(self) -> None:
        """Initialize output aggregator."""
        pass

    # =========================================================================
    # Public API
    # =========================================================================

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Aggregate SA and IRB results into final output.

        Args:
            sa_results: Standardised Approach calculations
            irb_results: IRB approach calculations
            config: Calculation configuration

        Returns:
            Combined LazyFrame with all calculations
        """
        return combine_results(sa_results=sa_results, irb_results=irb_results)

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
        equity_bundle: EquityResultBundle | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate with full audit trail.

        Args:
            sa_bundle: SA calculation results bundle
            irb_bundle: IRB calculation results bundle
            slotting_bundle: Slotting calculation results bundle
            config: Calculation configuration
            equity_bundle: Equity calculation results bundle

        Returns:
            AggregatedResultBundle with full audit trail
        """
        # Get result frames from bundles
        sa_results = sa_bundle.results if sa_bundle else None
        irb_results = irb_bundle.results if irb_bundle else None
        slotting_results = slotting_bundle.results if slotting_bundle else None
        equity_results = equity_bundle.results if equity_bundle else None

        # Combine all results
        combined = combine_results(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
        )

        # Apply output floor (Basel 3.1 only)
        floor_impact = None
        if config.output_floor.enabled and irb_results is not None and sa_results is not None:
            floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))
            combined, floor_impact = apply_floor_with_impact(combined, sa_results, floor_pct)

        # Generate supporting factor impact (CRR only)
        supporting_factor_impact = None
        if config.supporting_factors.enabled and sa_results is not None:
            supporting_factor_impact = generate_supporting_factor_impact(sa_results)

        # Generate pre/post CRM summaries for regulatory reporting
        pre_crm_summary = generate_pre_crm_summary(combined)
        post_crm_detailed = generate_post_crm_detailed(combined)
        post_crm_summary = generate_post_crm_summary(post_crm_detailed)

        # Generate summaries from post-CRM detailed view (split rows for guarantees)
        summary_by_class = generate_summary_by_class(post_crm_detailed)
        summary_by_approach = generate_summary_by_approach(post_crm_detailed)

        # Compute portfolio-level EL summary with T2 credit cap (IRB only)
        el_summary = compute_el_portfolio_summary(irb_results)

        # Collect all errors from input bundles
        all_errors: list = []
        for bundle in (sa_bundle, irb_bundle, slotting_bundle, equity_bundle):
            if bundle:
                all_errors.extend(bundle.errors)

        return AggregatedResultBundle(
            results=combined,
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
            floor_impact=floor_impact,
            supporting_factor_impact=supporting_factor_impact,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            pre_crm_summary=pre_crm_summary,
            post_crm_detailed=post_crm_detailed,
            post_crm_summary=post_crm_summary,
            el_summary=el_summary,
            errors=all_errors,
        )

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply output floor to IRB RWA (Basel 3.1 only).

        Final RWA = max(IRB RWA, SA RWA x floor_percentage)

        Args:
            irb_rwa: IRB RWA before floor
            sa_equivalent_rwa: Equivalent SA RWA for comparison
            config: Calculation configuration

        Returns:
            LazyFrame with floor-adjusted RWA
        """
        if not config.output_floor.enabled:
            return irb_rwa

        floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))

        # Join IRB and SA results on exposure_reference
        sa_cols = set(sa_equivalent_rwa.collect_schema().names())
        sa_rwa_col = resolve_rwa_col(sa_cols)
        if not sa_rwa_col:
            return irb_rwa

        floored = irb_rwa.join(
            sa_equivalent_rwa.select(
                [
                    pl.col("exposure_reference"),
                    pl.col(sa_rwa_col).alias("sa_rwa"),
                ]
            ),
            on="exposure_reference",
            how="left",
        )

        irb_cols = set(floored.collect_schema().names())
        irb_rwa_col = "rwa" if "rwa" in irb_cols else "rwa_post_factor"

        return floored.with_columns(
            [
                (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
                pl.lit(floor_pct).alias("output_floor_pct"),
            ]
        ).with_columns(
            [
                (pl.col("floor_rwa") > pl.col(irb_rwa_col)).alias("is_floor_binding"),
                pl.max_horizontal(
                    pl.lit(0.0),
                    pl.col("floor_rwa") - pl.col(irb_rwa_col),
                ).alias("floor_impact_rwa"),
                pl.max_horizontal(
                    pl.col(irb_rwa_col),
                    pl.col("floor_rwa"),
                ).alias("rwa_final"),
            ]
        )


# =============================================================================
# Factory Function
# =============================================================================


def create_output_aggregator() -> OutputAggregator:
    """
    Create an OutputAggregator instance.

    Returns:
        OutputAggregator ready for use
    """
    return OutputAggregator()
