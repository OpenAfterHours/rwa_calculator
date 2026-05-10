"""
Generate P1.103 fixtures: B31 Art. 122(3) Table 6A short-term corporate ECAI risk weights.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce one counterparty row: corporate, GB, entity_type="corporate".
- Produce one facility row: term_loan, GBP, 73-day maturity (2027-01-01 to 2027-03-15),
  has_short_term_ecai=True (signals short-term ECAI assessment → Table 6A branch).
- Produce one loan row: GBP 1,000,000 drawn, same maturity window.
- Produce one external rating row: S&P "A-3", CQS 3, pd=None.
- No collateral, no guarantee, no provisions — clean single-factor SA test.
- Framework: CalculationConfig.basel_3_1().

Scenario rationale:
    Basel 3.1 Art. 122(3) introduces Table 6A for corporate exposures that carry a
    *dedicated short-term ECAI assessment* (analogous to Art. 120(2B) Table 4A for
    institutions).  When ``has_short_term_ecai=True`` on the facility, the engine
    routes the risk-weight lookup to Table 6A instead of the standard long-term
    corporate Table 6 (Art. 122(2)).

    CQS 3 is the discriminating band:
        Table 6  (long-term, Art. 122(2)): CQS 3 = 75%
        Table 6A (short-term, Art. 122(3)): CQS 3 = 100%

    Both tables share CQS 1 = 20%, so CQS 3 is the cleanest discriminator —
    a Table 6 fallback would produce 750,000 RWA rather than the correct 1,000,000.

    The fixture exercises the minimum short-term maturity window:
        73 days = 2027-03-15 - 2027-01-01
        residual_maturity_years = 73 / 365 ≈ 0.1999 ≤ 0.25  → short-term gate fires
        has_short_term_ecai = True                            → Table 6A branch taken
        CQS 3 / Table 6A                                      → RW = 1.00

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD  = drawn_amount + interest = 1,000,000 + 0.00 = 1,000,000
    RW   = Table 6A, CQS 3 = 1.00  (PRA PS1/26 Art. 122(3))
    RWA  = EAD × RW = 1,000,000 × 1.00 = 1,000,000
    K    = RWA × 0.08 = 80,000

    Contrastive (Table 6, has_short_term_ecai=False, same exposure):
        RW  = 0.75  (B31_CORPORATE_RISK_WEIGHTS CQS 3 — must NOT match)
        RWA = 750,000

References:
    - PRA PS1/26 Art. 122(2) Table 6: long-term corporate ECAI risk weights.
    - PRA PS1/26 Art. 122(3) Table 6A: short-term corporate ECAI risk weights.
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_CORPORATE_RISK_WEIGHTS (Table 6).
    - src/rwa_calc/data/schemas.py: FACILITY_SCHEMA field ``has_short_term_ecai``.
    - tests/fixtures/p1_105/p1_105.py: institution analogue (Table 4A, Art. 120(2B)).
    - docs/user-guide/exposure-classes/corporate.md: Table 6A narrative.

Note on schema field:
    ``has_short_term_ecai`` was added to FACILITY_SCHEMA by the engine-implementer
    during P1.105.  The corporate short-term ECAI path (P1.103) reuses the same
    field — the engine routes based on both exposure class and this flag.
    The ``with_columns`` call below is idempotent if the field is already in the
    schema (no-op update of the already-typed column).

Usage:
    uv run python tests/fixtures/p1_103/p1_103.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_CORP_ST_ECAI_01"
FACILITY_REF = "FAC_CORP_ST_ECAI_01"
LOAN_REF = "LN_CORP_ST_ECAI_01"
RATING_REF = "RTG_CORP_ST_ECAI_01"

# 73-day maturity window: residual = 73/365 ≈ 0.1999y ≤ 0.25y → short-term gate fires.
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2027, 3, 15)  # 73 days from VALUE_DATE

EAD = 1_000_000.0  # GBP 1,000,000; interest=0 → EAD exact
CQS = 3

RATING_AGENCY = "S&P"
RATING_VALUE = "A-3"  # S&P short-term mid-grade rating → CQS 3
RATING_DATE = date(2027, 1, 2)

# Table 6A (Art. 122(3)) expected risk weight for CQS 3 = 1.00.
EXPECTED_RISK_WEIGHT: float = 1.00
EXPECTED_EAD: float = EAD
EXPECTED_RWA: float = EAD * EXPECTED_RISK_WEIGHT  # 1,000,000
EXPECTED_K: float = EXPECTED_RWA * 0.08  # 80,000

# Table 6 (fallback, has_short_term_ecai=False) long-term corporate CQS 3 = 0.75.
# Used by test-writer to assert the old path is NOT taken for this exposure.
TABLE6_FALLBACK_RISK_WEIGHT: float = 0.75
TABLE6_FALLBACK_RWA: float = EAD * TABLE6_FALLBACK_RISK_WEIGHT  # 750,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.103 corporate counterparty: entity_type=corporate, country_code=GB, not defaulted.

    entity_type="corporate" resolves to ExposureClass.CORPORATE.  GB country is used
    so the scenario is recognisably a domestic corporate.  No FSE scalar applies.
    """

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
    """
    P1.103 loan: GBP 1,000,000 drawn, 73-day maturity.

    residual_maturity_years = 73/365 ≈ 0.1999y ≤ 0.25 → short-term gate fires.
    interest=0 so EAD = drawn_amount exactly.
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
class _Rating:
    """
    P1.103 external short-term ECAI rating: S&P A-3, CQS 3, pd=None, model_id=None.

    "A-3" is S&P's short-term rating in the mid-grade band, mapping to CQS 3.
    External rating with pd=None drives the SA ECAI-rated path.
    is_solicited=True: solicited ratings are given precedence in ECAI mapping.
    """

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


def create_p1103_counterparty() -> pl.DataFrame:
    """
    Return one P1.103 counterparty row as a DataFrame.

    entity_type=corporate, country_code=GB, not defaulted, no FI scalar.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Acme Manufacturing PLC",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1103_facility() -> pl.DataFrame:
    """
    Return one P1.103 facility row as a DataFrame.

    Includes ``has_short_term_ecai=True``.  The column is appended after the base
    schema construction so the parquet write succeeds regardless of whether the
    engine-implementer has added ``has_short_term_ecai`` to FACILITY_SCHEMA yet.

    Once FACILITY_SCHEMA declares the field (added during P1.105), ``dtypes_of``
    already includes it and the ``with_columns`` call becomes a harmless typed update.
    """
    base_row = {
        "facility_reference": FACILITY_REF,
        "product_type": "term_loan",
        "book_code": "CORP_LENDING",
        "counterparty_reference": COUNTERPARTY_REF,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "currency": "GBP",
        "limit": EAD,
        "committed": True,
        "lgd": 0.45,
        "beel": 0.0,
        "is_revolving": False,
        "seniority": "senior",
        "risk_type": "MR",
        "is_short_term_trade_lc": False,
    }
    base_schema = dtypes_of(FACILITY_SCHEMA)
    df = pl.DataFrame([base_row], schema=base_schema)
    # Append has_short_term_ecai regardless of whether it is in FACILITY_SCHEMA yet.
    # After engine-implementer adds the field (P1.105 wave), this with_columns is a
    # no-op typed update.
    return df.with_columns(pl.lit(True).alias("has_short_term_ecai"))


def create_p1103_loan() -> pl.DataFrame:
    """
    Return one P1.103 loan row as a DataFrame.

    GBP 1,000,000 drawn, value_date=2027-01-01, maturity_date=2027-03-15 (73 days).
    73/365 ≈ 0.1999y ≤ 0.25y residual maturity → Art. 122 short-term gate fires.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=EAD,
        interest=0.0,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1103_rating() -> pl.DataFrame:
    """
    Return one P1.103 external short-term ECAI rating row as a DataFrame.

    S&P A-3, CQS 3, pd=None — drives the SA ECAI-rated corporate path.
    """
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="external",
        rating_agency=RATING_AGENCY,
        rating_value=RATING_VALUE,
        cqs=CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1103_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.103 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1103_counterparty()),
        ("facility", create_p1103_facility()),
        ("loan", create_p1103_loan()),
        ("rating", create_p1103_rating()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.103 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: B31 Art. 122(3) Table 6A — short-term ECAI corporate RW")
    print(f"          entity_type=corporate, country_code=GB, GBP {EAD:,.0f}")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (73 days)")
    print(
        f"          residual_maturity ≈ {(MATURITY_DATE - VALUE_DATE).days / 365:.4f}y"
        " ≤ 0.25y → short-term gate fires"
    )
    print(f"          has_short_term_ecai=True → Table 6A branch, CQS {CQS}")
    print("")
    print("  CQS  Table 6A RW  Expected RWA    Capital (8%)")
    print(
        f"   {CQS}     {EXPECTED_RISK_WEIGHT:.0%}       {EXPECTED_RWA:>12,.0f}    {EXPECTED_K:>10,.0f}"
    )
    print("")
    print("  Contrastive (Table 6, has_short_term_ecai=False):")
    print(
        f"   {CQS}     {TABLE6_FALLBACK_RISK_WEIGHT:.0%}       {TABLE6_FALLBACK_RWA:>12,.0f}"
        f"    {TABLE6_FALLBACK_RWA * 0.08:>10,.0f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1103_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
