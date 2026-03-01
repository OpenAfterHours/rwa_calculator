"""Tests for error handling contracts.

Tests the CalculationError and LazyFrameResult classes,
including error accumulation and filtering.
"""

import polars as pl
import pytest

from rwa_calc.contracts.errors import (
    ERROR_INVALID_VALUE,
    ERROR_MISSING_FIELD,
    CalculationError,
    LazyFrameResult,
    business_rule_error,
    crm_warning,
    hierarchy_error,
    invalid_value_error,
    missing_field_error,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity


class TestCalculationError:
    """Tests for CalculationError dataclass."""

    def test_create_basic_error(self):
        """Should create error with required fields."""
        error = CalculationError(
            code="TEST001",
            message="Test error message",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
        )

        assert error.code == "TEST001"
        assert error.message == "Test error message"
        assert error.severity == ErrorSeverity.ERROR
        assert error.category == ErrorCategory.DATA_QUALITY

    def test_create_error_with_optional_fields(self):
        """Should create error with optional context fields."""
        error = CalculationError(
            code="CRM001",
            message="Ineligible collateral",
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.CRM,
            exposure_reference="EXP001",
            counterparty_reference="CPTY001",
            regulatory_reference="CRR Art. 197",
            field_name="collateral_type",
            expected_value="financial",
            actual_value="other",
        )

        assert error.exposure_reference == "EXP001"
        assert error.counterparty_reference == "CPTY001"
        assert error.regulatory_reference == "CRR Art. 197"
        assert error.field_name == "collateral_type"
        assert error.expected_value == "financial"
        assert error.actual_value == "other"

    def test_error_immutable(self):
        """CalculationError should be immutable (frozen dataclass)."""
        error = CalculationError(
            code="TEST001",
            message="Test",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
        )

        with pytest.raises(AttributeError):
            error.message = "Changed"

    def test_error_str_representation(self):
        """__str__ should provide human-readable representation."""
        error = CalculationError(
            code="DQ001",
            message="Missing required field",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
            exposure_reference="LOAN001",
            regulatory_reference="CRR Art. 111",
        )

        str_repr = str(error)

        assert "[DQ001]" in str_repr
        assert "ERROR" in str_repr
        assert "Missing required field" in str_repr
        assert "Exposure: LOAN001" in str_repr
        assert "Ref: CRR Art. 111" in str_repr

    def test_error_to_dict(self):
        """to_dict should serialize error to dictionary."""
        error = CalculationError(
            code="TEST001",
            message="Test",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
        )

        error_dict = error.to_dict()

        assert error_dict["code"] == "TEST001"
        assert error_dict["severity"] == "error"
        assert error_dict["category"] == "data_quality"


class TestLazyFrameResult:
    """Tests for LazyFrameResult container."""

    def test_create_result_with_empty_errors(self):
        """Should create result with LazyFrame and no errors."""
        lf = pl.LazyFrame({"col1": [1, 2, 3]})
        result = LazyFrameResult(frame=lf)

        assert result.frame is lf
        assert result.errors == []
        assert result.has_errors is False
        assert result.has_critical_errors is False

    def test_create_result_with_errors(self):
        """Should create result with errors."""
        lf = pl.LazyFrame({"col1": [1, 2, 3]})
        errors = [
            CalculationError(
                code="TEST001",
                message="Test error",
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.DATA_QUALITY,
            )
        ]

        result = LazyFrameResult(frame=lf, errors=errors)

        assert len(result.errors) == 1
        assert result.has_errors is True

    def test_has_critical_errors(self):
        """has_critical_errors should only be True for critical severity."""
        lf = pl.LazyFrame({"col1": [1]})

        # Warning only
        result_warning = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError(
                    code="W001",
                    message="Warning",
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.CRM,
                )
            ],
        )
        assert result_warning.has_critical_errors is False
        assert result_warning.has_errors is False  # Warnings don't count as errors

        # Error only
        result_error = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError(
                    code="E001",
                    message="Error",
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.DATA_QUALITY,
                )
            ],
        )
        assert result_error.has_critical_errors is False
        assert result_error.has_errors is True

        # Critical
        result_critical = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError(
                    code="C001",
                    message="Critical",
                    severity=ErrorSeverity.CRITICAL,
                    category=ErrorCategory.CALCULATION,
                )
            ],
        )
        assert result_critical.has_critical_errors is True
        assert result_critical.has_errors is True

    def test_warnings_property(self):
        """warnings should filter to warning-level only."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError("W1", "Warning 1", ErrorSeverity.WARNING, ErrorCategory.CRM),
                CalculationError("E1", "Error 1", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
                CalculationError("W2", "Warning 2", ErrorSeverity.WARNING, ErrorCategory.CRM),
            ],
        )

        warnings = result.warnings

        assert len(warnings) == 2
        assert all(w.severity == ErrorSeverity.WARNING for w in warnings)

    def test_critical_errors_property(self):
        """critical_errors should filter to critical-level only."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError("W1", "Warning", ErrorSeverity.WARNING, ErrorCategory.CRM),
                CalculationError(
                    "C1", "Critical", ErrorSeverity.CRITICAL, ErrorCategory.CALCULATION
                ),
                CalculationError("E1", "Error", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
            ],
        )

        critical = result.critical_errors

        assert len(critical) == 1
        assert critical[0].code == "C1"

    def test_errors_by_category(self):
        """errors_by_category should filter by category."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError("D1", "Data 1", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
                CalculationError("C1", "CRM 1", ErrorSeverity.WARNING, ErrorCategory.CRM),
                CalculationError("D2", "Data 2", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
            ],
        )

        data_errors = result.errors_by_category(ErrorCategory.DATA_QUALITY)
        crm_errors = result.errors_by_category(ErrorCategory.CRM)

        assert len(data_errors) == 2
        assert len(crm_errors) == 1

    def test_errors_by_exposure(self):
        """errors_by_exposure should filter by exposure reference."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(
            frame=lf,
            errors=[
                CalculationError(
                    "E1",
                    "Error 1",
                    ErrorSeverity.ERROR,
                    ErrorCategory.DATA_QUALITY,
                    exposure_reference="EXP001",
                ),
                CalculationError(
                    "E2",
                    "Error 2",
                    ErrorSeverity.ERROR,
                    ErrorCategory.DATA_QUALITY,
                    exposure_reference="EXP002",
                ),
                CalculationError(
                    "E3",
                    "Error 3",
                    ErrorSeverity.ERROR,
                    ErrorCategory.DATA_QUALITY,
                    exposure_reference="EXP001",
                ),
            ],
        )

        exp001_errors = result.errors_by_exposure("EXP001")

        assert len(exp001_errors) == 2

    def test_add_error(self):
        """add_error should append to errors list."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(frame=lf)

        result.add_error(
            CalculationError("E1", "Error", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY)
        )

        assert len(result.errors) == 1

    def test_add_errors(self):
        """add_errors should extend errors list."""
        lf = pl.LazyFrame({"col1": [1]})
        result = LazyFrameResult(frame=lf)

        result.add_errors(
            [
                CalculationError("E1", "Error 1", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
                CalculationError("E2", "Error 2", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY),
            ]
        )

        assert len(result.errors) == 2

    def test_merge_results(self):
        """merge should combine errors from both results."""
        lf1 = pl.LazyFrame({"col1": [1]})
        lf2 = pl.LazyFrame({"col2": [2]})

        result1 = LazyFrameResult(
            frame=lf1,
            errors=[
                CalculationError("E1", "Error 1", ErrorSeverity.ERROR, ErrorCategory.DATA_QUALITY)
            ],
        )
        result2 = LazyFrameResult(
            frame=lf2,
            errors=[CalculationError("E2", "Error 2", ErrorSeverity.ERROR, ErrorCategory.CRM)],
        )

        merged = result1.merge(result2)

        # Frame from result1 is kept
        assert merged.frame is lf1
        # Errors are combined
        assert len(merged.errors) == 2


class TestErrorFactoryFunctions:
    """Tests for error factory functions."""

    def test_missing_field_error(self):
        """missing_field_error should create correct error."""
        error = missing_field_error(
            field_name="pd",
            exposure_reference="LOAN001",
            regulatory_reference="CRR Art. 163",
        )

        assert error.code == ERROR_MISSING_FIELD
        assert error.severity == ErrorSeverity.ERROR
        assert error.category == ErrorCategory.DATA_QUALITY
        assert error.field_name == "pd"
        assert "pd" in error.message

    def test_invalid_value_error(self):
        """invalid_value_error should create correct error."""
        error = invalid_value_error(
            field_name="cqs",
            actual_value="7",
            expected_value="1-6",
            exposure_reference="LOAN001",
        )

        assert error.code == ERROR_INVALID_VALUE
        assert error.severity == ErrorSeverity.ERROR
        assert error.expected_value == "1-6"
        assert error.actual_value == "7"

    def test_business_rule_error(self):
        """business_rule_error should create correct error."""
        error = business_rule_error(
            code="BR001",
            message="PD exceeds maximum",
            exposure_reference="LOAN001",
            regulatory_reference="CRE30.55",
        )

        assert error.code == "BR001"
        assert error.category == ErrorCategory.BUSINESS_RULE
        assert error.regulatory_reference == "CRE30.55"

    def test_hierarchy_error(self):
        """hierarchy_error should create correct error."""
        error = hierarchy_error(
            code="HIE001",
            message="Circular reference detected",
            counterparty_reference="CPTY001",
        )

        assert error.code == "HIE001"
        assert error.category == ErrorCategory.HIERARCHY
        assert error.counterparty_reference == "CPTY001"

    def test_crm_warning(self):
        """crm_warning should create warning-level error."""
        error = crm_warning(
            code="CRM001",
            message="Collateral maturity mismatch",
            exposure_reference="LOAN001",
        )

        assert error.code == "CRM001"
        assert error.severity == ErrorSeverity.WARNING
        assert error.category == ErrorCategory.CRM
