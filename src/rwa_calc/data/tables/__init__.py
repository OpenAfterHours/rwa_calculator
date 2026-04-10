"""
Regulatory lookup tables for RWA calculations.

This module provides static lookup tables as Polars DataFrames for efficient
joins in the calculation pipeline. Tables are defined per CRR (EU 575/2013)
as onshored into UK law, plus Basel 3.1 (PRA PS1/26) tables.

Modules:
    crr_risk_weights: SA risk weights by exposure class and CQS
    b31_risk_weights: Basel 3.1 LTV-band SA risk weights for real estate
    crr_haircuts: CRM supervisory haircuts
    crr_slotting: CRR specialised lending slotting risk weights
    b31_slotting: Basel 3.1 specialised lending slotting risk weights
    crr_firb_lgd: F-IRB supervisory LGD values (CRR)
    b31_firb_lgd: F-IRB supervisory LGD values (Basel 3.1)
    crr_equity_rw: CRR equity risk weights (Art. 133 SA, Art. 155 IRB Simple)
    b31_equity_rw: Basel 3.1 equity risk weights (PRA PS1/26 Art. 133)
"""

from .b31_equity_rw import (
    B31_SA_EQUITY_RISK_WEIGHTS,
    get_b31_equity_risk_weights,
    get_b31_equity_rw_table,
    lookup_b31_equity_rw,
)
from .b31_firb_lgd import (
    B31_FIRB_LGD_COMMERCIAL_RE,
    B31_FIRB_LGD_COVERED_BOND,
    B31_FIRB_LGD_FINANCIAL_COLLATERAL,
    B31_FIRB_LGD_OTHER_PHYSICAL,
    B31_FIRB_LGD_RECEIVABLES,
    B31_FIRB_LGD_RESIDENTIAL_RE,
    B31_FIRB_LGD_SUBORDINATED,
    B31_FIRB_LGD_UNSECURED_SENIOR,
    B31_FIRB_LGD_UNSECURED_SENIOR_FSE,
    get_b31_firb_lgd_table,
    get_b31_vs_crr_lgd_comparison,
    lookup_b31_firb_lgd,
)
from .b31_risk_weights import (
    B31_ADC_PRESOLD_RISK_WEIGHT,
    B31_ADC_RISK_WEIGHT,
    B31_COMMERCIAL_GENERAL_MAX_SECURED_RATIO,
    B31_COMMERCIAL_GENERAL_SECURED_RW,
    B31_COMMERCIAL_INCOME_LTV_BANDS,
    B31_LARGE_CORPORATE_REVENUE_THRESHOLD_GBP,
    B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO,
    B31_RESIDENTIAL_GENERAL_SECURED_RW,
    B31_RESIDENTIAL_INCOME_LTV_BANDS,
    B31_SME_TURNOVER_THRESHOLD_GBP,
    b31_adc_rw_expr,
    b31_commercial_rw_expr,
    b31_residential_rw_expr,
    lookup_b31_commercial_rw,
    lookup_b31_residential_rw,
)
from .b31_slotting import (
    B31_SLOTTING_RISK_WEIGHTS,
    B31_SLOTTING_RISK_WEIGHTS_HVCRE,
    B31_SLOTTING_RISK_WEIGHTS_PREOP,
    lookup_b31_slotting_rw,
)
from .crr_equity_rw import (
    IRB_SIMPLE_EQUITY_RISK_WEIGHTS,
    SA_EQUITY_RISK_WEIGHTS,
    get_combined_equity_rw_table,
    get_equity_risk_weights,
    get_equity_rw_table,
    lookup_equity_rw,
)
from .crr_firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_SUPERVISORY_LGD,
    get_firb_lgd_table,
    get_firb_lgd_table_for_framework,
)
from .crr_haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    get_haircut_table,
)
from .crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    COMMERCIAL_RE_PARAMS,
    CORPORATE_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_STANDARD,
    INSTITUTION_RISK_WEIGHTS_UK,
    RESIDENTIAL_MORTGAGE_PARAMS,
    RETAIL_RISK_WEIGHT,
    get_all_risk_weight_tables,
)
from .crr_slotting import (
    SLOTTING_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS_HVCRE,
    SLOTTING_RISK_WEIGHTS_HVCRE_SHORT,
    SLOTTING_RISK_WEIGHTS_SHORT,
    calculate_slotting_rwa,
    lookup_slotting_rw,
)
from .eu_sovereign import (
    EU_COUNTRY_DOMESTIC_CURRENCY,
    EU_MEMBER_STATES,
    build_eu_domestic_currency_expr,
)

__all__ = [
    # Basel 3.1 risk weights
    "B31_RESIDENTIAL_GENERAL_SECURED_RW",
    "B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO",
    "B31_RESIDENTIAL_INCOME_LTV_BANDS",
    "B31_COMMERCIAL_INCOME_LTV_BANDS",
    "B31_COMMERCIAL_GENERAL_SECURED_RW",
    "B31_COMMERCIAL_GENERAL_MAX_SECURED_RATIO",
    "B31_ADC_RISK_WEIGHT",
    "B31_ADC_PRESOLD_RISK_WEIGHT",
    "B31_LARGE_CORPORATE_REVENUE_THRESHOLD_GBP",
    "B31_SME_TURNOVER_THRESHOLD_GBP",
    "b31_residential_rw_expr",
    "b31_commercial_rw_expr",
    "b31_adc_rw_expr",
    "lookup_b31_residential_rw",
    "lookup_b31_commercial_rw",
    # CRR risk weights
    "CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS",
    "INSTITUTION_RISK_WEIGHTS_UK",
    "INSTITUTION_RISK_WEIGHTS_STANDARD",
    "CORPORATE_RISK_WEIGHTS",
    "RESIDENTIAL_MORTGAGE_PARAMS",
    "COMMERCIAL_RE_PARAMS",
    "RETAIL_RISK_WEIGHT",
    "get_all_risk_weight_tables",
    # Haircuts
    "COLLATERAL_HAIRCUTS",
    "BASEL31_COLLATERAL_HAIRCUTS",
    "FX_HAIRCUT",
    "get_haircut_table",
    # Slotting — CRR
    "SLOTTING_RISK_WEIGHTS",
    "SLOTTING_RISK_WEIGHTS_SHORT",
    "SLOTTING_RISK_WEIGHTS_HVCRE",
    "SLOTTING_RISK_WEIGHTS_HVCRE_SHORT",
    "lookup_slotting_rw",
    "calculate_slotting_rwa",
    # Slotting — Basel 3.1
    "B31_SLOTTING_RISK_WEIGHTS",
    "B31_SLOTTING_RISK_WEIGHTS_PREOP",
    "B31_SLOTTING_RISK_WEIGHTS_HVCRE",
    "lookup_b31_slotting_rw",
    # F-IRB LGD — CRR
    "FIRB_SUPERVISORY_LGD",
    "BASEL31_FIRB_SUPERVISORY_LGD",
    "get_firb_lgd_table",
    "get_firb_lgd_table_for_framework",
    # F-IRB LGD — Basel 3.1
    "B31_FIRB_LGD_UNSECURED_SENIOR",
    "B31_FIRB_LGD_UNSECURED_SENIOR_FSE",
    "B31_FIRB_LGD_SUBORDINATED",
    "B31_FIRB_LGD_COVERED_BOND",
    "B31_FIRB_LGD_FINANCIAL_COLLATERAL",
    "B31_FIRB_LGD_RECEIVABLES",
    "B31_FIRB_LGD_RESIDENTIAL_RE",
    "B31_FIRB_LGD_COMMERCIAL_RE",
    "B31_FIRB_LGD_OTHER_PHYSICAL",
    "get_b31_firb_lgd_table",
    "lookup_b31_firb_lgd",
    "get_b31_vs_crr_lgd_comparison",
    # EU sovereign treatment
    "EU_MEMBER_STATES",
    "EU_COUNTRY_DOMESTIC_CURRENCY",
    "build_eu_domestic_currency_expr",
    # Equity risk weights — CRR
    "SA_EQUITY_RISK_WEIGHTS",
    "IRB_SIMPLE_EQUITY_RISK_WEIGHTS",
    "get_equity_risk_weights",
    "lookup_equity_rw",
    "get_equity_rw_table",
    "get_combined_equity_rw_table",
    # Equity risk weights — Basel 3.1
    "B31_SA_EQUITY_RISK_WEIGHTS",
    "get_b31_equity_risk_weights",
    "lookup_b31_equity_rw",
    "get_b31_equity_rw_table",
]
