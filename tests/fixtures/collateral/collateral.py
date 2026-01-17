"""
Generate collateral test fixtures for credit risk mitigation testing.

The output will be saved as `collateral.parquet` ready to get picked up within the wider
testing process.

Collateral types for testing:
    - Cash collateral (0% haircut)
    - Government bonds (supervisory haircuts by maturity)
    - Equity (25% haircut for main index)
    - Real estate (residential/commercial, LTV-based)
    - Receivables (IRB eligible)

CRM scenarios covered:
    D1: Cash collateral (SA) - £500k cash against £1m exposure
    D2: Government bond collateral - £600k gilts with maturity haircut
    D3: Equity collateral - £400k listed equity, 25% haircut
    D5: Maturity mismatch - 2yr collateral against 5yr exposure
    D6: Currency mismatch - EUR collateral against GBP exposure
    B2: Corporate with financial collateral (IRB)
    B3: Corporate with real estate (FIRB)
    A5/A6: Residential mortgages with different LTVs

Usage:
    uv run python tests/fixtures/collateral/collateral.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import COLLATERAL_SCHEMA


def main() -> None:
    """Entry point for collateral generation."""
    output_path = save_collateral()
    print_summary(output_path)


@dataclass(frozen=True)
class Collateral:
    """A collateral item for credit risk mitigation."""

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date | None
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_cqs: int | None
    issuer_type: str | None
    residual_maturity_years: float | None
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    valuation_date: date
    valuation_type: str
    property_type: str | None
    property_ltv: float | None
    is_income_producing: bool | None
    is_adc: bool | None
    is_presold: bool | None

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
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
            "property_type": self.property_type,
            "property_ltv": self.property_ltv,
            "is_income_producing": self.is_income_producing,
            "is_adc": self.is_adc,
            "is_presold": self.is_presold,
        }


VALUE_DATE = date(2026, 1, 1)


def create_collateral() -> pl.DataFrame:
    """
    Create collateral test data.

    Returns:
        pl.DataFrame: Collateral matching COLLATERAL_SCHEMA
    """
    collateral = [
        *_cash_collateral(),
        *_government_bond_collateral(),
        *_equity_collateral(),
        *_residential_real_estate(),
        *_commercial_real_estate(),
        *_receivables_collateral(),
        *_crm_test_collateral(),
    ]

    return pl.DataFrame([c.to_dict() for c in collateral], schema=COLLATERAL_SCHEMA)


def _cash_collateral() -> list[Collateral]:
    """
    Cash collateral - 0% haircut, highest quality CRM.

    Scenario D1: Cash collateral against corporate exposure.
    """
    return [
        # D1: Cash collateral for corporate loan - £500k cash
        Collateral(
            collateral_reference="COLL_CASH_001",
            collateral_type="cash",
            currency="GBP",
            maturity_date=None,
            market_value=500_000.0,
            nominal_value=500_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_UK_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Cash collateral for SME loan
        Collateral(
            collateral_reference="COLL_CASH_002",
            collateral_type="cash",
            currency="GBP",
            maturity_date=None,
            market_value=200_000.0,
            nominal_value=200_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_SME_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
    ]


def _government_bond_collateral() -> list[Collateral]:
    """
    Government bond collateral - supervisory haircuts by residual maturity.

    Scenario D2: UK gilts collateral.
    Haircuts (CRE22.52): <=1yr: 0.5%, 1-3yr: 2%, 3-5yr: 4%, 5-10yr: 4%, >10yr: 12%
    """
    return [
        # D2: UK Gilts 5-year - 4% haircut
        Collateral(
            collateral_reference="COLL_GILT_001",
            collateral_type="bond",
            currency="GBP",
            maturity_date=date(2031, 1, 1),
            market_value=600_000.0,
            nominal_value=600_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_UK_003",
            issuer_cqs=1,
            issuer_type="sovereign",
            residual_maturity_years=5.0,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Short-term gilt - 0.5% haircut
        Collateral(
            collateral_reference="COLL_GILT_002",
            collateral_type="bond",
            currency="GBP",
            maturity_date=date(2026, 6, 1),
            market_value=1_000_000.0,
            nominal_value=1_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_INST_UK_001",
            issuer_cqs=1,
            issuer_type="sovereign",
            residual_maturity_years=0.4,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # US Treasury bond - 2% haircut (1-3yr)
        Collateral(
            collateral_reference="COLL_UST_001",
            collateral_type="bond",
            currency="USD",
            maturity_date=date(2028, 6, 1),
            market_value=800_000.0,
            nominal_value=800_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_SOV_US_001",
            issuer_cqs=1,
            issuer_type="sovereign",
            residual_maturity_years=2.4,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
    ]


def _equity_collateral() -> list[Collateral]:
    """
    Equity collateral - 25% haircut for main index equities.

    Scenario D3: Listed equity collateral.
    """
    return [
        # D3: Listed equity (FTSE 100) - 25% haircut
        Collateral(
            collateral_reference="COLL_EQ_001",
            collateral_type="equity",
            currency="GBP",
            maturity_date=None,
            market_value=400_000.0,
            nominal_value=400_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_UR_001",
            issuer_cqs=None,
            issuer_type="corporate",
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Listed equity for subordinated loan
        Collateral(
            collateral_reference="COLL_EQ_002",
            collateral_type="equity",
            currency="GBP",
            maturity_date=None,
            market_value=1_000_000.0,
            nominal_value=1_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_CORP_SUB_001",
            issuer_cqs=None,
            issuer_type="corporate",
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
    ]


def _residential_real_estate() -> list[Collateral]:
    """
    Residential real estate collateral for mortgages.

    Scenario A5: 60% LTV residential = 20% RW
    Scenario A6: 85% LTV residential = 35% RW
    """
    return [
        # A5: Residential property 60% LTV (£500k loan / £833,333 property)
        Collateral(
            collateral_reference="COLL_RRE_001",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=833_333.0,
            nominal_value=833_333.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_RTL_MTG_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="residential",
            property_ltv=0.60,
            is_income_producing=False,
            is_adc=False,
            is_presold=None,
        ),
        # A6: Residential property 85% LTV (£850k loan / £1,000,000 property)
        Collateral(
            collateral_reference="COLL_RRE_002",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=1_000_000.0,
            nominal_value=1_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_RTL_MTG_002",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="residential",
            property_ltv=0.85,
            is_income_producing=False,
            is_adc=False,
            is_presold=None,
        ),
        # Additional residential property for lending group testing
        Collateral(
            collateral_reference="COLL_RRE_003",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=350_000.0,
            nominal_value=350_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_LG2_OWNER",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="residential",
            property_ltv=0.23,
            is_income_producing=False,
            is_adc=False,
            is_presold=None,
        ),
    ]


def _commercial_real_estate() -> list[Collateral]:
    """
    Commercial real estate collateral.

    Scenario B3: Corporate with real estate - FIRB supervisory LGD.
    Different RW treatment for income-producing properties.
    """
    return [
        # B3: Commercial property for corporate loan (non-income producing)
        Collateral(
            collateral_reference="COLL_CRE_001",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=2_000_000.0,
            nominal_value=2_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_CORP_001_A",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="commercial",
            property_ltv=0.55,
            is_income_producing=False,
            is_adc=False,
            is_presold=None,
        ),
        # Income-producing commercial property
        Collateral(
            collateral_reference="COLL_CRE_002",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=5_000_000.0,
            nominal_value=5_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_CORP_002_A",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="commercial",
            property_ltv=0.60,
            is_income_producing=True,
            is_adc=False,
            is_presold=None,
        ),
        # ADC property (150% RW unless pre-sold)
        Collateral(
            collateral_reference="COLL_CRE_003",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=3_000_000.0,
            nominal_value=3_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_A",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="commercial",
            property_ltv=0.50,
            is_income_producing=False,
            is_adc=True,
            is_presold=False,
        ),
        # Pre-sold ADC property (100% RW)
        Collateral(
            collateral_reference="COLL_CRE_004",
            collateral_type="real_estate",
            currency="GBP",
            maturity_date=None,
            market_value=4_000_000.0,
            nominal_value=4_000_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_001_B",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="independent",
            property_type="commercial",
            property_ltv=0.50,
            is_income_producing=False,
            is_adc=True,
            is_presold=True,
        ),
    ]


def _receivables_collateral() -> list[Collateral]:
    """
    Receivables collateral - IRB eligible only.

    Supervisory LGD: 20% (FIRB), Floor 10% (AIRB).
    """
    return [
        # Trade receivables for SME loan
        Collateral(
            collateral_reference="COLL_REC_001",
            collateral_type="receivables",
            currency="GBP",
            maturity_date=date(2026, 4, 1),
            market_value=300_000.0,
            nominal_value=350_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_FAC_SME_001_A",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=0.25,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Invoice receivables for SME retail
        Collateral(
            collateral_reference="COLL_REC_002",
            collateral_type="receivables",
            currency="GBP",
            maturity_date=date(2026, 3, 1),
            market_value=100_000.0,
            nominal_value=120_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_RTL_SME_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=0.16,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
    ]


def _crm_test_collateral() -> list[Collateral]:
    """
    Collateral specifically for CRM scenario testing.

    D5: Maturity mismatch - 2yr collateral against 5yr exposure
    D6: Currency mismatch - EUR collateral against GBP exposure
    B2: Corporate with financial collateral (IRB)
    """
    return [
        # =============================================================================
        # D5: Maturity mismatch scenario
        # £500k collateral with 2yr residual against 5yr exposure
        # Adjustment factor: (t-0.25)/(T-0.25) = (1.75)/(4.75) = 0.368
        # =============================================================================
        Collateral(
            collateral_reference="COLL_MAT_MISMATCH_001",
            collateral_type="bond",
            currency="GBP",
            maturity_date=date(2028, 1, 1),  # 2yr maturity
            market_value=500_000.0,
            nominal_value=500_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_SUB_001_A",  # 5yr exposure
            issuer_cqs=1,
            issuer_type="sovereign",
            residual_maturity_years=2.0,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # =============================================================================
        # D6: Currency mismatch scenario
        # €500k collateral against GBP exposure - 8% FX haircut
        # =============================================================================
        Collateral(
            collateral_reference="COLL_CCY_MISMATCH_001",
            collateral_type="cash",
            currency="EUR",
            maturity_date=None,
            market_value=500_000.0,
            nominal_value=500_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_HIER_SUB_002_A",  # GBP exposure
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # =============================================================================
        # B2: Corporate with financial collateral (IRB testing)
        # £500k cash collateral, LGD=0% for cash portion
        # =============================================================================
        Collateral(
            collateral_reference="COLL_IRB_CORP_001",
            collateral_type="cash",
            currency="GBP",
            maturity_date=None,
            market_value=500_000.0,
            nominal_value=500_000.0,
            beneficiary_type="facility",
            beneficiary_reference="FAC_CORP_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Gold collateral (0% haircut like cash)
        Collateral(
            collateral_reference="COLL_GOLD_001",
            collateral_type="gold",
            currency="GBP",
            maturity_date=None,
            market_value=250_000.0,
            nominal_value=250_000.0,
            beneficiary_type="facility",
            beneficiary_reference="FAC_CORP_002",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Corporate bond collateral (CQS 3, higher haircut)
        Collateral(
            collateral_reference="COLL_CORP_BOND_001",
            collateral_type="bond",
            currency="GBP",
            maturity_date=date(2029, 1, 1),
            market_value=400_000.0,
            nominal_value=400_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_INST_UR_001",
            issuer_cqs=3,
            issuer_type="corporate",
            residual_maturity_years=3.0,
            is_eligible_financial_collateral=True,
            is_eligible_irb_collateral=True,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
        # Ineligible collateral (for testing exclusion)
        Collateral(
            collateral_reference="COLL_INELIG_001",
            collateral_type="other_physical",
            currency="GBP",
            maturity_date=None,
            market_value=100_000.0,
            nominal_value=100_000.0,
            beneficiary_type="loan",
            beneficiary_reference="LOAN_DF_CORP_001",
            issuer_cqs=None,
            issuer_type=None,
            residual_maturity_years=None,
            is_eligible_financial_collateral=False,
            is_eligible_irb_collateral=False,
            valuation_date=VALUE_DATE,
            valuation_type="market",
            property_type=None,
            property_ltv=None,
            is_income_producing=None,
            is_adc=None,
            is_presold=None,
        ),
    ]


def save_collateral(output_dir: Path | None = None) -> Path:
    """
    Create and save collateral to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/collateral directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_collateral()
    output_path = output_dir / "collateral.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved collateral to: {output_path}")
    print(f"\nCreated {len(df)} collateral items:")

    print("\nBy collateral type:")
    type_counts = df.group_by("collateral_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['collateral_type']}: {row['len']}")

    print("\nBy beneficiary type:")
    ben_counts = df.group_by("beneficiary_type").len().sort("beneficiary_type")
    for row in ben_counts.iter_rows(named=True):
        print(f"  {row['beneficiary_type']}: {row['len']}")

    print("\nTotal market value by type:")
    value_totals = (
        df.group_by("collateral_type")
        .agg(pl.col("market_value").sum().alias("total_value"))
        .sort("collateral_type")
    )
    for row in value_totals.iter_rows(named=True):
        print(f"  {row['collateral_type']}: £{row['total_value']:,.0f}")

    print("\nEligibility summary:")
    sa_eligible = df.filter(pl.col("is_eligible_financial_collateral")).height
    irb_eligible = df.filter(pl.col("is_eligible_irb_collateral")).height
    print(f"  SA eligible (financial collateral): {sa_eligible}")
    print(f"  IRB eligible: {irb_eligible}")

    print("\nReal estate breakdown:")
    re_df = df.filter(pl.col("collateral_type") == "real_estate")
    if re_df.height > 0:
        by_property = re_df.group_by("property_type").len().sort("property_type")
        for row in by_property.iter_rows(named=True):
            print(f"  {row['property_type']}: {row['len']}")


if __name__ == "__main__":
    main()
