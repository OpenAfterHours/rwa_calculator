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
    from collections.abc import Sequence
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
# Contingent booked on a COMMITMENT risk_type (MR = NIF / RUF, OC = other
# commitment) while ``is_obs_commitment`` is False — the contingent default,
# i.e. an issued item. The two inputs contradict each other; under CRR F-IRB the
# row takes the Art. 166(10)(b) issued-item 50% instead of the Art. 166(8)(d)
# 75% for "other credit lines, note issuance facilities (NIFs), and revolving
# underwriting facilities (RUFs)". Not auto-resolved: an issued medium-risk item
# mis-coded MR would then be overstated (CM-09).
ERROR_ISSUED_ITEM_ON_COMMITMENT_RISK_TYPE = "DQ017"
# One ``exposure_reference`` claimed by more than one exposure namespace — a loan
# and a contingent sharing a reference, or a user row named like an engine-minted
# one (``<facility>_UNDRAWN``, ``ccr__<netting set>``, ``ft__``, ``dfc__``) or like
# an equity exposure (review finding RC-10). Uniqueness was only ever declared PER
# TABLE (``TABLE_UNIQUE_KEYS``), so such a pair was plausible input, and every
# join keyed on the bare reference merged the two rows: the IRB model-permission
# de-duplication kept one of them (the other's capital left the total) and a
# guarantee on the loan covered the contingent too. ERROR, one per colliding
# reference. The hierarchy stage keeps the rows apart by re-keying each colliding
# loan / contingent to ``<reference>#<type>`` and resolving every typed pointer to
# it (facility mapping, short-term rating scope, CRM beneficiary, securitisation
# allocation) by its declared type (``engine/hierarchy/namespace.py``).
ERROR_EXPOSURE_REFERENCE_COLLISION = "DQ019"
# An amount in a currency other than the reporting currency with no FX rate into
# it (review finding RC-11). ``engine/fx`` keeps such an amount in its source
# currency's units and every downstream GBP threshold, total and template reads it
# as reporting currency — a 1:1 conversion that understates (KWD) or overstates
# (ZAR) depending on the currency, which is why the defect is the silence, not a
# direction. ERROR, one per currency, naming the rows and amounts per table.
# Emitted by ``contracts/validation.py::_validate_missing_fx_rates`` (the
# pipeline-entry input gate); not raised when conversion is off.
ERROR_FX_RATE_MISSING = "DQ020"
# A facility-mapping child (sub-facility, loan or contingent) mapped under more than
# one parent facility (review findings RC-01 / RC-02 / SF-03). A facility hierarchy
# is a tree; a second parent used to make a sub-facility's root depend on row order
# and made a loan consume the headroom of every parent it was mapped to. WARNING:
# the hierarchy stage resolves the graph deterministically and conservatively (one
# parent per sub-facility, the lowest reference; one root per loan / contingent,
# that of its lowest-referenced parent; one reduction per root) and names the
# resolution here.
ERROR_FACILITY_MAPPING_MULTI_PARENT = "DQ021"
# Facility mappings that form a cycle (review finding RC-02). Every member used to
# be treated as somebody's sub-facility, so NONE emitted its undrawn commitment.
# WARNING: every facility on the cycle is treated as a root of its own instead.
ERROR_FACILITY_MAPPING_CYCLE = "DQ022"
# A risk type only the ENGINE mints (``CCR_DERIVATIVE`` / ``CCR_SFT`` /
# ``CCR_DEFAULT_FUND`` / ``SETTLEMENT_FAILED_TRADE``) supplied on a LENDING table
# (review finding CC-19). Those tags route a row to a counterparty-credit-risk
# treatment — the ``standardised_ccr`` approach label, the repo-style IRB
# maturity, the CCR rows of C 07.00, the 1250% own-funds conversion — whose
# exposure value comes from the CCR methods or the FCCM (CRR Art. 111(2); PS1/26
# Art. 111(2) / (2A)), never from an Annex I / Table A1 CCF on a nominal amount.
# ERROR. The hierarchy stage disregards the two CCR routing tags (rewritten to
# ``DQ023:<tag>``: the row keeps the residual CCF of an unrecognised risk type and
# loses the CCR routing) and honours the two own-funds tags, whose 1250% weight
# disregarding would cut (``data/schemas.py::DISREGARDED_ENGINE_ONLY_RISK_TYPES``).
# Replaces the DQ006 such a value would otherwise draw.
ERROR_ENGINE_ONLY_RISK_TYPE = "DQ023"

# Hierarchy error codes
ERROR_CIRCULAR_HIERARCHY = "HIE001"
ERROR_MISSING_PARENT = "HIE002"
ERROR_HIERARCHY_DEPTH = "HIE003"
# Facility undrawn commitments (engine/hierarchy/facility_warnings.py). All three
# are WARNINGs: each names a facility whose undrawn row the hierarchy stage built
# on a treatment the input did not state outright, so the number is visible
# rather than silently chosen.
#
# ``committed=False`` with a non-null risk_type other than the UCC bucket LR. An
# uncommitted facility is an accepted, unconditionally cancellable commitment
# (PS1/26 Glossary "commitment"; Table A1 row (7) 10%; CRR Annex I 4(a) 0%), so
# its undrawn row is priced as LR whatever the row declared.
ERROR_UNCOMMITTED_FACILITY_RISK_TYPE = "HIE004"
# A loan / contingent drawn in a currency other than its facility's, or a
# sub-facility limit in a currency other than its umbrella's, with no FX rate in
# the run to express it in the facility currency. The amount is NOT netted
# against the headroom (the undrawn commitment is measured gross of it) rather
# than subtracted in raw units (CRR Art. 4(1)(56): the commitment's extent is
# "determined by the advised limit").
ERROR_FACILITY_HEADROOM_FX_RATE_MISSING = "HIE005"
# A facility with a null ``limit`` that is not an umbrella (MOF parent): its
# undrawn commitment cannot be measured, so no undrawn row is generated.
ERROR_FACILITY_LIMIT_MISSING = "HIE006"

# Classification error codes
ERROR_UNKNOWN_EXPOSURE_CLASS = "CLS001"
ERROR_APPROACH_NOT_PERMITTED = "CLS002"
ERROR_MISSING_RATING = "CLS003"
ERROR_QRRE_COLUMNS_MISSING = "CLS004"
ERROR_RETAIL_POOL_MGMT_MISSING = "CLS005"
ERROR_MODEL_PERMISSION_UNMATCHED = "CLS006"
# CLS007 (ERROR_FSE_COLUMN_MISSING) was retired with the classifier's
# column-presence guards — the absent-column state it detected is
# unrepresentable on sealed input. See engine/classify/audit.py.
ERROR_LARGE_CORP_REVENUE_NULL = "CLS008"
ERROR_LFSE_ASSETS_NULL = "CLS009"
ERROR_QRRE_GATE_DEMOTION = "CLS010"
ERROR_LARGE_CORP_GROUP_ROLLUP = "CLS011"
# A slotting-approach exposure with no recognised slotting_category (null, or
# not a SlottingCategory value). CRR / PS1/26 Art. 153(5) weight a slotted
# exposure by the grade the institution assigns; the engine applies the cited
# pack default ("satisfactory") and, with this WARNING, no longer does so
# silently. Emitted by the classifier's post-materialise roll-up.
ERROR_SLOTTING_CATEGORY_MISSING = "CLS012"
# Null counterparty entity_type (RC-12). ``entity_type`` is the single source of
# the exposure class (CRR / PS1/26 Art. 112, Table A2), and a null matches no row
# of the class map, so the classifier files the exposure under OTHER (100% SA)
# and the obligor's ECAI rating is never read. An unrecognised NON-null string
# already draws DQ006; the null drew nothing at all. One WARNING per run naming
# the counterparties. The fallback class itself is deliberately unchanged — the
# true class, and so the direction of error, is unknowable from the row.
ERROR_NULL_ENTITY_TYPE = "CLS013"
# Basel 3.1 SME size undetermined: the PS1/26 glossary SME definition is
# turnover-only ("an annual turnover of not more than GBP 44 million"), so a
# corporate with no annual revenue (own or group) whose total assets would have
# met the Commission Rec 2003/361/EC balance-sheet limb is NOT treated as an SME.
ERROR_SME_REVENUE_NULL_B31 = "CLS015"
# SME size test decided by the consolidated group: the entity's OWN figures pass
# the SME test but the highest-consolidation group figures do not (PS1/26
# glossary SME (1); CRR Art. 4(1)(128D) / Art. 153(4) "consolidated group").
ERROR_SME_GROUP_SIZE_FLIP = "CLS016"

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
# change (Basel 3.1 only; omitted by PS1/26 rule 4.11 for protection entered into
# before 1 Jan 2027, on reporting dates 1 Jan 2027 - 30 Jun 2028) is dropped and
# the exposure flows unguaranteed.
ERROR_INELIGIBLE_UNFUNDED_PROTECTION = "CRM012"
# Ineligible guarantor (CRR/PS1-26 Art. 201(1)/(2), with CRR Art. 194(5) /
# PS1/26 Art. 194(6)(c)): a corporate guarantor without an ECAI credit
# assessment (or, for an IRB-approach beneficiary, an internal rating), or a
# natural person of any rating (no Art. 201 limb names one; an A-IRB beneficiary
# is outside the list, CRR Art. 108(2)), is not an eligible protection provider —
# the covered exposure reverts to the borrower's own basis. The message names
# which cause applied.
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
# Tranched unfunded protection (CRR Art. 234 / PS1/26 Art. 234(1), with Art.
# 235(2)): a guarantee that covers a BAND of the loss distribution — an
# attachment_amount above zero, or any detachment_amount — rather than a
# pro-rata share transfers risk "in one or more tranches", which Art. 234 sends
# to the securitisation framework (Chapter 5), and Art. 235(2) allows the
# risk-weight substitution only where the protected and unprotected parts are of
# equal seniority. This engine does not run Chapter 5 for such protection, so the
# guarantee is NOT recognised (the exposure keeps the obligor's own basis, the
# Art. 268(1) upper bound of the Chapter 5 result) and this warning names it (one
# per guarantee row).
ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED = "CRM027"
# One guarantee_reference entered inconsistently across rows. Rows sharing a
# guarantee_reference are ONE contract with ONE cap (Art. 233(1): G is the amount
# the provider undertook to pay; Art. 213(1)(b): its extent must be clearly
# defined): the total recognised across the rows is capped at the contract's
# amount_covered and allocated pro-rata to each row's covered demand. This
# warning fires when those rows state DIFFERENT amount_covered values (the
# largest is used as the cap) and when one guarantee_reference is entered more
# than once for the same beneficiary (a repeat from the same guarantor is one
# undertaking: only its largest row is used) - one per guarantee_reference and
# cause.
ERROR_GUARANTEE_REFERENCE_INCONSISTENT = "CRM028"
# Not eligible unfunded credit protection (CRR / PS1/26 Art. 213(1)(b)-(d) and
# Art. 215(1)(b)): a letter of comfort, comfort letter or keepwell is not an
# explicitly documented obligation assumed by the provider to pay on the
# obligor's default, so a guarantee row whose guarantee_type names one is NOT
# recognised and this warning names it (one per guarantee row).
ERROR_NOT_ELIGIBLE_PROTECTION_TYPE = "CRM029"
# guarantee_type names a credit derivative while protection_type does not
# (protection_type defaults to "guarantee" when absent). The row is treated as
# the credit derivative its guarantee_type says it is — so the CRR / PS1/26
# Art. 233(2) restructuring-exclusion treatment applies when
# includes_restructuring is False — and this warning records the disagreement
# (one per guarantee row).
ERROR_PROTECTION_TYPE_MISMATCH = "CRM030"

# SFT (Financial Collateral Comprehensive Method) error codes — emitted by the
# peer sft_fccm stage (engine/sft/). The older CCR codes (CCR001/010/011/020) are
# declared beside their SA-CCR producers; these three are the SFT FCCM ones.
#
# SFT collateral not recognised in E* (CRR / PS1-26 Art. 223(1): volatility
# adjustments are applied "when valuing financial collateral"; Art. 197/198 list
# the eligible items). A collateral row whose type is not one the SFT path can
# price from the Art. 224 Tables 1/3 (real estate, receivables, other physical,
# a bare "bond" with no issuer class, CIU units, an unknown string), or a debt
# security whose CQS fails Art. 197(1)(b)-(d), contributes NOTHING to the
# CVA·(1-HC-HFX) term; so does a row keyed to a netting set holding no SFT trade.
# One WARNING per collateral row.
ERROR_SFT_COLLATERAL_NOT_RECOGNISED = "CCR027"
# SFT netting set without an eligible master netting agreement (CRR / PS1-26
# Art. 220(1): the netted E* applies to "exposures subject to an eligible master
# netting agreement"; Art. 206(1)(a)-(d) eligibility; PS1/26 Art. 111(2A)). A
# netting set holding more than one trade whose trades do not ALL carry both
# under_master_netting_agreement and is_legally_enforceable is split into one
# single-trade set per trade (Art. 223(5) per transaction); collateral rows on it
# that are not linked to one of its trades by trade_id are not recognised. One
# WARNING per affected netting set.
ERROR_SFT_NETTING_NOT_RECOGNISED = "CCR028"
# SFT netting set spanning more than one counterparty (CRR / PS1-26 Art. 220(4):
# E* is "the exposure value of the exposure to the counterparty"; a master
# netting agreement is bilateral). The engine would otherwise book the whole set
# against the first counterparty's risk weight; the set is instead split into one
# single-trade set per trade, each against its own counterparty, and this ERROR
# names the counterparties. One ERROR per affected netting set.
ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET = "CCR029"
# Collateral currency unknown (CRR Art. 223(2)/224 Table 4, PS1/26 Art. 230(1)(b);
# review CL-14): a collateral row whose currency (pre-conversion
# ``original_currency``, else ``currency``) is null cannot show that it matches
# the exposure's currency, so it is treated as currency-mismatched and takes the
# H_fx volatility adjustment wherever H_fx applies to its type (financial
# collateral in both regimes; non-financial under Basel 3.1). Its value is also
# left unconverted by FX conversion. One rolled-up warning per run naming up to
# five references. Life insurance is excluded — CRM020 owns that case.
ERROR_COLLATERAL_CURRENCY_UNKNOWN = "CRM023"
# Netted deposit repayable on demand (CRR/PS1-26 Art. 238(1), Art. 237(1);
# review NT-03): a deposit under an on-balance-sheet netting agreement with no
# maturity_date is withdrawable on demand, so the protection's residual maturity
# is zero — "the time to the earliest date at which the protection may terminate"
# (PS1/26 Art. 238(1)(b): "the date when the deposit ... can be withdrawn"). Where
# it nets against a loan with a later maturity, the Art. 237(1) three-month gate
# removes the relief; this warning (one per netting agreement) records that. An
# on-demand deposit against an on-demand loan (both maturities null) is a matched
# pair and still nets.
ERROR_ON_DEMAND_NETTED_DEPOSIT = "CRM024"
# Loan-table collateral pledged only to counterparty-credit-risk rows (CRR
# Art. 223(5A), PS1/26 Art. 191A(4); review CL-04 / CC-07): collateral pools and
# direct links from the collateral table never reduce an SA-CCR derivative, FCCM
# SFT, failed-trade or default-fund row — their collateral is taken into account
# in the CCR Part's own calculation (ccr_collateral / sft_collateral). A pledge
# whose ONLY beneficiaries are such rows therefore mitigates nothing; one rolled-
# up warning per run names the items. Guarantees still apply to CCR rows.
ERROR_CCR_ONLY_COLLATERAL_POOL = "CRM025"
# Non-Art. 197 collateral flagged as eligible financial collateral (CRR/PS1-26
# Art. 197(1), 199(1); review CL-01): is_eligible_financial_collateral is the
# firm's Art. 197 attestation, and only an Art. 197 type (cash, debt securities,
# equity, gold, securitisation positions, covered bonds) can reduce an SA
# exposure value under the Financial Collateral Comprehensive Method, or be
# substituted under the Simple Method (Art. 222). A flagged immovable-property,
# receivable, other-physical, life-insurance or unrecognised row is ignored for
# both (it stays available to the
# F-IRB Foundation Collateral Method under its own Art. 199 attestation, and
# life insurance to Art. 232). One rolled-up warning per run.
ERROR_NON_ART197_FLAGGED_FINANCIAL = "CRM026"
# Financial collateral not attested as meeting Art. 207 (CRR Art. 207(1): "under
# all approaches and methods"; PS1/26 Art. 207(1) names the Simple, Comprehensive
# and Foundation Collateral Methods and the SFT VaR Method; review CL-06, P1.445):
# a cash, debt-security, equity, gold or credit-linked-note row whose
# is_eligible_financial_collateral is False or unset (the loader seals absent and
# null to False) is recognised under no method. It reduces no SA exposure value,
# takes no Simple Method substitution, and gives no F-IRB LGD* relief, no Basel 3.1
# A-IRB Art. 161(5) LGD-floor credit and no C 08.01 col 0180 amount. One rolled-up
# warning per run names the items.
ERROR_UNATTESTED_FINANCIAL_COLLATERAL = "CRM031"

# SA-CCR trade-input codes (review CC-06). Raised by the input gate
# (contracts/ccr_input_checks.py), one row-named ERROR per offending trade, for the
# inputs that used to give a netting set a silently zero add-on or drop the trade.
# Each names the conservative treatment engine/ccr applies instead; the result is
# still produced. (CCR001 / CCR010 / CCR011 / CCR020 live beside the gates that
# raise them under engine/ccr/.)
#
# Unrecognised risk category (CRR Art. 277(1)): the trade's asset_class is missing
# or is not one of the six risk categories (case-insensitive). It is priced in the
# Art. 277(1)(f) other-risks category (Art. 280f, SF 8%) as its own hedging set.
ERROR_CCR_UNRECOGNISED_RISK_CATEGORY = "CCR021"
# Unrecognised risk factor (CRR Art. 277a(1)(c)/(e), Art. 280): a credit trade's
# credit_quality or a commodity trade's commodity_type is missing or outside the
# supervisory-factor table. The trade takes the highest factor of that table
# (credit single name NON_RATED, credit index HY, commodity ELECTRICITY).
ERROR_CCR_UNRECOGNISED_RISK_FACTOR = "CCR022"
# Orphan trade (CRR Art. 272(4), CCR (CRR) Part Art. 274(1)): the trade's
# netting_set_id names no row in the netting-set table. It is priced as its own
# non-enforceable netting set with no counterparty (unrated fallback weight,
# alpha 1.4) rather than dropped.
ERROR_CCR_ORPHAN_TRADE = "CCR023"
# Equity / commodity trade priced on its notional (CCR (CRR) Part Art. 279b(1)(c),
# P1.406): the trade's market_price or number_of_units is null, so its adjusted
# notional cannot be the market price x number of units. engine/ccr reads it as
# "contractually expressed as a notional amount" and takes |notional| — the
# article's own second limb — rather than the null product, which used to leave
# the trade out of the add-on. WARNING (the treatment is the rule's, but the engine cannot
# see the contract's form), one row-named entry per trade up to a sample cap.
# Numbered after the CCR030-CCR034 range reserved for the ccp_cva cluster.
ERROR_CCR_NOTIONAL_LIMB_APPLIED = "CCR035"
# FX trade with no second payment leg (CCR (CRR) Part Art. 279b(1)(b)(i),
# Art. 277a(1)(b), P1.406): notional_leg2 and currency_leg2 are both null.
# engine/ccr reads the trade as "consist[ing] of one payment leg" and takes its
# notional as the adjusted notional; with no currency pair stated it shares no
# FX hedging set (its own). WARNING (the treatment is the rule's, but the engine
# cannot see whether the contract really has one payment leg), one row-named
# entry per trade up to a sample cap.
ERROR_CCR_FX_SINGLE_PAYMENT_LEG = "CCR036"
# FX trade whose second leg is stated without the notional the rule needs (CCR
# (CRR) Part Art. 279b(1)(b), Art. 277a(1)(b), P1.406): currency_leg2 is set,
# notional_leg2 is null, and rule (ii) / (iii) needs that leg's notional — the
# stated second leg is not the reporting currency (or both legs are). engine/ccr
# takes the first leg's notional (at spot where it has a rate) as an estimate
# and makes the trade its own FX hedging set, so the estimate offsets none of
# the pair's other trades. Not raised when the stated second leg is the
# reporting currency and the first leg is not: rule (ii) then takes "the
# notional amount of the other payment leg", the first leg at spot — the
# complete value, netted in its pair. Reads the run's base currency, so only the
# configured (pipeline-entry) gate call raises it. Before P1.406 the trade added
# nothing to the FX add-on.
ERROR_CCR_FX_SECOND_LEG_NOTIONAL_MISSING = "CCR037"
# Equity / commodity trade with no adjusted notional at all (CCR (CRR) Part
# Art. 279b(1)(c), P1.406): market_price or number_of_units is null AND the
# notional is 0 or null, so neither limb of the article gives a value and the
# trade adds nothing to its add-on (the 0.0 placeholder notional of a
# unit-priced trade whose units are missing is the common shape). ERROR, one
# row-named entry per trade up to a sample cap; raised instead of CCR035.
ERROR_CCR_NO_ADJUSTED_NOTIONAL = "CCR038"

# Counterparty credit risk / CVA codes reserved for the 2026-11 review's ccp_cva
# cluster (CCR030-CCR034). The other CCR codes (CCR001 / CCR010 / CCR011 /
# CCR020) are declared beside their producers under engine/ccr/.
#
# BA-CVA coverage (PS1/26 CVA Risk Part 4.1 / 1.2 "covered transaction", CC-16):
# a counterparty with OTC derivative netting sets has no row in the BA-CVA
# counterparty input, so it has no sector, credit quality or M_NS and its CVA
# own funds are silently zero (the BA-CVA join drops it). One WARNING per such
# counterparty. QCCP derivatives (exclusion (1)(a)) and counterparties listed
# with cva_in_scope=False are not warned. Basel 3.1 only (cva_ba_cva Feature).
ERROR_CVA_COUNTERPARTY_NOT_SUPPLIED = "CCR030"

# Failed-trade side unknown (CRR Art. 378, CC-09): a DvP failed trade whose
# ``is_purchase`` is null and whose agreed price differs from the market value.
# The loss side decides the charge ("where the difference could involve a loss
# for the credit institution"), so the engine charges the absolute difference —
# conservative for either side — and names the trade with one WARNING.
ERROR_FAILED_TRADE_SIDE_UNKNOWN = "CCR031"

# Default-fund allocation inputs missing (CCR (CRR) Part Art. 308(2), CC-10): a
# QCCP pre-funded contribution with no K_CCP or no DF_CM cannot be allocated its
# share of the CCP's hypothetical capital. The engine charges the 8% x 2% x DF_i
# floor — the one arm of the Art. 308(2) max it can still evaluate, a LOWER
# bound — and names the contribution with one ERROR, since the charge can
# understate. (A null used to reach the SA chain and give RWEA 0 silently.)
ERROR_DFC_ALLOCATION_INPUT_MISSING = "CCR032"
# SA-CCR collateral, margin-term and reporting-currency codes (review cluster
# saccr_b). Built by engine/ccr from the same expressions that price the netting
# set, decoded by contracts/ccr_collateral_checks.py and appended by the ccr / sft
# stages; one row-named entry per finding up to a sample cap.
#
# CCR collateral item not recognised (CCR (CRR) Part Art. 276(1)(a)/(b), Art. 197,
# Art. 274(1)): the item is not Art. 197 eligible financial collateral (a
# non-financial type, a debt security below the Art. 197(1)(b)/(d) credit quality,
# an equity outside a main index), or it was pledged against a netting set that is
# not legally enforceable and holds more than one trade, so it cannot be attributed
# to the single-transaction netting sets Art. 274(1) substitutes. WARNING: the item
# is left out of VM and NICA (no relief if received, no add-on if posted).
ERROR_CCR_COLLATERAL_NOT_RECOGNISED = "CCR024"
# Margin terms conflict (CCR (CRR) Part Art. 275(2), Art. 285): a netting set and
# the margin agreement it names both state a margin threshold, minimum transfer
# amount, NICA or MPOR, and the two differ. WARNING: the capital-conservative
# value is used (the larger TH / MTA / MPOR, the smaller signed NICA).
ERROR_CCR_MARGIN_TERMS_CONFLICT = "CCR025"
# No spot rate to the reporting currency (CCR (CRR) Part Art. 279b(3), Art. 275):
# a trade, CCR collateral item, SFT or SFT collateral item is denominated in a
# currency with no fx_rates row to the reporting currency. ERROR: its amounts are
# used unconverted (the FXConverter's own pass-through for a missing rate) so the
# exposure value is not in the reporting currency.
ERROR_CCR_NO_REPORTING_CURRENCY_RATE = "CCR026"

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
# Retail IRB row priced on an Art. 161(1) corporate supervisory LGD (P1.351).
# Art. 161(1) is a corporates / institutions article in both regimes (PS1/26
# heads it "CORPORATES AND INSTITUTIONS"); retail IRB takes own LGD estimates
# (CRR Art. 151(7), Art. 164(1); PS1/26 Art. 147A(1)(g), Art. 164(1)(a)), and
# the only supervisory retail LGD is for dilution risk of purchased receivables
# (Art. 164(1)). Raised at the pipeline exit by
# contracts/validation.py::validate_branch_reasons for a retail row on the
# ``supervisory_firb`` branch, or on ``supervisory_subtype`` with any subtype
# other than exactly ``dilution_risk`` (the engine dispatch is case-sensitive,
# so a respelled subtype is priced on the seniority fallback). WARNING: the
# value is not changed. Which treatment is right (SA, refusal, or the firm's
# own estimate) is a separate decision.
ERROR_UNAUTHORISED_RETAIL_SUPERVISORY_LGD = "IRB009"

# SA error codes
ERROR_INVALID_CQS = "SA001"
ERROR_MISSING_RISK_WEIGHT = "SA002"
ERROR_INVALID_LTV = "SA003"
ERROR_DUE_DILIGENCE_NOT_PERFORMED = "SA004"
ERROR_EQUITY_IN_MAIN_TABLE = "SA005"
# Basel 3.1 project-finance exposure whose project_phase is null or outside the
# input vocabulary. PS1/26 Art. 122B(3) defines the operational phase by
# evidenced conditions, so the exposure is treated as pre-operational (the
# Art. 122B(2)(c) 130% weight when unrated). WARNING; emitted by the
# classifier's post-materialise roll-up (engine/classify/audit.py).
ERROR_PF_PHASE_UNEVIDENCED = "SA006"
# A ``ciu_holdings`` row whose ``exposure_class`` is null or outside the
# ``ExposureClass`` vocabulary (``securitisation``, ``subordinated_debt``, a
# typo). The engine cannot weight such an underlying "as if directly held"
# (PS1/26 Art. 132A(1)), so a look-through fund holding it takes the Art. 132(2)
# 1,250% fall-back on that slice. WARNING from the input-domain gate; the weight
# itself is applied by ``engine/equity/calculator.py::_holding_rw_expr``.
ERROR_CIU_HOLDING_CLASS_UNSUPPORTED = "SA008"
# Borrower income currency unknown on an Art. 123B-scope exposure (RE-05). PS1/26
# Art. 123B(3): where an institution "is unable to identify those exposures with a
# currency mismatch" it "shall apply the risk weight multiplier of 1.5 to all
# unhedged retail exposures, and unhedged residential real estate exposures ...,
# except where the lending currency is the same as the domestic currency of the
# country of residence of the obligor". The engine applies that fallback wherever
# ``borrower_income_currency`` is null — verbatim for exposures incurred before
# 1 January 2027 (123B(3)(b)), as a conservative proxy for later ones, where
# 123B(1) obliges the institution to know the income currency. One WARNING per
# run with the count, split by value date.
ERROR_INCOME_CURRENCY_UNKNOWN = "SA010"
# A PSE counterparty that is not definitely UK (non-GB, or no country_code) with
# a NULL is_equivalent_jurisdiction. Null means NOT equivalent, so CRR
# Art. 116(5)'s "Otherwise ... 100 %" weights every exposure to it AND every
# guarantee it provides (Art. 235(1) prices the covered part at the guarantor's
# direct weight) at 100% — for a PSE in an equivalent jurisdiction that left the
# column unpopulated, a 20% Table 2 / 2A weight becomes 100%. The weight is right
# on the data supplied; the warning makes the data-migration hazard visible. One
# WARNING per run with the count, from the classifier's counterparty census
# (engine/classify/audit.py::collect_input_warnings). An explicit False is a
# determination, not a gap, and does not count.
ERROR_PSE_EQUIVALENCE_UNASSERTED = "SA011"

# Supporting factor error codes
ERROR_SME_MISSING_COUNTERPARTY_REF = "SF001"

# Real estate loan-splitter error codes (CRR Art. 125/126, B3.1 Art. 124F/H)
ERROR_RE_NON_ELIGIBLE_COLLATERAL = "RE001"
ERROR_RE_ZERO_EFFECTIVE_CAP = "RE002"
ERROR_RE_MIXED_PROPERTY_TYPES = "RE003"
ERROR_RE_CRR_RENTAL_COVERAGE_FAILED = "RE004"
# Real-estate evidence (CL-08 / RE-10). RE005: a real-estate class (a mortgage
# product label) with no linked property collateral and no LTV — the
# preferential real-estate weights are withheld (CRR Art. 124(1)/125(1); PS1/26
# glossary "real estate exposure", Art. 124A(1)(a)). RE006: an LTV derived from
# the linked property value because no ``property_ltv`` was supplied (PS1/26
# Art. 124C(1)-(3)).
ERROR_RE_NO_PROPERTY_EVIDENCE = "RE005"
ERROR_RE_LTV_DERIVED = "RE006"

# Securitisation allocator validation codes (phase 1: flag + exclude).
# References: CRR Art. 109, Art. 244-246 (significant risk transfer);
# PRA PS1/26 Art. 147A(1)(j).
ERROR_SEC_OVER_ALLOCATED = "SEC001"
ERROR_SEC_INVALID_PCT = "SEC002"
ERROR_SEC_UNKNOWN_REFERENCE = "SEC003"
ERROR_SEC_DUPLICATE = "SEC004"
ERROR_SEC_FULLY_SECURITISED = "SEC005"
# An allocation row whose ``significant_risk_transfer`` is explicitly False
# carves nothing out: CRR Art. 244(1) / 245(1) let the originator exclude the
# underlying exposures only where significant credit risk has been transferred
# (limb (a)) or every retained position takes 1,250% / is deducted (limb (b)),
# and the engine has no securitisation-position route to evidence limb (b). The
# exposure stays on balance sheet at its full weight; WARNING, one per run.
ERROR_SEC_NO_SIGNIFICANT_RISK_TRANSFER = "SEC006"

# Configuration error codes
ERROR_INVALID_CONFIG = "CFG001"
ERROR_MISSING_PERMISSION = "CFG002"
# PS1/26 Credit Risk: General Provisions rules 4.1-4.10 (equity transitional).
# A WARNING, never an RWA change: the configured firm fact and election lead to
# a treatment the engine does not apply. Two cases share it — a firm that had
# IRB permission on 31 December 2026 and has not made the rule 4.9 election
# (rules 4.5 / 4.6 are not implemented, so the Art. 133 weights it receives are
# the 4.9 election's), and a firm without that permission that set ``opt_out``
# (rule 4.9 replaces only 4.5, 4.6 and 4.8, so there is nothing to elect and the
# rule 4.2 / 4.3 weights still apply to its direct equity).
ERROR_EQUITY_TRANSITIONAL_CONFIG = "CFG003"

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

# Aggregator facility-share fallback code. Every priced candidate of one shared
# facility carried a non-finite / absent own-approach RWA, so the riskiest-member
# ranking decided nothing and a deterministic ordering allocated the commitment
# instead. A WARNING rather than an error: the exposure is still capitalised
# (never dropped), but the member it was capitalised against was not chosen by
# the policy metric, and that must not be silent.
ERROR_FACILITY_SHARE_FALLBACK = "AGG003"

# Group-wide obligor aggregation code. On a solo / sub-consolidated run the
# retail threshold (CRR Art. 123(c); PS1/26 Art. 123(1)(b)(ii) / 123A(1)(b)(ii) /
# 147(5)(a)(ii)) counts the amount the obligor owes to the institution, its parent
# undertakings, its subsidiaries and subsidiaries of its parent undertakings —
# i.e. every entity in the reporting-entity registry, not only the run's books.
# A WARNING naming the rows that failed the threshold ONLY because of debt booked
# in other group entities, so a solo classification that differs from what the
# solo books alone show is never silent. Counted over natural persons and
# SME-sized obligors only — the obligors the retail threshold governs.
ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES = "AGG004"

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

# Published supervisory validation-rule codes (reporting.filing). These are
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


def uncommitted_facility_risk_type_warning(
    *, facility_reference: str, risk_type: str
) -> CalculationError:
    """Create a HIE004 warning: an uncommitted facility declared a non-UCC risk_type.

    ``committed=False`` is the documented encoding of an accepted commitment the
    institution may cancel unconditionally at any time. Its undrawn headroom is
    therefore priced in the UCC bucket (``LR``: PS1/26 Table A1 row (7) 10%; CRR
    Annex I 4(a) 0%) and the declared ``risk_type`` is not used. The warning
    exists because the two inputs contradict each other: either the line is not
    unconditionally cancellable (set ``committed=True``) or its risk type is LR.
    ``exposure_reference`` carries the facility reference (the undrawn row's
    ``source_exposure_reference``).

    References:
    - PRA PS1/26 Glossary "commitment"; Art. 111 Table A1 row (7)
    - CRR Art. 111, Annex I item 4(a)
    """
    return CalculationError(
        code=ERROR_UNCOMMITTED_FACILITY_RISK_TYPE,
        message=(
            f"Facility '{facility_reference}' has committed=False (an accepted, "
            "unconditionally cancellable commitment) but declares risk_type "
            f"'{risk_type}'. Its undrawn headroom is priced in the UCC bucket LR "
            "(PS1/26 Table A1 row (7); CRR Annex I 4(a)); set committed=True if the "
            "line cannot be cancelled unconditionally."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.HIERARCHY,
        exposure_reference=facility_reference,
        regulatory_reference="PS1/26 Art. 111 Table A1 row (7); CRR Annex I 4(a)",
        field_name="risk_type",
        expected_value="LR (or committed=True)",
        actual_value=risk_type,
    )


def facility_headroom_fx_rate_missing_warning(
    *,
    facility_reference: str,
    currency: str,
    facility_currency: str,
    umbrella_reference: str | None = None,
) -> CalculationError:
    """Create a HIE005 warning: an amount could not be put in its facility's currency.

    Undrawn headroom is ``limit - utilisation`` in the FACILITY's currency, so a
    drawing in another currency is converted at the run's FX rates before it is
    netted. Where the run holds no rate for one side, the amount is not netted —
    the headroom is never reduced by an amount the run cannot measure — and this
    warning names the facility and the currency. With ``umbrella_reference`` set,
    the facility is a sub-facility whose own limit could not be expressed in its
    umbrella's currency, so it takes no slice of the umbrella's waterfall (the
    umbrella's residual row carries that headroom instead).

    References:
    - CRR Art. 4(1)(56); PRA PS1/26 Glossary "conversion factor"
    - CRR Art. 111(1); PRA PS1/26 Art. 111(1)(b)
    """
    if umbrella_reference is None:
        effect = (
            f"Utilisation in {currency} could not be converted into the facility "
            f"currency {facility_currency}: the run holds no FX rate for it. Those "
            "amounts were not netted, so the facility's undrawn commitment is "
            "measured gross of them."
        )
    else:
        effect = (
            f"Its {currency} limit could not be expressed in the currency "
            f"{facility_currency} of umbrella '{umbrella_reference}': the run holds "
            "no FX rate for it. The sub-facility takes no slice of the umbrella's "
            "waterfall; the umbrella's residual row carries that headroom."
        )
    return CalculationError(
        code=ERROR_FACILITY_HEADROOM_FX_RATE_MISSING,
        message=f"Facility '{facility_reference}': {effect} Supply the missing fx_rates row.",
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.HIERARCHY,
        exposure_reference=facility_reference,
        regulatory_reference="CRR Art. 4(1)(56); PS1/26 Glossary 'conversion factor'",
        field_name="currency",
        expected_value=facility_currency,
        actual_value=currency,
    )


def facility_limit_missing_warning(*, facility_reference: str) -> CalculationError:
    """Create a HIE006 warning: a facility has no limit, so no undrawn commitment.

    The extent of a commitment is "determined by the advised limit" (CRR Art.
    4(1)(56); PS1/26 Glossary "conversion factor"). With ``limit`` null the
    undrawn amount is unknown, and the engine does not invent one: no undrawn row
    is generated. Not raised for an umbrella (a facility with sub-facilities),
    where a null limit legitimately means "no cap above the sub-limits".

    References:
    - CRR Art. 4(1)(56); PRA PS1/26 Glossary "conversion factor"
    """
    return CalculationError(
        code=ERROR_FACILITY_LIMIT_MISSING,
        message=(
            f"Facility '{facility_reference}' has no limit, so its undrawn "
            "commitment cannot be measured and no undrawn exposure row was "
            "generated. Supply the advised limit (or 0 if nothing was committed)."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.HIERARCHY,
        exposure_reference=facility_reference,
        regulatory_reference="CRR Art. 4(1)(56); PS1/26 Glossary 'conversion factor'",
        field_name="limit",
    )


def facility_warning_summary(
    *,
    code: str,
    omitted: int,
    sample_cap: int,
    detail: str,
    category: ErrorCategory = ErrorCategory.HIERARCHY,
) -> CalculationError:
    """Create the one summary that closes a sampled HIE004-HIE006 / DQ021 group.

    The facility-undrawn warnings follow the estate's ``sample_cap`` contract
    (as DQ005 / DQ013 do): up to ``sample_cap`` facilities are named one per
    warning, then this single WARNING carries the truthful count of the rest,
    so a systemic gap — a whole multi-currency book with no FX table — stays
    readable instead of raising one warning per facility. ``actual_value``
    holds the omitted count; ``exposure_reference`` is None (no one facility).
    ``category`` follows the code it closes (DATA_QUALITY for DQ021).
    """
    return CalculationError(
        code=code,
        message=(
            f"{omitted} additional facility warning(s) omitted beyond "
            f"sample_cap={sample_cap}: {detail}"
        ),
        severity=ErrorSeverity.WARNING,
        category=category,
        actual_value=str(omitted),
    )


def facility_multi_parent_warning(
    *,
    child_reference: str,
    child_type: str,
    parents: Sequence[str],
    kept: str,
    ignored: Sequence[str] = (),
) -> CalculationError:
    """Create a DQ021 warning for a facility-mapping child with several parents.

    A facility hierarchy is a tree, and every consumer of ``facility_mappings``
    assumed one: a sub-facility's root was taken from a last-wins dict over an
    unordered ``unique()`` (so RWA changed from run to run), and a loan or
    contingent consumed the headroom of EVERY facility it was mapped to (review
    findings RC-01 / RC-02 / SF-03). The hierarchy stage now resolves the
    mapping deterministically, and this warning says how:

    - ``child_type == "facility"``: ``kept`` is the one parent the sub-facility
      is attached to (the lowest reference); ``ignored`` the parents dropped.
    - a loan / contingent: ``kept`` is the ROOT whose headroom it reduces — the
      root of its lowest-referenced parent. Every mapping under that root is
      kept (an overlapping sub-limit genuinely constrains the same drawing), but
      the root's headroom is reduced once. ``ignored`` lists the parents under
      any other root; those facilities' commitments are measured gross of it.

    Reference: CRR Art. 4(1)(56) / PS1/26 Glossary "conversion factor" — the
    undrawn amount is that of "the commitment ... determined by the advised
    limit", which one drawing reduces once.
    """
    listed = ", ".join(parents)
    if child_type == "facility":
        resolution = (
            f"A facility hierarchy is a tree, so it is attached to '{kept}' (the "
            "lowest reference) only: its limit, drawings and undrawn slice count "
            "once, under that parent. The parent no longer depends on row order."
        )
    elif ignored:
        resolution = (
            f"It reduces the headroom under root '{kept}' only (the root of its "
            f"lowest-referenced parent); the mapping(s) to {', '.join(ignored)} are "
            "ignored, so those facilities' undrawn commitments are measured gross "
            "of it rather than reduced a second time."
        )
    else:
        resolution = (
            f"All of them hang under root '{kept}': it reduces each mapped "
            f"sub-limit's own headroom, but '{kept}''s headroom only once."
        )
    return CalculationError(
        code=ERROR_FACILITY_MAPPING_MULTI_PARENT,
        message=(
            f"[facility_mappings] {child_type} '{child_reference}' is mapped under "
            f"{len(parents)} parent facilities ({listed}). {resolution}"
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=child_reference,
        regulatory_reference="CRR Art. 4(1)(56); PS1/26 Glossary 'conversion factor'",
        field_name="parent_facility_reference",
        expected_value="one parent facility per child",
        actual_value=listed,
    )


def facility_mapping_cycle_warning(*, members: Sequence[str]) -> CalculationError:
    """Create a DQ022 warning for facility mappings that form a cycle.

    Every facility on a cycle is somebody's child, and only root / standalone
    facilities emit an undrawn row, so a cycle used to delete every member's
    undrawn commitment with no error (review finding RC-02: a two-facility
    cycle took EAD from 2.25m to 0.5m). The hierarchy stage now treats every
    member as a root of its own — each keeps its own limit and emits its own
    undrawn commitment, netted only by its own children — which is the
    conservative reading of a graph that names no root.

    ``members`` is the cycle, sorted; ``actual_value`` holds it joined.
    """
    listed = ", ".join(members)
    return CalculationError(
        code=ERROR_FACILITY_MAPPING_CYCLE,
        message=(
            f"[facility_mappings] facilities {listed} form a cycle of parent "
            "mappings, so none of them has a root. Each is treated as a root "
            "facility of its own: it keeps its own limit and emits its own undrawn "
            "commitment instead of every member being dropped as a sub-facility."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=members[0] if members else None,
        regulatory_reference="CRR Art. 111(1); PS1/26 Art. 111(1)",
        field_name="parent_facility_reference",
        expected_value="an acyclic facility hierarchy",
        actual_value=listed,
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


def pse_equivalence_unasserted_warning(*, n: int) -> CalculationError:
    """Create the SA011 warning for PSE counterparties with no equivalence flag.

    CRR Art. 116(5): a third-country PSE may take the Art. 116(1)/(2) weights
    only where the Treasury has determined its jurisdiction equivalent;
    "Otherwise the institutions shall apply a risk weight of 100 %". PS1/26
    Art. 116(3A) keeps that gate under Basel 3.1. ``is_equivalent_jurisdiction``
    has no default (null means not equivalent), so the engine applies the 100% to
    these counterparties as obligors and as guarantors. One aggregate warning
    carries the count of counterparty rows.
    """
    return CalculationError(
        code=ERROR_PSE_EQUIVALENCE_UNASSERTED,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"{n} public sector entity counterparty row(s) outside the UK (or with no "
            "country_code) carry no is_equivalent_jurisdiction. A null flag means no "
            "Treasury equivalence determination, so CRR Art. 116(5) weights every "
            "exposure to them, and every guarantee they provide, at 100% (in place of "
            "the Art. 116(1)/(2) Table 2 / 2A weight). Set is_equivalent_jurisdiction "
            "to True for PSEs in an equivalent jurisdiction, or to False to confirm "
            "the 100%."
        ),
        regulatory_reference="CRR Art. 116(5) / PRA PS1/26 Art. 116(3A)",
        field_name="is_equivalent_jurisdiction",
    )


def pf_phase_unevidenced_warning(*, n: int) -> CalculationError:
    """Create the SA006 warning for project-finance rows with no recognised phase.

    PRA PS1/26 Art. 122B(2)(c) weights an unrated project-finance exposure
    130% in the pre-operational phase and 100% in the operational phase
    (80% when also high quality, Art. 122B(4)); Art. 122B(3) defines the
    operational phase by conditions the firm must show. A null or
    unrecognised ``project_phase`` therefore demonstrates nothing, and the
    engine treats the exposure as pre-operational. One aggregate warning
    carries the count, mirroring the classifier roll-ups (CLS010, DQ008).
    """
    return CalculationError(
        code=ERROR_PF_PHASE_UNEVIDENCED,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"{n} project-finance exposure(s) carry no recognised project_phase "
            "(null, or not one of pre_operational / operational / "
            "high_quality_operational). PS1/26 Art. 122B(3) requires the "
            "operational phase to be demonstrated, so they are treated as "
            "pre-operational: 130% under Art. 122B(2)(c) when unrated."
        ),
        regulatory_reference="PRA PS1/26 Art. 122B(2)(c) / Art. 122B(3)",
        field_name="project_phase",
    )


def slotting_category_missing_warning(*, n: int) -> CalculationError:
    """Create the CLS012 warning for slotted rows with no recognised grade.

    CRR Art. 153(5) and PRA PS1/26 Art. 153(5) assign a slotted exposure the
    risk weight of the category the institution grades it into; an exposure
    with no grade has not been slotted. The engine keeps the cited pack
    default (``satisfactory``, which the slotting weight and expected-loss
    tables carry as their ``default``) — whether a missing grade should
    instead take ``weak`` is an open owner decision (review IV-09) — and this
    aggregate warning, carrying the row count, makes the substitution visible.
    """
    return CalculationError(
        code=ERROR_SLOTTING_CATEGORY_MISSING,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"{n} slotting exposure(s) carry no recognised slotting_category (null, "
            "or not one of strong / good / satisfactory / weak / default). They are "
            "weighted at the 'satisfactory' grade, the pack default, for both the "
            "risk weight and the expected-loss rate. Art. 153(5) weights a slotted "
            "exposure by the grade the institution assigns: an obligor that is in "
            "fact weak is understated, one in default is misstated."
        ),
        regulatory_reference="CRR Art. 153(5) / PRA PS1/26 Art. 153(5)",
        field_name="slotting_category",
    )


def no_property_evidence_warning(*, n_standardised: int, n_other: int) -> CalculationError:
    """Create the RE005 warning: a real-estate class with no evidence of security.

    A mortgage product label is not security. The PS1/26 glossary defines a
    real estate exposure as "an ADC exposure or an exposure secured by a charge
    on immovable property", and CRR Art. 125(1) reaches only exposures "fully
    and completely secured by mortgages on residential property". An exposure
    whose class came from its product label alone, with no property collateral
    linked at any level and no LTV supplied, is therefore not given
    the preferential real-estate weights: a Standardised-Approach row takes the
    class of its counterparty, and an IRB row keeps its IRB class while its
    Standardised-equivalent weight (the Basel 3.1 output floor) is the
    counterparty-class weight. One roll-up per run, counting both populations.
    """
    return CalculationError(
        code=ERROR_RE_NO_PROPERTY_EVIDENCE,
        message=(
            f"{n_standardised + n_other} exposure(s) carry a mortgage product label but "
            "no property collateral is linked to them and no LTV is "
            "supplied, so they are not treated as secured by real estate: "
            f"{n_standardised} Standardised-Approach exposure(s) take their "
            f"counterparty's exposure class, and {n_other} IRB exposure(s) keep their "
            "IRB class with a counterparty-class Standardised-equivalent weight. "
            "Link the property (collateral_type 'real_estate' with market_value) or "
            "supply property_ltv to claim the real-estate treatment."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        regulatory_reference="CRR Art. 124(1), 125(1); PS1/26 Art. 124, 124A(1)(a)",
        field_name="property_ltv",
    )


def ltv_derived_warning(*, n: int) -> CalculationError:
    """Create the RE006 warning: an LTV derived because none was supplied.

    PS1/26 Art. 124C(1): "The loan-to-value (LTV) ... is the amount of the loan
    divided by the value of the property"; (2) the amount of the loan includes
    the outstanding amount and any undrawn committed amount; (3) it includes
    loans secured by charges ranking ahead. Where a property is linked to an
    exposure with a ``market_value`` but no ``property_ltv``, the hierarchy stage
    derives the LTV that way rather than leaving it null (which used to price
    CRR at the 35% band and Basel 3.1 at an LTV of 100%). The derivation is a
    substitution for a missing input, so it is reported, once per run.
    """
    return CalculationError(
        code=ERROR_RE_LTV_DERIVED,
        message=(
            f"property_ltv not supplied on {n} exposure(s) secured by a linked property; "
            "the LTV was derived as (drawn + accrued interest + undrawn committed "
            "amount) / property market value, plus any prior-charge LTV "
            "(PS1/26 Art. 124C(1)-(3)). Supply property_ltv to use the firm's own "
            "Art. 124C / Art. 124D figure."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        regulatory_reference="PS1/26 Art. 124C(1)-(3); CRR Art. 125(2)(d), 126(2)(d)",
        field_name="property_ltv",
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


def issued_item_on_commitment_risk_type_warning(*, context: str, n: int) -> CalculationError:
    """Create a DQ017 warning for a contingent on a commitment bucket marked as issued.

    ``risk_type`` is ``MR`` (the NIF / RUF commitment bucket) or ``OC`` (other
    commitments) but ``is_obs_commitment`` is False — the contingent default,
    which marks an issued item. Under CRR F-IRB the engine follows the flag and
    prices the row on the Art. 166(10)(b) issued-item 50% rather than the
    Art. 166(8)(d) 75% the bucket names, and under Basel 3.1 A-IRB the row is not a
    revolving loan commitment, so no own estimate of conversion factor or EAD
    applies (PS1/26 Art. 166D(1)(b)); the SA factor is the same either way.
    The contradiction is reported, not resolved: setting the flag for the
    preparer would overstate an issued medium-risk item that was simply coded
    ``MR`` instead of ``MR_ISSUED`` (CM-09).

    References:
    - CRR Art. 166(8)(d): NIFs / RUFs / other credit lines 75%
    - CRR Art. 166(10)(b): issued medium-risk items 50%
    - PRA PS1/26 Art. 166D(1): A-IRB own estimates for revolving loan commitments only
    """
    return CalculationError(
        code=ERROR_ISSUED_ITEM_ON_COMMITMENT_RISK_TYPE,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[{context}] {n} row(s) carry a commitment 'risk_type' (MR = NIF / RUF, "
            "OC = other commitment) but 'is_obs_commitment' is False (an issued "
            "item, the contingent default). Under CRR F-IRB they take the "
            "Art. 166(10)(b) issued-item 50% instead of the Art. 166(8)(d) 75%, and "
            "under Basel 3.1 A-IRB they are not revolving loan commitments, so no own "
            "estimate applies (PS1/26 Art. 166D(1)(b)) — set 'is_obs_commitment' True "
            "for a commitment booked as a contingent, or use 'MR_ISSUED' for an issued "
            "medium-risk item."
        ),
        field_name="is_obs_commitment",
        regulatory_reference="CRR Art. 166(8)(d); Art. 166(10)(b); PS1/26 Art. 166D(1)",
    )


def unsupported_ciu_holding_class_warning(*, n: int, values: list[str]) -> CalculationError:
    """Create an SA008 warning for CIU holdings with an unidentified exposure class.

    ``ciu_holdings.exposure_class`` carries no categorical domain of its own, so
    a value the engine does not know -- ``securitisation``, ``subordinated_debt``,
    a typo, a null -- used to fall through the (exposure_class, CQS) join to a
    flat 100%. PS1/26 Art. 132A(1) weights each underlying "as if directly held",
    which an unidentified class cannot be, so the look-through calculation takes
    the Art. 132(2) 1,250% fall-back for that slice of the fund (Art. 132(2)
    permits "a combination of the approaches"). This warning names the values.

    References:
    - PRA PS1/26 Art. 132(2), 132A(1); CRR Art. 132 as it applied before
      revocation (PRA Rulebook Credit Risk: Standardised Approach (CRR) Part)
    """
    return CalculationError(
        code=ERROR_CIU_HOLDING_CLASS_UNSUPPORTED,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[ciu_holdings] {n} row(s) carry an exposure_class outside the "
            f"ExposureClass vocabulary ({', '.join(values)}). An underlying the "
            "engine cannot identify cannot be risk weighted as if directly held, so "
            "a look-through fund holding it takes the 1,250% fall-back on that "
            "holding's value."
        ),
        field_name="exposure_class",
        regulatory_reference="PS1/26 Art. 132(2), 132A(1)",
    )


def failed_trade_side_unknown_warning(*, failed_trade_id: str) -> CalculationError:
    """Create a CCR031 warning for a DvP failed trade whose side is not supplied.

    CRR Art. 378 charges the price difference "where the difference could
    involve a loss for the credit institution" — a seller loses when the market
    value has fallen below the agreed price, a purchaser when it has risen above
    it. With ``is_purchase`` null the engine cannot tell which, so it charges the
    absolute difference (conservative for either side); this warning names the
    trade so the preparer can supply the side (review item CC-09).
    """
    return CalculationError(
        code=ERROR_FAILED_TRADE_SIDE_UNKNOWN,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[ccr.failed_trades] DvP failed trade {failed_trade_id!r} has no "
            "'is_purchase', so the side that can lose is unknown: the absolute price "
            "difference is charged (CRR Art. 378). Supply 'is_purchase' to charge only "
            "a loss-making difference."
        ),
        exposure_reference=f"ft__{failed_trade_id}",
        field_name="is_purchase",
        regulatory_reference="CRR Art. 378",
    )


def dfc_allocation_input_missing_error(
    *, contribution_id: str, missing: list[str]
) -> CalculationError:
    """Create a CCR032 error for a QCCP pre-funded contribution Art. 308(2) cannot allocate.

    CCR (CRR) Part Art. 308(2): ``K_i = max(K_CCP x DF_i / (DF_CCP + DF_CM),
    8% x 2% x DF_i)``. Without ``K_CCP`` or ``DF_CM`` (both communicated by the
    CCP under EMIR Art. 50c) only the floor can be evaluated, so the engine
    charges it as a lower bound and this error names the contribution — the
    true requirement can be higher (review item CC-10).
    """
    return CalculationError(
        code=ERROR_DFC_ALLOCATION_INPUT_MISSING,
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        message=(
            f"[ccr.default_fund_contributions] QCCP pre-funded contribution "
            f"{contribution_id!r} has no {' or '.join(repr(m) for m in missing)}, so its "
            "share of K_CCP cannot be allocated (CRR Art. 308(2)): only the 8% x 2% x DF_i "
            "floor is charged, which can understate. Supply the CCP's published values."
        ),
        exposure_reference=f"dfc__{contribution_id}",
        field_name=missing[0],
        regulatory_reference="CRR Art. 308(2)",
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


def exposure_reference_collision_error(
    *,
    reference: str,
    namespaces: Sequence[str],
    qualified: Sequence[str],
) -> CalculationError:
    """Create a DQ019 error for an exposure_reference claimed by several namespaces.

    ``namespaces`` names every table (or engine-minted family) that produces an
    exposure row with this reference; ``qualified`` the references the
    colliding loan / contingent rows are published under instead
    (``<reference>#loan`` / ``<reference>#contingent``), empty when none of the
    claimants is a lending row the stage can re-key.

    One per colliding reference and uncapped, for the reason
    :func:`duplicate_input_key_error` gives: the finding is a property of a
    row, and a sampled collision leaves the un-sampled ones as merged as before.
    Severity is ERROR: before the re-key the two rows merged downstream (the
    IRB model-permission de-duplication kept one of them; a guarantee on one
    covered both), so the input was reporting one exposure's capital twice or
    not at all, and even after it a pointer that does not say which row it
    means (``beneficiary_type`` ``'exposure'`` or null) matches neither.

    Reference: CRR / PS1/26 Art. 111(1) — each item's exposure value is
    measured; Art. 213(1)(a) — "the credit protection is direct".
    """
    listed = ", ".join(namespaces)
    if qualified:
        resolution = (
            "The rows are kept apart: each colliding loan / contingent is published "
            f"as {', '.join(repr(q) for q in qualified)}, and every pointer to it "
            "(facility mapping, short-term rating scope, collateral / guarantee / "
            "provision beneficiary, securitisation allocation) is resolved by its "
            "declared type. A pointer whose type does not say which row it means "
            "(beneficiary_type 'exposure' or null) now matches neither."
        )
    else:
        resolution = (
            "None of the claimants is a loan or contingent row the hierarchy stage "
            "can re-key, so the rows may still merge downstream."
        )
    return CalculationError(
        code=ERROR_EXPOSURE_REFERENCE_COLLISION,
        message=(
            f"exposure_reference '{reference}' is claimed by more than one exposure "
            f"namespace ({listed}). Uniqueness was declared per table only, and every "
            "join keyed on the bare reference merges the rows. "
            f"{resolution} Give every exposure a reference unique across tables."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        exposure_reference=reference,
        regulatory_reference="CRR Art. 111(1); Art. 213(1)(a)",
        field_name="exposure_reference",
        expected_value="one exposure namespace per reference",
        actual_value=listed,
    )


def fx_rate_missing_error(
    *,
    currency: str,
    base_currency: str,
    rows: int,
    detail: str,
) -> CalculationError:
    """Create a DQ020 error for amounts in a currency with no rate into the base.

    ``engine/fx`` converts an amount only where ``fx_rates`` holds a
    ``currency -> base_currency`` rate; any other amount passes through in its
    SOURCE currency's units while its row keeps the source currency code, and
    every downstream threshold, total and template then reads it as reporting
    currency — a 1:1 conversion nobody chose (review finding RC-11). The
    direction depends on the currency (1m KWD read as GBP understates by ~60%,
    1m ZAR overstates ~20x), so the defect is the silence, which this ends. The
    amounts are still passed through unconverted: the engine has no rate to
    apply and must not invent one.

    ``detail`` lists the affected rows and amounts per table; ``actual_value``
    is the currency, ``expected_value`` the missing pair.
    """
    return CalculationError(
        code=ERROR_FX_RATE_MISSING,
        message=(
            f"No FX rate {currency} -> {base_currency} in fx_rates: {rows} row(s) "
            f"carry {currency} amounts ({detail}), which are NOT converted and are "
            f"read as {base_currency} by every threshold, total and template "
            f"downstream. Supply the {currency} -> {base_currency} rate."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        field_name="currency",
        expected_value=f"an fx_rates row {currency} -> {base_currency}",
        actual_value=currency,
    )


def engine_only_risk_type_error(
    *,
    table: str,
    column: str,
    value: str,
    count: int,
    disregarded: bool,
) -> CalculationError:
    """Create a DQ023 error for an engine-only risk type on a lending table.

    ``CCR_DERIVATIVE`` / ``CCR_SFT`` / ``CCR_DEFAULT_FUND`` /
    ``SETTLEMENT_FAILED_TRADE`` tag the rows the counterparty-credit-risk stages
    mint. On a lending row the first two used to be accepted silently and
    route it to the CCR treatment — a contingent priced at a CCF on its nominal
    amount yet labelled ``standardised_ccr`` and reported on C 07.00's CCR
    rows, a ``CCR_SFT`` row given the repo-style IRB maturity (review finding
    CC-19). The exposure value of a derivative or an SFT is not an Annex I /
    Table A1 CCF on a nominal amount at all (CRR Art. 111(2); PS1/26 Art. 111(2)
    / (2A)).

    ``disregarded`` says what the hierarchy stage does with the value
    (``data/schemas.py::DISREGARDED_ENGINE_ONLY_RISK_TYPES``). True for the two
    CCR routing tags: the value is rewritten to ``DQ023:<TAG>``, an explicit but
    unrecognised risk type, so the row keeps the residual CCF it had —
    ``obs_product`` is not consulted, an explicit risk type outranks it — and
    loses only the CCR routing. False for the two own-funds tags: their 1250%
    weight is kept, since disregarding it would cut the row's RWA. Lending
    tables carry ``is_sft`` for a repo-style maturity.
    """
    canonical = value.strip().upper()
    if disregarded:
        treatment = (
            f"The value is disregarded: it is rewritten to 'DQ023:{canonical}', an "
            "unrecognised risk type, so the row keeps the CCF residual it had "
            "(obs_product is not consulted - an explicit risk_type outranks it) and "
            "loses only the counterparty-credit-risk routing."
        )
    else:
        treatment = (
            "The value is honoured: it selects the 1250% own-funds conversion, which "
            "the row keeps, because disregarding the tag would lower its capital."
        )
    return CalculationError(
        code=ERROR_ENGINE_ONLY_RISK_TYPE,
        message=(
            f"[{table}] '{column}' = '{value}' on {count} row(s): this risk type is "
            "minted by the counterparty-credit-risk stages for their own rows and is "
            f"not a lending-table category. {treatment} Book derivatives, SFTs, "
            "failed trades and default-fund contributions in the CCR / SFT inputs, "
            "or flag a repo-style loan with is_sft."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        regulatory_reference="CRR Art. 111(2); PS1/26 Art. 111(2) / (2A)",
        field_name=column,
        expected_value="a lending risk type (FR, FRC, MR, MR_ISSUED, OC, MLR, LR)",
        actual_value=value,
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


def facility_share_fallback_warning(*, group: str, candidate_count: int) -> CalculationError:
    """Create an AGG003 warning for a facility share resolved by the fallback rule.

    Raised by the aggregator's facility-share resolver when EVERY priced
    candidate of one shared facility carries a non-finite (NaN / inf) or absent
    own-approach RWA, so the ranking metric decides nothing. The group is never
    dropped — dropping every candidate would delete the facility's undrawn
    commitment from the submission outright — so a deterministic ordering
    (risk weight descending, then the counterparty reference) picks the member
    instead. This warning is what makes that substitution attributable: a
    fallback nobody is told about is indistinguishable from a ranked outcome.
    """
    return CalculationError(
        code=ERROR_FACILITY_SHARE_FALLBACK,
        message=(
            f"Facility share '{group}': all {candidate_count} priced candidate(s) "
            "carry a non-finite or absent own-approach RWA, so the riskiest-member "
            "ranking could not be applied. The commitment was allocated by the "
            "deterministic fallback (highest risk weight, then lowest counterparty "
            "reference). Check the candidates' PD / LGD / EAD inputs."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        field_name=group,
        actual_value=str(candidate_count),
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
