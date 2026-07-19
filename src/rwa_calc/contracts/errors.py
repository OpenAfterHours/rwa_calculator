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
# Short-term ECAI rating scoped onto an ineligible obligor class
# (CRR/PS1-26 Art. 140(1) / CRE21.16 — short-term assessments are confined to
# institution / corporate obligors). The mis-scoped override is ignored for RW.
ERROR_MISSCOPED_SHORT_TERM_RATING = "DQ009"

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
ERROR_LFSE_ASSETS_NULL = "CLS009"
ERROR_QRRE_GATE_DEMOTION = "CLS010"
ERROR_LARGE_CORP_GROUP_ROLLUP = "CLS011"

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
# Ineligible unfunded credit protection (CRR/PS1-26 Art. 213(1)(c)(i)): a
# guarantee the provider can unilaterally cancel (both regimes) or unilaterally
# change (Basel 3.1 only) is dropped and the exposure flows unguaranteed.
ERROR_INELIGIBLE_UNFUNDED_PROTECTION = "CRM012"
# Ineligible guarantor (CRR/PS1-26 Art. 201(1)(g)/(2)): a corporate guarantor
# without an ECAI credit assessment (or, for an IRB-approach beneficiary, an
# internal rating) is not an eligible protection provider — the covered exposure
# reverts to the borrower's own basis.
ERROR_INELIGIBLE_GUARANTOR = "CRM013"
# Ineligible IRB/FCM non-financial collateral (CRR/PS1-26 Art. 199(2)/(5)/(6)):
# real-estate / receivables / other-physical collateral is recognised on the
# FIRB Foundation Collateral Method (LGD* substitution) path only when the
# institution attests eligibility via is_eligible_irb_collateral. An unattested
# row (flag False/unset), or a receivable whose ORIGINAL maturity is populated
# > 1 year (Art. 199(5)), is zeroed and this warning is raised (one per row).
ERROR_INELIGIBLE_IRB_COLLATERAL = "CRM014"
# Own-issue / connected-issuer collateral (CRR/PS1-26 Art. 194(4)): funded credit
# protection is ineligible where its value is materially positively correlated
# with the obligor's credit quality — the canonical case being a security ISSUED
# by the obligor or a member of the obligor's group (BCBS CRE22). When a
# collateral row's issuer_counterparty_reference resolves to the obligor, or to a
# counterparty sharing the obligor's ultimate parent, the row is zeroed (no CRM
# benefit) and this warning is raised (one per row). Null issuer is permissive.
ERROR_OWN_ISSUE_COLLATERAL = "CRM015"
# Cross-counterparty on-balance-sheet netting (CRR/PS1-26 Art. 195): on-B/S
# netting is limited to mutual claims / reciprocal cash balances between the
# institution and a SINGLE counterparty. A netting_agreement_reference that spans
# more than one counterparty cannot net a deposit from counterparty A against a
# loan to counterparty B; such cross-counterparty offsets are disallowed and this
# warning names the agreement (one per multi-counterparty agreement).
ERROR_CROSS_COUNTERPARTY_NETTING = "CRM016"
# Third-party deposit under FIRB (CRR/PS1-26 Art. 200(a)/232(2), P1.239/P1.240):
# cash on deposit with a third-party institution is "other funded credit
# protection" treated as a guarantee at the holder institution's risk weight.
# The SA risk-weight substitution is implemented; the FIRB analogue is a deferred
# follow-up, so under FIRB such a deposit is conservatively given NO CRM benefit
# (it is excluded from the LGD* collateral input rather than valued at 0% cash)
# and this warning records the pending substitution (one per gated row).
ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED = "CRM017"
# Non-main-index equity collateral eligibility (CRR/PS1-26 Art. 197(1)(f)/198(1)(a),
# P1.271): equities/convertible bonds are eligible financial collateral under all
# methods only when included in a MAIN index (Art. 197(1)(f)); a non-main-index
# equity is eligible only if LISTED on a recognised exchange (Art. 198(1)(a)) and
# then only under the comprehensive method. A collateral row of equity type that is
# neither attested main-index nor attested listed (is_main_index and is_listed both
# False/unset) is ineligible: its value is zeroed, is_eligible_financial_collateral
# is cleared, and this warning is raised (one per gated row).
ERROR_NON_MAIN_INDEX_EQUITY_INELIGIBLE = "CRM018"
# Credit-linked note own-issuance (CRR/PS1-26 Art. 218, P1.274): a credit-linked
# note is treated as cash collateral only when it is ISSUED BY THE LENDING
# institution itself (the note's cash proceeds fund the protection). A CLN that
# is not attested own-issued (is_own_issued_cln False/unset) is not within Art.
# 218 — its value is materially correlated with the reference entity (Art. 194(4)
# wrong-way risk), so it is ineligible funded protection: its value is zeroed,
# is_eligible_financial_collateral is cleared, and this warning is raised (one per
# gated row).
ERROR_CREDIT_LINKED_NOTE_NOT_OWN_ISSUED = "CRM019"
# Life-insurance policy currency unknown (CRR/PS1-26 Art. 232(3) with Art. 233(3),
# P1.275): a pledged life-insurance policy's surrender value is reduced by the 8%
# FX volatility haircut when the policy currency differs from the exposure
# currency. A life-insurance collateral row that carries a currency column but
# leaves it null cannot prove a currency match, so the 8% reduction is applied
# conservatively (the anti-conservative full-benefit treatment is disallowed) and
# this warning is raised (one per row with an unknown policy currency).
ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN = "CRM020"

# IRB error codes
ERROR_PD_OUT_OF_RANGE = "IRB001"
ERROR_LGD_OUT_OF_RANGE = "IRB002"
ERROR_MATURITY_INVALID = "IRB003"
ERROR_MISSING_PD = "IRB004"
ERROR_MISSING_LGD = "IRB005"
ERROR_MISSING_EXPECTED_LOSS = "IRB006"
# Portfolio-level A-IRB retail-RE LGD-floor backstop (CRR Art. 164(4)): the
# EAD-weighted-average own-estimate LGD of an A-IRB retail real-estate book fell
# below the residential 10% / commercial 15% floor. Monitoring WARNING only —
# never an RWA/LGD adjustment.
ERROR_RETAIL_RE_PORTFOLIO_LGD_FLOOR = "IRB007"

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

# Aggregator non-finite output code. A single NaN/inf in a per-row RWA/EAD/RW
# column propagates through Polars ``.sum()`` (NaN is not skipped like null) and
# blanks the portfolio totals and the by-class/by-approach charts. The aggregator
# detects this and surfaces it here so the gap is a visible coded issue rather
# than a silently blank result page.
ERROR_NON_FINITE_OUTPUT = "AGG001"

# Aggregator non-finite IRB input code. A NaN PD/LGD reaching the IRB floors is
# treated as null and raised to the regulatory floor (conservative) — a finite
# result, so it does NOT trip AGG001. This warning surfaces that the input data
# carried a non-finite value rather than letting it be absorbed silently.
ERROR_NON_FINITE_INPUT = "AGG002"

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
# The mapped legacy approach column carries labels that do not resolve to our
# methodology vocabulary (STD / FIRB / AIRB / SLOTTING / EQUITY), so the by-method
# allocation would split the two sides on keys that can never meet.
ERROR_RECON_METHOD_UNRESOLVED = "REC007"

# Cross-template reporting tie-out codes (reporting.tieouts). Non-fatal:
# a break means two independently-generated templates (C 02.00 / C 07.00 /
# C 08.01 / OV1) disagree on a comparable aggregate beyond tolerance. The
# specific tie is carried on the finding's field_name.
ERROR_CROSS_TEMPLATE_INCONSISTENCY = "TIE001"


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


def misscoped_short_term_rating_warning(
    *, exposure_reference: str | None, obligor_entity_type: str | None
) -> CalculationError:
    """Create a DQ009 warning for a short-term ECAI rating on an ineligible class.

    CRR Art. 140(1) / PS1/26 Art. 140(1) (CRE21.16): short-term credit
    assessments may be used only for institution and corporate obligors. A
    short-term rating attached to any other class (e.g. a sovereign) is ignored
    for risk-weight purposes — the exposure reverts to its counterparty-level
    long-term rating — and this warning records the rejected mis-scope. One is
    emitted per mis-scoped exposure (the fixture estate is loan-scoped, so this
    equals one per mis-scoped rating).
    """
    return CalculationError(
        code=ERROR_MISSCOPED_SHORT_TERM_RATING,
        message=(
            f"Short-term ECAI rating on exposure '{exposure_reference}' is scoped "
            f"onto an ineligible obligor class (entity_type '{obligor_entity_type}'); "
            "Art. 140(1) confines short-term assessments to institution / corporate "
            "obligors, so the override is ignored and the exposure reverts to its "
            "counterparty-level rating."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=exposure_reference,
        regulatory_reference="CRR Art. 140(1)",
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


def non_finite_output_error(
    *, column: str, count: int, references: list[str] | None = None
) -> CalculationError:
    """Create an AGG001 error for a non-finite (NaN / inf) per-row output value.

    Raised by the output aggregator when a final RWA / EAD / risk-weight column
    carries a NaN or inf on one or more rows. Polars ``.sum()`` propagates a NaN
    (it is not skipped like a null), so a single poisoned row would otherwise
    blank the portfolio totals and the by-class / by-approach charts. Surfacing
    it as a coded ``error`` (not ``critical``) keeps the run "successful" — the
    unaffected rows still report correctly and are shown — while making the
    excluded rows explicit in the audit trail. ``references`` carries up to a
    handful of the offending ``exposure_reference`` values for triage.
    """
    sample = ""
    if references:
        shown = ", ".join(references)
        sample = f" (e.g. {shown})"
    return CalculationError(
        code=ERROR_NON_FINITE_OUTPUT,
        message=(
            f"{count} exposure(s) produced a non-finite (NaN/inf) value in "
            f"'{column}'{sample}; these rows are excluded from portfolio totals "
            "and the summary charts. Check the IRB inputs (PD/LGD/EAD/maturity) "
            "or guarantee allocation for these exposures."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.CALCULATION,
        field_name=column,
        actual_value=str(count),
    )


def non_finite_input_warning(
    *, column: str, count: int, references: list[str] | None = None
) -> CalculationError:
    """Create an AGG002 warning for a non-finite (NaN/inf) IRB input value.

    Raised by the output aggregator when a raw IRB input column (``pd`` / ``lgd``)
    carries a NaN/inf on one or more rows. The IRB floors treat a NaN as null and
    raise it to the regulatory floor (conservative and finite — so it never trips
    the AGG001 *output* error), which would otherwise absorb the bad input
    silently. This ``warning`` makes the source-data problem visible without
    failing the run. ``references`` carries up to a handful of the affected
    ``exposure_reference`` values.
    """
    sample = ""
    if references:
        shown = ", ".join(references)
        sample = f" (e.g. {shown})"
    return CalculationError(
        code=ERROR_NON_FINITE_INPUT,
        message=(
            f"{count} exposure(s) carried a non-finite (NaN/inf) value in the IRB "
            f"input '{column}'{sample}; it was treated as null and raised to the "
            "regulatory floor where one applies. Check the source PD/LGD data."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        field_name=column,
        actual_value=str(count),
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
