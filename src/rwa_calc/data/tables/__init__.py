"""
Regulatory lookup tables for RWA calculations.

This module provides static lookup tables as Polars DataFrames for efficient
joins in the calculation pipeline. Tables are defined per CRR (EU 575/2013)
as onshored into UK law, plus Basel 3.1 (PRA PS1/26) tables.

Modules:
    crr_risk_weights: SA risk weights by exposure class and CQS
    b31_risk_weights: Basel 3.1 LTV-band SA risk weights for real estate
    haircuts: CRM supervisory haircuts (CRR Art. 224 and PRA PS1/26 Art. 224)
    crr_slotting: CRR specialised lending slotting risk weights
    b31_slotting: Basel 3.1 specialised lending slotting risk weights
    firb_lgd: F-IRB PD/maturity floors and caps (CRR Art. 162/163)
    crr_equity_rw: CRR equity risk weights (Art. 133 SA, Art. 155 IRB Simple)
    b31_equity_rw: Basel 3.1 equity risk weights (PRA PS1/26 Art. 133)
    entity_class_mapping: entity_type → SA/IRB exposure class lookup
"""

from .b31_equity_rw import (
    B31_SA_EQUITY_RISK_WEIGHTS,
    get_b31_equity_risk_weights,
    get_b31_equity_rw_table,
    lookup_b31_equity_rw,
)
from .b31_risk_weights import (
    B31_ADC_PRESOLD_RISK_WEIGHT,
    B31_ADC_RISK_WEIGHT,
    B31_COMMERCIAL_GENERAL_MAX_SECURED_RATIO,
    B31_COMMERCIAL_GENERAL_SECURED_RW,
    B31_COMMERCIAL_INCOME_LTV_BANDS,
    B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO,
    B31_RESIDENTIAL_GENERAL_SECURED_RW,
    B31_RESIDENTIAL_INCOME_LTV_BANDS,
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
from .crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    COMMERCIAL_RE_PARAMS,
    CORPORATE_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
    RESIDENTIAL_MORTGAGE_PARAMS,
    RETAIL_RISK_WEIGHT,
    build_institution_guarantor_rw_expr,
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
from .entity_class_mapping import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
    ENTITY_TYPES_BY_SA_CLASS,
)
from .eu_sovereign import (
    EU_COUNTRY_DOMESTIC_CURRENCY,
    EU_MEMBER_STATES,
    build_eu_domestic_currency_expr,
)
from .haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    get_haircut_table,
)
from .re_split_parameters import (
    RE_SPLIT_PARAMS_B31_COMMERCIAL,
    RE_SPLIT_PARAMS_B31_RESIDENTIAL,
    RE_SPLIT_PARAMS_CRR_COMMERCIAL,
    RE_SPLIT_PARAMS_CRR_RESIDENTIAL,
    SplitParameters,
    re_split_parameters,
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
    "b31_residential_rw_expr",
    "b31_commercial_rw_expr",
    "b31_adc_rw_expr",
    "lookup_b31_residential_rw",
    "lookup_b31_commercial_rw",
    # CRR risk weights
    "CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS",
    "INSTITUTION_RISK_WEIGHTS_B31_ECRA",
    "INSTITUTION_RISK_WEIGHTS_CRR",
    "CORPORATE_RISK_WEIGHTS",
    "RESIDENTIAL_MORTGAGE_PARAMS",
    "COMMERCIAL_RE_PARAMS",
    "RETAIL_RISK_WEIGHT",
    "build_institution_guarantor_rw_expr",
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
    # EU sovereign treatment
    "EU_MEMBER_STATES",
    "EU_COUNTRY_DOMESTIC_CURRENCY",
    "build_eu_domestic_currency_expr",
    # Entity-type to exposure-class mappings
    "ENTITY_TYPE_TO_SA_CLASS",
    "ENTITY_TYPE_TO_IRB_CLASS",
    "ENTITY_TYPES_BY_SA_CLASS",
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
    # Real estate loan-splitting (CRR Art. 125/126, B3.1 Art. 124F/H)
    "SplitParameters",
    "re_split_parameters",
    "RE_SPLIT_PARAMS_CRR_RESIDENTIAL",
    "RE_SPLIT_PARAMS_CRR_COMMERCIAL",
    "RE_SPLIT_PARAMS_B31_RESIDENTIAL",
    "RE_SPLIT_PARAMS_B31_COMMERCIAL",
]
