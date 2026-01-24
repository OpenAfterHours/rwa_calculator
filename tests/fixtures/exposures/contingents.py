"""
Generate contingent (off-balance sheet) test fixtures for exposure testing.

The output will be saved as `contingents.parquet` ready to get picked up within the wider
testing process.

Contingents are off-balance sheet exposures that require Credit Conversion Factors (CCF):
    - Letters of credit (trade/standby)
    - Guarantees issued
    - Undrawn commitments
    - Note issuance facilities
    - Trade finance items

CCF categories (Basel SA):
    - 0%: Unconditionally cancellable commitments
    - 20%: Short-term self-liquidating trade letters of credit
    - 40%: Undrawn committed facilities (>1yr), note issuance facilities
    - 50%: Transaction-related contingents, trade-related contingents
    - 100%: Direct credit substitutes, acceptances, standby LCs

Usage:
    uv run python tests/fixtures/exposures/contingents.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import CONTINGENTS_SCHEMA


def main() -> None:
    """Entry point for contingents generation."""
    output_path = save_contingents()
    print_summary(output_path)


@dataclass(frozen=True)
class Contingent:
    """An off-balance sheet contingent exposure."""

    contingent_reference: str
    contract_type: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    nominal_amount: float
    lgd: float
    beel: float
    ccf_category: str
    seniority: str
    risk_type: str = "MR"  # Default to MR, should be set based on ccf_category
    ccf_modelled: float | None = None  # Optional: A-IRB modelled CCF (0.0-1.5, Retail can exceed 100%)
    is_short_term_trade_lc: bool | None = None  # Art. 166(9): short-term LC for goods = 20% under F-IRB

    def to_dict(self) -> dict:
        return {
            "contingent_reference": self.contingent_reference,
            "contract_type": self.contract_type,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "nominal_amount": self.nominal_amount,
            "lgd": self.lgd,
            "beel": self.beel,
            "ccf_category": self.ccf_category,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "ccf_modelled": self.ccf_modelled,
            "is_short_term_trade_lc": self.is_short_term_trade_lc,
        }


VALUE_DATE = date(2026, 1, 1)


def create_contingents() -> pl.DataFrame:
    """
    Create contingent test data.

    Returns:
        pl.DataFrame: Contingents matching CONTINGENTS_SCHEMA
    """
    contingents = [
        *_trade_finance_contingents(),
        *_guarantee_contingents(),
        *_commitment_contingents(),
        *_ccf_test_contingents(),
    ]

    return pl.DataFrame([c.to_dict() for c in contingents], schema=CONTINGENTS_SCHEMA)


def _trade_finance_contingents() -> list[Contingent]:
    """
    Trade finance contingents - typically 20-50% CCF.

    Documentary letters of credit and trade-related items.
    """
    return [
        # Documentary LC - short-term trade (20% CCF under SA and F-IRB per Art. 166(9))
        Contingent(
            contingent_reference="CONT_TF_001",
            contract_type="documentary_lc",
            product_type="TRADE_LC",
            book_code="TRADE_FINANCE",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 6, 30),
            currency="GBP",
            nominal_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="trade_lc_short_term",
            seniority="senior",
            risk_type="MLR",  # Medium-low risk
            is_short_term_trade_lc=True,  # Art. 166(9) exception - retains 20% under F-IRB
        ),
        # Import LC for SME
        Contingent(
            contingent_reference="CONT_TF_002",
            contract_type="documentary_lc",
            product_type="IMPORT_LC",
            book_code="TRADE_FINANCE",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 9, 30),
            currency="USD",
            nominal_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="trade_lc_short_term",
            seniority="senior",
            risk_type="MLR",  # Medium-low risk
            is_short_term_trade_lc=True,  # Art. 166(9) exception - retains 20% under F-IRB
        ),
        # Shipping guarantee (50% CCF)
        Contingent(
            contingent_reference="CONT_TF_003",
            contract_type="shipping_guarantee",
            product_type="SHIPPING_GUAR",
            book_code="TRADE_FINANCE",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 4, 30),
            currency="GBP",
            nominal_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="trade_related",
            seniority="senior",
        ),
    ]


def _guarantee_contingents() -> list[Contingent]:
    """
    Guarantee contingents - 50-100% CCF depending on type.

    Financial guarantees, performance bonds, bid bonds.
    """
    return [
        # Financial guarantee (100% CCF - direct credit substitute)
        Contingent(
            contingent_reference="CONT_GUAR_001",
            contract_type="financial_guarantee",
            product_type="FIN_GUARANTEE",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            nominal_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="direct_credit_substitute",
            seniority="senior",
        ),
        # Standby LC (100% CCF)
        Contingent(
            contingent_reference="CONT_GUAR_002",
            contract_type="standby_lc",
            product_type="STANDBY_LC",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            nominal_amount=10_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="direct_credit_substitute",
            seniority="senior",
        ),
        # Performance bond (50% CCF)
        Contingent(
            contingent_reference="CONT_GUAR_003",
            contract_type="performance_bond",
            product_type="PERF_BOND",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 12, 31),
            currency="GBP",
            nominal_amount=1_500_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="transaction_related",
            seniority="senior",
        ),
        # Bid bond (50% CCF)
        Contingent(
            contingent_reference="CONT_GUAR_004",
            contract_type="bid_bond",
            product_type="BID_BOND",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 6, 30),
            currency="GBP",
            nominal_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="transaction_related",
            seniority="senior",
        ),
    ]


def _commitment_contingents() -> list[Contingent]:
    """
    Undrawn commitment contingents - 0-40% CCF depending on terms.

    Note: These are separate from facility undrawn amounts.
    """
    return [
        # Committed undrawn facility >1yr (40% CCF)
        Contingent(
            contingent_reference="CONT_COMMIT_001",
            contract_type="committed_facility",
            product_type="UNDRAWN_COMMIT",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_004",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),
            currency="GBP",
            nominal_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="committed_facility",
            seniority="senior",
        ),
        # Note issuance facility (40% CCF)
        Contingent(
            contingent_reference="CONT_COMMIT_002",
            contract_type="note_issuance_facility",
            product_type="NIF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 6, 30),
            currency="GBP",
            nominal_amount=20_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="nif_ruf",
            seniority="senior",
        ),
        # Unconditionally cancellable commitment (0% CCF)
        Contingent(
            contingent_reference="CONT_COMMIT_003",
            contract_type="uncommitted_facility",
            product_type="UNCOMMIT_LINE",
            book_code="RETAIL_CARDS",
            counterparty_reference="RTL_QRRE_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 1, 1),
            currency="GBP",
            nominal_amount=5_000.0,  # Undrawn credit card limit
            lgd=0.85,
            beel=0.0,
            ccf_category="unconditionally_cancellable",
            seniority="senior",
        ),
        # SME retail undrawn commitment
        Contingent(
            contingent_reference="CONT_COMMIT_004",
            contract_type="uncommitted_facility",
            product_type="UNCOMMIT_LINE",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            nominal_amount=100_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="unconditionally_cancellable",
            seniority="senior",
        ),
    ]


def _ccf_test_contingents() -> list[Contingent]:
    """
    Contingents specifically for CCF testing across all categories.

    Covers 0%, 20%, 40%, 50%, 100% CCF scenarios with explicit risk_type.

    Risk Type Mapping:
    - LR (low_risk): 0% CCF - unconditionally cancellable
    - MLR (medium_low_risk): 20% CCF - documentary credits, trade finance
    - MR (medium_risk): 50% CCF - NIFs, RUFs, committed undrawn
    - FR (full_risk): 100% CCF - direct credit substitutes, guarantees
    """
    return [
        # =============================================================================
        # CCF 0%: Unconditionally cancellable (retail)
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_0PCT",
            contract_type="uncommitted_facility",
            product_type="UNCOMMIT_OVERDRAFT",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_IND_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 1, 1),
            currency="GBP",
            nominal_amount=2_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="unconditionally_cancellable",
            seniority="senior",
            risk_type="LR",  # Low risk = 0% CCF
        ),
        # =============================================================================
        # CCF 20%: Short-term self-liquidating trade LC (standard MLR, no exception)
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_20PCT",
            contract_type="documentary_lc",
            product_type="EXPORT_LC",
            book_code="TRADE_FINANCE",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 4, 1),
            currency="USD",
            nominal_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="trade_lc_short_term",
            seniority="senior",
            risk_type="MLR",  # Medium-low risk = 20% CCF (SA), 75% (F-IRB)
            is_short_term_trade_lc=False,  # NOT a goods-movement LC, so 75% under F-IRB
        ),
        # =============================================================================
        # CCF 20% F-IRB Exception: Short-term trade LC for goods movement (Art. 166(9))
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_20PCT_FIRB",
            contract_type="documentary_lc",
            product_type="IMPORT_LC",
            book_code="TRADE_FINANCE",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 5, 1),
            currency="GBP",
            nominal_amount=4_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="trade_lc_short_term",
            seniority="senior",
            risk_type="MLR",  # Medium-low risk = 20% CCF under BOTH SA and F-IRB
            is_short_term_trade_lc=True,  # Art. 166(9) exception - retains 20% under F-IRB
        ),
        # =============================================================================
        # CCF 40%/50%: Committed undrawn facility
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_40PCT",
            contract_type="committed_facility",
            product_type="UNDRAWN_RCF",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            nominal_amount=500_000.0,  # Undrawn portion of FAC_HIER_001
            lgd=0.45,
            beel=0.0,
            ccf_category="committed_facility",
            seniority="senior",
            risk_type="MR",  # Medium risk = 50% CCF (SA), 75% (F-IRB)
        ),
        # =============================================================================
        # CCF 50%: Transaction-related contingent
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_50PCT",
            contract_type="advance_payment_guarantee",
            product_type="APG",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB1",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            nominal_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="transaction_related",
            seniority="senior",
            risk_type="MR",  # Medium risk = 50% CCF (SA), 75% (F-IRB)
        ),
        # =============================================================================
        # CCF 100%: Direct credit substitute (acceptance)
        # =============================================================================
        Contingent(
            contingent_reference="CONT_CCF_100PCT",
            contract_type="acceptance",
            product_type="BANKERS_ACCEPT",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2026, 7, 1),
            currency="GBP",
            nominal_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            ccf_category="direct_credit_substitute",
            seniority="senior",
            risk_type="FR",  # Full risk = 100% CCF
        ),
        # Subordinated contingent for LGD testing
        Contingent(
            contingent_reference="CONT_SUB_001",
            contract_type="financial_guarantee",
            product_type="FIN_GUARANTEE",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            nominal_amount=2_000_000.0,
            lgd=0.75,
            beel=0.0,
            ccf_category="direct_credit_substitute",
            seniority="subordinated",
            risk_type="FR",  # Full risk = 100% CCF
        ),
    ]


def save_contingents(output_dir: Path | None = None) -> Path:
    """
    Create and save contingents to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/exposures directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_contingents()
    output_path = output_dir / "contingents.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved contingents to: {output_path}")
    print(f"\nCreated {len(df)} contingents:")

    print("\nBy contract type:")
    type_counts = df.group_by("contract_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['contract_type']}: {row['len']}")

    print("\nBy CCF category:")
    ccf_counts = df.group_by("ccf_category").len().sort("ccf_category")
    for row in ccf_counts.iter_rows(named=True):
        print(f"  {row['ccf_category']}: {row['len']}")

    print("\nBy book code:")
    book_counts = df.group_by("book_code").len().sort("book_code")
    for row in book_counts.iter_rows(named=True):
        print(f"  {row['book_code']}: {row['len']}")

    print("\nTotal nominal by CCF category:")
    ccf_totals = (
        df.group_by("ccf_category")
        .agg(pl.col("nominal_amount").sum().alias("total_nominal"))
        .sort("ccf_category")
    )
    for row in ccf_totals.iter_rows(named=True):
        print(f"  {row['ccf_category']}: GBP {row['total_nominal']:,.0f}")


if __name__ == "__main__":
    main()
