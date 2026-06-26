"""
Error handling contracts for RWA calculator.

Provides structured error representation using the Result pattern:
- CalculationError: Immutable error details with regulatory references

This approach enables:
- Error accumulation without exceptions (process all exposures)
- Full audit trail of issues encountered
- Regulatory reference tracking for compliance reporting
- Severity-based filtering for reporting and alerting
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

if TYPE_CHECKING:
    from pathlib import Path


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

    def to_dict(self) -> dict[str, str | None]:
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
ERROR_OPTIONAL_FILE_UNREADABLE = "DQ007"
ERROR_BEEL_ON_NON_DEFAULTED_EXPOSURE = "DQ008"

# Hierarchy error codes
ERROR_CIRCULAR_HIERARCHY = "HIE001"
ERROR_MISSING_PARENT = "HIE002"
ERROR_HIERARCHY_DEPTH = "HIE003"

# Classification error codes
ERROR_UNKNOWN_EXPOSURE_CLASS = "CLS001"
ERROR_APPROACH_NOT_PERMITTED = "CLS002"
ERROR_MISSING_RATING = "CLS003"
ERROR_QRRE_COLUMNS_MISSING = "CLS004"
ERROR_RETAIL_POOL_MGMT_MISSING = "CLS005"
ERROR_MODEL_PERMISSION_UNMATCHED = "CLS006"
ERROR_FSE_COLUMN_MISSING = "CLS007"
ERROR_LARGE_CORP_REVENUE_NULL = "CLS008"

# CRM error codes
ERROR_INELIGIBLE_COLLATERAL = "CRM001"
ERROR_MATURITY_MISMATCH = "CRM002"
ERROR_CURRENCY_MISMATCH = "CRM003"
ERROR_COLLATERAL_OVERALLOCATION = "CRM004"
ERROR_INVALID_GUARANTEE = "CRM005"
ERROR_AIRB_MODEL_COLLATERAL_MISDIRECTED = "CRM006"
ERROR_LOOK_THROUGH_APPLIED = "CRM007"
ERROR_LOOK_THROUGH_NOT_IMPLEMENTED = "CRM008"
# Collateral-links (M:N collateral-to-beneficiary) referential integrity
ERROR_COLLATERAL_LINK_UNKNOWN_COLLATERAL = "CRM009"
ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY = "CRM010"
ERROR_COLLATERAL_LINK_DUPLICATE = "CRM011"

# IRB error codes
ERROR_PD_OUT_OF_RANGE = "IRB001"
ERROR_LGD_OUT_OF_RANGE = "IRB002"
ERROR_MATURITY_INVALID = "IRB003"
ERROR_MISSING_PD = "IRB004"
ERROR_MISSING_LGD = "IRB005"
ERROR_MISSING_EXPECTED_LOSS = "IRB006"

# SA error codes
ERROR_INVALID_CQS = "SA001"
ERROR_MISSING_RISK_WEIGHT = "SA002"
ERROR_INVALID_LTV = "SA003"
ERROR_DUE_DILIGENCE_NOT_PERFORMED = "SA004"
ERROR_EQUITY_IN_MAIN_TABLE = "SA005"

# Supporting factor error codes
ERROR_SME_MISSING_COUNTERPARTY_REF = "SF001"

# Real estate loan-splitter error codes (CRR Art. 125/126, B3.1 Art. 124F/H)
ERROR_RE_NON_ELIGIBLE_COLLATERAL = "RE001"
ERROR_RE_ZERO_EFFECTIVE_CAP = "RE002"
ERROR_RE_MIXED_PROPERTY_TYPES = "RE003"
ERROR_RE_CRR_RENTAL_COVERAGE_FAILED = "RE004"

# Securitisation allocator validation codes (phase 1: flag + exclude).
# References: CRR Art. 109, Art. 244-246 (significant risk transfer);
# PRA PS1/26 Art. 147A(1)(j).
ERROR_SEC_OVER_ALLOCATED = "SEC001"
ERROR_SEC_INVALID_PCT = "SEC002"
ERROR_SEC_UNKNOWN_REFERENCE = "SEC003"
ERROR_SEC_DUPLICATE = "SEC004"
ERROR_SEC_FULLY_SECURITISED = "SEC005"

# Configuration error codes
ERROR_INVALID_CONFIG = "CFG001"
ERROR_MISSING_PERMISSION = "CFG002"

# Aggregated output bound error codes (validate_aggregated_bundle)
ERROR_RW_ABOVE_CAP = "OUT001"
ERROR_RW_NEGATIVE = "OUT002"
ERROR_RWA_NEGATIVE = "OUT003"
ERROR_EAD_NULL = "OUT004"

# Parallel-run reconciliation error codes (legacy-vs-ours comparison).
# Non-fatal: reconciliation degrades gracefully (skips the affected
# component/column) and records the issue rather than aborting.
ERROR_RECON_LEGACY_COLUMN_MISSING = "REC001"
ERROR_RECON_DUPLICATE_LEGACY_KEY = "REC002"
ERROR_RECON_KEY_COLUMN_MISSING = "REC003"
ERROR_RECON_GRAIN_HETEROGENEOUS = "REC004"
# Every key is one-sided: the legacy and our key columns share no values, so the
# join matched nothing (almost always a key-mapping mistake, not a real break).
ERROR_RECON_NO_KEY_OVERLAP = "REC005"
# Our side carries non-finite (NaN / inf) values: a single one poisons the
# portfolio total and the tie-out, blanking "ours" even though most rows are fine.
ERROR_RECON_NON_FINITE_VALUE = "REC006"


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


def classification_warning(
    code: str,
    message: str,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a classification-related warning."""
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CLASSIFICATION,
        regulatory_reference=regulatory_reference,
    )


def securitisation_warning(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
    severity: ErrorSeverity = ErrorSeverity.WARNING,
) -> CalculationError:
    """Create a securitisation-allocator informational warning or error.

    Used by the SecuritisationAllocator stage to surface validation issues
    on the user-supplied ``securitisation_allocations`` input table:
    over-allocation (sum > 1), invalid pct, orphan exposure_reference,
    duplicate (exposure, pool) pair, or fully securitised exposure.

    References:
    - CRR Art. 109, Art. 244-246
    - PRA PS1/26 Art. 147A(1)(j)
    """
    return CalculationError(
        code=code,
        message=message,
        severity=severity,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
    )


def re_split_warning(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a real estate loan-splitter informational warning.

    Used by the RealEstateSplitter stage to surface decisions that
    diverge from the default split path: ineligible RE collateral,
    zero effective cap after prior-charge reduction, mixed
    residential / commercial allocation, and CRR CRE rental coverage
    failure (Art. 126(2)(d)).
    """
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CLASSIFICATION,
        exposure_reference=exposure_reference,
        regulatory_reference=regulatory_reference,
    )


def beel_on_non_defaulted_exposure_warning(*, n: int) -> CalculationError:
    """Create a DQ008 warning for the (is_defaulted=False ∧ beel>0) contradiction.

    PS1/26 Art. 181(1)(h)(ii) and CRR Art. 158(5) define BEEL only for
    defaulted exposures. When a firm's A-IRB pipeline populates ``beel``
    alongside ``lgd`` on performing rows, the engine does NOT silently
    promote those rows to defaulted; instead it routes them through the
    standard performing branch and emits a single aggregate warning
    carrying the total count of offending exposures, mirroring the
    CLS006 / CLS008 roll-up pattern used by every other classifier-stage
    warning. The value is unused downstream — IRB defaulted treatment
    only reads ``beel`` when ``is_defaulted`` is True.
    """
    return CalculationError(
        code=ERROR_BEEL_ON_NON_DEFAULTED_EXPOSURE,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"BEEL populated on {n} non-defaulted exposure(s); "
            "BEEL is defined only for defaulted exposures under "
            "PS1/26 Art. 181(1)(h)(ii) / CRR Art. 158(5). "
            "Value will not be consumed on these rows."
        ),
        regulatory_reference="PS1/26 Art. 181(1)(h)(ii); CRR Art. 158(5)",
        field_name="beel",
    )


def optional_file_load_error(
    *, relative_path: str | Path, field_name: str, exc: Exception
) -> CalculationError:
    """Create a DQ007 warning for an optional input file that could not be loaded.

    Used by the loader's optional-file path: when an optional parquet/CSV
    exists but cannot be read (corrupt bytes, OSError, ComputeError, etc.),
    the loader returns ``None`` for the bundle field and appends one of
    these warnings so the absence is visible in the audit trail rather
    than swallowed silently. Missing files (FileNotFoundError) are not
    reported via this factory — those are the legitimate "not configured"
    case.
    """
    return CalculationError(
        code=ERROR_OPTIONAL_FILE_UNREADABLE,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"Optional input file '{relative_path}' could not be loaded: "
            f"{type(exc).__name__}: {exc}; treating as absent"
        ),
        field_name=field_name,
        actual_value=str(relative_path),
    )


def missing_required_column_error(*, table: str, column: str) -> CalculationError:
    """Create a DQ001 error for a required input column missing at load.

    Used by the loader's edge seal (migration Phase 3): a required column
    absent from an input table is injected as a typed-null column so the
    pipeline can continue with the rows that survive downstream null
    handling, and one of these errors records the gap. This implements
    the ``ColumnSpec.required`` contract that was previously documentary
    only.
    """
    return CalculationError(
        code=ERROR_MISSING_FIELD,
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.SCHEMA_VALIDATION,
        message=(
            f"Required column '{column}' missing from input table '{table}'; "
            "injected as typed nulls — affected calculations will degrade "
            "per downstream null semantics"
        ),
        field_name=column,
        actual_value=table,
    )


def reconciliation_warning(
    code: str,
    message: str,
    *,
    field_name: str | None = None,
    actual_value: str | None = None,
) -> CalculationError:
    """Create a non-fatal parallel-run reconciliation warning.

    Reconciliation never aborts on a data issue — a missing mapped column, a
    duplicate legacy key, or a heterogeneous aggregation grain degrades the
    affected component/row and is recorded here so the problem is visible in the
    reconciliation report rather than silently swallowed. Use one of the
    ``ERROR_RECON_*`` codes.
    """
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        field_name=field_name,
        actual_value=actual_value,
    )
