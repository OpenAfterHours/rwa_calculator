"""
Regulatory parameters for RWA calculations.

Contains all lookup tables and constants required for SA and IRB RWA calculations
per CRE20-36 (Basel III), CRR, and UK PRA PS9/24 deviations.

References:
- CRE20: SA risk weights
- CRE21: SA credit risk mitigation
- CRE22: CRM haircuts and eligibility
- CRE30-36: IRB approach
- PRA PS9/24: UK Basel 3.1 implementation
"""

from typing import TypedDict


# =============================================================================
# STANDARDISED APPROACH RISK WEIGHTS
# =============================================================================

# Sovereign risk weights by Credit Quality Step (CRE20.7)
# CQS 0 represents unrated
CGCB_RISK_WEIGHTS: dict[int, float] = {
    1: 0.00,   # AAA to AA-
    2: 0.20,   # A+ to A-
    3: 0.50,   # BBB+ to BBB-
    4: 1.00,   # BB+ to BB-
    5: 1.00,   # B+ to B-
    6: 1.50,   # CCC+ and below
    0: 1.00,   # Unrated
}

# Institution risk weights - Basel standard ECRA (CRE20.16)
INSTITUTION_RISK_WEIGHTS: dict[int, float] = {
    1: 0.20,   # AAA to AA-
    2: 0.50,   # A+ to A- (Basel standard)
    3: 0.50,   # BBB+ to BBB-
    4: 1.00,   # BB+ to BB-
    5: 1.00,   # B+ to B-
    6: 1.50,   # CCC+ and below
    0: 0.40,   # Unrated (SCRA Grade A)
}

# Institution risk weights - UK deviation (PRA PS9/24)
# CQS 2 gets 30% instead of 50%
INSTITUTION_RISK_WEIGHTS_UK: dict[int, float] = {
    1: 0.20,   # AAA to AA-
    2: 0.30,   # A+ to A- (UK deviation - 30% instead of 50%)
    3: 0.50,   # BBB+ to BBB-
    4: 1.00,   # BB+ to BB-
    5: 1.00,   # B+ to B-
    6: 1.50,   # CCC+ and below
    0: 0.40,   # Unrated (SCRA Grade A)
}

# Corporate risk weights by CQS (CRE20.25-26)
CORPORATE_RISK_WEIGHTS: dict[int, float] = {
    1: 0.20,   # AAA to AA-
    2: 0.50,   # A+ to A-
    3: 0.75,   # BBB+ to BBB-
    4: 1.00,   # BB+ to BB-
    5: 1.50,   # B+ to B-
    6: 1.50,   # CCC+ and below
    0: 1.00,   # Unrated
}

# Retail exposure risk weight (CRE20.66)
RETAIL_RISK_WEIGHT: float = 0.75

# Residential mortgage risk weights by LTV band (CRE20.71-73)
# Format: (ltv_lower, ltv_upper, risk_weight)
RESIDENTIAL_MORTGAGE_RISK_WEIGHTS: list[tuple[float, float, float]] = [
    (0.00, 0.50, 0.20),   # LTV <= 50%: 20%
    (0.50, 0.60, 0.20),   # 50% < LTV <= 60%: 20%
    (0.60, 0.70, 0.25),   # 60% < LTV <= 70%: 25%
    (0.70, 0.80, 0.30),   # 70% < LTV <= 80%: 30%
    (0.80, 0.90, 0.35),   # 80% < LTV <= 90%: 35%
    (0.90, 1.00, 0.50),   # 90% < LTV <= 100%: 50%
    (1.00, float("inf"), 0.70),  # LTV > 100%: 70%
]

# Commercial real estate risk weights by LTV band (CRE20.83-85)
# For non-income-producing CRE
COMMERCIAL_RE_RISK_WEIGHTS: list[tuple[float, float, float]] = [
    (0.00, 0.60, 0.60),   # LTV <= 60%: 60%
    (0.60, 0.80, 0.80),   # 60% < LTV <= 80%: 80% (whole-loan approach)
    (0.80, float("inf"), 1.10),  # LTV > 80%: 110% (whole-loan)
]

# ADC (Acquisition/Development/Construction) risk weight (CRE20.87)
ADC_RISK_WEIGHT: float = 1.50  # 150% unless pre-sold
ADC_PRESOLD_RISK_WEIGHT: float = 1.00  # 100% if pre-sold


# =============================================================================
# SPECIALISED LENDING SLOTTING (CRE33)
# =============================================================================

class SlottingRiskWeights(TypedDict):
    """Risk weights for slotting categories by remaining maturity."""
    strong: float
    strong_short: float  # < 2.5 years
    good: float
    good_short: float    # < 2.5 years
    satisfactory: float
    weak: float
    default: float


SLOTTING_RISK_WEIGHTS: SlottingRiskWeights = {
    "strong": 0.70,
    "strong_short": 0.50,   # < 2.5 years remaining
    "good": 0.90,
    "good_short": 0.70,     # < 2.5 years remaining
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,        # 0% for defaulted (100% covered by provisions)
}

# HVCRE (High Volatility Commercial Real Estate) multiplier (CRE33.6)
HVCRE_MULTIPLIER: float = 1.25  # 25% higher than standard slotting


# =============================================================================
# IRB PARAMETERS
# =============================================================================

# PD floors by exposure class (Basel 3.1 - CRE31.6)
PD_FLOORS: dict[str, float] = {
    "CORPORATE": 0.0003,           # 0.03% = 3 basis points
    "CORPORATE_SME": 0.0003,       # 0.03%
    "CENTRAL_GOVT_CENTRAL_BANK": 0.0003,  # 0.03%
    "INSTITUTION": 0.0003,         # 0.03%
    "RETAIL": 0.0005,              # 0.05%
    "RETAIL_MORTGAGE": 0.0005,     # 0.05%
    "RETAIL_QRRE": 0.0010,         # 0.10%
    "RETAIL_SME": 0.0005,          # 0.05%
}

# F-IRB supervisory LGD values (CRE32.9-12)
FIRB_LGD: dict[str, dict[str, float]] = {
    "unsecured": {
        "senior": 0.45,            # 45% for senior unsecured
        "subordinated": 0.75,      # 75% for subordinated
    },
    "financial_collateral": {
        "senior": 0.00,            # 0% for cash, gold, eligible securities
    },
    "receivables": {
        "senior": 0.35,            # 35% (with 125% haircut)
    },
    "commercial_re": {
        "senior": 0.35,            # 35% for CRE (with 140% haircut)
    },
    "residential_re": {
        "senior": 0.35,            # 35% for RRE (with 140% haircut)
    },
    "other_physical": {
        "senior": 0.40,            # 40% for other physical collateral
    },
}

# A-IRB LGD floors by collateral type (Basel 3.1 - CRE32.20)
AIRB_LGD_FLOORS: dict[str, float] = {
    "unsecured": 0.25,             # 25% floor for unsecured corporate
    "financial_collateral": 0.00,  # 0% floor
    "receivables": 0.10,           # 10% floor
    "commercial_re": 0.10,         # 10% floor for CRE
    "residential_re": 0.05,        # 5% floor for RRE
    "other_physical": 0.15,        # 15% floor
    "retail_unsecured": 0.50,      # 50% floor for unsecured retail
    "retail_mortgage": 0.05,       # 5% floor for retail mortgages
    "retail_qrre": 0.50,           # 50% floor for QRRE
}


# =============================================================================
# ASSET CORRELATION PARAMETERS (CRE31)
# =============================================================================

class CorrelationParams(TypedDict):
    """Parameters for asset correlation calculation."""
    type: str           # "fixed" or "pd_dependent"
    r_min: float        # Minimum correlation (for PD-dependent)
    r_max: float        # Maximum correlation (for PD-dependent)
    fixed: float        # Fixed correlation value
    decay_factor: float # K factor in formula (50 for corp, 35 for retail)


CORRELATION_PARAMS: dict[str, CorrelationParams] = {
    # Corporate: R = 0.12 * f(PD) + 0.24 * (1 - f(PD)), where f(PD) = (1 - e^(-50*PD)) / (1 - e^(-50))
    "CORPORATE": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CORPORATE_SME": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CENTRAL_GOVT_CENTRAL_BANK": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "INSTITUTION": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    # Retail mortgage: R = 0.15 (fixed)
    "RETAIL_MORTGAGE": {
        "type": "fixed",
        "r_min": 0.15,
        "r_max": 0.15,
        "fixed": 0.15,
        "decay_factor": 0.0,
    },
    # QRRE: R = 0.04 (fixed)
    "RETAIL_QRRE": {
        "type": "fixed",
        "r_min": 0.04,
        "r_max": 0.04,
        "fixed": 0.04,
        "decay_factor": 0.0,
    },
    # Other retail: R = 0.03 * f(PD) + 0.16 * (1 - f(PD)), decay factor = 35
    "RETAIL": {
        "type": "pd_dependent",
        "r_min": 0.03,
        "r_max": 0.16,
        "fixed": 0.0,
        "decay_factor": 35.0,
    },
    "RETAIL_SME": {
        "type": "pd_dependent",
        "r_min": 0.03,
        "r_max": 0.16,
        "fixed": 0.0,
        "decay_factor": 35.0,
    },
}


# =============================================================================
# CREDIT RISK MITIGATION - HAIRCUTS (CRE22)
# =============================================================================

# Supervisory haircuts for collateral (CRE22.52-53)
# Format: {collateral_type: {issuer_type: {maturity_bucket: haircut}}}
COLLATERAL_HAIRCUTS: dict[str, dict] = {
    "cash": {"all": 0.00},  # 0% haircut for cash
    "gold": {"all": 0.15},  # 15% haircut for gold (volatility in price)

    # Sovereign debt securities (by residual maturity in years)
    "sovereign_debt": {
        "cqs_1": {
            "0-1": 0.005,    # 0.5%
            "1-3": 0.02,     # 2%
            "3-5": 0.02,     # 2%
            "5-10": 0.04,    # 4%
            "10+": 0.04,     # 4%
        },
        "cqs_2_3": {
            "0-1": 0.01,     # 1%
            "1-3": 0.03,     # 3%
            "3-5": 0.04,     # 4%
            "5-10": 0.06,    # 6%
            "10+": 0.12,     # 12%
        },
    },

    # Corporate debt securities
    "corporate_debt": {
        "cqs_1_2": {
            "0-1": 0.01,     # 1%
            "1-3": 0.04,     # 4%
            "3-5": 0.06,     # 6%
            "5-10": 0.10,    # 10%
            "10+": 0.12,     # 12%
        },
        "cqs_3": {
            "0-1": 0.02,     # 2%
            "1-3": 0.06,     # 6%
            "3-5": 0.08,     # 8%
            "5-10": 0.15,    # 15%
            "10+": 0.15,     # 15%
        },
    },

    # Equity
    "equity": {
        "main_index": 0.25,      # 25% for main index equities
        "other_listed": 0.35,    # 35% for other listed equities
    },

    # Other eligible collateral
    "receivables": {"all": 0.20},    # 20% for eligible receivables
    "other_physical": {"all": 0.40}, # 40% for other physical collateral
}

# Currency mismatch haircut (CRE22.54)
FX_HAIRCUT: float = 0.08  # 8% for currency mismatch


# =============================================================================
# CREDIT CONVERSION FACTORS (CCF) - CRE20.93-98
# =============================================================================

CCF_VALUES: dict[str, float] = {
    # 0% CCF
    "unconditionally_cancellable": 0.00,

    # 10% CCF (Basel 3.1 - retail unconditionally cancellable)
    "retail_unconditionally_cancellable": 0.10,

    # 20% CCF
    "short_term_trade_lc": 0.20,  # Self-liquidating trade LCs < 1 year
    "transaction_related": 0.20,  # Transaction-related contingencies

    # 40% CCF
    "committed_facility": 0.40,   # Other committed but undrawn facilities
    "nif_ruf": 0.40,              # Note issuance/revolving underwriting facilities

    # 50% CCF
    "performance_bonds": 0.50,    # Performance-related contingencies
    "bid_bonds": 0.50,
    "warranties": 0.50,

    # 100% CCF
    "direct_credit_substitute": 1.00,  # Guarantees, standby LCs
    "acceptances": 1.00,
    "forward_purchase": 1.00,
    "securities_lending": 1.00,
}


# =============================================================================
# MATURITY PARAMETERS (CRE32)
# =============================================================================

# Effective maturity floor and cap
MATURITY_FLOOR: float = 1.0  # 1 year minimum
MATURITY_CAP: float = 5.0    # 5 year maximum (for corporate)

# Maturity adjustment formula constants (CRE31.7)
# b(PD) = (0.11852 - 0.05478 * ln(PD))^2
# MA = (1 + (M - 2.5) * b) / (1 - 1.5 * b)


# =============================================================================
# OUTPUT FLOOR (Basel 3.1)
# =============================================================================

# Output floor percentage (CRE99)
OUTPUT_FLOOR_PERCENTAGE: float = 0.725  # 72.5% of SA equivalent at full implementation

# Transitional floor schedule
OUTPUT_FLOOR_TRANSITIONAL: dict[int, float] = {
    2025: 0.50,   # 50% from 1 Jan 2025
    2026: 0.55,   # 55% from 1 Jan 2026
    2027: 0.60,   # 60% from 1 Jan 2027
    2028: 0.65,   # 65% from 1 Jan 2028
    2029: 0.70,   # 70% from 1 Jan 2029
    2030: 0.725,  # 72.5% from 1 Jan 2030 (full implementation)
}
