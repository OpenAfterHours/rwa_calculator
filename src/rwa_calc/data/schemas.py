"""
This module contains all the schemas for all data inputs for the rwa_calc.

Supports both UK CRR (Basel 3.0, until Dec 2026) and PRA PS9/24 (Basel 3.1, from Jan 2027).

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

Output Schemas:
- Calculation_output        # Full RWA calculation results with complete audit trail
                            # Includes: classification, EAD breakdown, CRM impact, risk weights,
                            # IRB parameters, hierarchy tracing, floor impact, and data quality flags

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
    "risk_type": pl.String,  # Mandatory: FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # Optional: A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
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
    "risk_type": pl.String,  # Mandatory: FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # Optional: A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # N/A for loans (null), included for unified schema
}

CONTINGENTS_SCHEMA = {
    "contingent_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "beel": pl.Float64,
    "seniority": pl.String,  # senior, subordinated - affects F-IRB LGD (45% vs 75%)
    "risk_type": pl.String,  # Mandatory: FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # Optional: A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
}

COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,  # corporate, individual, sovereign, institution, etc.
    "country_code": pl.String,
    "annual_revenue": pl.Float64,  # For SME classification (£440m large corp, £50m SME)
    "total_assets": pl.Float64,  # Alternative to revenue for large corporate threshold (CRE30.6)
    "default_status": pl.Boolean,
    "sector_code": pl.String,  # Based on SIC
    # Entity type flags for exposure class determination (CRR Art 107, 112-118)
    "is_financial_institution": pl.Boolean,  # Credit institution, investment firm (CRE20.16)
    "is_regulated": pl.Boolean,  # Prudentially regulated institution (affects RW)
    "is_pse": pl.Boolean,  # Public Sector Entity - may receive sovereign or institution RW (CRR Art 116)
    "is_mdb": pl.Boolean,  # Multilateral Development Bank - 0% RW if on eligible list (CRR Art 117)
    "is_international_org": pl.Boolean,  # International Organisation - 0% RW (CRR Art 118)
    "is_central_counterparty": pl.Boolean,  # CCP exposure treatment (CRR Art 300-311)
    "is_regional_govt_local_auth": pl.Boolean,  # RGLA - may receive sovereign RW (CRR Art 115)
    "is_managed_as_retail": pl.Boolean,  # SME managed on pooled retail basis (CRR Art 123)
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
# FX RATES SCHEMA
# =============================================================================

FX_RATES_SCHEMA = {
    "currency_from": pl.String,   # Source currency (e.g., "USD")
    "currency_to": pl.String,     # Target currency (e.g., "GBP")
    "rate": pl.Float64,           # Multiply source amount by rate to get target amount
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
    "undrawn_amount": pl.Float64,  # Undrawn commitment (limit - drawn for facilities)
    "nominal_amount": pl.Float64,  # Total nominal (for contingents)
    "lgd": pl.Float64,  # Internal LGD estimate (if available)
    "beel": pl.Float64,  # Best estimate expected loss
    "seniority": pl.String,  # senior, subordinated
    "risk_type": pl.String,  # FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    # FX conversion audit trail (populated after FX conversion)
    "original_currency": pl.String,       # Currency before FX conversion
    "original_amount": pl.Float64,        # Amount before FX conversion (drawn + nominal)
    "fx_rate_applied": pl.Float64,        # Rate used (null if no conversion needed)
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
    "undrawn_amount": pl.Float64,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "seniority": pl.String,
    "risk_type": pl.String,  # FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    # Counterparty hierarchy additions
    "counterparty_has_parent": pl.Boolean,
    "parent_counterparty_reference": pl.String,
    "ultimate_parent_reference": pl.String,
    "counterparty_hierarchy_depth": pl.Int8,
    # Rating inheritance
    "rating_inherited": pl.Boolean,
    "rating_source_counterparty": pl.String,
    "rating_inheritance_reason": pl.String,
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
    "undrawn_amount": pl.Float64,
    "seniority": pl.String,
    "risk_type": pl.String,  # FR, MR, MLR, LR - determines CCF (CRR Art. 111)
    "ccf_modelled": pl.Float64,  # A-IRB modelled CCF (0.0-1.0)
    "is_short_term_trade_lc": pl.Boolean,  # Short-term LC for goods movement - 20% CCF under F-IRB (Art. 166(9))
    # Classification additions
    "exposure_class": pl.String,  # sovereign, institution, corporate, retail, etc.
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
    "ead_after_guarantee": pl.Float64,
    # Final EAD
    "final_ead": pl.Float64,
    # LGD determination
    "lgd_type": pl.String,  # "supervisory" or "modelled"
    "lgd_value": pl.Float64,  # LGD for calculation
    "lgd_floor": pl.Float64,  # Applicable floor (Basel 3.1)
    "lgd_floored": pl.Float64,  # max(lgd_value, lgd_floor)
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
    "exposure_type": pl.String,  # "loan", "facility", "contingent"
    "counterparty_reference": pl.String,  # Links to counterparty
    "book_code": pl.String,  # Portfolio/book classification
    "currency": pl.String,  # Exposure currency
    "basel_version": pl.String,  # "3.0" or "3.1"

    # -------------------------------------------------------------------------
    # COUNTERPARTY HIERARCHY (Rating Inheritance)
    # -------------------------------------------------------------------------
    "counterparty_has_parent": pl.Boolean,  # Whether counterparty is part of org hierarchy
    "parent_counterparty_reference": pl.String,  # Immediate parent in org structure
    "ultimate_parent_reference": pl.String,  # Top-level parent (for group-level analysis)
    "counterparty_hierarchy_depth": pl.Int8,  # Levels from ultimate parent (0=top)
    "rating_inherited": pl.Boolean,  # Whether rating came from parent
    "rating_source_counterparty": pl.String,  # Counterparty whose rating was used
    "rating_inheritance_reason": pl.String,  # "own_rating", "parent_rating", "group_rating", "unrated"

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
    "exposure_class": pl.String,  # Determined class (central_govt, institution, corporate, retail, etc.)
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

    # -------------------------------------------------------------------------
    # CRM - GUARANTEE IMPACT (Substitution approach)
    # -------------------------------------------------------------------------
    "guarantee_references": pl.List(pl.String),  # IDs of guarantees used
    "guarantor_references": pl.List(pl.String),  # Guarantor counterparty IDs
    "guarantee_coverage_pct": pl.Float64,  # % of exposure guaranteed
    "guaranteed_amount": pl.Float64,  # Amount covered by guarantee
    "guarantor_risk_weight": pl.Float64,  # RW of guarantor (for substitution)
    "guarantee_benefit": pl.Float64,  # RWA reduction from guarantee

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
    "sl_slotting_category": pl.String,  # strong/good/satisfactory/weak/default
    "sl_risk_weight": pl.Float64,  # Slotting RW
    "equity_type": pl.String,  # Equity category if applicable
    "equity_risk_weight": pl.Float64,  # Equity RW

    # -------------------------------------------------------------------------
    # REAL ESTATE SPECIFIC
    # -------------------------------------------------------------------------
    "property_type": pl.String,  # residential/commercial
    "property_ltv": pl.Float64,  # Loan-to-value ratio
    "ltv_band": pl.String,  # LTV band for RW lookup
    "is_income_producing": pl.Boolean,  # CRE income flag
    "is_adc": pl.Boolean,  # ADC exposure flag
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
    # EXPECTED LOSS (IRB comparison to provisions)
    # -------------------------------------------------------------------------
    "irb_expected_loss": pl.Float64,  # PD × LGD × EAD
    "provision_held": pl.Float64,  # Total provision amount
    "el_shortfall": pl.Float64,  # max(0, EL - provision)
    "el_excess": pl.Float64,  # max(0, provision - EL)

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

# Basel 3.1 (PRA PS9/24) specific output fields
# These fields track Basel 3.1-specific treatments
BASEL31_OUTPUT_SCHEMA_ADDITIONS = {
    "regulatory_framework": pl.String,  # "BASEL_3_1"
    "b31_effective_date": pl.Date,  # 1 January 2027
    # Output floor (CRE99.1-8, PS9/24 Ch.12)
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
    # Differentiated PD floors (CRE30.55, PS9/24 Ch.5)
    "b31_pd_floor_class": pl.String,  # Exposure class for PD floor
    "b31_pd_floor_value": pl.Float64,  # 0.03% (corp), 0.05% (retail), 0.10% (QRRE)
    "b31_pd_floor_binding": pl.Boolean,  # Whether PD floor was binding
    # A-IRB LGD floors (CRE30.41, PS9/24 Ch.5)
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
