"""
Dual-Framework Comparison and Transitional Schedule Runners for RWA Calculator.

Pipeline position:
    Wraps PipelineOrchestrator -> produces ComparisonBundle / TransitionalScheduleBundle

Key responsibilities:
- Run the same portfolio through both CRR and Basel 3.1 pipelines (M3.1)
- Join per-exposure results on exposure_reference to compute deltas
- Generate summary views by exposure class and approach
- Model the transitional output floor schedule across 2027-2032 (M3.3)
- Accumulate errors from all pipeline runs

Why: During the Basel 3.1 transition (PRA PS9/24, effective 1 Jan 2027),
firms must quantify the capital impact of moving from CRR to Basel 3.1.
The output floor phases in from 50% (2027) to 72.5% (2032+), so firms need
year-by-year modelling to plan for the increasing floor bite.

References:
- PRA PS9/24 Ch.12: Output floor transitional period
- CRR Art. 92: Own funds requirements (capital ratios)

Usage:
    from rwa_calc.engine.comparison import DualFrameworkRunner, TransitionalScheduleRunner

    # M3.1: Side-by-side comparison
    runner = DualFrameworkRunner()
    comparison = runner.compare(raw_data, crr_config, b31_config)

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

from rwa_calc.contracts.bundles import ComparisonBundle, TransitionalScheduleBundle
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
