"""
Schema validation functions for RWA calculator.

Provides utilities for validating LazyFrame schemas against
expected definitions without materializing data. This enables
early detection of schema mismatches at pipeline boundaries.

Key functions:
- validate_schema: Check LazyFrame schema against expected types
- validate_required_columns: Check for required columns
- validate_bundle_schemas: Validate all frames in a bundle
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_MISSING_FIELD,
    ERROR_TYPE_MISMATCH,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import (
        ClassifiedExposuresBundle,
        CRMAdjustedBundle,
        RawDataBundle,
        ResolvedHierarchyBundle,
    )


def validate_schema(
    lf: pl.LazyFrame,
    expected_schema: dict[str, pl.DataType],
    context: str = "",
    strict: bool = False,
) -> list[str]:
    """
    Validate LazyFrame schema against expected schema.

    Checks that all expected columns exist with correct types.
    Does NOT materialize the LazyFrame.

    Args:
        lf: LazyFrame to validate
        expected_schema: Dict mapping column names to expected Polars types
        context: Context string for error messages (e.g., "facilities")
        strict: If True, also flag extra columns not in expected schema

    Returns:
        List of validation error messages (empty if valid)

    Example:
        >>> errors = validate_schema(
        ...     facilities_lf,
        ...     FACILITY_SCHEMA,
        ...     context="facilities"
        ... )
        >>> if errors:
        ...     print("\\n".join(errors))
    """
    errors: list[str] = []
    actual_schema = lf.collect_schema()
    context_prefix = f"[{context}] " if context else ""

    # Check for missing columns
    for col_name, expected_type in expected_schema.items():
        if col_name not in actual_schema:
            errors.append(
                f"{context_prefix}Missing column: '{col_name}' "
                f"(expected type: {expected_type})"
            )
        else:
            actual_type = actual_schema[col_name]
            if not _types_compatible(actual_type, expected_type):
                errors.append(
                    f"{context_prefix}Type mismatch for '{col_name}': "
                    f"expected {expected_type}, got {actual_type}"
                )

    # Check for unexpected columns (if strict mode)
    if strict:
        extra_columns = set(actual_schema.names()) - set(expected_schema.keys())
        for col_name in extra_columns:
            errors.append(
                f"{context_prefix}Unexpected column: '{col_name}' "
                f"(type: {actual_schema[col_name]})"
            )

    return errors


def _types_compatible(actual: pl.DataType, expected: pl.DataType) -> bool:
    """
    Check if actual type is compatible with expected type.

    Allows some flexibility for compatible types (e.g., Int32 -> Int64).
    """
    # Exact match
    if actual == expected:
        return True

    # Allow integer type promotions
    int_types = {pl.Int8, pl.Int16, pl.Int32, pl.Int64}
    if actual in int_types and expected in int_types:
        return True

    # Allow float type promotions
    float_types = {pl.Float32, pl.Float64}
    if actual in float_types and expected in float_types:
        return True

    # Allow Utf8/String compatibility
    string_types = {pl.Utf8, pl.String}
    if actual in string_types and expected in string_types:
        return True

    return False


def validate_required_columns(
    lf: pl.LazyFrame,
    required_columns: list[str],
    context: str = "",
) -> list[str]:
    """
    Validate that required columns are present in LazyFrame.

    Does not check types, only presence.

    Args:
        lf: LazyFrame to validate
        required_columns: List of column names that must be present
        context: Context string for error messages

    Returns:
        List of missing column names (empty if all present)
    """
    actual_columns = set(lf.collect_schema().names())
    missing = [col for col in required_columns if col not in actual_columns]

    context_prefix = f"[{context}] " if context else ""
    return [f"{context_prefix}Missing required column: '{col}'" for col in missing]


def validate_schema_to_errors(
    lf: pl.LazyFrame,
    expected_schema: dict[str, pl.DataType],
    context: str = "",
) -> list[CalculationError]:
    """
    Validate schema and return CalculationError objects.

    Same as validate_schema but returns structured errors.

    Args:
        lf: LazyFrame to validate
        expected_schema: Dict mapping column names to expected Polars types
        context: Context string for error messages

    Returns:
        List of CalculationError objects for any schema issues
    """
    errors: list[CalculationError] = []
    actual_schema = lf.collect_schema()

    for col_name, expected_type in expected_schema.items():
        if col_name not in actual_schema:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_FIELD,
                    message=f"Missing column '{col_name}' in {context}",
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.SCHEMA_VALIDATION,
                    field_name=col_name,
                    expected_value=str(expected_type),
                )
            )
        else:
            actual_type = actual_schema[col_name]
            if not _types_compatible(actual_type, expected_type):
                errors.append(
                    CalculationError(
                        code=ERROR_TYPE_MISMATCH,
                        message=f"Type mismatch for '{col_name}' in {context}",
                        severity=ErrorSeverity.ERROR,
                        category=ErrorCategory.SCHEMA_VALIDATION,
                        field_name=col_name,
                        expected_value=str(expected_type),
                        actual_value=str(actual_type),
                    )
                )

    return errors


def validate_raw_data_bundle(
    bundle: RawDataBundle,
    schemas: dict[str, dict[str, pl.DataType]],
) -> list[CalculationError]:
    """
    Validate all LazyFrames in a RawDataBundle against expected schemas.

    Args:
        bundle: RawDataBundle to validate
        schemas: Dict mapping bundle attribute names to expected schemas

    Returns:
        List of CalculationError objects for any schema issues
    """
    all_errors: list[CalculationError] = []

    frame_mapping = {
        "facilities": bundle.facilities,
        "loans": bundle.loans,
        "contingents": bundle.contingents,
        "counterparties": bundle.counterparties,
        "collateral": bundle.collateral,
        "guarantees": bundle.guarantees,
        "provisions": bundle.provisions,
        "ratings": bundle.ratings,
        "facility_mappings": bundle.facility_mappings,
        "org_mappings": bundle.org_mappings,
        "lending_mappings": bundle.lending_mappings,
    }

    for name, lf in frame_mapping.items():
        if name in schemas:
            errors = validate_schema_to_errors(lf, schemas[name], context=name)
            all_errors.extend(errors)

    return all_errors


def validate_resolved_hierarchy_bundle(
    bundle: ResolvedHierarchyBundle,
    expected_columns: list[str],
) -> list[CalculationError]:
    """
    Validate ResolvedHierarchyBundle has expected hierarchy columns.

    Args:
        bundle: ResolvedHierarchyBundle to validate
        expected_columns: List of column names expected in exposures frame

    Returns:
        List of CalculationError objects for any issues
    """
    errors: list[CalculationError] = []

    # Check exposures frame has hierarchy columns
    missing = validate_required_columns(
        bundle.exposures,
        expected_columns,
        context="resolved_exposures",
    )
    for msg in missing:
        errors.append(
            CalculationError(
                code=ERROR_MISSING_FIELD,
                message=msg,
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.SCHEMA_VALIDATION,
            )
        )

    return errors


def validate_classified_bundle(
    bundle: ClassifiedExposuresBundle,
    expected_columns: list[str],
) -> list[CalculationError]:
    """
    Validate ClassifiedExposuresBundle has expected classification columns.

    Args:
        bundle: ClassifiedExposuresBundle to validate
        expected_columns: List of column names expected in classified frames

    Returns:
        List of CalculationError objects for any issues
    """
    errors: list[CalculationError] = []

    for frame_name, lf in [
        ("all_exposures", bundle.all_exposures),
        ("sa_exposures", bundle.sa_exposures),
        ("irb_exposures", bundle.irb_exposures),
    ]:
        missing = validate_required_columns(lf, expected_columns, context=frame_name)
        for msg in missing:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_FIELD,
                    message=msg,
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.SCHEMA_VALIDATION,
                )
            )

    return errors


def validate_crm_adjusted_bundle(
    bundle: CRMAdjustedBundle,
    expected_columns: list[str],
) -> list[CalculationError]:
    """
    Validate CRMAdjustedBundle has expected CRM-related columns.

    Args:
        bundle: CRMAdjustedBundle to validate
        expected_columns: List of column names expected

    Returns:
        List of CalculationError objects for any issues
    """
    errors: list[CalculationError] = []

    for frame_name, lf in [
        ("exposures", bundle.exposures),
        ("sa_exposures", bundle.sa_exposures),
        ("irb_exposures", bundle.irb_exposures),
    ]:
        missing = validate_required_columns(lf, expected_columns, context=frame_name)
        for msg in missing:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_FIELD,
                    message=msg,
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.SCHEMA_VALIDATION,
                )
            )

    return errors


# =============================================================================
# BUSINESS RULE VALIDATORS
# =============================================================================


def validate_non_negative_amounts(
    lf: pl.LazyFrame,
    amount_columns: list[str],
    context: str = "",
) -> pl.LazyFrame:
    """
    Add validation expressions for non-negative amount columns.

    Returns a LazyFrame with validation flag columns added.
    Does NOT collect/materialize.

    Args:
        lf: LazyFrame to validate
        amount_columns: List of columns that should be non-negative
        context: Context for naming validation columns

    Returns:
        LazyFrame with _valid_{col} columns added
    """
    exprs = []
    for col in amount_columns:
        if col in lf.collect_schema().names():
            valid_col = f"_valid_{col}"
            exprs.append(
                (pl.col(col) >= 0).alias(valid_col)
            )

    if exprs:
        return lf.with_columns(exprs)
    return lf


def validate_pd_range(
    lf: pl.LazyFrame,
    pd_column: str = "pd",
    min_pd: float = 0.0,
    max_pd: float = 1.0,
) -> pl.LazyFrame:
    """
    Add validation expression for PD range [0, 1].

    Args:
        lf: LazyFrame to validate
        pd_column: Name of PD column
        min_pd: Minimum valid PD (default 0)
        max_pd: Maximum valid PD (default 1)

    Returns:
        LazyFrame with _valid_pd column added
    """
    if pd_column in lf.collect_schema().names():
        return lf.with_columns(
            ((pl.col(pd_column) >= min_pd) & (pl.col(pd_column) <= max_pd))
            .alias("_valid_pd")
        )
    return lf


def validate_lgd_range(
    lf: pl.LazyFrame,
    lgd_column: str = "lgd",
    min_lgd: float = 0.0,
    max_lgd: float = 1.25,  # Can exceed 1.0 in some cases
) -> pl.LazyFrame:
    """
    Add validation expression for LGD range.

    Args:
        lf: LazyFrame to validate
        lgd_column: Name of LGD column
        min_lgd: Minimum valid LGD (default 0)
        max_lgd: Maximum valid LGD (default 1.25)

    Returns:
        LazyFrame with _valid_lgd column added
    """
    if lgd_column in lf.collect_schema().names():
        return lf.with_columns(
            ((pl.col(lgd_column) >= min_lgd) & (pl.col(lgd_column) <= max_lgd))
            .alias("_valid_lgd")
        )
    return lf


# =============================================================================
# RISK TYPE AND CCF VALIDATORS
# =============================================================================

# Valid risk type codes (short form)
VALID_RISK_TYPE_CODES = {"fr", "mr", "mlr", "lr"}

# Valid risk type full values
VALID_RISK_TYPES = {"full_risk", "medium_risk", "medium_low_risk", "low_risk"}

# Mapping from codes to full values
RISK_TYPE_CODE_TO_VALUE = {
    "fr": "full_risk",
    "mr": "medium_risk",
    "mlr": "medium_low_risk",
    "lr": "low_risk",
}


def validate_risk_type(
    lf: pl.LazyFrame,
    column: str = "risk_type",
) -> pl.LazyFrame:
    """
    Add validation expression for risk_type values.

    Validates that risk_type is one of:
    - Codes: FR, MR, MLR, LR (case insensitive)
    - Full values: full_risk, medium_risk, medium_low_risk, low_risk

    Args:
        lf: LazyFrame to validate
        column: Name of risk_type column

    Returns:
        LazyFrame with _valid_risk_type column added
    """
    if column not in lf.collect_schema().names():
        return lf

    # Create combined set of valid values (both codes and full values)
    all_valid = VALID_RISK_TYPE_CODES | VALID_RISK_TYPES

    return lf.with_columns(
        pl.col(column)
        .str.to_lowercase()
        .is_in(all_valid)
        .alias("_valid_risk_type")
    )


def validate_ccf_modelled(
    lf: pl.LazyFrame,
    column: str = "ccf_modelled",
    min_ccf: float = 0.0,
    max_ccf: float = 1.5,
) -> pl.LazyFrame:
    """
    Add validation expression for ccf_modelled range.

    Validates that ccf_modelled is in range [0.0, 1.5] when present.
    Null values are considered valid (the field is optional).

    Note: Retail IRB CCFs can exceed 100% due to additional drawdown
    behaviour (borrowers may draw more than committed amounts during
    stress). A cap of 150% is applied as a reasonable upper bound.

    Args:
        lf: LazyFrame to validate
        column: Name of ccf_modelled column
        min_ccf: Minimum valid CCF (default 0.0)
        max_ccf: Maximum valid CCF (default 1.5, allowing for Retail IRB)

    Returns:
        LazyFrame with _valid_ccf_modelled column added
    """
    if column not in lf.collect_schema().names():
        return lf

    return lf.with_columns(
        pl.when(pl.col(column).is_null())
        .then(pl.lit(True))  # Null is valid (optional field)
        .otherwise(
            (pl.col(column) >= min_ccf) & (pl.col(column) <= max_ccf)
        )
        .alias("_valid_ccf_modelled")
    )


def normalize_risk_type(
    lf: pl.LazyFrame,
    column: str = "risk_type",
) -> pl.LazyFrame:
    """
    Normalize risk_type codes to full values.

    Converts short codes (FR, MR, MLR, LR) to full values
    (full_risk, medium_risk, medium_low_risk, low_risk).
    Values already in full form are preserved.

    Args:
        lf: LazyFrame with risk_type column
        column: Name of risk_type column

    Returns:
        LazyFrame with normalized risk_type values
    """
    if column not in lf.collect_schema().names():
        return lf

    # Normalize to lowercase first, then map codes to full values
    return lf.with_columns(
        pl.col(column)
        .str.to_lowercase()
        .replace(RISK_TYPE_CODE_TO_VALUE)
        .alias(column)
    )
