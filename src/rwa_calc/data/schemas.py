"""
This module contains all the schemas for all data inputs for the rwa_calc.

Supports both UK CRR (Basel 3.0, until Dec 2026) and PRA PS1/26 (Basel 3.1, from Jan 2027).

Also defines COLUMN_VALUE_CONSTRAINTS — valid value sets for categorical columns,
used by validate_bundle_values to catch invalid input values early.

Key Data Inputs:
- Loan                      # Drawn exposures (leaf nodes in exposure hierarchy)
- Facility                  # Committed credit limits (parent nodes) with seniority, risk_type
- Contingents               # Off-balance sheet commitments with CCF category
- Counterparty              # Borrower/obligor with entity flags (PSE, MDB, institution, etc.)
- Collateral                # Security items with RE-specific fields (LTV, property type, ADC)
- Guarantee                 # Guarantees and credit protection
- Provision                 # IFRS 9 provisions/impairments (SCRA, GCRA)
- Ratings                   # Internal and external credit ratings
- Specialised_lending       # Slotting approach for PF, OF, CF, IPRE (CRE33)
- Equity_exposure           # Equity holdings - SA only under Basel 3.1 (CRE20.58-62)

Mappings:
- Facility_mappings         # Mappings between Facilities, Loans and Contingents
- Org_mapping               # Mapping between counterparties (parents to children) for rating/turnover inheritance
- Lending_mapping           # Mapping between connected counterparties for Retail threshold aggregation
- Ratings_mapping           # Mapping between Internal and External Ratings to Counterparties
- Collateral_mapping        # Mapping between Collateral and Exposures/Counterparties
- Provision_mapping         # Mapping between Provision and Exposures/Counterparties
- Guarantee_mapping         # Mapping between Guarantee and Exposures/Counterparties
- Exposure_class_mapping    # Mapping of counterparty/exposure attributes to SA/IRB exposure classes

Reference/Lookup Data:
- Central_govt_central_bank_risk_weights  # CQS to risk weight mapping for central govts/central banks (0%-150%)
- Institution_risk_weights  # CQS to risk weight mapping (ECRA) with UK CQS2=30% deviation
- Corporate_risk_weights    # CQS to risk weight mapping for corporates
- Mortgage_risk_weights     # LTV band to risk weight mapping (residential: 20%-70%)
- Collateral_haircuts       # Supervisory haircuts by collateral type
- CCF_table                 # Credit Conversion Factors by product/commitment type
- FIRB_LGD_table            # Supervisory LGD values by collateral type (0%-75%)
- AIRB_LGD_floors           # LGD floors by collateral type (0%-25%)
- PD_floors                 # PD floors by exposure class (Corporate 0.03%, Retail 0.05%, QRRE 0.10%)
- Correlation_parameters    # Asset correlation formulas/values by exposure class

Configuration:
- IRB_permissions           # Which exposure classes can use IRB (SA/FIRB/AIRB)
- Calculation_config        # Basel version toggle (3.0 vs 3.1), reporting date

Output Schemas:
- Calculation_output        # Full RWA calculation results with complete audit trail
                            # Includes: classification, EAD breakdown, CRM impact, risk weights,
                            # IRB parameters, hierarchy tracing, floor impact, and data quality flags

"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec

FACILITY_SCHEMA: dict[str, ColumnSpec] = {
    "facility_reference": ColumnSpec(pl.String),
    "product_type": ColumnSpec(pl.String, required=False),
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "counterparty_reference": ColumnSpec(pl.String),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "limit": ColumnSpec(pl.Float64, required=False),
    "committed": ColumnSpec(pl.Boolean, default=False, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "is_revolving": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qrre_transactor": ColumnSpec(pl.Boolean, default=False, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "risk_type": ColumnSpec(pl.String, required=False),
    "underlying_risk_type": ColumnSpec(pl.String, required=False),
    "ccf_modelled": ColumnSpec(pl.Float64, required=False),
    "ead_modelled": ColumnSpec(pl.Float64, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_buy_to_let": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "facility_termination_date": ColumnSpec(pl.Date, required=False),
    # Art. 162(3) / PS1/26: explicit numeric M override (years). When populated it
    # supersedes the maturity_date-derived M and bypasses the 1-year floor —
    # firm-owned judgement for short-term carve-outs.
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
}

LOAN_SCHEMA: dict[str, ColumnSpec] = {
    "loan_reference": ColumnSpec(pl.String),
    "product_type": ColumnSpec(pl.String, required=False),
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "counterparty_reference": ColumnSpec(pl.String),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "drawn_amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "interest": ColumnSpec(pl.Float64, default=0.0, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_buy_to_let": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
    "has_netting_agreement": ColumnSpec(pl.Boolean, default=False, required=False),
    "netting_facility_reference": ColumnSpec(pl.String, required=False),
    "due_diligence_performed": ColumnSpec(pl.Boolean, default=False, required=False),
    "due_diligence_override_rw": ColumnSpec(pl.Float64, required=False),
    # Note: CCF fields (risk_type, ccf_modelled, is_short_term_trade_lc) are NOT included
    # because CCF only applies to off-balance sheet items (undrawn commitments, contingents).
    # Drawn loans are already on-balance sheet, so EAD = drawn_amount + interest directly.
}

CONTINGENTS_SCHEMA: dict[str, ColumnSpec] = {
    "contingent_reference": ColumnSpec(pl.String),
    "product_type": ColumnSpec(pl.String, required=False),
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "counterparty_reference": ColumnSpec(pl.String),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "nominal_amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "risk_type": ColumnSpec(pl.String, required=False),
    "underlying_risk_type": ColumnSpec(pl.String, required=False),
    "ccf_modelled": ColumnSpec(pl.Float64, required=False),
    "ead_modelled": ColumnSpec(pl.Float64, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
    "bs_type": ColumnSpec(pl.String, default="OFB", required=False),
    "due_diligence_performed": ColumnSpec(pl.Boolean, default=False, required=False),
    "due_diligence_override_rw": ColumnSpec(pl.Float64, required=False),
}

COUNTERPARTY_SCHEMA: dict[str, ColumnSpec] = {
    "counterparty_reference": ColumnSpec(pl.String),
    "counterparty_name": ColumnSpec(pl.String, required=False),
    # entity_type: Single source of truth for exposure class determination.
    # Maps directly to SA and IRB exposure classes. Valid values:
    #   Central govt/central bank class:
    #     - "sovereign"           → SA: CENTRAL_GOVT_CENTRAL_BANK, IRB: CENTRAL_GOVT_CENTRAL_BANK
    #     - "central_bank"        → SA: CENTRAL_GOVT_CENTRAL_BANK, IRB: CENTRAL_GOVT_CENTRAL_BANK
    #   RGLA class (CRR Art. 115) - requires explicit IRB treatment:
    #     - "rgla_sovereign"      → SA: RGLA, IRB: CENTRAL_GOVT_CENTRAL_BANK (has taxing powers/govt guarantee)
    #     - "rgla_institution"    → SA: RGLA, IRB: INSTITUTION (no sovereign equivalence)
    #   PSE class (CRR Art. 116) - requires explicit IRB treatment:
    #     - "pse_sovereign"       → SA: PSE, IRB: CENTRAL_GOVT_CENTRAL_BANK (govt guaranteed)
    #     - "pse_institution"     → SA: PSE, IRB: INSTITUTION (commercial PSE)
    #   MDB/International org class (CRR Art. 117-118):
    #     - "mdb"                 → SA: MDB (0% RW), IRB: CENTRAL_GOVT_CENTRAL_BANK
    #     - "international_org"   → SA: MDB (0% RW), IRB: CENTRAL_GOVT_CENTRAL_BANK
    #   Institution class (CRR Art. 112(d)):
    #     - "institution"         → SA: INSTITUTION, IRB: INSTITUTION
    #     - "bank"                → SA: INSTITUTION, IRB: INSTITUTION
    #     - "ccp"                 → SA: INSTITUTION, IRB: INSTITUTION (CCP treatment Art. 300-311)
    #     - "financial_institution" → SA: INSTITUTION, IRB: INSTITUTION
    #   Corporate class (CRR Art. 112(g)):
    #     - "corporate"           → SA: CORPORATE, IRB: CORPORATE
    #     - "company"             → SA: CORPORATE, IRB: CORPORATE
    #   Retail class (CRR Art. 112(h)):
    #     - "individual"          → SA: RETAIL_OTHER, IRB: RETAIL_OTHER
    #     - "retail"              → SA: RETAIL_OTHER, IRB: RETAIL_OTHER
    #   Specialised lending (CRR Art. 112(1)(g) / Art. 147(8)):
    #     - "specialised_lending" → SA: CORPORATE (sub-type), IRB: SPECIALISED_LENDING
    #   Other items class (CRR Art. 112(q), Art. 134):
    #     - "other_cash"              → SA: OTHER, 0% RW (Art. 134(1))
    #     - "other_gold"              → SA: OTHER, 0% RW (Art. 134(4))
    #     - "other_items_in_collection" → SA: OTHER, 20% RW (Art. 134(3))
    #     - "other_tangible"          → SA: OTHER, 100% RW (Art. 134(2))
    #     - "other_residual_lease"    → SA: OTHER, 1/t × 100% RW (Art. 134(6))
    "entity_type": ColumnSpec(pl.String),
    "country_code": ColumnSpec(pl.String, required=False),
    "annual_revenue": ColumnSpec(pl.Float64, required=False),
    "total_assets": ColumnSpec(pl.Float64, required=False),
    "default_status": ColumnSpec(pl.Boolean, default=False, required=False),
    "sector_code": ColumnSpec(pl.String, required=False),
    "apply_fi_scalar": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_managed_as_retail": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_natural_person": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_social_housing": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_financial_sector_entity": ColumnSpec(pl.Boolean, default=False, required=False),
    "scra_grade": ColumnSpec(pl.String, required=False),
    "is_investment_grade": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_ccp_client_cleared": ColumnSpec(pl.Boolean, required=False),
    "borrower_income_currency": ColumnSpec(pl.String, required=False),
    "sovereign_cqs": ColumnSpec(pl.Int32, required=False),
    "local_currency": ColumnSpec(pl.String, required=False),
    "institution_cqs": ColumnSpec(pl.Int8, required=False),
}

COLLATERAL_SCHEMA: dict[str, ColumnSpec] = {
    "collateral_reference": ColumnSpec(pl.String),
    "collateral_type": ColumnSpec(pl.String),
    "currency": ColumnSpec(pl.String, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "market_value": ColumnSpec(pl.Float64, required=False),
    "nominal_value": ColumnSpec(pl.Float64, required=False),
    "pledge_percentage": ColumnSpec(pl.Float64, required=False),
    "beneficiary_type": ColumnSpec(pl.String),
    "beneficiary_reference": ColumnSpec(pl.String),
    "issuer_cqs": ColumnSpec(pl.Int8, required=False),
    "issuer_type": ColumnSpec(pl.String, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    "is_eligible_financial_collateral": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_eligible_irb_collateral": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 181 / CRE36 / Basel 3.1 Art. 169A: AIRB own LGD already reflects
    # the collateral effect, so collateral incorporated into the firm's internal
    # LGD model must not contribute CRM benefit to non-AIRB exposures of the
    # same counterparty (otherwise double-counted). When True, the row is
    # routed only to AIRB exposures whose modelled LGD is preserved.
    "is_airb_model_collateral": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_main_index": ColumnSpec(pl.Boolean, default=False, required=False),
    "valuation_date": ColumnSpec(pl.Date, required=False),
    "valuation_type": ColumnSpec(pl.String, required=False),
    "property_type": ColumnSpec(pl.String, required=False),
    "property_ltv": ColumnSpec(pl.Float64, required=False),
    "is_income_producing": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_adc": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_presold": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qualifying_re": ColumnSpec(pl.Boolean, required=False),
    "prior_charge_ltv": ColumnSpec(pl.Float64, default=0.0, required=False),
    # CRR Art. 126(2)(d): rental income / interest payments ratio (>= 1.5
    # required to qualify CRE for the 50% preferential RW). Optional; if
    # absent, CRE collateral is conservatively treated as failing the test
    # under CRR and the loan-splitter leaves the exposure in its original
    # corporate / retail class. Not used under Basel 3.1.
    "rental_to_interest_ratio": ColumnSpec(pl.Float64, required=False),
    "liquidation_period_days": ColumnSpec(pl.Int32, required=False),
    "qualifies_for_zero_haircut": ColumnSpec(pl.Boolean, default=False, required=False),
    "insurer_risk_weight": ColumnSpec(pl.Float64, required=False),
    "credit_event_reduction": ColumnSpec(pl.Float64, default=0.0, required=False),
}

GUARANTEE_SCHEMA: dict[str, ColumnSpec] = {
    "guarantee_reference": ColumnSpec(pl.String),
    "guarantee_type": ColumnSpec(pl.String, required=False),
    "guarantor": ColumnSpec(pl.String),
    "currency": ColumnSpec(pl.String, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "amount_covered": ColumnSpec(pl.Float64, required=False),
    "percentage_covered": ColumnSpec(pl.Float64, required=False),
    "beneficiary_type": ColumnSpec(pl.String),
    "beneficiary_reference": ColumnSpec(pl.String),
    "protection_type": ColumnSpec(pl.String, default="guarantee", required=False),
    "includes_restructuring": ColumnSpec(pl.Boolean, default=False, required=False),
}

PROVISION_SCHEMA: dict[str, ColumnSpec] = {
    "provision_reference": ColumnSpec(pl.String),
    "provision_type": ColumnSpec(pl.String, required=False),
    "ifrs9_stage": ColumnSpec(pl.Int8, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "as_of_date": ColumnSpec(pl.Date, required=False),
    "beneficiary_type": ColumnSpec(pl.String),
    "beneficiary_reference": ColumnSpec(pl.String),
}

RATINGS_SCHEMA: dict[str, ColumnSpec] = {
    "rating_reference": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String),
    "rating_type": ColumnSpec(pl.String),
    "rating_agency": ColumnSpec(pl.String, required=False),
    "rating_value": ColumnSpec(pl.String, required=False),
    "cqs": ColumnSpec(pl.Int8, required=False),
    "pd": ColumnSpec(pl.Float64, required=False),
    "rating_date": ColumnSpec(pl.Date, required=False),
    "is_solicited": ColumnSpec(pl.Boolean, default=True, required=False),
    "model_id": ColumnSpec(pl.String, required=False),
}

# Specialised Lending exposures - slotting approach (CRE33.1-8, PS1/26 Ch.5)
# These are corporate exposures with specific risk characteristics requiring separate treatment
SPECIALISED_LENDING_SCHEMA: dict[str, ColumnSpec] = {
    "counterparty_reference": ColumnSpec(pl.String),
    "sl_type": ColumnSpec(pl.String),
    "project_phase": ColumnSpec(pl.String, required=False),
    "slotting_category": ColumnSpec(pl.String, required=False),
    "is_hvcre": ColumnSpec(pl.Boolean, default=False, required=False),
    # Supervisory risk weights by category (CRE33.5):
    # strong: 70% (50% if <2.5yr), good: 90% (70% if <2.5yr),
    # satisfactory: 115%, weak: 250%, default: 0%
}

# Equity exposures - must use SA under Basel 3.1 (CRE20.58-62, CRR Art 133)
# IRB approaches for equity withdrawn under PRA PS1/26
EQUITY_EXPOSURE_SCHEMA: dict[str, ColumnSpec] = {
    "exposure_reference": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String),
    "equity_type": ColumnSpec(pl.String, default="other", required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "carrying_value": ColumnSpec(pl.Float64, required=False),
    "fair_value": ColumnSpec(pl.Float64, required=False),
    "is_speculative": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_exchange_traded": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_government_supported": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_significant_investment": ColumnSpec(pl.Boolean, default=False, required=False),
    "ciu_approach": ColumnSpec(pl.String, required=False),
    "ciu_mandate_rw": ColumnSpec(pl.Float64, required=False),
    "ciu_third_party_calc": ColumnSpec(pl.Boolean, default=False, required=False),
    "fund_reference": ColumnSpec(pl.String, required=False),
    "fund_nav": ColumnSpec(pl.Float64, required=False),
    # Risk weight: 100% (listed), 250% (unlisted), 400% (speculative)
}

# CIU fund holdings for look-through approach (Art. 132)
CIU_HOLDINGS_SCHEMA: dict[str, ColumnSpec] = {
    "fund_reference": ColumnSpec(pl.String),
    "holding_reference": ColumnSpec(pl.String),
    "exposure_class": ColumnSpec(pl.String),
    "cqs": ColumnSpec(pl.Int8, required=False),
    "holding_value": ColumnSpec(pl.Float64, required=False),
}


# =============================================================================
# FX RATES SCHEMA
# =============================================================================

FX_RATES_SCHEMA: dict[str, ColumnSpec] = {
    "currency_from": ColumnSpec(pl.String),
    "currency_to": ColumnSpec(pl.String),
    "rate": ColumnSpec(pl.Float64),
}


# =============================================================================
# MAPPING SCHEMAS
# =============================================================================

FACILITY_MAPPING_SCHEMA: dict[str, ColumnSpec] = {
    "parent_facility_reference": ColumnSpec(pl.String),
    "child_reference": ColumnSpec(pl.String),
    "child_type": ColumnSpec(pl.String, required=False),
}

ORG_MAPPING_SCHEMA: dict[str, ColumnSpec] = {
    "parent_counterparty_reference": ColumnSpec(pl.String),
    "child_counterparty_reference": ColumnSpec(pl.String),
}

LENDING_MAPPING_SCHEMA: dict[str, ColumnSpec] = {
    "parent_counterparty_reference": ColumnSpec(pl.String),
    "child_counterparty_reference": ColumnSpec(pl.String),
}

EXPOSURE_CLASS_MAPPING_SCHEMA = {
    "exposure_class_code": pl.String,
    "exposure_class_name": pl.String,
    "is_sa_class": pl.Boolean,  # Valid for Standardised Approach
    "is_irb_class": pl.Boolean,  # Valid for IRB Approach
    "parent_class_code": pl.String,  # For sub-classifications
}


# =============================================================================
# REFERENCE / LOOKUP DATA SCHEMAS
# =============================================================================

CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHT_SCHEMA = {
    "cqs": pl.Int8,  # 1-6, 0 for unrated
    "risk_weight": pl.Float64,  # 0%, 20%, 50%, 100%, 150%
}

INSTITUTION_RISK_WEIGHT_SCHEMA = {
    "cqs": pl.Int8,  # 1-6, 0 for unrated
    "risk_weight": pl.Float64,  # 20%, 30% (UK), 50%, 100%, 150%
    "short_term_risk_weight": pl.Float64,  # For exposures <= 3 months
}

CORPORATE_RISK_WEIGHT_SCHEMA = {
    "cqs": pl.Int8,  # 1-6, 0 for unrated
    "risk_weight": pl.Float64,
}

MORTGAGE_RISK_WEIGHT_SCHEMA = {
    "ltv_lower": pl.Float64,  # Lower bound of LTV band
    "ltv_upper": pl.Float64,  # Upper bound of LTV band
    "risk_weight": pl.Float64,  # 20%, 25%, 30%, 35%, 40%, 50%, 70%
    "property_type": pl.String,  # residential, commercial
}

COLLATERAL_HAIRCUT_SCHEMA = {
    "collateral_type": pl.String,  # cash, gold, equity, bond, etc.
    "issuer_type": pl.String,  # sovereign, corporate, etc.
    "residual_maturity_lower": pl.Float64,  # In years
    "residual_maturity_upper": pl.Float64,
    "cqs": pl.Int8,  # For rated securities
    "haircut": pl.Float64,  # Supervisory haircut percentage
    "fx_haircut": pl.Float64,  # Additional FX mismatch haircut (8%)
}

CCF_SCHEMA = {
    "commitment_type": pl.String,  # Unconditionally cancellable, other commitments, etc.
    "product_category": pl.String,
    "ccf": pl.Float64,  # Credit Conversion Factor (0%, 20%, 40%, 50%, 100%)
    "basel_version": pl.String,  # 3.0, 3.1
}

FIRB_LGD_SCHEMA = {
    "collateral_type": pl.String,  # financial, receivables, commercial_re, residential_re, other_physical, unsecured
    "seniority": pl.String,  # senior, subordinated
    "lgd": pl.Float64,  # 0%, 35%, 40%, 45%, 75%
}

AIRB_LGD_FLOOR_SCHEMA = {
    "collateral_type": pl.String,
    "seniority": pl.String,
    "lgd_floor": pl.Float64,  # 0%, 5%, 10%, 15%, 25%
}

PD_FLOOR_SCHEMA = {
    "exposure_class": pl.String,  # corporate, retail, qrre, etc.
    "pd_floor": pl.Float64,  # 0.03%, 0.05%, 0.10%
}

CORRELATION_PARAMETER_SCHEMA = {
    "exposure_class": pl.String,
    "correlation_type": pl.String,  # fixed, pd_dependent
    "r_min": pl.Float64,  # Minimum correlation
    "r_max": pl.Float64,  # Maximum correlation
    "fixed_correlation": pl.Float64,  # For fixed types (e.g., mortgage 15%, QRRE 4%)
    "decay_factor": pl.Float64,  # For PD-dependent formula (50 for corp, 35 for retail)
}


# =============================================================================
# COLUMN VALUE CONSTRAINTS
# =============================================================================
# MODEL PERMISSIONS SCHEMA
# =============================================================================

MODEL_PERMISSIONS_SCHEMA: dict[str, ColumnSpec] = {
    "model_id": ColumnSpec(pl.String),
    "exposure_class": ColumnSpec(pl.String),
    "approach": ColumnSpec(pl.String),
    # country_codes / excluded_book_codes absent → null (all geographies / no exclusions)
    "country_codes": ColumnSpec(pl.String, required=False),
    "excluded_book_codes": ColumnSpec(pl.String, required=False),
}


# =============================================================================
# Valid value sets for categorical input columns.
# Used by validate_bundle_values() to catch invalid values at input time.

VALID_ENTITY_TYPES = {
    "sovereign",
    "central_bank",
    "rgla_sovereign",
    "rgla_institution",
    "pse_sovereign",
    "pse_institution",
    "mdb",
    "mdb_named",
    "international_org",
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "corporate",
    "company",
    "individual",
    "retail",
    "specialised_lending",
    "equity",
    "covered_bond",
    "other_cash",
    "other_gold",
    "other_items_in_collection",
    "other_tangible",
    "other_residual_lease",
    "high_risk",
    "high_risk_venture_capital",
    "high_risk_private_equity",
    "high_risk_speculative_re",
}

VALID_SENIORITY = {"senior", "subordinated"}

VALID_COLLATERAL_TYPES = {
    "cash",
    "gold",
    "equity",
    "bond",
    "real_estate",
    "receivables",
    "other_physical",
    "life_insurance",
    "credit_linked_note",
}

# =============================================================================
# Engine-side collateral classification (CRM)
# =============================================================================
# These lists capture every collateral_type string the CRM engine recognises,
# grouped by the regulatory category it maps to. They are broader than
# VALID_COLLATERAL_TYPES because the engine accepts synonyms (e.g. "rre" /
# "residential_property" for residential real estate, "govt_bond" / "gilt" for
# sovereign debt). VALID_COLLATERAL_TYPES is the canonical input set used by
# validate_bundle_values; these engine lists drive Polars expression builders
# in engine/crm/expressions.py for category-based dispatch.
#
# References: CRR Art. 161 / 230, CRE22.40-78

FINANCIAL_COLLATERAL_TYPES: list[str] = [
    "cash",
    "deposit",
    "gold",
    "financial_collateral",
    "government_bond",
    "corporate_bond",
    "equity",
    "credit_linked_note",
]

RECEIVABLE_COLLATERAL_TYPES: list[str] = ["receivables", "trade_receivables"]

REAL_ESTATE_COLLATERAL_TYPES: list[str] = [
    "real_estate",
    "property",
    "rre",
    "cre",
    "residential_re",
    "commercial_re",
    "residential",
    "commercial",
    "residential_property",
    "commercial_property",
]

OTHER_PHYSICAL_COLLATERAL_TYPES: list[str] = [
    "other_physical",
    "equipment",
    "inventory",
    "other",
]

COVERED_BOND_COLLATERAL_TYPES: list[str] = ["covered_bond", "covered_bonds"]

LIFE_INSURANCE_COLLATERAL_TYPES: list[str] = ["life_insurance"]

CREDIT_LINKED_NOTE_COLLATERAL_TYPES: list[str] = ["credit_linked_note"]

# Art. 227(2)(a): collateral types eligible for zero-haircut treatment in repos.
# Both the exposure and collateral must be cash or 0%-RW sovereign debt securities.
ZERO_HAIRCUT_ELIGIBLE_TYPES: list[str] = [
    "cash",
    "deposit",
    "govt_bond",
    "sovereign_bond",
    "government_bond",
    "gilt",
]

# Subset of real estate types that are NOT eligible financial collateral
# (used for SA EAD reduction eligibility check).
NON_ELIGIBLE_RE_TYPES: list[str] = [
    "real_estate",
    "property",
    "rre",
    "cre",
    "residential_property",
    "commercial_property",
]

# Beneficiary types treated as direct attachment to a single exposure
# (vs. facility-level or counterparty-level pro-rata allocation).
DIRECT_BENEFICIARY_TYPES: list[str] = ["exposure", "loan", "contingent"]

# Canonical mapping from accepted collateral_type string to its CRM category.
# Single source of truth for engine-side categorisation. Engine code can use
# either the per-category lists above (is_in checks) or this mapping
# (category-resolution joins).
COLLATERAL_TYPE_CATEGORY: dict[str, str] = {
    **dict.fromkeys(FINANCIAL_COLLATERAL_TYPES, "financial"),
    **dict.fromkeys(RECEIVABLE_COLLATERAL_TYPES, "receivables"),
    **dict.fromkeys(REAL_ESTATE_COLLATERAL_TYPES, "real_estate"),
    **dict.fromkeys(OTHER_PHYSICAL_COLLATERAL_TYPES, "other_physical"),
    **dict.fromkeys(COVERED_BOND_COLLATERAL_TYPES, "covered_bond"),
    **dict.fromkeys(LIFE_INSURANCE_COLLATERAL_TYPES, "life_insurance"),
}


VALID_PROPERTY_TYPES = {"residential", "commercial", "adc"}

VALID_ISSUER_TYPES = {"sovereign", "pse", "corporate", "securitisation"}

VALID_VALUATION_TYPES = {"market", "indexed", "independent"}

VALID_PROVISION_TYPES = {"scra", "gcra"}

VALID_RATING_TYPES = {"internal", "external"}

VALID_SL_TYPES = {
    "project_finance",
    "object_finance",
    "commodities_finance",
    "ipre",
    "hvcre",
}

VALID_PROJECT_PHASES = {"pre_operational", "operational", "high_quality_operational"}

VALID_SLOTTING_CATEGORIES = {"strong", "good", "satisfactory", "weak", "default"}

VALID_EQUITY_TYPES = {
    "central_bank",
    "subordinated_debt",
    "listed",
    "exchange_traded",
    "government_supported",
    "unlisted",
    "speculative",
    "private_equity",
    "private_equity_diversified",
    "ciu",
    "other",
}

VALID_BENEFICIARY_TYPES = {"counterparty", "loan", "facility", "contingent"}

VALID_PROTECTION_TYPES = {"guarantee", "credit_derivative"}

VALID_SCRA_GRADES = {"A", "A_ENHANCED", "B", "C"}

VALID_RISK_TYPES_INPUT = {"FR", "FRC", "MR", "OC", "MLR", "LR"}

VALID_BS_TYPES = {"ONB", "OFB"}

VALID_CHILD_TYPES = {"facility", "loan", "contingent"}

VALID_MODEL_PERMISSION_APPROACHES = {"foundation_irb", "advanced_irb", "slotting"}

VALID_CIU_APPROACHES = {"look_through", "mandate_based", "fallback"}

# Registry: maps table_name -> {column_name -> valid_values_set}
# Used by validate_bundle_values() for input validation.
COLUMN_VALUE_CONSTRAINTS: dict[str, dict[str, set[str]]] = {
    "facilities": {
        "seniority": VALID_SENIORITY,
        "risk_type": VALID_RISK_TYPES_INPUT,
        "underlying_risk_type": VALID_RISK_TYPES_INPUT,
    },
    "loans": {
        "seniority": VALID_SENIORITY,
    },
    "contingents": {
        "seniority": VALID_SENIORITY,
        "bs_type": VALID_BS_TYPES,
        "risk_type": VALID_RISK_TYPES_INPUT,
        "underlying_risk_type": VALID_RISK_TYPES_INPUT,
    },
    "counterparties": {
        "entity_type": VALID_ENTITY_TYPES,
        "scra_grade": VALID_SCRA_GRADES,
    },
    "collateral": {
        "collateral_type": VALID_COLLATERAL_TYPES,
        "property_type": VALID_PROPERTY_TYPES,
        "issuer_type": VALID_ISSUER_TYPES,
        "valuation_type": VALID_VALUATION_TYPES,
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
    },
    "provisions": {
        "provision_type": VALID_PROVISION_TYPES,
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
    },
    "ratings": {
        "rating_type": VALID_RATING_TYPES,
    },
    "specialised_lending": {
        "sl_type": VALID_SL_TYPES,
        "slotting_category": VALID_SLOTTING_CATEGORIES,
        "project_phase": VALID_PROJECT_PHASES,
    },
    "equity_exposures": {
        "equity_type": VALID_EQUITY_TYPES,
        "ciu_approach": VALID_CIU_APPROACHES,
    },
    "guarantees": {
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
        "protection_type": VALID_PROTECTION_TYPES,
    },
    "facility_mappings": {
        "child_type": VALID_CHILD_TYPES,
    },
    "model_permissions": {
        "approach": VALID_MODEL_PERMISSION_APPROACHES,
    },
}


# =============================================================================
# STAGE-OUTPUT SCHEMAS (calculator-derived columns)
# =============================================================================
#
# Columns produced by upstream pipeline stages (HierarchyResolver, CRMProcessor,
# Classifier) and consumed by downstream calculators (SA, IRB, Equity, Slotting).
# These are NOT input columns — they are emitted mid-pipeline. Calculators call
# ``ensure_columns(lf, <STAGE>_OUTPUT_SCHEMA)`` to guarantee the columns exist
# with declared defaults before using them, which previously required dozens of
# hand-written ``if "col" not in schema.names()`` blocks per calculator.
#
# All columns here are ``required=False`` — they are produced optionally by the
# upstream stage (e.g., when a counterparty has no parent, ``cp_scra_grade``
# stays null) and defaulted when absent.

# Columns joined onto exposures from counterparty data during hierarchy
# resolution. Prefixed ``cp_`` to distinguish from exposure-native columns.
HIERARCHY_OUTPUT_SCHEMA: dict[str, ColumnSpec] = {
    "cp_country_code": ColumnSpec(pl.String, required=False),
    "cp_entity_type": ColumnSpec(pl.String, required=False),
    "cp_is_natural_person": ColumnSpec(pl.Boolean, default=False, required=False),
    "cp_is_social_housing": ColumnSpec(pl.Boolean, default=False, required=False),
    "cp_is_managed_as_retail": ColumnSpec(pl.Boolean, default=False, required=False),
    "cp_is_investment_grade": ColumnSpec(pl.Boolean, default=False, required=False),
    "cp_is_ccp_client_cleared": ColumnSpec(pl.Boolean, required=False),
    "cp_scra_grade": ColumnSpec(pl.String, required=False),
    "cp_sovereign_cqs": ColumnSpec(pl.Int32, required=False),
    "cp_local_currency": ColumnSpec(pl.String, required=False),
    "cp_institution_cqs": ColumnSpec(pl.Int8, required=False),
}

# Columns produced by the CRM stage: collateral value buckets and provision
# allocations. Calculators consume these when computing secured/unsecured
# splits (Art. 127) and EAD net of provisions (Art. 111(2)).
CRM_OUTPUT_SCHEMA: dict[str, ColumnSpec] = {
    "collateral_re_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "collateral_receivables_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "collateral_other_physical_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "provision_allocated": ColumnSpec(pl.Float64, default=0.0, required=False),
    "provision_deducted": ColumnSpec(pl.Float64, default=0.0, required=False),
}

# Columns produced by the classification stage: SME / retail / RE / SL flags
# derived from counterparty attributes + exposure amounts + regulatory rules.
CLASSIFIER_OUTPUT_SCHEMA: dict[str, ColumnSpec] = {
    "qualifies_as_retail": ColumnSpec(pl.Boolean, default=True, required=False),
    "is_sme": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_defaulted": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_income_cover": ColumnSpec(pl.Boolean, default=False, required=False),
    "ltv": ColumnSpec(pl.Float64, required=False),
    "sl_project_phase": ColumnSpec(pl.String, required=False),
    # Real estate loan-split candidate flags (CRR Art. 125/126, B3.1 Art. 124F/H).
    # Populated by Classifier._flag_property_reclassification_candidates.
    # Consumed by the downstream RealEstateSplitter stage.
    "re_split_target_class": ColumnSpec(pl.String, required=False),
    "re_split_mode": ColumnSpec(pl.String, required=False),
    "re_split_property_type": ColumnSpec(pl.String, required=False),
    "re_split_property_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "re_split_cre_rental_coverage_met": ColumnSpec(pl.Boolean, default=False, required=False),
}


# Columns produced by the RealEstateSplitter stage. Both rows of a split share
# `split_parent_id`; `re_split_role` is one of "secured" / "residual" / "whole"
# (or null for unaffected rows).
RE_SPLITTER_OUTPUT_SCHEMA: dict[str, ColumnSpec] = {
    "split_parent_id": ColumnSpec(pl.String, required=False),
    "re_split_role": ColumnSpec(pl.String, required=False),
}


# =============================================================================
# INTERMEDIATE PIPELINE SCHEMAS
# =============================================================================

# Schema for exposures after loading (unified from facilities, loans, contingents)
RAW_EXPOSURE_SCHEMA = {
    "exposure_reference": pl.String,  # Unique identifier
    "exposure_type": pl.String,  # "facility", "loan", "contingent"
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,  # Drawn balance (0 for facilities without loans)
    "interest": pl.Float64,  # Accrued interest (adds to on-balance-sheet EAD, not undrawn)
    "undrawn_amount": pl.Float64,  # Undrawn commitment (limit - drawn for facilities)
    "nominal_amount": pl.Float64,  # Total nominal (for contingents)
    "lgd": pl.Float64,  # Internal LGD estimate (if available)
    "lgd_unsecured": pl.Float64,  # Art. 169B(2)(c): firm's own unsecured LGD estimate
    "has_sufficient_collateral_data": pl.Boolean,  # Art. 169A/169B: True=LGD modelling, False=Foundation fallback
    "beel": pl.Float64,  # Best estimate expected loss
    "seniority": pl.String,  # senior, subordinated
    "risk_type": pl.String,  # FR, FRC, MR, OC, MLR, LR - determines CCF (Art. 111)
    "underlying_risk_type": pl.String,  # Art. 111(1)(c) - OBS item type for commitment-to-issue
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.5, can exceed 100% for retail)
    "ead_modelled": pl.Float64,  # A-IRB modelled facility-level EAD (Art. 166D(3)/(4))
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    "is_payroll_loan": pl.Boolean,  # Payroll/pension loan — 35% RW under Basel 3.1 (Art. 123(3)(a-b))
    "is_buy_to_let": pl.Boolean,  # BTL property lending - excluded from SME supporting factor (CRR Art. 501)
    "has_one_day_maturity_floor": pl.Boolean,  # Art. 162(3): repos/SFTs with daily margining — 1-day M floor
    "is_sft": pl.Boolean,  # CRR Art. 162(1): repurchase / securities / commodities lending/borrowing — F-IRB M = 0.5y
    "facility_termination_date": pl.Date,  # Art. 162(2A)(k): max contractual termination date for revolving facilities (Basel 3.1 M)
    "effective_maturity": pl.Float64,  # Art. 162(3): explicit numeric M override (years); bypasses 1y floor when populated
    # FX conversion audit trail (populated after FX conversion)
    "original_currency": pl.String,  # Currency before FX conversion
    "original_amount": pl.Float64,  # Amount before FX conversion (drawn + interest + nominal)
    "fx_rate_applied": pl.Float64,  # Rate used (null if no conversion needed)
}

# Schema for exposures after hierarchy resolution
RESOLVED_HIERARCHY_SCHEMA = {
    # Original exposure fields
    "exposure_reference": pl.String,
    "exposure_type": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "interest": pl.Float64,  # Accrued interest (adds to on-balance-sheet EAD, not undrawn)
    "undrawn_amount": pl.Float64,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "lgd_unsecured": pl.Float64,  # Art. 169B(2)(c): firm's own unsecured LGD estimate
    "has_sufficient_collateral_data": pl.Boolean,  # Art. 169A/169B: True=LGD modelling, False=Foundation fallback
    "seniority": pl.String,
    "risk_type": pl.String,  # FR, FRC, MR, OC, MLR, LR - determines CCF (Art. 111)
    "underlying_risk_type": pl.String,  # Art. 111(1)(c) - OBS item type for commitment-to-issue
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.5, can exceed 100% for retail)
    "ead_modelled": pl.Float64,  # A-IRB modelled facility-level EAD (Art. 166D(3)/(4))
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    "is_buy_to_let": pl.Boolean,  # BTL property lending - excluded from SME supporting factor (CRR Art. 501)
    # Counterparty hierarchy additions
    "counterparty_has_parent": pl.Boolean,
    "parent_counterparty_reference": pl.String,
    "ultimate_parent_reference": pl.String,
    "counterparty_hierarchy_depth": pl.Int8,
    # Facility hierarchy additions
    "exposure_has_parent": pl.Boolean,
    "parent_facility_reference": pl.String,
    "root_facility_reference": pl.String,
    "facility_hierarchy_depth": pl.Int8,
    # Lending group aggregation
    "lending_group_reference": pl.String,
    "lending_group_total_exposure": pl.Float64,
    # Retail threshold adjustment (CRR Art. 123(c) - residential property exclusion)
    "lending_group_adjusted_exposure": pl.Float64,  # Excludes residential RE for retail threshold
    "residential_collateral_value": pl.Float64,  # Residential RE collateral securing this exposure
    "exposure_for_retail_threshold": pl.Float64,  # This exposure's contribution (excl. residential RE)
}

# Schema for exposures after classification
CLASSIFIED_EXPOSURE_SCHEMA = {
    # Include all resolved hierarchy fields
    "exposure_reference": pl.String,
    "exposure_type": pl.String,
    "counterparty_reference": pl.String,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "interest": pl.Float64,  # Accrued interest (adds to on-balance-sheet EAD, not undrawn)
    "undrawn_amount": pl.Float64,
    "seniority": pl.String,
    "risk_type": pl.String,  # FR, FRC, MR, OC, MLR, LR - determines CCF (Art. 111)
    "underlying_risk_type": pl.String,  # Art. 111(1)(c) - OBS item type for commitment-to-issue
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.5, can exceed 100% for retail)
    "ead_modelled": pl.Float64,  # A-IRB modelled facility-level EAD (Art. 166D(3)/(4))
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    "is_buy_to_let": pl.Boolean,  # BTL property lending - excluded from SME supporting factor (CRR Art. 501)
    # A-IRB LGD modelling (Art. 169A/169B)
    "lgd_unsecured": pl.Float64,  # Art. 169B(2)(c): firm's own unsecured LGD estimate
    "has_sufficient_collateral_data": pl.Boolean,  # Art. 169A/169B: True=LGD modelling, False=Foundation fallback
    # Classification additions
    "exposure_class": pl.String,  # central_govt_central_bank, institution, corporate, retail, etc.
    "exposure_class_reason": pl.String,  # Explanation of classification
    "approach_permitted": pl.String,  # SA, FIRB, AIRB based on permissions
    "approach_applied": pl.String,  # Actual approach used
    "approach_selection_reason": pl.String,  # Why this approach was selected
    # Rating information
    "cqs": pl.Int8,  # Credit Quality Step (1-6, 0 for unrated)
    "pd": pl.Float64,  # Probability of default (for IRB)
    "rating_agency": pl.String,  # Source of external rating
    "rating_value": pl.String,  # Original rating value
    # Entity flags carried forward
    "is_sme": pl.Boolean,  # SME classification flag
    "is_retail_eligible": pl.Boolean,  # Meets retail criteria
}

# Schema for exposures after CRM application
CRM_ADJUSTED_SCHEMA = {
    # Include all classified exposure fields
    "exposure_reference": pl.String,
    "exposure_type": pl.String,
    "counterparty_reference": pl.String,
    "currency": pl.String,
    "exposure_class": pl.String,
    "approach_applied": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "seniority": pl.String,
    # EAD calculation
    "drawn_amount": pl.Float64,
    "interest": pl.Float64,  # Accrued interest (adds to on-balance-sheet EAD, not undrawn)
    "undrawn_amount": pl.Float64,
    "ccf_applied": pl.Float64,  # Credit conversion factor
    "converted_undrawn": pl.Float64,  # undrawn × CCF
    "gross_ead": pl.Float64,  # drawn + converted_undrawn
    # Collateral impact
    "collateral_gross_value": pl.Float64,
    "collateral_haircut_applied": pl.Float64,
    "fx_haircut_applied": pl.Float64,
    "collateral_adjusted_value": pl.Float64,
    "ead_after_collateral": pl.Float64,
    # Guarantee impact
    "guarantee_coverage_pct": pl.Float64,
    "guaranteed_amount": pl.Float64,
    "guarantee_fx_haircut": pl.Float64,  # FX mismatch haircut on guarantee (8% or 0%)
    "guarantee_restructuring_haircut": pl.Float64,  # CDS restructuring exclusion (40% or 0%)
    "ead_after_guarantee": pl.Float64,
    # Final EAD
    "final_ead": pl.Float64,
    # LGD determination
    "lgd_type": pl.String,  # "supervisory" or "modelled"
    "lgd_value": pl.Float64,  # LGD for calculation
    "lgd_floor": pl.Float64,  # Applicable floor (Basel 3.1)
    "lgd_floored": pl.Float64,  # max(lgd_value, lgd_floor)
}

# Pre/Post CRM columns for regulatory reporting
# These columns support dual-view reporting per COREP requirements:
# - Pre-CRM: Original exposure under borrower's risk class
# - Post-CRM: Split exposure between borrower (unguaranteed) and guarantor (guaranteed)
CRM_PRE_POST_COLUMNS = {
    # Pre-CRM attributes (original exposure before CRM substitution)
    "pre_crm_counterparty_reference": pl.String,  # Original borrower reference
    "pre_crm_exposure_class": pl.String,  # Original exposure class before substitution
    # Post-CRM attributes (for guaranteed portion)
    "post_crm_counterparty_guaranteed": pl.String,  # = guarantor_reference for guaranteed exposures
    "post_crm_exposure_class_guaranteed": pl.String,  # Derived from guarantor's entity_type
    # CRM impact indicators
    "is_guaranteed": pl.Boolean,  # Whether exposure has effective guarantee
    "guaranteed_portion": pl.Float64,  # EAD covered by guarantee
    "unguaranteed_portion": pl.Float64,  # EAD not covered by guarantee
    "guarantor_reference": pl.String,  # Foreign key to get guarantor attributes via joins
    # Risk weight tracking (populated by calculators)
    "pre_crm_risk_weight": pl.Float64,  # Borrower's RW before guarantee substitution
    "guarantor_rw": pl.Float64,  # Guarantor's RW (SA lookup or IRB-calculated)
    "guarantee_benefit_rw": pl.Float64,  # RW reduction from guarantee
    # IRB-specific pre/post CRM tracking
    "rwa_irb_original": pl.Float64,  # IRB RWA before guarantee substitution
    "risk_weight_irb_original": pl.Float64,  # IRB RW before guarantee substitution
    "guarantee_method_used": pl.String,  # "SA_RW_SUBSTITUTION", "PD_SUBSTITUTION", or "NO_GUARANTEE"
    "is_guarantee_beneficial": pl.Boolean,  # Whether guarantee reduces RWA
    "guarantee_status": pl.String,  # "NO_GUARANTEE", "SA_RW_SUBSTITUTION", "PD_SUBSTITUTION", "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"
}

# Schema for SA calculation results
SA_RESULT_SCHEMA = {
    "exposure_reference": pl.String,
    "exposure_class": pl.String,
    "final_ead": pl.Float64,
    # Risk weight determination
    "sa_cqs": pl.Int8,
    "sa_base_risk_weight": pl.Float64,
    "sa_rw_adjustment": pl.Float64,
    "sa_rw_adjustment_reason": pl.String,
    "sa_final_risk_weight": pl.Float64,
    "sa_rw_regulatory_ref": pl.String,
    # RWA calculation
    "sa_rwa": pl.Float64,  # final_ead × risk_weight
}

# Schema for IRB calculation results
IRB_RESULT_SCHEMA = {
    "exposure_reference": pl.String,
    "exposure_class": pl.String,
    "final_ead": pl.Float64,
    # IRB parameters
    "irb_pd_original": pl.Float64,
    "irb_pd_floor": pl.Float64,
    "irb_pd_floored": pl.Float64,  # max(pd_original, pd_floor)
    "irb_lgd_type": pl.String,  # "supervisory" or "modelled"
    "irb_lgd_original": pl.Float64,
    "irb_lgd_floor": pl.Float64,
    "irb_lgd_floored": pl.Float64,  # max(lgd_original, lgd_floor)
    "irb_maturity_m": pl.Float64,  # Effective maturity
    # Formula components
    "irb_correlation_r": pl.Float64,  # Asset correlation
    "irb_maturity_adj_b": pl.Float64,  # Maturity adjustment factor
    "irb_capital_k": pl.Float64,  # Capital requirement (K)
    "irb_scaling_factor": pl.Float64,  # 1.06
    # RWA calculation
    "irb_risk_weight": pl.Float64,  # 12.5 × K × scaling_factor
    "irb_rwa": pl.Float64,  # final_ead × risk_weight
    # Expected loss
    "irb_expected_loss": pl.Float64,  # PD × LGD × EAD
}

# Schema for slotting calculation results
SLOTTING_RESULT_SCHEMA = {
    "exposure_reference": pl.String,
    "sl_type": pl.String,  # project_finance, object_finance, etc.
    "slotting_category": pl.String,  # strong, good, satisfactory, weak, default
    "remaining_maturity_years": pl.Float64,
    "is_hvcre": pl.Boolean,
    "sl_base_risk_weight": pl.Float64,
    "sl_maturity_adjusted_rw": pl.Float64,
    "sl_final_risk_weight": pl.Float64,
    "sl_rwa": pl.Float64,
}


# =============================================================================
# CONFIGURATION SCHEMAS
# =============================================================================

IRB_PERMISSIONS_SCHEMA = {
    "exposure_class": pl.String,
    "approach_permitted": pl.String,  # SA, FIRB, AIRB
    "effective_date": pl.Date,
}

CALCULATION_CONFIG_SCHEMA = {
    "config_key": pl.String,
    "config_value": pl.String,
    "config_type": pl.String,  # string, float, date, boolean
    # Expected keys: basel_version (3.0/3.1), reporting_date, output_floor_percentage, etc.
}


# =============================================================================
# OUTPUT SCHEMAS
# =============================================================================

# Main RWA calculation output schema
# Designed to enable full auditability: users can investigate why results occurred
# and replicate the calculation from the output data alone.
CALCULATION_OUTPUT_SCHEMA = {
    # -------------------------------------------------------------------------
    # IDENTIFICATION & LINEAGE
    # -------------------------------------------------------------------------
    "calculation_run_id": pl.String,  # Unique run identifier for audit trail
    "calculation_timestamp": pl.Datetime,  # When calculation was performed
    "exposure_reference": pl.String,  # Links to source loan/facility/contingent
    "parent_exposure_reference": pl.String,  # Original exposure before multi-guarantor split
    "exposure_type": pl.String,  # "loan", "facility", "contingent"
    "counterparty_reference": pl.String,  # Links to counterparty
    "book_code": pl.String,  # Portfolio/book classification
    "currency": pl.String,  # Exposure currency
    "model_id": pl.String,  # IRB model identifier (for model-level permission audit trail)
    "basel_version": pl.String,  # "3.0" or "3.1"
    # -------------------------------------------------------------------------
    # COUNTERPARTY HIERARCHY (Rating Inheritance)
    # -------------------------------------------------------------------------
    "counterparty_has_parent": pl.Boolean,  # Whether counterparty is part of org hierarchy
    "parent_counterparty_reference": pl.String,  # Immediate parent in org structure
    "ultimate_parent_reference": pl.String,  # Top-level parent (for group-level analysis)
    "counterparty_hierarchy_depth": pl.Int8,  # Levels from ultimate parent (0=top)
    "internal_pd": pl.Float64,  # Internal PD from firm's IRB model (gates IRB approach)
    "external_cqs": pl.Int8,  # CQS from external rating agency
    # -------------------------------------------------------------------------
    # LENDING GROUP HIERARCHY (Retail Threshold Aggregation)
    # -------------------------------------------------------------------------
    "lending_group_reference": pl.String,  # Lending group parent if applicable
    "lending_group_total_exposure": pl.Float64,  # Aggregated exposure across group
    "retail_threshold_applied": pl.Float64,  # £1m (3.0) or £880k (3.1)
    "retail_eligible_via_group": pl.Boolean,  # Whether retail classification based on group aggregation
    # -------------------------------------------------------------------------
    # EXPOSURE HIERARCHY (Facility Structure)
    # -------------------------------------------------------------------------
    "exposure_has_parent": pl.Boolean,  # Whether exposure is child of a facility
    "parent_facility_reference": pl.String,  # Parent facility reference
    "root_facility_reference": pl.String,  # Top-level facility in hierarchy
    "facility_hierarchy_depth": pl.Int8,  # Levels from root facility (0=top)
    "facility_hierarchy_path": pl.List(pl.String),  # Full path from root to this exposure
    # -------------------------------------------------------------------------
    # CRM INHERITANCE (From Hierarchy)
    # -------------------------------------------------------------------------
    "collateral_source_level": pl.String,  # "exposure", "facility", "counterparty"
    "collateral_inherited_from": pl.String,  # Reference of entity collateral inherited from
    "collateral_allocation_method": pl.String,  # "direct", "pro_rata", "waterfall", "optimised"
    "guarantee_source_level": pl.String,  # "exposure", "facility", "counterparty"
    "guarantee_inherited_from": pl.String,  # Reference of entity guarantee inherited from
    "provision_source_level": pl.String,  # "exposure", "facility", "counterparty"
    "provision_inherited_from": pl.String,  # Reference of entity provision inherited from
    "crm_allocation_notes": pl.String,  # Explanation of how CRM was allocated down hierarchy
    # -------------------------------------------------------------------------
    # EXPOSURE CLASSIFICATION
    # -------------------------------------------------------------------------
    "exposure_class": pl.String,  # Determined class (central_govt_central_bank, institution, corporate, retail, etc.)
    "exposure_class_reason": pl.String,  # Explanation of classification decision
    "approach_permitted": pl.String,  # "SA", "FIRB", "AIRB" based on permissions
    "approach_applied": pl.String,  # Actual approach used
    "approach_selection_reason": pl.String,  # Why this approach was selected
    # -------------------------------------------------------------------------
    # ORIGINAL EXPOSURE VALUES
    # -------------------------------------------------------------------------
    "drawn_amount": pl.Float64,  # Original drawn balance
    "undrawn_amount": pl.Float64,  # Undrawn commitment amount
    "original_maturity_date": pl.Date,  # Contractual maturity
    "residual_maturity_years": pl.Float64,  # Years to maturity
    # -------------------------------------------------------------------------
    # CCF APPLICATION (Off-balance sheet conversion)
    # -------------------------------------------------------------------------
    "ccf_applied": pl.Float64,  # CCF percentage (0%, 20%, 40%, 50%, 100%)
    "ccf_source": pl.String,  # Reference to regulatory article
    "converted_undrawn": pl.Float64,  # undrawn_amount × ccf_applied
    # -------------------------------------------------------------------------
    # CRM - COLLATERAL IMPACT
    # -------------------------------------------------------------------------
    "collateral_references": pl.List(pl.String),  # IDs of collateral items used
    "collateral_types": pl.List(pl.String),  # Types of collateral
    "collateral_gross_value": pl.Float64,  # Total market value before haircuts
    "collateral_haircut_applied": pl.Float64,  # Weighted average haircut %
    "fx_haircut_applied": pl.Float64,  # FX mismatch haircut (8% or 0%)
    "maturity_mismatch_adjustment": pl.Float64,  # Adjustment for maturity mismatch
    "collateral_adjusted_value": pl.Float64,  # Net collateral value after haircuts
    "on_bs_netting_amount": pl.Float64,  # On-balance sheet netting benefit (CRR Art. 195)
    # Per-type collateral tracking for COREP C 08.01 (cols 0170-0210)
    "collateral_financial_value": pl.Float64,  # Eligible financial collateral adj value
    "collateral_re_value": pl.Float64,  # Real estate collateral adj value
    "collateral_receivables_value": pl.Float64,  # Receivables collateral adj value
    "collateral_other_physical_value": pl.Float64,  # Other physical collateral adj value
    "collateral_cash_value": pl.Float64,  # Cash/deposit collateral adj value (subset of financial)
    # -------------------------------------------------------------------------
    # CRM - GUARANTEE IMPACT (Substitution approach)
    # -------------------------------------------------------------------------
    "guarantee_references": pl.List(pl.String),  # IDs of guarantees used
    "guarantor_references": pl.List(pl.String),  # Guarantor counterparty IDs
    "guarantee_coverage_pct": pl.Float64,  # % of exposure guaranteed
    "guaranteed_amount": pl.Float64,  # Amount covered by guarantee
    "guarantee_fx_haircut": pl.Float64,  # FX mismatch haircut on guarantee (8% or 0%)
    "guarantee_restructuring_haircut": pl.Float64,  # CDS restructuring exclusion (40% or 0%)
    "guarantor_risk_weight": pl.Float64,  # RW of guarantor (for substitution)
    "guarantee_benefit": pl.Float64,  # RWA reduction from guarantee
    # -------------------------------------------------------------------------
    # PRE/POST CRM COUNTERPARTY TRACKING (Regulatory reporting)
    # -------------------------------------------------------------------------
    # Pre-CRM attributes (original exposure before CRM substitution)
    "pre_crm_counterparty_reference": pl.String,  # Original borrower reference
    "pre_crm_exposure_class": pl.String,  # Original exposure class before substitution
    # Post-CRM attributes (for guaranteed portion)
    "post_crm_counterparty_guaranteed": pl.String,  # = guarantor_reference for guaranteed
    "post_crm_exposure_class_guaranteed": pl.String,  # Derived from guarantor's entity_type
    "guarantor_reference": pl.String,  # Foreign key to guarantor data
    # CRM split tracking
    "is_guaranteed": pl.Boolean,  # Whether exposure has effective guarantee
    "guaranteed_portion": pl.Float64,  # EAD covered by guarantee
    "unguaranteed_portion": pl.Float64,  # EAD not covered by guarantee
    # Risk weight tracking for pre/post CRM reporting
    "pre_crm_risk_weight": pl.Float64,  # Borrower's RW before guarantee substitution
    "guarantee_benefit_rw": pl.Float64,  # RW reduction from guarantee (pre_crm_rw - post_crm_rw)
    # IRB-specific tracking
    "rwa_irb_original": pl.Float64,  # IRB RWA before guarantee substitution
    "risk_weight_irb_original": pl.Float64,  # IRB RW before guarantee substitution
    "guarantee_method_used": pl.String,  # "SA_RW_SUBSTITUTION", "PD_SUBSTITUTION", or "NO_GUARANTEE"
    "guarantee_status": pl.String,  # Detailed status including non-beneficial flag
    "protection_type": pl.String,  # "guarantee" or "credit_derivative" — unfunded protection type
    # -------------------------------------------------------------------------
    # CRM - PROVISION IMPACT
    # -------------------------------------------------------------------------
    "provision_references": pl.List(pl.String),  # IDs of provisions applied
    "scra_provision_amount": pl.Float64,  # Specific provisions
    "gcra_provision_amount": pl.Float64,  # General provisions
    "provision_capped_amount": pl.Float64,  # Amount eligible for CRM
    # -------------------------------------------------------------------------
    # EAD CALCULATION
    # -------------------------------------------------------------------------
    "gross_ead": pl.Float64,  # drawn + converted_undrawn
    "ead_after_collateral": pl.Float64,  # After collateral CRM
    "ead_after_guarantee": pl.Float64,  # Portion not guaranteed
    "final_ead": pl.Float64,  # Final EAD for RWA calculation
    "ead_calculation_method": pl.String,  # "simple", "comprehensive", "supervisory_haircut"
    # Art. 222 Financial Collateral Simple Method (FCSM)
    "fcsm_collateral_value": pl.Float64,  # Total eligible financial collateral (raw market value)
    "fcsm_collateral_rw": pl.Float64,  # Weighted-average SA RW of collateral
    "pre_fcsm_risk_weight": pl.Float64,  # Risk weight before FCSM substitution
    # -------------------------------------------------------------------------
    # RISK WEIGHT DETERMINATION - SA
    # -------------------------------------------------------------------------
    "sa_cqs": pl.Int8,  # Credit Quality Step used (1-6, 0=unrated)
    "sa_rating_source": pl.String,  # Rating agency or "internal"
    "sa_base_risk_weight": pl.Float64,  # Base RW from lookup table
    "sa_rw_adjustment": pl.Float64,  # Any adjustments applied
    "sa_rw_adjustment_reason": pl.String,  # Reason for adjustment
    "sa_final_risk_weight": pl.Float64,  # Final SA risk weight
    "sa_rw_regulatory_ref": pl.String,  # CRR article / CRE reference
    # -------------------------------------------------------------------------
    # RISK WEIGHT DETERMINATION - IRB
    # -------------------------------------------------------------------------
    "irb_pd_original": pl.Float64,  # PD before flooring
    "irb_pd_floor": pl.Float64,  # Applicable PD floor
    "irb_pd_floored": pl.Float64,  # max(pd_original, pd_floor)
    "irb_lgd_type": pl.String,  # "supervisory" (F-IRB) or "modelled" (A-IRB)
    "irb_lgd_original": pl.Float64,  # LGD before flooring
    "irb_lgd_floor": pl.Float64,  # Applicable LGD floor
    "irb_lgd_floored": pl.Float64,  # max(lgd_original, lgd_floor)
    "irb_maturity_m": pl.Float64,  # Effective maturity (M)
    "irb_correlation_r": pl.Float64,  # Asset correlation
    "irb_maturity_adj_b": pl.Float64,  # Maturity adjustment factor
    "irb_capital_k": pl.Float64,  # Capital requirement (K)
    "irb_risk_weight": pl.Float64,  # 12.5 × K × 100%
    # -------------------------------------------------------------------------
    # SPECIALISED LENDING / EQUITY (Alternative approaches)
    # -------------------------------------------------------------------------
    "sl_type": pl.String,  # SL category if applicable
    "sl_project_phase": pl.String,  # pre_operational/operational/high_quality_operational
    "sl_slotting_category": pl.String,  # strong/good/satisfactory/weak/default
    "sl_risk_weight": pl.Float64,  # Slotting RW
    "equity_type": pl.String,  # Equity category if applicable
    "equity_risk_weight": pl.Float64,  # Equity RW
    "equity_transitional_approach": pl.String,  # "sa_transitional" or "irb_transitional" (B3.1)
    "equity_higher_risk": pl.Boolean,  # True if 400%+ RW (speculative, venture capital)
    # -------------------------------------------------------------------------
    # REAL ESTATE SPECIFIC
    # -------------------------------------------------------------------------
    "property_type": pl.String,  # residential/commercial
    "property_ltv": pl.Float64,  # Loan-to-value ratio
    "ltv_band": pl.String,  # LTV band for RW lookup
    "is_income_producing": pl.Boolean,  # CRE income flag
    "is_adc": pl.Boolean,  # ADC exposure flag
    "is_qualifying_re": pl.Boolean,  # Art. 124A: meets regulatory RE qualifying criteria
    "materially_dependent_on_property": pl.Boolean,  # Cash-flow dependency on property (B3.1)
    "mortgage_risk_weight": pl.Float64,  # LTV-based RW
    # -------------------------------------------------------------------------
    # FINAL RWA CALCULATION
    # -------------------------------------------------------------------------
    "rwa_before_floor": pl.Float64,  # EAD × RW (before output floor)
    "sa_equivalent_rwa": pl.Float64,  # SA RWA for floor comparison
    "output_floor_pct": pl.Float64,  # Floor percentage (72.5% for 3.1)
    "output_floor_rwa": pl.Float64,  # sa_equivalent_rwa × floor_pct
    "floor_binding": pl.Boolean,  # Whether floor increased RWA
    "floor_impact": pl.Float64,  # Additional RWA from floor
    "final_rwa": pl.Float64,  # max(rwa_before_floor, output_floor_rwa)
    "risk_weight_effective": pl.Float64,  # final_rwa / final_ead (implied RW)
    # -------------------------------------------------------------------------
    # CURRENCY MISMATCH (Basel 3.1 Art. 123B / CRE20.93)
    # -------------------------------------------------------------------------
    "borrower_income_currency": pl.String,  # ISO currency of borrower's primary income
    "currency_mismatch_multiplier_applied": pl.Boolean,  # True if 1.5x RW multiplier applied
    # -------------------------------------------------------------------------
    # POST-MODEL ADJUSTMENTS (Basel 3.1 PRA PS9/24 Art. 153(5A), 154(4A), 158(6A))
    # -------------------------------------------------------------------------
    "rwa_pre_adjustments": pl.Float64,  # RWEA before post-model adjustments
    "post_model_adjustment_rwa": pl.Float64,  # General PMA add-on to RWEA
    "mortgage_rw_floor_adjustment": pl.Float64,  # RWEA increase from mortgage RW floor
    "unrecognised_exposure_adjustment": pl.Float64,  # RWEA increase for unrecognised exposures
    "el_pre_adjustment": pl.Float64,  # EL before post-model adjustments
    "post_model_adjustment_el": pl.Float64,  # General PMA add-on to EL
    "el_after_adjustment": pl.Float64,  # EL after post-model adjustments
    # -------------------------------------------------------------------------
    # DOUBLE DEFAULT (CRR Art. 153(3), 202-203 — CRR only)
    # -------------------------------------------------------------------------
    "is_double_default_eligible": pl.Boolean,  # Whether exposure qualifies for DD treatment
    "double_default_unfunded_protection": pl.Float64,  # Guaranteed portion under DD → COREP 0220
    "irb_lgd_double_default": pl.Float64,  # LGD used in DD calculation (= obligor LGD)
    # -------------------------------------------------------------------------
    # EXPECTED LOSS (IRB comparison to provisions)
    # -------------------------------------------------------------------------
    "irb_expected_loss": pl.Float64,  # PD × LGD × EAD
    "provision_held": pl.Float64,  # Total provision amount
    "ava_amount": pl.Float64,  # Additional value adjustments (Art. 34) — Pool B component
    "other_own_funds_reductions": pl.Float64,  # Other own funds reductions — Pool B component
    "el_shortfall": pl.Float64,  # max(0, EL - pool_b) where pool_b = prov + AVA + other
    "el_excess": pl.Float64,  # max(0, pool_b - EL)
    # -------------------------------------------------------------------------
    # BASEL 3.1 ADJUSTMENTS
    # -------------------------------------------------------------------------
    "sme_supporting_factor": pl.Float64,  # SME factor (3.0 only, 0.7619/0.85)
    "infra_supporting_factor": pl.Float64,  # Infrastructure factor if applicable
    "supporting_factor_benefit": pl.Float64,  # RWA reduction from factors
    # -------------------------------------------------------------------------
    # WARNINGS & VALIDATION
    # -------------------------------------------------------------------------
    "calculation_warnings": pl.List(pl.String),  # Any issues/assumptions made
    "data_quality_flags": pl.List(pl.String),  # Missing/imputed values
}


# =============================================================================
# FRAMEWORK-SPECIFIC OUTPUT SCHEMA ADDITIONS
# =============================================================================

# CRR (Basel 3.0) specific output fields
# These fields track CRR-specific treatments not available under Basel 3.1
CRR_OUTPUT_SCHEMA_ADDITIONS = {
    "regulatory_framework": pl.String,  # "CRR"
    "crr_effective_date": pl.Date,  # Regulation effective date
    # SME Supporting Factor (Art. 501)
    "sme_supporting_factor_eligible": pl.Boolean,  # Turnover < EUR 50m
    "sme_supporting_factor_applied": pl.Boolean,  # Whether factor was applied
    "sme_supporting_factor_value": pl.Float64,  # 0.7619
    "rwa_before_sme_factor": pl.Float64,  # RWA before SME factor
    "rwa_sme_factor_benefit": pl.Float64,  # RWA reduction from SME factor
    # Infrastructure Supporting Factor (Art. 501a)
    "infrastructure_factor_eligible": pl.Boolean,  # Qualifies as infrastructure
    "infrastructure_factor_applied": pl.Boolean,  # Whether factor was applied
    "infrastructure_factor_value": pl.Float64,  # 0.75
    "rwa_infrastructure_factor_benefit": pl.Float64,  # RWA reduction
    # CRR exposure classes (Art. 112)
    "crr_exposure_class": pl.String,  # CRR-specific classification
    "crr_exposure_subclass": pl.String,  # Sub-classification where applicable
    # Residential mortgage treatment (Art. 125)
    "crr_mortgage_treatment": pl.String,  # "35_pct" or "split_treatment"
    "crr_mortgage_ltv_threshold": pl.Float64,  # 80% LTV threshold
    # PD floor (Art. 163) - single floor for all classes
    "crr_pd_floor": pl.Float64,  # 0.03% single floor
    # No LGD floors under CRR A-IRB
    "crr_airb_lgd_floor_applied": pl.Boolean,  # Always False under CRR
}

# Basel 3.1 (PRA PS1/26) specific output fields
# These fields track Basel 3.1-specific treatments
BASEL31_OUTPUT_SCHEMA_ADDITIONS = {
    "regulatory_framework": pl.String,  # "BASEL_3_1"
    "b31_effective_date": pl.Date,  # 1 January 2027
    # Output floor (CRE99.1-8, PS1/26 Ch.12)
    "output_floor_applicable": pl.Boolean,  # Whether floor applies to this exposure
    "output_floor_percentage": pl.Float64,  # 72.5% (fully phased in)
    "rwa_irb_unrestricted": pl.Float64,  # IRB RWA before floor
    "rwa_sa_equivalent": pl.Float64,  # Parallel SA calculation
    "rwa_floor_amount": pl.Float64,  # sa_equivalent × floor_pct
    "rwa_floor_impact": pl.Float64,  # Additional RWA from floor
    "is_floor_binding": pl.Boolean,  # Whether floor increased RWA
    # LTV bands for real estate (CRE20.71-87)
    "b31_ltv_band": pl.String,  # "0-50%", "50-60%", "60-70%", etc.
    "b31_ltv_band_rw": pl.Float64,  # Risk weight for LTV band (20%-70%)
    # Differentiated PD floors (CRE30.55, PS1/26 Ch.5)
    "b31_pd_floor_class": pl.String,  # Exposure class for PD floor
    "b31_pd_floor_value": pl.Float64,  # 0.03% (corp), 0.05% (retail), 0.10% (QRRE)
    "b31_pd_floor_binding": pl.Boolean,  # Whether PD floor was binding
    # A-IRB LGD floors (CRE30.41, PS1/26 Ch.5)
    "b31_lgd_floor_class": pl.String,  # Classification for LGD floor
    "b31_lgd_floor_value": pl.Float64,  # 0%, 5%, 10%, 15%, 25% depending on collateral
    "b31_lgd_floor_binding": pl.Boolean,  # Whether LGD floor was binding
    # SME factors NOT available under Basel 3.1
    "b31_sme_factor_note": pl.String,  # "Not available under Basel 3.1"
}


# Combined expected output schema for acceptance testing
EXPECTED_OUTPUT_SCHEMA = {
    "scenario_id": pl.String,  # e.g., "CRR-A1", "B31-A1"
    "scenario_group": pl.String,  # e.g., "CRR-A", "B31-A"
    "regulatory_framework": pl.String,  # "CRR" or "BASEL_3_1"
    "description": pl.String,  # Human-readable scenario description
    "exposure_reference": pl.String,  # Link to test fixture
    "counterparty_reference": pl.String,  # Link to test fixture
    "approach": pl.String,  # "SA", "FIRB", "AIRB"
    "exposure_class": pl.String,  # Exposure classification
    # Input summary
    "ead": pl.Float64,  # Exposure at default
    "pd": pl.Float64,  # Probability of default (IRB)
    "lgd": pl.Float64,  # Loss given default (IRB)
    "maturity": pl.Float64,  # Effective maturity (IRB)
    # Output values
    "risk_weight": pl.Float64,  # Applied risk weight
    "rwa_before_sf": pl.Float64,  # RWA before supporting factors
    "supporting_factor": pl.Float64,  # SME/infrastructure factor (1.0 if none)
    "rwa_after_sf": pl.Float64,  # Final RWA
    "expected_loss": pl.Float64,  # EL for IRB
    # Regulatory reference
    "regulatory_reference": pl.String,  # CRR Art. xxx or CRE xx.xx
    # Calculation details (JSON string for flexibility)
    "calculation_details_json": pl.String,  # JSON-encoded calculation breakdown
}
