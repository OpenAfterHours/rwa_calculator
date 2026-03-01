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

from enum import IntEnum, StrEnum


class RegulatoryFramework(StrEnum):
    """
    Regulatory framework for RWA calculations.
    """

    CRR = "CRR"
    """
    Capital Requirements Regulation (EU 575/2013) - Basel 3.0.

    Effective until 31 December 2026.
    Key features: SME supporting factors, simpler LTV treatment.
    """

    BASEL_3_1 = "BASEL_3_1"
    """
    PRA PS9/24 UK implementation of Basel 3.1.

    Effective from 1 January 2027.
    Key features: Output floor, LGD floors, differentiated PD floors.
    """


class ExposureClass(StrEnum):
    """
    Exposure classes for credit risk classification (CRR Art. 112, Basel 3.1 CRE20).
    """

    CENTRAL_GOVT_CENTRAL_BANK = "central_govt_central_bank"
    """Central government and central bank exposures (CRR Art. 112(a), CRE20.7-15)"""

    INSTITUTION = "institution"
    """Exposures to institutions (CRR Art. 112(d), CRE20.16-21)"""

    CORPORATE = "corporate"
    """Corporate exposures (CRR Art. 112(g), CRE20.22-25)"""

    CORPORATE_SME = "corporate_sme"
    """SME corporate (turnover <= EUR 50m / GBP 44m)"""

    RETAIL_MORTGAGE = "retail_mortgage"
    """Retail - residential mortgages (CRR Art. 112(h), CRE20.71-81)"""

    RETAIL_QRRE = "retail_qrre"
    """Retail - qualifying revolving retail exposures (CRE30.23-24)"""

    RETAIL_OTHER = "retail_other"
    """Retail - other (CRR Art. 112(h), CRE20.65-70)"""

    SPECIALISED_LENDING = "specialised_lending"
    """Specialised lending - slotting approach (CRE33)"""

    EQUITY = "equity"
    """Equity exposures (CRR Art. 112(p), CRE20.58-62)"""

    DEFAULTED = "defaulted"
    """Exposures in default (CRR Art. 112(j), CRE20.88-90)"""

    PSE = "pse"
    """Exposures to PSEs (CRR Art. 112(c), CRE20.7-15)"""

    MDB = "mdb"
    """Exposures to MDBs and international organisations (CRR Art. 117-118)"""

    RGLA = "rgla"
    """Regional government and local authorities (CRR Art. 115)"""

    OTHER = "other"
    """Other items (CRR Art. 112(q))"""


class ApproachType(StrEnum):
    """
    Calculation approach for credit risk.
    """

    SA = "standardised"
    """Standardised Approach - risk weights from lookup tables"""

    FIRB = "foundation_irb"
    """Foundation IRB - bank-estimated PD, supervisory LGD/EAD"""

    AIRB = "advanced_irb"
    """Advanced IRB - bank-estimated PD, LGD, EAD"""

    SLOTTING = "slotting"
    """Slotting approach for specialised lending (CRE33)"""


class CQS(IntEnum):
    """
    Credit Quality Steps for external ratings mapping.
    """

    CQS1 = 1
    """CQS 1: AAA to AA- (S&P/Fitch), Aaa to Aa3 (Moody's)"""

    CQS2 = 2
    """CQS 2: A+ to A-"""

    CQS3 = 3
    """CQS 3: BBB+ to BBB-"""

    CQS4 = 4
    """CQS 4: BB+ to BB-"""

    CQS5 = 5
    """CQS 5: B+ to B-"""

    CQS6 = 6
    """CQS 6: CCC+ and below"""

    UNRATED = 0
    """UNRATED: Applies when no eligible rating exists (uses 0 for type handling)"""


class CollateralType(StrEnum):
    """
    Categories of eligible collateral for CRM.

    Determines applicable haircuts and LGD treatment based on CRR Art. 197-199 and CRE22.
    """

    FINANCIAL = "financial"
    """Cash and eligible financial collateral (CRE22.40)"""

    IMMOVABLE = "immovable"
    """Real estate / immovable property (CRE22.72-78)"""

    RECEIVABLES = "receivables"
    """Eligible receivables (CRE22.65-66)"""

    OTHER_PHYSICAL = "other_physical"
    """Other eligible physical collateral (CRE22.67-71)"""

    OTHER = "other"
    """Collateral not eligible for CRM"""


class IFRSStage(IntEnum):
    """
    IFRS 9 expected credit loss staging.
    """

    STAGE_1 = 1
    """Stage 1: 12-month ECL (performing)"""

    STAGE_2 = 2
    """Stage 2: Lifetime ECL, not credit-impaired"""

    STAGE_3 = 3
    """Stage 3: Lifetime ECL, credit-impaired (defaulted)"""


class ErrorSeverity(StrEnum):
    """
    Severity levels for calculation errors.
    """

    WARNING = "warning"
    """Informational warning - calculation proceeds"""

    ERROR = "error"
    """Error that may affect result accuracy"""

    CRITICAL = "critical"
    """Critical error that may invalidate results"""


class ErrorCategory(StrEnum):
    """
    Categories for calculation errors.
    """

    DATA_QUALITY = "data_quality"
    """Missing or invalid input data"""

    BUSINESS_RULE = "business_rule"
    """Violation of regulatory business rules"""

    SCHEMA_VALIDATION = "schema_validation"
    """Schema validation failures"""

    CONFIGURATION = "configuration"
    """Configuration issues"""

    CALCULATION = "calculation"
    """Internal calculation errors"""

    HIERARCHY = "hierarchy"
    """Hierarchy resolution issues"""

    CRM = "crm"
    """CRM application issues"""


class SlottingCategory(StrEnum):
    """
    Supervisory slotting categories for specialised lending (CRE33.5-8).
    """

    STRONG = "strong"
    """70% RW (50% if < 2.5yr maturity)"""

    GOOD = "good"
    """90% RW (70% if < 2.5yr maturity)"""

    SATISFACTORY = "satisfactory"
    """115% RW"""

    WEAK = "weak"
    """250% RW"""

    DEFAULT = "default"
    """0% RW (100% provisioning expected)"""


class SpecialisedLendingType(StrEnum):
    """
    Types of specialised lending exposures (CRE33.1-4).
    """

    PROJECT_FINANCE = "project_finance"
    """Project Finance"""

    OBJECT_FINANCE = "object_finance"
    """Object Finance"""

    COMMODITIES_FINANCE = "commodities_finance"
    """Commodities Finance"""

    IPRE = "ipre"
    """Income-producing real estate"""

    HVCRE = "hvcre"
    """High-volatility commercial real estate"""


class PropertyType(StrEnum):
    """
    Property types for real estate collateral.
    """

    RESIDENTIAL = "residential"
    """Residential property"""

    COMMERCIAL = "commercial"
    """Commercial property"""

    ADC = "adc"
    """Acquisition, Development, Construction (ADC)"""


class Seniority(StrEnum):
    """
    Seniority of exposure for LGD determination.
    """

    SENIOR = "senior"
    """
    Senior unsecured debt - first claim after secured creditors.

    Under F-IRB, senior exposures get 45% LGD.
    """

    SUBORDINATED = "subordinated"
    """
    Subordinated unsecured debt - claim after senior unsecured creditors.

    Under F-IRB, subordinated exposures get 75% LGD.
    Under Basel 3.1 SA, subordinated debt gets flat 150% RW (CRE20.47).
    """


class SCRAGrade(StrEnum):
    """
    Standardised Credit Risk Assessment Approach (SCRA) grades (Basel 3.1 CRE20.16-21).
    """

    A = "A"
    """CET1 > 14%, Leverage > 5%, meets all regulatory requirements → 40% RW"""

    B = "B"
    """CET1 > 5.5%, Leverage > 3%, meets minimum requirements → 75% RW"""

    C = "C"
    """Below minimum regulatory requirements → 150% RW"""


class CommitmentType(StrEnum):
    """
    Commitment types for CCF determination.

    Affects credit conversion factors for undrawn amounts.
    """

    UNCONDITIONALLY_CANCELLABLE = "unconditionally_cancellable"
    """Unconditionally Cancellable - 0% CCF under SA (10% under Basel 3.1)"""

    COMMITTED = "committed"
    """Other committed facilities - 40% or higher CCF"""

    TRADE_FINANCE = "trade_finance"
    """Trade finance - 20% CCF"""

    DIRECT_CREDIT_SUBSTITUTE = "direct_credit_substitute"
    """Direct credit substitutes - 100% CCF"""


class RiskType(StrEnum):
    """
    Off-balance sheet risk categories for CCF determination.

    Based on CRR Art. 111 CCF categories.
    """

    FR = "full_risk"
    """
    Full Risk - 100% CCF under SA and F-IRB
    
    -- Direct credit substitutes, guarantees, acceptances
    """

    MR = "medium_risk"
    """
    Medium Risk - 50% CCF under SA, 75% CCF under F-IRB (CRR Art. 166(8))
    
    -- NIFs, RUFs, standby LCs, committed undrawn facilities
    """

    MLR = "medium_low_risk"
    """
    Medium Low Risk - 20% CCF under SA, 75% CCF under F-IRB (CRR Art. 166(8))

    -- Documentary credits, trade finance, short-term self-liquidating
    """

    LR = "low_risk"
    """
    Low Risk - 0% CCF under SA and F-IRB
    -- Unconditionally cancellable commitments
    """


class IRBApproachOption(StrEnum):
    """
    User-selectable IRB approach options.

    Determines which IRB approaches are permitted for the calculation.
    """

    SA_ONLY = "sa_only"
    """Standardised Approach only - no IRB permissions"""

    FIRB = "firb"
    """
    Foundation IRB permitted (where regulatory allowed).
    
    - Retail classes fall back to SA (FIRB not permitted for retail)
    - Specialised lending can use FIRB or slotting
    """

    AIRB = "airb"
    """
    Advanced IRB permitted (where regulatory allowed).
    
    - Specialised lending uses slotting (AIRB not permitted)
    """

    FULL_IRB = "full_irb"
    """
    Full IRB permissions (FIRB and AIRB).
    
    - AIRB takes precedence when both are permitted
    """

    RETAIL_AIRB_CORPORATE_FIRB = "retail_airb_corporate_firb"
    """
    Hybrid approach: AIRB for retail and FIRB for corporate.
    
    Corporates can be reclassified to retail if:
    - Managed as part of retail pool (is_managed_as_retail=True)
    - Aggregated exposure < EUR 1m
    - Has internally modelled LGD
    With property collateral → RETAIL_MORTGAGE, otherwise → RETAIL_OTHER
    """


class EquityType(StrEnum):
    """
    Types of equity exposures for risk weight determination.

    Used for both Article 133 (SA) and Article 155 (IRB Simple) approaches.
    """

    CENTRAL_BANK = "central_bank"
    """Central bank equity - 0% SA (Art. 133(6))"""

    LISTED = "listed"
    """Listed equity on recognised exchange - 100% SA / 290% IRB"""

    EXCHANGE_TRADED = "exchange_traded"
    """Explicitly exchange-traded - 100% SA / 290% IRB"""

    GOVERNMENT_SUPPORTED = "government_supported"
    """Government programme equity - 100% SA / 190% IRB"""

    UNLISTED = "unlisted"
    """Unlisted equity - 250% SA / 370% IRB"""

    SPECULATIVE = "speculative"
    """Speculative unlisted/venture capital - 400% SA / 370% IRB"""

    PRIVATE_EQUITY = "private_equity"
    """Private equity holdings - 250% SA / 370% IRB"""

    PRIVATE_EQUITY_DIVERSIFIED = "private_equity_diversified"
    """Private equity in diversified portfolio - 250% SA / 190% IRB"""

    CIU = "ciu"
    """Collective investment undertakings - 250% SA / 370% IRB (or look-through)"""

    OTHER = "other"
    """Other equity exposures - 250% SA / 370% IRB"""


class EquityApproach(StrEnum):
    """
    Equity exposure calculation approach.
    """

    SA = "sa"
    """
    Article 133 Standardised Approach:
    - 0% for central bank
    - 100% for listed/government-supported
    - 250% for unlisted
    - 400% for speculative
    """

    IRB_SIMPLE = "irb_simple"
    """
    Article 155 IRB Simple Risk Weight Method:
    - 190% for diversified private equity
    - 290% for exchange-traded
    - 370% for other equity
    """
