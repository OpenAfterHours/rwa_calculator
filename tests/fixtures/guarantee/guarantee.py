"""
Generate guarantee test fixtures for credit risk mitigation testing.

The output will be saved as `guarantee.parquet` ready to get picked up within the wider
testing process.

Guarantees provide unfunded credit protection through substitution approach:
    - Guaranteed portion takes risk weight of guarantor
    - Unguaranteed portion retains borrower's risk weight

Guarantee types for testing:
    - Sovereign guarantees (0% RW for CQS 1)
    - Bank/institution guarantees (20-50% RW)
    - Export credit agency guarantees
    - Parent company guarantees (intragroup)

CRM scenarios covered:
    D4: Guarantee substitution - £600k bank guarantee against £1m corporate
    H4: Full CRM chain - exposure + collateral + guarantee + provision

Usage:
    uv run python tests/fixtures/guarantee/guarantee.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import GUARANTEE_SCHEMA


def main() -> None:
    """Entry point for guarantee generation."""
    output_path = save_guarantees()
    print_summary(output_path)


@dataclass(frozen=True)
class Guarantee:
    """A guarantee for credit risk mitigation."""

    guarantee_reference: str
    guarantee_type: str
    guarantor: str  # counterparty_reference of the guarantor
    currency: str
    maturity_date: date | None
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": self.guarantee_type,
            "guarantor": self.guarantor,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
        }


VALUE_DATE = date(2026, 1, 1)


def create_guarantees() -> pl.DataFrame:
    """
    Create guarantee test data.

    Returns:
        pl.DataFrame: Guarantees matching GUARANTEE_SCHEMA
    """
    guarantees = [
        *_sovereign_guarantees(),
        *_institution_guarantees(),
        *_corporate_guarantees(),
        *_crm_test_guarantees(),
    ]

    return pl.DataFrame([g.to_dict() for g in guarantees], schema=GUARANTEE_SCHEMA)


def _sovereign_guarantees() -> list[Guarantee]:
    """
    Sovereign guarantees - substitution to 0% RW (CQS 1).

    UK Government and export credit agency guarantees.
    """
    return [
        # UK Government guarantee on corporate loan
        # NOTE: Uses dedicated test loan to avoid affecting CRR-A12 test
        Guarantee(
            guarantee_reference="GUAR_SOV_001",
            guarantee_type="sovereign_guarantee",
            guarantor="SOV_UK_001",
            currency="GBP",
            maturity_date=date(2030, 12, 31),
            amount_covered=5_000_000.0,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_GUAR_TEST_SOV_001",  # Dedicated test loan
        ),
        # UK Export Finance guarantee (UKEF)
        Guarantee(
            guarantee_reference="GUAR_ECA_001",
            guarantee_type="export_credit_guarantee",
            guarantor="SOV_UK_001",
            currency="GBP",
            maturity_date=date(2029, 6, 30),
            amount_covered=10_000_000.0,
            percentage_covered=0.80,  # 80% covered by UKEF
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_CORP_001_A",
        ),
        # US Government partial guarantee
        Guarantee(
            guarantee_reference="GUAR_SOV_002",
            guarantee_type="sovereign_guarantee",
            guarantor="SOV_US_001",
            currency="USD",
            maturity_date=date(2028, 12, 31),
            amount_covered=2_500_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_SOV_BR_001",
        ),
    ]


def _institution_guarantees() -> list[Guarantee]:
    """
    Bank/institution guarantees - substitution to bank RW.

    NOTE: These guarantees use dedicated test loans (LOAN_GUAR_TEST_*)
    to avoid affecting other scenario tests (e.g., CRR-A).
    Actual D4 scenario uses GUAR_CRM_D4 with LOAN_CRM_D4.
    """
    return [
        # Barclays guarantee on corporate loan (CQS 1 bank = 20% RW)
        # Uses dedicated test loan to avoid affecting CRR-A tests
        Guarantee(
            guarantee_reference="GUAR_BANK_001",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_001",  # Barclays CQS 1
            currency="GBP",
            maturity_date=date(2028, 6, 30),
            amount_covered=600_000.0,
            percentage_covered=0.60,  # 60% of £1m exposure
            beneficiary_type="loan",
            beneficiary_reference="LOAN_GUAR_TEST_001",  # Dedicated test loan
        ),
        # HSBC guarantee on SME loan
        # Uses dedicated test loan to avoid affecting CRR-A tests
        Guarantee(
            guarantee_reference="GUAR_BANK_002",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_002",  # HSBC CQS 1
            currency="GBP",
            maturity_date=date(2028, 12, 31),
            amount_covered=1_000_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_GUAR_TEST_002",  # Dedicated test loan
        ),
        # Metro Bank guarantee (CQS 2 = 30% RW UK deviation)
        Guarantee(
            guarantee_reference="GUAR_BANK_003",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_003",  # Metro Bank CQS 2
            currency="GBP",
            maturity_date=date(2027, 12, 31),
            amount_covered=250_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_DF_CORP_001",
        ),
        # JPMorgan guarantee on interbank loan
        Guarantee(
            guarantee_reference="GUAR_BANK_004",
            guarantee_type="bank_guarantee",
            guarantor="INST_US_001",  # JPMorgan CQS 1
            currency="USD",
            maturity_date=date(2027, 6, 30),
            amount_covered=5_000_000.0,
            percentage_covered=0.25,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_INST_UR_001",
        ),
        # Standby letter of credit from bank
        Guarantee(
            guarantee_reference="GUAR_SBLC_001",
            guarantee_type="standby_letter_of_credit",
            guarantor="INST_UK_001",
            currency="GBP",
            maturity_date=date(2027, 3, 31),
            amount_covered=500_000.0,
            percentage_covered=1.0,
            beneficiary_type="facility",
            beneficiary_reference="FAC_CORP_SME_001",
        ),
    ]


def _corporate_guarantees() -> list[Guarantee]:
    """
    Corporate/parent company guarantees.

    Intragroup guarantees and corporate cross-guarantees.
    """
    return [
        # Parent company guarantee (rated parent for unrated subsidiary)
        Guarantee(
            guarantee_reference="GUAR_CORP_001",
            guarantee_type="parent_company_guarantee",
            guarantor="CORP_GRP1_PARENT",  # Alpha Holdings - rated CQS 2
            currency="GBP",
            maturity_date=date(2029, 12, 31),
            amount_covered=2_000_000.0,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_A",
        ),
        # Cross-guarantee within group
        Guarantee(
            guarantee_reference="GUAR_CORP_002",
            guarantee_type="cross_guarantee",
            guarantor="CORP_GRP2_ULTIMATE",  # Beta Corp - rated CQS 1
            currency="GBP",
            maturity_date=date(2030, 6, 30),
            amount_covered=3_000_000.0,
            percentage_covered=0.60,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_SUB_001_A",
        ),
        # Large corporate guarantee on SME (uses dedicated test loan)
        Guarantee(
            guarantee_reference="GUAR_CORP_003",
            guarantee_type="corporate_guarantee",
            guarantor="CORP_UK_001",  # BP - CQS 1
            currency="GBP",
            maturity_date=date(2028, 12, 31),
            amount_covered=400_000.0,
            percentage_covered=0.80,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_GUAR_TEST_RTL_001",  # Dedicated test loan
        ),
    ]


def _crm_test_guarantees() -> list[Guarantee]:
    """
    Guarantees specifically for CRM scenario testing.

    D4: Bank guarantee substitution - 60% covered by CQS 2 UK bank (30% RW)
    H4: Full CRM chain - exposure with collateral + guarantee + provision
    """
    return [
        # =============================================================================
        # D4: Bank guarantee substitution scenario
        # £1m loan to unrated corporate (100% RW)
        # 60% guaranteed by Metro Bank (CQS 2 UK bank = 30% RW UK deviation)
        # Blended RW = 0.6 * 30% + 0.4 * 100% = 18% + 40% = 58%
        # RWA = £1m * 58% = £580k
        # =============================================================================
        Guarantee(
            guarantee_reference="GUAR_CRM_D4",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_003",  # Metro Bank - CQS 2 (30% RW UK deviation)
            currency="GBP",
            maturity_date=date(2030, 1, 1),  # Maturity >= loan maturity
            amount_covered=600_000.0,  # 60% of £1m
            percentage_covered=0.60,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CRM_D4",
        ),
        # =============================================================================
        # H4: Full CRM chain scenario
        # This guarantee is part of a fully mitigated exposure:
        # - Loan: LOAN_FAC_CORP_002_A (£30m)
        # - Collateral: COLL_CRE_002 (commercial RE £5m)
        # - Guarantee: 50% bank guarantee (£15m)
        # - Provision: To be added in provision fixtures
        # =============================================================================
        Guarantee(
            guarantee_reference="GUAR_CRM_CHAIN_001",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_002",  # HSBC CQS 1
            currency="GBP",
            maturity_date=date(2029, 6, 30),
            amount_covered=15_000_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_CORP_002_A",
        ),
        # Partial sovereign guarantee for hierarchy test
        Guarantee(
            guarantee_reference="GUAR_CRM_CHAIN_002",
            guarantee_type="sovereign_guarantee",
            guarantor="SOV_UK_001",
            currency="GBP",
            maturity_date=date(2030, 6, 30),
            amount_covered=4_000_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_SUB_002_A",
        ),
        # Guarantee with maturity shorter than exposure (maturity mismatch)
        Guarantee(
            guarantee_reference="GUAR_MAT_MISMATCH_001",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_001",
            currency="GBP",
            maturity_date=date(2027, 1, 1),  # 1yr maturity vs 4yr exposure
            amount_covered=500_000.0,
            percentage_covered=0.50,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_B",
        ),
        # Guarantee in different currency (EUR guarantee for GBP exposure)
        Guarantee(
            guarantee_reference="GUAR_CCY_MISMATCH_001",
            guarantee_type="bank_guarantee",
            guarantor="INST_DE_001",  # Deutsche Bank
            currency="EUR",
            maturity_date=date(2029, 12, 31),
            amount_covered=400_000.0,  # EUR amount
            percentage_covered=0.40,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_C",
        ),
        # =============================================================================
        # CRR-H4: Full CRM Chain - Bank Guarantee
        # Part of combined CRM: provision + cash + guarantee
        # £2m gross, £100k provision, £500k cash, £400k bank guarantee (CQS 2 = 30%)
        # Net exposure after cash/prov = £1.4m
        # Guaranteed: £400k at 30% RW, Non-guaranteed: £1m at 100% RW
        # =============================================================================
        Guarantee(
            guarantee_reference="GUAR_CRM_FULL_BANK",
            guarantee_type="bank_guarantee",
            guarantor="INST_UK_003",  # Metro Bank - CQS 2 (30% RW UK deviation)
            currency="GBP",
            maturity_date=date(2030, 1, 1),  # Maturity >= loan maturity
            amount_covered=400_000.0,  # £400k guaranteed
            percentage_covered=0.2857,  # 400k / 1.4m net exposure ≈ 28.57%
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CRM_FULL",
        ),
    ]


def save_guarantees(output_dir: Path | None = None) -> Path:
    """
    Create and save guarantees to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/guarantee directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_guarantees()
    output_path = output_dir / "guarantee.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved guarantees to: {output_path}")
    print(f"\nCreated {len(df)} guarantees:")

    print("\nBy guarantee type:")
    type_counts = df.group_by("guarantee_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['guarantee_type']}: {row['len']}")

    print("\nBy beneficiary type:")
    ben_counts = df.group_by("beneficiary_type").len().sort("beneficiary_type")
    for row in ben_counts.iter_rows(named=True):
        print(f"  {row['beneficiary_type']}: {row['len']}")

    print("\nTotal amount covered by type:")
    value_totals = (
        df.group_by("guarantee_type")
        .agg(pl.col("amount_covered").sum().alias("total_covered"))
        .sort("guarantee_type")
    )
    for row in value_totals.iter_rows(named=True):
        print(f"  {row['guarantee_type']}: GBP {row['total_covered']:,.0f}")

    print("\nCoverage distribution:")
    full_coverage = df.filter(pl.col("percentage_covered") == 1.0).height
    partial_coverage = df.filter(pl.col("percentage_covered") < 1.0).height
    print(f"  Full coverage (100%): {full_coverage}")
    print(f"  Partial coverage: {partial_coverage}")


if __name__ == "__main__":
    main()
