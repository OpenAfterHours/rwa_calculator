# Regulatory Compliance Audit & Rectification Plan — CRR / PS1-26 Articles 111–168, 192–241

**Scope:** Standardised Approach (Art. 111–134), ECAI use (Art. 135–141), IRB approach (Art. 142–168), and Credit Risk Mitigation (Art. 192–241) — audited against **both** live regimes: UK CRR (in force to 31 Dec 2026) and PRA PS1/26 / Basel 3.1 (effective 1 Jan 2027).
**Date:** 2026-07-07
**Method:** 14 parallel article-group auditors (regulation ⇄ code cross-reference via the `crr`/`basel31` skills, the pack citations, and `docs/assets/*.pdf`), then two-lens adversarial verification (regulation + code) of every candidate finding. 174 agent-runs total.
**Status of P-codes below:** *proposed* — `plan-curator` owns `IMPLEMENTATION_PLAN.md`; these IDs (P1.216–P1.296) are suggested and do not yet exist in the work queue.

---

## 1. Headline

The engine is **substantially compliant and largely conservative** across the whole range: all in-scope numeric pack values (risk weights, CCFs, haircuts, LGD floors, correlations, LTV bands, transitional schedules) were checked against the regulation text and are correct for both regimes. The PS1/26 (Basel 3.1) arm is the more complete of the two; most residual defects are on the **live CRR arm** or in **CRM edge mechanics**.

The audit produced **81 newly-confirmed findings** (adversarially verified), plus **48 gaps that are already tracked** in the work queue, and **dismissed 3** on verification.

| Effective severity | New findings | Meaning |
|---|---:|---|
| 🔴 **High** | **7** | Likely capital **understatement** on realistic portfolios |
| 🟠 **Medium** | **41** | Edge-case misstatement or non-conservative shortcut |
| 🟡 **Low** | **33** | Conservative-only deviation, audit-trail, docstring, or spec |
| **Total new** | **81** | |
| Already tracked | 48 | Mapped to existing P-codes / plan docs (§6) |
| Refuted | 3 | Investigated & dismissed (§7) |

> **Direction of error matters.** The seven high-severity items and most mediums cause **under-statement** of RWA (a prudential exposure). A handful (e.g. CRR defaulted RE flat-100, slotting guarantees ignored) are **over-statements** — conservative, but still corrections. Each item below states the direction.

### The seven high-severity findings

| P-code | Article | Regime | One-line |
|---|---|---|---|
| **P1.216** | Art. 131 | CRR | Short-term-rated bank/corporate paper never routed through Table 7 → ST-CQS2/3 under-weighted (e.g. 20% vs 50%). |
| **P1.217** | Art. 111 / Annex I | CRR | "Other commitments" 50%/20% CCF split keyed on **remaining** maturity, not **original** → every seasoned >1yr facility drops to 20% CCF in its final year. |
| **P1.218** | Art. 235/236 | both | Guarantee coverage fraction computed on **post-CCF** EAD, not the CCF=100% basis → over-recognises cover on undrawn commitments (≈47% RWA under-statement in the worked case). |
| **P1.219** | Art. 239(3) | both | Guarantee maturity-mismatch `t` uses **original** term, not residual → seasoned guarantees escape the (t−0.25)/(T−0.25) haircut. |
| **P1.220** | Art. 147/147A | B31 | Institution-typed RGLAs/PSEs stay IRB-modellable under Basel 3.1, where PS1/26 mandates the SA quasi-sovereign class → modelled RW below SA floor. |
| **P1.221** | Art. 159 | both | IRB EL-vs-provision netting done **per-row then summed** instead of pool-aggregate → over-states both CET1 shortfall deduction and T2 excess credit. |
| **P1.222** | Art. 115(5) | both | Flat-20% domestic-currency RGLA weight over-extended from UK to all EU member states → EU sub-sovereigns under-weighted (20% vs up to 150%). |

---

## 2. Coverage matrix

179 article-level coverage entries were recorded (one per article/sub-article group). Rollup:

| Status | Count | |
|---|---:|---|
| Compliant | 65 | Implemented and value-correct for both regimes |
| Partial | 76 | Core path correct; a sub-rule or regime arm is missing (most findings live here) |
| Gap / not-implemented | 22 | Requirement not addressed (many are permission-gated or edge populations) |
| Not applicable | 16 | Supervisory-process / governance articles with no calculator surface |

### Per-article-group heat map

| Group (articles) | Compliant | Partial | Gap / not-impl | N/A | Worst new finding |
|---|:--:|:--:|:--:|:--:|---|
| SA exposure value (111–113) | 7 | 3 | 1 | – | 🔴 P1.217 CCF original-maturity |
| SA sovereigns (114–118) | 7 | 3 | 6 | 3 | 🔴 P1.222 EU RGLA 20% |
| SA inst/corp (119–122) | 11 | 3 | 5 | 1 | 🟠 P1.255 unrated-corp higher-of-sovereign |
| SA retail/RE (123–126) | 14 | 3 | – | – | 🟠 P1.263 CRR Art. 126 inverted gate |
| SA other classes (127–134) | 3 | 6 | 1 | – | 🟠 P1.258 CIU third-party ×1.2 |
| SA ECAI (135–141) | 1 | 4 | 2 | 1 | 🔴 P1.216 / 🟠 ST + currency + seniority |
| IRB scope (142–150) | 3 | 5 | – | 3 | 🔴 P1.220 RGLA/PSE FIRB under B31 |
| IRB RW (151–158) | 4 | 8 | – | – | 🟠 P1.242 LFSE 1.25× not derived |
| IRB EL/params (159–165) | – | 7 | – | 1 | 🔴 P1.221 EL pool netting |
| IRB EAD (166–168) | 5 | 5 | 1 | – | 🟠 P1.250 CRR A-IRB CCF fallback |
| CRM eligibility (192–204) | 3 | 9 | 1 | – | 🟠 third-party cash, guarantor eligibility |
| CRM requirements (205–217) | – | 6 | 2 | 5 | 🟠 P1.228 double-default unreachable |
| CRM funded calc (218–232) | 5 | 7 | 1 | 2 | 🟠 bond mis-bucketing, netting mismatch |
| CRM unfunded/MM (233–241) | 2 | 7 | 2 | – | 🔴 P1.218 / P1.219 guarantee mechanics |

---

## 3. Rectification strategy — phasing

Findings cluster into **11 workstreams** (§5). Recommended sequencing balances capital impact, shared-file contention, and the CRR sunset (31 Dec 2026 — CRR-only fixes have an 18-month useful life, so they are worth doing but should not block B31 work).

**Phase 1 — Capital-correctness, high severity (7 items, ~2–3 sprints).**
The seven 🔴 items. Each is a self-contained, well-localised change with a clear hand-calc and (mostly) an existing mis-pinned test to invert. Do these first; several share files with their workstream siblings, so pull the adjacent mediums in with them.
→ P1.216 (WS1), P1.222 (WS6), P1.218 + P1.219 (WS2), P1.220 + P1.221 (WS5), P1.217 (WS10).

**Phase 2 — Capital-correctness, medium severity (41 items, grouped by workstream).**
Run workstream-by-workstream so shared files (`risk_weights.py`, `guarantees.py`, `haircuts.py`, `ccf.py`) are touched once per stream. Priority order: **WS2** (guarantees) → **WS1** (CRR short-term ECAI) → **WS3/WS4** (collateral & netting) → **WS5** (IRB params) → **WS6/WS7/WS8/WS9** (SA classes).

**Phase 3 — Conservative-only, audit-trail, docstrings & spec (33 items).**
Low-risk cleanup. Batch the pure docs/citation cluster (WS11 + the low docstring/spec items) into a single housekeeping PR. The conservative-only calc deviations (e.g. CRR defaulted-RE flat-100, unconditional 1-year guarantee filter) are correctness fixes but not prudential exposures — schedule after Phase 2.

**Schema-change items** (need an input column before the engine change lands): P1.220 relies on entity-type sets only (no schema change); but P1.229 (funding currency), the third-party-cash cluster (WS4), guarantor-eligibility (P1.227), rating-currency (P1.261) and implicit-support (P1.259) all add optional columns to `COLLATERAL_SCHEMA` / `RATINGS_SCHEMA` / `COUNTERPARTY_SCHEMA`. Land the schema additions (nullable, backward-compatible, conservative default) in a dedicated enablement PR ahead of the consuming logic — mirrors the P2.40a→P2.40b split already used in the plan.

**Guardrails (from `IMPLEMENTATION_PLAN.md` do-not-do register):** no bulk golden regeneration; never fill Float/String nulls to 0.0 (several fixes below *tighten* an anti-conservative null default — the correct direction); items touching the hard-excluded shared files (`aggregator.py`, `pipeline.py`, `registry.py`, `orchestrator.py`, `contracts/*`) run single-stream. P1.221 (WS5) writes to `engine/aggregator/_el_summary.py` — treat as single-stream.

---

## 4. TDD approach per item

Each item follows the project loop: **(1)** write/adjust a failing acceptance or unit test encoding the regulator's hand-calc (many findings name an existing test that is pinned the *wrong* way — invert it); **(2)** minimum engine change; **(3)** green validation gate (`arch_check`, `ruff`, `ty`, contracts) + `watchfire` citation check; **(4)** changelog + docstring + `@cites` update. Because several fixes invert a currently-passing test, expect a short list of golden/acceptance deltas per workstream — review them as regulatory evidence, not regressions.

---

## 5. Findings by workstream

### WS1 — SA short-term ECAI rating treatment (CRR Table 7 + obligor contamination)
_6 findings (1 high, 4 medium, 1 low)_

- **P1.216** [🔴 HIGH] · **CRR Art. 131** (crr) · effort M
  - _Gap:_ Exposures to institutions and corporates with a dedicated short-term ECAI credit assessment shall be risk-weighted per Table 7: CQS1 20%, CQS2 50%, CQS3 100%, CQS4-6 150% (UK CRR Art. 131, verified in docs/assets/crr.pdf p.129 — still in force until 31 Dec 2026).
  - _Evidence:_ engine/stages/hierarchy/enrich.py:158-240 (apply_short_term_rating_override) runs under BOTH regimes: it overwrites `cqs` with the short-term rating's CQS and sets `has_short_term_ecai=True`. Only the B31 ladder consults that flag (risk_weights.py:641-650 Table 4A institutions, 692-719 Table 6A corporates). The CRR ladder (_apply_crr_risk_weight_overrides, risk_weights.py:1202-1368, and _crr_append_institution_maturity_branches :805-832) never reads has_short_term_ecai, so a short-term-rated exposure is routed thro
  - _Fix:_ Add a cited pack table `crr_short_term_ecai_risk_weights` (CRR Art. 131 Table 7 — numerically identical to the existing b31_corporate_short_term_ecai table: 20/50/100/150/150/150) and insert `has_short_term_ecai`-gated branches ahead of the maturity-based Table 4 branch in _crr_append_institution_maturity_branches plus a new corporate branch in the CRR ladder, mirroring the B31 Table 4A/6A appende
  - _Files:_ `risk_weights.py`, `enrich.py`, `crr.py`
- **P1.223** [🟠 MED] · **CRR Art. 120(3)(c) / PS1/26 Art. 120(3)(c)** (both) · effort S
  - _Gap:_ If a short-term issue assessment maps to a LESS favourable risk weight than the general preferential short-term treatment, the general preferential treatment must not be used and ALL unrated short-term claims on that obligor must be assigned the short-term assessment's risk weight (crr.pdf p.118; ps126app1.pdf p.41).
  - _Evidence:_ The short-term override is strictly per-exposure: enrich.py:160-240 joins short-term ratings by (scope_type, scope_id) to a single exposure, and the SA branches (risk_weights.py:641-650 B31; none in CRR) key only on the row's own has_short_term_ecai flag. There is no obligor-level propagation, so when a bank has one issue rated ST-CQS3 (100% Table 4A) its OTHER short-term unrated exposures still receive the Table 4/5A preferential 20-50% — an understatement in exactly the scenario para (3)(c) targets. Requires an o
  - _Fix:_ In apply_short_term_rating_override, compute per-counterparty the worst short-term-assessment RW, compare against the general preferential RW, and where less favourable stamp an obligor-level flag/RW that the SA short-term branches use in place of Table 4/5A for all short-term exposures to that counterparty.
  - _Files:_ `enrich.py`, `risk_weights.py`
- **P1.224** [🟠 MED] · **CRR Art. 120(3) (with Art. 131)** (crr) · effort M
  - _Gap:_ Where a short-term issue-specific assessment exists, that exposure must take the Art. 131 short-term mapping (CQS1 20%, CQS2 50%, CQS3 100%, CQS4-6 150%) per the Art. 120(3)(b)/(c) interaction rules — it does not get the Table 4 general preferential treatment (crr.pdf p.118).
  - _Evidence:_ engine/stages/hierarchy/enrich.py:229-238 (apply_short_term_rating_override) splices the short-term rating's CQS into the exposure's `cqs` and sets has_short_term_ecai=True for BOTH regimes, but only the B31 chain consumes the flag (risk_weights.py:641-650 Table 4A, :711-719 Table 6A). The CRR institution chain (risk_weights.py:805-832) routes a <=3m exposure whose cqs came from a short-term rating through Table 4: ST-CQS2 gets 20% instead of Art. 131's 50%, ST-CQS3 gets 20% instead of 100% — understatements of up 
  - _Fix:_ Add a CRR branch mirroring the B31 Table 4A/6A branches: when has_short_term_ecai fires, map cqs through the Art. 131 Table (20/50/100/150) for institutions and corporates ahead of the Table 4 short-term branch.
  - _Files:_ `enrich.py`, `risk_weights.py`
- **P1.225** [🟠 MED] · **CRR Art. 140(2) / PS1/26 Art. 140(2)** (both) · effort M
  - _Gap:_ If any short-term rated facility of an obligor attracts 150%, ALL unrated unsecured exposures to that obligor (short- or long-term) must also be assigned 150% (Art. 140(2)(a)); if a short-term rated facility attracts 50%, no unrated short-term exposure to that obligor may be weighted below 100% (Art. 140(2)(b)). Identical text in both regimes (CRE21.17-21.18).
  - _Evidence:_ apply_short_term_rating_override (engine/stages/hierarchy/enrich.py:160-240) affects only the exposure the rating is scoped to; no code anywhere in engine/ implements the obligor-level spillover (grep for the 150%-contamination / unrated-floor logic returns nothing beyond the @cites decorator at enrich.py:159). An obligor with a ST rating mapping to 150% (e.g. B31 Table 4A CQS4) and other unrated unsecured exposures leaves those at their class default (e.g. unrated corporate 100%) — understated by 50pp.
  - _Fix:_ After the per-exposure ST override, compute per-counterparty aggregates (any ST rating whose table RW is 150%; any ST rating at 50%) and broadcast two flags onto the unified frame; in the SA stage, force 150% on unrated unsecured rows of contaminated obligors and floor unrated short-term rows at 100% for 50%-flagged obligors, in both regime arms.
  - _Files:_ `enrich.py`, `risk_weights.py`
- **P1.226** [🟠 MED] · **CRR Art. 140(1) (with Art. 131 Table 7)** (crr) · effort M
  - _Gap:_ Under CRR, a short-term credit assessment applies to the specific short-term item and that item is risk-weighted per Art. 131 Table 7 (CQS1 20%, CQS2 50%, CQS3 100%, CQS4-6 150%) — not per the long-term institution/corporate tables.
  - _Evidence:_ The short-term rating override is regime-ungated: engine/stages/hierarchy/enrich.py:160-240 overwrites cqs with the short-term rating's CQS and sets has_short_term_ecai for any run, but has_short_term_ecai is only ever read by the two B31 helpers (engine/sa/risk_weights.py:627 and :710). The CRR override chain (_apply_crr_risk_weight_overrides, risk_weights.py:1202-1368, and _crr_append_institution_maturity_branches:805-832) has no Table 7 branch, so a CRR ST-rated institution exposure with ST CQS3 and residual <=3
  - _Fix:_ Add a CRR Art. 131 Table 7 lookup (new pack LookupTable in packs/crr.py: 1->20%, 2->50%, 3->100%, 4-6->150%) and a has_short_term_ecai-gated branch for institutions AND corporates at the top of the CRR institution/corporate branches, mirroring the B31 Table 4A/6A pattern; alternatively feature-gate the enrich override off under CRR until Table 7 exists.
  - _Files:_ `enrich.py`, `risk_weights.py`
- **P1.264** [🟡 LOW] · **CRR Art. 140(1) / PS1/26 Art. 140(1)** (both) · effort S
  - _Gap:_ Short-term credit assessments may only be used for short-term asset and off-balance-sheet items constituting exposures to institutions and corporates.
  - _Evidence:_ apply_short_term_rating_override (engine/stages/hierarchy/enrich.py:229-240) overwrites cqs for ANY scope-matched exposure regardless of exposure class; the B31 Table 4A/6A branches are correctly class-gated (risk_weights.py:641, 711), but a mis-scoped ST rating on e.g. a sovereign loan still replaces that row's long-term CQS, which then drives the Art. 114 sovereign table. There is no DQ validation rejecting ST ratings scoped to non-institution/non-corporate obligors, and the <=3m maturity precondition is delegate
  - _Fix:_ Apply the cqs override only when the matched exposure's counterparty class is institution or corporate (or emit a DQ error, e.g. DQ-RT-ST3, for out-of-class short-term rating rows) and optionally cross-check original_maturity_years <= 0.25 at the loader edge.
  - _Files:_ `enrich.py`, `validation.py`

### WS2 — Unfunded credit protection (guarantee) mechanics
_8 findings (2 high, 6 medium, 0 low)_

- **P1.218** [🔴 HIGH] · **Art. 235(1)/236(3) CRR; Art. 235(1)(a)/236(1)(a) PS1/26** (both) · effort M
  - _Gap:_ For unfunded protection the covered part Eg = min(GA, E) must be determined with E measured at 100% of an off-balance-sheet item's value ('prior to the application of any applicable conversion factors' — PS1/26 Art. 235(1)(a), ps126app1.pdf p.213; CRR Art. 235(1) and Art. 236(3) impose the same CCF=100% override), with conversion factors re-applied to covered and uncovered parts afterwards.
  - _Evidence:_ The guarantee split caps and pro-rates coverage against the post-CCF EAD: src/rwa_calc/engine/crm/guarantees.py:647-668 (_join_multi_guarantees computes _scale = min(1, ead_after_collateral/_total_coverage) and _guar_ratio = _effective_amount/ead_after_collateral), :916 (percentage coverage = percentage_covered x ead_after_collateral) and :939-944 (pro-rata basis ead_after_collateral). ead_after_collateral is post-CCF by construction — src/rwa_calc/engine/crm/collateral.py:1079-1089 sets it to E* x effective_ccf fo
  - _Fix:_ Compute the guarantee coverage fraction against ead_for_crm (the CCF=100% basis already on the frame): cap total coverage at ead_for_crm, derive _guar_ratio = _effective_amount/ead_for_crm, then size guarantor/remainder sub-rows as ratio x ead_after_collateral (equal-CCF case) or re-apply the per-part CCFs as _apply_cross_approach_ccf already does for the IRB/SA-guarantor subset. Base percentage_c
  - _Files:_ `guarantees.py`, `collateral.py`, `credit-risk-mitigation.md`
- **P1.219** [🔴 HIGH] · **Art. 239(3) with Art. 238(1) CRR; PS1/26 Art. 239(3)** (both) · effort M
  - _Gap:_ In GA = G* x (t-0.25)/(T-0.25), t is 'the number of years REMAINING to the maturity date of the credit protection calculated in accordance with Article 238' (crr.pdf p.233; identical in PS1/26, ps126app1.pdf p.219). Original contract term is only relevant to the separate Art. 237(2)(a) >=1y eligibility gate.
  - _Evidence:_ src/rwa_calc/engine/crm/guarantees.py:1330-1336 (_apply_maturity_mismatch_to_guarantees): when both columns exist, t_raw = when(original_maturity_years.is_not_null()).then(original_maturity_years).otherwise(t_from_date) — i.e. the ORIGINAL term wins over the residual derived from maturity_date. data/schemas.py:588-592 documents original_maturity_years as the original contract term (needed for the Art. 237(2)(a) gate at guarantees.py:196-200), so any dataset that populates it correctly for the 1y gate silently overs
  - _Fix:_ Invert the preference: t = residual from maturity_date when present; fall back to original_maturity_years only when no maturity_date exists (and document that fallback as assuming an unseasoned guarantee). Keep original_maturity_years solely for the Art. 237(2)(a) gate. Re-pin the P1.200 test with an explicit guarantee maturity_date.
  - _Files:_ `guarantees.py`, `schemas.py`, `test_p1_200_b31_guarantee_maturity_mismatch.py`
- **P1.227** [🟠 MED] · **CRR Art. 201(1)(g)/(2); PS1/26 Art. 201(1)(g)/(2) (via CRR Art. 194(5) / PS1/26 Art. 194(6)(c))** (both) · effort M
  - _Gap:_ Unfunded credit protection may only be recognised where the provider is on the Art. 201 eligible list. Corporates (incl. parents/subsidiaries/affiliates) are eligible only if they have an ECAI credit assessment, or — for IRB/PSM exposures only — an internal rating (CRR Art. 201(1)(g)(i)-(ii), 201(2); PS1/26 Art. 201(1)(g), 201(2)).
  - _Evidence:_ engine/crm/guarantees.py::apply_guarantees (lines 92-166) and _prepare_guarantees (169-220) apply FX/restructuring/maturity haircuts and split, but contain no provider-eligibility filter of any kind — the only drop is the Art. 237(2) original-maturity<1y filter (line 200). Guarantor pricing then proceeds for ANY entity: engine/sa/guarantor_rw.py::build_corporate_guarantor_rw_expr (523-570) resolves a completely unrated corporate guarantor to the unrated corporate RW (CRR 100% via _CORPORATE_RW[CQS.UNRATED] line 560
  - _Fix:_ In _prepare_guarantees (or a new eligibility step), join guarantor entity_type + external CQS + internal_pd and drop (with a CRM warning error code) guarantee rows whose provider is a corporate with no ECAI rating and — unless the covered exposure is on the PSM path — no internal rating. Keep sovereigns/RGLA/PSE/MDB/IO/institutions/QCCPs unconditionally eligible per Art. 201(1)(a)-(f),(h).
  - _Files:_ `guarantees.py`, `guarantor_rw.py`
- **P1.228** [🟠 MED] · **CRR Art. 217 / Art. 153(3)** (crr) · effort M
  - _Gap:_ Credit protection meeting the Art. 202/217 requirements qualifies for the Art. 153(3) double-default formula K_dd = K_0 x (0.15 + 160 x PD_pp); when the firm elects DD it should actually be applied to eligible exposures.
  - _Evidence:_ src/rwa_calc/engine/irb/guarantee.py:682-694 — `rw_dd = risk_weight_irb_original * dd_multiplier`; line 685 `rw_dd_floored = pl.max_horizontal(rw_dd, pl.col("guarantor_rw"))`; line 691 applies DD only `pl.when(_is_dd_eligible & (rw_dd_floored < pl.col("guarantor_rw")))`. Since max(rw_dd, guarantor_rw) >= guarantor_rw by construction, the strict `<` gate is always False: the DD RW never overrides substitution, `_is_dd_applied` (lines 707-710) is always False, and guarantee_status can never be "DOUBLE_DEFAULT". Meanw
  - _Fix:_ Compare the unfloored DD RW against substitution: apply DD when `_is_dd_eligible & (rw_dd < guarantor_rw)` and then use rw_dd (CRR Art. 153(3) has no direct-to-guarantor floor; if the Basel II para 284 floor is intentionally retained, gate on `rw_dd < guarantor_rw` and emit `rw_dd_floored`, which equals guarantor_rw only at the boundary). Also make `double_default_unfunded_protection` and `is_doub
  - _Files:_ `guarantee.py`, `generator.py`, `test_irb_double_default.py`
- **P1.229** [🟠 MED] · **Art. 235(3) CRR; PS1/26 Art. 235(3)** (both) · effort M
  - _Gap:_ The Art. 114(4)/(7) 0% extension to centrally-guaranteed exposures requires BOTH that the guarantee is denominated in the relevant domestic currency AND that 'the exposure is funded in that currency' (crr.pdf p.231; ps126app1.pdf pp.214-215).
  - _Evidence:_ src/rwa_calc/engine/crm/guarantees.py:361-389 (_build_domestic_cgcb_flag) and engine/eu_sovereign.py:83-111 test only guarantor-country vs guarantee-currency; the exposure's own denomination/funding currency is used merely as a fallback when guarantee_currency is missing, never as a second conjunctive limb. A USD-funded loan guaranteed in EUR by an EU sovereign with non-zero CQS RW (e.g. CQS3 at 50%) gets 0% on the covered part where the regulation denies the extension (RWA under-statement). Edge population: FX-fun
  - _Fix:_ AND the existing test with denomination_currency_expr(exposure) == guarantee currency (as a proxy for funded-in-currency, or add an explicit funding-currency input), under both regimes.
  - _Files:_ `guarantees.py`, `eu_sovereign.py`, `guarantee.py`
- **P1.230** [🟠 MED] · **Art. 235 (PS1/26 RWSM for slotting; CRR Art. 236 via Art. 153(5))** (both) · effort M
  - _Gap:_ Unfunded protection on specialised-lending slotting exposures is recognisable — under PS1/26 the Art. 191A Part 3 decision tree routes SA and slotting exposures to the Risk-Weight Substitution Method (Art. 235); under CRR, slotting is an IRB sub-approach whose guarantees fall under Arts. 235/236.
  - _Evidence:_ engine/slotting/** contains zero references to guarantor_*, guaranteed_portion or is_guarantee_beneficial (grep confirmed); guarantee substitution exists only in engine/sa/rw_adjustments.py:219-283 and engine/irb/guarantee.py. A guaranteed slotting exposure therefore receives zero CRM benefit under both regimes (RWA over-statement / conservative), and per the project's own confirmed investigation the B31 unified pass additionally stamps slotting rows with a wrong pre_crm_risk_weight=1.0 audit value. Recorded in pro
  - _Fix:_ Extend the RWSM row-split consumption to the slotting branch: after slotting RW lookup, blend guarantor SA RW on the guaranteed_portion (reusing build_guarantor_rw_expr and the beneficial gate), and zero covered-part EL per PS1/26 Art. 235(1A); add a P-code to IMPLEMENTATION_PLAN.md.
  - _Files:_ `namespace.py`, `rw_adjustments.py`, `guarantees.py`
- **P1.231** [🟠 MED] · **Art. 237(1)/(2)(b) CRR; PS1/26 Art. 237(1)/(2)(b)** (both) · effort M
  - _Gap:_ Protection with residual maturity <3 months that is shorter than the exposure shall not be used (237(1)); under any mismatch, protection on an exposure subject to the Art. 162(3) one-day M floor shall not be used (237(2)(b)).
  - _Evidence:_ The guarantee path implements neither gate explicitly. (a) 237(2)(b): haircuts.py:718-748 gates collateral on exposure_has_one_day_maturity_floor, but _apply_maturity_mismatch_to_guarantees (guarantees.py:1267-1371) has no equivalent — a guarantee on a daily-margined SFT/repo exposure with any mismatch is still recognised (scaled, not zeroed). (b) 237(1): the 3-month rule is only effected implicitly by the 0.25 floor in the 239(3) scale; when the exposure's own residual T <= 0.25y both t_eff and exp_t_eff floor to 
  - _Fix:_ In _apply_maturity_mismatch_to_guarantees: join the exposure's one-day-floor flag and zero coverage on any mismatch; test raw t < 0.25 AND t < raw T explicitly (before flooring) and zero coverage; align null-T handling with the collateral 5y default.
  - _Files:_ `guarantees.py`, `haircuts.py`
- **P1.232** [🟠 MED] · **Art. 237(2)(a) CRR; PS1/26 Art. 237(2)(a)** (both) · effort M
  - _Gap:_ The original-maturity >=1 year condition applies only 'where there is a maturity mismatch' (Art. 237(2) chapeau); matched short-dated protection (protection maturity >= exposure maturity) remains eligible.
  - _Evidence:_ src/rwa_calc/engine/crm/guarantees.py:191-200 drops every guarantee row with original_maturity_years < 1.0 unconditionally, before any mismatch determination — a 9-month guarantee fully covering a 6-month exposure (no mismatch) is discarded, over-stating RWA. The collateral sibling is correct: haircuts.py:736-744 evaluates the <1y gate only inside the mismatch branch (the when-chain returns 1.0 first when there is no mismatch). Conservative-only deviation, but systematic for short-dated trade-finance guarantees.
  - _Fix:_ Move the original-maturity test out of the unconditional pre-filter into _apply_maturity_mismatch_to_guarantees, zeroing coverage only when a mismatch exists (mirroring haircuts.py ordering).
  - _Files:_ `guarantees.py`, `haircuts.py`

### WS3 — Financial-collateral eligibility & supervisory haircuts
_8 findings (0 high, 5 medium, 3 low)_

- **P1.233** [🟠 MED] · **CRR Art. 197(1)(c)/(d); PS1/26 Art. 197(1)(c)/(d)** (both) · effort S
  - _Gap:_ Institution/corporate debt securities with CQS 1-3 are eligible financial collateral with Art. 224 Table 1 bond haircuts; CQS 4-6/unrated corporate debt is ineligible (subject to the Art. 197(4) route).
  - _Evidence:_ 'bond' is a canonical validated collateral_type (data/schemas.py:1554, VALID_COLLATERAL_TYPES) but haircuts.py::_normalize_collateral_type_expr only maps it to govt_bond when issuer_type=='sovereign' (645-649); with issuer_type corporate/pse/securitisation or null it falls to .otherwise('other_physical') (658). Effects: (a) the Art. 197 bond CQS-eligibility zeroing (570-578) never fires — a CQS-5 corporate 'bond' flagged is_eligible_financial_collateral=True is recognised at 60% of market value in the SA E* reducti
  - _Fix:_ Extend _normalize_collateral_type_expr: 'bond' + issuer_type in (corporate, pse, institution) -> corp_bond (and add 'bond' to the financial-type categorisation keyed on issuer_type) so the Art. 197 CQS gates and Table 1 haircuts apply; route issuer_type='securitisation' to the new securitisation branch.
  - _Files:_ `haircuts.py`, `schemas.py`, `expressions.py`
- **P1.234** [🟠 MED] · **CRR Art. 197(1)(h); PS1/26 Art. 197(1)(h)** (both) · effort M
  - _Gap:_ Non-resecuritisation securitisation positions risk-weighted <= 100% are eligible financial collateral, with dedicated (roughly double-corporate) supervisory haircuts in Art. 224 Table 1; resecuritisations and >100%-RW positions are ineligible.
  - _Evidence:_ No securitisation branch exists: haircuts.py::_normalize_collateral_type_expr (634-659) has no securitisation case, and the pack haircut tables contain no securitisation rows (rulebook/packs/crr.py:756-790 rows cover cash/gold/govt_bond/corp_bond/equity/RE/receivables/other_physical only; b31.py:754-804 likewise). VALID_ISSUER_TYPES includes 'securitisation' (data/schemas.py:1676) but it is never consumed for haircut pricing or eligibility. Consequence: a securitisation bond posted as 'corporate_bond' receives corp
  - _Fix:_ Add a 'securitisation' collateral normalisation branch keyed on issuer_type/collateral_type, with dedicated Art. 224 Table 1 securitisation haircut rows in both packs, an eligibility gate on position RW <= 100%, and hard ineligibility for resecuritisations.
  - _Files:_ `haircuts.py`, `crr.py`, `b31.py`
- **P1.235** [🟠 MED] · **CRR Art. 199(2), 199(5), 199(6); PS1/26 Art. 199(2)/(5)/(6)** (both) · effort M
  - _Gap:_ IRB/FCM non-financial collateral is eligible only under conditions: RE — property value not materially dependent on obligor credit and (for CRE under PS1/26; for both under CRR unless the 199(3)/(4) derogations apply) repayment not materially dependent on the property (199(2)); receivables — commercial, original maturity <= 1 year, excluding securitisation-linked/sub-participation/credit-derivative-related and affiliated-party amounts (199(5)); other physical — supervisory permission plus liquid-market / public-price / 70%-10% realisation tests (199(6)).
  - _Evidence:_ The FIRB Foundation Collateral Method waterfall recognises every real_estate/receivables/other_physical collateral row unconditionally: engine/crm/collateral.py:687-709 annotates all rows with LGDS/overcollateralisation and no eligibility filter exists anywhere in the chain. The schema field designed for this — is_eligible_irb_collateral (data/schemas.py:496, default False) — is written only onto synthetic netting rows (collateral.py:286-287) and is never read as a gate (grep across src shows no consumer). Receivab
  - _Fix:_ Wire is_eligible_irb_collateral as a real gate on the non-financial branches of the FCM waterfall (defaulting False is already conservative), or at minimum zero non-financial collateral rows lacking the flag and emit a CRM data-quality warning; add a receivables original-maturity<=1y and affiliated-party check where inputs allow.
  - _Files:_ `collateral.py`, `schemas.py`, `haircuts.py`
- **P1.236** [🟠 MED] · **Art. 224 Table 1 with Art. 197(1)(b)/(d) (PS1/26 retained)** (both) · effort S
  - _Gap:_ Debt-security collateral takes the Art. 224 Table 1 haircut by issuer class, CQS and maturity, and is ineligible below CQS 4 (government) / CQS 3 (corporate) per Art. 197 — ineligible bonds must get zero recognition.
  - _Evidence:_ VALID_COLLATERAL_TYPES (data/schemas.py:1550-1560) canonicalises bonds as "bond" (with issuer_type in {sovereign,pse,corporate,securitisation}), but _normalize_collateral_type_expr (engine/crm/haircuts.py:637-659) only maps "bond" to govt_bond when issuer_type=="sovereign" (line 647); a "bond" with issuer_type corporate/pse/securitisation falls to other_physical → 40% flat haircut instead of the 1-12%/20% table, and — worse — bypasses the _bond_ineligible Art. 197 CQS gate (haircuts.py:571-577, keyed on _lookup_typ
  - _Fix:_ Extend _normalize_collateral_type_expr with a ((ct=="bond") & issuer_type in {corporate, pse, institution}) → corp_bond branch (and securitisation → ineligible or a dedicated securitisation haircut column), so canonical bonds hit the Table 1 lookup and the Art. 197 eligibility gate.
  - _Files:_ `haircuts.py`, `schemas.py`
- **P1.237** [🟠 MED] · **Art. 224 Table 3 / Art. 197-198 (PS1/26 Art. 224)** (both) · effort M
  - _Gap:_ Main-index equities take 15% (CRR) / 20% (B31); other listed equities 25% / 30% — and under Art. 198 non-main-index equities are only eligible for repo-style transactions at all. Unknown index status should not default to the cheaper haircut.
  - _Evidence:_ engine/crm/haircuts.py:521: _equity_main_index_expr = pl.col("is_main_index").fill_null(True) — a null is_main_index on an equity collateral row is treated as main-index, giving the 15%/20% haircut instead of 25%/30% (and general-lending eligibility rather than the Art. 198 repo-only restriction, which is otherwise only enforced via the input is_eligible_financial_collateral flag). Anti-conservative null default, contrary to the project's own never-fill-anti-conservative rule.
  - _Fix:_ Change the null default to False (other-equity haircut) at haircuts.py:521; optionally emit a DQ warning when equity collateral lacks is_main_index.
  - _Files:_ `haircuts.py`
- **P1.270** [🟡 LOW] · **CRR Art. 194(4); PS1/26 Art. 194(4)** (both) · effort S
  - _Gap:_ Funded protection may be recognised only where the correlation between collateral value and obligor credit quality is 'not too high' (CRR) / there is 'no material positive correlation' (PS1/26) — the canonical case being securities issued by the obligor or a related group entity, which Basel (CRE22) makes expressly ineligible.
  - _Evidence:_ COLLATERAL_SCHEMA (data/schemas.py:481-542) carries issuer_type and issuer_cqs but no issuer identity/counterparty reference, so the engine cannot detect (or warn on) collateral issued by the obligor or its group; such rows are priced normally through the Art. 224 haircut chain. Impact depends wholly on upstream data hygiene; the deviation is an audit-trail/validation gap rather than a formula error.
  - _Fix:_ Add an optional issuer_counterparty_reference to COLLATERAL_SCHEMA and emit a data-quality error (zeroing the row) when it resolves to the obligor or a member of the obligor's hierarchy group.
  - _Files:_ `schemas.py`, `haircuts.py`
- **P1.271** [🟡 LOW] · **CRR Art. 197(1)(f) / Art. 198(1)(a); PS1/26 Art. 197(1)(f) / 198(1)(a)** (both) · effort S
  - _Gap:_ Only equities/convertibles included in a main index are eligible collateral under all methods (Art. 197(1)(f)); non-main-index equities are eligible only if listed on a recognised exchange and only under FCCM (CRR Art. 198(1)(a); PS1/26 extends to FCM/SFT-VaR), at the higher 25%/30% haircut.
  - _Evidence:_ engine/crm/haircuts.py:519-525: when is_main_index is present, the equity haircut lookup uses pl.col('is_main_index').fill_null(True) — equity with UNREPORTED index membership is treated as main-index, receiving both Art. 197 all-methods eligibility and the lower 15% (CRR) / 20% (B31) haircut instead of 25%/30% (or ineligibility if unlisted). data/schemas.py:509-516 documents this as a deliberate backward-compatibility default, pinned by tests/unit/crm/test_equity_main_index.py. Anti-conservative by 10pp of collate
  - _Fix:_ Flip the null-resolution to other-listed (fill_null(False)) or make it a validated required field for equity collateral; add an is_listed flag (default False -> ineligible) to gate Art. 198(1)(a).
  - _Files:_ `haircuts.py`, `schemas.py`
- **P1.272** [🟡 LOW] · **PS1/26 Art. 230(1) / CRR Art. 228(2)** (both) · effort S
  - _Gap:_ The FCM LGD* denominators use E(1+HE): LGD* = LGDU·EU/(E(1+HE)) + LGDS·ES/(E(1+HE)) with EU = E(1+HE) − ES (PS1/26 Art. 230(1), verified verbatim); CRR Art. 228(2) equivalently embeds HE in E*.
  - _Evidence:_ lgd_star_expr (engine/crm/collateral.py:1102-1111) computes (LGDS·min(C,E) + LGDU·max(0,E−C))/E on ead_for_crm without the (1+HE) gross-up; exposure_volatility_haircut is consumed only in the SA EAD branch (collateral.py:1074-1092). HE is non-zero only for is_sft rows lending securities on the general CRM path, so FIRB SFT-style exposures there get a slightly understated LGD* (unsecured share denominator too small). The dedicated SFT-FCCM path is unaffected (it emits E* directly).
  - _Fix:_ Multiply the exposure basis in lgd_star_expr (and the total_collateral cap) by (1 + exposure_volatility_haircut) for rows where HE > 0.
  - _Files:_ `collateral.py`

### WS4 — Third-party cash, on-B/S netting & other funded protection
_7 findings (0 high, 4 medium, 3 low)_

- **P1.238** [🟠 MED] · **CRR Art. 195; PS1/26 Art. 195** (both) · effort M
  - _Gap:_ On-balance-sheet netting is limited to 'mutual claims between itself and its counterparty' and 'reciprocal cash balances between the institution and the counterparty' (CRR Art. 195; PS1/26 Art. 195(1)-(2) identical). Netting a deposit received from counterparty A against a loan to counterparty B is not within Art. 195 eligibility.
  - _Evidence:_ engine/crm/collateral.py::generate_netting_collateral (152-260): the netting pool is grouped only by (netting_agreement_reference, currency) (lines 218-224) and beneficiaries are matched solely on the shared reference (lines 230-247) — there is no counterparty-equality constraint. The docstring at lines 168-172 makes it deliberate: 'A deposit from one counterparty may net a loan to a different counterparty (and across different facilities) iff both carry the same reference'. If input data carries a group-level nett
  - _Fix:_ Constrain the pool join to rows sharing the same counterparty_reference (or gate cross-counterparty pools behind an explicit, documented input attestation and emit a CRM warning), so that only reciprocal balances with the same counterparty net by default.
  - _Files:_ `collateral.py`
- **P1.239** [🟠 MED] · **CRR Art. 200(a) (+ Art. 232(2)); PS1/26 Art. 200(1)(a)** (both) · effort M
  - _Gap:_ Cash on deposit with a THIRD-PARTY institution pledged to the lender is 'other funded credit protection' — recognised via the Other Funded Credit Protection Method as if it were a guarantee by the third-party institution (Art. 232(2)), not as own-bank cash with a 0% haircut/full EAD offset.
  - _Evidence:_ There is no input attribute identifying the deposit-holding institution: COLLATERAL_SCHEMA (data/schemas.py:481-542) has no holder/depository field, and engine/crm/haircuts.py::_normalize_collateral_type_expr (639-640) maps every 'cash'/'deposit' row to the cash bucket -> 0% haircut, FIRB LGDS 0%, full SA E* offset. A third-party deposit therefore gets full cash treatment (0% RW-equivalent) instead of substitution to the third-party institution's risk weight (>=20%) / guarantee treatment — an understatement wheneve
  - _Fix:_ Add an optional held_by_counterparty_reference (or is_third_party_deposit flag) to COLLATERAL_SCHEMA; when set, route the row through guarantee-equivalent treatment (substitute the holding institution's RW under SA / treat as institution guarantee under PSM) per Art. 232(2), and optionally add an instrument type for Art. 200(c) valued at repurchase price per Art. 232(4).
  - _Files:_ `schemas.py`, `haircuts.py`
- **P1.240** [🟠 MED] · **CRR Art. 212(1) (with Art. 200(a), 232(1))** (both) · effort M
  - _Gap:_ Cash on deposit with (or cash-assimilated instruments held by) a third-party institution, pledged to the lender, is 'other funded credit protection' and must be treated as a guarantee BY the third-party institution (risk-weighted at that institution's RW per Art. 232(1)) — not as own-held cash collateral at 0% effective RW.
  - _Evidence:_ src/rwa_calc/engine/crm/haircuts.py:639 — `_normalize_collateral_type_expr` maps `ct.is_in(['cash','deposit','credit_linked_note']) -> 'cash'` (0% haircut, full EAD reduction). COLLATERAL_SCHEMA (data/schemas.py:481-526) has no deposit-holding-institution field, so a third-party deposit input as 'deposit' silently receives lending-institution cash treatment (Art. 197(1)(a)) instead of substitution at the third-party bank's RW (typically >=20%) — RWA understated. Consistent with the gap, COREP C08.01 column 0173 'In
  - _Fix:_ Add a `deposit_holder_reference` (or `is_third_party_deposit`) column to COLLATERAL_SCHEMA; route flagged rows out of the cash-haircut path into the guarantee-substitution machinery keyed on the holding institution (reuse the life-insurance pattern of Art. 232 mapping), and feed COREP 0173. Interim mitigation: document that third-party deposits must be input as guarantee rows from the holding bank
  - _Files:_ `haircuts.py`, `schemas.py`, `generator.py`
- **P1.241** [🟠 MED] · **Art. 219 with Art. 237-238 (PS1/26 retained)** (both) · effort M
  - _Gap:_ On-balance-sheet netting treats deposits as cash collateral; funded-protection maturity-mismatch rules (Arts. 237-238) then apply — a deposit whose residual maturity is shorter than the netted loan's must take the (t−0.25)/(T−0.25) adjustment (or be zeroed below 3 months).
  - _Evidence:_ generate_netting_collateral (engine/crm/collateral.py:230-297) builds the synthetic cash collateral from the deposit pool but carries the LOAN sibling's maturity_date (line 277, selected from positive_siblings at line 239) and sets residual_maturity_years to null (line 285). apply_maturity_mismatch (haircuts.py:706) fills null residual_maturity_years to 10.0y, so the mismatch test coll_maturity < exposure_maturity can never fire for netting collateral: a 6-month deposit netting a 5-year loan receives full, unadjust
  - _Fix:_ Carry the negative-drawn (deposit) row's maturity into the netting pool aggregation (e.g. min maturity per pool) and emit it as residual_maturity_years on the synthetic collateral rows so Art. 237/238 applies; note IMPLEMENTATION_PLAN P7.5's claim that Art. 219 is 'not in scope' is stale and should be corrected.
  - _Files:_ `collateral.py`, `haircuts.py`
- **P1.273** [🟡 LOW] · **CRR Art. 211** (both) · effort S
  - _Gap:_ Exposures arising from leases may be treated as collateralised by the leased property when the Art. 211 conditions (lessor risk management, valuation, Art. 208/210 compliance of the leased asset) are met — feeding the IRB secured-LGD / FCM machinery.
  - _Evidence:_ No lease-as-collateral path exists: the only lease concept is the `other_residual_lease` entity type mapped to the OTHER class at 100% RW (src/rwa_calc/rulebook/packs/common.py:726,767; src/rwa_calc/engine/sa/risk_weights.py:1186,1358 — the residual-value Art. 134(7) side), and COLLATERAL_SCHEMA has no leased-asset collateral type. A lessor portfolio therefore gets unsecured treatment (F-IRB LGD 45%/40% instead of the other-physical-collateral secured LGD). Conservative-only deviation, both regimes; not tracked in 
  - _Fix:_ If lessor portfolios are in scope, allow lease exposures to carry an 'other_physical' (or RE) collateral row representing the leased asset with an Art. 211 attestation flag, flowing through the existing Art. 199(6)-(8)/230 machinery; otherwise document the scope exclusion.
  - _Files:_ `common.py`, `risk_weights.py`, `schemas.py`
- **P1.274** [🟡 LOW] · **Art. 218 (PS1/26 retained)** (both) · effort S
  - _Gap:_ Only credit-linked notes issued by the lending institution itself may be treated as cash collateral, and only where the embedded credit default swap qualifies as eligible unfunded protection.
  - _Evidence:_ engine/crm/haircuts.py:639 and :827-829 map any collateral_type="credit_linked_note" to cash (0% haircut, LGDS 0% via FINANCIAL_COLLATERAL_TYPES, schemas.py:1583) with no issuer-identity or embedded-CDS eligibility check — a third-party CLN mis-tagged with this type receives full cash treatment.
  - _Fix:_ Gate the CLN→cash mapping on an issuer==reporting-institution marker (e.g. issuer_type="self" or a boolean), else fall back to the instrument's own bond treatment; emit a DQ warning when the marker is absent.
  - _Files:_ `haircuts.py`, `schemas.py`
- **P1.275** [🟡 LOW] · **Art. 232(2)-(3) (PS1/26 retained)** (both) · effort S
  - _Gap:_ The life-insurance protection value is the current surrender value, reduced per Art. 233(3)/(4) (8% haircut, maturity-mismatch-scaled) on a currency mismatch; the mapped RW applies to the collateralised portion.
  - _Evidence:_ The SA RW-mapping path (engine/crm/life_insurance.py:129-158) sums raw market_value with no currency comparison — a USD policy securing a GBP exposure gets full value with no 8% reduction (understatement); it also joins only beneficiary_reference = exposure_reference, silently dropping facility- and counterparty-level life-insurance pledges (conservative). The comprehensive/LGD path does apply Hfx (haircuts.py:917-938 and the vectorised gate, since life_insurance is not in NON_FINANCIAL_COLLATERAL_TYPES). RW map va
  - _Fix:_ Apply the Art. 233(3) 8% reduction in compute_life_insurance_columns when policy currency differs from exposure currency; extend the join to facility/counterparty beneficiary levels pro-rata; fix the pack citation to Art. 232(3).
  - _Files:_ `life_insurance.py`, `common.py`

### WS5 — IRB classification & risk parameters
_17 findings (2 high, 10 medium, 5 low)_

- **P1.220** [🔴 HIGH] · **PS1/26 Art. 147(3)(c)-(e) read with Art. 147A(1)(a)** (b31) · effort M
  - _Gap:_ PS1/26 Art. 147(3) assigns exposures to "(c) regional governments; (d) local authorities; (e) public sector entities; (f) multilateral development banks" to the central-governments/quasi-sovereign class UNCONDITIONALLY (verified in ps126app1.pdf p.88-89 — the CRR-era "treated as exposures to central governments under Articles 115/116" qualifier is removed; only international organisations retain a 0%-RW qualifier), and PS1/26 Art. 147(4) limits the institutions class to institutions and Art. 119(5) financial institutions. Art. 147A(1)(a) then mandates the Standardised Approach for the whole quasi-sovereign class.
  - _Evidence:_ The engine deliberately keeps institution-typed RGLAs/PSEs modellable under Basel 3.1: B31_SOVEREIGN_LIKE_ENTITY_TYPES excludes rgla_institution/pse_institution with the comment "they route to institution IRB per Art. 147A(1)(b)" (data/schemas.py:1538-1548); approach.py:204-215 only blocks A-IRB for the institution class, so an rgla_institution/pse_institution row with an internal rating and an INSTITUTION-class model permission is assigned F-IRB; contracts/config.py:463-465,479-482 documents the design on the basi
  - _Fix:_ Under the approach_restrictions_b31_applicable Feature, add rgla_institution and pse_institution to the SA-only entity-type set (or a separate b31_quasi_sovereign_sa_only list keyed off the pack), update full_irb_b31() docstring, and correct the skill/docs tables that carry the CRR-era 0%-RW qualifier. Verify against ps126app1.pdf Art. 147(3)-(4) before changing, since this contradicts the project
  - _Files:_ `schemas.py`, `approach.py`, `config.py`
- **P1.221** [🔴 HIGH] · **CRR Art. 159 / PS1/26 Art. 159 (CRE35.4)** (both) · effort M
  - _Gap:_ Art. 159 requires institutions to subtract TOTAL expected loss amounts from the TOTAL general and specific credit risk adjustments, AVAs and other own-funds reductions related to those exposures (an aggregate comparison per pool; CRE35.4: 'banks must compare the total amount of total eligible provisions with the total EL amount'). Only the defaulted-SCRA-cannot-cover-other-EL restriction limits netting.
  - _Evidence:_ src/rwa_calc/engine/irb/adjustments.py:360-364 computes PER-EXPOSURE el_shortfall = max(0, EL_i - poolB_i) and el_excess = max(0, poolB_i - EL_i); src/rwa_calc/engine/aggregator/_el_summary.py:99-101 then SUMS these already-floored row values within each default-status pool (pl.col('el_shortfall').sum()), and lines 197-230 use those sums directly as effective_shortfall/effective_excess. No intra-pool netting of aggregate EL vs aggregate Pool B ever occurs — the comment at _el_summary.py:224 ('still net within their
  - _Fix:_ In compute_el_portfolio_summary, aggregate raw sums of expected_loss and pool_b (provisions+AVA+other OFR) per default-status pool, then compute pool-level shortfall = max(0, sum_EL - sum_poolB) and excess = max(0, sum_poolB - sum_EL) before applying the two-branch cross-offset rule. Keep the per-row columns for audit only, not for summation into the capital figures.
  - _Files:_ `adjustments.py`, `_el_summary.py`
- **P1.242** [🟠 MED] · **CRR Art. 142(1)(4)-(5) / Art. 153(2); PS1/26 IRB Part glossary (large financial sector entity) / Art. 153(2)** (both) · effort M
  - _Gap:_ The 1.25x correlation multiplier applies to exposures to large financial sector entities (total assets >= EUR 70bn under CRR Art. 142(1)(4); >= GBP 79bn at highest level of consolidation under the PS1/26 IRB Part glossary, verified in ps126app1.pdf) and to unregulated financial sector entities. PS1/26 retains the multiplier unchanged ("shall multiply the coefficient of correlation (R) ... by 1.25").
  - _Evidence:_ The multiplier is driven solely by the user-supplied counterparty flag: engine/stages/classify/subtypes.py:181-184 sets requires_fi_scalar = cp_apply_fi_scalar with the explicit docstring "user flag is authoritative ... (no entity-type gate)" (subtypes.py:70-71); engine/irb/formulas.py:668-676 applies 1.25 when requires_fi_scalar. apply_fi_scalar defaults to False (data/schemas.py:437). The CRR pack carries lfse_total_assets_threshold = EUR 70bn (rulebook/packs/crr.py:621, mis-cited to "Art. 4(1)(146)" — the large-
  - _Fix:_ Derive a fallback: requires_fi_scalar = apply_fi_scalar OR (is_financial_sector_entity AND cp_total_assets >= lfse_total_assets_threshold), reading the threshold from the pack (fix b31 value to GBP 79,000,000,000 with a PS1/26 glossary citation; fix the crr citation to Art. 142(1)(4)). Emit a DQ warning when is_financial_sector_entity=True, total_assets >= threshold and apply_fi_scalar is False/nu
  - _Files:_ `subtypes.py`, `formulas.py`, `crr.py`
- **P1.243** [🟠 MED] · **CRR Art. 147(5)(a); PS1/26 Art. 147(5)(a)** (both) · effort M
  - _Gap:_ For IRB retail class assignment the monetary cap applies ONLY to the SME limb: CRR Art. 147(5)(a) — "(i) exposures to one or more natural persons; (ii) exposures to an SME, provided in that case that the total amount owed ... exceed EUR 1 million" (verified crr.pdf); PS1/26 Art. 147(5)(a) identical structure with GBP 880,000 (verified ps126app1.pdf p.90). Natural persons qualify for IRB retail with no amount cap (subject to the management-basis conditions).
  - _Evidence:_ qualifies_as_retail applies the aggregate threshold to every row: engine/stages/classify/attributes.py:566-579 (CRR branch is a pure threshold check; the B31 branch also puts threshold_fail first at :614-616), and engine/stages/classify/subtypes.py:164-169 reclassifies any RETAIL_OTHER row with qualifies_as_retail=False — including natural persons — to CORPORATE. A natural person with > EUR 1m / GBP 880k of non-RRE-secured aggregate borrowing in an IRB retail book is therefore expelled from the retail IRB class int
  - _Fix:_ Split the concepts: keep qualifies_as_retail for SA regulatory-retail (threshold applies to all), and add an IRB-side qualifier where the threshold limb is bypassed for natural persons (cp_entity_type in individual/natural_person or is_natural_person=True), so IRB-routed natural persons stay in the retail IRB class regardless of aggregate amount.
  - _Files:_ `attributes.py`, `subtypes.py`
- **P1.244** [🟠 MED] · **PS1/26 Art. 147(5A)(a)-(b) (CRR analogue Art. 154(4)(a)-(b), out of this range)** (b31) · effort M
  - _Gap:_ QRRE sub-class assignment requires (a) the exposures are to individuals, and (b) they are revolving, UNSECURED, and (to the extent undrawn) immediately and unconditionally cancellable (ps126app1.pdf p.90-91, with a wage-account collateral derogation). The GBP 90k limit is condition (c) only.
  - _Evidence:_ engine/stages/classify/subtypes.py:122-138 classifies QRRE from exposure_class==RETAIL_OTHER AND qualifies_as_retail AND is_revolving AND per-obligor aggregate facility_limit <= GBP 90k. Neither the individuals-only condition (is_natural_person exists on COUNTERPARTY_SCHEMA at schemas.py:439 but is unused here — an SME reclassified to RETAIL_OTHER via reclassify_corporate_to_retail can become QRRE) nor the unsecured/unconditionally-cancellable conditions are tested (a secured revolving retail facility qualifies). M
  - _Fix:_ Extend is_qrre_candidate with an individuals gate (cp_entity_type in {individual, natural_person} or cp_is_natural_person) and an unsecured gate (no collateral allocated to the exposure, with the wage-account derogation as an input flag). The same conditions apply under CRR Art. 154(4) so the gate need not be regime-Featured except for the limit value already handled.
  - _Files:_ `subtypes.py`, `schemas.py`
- **P1.245** [🟠 MED] · **PS1/26 Art. 147(4C)(b)(ii) read with Art. 147A(1)(e)** (b31) · effort M
  - _Gap:_ The financial-corporates-and-large-corporates subclass (F-IRB only) captures corporates "with annual revenue of more than GBP 440 million, taken at the highest level of consolidation which is performed and at which audited financial statements are available ... annual revenue shall be calculated as the average annual amount over the last three years" (ps126app1.pdf p.89).
  - _Evidence:_ engine/stages/classify/approach.py:186-203 tests cp_annual_revenue — the counterparty's own point-in-time revenue field (schemas.py:433, no consolidation-basis documentation) — against the GBP 440m pack threshold. No group roll-up is performed (no annual_revenue handling anywhere in engine/stages/hierarchy despite parent/ultimate-parent mappings being available), and no 3-year averaging. A subsidiary with own revenue below GBP 440m inside a larger consolidated group keeps A-IRB eligibility where PS1/26 mandates F-I
  - _Fix:_ Either roll consolidated revenue up the existing counterparty hierarchy (max of own and ultimate-parent group revenue) before the large-corp test, or document on COUNTERPARTY_SCHEMA.annual_revenue that the 3-year-average highest-consolidation figure must be supplied, and add a DQ warning when a counterparty with a parent mapping carries revenue just below the threshold.
  - _Files:_ `approach.py`, `schemas.py`
- **P1.246** [🟠 MED] · **CRR Art. 153(2) / PS1/26 Art. 153(2)** (both) · effort M
  - _Gap:_ The asset-value-correlation coefficient must be multiplied by 1.25 for all exposures to large financial sector entities (total assets >= EUR 70bn, CRR Art. 4(1)(146)) and to unregulated financial entities — it is a mandatory treatment, not an input election.
  - _Evidence:_ engine/stages/classify/subtypes.py:181-184 sets requires_fi_scalar purely as (cp_apply_fi_scalar == True).fill_null(False) — the docstring at :70-71 says 'derives requires_fi_scalar directly from the user-supplied apply_fi_scalar flag (no entity-type gate)'. The 1.25x is then applied in engine/irb/formulas.py:668-676 only when that flag is set. The rulepack DECLARES the size test — rulebook/packs/crr.py:621 'lfse_total_assets_threshold': Decimal('70000000000') # EUR 70bn (Art. 4(1)(146)) — but a repo-wide grep show
  - _Fix:_ Derive requires_fi_scalar = cp_apply_fi_scalar OR (cp_is_financial_sector_entity AND (cp_is_unregulated OR total_assets >= regulatory_threshold(pack, 'lfse_total_assets_threshold', ...))) in classify_exposure_subtypes; keep the explicit flag as an authoritative True-override. Give b31.py a real threshold (PRA GBP conversion of EUR 70bn) instead of 0, or gate the derivation per-regime via a Feature
  - _Files:_ `subtypes.py`, `formulas.py`, `crr.py`
- **P1.247** [🟠 MED] · **CRR Art. 158(7)-(9)** (crr) · effort M
  - _Gap:_ For equity exposures under the Art. 155(2) simple risk-weight method, expected loss amounts must be calculated as EL x exposure value with EL = 0.8% for private equity in sufficiently diversified portfolios and exchange-traded exposures, 2.4% for all other equity; these EL amounts feed the Art. 159 shortfall/excess comparison.
  - _Evidence:_ engine/equity/calculator.py::_apply_equity_weights_irb_simple (:692-734) assigns only risk_weight, and _calculate_rwa (:1033-1043) emits only rwa/rwa_final — no expected_loss column is ever produced on the IRB-Simple path (the only equity EL is on the PD/LGD branch at :910). A repo-wide grep for 0.008/0.024 finds only the slotting EL pack entries (packs/crr.py:405, b31.py:397) — the Art. 158(7) equity EL rates exist nowhere. compute_el_shortfall_excess (engine/irb/adjustments.py:287) and the slotting twin are the o
  - _Fix:_ Add a cited FormulaParams entry (equity_simple_el: diversified_pe 0.008, exchange_traded 0.008, other 0.024) to packs/crr.py; in _apply_equity_weights_irb_simple emit expected_loss = el_rate x ead_final using the same type-routing as the RW when-chain; include equity expected_loss in the EL shortfall/excess aggregation.
  - _Files:_ `calculator.py`, `adjustments.py`, `crr.py`
- **P1.248** [🟠 MED] · **PS1/26 Art. 161(5) (CRE32.17)** (b31) · effort M
  - _Gap:_ Under Basel 3.1 the A-IRB LGD floor for a PARTIALLY secured corporate exposure is the EAD-weighted average of the 25% unsecured floor on the unsecured portion and the collateral-type LGDS floor on the secured portion (CRE32.17 formula; PS1/26 Art. 161(5) mirrors it).
  - _Evidence:_ src/rwa_calc/engine/irb/formulas.py:301-315 (_lgd_floor_expression_with_collateral) assigns the FULL secured floor (e.g. 10% for RRE/CRE, 15% other physical) to the whole exposure whenever collateral_type matches, with no weighting by coverage; the EAD-weighted blend exists only in _lgd_floor_blended_expression, whose eligibility gate at formulas.py:402 is exp_class.is_in(['retail_other','retail_qrre']) — corporates are excluded. A corporate 10%-secured by RRE with own LGD 15% gets floor 10% (own 15% kept) where th
  - _Fix:_ Extend _lgd_floor_blended_expression eligibility to corporate/institution A-IRB rows (using crm_alloc_* and total_collateral_for_lgd with LGDU=25% from floors['unsecured']), retaining the flat per-type floor only as the no-allocation-columns fallback.
  - _Files:_ `formulas.py`, `transforms.py`
- **P1.249** [🟠 MED] · **CRR Art. 162(1)** (crr) · effort M
  - _Gap:_ Institutions without own-LGD/CCF permission shall assign M = 0.5y to repo-style exposures and M = 2.5y to ALL other exposures, unless their Art. 143 permission requires use of the Art. 162(2) effective maturity for each exposure.
  - _Evidence:_ src/rwa_calc/engine/irb/transforms.py:889-914 (_maturity_base_expr) derives M from maturity_date clipped [1,5] for every row regardless of approach; the only Art. 162(1) element implemented is the SFT 0.5y override (_apply_firb_sft_supervisory_maturity, transforms.py:917-939, gated on the firb_sft_supervisory_maturity Feature). There is no Feature/config election to apply the fixed 2.5y to FIRB non-SFT exposures — the calculator hard-codes the 'alternative' 162(1) second-sentence behaviour. For a firm whose permiss
  - _Fix:_ Add a CRR pack Feature (e.g. firb_fixed_supervisory_maturity) or CalculationConfig election that, when set, pins FIRB non-SFT M to 2.5y (repo-style stays 0.5y) ahead of the date-derived rung; document the default as the Art. 162(1) second-sentence alternative.
  - _Files:_ `transforms.py`, `crr.py`
- **P1.250** [🟠 MED] · **CRR Art. 166(8)** (crr) · effort S
  - _Gap:_ Under CRR, own-estimate conversion factors are permitted only across the product types in Art. 166(8)(a)-(d) (credit lines, trade LCs, purchased-receivables commitments, NIFs/RUFs), subject to permission; an A-IRB institution without an own estimate for an item must apply the Art. 166(8) supervisory CFs (e.g. 75% for credit lines/NIFs/RUFs), not the SA Art. 111 CCFs.
  - _Evidence:_ src/rwa_calc/engine/ccf.py:569 — under CRR the A-IRB branch is `airb_ccf = ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type"))`. Two defects: (1) when ccf_modelled is null the row gets the SA CCF (MR/OC 50%, MLR 20%, and even 20% for short-maturity OC via the Art. 111 override at ccf.py:486-501) instead of the Art. 166(8)(d) supervisory 75% — a 25-30pp EAD under-statement on undrawn commitments; (2) ccf_modelled is honoured for ANY risk_type, including FR issued items (guarantees, credit derivatives) and 
  - _Fix:_ In the CRR (not firb_uses_sa_ccf) branch of _compute_ccf: change the A-IRB fallback to `ccf_modelled_expr.fill_null(pl.col("_firb_ccf_from_risk_type"))`, and gate the use of ccf_modelled on the Art. 166(8)(a)-(d) product scope (is_obs_commitment=True commitments / trade LCs), routing issued OBS items (is_obs_commitment=False) and FR/FRC rows to the Art. 166(10)/166(8) supervisory values unconditio
  - _Files:_ `ccf.py`, `test_ccf.py`, `test_irb_approach_selection.py`
- **P1.251** [🟠 MED] · **PS1/26 Art. 166C(1) (with Art. 111(1) Table A1 Row 4(b))** (b31) · effort M
  - _Gap:_ Under PS1/26, F-IRB (and Slotting) off-balance-sheet exposure values use the SA conversion factor 'that would be applicable ... under the Standardised Approach, as set out in Article 111' — which includes the PRA-specific Table A1 Row 4(b) 50% CCF for UK residential mortgage commitments not subject to a 10% or 100% CCF.
  - _Evidence:_ src/rwa_calc/engine/ccf.py:510-520 — the Row 4(b) override (`is_uk_residential_mortgage_commitment` -> 50%) rewrites only `_sa_ccf_from_risk_type`; the parallel `_firb_ccf_from_risk_type` column (built at ccf.py:467/474-480 from the same B31 SA table) is not patched, unlike `_apply_purchased_receivable_ccf` (ccf.py:623-632) which correctly patches both columns. The final CCF selection at ccf.py:577-578 routes approach==FIRB rows to `_firb_ccf_from_risk_type`, so a B31 F-IRB exposure flagged is_uk_residential_mortga
  - _Fix:_ Apply the Row 4(b) override to both `_sa_ccf_from_risk_type` and `_firb_ccf_from_risk_type` in the same with_columns (mirroring the _apply_purchased_receivable_ccf pattern), and add a unit test pinning B31 FIRB + is_uk_residential_mortgage_commitment + risk_type=OC -> CCF 0.50.
  - _Files:_ `ccf.py`
- **P1.276** [🟡 LOW] · **CRR Art. 147(3)(b) / 147(4)(c)** (crr) · effort S
  - _Gap:_ Only MDBs referred to in Art. 117(2) (0% RW list) are assigned to the central-governments IRB class; "exposures to multilateral development banks which are not assigned a 0% risk weight under Article 117" must be assigned to the institutions class (verified crr.pdf Art. 147(4)(c)).
  - _Evidence:_ rulebook/packs/common.py:747 maps entity_type "mdb" (the generic, CQS-rated, non-0% MDB — the SA layer distinguishes it from "mdb_named", which alone gets the 0% override at engine/sa/risk_weights.py:1102-1103) to ExposureClass.CENTRAL_GOVT_CENTRAL_BANK in entity_type_to_irb_class, same as "mdb_named". Under CRR the capital effect is nil (identical correlation formula, supervisory LGD and uniform 0.03% PD floor for CGCB vs INSTITUTION) but the IRB exposure class is misreported in COREP C08 class breakdowns and the 
  - _Fix:_ Map "mdb" to ExposureClass.INSTITUTION in entity_type_to_irb_class (keep "mdb_named" on CGCB), or split the map by regime if the B31 quasi-sovereign entity list is reworked under the rgla/pse finding.
  - _Files:_ `common.py`, `entity_class_maps.py`
- **P1.277** [🟡 LOW] · **CRR Art. 160(1)** (crr) · effort S
  - _Gap:_ The 0.03% PD floor applies to exposures to corporates and institutions; exposures to central governments and central banks are NOT subject to the floor under CRR.
  - _Evidence:_ packs/crr.py:135-147 includes 'sovereign': Decimal('0.0003') in pd_floors, and formulas.py:151-153 short-circuits to a single scalar floor when all values are equal ('Optimisation: if all floors are the same (CRR case)'), so CENTRAL_GOVT_CENTRAL_BANK IRB rows are floored at 0.03%. A AAA sovereign with modelled PD 0.01% gets PD 0.03% -> RWA overstated (conservative-only). Under B31 this is moot (Art. 147A routes sovereigns to SA; contracts/config.py:485).
  - _Fix:_ Set the CRR sovereign pd_floors entry to 0 (or None) and drop the all-equal scalar shortcut so the class-routing expression always runs; add a unit test pinning sovereign PD pass-through under CRR.
  - _Files:_ `crr.py`, `formulas.py`
- **P1.278** [🟡 LOW] · **CRR Art. 160(2) / Art. 163(2) (and PS1/26 successors)** (both) · effort S
  - _Gap:_ For purchased corporate receivables where the institution cannot estimate PDs, PD shall be the EL estimate divided by LGD (top-down approach); dilution-risk PD shall equal the EL estimate for dilution risk.
  - _Evidence:_ No implementation exists: grep for '160(2)' / EL-derived PD returns nothing in src/rwa_calc; the purchased-receivables machinery covers only the LGD side (Art. 161(1)(e)-(g) subtype routing at irb/transforms.py:182-196). The classifier gates all IRB routing on internal_pd being non-null (has_internal_rating), so purchased receivables without obligor PDs fall to SA rather than the Art. 160(2) top-down IRB treatment, and there is no EL-estimate input field on the schemas to support it.
  - _Fix:_ Add el_estimate / el_dilution_estimate inputs for purchased receivables and derive PD = EL/LGD (dilution PD = EL) in the classifier/IRB prep when internal_pd is null and purchased_receivables_subtype is set; document the SA fallback otherwise.
  - _Files:_ `transforms.py`, `classifier.py`, `schemas.py`
- **P1.279** [🟡 LOW] · **CRR Art. 166(4) / PS1/26 Art. 166A(4)** (both) · effort S
  - _Gap:_ The exposure value for leases is the discounted minimum lease payments (payments over the lease term the lessee is or can be required to make plus any bargain option); a third-party residual-value payment obligation meeting Art. 201/213 may be recognised as unfunded credit protection.
  - _Evidence:_ Grep of src/rwa_calc for lease handling finds only the SA-side "other_residual_lease" entity type (data/schemas.py:430,1507; packs/common.py:726,767; engine/sa/risk_weights.py:1186,1358 — the Art. 134 residual-value path). There is no lease product type on LOAN/FACILITY schemas, no discounting of minimum lease payments, and no documented input convention: a finance-lease receivable only complies if the upstream feed already supplies drawn_amount as the discounted receivable, which nothing validates or documents. Th
  - _Fix:_ Document the lease input convention (drawn_amount = discounted minimum lease payments per Art. 166(4)/166A(4)) in docs/specifications and the schema docstrings; optionally add an exposure_type="lease" marker with a DQ validation that a discount rate/undiscounted-flows pair is absent or consistent.
  - _Files:_ `schemas.py`, `ccf.py`
- **P1.280** [🟡 LOW] · **PS1/26 Art. 166A(5) (mis-cited as "Art. 166E(5)")** (b31) · effort S
  - _Gap:_ The 40%/10% CCF for undrawn purchase commitments on revolving purchased receivables sits in Article 166A paragraph 5 (second sub-paragraph) of the final PS1/26 instrument (ps126app1.pdf p.118); the instrument's IRB exposure-value section runs Art. 166A-166D only — no Article 166E exists.
  - _Evidence:_ The implemented values are correct (40% OC default, 10% UCC — engine/ccf.py::_apply_purchased_receivable_ccf reading _SA_CCF_B31_MAP), but 13 code references cite the non-existent "Art. 166E(5)": src/rwa_calc/engine/ccf.py:385,589-599 (including the @cites("PS1/26, paragraph 166.5") watchfire decorator at :592), src/rwa_calc/data/schemas.py:200-206,359, src/rwa_calc/engine/stages/hierarchy/facility_undrawn.py:28,513, src/rwa_calc/engine/stages/hierarchy/unify.py:23,151,286. docs/specifications/crr/credit-conversion
  - _Fix:_ Global rename of the citation to "PS1/26 Art. 166A(5)" across the four source files and the spec; refresh the spec's stale "not yet implemented" warning block (P2.31/P2.32/P2.33 no longer exist in IMPLEMENTATION_PLAN.md); verify the watchfire PS-instrument encoding still parses (166.5 remains numerically valid for Art. 166A para 5 only by coincidence — prefer the documented PS1/26 grammar form for
  - _Files:_ `ccf.py`, `schemas.py`, `facility_undrawn.py`

### WS6 — SA sovereign / quasi-sovereign risk weights
_6 findings (1 high, 2 medium, 3 low)_

- **P1.222** [🔴 HIGH] · **Art. 115(5) (CRR and PS1/26)** (both) · effort M
  - _Gap:_ UK CRR Art. 115(5) (as onshored by SI 2018/1401 reg. 113(4), crr.pdf p.114): flat 20% applies only to 'regional governments or local authorities of the United Kingdom ... denominated and funded in pounds sterling'. PS1/26 Art. 115(5) (ps126app1.pdf p.37) is identically UK/sterling-scoped. Non-UK RGLAs must instead use Table 1A (sovereign-derived) / Table 1B (own rating) or, if Art. 115(4) equivalence applies, central-government treatment.
  - _Evidence:_ engine/sa/risk_weights.py builds is_domestic_currency = is_uk_domestic | is_eu_domestic (lines 894-897, using build_eu_domestic_currency_expr over the 27-state eu_country_domestic_currency map, rulebook/packs/common.py:780-815) and applies '.when((uc == "RGLA") & is_domestic_currency).then(20%)' in BOTH regime chains (CRR: lines 1291-1293; B31: lines 1085-1087) AHEAD of the rated Table 1B join value and the unrated sovereign-derived branch. Result: an unrated Italian municipality in EUR (sovereign CQS3) gets 20% in
  - _Fix:_ Restrict the RGLA domestic-currency 20% branch to the UK limb only (cp_country_code=='GB' & denomination=='GBP') in both _apply_crr_risk_weight_overrides and _apply_b31_risk_weight_overrides; let EU RGLAs fall through to Table 1B (rated) / Table 1A sovereign-derived (unrated). Optionally add an Art. 115(4)-style central-government treatment for equivalence-listed third-country RGLAs (conservative 
  - _Files:_ `risk_weights.py`, `common.py`, `test_rgla_risk_weights.py`
- **P1.252** [🟠 MED] · **Art. 116(5) (CRR) / Art. 116(3A) (PS1/26)** (both) · effort M
  - _Gap:_ UK CRR Art. 116(5) (crr.pdf p.115): third-country PSEs may be risk-weighted per Art. 116(1)/(2) only where the Treasury has determined the jurisdiction's supervisory arrangements equivalent; 'Otherwise the institutions shall apply a risk weight of 100%'. PS1/26 scopes Art. 116(1)-(3) to 'UK public sector entities' and Art. 116(3A) redirects to third-country PSEs only via CRR Art. 116(5) equivalence (ps126app1.pdf pp.37-38).
  - _Evidence:_ Both override chains apply PSE Table 2 (sovereign-derived), Table 2A (own rating) and the Art. 116(3) short-term 20% to every PSE row regardless of jurisdiction: engine/sa/risk_weights.py:1058-1077 (B31) and 1266-1283 (CRR) key only on cqs / cp_sovereign_cqs / original_maturity_years. No jurisdiction-equivalence input exists anywhere (grep for 'equivalen' in data/schemas.py finds only unrelated output-floor columns). A PSE in a non-equivalent jurisdiction whose sovereign is CQS1 therefore gets 20% (or 20% short-ter
  - _Fix:_ Add a counterparty-level Boolean (e.g. jurisdiction_equivalent, default True for GB, nullable otherwise) or a pack-cited equivalent-jurisdiction country list; gate the PSE Table 2/2A and 116(3) short-term branches on GB-or-equivalent, with a flat 100% fallback for non-equivalent third-country PSEs. Mirror the same gate in the guarantor PSE branch. At minimum, add a DQ warning when a non-GB PSE is 
  - _Files:_ `risk_weights.py`, `schemas.py`
- **P1.253** [🟠 MED] · **Art. 117(1) (CRR)** (crr) · effort S
  - _Gap:_ Under UK CRR Art. 117(1) (crr.pdf p.116), exposures to non-named MDBs are treated 'in the same manner as exposures to institutions' — rated MDBs use Art. 120 Table 3 (CQS2 = 50%), unrated MDBs use Art. 121 Table 5 sovereign-derived — with short-term preferentials excluded. The dedicated MDB Table 2B (CQS2 = 30%, unrated 50%) exists only under PS1/26 Art. 117(1)(a)/(b).
  - _Evidence:_ engine/sa/guarantor_rw.py::build_guarantor_rw_expr prices non-named MDB guarantors from _MDB_RW = Table 2B for BOTH regimes with no is_basel_3_1 gate: lines 246-254 '.when(gec == "mdb").then(_cqs_table_lookup_expr(cqs_col, _MDB_RW, float(_MDB_UNRATED_RW)))' where _MDB_RW is read from mdb_risk_weights_table_2b (line 79); the docstring (lines 190-191) asserts 'PSE / RGLA / MDB / IO / CCP values are framework-identical', which is false for MDBs. The chain is compiled into both live guarantee-substitution paths: SA (en
  - _Fix:_ In build_guarantor_rw_expr, gate the MDB branch on is_basel_3_1: B31 keeps Table 2B; CRR routes rated non-named MDB guarantors through build_institution_guarantor_rw_expr(cqs_col, is_basel_3_1=False) (long-term only) and unrated ones to the institution unrated fallback (Art. 121; conservative 100% absent a guarantor-sovereign CQS). Fix the 'framework-identical' docstring and add CRR guarantee-subs
  - _Files:_ `guarantor_rw.py`, `rw_adjustments.py`, `guarantee.py`
- **P1.281** [🟡 LOW] · **Art. 114(3) (both) / Art. 114(2A) (PS1/26)** (both) · effort S
  - _Gap:_ Art. 114(3) (CRR crr.pdf p.112; PS1/26 p.36): exposures to the ECB are 0%. PS1/26 Art. 114(2A): an unrated central bank uses the ECAI rating of its jurisdiction's central government.
  - _Evidence:_ Grep for 'ECB' across src/rwa_calc finds only an (incorrect) docstring mention in crr_risk_weight_tables.py:343 — there is no ECB 0% branch; an ECB counterparty typed 'central_bank' with no rating falls to the Art. 114(1) unrated 100%. Likewise there is no Art. 114(2A) logic mapping an unrated central bank onto its central government's CQS — the CGCB branch reads only the exposure's own resolved cqs (risk_weights.py join + lines 1020-1031), so under B31 an unrated foreign central bank with a CQS1-rated government g
  - _Fix:_ Handle the ECB via a documented data convention (e.g. a dedicated entity_type or mdb_named-style flag) or an explicit branch; for PS1/26 Art. 114(2A), coalesce cp_sovereign_cqs into cqs for entity_type=='central_bank' rows under the B31 pack (Feature-gated), mirroring the existing MDB cp_institution_cqs lift at risk_weights.py:911-928.
  - _Files:_ `risk_weights.py`, `crr_risk_weight_tables.py`
- **P1.282** [🟡 LOW] · **Art. 115(2)/(4), Art. 116(4) (CRR; PS1/26 Art. 115(2))** (both) · effort S
  - _Gap:_ RGLAs on the central-government-equivalence list (UK: Scottish/Welsh/NI governments under PS1/26 Art. 115(2); third-country via CRR Art. 115(4)) are treated as exposures to their central government under Art. 114; CRR Art. 116(4) allows the same for guaranteed PSEs in exceptional circumstances.
  - _Evidence:_ The input schema models the distinction (entity types rgla_sovereign/pse_sovereign, schemas.py; common.py:701-704) but SA only honours it for GB RGLAs, as a hardcoded 0% (risk_weights.py:1079-1084 B31 / 1284-1290 CRR; scalar rgla_uk_devolved_rw, packs/common.py:487-491) rather than routing through the Art. 114 UK-sovereign treatment — numerically identical while the UK is CQS1 (and for sterling exposures via 114(4)), but it would understate on a UK downgrade below CQS1 for non-sterling exposures. Non-GB rgla_sovere
  - _Fix:_ Replace the hardcoded GB 0% with a re-route of rgla_sovereign (GB, plus non-GB where Art. 115(4) equivalence is asserted by data) and CRR-side pse_sovereign rows through the CGCB branch (Art. 114 CQS table + domestic-currency override), keyed on cp_sovereign_cqs; keep the current conservative behaviour where the flag or sovereign CQS is absent.
  - _Files:_ `risk_weights.py`, `common.py`
- **P1.283** [🟡 LOW] · **Art. 118** (both) · effort S
  - _Gap:_ UK CRR Art. 118 (crr.pdf p.117, with (f) omitted by SI 2019/1232) and PS1/26 Art. 118(1) (ps126app1.pdf pp.39-40) assign 0% to a closed FIVE-entry list: EU, IMF, BIS, EFSF, ESM. The ECB is 0% via Art. 114(3); IBRD/IFC/EBRD etc. are Art. 117(2) MDBs.
  - _Evidence:_ engine/sa/crr_risk_weight_tables.py:339-353 (_create_io_df docstring) states 'Art. 118 names 16 IOs (EU, IMF, BIS, ECB, EFSF, ESM, IBRD, IFC, IADB, ADB, AfDB, CEB, NIB, CDB, EBRD, EFSI)' — conflating the Art. 117(2) MDB list with the Art. 118 IO list, inventing an 'EFSI' entry, and misplacing the ECB. The runtime 0% value is correct and classification is data-driven, so there is no capital impact, but the docstring invites mis-mapping of entity_type international_org in input data (the project's own CRR spec, docs/
  - _Fix:_ Correct the docstring to the closed 5-entry list (EU, IMF, BIS, EFSF, ESM; Art. 118(f) omitted from UK CRR), and note that the ECB is 0% under Art. 114(3) and the development banks under Art. 117(2).
  - _Files:_ `crr_risk_weight_tables.py`

### WS7 — SA institution / corporate risk weights
_5 findings (0 high, 2 medium, 3 low)_

- **P1.254** [🟠 MED] · **PS1/26 Art. 121(6)** (b31) · effort M
  - _Gap:_ The SCRA risk weight for a non-local-currency exposure to an unrated institution may not be less than the RW applicable to its sovereign of incorporation 'as set out in Article 114(1) and (2)' — for an UNRATED sovereign, Art. 114(1) assigns 100%, so the floor should bind at 100% (ps126app1.pdf p.43).
  - _Evidence:_ _apply_sovereign_floor_for_institutions maps cp_sovereign_cqs through the CGCB table with unrated_default=pl.lit(None) (engine/sa/risk_weights.py:1402-1406) and the floor predicate requires _sovereign_rw non-null (:1430-1436), so when the sovereign CQS is null (unknown OR genuinely unrated) no floor applies. An FX exposure to an SCRA Grade-A bank in an unrated-sovereign jurisdiction keeps 40% instead of flooring at 100%. Mitigant: null is ambiguous between 'unrated' and 'not supplied', and unrated sovereigns are ra
  - _Fix:_ Distinguish 'sovereign unrated' from 'sovereign CQS not supplied' (e.g. sentinel 0 or a cp_sovereign_unrated flag) and floor at 100% for confirmed-unrated sovereigns; keep the no-floor behaviour only for missing data, with a DQ warning.
  - _Files:_ `risk_weights.py`
- **P1.255** [🟠 MED] · **CRR Art. 122(2)** (crr) · effort M
  - _Gap:_ Unrated corporates shall be assigned 100% OR the risk weight of exposures to the central government of the jurisdiction of incorporation, whichever is HIGHER (crr.pdf p.120: 'whichever is the higher').
  - _Evidence:_ The CRR unrated corporate weight is the flat join value corporate_risk_weights[UNRATED]=1.00 (packs/crr.py:938); _apply_crr_risk_weight_overrides (engine/sa/risk_weights.py:1200-1368) contains no corporate branch reading cp_sovereign_cqs, and the sovereign floor helper is scoped to _upper_class contains 'INSTITUTION' only (risk_weights.py:1428). An unrated corporate incorporated in a CQS6 jurisdiction (sovereign RW 150%) is weighted 100% — a 50pp understatement. Only CQS6 sovereigns diverge (CQS4/5 sovereigns are 1
  - _Fix:_ In _apply_crr_risk_weight_overrides add a branch for CORPORATE & unrated: max_horizontal(1.00, CGCB-table lookup on cp_sovereign_cqs with null->1.00), CRR arm only.
  - _Files:_ `risk_weights.py`, `crr.py`
- **P1.284** [🟡 LOW] · **CRR Art. 119(2)-(3)** (crr) · effort S
  - _Gap:_ Exposures to institutions with residual maturity <=3m denominated AND funded in the borrower's national currency shall be assigned a RW one category less favourable than the Art. 114(4)-(7) preferential sovereign RW, with a 20% floor (crr.pdf p.117). Effectively 20% for e.g. GBP <=3m exposures to UK institutions.
  - _Evidence:_ No branch in _apply_crr_risk_weight_overrides or _crr_append_institution_maturity_branches (engine/sa/risk_weights.py:805-832, 1200-1368) implements the Art. 119(2) derivation; such exposures instead get Table 4 (rated: 20-150%) or, if unrated with original maturity >3m but residual <=3m, the flat 100% fallback instead of 20%. The omission can only overstate RWA (the rule grants a more favourable weight), so it is a conservative-only deviation. CRR-only — PS1/26 leaves Art. 119(2)-(3) blank. Sunsets 31 Dec 2026.
  - _Fix:_ If desired before end-2026: add a CRR institution branch for residual<=3m & denominated-and-funded-in-national-currency (reuse cp_local_currency plus a funding flag) assigning max(20%, one-step-worse of the Art. 114(4)-(7) preferential RW).
  - _Files:_ `risk_weights.py`
- **P1.285** [🟡 LOW] · **CRR Art. 119(4)** (crr) · effort S
  - _Gap:_ Exposures in the form of minimum reserves required by the Bank of England held via another institution may be risk-weighted as exposures to the central bank, subject to conditions (crr.pdf p.117).
  - _Evidence:_ No input flag or engine branch exists for intermediated central-bank reserves (no grep hits for reserves handling in engine/ or data/schemas.py); such exposures would be weighted as ordinary institution exposures. Conservative-only (institution RW >= central-bank RW) and permissive ('may'), so no capital understatement is possible. N/A under PS1/26 (provision left blank).
  - _Fix:_ Optionally add an is_minimum_reserves boolean routed to CGCB treatment on the CRR arm; low priority given the permissive wording and CRR sunset.
  - _Files:_ `risk_weights.py`, `schemas.py`
- **P1.286** [🟡 LOW] · **CRR Art. 119(5)-(6) / PS1/26 Art. 119 (provision not in PRA Rulebook)** (b31) · effort S
  - _Gap:_ Under PS1/26 the CRR Art. 119(5) rule treating comparably-regulated financial institutions as institutions was NOT carried into the PRA Rulebook (ps126app1.pdf p.40: paras 5-6 '[Note: Provision not in PRA Rulebook]'); consistent with CRE20.40, non-bank financial institutions not meeting the institution definition should be weighted as corporates under Basel 3.1.
  - _Evidence:_ entity_type_to_sa_class and entity_type_to_irb_class map 'financial_institution' -> INSTITUTION regime-invariantly (rulebook/packs/common.py:711 and :753, comment 'Regime-invariant base'). Under B31 a tagged non-bank FI therefore receives institution ECRA/SCRA weights (CQS2 30% vs corporate 50%; CQS3 50% vs 75%; unrated SCRA-A 40% vs corporate 100%) — potential understatement. Under CRR the mapping is correct provided input tagging respects the Art. 119(5) comparability condition (documented at data/schemas.py:416)
  - _Fix:_ Verify the PS1/26 glossary scope of 'institution'; if confirmed narrower, make the financial_institution mapping regime-sensitive (B31 overlay maps it to CORPORATE, or gate on a cited pack Feature) and document the CRR-only comparability condition in the schema contract.
  - _Files:_ `common.py`, `schemas.py`

### WS8 — SA other classes (CIU, defaulted, ECAI seniority/currency)
_11 findings (0 high, 6 medium, 5 low)_

- **P1.256** [🟠 MED] · **PS1/26 Art. 127 vs Art. 133(5) / Art. 112 Table A2** (b31) · effort M
  - _Gap:_ The PS1/26 exposure-class waterfall (Art. 112 Table A2) ranks subordinated debt/equity/own-funds instruments (priority 3) above exposures in default (priority 5); a defaulted subordinated debt instrument therefore keeps the Art. 133(5) 150% RW, not the Art. 127 provision-based RW.
  - _Evidence:_ risk_weights.py:1526-1527 carves only HIGH_RISK out of the defaulted override ('Art. 128 (HIGH_RISK) takes precedence per Table A2 priority 4 > 5'); the subordinated-debt 150% branch (:1044-1052) is a when-chain branch that _apply_defaulted_risk_weight overwrites at :1529-1533. A defaulted subordinated corporate/institution instrument with provisions >= 20% of gross outstanding is re-weighted to 100% instead of 150% — an understatement, and defaulted sub-debt plausibly carries >= 20% provisions.
  - _Fix:_ Under the B31 feature, extend the defaulted-override exclusion to rows with seniority=='subordinated' on institution/corporate classes (mirroring the HIGH_RISK carve-out), so the Art. 133(5) 150% survives.
  - _Files:_ `risk_weights.py`
- **P1.257** [🟠 MED] · **CRR Art. 127(3)-(4)** (crr) · effort S
  - _Gap:_ Defaulted exposures fully and completely secured by mortgages on residential property (Art. 125) or commercial immovable property (Art. 126) shall be assigned a flat 100% RW on the exposure value remaining after specific credit risk adjustments, regardless of the 20% provision test (crr.pdf p.126, Art. 127(3)/(4)).
  - _Evidence:_ risk_weights.py:1513-1524 (CRR branch of _apply_defaulted_risk_weight) applies the 150%/100% provision-ratio test to ALL defaulted rows; there is no residential/commercial-mortgage carve-out on the CRR path (the RESI-RE 100% carve-out at :1487-1511 is gated behind the B31 `sa_revised_defaulted_treatment` feature). A defaulted RESIDENTIAL_MORTGAGE or COMMERCIAL_MORTGAGE exposure with provisions < 20% therefore gets 150% instead of the mandatory 100% — a conservative but material overstatement on the common case of c
  - _Fix:_ In the CRR branch, before the provision test, assign flat 100% to defaulted rows whose class matches _is_residential_re_class or _is_commercial_re_class (the Art. 125/126 fully-secured routing), keeping the provision-ratio test for all other classes.
  - _Files:_ `risk_weights.py`
- **P1.258** [🟠 MED] · **Art. 132(4) (PS1/26; PRA rules replacing CRR Art. 132)** (both) · effort M
  - _Gap:_ An institution that relies on third-party calculations of a CIU's RWEA (under either the look-through or mandate-based approach) shall multiply the resulting RWEA by a factor of 1.2, unless it has unrestricted access to the detailed calculations (ps126app1.pdf p.63-64, Art. 132(4); identical requirement in the pre-2027 PRA rules that replaced UK CRR Art. 132 per SI 2021/1078).
  - _Evidence:_ engine/equity/calculator.py:129-143 (_append_ciu_branches): the x1.2 `ciu_third_party_calc` multiplier is applied ONLY on the mandate_based branch (:133-138); the look_through branch (:139-140) takes `ciu_look_through_rw` (or the internally aggregated fund RW from _resolve_look_through_rw :362-493) with no multiplier. A fund RW supplied or computed from third-party (depositary/management-company) calculations under the LTA is recognised 20% too low — most banks' fund look-through data is exactly such third-party ou
  - _Fix:_ Apply the same ciu_third_party_calc-gated 1.2 multiplier on the look_through branch (and optionally add an `unrestricted_access` input flag for the PS1/26 Art. 132(4) derogation).
  - _Files:_ `calculator.py`
- **P1.259** [🟠 MED] · **PS1/26 Art. 138(1)(g) + Art. 139(6)** (b31) · effort M
  - _Gap:_ From 1 Jan 2027, an institution shall not use a credit assessment that incorporates assumptions of implicit government support to risk-weight an exposure to an institution (unless the rated institution is publicly owned/sponsored); Art. 139(6) adds a higher-of rule when only support-tainted issue-specific assessments exist (CRE21.13-21.15).
  - _Evidence:_ RATINGS_SCHEMA (src/rwa_calc/data/schemas.py:634-665) has no field to flag a rating as incorporating implicit government support, and grep for any implicit-support concept in src/ returns nothing in the ratings path (only the unrelated equity is_government_supported at schemas.py:691). The Art. 138 resolution (engine/stages/hierarchy/ratings.py:103-140) and the B31 institution branches (engine/sa/risk_weights.py:621-689) therefore accept support-inflated bank ratings unfiltered, understating institution RW relative
  - _Fix:_ Add rating_incorporates_government_support (Boolean, default False) plus an is-publicly-sponsored counterparty flag; under a b31 pack Feature, exclude flagged ratings from the Art. 138 resolution for institution obligors (falling to SCRA), and implement the Art. 139(6) higher-of comparison for issue-specific ratings.
  - _Files:_ `schemas.py`, `ratings.py`, `risk_weights.py`
- **P1.260** [🟠 MED] · **CRR Art. 139(2) (PS1/26 Art. 139(2)/(2A))** (crr) · effort M
  - _Gap:_ An issuer (general) credit assessment may only be used to derive a LOWER risk weight for an unrated item if the exposure ranks pari passu or senior in all respects to senior unsecured exposures of the issuer; otherwise the exposure is treated as unrated (Art. 139(2)(b)).
  - _Evidence:_ attach_counterparty_rating (engine/stages/hierarchy/enrich.py:105-155) joins the Art. 138-resolved counterparty CQS onto every exposure row unconditionally; the exposure-level seniority column exists (schemas.py:176, values senior/subordinated) but is consumed only by FIRB LGD selection (engine/crm/collateral.py:1047) and the B31 sub-debt 150% override (engine/sa/risk_weights.py:1045-1052). Under CRR (no sub-debt class) a subordinated exposure to a CQS1-rated corporate gets 20% from the Art. 122 table instead of th
  - _Fix:_ In the CRR SA arm, null the CQS (treat as unrated) for rows where seniority='subordinated' and the CQS-table RW would be lower than the class's unrated RW — i.e. only allow issuer-rating inference downward for pari-passu/senior exposures, mirroring the existing Art. 139(2B) CQS-nulling pattern at risk_weights.py:938-948.
  - _Files:_ `enrich.py`, `risk_weights.py`
- **P1.261** [🟠 MED] · **CRR Art. 141 / PS1/26 Art. 141** (both) · effort M
  - _Gap:_ A credit assessment referring to a domestic-currency item of the obligor cannot be used for a foreign-currency exposure to that obligor (CRR); PS1/26 tightens to strict bidirectional matching (FC ratings only for FC exposures, DC ratings only for DC exposures), with an MDB participation / convertibility-guarantee exception (Art. 141(3)).
  - _Evidence:_ RATINGS_SCHEMA (src/rwa_calc/data/schemas.py:634-665) carries no rating-denomination-currency field, so the Art. 138 resolution and attach_counterparty_rating apply one CQS to all of an obligor's exposures regardless of original_currency. A sovereign/corporate rated on its local-currency scale (typically better than the FC rating) therefore drives the RW of FX exposures — non-conservative for the classic EM-sovereign LC/FC split. The only Art. 141 citation in code (engine/eu_sovereign.py:47) actually implements Art
  - _Fix:_ Add rating_currency_scope (e.g. 'domestic'/'foreign'/'all', default 'all' to preserve legacy behaviour) to RATINGS_SCHEMA; resolve best external CQS per scope in build_rating_inheritance_lazy and select per exposure by comparing original_currency to the obligor's domestic currency, honouring the MDB-participation exception; also move the Art. 141 @cites off build_eu_domestic_currency_expr.
  - _Files:_ `schemas.py`, `ratings.py`, `eu_sovereign.py`
- **P1.287** [🟡 LOW] · **PS1/26 Art. 132(6) (and PRA-rules equivalent under CRR)** (both) · effort S
  - _Gap:_ The RWEA of a CIU's exposures calculated under the look-through or mandate-based approach shall be capped at the fall-back approach amount (1,250%) (ps126app1.pdf p.64, Art. 132(6)).
  - _Evidence:_ equity/calculator.py:133-140 — the mandate branch computes `ciu_mandate_rw.fill_null(12.5) * 1.2` with no cap (null mandate RW + third-party flag yields RW 15.0 > 12.5), and the look-through RW from the Art. 132a leverage adjustment (weighted_sum / fund_nav, :460-477) can also exceed 12.5 for highly leveraged funds. Overstates RWA (conservative-only) in edge cases.
  - _Fix:_ Clip the mandate-based and look-through CIU RW expressions at CIU_FALLBACK_RW (12.5) after the third-party multiplier.
  - _Files:_ `calculator.py`
- **P1.288** [🟡 LOW] · **Art. 134(4) (CRR and PS1/26, identical)** (both) · effort S
  - _Gap:_ Gold bullion held in own vaults or on an allocated basis receives 0% only 'to the extent backed by bullion liabilities'; unbacked gold takes the 100% other-items weight.
  - _Evidence:_ risk_weights.py:1176-1180 (B31) and :1348-1352 (CRR) assign the 0% other_cash RW to entity_type in ['other_cash','other_gold'] unconditionally (pack other_items_gold_rw, common.py:423-427); there is no bullion-liability-backing input or proportioning, so unbacked proprietary gold positions are risk-weighted 0% instead of 100% — an understatement contingent on input usage.
  - _Fix:_ Add a `bullion_liability_backed_value` input (or boolean) and weight only the backed portion at 0%, defaulting unbacked gold to the 100% other-items RW; at minimum document that suppliers must only tag backed gold as other_gold.
  - _Files:_ `risk_weights.py`, `common.py`
- **P1.289** [🟡 LOW] · **Art. 134(7) (CRR and PS1/26, identical)** (both) · effort S
  - _Gap:_ Residual value of leased assets: RWEA = 1/t x 100% x residual value where t is the greater of 1 and the NEAREST NUMBER OF WHOLE YEARS of the lease remaining (crr.pdf p.131; ps126app1.pdf p.68).
  - _Evidence:_ risk_weights.py:1186-1187 (B31) and :1358-1359 (CRR) compute `1.0 / residual_maturity_years.fill_null(1.0).clip(lower_bound=1.0)` — fractional years, not nearest-whole-year rounding. For 2.4y remaining the rule requires t=2 (RW 50%) but the code gives 41.7% (understates); for 2.6y the code gives 38.5% vs required 33.3% (overstates). Small, both-direction misstatement on a niche asset class.
  - _Fix:_ Round residual_maturity_years to the nearest whole year before the 1/t division: `1.0 / residual_maturity_years.round(0).clip(lower_bound=1.0)`.
  - _Files:_ `risk_weights.py`
- **P1.290** [🟡 LOW] · **Art. 134(6) (CRR and PS1/26, identical)** (both) · effort S
  - _Gap:_ Where an institution provides nth-to-default credit protection on a basket, the RWs of the basket exposures (excluding the n-1 lowest-RWEA exposures) are aggregated up to a 1,250% maximum and multiplied by the protection nominal (crr.pdf p.131 [F78]; ps126app1.pdf p.67-68).
  - _Evidence:_ No implementation or input representation exists: grep for nth/basket across src/rwa_calc finds no sold-basket-protection branch, and neither the SA ladders (risk_weights.py:1175-1189, 1347-1361 Other Items) nor any input schema (data/schemas.py) can express a sold nth-to-default basket. Firms writing such protection cannot be capitalised by the engine at all (silent omission rather than misstatement of a computed number).
  - _Fix:_ Either implement an Art. 134(6) input (basket reference, n, member RWs, protection nominal) with the aggregation formula, or document the exclusion as an explicit scope limitation with a validation error when such positions are supplied.
  - _Files:_ `risk_weights.py`, `schemas.py`
- **P1.291** [🟡 LOW] · **CRR Art. 138 / PS1/26 Art. 138(2)** (both) · effort S
  - _Gap:_ An institution shall use solicited credit assessments; unsolicited assessments may only be used if the ECAI's unsolicited ratings are confirmed not to differ in quality (and, under PS1/26, the ECAI has not used them to pressure the entity).
  - _Evidence:_ is_solicited is declared on RATINGS_SCHEMA (src/rwa_calc/data/schemas.py:643, default True) but a src-wide grep shows it is read nowhere — the Art. 138 resolution (engine/stages/hierarchy/ratings.py:109-119) includes unsolicited rows with no filter, DQ warning, or audit note. rating_is_inferred (schemas.py:661) is similarly dormant. Direction of misstatement is data-dependent; mainly an eligibility/audit-trail hole since the confirmation condition is firm governance.
  - _Fix:_ Either consume the flag (config switch unsolicited_ratings_eligible, default True; when False exclude is_solicited=False rows from per_agency_latest and emit a DQ warning) or remove the dead column so the schema does not advertise unimplemented behaviour.
  - _Files:_ `schemas.py`, `ratings.py`

### WS9 — SA retail & real-estate
_6 findings (0 high, 2 medium, 4 low)_

- **P1.262** [🟠 MED] · **Art. 124E (PS1/26)** (b31) · effort M
  - _Gap:_ PS1/26 Art. 124E treats a real-estate exposure as materially dependent on cash flows generated by the property BY DEFAULT, with enumerated exceptions (primary residence, natural person within the three-property limit, social housing, cooperative, etc.). Materially dependent exposures must take the Art. 124G/124I whole-loan tables, not the 124F/124H loan-split.
  - _Evidence:_ The engine derives has_income_cover as: explicit collateral is_income_producing flag (schema default FALSE - data/schemas.py:521; hierarchy join enrich.py:488, coalesce default False at enrich.py:533-535) OR natural-person >3 properties (classify/attributes.py:456-487). So the engine default when the firm supplies no dependence data is NOT materially dependent, which routes to the preferential 20% loan-split (b31_risk_weight_tables.py:556) instead of the 30-105% Table 6B / 100-110% CRE bands. Only one of the Art. 1
  - _Fix:_ Under the B31 pack, treat a null/absent is_income_producing on RE-collateralised exposures as materially dependent unless an engine-verifiable exception fires (natural person <=3 properties, or an explicit not-dependent attestation column), and emit a DQ warning when the flag is defaulted. Keep the current behaviour under CRR.
  - _Files:_ `enrich.py`, `attributes.py`, `schemas.py`
- **P1.263** [🟠 MED] · **Art. 126 (CRR)** (crr) · effort M
  - _Gap:_ CRR Art. 126(2)(b): the 50% CRE risk weight applies only where the risk of the borrower does NOT materially depend on the performance of the property/project, i.e. repayment capacity comes from other sources; Art. 126(3)-(4) allow waiving (b) only where published loss-rate evidence exists (not exercised broadly in the UK). Art. 126 contains no rental-income-coverage test.
  - _Evidence:_ src/rwa_calc/engine/sa/risk_weights.py:782-788 grants the preferential 50% blend when has_income_cover=True and 100% otherwise - the opposite direction of Art. 126(2)(b). has_income_cover is sourced from collateral is_income_producing (engine/stages/hierarchy/enrich.py:488) or, on the split path, a >=1.5x rental_to_interest_ratio test (engine/stages/re_split/flagging.py:157-160, gated by pack Feature sa_re_split_cre_rental_coverage_required, packs/crr.py:243-247); splitter-emitted CRR CRE secured rows force has_inc
  - _Fix:_ Split the semantics: model Art. 126(2)(b) as a non-dependence condition (default: preferential 50% NOT available when the exposure is income-producing), and only allow the rental-coverage route if the firm elects an Art. 126(3)-style derogation via config. Rename/duplicate has_income_cover so the CRR gate and the B31 material-dependence flag are not the same column with inverted meanings, and fix 
  - _Files:_ `risk_weights.py`, `flagging.py`, `splitter.py`
- **P1.292** [🟡 LOW] · **Art. 124A (PS1/26)** (b31) · effort S
  - _Gap:_ PS1/26 Art. 124A: the preferential Art. 124F-124I treatments apply only to exposures meeting the regulatory real-estate qualifying criteria (finished property, legal enforceability/first charge, prudent valuation, documentation); non-qualifying RE routes to Art. 124J (150% income-dependent / counterparty RW / max(60%, cp RW)).
  - _Evidence:_ is_qualifying_re has no default in the collateral schema (data/schemas.py:524, nullable) and the SA router treats null as qualifying: risk_weights.py:605 'is_non_qualifying = pl.col("is_qualifying_re").fill_null(True) == False'; the hierarchy-side Art. 124(4) trigger re_collateral_non_qualifying likewise fill_null(False) (re_split/flagging.py:165). A firm that never populates the Art. 124A assessment gets 124F/124H preferential weights on every RE exposure - an anti-conservative default on missing data (contrast wi
  - _Fix:_ Emit a DQ warning (and optionally a config switch) when is_qualifying_re is null on B31 RE-classed rows; consider defaulting null to non-qualifying under the B31 pack, or at minimum document the input contract that null means the firm has positively assessed Art. 124A compliance.
  - _Files:_ `risk_weights.py`, `schemas.py`, `flagging.py`
- **P1.293** [🟡 LOW] · **Art. 123 (PS1/26)** (b31) · effort S
  - _Gap:_ PS1/26 Art. 123: the 45% risk weight applies to QRRE transactor exposures - the obligor must first meet the qualifying revolving retail criteria (revolving facility, aggregate facility limit within the QRRE cap, regulatory-retail qualification) and the 12-month full-repayment transactor behaviour.
  - _Evidence:_ risk_weights.py:577-581 applies 45% to ANY exposure whose class contains 'RETAIL' with the raw input flag is_qrre_transactor=True; it is not gated on the RETAIL_QRRE classification the engine itself computes (classify/subtypes.py:122-138: revolving + obligor aggregate <= qrre_max_limit), and the branch precedes the non-regulatory-retail 100% branch (lines 586-590). Impact is limited because non-qualifying retail is reclassified to CORPORATE upstream, but a mis-flagged non-revolving or over-QRRE-limit retail row rec
  - _Fix:_ Gate the 45% branch on exposure_class == RETAIL_QRRE (or on the engine-computed is_qrre predicate) rather than any RETAIL class, and emit a DQ warning when is_qrre_transactor=True on a non-QRRE row.
  - _Files:_ `risk_weights.py`, `subtypes.py`, `schemas.py`
- **P1.294** [🟡 LOW] · **Art. 124/125 (CRR)** (crr) · effort S
  - _Gap:_ CRR Art. 124(1): the part of the exposure exceeding the fully-and-completely-secured portion shall be assigned the risk weight applicable to the UNSECURED exposures of the counterparty - 75% only if the obligor qualifies as retail under Art. 123, otherwise 100%.
  - _Evidence:_ For whole-loan RETAIL_MORTGAGE/RESIDENTIAL_MORTGAGE rows with LTV > 80%, risk_weights.py:790-801 blends 35% x (0.80/LTV) with a HARD-CODED 75% (pack crr.py:1008-1010 resi_rw_high) on the excess, without checking qualifies_as_retail. An individual whose non-RRE-secured aggregate exceeds EUR 1m (so the excess should carry the 100% unsecured RW) still gets 75% on the excess - a small under-statement. The CRE branch does this correctly via the Art. 122 CQS lookup (lines 774-778), and the physical splitter path is also 
  - _Fix:_ Replace the fixed 75% excess weight with a conditional: 75% when qualifies_as_retail else 100% (or the counterparty CQS RW), mirroring the CRE residual lookup.
  - _Files:_ `risk_weights.py`, `crr.py`
- **P1.295** [🟡 LOW] · **Art. 126 (CRR)** (crr) · effort S
  - _Gap:_ Art. 126(2)(d) proportion split: 50% on the part of the loan up to 50% of market value, counterparty unsecured RW on the excess. The spec should reflect the implemented state.
  - _Evidence:_ docs/specifications/crr/sa-risk-weights.md:1046-1051 carries an open 'Code Divergence (D3.36)' bug note claiming the calculator implements a binary whole-loan Art. 126 treatment (100% on the whole exposure when LTV > 50%). The code now implements the proportion split: risk_weights.py:766-788 computes cre_secured_share = min(1, 0.50/LTV) and blends 50% with the Art. 122 CQS residual RW. The spec note is stale audit trail - no calculation impact.
  - _Fix:_ Close/remove the D3.36 divergence note in the spec and describe the implemented proportion-split behaviour.
  - _Files:_ `sa-risk-weights.md`, `risk_weights.py`

### WS10 — SA exposure value / CCF
_5 findings (1 high, 0 medium, 4 low)_

- **P1.217** [🔴 HIGH] · **CRR Art. 111(1) / Annex I items 2(b), 3(b)** (crr) · effort M
  - _Gap:_ CRR Annex I classifies undrawn credit facilities as Medium Risk (50% CCF) when their ORIGINAL maturity exceeds one year, and Medium/Low Risk (20% CCF) only when their ORIGINAL maturity is up to and including one year (verified verbatim: crr.pdf pp.433-434 — 'undrawn credit facilities ... with an original maturity of more than one year' / '... with an original maturity of up to and including one year'). The 50/20 split never changes over the life of the commitment.
  - _Evidence:_ src/rwa_calc/engine/ccf.py:486-501 (_compute_ccf, CRR branch): the OC->20% remap tests REMAINING maturity — `(pl.col("maturity_date").cast(pl.Date) - pl.lit(config.reporting_date)).dt.total_days() <= _OC_SHORT_MATURITY_THRESHOLD_DAYS` (365, IntParam at src/rwa_calc/rulebook/packs/common.py:603-607, itself cited as 'other-commitments <=1yr maturity day boundary'). The code comment at ccf.py:92-94 explicitly says 'remaining-maturity day boundary'. Consequence: a 3-year committed revolver tagged risk_type=OC receives 
  - _Fix:_ In the CRR OC branch of _compute_ccf, derive ORIGINAL maturity — prefer original_maturity_years when present, else (maturity_date - start_date) — and apply the 20% MLR remap only when original maturity <= 1 year; when neither source is available keep the conservative 50% MR default. Re-pin test_sa_pipeline_oc_20_percent_crr_short_maturity to an original-maturity <=1yr case and add a seasoned >1yr-
  - _Files:_ `ccf.py`, `common.py`, `test_ccf.py`
- **P1.265** [🟡 LOW] · **PS1/26 Art. 111(1)(c) (no CRR SA equivalent)** (crr) · effort S
  - _Gap:_ The commitment-to-issue lower-of CCF rule is introduced by PS1/26 Art. 111(1)(c) / BCBS CRE20.101. CRR Annex I has no SA lower-of rule — a commitment to provide guarantees is itself classified by Annex I (e.g. MR 50% if original maturity >1yr).
  - _Evidence:_ src/rwa_calc/engine/ccf.py:524-546: the lower-of cap fires whenever underlying_risk_type is non-empty, with no is_b31 gate — under CalculationConfig.crr() a caller-supplied underlying_risk_type reduces the SA CCF to min(commitment, underlying), e.g. an FR commitment over an LR underlying drops from 100% to 0% under CRR where Annex I provides no such relief. Opt-in only (column absent => no-op), so exposure to the deviation requires the caller to populate a B31-era field on a CRR run.
  - _Fix:_ Gate the lower-of cap on the B31 pack feature (e.g. sa_revised_ccf_table), or document explicitly that populating underlying_risk_type under CRR elects the B31-style treatment.
  - _Files:_ `ccf.py`
- **P1.266** [🟡 LOW] · **CRR Art. 111 / PS1/26 Art. 111 Table A1 (documentation)** (both) · effort S
  - _Gap:_ Specs are the single source of truth (docs/specifications/) and must reflect implemented behaviour.
  - _Evidence:_ docs/specifications/crr/credit-conversion-factors.md:394-404 still carries a 'Not yet implemented' warning block claiming the concrete-product->risk_type derivation (P2.31), the Art. 166E(5) purchased-receivables 40%/10% pathway (P2.32) and the Row 4(b) UK resi-mortgage auto-CCF (P2.33) are missing, but all three are live: build_product_to_risk_type_expr + the obs_product fill (src/rwa_calc/engine/ccf.py:121-147, :443-456, pack CategoryMap common.py:822+), _apply_purchased_receivable_ccf (ccf.py:592-632), and the R
  - _Fix:_ Delete/rewrite the stale warning admonition in the spec to describe the shipped behaviour (obs_product derivation is optional; explicit risk_type wins).
  - _Files:_ `credit-conversion-factors.md`, `ccf.py`
- **P1.267** [🟡 LOW] · **CRR Art. 111(1) / Annex I item 1; PS1/26 Art. 111(1) Table A1 Row 1(f)** (both) · effort S
  - _Gap:_ Under CRR Annex I, unclassified items 'also carrying full risk' belong in the Full Risk bucket (100% CCF); under PS1/26 Table A1, 'any other issued off-balance sheet items that have the character of credit substitutes' get 100% (Row 1(f)) while only residual COMMITMENTS get 40% (Row 5).
  - _Evidence:_ src/rwa_calc/rulebook/packs/common.py:151-155 defines sa_ccf_default = 0.50 ('MR-equivalent fallback for unrecognised risk_type'), applied at src/rwa_calc/engine/ccf.py:207 (.otherwise(pl.lit(_SA_CCF_DEFAULT))). A row whose risk_type string is unrecognised (data-quality failure) is converted at 50% even if the underlying product is a direct credit substitute that should get 100% — a potential understatement, but only on malformed input; well-formed inputs resolve via RISK_TYPE_SYNONYMS or the obs_product map.
  - _Fix:_ Consider a 100% (FR) fallback for unrecognised risk_type plus a DQ error row (the error-accumulation channel already exists), or at minimum emit a DQ warning when the .otherwise() default fires so the 50% assumption is visible in the audit trail.
  - _Files:_ `common.py`, `ccf.py`
- **P1.268** [🟡 LOW] · **CRR Art. 113(6)-(7); PS1/26 Art. 113(6)** (both) · effort S
  - _Gap:_ With prior permission, an institution may assign a 0% risk weight to exposures to its parent, subsidiary, or sister undertakings meeting conditions (a)-(e) (CRR Art. 113(6); IPS members under 113(7)). PS1/26 retains the permission-gated intragroup 0% RW (ps126app1.pdf p.35: 'an institution may with the prior permission of the PRA, assign a risk weight of 0% to the exposures ... to a counterparty which is its parent undertaking, its subsidiary, a subsidiary of its parent undertaking or an undertaking linked by a common management relationship').
  - _Evidence:_ No engine support exists: grep for intragroup/113(6)/113(7) across src/rwa_calc finds only the IRB PPU provenance enum PpuReason.ART_150_1_E/F (src/rwa_calc/domain/enums.py:764-767, COREP row routing only — 'Provenance-only — it does not alter the SA risk weight or RWA') and an unrelated CVA-exemption comment (data/schemas.py:1029). There is no is_intragroup input flag, no CalculationConfig field, and no 0% RW branch in engine/sa/risk_weights.py. A firm holding the Art. 113(6) permission cannot represent it; all in
  - _Fix:_ Add an opt-in per-counterparty flag (e.g. intragroup_zero_rw_permitted on COUNTERPARTY_SCHEMA) plus a config gate, and a 0% RW override branch (ordered before the class RW lookup) in both regime override chains, excluding own-funds-instrument exposures. Conservative-only today, so low priority.
  - _Files:_ `enums.py`, `risk_weights.py`

### WS11 — Citations, docstrings & spec staleness
_2 findings (0 high, 0 medium, 2 low)_

- **P1.269** [🟡 LOW] · **CRR Art. 217** (both) · effort S
  - _Gap:_ The @cites citation index (watchfire matrix) should map articles to the functions that implement them; Art. 217 is the double-default qualification article.
  - _Evidence:_ src/rwa_calc/engine/crm/guarantees.py:1267 — `@cites("CRR Art. 217")` decorates `_apply_maturity_mismatch_to_guarantees`, which implements Art. 238(1)/239(3) maturity mismatch (its own docstring references only Art. 237-239); and guarantees.py:91 cites Art. 217 on `apply_guarantees`, which performs substitution, not DD qualification (the DD logic lives in engine/irb/guarantee.py::_apply_double_default, which carries no Art. 217/202 cite). `uv run watchfire matrix` therefore attributes Art. 217 to the wrong function
  - _Fix:_ Move the Art. 217 cite (and add Art. 202) onto _apply_double_default in engine/irb/guarantee.py; replace the guarantees.py:1267 decorator with @cites("CRR Art. 238")/@cites("CRR Art. 239") if the watchfire index supports them, else drop it.
  - _Files:_ `guarantees.py`, `guarantee.py`
- **P1.296** [🟡 LOW] · **Art. 222(3) with PS1/26 Art. 133** (b31) · effort S
  - _Gap:_ FCSM assigns the collateralised portion the risk weight of a direct exposure to the collateral instrument under the SA chapter; under PS1/26, equity exposures are 250% (400% higher-risk; transitional 160% in 2027), so main-index equity FCSM collateral should carry the B31 equity RW, not the CRR 100%.
  - _Evidence:_ packs/common.py:101-105 pins fcsm_equity_collateral_rw at 100% as regime-invariant, and simple_method.py:150-155 applies it under both regimes with a comment asserting Art. 222(1) prescribes 100% — no such prescription exists in CRR/PS1/26 Art. 222 text (it defers to the Chapter 2 RW). Since apply_fcsm_rw_substitution (sa/rw_adjustments.py:106-116) blends unconditionally whenever FCSM collateral value > 0, using 100% instead of 250% understates the blended RW under B31 whenever equity collateral is present. Require
  - _Fix:_ Move fcsm_equity_collateral_rw into the regime packs (CRR 1.00, B31 2.50 with the Art. 4.2 transitional schedule) or derive it from the regime's equity RW table; alternatively verify the PRA text and document the 100% position with a citation to the actual paragraph.
  - _Files:_ `common.py`, `simple_method.py`
---

## 6. Already-tracked gaps (48) — no new P-code

Every gap below was independently surfaced by this audit **and** is already recorded in `IMPLEMENTATION_PLAN.md` or a `docs/plans/` file. They are listed so the coverage is provably complete; no new P-code is proposed. Where the tracked item is in the *Completed Items* list, the audit re-confirmed it as fixed.

| Tracked ref | Article(s) | Regime | Sev | Audit finding |
|---|---|---|---|---|
| **P1.208** | CRR Art. 111(1) (with Art. 110(1)/62(c)); PS1/26 Art. 111 unchanged | both | high | art111-gcra-included-in-sa-provision-deduction |
| **P6.44** | CRR Art. 111(1)(a)-(b) | both | low | art111-provision-citation-111-2-vs-111-1 |
| **P4.51** | CRR Art. 112(f)/(k) | both | low | art112-enum-docstring-subpoint-typos |
| **P2.47** | CRR Art. 121(1)-(2) | crr | high | art121-crr-unrated-institution-sovereign-derived |
| **P2.47** | CRR Art. 136 (PS1/26: provision not in PRA Rulebook) | both | low | art136-grade-string-cqs-map |
| **P5.13** | Art. 124A-124L (PS1/26) | b31 | low | b31-re-acceptance-test-gap |
| **P2.51** | Art. 132(5)/132A(1) (PS1/26) and PRA-rules equivalent under CRR | both | medium | art132-nested-ciu-holding-default-rw |
| **P7.5** | PS1/26 Art. 150(1)(e)/(k)/(l), 150(1A), 150(4) | b31 | low | art150-ps126-ppu-vocabulary |
| **P7.5** | CRR Art. 166(3) (via Art. 219) / PS1/26 Art. 166A(3) | both | low | art166-3-onbs-netting-absent |
| **P7.5** | CRR Art. 197(4); PS1/26 Art. 197(4) | both | low | art197-4-unrated-institution-debt-route |
| **P7.5** | CRR Art. 214 / Art. 215(2) | both | low | art214-215-counter-guarantees-not-modelled |
| **P7.5** | Art. 222(5) (PS1/26 Art. 222) | both | low | art222-otc-derivative-carveout-missing |
| **P7.4** | CRR Art. 157(2)-(5) / PS1/26 Art. 157 | both | low | art157-dilution-maturity-one-year |
| **P7.4** | CRR Art. 152 / PS1/26 Art. 132-132C | both | low | art152-ciu-irb-look-through-sa-only |
| **P7.4** | CRR Art. 166(6) / PS1/26 Art. 166A(5) | both | low | art166-6-dilution-capital-not-deducted |
| **P1.203** | CRR Art. 153(3) with Art. 202 | crr | medium | art153-3-double-default-eligibility-gates |
| **P1.203** | CRR Art. 202 (PS1/26: provision left blank — double default removed) | crr | medium | art202-double-default-provider-gates |
| **P1.203** | CRR Art. 217 (with Art. 202) | crr | medium | art217-dd-eligibility-set |
| **P1.204** | Art. 153(5) (PS1/26) | b31 | medium | art153-5-b31-slotting-short-maturity-election |
| **P1.209** | Art. 158(6A) (PS1/26) with Art. 159 | b31 | medium | art158-6a-pma-el-not-fed-to-shortfall |
| **P1.209** | PS1/26 Art. 158(6A) / Art. 159 | b31 | medium | art159-pma-el-grossup-bypass |
| **P1.205** | CRR Art. 155(3) with Art. 165(1) | crr | low | art155-crr-equity-009-pd-floors-unreachable |
| **P1.205** | CRR Art. 165(1)(a)-(b) | crr | low | art165-equity-009-floors-unreachable |
| **P1.206** | CRR Art. 155(3) with Art. 165(2) | crr | low | art155-crr-pdlgd-diversified-flag-ignored |
| **P1.206** | CRR Art. 165(2) | crr | low | art165-equity-diversified-lgd-flag |
| **P1.207** | Art. 133(3)-(4) (PS1/26, successor to Art. 155 for equity) | b31 | low | art133-b31-speculative-flag-bypass |
| **P2.37** | CRR Art. 155(4) | crr | low | art155-4-internal-models-approach-absent |
| **P1.183** | CRR Art. 164(4)-(5) | crr | high | art164-crr-portfolio-avg-lgd-floors |
| **P1.210** | CRR Art. 159 (third sentence) / PS1/26 Art. 159(3) | both | medium | art159-gcra-scra-not-split |
| **P2.50** | PS1/26 Art. 163(1)(b)-(c) | b31 | low | art163-b31-nonuk-rre-pd-floor |
| **P2.52** | CRR Art. 159 / PS1/26 Art. 159 | both | low | art159-purchased-default-discount |
| **P6.40** | CRR Art. 163 / PS1/26 Art. 163(1) | b31 | low | art163-stale-pd-floor-docstrings |
| **P1.201** | CRR Art. 204(1) with valuation at Art. 233(2); PS1/26 Art. 204/233(2) | both | medium | art204-233-restructuring-60pct-cap-and-pct-coverage |
| **P1.201** | CRR Art. 216(1)(a)(iii) / Art. 233(2)(b) | both | medium | art216-restructuring-60pct-cap |
| **P1.201** | Art. 233(2)(b) CRR; PS1/26 Art. 233(2)(b) | both | medium | art233-cds-60pct-cap-missing |
| **P1.199** | CRR Art. 197(5)-(6) / Art. 198(1)(b); PS1/26 Art. 197(5)-(6) / 198(1)(b) | both | medium | art197-5-ciu-collateral-misbucket |
| **P1.199** | Art. 224(with Art. 197(5)-(6)) CIU collateral | both | medium | art224-ciu-collateral-look-through |
| **P1.202** | CRR Art. 216(1)(a)(iii) / Art. 233(2) | both | medium | art216-restructuring-haircut-pct-skip |
| **P1.202** | Art. 233(2) CRR; PS1/26 Art. 233(2) | both | medium | art233-restructuring-pct-covered-skip |
| **P1.10** | CRR Art. 213 (+PS1/26 Art. 213 & Rule 4.11) | both | medium | art213-eligibility-conditions-unvalidated |
| **P1.198** | PS1/26 Art. 230(1)(b) / 231(1)(b) | b31 | medium | art230-b31-nonfinancial-fx-haircut |
| **P6.27** | Art. 230-231 waterfall (both regimes) | both | low | art231-sequential-fill-numeric-drift |
| **P5.16** | Art. 234 CRR; PS1/26 Art. 234 | both | medium | art234-tranching-no-chapter5 |
| **P1.178** | Art. 236 CRR; PS1/26 Art. 236 PSM | both | medium | art236-external-rated-guarantor-sa-rw-on-irb |
| **docs/plans/margined-sft-fccm-extension.md** | CRR Art. 166(2) (via Art. 220) / PS1/26 Art. 166B(1) | both | low | art166-2-sft-mna-single-ns-exposure |
| **docs/plans/margined-sft-fccm-extension.md** | CRR Art. 196 (+ Art. 220); PS1/26 Art. 196 | both | low | art196-mna-single-trade-only |
| **margined-sft-fccm-extension.md** | Art. 224 / Art. 220 (PS1/26 Art. 224 Tables 1-4) | b31 | high | sft-fccm-b31-uses-crr-haircuts |
| **margined-sft-fccm-extension.md** | Art. 220(3) (PS1/26 Art. 220) | both | low | art220-multi-trade-netting-gross-haircuts |
---

## 7. Refuted candidate findings (3) — investigated & dismissed

Three candidate findings were raised by the first-pass auditors and **dismissed** under adversarial verification (regulation + code lenses). They are recorded here so they are not re-raised.

### ❌ art114-7-third-country-scope-and-b31-basis — Art. 114(7) (CRR; PS1/26 successor unstated)
- **Claimed gap:** UK CRR Art. 114(7) (crr.pdf p.113): institutions MAY apply a third country's lower domestic-currency CGCB risk weight where the Treasury has determined equivalence. PS1/26 Art. 114 carries only paras (1)-(4) into the rulebook; para 7 is marked '[Provision not in PRA Rulebook]' (ps126app1.pdf p.36).
- **Why dismissed:** The finding's material limb rests on a false reading of PS1/26: PRA Rulebook Article 114(1)(b) (ps126app1.pdf, PRA2026/1 p.35) explicitly lists 'Article 114(7) of CRR' as an applicable CGCB treatment, and the Article 112 table row (11) (p.34) repeats the cross-reference — the same surviving-CRR pattern as 'Article 115(4) of CRR' and 'Article 116(5) of CRR' the finding cites as the contrast — so the engine's regime-invariant B31 0% (src/rwa_calc/rulebook/packs/common.py:779, engine/eu_sovereign.p

### ❌ art129-crr-unrated-cb-issuer-fallback — CRR Art. 129(5) with Art. 121
- **Claimed gap:** Unrated covered bonds take a RW derived from the issuer's senior unsecured RW; for an issuer with no own ECAI rating that RW is the Art. 121 Table 5 sovereign-derived weight (e.g. UK sovereign CQS1 -> institution 20% -> CB 10%), not a flat 100%.
- **Why dismissed:** The CB fallback at risk_weights.py:465-475 faithfully derives the covered-bond weight FROM the issuer's senior-unsecured RW, exactly as Art. 129(5) requires. The codebase deliberately assigns an unrated CRR institution's senior-unsecured RW a flat 100% (Art. 121 fallback), a settled P1.149 decision pinned by passing tests (tests/unit/crr/test_crr_institution_standard.py:165-195, :425-441 "Falls through to Table 5 fallback (100%)") and cited in packs/crr.py:885-899 to Art. 120; the sovereign-deri

### ❌ art232-third-party-cash-and-repurchasable — Art. 232(1) and 232(4) (PS1/26 retained)
- **Claimed gap:** Cash on deposit with (or cash-assimilated instruments held by) a third-party institution may be treated as a guarantee by that institution (Art. 232(1)); third-party instruments repurchasable on request (Art. 200(1)(c)) may be treated as a guarantee by the issuing institution (Art. 232(4)) — both ro
- **Why dismissed:** Art. 232(1)/(4) are "may be treated as a guarantee by the [third-party/issuing] institution" provisions — they reclassify third-party cash and repurchase-on-request instruments as UNFUNDED protection, not funded collateral, so the finding grepped the wrong chain (collateral/haircuts). The prescribed routing (Art. 235 RW-substitution for SA, Art. 236 parameter substitution for IRB) is fully implemented: src/rwa_calc/engine/sa/rw_adjustments.py:154-166 apply_guarantee_substitution substitutes the 

---

## 8. Audit provenance

- **Auditors:** 14 article-group agents (SA exposure value, sovereigns, inst/corp, retail/RE, other classes, ECAI, IRB scope, IRB RW, IRB EL/params, IRB EAD, CRM eligibility, CRM requirements, CRM funded-calc, CRM unfunded/MM).
- **Verification:** every new finding challenged by an independent regulation-lens verifier and a code-lens verifier; a finding survives only if neither refutes it. 3 findings refuted (§7); 1 survived a split verdict (retained as CONFIRMED, code-lens caveat noted inline).
- **Numeric checks:** pack values compared against `docs/assets/crr.pdf` and `docs/assets/ps126app1.pdf` (page refs inline in each finding's evidence) and the `crr`/`basel31` skills.
- **Not in scope of this pass:** CCR/SA-CCR (Art. 274-311), securitisation (Art. 242-270), large exposures, market/operational risk, and reporting-template population (COREP/Pillar III) except where a CRM/SA/IRB calculation feeds them.
- **Machine-readable finding set** (81 findings + coverage + tracked + refuted) retained for this session; workflow run id `wf_98a9ab68-e06`.
