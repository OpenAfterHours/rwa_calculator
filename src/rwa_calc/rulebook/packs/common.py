"""
Common rulebook pack — regime-invariant cited scalars.

Pipeline position:
    Base layer of both regimes (``REGIME_PACKS["crr"]`` and
    ``REGIME_PACKS["b31"]`` both start with ``"common"``); merged first by
    ``rulebook/resolve.py``, then overlaid by the regime amendment pack.

Key responsibilities:
- Hold values that do not differ between CRR and Basel 3.1 (the FX haircut,
  the SA-CCR supervisory alpha, and the Financial Collateral Simple Method
  floors — Art. 222 is retained unchanged under PRA PS1/26).

References:
- CRR Art. 224: FCCM supervisory haircuts (the FX/currency-mismatch
  haircut, 8% base).
- CRR Art. 274(2) / BCBS CRE52.1: SA-CCR default supervisory alpha (1.4).
- CRR Art. 222 / PRA PS1/26 Art. 222: Financial Collateral Simple Method
  floors and carve-outs (retained for SA exposures under Basel 3.1).
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.rulebook.model import (
    CategoryMap,
    Citation,
    IntParam,
    LookupTable,
    RuleEntry,
    ScalarParam,
)

ENTRIES: dict[str, RuleEntry] = {
    "fx_haircut": ScalarParam(
        name="fx_haircut",
        value=Decimal("0.08"),
        citation=Citation("CRR", "224"),
    ),
    # CDS restructuring-exclusion haircut (CRR Art. 233(2) / PRA PS1/26
    # Art. 233(2)): unfunded protection without restructuring as a credit event
    # is reduced by 40%. Regime-invariant (retained unchanged under Basel 3.1).
    "restructuring_exclusion_haircut": ScalarParam(
        name="restructuring_exclusion_haircut",
        value=Decimal("0.40"),
        citation=Citation("CRR", "233(2)", "credit-derivative restructuring-exclusion 40% haircut"),
    ),
    "sa_ccr_alpha": ScalarParam(
        name="sa_ccr_alpha",
        value=Decimal("1.4"),
        citation=Citation("CRR", "274(2)"),
    ),
    # CRR Art. 274(2) second sub-paragraph — alpha=1.0 carve-out for non-financial
    # / pension-scheme counterparties (EMIR Art. 2(9)/2(10)). Regime-invariant.
    "sa_ccr_alpha_carve_out": ScalarParam(
        name="sa_ccr_alpha_carve_out",
        value=Decimal("1.0"),
        citation=Citation("CRR", "274(2)", "alpha=1.0 carve-out for NFC / pension-scheme"),
    ),
    # Financial Collateral Simple Method (CRR Art. 222 / PRA PS1/26 Art. 222).
    # Single-regime: PS1/26 retains Art. 222 unchanged for SA exposures.
    "fcsm_rw_floor": ScalarParam(
        name="fcsm_rw_floor",
        value=Decimal("0.20"),
        citation=Citation("CRR", "222(1)", "minimum 20% RW floor for the secured portion"),
    ),
    "fcsm_sovereign_bond_discount": ScalarParam(
        name="fcsm_sovereign_bond_discount",
        value=Decimal("0.20"),
        citation=Citation("CRR", "222(4)(b)", "20% market-value discount on 0%-RW sovereign bonds"),
    ),
    "fcsm_sft_cmp_floor": ScalarParam(
        name="fcsm_sft_cmp_floor",
        value=Decimal("0.00"),
        citation=Citation("CRR", "222(4)(a)", "SFT zero-haircut core-market-participant floor"),
    ),
    "fcsm_sft_non_cmp_floor": ScalarParam(
        name="fcsm_sft_non_cmp_floor",
        value=Decimal("0.10"),
        citation=Citation("CRR", "222(4)(b)", "SFT zero-haircut non-CMP 10% floor"),
    ),
    "fcsm_equity_collateral_rw": ScalarParam(
        name="fcsm_equity_collateral_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "222(1)", "equity held as FCSM collateral risk-weighted at 100%"),
    ),
    # F-IRB overcollateralisation divisors and minimum collateralisation
    # thresholds (CRR Art. 230 Table 5 / CRE32.9-12). The values are
    # regime-INVARIANT; whether CRR applies them is carried by the regime
    # Features ``firb_overcollateralisation_divisor_applies`` /
    # ``firb_min_collateralisation_threshold_applies`` (Basel 3.1 replaces the
    # step-function with the continuous LGD* formula, PS1/26 Art. 230(1)).
    "overcollateralisation_ratios": LookupTable(
        name="overcollateralisation_ratios",
        entries={
            "financial": Decimal("1.0"),
            "receivables": Decimal("1.25"),
            "real_estate": Decimal("1.40"),
            "other_physical": Decimal("1.40"),
            "life_insurance": Decimal("1.0"),
        },
        key="collateral_category",
        citation=Citation("CRR", "230", "Table 5 overcollateralisation divisors"),
        default=Decimal("1.0"),
    ),
    "min_collateralisation_thresholds": LookupTable(
        name="min_collateralisation_thresholds",
        entries={
            "financial": Decimal("0.0"),
            "receivables": Decimal("0.0"),
            "real_estate": Decimal("0.30"),
            "other_physical": Decimal("0.30"),
            "life_insurance": Decimal("0.0"),
        },
        key="collateral_category",
        citation=Citation("CRR", "230", "minimum collateralisation thresholds"),
        default=Decimal("0.0"),
    ),
    # Specialised-lending slotting short-maturity split (2.5y). Regime-invariant:
    # CRR Art. 153(5) and PRA PS1/26 Art. 153(5) both split slotting RW / EL at a
    # 2.5-year remaining maturity. Consumed in engine/slotting/transforms.py.
    "slotting_short_maturity_threshold_years": ScalarParam(
        name="slotting_short_maturity_threshold_years",
        value=Decimal("2.5"),
        citation=Citation("CRR", "153(5)", "specialised-lending <2.5y short-maturity split"),
    ),
    # SA / F-IRB CCF fallbacks that do not vary by regime. The conservative
    # MR-equivalent default (50%) catches unrecognised risk_type values under
    # both CRR Art. 111 and PRA PS1/26 Table A1; the OC short-maturity override
    # (20%) maps "other commitments" to MLR when remaining maturity <= 1 year
    # (CRR Art. 111, retained under Basel 3.1). Consumed in engine/ccf.py.
    "sa_ccf_default": ScalarParam(
        name="sa_ccf_default",
        value=Decimal("0.50"),
        citation=Citation("CRR", "111", "MR-equivalent fallback for unrecognised risk_type"),
    ),
    "oc_short_maturity_ccf": ScalarParam(
        name="oc_short_maturity_ccf",
        value=Decimal("0.20"),
        citation=Citation("CRR", "111", "OC mapped to MLR (20%) when remaining maturity <= 1yr"),
    ),
    # Failed-trade settlement-risk multipliers (CRR Art. 378 / 379 / 92(3)(ca);
    # PRA PS1/26 Art. 92 — numerics unchanged). The DvP working-days-past-due
    # band BOUNDS stay as int counts in data/tables/failed_trades_multipliers.py
    # (they feed both the multiplier ladder and the regulatory_band strings in
    # engine/ccr/failed_trades.py); only the multipliers / conversion move here.
    "failed_trade_dvp_mult_5_15": ScalarParam(
        name="failed_trade_dvp_mult_5_15",
        value=Decimal("0.08"),
        citation=Citation("CRR", "378", "Table 1 DvP 5-15 working days past due"),
    ),
    "failed_trade_dvp_mult_16_30": ScalarParam(
        name="failed_trade_dvp_mult_16_30",
        value=Decimal("0.50"),
        citation=Citation("CRR", "378", "Table 1 DvP 16-30 working days past due"),
    ),
    "failed_trade_dvp_mult_31_45": ScalarParam(
        name="failed_trade_dvp_mult_31_45",
        value=Decimal("0.75"),
        citation=Citation("CRR", "378", "Table 1 DvP 31-45 working days past due"),
    ),
    "failed_trade_dvp_mult_46_plus": ScalarParam(
        name="failed_trade_dvp_mult_46_plus",
        value=Decimal("1.00"),
        citation=Citation("CRR", "378", "Table 1 DvP 46+ working days past due"),
    ),
    "failed_trade_non_dvp_col4_rw_multiplier": ScalarParam(
        name="failed_trade_non_dvp_col4_rw_multiplier",
        value=Decimal("12.50"),
        citation=Citation("CRR", "379", "(1) Table 2 Col 4 non-DvP 1250% RW => 12.5"),
    ),
    "own_funds_to_rwa_factor": ScalarParam(
        name="own_funds_to_rwa_factor",
        value=Decimal("12.5"),
        citation=Citation("CRR", "92", "(3)(ca) own-funds -> RWA conversion 1/0.08"),
    ),
    # SA-CCR supervisory option volatilities (CRR Art. 279a(2) / BCBS CRE52.47
    # Table 3) for the Black-Scholes Phi(d1) supervisory delta. Regime-invariant.
    # The two commodity volatilities are carried for table completeness; the
    # engine option-delta path does not yet distinguish commodity options.
    "sa_ccr_option_volatility_ir": ScalarParam(
        name="sa_ccr_option_volatility_ir",
        value=Decimal("0.50"),
        citation=Citation("CRR", "279a", "(2) Table 3 interest-rate option volatility"),
    ),
    "sa_ccr_option_volatility_fx": ScalarParam(
        name="sa_ccr_option_volatility_fx",
        value=Decimal("0.15"),
        citation=Citation("CRR", "279a", "(2) Table 3 FX option volatility"),
    ),
    "sa_ccr_option_volatility_credit_sn": ScalarParam(
        name="sa_ccr_option_volatility_credit_sn",
        value=Decimal("1.00"),
        citation=Citation("CRR", "279a", "(2) Table 3 single-name credit option volatility"),
    ),
    "sa_ccr_option_volatility_credit_idx": ScalarParam(
        name="sa_ccr_option_volatility_credit_idx",
        value=Decimal("0.80"),
        citation=Citation("CRR", "279a", "(2) Table 3 index credit option volatility"),
    ),
    "sa_ccr_option_volatility_equity_sn": ScalarParam(
        name="sa_ccr_option_volatility_equity_sn",
        value=Decimal("1.20"),
        citation=Citation("CRR", "279a", "(2) Table 3 single-name equity option volatility"),
    ),
    "sa_ccr_option_volatility_equity_idx": ScalarParam(
        name="sa_ccr_option_volatility_equity_idx",
        value=Decimal("0.75"),
        citation=Citation("CRR", "279a", "(2) Table 3 index equity option volatility"),
    ),
    "sa_ccr_option_volatility_commodity_electricity": ScalarParam(
        name="sa_ccr_option_volatility_commodity_electricity",
        value=Decimal("1.50"),
        citation=Citation("CRR", "279a", "(2) Table 3 electricity commodity option volatility"),
    ),
    "sa_ccr_option_volatility_commodity_other": ScalarParam(
        name="sa_ccr_option_volatility_commodity_other",
        value=Decimal("0.70"),
        citation=Citation("CRR", "279a", "(2) Table 3 other commodity option volatility"),
    ),
    # CDO tranche supervisory-delta closed-form coefficients (CRR Art. 279a(3) /
    # BCBS CRE52.43): |delta| = 15 / ((1 + 14*A) * (1 + 14*D)).
    "sa_ccr_cdo_tranche_numerator": ScalarParam(
        name="sa_ccr_cdo_tranche_numerator",
        value=Decimal("15"),
        citation=Citation("CRR", "279a", "(3) CDO tranche delta numerator"),
    ),
    "sa_ccr_cdo_tranche_coefficient": ScalarParam(
        name="sa_ccr_cdo_tranche_coefficient",
        value=Decimal("14"),
        citation=Citation("CRR", "279a", "(3) CDO tranche delta attachment/detachment coefficient"),
    ),
    # SA-CCR adjusted-notional supervisory duration (CRR Art. 279b(1)(a)):
    # SD(S,E) = (exp(-0.05*S) - exp(-0.05*E))/0.05 with S floored at 10 BD =
    # 10/250 = 0.04 year fraction. Regime-invariant.
    "sa_ccr_supervisory_duration_rate": ScalarParam(
        name="sa_ccr_supervisory_duration_rate",
        value=Decimal("0.05"),
        citation=Citation("CRR", "279b", "(1)(a) supervisory duration rate"),
    ),
    "sa_ccr_start_floor_years": ScalarParam(
        name="sa_ccr_start_floor_years",
        value=Decimal("0.04"),
        citation=Citation("CRR", "279b", "(1)(a) start-date floor 10/250 = 0.04 year fraction"),
    ),
    # SA-CCR maturity-factor scalars (CRR Art. 279c): unmargined 1-year cap /
    # denominator and the margined 3/2 (=1.5) scalar. Regime-invariant.
    "mf_unmargined_cap_years": ScalarParam(
        name="mf_unmargined_cap_years",
        value=Decimal("1.0"),
        citation=Citation("CRR", "279c", "(1)(a) unmargined MF cap = 1 year"),
    ),
    "mf_unmargined_denom_years": ScalarParam(
        name="mf_unmargined_denom_years",
        value=Decimal("1.0"),
        citation=Citation("CRR", "279c", "(1)(a) unmargined MF denominator = 1 year"),
    ),
    "mf_margined_scalar": ScalarParam(
        name="mf_margined_scalar",
        value=Decimal("1.5"),
        citation=Citation("CRR", "279c", "(1)(b) margined MF 3/2 scalar"),
    ),
    # SA-CCR PFE multiplier (CRR Art. 278(3)): floor F = 0.05 and the 2 in the
    # 2*(1-F)*AddOn denominator of the multiplier exponent.
    "pfe_multiplier_floor_f": ScalarParam(
        name="pfe_multiplier_floor_f",
        value=Decimal("0.05"),
        citation=Citation("CRR", "278", "(3) PFE multiplier floor F = 5%"),
    ),
    "pfe_aggregate_denom_coeff": ScalarParam(
        name="pfe_aggregate_denom_coeff",
        value=Decimal("2"),
        citation=Citation("CRR", "278", "(3) PFE multiplier exponent denominator coefficient"),
    ),
    # SA-CCR single-value supervisory factors (CRR Art. 280 Table 1).
    "sa_ccr_supervisory_factor_ir": ScalarParam(
        name="sa_ccr_supervisory_factor_ir",
        value=Decimal("0.005"),
        citation=Citation("CRR", "280", "Table 1 interest-rate supervisory factor"),
    ),
    "sa_ccr_supervisory_factor_fx": ScalarParam(
        name="sa_ccr_supervisory_factor_fx",
        value=Decimal("0.04"),
        citation=Citation("CRR", "280", "Table 1 FX supervisory factor"),
    ),
    "sa_ccr_supervisory_factor_equity_sn": ScalarParam(
        name="sa_ccr_supervisory_factor_equity_sn",
        value=Decimal("0.32"),
        citation=Citation("CRR", "280", "Table 1 single-name equity supervisory factor"),
    ),
    "sa_ccr_supervisory_factor_equity_idx": ScalarParam(
        name="sa_ccr_supervisory_factor_equity_idx",
        value=Decimal("0.20"),
        citation=Citation("CRR", "280", "Table 1 index equity supervisory factor"),
    ),
    # SA-CCR asset-class correlations (CRR Art. 280a credit / 280b equity /
    # 280c commodity — cited to parent Art. 280, which is in the index).
    "sa_ccr_correlation_credit_sn": ScalarParam(
        name="sa_ccr_correlation_credit_sn",
        value=Decimal("0.50"),
        citation=Citation("CRR", "280", "280a single-name credit correlation"),
    ),
    "sa_ccr_correlation_credit_idx": ScalarParam(
        name="sa_ccr_correlation_credit_idx",
        value=Decimal("0.80"),
        citation=Citation("CRR", "280", "280a index credit correlation"),
    ),
    "sa_ccr_correlation_equity_sn": ScalarParam(
        name="sa_ccr_correlation_equity_sn",
        value=Decimal("0.50"),
        citation=Citation("CRR", "280", "280b single-name equity correlation"),
    ),
    "sa_ccr_correlation_equity_idx": ScalarParam(
        name="sa_ccr_correlation_equity_idx",
        value=Decimal("0.80"),
        citation=Citation("CRR", "280", "280b index equity correlation"),
    ),
    "sa_ccr_correlation_commodity": ScalarParam(
        name="sa_ccr_correlation_commodity",
        value=Decimal("0.40"),
        citation=Citation("CRR", "280", "280c commodity correlation (0.40, NOT 0.80)"),
    ),
    # SA-CCR IR cross-bucket correlations (CRR Art. 277a(1)(a)): adjacent buckets
    # 0.70, non-adjacent (B1,B3) 0.30.
    "sa_ccr_ir_bucket_correlation_12": ScalarParam(
        name="sa_ccr_ir_bucket_correlation_12",
        value=Decimal("0.7"),
        citation=Citation("CRR", "277a", "(1)(a) IR adjacent-bucket correlation B1-B2"),
    ),
    "sa_ccr_ir_bucket_correlation_23": ScalarParam(
        name="sa_ccr_ir_bucket_correlation_23",
        value=Decimal("0.7"),
        citation=Citation("CRR", "277a", "(1)(a) IR adjacent-bucket correlation B2-B3"),
    ),
    "sa_ccr_ir_bucket_correlation_13": ScalarParam(
        name="sa_ccr_ir_bucket_correlation_13",
        value=Decimal("0.3"),
        citation=Citation("CRR", "277a", "(1)(a) IR non-adjacent-bucket correlation B1-B3"),
    ),
    # SA-CCR sub-class supervisory factors (CRR Art. 280 Table 1). String-keyed
    # by the credit-quality / commodity-bucket label; consumed in engine/ccr/pfe.py
    # via lookup_float_map.
    "sa_ccr_supervisory_factors_credit_sn": LookupTable(
        name="sa_ccr_supervisory_factors_credit_sn",
        entries={
            "IG": Decimal("0.0046"),
            "HY": Decimal("0.013"),
            "NON_RATED": Decimal("0.06"),
        },
        key="credit_quality",
        citation=Citation("CRR", "280", "Table 1 single-name credit SF by quality"),
        default=Decimal("0.06"),
    ),
    "sa_ccr_supervisory_factors_credit_idx": LookupTable(
        name="sa_ccr_supervisory_factors_credit_idx",
        entries={
            "IG": Decimal("0.0038"),
            "HY": Decimal("0.0106"),
        },
        key="credit_quality",
        citation=Citation("CRR", "280", "Table 1 index credit SF by quality"),
        default=Decimal("0.0106"),
    ),
    "sa_ccr_supervisory_factors_commodity": LookupTable(
        name="sa_ccr_supervisory_factors_commodity",
        entries={
            "ELECTRICITY": Decimal("0.40"),
            "OIL_GAS": Decimal("0.18"),
            "METALS": Decimal("0.18"),
            "AGRICULTURAL": Decimal("0.18"),
            "OTHER": Decimal("0.18"),
        },
        key="commodity_type",
        citation=Citation("CRR", "280", "Table 1 commodity SF by bucket"),
        default=Decimal("0.18"),
    ),
    # SA-CCR specific wrong-way-risk LGD override (CRR Art. 291(5)(c)): 100%.
    "ccr_wwr_specific_lgd_override": ScalarParam(
        name="ccr_wwr_specific_lgd_override",
        value=Decimal("1.0"),
        citation=Citation("CRR", "291", "(5)(c) specific WWR LGD = 100% override"),
    ),
    # =========================================================================
    # SA RISK-WEIGHT INVARIANT SCALARS
    # Regime-invariant SA risk weights — identical under CRR and PRA PS1/26.
    # =========================================================================
    # Qualifying CCP trade exposures (CRR Art. 306 / BCBS CRE54.14-15).
    "qccp_proprietary_rw": ScalarParam(
        name="qccp_proprietary_rw",
        value=Decimal("0.02"),
        citation=Citation("CRR", "306", "CRE54.14 clearing-member proprietary trades 2%"),
    ),
    "qccp_client_cleared_rw": ScalarParam(
        name="qccp_client_cleared_rw",
        value=Decimal("0.04"),
        citation=Citation("CRR", "306", "CRE54.15 client-cleared trades 4%"),
    ),
    # Other items (CRR Art. 134 / PRA PS1/26 Art. 134) — retained unchanged.
    "other_items_cash_rw": ScalarParam(
        name="other_items_cash_rw",
        value=Decimal("0.00"),
        citation=Citation("CRR", "134", "(1) cash and cash-equivalent items 0%"),
    ),
    "other_items_gold_rw": ScalarParam(
        name="other_items_gold_rw",
        value=Decimal("0.00"),
        citation=Citation("CRR", "134", "(4) gold bullion held in own vaults 0%"),
    ),
    "other_items_collection_rw": ScalarParam(
        name="other_items_collection_rw",
        value=Decimal("0.20"),
        citation=Citation("CRR", "134", "(3) items in the course of collection 20%"),
    ),
    "other_items_tangible_rw": ScalarParam(
        name="other_items_tangible_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "134", "(2) tangible assets / prepayments 100%"),
    ),
    "other_items_default_rw": ScalarParam(
        name="other_items_default_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "134", "(2) all other items 100%"),
    ),
    # High-risk items (CRR Art. 128 / PRA PS1/26 Art. 128) — 150% flat, single
    # source for both regimes (was HIGH_RISK_RW + B31_HIGH_RISK_RW).
    "high_risk_rw": ScalarParam(
        name="high_risk_rw",
        value=Decimal("1.50"),
        citation=Citation("CRR", "128", "particularly-high-risk items 150% flat"),
    ),
    # Regulatory retail (CRR Art. 123 / PRA PS1/26 Art. 123) — 75% flat.
    "retail_risk_weight": ScalarParam(
        name="retail_risk_weight",
        value=Decimal("0.75"),
        citation=Citation("CRR", "123", "regulatory retail 75% flat"),
    ),
    # ECA / MEIP direct sovereign risk weights (CRR Art. 137 Table 9). Maps the
    # minimum export-insurance-premium score (0-7) straight to a sovereign RW;
    # the engine indexes scores 0-7 explicitly, so ``default`` is inert (out-of-
    # range / null scores defer to the Art. 114 unrated 100% fallback in-engine).
    "eca_meip_risk_weights": LookupTable(
        name="eca_meip_risk_weights",
        entries={
            0: Decimal("0.00"),
            1: Decimal("0.00"),
            2: Decimal("0.20"),
            3: Decimal("0.50"),
            4: Decimal("1.00"),
            5: Decimal("1.00"),
            6: Decimal("1.00"),
            7: Decimal("1.50"),
        },
        key="eca_meip_score",
        citation=Citation("CRR", "137", "(1)-(2) Table 9 ECA/MEIP score -> sovereign RW"),
        default=Decimal("1.00"),
    ),
    # SA SOVEREIGN/PSE/RGLA/MDB/IO INVARIANT SCALARS (CRR Art. 114-118)
    "pse_short_term_rw": ScalarParam(
        name="pse_short_term_rw",
        value=Decimal("0.20"),
        citation=Citation("CRR", "116", "(3) short-term PSE 20%"),
    ),
    "pse_unrated_default_rw": ScalarParam(
        name="pse_unrated_default_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "116", "unrated PSE conservative fallback 100%"),
    ),
    "rgla_uk_devolved_rw": ScalarParam(
        name="rgla_uk_devolved_rw",
        value=Decimal("0.00"),
        citation=Citation("CRR", "115", "PRA UK devolved administrations 0%"),
    ),
    "rgla_uk_local_auth_rw": ScalarParam(
        name="rgla_uk_local_auth_rw",
        value=Decimal("0.20"),
        citation=Citation("CRR", "115", "PRA UK local authorities 20%"),
    ),
    "rgla_domestic_currency_rw": ScalarParam(
        name="rgla_domestic_currency_rw",
        value=Decimal("0.20"),
        citation=Citation("CRR", "115", "(5) domestic-currency RGLA 20%"),
    ),
    "rgla_unrated_default_rw": ScalarParam(
        name="rgla_unrated_default_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "115", "unrated RGLA conservative fallback 100%"),
    ),
    "mdb_named_zero_rw": ScalarParam(
        name="mdb_named_zero_rw",
        value=Decimal("0.00"),
        citation=Citation("CRR", "117", "(2) named MDB 0%"),
    ),
    "mdb_unrated_rw": ScalarParam(
        name="mdb_unrated_rw",
        value=Decimal("0.50"),
        citation=Citation("CRR", "117", "(1) Table 2B unrated MDB 50%"),
    ),
    "io_zero_rw": ScalarParam(
        name="io_zero_rw",
        value=Decimal("0.00"),
        citation=Citation("CRR", "118", "named international organisation 0%"),
    ),
    # SA-CCR margined maturity-factor integer counts (CRR Art. 285 MPOR cascade +
    # Art. 279c(2) business-day-year basis). Regime-invariant integer counts —
    # kept int end-to-end (the days-per-year divisor is float()-ed at the call site).
    "mf_margined_floor_days_repo_sft": IntParam(
        name="mf_margined_floor_days_repo_sft",
        value=5,
        citation=Citation("CRR", "285", "(2)(a) MPOR floor for all-SFT netting set = 5 BD"),
    ),
    "mf_margined_floor_days_otc": IntParam(
        name="mf_margined_floor_days_otc",
        value=10,
        citation=Citation("CRR", "285", "(2)(b) MPOR floor for OTC derivative netting set = 10 BD"),
    ),
    "mf_margined_floor_days_large_or_illiquid": IntParam(
        name="mf_margined_floor_days_large_or_illiquid",
        value=20,
        citation=Citation("CRR", "285", "(3) MPOR floor for large/illiquid netting set = 20 BD"),
    ),
    "mf_margined_large_netting_set_trade_count": IntParam(
        name="mf_margined_large_netting_set_trade_count",
        value=5000,
        citation=Citation("CRR", "285", "(3)(a) large netting-set trade-count threshold = 5000"),
    ),
    "mf_margined_dispute_threshold": IntParam(
        name="mf_margined_dispute_threshold",
        value=2,
        citation=Citation("CRR", "285", "(4) MPOR dispute-doubling threshold = more than 2"),
    ),
    "mf_margined_dispute_multiplier": IntParam(
        name="mf_margined_dispute_multiplier",
        value=2,
        citation=Citation("CRR", "285", "(4) MPOR dispute-doubling multiplier = 2x"),
    ),
    "sa_ccr_business_days_per_year": IntParam(
        name="sa_ccr_business_days_per_year",
        value=250,
        citation=Citation("CRR", "279c", "(2) business days per year in the MF sqrt divisor"),
    ),
    # Failed-trade settlement-risk band lower bounds in working days past due
    # (CRR Art. 378 DvP Table 1 / Art. 379 non-DvP Column 4). Integer day counts.
    "failed_trade_dvp_band_5_15_lower_days": IntParam(
        name="failed_trade_dvp_band_5_15_lower_days",
        value=5,
        citation=Citation("CRR", "378", "Table 1 DvP 5-15 working-days band lower bound"),
    ),
    "failed_trade_dvp_band_16_30_lower_days": IntParam(
        name="failed_trade_dvp_band_16_30_lower_days",
        value=16,
        citation=Citation("CRR", "378", "Table 1 DvP 16-30 working-days band lower bound"),
    ),
    "failed_trade_dvp_band_31_45_lower_days": IntParam(
        name="failed_trade_dvp_band_31_45_lower_days",
        value=31,
        citation=Citation("CRR", "378", "Table 1 DvP 31-45 working-days band lower bound"),
    ),
    "failed_trade_dvp_band_46_plus_lower_days": IntParam(
        name="failed_trade_dvp_band_46_plus_lower_days",
        value=46,
        citation=Citation("CRR", "378", "Table 1 DvP 46+ working-days band lower bound"),
    ),
    "failed_trade_non_dvp_col4_lower_days": IntParam(
        name="failed_trade_non_dvp_col4_lower_days",
        value=5,
        citation=Citation("CRR", "379", "(1) non-DvP free-delivery Column 4 t+5 lower bound"),
    ),
    # CCF / CRM integer singletons relocated from data/tables (S13-c). Both are
    # regime-invariant — CRR carries them unchanged into PS1/26 — so they live in
    # the common pack and reach both the crr and b31 resolved packs.
    "oc_short_maturity_threshold_days": IntParam(
        name="oc_short_maturity_threshold_days",
        value=365,
        citation=Citation("CRR", "111", "(1) other-commitments <=1yr maturity day boundary"),
    ),
    "zero_haircut_max_sovereign_cqs": IntParam(
        name="zero_haircut_max_sovereign_cqs",
        value=1,
        citation=Citation("CRR", "227", "(2)(a) max sovereign CQS for zero-haircut repo"),
    ),
    # CRM supervisory-haircut liquidation periods in business days (CRR Art.
    # 224(2)), relocated from data/tables (S13-h). Integer day counts feeding the
    # Art. 226(2) sqrt(T_m/10) scaling; kept int end-to-end.
    "liquidation_period_repo": IntParam(
        name="liquidation_period_repo",
        value=5,
        citation=Citation("CRR", "224", "(2) repo-style transaction liquidation period = 5 BD"),
    ),
    "liquidation_period_capital_market": IntParam(
        name="liquidation_period_capital_market",
        value=10,
        citation=Citation("CRR", "224", "(2) other capital-market liquidation period = 10 BD"),
    ),
    "liquidation_period_secured_lending": IntParam(
        name="liquidation_period_secured_lending",
        value=20,
        citation=Citation("CRR", "224", "(2) secured-lending liquidation period = 20 BD"),
    ),
    # Entity-type -> exposure-class classification maps (CRR Art. 112 SA / Art.
    # 147 IRB), relocated from data/tables (S13-d). Category labels, not rates —
    # consumed in Python via Expr.replace_strict (engine/entity_class_maps.py
    # rebinds them; each call site keeps its own replace_strict default). The
    # SA/IRB split diverges for RGLA/PSE/MDB/international_org (Art. 147(3)/(4)(b))
    # and specialised_lending (Art. 147(8)). Regime-invariant base — the Basel
    # 3.1 high-risk demotion is a classifier Feature, not a map change.
    "entity_type_to_sa_class": CategoryMap(
        name="entity_type_to_sa_class",
        key="entity_type",
        citation=Citation("CRR", "112", "Table A2 SA exposure-class mapping by entity type"),
        entries={
            "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "rgla_sovereign": ExposureClass.RGLA.value,
            "rgla_institution": ExposureClass.RGLA.value,
            "pse_sovereign": ExposureClass.PSE.value,
            "pse_institution": ExposureClass.PSE.value,
            "mdb": ExposureClass.MDB.value,
            "mdb_named": ExposureClass.MDB.value,
            "international_org": ExposureClass.INTERNATIONAL_ORGANISATION.value,
            "institution": ExposureClass.INSTITUTION.value,
            "bank": ExposureClass.INSTITUTION.value,
            "ccp": ExposureClass.INSTITUTION.value,
            "financial_institution": ExposureClass.INSTITUTION.value,
            "corporate": ExposureClass.CORPORATE.value,
            "company": ExposureClass.CORPORATE.value,
            "individual": ExposureClass.RETAIL_OTHER.value,
            "retail": ExposureClass.RETAIL_OTHER.value,
            # Art. 112(1)(h) natural-person non-SME obligors (alias of individual/retail).
            "natural_person": ExposureClass.RETAIL_OTHER.value,
            # Art. 112(1)(g): SL is a corporate sub-type under SA, not a separate class.
            "specialised_lending": ExposureClass.CORPORATE.value,
            "equity": ExposureClass.EQUITY.value,
            "covered_bond": ExposureClass.COVERED_BOND.value,
            "other_cash": ExposureClass.OTHER.value,
            "other_gold": ExposureClass.OTHER.value,
            "other_items_in_collection": ExposureClass.OTHER.value,
            "other_tangible": ExposureClass.OTHER.value,
            "other_residual_lease": ExposureClass.OTHER.value,
            # High-risk items (Art. 128): 150% unconditional (SA-only).
            "high_risk": ExposureClass.HIGH_RISK.value,
            "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
            "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
            "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
        },
    ),
    "entity_type_to_irb_class": CategoryMap(
        name="entity_type_to_irb_class",
        key="entity_type",
        citation=Citation("CRR", "147", "IRB exposure-class mapping by entity type"),
        entries={
            "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            # Art. 147(3): RGLA/PSE sovereign-equivalence under IRB.
            "rgla_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            # Art. 147(4)(b): RGLA/PSE institution treatment under IRB.
            "rgla_institution": ExposureClass.INSTITUTION.value,
            "pse_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "pse_institution": ExposureClass.INSTITUTION.value,
            "mdb": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "mdb_named": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "international_org": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
            "institution": ExposureClass.INSTITUTION.value,
            "bank": ExposureClass.INSTITUTION.value,
            "ccp": ExposureClass.INSTITUTION.value,
            "financial_institution": ExposureClass.INSTITUTION.value,
            "corporate": ExposureClass.CORPORATE.value,
            "company": ExposureClass.CORPORATE.value,
            "individual": ExposureClass.RETAIL_OTHER.value,
            "retail": ExposureClass.RETAIL_OTHER.value,
            "natural_person": ExposureClass.RETAIL_OTHER.value,
            # Art. 147(8): SL is a legitimate IRB sub-class (unlike SA).
            "specialised_lending": ExposureClass.SPECIALISED_LENDING.value,
            "equity": ExposureClass.EQUITY.value,
            "covered_bond": ExposureClass.COVERED_BOND.value,
            "other_cash": ExposureClass.OTHER.value,
            "other_gold": ExposureClass.OTHER.value,
            "other_items_in_collection": ExposureClass.OTHER.value,
            "other_tangible": ExposureClass.OTHER.value,
            "other_residual_lease": ExposureClass.OTHER.value,
            # High-risk items are SA-only — kept as HIGH_RISK label (no IRB treatment).
            "high_risk": ExposureClass.HIGH_RISK.value,
            "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
            "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
            "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
        },
    ),
    # EU member-state -> domestic currency (CRR Art. 114(4)/(7) 0% CGCB RW for
    # exposures in a member state's domestic currency), relocated from
    # data/tables (S13-e). Eurozone members map to EUR; non-euro members to their
    # national currency. Consumed in Python via Expr.replace_strict (default=None)
    # in engine/eu_sovereign.py. Regime-invariant (CRE20.9 preserves it).
    "eu_country_domestic_currency": CategoryMap(
        name="eu_country_domestic_currency",
        key="country_code",
        citation=Citation("CRR", "114", "(4)/(7) EU member-state domestic currency 0% CGCB RW"),
        entries={
            # Eurozone members (EUR)
            "AT": "EUR",
            "BE": "EUR",
            "HR": "EUR",
            "CY": "EUR",
            "EE": "EUR",
            "FI": "EUR",
            "FR": "EUR",
            "DE": "EUR",
            "GR": "EUR",
            "IE": "EUR",
            "IT": "EUR",
            "LV": "EUR",
            "LT": "EUR",
            "LU": "EUR",
            "MT": "EUR",
            "NL": "EUR",
            "PT": "EUR",
            "SK": "EUR",
            "SI": "EUR",
            "ES": "EUR",
            # Non-euro EU members
            "BG": "BGN",  # Bulgarian lev
            "CZ": "CZK",  # Czech koruna
            "DK": "DKK",  # Danish krone
            "HU": "HUF",  # Hungarian forint
            "PL": "PLN",  # Polish zloty
            "RO": "RON",  # Romanian leu
            "SE": "SEK",  # Swedish krona
        },
    ),
    # Concrete OBS product -> abstract Annex I risk_type bucket (CRR Annex I
    # paras 1-4 / Art. 111(1)), relocated from data/tables (S13-f). Category
    # labels (product key -> FR/MLR/...), not rates. Framework-invariant: every
    # product resolves to the same risk_type under CRR Annex I and PS1/26 Table
    # A1; the framework split lives downstream in the sa_ccf lookup. Consumed in
    # Python via Expr.replace_strict in engine/ccf.py (default=None for unmapped).
    "obs_product_to_risk_type": CategoryMap(
        name="obs_product_to_risk_type",
        key="obs_product",
        citation=Citation("CRR", "111", "Annex I OBS product -> risk_type bucket"),
        entries={
            # Bankers' acceptances: direct credit substitutes -> 100% CCF (FR).
            "ACCEPTANCE": "FR",
            # Non-direct-credit-substitute guarantees -> 20% (MLR), Annex I Row 6(b).
            "PERFORMANCE_BOND": "MLR",
            "WARRANTY": "MLR",
            "TENDER_BOND": "MLR",
            "BID_BOND": "MLR",
            # Self-liquidating trade-related letters of credit -> 20%, Row 6(a).
            "DOCUMENTARY_CREDIT": "MLR",
            "TRADE_LC": "MLR",
        },
    ),
}
