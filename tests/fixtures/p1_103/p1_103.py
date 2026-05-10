"""
Generate P1.103 fixtures: B31 Art. 122(3) Table 6A short-term corporate ECAI risk weights.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce one counterparty row: corporate, GB, entity_type="corporate".
- Produce one facility row: term_loan, GBP, 73-day maturity (2027-01-01 to 2027-03-15).
- Produce one loan row: GBP 1,000,000 drawn, same maturity window.
- Produce one **short-term** external rating row: CQS 3, S&P "A-3", attached
  to the facility via ``scope_type='facility'`` / ``scope_id=FACILITY_REF`` with
  ``is_short_term=True``.
- No collateral, no guarantee, no provisions — clean single-factor SA test.
- Framework: CalculationConfig.basel_3_1().

Scenario rationale:
    Basel 3.1 Art. 122(3) introduces Table 6A for corporate exposures that carry a
    *dedicated short-term ECAI assessment* (analogous to Art. 120(2B) Table 4A for
    institutions). Short-term ECAI assessments are issue-specific under Basel/CRR,
    so the flag lives on the **rating row** rather than the facility row — the
    rating carries ``is_short_term=True`` together with a ``(scope_type, scope_id)``
    pair identifying the target facility.

    CQS 3 is the discriminating band:
        Table 6  (long-term, Art. 122(2)): CQS 3 = 75%
        Table 6A (short-term, Art. 122(3)): CQS 3 = 100%

    Both tables share CQS 1 = 20%, so CQS 3 is the cleanest discriminator —
    a Table 6 fallback would produce 750,000 RWA rather than the correct 1,000,000.

    The fixture exercises the override semantics: the rating row's
    ``is_short_term`` flag is what routes the SA engine to Table 6A,
    regardless of any engine-side maturity gate. Maturity is set to a
    regulatorily-qualifying 73 days here so a producer-side check
    (``original_maturity_years <= 0.25``) would also pass.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD  = drawn_amount + interest = 1,000,000 + 0.00 = 1,000,000
    RW   = Table 6A, CQS 3 = 1.00  (PRA PS1/26 Art. 122(3))
    RWA  = EAD × RW = 1,000,000 × 1.00 = 1,000,000
    K    = RWA × 0.08 = 80,000

    Contrastive (Table 6, is_short_term=False, same exposure):
        RW  = 0.75  (B31_CORPORATE_RISK_WEIGHTS CQS 3 — must NOT match)
        RWA = 750,000

References:
    - PRA PS1/26 Art. 122(2) Table 6: long-term corporate ECAI risk weights.
    - PRA PS1/26 Art. 122(3) Table 6A: short-term corporate ECAI risk weights.
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_CORPORATE_RISK_WEIGHTS (Table 6).
    - src/rwa_calc/data/schemas.py: RATINGS_SCHEMA fields ``is_short_term``,
      ``scope_type``, ``scope_id``.
    - tests/fixtures/p1_105/p1_105.py: institution analogue (Table 4A, Art. 120(2B)).
    - docs/user-guide/exposure-classes/corporate.md: Table 6A narrative.

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

# 73-day maturity window: residual = 73/365 ≈ 0.1999y ≤ 0.25y → producer-side
# Art. 122(3) gate qualifies, so it is legitimate to flag this rating row as
# short-term.
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

# Table 6 (fallback, is_short_term=False) long-term corporate CQS 3 = 0.75.
TABLE6_FALLBACK_RISK_WEIGHT: float = 0.75
TABLE6_FALLBACK_RWA: float = EAD * TABLE6_FALLBACK_RISK_WEIGHT  # 750,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.103 corporate counterparty: entity_type=corporate, country_code=GB."""

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
    """P1.103 loan: GBP 1,000,000 drawn, 73-day maturity."""

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
    P1.103 external short-term ECAI rating.

    ``is_short_term=True`` with ``scope_type='facility'`` / ``scope_id=FACILITY_REF``
    attaches the rating to one specific facility. The HierarchyResolver applies
    this rating to the drawn loan (matched via ``parent_facility_reference``),
    overriding the counterparty-level rating inheritance and routing the SA
    engine to Table 6A.
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
    is_short_term: bool
    scope_type: str | None
    scope_id: str | None

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
            "is_short_term": self.is_short_term,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1103_counterparty() -> pl.DataFrame:
    """Return one P1.103 counterparty row as a DataFrame."""
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
    """Return one P1.103 facility row as a DataFrame."""
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
    return pl.DataFrame([base_row], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1103_loan() -> pl.DataFrame:
    """Return one P1.103 loan row as a DataFrame."""
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
    """Return one P1.103 external short-term ECAI rating row as a DataFrame."""
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
        is_short_term=True,
        scope_type="facility",
        scope_id=FACILITY_REF,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1103_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all P1.103 parquet files and return a mapping of name -> path."""
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
        "          rating row: is_short_term=True, "
        f"scope_type=facility, scope_id={FACILITY_REF} → Table 6A, CQS {CQS}"
    )
    print("")
    print("  CQS  Table 6A RW  Expected RWA    Capital (8%)")
    print(
        f"   {CQS}     {EXPECTED_RISK_WEIGHT:.0%}       {EXPECTED_RWA:>12,.0f}    {EXPECTED_K:>10,.0f}"
    )
    print("")
    print("  Contrastive (Table 6, is_short_term=False):")
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
