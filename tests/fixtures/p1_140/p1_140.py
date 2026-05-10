"""
Generate P1.140 fixtures: ADC classification derivation (Art. 124(3) / Art. 124K).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (classifier.py)

Key responsibilities:
- Produce two counterparty rows:
    CP_ADC_SPV_001: corporate entity (SPV-like developer), GB.
    CP_ADC_NP_001:  individual (natural person), GB.
- Produce two facility rows (NEW field: is_under_construction=True):
    FAC_ADC_SPV_001: development_finance, senior, GBP 10,000,000, maturity 2030.
    FAC_ADC_NP_001:  mortgage, senior, GBP 250,000, maturity 2055.
- Produce two loan rows (NEW field: is_under_construction=True):
    LN_ADC_SPV_001: development_finance, senior, drawn GBP 10,000,000.
    LN_ADC_NP_001:  mortgage, senior, drawn GBP 250,000.
- Produce two collateral rows (is_adc=null — derivation must fire):
    COL_ADC_SPV_001: residential RE on LN_ADC_SPV_001, LTV=0.83, is_adc=null.
    COL_ADC_NP_001:  residential RE on LN_ADC_NP_001, LTV=0.71, is_adc=null.
- Produce self-referencing facility_mapping rows (trivial hierarchy).
- Produce empty lending_mapping and org_mapping.

Scenario design — ADC classification (Basel 3.1 Art. 124(3) / Art. 124K):
    ADC ("Acquisition, Development and Construction") exposures attract a 150%
    risk weight under Basel 3.1 unless specific conditions are met.

    The ADC flag on collateral may be supplied explicitly (is_adc=True/False) or
    derived by the engine from the exposure's product_type + is_under_construction flag:
        derived is_adc = True  when:
            (a) the exposure's product_type is a development-finance type, OR
            (b) is_under_construction=True on the loan/facility.

    Discrimination between the two P1.140 scenarios:
        SPV exposure (CP_ADC_SPV_001 / LN_ADC_SPV_001):
            product_type=development_finance, is_under_construction=True
            → is_adc should be derived as True by the engine.
            → Collateral is_adc=null so the derivation is the SOLE source.

        Natural-person exposure (CP_ADC_NP_001 / LN_ADC_NP_001):
            product_type=mortgage, is_under_construction=True
            → is_adc derived as True via is_under_construction flag even
              though product_type alone would not trigger ADC treatment.
            → Demonstrates that is_under_construction is the decisive flag.

    Both collateral rows have is_adc=null intentionally: the engine must derive
    is_adc from exposure-level attributes rather than reading it directly from
    the collateral row.

New field introduced by P1.140:
    is_under_construction (pl.Boolean, default=False):
        Added to FACILITY_SCHEMA, LOAN_SCHEMA, and CONTINGENTS_SCHEMA.
        When True, signals that the financed property is under construction,
        satisfying the Basel 3.1 Art. 124K(1) ADC definition even when
        product_type does not directly indicate development finance.

    Until the engine-implementer wave adds this field to the canonical schemas in
    src/rwa_calc/data/schemas.py, the fixture parquet files carry the column but
    the loader will ignore it (unknown columns pass through).  The engine-implementer
    must add:
        "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False)
    to FACILITY_SCHEMA, LOAN_SCHEMA, and CONTINGENTS_SCHEMA.

Schema-validator workaround:
    The fixture builds its facility and loan DataFrames using local inline dtype
    dicts (_FACILITY_FIXTURE_SCHEMA, _LOAN_FIXTURE_SCHEMA) that include
    is_under_construction=pl.Boolean rather than calling dtypes_of(FACILITY_SCHEMA)
    / dtypes_of(LOAN_SCHEMA), because those canonical schemas do not yet declare
    the new column.  The approach mirrors the p1_182 pattern for business_age_years.

References:
    - PRA PS1/26 Art. 124(3) p.50: ADC exposure definition.
    - PRA PS1/26 Art. 124K(1)/(2) p.58: ADC risk weight = 150%.
    - PRA PS1/26 Glossary p.3: "acquisition, development and construction" definition.
    - src/rwa_calc/data/schemas.py: FACILITY_SCHEMA, LOAN_SCHEMA, CONTINGENTS_SCHEMA.

Usage:
    uv run python tests/fixtures/p1_140/p1_140.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    ORG_MAPPING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_SPV_REF = "CP_ADC_SPV_001"
CP_NP_REF = "CP_ADC_NP_001"

# Facility references
FAC_SPV_REF = "FAC_ADC_SPV_001"
FAC_NP_REF = "FAC_ADC_NP_001"

# Loan references
LOAN_SPV_REF = "LN_ADC_SPV_001"
LOAN_NP_REF = "LN_ADC_NP_001"

# Collateral references
COL_SPV_REF = "COL_ADC_SPV_001"
COL_NP_REF = "COL_ADC_NP_001"

# Dates
REPORTING_DATE = date(2027, 1, 2)  # Post Basel 3.1 go-live (1 Jan 2027)
FAC_SPV_MATURITY = date(2030, 6, 30)
FAC_NP_MATURITY = date(2055, 6, 30)
LOAN_SPV_MATURITY = date(2030, 6, 30)
LOAN_NP_MATURITY = date(2055, 6, 30)

# Loan / facility economics
FACILITY_SPV_LIMIT = 10_000_000.0
FACILITY_NP_LIMIT = 250_000.0
LOAN_SPV_DRAWN = 10_000_000.0
LOAN_NP_DRAWN = 250_000.0

# Collateral values
COL_SPV_MARKET_VALUE = 12_000_000.0
COL_NP_MARKET_VALUE = 350_000.0
COL_SPV_LTV = 0.83
COL_NP_LTV = 0.71

# Expected derivation outcomes (assertions live in the test)
# SPV: product_type=development_finance + is_under_construction=True → is_adc=True
EXPECTED_ADC_SPV: bool = True
# NP: product_type=mortgage, is_under_construction=True → is_adc=True (via flag)
EXPECTED_ADC_NP: bool = True

# ADC risk weight under PRA PS1/26 Art. 124K(1)
ADC_RISK_WEIGHT: float = 1.50  # 150%


# ---------------------------------------------------------------------------
# Fixture dtype schemas (inline — is_under_construction not yet in canonical schema)
# ---------------------------------------------------------------------------

_FACILITY_FIXTURE_SCHEMA: dict[str, pl.DataType] = {
    "facility_reference": pl.String,
    "product_type": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "limit": pl.Float64,
    "committed": pl.Boolean,
    "seniority": pl.String,
    # NEW field for P1.140 — not yet in FACILITY_SCHEMA canonical schema.
    # Engine-implementer must add:
    #   "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False)
    # to FACILITY_SCHEMA in src/rwa_calc/data/schemas.py.
    "is_under_construction": pl.Boolean,
}

_LOAN_FIXTURE_SCHEMA: dict[str, pl.DataType] = {
    "loan_reference": pl.String,
    "product_type": pl.String,
    "counterparty_reference": pl.String,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "interest": pl.Float64,
    "seniority": pl.String,
    # NEW field for P1.140 — not yet in LOAN_SCHEMA canonical schema.
    # Engine-implementer must add:
    #   "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False)
    # to LOAN_SCHEMA in src/rwa_calc/data/schemas.py.
    "is_under_construction": pl.Boolean,
}


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Counterparty row for P1.140."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    is_natural_person: bool
    annual_revenue: float | None
    default_status: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "is_natural_person": self.is_natural_person,
            "annual_revenue": self.annual_revenue,
            "default_status": self.default_status,
        }


@dataclass(frozen=True)
class _Facility:
    """
    Facility row for P1.140 — includes the new is_under_construction flag.

    is_under_construction=True is the load-bearing field for P1.140: it marks
    the property as under construction, satisfying the Basel 3.1 Art. 124K ADC
    definition regardless of product_type.
    """

    facility_reference: str
    product_type: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "is_under_construction": self.is_under_construction,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Loan row for P1.140 — includes the new is_under_construction flag.

    The loan-level is_under_construction flag mirrors the facility flag.
    Both must carry the flag because the engine may route the exposure via
    either loan or facility rows depending on the input data shape.
    """

    loan_reference: str
    product_type: str
    counterparty_reference: str
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "counterparty_reference": self.counterparty_reference,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "is_under_construction": self.is_under_construction,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    Collateral row for P1.140.

    is_adc is deliberately NULL on both rows so the engine must derive the ADC
    flag from the exposure's product_type + is_under_construction, not from the
    collateral row directly.  is_presold=False (no presales arrangement reduces
    the ADC characterisation risk).

    property_ltv and property_type are provided so the engine can apply
    the correct RE risk weight if ADC classification is overridden or
    is not triggered.
    """

    collateral_reference: str
    collateral_type: str
    beneficiary_type: str
    beneficiary_reference: str
    market_value: float
    property_type: str
    property_ltv: float
    is_qualifying_re: bool
    is_adc: bool | None  # Deliberately None — derivation must fire
    is_presold: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "market_value": self.market_value,
            "property_type": self.property_type,
            "property_ltv": self.property_ltv,
            "is_qualifying_re": self.is_qualifying_re,
            "is_adc": self.is_adc,
            "is_presold": self.is_presold,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1140_counterparties() -> pl.DataFrame:
    """
    Return two P1.140 counterparties as a DataFrame.

    CP_ADC_SPV_001: corporate entity_type — a developer or SPV borrowing for a
        residential development project. annual_revenue=8,000,000 keeps the
        counterparty below the Basel 3.1 large-corporate threshold (GBP 440m)
        so it is treated as a standard SME corporate for SA classification purposes.

    CP_ADC_NP_001: individual (is_natural_person=True) — a self-build borrower
        undertaking residential construction. Entity_type=individual maps to
        the retail exposure class under SA.  annual_revenue=null (individuals
        typically have no disclosed revenue in the borrower file).
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_SPV_REF,
            counterparty_name="P1.140 ADC Developer SPV Ltd",
            entity_type="corporate",
            country_code="GB",
            is_natural_person=False,
            annual_revenue=8_000_000.0,
            default_status=False,
        ),
        _Counterparty(
            counterparty_reference=CP_NP_REF,
            counterparty_name="P1.140 ADC Natural Person Self-Build",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            annual_revenue=None,
            default_status=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1140_facilities() -> pl.DataFrame:
    """
    Return two P1.140 facilities as a DataFrame.

    FAC_ADC_SPV_001: development_finance product — a committed senior facility
        of GBP 10,000,000 against CP_ADC_SPV_001 maturing 2030-06-30.
        is_under_construction=True is the load-bearing ADC flag for this row.

    FAC_ADC_NP_001: mortgage product — a committed senior facility of GBP 250,000
        against CP_ADC_NP_001 maturing 2055-06-30.
        is_under_construction=True is the load-bearing ADC flag:
        product_type=mortgage would not by itself trigger ADC treatment under
        Art. 124K but the is_under_construction flag does.

    Both facilities use the inline _FACILITY_FIXTURE_SCHEMA because
    is_under_construction is not yet declared in the canonical FACILITY_SCHEMA.
    """
    rows = [
        _Facility(
            facility_reference=FAC_SPV_REF,
            product_type="development_finance",
            counterparty_reference=CP_SPV_REF,
            value_date=REPORTING_DATE,
            maturity_date=FAC_SPV_MATURITY,
            currency="GBP",
            limit=FACILITY_SPV_LIMIT,
            committed=True,
            seniority="senior",
            is_under_construction=True,
        ),
        _Facility(
            facility_reference=FAC_NP_REF,
            product_type="mortgage",
            counterparty_reference=CP_NP_REF,
            value_date=REPORTING_DATE,
            maturity_date=FAC_NP_MATURITY,
            currency="GBP",
            limit=FACILITY_NP_LIMIT,
            committed=True,
            seniority="senior",
            is_under_construction=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=_FACILITY_FIXTURE_SCHEMA)


def create_p1140_loans() -> pl.DataFrame:
    """
    Return two P1.140 loans as a DataFrame.

    LN_ADC_SPV_001: fully drawn development_finance loan, GBP 10,000,000
        against CP_ADC_SPV_001.  EAD = 10,000,000 + 0 = 10,000,000 GBP.
        is_under_construction=True — ADC derivation fires.

    LN_ADC_NP_001: fully drawn mortgage loan, GBP 250,000
        against CP_ADC_NP_001.  EAD = 250,000 + 0 = 250,000 GBP.
        is_under_construction=True — ADC derivation fires (even though
        product_type=mortgage would not individually indicate ADC).

    Both loans use the inline _LOAN_FIXTURE_SCHEMA because
    is_under_construction is not yet declared in the canonical LOAN_SCHEMA.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_SPV_REF,
            product_type="development_finance",
            counterparty_reference=CP_SPV_REF,
            maturity_date=LOAN_SPV_MATURITY,
            currency="GBP",
            drawn_amount=LOAN_SPV_DRAWN,
            interest=0.0,
            seniority="senior",
            is_under_construction=True,
        ),
        _Loan(
            loan_reference=LOAN_NP_REF,
            product_type="mortgage",
            counterparty_reference=CP_NP_REF,
            maturity_date=LOAN_NP_MATURITY,
            currency="GBP",
            drawn_amount=LOAN_NP_DRAWN,
            interest=0.0,
            seniority="senior",
            is_under_construction=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=_LOAN_FIXTURE_SCHEMA)


def create_p1140_collateral() -> pl.DataFrame:
    """
    Return two P1.140 collateral rows as a DataFrame.

    COL_ADC_SPV_001: Residential real-estate collateral securing LN_ADC_SPV_001.
        market_value=12,000,000, LTV=0.83.
        is_adc=None — the engine must derive is_adc=True from the loan's
        product_type (development_finance) and/or is_under_construction flag.
        is_presold=False — no pre-sales reduce the ADC risk characterisation.
        is_qualifying_re=True — the property meets eligibility criteria under
        Art. 124 (Basel 3.1) assuming standard regulatory conditions.

    COL_ADC_NP_001: Residential real-estate collateral securing LN_ADC_NP_001.
        market_value=350,000, LTV=0.71.
        is_adc=None — derivation must fire (via is_under_construction on loan).
        is_presold=False, is_qualifying_re=True.

    The COLLATERAL_SCHEMA already declares is_adc as an optional Boolean
    (default=False), so the fixture can use dtypes_of(COLLATERAL_SCHEMA)
    directly.  The None values for is_adc are correctly handled as null
    by Polars when passed in the row dict.
    """
    rows = [
        _Collateral(
            collateral_reference=COL_SPV_REF,
            collateral_type="real_estate",
            beneficiary_type="loan",
            beneficiary_reference=LOAN_SPV_REF,
            market_value=COL_SPV_MARKET_VALUE,
            property_type="residential",
            property_ltv=COL_SPV_LTV,
            is_qualifying_re=True,
            is_adc=None,  # Deliberately null — derivation must fire
            is_presold=False,
        ),
        _Collateral(
            collateral_reference=COL_NP_REF,
            collateral_type="real_estate",
            beneficiary_type="loan",
            beneficiary_reference=LOAN_NP_REF,
            market_value=COL_NP_MARKET_VALUE,
            property_type="residential",
            property_ltv=COL_NP_LTV,
            is_qualifying_re=True,
            is_adc=None,  # Deliberately null — derivation must fire
            is_presold=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p1140_facility_mapping() -> pl.DataFrame:
    """
    Return trivial self-referencing facility mappings as a DataFrame.

    Each facility maps to itself (parent == child), which satisfies the
    hierarchy resolver without introducing cross-facility relationships.
    This is the minimal mapping required to pass the pipeline loader's
    facility_mapping validation.

    The lending_mapping and org_mapping are empty (zero rows) — there
    are no connected party relationships in this scenario.
    """
    rows = [
        {
            "parent_facility_reference": FAC_SPV_REF,
            "child_reference": LOAN_SPV_REF,
            "child_type": "loan",
        },
        {
            "parent_facility_reference": FAC_NP_REF,
            "child_reference": LOAN_NP_REF,
            "child_type": "loan",
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1140_lending_mapping() -> pl.DataFrame:
    """Return an empty lending mapping DataFrame (no connected party relationships)."""
    return pl.DataFrame(
        schema=dtypes_of(LENDING_MAPPING_SCHEMA),
    )


def create_p1140_org_mapping() -> pl.DataFrame:
    """Return an empty org mapping DataFrame (no organisational hierarchy)."""
    return pl.DataFrame(
        schema=dtypes_of(ORG_MAPPING_SCHEMA),
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1140_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.140 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p1140_counterparties()),
        ("facility", create_p1140_facilities()),
        ("loan", create_p1140_loans()),
        ("collateral", create_p1140_collateral()),
        ("facility_mapping", create_p1140_facility_mapping()),
        ("lending_mapping", create_p1140_lending_mapping()),
        ("org_mapping", create_p1140_org_mapping()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.140 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: ADC classification derivation (Art. 124(3) / Art. 124K)")
    print(f"  SPV counterparty:  {CP_SPV_REF} (corporate, GB)")
    print(f"    Facility:        {FAC_SPV_REF}  GBP {FACILITY_SPV_LIMIT:,.0f}")
    print(f"    Loan:            {LOAN_SPV_REF}  GBP {LOAN_SPV_DRAWN:,.0f}")
    print(f"    Collateral:      {COL_SPV_REF}  MV={COL_SPV_MARKET_VALUE:,.0f}  LTV={COL_SPV_LTV}")
    print("    is_under_construction=True, is_adc=null (derivation fires -> True)")
    print()
    print(f"  NP counterparty:   {CP_NP_REF} (individual, GB)")
    print(f"    Facility:        {FAC_NP_REF}  GBP {FACILITY_NP_LIMIT:,.0f}")
    print(f"    Loan:            {LOAN_NP_REF}  GBP {LOAN_NP_DRAWN:,.0f}")
    print(f"    Collateral:      {COL_NP_REF}  MV={COL_NP_MARKET_VALUE:,.0f}  LTV={COL_NP_LTV}")
    print("    is_under_construction=True, is_adc=null (derivation fires -> True)")
    print()
    print(f"  ADC risk weight (Art. 124K(1)): {ADC_RISK_WEIGHT:.0%}")
    print()
    print("  Schema note:")
    print("    is_under_construction is NEW — not yet in canonical FACILITY_SCHEMA /")
    print("    LOAN_SCHEMA / CONTINGENTS_SCHEMA.  Engine-implementer must add:")
    print('      "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False)')
    print("    to all three schemas in src/rwa_calc/data/schemas.py.")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1140_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
