"""
This module creates the institution counterparties ready for testing.

The output will be saved as `institutions.parquet` ready to get picked up within the wider testing
process.

The schemas can be used to support the structure of the outputs of this module.

Institution Risk Weights (SA) per CRE20.16 with UK ECRA deviation:
    CQS 1: 20%
    CQS 2: 30% (UK deviation from Basel 50%)
    CQS 3: 50%
    CQS 4: 100%
    CQS 5: 100%
    CQS 6: 150%
    Unrated: 40%

Short-term exposures (<=3 months) may receive preferential treatment.
"""

from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA


def create_institution_counterparties() -> pl.DataFrame:
    """
    Create test institution counterparties covering all CQS risk weight bands.

    Returns:
        pl.DataFrame: Institution counterparties matching COUNTERPARTY_SCHEMA
    """
    institutions = [
        # CQS 1 Institutions - 20% Risk Weight
        {
            "counterparty_reference": "INST_UK_001",
            "counterparty_name": "Barclays Bank PLC",
            "entity_type": "institution",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 1_500_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": "INST_UK_002",
            "counterparty_name": "HSBC Bank PLC",
            "entity_type": "institution",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 2_000_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": "INST_US_001",
            "counterparty_name": "JPMorgan Chase Bank NA",
            "entity_type": "institution",
            "country_code": "US",
            "annual_revenue": None,
            "total_assets": 3_500_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": "INST_DE_001",
            "counterparty_name": "Deutsche Bank AG",
            "entity_type": "institution",
            "country_code": "DE",
            "annual_revenue": None,
            "total_assets": 1_300_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CQS 2 Institution - 30% Risk Weight (UK deviation)
        {
            "counterparty_reference": "INST_UK_003",
            "counterparty_name": "Metro Bank PLC",
            "entity_type": "institution",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 20_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CQS 3 Institution - 50% Risk Weight
        {
            "counterparty_reference": "INST_IT_001",
            "counterparty_name": "Banca Monte dei Paschi di Siena",
            "entity_type": "institution",
            "country_code": "IT",
            "annual_revenue": None,
            "total_assets": 150_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CQS 4/5 Institution - 100% Risk Weight
        {
            "counterparty_reference": "INST_TR_001",
            "counterparty_name": "Turkish Development Bank",
            "entity_type": "institution",
            "country_code": "TR",
            "annual_revenue": None,
            "total_assets": 50_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CQS 6 Institution - 150% Risk Weight
        {
            "counterparty_reference": "INST_XX_001",
            "counterparty_name": "High Risk Regional Bank",
            "entity_type": "institution",
            "country_code": "XX",
            "annual_revenue": None,
            "total_assets": 5_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Unrated Institution - 40% Risk Weight
        {
            "counterparty_reference": "INST_UR_001",
            "counterparty_name": "Unrated Regional Bank",
            "entity_type": "institution",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 10_000_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Investment Firm - regulated
        {
            "counterparty_reference": "INST_UK_004",
            "counterparty_name": "UK Investment Services Ltd",
            "entity_type": "institution",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "sector_code": "66.12",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Central Counterparty
        {
            "counterparty_reference": "INST_CCP_001",
            "counterparty_name": "LCH Ltd",
            "entity_type": "ccp",
            "country_code": "GB",
            "annual_revenue": None,
            "total_assets": 100_000_000_000.0,
            "default_status": False,
            "sector_code": "66.11",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Defaulted Institution
        {
            "counterparty_reference": "INST_DF_001",
            "counterparty_name": "Defaulted Bank",
            "entity_type": "institution",
            "country_code": "XX",
            "annual_revenue": None,
            "total_assets": 1_000_000_000.0,
            "default_status": True,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
    ]

    return pl.DataFrame(institutions, schema=COUNTERPARTY_SCHEMA)


def save_institution_counterparties(output_dir: Path | None = None) -> Path:
    """
    Create and save institution counterparties to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path: Path to the saved parquet file
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_institution_counterparties()
    output_path = output_dir / "institution.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_institution_counterparties()
    print(f"Saved institution counterparties to: {output_path}")

    # Display the data for verification
    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} institution counterparties:")
    print(df)
