"""
Credit Risk Mitigation (CRM) haircut calculations.

Implements supervisory haircuts, maturity mismatch adjustments,
and FX mismatch adjustments per CRE22.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.rwa_expected_outputs.data.regulatory_params import (
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
)


def _get_maturity_bucket(residual_maturity_years: float) -> str:
    """Convert residual maturity to bucket string."""
    if residual_maturity_years <= 1:
        return "0-1"
    elif residual_maturity_years <= 3:
        return "1-3"
    elif residual_maturity_years <= 5:
        return "3-5"
    elif residual_maturity_years <= 10:
        return "5-10"
    else:
        return "10+"


def get_collateral_haircut(
    collateral_type: str,
    issuer_type: str = "sovereign",
    cqs: int = 1,
    residual_maturity_years: float = 5.0,
) -> float:
    """
    Get supervisory haircut for collateral.

    Args:
        collateral_type: Type of collateral (cash, gold, sovereign_debt, etc.)
        issuer_type: Issuer type for securities (sovereign, corporate)
        cqs: Credit quality step of issuer (1-6)
        residual_maturity_years: Residual maturity in years

    Returns:
        Haircut as decimal (e.g., 0.04 for 4%)

    Reference: CRE22.52-53
    """
    # Cash - 0% haircut
    if collateral_type == "cash":
        return 0.0

    # Gold - 15% haircut
    if collateral_type == "gold":
        return COLLATERAL_HAIRCUTS.get("gold", {}).get("all", 0.15)

    # Equity
    if collateral_type == "equity":
        equity_haircuts = COLLATERAL_HAIRCUTS.get("equity", {})
        return equity_haircuts.get("main_index", 0.25)

    # Receivables
    if collateral_type == "receivables":
        return COLLATERAL_HAIRCUTS.get("receivables", {}).get("all", 0.20)

    # Other physical
    if collateral_type == "other_physical":
        return COLLATERAL_HAIRCUTS.get("other_physical", {}).get("all", 0.40)

    # Sovereign debt
    if collateral_type in ["sovereign_debt", "government_bond", "gilt"]:
        haircuts = COLLATERAL_HAIRCUTS.get("sovereign_debt", {})
        maturity_bucket = _get_maturity_bucket(residual_maturity_years)

        if cqs == 1:
            return haircuts.get("cqs_1", {}).get(maturity_bucket, 0.04)
        else:  # CQS 2-3
            return haircuts.get("cqs_2_3", {}).get(maturity_bucket, 0.06)

    # Corporate debt
    if collateral_type in ["corporate_debt", "corporate_bond"]:
        haircuts = COLLATERAL_HAIRCUTS.get("corporate_debt", {})
        maturity_bucket = _get_maturity_bucket(residual_maturity_years)

        if cqs <= 2:
            return haircuts.get("cqs_1_2", {}).get(maturity_bucket, 0.06)
        else:  # CQS 3
            return haircuts.get("cqs_3", {}).get(maturity_bucket, 0.08)

    # Default fallback
    return 0.20


def apply_maturity_mismatch(
    collateral_value: float,
    collateral_maturity_years: float,
    exposure_maturity_years: float,
    min_maturity_years: float = 0.25,
) -> float:
    """
    Apply maturity mismatch adjustment to collateral value.

    Args:
        collateral_value: Value of collateral after haircuts
        collateral_maturity_years: Remaining maturity of collateral (t)
        exposure_maturity_years: Remaining maturity of exposure (T)
        min_maturity_years: Minimum collateral maturity (default 3 months)

    Returns:
        Adjusted collateral value

    Formula (CRE22.66):
        C_adj = C * (t - 0.25) / (T - 0.25)

    If collateral maturity < 3 months (0.25 years), collateral value = 0

    Reference: CRE22.65-66
    """
    # Collateral with maturity < 3 months has no value for CRM
    if collateral_maturity_years < min_maturity_years:
        return 0.0

    # No mismatch if collateral matures after exposure
    if collateral_maturity_years >= exposure_maturity_years:
        return collateral_value

    # Apply maturity mismatch formula
    t = collateral_maturity_years
    T = exposure_maturity_years

    adjustment = (t - 0.25) / (T - 0.25)
    return collateral_value * max(adjustment, 0.0)


def apply_fx_mismatch(
    collateral_value: float,
    exposure_currency: str,
    collateral_currency: str,
    fx_haircut: float = FX_HAIRCUT,
) -> float:
    """
    Apply FX mismatch haircut to collateral value.

    Args:
        collateral_value: Value of collateral after other haircuts
        exposure_currency: Currency of the exposure
        collateral_currency: Currency of the collateral
        fx_haircut: FX mismatch haircut (default 8%)

    Returns:
        Adjusted collateral value

    Formula: C_adj = C * (1 - Hfx) where Hfx = 8%

    Reference: CRE22.54
    """
    if exposure_currency == collateral_currency:
        return collateral_value

    return collateral_value * (1 - fx_haircut)


def calculate_adjusted_collateral_value(
    collateral_market_value: float,
    collateral_type: str,
    issuer_type: str = "sovereign",
    cqs: int = 1,
    residual_maturity_years: float = 5.0,
    exposure_maturity_years: float = 5.0,
    exposure_currency: str = "GBP",
    collateral_currency: str = "GBP",
) -> dict:
    """
    Calculate fully adjusted collateral value after all haircuts.

    Args:
        collateral_market_value: Current market value of collateral
        collateral_type: Type of collateral
        issuer_type: Issuer type for securities
        cqs: Credit quality step of issuer
        residual_maturity_years: Collateral residual maturity
        exposure_maturity_years: Exposure residual maturity
        exposure_currency: Currency of exposure
        collateral_currency: Currency of collateral

    Returns:
        Dictionary with:
        - market_value: Original market value
        - base_haircut: Supervisory haircut applied
        - value_after_haircut: Value after base haircut
        - maturity_mismatch_adj: Whether maturity mismatch applied
        - value_after_maturity_adj: Value after maturity adjustment
        - fx_mismatch_adj: Whether FX mismatch applied
        - adjusted_value: Final adjusted collateral value
    """
    # Get and apply base haircut
    base_haircut = get_collateral_haircut(
        collateral_type=collateral_type,
        issuer_type=issuer_type,
        cqs=cqs,
        residual_maturity_years=residual_maturity_years,
    )
    value_after_haircut = collateral_market_value * (1 - base_haircut)

    # Apply maturity mismatch adjustment
    has_maturity_mismatch = residual_maturity_years < exposure_maturity_years
    value_after_maturity_adj = apply_maturity_mismatch(
        collateral_value=value_after_haircut,
        collateral_maturity_years=residual_maturity_years,
        exposure_maturity_years=exposure_maturity_years,
    )

    # Apply FX mismatch adjustment
    has_fx_mismatch = exposure_currency != collateral_currency
    adjusted_value = apply_fx_mismatch(
        collateral_value=value_after_maturity_adj,
        exposure_currency=exposure_currency,
        collateral_currency=collateral_currency,
    )

    return {
        "market_value": collateral_market_value,
        "base_haircut": base_haircut,
        "value_after_haircut": value_after_haircut,
        "maturity_mismatch_adj": has_maturity_mismatch,
        "value_after_maturity_adj": value_after_maturity_adj,
        "fx_mismatch_adj": has_fx_mismatch,
        "adjusted_value": adjusted_value,
    }


def calculate_guarantee_substitution(
    exposure_amount: float,
    exposure_risk_weight: float,
    guarantee_amount: float,
    guarantor_risk_weight: float,
) -> dict:
    """
    Calculate RWA using guarantee substitution approach.

    Args:
        exposure_amount: EAD of the exposure
        exposure_risk_weight: Risk weight of underlying exposure
        guarantee_amount: Amount covered by guarantee
        guarantor_risk_weight: Risk weight of guarantor

    Returns:
        Dictionary with:
        - covered_amount: Amount covered by guarantee
        - uncovered_amount: Amount not covered
        - covered_rwa: RWA on covered portion (at guarantor RW)
        - uncovered_rwa: RWA on uncovered portion (at original RW)
        - total_rwa: Sum of covered and uncovered RWA

    Reference: CRE22.70-71
    """
    # Split exposure into covered and uncovered portions
    covered_amount = min(guarantee_amount, exposure_amount)
    uncovered_amount = exposure_amount - covered_amount

    # Calculate RWA for each portion
    covered_rwa = covered_amount * guarantor_risk_weight
    uncovered_rwa = uncovered_amount * exposure_risk_weight

    return {
        "covered_amount": covered_amount,
        "uncovered_amount": uncovered_amount,
        "covered_rwa": covered_rwa,
        "uncovered_rwa": uncovered_rwa,
        "total_rwa": covered_rwa + uncovered_rwa,
    }
