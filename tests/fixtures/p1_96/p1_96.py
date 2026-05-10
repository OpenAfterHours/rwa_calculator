"""
Generate P1.96 fixtures: covered-bond collateral haircut routing.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/haircuts.py)

Scenario design:
    Two paired CRR runs exercise the Art. 197 / Art. 207(2) ineligibility split
    for covered-bond collateral used with the Financial Collateral Comprehensive
    Method (FCSM, CRR Art. 223-226).

    Run A — non-repo term loan (exposure_is_sft=False):
        The engine must detect that covered_bond is ineligible financial collateral
        under Art. 197 (covered bonds are not in the Art. 197 eligible list for
        non-SFT exposures).  is_eligible_financial_collateral is set True by the
        client but the engine should override it to False for non-SFT paths.
        liquidation_period_days=20 (default non-SFT supervisory period).

        Hand-calc (CRR Art. 224 Table 1, corp-bond CQS 1, 1–5y band):
            H_n = 4% (base 10-day haircut)
            T_m = 20 days (non-SFT supervisory period)
            H_m = 0.04 × sqrt(20/10) = 0.04 × 1.41421356 = 0.05656854
            FX haircut = 0 (GBP/GBP)
            C_adj = 600_000 × (1 − 0.05656854) = 566_057.14
            E* = max(0, 1_000_000 − 566_057.14) = 433_942.86

        Note: whether the engine applies FCSM at all for Run A depends on
        Art. 197 eligibility logic.  The hand-calc above reflects the post-fix
        path where covered_bond routes correctly via the corp-bond table.
        The pre-fix bug routes covered_bond to 'other_physical' (40% base).

    Run B — repo (exposure_is_sft=True):
        Under Art. 207(2) repos may use a wider set of eligible collateral,
        including covered bonds. The engine must route this to FCSM with the
        SFT 5-day supervisory liquidation period.
        liquidation_period_days=5 (SFT supervisory period).

        Hand-calc (CRR Art. 224 Table 1, corp-bond CQS 1, 1–5y band):
            H_n = 4%
            T_m = 5 days (SFT period, Art. 224(2)(c))
            H_m = 0.04 × sqrt(5/10) = 0.04 × 0.70710678 = 0.02828427
            FX haircut = 0 (GBP/GBP)
            C_adj = 600_000 × (1 − 0.02828427) = 583_029.44
            E* = max(0, 1_000_000 − 583_029.44) = 416_970.56

        Pre-fix bug: routes covered_bond to 'other_physical' (40% base) →
            H_m = 0.40 × sqrt(5/10) ≈ 0.28284271
            C_adj ≈ 430_294.37
            E* ≈ 569_705.63

    Reporting date: 2026-01-01.
    Both facilities mature 2027-06-30 (residual ≈ 1.5y → 1–5y haircut band).

References:
    - CRR Art. 197:    Eligible financial collateral (non-SFT)
    - CRR Art. 207(2): Extended eligible collateral for SFTs (repos)
    - CRR Art. 223:    Financial Collateral Comprehensive Method (FCSM)
    - CRR Art. 224 Table 1: Supervisory haircut schedule (covered_bond → corp-bond band)
    - CRR Art. 226:    Liquidation-period scaling sqrt(T_m / 10)

Usage:
    uv run python tests/fixtures/p1_96/p1_96.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_P196"

# Run A — non-repo term loan
FACILITY_REF_A = "FAC_P196_A"
LOAN_REF_A = "LOAN_P196_A"
COLLATERAL_REF_A = "COLL_P196_A"

# Run B — repo (SFT)
FACILITY_REF_B = "FAC_P196_B"
LOAN_REF_B = "LOAN_P196_B"
COLLATERAL_REF_B = "COLL_P196_B"

REPORTING_DATE = date(2026, 1, 1)
VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2027, 6, 30)  # residual ≈ 1.5y from reporting date

# Collateral parameters
MARKET_VALUE: float = 600_000.0
NOMINAL_VALUE: float = 600_000.0
DRAWN_AMOUNT: float = 1_000_000.0

# CRR Art. 224 Table 1: covered_bond routes to corp-bond band
# CQS 1, 1-5y residual maturity → H_n = 4%
H_N: float = 0.04  # Base 10-day haircut

# Run A — non-SFT, 20-day supervisory liquidation period
LIQ_PERIOD_A: int = 20
H_M_A: float = H_N * math.sqrt(LIQ_PERIOD_A / 10)  # 0.04 × sqrt(2) ≈ 0.05656854
C_ADJ_A: float = MARKET_VALUE * (1.0 - H_M_A)
EAD_FINAL_A: float = max(0.0, DRAWN_AMOUNT - C_ADJ_A)

# Run B — SFT repo, 5-day supervisory liquidation period (Art. 224(2)(c))
LIQ_PERIOD_B: int = 5
H_M_B: float = H_N * math.sqrt(LIQ_PERIOD_B / 10)  # 0.04 × sqrt(0.5) ≈ 0.02828427
C_ADJ_B: float = MARKET_VALUE * (1.0 - H_M_B)
EAD_FINAL_B: float = max(0.0, DRAWN_AMOUNT - C_ADJ_B)

# Pre-fix (other_physical 40% base) — for test reference
H_N_BUG: float = 0.40
EAD_FINAL_B_PRE_FIX: float = max(
    0.0, DRAWN_AMOUNT - MARKET_VALUE * (1.0 - H_N_BUG * math.sqrt(LIQ_PERIOD_B / 10))
)


# ---------------------------------------------------------------------------
# Private dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.96 counterparty: GB corporate, not defaulted, not a financial sector entity.

    entity_type=corporate → SA risk weight 100% (CRR Art. 122, unrated).
    is_financial_sector_entity=False, apply_fi_scalar=False → no FI scalar.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    is_financial_sector_entity: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.96 facility row.

    Run A: product_type=term_loan, is_sft=False.
    Run B: product_type=repo, is_sft=True (triggers SFT haircut period).
    """

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
    has_one_day_maturity_floor: bool
    is_sft: bool

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
            "has_one_day_maturity_floor": self.has_one_day_maturity_floor,
            "is_sft": self.is_sft,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.96 loan row.

    Run A: product_type=term_loan, is_sft=False (Art. 197 path).
    Run B: product_type=repo, is_sft=True (Art. 207(2) extended eligibility).
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
    seniority: str
    has_one_day_maturity_floor: bool
    is_sft: bool

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
            "has_one_day_maturity_floor": self.has_one_day_maturity_floor,
            "is_sft": self.is_sft,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.96 collateral row: covered_bond, GBP, CQS 1, residual_maturity=2.0y.

    collateral_type=covered_bond routes through the Art. 224 Table 1 corp-bond
    haircut band (H_n=4% for CQS 1, 1-5y residual maturity).

    is_eligible_financial_collateral=True is the client-asserted value.
    For Run A (non-SFT), the engine should override this to False under Art. 197
    because covered bonds are not in the Art. 197 non-SFT eligible list.
    For Run B (SFT/repo), Art. 207(2) permits covered bonds as eligible collateral.

    liquidation_period_days: 20 for Run A, 5 for Run B.
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_cqs: int
    issuer_type: str
    residual_maturity_years: float
    original_maturity_years: float
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    valuation_date: date
    valuation_type: str
    liquidation_period_days: int

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "market_value": self.market_value,
            "nominal_value": self.nominal_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_cqs": self.issuer_cqs,
            "issuer_type": self.issuer_type,
            "residual_maturity_years": self.residual_maturity_years,
            "original_maturity_years": self.original_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
            "liquidation_period_days": self.liquidation_period_days,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p196_counterparty() -> pl.DataFrame:
    """
    Return the P1.96 counterparty as a single-row DataFrame.

    GB corporate, unrated, not defaulted, not a financial sector entity.
    This single counterparty is shared by both Run A and Run B.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Covered Bond Haircut Routing Corporate Ltd",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        is_financial_sector_entity=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p196_facilities() -> pl.DataFrame:
    """
    Return both P1.96 facility rows as a two-row DataFrame.

    FAC_P196_A: term_loan, is_sft=False (Art. 197 non-SFT ineligibility path).
    FAC_P196_B: repo, is_sft=True (Art. 207(2) extended eligibility path).
    """
    rows = [
        _Facility(
            facility_reference=FACILITY_REF_A,
            product_type="term_loan",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
            has_one_day_maturity_floor=False,
            is_sft=False,
        ),
        _Facility(
            facility_reference=FACILITY_REF_B,
            product_type="repo",
            book_code="FI_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
            has_one_day_maturity_floor=False,
            is_sft=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p196_loans() -> pl.DataFrame:
    """
    Return both P1.96 loan rows as a two-row DataFrame.

    LOAN_P196_A: term_loan, is_sft=False → engine uses 20-day supervisory
                 liquidation period for haircut scaling.
    LOAN_P196_B: repo, is_sft=True → engine uses 5-day SFT period (Art. 224(2)(c)).
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF_A,
            product_type="term_loan",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            has_one_day_maturity_floor=False,
            is_sft=False,
        ),
        _Loan(
            loan_reference=LOAN_REF_B,
            product_type="repo",
            book_code="FI_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            has_one_day_maturity_floor=False,
            is_sft=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p196_collateral() -> pl.DataFrame:
    """
    Return both P1.96 collateral rows as a two-row DataFrame.

    COLL_P196_A: beneficiary=LOAN_P196_A, liquidation_period_days=20 (non-SFT).
                 is_eligible_financial_collateral=True (client-asserted; engine
                 should override to False for the non-SFT Art. 197 path).

    COLL_P196_B: beneficiary=LOAN_P196_B, liquidation_period_days=5 (SFT repo).
                 is_eligible_financial_collateral=True (eligible under Art. 207(2)).

    Both rows:
        collateral_type=covered_bond → corp-bond haircut band (Art. 224 Table 1)
        issuer_cqs=1, residual_maturity_years=2.0 → 1-5y band, H_n=4%
        currency=GBP, no FX haircut.
    """
    rows = [
        _Collateral(
            collateral_reference=COLLATERAL_REF_A,
            collateral_type="covered_bond",
            currency="GBP",
            maturity_date=date(2028, 1, 1),
            market_value=MARKET_VALUE,
            nominal_value=NOMINAL_VALUE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_A,
            issuer_cqs=1,
            issuer_type="institution",
            residual_maturity_years=2.0,
            original_maturity_years=5.0,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
            liquidation_period_days=LIQ_PERIOD_A,
        ),
        _Collateral(
            collateral_reference=COLLATERAL_REF_B,
            collateral_type="covered_bond",
            currency="GBP",
            maturity_date=date(2028, 1, 1),
            market_value=MARKET_VALUE,
            nominal_value=NOMINAL_VALUE,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF_B,
            issuer_cqs=1,
            issuer_type="institution",
            residual_maturity_years=2.0,
            original_maturity_years=5.0,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
            liquidation_period_days=LIQ_PERIOD_B,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p196_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.96 parquet files and return a mapping of name -> path.

    Four parquet files are written:
    - counterparty.parquet  (1 row: CP_P196)
    - facility.parquet      (2 rows: FAC_P196_A, FAC_P196_B)
    - loan.parquet          (2 rows: LOAN_P196_A, LOAN_P196_B)
    - collateral.parquet    (2 rows: COLL_P196_A, COLL_P196_B)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p196_counterparty()),
        ("facility", create_p196_facilities()),
        ("loan", create_p196_loans()),
        ("collateral", create_p196_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.96 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR covered-bond collateral haircut routing (Art. 197 / Art. 207(2))")
    print("")
    print("  Run A (term_loan, is_sft=False, liq_period=20d):")
    print(f"    H_n (corp-bond CQS1 1-5y)      = {H_N:.4f}  (4.0%)")
    print(f"    H_m (scaled to {LIQ_PERIOD_A}d)           = {H_M_A:.8f}")
    print(f"    C_adj                           = {C_ADJ_A:,.2f}")
    print(f"    EAD (E*)                        = {EAD_FINAL_A:,.2f}")
    print("")
    print("  Run B (repo, is_sft=True, liq_period=5d):")
    print(f"    H_n (corp-bond CQS1 1-5y)      = {H_N:.4f}  (4.0%)")
    print(f"    H_m (scaled to {LIQ_PERIOD_B}d)            = {H_M_B:.8f}")
    print(f"    C_adj                           = {C_ADJ_B:,.2f}")
    print(f"    EAD (E*)                        = {EAD_FINAL_B:,.2f}")
    print(f"    Pre-fix EAD (other_physical 40%)= {EAD_FINAL_B_PRE_FIX:,.2f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p196_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
