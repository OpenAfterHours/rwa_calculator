"""
Basel 3.1 rulebook pack — PRA PS1/26 cited regime entries.

Pipeline position:
    Amendment layer for the ``"b31"`` regime (``REGIME_PACKS["b31"] =
    ("common", "b31")``); overlaid on the common pack by
    ``rulebook/resolve.py``, overriding any colliding entry names (e.g. the
    IRB scaling factor, which Basel 3.1 removes).

Key responsibilities:
- Hold the Basel-3.1-specific proof-pack values: the removed IRB scaling
  factor (1.0), the A-IRB LGD floor and output-floor feature flags, and the
  output-floor transitional ``Schedule``.

References:
- PRA PS1/26 Art. 153(1): IRB scaling factor removed under Basel 3.1 (1.0).
- PRA PS1/26 Art. 161(5): A-IRB own-estimate LGD floors.
- PRA PS1/26 Art. 92: the aggregate output floor.
- PRA PS1/26 Art. 92(5): output-floor transitional phase-in percentages.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.rulebook.model import (
    Citation,
    DecisionTable,
    Feature,
    FormulaParams,
    RuleEntry,
    ScalarParam,
    Schedule,
)

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.0"),
        citation=Citation("PS1/26", "153(1)"),
    ),
    "airb_lgd_floor": Feature(
        name="airb_lgd_floor",
        enabled=True,
        citation=Citation("PS1/26", "161(5)"),
    ),
    # IRB maturity (M) regime treatments — see packs/crr.py. Basel 3.1 deleted the
    # CRR SFT supervisory M and the short-term-trade one-day-floor derivation, and
    # added the revolving→termination-date rule (Art. 162(2A)(k)).
    "firb_sft_supervisory_maturity": Feature(
        name="firb_sft_supervisory_maturity",
        enabled=False,
        citation=Citation(
            "PS1/26", "162", "Basel 3.1 deleted the CRR Art. 162(1) SFT supervisory M"
        ),
    ),
    "one_day_maturity_floor": Feature(
        name="one_day_maturity_floor",
        enabled=False,
        citation=Citation(
            "PS1/26", "162", "no CRR Art. 162(3) short-term-trade one-day-floor derivation"
        ),
    ),
    "revolving_uses_termination_maturity": Feature(
        name="revolving_uses_termination_maturity",
        enabled=True,
        citation=Citation(
            "PS1/26", "162(2A)(k)", "revolving facilities use the facility termination date for M"
        ),
    ),
    # Basel 3.1 removed the CRR Art. 153(3) double-default treatment.
    "double_default_treatment": Feature(
        name="double_default_treatment",
        enabled=False,
        citation=Citation("PS1/26", "153", "Basel 3.1 removed CRR double-default treatment"),
    ),
    # Basel 3.1 splits F-IRB senior unsecured supervisory LGD into FSE 45%
    # (Art. 161(1)(a)) vs non-FSE 40% (Art. 161(1)(aa)); CRR has no such split.
    # Gates the per-row FSE selection in engine/irb/formulas.py::apply_firb_lgd.
    "firb_fse_senior_lgd_split": Feature(
        name="firb_fse_senior_lgd_split",
        enabled=True,
        citation=Citation(
            "PS1/26", "161(1)(aa)", "senior unsecured F-IRB LGD FSE 45% / non-FSE 40%"
        ),
    ),
    # IRB PD floors differentiated by exposure class (PRA PS1/26 Art. 160(1)
    # wholesale / Art. 163(1) retail). Overrides the CRR uniform 0.03% bundle.
    # Consumed by engine/irb/formulas.py::_pd_floor_expression.
    "pd_floors": FormulaParams(
        name="pd_floors",
        params={
            "corporate": Decimal("0.0005"),
            "corporate_sme": Decimal("0.0005"),
            "sovereign": Decimal("0.0005"),
            "institution": Decimal("0.0005"),
            "retail_mortgage": Decimal("0.0010"),
            "retail_other": Decimal("0.0005"),
            "retail_qrre_transactor": Decimal("0.0005"),
            "retail_qrre_revolver": Decimal("0.0010"),
        },
        citation=Citation(
            "PS1/26",
            "160(1)",
            "differentiated IRB PD floors (Art. 160(1) wholesale / 163(1) retail)",
        ),
    ),
    # A-IRB LGD floors (PRA PS1/26 Art. 161(5) corporate / Art. 164(4) retail).
    # Overrides the CRR all-zero bundle; gated on by the airb_lgd_floor Feature.
    # Keyed the same as contracts/config.py::LGDFloors for a 1:1 byte-identical
    # swap. Consumed by the LGD-floor builders in engine/irb.
    "lgd_floors": FormulaParams(
        name="lgd_floors",
        params={
            "unsecured": Decimal("0.25"),
            "subordinated_unsecured": Decimal("0.50"),
            "financial_collateral": Decimal("0.0"),
            "receivables": Decimal("0.10"),
            "commercial_real_estate": Decimal("0.10"),
            "residential_real_estate": Decimal("0.10"),
            "other_physical": Decimal("0.15"),
            "retail_rre": Decimal("0.05"),
            "retail_qrre_unsecured": Decimal("0.50"),
            "retail_other_unsecured": Decimal("0.30"),
            "retail_lgdu": Decimal("0.30"),
        },
        citation=Citation(
            "PS1/26", "161(5)", "A-IRB LGD floors (Art. 161(5) corporate / 164(4) retail)"
        ),
    ),
    # Basel 3.1 revised SA base risk-weight tables (PRA PS1/26 Art. 122(2)
    # corporate Table 6, Art. 120 institution ECRA/SCRA). Overrides the CRR
    # Feature; gates the combined-CQS table selection in
    # engine/sa/risk_weights.py and (S6c) the shared guarantor-RW builder. The
    # table VALUES live in data/tables/b31_risk_weights.py.
    "sa_revised_risk_weight_tables": Feature(
        name="sa_revised_risk_weight_tables",
        enabled=True,
        citation=Citation("PS1/26", "122(2)", "Basel 3.1 revised SA risk-weight tables"),
    ),
    # PRA PS1/26 Art. 139(2B): non-issue-specific ECAI assessments are disapplied
    # for the SA specialised-lending routing — such SL exposures are treated as
    # unrated (routed through the unrated-SL RW branch).
    "sa_sl_inferred_rating_disapplied": Feature(
        name="sa_sl_inferred_rating_disapplied",
        enabled=True,
        citation=Citation("PS1/26", "139(2B)", "non-issue-specific ECAI disapplied for SL"),
    ),
    # Basel 3.1 defaulted-exposure treatment (PRA PS1/26 Art. 127 / CRE20.88):
    # gross-outstanding unsecured denominator + the Art. 127(3) residential-RE
    # non-income flat-100% carve-out. Overrides the CRR Feature; gates the regime
    # block in engine/sa/risk_weights.py::_apply_defaulted_risk_weight.
    "sa_revised_defaulted_treatment": Feature(
        name="sa_revised_defaulted_treatment",
        enabled=True,
        citation=Citation(
            "PS1/26", "127", "gross-outstanding denominator + RESI-RE non-income 100%"
        ),
    ),
    # Basel 3.1 SA post-RW adjustments. Currency-mismatch 1.5x multiplier (PRA
    # PS1/26 Art. 123B / CRE20.93) for retail/RE with an income-currency mismatch;
    # due-diligence RW override (PRA PS1/26 Art. 110A). Each Feature gates its
    # whole function in engine/sa/rw_adjustments.py.
    "sa_currency_mismatch_multiplier": Feature(
        name="sa_currency_mismatch_multiplier",
        enabled=True,
        citation=Citation("PS1/26", "123B", "1.5x retail/RE currency-mismatch multiplier"),
    ),
    "sa_due_diligence_override": Feature(
        name="sa_due_diligence_override",
        enabled=True,
        citation=Citation("PS1/26", "110A", "due-diligence RW override (RW may only increase)"),
    ),
    # Basel 3.1 revised slotting tables (PRA PS1/26 Art. 153(5) Table A / CRE33):
    # HVCRE risk-weight + EL splits and the PF pre-operational distinction.
    # Overrides the CRR Feature; selects the B31 table family in
    # engine/slotting/transforms.py.
    "slotting_revised_tables": Feature(
        name="slotting_revised_tables",
        enabled=True,
        citation=Citation("PS1/26", "153(5)", "Basel 3.1 slotting tables (HVCRE + PF pre-op)"),
    ),
    # Basel 3.1 removed the IRB equity approaches — all equity uses SA
    # (CRE20.58-62 / PRA PS1/26 Art. 133). Overrides the CRR Feature.
    "equity_irb_approaches_available": Feature(
        name="equity_irb_approaches_available",
        enabled=False,
        citation=Citation("PS1/26", "133", "Basel 3.1 removed IRB equity — all equity uses SA"),
    ),
    # Basel 3.1 equity SA risk weights (PRA PS1/26 Art. 133(3)-(5)): 250% / 400%
    # speculative / 150% subordinated. Overrides the CRR Feature.
    "equity_revised_sa_risk_weights": Feature(
        name="equity_revised_sa_risk_weights",
        enabled=True,
        citation=Citation("PS1/26", "133", "Basel 3.1 equity SA RW 250%/400%/150%"),
    ),
    # Basel 3.1 Art. 147A(1) IRB-approach restrictions: FSE/large-corp/institution
    # no A-IRB, sovereign-like + equity SA-only, IPRE/HVCRE slotting-only.
    # Overrides the CRR Feature; gates engine/stages/classify/{approach,audit}.py.
    "approach_restrictions_b31_applicable": Feature(
        name="approach_restrictions_b31_applicable",
        enabled=True,
        citation=Citation(
            "PS1/26",
            "147A",
            "Art. 147A(1) IRB approach restrictions (FSE/large-corp/institution/sovereign/IPRE)",
        ),
    ),
    # Basel 3.1 re-introduces the 150% high-risk class (PRA PS1/26 Art. 128).
    "b31_high_risk_class_applicable": Feature(
        name="b31_high_risk_class_applicable",
        enabled=True,
        citation=Citation("PS1/26", "128", "Basel 3.1 re-introduces the 150% high-risk class"),
    ),
    # Basel 3.1 Art. 124E(1)(b)/(2): natural-person RRE re-routed to income-
    # producing whole-loan (Art. 124G) above the three-property limit.
    "b31_art_124e_three_property_limit_applies": Feature(
        name="b31_art_124e_three_property_limit_applies",
        enabled=True,
        citation=Citation(
            "PS1/26", "124E", "natural-person three-property income-producing re-route"
        ),
    ),
    # Basel 3.1 Art. 147A(1) COREP corporate sub-class split (financial-large /
    # SME / other).
    "b31_exposure_subclass_reporting_applies": Feature(
        name="b31_exposure_subclass_reporting_applies",
        enabled=True,
        citation=Citation("PS1/26", "147A", "three-way corporate COREP exposure-subclass split"),
    ),
    # Basel 3.1 SME correlation uses GBP-native turnover thresholds directly, no
    # EUR FX conversion (PRA PS1/26 Art. 153(4)). Overrides the CRR Feature.
    "irb_correlation_sme_gbp_native": Feature(
        name="irb_correlation_sme_gbp_native",
        enabled=True,
        citation=Citation("PS1/26", "153(4)", "SME correlation uses GBP-native turnover, no FX"),
    ),
    # CCF regime gates (engine/ccf.py). Basel 3.1 Art. 166C: F-IRB CCFs equal SA
    # CCFs (SL slotting → SA). Art. 166D(5): A-IRB EAD floor tests. Override the CRR
    # Features; the CCF tables and the 0.5 floor multiplier stay data-layer constants.
    "firb_uses_sa_ccf": Feature(
        name="firb_uses_sa_ccf",
        enabled=True,
        citation=Citation("PS1/26", "166C", "F-IRB CCFs equal SA CCFs; Art. 147(8) SL uses SA"),
    ),
    "airb_ead_floor_applies": Feature(
        name="airb_ead_floor_applies",
        enabled=True,
        citation=Citation("PS1/26", "166D(5)", "A-IRB EAD floor tests (on-BS + 50% off-BS)"),
    ),
    # SA CCF table selection: Basel 3.1 Table A1 (OC 40%, LR 10%) vs the CRR Annex I
    # table. Overrides the CRR Feature; gates the provisions pro-rata weighting basis.
    "sa_revised_ccf_table": Feature(
        name="sa_revised_ccf_table",
        enabled=True,
        citation=Citation("PS1/26", "111(1)", "Basel 3.1 revised SA CCF table (Table A1)"),
    ),
    # SA-CCR transitional alpha add-on (PRA PS1/26 Art. 274(2A)): Basel-3.1-only
    # phase-in (2027-2029) of the α=1.4 uplift for legacy CVA-exempt non-financial
    # counterparties carved out to α=1.0. Overrides the CRR Feature; gates the
    # add-on branch in engine/ccr/pipeline_adapter.py.
    "ccr_transitional_alpha_addon_applicable": Feature(
        name="ccr_transitional_alpha_addon_applicable",
        enabled=True,
        citation=Citation(
            "PS1/26", "274(2A)", "transitional alpha add-on for legacy CVA-exempt counterparties"
        ),
    ),
    "output_floor": Feature(
        name="output_floor",
        enabled=True,
        citation=Citation("PS1/26", "92"),
    ),
    "output_floor_pct": Schedule(
        name="output_floor_pct",
        steps=(
            (date(2027, 1, 1), Decimal("0.60")),
            (date(2028, 1, 1), Decimal("0.65")),
            (date(2029, 1, 1), Decimal("0.70")),
            (date(2030, 1, 1), Decimal("0.725")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "92(5)"),
    ),
    # Basel 3.1 replaces the CRR Art. 230 F-IRB collateral step-functions with
    # the continuous LGD* formula (PS1/26 Art. 230(1)): no overcollateralisation
    # divisor and no minimum collateralisation threshold. Overrides the CRR
    # Features of the same name.
    "firb_overcollateralisation_divisor_applies": Feature(
        name="firb_overcollateralisation_divisor_applies",
        enabled=False,
        citation=Citation("PS1/26", "230(1)", "LGD* formula — no overcollateralisation divisor"),
    ),
    "firb_min_collateralisation_threshold_applies": Feature(
        name="firb_min_collateralisation_threshold_applies",
        enabled=False,
        citation=Citation(
            "PS1/26", "230(1)", "LGD* formula — no minimum collateralisation threshold"
        ),
    ),
    # Canonical F-IRB supervisory LGD under Basel 3.1 (PRA PS1/26 Art. 161 /
    # CRE32.9-12). Overrides the CRR table of the same name. Key changes:
    # non-FSE senior 45%->40% with a distinct FSE row at 45%; receivables/RE
    # 35%->20%, other physical 40%->25%, dilution risk 75%->100%; Art. 230(2)
    # drops the *_subordinated secured-portion LGDS rows. life_insurance is
    # CRM-only (Art. 232(2)(b), unchanged at 40%).
    "firb_supervisory_lgd": DecisionTable(
        name="firb_supervisory_lgd",
        key_names=("collateral_type", "seniority", "is_fse"),
        rows=(
            (("unsecured", "senior", False), Decimal("0.40")),
            (("unsecured", "senior", True), Decimal("0.45")),
            (("unsecured", "subordinated", False), Decimal("0.75")),
            (("covered_bond", "senior", False), Decimal("0.1125")),
            (("financial_collateral", "senior", False), Decimal("0.00")),
            (("receivables", "senior", False), Decimal("0.20")),
            (("residential_re", "senior", False), Decimal("0.20")),
            (("commercial_re", "senior", False), Decimal("0.20")),
            (("other_physical", "senior", False), Decimal("0.25")),
            (("purchased_receivables", "senior", False), Decimal("0.40")),
            (("purchased_receivables", "subordinated", False), Decimal("1.00")),
            (("purchased_receivables", "dilution_risk", False), Decimal("1.00")),
            (("life_insurance", "senior", False), Decimal("0.40")),
        ),
        citation=Citation("PS1/26", "161", "Basel 3.1 F-IRB supervisory LGD (CRE32.9-12)"),
    ),
    # FCCM collateral-haircut maturity-band structure: Basel 3.1 uses 5 bands
    # (0_1y / 1_3y / 3_5y / 5_10y / 10y_plus) vs the CRR 3 bands. Overrides the CRR
    # Feature; gates _maturity_band_expression in engine/crm/haircuts.py. The
    # haircut VALUES live in the collateral_haircuts DecisionTable below.
    "collateral_haircut_maturity_bands_revised": Feature(
        name="collateral_haircut_maturity_bands_revised",
        enabled=True,
        citation=Citation(
            "PS1/26", "224", "FCCM 5 maturity bands (0_1y / 1_3y / 3_5y / 5_10y / 10y_plus)"
        ),
    ),
    # Basel 3.1 FCCM supervisory haircuts (PRA PS1/26 Art. 224 Tables 1/3 /
    # CRE22.52-53). Overrides the CRR table of the same name. 5 maturity bands
    # (0_1y / 1_3y / 3_5y / 5_10y / 10y_plus); long-dated corporate steps up to
    # 12%/20%, gold 15%->20%, equity 15%/25%->20%/30%; non-financial Art. 230(2)
    # HC is 40% for all types. cqs 2 and 3 carry identical values.
    "collateral_haircuts": DecisionTable(
        name="collateral_haircuts",
        key_names=("collateral_type", "cqs", "maturity_band", "is_main_index"),
        rows=(
            (("cash", None, None, None), Decimal("0.00")),
            (("gold", None, None, None), Decimal("0.20")),
            (("govt_bond", 1, "0_1y", None), Decimal("0.005")),
            (("govt_bond", 1, "1_3y", None), Decimal("0.02")),
            (("govt_bond", 1, "3_5y", None), Decimal("0.02")),
            (("govt_bond", 1, "5_10y", None), Decimal("0.04")),
            (("govt_bond", 1, "10y_plus", None), Decimal("0.04")),
            (("govt_bond", 2, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 2, "1_3y", None), Decimal("0.03")),
            (("govt_bond", 2, "3_5y", None), Decimal("0.03")),
            (("govt_bond", 2, "5_10y", None), Decimal("0.06")),
            (("govt_bond", 2, "10y_plus", None), Decimal("0.06")),
            (("govt_bond", 3, "0_1y", None), Decimal("0.01")),
            (("govt_bond", 3, "1_3y", None), Decimal("0.03")),
            (("govt_bond", 3, "3_5y", None), Decimal("0.03")),
            (("govt_bond", 3, "5_10y", None), Decimal("0.06")),
            (("govt_bond", 3, "10y_plus", None), Decimal("0.06")),
            (("govt_bond", 4, "0_1y", None), Decimal("0.15")),
            (("govt_bond", 4, "1_3y", None), Decimal("0.15")),
            (("govt_bond", 4, "3_5y", None), Decimal("0.15")),
            (("govt_bond", 4, "5_10y", None), Decimal("0.15")),
            (("govt_bond", 4, "10y_plus", None), Decimal("0.15")),
            (("corp_bond", 1, "0_1y", None), Decimal("0.01")),
            (("corp_bond", 1, "1_3y", None), Decimal("0.03")),
            (("corp_bond", 1, "3_5y", None), Decimal("0.04")),
            (("corp_bond", 1, "5_10y", None), Decimal("0.06")),
            (("corp_bond", 1, "10y_plus", None), Decimal("0.12")),
            (("corp_bond", 2, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 2, "1_3y", None), Decimal("0.04")),
            (("corp_bond", 2, "3_5y", None), Decimal("0.06")),
            (("corp_bond", 2, "5_10y", None), Decimal("0.12")),
            (("corp_bond", 2, "10y_plus", None), Decimal("0.20")),
            (("corp_bond", 3, "0_1y", None), Decimal("0.02")),
            (("corp_bond", 3, "1_3y", None), Decimal("0.04")),
            (("corp_bond", 3, "3_5y", None), Decimal("0.06")),
            (("corp_bond", 3, "5_10y", None), Decimal("0.12")),
            (("corp_bond", 3, "10y_plus", None), Decimal("0.20")),
            (("equity", None, None, True), Decimal("0.20")),
            (("equity", None, None, False), Decimal("0.30")),
            (("real_estate", None, None, None), Decimal("0.40")),
            (("receivables", None, None, None), Decimal("0.40")),
            (("other_physical", None, None, None), Decimal("0.40")),
        ),
        citation=Citation(
            "PS1/26", "224", "Basel 3.1 FCCM supervisory haircuts (5 maturity bands)"
        ),
    ),
}
