"""
Generate P1.142 fixtures: Basel 3.1 Art. 124E three-property limit → income-producing RE routing.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/real_estate.py)

Scenario design (P1.142 — Art. 124E three-property limit):

    Basel 3.1 Art. 124E(1)(b) limits the preferential owner-occupied residential
    treatment (Art. 124F loan-split, Art. 124L) to borrowers whose total exposure is
    secured on no more than THREE residential properties (including the financed one).
    When the limit is BREACHED (count >= 4) the exposure is re-routed to the
    income-producing residential whole-loan track (Art. 124G, Table 6B).

    Art. 124E(4) specifies that housing units (flats, apartments) within a single
    building are each counted individually — a multi-let block of flats is not a
    single property.

    Two obligor rows exercise the threshold:

    BREACH row (CP_P1142_BREACH):
        qualifying_property_count = 4  → limit breached (4 > 3)
        Engine must set materially_dependent = False (or route to income-producing),
        deriving the Art. 124G whole-loan treatment.
        Table 6B, LTV band 70-80% → RW = 0.50.
        EAD = 200,000 (on-balance CCF = 1.0)
        RWA = 200,000 x 0.50 = 100,000.00

    CONTROL row (CP_P1142_CTRL):
        qualifying_property_count = 3  → limit met (3 <= 3)
        Engine keeps owner-occupied Art. 124F loan-split treatment.
        Loan-split: secured_share = min(1, 0.55 / 0.75) = 0.73333
        RW_split = 0.20 x 0.73333 + 0.75 x 0.26667 = 0.34667
        RWA = 200,000 x 0.34667 = 69,333.33

    Common inputs for both rows:
        entity_type = "individual" (natural person)
        is_natural_person = True
        is_social_housing = False
        is_income_producing = null/absent on collateral (engine derives from count)
        property_type = "residential"
        property_ltv = 0.75
        prior_charge_ltv = 0.0 (senior first charge)
        is_qualifying_re = True
        EAD = 200,000 GBP, on-balance sheet (loan, CCF implicit = 1.0)

New field introduced by P1.142 (counterparty level):
    qualifying_property_count (pl.Int32, nullable):
        Count of residential properties securing the borrower's total residential
        RE exposure with the firm.  Null means the count is unknown/not collected
        (treated conservatively by the engine — limit assumed breached).

    Until the engine-implementer wave adds this field to COUNTERPARTY_SCHEMA in
    src/rwa_calc/data/schemas.py, the fixture uses an inline dtype dict that
    extends the canonical schema with the new column.

Schema-validator workaround:
    create_p1142_counterparties() uses _COUNTERPARTY_FIXTURE_SCHEMA (an inline
    dict) rather than dtypes_of(COUNTERPARTY_SCHEMA) because qualifying_property_count
    is not yet in the canonical schema.  The engine-implementer must add:
        "qualifying_property_count": ColumnSpec(pl.Int32, required=False)
    to COUNTERPARTY_SCHEMA in src/rwa_calc/data/schemas.py.

Hand-calculations:
    Breach row (count=4):
        materially_dependent_flag = NOT (count <= 3) = True  →  Art. 124G whole-loan
        LTV band: 0.75 falls in 70%-80% band (Table 6B: >= 0.70 and < 0.80)
        RW = 0.50 (Table 6B row for 70-80% LTV)
        EAD = 200,000  (on-BS, CCF = 1.0)
        RWA = 200,000 x 0.50 = 100,000.00

    Control row (count=3):
        materially_dependent_flag = NOT (count <= 3) = False  →  Art. 124F loan-split
        secured_share = min(1.0, 0.55 / 0.75) = min(1.0, 0.73333...) = 0.73333...
        unsecured_share = 1.0 - 0.73333... = 0.26667...
        RW_secured   = 0.20   (Art. 124F preferential rate)
        RW_unsecured = 0.75   (Art. 124L(a) residual rate)
        blended_RW   = 0.20 x 0.73333... + 0.75 x 0.26667... = 0.34667...
        EAD = 200,000
        RWA = 200,000 x 0.34667... = 69,333.33

References:
    - PRA PS1/26 Art. 124E(1)(b): three-property limit for owner-occupied RE.
    - PRA PS1/26 Art. 124E(2): exclusion from owner-occupied path when limit breached.
    - PRA PS1/26 Art. 124E(4): individual housing units counted separately.
    - PRA PS1/26 Art. 124F: owner-occupied residential loan-split (20% / 75%).
    - PRA PS1/26 Art. 124G Table 6B: income-producing residential RW = 0.50 (70-80% LTV).
    - PRA PS1/26 Art. 124L(a): residual/unsecured portion RW = 75%.
    - src/rwa_calc/data/schemas.py: COUNTERPARTY_SCHEMA (qualifying_property_count NEW).
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_RESIDENTIAL_INCOME_LTV_BANDS (RW=0.50).
    - IMPLEMENTATION_PLAN.md: P1.142 entry.

Usage:
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p1_142/p1_142.py
"""

from __future__ import annotations

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
    LOAN_SCHEMA,
    ORG_MAPPING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_BREACH_REF = "CP_P1142_BREACH"
CP_CTRL_REF = "CP_P1142_CTRL"

# Loan references (one per obligor)
LOAN_BREACH_REF = "LN_P1142_BREACH"
LOAN_CTRL_REF = "LN_P1142_CTRL"

# Collateral references (one per loan)
COL_BREACH_REF = "COL_P1142_BREACH"
COL_CTRL_REF = "COL_P1142_CTRL"

# Dates
REPORTING_DATE = date(2027, 1, 2)  # Post Basel 3.1 go-live (1 Jan 2027)
LOAN_MATURITY = date(2052, 1, 2)  # 25-year residential mortgage, SA only

# Economics
EAD_AMOUNT: float = 200_000.0
PROPERTY_LTV: float = 0.75
PRIOR_CHARGE_LTV: float = 0.0

# Three-property limit threshold (Art. 124E(1)(b))
THREE_PROPERTY_LIMIT: int = 3

# Qualifying property counts for the two scenarios
BREACH_PROPERTY_COUNT: int = 4  # > limit → Art. 124G income-producing route
CTRL_PROPERTY_COUNT: int = 3  # <= limit → Art. 124F loan-split route

# Art. 124F loan-split parameters (Basel 3.1)
ART_124F_SPLIT_THRESHOLD: float = 0.55  # portion attracting 20% RW
ART_124F_SECURED_RW: float = 0.20
ART_124L_UNSECURED_RW: float = 0.75

# Art. 124G Table 6B (70-80% LTV band)
ART_124G_RW_70_80: float = 0.50

# Hand-calculated expected outputs (for test-writer reference)
# Breach row:
BREACH_SECURED_SHARE: float = min(1.0, ART_124F_SPLIT_THRESHOLD / PROPERTY_LTV)  # not used
EXPECTED_RW_BREACH: float = ART_124G_RW_70_80  # 0.50
EXPECTED_RWA_BREACH: float = EAD_AMOUNT * EXPECTED_RW_BREACH  # 100,000.00

# Control row:
CTRL_SECURED_SHARE: float = min(1.0, ART_124F_SPLIT_THRESHOLD / PROPERTY_LTV)  # 0.73333...
CTRL_UNSECURED_SHARE: float = 1.0 - CTRL_SECURED_SHARE  # 0.26667...
EXPECTED_RW_CTRL: float = (
    ART_124F_SECURED_RW * CTRL_SECURED_SHARE + ART_124L_UNSECURED_RW * CTRL_UNSECURED_SHARE
)  # 0.34667...
EXPECTED_RWA_CTRL: float = EAD_AMOUNT * EXPECTED_RW_CTRL  # 69,333.33


# ---------------------------------------------------------------------------
# Inline fixture schema (counterparty — qualifying_property_count not yet in schema)
# ---------------------------------------------------------------------------

# Build the counterparty dtype dict from the canonical schema then extend it
# with the new field.  This mirrors the p1_140 pattern for is_under_construction.
_COUNTERPARTY_FIXTURE_SCHEMA: dict[str, pl.DataType] = {
    **dtypes_of(COUNTERPARTY_SCHEMA),
    # NEW field for P1.142 — not yet in COUNTERPARTY_SCHEMA canonical schema.
    # Engine-implementer must add:
    #   "qualifying_property_count": ColumnSpec(pl.Int32, required=False)
    # to COUNTERPARTY_SCHEMA in src/rwa_calc/data/schemas.py.
    "qualifying_property_count": pl.Int32,
}


# ---------------------------------------------------------------------------
# Private dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    Counterparty row for P1.142.

    Both obligors are natural persons (is_natural_person=True) which is a
    pre-condition for the Art. 124E owner-occupied residential treatment path.
    qualifying_property_count is the load-bearing new field: 4 triggers the
    income-producing re-route; 3 stays on the preferential loan-split track.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    is_natural_person: bool
    is_social_housing: bool
    default_status: bool
    qualifying_property_count: int | None

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "is_natural_person": self.is_natural_person,
            "is_social_housing": self.is_social_housing,
            "default_status": self.default_status,
            "qualifying_property_count": self.qualifying_property_count,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Loan row for P1.142 — on-balance-sheet residential mortgage, fully drawn.

    drawn_amount = 200,000 GBP → EAD = 200,000 (interest = 0).
    seniority = "senior": first charge (prior_charge_ltv = 0.0 on collateral).
    product_type = "mortgage": standard retail residential mortgage.
    is_under_construction = False: completed/standing property, not ADC.
    """

    loan_reference: str
    product_type: str
    counterparty_reference: str
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    seniority: str

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
        }


@dataclass(frozen=True)
class _Collateral:
    """
    Collateral row for P1.142 — residential real estate, LTV=0.75, senior first charge.

    is_income_producing is deliberately null/absent: the engine must derive
    the income-producing flag from qualifying_property_count on the counterparty,
    not from a pre-set collateral flag.

    property_ltv = 0.75: falls in the Art. 124G Table 6B 70-80% band → RW=0.50
    for the breach row; stays on Art. 124F loan-split for the control row.

    prior_charge_ltv = 0.0: no prior senior charge — the firm holds a first-rank
    mortgage, so the effective LTV for the split calculation is 0.75 (the gross LTV).

    is_qualifying_re = True: property meets Art. 124 eligibility criteria.
    """

    collateral_reference: str
    collateral_type: str
    beneficiary_type: str
    beneficiary_reference: str
    market_value: float
    property_type: str
    property_ltv: float
    is_qualifying_re: bool
    prior_charge_ltv: float
    is_income_producing: bool | None  # Deliberately null — engine must derive

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
            "prior_charge_ltv": self.prior_charge_ltv,
            "is_income_producing": self.is_income_producing,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1142_counterparties() -> pl.DataFrame:
    """
    Return two P1.142 counterparty rows as a DataFrame.

    CP_P1142_BREACH: natural person, qualifying_property_count=4 → Art. 124E limit
        breached → engine must route to Art. 124G income-producing residential track.
    CP_P1142_CTRL: natural person, qualifying_property_count=3 → limit met →
        engine keeps Art. 124F owner-occupied loan-split track.

    Uses _COUNTERPARTY_FIXTURE_SCHEMA (inline dict) because qualifying_property_count
    is not yet declared in the canonical COUNTERPARTY_SCHEMA.
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_BREACH_REF,
            counterparty_name="P1.142 Natural Person Breach (4 properties)",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            is_social_housing=False,
            default_status=False,
            qualifying_property_count=BREACH_PROPERTY_COUNT,  # 4 — breaches the limit
        ),
        _Counterparty(
            counterparty_reference=CP_CTRL_REF,
            counterparty_name="P1.142 Natural Person Control (3 properties)",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            is_social_housing=False,
            default_status=False,
            qualifying_property_count=CTRL_PROPERTY_COUNT,  # 3 — within the limit
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=_COUNTERPARTY_FIXTURE_SCHEMA)


def create_p1142_loans() -> pl.DataFrame:
    """
    Return two P1.142 loan rows as a DataFrame.

    LN_P1142_BREACH: GBP 200,000 residential mortgage for CP_P1142_BREACH.
        EAD = 200,000 + 0 interest = 200,000.
    LN_P1142_CTRL: GBP 200,000 residential mortgage for CP_P1142_CTRL.
        Both identical economically; only the counterparty's property count differs.
    Conforms to LOAN_SCHEMA.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_BREACH_REF,
            product_type="mortgage",
            counterparty_reference=CP_BREACH_REF,
            maturity_date=LOAN_MATURITY,
            currency="GBP",
            drawn_amount=EAD_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
        _Loan(
            loan_reference=LOAN_CTRL_REF,
            product_type="mortgage",
            counterparty_reference=CP_CTRL_REF,
            maturity_date=LOAN_MATURITY,
            currency="GBP",
            drawn_amount=EAD_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1142_collateral() -> pl.DataFrame:
    """
    Return two P1.142 collateral rows as a DataFrame.

    COL_P1142_BREACH: Residential real-estate collateral securing LN_P1142_BREACH.
        LTV=0.75, prior_charge_ltv=0.0, is_qualifying_re=True.
        is_income_producing=None (null) — the engine must derive this from the
        counterparty's qualifying_property_count, not from the collateral row.

    COL_P1142_CTRL: Identical collateral for LN_P1142_CTRL.
        Same LTV, same null is_income_producing — the discriminating element is
        entirely the counterparty property count (4 vs 3).

    Both rows use dtypes_of(COLLATERAL_SCHEMA) because all collateral columns
    used here (including is_income_producing) are already declared in the schema.
    Conforms to COLLATERAL_SCHEMA.
    """
    rows = [
        _Collateral(
            collateral_reference=COL_BREACH_REF,
            collateral_type="real_estate",
            beneficiary_type="loan",
            beneficiary_reference=LOAN_BREACH_REF,
            market_value=EAD_AMOUNT / PROPERTY_LTV,  # implied property value ≈ 266,667
            property_type="residential",
            property_ltv=PROPERTY_LTV,
            is_qualifying_re=True,
            prior_charge_ltv=PRIOR_CHARGE_LTV,
            is_income_producing=None,  # Deliberately null — engine must derive
        ),
        _Collateral(
            collateral_reference=COL_CTRL_REF,
            collateral_type="real_estate",
            beneficiary_type="loan",
            beneficiary_reference=LOAN_CTRL_REF,
            market_value=EAD_AMOUNT / PROPERTY_LTV,  # implied property value ≈ 266,667
            property_type="residential",
            property_ltv=PROPERTY_LTV,
            is_qualifying_re=True,
            prior_charge_ltv=PRIOR_CHARGE_LTV,
            is_income_producing=None,  # Deliberately null — engine must derive
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p1142_facility_mapping() -> pl.DataFrame:
    """
    Return trivial self-referencing facility-mapping rows as a DataFrame.

    The P1.142 scenario has no facility layer (SA-only, no IRB model).
    Mapping is loan → loan (child_type="loan") with no parent facility,
    expressed as an empty facility mapping.  The hierarchy resolver requires
    this DataFrame to be present (even if empty) for the pipeline to proceed.
    Conforms to FACILITY_MAPPING_SCHEMA.
    """
    return pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1142_lending_mapping() -> pl.DataFrame:
    """Return an empty lending mapping DataFrame (no connected party relationships)."""
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def create_p1142_org_mapping() -> pl.DataFrame:
    """Return an empty org mapping DataFrame (no organisational hierarchy)."""
    return pl.DataFrame(schema=dtypes_of(ORG_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1142_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.142 parquet files and return a mapping of name to path.

    Six parquet files are written:
    - counterparty.parquet      (2 rows: breach + control obligors)
    - loan.parquet              (2 rows: LN_P1142_BREACH, LN_P1142_CTRL)
    - collateral.parquet        (2 rows: COL_P1142_BREACH, COL_P1142_CTRL)
    - facility_mapping.parquet  (0 rows: empty — no facility layer)
    - lending_mapping.parquet   (0 rows: no connected-party relationships)
    - org_mapping.parquet       (0 rows: no organisational hierarchy)

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p1142_counterparties()),
        ("loan", create_p1142_loans()),
        ("collateral", create_p1142_collateral()),
        ("facility_mapping", create_p1142_facility_mapping()),
        ("lending_mapping", create_p1142_lending_mapping()),
        ("org_mapping", create_p1142_org_mapping()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary with column details."""
    print("P1.142 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {df.shape[0]:>3} row(s) x {df.shape[1]:>3} cols  ->  {path.name}")
    print("-" * 80)
    print("Scenario: Art. 124E three-property limit → income-producing RE routing (Basel 3.1)")
    print()
    print(f"  BREACH row  ({CP_BREACH_REF}):")
    print(
        f"    qualifying_property_count = {BREACH_PROPERTY_COUNT}  → limit breached (> {THREE_PROPERTY_LIMIT})"
    )
    print("    → Art. 124G whole-loan, Table 6B LTV 70-80%")
    print(
        f"    EAD = {EAD_AMOUNT:,.2f}  RW = {EXPECTED_RW_BREACH:.4f}  RWA = {EXPECTED_RWA_BREACH:,.2f}"
    )
    print()
    print(f"  CONTROL row ({CP_CTRL_REF}):")
    print(
        f"    qualifying_property_count = {CTRL_PROPERTY_COUNT}  → limit met (<= {THREE_PROPERTY_LIMIT})"
    )
    print("    → Art. 124F loan-split track")
    print(
        f"    secured_share = min(1, {ART_124F_SPLIT_THRESHOLD}/{PROPERTY_LTV}) = {CTRL_SECURED_SHARE:.5f}"
    )
    print(
        f"    blended RW = {ART_124F_SECURED_RW} x {CTRL_SECURED_SHARE:.5f} + {ART_124L_UNSECURED_RW} x {CTRL_UNSECURED_SHARE:.5f} = {EXPECTED_RW_CTRL:.5f}"
    )
    print(
        f"    EAD = {EAD_AMOUNT:,.2f}  RW = {EXPECTED_RW_CTRL:.5f}  RWA = {EXPECTED_RWA_CTRL:,.2f}"
    )
    print()
    print("  Schema note:")
    print("    qualifying_property_count is NEW — not yet in canonical COUNTERPARTY_SCHEMA.")
    print("    Engine-implementer must add:")
    print('      "qualifying_property_count": ColumnSpec(pl.Int32, required=False)')
    print("    to COUNTERPARTY_SCHEMA in src/rwa_calc/data/schemas.py.")
    print("    Engine-implementer must also add B31_RRE_THREE_PROPERTY_LIMIT = 3")
    print("    to src/rwa_calc/data/tables/b31_risk_weights.py.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1142_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
