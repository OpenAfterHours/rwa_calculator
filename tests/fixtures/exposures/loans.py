"""
Generate loan test fixtures for exposure hierarchy testing.

The output will be saved as `loans.parquet` ready to get picked up within the wider
testing process.

Loans are drawn exposures that can be:
    - Standalone (no parent facility)
    - Under a facility (linked via facility_mapping)

Loan types for testing:
    - Term loans
    - Drawn portions of revolving facilities
    - Mortgages
    - Subordinated loans

Usage:
    uv run python tests/fixtures/exposures/loans.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import LOAN_SCHEMA


def main() -> None:
    """Entry point for loans generation."""
    output_path = save_loans()
    print_summary(output_path)


@dataclass(frozen=True)
class Loan:
    """A drawn loan exposure."""

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    lgd: float
    beel: float
    seniority: str

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
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
        }


VALUE_DATE = date(2026, 1, 1)


def create_loans() -> pl.DataFrame:
    """
    Create loan test data.

    Returns:
        pl.DataFrame: Loans matching LOAN_SCHEMA
    """
    loans = [
        *_sovereign_loans(),
        *_institution_loans(),
        *_corporate_standalone_loans(),
        *_corporate_facility_loans(),
        *_retail_loans(),
        *_hierarchy_test_loans(),
        *_defaulted_loans(),
    ]

    return pl.DataFrame([ln.to_dict() for ln in loans], schema=LOAN_SCHEMA)


def _sovereign_loans() -> list[Loan]:
    """
    Standalone loans to sovereign counterparties.

    Scenario A1: UK Sovereign with CQS1 = 0% RW
    """
    return [
        # UK Government loan - 0% RW (Scenario A1)
        Loan(
            loan_reference="LOAN_SOV_UK_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # US Government loan
        Loan(
            loan_reference="LOAN_SOV_US_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_US_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="USD",
            drawn_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Lower rated sovereign - Brazil (CQS 4, 100% RW)
        Loan(
            loan_reference="LOAN_SOV_BR_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_BR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="USD",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _institution_loans() -> list[Loan]:
    """
    Loans to institution counterparties.

    Scenario A4: UK Institution CQS2 = 30% RW (UK deviation)
    """
    return [
        # UK Bank loan - Barclays (CQS 1, 20% RW)
        Loan(
            loan_reference="LOAN_INST_UK_001",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),
            currency="GBP",
            drawn_amount=50_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # UK Bank loan - Metro Bank (CQS 2, 30% RW - UK deviation) (Scenario A4)
        Loan(
            loan_reference="LOAN_INST_UK_003",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Unrated institution loan - 40% RW
        Loan(
            loan_reference="LOAN_INST_UR_001",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 12, 31),
            currency="GBP",
            drawn_amount=10_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _corporate_standalone_loans() -> list[Loan]:
    """
    Standalone loans to corporate counterparties (not under facility).

    Scenario A2: Unrated corporate = 100% RW
    Scenario A3: Rated corporate CQS2 = 50% RW
    """
    return [
        # Unrated corporate loan - 100% RW (Scenario A2)
        Loan(
            loan_reference="LOAN_CORP_UR_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Rated corporate CQS 2 - 50% RW (Scenario A3)
        Loan(
            loan_reference="LOAN_CORP_UK_003",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Large corporate CQS 1 - 20% RW
        Loan(
            loan_reference="LOAN_CORP_UK_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 3, 31),
            currency="GBP",
            drawn_amount=25_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Subordinated loan - 75% LGD
        Loan(
            loan_reference="LOAN_CORP_SUB_001",
            product_type="SUBORDINATED_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 3, 31),
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.75,
            beel=0.0,
            seniority="subordinated",
        ),
        # SME Corporate loans
        Loan(
            loan_reference="LOAN_CORP_SME_001",
            product_type="SME_TERM_LOAN",
            book_code="SME_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _corporate_facility_loans() -> list[Loan]:
    """
    Loans drawn under corporate facilities.

    These loans are linked to facilities via facility_mapping.
    """
    return [
        # Drawn under FAC_CORP_001 (BP RCF)
        Loan(
            loan_reference="LOAN_FAC_CORP_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            drawn_amount=20_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Drawn under FAC_CORP_002 (Unilever term)
        Loan(
            loan_reference="LOAN_FAC_CORP_002_A",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 6, 30),
            currency="GBP",
            drawn_amount=30_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Drawn under FAC_CORP_SME_001
        Loan(
            loan_reference="LOAN_FAC_SME_001_A",
            product_type="RCF_DRAWING",
            book_code="SME_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _retail_loans() -> list[Loan]:
    """
    Loans to retail counterparties.

    Scenario A5: Residential mortgage 60% LTV = 20% RW
    Scenario A6: Residential mortgage 85% LTV = 35% RW
    Scenario A9: Retail exposure = 75% RW
    Scenario A10: SME retail = 75% RW
    """
    return [
        # Standard retail loan (Scenario A9)
        Loan(
            loan_reference="LOAN_RTL_IND_001",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_IND_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),
            currency="GBP",
            drawn_amount=50_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Residential mortgage 60% LTV (Scenario A5)
        Loan(
            loan_reference="LOAN_RTL_MTG_001",
            product_type="RESIDENTIAL_MORTGAGE",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference="RTL_MTG_001",
            value_date=VALUE_DATE,
            maturity_date=date(2051, 1, 1),
            currency="GBP",
            drawn_amount=500_000.0,  # Property value £833,333, LTV 60%
            lgd=0.10,
            beel=0.0,
            seniority="senior",
        ),
        # Residential mortgage 85% LTV (Scenario A6)
        Loan(
            loan_reference="LOAN_RTL_MTG_002",
            product_type="RESIDENTIAL_MORTGAGE",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference="RTL_MTG_002",
            value_date=VALUE_DATE,
            maturity_date=date(2051, 1, 1),
            currency="GBP",
            drawn_amount=850_000.0,  # Property value £1,000,000, LTV 85%
            lgd=0.10,
            beel=0.0,
            seniority="senior",
        ),
        # SME retail loan (Scenario A10)
        Loan(
            loan_reference="LOAN_RTL_SME_001",
            product_type="SME_LOAN",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # QRRE - credit card balance
        Loan(
            loan_reference="LOAN_RTL_QRRE_001",
            product_type="CREDIT_CARD",
            book_code="RETAIL_CARDS",
            counterparty_reference="RTL_QRRE_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 1, 1),
            currency="GBP",
            drawn_amount=5_000.0,
            lgd=0.85,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _hierarchy_test_loans() -> list[Loan]:
    """
    Loans specifically for exposure hierarchy testing.

    Scenario H1: Facility with multiple loans - £5m facility, 3 loans drawn
    """
    return [
        # =============================================================================
        # HIERARCHY TEST 1: Multiple loans under single facility (FAC_HIER_001)
        # Tests aggregation of loans at facility level
        # Total drawn: £1.5m + £2.0m + £1.0m = £4.5m under £5m limit
        # =============================================================================
        Loan(
            loan_reference="LOAN_HIER_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_001_B",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_001_C",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # HIERARCHY TEST 2: Loans under sub-facilities
        # Tests multi-level facility hierarchy
        # =============================================================================
        Loan(
            loan_reference="LOAN_HIER_SUB_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB1",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_SUB_002_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB2",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            drawn_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # HIERARCHY TEST 3: Lending group loans
        # Loans to connected retail parties for threshold aggregation
        # =============================================================================
        Loan(
            loan_reference="LOAN_LG2_OWNER",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_LG2_OWNER",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=80_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_LG2_COMPANY",
            product_type="SME_LOAN",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_LG2_COMPANY",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=350_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _defaulted_loans() -> list[Loan]:
    """
    Loans to defaulted counterparties.

    Tests defaulted exposure treatment.
    """
    return [
        Loan(
            loan_reference="LOAN_DF_CORP_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_DF_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 12, 31),
            currency="GBP",
            drawn_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_DF_RTL_001",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_DF_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            drawn_amount=25_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def save_loans(output_dir: Path | None = None) -> Path:
    """
    Create and save loans to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/exposures directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_loans()
    output_path = output_dir / "loans.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved loans to: {output_path}")
    print(f"\nCreated {len(df)} loans:")

    print("\nBy product type:")
    type_counts = df.group_by("product_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['product_type']}: {row['len']}")

    print("\nBy book code:")
    book_counts = df.group_by("book_code").len().sort("book_code")
    for row in book_counts.iter_rows(named=True):
        print(f"  {row['book_code']}: {row['len']}")

    print("\nTotal drawn by book:")
    book_totals = df.group_by("book_code").agg(pl.col("drawn_amount").sum().alias("total_drawn")).sort("book_code")
    for row in book_totals.iter_rows(named=True):
        print(f"  {row['book_code']}: £{row['total_drawn']:,.0f}")


if __name__ == "__main__":
    main()
