"""
CRR CRM supervisory haircuts (CRR Art. 224).

Implements collateral haircut lookups and adjustments.
"""

import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_FX_HAIRCUT,
    CRR_HAIRCUTS,
)


def get_collateral_haircut(
    collateral_type: str,
    cqs: int | None = None,
    residual_maturity_years: float | None = None,
    is_main_index: bool = False,
) -> Decimal:
    """
    Get supervisory haircut for collateral (CRR Art. 224).

    Args:
        collateral_type: Type of collateral
        cqs: Credit quality step of issuer (for debt securities)
        residual_maturity_years: Remaining maturity
        is_main_index: For equity, whether it's on a main index

    Returns:
        Haircut as Decimal (e.g., 0.02 for 2%)
    """
    collateral_lower = collateral_type.lower()

    # Cash - 0%
    if collateral_lower in ("cash", "deposit"):
        return CRR_HAIRCUTS["cash"]

    # Gold - 15%
    if collateral_lower == "gold":
        return CRR_HAIRCUTS["gold"]

    # Government bonds
    if collateral_lower in ("govt_bond", "sovereign_bond", "government_bond", "gilt"):
        maturity = residual_maturity_years or 5.0
        if cqs == 1:
            if maturity <= 1:
                return CRR_HAIRCUTS["govt_bond_cqs1_0_1y"]
            elif maturity <= 5:
                return CRR_HAIRCUTS["govt_bond_cqs1_1_5y"]
            else:
                return CRR_HAIRCUTS["govt_bond_cqs1_5y_plus"]
        elif cqs in (2, 3):
            if maturity <= 1:
                return CRR_HAIRCUTS["govt_bond_cqs2_3_0_1y"]
            elif maturity <= 5:
                return CRR_HAIRCUTS["govt_bond_cqs2_3_1_5y"]
            else:
                return CRR_HAIRCUTS["govt_bond_cqs2_3_5y_plus"]
        # CQS 4+ or unrated - use higher haircut
        return Decimal("0.15")

    # Corporate bonds
    if collateral_lower in ("corp_bond", "corporate_bond"):
        maturity = residual_maturity_years or 5.0
        if cqs == 1:
            if maturity <= 1:
                return CRR_HAIRCUTS["corp_bond_cqs1_0_1y"]
            elif maturity <= 5:
                return CRR_HAIRCUTS["corp_bond_cqs1_1_5y"]
            else:
                return CRR_HAIRCUTS["corp_bond_cqs1_5y_plus"]
        elif cqs in (2, 3):
            if maturity <= 1:
                return CRR_HAIRCUTS["corp_bond_cqs2_3_0_1y"]
            elif maturity <= 5:
                return CRR_HAIRCUTS["corp_bond_cqs2_3_1_5y"]
            else:
                return CRR_HAIRCUTS["corp_bond_cqs2_3_5y_plus"]
        # Lower rated - not eligible or high haircut
        return Decimal("0.20")

    # Equity
    if collateral_lower in ("equity", "shares", "stock"):
        if is_main_index:
            return CRR_HAIRCUTS["equity_main_index"]
        return CRR_HAIRCUTS["equity_other"]

    # Receivables
    if collateral_lower in ("receivables", "trade_receivables"):
        return CRR_HAIRCUTS["receivables"]

    # Real estate (not typically haircut-based in CRM, but for completeness)
    if collateral_lower in ("real_estate", "property", "rre", "cre"):
        return Decimal("0.00")  # RE uses LTV-based treatment

    # Other physical collateral
    return CRR_HAIRCUTS["other_physical"]


def get_fx_haircut(exposure_currency: str, collateral_currency: str) -> Decimal:
    """
    Get FX mismatch haircut (CRR Art. 224).

    Args:
        exposure_currency: Currency of exposure
        collateral_currency: Currency of collateral

    Returns:
        FX haircut (0% if same currency, 8% if different)
    """
    if exposure_currency.upper() == collateral_currency.upper():
        return Decimal("0.00")
    return CRR_FX_HAIRCUT


def calculate_adjusted_collateral_value(
    collateral_value: Decimal, collateral_haircut: Decimal, fx_haircut: Decimal = Decimal("0.00")
) -> Decimal:
    """
    Calculate adjusted collateral value after haircuts (CRR Art. 223).

    Args:
        collateral_value: Market value of collateral
        collateral_haircut: Collateral-specific haircut
        fx_haircut: FX mismatch haircut (default 0%)

    Returns:
        Adjusted collateral value

    Formula: C_adjusted = C × (1 - Hc - Hfx)
    """
    total_haircut = collateral_haircut + fx_haircut
    return collateral_value * (Decimal("1") - total_haircut)


def apply_maturity_mismatch(
    collateral_value: Decimal,
    collateral_maturity_years: float,
    exposure_maturity_years: float,
    minimum_maturity_years: float = 0.25,
) -> tuple[Decimal, str]:
    """
    Apply maturity mismatch adjustment (CRR Art. 238).

    Args:
        collateral_value: Adjusted collateral value
        collateral_maturity_years: Residual maturity of collateral
        exposure_maturity_years: Residual maturity of exposure
        minimum_maturity_years: Minimum maturity threshold (default 3 months)

    Returns:
        Tuple of (adjusted_value, description)

    Formula:
        If t < T: Adjusted = C × (t - 0.25) / (T - 0.25)
        Where t = collateral maturity, T = exposure maturity (capped at 5y)
    """
    # If collateral maturity >= exposure maturity, no adjustment
    if collateral_maturity_years >= exposure_maturity_years:
        return collateral_value, "No maturity mismatch adjustment"

    # If collateral maturity < 3 months, no protection
    if collateral_maturity_years < minimum_maturity_years:
        return Decimal("0"), "Collateral maturity < 3 months, no protection"

    # Apply adjustment
    t = max(collateral_maturity_years, minimum_maturity_years)
    T = min(max(exposure_maturity_years, minimum_maturity_years), 5.0)

    adjustment_factor = Decimal(str((t - 0.25) / (T - 0.25)))
    adjusted_value = collateral_value * adjustment_factor

    desc = f"Maturity adj: {adjustment_factor:.3f} (t={t:.1f}y, T={T:.1f}y)"
    return adjusted_value, desc
