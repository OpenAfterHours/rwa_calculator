# Implementation Plan

**Last updated:** 2026-05-03 (curator audit pass)
**Package version:** 0.2.6 (pyproject.toml) | **Test suite:** 5,329 selectable (5,207 pass, 21 skipped, 11 deselected benchmarks)
**CRR acceptance:** 100% (169) | **B31 acceptance:** 100% (212) | **Comparison:** 100% (60) | **Stress:** 56 (+4 slow)
**Unit:** 4,397 | **Contract:** 145 | **Integration:** 122 | **Acceptance:** 497 selectable
**Source TODO/FIXME/HACK count:** 1 — `engine/hierarchy.py:2034` (tracked as P6.26)

**2026-05-03 audit summary**

- Closed (silent fix): P1.99, P1.121, P1.132
- Closed-claim-invalid: P1.131; P1.94 sub-claim (c)
- Re-scoped: P1.118 (partial), P4.2
- File:line drift: most `sa/calculator.py:14xx-17xx` refs now live in `sa/namespace.py` (re-scoped en masse rather than per-bullet — file:line still discoverable via grep on the named function).

---

## Status Legend

- [ ] Not started
- [~] Partial / needs rework
- [x] Complete

---

## Remaining Work — Prioritized Bullet List

Items are sorted by priority. Each item notes its ID, status, and effort estimate (S/M/L).

### Tier 1 — Calculation Correctness (must fix for regulatory accuracy)

- **P1.93** [ ] **NEW** — FCSM Art. 222(4) SFT zero-haircut 0%/10% exception not implemented. SFTs meeting Art. 227 zero-haircut conditions should get 0% RW (or 10% if counterparty is not a core market participant per Art. 227(3)). Art. 222(6) same-currency cash/sovereign 0% also not gated. No `is_core_market_participant` field in schema. **Effort: M** | Ref: PRA PS1/26 Art. 222(4)/(6), Art. 227(3)
- **P1.94** [~] **PARTIAL** — B31 currency mismatch 1.5x: 150% cap fixed v0.1.192; auto-detection wired (`sa/namespace.py:1582-1606`). Remaining: (a) `is_hedged` flag missing — multiplier fires whenever currencies differ; (b) 90%-coverage hedge test (Art. 123B(2)); (d) revolving instalment rule (123B(2A)); (e) pre-2027 portfolio fallback (123B(3)); (f) scope too broad — catches non-RRE CRE but 123B is retail (h) / residential RE (i) only; (g) CR5 pre-multiplier RW reporting + OF 02.00 row 0380 memo. **Effort: S** | Ref: PRA PS1/26 Art. 123B
- **P1.95** [ ] **REVISED** — B31 guarantee substitution uses flat 40% (B31) for unrated institution guarantors (`sa/calculator.py:1569-1578`, post-P1.149 fix). Under B31 should use SCRA grades A→40%, B→75%, C→150% per capital adequacy. **Effort: M** | Ref: PRA PS1/26 Art. 121/235
- **P1.96** [~] **DOWNGRADED** — Covered bond collateral haircut falls through to `other_physical` (40%). `haircuts.py:_normalize_collateral_type_expr` doesn't recognise `covered_bond`. PDF confirms covered bonds NOT listed in Art. 197 as eligible financial collateral; appear only in Art. 207(2) (repo) and Art. 161(1)(d) (F-IRB LGD 11.25%). Impact limited to narrow Art. 207(2) repo scenario. **Effort: S** | Ref: PRA PS1/26 Art. 197, 207(2), 224
- **P1.97** [x] FIXED v0.2.6.
- **P1.98** [x] FIXED v0.2.6.
- **P1.100** [x] **FIXED v0.2.10** — Art. 137 ECA score-to-RW direct mapping implemented for CRR sovereigns. New `eca_score` field on COUNTERPARTY_SCHEMA; `ECA_MEIP_RISK_WEIGHTS` Table 9 (0/0/20/50/100/100/100/150 %) in `data/tables/crr_risk_weights.py`; SA namespace gates Art. 137 between Art. 114 CQS lookup and 100% unrated fallback. Pinned by `tests/acceptance/crr/test_p1_100_art_137_eca_meip_sovereign.py` (5 tests).
- **P1.101** [x] **FIXED v0.2.10** — Art. 226(1) non-daily revaluation haircut scaling implemented. New `revaluation_frequency_days` field on COLLATERAL_SCHEMA; `engine/crm/haircuts.py` multiplies post-Art-226(2) collateral and FX haircuts by `sqrt((N_R + T_m − 1) / T_m)` when N_R > 1. Art. 227 zero-haircut short-circuit preserved. Pinned by `tests/acceptance/crr/test_p1_101_art_226_1_non_daily_revaluation.py` (6 tests).
- **P1.103** [ ] **NEW** — Art. 122(3) Table 6A short-term corporate ECAI risk weights not implemented. PRA PS1/26 introduces Table 6A: CQS1=20%, CQS2=50%, CQS3=100%, Others=150%. Neither spec nor code references Table 6A. Code falls through to long-term CQS table. **Effort: S** | Ref: PRA PS1/26 Art. 122(3)
- **P1.104** [x] **FIXED v0.2.11** — CRR Art. 239(1) FCSM maturity-mismatch eligibility gate implemented in `engine/crm/simple_method.py::compute_fcsm_columns()`. Collateral with `residual_maturity_years < exposure residual_maturity_years` is treated as ineligible (binary — Art. 239(2) `(t-0.25)/(T-0.25)` partial adjustment is FCCM/IRB only, not FCSM). Direct/facility/counterparty residual maturity coalesced for multi-level allocation. Pinned by `tests/acceptance/crr/test_p1_104_art_239_1_fcsm_maturity_eligibility.py` (8 tests). Note: plan-bullet citation was Art. 222(7); architect verified actual cite is Art. 239(1) — Art. 222(7) is a definition-extension paragraph for sovereign debt-securities scope.
- **P1.106** [x] FIXED v0.2.6.
- **P1.107** [x] FIXED v0.2.7.
- **P1.108** [~] **DISPUTED** — CRR 1.06 scaling applied to retail IRB. `formulas.py:360`/`namespace.py:488` apply 1.06 to ALL CRR classes. BCBS CRE31.23 retail has NO 1.06, but UK-onshored CRR Art. 154(1) (CRR PDF p.151) includes `× 12.5 × 1.06`. If UK text authoritative, code is correct. Needs PRA legal clarification. B31 unaffected. **Effort: S (if confirmed bug)** | Ref: CRR Art. 153(1)/154(1), BCBS CRE31.23
- **P1.109** [ ] **NEW** — Art. 237-238 maturity mismatch not applied to unfunded credit protection (guarantees/CDS). `guarantees.py` applies FX haircut but NO maturity mismatch. When guarantee maturity < exposure maturity, Art. 238 requires `GA = G* × (t-0.25)/(T-0.25)` reduction. Art. 237(2) requires ineligibility when residual < 3 months or original < 1 year. **Understates capital** for exposures with short-dated guarantees. **Effort: M** | Ref: CRR Art. 237-238
- **P1.110** [ ] **NEW** — B31 guarantee substitution CQS table uses CRR corporate weights (CQS 3=100%). `sa/calculator.py:1630-1631` maps corporate guarantor CQS 3-4 to 100% under both CRR and B31. B31 Table 6 gives CQS 3=75%. **Overstates capital** for B31 exposures with CQS 3 corporate guarantors. Related to P1.95 (SCRA) but distinct: P1.95 is about unrated institution guarantors, P1.110 is about rated corporate guarantors. **Effort: S** | Ref: PRA PS1/26 Art. 122(2) Table 6, Art. 235
- **P1.112** [x] FIXED v0.2.6.
- **P1.114** [x] FIXED v0.2.6.
- **P1.117** [x] FIXED v0.2.7.
- **P1.118** [~] **PARTIAL** — Art. 162(3) one-day maturity floor wired (`irb/formulas.py:705-707` reads `has_one_day_maturity_floor`, suppresses 1y floor). Remaining: broader carve-out for qualifying short-term exposures (trade finance ≤1y, FX settlement) — still get default M=2.5 unless caller pre-sets flag; no derivation from product-type/SFT inputs. **Effort: S** | Ref: CRR Art. 162(3)
- **P1.120** [ ] **NEW** — B31 SA defaulted provision-ratio denominator wrong. Art. 127(1) requires `provisions / gross_outstanding`; code uses `unsecured_ead` (post-provision, post-CRM). For partially collateralised exposures, smaller denominator pushes ratio below 20%, inflating RW from 100% to 150%. **Capital overstatement for collateralised defaults.** **Effort: S** | Ref: PRA PS1/26 Art. 127(1); `calculator.py:1250-1275`
- **P1.122** [ ] **NEW** — Guarantee substitution has no B31 framework branching. `_apply_guarantee_substitution()` (`sa/calculator.py:1428-1709`) has zero `is_basel_3_1` checks. Affects: (a) corporate CQS 3 = 100% (B31 Table 6 = 75%), (b) unrated institutions use CRR sovereign-derived (B31 = SCRA), (c) no short-term guarantor treatment. Subsumes P1.95 and P1.110. **Effort: M** | Ref: PRA PS1/26 Art. 122/121/235
- **P1.123** [ ] **NEW** — FCCM missing exposure volatility haircut (HE) for SFT exposures. Art. 223(5) formula: `E* = max(0, E(1+HE) - CVA(1-HC-HFX))`. `collateral.py` omits the `(1+HE)` gross-up on the exposure side. HE=0 for standard lending (correct), but HE>0 for SFTs where exposure is a debt security. **Understates E* and hence RWA for SFT portfolios.** **Effort: M** | Ref: CRR Art. 223(5)
- **P1.124** [x] FIXED v0.2.7.
- **P1.125** [x] FIXED v0.2.7.
- **P1.126** [x] FIXED v0.2.7.
- **P1.127** [ ] **NEW** — Art. 159 Pool B composition: upstream per-exposure EL shortfall may not include AVA / other own-funds reductions. Aggregator `_el_summary.py:197-201` two-branch rule relies on upstream `el_shortfall`/`el_excess`; if IRB/slotting compute as `max(0, EL - provisions)` excluding AVA (Art. 34/105), the rule mis-evaluates. Needs upstream verification. **Effort: S** | Ref: CRR Art. 159(1)
- **P1.128** [ ] **NEW** — B31 SCRA short-term missing Art. 121(4) trade finance ≤6m extension. SCRA branch at `sa/calculator.py:751-754` checks only `residual ≤ 0.25`, missing the `is_short_term_trade_lc & residual ≤ 0.5` clause that ECRA branch (`:730-739`) has. **Overstates capital** for unrated institution trade finance with 3-6m residual maturity. **Effort: S** | Ref: PRA PS1/26 Art. 121(4)
- **P1.130** [ ] **NEW** — Aggregator summaries use pre-floor RWA. `aggregator.py:92-96` builds `summary_by_class`/`summary_by_approach` from `post_crm_detailed` before the floor at `:152`. Polars LazyFrames are immutable — summaries don't reflect floored RWA. **Understates reported RWA** when floor binds. Move summary generation post-floor or regenerate from floored frame. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P1.30(e)** [ ] Art. 234 partial protection tranching — structured protection covering only part of the loss range. Not modelled. **Effort: L** | Ref: PRA PS1/26 Art. 234
- **P1.105** [x] **FIXED v0.2.12** — PRA PS1/26 Art. 120(2B) Table 4A short-term institution ECAI risk weights implemented. New optional `has_short_term_ecai` Boolean on `FACILITY_SCHEMA` (default False); new `B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS` table in `data/tables/b31_risk_weights.py` (CQS1=20%, CQS2=50%, CQS3=100%, CQS4-5=150%); `_b31_append_institution_maturity_branches` (`engine/sa/namespace.py`) gates Table 4A ahead of Table 4 fallback when `is_institution & is_rated & has_short_term_ecai & in_st_window`; `engine/hierarchy.py::_propagate_facility_qrre_columns` extended to OR-aggregate the flag across counterparties so loans inherit it. CRR path unchanged. Pinned by `tests/acceptance/basel31/test_p1_105_art_120_2b_short_term_institution_ecai.py` (5 tests).
- **P1.10** [ ] Unfunded credit protection transitional (PRA Rule 4.11) — narrow eligibility carve-out for legacy contracts during 1 Jan 2027–30 Jun 2028. Requires Art. 213 eligibility validation first. **Effort: M** | Ref: PRA PS1/26 Rule 4.11
- **P1.151** [ ] **NEW** — Purchased receivables / dilution-risk LGD missing (Art. 161(1)(e)–(g)). `src/rwa_calc/engine/irb/firb_lgd.py`. No `purchased_receivables_senior`, `_subordinated`, `dilution_risk` keys. Exposures default to 45% senior. B3.1 dilution-risk LGD = 100% not applied. **Effort: M** | Ref: PRA PS1/26 Art. 161(1)(e)-(g)
- **P1.153** [ ] **NEW** — Art. 155(3) PD/LGD equity approach entirely absent. `src/rwa_calc/engine/equity/`. No `EquityApproach.PD_LGD` enum, no Art. 165 floor table (0.09%/0.40%/1.25%), no M=5y equity handling, no EL×12.5+RWEA cap. Required under CRR; removed under B3.1. **Effort: L** | Ref: CRR Art. 155(3), Art. 165
- **P1.154** [ ] **NEW** — `international_org` collapsed into MDB. `src/rwa_calc/engine/classifier.py:80, 119`, `src/rwa_calc/domain/enums.py`. Art. 112(1)(e) international organisations (IMF, BIS) misclassified as MDB. Add `ExposureClass.INTERNATIONAL_ORGANISATION`; route SA and IRB mappings accordingly. **Effort: M** | Ref: CRR Art. 112(1)(e), Art. 117-118
- **P1.156** [x] FIXED v0.2.7.
- **P1.157** [x] **FIXED v0.2.11** — PSM PD floor now uses guarantor's exposure-class context (Art. 160(4) / 163(1)). `_pd_floor_expression` extended with `exposure_class_col` / `transactor_col` kwargs (additive, backward-compatible); three call sites in `engine/irb/guarantee.py` (`_apply_parameter_substitution`, `_adjust_expected_loss`, `_apply_double_default`) now read `guarantor_exposure_class` instead of the borrower's row-level `exposure_class`, so a corporate guarantor's PD is floored at corporate 0.05% rather than the borrower's QRRE-revolver 0.10%. The NBD floor (`_apply_no_better_than_direct_floor`) was already present but the prior fixture/test were degenerate; replaced with a binding configuration. Pinned by `tests/acceptance/basel31/test_p1_157_psm_no_better_than_direct.py` (13 tests).
- **P1.158** [x] FIXED v0.2.6.
- **P1.159** [ ] **NEW** — PSM correlation re-derivation reads borrower row, not guarantor. `irb/guarantee.py::_parametric_irb_risk_weight_expr` Step 3 pulls `exposure_class`/`turnover_m`/`requires_fi_scalar` from borrower LF columns. Art. 236(1)(a)(i) requires guarantor's correlation curve when guarantor and borrower sit in different exposure classes. **Effort: M** | Ref: PRA PS1/26 Art. 236(1)(a)(i); `irb/guarantee.py`
- **P1.160** [ ] **NEW** — PSM LGD substitution always reads senior-unsecured F-IRB scalar. `irb/guarantee.py::_apply_parameter_substitution:300-301` Step 2 reads `unsecured_senior` for every row, collapsing subordinated guarantees (Art. 161(1)(b), 75%) and covered-bond guarantees (Art. 161(1)(d), 11.25%) onto senior LGD. Distinct from P1.156 (substitution-rule scalar); P1.160 is about row-wise table routing by guarantor seniority. **Effort: M** | Ref: PRA PS1/26 Art. 161(1)(aa)/(b)/(d)
- **P1.161** [ ] **NEW** — PRA Art. 191A(2)(e)/(f) two-layer protection look-through not implemented. (2)(e): apply funded-collateral framework through an unfunded guarantee where guarantor has posted eligible collateral. (2)(f): borrower-deeming flexibility for CRM-method selection. `engine/crm/processor.py` treats funded/unfunded as distinct portions. Distinct from P1.30(e). **Effort: M** | Ref: PRA PS1/26 Art. 191A(2)(d)-(f)
- **P1.162** [ ] **NEW** — UKB OV1 missing seven mandatory output-floor disclosure rows. `B31_OV1_ROWS` (`pillar3/templates.py:125-139`) jumps from row 4 to 5 and 24 to 26 — omits Annex XX rows **4a** (Total RWEAs pre-floor), **5a/5b/6a/6b/7a/7b** (CET1/Tier1/Total ratios pre-floor / pre-floor transitional). Add seven `P3Row` entries; wire `_generate_ov1()` row 4a from pre-floor totals; rows 5a-7b nullable with firm override hook. Refresh fixtures/goldens. **Effort: S–M** | Ref: PRA PS1/26 Annex XX UKB OV1, Art. 92(2A)/(5)

<!-- ### Migrated from DOCS_IMPLEMENTATION_PLAN.md on 2026-05-03 -->
<!-- D3.1, D3.4, D3.6, D3.11–D3.23, D3.27, D3.29, D3.36–D3.39, D3.43 → P1.163–P1.185. -->
<!-- These items are code-side only; the docs side has already been corrected. -->

- **P1.164** [x] **FIXED v0.2.12** — CRR IRB Simple `GOVERNMENT_SUPPORTED` collapsed to Art. 155(2)(c) "all other equity" 370%. `data/tables/crr_equity_rw.py` `IRB_SIMPLE_EQUITY_RISK_WEIGHTS[GOVERNMENT_SUPPORTED]` updated 1.90 → 3.70 with Art. 155(2)(c) citation; redundant `is_government_supported` / `equity_type=="government_supported"` branches in `engine/equity/calculator.py::_apply_equity_weights_irb_simple` removed (fall-through to `.otherwise(_IRB_RW[OTHER])` now produces the correct 370%). Basel 3.1 unaffected — Art. 155 left blank under PS1/26, B31 routes through Art. 133(3) 250%. Pinned by `tests/acceptance/crr/test_p1_164_art_155_2c_government_supported_irb_simple.py` (5 tests) plus updated CRR-J14 acceptance and unit-table assertions.
- **P1.165** [ ] **NEW (migrated from D3.6, 2026-05-03)** — CRR receivables haircut 0.20 in `haircuts.py:71` is an "ad-hoc approximation" with no regulatory basis. Spec correctly states non-financial collateral does not use Art. 224 haircuts (Art. 230 C*/C** mechanism applies instead). Code-quality cleanup: either remove the receivables haircut entirely or annotate the constant with regulatory rationale. **Effort: S** | Ref: CRR Art. 224, Art. 230
- **P1.167** [~] **Tracked as P2.14** — CRR HIGH_RISK class active despite Art. 128 omitted by SI 2021/1078. Resolve under P2.14. **Effort: S**
- **P1.169** [x] FIXED v0.2.6.
- **P1.173** [~] **Tracked as P2.17** — CRR retail payroll/pension 35% not implemented in CRR path (CRR2 added it). Sub-gap (cosmetic, see P1.175): comments at `b31_risk_weights.py:212` and `schemas.py:80,101,642` cite "Art. 123(3)(a-b)" — should be Art. 123(4). **Effort: S** | Ref: CRR Art. 123(4)
- **P1.174** [~] **Tracked as P1.120** — B31 defaulted provision-ratio denominator uses `unsecured_ead` instead of gross outstanding (Art. 127(1)). Resolve under P1.120. **Effort: S**
- **P1.177** [x] **FIXED v0.2.10** — UK CRR slotting now ignores `is_hvcre` per Art. 153(5) Table 1 (UK has no EU HVCRE Table 2). `engine/slotting/namespace.py` and `data/tables/crr_slotting.py` route all SL through Table 1 weights and Table B EL rates under CRR; Basel 3.1 HVCRE handling unchanged. CRR-E4/E7/E8 expected outputs patched; CRR-E9 added. 20 pre-existing tests that codified the bug were deleted/updated. Pinned by `tests/acceptance/crr/test_p1_177_art_153_5_uk_crr_no_hvcre.py` (5 tests) plus updated CRR-E suite.
- **P1.178** [~] **Tracked as P1.122** — B31 guarantee substitution missing framework branching. Subsumes P1.95/P1.110. Resolve under P1.122. **Effort: M**
- **P1.179** [ ] **NEW** — `firb_lgd.py::get_firb_lgd_table()` always returns CRR values; B31 equivalent is `get_b31_firb_lgd_table()` separately — naming creates confusion risk. Rename to `get_crr_firb_lgd_table()` or add `is_basel_3_1` param. **Effort: S**
- **P1.180** [ ] **NEW** — `covered_bond_unrated_derivation` in `crr_risk_weights.py` has 7 entries but CRR Art. 129(5) only produces 4. Extra 3 entries (30/40/75%) only arise under B31 SCRA. Split into `_CRR` (4) and `_B31` (7) keyed off `config.is_basel_3_1`. **Effort: S** | Ref: CRR Art. 129(5)
- **P1.181** [x] **FIXED v0.2.11** — CRR Art. 126(2)(d) commercial RE proportion split implemented. `_crr_append_real_estate_branches` (`engine/sa/namespace.py`) residual leg now uses `_cqs_table_lookup_expr` against `CORPORATE_RISK_WEIGHTS` (per Art. 124(1)) instead of the constant 100%; `engine/hierarchy.py::_coerce_loans_to_unified` defensively passes through the CLASSIFIER_OUTPUT_SCHEMA RE columns so the CRE branch entry conditions are met. Pinned by `tests/acceptance/crr/test_p1_181_art_126_cre_proportion_split.py` (7 tests, with the LTV 0.80 corporate-CQS1 row discriminating proportion split from naïve whole-loan).
- **P1.182** [x] FIXED v0.2.7.
- **P1.183** [ ] **NEW** — CRR Art. 164(4) portfolio-level LGD floors not implemented. `LGDFloors.crr()` returns zeros; Art. 164(4) (CRR2) imposes portfolio-level minimum LGD: ≥10% retail residential RE, ≥15% retail commercial RE. Per-exposure architecture can't enforce directly. **Capital impact: understatement.** Add post-aggregation validation step computing EW avg LGD per retail RE sub-class; emit error or re-floor. **Effort: M** | Ref: UK CRR Art. 164(4)
- **P1.184** [ ] **NEW** — CRR MDB RW table uses B31 Table 2B values. `crr_risk_weights.py:231-246` defines `MDB_RISK_WEIGHTS_TABLE_2B` with CQS 2 = 30%, unrated = 50%. CRR Art. 117(1) treats non-0% MDBs as institutions (Table 3 CQS 2 = 50% under CRR). **Capital impact: understatement** for CRR MDB CQS 2 (20pp) and unrated (50pp). Under CRR route non-named MDBs to institution lookup; B31 Table 2B is correct. **Effort: M** | Ref: CRR Art. 117(1)

#### Tier 1b — Source-code docstring corrections (cosmetic, no calculation impact)

These items are docstring / code-comment / structural-organisation corrections only. The calculations they describe are correct; the bugs are in the prose surrounding them. Tagged Effort: S.

- **P1.163** [ ] **NEW (migrated from D3.1, 2026-05-03; docstring only)** — `formulas.py:62-63` docstring: retail mortgage PD floor = 0.05%, QRRE transactors PD floor = 0.03%. Correct values per regulation: **0.10%** and **0.05%** respectively. Code constants and other docs use the right values; this is a docstring-only typo with no calculation impact. **Effort: S** | Ref: PRA PS1/26 Art. 160(1)
- **P1.166** [ ] **NEW (docstring only)** — `equity/calculator.py:21` says "CIU fallback: 150% → 250%". Both wrong — Art. 132(2) fallback = **1,250%**. Constants correct (P1.119/v0.1.184); module docstring stale. **Effort: S** | Ref: PRA PS1/26 Art. 132(2)
- **P1.168** [ ] **NEW (docstring only)** — `b31_risk_weights.py:16` and `:327` say "CQS5: 100%"; PRA retains CQS 5 = **150%**. Constant at `:143` is correct (`Decimal("1.50")`); docstrings only. **Effort: S** | Ref: PRA PS1/26 Art. 122 Table 6
- **P1.171** [ ] **NEW (structural)** — `SA_EQUITY_RISK_WEIGHTS` CRR-correct (100% flat) except CIU (150% instead of 1,250%) which is fixed by P1.119/P1.170. No-op once P1.170 verified. **Effort: S** | Ref: CRR Art. 133(2)
- **P1.175** [ ] **NEW (comment refs)** — Art. 114 para errors in comments across `calculator.py`/`classifier.py`/`eu_sovereign.py`/`guarantee.py` cite "Art. 114(3)/(4)" for domestic currency. UK = 114(4); EU = 114(7). Bundle with P1.173 sub-gap. **Effort: S** | Ref: CRR Art. 114(4)/(7), Art. 123(4)
- **P1.185** [ ] **NEW (docstring only)** — `domain/enums.py:320` `SCRAGrade.B` docstring has fabricated CET1/leverage thresholds. Art. 121(1)(b) defines Grade B qualitatively — no thresholds in regulation. Lookup logic unchanged. **Effort: S** | Ref: PRA PS1/26 Art. 121(1)(b)

- **P1.186** [~] **PARTIAL — re-opened 2026-05-03** — FX collateral Hfx defaults to 10-day (8%); Art. 224(2) requires 20-day (11.314%) for secured lending. `engine/crm/haircuts.py:130-136` `fill_null(10)` on `liquidation_period_days`, but no code populates from `is_sft`/transaction type. Per-period constants exist at `data/tables/haircuts.py:146-148` but unwired. **Capital impact:** ~3.07% RWA understatement on FX-mismatched protected secured lending. Closes `liquidation_period as config` from P6.15. **Effort: S** | Ref: CRR Art. 224(2)(a)
- **P1.187** [x] FIXED v0.2.7.
- **P6.9** [~] Provision pro-rata weight uses pre-CCF approximation (`drawn + interest + nominal`) instead of spec's `ead_gross`. Reasonable but diverges from spec. **Effort: S** | Ref: CRM spec
- **P6.15** [~] 3 missing schema fields: `protection_inception_date` (P1.10), `contractual_termination_date` (P1.20 revolving maturity), `liquidation_period` as config (P1.39 dependency, now tracked as P1.186). **Effort: S**

### Tier 2 — Test Coverage Gaps (no code changes, but essential for confidence)

- **P5.11** [ ] **NEW** — Missing acceptance tests for secondary SA exposure classes. Covered bonds, PSE, RGLA, MDB, high-risk items, and other items (Art. 134) have 60-120 unit tests each but ZERO end-to-end acceptance tests. Need CRR and B31 acceptance scenarios. **Effort: M**
- **P5.12** [ ] **NEW** — Missing B31 acceptance tests for Art. 129A covered bond changes (SCRA-derived unrated RW). Only unit tests exist. **Effort: S**
- **P5.13** [ ] **NEW** — Missing acceptance tests for Art. 124A-124L RE treatment scenarios under B31 (income-dependent/non-dependent, commercial sub-types, Other RE Art. 124J). Only unit tests. **Effort: S**
- **P5.14** [ ] **NEW** — No integration/acceptance tests for COREP or Pillar III reporting generators. All 663+ COREP tests and 197+ Pillar III tests are unit tests with synthetic data. No test validates full pipeline → reporting output. **Effort: M**
- **P5.15** [ ] **NEW** — Art. 123A(1)(b)(ii) 0.2% portfolio granularity sub-condition not implemented or tracked. The retail qualifying check only enforces the GBP 880k threshold, not the condition that no single exposure may exceed 0.2% of the total retail portfolio. Low impact (most portfolios satisfy this naturally). **Effort: M**

### Tier 3 — COREP Reporting Completeness

- **P2.14** [ ] **NEW** — CRR engine applies Art. 128 high-risk 150% RW despite UK omission (D3.12). Art. 128 was removed from UK onshored CRR by SI 2021/1078 effective 1 Jan 2022 — no legal basis for the HIGH_RISK exposure class under CRR until Basel 3.1 reintroduces it from 2027. Conservative overstatement. **Effort: S** | Ref: SI 2021/1078, `calculator.py:1051-1055`
- **P2.13** [~] **UPGRADED TO P1.123** — FCCM exposure volatility haircut (HE) upgraded to P1 (Tier 1) as P1.123 after Phase 7 audit confirmed SFT capital understatement impact.
- **P2.12** [ ] **NEW** — C 07.00 / OF 07.00 missing col 0020 "Exposures deducted from own funds". Standard column between 0010 and 0030. Template submission validation will flag this. **Effort: S**
- **P2.1** [~] COREP template rework — see detailed section below.
- **P2.5** [~] COREP missing row structure — OF 02.00 sub-class breakdown rows (0295-0297, 0355-0356, 0382-0385) need `cp_is_fse`/`is_sme` pipeline columns. OF 08.01 revolving row 0017 needs pipeline column. **Effort: M**
- **P2.7** [~] COREP pre-credit-derivative RWEA (row 0310) — approximated as total RWEA. Accurate split requires per-exposure pre/post CD tracking in CRM pipeline. **Effort: M**
- **P2.17** [ ] **NEW** — CRR payroll/pension loan 35% RW not applied in CRR code path. `calculator.py:993-995` applies flat 75% to all CRR retail. CRR2 (Reg 2019/876) introduced Art. 123 second subparagraph giving 35% for qualifying payroll/pension loans. `is_payroll_loan` flag and 35% logic exist only in B31 branch. Conservative overstatement. **Effort: S** | Ref: CRR Art. 123 (CRR2 amendment)
- **P2.16** [ ] **NEW** — Output floor edge cases: (a) GCRA cap not enforced when S-TREA=0 (`_floor.py:77` passes GCRA uncapped; should be 0.0 per "1.25% of S-TREA"); (b) S-TREA fallback to `rwa_final` when `sa_rwa` absent (`aggregator.py:138`) skews GCRA cap on audit path. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P2.15** [ ] **NEW** — Equity transitional Rules 4.7-4.8 (CIU underlyings for IRB-permissioned firms) not implemented. Code excludes CIU look-through/mandate-based from transitional floor entirely — correct for SA-only firms (Rules 4.1-4.3) but wrong for IRB firms where Art. 155 CIU underlyings should use higher-of IRB/transitional SA. Also, opt-out election (Rules 4.9-4.10) has no config flag. **Effort: S** | Ref: PRA PS1/26 Rules 4.7-4.10, `calculator.py:690-693`
- **P2.18** [ ] **NEW** — Art. 226(1) non-daily revaluation haircut scaling missing. When collateral revalued less frequently than daily, supervisory haircuts should be scaled by `sqrt((NR + T_m - 1) / T_m)`. `haircuts.py` scales by liquidation period but has no NR factor. No `revaluation_frequency_days` input field. **Effort: S** | Ref: CRR Art. 226(1)
- **P2.19** [ ] **NEW** — Higher-risk equity Art. 133(4) definition relies on pre-classified `equity_type` instead of evaluating regulatory conditions dynamically. No `is_held_for_short_term_resale` or `is_derived_from_derivative` flags in schema. If input data doesn't pre-classify correctly, unlisted equity held for short-term resale gets 250% instead of 400%. **Effort: S** | Ref: PRA PS1/26 Art. 133(4)
- **P2.20** [ ] **NEW** — `OutputFloorSummary.total_rwa_post_floor` field name misleading — only contains floored IRB+slotting component, excludes SA and equity RWA. **Effort: S** | Ref: `_floor.py:253`
- **P2.21** [ ] **NEW** — Pipeline error conversion drops ALL `CalculationError` metadata (not just `regulatory_reference`). `pipeline.py:348-356` uses `getattr(error, "error_type", "unknown")` and `getattr(error, "context", {})` but `CalculationError` has no such attributes. Audit trail severely degraded. **Effort: S**
- **P1.137** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.2/4.3 SA ladder not implemented. PS1/26 Rule 4.2 (SA standard equity 160% 2027 / 190% 2028 / 220% 2029 → 250% 2030) and Rule 4.3 (higher-risk equity 220% 2027 / 280% 2028 / 340% 2029 → 400% 2030) not applied. **Capital overstatement in transitional 2027-2029 for SA-only firms.** **Effort: M** | Ref: PRA PS1/26 Rule 4.2-4.3
- **P1.138** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.6 IRB higher-of not implemented. IRB firms holding Art. 155 permission on 31 Dec 2026 should take `max(legacy Art. 155 RW, Rule 4.2/4.3 transitional SA RW)` through 2029. Code transitions instantly to new Art. 133 treatment. **Effort: M** | Ref: PRA PS1/26 Rule 4.4-4.6
- **P1.139** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.8 CIU higher-of not implemented. Look-through / mandate-based CIU firms should take `max(legacy Art. 155(2) simple RW, new Rule 4.2/4.3 RW)` during transitional period. **Effort: M** | Ref: PRA PS1/26 Rule 4.7-4.8
- **P1.140** [ ] **NEW (Phase 9)** — ADC classification flag-only; no derivation logic. `engine/classifier.py` has zero `is_adc` logic. User must pre-tag; a mis-flagged CRE/RRE development loan silently routes to corporate 75-100% instead of the 150% ADC weight. **Capital understatement** for mis-tagged land-acquisition/development/construction loans. **Effort: M** | Ref: PRA PS1/26 Art. 124(3), Art. 124K
- **P1.141** [ ] **NEW (Phase 9)** — Art. 124(4) mixed residential/commercial RE splitting not implemented. No code splits a mixed-use exposure into RRE/CRE portions proportional to collateral value. **Effort: M** | Ref: PRA PS1/26 Art. 124(4)
- **P1.142** [ ] **NEW (Phase 9)** — Art. 124E three-property limit for "materially dependent" not automated. Natural-person obligors with 4+ BTL properties should be pushed to Art. 124G (income-dependent) risk weights. Currently no derivation — caller must manually set `is_income_producing_re`. **Understates capital** where the three-property test is not correctly pre-tagged. **Effort: M** | Ref: PRA PS1/26 Art. 124E(2)
- **P1.143** [ ] **NEW (Phase 9)** — Rule 4.11 unfunded credit protection grandfathering window (1 Jan 2027 – 30 Jun 2028) not honoured. Distinct from P1.10 (which is the underlying Art. 213 eligibility check; P1.143 is the transitional date-gated relaxation that depends on it). **Effort: M** | Ref: PRA PS1/26 Rule 4.11
- **P1.144** [x] FIXED v0.2.7.
- **P1.145** [ ] **NEW (Phase 9)** — Classifier `unique(subset=[exposure_reference], keep="first")` non-deterministic on duplicate permissions. `engine/classifier.py:832-844`. When `model_permissions` has duplicate rows for the same exposure, `keep="first"` depends on row order — which is not guaranteed. Changing input order can silently flip IRB↔SA. **Effort: S** | Ref: classifier model_permissions resolution
- **P1.146** [ ] **NEW (Phase 9)** — `is_guaranteed` null filter drops rows in CRM reporting. `engine/aggregator/_crm_reporting.py:138,166,212` filters on `is_guaranteed == True`. `engine/crm/guarantees.py:260` doesn't `fill_null(False)` before feeding the aggregator. Guaranteed exposures with null `is_guaranteed` are silently dropped from CR7/CR7A Pillar III disclosures. **Effort: S**
- **P1.147** [ ] **NEW (Phase 9)** — `ValidationRequest` does not require `model_permissions` for IRB permission mode. Missing file silently falls back to SA for all exposures when users have requested IRB. **Silent capital overstatement**. **Effort: S** | Ref: IRB permission gating
- **P2.22** [ ] **NEW (Phase 8)** — Supporting factors `min()` instead of Art. 501(2) substitution rule. `supporting_factors.py:324` uses `pl.min_horizontal(sme_factor, infra_factor)` when both apply. CRR Art. 501(2) second subparagraph says "multiply by the factor in Article 501a **instead**" — infrastructure replaces SME when both qualify. **Capital understatement** (should use 0.75). Rare overlap. **Effort: S** | Ref: CRR Art. 501(2), Art. 501a(1)
- **P2.23** [ ] **NEW** — Equity excluded from output-floor U-TREA/S-TREA. `_schemas.py:30-35` `FLOOR_ELIGIBLE_APPROACHES` covers only IRB/slotting; equity (`approach_applied="EQUITY"`) is non-eligible. CRR equity IRB Simple RWA missing from U-TREA. S-TREA also omits market (ASA), op (SMA), CVA. Surface on `OutputFloorSummary`. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P2.24** [ ] **NEW (Phase 8)** — Hierarchy resolver counterparty join may fan out on duplicate org_mappings. `hierarchy.py:491-501` joins counterparties with `org_mappings` without deduplicating by `child_counterparty_reference`. Multiple parent mappings (data quality issue) silently multiply exposure rows. **Effort: S**
- **P2.25** [ ] **NEW (Phase 9)** — CR5 special disclosure rules not implemented. `reporting/pillar3/generator.py:325-359` omits: (a) currency mismatch multiplier exposures reported at pre-multiplier RW with post-multiplier RWEA; (b) regulatory RE not-materially-dependent split up to / above 55% LTV; (c) equity transitional reported at end-state RW. **Effort: M** | Ref: PRA PS1/26 Annex XX §CR5
- **P2.26** [ ] **NEW (Phase 9)** — COREP Annex II sign-convention violated for (-) labelled columns. `reporting/corep/generator.py:3140-3214, 3385-3406` emits positive sums for columns 0030/0035/0050/0060/0070/0080/0090/0130/0140/0290, which are declared negative in Annex II §1.3. **PRA DPM validation will reject returns.** **Effort: S** | Ref: COREP Annex II §1.3
- **P2.27** [ ] **NEW (Phase 9)** — OF 08.01 col 0275 uses IRB EAD not SA-equivalent. `reporting/corep/generator.py:3615`. Annex II §OF 08.01 col 0275 requires SA-equivalent post-CCF / post-CRM EAD. Using IRB EAD overstates the non-modelled exposure denominator for the output floor. **Effort: S** | Ref: COREP Annex II §OF 08.01 col 0275
- **P2.28** [ ] **NEW (Phase 9)** — CR9 row taxonomy incomplete. `reporting/pillar3/templates.py:565-580` missing AIRB RE 4-way sub-class split (resi SME, resi non-SME, comm SME, comm non-SME) and FIRB "financial / large corporates" sub-row. **Superseded by P2.49** which expresses the full row taxonomy. **Effort: S** | Ref: PRA PS1/26 Annex XXII §CR9
- **P2.29** [ ] **NEW (Phase 9)** — OV1 equity sub-approach rows hard-coded null. `reporting/pillar3/generator.py:275-277`. B31 OV1 rows 11 (IRB Trans), 12 (LTA), 13 (MBA), 14 (Fall-back) always null despite the pipeline having the source columns. Rows 26/27 (floor multiplier / OF-ADJ) also null. **Effort: S** | Ref: PRA PS1/26 Annex XX §OV1
- **P2.30** [ ] **NEW (Phase 9)** — CCF Annex I row discrimination incomplete: Row 3 (non-credit-substitute issued OBS, 50%) not distinguishable from Row 4 (NIFs/RUFs). `domain/enums.py:346-403` exposes only 6 `RiskType` values versus the Annex I taxonomy. Reporting-only impact (RWA unaffected) but prevents Annex I-faithful disclosure. **Effort: S** | Ref: CRR Annex I
- **P2.31** [ ] **NEW (Phase 9)** — No Annex I concrete-item-to-risk-type mapping table in code or spec. `engine/ccf.py:76-122`. Users must manually map acceptances, performance bonds, warranties, tender bonds, etc. to the right Annex I row. **Silent misclassification risk** under CCF. **Effort: M** | Ref: CRR Annex I
- **P2.32** [ ] **NEW (Phase 9)** — CCF Art. 166(5) / Art. 166E(5) purchased-receivables 40%/10% not implemented. `engine/ccf.py` has no purchased-receivables branch. **Effort: M** | Ref: CRR Art. 166(5), PRA PS1/26 Art. 166E(5)
- **P2.33** [ ] **NEW (Phase 9)** — CCF UK residential mortgage commitment Row 4(b) 50% PRA deviation not enforceable. No flag or derivation for "UK residential mortgage commitment"; caller must manually tag as MR else falls through to OC = 40%. **UK-specific capital understatement risk** when un-tagged. **Effort: S** | Ref: PRA PS1/26 Annex I Row 4(b)
- **P2.34** [ ] **NEW (Phase 9)** — Output validation has no regulatory output-bounds checker. `src/rwa_calc/contracts/validation.py` validates inputs only; no `validate_aggregated_bundle` asserting RW ≤ 12.5, RWA ≥ 0, `ead_final` non-null. Corrupt results can leave the pipeline undetected. **Effort: S** | Ref: internal contract hardening
- **P2.35** [ ] **NEW (Phase 9)** — Hierarchy silently truncates at `max_depth=10`. `engine/hierarchy.py:233, 1908, 1942`. No error emitted when a parent chain exceeds 10 hops. **Effort: S** | Ref: internal hierarchy contract
- **P2.36** [ ] **NEW** — Sovereign/institution PD floors not first-class config fields. `src/rwa_calc/contracts/config.py` `PDFloors`. No `sovereign`/`institution` fields; correct 0.05% floor applied by accident via corporate-floor fallback. **Effort: S** | Ref: PRA PS1/26 Art. 160(1)
- **P2.37** [ ] **NEW** — Art. 155(4) Internal Models Approach (CRR equity) entirely absent. VaR-based equity capital with PRA-permission gate. Lower priority than P1.153 (PD/LGD approach). **Effort: L** | Ref: CRR Art. 155(4)
- **P2.38** [ ] **NEW** — Non-trading-book short-position netting (Art. 155(2)) not modelled. **Effort: M** | Ref: CRR Art. 155(2)
- **P2.39** [ ] **NEW** — Art. 147A(1)(h) equity SA-only not a hard block. `src/rwa_calc/engine/classifier.py:1039`, `_b31_sa_only`. Currently relies on absence of IRB permissions. Add explicit `EQUITY` guard. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(h)
- **P2.40** [ ] **NEW** — model_id precedence chain incomplete. `src/rwa_calc/engine/hierarchy.py:1288–1295`. Only counterparty-level `internal_model_id` consulted; spec specifies exposure → facility → loan → model_permissions default. **Effort: M** | Ref: model_permissions spec
- **P2.41** [ ] **NEW** — `exposure_subclass` for Art. 147A(1)(e)/(f) COREP split. `src/rwa_calc/engine/classifier.py`, `domain/enums.py`. Note: previously attributed to P2.28, but P2.28 covers CR9 row taxonomy. Separate need. **Effort: M** | Ref: PRA PS1/26 Art. 147A(1)(e)/(f)
- **P2.42** [ ] **NEW** — OF 02.01 col 0030 U-TREA should be 0010+0020 sum. `src/rwa_calc/engine/reporting/corep/generator.py:2988–2993`. Currently col 0030 copies `modelled_rwa` only; should be arithmetic sum per COREP instructions. **Effort: S** | Ref: COREP OF 02.01 instructions
- **P2.43** [ ] **NEW** — PSM LGD source switch (Art. 236(1)(a)(i) option (i)) not exposed. Only option (ii) (guarantor F-IRB scalar) wired in `irb/guarantee.py::_apply_parameter_substitution`. Add `psm_lgd_source` switch on `IRBPermissions` for option (i) (borrower-unprotected LGD). Distinct from P1.160. **Effort: S** | Ref: PRA PS1/26 Art. 236(1)(a)(i)
- **P2.44** [ ] **NEW** — Art. 139(2B) ECAI rating-attribution disapplication for SA SL not enforced. IRB firm routing SA SL through Art. 122B(1) must use only directly applicable ECAI, not 139(2)/(2A) inferred fallbacks. Engine has single `external_cqs` with no provenance flag. Add `rating_is_issue_specific`/`rating_is_inferred` Bool. **Effort: S–M** | Ref: PRA PS1/26 Art. 122B(1), 139(2)/(2A)/(2B)
- **P2.45** [ ] **NEW** — Art. 143(6) Overseas Model Approach (OMA) not represented. New B31 IRB permission for retail/SME-corp of equivalent-jurisdiction overseas subs, capped at 7.5% of group RWA / EV pre-output-floor. Need: OMA enum, jurisdiction-equivalence Bool, post-aggregation cap validation, Art. 143(6)(c)-(k) checks. **Effort: M** | Ref: PRA PS1/26 Art. 143(6)/(7)/(8)
- **P2.46** [ ] **NEW** — CRR Art. 150(1) PPU provenance enum missing on `model_permissions`. COREP col 0050 ("PPU SA") indistinguishable from Art. 148 roll-out or no-permission SA. Add `ppu_reason` enum. Sub-finding: Art. 150(2) firm-level equity materiality (10%/5% own funds) not enforced — note as non-goal. **Effort: S–M** | Ref: CRR Art. 150(1)/(2); PRA Art. 150(1A)
- **P2.47** [ ] **NEW** — Art. 136 ECAI grade strings, Art. 137 OECD MEIP direct-to-RW, and Art. 138 second-best selection not implemented. Engine accepts only raw CQS integers. Need: Art. 136 grade-string→CQS map; Art. 137 Table 9 MEIP 0-7→RW direct (not via CQS); Art. 121 sovereign-derived institution propagation; Art. 138 second-best across ECAI+ECA. Distinct from P1.100. **Capital impact:** unrated sovereigns with low MEIP default to 100% instead of 0%/20%. **Effort: M** | Ref: PRA PS1/26 Art. 136-138, 121
- **P2.48** [ ] **NEW** — Pillar III CR8 RWEA flow only populates closing row; rows 1 (opening) and 2-8 (flow drivers) emit `None` (`pillar3/generator.py::_generate_cr8:690-718` lacks prior-period data). Sign convention: increases positive, decreases negative. Need optional `previous_period_results` on reporting boundary; compute seven flow drivers; signed Decimals. **Effort: M** | Ref: PRA PS1/26 Annex XXII §11
- **P2.49** [ ] **NEW** — CR9 column-`a` taxonomy missing F-IRB sub-classes 2.2 (Financial/large corp) and 2.4 (Other corp — non-SME), and A-IRB sub-class 1.3 plus seven retail sub-classes (RRE/CRE × SME/non-SME, QRRE, Other-SME, Other-non-SME) currently collapsed into `retail_mortgage`/`retail_qrre`/`retail_other`. **Supersedes P2.28**. Extend `CR9_FIRB_CLASSES`/`CR9_AIRB_CLASSES`. **Effort: M** | Ref: PRA PS1/26 Annex XXII pp.19-20
- **P2.9** [ ] OF 34.07 — IRB CCR template. CCR is out of scope; document as known gap or add placeholder. **Effort: S**
- **P4.20** [ ] C 08.02 PD bands use fixed buckets instead of firm-specific internal rating grades. **Effort: M**

### Tier 4 — Pillar III Disclosure Gaps

- **P3.5** [ ] **NEW** — CR9.1 (ECAI-based PD backtesting) has template definitions but no generator method, no bundle field, no stub. P3.2 marked [x] Complete but CR9.1 is not callable. **Effort: S**
- **P3.3** [~] Missing qualitative tables UKB CRD (SA qualitative, Art. 444(a-d)) and UKB CRE (IRB qualitative, Art. 452(a-f)). CR6 AIRB purchased receivables sub-row missing. CR5 rows 18-33 not detailed. **Effort: M**
- **P3.6** [ ] **NEW (Phase 9)** — CR5 / CR9 / OV1 disclosure gaps overlap with P2.25/P2.28/P2.29. Pillar III tables cannot faithfully reproduce Annex XX / XXII rows without: (a) pre-multiplier RW column, (b) equity transitional end-state RW column, (c) AIRB RE 4-way sub-class split, (d) FIRB financial/large-corp sub-rows, (e) OV1 equity sub-approach populations. **Effort: M** | Ref: PRA PS1/26 Annex XX §CR5/OV1, Annex XXII §CR9

### Tier 5 — Documentation & Consistency

- **P4.2** [~] Stale version numbers — `overview.md` says 0.1.37, `prd.md` says 0.1.28; current `pyproject.toml` is **0.2.6**. Plan header re-baselined; docs side still drifted. **Effort: S**
- **P4.3** [~] Stale `docs/plans/implementation-plan.md` — shows items as incomplete that are done. **Effort: S**
- **P4.4** [~] Stale PRD FR statuses. **Effort: S**
- **P4.8** [~] COREP template spec thin in `output-reporting.md` — detailed in `corep-reporting.md` feature doc. Cross-reference needed. **Effort: S**
- **P4.9** [~] Type checker inconsistency — docs disagree with CLAUDE.md (`mypy` vs `ty`). **Effort: S**
- **P4.10** [~] `model_permissions` not in architecture spec. **Effort: S**
- **P4.23** [ ] Stale test counts in `regulatory-compliance.md` (97 CRR / 116 B31; actual 169/212). **Effort: S**
- **P4.24** [ ] Stale NFR metrics in `nfr.md`: 1,844+ tests (actual 5,188); "6 stages" (actual 9 protocols); 8 namespaces (actual 2). **Effort: S**
- **P4.25** [ ] Stale acceptance test counts in `index.md`. **Effort: S**
- **P4.26** [ ] Stale PD floor values in `irb/formulas.py` docstring (retail mortgage 0.05% → 0.10%; QRRE transactor 0.03% → 0.05%). Runtime correct. **Effort: S**
- **P4.27** [ ] Stale PD floor values in `.claude/skills/basel31/references/irb-changes.md`. **Effort: S**
- **P4.28** [ ] Stale C 07.00 column count in `reporting/corep/templates.py` docstring (says 24/22, actual 27/27). **Effort: S**
- **P4.29** [ ] Stale "Not Yet Implemented" in `docs/user-guide/regulatory/basel31.md:186-187, 196` (currency mismatch, defaulted — both done). **Effort: S**
- **P4.30** [ ] Regulatory compliance matrix missing groups B31-K/L/M, CRR-J/D2. **Effort: S**
- **P4.31** [ ] Skill ref `slotting-changes.md` shows BCBS pre-op PF weights (80/100/120/350%) as PRA B31; PRA has no separate pre-op table. **Effort: S**
- **P4.32** [ ] Skill reference files (`.claude/skills/.../references/*.md`) need systematic BCBS-vs-PRA audit. **Effort: S**
- **P4.33** [ ] Stale BCBS output floor in docstrings: `comparison.py:18`, `bundles.py:489`, `ui/marimo/comparison_app.py:14-15` say "50% (2027) to 72.5% (2032+)". Runtime correct. **Effort: S**
- **P4.47** [ ] Informational: PS1/26 output-floor transitional is 3 years (60/65/70% 2027-2029 per Art. 92(5)); 2030+ → Art. 92(2A) 72.5%. Audit any cite of Art. 92(5)(d) (doesn't exist). **Effort: S**
- **P4.48** [ ] Covered bond "Art. 161(1B)" comments at `irb/firb_lgd.py:256,263,698,717,776,804` — article doesn't exist; correct ref Art. 161(1)(d). 11.25% value correct. **Effort: S**
- **P4.49** [ ] CCF docstrings at `irb/ccf.py:7,132,150,164,189` cite Art. 166(9); correct ref Art. 166(8)(b). **Effort: S**
- **P4.51** [ ] `ExposureClass` docstring typos at `domain/enums.py:52,76,91`: `HIGH_RISK` Art. 112(l)→(k); `INSTITUTION` (d)→(f). **Effort: S**
- **P4.52** [ ] `ciu_holdings` not in `docs/specifications/architecture.md` data-model section. **Effort: S**
- **P4.53** [ ] Undocumented CalculationConfig fields: `PostModelAdjustmentConfig`, `collect_engine`, `spill_dir`. **Effort: S**
- **P4.54** [ ] fastexcel vs xlsxwriter inconsistency between `overview.md` and `output-reporting.md`. **Effort: S**
- **P4.55** [ ] Document new B3.1 sovereign/institution PD floors (pairs with P2.36) in `firb-calculation.md`/`airb-calculation.md`. **Effort: S**

### Tier 6 — Code Quality

- **P6.15** [~] 3 missing schema fields — see Tier 1 above.
- **P6.16** [ ] **NEW (Phase 9)** — `approach_applied="EQUITY"` uppercase while all other approaches are lowercase. `engine/aggregator/_equity_prep.py:23`. Breaks `FLOOR_ELIGIBLE_APPROACHES` set-membership and any group-by comparison. **Effort: S**
- **P6.17** [ ] **NEW (Phase 9)** — Pre-floor `rwa_final` naming collision. `engine/pipeline.py:487-490`. Consumers reading `sa_results` / `irb_results` see pre-floor values under the label `rwa_final`, creating ambiguity against the post-floor `rwa_final` on the aggregated bundle. **Effort: S**
- **P6.18** [ ] **NEW (Phase 9)** — Loader `_load_file_optional` swallows all exceptions. `engine/loader.py:232-234`. Bare `except Exception` silently turns a corrupt optional file into "absent". Replace with narrow `(FileNotFoundError,)` + logged `CalculationError`. **Effort: S**
- **P6.19** [ ] **NEW (Phase 9)** — `DataSourceRegistry` missing `ciu_holdings` entry. `config/data_sources.py:44-141`. Registry-driven loading silently drops CIU look-through data. **Effort: S**
- **P6.20** [ ] **NEW (Phase 9)** — `CreditRiskCalc.base_currency` never forwarded. `api/service.py:76-86, 165-182`. User setting a non-GBP base currency is a silent no-op. **Effort: S**
- **P6.21** [ ] **NEW (Phase 9)** — `_compute_portfolio_waterfall` eagerly collects mid-pipeline. `engine/comparison.py:754-763, 387`. Breaks the LazyFrame-first contract. **Effort: S**
- **P6.22** [ ] **NEW (Phase 9)** — `CapitalImpactAnalyzer` supporting-factor attribution divides by 1.06 for CRR IRB. `engine/comparison.py:693-698`. Under-attributes by ~6% (diagnostic only, not regulatory RWA). **Effort: S**
- **P6.23** [ ] **NEW (Phase 9)** — `_TRANSITIONAL_REPORTING_DATES` hardcoded to mid-year. `engine/comparison.py:231-236`. Uses `date(YYYY, 6, 30)` but PRA effective dates are 1 Jan. **Effort: S** | Ref: PRA PS1/26 Art. 92(5)
- **P6.24** [ ] **NEW** — `LazyFrameResult` mutability across stage boundaries. `src/rwa_calc/contracts/errors.py:86`. Not `frozen=True`; exposes `add_error`/`add_errors` mutation methods. Contradicts immutable-bundle architecture principle. **Effort: S**
- **P6.25** [ ] **NEW (D3.52 doc-writer, P19-03 closure)** — Factory-method asymmetry for CRM/A-IRB collateral knobs. `CalculationConfig.crr()` exposes `crm_collateral_method` but NOT `airb_collateral_method`; `CalculationConfig.basel_3_1()` exposes both. Add explicit framework-appropriate defaults to both factory signatures. **Effort: S** | Ref: `src/rwa_calc/contracts/config.py:838-906,953-971`
- **P6.26** [ ] **NEW (curator audit 2026-05-03)** — Lone source-tree TODO marker at `engine/hierarchy.py:2034`: `# TODO(qrre-coupling): also set in _undrawn_select_expressions; consolidate.`. Refactor the two sites to share a single helper, or mark TODO closed if duplication is intentional. **Effort: S** | Ref: `src/rwa_calc/engine/hierarchy.py:2030-2050`
- **P6.27** [ ] **NEW (batch 20260508-0020 surfacing)** — Pre-existing failures in `tests/unit/crm/test_collateral_sequential_fill.py`: `TestSequentialFillAllCategories::test_all_five_categories_b31` (got 0.15015 vs 0.1595 expected) and `TestPerTypeMinThreshold::test_covered_bonds_no_threshold` (got 0.34595 vs 0.3655 expected). Both reproduce on the unmodified main `src/` per engine-implementer attestation. Numerical drift on multi-collateral sequential-fill blended LGD calculation. **Effort: S** | Ref: `src/rwa_calc/engine/crm/collateral.py`, `tests/unit/crm/test_collateral_sequential_fill.py:733,990`

**Note on P6.16–P6.23 ID collision:** The Tier 6 bullet entries P6.16–P6.23 added in Phase 9 conflict with pre-existing detailed `### P6.16` through `### P6.21` subsections (now removed from this file along with all detailed sections). The Phase 9 entries are distinct new items but reuse the completed IDs. Documented here for a future renumbering pass.

### Tier 7 — Future / v2.0 (Not Yet Planned)

- **P7.1** [ ] Stress testing integration (M4.3)
- **P7.2** [ ] Portfolio-level concentration metrics (M4.4)
- **P7.3** [ ] REST API (M4.5)
- **P7.4** [ ] Additional exposure classes: securitisation, CIU beyond fallback, purchased receivables, dilution risk
- **P7.5** [ ] **NEW** — Additional CRM methods not in scope: Art. 217 basket credit derivatives, Art. 219 on-balance-sheet netting, Art. 214 counter-guarantees by sovereigns, Art. 215(2) mutual guarantee schemes, Art. 222(5) derivative cash collateral 0%, Art. 230(3) UK IRB 50% RW property option, Art. 197(4) unrated bond eligibility route
- **P7.5** [ ] **NEW** — Art. 150(1A) materiality/immateriality thresholds for IRB firms using SA for immaterial classes. Currently only in COREP templates, not in the engine. **Effort: M**
- **P7.6** [ ] **NEW** — Art. 147B roll-out class tracking in the classification engine (currently only in COREP reporting). **Effort: M**
- **P7.7** [ ] **UPGRADED TO P1.105** — moved to Tier 1.
- **P7.8** [ ] **NEW** — CRR Art. 121(4) trade finance preferential RW for unrated institutions (CRR-only, sunsets 31 Dec 2026). Flat 50% (≤1y) / 20% (≤3m), independent of sovereign CQS ladder. CRR SA routes all unrated institutions through Art. 121(1); CQS 2-6 over-weighted. Add `is_trade_finance` Bool, `CRR_ART_121_4_*_RW` constants, gate in CRR institution branch. **Effort: S** | Ref: CRR Art. 121(4); 162(3); 4(1)(80)

---

## Detailed Sections (Long-Form)

The bullet list above is the canonical work-queue. The two items below have substantive sub-issue structure that doesn't compress cleanly into a single bullet, so they are kept in long-form.

### P1.9 Output Floor — OF-ADJ, portfolio-level application, U-TREA/S-TREA

- **Status:** [~] Partial — sub-items (a) OF-ADJ, (b) portfolio-level, (d) skip-transitional all FIXED; only (c) remains.
- **Remaining (c):** U-TREA/S-TREA COREP export. `OutputFloorSummary` is on `AggregatedResultBundle`, but full `OF 02.01` COREP template wiring (4-column comparison) not yet done — tracked under P2.1.
- **File:Line:** `engine/aggregator/_floor.py`, `_schemas.py`, `aggregator.py`, `contracts/bundles.py`
- **Spec ref:** `docs/specifications/output-reporting.md`, PRA PS1/26 Art. 92(2A)/(3A)/(5)
- **Tests:** 80 unit tests across `test_portfolio_level_floor.py`, `test_of_adj.py`, `test_output_floor_skip_transitional.py`.

### P2.1 COREP template rework — structure alignment

- **Status:** [~] Needs rework
- **Impact:** Current COREP generator (`reporting/corep/generator.py`) uses simplified column sets and one-row-per-class structure. Only C 07.00, C 08.01, C 08.02 (and OF variants) are implemented. Full-width CRR/B31 column definitions exist in `templates.py` (lines 1-651) but generator uses backward-compatibility aliases. Specific sub-gaps:
  - C 08.01 col `0120` ("Of which: off balance sheet") still null — needs off-BS EAD pipeline column
  - B31 OF 08.02 missing columns `0001` and `0101-0105` (per-grade CCF breakdown)
  - B31 C 08.01 off-BS CCF sub-rows `0031-0035` always null
  - C 07.00 B31 CIU sub-rows `0284/0285` defined but never populated by generator
  - B31 slotting FCCM cols `0101-0104` in C 08.01 still null — pipeline FCCM for slotting not yet wired
  - **From PDF comparison:** OF 07.00 missing cols 0230/0235/0240 (ECAI breakdown). OF 09.02 missing cols. OF 08.01 missing cols 0254/0265/0282; col 0280 renamed. OF 02.00 needs rows 0034/0035/0036 (floor indicator/multiplier/OF-ADJ). OF 08.06 col 0070 removed in B3.1; col 0031 is a deduction. OF 08.07 cols 0160-0180 consolidated-basis-only. OF 09.01 missing col 0061.
- **File:Line:** `reporting/corep/generator.py`, `reporting/corep/templates.py`
- **Fix:** Migrate generator to use full template definitions. Rework row/column logic. Add missing pipeline columns for equity transitional and currency mismatch reporting. Remove dead alias objects.
- **Tests needed:** Rewrite COREP tests (~250 tests in `tests/unit/test_corep.py`).

---

## Audit History

For per-pass detail see git history (`git log -p IMPLEMENTATION_PLAN.md`) and `docs/appendix/changelog.md`.

| Pass | Date | New items | Notes |
|------|------|-----------|-------|
| Phase 5 | early 2026 | 7 P1, 1 P4 | CRR 1.06 retail (P1.108 disputed); guarantee maturity mismatch (P1.109) |
| Phase 6 | 2026-04-10 | 6 P1, 6 P4, 1 P5 | B31 covered bond CQS 2/6 RW bug (P1.113) |
| Phase 7 | 2026-04-10 | 7 P1, 4 P2 | FCCM HE for SFTs upgraded P2.13→P1.123; PSA legal-clarification flag on P1.108 |
| Phase 8 | 2026-04-10 | 7 P1, 3 P2, 5 spec corrections | Output floor binding aggregator gap (P1.130); Opus deep-analysis on SA / IRB / equity |
| Phase 9 | 2026-04-18 | 13 P1, 11 P2, 1 P3, 1 P4, 8 P6 | Equity transitional ladder (P1.137-139); ADC classification (P1.140); CR8 / CR9 / OV1 disclosure gaps |
| Curator | 2026-05-03 | — | Closed silent fixes (P1.99/P1.121/P1.132); closed-claim-invalid (P1.131, P1.94(c)); file:line drift survey |

---

## Completed Items (Reference)

Closure summaries pruned from this file 2026-05-03. Closure rationale and per-version detail are preserved in git history (`git log -p IMPLEMENTATION_PLAN.md`) and `docs/appendix/changelog.md`. Recently closed: P1.97, P1.98, P1.99, P1.106, P1.107, P1.112, P1.114, P1.117, P1.121, P1.124, P1.125, P1.126, P1.131 (closed-claim-invalid), P1.132 (silent fix), P1.144, P1.156, P1.158, P1.169, P1.182, P1.186 (now re-opened as partial — see Tier 1), P1.187.
