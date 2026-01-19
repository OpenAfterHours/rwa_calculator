"""Unit tests for the API formatters module.

Tests cover:
- ResultFormatter class
- compute_summary convenience function
- materialize_bundle convenience function
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.api.formatters import (
    ResultFormatter,
    compute_summary,
    materialize_bundle,
)
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_result_bundle() -> AggregatedResultBundle:
    """Create a sample AggregatedResultBundle for testing."""
    results = pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "approach_applied": ["SA", "SA", "IRB"],
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

    def test_successful_response(self, sample_result_bundle: AggregatedResultBundle) -> None:
        """Should format successful result bundle."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert isinstance(response, CalculationResponse)
        assert response.success is True
        assert response.framework == "CRR"
        assert response.reporting_date == date(2024, 12, 31)

    def test_materializes_results(self, sample_result_bundle: AggregatedResultBundle) -> None:
        """Should materialize LazyFrame to DataFrame."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert isinstance(response.results, pl.DataFrame)
        assert len(response.results) == 3

    def test_computes_summary_statistics(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should compute summary statistics correctly."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary.exposure_count == 3
        assert response.summary.total_ead == Decimal("2250000")
        assert response.summary.total_rwa == Decimal("1750000")

    def test_includes_performance_metrics(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should include performance metrics."""
        formatter = ResultFormatter()
        started = datetime.now()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=started,
        )

        assert response.performance is not None
        assert response.performance.started_at == started
        assert response.performance.exposure_count == 3
        assert response.performance.duration_seconds >= 0

    def test_materializes_summary_by_class(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should materialize summary by class."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary_by_class is not None
        assert isinstance(response.summary_by_class, pl.DataFrame)

    def test_converts_errors(self, error_result_bundle: AggregatedResultBundle) -> None:
        """Should convert CalculationErrors to APIErrors."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=error_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert len(response.errors) == 2
        assert response.errors[0].code == "TEST001"
        assert response.errors[1].code == "TEST002"


class TestResultFormatterFormatErrorResponse:
    """Tests for ResultFormatter.format_error_response method."""

    def test_error_response(self) -> None:
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
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.success is False
        assert len(response.errors) == 1
        assert response.summary.exposure_count == 0
        assert response.results.height == 0


class TestResultFormatterComputeSummary:
    """Tests for ResultFormatter._compute_summary method."""

    def test_empty_results(self, empty_result_bundle: AggregatedResultBundle) -> None:
        """Should handle empty results."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=empty_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        assert response.summary.exposure_count == 0
        assert response.summary.total_ead == Decimal("0")
        assert response.summary.total_rwa == Decimal("0")
        assert response.summary.average_risk_weight == Decimal("0")

    def test_computes_average_risk_weight(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should compute average risk weight correctly."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        # Total RWA = 1,750,000, Total EAD = 2,250,000
        # Average RW = 1,750,000 / 2,250,000 ≈ 0.7778
        expected_avg_rw = Decimal("1750000") / Decimal("2250000")
        assert response.summary.average_risk_weight == expected_avg_rw

    def test_computes_rwa_by_approach(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should compute RWA by approach."""
        formatter = ResultFormatter()
        response = formatter.format_response(
            bundle=sample_result_bundle,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            started_at=datetime.now(),
        )

        # SA RWA = 1,375,000, IRB RWA = 375,000
        assert response.summary.total_rwa_sa == Decimal("1375000")
        assert response.summary.total_rwa_irb == Decimal("375000")


class TestResultFormatterFindColumn:
    """Tests for ResultFormatter._find_column method."""

    def test_finds_first_match(self) -> None:
        """Should find first matching column."""
        formatter = ResultFormatter()
        df = pl.DataFrame({
            "ead_final": [100],
            "rwa_final": [50],
        })

        col = formatter._find_column(df, ["ead", "ead_final", "exposure_at_default"])
        assert col == "ead_final"

    def test_returns_none_for_no_match(self) -> None:
        """Should return None when no columns match."""
        formatter = ResultFormatter()
        df = pl.DataFrame({
            "amount": [100],
        })

        col = formatter._find_column(df, ["ead", "ead_final", "exposure_at_default"])
        assert col is None


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestComputeSummary:
    """Tests for compute_summary convenience function."""

    def test_basic_summary(self) -> None:
        """Should compute summary from DataFrame."""
        df = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002"],
            "ead_final": [1000000.0, 500000.0],
            "rwa_final": [500000.0, 250000.0],
        })

        summary = compute_summary(df)

        assert isinstance(summary, SummaryStatistics)
        assert summary.exposure_count == 2
        assert summary.total_ead == Decimal("1500000")
        assert summary.total_rwa == Decimal("750000")

    def test_empty_dataframe(self) -> None:
        """Should handle empty DataFrame."""
        df = pl.DataFrame({
            "ead_final": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        })

        summary = compute_summary(df)

        assert summary.exposure_count == 0
        assert summary.total_ead == Decimal("0")


class TestMaterializeBundle:
    """Tests for materialize_bundle convenience function."""

    def test_materializes_all_frames(
        self, sample_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should materialize all LazyFrames in bundle."""
        result = materialize_bundle(sample_result_bundle)

        assert "results" in result
        assert isinstance(result["results"], pl.DataFrame)
        assert "sa_results" in result
        assert "irb_results" in result
        assert "summary_by_class" in result

    def test_handles_none_frames(
        self, empty_result_bundle: AggregatedResultBundle
    ) -> None:
        """Should handle None LazyFrames."""
        result = materialize_bundle(empty_result_bundle)

        assert "results" in result
        # Optional frames that are None won't be in result
        assert result.get("sa_results") is None or "sa_results" not in result
