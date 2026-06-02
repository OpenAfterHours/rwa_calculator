"""
Generate P1.200 fixtures: B31 guarantee/CDS maturity-mismatch (t−0.25)/(T−0.25) scaling.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantees.py)

Key responsibilities:
- Produce two counterparty rows:
    CP-OBLIGOR-200:   corporate, GB, cqs=null (unrated → 100% SA RW Art. 122)
    CP-GUARANTOR-200: institution, GB, cqs=1 (external rating → 20% SA RW)
- Produce one loan row:
    EXP-200: GBP 1,000,000, value_date=2026-06-01, maturity_date=2030-06-01 (T=4.0y)
- Produce one guarantee row:
    G-200: original_maturity_years=2.0 (t=2.0y < T=4.0y → mismatch)
           protection_type=credit_derivative, includes_restructuring=True
           Art. 239(3): GA = 1,000,000 × (2.0−0.25)/(4.0−0.25) = 466,666.6666666667
- Produce one external rating row (guarantor CQS 1 only; obligor is unrated/null CQS).

Defect under test (pre-fix):
    crm/guarantees.py guards the only call to _apply_maturity_mismatch_to_guarantees()
    with ``if config.is_crr``.  Under basel_3_1(), the guard prevents the scaling
    entirely, so GA = 1,000,000 (full face), yielding RWA = 200,000 (20% × 1m).
    The correct B31 RWA is 626,666.67 — an understatement of 426,667 (~68%).

Post-fix assertion (primary):
    EXP-200 + G-200, config=basel_3_1() → Art. 239(3) applies → RWA = 626,666.6666666666
    EXP-200 + G-200, config=crr()       → same scaling (CRR already correct) → same RWA

Hand-calculations (Art. 239(3), CalculationConfig.basel_3_1()):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP
    T_raw = (2030-06-01 − 2026-06-01) = 4.0y; T_eff = max(min(4.0,5.0),0.25) = 4.0
    t_raw = original_maturity_years = 2.0y; filter 2.0 >= 1.0 → ELIGIBLE (Art.237(2)(a))
    t_eff = max(2.0, 0.25) = 2.0
    mismatch: t_eff 2.0 < T_eff 4.0 → scaling applies
    H_fx = 0 (GBP = GBP); H_r = 0 (includes_restructuring = True, CDS)
    G* = 1,000,000 × 1 × 1 = 1,000,000
    m = (t_eff − 0.25) / (T_eff − 0.25) = 1.75 / 3.75 = 0.4666666666666667
    GA = G* × m = 466,666.6666666667
    uncovered = 1,000,000 − 466,666.6666666667 = 533,333.3333333333
    RW_borrower = 1.00 (unrated corp, Art. 122); RW_guarantor = 0.20 (institution CQS 1)
    CORRECT B31 RWA = 466,666.67 × 0.20 + 533,333.33 × 1.00
                    = 93,333.33 + 533,333.33
                    = 626,666.6666666666

References:
    - PS1/26 Art. 235(1): RWSM substitution approach
    - PS1/26 Art. 237(2)(a): minimum original maturity >= 1y eligibility filter
    - PS1/26 Art. 238(1): definition of protection maturity t
    - PS1/26 Art. 239(3): GA = G* × (t−0.25)/(T−0.25) maturity mismatch adjustment
    - CRR Art. 239(3): identical formula (both frameworks)
    - src/rwa_calc/data/schemas.py: GUARANTEE_SCHEMA (original_maturity_years field)
    - src/rwa_calc/engine/crm/guarantees.py: _apply_maturity_mismatch_to_guarantees

Usage:
    python tests/fixtures/p1_200/p1_200.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, GUARANTEE_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — exported for test assertions
# ---------------------------------------------------------------------------

REPORTING_DATE = date(2026, 6, 1)

# Counterparty references
OBLIGOR_REF = "CP-OBLIGOR-200"
GUARANTOR_REF = "CP-GUARANTOR-200"

# Exposure reference
LOAN_REF = "EXP-200"

# Guarantee reference
GUARANTEE_REF = "G-200"

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_EAD = LOAN_DRAWN_AMOUNT  # interest = 0

# Loan maturity: T = 4.0y from reporting date 2026-06-01
LOAN_VALUE_DATE = date(2026, 6, 1)
LOAN_MATURITY_DATE = date(2030, 6, 1)

# Guarantee maturity parameters
GUARANTEE_ORIGINAL_MATURITY_YEARS: float = 2.0  # t = 2.0y  (>= 1.0 → eligible)
GUARANTEE_MATURITY_DATE = date(2028, 6, 1)       # approx 2y from value date

# Art. 239(3) scalars
_T_EFF: float = 4.0    # max(min(4.0, 5.0), 0.25)
_T_EFF_FLOOR: float = 0.25
_t_EFF: float = 2.0    # max(2.0, 0.25)

# Derived: maturity multiplier m = (t−0.25)/(T−0.25) = 1.75/3.75
EXPECTED_MATURITY_MULTIPLIER: float = (_t_EFF - _T_EFF_FLOOR) / (_T_EFF - _T_EFF_FLOOR)

# Guaranteed (GA) and unguaranteed portions
EXPECTED_GUARANTEED_PORTION: float = LOAN_EAD * EXPECTED_MATURITY_MULTIPLIER

# Risk weights
EXPECTED_GUARANTOR_RW: float = 0.20   # institution CQS 1, Art. 120 Table 3
_BORROWER_RW: float = 1.00            # unrated corporate, Art. 122

# Correct B31 total RWA (post-fix)
EXPECTED_TOTAL_RWA_B31: float = (
    EXPECTED_GUARANTEED_PORTION * EXPECTED_GUARANTOR_RW
    + (LOAN_EAD - EXPECTED_GUARANTEED_PORTION) * _BORROWER_RW
)

# Bugged B31 total RWA (pre-fix: mismatch scaling skipped → GA = full 1m)
BUGGED_TOTAL_RWA: float = LOAN_EAD * EXPECTED_GUARANTOR_RW  # = 200,000.0

# Guarantor rating
GUARANTOR_CQS = 1
_GUARANTOR_RATING_VALUE = "AA"   # CQS 1: AAA–AA-
RATING_AGENCY = "S&P"
RATING_DATE = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.200 counterparty row."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.200 loan: GBP 1,000,000 drawn, 4-year maturity."""

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
class _Rating:
    """P1.200 external ECAI rating."""

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


@dataclass(frozen=True)
class _Guarantee:
    """
    P1.200 guarantee row: CDS (credit_derivative) with maturity mismatch.

    Uses original_maturity_years (GUARANTEE_SCHEMA field, Art. 237/239(3)) and
    includes_restructuring=True to suppress the 40% H_r haircut (Art.233(2)).
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
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1200_counterparties() -> pl.DataFrame:
    """
    Return two P1.200 counterparties (obligor + guarantor) as a DataFrame.

    CP-OBLIGOR-200:   corporate, GB, unrated (null CQS) — 100% SA risk weight.
    CP-GUARANTOR-200: institution, GB, CQS 1 — 20% SA risk weight.
    """
    rows = [
        _Counterparty(
            counterparty_reference=OBLIGOR_REF,
            counterparty_name="P1.200 Obligor Corporate GB Unrated",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.200 Guarantor Institution GB CQS1",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1200_loan() -> pl.DataFrame:
    """
    Return one P1.200 loan as a DataFrame.

    EXP-200: GBP 1,000,000, value_date=2026-06-01, maturity_date=2030-06-01 (T=4.0y).
    EAD = drawn_amount (interest=0) = 1,000,000.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=OBLIGOR_REF,
            currency="GBP",
            value_date=LOAN_VALUE_DATE,
            maturity_date=LOAN_MATURITY_DATE,
            drawn_amount=LOAN_DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1200_ratings() -> pl.DataFrame:
    """
    Return one P1.200 external rating (guarantor only) as a DataFrame.

    CP-GUARANTOR-200: CQS 1 / S&P AA → 20% SA institution RW.
    CP-OBLIGOR-200 is unrated — no rating row (null CQS → 100% unrated corporate RW).
    """
    rows = [
        _Rating(
            rating_reference="RTG-P1200-GUARANTOR",
            counterparty_reference=GUARANTOR_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=_GUARANTOR_RATING_VALUE,
            cqs=GUARANTOR_CQS,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1200_guarantees() -> pl.DataFrame:
    """
    Return one P1.200 guarantee row as a DataFrame.

    G-200: CDS (credit_derivative) from CP-GUARANTOR-200 on EXP-200.
        original_maturity_years = 2.0y (t < T=4.0y → mismatch, passes >=1y filter)
        includes_restructuring = True (suppresses 40% H_r Art.233(2) haircut)
        currency = GBP (no FX haircut vs GBP exposure)
        Art. 239(3): GA = 1,000,000 × (2.0−0.25)/(4.0−0.25) = 466,666.6666666667
    """
    # Use explicit schema dict to ensure optional GUARANTEE_SCHEMA fields are typed correctly
    guarantee_schema_plus = {
        "guarantee_reference": pl.String,
        "guarantee_type": pl.String,
        "guarantor": pl.String,
        "currency": pl.String,
        "maturity_date": pl.Date,
        "amount_covered": pl.Float64,
        "percentage_covered": pl.Float64,
        "beneficiary_type": pl.String,
        "beneficiary_reference": pl.String,
        "protection_type": pl.String,
        "includes_restructuring": pl.Boolean,
        "original_maturity_years": pl.Float64,
    }

    rows = [
        _Guarantee(
            guarantee_reference=GUARANTEE_REF,
            guarantee_type="credit_derivative",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="credit_derivative",
            includes_restructuring=True,
            original_maturity_years=GUARANTEE_ORIGINAL_MATURITY_YEARS,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=guarantee_schema_plus)


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1200_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.200 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the data/ subdirectory
                    within the p1_200 fixture package.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1200_counterparties()),
        ("loan", create_p1200_loan()),
        ("rating", create_p1200_ratings()),
        ("guarantee", create_p1200_guarantees()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.200 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: B31 Art. 239(3) maturity mismatch on unfunded protection (CDS)")
    print(f"  Obligor:   {OBLIGOR_REF} (corporate, unrated, 100% RW)")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS}, 20% RW)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}  maturity {LOAN_MATURITY_DATE}")
    print()
    print(f"  {GUARANTEE_REF}: original_maturity_years={GUARANTEE_ORIGINAL_MATURITY_YEARS}")
    print(f"    T_eff={_T_EFF:.2f}y, t_eff={_t_EFF:.2f}y → mismatch → Art.239(3) applies")
    print(f"    m = ({_t_EFF}−0.25)/({_T_EFF}−0.25) = {EXPECTED_MATURITY_MULTIPLIER:.16f}")
    print(f"    GA = 1,000,000 × m = {EXPECTED_GUARANTEED_PORTION:.10f}")
    print(f"    CORRECT B31 RWA = {EXPECTED_TOTAL_RWA_B31:.10f}")
    print(f"    BUGGED B31 RWA (guard blocks scaling) = {BUGGED_TOTAL_RWA:.1f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1200_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
