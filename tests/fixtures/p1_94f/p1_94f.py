"""
Generate P1.94f fixtures: exposure-class gate on Art. 123B currency-mismatch multiplier.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/currency_mismatch.py)

Key responsibilities:
- Produce three counterparties (natural person RRE, corporate CRE, corporate general) each
  with borrower_income_currency=GBP, all in GB, all non-defaulted.
- Produce three EUR-denominated loan rows, all is_hedged=False.  The currency mismatch
  (EUR loan, GBP income) fires the Art. 123B eligibility check in each arm.
- Produce one collateral row (immovable / commercial) linked to the CRE loan so the
  engine classifier routes it to exposure_class=commercial_mortgage.
- Arm A fires the multiplier (retail_other); Arms B and C do NOT (wrong exposure class).

Scenario design:

    Arm A — P194F_RRE (retail_other, is_hedged=False):
        Counterparty: natural person, GB, borrower_income_currency=GBP
        Loan: EUR 100,000, book_code=RETAIL_LENDING, term_loan
        Expected exposure_class: retail_other
        Expected currency_mismatch_multiplier_applied: True
        Base SA retail RW = 75%  (PRA PS1/26 Art. 123(1))
        Art. 123B multiplier = 1.5x → effective RW = 1.125
        EAD = 100,000
        RWA = 112,500.00

    Arm B — P194F_CRE (commercial_mortgage, is_hedged=False):
        Counterparty: corporate, GB, borrower_income_currency=GBP
        Loan: EUR 1,000,000, book_code=COMMERCIAL_RE, term_loan
        Collateral: immovable/commercial, value=1,538,461.54 EUR → LTV=65%
        Expected exposure_class: commercial_mortgage (CRE class — NOT retail)
        Expected currency_mismatch_multiplier_applied: False
        Base SA CRE RW = 100% (Art. 126, unrated corporate, LTV 65%)
        No multiplier fires — Art. 123B gate requires retail_other class.
        EAD = 1,000,000
        RWA = 1,000,000.00

    Arm C — P194F_CORP (corporate, is_hedged=False):
        Counterparty: corporate, GB, borrower_income_currency=GBP
        Loan: EUR 1,000,000, book_code=CORP_LENDING, term_loan
        Expected exposure_class: corporate
        Expected currency_mismatch_multiplier_applied: False
        Base SA corporate RW = 100% (Art. 122, unrated)
        No multiplier fires — Art. 123B gate requires retail_other class.
        EAD = 1,000,000
        RWA = 1,000,000.00

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Art. 123B currency-mismatch multiplier (PRA PS1/26 Art. 123B):
        Trigger conditions (ALL must hold):
          1. exposure_class = retail_other (non-mortgage retail)
          2. currency (loan) != borrower_income_currency (counterparty)  EUR != GBP
          3. is_hedged = False
          4. is_defaulted = False

    Arm A (retail_other, EUR vs GBP, is_hedged=False):
        Multiplier FIRES: RW = 75% x 1.50 = 112.5%
        RWA = 100,000 x 1.125 = 112,500.00

    Arm B (commercial_mortgage — not retail_other):
        Multiplier does NOT fire: exposure_class gate fails.
        Art. 126 CRE: LTV 65% on unrated corporate collateral → standard 100% RW.
        RWA = 1,000,000 x 1.00 = 1,000,000.00

    Arm C (corporate — not retail_other):
        Multiplier does NOT fire: exposure_class gate fails.
        Art. 122: unrated corporate → 100% RW.
        RWA = 1,000,000 x 1.00 = 1,000,000.00

Regulatory references:
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - PRA PS1/26 Art. 123B: 1.5x currency-mismatch multiplier applies ONLY to
      retail exposures (not commercial_mortgage or corporate).
    - PRA PS1/26 Art. 126: commercial RE risk weights (LTV-dependent).
    - PRA PS1/26 Art. 122: corporate SA risk weights (CQS table).
    - BCBS CRE20.89-90: currency mismatch add-on for unhedged foreign-currency retail.
    - src/rwa_calc/data/schemas.py: LOAN_SCHEMA, COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA.
    - tests/fixtures/p1_94a/p1_94a.py: sibling scenario for is_hedged gate.

Usage:
    uv run python tests/fixtures/p1_94f/p1_94f.py
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

# Counterparty references
COUNTERPARTY_REF_RRE: str = "CP_P194F_RRE"
COUNTERPARTY_REF_CRE: str = "CP_P194F_CRE"
COUNTERPARTY_REF_CORP: str = "CP_P194F_CORP"

# Loan (exposure) references
LOAN_REF_RRE: str = "P194F_RRE"
LOAN_REF_CRE: str = "P194F_CRE"
LOAN_REF_CORP: str = "P194F_CORP"

# Collateral reference for Arm B (CRE)
COLLATERAL_REF_CRE: str = "COLL_P194F_CRE"

# Common dates — Basel 3.1 regime (value_date >= 2027-01-01)
VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2032, 1, 4)

# EAD per arm
EAD_RRE: float = 100_000.0
EAD_CRE: float = 1_000_000.0
EAD_CORP: float = 1_000_000.0

# CRE collateral value calibrated to LTV = 65%
# LTV = loan / value  →  value = loan / ltv  =  1_000_000 / 0.65 ≈ 1,538,461.54
COLLATERAL_VALUE_CRE: float = 1_538_461.54
LTV_CRE: float = EAD_CRE / COLLATERAL_VALUE_CRE  # ≈ 0.65

# ---------------------------------------------------------------------------
# Regulatory scalars — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

#: Base SA risk weight for retail non-mortgage (PRA PS1/26 Art. 123(1))
SA_RETAIL_BASE_RW: float = 0.75

#: Art. 123B currency-mismatch multiplier (PRA PS1/26 Art. 123B)
CURRENCY_MISMATCH_MULTIPLIER: float = 1.50

# Arm A (RRE / retail_other) — multiplier fires
RW_RRE: float = SA_RETAIL_BASE_RW * CURRENCY_MISMATCH_MULTIPLIER  # 1.125
RWA_RRE: float = EAD_RRE * RW_RRE  # 112,500.00

# Arm B (commercial_mortgage) — multiplier suppressed by exposure-class gate
RW_CRE: float = 1.00  # Art. 126 unrated corporate, LTV 65%
RWA_CRE: float = EAD_CRE * RW_CRE  # 1,000,000.00

# Arm C (corporate) — multiplier suppressed by exposure-class gate
RW_CORP: float = 1.00  # Art. 122 unrated corporate
RWA_CORP: float = EAD_CORP * RW_CORP  # 1,000,000.00


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.94f counterparty row.

    borrower_income_currency=GBP creates a mismatch with EUR-denominated loans,
    which is needed to trigger Art. 123B eligibility for the retail arm (A).
    Arms B and C share the same mismatch but the exposure class gate blocks
    the multiplier — the test-writer asserts multiplier_applied=False on those.
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
    P1.94f loan row — EUR-denominated, is_hedged=False.

    All three arms use EUR currency against GBP income (mismatch present).
    The exposure-class gate (retail_other only) determines whether the multiplier
    fires, not the is_hedged flag (which is False for all arms in this scenario).
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


@dataclass(frozen=True)
class _Collateral:
    """
    P1.94f collateral row — immovable / commercial property securing the CRE loan.

    collateral_type="immovable" (CollateralType.IMMOVABLE): routes to the RE branch
    in the CRM processor.
    property_type="commercial" (PropertyType.COMMERCIAL): signals commercial RE,
    which with book_code=COMMERCIAL_RE drives the classifier to commercial_mortgage.
    collateral_value / LTV calibrated to 65% (below the 80% threshold) — ensures
    the exposure receives the standard CRE risk weight, not the high-LTV rate.
    beneficiary_type="loan", beneficiary_reference=LOAN_REF_CRE: links to Arm B.
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    property_type: str
    property_ltv: float
    beneficiary_type: str
    beneficiary_reference: str
    is_income_producing: bool
    is_qualifying_re: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "property_type": self.property_type,
            "property_ltv": self.property_ltv,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "is_income_producing": self.is_income_producing,
            "is_qualifying_re": self.is_qualifying_re,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p194f_counterparties() -> pl.DataFrame:
    """
    Return all three P1.94f counterparties as a single DataFrame.

    CP_P194F_RRE: natural person, GB, borrower_income_currency=GBP.
        entity_type=natural_person → classifier routes to retail_other.
        Art. 123B multiplier fires for this arm (retail_other + EUR loan + unhedged).

    CP_P194F_CRE: corporate, GB, borrower_income_currency=GBP.
        entity_type=corporate + book_code=COMMERCIAL_RE → classifier routes to
        commercial_mortgage (with collateral evidence).
        Art. 123B multiplier does NOT fire (exposure_class != retail_other).

    CP_P194F_CORP: corporate, GB, borrower_income_currency=GBP.
        entity_type=corporate + book_code=CORP_LENDING → classifier routes to corporate.
        Art. 123B multiplier does NOT fire (exposure_class != retail_other).
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_RRE,
            counterparty_name="P194F Natural Person (RRE arm)",
            entity_type="natural_person",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=True,
            borrower_income_currency="GBP",
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_CRE,
            counterparty_name="P194F Corporate CRE (commercial_mortgage arm)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=False,
            borrower_income_currency="GBP",
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_CORP,
            counterparty_name="P194F Corporate (sanity anchor)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=False,
            borrower_income_currency="GBP",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p194f_loans() -> pl.DataFrame:
    """
    Return all three P1.94f loan rows as a single DataFrame.

    All three arms use EUR currency (mismatch against GBP income) and is_hedged=False.
    The is_hedged column is appended via with_columns() to handle any schema-state
    transition consistently (same pattern as p1_94a).

    Arm A (P194F_RRE): retail_other, EUR 100,000, book_code=RETAIL_LENDING.
    Arm B (P194F_CRE): commercial_mortgage, EUR 1,000,000, book_code=COMMERCIAL_RE.
    Arm C (P194F_CORP): corporate, EUR 1,000,000, book_code=CORP_LENDING.
    """
    raw_rows = [
        _Loan(
            loan_reference=LOAN_REF_RRE,
            product_type="term_loan",
            book_code="RETAIL_LENDING",
            counterparty_reference=COUNTERPARTY_REF_RRE,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="EUR",
            drawn_amount=EAD_RRE,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
        ),
        _Loan(
            loan_reference=LOAN_REF_CRE,
            product_type="term_loan",
            book_code="COMMERCIAL_RE",
            counterparty_reference=COUNTERPARTY_REF_CRE,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="EUR",
            drawn_amount=EAD_CRE,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
        ),
        _Loan(
            loan_reference=LOAN_REF_CORP,
            product_type="term_loan",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF_CORP,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="EUR",
            drawn_amount=EAD_CORP,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            is_hedged=False,
        ),
    ]

    # Build with the declared schema columns first (excluding is_hedged),
    # then append is_hedged as a typed Boolean column.  Mirrors p1_94a pattern.
    loan_schema_cols = dtypes_of(LOAN_SCHEMA)
    rows_without_hedged = [
        {k: v for k, v in r.to_dict().items() if k != "is_hedged"} for r in raw_rows
    ]
    df = pl.DataFrame(rows_without_hedged, schema=loan_schema_cols)

    is_hedged_values = [r.is_hedged for r in raw_rows]
    df = df.with_columns(pl.Series("is_hedged", is_hedged_values, dtype=pl.Boolean))
    return df


def create_p194f_collateral() -> pl.DataFrame:
    """
    Return the single P1.94f collateral row (for Arm B — CRE).

    collateral_type="immovable" (CollateralType.IMMOVABLE): immovable property.
    property_type="commercial" (PropertyType.COMMERCIAL): commercial RE.
    property_ltv=0.65: LTV = EUR 1,000,000 / EUR 1,538,461.54 ≈ 65%.
    beneficiary_type="loan", beneficiary_reference=P194F_CRE: links to Arm B loan.
    is_qualifying_re=True: marks this as qualifying RE for SA classification.
    is_income_producing=True: standard IPRE flag for commercial property.

    Arms A and C have no collateral.
    """
    row = _Collateral(
        collateral_reference=COLLATERAL_REF_CRE,
        collateral_type="immovable",
        currency="EUR",
        market_value=COLLATERAL_VALUE_CRE,
        property_type="commercial",
        property_ltv=round(LTV_CRE, 6),
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF_CRE,
        is_income_producing=True,
        is_qualifying_re=True,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Empty helpers
# ---------------------------------------------------------------------------


def create_p194f_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p194f_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p194f_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p194f_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p194f_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame (no external ratings in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p194f_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------


def build_p1_94f_bundle(*, fixtures_dir: Path) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P1.94f scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module; the ``fixtures_dir`` argument is accepted for
    interface symmetry with other bundle builders (it is not used here).

    Returns:
        RawDataBundle with:
        - 3 counterparties (CP_P194F_RRE, CP_P194F_CRE, CP_P194F_CORP)
        - 3 loans (P194F_RRE, P194F_CRE, P194F_CORP), all EUR, is_hedged=False
        - 1 collateral row (COLL_P194F_CRE, immovable/commercial, LTV 65%)
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Path to the fixtures directory (unused; accepted for
            interface compatibility with other bundle builders).
    """
    return make_raw_bundle(
        facilities=create_p194f_empty_facilities().lazy(),
        loans=create_p194f_loans().lazy(),
        counterparties=create_p194f_counterparties().lazy(),
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
        contingents=create_p194f_empty_contingents().lazy(),
        collateral=create_p194f_collateral().lazy(),
        guarantees=create_p194f_empty_guarantees().lazy(),
        provisions=create_p194f_empty_provisions().lazy(),
        ratings=create_p194f_empty_ratings().lazy(),
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p194f_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.94f parquet files and return a mapping of name -> path.

    Three parquet files are written:
    - counterparties.parquet  (3 rows: CP_P194F_RRE, CP_P194F_CRE, CP_P194F_CORP)
    - loans.parquet           (3 rows: P194F_RRE, P194F_CRE, P194F_CORP)
    - collateral.parquet      (1 row: COLL_P194F_CRE, immovable/commercial, LTV 65%)

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
        ("counterparties", create_p194f_counterparties()),
        ("loans", create_p194f_loans()),
        ("collateral", create_p194f_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.94f fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<20} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: P1.94f — exposure-class gate on Art. 123B currency-mismatch multiplier")
    print()
    print(f"  Base retail SA RW (Art. 123(1)):   {SA_RETAIL_BASE_RW:.0%}")
    print(f"  Art. 123B multiplier:              {CURRENCY_MISMATCH_MULTIPLIER:.2f}x")
    print()
    print("  Arm A (P194F_RRE, retail_other, is_hedged=False):")
    print("    exposure_class                       = retail_other")
    print(f"    risk_weight                          = {RW_RRE:.4f}")
    print(f"    rwa                                  = {RWA_RRE:,.2f}")
    print("    currency_mismatch_multiplier_applied = True")
    print()
    print("  Arm B (P194F_CRE, commercial_mortgage, is_hedged=False):")
    print("    exposure_class                       = commercial_mortgage")
    print(f"    risk_weight                          = {RW_CRE:.4f}")
    print(f"    rwa                                  = {RWA_CRE:,.2f}")
    print("    currency_mismatch_multiplier_applied = False")
    print("    anti-assertion: RW != 1.50, RWA != 1,500,000.00")
    print()
    print("  Arm C (P194F_CORP, corporate, is_hedged=False):")
    print("    exposure_class                       = corporate")
    print(f"    risk_weight                          = {RW_CORP:.4f}")
    print(f"    rwa                                  = {RWA_CORP:,.2f}")
    print("    currency_mismatch_multiplier_applied = False")
    print()
    loans_df = pl.read_parquet(saved["loans"])
    if "is_hedged" in loans_df.columns:
        dtype = loans_df.schema["is_hedged"]
        hedged_vals = loans_df["is_hedged"].to_list()
        print(f"  is_hedged column dtype:            {dtype}")
        print(f"  is_hedged values:                  {hedged_vals}")
    else:
        print("  WARNING: is_hedged column missing from loans parquet")
    coll_df = pl.read_parquet(saved["collateral"])
    print(f"  collateral_type:                   {coll_df['collateral_type'][0]}")
    print(f"  property_type:                     {coll_df['property_type'][0]}")
    print(f"  property_ltv:                      {coll_df['property_ltv'][0]:.4f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p194f_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
