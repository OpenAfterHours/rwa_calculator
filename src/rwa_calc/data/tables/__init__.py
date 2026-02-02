"""
CRR regulatory lookup tables for RWA calculations.

This module provides static lookup tables as Polars DataFrames for efficient
joins in the calculation pipeline. Tables are defined per CRR (EU 575/2013)
as onshored into UK law.

Modules:
    crr_risk_weights: SA risk weights by exposure class and CQS
    crr_haircuts: CRM supervisory haircuts
    crr_slotting: Specialised lending slotting risk weights
    crr_firb_lgd: F-IRB supervisory LGD values
    crr_equity_rw: Equity risk weights (Art. 133 SA, Art. 155 IRB Simple)
"""

from .crr_risk_weights import (
    SOVEREIGN_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_UK,
    INSTITUTION_RISK_WEIGHTS_STANDARD,
    CORPORATE_RISK_WEIGHTS,
    RESIDENTIAL_MORTGAGE_PARAMS,
    COMMERCIAL_RE_PARAMS,
    RETAIL_RISK_WEIGHT,
    get_all_risk_weight_tables,
)
from .crr_haircuts import (
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    get_haircut_table,
)
from .crr_slotting import (
    SLOTTING_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS_HVCRE,
    get_slotting_table,
)
from .crr_firb_lgd import (
    FIRB_SUPERVISORY_LGD,
    get_firb_lgd_table,
)
from .crr_equity_rw import (
    SA_EQUITY_RISK_WEIGHTS,
    IRB_SIMPLE_EQUITY_RISK_WEIGHTS,
    get_equity_risk_weights,
    lookup_equity_rw,
    get_equity_rw_table,
    get_combined_equity_rw_table,
)

__all__ = [
    # Risk weights
    "SOVEREIGN_RISK_WEIGHTS",
    "INSTITUTION_RISK_WEIGHTS_UK",
    "INSTITUTION_RISK_WEIGHTS_STANDARD",
    "CORPORATE_RISK_WEIGHTS",
    "RESIDENTIAL_MORTGAGE_PARAMS",
    "COMMERCIAL_RE_PARAMS",
    "RETAIL_RISK_WEIGHT",
    "get_all_risk_weight_tables",
    # Haircuts
    "COLLATERAL_HAIRCUTS",
    "FX_HAIRCUT",
    "get_haircut_table",
    # Slotting
    "SLOTTING_RISK_WEIGHTS",
    "SLOTTING_RISK_WEIGHTS_HVCRE",
    "get_slotting_table",
    # F-IRB LGD
    "FIRB_SUPERVISORY_LGD",
    "get_firb_lgd_table",
    # Equity risk weights
    "SA_EQUITY_RISK_WEIGHTS",
    "IRB_SIMPLE_EQUITY_RISK_WEIGHTS",
    "get_equity_risk_weights",
    "lookup_equity_rw",
    "get_equity_rw_table",
    "get_combined_equity_rw_table",
]
