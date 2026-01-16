"""
This module contains all the schemas for all data inputs for the rwa_calc.

Key Data Inputs:
- Loan                      # Drawn exposures (leaf nodes in exposure hierarchy)
- Facility                  # Committed credit limits (parent nodes in exposure hierarchy)
- Contingents               # Off-balance sheet commitments
- Counterparty              # Borrower/obligor information and attributes
- Collateral                # Security/collateral items with values and types
- Guarantee                 # Guarantees and credit protection
- Provision                 # IFRS 9 provisions/impairments (SCRA, GCRA)
- Ratings                   # Internal and external credit ratings

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
- Sovereign_risk_weights    # CQS to risk weight mapping for sovereigns (0%-150%)
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

Output Schemas (defined in results.py):
- RWA_result                # Calculated RWA with audit trail
- EL_comparison             # IRB Expected Loss vs Provisions comparison
- Output_floor_result       # Floor calculation breakdown (72.5% of SA equivalent)

"""

import polars as pl

FACILITY_SCHEMA = {
    "facility_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "limit": pl.Float64,
    "committed": pl.Boolean,
    "lgd": pl.Float64,
    "beel": pl.Float64,
    "ltv": pl.Float64,  # Loan-to-value ratio for real estate
    "is_revolving": pl.Boolean,
}

LOAN_SCHEMA = {
    "loan_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "lgd": pl.Float64,
    "beel": pl.Float64,
    "ltv": pl.Float64,  # Loan-to-value ratio for real estate
}

CONTINGENTS_SCHEMA = {
    "contingent_reference": pl.String,
    "contract_type": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "beel": pl.Float64,
    "ccf_category": pl.String,  # Category for CCF lookup
}

COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,  # corporate, individual, sovereign, institution, etc.
    "country_code": pl.String,
    "annual_revenue": pl.Float64,  # For SME classification (£440m large corp, £50m SME)
    "default_status": pl.Boolean,
}

COLLATERAL_SCHEMA = {
    "collateral_reference": pl.String,
    "collateral_type": pl.String,
    "currency": pl.String,
    "maturity_date": pl.Date,
    "market_value": pl.Float64,
    "nominal_value": pl.Float64,
    "beneficiary_type": pl.String, # counterparty/loan/facility/contingent
    "beneficiary_reference":pl.String, # reference to find on the above tables
}

GUARANTEE_SCHEMA = {
    "guarantee_reference": pl.String,
    "guarantee_type": pl.String,
    "guarantor": pl.String,
    "currency": pl.String,
    "maturity_date": pl.Date,
    "amount_covered": pl.Float64,
    "percentage_covered": pl.Float64,
    "beneficiary_type": pl.String,
    "beneficiary_reference":pl.String,
}

PROVISION_SCHEMA = {
    "provision_reference": pl.String,
    "provision_type": pl.String,  # SCRA (Specific), GCRA (General)
    "ifrs9_stage": pl.Int8,  # 1, 2, or 3
    "currency": pl.String,
    "amount": pl.Float64,
    "as_of_date": pl.Date,
    "beneficiary_type": pl.String, # counterparty/loan/facility/contingent
    "beneficiary_reference":pl.String, # reference to find on the above tables
}

RATINGS_SCHEMA = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,  # internal, external
    "rating_agency": pl.String,  # internal, S&P, Moodys, Fitch, DBRS, etc.
    "rating_value": pl.String,  # AAA, AA+, Aa1, etc.
    "cqs": pl.Int8,  # Credit Quality Step 1-6
    "pd": pl.Float64,  # Probability of Default (for internal ratings)
    "rating_date": pl.Date,
    "is_solicited": pl.Boolean,
}


# =============================================================================
# MAPPING SCHEMAS
# =============================================================================

FACILITY_MAPPING_SCHEMA = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,  # facility, loan, contingent
}

ORG_MAPPING_SCHEMA = {
    "parent_counterparty_reference": pl.String,
    "child_counterparty_reference": pl.String,
}

LENDING_MAPPING_SCHEMA = {
    "parent_counterparty_reference": pl.String,
    "child_counterparty_reference": pl.String,
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

SOVEREIGN_RISK_WEIGHT_SCHEMA = {
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