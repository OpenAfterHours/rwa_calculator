"""
Generate P1.124 fixtures: CRR Art. 237(2)(a) guarantee maturity ineligibility.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Key responsibilities:
- Produce two counterparty rows:
    CP_BORROWER: corporate, GB, cqs=4 (external rating, 100% SA RW)
    CP_GUARANTOR: institution, GB, cqs=1 (external rating, 20% SA RW)
- Produce one loan row:
    LOAN_001: GBP 1,000,000, value_date=2026-01-01, maturity_date=2031-01-01 (5y residual)
- Produce two guarantee rows:
    GUAR_SHORT:    maturity_date=2026-10-01 (9m residual), original_maturity_years=0.75
                   FAILING eligibility: residual maturity < 1 year (Art. 237(2)(a))
    GUAR_ELIGIBLE: maturity_date=2028-01-01 (2y residual), original_maturity_years=2.0
                   PASSING eligibility: residual maturity >= 1 year
- Produce two external rating rows: one per counterparty.

Defect under test (pre-fix):
    The CRM processor does not enforce CRR Art. 237(2)(a), which requires that the
    residual maturity of the credit protection is at least 1 year. GUAR_SHORT has a
    9-month residual maturity, making it ineligible regardless of the guarantor's
    creditworthiness.  Without the fix, GUAR_SHORT is applied and the borrower's RW
    is substituted by the guarantor's RW (20% instead of 100%) — understating RWA.

Post-fix assertion (primary):
    LOAN_001 + GUAR_SHORT  → guarantee is INELIGIBLE → RW = 100% (borrower CQS 4)
                               RWA = 1,000,000 × 100% = 1,000,000
    LOAN_001 + GUAR_ELIGIBLE → guarantee is ELIGIBLE  → RW = 20%  (guarantor CQS 1)
                               RWA = 1,000,000 × 20% = 200,000

Hand-calculation (CRR, CalculationConfig.crr()):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP

    GUAR_SHORT (ineligible path):
        residual_maturity = (2026-10-01 − 2026-01-01) / 365 ≈ 0.747y < 1.0y
        Art. 237(2)(a): residual maturity < 1 year → protection ineligible
        RW = CORP_UK_UNRATED fallback for CQS 4 = 100%
        RWA = 1,000,000 × 1.00 = 1,000,000

    GUAR_ELIGIBLE (eligible path):
        residual_maturity = (2028-01-01 − 2026-01-01) / 365 ≈ 2.0y >= 1.0y
        Art. 237(2)(a): satisfied
        Substitution: RW of guarantor (INST_GB CQS 1) = 20%
        RWA = 1,000,000 × 0.20 = 200,000

    Maturity mismatch adjustment (Art. 233):
        GUAR_ELIGIBLE: t=2y, T=5y → Pa = (t−0.25)/(T−0.25) = 1.75/4.75 ≈ 0.3684
        Adjusted coverage = 1,000,000 × 0.3684 = 368,400
        Blended RWA = (368,400 × 20%) + (631,600 × 100%) = 73,680 + 631,600 = 705,280
        (Exact maturity mismatch is for engine-implementer; the test-writer pins the
         pre/post eligibility boundary, not the maturity-adjusted value.)

    NOTE: The primary test assertion is the INELIGIBILITY gate — GUAR_SHORT produces
    no CRM benefit at all. The maturity-mismatch discount on GUAR_ELIGIBLE is a
    secondary concern; the engine-implementer decides whether to test it separately.

Schema dependency:
    GUARANTEE_SCHEMA in src/rwa_calc/data/schemas.py does NOT yet include
    ``original_maturity_years`` (ColumnSpec(pl.Float64, required=False)).
    This field is written into the parquet at column level; Polars accepts unknown
    columns without error.  The engine-implementer must add the field to
    GUARANTEE_SCHEMA before the engine can read it through ensure_columns.
    See P1.124 in IMPLEMENTATION_PLAN.md for the schema change item.

References:
    - CRR Art. 237(2)(a): minimum residual maturity of protection >= 1 year
    - CRR Art. 233: maturity mismatch adjustment for partially-matched protection
    - CRR Art. 207: eligibility conditions for unfunded credit protection
    - src/rwa_calc/data/schemas.py: GUARANTEE_SCHEMA (engine-implementer must add field)
    - src/rwa_calc/engine/crm/: CRM processor guarantee eligibility gate

Usage:
    uv run python tests/fixtures/p1_124/p1_124.py
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
BORROWER_REF = "CP_BORROWER_P1124"
GUARANTOR_REF = "CP_GUARANTOR_P1124"

# Loan reference
LOAN_REF = "LOAN_001_P1124"

# Guarantee references
GUAR_SHORT_REF = "GUAR_SHORT_P1124"   # ineligible: 9m residual < 1y
GUAR_ELIGIBLE_REF = "GUAR_ELIGIBLE_P1124"  # eligible: 2y residual >= 1y

# Loan dates
LOAN_VALUE_DATE = date(2026, 1, 1)
LOAN_MATURITY_DATE = date(2031, 1, 1)  # 5y residual

# Guarantee maturity dates
# Short: 273 days / 365 ≈ 0.747y < 1.0y → Art. 237(2)(a) ineligible
GUAR_SHORT_MATURITY = date(2026, 10, 1)
# Eligible: 2y residual ≥ 1.0y → Art. 237(2)(a) satisfied
GUAR_ELIGIBLE_MATURITY = date(2028, 1, 1)

# Original maturity in fractional years (written into parquet for engine use)
GUAR_SHORT_ORIGINAL_MATURITY_YEARS: float = 0.75
GUAR_ELIGIBLE_ORIGINAL_MATURITY_YEARS: float = 2.0

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_INTEREST = 0.0
LOAN_EAD = LOAN_DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Risk weights (CRR, external rating)
BORROWER_CQS = 4      # corporate CQS 4 → 100% RW
GUARANTOR_CQS = 1     # institution CQS 1 → 20% RW

# Expected outputs
EXPECTED_RW_NO_CRM: float = 1.00    # borrower CQS 4 corporate → 100%
EXPECTED_RW_WITH_CRM: float = 0.20  # guarantor CQS 1 institution → 20%

EXPECTED_RWA_INELIGIBLE: float = LOAN_EAD * EXPECTED_RW_NO_CRM   # 1,000,000
EXPECTED_RWA_ELIGIBLE: float = LOAN_EAD * EXPECTED_RW_WITH_CRM   # 200,000

# CQS-to-rating mapping (S&P scale, representative mid-band)
_CQS_RATING_VALUE: dict[int, str] = {
    1: "AA",   # CQS 1: AAA to AA-  → use AA
    4: "BB",   # CQS 4: BB+ to BB-  → use BB
}

RATING_AGENCY = "S&P"
RATING_DATE = date(2026, 1, 2)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.124 counterparty row (borrower or guarantor)."""

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
    """P1.124 loan: GBP 1,000,000 drawn, 5-year maturity."""

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
    """P1.124 external ECAI rating: S&P scale, pd=None, model_id=None."""

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
    P1.124 guarantee row.

    Includes ``original_maturity_years`` — a field not yet in GUARANTEE_SCHEMA.
    The parquet writer accepts extra columns without error; the engine-implementer
    must add the field to GUARANTEE_SCHEMA before the calculator can consume it.
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


def create_p1124_counterparties() -> pl.DataFrame:
    """
    Return two P1.124 counterparties (borrower + guarantor) as a DataFrame.

    CP_BORROWER_P1124: corporate, GB, cqs=4 — 100% SA risk weight.
    CP_GUARANTOR_P1124: institution, GB, cqs=1 — 20% SA risk weight.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.124 Borrower Corporate GB CQS4",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.124 Guarantor Institution GB CQS1",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1124_loan() -> pl.DataFrame:
    """
    Return one P1.124 loan as a DataFrame.

    LOAN_001_P1124: GBP 1,000,000, value_date=2026-01-01, maturity_date=2031-01-01.
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


def create_p1124_ratings() -> pl.DataFrame:
    """
    Return two P1.124 external ratings (one per counterparty) as a DataFrame.

    Borrower  (CP_BORROWER_P1124):   CQS 4 / S&P BB  → 100% SA corporate RW.
    Guarantor (CP_GUARANTOR_P1124):  CQS 1 / S&P AA  → 20% SA institution RW.
    """
    rows = [
        _Rating(
            rating_reference="RTG-P1124-BORROWER",
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
            rating_reference="RTG-P1124-GUARANTOR",
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


def create_p1124_guarantees() -> pl.DataFrame:
    """
    Return two P1.124 guarantee rows as a DataFrame.

    GUAR_SHORT_P1124:    maturity_date=2026-10-01, original_maturity_years=0.75
        residual ≈ 0.747y < 1.0y → Art. 237(2)(a) ineligible → no CRM benefit.

    GUAR_ELIGIBLE_P1124: maturity_date=2028-01-01, original_maturity_years=2.0
        residual = 2.0y >= 1.0y → Art. 237(2)(a) satisfied → substitution applies.

    Column ``original_maturity_years`` is written as an extra column beyond
    GUARANTEE_SCHEMA.  Polars does not validate this against the schema on write;
    the engine-implementer must add the field to GUARANTEE_SCHEMA to read it.
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
        # NEW field — not yet in GUARANTEE_SCHEMA; engine-implementer must add it.
        "original_maturity_years": pl.Float64,
    }

    rows = [
        _Guarantee(
            guarantee_reference=GUAR_SHORT_REF,
            guarantee_type="guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUAR_SHORT_MATURITY,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            original_maturity_years=GUAR_SHORT_ORIGINAL_MATURITY_YEARS,
        ),
        _Guarantee(
            guarantee_reference=GUAR_ELIGIBLE_REF,
            guarantee_type="guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUAR_ELIGIBLE_MATURITY,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            original_maturity_years=GUAR_ELIGIBLE_ORIGINAL_MATURITY_YEARS,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=guarantee_schema_plus)


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1124_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.124 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1124_counterparties()),
        ("loan", create_p1124_loan()),
        ("rating", create_p1124_ratings()),
        ("guarantee", create_p1124_guarantees()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.124 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 237(2)(a) guarantee maturity ineligibility")
    print(f"  Borrower:  {BORROWER_REF} (corporate, CQS {BORROWER_CQS}, {EXPECTED_RW_NO_CRM:.0%} RW)")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS}, {EXPECTED_RW_WITH_CRM:.0%} RW)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print()
    print("  GUAR_SHORT_P1124:    maturity=2026-10-01, original_maturity_years=0.75")
    print("    residual ≈ 0.747y < 1.0y → INELIGIBLE → RWA = 1,000,000")
    print()
    print("  GUAR_ELIGIBLE_P1124: maturity=2028-01-01, original_maturity_years=2.0")
    print("    residual = 2.0y >= 1.0y → ELIGIBLE   → RWA = 200,000 (pre-maturity-adj)")
    print()
    print("  Schema note: original_maturity_years is an extra column beyond GUARANTEE_SCHEMA.")
    print("  Engine-implementer must add ColumnSpec(pl.Float64, required=False) to GUARANTEE_SCHEMA.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1124_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
