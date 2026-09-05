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
# RESERVED — no producer. Its sole emitter (``validate_schema_to_errors``) was
# deleted as unfirable: it ran DOWNSTREAM of the loader edge seal, where every
# declared column has already been cast to its declared dtype. Kept reserved
# rather than recycled so old audit records stay readable; the same finding
# taken UPSTREAM of that cast, where it does fire, is DQ014.
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
# An unsolicited ECAI credit assessment supplied on a rating row. CRR / PS1-26
# Art. 138 chapeau: an institution "shall use solicited credit assessments.
# However it may use unsolicited credit assessments if the competent authority
# has confirmed that unsolicited credit assessments of an ECAI do not differ in
# quality from solicited credit assessments of this ECAI." The permission is
# per-ECAI and granted by the supervisor, so it is NOT derivable from the
# rating row: the engine cannot decide eligibility and therefore does not
# filter. The warning records that the flag was supplied and is not acted on,
# so the condition is visible rather than silent (P1.291).
ERROR_UNSOLICITED_RATING_NOT_FILTERED = "DQ015"
# Negative on-balance amount (drawn_amount / interest) carrying no
# netting_agreement_reference. A negative balance is the on-balance-sheet
# netting convention (CRR Art. 195/219) — it may offset ONLY the loans that
# share its reference; without a reference it cannot net against anything and
# is a data error that would understate the gross exposure value were it not
# floored at 0 (CRR Art. 111 SA / Art. 166 IRB).
ERROR_NEGATIVE_AMOUNT_WITHOUT_NETTING = "DQ010"
# Non-finite (NaN / ±inf) value in a float column of a raw input table.
# Nulled at the pipeline entry (contracts/validation.py::scrub_non_finite_values)
# before any calculation: a NaN survives every arithmetic step (unlike null,
# which downstream semantics handle), poisoning rwa_final on the affected rows
# and — through the Basel 3.1 portfolio output floor — the whole portfolio.
ERROR_NON_FINITE_RAW_INPUT = "DQ011"
# Negative value in an amount column whose regulatory domain excludes negatives
# (a facility limit, a contingent nominal, a collateral value, a guarantee
# cover, a provision amount). Distinct from DQ010: drawn_amount / interest MAY
# legitimately be negative under the on-balance-sheet netting convention
# (CRR Art. 195/219), these columns may not — a negative here manufactures
# exposure or capital relief out of nothing. Emitted by the input-domain gate
# (contracts/validation.py::_validate_numeric_ranges).
ERROR_NEGATIVE_AMOUNT = "DQ012"
# Input value outside the domain declared for its column
# (``data/schemas.py`` ``ColumnSpec.domain``). The GENERIC code emitted by the
# declaration-driven input-domain gate for any column that does not pin an
# older, more specific code — a CQS outside 1-6, an FX rate <= 0, an LTV below
# zero, a risk-weight override above the 1250% cap. New declarations need no
# new code: only columns whose code the estate already publishes are pinned
# (contracts/validation.py::_DOMAIN_REPORTING).
ERROR_INPUT_OUT_OF_DOMAIN = "DQ013"
# Input column supplied in a dtype whose cast to the declared dtype can destroy
# values — a String amount, a float into a declared integer band. The loader
# seal casts non-strictly (``contracts/edges.py::conform_lenient``), so an
# unparseable value becomes null, and the input-domain gate's rule is correctly
# that null is never a domain violation: without this code a value that could
# not be READ is indistinguishable from one never SUPPLIED and from a genuine
# zero. Measured: a GBP 1m drawn_amount arriving as "1,000,000.00" published
# rwa_final = 0.00 with an empty error list. This is the UPSTREAM form of the
# check DQ003 lost — see DQ003 above for why it is a new code and not a revival.
# Emitted by the loader edge seal (``engine/loader.py::_seal_table``).
ERROR_UNREADABLE_INPUT_DTYPE = "DQ014"
# Off-balance-sheet row carrying an amount but no resolvable Annex I / Table A1
# risk category: ``risk_type`` is null AND ``obs_product`` maps to nothing. Such
# a row is schema-VALID — ``risk_type`` is optional and DQ006's domain test
# filters ``is_not_null()`` before it runs — so today it takes the CCF residual
# limb silently. That is well-formed input producing an unreviewed capital
# number, not malformed input: the residual is CRR Annex I 1(k)'s 100% or PS1/26
# Table A1 Row 3/5's 50%/40%, none of which the preparer chose. Distinct from
# DQ006, which fires only when a NON-null string fails the domain (P1.267).
ERROR_UNRESOLVED_OBS_RISK_TYPE = "DQ016"

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
# Cross-counterparty on-balance-sheet netting (CRR/PS1-26 Art. 195/205(a)): the
# set-off perimeter is the netting_agreement_reference, so a deposit from
# counterparty A DOES offset a loan to counterparty B under the same agreement.
# This warning is the audit record of such an applied offset (one per spanning or
# null-counterparty agreement): Art. 205(a) enforceability against every party
# must be evidenced separately. With the pack Feature
# ``on_bs_netting_perimeter_is_agreement`` disabled the offset is instead refused
# and the message says so; the trigger is identical in both states.
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
# Unrecognised collateral type (CRR/PS1-26 Art. 230-231, D5): a collateral_type
# matching none of the known category sets (data/schemas.py
# RECOGNISED_COLLATERAL_TYPES) falls through collateral_category_expr to the
# "other" fallback category. The Art. 231 waterfall keys on the same sets, so the
# row is recognised at no LGDS, reports in no CRM column, and CHANGES RWA — all
# silently. Typically a spelling/mapping error in the source feed (e.g.
# "residential_real_estate" for "real_estate"). This warning names the collateral
# reference and the offending value (one per row). A NULL collateral_type does
# NOT warn: absence is the project's null-permissive convention, not an asserted
# defect.
ERROR_UNRECOGNISED_COLLATERAL_TYPE = "CRM021"
# Below the Art. 230 minimum collateralisation level (CRR Art. 230(2) Table 5): the
# C* row sets a minimum required collateralisation of 30% of the exposure for real
# estate and other physical collateral, and below it the exposure is treated as
# FULLY UNSECURED — the whole category is dropped from the Art. 231 waterfall and
# LGD reverts to LGDU. That is correct capital, but it was applied with no
# diagnostic, leaving a preparer with a populated collateral column, an LGD at the
# supervisory unsecured value, and nothing joining the two. One rolled-up warning
# per collateral category names the count, the C/E ratio band and up to five
# exposure references. CRR-only: PS1/26 Art. 230(1) removes C*/C** entirely, so
# this is gated on the firb_min_collateralisation_threshold_applies pack Feature.
# It does NOT restate an Art. 199 drop — an unattested pledge is already zeroed
# before C* is evaluated, and CRM014 owns that cause.
ERROR_BELOW_MIN_COLLATERALISATION = "CRM022"

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
# Own-estimate conversion factor (``ccf_modelled``) outside its input domain
# [0, 1.5]. The A-IRB own-estimate CCF of CRR Art. 166(8)/(10): a value above
# 1.5 is beyond even the retail additional-drawdown allowance, and a negative
# one would reduce the exposure value. Emitted by the input-domain gate
# (contracts/validation.py::_validate_numeric_ranges), never floored silently.
ERROR_CCF_OUT_OF_RANGE = "IRB008"

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
# P1.345 / P1.317: the twin of OUT004 on the capital carrier. P1.317 published a
# populated ead_final, a risk_weight of 2.5 and a NULL rwa_final — the bounds
# gate was one spec short, so nothing production-side noticed. The test-side
# guard shipped with P1.317 is equity-scoped; this one is class-agnostic.
ERROR_RWA_NULL = "OUT005"

# Branch-reason code (validate_branch_reasons). A row whose *_branch_reason
# column reads UNKNOWN_FALLBACK was priced on a branch the engine could not
# justify: either the deciding predicate evaluated to null and pl.when silently
# took `otherwise`, or a value was substituted for input that was simply absent.
# The number such a row carries is plausible and unearned, which is precisely
# the failure docs/plans/test-space-correctness-proposal.md exists to close —
# so the reason column never stands alone, and this code is what accompanies it.
ERROR_UNKNOWN_BRANCH_FALLBACK = "BR001"

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
# The legacy extract could not be projected into the sealed reporting-ledger
# vocabulary, so the firm's side of a return cannot be generated from it. The
# reconciliation itself is unaffected — the exposure-grain comparison still runs
# and every summary is identical; only the template comparison is unavailable.
# The message names the ledger columns the mapping does not supply, so the
# remedy is actionable rather than a bare failure.
ERROR_RECON_LEDGER_UNAVAILABLE = "REC008"

# Cross-template reporting tie-out codes (reporting.tieouts). Non-fatal:
# a break means two independently-generated templates (C 02.00 / C 07.00 /
# C 08.01 / OV1) disagree on a comparable aggregate beyond tolerance. The
# specific tie is carried on the finding's field_name.
ERROR_CROSS_TEMPLATE_INCONSISTENCY = "TIE001"

# Published supervisory validation-rule codes (reporting.validations). These are
# the SUPERVISOR's own arithmetic checks on the submitted return, not in-house
# ones: the EBA DPM rules for COREP under CRR and the BoE banking taxonomy rules
# under PS1/26. As with TIE001 the broken rule id is carried on the finding's
# field_name and both figures in the message (one code per failure mode, not one
# per rule).
#
# VAL001 is a BLOCKING defect in the filing: an Error-severity rule break means
# the supervisor rejects the entire return, so it is not a quality nit.
ERROR_VALIDATION_RULE_ERROR = "VAL001"
# VAL002 is a Warning-severity break: the return is accepted, but the firm is
# expected to explain or correct the flagged figure.
ERROR_VALIDATION_RULE_WARNING = "VAL002"
# VAL003 says the estate was not checked well enough for the ABSENCE of VAL001 /
# VAL002 to mean anything: either no rule executed at all, or an emitted template
# had no rule executed against it. Without it the natural gate
# ``if not check_supervisory_validations(...): submit()`` fails OPEN — an
# unreadable estate yields zero breaks and looks identical to a clean one. Error
# severity because it blocks a submission DECISION, not because a figure is wrong.
ERROR_VALIDATION_COVERAGE_INSUFFICIENT = "VAL003"


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


def unsolicited_rating_not_filtered_warning(*, n: int) -> CalculationError:
    """Create a DQ015 warning for unsolicited ECAI assessments used unfiltered.

    CRR / PS1-26 Art. 138 chapeau: an institution "shall use solicited credit
    assessments. However it may use unsolicited credit assessments if the
    competent authority has confirmed that unsolicited credit assessments of an
    ECAI do not differ in quality from solicited credit assessments of this
    ECAI."

    The engine deliberately does NOT filter on ``is_solicited``, and the reason
    is that the article's permission is **per-ECAI and supervisor-granted**: it
    is not a property of the rating row, and no input carries it. Suppressing
    every unsolicited assessment would deny ratings a firm is entitled to use
    wherever that confirmation exists — wrong in the denying direction, and on
    a flag whose default is ``True`` it would also change nothing for the
    firms that never populate it.

    So the honest treatment is to surface the condition rather than act on it.
    This warning is what makes ``is_solicited`` a *read* column instead of a
    declared-and-ignored one: a firm that marks an assessment unsolicited is
    told, once per run, that the engine has used it and that the Art. 138
    confirmation is the firm's to hold. One warning per run, not per row —
    the condition is a portfolio-level governance fact, not a row defect.
    """
    return CalculationError(
        code=ERROR_UNSOLICITED_RATING_NOT_FILTERED,
        message=(
            f"{n} ECAI credit assessment(s) are flagged unsolicited "
            "(is_solicited=False) and have been used unfiltered. Art. 138 permits "
            "unsolicited assessments only where the competent authority has "
            "confirmed they do not differ in quality from that ECAI's solicited "
            "assessments; the engine cannot verify that confirmation from the "
            "input, so it does not suppress them. Confirm the permission is held "
            "for each ECAI concerned, or omit the assessment."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        regulatory_reference="CRR Art. 138",
    )


def negative_amount_without_netting_warning(
    *, context: str, column: str, n: int
) -> CalculationError:
    """Create a DQ010 warning for a negative on-balance amount with no netting.

    A negative ``drawn_amount`` / ``interest`` is the on-balance-sheet netting
    convention (CRR Art. 195/219): a deposit / credit balance offsets the loans
    that share its ``netting_agreement_reference`` (``data/schemas.py``). A
    negative amount WITHOUT such a reference cannot net against anything — it is
    a data error that would understate the gross exposure value were it not
    floored at 0 for both EAD and the gross-exposure reporting carriers
    (CRR Art. 111 SA / Art. 166 IRB). The row is retained and the negative is
    clipped to 0; one aggregate warning is emitted per offending column/table.
    """
    return CalculationError(
        code=ERROR_NEGATIVE_AMOUNT_WITHOUT_NETTING,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[{context}] {n} row(s) have a negative '{column}' with no "
            "netting_agreement_reference. A negative balance without a netting "
            "agreement cannot offset an exposure (CRR Art. 195/219); it is "
            "floored at 0 for the gross exposure value (Art. 111 / Art. 166)."
        ),
        field_name=column,
        regulatory_reference="CRR Art. 111; Art. 166",
    )


def unresolved_obs_risk_type_warning(
    *, context: str, amount_column: str, n: int
) -> CalculationError:
    """Create a DQ016 warning for an OBS amount with no resolvable risk category.

    ``risk_type`` is null and ``obs_product`` maps to no Annex I / Table A1
    bucket, yet the row carries a non-zero off-balance-sheet amount. Nothing
    else reports this: ``risk_type`` is an optional column, so no DQ001 fires,
    and the DQ006 categorical-domain test filters ``is_not_null()`` before it
    runs, so a null never reaches it. The row is retained and priced on the
    residual limb of ``engine/ccf.py::_sa_ccf_residual`` — CRR Annex I item
    1(k)'s 100%, or PS1/26 Table A1 Row 5's 40% (commitment) / Row 3's 50%
    (issued item). Every one of those is the regime's catch-all rather than a
    category the preparer selected, which is what this warning makes visible.

    References:
    - CRR Art. 111, Annex I item 1(k) (full-risk residual)
    - PRA PS1/26 Art. 111, Table A1 Rows 3 and 5 (issued / commitment residuals)
    """
    return CalculationError(
        code=ERROR_UNRESOLVED_OBS_RISK_TYPE,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[{context}] {n} row(s) carry a non-zero '{amount_column}' but no "
            "resolvable off-balance-sheet risk category: 'risk_type' is null and "
            "'obs_product' maps to no Annex I / Table A1 bucket. The CCF residual "
            "applies (CRR Annex I 1(k) 100%; PS1/26 Table A1 Row 5 40% / Row 3 "
            "50%) — supply 'risk_type' or 'obs_product' to select a category."
        ),
        field_name="risk_type",
        regulatory_reference="CRR Art. 111 Annex I 1(k); PS1/26 Art. 111 Table A1 Rows 3, 5",
    )


def orphan_reference_error(
    *,
    table: str,
    column: str,
    parent_table: str,
    value: str,
    reference: str | None,
    counterparty_reference: str | None,
    reason: str,
) -> CalculationError:
    """Create a DQ005 error for a foreign key that resolves to no parent row.

    The reference IS supplied and points nowhere: the feed's parent table is
    short a row, or the value is a typo. That is a different repair from an
    absent reference (:func:`absent_reference_error`, DQ001) — this one needs
    the PARENT feed re-sent or extended, that one needs the child column
    populated — so the two carry different codes rather than one code with two
    messages.

    The row is never dropped. Every counterparty-attribute join in the
    hierarchy stage is ``how="left"`` deliberately (dropping the exposure would
    remove its capital from the portfolio outright, which is worse than
    mis-pricing it), so the row survives carrying whatever fallback treatment
    ``reason`` names. This error is what makes that substitution visible.

    Severity is ERROR, matching the declared-domain gate: the row does not
    degrade to a null anyone would notice, it publishes a plausible and wrong
    number.
    """
    return CalculationError(
        code=ERROR_ORPHAN_REFERENCE,
        message=(
            f"[{table}] '{column}' = '{value}' resolves to no row in '{parent_table}'. {reason}"
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=reference,
        counterparty_reference=counterparty_reference,
        regulatory_reference=reason,
        field_name=column,
        expected_value=f"a {parent_table} reference that exists",
        actual_value=value,
    )


def absent_reference_error(
    *,
    table: str,
    column: str,
    parent_table: str,
    reference: str | None,
    reason: str,
) -> CalculationError:
    """Create a DQ001 error for a declared foreign key that was never supplied.

    Deliberately NOT DQ005. An orphan is a BROKEN link — a value that points at
    a row somebody expected to exist — and its repair is to the parent feed. A
    null is a MISSING FIELD: no link was ever asserted, and its repair is to
    this row. Reporting both under one code would tell an operator to go
    looking in the wrong file, and would make the two indistinguishable in the
    audit trail even though they arrive from different upstream faults (a
    partial parent extract versus an unpopulated column).

    They reach the same engine fallback, which is why the distinction has to be
    made HERE: downstream, both are simply a null obligor attribute and the
    information about which one it was is gone.
    """
    return CalculationError(
        code=ERROR_MISSING_FIELD,
        message=(
            f"[{table}] '{column}' is null, so this row asserts no link to "
            f"'{parent_table}' at all. {reason}"
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=reference,
        regulatory_reference=reason,
        field_name=column,
        expected_value=f"a {parent_table} reference",
    )


def duplicate_input_key_error(
    *,
    table: str,
    column: str,
    value: str,
    count: int,
    names_a_counterparty: bool,
) -> CalculationError:
    """Create a DQ004 error for an input table's natural key appearing twice.

    One per DUPLICATED KEY rather than one per table, and uncapped, because a
    count alone is not actionable: an operator repairs a feed by finding the
    rows, and the population is bounded by the number of distinct duplicated
    keys — which is zero on well-formed input. This is the one place in the
    input gate where the estate's ``sample_cap`` sampling contract does not
    apply, and the reason is that a sampled duplicate leaves the un-sampled
    rows exactly as unaccounted-for as they were before the gate existed.

    Severity is ERROR, unlike the ``org_mappings`` DQ004 raised by
    ``engine/hierarchy/graph.py``, which is a WARNING. The two are not
    inconsistent: there, the resolver de-duplicates a MAPPING table
    deterministically and no exposure is lost, so the operator is told about a
    tidy-up. Here the key names an exposure or an obligor — the model-permission
    join collapses duplicate exposure rows and the counterparty join multiplies
    them — so the portfolio total is wrong in one direction or the other and the
    reference has stopped identifying a row at all.

    ``names_a_counterparty`` routes the offending value to the right reference
    field. Both fields are read by consumers that triage by row, and putting a
    counterparty reference in ``exposure_reference`` would make the error
    unjoinable to the obligor it is actually about.
    """
    return CalculationError(
        code=ERROR_DUPLICATE_KEY,
        message=(
            f"[{table}] {count} input rows share '{column}' = '{value}'. The key "
            "no longer identifies a row: downstream de-duplication keeps one "
            "exposure row per reference (so the others' capital leaves the "
            "portfolio total), and a duplicated obligor multiplies every exposure "
            "that joins to it. Neither outcome is recoverable from the output."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=None if names_a_counterparty else value,
        counterparty_reference=value if names_a_counterparty else None,
        field_name=column,
        expected_value="one row per key",
        actual_value=str(count),
    )


def non_finite_raw_input_error(
    *, table: str, column: str, count: int, references: list[str] | None = None
) -> CalculationError:
    """Create a DQ011 error for non-finite (NaN / ±inf) raw input values.

    Emitted by the pipeline-entry scrub (``scrub_non_finite_values``) — one
    aggregate error per affected (table, column). The offending values are
    replaced with null so the affected rows degrade per the documented
    downstream null semantics instead of a NaN silently surviving every
    arithmetic step: unscrubbed, a single NaN poisons the exposure's
    ``rwa_final`` (AGG001) and, through the Basel 3.1 portfolio output floor,
    every other row's post-floor RWA. ``references`` carries up to a handful
    of affected row references for triage.
    """
    sample = ""
    if references:
        shown = ", ".join(references)
        sample = f" (e.g. {shown})"
    return CalculationError(
        code=ERROR_NON_FINITE_RAW_INPUT,
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"{count} non-finite (NaN/inf) value(s) in raw input "
            f"'{table}.{column}'{sample} replaced with null; affected rows "
            "degrade per downstream null semantics instead of poisoning "
            "portfolio totals. Check the source data feed."
        ),
        field_name=column,
        actual_value=str(count),
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


def unreadable_input_dtype_error(
    *, table: str, column: str, supplied: str, declared: str
) -> CalculationError:
    """Create a DQ014 error for an input column supplied in a destructive dtype.

    Emitted by the loader's edge seal (``engine/loader.py::_seal_table``),
    one per (table, column), from the ``LossyCast`` findings that
    ``EdgeContract.conform_lenient`` returns. The seal casts a mismatched
    column with ``strict=False``, so any value Polars cannot convert
    becomes null — and null is legitimately "not supplied" everywhere
    downstream. A GBP 1,000,000 ``drawn_amount`` arriving as the string
    ``"1,000,000.00"`` therefore published ``ead_final = rwa_final =
    0.00``, a 100% understatement of that exposure's capital, on a row
    that looks populated and with nothing in the error list.

    ERROR rather than WARNING deliberately: the measured consequence is a
    silent understatement of regulatory capital, and the remedy is a
    re-typed feed, not a judgement call. The finding is the dtype drift
    itself — no value is inspected, because the seal runs on every table
    of every run and must not materialise anything — so the message says
    what CAN have happened, not how many values did.
    """
    return CalculationError(
        code=ERROR_UNREADABLE_INPUT_DTYPE,
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.SCHEMA_VALIDATION,
        message=(
            f"Input column '{table}.{column}' arrived as {supplied} where {declared} "
            f"is declared; the loader seal casts it non-strictly, so any value that "
            f"could not be converted became null — indistinguishable from a value "
            f"that was never supplied (a nulled amount publishes as 0.00 capital, "
            f"not as an error). Re-send '{column}' typed as {declared}."
        ),
        field_name=column,
        actual_value=supplied,
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
