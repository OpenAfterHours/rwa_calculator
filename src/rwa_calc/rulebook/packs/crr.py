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

from rwa_calc.domain.enums import CQS, EquityType
from rwa_calc.rulebook.model import (
    Citation,
    DecisionTable,
    Feature,
    FormulaParams,
    LookupTable,
    ReportingTemplateSet,
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
    # CRR Art. 501/501a supporting-factor multipliers — the VALUES gated by the
    # `supporting_factors` Feature above. SME 0.7619 (<= threshold) / 0.85 (> threshold)
    # + infrastructure 0.75. Consumed in engine/supporting_factors.py (Decimal via
    # pack.formula(...).params for the scalar helpers, float via compile.formula_float_map
    # in apply_factors). The FX-derived SME exposure THRESHOLD stays config
    # (RegulatoryThresholds → S11c). Basel 3.1 removes these (all 1.0 — packs/b31.py).
    "supporting_factors_values": FormulaParams(
        name="supporting_factors_values",
        params={
            "sme_factor_under_threshold": Decimal("0.7619"),
            "sme_factor_above_threshold": Decimal("0.85"),
            "infrastructure_factor": Decimal("0.75"),
        },
        citation=Citation("CRR", "501", "SME 0.7619/0.85 + infrastructure 0.75 multipliers"),
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
    # CRR Art. 164(4)/(5): portfolio-level minimum EAD-weighted-average LGD for
    # A-IRB retail exposures secured by real estate (residential 10% / commercial
    # 15%), excluding central-government-guaranteed exposures (164(4)). CRR has no
    # per-exposure A-IRB LGD floor (airb_lgd_floor off above), so this
    # portfolio-level backstop is the live CRR check; the aggregator emits a
    # monitoring WARNING on breach (never an RWA/LGD mutation). Basel 3.1's own
    # per-exposure airb_lgd_floor supersedes it, so b31.py disables this Feature.
    "crr_retail_re_portfolio_lgd_floor": Feature(
        name="crr_retail_re_portfolio_lgd_floor",
        enabled=True,
        citation=Citation(
            "CRR", "164", "(4)/(5) portfolio-level EW-avg LGD floor for A-IRB retail RE"
        ),
    ),
    "retail_residential_re_portfolio_lgd_floor": ScalarParam(
        name="retail_residential_re_portfolio_lgd_floor",
        value=Decimal("0.10"),
        citation=Citation("CRR", "164", "(4) residential-RE portfolio EW-avg LGD floor 10%"),
    ),
    "retail_commercial_re_portfolio_lgd_floor": ScalarParam(
        name="retail_commercial_re_portfolio_lgd_floor",
        value=Decimal("0.15"),
        citation=Citation("CRR", "164", "(4) commercial-RE portfolio EW-avg LGD floor 15%"),
    ),
    # IRB maturity (M) regime treatments — Features gate only the on/off regime
    # branch; the numeric constants they gate (0.5y SFT supervisory M, the 1/365
    # one-day floor) stay engine literals. Consumed in engine/irb/transforms.py.
    "firb_sft_supervisory_maturity": Feature(
        name="firb_sft_supervisory_maturity",
        enabled=True,
        citation=Citation("CRR", "162(1)", "F-IRB fixed 0.5y supervisory M for repo-style SFTs"),
    ),
    # Art. 162(1) exists under CRR, so its fixed 2.5y "all other exposures" M is
    # AVAILABLE here — but Art. 162(1) second sentence makes the choice between it
    # and the per-exposure Art. 162(2) M an Art. 143 permission matter. This Feature
    # therefore only says "the regime has the provision"; the firm-level election is
    # CalculationConfig.firb_fixed_maturity (default off, so the engine keeps the
    # date-derived Art. 162(2) M unless a firm opts in). B31 sets it False.
    "firb_fixed_supervisory_maturity": Feature(
        name="firb_fixed_supervisory_maturity",
        enabled=True,
        citation=Citation(
            "CRR", "162(1)", "fixed F-IRB supervisory M available (2.5y non-repo-style)"
        ),
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
    # CCR/SFT synthetic-row effective-maturity rung (Art. 162). Gates the new
    # ccr_effective_maturity carrier rung in engine/irb/transforms.py (the MNA &
    # one-day maturity floors for FCCM-SFT / SA-CCR synthetic IRB rows). Enabled
    # under BOTH regimes — only the CRR Art. 162(1) fixed 0.5y is regime-specific
    # (gated by firb_sft_supervisory_maturity); the sub-1y MNA floors and the
    # one-day override survive under Basel 3.1 (only Art. 162(1)/162(4) were deleted).
    # Declared in both packs (crr.py + b31.py) so pack.feature() never KeyErrors.
    "ccr_synthetic_maturity": Feature(
        name="ccr_synthetic_maturity",
        enabled=True,
        citation=Citation("CRR", "162", "CCR/SFT synthetic-row MNA & one-day maturity floors"),
    ),
    # CRR Art. 162(2)(c)/(d): the 10BD/5BD intermediate maturity floors apply to
    # collateralised derivs / repos merely "subject to a master netting agreement"
    # — NO daily-re-margining condition under CRR. So the daily condition is NOT
    # required here (enabled=False). Basel 3.1 162(2A)(c)/(d) ADDED a "daily
    # re-margin OR revaluation + prompt-liquidation" condition (b31.py = True).
    # Declared in both packs (KeyError-safety).
    "mna_intermediate_floor_requires_daily_condition": Feature(
        name="mna_intermediate_floor_requires_daily_condition",
        enabled=False,
        citation=Citation("CRR", "162(2)", "5BD/10BD MNA floors need no daily-re-margin condition"),
    ),
    # CRR Art. 153(3)/202-203 double-default treatment for guaranteed exposures —
    # removed under Basel 3.1. The election (config.enable_double_default) and the
    # 0.15+160xPD multiplier constant stay engine-side; only the regime gate moves.
    "double_default_treatment": Feature(
        name="double_default_treatment",
        enabled=True,
        citation=Citation("CRR", "153(3)", "double-default treatment (Art. 153(3), 202-203)"),
    ),
    # Art. 213(1)(c)(i) unfunded-credit-protection eligibility: CRR gates only the
    # unilateral-CANCELLATION arm (a guarantee the provider can unilaterally
    # cancel is ineligible). The "or change" limb is a PS1/26 addition, so this
    # Feature is disabled under CRR; Basel 3.1 (packs/b31.py) overrides it True.
    # Gates the change branch in engine/crm/guarantees.py::_gate_unilateral_protection.
    "ucp_unilateral_change_ineligible": Feature(
        name="ucp_unilateral_change_ineligible",
        enabled=False,
        citation=Citation(
            "CRR", "213", "(1)(c)(i) UCP ineligible if the provider can unilaterally cancel"
        ),
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
    # IRB PD floors. CRR Art. 160(1) is exhaustive about its scope: "The PD of an
    # exposure to a corporate or an institution shall be at least 0,03 %" — there
    # is no central-government / central-bank limb, so ``sovereign`` is 0 (P1.277).
    # Retail is floored at the same 0.03% by a SEPARATE article, Art. 163(1) ("The
    # PD of an exposure shall be at least 0,03 %", retail sub-section). Basel 3.1
    # differentiates all of these (packs/b31.py). Consumed by
    # engine/irb/formulas.py::_pd_floor_expression via compile.formula_float_map —
    # note the values are deliberately NON-uniform, which is what keeps that
    # builder's all-equal scalar shortcut from collapsing the class ladder.
    "pd_floors": FormulaParams(
        name="pd_floors",
        params={
            "corporate": Decimal("0.0003"),
            "corporate_sme": Decimal("0.0003"),
            # Art. 160(1) does not reach central governments or central banks.
            "sovereign": Decimal("0"),
            "institution": Decimal("0.0003"),
            "retail_mortgage": Decimal("0.0003"),
            "retail_other": Decimal("0.0003"),
            "retail_qrre_transactor": Decimal("0.0003"),
            "retail_qrre_revolver": Decimal("0.0003"),
        },
        citation=Citation(
            "CRR",
            "160(1)",
            "0.03% IRB PD floor for corporates and institutions only "
            "(retail floored separately by Art. 163(1); no CGCB floor)",
        ),
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
    # SA risk-weight override LADDER dispatch (distinct from the base-table
    # Feature above): selects the whole when/then override sequence applied on
    # top of the base CQS join — institution ECRA/SCRA branches, covered-bond
    # derivation, real-estate handling, currency-mismatch hook and the Art. 128
    # high-risk reintroduction. CRR runs the original Art. 112-134 ladder
    # (_apply_crr_risk_weight_overrides); Basel 3.1 runs the PS1/26 revised ladder
    # (_apply_b31_risk_weight_overrides). Gates the top-level dispatch in
    # engine/sa/risk_weights.py::apply_risk_weights; the branch VALUES stay in the
    # helper functions / data/tables.
    "sa_revised_risk_weight_overrides": Feature(
        name="sa_revised_risk_weight_overrides",
        enabled=False,
        citation=Citation("CRR", "112", "original SA risk-weight override ladder (Art. 112-134)"),
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
    # PS1/26 Art. 114(2A): an unrated central bank is weighted on the ECAI
    # assessment of the central government of its jurisdiction. CRR Art. 114 has
    # NO paragraph 2A — it runs 1, 2, 3, 4 (5/6 deleted) and 7 — so an unrated
    # central bank stays on the Art. 114(1) 100% fallback here. Only this limb is
    # regime-specific: the Art. 114(3) ECB 0% exists in both frameworks and is
    # deliberately NOT Feature-gated (see ecb_zero_rw in packs/common.py).
    "central_bank_uses_sovereign_cqs": Feature(
        name="central_bank_uses_sovereign_cqs",
        enabled=False,
        citation=Citation("CRR", "114", "no Art. 114(2A) central-bank/sovereign CQS read-across"),
    ),
    # CRR Art. 113(6) core-UK-group 0% risk weight. With PRA permission an
    # institution may assign a 0% risk weight to exposures to counterparties in
    # the same "core UK group" (same prudential consolidation, established in the
    # UK, no impediment to the prompt transfer of own funds). It is an
    # individual-basis treatment: on a consolidated / sub-consolidated run the
    # intragroup rows are eliminated before weighting, so the 0% only bites solo.
    # The Feature carries the regime story (enabled under BOTH regimes — PS1/26
    # retains the permission, so check 17 gates on the Feature, never on is_crr);
    # the scope resolver computes the per-row eligibility carrier
    # (intragroup_zero_rw_eligible) and the SA final-RW override in
    # engine/sa/rw_adjustments.py::apply_intragroup_zero_rw reads the 0% value
    # below. SA lending rows only — IRB rows reach SA via the Art. 150(1)(e) PPU
    # route, so they are out of scope here.
    "intragroup_zero_rw": Feature(
        name="intragroup_zero_rw",
        enabled=True,
        citation=Citation("CRR", "113", "(6) core-UK-group 0% RW permission (individual basis)"),
    ),
    "intragroup_zero_rw_pct": ScalarParam(
        name="intragroup_zero_rw_pct",
        value=Decimal("0.00"),
        citation=Citation("CRR", "113", "(6) 0% RW for core-UK-group intragroup exposures"),
    ),
    # SA RE loan-split regime gates (engine/stages/re_split/flagging.py, run inside
    # the classifier stage). CRR Art. 125/126 vs PS1/26 Art. 124F/124H. Each gates one
    # regulatory limb of the split decision; the split LTV/RW parameter VALUES live in
    # data/tables/re_split_parameters.py (the splitter call-site migration is S9g).
    "sa_re_split_cre_rental_coverage_required": Feature(
        name="sa_re_split_cre_rental_coverage_required",
        enabled=True,
        citation=Citation("CRR", "126", "CRE split requires the rental-coverage test (>=1.5x)"),
    ),
    "sa_re_split_art_124_4_all_or_nothing": Feature(
        name="sa_re_split_art_124_4_all_or_nothing",
        enabled=False,
        citation=Citation("CRR", "124", "no Art. 124(4) all-or-nothing mixed-RE rule under CRR"),
    ),
    "sa_re_split_whole_loan_path_applies": Feature(
        name="sa_re_split_whole_loan_path_applies",
        enabled=False,
        citation=Citation("CRR", "126", "no Art. 124H(3) whole-loan CRE path; all eligible split"),
    ),
    # RE loan-split parameter set selection (splitter, engine/stages/re_split/
    # splitter.py): CRR Art. 125/126 LTV caps / RW (RRE 80%/35%, CRE 50%/50%,
    # rental-coverage flag) vs PS1/26 Art. 124F/124H (RRE 55%/20%, CRE 55%/60%,
    # prior-charge reduction). The VALUES live in data/tables/re_split_parameters.py;
    # re_split_parameters / _split_unified_frame keep their is_basel_3_1 bool param.
    "sa_re_split_revised_parameters": Feature(
        name="sa_re_split_revised_parameters",
        enabled=False,
        citation=Citation("CRR", "125", "CRR Art. 125/126 RE-split LTV caps and risk weights"),
    ),
    # SA RE loan-split secured-LTV caps — the preferential-RW LTV ceiling per
    # property type. CRR Art. 125 RRE 80% / Art. 126 CRE 50%. Consumed by
    # engine/stages/re_split/params.py via compile.scalar_value; b31.py overrides
    # both with the PS1/26 Art. 124F/124H 55% values.
    "re_split_rre_secured_ltv_cap": ScalarParam(
        name="re_split_rre_secured_ltv_cap",
        value=Decimal("0.80"),
        citation=Citation("CRR", "125", "RRE preferential RW up to 80% LTV"),
    ),
    "re_split_cre_secured_ltv_cap": ScalarParam(
        name="re_split_cre_secured_ltv_cap",
        value=Decimal("0.50"),
        citation=Citation("CRR", "126", "CRE preferential RW up to 50% LTV"),
    ),
    # SA CCF schedule (CRR Art. 111 / Annex I categories). String-keyed by the
    # uppercase risk_type bucket; consumed in engine/ccf.py via lookup_float_map.
    # b31.py overrides this with the PS1/26 Table A1 values (OC 40% / LR 10%).
    "sa_ccf": LookupTable(
        name="sa_ccf",
        entries={
            "FR": Decimal("1.00"),
            "FRC": Decimal("1.00"),
            "MR": Decimal("0.50"),
            "MR_ISSUED": Decimal("0.50"),
            "OC": Decimal("0.50"),
            "MLR": Decimal("0.20"),
            "LR": Decimal("0.00"),
        },
        key="risk_type",
        citation=Citation(
            "CRR", "111", "SA CCFs (Annex I): FR/FRC 100%, MR/OC 50%, MLR 20%, LR 0%"
        ),
        default=Decimal("0.50"),
    ),
    # CRR Art. 166(10) F-IRB residual fallback for issued OBS items not in scope
    # of Art. 166(8). Selected by the engine when is_obs_commitment=False.
    "firb_obs_fallback_ccf": LookupTable(
        name="firb_obs_fallback_ccf",
        entries={
            "FR": Decimal("1.00"),
            "FRC": Decimal("1.00"),
            "MR": Decimal("0.50"),
            "MR_ISSUED": Decimal("0.50"),
            "OC": Decimal("0.50"),
            "MLR": Decimal("0.20"),
            "LR": Decimal("0.00"),
        },
        key="risk_type",
        citation=Citation("CRR", "166", "(10) F-IRB fallback: FR 100%, MR/OC 50%, MLR 20%, LR 0%"),
        default=Decimal("0.50"),
    ),
    # CRR Art. 166(8) bespoke F-IRB CCFs.
    "firb_trade_lc_ccf": ScalarParam(
        name="firb_trade_lc_ccf",
        value=Decimal("0.20"),
        citation=Citation("CRR", "166", "(8)(b) short-term trade LC from movement of goods"),
    ),
    "firb_credit_line_ccf": ScalarParam(
        name="firb_credit_line_ccf",
        value=Decimal("0.75"),
        citation=Citation("CRR", "166", "(8)(d) credit lines / NIFs / RUFs"),
    ),
    # Slotting (supervisory specialised-lending) risk-weight + EL-rate tables:
    # Basel 3.1 (PRA PS1/26 Art. 153(5) Table A / CRE33) revises them with HVCRE
    # and PF pre-operational splits — see packs/b31.py. The Feature selects the
    # CRR vs B31 table family in engine/slotting/transforms.py (apply_slotting_
    # weights / apply_el_rates); the VALUES stay in data/tables/{crr,b31}_slotting.
    "slotting_guarantee_substitution": Feature(
        name="slotting_guarantee_substitution",
        enabled=True,
        citation=Citation(
            "CRR",
            "235",
            "RW substitution applied to slotting by analogy (operator "
            "decision 2026-07-12): the CRR black-letter scoping is UNSETTLED "
            "(Art. 235 textually SA-scoped; Art. 236 needs a guarantor PD; "
            "Art. 161(3) A-IRB-only) but COREP Annex II para 43 expects "
            "substitution flows on slotting rows and zero relief mis-states "
            "the risk; covered-part EL zeroing mirrors the IRB SA-guarantor "
            "precedent. Flip enabled=False to restore zero relief",
        ),
    ),
    "slotting_revised_tables": Feature(
        name="slotting_revised_tables",
        enabled=False,
        citation=Citation(
            "CRR", "153(5)", "UK CRR single slotting table (HVCRE Table 2 not onshored)"
        ),
    ),
    # CRR specialised-lending slotting risk weights (Art. 153(5)) + EL rates
    # (Art. 158(6) Table B). String-keyed by SlottingCategory value; consumed by
    # engine/slotting/transforms.py via compile.lookup_float_map for Polars
    # replace_strict. UK CRR onshored a single weight table (HVCRE Table 2 not
    # onshored); the engine keeps HVCRE keys for audit symmetry. b31.py overrides
    # these with the PS1/26 Table A / Table B values. (Art. 158 was omitted from
    # UK CRR by SI 2021/1078 — the EL citation is soft-allowlisted in arch_check.)
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
        citation=Citation("CRR", "153(5)", "slotting RW, remaining maturity >= 2.5y"),
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
        citation=Citation("CRR", "153(5)", "slotting RW, remaining maturity < 2.5y"),
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
        citation=Citation("CRR", "153(5)", "HVCRE slotting RW, remaining maturity >= 2.5y"),
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
        citation=Citation("CRR", "153(5)", "HVCRE slotting RW, remaining maturity < 2.5y"),
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
        citation=Citation("CRR", "158(6)", "slotting EL rate, remaining maturity >= 2.5y"),
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
        citation=Citation("CRR", "158(6)", "slotting EL rate, remaining maturity < 2.5y"),
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
        citation=Citation("CRR", "158(6)", "HVCRE slotting EL rate (flat, no maturity split)"),
        default=Decimal("0.028"),
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
    # CRR Art. 165 supervisory parameters for the Art. 155(3) PD/LGD equity
    # approach, consumed by engine/equity/calculator.py. CRR-only: Basel 3.1
    # removes the IRB equity approaches (equity_irb_approaches_available is False
    # under b31), so these have no b31 counterpart and are read only on the CRR
    # path. Decimals expressed as fractions (Decimal("0.0040") = 0.40%).
    "equity_pd_floors": FormulaParams(
        name="equity_pd_floors",
        params={
            "exchange_traded_long_term": Decimal("0.0009"),  # 0.09% Art. 165(1)(a)
            "non_exchange_regular_cashflow": Decimal("0.0009"),  # 0.09% Art. 165(1)(b)
            "exchange_traded": Decimal("0.0040"),  # 0.40% Art. 165(1)(c)
            "other": Decimal("0.0125"),  # 1.25% Art. 165(1)(d)
        },
        citation=Citation("CRR", "165", "(1) minimum PDs by equity sub-type"),
    ),
    "equity_pd_lgd_lgd": FormulaParams(
        name="equity_pd_lgd_lgd",
        params={
            "private_equity_diversified": Decimal("0.65"),  # 65% Art. 165(2)
            "other": Decimal("0.90"),  # 90% Art. 165(2)
        },
        citation=Citation("CRR", "165", "(2) supervisory LGD 65% diversified PE / 90% other"),
    ),
    "equity_pd_lgd_maturity": ScalarParam(
        name="equity_pd_lgd_maturity",
        value=Decimal("5.0"),
        citation=Citation("CRR", "165", "(3) fixed maturity M = 5 years"),
    ),
    "equity_pd_lgd_no_default_info_scaling": ScalarParam(
        name="equity_pd_lgd_no_default_info_scaling",
        value=Decimal("1.5"),
        citation=Citation("CRR", "155(3)", "1.5x RW scaling absent Art. 178 default data"),
    ),
    # Equity SA risk weights (CRR Art. 133(2) 100% flat / Art. 132(2) CIU 1250% /
    # central bank 0%). The equity_revised_sa_risk_weights Feature selects CRR vs
    # B31; packs/b31.py OVERRIDES this entry with the Art. 133(3)-(5) table. Enum
    # (EquityType)-keyed; consumed by engine/equity/calculator.py and
    # engine/sa/risk_weights.py via compile.lookup_float_map.
    "equity_sa_risk_weights": LookupTable(
        name="equity_sa_risk_weights",
        entries={
            EquityType.CENTRAL_BANK: Decimal("0.00"),
            EquityType.SUBORDINATED_DEBT: Decimal("1.00"),
            EquityType.LISTED: Decimal("1.00"),
            EquityType.EXCHANGE_TRADED: Decimal("1.00"),
            EquityType.GOVERNMENT_SUPPORTED: Decimal("1.00"),
            EquityType.UNLISTED: Decimal("1.00"),
            EquityType.SPECULATIVE: Decimal("1.00"),
            EquityType.PRIVATE_EQUITY: Decimal("1.00"),
            EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("1.00"),
            EquityType.CIU: Decimal("12.50"),
            EquityType.OTHER: Decimal("1.00"),
        },
        key="equity_type",
        citation=Citation("CRR", "133", "Art. 133(2) 100% flat / Art. 132(2) CIU 1250%"),
        default=Decimal("1.00"),
    ),
    # IRB Simple equity risk weights (CRR Art. 155(2)): PE-diversified 190%,
    # exchange-traded 290%, all other 370%. CRR-only (Basel 3.1 removes IRB equity).
    "equity_irb_simple_risk_weights": LookupTable(
        name="equity_irb_simple_risk_weights",
        entries={
            EquityType.CENTRAL_BANK: Decimal("0.00"),
            EquityType.SUBORDINATED_DEBT: Decimal("3.70"),
            EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("1.90"),
            EquityType.PRIVATE_EQUITY: Decimal("3.70"),
            EquityType.EXCHANGE_TRADED: Decimal("2.90"),
            EquityType.LISTED: Decimal("2.90"),
            EquityType.GOVERNMENT_SUPPORTED: Decimal("3.70"),
            EquityType.UNLISTED: Decimal("3.70"),
            EquityType.SPECULATIVE: Decimal("3.70"),
            EquityType.CIU: Decimal("3.70"),
            EquityType.OTHER: Decimal("3.70"),
        },
        key="equity_type",
        citation=Citation("CRR", "155", "(2) IRB simple PE-div 190%/exch 290%/other 370%"),
        default=Decimal("3.70"),
    ),
    # IRB Simple equity expected-loss rates (Art. 158(7)): the EL amount is
    # EL rate x exposure value, paired with the Art. 155(2) simple RW bucket —
    # 0.8% for diversified PE (190%) and exchange-traded/listed (290%), 2.4% for
    # all other equity (370%). Central-bank equity (0% RW) carries no EL. Art. 158
    # was omitted from onshored UK CRR by SI 2021/1078 (soft-allowlisted in
    # arch_check); the live text is PRA Rulebook (CRR Firms) IRB Approach Part,
    # mirroring EU CRR Art. 158(7) / Annex VII Part I point 32. These EL amounts
    # are a disclosure quantity (COREP C08 / Pillar 3 IRB EL) and do NOT feed the
    # Art. 159 EL-vs-provisions comparison, which is limited to Art. 158(5),(6),(10).
    # CRR-only (Basel 3.1 removes IRB equity). Enum (EquityType)-keyed; consumed
    # by engine/equity/calculator.py via compile.lookup_float_map.
    "equity_irb_simple_el": LookupTable(
        name="equity_irb_simple_el",
        entries={
            EquityType.CENTRAL_BANK: Decimal("0.0"),
            EquityType.SUBORDINATED_DEBT: Decimal("0.024"),
            EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("0.008"),
            EquityType.PRIVATE_EQUITY: Decimal("0.024"),
            EquityType.EXCHANGE_TRADED: Decimal("0.008"),
            EquityType.LISTED: Decimal("0.008"),
            EquityType.GOVERNMENT_SUPPORTED: Decimal("0.024"),
            EquityType.UNLISTED: Decimal("0.024"),
            EquityType.SPECULATIVE: Decimal("0.024"),
            EquityType.CIU: Decimal("0.024"),
            EquityType.OTHER: Decimal("0.024"),
        },
        key="equity_type",
        citation=Citation("CRR", "158(7)", "IRB simple equity EL 0.8% div-PE/exch, 2.4% other"),
        default=Decimal("0.024"),
    ),
    # CRR Art. 155(2): non-trading-book short positions may net long positions in
    # the same stock only if the explicit hedge covers >= 1 year. Documentary
    # value-home (the netting logic lives in engine/equity/calculator.py).
    "equity_netting_min_hedge_years": ScalarParam(
        name="equity_netting_min_hedge_years",
        value=Decimal("1.0"),
        citation=Citation("CRR", "155(2)", "min 1y hedge tenor for short-position netting"),
    ),
    # Basel-3.1 capital-stack regime GATES, all absent under CRR (S11d). These
    # mirror the regime-derived `enabled` flags on contracts/config.py's
    # OutputFloorConfig / EquityTransitionalConfig / PostModelAdjustmentConfig —
    # the engine sources the on/off gate from these Features; the VALUES
    # (floor pct + transitional schedule, equity transitional RW schedule,
    # mortgage RW floor) and the firm ELECTIONS (institution_type/reporting_basis,
    # opt_out, PMA scalars) stay config-side. The aggregate output floor
    # (engine/aggregator), the PRA equity transitional floor (engine/equity), and
    # the IRB post-model adjustments (engine/irb/adjustments) are all Basel-3.1-only.
    "output_floor": Feature(
        name="output_floor",
        enabled=False,
        citation=Citation("CRR", "92", "no aggregate output floor under CRR"),
    ),
    "equity_transitional": Feature(
        name="equity_transitional",
        enabled=False,
        citation=Citation("CRR", "133", "no PRA equity transitional regime under CRR"),
    ),
    "post_model_adjustments": Feature(
        name="post_model_adjustments",
        enabled=False,
        citation=Citation("CRR", "153", "no post-model adjustment framework under CRR"),
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
    # CRR Art. 147(3)(b) admits only the Art. 117(2) named (0% RW) MDBs to the
    # central-government IRB class; Art. 147(4)(c) puts "exposures to multilateral
    # development banks which are not assigned a 0 % risk weight under Article 117"
    # in the INSTITUTIONS class. PS1/26 Art. 147(3)(f) drops that split (all MDBs
    # are quasi-sovereign there), so the reroute is CRR-only. Gates the
    # non-named-MDB IRB-class step in engine/stages/classify/attributes.py
    # (entity_type_to_irb_class itself stays the framework-invariant base map).
    "crr_non_named_mdb_institution_irb_class": Feature(
        name="crr_non_named_mdb_institution_irb_class",
        enabled=True,
        citation=Citation(
            "CRR", "147", "Art. 147(4)(c) non-0% MDBs assigned to the institutions IRB class"
        ),
    ),
    # Basel 3.1 Art. 124E(1)(b)/(2): natural-person RRE re-routed to income-
    # producing whole-loan above the three-property limit; no CRR equivalent.
    "b31_art_124e_three_property_limit_applies": Feature(
        name="b31_art_124e_three_property_limit_applies",
        enabled=False,
        citation=Citation("CRR", "124", "no natural-person three-property re-route under CRR"),
    ),
    # Basel 3.1 Art. 123A two-path retail qualification (SME auto-qualify + the
    # threshold/granularity limbs); CRR uses the single aggregate-exposure threshold
    # check only. Gates engine/stages/classify/attributes.py::_build_qualifies_as_retail_expr.
    # The retail-exposure THRESHOLD it compares against is FX-derived and stays config
    # (RegulatoryThresholds → S11c); the enforce_retail_granularity election stays config.
    "retail_art_123a_two_path_applicable": Feature(
        name="retail_art_123a_two_path_applicable",
        enabled=False,
        citation=Citation("CRR", "123", "single aggregate-exposure retail threshold check"),
    ),
    # CRR regulatory monetary thresholds: the EUR source amounts (CRR Art. 123/123A/
    # 501/4(1)(146)) converted to GBP at the run's EUR/GBP rate. The pack holds the
    # FX-INVARIANT EUR bases; the engine applies × eur_gbp_rate (a market input that
    # stays on config/RunConfig, NOT a regulatory value) at the read site via
    # engine/thresholds.py::regulatory_threshold. The `regulatory_thresholds_fx_derived`
    # Feature (True under CRR) gates the ×rate. Mirrors
    # contracts/config.py::RegulatoryThresholds.crr field-for-field.
    "regulatory_thresholds": FormulaParams(
        name="regulatory_thresholds",
        params={
            "sme_turnover_threshold": Decimal("50000000"),  # EUR 50m (Art. 501 / 4(1)(128D))
            "sme_balance_sheet_threshold": Decimal("43000000"),  # EUR 43m (Rec 2003/361/EC)
            "sme_exposure_threshold": Decimal("2500000"),  # EUR 2.5m (Art. 501)
            "large_corporate_revenue_threshold": Decimal("0"),  # n/a under CRR
            "retail_max_exposure": Decimal("1000000"),  # EUR 1m (Art. 123(c))
            "qrre_max_limit": Decimal("100000"),  # EUR 100k (Art. 123)
            "lfse_total_assets_threshold": Decimal("70000000000"),  # EUR 70bn (Art. 142(1)(4))
        },
        citation=Citation("CRR", "123", "EUR monetary thresholds (× EUR/GBP rate → GBP)"),
    ),
    "regulatory_thresholds_fx_derived": Feature(
        name="regulatory_thresholds_fx_derived",
        enabled=True,
        citation=Citation("CRR", "123", "CRR thresholds are EUR amounts converted at the FX rate"),
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
    # CCF regime gates (engine/ccf.py). firb_uses_sa_ccf: Basel 3.1 Art. 166C makes
    # F-IRB CCFs equal the SA CCFs (and routes SL slotting to SA); CRR uses the
    # Art. 166(8)+(10) bespoke/fallback CCFs. airb_ead_floor_applies: Basel 3.1
    # Art. 166D(5) adds the A-IRB EAD floor tests (on-BS EAD + 50% off-BS at F-IRB
    # CCF); CRR has none. Both gate only the branch — the SA/F-IRB CCF tables and the
    # 0.5 floor multiplier stay static data-layer constants.
    "firb_uses_sa_ccf": Feature(
        name="firb_uses_sa_ccf",
        enabled=False,
        citation=Citation("CRR", "166", "F-IRB uses Art. 166(8)+(10) bespoke/fallback CCFs"),
    ),
    "airb_ead_floor_applies": Feature(
        name="airb_ead_floor_applies",
        enabled=False,
        citation=Citation("CRR", "166", "no A-IRB EAD floor tests under CRR"),
    ),
    # SA CCF table selection (CRR Annex I vs PS1/26 Table A1: OC 50→40%, LR 0→10%).
    # Distinct from firb_uses_sa_ccf (which decides WHETHER F-IRB uses SA CCFs); this
    # selects WHICH SA CCF table. Gates the pro-rata weighting basis in
    # engine/crm/provisions.py; sa_ccf_expression keeps its is_basel_3_1 bool param.
    "sa_revised_ccf_table": Feature(
        name="sa_revised_ccf_table",
        enabled=False,
        citation=Citation("CRR", "111", "CRR Annex I SA CCF table"),
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
    # AIRB LGD collateral method (PS1/26 Art. 169A/169B): Basel 3.1 introduces the
    # Foundation Collateral Method election and the Art. 169B LGD-modelling /
    # insufficient-data fallback that route AIRB exposures to the supervisory LGD
    # formula. CRR AIRB is free-form (own LGD always kept), so this is disabled.
    # Gates the AIRB-method branches in engine/crm/collateral.py.
    "airb_lgd_collateral_method_applicable": Feature(
        name="airb_lgd_collateral_method_applicable",
        enabled=False,
        citation=Citation("CRR", "181", "CRR AIRB own-LGD is free-form (no collateral method)"),
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
            # CRR Art. 224 Table 1, "Volatility adjustments for securitisation
            # positions and meeting the criteria in Article 197(1)(h)", 10-day
            # liquidation column (crr.pdf p.221, printed values). Eligible only for
            # CQS 1-3 non-resecuritisation positions with RW <= 100% (Art. 197(1)(h)
            # / Art. 261-264, gated in haircuts.py).
            (("securitisation", 1, "0_1y", None), Decimal("0.02")),
            (("securitisation", 1, "1_5y", None), Decimal("0.08")),
            (("securitisation", 1, "5y_plus", None), Decimal("0.16")),
            (("securitisation", 2, "0_1y", None), Decimal("0.04")),
            (("securitisation", 2, "1_5y", None), Decimal("0.12")),
            (("securitisation", 2, "5y_plus", None), Decimal("0.24")),
            (("securitisation", 3, "0_1y", None), Decimal("0.04")),
            (("securitisation", 3, "1_5y", None), Decimal("0.12")),
            (("securitisation", 3, "5y_plus", None), Decimal("0.24")),
            (("equity", None, None, True), Decimal("0.15")),
            (("equity", None, None, False), Decimal("0.25")),
            (("real_estate", None, None, None), Decimal("0.00")),
            (("receivables", None, None, None), Decimal("0")),
            (("other_physical", None, None, None), Decimal("0.40")),
        ),
        citation=Citation("CRR", "224", "FCCM supervisory haircuts Table 1 (3 maturity bands)"),
    ),
    # =========================================================================
    # SA EXPOSURE-CLASS CQS RISK-WEIGHT TABLES (CRR Art. 114-117)
    # CQS-enum-keyed so data/tables builders read them back as dict[CQS, Decimal]
    # (byte-identical to the former module-level literals). Sovereign-derived vs
    # own-rating variants are kept separate per the regulation's table split.
    # =========================================================================
    "cgcb_risk_weights": LookupTable(
        name="cgcb_risk_weights",
        entries={
            CQS.CQS1: Decimal("0.00"),
            CQS.CQS2: Decimal("0.20"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("CRR", "114", "central govt / central bank RW by CQS"),
        default=Decimal("1.00"),
    ),
    "pse_risk_weights_sovereign_derived": LookupTable(
        name="pse_risk_weights_sovereign_derived",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("1.00"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "116", "(1) Table 2 PSE sovereign-derived RW"),
        default=Decimal("1.00"),
    ),
    "pse_risk_weights_own_rating": LookupTable(
        name="pse_risk_weights_own_rating",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "116", "(2) Table 2A PSE own-rating RW"),
        default=Decimal("1.00"),
    ),
    "rgla_risk_weights_sovereign_derived": LookupTable(
        name="rgla_risk_weights_sovereign_derived",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("1.00"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "115", "(1)(a) Table 1A RGLA sovereign-derived RW"),
        default=Decimal("1.00"),
    ),
    "rgla_risk_weights_own_rating": LookupTable(
        name="rgla_risk_weights_own_rating",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "115", "(1)(b) Table 1B RGLA own-rating RW"),
        default=Decimal("1.00"),
    ),
    "mdb_risk_weights_table_2b": LookupTable(
        name="mdb_risk_weights_table_2b",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.30"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("0.50"),
        },
        key="cqs",
        citation=Citation("CRR", "117", "(1) Table 2B non-named MDB RW by CQS"),
        default=Decimal("0.50"),
    ),
    # Institution RW tables (CRR Art. 120 Table 3 ECRA / Art. 120(2) Table 4
    # short-term / Art. 121 Table 5 sovereign-derived). CQS-enum-keyed.
    "institution_rw_crr": LookupTable(
        name="institution_rw_crr",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("0.50"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("CRR", "120", "Table 3 institution RW by CQS (CQS2 50%)"),
        default=Decimal("1.00"),
    ),
    "institution_short_term_rw_crr": LookupTable(
        name="institution_short_term_rw_crr",
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
        citation=Citation("CRR", "120", "(2) Table 4 short-term institution RW (<=3m)"),
        default=Decimal("0.20"),
    ),
    # CRR Art. 131 Table 7: dedicated short-term ECAI assessment risk weights,
    # shared by rated institutions and corporates. CQS 1 = 20%, CQS 2 = 50%,
    # CQS 3 = 100%, CQS 4-6/Others = 150%. Numerically identical to PRA PS1/26
    # Table 4A / Table 6A (packs/b31.py).
    "crr_short_term_ecai_risk_weights": LookupTable(
        name="crr_short_term_ecai_risk_weights",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("1.00"),
            CQS.CQS4: Decimal("1.50"),
            CQS.CQS5: Decimal("1.50"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "131", "Table 7 short-term ECAI RW"),
        default=Decimal("1.50"),
    ),
    "institution_rw_sovereign_derived": LookupTable(
        name="institution_rw_sovereign_derived",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("1.00"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.00"),
            CQS.CQS6: Decimal("1.50"),
        },
        key="cqs",
        citation=Citation("CRR", "121", "Table 5 sovereign-derived institution RW (unrated)"),
        default=Decimal("1.00"),
    ),
    "corporate_risk_weights": LookupTable(
        name="corporate_risk_weights",
        entries={
            CQS.CQS1: Decimal("0.20"),
            CQS.CQS2: Decimal("0.50"),
            CQS.CQS3: Decimal("1.00"),
            CQS.CQS4: Decimal("1.00"),
            CQS.CQS5: Decimal("1.50"),
            CQS.CQS6: Decimal("1.50"),
            CQS.UNRATED: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("CRR", "122", "Table 5 corporate RW by CQS"),
        default=Decimal("1.00"),
    ),
    "covered_bond_risk_weights": LookupTable(
        name="covered_bond_risk_weights",
        entries={
            CQS.CQS1: Decimal("0.10"),
            CQS.CQS2: Decimal("0.20"),
            CQS.CQS3: Decimal("0.20"),
            CQS.CQS4: Decimal("0.50"),
            CQS.CQS5: Decimal("0.50"),
            CQS.CQS6: Decimal("1.00"),
        },
        key="cqs",
        citation=Citation("CRR", "129", "Table 6A covered-bond RW by CQS (rated)"),
        default=Decimal("1.00"),
    ),
    # Unrated covered-bond RW derived from the issuing institution's own RW
    # (CRR Art. 129(5)(a)-(d)). Decimal-keyed: issuer-institution RW -> CB RW.
    # NB Art. 129(5)(b) maps 0.50 -> 0.20 (NOT 0.25, the PS1/26 value).
    "covered_bond_unrated_derivation_crr": LookupTable(
        name="covered_bond_unrated_derivation_crr",
        entries={
            Decimal("0.20"): Decimal("0.10"),
            Decimal("0.50"): Decimal("0.20"),
            Decimal("1.00"): Decimal("0.50"),
            Decimal("1.50"): Decimal("1.00"),
        },
        key="issuer_institution_rw",
        citation=Citation("CRR", "129", "(5)(a)-(d) unrated CB derivation from issuer RW"),
        default=Decimal("1.00"),
    ),
    # SA INSTITUTION/CORPORATE/RETAIL/DEFAULTED TAIL SCALARS (CRR Art. 121-127)
    "institution_short_term_unrated_rw_crr": ScalarParam(
        name="institution_short_term_unrated_rw_crr",
        value=Decimal("0.20"),
        citation=Citation("CRR", "121", "(3) unrated short-term institution 20%"),
    ),
    "crr_corporate_sme_rw": ScalarParam(
        name="crr_corporate_sme_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "122", "corporate SME flat 100% (Basel 3.1 reduces to 85%)"),
    ),
    "crr_non_regulatory_retail_rw": ScalarParam(
        name="crr_non_regulatory_retail_rw",
        value=Decimal("1.00"),
        citation=Citation("CRR", "123", "non-regulatory retail 100%"),
    ),
    "crr_defaulted_rw_high_provision": ScalarParam(
        name="crr_defaulted_rw_high_provision",
        value=Decimal("1.00"),
        citation=Citation("CRR", "127", "defaulted, provisions >= 20% of unsecured EAD"),
    ),
    "crr_defaulted_rw_low_provision": ScalarParam(
        name="crr_defaulted_rw_low_provision",
        value=Decimal("1.50"),
        citation=Citation("CRR", "127", "defaulted, provisions < 20%"),
    ),
    "crr_defaulted_provision_threshold": ScalarParam(
        name="crr_defaulted_provision_threshold",
        value=Decimal("0.20"),
        citation=Citation("CRR", "127", "20% provision threshold"),
    ),
    # SA REAL-ESTATE RW PARAMETERS (CRR Art. 125/126)
    "residential_mortgage_params": FormulaParams(
        name="residential_mortgage_params",
        params={
            "ltv_threshold": Decimal("0.80"),
            "rw_low_ltv": Decimal("0.35"),
            "rw_high_ltv": Decimal("0.75"),
        },
        citation=Citation("CRR", "125", "residential mortgage LTV<=80% 35% / excess 75%"),
    ),
    "commercial_re_params": FormulaParams(
        name="commercial_re_params",
        params={
            "ltv_threshold": Decimal("0.50"),
            "rw_low_ltv": Decimal("0.50"),
            "rw_standard": Decimal("1.00"),
        },
        citation=Citation("CRR", "126", "commercial RE LTV<=50%+income 50% / else 100%"),
    ),
    # ------------------------------------------------------------------
    # Reporting template inventory (Phase 7 S6). The COREP credit-risk +
    # CCR set per Reg (EU) 2021/451 Annex I as onshored (CRR Art. 430
    # reporting obligation) and the Pillar 3 disclosure set per Part Eight;
    # ids are the template-bundle field names. The declarative reporting
    # layer selects each template's regime TemplateSpec by ``variant``.
    "reporting_template_set": ReportingTemplateSet(
        name="reporting_template_set",
        corep=(
            "c_02_00",
            "c07_00",
            "c08_01",
            "c08_02",
            "c08_03",
            "c08_04",
            "c08_05",
            "c08_06",
            "c08_07",
            "c09_01",
            "c09_02",
            "c34_01",
            "c34_02",
            "c34_04",
            "c34_08",
        ),
        pillar3=(
            "ov1",
            "cr4",
            "cr5",
            "cr6",
            "cr6a",
            "cr7",
            "cr7a",
            "cr8",
            "cr9",
            "cr9_1",
            "cr10",
            "ccr1",
            "ccr2",
            "ccr3",
            "ccr8",
        ),
        variant="crr",
        citation=Citation(
            "CRR", "430", "COREP CR/CCR set per Reg (EU) 2021/451 Annex I; Pillar 3 per Part Eight"
        ),
    ),
}
