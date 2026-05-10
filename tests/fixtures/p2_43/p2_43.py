"""
Generate P2.43 fixtures: PSM LGD source switch — Art. 236(1)(a)(i) option (i).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/psm.py)

Scenario design (P2.43 — Basel 3.1 F-IRB corporate PSM LGD source switch):

    A single subordinated F-IRB corporate exposure is fully covered by an unfunded
    guarantee from a better-quality corporate guarantor under Basel 3.1 PSM
    (Art. 236(1)(a)(i)).

    The scenario exercises Art. 236(1)(a)(i) option (i) versus option (ii), which
    are the two choices for LGD under PSM when the guarantor's approach is IRB:

    Art. 236(1)(a)(i) option (i): use the supervisory LGD that corresponds to the
        guarantor's own seniority and exposure class — i.e., the guarantor's F-IRB
        supervisory LGD as if the guaranteed obligation were a direct exposure on the
        guarantor. For a corporate guarantor with senior seniority, Art. 161(1)(a)
        applies: supervisory LGD = 40% (Basel 3.1) or 45% (CRR).

    Art. 236(1)(a)(i) option (ii): use the borrower's own LGD (which for this
        subordinated exposure under Art. 161(1)(b) = 75%).

    The two options produce materially different RWA on the covered portion:
        Option (i): LGD = 40% (B31 senior corporate F-IRB supervisory LGD)
        Option (ii): LGD = 75% (borrower's F-IRB subordinated supervisory LGD)

    The discriminating input: guarantor_seniority on the guarantee row is "senior",
    so option (i) routes to Art. 161(1)(a) supervisory LGD 40% (B31) / 45% (CRR).
    The borrower's own loan has seniority="subordinated" — Art. 161(1)(b) = 75%.
    The LGD gap (40% vs 75%) makes the two options unambiguous.

    The fixture is IDENTICAL for both test arms. The engine-implementer will add
    a new field ``IRBPermissions.psm_lgd_source`` to config (values: "option_i",
    "option_ii") that selects between the two paths. No schema change in fixtures.

Counterparties:
    BORROWER_42 : corporate, GB, internal_pd=0.05, annual_revenue=600m (above
        GBP 44m → not SME; above GBP 440m → large-corp, F-IRB only under B31),
        is_financial_sector_entity=False, entity_type="corporate".
    GUARANTOR_99: corporate, GB, internal_pd=0.005, is_financial_sector_entity=False,
        entity_type="corporate".

Loan:
    EXP_P2_43: subordinated corporate term loan, GBP 1,000,000, drawn in full,
        interest=0, seniority="subordinated" → borrower F-IRB LGD = 75%
        (Art. 161(1)(b), both CRR and B31), M≈2.5y (2026-01-01 to 2028-07-01).

Guarantee:
    GTE_P2_43: full unfunded corporate guarantee from GUARANTOR_99 covering 100%
        of EXP_P2_43. guarantor_seniority="senior" → option (i) supervisory LGD
        = 40% (B31) / 45% (CRR) per Art. 161(1)(a).
        GBP currency matches loan → no FX haircut (H_fx = 0).
        original_maturity_years=3.0 → satisfies Art. 237(2)(a) eligibility (≥ 1y).

Model permissions:
    corp_firb_v1: foundation_irb for exposure_class="corporate".
        Both borrower and guarantor reference this model_id.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Loan:
        EAD = 1,000,000 GBP
        M ≈ 2.5y (2026-01-01 → 2028-07-01 ≈ 2.5y; or use effective_maturity=2.5)
        PD_borrower = 0.05 (5%, > Basel 3.1 corporate floor 0.0005 → no floor effect)
        LGD_borrower = 0.75 (Art. 161(1)(b) subordinated F-IRB supervisory LGD)
        Borrower's OWN uncovered RWA (informational, applies only to uncovered portion):
            K_corp(PD=0.05, LGD=0.75, M=2.5) computed per Art. 153-154.

    Guarantee PSM option (i) — covered portion (EAD_covered = 1,000,000):
        PD_guarantor = 0.005 (0.5%, > B31 floor 0.0005)
        LGD_option_i = 0.40  (Art. 161(1)(a): B31 senior corporate F-IRB supervisory LGD)
        Guarantor exposure class: corporate, seniority: senior
        K_psm_i = K_corp(PD=0.005, LGD=0.40, M=2.5) per Art. 153-154
        RWA_option_i = K_psm_i × 12.5 × 1,000,000

    Guarantee PSM option (ii) — covered portion (EAD_covered = 1,000,000):
        LGD_option_ii = 0.75  (Art. 161(1)(b): borrower's own subordinated LGD)
        K_psm_ii = K_corp(PD=0.005, LGD=0.75, M=2.5) per Art. 153-154
        RWA_option_ii = K_psm_ii × 12.5 × 1,000,000

    Note: RWA_option_i < RWA_option_ii because LGD_option_i (40%) < LGD_option_ii (75%).
    The test checks that the engine routes to the correct LGD when
    IRBPermissions.psm_lgd_source is set to "option_i" vs "option_ii".

References:
    - PRA PS1/26 Art. 236(1)(a)(i): PSM LGD source options (i) and (ii).
    - PRA PS1/26 Art. 161(1)(a): Basel 3.1 F-IRB supervisory LGD 40% (corporate senior,
      non-FSE). CRR counterpart is 45%.
    - PRA PS1/26 Art. 161(1)(b): F-IRB supervisory LGD 75% (corporate subordinated).
      Both CRR and B31 agree at 75%.
    - PRA PS1/26 Art. 237(2)(a): minimum original maturity of unfunded protection ≥ 1 year.
    - PRA PS1/26 Art. 163(1): B31 corporate PD floor 0.05%; CRR floor 0.03%.
    - PRA PS1/26 Art. 147A: large corporates (>GBP 440m) restricted to F-IRB only.

Usage:
    uv run python tests/fixtures/p2_43/p2_43.py
    uv run python tests/fixtures/p2_43/p2_43.py --data-dir /path/to/output
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

# Counterparty references (match architect proposal)
BORROWER_REF: str = "BORROWER_42"
GUARANTOR_REF: str = "GUARANTOR_99"

# Exposure references
LOAN_REF: str = "EXP_P2_43"
FACILITY_REF: str = "FAC_P2_43"

# Guarantee reference
GUARANTEE_REF: str = "GTE_P2_43"

# Rating references
RTG_BORROWER_REF: str = "RTG_P2_43_BORR"
RTG_GUARANTOR_REF: str = "RTG_P2_43_GTR"

# Model permission ID
MODEL_ID: str = "corp_firb_v1"

# Dates
VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE: date = date(2028, 7, 1)  # ~2.5y from VALUE_DATE → M ≈ 2.5y
GUARANTEE_MATURITY_DATE: date = date(2029, 1, 1)  # original_maturity ≈ 3.0y ≥ 1y → eligible
RATING_DATE: date = date(2026, 1, 2)

# Loan economics
DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
EAD: float = DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Guarantee coverage (full)
AMOUNT_COVERED: float = 1_000_000.0
PERCENTAGE_COVERED: float = 1.0
ORIGINAL_MATURITY_YEARS: float = 3.0  # ≥ 1y → Art. 237(2)(a) eligible

# IRB inputs
PD_BORROWER: float = 0.05   # 5.0% — high-PD CCC-rated; above B31 corporate floor 0.0005
PD_GUARANTOR: float = 0.005  # 0.5% — better quality; above B31 corporate floor 0.0005
EFFECTIVE_MATURITY: float = 2.5  # M = 2.5y (explicit override avoids date arithmetic edge cases)

# Borrower annual revenue — above GBP 440m → large corporate → F-IRB only (Art. 147A)
ANNUAL_REVENUE_BORROWER: float = 600_000_000.0

# Expected F-IRB supervisory LGD values (for test assertions)
# Borrower's own LGD (subordinated, Art. 161(1)(b)) — same under CRR and Basel 3.1
EXPECTED_LGD_BORROWER: float = 0.75

# Guarantor's LGD under PSM option (i): Art. 161(1)(a) senior corporate supervisory LGD
#   Basel 3.1: 40%  (reduced from CRR 45% per PS1/26 irb-changes)
#   CRR:       45%
EXPECTED_LGD_OPTION_I_B31: float = 0.40
EXPECTED_LGD_OPTION_I_CRR: float = 0.45

# Guarantor's LGD under PSM option (ii): borrower's own subordinated LGD
EXPECTED_LGD_OPTION_II: float = 0.75  # same under CRR and Basel 3.1


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.43 counterparty row (borrower or guarantor)."""

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
    """
    P2.43 parent facility for the borrower.

    The codebase requires a parent facility for every loan (hierarchy resolver).
    seniority="subordinated" matches the loan so no seniority mismatch arises
    at the facility-loan link.
    effective_maturity=2.5 is set explicitly to avoid date-arithmetic edge cases.
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
    P2.43 subordinated corporate term loan.

    seniority="subordinated" drives the borrower's F-IRB supervisory LGD to 75%
    under Art. 161(1)(b) (both CRR and Basel 3.1). This creates a clear LGD gap
    against the guarantor's senior LGD (option (i): 40% B31 / 45% CRR) that
    makes the two PSM options unambiguously distinguishable.

    effective_maturity=2.5: M = 2.5y is load-bearing for maturity adjustment in
    the IRB K-formula and must be consistent across facility, loan, and guarantee.
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
    """
    P2.43 guarantee row: full unfunded corporate guarantee from GUARANTOR_99.

    guarantor_seniority="senior": routes PSM option (i) to Art. 161(1)(a)
    supervisory LGD of 40% (Basel 3.1) / 45% (CRR).  The discriminating field
    vs. option (ii) which uses the borrower's own subordinated LGD of 75%.

    original_maturity_years=3.0: satisfies Art. 237(2)(a) eligibility (≥ 1y).
    currency="GBP": matches loan → no FX mismatch haircut (H_fx = 0).
    amount_covered=1,000,000 = full EAD → 100% coverage.
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
    """P2.43 internal rating row."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

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
    """P2.43 model-permission row."""

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


def create_p243_counterparties() -> pl.DataFrame:
    """
    Return both P2.43 counterparties (borrower + guarantor) as a DataFrame.

    BORROWER_42: large corporate (annual_revenue=600m > 440m threshold → F-IRB only
        under Basel 3.1 Art. 147A). is_financial_sector_entity=False: no FI scalar.
        PD=0.05 (5%), high-PD CCC-rated corporate — internal rating row carries this.
        turnover_m=60 (GBP 600m) is above GBP 44m → classified as non-SME corporate.

    GUARANTOR_99: corporate, GB, annual_revenue unspecified (null → engine treats as
        large corporate conservatively). is_financial_sector_entity=False: no FI scalar.
        PD=0.005 (0.5%), better-quality corporate than borrower.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P2.43 Corporate Borrower GB High-PD",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=ANNUAL_REVENUE_BORROWER,  # 600m > 440m → large-corp, F-IRB only
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,  # non-FSE: Art. 153(2) FI scalar does NOT apply
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P2.43 Corporate Guarantor GB Low-PD",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,  # null → treated conservatively as large-corp
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p243_facility() -> pl.DataFrame:
    """
    Return the P2.43 parent facility as a DataFrame.

    FAC_P2_43: one senior facility row for BORROWER_42 that the loan EXP_P2_43 links
    into via the hierarchy resolver.  seniority="subordinated" matches the loan so
    the hierarchy resolver sees a consistent seniority at the facility level.
    effective_maturity=2.5 is the IRB M override — prevents date-rounding divergence.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
        product_type="TERM_LOAN",
        book_code="CORP_LENDING",
        counterparty_reference=BORROWER_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        limit=DRAWN_AMOUNT,
        committed=True,
        seniority="subordinated",
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p243_loan() -> pl.DataFrame:
    """
    Return the P2.43 loan as a DataFrame.

    EXP_P2_43: GBP 1,000,000 subordinated term loan.
    seniority="subordinated": drives F-IRB supervisory LGD to Art. 161(1)(b) = 75%
    under both CRR and Basel 3.1.  This is the load-bearing field for PSM option (ii).
    effective_maturity=2.5 consistent with the parent facility.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="TERM_LOAN",
        book_code="CORP_LENDING",
        counterparty_reference=BORROWER_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=DRAWN_AMOUNT,
        interest=LOAN_INTEREST,
        seniority="subordinated",
        effective_maturity=EFFECTIVE_MATURITY,
        is_payroll_loan=False,
        is_buy_to_let=False,
        is_under_construction=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p243_guarantee() -> pl.DataFrame:
    """
    Return the P2.43 guarantee as a DataFrame.

    GTE_P2_43: 100% unfunded corporate guarantee from GUARANTOR_99.

    guarantor_seniority="senior": the key discriminating field.
        PSM option (i): engine reads guarantor_seniority → Art. 161(1)(a) LGD = 40% (B31).
        PSM option (ii): engine uses borrower's own seniority → Art. 161(1)(b) LGD = 75%.
    original_maturity_years=3.0: > 1.0y → satisfies Art. 237(2)(a) eligibility.
    currency="GBP": matches loan → no FX mismatch haircut (H_fx = 0).
    beneficiary_type="loan": links directly to EXP_P2_43.
    """
    row = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="corporate_guarantee",
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


def create_p243_ratings() -> pl.DataFrame:
    """
    Return both P2.43 internal ratings as a DataFrame.

    RTG_P2_43_BORR: borrower PD=0.05 (5%), CQS=5, model_id=corp_firb_v1.
        PD=0.05 is well above B31 corporate floor 0.0005 → no floor effect.
        CQS=5 corresponds to high-PD CCC-rated band.

    RTG_P2_43_GTR: guarantor PD=0.005 (0.5%), CQS=3, model_id=corp_firb_v1.
        PD=0.005 is above B31 corporate floor 0.0005 → no floor effect.
        Both borrower and guarantor share the same model_id (corp_firb_v1)
        to confirm the engine disambiguates via counterparty_reference, not model_id.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="CCC",  # high-PD CCC-rated → PD=5%
            cqs=5,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BB",  # mid-grade BB → PD=0.5%
            cqs=3,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p243_model_permission() -> pl.DataFrame:
    """
    Return the P2.43 model permission as a DataFrame.

    corp_firb_v1: grants foundation_irb for exposure_class="corporate".
    A single model_id covers both the borrower and the guarantor — the engine
    uses the counterparty's exposure class + model_id to resolve IRB parameters.

    Under Basel 3.1, large corporates (annual_revenue > GBP 440m) are restricted
    to F-IRB only (Art. 147A), so foundation_irb is the only valid approach here.
    Only one row is needed (foundation_irb only — no advanced_irb row for this
    scenario, since the borrower is above the 440m large-corp threshold).
    """
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,  # all geographies
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p243_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.43 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_43/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p243_counterparties()),
        ("facility", create_p243_facility()),
        ("loan", create_p243_loan()),
        ("guarantee", create_p243_guarantee()),
        ("rating", create_p243_ratings()),
        ("model_permission", create_p243_model_permission()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.43 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PSM LGD source switch — Art. 236(1)(a)(i) option (i) vs option (ii)")
    print(f"  Borrower:  {BORROWER_REF} (corporate, GB, annual_revenue={ANNUAL_REVENUE_BORROWER:,.0f})")
    print(f"             PD={PD_BORROWER}, seniority=subordinated")
    print(f"             Borrower F-IRB supervisory LGD = {EXPECTED_LGD_BORROWER} (Art. 161(1)(b))")
    print(f"  Guarantor: {GUARANTOR_REF} (corporate, GB)")
    print(f"             PD={PD_GUARANTOR}, guarantor_seniority=senior")
    print(f"  Loan:      {LOAN_REF}  GBP {DRAWN_AMOUNT:,.0f} subordinated")
    print(f"             value_date={VALUE_DATE}, maturity_date={MATURITY_DATE}, M={EFFECTIVE_MATURITY}y")
    print(f"  Guarantee: {GUARANTEE_REF}  100% coverage, original_maturity={ORIGINAL_MATURITY_YEARS}y")
    print()
    print("  PSM option (i)  — guarantor supervisory LGD (senior seniority):")
    print(f"    Basel 3.1: LGD = {EXPECTED_LGD_OPTION_I_B31} (Art. 161(1)(a) B31 corporate senior)")
    print(f"    CRR:       LGD = {EXPECTED_LGD_OPTION_I_CRR} (Art. 161(1)(a) CRR corporate senior)")
    print("  PSM option (ii) — borrower's own LGD:")
    print(f"    Both:      LGD = {EXPECTED_LGD_OPTION_II} (Art. 161(1)(b) subordinated)")
    print()
    print("  Engine switch: IRBPermissions.psm_lgd_source = 'option_i' | 'option_ii'")
    print("  Fixture is IDENTICAL for both test arms; only config changes between arms.")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p243_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
