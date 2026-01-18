"""
This module contains all the schemas for all data inputs for the rwa_calc.

Supports both UK CRR (Basel 3.0, until Dec 2026) and PRA PS9/24 (Basel 3.1, from Jan 2027).

Key Data Inputs:
- Loan                      # Drawn exposures (leaf nodes in exposure hierarchy)
- Facility                  # Committed credit limits (parent nodes) with seniority, commitment_type
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
    "is_revolving": pl.Boolean,
    "seniority": pl.String,  # senior, subordinated - affects F-IRB LGD (45% vs 75%)
    "commitment_type": pl.String,  # unconditionally_cancellable, committed_other - affects CCF (0%/10% vs 40%/75%)
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
    "seniority": pl.String,  # senior, subordinated - affects F-IRB LGD (45% vs 75%)
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
    "seniority": pl.String,  # senior, subordinated - affects F-IRB LGD (45% vs 75%)
}

COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,  # corporate, individual, sovereign, institution, etc.
    "country_code": pl.String,
    "annual_revenue": pl.Float64,  # For SME classification (£440m large corp, £50m SME)
    "total_assets": pl.Float64,  # Alternative to revenue for large corporate threshold (CRE30.6)
    "default_status": pl.Boolean,
    "sector_code": pl.String,  # Industry classification for specialised lending, correlation adjustments
    # Entity type flags for exposure class determination (CRR Art 107, 112-118)
    "is_financial_institution": pl.Boolean,  # Credit institution, investment firm (CRE20.16)
    "is_regulated": pl.Boolean,  # Prudentially regulated institution (affects RW)
    "is_pse": pl.Boolean,  # Public Sector Entity - may receive sovereign or institution RW (CRR Art 116)
    "is_mdb": pl.Boolean,  # Multilateral Development Bank - 0% RW if on eligible list (CRR Art 117)
    "is_international_org": pl.Boolean,  # International Organisation - 0% RW (CRR Art 118)
    "is_central_counterparty": pl.Boolean,  # CCP exposure treatment (CRR Art 300-311)
    "is_regional_govt_local_auth": pl.Boolean,  # RGLA - may receive sovereign RW (CRR Art 115)
}

COLLATERAL_SCHEMA = {
    "collateral_reference": pl.String,
    "collateral_type": pl.String,  # cash, gold, equity, bond, real_estate, receivables, other_physical
    "currency": pl.String,
    "maturity_date": pl.Date,
    "market_value": pl.Float64,
    "nominal_value": pl.Float64,
    "beneficiary_type": pl.String,  # counterparty/loan/facility/contingent
    "beneficiary_reference": pl.String,  # reference to find on the above tables
    # For securities collateral - haircut determination (CRE22.52-53)
    "issuer_cqs": pl.Int8,  # Credit Quality Step of issuer (1-6) for haircut lookup
    "issuer_type": pl.String,  # sovereign, pse, corporate, securitisation - for haircut table
    "residual_maturity_years": pl.Float64,  # For haircut bands: <=1yr, 1-3yr, 3-5yr, 5-10yr, >10yr
    # Eligibility flags
    "is_eligible_financial_collateral": pl.Boolean,  # Meets SA eligibility (CRR Art 197, CRE22.40)
    "is_eligible_irb_collateral": pl.Boolean,  # Meets IRB eligibility - wider pool (CRR Art 199)
    # Valuation requirements (CRE22.75-78)
    "valuation_date": pl.Date,  # Date of last valuation
    "valuation_type": pl.String,  # market, indexed, independent - RE must be independent
    # Real estate specific fields (CRE20.71-87)
    "property_type": pl.String,  # residential, commercial - different RW tables
    "property_ltv": pl.Float64,  # Loan-to-value ratio for SA RW lookup (20%-70% bands)
    "is_income_producing": pl.Boolean,  # Material income dependence affects commercial RE RW
    "is_adc": pl.Boolean,  # Acquisition/Development/Construction - 150% RW unless pre-sold
    "is_presold": pl.Boolean,  # ADC pre-sold to qualifying buyer - 100% RW
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

# Specialised Lending exposures - slotting approach (CRE33.1-8, PS9/24 Ch.5)
# These are corporate exposures with specific risk characteristics requiring separate treatment
SPECIALISED_LENDING_SCHEMA = {
    "exposure_reference": pl.String,  # Links to facility/loan reference
    "sl_type": pl.String,  # project_finance, object_finance, commodities_finance, ipre
    "slotting_category": pl.String,  # strong, good, satisfactory, weak, default
    "remaining_maturity_years": pl.Float64,  # <2.5yr gets reduced RW for strong/good categories
    "is_hvcre": pl.Boolean,  # High-volatility commercial real estate (higher RW)
    # Supervisory risk weights by category (CRE33.5):
    # strong: 70% (50% if <2.5yr), good: 90% (70% if <2.5yr),
    # satisfactory: 115%, weak: 250%, default: 0%
}

# Equity exposures - must use SA under Basel 3.1 (CRE20.58-62, CRR Art 133)
# IRB approaches for equity withdrawn under PRA PS9/24
EQUITY_EXPOSURE_SCHEMA = {
    "exposure_reference": pl.String,
    "counterparty_reference": pl.String,
    "equity_type": pl.String,  # listed, unlisted, private_equity, ciu, other
    "currency": pl.String,
    "carrying_value": pl.Float64,  # Balance sheet value
    "fair_value": pl.Float64,  # For mark-to-market positions
    # Classification flags affecting risk weight
    "is_speculative": pl.Boolean,  # Speculative unlisted equity - 400% RW
    "is_exchange_traded": pl.Boolean,  # Listed on recognised exchange - 100% RW
    "is_government_supported": pl.Boolean,  # Certain govt-supported programmes - reduced RW
    "is_significant_investment": pl.Boolean,  # >10% of CET1 - may require deduction
    # Risk weight: 100% (listed), 250% (unlisted), 400% (speculative)
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