"""
Input schemas, categorical constraints, and reference-data tables for rwa_calc.

Supports both UK CRR (Basel 3.0, until Dec 2026) and PRA PS1/26 (Basel 3.1, from Jan 2027).

Pipeline position:
    DataSource -> Loader (validates against these schemas) -> HierarchyResolver

Key responsibilities:
- Declare frozen ColumnSpec schemas for every input bundle (Loan, Facility, ...)
- Declare the VALID_* enum sets and COLUMN_VALUE_CONSTRAINTS (the input-validation
  map built from them) consumed by validate_bundle_values to catch invalid input
  values early; engine/** may not redeclare these string collections (arch_check check 6)
- Declare the column-shape of the reference / lookup tables (risk weights, CCFs,
  haircuts, LGD/PD floors). NOTE: shape declarations only — the regulatory VALUES
  now live in the rulepack packs (rwa_calc/rulebook/packs/{common,crr,b31}.py) and
  are read through the resolved pack, not from these dicts
- Declare the Calculation_output schema (full RWA audit trail)

Key Data Inputs:
- Loan                      # Drawn exposures (leaf nodes in exposure hierarchy)
- Facility                  # Committed credit limits (parent nodes) with seniority, risk_type
- Contingents               # Off-balance sheet commitments with CCF category
- Counterparty              # Borrower/obligor with entity flags (PSE, MDB, institution, etc.)
- Collateral                # Security items with RE-specific fields (LTV, property type, ADC);
                            # linked to its beneficiary via beneficiary_type/beneficiary_reference
- Collateral_links          # Optional M:N side table splitting one collateral item across many
                            # beneficiaries (sub-limit + priority); FK to Collateral. Logical key
                            # (collateral_reference, beneficiary_type, beneficiary_reference) (Art. 230-231)
- Guarantee                 # Guarantees and credit protection; linked via beneficiary_type/beneficiary_reference
- Provision                 # IFRS 9 provisions/impairments (SCRA, GCRA); linked via beneficiary_type/beneficiary_reference
- Ratings                   # Internal and external credit ratings; linked to counterparty via counterparty_reference
- Specialised_lending       # Slotting approach for PF, OF, CF, IPRE (CRE33)
- Equity_exposure           # Equity holdings - SA only under Basel 3.1 (CRE20.58-62)
- CIU_holdings              # Fund look-through holdings for the CIU look-through approach (Art. 132)
- FX_rates                  # Currency conversion table (currency_from, currency_to, rate)

Counterparty Credit Risk (CCR) Inputs:
- Trade                     # OTC derivative / long-settlement row for SA-CCR (Art. 271-279a).
                            # Carries asset_class, notional, MtM, supervisory delta, option / CDO
                            # inputs, the client-cleared-to-QCCP flag (is_client_cleared, Art. 307),
                            # and the specific-WWR flag. SFTs are NOT carried here since the
                            # SFT/FCCM split — see SFT_trade below
- Netting_set               # Per-netting-set row with legal-enforceability flag (Art. 295),
                            # margined / unmargined toggle, large-NS / illiquid-collateral MPOR
                            # cascade inputs (Art. 285), and general-WWR flag
- Margin_agreement          # ISDA CSA-level row (threshold, MTA, NICA, MPOR, segregation) —
                            # separable from netting set so one CSA can cover multiple sets
- CCR_collateral            # CCR-specific collateral keyed by netting_set_id (vs the
                            # exposure-keyed Collateral schema); haircut lookup via Art. 224
- DF_contribution           # Optional clearing-member default-fund contribution to a (Q)CCP;
                            # is_qccp_ccp discriminates the Art. 308 (QCCP) vs Art. 309
                            # (non-QCCP) capital branch

Securities Financing Transaction (SFT) Inputs:
- SFT_trade                 # Lean SFT row (RawDataBundle.sft) priced via the Financial
                            # Collateral Comprehensive Method (Art. 271(2), 220-223). Carries the
                            # Art. 223(5) exposure-side volatility-haircut (HE) inputs first-class
                            # and the netting-set counterparty denormalised onto the trade
                            # (single-trade-NS scope, Art. 220(1)(a)); optional margined / MPOR flags
- SFT_collateral            # Optional SFT collateral keyed by netting_set_id; market_value +
                            # Art. 224 haircut (HC/HFX) inputs feeding the FCCM E* formula

CVA Risk Inputs (Basel 3.1 / PS1/26 only — BA-CVA):
- CVA_counterparty          # Optional BA-CVA counterparty row (sector x credit-quality RW_c,
                            # M_NS); gates BA-CVA inclusion via cva_in_scope (PS1/26 CVA Part Ch.4)
- CVA_hedge                 # Optional BA-CVA single-name / index CDS hedge feeding K_hedged
                            # (correlation band, RW_h, M_h, notional B_h); PS1/26 CVA Part Ch.4

Settlement Risk Inputs:
- Failed_trade              # One row per failed DvP or non-DvP free-delivery settlement
                            # (Art. 378 Table 1 / Art. 379 Table 2); reserves Art. 379(2)-(3)
                            # and Art. 380 elective flags (immateriality, CET1 deduction,
                            # system-wide failure waiver)

Securitisation:
- Securitisation_allocation # Many-to-one flag mapping originated exposures to securitisation
                            # pools; allocated portion is excluded from standard credit-risk
                            # RWA totals (Art. 244-246 significant risk transfer); SEC-SA /
                            # SEC-IRBA / SEC-ERBA framework itself remains out of scope

Mappings:
- Facility_mappings         # Mappings between Facilities, Loans and Contingents
- Org_mapping               # Mapping between counterparties (parents to children) for rating/turnover inheritance
- Lending_mapping           # Mapping between connected counterparties for Retail threshold aggregation
- Exposure_class_mapping    # Mapping of counterparty/exposure attributes to SA/IRB exposure classes

  Note: ratings, collateral, provisions and guarantees do NOT use standalone
  *_mapping tables. Ratings link to their counterparty via a counterparty_reference
  column on the Ratings schema; collateral / provision / guarantee each link to
  their beneficiary via embedded beneficiary_type + beneficiary_reference columns
  (constrained by VALID_BENEFICIARY_TYPES). The only standalone collateral side
  table is the optional M:N Collateral_links frame above.

Reference/Lookup Data (column-shape declarations only — VALUES live in the rulepack
packs, read via the resolved pack; not consumed from these dicts):
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

Configuration (column-shape declarations; runtime config is the CalculationConfig dataclass):
- IRB_permissions           # Which exposure classes can use IRB (SA/FIRB/AIRB)
- Model_permissions         # Per-model approach + geography / book-code scoping
                            # (model_id, exposure_class, approach, country_codes,
                            # excluded_book_codes)
- Calculation_config        # Basel version toggle (3.0 vs 3.1), reporting date

Output Schemas:
- Calculation_output        # Full RWA calculation results with complete audit trail
                            # Includes: classification, EAD breakdown, CRM impact, risk weights,
                            # IRB parameters, hierarchy tracing, floor impact, and data quality flags

Intermediate Pipeline-Stage Schemas (emitted mid-pipeline; consumed downstream
via ``ensure_columns``; not user inputs):
- Hierarchy_output          # ``cp_*`` columns joined from counterparty data during hierarchy resolution
- CRM_output                # Collateral buckets + provision allocations after the CRM stage (Art. 111(2), 127)
- Classifier_output         # SME / retail / RE / SL flags + LTV + RE loan-split candidate flags
- RE_splitter_output        # ``split_parent_id`` + ``re_split_role`` rows from the real-estate splitter

References:
- CRR Art. 110: Treatment of credit risk adjustments (basis for Provision schema)
- CRR Art. 111: Exposure value and CCF basis (basis for Contingents schema)
- CRR Art. 112-134: SA exposure classes (basis for exposure-class enums)
- CRR Art. 132: CIU look-through approach (basis for CIU_holdings schema)
- CRR Art. 147-153: IRB approach assignment (basis for approach/permission enums)
- CRR Art. 153(5): Specialised-lending slotting categories (PF, OF, CF, IPRE)
- CRR Art. 197-200: Eligible collateral types (basis for collateral_type enum)
- CRR Art. 213-217: Eligible guarantor types (basis for guarantor_type enum)
- CRR Art. 220-223: Financial Collateral Comprehensive Method (basis for SFT_trade / SFT_collateral)
- CRR Art. 223-230: Collateral valuation / supervisory haircut categories
- CRR Art. 230-231: Collateral substitution / sequential allocation (basis for Collateral_links)
- CRR Art. 244-246: Securitisation significant risk transfer (basis for Securitisation_allocation)
- CRR Art. 271(2): SFT exposure value via FCCM under the CCR framework (basis for SFT_trade)
- CRR Art. 271-279a: SA-CCR scope and exposure-value methodology (basis for Trade schema)
- CRR Art. 272(7), 285(5): Margin agreement (CSA) parameters (basis for Margin_agreement schema)
- CRR Art. 285, 295: MPOR cascade and netting-set legal enforceability (basis for Netting_set schema)
- CRR Art. 291: Wrong-way risk flags (general + specific) on Trade / Netting_set
- CRR Art. 306-307: QCCP proprietary vs client-cleared routing (``is_client_cleared``)
- CRR Art. 308-309: CCP default-fund contribution capital (basis for DF_contribution)
- CRR Art. 378-380: Settlement risk treatment (basis for Failed_trade schema)
- CRR Art. 501 / 501a: SME and infrastructure supporting-factor eligibility fields
- PRA PS1/26 (Basel 3.1): LTV bands, ADC flag, IPRE flags, equity SA-only treatment
  (CRE20.58-62), and revised SA input fields effective 1 Jan 2027
- PRA PS1/26 CVA Part Ch.4: Basic Approach for CVA (BA-CVA) — basis for CVA_counterparty / CVA_hedge
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
    # CRR Art. 111(1) / Annex I items 2(b),3(b): original maturity (years) of an
    # "other commitment" (OC). The SA CCF engine keys the 50% (MR, original > 1yr)
    # / 20% (MLR, original <= 1yr) split on ORIGINAL — not residual — maturity.
    # Nullable; when absent the engine falls back to (maturity_date - value_date),
    # else the conservative 50% MR default. Mirrors the nullable
    # original_maturity_years on GUARANTEE_SCHEMA / COLLATERAL_SCHEMA.
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    # CRR Art. 114(4)/(7) via Art. 235(3): funding currency of any undrawn
    # exposure this facility generates. See LOAN_SCHEMA.funding_currency for the
    # full null-PERMISSIVE semantics (falls back to the denomination currency).
    "funding_currency": ColumnSpec(pl.String, required=False),
    "limit": ColumnSpec(pl.Float64, required=False),
    "committed": ColumnSpec(pl.Boolean, default=True, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "is_revolving": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qrre_transactor": ColumnSpec(pl.Boolean, default=False, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "risk_type": ColumnSpec(pl.String, required=False),
    "underlying_risk_type": ColumnSpec(pl.String, required=False),
    # CRR Annex I paras 1-4 / Art. 111(1): a normalised concrete OBS product key
    # (e.g. "ACCEPTANCE", "PERFORMANCE_BOND", "DOCUMENTARY_CREDIT"), distinct from
    # the free-text ``product_type``. When ``risk_type`` is null/empty the CCF
    # engine resolves the abstract Annex I risk_type bucket from this product via
    # ANNEX1_PRODUCT_RISK_TYPE. Explicit ``risk_type`` always wins.
    "obs_product": ColumnSpec(pl.String, required=False),
    "ccf_modelled": ColumnSpec(pl.Float64, required=False),
    "ead_modelled": ColumnSpec(pl.Float64, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 166(8)(d) vs Art. 166(10): True for credit lines / NIFs / RUFs
    # (75% F-IRB CCF), False for issued OBS items (Art. 166(10) — 50% MR / 20% MLR).
    # Facilities default to True because a facility row is, by construction, a
    # commitment / credit line.
    "is_obs_commitment": ColumnSpec(pl.Boolean, default=True, required=False),
    # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): commitments to extend credit
    # secured by residential property attract a 50% CCF. When True under Basel
    # 3.1 the CCF engine overrides the otherwise-resolved SA CCF to the MR /
    # Row 4(b) rate (50%), unless that CCF is already 10% or 100% (the Row 4(b)
    # "not subject to a 10% or 100% conversion factor" carve-out). No effect
    # under CRR (Table A1 is Basel 3.1 only).
    "is_uk_residential_mortgage_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 166E(5): undrawn purchase commitments for *revolving*
    # purchased-receivables facilities attract a 40% CCF by default (Table A1
    # Row 5 "Other Commitments"), dropping to 10% where the commitment also
    # meets the Table A1 Row 7 UCC criteria (LR risk_type). When True under
    # Basel 3.1 the CCF engine routes the row to the OC (40%) / LR (10%) rate
    # regardless of the otherwise-resolved risk_type. No effect under CRR
    # (Art. 166E(5) is Basel 3.1 only).
    "is_purchased_receivable_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_buy_to_let": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 178 row-level default flag. When True, the exposure is routed
    # through the Art. 153(1)(ii) / 154(1)(i) defaulted IRB treatment (or the
    # Art. 127 SA defaulted branch) even if the counterparty's
    # ``default_status`` is False — supports the case of a single defaulted
    # facility on an otherwise-performing obligor. The counterparty-level
    # ``default_status`` propagates to every exposure of that counterparty
    # regardless of this flag.
    "is_defaulted": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 124(3) / Art. 124K: True when the financed property is
    # under construction. Drives the ADC ("Acquisition, Development and
    # Construction") classification path in the classifier. Combined with the
    # corporate (non-natural-person) gate, a True value derives is_adc=True so
    # the SA branch routes to the 150% Art. 124K(1) ADC risk weight.
    "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "facility_termination_date": ColumnSpec(pl.Date, required=False),
    # Art. 162(3) / PS1/26: explicit numeric M override (years). When populated it
    # supersedes the maturity_date-derived M and bypasses the 1-year floor —
    # firm-owned judgement for short-term carve-outs.
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
    # PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased-receivables F-IRB LGD routing.
    # Null for non-purchased-receivables exposures (default). When set, takes
    # precedence over the seniority-based LGD selector:
    #   "senior"        -> Art. 161(1)(e) LGD = 40% (B3.1) / 45% (CRR)
    #   "subordinated"  -> Art. 161(1)(f) LGD = 100%
    #   "dilution_risk" -> Art. 161(1)(g) LGD = 100% (B3.1) / 75% (CRR)
    "purchased_receivables_subtype": ColumnSpec(pl.String, required=False),
}

LOAN_SCHEMA: dict[str, ColumnSpec] = {
    "loan_reference": ColumnSpec(pl.String),
    "product_type": ColumnSpec(pl.String, required=False),
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "counterparty_reference": ColumnSpec(pl.String),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    # CRR Art. 114(4)/(7) via Art. 235(3): the currency in which the exposure is
    # FUNDED. The 0% domestic-CGCB extension to a centrally-guaranteed exposure
    # requires the exposure to be BOTH denominated AND funded in the guarantor's
    # domestic currency. Distinct from ``currency`` (the denomination): a loan can
    # be denominated in one currency yet funded in another. Null-PERMISSIVE — when
    # absent the funding-currency limb falls back to the exposure's denomination
    # currency (engine/eu_sovereign.funding_currency_expr), preserving datasets
    # that do not report a separate funding currency (mirrors the Art. 237(2)(a)
    # original-maturity null fallback).
    "funding_currency": ColumnSpec(pl.String, required=False),
    "drawn_amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "interest": ColumnSpec(pl.Float64, default=0.0, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_buy_to_let": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 178 row-level default flag. See FACILITY_SCHEMA for full notes.
    "is_defaulted": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 124(3) / Art. 124K: True when the financed property is
    # under construction — drives the ADC classification derivation in the
    # classifier (combined with a corporate / non-natural-person gate).
    "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 195/219 on-balance-sheet netting. A non-null reference is the sole
    # signal that the exposure participates in a netting agreement: a deposit
    # (negative drawn amount) and the loans it offsets net iff they carry the SAME
    # reference. Netting is driven exclusively by this reference — never by
    # facility hierarchy or counterparty — reflecting the legal right of set-off.
    "netting_agreement_reference": ColumnSpec(pl.String, required=False),
    "due_diligence_performed": ColumnSpec(pl.Boolean, default=False, required=False),
    "due_diligence_override_rw": ColumnSpec(pl.Float64, required=False),
    # PRA PS1/26 Art. 123B(2) / CRE20.93: loan-level hedge flag that suppresses
    # the 1.5x retail/RE currency-mismatch multiplier when True. Defaults to
    # False (unhedged — multiplier fires under FX mismatch).
    "is_hedged": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 123B(2): hedge coverage proportion (0.0-1.0). When >= 0.90
    # the loan is treated as fully hedged and the 1.5x currency-mismatch
    # multiplier is suppressed even if ``is_hedged`` is False. Defaults to 0.0
    # (no hedge coverage — multiplier fires under FX mismatch unless is_hedged).
    "hedge_coverage_ratio": ColumnSpec(pl.Float64, default=0.0, required=False),
    # PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased-receivables F-IRB LGD routing.
    # Null for non-purchased-receivables exposures (default). When set, takes
    # precedence over the seniority-based LGD selector:
    #   "senior"        -> Art. 161(1)(e) LGD = 40% (B3.1) / 45% (CRR)
    #   "subordinated"  -> Art. 161(1)(f) LGD = 100%
    #   "dilution_risk" -> Art. 161(1)(g) LGD = 100% (B3.1) / 75% (CRR)
    "purchased_receivables_subtype": ColumnSpec(pl.String, required=False),
    # CRR Art. 159(1) Pool B components (c)/(d): additional value adjustments
    # (AVAs per Art. 34/105) and other own funds reductions associated with the
    # exposure. Enter the per-exposure Pool B exactly once at the IRB EL
    # shortfall stage (engine/irb/adjustments.py compute_el_shortfall_excess);
    # hierarchy passes them through from the loan row. Null (not 0.0) when
    # unreported — absence of data must not imply a zero AVA.
    "ava_amount": ColumnSpec(pl.Float64, required=False),
    "other_own_funds_reductions": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 223(5) FCCM exposure volatility haircut (HE) inputs. Populated when
    # the exposure itself is a debt security (typical for SFTs where the firm lends
    # out a bond — the bond carries its own price-volatility risk on the exposure
    # side). Null/cash/standard loan exposures derive HE = 0. The same Art. 224
    # Table 1 used for HC governs HE — keyed off these three fields.
    "exposure_collateral_type": ColumnSpec(pl.String, required=False),
    "exposure_security_cqs": ColumnSpec(pl.Int8, required=False),
    "exposure_security_residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 124-126 / PRA PS1/26 Art. 124C-124K: loan-level real-estate
    # inputs for exposures whose LTV / property data live on the loan row
    # rather than a separate collateral row (e.g. CRE Art. 126(2)(d)
    # proportion-split scenarios). HierarchyResolver passes these through to
    # the unified exposure frame; without them the SA real-estate branch
    # cannot route the exposure. Null (never 0.0 / "") when unreported —
    # absence of data must not fabricate an LTV or a property type.
    "ltv": ColumnSpec(pl.Float64, required=False),
    "property_type": ColumnSpec(pl.String, required=False),
    # CRR Art. 126(2): the preferential 50% CRE risk weight requires
    # demonstrated income cover (rental income >= 1.5x interest payments).
    # Unknown defaults to False — without evidence the preferential treatment
    # is withheld (conservative), matching the engine's fill_null(False)
    # handling and the CLASSIFIER_OUTPUT_SCHEMA default.
    "has_income_cover": ColumnSpec(pl.Boolean, default=False, required=False),
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
    # CRR Art. 111(1) / Annex I items 2(b),3(b): OC original maturity (years).
    # Mirrored from FACILITY_SCHEMA; see the FACILITY_SCHEMA notes for full detail.
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    "currency": ColumnSpec(pl.String, required=False),
    # CRR Art. 114(4)/(7) via Art. 235(3): funding currency of this contingent
    # exposure. See LOAN_SCHEMA.funding_currency for the full null-PERMISSIVE
    # semantics (falls back to the denomination currency).
    "funding_currency": ColumnSpec(pl.String, required=False),
    "nominal_amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "lgd": ColumnSpec(pl.Float64, required=False),
    "lgd_unsecured": ColumnSpec(pl.Float64, required=False),
    "has_sufficient_collateral_data": ColumnSpec(pl.Boolean, default=False, required=False),
    "beel": ColumnSpec(pl.Float64, required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "risk_type": ColumnSpec(pl.String, required=False),
    "underlying_risk_type": ColumnSpec(pl.String, required=False),
    # CRR Annex I paras 1-4 / Art. 111(1): normalised concrete OBS product key.
    # Mirrored from FACILITY_SCHEMA; when ``risk_type`` is null/empty the CCF
    # engine resolves the Annex I risk_type bucket from this product via
    # ANNEX1_PRODUCT_RISK_TYPE. Explicit ``risk_type`` always wins.
    "obs_product": ColumnSpec(pl.String, required=False),
    "ccf_modelled": ColumnSpec(pl.Float64, required=False),
    "ead_modelled": ColumnSpec(pl.Float64, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 166(8)(d) vs Art. 166(10): contingent rows are issued OBS items by
    # default (False -> Art. 166(10) fallback: 50% MR / 20% MLR / 100% FR / 0% LR).
    # Override to True for genuine commitment-style contingents (e.g., an
    # NIF / RUF booked as a contingent), in which case Art. 166(8)(d) -> 75% applies.
    "is_obs_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): commitments to extend credit
    # secured by residential property attract a 50% CCF. Mirrored from
    # FACILITY_SCHEMA for parity; see the FACILITY_SCHEMA notes for full detail.
    "is_uk_residential_mortgage_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 166E(5): revolving purchased-receivables undrawn purchase
    # commitment flag. Mirrored from FACILITY_SCHEMA for parity; see the
    # FACILITY_SCHEMA notes for full detail.
    "is_purchased_receivable_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 178 row-level default flag. See FACILITY_SCHEMA for full notes.
    "is_defaulted": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 124(3) / Art. 124K: True when the financed property is
    # under construction — drives the ADC classification derivation in the
    # classifier (combined with a corporate / non-natural-person gate).
    "is_under_construction": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 126(2): preferential 50% CRE RW requires demonstrated income
    # cover. Mirrored from LOAN_SCHEMA so contingent rows carry the same
    # unknown->False conservative default; see the LOAN_SCHEMA notes.
    "has_income_cover": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_sft": ColumnSpec(pl.Boolean, default=False, required=False),
    "effective_maturity": ColumnSpec(pl.Float64, required=False),
    "bs_type": ColumnSpec(pl.String, default="OFB", required=False),
    "due_diligence_performed": ColumnSpec(pl.Boolean, default=False, required=False),
    "due_diligence_override_rw": ColumnSpec(pl.Float64, required=False),
    # PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased-receivables F-IRB LGD routing.
    # Null for non-purchased-receivables exposures (default). When set, takes
    # precedence over the seniority-based LGD selector:
    #   "senior"        -> Art. 161(1)(e) LGD = 40% (B3.1) / 45% (CRR)
    #   "subordinated"  -> Art. 161(1)(f) LGD = 100%
    #   "dilution_risk" -> Art. 161(1)(g) LGD = 100% (B3.1) / 75% (CRR)
    "purchased_receivables_subtype": ColumnSpec(pl.String, required=False),
    # CRR Art. 223(5) FCCM exposure volatility haircut (HE) inputs — see
    # LOAN_SCHEMA for full notes. Mirrored on contingents for symmetry with
    # the loans schema; populated only when the contingent exposure is itself
    # a debt security under an SFT.
    "exposure_collateral_type": ColumnSpec(pl.String, required=False),
    "exposure_security_cqs": ColumnSpec(pl.Int8, required=False),
    "exposure_security_residual_maturity_years": ColumnSpec(pl.Float64, required=False),
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
    # PRA PS1/26 Art. 124E(1)(b): count of residential properties securing the
    # borrower's total residential RE exposure (including the financed one). When
    # this count exceeds the three-property limit, the owner-occupied preferential
    # treatment is disapplied and the exposure routes to the income-producing
    # residential track (Art. 124G). Null = unknown (no income-producing re-route).
    "qualifying_property_count": ColumnSpec(pl.Int32, required=False),
    "is_social_housing": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_financial_sector_entity": ColumnSpec(pl.Boolean, default=False, required=False),
    "scra_grade": ColumnSpec(pl.String, required=False),
    "is_investment_grade": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_ccp_client_cleared": ColumnSpec(pl.Boolean, required=False),
    "borrower_income_currency": ColumnSpec(pl.String, required=False),
    "sovereign_cqs": ColumnSpec(pl.Int32, required=False),
    "local_currency": ColumnSpec(pl.String, required=False),
    "institution_cqs": ColumnSpec(pl.Int8, required=False),
    # CRR Art. 137(1)-(2) Table 9: nominated ECA's minimum export insurance
    # premium (MEIP) score 0-7 used as a direct sovereign risk-weight input
    # when no ECAI rating is available. Null when ECA path is not used.
    "eca_score": ColumnSpec(pl.Int8, required=False),
    # CRR Art. 227(3) / PRA PS1/26 Art. 227(3): True when the counterparty is
    # enumerated as a core market participant (sovereigns/CBs eligible for 0%
    # RW under Art. 114, supervised institutions and investment firms, certain
    # insurance undertakings, regulated CIUs subject to capital requirements,
    # regulated pension funds, recognised clearing organisations). Drives the
    # Art. 222(4) FCSM SFT carve-out: 0% RW (CMP) vs 10% RW (non-CMP).
    # Defaults to False (conservative — non-CMP treatment).
    "is_core_market_participant": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 272 Def (88) / PRA PS1/26 Art. 306: True when the counterparty
    # is a qualified central counterparty (QCCP). Drives the Art. 306(1) 2%
    # trade-exposure RW (and the Art. 307 4% client-cleared route). Defaults
    # to False so pre-existing fixtures route to the non-QCCP / SA fallback.
    "is_qccp": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 274(2) second sub-paragraph: SA-CCR supervisory-alpha discriminator.
    # "financial" (default) → alpha = 1.4; "non_financial" (EMIR Art. 2(9)),
    # "pension_scheme" (EMIR Art. 2(10)) and "pension_default_comp" → alpha = 1.0
    # carve-out. Read by engine/ccr/pipeline_adapter.py to compute the per-row
    # ``alpha_applied`` scalar. Defaults to "financial" so pre-existing CCR
    # fixtures (which never set this column) keep the standard alpha = 1.4.
    "counterparty_type": ColumnSpec(pl.String, default="financial", required=False),
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
    # CRR / PS1-26 Art. 197(1)(h): a securitisation position is eligible financial
    # collateral only if it is NOT a resecuritisation AND its own risk weight is
    # <= 100%. These two fields drive that gate for issuer_type/collateral_type
    # "securitisation" (dedicated Art. 224 Table 1 supervisory-haircut column).
    #   is_resecuritisation: True => hard-ineligible (Art. 197(1)(h)). The default
    #     False means "NOT KNOWN to be a resecuritisation", not "confirmed plain
    #     securitisation" — RESIDUAL RISK: a genuine resecuritisation posted
    #     without this flag set is wrongly recognised. Unlike the RW/CQS gate
    #     (conservative on null), resecuritisation cannot be inferred from other
    #     fields, so the correct signal must be supplied by the data provider.
    #   securitisation_position_risk_weight: the position's own RW as a fraction
    #     (e.g. 0.20 = 20%). Null is CONSERVATIVE — the RW<=100% gate cannot be
    #     confirmed, so the position is treated as ineligible (absence of data
    #     must not fabricate eligibility). Only consulted for securitisation rows.
    "is_resecuritisation": ColumnSpec(pl.Boolean, default=False, required=False),
    "securitisation_position_risk_weight": ColumnSpec(pl.Float64, required=False),
    # PRA PS1/26 Art. 191A(2)(d)-(f): two-layer protection look-through.
    # Optional reference to the counterparty that posted the collateral (e.g.
    # the guarantor for guarantee-anchored collateral). When the engine
    # honours an Art. 191A(2)(e)(i) "funded-only" election, the collateral is
    # re-anchored from the guarantee onto the original obligor exposure.
    "posted_by_counterparty_reference": ColumnSpec(pl.String, required=False),
    # CRR/PS1-26 Art. 200(a)/232(2) with Art. 212(1) (P1.239/P1.240): cash on
    # deposit with (or cash-assimilated instruments held by) a THIRD-PARTY
    # institution, pledged to the lender, is "other funded credit protection" —
    # treated as a GUARANTEE by the deposit-holding institution (its own SA risk
    # weight substitutes on the covered part), NOT as own-bank cash at a 0%
    # haircut. This optional reference identifies that holder institution; the
    # deposit row's issuer_type/issuer_cqs describe the holder (a cash deposit is
    # a claim on the institution holding it), so the holder's institution RW is
    # derived from issuer_cqs. NULL is PERMISSIVE = own-bank deposit → the
    # existing 0% cash treatment is preserved (the overwhelmingly common case, so
    # existing datasets are unaffected). Populated => third-party: the row is
    # excluded from every 0% cash-collateral value channel (SA E*, FIRB LGD*) and
    # instead drives the SA risk-weight substitution. FIRB substitution is a
    # deferred follow-up — under FIRB a third-party deposit currently gives NO
    # benefit (conservative) and raises CRM017.
    "held_by_counterparty_reference": ColumnSpec(pl.String, required=False),
    # CRR/PS1-26 Art. 194(4): funded protection is ineligible where its value is
    # materially positively correlated with the obligor's credit quality — the
    # canonical case (BCBS CRE22) being a security ISSUED by the obligor or a
    # group member. This optional reference identifies the counterparty that
    # ISSUED the collateral security (distinct from posted_by_counterparty_reference,
    # which is who PROVIDED it). When it resolves to the obligor or a counterparty
    # sharing the obligor's ultimate parent, the CRM engine zeroes the row and
    # raises CRM015. Null is PERMISSIVE (issuer unknown / not an issued security,
    # e.g. cash on deposit) — the gate never fires, so existing data is unaffected.
    "issuer_counterparty_reference": ColumnSpec(pl.String, required=False),
    # CRR Art. 181 / CRE36 / Basel 3.1 Art. 169A: AIRB own LGD already reflects
    # the collateral effect, so collateral incorporated into the firm's internal
    # LGD model must not contribute CRM benefit to non-AIRB exposures of the
    # same counterparty (otherwise double-counted). When True, the row is
    # routed only to AIRB exposures whose modelled LGD is preserved.
    "is_airb_model_collateral": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 224 Table 4 / PRA PS1/26: distinguishes main-index equity (15%
    # haircut CRR / 20% Basel 3.1) from other listed equity (25% / 30%). No
    # Boolean default on purpose: null means "index membership unreported" and
    # the haircut engine (engine/crm/haircuts.py) resolves null -> other-listed
    # equity (the higher, CONSERVATIVE haircut) per P1.237/P1.271 — CRR/PS1-26
    # Art. 197(1)(f)/198(1)(a): only main-index equities earn the cheaper
    # all-methods treatment, so unknown membership must not fabricate it.
    "is_main_index": ColumnSpec(pl.Boolean, required=False),
    # CRR Art. 198(1)(a) / PRA PS1/26 Art. 198(1)(a): a non-main-index equity (or
    # convertible bond) is eligible financial collateral only if it is traded on a
    # recognised exchange, i.e. LISTED — and then only under the comprehensive
    # method this calculator uses by default. Main-index equities are eligible
    # under all methods regardless (Art. 197(1)(f)), so this flag is only consulted
    # for equity that is NOT attested main-index. No Boolean default on purpose:
    # null means "listing status unreported" and the haircut engine
    # (engine/crm/haircuts.py) resolves null -> not listed -> INELIGIBLE (the
    # conservative default; absence of data must not fabricate eligibility). Per
    # P1.271 — CRR/PS1-26 Art. 197(1)(f)/198(1)(a).
    "is_listed": ColumnSpec(pl.Boolean, required=False),
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
    # CRR Art. 226(1) / PRA PS1/26 Art. 226(1): non-daily mark-to-market or
    # non-daily-remargining adjustment. When N_R > 1 the supervisory haircut
    # is scaled by sqrt((N_R + T_m - 1) / T_m) where T_m is the liquidation
    # period in business days. Null is treated as daily revaluation (N_R=1)
    # with no scaling applied.
    "revaluation_frequency_days": ColumnSpec(pl.Int32, required=False),
    "qualifies_for_zero_haircut": ColumnSpec(pl.Boolean, default=False, required=False),
    "insurer_risk_weight": ColumnSpec(pl.Float64, required=False),
    "credit_event_reduction": ColumnSpec(pl.Float64, default=0.0, required=False),
}

# Optional M:N linkage of one collateral item to multiple beneficiaries.
#
# COLLATERAL_SCHEMA carries a single ``beneficiary_reference`` per row. When a
# physical pledge backs several facilities/loans, the firm supplies this side
# table instead: the collateral row defines the finite value once, and each
# link row names one beneficiary it may protect. The CRM stage then splits the
# finite value across the linked beneficiaries for the most beneficial RWA
# impact (engine/crm/link_allocation.py). Entirely additive — a corpus with no
# collateral_links table behaves exactly as the single-beneficiary path.
#
# Many-to-one with collateral: multiple rows share a ``collateral_reference``.
# Logical key = (collateral_reference, beneficiary_type, beneficiary_reference).
#
# References:
# - CRR Art. 193/194/207: CRM eligibility and recognition conditions
# - CRR Art. 230-231: substitution / sequential allocation of collateral
COLLATERAL_LINK_SCHEMA: dict[str, ColumnSpec] = {
    # FK to COLLATERAL_SCHEMA primary key. The finite value lives on that row.
    "collateral_reference": ColumnSpec(pl.String),
    # One of VALID_BENEFICIARY_TYPES. Direct types (exposure/loan/contingent)
    # resolve on exposure_reference; "facility"/"counterparty" resolve on the
    # pooled parent reference, mirroring the collateral cascade.
    "beneficiary_type": ColumnSpec(pl.String),
    "beneficiary_reference": ColumnSpec(pl.String),
    # Optional per-link sub-limit (e.g. a legal cap on how much of this item may
    # protect this beneficiary). Null = bounded only by the item's finite value.
    "max_pledge_amount": ColumnSpec(pl.Float64, required=False),
    # Optional manual fill order (lower = filled first). Null = engine ranks by
    # pre-CRM RWA density (greedy most-beneficial allocation).
    "priority": ColumnSpec(pl.Int32, required=False),
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
    # CRR Art. 237(2)(a): original maturity of unfunded credit protection.
    # A guarantee with original_maturity_years < 1.0 is ineligible. Null is
    # treated permissively (defaulted to >= 1y) — mirrors the collateral
    # original_maturity_years fallback in engine/crm/haircuts.py.
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    # CRR / PS1-26 Art. 213(1)(c)(i): unfunded credit protection eligibility.
    # A guarantee the protection provider can unilaterally CANCEL is ineligible
    # under both regimes; one whose terms the provider can unilaterally CHANGE
    # (increasing the effective cost of protection) is additionally ineligible
    # under Basel 3.1 only (the "or change" words are new in PS1/26, gated by
    # the ucp_unilateral_change_ineligible pack Feature). Both flags are
    # null-PERMISSIVE — a null means "no known defect => eligible", mirroring
    # the Art. 237(2)(a) original_maturity_years fallback above: no default is
    # declared, so apply_boolean_column_defaults leaves nulls untouched.
    "is_unilaterally_cancellable": ColumnSpec(pl.Boolean, required=False),
    "is_unilaterally_changeable": ColumnSpec(pl.Boolean, required=False),
    # Seniority of the guarantor's claim drives F-IRB supervisory LGD selection
    # in PSM (parameter substitution) — Art. 161(1)(a)/(aa)/(b). Allowed
    # values: "senior", "subordinated". Engine treats missing as "senior".
    "guarantor_seniority": ColumnSpec(pl.String, required=False),
    # PRA PS1/26 Art. 191A(2)(d)-(f): two-layer protection look-through.
    # Flags a guarantee whose obligation is itself collateralised by the
    # guarantor (e.g. cash pledged against the guarantee).  When True and
    # ``look_through_election`` is "funded_only", the engine suppresses
    # the guarantee row (no Art. 235 RWSM substitution) and re-anchors the
    # guarantor-posted collateral directly onto the original obligor exposure.
    "is_collateralised_by_guarantor": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 191A(2)(e)(i): election on how to recognise the
    # two-layer protection. Allowed values:
    #   "none"        — default; recognise the guarantee normally (no look-through).
    #   "funded_only" — recognise ONLY the funded collateral; suppress the
    #                   guarantee and re-anchor the collateral on the obligor.
    #   "both"        — out of scope for the current implementation; treated
    #                   as "none" with a CRM warning.
    "look_through_election": ColumnSpec(pl.String, default="none", required=False),
    # CRR Art. 234: tranching of credit protection. When a guarantee protects a
    # mezzanine loss band rather than first loss, ``attachment_amount`` (a) marks
    # where protection begins and ``detachment_amount`` (d) where it ends. The
    # obligor retains a first-loss tranche [0, a) and a senior tranche [d, EAD]
    # at its own risk weight, while [a, d) is substituted to the guarantor. Null
    # on both => first-loss attach (a = 0), preserving legacy single-remainder
    # behaviour.
    "attachment_amount": ColumnSpec(pl.Float64, required=False),
    "detachment_amount": ColumnSpec(pl.Float64, required=False),
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
    # PRA PS1/26 Art. 120(2B) Table 4A / Art. 122(3) Table 6A: short-term ECAI
    # assessments are issue-specific (attached to a particular exposure, not the
    # counterparty as a whole). ``is_short_term=True`` flags this rating row as
    # such; ``scope_type`` / ``scope_id`` identify which exposure it attaches to.
    # When ``is_short_term=False`` the rating applies counterparty-wide (legacy
    # behaviour) and the two scope columns must be null.
    "is_short_term": ColumnSpec(pl.Boolean, default=False, required=False),
    "scope_type": ColumnSpec(pl.String, required=False),
    "scope_id": ColumnSpec(pl.String, required=False),
    # PRA PS1/26 Art. 139(2B): inferred / issuer-level (non-issue-specific) ECAI
    # assessments are disapplied for the SA specialised-lending routing under
    # Art. 122B(1). These provenance flags let the engine distinguish a directly
    # applicable issue-specific rating from one inferred from a related entity.
    # Defaults preserve legacy behaviour: existing ratings are treated as
    # directly applicable (issue-specific) and not inferred.
    "rating_is_issue_specific": ColumnSpec(pl.Boolean, default=True, required=False),
    "rating_is_inferred": ColumnSpec(pl.Boolean, default=False, required=False),
    # Firm-supplied internal rating grade (COREP Annex II, C 08.02 obligor grade
    # scale). Free-text firm master-scale label; no COLUMN_VALUE_CONSTRAINTS entry.
    "internal_rating_grade": ColumnSpec(pl.String, required=False),
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
    # Number of years the underlying business has existed.
    # Used by Basel 3.1 PE/VC higher-risk test (PRA PS1/26 Glossary p.5,
    # Art. 133(4)): unlisted PE with business_age_years < 5.0 (or null,
    # treated conservatively) routes to 400%; >= 5.0 routes to standard 250%.
    "business_age_years": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 155(3): True -> institution has sufficient Art. 178 default-
    # definition data, so the 1.5x PD/LGD scaling does NOT apply. False/null ->
    # the 1.5x scaling applies. Skipping the scaling is the preferential
    # treatment and requires affirmative attestation, so unknown -> False
    # (apply the 1.5x — conservative). Recorded FIX decision 2026-06-12:
    # the previous default=True made the code contradict this very comment.
    "has_default_definition_info": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 155(2) non-trading-book short-position netting inputs.
    # position_value: signed market value (+long / -short). When absent the
    #   equity calculator falls back to the fair_value/carrying_value/ead chain
    #   (every position stands alone on its absolute value).
    # issuer_reference: netting key — same string means the same individual
    #   stock (Art. 155(2) permits netting only within one issuer). Null -> no
    #   netting for that row.
    # is_explicitly_hedged: True -> the offsetting short is an explicit hedge
    #   covering at least one year, so it may net the matching long. Default
    #   False -> the short is treated as a standalone long on its absolute value.
    "position_value": ColumnSpec(pl.Float64, required=False),
    "issuer_reference": ColumnSpec(pl.String, required=False),
    "is_explicitly_hedged": ColumnSpec(pl.Boolean, default=False, required=False),
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
    # ppu_reason absent → null. Identifies the legal basis for an SA-routed
    # (approach="standardised") permission: any CRR Art. 150(1)(a)-(j) permanent
    # partial use condition, or Art. 148 sequential IRB roll-out. Provenance-only
    # — drives COREP C 07.00 / OF 07.00 Section 1 rows 0050/0060 (PpuReason enum).
    "ppu_reason": ColumnSpec(pl.String, required=False),
}


# =============================================================================
# SECURITISATION ALLOCATIONS SCHEMA
# =============================================================================
# User-supplied flag mapping originated exposures to securitisation pools.
# Phase 1 scope: flag + exclude from standard credit-risk RWA totals. The
# securitisation RWA framework itself (SEC-SA, SEC-IRBA, SEC-ERBA — CRR
# Art. 259-264 / PS1/26 Art. 261-264) is out of scope.
#
# Many-to-one with exposures: a single exposure_reference may have multiple
# rows when the exposure is split across more than one pool. The sum of
# allocation_pct values for the same exposure must satisfy
# ``sum(pct) <= 1.0``; the residual (1 - sum) flows on-balance-sheet.
#
# References:
# - CRR Art. 109: gateway to securitisation framework
# - CRR Art. 244-246: significant risk transfer (originator's right to exclude)
# - PRA PS1/26 Art. 147A(1)(j): securitisation positions restricted from IRB
SECURITISATION_ALLOCATION_SCHEMA: dict[str, ColumnSpec] = {
    # Native key on the source table (loan_reference / contingent_reference /
    # facility_reference). Discriminated by ``exposure_type``.
    "exposure_reference": ColumnSpec(pl.String),
    # One of {"loan", "contingent", "facility"}. Validated by
    # COLUMN_VALUE_CONSTRAINTS["securitisation_allocations"]["exposure_type"].
    "exposure_type": ColumnSpec(pl.String),
    # Free-text pool / SPV identifier. No enum — pool universes are firm-
    # specific and may include synthetic / traditional pools of varying types.
    "pool_reference": ColumnSpec(pl.String),
    # Fraction of the exposure transferred to this pool. Each row must be in
    # ``(0, 1]``; per-exposure sums must be in ``[0, 1]``.
    "allocation_pct": ColumnSpec(pl.Float64),
    # CRR Art. 244 (traditional) vs Art. 245 (synthetic). Carried for future
    # use by the securitisation RWA framework — not consumed in phase 1.
    "transfer_type": ColumnSpec(pl.String, default="traditional", required=False),
    # SRT assertion by the firm. Phase 1 trusts this flag — the engine does
    # not validate the Art. 244-246 conditions. When False, exposure carve-out
    # is still applied (firm's responsibility to set correctly).
    "significant_risk_transfer": ColumnSpec(pl.Boolean, default=True, required=False),
    "effective_date": ColumnSpec(pl.Date, required=False),
}


# =============================================================================
# COUNTERPARTY CREDIT RISK (CCR) INPUT SCHEMAS — P8.5
# =============================================================================
# Four parquet-backed input tables consumed by the SA-CCR pipeline (P8.20+).
# Held under ``RawDataBundle.ccr`` as a ``RawCCRBundle`` composite; entirely
# optional at the firm level — firms without derivative or SFT books leave
# ``RawDataBundle.ccr = None`` and the CCR stage no-ops.
#
# References:
# - CRR Art. 271 (CCR scope — derivatives, repos, SFTs, long-settlement)
# - CRR Art. 272(4) (netting set), 272(7) (margin agreement), 272(9) (MPOR)
# - CRR Art. 275(1)-(2) (replacement cost — V, C)
# - CRR Art. 285(2)(b) (10 business-day MPOR minimum)
# - CRR Art. 295-297 (contractual netting recognition)

#: Trade-level input for SA-CCR (OTC derivatives / long-settlement trades).
#: One row per derivative trade. Consumed by the ``ccr_sa_ccr`` derivative
#: stage. SFTs are NOT carried here since the SFT/FCCM separation — securities
#: financing transactions have their own lean ``SFT_TRADE_SCHEMA`` input
#: (``RawDataBundle.sft``), priced by the peer ``sft_fccm`` FCCM stage
#: (CRR Art. 271(2), Art. 220-223).
TRADE_SCHEMA: dict[str, ColumnSpec] = {
    # Required (8) — primary key + core economic terms.
    "trade_id": ColumnSpec(pl.String),
    "netting_set_id": ColumnSpec(pl.String),
    # "interest_rate" | "fx" | "credit" | "equity" | "commodity"
    "asset_class": ColumnSpec(pl.String),
    # "derivative" — REQUIRED on every CCR (derivative) trade row. The "sft"
    # value remains valid in VALID_TRANSACTION_TYPES (the guard detects it), but
    # SFT rows belong in SFT_TRADE_SCHEMA / RawDataBundle.sft, not here — a "sft"
    # row reaching this frame is flagged CCR020 and excluded from the Art. 274
    # chain. See partition_out_sft_rows (engine/ccr/pipeline_adapter.py).
    "transaction_type": ColumnSpec(pl.String),
    "notional": ColumnSpec(pl.Float64),
    "currency": ColumnSpec(pl.String),
    "maturity_date": ColumnSpec(pl.Date),
    "start_date": ColumnSpec(pl.Date),
    # Optional with defaults (3).
    # CRR Art. 279a(1) supervisory delta — defaults to 1.0 for non-option
    # directional trades. Options carry a separate computed delta.
    "delta": ColumnSpec(pl.Float64, default=1.0, required=False),
    "is_long": ColumnSpec(pl.Boolean, default=True, required=False),
    # CRR Art. 275 replacement cost: V (current market value). Defaulted to
    # 0.0 (at-par trade) — conservative for typical IRS / vanilla derivatives.
    "mtm_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    # Optional with default (4th) — long-settlement flag.
    "is_long_settlement": ColumnSpec(pl.Boolean, default=False, required=False),
    # Optional nullable (3) — schema-present for richer trade types added later.
    "underlying_reference": ColumnSpec(pl.String, required=False),
    "option_strike": ColumnSpec(pl.Float64, required=False),
    # Optional nullable (4) — option/CDO supervisory delta inputs (CRR Art. 279a(2)/(3)).
    # option_type: "call" | "put" — null for non-option trades.
    # option_underlying_price: current price of the underlying (P in Black-Scholes Φ(d1)).
    # cdo_attachment: attachment point A of a CDO tranche (0 ≤ A < D ≤ 1); null if not CDO.
    # cdo_detachment: detachment point D of a CDO tranche (0 ≤ A < D ≤ 1); null if not CDO.
    "option_type": ColumnSpec(pl.String, required=False),
    "option_underlying_price": ColumnSpec(pl.Float64, required=False),
    "cdo_attachment": ColumnSpec(pl.Float64, required=False),
    "cdo_detachment": ColumnSpec(pl.Float64, required=False),
    "payment_leg_index_id": ColumnSpec(pl.String, required=False),
    # CRR Art. 307: True when the trade is client-cleared through a clearing
    # member to a QCCP — routes the trade exposure to the 4% RW branch (vs.
    # the 2% proprietary branch in Art. 306(1)). Trade-level (not CP-level)
    # because Art. 307 keys on the trade's clearing relationship. Defaults to
    # False so pre-existing fixtures route to the proprietary/non-QCCP branch.
    "is_client_cleared": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 291(1)(b)/(4)-(5): specific wrong-way risk flag. When True,
    # ``engine/ccr/wwr.py::apply_wwr_gate`` breaks the trade out into its own
    # single-trade synthetic netting set (id ``<original>__wwr__<trade_id>``)
    # and assigns ``wwr_lgd_override = 1.0`` to that synthetic NS.
    "is_specific_wwr": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 279b(1)(b): FX-derivative second-leg notional and ISO-4217
    # currency. Required when ``asset_class == "fx"`` — the FX adjusted-notional
    # branch converts both legs to ``CalculationConfig.base_currency`` at spot
    # and applies the one-leg-is-base / max(both-foreign) rule. Null for non-FX
    # trades (interest_rate uses the single ``notional`` / ``currency`` pair).
    "notional_leg2": ColumnSpec(pl.Float64, required=False),
    "currency_leg2": ColumnSpec(pl.String, required=False),
    # P8.33 — equity / credit / commodity asset-class hedging-set columns.
    # All nullable: only populated for the relevant asset_class; null for
    # interest_rate / fx rows. Consumed downstream by P8.34-P8.37 (per-asset-class
    # add-on calculators) — see ``data/tables/sa_ccr_factors.py`` for the
    # supervisory factor / correlation lookups keyed by these columns.
    #
    # CRR Art. 279b(1)(c) / CRE52.45: equity & commodity adjusted notional is
    # ``d = market_price × number_of_units`` (current spot price times share or
    # unit count) rather than the IR / FX notional convention.
    "market_price": ColumnSpec(pl.Float64, required=False),
    "number_of_units": ColumnSpec(pl.Float64, required=False),
    # CRR Art. 277(2)(c)-(d) / CRE52.60: credit & equity hedging sets are
    # partitioned by issuer reference (single-name LEI) or index ticker. Used
    # by the per-entity correlation step (Art. 280a / 280b).
    "reference_entity": ColumnSpec(pl.String, required=False),
    # CRR Art. 277(3)(b) / CRE52.67: commodity hedging sets are partitioned
    # into 5 fixed buckets — ELECTRICITY / OIL_GAS / METALS / AGRICULTURAL /
    # OTHER. UPPER-CASE to match ``SA_CCR_SUPERVISORY_FACTORS_COMMODITY``
    # keys in ``data/tables/sa_ccr_factors.py``. See COLUMN_VALUE_CONSTRAINTS.
    "commodity_type": ColumnSpec(pl.String, required=False),
    # CRR Art. 280c / CRE52.68: the individual commodity reference within a
    # bucket (e.g. a specific power product or delivery hub). Trades that share
    # a ``commodity_reference`` are fully netted into one effective notional
    # ``D_k`` BEFORE the within-bucket ρ=0.40 aggregation — mirroring how
    # ``reference_entity`` partitions the credit / equity add-ons. Free-text
    # (no COLUMN_VALUE_CONSTRAINTS entry). Nullable: when null the commodity
    # add-on falls back to per-trade (``trade_id``) granularity, preserving the
    # pre-existing behaviour for inputs that do not populate the column.
    "commodity_reference": ColumnSpec(pl.String, required=False),
    # CRR Art. 280a / 280b / CRE52.61: discriminator for single-name vs index
    # in credit / equity asset classes. Default None (not False) — null means
    # "not applicable" (IR / FX / commodity rows); False would be a load-bearing
    # "single-name" claim for credit / equity rows.
    "is_index": ColumnSpec(pl.Boolean, required=False),
    # CRR Art. 280 Table 2: credit-quality discriminator for the credit asset
    # class supervisory factor lookup. Valid values {"IG", "HY", "NON_RATED"};
    # null for non-credit rows (IR / FX / equity / commodity). Keyed by
    # COLUMN_VALUE_CONSTRAINTS["trades"]["credit_quality"] for input validation.
    "credit_quality": ColumnSpec(pl.String, required=False),
    # PRA PS1/26 Art. 274(2A): firm-supplied legacy CVA-exemption flag. True
    # when the trade was entered into prior to 1 Jan 2027 AND the counterparty
    # is one of those listed in the CVA Risk Part 7.1(1)(a)/(b) (the
    # non-financial / pension-scheme / intragroup CVA-exempt cohort). When True
    # the netting set qualifies for the transitional alpha add-on (phased
    # 60%/40%/20% of the (α=1.4 − α=1.0) × (RC+PFE) uplift across 2027-2029).
    # Conservative default False — pre-2027 fixtures and the Python-bundle path
    # see no transitional add-on. See SA_CCR_TRANSITIONAL_ADDON_PHASE in
    # data/tables/sa_ccr_factors.py.
    "is_legacy_cva_exempt": ColumnSpec(pl.Boolean, default=False, required=False),
    # IRB effective-maturity (Art. 162) input flags (3) — CCR/SFT IRB
    # effective-maturity fix Phase 2. SA-CCR derivatives are IN SCOPE for the
    # carrier (an internally-rated CP routes the synthetic CCR_DERIVATIVE row to
    # FIRB/AIRB and hits the Art. 162 chain). Mirror of the SFT_TRADE_SCHEMA
    # flags — CARRY-ONLY this phase; the producer (engine/ccr/pipeline_adapter.py)
    # reads them in Phase 3 alongside the NS-grain margining cascade
    # (_attach_mpor_cascade_inputs, which sources is_margined /
    # remargining_frequency_days from NETTING_SET_SCHEMA / MARGIN_AGREEMENT_SCHEMA,
    # not from this trade schema). All three are Boolean (no
    # COLUMN_VALUE_CONSTRAINTS entry needed) and default conservatively to False:
    # an absent flag NEVER unlocks a sub-1y floor, so a derivative omitting them
    # falls to the Art. 162(2)(f) / 162(2A)(f) 1-year catch-all.
    #
    # under_master_netting_agreement: Art. 162(2) MNA precondition for any sub-1y
    # floor. (CRR Art. 162(2); PS1/26 Art. 162(2A).)
    "under_master_netting_agreement": ColumnSpec(pl.Boolean, default=False, required=False),
    # qualifies_one_day_maturity_floor: all three Art. 162(3) conditions
    # conjunctively (daily re-margin AND revaluation AND prompt-liquidation docs).
    # (CRR Art. 162(3); PS1/26 Art. 162(3).)
    "qualifies_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    # qualifies_mna_intermediate_floor: B31 Art. 162(2A)(c)/(d) "daily re-margin
    # OR revaluation AND prompt-liquidation" documentation condition gating the
    # 5BD/10BD intermediate floors UNDER B31 ONLY (unused under CRR, where the
    # 5BD/10BD apply on MNA alone). (PS1/26 Art. 162(2A)(c)/(d).)
    "qualifies_mna_intermediate_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    # Own-estimate LGD carrier for A-IRB routing of the synthetic SA-CCR
    # derivative row (P1.215, mirrors ``ccr_effective_maturity`` / the SFT
    # sibling on SFT_TRADE_SCHEMA). Null (the common case) => no modelled LGD =>
    # the row routes to SA / FIRB, bit-identical to today.
    # (CRR Art. 143 / Art. 169-171: own-estimate LGD under A-IRB.)
    "ccr_modelled_lgd": ColumnSpec(pl.Float64, required=False),
}

#: Netting-set-level input for SA-CCR. One row per netting set keyed by
#: ``netting_set_id``. Carries legal-enforceability flag (Art. 295) and the
#: denormalised margin parameters consumed by the margined Replacement Cost
#: formula (P8.11) — null in the unmargined CCR-A1 case.
NETTING_SET_SCHEMA: dict[str, ColumnSpec] = {
    # Required (2).
    "netting_set_id": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String),
    # Optional with defaults (2).
    # CRR Art. 295: a netting set is only recognised for capital relief if
    # the bank can demonstrate legal enforceability in each relevant
    # jurisdiction. Conservative default: False (no netting benefit until
    # legality confirmed).
    "is_legally_enforceable": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_margined": ColumnSpec(pl.Boolean, default=False, required=False),
    # Optional nullable (6) — margined RC / MF parameters; null when
    # ``is_margined`` is False.
    "netting_agreement_type": ColumnSpec(pl.String, required=False),
    "margin_threshold": ColumnSpec(pl.Float64, required=False),
    "minimum_transfer_amount": ColumnSpec(pl.Float64, required=False),
    "nica": ColumnSpec(pl.Float64, required=False),
    "mpor_days": ColumnSpec(pl.Int32, required=False),
    "margin_agreement_id": ColumnSpec(pl.String, required=False),
    # Optional with defaults (2) — consumed by the margined maturity-factor
    # (Art. 279c(2)) MPOR cascade (Art. 285(3)(b) and Art. 285(4)).
    # ``number_of_trades``: netting-set trade count used to determine whether
    # the large-netting-set 20-day MPOR floor applies (Art. 285(3)(b):
    # threshold > 5000 trades).  Null-safe default 0 means no large-NS uplift
    # when the count is unknown, consistent with the conservative-default
    # pattern elsewhere in this schema.
    "number_of_trades": ColumnSpec(pl.Int32, default=0, required=False),
    # ``has_illiquid_collateral_or_hard_to_replace_otc``: True when the
    # netting set contains illiquid collateral or hard-to-replace OTC trades
    # per Art. 285(3)(b), triggering the 20-day MPOR floor regardless of
    # trade count.  Conservative default: False (no uplift when unknown).
    "has_illiquid_collateral_or_hard_to_replace_otc": ColumnSpec(
        pl.Boolean, default=False, required=False
    ),
    # CRR Art. 291(1)(a) / 291(6): general wrong-way risk flag. Conservative
    # default False — flips ``engine/ccr/wwr.py::apply_wwr_gate`` into emitting
    # a CCR011 WARNING for the netting set.
    "has_general_wwr_flag": ColumnSpec(pl.Boolean, default=False, required=False),
    # CRR Art. 291(5)(c): LGD override applied by the WWR gate to synthetic
    # single-trade netting sets carved out for specific WWR. Null on regular
    # netting sets; set to 1.0 by the gate on the synthetic NS row.
    "wwr_lgd_override": ColumnSpec(pl.Float64, default=None, required=False),
}

#: Margin-agreement-level (CSA) input for SA-CCR. Separate from
#: ``NETTING_SET_SCHEMA`` so a single ISDA CSA covering multiple netting
#: sets can be represented without denormalisation. Empty (zero-row) frame
#: is the unmargined case.
MARGIN_AGREEMENT_SCHEMA: dict[str, ColumnSpec] = {
    # Required (2).
    "margin_agreement_id": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String),
    # Optional with defaults (5).
    "margin_threshold": ColumnSpec(pl.Float64, default=0.0, required=False),
    "minimum_transfer_amount": ColumnSpec(pl.Float64, default=0.0, required=False),
    "nica": ColumnSpec(pl.Float64, default=0.0, required=False),
    # CRR Art. 285(2)(b): minimum Margin Period of Risk for standard margined
    # netting sets is 10 business days. Default to the regulatory minimum so
    # SA-CCR PFE add-on uses it when ``mpor_days`` is not explicitly supplied.
    "mpor_days": ColumnSpec(pl.Int32, default=10, required=False),
    "is_segregated_im": ColumnSpec(pl.Boolean, default=False, required=False),
    # Optional nullable (3).
    "remargining_frequency_days": ColumnSpec(pl.Int32, required=False),
    "dispute_count_qtr": ColumnSpec(pl.Int32, required=False),
    "governing_law": ColumnSpec(pl.String, required=False),
}

#: CCR-specific collateral input. Keyed by ``netting_set_id`` (structurally
#: different from ``COLLATERAL_SCHEMA`` which is keyed by beneficiary). Haircut
#: lookup reuses the supervisory haircut tables in ``engine/crm/`` (Art. 224).
CCR_COLLATERAL_SCHEMA: dict[str, ColumnSpec] = {
    # Required (3).
    "ccr_collateral_reference": ColumnSpec(pl.String),
    "netting_set_id": ColumnSpec(pl.String),
    "collateral_type": ColumnSpec(pl.String),
    # Optional with defaults (3).
    # CRR Art. 275(1) replacement cost: C (net collateral). Conservative
    # default: 0.0 (no collateral credit when value unknown).
    "market_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "is_posted_by_firm": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_segregated": ColumnSpec(pl.Boolean, default=False, required=False),
    # Optional nullable (5).
    "currency": ColumnSpec(pl.String, required=False),
    "issuer_cqs": ColumnSpec(pl.Int8, required=False),
    "issuer_type": ColumnSpec(pl.String, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    "haircut_override": ColumnSpec(pl.Float64, required=False),
}


# =============================================================================
# SECURITIES FINANCING TRANSACTION (SFT) INPUT SCHEMAS — SFT/FCCM separation
# =============================================================================
# Dedicated, lean input schemas for SFTs priced via the Financial Collateral
# Comprehensive Method (FCCM, CRR Art. 220-223). Today SFTs are tunnelled
# through the SA-CCR ``TRADE_SCHEMA`` / ``CCR_COLLATERAL_SCHEMA`` (discriminated
# by ``transaction_type == "sft"``), carrying ~25 derivative-only columns they
# never use and three HE-input columns that ``TRADE_SCHEMA`` never declared.
# These schemas declare the FCCM input contract first-class so a developer can
# see exactly what an SFT row needs.
#
# Declaration-only at this phase — the loader / bundle / stage wiring lands in
# later phases of docs/plans/sft-fccm-separation.md. The current engine path
# still reads SFT rows out of the shared CCR bundle.
#
# Scope: single-trade, single-counterparty netting sets (Art. 220(1)(a)), so
# the netting-set ``counterparty_reference`` is denormalised onto the trade
# row and no separate SFT netting-set table is needed.
#
# References:
# - CRR Art. 220(1)(a) — single-counterparty SFT / master-netting-set scope
# - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))
# - CRR Art. 224 Table 1 — supervisory haircuts (H_10) by type / CQS / maturity
# - CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274

#: Trade-level FCCM input. One row per SFT (repo / securities-lending). The
#: netting-set counterparty is denormalised onto the trade (single-trade-NS
#: scope, Art. 220(1)(a)) so FCCM needs no separate SFT netting-set table.
#: The ``exposure_*`` columns carry the Art. 223(5) exposure-side volatility
#: haircut (HE) inputs — declared first-class here, where they were previously
#: tunnelled undeclared through ``TRADE_SCHEMA``. Same dtypes as the identically
#: named LOAN_SCHEMA / CONTINGENTS_SCHEMA lending-side declarations.
SFT_TRADE_SCHEMA: dict[str, ColumnSpec] = {
    # Required (7) — primary key + core economic terms + denormalised CP.
    "trade_id": ColumnSpec(pl.String),
    "netting_set_id": ColumnSpec(pl.String),
    # Denormalised from the netting set; becomes the synthetic exposure row's
    # ``counterparty_reference`` and drives the SA institution risk-weight lookup
    # (CRR Art. 120(1) Table 3).
    "counterparty_reference": ColumnSpec(pl.String),
    # E — the exposure amount lent / sold under the SFT (Art. 223(5)).
    "notional": ColumnSpec(pl.Float64),
    "currency": ColumnSpec(pl.String),
    "maturity_date": ColumnSpec(pl.Date),
    "start_date": ColumnSpec(pl.Date),
    # Optional nullable (3) — Art. 223(5) exposure-side HE inputs, keyed into the
    # Art. 224 Table 1 supervisory-haircut lookup. Null when the exposure side is
    # cash / a standard loan (HE = 0; engine treats null as no haircut).
    "exposure_collateral_type": ColumnSpec(pl.String, required=False),
    "exposure_security_cqs": ColumnSpec(pl.Int8, required=False),
    "exposure_security_residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    # Optional margining inputs (5) — SFT/FCCM separation Phase 0b. These make a
    # margined SFT under a qualifying Art. 285(2)-(4) margin agreement
    # REPRESENTABLE. NO engine math reads them yet (carry-only this phase): an
    # SFT row that omits them seals to the unmargined defaults below, so the
    # FCCM E* is bit-identical to today's path. All denormalised onto the trade
    # row (single-CP single-trade NS scope, Art. 220(1)(a)).
    #
    # is_margined: True => this SFT is under a qualifying Art. 285(2)-(4) margin
    # agreement (margined branch (b): T_M = MPOR, Art. 226 non-daily term
    # suppressed). False/absent => unmargined branch (a) = today's behaviour.
    "is_margined": ColumnSpec(pl.Boolean, default=False, required=False),
    # remargining_frequency_days: dual-purpose revaluation/remargin period in
    # business days. Branch (a): N_R feeding the Art. 226 √((N_R+T_M−1)/T_M)
    # term (1 => daily => term 1.0). Branch (b): N feeding Art. 285(5)
    # MPOR = F + N − 1. Default 1 keeps both branches at the daily minimum.
    "remargining_frequency_days": ColumnSpec(pl.Int16, default=1, required=False),
    # mpor_floor_category: selects the Art. 285(2)-(3) floor F (branch (b) only):
    # 'repo_only' => F=5 (Art. 285(2)(a)); 'other' => F=10 (Art. 285(2)(b));
    # 'illiquid_or_large' => F=20 (Art. 285(3)). The actual F is read from cited
    # pack scalars — never hardcoded in engine. Value-constrained via
    # VALID_MPOR_FLOOR_CATEGORIES in COLUMN_VALUE_CONSTRAINTS['sft_trades'].
    "mpor_floor_category": ColumnSpec(pl.String, default="repo_only", required=False),
    # has_margin_dispute_doubling: True => apply the Art. 285(4) doubling of F
    # (> 2 margin-call disputes over the preceding two quarters, each exceeding
    # the applicable MPOR). Pre-computed upstream; the engine does not track
    # quarters. When True: F → 2·F before MPOR = 2F + N − 1.
    "has_margin_dispute_doubling": ColumnSpec(pl.Boolean, default=False, required=False),
    # mpor_days_override: optional explicit MPOR (business days) that SUPERSEDES
    # the F + N − 1 derivation (branch (b) only). Null (the common case) => the
    # engine derives MPOR from the fields above; non-null => used directly as
    # T_M. No default-fill — null is the 'derive me' signal.
    "mpor_days_override": ColumnSpec(pl.Int16, default=None, required=False),
    # IRB effective-maturity (Art. 162) input flags (3) — CCR/SFT IRB
    # effective-maturity fix Phase 2. CARRY-ONLY this phase: declared so a
    # margined / netted SFT routing to FIRB/AIRB is REPRESENTABLE; the producer
    # (engine/sft/fccm.py) and the IRB maturity chain that read them land in
    # Phases 3-4. All three are Boolean — no COLUMN_VALUE_CONSTRAINTS entry is
    # needed (the dtype is the constraint). All default conservatively to False:
    # an absent flag NEVER unlocks a sub-1y maturity floor (anti-conservative
    # trap), so an SFT omitting them falls to the Art. 162(2)(f) / 162(2A)(f)
    # 1-year catch-all — bit-identical to today's behaviour.
    #
    # under_master_netting_agreement: Art. 162(2) MNA precondition. ANY sub-1y
    # maturity floor (one-day, 5BD, 10BD) requires this True; without it the row
    # falls to the 1-year catch-all. (CRR Art. 162(2); PS1/26 Art. 162(2A).)
    "under_master_netting_agreement": ColumnSpec(pl.Boolean, default=False, required=False),
    # qualifies_one_day_maturity_floor: carries ALL THREE Art. 162(3) conditions
    # conjunctively — (i) daily re-margining AND (ii) daily revaluation AND
    # (iii) documentation provisions for prompt liquidation / set-off. True =>
    # the ~1-day (1/365 y) floor is available. Default False: NEVER inferred
    # from remargining_frequency_days (absent ≠ qualifying). (CRR Art. 162(3);
    # PS1/26 Art. 162(3) — the AND condition is unchanged under B31.)
    "qualifies_one_day_maturity_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    # qualifies_mna_intermediate_floor: the B31 Art. 162(2A)(c)/(d) documentation
    # condition — "daily re-margining OR revaluation AND prompt-liquidation /
    # set-off" (note the OR, distinct from 162(3)'s AND) — that gates the
    # 5BD / 10BD intermediate MNA floors UNDER B31 ONLY. Under CRR the 5BD/10BD
    # floors apply on MNA alone (Art. 162(2)(c)/(d): "subject to an MNA" is the
    # only condition), so this flag is unused under CRR; under B31 a repo/deriv
    # under an MNA but lacking it falls to the 162(2A)(f) 1-year catch-all.
    # Default False (conservative). (PS1/26 Art. 162(2A)(c)/(d).)
    "qualifies_mna_intermediate_floor": ColumnSpec(pl.Boolean, default=False, required=False),
    # Own-estimate LGD carrier for A-IRB routing of the synthetic CCR/SFT row
    # (P1.215, mirrors ``ccr_effective_maturity``). A netting-set/trade that
    # routes to A-IRB carries the firm's modelled LGD here — the synthetic
    # ``ccr__<NS>`` row has no lending ``lgd`` of its own, so this dedicated
    # carrier feeds the classifier's ``has_modelled_lgd`` AIRB gate and the IRB
    # LGD selection (engine/irb/transforms.py). Null (the common case) => no
    # modelled LGD => the row falls to SA / FIRB, bit-identical to today.
    # (CRR Art. 143 / Art. 169-171: own-estimate LGD under A-IRB.)
    "ccr_modelled_lgd": ColumnSpec(pl.Float64, required=False),
}

#: Netting-set-keyed collateral received against an SFT, feeding the
#: ``CVA·(1−HC−HFX)`` term of the FCCM E* formula (Art. 223(5)). A lean subset
#: of ``CCR_COLLATERAL_SCHEMA`` — the SA-CCR-only columns (``is_posted_by_firm``,
#: ``is_segregated``, ``issuer_type``, ``haircut_override``) are intentionally
#: dropped. Optional table: an uncollateralised SFT carries no collateral row.
SFT_COLLATERAL_SCHEMA: dict[str, ColumnSpec] = {
    # Required (3).
    "sft_collateral_reference": ColumnSpec(pl.String),
    "netting_set_id": ColumnSpec(pl.String),
    "collateral_type": ColumnSpec(pl.String),
    # Optional with default (1) — CVA (collateral market value) in the E*
    # formula; 0.0 when unknown (no collateral credit).
    "market_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    # Optional nullable (3) — Art. 224 Table 1 HC lookup inputs + the HFX
    # same-currency shortcut (Art. 224 Table 4: HFX = 0 when collateral and
    # exposure currencies match).
    "currency": ColumnSpec(pl.String, required=False),
    "issuer_cqs": ColumnSpec(pl.Int8, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
}

#: Valid values for the CCR/SFT trade discriminator ``transaction_type``
#: (TRADE_SCHEMA). A bad value silently mis-routes an SFT into the SA-CCR
#: Art. 274 chain (≈0 EAD) instead of FCCM (Art. 271(2)), so it is value-
#: constrained via ``COLUMN_VALUE_CONSTRAINTS`` below. Enforced once the CCR/SFT
#: trade frame is wired into ``validate_bundle_values`` (later separation phase).
VALID_TRANSACTION_TYPES: set[str] = {"derivative", "sft"}

#: Valid values for the margined-SFT MPOR floor selector ``mpor_floor_category``
#: (SFT_TRADE_SCHEMA, SFT/FCCM separation Phase 0b). Selects the Art. 285(2)-(3)
#: floor F (branch (b) only): ``repo_only`` => F=5 (Art. 285(2)(a)); ``other`` =>
#: F=10 (Art. 285(2)(b)); ``illiquid_or_large`` => F=20 (Art. 285(3)). A bad value
#: would silently mis-floor the MPOR, so it is value-constrained via
#: ``COLUMN_VALUE_CONSTRAINTS['sft_trades']`` below. The actual F value is read
#: from cited pack scalars in the engine — this set only constrains the input.
VALID_MPOR_FLOOR_CATEGORIES: set[str] = {"repo_only", "other", "illiquid_or_large"}


# =============================================================================
# FAILED-TRADE (SETTLEMENT RISK) INPUT SCHEMA — P8.24
# =============================================================================
# One row per failed settlement (DvP or non-DvP free delivery) consumed by
# ``engine/ccr/failed_trades.py``. Held under an optional leaf bundle on
# ``RawCCRBundle.failed_trades``; absent when the firm has no failed trades.
#
# References:
# - CRR Art. 378 + Table 1: DvP multiplier ladder.
# - CRR Art. 379(1) + Table 2: non-DvP free-delivery treatment.
# - CRR Art. 379(2)-(3): immateriality / CET1-deduction electives (schema
#   reserves the flags; engine currently treats them as no-op false).
# - CRR Art. 380: system-wide failure waiver (schema reserves the flag).

#: Failed-trade input schema. ``settlement_type`` discriminates the two
#: branches: ``"dvp"`` rows require ``agreed_settlement_price`` +
#: ``current_market_value``; ``"non_dvp_free_delivery"`` rows require
#: ``value_transferred`` + ``current_positive_exposure``. Optional booleans
#: default False per Art. 378-380 scope rules.
FAILED_TRADE_SCHEMA: dict[str, ColumnSpec] = {
    # Required (5) — primary key + core settlement attributes.
    "failed_trade_id": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String),
    # "dvp" | "non_dvp_free_delivery"
    "settlement_type": ColumnSpec(pl.String),
    "working_days_past_due": ColumnSpec(pl.Int32),
    # "debt" | "equity" | "fx" | "commodity"
    "instrument_class": ColumnSpec(pl.String),
    # DvP-only (Art. 378 Table 1 inputs) — null for non-DvP rows.
    "agreed_settlement_price": ColumnSpec(pl.Float64, required=False),
    "current_market_value": ColumnSpec(pl.Float64, required=False),
    # Non-DvP-only (Art. 379(1) Table 2 inputs) — null for DvP rows.
    "value_transferred": ColumnSpec(pl.Float64, required=False),
    "current_positive_exposure": ColumnSpec(pl.Float64, required=False),
    # Optional boolean flags — Art. 378-380 scope and election gates.
    # Art. 378 first paragraph: repo / sec-lending exclusion.
    "is_repo_or_sec_lending": ColumnSpec(pl.Boolean, default=False, required=False),
    # Art. 379(2): immateriality carve-out (100% RW alternative).
    "is_immaterial": ColumnSpec(pl.Boolean, default=False, required=False),
    # Art. 379(3): CET1 deduction election.
    "elect_cet1_deduction": ColumnSpec(pl.Boolean, default=False, required=False),
    # Art. 380: system-wide failure waiver.
    "system_wide_failure_waiver": ColumnSpec(pl.Boolean, default=False, required=False),
}


# =============================================================================
# DEFAULT-FUND-CONTRIBUTION (CCP) INPUT SCHEMA — P8.49
# =============================================================================
# One row per clearing-member default-fund contribution consumed by
# ``engine/ccr/default_fund.py``. Held under an optional frame on
# ``RawCCRBundle.default_fund_contributions``; absent when the firm has no
# CCP default-fund contributions.
#
# References:
# - CRR Art. 308(2): K_CCP hypothetical capital + K_CM clearing-member
#   allocation (K_CM = K_CCP x DF_i / DF_CM).
# - CRR Art. 308(3): QCCP pre-funded own-funds (RWEA = K_CM x 12.5).
# - CRR Art. 309(1)/(2): non-QCCP / unfunded treatment (same arithmetic).

#: Default-fund-contribution input schema. ``is_qccp_ccp`` discriminates the
#: Art. 308 (QCCP) vs Art. 309 (non-QCCP) branch; ``is_unfunded_commitment``
#: selects the Art. 309 unfunded leg. The firm supplies ``k_ccp_published``
#: (K_CCP), ``df_i_contribution_amount`` (DF_i) and
#: ``df_cm_total_contributions`` (DF_CM); the engine derives K_CM and RWEA.
#: Optional booleans default False per Art. 308/309 scope rules.
DF_CONTRIBUTION_SCHEMA: dict[str, ColumnSpec] = {
    # Required — primary key + CCP reference.
    "contribution_id": ColumnSpec(pl.String),
    "ccp_reference": ColumnSpec(pl.String),
    # QCCP flag (CRR Art. 272 Def (88)): True -> Art. 308, False -> Art. 309.
    "is_qccp_ccp": ColumnSpec(pl.Boolean, default=False, required=False),
    # Art. 308(2) clearing-member allocation inputs.
    "df_i_contribution_amount": ColumnSpec(pl.Float64),  # DF_i (>= 0)
    "df_cm_total_contributions": ColumnSpec(pl.Float64),  # DF_CM (> 0 — denominator)
    # Art. 308(2) K_CCP supplied by the firm (simulation out of scope).
    "k_ccp_published": ColumnSpec(pl.Float64),  # K_CCP (>= 0)
    # Art. 309 unfunded-commitment flag — meaningful only when is_qccp_ccp=False.
    "is_unfunded_commitment": ColumnSpec(pl.Boolean, default=False, required=False),
}


# =============================================================================
# BA-CVA COUNTERPARTY INPUT SCHEMA — P8.60
# =============================================================================
# One row per counterparty in scope of the Basic Approach to CVA risk
# (PRA PS1/26 Credit Valuation Adjustment Risk Part, Chapter 4). Held under an
# optional frame on ``RawDataBundle.cva_counterparties``; absent when the firm
# has no CVA scope (the CVA stage then no-ops, leaving ``cva_rwa = None``).
#
# References:
# - PS1/26 CVA Part 4.3: SCVA_c inputs (M_NS, EAD_NS, DF_NS, RW_c).
# - PS1/26 CVA Part 4.4: sector x credit-quality supervisory RW table.

#: Eligible ``cva_rw_sector`` keys — must match the first key of the
#: ``cva_ba_supervisory_risk_weights`` DecisionTable in packs/b31.py.
VALID_CVA_RW_SECTORS = {
    "SOVEREIGN",
    "LOCAL_GOVERNMENT",
    "FINANCIAL",
    "PENSION_FUND",
    "BASIC_MATERIALS",
    "CONSUMER",
    "TECHNOLOGY",
    "HEALTHCARE",
    "OTHER",
}

#: Eligible ``cva_rw_rating_band`` keys — investment grade vs high-yield/non-rated
#: (PS1/26 CVA Part 4.4 table columns).
VALID_CVA_RW_RATING_BANDS = {"IG", "HY_NR"}

#: BA-CVA counterparty input schema. ``counterparty_reference`` is the FK to the
#: netting set's counterparty; ``cva_rw_sector`` / ``cva_rw_rating_band`` select
#: RW_c from the Art. 4.4 table; ``cva_effective_maturity_years`` is M_NS;
#: ``cva_in_scope`` gates BA-CVA inclusion (out-of-scope rows are dropped).
CVA_COUNTERPARTY_SCHEMA: dict[str, ColumnSpec] = {
    "counterparty_reference": ColumnSpec(pl.String),
    "cva_rw_sector": ColumnSpec(pl.String),
    "cva_rw_rating_band": ColumnSpec(pl.String),
    "cva_effective_maturity_years": ColumnSpec(pl.Float64),
    "cva_in_scope": ColumnSpec(pl.Boolean, default=True, required=False),
}

#: Eligible ``cva_hedge_type`` keys — single-name vs index CDS hedges
#: (PS1/26 CVA Part 4.7 single-name / 4.8 index).
VALID_CVA_HEDGE_TYPES = {"SINGLE_NAME", "INDEX"}

#: Eligible ``cva_hedge_correlation_band`` keys — must match the key of the
#: ``cva_ba_single_name_hedge_correlation`` DecisionTable in packs/b31.py
#: (PS1/26 CVA Part 4.10 r_hc supervisory correlation table).
VALID_CVA_HEDGE_CORRELATION_BANDS = {"IDENTICAL", "LEGALLY_RELATED", "SAME_SECTOR_REGION"}

#: Full BA-CVA hedge input schema (P8.62). ``counterparty_reference`` is the FK
#: to the hedged counterparty (null for INDEX hedges); ``cva_hedge_correlation_band``
#: selects r_hc from the Part 4.10 table; ``cva_hedge_rw_sector`` /
#: ``cva_hedge_rw_rating_band`` select RW_h from the Part 4.4 table;
#: ``cva_hedge_residual_maturity_years`` is M_h; ``cva_hedge_notional`` is B_h;
#: ``cva_hedge_eligible`` gates inclusion in K_hedged (ineligible rows are dropped).
CVA_HEDGE_SCHEMA: dict[str, ColumnSpec] = {
    "cva_hedge_reference": ColumnSpec(pl.String),
    "cva_hedge_type": ColumnSpec(pl.String),
    "counterparty_reference": ColumnSpec(pl.String, required=False),
    "cva_hedge_correlation_band": ColumnSpec(pl.String, required=False),
    "cva_hedge_rw_sector": ColumnSpec(pl.String),
    "cva_hedge_rw_rating_band": ColumnSpec(pl.String),
    "cva_hedge_residual_maturity_years": ColumnSpec(pl.Float64),
    "cva_hedge_notional": ColumnSpec(pl.Float64),
    "cva_hedge_eligible": ColumnSpec(pl.Boolean, default=True, required=False),
}


# Short-code mapping for the five SA-CCR asset classes used to compose the
# stable ``hedging_set_id`` per CRR Art. 277(1) (e.g. "IR-NS-IR-01-GBP-GT_5Y").
# Keys are the canonical ``TRADE_SCHEMA.asset_class`` input strings; values are the
# BCBS / CRR conventional short codes. NOTE: only the ``interest_rate`` entry is
# currently consumed (engine/ccr/hedging_sets.py looks up ``asset_short`` for the IR
# hedging-set id); the FX / credit / equity / commodity ids use hardcoded literals.
ASSET_CLASS_SHORT_CODE: dict[str, str] = {
    "interest_rate": "IR",
    "fx": "FX",
    "credit": "CR",
    "equity": "EQ",
    "commodity": "CO",
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
    "natural_person",
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

# PRA PS1/26 Art. 161(1)(e)/(f)/(g): purchased-receivables F-IRB LGD sub-types.
VALID_PURCHASED_RECEIVABLES_SUBTYPES = {"senior", "subordinated", "dilution_risk"}

# RGLA / PSE entity types whose SA exposure class differs from their IRB
# exposure class (CRR Art. 147(3)/147(4)(b)). Used by the classifier's
# IRB-class sync (these are excluded from the SA-class sync because their
# IRB class is already correct) and by the post-approach exposure_class
# alignment (rewrites their post-approach ``exposure_class`` to the IRB
# class so the IRB calculator sees CGCB / INSTITUTION rather than RGLA /
# PSE).
RGLA_PSE_ENTITY_TYPES: tuple[str, ...] = (
    "rgla_sovereign",
    "rgla_institution",
    "pse_sovereign",
    "pse_institution",
)

# Entity types the Basel 3.1 approach-restriction step forces to the
# Standardised Approach only (no IRB), under PS1/26 Art. 147A(1)(a) read
# with Art. 147(3). Art. 147(3)(a)-(f) assign central governments, central
# banks, regional governments, local authorities, public sector entities
# and MDBs to the central-government / quasi-sovereign exposure class
# (Art. 147(2)(a)); Art. 147(3)(g) adds international organisations that
# carry a 0% SA risk weight. The "0% SA RW" qualifier binds ONLY the
# (g) international-organisations limb — regional governments (c), local
# authorities (d) and public sector entities (e) are assigned to that
# class UNCONDITIONALLY, dropping the CRR-era "treated as institutions"
# carve-out. Art. 147A(1)(a) then makes the whole class SA-only, so the
# institution-typed variants rgla_institution / pse_institution are IN
# scope here (superseding the earlier Art. 147A(1)(b)/147(4)(b) reading
# that routed them to institution F-IRB).
B31_SOVEREIGN_LIKE_ENTITY_TYPES: tuple[str, ...] = (
    "sovereign",
    "central_bank",
    "rgla_sovereign",
    "rgla_institution",
    "pse_sovereign",
    "pse_institution",
    "mdb",
    "mdb_named",
    "international_org",
)

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

# CRR/PS1-26 Art. 200(a)/232(2): cash-on-deposit collateral types eligible for the
# third-party-deposit (other-funded-protection) treatment when held at another
# institution (P1.239/P1.240).
THIRD_PARTY_DEPOSIT_COLLATERAL_TYPES: list[str] = ["cash", "deposit"]

# CRR/PS1-26 Art. 232(2) applies only where the deposit holder is an INSTITUTION.
# The deposit row's issuer_type describes the holder; only these values reach the
# institution risk-weight substitution — any other populated holder is out of
# scope (no benefit + CRM017).
INSTITUTION_DEPOSIT_HOLDER_TYPES: list[str] = ["institution", "bank", "credit_institution"]

CREDIT_LINKED_NOTE_COLLATERAL_TYPES: list[str] = ["credit_linked_note"]

# CRR/PS1-26 Art. 197(1)(f)/198(1)(a): the collateral_type synonyms the CRM engine
# treats as equity (main-index and non-main-index). Mirrors the equity branch of
# engine/crm/haircuts.py::_normalize_collateral_type_expr; used by the Art. 198(1)(a)
# non-main-index-equity listing-eligibility gate (P1.271).
EQUITY_COLLATERAL_TYPES: list[str] = ["equity", "shares", "stock"]

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

# Non-financial funded collateral types recognised under CRR Art. 230
# (Foundation Collateral Method). These types are NOT subject to the Art. 224
# Table 4 FX volatility haircut (H_fx) — Art. 233 H_fx is scoped to unfunded
# credit protection (guarantees / CDS), and Arts. 229–230 (the funded
# non-financial path) make no mention of an FX adjustment. FX risk on these
# collateral values is captured upstream by the spot-rate ``FXConverter``.
#
# Used by ``engine/crm/haircuts.py`` to gate the H_fx expression so that the
# Art. 230 LGD* formula receives the raw (FX-rebased) collateral value C
# without an additional volatility charge.
#
# References:
#   CRR Art. 229–230: Foundation Collateral Method (no H_fx in formula)
#   CRR Art. 233:    Unfunded credit protection scope of H_fx
NON_FINANCIAL_COLLATERAL_TYPES: list[str] = [
    *RECEIVABLE_COLLATERAL_TYPES,
    *REAL_ESTATE_COLLATERAL_TYPES,
    *OTHER_PHYSICAL_COLLATERAL_TYPES,
]


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

VALID_BENEFICIARY_TYPES = {"counterparty", "loan", "facility", "contingent", "guarantee"}

# PRA PS1/26 Art. 191A(2)(e)(i): allowed values for the look-through election
# on a two-layer protection guarantee. "funded_only" is the only path
# implemented today — "both" is reserved for future work (treated as "none").
VALID_LOOK_THROUGH_ELECTIONS = {"none", "funded_only", "both"}

VALID_PROTECTION_TYPES = {"guarantee", "credit_derivative"}

VALID_SCRA_GRADES = {"A", "A_ENHANCED", "B", "C"}

# CRR Art. 274(2) second sub-paragraph: the supervisory alpha carve-out
# (alpha = 1.0 instead of the 1.4 default) applies to derivative netting sets
# whose counterparty is a non-financial counterparty (EMIR Art. 2(9)), a
# pension scheme arrangement (EMIR Art. 2(10)), or a pension-scheme
# default-fund-contribution position. "financial" is the default — standard
# alpha = 1.4. Consumed by engine/ccr/pipeline_adapter.py to select the per-row
# ``alpha_applied`` scalar (see SA_CCR_ALPHA / SA_CCR_ALPHA_CARVE_OUT in
# data/tables/sa_ccr_factors.py).
VALID_CCR_COUNTERPARTY_TYPES = {
    "financial",
    "non_financial",
    "pension_scheme",
    "pension_default_comp",
}

# The subset of VALID_CCR_COUNTERPARTY_TYPES that qualifies for the CRR
# Art. 274(2) alpha = 1.0 carve-out (non-financial / pension-scheme / pension
# default-fund-contribution). "financial" is excluded — it keeps alpha = 1.4.
# engine/ccr/pipeline_adapter.py membership-tests ``counterparty_type`` against
# this set so the category strings are not inlined in engine scope.
CCR_ALPHA_CARVE_OUT_COUNTERPARTY_TYPES = {
    "non_financial",
    "pension_scheme",
    "pension_default_comp",
}

# P8.5 extension: "CCR_DERIVATIVE" / "CCR_SFT" tag exposures originated by
# the SA-CCR pipeline (CRR Art. 271). They flow through the same exposure
# row model as on-balance-sheet items but are routed into the dedicated CCR
# stages downstream.
# MR_ISSUED (P2.30): CRR Annex I Row 3 — "other" issued medium-risk OBS items
# (performance bonds, bid bonds, warranties, standby LCs not direct credit
# substitutes). Same 50% SA CCF as MR (Row 4 NIF/RUF commitments) but routed
# separately so Row 3 issued contingents are distinguishable from Row 4
# commitments.
VALID_RISK_TYPES_INPUT = {
    "FR",
    "FRC",
    "MR",
    "MR_ISSUED",
    "OC",
    "MLR",
    "LR",
    "CCR_DERIVATIVE",
    "CCR_SFT",
}

# Lowercase synonyms accepted on input for the risk_type column. Maps every
# permitted spelling (short code or full name) to its canonical uppercase
# form in VALID_RISK_TYPES_INPUT. Consumed by the CCF builders in
# data/tables/ccf.py so risk_type matching is case-insensitive and accepts
# both "FR" and "full_risk" style inputs.
RISK_TYPE_SYNONYMS: dict[str, str] = {
    "fr": "FR",
    "full_risk": "FR",
    "frc": "FRC",
    "full_risk_commitment": "FRC",
    "mr": "MR",
    "medium_risk": "MR",
    "mr_issued": "MR_ISSUED",
    "medium_risk_issued": "MR_ISSUED",
    "oc": "OC",
    "other_commit": "OC",
    "mlr": "MLR",
    "medium_low_risk": "MLR",
    "lr": "LR",
    "low_risk": "LR",
}

# CRR Annex I paras 1-4 / Art. 111(1): canonical normalised OBS *product* keys
# accepted on the ``obs_product`` column. Each maps (via ANNEX1_PRODUCT_RISK_TYPE
# in data/tables/ccf.py) to an abstract Annex I risk_type bucket. Distinct from
# the free-text ``product_type``.
VALID_OBS_PRODUCTS = {
    "ACCEPTANCE",
    "PERFORMANCE_BOND",
    "WARRANTY",
    "TENDER_BOND",
    "BID_BOND",
    "DOCUMENTARY_CREDIT",
    "TRADE_LC",
}

# Lowercase synonyms accepted on input for the obs_product column. Maps every
# permitted spelling to its canonical uppercase form in VALID_OBS_PRODUCTS.
# Consumed by build_product_to_risk_type_expr in data/tables/ccf.py so product
# matching is case-insensitive. Mirrors RISK_TYPE_SYNONYMS in shape.
OBS_PRODUCT_SYNONYMS: dict[str, str] = {
    "acceptance": "ACCEPTANCE",
    "bankers_acceptance": "ACCEPTANCE",
    "performance_bond": "PERFORMANCE_BOND",
    "perf_bond": "PERFORMANCE_BOND",
    "warranty": "WARRANTY",
    "tender_bond": "TENDER_BOND",
    "bid_bond": "BID_BOND",
    "documentary_credit": "DOCUMENTARY_CREDIT",
    "doc_credit": "DOCUMENTARY_CREDIT",
    "trade_lc": "TRADE_LC",
}

VALID_BS_TYPES = {"ONB", "OFB"}

VALID_CHILD_TYPES = {"facility", "loan", "contingent"}

# Allowed values for ``RATINGS_SCHEMA.scope_type`` — identifies which exposure a
# short-term rating row attaches to. Mirrors VALID_CHILD_TYPES but kept as a
# distinct set because the two concepts (facility-mapping child type vs rating
# scope) are independent contracts. Null is also valid (counterparty-wide).
VALID_RATING_SCOPE_TYPES = {"facility", "loan", "contingent"}

VALID_MODEL_PERMISSION_APPROACHES = {
    "foundation_irb",
    "advanced_irb",
    "slotting",
    # "standardised" permits an IRB-permissioned firm to route an exposure class
    # to SA under a permanent partial use (CRR Art. 150(1)) or sequential roll-out
    # (CRR Art. 148) permission; the legal basis is carried in ``ppu_reason``.
    "standardised",
}

# Allowed values for ``model_permissions.ppu_reason`` — the legal basis for an
# SA-routed (approach="standardised") permission. CRR Art. 150(1)(a)-(j) permanent
# partial use conditions plus Art. 148 sequential IRB roll-out. Mirrors the
# PpuReason enum (domain/enums.py); null is also valid (plain SA fallback).
VALID_PPU_REASONS = {
    "art_150_1_a",
    "art_150_1_b",
    "art_150_1_c",
    "art_150_1_d",
    "art_150_1_e",
    "art_150_1_f",
    "art_150_1_g",
    "art_150_1_h",
    "art_150_1_i",
    "art_150_1_j",
    "art_148_rollout",
}

VALID_CIU_APPROACHES = {"look_through", "mandate_based", "fallback"}

# CRR Art. 244 (traditional) vs Art. 245 (synthetic) — see
# SECURITISATION_ALLOCATION_SCHEMA. Carried for future use; phase 1 trusts
# the firm's classification without validation of the underlying transfer.
VALID_TRANSFER_TYPES = {"traditional", "synthetic"}

# Native source table per exposure_reference on securitisation_allocations.
VALID_SECURITISATION_EXPOSURE_TYPES = {"loan", "contingent", "facility"}

# Registry: maps table_name -> {column_name -> valid_values_set}
# Used by validate_bundle_values() for input validation.
COLUMN_VALUE_CONSTRAINTS: dict[str, dict[str, set[str]]] = {
    "facilities": {
        "seniority": VALID_SENIORITY,
        "risk_type": VALID_RISK_TYPES_INPUT,
        "underlying_risk_type": VALID_RISK_TYPES_INPUT,
        "obs_product": VALID_OBS_PRODUCTS,
        "purchased_receivables_subtype": VALID_PURCHASED_RECEIVABLES_SUBTYPES,
    },
    "loans": {
        "seniority": VALID_SENIORITY,
        "purchased_receivables_subtype": VALID_PURCHASED_RECEIVABLES_SUBTYPES,
        "exposure_collateral_type": VALID_COLLATERAL_TYPES,
    },
    "contingents": {
        "seniority": VALID_SENIORITY,
        "bs_type": VALID_BS_TYPES,
        "risk_type": VALID_RISK_TYPES_INPUT,
        "underlying_risk_type": VALID_RISK_TYPES_INPUT,
        "obs_product": VALID_OBS_PRODUCTS,
        "purchased_receivables_subtype": VALID_PURCHASED_RECEIVABLES_SUBTYPES,
        "exposure_collateral_type": VALID_COLLATERAL_TYPES,
    },
    "counterparties": {
        "entity_type": VALID_ENTITY_TYPES,
        "scra_grade": VALID_SCRA_GRADES,
        # CRR Art. 274(2) second sub-paragraph — SA-CCR alpha carve-out discriminator.
        "counterparty_type": VALID_CCR_COUNTERPARTY_TYPES,
    },
    "collateral": {
        "collateral_type": VALID_COLLATERAL_TYPES,
        "property_type": VALID_PROPERTY_TYPES,
        "issuer_type": VALID_ISSUER_TYPES,
        "valuation_type": VALID_VALUATION_TYPES,
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
    },
    "collateral_links": {
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
    },
    "provisions": {
        "provision_type": VALID_PROVISION_TYPES,
        "beneficiary_type": VALID_BENEFICIARY_TYPES,
    },
    "ratings": {
        "rating_type": VALID_RATING_TYPES,
        "scope_type": VALID_RATING_SCOPE_TYPES,
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
        "look_through_election": VALID_LOOK_THROUGH_ELECTIONS,
    },
    "facility_mappings": {
        "child_type": VALID_CHILD_TYPES,
    },
    "model_permissions": {
        "approach": VALID_MODEL_PERMISSION_APPROACHES,
        "ppu_reason": VALID_PPU_REASONS,
    },
    "securitisation_allocations": {
        "exposure_type": VALID_SECURITISATION_EXPOSURE_TYPES,
        "transfer_type": VALID_TRANSFER_TYPES,
    },
    # P8.60 — BA-CVA counterparty sector / credit-quality discriminators
    # (PS1/26 CVA Part 4.4 supervisory RW table).
    "cva_counterparties": {
        "cva_rw_sector": VALID_CVA_RW_SECTORS,
        "cva_rw_rating_band": VALID_CVA_RW_RATING_BANDS,
    },
    # P8.62 — full BA-CVA hedge sector / credit-quality / correlation-band / type
    # discriminators (PS1/26 CVA Part 4.4 RW table, 4.7/4.8 hedge types, 4.10
    # r_hc correlation table).
    "cva_hedges": {
        "cva_hedge_type": VALID_CVA_HEDGE_TYPES,
        "cva_hedge_correlation_band": VALID_CVA_HEDGE_CORRELATION_BANDS,
        "cva_hedge_rw_sector": VALID_CVA_RW_SECTORS,
        "cva_hedge_rw_rating_band": VALID_CVA_RW_RATING_BANDS,
    },
    # P8.33 — CRR Art. 277(3)(b) / CRE52.67 commodity hedging-set partition.
    # UPPER-CASE bucket keys to match ``SA_CCR_SUPERVISORY_FACTORS_COMMODITY``
    # in ``data/tables/sa_ccr_factors.py`` — load-bearing for the P8.37
    # supervisory-factor join.
    "trades": {
        # SFT/FCCM separation — the CCR/SFT trade discriminator. Dormant until
        # the CCR/SFT trade frame is added to validate_bundle_values'
        # frame_mapping (like commodity_type/credit_quality below today).
        "transaction_type": VALID_TRANSACTION_TYPES,
        "commodity_type": {"ELECTRICITY", "OIL_GAS", "METALS", "AGRICULTURAL", "OTHER"},
        # P8.35 — CRR Art. 280 Table 2 credit-quality discriminator: keyed off
        # ``SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN`` / ``..._CREDIT_IDX`` in
        # ``data/tables/sa_ccr_factors.py``.
        "credit_quality": {"IG", "HY", "NON_RATED"},
    },
    # SFT/FCCM separation Phase 0b — the margined-SFT MPOR floor selector. A bad
    # value would silently mis-floor the Art. 285 margin period of risk. Dormant
    # until the SFT trade frame is added to validate_bundle_values' frame_mapping
    # (mirrors the 'trades' entry above), but declared here as the single source
    # of truth for the input domain.
    "sft_trades": {
        "mpor_floor_category": VALID_MPOR_FLOOR_CATEGORIES,
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
    # CRR Art. 272 Def (88) — qualifying-CCP flag. Gates the Art. 306(1) 2%/4%
    # QCCP trade-exposure pin: only an explicit False demotes a ``ccp``
    # entity_type to the standard institution ladder (Art. 107(2)(a)).
    "cp_is_qccp": ColumnSpec(pl.Boolean, required=False),
    "cp_scra_grade": ColumnSpec(pl.String, required=False),
    "cp_sovereign_cqs": ColumnSpec(pl.Int32, required=False),
    "cp_local_currency": ColumnSpec(pl.String, required=False),
    "cp_institution_cqs": ColumnSpec(pl.Int8, required=False),
    # CRR Art. 137(1)-(2) Table 9 — nominated ECA MEIP score (0-7).
    "cp_eca_score": ColumnSpec(pl.Int8, required=False),
    # CRR Art. 227(3) / PRA PS1/26 Art. 227(3) — core market participant flag
    # propagated from COUNTERPARTY_SCHEMA. Used by the FCSM SFT carve-out
    # (Art. 222(4)) to select 0% RW (True) vs 10% RW (False).
    "cp_is_core_market_participant": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 139(2B): whether the Art. 138-resolved external rating came
    # from an issue-specific assessment. False signals an inferred / issuer-level
    # rating, which is disapplied for the SA specialised-lending routing under
    # Art. 122B(1). Default True preserves legacy behaviour (directly applicable).
    "external_rating_is_issue_specific": ColumnSpec(pl.Boolean, default=True, required=False),
    # Firm-supplied internal rating grade carried through as a cp_-prefixed
    # results column for COREP C 08.02 grade-keyed rows (Annex II, C 08.02).
    "cp_internal_rating_grade": ColumnSpec(pl.String, required=False),
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
    # CRR Art. 123 / PS1/26 Art. 123A / CRE20.65-67: the 75% retail weight
    # is PREFERENTIAL — available only when the qualifying criteria are
    # demonstrated. Unknown -> False (100% non-qualifying retail), the
    # conservative direction. Recorded FIX decision 2026-06-12 (was True,
    # diverging from b31_risk_weights' coalesce-False); the classifier
    # always recomputes this in-pipeline, so only direct-invocation paths
    # are affected and no goldens change.
    "qualifies_as_retail": ColumnSpec(pl.Boolean, default=False, required=False),
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
    "re_split_residential_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "re_split_commercial_value": ColumnSpec(pl.Float64, default=0.0, required=False),
    "re_split_residential_eligible": ColumnSpec(pl.Boolean, default=False, required=False),
    "re_split_commercial_eligible": ColumnSpec(pl.Boolean, default=False, required=False),
    "re_split_cre_rental_coverage_met": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 124(4) all-or-nothing gate: True for mixed-RE rows where
    # at least one component fails Art. 124A — splitter routes BOTH secured rows
    # through Art. 124J (Other RE) and allocates full pro-rata EAD (no 0.55xV cap).
    "re_split_force_other_re": ColumnSpec(pl.Boolean, default=False, required=False),
    # PRA PS1/26 Art. 147A(1)(e)/(f) corporate sub-class — Basel 3.1 only (null
    # under CRR). Drives the COREP C 02.00 / OF 02.00 corporate sub-row split:
    # corporate_financial_large (FSE or revenue > GBP 440m) -> 0295,
    # corporate_sme -> 0296/0355, corporate_other -> 0297/0356. Populated by
    # Classifier._derive_exposure_subclass for corporate / corporate_sme rows.
    "exposure_subclass": ColumnSpec(pl.String, required=False),
    # CRR Art. 150(1)(a)-(j) PPU / Art. 148 roll-out provenance for SA-routed
    # exposures, carried from the surviving model_permissions row by
    # Classifier._resolve_model_permissions. Null under CRR/B31 when no SA-routing
    # permission applied. Drives COREP C 07.00 / OF 07.00 Section 1 rows 0050/0060.
    "ppu_reason": ColumnSpec(pl.String, required=False),
}


# Columns produced by the RealEstateSplitter stage. Both rows of a split share
# `split_parent_id`; `re_split_role` is one of "secured" / "secured_rre" /
# "secured_cre" / "residual" / "whole" (or null for unaffected rows).
# - "secured" — single-component (pure RRE or pure CRE) preferential row
# - "secured_rre" / "secured_cre" — emitted in pairs for mixed RRE+CRE exposures
#   (PRA PS1/26 Art. 124(4); CRR Art. 124(1) "any part of an exposure")
# - "residual" — uncollateralised remainder, original counterparty class
# - "whole" — B3.1 Art. 124H(3) non-NP/SME corporate CRE-only reclassification
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
    # CRR Art. 111(1)/Annex I 2(b),3(b): OC original maturity (years) for the SA CCF MR/MLR split
    "original_maturity_years": pl.Float64,
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
    "is_payroll_loan": pl.Boolean,  # Payroll/pension loan — 35% RW under Basel 3.1 (Art. 123(4))
    "is_buy_to_let": pl.Boolean,  # BTL property lending - excluded from SME supporting factor (CRR Art. 501)
    "has_one_day_maturity_floor": pl.Boolean,  # Art. 162(3): repos/SFTs with daily margining — 1-day M floor
    "is_sft": pl.Boolean,  # CRR Art. 162(1): repurchase / securities / commodities lending/borrowing — F-IRB M = 0.5y
    "facility_termination_date": pl.Date,  # Art. 162(2A)(k): max contractual termination date for revolving facilities (Basel 3.1 M)
    "effective_maturity": pl.Float64,  # Art. 162(3): explicit numeric M override (years); bypasses 1y floor when populated
    # FX conversion audit trail (populated after FX conversion)
    "original_currency": pl.String,  # Currency before FX conversion
    "original_amount": pl.Float64,  # Amount before FX conversion (drawn + interest + nominal)
    "fx_rate_applied": pl.Float64,  # Rate used (null if no conversion needed)
    # CCR provenance (CRR Art. 271). Populated only on synthetic exposure rows
    # appended by the SA-CCR pipeline stage (engine/ccr/pipeline_adapter.py);
    # null on traditional lending / contingent / facility-undrawn rows.
    "source_netting_set_id": pl.String,
    "ccr_method": pl.String,
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
    # CRR Art. 111(1)/Annex I 2(b),3(b): OC original maturity (years) for the SA CCF MR/MLR split
    "original_maturity_years": pl.Float64,
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
    # Parent + every ancestor facility (incl. self) — drives the CRM cascade of
    # facility-level collateral down nested facility hierarchies.
    "ancestor_facilities": pl.List(pl.String),
    # Lending group aggregation
    "lending_group_reference": pl.String,
    "lending_group_total_exposure": pl.Float64,
    # Retail threshold adjustment (CRR Art. 123(c) - residential property exclusion)
    "lending_group_adjusted_exposure": pl.Float64,  # Excludes residential RE for retail threshold
    "residential_collateral_value": pl.Float64,  # Residential RE collateral securing this exposure
    "exposure_for_retail_threshold": pl.Float64,  # This exposure's contribution (excl. residential RE)
    # CCR provenance (CRR Art. 271); null for traditional lending rows.
    "source_netting_set_id": pl.String,
    "ccr_method": pl.String,
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
    # CCR provenance (CRR Art. 271); null for traditional lending rows.
    "source_netting_set_id": pl.String,
    "ccr_method": pl.String,
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
    # CCR provenance (CRR Art. 271); null for traditional lending rows.
    "source_netting_set_id": pl.String,
    "ccr_method": pl.String,
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

# Schema for IRB calculation results.
# NOTE (documentary only — NOT enforced): the live IRB output uses un-prefixed
# names (``pd_floored``/``pd``, ``lgd_floored``/``lgd_input``/``lgd``), not the
# ``irb_``-prefixed names below. See CALCULATION_OUTPUT_SCHEMA's note.
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
#
# NOTE (documentary only — NOT enforced): this dict is never applied to the output
# frame via select/rename/cast. The real per-exposure output (what scan_results()
# scans) is the raw aggregator ``results`` frame sealed by
# ``contracts/edges.AGGREGATOR_EXIT_EDGE``. Several IRB columns below use aspirational
# ``irb_``-prefixed names the engine never emits — the real output names are
# un-prefixed: ``pd_floored``/``pd``, ``lgd_floored``/``lgd_input``/``lgd``,
# ``ead_final``, ``rwa_final``, ``risk_weight``. Consumers that must match the live
# output (the reconciliation registry in analysis/recon_registry.py and the
# COREP/Pillar-III generators) key on those real names, never on this schema.
# Guarded by tests/integration/test_reconciliation_output_contract.py.
CALCULATION_OUTPUT_SCHEMA = {
    # -------------------------------------------------------------------------
    # IDENTIFICATION & LINEAGE
    # -------------------------------------------------------------------------
    "calculation_run_id": pl.String,  # Unique run identifier for audit trail
    "calculation_timestamp": pl.Datetime,  # When calculation was performed
    "exposure_reference": pl.String,  # Links to source loan/facility/contingent
    "source_exposure_reference": pl.String,  # Pre-concatenation base ref for reconciliation (strips guarantee/undrawn/RE suffixes)
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
    "ancestor_facilities": pl.List(
        pl.String
    ),  # Parent + all ancestors (incl. self) for CRM cascade
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
    "risk_weight_pre_currency_mismatch": pl.Float64,  # RW snapshot before 1.5x mismatch multiply
    # -------------------------------------------------------------------------
    # POST-MODEL ADJUSTMENTS (Basel 3.1 PRA PS1/26 Art. 153(5A), 154(4A), 158(6A))
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


# The parallel-run reconciliation component registry (ReconcilableComponent /
# RECONCILABLE_COMPONENTS) and the LegacyColumnMapping / ComponentMapping config
# moved to rwa_calc.analysis.recon_registry (migration Phase 6 - analysis layer).
# The collapse-helper output-domain tuples below stay here (engine-consumed).

# Numeric result fields that must be SUMMED when collapsing guarantee/RE sub-rows
# (and any coarser key grain) back to a parent/key. Mirrors the runtime results
# frame names (ead_final / rwa_final / expected_loss). Single source of truth for
# the engine collapse helper and the acceptance-test result lookup.
ADDITIVE_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {
        "ead_final",
        "ead_pre_crm",
        "ead_after_collateral",
        "rwa_final",
        "rwa_pre_crm",
        "rwa_post_factor",
        "rwa_pre_factor",
        "guaranteed_portion",
        "unguaranteed_portion",
        "drawn_amount",
        "undrawn_amount",
        "nominal_amount",
        "provision_deducted",
        "provision_on_drawn",
        "provision_on_nominal",
        "expected_loss",
    }
)

# Columns that carry a row's link to its pre-concatenation base exposure. The
# collapse helper coalesces whichever are present, in order (then falls back to
# exposure_reference), to derive the parent/base grain.
# ``source_exposure_reference`` is the primary, always-present base: unify.py sets
# it on loans/contingents, facility_undrawn.py sets it to the facility reference
# (recovering undrawn / MOF rows the parent-link columns cannot), the equity path
# and synthetic CCR/SFT builders set it too. It is listed first so it wins the
# coalesce; guarantee (``parent_exposure_reference``) and RE-split
# (``split_parent_id``) recovery is unchanged because on those sub-rows the base
# equals the parent link. The latter two are retained as defensive fallbacks for
# result parquets written before ``source_exposure_reference`` existed (typed null
# there -> fall through). All three are declared required on the sealed
# aggregator-exit edge, so they are always present on a live results frame.
RECON_PARENT_KEY_COLUMNS: tuple[str, ...] = (
    "source_exposure_reference",
    "parent_exposure_reference",
    "split_parent_id",
)

# Ratio columns that are meaningless when summed/first-ed across sub-rows and must
# be recomputed as sum(rwa) / sum(ead) after the collapse group-by.
RECON_RATIO_COLUMNS: tuple[str, ...] = ("risk_weight", "risk_weight_effective")

# Categorical columns whose within-group disagreement is surfaced when a coarse
# reconciliation key aggregates rows of mixed class/approach.
RECON_HETEROGENEITY_COLUMNS: tuple[str, ...] = ("exposure_class", "approach_applied")
