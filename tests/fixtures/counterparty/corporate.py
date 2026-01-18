"""
This module creates the corporate counterparties ready for testing.

The output will be saved as `corporates.parquet` ready to get picked up within the wider testing
process.

The schemas can be used to support the structure of the outputs of this module.

Corporate Risk Weights (SA) per CRE20.25-26:
    CQS 1: 20%
    CQS 2: 50%
    CQS 3: 75%
    CQS 4: 100%
    CQS 5: 150%
    CQS 6: 150%
    Unrated: 100%

SME Classification Thresholds:
    - Large Corporate: Annual revenue > £440m (uses corporate IRB formula)
    - SME Corporate: Annual revenue £50m - £440m (may use SME supporting factor)
    - SME Retail: Annual revenue < £50m AND total exposure < £1m (retail treatment)
"""

import polars as pl
from pathlib import Path

from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA


def create_corporate_counterparties() -> pl.DataFrame:
    """
    Create test corporate counterparties covering all CQS risk weight bands and SME thresholds.

    Returns:
        pl.DataFrame: Corporate counterparties matching COUNTERPARTY_SCHEMA
    """
    corporates = [
        # CQS 1 Corporate - 20% Risk Weight (Large rated corporate)
        {
            "counterparty_reference": "CORP_UK_001",
            "counterparty_name": "British Petroleum PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 200_000_000_000.0,
            "total_assets": 250_000_000_000.0,
            "default_status": False,
            "sector_code": "06.10",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_UK_002",
            "counterparty_name": "Unilever PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 60_000_000_000.0,
            "total_assets": 80_000_000_000.0,
            "default_status": False,
            "sector_code": "20.41",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 2 Corporate - 50% Risk Weight
        {
            "counterparty_reference": "CORP_UK_003",
            "counterparty_name": "Tesco PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 65_000_000_000.0,
            "total_assets": 50_000_000_000.0,
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
        # CQS 3 Corporate - 75% Risk Weight
        {
            "counterparty_reference": "CORP_UK_004",
            "counterparty_name": "Mid-Sized Manufacturing Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 500_000_000.0,
            "total_assets": 400_000_000.0,
            "default_status": False,
            "sector_code": "25.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 4 Corporate - 100% Risk Weight
        {
            "counterparty_reference": "CORP_UK_005",
            "counterparty_name": "Regional Services Corp",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,
            "total_assets": 80_000_000.0,
            "default_status": False,
            "sector_code": "82.99",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # CQS 5/6 Corporate - 150% Risk Weight
        {
            "counterparty_reference": "CORP_XX_001",
            "counterparty_name": "High Risk Ventures Inc",
            "entity_type": "corporate",
            "country_code": "XX",
            "annual_revenue": 50_000_000.0,
            "total_assets": 30_000_000.0,
            "default_status": False,
            "sector_code": "64.30",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Unrated Corporate - 100% Risk Weight (Scenario A2 from plan)
        {
            "counterparty_reference": "CORP_UR_001",
            "counterparty_name": "Unrated Large Corporate Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "sector_code": "28.99",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # SME Corporate (revenue < £44m) - eligible for SME supporting factor
        {
            "counterparty_reference": "CORP_SME_001",
            "counterparty_name": "SME Engineering Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 30_000_000.0,  # £30m - below £44m SME threshold
            "total_assets": 25_000_000.0,
            "default_status": False,
            "sector_code": "25.62",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_SME_002",
            "counterparty_name": "SME Tech Solutions Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 35_000_000.0,  # £35m - below £44m SME threshold
            "total_assets": 28_000_000.0,
            "default_status": False,
            "sector_code": "62.01",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Small SME (revenue < £50m but > £880k, corporate treatment)
        {
            "counterparty_reference": "CORP_SME_003",
            "counterparty_name": "Small Business Services Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 5_000_000.0,
            "total_assets": 3_000_000.0,
            "default_status": False,
            "sector_code": "70.22",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Large Corporate (revenue > £440m)
        {
            "counterparty_reference": "CORP_LRG_001",
            "counterparty_name": "Large Corporate Holdings PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 500_000_000.0,
            "total_assets": 600_000_000.0,
            "default_status": False,
            "sector_code": "64.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # PSE treated as corporate
        {
            "counterparty_reference": "CORP_PSE_001",
            "counterparty_name": "Transport for London",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 10_000_000_000.0,
            "total_assets": 50_000_000_000.0,
            "default_status": False,
            "sector_code": "49.31",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": True,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # Defaulted Corporate
        {
            "counterparty_reference": "CORP_DF_001",
            "counterparty_name": "Defaulted Company Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 20_000_000.0,
            "total_assets": 15_000_000.0,
            "default_status": True,
            "sector_code": "47.19",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # =============================================================================
        # ORG HIERARCHY TEST GROUP 1: Rated Parent with Unrated Subsidiaries
        # Tests rating inheritance via ORG_MAPPING (Scenario H2 from plan)
        # Parent CORP_GRP1_PARENT is rated (CQS 2), children should inherit rating
        # =============================================================================
        {
            "counterparty_reference": "CORP_GRP1_PARENT",
            "counterparty_name": "Alpha Holdings PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 2_000_000_000.0,
            "total_assets": 3_000_000_000.0,
            "default_status": False,
            "sector_code": "64.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP1_SUB1",
            "counterparty_name": "Alpha Manufacturing Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 500_000_000.0,
            "total_assets": 400_000_000.0,
            "default_status": False,
            "sector_code": "25.11",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP1_SUB2",
            "counterparty_name": "Alpha Services Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 300_000_000.0,
            "total_assets": 200_000_000.0,
            "default_status": False,
            "sector_code": "82.99",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP1_SUB3",
            "counterparty_name": "Alpha Logistics Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 150_000_000.0,
            "total_assets": 100_000_000.0,
            "default_status": False,
            "sector_code": "49.41",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # =============================================================================
        # ORG HIERARCHY TEST GROUP 2: Multi-level Hierarchy
        # Tests rating inheritance through multiple levels
        # Ultimate parent -> Intermediate holding -> Operating subsidiaries
        # =============================================================================
        {
            "counterparty_reference": "CORP_GRP2_ULTIMATE",
            "counterparty_name": "Beta Group PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 5_000_000_000.0,
            "total_assets": 8_000_000_000.0,
            "default_status": False,
            "sector_code": "64.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP2_INTHOLD",
            "counterparty_name": "Beta UK Holdings Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 1_500_000_000.0,
            "total_assets": 2_000_000_000.0,
            "default_status": False,
            "sector_code": "64.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP2_OPSUB1",
            "counterparty_name": "Beta Retail Operations Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 800_000_000.0,
            "total_assets": 600_000_000.0,
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
            "counterparty_reference": "CORP_GRP2_OPSUB2",
            "counterparty_name": "Beta Online Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
            "total_assets": 300_000_000.0,
            "default_status": False,
            "sector_code": "47.91",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        # =============================================================================
        # ORG HIERARCHY TEST GROUP 3: SME Turnover Aggregation
        # Tests consolidated turnover for SME classification
        # Group turnover used to determine SME vs Large Corporate treatment
        # =============================================================================
        {
            "counterparty_reference": "CORP_GRP3_PARENT",
            "counterparty_name": "Gamma SME Holdings Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 30_000_000.0,
            "total_assets": 25_000_000.0,
            "default_status": False,
            "sector_code": "64.20",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP3_SUB1",
            "counterparty_name": "Gamma Engineering Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 15_000_000.0,
            "total_assets": 10_000_000.0,
            "default_status": False,
            "sector_code": "25.62",
            "is_financial_institution": False,
            "is_regulated": False,
            "is_pse": False,
            "is_mdb": False,
            "is_international_org": False,
            "is_central_counterparty": False,
            "is_regional_govt_local_auth": False,
        },
        {
            "counterparty_reference": "CORP_GRP3_SUB2",
            "counterparty_name": "Gamma Construction Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 20_000_000.0,
            "total_assets": 15_000_000.0,
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
    ]

    return pl.DataFrame(corporates, schema=COUNTERPARTY_SCHEMA)


def save_corporate_counterparties(output_dir: Path | None = None) -> Path:
    """
    Create and save corporate counterparties to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path: Path to the saved parquet file
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_corporate_counterparties()
    output_path = output_dir / "corporate.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_corporate_counterparties()
    print(f"Saved corporate counterparties to: {output_path}")

    # Display the data for verification
    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} corporate counterparties:")
    print(df)
