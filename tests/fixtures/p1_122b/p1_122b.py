"""
Generate P1.122(b) fixtures: IRB borrower + unrated SCRA-B institution guarantor.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/irb/guarantee.py)

Scenario design (P1.122(b) — IRB borrower + unrated SCRA-B institution guarantor):

    A single F-IRB corporate borrower (PD=0.02) is fully covered by an unfunded guarantee
    from an institution guarantor that carries no ECAI rating (rating_value="NR",
    cqs=None) but is classified as SCRA Grade B in its counterparty row.

    Under Basel 3.1 Art. 121 (SCRA), an unrated institution with SCRA Grade B and
    residual maturity >3 months receives a risk weight of 75%.

    Pre-fix behaviour (defect under test):
        The engine incorrectly dispatches SCRA-B to the SCRA-A branch (or equivalent
        mis-routing), producing a risk weight of 40% instead of 75%.
        RWA pre-fix = 1,000,000 × 0.40 = 400,000.

    Post-fix expected (B31):
        Guarantor SA RW: SCRA Grade B, >3m maturity → Art. 121 Table 5 = 75%.
        Substitution: guarantor RW 75% < borrower unguaranteed RW → use 75%.
        RWA post-fix = 1,000,000 × 0.75 = 750,000.

    Regulatory references:
        - PRA PS1/26 Art. 121 Table 5: SCRA Grade B (>3m) = 75%.
        - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM).
        - CRR Art. 237(2)(a): original maturity of unfunded credit protection >= 1 year.

    Discriminating element:
        counterparty.scra_grade = "B" on CP_GUARANTOR_P1122B.
        This is the field the engine reads when routing the SCRA guarantee path.
        Without the fix, "B" is routed to the wrong risk-weight bucket (40%).
        Post-fix, "B" correctly maps to 75% (>3m maturity branch).

    Distinction from related scenarios:
        P1.95: pure SA borrower + SCRA guarantor (no IRB on the borrower side).
        P1.122(a): IRB borrower + null-PD *corporate* guarantor → SA fallback via CQS.
        P1.122(b): IRB borrower + unrated *institution* guarantor → SA fallback via SCRA.

Counterparties (2 rows):
    CP_BORROWER_P1122B: entity_type="company" → SA: CORPORATE / IRB: CORPORATE.
        annual_revenue=100,000,000 (> GBP 44m SME threshold, not SME),
        total_assets=500,000,000; default_status=False, is_financial_sector_entity=False.
        scra_grade=None (borrower is not an institution; field not applicable).
    CP_GUARANTOR_P1122B: entity_type="bank" → SA: INSTITUTION / IRB: INSTITUTION.
        scra_grade="B" — CRITICAL discriminating field.
        No external rating (cqs=None on its rating row) → SCRA path applies.
        default_status=False, apply_fi_scalar=False.

Ratings (2 rows):
    Borrower  (CP_BORROWER_P1122B): rating_type="internal", pd=0.02, model_id=MODEL_BORROWER_FIRB.
        Drives F-IRB routing for the borrower exposure.
    Guarantor (CP_GUARANTOR_P1122B): rating_type="external", rating_value="NR", cqs=None, pd=None.
        No ECAI rating → ECRA does not apply. Engine uses SCRA path.
        model_id=None → guarantor cannot route IRB.

Facility (1 row):
    FAC_P1122B: committed senior term loan facility for CP_BORROWER_P1122B.

Loan (1 row):
    LOAN_P1122B: GBP 1,000,000 senior term loan on CP_BORROWER_P1122B.
        seniority="senior"; effective_maturity=5.0y.

Guarantee (1 row):
    GTE_P1122B: 100% coverage of LOAN_P1122B by CP_GUARANTOR_P1122B.
        original_maturity_years=5.0 >= 1.0y → satisfies Art. 237(2)(a) eligibility.
        guarantor_seniority="senior".
        currency="GBP" matches loan → no FX mismatch haircut (H_fx = 0).

Model permissions (1 row):
    MODEL_BORROWER_FIRB: foundation_irb for exposure_class="corporate".
        Borrower's rating row references this model_id, enabling F-IRB routing.
        Guarantor has no model_id → cannot route IRB.

Hand-calculation:
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP.

    B31 path (CalculationConfig.basel_3_1()):
        Borrower: F-IRB corporate (pd=0.02, corporate F-IRB supervisory LGD=40% senior).
        Guarantor approach = SA-fallback (no ECAI rating, cqs=None, pd=None).
        Guarantor SCRA grade = "B", residual maturity 5y > 3m.
        Guarantor SA RW: SCRA Grade B (>3m) → Art. 121 Table 5 = 75%.
        Substitution: guarantor RW 75% applied (< borrower unguaranteed RW).
        RWA (post-fix) = 1,000,000 × 0.75 = 750,000.
        RWA (pre-fix)  = 1,000,000 × 0.40 = 400,000 (bug: SCRA-B routed to SCRA-A).

References:
    - PRA PS1/26 Art. 121 Table 5: SCRA Grade B (>3m) = 75%.
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees.
    - CRR Art. 237(2)(a): original maturity of unfunded credit protection >= 1 year.
    - src/rwa_calc/data/schemas.py: VALID_SCRA_GRADES = {"A", "A_ENHANCED", "B", "C"}.

Usage:
    uv run python tests/fixtures/p1_122b/p1_122b.py
    uv run python tests/fixtures/p1_122b/p1_122b.py --data-dir tests/fixtures/p1_122b/data
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
BORROWER_REF: str = "CP_BORROWER_P1122B"
GUARANTOR_REF: str = "CP_GUARANTOR_P1122B"

# Exposure references
LOAN_REF: str = "LOAN_P1122B"
FACILITY_REF: str = "FAC_P1122B"

# Guarantee reference
GUARANTEE_REF: str = "GTE_P1122B"

# Rating references
RTG_BORROWER_REF: str = "RTG_P1122B_BORR"
RTG_GUARANTOR_REF: str = "RTG_P1122B_GTR"

# Model permission ID
MODEL_ID: str = "MODEL_BORROWER_FIRB"

# Dates — Basel 3.1 effective from 1 Jan 2027
VALUE_DATE: date = date(2027, 1, 2)
MATURITY_DATE: date = date(2032, 1, 2)  # 5y residual
GUARANTEE_MATURITY_DATE: date = date(2032, 1, 2)  # matches loan — no maturity mismatch
RATING_DATE: date = date(2027, 1, 2)

# Loan economics
DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
EAD: float = DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Guarantee coverage (full)
AMOUNT_COVERED: float = 1_000_000.0
PERCENTAGE_COVERED: float = 1.0
ORIGINAL_MATURITY_YEARS: float = 5.0  # >= 1y → satisfies Art. 237(2)(a) eligibility

# Effective maturity override (avoids date-arithmetic edge cases)
EFFECTIVE_MATURITY: float = 5.0

# Counterparty financials
# annual_revenue > GBP 44m SME threshold → classified as non-SME large corporate
ANNUAL_REVENUE: float = 100_000_000.0  # GBP 100m
TOTAL_ASSETS: float = 500_000_000.0  # GBP 500m (borrower only)

# Borrower internal PD — drives F-IRB routing when model_id is present
PD_BORROWER: float = 0.02  # 2.0% — well above Basel 3.1 corporate floor 0.0005

# Guarantor SCRA grade — the discriminating value for the SA risk weight:
#   B31 Art. 121 Table 5: SCRA Grade B (>3m) → 75%   (post-fix expected)
#   Pre-fix bug: SCRA-B mis-routed to SCRA-A (40%)
GUARANTOR_SCRA_GRADE: str = "B"

# Expected SA risk weights (assertions live in the test)
EXPECTED_GUARANTOR_RW_B31: float = 0.75  # B31 Art. 121 Table 5, SCRA-B >3m — POST-FIX
EXPECTED_GUARANTOR_RW_B31_PRE_FIX: float = 0.40  # Pre-fix bug: SCRA-B routed to SCRA-A

EXPECTED_RWA_B31: float = EAD * EXPECTED_GUARANTOR_RW_B31  # 750,000
EXPECTED_RWA_B31_PRE_FIX: float = EAD * EXPECTED_GUARANTOR_RW_B31_PRE_FIX  # 400,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.122(b) counterparty row (borrower or guarantor)."""

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
    is_natural_person: bool
    scra_grade: str | None

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
            "is_natural_person": self.is_natural_person,
            "scra_grade": self.scra_grade,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.122(b) parent facility for the borrower.

    The hierarchy resolver requires a parent facility for each loan.
    seniority="senior" matches the loan.
    effective_maturity=5.0 is set explicitly to prevent date-rounding divergence
    in the IRB maturity adjustment.
    """

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
    """
    P1.122(b) senior corporate term loan.

    seniority="senior": drives F-IRB supervisory LGD to Art. 161(1)(a) = 40% (B31).
    effective_maturity=5.0: consistent with the parent facility.
    is_payroll_loan / is_buy_to_let / is_under_construction / is_hedged all False.
    """

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
    is_hedged: bool

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
            "is_hedged": self.is_hedged,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    P1.122(b) guarantee row: 100% unfunded institution guarantee from CP_GUARANTOR_P1122B.

    The discriminating element is the guarantor's scra_grade="B" on the counterparty row
    combined with cqs=None in its rating row. The null CQS and null PD prevent ECRA/IRB
    routing — the engine must use the SCRA path in the SA guarantee fallback.

        B31 Art. 121 Table 5: SCRA Grade B (>3m) → 75%   (post-fix expected)
        Pre-fix bug: SCRA-B mis-routed → 40%

    original_maturity_years=5.0: > 1.0y → satisfies Art. 237(2)(a) eligibility.
    guarantor_seniority="senior" → satisfies schema completeness.
    currency="GBP": matches loan → H_fx = 0 (no FX mismatch haircut).
    """

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
    """P1.122(b) rating row (internal for borrower; external NR for guarantor)."""

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
    """P1.122(b) model-permission row."""

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


def create_p1122b_counterparties() -> pl.DataFrame:
    """
    Return both P1.122(b) counterparties (borrower + guarantor) as a DataFrame.

    CP_BORROWER_P1122B:
        entity_type="company" → maps to SA: CORPORATE / IRB: CORPORATE.
        annual_revenue=100,000,000 (GBP 100m) > GBP 44m → non-SME corporate.
        total_assets=500,000,000: informational only.
        Borrower has a rating row with pd=0.02 and model_id=MODEL_BORROWER_FIRB
        → engine routes to F-IRB.
        scra_grade=None: borrower is not an institution, field not applicable.

    CP_GUARANTOR_P1122B:
        entity_type="bank" → maps to SA: INSTITUTION.
        scra_grade="B": CRITICAL discriminating field.
        Guarantor has a rating row with cqs=None and pd=None → ECRA does not apply;
        engine uses SCRA path, reading scra_grade from the counterparty row.
        model_id=None → guarantor cannot route IRB.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1122B Borrower Corp",
            entity_type="company",
            country_code="GB",
            annual_revenue=ANNUAL_REVENUE,
            total_assets=TOTAL_ASSETS,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
            scra_grade=None,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1122B Guarantor Bank",
            entity_type="bank",
            country_code="DE",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
            scra_grade=GUARANTOR_SCRA_GRADE,  # "B" — load-bearing discriminating field
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1122b_facility() -> pl.DataFrame:
    """
    Return the P1.122(b) parent facility as a DataFrame.

    FAC_P1122B: committed senior term loan facility for CP_BORROWER_P1122B.
    effective_maturity=5.0 matches LOAN_P1122B to prevent date-arithmetic divergence
    in the IRB maturity-adjustment calculation.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
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
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1122b_loan() -> pl.DataFrame:
    """
    Return the P1.122(b) loan as a DataFrame.

    LOAN_P1122B: GBP 1,000,000 senior term loan on CP_BORROWER_P1122B.
    seniority="senior": drives F-IRB supervisory LGD to Art. 161(1)(a) 40% (B31).
    effective_maturity=5.0: explicit M override consistent with the parent facility.
    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
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
        is_hedged=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1122b_guarantee() -> pl.DataFrame:
    """
    Return the P1.122(b) guarantee as a DataFrame.

    GTE_P1122B: 100% unfunded institution guarantee from CP_GUARANTOR_P1122B.

    The guarantor's counterparty row carries scra_grade="B" and its rating row
    carries cqs=None and pd=None. This forces the SA guarantee fallback to the
    SCRA path and read the grade from the counterparty row.
        B31 Art. 121 Table 5: SCRA Grade B (>3m) → 75%   (post-fix expected)

    original_maturity_years=5.0: >= 1.0y → satisfies Art. 237(2)(a) eligibility.
    currency="GBP": matches loan → H_fx = 0 (no FX mismatch haircut).
    """
    row = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="guarantee",
        guarantor=GUARANTOR_REF,
        currency="GBP",
        maturity_date=GUARANTEE_MATURITY_DATE,
        amount_covered=AMOUNT_COVERED,
        percentage_covered=PERCENTAGE_COVERED,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        protection_type="guarantee",
        includes_restructuring=True,
        original_maturity_years=ORIGINAL_MATURITY_YEARS,
        guarantor_seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p1122b_ratings() -> pl.DataFrame:
    """
    Return both P1.122(b) ratings as a DataFrame.

    RTG_P1122B_BORR (borrower, internal):
        rating_type="internal", pd=0.02 (2%), model_id=MODEL_BORROWER_FIRB.
        The model_id links to the model_permission row → engine routes borrower to F-IRB.
        cqs=None: internal ratings do not carry a CQS.

    RTG_P1122B_GTR (guarantor, external NR):
        rating_type="external", rating_value="NR", cqs=None, pd=None.
        No ECAI rating → ECRA does not apply. Engine resolves to SCRA path and reads
        scra_grade from the counterparty row (CP_GUARANTOR_P1122B.scra_grade = "B").
        model_id=None: no model permission → IRB not available for guarantor.

    The combination borrower-IRB + guarantor-SCRA-B is the unique fixture of P1.122(b).
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",  # representative mid-grade for pd=2%
            cqs=None,  # internal rating: no ECAI CQS
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,  # links to MODEL_BORROWER_FIRB → F-IRB routing
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="external",
            rating_agency="Moody's",
            rating_value="NR",  # Not Rated — no ECAI CQS → SCRA path applies
            cqs=None,  # CRITICAL: no CQS → ECRA does not apply
            pd=None,  # no PD → IRB not available for guarantor
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=None,  # no model_id → guarantor cannot route IRB
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1122b_model_permission() -> pl.DataFrame:
    """
    Return the P1.122(b) model permission as a DataFrame.

    MODEL_BORROWER_FIRB: grants foundation_irb for exposure_class="corporate".
    Covers only the borrower (CP_BORROWER_P1122B), whose rating references this
    model_id. The guarantor's rating row has model_id=None — deliberately excluded
    to prevent IRB routing for the guarantor.
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


def save_p1122b_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.122(b) parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the ``data/`` subdirectory
            next to this file (``tests/fixtures/p1_122b/data/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p1122b_counterparties()),
        ("facility", create_p1122b_facility()),
        ("loan", create_p1122b_loan()),
        ("guarantee", create_p1122b_guarantee()),
        ("rating", create_p1122b_ratings()),
        ("model_permission", create_p1122b_model_permission()),
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


def load_p1_122b_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.122(b) parquets.

    All six parquets are loaded:
      - counterparty.parquet: borrower (entity_type="company") + guarantor (entity_type="bank")
      - facility.parquet:    FAC_P1122B (parent facility for the loan)
      - loan.parquet:        LOAN_P1122B (GBP 1,000,000 senior term loan)
      - guarantee.parquet:   GTE_P1122B (100% coverage by CP_GUARANTOR_P1122B)
      - rating.parquet:      borrower (internal, pd=0.02, model_id=MODEL_BORROWER_FIRB)
                             guarantor (external NR, cqs=None, pd=None → SCRA-B path)
      - model_permission.parquet: MODEL_BORROWER_FIRB → corporate/foundation_irb

    facility_mappings and lending_mappings are empty frames (no hierarchy rows needed
    for a single loan/facility pair linked directly via counterparty_reference).

    The critical counterparty field is CP_GUARANTOR_P1122B.scra_grade = "B", which
    drives the SCRA risk-weight lookup in the SA guarantee fallback branch.
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
    print("P1.122(b) fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: IRB borrower + unrated SCRA-B institution guarantor")
    print(
        f"  Borrower:  {BORROWER_REF} (entity_type='company', annual_revenue={ANNUAL_REVENUE:,.0f})"
    )
    print(f"             F-IRB: pd={PD_BORROWER}, model_id={MODEL_ID}")
    print(f"  Guarantor: {GUARANTOR_REF} (entity_type='bank', scra_grade='{GUARANTOR_SCRA_GRADE}')")
    print("             SA-fallback: cqs=None, pd=None, model_id=None")
    print(
        f"  Loan:      {LOAN_REF}  GBP {DRAWN_AMOUNT:,.0f}, "
        f"seniority=senior, M={EFFECTIVE_MATURITY}y"
    )
    print(
        f"  Guarantee: {GUARANTEE_REF}  100% coverage, "
        f"original_maturity={ORIGINAL_MATURITY_YEARS}y, senior"
    )
    print()
    print("  B31 (CalculationConfig.basel_3_1()) — post-fix:")
    print(
        f"    Guarantor SA RW (SCRA Grade B >3m, Art. 121 Table 5) "
        f"= {EXPECTED_GUARANTOR_RW_B31:.0%}"
    )
    print(f"    Expected RWA = {EXPECTED_RWA_B31:,.0f}")
    print(
        f"    Pre-fix bug RWA = {EXPECTED_RWA_B31_PRE_FIX:,.0f}  "
        f"(understates by {EXPECTED_RWA_B31 - EXPECTED_RWA_B31_PRE_FIX:,.0f})"
    )


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1122b_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
