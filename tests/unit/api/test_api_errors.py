"""Unit tests for the API errors module.

Tests cover:
- convert_to_api_error function
- convert_errors function
- create_api_error factory function
- Error message overrides
"""

from __future__ import annotations

import pytest

from rwa_calc.api.errors import (
    convert_errors,
    convert_to_api_error,
    create_api_error,
    create_file_not_found_error,
    create_load_error,
    create_validation_error,
)
from rwa_calc.api.models import APIError
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_calculation_error() -> CalculationError:
    """Create a sample CalculationError for testing."""
    return CalculationError(
        code="DQ001",
        message="Required field 'amount' is missing",
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference="EXP001",
        field_name="amount",
    )


@pytest.fixture
def detailed_calculation_error() -> CalculationError:
    """Create a detailed CalculationError with all fields."""
    return CalculationError(
        code="DQ002",
        message="Invalid value",
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference="EXP002",
        counterparty_reference="CPT001",
        regulatory_reference="CRR Art. 153",
        field_name="pd",
        expected_value="0.0 to 1.0",
        actual_value="1.5",
    )


# =============================================================================
# convert_to_api_error Tests
# =============================================================================


class TestConvertToApiError:
    """Tests for convert_to_api_error function."""

    def test_basic_conversion(self, sample_calculation_error: CalculationError) -> None:
        """Should convert basic CalculationError to APIError."""
        api_error = convert_to_api_error(sample_calculation_error)

        assert isinstance(api_error, APIError)
        assert api_error.code == "DQ001"
        assert api_error.severity == "error"
        assert api_error.category == "Data Quality"

    def test_preserves_exposure_reference(self, sample_calculation_error: CalculationError) -> None:
        """Should preserve exposure reference in details."""
        api_error = convert_to_api_error(sample_calculation_error)

        assert "exposure_reference" in api_error.details
        assert api_error.details["exposure_reference"] == "EXP001"

    def test_preserves_field_name(self, sample_calculation_error: CalculationError) -> None:
        """Should preserve field name in details."""
        api_error = convert_to_api_error(sample_calculation_error)

        assert "field_name" in api_error.details
        assert api_error.details["field_name"] == "amount"

    def test_detailed_conversion(self, detailed_calculation_error: CalculationError) -> None:
        """Should convert error with all fields."""
        api_error = convert_to_api_error(detailed_calculation_error)

        assert api_error.severity == "warning"
        assert api_error.details["counterparty_reference"] == "CPT001"
        assert api_error.details["regulatory_reference"] == "CRR Art. 153"
        assert api_error.details["expected_value"] == "0.0 to 1.0"
        assert api_error.details["actual_value"] == "1.5"

    def test_message_override_for_known_code(self) -> None:
        """Should use user-friendly message for known error codes."""
        error = CalculationError(
            code="DQ001",
            message="Technical error message",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
        )
        api_error = convert_to_api_error(error)

        # Should use override message instead of technical message
        assert "Required field" in api_error.message

    def test_fallback_to_original_message(self) -> None:
        """Should use original message for unknown error codes."""
        error = CalculationError(
            code="UNKNOWN999",
            message="Custom error message",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
        )
        api_error = convert_to_api_error(error)

        assert api_error.message == "Custom error message"

    def test_severity_levels(self) -> None:
        """Should convert all severity levels correctly."""
        for severity in [ErrorSeverity.WARNING, ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]:
            error = CalculationError(
                code="TEST",
                message="Test",
                severity=severity,
                category=ErrorCategory.CALCULATION,
            )
            api_error = convert_to_api_error(error)
            assert api_error.severity == severity.value

    def test_category_display_names(self) -> None:
        """Should use display names for categories."""
        category_tests = [
            (ErrorCategory.DATA_QUALITY, "Data Quality"),
            (ErrorCategory.BUSINESS_RULE, "Business Rule"),
            (ErrorCategory.CRM, "Credit Risk Mitigation"),
            (ErrorCategory.HIERARCHY, "Hierarchy"),
        ]
        for category, expected_display in category_tests:
            error = CalculationError(
                code="TEST",
                message="Test",
                severity=ErrorSeverity.ERROR,
                category=category,
            )
            api_error = convert_to_api_error(error)
            assert api_error.category == expected_display


# =============================================================================
# convert_errors Tests
# =============================================================================


class TestConvertErrors:
    """Tests for convert_errors function."""

    def test_empty_list(self) -> None:
        """Should handle empty list."""
        result = convert_errors([])
        assert result == []

    def test_single_error(self, sample_calculation_error: CalculationError) -> None:
        """Should convert single error."""
        result = convert_errors([sample_calculation_error])
        assert len(result) == 1
        assert isinstance(result[0], APIError)

    def test_multiple_errors(
        self,
        sample_calculation_error: CalculationError,
        detailed_calculation_error: CalculationError,
    ) -> None:
        """Should convert multiple errors."""
        result = convert_errors([sample_calculation_error, detailed_calculation_error])
        assert len(result) == 2
        assert all(isinstance(e, APIError) for e in result)


# =============================================================================
# create_api_error Tests
# =============================================================================


class TestCreateApiError:
    """Tests for create_api_error factory function."""

    def test_basic_error(self) -> None:
        """Should create basic error with required fields."""
        error = create_api_error(
            code="TEST001",
            message="Test error message",
        )
        assert error.code == "TEST001"
        assert error.message == "Test error message"
        assert error.severity == "error"
        assert error.category == "Calculation"

    def test_custom_severity_and_category(self) -> None:
        """Should accept custom severity and category."""
        error = create_api_error(
            code="TEST001",
            message="Test",
            severity="warning",
            category="Custom Category",
        )
        assert error.severity == "warning"
        assert error.category == "Custom Category"

    def test_with_details(self) -> None:
        """Should include details in error."""
        error = create_api_error(
            code="TEST001",
            message="Test",
            exposure_reference="EXP001",
            field_name="amount",
        )
        assert error.details["exposure_reference"] == "EXP001"
        assert error.details["field_name"] == "amount"

    def test_filters_none_values(self) -> None:
        """Should filter out None values from details."""
        error = create_api_error(
            code="TEST001",
            message="Test",
            exposure_reference="EXP001",
            field_name=None,
        )
        assert "exposure_reference" in error.details
        assert "field_name" not in error.details


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestCreateValidationError:
    """Tests for create_validation_error function."""

    def test_basic_validation_error(self) -> None:
        """Should create basic validation error."""
        error = create_validation_error("Validation failed")
        assert error.code == "VAL001"
        assert error.message == "Validation failed"
        assert error.severity == "error"
        assert error.category == "Validation"

    def test_with_path(self) -> None:
        """Should include path in details."""
        error = create_validation_error("File not found", path="/path/to/file")
        assert error.details["path"] == "/path/to/file"


class TestCreateFileNotFoundError:
    """Tests for create_file_not_found_error function."""

    def test_file_not_found_error(self) -> None:
        """Should create file not found error."""
        error = create_file_not_found_error("/path/to/missing.parquet")
        assert error.code == "VAL002"
        assert "/path/to/missing.parquet" in error.message
        assert error.details["path"] == "/path/to/missing.parquet"


class TestCreateLoadError:
    """Tests for create_load_error function."""

    def test_basic_load_error(self) -> None:
        """Should create basic load error."""
        error = create_load_error("Database connection failed")
        assert error.code == "LOAD001"
        assert "Database connection failed" in error.message
        assert error.severity == "critical"

    def test_with_source(self) -> None:
        """Should include source in details."""
        error = create_load_error("Parse error", source="facilities.parquet")
        assert error.details["source"] == "facilities.parquet"
