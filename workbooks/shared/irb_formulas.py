"""
IRB (Internal Ratings-Based) formula calculations for workbooks.

This module re-exports the IRB formulas from the main rwa_calc package
to avoid code duplication. The core IRB formula (Basel II/III) is
the same for both CRR and Basel 3.1 - only the floors differ.

References:
- CRR Art. 153-154: IRB risk weight functions
- CRE31: Basel 3.1 IRB approach
"""

# Re-export from main module to avoid duplication
from rwa_calc.engine.irb.formulas import (
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
    # Also export scalar helper functions for workbook calculations
    _norm_cdf,
    _norm_ppf,
    # Export constants
    G_999,
    # Export correlation params for reference
    CORRELATION_PARAMS,
    CorrelationParams,
    get_correlation_params,
)

# Convenience functions for workbook use


def apply_pd_floor(pd: float, pd_floor: float = 0.0003) -> float:
    """
    Apply PD floor.

    Args:
        pd: Raw probability of default
        pd_floor: PD floor to apply (default 0.03% for CRR/Basel 3.1 corporate)

    Returns:
        Floored PD

    Note: PD floors differ between CRR and Basel 3.1 for retail classes.
    - CRR: 0.03% for all classes
    - Basel 3.1: 0.03% corporate, 0.05% retail, 0.10% QRRE
    """
    return max(pd, pd_floor)


def apply_lgd_floor(lgd: float, lgd_floor: float | None = None) -> float:
    """
    Apply LGD floor for A-IRB approach.

    Args:
        lgd: Raw LGD estimate
        lgd_floor: LGD floor to apply (None = no floor, as in CRR A-IRB)

    Returns:
        Floored LGD

    Note: LGD floors only apply under Basel 3.1 A-IRB, not CRR.
    """
    if lgd_floor is None:
        return lgd
    return max(lgd, lgd_floor)


def calculate_risk_weight_from_k(
    k: float,
    ma: float = 1.0,
    apply_scaling_factor: bool = False,
) -> float:
    """
    Convert capital K to equivalent risk weight.

    Args:
        k: Capital requirement
        ma: Maturity adjustment
        apply_scaling_factor: Whether to apply 1.06 scaling (CRR only)

    Returns:
        Equivalent risk weight (for comparison with SA)

    Formula:
        CRR:       RW = K × 12.5 × 1.06 × MA
        Basel 3.1: RW = K × 12.5 × MA
    """
    scaling_factor = 1.06 if apply_scaling_factor else 1.0
    return k * 12.5 * scaling_factor * ma


__all__ = [
    # Main functions
    "calculate_correlation",
    "calculate_expected_loss",
    "calculate_irb_rwa",
    "calculate_k",
    "calculate_maturity_adjustment",
    # Helper functions
    "apply_pd_floor",
    "apply_lgd_floor",
    "calculate_risk_weight_from_k",
    # Constants and params
    "G_999",
    "CORRELATION_PARAMS",
    "CorrelationParams",
    "get_correlation_params",
]
