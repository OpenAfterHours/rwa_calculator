"""
F-IRB PD and maturity floors/caps — CRR Art. 162/163.

Canonical home for the CRR IRB parameter bounds (PD floor, maturity floor and
cap) and the scalar IRB K factor, plus the small float helpers that apply them.
The supervisory-LGD tables and Art. 230 overcollateralisation parameters that
previously lived here have moved to the rulepack (``firb_supervisory_lgd``,
``overcollateralisation_ratios``, ``min_collateralisation_thresholds``); the
engine now reads those per-run via ``rulebook.resolve``.

Reference:
    CRR Art. 162: Maturity floor and cap for IRB
    CRR Art. 163: PD floor for IRB
    CRR Art. 153(1): IRB K scaling factor (1.06, removed under Basel 3.1)
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

# PD floor under CRR (single floor for all classes)
CRR_PD_FLOOR: Decimal = Decimal("0.0003")  # 0.03%

# Maturity parameters
CRR_MATURITY_FLOOR: Decimal = Decimal("1.0")  # 1 year minimum
CRR_MATURITY_CAP: Decimal = Decimal("5.0")  # 5 year maximum

# IRB K scaling factor (CRR Art. 153(1)). Removed under Basel 3.1 (set to 1.0).
# Used in CRR-vs-B31 attribution math to isolate the scaling-factor delta.
CRR_K_SCALING_FACTOR: Decimal = Decimal("1.06")


# =============================================================================
# IRB PARAMETER FLOORS AND CAPS
# =============================================================================


def get_irb_parameters_df() -> pl.DataFrame:
    """
    Get IRB parameter floors and caps as DataFrame.

    Returns:
        DataFrame with regulatory parameter bounds
    """
    return pl.DataFrame(
        {
            "parameter": ["pd_floor", "maturity_floor", "maturity_cap"],
            "value": [0.0003, 1.0, 5.0],
            "unit": ["decimal", "years", "years"],
            "description": [
                "Minimum PD (0.03%)",
                "Minimum effective maturity",
                "Maximum effective maturity",
            ],
            "regulatory_reference": [
                "CRR Art. 163",
                "CRR Art. 162",
                "CRR Art. 162",
            ],
        }
    ).with_columns(
        [
            pl.col("value").cast(pl.Float64),
        ]
    )


def apply_pd_floor(pd: Decimal | float) -> Decimal:
    """
    Apply PD floor.

    Args:
        pd: Probability of default

    Returns:
        Floored PD (minimum 0.03%)
    """
    pd_decimal = Decimal(str(pd)) if not isinstance(pd, Decimal) else pd
    return max(pd_decimal, CRR_PD_FLOOR)


def apply_maturity_bounds(maturity: Decimal | float) -> Decimal:
    """
    Apply maturity floor and cap.

    Args:
        maturity: Effective maturity in years

    Returns:
        Bounded maturity (1-5 years)
    """
    mat_decimal = Decimal(str(maturity)) if not isinstance(maturity, Decimal) else maturity
    return max(CRR_MATURITY_FLOOR, min(CRR_MATURITY_CAP, mat_decimal))
