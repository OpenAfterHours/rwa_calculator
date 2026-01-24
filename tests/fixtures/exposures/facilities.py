"""
Generate facility test fixtures for exposure hierarchy testing.

The output will be saved as `facilities.parquet` ready to get picked up within the wider
testing process.

Facilities are committed credit limits that act as parent nodes in the exposure hierarchy.
Loans and contingents can be drawn under facilities.

Facility types for testing:
    - Revolving credit facilities (RCF)
    - Term loan facilities
    - Uncommitted facilities (unconditionally cancellable)
    - Subordinated facilities

Usage:
    uv run python tests/fixtures/exposures/facilities.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import FACILITY_SCHEMA


def main() -> None:
    """Entry point for facilities generation."""
    output_path = save_facilities()
    print_summary(output_path)


@dataclass(frozen=True)
class Facility:
    """A credit facility."""

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    lgd: float
    beel: float
    is_revolving: bool
    seniority: str
    risk_type: str  # FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    ccf_modelled: float | None = None  # Optional: A-IRB modelled CCF (0.0-1.5, Retail can exceed 100%)
    is_short_term_trade_lc: bool | None = None  # Art. 166(9): short-term LC for goods = 20% under F-IRB

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
            "lgd": self.lgd,
            "beel": self.beel,
            "is_revolving": self.is_revolving,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "ccf_modelled": self.ccf_modelled,
            "is_short_term_trade_lc": self.is_short_term_trade_lc,
        }


VALUE_DATE = date(2026, 1, 1)


def create_facilities() -> pl.DataFrame:
    """
    Create facility test data.

    Returns:
        pl.DataFrame: Facilities matching FACILITY_SCHEMA
    """
    facilities = [
        *_corporate_facilities(),
        *_institution_facilities(),
        *_retail_facilities(),
        *_hierarchy_test_facilities(),
        *_complex_scenario_facilities(),
    ]

    return pl.DataFrame([f.to_dict() for f in facilities], schema=FACILITY_SCHEMA)


def _corporate_facilities() -> list[Facility]:
    """
    Facilities for corporate counterparties.

    Includes:
        - Large corporate RCFs
        - SME term facilities
        - Subordinated facilities for LGD testing
    """
    return [
        # Large corporate RCF - BP
        Facility(
            facility_reference="FAC_CORP_001",
            product_type="RCF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            limit=50_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn (50% SA, 75% F-IRB)
        ),
        # Large corporate term facility - Unilever
        Facility(
            facility_reference="FAC_CORP_002",
            product_type="TERM_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 6, 30),
            currency="GBP",
            limit=30_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=False,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # SME corporate facility
        Facility(
            facility_reference="FAC_CORP_SME_001",
            product_type="RCF",
            book_code="SME_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            limit=5_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # Subordinated facility - for LGD testing (75% vs 45%)
        Facility(
            facility_reference="FAC_CORP_SUB_001",
            product_type="SUBORDINATED_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 3, 31),
            currency="GBP",
            limit=10_000_000.0,
            committed=True,
            lgd=0.75,
            beel=0.0,
            is_revolving=False,
            seniority="subordinated",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # Uncommitted facility - 0% CCF for unconditionally cancellable
        Facility(
            facility_reference="FAC_CORP_UNCOMMIT_001",
            product_type="UNCOMMITTED_RCF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_004",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            limit=2_000_000.0,
            committed=False,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="LR",  # Low risk - unconditionally cancellable (0% CCF)
        ),
        # Unrated corporate facility (Scenario A2)
        Facility(
            facility_reference="FAC_CORP_UNRATED_001",
            product_type="TERM_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            limit=1_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=False,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
    ]


def _institution_facilities() -> list[Facility]:
    """
    Facilities for institution counterparties.

    Interbank lending facilities.
    """
    return [
        # Interbank facility - Barclays
        Facility(
            facility_reference="FAC_INST_001",
            product_type="INTERBANK_FACILITY",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),
            currency="GBP",
            limit=100_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # Short-term facility for preferential RW testing
        Facility(
            facility_reference="FAC_INST_002",
            product_type="SHORT_TERM_FACILITY",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 4, 1),  # 3 months
            currency="GBP",
            limit=50_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=False,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
    ]


def _retail_facilities() -> list[Facility]:
    """
    Facilities for retail counterparties.

    Includes:
        - Mortgage facilities
        - SME retail facilities
        - Credit card facilities (QRRE)
    """
    return [
        # Mortgage facility
        Facility(
            facility_reference="FAC_RTL_MTG_001",
            product_type="MORTGAGE_FACILITY",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference="RTL_MTG_001",
            value_date=VALUE_DATE,
            maturity_date=date(2051, 1, 1),
            currency="GBP",
            limit=500_000.0,
            committed=True,
            lgd=0.10,
            beel=0.0,
            is_revolving=False,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # SME retail facility
        Facility(
            facility_reference="FAC_RTL_SME_001",
            product_type="SME_FACILITY",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            limit=500_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # Credit card facility (QRRE)
        Facility(
            facility_reference="FAC_RTL_QRRE_001",
            product_type="CREDIT_CARD",
            book_code="RETAIL_CARDS",
            counterparty_reference="RTL_QRRE_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 1, 1),
            currency="GBP",
            limit=10_000.0,
            committed=True,
            lgd=0.85,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="LR",  # Low risk - unconditionally cancellable (0% CCF)
        ),
    ]


def _hierarchy_test_facilities() -> list[Facility]:
    """
    Facilities specifically for exposure hierarchy testing.

    Tests:
        - Facility with multiple loans (H1 scenario)
        - Parent facility with sub-facilities
        - Facilities for lending group counterparties
    """
    return [
        # =============================================================================
        # HIERARCHY TEST 1: Facility with multiple loans
        # Scenario H1 from plan: £5m facility with 3 loans drawn
        # =============================================================================
        Facility(
            facility_reference="FAC_HIER_001",
            product_type="RCF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            limit=5_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # =============================================================================
        # HIERARCHY TEST 2: Parent facility with sub-facility
        # Tests multi-level facility hierarchy
        # =============================================================================
        Facility(
            facility_reference="FAC_HIER_PARENT_001",
            product_type="MASTER_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_ULTIMATE",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            limit=20_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        Facility(
            facility_reference="FAC_HIER_SUB_001",
            product_type="SUB_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB1",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            limit=8_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        Facility(
            facility_reference="FAC_HIER_SUB_002",
            product_type="SUB_FACILITY",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB2",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            limit=5_000_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        # =============================================================================
        # HIERARCHY TEST 3: Lending group facilities
        # Facilities for connected retail counterparties
        # =============================================================================
        Facility(
            facility_reference="FAC_LG2_OWNER",
            product_type="PERSONAL_LOAN_FACILITY",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_LG2_OWNER",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            limit=100_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=False,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
        Facility(
            facility_reference="FAC_LG2_COMPANY",
            product_type="SME_FACILITY",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_LG2_COMPANY",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            limit=400_000.0,
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn
        ),
    ]


def _complex_scenario_facilities() -> list[Facility]:
    """
    Facilities for CRR-H complex scenario testing.

    CRR-H1: Facility with multiple loans
        - £5m limit, £4m drawn (3 loans), £1m undrawn (50% CCF)
        - Total EAD = £4.5m
    """
    return [
        # =============================================================================
        # CRR-H1: Facility with Multiple Loans
        # Tests aggregation of loans at facility level
        # Limit: £5m, Drawn: £4m, Undrawn: £1m (50% CCF = £0.5m EAD)
        # Total EAD: £4.5m
        # =============================================================================
        Facility(
            facility_reference="FAC_MULTI_001",
            product_type="RCF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_FAC_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            limit=5_000_000.0,  # £5m limit
            committed=True,
            lgd=0.45,
            beel=0.0,
            is_revolving=True,
            seniority="senior",
            risk_type="MR",  # Medium risk - committed undrawn (50% SA, 75% F-IRB)
        ),
    ]


def save_facilities(output_dir: Path | None = None) -> Path:
    """
    Create and save facilities to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/exposures directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_facilities()
    output_path = output_dir / "facilities.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved facilities to: {output_path}")
    print(f"\nCreated {len(df)} facilities:")

    print("\nBy product type:")
    type_counts = df.group_by("product_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['product_type']}: {row['len']}")

    print("\nBy seniority:")
    sen_counts = df.group_by("seniority").len().sort("seniority")
    for row in sen_counts.iter_rows(named=True):
        print(f"  {row['seniority']}: {row['len']}")

    print("\nTotal limit by book:")
    book_totals = df.group_by("book_code").agg(pl.col("limit").sum().alias("total_limit")).sort("book_code")
    for row in book_totals.iter_rows(named=True):
        print(f"  {row['book_code']}: £{row['total_limit']:,.0f}")


if __name__ == "__main__":
    main()
