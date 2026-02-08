"""
Standardised Approach (SA) risk weight calculations.

Provides lookup functions for SA risk weights by exposure class,
following CRE20 and UK PRA PS9/24 deviations.
"""

from typing import Literal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.rwa_expected_outputs.data.regulatory_params import (
    CGCB_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_UK,
    CORPORATE_RISK_WEIGHTS,
    RETAIL_RISK_WEIGHT,
    RESIDENTIAL_MORTGAGE_RISK_WEIGHTS,
    COMMERCIAL_RE_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS,
    HVCRE_MULTIPLIER,
    ADC_RISK_WEIGHT,
    ADC_PRESOLD_RISK_WEIGHT,
)


def get_cgcb_risk_weight(cqs: int | None) -> float:
    """
    Get SA risk weight for central govt/central bank exposure.

    Args:
        cqs: Credit Quality Step (1-6), or None/0 for unrated

    Returns:
        Risk weight as decimal (e.g., 0.20 for 20%)

    Reference: CRE20.7
    """
    if cqs is None or cqs == 0:
        return CGCB_RISK_WEIGHTS[0]
    return CGCB_RISK_WEIGHTS.get(cqs, CGCB_RISK_WEIGHTS[0])


def get_institution_risk_weight(
    cqs: int | None,
    use_uk_deviation: bool = True,
) -> float:
    """
    Get SA risk weight for institution exposure.

    Args:
        cqs: Credit Quality Step (1-6), or None/0 for unrated
        use_uk_deviation: If True, use UK-specific weights (30% for CQS2)

    Returns:
        Risk weight as decimal

    Reference: CRE20.16, PRA PS9/24 (UK deviation for CQS2)
    """
    lookup = INSTITUTION_RISK_WEIGHTS_UK if use_uk_deviation else INSTITUTION_RISK_WEIGHTS
    if cqs is None or cqs == 0:
        return lookup[0]
    return lookup.get(cqs, lookup[0])


def get_corporate_risk_weight(cqs: int | None) -> float:
    """
    Get SA risk weight for corporate exposure.

    Args:
        cqs: Credit Quality Step (1-6), or None/0 for unrated

    Returns:
        Risk weight as decimal

    Reference: CRE20.25-26
    """
    if cqs is None or cqs == 0:
        return CORPORATE_RISK_WEIGHTS[0]
    return CORPORATE_RISK_WEIGHTS.get(cqs, CORPORATE_RISK_WEIGHTS[0])


def get_retail_risk_weight() -> float:
    """
    Get SA risk weight for retail exposure.

    Returns:
        Risk weight as decimal (0.75 = 75%)

    Reference: CRE20.66
    """
    return RETAIL_RISK_WEIGHT


def get_mortgage_risk_weight(
    ltv: float,
    property_type: Literal["residential", "commercial"] = "residential",
    is_income_producing: bool = False,
    is_adc: bool = False,
    is_presold: bool = False,
) -> float:
    """
    Get SA risk weight for mortgage/real estate exposure.

    Args:
        ltv: Loan-to-value ratio as decimal (e.g., 0.60 for 60%)
        property_type: "residential" or "commercial"
        is_income_producing: Whether repayment depends on property income
        is_adc: Whether it's acquisition/development/construction
        is_presold: If ADC, whether it's pre-sold

    Returns:
        Risk weight as decimal

    Reference: CRE20.71-87
    """
    # ADC treatment (CRE20.87)
    if is_adc:
        return ADC_PRESOLD_RISK_WEIGHT if is_presold else ADC_RISK_WEIGHT

    # Select appropriate table
    if property_type == "residential":
        rw_table = RESIDENTIAL_MORTGAGE_RISK_WEIGHTS
    else:
        rw_table = COMMERCIAL_RE_RISK_WEIGHTS

    # Find risk weight for LTV band
    for ltv_lower, ltv_upper, rw in rw_table:
        if ltv_lower < ltv <= ltv_upper:
            return rw
        if ltv <= ltv_lower and ltv_lower == 0:
            return rw

    # Return highest RW if above all bands
    return rw_table[-1][2]


def get_commercial_re_risk_weight(ltv: float, is_income_producing: bool = False) -> float:
    """
    Get SA risk weight for commercial real estate.

    Args:
        ltv: Loan-to-value ratio as decimal
        is_income_producing: Whether repayment depends on property income

    Returns:
        Risk weight as decimal

    Reference: CRE20.83-85
    """
    return get_mortgage_risk_weight(
        ltv=ltv,
        property_type="commercial",
        is_income_producing=is_income_producing,
    )


def get_slotting_risk_weight(
    category: Literal["strong", "good", "satisfactory", "weak", "default"],
    remaining_maturity_years: float = 3.0,
    is_hvcre: bool = False,
) -> float:
    """
    Get risk weight for specialised lending using slotting approach.

    Args:
        category: Slotting category
        remaining_maturity_years: Remaining maturity in years
        is_hvcre: Whether it's high-volatility commercial real estate

    Returns:
        Risk weight as decimal

    Reference: CRE33.5-6
    """
    # Get base risk weight
    if category == "strong":
        rw = SLOTTING_RISK_WEIGHTS["strong_short"] if remaining_maturity_years < 2.5 else SLOTTING_RISK_WEIGHTS["strong"]
    elif category == "good":
        rw = SLOTTING_RISK_WEIGHTS["good_short"] if remaining_maturity_years < 2.5 else SLOTTING_RISK_WEIGHTS["good"]
    elif category == "satisfactory":
        rw = SLOTTING_RISK_WEIGHTS["satisfactory"]
    elif category == "weak":
        rw = SLOTTING_RISK_WEIGHTS["weak"]
    else:  # default
        rw = SLOTTING_RISK_WEIGHTS["default"]

    # Apply HVCRE multiplier if applicable
    if is_hvcre and category not in ["default"]:
        rw = rw * HVCRE_MULTIPLIER

    return rw


def calculate_sa_rwa(
    ead: float,
    risk_weight: float,
) -> float:
    """
    Calculate RWA using Standardised Approach.

    Args:
        ead: Exposure at Default
        risk_weight: Risk weight as decimal (e.g., 0.50 for 50%)

    Returns:
        Risk-Weighted Assets

    Formula: RWA = EAD x Risk Weight
    """
    return ead * risk_weight
