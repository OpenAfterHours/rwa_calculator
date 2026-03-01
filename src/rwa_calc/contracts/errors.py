"""
Error handling contracts for RWA calculator.

Provides structured error representation using the Result pattern:
- CalculationError: Immutable error details with regulatory references
- LazyFrameResult: Combines LazyFrame output with accumulated errors

This approach enables:
- Error accumulation without exceptions (process all exposures)
- Full audit trail of issues encountered
- Regulatory reference tracking for compliance reporting
- Severity-based filtering for reporting and alerting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True)
class CalculationError:
    """
    Immutable representation of a calculation error or warning.

    Attributes:
        code: Unique error code (e.g., "CRM001", "CLASS002")
              Format: {COMPONENT}{NUMBER} where COMPONENT is 2-5 chars
        message: Human-readable description of the issue
        severity: Error severity level (WARNING, ERROR, CRITICAL)
        category: Error category for filtering (DATA_QUALITY, BUSINESS_RULE, etc.)
        exposure_reference: Optional reference to affected exposure
        counterparty_reference: Optional reference to affected counterparty
        regulatory_reference: Optional regulatory article (e.g., "CRR Art. 153")
        field_name: Optional name of the problematic field
        expected_value: Optional description of expected value/format
        actual_value: Optional actual value that caused the error
    """

    code: str
    message: str
    severity: ErrorSeverity
    category: ErrorCategory
    exposure_reference: str | None = None
    counterparty_reference: str | None = None
    regulatory_reference: str | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None

    def __str__(self) -> str:
        """Human-readable error representation."""
        parts = [f"[{self.code}] {self.severity.value.upper()}: {self.message}"]

        if self.exposure_reference:
            parts.append(f"Exposure: {self.exposure_reference}")
        if self.counterparty_reference:
            parts.append(f"Counterparty: {self.counterparty_reference}")
        if self.regulatory_reference:
            parts.append(f"Ref: {self.regulatory_reference}")

        return " | ".join(parts)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "exposure_reference": self.exposure_reference,
            "counterparty_reference": self.counterparty_reference,
            "regulatory_reference": self.regulatory_reference,
            "field_name": self.field_name,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
        }


@dataclass
class LazyFrameResult:
    """
    Result container combining a LazyFrame with accumulated errors.

    Implements the Result pattern for LazyFrame operations, allowing
    errors to be collected without throwing exceptions. This enables
    processing all exposures and reporting all issues.

    Attributes:
        frame: The resulting LazyFrame (may be partial if errors occurred)
        errors: List of errors/warnings encountered during processing

    Usage:
        result = processor.apply_crm(data, config)
        if result.has_critical_errors:
            # Handle critical failures
        else:
            # Continue with result.frame, log result.warnings
    """

    frame: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if any errors (not warnings) occurred."""
        return any(e.severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL) for e in self.errors)

    @property
    def has_critical_errors(self) -> bool:
        """Check if any critical errors occurred."""
        return any(e.severity == ErrorSeverity.CRITICAL for e in self.errors)

    @property
    def warnings(self) -> list[CalculationError]:
        """Get only warning-level issues."""
        return [e for e in self.errors if e.severity == ErrorSeverity.WARNING]

    @property
    def critical_errors(self) -> list[CalculationError]:
        """Get only critical errors."""
        return [e for e in self.errors if e.severity == ErrorSeverity.CRITICAL]

    def errors_by_category(self, category: ErrorCategory) -> list[CalculationError]:
        """Filter errors by category."""
        return [e for e in self.errors if e.category == category]

    def errors_by_exposure(self, exposure_reference: str) -> list[CalculationError]:
        """Get all errors for a specific exposure."""
        return [e for e in self.errors if e.exposure_reference == exposure_reference]

    def add_error(self, error: CalculationError) -> None:
        """Add an error to the result."""
        self.errors.append(error)

    def add_errors(self, errors: list[CalculationError]) -> None:
        """Add multiple errors to the result."""
        self.errors.extend(errors)

    def merge(self, other: LazyFrameResult) -> LazyFrameResult:
        """
        Merge another result's errors into this one.

        Note: Does not modify frames - caller must handle frame combination.
        """
        combined_errors = self.errors + other.errors
        return LazyFrameResult(frame=self.frame, errors=combined_errors)


# =============================================================================
# ERROR CODE CONSTANTS
# =============================================================================

# Data quality error codes
ERROR_MISSING_FIELD = "DQ001"
ERROR_INVALID_VALUE = "DQ002"
ERROR_TYPE_MISMATCH = "DQ003"
ERROR_DUPLICATE_KEY = "DQ004"
ERROR_ORPHAN_REFERENCE = "DQ005"
ERROR_INVALID_COLUMN_VALUE = "DQ006"

# Hierarchy error codes
ERROR_CIRCULAR_HIERARCHY = "HIE001"
ERROR_MISSING_PARENT = "HIE002"
ERROR_HIERARCHY_DEPTH = "HIE003"

# Classification error codes
ERROR_UNKNOWN_EXPOSURE_CLASS = "CLS001"
ERROR_APPROACH_NOT_PERMITTED = "CLS002"
ERROR_MISSING_RATING = "CLS003"

# CRM error codes
ERROR_INELIGIBLE_COLLATERAL = "CRM001"
ERROR_MATURITY_MISMATCH = "CRM002"
ERROR_CURRENCY_MISMATCH = "CRM003"
ERROR_COLLATERAL_OVERALLOCATION = "CRM004"
ERROR_INVALID_GUARANTEE = "CRM005"

# IRB error codes
ERROR_PD_OUT_OF_RANGE = "IRB001"
ERROR_LGD_OUT_OF_RANGE = "IRB002"
ERROR_MATURITY_INVALID = "IRB003"
ERROR_MISSING_PD = "IRB004"
ERROR_MISSING_LGD = "IRB005"

# SA error codes
ERROR_INVALID_CQS = "SA001"
ERROR_MISSING_RISK_WEIGHT = "SA002"
ERROR_INVALID_LTV = "SA003"

# Configuration error codes
ERROR_INVALID_CONFIG = "CFG001"
ERROR_MISSING_PERMISSION = "CFG002"


# =============================================================================
# ERROR FACTORY FUNCTIONS
# =============================================================================


def missing_field_error(
    field_name: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a missing field error."""
    return CalculationError(
        code=ERROR_MISSING_FIELD,
        message=f"Required field '{field_name}' is missing or null",
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
        field_name=field_name,
    )


def invalid_value_error(
    field_name: str,
    actual_value: str,
    expected_value: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create an invalid value error."""
    return CalculationError(
        code=ERROR_INVALID_VALUE,
        message=f"Invalid value for '{field_name}': expected {expected_value}, got {actual_value}",
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
        field_name=field_name,
        expected_value=expected_value,
        actual_value=actual_value,
    )


def business_rule_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
) -> CalculationError:
    """Create a business rule violation error."""
    return CalculationError(
        code=code,
        message=message,
        severity=severity,
        category=ErrorCategory.BUSINESS_RULE,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
    )


def hierarchy_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    counterparty_reference: str | None = None,
) -> CalculationError:
    """Create a hierarchy-related error."""
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.HIERARCHY,
        exposure_reference=exposure_reference,
        counterparty_reference=counterparty_reference,
    )


def crm_warning(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a CRM-related warning."""
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CRM,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
    )
