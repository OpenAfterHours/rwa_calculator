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
    "contract_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.Date,
    "limit": pl.Date,
    "committed": pl.Boolean,
    "lgd": pl.Float64,
    "beel": pl.Float64,
}

LOAN_SCHEMA = {
    "loan_reference": pl.String,
    "contract_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.Date,
    "amount": pl.Float64,
    "lgd": pl.Float64,
    "beel": pl.Float64,
}

CONTINGENTS_SCHEMA = {
    "contingents_reference": pl.String,
    "contract_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.Date,
    "amount": pl.Float64,
    "lgd": pl.Float64,
    "beel": pl.Float64,
    "off_balance_sheet": pl.Boolean,
}

COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
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

}

RATINGS_SCHEMA = {

}