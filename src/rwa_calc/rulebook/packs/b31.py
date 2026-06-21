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

from rwa_calc.domain.enums import CQS, EquityType
from rwa_calc.rulebook.model import (
    BandedTable,
    Citation,
    DateParam,
    DecisionTable,
    Feature,
    FormulaParams,
    IntParam,
    LookupTable,
    RuleEntry,
    ScalarParam,
    Schedule,
)

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.0"),
        citation=Citation("PS1/26", "153", "(1)"),
    ),
    # Basel 3.1 removes the CRR Art. 501/501a supporting factors. The Feature is
    # disabled (the engine returns factor=1.0 before reading values); the values
    # bundle is all-1.0 for shape parity with packs/crr.py (mirrors
    # contracts/config.py::SupportingFactors.basel_3_1()). Consumed in
    # engine/supporting_factors.py.
    "supporting_factors": Feature(
        name="supporting_factors",
        enabled=False,
        citation=Citation("PS1/26", "501", "SME/infrastructure supporting factors removed"),
    ),
    "supporting_factors_values": FormulaParams(
        name="supporting_factors_values",
        params={
            "sme_factor_under_threshold": Decimal("1.0"),
            "sme_factor_above_threshold": Decimal("1.0"),
            "infrastructure_factor": Decimal("1.0"),
        },
        citation=Citation("PS1/26", "501", "supporting factors removed (all 1.0)"),
    ),
    "airb_lgd_floor": Feature(
        name="airb_lgd_floor",
        enabled=True,
        citation=Citation("PS1/26", "161", "(5)"),
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
            "PS1/26", "162", "(2A)(k) revolving facilities use the facility termination date for M"
        ),
    ),
    # CCR/SFT synthetic-row effective-maturity rung (PS1/26 Art. 162) — see
    # packs/crr.py. Enabled under BOTH regimes: Basel 3.1 deleted only the CRR
    # Art. 162(1) fixed 0.5y SFT supervisory M (gated separately by
    # firb_sft_supervisory_maturity, off here); the sub-1y MNA floors (162(2A)(c)/(d))
    # and the daily-re-margin one-day override (162(3)) survive. Declared here so
    # pack.feature("ccr_synthetic_maturity") never KeyErrors under b31.
    "ccr_synthetic_maturity": Feature(
        name="ccr_synthetic_maturity",
        enabled=True,
        citation=Citation("PS1/26", "162", "CCR/SFT synthetic-row MNA & one-day maturity floors"),
    ),
    # PS1/26 Art. 162(2A)(c)/(d): Basel 3.1 gates the 10BD/5BD intermediate maturity
    # floors on a "daily re-margining OR revaluation AND prompt-liquidation/set-off"
    # documentation condition (the OR is distinct from 162(3)'s AND). So the daily
    # condition IS required under B31 (enabled=True); an MNA repo/deriv lacking
    # qualifies_mna_intermediate_floor falls to the 162(2A)(f) 1-year catch-all.
    # CRR (crr.py) sets this False (floors apply on MNA alone).
    "mna_intermediate_floor_requires_daily_condition": Feature(
        name="mna_intermediate_floor_requires_daily_condition",
        enabled=True,
        citation=Citation(
            "PS1/26", "162", "(2A)(c)/(d) B31 gates 5BD/10BD floors on a daily condition"
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
            "PS1/26", "161", "(1)(aa) senior unsecured F-IRB LGD FSE 45% / non-FSE 40%"
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
            "160",
            "(1) differentiated IRB PD floors (Art. 160(1) wholesale / 163(1) retail)",
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
            "PS1/26", "161", "(5) A-IRB LGD floors (Art. 161(5) corporate / 164(4) retail)"
        ),
    ),
    # Basel 3.1 revised SA base risk-weight tables (PRA PS1/26 Art. 122(2)
    # corporate Table 6, Art. 120 institution ECRA/SCRA). Overrides the CRR
    # Feature; gates the combined-CQS table selection in
    # engine/sa/risk_weights.py and (S6c) the shared guarantor-RW builder. The
    # table VALUES live in this pack; the pack-bound table builders that read
    # them back live in engine/sa/b31_risk_weight_tables.py.
    "sa_revised_risk_weight_tables": Feature(
        name="sa_revised_risk_weight_tables",
        enabled=True,
        citation=Citation("PS1/26", "122", "(2) Basel 3.1 revised SA risk-weight tables"),
    ),
    # Basel 3.1 revised SA risk-weight override ladder (PRA PS1/26): the PS1/26
    # institution ECRA/SCRA branches, revised covered-bond/real-estate handling,
    # the currency-mismatch multiplier hook and the Art. 128 high-risk
    # reintroduction. Overrides the CRR Feature; gates the top-level override-ladder
    # dispatch in engine/sa/risk_weights.py::apply_risk_weights.
    "sa_revised_risk_weight_overrides": Feature(
        name="sa_revised_risk_weight_overrides",
        enabled=True,
        citation=Citation("PS1/26", "122", "Basel 3.1 revised SA risk-weight override ladder"),
    ),
    # PRA PS1/26 Art. 139(2B): non-issue-specific ECAI assessments are disapplied
    # for the SA specialised-lending routing — such SL exposures are treated as
    # unrated (routed through the unrated-SL RW branch).
    "sa_sl_inferred_rating_disapplied": Feature(
        name="sa_sl_inferred_rating_disapplied",
        enabled=True,
        citation=Citation("PS1/26", "139", "(2B) non-issue-specific ECAI disapplied for SL"),
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
    # SA RE loan-split regime gates. Basel 3.1 (PS1/26 Art. 124F/124H) drops the CRE
    # rental-coverage test, adds the Art. 124(4) all-or-nothing mixed-RE gate, and
    # adds the Art. 124H(3) pure-CRE whole-loan path. Override the CRR Features; the
    # split parameter VALUES live in data/tables/re_split_parameters.py (S9g).
    "sa_re_split_cre_rental_coverage_required": Feature(
        name="sa_re_split_cre_rental_coverage_required",
        enabled=False,
        citation=Citation(
            "PS1/26", "124H", "Basel 3.1 removes the CRE rental-coverage requirement"
        ),
    ),
    "sa_re_split_art_124_4_all_or_nothing": Feature(
        name="sa_re_split_art_124_4_all_or_nothing",
        enabled=True,
        citation=Citation(
            "PS1/26", "124", "(4) mixed-RE with any non-qualifying component drops to Art. 124J"
        ),
    ),
    "sa_re_split_whole_loan_path_applies": Feature(
        name="sa_re_split_whole_loan_path_applies",
        enabled=True,
        citation=Citation(
            "PS1/26", "124H", "(3) pure-CRE non-NP/SME corporates route to a whole-loan row"
        ),
    ),
    # RE loan-split parameter set selection: Basel 3.1 Art. 124F/124H LTV caps / RW
    # (RRE 55%/20%, CRE 55%/60%, prior-charge reduction) override the CRR Art. 125/126
    # values. The VALUES live in data/tables/re_split_parameters.py.
    "sa_re_split_revised_parameters": Feature(
        name="sa_re_split_revised_parameters",
        enabled=True,
        citation=Citation(
            "PS1/26", "124F", "Basel 3.1 Art. 124F/124H RE-split LTV caps and risk weights"
        ),
    ),
    # SA RE loan-split secured-LTV caps. Basel 3.1 (PS1/26 Art. 124F RRE /
    # Art. 124H CRE) revises both caps to 55% of property value (less prior
    # charges per Art. 124F(2)/124H(2)). Override the CRR Art. 125/126 caps.
    "re_split_rre_secured_ltv_cap": ScalarParam(
        name="re_split_rre_secured_ltv_cap",
        value=Decimal("0.55"),
        citation=Citation("PS1/26", "124F", "RRE preferential RW up to 55% of value"),
    ),
    "re_split_cre_secured_ltv_cap": ScalarParam(
        name="re_split_cre_secured_ltv_cap",
        value=Decimal("0.55"),
        citation=Citation("PS1/26", "124H", "CRE preferential RW up to 55% of value"),
    ),
    # PRA PS1/26 Art. 111 Table A1 SA CCFs: OC 40% (Row 5) + LR/UCC 10% (Row 6)
    # override the CRR values; FR/FRC/MR/MLR unchanged. Full table (b31 = common
    # + b31 overlay, so it cannot partially inherit the crr entry).
    "sa_ccf": LookupTable(
        name="sa_ccf",
        entries={
            "FR": Decimal("1.00"),
            "FRC": Decimal("1.00"),
            "MR": Decimal("0.50"),
            "MR_ISSUED": Decimal("0.50"),
            "OC": Decimal("0.40"),
            "MLR": Decimal("0.20"),
            "LR": Decimal("0.10"),
        },
        key="risk_type",
        citation=Citation("PS1/26", "111", "Table A1 SA CCFs (OC 40% Row 5, LR/UCC 10% Row 6)"),
        default=Decimal("0.50"),
    ),
    # PRA PS1/26 Art. 274(2A) transitional alpha add-on phase fractions keyed by
    # reporting year (Basel 3.1 only). Years absent from the table (2030+) resolve
    # to 0 via .get(year, 0.0) in engine/ccr/pipeline_adapter.py.
    "sa_ccr_transitional_addon_phase": LookupTable(
        name="sa_ccr_transitional_addon_phase",
        entries={
            2027: Decimal("0.60"),
            2028: Decimal("0.40"),
            2029: Decimal("0.20"),
        },
        key="reporting_year",
        citation=Citation("PS1/26", "274", "(2A) transitional alpha add-on phase-out 2027-2029"),
        default=Decimal("0"),
    ),
    # Basel 3.1 revised slotting tables (PRA PS1/26 Art. 153(5) Table A / CRE33):
    # HVCRE risk-weight + EL splits and the PF pre-operational distinction.
    # Overrides the CRR Feature; selects the B31 table family in
    # engine/slotting/transforms.py.
    "slotting_revised_tables": Feature(
        name="slotting_revised_tables",
        enabled=True,
        citation=Citation("PS1/26", "153", "(5) Basel 3.1 slotting tables (HVCRE + PF pre-op)"),
    ),
    # Basel 3.1 specialised-lending slotting risk weights (PS1/26 Art. 153(5)
    # Table A) + EL rates (Art. 158(6) Table B). String-keyed by SlottingCategory
    # value; OVERRIDE the crr slotting_* entries via overlay. slotting_rw_preop is
    # b31-only (PRA keeps pre-op PF at the standard Table A weights — no CRR twin).
    # Consumed by engine/slotting/transforms.py via compile.lookup_float_map.
    "slotting_rw_base": LookupTable(
        name="slotting_rw_base",
        entries={
            "strong": Decimal("0.70"),
            "good": Decimal("0.90"),
            "satisfactory": Decimal("1.15"),
            "weak": Decimal("2.50"),
            "default": Decimal("0.00"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "153", "(5) Table A slotting RW (>= 2.5y)"),
        default=Decimal("1.15"),
    ),
    "slotting_rw_short": LookupTable(
        name="slotting_rw_short",
        entries={
            "strong": Decimal("0.50"),
            "good": Decimal("0.70"),
            "satisfactory": Decimal("1.15"),
            "weak": Decimal("2.50"),
            "default": Decimal("0.00"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "153", "(5)(d) Table A slotting RW (< 2.5y)"),
        default=Decimal("1.15"),
    ),
    "slotting_rw_preop": LookupTable(
        name="slotting_rw_preop",
        entries={
            "strong": Decimal("0.70"),
            "good": Decimal("0.90"),
            "satisfactory": Decimal("1.15"),
            "weak": Decimal("2.50"),
            "default": Decimal("0.00"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "153", "(5) Table A pre-operational PF (= operational)"),
        default=Decimal("1.15"),
    ),
    "slotting_rw_hvcre": LookupTable(
        name="slotting_rw_hvcre",
        entries={
            "strong": Decimal("0.95"),
            "good": Decimal("1.20"),
            "satisfactory": Decimal("1.40"),
            "weak": Decimal("2.50"),
            "default": Decimal("0.00"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "153", "(5) Table A HVCRE slotting RW (>= 2.5y)"),
        default=Decimal("1.15"),
    ),
    "slotting_rw_hvcre_short": LookupTable(
        name="slotting_rw_hvcre_short",
        entries={
            "strong": Decimal("0.70"),
            "good": Decimal("0.95"),
            "satisfactory": Decimal("1.40"),
            "weak": Decimal("2.50"),
            "default": Decimal("0.00"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "153", "(5)(d) Table A HVCRE slotting RW (< 2.5y)"),
        default=Decimal("1.15"),
    ),
    "slotting_el_base": LookupTable(
        name="slotting_el_base",
        entries={
            "strong": Decimal("0.004"),
            "good": Decimal("0.008"),
            "satisfactory": Decimal("0.028"),
            "weak": Decimal("0.08"),
            "default": Decimal("0.50"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "158", "(6) Table B slotting EL rate (>= 2.5y)"),
        default=Decimal("0.028"),
    ),
    "slotting_el_short": LookupTable(
        name="slotting_el_short",
        entries={
            "strong": Decimal("0.0"),
            "good": Decimal("0.004"),
            "satisfactory": Decimal("0.028"),
            "weak": Decimal("0.08"),
            "default": Decimal("0.50"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "158", "(6) Table B slotting EL rate (< 2.5y)"),
        default=Decimal("0.028"),
    ),
    "slotting_el_hvcre": LookupTable(
        name="slotting_el_hvcre",
        entries={
            "strong": Decimal("0.004"),
            "good": Decimal("0.004"),
            "satisfactory": Decimal("0.028"),
            "weak": Decimal("0.08"),
            "default": Decimal("0.50"),
        },
        key="slotting_category",
        citation=Citation("PS1/26", "158", "(6) Table B HVCRE slotting EL rate (flat)"),
        default=Decimal("0.028"),
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
    # Basel 3.1 SA equity risk weights (PRA PS1/26 Art. 133(3)-(5)): standard 250%,
    # higher-risk PE/VC/speculative 400%, subordinated 150%, central bank 0%, CIU
    # 1250% (Art. 132(2)). OVERRIDES the crr equity_sa_risk_weights via overlay.
    # Enum (EquityType)-keyed; consumed via compile.lookup_float_map.
    "equity_sa_risk_weights": LookupTable(
        name="equity_sa_risk_weights",
        entries={
            EquityType.CENTRAL_BANK: Decimal("0.00"),
            EquityType.SUBORDINATED_DEBT: Decimal("1.50"),
            EquityType.LISTED: Decimal("2.50"),
            EquityType.EXCHANGE_TRADED: Decimal("2.50"),
            EquityType.GOVERNMENT_SUPPORTED: Decimal("2.50"),
            EquityType.UNLISTED: Decimal("2.50"),
            EquityType.SPECULATIVE: Decimal("4.00"),
            EquityType.PRIVATE_EQUITY: Decimal("4.00"),
            EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("4.00"),
            EquityType.CIU: Decimal("12.50"),
            EquityType.OTHER: Decimal("2.50"),
        },
        key="equity_type",
        citation=Citation("PS1/26", "133", "Art. 133(3)-(5) equity SA RW 250%/400%/150%"),
        default=Decimal("2.50"),
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
    # Basel 3.1 Art. 123A two-path retail qualification — see packs/crr.py. Gates the
    # B31 SME-auto-qualify + threshold/granularity limbs in
    # engine/stages/classify/attributes.py::_build_qualifies_as_retail_expr.
    "retail_art_123a_two_path_applicable": Feature(
        name="retail_art_123a_two_path_applicable",
        enabled=True,
        citation=Citation("PS1/26", "123A", "two-path retail qualification (SME + granularity)"),
    ),
    # Basel 3.1 regulatory monetary thresholds — PRA-native GBP values (Art. 147(5A) /
    # 147A(1)(d) / 153(4)), EXCEPT sme_balance_sheet which PS1/26 does not restate, so it
    # stays the Commission Rec 2003/361/EC EUR 43m converted at the default 0.8732. B31
    # never FX-syncs (config.py builds B31 thresholds at the fixed 0.8732), so
    # 43m × 0.8732 = 37547600 is frozen byte-identically. The Feature is False (values are
    # final GBP, no × rate). Mirrors RegulatoryThresholds.basel_3_1(0.8732) field-for-field.
    "regulatory_thresholds": FormulaParams(
        name="regulatory_thresholds",
        params={
            "sme_turnover_threshold": Decimal("44000000"),  # GBP 44m (Art. 153(4))
            "sme_balance_sheet_threshold": Decimal("37547600"),  # EUR 43m × 0.8732 (frozen)
            "sme_exposure_threshold": Decimal("0"),  # n/a under Basel 3.1
            "large_corporate_revenue_threshold": Decimal("440000000"),  # GBP 440m (Art. 147A(1)(d))
            "retail_max_exposure": Decimal("880000"),  # GBP 880k (Art. 147(5A))
            "qrre_max_limit": Decimal("90000"),  # GBP 90k (Art. 147(5A)(c))
            "lfse_total_assets_threshold": Decimal("0"),  # n/a under Basel 3.1
        },
        citation=Citation("PS1/26", "147", "PRA-native GBP thresholds (sme_balance_sheet frozen)"),
    ),
    "regulatory_thresholds_fx_derived": Feature(
        name="regulatory_thresholds_fx_derived",
        enabled=False,
        citation=Citation("PS1/26", "147", "Basel 3.1 thresholds are native GBP, no FX conversion"),
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
        citation=Citation("PS1/26", "153", "(4) SME correlation uses GBP-native turnover, no FX"),
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
        citation=Citation("PS1/26", "166D", "(5) A-IRB EAD floor tests (on-BS + 50% off-BS)"),
    ),
    # A-IRB own-estimate CCF floor (PRA PS1/26 Art. 166D(1) / BCBS CRE32.27):
    # own-estimate CCFs for eligible revolving facilities are floored at 50% of
    # the SA CCF for the same item type. Read in engine/ccf.py::_compute_ccf
    # (Basel-3.1-only; the CRR path uses the raw modelled CCF). Gated by the
    # firb_uses_sa_ccf Feature above.
    "airb_revolving_ccf_floor_multiplier": ScalarParam(
        name="airb_revolving_ccf_floor_multiplier",
        value=Decimal("0.5"),
        citation=Citation("PS1/26", "166D", "(1) own-estimate CCF floor 50% of SA CCF (CRE32.27)"),
    ),
    # A-IRB facility-level EAD floor multiplier (PRA PS1/26 Art. 166D(5)(b)): the
    # Art. 166D(3) single-EAD approach floors EAD at on-BS EAD + 50% of the
    # off-BS EAD measured at the F-IRB CCF. Read in engine/ccf.py::_compute_ead,
    # gated by the airb_ead_floor_applies Feature above.
    "airb_obs_floor_b_multiplier": ScalarParam(
        name="airb_obs_floor_b_multiplier",
        value=Decimal("0.5"),
        citation=Citation("PS1/26", "166D", "(5)(b) facility-level EAD floor — on-BS + 50% off-BS"),
    ),
    # SA CCF table selection: Basel 3.1 Table A1 (OC 40%, LR 10%) vs the CRR Annex I
    # table. Overrides the CRR Feature; gates the provisions pro-rata weighting basis.
    "sa_revised_ccf_table": Feature(
        name="sa_revised_ccf_table",
        enabled=True,
        citation=Citation("PS1/26", "111", "(1) Basel 3.1 revised SA CCF table (Table A1)"),
    ),
    # SA-CCR transitional alpha add-on (PRA PS1/26 Art. 274(2A)): Basel-3.1-only
    # phase-in (2027-2029) of the α=1.4 uplift for legacy CVA-exempt non-financial
    # counterparties carved out to α=1.0. Overrides the CRR Feature; gates the
    # add-on branch in engine/ccr/pipeline_adapter.py.
    "ccr_transitional_alpha_addon_applicable": Feature(
        name="ccr_transitional_alpha_addon_applicable",
        enabled=True,
        citation=Citation(
            "PS1/26", "274", "(2A) transitional alpha add-on for legacy CVA-exempt counterparties"
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
        citation=Citation("PS1/26", "92", "(5)"),
    ),
    # Full (fully-phased-in) output floor — Art. 92 72.5%. Used when a firm
    # voluntarily skips the Art. 92(5) transitional phase-in (the skip_transitional
    # ELECTION on OutputFloorConfig): the floor is the full 72.5% from day one,
    # not the output_floor_pct Schedule value. Consumed in
    # engine/aggregator/aggregator.py::_output_floor_pct.
    "output_floor_pct_full": ScalarParam(
        name="output_floor_pct_full",
        value=Decimal("0.725"),
        citation=Citation("PS1/26", "92", "fully phased-in output floor (72.5%)"),
    ),
    # GCRA cap for OF-ADJ (PRA PS1/26 Art. 92 para 2A): general credit risk
    # adjustments are capped at 1.25% of S-TREA before entering
    # OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2). Read in
    # engine/aggregator/_floor.py::compute_of_adj (output floor is Basel-3.1-only).
    "gcra_cap_rate": ScalarParam(
        name="gcra_cap_rate",
        value=Decimal("0.0125"),
        citation=Citation("PS1/26", "92", "GCRA cap at 1.25% of S-TREA (Art. 92 para 2A)"),
    ),
    # Basel-3.1 capital-stack regime GATES (S11d). Mirror the regime-derived
    # `enabled` flags on EquityTransitionalConfig / PostModelAdjustmentConfig
    # (the output_floor gate is the Feature above). The engine sources the on/off
    # gate from these Features; the VALUES (equity transitional RW schedule,
    # mortgage RW floor) and the firm ELECTIONS (opt_out, PMA scalars) stay
    # config-side until the S11e carve.
    "equity_transitional": Feature(
        name="equity_transitional",
        enabled=True,
        citation=Citation("PS1/26", "4.1", "PRA equity transitional regime (Rules 4.1-4.10)"),
    ),
    # PRA Rules 4.2/4.3 transitional SA equity risk weights (2027-2030), the VALUES
    # gated by the equity_transitional Feature above. Two Schedules — standard and
    # higher-risk — mirror EquityTransitionalConfig.basel_3_1()'s
    # {date: (standard_rw, higher_risk_rw)} schedule field-for-field. before_first=0.0
    # marks "before the first step": the engine accessor maps that to None (no
    # transition) so the floor is skipped, byte-identical with get_transitional_rw.
    # Consumed in engine/equity/calculator.py::_equity_transitional_rw.
    "equity_transitional_std_rw": Schedule(
        name="equity_transitional_std_rw",
        steps=(
            (date(2027, 1, 1), Decimal("1.60")),
            (date(2028, 1, 1), Decimal("1.90")),
            (date(2029, 1, 1), Decimal("2.20")),
            (date(2030, 1, 1), Decimal("2.50")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "4.2", "transitional standard equity RW (Rules 4.2/4.3)"),
    ),
    "equity_transitional_hr_rw": Schedule(
        name="equity_transitional_hr_rw",
        steps=(
            (date(2027, 1, 1), Decimal("2.20")),
            (date(2028, 1, 1), Decimal("2.80")),
            (date(2029, 1, 1), Decimal("3.40")),
            (date(2030, 1, 1), Decimal("4.00")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "4.3", "transitional higher-risk equity RW (Rules 4.2/4.3)"),
    ),
    "post_model_adjustments": Feature(
        name="post_model_adjustments",
        enabled=True,
        citation=Citation(
            "PS1/26", "154", "(4A) IRB post-model adjustments (Art. 153(5A)/154(4A)/158(6A))"
        ),
    ),
    # PRA PS1/26 Art. 154(4A)(b) mortgage RW floor — the 10% minimum risk weight for
    # residential-mortgage IRB exposures, gated by post_model_adjustments above. 0.10
    # is the regulatory DEFAULT; a firm may apply a higher PMA floor by overriding this
    # scalar via ResolvedRulepack.with_overrides. Consumed in
    # engine/irb/adjustments.py::apply_post_model_adjustments (read only when the gate is
    # on, so CRR — Feature off — never resolves it and packs/crr.py omits it).
    "mortgage_rw_floor": ScalarParam(
        name="mortgage_rw_floor",
        value=Decimal("0.10"),
        citation=Citation("PS1/26", "154", "(4A) 10% mortgage RW floor (residential IRB)"),
    ),
    # Basel 3.1 replaces the CRR Art. 230 F-IRB collateral step-functions with
    # the continuous LGD* formula (PS1/26 Art. 230(1)): no overcollateralisation
    # divisor and no minimum collateralisation threshold. Overrides the CRR
    # Features of the same name.
    "firb_overcollateralisation_divisor_applies": Feature(
        name="firb_overcollateralisation_divisor_applies",
        enabled=False,
        citation=Citation("PS1/26", "230", "(1) LGD* formula — no overcollateralisation divisor"),
    ),
    "firb_min_collateralisation_threshold_applies": Feature(
        name="firb_min_collateralisation_threshold_applies",
        enabled=False,
        citation=Citation(
            "PS1/26", "230", "(1) LGD* formula — no minimum collateralisation threshold"
        ),
    ),
    # AIRB LGD collateral method (PS1/26 Art. 169A/169B): Basel 3.1 Foundation
    # Collateral Method election + Art. 169B LGD-modelling/insufficient-data fallback
    # route AIRB exposures to the supervisory LGD formula. Overrides the CRR Feature;
    # gates the AIRB-method branches in engine/crm/collateral.py.
    "airb_lgd_collateral_method_applicable": Feature(
        name="airb_lgd_collateral_method_applicable",
        enabled=True,
        citation=Citation(
            "PS1/26", "169A", "AIRB LGD Modelling / Foundation Collateral Method (Art. 169A/169B)"
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
    # =========================================================================
    # SA INSTITUTION ECRA CQS RISK-WEIGHT TABLES (PRA PS1/26 Art. 120)
    # CQS-enum-keyed; read back into data/tables as dict[CQS, Decimal]. These are
    # the Basel-3.1 ECRA values (CQS2=30%, long-term unrated=40% SCRA Grade A),
    # previously mis-homed as B31 literals inside data/tables/crr_risk_weights.py.
    # =========================================================================
    "institution_rw_b31_ecra": LookupTable(
        name="institution_rw_b31_ecra",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.30"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("0.40"),
        },
        key="cqs",
        citation=Citation("PS1/26", "120", "Table 3 ECRA institution RW (CQS2 30%, unrated 40%)"),
        default=Decimal("0.40"),
    ),
    "institution_short_term_rw_b31_ecra": LookupTable(
        name="institution_short_term_rw_b31_ecra",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.20"),
            CQS.CQS3: Decimal("0.20"),
            CQS.CQS4: Decimal("0.50"),
            CQS.CQS5: Decimal("0.50"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("0.20"),
        },
        key="cqs",
        citation=Citation("PS1/26", "120", "(2) Table 4 ECRA short-term institution RW"),
        default=Decimal("0.20"),
    ),
    # =========================================================================
    # SA CORPORATE / COVERED-BOND CQS RISK-WEIGHT TABLES (PRA PS1/26 Art. 122/129)
    # Raw-int-keyed (1-6, None for unrated) to match the data/tables int-keyed
    # dicts read back via _build_int_cqs_rw_df. Corporate CQS3=75% (vs CRR 100%).
    # =========================================================================
    "b31_corporate_risk_weights": LookupTable(
        name="b31_corporate_risk_weights",
        entries={
            1: Decimal("0.20"),
            2: Decimal("0.50"),
            3: Decimal("0.75"),
            4: Decimal("1.00"),
            5: Decimal("1.50"),
            6: Decimal("1.50"),
            None: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("PS1/26", "122", "(2) Table 6 corporate RW (CQS3 75%, CQS5 150%)"),
        default=Decimal("1.00"),
    ),
    "b31_covered_bond_risk_weights": LookupTable(
        name="b31_covered_bond_risk_weights",
        entries={
            1: Decimal("0.10"),
            2: Decimal("0.20"),
            3: Decimal("0.20"),
            4: Decimal("0.50"),
            5: Decimal("0.50"),
            6: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("PS1/26", "129", "(4) Table 7 covered-bond RW (= CRR Table 6A)"),
        default=Decimal("1.00"),
    ),
    # Unrated covered-bond RW derived from the issuing institution's own RW
    # (PRA PS1/26 Art. 129(5)): 7-input chain incl. ECRA CQS2 (0.30->0.15),
    # SCRA Grade A (0.40->0.20) / B (0.75->0.35), and (5)(b) 0.50->0.25.
    "covered_bond_unrated_derivation_b31": LookupTable(
        name="covered_bond_unrated_derivation_b31",
        entries={
            Decimal("0.20"): Decimal("0.10"),
            Decimal("0.30"): Decimal("0.15"),
            Decimal("0.40"): Decimal("0.20"),
            Decimal("0.50"): Decimal("0.25"),
            Decimal("0.75"): Decimal("0.35"),
            Decimal("1.00"): Decimal("0.50"),
            Decimal("1.50"): Decimal("1.00"),
        },
        key="issuer_institution_rw",
        citation=Citation("PS1/26", "129", "(5) unrated CB derivation from issuer RW (7-input)"),
        default=Decimal("1.00"),
    ),
    # Unrated covered-bond RW direct from issuer SCRA grade (PRA PS1/26
    # Art. 129(5)): SCRA grade -> institution RW -> CB RW, pre-resolved.
    "b31_covered_bond_unrated_from_scra": LookupTable(
        name="b31_covered_bond_unrated_from_scra",
        entries={
            "A_ENHANCED": Decimal("0.15"),
            "A": Decimal("0.20"),
            "B": Decimal("0.35"),
            "C": Decimal("1.00"),
        },
        key="scra_grade",
        citation=Citation("PS1/26", "129", "(5) unrated CB RW direct from issuer SCRA grade"),
        default=Decimal("1.00"),
    ),
    # =========================================================================
    # SA INSTITUTION SCRA / ECRA SHORT-TERM TABLES (PRA PS1/26 Art. 120 / 122)
    # SCRA (unrated) tables are str-keyed by grade; ECRA short-term + dedicated
    # short-term-ECAI tables are raw-int-keyed by CQS (1-6).
    # =========================================================================
    "b31_scra_risk_weights": LookupTable(
        name="b31_scra_risk_weights",
        entries={
            "A": Decimal("0.40"),
            "A_ENHANCED": Decimal("0.30"),
            "B": Decimal("0.75"),
            "C": Decimal("1.50"),
        },
        key="scra_grade",
        citation=Citation("PS1/26", "120", "SCRA long-term institution RW by grade (CRE20.18-21)"),
        default=Decimal("1.50"),
    ),
    "b31_scra_short_term_risk_weights": LookupTable(
        name="b31_scra_short_term_risk_weights",
        entries={
            "A": Decimal("0.20"),
            "A_ENHANCED": Decimal("0.20"),
            "B": Decimal("0.50"),
            "C": Decimal("1.50"),
        },
        key="scra_grade",
        citation=Citation("PS1/26", "120", "Art. 120A SCRA short-term institution RW by grade"),
        default=Decimal("1.50"),
    ),
    "b31_ecra_short_term_risk_weights": LookupTable(
        name="b31_ecra_short_term_risk_weights",
        entries={
            1: Decimal("0.20"),
            2: Decimal("0.20"),
            3: Decimal("0.20"),
            4: Decimal("0.50"),
            5: Decimal("0.50"),
            6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("PS1/26", "120", "(2) Table 4 ECRA short-term (long-term rating, <=3m)"),
        default=Decimal("1.50"),
    ),
    "b31_ecra_short_term_ecai_risk_weights": LookupTable(
        name="b31_ecra_short_term_ecai_risk_weights",
        entries={
            1: Decimal("0.20"),
            2: Decimal("0.50"),
            3: Decimal("1.00"),
            4: Decimal("1.50"),
            5: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation(
            "PS1/26", "120", "(2B) Table 4A dedicated short-term ECAI institution RW"
        ),
        default=Decimal("1.50"),
    ),
    "b31_corporate_short_term_ecai_risk_weights": LookupTable(
        name="b31_corporate_short_term_ecai_risk_weights",
        entries={
            1: Decimal("0.20"),
            2: Decimal("0.50"),
            3: Decimal("1.00"),
            4: Decimal("1.50"),
            5: Decimal("1.50"),
            6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("PS1/26", "122", "(3) Table 6A dedicated short-term ECAI corporate RW"),
        default=Decimal("1.50"),
    ),
    # =========================================================================
    # SA B31 CORPORATE / RETAIL / DEFAULTED / CURRENCY-MISMATCH TAIL SCALARS
    # =========================================================================
    "b31_corporate_investment_grade_rw": ScalarParam(
        name="b31_corporate_investment_grade_rw",
        value=Decimal("0.65"),
        citation=Citation("PS1/26", "122", "(6)(a) investment-grade corporate 65%"),
    ),
    "b31_corporate_non_investment_grade_rw": ScalarParam(
        name="b31_corporate_non_investment_grade_rw",
        value=Decimal("1.35"),
        citation=Citation("PS1/26", "122", "(6)(b) non-investment-grade corporate 135%"),
    ),
    "b31_corporate_sme_rw": ScalarParam(
        name="b31_corporate_sme_rw",
        value=Decimal("0.85"),
        citation=Citation("PS1/26", "122", "SME corporate 85% (CRE20.47)"),
    ),
    "b31_subordinated_debt_rw": ScalarParam(
        name="b31_subordinated_debt_rw",
        value=Decimal("1.50"),
        citation=Citation("PS1/26", "133", "subordinated debt 150% flat (CRE20.49)"),
    ),
    "b31_defaulted_rw_high_provision": ScalarParam(
        name="b31_defaulted_rw_high_provision",
        value=Decimal("1.00"),
        citation=Citation("PS1/26", "127", "defaulted, provisions >= 20%"),
    ),
    "b31_defaulted_rw_low_provision": ScalarParam(
        name="b31_defaulted_rw_low_provision",
        value=Decimal("1.50"),
        citation=Citation("PS1/26", "127", "defaulted, provisions < 20%"),
    ),
    "b31_defaulted_provision_threshold": ScalarParam(
        name="b31_defaulted_provision_threshold",
        value=Decimal("0.20"),
        citation=Citation("PS1/26", "127", "20% provision threshold"),
    ),
    "b31_defaulted_resi_re_non_income_rw": ScalarParam(
        name="b31_defaulted_resi_re_non_income_rw",
        value=Decimal("1.00"),
        citation=Citation("PS1/26", "127", "defaulted general RESI RE (non-income) 100% flat"),
    ),
    "b31_retail_transactor_rw": ScalarParam(
        name="b31_retail_transactor_rw",
        value=Decimal("0.45"),
        citation=Citation("PS1/26", "123", "QRRE transactor 45%"),
    ),
    "b31_retail_payroll_loan_rw": ScalarParam(
        name="b31_retail_payroll_loan_rw",
        value=Decimal("0.35"),
        citation=Citation("PS1/26", "123", "(4) payroll/pension loan 35%"),
    ),
    "b31_retail_non_regulatory_rw": ScalarParam(
        name="b31_retail_non_regulatory_rw",
        value=Decimal("1.00"),
        citation=Citation("PS1/26", "123", "(3)(c) non-regulatory retail 100%"),
    ),
    "b31_retail_granularity_limit": ScalarParam(
        name="b31_retail_granularity_limit",
        value=Decimal("0.002"),
        citation=Citation("PS1/26", "123", "123A(1)(b)(ii) single-obligor 0.2% granularity cap"),
    ),
    # PRA PS1/26 commencement date — the Basel 3.1 SA framework (including the
    # Art. 123B currency-mismatch multiplier this date gates) takes effect on
    # 1 January 2027; reporting dates strictly before fall under pre-Basel-3.1
    # treatment. Relocated from data/tables (S13-g) as the first DateParam.
    "b31_effective_date": DateParam(
        name="b31_effective_date",
        value=date(2027, 1, 1),
        citation=Citation("PS1/26", "123B", "Basel 3.1 commencement date (1 Jan 2027)"),
    ),
    "b31_currency_mismatch_multiplier": ScalarParam(
        name="b31_currency_mismatch_multiplier",
        value=Decimal("1.5"),
        citation=Citation("PS1/26", "123B", "currency-mismatch 1.5x RW multiplier"),
    ),
    "b31_currency_mismatch_rw_cap": ScalarParam(
        name="b31_currency_mismatch_rw_cap",
        value=Decimal("1.50"),
        citation=Citation("PS1/26", "123B", "currency-mismatch absolute RW cap 150%"),
    ),
    "b31_currency_mismatch_hedge_coverage_floor": ScalarParam(
        name="b31_currency_mismatch_hedge_coverage_floor",
        value=Decimal("0.90"),
        citation=Citation("PS1/26", "123B", "(2) multiplier waived when hedge coverage >= 90%"),
    ),
    # SA B31 REAL-ESTATE EXPR SCALARS (PRA PS1/26 Art. 124I/124J/124K/124L)
    "b31_cre_income_junior_rw_low": ScalarParam(
        name="b31_cre_income_junior_rw_low",
        value=Decimal("1.00"),
        citation=Citation("PS1/26", "124I", "(3)(a) junior CRE LTV<=60% 100%"),
    ),
    "b31_cre_income_junior_rw_mid": ScalarParam(
        name="b31_cre_income_junior_rw_mid",
        value=Decimal("1.25"),
        citation=Citation("PS1/26", "124I", "(3)(b) junior CRE 60-80% 125%"),
    ),
    "b31_cre_income_junior_rw_high": ScalarParam(
        name="b31_cre_income_junior_rw_high",
        value=Decimal("1.375"),
        citation=Citation("PS1/26", "124I", "(3)(c) junior CRE LTV>80% 137.5%"),
    ),
    "b31_rre_residual_rw_natural_person": ScalarParam(
        name="b31_rre_residual_rw_natural_person",
        value=Decimal("0.75"),
        citation=Citation("PS1/26", "124L", "(a) natural person / retail-SME 75%"),
    ),
    "b31_rre_residual_rw_retail_sme": ScalarParam(
        name="b31_rre_residual_rw_retail_sme",
        value=Decimal("0.75"),
        citation=Citation("PS1/26", "124L", "(a) retail-qualifying SME 75%"),
    ),
    "b31_rre_residual_rw_other_sme": ScalarParam(
        name="b31_rre_residual_rw_other_sme",
        value=Decimal("0.85"),
        citation=Citation("PS1/26", "124L", "(b) other SME 85%"),
    ),
    "b31_rre_residual_rw_social_housing_floor": ScalarParam(
        name="b31_rre_residual_rw_social_housing_floor",
        value=Decimal("0.75"),
        citation=Citation("PS1/26", "124L", "(c) social housing floor 75%"),
    ),
    "b31_adc_risk_weight": ScalarParam(
        name="b31_adc_risk_weight",
        value=Decimal("1.50"),
        citation=Citation("PS1/26", "124K", "(1) ADC 150%"),
    ),
    "b31_adc_presold_risk_weight": ScalarParam(
        name="b31_adc_presold_risk_weight",
        value=Decimal("1.00"),
        citation=Citation("PS1/26", "124K", "(2) qualifying residential pre-sold ADC 100%"),
    ),
    "b31_other_re_income_dependent_rw": ScalarParam(
        name="b31_other_re_income_dependent_rw",
        value=Decimal("1.50"),
        citation=Citation("PS1/26", "124J", "(1) other-RE income-dependent 150%"),
    ),
    "b31_other_re_cre_floor_rw": ScalarParam(
        name="b31_other_re_cre_floor_rw",
        value=Decimal("0.60"),
        citation=Citation("PS1/26", "124J", "(3)(b) other-RE CRE floor 60%"),
    ),
    # Art. 124E(1)(b) three-property limit: owner-occupied preferential RRE
    # treatment is restricted to natural persons whose total residential RE
    # exposure is secured on no more than three properties; a count strictly
    # above this re-routes to the income-producing whole-loan track (Art. 124G).
    "b31_rre_three_property_limit": IntParam(
        name="b31_rre_three_property_limit",
        value=3,
        citation=Citation("PS1/26", "124E", "(1)(b) max residential properties for owner-occupied"),
    ),
    # RE general loan-split secured portion RW + cap (RRE Art. 124F / CRE Art. 124H)
    # and the income-RRE junior-charge multiplier + LTV gate (Art. 124G(2)).
    "b31_residential_general_secured_rw": ScalarParam(
        name="b31_residential_general_secured_rw",
        value=Decimal("0.20"),
        citation=Citation("PS1/26", "124F", "(1) RRE loan-split secured portion 20%"),
    ),
    "b31_residential_general_max_secured_ratio": ScalarParam(
        name="b31_residential_general_max_secured_ratio",
        value=Decimal("0.55"),
        citation=Citation("PS1/26", "124F", "(1) RRE loan-split cap 55% of value"),
    ),
    "b31_residential_income_junior_multiplier": ScalarParam(
        name="b31_residential_income_junior_multiplier",
        value=Decimal("1.25"),
        citation=Citation("PS1/26", "124G", "(2) junior income-RRE 1.25x multiplier"),
    ),
    "b31_residential_income_junior_ltv_threshold": ScalarParam(
        name="b31_residential_income_junior_ltv_threshold",
        value=Decimal("0.50"),
        citation=Citation("PS1/26", "124G", "(2) junior multiplier applies above 50% LTV"),
    ),
    "b31_commercial_general_secured_rw": ScalarParam(
        name="b31_commercial_general_secured_rw",
        value=Decimal("0.60"),
        citation=Citation("PS1/26", "124H", "(1) CRE loan-split secured portion 60%"),
    ),
    "b31_commercial_general_max_secured_ratio": ScalarParam(
        name="b31_commercial_general_max_secured_ratio",
        value=Decimal("0.55"),
        citation=Citation("PS1/26", "124H", "(2) CRE loan-split cap 55% of value"),
    ),
    # Income-producing RE LTV-band tables (whole-loan RW by LTV). The final
    # None-bound band is the catch-all; the data layer renders these to the
    # historical list[dict] (ltv_lower / ltv_upper=999.0 sentinel / risk_weight)
    # and the SA RE expr builders compile them to the cumulative LTV when/then.
    "b31_residential_income_ltv_bands": BandedTable(
        name="b31_residential_income_ltv_bands",
        bands=(
            (Decimal("0.50"), Decimal("0.30")),
            (Decimal("0.60"), Decimal("0.35")),
            (Decimal("0.70"), Decimal("0.40")),
            (Decimal("0.80"), Decimal("0.50")),
            (Decimal("0.90"), Decimal("0.60")),
            (Decimal("1.00"), Decimal("0.75")),
            (None, Decimal("1.05")),
        ),
        input="ltv",
        citation=Citation("PS1/26", "124G", "Table 6B income-producing RRE LTV bands"),
    ),
    "b31_commercial_income_ltv_bands": BandedTable(
        name="b31_commercial_income_ltv_bands",
        bands=(
            (Decimal("0.80"), Decimal("1.00")),
            (None, Decimal("1.10")),
        ),
        input="ltv",
        citation=Citation("PS1/26", "124I", "(1)/(2) income-producing CRE LTV bands"),
    ),
    # SA specialised-lending risk weights by SL type (PRA PS1/26 Art. 122A-122B).
    "b31_sa_sl_risk_weights": LookupTable(
        name="b31_sa_sl_risk_weights",
        entries={
            "object_finance": Decimal("1.00"),
            "commodities_finance": Decimal("1.00"),
            "project_finance_pre_operational": Decimal("1.30"),
            "project_finance_operational": Decimal("1.00"),
            "project_finance_high_quality": Decimal("0.80"),
        },
        key="sl_type",
        citation=Citation("PS1/26", "122A", "SA specialised-lending risk weights"),
    ),
    # ---------------------------------------------------------------------
    # BA-CVA (Basel-3.1-only) — PRA PS1/26 Credit Valuation Adjustment Risk
    # Part, Chapter 4. The CVA risk capital charge has no CRR equivalent
    # (CRR Art. 382 advanced/standardised CVA is replaced wholesale), so the
    # feature is present/True ONLY in this pack — absent from common/crr, so
    # ``pack.feature("cva_ba_cva")`` is False under CRR and the CVA stage is a
    # clean no-op. Consumed by engine/cva/ba_cva.py + engine/stages/cva.py.
    # ---------------------------------------------------------------------
    "cva_ba_cva": Feature(
        name="cva_ba_cva",
        enabled=True,
        citation=Citation(
            "PS1/26", "4.1", "BA-CVA in scope (Credit Valuation Adjustment Risk Part)"
        ),
    ),
    # DS_BA-CVA discount scalar applied to K_reduced (PS1/26 CVA Part 4.2,
    # page 399): OFR_CVA = DS_BA-CVA x K_reduced.
    "ds_ba_cva": ScalarParam(
        name="ds_ba_cva",
        value=Decimal("0.65"),
        citation=Citation("PS1/26", "4.2", "DS_BA-CVA = 0.65 (reduced BA-CVA own-funds scalar)"),
    ),
    # Supervisory correlation rho (PS1/26 CVA Part 4.2, page 399): used inside
    # K_reduced = sqrt[(rho.SUM SCVA_c)^2 + (1-rho^2).SUM SCVA_c^2].
    "cva_ba_supervisory_correlation": ScalarParam(
        name="cva_ba_supervisory_correlation",
        value=Decimal("0.50"),
        citation=Citation("PS1/26", "4.2", "rho = 50% supervisory correlation parameter"),
    ),
    # Supervisory discount rate (PS1/26 CVA Part 4.3, page 400): the 0.05 rate
    # inside DF_NS = (1 - e^(-0.05.M_NS)) / (0.05.M_NS).
    "cva_ba_supervisory_discount_rate": ScalarParam(
        name="cva_ba_supervisory_discount_rate",
        value=Decimal("0.05"),
        citation=Citation("PS1/26", "4.3", "supervisory discount rate 0.05 in DF_NS"),
    ),
    # Supervisory CVA risk weights RW_c by (sector x credit quality) per the
    # PS1/26 CVA Part 4.4 table (page 401). Investment grade ("IG") vs high
    # yield / non-rated ("HY_NR"). Consumed by engine/cva/ba_cva.py.
    "cva_ba_supervisory_risk_weights": DecisionTable(
        name="cva_ba_supervisory_risk_weights",
        key_names=("cva_rw_sector", "cva_rw_rating_band"),
        rows=(
            (("SOVEREIGN", "IG"), Decimal("0.005")),
            (("SOVEREIGN", "HY_NR"), Decimal("0.020")),
            (("LOCAL_GOVERNMENT", "IG"), Decimal("0.010")),
            (("LOCAL_GOVERNMENT", "HY_NR"), Decimal("0.040")),
            (("FINANCIAL", "IG"), Decimal("0.050")),
            (("FINANCIAL", "HY_NR"), Decimal("0.120")),
            (("PENSION_FUND", "IG"), Decimal("0.035")),
            (("PENSION_FUND", "HY_NR"), Decimal("0.085")),
            (("BASIC_MATERIALS", "IG"), Decimal("0.030")),
            (("BASIC_MATERIALS", "HY_NR"), Decimal("0.070")),
            (("CONSUMER", "IG"), Decimal("0.030")),
            (("CONSUMER", "HY_NR"), Decimal("0.085")),
            (("TECHNOLOGY", "IG"), Decimal("0.020")),
            (("TECHNOLOGY", "HY_NR"), Decimal("0.055")),
            (("HEALTHCARE", "IG"), Decimal("0.015")),
            (("HEALTHCARE", "HY_NR"), Decimal("0.050")),
            (("OTHER", "IG"), Decimal("0.050")),
            (("OTHER", "HY_NR"), Decimal("0.120")),
        ),
        citation=Citation("PS1/26", "4.4", "supervisory CVA risk weight table (sector x IG/HY-NR)"),
        # Conservative catch-all = Other sector HY/NR (12.0%) for unmapped keys.
        default=Decimal("0.120"),
    ),
    # ---------------------------------------------------------------------
    # Full BA-CVA (eligible CVA hedges) — PRA PS1/26 CVA Part 4.5-4.10.
    # Engaged only when the firm supplies eligible CVA hedges; otherwise the
    # reduced charge above applies. Consumed by engine/cva/ba_cva.py.
    # ---------------------------------------------------------------------
    # beta: hedging-disallowance weight in the K_full blend
    # K_full = beta x K_reduced + (1 - beta) x K_hedged (PS1/26 CVA Part 4.5,
    # page 401).
    "cva_ba_beta": ScalarParam(
        name="cva_ba_beta",
        value=Decimal("0.25"),
        citation=Citation("PS1/26", "4.5", "hedging-disallowance weight beta in K_full blend"),
    ),
    # r_hc supervisory correlation between the credit spread of counterparty c
    # and a single-name hedge h, keyed on the hedge's correlation band
    # (PS1/26 CVA Part 4.10, page 403): references directly = 100%, legally
    # related = 80%, shares sector and region = 50%.
    "cva_ba_single_name_hedge_correlation": DecisionTable(
        name="cva_ba_single_name_hedge_correlation",
        key_names=("cva_hedge_correlation_band",),
        rows=(
            (("IDENTICAL",), Decimal("1.00")),
            (("LEGALLY_RELATED",), Decimal("0.80")),
            (("SAME_SECTOR_REGION",), Decimal("0.50")),
        ),
        citation=Citation("PS1/26", "4.10", "r_hc single-name hedge supervisory correlation"),
        # Most conservative single-name correlation (lowest hedge offset) for
        # unmapped bands.
        default=Decimal("0.50"),
    ),
    # Index-hedge supervisory diversification multiplier applied to RW_i for
    # index eligible BA-CVA hedges (PS1/26 CVA Part 4.8(1)/(2), page 403):
    # RW_i_ind = (table RW) x 0.70.
    "cva_ba_index_diversification_factor": ScalarParam(
        name="cva_ba_index_diversification_factor",
        value=Decimal("0.70"),
        citation=Citation("PS1/26", "4.8", "index-hedge supervisory diversification multiplier"),
    ),
}
