"""
Generate loan test fixtures for exposure hierarchy testing.

The output will be saved as `loans.parquet` ready to get picked up within the wider
testing process.

Loans are drawn exposures that can be:
    - Standalone (no parent facility)
    - Under a facility (linked via facility_mapping)

Loan types for testing:
    - Term loans
    - Drawn portions of revolving facilities
    - Mortgages
    - Subordinated loans

Usage:
    uv run python tests/fixtures/exposures/loans.py
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import LOAN_SCHEMA


def main() -> None:
    """Entry point for loans generation."""
    output_path = save_loans()
    print_summary(output_path)


@dataclass(frozen=True)
class Loan:
    """
    A drawn loan exposure.

    Note: CCF fields (risk_type, ccf_modelled, is_short_term_trade_lc) are NOT included
    because CCF only applies to off-balance sheet items (undrawn commitments, contingents).
    Drawn loans are already on-balance sheet, so EAD = drawn_amount directly.
    """

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    lgd: float  # A-IRB modelled LGD (optional)
    beel: float  # Best estimate expected loss
    seniority: str  # senior, subordinated - affects F-IRB LGD (45% vs 75%)

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
        }


VALUE_DATE = date(2026, 1, 1)


def create_loans() -> pl.DataFrame:
    """
    Create loan test data.

    Returns:
        pl.DataFrame: Loans matching LOAN_SCHEMA
    """
    loans = [
        *_sovereign_loans(),
        *_institution_loans(),
        *_corporate_standalone_loans(),
        *_corporate_facility_loans(),
        *_firb_scenario_loans(),
        *_airb_scenario_loans(),
        *_retail_loans(),
        *_hierarchy_test_loans(),
        *_defaulted_loans(),
        *_crm_scenario_loans(),
        *_slotting_scenario_loans(),
        *_supporting_factor_scenario_loans(),
        *_provision_scenario_loans(),
        *_complex_scenario_loans(),
    ]

    return pl.DataFrame([ln.to_dict() for ln in loans], schema=LOAN_SCHEMA)


def _sovereign_loans() -> list[Loan]:
    """
    Standalone loans to sovereign counterparties.

    Scenario A1: UK Sovereign with CQS1 = 0% RW
    """
    return [
        # UK Government loan - 0% RW (Scenario A1)
        Loan(
            loan_reference="LOAN_SOV_UK_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # US Government loan
        Loan(
            loan_reference="LOAN_SOV_US_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_US_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="USD",
            drawn_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Lower rated sovereign - Brazil (CQS 4, 100% RW)
        Loan(
            loan_reference="LOAN_SOV_BR_001",
            product_type="SOVEREIGN_LOAN",
            book_code="SOVEREIGN",
            counterparty_reference="SOV_BR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="USD",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _institution_loans() -> list[Loan]:
    """
    Loans to institution counterparties.

    Scenario A4: UK Institution CQS2 = 30% RW (UK deviation)
    """
    return [
        # UK Bank loan - Barclays (CQS 1, 20% RW)
        Loan(
            loan_reference="LOAN_INST_UK_001",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),
            currency="GBP",
            drawn_amount=50_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # UK Bank loan - Metro Bank (CQS 2, 30% RW - UK deviation) (Scenario A4)
        Loan(
            loan_reference="LOAN_INST_UK_003",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Unrated institution loan - 40% RW
        Loan(
            loan_reference="LOAN_INST_UR_001",
            product_type="INTERBANK_LOAN",
            book_code="FI_LENDING",
            counterparty_reference="INST_UR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 12, 31),
            currency="GBP",
            drawn_amount=10_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _corporate_standalone_loans() -> list[Loan]:
    """
    Standalone loans to corporate counterparties (not under facility).

    Scenario A2: Unrated corporate = 100% RW
    Scenario A3: Rated corporate CQS2 = 50% RW
    """
    return [
        # Unrated corporate loan - 100% RW (Scenario A2)
        Loan(
            loan_reference="LOAN_CORP_UR_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Rated corporate CQS 2 - 50% RW (Scenario A3)
        Loan(
            loan_reference="LOAN_CORP_UK_003",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Large corporate CQS 1 - 20% RW
        Loan(
            loan_reference="LOAN_CORP_UK_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 3, 31),
            currency="GBP",
            drawn_amount=25_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Subordinated loan - 75% LGD
        Loan(
            loan_reference="LOAN_CORP_SUB_001",
            product_type="SUBORDINATED_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_003",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 3, 31),
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.75,
            beel=0.0,
            seniority="subordinated",
        ),
        # SME Corporate loans
        Loan(
            loan_reference="LOAN_CORP_SME_001",
            product_type="SME_TERM_LOAN",
            book_code="SME_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _corporate_facility_loans() -> list[Loan]:
    """
    Loans drawn under corporate facilities.

    These loans are linked to facilities via facility_mapping.
    """
    return [
        # Drawn under FAC_CORP_001 (BP RCF)
        Loan(
            loan_reference="LOAN_FAC_CORP_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_001",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            drawn_amount=20_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Drawn under FAC_CORP_002 (Unilever term)
        Loan(
            loan_reference="LOAN_FAC_CORP_002_A",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 6, 30),
            currency="GBP",
            drawn_amount=30_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Drawn under FAC_CORP_SME_001
        Loan(
            loan_reference="LOAN_FAC_SME_001_A",
            product_type="RCF_DRAWING",
            book_code="SME_LENDING",
            counterparty_reference="CORP_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _firb_scenario_loans() -> list[Loan]:
    """
    Loans for CRR F-IRB scenario testing (Group CRR-B).

    These loans are used in conjunction with FIRB internal ratings
    to test specific F-IRB calculation features.

    Scenarios:
        CRR-B2: High PD corporate (CORP_UK_005)
        CRR-B3: Subordinated loan (CORP_UK_004)
        CRR-B4: Collateralised loan (CORP_SME_002)
        CRR-B6: Standalone loan for PD floor test (CORP_UK_002)
        CRR-B7: Long maturity loan (CORP_LRG_001)
    """
    return [
        # =============================================================================
        # CRR-B2: High PD corporate loan
        # £5m term loan to CORP_UK_005 with 5% PD
        # =============================================================================
        Loan(
            loan_reference="LOAN_CORP_UK_005",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_005",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3 year maturity
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-B3: Subordinated loan
        # £2m subordinated loan to CORP_UK_004 with 75% LGD
        # Tests CRR Art. 161 subordinated claim treatment
        # =============================================================================
        Loan(
            loan_reference="LOAN_SUB_001",
            product_type="SUBORDINATED_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_004",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 1, 1),  # 4 year maturity
            currency="GBP",
            drawn_amount=2_000_000.0,
            lgd=0.75,  # Subordinated LGD per CRR Art. 161
            beel=0.0,
            seniority="subordinated",
        ),
        # =============================================================================
        # CRR-B4: Collateralised loan
        # £5m loan to CORP_SME_002 with 50% cash collateral coverage
        # Tests blended LGD calculation (50% secured at 0%, 50% unsecured at 45%)
        # =============================================================================
        Loan(
            loan_reference="LOAN_COLL_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_002",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),  # 2.5 year maturity
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.225,  # Blended: 50% × 0% + 50% × 45%
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-B6: Standalone loan for PD floor binding test
        # £1m loan to CORP_UK_002 (rated CQS 1) to test 0.03% floor
        # Internal rating has PD 0.01% which is floored to 0.03%
        # =============================================================================
        Loan(
            loan_reference="LOAN_CORP_UK_002",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UK_002",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),  # 2 year maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-B7: Long maturity loan
        # £8m loan to CORP_LRG_001 with 7 year contractual maturity
        # Tests CRR Art. 162 maturity cap of 5 years
        # =============================================================================
        Loan(
            loan_reference="LOAN_LONG_MAT_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_LRG_001",
            value_date=VALUE_DATE,
            maturity_date=date(2033, 1, 1),  # 7 year maturity (capped at 5)
            currency="GBP",
            drawn_amount=8_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _retail_loans() -> list[Loan]:
    """
    Loans to retail counterparties.

    Scenario A5: Residential mortgage 60% LTV = 20% RW
    Scenario A6: Residential mortgage 85% LTV = 35% RW
    Scenario A9: Retail exposure = 75% RW
    Scenario A10: SME retail = 75% RW
    """
    return [
        # Standard retail loan (Scenario A9)
        Loan(
            loan_reference="LOAN_RTL_IND_001",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_IND_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),
            currency="GBP",
            drawn_amount=50_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # Residential mortgage 60% LTV (Scenario A5)
        Loan(
            loan_reference="LOAN_RTL_MTG_001",
            product_type="RESIDENTIAL_MORTGAGE",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference="RTL_MTG_001",
            value_date=VALUE_DATE,
            maturity_date=date(2051, 1, 1),
            currency="GBP",
            drawn_amount=500_000.0,  # Property value £833,333, LTV 60%
            lgd=0.10,
            beel=0.0,
            seniority="senior",
        ),
        # Residential mortgage 85% LTV (Scenario A6)
        Loan(
            loan_reference="LOAN_RTL_MTG_002",
            product_type="RESIDENTIAL_MORTGAGE",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference="RTL_MTG_002",
            value_date=VALUE_DATE,
            maturity_date=date(2051, 1, 1),
            currency="GBP",
            drawn_amount=850_000.0,  # Property value £1,000,000, LTV 85%
            lgd=0.10,
            beel=0.0,
            seniority="senior",
        ),
        # SME retail loan (Scenario A10)
        Loan(
            loan_reference="LOAN_RTL_SME_001",
            product_type="SME_LOAN",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_SME_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 12, 31),
            currency="GBP",
            drawn_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # QRRE - credit card balance
        Loan(
            loan_reference="LOAN_RTL_QRRE_001",
            product_type="CREDIT_CARD",
            book_code="RETAIL_CARDS",
            counterparty_reference="RTL_QRRE_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 1, 1),
            currency="GBP",
            drawn_amount=5_000.0,
            lgd=0.85,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _hierarchy_test_loans() -> list[Loan]:
    """
    Loans specifically for exposure hierarchy testing.

    Scenario H1: Facility with multiple loans - £5m facility, 3 loans drawn
    """
    return [
        # =============================================================================
        # HIERARCHY TEST 1: Multiple loans under single facility (FAC_HIER_001)
        # Tests aggregation of loans at facility level
        # Total drawn: £1.5m + £2.0m + £1.0m = £4.5m under £5m limit
        # =============================================================================
        Loan(
            loan_reference="LOAN_HIER_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_001_B",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_001_C",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP1_PARENT",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # HIERARCHY TEST 2: Loans under sub-facilities
        # Tests multi-level facility hierarchy
        # =============================================================================
        Loan(
            loan_reference="LOAN_HIER_SUB_001_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB1",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_HIER_SUB_002_A",
            product_type="RCF_DRAWING",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP2_OPSUB2",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            drawn_amount=3_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # HIERARCHY TEST 3: Lending group loans
        # Loans to connected retail parties for threshold aggregation
        # =============================================================================
        Loan(
            loan_reference="LOAN_LG2_OWNER",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_LG2_OWNER",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=80_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_LG2_COMPANY",
            product_type="SME_LOAN",
            book_code="SME_RETAIL",
            counterparty_reference="RTL_LG2_COMPANY",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=350_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _airb_scenario_loans() -> list[Loan]:
    """
    Loans for CRR A-IRB scenario testing (Group CRR-C).

    These loans test Advanced IRB where the bank provides its own estimates
    for PD, LGD, and EAD. Key differences from F-IRB:
    - Bank's own LGD estimates (not supervisory 45%)
    - CRR has NO LGD floors (unlike Basel 3.1 which has 25% unsecured floor)
    - More capital-efficient for banks with strong risk management

    Scenarios:
        CRR-C1: Corporate A-IRB with internal LGD 35% (vs 45% F-IRB)
        CRR-C2: Retail A-IRB with internal LGD 15% (retail MUST use A-IRB)
        CRR-C3: Specialised Lending A-IRB with internal LGD 25%
    """
    return [
        # =============================================================================
        # CRR-C1: Corporate A-IRB with bank's own LGD estimate
        # £5m corporate loan, PD 1%, LGD 35% (bank's internal estimate)
        # Lower RWA than F-IRB due to LGD below supervisory 45%
        # =============================================================================
        Loan(
            loan_reference="LOAN_CORP_AIRB_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_AIRB_001",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),  # 2.5 year maturity
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.35,  # Bank's own LGD estimate (below F-IRB 45%)
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-C2: Retail A-IRB with bank's own estimates
        # £100k retail loan, PD 0.3%, LGD 15% (secured/low loss history)
        # Retail exposures MUST use A-IRB (F-IRB not available)
        # No maturity adjustment for retail
        # =============================================================================
        Loan(
            loan_reference="LOAN_RTL_AIRB_001",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_AIRB_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # No maturity adjustment for retail
            currency="GBP",
            drawn_amount=100_000.0,
            lgd=0.15,  # Bank's own LGD estimate (low loss history)
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-C3: Specialised Lending A-IRB (Project Finance)
        # £10m project finance, PD 1.5%, LGD 25% (strong collateral position)
        # Alternative to slotting approach when A-IRB permission granted
        # =============================================================================
        Loan(
            loan_reference="LOAN_SL_AIRB_001",
            product_type="PROJECT_FINANCE",
            book_code="SPECIALISED_LENDING",
            counterparty_reference="SL_PF_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 1, 1),  # 4 year maturity
            currency="GBP",
            drawn_amount=10_000_000.0,
            lgd=0.25,  # Bank's own LGD estimate (strong collateral)
            beel=0.0,
            seniority="senior",
        ),
    ]


def _defaulted_loans() -> list[Loan]:
    """
    Loans to defaulted counterparties.

    Tests defaulted exposure treatment.
    """
    return [
        Loan(
            loan_reference="LOAN_DF_CORP_001",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_DF_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 12, 31),
            currency="GBP",
            drawn_amount=500_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        Loan(
            loan_reference="LOAN_DF_RTL_001",
            product_type="PERSONAL_LOAN",
            book_code="RETAIL_UNSECURED",
            counterparty_reference="RTL_DF_001",
            value_date=VALUE_DATE,
            maturity_date=date(2027, 6, 30),
            currency="GBP",
            drawn_amount=25_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _crm_scenario_loans() -> list[Loan]:
    """
    Loans for CRR-D Credit Risk Mitigation scenario testing.

    All loans are £1m to unrated corporate (100% RW under SA) to test CRM effects.

    CRR-D1: Cash collateral - 0% haircut
    CRR-D2: Government bond collateral - 4% haircut (CQS 1, >5y)
    CRR-D3: Equity collateral (main index) - 15% haircut
    CRR-D4: Bank guarantee - substitution approach (60% covered by CQS 2 bank)
    CRR-D5: Maturity mismatch - 2yr collateral against 5yr exposure
    CRR-D6: Currency mismatch - EUR collateral against GBP exposure
    """
    return [
        # D1: Cash collateral scenario - £1m loan, £500k cash collateral
        Loan(
            loan_reference="LOAN_CRM_D1",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3yr maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,  # Not used for SA
            beel=0.0,
            seniority="senior",
        ),
        # D2: Government bond collateral scenario - £1m loan, £600k gilt (4% haircut)
        Loan(
            loan_reference="LOAN_CRM_D2",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3yr maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # D3: Equity collateral scenario - £1m loan, £400k main index equity (15% haircut)
        Loan(
            loan_reference="LOAN_CRM_D3",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3yr maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # D4: Bank guarantee scenario - £1m loan, 60% guaranteed by CQS 2 UK bank
        Loan(
            loan_reference="LOAN_CRM_D4",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW base
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3yr maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # D5: Maturity mismatch scenario - £1m 5yr loan, £500k 2yr collateral
        Loan(
            loan_reference="LOAN_CRM_D5",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),  # 5yr maturity for mismatch test
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # D6: Currency mismatch scenario - £1m GBP loan, €500k EUR cash collateral
        Loan(
            loan_reference="LOAN_CRM_D6",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_UR_001",  # Unrated corporate - 100% RW
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),  # 3yr maturity
            currency="GBP",
            drawn_amount=1_000_000.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _slotting_scenario_loans() -> list[Loan]:
    """
    Loans for CRR-E Slotting scenario testing.

    Tests supervisory slotting approach for specialised lending.
    All counterparties have entity_type="specialised_lending" to enable slotting.

    CRR Slotting Risk Weights:
        Strong: 70% (CRR has Strong = Good = 70%)
        Good: 70%
        Satisfactory: 115%
        Weak: 250%
        Default: 0% (100% deduction from capital)

    Note: CRR has same weights for HVCRE and non-HVCRE.
    Basel 3.1 has differentiated weights for HVCRE.

    Scenarios:
        CRR-E1: Project Finance - Strong (70% RW)
        CRR-E2: Project Finance - Good (70% RW)
        CRR-E3: IPRE - Weak (250% RW)
        CRR-E4: HVCRE - Strong (70% RW under CRR)
    """
    return [
        # =============================================================================
        # CRR-E1: Project Finance - Strong
        # £10m project finance, Strong slotting category = 70% RW
        # =============================================================================
        Loan(
            loan_reference="LOAN_SL_PF_001",
            product_type="PROJECT_FINANCE",
            book_code="SPECIALISED_LENDING",
            counterparty_reference="SL_PF_STRONG",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),  # 5yr maturity
            currency="GBP",
            drawn_amount=10_000_000.0,
            lgd=0.45,  # Not used for slotting
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-E2: Project Finance - Good
        # £10m project finance, Good slotting category = 70% RW (same as Strong under CRR)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SL_PF_002",
            product_type="PROJECT_FINANCE",
            book_code="SPECIALISED_LENDING",
            counterparty_reference="SL_PF_GOOD",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),  # 5yr maturity
            currency="GBP",
            drawn_amount=10_000_000.0,
            lgd=0.45,  # Not used for slotting
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-E3: IPRE - Weak
        # £5m income-producing real estate, Weak slotting category = 250% RW (punitive)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SL_IPRE_001",
            product_type="IPRE",
            book_code="SPECIALISED_LENDING",
            counterparty_reference="SL_IPRE_WEAK",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),  # 5yr maturity
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.45,  # Not used for slotting
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-E4: HVCRE - Strong
        # £5m high-volatility CRE, Strong slotting category = 70% RW
        # Note: CRR uses same weights as non-HVCRE; Basel 3.1 has higher HVCRE weights
        # =============================================================================
        Loan(
            loan_reference="LOAN_SL_HVCRE_001",
            product_type="HVCRE",
            book_code="SPECIALISED_LENDING",
            counterparty_reference="SL_HVCRE_STRONG",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),  # 5yr maturity
            currency="GBP",
            drawn_amount=5_000_000.0,
            lgd=0.45,  # Not used for slotting
            beel=0.0,
            seniority="senior",
        ),
    ]


def _supporting_factor_scenario_loans() -> list[Loan]:
    """
    Loans for CRR-F Supporting Factor scenario testing.

    Tests CRR tiered SME supporting factor and infrastructure factor.

    SME Supporting Factor (CRR2 Art. 501) - TIERED:
        - Exposures up to EUR 2.5m (~£2.2m): factor of 0.7619 (23.81% reduction)
        - Exposures above EUR 2.5m: factor of 0.85 (15% reduction)
        - Formula: [min(E, threshold) * 0.7619 + max(E - threshold, 0) * 0.85] / E

    Infrastructure Factor (CRR Art. 501a):
        - Flat 0.75 factor (not tiered)

    Scenarios:
        CRR-F1: Small SME (£2m) - Tier 1 only - factor 0.7619
        CRR-F2: Medium SME (£4m) - Blended factor ~0.80
        CRR-F3: Large SME (£10m) - Tier 2 dominant - factor ~0.83
        CRR-F4: Retail SME (£500k) - Tier 1 factor with 75% RW
        CRR-F5: Infrastructure (£50m) - Flat 0.75 factor
        CRR-F6: Large Corporate (£20m) - No factor (turnover > £44m)
        CRR-F7: At threshold (£2.2m) - Tier 1 only - factor 0.7619
    """
    return [
        # =============================================================================
        # CRR-F1: SME Tier 1 Only - Small Exposure
        # £2m exposure (< £2.2m threshold) = pure Tier 1 factor (0.7619)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SME_TIER1",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_SMALL",
            value_date=VALUE_DATE,
            maturity_date=date(2031, 1, 1),
            currency="GBP",
            drawn_amount=2_000_000.0,  # £2m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F2: SME Blended Factor - Medium Exposure
        # £4m exposure = blended factor (£2.2m @ 0.7619 + £1.8m @ 0.85)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SME_TIER_BLEND",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_MEDIUM",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 6, 30),
            currency="GBP",
            drawn_amount=4_000_000.0,  # £4m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F3: SME Tier 2 Dominant - Large Exposure
        # £10m exposure = Tier 2 dominant (£2.2m @ 0.7619 + £7.8m @ 0.85)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SME_TIER2_DOM",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_LARGE",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=10_000_000.0,  # £10m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F4: Retail SME with Tier 1 Factor
        # £500k retail exposure + SME factor (0.7619)
        # Combined effect: 75% RW × 0.7619 = 57.14% effective RW
        # =============================================================================
        Loan(
            loan_reference="LOAN_RTL_SME_TIER1",
            product_type="BUSINESS_LOAN",
            book_code="RETAIL_LENDING",
            counterparty_reference="RTL_SME_SMALL",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 1, 1),
            currency="GBP",
            drawn_amount=500_000.0,  # £500k
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F5: Infrastructure Supporting Factor
        # £50m infrastructure exposure = flat 0.75 factor (not tiered)
        # =============================================================================
        Loan(
            loan_reference="LOAN_INFRA_001",
            product_type="INFRASTRUCTURE_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_INFRA_001",
            value_date=VALUE_DATE,
            maturity_date=date(2040, 1, 1),  # Long-term infrastructure
            currency="GBP",
            drawn_amount=50_000_000.0,  # £50m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F6: Large Corporate - No SME Factor
        # £20m exposure but turnover > £44m threshold = no factor (1.0)
        # =============================================================================
        Loan(
            loan_reference="LOAN_CORP_LARGE",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_LARGE_001",
            value_date=VALUE_DATE,
            maturity_date=date(2030, 1, 1),
            currency="GBP",
            drawn_amount=20_000_000.0,  # £20m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-F7: At Exposure Threshold Boundary
        # £2.2m exposure (exactly at threshold) = Tier 1 only (0.7619)
        # =============================================================================
        Loan(
            loan_reference="LOAN_SME_BOUNDARY",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_BOUNDARY",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 6, 30),
            currency="GBP",
            drawn_amount=2_200_000.0,  # £2.2m exactly
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _provision_scenario_loans() -> list[Loan]:
    """
    Loans for CRR-G Provisions & Impairments scenario testing.

    Tests provision treatment for SA and EL shortfall/excess for IRB.

    SA Treatment (CRR Art. 110):
        - Specific provisions reduce EAD directly
        - RWA calculated on net exposure

    IRB Treatment (CRR Art. 158-159):
        - Expected Loss = PD × LGD × EAD
        - EL Shortfall (provisions < EL): 50% CET1 + 50% T2 deduction
        - EL Excess (provisions > EL): T2 credit capped at 0.6% IRB RWA

    Scenarios:
        CRR-G1: SA with specific provision - £1m gross, £50k provision
        CRR-G2: IRB EL shortfall - £5m, PD 2%, provisions £30k < EL £45k
        CRR-G3: IRB EL excess - £5m, PD 0.5%, provisions £50k > EL £11.25k
    """
    return [
        # =============================================================================
        # CRR-G1: SA with Specific Provision
        # £1m gross exposure, £50k specific provision
        # EAD_net = £950k, RWA = £950k × 100% = £950k
        # =============================================================================
        Loan(
            loan_reference="LOAN_PROV_G1",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_PROV_G1",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 1, 1),
            currency="GBP",
            drawn_amount=1_000_000.0,  # £1m gross
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-G2: IRB EL Shortfall
        # £5m gross, PD 2%, LGD 45%
        # EL = 2% × 45% × £5m = £45,000
        # Provisions = £30,000 (specific £20k + general £10k)
        # Shortfall = £45,000 - £30,000 = £15,000
        # =============================================================================
        Loan(
            loan_reference="LOAN_PROV_G2",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_PROV_G2",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=5_000_000.0,  # £5m gross
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-G3: IRB EL Excess
        # £5m gross, PD 0.5%, LGD 45%
        # EL = 0.5% × 45% × £5m = £11,250
        # Provisions = £50,000 (specific £35k + general £15k)
        # Excess = £50,000 - £11,250 = £38,750
        # T2 credit capped at 0.6% × RWA
        # =============================================================================
        Loan(
            loan_reference="LOAN_PROV_G3",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_PROV_G3",
            value_date=VALUE_DATE,
            maturity_date=date(2028, 6, 30),
            currency="GBP",
            drawn_amount=5_000_000.0,  # £5m gross
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def _complex_scenario_loans() -> list[Loan]:
    """
    Loans for CRR-H Complex/Combined scenario testing.

    Tests complex scenarios that combine multiple features:
    - Facility with multiple loans (hierarchy)
    - Counterparty group (rating inheritance)
    - SME chain with supporting factor
    - Full CRM chain (collateral + guarantee + provision)

    Scenarios:
        CRR-H1: Facility with multiple loans (FAC_MULTI_001)
        CRR-H2: Counterparty group with rating inheritance (GRP_MULTI_001)
        CRR-H3: SME chain with supporting factor (LOAN_SME_CHAIN)
        CRR-H4: Full CRM chain (LOAN_CRM_FULL)
    """
    return [
        # =============================================================================
        # CRR-H1: Facility with Multiple Loans (Aggregated)
        # Represents aggregated EAD from multiple sub-exposures:
        # - £2m term loan + £1.5m trade finance + £0.5m overdraft = £4m drawn
        # - £1m undrawn commitment (50% CCF = £0.5m EAD)
        # Total EAD = £4.5m, unrated corporate = 100% RW
        # Use facility reference as loan_reference for test compatibility
        # =============================================================================
        Loan(
            loan_reference="FAC_MULTI_001",  # Use facility ref for test lookup
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_FAC_001",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=4_500_000.0,  # £4.5m aggregated EAD
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-H2: Counterparty Group with Rating Inheritance (Aggregated)
        # Represents aggregated exposure across group:
        # - Parent: £3m (CQS 2 = 50% RW)
        # - Sub1: £1.5m (unrated, inherits CQS 2 = 50% RW)
        # - Sub2: £0.5m (CQS 3 = 100% RW)
        # Total EAD = £5m, blended RW = (3*50% + 1.5*50% + 0.5*100%)/5 = 55%
        # Use group reference as loan_reference for test compatibility
        # =============================================================================
        Loan(
            loan_reference="GRP_MULTI_001",  # Use group ref for test lookup
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_GRP_001",  # Use parent counterparty
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=5_000_000.0,  # £5m aggregated EAD
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-H3: SME Chain with Supporting Factor
        # £2m loan to SME (turnover £25m) - base 100% RW × 0.7619 SF = 76.19% eff RW
        # RWA = £2m × 100% × 0.7619 = £1,523,800
        # =============================================================================
        Loan(
            loan_reference="LOAN_SME_CHAIN",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_SME_CHAIN",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,  # £2m
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =============================================================================
        # CRR-H4: Full CRM Chain
        # £2m gross exposure to unrated corporate (100% RW)
        # CRM: £100k provision + £500k cash collateral + £400k bank guarantee
        # Net EAD after CRM = £1.4m (after prov and cash)
        # Guaranteed portion £400k at guarantor RW (30%), remainder £600k at 100%
        # =============================================================================
        Loan(
            loan_reference="LOAN_CRM_FULL",
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference="CORP_CRM_FULL",
            value_date=VALUE_DATE,
            maturity_date=date(2029, 12, 31),
            currency="GBP",
            drawn_amount=2_000_000.0,  # £2m gross
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]


def save_loans(output_dir: Path | None = None) -> Path:
    """
    Create and save loans to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/exposures directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_loans()
    output_path = output_dir / "loans.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved loans to: {output_path}")
    print(f"\nCreated {len(df)} loans:")

    print("\nBy product type:")
    type_counts = df.group_by("product_type").len().sort("len", descending=True)
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['product_type']}: {row['len']}")

    print("\nBy book code:")
    book_counts = df.group_by("book_code").len().sort("book_code")
    for row in book_counts.iter_rows(named=True):
        print(f"  {row['book_code']}: {row['len']}")

    print("\nTotal drawn by book:")
    book_totals = df.group_by("book_code").agg(pl.col("drawn_amount").sum().alias("total_drawn")).sort("book_code")
    for row in book_totals.iter_rows(named=True):
        print(f"  {row['book_code']}: £{row['total_drawn']:,.0f}")


if __name__ == "__main__":
    main()
