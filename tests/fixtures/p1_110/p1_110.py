"""
Generate P1.110 fixtures: B31 SA RWSM corporate CQS-3 guarantor risk weight = 75%.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Key responsibilities:
- Produce two counterparty rows:
    CP_BORROWER_P1110: corporate, GB, default_status=False, is_financial_sector_entity=False
    CP_GUARANTOR_P1110: corporate, GB, default_status=False, is_financial_sector_entity=False,
                        is_ccp_client_cleared=False
- Produce one loan row:
    LOAN_P1110: GBP 1,000,000 term loan, value_date=2027-01-02, maturity_date=2032-01-02 (5y)
- Produce one guarantee row:
    GTE_P1110: full-coverage (100%) GBP corporate guarantee from CP_GUARANTOR_P1110,
               covering LOAN_P1110, maturity_date=2032-01-02, original_maturity_years=5.0,
               includes_restructuring=True, guarantor_seniority="senior"
- Produce two external rating rows:
    Borrower: CQS=5 (S&P "B"), pd=null — triggers 150% SA RW (both CRR and B31)
    Guarantor: CQS=3 (S&P "BBB"), pd=null — the discriminating defect-triggering value

Defect under test (pre-fix):
    Under B31 SA RWSM (PRA PS1/26 Art. 235), the guarantee substitution should
    apply the guarantor's B31 SA risk weight (Art. 122(2) Table 6: CQS 3 = 75%).
    Pre-fix, the engine uses 100% (the CRR Table 5 value) for CQS 3, overstating
    capital by GBP 250,000 on a 1m GBP exposure.

Post-fix assertion (primary):
    B31 (CalculationConfig.basel_3_1()):
        guarantor SA RW (corporate CQS 3) = 75%
        Substituted RW = 75% (guarantor RW < borrower pre-CRM RW of 150%)
        RWA = 1,000,000 × 0.75 = 750,000

CRR regression assertion:
    CRR (CalculationConfig.crr()):
        guarantor SA RW (corporate CQS 3, CRR Table 5) = 100%
        Substituted RW = 100% (guarantor RW < borrower pre-CRM RW of 150%)
        RWA = 1,000,000 × 1.00 = 1,000,000

Hand-calculation (shared input data, different config):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP

    B31 path (CalculationConfig.basel_3_1()):
        Borrower SA RW: corporate CQS 5 → 100% (Art. 122(2) Table 6, CQS 5)
        Guarantor SA RW: corporate CQS 3 → 75% (Art. 122(2) Table 6, CQS 3)
        Guarantee eligible: original_maturity_years=5.0 ≥ 1.0y (Art. 237(2)(a))
        Substitution applies: guarantor RW 75% < borrower RW 100% → use 75%
        RWA = 1,000,000 × 0.75 = 750,000

    CRR path (CalculationConfig.crr()):
        Borrower SA RW: corporate CQS 5 → 150% (CRR Table 5, CQS 5)
        Guarantor SA RW: corporate CQS 3 → 100% (CRR Table 5, CQS 3)
        Substitution applies: guarantor RW 100% < borrower RW 150% → use 100%
        RWA = 1,000,000 × 1.00 = 1,000,000

Note: The same parquet files are used for both framework assertions. The test
parametrises the framework by passing CalculationConfig.basel_3_1() vs
CalculationConfig.crr() — fixture data is config-agnostic.

Note on rating_type: The valid values for rating_type are "external" and "internal"
(VALID_RATING_TYPES in schemas.py). The architect's proposal used "issuer" to indicate
an external issuer rating; "external" is the correct schema value.

References:
    - PRA PS1/26 Art. 122(2) Table 6: B31 corporate SA risk weights by CQS
      (CQS 3 = 75%, CQS 5 = 100%)
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Table 5: CRR corporate SA risk weights by CQS
      (CQS 3 = 100%, CQS 5 = 150%)
    - CRR Art. 237(2)(a): original maturity of unfunded credit protection >= 1 year
    - src/rwa_calc/data/schemas.py: GUARANTEE_SCHEMA (guarantor_seniority added by P1.156)

Usage:
    uv run python tests/fixtures/p1_110/p1_110.py
    uv run python tests/fixtures/p1_110/p1_110.py --data-dir tests/fixtures/p1_110/data
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, GUARANTEE_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references (as specified in proposal)
BORROWER_REF = "CP_BORROWER_P1110"
GUARANTOR_REF = "CP_GUARANTOR_P1110"

# Loan reference
LOAN_REF = "LOAN_P1110"

# Guarantee reference
GUARANTEE_REF = "GTE_P1110"

# Rating references
RTG_BORROWER_REF = "RTG-P1110-BORROWER"
RTG_GUARANTOR_REF = "RTG-P1110-GUARANTOR"

# Loan dates (Basel 3.1 effective 1 Jan 2027 — value_date post-go-live)
LOAN_VALUE_DATE = date(2027, 1, 2)
LOAN_MATURITY_DATE = date(2032, 1, 2)  # 5y residual
GUARANTEE_MATURITY_DATE = date(2032, 1, 2)  # matches loan — no maturity mismatch

RATING_DATE = date(2027, 1, 2)

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_INTEREST = 0.0
LOAN_EAD = LOAN_DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Guarantee coverage
AMOUNT_COVERED = 1_000_000.0  # full coverage
PERCENTAGE_COVERED = 1.0
ORIGINAL_MATURITY_YEARS = 5.0  # ≥ 1y → satisfies Art. 237(2)(a) eligibility

# CQS assignments
# Borrower:  CQS 5 — corporate SA RW = 100% (B31) / 150% (CRR)
# Guarantor: CQS 3 — the defect-triggering value:
#                     B31 Table 6 → 75%   (post-fix expected)
#                     CRR Table 5 → 100%  (pre-fix bug + CRR regression)
BORROWER_CQS = 5
GUARANTOR_CQS = 3  # discriminating threshold

# Representative S&P rating values for CQS mapping
_CQS_RATING_VALUE: dict[int, str] = {
    3: "BBB",  # CQS 3: BBB+ to BBB-  → use BBB (mid-band)
    5: "B",  # CQS 5: B+ to B-      → use B   (mid-band)
}
RATING_AGENCY = "S&P"

# Expected SA risk weights (for documentation; assertions live in the test)
# B31 (CalculationConfig.basel_3_1()):
EXPECTED_BORROWER_RW_B31: float = 1.00  # corporate CQS 5, B31 Table 6
EXPECTED_GUARANTOR_RW_B31: float = 0.75  # corporate CQS 3, B31 Table 6 — POST-FIX
EXPECTED_RWA_B31: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_B31  # 750,000

# CRR (CalculationConfig.crr()):
EXPECTED_BORROWER_RW_CRR: float = 1.50  # corporate CQS 5, CRR Table 5
EXPECTED_GUARANTOR_RW_CRR: float = 1.00  # corporate CQS 3, CRR Table 5 — regression
EXPECTED_RWA_CRR: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_CRR  # 1,000,000

# Pre-fix bug reference (B31, before the defect is repaired):
EXPECTED_RWA_B31_PRE_FIX: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_CRR  # 1,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.110 counterparty row (borrower or guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.110 loan: GBP 1,000,000 term loan, 5-year maturity."""

    loan_reference: str
    product_type: str
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
            "product_type": self.product_type,
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
    P1.110 guarantee row.

    Full coverage of LOAN_P1110 by CP_GUARANTOR_P1110 (corporate, CQS 3).
    The discriminating risk weight is:
        B31 Art. 122(2) Table 6 CQS 3 → 75%
        CRR Table 5             CQS 3 → 100%

    guarantor_seniority is present in GUARANTEE_SCHEMA (added by P1.156).
    original_maturity_years is present in GUARANTEE_SCHEMA (added by P1.124).
    """

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date
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
    """P1.110 external ECAI rating: S&P scale, pd=None, internal_pd=None, model_id=None."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1110_counterparties() -> pl.DataFrame:
    """
    Return two P1.110 counterparties (borrower + guarantor) as a DataFrame.

    CP_BORROWER_P1110: corporate, GB, CQS=5 — 150% CRR / 100% B31 SA risk weight.
    CP_GUARANTOR_P1110: corporate, GB, CQS=3 — 100% CRR / 75% B31 SA risk weight.

    Both counterparties are non-FSE (is_financial_sector_entity=False) so the
    Art. 122(2)(a) FSE 1.25× scalar gate does not apply.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.110 Borrower Corporate GB CQS5",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.110 Guarantor Corporate GB CQS3",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1110_loan() -> pl.DataFrame:
    """
    Return one P1.110 loan as a DataFrame.

    LOAN_P1110: GBP 1,000,000 term loan on borrower CP_BORROWER_P1110.
    value_date=2027-01-02 (post Basel 3.1 go-live), maturity_date=2032-01-02 (5y).
    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP.
    seniority=senior_unsecured so borrower SA RW is the unmitigated corporate RW.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="term_loan",
        counterparty_reference=BORROWER_REF,
        currency="GBP",
        value_date=LOAN_VALUE_DATE,
        maturity_date=LOAN_MATURITY_DATE,
        drawn_amount=LOAN_DRAWN_AMOUNT,
        interest=LOAN_INTEREST,
        seniority="senior_unsecured",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1110_guarantee() -> pl.DataFrame:
    """
    Return one P1.110 guarantee as a DataFrame.

    GTE_P1110: full-coverage (100%) corporate guarantee from CP_GUARANTOR_P1110
    covering LOAN_P1110.

    original_maturity_years=5.0 ≥ 1.0y → satisfies Art. 237(2)(a) eligibility.
    guarantor_seniority="senior" → F-IRB LGD selector (irrelevant for SA path,
    included for schema completeness and parity with P1.156/P1.157 fixtures).
    maturity_date matches loan maturity → no maturity mismatch adjustment.

    The discriminating element is the guarantor's CQS 3:
        B31 (CalculationConfig.basel_3_1()): Art. 122(2) Table 6 → 75% RW
        CRR (CalculationConfig.crr()):        CRR Table 5          → 100% RW
    """
    guarantee = _Guarantee(
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
    return pl.DataFrame([guarantee.to_dict()], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p1110_ratings() -> pl.DataFrame:
    """
    Return two P1.110 external ratings (one per counterparty) as a DataFrame.

    Borrower  (CP_BORROWER_P1110):   CQS 5 / S&P B
        → 150% SA corporate RW (CRR) / 100% SA corporate RW (B31).
    Guarantor (CP_GUARANTOR_P1110):  CQS 3 / S&P BBB
        → 100% SA corporate RW (CRR) / 75% SA corporate RW (B31) — discriminating value.

    pd=None and model_id=None on both rows: no PSM / IRB path is triggered.
    This ensures the SA RWSM code path is exercised exclusively.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=_CQS_RATING_VALUE[BORROWER_CQS],
            cqs=BORROWER_CQS,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=_CQS_RATING_VALUE[GUARANTOR_CQS],
            cqs=GUARANTOR_CQS,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type, written to data/ subdirectory)
# ---------------------------------------------------------------------------


def save_p1110_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.110 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the ``data/`` subdirectory
            next to this file (``tests/fixtures/p1_110/data/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p1110_counterparties()),
        ("loan", create_p1110_loan()),
        ("guarantee", create_p1110_guarantee()),
        ("rating", create_p1110_ratings()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.110 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: B31 SA RWSM corporate CQS-3 guarantor RW = 75% (Art. 122(2) Table 6)")
    print(f"  Borrower:  {BORROWER_REF} (corporate, CQS {BORROWER_CQS})")
    print(f"             B31 pre-CRM RW = {EXPECTED_BORROWER_RW_B31:.0%}")
    print(f"             CRR pre-CRM RW = {EXPECTED_BORROWER_RW_CRR:.0%}")
    print(f"  Guarantor: {GUARANTOR_REF} (corporate, CQS {GUARANTOR_CQS})")
    print(f"             B31 RW = {EXPECTED_GUARANTOR_RW_B31:.0%} (Art. 122(2) Table 6)")
    print(f"             CRR RW = {EXPECTED_GUARANTOR_RW_CRR:.0%} (CRR Table 5)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print(f"  Guarantee: {GUARANTEE_REF}  100% coverage, original_maturity=5.0y, senior")
    print()
    print("  B31 (CalculationConfig.basel_3_1()):")
    print(f"    Substituted guarantor RW = {EXPECTED_GUARANTOR_RW_B31:.0%}")
    print(f"    Expected RWA             = {EXPECTED_RWA_B31:,.0f}")
    print(
        f"    Pre-fix bug RWA          = {EXPECTED_RWA_B31_PRE_FIX:,.0f}  (overstates by 250,000)"
    )
    print()
    print("  CRR (CalculationConfig.crr()) — regression:")
    print(f"    Substituted guarantor RW = {EXPECTED_GUARANTOR_RW_CRR:.0%}")
    print(f"    Expected RWA             = {EXPECTED_RWA_CRR:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1110_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
