"""
CRR rulebook pack — pre-Basel-3.1 cited regime entries.

Pipeline position:
    Amendment layer for the ``"crr"`` regime (``REGIME_PACKS["crr"] =
    ("common", "crr")``); overlaid on the common pack by
    ``rulebook/resolve.py``, overriding any colliding entry names.

Key responsibilities:
- Hold the CRR-specific proof-pack values: the IRB K scaling factor, the
  SME/infrastructure supporting-factor feature flag, and a small CQS->RW
  lookup demonstrating the ``LookupTable`` shape.

References:
- CRR Art. 153(1): IRB risk-weight scaling factor (1.06).
- CRR Art. 501: SME supporting factor (and Art. 501a infrastructure).
- CRR Art. 122: standardised corporate risk weights by credit-quality step.
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.rulebook.model import (
    Citation,
    DecisionTable,
    Feature,
    FormulaParams,
    LookupTable,
    RuleEntry,
    ScalarParam,
)

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.06"),
        citation=Citation("CRR", "153(1)"),
    ),
    "supporting_factors": Feature(
        name="supporting_factors",
        enabled=True,
        citation=Citation("CRR", "501"),
    ),
    # CRR imposes no A-IRB own-estimate LGD floor (Art. 164 lets A-IRB firms model
    # LGD freely). The Feature gates the LGD-floor branch in engine/irb; Basel 3.1
    # overrides it to True (packs/b31.py). The lgd_floors bundle below is all-zero
    # under CRR so the gate and the values agree.
    "airb_lgd_floor": Feature(
        name="airb_lgd_floor",
        enabled=False,
        citation=Citation("CRR", "164", "no A-IRB own-estimate LGD floor under CRR"),
    ),
    # IRB maturity (M) regime treatments — Features gate only the on/off regime
    # branch; the numeric constants they gate (0.5y SFT supervisory M, the 1/365
    # one-day floor) stay engine literals. Consumed in engine/irb/transforms.py.
    "firb_sft_supervisory_maturity": Feature(
        name="firb_sft_supervisory_maturity",
        enabled=True,
        citation=Citation("CRR", "162(1)", "F-IRB fixed 0.5y supervisory M for repo-style SFTs"),
    ),
    "one_day_maturity_floor": Feature(
        name="one_day_maturity_floor",
        enabled=True,
        citation=Citation(
            "CRR", "162(3)", "one-day M floor derivation for short-term trade finance"
        ),
    ),
    "revolving_uses_termination_maturity": Feature(
        name="revolving_uses_termination_maturity",
        enabled=False,
        citation=Citation(
            "CRR", "162", "revolving facilities use the standard M derivation under CRR"
        ),
    ),
    # CRR Art. 153(3)/202-203 double-default treatment for guaranteed exposures —
    # removed under Basel 3.1. The election (config.enable_double_default) and the
    # 0.15+160xPD multiplier constant stay engine-side; only the regime gate moves.
    "double_default_treatment": Feature(
        name="double_default_treatment",
        enabled=True,
        citation=Citation("CRR", "153(3)", "double-default treatment (Art. 153(3), 202-203)"),
    ),
    # F-IRB senior unsecured supervisory LGD: CRR applies a flat 45% (Art. 161(1)(a))
    # with no financial-sector-entity split, so this is disabled. Basel 3.1 splits
    # senior unsecured into FSE 45% (Art. 161(1)(a)) vs non-FSE 40% (Art. 161(1)(aa)).
    # Gates the per-row FSE selection in engine/irb/formulas.py::apply_firb_lgd.
    "firb_fse_senior_lgd_split": Feature(
        name="firb_fse_senior_lgd_split",
        enabled=False,
        citation=Citation("CRR", "161(1)(a)", "flat 45% senior unsecured F-IRB LGD, no FSE split"),
    ),
    # IRB PD floors (CRR Art. 160(1)): a uniform 0.03% floor across every IRB
    # exposure class. Basel 3.1 differentiates these (packs/b31.py). Consumed by
    # engine/irb/formulas.py::_pd_floor_expression via compile.formula_float_map.
    "pd_floors": FormulaParams(
        name="pd_floors",
        params={
            "corporate": Decimal("0.0003"),
            "corporate_sme": Decimal("0.0003"),
            "sovereign": Decimal("0.0003"),
            "institution": Decimal("0.0003"),
            "retail_mortgage": Decimal("0.0003"),
            "retail_other": Decimal("0.0003"),
            "retail_qrre_transactor": Decimal("0.0003"),
            "retail_qrre_revolver": Decimal("0.0003"),
        },
        citation=Citation("CRR", "160(1)", "uniform 0.03% IRB PD floor"),
    ),
    # A-IRB LGD floors: all zero under CRR (no A-IRB LGD floor — see airb_lgd_floor
    # Feature). Basel 3.1 sets the Art. 161(5)/164(4) floors (packs/b31.py). Keyed
    # the same as contracts/config.py::LGDFloors so the engine projection is a
    # 1:1 byte-identical swap. Consumed by the LGD-floor builders in engine/irb.
    "lgd_floors": FormulaParams(
        name="lgd_floors",
        params={
            "unsecured": Decimal("0.0"),
            "subordinated_unsecured": Decimal("0.0"),
            "financial_collateral": Decimal("0.0"),
            "receivables": Decimal("0.0"),
            "commercial_real_estate": Decimal("0.0"),
            "residential_real_estate": Decimal("0.0"),
            "other_physical": Decimal("0.0"),
            "retail_rre": Decimal("0.0"),
            "retail_qrre_unsecured": Decimal("0.0"),
            "retail_other_unsecured": Decimal("0.0"),
            "retail_lgdu": Decimal("0.0"),
        },
        citation=Citation("CRR", "164", "no A-IRB own-estimate LGD floor under CRR (all zero)"),
    ),
    "corporate_cqs_rw": LookupTable(
        name="corporate_cqs_rw",
        entries={1: Decimal("0.20"), 2: Decimal("0.50")},
        key="cqs",
        citation=Citation("CRR", "122"),
        default=Decimal("1.00"),
    ),
    # SA base risk-weight tables: Basel 3.1 replaces the CRR Art. 112-134 tables
    # with the PS1/26 revised set (corporate Table 6 CQS3 100%->75%, institution
    # ECRA/SCRA, etc.) — see packs/b31.py. The Feature gates the combined-CQS
    # table selection in engine/sa/risk_weights.py::_prepare_risk_weight_lookup
    # and (S6c) the shared guarantor-RW builder; the table VALUES stay in
    # data/tables/{crr,b31}_risk_weights.py. CRR uses the original tables.
    "sa_revised_risk_weight_tables": Feature(
        name="sa_revised_risk_weight_tables",
        enabled=False,
        citation=Citation("CRR", "122", "original SA risk-weight tables (Art. 112-134)"),
    ),
    # PRA PS1/26 Art. 139(2B) disapplies inferred / issuer-level (non-issue-
    # specific) ECAI assessments for the SA specialised-lending routing — CRR has
    # no such disapplication. Gates the SL CQS-nulling in
    # engine/sa/risk_weights.py::_prepare_risk_weight_lookup.
    "sa_sl_inferred_rating_disapplied": Feature(
        name="sa_sl_inferred_rating_disapplied",
        enabled=False,
        citation=Citation("CRR", "139", "inferred/issuer-level ECAI assessments apply to SL"),
    ),
    # SA defaulted-exposure treatment (Art. 127): Basel 3.1 revises the unsecured
    # denominator basis (gross outstanding vs the CRR pre-provision ead_final) and
    # adds the Art. 127(3) residential-RE non-income flat-100% carve-out — see
    # packs/b31.py. The Feature gates the whole regime block in
    # engine/sa/risk_weights.py::_apply_defaulted_risk_weight; the thresholds /
    # RW values stay in data/tables/{crr,b31}_risk_weights.py.
    "sa_revised_defaulted_treatment": Feature(
        name="sa_revised_defaulted_treatment",
        enabled=False,
        citation=Citation(
            "CRR", "127", "CRR defaulted RW: pre-provision denominator, no RE carve-out"
        ),
    ),
    # Basel-3.1-only SA post-RW adjustments — absent under CRR. The currency-
    # mismatch 1.5x multiplier (PS1/26 Art. 123B) and the due-diligence RW
    # override (PS1/26 Art. 110A) gate their whole functions in
    # engine/sa/rw_adjustments.py; the multiplier/cap/hedge-floor scalars and the
    # Art. 123B(3) commencement-date check stay engine-side.
    "sa_currency_mismatch_multiplier": Feature(
        name="sa_currency_mismatch_multiplier",
        enabled=False,
        citation=Citation("CRR", "123", "no currency-mismatch multiplier under CRR"),
    ),
    "sa_due_diligence_override": Feature(
        name="sa_due_diligence_override",
        enabled=False,
        citation=Citation("CRR", "110", "no Art. 110A due-diligence RW override under CRR"),
    ),
    # Slotting (supervisory specialised-lending) risk-weight + EL-rate tables:
    # Basel 3.1 (PRA PS1/26 Art. 153(5) Table A / CRE33) revises them with HVCRE
    # and PF pre-operational splits — see packs/b31.py. The Feature selects the
    # CRR vs B31 table family in engine/slotting/transforms.py (apply_slotting_
    # weights / apply_el_rates); the VALUES stay in data/tables/{crr,b31}_slotting.
    "slotting_revised_tables": Feature(
        name="slotting_revised_tables",
        enabled=False,
        citation=Citation(
            "CRR", "153(5)", "UK CRR single slotting table (HVCRE Table 2 not onshored)"
        ),
    ),
    # Equity: under Basel 3.1 the IRB equity approaches (Art. 155(2) IRB Simple /
    # Art. 155(3) PD-LGD) are removed — all equity uses SA (CRE20.58-62). The
    # Feature gates the approach selection + the COREP transitional-approach label
    # in engine/equity/calculator.py.
    "equity_irb_approaches_available": Feature(
        name="equity_irb_approaches_available",
        enabled=True,
        citation=Citation("CRR", "155", "IRB equity approaches (Simple / PD-LGD) available"),
    ),
    # Equity SA risk weights: CRR Art. 133(2) 100% flat (250% Art. 48(4), CIU
    # 1250% Art. 132) vs Basel 3.1 Art. 133(3)-(5) 250%/400%/150%. The Feature
    # selects the CRR vs B31 SA-equity RW method; the VALUES stay in
    # data/tables/{crr,b31}_equity_rw.py.
    "equity_revised_sa_risk_weights": Feature(
        name="equity_revised_sa_risk_weights",
        enabled=False,
        citation=Citation("CRR", "133", "CRR Art. 133(2) 100% flat equity SA RW"),
    ),
    # Classifier Art. 147A IRB-approach restrictions: Basel 3.1 removes A-IRB for
    # FSE/large-corp/institution, forces sovereign-like + equity to SA, and routes
    # IPRE/HVCRE to slotting (PRA PS1/26 Art. 147A(1)) — none of which exist under
    # CRR. The Feature gates the whole Art. 147A restriction family in
    # engine/stages/classify/{approach,audit}.py; the FX-derived thresholds those
    # branches read (sme_balance_sheet, large_corporate_revenue) stay config.
    "approach_restrictions_b31_applicable": Feature(
        name="approach_restrictions_b31_applicable",
        enabled=False,
        citation=Citation("CRR", "147", "no Art. 147A IRB approach restrictions under CRR"),
    ),
    # CRR Art. 128 (150% high-risk class) was omitted from UK onshored CRR by
    # SI 2021/1078, so HIGH_RISK falls through to OTHER; Basel 3.1 re-introduces it.
    "b31_high_risk_class_applicable": Feature(
        name="b31_high_risk_class_applicable",
        enabled=False,
        citation=Citation(
            "CRR", "128", "Art. 128 high-risk class omitted from UK CRR (SI 2021/1078)"
        ),
    ),
    # Basel 3.1 Art. 124E(1)(b)/(2): natural-person RRE re-routed to income-
    # producing whole-loan above the three-property limit; no CRR equivalent.
    "b31_art_124e_three_property_limit_applies": Feature(
        name="b31_art_124e_three_property_limit_applies",
        enabled=False,
        citation=Citation("CRR", "124", "no natural-person three-property re-route under CRR"),
    ),
    # Basel 3.1 Art. 147A(1) COREP corporate sub-class split (financial-large /
    # SME / other); CRR has no exposure_subclass reporting column.
    "b31_exposure_subclass_reporting_applies": Feature(
        name="b31_exposure_subclass_reporting_applies",
        enabled=False,
        citation=Citation("CRR", "147", "no COREP corporate exposure-subclass split under CRR"),
    ),
    # IRB SME-correlation turnover basis (Art. 153(4)): CRR converts GBP turnover
    # to EUR via eur_gbp_rate then clips EUR 5-50m; Basel 3.1 uses GBP-native
    # thresholds directly (no FX conversion). The Feature selects the branch in
    # engine/irb/formulas.py::_correlation_expr_from_pd; the turnover threshold
    # VALUES (EUR 50m / GBP 44m / eur_gbp_rate) stay config-threaded (FX-derived,
    # → S11).
    "irb_correlation_sme_gbp_native": Feature(
        name="irb_correlation_sme_gbp_native",
        enabled=False,
        citation=Citation("CRR", "153(4)", "SME correlation converts GBP turnover to EUR"),
    ),
    # SA-CCR transitional alpha add-on (PRA PS1/26 Art. 274(2A)): a Basel-3.1-only
    # phase-in (2027-2029) of the α=1.4 uplift for legacy CVA-exempt non-financial
    # counterparties carved out to α=1.0. CRR has no such add-on. The Feature gates
    # the whole add-on branch in engine/ccr/pipeline_adapter.py::_attach_transitional_
    # add_on (fed via the stage adapter); the phase fractions and the 0.4 alpha
    # uplift stay engine/data constants.
    "ccr_transitional_alpha_addon_applicable": Feature(
        name="ccr_transitional_alpha_addon_applicable",
        enabled=False,
        citation=Citation("CRR", "274", "no SA-CCR transitional alpha add-on under CRR"),
    ),
    # F-IRB collateral step-functions apply under CRR (Art. 230 Table 5): the
    # overcollateralisation divisor and the 30% C*/C** minimum threshold. Basel
    # 3.1 removes both (see packs/b31.py); the divisor/threshold values
    # themselves live regime-invariantly in packs/common.py.
    "firb_overcollateralisation_divisor_applies": Feature(
        name="firb_overcollateralisation_divisor_applies",
        enabled=True,
        citation=Citation("CRR", "230", "Table 5 overcollateralisation divisor applies"),
    ),
    "firb_min_collateralisation_threshold_applies": Feature(
        name="firb_min_collateralisation_threshold_applies",
        enabled=True,
        citation=Citation("CRR", "230", "30% C*/C** minimum collateralisation threshold applies"),
    ),
    # Canonical F-IRB supervisory LGD (CRR Art. 161 / Art. 230 Table 5). One
    # table at FIRB granularity (collateral_type, seniority, is_fse) — the
    # single source for both the IRB-direct lookups (S5) and the CRM-shape
    # simple-category projection (engine/crm/expressions.py::supervisory_lgd_values).
    # CRR has no FSE split, so is_fse True == False for unsecured senior; the
    # life_insurance row is CRM-only (Art. 232(2)(b)).
    "firb_supervisory_lgd": DecisionTable(
        name="firb_supervisory_lgd",
        key_names=("collateral_type", "seniority", "is_fse"),
        rows=(
            (("unsecured", "senior", False), Decimal("0.45")),
            (("unsecured", "senior", True), Decimal("0.45")),
            (("unsecured", "subordinated", False), Decimal("0.75")),
            (("covered_bond", "senior", False), Decimal("0.1125")),
            (("financial_collateral", "senior", False), Decimal("0.00")),
            (("financial_collateral", "subordinated", False), Decimal("0.00")),
            (("receivables", "senior", False), Decimal("0.35")),
            (("receivables", "subordinated", False), Decimal("0.65")),
            (("residential_re", "senior", False), Decimal("0.35")),
            (("residential_re", "subordinated", False), Decimal("0.65")),
            (("commercial_re", "senior", False), Decimal("0.35")),
            (("commercial_re", "subordinated", False), Decimal("0.65")),
            (("other_physical", "senior", False), Decimal("0.40")),
            (("other_physical", "subordinated", False), Decimal("0.70")),
            (("purchased_receivables", "senior", False), Decimal("0.45")),
            (("purchased_receivables", "subordinated", False), Decimal("1.00")),
            (("purchased_receivables", "dilution_risk", False), Decimal("0.75")),
            (("life_insurance", "senior", False), Decimal("0.40")),
        ),
        citation=Citation("CRR", "161", "F-IRB supervisory LGD (Art. 161 / Art. 230 Table 5)"),
    ),
    # FCCM collateral-haircut maturity-band structure (CRR Art. 224 Table 1): CRR
    # uses 3 bands (0_1y / 1_5y / 5y_plus); Basel 3.1 uses 5 (0_1y / 1_3y / 3_5y /
    # 5_10y / 10y_plus) — see packs/b31.py. The Feature gates the band-classification
    # expression in engine/crm/haircuts.py::_maturity_band_expression; the haircut
    # VALUES live in the collateral_haircuts DecisionTable below (already pack-backed).
    "collateral_haircut_maturity_bands_revised": Feature(
        name="collateral_haircut_maturity_bands_revised",
        enabled=False,
        citation=Citation("CRR", "224", "FCCM 3 maturity bands (0_1y / 1_5y / 5y_plus)"),
    ),
    # FCCM supervisory haircuts (CRR Art. 224 Table 1) — 10-business-day base
    # values keyed by (collateral_type, cqs, maturity_band, is_main_index). CRR
    # uses 3 maturity bands (0_1y / 1_5y / 5y_plus). Rendered to the join lookup
    # frame by compile.decision_table_df and consumed in engine/crm/haircuts.py;
    # ``None`` key entries are the non-bond / non-equity rows (cqs / band /
    # is_main_index do not apply). cqs 2 and 3 carry identical values (Art. 224
    # Table 1 groups CQS 2-3).
    "collateral_haircuts": DecisionTable(
        name="collateral_haircuts",
        key_names=("collateral_type", "cqs", "maturity_band", "is_main_index"),
        rows=(
            (("cash", None, None, None), Decimal("0.00")),
            (("gold", None, None, None), Decimal("0.15")),
            (("govt_bond", 1, "0_1y", None), Decimal("0.005")),
            (("govt_bond", 1, "1_5y", None), Decimal("0.02")),
            (("govt_bond", 1, "5y_plus", None), Decimal("0.04")),
            (("govt_bond", 2, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 2, "1_5y", None), Decimal("0.03")),
            (("govt_bond", 2, "5y_plus", None), Decimal("0.06")),
            (("govt_bond", 3, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 3, "1_5y", None), Decimal("0.03")),
            (("govt_bond", 3, "5y_plus", None), Decimal("0.06")),
            (("govt_bond", 4, "0_1y", None), Decimal("0.15")),
            (("govt_bond", 4, "1_5y", None), Decimal("0.15")),
            (("govt_bond", 4, "5y_plus", None), Decimal("0.15")),
            (("corp_bond", 1, "0_1y", None), Decimal("0.01")),
            (("corp_bond", 1, "1_5y", None), Decimal("0.04")),
            (("corp_bond", 1, "5y_plus", None), Decimal("0.08")),
            (("corp_bond", 2, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 2, "1_5y", None), Decimal("0.06")),
            (("corp_bond", 2, "5y_plus", None), Decimal("0.12")),
            (("corp_bond", 3, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 3, "1_5y", None), Decimal("0.06")),
            (("corp_bond", 3, "5y_plus", None), Decimal("0.12")),
            (("equity", None, None, True), Decimal("0.15")),
            (("equity", None, None, False), Decimal("0.25")),
            (("real_estate", None, None, None), Decimal("0.00")),
            (("receivables", None, None, None), Decimal("0")),
            (("other_physical", None, None, None), Decimal("0.40")),
        ),
        citation=Citation("CRR", "224", "FCCM supervisory haircuts Table 1 (3 maturity bands)"),
    ),
}
