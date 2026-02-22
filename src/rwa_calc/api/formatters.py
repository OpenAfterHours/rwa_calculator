"""
Result formatting utilities for RWA Calculator API.

ResultFormatter: Formats AggregatedResultBundle for API responses
compute_summary: Calculates SummaryStatistics from results

Handles LazyFrame materialization and summary computation for UI consumption.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.api.errors import convert_errors
from rwa_calc.api.models import (
    APIError,
    CalculationResponse,
    PerformanceMetrics,
    SummaryStatistics,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle


# =============================================================================
# Result Formatter
# =============================================================================


class ResultFormatter:
    """
    Formats pipeline results for API responses.

    Handles:
    - LazyFrame materialization to DataFrames
    - Summary statistics computation
    - Error conversion to API format
    - Performance metrics calculation

    Usage:
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )
    """

    def format_response(
        self,
        bundle: AggregatedResultBundle,
        framework: str,
        reporting_date: date,
        started_at: datetime,
    ) -> CalculationResponse:
        """
        Format AggregatedResultBundle into CalculationResponse.

        Materializes LazyFrames and computes summary statistics.

        Args:
            bundle: Result bundle from pipeline
            framework: Framework used for calculation
            reporting_date: As-of date
            started_at: Calculation start time

        Returns:
            CalculationResponse ready for API return
        """
        completed_at = datetime.now()

        # Batch-collect results + summary frames in one pl.collect_all() call.
        # This lets Polars deduplicate any shared subplans across all frames.
        results_df, summary_by_class, summary_by_approach = (
            self._batch_materialize_all(
                bundle.results,
                bundle.summary_by_class,
                bundle.summary_by_approach,
            )
        )

        summary = self._compute_summary(
            results_df=results_df,
            floor_impact=bundle.floor_impact,
        )

        errors = convert_errors(bundle.errors) if bundle.errors else []

        has_critical = any(e.severity == "critical" for e in errors)
        success = not has_critical and results_df.height > 0

        performance = PerformanceMetrics(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            exposure_count=results_df.height,
        )

        return CalculationResponse(
            success=success,
            framework=framework,
            reporting_date=reporting_date,
            summary=summary,
            results=results_df,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            errors=errors,
            performance=performance,
        )

    def format_error_response(
        self,
        errors: list[APIError],
        framework: str,
        reporting_date: date,
        started_at: datetime,
    ) -> CalculationResponse:
        """
        Format an error response when calculation fails.

        Args:
            errors: List of errors that caused failure
            framework: Framework that was requested
            reporting_date: As-of date
            started_at: Calculation start time

        Returns:
            CalculationResponse indicating failure
        """
        completed_at = datetime.now()

        empty_summary = SummaryStatistics(
            total_ead=Decimal("0"),
            total_rwa=Decimal("0"),
            exposure_count=0,
            average_risk_weight=Decimal("0"),
        )

        empty_results = pl.DataFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "approach_applied": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "risk_weight": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        })

        performance = PerformanceMetrics(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            exposure_count=0,
        )

        return CalculationResponse(
            success=False,
            framework=framework,
            reporting_date=reporting_date,
            summary=empty_summary,
            results=empty_results,
            errors=errors,
            performance=performance,
        )

    def _batch_materialize_all(
        self,
        results: pl.LazyFrame,
        summary_by_class: pl.LazyFrame | None,
        summary_by_approach: pl.LazyFrame | None,
    ) -> tuple[pl.DataFrame, pl.DataFrame | None, pl.DataFrame | None]:
        """
        Batch-collect results + summary LazyFrames using pl.collect_all().

        Collecting everything in one call lets Polars deduplicate any
        shared subplans for a single pass through the data.

        Args:
            results: Main results LazyFrame (required)
            summary_by_class: Optional summary-by-class LazyFrame
            summary_by_approach: Optional summary-by-approach LazyFrame

        Returns:
            Tuple of (results DataFrame, class summary, approach summary)
        """
        frames_to_collect: list[pl.LazyFrame] = [results]
        indices: dict[str, int] = {"results": 0}

        if summary_by_class is not None:
            indices["class"] = len(frames_to_collect)
            frames_to_collect.append(summary_by_class)

        if summary_by_approach is not None:
            indices["approach"] = len(frames_to_collect)
            frames_to_collect.append(summary_by_approach)

        try:
            collected = pl.collect_all(frames_to_collect)
        except Exception:
            empty_results = pl.DataFrame({
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            })
            return empty_results, None, None

        results_df = collected[indices["results"]]
        class_df = collected[indices["class"]] if "class" in indices else None
        approach_df = collected[indices["approach"]] if "approach" in indices else None

        return results_df, class_df, approach_df

    def _compute_summary(
        self,
        results_df: pl.DataFrame,
        floor_impact: pl.LazyFrame | None,
    ) -> SummaryStatistics:
        """
        Compute summary statistics from the already-materialized results DataFrame.

        Filters results_df by approach_applied instead of re-collecting separate
        LazyFrames, eliminating 6 redundant pipeline executions.

        Args:
            results_df: Materialized results DataFrame
            floor_impact: Optional floor impact LazyFrame

        Returns:
            SummaryStatistics with computed metrics
        """
        if results_df.height == 0:
            return SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            )

        ead_col = self._find_column(results_df, ["ead_final", "ead", "exposure_at_default"])
        rwa_col = self._find_column(results_df, ["rwa_final", "rwa", "risk_weighted_assets"])

        total_ead = Decimal("0")
        total_rwa = Decimal("0")

        if ead_col:
            total_ead = Decimal(str(results_df[ead_col].sum() or 0))
        if rwa_col:
            total_rwa = Decimal(str(results_df[rwa_col].sum() or 0))

        avg_rw = total_rwa / total_ead if total_ead > 0 else Decimal("0")

        # Compute per-approach stats from already-materialized results_df
        approach_stats = self._compute_approach_stats(results_df, ead_col, rwa_col)

        floor_applied = False
        floor_impact_value = Decimal("0")
        if floor_impact is not None:
            try:
                floor_df = floor_impact.collect()
                if "floor_binding" in floor_df.columns:
                    floor_applied = floor_df["floor_binding"].any()
                if "floor_add_on" in floor_df.columns:
                    floor_impact_value = Decimal(str(floor_df["floor_add_on"].sum() or 0))
            except Exception:
                pass

        return SummaryStatistics(
            total_ead=total_ead,
            total_rwa=total_rwa,
            exposure_count=results_df.height,
            average_risk_weight=avg_rw,
            total_ead_sa=approach_stats["ead_sa"],
            total_ead_irb=approach_stats["ead_irb"],
            total_ead_slotting=approach_stats["ead_slotting"],
            total_rwa_sa=approach_stats["rwa_sa"],
            total_rwa_irb=approach_stats["rwa_irb"],
            total_rwa_slotting=approach_stats["rwa_slotting"],
            floor_applied=floor_applied,
            floor_impact=floor_impact_value,
        )

    def _compute_approach_stats(
        self,
        results_df: pl.DataFrame,
        ead_col: str | None,
        rwa_col: str | None,
    ) -> dict[str, Decimal]:
        """
        Compute per-approach EAD and RWA totals from the materialized results DataFrame.

        Filters on the approach_applied column instead of re-collecting separate LazyFrames.

        Args:
            results_df: Materialized results DataFrame
            ead_col: Name of EAD column (or None)
            rwa_col: Name of RWA column (or None)

        Returns:
            Dict with keys ead_sa, ead_irb, ead_slotting, rwa_sa, rwa_irb, rwa_slotting
        """
        stats: dict[str, Decimal] = {
            "ead_sa": Decimal("0"),
            "ead_irb": Decimal("0"),
            "ead_slotting": Decimal("0"),
            "rwa_sa": Decimal("0"),
            "rwa_irb": Decimal("0"),
            "rwa_slotting": Decimal("0"),
        }

        if "approach_applied" not in results_df.columns:
            return stats

        # SA approaches
        sa_approaches = {"SA", "standardised"}
        # IRB approaches: "foundation_irb"/"advanced_irb" from ApproachType enum,
        # "FIRB" from aggregator fallback when 'approach' column is missing
        irb_approaches = {"foundation_irb", "advanced_irb", "FIRB"}
        # Slotting approaches: "SLOTTING" from aggregator literal, "slotting" from ApproachType enum
        slotting_approaches = {"SLOTTING", "slotting"}

        approach_mapping = {
            "sa": sa_approaches,
            "irb": irb_approaches,
            "slotting": slotting_approaches,
        }

        for key, approaches in approach_mapping.items():
            filtered = results_df.filter(pl.col("approach_applied").is_in(approaches))
            if filtered.height > 0:
                if ead_col and ead_col in filtered.columns:
                    stats[f"ead_{key}"] = Decimal(str(filtered[ead_col].sum() or 0))
                if rwa_col and rwa_col in filtered.columns:
                    stats[f"rwa_{key}"] = Decimal(str(filtered[rwa_col].sum() or 0))

        return stats

    def _find_column(
        self,
        df: pl.DataFrame,
        candidates: list[str],
    ) -> str | None:
        """
        Find first matching column name from candidates.

        Args:
            df: DataFrame to search
            candidates: List of possible column names

        Returns:
            First matching column name or None
        """
        for col in candidates:
            if col in df.columns:
                return col
        return None


# =============================================================================
# Convenience Functions
# =============================================================================


def compute_summary(results_df: pl.DataFrame) -> SummaryStatistics:
    """
    Compute summary statistics from a results DataFrame.

    Convenience function for quick summary computation.

    Args:
        results_df: DataFrame with calculation results

    Returns:
        SummaryStatistics with computed metrics
    """
    formatter = ResultFormatter()
    return formatter._compute_summary(
        results_df=results_df,
        floor_impact=None,
    )


def materialize_bundle(bundle: AggregatedResultBundle) -> dict[str, pl.DataFrame]:
    """
    Materialize all LazyFrames in a bundle to DataFrames.

    Useful for debugging and inspection.

    Args:
        bundle: AggregatedResultBundle to materialize

    Returns:
        Dictionary of materialized DataFrames
    """
    result: dict[str, pl.DataFrame] = {}

    try:
        result["results"] = bundle.results.collect()
    except Exception:
        result["results"] = pl.DataFrame()

    for name, lazy in [
        ("sa_results", bundle.sa_results),
        ("irb_results", bundle.irb_results),
        ("slotting_results", bundle.slotting_results),
        ("floor_impact", bundle.floor_impact),
        ("summary_by_class", bundle.summary_by_class),
        ("summary_by_approach", bundle.summary_by_approach),
    ]:
        if lazy is not None:
            try:
                result[name] = lazy.collect()
            except Exception:
                result[name] = pl.DataFrame()

    return result
