"""
Generate P1.104 fixtures: CRR Art. 239(1) FCSM maturity-mismatch eligibility.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/simple_method.py)

Key responsibilities:
- Produce one counterparty row: corporate, GBP, cqs=4, no FSE flag.
- Produce two loan rows: both LN_P1104_COMPLIANT and LN_P1104_MISMATCH share the
  same counterparty (CP_P1104), currency (GBP), drawn_amount=1,000,000, and a
  5-year residual maturity (value_date=2026-01-01, maturity_date=2031-01-01).
- Produce two collateral rows: COLL_P1104_OK (residual_maturity_years=6.0, linked to
  LN_P1104_COMPLIANT) and COLL_P1104_SHORT (residual_maturity_years=3.0, linked to
  LN_P1104_MISMATCH).  Both are corporate bonds with issuer_cqs=2,
  is_eligible_financial_collateral=True.
- Config: approach=standardised, crm_collateral_method=SIMPLE, is_basel_3_1=False.

Scenario rationale (CRR Art. 239(1)):
    FCSM eligibility requires the collateral residual maturity to be >= the exposure
    residual maturity. When collateral residual maturity < exposure residual maturity
    the entire collateral row is ineligible — FCSM does NOT apply a partial
    maturity-adjustment formula (that formula, Art. 239(2), applies to FCCM/IRB only).
    The eligibility test is binary (strict "less than").

    Case A (compliant): COLL_P1104_OK has residual_maturity_years=6.0 >= 5.0y exposure
        → collateral recognised, FCSM blended RW = 0.50
        → RWA = 1,000,000 * 0.50 = 500,000

    Case B (mismatch): COLL_P1104_SHORT has residual_maturity_years=3.0 < 5.0y exposure
        → collateral excluded (Art. 239(1))
        → unsecured corporate CQS 4 RW = 1.00
        → RWA = 1,000,000 * 1.00 = 1,000,000

Hand-calculation (CRR, CalculationConfig.crr(), FCSM method):
    Exposure residual maturity: (2031-01-01 - 2026-01-01) / 365 ≈ 5.0 years

    Case A — compliant maturity (6.0 >= 5.0):
        maturity_eligibility = True
        collateral_recognised = 1,000,000
        fcsm_item_rw = max(FCSM_RW_FLOOR=0.20, issuer_cqs2_rw=0.50) = 0.50
        fcsm_collateral_value = min(1,000,000, EAD=1,000,000) = 1,000,000
        secured_pct = 1.00, unsecured_pct = 0.00
        blended_rw = 1.00 * 0.50 + 0.00 * 1.00 = 0.50
        RWA = 1,000,000 * 0.50 = 500,000

    Case B — mismatch (3.0 < 5.0):
        maturity_eligibility = False  (Art. 239(1))
        collateral_recognised = 0
        secured_pct = 0.00, unsecured_pct = 1.00
        blended_rw = 0.00 + 1.00 * 1.00 = 1.00
        RWA = 1,000,000 * 1.00 = 1,000,000

Regulatory references:
    - CRR Art. 239(1): collateral ineligible when residual maturity < exposure maturity.
    - CRR Art. 222(3): FCSM_RW_FLOOR = 20% (src/rwa_calc/data/tables/crr_simple_method.py:24).
    - CRR Art. 122 Table 5: corporate CQS 4 = 100% (unsecured), CQS 2 = 50%.
    - docs/specifications/crr/credit-risk-mitigation.md lines 827-838.

Usage:
    uv run python tests/fixtures/p1_104_art_239_1_fcsm_maturity/p1_104.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_P1104"

LOAN_REF_COMPLIANT = "LN_P1104_COMPLIANT"
LOAN_REF_MISMATCH = "LN_P1104_MISMATCH"

COLLATERAL_REF_OK = "COLL_P1104_OK"
COLLATERAL_REF_SHORT = "COLL_P1104_SHORT"

VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2031, 1, 1)  # residual ≈ 5.0 years from VALUE_DATE

# Exposure residual maturity in years (approximate — used in hand-calc only)
EXPOSURE_RESIDUAL_MATURITY_YEARS: float = (MATURITY_DATE - VALUE_DATE).days / 365.0  # ≈ 5.0

DRAWN_AMOUNT = 1_000_000.0

# Collateral parameters
COLLATERAL_MARKET_VALUE = 1_000_000.0
ISSUER_CQS = 2
ISSUER_TYPE = "corporate"
COLLATERAL_TYPE = "bond"

# Compliant collateral: residual maturity EXCEEDS exposure (Art. 239(1) satisfied)
COLL_OK_RESIDUAL_MATURITY_YEARS: float = 6.0

# Mismatched collateral: residual maturity BELOW exposure (Art. 239(1) violated)
COLL_SHORT_RESIDUAL_MATURITY_YEARS: float = 3.0

# Expected outputs (for test-writer assertions)
# Corporate CQS 4 → unsecured RW = 1.00 (CRR Art. 122 Table 5)
CORPORATE_CQS4_RW: float = 1.00
# Corporate CQS 2 → FCSM item RW = max(0.20 floor, 0.50) = 0.50 (CRR Art. 222(3))
FCSM_RW_FLOOR: float = 0.20
CORPORATE_CQS2_RW: float = 0.50
FCSM_ITEM_RW: float = max(FCSM_RW_FLOOR, CORPORATE_CQS2_RW)  # = 0.50

# Case A: compliant — collateral fully recognised
EXPECTED_FCSM_COLLATERAL_VALUE_A: float = COLLATERAL_MARKET_VALUE  # 1,000,000
EXPECTED_FCSM_COLLATERAL_RW_A: float = FCSM_ITEM_RW  # 0.50
EXPECTED_RISK_WEIGHT_A: float = 0.50  # blended: 1.00 * 0.50 + 0.00 * 1.00
EXPECTED_RWA_A: float = DRAWN_AMOUNT * EXPECTED_RISK_WEIGHT_A  # 500,000

# Case B: mismatch — collateral excluded, unsecured corporate CQS 4 RW
EXPECTED_FCSM_COLLATERAL_VALUE_B: float = 0.0
EXPECTED_FCSM_COLLATERAL_RW_B: float = 0.0
EXPECTED_RISK_WEIGHT_B: float = CORPORATE_CQS4_RW  # 1.00
EXPECTED_RWA_B: float = DRAWN_AMOUNT * EXPECTED_RISK_WEIGHT_B  # 1,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.104 counterparty: unrated corporate, GBP, CQS 4, not FSE.

    entity_type=corporate ensures SA corporate risk weight table is used.
    cqs=4 is carried in the ratings row (no cqs field on COUNTERPARTY_SCHEMA
    directly, but the external rating row supplies CQS 4 → corporate RW=100%).
    is_financial_sector_entity=False so no FSE RW uplift applies (Art. 122).
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.104 loan: GBP 1,000,000 drawn, 5-year maturity (2026-01-01 to 2031-01-01).

    Both loans share the same counterparty (CP_P1104) and date window so that
    the only variable between Case A and Case B is the collateral maturity.
    interest=0 → EAD = drawn_amount = 1,000,000 exactly.
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
class _Collateral:
    """
    P1.104 collateral: corporate bond, GBP, issuer_cqs=2, market_value=1,000,000.

    Two instances are created with different residual_maturity_years to test
    the Art. 239(1) binary eligibility gate.

    COLL_P1104_OK:    residual_maturity_years=6.0 (>= 5.0y exposure → eligible)
    COLL_P1104_SHORT: residual_maturity_years=3.0 (<  5.0y exposure → ineligible)
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_type: str
    issuer_cqs: int
    residual_maturity_years: float
    is_eligible_financial_collateral: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_type": self.issuer_type,
            "issuer_cqs": self.issuer_cqs,
            "residual_maturity_years": self.residual_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1104_counterparty() -> pl.DataFrame:
    """
    Return the P1.104 counterparty as a single-row DataFrame.

    Corporate, GB, no FSE flag, not defaulted.  CQS 4 is conveyed by the
    external rating row (ratings are loaded separately by the engine).
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="FCSM Maturity Mismatch Test Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1104_loans() -> pl.DataFrame:
    """
    Return the two P1.104 loan rows as a DataFrame (one per case).

    LN_P1104_COMPLIANT: links to COLL_P1104_OK (compliant maturity — eligible).
    LN_P1104_MISMATCH:  links to COLL_P1104_SHORT (short maturity — ineligible).
    Both loans: GBP 1,000,000, 2026-01-01 to 2031-01-01, interest=0.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF_COMPLIANT,
            counterparty_reference=COUNTERPARTY_REF,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
        _Loan(
            loan_reference=LOAN_REF_MISMATCH,
            counterparty_reference=COUNTERPARTY_REF,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1104_collateral() -> pl.DataFrame:
    """
    Return the two P1.104 collateral rows as a DataFrame.

    COLL_P1104_OK:    residual_maturity_years=6.0 >= 5.0y exposure → Art. 239(1) met.
    COLL_P1104_SHORT: residual_maturity_years=3.0 <  5.0y exposure → Art. 239(1) violated.

    Both rows: bond, GBP, market_value=1,000,000, issuer_cqs=2 (corporate issuer).
    is_eligible_financial_collateral=True so the FCSM eligibility gate is reached
    (the maturity check is the final gate, not the first).
    """
    rows = [
        _Collateral(
            collateral_reference=COLLATERAL_REF_OK,
            collateral_type="bond",
            currency="GBP",
            market_value=COLLATERAL_MARKET_VALUE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_COMPLIANT,
            issuer_type=ISSUER_TYPE,
            issuer_cqs=ISSUER_CQS,
            residual_maturity_years=COLL_OK_RESIDUAL_MATURITY_YEARS,
            is_eligible_financial_collateral=True,
        ),
        _Collateral(
            collateral_reference=COLLATERAL_REF_SHORT,
            collateral_type="bond",
            currency="GBP",
            market_value=COLLATERAL_MARKET_VALUE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_MISMATCH,
            issuer_type=ISSUER_TYPE,
            issuer_cqs=ISSUER_CQS,
            residual_maturity_years=COLL_SHORT_RESIDUAL_MATURITY_YEARS,
            is_eligible_financial_collateral=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1104_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.104 parquet files and return a mapping of name -> path.

    Three parquet files are written:
    - counterparty.parquet   (1 row: CP_P1104)
    - loan.parquet           (2 rows: LN_P1104_COMPLIANT, LN_P1104_MISMATCH)
    - collateral.parquet     (2 rows: COLL_P1104_OK, COLL_P1104_SHORT)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1104_counterparty()),
        ("loan", create_p1104_loans()),
        ("collateral", create_p1104_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.104 fixture generation complete")
    print("-" * 72)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 72)
    print("Scenario: CRR Art. 239(1) — FCSM binary maturity-mismatch eligibility")
    print(f"  Exposure:            CP_P1104, GBP {DRAWN_AMOUNT:,.0f}, CQS 4, corporate")
    print(
        f"  Exposure maturity:   {VALUE_DATE} -> {MATURITY_DATE} (~{EXPOSURE_RESIDUAL_MATURITY_YEARS:.2f}y)"
    )
    print("")
    print(
        f"  Case A (compliant):  COLL_P1104_OK,    residual={COLL_OK_RESIDUAL_MATURITY_YEARS:.1f}y >= {EXPOSURE_RESIDUAL_MATURITY_YEARS:.1f}y exposure"
    )
    print("    maturity_eligibility = True")
    print(f"    fcsm_item_rw = max({FCSM_RW_FLOOR}, {CORPORATE_CQS2_RW}) = {FCSM_ITEM_RW:.2f}")
    print(f"    risk_weight  = {EXPECTED_RISK_WEIGHT_A:.2f}")
    print(f"    RWA          = {EXPECTED_RWA_A:,.0f}")
    print("")
    print(
        f"  Case B (mismatch):   COLL_P1104_SHORT, residual={COLL_SHORT_RESIDUAL_MATURITY_YEARS:.1f}y < {EXPOSURE_RESIDUAL_MATURITY_YEARS:.1f}y exposure"
    )
    print("    maturity_eligibility = False  (Art. 239(1) ineligible)")
    print("    fcsm_collateral_value = 0")
    print(f"    risk_weight  = {EXPECTED_RISK_WEIGHT_B:.2f}")
    print(f"    RWA          = {EXPECTED_RWA_B:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1104_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
