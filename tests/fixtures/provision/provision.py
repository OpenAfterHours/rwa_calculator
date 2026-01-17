"""
Generate provision test fixtures for credit risk mitigation testing.

The output will be saved as `provision.parquet` ready to get picked up within the wider
testing process.

Provisions reduce EAD and affect RWA calculations:
    - SCRA (Specific Credit Risk Adjustments): Against specific exposures
    - GCRA (General Credit Risk Adjustments): Portfolio-level provisions

IFRS 9 staging:
    - Stage 1: 12-month expected credit loss (performing)
    - Stage 2: Lifetime ECL (significant increase in credit risk)
    - Stage 3: Credit-impaired (defaulted)

CRM scenarios covered:
    H4: Full CRM chain - exposure + collateral + guarantee + provision

Usage:
    uv run python tests/fixtures/provision/provision.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import PROVISION_SCHEMA


def main() -> None:
    """Entry point for provision generation."""
    output_path = save_provisions()
    print_summary(output_path)


@dataclass(frozen=True)
class Provision:
    """A credit provision for risk mitigation."""

    provision_reference: str
    provision_type: str  # SCRA or GCRA
    ifrs9_stage: int  # 1, 2, or 3
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


VALUE_DATE = date(2026, 1, 1)


def create_provisions() -> pl.DataFrame:
    """
    Create provision test data.

    Returns:
        pl.DataFrame: Provisions matching PROVISION_SCHEMA
    """
    provisions = [
        *_stage1_provisions(),
        *_stage2_provisions(),
        *_stage3_provisions(),
        *_general_provisions(),
        *_crm_test_provisions(),
    ]

    return pl.DataFrame([p.to_dict() for p in provisions], schema=PROVISION_SCHEMA)


def _stage1_provisions() -> list[Provision]:
    """
    Stage 1 provisions - 12-month ECL for performing exposures.

    Low provision rates (typically 0.1-0.5% of exposure).
    """
    return [
        # Corporate performing loan - minimal provision
        Provision(
            provision_reference="PROV_S1_CORP_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=25_000.0,  # 0.1% of £25m
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_UK_001",
        ),
        # Institution loan - very low provision
        Provision(
            provision_reference="PROV_S1_INST_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=25_000.0,  # 0.05% of £50m
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_INST_UK_001",
        ),
        # Mortgage - low provision
        Provision(
            provision_reference="PROV_S1_MTG_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=500.0,  # 0.1% of £500k
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_RTL_MTG_001",
        ),
        # SME loan provision
        Provision(
            provision_reference="PROV_S1_SME_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=10_000.0,  # 0.5% of £2m
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_SME_001",
        ),
        # Facility-level provision
        Provision(
            provision_reference="PROV_S1_FAC_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=50_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="facility",
            beneficiary_reference="FAC_CORP_001",
        ),
    ]


def _stage2_provisions() -> list[Provision]:
    """
    Stage 2 provisions - Lifetime ECL for watch-list exposures.

    Higher provision rates (typically 2-10% of exposure).
    """
    return [
        # Watch-list corporate - significant increase in credit risk
        Provision(
            provision_reference="PROV_S2_CORP_001",
            provision_type="SCRA",
            ifrs9_stage=2,
            currency="GBP",
            amount=50_000.0,  # 5% of £1m unrated corporate
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_UR_001",
        ),
        # Watch-list SME retail
        Provision(
            provision_reference="PROV_S2_SME_001",
            provision_type="SCRA",
            ifrs9_stage=2,
            currency="GBP",
            amount=25_000.0,  # 5% of £500k
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_RTL_SME_001",
        ),
        # Watch-list hierarchy loan
        Provision(
            provision_reference="PROV_S2_HIER_001",
            provision_type="SCRA",
            ifrs9_stage=2,
            currency="GBP",
            amount=75_000.0,  # 5% of £1.5m
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_A",
        ),
        # Subordinated loan - higher provision due to higher risk
        Provision(
            provision_reference="PROV_S2_SUB_001",
            provision_type="SCRA",
            ifrs9_stage=2,
            currency="GBP",
            amount=500_000.0,  # 10% of £5m subordinated
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_SUB_001",
        ),
    ]


def _stage3_provisions() -> list[Provision]:
    """
    Stage 3 provisions - Credit-impaired (defaulted) exposures.

    High provision rates reflecting expected loss (typically 20-80%).
    """
    return [
        # Defaulted corporate - significant provision
        Provision(
            provision_reference="PROV_S3_CORP_001",
            provision_type="SCRA",
            ifrs9_stage=3,
            currency="GBP",
            amount=225_000.0,  # 45% of £500k (aligned with LGD)
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_DF_CORP_001",
        ),
        # Defaulted retail - high provision
        Provision(
            provision_reference="PROV_S3_RTL_001",
            provision_type="SCRA",
            ifrs9_stage=3,
            currency="GBP",
            amount=11_250.0,  # 45% of £25k
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_DF_RTL_001",
        ),
        # Counterparty-level provision for defaulted sovereign
        Provision(
            provision_reference="PROV_S3_SOV_001",
            provision_type="SCRA",
            ifrs9_stage=3,
            currency="USD",
            amount=400_000.0,  # 20% of Brazil exposure
            as_of_date=VALUE_DATE,
            beneficiary_type="counterparty",
            beneficiary_reference="SOV_BR_001",
        ),
    ]


def _general_provisions() -> list[Provision]:
    """
    General Credit Risk Adjustments (GCRA) - portfolio-level provisions.

    Not attributable to specific exposures.
    """
    return [
        # Corporate lending book GCRA
        Provision(
            provision_reference="PROV_GCRA_CORP",
            provision_type="GCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=500_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="counterparty",
            beneficiary_reference="BOOK_CORP_LENDING",
        ),
        # SME lending book GCRA
        Provision(
            provision_reference="PROV_GCRA_SME",
            provision_type="GCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=100_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="counterparty",
            beneficiary_reference="BOOK_SME_LENDING",
        ),
        # Retail book GCRA
        Provision(
            provision_reference="PROV_GCRA_RTL",
            provision_type="GCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=75_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="counterparty",
            beneficiary_reference="BOOK_RETAIL",
        ),
    ]


def _crm_test_provisions() -> list[Provision]:
    """
    Provisions specifically for CRM scenario testing.

    H4: Full CRM chain - exposure + collateral + guarantee + provision
    """
    return [
        # =============================================================================
        # H4: Full CRM chain scenario
        # This provision completes the CRM chain:
        # - Loan: LOAN_FAC_CORP_002_A (£30m)
        # - Collateral: COLL_CRE_002 (commercial RE £5m)
        # - Guarantee: GUAR_CRM_CHAIN_001 (50% bank guarantee £15m)
        # - Provision: £300k SCRA
        # =============================================================================
        Provision(
            provision_reference="PROV_CRM_CHAIN_001",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=300_000.0,  # 1% of £30m
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_CORP_002_A",
        ),
        # Additional provision for hierarchy sub-facility loan
        Provision(
            provision_reference="PROV_CRM_CHAIN_002",
            provision_type="SCRA",
            ifrs9_stage=1,
            currency="GBP",
            amount=50_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_SUB_001_A",
        ),
        # Provision for maturity mismatch scenario
        Provision(
            provision_reference="PROV_MAT_TEST_001",
            provision_type="SCRA",
            ifrs9_stage=2,
            currency="GBP",
            amount=100_000.0,
            as_of_date=VALUE_DATE,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_B",
        ),
    ]


def save_provisions(output_dir: Path | None = None) -> Path:
    """
    Create and save provisions to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/provision directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_provisions()
    output_path = output_dir / "provision.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved provisions to: {output_path}")
    print(f"\nCreated {len(df)} provisions:")

    print("\nBy provision type:")
    type_counts = df.group_by("provision_type").len().sort("provision_type")
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['provision_type']}: {row['len']}")

    print("\nBy IFRS 9 stage:")
    stage_counts = df.group_by("ifrs9_stage").len().sort("ifrs9_stage")
    for row in stage_counts.iter_rows(named=True):
        print(f"  Stage {row['ifrs9_stage']}: {row['len']}")

    print("\nBy beneficiary type:")
    ben_counts = df.group_by("beneficiary_type").len().sort("beneficiary_type")
    for row in ben_counts.iter_rows(named=True):
        print(f"  {row['beneficiary_type']}: {row['len']}")

    print("\nTotal provisions by stage:")
    stage_totals = (
        df.group_by("ifrs9_stage")
        .agg(pl.col("amount").sum().alias("total_amount"))
        .sort("ifrs9_stage")
    )
    for row in stage_totals.iter_rows(named=True):
        print(f"  Stage {row['ifrs9_stage']}: GBP {row['total_amount']:,.0f}")


if __name__ == "__main__":
    main()
