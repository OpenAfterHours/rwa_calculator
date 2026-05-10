"""
Generate P1.120 fixtures: B31 SA defaulted corporate, partially collateralised via FCCM cash.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py fix)

Key responsibilities:
- Produce one counterparty row: corporate, country=GB, default_status=True.
- Produce one loan row: GBP 100,000 drawn, maturity 2027-12-31.
- Produce one provision row: 8,000 deducted against the loan.
- Produce one collateral row: GBP 60,000 cash (collateral_type="cash"),
  0% haircut (same currency, FCCM-eligible).

Scenario design (B31-K13 — partial-secured defaulted corporate):
    Gross outstanding = drawn_amount = 100,000  (ead_gross before provision)
    Provision deducted: 8,000
    After CCF stage: ead_pre_crm = 100,000 - 8,000 = 92,000
    After FCCM stage: ead_final   = 92,000 - 60,000 = 32,000

    Art. 127(1) B31 threshold test:
        provision_amount / gross_outstanding = 8,000 / 100,000 = 8.0%
        8.0% < 20%  →  RW = 150%

    Under the current buggy engine (D3.19):
        denominator = unsecured_ead = ead_final = 32,000
        8,000 / 32,000 = 25%  ≥  20%  →  buggy RW = 100%  (understates capital)

    After the fix:
        denominator = gross_outstanding = ead_gross + provision_deducted = 100,000
        8,000 / 100,000 = 8%  <  20%  →  correct RW = 150%
        RWA = 32,000 × 1.50 = 48,000

    The fixture is deliberately constructed so:
        - Under the buggy denominator (unsecured_ead = 32,000):
          8,000 / 32,000 = 25% → 100% RW → RWA = 32,000  (wrong, too low)
        - Under the correct denominator (gross = 100,000):
          8,000 / 100,000 = 8% → 150% RW → RWA = 48,000  (correct)
    This creates a clear binary signal: any regression restoring the bug
    produces a 33% RWA understatement.

Hand-calculation (B31, CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))):
    Step 1 - Classification: entity_type="corporate" → exposure_class=CORPORATE
    Step 2 - CCF: drawn loan, no undrawn → EAD_pre_crm = 100,000 - 8,000 = 92,000
    Step 3 - FCCM: cash GBP 60,000, H_collateral=0%, H_FX=0% (same ccy) → C*=60,000
             EAD_final = max(0, 92,000 - 60,000) = 32,000
    Step 4 - Art. 127(1) B31 denominator:
             gross_outstanding = ead_gross + provision_deducted = 92,000 + 8,000 = 100,000
             provision_ratio = 8,000 / 100,000 = 0.08 < 0.20  →  RW = 1.50
    Step 5 - RWA = 32,000 × 1.50 = 48,000

References:
    - PRA PS1/26 Art. 127(1): defaulted SA RW threshold denominator = "outstanding amount
      of the item or facility" (gross, pre-CRM, pre-provision)
    - BCBS CRE20.88-90: defaulted exposure provision threshold mechanics
    - docs/specifications/crr/sa-risk-weights.md § "Defaulted Exposures (CRR Art. 127 /
      PRA PS1/26 Art. 127)" — warning box "Code Divergence — B31 Path (D3.19)"
    - CRR Art. 223 / BCBS CRE22.40: FCCM — cash same-currency zero haircut
    - src/rwa_calc/engine/sa/namespace.py: B31 defaulted branch (bug site)

Usage:
    uv run python tests/fixtures/p1_120/p1_120.py
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
    LOAN_SCHEMA,
    PROVISION_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_K13"
LOAN_REF = "B31_K13_PARTIAL_SECURED_DEFAULT"
COLLATERAL_REF = "COLL_K13_CASH_GBP"
PROVISION_REF = "PROV_K13_001"

REPORTING_DATE = date(2027, 6, 30)
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2027, 12, 31)

# Monetary amounts (GBP, exact integers for clean hand-calculation)
DRAWN_AMOUNT: float = 100_000.0  # Gross outstanding
PROVISION_AMOUNT: float = 8_000.0  # Deducted specific provision
COLLATERAL_VALUE: float = 60_000.0  # Cash GBP — 0% haircut

# Derived intermediates
EAD_PRE_CRM: float = DRAWN_AMOUNT - PROVISION_AMOUNT  # 92,000
EAD_FINAL: float = EAD_PRE_CRM - COLLATERAL_VALUE  # 32,000
GROSS_OUTSTANDING: float = DRAWN_AMOUNT  # 100,000

# Art. 127(1) B31 threshold test
PROVISION_RATIO: float = PROVISION_AMOUNT / GROSS_OUTSTANDING  # 0.08
THRESHOLD: float = 0.20  # 20%

# Expected results (post-fix)
EXPECTED_RISK_WEIGHT: float = 1.50  # 8% < 20% → 150%
EXPECTED_RWA: float = EAD_FINAL * EXPECTED_RISK_WEIGHT  # 48,000

# Buggy result (pre-fix) — denominator = EAD_final = 32,000
BUGGY_PROVISION_RATIO: float = PROVISION_AMOUNT / EAD_FINAL  # 0.25
BUGGY_RISK_WEIGHT: float = 1.00  # 25% >= 20% → 100% (wrong)
BUGGY_RWA: float = EAD_FINAL * BUGGY_RISK_WEIGHT  # 32,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    CP_K13: defaulted UK corporate counterparty.

    default_status=True propagates through the pipeline so the exposure is
    routed to the Art. 127 defaulted risk-weight branch (not the standard
    corporate 100% unrated branch).
    is_financial_sector_entity=False: no FI scalar.
    apply_fi_scalar=False: not a financial institution.
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
    B31_K13_PARTIAL_SECURED_DEFAULT: GBP 100,000 drawn corporate loan.

    drawn_amount=100,000: gross outstanding before provision deduction.
    interest=0.0: no accrued interest — keeps EAD computation clean.
    seniority="senior": standard senior unsecured ranking.
    is_sft=False: term loan, not a securities financing transaction.
    book_code="BANKING": standard banking book.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    book_code: str
    is_sft: bool

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
            "book_code": self.book_code,
            "is_sft": self.is_sft,
        }


@dataclass(frozen=True)
class _Provision:
    """
    PROV_K13_001: GBP 8,000 specific provision, deducted from EAD.

    provision_type=SCRA: specific credit risk adjustment (Stage 3 IFRS 9).
    ifrs9_stage=3: credit-impaired (counterparty is defaulted).
    amount=8,000: the provision deducted from the gross exposure value.
    beneficiary_type="loan": provision attaches to the loan row directly.
    treatment=deducted (expressed via SCRA + Stage 3 — pipeline interprets
    SCRA/stage-3 as deducted specific provisions under Art. 127).
    """

    provision_reference: str
    provision_type: str
    ifrs9_stage: int
    currency: str
    amount: float
    as_of_date: date
    beneficiary_type: str
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "provision_reference": self.provision_reference,
            "provision_type": self.provision_type,
            "ifrs9_stage": self.ifrs9_stage,
            "currency": self.currency,
            "amount": self.amount,
            "as_of_date": self.as_of_date,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    COLL_K13_CASH_GBP: GBP 60,000 cash collateral eligible under FCCM.

    collateral_type="cash": cash deposit — attracts 0% supervisory haircut
    under CRR Art. 224 / BCBS CRE22.40 when currency matches the exposure.
    currency="GBP": same as the loan currency → H_FX = 0%, no FX haircut.
    market_value=60,000: the full amount is eligible (no haircut applied).
    is_eligible_financial_collateral=True: routes through the FCCM
    (Financial Collateral Comprehensive Method) engine path.
    is_eligible_irb_collateral=True: also eligible for IRB CRM (unused here).
    issuer_cqs=None, issuer_type=None: cash has no issuer.
    residual_maturity_years=None: cash has no maturity.
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    valuation_date: date
    valuation_type: str

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "nominal_value": self.nominal_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1120_counterparty() -> pl.DataFrame:
    """
    Return the P1.120 counterparty (defaulted UK corporate) as a single-row DataFrame.

    default_status=True routes the exposure to the Art. 127 defaulted path.
    entity_type=corporate → SA exposure class CORPORATE.
    No sovereign_cqs, no scra_grade, no institution_cqs — corporate entity.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="K13 Defaulted Corporate Ltd — P1.120",
        entity_type="corporate",
        country_code="GB",
        default_status=True,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1120_loan() -> pl.DataFrame:
    """
    Return the P1.120 loan (GBP 100,000 drawn, defaulted corporate) as a single-row DataFrame.

    drawn_amount=100,000 = gross outstanding for Art. 127(1) denominator.
    interest=0: no accrued interest → EAD_pre_crm = drawn_amount - provision = 92,000.
    maturity_date=2027-12-31: short remaining maturity (~6 months from REPORTING_DATE).
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        seniority="senior",
        book_code="BANKING",
        is_sft=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1120_provision() -> pl.DataFrame:
    """
    Return the P1.120 provision (GBP 8,000 SCRA Stage 3) as a single-row DataFrame.

    amount=8,000 is deducted from the gross outstanding (100,000) before CRM.
    As a proportion of gross_outstanding: 8,000 / 100,000 = 8% < 20% threshold.
    After the engine fix: Art. 127(1) B31 → RW = 150%.
    Under the buggy engine (pre-fix): denominator = ead_final = 32,000
        → 8,000 / 32,000 = 25% ≥ 20% → buggy RW = 100%.
    """
    row = _Provision(
        provision_reference=PROVISION_REF,
        provision_type="SCRA",
        ifrs9_stage=3,
        currency="GBP",
        amount=PROVISION_AMOUNT,
        as_of_date=REPORTING_DATE,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(PROVISION_SCHEMA))


def create_p1120_collateral() -> pl.DataFrame:
    """
    Return the P1.120 collateral (GBP 60,000 cash, FCCM-eligible) as a single-row DataFrame.

    collateral_type="cash" with currency="GBP" (same as loan) → H_collateral=0%,
    H_FX=0% under CRR Art. 224 / BCBS CRE22.40.
    Adjusted collateral C* = 60,000 × (1 - 0%) = 60,000.
    EAD_final = max(0, ead_pre_crm - C*) = max(0, 92,000 - 60,000) = 32,000.
    """
    row = _Collateral(
        collateral_reference=COLLATERAL_REF,
        collateral_type="cash",
        currency="GBP",
        market_value=COLLATERAL_VALUE,
        nominal_value=COLLATERAL_VALUE,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        is_eligible_financial_collateral=True,
        is_eligible_irb_collateral=True,
        valuation_date=REPORTING_DATE,
        valuation_type="market",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1120_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.120 parquet files and return a mapping of name -> path.

    Four files are written:
    - counterparty.parquet  (1 row: CP_K13, defaulted corporate)
    - loan.parquet          (1 row: B31_K13_PARTIAL_SECURED_DEFAULT, GBP 100k drawn)
    - provision.parquet     (1 row: PROV_K13_001, GBP 8k SCRA Stage 3)
    - collateral.parquet    (1 row: COLL_K13_CASH_GBP, GBP 60k cash FCCM)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1120_counterparty()),
        ("loan", create_p1120_loan()),
        ("provision", create_p1120_provision()),
        ("collateral", create_p1120_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.120 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: B31 SA defaulted corporate (Art. 127), partially collateralised FCCM cash")
    print(f"  Counterparty: {COUNTERPARTY_REF}  entity_type=corporate  default_status=True")
    print(f"  Loan: {LOAN_REF}")
    print(f"  Gross outstanding    = {DRAWN_AMOUNT:>10,.0f} GBP  (drawn_amount)")
    print(f"  Provision (deducted) = {PROVISION_AMOUNT:>10,.0f} GBP  (SCRA Stage 3)")
    print(f"  EAD pre-CRM          = {EAD_PRE_CRM:>10,.0f} GBP  (= drawn - provision)")
    print(f"  Cash collateral      = {COLLATERAL_VALUE:>10,.0f} GBP  (0% haircut, same ccy)")
    print(f"  EAD final            = {EAD_FINAL:>10,.0f} GBP  (= ead_pre_crm - collateral)")
    print()
    print("  Art. 127(1) B31 denominator check:")
    print(f"    gross_outstanding = {GROSS_OUTSTANDING:,.0f}")
    print(
        f"    provision / gross  = {PROVISION_RATIO:.1%}  <  {THRESHOLD:.0%}  ->  RW = {EXPECTED_RISK_WEIGHT:.0%}"
    )
    print(f"    CORRECT RWA = {EAD_FINAL:,.0f} x {EXPECTED_RISK_WEIGHT:.0%} = {EXPECTED_RWA:,.0f}")
    print()
    print("  Buggy engine (pre-fix) — denominator = ead_final:")
    print(
        f"    provision / ead_final = {BUGGY_PROVISION_RATIO:.1%}  >=  {THRESHOLD:.0%}  ->  buggy RW = {BUGGY_RISK_WEIGHT:.0%}"
    )
    print(
        f"    BUGGY RWA = {EAD_FINAL:,.0f} x {BUGGY_RISK_WEIGHT:.0%} = {BUGGY_RWA:,.0f}  (understates by {EXPECTED_RWA - BUGGY_RWA:,.0f})"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1120_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
