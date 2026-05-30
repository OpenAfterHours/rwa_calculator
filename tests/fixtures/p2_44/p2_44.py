"""
Generate P2.44 fixtures: SA-SL inferred-rating fallback suppression.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/sl.py)

Scenario design (P2.44 — Basel 3.1 SA specialised-lending Art.122B(1)/(2)(a)):

    An object_finance SL exposure carries a single external rating that is
    inferred (rating_is_inferred=True, rating_is_issue_specific=False).

    Art. 139(2B) disapplies the Art. 139(2)/(2A) inferred-rating fallbacks for
    the Art. 122B(1) SA-SL routing path.  Because the only available rating is
    inferred, the engine MUST treat the exposure as unrated and apply
    Art. 122B(2)(a) object-finance 100% risk weight — NOT the 75% CQS-3 rated
    corporate weight that Art. 122(2) Table 6 would otherwise yield.

    Expected outputs:
        risk_weight = 1.00 (100%, Art. 122B(2)(a) unrated object-finance)
        ead         = 1,000,000 GBP
        rwa         = 1,000,000 GBP
        exposure_class_sa = CORPORATE (SA sub-type for SL)
        sl_type     = "object_finance" (carried through audit trail)

    Anti-assertion: risk_weight != 0.75 (CQS-3 corporate B3.1 = 75%, which
    would be the result if the inferred rating were incorrectly used).

    Scalar source: B31_SA_SL_RISK_WEIGHTS["object_finance"] = 1.00
    (data/tables/b31_risk_weights.py:274).

Two new Boolean columns on RATINGS_SCHEMA are added to the ratings parquet:
    - rating_is_issue_specific (default True): False here — the rating is
      counterparty-wide, not issue-specific.
    - rating_is_inferred (default False): True here — the rating is inferred
      from a related entity rather than directly assigned.

These columns are not yet in RATINGS_SCHEMA in data/schemas.py at this stage
(engine-implementer will add them in a later wave). The fixture pre-populates
them so the parquet is ready; the existing schema columns are written first
via dtypes_of(RATINGS_SCHEMA), and the two new columns are appended
via with_columns.

Counterparty:
    CP_P244 : specialised_lending, GB, GBP — routes to SA CORPORATE with
              sl_type metadata.

SL metadata:
    CP_P244 : sl_type=object_finance, is_hvcre=False, project_phase=null.

Exposure (on-balance loan):
    EXP_P244: GBP 1,000,000 drawn, senior, provisions=0.

Rating:
    RT_P244 : external, AgencyA, CQS 3, rating_is_issue_specific=False,
              rating_is_inferred=True, is_short_term=False.

References:
    - PRA PS1/26 Art. 122B(1): SA routing for specialised-lending sub-classes.
    - PRA PS1/26 Art. 122B(2)(a): unrated object-finance risk weight = 100%.
    - PRA PS1/26 Art. 139(2B): disapplies inferred-rating fallbacks for
      Art. 122B(1) SA-SL routing.
    - PRA PS1/26 Art. 139(2)/(2A): inferred-rating fallbacks (disapplied here).
    - data/tables/b31_risk_weights.py:274 B31_SA_SL_RISK_WEIGHTS.

Usage:
    uv run python tests/fixtures/p2_44/p2_44.py
    uv run python tests/fixtures/p2_44/p2_44.py --data-dir /path/to/output
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
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_P244"
EXPOSURE_REF: str = "EXP_P244"
FACILITY_REF: str = "FAC_P244"
RATING_REF: str = "RT_P244"

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2032, 1, 1)
RATING_DATE: date = date(2027, 1, 1)

# Loan economics
DRAWN_AMOUNT: float = 1_000_000.0
PROVISIONS: float = 0.0

# Rating inputs (load-bearing)
RATING_CQS: int = 3
RATING_IS_ISSUE_SPECIFIC: bool = False  # counterparty-wide, not issue-specific
RATING_IS_INFERRED: bool = True  # inferred rating — Art. 139(2B) suppresses fallback

# Expected outputs (test-writer anchors)
EXPECTED_RISK_WEIGHT: float = 1.00  # Art. 122B(2)(a) unrated object-finance
EXPECTED_EAD: float = 1_000_000.0
EXPECTED_RWA: float = 1_000_000.0
EXPECTED_EXPOSURE_CLASS_SA: str = "CORPORATE"
EXPECTED_SL_TYPE: str = "object_finance"

# Anti-assertion: CQS-3 corporate Basel 3.1 rated risk weight (must NOT be applied)
ANTI_EXPECTED_RISK_WEIGHT: float = 0.75  # Art. 122(2) Table 6 CQS-3 — incorrect path


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.44 counterparty row (SL entity)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Facility:
    """P2.44 parent facility."""

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
        }


@dataclass(frozen=True)
class _Loan:
    """P2.44 on-balance loan row."""

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
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p244_counterparty() -> pl.DataFrame:
    """
    Return the P2.44 SL counterparty as a DataFrame.

    CP_P244: entity_type="specialised_lending" — routes to SA CORPORATE exposure
    class via entity_class_mapping.py. Country GB, currency GBP.
    apply_fi_scalar=False: non-FSE, no FI scalar.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P2.44 Object Finance SL SPV",
        entity_type="specialised_lending",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p244_sl_metadata() -> pl.DataFrame:
    """
    Return the P2.44 specialised lending metadata row.

    CP_P244: sl_type="object_finance", is_hvcre=False, project_phase=null.
    slotting_category is null — this scenario uses SA routing (Art. 122B),
    not IRB slotting (Art. 153(5)). The sl_type is the load-bearing field
    for the Art. 122B(2)(a) 100% unrated risk weight.
    """
    row = {
        "counterparty_reference": COUNTERPARTY_REF,
        "sl_type": "object_finance",
        "is_hvcre": False,
    }
    return pl.DataFrame([row], schema=dtypes_of(SPECIALISED_LENDING_SCHEMA))


def create_p244_facility() -> pl.DataFrame:
    """
    Return the P2.44 parent facility as a DataFrame.

    FAC_P244: senior, GBP 1,000,000 limit. Provides the parent node in the
    hierarchy resolver for the loan EXP_P244.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
        product_type="TERM_LOAN",
        book_code="SL_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        limit=DRAWN_AMOUNT,
        committed=True,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p244_loan() -> pl.DataFrame:
    """
    Return the P2.44 on-balance loan as a DataFrame.

    EXP_P244: GBP 1,000,000 drawn, senior, no provisions. This is a plain
    on-balance sheet term loan to the SL SPV. EAD = drawn_amount = 1,000,000.
    provisions=0.0 (no IFRS 9 stage adjustment needed).
    """
    row = _Loan(
        loan_reference=EXPOSURE_REF,
        product_type="TERM_LOAN",
        book_code="SL_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        seniority="senior",
        is_payroll_loan=False,
        is_buy_to_let=False,
        is_under_construction=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p244_rating() -> pl.DataFrame:
    """
    Return the P2.44 external rating as a DataFrame.

    RT_P244: external, AgencyA, CQS 3, rating_is_issue_specific=False,
    rating_is_inferred=True.

    The two new Boolean columns are not yet in RATINGS_SCHEMA (engine-implementer
    will add them in the next wave). They are appended here via with_columns so
    the parquet file is ready for the engine to consume when the schema is extended.

    Load-bearing values:
        rating_is_inferred=True: Art. 139(2B) triggers — inferred rating is
            suppressed for the Art. 122B(1) SA-SL routing path.
        rating_is_issue_specific=False: counterparty-wide (long-term) rating.
        cqs=3: if the rating were NOT suppressed, Art. 122(2) Table 6 would
            yield 75% (CQS-3 corporate Basel 3.1). The anti-assertion checks
            the engine does NOT use this path.
    """
    base_dict = {
        "rating_reference": RATING_REF,
        "counterparty_reference": COUNTERPARTY_REF,
        "rating_type": "external",
        "rating_agency": "AgencyA",
        "rating_value": "BBB",
        "cqs": RATING_CQS,
        "pd": None,
        "rating_date": RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    df = pl.DataFrame([base_dict], schema=dtypes_of(RATINGS_SCHEMA))
    # Append the two new Boolean columns that will be added to RATINGS_SCHEMA
    # in the engine-implementer wave. Default values per schema proposal:
    #   rating_is_issue_specific default=True → False here (counterparty-wide)
    #   rating_is_inferred       default=False → True here (inferred rating)
    return df.with_columns(
        pl.lit(RATING_IS_ISSUE_SPECIFIC).alias("rating_is_issue_specific"),
        pl.lit(RATING_IS_INFERRED).alias("rating_is_inferred"),
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p244_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.44 parquet files and return a mapping of name to path.

    Files produced:
        counterparty.parquet    — 1 row  (CP_P244, specialised_lending, GB)
        sl_metadata.parquet     — 1 row  (CP_P244, object_finance)
        facility.parquet        — 1 row  (FAC_P244, senior, GBP 1m)
        loan.parquet            — 1 row  (EXP_P244, drawn=1m, senior)
        rating.parquet          — 1 row  (RT_P244, CQS-3, inferred=True)

    The rating parquet includes two extra Boolean columns not yet in
    RATINGS_SCHEMA: rating_is_issue_specific=False, rating_is_inferred=True.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_44/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p244_counterparty()),
        ("sl_metadata", create_p244_sl_metadata()),
        ("facility", create_p244_facility()),
        ("loan", create_p244_loan()),
        ("rating", create_p244_rating()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.44 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: SA-SL inferred-rating fallback suppression Art. 139(2B)")
    print(f"  Counterparty: {COUNTERPARTY_REF}  entity_type=specialised_lending  GB")
    print("  SL metadata:  sl_type=object_finance  is_hvcre=False")
    print(f"  Loan:         {EXPOSURE_REF}  GBP {DRAWN_AMOUNT:,.0f}  senior  provisions=0")
    print(f"  Rating:       {RATING_REF}  AgencyA  CQS {RATING_CQS}")
    print(f"                rating_is_inferred={RATING_IS_INFERRED}")
    print(f"                rating_is_issue_specific={RATING_IS_ISSUE_SPECIFIC}")
    print()
    print("  Expected outputs (Art. 122B(2)(a) unrated object-finance path):")
    print(f"    risk_weight = {EXPECTED_RISK_WEIGHT:.2f}  (100% — inferred rating suppressed)")
    print(f"    ead         = {EXPECTED_EAD:,.2f}")
    print(f"    rwa         = {EXPECTED_RWA:,.2f}")
    print(f"  Anti-assertion: risk_weight != {ANTI_EXPECTED_RISK_WEIGHT:.2f} (CQS-3 corporate 75%)")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p244_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
