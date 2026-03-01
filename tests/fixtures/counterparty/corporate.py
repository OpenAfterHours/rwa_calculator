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

from pathlib import Path

import polars as pl

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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Small SME (revenue < £50m but > £880k, managed as retail - 75% RW)
        {
            "counterparty_reference": "CORP_SME_003",
            "counterparty_name": "Small Business Services Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 5_000_000.0,
            "total_assets": 3_000_000.0,
            "default_status": False,
            "sector_code": "70.22",
            "is_regulated": True,
            "is_managed_as_retail": True,  # Managed on pooled retail basis (CRR Art. 123)
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
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # PSE with institution IRB treatment (commercial PSE)
        {
            "counterparty_reference": "CORP_PSE_001",
            "counterparty_name": "Transport for London",
            "entity_type": "pse_institution",
            "country_code": "GB",
            "annual_revenue": 10_000_000_000.0,
            "total_assets": 50_000_000_000.0,
            "default_status": False,
            "sector_code": "49.31",
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # A-IRB TEST: Corporate with bank's own LGD estimate (CRR-C1)
        # Tests A-IRB where bank provides own PD, LGD, and EAD estimates
        # LGD 35% - below F-IRB supervisory 45%, demonstrating A-IRB benefit
        # =============================================================================
        {
            "counterparty_reference": "CORP_AIRB_001",
            "counterparty_name": "Advanced IRB Corporate PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 800_000_000.0,
            "total_assets": 1_200_000_000.0,
            "default_status": False,
            "sector_code": "64.19",
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
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
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # CRR-F: Supporting Factor Test Scenarios
        # These counterparties support the tiered SME and infrastructure factor tests
        # =============================================================================
        # CRR-F1: SME Small - uses CORP_SME_001 (already exists, turnover £30m)
        # CRR-F2: SME Medium - turnover £25m (blended factor)
        {
            "counterparty_reference": "CORP_SME_MEDIUM",
            "counterparty_name": "Medium SME Services Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 25_000_000.0,  # £25m - below £44m threshold
            "total_assets": 20_000_000.0,
            "default_status": False,
            "sector_code": "70.22",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-F3: SME Large - uses CORP_SME_002 (already exists, turnover £35m)
        # CRR-F5: Infrastructure project (0.75 factor, not tiered)
        {
            "counterparty_reference": "CORP_INFRA_001",
            "counterparty_name": "Thames Tideway Infrastructure Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "sector_code": "42.21",  # Construction of utility projects
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-F6: Large Corporate - no SME factor (turnover > £44m)
        {
            "counterparty_reference": "CORP_LARGE_001",
            "counterparty_name": "Large Multinational Corp PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 200_000_000.0,  # £200m - exceeds £44m threshold
            "total_assets": 300_000_000.0,
            "default_status": False,
            "sector_code": "46.90",  # Non-specialised wholesale trade
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-F7: SME at boundary - turnover £20m (at threshold)
        {
            "counterparty_reference": "CORP_SME_BOUNDARY",
            "counterparty_name": "Boundary SME Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 20_000_000.0,  # £20m - well below £44m threshold
            "total_assets": 15_000_000.0,
            "default_status": False,
            "sector_code": "62.02",  # Computer consultancy
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Alias for CRR-F1 (CORP_SME_SMALL -> same characteristics as CORP_SME_001)
        {
            "counterparty_reference": "CORP_SME_SMALL",
            "counterparty_name": "Small SME Manufacturing Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 30_000_000.0,  # £30m - below £44m threshold
            "total_assets": 22_000_000.0,
            "default_status": False,
            "sector_code": "25.11",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # Alias for CRR-F3 (CORP_SME_LARGE -> same characteristics as CORP_SME_002)
        {
            "counterparty_reference": "CORP_SME_LARGE",
            "counterparty_name": "Large SME Services Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 35_000_000.0,  # £35m - below £44m threshold
            "total_assets": 30_000_000.0,
            "default_status": False,
            "sector_code": "62.01",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # CRR-G: Provisions & Impairments Test Scenarios
        # These counterparties support the provision/EL shortfall/EL excess tests
        # =============================================================================
        # CRR-G1: SA with specific provision (unrated corporate)
        {
            "counterparty_reference": "CORP_PROV_G1",
            "counterparty_name": "Provision Test Corporate G1 Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,  # £100m - large corporate
            "total_assets": 80_000_000.0,
            "default_status": False,
            "sector_code": "46.90",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-G2: IRB EL shortfall (F-IRB corporate, PD 2%)
        {
            "counterparty_reference": "CORP_PROV_G2",
            "counterparty_name": "Provision Test Corporate G2 Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 150_000_000.0,  # £150m - large corporate
            "total_assets": 120_000_000.0,
            "default_status": False,
            "sector_code": "25.99",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-G3: IRB EL excess (F-IRB corporate, PD 0.5%)
        {
            "counterparty_reference": "CORP_PROV_G3",
            "counterparty_name": "Provision Test Corporate G3 Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 180_000_000.0,  # £180m - large corporate
            "total_assets": 150_000_000.0,
            "default_status": False,
            "sector_code": "28.99",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # CRR-H: Complex/Combined Scenario Test Counterparties
        # These counterparties support the complex scenario acceptance tests
        # =============================================================================
        # CRR-H1: Facility with multiple loans (unrated corporate = 100% RW)
        {
            "counterparty_reference": "CORP_FAC_001",
            "counterparty_name": "Multi-Facility Corporate Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 120_000_000.0,  # £120m - large corporate (unrated)
            "total_assets": 100_000_000.0,
            "default_status": False,
            "sector_code": "46.49",  # Wholesale of other household goods
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-H2: Counterparty group parent (rated CQS 2 = 50% RW)
        # Has unrated subsidiary (inherits 50%) and rated subsidiary (CQS 3 = 100%)
        {
            "counterparty_reference": "CORP_GRP_001",
            "counterparty_name": "Group Holdings Parent PLC",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 500_000_000.0,  # £500m - large corporate
            "total_assets": 400_000_000.0,
            "default_status": False,
            "sector_code": "64.20",  # Holding company activities
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-H2: Unrated subsidiary (inherits parent CQS 2 = 50% RW)
        {
            "counterparty_reference": "CORP_GRP_001_SUB1",
            "counterparty_name": "Group Subsidiary One Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 80_000_000.0,
            "total_assets": 60_000_000.0,
            "default_status": False,
            "sector_code": "46.73",  # Wholesale of building materials
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-H2: Rated subsidiary (own CQS 3 = 100% RW)
        {
            "counterparty_reference": "CORP_GRP_001_SUB2",
            "counterparty_name": "Group Subsidiary Two Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 60_000_000.0,
            "total_assets": 45_000_000.0,
            "default_status": False,
            "sector_code": "43.21",  # Electrical installation
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-H3: SME chain with supporting factor (turnover £25m)
        {
            "counterparty_reference": "CORP_SME_CHAIN",
            "counterparty_name": "SME Chain Test Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 25_000_000.0,  # £25m - below £44m SME threshold
            "total_assets": 20_000_000.0,
            "default_status": False,
            "sector_code": "25.62",  # Machining
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # CRR-H4: Full CRM chain (unrated corporate = 100% RW base)
        {
            "counterparty_reference": "CORP_CRM_FULL",
            "counterparty_name": "Full CRM Chain Corporate Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 90_000_000.0,  # Large corporate (unrated)
            "total_assets": 70_000_000.0,
            "default_status": False,
            "sector_code": "28.21",  # Manufacture of ovens and furnaces
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # CRR-A7: Commercial RE borrower (40% LTV, income cover)
        # =============================================================================
        {
            "counterparty_reference": "CORP_CRE_001",
            "counterparty_name": "Commercial Property Investor Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 50_000_000.0,
            "total_assets": 80_000_000.0,
            "default_status": False,
            "sector_code": "68.20",  # Renting and operating of own real estate
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # CRR-A8: Off-Balance Sheet CCF test (unrated corporate = 100% RW)
        # Counterparty for CONT_CCF_001 contingent fixture
        # =============================================================================
        {
            "counterparty_reference": "CORP_OBS_001",
            "counterparty_name": "OBS Test Corporate Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 100_000_000.0,  # Large corporate (no SME factor)
            "total_assets": 80_000_000.0,
            "default_status": False,
            "sector_code": "46.90",
            "is_regulated": True,
            "is_managed_as_retail": False,
        },
        # =============================================================================
        # HIERARCHY TEST 4: Same Reference Pattern
        # Tests scenario where facility_reference = loan_reference
        # This is a valid business pattern when source systems use unified identifiers
        # =============================================================================
        {
            "counterparty_reference": "CORP_SAME_REF",
            "counterparty_name": "Same Reference Test Corp Ltd",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 75_000_000.0,  # Large corporate
            "total_assets": 60_000_000.0,
            "default_status": False,
            "sector_code": "46.90",  # Non-specialised wholesale trade
            "is_regulated": True,
            "is_managed_as_retail": False,
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
