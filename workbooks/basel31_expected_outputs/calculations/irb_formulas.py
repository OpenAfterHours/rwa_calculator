"""
IRB (Internal Ratings-Based) formula calculations for Basel 3.1.

This module wraps the shared IRB formulas with Basel 3.1 specific defaults
(PD floors, LGD floors per PRA PS9/24 / CRE31-32).

For the core IRB formula (which is the same for CRR and Basel 3.1),
see workbooks/shared/irb_formulas.py.
"""

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
    apply_lgd_floor as _base_apply_lgd_floor,
)

# Import Basel 3.1 specific parameters
from workbooks.basel31_expected_outputs.data.regulatory_params import (
    PD_FLOORS,
    AIRB_LGD_FLOORS,
    MATURITY_FLOOR,
    MATURITY_CAP,
)


def apply_pd_floor(pd: float, exposure_class: str) -> float:
    """
    Apply Basel 3.1 PD floor based on exposure class.

    Args:
        pd: Raw probability of default
        exposure_class: Exposure class for floor lookup

    Returns:
        Floored PD

    Basel 3.1 PD Floors (CRE30.55, PRA PS9/24):
        - Corporate/Sovereign/Institution: 0.05%
        - Retail (non-QRRE): 0.05%
        - QRRE: 0.10%
    """
    floor = PD_FLOORS.get(exposure_class, PD_FLOORS.get("CORPORATE", 0.0005))
    return _base_apply_pd_floor(pd, floor)


def apply_lgd_floor(
    lgd: float,
    collateral_type: str = "unsecured",
    exposure_class: str = "CORPORATE",
) -> float:
    """
    Apply Basel 3.1 LGD floor for A-IRB approach.

    Args:
        lgd: Raw LGD estimate
        collateral_type: Type of collateral securing the exposure
        exposure_class: Exposure class

    Returns:
        Floored LGD

    Basel 3.1 A-IRB LGD Floors (CRE32.20):
        - Unsecured: 25%
        - Financial collateral: 0%
        - Receivables: 10%
        - Commercial/Residential RE: 10%/5%
        - Retail unsecured: 50%
        - Retail QRRE: 50%

    Note: CRR A-IRB has no LGD floors.
    """
    # Map exposure class to floor key
    if "RETAIL" in exposure_class:
        if "MORTGAGE" in exposure_class:
            floor_key = "retail_mortgage"
        elif "QRRE" in exposure_class:
            floor_key = "retail_qrre"
        else:
            floor_key = "retail_unsecured"
    else:
        floor_key = collateral_type

    floor = AIRB_LGD_FLOORS.get(floor_key, AIRB_LGD_FLOORS.get("unsecured", 0.25))
    return _base_apply_lgd_floor(lgd, floor)


def calculate_maturity_adjustment(
    pd: float,
    maturity: float,
    apply_adjustment: bool = True,
) -> float:
    """
    Calculate maturity adjustment factor for corporate/wholesale exposures.

    Uses Basel 3.1 maturity floor (1 year) and cap (5 years).

    Args:
        pd: Probability of default (floored)
        maturity: Effective maturity in years
        apply_adjustment: Whether to apply adjustment (False for retail)

    Returns:
        Maturity adjustment factor

    Reference: CRE31.7
    """
    return _base_calculate_maturity_adjustment(
        pd,
        maturity,
        apply_adjustment=apply_adjustment,
        maturity_floor=MATURITY_FLOOR,
        maturity_cap=MATURITY_CAP,
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
    Calculate RWA using Basel 3.1 IRB approach.

    Applies Basel 3.1 specific PD floors (differentiated by exposure class).

    Args:
        ead: Exposure at Default
        pd: Probability of default (raw)
        lgd: Loss given default
        correlation: Asset correlation
        maturity: Effective maturity in years
        exposure_class: Exposure class for floors
        apply_maturity_adjustment: Whether to apply MA (False for retail)
        apply_pd_floor_flag: Whether to apply PD floor

    Returns:
        Dictionary with calculation details

    Reference: CRE31.4, CRE31.7
    """
    # Get Basel 3.1 PD floor for this exposure class
    pd_floor = PD_FLOORS.get(exposure_class, PD_FLOORS.get("CORPORATE", 0.0005))

    is_retail = "RETAIL" in exposure_class

    return _base_calculate_irb_rwa(
        ead=ead,
        pd=pd,
        lgd=lgd,
        correlation=correlation,
        maturity=maturity,
        pd_floor=pd_floor if apply_pd_floor_flag else 0.0,
        lgd_floor=None,  # LGD floors only for A-IRB, handled separately
        apply_maturity_adjustment=apply_maturity_adjustment,
        is_retail=is_retail,
    )


# Re-export for compatibility
__all__ = [
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_irb_rwa",
    "calculate_expected_loss",
    "apply_pd_floor",
    "apply_lgd_floor",
]
