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

        # Compute summary lazily — only aggregates, no full materialization
        summary, exposure_count = self._compute_summary_lazy(
            results=bundle.results,
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

        # Sink results + summaries to parquet via cache
        cached = cache.sink_results(
            results=bundle.results,
            summary_by_class=bundle.summary_by_class,
            summary_by_approach=bundle.summary_by_approach,
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

    def _compute_summary_lazy(
        self,
        results: pl.LazyFrame,
        floor_impact: pl.LazyFrame | None,
    ) -> tuple[SummaryStatistics, int]:
        """
        Compute summary statistics via a single lazy aggregation.

        Collects only a tiny 1-row aggregate — never materializes
        the full results DataFrame.

        Args:
            results: Results LazyFrame
            floor_impact: Optional floor impact LazyFrame

        Returns:
            Tuple of (SummaryStatistics, exposure_count)
        """
        schema = results.collect_schema()
        ead_col = self._find_column_in_schema(schema, ["ead_final", "ead", "exposure_at_default"])
        rwa_col = self._find_column_in_schema(schema, ["rwa_final", "rwa", "risk_weighted_assets"])
        has_approach = "approach_applied" in schema.names()

        # Build aggregation expressions
        agg_exprs: list[pl.Expr] = [pl.len().alias("count")]

        if ead_col:
            agg_exprs.append(pl.col(ead_col).sum().alias("total_ead"))
        if rwa_col:
            agg_exprs.append(pl.col(rwa_col).sum().alias("total_rwa"))

        # Per-approach aggregations
        sa_approaches = ["SA", "standardised"]
        irb_approaches = ["foundation_irb", "advanced_irb", "FIRB"]
        slotting_approaches = ["SLOTTING", "slotting"]

        if has_approach:
            if ead_col:
                agg_exprs.append(
                    pl.col(ead_col).filter(pl.col("approach_applied").is_in(sa_approaches)).sum().alias("ead_sa")
                )
                agg_exprs.append(
                    pl.col(ead_col).filter(pl.col("approach_applied").is_in(irb_approaches)).sum().alias("ead_irb")
                )
                agg_exprs.append(
                    pl.col(ead_col).filter(pl.col("approach_applied").is_in(slotting_approaches)).sum().alias("ead_slotting")
                )
            if rwa_col:
                agg_exprs.append(
                    pl.col(rwa_col).filter(pl.col("approach_applied").is_in(sa_approaches)).sum().alias("rwa_sa")
                )
                agg_exprs.append(
                    pl.col(rwa_col).filter(pl.col("approach_applied").is_in(irb_approaches)).sum().alias("rwa_irb")
                )
                agg_exprs.append(
                    pl.col(rwa_col).filter(pl.col("approach_applied").is_in(slotting_approaches)).sum().alias("rwa_slotting")
                )

        try:
            agg_df = results.select(agg_exprs).collect()
        except Exception:
            return SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ), 0

        exposure_count = int(agg_df["count"][0])
        if exposure_count == 0:
            return SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ), 0

        total_ead = Decimal(str(agg_df["total_ead"][0] or 0)) if ead_col else Decimal("0")
        total_rwa = Decimal(str(agg_df["total_rwa"][0] or 0)) if rwa_col else Decimal("0")
        avg_rw = total_rwa / total_ead if total_ead > 0 else Decimal("0")

        # Extract per-approach stats
        def _get_decimal(col_name: str) -> Decimal:
            if col_name in agg_df.columns:
                return Decimal(str(agg_df[col_name][0] or 0))
            return Decimal("0")

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
            total_ead_sa=_get_decimal("ead_sa"),
            total_ead_irb=_get_decimal("ead_irb"),
            total_ead_slotting=_get_decimal("ead_slotting"),
            total_rwa_sa=_get_decimal("rwa_sa"),
            total_rwa_irb=_get_decimal("rwa_irb"),
            total_rwa_slotting=_get_decimal("rwa_slotting"),
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
