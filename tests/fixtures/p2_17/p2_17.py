"""
Generate P2.17 fixtures: CRR Art. 123 second subparagraph payroll/pension loan 35% RW.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py CRR branch)

Key responsibilities:
- Produce three counterparty rows: two payroll-loan borrowers (CP_RETAIL_PAY_001,
  CP_RETAIL_PAY_002) and one non-payroll retail borrower (CP_RETAIL_NONPAY_003).
- Produce three loan rows: LOAN_PAY_001 and LOAN_PAY_002 with is_payroll_loan=True,
  LOAN_NONPAY_003 with is_payroll_loan=False.
- No collateral, guarantees, provisions, facilities, or contingents — clean single-factor
  SA test isolating the payroll loan risk weight branch.
- CRR framework only (CalculationConfig.crr()).

Scenario rationale (CRR Art. 123 second subparagraph):

  CRR2 (Regulation (EU) 2019/876, amendment F68) inserted a second subparagraph into
  Art. 123 assigning a 35% risk weight to loans granted to pensioners or employees with
  permanent contracts against unconditional transfer of salary or pension, subject to
  four conditions:
    (a) unconditional payroll/pension deduction authorisation to the credit institution;
    (b) insurance covering death, inability to work, unemployment, or salary/pension reduction;
    (c) aggregate loan payments <= 20% of net monthly salary/pension;
    (d) maximum original maturity of 10 years.

  All three counterparties qualify as retail:
    - entity_type="individual" (is_natural_person=True)
    - country_code=GB
    - no annual_revenue → natural person, revenue threshold irrelevant

  The two payroll loans (LOAN_PAY_001, LOAN_PAY_002) set is_payroll_loan=True and must
  receive a 35% SA risk weight under CRR. The non-payroll loan (LOAN_NONPAY_003) sets
  is_payroll_loan=False and must receive the standard 75% retail risk weight.

  Note: the CRR SA engine branch currently applies 75% flat to all retail exposures and
  does not check is_payroll_loan. This fixture drives the implementation of the missing
  35% payroll branch in the CRR risk weight chain (sa/namespace.py).

Hand-calculation (CRR, CalculationConfig.crr()):

  LOAN_PAY_001 (CP_RETAIL_PAY_001, is_payroll_loan=True):
    Exposure class: RETAIL_OTHER
    EAD = drawn_amount + interest = 50,000 + 0 = 50,000
    SA RW (Art. 123 second subparagraph): 35%
    RWA = 50,000 × 0.35 = 17,500

  LOAN_PAY_002 (CP_RETAIL_PAY_002, is_payroll_loan=True):
    Exposure class: RETAIL_OTHER
    EAD = 25,000 + 0 = 25,000
    SA RW (Art. 123 second subparagraph): 35%
    RWA = 25,000 × 0.35 = 8,750

  LOAN_NONPAY_003 (CP_RETAIL_NONPAY_003, is_payroll_loan=False):
    Exposure class: RETAIL_OTHER
    EAD = 30,000 + 0 = 30,000
    SA RW (Art. 123 first paragraph): 75%
    RWA = 30,000 × 0.75 = 22,500

  Total RWA: 17,500 + 8,750 + 22,500 = 48,750

References:
    - CRR Art. 123 second subparagraph (CRR2, Regulation (EU) 2019/876 F68):
      payroll/pension loan 35% RW conditions (a)-(d)
    - docs/specifications/crr/sa-risk-weights.md §Payroll / Pension Loans (CRR Art. 123, CRR2)
    - src/rwa_calc/engine/sa/namespace.py: CRR retail branch (currently missing payroll check)
    - src/rwa_calc/data/schemas.py: LOAN_SCHEMA is_payroll_loan (line 130)

Usage:
    uv run python tests/fixtures/p2_17/p2_17.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_RETAIL_PAY_001: str = "CP_RETAIL_PAY_001"
CP_RETAIL_PAY_002: str = "CP_RETAIL_PAY_002"
CP_RETAIL_NONPAY_003: str = "CP_RETAIL_NONPAY_003"

LOAN_PAY_001: str = "LOAN_PAY_001"
LOAN_PAY_002: str = "LOAN_PAY_002"
LOAN_NONPAY_003: str = "LOAN_NONPAY_003"

# Counterparty exposure totals (used to verify retail qualifying threshold)
TOTAL_EXPOSURE_PAY_001: float = 50_000.0
TOTAL_EXPOSURE_PAY_002: float = 25_000.0
TOTAL_EXPOSURE_NONPAY_003: float = 30_000.0

# Loan amounts (fully drawn, interest=0 → EAD = drawn_amount)
DRAWN_PAY_001: float = 50_000.0
DRAWN_PAY_002: float = 25_000.0
DRAWN_NONPAY_003: float = 30_000.0

# ---------------------------------------------------------------------------
# Expected outputs — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

#: CRR Art. 123 second subparagraph: payroll/pension loan → 35%
EXPECTED_RW_PAYROLL: float = 0.35

#: CRR Art. 123 first paragraph: standard regulatory retail → 75%
EXPECTED_RW_RETAIL: float = 0.75

EXPECTED_RWA_PAY_001: float = DRAWN_PAY_001 * EXPECTED_RW_PAYROLL  # 17,500
EXPECTED_RWA_PAY_002: float = DRAWN_PAY_002 * EXPECTED_RW_PAYROLL  # 8,750
EXPECTED_RWA_NONPAY_003: float = DRAWN_NONPAY_003 * EXPECTED_RW_RETAIL  # 22,500
EXPECTED_RWA_TOTAL: float = (
    EXPECTED_RWA_PAY_001 + EXPECTED_RWA_PAY_002 + EXPECTED_RWA_NONPAY_003
)  # 48,750


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P2.17 retail counterparty.

    All three counterparties are natural persons (entity_type="individual",
    is_natural_person=True) domiciled in GB — well within the CRR Art. 123
    retail qualifying criteria (individual natural person, no revenue threshold
    concern).  annual_revenue=None (natural persons have no revenue).
    apply_fi_scalar=False: no FIRB 1.25x correlation multiplier.
    is_managed_as_retail=True: explicit flag ensuring retail classification
    (CRR Art. 123 qualifying condition).
    default_status=False: performing exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    is_natural_person: bool
    is_managed_as_retail: bool
    apply_fi_scalar: bool
    default_status: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "is_natural_person": self.is_natural_person,
            "is_managed_as_retail": self.is_managed_as_retail,
            "apply_fi_scalar": self.apply_fi_scalar,
            "default_status": self.default_status,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P2.17 loan row.

    product_type="personal_loan": unsecured personal lending — no real estate
    collateral, no CCF (fully drawn on-balance-sheet).
    is_payroll_loan: True for payroll borrowers → 35% CRR RW (Art. 123 2nd subpara).
    is_payroll_loan: False for non-payroll borrower → 75% CRR RW (Art. 123 1st para).
    seniority=senior: standard senior unsecured claim.
    EAD = drawn_amount + interest = drawn_amount (interest=0 in all three rows).
    """

    loan_reference: str
    product_type: str
    counterparty_reference: str
    currency: str
    drawn_amount: float
    interest: float
    value_date: date
    maturity_date: date
    seniority: str
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "seniority": self.seniority,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p217_counterparties() -> pl.DataFrame:
    """
    Return all P2.17 counterparties as a DataFrame.

    Three natural-person retail counterparties:
      CP_RETAIL_PAY_001  : payroll borrower  — paired with LOAN_PAY_001  (is_payroll_loan=True)
      CP_RETAIL_PAY_002  : payroll borrower  — paired with LOAN_PAY_002  (is_payroll_loan=True)
      CP_RETAIL_NONPAY_003: non-payroll borrower — paired with LOAN_NONPAY_003 (is_payroll_loan=False)

    All three qualify as retail under CRR Art. 123:
    - entity_type="individual" routes through the retail classification branch.
    - is_natural_person=True is consistent with the payroll/pension loan conditions.
    - No annual_revenue: natural persons do not have a revenue threshold check.
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_RETAIL_PAY_001,
            counterparty_name="Payroll Borrower One",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            is_managed_as_retail=True,
            apply_fi_scalar=False,
            default_status=False,
        ),
        _Counterparty(
            counterparty_reference=CP_RETAIL_PAY_002,
            counterparty_name="Payroll Borrower Two",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            is_managed_as_retail=True,
            apply_fi_scalar=False,
            default_status=False,
        ),
        _Counterparty(
            counterparty_reference=CP_RETAIL_NONPAY_003,
            counterparty_name="Standard Retail Borrower Three",
            entity_type="individual",
            country_code="GB",
            is_natural_person=True,
            is_managed_as_retail=True,
            apply_fi_scalar=False,
            default_status=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p217_loans() -> pl.DataFrame:
    """
    Return all P2.17 loan rows as a DataFrame.

    Three personal loans:
      LOAN_PAY_001 : GBP 50,000, is_payroll_loan=True  → EAD=50,000, expected RWA=17,500 (35%)
      LOAN_PAY_002 : GBP 25,000, is_payroll_loan=True  → EAD=25,000, expected RWA=8,750  (35%)
      LOAN_NONPAY_003: GBP 30,000, is_payroll_loan=False → EAD=30,000, expected RWA=22,500 (75%)

    Maturity dates place original maturity at 5 years (PAY_001, NONPAY_003) and 4 years
    (PAY_002) — both within the 10-year maximum for CRR Art. 123 payroll condition (d).
    """
    rows = [
        _Loan(
            loan_reference=LOAN_PAY_001,
            product_type="personal_loan",
            counterparty_reference=CP_RETAIL_PAY_001,
            currency="GBP",
            drawn_amount=DRAWN_PAY_001,
            interest=0.0,
            value_date=date(2026, 1, 15),
            maturity_date=date(2031, 1, 15),
            seniority="senior",
            is_payroll_loan=True,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
        _Loan(
            loan_reference=LOAN_PAY_002,
            product_type="personal_loan",
            counterparty_reference=CP_RETAIL_PAY_002,
            currency="GBP",
            drawn_amount=DRAWN_PAY_002,
            interest=0.0,
            value_date=date(2026, 2, 1),
            maturity_date=date(2030, 2, 1),
            seniority="senior",
            is_payroll_loan=True,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
        _Loan(
            loan_reference=LOAN_NONPAY_003,
            product_type="personal_loan",
            counterparty_reference=CP_RETAIL_NONPAY_003,
            currency="GBP",
            drawn_amount=DRAWN_NONPAY_003,
            interest=0.0,
            value_date=date(2026, 1, 20),
            maturity_date=date(2031, 1, 20),
            seniority="senior",
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory (matches test-writer expected API)
# ---------------------------------------------------------------------------


def build_p2_17_bundle(*, fixtures_dir: Path) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P2.17 scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module; the ``fixtures_dir`` argument is accepted for
    interface symmetry with other bundle builders (it is not used here).

    Returns:
        RawDataBundle with:
        - 3 counterparties (CP_RETAIL_PAY_001, CP_RETAIL_PAY_002, CP_RETAIL_NONPAY_003)
        - 3 loans (LOAN_PAY_001 is_payroll_loan=True, LOAN_PAY_002 is_payroll_loan=True,
          LOAN_NONPAY_003 is_payroll_loan=False)
        - All other LazyFrames: None (loader treats absence as empty)

    Args:
        fixtures_dir: Path to the fixtures directory (unused; accepted for
            interface compatibility with other bundle builders).
    """
    return RawDataBundle(
        facilities=None,
        loans=create_p217_loans().lazy(),
        counterparties=create_p217_counterparties().lazy(),
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
        contingents=None,
        collateral=None,
        guarantees=None,
        provisions=None,
        ratings=None,
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p217_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.17 parquet files and return a mapping of name to path.

    Two parquet files are written:
    - counterparties.parquet (3 rows: CP_RETAIL_PAY_001, CP_RETAIL_PAY_002,
      CP_RETAIL_NONPAY_003)
    - loans.parquet          (3 rows: LOAN_PAY_001, LOAN_PAY_002, LOAN_NONPAY_003)

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
        ("counterparties", create_p217_counterparties()),
        ("loans", create_p217_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.17 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<25} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: CRR Art. 123 second subparagraph — payroll/pension loan 35% RW")
    print()
    print("  Payroll loans (is_payroll_loan=True) — Art. 123 second subparagraph:")
    print(f"    LOAN_PAY_001  EAD={DRAWN_PAY_001:>10,.0f}  RW={EXPECTED_RW_PAYROLL:.0%}  "
          f"RWA={EXPECTED_RWA_PAY_001:>10,.0f}")
    print(f"    LOAN_PAY_002  EAD={DRAWN_PAY_002:>10,.0f}  RW={EXPECTED_RW_PAYROLL:.0%}  "
          f"RWA={EXPECTED_RWA_PAY_002:>10,.0f}")
    print()
    print("  Standard retail loan (is_payroll_loan=False) — Art. 123 first paragraph:")
    print(f"    LOAN_NONPAY_003  EAD={DRAWN_NONPAY_003:>10,.0f}  RW={EXPECTED_RW_RETAIL:.0%}  "
          f"RWA={EXPECTED_RWA_NONPAY_003:>10,.0f}")
    print()
    print(f"  Total RWA: {EXPECTED_RWA_TOTAL:>12,.0f}")

    # Verify is_payroll_loan column is present in loans parquet
    loans_df = pl.read_parquet(saved["loans"])
    if "is_payroll_loan" in loans_df.columns:
        vals = loans_df["is_payroll_loan"].to_list()
        print(f"\n  is_payroll_loan values in loans parquet: {vals}")
    else:
        print("\n  WARNING: is_payroll_loan column missing from loans parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p217_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
