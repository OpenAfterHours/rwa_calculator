"""
Generate P1.94a fixtures: is_hedged flag gates Art. 123B currency-mismatch multiplier.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/calculator.py or
    sa/currency_mismatch.py)

Key responsibilities:
- Produce one shared counterparty (CP_P194A): natural person, GB,
  borrower_income_currency=GBP.
- Produce two loan rows: P194A_HEDGED (is_hedged=True) and P194A_UNHEDGED
  (is_hedged=False), both EUR-denominated, both retail/non-mortgage.
- The is_hedged column is written as pl.Boolean in the parquet.  LOAN_SCHEMA
  does not declare is_hedged yet — the engine-implementer will add it in Wave 4.
  The builder applies a defensive cast so the column survives a schema round-trip.

Scenario design:

    Both arms are identical SA retail exposures except for the is_hedged flag:
        - Counterparty: natural person, country_code=GB, borrower_income_currency=GBP
        - Exposure currency: EUR (mismatch against GBP income → Art. 123B applies to
          Arm B)
        - EAD: EUR 100,000
        - Exposure class: retail_other (non-mortgage retail)
        - Framework: Basel 3.1 (CalculationConfig.basel_3_1())

    Arm A — P194A_HEDGED (is_hedged=True):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=True  → Art. 123B currency-mismatch multiplier suppressed
        Expected: risk_weight=0.75, rwa=75,000, currency_mismatch_multiplier_applied=False

    Arm B — P194A_UNHEDGED (is_hedged=False):
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        is_hedged=False AND currency != borrower_income_currency
            → Art. 123B multiplier fires: 1.5 × 75% = 112.5%
        Expected: risk_weight=1.125, rwa=112,500, currency_mismatch_multiplier_applied=True

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Base retail SA risk weight (Art. 123(1), non-mortgage, non-defaulted):
        RW_base = 75%

    Art. 123B currency-mismatch multiplier (PRA PS1/26 Art. 123B):
        Trigger conditions (ALL must hold):
          1. exposure_class = retail (non-mortgage)
          2. currency (exposure) != borrower_income_currency (counterparty)
          3. is_hedged = False  (new flag — hedged exposures exempt)
          4. is_defaulted = False (defaulted exposures take Art. 127 RW, not Art. 123B)
        Multiplier = 1.50
        RW_arm_b = 75% × 1.50 = 112.5%

    Arm A (hedged): RWA = 100,000 × 0.75  = 75,000
    Arm B (unhedged): RWA = 100,000 × 1.125 = 112,500

Regulatory references:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5× currency-mismatch multiplier for retail
      exposures where loan currency != borrower income currency.
    - BCBS CRE20.89-90: currency mismatch add-on for unhedged foreign-currency retail.
    - src/rwa_calc/data/schemas.py: LOAN_SCHEMA (is_hedged will be added in Wave 4),
      COUNTERPARTY_SCHEMA (borrower_income_currency).
    - tests/fixtures/single_exposure.py: calculate_single_sa_exposure (is_hedged param
      added in this wave).

Usage:
    uv run python tests/fixtures/p1_94a/p1_94a.py
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

COUNTERPARTY_REF: str = "CP_P194A"
LOAN_REF_HEDGED: str = "P194A_HEDGED"
LOAN_REF_UNHEDGED: str = "P194A_UNHEDGED"

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2032, 1, 4)

# Both arms carry the same drawn amount (EAD = drawn, no interest, no CRM)
DRAWN_AMOUNT: float = 100_000.0

# ---------------------------------------------------------------------------
# Regulatory scalars (single source of truth for test-writer assertions)
# ---------------------------------------------------------------------------

#: Base SA risk weight for retail non-mortgage (PRA PS1/26 Art. 123(1))
SA_RETAIL_BASE_RW: float = 0.75

#: Art. 123B currency-mismatch multiplier
CURRENCY_MISMATCH_MULTIPLIER: float = 1.50

#: Arm A (hedged) — multiplier suppressed
RW_HEDGED: float = SA_RETAIL_BASE_RW  # 0.75
RWA_HEDGED: float = DRAWN_AMOUNT * RW_HEDGED  # 75,000.00

#: Arm B (unhedged) — multiplier applied
RW_UNHEDGED: float = SA_RETAIL_BASE_RW * CURRENCY_MISMATCH_MULTIPLIER  # 1.125
RWA_UNHEDGED: float = DRAWN_AMOUNT * RW_UNHEDGED  # 112,500.00


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.94a shared counterparty: natural person, GB, borrower income in GBP.

    entity_type=natural_person → classifier routes to retail_other exposure class
    (non-mortgage retail, no LTV supplied).
    borrower_income_currency=GBP: triggers Art. 123B when loan is EUR and is_hedged=False.
    annual_revenue/total_assets: not applicable (natural person) — omitted (null).
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
    P1.94a loan: EUR-denominated retail drawn loan with is_hedged flag.

    currency=EUR vs. counterparty borrower_income_currency=GBP → currency mismatch.
    is_hedged controls whether Art. 123B multiplier fires.
    product_type=term_loan: on-balance-sheet, EAD = drawn_amount.
    seniority=senior: standard senior claim.
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
    is_hedged: bool  # NOTE: not yet in LOAN_SCHEMA — engine-implementer adds in Wave 4

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
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p194a_counterparty() -> pl.DataFrame:
    """
    Return the P1.94a counterparty (natural person, GB, income GBP) as a DataFrame.

    entity_type=natural_person → classifier produces exposure_class=retail_other.
    borrower_income_currency=GBP: the EUR-denominated loan triggers Art. 123B
    for the unhedged arm.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P194A Test Individual",
        entity_type="natural_person",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
        is_natural_person=True,
        borrower_income_currency="GBP",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p194a_loans() -> pl.DataFrame:
    """
    Return both P1.94a loan rows (hedged + unhedged) as a single DataFrame.

    Both rows share the same counterparty and EUR denomination.
    The is_hedged column is carried as pl.Boolean.

    LOAN_SCHEMA does not yet declare is_hedged.  The column is added via
    with_columns() after building from dtypes_of(LOAN_SCHEMA) so that existing
    schema columns are typed correctly and is_hedged is appended with the right
    dtype regardless of schema state.
    """
    hedged_row = _Loan(
        loan_reference=LOAN_REF_HEDGED,
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
        is_hedged=True,
    )
    unhedged_row = _Loan(
        loan_reference=LOAN_REF_UNHEDGED,
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
    )

    rows = [hedged_row.to_dict(), unhedged_row.to_dict()]

    # Build with the declared schema columns first (excluding is_hedged),
    # then append is_hedged as a typed Boolean column.  This pattern ensures
    # the row loads cleanly whether or not LOAN_SCHEMA has been amended yet.
    loan_schema_cols = dtypes_of(LOAN_SCHEMA)
    rows_without_hedged = [{k: v for k, v in r.items() if k != "is_hedged"} for r in rows]
    df = pl.DataFrame(rows_without_hedged, schema=loan_schema_cols)

    # Append is_hedged as pl.Boolean — the single source of truth for this fixture
    is_hedged_values = [r["is_hedged"] for r in rows]
    df = df.with_columns(pl.Series("is_hedged", is_hedged_values, dtype=pl.Boolean))
    return df


# ---------------------------------------------------------------------------
# Empty helpers (no collateral, guarantees, etc. in this scenario)
# ---------------------------------------------------------------------------


def create_p194a_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p194a_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p194a_empty_collateral() -> pl.DataFrame:
    """Return an empty collateral DataFrame (no CRM in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p194a_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p194a_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p194a_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame (no external ratings in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p194a_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------


def build_p1_94a_bundle(*, fixtures_dir: Path) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P1.94a scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module; the ``fixtures_dir`` argument is accepted for
    interface symmetry with other bundle builders (it is not used here).

    Returns:
        RawDataBundle with:
        - 1 counterparty (CP_P194A, natural person, GB, income GBP)
        - 2 loans (P194A_HEDGED is_hedged=True, P194A_UNHEDGED is_hedged=False),
          both EUR-denominated, retail/non-mortgage
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Path to the fixtures directory (unused; accepted for
            interface compatibility with other bundle builders).
    """
    return make_raw_bundle(
        facilities=create_p194a_empty_facilities().lazy(),
        loans=create_p194a_loans().lazy(),
        counterparties=create_p194a_counterparty().lazy(),
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
        contingents=create_p194a_empty_contingents().lazy(),
        collateral=create_p194a_empty_collateral().lazy(),
        guarantees=create_p194a_empty_guarantees().lazy(),
        provisions=create_p194a_empty_provisions().lazy(),
        ratings=create_p194a_empty_ratings().lazy(),
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p194a_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.94a parquet files and return a mapping of name -> path.

    Two parquet files are written:
    - counterparty.parquet  (1 row: CP_P194A)
    - loans.parquet         (2 rows: P194A_HEDGED, P194A_UNHEDGED)

    The loans parquet includes the is_hedged column (pl.Boolean) even though
    LOAN_SCHEMA does not yet declare it.  The engine-implementer will amend the
    schema in Wave 4; the parquet is forward-compatible.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p194a_counterparty()),
        ("loans", create_p194a_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.94a fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<20} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: P1.94a — is_hedged flag gates Art. 123B currency-mismatch multiplier")
    print()
    print(f"  Base retail SA RW (Art. 123(1)):   {SA_RETAIL_BASE_RW:.0%}")
    print(f"  Art. 123B multiplier:              {CURRENCY_MISMATCH_MULTIPLIER:.2f}×")
    print()
    print("  Arm A (P194A_HEDGED,   is_hedged=True ):")
    print(f"    risk_weight                      = {RW_HEDGED:.4f}")
    print(f"    rwa                              = {RWA_HEDGED:,.2f}")
    print("    currency_mismatch_multiplier_applied = False")
    print()
    print("  Arm B (P194A_UNHEDGED, is_hedged=False):")
    print(f"    risk_weight                      = {RW_UNHEDGED:.4f}")
    print(f"    rwa                              = {RWA_UNHEDGED:,.2f}")
    print("    currency_mismatch_multiplier_applied = True")
    print()
    # Verify is_hedged column presence and dtype
    loans_df = pl.read_parquet(saved["loans"])
    if "is_hedged" in loans_df.columns:
        dtype = loans_df.schema["is_hedged"]
        hedged_vals = loans_df["is_hedged"].to_list()
        print(f"  is_hedged column dtype:            {dtype}")
        print(f"  is_hedged values:                  {hedged_vals}")
    else:
        print("  WARNING: is_hedged column missing from loans parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p194a_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
