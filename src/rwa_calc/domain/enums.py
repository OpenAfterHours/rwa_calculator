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

from __future__ import annotations

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
    PRA PS1/26 UK implementation of Basel 3.1.

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

    COVERED_BOND = "covered_bond"
    """Covered bonds (CRR Art. 129, PRA PS1/26 Art. 129)"""

    HIGH_RISK = "high_risk"
    """Items associated with particularly high risk (CRR Art. 112(l), Art. 128)"""

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

    EQUITY = "equity"
    """Equity approach - routes to equity calculator or SA equity risk weights"""


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

    CLASSIFICATION = "classification"
    """Exposure classification issues"""


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

    Short-term (≤3m) risk weights differ from long-term — see B31_SCRA_SHORT_TERM_RISK_WEIGHTS.
    """

    A = "A"
    """Meets all minimum requirements + buffers → 40% RW (>3m), 20% (≤3m)"""

    A_ENHANCED = "A_ENHANCED"
    """CET1 >= 14% AND leverage ratio >= 5% → 30% RW (>3m), 20% (≤3m) (CRE20.19)"""

    B = "B"
    """CET1 > 5.5%, Leverage > 3%, meets minimum requirements → 75% RW (>3m), 50% (≤3m)"""

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
    Full Risk - 100% CCF under SA and F-IRB (Table A1 Row 1)

    -- Direct credit substitutes, guarantees, acceptances, credit derivatives
    """

    FRC = "full_risk_commitment"
    """
    Full Risk Commitment - 100% CCF under SA and F-IRB (Table A1 Row 2)

    Commitments with certain drawdown, distinct from Row 1 (credit substitutes).
    -- Factoring / invoice discounting facilities
    -- Outright forward purchase agreements
    -- Asset sale and repurchase agreements (repos)
    -- Forward deposits
    -- Partly-paid shares and securities
    -- Other commitments with certain drawdowns

    Ref: PRA PS1/26 Art. 111 Table A1 Row 2, CRR Annex I para 2
    Under Basel 3.1 A-IRB, these cannot use own-estimate CCFs even if revolving
    (Art. 166D(1)(a) carve-out).
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

    OC = "other_commit"
    """
    Other Commitments - 40% CCF under Basel 3.1 SA (PRA Art. 111 Table A1 Row 5)

    -- All other commitments not in FR/MR/MLR/LR categories.
    Under CRR, these were 0% (same as LR); Basel 3.1 introduces the 40% category.
    """

    LR = "low_risk"
    """
    Low Risk - 0% CCF under SA and F-IRB
    -- Unconditionally cancellable commitments
    """


class PermissionMode(StrEnum):
    """
    High-level permission mode for the calculation.

    Controls whether the firm uses the Standardised Approach for all exposures
    or routes exposures to IRB based on model-level permissions.

    When IRB is selected, approach routing is driven entirely by the
    ``model_permissions`` input table — each model's approved approach
    (AIRB, FIRB, slotting) is resolved per-exposure. Exposures without
    a matching model permission fall back to SA.
    """

    STANDARDISED = "standardised"
    """All exposures use the Standardised Approach."""

    IRB = "irb"
    """
    IRB approaches permitted, driven by model-level permissions.

    Requires ``model_permissions`` input data. Without it, all exposures
    fall back to SA with a warning.
    """


class EquityType(StrEnum):
    """
    Types of equity exposures for risk weight determination.

    Used for both Article 133 (SA) and Article 155 (IRB Simple) approaches.
    """

    CENTRAL_BANK = "central_bank"
    """Central bank equity - 0% CRR SA (sovereign treatment)"""

    LISTED = "listed"
    """Listed equity on recognised exchange - 100% CRR SA / 250% B31 SA / 290% IRB Simple"""

    EXCHANGE_TRADED = "exchange_traded"
    """Explicitly exchange-traded - 100% CRR SA / 250% B31 SA / 290% IRB Simple"""

    GOVERNMENT_SUPPORTED = "government_supported"
    """Government programme equity - 100% CRR SA / 100% B31 SA / 190% IRB Simple"""

    UNLISTED = "unlisted"
    """Unlisted equity - 100% CRR SA (Art. 133(2)) / 250% B31 SA / 370% IRB Simple"""

    SPECULATIVE = "speculative"
    """Speculative unlisted - 100% CRR SA (Art. 133(2)) / 400% B31 SA / 370% IRB Simple"""

    PRIVATE_EQUITY = "private_equity"
    """Private equity holdings - 100% CRR SA (Art. 133(2)) / 400% B31 SA (Art. 133(5)) / 370% IRB Simple"""

    PRIVATE_EQUITY_DIVERSIFIED = "private_equity_diversified"
    """PE in diversified portfolio - 100% CRR SA / 400% B31 SA (Art. 133(5)) / 190% IRB Simple"""

    SUBORDINATED_DEBT = "subordinated_debt"
    """Subordinated debt / non-equity own funds - 100% CRR SA / 150% B31 SA (Art. 133(1))"""

    CIU = "ciu"
    """Collective investment undertakings - 150% CRR SA (Art. 132(2)) / 250% listed or 400% unlisted B31 SA"""

    OTHER = "other"
    """Other equity exposures - 100% CRR SA (Art. 133(2)) / 250% B31 SA / 370% IRB Simple"""


class EquityApproach(StrEnum):
    """
    Equity exposure calculation approach.
    """

    SA = "sa"
    """
    Article 133 Standardised Approach:
    - CRR: 0% central bank, 100% all other equity (Art. 133(2) flat)
    - B31: 0% central bank, 100% govt-supported, 250% standard, 400% higher-risk
    """

    IRB_SIMPLE = "irb_simple"
    """
    Article 155 IRB Simple Risk Weight Method:
    - 190% for diversified private equity
    - 290% for exchange-traded
    - 370% for other equity
    """


class InstitutionType(StrEnum):
    """
    Institution type for output floor applicability (PRA PS1/26 Art. 92 para 2A).

    The output floor applies only to specific (institution_type, reporting_basis)
    combinations. Exempt entities use U-TREA (no floor add-on).
    """

    STANDALONE_UK = "standalone_uk"
    """Stand-alone UK institution — floor applies on individual basis (para 2A(a)(i))."""

    RING_FENCED_BODY = "ring_fenced_body"
    """Ring-fenced body in a sub-consolidation group — floor applies on
    sub-consolidated basis (para 2A(a)(ii)). Exempt at individual level (para 2A(c))."""

    NON_RING_FENCED = "non_ring_fenced"
    """Non-ring-fenced institution on sub-consolidated basis — exempt (para 2A(b))."""

    INTERNATIONAL_SUBSIDIARY = "international_subsidiary"
    """International subsidiary CRR consolidation entity — exempt (para 2A(d))."""

    CRR_CONSOLIDATION_ENTITY = "crr_consolidation_entity"
    """Non-international-subsidiary CRR consolidation entity — floor applies
    on consolidated basis (para 2A(a)(iii))."""


class ReportingBasis(StrEnum):
    """
    Basis on which the capital calculation is performed.

    Determines output floor applicability in combination with InstitutionType
    (PRA PS1/26 Art. 92 para 2A, Reporting (CRR) Part Rule 2.2A).
    """

    INDIVIDUAL = "individual"
    """Individual entity basis — applies to stand-alone UK institutions."""

    SUB_CONSOLIDATED = "sub_consolidated"
    """Sub-consolidated basis — applies to ring-fenced body sub-groups."""

    CONSOLIDATED = "consolidated"
    """Consolidated basis — applies to UK group-level CRR consolidation entities."""


class CRMCollateralMethod(StrEnum):
    """
    Method for recognising financial collateral in credit risk mitigation.

    Institutions must elect one method for financial collateral recognition.
    The choice applies firm-wide for all SA exposures (CRR Art. 191A / PRA PS1/26 Art. 191A).
    IRB exposures always use the Foundation Collateral Method regardless.
    """

    COMPREHENSIVE = "comprehensive"
    """Financial Collateral Comprehensive Method (Art. 223-224).

    Default method. Reduces EAD via supervisory haircuts applied to collateral
    market values (H_c, H_fx, maturity mismatch). Both SA and IRB eligible.
    """

    SIMPLE = "simple"
    """Financial Collateral Simple Method (Art. 222).

    SA-only. Substitutes the risk weight on the collateralised portion with the
    collateral's own SA risk weight, subject to a 20% floor. EAD is NOT reduced.
    Special 0% RW for same-currency cash deposits and 0%-RW sovereign bonds.
    """


class AIRBCollateralMethod(StrEnum):
    """
    A-IRB collateral recognition method under Basel 3.1 (Art. 169A/169B).

    Under Basel 3.1, A-IRB firms must use one of two methods to recognise
    collateral in LGD estimates. Under CRR, A-IRB is free-form (no method
    constraint). Art. 191A Part 2 governs the choice.
    """

    LGD_MODELLING = "lgd_modelling"
    """LGD Modelling Collateral Method (Art. 169A).

    Default for A-IRB under Basel 3.1.  The firm models collateral effects
    directly in its LGD estimates.  When the firm has sufficient data to model
    a collateral type in a jurisdiction (Art. 169A(1)(a)), own LGD captures
    collateral effects — the calculator keeps the modelled LGD.  When data is
    insufficient (Art. 169B), the calculator falls back to the Foundation
    Collateral Method formula (Art. 230/231) with the firm's own unsecured LGD
    as LGDU instead of the supervisory value.
    """

    FOUNDATION = "foundation"
    """Foundation Collateral Method (Art. 229-231).

    A-IRB firm elects to use the same Foundation Collateral Method as F-IRB,
    with supervisory LGDS values and supervisory LGDU.  Same formula and
    parameters as F-IRB collateral recognition.
    """
