"""Unit tests for the API models module.

Tests cover:
- CalculationRequest dataclass
- ValidationRequest dataclass
- SummaryStatistics dataclass
- APIError dataclass
- PerformanceMetrics dataclass
- CalculationResponse dataclass
- ValidationResponse dataclass
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api.models import (
    APIError,
    CalculationRequest,
    CalculationResponse,
    PerformanceMetrics,
    SummaryByDimension,
    SummaryStatistics,
    ValidationRequest,
    ValidationResponse,
)


# =============================================================================
# CalculationRequest Tests
# =============================================================================


class TestCalculationRequest:
    """Tests for CalculationRequest dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Request should be created with required fields."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert request.data_path == "/path/to/data"
        assert request.framework == "CRR"
        assert request.reporting_date == date(2024, 12, 31)

    def test_default_values(self) -> None:
        """Default values should be set correctly."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert request.base_currency == "GBP"
        assert request.enable_irb is False
        assert request.data_format == "parquet"
        assert request.eur_gbp_rate == Decimal("0.88")

    def test_path_property_returns_path_object(self) -> None:
        """Path property should return Path object."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert isinstance(request.path, Path)
        # Compare parts to handle platform differences
        assert request.path.parts[-3:] == ("path", "to", "data")

    def test_frozen_dataclass(self) -> None:
        """Request should be immutable."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            request.data_path = "/new/path"  # type: ignore

    def test_basel_31_framework(self) -> None:
        """Should accept BASEL_3_1 framework."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
        )
        assert request.framework == "BASEL_3_1"

    def test_csv_format(self) -> None:
        """Should accept csv data format."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            data_format="csv",
        )
        assert request.data_format == "csv"


# =============================================================================
# ValidationRequest Tests
# =============================================================================


class TestValidationRequest:
    """Tests for ValidationRequest dataclass."""

    def test_create_with_defaults(self) -> None:
        """Request should be created with default format."""
        request = ValidationRequest(data_path="/path/to/data")
        assert request.data_path == "/path/to/data"
        assert request.data_format == "parquet"

    def test_path_property(self) -> None:
        """Path property should return Path object."""
        request = ValidationRequest(data_path="/path/to/data")
        assert isinstance(request.path, Path)

    def test_csv_format(self) -> None:
        """Should accept csv format."""
        request = ValidationRequest(
            data_path="/path/to/data",
            data_format="csv",
        )
        assert request.data_format == "csv"


# =============================================================================
# SummaryStatistics Tests
# =============================================================================


class TestSummaryStatistics:
    """Tests for SummaryStatistics dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Statistics should be created with required fields."""
        stats = SummaryStatistics(
            total_ead=Decimal("1000000"),
            total_rwa=Decimal("500000"),
            exposure_count=100,
            average_risk_weight=Decimal("0.5"),
        )
        assert stats.total_ead == Decimal("1000000")
        assert stats.total_rwa == Decimal("500000")
        assert stats.exposure_count == 100
        assert stats.average_risk_weight == Decimal("0.5")

    def test_default_values(self) -> None:
        """Default values should be zero."""
        stats = SummaryStatistics(
            total_ead=Decimal("1000000"),
            total_rwa=Decimal("500000"),
            exposure_count=100,
            average_risk_weight=Decimal("0.5"),
        )
        assert stats.total_rwa_sa == Decimal("0")
        assert stats.total_rwa_irb == Decimal("0")
        assert stats.total_rwa_slotting == Decimal("0")
        assert stats.floor_applied is False
        assert stats.floor_impact == Decimal("0")

    def test_with_floor_impact(self) -> None:
        """Should track floor application and impact."""
        stats = SummaryStatistics(
            total_ead=Decimal("1000000"),
            total_rwa=Decimal("500000"),
            exposure_count=100,
            average_risk_weight=Decimal("0.5"),
            floor_applied=True,
            floor_impact=Decimal("50000"),
        )
        assert stats.floor_applied is True
        assert stats.floor_impact == Decimal("50000")


# =============================================================================
# SummaryByDimension Tests
# =============================================================================


class TestSummaryByDimension:
    """Tests for SummaryByDimension dataclass."""

    def test_create_with_dataframe(self) -> None:
        """Should store dimension name and DataFrame."""
        df = pl.DataFrame({
            "exposure_class": ["CORPORATE", "RETAIL"],
            "total_rwa": [100000.0, 50000.0],
        })
        summary = SummaryByDimension(
            dimension_name="exposure_class",
            data=df,
        )
        assert summary.dimension_name == "exposure_class"
        assert len(summary.data) == 2


# =============================================================================
# APIError Tests
# =============================================================================


class TestAPIError:
    """Tests for APIError dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Error should be created with required fields."""
        error = APIError(
            code="DQ001",
            message="Test error message",
            severity="error",
            category="Data Quality",
        )
        assert error.code == "DQ001"
        assert error.message == "Test error message"
        assert error.severity == "error"
        assert error.category == "Data Quality"

    def test_default_details(self) -> None:
        """Details should default to empty dict."""
        error = APIError(
            code="DQ001",
            message="Test",
            severity="error",
            category="Data Quality",
        )
        assert error.details == {}

    def test_with_details(self) -> None:
        """Should store additional details."""
        error = APIError(
            code="DQ001",
            message="Test",
            severity="error",
            category="Data Quality",
            details={"exposure_reference": "EXP001", "field_name": "amount"},
        )
        assert error.details["exposure_reference"] == "EXP001"
        assert error.details["field_name"] == "amount"

    def test_str_representation(self) -> None:
        """String representation should be formatted correctly."""
        error = APIError(
            code="DQ001",
            message="Test error",
            severity="error",
            category="Data Quality",
        )
        assert str(error) == "[DQ001] ERROR: Test error"

    def test_severity_levels(self) -> None:
        """Should accept all severity levels."""
        for severity in ["warning", "error", "critical"]:
            error = APIError(
                code="TEST",
                message="Test",
                severity=severity,
                category="Test",
            )
            assert error.severity == severity


# =============================================================================
# PerformanceMetrics Tests
# =============================================================================


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Metrics should be created with required fields."""
        started = datetime(2024, 1, 1, 10, 0, 0)
        completed = datetime(2024, 1, 1, 10, 0, 5)
        metrics = PerformanceMetrics(
            started_at=started,
            completed_at=completed,
            duration_seconds=5.0,
            exposure_count=1000,
        )
        assert metrics.started_at == started
        assert metrics.completed_at == completed
        assert metrics.duration_seconds == 5.0
        assert metrics.exposure_count == 1000

    def test_exposures_per_second_property(self) -> None:
        """Should calculate throughput correctly."""
        metrics = PerformanceMetrics(
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_seconds=5.0,
            exposure_count=1000,
        )
        assert metrics.exposures_per_second == 200.0

    def test_exposures_per_second_zero_duration(self) -> None:
        """Should return 0 for zero duration."""
        metrics = PerformanceMetrics(
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_seconds=0.0,
            exposure_count=1000,
        )
        assert metrics.exposures_per_second == 0.0


# =============================================================================
# CalculationResponse Tests
# =============================================================================


class TestCalculationResponse:
    """Tests for CalculationResponse dataclass."""

    @pytest.fixture
    def sample_response(self) -> CalculationResponse:
        """Create a sample response for testing."""
        return CalculationResponse(
            success=True,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            summary=SummaryStatistics(
                total_ead=Decimal("1000000"),
                total_rwa=Decimal("500000"),
                exposure_count=100,
                average_risk_weight=Decimal("0.5"),
            ),
            results=pl.DataFrame({
                "exposure_reference": ["EXP001", "EXP002"],
                "rwa_final": [250000.0, 250000.0],
            }),
        )

    def test_create_successful_response(self, sample_response: CalculationResponse) -> None:
        """Response should be created with success status."""
        assert sample_response.success is True
        assert sample_response.framework == "CRR"
        assert sample_response.reporting_date == date(2024, 12, 31)

    def test_has_warnings_false_when_no_errors(self, sample_response: CalculationResponse) -> None:
        """has_warnings should be False when no errors."""
        assert sample_response.has_warnings is False

    def test_has_errors_false_when_no_errors(self, sample_response: CalculationResponse) -> None:
        """has_errors should be False when no errors."""
        assert sample_response.has_errors is False

    def test_warning_count(self) -> None:
        """Should count warnings correctly."""
        response = CalculationResponse(
            success=True,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            summary=SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ),
            results=pl.DataFrame(),
            errors=[
                APIError(code="W1", message="Warning 1", severity="warning", category="Test"),
                APIError(code="W2", message="Warning 2", severity="warning", category="Test"),
                APIError(code="E1", message="Error 1", severity="error", category="Test"),
            ],
        )
        assert response.warning_count == 2
        assert response.error_count == 1

    def test_has_warnings_true(self) -> None:
        """has_warnings should be True when warnings exist."""
        response = CalculationResponse(
            success=True,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            summary=SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ),
            results=pl.DataFrame(),
            errors=[
                APIError(code="W1", message="Warning", severity="warning", category="Test"),
            ],
        )
        assert response.has_warnings is True
        assert response.has_errors is False

    def test_has_errors_true(self) -> None:
        """has_errors should be True when errors exist."""
        response = CalculationResponse(
            success=False,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            summary=SummaryStatistics(
                total_ead=Decimal("0"),
                total_rwa=Decimal("0"),
                exposure_count=0,
                average_risk_weight=Decimal("0"),
            ),
            results=pl.DataFrame(),
            errors=[
                APIError(code="E1", message="Error", severity="error", category="Test"),
            ],
        )
        assert response.has_errors is True


# =============================================================================
# ValidationResponse Tests
# =============================================================================


class TestValidationResponse:
    """Tests for ValidationResponse dataclass."""

    def test_valid_response(self) -> None:
        """Valid response should have correct properties."""
        response = ValidationResponse(
            valid=True,
            data_path="/path/to/data",
            files_found=["file1.parquet", "file2.parquet"],
        )
        assert response.valid is True
        assert response.found_count == 2
        assert response.missing_count == 0

    def test_invalid_response(self) -> None:
        """Invalid response should track missing files."""
        response = ValidationResponse(
            valid=False,
            data_path="/path/to/data",
            files_found=["file1.parquet"],
            files_missing=["file2.parquet", "file3.parquet"],
            errors=[
                APIError(code="VAL002", message="Missing file", severity="error", category="Validation"),
            ],
        )
        assert response.valid is False
        assert response.found_count == 1
        assert response.missing_count == 2
