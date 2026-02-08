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

        results_df = self._materialize_results(bundle.results)

        summary = self._compute_summary(
            results_df=results_df,
            sa_results=bundle.sa_results,
            irb_results=bundle.irb_results,
            slotting_results=bundle.slotting_results,
            floor_impact=bundle.floor_impact,
        )

        summary_by_class = self._materialize_optional(bundle.summary_by_class)
        summary_by_approach = self._materialize_optional(bundle.summary_by_approach)

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

    def _materialize_results(self, lazy_frame: pl.LazyFrame) -> pl.DataFrame:
        """
        Materialize main results LazyFrame to DataFrame.

        Args:
            lazy_frame: LazyFrame containing results

        Returns:
            Materialized DataFrame
        """
        try:
            return lazy_frame.collect()
        except Exception:
            return pl.DataFrame({
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            })

    def _materialize_optional(
        self,
        lazy_frame: pl.LazyFrame | None,
    ) -> pl.DataFrame | None:
        """
        Materialize optional LazyFrame to DataFrame.

        Args:
            lazy_frame: Optional LazyFrame

        Returns:
            Materialized DataFrame or None
        """
        if lazy_frame is None:
            return None
        try:
            return lazy_frame.collect()
        except Exception:
            return None

    def _compute_summary(
        self,
        results_df: pl.DataFrame,
        sa_results: pl.LazyFrame | None,
        irb_results: pl.LazyFrame | None,
        slotting_results: pl.LazyFrame | None,
        floor_impact: pl.LazyFrame | None,
    ) -> SummaryStatistics:
        """
        Compute summary statistics from results.

        Args:
            results_df: Materialized results DataFrame
            sa_results: Optional SA results LazyFrame
            irb_results: Optional IRB results LazyFrame
            slotting_results: Optional Slotting results LazyFrame
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

        total_ead_sa = self._sum_ead_from_lazyframe(sa_results)
        total_ead_irb = self._sum_ead_from_lazyframe(irb_results)
        total_ead_slotting = self._sum_ead_from_lazyframe(slotting_results)

        total_rwa_sa = self._sum_rwa_from_lazyframe(sa_results)
        total_rwa_irb = self._sum_rwa_from_lazyframe(irb_results)
        total_rwa_slotting = self._sum_rwa_from_lazyframe(slotting_results)

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
            total_ead_sa=total_ead_sa,
            total_ead_irb=total_ead_irb,
            total_ead_slotting=total_ead_slotting,
            total_rwa_sa=total_rwa_sa,
            total_rwa_irb=total_rwa_irb,
            total_rwa_slotting=total_rwa_slotting,
            floor_applied=floor_applied,
            floor_impact=floor_impact_value,
        )

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

    def _sum_rwa_from_lazyframe(
        self,
        lazy_frame: pl.LazyFrame | None,
    ) -> Decimal:
        """
        Sum RWA from a LazyFrame.

        Args:
            lazy_frame: Optional LazyFrame with RWA column

        Returns:
            Total RWA as Decimal
        """
        if lazy_frame is None:
            return Decimal("0")

        try:
            df = lazy_frame.collect()
            rwa_col = self._find_column(
                df,
                ["rwa", "rwa_final", "rwa_post_factor", "risk_weighted_assets"],
            )
            if rwa_col:
                return Decimal(str(df[rwa_col].sum() or 0))
        except Exception:
            pass

        return Decimal("0")

    def _sum_ead_from_lazyframe(
        self,
        lazy_frame: pl.LazyFrame | None,
    ) -> Decimal:
        """
        Sum EAD from a LazyFrame.

        Args:
            lazy_frame: Optional LazyFrame with EAD column

        Returns:
            Total EAD as Decimal
        """
        if lazy_frame is None:
            return Decimal("0")

        try:
            df = lazy_frame.collect()
            ead_col = self._find_column(
                df,
                ["ead_final", "ead", "exposure_at_default"],
            )
            if ead_col:
                return Decimal(str(df[ead_col].sum() or 0))
        except Exception:
            pass

        return Decimal("0")


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
        sa_results=None,
        irb_results=None,
        slotting_results=None,
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
