"""
Error conversion utilities for RWA Calculator API.

convert_to_api_error: Converts internal CalculationError to user-friendly APIError
convert_errors: Batch conversion of error lists
create_api_error: Factory function for creating APIError instances

Provides user-friendly error messages and categorization for UI display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rwa_calc.api.models import APIError

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError


# =============================================================================
# User-Friendly Error Messages
# =============================================================================


ERROR_MESSAGE_OVERRIDES: dict[str, str] = {
    "DQ001": "Required field is missing from the input data",
    "DQ002": "Field contains an invalid value",
    "DQ003": "Field has incorrect data type",
    "DQ004": "Duplicate key found in data",
    "DQ005": "Reference points to non-existent record",
    "HIE001": "Circular reference detected in hierarchy",
    "HIE002": "Parent record not found in hierarchy",
    "HIE003": "Hierarchy exceeds maximum depth",
    "CLS001": "Unable to determine exposure class",
    "CLS002": "Approach not permitted for exposure class",
    "CLS003": "Missing credit rating for exposure",
    "CRM001": "Collateral is not eligible for credit risk mitigation",
    "CRM002": "Collateral maturity is less than exposure maturity",
    "CRM003": "Currency mismatch between collateral and exposure",
    "CRM004": "Collateral allocated exceeds available amount",
    "CRM005": "Guarantee does not meet eligibility criteria",
    "IRB001": "PD value is outside valid range (0% - 100%)",
    "IRB002": "LGD value is outside valid range (0% - 100%)",
    "IRB003": "Maturity value is invalid",
    "IRB004": "Required PD value is missing",
    "IRB005": "Required LGD value is missing",
    "SA001": "Invalid Credit Quality Step for exposure",
    "SA002": "Cannot determine risk weight for exposure",
    "SA003": "Invalid LTV ratio for real estate exposure",
    "CFG001": "Invalid configuration parameter",
    "CFG002": "IRB permission not granted for exposure class",
}


CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "data_quality": "Data Quality",
    "business_rule": "Business Rule",
    "schema_validation": "Schema Validation",
    "configuration": "Configuration",
    "calculation": "Calculation",
    "hierarchy": "Hierarchy",
    "crm": "Credit Risk Mitigation",
}


# =============================================================================
# Conversion Functions
# =============================================================================


def convert_to_api_error(error: CalculationError) -> APIError:
    """
    Convert internal CalculationError to user-friendly APIError.

    Transforms technical error details into format suitable for
    UI display and end-user comprehension.

    Args:
        error: Internal CalculationError from calculation pipeline

    Returns:
        APIError with user-friendly message and details
    """
    message = _get_user_friendly_message(error)
    severity = error.severity.value if hasattr(error.severity, "value") else str(error.severity)
    category = error.category.value if hasattr(error.category, "value") else str(error.category)

    details = _build_error_details(error)

    return APIError(
        code=error.code,
        message=message,
        severity=severity,
        category=CATEGORY_DISPLAY_NAMES.get(category, category),
        details=details,
    )


def convert_errors(errors: list[CalculationError]) -> list[APIError]:
    """
    Convert a list of CalculationErrors to APIErrors.

    Args:
        errors: List of internal CalculationError instances

    Returns:
        List of user-friendly APIError instances
    """
    return [convert_to_api_error(error) for error in errors]


def create_api_error(
    code: str,
    message: str,
    severity: str = "error",
    category: str = "Calculation",
    **details: str | None,
) -> APIError:
    """
    Factory function to create APIError with optional details.

    Args:
        code: Error code
        message: Error message
        severity: Error severity (warning, error, critical)
        category: Error category
        **details: Additional context (exposure_reference, field_name, etc.)

    Returns:
        APIError instance
    """
    filtered_details = {k: v for k, v in details.items() if v is not None}
    return APIError(
        code=code,
        message=message,
        severity=severity,
        category=category,
        details=filtered_details,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _get_user_friendly_message(error: CalculationError) -> str:
    """
    Get user-friendly message for an error.

    Uses override if available, otherwise falls back to original message.
    """
    base_message = ERROR_MESSAGE_OVERRIDES.get(error.code, error.message)

    context_parts = []
    if error.exposure_reference:
        context_parts.append(f"Exposure: {error.exposure_reference}")
    if error.field_name:
        context_parts.append(f"Field: {error.field_name}")
    if error.actual_value and error.expected_value:
        context_parts.append(f"Expected {error.expected_value}, got {error.actual_value}")

    if context_parts:
        return f"{base_message} ({', '.join(context_parts)})"
    return base_message


def _build_error_details(error: CalculationError) -> dict:
    """
    Build details dictionary from error attributes.

    Only includes non-None values to keep details clean.
    """
    details = {}

    if error.exposure_reference:
        details["exposure_reference"] = error.exposure_reference
    if error.counterparty_reference:
        details["counterparty_reference"] = error.counterparty_reference
    if error.regulatory_reference:
        details["regulatory_reference"] = error.regulatory_reference
    if error.field_name:
        details["field_name"] = error.field_name
    if error.expected_value:
        details["expected_value"] = error.expected_value
    if error.actual_value:
        details["actual_value"] = error.actual_value

    return details


def create_validation_error(message: str, path: str | None = None) -> APIError:
    """
    Create an error for data validation failures.

    Args:
        message: Error message
        path: Optional file path

    Returns:
        APIError for validation failure
    """
    details = {"path": path} if path else {}
    return APIError(
        code="VAL001",
        message=message,
        severity="error",
        category="Validation",
        details=details,
    )


def create_file_not_found_error(file_path: str) -> APIError:
    """
    Create an error for missing required file.

    Args:
        file_path: Path to missing file

    Returns:
        APIError for missing file
    """
    return APIError(
        code="VAL002",
        message=f"Required file not found: {file_path}",
        severity="error",
        category="Validation",
        details={"path": file_path},
    )


def create_load_error(message: str, source: str | None = None) -> APIError:
    """
    Create an error for data loading failures.

    Args:
        message: Error message
        source: Optional source file/table

    Returns:
        APIError for load failure
    """
    details = {"source": source} if source else {}
    return APIError(
        code="LOAD001",
        message=f"Failed to load data: {message}",
        severity="critical",
        category="Data Loading",
        details=details,
    )
