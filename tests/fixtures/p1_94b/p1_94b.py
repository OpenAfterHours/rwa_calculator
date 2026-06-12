"""
Generate P1.94b fixtures: hedge_coverage_ratio gate on Art. 123B(2) currency-mismatch multiplier.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/currency_mismatch.py)

Key responsibilities:
- Produce one counterparty (CP_P194B): natural person, GB, borrower_income_currency=GBP.
- Produce one loan row (P194B_PARTIAL_HEDGE): EUR-denominated retail loan with
  is_hedged=False and hedge_coverage_ratio=0.85 (below the 0.90 threshold).
- hedge_coverage_ratio is a NEW column (pl.Float64) not yet in production LOAN_SCHEMA.
  The builder appends it defensively after the schema cast, so the column survives
  the round-trip even before the engine-implementer adds it to LOAN_SCHEMA in Wave 4.

Scenario design:

    Arm (P194B_PARTIAL_HEDGE):
        Counterparty: natural person, GB, borrower_income_currency=GBP
        Loan: EUR 100,000, book_code=RETAIL_LENDING, term_loan
        currency=EUR vs. borrower_income_currency=GBP → currency mismatch present
        is_hedged=False → hedge gate is open (multiplier not suppressed by full hedge)
        hedge_coverage_ratio=0.85 → below the 0.90 Art. 123B(2) threshold
            → Art. 123B multiplier fires: 1.5 × 75% = 112.5%

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Art. 123B(2) hedge-coverage threshold:
        A partial hedge qualifies as a "hedge" (suppresses multiplier) ONLY when
        hedge_coverage_ratio >= 0.90 (PRA PS1/26 Art. 123B(2)).
        0.85 < 0.90 → partial hedge is insufficient → multiplier fires.

    Base retail SA risk weight (Art. 123(1), non-mortgage, non-defaulted):
        RW_base = 75%

    Art. 123B multiplier applies:
        RW = 75% × 1.50 = 112.5%

    EAD = 100,000
    RWA = 100,000 × 1.125 = 112,500.00

    Expected scalar assertions:
        risk_weight                          = 1.125
        rwa                                  = 112,500.00
        currency_mismatch_multiplier_applied = True

Regulatory references:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5x currency-mismatch multiplier for retail
      exposures where loan currency != borrower income currency.
    - PRA PS1/26 Art. 123B(2): hedge must cover >= 90% of the notional to
      qualify as a full hedge that suppresses the multiplier.
    - BCBS CRE20.89-93: currency mismatch add-on for unhedged/partially-hedged
      foreign-currency retail exposures.
    - src/rwa_calc/data/schemas.py: LOAN_SCHEMA (hedge_coverage_ratio will be
      added by engine-implementer in Wave 4), COUNTERPARTY_SCHEMA.
    - tests/fixtures/p1_94a/p1_94a.py: sibling scenario for is_hedged gate.
    - tests/fixtures/single_exposure.py: calculate_single_sa_exposure helper.

Usage:
    uv run python tests/fixtures/p1_94b/p1_94b.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_P194B"
LOAN_REF: str = "P194B_PARTIAL_HEDGE"

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2032, 1, 4)

DRAWN_AMOUNT: float = 100_000.0

# ---------------------------------------------------------------------------
# Regulatory scalars (single source of truth for test-writer assertions)
# ---------------------------------------------------------------------------

#: Art. 123B(2) hedge-coverage threshold — must be >= 0.90 to suppress multiplier
HEDGE_COVERAGE_THRESHOLD: float = 0.90

#: Fixture value: below threshold → multiplier fires
HEDGE_COVERAGE_RATIO: float = 0.85

#: Base SA risk weight for retail non-mortgage (PRA PS1/26 Art. 123(1))
SA_RETAIL_BASE_RW: float = 0.75

#: Art. 123B currency-mismatch multiplier (PRA PS1/26 Art. 123B)
CURRENCY_MISMATCH_MULTIPLIER: float = 1.50

#: Expected risk weight: multiplier fires because hedge_coverage_ratio < 0.90
RW_PARTIAL_HEDGE: float = SA_RETAIL_BASE_RW * CURRENCY_MISMATCH_MULTIPLIER  # 1.125

#: Expected RWA
RWA_PARTIAL_HEDGE: float = DRAWN_AMOUNT * RW_PARTIAL_HEDGE  # 112,500.00


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.94b counterparty: natural person, GB, borrower income in GBP.

    entity_type=natural_person → classifier routes to retail_other exposure class
    (non-mortgage retail, no LTV supplied).
    borrower_income_currency=GBP: triggers Art. 123B mismatch check for an EUR loan.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool
    borrower_income_currency: str

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_natural_person": self.is_natural_person,
            "borrower_income_currency": self.borrower_income_currency,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.94b loan row: EUR-denominated retail loan, is_hedged=False, hedge_coverage_ratio=0.85.

    currency=EUR vs. counterparty borrower_income_currency=GBP → currency mismatch.
    is_hedged=False: the is_hedged flag does not suppress the multiplier.
    hedge_coverage_ratio=0.85: below 0.90 threshold → Art. 123B multiplier fires.
    NOTE: hedge_coverage_ratio is not yet in production LOAN_SCHEMA.  It is
    appended as a pl.Float64 column via with_columns() in create_p194b_loans().
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
    lgd: float
    beel: float
    seniority: str
    is_hedged: bool
    hedge_coverage_ratio: float  # NOTE: new column — not yet in LOAN_SCHEMA (Wave 4)

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
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
            "is_hedged": self.is_hedged,
            "hedge_coverage_ratio": self.hedge_coverage_ratio,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p194b_counterparty() -> pl.DataFrame:
    """
    Return the P1.94b counterparty (natural person, GB, income GBP) as a DataFrame.

    entity_type=natural_person → classifier produces exposure_class=retail_other.
    borrower_income_currency=GBP: the EUR-denominated loan triggers Art. 123B
    eligibility check.
    """
    # Art. 123A(1)(b)(iii): the portfolio-management attestation must be in place
    # for a natural-person loan to qualify as retail. The classifier enforces this
    # per-row, so the fixture sets is_managed_as_retail=True to satisfy the
    # retail-qualification precondition for Art. 123B(2) hedge-coverage testing.
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P194B Test Individual",
        entity_type="natural_person",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=True,
        is_natural_person=True,
        borrower_income_currency="GBP",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p194b_loans() -> pl.DataFrame:
    """
    Return the P1.94b loan row (partially hedged) as a DataFrame.

    The loan has is_hedged=False and hedge_coverage_ratio=0.85 (below the 0.90
    Art. 123B(2) threshold).

    Build pattern:
    1. Construct the row dict including is_hedged and hedge_coverage_ratio.
    2. Build a DataFrame from the known LOAN_SCHEMA columns only (excluding both
       new columns) using dtypes_of(LOAN_SCHEMA) for correct dtype coercion.
    3. Append is_hedged as pl.Boolean via with_columns() — same as p1_94a/p1_94f.
    4. Append hedge_coverage_ratio as pl.Float64 via with_columns() — new column.

    This pattern ensures all existing schema columns are correctly typed, and the
    two new columns are present with explicit dtypes regardless of whether
    LOAN_SCHEMA has been amended yet by the engine-implementer.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="term_loan",
        book_code="RETAIL_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="EUR",
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        lgd=0.45,
        beel=0.0,
        seniority="senior",
        is_hedged=False,
        hedge_coverage_ratio=HEDGE_COVERAGE_RATIO,
    )

    rows = [row.to_dict()]

    # Step 1: Strip new columns before building with the declared schema.
    loan_schema_cols = dtypes_of(LOAN_SCHEMA)
    rows_base = [
        {k: v for k, v in r.items() if k not in ("is_hedged", "hedge_coverage_ratio")} for r in rows
    ]
    df = pl.DataFrame(rows_base, schema=loan_schema_cols)

    # Step 2: Set is_hedged explicitly from row data as pl.Boolean.
    # is_hedged IS declared in LOAN_SCHEMA (added in the p1_94a wave), so it already
    # exists as a null-filled column after the schema build above.  We must overwrite
    # it with the actual value from the row dict, not leave it null.
    is_hedged_values = [r["is_hedged"] for r in rows]
    df = df.with_columns(pl.Series("is_hedged", is_hedged_values, dtype=pl.Boolean))

    # Step 3: Append hedge_coverage_ratio as pl.Float64 — new column, not yet in
    # production LOAN_SCHEMA.  The engine-implementer will add it in Wave 4; the
    # parquet is forward-compatible from today.
    hedge_ratio_values = [r["hedge_coverage_ratio"] for r in rows]
    df = df.with_columns(pl.Series("hedge_coverage_ratio", hedge_ratio_values, dtype=pl.Float64))

    return df


# ---------------------------------------------------------------------------
# Empty helpers (no collateral, guarantees, etc. in this scenario)
# ---------------------------------------------------------------------------


def create_p194b_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p194b_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p194b_empty_collateral() -> pl.DataFrame:
    """Return an empty collateral DataFrame (no CRM in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p194b_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p194b_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p194b_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame (no external ratings in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p194b_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------


def load_p1_94b_bundle(*, fixtures_dir: Path | None = None) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P1.94b scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module.  The optional ``fixtures_dir`` argument is accepted
    for interface symmetry with other bundle builders; if supplied and the
    parquet files exist, they are loaded from disk.  Otherwise, the in-memory
    DataFrames are used.

    Returns:
        RawDataBundle with:
        - 1 counterparty (CP_P194B, natural person, GB, income GBP)
        - 1 loan (P194B_PARTIAL_HEDGE, EUR, is_hedged=False,
          hedge_coverage_ratio=0.85)
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Optional path to the fixtures data directory.  Unused
            unless parquet files have been written; accepted for interface
            compatibility with other bundle builders.
    """
    if fixtures_dir is not None:
        cp_path = fixtures_dir / "counterparty.parquet"
        loans_path = fixtures_dir / "loans.parquet"
        if cp_path.exists() and loans_path.exists():
            counterparties_lf = pl.read_parquet(cp_path).lazy()
            loans_lf = pl.read_parquet(loans_path).lazy()
        else:
            counterparties_lf = create_p194b_counterparty().lazy()
            loans_lf = create_p194b_loans().lazy()
    else:
        counterparties_lf = create_p194b_counterparty().lazy()
        loans_lf = create_p194b_loans().lazy()

    return make_raw_bundle(
        facilities=create_p194b_empty_facilities().lazy(),
        loans=loans_lf,
        counterparties=counterparties_lf,
        facility_mappings=pl.DataFrame(
            schema={"parent_facility_reference": pl.String, "child_reference": pl.String}
        ).lazy(),
        lending_mappings=pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy(),
        org_mappings=None,
        contingents=create_p194b_empty_contingents().lazy(),
        collateral=create_p194b_empty_collateral().lazy(),
        guarantees=create_p194b_empty_guarantees().lazy(),
        provisions=create_p194b_empty_provisions().lazy(),
        ratings=create_p194b_empty_ratings().lazy(),
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# Alias for interface compatibility with other bundle builders
def build_p1_94b_bundle(*, fixtures_dir: Path | None = None) -> RawDataBundle:
    """Alias for load_p1_94b_bundle — accepted for interface symmetry."""
    return load_p1_94b_bundle(fixtures_dir=fixtures_dir)


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p194b_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.94b parquet files and return a mapping of name -> path.

    Two parquet files are written:
    - counterparty.parquet  (1 row: CP_P194B)
    - loans.parquet         (1 row: P194B_PARTIAL_HEDGE)

    The loans parquet includes:
      - is_hedged column (pl.Boolean) — as in p1_94a/p1_94f
      - hedge_coverage_ratio column (pl.Float64) — NEW column for this scenario

    Both extra columns are forward-compatible: the engine-implementer will amend
    LOAN_SCHEMA in Wave 4 to declare hedge_coverage_ratio officially.

    Args:
        output_dir: Target directory. Defaults to the data/ subdirectory
            adjacent to this module file.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p194b_counterparty()),
        ("loans", create_p194b_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.94b fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<20} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print(
        "Scenario: P1.94b — hedge_coverage_ratio=0.85 below 0.90 threshold "
        "→ Art. 123B multiplier fires"
    )
    print()
    print(f"  Art. 123B(2) hedge coverage threshold: {HEDGE_COVERAGE_THRESHOLD:.2f}")
    print(f"  Fixture hedge_coverage_ratio:          {HEDGE_COVERAGE_RATIO:.2f}  (<threshold)")
    print(f"  Base retail SA RW (Art. 123(1)):       {SA_RETAIL_BASE_RW:.0%}")
    print(f"  Art. 123B multiplier:                  {CURRENCY_MISMATCH_MULTIPLIER:.2f}x")
    print()
    print(
        f"  Arm (P194B_PARTIAL_HEDGE, is_hedged=False, hedge_coverage_ratio={HEDGE_COVERAGE_RATIO}):"
    )
    print(f"    risk_weight                          = {RW_PARTIAL_HEDGE:.4f}")
    print(f"    rwa                                  = {RWA_PARTIAL_HEDGE:,.2f}")
    print("    currency_mismatch_multiplier_applied = True")
    print()

    # Verify new columns in loans parquet
    loans_df = pl.read_parquet(saved["loans"])
    for col_name, _expected_dtype in [
        ("is_hedged", pl.Boolean),
        ("hedge_coverage_ratio", pl.Float64),
    ]:
        if col_name in loans_df.columns:
            actual_dtype = loans_df.schema[col_name]
            val = loans_df[col_name][0]
            print(f"  {col_name} dtype: {actual_dtype}  value: {val}")
        else:
            print(f"  WARNING: {col_name} column missing from loans parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p194b_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
