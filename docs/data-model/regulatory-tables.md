# Regulatory Tables

<!-- GENERATED FILE — DO NOT EDIT. Regenerate: uv run python scripts/generate_regulatory_tables.py -->

Every cited regulatory value in the rulepack packs `src/rwa_calc/rulebook/packs/{common,crr,b31}.py`, rendered from `rwa_calc.rulebook.resolve.resolve(regime, date)`. **This page is generated** — a wrong value here is a rulepack finding, never a docs edit. Entries identical under both regimes appear once; divergent entries appear per regime.

Package version `0.3.24`. Resolved packs:

- **CRR** (`crr` @ 2026-01-01) — 203 entries, content hash `ce2b4dbd2b2f7daf`
- **Basel 3.1** (`b31` @ 2027-01-01) — 235 entries, content hash `9a883964d8479e76`

## Regime features

On/off behaviour switches (`Feature`).

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `airb_ead_floor_applies` | off | on | CRR Art. 166 / PS1/26, paragraph 166D |
| `airb_lgd_collateral_method_applicable` | off | on | CRR Art. 181 / PS1/26, paragraph 169A |
| `airb_lgd_floor` | off | on | CRR Art. 164 / PS1/26, paragraph 161 |
| `approach_restrictions_b31_applicable` | off | on | CRR Art. 147 / PS1/26, paragraph 147A |
| `b31_art_124e_three_property_limit_applies` | off | on | CRR Art. 124 / PS1/26, paragraph 124E |
| `b31_exposure_subclass_reporting_applies` | off | on | CRR Art. 147 / PS1/26, paragraph 147A |
| `b31_high_risk_class_applicable` | off | on | CRR Art. 128 / PS1/26, paragraph 128 |
| `ccr_synthetic_maturity` | on | on | CRR Art. 162 / PS1/26, paragraph 162 |
| `ccr_transitional_alpha_addon_applicable` | off | on | CRR Art. 274 / PS1/26, paragraph 274 |
| `central_bank_uses_sovereign_cqs` | off | on | CRR Art. 114 / PS1/26, paragraph 114 |
| `collateral_haircut_maturity_bands_revised` | off | on | CRR Art. 224 / PS1/26, paragraph 224 |
| `crr_non_named_mdb_institution_irb_class` | on | off | CRR Art. 147 / PS1/26, paragraph 147 |
| `crr_retail_re_portfolio_lgd_floor` | on | off | CRR Art. 164 / PS1/26, paragraph 164 |
| `cva_ba_cva` | — | on | PS1/26, paragraph 4.1 |
| `double_default_treatment` | on | off | CRR Art. 153(3) / PS1/26, paragraph 153 |
| `equity_irb_approaches_available` | on | off | CRR Art. 155 / PS1/26, paragraph 133 |
| `equity_revised_sa_risk_weights` | off | on | CRR Art. 133 / PS1/26, paragraph 133 |
| `equity_transitional` | off | on | CRR Art. 133 / PS1/26, paragraph 4.1 |
| `firb_fixed_supervisory_maturity` | on | off | CRR Art. 162(1) / PS1/26, paragraph 162 |
| `firb_fse_senior_lgd_split` | off | on | CRR Art. 161(1)(a) / PS1/26, paragraph 161 |
| `firb_min_collateralisation_threshold_applies` | on | off | CRR Art. 230 / PS1/26, paragraph 230 |
| `firb_overcollateralisation_divisor_applies` | on | off | CRR Art. 230 / PS1/26, paragraph 230 |
| `firb_sft_supervisory_maturity` | on | off | CRR Art. 162(1) / PS1/26, paragraph 162 |
| `firb_uses_sa_ccf` | off | on | CRR Art. 166 / PS1/26, paragraph 166C |
| `intragroup_zero_rw` | on | on | CRR Art. 113 / PS1/26, paragraph 113 |
| `irb_correlation_sme_gbp_native` | off | on | CRR Art. 153(4) / PS1/26, paragraph 153 |
| `mna_intermediate_floor_requires_daily_condition` | off | on | CRR Art. 162(2) / PS1/26, paragraph 162 |
| `one_day_maturity_floor` | on | off | CRR Art. 162(3) / PS1/26, paragraph 162 |
| `output_floor` | off | on | CRR Art. 92 / PS1/26, paragraph 92 |
| `post_model_adjustments` | off | on | CRR Art. 153 / PS1/26, paragraph 154 |
| `regulatory_thresholds_fx_derived` | on | off | CRR Art. 123 / PS1/26, paragraph 147 |
| `retail_art_123a_two_path_applicable` | off | on | CRR Art. 123 / PS1/26, paragraph 123A |
| `revolving_uses_termination_maturity` | off | on | CRR Art. 162 / PS1/26, paragraph 162 |
| `sa_currency_mismatch_multiplier` | off | on | CRR Art. 123 / PS1/26, paragraph 123B |
| `sa_due_diligence_override` | off | on | CRR Art. 110 / PS1/26, paragraph 110A |
| `sa_re_split_art_124_4_all_or_nothing` | off | on | CRR Art. 124 / PS1/26, paragraph 124 |
| `sa_re_split_cre_rental_coverage_required` | on | off | CRR Art. 126 / PS1/26, paragraph 124H |
| `sa_re_split_revised_parameters` | off | on | CRR Art. 125 / PS1/26, paragraph 124F |
| `sa_re_split_whole_loan_path_applies` | off | on | CRR Art. 126 / PS1/26, paragraph 124H |
| `sa_revised_ccf_table` | off | on | CRR Art. 111 / PS1/26, paragraph 111 |
| `sa_revised_defaulted_treatment` | off | on | CRR Art. 127 / PS1/26, paragraph 127 |
| `sa_revised_risk_weight_overrides` | off | on | CRR Art. 112 / PS1/26, paragraph 122 |
| `sa_revised_risk_weight_tables` | off | on | CRR Art. 122 / PS1/26, paragraph 122 |
| `sa_sl_inferred_rating_disapplied` | off | on | CRR Art. 139 / PS1/26, paragraph 139 |
| `slotting_guarantee_substitution` | on | on | CRR Art. 235 / PS1/26, paragraph 235 |
| `slotting_revised_tables` | off | on | CRR Art. 153(5) / PS1/26, paragraph 153 |
| `supporting_factors` | on | off | CRR Art. 501 / PS1/26, paragraph 501 |
| `ucp_unilateral_change_ineligible` | off | on | CRR Art. 213 / PS1/26, paragraph 213 |

## Scalar parameters

Decimal-valued parameters (`ScalarParam`). Risk weights and factors are decimal fractions (0.20 = 20%).

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `airb_obs_floor_b_multiplier` | — | `0.5` | PS1/26, paragraph 166D |
| `airb_revolving_ccf_floor_multiplier` | — | `0.5` | PS1/26, paragraph 166D |
| `b31_adc_presold_risk_weight` | — | `1.00` | PS1/26, paragraph 124K |
| `b31_adc_risk_weight` | — | `1.50` | PS1/26, paragraph 124K |
| `b31_commercial_general_max_secured_ratio` | — | `0.55` | PS1/26, paragraph 124H |
| `b31_commercial_general_secured_rw` | — | `0.60` | PS1/26, paragraph 124H |
| `b31_corporate_investment_grade_rw` | — | `0.65` | PS1/26, paragraph 122 |
| `b31_corporate_non_investment_grade_rw` | — | `1.35` | PS1/26, paragraph 122 |
| `b31_corporate_sme_rw` | — | `0.85` | PS1/26, paragraph 122 |
| `b31_cre_income_junior_rw_high` | — | `1.375` | PS1/26, paragraph 124I |
| `b31_cre_income_junior_rw_low` | — | `1.00` | PS1/26, paragraph 124I |
| `b31_cre_income_junior_rw_mid` | — | `1.25` | PS1/26, paragraph 124I |
| `b31_currency_mismatch_hedge_coverage_floor` | — | `0.90` | PS1/26, paragraph 123B |
| `b31_currency_mismatch_multiplier` | — | `1.5` | PS1/26, paragraph 123B |
| `b31_currency_mismatch_rw_cap` | — | `1.50` | PS1/26, paragraph 123B |
| `b31_defaulted_provision_threshold` | — | `0.20` | PS1/26, paragraph 127 |
| `b31_defaulted_resi_re_non_income_rw` | — | `1.00` | PS1/26, paragraph 127 |
| `b31_defaulted_rw_high_provision` | — | `1.00` | PS1/26, paragraph 127 |
| `b31_defaulted_rw_low_provision` | — | `1.50` | PS1/26, paragraph 127 |
| `b31_other_re_cre_floor_rw` | — | `0.60` | PS1/26, paragraph 124J |
| `b31_other_re_income_dependent_rw` | — | `1.50` | PS1/26, paragraph 124J |
| `b31_residential_general_max_secured_ratio` | — | `0.55` | PS1/26, paragraph 124F |
| `b31_residential_general_secured_rw` | — | `0.20` | PS1/26, paragraph 124F |
| `b31_residential_income_junior_ltv_threshold` | — | `0.50` | PS1/26, paragraph 124G |
| `b31_residential_income_junior_multiplier` | — | `1.25` | PS1/26, paragraph 124G |
| `b31_retail_granularity_limit` | — | `0.002` | PS1/26, paragraph 123 |
| `b31_retail_non_regulatory_rw` | — | `1.00` | PS1/26, paragraph 123 |
| `b31_retail_payroll_loan_rw` | — | `0.35` | PS1/26, paragraph 123 |
| `b31_retail_transactor_rw` | — | `0.45` | PS1/26, paragraph 123 |
| `b31_rre_residual_rw_natural_person` | — | `0.75` | PS1/26, paragraph 124L |
| `b31_rre_residual_rw_other_sme` | — | `0.85` | PS1/26, paragraph 124L |
| `b31_rre_residual_rw_retail_sme` | — | `0.75` | PS1/26, paragraph 124L |
| `b31_rre_residual_rw_social_housing_floor` | — | `0.75` | PS1/26, paragraph 124L |
| `b31_subordinated_debt_rw` | — | `1.50` | PS1/26, paragraph 133 |
| `ccr_wwr_specific_lgd_override` | `1.0` | `1.0` | CRR Art. 291 |
| `crr_corporate_sme_rw` | `1.00` | — | CRR Art. 122 |
| `crr_defaulted_provision_threshold` | `0.20` | — | CRR Art. 127 |
| `crr_defaulted_rw_high_provision` | `1.00` | — | CRR Art. 127 |
| `crr_defaulted_rw_low_provision` | `1.50` | — | CRR Art. 127 |
| `crr_non_regulatory_retail_rw` | `1.00` | — | CRR Art. 123 |
| `cva_ba_beta` | — | `0.25` | PS1/26, paragraph 4.5 |
| `cva_ba_index_diversification_factor` | — | `0.70` | PS1/26, paragraph 4.8 |
| `cva_ba_supervisory_correlation` | — | `0.50` | PS1/26, paragraph 4.2 |
| `cva_ba_supervisory_discount_rate` | — | `0.05` | PS1/26, paragraph 4.3 |
| `ds_ba_cva` | — | `0.65` | PS1/26, paragraph 4.2 |
| `ecb_zero_rw` | `0.00` | `0.00` | CRR Art. 114 |
| `equity_netting_min_hedge_years` | `1.0` | — | CRR Art. 155(2) |
| `equity_pd_lgd_maturity` | `5.0` | — | CRR Art. 165 |
| `equity_pd_lgd_no_default_info_scaling` | `1.5` | — | CRR Art. 155(3) |
| `failed_trade_dvp_mult_16_30` | `0.50` | `0.50` | CRR Art. 378 |
| `failed_trade_dvp_mult_31_45` | `0.75` | `0.75` | CRR Art. 378 |
| `failed_trade_dvp_mult_46_plus` | `1.00` | `1.00` | CRR Art. 378 |
| `failed_trade_dvp_mult_5_15` | `0.08` | `0.08` | CRR Art. 378 |
| `failed_trade_non_dvp_col4_rw_multiplier` | `12.50` | `12.50` | CRR Art. 379 |
| `fcsm_equity_collateral_rw` | `1.00` | `1.00` | CRR Art. 222(1) |
| `fcsm_rw_floor` | `0.20` | `0.20` | CRR Art. 222(1) |
| `fcsm_sft_cmp_floor` | `0.00` | `0.00` | CRR Art. 222(4)(a) |
| `fcsm_sft_non_cmp_floor` | `0.10` | `0.10` | CRR Art. 222(4)(b) |
| `fcsm_sovereign_bond_discount` | `0.20` | `0.20` | CRR Art. 222(4)(b) |
| `firb_credit_line_ccf` | `0.75` | — | CRR Art. 166 |
| `firb_fixed_supervisory_maturity_years` | `2.5` | `2.5` | CRR Art. 162(1) |
| `firb_sft_supervisory_maturity_years` | `0.5` | `0.5` | CRR Art. 162(1) |
| `firb_trade_lc_ccf` | `0.20` | — | CRR Art. 166 |
| `fx_haircut` | `0.08` | `0.08` | CRR Art. 224 |
| `gcra_cap_rate` | — | `0.0125` | PS1/26, paragraph 92 |
| `high_risk_rw` | `1.50` | `1.50` | CRR Art. 128 |
| `institution_short_term_unrated_rw_crr` | `0.20` | — | CRR Art. 121 |
| `intragroup_zero_rw_pct` | `0.00` | `0.00` | CRR Art. 113 / PS1/26, paragraph 113 |
| `io_zero_rw` | `0.00` | `0.00` | CRR Art. 118 |
| `irb_maturity_floor_collateralised_deriv_years` | `0.02739726027397260273972602740` | `0.02739726027397260273972602740` | CRR Art. 162(2) |
| `irb_maturity_floor_repo_sft_years` | `0.01369863013698630136986301370` | `0.01369863013698630136986301370` | CRR Art. 162(2) |
| `irb_scaling_factor` | `1.06` | `1.0` | CRR Art. 153(1) / PS1/26, paragraph 153 |
| `mdb_named_zero_rw` | `0.00` | `0.00` | CRR Art. 117 |
| `mdb_unrated_rw` | `0.50` | `0.50` | CRR Art. 117 |
| `mf_margined_scalar` | `1.5` | `1.5` | CRR Art. 279c |
| `mf_unmargined_cap_years` | `1.0` | `1.0` | CRR Art. 279c |
| `mf_unmargined_denom_years` | `1.0` | `1.0` | CRR Art. 279c |
| `mortgage_rw_floor` | — | `0.10` | PS1/26, paragraph 154 |
| `oc_short_maturity_ccf` | `0.20` | `0.20` | CRR Art. 111 |
| `one_day_maturity_floor_years` | `0.002739726027397260273972602740` | `0.002739726027397260273972602740` | CRR Art. 162(3) |
| `other_items_cash_rw` | `0.00` | `0.00` | CRR Art. 134 |
| `other_items_collection_rw` | `0.20` | `0.20` | CRR Art. 134 |
| `other_items_default_rw` | `1.00` | `1.00` | CRR Art. 134 |
| `other_items_gold_rw` | `0.00` | `0.00` | CRR Art. 134 |
| `other_items_tangible_rw` | `1.00` | `1.00` | CRR Art. 134 |
| `output_floor_pct_full` | — | `0.725` | PS1/26, paragraph 92 |
| `own_funds_to_rwa_factor` | `12.5` | `12.5` | CRR Art. 92 |
| `pfe_aggregate_denom_coeff` | `2` | `2` | CRR Art. 278 |
| `pfe_multiplier_floor_f` | `0.05` | `0.05` | CRR Art. 278 |
| `pse_non_equivalent_jurisdiction_rw` | `1.00` | `1.00` | CRR Art. 116 |
| `pse_short_term_rw` | `0.20` | `0.20` | CRR Art. 116 |
| `pse_unrated_default_rw` | `1.00` | `1.00` | CRR Art. 116 |
| `qccp_client_cleared_rw` | `0.04` | `0.04` | CRR Art. 306 |
| `qccp_proprietary_rw` | `0.02` | `0.02` | CRR Art. 306 |
| `re_split_cre_secured_ltv_cap` | `0.50` | `0.55` | CRR Art. 126 / PS1/26, paragraph 124H |
| `re_split_rre_secured_ltv_cap` | `0.80` | `0.55` | CRR Art. 125 / PS1/26, paragraph 124F |
| `restructuring_exclusion_haircut` | `0.40` | `0.40` | CRR Art. 233(2) |
| `retail_commercial_re_portfolio_lgd_floor` | `0.15` | — | CRR Art. 164 |
| `retail_residential_re_portfolio_lgd_floor` | `0.10` | — | CRR Art. 164 |
| `retail_risk_weight` | `0.75` | `0.75` | CRR Art. 123 |
| `rgla_domestic_currency_rw` | `0.20` | `0.20` | CRR Art. 115 |
| `rgla_uk_devolved_rw` | `0.00` | `0.00` | CRR Art. 115 |
| `rgla_uk_local_auth_rw` | `0.20` | `0.20` | CRR Art. 115 |
| `rgla_unrated_default_rw` | `1.00` | `1.00` | CRR Art. 115 |
| `sa_ccf_default` | `0.50` | `0.50` | CRR Art. 111 |
| `sa_ccr_alpha` | `1.4` | `1.4` | CRR Art. 274(2) |
| `sa_ccr_alpha_carve_out` | `1.0` | `1.0` | CRR Art. 274(2) |
| `sa_ccr_cdo_tranche_coefficient` | `14` | `14` | CRR Art. 279a |
| `sa_ccr_cdo_tranche_numerator` | `15` | `15` | CRR Art. 279a |
| `sa_ccr_correlation_commodity` | `0.40` | `0.40` | CRR Art. 280 |
| `sa_ccr_correlation_credit_idx` | `0.80` | `0.80` | CRR Art. 280 |
| `sa_ccr_correlation_credit_sn` | `0.50` | `0.50` | CRR Art. 280 |
| `sa_ccr_correlation_equity_idx` | `0.80` | `0.80` | CRR Art. 280 |
| `sa_ccr_correlation_equity_sn` | `0.50` | `0.50` | CRR Art. 280 |
| `sa_ccr_ir_bucket_correlation_12` | `0.7` | `0.7` | CRR Art. 277a |
| `sa_ccr_ir_bucket_correlation_13` | `0.3` | `0.3` | CRR Art. 277a |
| `sa_ccr_ir_bucket_correlation_23` | `0.7` | `0.7` | CRR Art. 277a |
| `sa_ccr_option_volatility_commodity_electricity` | `1.50` | `1.50` | CRR Art. 279a |
| `sa_ccr_option_volatility_commodity_other` | `0.70` | `0.70` | CRR Art. 279a |
| `sa_ccr_option_volatility_credit_idx` | `0.80` | `0.80` | CRR Art. 279a |
| `sa_ccr_option_volatility_credit_sn` | `1.00` | `1.00` | CRR Art. 279a |
| `sa_ccr_option_volatility_equity_idx` | `0.75` | `0.75` | CRR Art. 279a |
| `sa_ccr_option_volatility_equity_sn` | `1.20` | `1.20` | CRR Art. 279a |
| `sa_ccr_option_volatility_fx` | `0.15` | `0.15` | CRR Art. 279a |
| `sa_ccr_option_volatility_ir` | `0.50` | `0.50` | CRR Art. 279a |
| `sa_ccr_start_floor_years` | `0.04` | `0.04` | CRR Art. 279b |
| `sa_ccr_supervisory_duration_rate` | `0.05` | `0.05` | CRR Art. 279b |
| `sa_ccr_supervisory_factor_equity_idx` | `0.20` | `0.20` | CRR Art. 280 |
| `sa_ccr_supervisory_factor_equity_sn` | `0.32` | `0.32` | CRR Art. 280 |
| `sa_ccr_supervisory_factor_fx` | `0.04` | `0.04` | CRR Art. 280 |
| `sa_ccr_supervisory_factor_ir` | `0.005` | `0.005` | CRR Art. 280 |
| `slotting_short_maturity_threshold_years` | `2.5` | `2.5` | CRR Art. 153(5) |

## Integer parameters

Integer counts — day floors, thresholds, band bounds (`IntParam`).

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `b31_rre_three_property_limit` | — | `3` | PS1/26, paragraph 124E |
| `failed_trade_dvp_band_16_30_lower_days` | `16` | `16` | CRR Art. 378 |
| `failed_trade_dvp_band_31_45_lower_days` | `31` | `31` | CRR Art. 378 |
| `failed_trade_dvp_band_46_plus_lower_days` | `46` | `46` | CRR Art. 378 |
| `failed_trade_dvp_band_5_15_lower_days` | `5` | `5` | CRR Art. 378 |
| `failed_trade_non_dvp_col4_lower_days` | `5` | `5` | CRR Art. 379 |
| `liquidation_period_capital_market` | `10` | `10` | CRR Art. 224 |
| `liquidation_period_repo` | `5` | `5` | CRR Art. 224 |
| `liquidation_period_secured_lending` | `20` | `20` | CRR Art. 224 |
| `mf_margined_dispute_multiplier` | `2` | `2` | CRR Art. 285 |
| `mf_margined_dispute_threshold` | `2` | `2` | CRR Art. 285 |
| `mf_margined_floor_days_large_or_illiquid` | `20` | `20` | CRR Art. 285 |
| `mf_margined_floor_days_otc` | `10` | `10` | CRR Art. 285 |
| `mf_margined_floor_days_repo_sft` | `5` | `5` | CRR Art. 285 |
| `mf_margined_large_netting_set_trade_count` | `5000` | `5000` | CRR Art. 285 |
| `mf_unmargined_floor_days` | `10` | `10` | CRR Art. 279c |
| `oc_short_maturity_threshold_days` | `365` | `365` | CRR Art. 111 |
| `sa_ccr_business_days_per_year` | `250` | `250` | CRR Art. 279c |
| `zero_haircut_max_sovereign_cqs` | `1` | `1` | CRR Art. 227 |

## Date parameters

Calendar-date parameters (`DateParam`).

| Name | CRR | Basel 3.1 | Citation |
|---|---|---|---|
| `b31_effective_date` | — | 2027-01-01 | PS1/26, paragraph 123B |

## Lookup tables

Exact-match key → value tables (`LookupTable`).

### `b31_corporate_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 122
 *((2) Table 6 corporate RW (CQS3 75%, CQS5 150%))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.75` |
| `4` | `1.00` |
| `5` | `1.50` |
| `6` | `1.50` |
| `None` | `1.00` |

### `b31_corporate_short_term_ecai_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 122
 *((3) Table 6A dedicated short-term ECAI corporate RW)*

Key column: `cqs`; default `1.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.50` |
| `5` | `1.50` |
| `6` | `1.50` |

### `b31_covered_bond_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 129
 *((4) Table 7 covered-bond RW (= CRR Table 6A))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.10` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.00` |

### `b31_covered_bond_unrated_from_scra`

**Basel 3.1 only** — PS1/26, paragraph 129
 *((5) unrated CB RW direct from issuer SCRA grade)*

Key column: `scra_grade`; default `1.00`

| Key | Value |
|---|---|
| `A_ENHANCED` | `0.15` |
| `A` | `0.20` |
| `B` | `0.35` |
| `C` | `1.00` |

### `b31_ecra_short_term_ecai_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 120
 *((2B) Table 4A dedicated short-term ECAI institution RW)*

Key column: `cqs`; default `1.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.50` |
| `5` | `1.50` |

### `b31_ecra_short_term_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 120
 *((2) Table 4 ECRA short-term (long-term rating, <=3m))*

Key column: `cqs`; default `1.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.50` |

### `b31_sa_sl_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 122A
 *(SA specialised-lending risk weights)*

Key column: `sl_type`

| Key | Value |
|---|---|
| `object_finance` | `1.00` |
| `commodities_finance` | `1.00` |
| `project_finance_pre_operational` | `1.30` |
| `project_finance_operational` | `1.00` |
| `project_finance_high_quality` | `0.80` |

### `b31_scra_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 120
 *(SCRA long-term institution RW by grade (CRE20.18-21))*

Key column: `scra_grade`; default `1.50`

| Key | Value |
|---|---|
| `A` | `0.40` |
| `A_ENHANCED` | `0.30` |
| `B` | `0.75` |
| `C` | `1.50` |

### `b31_scra_short_term_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 120
 *(Art. 120A SCRA short-term institution RW by grade)*

Key column: `scra_grade`; default `1.50`

| Key | Value |
|---|---|
| `A` | `0.20` |
| `A_ENHANCED` | `0.20` |
| `B` | `0.50` |
| `C` | `1.50` |

### `cgcb_risk_weights`

**CRR** — CRR Art. 114
 *(central govt / central bank RW by CQS)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.00` |
| `2` | `0.20` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `1.00` |

### `corporate_cqs_rw`

**CRR** — CRR Art. 122

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |

### `corporate_risk_weights`

**CRR** — CRR Art. 122
 *(Table 6 corporate RW by CQS)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.50` |
| `6` | `1.50` |
| `0` | `1.00` |

### `covered_bond_risk_weights`

**CRR** — CRR Art. 129
 *(Table 6A covered-bond RW by CQS (rated))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.10` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.00` |

### `covered_bond_unrated_derivation_b31`

**Basel 3.1 only** — PS1/26, paragraph 129
 *((5) unrated CB derivation from issuer RW (7-input))*

Key column: `issuer_institution_rw`; default `1.00`

| Key | Value |
|---|---|
| `0.20` | `0.10` |
| `0.30` | `0.15` |
| `0.40` | `0.20` |
| `0.50` | `0.25` |
| `0.75` | `0.35` |
| `1.00` | `0.50` |
| `1.50` | `1.00` |

### `covered_bond_unrated_derivation_crr`

**CRR** — CRR Art. 129
 *((5)(a)-(d) unrated CB derivation from issuer RW)*

Key column: `issuer_institution_rw`; default `1.00`

| Key | Value |
|---|---|
| `0.20` | `0.10` |
| `0.50` | `0.20` |
| `1.00` | `0.50` |
| `1.50` | `1.00` |

### `crr_short_term_ecai_risk_weights`

**CRR** — CRR Art. 131
 *(Table 7 short-term ECAI RW)*

Key column: `cqs`; default `1.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.50` |
| `5` | `1.50` |
| `6` | `1.50` |

### `eca_meip_risk_weights`

**Both regimes** — CRR Art. 137
 *((1)-(2) Table 9 ECA/MEIP score -> sovereign RW)*

Key column: `eca_meip_score`; default `1.00`

| Key | Value |
|---|---|
| `0` | `0.00` |
| `1` | `0.00` |
| `2` | `0.20` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.00` |
| `7` | `1.50` |

### `equity_irb_simple_el`

**CRR** — CRR Art. 158(7)
 *(IRB simple equity EL 0.8% div-PE/exch, 2.4% other)*

Key column: `equity_type`; default `0.024`

| Key | Value |
|---|---|
| `central_bank` | `0.0` |
| `subordinated_debt` | `0.024` |
| `private_equity_diversified` | `0.008` |
| `private_equity` | `0.024` |
| `exchange_traded` | `0.008` |
| `listed` | `0.008` |
| `government_supported` | `0.024` |
| `unlisted` | `0.024` |
| `speculative` | `0.024` |
| `ciu` | `0.024` |
| `other` | `0.024` |

### `equity_irb_simple_risk_weights`

**CRR** — CRR Art. 155
 *((2) IRB simple PE-div 190%/exch 290%/other 370%)*

Key column: `equity_type`; default `3.70`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `3.70` |
| `private_equity_diversified` | `1.90` |
| `private_equity` | `3.70` |
| `exchange_traded` | `2.90` |
| `listed` | `2.90` |
| `government_supported` | `3.70` |
| `unlisted` | `3.70` |
| `speculative` | `3.70` |
| `ciu` | `3.70` |
| `other` | `3.70` |

### `equity_sa_risk_weights`

**CRR** — CRR Art. 133
 *(Art. 133(2) 100% flat / Art. 132(2) CIU 1250%)*

Key column: `equity_type`; default `1.00`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `1.00` |
| `listed` | `1.00` |
| `exchange_traded` | `1.00` |
| `government_supported` | `1.00` |
| `unlisted` | `1.00` |
| `speculative` | `1.00` |
| `private_equity` | `1.00` |
| `private_equity_diversified` | `1.00` |
| `ciu` | `12.50` |
| `other` | `1.00` |

**Basel 3.1** — PS1/26, paragraph 133
 *(Art. 133(3)-(5) equity SA RW 250%/400%/150%)*

Key column: `equity_type`; default `2.50`

| Key | Value |
|---|---|
| `central_bank` | `0.00` |
| `subordinated_debt` | `1.50` |
| `listed` | `2.50` |
| `exchange_traded` | `2.50` |
| `government_supported` | `2.50` |
| `unlisted` | `2.50` |
| `speculative` | `4.00` |
| `private_equity` | `4.00` |
| `private_equity_diversified` | `4.00` |
| `ciu` | `12.50` |
| `other` | `2.50` |

### `firb_obs_fallback_ccf`

**CRR** — CRR Art. 166
 *((10) F-IRB fallback: FR 100%, MR/OC 50%, MLR 20%, LR 0%)*

Key column: `risk_type`; default `0.50`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.50` |
| `MLR` | `0.20` |
| `LR` | `0.00` |

### `institution_rw_b31_ecra`

**Basel 3.1 only** — PS1/26, paragraph 120
 *(Table 3 ECRA institution RW (CQS2 30%, unrated 40%))*

Key column: `cqs`; default `0.40`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.30` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `0.40` |

### `institution_rw_crr`

**CRR** — CRR Art. 120
 *(Table 3 institution RW by CQS (CQS2 50%))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `1.00` |

### `institution_rw_sovereign_derived`

**CRR** — CRR Art. 121
 *(Table 5 sovereign-derived institution RW (unrated))*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `institution_short_term_rw_b31_ecra`

**Basel 3.1 only** — PS1/26, paragraph 120
 *((2) Table 4 ECRA short-term institution RW)*

Key column: `cqs`; default `0.20`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.50` |
| `0` | `0.20` |

### `institution_short_term_rw_crr`

**CRR** — CRR Art. 120
 *((2) Table 4 short-term institution RW (<=3m))*

Key column: `cqs`; default `0.20`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.20` |
| `3` | `0.20` |
| `4` | `0.50` |
| `5` | `0.50` |
| `6` | `1.50` |
| `0` | `0.20` |

### `mdb_risk_weights_table_2b`

**CRR** — CRR Art. 117
 *((1) Table 2B non-named MDB RW by CQS)*

Key column: `cqs`; default `0.50`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.30` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |
| `0` | `0.50` |

### `min_collateralisation_thresholds`

**Both regimes** — CRR Art. 230
 *(minimum collateralisation thresholds)*

Key column: `collateral_category`; default `0.0`

| Key | Value |
|---|---|
| `financial` | `0.0` |
| `receivables` | `0.0` |
| `real_estate` | `0.30` |
| `other_physical` | `0.30` |
| `life_insurance` | `0.0` |

### `overcollateralisation_ratios`

**Both regimes** — CRR Art. 230
 *(Table 5 overcollateralisation divisors)*

Key column: `collateral_category`; default `1.0`

| Key | Value |
|---|---|
| `financial` | `1.0` |
| `receivables` | `1.25` |
| `real_estate` | `1.40` |
| `other_physical` | `1.40` |
| `life_insurance` | `1.0` |

### `pse_risk_weights_own_rating`

**CRR** — CRR Art. 116
 *((2) Table 2A PSE own-rating RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `pse_risk_weights_sovereign_derived`

**CRR** — CRR Art. 116
 *((1) Table 2 PSE sovereign-derived RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `rgla_risk_weights_own_rating`

**CRR** — CRR Art. 115
 *((1)(b) Table 1B RGLA own-rating RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `0.50` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `rgla_risk_weights_sovereign_derived`

**CRR** — CRR Art. 115
 *((1)(a) Table 1A RGLA sovereign-derived RW)*

Key column: `cqs`; default `1.00`

| Key | Value |
|---|---|
| `1` | `0.20` |
| `2` | `0.50` |
| `3` | `1.00` |
| `4` | `1.00` |
| `5` | `1.00` |
| `6` | `1.50` |

### `sa_ccf`

**CRR** — CRR Art. 111
 *(SA CCFs (Annex I): FR/FRC 100%, MR/OC 50%, MLR 20%, LR 0%)*

Key column: `risk_type`; default `0.50`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.50` |
| `MLR` | `0.20` |
| `LR` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 111
 *(Table A1 SA CCFs (OC 40% Row 5, LR/UCC 10% Row 6))*

Key column: `risk_type`; default `0.50`

| Key | Value |
|---|---|
| `FR` | `1.00` |
| `FRC` | `1.00` |
| `MR` | `0.50` |
| `MR_ISSUED` | `0.50` |
| `OC` | `0.40` |
| `MLR` | `0.20` |
| `LR` | `0.10` |

### `sa_ccr_supervisory_factors_commodity`

**Both regimes** — CRR Art. 280
 *(Table 1 commodity SF by bucket)*

Key column: `commodity_type`; default `0.18`

| Key | Value |
|---|---|
| `ELECTRICITY` | `0.40` |
| `OIL_GAS` | `0.18` |
| `METALS` | `0.18` |
| `AGRICULTURAL` | `0.18` |
| `OTHER` | `0.18` |

### `sa_ccr_supervisory_factors_credit_idx`

**Both regimes** — CRR Art. 280
 *(Table 1 index credit SF by quality)*

Key column: `credit_quality`; default `0.0106`

| Key | Value |
|---|---|
| `IG` | `0.0038` |
| `HY` | `0.0106` |

### `sa_ccr_supervisory_factors_credit_sn`

**Both regimes** — CRR Art. 280
 *(Table 1 single-name credit SF by quality)*

Key column: `credit_quality`; default `0.06`

| Key | Value |
|---|---|
| `IG` | `0.0046` |
| `HY` | `0.013` |
| `NON_RATED` | `0.06` |

### `sa_ccr_transitional_addon_phase`

**Basel 3.1 only** — PS1/26, paragraph 274
 *((2A) transitional alpha add-on phase-out 2027-2029)*

Key column: `reporting_year`; default `0`

| Key | Value |
|---|---|
| `2027` | `0.60` |
| `2028` | `0.40` |
| `2029` | `0.20` |

### `slotting_el_base`

**CRR** — CRR Art. 158(6)
 *(slotting EL rate, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.008` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B slotting EL rate (>= 2.5y))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.008` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `slotting_el_hvcre`

**CRR** — CRR Art. 158(6)
 *(HVCRE slotting EL rate (flat, no maturity split))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B HVCRE slotting EL rate (flat))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.004` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `slotting_el_short`

**CRR** — CRR Art. 158(6)
 *(slotting EL rate, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.0` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

**Basel 3.1** — PS1/26, paragraph 158
 *((6) Table B slotting EL rate (< 2.5y))*

Key column: `slotting_category`; default `0.028`

| Key | Value |
|---|---|
| `strong` | `0.0` |
| `good` | `0.004` |
| `satisfactory` | `0.028` |
| `weak` | `0.08` |
| `default` | `0.50` |

### `slotting_rw_base`

**CRR** — CRR Art. 153(5)
 *(slotting RW, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.90` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5) Table A slotting RW (>= 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.90` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_hvcre`

**CRR** — CRR Art. 153(5)
 *(HVCRE slotting RW, remaining maturity >= 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.95` |
| `good` | `1.20` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5) Table A HVCRE slotting RW (>= 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.95` |
| `good` | `1.20` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_hvcre_short`

**CRR** — CRR Art. 153(5)
 *(HVCRE slotting RW, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.95` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5)(d) Table A HVCRE slotting RW (< 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.95` |
| `satisfactory` | `1.40` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_preop`

**Basel 3.1 only** — PS1/26, paragraph 153
 *((5) Table A pre-operational PF (= operational))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.70` |
| `good` | `0.90` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

### `slotting_rw_short`

**CRR** — CRR Art. 153(5)
 *(slotting RW, remaining maturity < 2.5y)*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.50` |
| `good` | `0.70` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

**Basel 3.1** — PS1/26, paragraph 153
 *((5)(d) Table A slotting RW (< 2.5y))*

Key column: `slotting_category`; default `1.15`

| Key | Value |
|---|---|
| `strong` | `0.50` |
| `good` | `0.70` |
| `satisfactory` | `1.15` |
| `weak` | `2.50` |
| `default` | `0.00` |

## Category maps

Label → label classification maps (`CategoryMap`).

### `entity_type_to_irb_class`

**Both regimes** — CRR Art. 147
 *(IRB exposure-class mapping by entity type)*

Key column: `entity_type`

| Key | Value |
|---|---|
| `sovereign` | `central_govt_central_bank` |
| `central_bank` | `central_govt_central_bank` |
| `central_bank_ecb` | `central_govt_central_bank` |
| `rgla_sovereign` | `central_govt_central_bank` |
| `rgla_institution` | `institution` |
| `pse_sovereign` | `central_govt_central_bank` |
| `pse_institution` | `institution` |
| `mdb` | `central_govt_central_bank` |
| `mdb_named` | `central_govt_central_bank` |
| `international_org` | `central_govt_central_bank` |
| `institution` | `institution` |
| `bank` | `institution` |
| `ccp` | `institution` |
| `financial_institution` | `institution` |
| `corporate` | `corporate` |
| `company` | `corporate` |
| `individual` | `retail_other` |
| `retail` | `retail_other` |
| `natural_person` | `retail_other` |
| `specialised_lending` | `specialised_lending` |
| `equity` | `equity` |
| `covered_bond` | `covered_bond` |
| `other_cash` | `other` |
| `other_gold` | `other` |
| `other_items_in_collection` | `other` |
| `other_tangible` | `other` |
| `other_residual_lease` | `other` |
| `high_risk` | `high_risk` |
| `high_risk_venture_capital` | `high_risk` |
| `high_risk_private_equity` | `high_risk` |
| `high_risk_speculative_re` | `high_risk` |

### `entity_type_to_sa_class`

**Both regimes** — CRR Art. 112
 *(Table A2 SA exposure-class mapping by entity type)*

Key column: `entity_type`

| Key | Value |
|---|---|
| `sovereign` | `central_govt_central_bank` |
| `central_bank` | `central_govt_central_bank` |
| `central_bank_ecb` | `central_govt_central_bank` |
| `rgla_sovereign` | `rgla` |
| `rgla_institution` | `rgla` |
| `pse_sovereign` | `pse` |
| `pse_institution` | `pse` |
| `mdb` | `mdb` |
| `mdb_named` | `mdb` |
| `international_org` | `international_organisation` |
| `institution` | `institution` |
| `bank` | `institution` |
| `ccp` | `institution` |
| `financial_institution` | `institution` |
| `corporate` | `corporate` |
| `company` | `corporate` |
| `individual` | `retail_other` |
| `retail` | `retail_other` |
| `natural_person` | `retail_other` |
| `specialised_lending` | `corporate` |
| `equity` | `equity` |
| `covered_bond` | `covered_bond` |
| `other_cash` | `other` |
| `other_gold` | `other` |
| `other_items_in_collection` | `other` |
| `other_tangible` | `other` |
| `other_residual_lease` | `other` |
| `high_risk` | `high_risk` |
| `high_risk_venture_capital` | `high_risk` |
| `high_risk_private_equity` | `high_risk` |
| `high_risk_speculative_re` | `high_risk` |

### `eu_country_domestic_currency`

**Both regimes** — CRR Art. 114
 *((4)/(7) EU member-state domestic currency 0% CGCB RW)*

Key column: `country_code`

| Key | Value |
|---|---|
| `AT` | `EUR` |
| `BE` | `EUR` |
| `HR` | `EUR` |
| `CY` | `EUR` |
| `EE` | `EUR` |
| `FI` | `EUR` |
| `FR` | `EUR` |
| `DE` | `EUR` |
| `GR` | `EUR` |
| `IE` | `EUR` |
| `IT` | `EUR` |
| `LV` | `EUR` |
| `LT` | `EUR` |
| `LU` | `EUR` |
| `MT` | `EUR` |
| `NL` | `EUR` |
| `PT` | `EUR` |
| `SK` | `EUR` |
| `SI` | `EUR` |
| `ES` | `EUR` |
| `BG` | `BGN` |
| `CZ` | `CZK` |
| `DK` | `DKK` |
| `HU` | `HUF` |
| `PL` | `PLN` |
| `RO` | `RON` |
| `SE` | `SEK` |

### `obs_product_to_risk_type`

**Both regimes** — CRR Art. 111
 *(Annex I OBS product -> risk_type bucket)*

Key column: `obs_product`

| Key | Value |
|---|---|
| `ACCEPTANCE` | `FR` |
| `PERFORMANCE_BOND` | `MLR` |
| `WARRANTY` | `MLR` |
| `TENDER_BOND` | `MLR` |
| `BID_BOND` | `MLR` |
| `DOCUMENTARY_CREDIT` | `MLR` |
| `TRADE_LC` | `MLR` |

## Banded tables

Ordered threshold tables over a numeric input (`BandedTable`).

### `b31_commercial_income_ltv_bands`

**Basel 3.1 only** — PS1/26, paragraph 124I
 *((1)/(2) income-producing CRE LTV bands)*

Input column: `ltv` (band applies when input <= bound)

| Upper bound | Value |
|---|---|
| `0.80` | `1.00` |
| — | `1.10` |

### `b31_residential_income_ltv_bands`

**Basel 3.1 only** — PS1/26, paragraph 124G
 *(Table 6B income-producing RRE LTV bands)*

Input column: `ltv` (band applies when input <= bound)

| Upper bound | Value |
|---|---|
| `0.50` | `0.30` |
| `0.60` | `0.35` |
| `0.70` | `0.40` |
| `0.80` | `0.50` |
| `0.90` | `0.60` |
| `1.00` | `0.75` |
| — | `1.05` |

### `life_insurance_secured_rw_map`

**Both regimes** — CRR Art. 232
 *((3) life-insurance secured-portion RW map)*

Input column: `insurer_risk_weight` (band applies when input <= bound)

| Upper bound | Value |
|---|---|
| `0.20` | `0.20` |
| `0.50` | `0.35` |
| `1.35` | `0.70` |
| — | `1.50` |

## Schedules

Date-stepped values with carry-forward (`Schedule`).

### `equity_transitional_hr_rw`

**Basel 3.1 only** — PS1/26, paragraph 4.3
 *(transitional higher-risk equity RW (Rules 4.2/4.3))*

Before first step: `0.0`

| Effective date | Value |
|---|---|
| 2027-01-01 | `2.20` |
| 2028-01-01 | `2.80` |
| 2029-01-01 | `3.40` |
| 2030-01-01 | `4.00` |

### `equity_transitional_std_rw`

**Basel 3.1 only** — PS1/26, paragraph 4.2
 *(transitional standard equity RW (Rules 4.2/4.3))*

Before first step: `0.0`

| Effective date | Value |
|---|---|
| 2027-01-01 | `1.60` |
| 2028-01-01 | `1.90` |
| 2029-01-01 | `2.20` |
| 2030-01-01 | `2.50` |

### `output_floor_pct`

**Basel 3.1 only** — PS1/26, paragraph 92
 *((5))*

Before first step: `0.0`

| Effective date | Value |
|---|---|
| 2027-01-01 | `0.60` |
| 2028-01-01 | `0.65` |
| 2029-01-01 | `0.70` |
| 2030-01-01 | `0.725` |

## Decision tables

Multi-key decision tables (`DecisionTable`).

### `collateral_haircuts`

**CRR** — CRR Art. 224
 *(FCCM supervisory haircuts Table 1 (3 maturity bands))*

Keys: `collateral_type` , `cqs` , `maturity_band` , `is_main_index`

| Keys | Value |
|---|---|
| `cash`, `None`, `None`, `None` | `0.00` |
| `gold`, `None`, `None`, `None` | `0.15` |
| `govt_bond`, `1`, `0_1y`, `None` | `0.005` |
| `govt_bond`, `1`, `1_5y`, `None` | `0.02` |
| `govt_bond`, `1`, `5y_plus`, `None` | `0.04` |
| `govt_bond`, `2`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `2`, `1_5y`, `None` | `0.03` |
| `govt_bond`, `2`, `5y_plus`, `None` | `0.06` |
| `govt_bond`, `3`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `3`, `1_5y`, `None` | `0.03` |
| `govt_bond`, `3`, `5y_plus`, `None` | `0.06` |
| `govt_bond`, `4`, `0_1y`, `None` | `0.15` |
| `govt_bond`, `4`, `1_5y`, `None` | `0.15` |
| `govt_bond`, `4`, `5y_plus`, `None` | `0.15` |
| `corp_bond`, `1`, `0_1y`, `None` | `0.01` |
| `corp_bond`, `1`, `1_5y`, `None` | `0.04` |
| `corp_bond`, `1`, `5y_plus`, `None` | `0.08` |
| `corp_bond`, `2`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `2`, `1_5y`, `None` | `0.06` |
| `corp_bond`, `2`, `5y_plus`, `None` | `0.12` |
| `corp_bond`, `3`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `3`, `1_5y`, `None` | `0.06` |
| `corp_bond`, `3`, `5y_plus`, `None` | `0.12` |
| `securitisation`, `1`, `0_1y`, `None` | `0.02` |
| `securitisation`, `1`, `1_5y`, `None` | `0.08` |
| `securitisation`, `1`, `5y_plus`, `None` | `0.16` |
| `securitisation`, `2`, `0_1y`, `None` | `0.04` |
| `securitisation`, `2`, `1_5y`, `None` | `0.12` |
| `securitisation`, `2`, `5y_plus`, `None` | `0.24` |
| `securitisation`, `3`, `0_1y`, `None` | `0.04` |
| `securitisation`, `3`, `1_5y`, `None` | `0.12` |
| `securitisation`, `3`, `5y_plus`, `None` | `0.24` |
| `equity`, `None`, `None`, `True` | `0.15` |
| `equity`, `None`, `None`, `False` | `0.25` |
| `real_estate`, `None`, `None`, `None` | `0.00` |
| `receivables`, `None`, `None`, `None` | `0` |
| `other_physical`, `None`, `None`, `None` | `0.40` |

**Basel 3.1** — PS1/26, paragraph 224
 *(Basel 3.1 FCCM supervisory haircuts (5 maturity bands))*

Keys: `collateral_type` , `cqs` , `maturity_band` , `is_main_index`

| Keys | Value |
|---|---|
| `cash`, `None`, `None`, `None` | `0.00` |
| `gold`, `None`, `None`, `None` | `0.20` |
| `govt_bond`, `1`, `0_1y`, `None` | `0.005` |
| `govt_bond`, `1`, `1_3y`, `None` | `0.02` |
| `govt_bond`, `1`, `3_5y`, `None` | `0.02` |
| `govt_bond`, `1`, `5_10y`, `None` | `0.04` |
| `govt_bond`, `1`, `10y_plus`, `None` | `0.04` |
| `govt_bond`, `2`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `2`, `1_3y`, `None` | `0.03` |
| `govt_bond`, `2`, `3_5y`, `None` | `0.03` |
| `govt_bond`, `2`, `5_10y`, `None` | `0.06` |
| `govt_bond`, `2`, `10y_plus`, `None` | `0.06` |
| `govt_bond`, `3`, `0_1y`, `None` | `0.01` |
| `govt_bond`, `3`, `1_3y`, `None` | `0.03` |
| `govt_bond`, `3`, `3_5y`, `None` | `0.03` |
| `govt_bond`, `3`, `5_10y`, `None` | `0.06` |
| `govt_bond`, `3`, `10y_plus`, `None` | `0.06` |
| `govt_bond`, `4`, `0_1y`, `None` | `0.15` |
| `govt_bond`, `4`, `1_3y`, `None` | `0.15` |
| `govt_bond`, `4`, `3_5y`, `None` | `0.15` |
| `govt_bond`, `4`, `5_10y`, `None` | `0.15` |
| `govt_bond`, `4`, `10y_plus`, `None` | `0.15` |
| `corp_bond`, `1`, `0_1y`, `None` | `0.01` |
| `corp_bond`, `1`, `1_3y`, `None` | `0.03` |
| `corp_bond`, `1`, `3_5y`, `None` | `0.04` |
| `corp_bond`, `1`, `5_10y`, `None` | `0.06` |
| `corp_bond`, `1`, `10y_plus`, `None` | `0.12` |
| `corp_bond`, `2`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `2`, `1_3y`, `None` | `0.04` |
| `corp_bond`, `2`, `3_5y`, `None` | `0.06` |
| `corp_bond`, `2`, `5_10y`, `None` | `0.12` |
| `corp_bond`, `2`, `10y_plus`, `None` | `0.20` |
| `corp_bond`, `3`, `0_1y`, `None` | `0.02` |
| `corp_bond`, `3`, `1_3y`, `None` | `0.04` |
| `corp_bond`, `3`, `3_5y`, `None` | `0.06` |
| `corp_bond`, `3`, `5_10y`, `None` | `0.12` |
| `corp_bond`, `3`, `10y_plus`, `None` | `0.20` |
| `securitisation`, `1`, `0_1y`, `None` | `0.02` |
| `securitisation`, `1`, `1_3y`, `None` | `0.08` |
| `securitisation`, `1`, `3_5y`, `None` | `0.08` |
| `securitisation`, `1`, `5_10y`, `None` | `0.16` |
| `securitisation`, `1`, `10y_plus`, `None` | `0.16` |
| `securitisation`, `2`, `0_1y`, `None` | `0.04` |
| `securitisation`, `2`, `1_3y`, `None` | `0.12` |
| `securitisation`, `2`, `3_5y`, `None` | `0.12` |
| `securitisation`, `2`, `5_10y`, `None` | `0.24` |
| `securitisation`, `2`, `10y_plus`, `None` | `0.24` |
| `securitisation`, `3`, `0_1y`, `None` | `0.04` |
| `securitisation`, `3`, `1_3y`, `None` | `0.12` |
| `securitisation`, `3`, `3_5y`, `None` | `0.12` |
| `securitisation`, `3`, `5_10y`, `None` | `0.24` |
| `securitisation`, `3`, `10y_plus`, `None` | `0.24` |
| `equity`, `None`, `None`, `True` | `0.20` |
| `equity`, `None`, `None`, `False` | `0.30` |
| `real_estate`, `None`, `None`, `None` | `0.40` |
| `receivables`, `None`, `None`, `None` | `0.40` |
| `other_physical`, `None`, `None`, `None` | `0.40` |

### `cva_ba_single_name_hedge_correlation`

**Basel 3.1 only** — PS1/26, paragraph 4.10
 *(r_hc single-name hedge supervisory correlation)*

Keys: `cva_hedge_correlation_band`; default `0.50`

| Keys | Value |
|---|---|
| `IDENTICAL` | `1.00` |
| `LEGALLY_RELATED` | `0.80` |
| `SAME_SECTOR_REGION` | `0.50` |

### `cva_ba_supervisory_risk_weights`

**Basel 3.1 only** — PS1/26, paragraph 4.4
 *(supervisory CVA risk weight table (sector x IG/HY-NR))*

Keys: `cva_rw_sector` , `cva_rw_rating_band`; default `0.120`

| Keys | Value |
|---|---|
| `SOVEREIGN`, `IG` | `0.005` |
| `SOVEREIGN`, `HY_NR` | `0.020` |
| `LOCAL_GOVERNMENT`, `IG` | `0.010` |
| `LOCAL_GOVERNMENT`, `HY_NR` | `0.040` |
| `FINANCIAL`, `IG` | `0.050` |
| `FINANCIAL`, `HY_NR` | `0.120` |
| `PENSION_FUND`, `IG` | `0.035` |
| `PENSION_FUND`, `HY_NR` | `0.085` |
| `BASIC_MATERIALS`, `IG` | `0.030` |
| `BASIC_MATERIALS`, `HY_NR` | `0.070` |
| `CONSUMER`, `IG` | `0.030` |
| `CONSUMER`, `HY_NR` | `0.085` |
| `TECHNOLOGY`, `IG` | `0.020` |
| `TECHNOLOGY`, `HY_NR` | `0.055` |
| `HEALTHCARE`, `IG` | `0.015` |
| `HEALTHCARE`, `HY_NR` | `0.050` |
| `OTHER`, `IG` | `0.050` |
| `OTHER`, `HY_NR` | `0.120` |

### `firb_supervisory_lgd`

**CRR** — CRR Art. 161
 *(F-IRB supervisory LGD (Art. 161 / Art. 230 Table 5))*

Keys: `collateral_type` , `seniority` , `is_fse`

| Keys | Value |
|---|---|
| `unsecured`, `senior`, `False` | `0.45` |
| `unsecured`, `senior`, `True` | `0.45` |
| `unsecured`, `subordinated`, `False` | `0.75` |
| `covered_bond`, `senior`, `False` | `0.1125` |
| `financial_collateral`, `senior`, `False` | `0.00` |
| `financial_collateral`, `subordinated`, `False` | `0.00` |
| `receivables`, `senior`, `False` | `0.35` |
| `receivables`, `subordinated`, `False` | `0.65` |
| `residential_re`, `senior`, `False` | `0.35` |
| `residential_re`, `subordinated`, `False` | `0.65` |
| `commercial_re`, `senior`, `False` | `0.35` |
| `commercial_re`, `subordinated`, `False` | `0.65` |
| `other_physical`, `senior`, `False` | `0.40` |
| `other_physical`, `subordinated`, `False` | `0.70` |
| `purchased_receivables`, `senior`, `False` | `0.45` |
| `purchased_receivables`, `subordinated`, `False` | `1.00` |
| `purchased_receivables`, `dilution_risk`, `False` | `0.75` |
| `life_insurance`, `senior`, `False` | `0.40` |

**Basel 3.1** — PS1/26, paragraph 161
 *(Basel 3.1 F-IRB supervisory LGD (CRE32.9-12))*

Keys: `collateral_type` , `seniority` , `is_fse`

| Keys | Value |
|---|---|
| `unsecured`, `senior`, `False` | `0.40` |
| `unsecured`, `senior`, `True` | `0.45` |
| `unsecured`, `subordinated`, `False` | `0.75` |
| `covered_bond`, `senior`, `False` | `0.1125` |
| `financial_collateral`, `senior`, `False` | `0.00` |
| `receivables`, `senior`, `False` | `0.20` |
| `residential_re`, `senior`, `False` | `0.20` |
| `commercial_re`, `senior`, `False` | `0.20` |
| `other_physical`, `senior`, `False` | `0.25` |
| `purchased_receivables`, `senior`, `False` | `0.40` |
| `purchased_receivables`, `subordinated`, `False` | `1.00` |
| `purchased_receivables`, `dilution_risk`, `False` | `1.00` |
| `life_insurance`, `senior`, `False` | `0.40` |

## Formula parameter bundles

Named parameter sets for one formula (`FormulaParams`).

### `commercial_re_params`

**CRR** — CRR Art. 126
 *(commercial RE LTV<=50%+income 50% / else 100%)*

| Parameter | Value |
|---|---|
| `ltv_threshold` | `0.50` |
| `rw_low_ltv` | `0.50` |
| `rw_standard` | `1.00` |

### `equity_pd_floors`

**CRR** — CRR Art. 165
 *((1) minimum PDs by equity sub-type)*

| Parameter | Value |
|---|---|
| `exchange_traded_long_term` | `0.0009` |
| `non_exchange_regular_cashflow` | `0.0009` |
| `exchange_traded` | `0.0040` |
| `other` | `0.0125` |

### `equity_pd_lgd_lgd`

**CRR** — CRR Art. 165
 *((2) supervisory LGD 65% diversified PE / 90% other)*

| Parameter | Value |
|---|---|
| `private_equity_diversified` | `0.65` |
| `other` | `0.90` |

### `lgd_floors`

**CRR** — CRR Art. 164
 *(no A-IRB own-estimate LGD floor under CRR (all zero))*

| Parameter | Value |
|---|---|
| `unsecured` | `0.0` |
| `subordinated_unsecured` | `0.0` |
| `financial_collateral` | `0.0` |
| `receivables` | `0.0` |
| `commercial_real_estate` | `0.0` |
| `residential_real_estate` | `0.0` |
| `other_physical` | `0.0` |
| `retail_rre` | `0.0` |
| `retail_qrre_unsecured` | `0.0` |
| `retail_other_unsecured` | `0.0` |
| `retail_lgdu` | `0.0` |

**Basel 3.1** — PS1/26, paragraph 161
 *((5) A-IRB LGD floors (Art. 161(5) corporate / 164(4) retail))*

| Parameter | Value |
|---|---|
| `unsecured` | `0.25` |
| `subordinated_unsecured` | `0.50` |
| `financial_collateral` | `0.0` |
| `receivables` | `0.10` |
| `commercial_real_estate` | `0.10` |
| `residential_real_estate` | `0.10` |
| `other_physical` | `0.15` |
| `retail_rre` | `0.05` |
| `retail_qrre_unsecured` | `0.50` |
| `retail_other_unsecured` | `0.30` |
| `retail_lgdu` | `0.30` |

### `pd_floors`

**CRR** — CRR Art. 160(1)
 *(0.03% IRB PD floor for corporates and institutions only (retail floored separately by Art. 163(1); no CGCB floor))*

| Parameter | Value |
|---|---|
| `corporate` | `0.0003` |
| `corporate_sme` | `0.0003` |
| `sovereign` | `0` |
| `institution` | `0.0003` |
| `retail_mortgage` | `0.0003` |
| `retail_other` | `0.0003` |
| `retail_qrre_transactor` | `0.0003` |
| `retail_qrre_revolver` | `0.0003` |

**Basel 3.1** — PS1/26, paragraph 160
 *((1) differentiated IRB PD floors (Art. 160(1) wholesale / 163(1) retail))*

| Parameter | Value |
|---|---|
| `corporate` | `0.0005` |
| `corporate_sme` | `0.0005` |
| `sovereign` | `0.0005` |
| `institution` | `0.0005` |
| `retail_mortgage` | `0.0010` |
| `retail_other` | `0.0005` |
| `retail_qrre_transactor` | `0.0005` |
| `retail_qrre_revolver` | `0.0010` |

### `regulatory_thresholds`

**CRR** — CRR Art. 123
 *(EUR monetary thresholds (× EUR/GBP rate → GBP))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `50000000` |
| `sme_balance_sheet_threshold` | `43000000` |
| `sme_exposure_threshold` | `2500000` |
| `large_corporate_revenue_threshold` | `0` |
| `retail_max_exposure` | `1000000` |
| `qrre_max_limit` | `100000` |
| `lfse_total_assets_threshold` | `70000000000` |

**Basel 3.1** — PS1/26, paragraph 147
 *(PRA-native GBP thresholds (sme_balance_sheet frozen))*

| Parameter | Value |
|---|---|
| `sme_turnover_threshold` | `44000000` |
| `sme_balance_sheet_threshold` | `37547600` |
| `sme_exposure_threshold` | `0` |
| `large_corporate_revenue_threshold` | `440000000` |
| `retail_max_exposure` | `880000` |
| `qrre_max_limit` | `90000` |
| `lfse_total_assets_threshold` | `79000000000` |

### `residential_mortgage_params`

**CRR** — CRR Art. 125
 *(residential mortgage LTV<=80% 35% / excess 75%)*

| Parameter | Value |
|---|---|
| `ltv_threshold` | `0.80` |
| `rw_low_ltv` | `0.35` |
| `rw_high_ltv` | `0.75` |

### `supporting_factors_values`

**CRR** — CRR Art. 501
 *(SME 0.7619/0.85 + infrastructure 0.75 multipliers)*

| Parameter | Value |
|---|---|
| `sme_factor_under_threshold` | `0.7619` |
| `sme_factor_above_threshold` | `0.85` |
| `infrastructure_factor` | `0.75` |

**Basel 3.1** — PS1/26, paragraph 501
 *(supporting factors removed (all 1.0))*

| Parameter | Value |
|---|---|
| `sme_factor_under_threshold` | `1.0` |
| `sme_factor_above_threshold` | `1.0` |
| `infrastructure_factor` | `1.0` |

## Other entries

Shapes outside the standard vocabulary, rendered field-by-field.

### `reporting_template_set`

**CRR** — CRR Art. 430
 *(COREP CR/CCR set per Reg (EU) 2021/451 Annex I; Pillar 3 per Part Eight)*

| Field | Value |
|---|---|
| `corep` | `('c_02_00', 'c07_00', 'c08_01', 'c08_02', 'c08_03', 'c08_04', 'c08_05', 'c08_06', 'c08_07', 'c09_01', 'c09_02', 'c34_01', 'c34_02', 'c34_04', 'c34_08')` |
| `pillar3` | `('ov1', 'cr4', 'cr5', 'cr6', 'cr6a', 'cr7', 'cr7a', 'cr8', 'cr9', 'cr9_1', 'cr10', 'ccr1', 'ccr2', 'ccr3', 'ccr8')` |
| `variant` | `crr` |

**Basel 3.1** — PS1/26, paragraph 430
 *(adds OF 02.01 (output floor) + CMS1/CMS2 to the CRR reporting set)*

| Field | Value |
|---|---|
| `corep` | `('c_02_00', 'c07_00', 'c08_01', 'c08_02', 'c08_03', 'c08_04', 'c08_05', 'c08_06', 'c08_07', 'c09_01', 'c09_02', 'c34_01', 'c34_02', 'c34_04', 'c34_08', 'of_02_01')` |
| `pillar3` | `('ov1', 'cr4', 'cr5', 'cr6', 'cr6a', 'cr7', 'cr7a', 'cr8', 'cr9', 'cr9_1', 'cr10', 'ccr1', 'ccr2', 'ccr3', 'ccr8', 'cms1', 'cms2')` |
| `variant` | `b31` |

