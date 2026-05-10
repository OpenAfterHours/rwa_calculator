"""
Generate P2.14 fixtures: CRR Art. 128 high-risk class omitted via SI 2021/1078.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce two counterparty rows: high_risk_venture_capital and high_risk_private_equity.
- Produce two facility rows: GBP loans with 3-year term.
- Produce two loan rows: fully drawn GBP loans, EAD = drawn_amount.
- No collateral, no guarantees, no provisions — clean single-factor SA test.
- Framework-agnostic fixture: same parquet rows feed both CRR and Basel 3.1 runs.

Scenario rationale:
    CRR Art. 128 (high-risk items, 150% risk weight) was omitted from UK onshored
    CRR by SI 2021/1078 (The Capital Requirements Regulation (Amendment) Regulations
    2021), reg. 6(3)(a), effective 1 January 2022. Under current UK CRR, the
    high-risk exposure class is a dead letter: exposures with entity types
    "high_risk_venture_capital" or "high_risk_private_equity" must fall through to
    their standard exposure class (residual = OTHER, 100% risk weight) rather than
    receiving the 150% Art. 128 treatment.

    Under PRA PS1/26 (Basel 3.1, effective 1 January 2027), Art. 128 is
    re-introduced. The 150% risk weight applies from 2027.

Hand-calculation (Run A — CRR, CalculationConfig.crr(reporting_date=2024-12-31)):
    Art. 128 omitted → high-risk entity types fall through to residual/OTHER class
    EAD per loan = drawn_amount:
        LN_VC_001:  1_000_000 GBP
        LN_PE_002:  2_000_000 GBP
    RW = 1.00 (residual 100%, Art. 134 or OTHER fall-through)
    RWA total = (1_000_000 + 2_000_000) × 1.00 = 3_000_000

Hand-calculation (Run B — Basel 3.1, CalculationConfig.basel_3_1(reporting_date=2027-06-30)):
    Art. 128 re-introduced → high-risk items at 150%
    RW = 1.50
    RWA total = (1_000_000 + 2_000_000) × 1.50 = 4_500_000

Expected outputs:
    Run A (CRR):
        CP_VC_001 / LN_VC_001: risk_weight=1.00, rwa=1_000_000
        CP_PE_002 / LN_PE_002: risk_weight=1.00, rwa=2_000_000
        Combined rwa = 3_000_000

    Run B (Basel 3.1):
        CP_VC_001 / LN_VC_001: risk_weight=1.50, rwa=1_500_000
        CP_PE_002 / LN_PE_002: risk_weight=1.50, rwa=3_000_000
        Combined rwa = 4_500_000

References:
    - UK CRR SI 2021/1078 reg. 6(3)(a): omission of Art. 128 from onshored CRR.
    - CRR Art. 128: high-risk items 150% risk weight (dead letter under UK CRR).
    - PRA PS1/26 Art. 128: re-introduction of high-risk 150% from 1 Jan 2027.
    - docs/specifications/crr/sa-risk-weights.md §High-Risk Exposures (Art. 128).
    - src/rwa_calc/data/schemas.py: VALID_ENTITY_TYPES (lines 547-549).
    - src/rwa_calc/engine/classifier.py: entity_class_mapping (lines 60-64).

Usage:
    uv run python tests/fixtures/p2_14/p2_14.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

VALUE_DATE: date = date(2024, 1, 1)
MATURITY_DATE: date = date(2027, 1, 1)  # 3-year term

# EAD values (fully drawn, interest=0 → EAD = drawn_amount)
EAD_VC: float = 1_000_000.0  # CP_VC_001 / LN_VC_001 / FAC_VC_001
EAD_PE: float = 2_000_000.0  # CP_PE_002 / LN_PE_002 / FAC_PE_002

# ---------------------------------------------------------------------------
# Expected outputs — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

#: Run A (CRR): Art. 128 omitted → fall-through to residual 100%
EXPECTED_RW_CRR: float = 1.00
EXPECTED_RWA_VC_CRR: float = EAD_VC * EXPECTED_RW_CRR  # 1_000_000
EXPECTED_RWA_PE_CRR: float = EAD_PE * EXPECTED_RW_CRR  # 2_000_000
EXPECTED_RWA_TOTAL_CRR: float = EXPECTED_RWA_VC_CRR + EXPECTED_RWA_PE_CRR  # 3_000_000

#: Run B (Basel 3.1): Art. 128 re-introduced → 150%
EXPECTED_RW_B31: float = 1.50
EXPECTED_RWA_VC_B31: float = EAD_VC * EXPECTED_RW_B31  # 1_500_000
EXPECTED_RWA_PE_B31: float = EAD_PE * EXPECTED_RW_B31  # 3_000_000
EXPECTED_RWA_TOTAL_B31: float = EXPECTED_RWA_VC_B31 + EXPECTED_RWA_PE_B31  # 4_500_000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    High-risk counterparty row for P2.14.

    entity_type values "high_risk_venture_capital" and "high_risk_private_equity"
    are declared in VALID_ENTITY_TYPES (data/schemas.py lines 547-549) and map to
    the HIGH_RISK exposure class in entity_class_mapping.py (lines 60-64).

    Under UK CRR (pre-2027) Art. 128 is omitted — these entity types must fall
    through to residual treatment (100% RW) rather than Art. 128 (150%).
    Under Basel 3.1 (post-2027) Art. 128 is re-introduced at 150%.

    annual_revenue is provided to avoid the CLS008 conservative-large warning
    under Basel 3.1 (threshold GBP 440m); both values are well below threshold.
    default_status=False: standard non-defaulted path.
    apply_fi_scalar=False: not a financial institution — no 1.25x IRB multiplier.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Facility:
    """
    Facility row for P2.14.

    Committed=True: full limit is available (no undrawn CCF complication for
    the SA test — the loan row carries the fully drawn amount).
    product_type="loan": plain vanilla loan product; no off-balance-sheet CCF.
    seniority="senior": standard senior secured path (no LGD override needed for SA).
    """

    facility_reference: str
    counterparty_reference: str
    product_type: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "product_type": self.product_type,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Loan row for P2.14.

    drawn_amount = full limit; interest=0 → EAD = drawn_amount exactly.
    seniority="senior": no subordination-based LGD uplift needed for SA.
    No model_id: pure SA path (no IRB model permission).
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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p214_counterparties() -> pl.DataFrame:
    """
    Return two P2.14 counterparties as a DataFrame.

    CP_VC_001: entity_type=high_risk_venture_capital, annual_revenue=2_500_000 GBP.
    CP_PE_002: entity_type=high_risk_private_equity,  annual_revenue=8_000_000 GBP.

    Both are GB-domiciled, not defaulted, no FI scalar.
    Both have annual_revenue well below GBP 440m so no CLS008 warning fires.
    """
    rows = [
        _Counterparty(
            counterparty_reference="CP_VC_001",
            counterparty_name="VC Fund Alpha Ltd",
            entity_type="high_risk_venture_capital",
            country_code="GB",
            annual_revenue=2_500_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference="CP_PE_002",
            counterparty_name="PE Vehicle Beta Ltd",
            entity_type="high_risk_private_equity",
            country_code="GB",
            annual_revenue=8_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p214_facilities() -> pl.DataFrame:
    """
    Return two P2.14 facility rows as a DataFrame.

    FAC_VC_001: limit=1_000_000 GBP, CP_VC_001, committed.
    FAC_PE_002: limit=2_000_000 GBP, CP_PE_002, committed.

    Both are GBP-denominated, value_date=2024-01-01, maturity_date=2027-01-01.
    committed=True: full limit drawn in the corresponding loan rows.
    """
    rows = [
        _Facility(
            facility_reference="FAC_VC_001",
            counterparty_reference="CP_VC_001",
            product_type="loan",
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            limit=EAD_VC,
            committed=True,
        ),
        _Facility(
            facility_reference="FAC_PE_002",
            counterparty_reference="CP_PE_002",
            product_type="loan",
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            limit=EAD_PE,
            committed=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p214_loans() -> pl.DataFrame:
    """
    Return two P2.14 loan rows as a DataFrame.

    LN_VC_001: drawn_amount=1_000_000 GBP, counterparty=CP_VC_001.
    LN_PE_002: drawn_amount=2_000_000 GBP, counterparty=CP_PE_002.

    interest=0 in both rows: EAD = drawn_amount exactly.
    seniority="senior": standard path, no subordination uplift.
    maturity_date=2027-01-01: 3-year residual at reporting date 2024-12-31
    (≈ 2.0 years, > 0.25y → not in the Art. 120(2) short-term gate).
    """
    rows = [
        _Loan(
            loan_reference="LN_VC_001",
            counterparty_reference="CP_VC_001",
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD_VC,
            interest=0.0,
            seniority="senior",
        ),
        _Loan(
            loan_reference="LN_PE_002",
            counterparty_reference="CP_PE_002",
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD_PE,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p214_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.14 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet  — 2 rows (CP_VC_001, CP_PE_002)
        facility.parquet      — 2 rows (FAC_VC_001, FAC_PE_002)
        loan.parquet          — 2 rows (LN_VC_001, LN_PE_002)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p214_counterparties()),
        ("facility", create_p214_facilities()),
        ("loan", create_p214_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.14 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 128 high-risk omitted via SI 2021/1078 (UK CRR)")
    print("          PRA PS1/26 re-introduces Art. 128 from 1 Jan 2027")
    print()
    print("  Counterparties:")
    print("    CP_VC_001  entity_type=high_risk_venture_capital  GBP 2.5m revenue")
    print("    CP_PE_002  entity_type=high_risk_private_equity   GBP 8.0m revenue")
    print()
    print("  Run A (CRR, reporting_date=2024-12-31):")
    print(f"    Art. 128 omitted → fallthrough to residual RW={EXPECTED_RW_CRR:.0%}")
    print(f"    RWA: VC={EXPECTED_RWA_VC_CRR:,.0f}  PE={EXPECTED_RWA_PE_CRR:,.0f}")
    print(f"    Total RWA = {EXPECTED_RWA_TOTAL_CRR:,.0f}")
    print()
    print("  Run B (Basel 3.1, reporting_date=2027-06-30):")
    print(f"    Art. 128 re-introduced → RW={EXPECTED_RW_B31:.0%}")
    print(f"    RWA: VC={EXPECTED_RWA_VC_B31:,.0f}  PE={EXPECTED_RWA_PE_B31:,.0f}")
    print(f"    Total RWA = {EXPECTED_RWA_TOTAL_B31:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p214_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
