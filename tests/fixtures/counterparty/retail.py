"""
This module creates the retail counterparties ready for testing.

The output will be saved as `retail.parquet` ready to get picked up within the wider testing
process.

The schemas can be used to support the structure of the outputs of this module.

Retail Risk Weights (SA) per CRE20.66-70:
    Standard Retail: 75%
    Retail Mortgage (varies by LTV): 20% - 70%
    QRRE (Qualifying Revolving Retail Exposures): 45%

Retail Classification Requirements:
    - Individual persons OR small businesses
    - Small business turnover < £880k (SME retail threshold)
    - Total exposure to counterparty/group < £1m
    - Part of a large pool of similarly managed exposures

Scenario A9 from plan: £50k loan to individual = £37.5k RWA (75% RW)
Scenario A10 from plan: £500k loan, SME turnover < £880k = £375k RWA (75% RW)
"""

import polars as pl
from pathlib import Path

from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA


def create_retail_counterparties() -> pl.DataFrame:
    """
    Create test retail counterparties covering individuals and small businesses.

    Returns:
        pl.DataFrame: Retail counterparties matching COUNTERPARTY_SCHEMA
    """
    retail = [
        # Individual - Standard Retail (Scenario A9)
        {
            "counterparty_reference": "RTL_IND_001",
            "counterparty_name": "John Smith",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 75_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_IND_002",
            "counterparty_name": "Jane Doe",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 120_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_IND_003",
            "counterparty_name": "Robert Johnson",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 45_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Individual - Mortgage borrower (for residential mortgage scenarios)
        {
            "counterparty_reference": "RTL_MTG_001",
            "counterparty_name": "Sarah Williams",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 95_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_MTG_002",
            "counterparty_name": "Michael Brown",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 150_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # SME Retail - Turnover under £880k threshold (Scenario A10)
        {
            "counterparty_reference": "RTL_SME_001",
            "counterparty_name": "Small Biz Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 500_000.0,
            "total_assets": 300_000.0,
            "default_status": False,
            "sector_code": "47.19",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_SME_002",
            "counterparty_name": "Corner Shop Trading",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000.0,
            "total_assets": 100_000.0,
            "default_status": False,
            "sector_code": "47.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_SME_003",
            "counterparty_name": "Local Services Co",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 800_000.0,
            "total_assets": 400_000.0,
            "default_status": False,
            "sector_code": "81.10",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # SME at threshold boundary (just under £880k)
        {
            "counterparty_reference": "RTL_SME_004",
            "counterparty_name": "Boundary Business Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 875_000.0,
            "total_assets": 500_000.0,
            "default_status": False,
            "sector_code": "62.02",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # QRRE eligible individuals (credit cards, overdrafts)
        {
            "counterparty_reference": "RTL_QRRE_001",
            "counterparty_name": "Credit Card Customer A",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 55_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "RTL_QRRE_002",
            "counterparty_name": "Overdraft Customer B",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 40_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # High-income individual (still retail if exposure criteria met)
        {
            "counterparty_reference": "RTL_HNW_001",
            "counterparty_name": "High Net Worth Individual",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 500_000.0,
            "total_assets": None,
            "default_status": False,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Defaulted retail individual
        {
            "counterparty_reference": "RTL_DF_001",
            "counterparty_name": "Defaulted Individual",
            "entity_type": "individual",
            "country_code": "GB",
            "annual_revenue": 30_000.0,
            "total_assets": None,
            "default_status": True,
            "sector_code": None,
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Defaulted SME retail
        {
            "counterparty_reference": "RTL_DF_002",
            "counterparty_name": "Defaulted Small Business",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000.0,
            "total_assets": 200_000.0,
            "default_status": True,
            "sector_code": "56.10",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
    ]

    return pl.DataFrame(retail, schema=COUNTERPARTY_SCHEMA)


def save_retail_counterparties(output_dir: Path | None = None) -> Path:
    """
    Create and save retail counterparties to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path: Path to the saved parquet file
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_retail_counterparties()
    output_path = output_dir / "retail.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_retail_counterparties()
    print(f"Saved retail counterparties to: {output_path}")

    # Display the data for verification
    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} retail counterparties:")
    print(df)
