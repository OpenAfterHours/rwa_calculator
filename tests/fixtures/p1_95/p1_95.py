"""
Generate P1.95 fixtures: B31 SCRA-grade dispatch for unrated institution guarantor.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Scenario design (P1.95 — parametrised SCRA guarantor substitution):

    A corporate borrower (CP_BORROWER_P195, GB, SME, unrated) has five GBP 1,000,000
    5-year loans, each fully guaranteed by a separate unrated GB institution carrying
    one of the SCRA grades: A, A_ENHANCED, B, C, or null (no SCRA grade).

    Under Basel 3.1 Art. 121 (SCRA) the guarantor substituted risk weight depends on
    the guarantor's SCRA grade and the guaranteed exposure's residual maturity:
        Residual maturity > 3 months (5y loans, all long-term):
            Grade A          → 40%
            Grade A_ENHANCED → 30%
            Grade B          → 75%
            Grade C          → 150%
            null (no grade)  → no SCRA path; falls back to borrower RW = 85%

    The borrower is an unrated SME corporate (annual_revenue = GBP 20m < GBP 44m
    SME threshold). Under Basel 3.1 Art. 122(2) the unrated SME corporate SA RW is 85%.

    The five fixture rows are the load-bearing inputs for the parametrised unit test
    family that validates SCRA-grade dispatch in the CRM guarantee processor.

Hand-calculation (B31, CalculationConfig.basel_3_1(reporting_date=date(2026, 6, 30))):

    Borrower baseline (unrated SME corporate, Art. 122(2)):
        RW_borrower = 85%
        EAD         = 1,000,000 GBP
        RWA_borrower = 1,000,000 × 0.85 = 850,000

    SCRA substitution (Art. 121, long-term >3m, for each guarantee row):
        Grade A:          RW_guarantor = 40% < 85%  → substitution applies, RWA = 400,000
        Grade A_ENHANCED: RW_guarantor = 30% < 85%  → substitution applies, RWA = 300,000
        Grade B:          RW_guarantor = 75% < 85%  → substitution applies, RWA = 750,000
        Grade C:          RW_guarantor = 150% > 85% → no substitution (borrower RW used)
        null:             No SCRA grade → no SCRA path; RWA = 850,000 (borrower RW)

    Note on Grade C: the substituted RW (150%) is higher than the borrower RW (85%).
    The CRM processor must NOT apply substitution when it would be disadvantageous.
    The expected RWA for Grade C is therefore 850,000 (borrower, no substitution).

    Guarantee eligibility (Art. 237(2)(a)):
        original_maturity_years = 5.0 ≥ 1.0y → all five guarantees are eligible.

References:
    - PRA PS1/26 Art. 121 (Table 5): SCRA grades and risk weights for unrated institutions
    - PRA PS1/26 Art. 121(1): SCRA Grade A → 40% (>3m), 20% (<=3m)
    - PRA PS1/26 Art. 121(1A): SCRA Grade A_ENHANCED → 30% (>3m), 20% (<=3m)
    - PRA PS1/26 Art. 121(2): SCRA Grade B → 75% (>3m), 50% (<=3m)
    - PRA PS1/26 Art. 121(3): SCRA Grade C → 150% (all maturities)
    - PRA PS1/26 Art. 122(2): unrated SME corporate → 85%
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM)
    - PRA PS1/26 Art. 237(2)(a): minimum original maturity of unfunded protection ≥ 1 year
    - src/rwa_calc/data/schemas.py: VALID_SCRA_GRADES = {"A", "A_ENHANCED", "B", "C"}
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_SCRA_RISK_WEIGHTS (long-term)

Usage:
    uv run python tests/fixtures/p1_95/p1_95.py
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
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF: str = "CP_BORROWER_P195"
GUARANTOR_REF_A: str = "CP_GUARANTOR_INST_P195_A"
GUARANTOR_REF_A_ENHANCED: str = "CP_GUARANTOR_INST_P195_A_ENHANCED"
GUARANTOR_REF_B: str = "CP_GUARANTOR_INST_P195_B"
GUARANTOR_REF_C: str = "CP_GUARANTOR_INST_P195_C"
GUARANTOR_REF_NULL: str = "CP_GUARANTOR_INST_P195_NULL"

# Loan references (one per SCRA grade)
LOAN_REF_A: str = "LN_P195_A"
LOAN_REF_A_ENHANCED: str = "LN_P195_A_ENHANCED"
LOAN_REF_B: str = "LN_P195_B"
LOAN_REF_C: str = "LN_P195_C"
LOAN_REF_NULL: str = "LN_P195_NULL"

# Guarantee references (one per SCRA grade)
GUARANTEE_REF_A: str = "GTE_P195_A"
GUARANTEE_REF_A_ENHANCED: str = "GTE_P195_A_ENHANCED"
GUARANTEE_REF_B: str = "GTE_P195_B"
GUARANTEE_REF_C: str = "GTE_P195_C"
GUARANTEE_REF_NULL: str = "GTE_P195_NULL"

# Dates
VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE: date = date(
    2031, 1, 1
)  # 5y loan; long-term (>3m) — all SCRA long-term weights apply

# Economics
LOAN_AMOUNT: float = 1_000_000.0  # GBP 1,000,000 drawn
LOAN_INTEREST: float = 0.0  # interest = 0 → EAD = drawn_amount
EAD: float = LOAN_AMOUNT + LOAN_INTEREST

# Guarantee coverage
PERCENTAGE_COVERED: float = 1.00  # 100% coverage
ORIGINAL_MATURITY_YEARS: float = 5.0  # 5y ≥ 1y → eligible under Art. 237(2)(a)

# Borrower annual revenue: GBP 20m < GBP 44m SME threshold
# → classifier derives is_sme=True → B31 unrated SME corporate RW = 85%
BORROWER_ANNUAL_REVENUE: float = 20_000_000.0

# ---------------------------------------------------------------------------
# Expected risk weights (load-bearing for test assertions; do not bake into engine)
# ---------------------------------------------------------------------------

# Borrower (unrated SME corporate, B31 Art. 122(2))
EXPECTED_RW_BORROWER: float = 0.85

# SCRA guarantor substituted risk weights (long-term >3m, B31 Art. 121 Table 5)
EXPECTED_RW_SCRA_A: float = 0.40  # Art. 121(1)
EXPECTED_RW_SCRA_A_ENHANCED: float = 0.30  # Art. 121(1A) — A_ENHANCED
EXPECTED_RW_SCRA_B: float = 0.75  # Art. 121(2)
EXPECTED_RW_SCRA_C: float = 1.50  # Art. 121(3) — > borrower RW; substitution does NOT apply

# Expected RWAs (EAD × effective risk weight)
# Grades A, A_ENHANCED, B: substituted RW < borrower RW → substitution applies
EXPECTED_RWA_A: float = EAD * EXPECTED_RW_SCRA_A  # 400,000
EXPECTED_RWA_A_ENHANCED: float = EAD * EXPECTED_RW_SCRA_A_ENHANCED  # 300,000
EXPECTED_RWA_B: float = EAD * EXPECTED_RW_SCRA_B  # 750,000
# Grade C: substituted RW (150%) > borrower RW (85%) → no substitution, use borrower RW
EXPECTED_RWA_C: float = EAD * EXPECTED_RW_BORROWER  # 850,000
# null: no SCRA grade → no substitution possible, use borrower RW
EXPECTED_RWA_NULL: float = EAD * EXPECTED_RW_BORROWER  # 850,000


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.95 counterparty row (borrower or institution guarantor).

    Borrower: corporate, GB, SME (annual_revenue < threshold), unrated, no scra_grade.
    Guarantors: institution, GB, not SME, unrated (no rating row), scra_grade in
        {"A", "A_ENHANCED", "B", "C", None} — the discriminating parameter.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    annual_revenue: float | None
    scra_grade: str | None

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "annual_revenue": self.annual_revenue,
            "scra_grade": self.scra_grade,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.95 loan: GBP 1,000,000 drawn, 5-year maturity (2026-01-01 to 2031-01-01).

    Residual maturity = 5y >> 3m → all SCRA long-term risk weights apply.
    interest = 0 → EAD = drawn_amount = 1,000,000 GBP.
    seniority = "senior": standard senior unsecured claim.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    P1.95 guarantee row: unfunded guarantee from unrated GB institution.

    original_maturity_years = 5.0 ≥ 1.0y → eligible under CRR Art. 237(2)(a).
    percentage_covered = 1.00 → full (100%) coverage of the loan.
    protection_type = "guarantee": standard unfunded credit guarantee.
    guarantor_seniority = "senior": default; irrelevant for SA RWSM substitution.
    """

    guarantee_reference: str
    guarantor: str
    beneficiary_type: str
    beneficiary_reference: str
    currency: str
    percentage_covered: float
    original_maturity_years: float
    protection_type: str
    guarantor_seniority: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantor": self.guarantor,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "currency": self.currency,
            "percentage_covered": self.percentage_covered,
            "original_maturity_years": self.original_maturity_years,
            "protection_type": self.protection_type,
            "guarantor_seniority": self.guarantor_seniority,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p195_counterparties() -> pl.DataFrame:
    """
    Return all P1.95 counterparties as a DataFrame (6 rows: 1 borrower + 5 guarantors).

    Borrower (CP_BORROWER_P195):
        entity_type = "corporate", GB, annual_revenue = GBP 20m (< GBP 44m SME threshold)
        → classifier derives is_sme=True → B31 unrated SME corporate RW = 85%.
        scra_grade = null: not an institution, no SCRA grade applies.

    Guarantors (CP_GUARANTOR_INST_P195_<grade>):
        entity_type = "institution", GB, not SME, unrated (no rating row).
        scra_grade in {"A", "A_ENHANCED", "B", "C", null} — the discriminating column.
        annual_revenue = null: institutions do not have SME revenue thresholds.
        No external ECAI rating rows → SCRA (unrated institution) path forced.
    """
    rows = [
        # ================================================================
        # Borrower: unrated SME corporate (B31 Art. 122(2) → RW = 85%)
        # annual_revenue = GBP 20m < GBP 44m → classified as SME by engine
        # ================================================================
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.95 Unrated SME Corporate Borrower GB",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=BORROWER_ANNUAL_REVENUE,
            scra_grade=None,
        ),
        # ================================================================
        # Guarantor — SCRA Grade A (RW 40% long-term, 20% short-term)
        # Substitution applies: 40% < 85% → RWA = 400,000
        # ================================================================
        _Counterparty(
            counterparty_reference=GUARANTOR_REF_A,
            counterparty_name="P1.95 Unrated Institution Guarantor GB SCRA-A",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=None,
            scra_grade="A",
        ),
        # ================================================================
        # Guarantor — SCRA Grade A_ENHANCED (RW 30% long-term, 20% short-term)
        # Substitution applies: 30% < 85% → RWA = 300,000
        # CET1 >= 14% AND leverage ratio >= 5% (criteria not validated by fixture)
        # ================================================================
        _Counterparty(
            counterparty_reference=GUARANTOR_REF_A_ENHANCED,
            counterparty_name="P1.95 Unrated Institution Guarantor GB SCRA-A-ENHANCED",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=None,
            scra_grade="A_ENHANCED",
        ),
        # ================================================================
        # Guarantor — SCRA Grade B (RW 75% long-term, 50% short-term)
        # Substitution applies: 75% < 85% → RWA = 750,000
        # ================================================================
        _Counterparty(
            counterparty_reference=GUARANTOR_REF_B,
            counterparty_name="P1.95 Unrated Institution Guarantor GB SCRA-B",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=None,
            scra_grade="B",
        ),
        # ================================================================
        # Guarantor — SCRA Grade C (RW 150% all maturities)
        # NO substitution: 150% > 85% → RWA = 850,000 (borrower RW applies)
        # ================================================================
        _Counterparty(
            counterparty_reference=GUARANTOR_REF_C,
            counterparty_name="P1.95 Unrated Institution Guarantor GB SCRA-C",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=None,
            scra_grade="C",
        ),
        # ================================================================
        # Guarantor — null SCRA grade (no grade assigned)
        # No SCRA substitution path available → RWA = 850,000 (borrower RW)
        # ================================================================
        _Counterparty(
            counterparty_reference=GUARANTOR_REF_NULL,
            counterparty_name="P1.95 Unrated Institution Guarantor GB SCRA-null",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            annual_revenue=None,
            scra_grade=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p195_loans() -> pl.DataFrame:
    """
    Return all P1.95 loans as a DataFrame (5 rows, one per SCRA grade variant).

    Each loan is GBP 1,000,000, value_date=2026-01-01, maturity_date=2031-01-01 (5y).
    All five loans reference the same borrower (CP_BORROWER_P195).
    Residual maturity = 5y >> 3m → SCRA long-term risk weights apply for the guarantor.
    EAD = 1,000,000 for each row.
    """
    loan_rows = [
        (LOAN_REF_A, "LN_P195_A: SCRA Grade A guarantor"),
        (LOAN_REF_A_ENHANCED, "LN_P195_A_ENHANCED: SCRA Grade A_ENHANCED guarantor"),
        (LOAN_REF_B, "LN_P195_B: SCRA Grade B guarantor"),
        (LOAN_REF_C, "LN_P195_C: SCRA Grade C guarantor"),
        (LOAN_REF_NULL, "LN_P195_NULL: null SCRA grade guarantor"),
    ]
    rows = [
        _Loan(
            loan_reference=ref,
            counterparty_reference=BORROWER_REF,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=LOAN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
        )
        for ref, _description in loan_rows
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p195_guarantees() -> pl.DataFrame:
    """
    Return all P1.95 guarantee rows as a DataFrame (5 rows, one per SCRA grade variant).

    Each guarantee:
        protection_type = "guarantee": unfunded credit guarantee.
        beneficiary_type = "loan": links to the corresponding loan row.
        percentage_covered = 1.00: 100% of the loan is covered.
        original_maturity_years = 5.0 ≥ 1.0y: satisfies Art. 237(2)(a) eligibility.
        currency = "GBP": no FX mismatch haircut.
        guarantor_seniority = "senior": standard (irrelevant for SA RWSM).

    The five guarantees link each loan to its corresponding SCRA-graded guarantor.
    """
    guarantee_rows = [
        (GUARANTEE_REF_A, GUARANTOR_REF_A, LOAN_REF_A),
        (GUARANTEE_REF_A_ENHANCED, GUARANTOR_REF_A_ENHANCED, LOAN_REF_A_ENHANCED),
        (GUARANTEE_REF_B, GUARANTOR_REF_B, LOAN_REF_B),
        (GUARANTEE_REF_C, GUARANTOR_REF_C, LOAN_REF_C),
        (GUARANTEE_REF_NULL, GUARANTOR_REF_NULL, LOAN_REF_NULL),
    ]
    rows = [
        _Guarantee(
            guarantee_reference=gte_ref,
            guarantor=guarantor_ref,
            beneficiary_type="loan",
            beneficiary_reference=loan_ref,
            currency="GBP",
            percentage_covered=PERCENTAGE_COVERED,
            original_maturity_years=ORIGINAL_MATURITY_YEARS,
            protection_type="guarantee",
            guarantor_seniority="senior",
        )
        for gte_ref, guarantor_ref, loan_ref in guarantee_rows
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p195_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.95 parquet files and return a mapping of name to path.

    Files written:
        counterparties.parquet — 6 rows (1 borrower + 5 SCRA-graded guarantors)
        loans.parquet          — 5 rows (one per SCRA grade variant)
        guarantees.parquet     — 5 rows (one per SCRA grade variant)

    No ratings rows are written: borrower and all guarantors are unrated (no ECAI CQS).
    The absence of ratings rows forces the SCRA (unrated) path for all institution
    guarantors. The borrower has no rating either — it uses the unrated SME corporate
    path via B31 Art. 122(2).

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparties", create_p195_counterparties()),
        ("loans", create_p195_loans()),
        ("guarantees", create_p195_guarantees()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.95 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: B31 SCRA-grade dispatch for unrated institution guarantor")
    print(
        f"  Borrower: {BORROWER_REF} (SME corporate, GB, annual_revenue=GBP {BORROWER_ANNUAL_REVENUE:,.0f})"
    )
    print(f"  Borrower B31 SA RW (unrated SME corporate, Art. 122(2)): {EXPECTED_RW_BORROWER:.0%}")
    print(f"  EAD per loan: GBP {EAD:,.0f}")
    print()
    print(f"  {'SCRA Grade':<14} {'Guarantor RW':>14} {'Substitution?':>14} {'Expected RWA':>14}")
    print(f"  {'-' * 57}")
    print(f"  {'A':<14} {EXPECTED_RW_SCRA_A:>13.0%} {'Yes':>14} {EXPECTED_RWA_A:>14,.0f}")
    print(
        f"  {'A_ENHANCED':<14} {EXPECTED_RW_SCRA_A_ENHANCED:>13.0%} {'Yes':>14} {EXPECTED_RWA_A_ENHANCED:>14,.0f}"
    )
    print(f"  {'B':<14} {EXPECTED_RW_SCRA_B:>13.0%} {'Yes':>14} {EXPECTED_RWA_B:>14,.0f}")
    print(
        f"  {'C':<14} {EXPECTED_RW_SCRA_C:>13.0%} {'No (>borrower)':>14} {EXPECTED_RWA_C:>14,.0f}"
    )
    print(f"  {'null':<14} {'N/A':>13} {'No (no grade)':>14} {EXPECTED_RWA_NULL:>14,.0f}")
    print("-" * 80)


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p195_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
