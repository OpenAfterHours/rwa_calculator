"""
This module creates the sovereign counterparties ready for testing.

The output will be saved as `sovereign.parquet` ready to get picked up within the wider testing
process.

The schemas can be used to support the structure of the outputs of this module.

Sovereign Risk Weights (SA) per CRE20.7:
    CQS 1: 0%
    CQS 2: 20%
    CQS 3: 50%
    CQS 4: 100%
    CQS 5: 100%
    CQS 6: 150%
    Unrated: 100%
"""

import polars as pl
from pathlib import Path

from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA


def create_sovereign_counterparties() -> pl.DataFrame:
    """
    Create test sovereign counterparties covering all CQS risk weight bands.

    Returns:
        pl.DataFrame: Sovereign counterparties matching COUNTERPARTY_SCHEMA
    """
    sovereigns = [
        # CQS 1 Sovereigns - 0% Risk Weight
        {
            "counterparty_reference": "SOV_UK_001",
            "counterparty_name": "UK Government",
            "entity_type": "sovereign",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "SOV_US_001",
            "counterparty_name": "US Government",
            "entity_type": "sovereign",
            "country_code": "US",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "SOV_DE_001",
            "counterparty_name": "Federal Republic of Germany",
            "entity_type": "sovereign",
            "country_code": "DE",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 2 Sovereign - 20% Risk Weight
        {
            "counterparty_reference": "SOV_SA_001",
            "counterparty_name": "Kingdom of Saudi Arabia",
            "entity_type": "sovereign",
            "country_code": "SA",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 3 Sovereign - 50% Risk Weight
        {
            "counterparty_reference": "SOV_MX_001",
            "counterparty_name": "United Mexican States",
            "entity_type": "sovereign",
            "country_code": "MX",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 4/5 Sovereign - 100% Risk Weight
        {
            "counterparty_reference": "SOV_BR_001",
            "counterparty_name": "Federative Republic of Brazil",
            "entity_type": "sovereign",
            "country_code": "BR",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 6 Sovereign - 150% Risk Weight
        {
            "counterparty_reference": "SOV_AR_001",
            "counterparty_name": "Argentine Republic",
            "entity_type": "sovereign",
            "country_code": "AR",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Unrated Sovereign - 100% Risk Weight
        {
            "counterparty_reference": "SOV_XX_001",
            "counterparty_name": "Unrated Sovereign State",
            "entity_type": "sovereign",
            "country_code": "XX",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": False,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Defaulted Sovereign - for scenario testing
        {
            "counterparty_reference": "SOV_DF_001",
            "counterparty_name": "Defaulted Sovereign",
            "entity_type": "sovereign",
            "country_code": "DF",
            "annual_revenue": None,
            "total_assets": None,
            "default_status": True,
            "sector_code": "84.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
    ]

    return pl.DataFrame(sovereigns, schema=COUNTERPARTY_SCHEMA)


def save_sovereign_counterparties(output_dir: Path | None = None) -> Path:
    """
    Create and save sovereign counterparties to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path: Path to the saved parquet file
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_sovereign_counterparties()
    output_path = output_dir / "sovereigns.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_sovereign_counterparties()
    print(f"Saved sovereign counterparties to: {output_path}")

    # Display the data for verification
    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} sovereign counterparties:")
    print(df)
