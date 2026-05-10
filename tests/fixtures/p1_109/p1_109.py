"""
Generate P1.109 fixtures: CRR Art. 237/238/239(3) maturity mismatch on unfunded protection.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Key responsibilities:
- Produce two counterparty rows:
    CP_BORROWER_P1109: corporate, GB, cqs=4 (external rating, 100% SA RW)
    CP_GUARANTOR_P1109: institution, GB, cqs=1 (external rating, 20% SA RW)
- Produce one loan row:
    LOAN_001_P1109: GBP 1,000,000, value_date=2026-01-01, maturity_date=2031-01-01 (5y residual)
- Produce two guarantee rows (parametrised scenarios):
    GUAR_FULL_P1109:  maturity_date=2031-01-01, original_maturity_years=5.0
                      Full-tenor guarantee — no maturity mismatch.
                      GA = 1,000,000, RWA = 200,000 (guarantor CQS 1 at 20%).
    GUAR_MM_P1109:    maturity_date=2028-07-01, original_maturity_years=2.5
                      Mismatched guarantee: residual 2.5y < loan residual 5y.
                      Art. 239(3) scaling applies:
                        GA = 1,000,000 × (2.5 − 0.25) / (5.0 − 0.25) = 473,684.2105263158
                        guaranteed RWA = 473,684.2105263158 × 0.20 = 94,736.8421052632
                        unguaranteed RWA = 526,315.7894736842 × 1.00 = 526,315.7894736842
                        total RWA = 621,052.6315789474
- Produce two external rating rows: one per counterparty.

Defect under test (pre-fix):
    The CRM processor does not implement CRR Art. 239(3), which requires that the
    covered portion of an exposure (GA) is scaled when the protection's residual
    maturity is shorter than the exposure's residual maturity.  Without the fix,
    GUAR_MM_P1109 is applied at full face value, yielding RWA = 200,000 rather than
    the correct 621,052.63 — understating RWA by approximately 421,053.

Post-fix assertion (primary):
    LOAN_001_P1109 + GUAR_FULL_P1109 → full-tenor, no scaling → RWA = 200,000
    LOAN_001_P1109 + GUAR_MM_P1109   → Art. 239(3) scaling  → RWA = 621,052.6315789474

Hand-calculations (CRR Art. 239(3), CalculationConfig.crr()):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP

    GUAR_FULL_P1109 (no-mismatch control):
        t = original_maturity_years = 5.0y, T = exposure residual = 5.0y
        t >= T → no adjustment, GA = 1,000,000
        RWA = 1,000,000 × 0.20 = 200,000

    GUAR_MM_P1109 (mismatch path):
        t = original_maturity_years = 2.5y, T = exposure residual = 5.0y
        Art. 239(3): GA = G* × (t − 0.25) / (T − 0.25)
                        = 1,000,000 × (2.5 − 0.25) / (5.0 − 0.25)
                        = 1,000,000 × 2.25 / 4.75
                        = 473,684.2105263158
        guaranteed portion RWA   = 473,684.2105263158 × 0.20 = 94,736.8421052632
        unguaranteed portion RWA = 526,315.7894736842 × 1.00 = 526,315.7894736842
        total RWA                = 621,052.6315789474

Schema dependency:
    GUARANTEE_SCHEMA in src/rwa_calc/data/schemas.py includes ``original_maturity_years``
    (ColumnSpec(pl.Float64, required=False)) — added in P1.124.

References:
    - CRR Art. 237(2)(a): minimum residual maturity of protection >= 1 year
    - CRR Art. 238: maturity of credit protection (t = min of contractual, original)
    - CRR Art. 239(3): maturity mismatch adjustment formula GA = G* × (t − 0.25) / (T − 0.25)
    - CRR Art. 207: eligibility conditions for unfunded credit protection
    - src/rwa_calc/data/schemas.py: GUARANTEE_SCHEMA
    - src/rwa_calc/engine/crm/: CRM processor maturity mismatch adjustment

Usage:
    uv run python tests/fixtures/p1_109/p1_109.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF = "CP_BORROWER_P1109"
GUARANTOR_REF = "CP_GUARANTOR_P1109"

# Loan reference
LOAN_REF = "LOAN_001_P1109"

# Guarantee references
GUAR_FULL_REF = "GUAR_FULL_P1109"  # full-tenor, no mismatch (control)
GUAR_MM_REF = "GUAR_MM_P1109"  # maturity-mismatched guarantee (Art. 239(3))

# Loan dates
LOAN_VALUE_DATE = date(2026, 1, 1)
LOAN_MATURITY_DATE = date(2031, 1, 1)  # 5y residual (reporting date = value date)

# Guarantee maturity dates
# Full-tenor: matches the loan maturity exactly — no mismatch.
GUAR_FULL_MATURITY = date(2031, 1, 1)
# Mismatch: 2.5y original maturity, shorter than the 5y loan residual.
GUAR_MM_MATURITY = date(2028, 7, 1)

# Original maturity in fractional years (written into parquet for Art. 239(3) engine use)
GUAR_FULL_ORIGINAL_MATURITY_YEARS: float = 5.0
GUAR_MM_ORIGINAL_MATURITY_YEARS: float = 2.5

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_INTEREST = 0.0
LOAN_EAD = LOAN_DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Risk weights (CRR, external rating)
BORROWER_CQS = 4  # corporate CQS 4 → 100% RW
GUARANTOR_CQS = 1  # institution CQS 1 → 20% RW

# Maturity mismatch parameters (Art. 239(3))
LOAN_RESIDUAL_MATURITY_YEARS: float = 5.0  # T
GUAR_MM_RESIDUAL_YEARS: float = 2.5  # t (= original_maturity_years for new protection)
_MATURITY_FLOOR: float = 0.25  # Art. 239(3) floor

# Art. 239(3) derived values (for reference; assertions belong in tests)
GA_MISMATCH: float = (
    LOAN_EAD
    * (GUAR_MM_RESIDUAL_YEARS - _MATURITY_FLOOR)
    / (LOAN_RESIDUAL_MATURITY_YEARS - _MATURITY_FLOOR)
)  # = 473,684.2105263158
GA_UNGUARANTEED: float = LOAN_EAD - GA_MISMATCH  # = 526,315.7894736842

# CQS-to-rating mapping (S&P scale, representative mid-band)
_CQS_RATING_VALUE: dict[int, str] = {
    1: "AA",  # CQS 1: AAA to AA-  → use AA
    4: "BB",  # CQS 4: BB+ to BB-  → use BB
}

RATING_AGENCY = "S&P"
RATING_DATE = date(2026, 1, 2)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.109 counterparty row (borrower or guarantor)."""

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
    """P1.109 loan: GBP 1,000,000 drawn, 5-year maturity."""

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
    """P1.109 external ECAI rating: S&P scale, pd=None, model_id=None."""

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
    P1.109 guarantee row.

    Includes ``original_maturity_years`` — the field added to GUARANTEE_SCHEMA by P1.124
    and consumed by the Art. 239(3) maturity mismatch logic.
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


def create_p1109_counterparties() -> pl.DataFrame:
    """
    Return two P1.109 counterparties (borrower + guarantor) as a DataFrame.

    CP_BORROWER_P1109: corporate, GB, cqs=4 — 100% SA risk weight.
    CP_GUARANTOR_P1109: institution, GB, cqs=1 — 20% SA risk weight.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.109 Borrower Corporate GB CQS4",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.109 Guarantor Institution GB CQS1",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1109_loan() -> pl.DataFrame:
    """
    Return one P1.109 loan as a DataFrame.

    LOAN_001_P1109: GBP 1,000,000, value_date=2026-01-01, maturity_date=2031-01-01.
    EAD = drawn_amount (interest=0) = 1,000,000.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=BORROWER_REF,
            currency="GBP",
            value_date=LOAN_VALUE_DATE,
            maturity_date=LOAN_MATURITY_DATE,
            drawn_amount=LOAN_DRAWN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1109_ratings() -> pl.DataFrame:
    """
    Return two P1.109 external ratings (one per counterparty) as a DataFrame.

    Borrower  (CP_BORROWER_P1109):   CQS 4 / S&P BB  → 100% SA corporate RW.
    Guarantor (CP_GUARANTOR_P1109):  CQS 1 / S&P AA  → 20% SA institution RW.
    """
    rows = [
        _Rating(
            rating_reference="RTG-P1109-BORROWER",
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
            rating_reference="RTG-P1109-GUARANTOR",
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


def create_p1109_guarantees() -> pl.DataFrame:
    """
    Return two P1.109 guarantee rows as a DataFrame.

    GUAR_FULL_P1109: maturity_date=2031-01-01, original_maturity_years=5.0
        Full-tenor guarantee — t == T, no Art. 239(3) adjustment.
        GA = 1,000,000, RWA = 200,000 (guarantor 20%).

    GUAR_MM_P1109: maturity_date=2028-07-01, original_maturity_years=2.5
        Maturity-mismatched guarantee — t=2.5y < T=5.0y.
        Art. 239(3): GA = 1,000,000 × (2.5−0.25)/(5.0−0.25) = 473,684.2105263158
        Total RWA = 473,684.21 × 0.20 + 526,315.79 × 1.00 = 621,052.6315789474
    """
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
            guarantee_reference=GUAR_FULL_REF,
            guarantee_type="guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUAR_FULL_MATURITY,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            original_maturity_years=GUAR_FULL_ORIGINAL_MATURITY_YEARS,
        ),
        _Guarantee(
            guarantee_reference=GUAR_MM_REF,
            guarantee_type="guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUAR_MM_MATURITY,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            original_maturity_years=GUAR_MM_ORIGINAL_MATURITY_YEARS,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=guarantee_schema_plus)


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1109_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.109 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the data/ subdirectory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1109_counterparties()),
        ("loan", create_p1109_loan()),
        ("rating", create_p1109_ratings()),
        ("guarantee", create_p1109_guarantees()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.109 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 237/238/239(3) maturity mismatch on unfunded protection")
    print(f"  Borrower:  {BORROWER_REF} (corporate, CQS {BORROWER_CQS}, 100% RW)")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS}, 20% RW)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print()
    print(f"  {GUAR_FULL_REF}: maturity=2031-01-01, original_maturity_years=5.0")
    print("    t == T → no mismatch adjustment → GA = 1,000,000 → RWA = 200,000")
    print()
    print(f"  {GUAR_MM_REF}: maturity=2028-07-01, original_maturity_years=2.5")
    print("    t=2.5y < T=5.0y → Art. 239(3) applies")
    print(f"    GA = 1,000,000 × (2.5−0.25)/(5.0−0.25) = {GA_MISMATCH:.10f}")
    print(f"    unguaranteed = {GA_UNGUARANTEED:.10f}")
    print(f"    total RWA = {GA_MISMATCH * 0.20 + GA_UNGUARANTEED * 1.00:.10f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1109_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
