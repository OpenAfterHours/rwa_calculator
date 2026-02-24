"""
Result formatting utilities for RWA Calculator API.

ResultFormatter: Formats AggregatedResultBundle for API responses

Sinks results to parquet via ResultsCache and computes lightweight
summary statistics — no full in-memory materialization of the results DataFrame.
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
from rwa_calc.api.results_cache import ResultsCache

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle


# =============================================================================
# Result Formatter
# =============================================================================


class ResultFormatter:
    """
    Formats pipeline results for API responses.

    Sinks results to parquet via ResultsCache for zero in-memory overhead,
    computes lightweight summary statistics via lazy aggregation, and
    converts errors to API format.

    Usage:
        cache = ResultsCache(Path(".cache"))
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )
    """

    def format_response(
        self,
        bundle: AggregatedResultBundle,
        cache: ResultsCache,
        framework: str,
        reporting_date: date,
        started_at: datetime,
    ) -> CalculationResponse:
        """
        Format AggregatedResultBundle into CalculationResponse.

        Sinks results to parquet and computes summary statistics lazily.

        Args:
            bundle: Result bundle from pipeline
            cache: ResultsCache for streaming results to parquet
            framework: Framework used for calculation
            reporting_date: As-of date
            started_at: Calculation start time

        Returns:
            CalculationResponse with paths to cached parquet files
        """
        completed_at = datetime.now()
        errors = convert_errors(bundle.errors) if bundle.errors else []

        # Single materialisation — collect results + summaries together via CSE.
        # This replaces the previous two-step flow (summary collect + sink) with
        # one pl.collect_all() call so Polars deduplicates the shared pipeline root.
        frames_to_collect: list[pl.LazyFrame] = [bundle.results]
        if bundle.summary_by_class is not None:
            frames_to_collect.append(bundle.summary_by_class)
        if bundle.summary_by_approach is not None:
            frames_to_collect.append(bundle.summary_by_approach)

        collected = pl.collect_all(frames_to_collect)
        results_df = collected[0]

        # Extract summary DataFrames from collected results
        idx = 1
        summary_by_class_df = None
        if bundle.summary_by_class is not None:
            summary_by_class_df = collected[idx]
            idx += 1
        summary_by_approach_df = None
        if bundle.summary_by_approach is not None:
            summary_by_approach_df = collected[idx]

        # Compute summary from already-collected DataFrame (zero cost)
        summary, exposure_count = self._compute_summary_from_df(
            results_df=results_df,
            floor_impact=bundle.floor_impact,
        )

        has_critical = any(e.severity == "critical" for e in errors)
        success = not has_critical and exposure_count > 0

        # Build metadata for the cache JSON
        metadata = {
            "framework": framework,
            "reporting_date": str(reporting_date),
            "total_ead": float(summary.total_ead),
            "total_rwa": float(summary.total_rwa),
            "exposure_count": summary.exposure_count,
        }

        # Write results + summaries to parquet via cache (no re-execution)
        cached = cache.sink_results(
            results=results_df,
            summary_by_class=summary_by_class_df,
            summary_by_approach=summary_by_approach_df,
            metadata=metadata,
        )

        performance = PerformanceMetrics(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            exposure_count=exposure_count,
        )

        return CalculationResponse(
            success=success,
            framework=framework,
            reporting_date=reporting_date,
            summary=summary,
            results_path=cached.results_path,
            summary_by_class_path=cached.summary_by_class_path,
            summary_by_approach_path=cached.summary_by_approach_path,
            errors=errors,
            performance=performance,
        )

    def format_error_response(
        self,
        errors: list[APIError],
        cache: ResultsCache,
        framework: str,
        reporting_date: date,
        started_at: datetime,
    ) -> CalculationResponse:
        """
        Format an error response when calculation fails.

        Writes an empty parquet to cache so downstream code can
        scan_results() without file-not-found errors.

        Args:
            errors: List of errors that caused failure
            cache: ResultsCache for writing empty parquet
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

        empty_lf = pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "approach_applied": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "risk_weight": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        })

        cached = cache.sink_results(results=empty_lf)

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
            results_path=cached.results_path,
            errors=errors,
            performance=performance,
        )

    def _compute_summary_from_df(
        self,
        results_df: pl.DataFrame,
        floor_impact: pl.LazyFrame | None,
    ) -> tuple[SummaryStatistics, int]:
        """
        Compute summary statistics from an already-collected DataFrame.

        Args:
            results_df: Collected results DataFrame
            floor_impact: Optional floor impact LazyFrame

        Returns:
            Tuple of (SummaryStatistics, exposure_count)
        """
        schema = results_df.schema
        ead_col = self._find_column_in_schema(schema, ["ead_final", "ead", "exposure_at_default"])
        rwa_col = self._find_column_in_schema(schema, ["rwa_final", "rwa", "risk_weighted_assets"])
        has_approach = "approach_applied" in schema.names()

        exposure_count = len(results_df)
        if exposure_count == 0:
            return SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ), 0

        total_ead = Decimal(str(results_df[ead_col].sum() or 0)) if ead_col else Decimal("0")
        total_rwa = Decimal(str(results_df[rwa_col].sum() or 0)) if rwa_col else Decimal("0")
        avg_rw = total_rwa / total_ead if total_ead > 0 else Decimal("0")

        # Per-approach aggregations
        sa_approaches = ["SA", "standardised"]
        irb_approaches = ["foundation_irb", "advanced_irb", "FIRB"]
        slotting_approaches = ["SLOTTING", "slotting"]

        def _approach_sum(col: str | None, approaches: list[str]) -> Decimal:
            if not col or not has_approach:
                return Decimal("0")
            mask = results_df["approach_applied"].is_in(approaches)
            return Decimal(str(results_df.filter(mask)[col].sum() or 0))

        # Floor impact
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

        summary = SummaryStatistics(
            total_ead=total_ead,
            total_rwa=total_rwa,
            exposure_count=exposure_count,
            average_risk_weight=avg_rw,
            total_ead_sa=_approach_sum(ead_col, sa_approaches),
            total_ead_irb=_approach_sum(ead_col, irb_approaches),
            total_ead_slotting=_approach_sum(ead_col, slotting_approaches),
            total_rwa_sa=_approach_sum(rwa_col, sa_approaches),
            total_rwa_irb=_approach_sum(rwa_col, irb_approaches),
            total_rwa_slotting=_approach_sum(rwa_col, slotting_approaches),
            floor_applied=floor_applied,
            floor_impact=floor_impact_value,
        )

        return summary, exposure_count

    def _find_column_in_schema(
        self,
        schema: pl.Schema,
        candidates: list[str],
    ) -> str | None:
        """
        Find first matching column name from candidates in a schema.

        Args:
            schema: Polars schema to search
            candidates: List of possible column names

        Returns:
            First matching column name or None
        """
        names = schema.names()
        for col in candidates:
            if col in names:
                return col
        return None
