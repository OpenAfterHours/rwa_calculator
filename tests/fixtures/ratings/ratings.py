"""
Generate credit ratings for test counterparties.

The output will be saved as `ratings.parquet` ready to get picked up within the wider
testing process.

Credit Quality Steps (CQS) map external ratings to risk weights:
    CQS 1: AAA to AA- (S&P/Fitch), Aaa to Aa3 (Moody's)
    CQS 2: A+ to A- (S&P/Fitch), A1 to A3 (Moody's)
    CQS 3: BBB+ to BBB- (S&P/Fitch), Baa1 to Baa3 (Moody's)
    CQS 4: BB+ to BB- (S&P/Fitch), Ba1 to Ba3 (Moody's)
    CQS 5: B+ to B- (S&P/Fitch), B1 to B3 (Moody's)
    CQS 6: CCC+ and below (S&P/Fitch), Caa1 and below (Moody's)

Rating types:
    - External: From recognised rating agencies (S&P, Moody's, Fitch)
    - Internal: Bank's own assessment with PD estimate (for IRB approach)

Usage:
    uv run python tests/fixtures/ratings/ratings.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import RATINGS_SCHEMA


def main() -> None:
    """Entry point for ratings generation."""
    output_path = save_ratings()
    print_summary(output_path)


@dataclass(frozen=True)
class Rating:
    """A credit rating for a counterparty."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float | None
    rating_date: date
    is_solicited: bool

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
        }


RATING_DATE = date(2026, 1, 1)


def create_ratings() -> pl.DataFrame:
    """
    Create credit ratings for test counterparties.

    Returns:
        pl.DataFrame: Ratings matching RATINGS_SCHEMA
    """
    ratings = [
        *_sovereign_external_ratings(),
        *_institution_external_ratings(),
        *_corporate_external_ratings(),
        *_corporate_internal_ratings(),
        *_firb_scenario_internal_ratings(),
        *_airb_scenario_internal_ratings(),
        *_provision_scenario_internal_ratings(),
        *_retail_internal_ratings(),
        *_complex_scenario_external_ratings(),
    ]

    return pl.DataFrame([r.to_dict() for r in ratings], schema=RATINGS_SCHEMA)


def _sovereign_external_ratings() -> list[Rating]:
    """
    External ratings for sovereign counterparties.

    Sovereigns are rated by major agencies with CQS mapping:
        UK, US, Germany: AAA (CQS 1) - 0% RW
        Saudi Arabia: A+ (CQS 2) - 20% RW
        Mexico: BBB+ (CQS 3) - 50% RW
        Brazil: BB- (CQS 4) - 100% RW
        Argentina: CCC+ (CQS 6) - 150% RW
        Unrated/Defaulted: No external rating
    """
    return [
        # CQS 1 Sovereigns - 0% Risk Weight
        Rating(
            "RTG_SOV_UK_001", "SOV_UK_001", "external", "S&P", "AAA", 1, None, RATING_DATE, True
        ),
        Rating(
            "RTG_SOV_US_001", "SOV_US_001", "external", "Moodys", "Aaa", 1, None, RATING_DATE, True
        ),
        Rating(
            "RTG_SOV_DE_001", "SOV_DE_001", "external", "Fitch", "AAA", 1, None, RATING_DATE, True
        ),
        # CQS 2 Sovereign - 20% Risk Weight
        Rating("RTG_SOV_SA_001", "SOV_SA_001", "external", "S&P", "A+", 2, None, RATING_DATE, True),
        # CQS 3 Sovereign - 50% Risk Weight
        Rating(
            "RTG_SOV_MX_001", "SOV_MX_001", "external", "S&P", "BBB+", 3, None, RATING_DATE, True
        ),
        # CQS 4 Sovereign - 100% Risk Weight
        Rating(
            "RTG_SOV_BR_001", "SOV_BR_001", "external", "S&P", "BB-", 4, None, RATING_DATE, True
        ),
        # CQS 6 Sovereign - 150% Risk Weight
        Rating(
            "RTG_SOV_AR_001", "SOV_AR_001", "external", "S&P", "CCC+", 6, None, RATING_DATE, True
        ),
        # SOV_XX_001 (Unrated) and SOV_DF_001 (Defaulted) have no external rating
    ]


def _institution_external_ratings() -> list[Rating]:
    """
    External ratings for institution counterparties.

    UK ECRA deviation: CQS 2 institutions get 30% RW (not Basel standard 50%)

    Rated institutions:
        Barclays, HSBC, JPMorgan: AA- (CQS 1) - 20% RW
        Metro Bank: A (CQS 2) - 30% RW (UK deviation)
        Monte dei Paschi: BBB (CQS 3) - 50% RW
        Turkish Dev Bank: BB (CQS 4) - 100% RW
        High Risk Regional: CCC (CQS 6) - 150% RW
        Investment Firm: A- (CQS 2)
        LCH (CCP): AA (CQS 1)
        Unrated Regional: No rating - 40% RW
    """
    return [
        # CQS 1 Institutions - 20% Risk Weight
        Rating(
            "RTG_INST_UK_001", "INST_UK_001", "external", "S&P", "AA-", 1, None, RATING_DATE, True
        ),
        Rating(
            "RTG_INST_UK_002",
            "INST_UK_002",
            "external",
            "Moodys",
            "Aa3",
            1,
            None,
            RATING_DATE,
            True,
        ),
        Rating(
            "RTG_INST_US_001", "INST_US_001", "external", "S&P", "AA-", 1, None, RATING_DATE, True
        ),
        Rating(
            "RTG_INST_CCP_001", "INST_CCP_001", "external", "S&P", "AA", 1, None, RATING_DATE, True
        ),
        # CQS 2 Institutions - 30% Risk Weight (UK deviation)
        Rating(
            "RTG_INST_UK_003", "INST_UK_003", "external", "Fitch", "A", 2, None, RATING_DATE, True
        ),
        Rating(
            "RTG_INST_UK_004", "INST_UK_004", "external", "S&P", "A-", 2, None, RATING_DATE, True
        ),
        # CQS 3 Institution - 50% Risk Weight
        Rating(
            "RTG_INST_IT_001",
            "INST_IT_001",
            "external",
            "Moodys",
            "Baa2",
            3,
            None,
            RATING_DATE,
            True,
        ),
        # CQS 4 Institution - 100% Risk Weight
        Rating(
            "RTG_INST_TR_001", "INST_TR_001", "external", "Fitch", "BB", 4, None, RATING_DATE, True
        ),
        # CQS 6 Institution - 150% Risk Weight
        Rating(
            "RTG_INST_XX_001", "INST_XX_001", "external", "S&P", "CCC", 6, None, RATING_DATE, True
        ),
        # INST_UR_001 (Unrated) and INST_DF_001 (Defaulted) have no external rating
    ]


def _corporate_external_ratings() -> list[Rating]:
    """
    External ratings for corporate counterparties.

    Includes:
        - Large rated corporates across CQS bands
        - Parent companies for rating inheritance testing (rated)
        - Subsidiaries intentionally unrated to test inheritance
    """
    return [
        # CQS 1 Corporates - 20% Risk Weight
        # Note: CORP_UK_001 intentionally unrated for A12 test (large corp, no SME factor)
        Rating(
            "RTG_CORP_UK_002",
            "CORP_UK_002",
            "external",
            "Moodys",
            "Aa2",
            1,
            None,
            RATING_DATE,
            True,
        ),
        # CQS 2 Corporates - 50% Risk Weight
        Rating(
            "RTG_CORP_UK_003", "CORP_UK_003", "external", "Fitch", "A", 2, None, RATING_DATE, True
        ),
        # CQS 3 Corporates - 75% Risk Weight
        Rating(
            "RTG_CORP_UK_004", "CORP_UK_004", "external", "S&P", "BBB", 3, None, RATING_DATE, True
        ),
        # CQS 4 Corporates - 100% Risk Weight
        Rating(
            "RTG_CORP_UK_005", "CORP_UK_005", "external", "S&P", "BB+", 4, None, RATING_DATE, True
        ),
        # CQS 5/6 Corporates - 150% Risk Weight
        Rating(
            "RTG_CORP_XX_001", "CORP_XX_001", "external", "Fitch", "B-", 5, None, RATING_DATE, True
        ),
        # Group 1 Parent - rated CQS 2 for inheritance testing
        Rating(
            "RTG_CORP_GRP1_PARENT",
            "CORP_GRP1_PARENT",
            "external",
            "S&P",
            "A-",
            2,
            None,
            RATING_DATE,
            True,
        ),
        # Group 1 subsidiaries intentionally have NO external rating - test inheritance
        # Group 2 Ultimate Parent - rated CQS 1 for multi-level inheritance
        Rating(
            "RTG_CORP_GRP2_ULTIMATE",
            "CORP_GRP2_ULTIMATE",
            "external",
            "Moodys",
            "Aa3",
            1,
            None,
            RATING_DATE,
            True,
        ),
        # Group 2 intermediate and operating subs have NO external rating - test inheritance
        # Group 3 SME Parent - rated CQS 3
        Rating(
            "RTG_CORP_GRP3_PARENT",
            "CORP_GRP3_PARENT",
            "external",
            "Fitch",
            "BBB-",
            3,
            None,
            RATING_DATE,
            True,
        ),
        # SME Corporates
        Rating(
            "RTG_CORP_SME_001", "CORP_SME_001", "external", "S&P", "BBB", 3, None, RATING_DATE, True
        ),
        Rating(
            "RTG_CORP_SME_002",
            "CORP_SME_002",
            "external",
            "Fitch",
            "BBB-",
            3,
            None,
            RATING_DATE,
            True,
        ),
        # Large Corporate
        Rating(
            "RTG_CORP_LRG_001", "CORP_LRG_001", "external", "S&P", "A", 2, None, RATING_DATE, True
        ),
        # CORP_UR_001 intentionally unrated for testing 100% RW unrated treatment
        # CORP_DF_001 (Defaulted) has no external rating
    ]


def _corporate_internal_ratings() -> list[Rating]:
    """
    Internal ratings with PD estimates for IRB approach testing.

    Internal ratings include PD (Probability of Default) for IRB calculations.
    PD floors per Basel 3.1:
        Corporate: 0.03%
        Retail (non-QRRE): 0.05%
        Retail QRRE: 0.10%
    """
    return [
        # Large corporates - low PD
        # Note: CORP_UK_001 intentionally unrated for A12 test
        Rating(
            "RTG_INT_CORP_UK_002",
            "CORP_UK_002",
            "internal",
            "internal",
            "1B",
            1,
            0.0008,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_CORP_UK_003",
            "CORP_UK_003",
            "internal",
            "internal",
            "2A",
            2,
            0.0015,
            RATING_DATE,
            False,
        ),
        # Mid-tier corporates
        Rating(
            "RTG_INT_CORP_UK_004",
            "CORP_UK_004",
            "internal",
            "internal",
            "3A",
            3,
            0.0050,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_CORP_UK_005",
            "CORP_UK_005",
            "internal",
            "internal",
            "4A",
            4,
            0.0150,
            RATING_DATE,
            False,
        ),
        # Higher risk
        Rating(
            "RTG_INT_CORP_XX_001",
            "CORP_XX_001",
            "internal",
            "internal",
            "5B",
            5,
            0.0500,
            RATING_DATE,
            False,
        ),
        # SME corporates
        Rating(
            "RTG_INT_CORP_SME_001",
            "CORP_SME_001",
            "internal",
            "internal",
            "3B",
            3,
            0.0100,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_CORP_SME_002",
            "CORP_SME_002",
            "internal",
            "internal",
            "3C",
            3,
            0.0120,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_CORP_SME_003",
            "CORP_SME_003",
            "internal",
            "internal",
            "4B",
            4,
            0.0200,
            RATING_DATE,
            False,
        ),
        # Group hierarchy - internal ratings for all entities
        Rating(
            "RTG_INT_GRP1_PARENT",
            "CORP_GRP1_PARENT",
            "internal",
            "internal",
            "2A",
            2,
            0.0020,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_GRP1_SUB1",
            "CORP_GRP1_SUB1",
            "internal",
            "internal",
            "2B",
            2,
            0.0025,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_GRP1_SUB2",
            "CORP_GRP1_SUB2",
            "internal",
            "internal",
            "2B",
            2,
            0.0028,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_GRP1_SUB3",
            "CORP_GRP1_SUB3",
            "internal",
            "internal",
            "2C",
            2,
            0.0030,
            RATING_DATE,
            False,
        ),
        # Institutions - internal ratings
        Rating(
            "RTG_INT_INST_UK_001",
            "INST_UK_001",
            "internal",
            "internal",
            "1A",
            1,
            0.0003,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_INST_UK_002",
            "INST_UK_002",
            "internal",
            "internal",
            "1A",
            1,
            0.0003,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_INST_UK_003",
            "INST_UK_003",
            "internal",
            "internal",
            "2A",
            2,
            0.0012,
            RATING_DATE,
            False,
        ),
        # PD floor test - internal PD below regulatory floor (use CORP_UK_002 instead)
        Rating(
            "RTG_INT_FLOOR_TEST",
            "CORP_UK_002",
            "internal",
            "internal",
            "1A+",
            1,
            0.0001,
            RATING_DATE,
            False,
        ),
    ]


def _firb_scenario_internal_ratings() -> list[Rating]:
    """
    Internal ratings with specific PD values for CRR F-IRB scenario testing.

    These ratings have exact PD values to match the expected outputs in the
    CRR-B scenario workbook. Each rating uses a specific PD that demonstrates
    a particular F-IRB calculation feature.

    Note: These ratings use FIRB_RATING_DATE (one day after RATING_DATE) to ensure
    they take precedence over other internal ratings for the same counterparty
    when using get_internal_rating() which returns the most recent rating.

    Scenarios:
        CRR-B1: Low PD corporate (0.10%)
        CRR-B2: High PD corporate (5.00%)
        CRR-B3: Subordinated exposure (1.00%)
        CRR-B4: Financial collateral (0.50%)
        CRR-B5: SME with supporting factor (2.00%)
        CRR-B6: PD floor binding (0.01% -> 0.03%)
        CRR-B7: Long maturity (0.80%)
    """
    # Use a date one day after standard rating date so FIRB ratings take precedence
    firb_rating_date = date(2026, 1, 2)

    return [
        # CRR-B1: Corporate F-IRB - Low PD (0.10%)
        # Tests standard F-IRB calculation with low credit risk
        Rating(
            "RTG_INT_FIRB_B1",
            "CORP_UK_001",
            "internal",
            "internal",
            "1C",
            1,
            0.0010,
            firb_rating_date,
            False,
        ),
        # CRR-B2: Corporate F-IRB - High PD (5.00%)
        # Tests F-IRB with elevated credit risk (correlation decreases with PD)
        Rating(
            "RTG_INT_FIRB_B2",
            "CORP_UK_005",
            "internal",
            "internal",
            "5A",
            5,
            0.0500,
            firb_rating_date,
            False,
        ),
        # CRR-B3: Subordinated Exposure - PD 1.00%
        # Tests 75% supervisory LGD for subordinated claims
        Rating(
            "RTG_INT_FIRB_B3",
            "CORP_UK_004",
            "internal",
            "internal",
            "4A",
            4,
            0.0100,
            firb_rating_date,
            False,
        ),
        # CRR-B4: Financial Collateral - PD 0.50%
        # Tests blended LGD with 50% cash collateral coverage
        Rating(
            "RTG_INT_FIRB_B4",
            "CORP_SME_002",
            "internal",
            "internal",
            "3B",
            3,
            0.0050,
            firb_rating_date,
            False,
        ),
        # CRR-B5: SME with Supporting Factor - PD 2.00%
        # Tests SME firm size adjustment + 0.7619 supporting factor
        Rating(
            "RTG_INT_FIRB_B5",
            "CORP_SME_001",
            "internal",
            "internal",
            "4B",
            4,
            0.0200,
            firb_rating_date,
            False,
        ),
        # CRR-B6: PD Floor Binding - PD 0.01% (uses existing RTG_INT_FLOOR_TEST)
        # The existing CORP_UK_002 rating with PD 0.0001 demonstrates floor binding
        # No new rating needed as RTG_INT_FLOOR_TEST already has PD 0.01%
        # CRR-B7: Long Maturity - PD 0.80%
        # Tests maturity cap of 5 years (7Y contractual -> 5Y capped)
        Rating(
            "RTG_INT_FIRB_B7",
            "CORP_LRG_001",
            "internal",
            "internal",
            "2C",
            2,
            0.0080,
            firb_rating_date,
            False,
        ),
    ]


def _airb_scenario_internal_ratings() -> list[Rating]:
    """
    Internal ratings with specific PD values for CRR A-IRB scenario testing.

    These ratings support the A-IRB scenarios where banks provide their own
    estimates for PD, LGD, and EAD. The LGD values come from the loan data;
    these ratings provide the PD estimates.

    Note: A-IRB uses the same PD floor as F-IRB (0.03% for corporates, 0.05% retail)

    Scenarios:
        CRR-C1: Corporate A-IRB - PD 1.00%
        CRR-C2: Retail A-IRB - PD 0.30%
        CRR-C3: Specialised Lending A-IRB - PD 1.50%
    """
    # Use same date as FIRB ratings for consistency
    airb_rating_date = date(2026, 1, 2)

    return [
        # CRR-C1: Corporate A-IRB - PD 1.00%
        # Tests A-IRB corporate with bank's own LGD (35% vs F-IRB 45%)
        Rating(
            "RTG_INT_AIRB_C1",
            "CORP_AIRB_001",
            "internal",
            "internal",
            "3A",
            3,
            0.0100,
            airb_rating_date,
            False,
        ),
        # CRR-C2: Retail A-IRB - PD 0.30%
        # Tests A-IRB retail with bank's own LGD (15%)
        # Retail MUST use A-IRB (F-IRB not available)
        Rating(
            "RTG_INT_AIRB_C2",
            "RTL_AIRB_001",
            "internal",
            "internal",
            "R1B",
            1,
            0.0030,
            airb_rating_date,
            False,
        ),
        # CRR-C3: Specialised Lending A-IRB - PD 1.50%
        # Tests A-IRB for project finance with bank's own LGD (25%)
        Rating(
            "RTG_INT_AIRB_C3",
            "SL_PF_001",
            "internal",
            "internal",
            "3B",
            3,
            0.0150,
            airb_rating_date,
            False,
        ),
    ]


def _provision_scenario_internal_ratings() -> list[Rating]:
    """
    Internal ratings for CRR-G Provisions & Impairments scenario testing.

    These ratings provide specific PD values for IRB scenarios that test
    EL shortfall and EL excess calculations.

    Scenarios:
        CRR-G2: EL Shortfall - PD 2.00% (EL > provisions)
        CRR-G3: EL Excess - PD 0.50% (provisions > EL)
    """
    # Use same date as FIRB ratings for consistency
    provision_rating_date = date(2026, 1, 2)

    return [
        # CRR-G2: IRB EL Shortfall - PD 2.00%
        # EL = 2% × 45% × £5m = £45,000 (provisions = £30k -> shortfall)
        Rating(
            "RTG_INT_PROV_G2",
            "CORP_PROV_G2",
            "internal",
            "internal",
            "4B",
            4,
            0.0200,
            provision_rating_date,
            False,
        ),
        # CRR-G3: IRB EL Excess - PD 0.50%
        # EL = 0.5% × 45% × £5m = £11,250 (provisions = £50k -> excess)
        Rating(
            "RTG_INT_PROV_G3",
            "CORP_PROV_G3",
            "internal",
            "internal",
            "3A",
            3,
            0.0050,
            provision_rating_date,
            False,
        ),
    ]


def _retail_internal_ratings() -> list[Rating]:
    """
    Internal ratings with PD estimates for retail IRB approach testing.

    Retail exposures use internal ratings for A-IRB approach.
    PD floors per Basel 3.1:
        Retail (non-QRRE): 0.05%
        Retail QRRE: 0.10%

    Retail sub-categories:
        - Standard retail individuals
        - Mortgage borrowers (lower PD due to collateral)
        - SME retail (small businesses under £880k turnover)
        - QRRE (qualifying revolving retail - credit cards, overdrafts)
        - Connected lending groups
    """
    return [
        # Standard retail individuals - typical consumer lending
        Rating(
            "RTG_INT_RTL_IND_001",
            "RTL_IND_001",
            "internal",
            "internal",
            "R2A",
            2,
            0.0080,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_IND_002",
            "RTL_IND_002",
            "internal",
            "internal",
            "R1B",
            1,
            0.0050,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_IND_003",
            "RTL_IND_003",
            "internal",
            "internal",
            "R3A",
            3,
            0.0150,
            RATING_DATE,
            False,
        ),
        # Mortgage borrowers - lower PD due to secured nature
        Rating(
            "RTG_INT_RTL_MTG_001",
            "RTL_MTG_001",
            "internal",
            "internal",
            "M1A",
            1,
            0.0030,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_MTG_002",
            "RTL_MTG_002",
            "internal",
            "internal",
            "M1B",
            1,
            0.0025,
            RATING_DATE,
            False,
        ),
        # SME retail - small businesses
        Rating(
            "RTG_INT_RTL_SME_001",
            "RTL_SME_001",
            "internal",
            "internal",
            "S2A",
            2,
            0.0100,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_SME_002",
            "RTL_SME_002",
            "internal",
            "internal",
            "S2B",
            2,
            0.0120,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_SME_003",
            "RTL_SME_003",
            "internal",
            "internal",
            "S3A",
            3,
            0.0180,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_SME_004",
            "RTL_SME_004",
            "internal",
            "internal",
            "S2C",
            2,
            0.0095,
            RATING_DATE,
            False,
        ),
        # QRRE - qualifying revolving retail exposures (credit cards, overdrafts)
        # Higher PD floor of 0.10% applies
        Rating(
            "RTG_INT_RTL_QRRE_001",
            "RTL_QRRE_001",
            "internal",
            "internal",
            "Q2A",
            2,
            0.0150,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_QRRE_002",
            "RTL_QRRE_002",
            "internal",
            "internal",
            "Q2B",
            2,
            0.0200,
            RATING_DATE,
            False,
        ),
        # High net worth individual
        Rating(
            "RTG_INT_RTL_HNW_001",
            "RTL_HNW_001",
            "internal",
            "internal",
            "R1A",
            1,
            0.0040,
            RATING_DATE,
            False,
        ),
        # Lending Group 1 - Married couple
        Rating(
            "RTG_INT_RTL_LG1_SP1",
            "RTL_LG1_SPOUSE1",
            "internal",
            "internal",
            "R2A",
            2,
            0.0070,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG1_SP2",
            "RTL_LG1_SPOUSE2",
            "internal",
            "internal",
            "R2A",
            2,
            0.0075,
            RATING_DATE,
            False,
        ),
        # Lending Group 2 - Business owner and company
        Rating(
            "RTG_INT_RTL_LG2_OWN",
            "RTL_LG2_OWNER",
            "internal",
            "internal",
            "R2B",
            2,
            0.0085,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG2_CO",
            "RTL_LG2_COMPANY",
            "internal",
            "internal",
            "S2A",
            2,
            0.0110,
            RATING_DATE,
            False,
        ),
        # Lending Group 3 - Family business group
        Rating(
            "RTG_INT_RTL_LG3_P1",
            "RTL_LG3_PERSON1",
            "internal",
            "internal",
            "R2A",
            2,
            0.0090,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG3_P2",
            "RTL_LG3_PERSON2",
            "internal",
            "internal",
            "R2B",
            2,
            0.0100,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG3_B1",
            "RTL_LG3_BIZ1",
            "internal",
            "internal",
            "S2A",
            2,
            0.0105,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG3_B2",
            "RTL_LG3_BIZ2",
            "internal",
            "internal",
            "S2B",
            2,
            0.0115,
            RATING_DATE,
            False,
        ),
        # Lending Group 4 - Boundary threshold test
        Rating(
            "RTG_INT_RTL_LG4_P",
            "RTL_LG4_PERSON",
            "internal",
            "internal",
            "R2A",
            2,
            0.0080,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG4_B",
            "RTL_LG4_BIZ",
            "internal",
            "internal",
            "S2A",
            2,
            0.0095,
            RATING_DATE,
            False,
        ),
        # Lending Group 5 - Over threshold test
        Rating(
            "RTG_INT_RTL_LG5_P",
            "RTL_LG5_PERSON",
            "internal",
            "internal",
            "R2B",
            2,
            0.0085,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_LG5_B",
            "RTL_LG5_BIZ",
            "internal",
            "internal",
            "S2B",
            2,
            0.0100,
            RATING_DATE,
            False,
        ),
        # Defaulted retail - PD = 100%
        Rating(
            "RTG_INT_RTL_DF_001",
            "RTL_DF_001",
            "internal",
            "internal",
            "D",
            6,
            1.0000,
            RATING_DATE,
            False,
        ),
        Rating(
            "RTG_INT_RTL_DF_002",
            "RTL_DF_002",
            "internal",
            "internal",
            "D",
            6,
            1.0000,
            RATING_DATE,
            False,
        ),
        # PD floor tests - internal PD below regulatory floor
        # Retail non-QRRE floor is 0.05% (0.0005)
        Rating(
            "RTG_INT_RTL_FLOOR_001",
            "RTL_MTG_001",
            "internal",
            "internal",
            "M1A+",
            1,
            0.0003,
            RATING_DATE,
            False,
        ),
        # QRRE floor is 0.10% (0.0010)
        Rating(
            "RTG_INT_QRRE_FLOOR_001",
            "RTL_QRRE_001",
            "internal",
            "internal",
            "Q1A+",
            1,
            0.0005,
            RATING_DATE,
            False,
        ),
    ]


def _complex_scenario_external_ratings() -> list[Rating]:
    """
    External ratings for CRR-H complex scenario testing.

    CRR-H2: Counterparty group with rating inheritance
        - CORP_GRP_001 (parent): rated CQS 2 (A = 50% RW for corporates)
        - CORP_GRP_001_SUB1: intentionally unrated (inherits parent CQS 2)
        - CORP_GRP_001_SUB2: rated CQS 3 (BBB = 100% RW for corporates)
    """
    return [
        # =============================================================================
        # CRR-H2: Group parent - rated CQS 2 (A rating)
        # Risk weight 50% for corporates with CQS 2
        # =============================================================================
        Rating(
            rating_reference="RTG_EXT_GRP_001_PARENT",
            counterparty_reference="CORP_GRP_001",
            rating_type="external",
            rating_agency="S&P",
            rating_value="A",
            cqs=2,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
        ),
        # =============================================================================
        # CRR-H2: Group subsidiary 2 - rated CQS 3 (BBB rating)
        # Risk weight 100% for corporates with CQS 3
        # SUB1 is intentionally unrated to test rating inheritance
        # =============================================================================
        Rating(
            rating_reference="RTG_EXT_GRP_001_SUB2",
            counterparty_reference="CORP_GRP_001_SUB2",
            rating_type="external",
            rating_agency="S&P",
            rating_value="BBB",
            cqs=3,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
        ),
    ]


def save_ratings(output_dir: Path | None = None) -> Path:
    """
    Create and save ratings to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/ratings directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_ratings()
    output_path = output_dir / "ratings.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved ratings to: {output_path}")
    print(f"\nCreated {len(df)} ratings:")

    print("\nBy rating type:")
    type_counts = df.group_by("rating_type").len().sort("rating_type")
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['rating_type']}: {row['len']} ratings")

    print("\nExternal ratings by CQS:")
    external = df.filter(pl.col("rating_type") == "external")
    cqs_counts = external.group_by("cqs").len().sort("cqs")
    for row in cqs_counts.iter_rows(named=True):
        print(f"  CQS {row['cqs']}: {row['len']} counterparties")

    print("\nInternal ratings PD range:")
    internal = df.filter(pl.col("rating_type") == "internal")
    if len(internal) > 0:
        pd_stats = internal.select(
            pl.col("pd").min().alias("min_pd"),
            pl.col("pd").max().alias("max_pd"),
            pl.col("pd").mean().alias("avg_pd"),
        ).row(0)
        print(f"  Min PD: {pd_stats[0]:.4%}")
        print(f"  Max PD: {pd_stats[1]:.4%}")
        print(f"  Avg PD: {pd_stats[2]:.4%}")


if __name__ == "__main__":
    main()
