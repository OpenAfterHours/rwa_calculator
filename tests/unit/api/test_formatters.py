"""Unit tests for the API formatters module.

Tests cover:
- ResultFormatter.format_response with ResultsCache
- ResultFormatter.format_error_response with ResultsCache
- Summary computation via lazy aggregation
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api.formatters import ResultFormatter
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.results_cache import ResultsCache
from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cache(tmp_path: Path) -> ResultsCache:
    """Create a ResultsCache in a temp directory."""
    return ResultsCache(tmp_path / "cache")


@pytest.fixture
def sample_result_bundle() -> AggregatedResultBundle:
    """Create a sample AggregatedResultBundle for testing."""
    results = pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "approach_applied": ["SA", "SA", "foundation_irb"],
        "exposure_class": ["corporate", "retail", "corporate"],
        "ead_final": [1000000.0, 500000.0, 750000.0],
        "risk_weight": [1.0, 0.75, 0.5],
        "rwa_final": [1000000.0, 375000.0, 375000.0],
    })

    sa_results = pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002"],
        "rwa": [1000000.0, 375000.0],
    })

    irb_results = pl.LazyFrame({
        "exposure_reference": ["EXP003"],
        "rwa": [375000.0],
    })

    summary_by_class = pl.LazyFrame({
        "exposure_class": ["corporate", "retail"],
        "total_ead": [1750000.0, 500000.0],
        "total_rwa": [1375000.0, 375000.0],
    })

    return AggregatedResultBundle(
        results=results,
        sa_results=sa_results,
        irb_results=irb_results,
        slotting_results=None,
        floor_impact=None,
        summary_by_class=summary_by_class,
        errors=[],
    )


@pytest.fixture
def empty_result_bundle() -> AggregatedResultBundle:
    """Create an empty AggregatedResultBundle."""
    return AggregatedResultBundle(
        results=pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        }),
        errors=[],
    )


@pytest.fixture
def error_result_bundle() -> AggregatedResultBundle:
    """Create a bundle with errors."""
    return AggregatedResultBundle(
        results=pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "rwa_final": [500000.0],
        }),
        errors=[
            CalculationError(
                code="TEST001",
                message="Test error",
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CALCULATION,
            ),
            CalculationError(
                code="TEST002",
                message="Test warning",
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
            ),
        ],
    )


# =============================================================================
# ResultFormatter Tests
# =============================================================================


class TestResultFormatterFormatResponse:
    """Tests for ResultFormatter.format_response method."""

    def test_successful_response(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should format successful result bundle."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert isinstance(response, CalculationResponse)
        assert response.success is True
        assert response.framework == "CRR"
        assert response.reporting_date == date(2024, 12, 31)

    def test_results_written_to_parquet(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should sink results to a parquet file that can be scanned lazily."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.results_path.exists()
        results_df = response.collect_results()
        assert isinstance(results_df, pl.DataFrame)
        assert results_df.height == 3

    def test_computes_summary_statistics(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should compute summary statistics correctly via lazy aggregation."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary.exposure_count == 3
        assert response.summary.total_ead == Decimal("2250000")
        assert response.summary.total_rwa == Decimal("1750000")

    def test_includes_performance_metrics(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should include performance metrics."""
        formatter = ResultFormatter()
        started = datetime.now()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=started,
        )

        assert response.performance is not None
        assert response.performance.started_at == started
        assert response.performance.exposure_count == 3
        assert response.performance.duration_seconds >= 0

    def test_writes_summary_by_class_parquet(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should write summary by class to parquet."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary_by_class_path is not None
        assert response.summary_by_class_path.exists()
        class_lf = response.scan_summary_by_class()
        assert class_lf is not None
        assert isinstance(class_lf, pl.LazyFrame)

    def test_converts_errors(
        self,
        error_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should convert CalculationErrors to APIErrors."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=error_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert len(response.errors) == 2
        assert response.errors[0].code == "TEST001"
        assert response.errors[1].code == "TEST002"


class TestResultFormatterFormatErrorResponse:
    """Tests for ResultFormatter.format_error_response method."""

    def test_error_response(self, cache: ResultsCache) -> None:
        """Should format error response correctly."""
        from rwa_calc.api.models import APIError

        formatter = ResultFormatter()
        errors = [
            APIError(
                code="ERR001",
                message="Critical error",
                severity="critical",
                category="System",
            )
        ]

        response = formatter.format_error_response(
            errors=errors,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.success is False
        assert len(response.errors) == 1
        assert response.summary.exposure_count == 0
        assert response.results_path.exists()
        assert response.collect_results().height == 0


class TestResultFormatterComputeSummaryLazy:
    """Tests for ResultFormatter._compute_summary_lazy method."""

    def test_empty_results(
        self,
        empty_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should handle empty results."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=empty_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary.exposure_count == 0
        assert response.summary.total_ead == Decimal("0")
        assert response.summary.total_rwa == Decimal("0")
        assert response.summary.average_risk_weight == Decimal("0")

    def test_computes_average_risk_weight(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should compute average risk weight correctly."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        # Total RWA = 1,750,000, Total EAD = 2,250,000
        expected_avg_rw = Decimal("1750000") / Decimal("2250000")
        assert response.summary.average_risk_weight == expected_avg_rw

    def test_computes_rwa_by_approach(
        self,
        sample_result_bundle: AggregatedResultBundle,
        cache: ResultsCache,
    ) -> None:
        """Should compute RWA by approach."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            cache=cache,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        # SA RWA = 1,375,000, IRB RWA = 375,000
        assert response.summary.total_rwa_sa == Decimal("1375000")
        assert response.summary.total_rwa_irb == Decimal("375000")


class TestComputeSummaryLazyApproachStats:
    """Tests for approach stats computed via lazy aggregation."""

    def _make_bundle(self, approach_applied: list[str], ead: list[float], rwa: list[float]) -> AggregatedResultBundle:
        """Helper to create a bundle with given approach data."""
        return AggregatedResultBundle(
            results=pl.LazyFrame({
                "exposure_reference": [f"EXP{i}" for i in range(len(approach_applied))],
                "approach_applied": approach_applied,
                "ead_final": ead,
                "rwa_final": rwa,
            }),
            errors=[],
        )

    def test_foundation_irb_counted_in_irb(self, cache: ResultsCache) -> None:
        """foundation_irb should be counted in ead_irb/rwa_irb."""
        bundle = self._make_bundle(["foundation_irb"], [1_000_000.0], [500_000.0])
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_irb == Decimal("1000000")
        assert response.summary.total_rwa_irb == Decimal("500000")
        assert response.summary.total_ead_sa == Decimal("0")

    def test_advanced_irb_counted_in_irb(self, cache: ResultsCache) -> None:
        """advanced_irb should be counted in ead_irb/rwa_irb."""
        bundle = self._make_bundle(["advanced_irb"], [2_000_000.0], [800_000.0])
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_irb == Decimal("2000000")
        assert response.summary.total_rwa_irb == Decimal("800000")

    def test_sa_counted_in_sa(self, cache: ResultsCache) -> None:
        """SA literal should be counted in ead_sa/rwa_sa."""
        bundle = self._make_bundle(["SA"], [500_000.0], [250_000.0])
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_sa == Decimal("500000")
        assert response.summary.total_rwa_sa == Decimal("250000")
        assert response.summary.total_ead_irb == Decimal("0")

    def test_slotting_counted_in_slotting(self, cache: ResultsCache) -> None:
        """Both SLOTTING literal and slotting enum value should be counted."""
        bundle = self._make_bundle(
            ["SLOTTING", "slotting"],
            [300_000.0, 200_000.0],
            [150_000.0, 100_000.0],
        )
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_slotting == Decimal("500000")
        assert response.summary.total_rwa_slotting == Decimal("250000")

    def test_mixed_approaches(self, cache: ResultsCache) -> None:
        """Mixed approach results should produce correct per-approach breakdown."""
        bundle = self._make_bundle(
            ["SA", "SA", "foundation_irb", "advanced_irb", "SLOTTING"],
            [1_000_000.0, 500_000.0, 750_000.0, 250_000.0, 300_000.0],
            [1_000_000.0, 375_000.0, 375_000.0, 100_000.0, 240_000.0],
        )
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_sa == Decimal("1500000")
        assert response.summary.total_rwa_sa == Decimal("1375000")
        assert response.summary.total_ead_irb == Decimal("1000000")
        assert response.summary.total_rwa_irb == Decimal("475000")
        assert response.summary.total_ead_slotting == Decimal("300000")
        assert response.summary.total_rwa_slotting == Decimal("240000")

    def test_firb_fallback_counted_in_irb(self, cache: ResultsCache) -> None:
        """FIRB fallback should also be counted in IRB."""
        bundle = self._make_bundle(["FIRB"], [400_000.0], [200_000.0])
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_irb == Decimal("400000")
        assert response.summary.total_rwa_irb == Decimal("200000")

    def test_no_approach_column(self, cache: ResultsCache) -> None:
        """Should return zeros when approach_applied column is missing."""
        bundle = AggregatedResultBundle(
            results=pl.LazyFrame({
                "exposure_reference": ["EXP001"],
                "ead_final": [100_000.0],
                "rwa_final": [50_000.0],
            }),
            errors=[],
        )
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=bundle, cache=cache, framework="CRR",
            reporting_date=date(2024, 12, 31), started_at=datetime.now(),
        )

        assert response.summary.total_ead_sa == Decimal("0")
        assert response.summary.total_ead_irb == Decimal("0")
        assert response.summary.total_ead_slotting == Decimal("0")
