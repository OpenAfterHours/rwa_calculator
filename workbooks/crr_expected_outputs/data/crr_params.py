"""
CRR (EU 575/2013) regulatory parameters for RWA calculations.

This module contains all lookup tables and constants required for SA and IRB
RWA calculations under the Capital Requirements Regulation as onshored into
UK law. This is the current UK framework, effective until 31 Dec 2026.

Key differences from Basel 3.1:
- SME supporting factor (0.7619) applies
- Infrastructure supporting factor (0.75) applies
- No output floor
- No A-IRB LGD floors
- 35%/50% residential mortgage treatment (not granular LTV bands)
- Single PD floor (0.03%) for all exposure classes

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 111: CCF
- CRR Art. 207-236: CRM
- CRR Art. 143-154: IRB approach
- CRR Art. 153(5): Slotting approach
- CRR Art. 501: SME supporting factor
"""

from decimal import Decimal
from typing import TypedDict

from src.rwa_calc.config.fx_rates import (
    CRR_REGULATORY_THRESHOLDS_EUR,
    get_crr_threshold_gbp,
)


# =============================================================================
# STANDARDISED APPROACH RISK WEIGHTS
# =============================================================================

# Sovereign risk weights by Credit Quality Step (CRR Art. 114)
CRR_CGCB_RW: dict[int | None, Decimal] = {
    1: Decimal("0.00"),   # AAA to AA-
    2: Decimal("0.20"),   # A+ to A-
    3: Decimal("0.50"),   # BBB+ to BBB-
    4: Decimal("1.00"),   # BB+ to BB-
    5: Decimal("1.00"),   # B+ to B-
    6: Decimal("1.50"),   # CCC+ and below
    None: Decimal("1.00"),  # Unrated
}

# Institution risk weights - UK deviation (CRR Art. 120-121)
# CQS 2 gets 30% instead of standard Basel 50%
CRR_INSTITUTION_RW_UK: dict[int | None, Decimal] = {
    1: Decimal("0.20"),   # AAA to AA-
    2: Decimal("0.30"),   # A+ to A- (UK deviation - 30% instead of 50%)
    3: Decimal("0.50"),   # BBB+ to BBB-
    4: Decimal("1.00"),   # BB+ to BB-
    5: Decimal("1.00"),   # B+ to B-
    6: Decimal("1.50"),   # CCC+ and below
    None: Decimal("0.40"),  # Unrated - derived from sovereign CQS2
}

# Institution risk weights - standard Basel (for comparison)
CRR_INSTITUTION_RW_STANDARD: dict[int | None, Decimal] = {
    1: Decimal("0.20"),
    2: Decimal("0.50"),   # Standard Basel
    3: Decimal("0.50"),
    4: Decimal("1.00"),
    5: Decimal("1.00"),
    6: Decimal("1.50"),
    None: Decimal("0.40"),
}

# Corporate risk weights by CQS (CRR Art. 122)
CRR_CORPORATE_RW: dict[int | None, Decimal] = {
    1: Decimal("0.20"),   # AAA to AA-
    2: Decimal("0.50"),   # A+ to A-
    3: Decimal("1.00"),   # BBB+ to BBB-
    4: Decimal("1.00"),   # BB+ to BB-
    5: Decimal("1.50"),   # B+ to B-
    6: Decimal("1.50"),   # CCC+ and below
    None: Decimal("1.00"),  # Unrated
}

# Retail exposure risk weight (CRR Art. 123)
CRR_RETAIL_RW: Decimal = Decimal("0.75")

# Residential mortgage risk weights (CRR Art. 125)
# CRR uses a simple split at 80% LTV, not granular bands like Basel 3.1
CRR_RESIDENTIAL_RW_LOW_LTV: Decimal = Decimal("0.35")   # LTV <= 80%
CRR_RESIDENTIAL_RW_HIGH_LTV: Decimal = Decimal("0.75")  # Portion above 80% LTV
CRR_RESIDENTIAL_LTV_THRESHOLD: Decimal = Decimal("0.80")

# Commercial real estate risk weights (CRR Art. 126)
CRR_COMMERCIAL_RW_LOW_LTV: Decimal = Decimal("0.50")    # LTV <= 50% with income cover
CRR_COMMERCIAL_RW_STANDARD: Decimal = Decimal("1.00")   # Otherwise
CRR_COMMERCIAL_LTV_THRESHOLD: Decimal = Decimal("0.50")


# =============================================================================
# CREDIT CONVERSION FACTORS (CRR Art. 111)
# =============================================================================

# CRR uses simpler CCF categories than Basel 3.1
CRR_CCF: dict[str, Decimal] = {
    # 0% CCF - Low risk
    "low_risk": Decimal("0.00"),
    "unconditionally_cancellable": Decimal("0.00"),

    # 20% CCF - Medium-low risk
    "medium_low_risk": Decimal("0.20"),
    "documentary_credit": Decimal("0.20"),
    "short_term_lc": Decimal("0.20"),
    "undrawn_short_term": Decimal("0.20"),  # <= 1 year

    # 50% CCF - Medium risk
    "medium_risk": Decimal("0.50"),
    "undrawn_long_term": Decimal("0.50"),   # > 1 year
    "performance_guarantee": Decimal("0.50"),
    "bid_bond": Decimal("0.50"),
    "nif_ruf": Decimal("0.50"),
    "standby_lc": Decimal("0.50"),

    # 100% CCF - Full risk
    "full_risk": Decimal("1.00"),
    "guarantee_given": Decimal("1.00"),
    "acceptance": Decimal("1.00"),
    "credit_derivative": Decimal("1.00"),
    "forward_purchase": Decimal("1.00"),
}


# =============================================================================
# SUPPORTING FACTORS (CRR Art. 501)
# =============================================================================

# SME supporting factor - Tiered approach (CRR2 Art. 501)
# The SME supporting factor uses a tiered structure based on total exposure:
#   - Exposures up to €2.5m: factor of 0.7619 (23.81% reduction)
#   - Exposures above €2.5m: factor of 0.85 (15% reduction)
#
# Formula: SME_factor = [min(E, €2.5m) × 0.7619 + max(E - €2.5m, 0) × 0.85] / E
#
# This means the effective factor ranges from 0.7619 (small exposures) to
# approaching 0.85 (very large exposures).
#
# Note: EUR thresholds are the regulatory source of truth. GBP equivalents are
# derived using the configurable FX rate in src/rwa_calc/config/fx_rates.py
#
# Reference: CRR2 Art. 501 (EU 2019/876 amending EU 575/2013)

# Tier 1: Exposures up to threshold
CRR_SME_SUPPORTING_FACTOR_TIER1: Decimal = Decimal("0.7619")

# Tier 2: Portion of exposures above threshold
CRR_SME_SUPPORTING_FACTOR_TIER2: Decimal = Decimal("0.85")

# Exposure threshold for tiered treatment
# EUR is canonical regulatory value; GBP derived from configurable FX rate
CRR_SME_EXPOSURE_THRESHOLD_EUR: Decimal = CRR_REGULATORY_THRESHOLDS_EUR["sme_exposure"]
CRR_SME_EXPOSURE_THRESHOLD_GBP: Decimal = get_crr_threshold_gbp("sme_exposure")

# Legacy constant for backwards compatibility (use calculate_sme_supporting_factor instead)
CRR_SME_SUPPORTING_FACTOR: Decimal = Decimal("0.7619")

# Infrastructure supporting factor (CRR Art. 501a)
CRR_INFRASTRUCTURE_SUPPORTING_FACTOR: Decimal = Decimal("0.75")

# SME turnover threshold (for eligibility, not the exposure threshold)
# EUR is canonical regulatory value; GBP derived from configurable FX rate
CRR_SME_TURNOVER_THRESHOLD_EUR: Decimal = CRR_REGULATORY_THRESHOLDS_EUR["sme_turnover"]
CRR_SME_TURNOVER_THRESHOLD_GBP: Decimal = get_crr_threshold_gbp("sme_turnover")


# =============================================================================
# SPECIALISED LENDING SLOTTING (CRR Art. 153(5))
# =============================================================================

class SlottingRiskWeights(TypedDict):
    """Risk weights for slotting categories."""
    strong: Decimal
    good: Decimal
    satisfactory: Decimal
    weak: Decimal
    default: Decimal


# CRR slotting risk weights (Art. 153(5))
# Note: CRR has same weights for Strong and Good categories
CRR_SLOTTING_RW: SlottingRiskWeights = {
    "strong": Decimal("0.70"),
    "good": Decimal("0.70"),         # Same as Strong under CRR
    "satisfactory": Decimal("1.15"),
    "weak": Decimal("2.50"),
    "default": Decimal("0.00"),      # 100% provisioned
}

# HVCRE uses same weights under CRR (unlike Basel 3.1)
CRR_SLOTTING_RW_HVCRE: SlottingRiskWeights = {
    "strong": Decimal("0.70"),
    "good": Decimal("0.70"),
    "satisfactory": Decimal("1.15"),
    "weak": Decimal("2.50"),
    "default": Decimal("0.00"),
}


# =============================================================================
# CREDIT RISK MITIGATION - HAIRCUTS (CRR Art. 224)
# =============================================================================

CRR_HAIRCUTS: dict[str, Decimal] = {
    # Cash and gold
    "cash": Decimal("0.00"),
    "gold": Decimal("0.15"),

    # Government bonds by CQS and maturity
    "govt_bond_cqs1_0_1y": Decimal("0.005"),
    "govt_bond_cqs1_1_5y": Decimal("0.02"),
    "govt_bond_cqs1_5y_plus": Decimal("0.04"),
    "govt_bond_cqs2_3_0_1y": Decimal("0.01"),
    "govt_bond_cqs2_3_1_5y": Decimal("0.03"),
    "govt_bond_cqs2_3_5y_plus": Decimal("0.06"),

    # Corporate bonds
    "corp_bond_cqs1_2_0_1y": Decimal("0.01"),
    "corp_bond_cqs1_2_1_5y": Decimal("0.04"),
    "corp_bond_cqs1_2_5y_plus": Decimal("0.06"),
    "corp_bond_cqs3_0_1y": Decimal("0.02"),
    "corp_bond_cqs3_1_5y": Decimal("0.06"),
    "corp_bond_cqs3_5y_plus": Decimal("0.08"),

    # Equity
    "equity_main_index": Decimal("0.15"),   # Main index (e.g., FTSE 100)
    "equity_other": Decimal("0.25"),        # Other listed equity

    # Other
    "receivables": Decimal("0.20"),
    "other_physical": Decimal("0.40"),
}

# Currency mismatch haircut (CRR Art. 224)
CRR_FX_HAIRCUT: Decimal = Decimal("0.08")  # 8%


# =============================================================================
# IRB PARAMETERS
# =============================================================================

# Single PD floor for all classes under CRR (Art. 163)
# Unlike Basel 3.1 which has differentiated floors
CRR_PD_FLOOR: Decimal = Decimal("0.0003")  # 0.03%

# F-IRB supervisory LGD values (CRR Art. 161)
CRR_FIRB_LGD: dict[str, Decimal] = {
    "unsecured_senior": Decimal("0.45"),
    "subordinated": Decimal("0.75"),
    "financial_collateral": Decimal("0.00"),
    "receivables": Decimal("0.35"),
    "residential_re": Decimal("0.35"),
    "commercial_re": Decimal("0.35"),
    "other_physical": Decimal("0.40"),
}

# Note: CRR A-IRB has no LGD floors (unlike Basel 3.1)
# Banks can use their own LGD estimates without floors


# =============================================================================
# MATURITY PARAMETERS (CRR Art. 162)
# =============================================================================

CRR_MATURITY_FLOOR: Decimal = Decimal("1.0")   # 1 year minimum
CRR_MATURITY_CAP: Decimal = Decimal("5.0")     # 5 year maximum


# =============================================================================
# EXPOSURE CLASS MAPPING (CRR Art. 112)
# =============================================================================

CRR_EXPOSURE_CLASSES = [
    "CENTRAL_GOVERNMENTS_CENTRAL_BANKS",
    "REGIONAL_GOVERNMENTS_LOCAL_AUTHORITIES",
    "PUBLIC_SECTOR_ENTITIES",
    "MULTILATERAL_DEVELOPMENT_BANKS",
    "INTERNATIONAL_ORGANISATIONS",
    "INSTITUTIONS",
    "CORPORATES",
    "RETAIL",
    "SECURED_BY_REAL_ESTATE",
    "PAST_DUE",
    "HIGHER_RISK_CATEGORIES",
    "COVERED_BONDS",
    "SECURITISATION",
    "INSTITUTIONS_CORPORATES_SHORT_TERM",
    "COLLECTIVE_INVESTMENT_UNDERTAKINGS",
    "EQUITY",
    "OTHER",
]
