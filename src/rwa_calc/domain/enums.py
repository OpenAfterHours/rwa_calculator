"""
Domain enums for RWA calculator.

Defines core enumerations used throughout the calculation pipeline:
- RegulatoryFramework: CRR vs Basel 3.1 toggle
- ExposureClass: Credit risk exposure classifications
- ApproachType: Calculation approach (SA, F-IRB, A-IRB)
- CQS: Credit Quality Steps for external ratings
- CollateralType: Categories of eligible collateral
- IFRSStage: IFRS 9 provision staging

These enums provide type safety and self-documenting code for the
dual-framework support (CRR until Dec 2026, Basel 3.1 from Jan 2027).
"""

from enum import Enum


class RegulatoryFramework(Enum):
    """
    Regulatory framework for RWA calculations.

    CRR: Capital Requirements Regulation (EU 575/2013) - Basel 3.0
         Effective until 31 December 2026
         Key features: SME supporting factors, simpler LTV treatment

    BASEL_3_1: PRA PS9/24 UK implementation of Basel 3.1
               Effective from 1 January 2027
               Key features: Output floor, LGD floors, differentiated PD floors
    """

    CRR = "CRR"
    BASEL_3_1 = "BASEL_3_1"


class ExposureClass(Enum):
    """
    Exposure classes for credit risk classification.

    Aligned with both CRR (Art. 112) and Basel 3.1 (CRE20).
    Used for determining applicable risk weights and IRB parameters.
    """

    # Sovereign and central bank exposures (CRR Art. 112(a), CRE20.7-15)
    SOVEREIGN = "sovereign"

    # Exposures to institutions (CRR Art. 112(d), CRE20.16-21)
    INSTITUTION = "institution"

    # Corporate exposures (CRR Art. 112(g), CRE20.22-25)
    CORPORATE = "corporate"

    # SME corporate (turnover <= EUR 50m / GBP 44m)
    CORPORATE_SME = "corporate_sme"

    # Retail - residential mortgages (CRR Art. 112(h), CRE20.71-81)
    RETAIL_MORTGAGE = "retail_mortgage"

    # Retail - qualifying revolving retail exposures (CRE30.23-24)
    RETAIL_QRRE = "retail_qrre"

    # Retail - other (CRR Art. 112(h), CRE20.65-70)
    RETAIL_OTHER = "retail_other"

    # Specialised lending - slotting approach (CRE33)
    SPECIALISED_LENDING = "specialised_lending"

    # Equity exposures (CRR Art. 112(p), CRE20.58-62)
    EQUITY = "equity"

    # Exposures in default (CRR Art. 112(j), CRE20.88-90)
    DEFAULTED = "defaulted"

    # Exposures to PSEs (CRR Art. 112(c), CRE20.7-15)
    PSE = "pse"

    # Exposures to MDBs and international organisations (CRR Art. 117-118)
    MDB = "mdb"

    # Regional government and local authorities (CRR Art. 115)
    RGLA = "rgla"

    # Other items (CRR Art. 112(q))
    OTHER = "other"


class ApproachType(Enum):
    """
    Calculation approach for credit risk.

    Determines the methodology used for risk weight calculation.
    Must be approved by the regulator (PRA) for each exposure class.
    """

    # Standardised Approach - risk weights from lookup tables
    SA = "standardised"

    # Foundation IRB - bank-estimated PD, supervisory LGD/EAD
    FIRB = "foundation_irb"

    # Advanced IRB - bank-estimated PD, LGD, EAD
    AIRB = "advanced_irb"

    # Slotting approach for specialised lending (CRE33)
    SLOTTING = "slotting"


class CQS(Enum):
    """
    Credit Quality Steps for external ratings mapping.

    Maps external agency ratings to standardised risk weight lookup.
    CQS 1-6 correspond to decreasing credit quality.
    UNRATED applies when no eligible rating exists.

    Mapping (approximate):
        CQS1: AAA to AA- (S&P/Fitch), Aaa to Aa3 (Moody's)
        CQS2: A+ to A-
        CQS3: BBB+ to BBB-
        CQS4: BB+ to BB-
        CQS5: B+ to B-
        CQS6: CCC+ and below
    """

    CQS1 = 1
    CQS2 = 2
    CQS3 = 3
    CQS4 = 4
    CQS5 = 5
    CQS6 = 6
    UNRATED = 0  # Using 0 instead of None for better type handling


class CollateralType(Enum):
    """
    Categories of eligible collateral for CRM.

    Determines applicable haircuts and LGD treatment.
    Based on CRR Art. 197-199 and CRE22.
    """

    # Cash and eligible financial collateral (CRE22.40)
    FINANCIAL = "financial"

    # Real estate / immovable property (CRE22.72-78)
    IMMOVABLE = "immovable"

    # Eligible receivables (CRE22.65-66)
    RECEIVABLES = "receivables"

    # Other eligible physical collateral (CRE22.67-71)
    OTHER_PHYSICAL = "other_physical"

    # Collateral not eligible for CRM
    OTHER = "other"


class IFRSStage(Enum):
    """
    IFRS 9 expected credit loss staging.

    Determines provision recognition and expected loss comparison.
    """

    # Stage 1: 12-month ECL (performing)
    STAGE_1 = 1

    # Stage 2: Lifetime ECL, not credit-impaired
    STAGE_2 = 2

    # Stage 3: Lifetime ECL, credit-impaired (defaulted)
    STAGE_3 = 3


class ErrorSeverity(Enum):
    """
    Severity levels for calculation errors.

    Used to classify issues encountered during RWA calculation.
    """

    # Informational warning - calculation proceeds
    WARNING = "warning"

    # Error that may affect result accuracy
    ERROR = "error"

    # Critical error that may invalidate results
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """
    Categories for calculation errors.

    Enables filtering and analysis of error types.
    """

    # Missing or invalid input data
    DATA_QUALITY = "data_quality"

    # Violation of regulatory business rules
    BUSINESS_RULE = "business_rule"

    # Schema validation failures
    SCHEMA_VALIDATION = "schema_validation"

    # Configuration issues
    CONFIGURATION = "configuration"

    # Internal calculation errors
    CALCULATION = "calculation"

    # Hierarchy resolution issues
    HIERARCHY = "hierarchy"

    # CRM application issues
    CRM = "crm"


class SlottingCategory(Enum):
    """
    Supervisory slotting categories for specialised lending.

    Based on CRE33.5-8. Determines risk weights for project finance,
    object finance, commodities finance, and IPRE.
    """

    STRONG = "strong"  # 70% RW (50% if < 2.5yr maturity)
    GOOD = "good"  # 90% RW (70% if < 2.5yr maturity)
    SATISFACTORY = "satisfactory"  # 115% RW
    WEAK = "weak"  # 250% RW
    DEFAULT = "default"  # 0% RW (100% provisioning expected)


class SpecialisedLendingType(Enum):
    """
    Types of specialised lending exposures.

    Based on CRE33.1-4.
    """

    PROJECT_FINANCE = "project_finance"
    OBJECT_FINANCE = "object_finance"
    COMMODITIES_FINANCE = "commodities_finance"
    IPRE = "ipre"  # Income-producing real estate
    HVCRE = "hvcre"  # High-volatility commercial real estate


class PropertyType(Enum):
    """
    Property types for real estate collateral.

    Determines applicable LTV bands and risk weights.
    """

    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    ADC = "adc"  # Acquisition, Development, Construction


class Seniority(Enum):
    """
    Seniority of exposure for LGD determination.

    Under F-IRB, senior exposures get 45% LGD, subordinated get 75%.
    """

    SENIOR = "senior"
    SUBORDINATED = "subordinated"


class CommitmentType(Enum):
    """
    Commitment types for CCF determination.

    Affects credit conversion factors for undrawn amounts.
    """

    # Unconditionally cancellable - 0% CCF under SA (10% under Basel 3.1)
    UNCONDITIONALLY_CANCELLABLE = "unconditionally_cancellable"

    # Other committed facilities - 40% or higher CCF
    COMMITTED = "committed"

    # Trade finance - 20% CCF
    TRADE_FINANCE = "trade_finance"

    # Direct credit substitutes - 100% CCF
    DIRECT_CREDIT_SUBSTITUTE = "direct_credit_substitute"


class RiskType(Enum):
    """
    Off-balance sheet risk categories for CCF determination.

    Based on CRR Art. 111 CCF categories.
    Under F-IRB (CRR Art. 166(8)), MR and MLR become 75% CCF.

    Values:
        FR (full_risk): 100% CCF under SA and F-IRB
            Direct credit substitutes, guarantees, acceptances

        MR (medium_risk): 50% CCF under SA, 75% CCF under F-IRB
            NIFs, RUFs, standby LCs, committed undrawn facilities

        MLR (medium_low_risk): 20% CCF under SA, 75% CCF under F-IRB
            Documentary credits, trade finance, short-term self-liquidating

        LR (low_risk): 0% CCF under SA and F-IRB
            Unconditionally cancellable commitments
    """

    FR = "full_risk"
    MR = "medium_risk"
    MLR = "medium_low_risk"
    LR = "low_risk"


class IRBApproachOption(Enum):
    """
    User-selectable IRB approach options.

    Determines which IRB approaches are permitted for the calculation.
    Used by the API and UI for explicit approach selection.

    Values:
        SA_ONLY: Standardised Approach only - no IRB permissions
        FIRB: Foundation IRB permitted (where regulatory allowed)
            - Retail classes fall back to SA (FIRB not permitted for retail)
            - Specialised lending can use FIRB or slotting
        AIRB: Advanced IRB permitted (where regulatory allowed)
            - Specialised lending uses slotting (AIRB not permitted)
        FULL_IRB: Both FIRB and AIRB permitted
            - AIRB takes precedence when both are permitted
        RETAIL_AIRB_CORPORATE_FIRB: Hybrid approach for firms with:
            - AIRB approval for retail exposures
            - FIRB approval for corporate exposures
            Corporates can be reclassified to retail if:
            - Managed as part of retail pool (is_managed_as_retail=True)
            - Aggregated exposure < EUR 1m
            - Has internally modelled LGD
            With property collateral → RETAIL_MORTGAGE, otherwise → RETAIL_OTHER
    """

    SA_ONLY = "sa_only"
    FIRB = "firb"
    AIRB = "airb"
    FULL_IRB = "full_irb"
    RETAIL_AIRB_CORPORATE_FIRB = "retail_airb_corporate_firb"


class EquityType(Enum):
    """
    Types of equity exposures for risk weight determination.

    Used for both Article 133 (SA) and Article 155 (IRB Simple) approaches.

    Values:
        CENTRAL_BANK: Central bank equity - 0% SA (Art. 133(6))
        LISTED: Listed equity on recognised exchange - 100% SA / 290% IRB
        EXCHANGE_TRADED: Explicitly exchange-traded - 100% SA / 290% IRB
        GOVERNMENT_SUPPORTED: Government programme equity - 100% SA / 190% IRB
        UNLISTED: Unlisted equity - 250% SA / 370% IRB
        SPECULATIVE: Speculative unlisted/venture capital - 400% SA / 370% IRB
        PRIVATE_EQUITY: Private equity holdings - 250% SA / 370% IRB
        PRIVATE_EQUITY_DIVERSIFIED: Private equity in diversified portfolio - 250% SA / 190% IRB
        CIU: Collective investment undertakings - 250% SA / 370% IRB (or look-through)
        OTHER: Other equity exposures - 250% SA / 370% IRB
    """

    CENTRAL_BANK = "central_bank"
    LISTED = "listed"
    EXCHANGE_TRADED = "exchange_traded"
    GOVERNMENT_SUPPORTED = "government_supported"
    UNLISTED = "unlisted"
    SPECULATIVE = "speculative"
    PRIVATE_EQUITY = "private_equity"
    PRIVATE_EQUITY_DIVERSIFIED = "private_equity_diversified"
    CIU = "ciu"
    OTHER = "other"


class EquityApproach(Enum):
    """
    Equity exposure calculation approach.

    Determines which regulatory article applies for equity risk weights.

    Values:
        SA: Article 133 Standardised Approach
            - 0% for central bank
            - 100% for listed/government-supported
            - 250% for unlisted
            - 400% for speculative

        IRB_SIMPLE: Article 155 IRB Simple Risk Weight Method
            - 190% for diversified private equity
            - 290% for exchange-traded
            - 370% for other equity
    """

    SA = "sa"
    IRB_SIMPLE = "irb_simple"
