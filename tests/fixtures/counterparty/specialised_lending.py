"""
This module creates the specialised lending counterparties ready for testing.

The output will be saved as `specialised_lending.parquet` ready to get picked up within the wider
testing process.

The schemas can be used to support the structure of the outputs of this module.

Specialised Lending Categories (CRE33):
    - Project Finance (PF): Long-term financing of infrastructure/industrial projects
    - Object Finance (OF): Financing of physical assets (ships, aircraft, satellites)
    - Commodities Finance (CF): Short-term lending to finance commodity reserves/inventories
    - Income Producing Real Estate (IPRE): Real estate held for rental income

Slotting Risk Weights per CRE33.5:
    Strong:        70% (50% if remaining maturity < 2.5 years)
    Good:          90% (70% if remaining maturity < 2.5 years)
    Satisfactory: 115%
    Weak:         250%
    Default:        0% (100% deduction from capital)

HVCRE (High Volatility Commercial Real Estate):
    Strong:        95% (70% if remaining maturity < 2.5 years)
    Good:         120% (95% if remaining maturity < 2.5 years)
    Satisfactory: 140%
    Weak:         250%
    Default:        0%

Scenarios from plan:
    E1: Project finance Strong - £10m = £7m RWA (70% RW)
    E2: Project finance Good - £10m = £9m RWA (90% RW)
    E3: IPRE Speculative - £5m = £5.75m RWA (115% RW)
    E4: HVCRE - Higher RW applied
"""

import polars as pl
from pathlib import Path

from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA


def create_specialised_lending_counterparties() -> pl.DataFrame:
    """
    Create test specialised lending counterparties covering all slotting categories.

    Returns:
        pl.DataFrame: Specialised lending counterparties matching COUNTERPARTY_SCHEMA
    """
    specialised_lending = [
        # Project Finance - Strong (Scenario E1)
        {
            "counterparty_reference": "SL_PF_001",
            "counterparty_name": "Thames Infrastructure Project SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "sector_code": "42.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Project Finance - Good (Scenario E2)
        {
            "counterparty_reference": "SL_PF_002",
            "counterparty_name": "Offshore Wind Farm SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 800_000_000.0,
            "default_status": False,
            "sector_code": "35.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Project Finance - Satisfactory
        {
            "counterparty_reference": "SL_PF_003",
            "counterparty_name": "Solar Park Development Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 200_000_000.0,
            "default_status": False,
            "sector_code": "35.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Project Finance - Weak
        {
            "counterparty_reference": "SL_PF_004",
            "counterparty_name": "Struggling Infrastructure SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 100_000_000.0,
            "default_status": False,
            "sector_code": "42.99",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Object Finance - Aircraft
        {
            "counterparty_reference": "SL_OF_001",
            "counterparty_name": "Aircraft Leasing SPV",
            "entity_type": "corporate",
            "country_code": "IE",
            "annual_revenue": None,
            "total_assets": 300_000_000.0,
            "default_status": False,
            "sector_code": "77.35",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Object Finance - Shipping
        {
            "counterparty_reference": "SL_OF_002",
            "counterparty_name": "Container Ship Finance Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 150_000_000.0,
            "default_status": False,
            "sector_code": "77.34",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Commodities Finance
        {
            "counterparty_reference": "SL_CF_001",
            "counterparty_name": "Oil Trading Finance SPV",
            "entity_type": "corporate",
            "country_code": "CH",
            "annual_revenue": None,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "sector_code": "46.71",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "SL_CF_002",
            "counterparty_name": "Metals Trading SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 200_000_000.0,
            "default_status": False,
            "sector_code": "46.72",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # IPRE - Strong
        {
            "counterparty_reference": "SL_IPRE_001",
            "counterparty_name": "Prime Office Building SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 50_000_000.0,
            "total_assets": 400_000_000.0,
            "default_status": False,
            "sector_code": "68.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # IPRE - Satisfactory/Speculative (Scenario E3)
        {
            "counterparty_reference": "SL_IPRE_002",
            "counterparty_name": "Retail Park Development SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 20_000_000.0,
            "total_assets": 150_000_000.0,
            "default_status": False,
            "sector_code": "68.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # HVCRE - High Volatility Commercial Real Estate (Scenario E4)
        {
            "counterparty_reference": "SL_HVCRE_001",
            "counterparty_name": "Speculative Development SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 80_000_000.0,
            "default_status": False,
            "sector_code": "41.10",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "SL_HVCRE_002",
            "counterparty_name": "Land Banking SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 50_000_000.0,
            "default_status": False,
            "sector_code": "68.10",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # ADC - Acquisition, Development, Construction
        {
            "counterparty_reference": "SL_ADC_001",
            "counterparty_name": "Residential Development SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 100_000_000.0,
            "default_status": False,
            "sector_code": "41.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Defaulted Specialised Lending
        {
            "counterparty_reference": "SL_DF_001",
            "counterparty_name": "Failed Project SPV",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 30_000_000.0,
            "default_status": True,
            "sector_code": "42.99",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
    ]

    return pl.DataFrame(specialised_lending, schema=COUNTERPARTY_SCHEMA)


def save_specialised_lending_counterparties(output_dir: Path | None = None) -> Path:
    """
    Create and save specialised lending counterparties to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path: Path to the saved parquet file
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_specialised_lending_counterparties()
    output_path = output_dir / "specialised_lending.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_specialised_lending_counterparties()
    print(f"Saved specialised lending counterparties to: {output_path}")

    # Display the data for verification
    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} specialised lending counterparties:")
    print(df)
