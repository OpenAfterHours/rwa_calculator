"""
Dual-Framework Comparison, Capital Impact Analysis, and Transitional Schedule Runners.

Pipeline position:
    Wraps PipelineOrchestrator -> produces ComparisonBundle / CapitalImpactBundle /
    TransitionalScheduleBundle

Key responsibilities:
- Run the same portfolio through both CRR and Basel 3.1 pipelines (M3.1)
- Join per-exposure results on exposure_reference to compute deltas
- Generate summary views by exposure class and approach
- Decompose RWA deltas into attributable regulatory drivers (M3.2)
- Model the transitional output floor schedule across 2027-2032 (M3.3)
- Accumulate errors from all pipeline runs

Why: During the Basel 3.1 transition (PRA PS9/24, effective 1 Jan 2027),
firms must quantify the capital impact of moving from CRR to Basel 3.1.
The output floor phases in from 50% (2027) to 72.5% (2032+), so firms need
year-by-year modelling to plan for the increasing floor bite.

References:
- PRA PS9/24 Ch.12: Output floor transitional period
- CRR Art. 92: Own funds requirements (capital ratios)
- CRR Art. 501/501a: SME and infrastructure supporting factors

Usage:
    from rwa_calc.engine.comparison import (
        CapitalImpactAnalyzer, DualFrameworkRunner, TransitionalScheduleRunner,
    )

    # M3.1: Side-by-side comparison
    runner = DualFrameworkRunner()
    comparison = runner.compare(raw_data, crr_config, b31_config)

    # M3.2: Capital impact analysis
    analyzer = CapitalImpactAnalyzer()
    impact = analyzer.analyze(comparison)

    # M3.3: Transitional floor schedule modelling
    schedule_runner = TransitionalScheduleRunner()
    schedule = schedule_runner.run(raw_data, irb_permissions)
    timeline_df = schedule.timeline.collect()
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    CapitalImpactBundle,
    ComparisonBundle,
    TransitionalScheduleBundle,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

logger = logging.getLogger(__name__)

# Columns to select from each framework's results for the comparison join
_COMPARISON_COLUMNS = [
    "exposure_reference",
    "exposure_class",
    "approach_applied",
    "ead_final",
    "risk_weight",
    "rwa_final",
]

# Optional columns to include if available
_OPTIONAL_COLUMNS = [
    "el_shortfall",
    "el_excess",
    "expected_loss",
    "sa_rwa",
    "supporting_factor",
]


class DualFrameworkRunner:
    """
    Run the same portfolio through CRR and Basel 3.1 pipelines and compare.

    Uses two separate PipelineOrchestrator instances (one per framework)
    to avoid CRM processor caching issues — each orchestrator initializes
    its own CRMProcessor with the correct is_basel_3_1 flag.

    The comparison join is on exposure_reference, producing per-exposure
    delta columns: delta_rwa, delta_risk_weight, delta_ead, delta_pct.
    """

    def compare(
        self,
        data: RawDataBundle,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> ComparisonBundle:
        """
        Run both frameworks on the same data and produce comparison.

        Args:
            data: Pre-loaded raw data bundle (shared between frameworks)
            crr_config: CRR configuration (must have framework=CRR)
            b31_config: Basel 3.1 configuration (must have framework=BASEL_3_1)

        Returns:
            ComparisonBundle with per-exposure deltas and summaries

        Raises:
            ValueError: If configs have wrong framework types
        """
        _validate_configs(crr_config, b31_config)

        logger.info("Running CRR pipeline...")
        crr_pipeline = PipelineOrchestrator()
        crr_results = crr_pipeline.run_with_data(data, crr_config)

        logger.info("Running Basel 3.1 pipeline...")
        b31_pipeline = PipelineOrchestrator()
        b31_results = b31_pipeline.run_with_data(data, b31_config)

        logger.info("Computing exposure-level deltas...")
        exposure_deltas = _compute_exposure_deltas(crr_results, b31_results)

        logger.info("Generating summary by exposure class...")
        summary_by_class = _compute_summary_by_class(exposure_deltas)

        logger.info("Generating summary by approach...")
        summary_by_approach = _compute_summary_by_approach(exposure_deltas)

        errors = list(crr_results.errors) + list(b31_results.errors)

        return ComparisonBundle(
            crr_results=crr_results,
            b31_results=b31_results,
            exposure_deltas=exposure_deltas,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            errors=errors,
        )


# =============================================================================
# Capital Impact Analysis (M3.2)
# =============================================================================

# IRB approach values used by the aggregator — "foundation_irb" and "advanced_irb"
# from ApproachType enum, plus "FIRB" from aggregator fallback
_IRB_APPROACHES = ["foundation_irb", "advanced_irb", "FIRB"]

# CRR scaling factor for IRB RWA (CRR Art. 153(1))
_CRR_SCALING_FACTOR = 1.06

# Attribution driver labels for the portfolio waterfall
_DRIVER_SCALING = "Scaling factor removal (1.06x)"
_DRIVER_SUPPORTING = "Supporting factor removal (SME/infrastructure)"
_DRIVER_FLOOR = "Output floor impact"
_DRIVER_METHODOLOGY = "Methodology & parameter changes"


class CapitalImpactAnalyzer:
    """
    Decompose the CRR vs Basel 3.1 RWA delta into regulatory drivers (M3.2).

    Takes a pre-computed ComparisonBundle (from DualFrameworkRunner) and produces
    a CapitalImpactBundle with per-exposure driver attribution and portfolio-level
    waterfall.

    Waterfall methodology (sequential, additive):
      CRR RWA
        → Remove 1.06x scaling factor (IRB only)
        → Remove supporting factors (SME/infrastructure)
        → Apply B31 methodology changes (PD/LGD floors, SA risk weights)
        → Apply output floor (IRB only)
      = B31 RWA

    The sum of all four drivers equals the total delta_rwa per exposure.

    Why: Stakeholders need to understand WHY capital requirements change,
    not just by how much. Attribution enables targeted capital planning,
    business-line communication, and regulatory dialogue about which
    Basel 3.1 changes drive the most impact for a given portfolio.

    Usage:
        comparison = DualFrameworkRunner().compare(data, crr_cfg, b31_cfg)
        impact = CapitalImpactAnalyzer().analyze(comparison)
        waterfall_df = impact.portfolio_waterfall.collect()
    """

    def analyze(self, comparison: ComparisonBundle) -> CapitalImpactBundle:
        """
        Decompose comparison deltas into driver-level attribution.

        Args:
            comparison: Pre-computed dual-framework comparison bundle

        Returns:
            CapitalImpactBundle with per-exposure and portfolio attribution
        """
        logger.info("Computing capital impact attribution (M3.2)...")

        attribution = _compute_exposure_attribution(comparison)
        waterfall = _compute_portfolio_waterfall(attribution)
        summary_by_class = _compute_attribution_summary(attribution, "exposure_class")
        summary_by_approach = _compute_attribution_summary(attribution, "approach_applied")

        return CapitalImpactBundle(
            exposure_attribution=attribution,
            portfolio_waterfall=waterfall,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            errors=list(comparison.errors),
        )


# =============================================================================
# Transitional Floor Schedule (M3.3)
# =============================================================================

# PRA PS9/24 transitional dates: 1 Jan of each year, with mid-year reporting
_TRANSITIONAL_REPORTING_DATES = [
    date(2027, 6, 30),  # Year 1: 50%
    date(2028, 6, 30),  # Year 2: 55%
    date(2029, 6, 30),  # Year 3: 60%
    date(2030, 6, 30),  # Year 4: 65%
    date(2031, 6, 30),  # Year 5: 70%
    date(2032, 6, 30),  # Year 6: 72.5% (fully phased)
]


class TransitionalScheduleRunner:
    """
    Model the output floor phase-in across 2027-2032.

    Runs the same portfolio through the Basel 3.1 pipeline for each
    transitional year, collecting floor impact metrics to produce a
    year-by-year timeline. This enables capital planning for the
    increasing floor bite.

    Why: PRA PS9/24 phases in the output floor gradually (50% in 2027
    to 72.5% in 2032+). A portfolio that is not floor-constrained in 2027
    may become floor-constrained as the percentage rises. Modelling this
    trajectory is essential for forward-looking capital management.

    Usage:
        from rwa_calc.engine.comparison import TransitionalScheduleRunner

        runner = TransitionalScheduleRunner()
        schedule = runner.run(raw_data, irb_permissions)
        timeline_df = schedule.timeline.collect()
    """

    def run(
        self,
        data: RawDataBundle,
        irb_permissions: IRBPermissions,
        reporting_dates: list[date] | None = None,
    ) -> TransitionalScheduleBundle:
        """
        Run the B31 pipeline for each transitional year and produce timeline.

        Args:
            data: Pre-loaded raw data bundle (shared across all years)
            irb_permissions: IRB approach permissions for the firm
            reporting_dates: Optional custom reporting dates (default: 2027-2032 mid-year)

        Returns:
            TransitionalScheduleBundle with year-by-year floor impact timeline
        """
        from rwa_calc.contracts.config import CalculationConfig

        dates = reporting_dates or _TRANSITIONAL_REPORTING_DATES
        yearly_results: dict[int, AggregatedResultBundle] = {}
        timeline_rows: list[dict] = []
        all_errors: list = []

        for reporting_date in dates:
            year = reporting_date.year
            logger.info(
                "Running transitional schedule for %d (floor date %s)...", year, reporting_date
            )

            config = CalculationConfig.basel_3_1(
                reporting_date=reporting_date,
                irb_permissions=irb_permissions,
            )

            pipeline = PipelineOrchestrator()
            result = pipeline.run_with_data(data, config)
            yearly_results[year] = result
            all_errors.extend(result.errors)

            floor_pct = float(config.get_output_floor_percentage())
            row = _extract_floor_metrics(result, reporting_date, floor_pct)
            timeline_rows.append(row)

        timeline = _build_timeline_lazyframe(timeline_rows)

        return TransitionalScheduleBundle(
            timeline=timeline,
            yearly_results=yearly_results,
            errors=all_errors,
        )


def _extract_floor_metrics(
    result: AggregatedResultBundle,
    reporting_date: date,
    floor_pct: float,
) -> dict:
    """Extract floor impact summary metrics from a single pipeline run.

    Collects the floor_impact LazyFrame (if present) and computes
    aggregate metrics for the timeline row.
    """
    year = reporting_date.year
    metrics: dict = {
        "reporting_date": reporting_date,
        "year": year,
        "floor_percentage": floor_pct,
        "total_rwa_pre_floor": 0.0,
        "total_rwa_post_floor": 0.0,
        "total_floor_impact": 0.0,
        "floor_binding_count": 0,
        "total_irb_exposure_count": 0,
        "total_ead": 0.0,
        "total_sa_rwa": 0.0,
    }

    # Get total RWA from summary_by_approach (covers all approaches)
    if result.summary_by_approach is not None:
        try:
            approach_df = result.summary_by_approach.collect()
            if "total_rwa" in approach_df.columns:
                metrics["total_rwa_post_floor"] = approach_df["total_rwa"].sum()
            if "total_ead" in approach_df.columns:
                metrics["total_ead"] = approach_df["total_ead"].sum()
        except Exception:
            logger.warning("Failed to collect summary_by_approach for year %d", year)

    # Get floor-specific metrics from floor_impact
    if result.floor_impact is not None:
        try:
            floor_df = result.floor_impact.collect()
            if floor_df.height > 0:
                metrics["total_irb_exposure_count"] = floor_df.height
                if "rwa_pre_floor" in floor_df.columns:
                    metrics["total_rwa_pre_floor"] = floor_df["rwa_pre_floor"].sum()
                if "floor_impact_rwa" in floor_df.columns:
                    metrics["total_floor_impact"] = floor_df["floor_impact_rwa"].sum()
                if "is_floor_binding" in floor_df.columns:
                    metrics["floor_binding_count"] = int(floor_df["is_floor_binding"].sum())
                if "floor_rwa" in floor_df.columns:
                    metrics["total_sa_rwa"] = floor_df["floor_rwa"].sum() / max(floor_pct, 1e-10)
        except Exception:
            logger.warning("Failed to collect floor_impact for year %d", year)

    return metrics


def _build_timeline_lazyframe(rows: list[dict]) -> pl.LazyFrame:
    """Build the timeline LazyFrame from collected metric rows."""
    if not rows:
        return pl.LazyFrame(
            {
                "reporting_date": pl.Series([], dtype=pl.Date),
                "year": pl.Series([], dtype=pl.Int32),
                "floor_percentage": pl.Series([], dtype=pl.Float64),
                "total_rwa_pre_floor": pl.Series([], dtype=pl.Float64),
                "total_rwa_post_floor": pl.Series([], dtype=pl.Float64),
                "total_floor_impact": pl.Series([], dtype=pl.Float64),
                "floor_binding_count": pl.Series([], dtype=pl.UInt32),
                "total_irb_exposure_count": pl.Series([], dtype=pl.UInt32),
                "total_ead": pl.Series([], dtype=pl.Float64),
                "total_sa_rwa": pl.Series([], dtype=pl.Float64),
            }
        )

    return pl.DataFrame(
        {
            "reporting_date": [r["reporting_date"] for r in rows],
            "year": [r["year"] for r in rows],
            "floor_percentage": [r["floor_percentage"] for r in rows],
            "total_rwa_pre_floor": [r["total_rwa_pre_floor"] for r in rows],
            "total_rwa_post_floor": [r["total_rwa_post_floor"] for r in rows],
            "total_floor_impact": [r["total_floor_impact"] for r in rows],
            "floor_binding_count": [r["floor_binding_count"] for r in rows],
            "total_irb_exposure_count": [r["total_irb_exposure_count"] for r in rows],
            "total_ead": [r["total_ead"] for r in rows],
            "total_sa_rwa": [r["total_sa_rwa"] for r in rows],
        },
        schema={
            "reporting_date": pl.Date,
            "year": pl.Int32,
            "floor_percentage": pl.Float64,
            "total_rwa_pre_floor": pl.Float64,
            "total_rwa_post_floor": pl.Float64,
            "total_floor_impact": pl.Float64,
            "floor_binding_count": pl.UInt32,
            "total_irb_exposure_count": pl.UInt32,
            "total_ead": pl.Float64,
            "total_sa_rwa": pl.Float64,
        },
    ).lazy()


# =============================================================================
# Private Helpers — Dual-Framework Comparison
# =============================================================================


def _validate_configs(crr_config: CalculationConfig, b31_config: CalculationConfig) -> None:
    """Validate that configs have correct framework types."""
    if not crr_config.is_crr:
        raise ValueError(f"crr_config must use CRR framework, got {crr_config.framework}")
    if not b31_config.is_basel_3_1:
        raise ValueError(f"b31_config must use Basel 3.1 framework, got {b31_config.framework}")


def _select_result_columns(results: AggregatedResultBundle, suffix: str) -> pl.LazyFrame:
    """Select and rename columns from a framework's results for comparison join.

    Picks the core columns needed for delta computation and renames them
    with a framework suffix (e.g., rwa_final -> rwa_crr or rwa_b31).
    """
    lf = results.results
    schema = lf.collect_schema()

    # Always select exposure_reference as the join key (no suffix)
    select_exprs: list[pl.Expr] = [pl.col("exposure_reference")]

    # exposure_class and approach_applied are shared context (no suffix)
    for col_name in ("exposure_class", "approach_applied"):
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    # Core numeric columns get framework suffix
    for col_name in ("ead_final", "risk_weight", "rwa_final"):
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    # Optional columns if they exist
    for col_name in _OPTIONAL_COLUMNS:
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    return lf.select(select_exprs)


def _compute_exposure_deltas(
    crr_results: AggregatedResultBundle,
    b31_results: AggregatedResultBundle,
) -> pl.LazyFrame:
    """Join CRR and B31 results on exposure_reference and compute deltas.

    Delta convention: positive delta means B31 is higher than CRR (increased capital).
    delta_pct is the percentage change relative to CRR (delta_rwa / crr_rwa * 100).
    """
    crr_lf = _select_result_columns(crr_results, "crr")
    b31_lf = _select_result_columns(b31_results, "b31")

    joined = crr_lf.join(b31_lf, on="exposure_reference", how="full", coalesce=True)

    # Use CRR exposure class/approach as the primary context; fall back to B31
    joined = joined.with_columns(
        [
            pl.coalesce(pl.col("exposure_class_crr"), pl.col("exposure_class_b31")).alias(
                "exposure_class"
            ),
            pl.coalesce(pl.col("approach_applied_crr"), pl.col("approach_applied_b31")).alias(
                "approach_applied"
            ),
        ]
    )

    # Compute deltas: B31 - CRR (positive = increased capital requirement)
    joined = joined.with_columns(
        [
            (pl.col("rwa_final_b31").fill_null(0.0) - pl.col("rwa_final_crr").fill_null(0.0)).alias(
                "delta_rwa"
            ),
            (
                pl.col("risk_weight_b31").fill_null(0.0) - pl.col("risk_weight_crr").fill_null(0.0)
            ).alias("delta_risk_weight"),
            (pl.col("ead_final_b31").fill_null(0.0) - pl.col("ead_final_crr").fill_null(0.0)).alias(
                "delta_ead"
            ),
        ]
    )

    # Percentage change relative to CRR
    joined = joined.with_columns(
        pl.when(pl.col("rwa_final_crr").abs() > 1e-10)
        .then(pl.col("delta_rwa") / pl.col("rwa_final_crr") * 100.0)
        .otherwise(
            pl.when(pl.col("rwa_final_b31").abs() > 1e-10)
            .then(pl.lit(float("inf")))
            .otherwise(pl.lit(0.0))
        )
        .alias("delta_rwa_pct")
    )

    return joined


def _compute_summary_by_class(exposure_deltas: pl.LazyFrame) -> pl.LazyFrame:
    """Aggregate delta RWA by exposure class."""
    return (
        exposure_deltas.group_by("exposure_class")
        .agg(
            [
                pl.col("rwa_final_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_final_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("ead_final_crr").sum().alias("total_ead_crr"),
                pl.col("ead_final_b31").sum().alias("total_ead_b31"),
                pl.len().alias("exposure_count"),
            ]
        )
        .with_columns(
            pl.when(pl.col("total_rwa_crr").abs() > 1e-10)
            .then(pl.col("total_delta_rwa") / pl.col("total_rwa_crr") * 100.0)
            .otherwise(pl.lit(0.0))
            .alias("delta_rwa_pct")
        )
        .sort("exposure_class")
    )


def _compute_summary_by_approach(exposure_deltas: pl.LazyFrame) -> pl.LazyFrame:
    """Aggregate delta RWA by calculation approach."""
    return (
        exposure_deltas.group_by("approach_applied")
        .agg(
            [
                pl.col("rwa_final_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_final_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("ead_final_crr").sum().alias("total_ead_crr"),
                pl.col("ead_final_b31").sum().alias("total_ead_b31"),
                pl.len().alias("exposure_count"),
            ]
        )
        .with_columns(
            pl.when(pl.col("total_rwa_crr").abs() > 1e-10)
            .then(pl.col("total_delta_rwa") / pl.col("total_rwa_crr") * 100.0)
            .otherwise(pl.lit(0.0))
            .alias("delta_rwa_pct")
        )
        .sort("approach_applied")
    )


# =============================================================================
# Private Helpers — Capital Impact Analysis (M3.2)
# =============================================================================

# Attribution driver column names
_ATTRIBUTION_DRIVERS = [
    "scaling_factor_impact",
    "supporting_factor_impact",
    "output_floor_impact",
    "methodology_impact",
]


def _safe_col(schema: pl.Schema, col_name: str, default: float = 0.0) -> pl.Expr:
    """Return col expression if present, otherwise a literal default."""
    if col_name in schema.names():
        return pl.col(col_name).fill_null(default)
    return pl.lit(default).alias(col_name)


def _compute_exposure_attribution(comparison: ComparisonBundle) -> pl.LazyFrame:
    """Compute per-exposure driver attribution from CRR and B31 results.

    Joins CRR and B31 aggregated results on exposure_reference, then
    computes the waterfall attribution for each exposure:

    1. scaling_factor_impact: CRR_rwa_final × (1/1.06 - 1) for IRB, else 0
    2. supporting_factor_impact: decomposed from rwa_pre_factor vs rwa_final
    3. output_floor_impact: from B31 floor_impact data
    4. methodology_impact: residual (delta - scaling - supporting - floor)

    The four drivers sum to delta_rwa for every exposure.
    """
    crr = comparison.crr_results
    b31 = comparison.b31_results

    # Select columns from CRR results
    crr_schema = crr.results.collect_schema()
    # For rwa_pre_factor: if missing, use rwa_final (no supporting factor applied)
    rwa_pre_factor_expr: pl.Expr
    if "rwa_pre_factor" in crr_schema.names():
        rwa_pre_factor_expr = pl.col("rwa_pre_factor").fill_null(pl.col("rwa_final"))
    else:
        rwa_pre_factor_expr = pl.col("rwa_final")

    crr_cols = [
        pl.col("exposure_reference"),
        pl.col("exposure_class")
        if "exposure_class" in crr_schema.names()
        else pl.lit(None).cast(pl.String).alias("exposure_class"),
        pl.col("approach_applied")
        if "approach_applied" in crr_schema.names()
        else pl.lit(None).cast(pl.String).alias("approach_applied"),
        _safe_col(crr_schema, "rwa_final").alias("rwa_crr"),
        rwa_pre_factor_expr.alias("rwa_pre_factor_crr"),
        _safe_col(crr_schema, "supporting_factor", 1.0).alias("supporting_factor_crr"),
    ]
    crr_lf = crr.results.select(crr_cols)

    # Select columns from B31 results
    b31_schema = b31.results.collect_schema()
    b31_cols = [
        pl.col("exposure_reference"),
        _safe_col(b31_schema, "rwa_final").alias("rwa_b31"),
        _safe_col(b31_schema, "rwa_pre_floor").alias("rwa_pre_floor_b31"),
    ]
    b31_lf = b31.results.select(b31_cols)

    # Join CRR and B31 on exposure_reference (full outer join)
    joined = crr_lf.join(b31_lf, on="exposure_reference", how="full", coalesce=True)

    # Left join B31 floor_impact for floor_impact_rwa
    if b31.floor_impact is not None:
        floor_schema = b31.floor_impact.collect_schema()
        if "floor_impact_rwa" in floor_schema.names():
            floor_lf = b31.floor_impact.select(
                [
                    pl.col("exposure_reference"),
                    pl.col("floor_impact_rwa").alias("b31_floor_impact_rwa"),
                ]
            )
            joined = joined.join(floor_lf, on="exposure_reference", how="left")

    # Fill nulls for robustness (exposures missing from one framework)
    joined = joined.with_columns(
        [
            pl.col("rwa_crr").fill_null(0.0),
            pl.col("rwa_b31").fill_null(0.0),
            pl.col("supporting_factor_crr").fill_null(1.0),
            pl.col("rwa_pre_floor_b31").fill_null(pl.col("rwa_b31")),
        ]
    )
    # rwa_pre_factor_crr: fill null with rwa_crr (means no supporting factor)
    joined = joined.with_columns(
        pl.col("rwa_pre_factor_crr").fill_null(pl.col("rwa_crr")),
    )

    # Ensure b31_floor_impact_rwa column exists
    joined_schema = joined.collect_schema()
    if "b31_floor_impact_rwa" not in joined_schema.names():
        joined = joined.with_columns(pl.lit(0.0).alias("b31_floor_impact_rwa"))
    else:
        joined = joined.with_columns(pl.col("b31_floor_impact_rwa").fill_null(0.0))

    # Compute delta
    joined = joined.with_columns(
        (pl.col("rwa_b31") - pl.col("rwa_crr")).alias("delta_rwa"),
    )

    is_irb = pl.col("approach_applied").is_in(_IRB_APPROACHES)

    # =========================================================================
    # Waterfall Step 1: Scaling factor removal (IRB only)
    #
    # CRR applies 1.06x to IRB K. Removing it reduces RWA.
    # Impact = CRR_rwa_final × (1/1.06 - 1)
    # =========================================================================
    joined = joined.with_columns(
        pl.when(is_irb)
        .then(pl.col("rwa_crr") * (1.0 / _CRR_SCALING_FACTOR - 1.0))
        .otherwise(0.0)
        .alias("scaling_factor_impact"),
    )

    # =========================================================================
    # Waterfall Step 2: Supporting factor removal
    #
    # For IRB: post-scaling intermediate = CRR_rwa_final / 1.06
    # Supporting factor added (CRR_rpf - CRR_rf) / 1.06 back.
    # For SA: no scaling, so impact = CRR_rpf - CRR_rf directly.
    # =========================================================================
    joined = joined.with_columns(
        pl.when(is_irb)
        .then((pl.col("rwa_pre_factor_crr") - pl.col("rwa_crr")) / _CRR_SCALING_FACTOR)
        .otherwise(pl.col("rwa_pre_factor_crr") - pl.col("rwa_crr"))
        .alias("supporting_factor_impact"),
    )

    # =========================================================================
    # Waterfall Step 3: Output floor impact (IRB only)
    #
    # Additional RWA from B31 output floor binding.
    # = floor_impact_rwa from the aggregator.
    # =========================================================================
    joined = joined.with_columns(
        pl.when(is_irb)
        .then(pl.col("b31_floor_impact_rwa"))
        .otherwise(0.0)
        .alias("output_floor_impact"),
    )

    # =========================================================================
    # Waterfall Step 4: Methodology & parameter changes (residual)
    #
    # Everything else: PD/LGD floor changes, SA risk weight table changes,
    # F-IRB supervisory LGD changes, correlation formula changes, etc.
    # Computed as: delta - scaling - supporting - floor
    # This ensures the waterfall is exactly additive.
    # =========================================================================
    joined = joined.with_columns(
        (
            pl.col("delta_rwa")
            - pl.col("scaling_factor_impact")
            - pl.col("supporting_factor_impact")
            - pl.col("output_floor_impact")
        ).alias("methodology_impact"),
    )

    # Select final output columns
    return joined.select(
        [
            "exposure_reference",
            "exposure_class",
            "approach_applied",
            "rwa_crr",
            "rwa_b31",
            "delta_rwa",
            "scaling_factor_impact",
            "supporting_factor_impact",
            "output_floor_impact",
            "methodology_impact",
        ]
    )


def _compute_portfolio_waterfall(attribution: pl.LazyFrame) -> pl.LazyFrame:
    """Build a portfolio-level waterfall from per-exposure attribution.

    Produces a 4-row LazyFrame with one row per driver, showing the
    aggregate impact and cumulative RWA from CRR baseline to B31 total.
    """
    # Aggregate each driver across the whole portfolio
    totals = attribution.select(
        [
            pl.col("rwa_crr").sum().alias("total_rwa_crr"),
            pl.col("scaling_factor_impact").sum().alias("total_scaling"),
            pl.col("supporting_factor_impact").sum().alias("total_supporting"),
            pl.col("output_floor_impact").sum().alias("total_floor"),
            pl.col("methodology_impact").sum().alias("total_methodology"),
            pl.col("rwa_b31").sum().alias("total_rwa_b31"),
        ]
    ).collect()

    crr_rwa = totals["total_rwa_crr"][0]
    scaling = totals["total_scaling"][0]
    supporting = totals["total_supporting"][0]
    methodology = totals["total_methodology"][0]
    floor = totals["total_floor"][0]

    # Build waterfall rows in order
    steps = [
        (1, _DRIVER_SCALING, scaling, crr_rwa + scaling),
        (2, _DRIVER_SUPPORTING, supporting, crr_rwa + scaling + supporting),
        (3, _DRIVER_METHODOLOGY, methodology, crr_rwa + scaling + supporting + methodology),
        (4, _DRIVER_FLOOR, floor, crr_rwa + scaling + supporting + methodology + floor),
    ]

    return pl.DataFrame(
        {
            "step": [s[0] for s in steps],
            "driver": [s[1] for s in steps],
            "impact_rwa": [s[2] for s in steps],
            "cumulative_rwa": [s[3] for s in steps],
        },
        schema={
            "step": pl.Int32,
            "driver": pl.String,
            "impact_rwa": pl.Float64,
            "cumulative_rwa": pl.Float64,
        },
    ).lazy()


def _compute_attribution_summary(
    attribution: pl.LazyFrame,
    group_col: str,
) -> pl.LazyFrame:
    """Aggregate driver attribution by a grouping column (class or approach)."""
    return (
        attribution.group_by(group_col)
        .agg(
            [
                pl.col("rwa_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("scaling_factor_impact").sum().alias("total_scaling_factor_impact"),
                pl.col("supporting_factor_impact").sum().alias("total_supporting_factor_impact"),
                pl.col("output_floor_impact").sum().alias("total_output_floor_impact"),
                pl.col("methodology_impact").sum().alias("total_methodology_impact"),
                pl.len().alias("exposure_count"),
            ]
        )
        .sort(group_col)
    )
