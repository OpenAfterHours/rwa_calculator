"""Tests for error handling contracts.

Tests the CalculationError class,
including error accumulation and filtering.
"""

import pytest

from rwa_calc.contracts.errors import (
    ERROR_INVALID_VALUE,
    ERROR_MISSING_FIELD,
    CalculationError,
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
