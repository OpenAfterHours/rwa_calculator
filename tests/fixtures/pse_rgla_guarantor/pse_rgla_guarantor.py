"""
Generate PSE/RGLA-guarantor fixtures: IRB borrower + PSE / RGLA SA guarantors (Phase 4 Slice 5).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/irb/guarantee.py)

Scenario design (IRB-guarantor PSE/RGLA substitution gap — recorded Phase 4 fix):

    A single F-IRB corporate borrower holds four fully-drawn GBP 1,000,000 term loans,
    each fully covered by an unfunded guarantee from a different public-sector guarantor.
    Every guarantor is external-rating-only (or unrated) — no internal PD — so
    ``guarantor_approach`` resolves to "sa" and the engine must price the guarantee via
    the SA risk-weight substitution method (RWSM) in
    ``engine/irb/guarantee.py::_compute_guarantor_rw_sa``.

    Defect under test (pre-fix):
        ``_compute_guarantor_rw_sa`` has no "pse" / "rgla" branches — those classes fall
        to ``.otherwise(pl.lit(None))``, so ``guarantor_rw`` is null,
        ``is_guarantee_beneficial`` is False, and the guarantee is silently discarded
        with status ``GUARANTEE_NOT_APPLIED_NON_BENEFICIAL`` (rwa stays at the
        borrower's own IRB RWA). The SA-side twin
        (``engine/sa/namespace.py::_build_guarantor_rw_expr``) already grants PSE
        Art. 116(2) Table 2A and RGLA Art. 115(1)(b) Table 1B treatment.

Counterparties (5 rows):
    CP_BORROWER_PSERGLA: entity_type="company" (SA/IRB: CORPORATE),
        annual_revenue=100,000,000 (> GBP 44m, non-SME), GB.
        Rated internally (pd=0.02, model_id=MODEL_BORROWER_FIRB) → F-IRB.
    CP_GTR_PSE_CQS2:  entity_type="pse_institution", GB — rated CQS 2 (external, pd=None).
    CP_GTR_PSE_CQS3:  entity_type="pse_institution", GB — rated CQS 3 (external, pd=None).
    CP_GTR_RGLA_GB:   entity_type="rgla_institution", GB — NO rating rows (unrated).
    CP_GTR_RGLA_DE:   entity_type="rgla_institution", DE — NO rating rows (unrated).

Loans (4 rows, one per guarantor — all on CP_BORROWER_PSERGLA):
    LOAN_PSE_CQS2 / LOAN_PSE_CQS3 / LOAN_RGLA_GB / LOAN_RGLA_DE:
        GBP 1,000,000 drawn senior term loans, effective_maturity=5.0y.

Guarantees (4 rows): 100% coverage, original_maturity_years=5.0 (>= 1y, Art. 237(2)(a)
    eligible), currency="GBP" matches the loans (no Art. 233(3) FX haircut).

Ratings (3 rows):
    Borrower: rating_type="internal", pd=0.02, model_id=MODEL_BORROWER_FIRB.
    PSE CQS2 guarantor: rating_type="external", cqs=2, pd=None (CRITICAL — forces
        guarantor_approach="sa" → RWSM → _compute_guarantor_rw_sa).
    PSE CQS3 guarantor: rating_type="external", cqs=3, pd=None.
    The RGLA guarantors deliberately have NO rating rows (guarantor_cqs null).

Model permissions (1 row):
    MODEL_BORROWER_FIRB: foundation_irb for exposure_class="corporate" — only the
    borrower's rating references it; guarantors cannot route IRB.

Hand-calculation (POST-FIX expected values — never derived from the engine):

    All loans: EAD = drawn + interest = 1,000,000 + 0 = 1,000,000 GBP; 100% coverage →
    blended RW = guarantor_rw, rwa_final = EAD x guarantor_rw on the guaranteed sub-row.

    Scenario A — rated PSE guarantor CQS 2 (CRR Art. 116(2) Table 2A; PS1/26 identical):
        guarantor_rw = 0.50 → rwa_final = 500,000 (both frameworks).
        Anti-confound: CQS 2 distinguishes a PSE Table 2A hit (50%) from a CGCB
        misroute (20%) and, on the B31 arm, an institution-ECRA misroute (30%).

    Scenario A2 — rated PSE guarantor CQS 3 (anti-corporate confound):
        PSE Table 2A CQS 3 = 50% vs corporate CRR Table 5 = 100% / B31 Table 6 = 75%
        → guarantor_rw = 0.50, rwa_final = 500,000 (both frameworks). Proves the PSE
        table was consulted, not the corporate branch.

    Scenario B — unrated RGLA guarantor (documented SA-side approximation,
        sa/namespace.py _build_guarantor_rw_expr: GB → 20%, else → 100%; NOT the full
        Art. 115(1)(a) sovereign-derived Table 1A — no guarantor sovereign CQS join
        exists; recorded decision):
        GB: guarantor_rw = 0.20 → rwa_final = 200,000.
        DE: guarantor_rw = 1.00 → rwa_final = 1,000,000 — still beneficial: the
            borrower's own F-IRB RW (pd=0.02, LGD 45% CRR / 40% B31, M=5y) is well
            above 100% in both frameworks, so rwa_final < rwa_irb_original.

    Pre-fix (current engine): guarantor_rw = null on every row above,
    rwa_final = rwa_irb_original (guarantee no-op),
    guarantee_status = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL".

Note: the same parquet files serve both framework arms — the acceptance test passes
CalculationConfig.crr() vs CalculationConfig.basel_3_1(); fixture data is config-agnostic.
PSE Table 2A / RGLA Table 1B values are identical under CRR and PS1/26.

References:
    - CRR Art. 116(2) Table 2A: rated PSE risk weights by own CQS (CQS 2/3 = 50%)
    - CRR Art. 115(1)(b) Table 1B: rated RGLA risk weights (same values)
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Art. 237(2)(a): unfunded credit protection original maturity >= 1 year
    - engine/irb/guarantee.py::_compute_guarantor_rw_sa: bug site (.otherwise(null))
    - engine/sa/namespace.py::_build_guarantor_rw_expr: SA-side reference implementation

Usage:
    uv run python tests/fixtures/pse_rgla_guarantor/pse_rgla_guarantor.py
    uv run python tests/fixtures/pse_rgla_guarantor/pse_rgla_guarantor.py --data-dir <dir>
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF: str = "CP_BORROWER_PSERGLA"
GUARANTOR_PSE_CQS2_REF: str = "CP_GTR_PSE_CQS2"
GUARANTOR_PSE_CQS3_REF: str = "CP_GTR_PSE_CQS3"
GUARANTOR_RGLA_GB_REF: str = "CP_GTR_RGLA_GB"
GUARANTOR_RGLA_DE_REF: str = "CP_GTR_RGLA_DE"

# Exposure references (one loan per guarantor, all on the same borrower)
LOAN_PSE_CQS2_REF: str = "LOAN_PSE_CQS2"
LOAN_PSE_CQS3_REF: str = "LOAN_PSE_CQS3"
LOAN_RGLA_GB_REF: str = "LOAN_RGLA_GB"
LOAN_RGLA_DE_REF: str = "LOAN_RGLA_DE"

FACILITY_PSE_CQS2_REF: str = "FAC_PSE_CQS2"
FACILITY_PSE_CQS3_REF: str = "FAC_PSE_CQS3"
FACILITY_RGLA_GB_REF: str = "FAC_RGLA_GB"
FACILITY_RGLA_DE_REF: str = "FAC_RGLA_DE"

GUARANTEE_PSE_CQS2_REF: str = "GTE_PSE_CQS2"
GUARANTEE_PSE_CQS3_REF: str = "GTE_PSE_CQS3"
GUARANTEE_RGLA_GB_REF: str = "GTE_RGLA_GB"
GUARANTEE_RGLA_DE_REF: str = "GTE_RGLA_DE"

# Rating references (RGLA guarantors deliberately have NO rating rows)
RTG_BORROWER_REF: str = "RTG_PSERGLA_BORR"
RTG_PSE_CQS2_REF: str = "RTG_PSERGLA_PSE2"
RTG_PSE_CQS3_REF: str = "RTG_PSERGLA_PSE3"

# Model permission ID
MODEL_ID: str = "MODEL_BORROWER_FIRB"

# Dates — Basel 3.1 effective from 1 Jan 2027 (mirrors p1_122a)
VALUE_DATE: date = date(2027, 1, 2)
MATURITY_DATE: date = date(2032, 1, 2)  # 5y residual
GUARANTEE_MATURITY_DATE: date = date(2032, 1, 2)  # matches loans — no maturity mismatch
RATING_DATE: date = date(2027, 1, 2)

# Loan economics (identical for all four loans)
DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
EAD: float = DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Guarantee coverage (full)
AMOUNT_COVERED: float = 1_000_000.0
PERCENTAGE_COVERED: float = 1.0
ORIGINAL_MATURITY_YEARS: float = 5.0  # >= 1y → satisfies Art. 237(2)(a) eligibility

# Effective maturity override (avoids date-arithmetic edge cases)
EFFECTIVE_MATURITY: float = 5.0

# Counterparty financials (borrower only — guarantor revenue not load-bearing)
ANNUAL_REVENUE: float = 100_000_000.0  # GBP 100m > GBP 44m SME threshold
TOTAL_ASSETS: float = 500_000_000.0

# Borrower internal PD — drives F-IRB routing when model_id is present.
# With M=5y this puts the borrower's own F-IRB RW well above 100% under both
# frameworks, so even the 100% non-GB RGLA substitution stays beneficial.
PD_BORROWER: float = 0.02

# Guarantor CQS values (PSE guarantors only; RGLA guarantors are unrated)
PSE_GUARANTOR_CQS2: int = 2
PSE_GUARANTOR_CQS3: int = 3

# ---------------------------------------------------------------------------
# Expected POST-FIX values (hand-calculated — assertions live in the test)
# ---------------------------------------------------------------------------

# CRR Art. 116(2) Table 2A (PS1/26 identical): PSE own-rating CQS 2 = CQS 3 = 50%
EXPECTED_GUARANTOR_RW_PSE_RATED: float = 0.50
EXPECTED_RWA_PSE_RATED: float = EAD * EXPECTED_GUARANTOR_RW_PSE_RATED  # 500,000

# SA-side documented unrated approximation (sa/namespace.py _build_guarantor_rw_expr):
# guarantor_country_code == "GB" → 20% (rgla_domestic), else → 100% (pse_unrated)
EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB: float = 0.20
EXPECTED_RWA_RGLA_UNRATED_GB: float = EAD * EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB  # 200,000
EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB: float = 1.00
EXPECTED_RWA_RGLA_UNRATED_NON_GB: float = EAD * EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB

# Expected derived guarantor exposure classes (ENTITY_TYPE_TO_SA_CLASS)
EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE: str = "pse"
EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA: str = "rgla"

# Post-fix audit values
EXPECTED_GUARANTEE_STATUS: str = "SA_RW_SUBSTITUTION"

# Pre-fix signature (current engine): guarantor_rw null → guarantee silently dropped
PRE_FIX_GUARANTEE_STATUS: str = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario (mirrors tests/fixtures/p1_122a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """PSE/RGLA-guarantor scenario counterparty row (borrower or guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Facility:
    """Parent facility for one loan (hierarchy requires a facility per loan)."""

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    effective_maturity: float

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Loan:
    """Senior corporate term loan (one per guarantor scenario)."""

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    effective_maturity: float
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


@dataclass(frozen=True)
class _Guarantee:
    """100% unfunded guarantee from one PSE / RGLA guarantor."""

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date | None
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str
    protection_type: str
    includes_restructuring: bool
    original_maturity_years: float
    guarantor_seniority: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": self.guarantee_type,
            "guarantor": self.guarantor,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "protection_type": self.protection_type,
            "includes_restructuring": self.includes_restructuring,
            "original_maturity_years": self.original_maturity_years,
            "guarantor_seniority": self.guarantor_seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """Rating row (internal for borrower; external CQS-only for PSE guarantors)."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int | None
    pd: float | None
    rating_date: date
    is_solicited: bool
    model_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """Model-permission row (borrower F-IRB only)."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_pse_rgla_counterparties() -> pl.DataFrame:
    """
    Return all five counterparties (borrower + four guarantors) as a DataFrame.

    CP_BORROWER_PSERGLA: entity_type="company" → CORPORATE; rated internally
        (pd=0.02, model_id=MODEL_BORROWER_FIRB) → routed F-IRB.

    CP_GTR_PSE_CQS2 / CP_GTR_PSE_CQS3: entity_type="pse_institution" →
        guarantor_exposure_class="pse" via ENTITY_TYPE_TO_SA_CLASS. External
        rating only (pd=None) → guarantor_approach="sa" → RWSM.

    CP_GTR_RGLA_GB / CP_GTR_RGLA_DE: entity_type="rgla_institution" →
        guarantor_exposure_class="rgla". NO rating rows → guarantor_cqs null →
        unrated fallback (GB → 20% / else → 100%, the SA-side approximation).
    """

    def _guarantor(ref: str, name: str, entity_type: str, country: str) -> _Counterparty:
        return _Counterparty(
            counterparty_reference=ref,
            counterparty_name=name,
            entity_type=entity_type,
            country_code=country,
            annual_revenue=None,  # not load-bearing for public-sector guarantors
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        )

    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="PSE/RGLA scenario Borrower Corporate GB F-IRB",
            entity_type="company",
            country_code="GB",
            annual_revenue=ANNUAL_REVENUE,
            total_assets=TOTAL_ASSETS,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        _guarantor(
            GUARANTOR_PSE_CQS2_REF,
            "PSE Guarantor GB rated CQS2",
            "pse_institution",
            "GB",
        ),
        _guarantor(
            GUARANTOR_PSE_CQS3_REF,
            "PSE Guarantor GB rated CQS3",
            "pse_institution",
            "GB",
        ),
        _guarantor(
            GUARANTOR_RGLA_GB_REF,
            "RGLA Guarantor GB unrated",
            "rgla_institution",
            "GB",
        ),
        _guarantor(
            GUARANTOR_RGLA_DE_REF,
            "RGLA Guarantor DE unrated",
            "rgla_institution",
            "DE",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_pse_rgla_facilities() -> pl.DataFrame:
    """
    Return the four parent facilities (one per loan) as a DataFrame.

    Mirrors p1_122a: committed senior term-loan facilities for the borrower,
    effective_maturity=5.0 matching the loans to prevent date-arithmetic
    divergence in the IRB maturity adjustment.
    """
    rows = [
        _Facility(
            facility_reference=fac_ref,
            product_type="term_loan",
            book_code="CORP_LENDING",
            counterparty_reference=BORROWER_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
        )
        for fac_ref in (
            FACILITY_PSE_CQS2_REF,
            FACILITY_PSE_CQS3_REF,
            FACILITY_RGLA_GB_REF,
            FACILITY_RGLA_DE_REF,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_pse_rgla_loans() -> pl.DataFrame:
    """
    Return the four loans as a DataFrame (one per guarantor scenario).

    Each loan: GBP 1,000,000 drawn senior term loan on CP_BORROWER_PSERGLA,
    effective_maturity=5.0. EAD = drawn + interest = 1,000,000.
    """
    rows = [
        _Loan(
            loan_reference=loan_ref,
            product_type="term_loan",
            book_code="CORP_LENDING",
            counterparty_reference=BORROWER_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        )
        for loan_ref in (
            LOAN_PSE_CQS2_REF,
            LOAN_PSE_CQS3_REF,
            LOAN_RGLA_GB_REF,
            LOAN_RGLA_DE_REF,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_pse_rgla_guarantees() -> pl.DataFrame:
    """
    Return the four guarantees as a DataFrame (one per loan, 100% coverage).

    Each guarantee: original_maturity_years=5.0 (Art. 237(2)(a) eligible),
    currency="GBP" matching the loan (H_fx = 0), guarantee maturity matching
    the loan maturity (no maturity-mismatch haircut).
    """
    pairs = [
        (GUARANTEE_PSE_CQS2_REF, GUARANTOR_PSE_CQS2_REF, LOAN_PSE_CQS2_REF),
        (GUARANTEE_PSE_CQS3_REF, GUARANTOR_PSE_CQS3_REF, LOAN_PSE_CQS3_REF),
        (GUARANTEE_RGLA_GB_REF, GUARANTOR_RGLA_GB_REF, LOAN_RGLA_GB_REF),
        (GUARANTEE_RGLA_DE_REF, GUARANTOR_RGLA_DE_REF, LOAN_RGLA_DE_REF),
    ]
    rows = [
        _Guarantee(
            guarantee_reference=gte_ref,
            guarantee_type="guarantee",
            guarantor=guarantor_ref,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=AMOUNT_COVERED,
            percentage_covered=PERCENTAGE_COVERED,
            beneficiary_type="loan",
            beneficiary_reference=loan_ref,
            protection_type="guarantee",
            includes_restructuring=True,
            original_maturity_years=ORIGINAL_MATURITY_YEARS,
            guarantor_seniority="senior",
        )
        for gte_ref, guarantor_ref, loan_ref in pairs
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_pse_rgla_ratings() -> pl.DataFrame:
    """
    Return the three rating rows as a DataFrame.

    RTG_PSERGLA_BORR (borrower, internal): pd=0.02, model_id=MODEL_BORROWER_FIRB
        → F-IRB routing. cqs=None (internal ratings carry no ECAI CQS).

    RTG_PSERGLA_PSE2 / RTG_PSERGLA_PSE3 (PSE guarantors, external): cqs=2 / cqs=3,
        pd=None (CRITICAL — the null PD forces guarantor_approach="sa" so the
        engine must price the guarantee via _compute_guarantor_rw_sa).

    The RGLA guarantors have NO rating rows at all — guarantor_cqs resolves null,
    pinning the unrated fallback branch of the shared guarantor RW expression.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",  # representative mid-grade for pd=2%
            cqs=None,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RTG_PSE_CQS2_REF,
            counterparty_reference=GUARANTOR_PSE_CQS2_REF,
            rating_type="external",
            rating_agency="Moody's",
            rating_value="A2",  # Moody's single-A equivalent → CQS 2
            cqs=PSE_GUARANTOR_CQS2,
            pd=None,  # CRITICAL: null PD → SA fallback (RWSM) for the guarantor
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
        _Rating(
            rating_reference=RTG_PSE_CQS3_REF,
            counterparty_reference=GUARANTOR_PSE_CQS3_REF,
            rating_type="external",
            rating_agency="Moody's",
            rating_value="Baa2",  # Moody's BBB equivalent → CQS 3
            cqs=PSE_GUARANTOR_CQS3,
            pd=None,  # CRITICAL: null PD → SA fallback (RWSM) for the guarantor
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_pse_rgla_model_permission() -> pl.DataFrame:
    """
    Return the model-permission row as a DataFrame.

    MODEL_BORROWER_FIRB: foundation_irb for exposure_class="corporate". Only
    the borrower's rating row references it — guarantors cannot route IRB.
    """
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_pse_rgla_guarantor_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all PSE/RGLA-guarantor parquet files and return a name → path mapping.

    Args:
        output_dir: Target directory. Defaults to the ``data/`` subdirectory
            next to this file (``tests/fixtures/pse_rgla_guarantor/data/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_pse_rgla_counterparties()),
        ("facility", create_pse_rgla_facilities()),
        ("loan", create_pse_rgla_loans()),
        ("guarantee", create_pse_rgla_guarantees()),
        ("rating", create_pse_rgla_ratings()),
        ("model_permission", create_pse_rgla_model_permission()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


# ---------------------------------------------------------------------------
# RawDataBundle loader — used by tests
# ---------------------------------------------------------------------------


def load_pse_rgla_guarantor_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from the PSE/RGLA-guarantor parquets.

    All six parquets are loaded:
      - counterparty.parquet: borrower (company) + 2 PSE + 2 RGLA guarantors
      - facility.parquet:    four parent facilities (one per loan)
      - loan.parquet:        four GBP 1,000,000 senior term loans
      - guarantee.parquet:   four 100%-coverage guarantees (one per loan)
      - rating.parquet:      borrower internal (pd=0.02, MODEL_BORROWER_FIRB) +
                             PSE external CQS 2 / CQS 3 (pd=None); RGLA unrated
      - model_permission.parquet: MODEL_BORROWER_FIRB → corporate/foundation_irb

    facility_mappings and lending_mappings are empty frames (loans link directly
    via counterparty_reference; mirrors the p1_122a / p1_122b wiring).
    """
    data_dir = Path(__file__).parent / "data"
    return make_raw_bundle(
        facilities=pl.scan_parquet(data_dir / "facility.parquet"),
        loans=pl.scan_parquet(data_dir / "loan.parquet"),
        counterparties=pl.scan_parquet(data_dir / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(data_dir / "guarantee.parquet"),
        ratings=pl.scan_parquet(data_dir / "rating.parquet"),
        model_permissions=pl.scan_parquet(data_dir / "model_permission.parquet"),
    )


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("PSE/RGLA-guarantor fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: IRB borrower + PSE / RGLA SA guarantors (Phase 4 Slice 5)")
    print(f"  Borrower:  {BORROWER_REF} (company, F-IRB pd={PD_BORROWER}, model={MODEL_ID})")
    print(f"  Guarantors: {GUARANTOR_PSE_CQS2_REF} (pse_institution, CQS 2)")
    print(f"              {GUARANTOR_PSE_CQS3_REF} (pse_institution, CQS 3)")
    print(f"              {GUARANTOR_RGLA_GB_REF} (rgla_institution, GB, unrated)")
    print(f"              {GUARANTOR_RGLA_DE_REF} (rgla_institution, DE, unrated)")
    print(f"  Loans:     4 x GBP {DRAWN_AMOUNT:,.0f}, senior, M={EFFECTIVE_MATURITY}y")
    print(f"  Guarantees: 100% coverage, original_maturity={ORIGINAL_MATURITY_YEARS}y")
    print()
    print("  POST-FIX expected (CRR == PS1/26 for PSE/RGLA tables):")
    print(
        f"    PSE rated CQS2/CQS3 (Art. 116(2) Table 2A) = "
        f"{EXPECTED_GUARANTOR_RW_PSE_RATED:.0%} -> RWA {EXPECTED_RWA_PSE_RATED:,.0f}"
    )
    print(
        f"    RGLA unrated GB (documented approximation) = "
        f"{EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB:.0%} -> RWA {EXPECTED_RWA_RGLA_UNRATED_GB:,.0f}"
    )
    print(
        f"    RGLA unrated DE = {EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB:.0%} -> "
        f"RWA {EXPECTED_RWA_RGLA_UNRATED_NON_GB:,.0f} (still < borrower IRB RWA)"
    )
    print()
    print("  PRE-FIX (bug): guarantor_rw null on all four rows; rwa = rwa_irb_original;")
    print(f"  guarantee_status = {PRE_FIX_GUARANTEE_STATUS}")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_pse_rgla_guarantor_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
