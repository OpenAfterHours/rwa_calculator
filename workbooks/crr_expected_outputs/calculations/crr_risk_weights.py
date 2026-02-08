"""
CRR SA risk weight lookup functions.

Implements risk weight lookups per CRR Articles 112-134.
"""

from decimal import Decimal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_CGCB_RW,
    CRR_INSTITUTION_RW_UK,
    CRR_INSTITUTION_RW_STANDARD,
    CRR_CORPORATE_RW,
    CRR_RETAIL_RW,
    CRR_RESIDENTIAL_RW_LOW_LTV,
    CRR_RESIDENTIAL_RW_HIGH_LTV,
    CRR_RESIDENTIAL_LTV_THRESHOLD,
    CRR_COMMERCIAL_RW_LOW_LTV,
    CRR_COMMERCIAL_RW_STANDARD,
    CRR_COMMERCIAL_LTV_THRESHOLD,
    CRR_SLOTTING_RW,
    CRR_SLOTTING_RW_HVCRE,
)


def get_cgcb_rw(cqs: int | None) -> Decimal:
    """
    Get risk weight for central govt/central bank exposure (CRR Art. 114).

    Args:
        cqs: Credit Quality Step (1-6) or None for unrated

    Returns:
        Risk weight as Decimal
    """
    return CRR_CGCB_RW.get(cqs, CRR_CGCB_RW[None])


def get_institution_rw(
    cqs: int | None,
    country: str = "GB",
    use_uk_deviation: bool = True
) -> Decimal:
    """
    Get risk weight for institution (CRR Art. 120-121).

    Args:
        cqs: Credit Quality Step (1-6) or None for unrated
        country: Country code
        use_uk_deviation: Whether to apply UK deviation (30% for CQS2)

    Returns:
        Risk weight as Decimal

    Note: UK applies 30% RW for CQS 2 instead of standard Basel 50%
    """
    if country == "GB" and use_uk_deviation:
        return CRR_INSTITUTION_RW_UK.get(cqs, CRR_INSTITUTION_RW_UK[None])
    return CRR_INSTITUTION_RW_STANDARD.get(cqs, CRR_INSTITUTION_RW_STANDARD[None])


def get_corporate_rw(cqs: int | None) -> Decimal:
    """
    Get risk weight for corporate exposure (CRR Art. 122).

    Args:
        cqs: Credit Quality Step (1-6) or None for unrated

    Returns:
        Risk weight as Decimal
    """
    return CRR_CORPORATE_RW.get(cqs, CRR_CORPORATE_RW[None])


def get_retail_rw() -> Decimal:
    """
    Get risk weight for retail exposure (CRR Art. 123).

    Returns:
        Risk weight as Decimal (75%)
    """
    return CRR_RETAIL_RW


def get_residential_mortgage_rw(ltv: Decimal) -> tuple[Decimal, str]:
    """
    Get risk weight for residential mortgage (CRR Art. 125).

    Args:
        ltv: Loan-to-value ratio as Decimal

    Returns:
        Tuple of (risk_weight, description)

    CRR Treatment:
    - LTV <= 80%: 35% on whole exposure
    - LTV > 80%: Split approach - 35% on portion up to 80% LTV,
                 75% on excess (effectively weighted average)
    """
    if ltv <= CRR_RESIDENTIAL_LTV_THRESHOLD:
        return CRR_RESIDENTIAL_RW_LOW_LTV, f"35% RW (LTV {ltv:.0%} <= 80%)"

    # Split treatment for high LTV
    # Calculate weighted average RW
    portion_low = CRR_RESIDENTIAL_LTV_THRESHOLD / ltv
    portion_high = (ltv - CRR_RESIDENTIAL_LTV_THRESHOLD) / ltv

    avg_rw = (CRR_RESIDENTIAL_RW_LOW_LTV * portion_low +
              CRR_RESIDENTIAL_RW_HIGH_LTV * portion_high)

    return avg_rw, f"Split RW ({ltv:.0%} LTV): {avg_rw:.1%}"


def get_commercial_re_rw(
    ltv: Decimal,
    has_income_cover: bool = True
) -> tuple[Decimal, str]:
    """
    Get risk weight for commercial real estate (CRR Art. 126).

    Args:
        ltv: Loan-to-value ratio as Decimal
        has_income_cover: Whether rental income >= 1.5x interest payments

    Returns:
        Tuple of (risk_weight, description)

    CRR Treatment:
    - LTV <= 50% AND income cover: 50%
    - Otherwise: 100% (no preferential treatment)
    """
    if ltv <= CRR_COMMERCIAL_LTV_THRESHOLD and has_income_cover:
        return CRR_COMMERCIAL_RW_LOW_LTV, f"50% RW (LTV {ltv:.0%} <= 50% with income cover)"

    return CRR_COMMERCIAL_RW_STANDARD, f"100% RW (standard treatment)"


def get_slotting_rw(
    category: str,
    is_hvcre: bool = False
) -> Decimal:
    """
    Get risk weight for specialised lending slotting (CRR Art. 153(5)).

    Args:
        category: Slotting category (strong, good, satisfactory, weak, default)
        is_hvcre: Whether this is high-volatility commercial real estate

    Returns:
        Risk weight as Decimal

    Note: Under CRR, HVCRE uses same weights as non-HVCRE (unlike Basel 3.1)
    """
    category_lower = category.lower()

    if is_hvcre:
        return CRR_SLOTTING_RW_HVCRE.get(category_lower, Decimal("1.15"))

    return CRR_SLOTTING_RW.get(category_lower, Decimal("1.15"))


def calculate_sa_rwa(
    ead: Decimal,
    risk_weight: Decimal,
    supporting_factor: Decimal = Decimal("1.0")
) -> Decimal:
    """
    Calculate SA RWA.

    Args:
        ead: Exposure at Default
        risk_weight: Risk weight as Decimal
        supporting_factor: SME/infrastructure factor (default 1.0 = no adjustment)

    Returns:
        RWA as Decimal

    Formula: RWA = EAD × RW × Supporting Factor
    """
    return ead * risk_weight * supporting_factor
