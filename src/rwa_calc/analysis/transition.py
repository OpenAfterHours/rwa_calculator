"""
Transitional output-floor schedule modelling (M3.3).

Runs a portfolio through the pipeline at successive transitional reporting dates,
collecting per-year output-floor impact metrics into a timeline. During the Basel
3.1 phase-in (PRA PS1/26 Art. 92(5): 60% in 2027 -> 72.5% in 2030+), a portfolio
that is not floor-constrained early may become so as the percentage rises, so the
year-by-year trajectory matters for forward-looking capital planning.

Pipeline position:
    PipelineOrchestrator (one run per reporting date) -> TransitionalScheduleBundle

References:
- PRA PS1/26 Art. 92(5), Art. 92(2A): output-floor transitional schedule.
- CRR Art. 92: own funds requirements.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import TransitionalScheduleBundle
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

logger = logging.getLogger(__name__)

# PRA PS1/26 transitional dates: 1 January of each year
_TRANSITIONAL_REPORTING_DATES = [
    date(2027, 1, 1),  # Year 1: 60% from 1 January (PRA PS1/26 Art. 92(5))
    date(2028, 1, 1),  # Year 2: 65% from 1 January
    date(2029, 1, 1),  # Year 3: 70% from 1 January
    date(2030, 1, 1),  # Year 4: 72.5% from 1 January (steady-state, Art. 92(2A))
]


class TransitionalScheduleRunner:
    """
    Model the output floor phase-in across 2027-2030.

    Runs the same portfolio through the Basel 3.1 pipeline for each
    transitional year, collecting floor impact metrics to produce a
    year-by-year timeline. This enables capital planning for the
    increasing floor bite.

    Why: PRA PS1/26 Art. 92(5) phases in the output floor (60% in 2027
    to 72.5% in 2030+). A portfolio that is not floor-constrained in 2027
    may become floor-constrained as the percentage rises. Modelling this
    trajectory is essential for forward-looking capital management.

    Usage:
        from rwa_calc.analysis.transition import TransitionalScheduleRunner

        runner = TransitionalScheduleRunner()
        schedule = runner.run(raw_data, permission_mode)
        timeline_df = schedule.timeline.collect()
    """

    def run(
        self,
        data: RawDataBundle,
        permission_mode: PermissionMode = PermissionMode.IRB,
        reporting_dates: list[date] | None = None,
    ) -> TransitionalScheduleBundle:
        """
        Run the B31 pipeline for each transitional year and produce timeline.

        Args:
            data: Pre-loaded raw data bundle (shared across all years)
            permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
            reporting_dates: Optional custom reporting dates (default: 2027-2030, 1 Jan)

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
                permission_mode=permission_mode,
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
            approach_df: pl.DataFrame = result.summary_by_approach.collect()
            if "total_rwa" in approach_df.columns:
                metrics["total_rwa_post_floor"] = approach_df["total_rwa"].sum()
            if "total_ead" in approach_df.columns:
                metrics["total_ead"] = approach_df["total_ead"].sum()
        except Exception:
            logger.warning("Failed to collect summary_by_approach for year %d", year)

    # Get floor-specific metrics from floor_impact
    if result.floor_impact is not None:
        try:
            floor_df: pl.DataFrame = result.floor_impact.collect()
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
