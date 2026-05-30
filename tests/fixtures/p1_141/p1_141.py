"""
Generate P1.141 fixtures: Art. 124(4) all-or-nothing qualifying gate for mixed RE.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (classifier.py / hierarchy.py / re_splitter.py)

Key responsibilities:
- Produce one counterparty row (CP-P1141): corporate, unrated, non-NP, non-SME.
- Produce one loan row (LN-P1141): SA, mortgage product, drawn GBP 2,000,000.
- Produce one facility row (FAC-P1141): committed senior facility, GBP 2,000,000.
- Produce two collateral rows linked to LN-P1141:
    COL-P1141-R: residential, market_value=1,500,000, is_qualifying_re=True
    COL-P1141-C: commercial, market_value=1,000,000, is_qualifying_re=False
- Produce trivial self-referencing facility_mapping, empty lending_mapping, org_mapping.

Scenario design — Art. 124(4) all-or-nothing qualifying gate (Basel 3.1 / PRA PS1/26):
    Art. 124(4) makes Art. 124J (Other RE) the default for mixed-use RE exposures.
    The preferential Art. 124F-124I tables apply ONLY if both the residential
    component AND the commercial component separately qualify under Art. 124A(1).
    If either component fails Art. 124A(1), BOTH components fall to Art. 124J —
    the "all-or-nothing" gate.

    In this scenario the commercial component has is_qualifying_re=False (e.g. a
    valuation-independence breach under Art. 124A(1)(c)). The residential component
    qualifies (is_qualifying_re=True). Because the commercial component fails the gate,
    BOTH components must use Art. 124J (Other RE), not the preferential Art. 124F/124H.

    The pro-rata EAD split (Art. 124(4)) still applies:
        V_RESI = 1,500,000 (60%); V_CRE = 1,000,000 (40%); V_total = 2,500,000
        EAD_RESI = 2,000,000 × 0.60 = 1,200,000
        EAD_CRE  = 2,000,000 × 0.40 =   800,000

    Art. 124J risk weight derivation (counterparty RW = 100%, corporate unrated):
        RESI component (non-income-dependent): RW = cp_rw = 1.00
        CRE component (non-income-dependent):  RW = max(0.60, cp_rw) = max(0.60, 1.00) = 1.00
        RWA_RESI = 1,200,000 × 1.00 = 1,200,000
        RWA_CRE  =   800,000 × 1.00 =   800,000
        RWA_total = 2,000,000

    Load-bearing input: the DIFFERING per-row is_qualifying_re values
    (residential True, commercial False). The is_qualifying_re column already
    exists on COLLATERAL_SCHEMA — no new fixture column is needed.

    Pre-fix contrast (for delta intuition — NOT asserted in acceptance tests):
        Without the gate, the residential component would receive the Art. 124F
        preferential RRE RW. At LTV 60% (= 1,200,000/2,000,000 effective on RESI):
            Cap = 0.55 × V_RESI = 825,000 → 20% band; residual 375,000 → 100%
            Pre-fix RWA_RESI ≈ 825,000×0.20 + 375,000×1.00 = 540,000
            Pre-fix RWA_CRE  = 800,000×1.00 = 800,000
            Pre-fix RWA_total ≈ 1,340,000
        Post-fix (gate enforced): RWA_total = 2,000,000 (+660,000).

Expected outputs (post-fix, CalculationConfig.basel_3_1()):
    split_parent_id = LN-P1141
    child rows: secured_rre (EAD=1,200,000, RW=1.00), secured_cre (EAD=800,000, RW=1.00),
                residual (EAD=0.0)
    RWA_total = 2,000,000.0
    sum(child EAD) == parent EAD == 2,000,000

References:
    - PRA PS1/26 Art. 124(4): all-or-nothing Art. 124J fallback for mixed RE (ps126app1.pdf p.51)
    - PRA PS1/26 Art. 124A(1): six-criterion qualifying gate (p.51)
    - PRA PS1/26 Art. 124J: Other RE RW (p.57-58)
    - PRA PS1/26 Art. 124F: RRE preferential RW table (p.55)
    - data/tables/b31_risk_weights.py: B31_OTHER_RE_CRE_FLOOR_RW=0.60,
      B31_CORPORATE_RISK_WEIGHTS[None]=1.00
    - docs/specifications/basel31/sa-risk-weights.md §"Mixed Real Estate Split (Art.124(4))"
      L1277-1346; known limitation L1338-1339

Usage:
    /home/philm/projects/rwa_calculator/.venv/bin/python tests/fixtures/p1_141/p1_141.py
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
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    ORG_MAPPING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty reference
COUNTERPARTY_REF: str = "CP-P1141"

# Facility and loan references
FACILITY_REF: str = "FAC-P1141"
LOAN_REF: str = "LN-P1141"

# Collateral references
COLLATERAL_REF_RESI: str = "COL-P1141-R"   # Residential — is_qualifying_re=True
COLLATERAL_REF_CRE: str = "COL-P1141-C"    # Commercial  — is_qualifying_re=False

# Dates — post Basel 3.1 go-live (1 Jan 2027)
REPORTING_DATE: date = date(2027, 1, 2)
MATURITY_DATE: date = date(2035, 6, 30)

# Loan economics
DRAWN_AMOUNT: float = 2_000_000.0

# Collateral values
RESI_MARKET_VALUE: float = 1_500_000.0    # 60% of total
CRE_MARKET_VALUE: float = 1_000_000.0     # 40% of total
TOTAL_COLLATERAL_VALUE: float = 2_500_000.0

# EAD split (pro-rata by collateral value per Art. 124(4))
RESI_SHARE: float = RESI_MARKET_VALUE / TOTAL_COLLATERAL_VALUE  # 0.60
CRE_SHARE: float = CRE_MARKET_VALUE / TOTAL_COLLATERAL_VALUE    # 0.40
EAD_RESI: float = DRAWN_AMOUNT * RESI_SHARE    # 1_200_000
EAD_CRE: float = DRAWN_AMOUNT * CRE_SHARE      # 800_000

# ---------------------------------------------------------------------------
# Expected outputs (post-fix, authoritative — test-writer must assert these)
# ---------------------------------------------------------------------------

#: Art. 124J RW for residential component (non-income-dependent, cp_rw=1.00)
EXPECTED_RW_RESI: float = 1.00

#: Art. 124J RW for CRE component (non-income-dependent, max(0.60, cp_rw=1.00))
EXPECTED_RW_CRE: float = 1.00

#: RWA for residential child row
EXPECTED_RWA_RESI: float = EAD_RESI * EXPECTED_RW_RESI  # 1_200_000.0

#: RWA for CRE child row
EXPECTED_RWA_CRE: float = EAD_CRE * EXPECTED_RW_CRE     # 800_000.0

#: Total RWA (parent) — sum of child RWA + residual (0)
EXPECTED_RWA_TOTAL: float = EXPECTED_RWA_RESI + EXPECTED_RWA_CRE  # 2_000_000.0

#: Total EAD (parent) — drawn_amount
EXPECTED_EAD_TOTAL: float = DRAWN_AMOUNT  # 2_000_000.0

#: Residual EAD = 0 (entire EAD allocated to secured components)
EXPECTED_EAD_RESIDUAL: float = 0.0

# Art. 124J CRE floor (B31_OTHER_RE_CRE_FLOOR_RW) — informational
ART_124J_CRE_FLOOR_RW: float = 0.60


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    Counterparty row for P1.141.

    Corporate, unrated (external_cqs=null → RW 100% under B31 Art. 122(2) Table 6).
    Non-NP, non-SME: ensures residual-class RW = 100% and the Art. 124J fallback
    for both CRE and RESI components gives a clean RWA = 2,000,000.

    annual_revenue=None signals unrated/no-CQS corporate — the engine must not
    force SME or large-corporate treatment from revenue alone.
    """

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
    Facility row for P1.141.

    Committed senior mortgage facility of GBP 2,000,000 against CP-P1141.
    product_type=mortgage routes the exposure through the RE classification path.
    is_defaulted=False, is_adc=False (via collateral default): standard performing
    mixed RE under Art. 124(4).
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
        }


@dataclass(frozen=True)
class _Loan:
    """
    Loan row for P1.141.

    Drawn amount GBP 2,000,000 against CP-P1141 under FAC-P1141.
    product_type=mortgage routes through RE classification.
    has_income_cover=False (via is_income_producing=False on both collateral rows):
    non-income-producing mixed RE, so Art. 124(4) pro-rata split applies (not
    Art. 124G/124I whole-loan income-dependent path).
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
    Collateral row for P1.141.

    Two rows — one residential (qualifying), one commercial (non-qualifying).

    The is_qualifying_re field is the load-bearing column for this scenario:
      - Residential (COL-P1141-R): is_qualifying_re=True  — Art. 124A satisfied
      - Commercial  (COL-P1141-C): is_qualifying_re=False — Art. 124A FAILED

    Because the commercial component fails, Art. 124(4) forces BOTH components
    through Art. 124J (Other RE) instead of the preferential Art. 124F/124H tables.

    is_income_producing=False on both rows: non-income-producing mixed RE.
    is_adc=False: not an ADC exposure.
    prior_charge_ltv=0.0: no prior charge.
    """

    collateral_reference: str
    beneficiary_type: str
    beneficiary_reference: str
    property_type: str
    market_value: float
    is_qualifying_re: bool
    is_income_producing: bool
    is_adc: bool
    prior_charge_ltv: float

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "property_type": self.property_type,
            "market_value": self.market_value,
            "is_qualifying_re": self.is_qualifying_re,
            "is_income_producing": self.is_income_producing,
            "is_adc": self.is_adc,
            "prior_charge_ltv": self.prior_charge_ltv,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1141_counterparty() -> pl.DataFrame:
    """
    Return the P1.141 counterparty as a single-row DataFrame.

    CP-P1141: unrated corporate, non-NP, non-SME.

    entity_type="corporate" maps to the corporate SA exposure class.
    No annual_revenue (null) → no SME treatment; no external CQS → RW 100%.
    is_natural_person=False ensures the residual class uses the standard
    corporate RW (not the Art. 124L 75%/85% NP retail or SME retail band).
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P1.141 Mixed RE Corporate Borrower Ltd",
            entity_type="corporate",
            country_code="GB",
            is_natural_person=False,
            annual_revenue=None,
            default_status=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1141_facility() -> pl.DataFrame:
    """
    Return the P1.141 facility as a single-row DataFrame.

    FAC-P1141: committed senior mortgage facility, GBP 2,000,000, matures 2035-06-30.
    product_type=mortgage routes through the RE classification branch in the engine.
    """
    rows = [
        _Facility(
            facility_reference=FACILITY_REF,
            product_type="mortgage",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=REPORTING_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1141_loan() -> pl.DataFrame:
    """
    Return the P1.141 loan as a single-row DataFrame.

    LN-P1141: fully drawn mortgage loan, GBP 2,000,000.
    EAD = drawn_amount = 2,000,000 (no undrawn commitment).

    interest=0.0: not relevant to the qualifying-gate test.
    The collateral rows (is_income_producing=False) ensure the exposure takes
    the non-income-producing Art. 124(4) split path, not the Art. 124G/124I
    income-dependent whole-loan path.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            product_type="mortgage",
            counterparty_reference=COUNTERPARTY_REF,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1141_collateral() -> pl.DataFrame:
    """
    Return the P1.141 collateral as a two-row DataFrame.

    COL-P1141-R (Residential):
      property_type="residential", market_value=1,500,000, is_qualifying_re=True.
      This component satisfies Art. 124A(1) on its own — preferential Art. 124F
      would apply to it if the gate were not triggered by the commercial component.

    COL-P1141-C (Commercial):
      property_type="commercial", market_value=1,000,000, is_qualifying_re=False.
      This component FAILS Art. 124A(1) (e.g. valuation-independence breach).
      Under Art. 124(4) this failure triggers the all-or-nothing gate: BOTH
      components drop to Art. 124J, wiping the residential 20% band.

    Both rows:
      beneficiary_type="loan", beneficiary_reference="LN-P1141".
      is_income_producing=False: non-income-producing RE.
      is_adc=False: not ADC.
      prior_charge_ltv=0.0: no prior charge.

    Schema: dtypes_of(COLLATERAL_SCHEMA) — is_qualifying_re already declared
    as an optional Boolean (default=True). Both values supplied explicitly so
    the engine reads the per-row signal without any coalescing.
    """
    rows = [
        # ===================================================================
        # COL-P1141-R: Residential component — QUALIFIES under Art. 124A(1).
        # is_qualifying_re=True. Without the gate this would use Art. 124F (20%
        # LTV-split band). Post-fix with gate active it uses Art. 124J instead.
        # ===================================================================
        _Collateral(
            collateral_reference=COLLATERAL_REF_RESI,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            property_type="residential",
            market_value=RESI_MARKET_VALUE,       # 1,500,000 (60% of total)
            is_qualifying_re=True,
            is_income_producing=False,
            is_adc=False,
            prior_charge_ltv=0.0,
        ),
        # ===================================================================
        # COL-P1141-C: Commercial component — FAILS Art. 124A(1).
        # is_qualifying_re=False. This failure triggers the Art. 124(4) gate,
        # forcing BOTH components to Art. 124J (Other RE, non-income-dependent).
        # RW = max(0.60, cp_rw) = max(0.60, 1.00) = 1.00.
        # ===================================================================
        _Collateral(
            collateral_reference=COLLATERAL_REF_CRE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            property_type="commercial",
            market_value=CRE_MARKET_VALUE,        # 1,000,000 (40% of total)
            is_qualifying_re=False,
            is_income_producing=False,
            is_adc=False,
            prior_charge_ltv=0.0,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p1141_facility_mapping() -> pl.DataFrame:
    """
    Return a trivial self-referencing facility mapping as a single-row DataFrame.

    FAC-P1141 → LN-P1141 (loan child): satisfies the hierarchy resolver without
    introducing cross-facility relationships.
    """
    rows = [
        {
            "parent_facility_reference": FACILITY_REF,
            "child_reference": LOAN_REF,
            "child_type": "loan",
        }
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1141_lending_mapping() -> pl.DataFrame:
    """Return an empty lending mapping DataFrame (no connected party relationships)."""
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def create_p1141_org_mapping() -> pl.DataFrame:
    """Return an empty org mapping DataFrame (no organisational hierarchy)."""
    return pl.DataFrame(schema=dtypes_of(ORG_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1141_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.141 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet    — 1 row  (CP-P1141, corporate unrated)
        facility.parquet        — 1 row  (FAC-P1141, mortgage GBP 2m)
        loan.parquet            — 1 row  (LN-P1141, drawn GBP 2m)
        collateral.parquet      — 2 rows (COL-P1141-R residential, COL-P1141-C commercial)
        facility_mapping.parquet — 1 row (FAC-P1141 → LN-P1141)
        lending_mapping.parquet — 0 rows
        org_mapping.parquet     — 0 rows

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1141_counterparty()),
        ("facility", create_p1141_facility()),
        ("loan", create_p1141_loan()),
        ("collateral", create_p1141_collateral()),
        ("facility_mapping", create_p1141_facility_mapping()),
        ("lending_mapping", create_p1141_lending_mapping()),
        ("org_mapping", create_p1141_org_mapping()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.141 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: Art. 124(4) all-or-nothing qualifying gate — mixed RE")
    print(f"  Counterparty:  {COUNTERPARTY_REF} (corporate, unrated, non-NP, GB)")
    print(f"  Facility:      {FACILITY_REF}  GBP {DRAWN_AMOUNT:,.0f}  (mortgage)")
    print(f"  Loan:          {LOAN_REF}  drawn GBP {DRAWN_AMOUNT:,.0f}")
    print()
    print("  Collateral:")
    print(f"    {COLLATERAL_REF_RESI}  residential  MV={RESI_MARKET_VALUE:>12,.0f}"
          f"  share={RESI_SHARE:.0%}  is_qualifying_re=True")
    print(f"    {COLLATERAL_REF_CRE }  commercial   MV={CRE_MARKET_VALUE:>12,.0f}"
          f"  share={CRE_SHARE:.0%}  is_qualifying_re=False  <- gate trigger")
    print()
    print("  Gate: commercial is_qualifying_re=False → Art. 124(4) all-or-nothing")
    print("        BOTH components → Art. 124J (Other RE), not Art. 124F/124H")
    print()
    print("  Expected outputs (post-fix, CalculationConfig.basel_3_1()):")
    print(f"    EAD_RESI = {EAD_RESI:>12,.0f}  RW = {EXPECTED_RW_RESI:.2f}"
          f"  RWA_RESI = {EXPECTED_RWA_RESI:>12,.0f}")
    print(f"    EAD_CRE  = {EAD_CRE:>12,.0f}  RW = {EXPECTED_RW_CRE:.2f}"
          f"  RWA_CRE  = {EXPECTED_RWA_CRE:>12,.0f}")
    print(f"    RWA_total= {EXPECTED_RWA_TOTAL:>12,.0f}  EAD_total= {EXPECTED_EAD_TOTAL:>12,.0f}")
    print(f"    residual EAD = {EXPECTED_EAD_RESIDUAL:.1f}")
    print()
    print("  Art. 124J CRE floor (B31_OTHER_RE_CRE_FLOOR_RW) = "
          f"{ART_124J_CRE_FLOOR_RW:.0%}")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1141_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
