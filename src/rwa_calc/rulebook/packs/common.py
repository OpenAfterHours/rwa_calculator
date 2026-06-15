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

from rwa_calc.rulebook.model import Citation, LookupTable, RuleEntry, ScalarParam

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
}
