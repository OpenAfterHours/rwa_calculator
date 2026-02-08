"""Data loaders and Basel 3.1 regulatory parameters for RWA calculations.

This module contains Basel 3.1 specific parameters (PRA PS9/24).
For CRR (Basel 3.0) parameters, see workbooks/crr_expected_outputs/data/.
"""

from .regulatory_params import (
    # SA risk weights
    CGCB_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_UK,
    CORPORATE_RISK_WEIGHTS,
    RETAIL_RISK_WEIGHT,
    RESIDENTIAL_MORTGAGE_RISK_WEIGHTS,
    COMMERCIAL_RE_RISK_WEIGHTS,
    ADC_RISK_WEIGHT,
    ADC_PRESOLD_RISK_WEIGHT,
    # Slotting
    SLOTTING_RISK_WEIGHTS,
    HVCRE_MULTIPLIER,
    # IRB
    PD_FLOORS,
    FIRB_LGD,
    AIRB_LGD_FLOORS,
    CORRELATION_PARAMS,
    # CRM
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    CCF_VALUES,
    # Maturity
    MATURITY_FLOOR,
    MATURITY_CAP,
    # Basel 3.1 output floor
    OUTPUT_FLOOR_PERCENTAGE,
    OUTPUT_FLOOR_TRANSITIONAL,
)
from .fixture_loader import load_fixtures, load_fixtures_eager, FixtureData

__all__ = [
    # Fixture loading
    "load_fixtures",
    "load_fixtures_eager",
    "FixtureData",
    # SA risk weights
    "CGCB_RISK_WEIGHTS",
    "INSTITUTION_RISK_WEIGHTS",
    "INSTITUTION_RISK_WEIGHTS_UK",
    "CORPORATE_RISK_WEIGHTS",
    "RETAIL_RISK_WEIGHT",
    "RESIDENTIAL_MORTGAGE_RISK_WEIGHTS",
    "COMMERCIAL_RE_RISK_WEIGHTS",
    "ADC_RISK_WEIGHT",
    "ADC_PRESOLD_RISK_WEIGHT",
    # Slotting
    "SLOTTING_RISK_WEIGHTS",
    "HVCRE_MULTIPLIER",
    # IRB
    "PD_FLOORS",
    "FIRB_LGD",
    "AIRB_LGD_FLOORS",
    "CORRELATION_PARAMS",
    # CRM
    "COLLATERAL_HAIRCUTS",
    "FX_HAIRCUT",
    "CCF_VALUES",
    # Maturity
    "MATURITY_FLOOR",
    "MATURITY_CAP",
    # Basel 3.1 output floor
    "OUTPUT_FLOOR_PERCENTAGE",
    "OUTPUT_FLOOR_TRANSITIONAL",
]
