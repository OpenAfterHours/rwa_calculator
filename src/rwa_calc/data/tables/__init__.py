"""
Regulatory lookup tables for RWA calculations.

This module provides static lookup tables as Polars DataFrames for efficient
joins in the calculation pipeline. Tables are defined per CRR (EU 575/2013)
as onshored into UK law, plus Basel 3.1 (PRA PS1/26) tables.

Modules:
    crr_risk_weights: SA risk weights by exposure class and CQS
    b31_risk_weights: Basel 3.1 LTV-band SA risk weights for real estate
    haircuts: CRM supervisory haircuts (CRR Art. 224 and PRA PS1/26 Art. 224)
    firb_lgd: F-IRB PD/maturity floors and caps (CRR Art. 162/163)
    entity_class_mapping: entity_type → SA/IRB exposure class lookup
"""

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
    # EU sovereign treatment
    "EU_MEMBER_STATES",
    "EU_COUNTRY_DOMESTIC_CURRENCY",
    "build_eu_domestic_currency_expr",
    # Entity-type to exposure-class mappings
    "ENTITY_TYPE_TO_SA_CLASS",
    "ENTITY_TYPE_TO_IRB_CLASS",
    "ENTITY_TYPES_BY_SA_CLASS",
]
