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
    from rwa_calc.contracts.bundles import AggregatedResultBundle, ELPortfolioSummary


# =============================================================================
# Constants
# =============================================================================

# Approach-string buckets for the SA / IRB / Slotting card totals. Production
# emits the long ``ApproachType`` values ("standardised", "foundation_irb",
# "advanced_irb", "slotting"); the short aliases (SA/FIRB/AIRB/SLOTTING) appear on
# branch frames and test fixtures, so both forms are listed to avoid undercounting.
_SA_APPROACHES = ["SA", "standardised", "sa", "STD"]
_IRB_APPROACHES = ["foundation_irb", "advanced_irb", "FIRB", "AIRB", "firb", "airb"]
_SLOTTING_APPROACHES = ["SLOTTING", "slotting"]

_EMPTY_SUMMARY = SummaryStatistics(
    total_ead=Decimal("0"),
    total_rwa=Decimal("0"),
    exposure_count=0,
    average_risk_weight=Decimal("0"),
)


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
        if bundle.summary_by_class_method is not None:
            frames_to_collect.append(bundle.summary_by_class_method)

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
            idx += 1
        summary_by_class_method_df = None
        if bundle.summary_by_class_method is not None:
            summary_by_class_method_df = collected[idx]

        # Compute summary from already-collected DataFrame (zero cost)
        summary, exposure_count = self._compute_summary_from_df(
            results_df=results_df,
            floor_impact=bundle.floor_impact,
            el_summary=bundle.el_summary,
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
            summary_by_class_method=summary_by_class_method_df,
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
            summary_by_class_method_path=cached.summary_by_class_method_path,
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

        empty_lf = pl.LazyFrame(
            {
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            }
        )

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
        el_summary: ELPortfolioSummary | None = None,
    ) -> tuple[SummaryStatistics, int]:
        """
        Compute summary statistics from an already-collected DataFrame.

        Args:
            results_df: Collected results DataFrame
            floor_impact: Optional floor impact LazyFrame
            el_summary: Optional portfolio-level EL summary with T2 credit cap

        Returns:
            Tuple of (SummaryStatistics, exposure_count)
        """
        exposure_count = len(results_df)
        if exposure_count == 0:
            return _EMPTY_SUMMARY, 0

        schema = results_df.schema
        ead_col = self._find_column_in_schema(schema, ["ead_final", "ead", "exposure_at_default"])
        rwa_col = self._find_column_in_schema(schema, ["rwa_final", "rwa", "risk_weighted_assets"])
        has_approach = "approach_applied" in schema.names()

        total_ead = _column_sum_decimal(results_df, ead_col)
        total_rwa = _column_sum_decimal(results_df, rwa_col)
        avg_rw = total_rwa / total_ead if total_ead > 0 else Decimal("0")

        floor_applied, floor_impact_value = _extract_floor_impact(floor_impact)
        el_shortfall, el_excess, t2_credit = _extract_el_fields(el_summary)

        summary = SummaryStatistics(
            total_ead=total_ead,
            total_rwa=total_rwa,
            exposure_count=exposure_count,
            average_risk_weight=avg_rw,
            total_ead_sa=_approach_sum(results_df, ead_col, _SA_APPROACHES, has_approach),
            total_ead_irb=_approach_sum(results_df, ead_col, _IRB_APPROACHES, has_approach),
            total_ead_slotting=_approach_sum(
                results_df, ead_col, _SLOTTING_APPROACHES, has_approach
            ),
            total_rwa_sa=_approach_sum(results_df, rwa_col, _SA_APPROACHES, has_approach),
            total_rwa_irb=_approach_sum(results_df, rwa_col, _IRB_APPROACHES, has_approach),
            total_rwa_slotting=_approach_sum(
                results_df, rwa_col, _SLOTTING_APPROACHES, has_approach
            ),
            floor_applied=floor_applied,
            floor_impact=floor_impact_value,
            total_el_shortfall=el_shortfall,
            total_el_excess=el_excess,
            t2_credit=t2_credit,
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


# =============================================================================
# Private summary helpers
# =============================================================================


def _finite_sum(series: pl.Series) -> float | int | None:
    """Sum a series, excluding non-finite (NaN / inf) values.

    Polars float ``.sum()`` propagates ``NaN`` (and ``inf``) — a single
    non-finite row would otherwise turn the whole portfolio total into
    ``NaN``/``inf`` and blank the stat cards. ``null`` rows are already skipped
    by ``.sum()``; here we additionally drop NaN/inf so the card shows the real
    total for the unaffected rows. The offending rows are surfaced separately as
    an aggregator ``CalculationError`` (AGG001), so this is a display safety net,
    not a silent correction.
    """
    if series.dtype in (pl.Float32, pl.Float64):
        series = series.filter(series.is_finite())
    return series.sum()


def _column_sum_decimal(df: pl.DataFrame, col: str | None) -> Decimal:
    """Sum a column as Decimal, returning 0 when the column is missing.

    Non-finite (NaN / inf) rows are excluded so one poisoned IRB row cannot
    blank the total (see ``_finite_sum``).
    """
    if not col:
        return Decimal("0")
    return Decimal(str(_finite_sum(df[col]) or 0))


def _approach_sum(
    df: pl.DataFrame,
    col: str | None,
    approaches: list[str],
    has_approach: bool,
) -> Decimal:
    """Sum a column over rows whose `approach_applied` is in `approaches`.

    Non-finite (NaN / inf) rows are excluded (see ``_finite_sum``).
    """
    if not col or not has_approach:
        return Decimal("0")
    mask = df["approach_applied"].is_in(approaches)
    return Decimal(str(_finite_sum(df.filter(mask)[col]) or 0))


def _extract_floor_impact(floor_impact: pl.LazyFrame | None) -> tuple[bool, Decimal]:
    """Materialise the floor-impact frame and return (applied, add_on)."""
    if floor_impact is None:
        return False, Decimal("0")
    try:
        floor_df: pl.DataFrame = floor_impact.collect()
    except Exception:
        return False, Decimal("0")
    applied = (
        bool(floor_df["floor_binding"].any()) if "floor_binding" in floor_df.columns else False
    )
    add_on = (
        Decimal(str(_finite_sum(floor_df["floor_add_on"]) or 0))
        if "floor_add_on" in floor_df.columns
        else Decimal("0")
    )
    return applied, add_on


def _extract_el_fields(el_summary: ELPortfolioSummary | None) -> tuple[Decimal, Decimal, Decimal]:
    """Return (shortfall, excess, t2_credit) from the EL summary or zeros."""
    if el_summary is None:
        return Decimal("0"), Decimal("0"), Decimal("0")
    return el_summary.total_el_shortfall, el_summary.total_el_excess, el_summary.t2_credit
