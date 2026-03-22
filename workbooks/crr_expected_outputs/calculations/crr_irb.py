"""
CRR IRB formula calculations.

Wraps the shared IRB formulas with CRR specific defaults.

Key differences from Basel 3.1:
- Single PD floor (0.03%) for all exposure classes
- No A-IRB LGD floors
- 1.06 scaling factor for all exposures (removed in Basel 3.1)
- SME supporting factor (0.7619) available
"""

from decimal import Decimal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import shared IRB formulas (core K calculation is framework-independent)
from workbooks.shared.irb_formulas import (
    calculate_k,
    calculate_maturity_adjustment as _base_calculate_maturity_adjustment,
    calculate_irb_rwa as _base_calculate_irb_rwa,
    calculate_expected_loss,
    apply_pd_floor as _base_apply_pd_floor,
)

# Import CRR specific parameters
from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_PD_FLOOR,
    CRR_FIRB_LGD,
    CRR_MATURITY_FLOOR,
    CRR_MATURITY_CAP,
)


def apply_pd_floor(pd: float, exposure_class: str | None = None) -> float:
    """
    Apply CRR PD floor.

    Args:
        pd: Raw probability of default
        exposure_class: Exposure class (not used in CRR - single floor)

    Returns:
        Floored PD

    CRR: Single 0.03% PD floor for all exposure classes
    (Unlike Basel 3.1 which has differentiated floors)
    """
    return _base_apply_pd_floor(pd, float(CRR_PD_FLOOR))


def get_firb_lgd(
    collateral_type: str = "unsecured",
    is_subordinated: bool = False
) -> Decimal:
    """
    Get F-IRB supervisory LGD (CRR Art. 161).

    Args:
        collateral_type: Type of collateral
        is_subordinated: Whether exposure is subordinated

    Returns:
        Supervisory LGD as Decimal
    """
    if is_subordinated:
        return CRR_FIRB_LGD["subordinated"]

    # Map collateral type to LGD
    lgd_mapping = {
        "unsecured": "unsecured_senior",
        "senior_unsecured": "unsecured_senior",
        "financial_collateral": "financial_collateral",
        "cash": "financial_collateral",
        "receivables": "receivables",
        "residential_re": "residential_re",
        "residential_real_estate": "residential_re",
        "rre": "residential_re",
        "commercial_re": "commercial_re",
        "commercial_real_estate": "commercial_re",
        "cre": "commercial_re",
        "other": "other_physical",
        "other_physical": "other_physical",
    }

    lgd_key = lgd_mapping.get(collateral_type.lower(), "unsecured_senior")
    return CRR_FIRB_LGD.get(lgd_key, CRR_FIRB_LGD["unsecured_senior"])


def calculate_maturity_adjustment(
    pd: float,
    maturity: float,
    apply_adjustment: bool = True,
) -> float:
    """
    Calculate maturity adjustment factor for corporate/wholesale exposures.

    Uses CRR maturity floor (1 year) and cap (5 years).

    Args:
        pd: Probability of default (floored)
        maturity: Effective maturity in years
        apply_adjustment: Whether to apply adjustment (False for retail)

    Returns:
        Maturity adjustment factor

    Reference: CRR Art. 162
    """
    return _base_calculate_maturity_adjustment(
        pd,
        maturity,
        apply_adjustment=apply_adjustment,
        maturity_floor=float(CRR_MATURITY_FLOOR),
        maturity_cap=float(CRR_MATURITY_CAP),
    )


def calculate_irb_rwa(
    ead: float,
    pd: float,
    lgd: float,
    correlation: float,
    maturity: float = 2.5,
    exposure_class: str = "CORPORATE",
    apply_maturity_adjustment: bool = True,
    apply_pd_floor_flag: bool = True,
) -> dict:
    """
    Calculate RWA using CRR IRB approach.

    Args:
        ead: Exposure at Default
        pd: Probability of default (raw)
        lgd: Loss given default
        correlation: Asset correlation (should include SME adjustment if applicable)
        maturity: Effective maturity in years
        exposure_class: Exposure class
        apply_maturity_adjustment: Whether to apply MA (False for retail)
        apply_pd_floor_flag: Whether to apply PD floor

    Returns:
        Dictionary with calculation details

    Key CRR differences from Basel 3.1:
    - Single PD floor (0.03%) for all classes
    - No A-IRB LGD floors
    - 1.06 scaling factor for non-retail (removed in Basel 3.1)

    Note: For SME corporates, ensure correlation is calculated with turnover
    using calculate_correlation(pd, exposure_class, turnover=turnover_m)
    to get the firm size adjustment per CRR Art. 153(4).

    Reference: CRR Art. 153-154
    """
    return _base_calculate_irb_rwa(
        ead=ead,
        pd=pd,
        lgd=lgd,
        correlation=correlation,
        maturity=maturity,
        pd_floor=float(CRR_PD_FLOOR) if apply_pd_floor_flag else 0.0,
        lgd_floor=None,  # CRR A-IRB has no LGD floors
        apply_maturity_adjustment=apply_maturity_adjustment,
        apply_scaling_factor=True,  # CRR applies 1.06 scaling for non-retail
    )


def calculate_irb_rwa_with_turnover(
    ead: float,
    pd: float,
    lgd: float,
    maturity: float = 2.5,
    exposure_class: str = "CORPORATE",
    turnover_m: float | None = None,
    apply_maturity_adjustment: bool = True,
    apply_pd_floor_flag: bool = True,
    turnover_currency: str = "EUR",
    eur_gbp_rate: float = 0.8732,
    apply_fi_scalar: bool = False,
) -> dict:
    """
    Calculate RWA using CRR IRB approach with automatic correlation calculation.

    This is a convenience function that calculates correlation internally,
    including the SME firm size adjustment for corporate exposures with turnover.

    Args:
        ead: Exposure at Default
        pd: Probability of default (raw)
        lgd: Loss given default
        maturity: Effective maturity in years
        exposure_class: Exposure class
        turnover_m: Annual turnover in millions (for SME adjustment)
        apply_maturity_adjustment: Whether to apply MA (False for retail)
        apply_pd_floor_flag: Whether to apply PD floor
        turnover_currency: Currency of turnover ("EUR" or "GBP")
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR

    Returns:
        Dictionary with calculation details including:
        - rwa: Risk-weighted assets
        - k: Capital requirement (K)
        - pd_floored: PD after floor applied
        - correlation: Asset correlation (with SME adjustment if applicable)
        - maturity_adjustment: Maturity adjustment factor
        - sme_adjustment_applied: Whether SME correlation adjustment was applied

    SME Firm Size Adjustment (CRR Art. 153(4)):
        For corporates with turnover < EUR 50m (GBP 44m):
        R_adjusted = R - 0.04 × (1 - (max(S, 5) - 5) / 45)
        where S = annual turnover in EUR millions

        This reduces correlation (and thus RWA) for smaller firms.

    Reference: CRR Art. 153-154
    """
    from workbooks.shared.correlation import calculate_correlation

    # Apply PD floor
    pd_floored = apply_pd_floor(pd) if apply_pd_floor_flag else pd

    # Calculate correlation with SME adjustment if applicable
    # The SME threshold is in EUR, so convert GBP turnover to EUR
    correlation = calculate_correlation(
        pd=pd_floored,
        exposure_class=exposure_class,
        turnover=turnover_m,
        sme_threshold=50.0,  # EUR 50m
        eur_gbp_rate=eur_gbp_rate,
        turnover_currency=turnover_currency,
        apply_fi_scalar=apply_fi_scalar,
    )

    # Track whether SME adjustment was applied
    # Convert turnover to EUR for threshold comparison
    turnover_eur = turnover_m
    if turnover_m is not None and turnover_currency.upper() == "GBP":
        turnover_eur = turnover_m / eur_gbp_rate

    sme_adjustment_applied = (
        turnover_eur is not None and
        turnover_eur < 50.0 and
        exposure_class.upper() in ["CORPORATE", "CORPORATE_SME", "CORPORATES"]
    )

    result = _base_calculate_irb_rwa(
        ead=ead,
        pd=pd,
        lgd=lgd,
        correlation=correlation,
        maturity=maturity,
        pd_floor=float(CRR_PD_FLOOR) if apply_pd_floor_flag else 0.0,
        lgd_floor=None,  # CRR A-IRB has no LGD floors
        apply_maturity_adjustment=apply_maturity_adjustment,
        apply_scaling_factor=True,  # CRR applies 1.06 scaling for non-retail
    )

    # Add SME adjustment info to result
    result["correlation"] = correlation
    result["sme_adjustment_applied"] = sme_adjustment_applied
    result["turnover_m"] = turnover_m

    return result


# Re-export for compatibility
__all__ = [
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_irb_rwa",
    "calculate_expected_loss",
    "apply_pd_floor",
    "get_firb_lgd",
]
