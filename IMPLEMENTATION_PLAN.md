# Implementation Plan

**Last updated:** 2026-05-03 (curator audit pass — P1.99 / P1.121 / P1.132 confirmed silently fixed and closed; P1.131 closed-claim-invalid; P1.94(c) sub-claim invalidated; P1.118 re-scoped; structural file:line drift surfaced; P4.2 re-scoped to include pyproject version).

**Status (2026-05-03):** ~165 open items remain. Same-day curator changes: (a) **silent fixes detected and closed**: P1.99 (CRR Art. 120 Table 4 short-term rated institution — implemented at `engine/sa/namespace.py:487-494` via `INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR`), P1.121 (CRR Art. 121(3) unrated institution short-term — wired at `engine/sa/namespace.py:498-499` via `INSTITUTION_SHORT_TERM_UNRATED_RW_CRR`), P1.132 (B31 government-supported equity — `data/tables/b31_equity_rw.py:44` already shows `Decimal("2.50")` not `1.00`); (b) **closed-claim-invalid**: P1.131 (`pipeline.py:318` uses `dataclasses.replace(result, errors=…)` which preserves all other fields, so `output_floor_summary` is **not** dropped — claim was wrong when filed); (c) **re-scoped**: P1.94 sub-claim (c) removed (auto-detection via `borrower_income_currency` vs `currency` IS implemented at `engine/sa/namespace.py:1606`; the `currency_mismatch_unhedged` flag the bullet referenced does not exist anywhere in the source tree), P1.118 partially-implemented (the `has_one_day_maturity_floor` flag IS consulted by `_maturity_adjustment_expr_from_pd` at `engine/irb/formulas.py:705-707`, suppressing the 1y M floor — remaining gap is M=2.5 default for qualifying short-term exposures without the flag); (d) **structural drift**: `engine/sa/calculator.py` is now 327 lines; the bulk of SA logic moved to `engine/sa/namespace.py` (1,752 lines). All `sa/calculator.py:14xx-17xx` line refs in P1.93–P1.130 / P2.x bullets are stale — most live in `sa/namespace.py` now. Re-scoped en-masse via this header note rather than per-bullet (file:line still discoverable via grep on the named function).

**Package version:** 0.2.6 (pyproject.toml — corrected from 0.1.202 in prior plan header) | **Test suite:** 5,329 selectable (5,329 total, 11 deselected benchmarks)
**Test run (2026-04-11):** 5,207 passed, 21 skipped (conditional fixture guards), 11 deselected (benchmarks)
**CRR acceptance:** 100% (169 tests) | **Basel 3.1 acceptance:** 100% (212 tests) | **Comparison:** 100% (60 tests) | **Stress:** 56 tests (+ 4 slow)
**Unit:** 4,397 | **Contract:** 145 | **Integration:** 122 | **Acceptance:** 497 selectable
**Acceptance tests skipped at runtime:** 21 (all conditional fixture-data guards — B31 FIRB 8, CRR FIRB 7, B31 CRM 7, provisions 15, output floor 4, stress 2; no unconditional skips)
**Source code TODO/FIXME/HACK count:** 1 — `engine/hierarchy.py:2034` `# TODO(qrre-coupling): also set in _undrawn_select_expressions; consolidate.` (newly surfaced 2026-05-03 audit; tracked as P6.26).

---

## Remaining Work — Prioritized Bullet List

Items are sorted by priority. Each item notes its ID, status, and effort estimate (S/M/L).

### Tier 1 — Calculation Correctness (must fix for regulatory accuracy)

- **P1.93** [ ] **NEW** — FCSM Art. 222(4) SFT zero-haircut 0%/10% exception not implemented. SFTs meeting Art. 227 zero-haircut conditions should get 0% RW (or 10% if counterparty is not a core market participant per Art. 227(3)). Art. 222(6) same-currency cash/sovereign 0% also not gated. No `is_core_market_participant` field in schema. **Effort: M** | Ref: PRA PS1/26 Art. 222(4)/(6), Art. 227(3)
- **P1.94** [~] **PARTIAL (150% cap fixed v0.1.192; auto-detection now wired; remaining gaps open)** — B31 currency mismatch 1.5x capped at 150% (`engine/sa/namespace.py:1613` `.clip(upper_bound=pl.lit(1.50))` per Art. 123B). Auto-detection from `borrower_income_currency`/`cp_borrower_income_currency` vs `currency` is implemented at `engine/sa/namespace.py:1582-1606` — the previously-cited `currency_mismatch_unhedged` flag does not exist in the source tree. Sub-claim (c) closed-claim-invalid 2026-05-03. Remaining work:
  - (a) `is_hedged` flag missing from schema (no `is_hedged` field anywhere in `src/rwa_calc/`); the multiplier fires whenever `borrower_income_currency != currency`, regardless of whether the exposure is FX-hedged. **Effort: S**.
  - (b) 90%-coverage hedge test (Art. 123B(2)) not implemented.
  - ~~(c) Auto-detection missing~~ — closed-claim-invalid (auto-detection is implemented; see header).
  - (d) Revolving-facility instalment rule (Art. 123B(2A)) not implemented.
  - (e) Pre-2027 portfolio fallback (Art. 123B(3)) not implemented.
  - (f) Scope check too broad — `engine/sa/namespace.py:1598-1604` `_uc.str.contains("COMMERCIAL")` catches all CRE (and `_uc.str.contains("CRE")`), including non-RRE commercial real estate; Art. 123B applies only to retail (h) and residential RE (i) exposures.
  - (g) CR5 reporting convention (base RW with multiplied RWEA) missing; OF 02.00 row 0380 memo not populated.
  **Effort: S** | Ref: PRA PS1/26 Art. 123B; `engine/sa/namespace.py:1566-1618`
- **P1.95** [ ] **REVISED** — B31 guarantee substitution uses CQS-based institution RW instead of SCRA grades for unrated institution guarantors. `sa/calculator.py:1569-1578` now applies 40% (B31) or 100% (CRR) for unrated institution guarantors based on `config.is_basel_3_1` (P1.149 fix). Under B31, unrated institutions should use SCRA grades (A→40%, B→75%, C→150%) based on capital-adequacy assessment, not a flat 40% fallback. **Effort: M** | Ref: PRA PS1/26 Art. 121/235
- **P1.96** [~] **DOWNGRADED** — Covered bond collateral haircut falls through to `other_physical` (40% default). `haircuts.py:_normalize_collateral_type_expr` does not recognise `covered_bond`/`covered_bonds` as a distinct collateral type. However, PDF extraction confirms covered bonds are **NOT listed** in PRA PS1/26 Art. 197 as eligible financial collateral for FCCM/FCSM. They only appear in Art. 207(2) (repo exception) and Art. 161(1)(d) (F-IRB LGD 11.25%). Impact is limited to the narrow Art. 207(2) repo scenario where covered bonds are used as collateral. **Effort: S** | Ref: PRA PS1/26 Art. 197, 207(2), 224
- **P1.97** [ ] **NEW** — B31 slotting missing non-HVCRE subgrade maturity differentiation (Art. 153(5)(d)). PRA Table A has columns A/B (Strong) and C/D (Good) with maturity-based subgrades: Strong A=50% (<2.5yr) vs B=70% (>=2.5yr), Good C=70% vs D=90%. Code has no B31 `_SHORT` table variants and `namespace.py:408-416` ignores `is_short` for B31. Art. 153(5)(d) says firms "may" use lower weights — optional but should be supported. Non-HVCRE only; HVCRE subgrades tracked separately as P1.117. **Effort: S** | Ref: PRA PS1/26 Art. 153(5)(d) Table A columns A-D
- **P1.98** [ ] **NEW** — Subordinated corporate A-IRB LGD floor fallback uses 50% instead of 25%. `formulas.py:157-166` applies `floors.subordinated_unsecured` (50%) when `exposure_class` absent and `seniority` contains "sub". Art. 161(5) makes no senior/subordinated distinction — all corporate unsecured = 25%. Only affects fallback path but is regulatory non-compliant. **Effort: S** | Ref: PRA PS1/26 Art. 161(5)
- **P1.100** [ ] **NEW** — Art. 137 ECA score-to-CQS mapping not implemented. Unrated sovereigns with ECA risk scores 0-7 should map to CQS 1-6 per Table 9. No `eca_score` field in schema. Unrated sovereigns default to 100% instead of potentially 0% (ECA 0-1). **Effort: S** | Ref: CRR Art. 137
- **P1.101** [ ] **NEW** — Art. 226(1) non-daily revaluation haircut adjustment not implemented. When collateral is revalued less frequently than daily, supervisory haircuts should be scaled by `sqrt((NR + T_m - 1) / T_m)`. No `revaluation_frequency_days` input field. Understates haircuts for infrequently revalued collateral. **Effort: S** | Ref: CRR Art. 226(1)
- **P1.103** [ ] **NEW** — Art. 122(3) Table 6A short-term corporate ECAI risk weights not implemented. PRA PS1/26 introduces Table 6A: CQS1=20%, CQS2=50%, CQS3=100%, Others=150%. Neither spec nor code references Table 6A. Code falls through to long-term CQS table. **Effort: S** | Ref: PRA PS1/26 Art. 122(3)
- **P1.104** [ ] **NEW** — FCSM Art. 222(7) maturity eligibility check missing. Simple Method requires collateral residual maturity >= exposure residual maturity (no mismatch allowed). `simple_method.py:compute_fcsm_columns()` never checks maturity relationship. Collateral with shorter maturity than exposure is incorrectly recognised. **Effort: S** | Ref: CRR Art. 222(7)
- **P1.106** [ ] **REVISED** — FCSM collateral RW for institution bonds ignores framework differentiation. `simple_method.py:90-91` uses CQS 2-3 = 50% for all institution bonds. Under PRA PS1/26 ECRA (B31), CQS 2 institutions should be 30%, so FCSM-collateralised B31 exposures are over-weighted. CRR CQS 2 correctly 50%. `_derive_collateral_rw_expr()` currently takes `is_basel_3_1` — extend the institution branch to use 30% when B31. **Effort: S** | Ref: PRA PS1/26 Art. 120 ECRA Table 3
- **P1.107** [ ] **NEW** — FCSM collateral RW for B31 corporate CQS 3 bonds uses 100% instead of 75%. `simple_method.py:110-111` gives CQS 3 = 100%. B31 Art. 122 Table 6 gives CQS 3 = 75%. Conservative overstatement. **Effort: S** | Ref: PRA PS1/26 Art. 122(2) Table 6
- **P1.108** [~] **DISPUTED** — CRR 1.06 scaling factor applied to retail IRB exposures. `formulas.py:360` and `namespace.py:488` apply 1.06 to ALL CRR exposure classes including retail. BCBS CRE31.23 (retail formula) has NO 1.06, but **UK-onshored CRR Art. 154(1) text (page 151 of CRR PDF) includes `× 12.5 × 1.06` in the retail formula**. If the UK CRR text is authoritative, the code is CORRECT. Needs PRA legal clarification on whether this is a transcription artefact or intentional UK deviation. B31 unaffected (1.06 removed entirely). Defaulted path at `adjustments.py:83` correctly exempts retail. **Effort: S (if confirmed as bug)** | Ref: CRR Art. 153(1), Art. 154(1), BCBS CRE31.23
- **P1.109** [ ] **NEW** — Art. 237-238 maturity mismatch not applied to unfunded credit protection (guarantees/CDS). `guarantees.py` applies FX haircut but NO maturity mismatch. When guarantee maturity < exposure maturity, Art. 238 requires `GA = G* × (t-0.25)/(T-0.25)` reduction. Art. 237(2) requires ineligibility when residual < 3 months or original < 1 year. **Understates capital** for exposures with short-dated guarantees. **Effort: M** | Ref: CRR Art. 237-238
- **P1.110** [ ] **NEW** — B31 guarantee substitution CQS table uses CRR corporate weights (CQS 3=100%). `sa/calculator.py:1630-1631` maps corporate guarantor CQS 3-4 to 100% under both CRR and B31. B31 Table 6 gives CQS 3=75%. **Overstates capital** for B31 exposures with CQS 3 corporate guarantors. Related to P1.95 (SCRA) but distinct: P1.95 is about unrated institution guarantors, P1.110 is about rated corporate guarantors. **Effort: S** | Ref: PRA PS1/26 Art. 122(2) Table 6, Art. 235
- **P1.112** [ ] **NEW** — Non-UK unrated PSE/RGLA default to 100% instead of sovereign-derived lookup. `sa/calculator.py:676-680` (B31 PSE), `696-700` (B31 RGLA), `996-1000` (CRR PSE), `1013-1017` (CRR RGLA) all use `cp_country_code == "GB" → 20%, otherwise → 100%`. Art. 116(1) Table 2 / Art. 115(1)(a) Table 1A require sovereign CQS-derived weights (e.g., CQS 1 sovereign → 20%). `cp_sovereign_cqs` field is available in schema. **Overstates capital** for non-UK PSE/RGLA with low sovereign CQS. **Effort: S** | Ref: CRR Art. 115(1)(a), Art. 116(1)
- **P1.114** [ ] **NEW** — Classifier null propagation in `str.contains()` for book_code/country_code silently routes to SA. `classifier.py:805,809` — when `cp_country_code` or `book_code` is null on an exposure row and the model_permissions field is non-null, `str.contains(null)` propagates null into `permission_valid`, causing silent SA fallback. Fix: add `.fill_null("")` on exposure columns before `str.contains()`. Effort: S | Ref: classifier model_permissions resolution
- **P1.117** [ ] **NEW** — B31 HVCRE short-maturity subgrades not implemented (distinct from P1.97). P1.97 covers non-HVCRE (Strong A=50%/B=70%, Good C=70%/D=90%). HVCRE Table A also has maturity-based subgrades: Strong A=70%/B=95%, Good C=95%/D=120%. No `B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` table exists. `namespace.py:408-416` ignores `is_short` for all B31 slotting. Effort: S | Ref: PRA PS1/26 Art. 153(5)(d)
- **P1.118** [~] **PARTIAL — re-scoped 2026-05-03** — Art. 162(3) one-day maturity floor on the IRB MA formula is now wired: `engine/irb/formulas.py:705-707` (`_maturity_adjustment_expr_from_pd`) reads `has_one_day_maturity_floor` and suppresses the 1y `maturity_floor` when True (the 5y cap is always applied). Defaulted to False at `formulas.py:376-377` when the column is absent. Remaining gap: the broader Art. 162(3) carve-out for *qualifying short-term exposures without `has_one_day_maturity_floor=True`* (e.g. trade finance <=1y, FX settlement) — these still get the default M=2.5 unless the caller pre-sets the flag, and there is no derivation logic populating the flag from product-type / SFT-flag inputs. Sub-claim that the flag is "only consulted for CRM maturity-mismatch" is closed-claim-invalid (now wired into the IRB MA). Effort: S (was M; reduced after partial implementation) | Ref: CRR Art. 162(3), PRA PS1/26 Art. 162(3); `engine/irb/formulas.py:373-377, 668-716`
- **P1.120** [ ] **NEW** — B31 SA defaulted provision-ratio denominator wrong (D3.19). Art. 127(1) requires `specific_provisions / gross_outstanding_amount` but code uses `unsecured_ead` (post-provision, post-CRM). For partially collateralised exposures, the smaller denominator can push the ratio below 20%, inflating RW from 100% to 150%. **Impact: Capital overstatement for collateralised defaulted exposures**. **Effort: S** | Ref: PRA PS1/26 Art. 127(1), `calculator.py:1250-1275`
- **P1.122** [ ] **NEW** — Guarantee substitution has no B31 framework branching. `_apply_guarantee_substitution()` at `sa/calculator.py:1428-1709` has zero `is_basel_3_1` checks. Uses single CQS table for both CRR and B31. Affects: (a) corporate CQS 3 = 100% (should be 75% under B31 per Table 6), (b) unrated institutions use CRR sovereign-derived (should use SCRA grades), (c) no short-term guarantor institution treatment. P1.95 and P1.110 are symptoms of this broader issue. **Effort: M** | Ref: PRA PS1/26 Art. 122/121/235
- **P1.123** [ ] **NEW** — FCCM missing exposure volatility haircut (HE) for SFT exposures. Art. 223(5) formula: `E* = max(0, E(1+HE) - CVA(1-HC-HFX))`. `collateral.py` omits the `(1+HE)` gross-up on the exposure side. HE=0 for standard lending (correct), but HE>0 for SFTs where exposure is a debt security. **Understates E* and hence RWA for SFT portfolios.** **Effort: M** | Ref: CRR Art. 223(5)
- **P1.124** [ ] **NEW** — Art. 237(2) guarantee ineligibility conditions not enforced. Guarantees with residual maturity < 3 months or original maturity < 1 year should be rejected entirely. Collateral maturity checks are correctly implemented in `haircuts.py:476-480`, but `guarantees.py` has no equivalent maturity eligibility check. Subset of P1.109 but distinct: P1.109 is the maturity mismatch *adjustment*, this is the eligibility *rejection*. **Effort: S** | Ref: CRR Art. 237(2)
- **P1.125** [ ] **NEW** — Classifier missing FSE column warning under B31. When `cp_is_financial_sector_entity` column is absent, `classifier.py:989-994` silently defaults `_is_fse = pl.lit(False)`, letting all FSEs get A-IRB instead of F-IRB (Art. 147A(1)(e)). Classifier already emits warnings for missing QRRE columns and retail pool management columns but not for FSE. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(e)
- **P1.126** [ ] **NEW** — Classifier Art. 147A(1)(d) null revenue defaults to "not large" (A-IRB permitted). `classifier.py:995-997` uses `fill_null(False)` on the large corporate check. Corporates with unknown revenue that exceed GBP 440m could get A-IRB instead of F-IRB. Should either conservatively treat null as "large" or emit a warning. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(d)
- **P1.127** [ ] **NEW** — Art. 159 Pool B composition: upstream per-exposure EL shortfall may not include AVA/other own funds reductions. Aggregator `_el_summary.py:197-201` correctly implements the two-branch rule but relies on upstream `el_shortfall`/`el_excess` columns. If IRB/slotting calculators compute shortfall as `max(0, EL - provisions)` without including AVA (Art. 34/105) and other own funds reductions in Pool B, the two-branch condition may be incorrectly evaluated. **Needs upstream verification.** **Effort: S** | Ref: CRR Art. 159(1)
- **P1.128** [ ] **NEW (Phase 8)** — B31 SCRA short-term missing Art. 121(4) trade finance <=6m extension. `sa/calculator.py:751-754` checks `residual_maturity_years <= 0.25` for SCRA (unrated institution) short-term but does NOT include the trade goods <=6m exception. The ECRA branch at `sa/calculator.py:730-739` correctly has `is_short_term_trade_lc & residual_maturity_years <= 0.5` but the SCRA branch omits this. Art. 121(4) grants the same exception to SCRA-graded institutions. **Overstates capital** for unrated institution trade finance exposures with 3-6m residual maturity. **Effort: S** | Ref: PRA PS1/26 Art. 121(4)
- **P1.130** [ ] **NEW (Phase 8)** — Aggregator summaries use pre-floor RWA. `aggregator.py:92-96` generates `summary_by_class` and `summary_by_approach` from `post_crm_detailed` BEFORE the output floor is applied at line 152. Since Polars LazyFrames are immutable, `apply_floor_with_impact()` returns a new LazyFrame that doesn't affect the pre-existing summary plans. Consumers expecting post-floor totals in summaries will see pre-floor RWA. **Understates reported RWA** when output floor is binding. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P1.30(e)** [ ] Art. 234 partial protection tranching — structured protection covering only part of the loss range. Not modelled. **Effort: L** | Ref: PRA PS1/26 Art. 234
- **P1.105** [ ] **NEW** — B31 Table 4A short-term institution ECAI risk weights not applied. `has_short_term_ecai` flag missing from schema. Table 4A gives CQS2=50%, CQS3=100% vs Table 4 fallback of 20% for both — current code *understates* risk for CQS 2-3 short-term-rated institutions. Also blocks Art. 122(3) Table 6A (P1.103). **Effort: S** | Ref: PRA PS1/26 Art. 120(2B), Art. 122(3)
- **P1.10** [ ] Unfunded credit protection transitional (PRA Rule 4.11) — narrow eligibility carve-out for legacy contracts during 1 Jan 2027–30 Jun 2028. Requires Art. 213 eligibility validation first. **Effort: M** | Ref: PRA PS1/26 Rule 4.11
- **P1.151** [ ] **NEW** — Purchased receivables / dilution-risk LGD missing (Art. 161(1)(e)–(g)). `src/rwa_calc/engine/irb/firb_lgd.py`. No `purchased_receivables_senior`, `_subordinated`, `dilution_risk` keys. Exposures default to 45% senior. B3.1 dilution-risk LGD = 100% not applied. **Effort: M** | Ref: PRA PS1/26 Art. 161(1)(e)-(g)
- **P1.153** [ ] **NEW** — Art. 155(3) PD/LGD equity approach entirely absent. `src/rwa_calc/engine/equity/`. No `EquityApproach.PD_LGD` enum, no Art. 165 floor table (0.09%/0.40%/1.25%), no M=5y equity handling, no EL×12.5+RWEA cap. Required under CRR; removed under B3.1. **Effort: L** | Ref: CRR Art. 155(3), Art. 165
- **P1.154** [ ] **NEW** — `international_org` collapsed into MDB. `src/rwa_calc/engine/classifier.py:80, 119`, `src/rwa_calc/domain/enums.py`. Art. 112(1)(e) international organisations (IMF, BIS) misclassified as MDB. Add `ExposureClass.INTERNATIONAL_ORGANISATION`; route SA and IRB mappings accordingly. **Effort: M** | Ref: CRR Art. 112(1)(e), Art. 117-118
- **P1.156** [ ] **NEW** — PSM guarantor LGD hard-coded 40%. `src/rwa_calc/engine/irb/guarantee.py:302, 462`. Art. 236 requires seniority-aware LGD: 40% non-FSE senior / 45% FSE senior / 75% subordinated, or borrower's unprotected LGD (option 1). **Effort: S** | Ref: CRR Art. 236
- **P1.157** [ ] **NEW** — PSM PD uplift "no better than direct" missing (Art. 160(4)). `src/rwa_calc/engine/irb/guarantee.py:316`. PSM-guaranteed PD must be floored at direct-exposure PD to avoid PSM producing lower capital than direct exposure to guarantor. **Effort: S** | Ref: CRR Art. 160(4)
- **P1.158** [ ] **NEW** — Null collateral maturity defaults to 5y. `src/rwa_calc/engine/crm/haircuts.py:449`. Art. 224 conservative fallback should be >10y band, not 5y (produces lower haircut than intended when maturity is missing). **Effort: S** | Ref: CRR Art. 224
- **P1.159** [ ] **NEW (D3.56 doc-writer, P19-07 closure)** — PSM correlation re-derivation reads borrower row, not guarantor. `engine/irb/guarantee.py::_parametric_irb_risk_weight_expr` Step 3 pulls correlation inputs (`exposure_class`, `turnover_m`, `requires_fi_scalar`) from the borrower's LazyFrame columns instead of the guarantor's. PRA PS1/26 Art. 236(1)(a)(i) (BCBS CRE22.74) requires the *guarantor's* correlation curve when the guarantor sits in a different exposure class than the borrower (e.g. an institution guaranteeing a corporate exposure — institution and corporate both use the 0.12-0.24 PD-dependent curve, but FSE/large-corp/institution differentiation under B31 changes the correlation multiplier). Cross-class guarantees currently use the wrong correlation. Spec at `docs/specifications/basel31/credit-risk-mitigation.md` (updated this batch) flags this as a "Code-side gating" warning. **Effort: M** | Ref: PRA PS1/26 Art. 236(1)(a)(i); BCBS CRE22.74; `src/rwa_calc/engine/irb/guarantee.py`; `src/rwa_calc/engine/irb/formulas.py:756`
- **P1.160** [ ] **NEW (D3.56 doc-writer, P19-07 closure)** — PSM LGD substitution always uses senior-unsecured F-IRB scalar; subordinated and covered-bond guarantor seniority not differentiated row-wise. `engine/irb/guarantee.py::_apply_parameter_substitution` Step 2 reads `unsecured_senior` from `firb_lgd_table` for every guaranteed row, so subordinated guarantees (Art. 161(1)(b), 75% LGD) and covered-bond guarantees (Art. 161(1)(d), 11.25% LGD) collapse onto the senior LGD. The engine cannot honour guarantor seniority. Closely related to P1.156 (Art. 236 hard-coded 40% scalar) but distinct: P1.156 is about the substitution-rule scalar; P1.160 is about routing the right `firb_lgd` table row by guarantor seniority. **Effort: M** | Ref: PRA PS1/26 Art. 161(1)(aa)/(b)/(d); BCBS CRE22.73; `src/rwa_calc/engine/irb/guarantee.py:300-301`; `src/rwa_calc/data/tables/firb_lgd.py`
- **P1.161** [ ] **NEW (D4.61 doc-writer closure, 2026-05-03)** — PRA PS1/26 Art. 191A(2)(e)/(2)(f) two-layer protection look-through not implemented. Engine does not recognise (i) the Art. 191A(2)(e) election to apply the funded-collateral framework *through* an unfunded guarantee where the guarantor itself has posted eligible funded collateral (the "funded only" / "unfunded + funded jointly" combinations on a guarantor-collateralised guarantee chain), nor (ii) the Art. 191A(2)(f) borrower-deeming flexibility that lets firms treat the guarantor as if it were the borrower for purposes of selecting the CRM method. `src/rwa_calc/engine/crm/processor.py` currently treats funded and unfunded protection as covering distinct portions of the original exposure (per the Art. 191A(2)(d) no-double-counting rule) — there is no surface or routing for the (2)(e)/(2)(f) combinations. **Distinct from P1.30(e)** (Art. 234 *tranched* coverage on a single exposure, not the two-layer look-through across protection layers). New B31 CRM spec section `docs/specifications/basel31/credit-risk-mitigation.md#look-through-for-unfunded-protection-backed-by-funded-protection-art-191a2e-f` (D4.61 closure) documents the regulation; the engine gap remains. Cross-ref: D4.61 (closed 2026-05-03). **Effort: M** | Ref: PRA PS1/26 Art. 191A(2)(d), (2)(e), (2)(f); Appendix 1 Part 4; `src/rwa_calc/engine/crm/processor.py`
- **P1.162** [ ] **NEW (D4.81 doc-writer closure, 2026-05-03)** — UKB OV1 missing seven mandatory output-floor disclosure rows. `B31_OV1_ROWS` in `src/rwa_calc/reporting/pillar3/templates.py:125-139` jumps from row 4 (slotting) directly to row 5 (AIRB) and from row 24 to row 26 — omitting the seven Annex XX UKB OV1 rows that are mandatory for output-floor-active institutions: **row 4a** (Total RWEAs pre-floor), **rows 5a/5b** (CET1 capital ratio pre-floor / pre-floor transitional), **rows 6a/6b** (Tier 1 capital ratio pre-floor / pre-floor transitional), **rows 7a/7b** (Total capital ratio pre-floor / pre-floor transitional). Non-disclosure breaches PS1/26 Annex XX for any firm where the Art. 92(2A) floor binds. Resolution: (i) add seven `P3Row` entries with row keys `"4a"`, `"5a"`, `"5b"`, `"6a"`, `"6b"`, `"7a"`, `"7b"` to `B31_OV1_ROWS`; (ii) wire `_generate_ov1()` in `src/rwa_calc/reporting/pillar3/generator.py` so row 4a populates from the pre-floor IRB+slotting+SA-non-IRB total (equivalently `OF 02.00 row 0010` minus the OF-ADJ in `OutputFloorSummary`), and rows 5a/5b/6a/6b/7a/7b accept `None`/null with a docstring + `docs/features/pillar3-disclosures.md` note that they are firm-supplied (own-funds figures sit outside the credit-risk pipeline); (iii) refresh Pillar 3 fixtures and golden files (`tests/fixtures/pillar3/*`, `tests/expected_outputs/pillar3/*`). Acceptance: B31 OV1 generator emits 14 rows (was 7); row 4a non-null whenever `OutputFloorSummary` is present; rows 5a-7b null by default and overridable via a config/firm-input hook. Single source of truth for the CRR↔B31 OV1 row delta is `docs/framework-comparison/disclosure-differences.md:31, 63-64`. Cross-ref: D4.81 (closed 2026-05-03), `docs/features/pillar3-disclosures.md` (updated this batch). **Effort: S–M** (additive only; dominant cost is fixture/golden updates) | Ref: PRA PS1/26 Annex XX UKB OV1 (Disclosure (CRR) Part), Art. 92(2A), Art. 92(5); `src/rwa_calc/reporting/pillar3/templates.py:125-139`, `src/rwa_calc/reporting/pillar3/generator.py`, `tests/fixtures/pillar3/`, `tests/expected_outputs/pillar3/`

<!-- ### Migrated from DOCS_IMPLEMENTATION_PLAN.md on 2026-05-03 -->
<!-- D3.1, D3.4, D3.6, D3.11–D3.23, D3.27, D3.29, D3.36–D3.39, D3.43 → P1.163–P1.185. -->
<!-- These items are code-side only; the docs side has already been corrected. Items already covered by a pre-existing FIXED P-code carry a `[x]` checkbox; those covered by an open P-code carry `[~]` and cross-reference the existing item. -->

- **P1.164** [ ] **NEW (migrated from D3.4, 2026-05-03)** — IRB Simple `GOVERNMENT_SUPPORTED: 190%` in `crr_equity_rw.py:64` has no corresponding entry in CRR Art. 155 (which only defines exchange-traded 290% / PE diversified 190% / other 370%). Either map `GOVERNMENT_SUPPORTED` to `OTHER` (370%) or document the 190% as an intentional conservative-favourable approximation with a code comment. **Capital impact:** small — affects only the narrow IRB Simple government-supported equity branch under CRR. Docs side fixed by D1.27 (`regulatory-tables.md` shows this as a code-specific mapping with no Art. 155 basis). **Effort: S** | Ref: CRR Art. 155
- **P1.165** [ ] **NEW (migrated from D3.6, 2026-05-03)** — CRR receivables haircut 0.20 in `haircuts.py:71` is an "ad-hoc approximation" with no regulatory basis. Spec correctly states non-financial collateral does not use Art. 224 haircuts (Art. 230 C*/C** mechanism applies instead). Code-quality cleanup: either remove the receivables haircut entirely (and route through Art. 230) or annotate the constant with the regulatory rationale for the 0.20 value. See P1.186/D4.75 for the related RE/other-physical ad-hoc haircuts in the same file. **Effort: S** | Ref: CRR Art. 224, Art. 230
- **P1.167** [~] **NEW (migrated from D3.12, 2026-05-03; cross-ref P2.14)** — CRR HIGH_RISK exposure class treated as active in CRR engine path (`sa/calculator.py:1041-1045`) despite Art. 128 being omitted from UK CRR by SI 2021/1078 effective 1 Jan 2022. Exposures should fall through to Art. 133 (equity 100%) or counterparty's standard class treatment, not 150%. Basel 3.1 path (`sa/calculator.py:859`) is correct (Art. 128 reintroduced). **Already tracked as P2.14** — this migration entry preserves the D3.12 lineage; resolve under P2.14 to avoid duplication. **Effort: S** | Ref: SI 2021/1078; `sa/calculator.py:1041-1045`
- **P1.169** [ ] **NEW (migrated from D3.14, 2026-05-03)** — `b31_risk_weights.py` `B31_ECRA_SHORT_TERM_RISK_WEIGHTS` (lines 197-204): CQS 4 and CQS 5 both set to `Decimal("0.20")` (20%). PRA PS1/26 Art. 120(2) Table 4 confirms CQS 4-5 = **50%** (not 20%). Code comment at line 189 ("CQS 1-5 all receive 20%") also wrong — only CQS 1-3 receive 20%; CQS 4-5 receive 50%. **Capital impact: understatement** for short-term-rated B31 institution exposures with CQS 4-5 (30 percentage points). Discovered during D1.22 fix — verified against PDF extraction. **Effort: S** | Ref: PRA PS1/26 Art. 120(2) Table 4
- **P1.173** [~] **NEW (migrated from D3.18, 2026-05-03; cross-ref P2.17)** — CRR retail payroll/pension 35% not implemented in CRR code path. `sa/calculator.py` CRR branch has no `is_payroll_loan` check — all CRR retail exposures receive flat 75%. The 35% treatment exists in CRR since CRR2 (Reg 2019/876, Art. 123 second subparagraph). **Already tracked as P2.17** — resolve under P2.17 to avoid duplication. **Sub-gap (article-reference correction):** code constant comment `B31_RETAIL_PAYROLL_LOAN_RW` in `b31_risk_weights.py:212` and schema comments in `schemas.py:80,101,642` cite "Art. 123(3)(a-b)" — should be **Art. 123(4)**. Art. 123(3) covers the risk weight tiers (45%/75%/100%), not payroll/pension. Article-reference fix is a Tier 1b cosmetic — see P1.175 below. **Effort: S** | Ref: CRR Art. 123 (CRR2 amendment), Art. 123(4)
- **P1.174** [~] **NEW (migrated from D3.19, 2026-05-03; cross-ref P1.120)** — B31 defaulted provision threshold denominator code bug. `calculator.py:1250-1275` uses `unsecured_ead` (post-provision unsecured exposure value) as the Basel 3.1 provision-coverage denominator. PRA PS1/26 Art. 127(1) specifies "the outstanding amount of the item or facility" — the gross outstanding balance, not the unsecured portion. **Capital impact: overstatement** for partially collateralised exposures (smaller denominator pushes the ratio below 20%, inflating RW from 100% to 150%). CRR path (`calculator.py:1276-1291`) correctly uses pre-provision unsecured value per CRR Art. 127(1). **Already tracked as P1.120** — resolve under P1.120 to avoid duplication. **Effort: S** | Ref: PRA PS1/26 Art. 127(1)
- **P1.177** [ ] **NEW (migrated from D3.22, 2026-05-03)** — CRR HVCRE slotting risk weight code bug: `crr_slotting.py` defines `SLOTTING_RISK_WEIGHTS_HVCRE` and `SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` with EU CRR Table 2 values (Strong: 95%/70%, Good: 120%/95%, Satisfactory: 140%/140%, Weak: 250%/250%). The UK onshored CRR has **no HVCRE concept** — Art. 153(5) contains only Table 1 for all SL types. "High volatility commercial real estate" does not appear anywhere in the UK CRR text. The EU CRR Table 2 was not retained in UK onshoring. **Capital impact: overstatement** (more conservative than required for `is_hvcre=True` CRR exposures). PRA PS1/26 introduces HVCRE as a new sub-type in Table A — B31 HVCRE constants are correct. **Action:** under CRR, route HVCRE exposures through the standard non-HVCRE Table 1; remove (or relabel) `SLOTTING_RISK_WEIGHTS_HVCRE`/`_SHORT`. CRR acceptance tests CRR-E4, CRR-E7, CRR-E8 will need updating. Discovered during D4.23 fix via full-text PDF search of crr.pdf. **Effort: S** | Ref: CRR Art. 153(5) (UK onshored, no HVCRE table)
- **P1.178** [~] **NEW (migrated from D3.23, 2026-05-03; cross-ref P1.122)** — B31 guarantee substitution: `_apply_guarantee_substitution()` at `sa/calculator.py:1428-1709` has zero `is_basel_3_1` checks. Uses CRR CQS tables for both frameworks. Affects: (a) corporate CQS 3 guarantors = 100% (B31 Table 6 = 75%), (b) unrated institution guarantors use CRR sovereign-derived 40% (B31 should use SCRA grades), (c) no short-term guarantor institution treatment. This is the root cause of P1.95, P1.110, P1.122. Docs correctly describe the B31 guarantee substitution rules; code does not implement them. **Already tracked as P1.122** (with P1.95 and P1.110 as sub-symptoms) — resolve under P1.122 to avoid duplication. **Effort: M** | Ref: PRA PS1/26 Art. 122/121/235
- **P1.179** [ ] **NEW (migrated from D3.27, 2026-05-03)** — `firb_lgd.py::get_firb_lgd_table()` is framework-agnostic — always returns CRR values. Function has no `is_basel_3_1` parameter. Any code calling it directly will get CRR LGD values regardless of framework. The B31 equivalent (`firb_lgd.py::get_b31_firb_lgd_table()`) exists separately but the naming pattern creates confusion risk. Practical impact is reduced because `regulatory-tables.md` points to dict constants rather than DataFrame functions; risk is future callers (or test fixtures) using the wrong function. **Action:** rename `get_firb_lgd_table()` → `get_crr_firb_lgd_table()` for symmetry, or add an `is_basel_3_1` parameter that dispatches to the right table. **Effort: S** | Ref: Code structure; `src/rwa_calc/data/tables/firb_lgd.py`
- **P1.180** [ ] **NEW (migrated from D3.29, 2026-05-03; partial cross-ref P1.184)** — `covered_bond_unrated_derivation` in `crr_risk_weights.py` has 7 entries but CRR Art. 129(5) only produces 4. The 3 extra entries (30%, 40%, 75% institution RW) only arise under B31 SCRA — they don't occur in CRR where unrated institutions get sovereign-derived rates (20%/50%/100%). Comment says "CRR Art. 129(5), PRA PS1/26 Art. 129" — misleading dual attribution. Won't produce wrong CRR results (Art. 129(5) lookup keyed on institution RW; the extra B31 keys never match a CRR row) but structurally conflates frameworks. **Action:** split into two named dicts (`COVERED_BOND_UNRATED_DERIVATION_CRR` with 4 entries, `_B31` with 7 entries) keyed off `config.is_basel_3_1`. Docs side fixed by D4.62. **Effort: S** | Ref: CRR Art. 129(5), PRA PS1/26 Art. 129(5)
- **P1.181** [ ] **NEW (migrated from D3.36, 2026-05-03)** — CRR Art. 126 CRE implemented as binary whole-loan; regulation requires proportion-based split. `crr_risk_weights.py::calculate_commercial_re_rw()` and `calculator.py:984-997` apply 50% if LTV ≤ 50% with income cover, 100% otherwise. Art. 126(2)(d) requires: 50% on the part of the loan not exceeding 50% of MV (or 60% of MLV), counterparty RW on the excess — analogous to Art. 125 RRE split which IS correctly implemented as a weighted blend. For LTV ≤ 50% the result is identical (whole loan within secured portion), but for LTV > 50% with qualifying conditions met, the code over-assigns risk. **Capital impact: overstatement** for CRE with LTV > 50% meeting Art. 126 qualifying conditions. **Action:** mirror Art. 125 pattern: `secured_share = min(1.0, 0.50 / LTV); avg_RW = 0.50 × secured_share + counterparty_RW × (1 - secured_share)`. Docs side fixed by D1.36. **Effort: S** | Ref: UK CRR Art. 126(2)(d)
- **P1.182** [ ] **NEW (migrated from D3.37, 2026-05-03)** — PE/VC always mapped to 400% higher-risk in equity calculator; regulation requires unlisted + business < 5yr test. `equity/calculator.py:570-574` assigns 400% to all `private_equity` and `private_equity_diversified` equity types unconditionally. Line 570 comment: "PE/VC is always higher risk (400%)". PRA PS1/26 Glossary (p.5) defines higher-risk equity as **unlisted + business has existed for less than five years** — both conditions must be met. Long-established PE holdings (business ≥ 5 years) should receive standard 250% (Art. 133(3)), not 400%. Also: `b31_equity_rw.py:9` docstring says "PE / VC / unlisted <5yr" conflating three separate concepts. Also affects `calculator.py:549-550` docstring ("PE / VC (always higher risk)"). **Capital impact: overstatement** for established PE holdings (150 percentage points). **Action:** (1) add `business_age_years` or `is_established` input field; (2) route PE/VC to 400% only when both conditions met; (3) update B31-L2, B31-L19 acceptance tests. Docs side fixed by D1.38. **Effort: M** | Ref: PRA PS1/26 Glossary p.5, Art. 133(3)-(4)
- **P1.183** [ ] **NEW (migrated from D3.38, 2026-05-03)** — CRR Art. 164(4) portfolio-level LGD floors not implemented. `LGDFloors.crr()` returns all zeros, but CRR Art. 164(4) (as amended by CRR2, Reg 2019/876) imposes portfolio-level minimum LGD requirements: exposure-weighted average LGD ≥ 10% for retail residential RE, ≥ 15% for retail commercial RE. These are portfolio-level (not per-exposure) floors requiring a post-aggregation validation step. The per-exposure architecture cannot directly enforce them. **Capital impact: understatement** for IRB retail RE portfolios where the exposure-weighted average LGD falls below the floor. **Action:** add a post-aggregation validation step that computes the exposure-weighted average LGD per retail RE sub-class and either (a) emits a `CalculationError` or (b) re-floors the LGD column at the portfolio level before recomputing capital. Docs side fixed by D1.39. **Effort: M** | Ref: UK CRR Art. 164(4)
- **P1.184** [ ] **NEW (migrated from D3.39, 2026-05-03; relates to P1.172)** — CRR MDB risk weight table uses Basel 3.1 Table 2B values. `crr_risk_weights.py:231-246` defines `MDB_RISK_WEIGHTS_TABLE_2B` with CQS 2 = 30% and unrated = 50%. CRR Art. 117(1) treats non-0% MDBs "in the same manner as exposures to institutions" — they should use institution Table 3 (CQS 2 = 50% under CRR). The 30% value is the PRA PS1/26 Art. 117(1)(a) Table 2B value, not CRR. **Capital impact: understatement** for CRR MDB exposures with CQS 2 (20pp under-capital) or unrated (50pp). Same root-cause pattern as P1.172 (D3.17 institution CQS 2). **Action:** under CRR framework, route non-named MDBs to institution risk weight lookup instead of a separate MDB table; under Basel 3.1, Table 2B is correct. Docs side fixed by D1.40. **Effort: M** | Ref: CRR Art. 117(1), PRA PS1/26 Art. 117(1)(a)

#### Tier 1b — Source-code docstring corrections (cosmetic, no calculation impact)

These items are docstring / code-comment / structural-organisation corrections only. The calculations they describe are correct; the bugs are in the prose surrounding them. Tagged Effort: S.

- **P1.163** [ ] **NEW (migrated from D3.1, 2026-05-03; docstring only)** — `formulas.py:62-63` docstring: retail mortgage PD floor = 0.05%, QRRE transactors PD floor = 0.03%. Correct values per regulation: **0.10%** and **0.05%** respectively. **The code constants and all other docs use the right values; this is a docstring-only typo with no calculation impact.** **Effort: S** | Ref: PRA PS1/26 Art. 160(1)
- **P1.166** [ ] **NEW (migrated from D3.11, 2026-05-03; docstring only)** — Equity calculator docstring (`equity/calculator.py:21`): "CIU fallback: 150% → 250%". Both values wrong — Art. 132(2) fallback is **1,250%** for both CRR2 and PRA PS1/26. The 250% is Art. 133 equity weight, not CIU fallback. **Code constants now correct (P1.119/v0.1.184 fixed the calculation); only the calculator module-level docstring still carries the stale prose.** **Effort: S** | Ref: PRA PS1/26 Art. 132(2); cross-ref P1.119/P1.170
- **P1.168** [ ] **NEW (migrated from D3.13, 2026-05-03; docstring only)** — `b31_risk_weights.py` module docstring (line 16): says "CQS5: 100%". Line 327 docstring: says "CQS5=100%". Both wrong — PRA retains CQS 5 = **150%**. **The code constant itself is correct (`5: Decimal("1.50")` at line 143); docstrings only.** **Effort: S** | Ref: PRA PS1/26 Art. 122 Table 6
- **P1.171** [ ] **NEW (migrated from D3.16, 2026-05-03; structural observation)** — Code-state observation arising from D1.20 fix: `regulatory-tables.md` SA Equity table previously showed B31 values (250%/400%) under heading "SA Equity (CRR Art. 133)". Table restructured during D1.20 fix (separate CRR and B31 with code-vs-regulation columns). **The underlying code constants `SA_EQUITY_RISK_WEIGHTS` are CRR-correct (100% flat) except for CIU (150% instead of 1,250%) which is fixed by P1.119/P1.170.** No new code action required beyond P1.170 — this entry preserves the D3.16 lineage as an audit trail. **Effort: S** (no-op — close together with P1.170 once verified) | Ref: CRR Art. 133(2)
- **P1.175** [ ] **NEW (migrated from D3.20, 2026-05-03; comment-only article references)** — Art. 114 paragraph number errors in source code comments. `calculator.py` (lines 511, 513, 603, 919, 1513), `classifier.py` (lines 906-907, 966), `eu_sovereign.py` (lines 5, 18), and `guarantee.py` (lines 188, 206) all reference "Art. 114(3)/(4)" for domestic currency treatment. Art. 114(3) is the **ECB** provision, not UK domestic currency. UK domestic = Art. 114(4); EU domestic = Art. 114(7) (third-country reciprocity in UK-onshored CRR). `classifier.py:966` specifically labels EU CGCB treatment as "Art. 114(4)" — should be Art. 114(7). **Code comments only — calculation correct.** Bundle with P1.173 sub-gap (Art. 123(3)→123(4) in `b31_risk_weights.py:212` and `schemas.py:80,101,642`). **Effort: S** | Ref: CRR Art. 114(4)/(7), Art. 123(4)
- **P1.185** [ ] **NEW (migrated from D3.43, 2026-05-03; docstring only)** — `domain/enums.py` `SCRAGrade.B` docstring retains fabricated quantitative thresholds. Source line 320 reads `"""CET1 > 5.5%, Leverage > 3%, meets minimum requirements → 75% RW (>3m), 50% (≤3m)"""`. D1.34 corrected the description in `docs/api/domain.md` but did not update the source enum docstring; source now contradicts corrected docs. Art. 121(1)(b) defines Grade B qualitatively ("meets minimum requirements excluding buffers") — no CET1/leverage thresholds in regulation. **Docstring only; SCRA grade lookup logic unchanged.** **Effort: S** | Ref: PRA PS1/26 Art. 121(1)(b); related to D1.34

- **P1.186** [x] **FIXED v0.2.6** — wired transaction-type-aware liquidation-period default into the CRM processor (`is_sft` propagation onto collateral) + `engine/crm/haircuts.py` (default 20-day for secured lending, 5-day for SFTs); D6 acceptance + D2/D3 collateral-haircut acceptance + 32 unit tests re-baselined to the 20-day default per CRR Art. 224(2)(a). **NEW (2026-05-03)** — FX collateral haircut Hfx defaults to 10-day liquidation period (8%) for *all* exposures regardless of transaction type, instead of the regulatory 20-day default (11.314%) for secured lending. CRR Art. 224(2) / PRA PS1/26 Art. 224(2) mandate three liquidation periods: (a) **secured lending = 20 business days → Hfx 11.314%**, (b) repo / SLB = 5 days → 5.657%, (c) capital-market-driven = 10 days → 8%. `engine/crm/haircuts.py:130-136` reads the optional `liquidation_period_days` collateral column and `fill_null(10)` — but no code populates it from the exposure transaction type, so a vanilla FX-mismatched loan facility receives the 10-day OTC-derivative value instead of the 20-day secured-lending value. The per-period constants `LIQUIDATION_PERIOD_REPO=5 / _CAPITAL_MARKET=10 / _SECURED_LENDING=20` already exist at `data/tables/haircuts.py:146-148` but are unwired. **Capital impact:** ~3.07% RWA understatement on the FX-mismatched protected portion of every secured-lending exposure (e.g. £1m USD loan + €500k EUR cash collateral: collateral over-recognised by £16.6k, RWA understated by £16.6k). Acceptance tests CRR-D6 and B31-D6 currently bake in the wrong number (`460k` should be `443.43k` adjusted collateral). **Action:** (i) in `engine/crm/haircuts.py` derive the liquidation-period default from the joined exposure row — `LIQUIDATION_PERIOD_REPO` when `is_sft=True`, `LIQUIDATION_PERIOD_SECURED_LENDING` (20) otherwise; per-collateral explicit override remains supported; (ii) re-baseline `tests/acceptance/{crr,basel31}/test_scenario_*_d_crm.py` D6 expected values to 443.43k / EAD 556.57k / RWA 556.57k; (iii) update `tests/unit/crm/test_collateral_fx_mismatch.py` to add an explicit `liquidation_period_days=10` override on the existing 8% pin and add a new test pinning the 20-day default for loan-derived collateral; (iv) refresh CRM specs (`docs/specifications/{crr,basel31}/credit-risk-mitigation.md`) to state the secured-lending default explicitly. **Closes the `liquidation_period as config` outstanding item from P6.15 / D2.39.** **Effort: S** | Ref: CRR Art. 224(2)(a), PRA PS1/26 Art. 224(2)(a), Art. 226(2); `src/rwa_calc/engine/crm/haircuts.py:130-136`, `src/rwa_calc/data/tables/haircuts.py:146-148`
- **P6.9** [~] Provision pro-rata weight uses pre-CCF approximation (`drawn + interest + nominal`) instead of spec's `ead_gross`. Reasonable but diverges from spec. **Effort: S** | Ref: CRM spec
- **P6.15** [~] 3 missing schema fields: `protection_inception_date` (P1.10), `contractual_termination_date` (P1.20 revolving maturity), `liquidation_period` as config (P1.39 dependency, now tracked as P1.186). **Effort: S**

### Tier 2 — Test Coverage Gaps (no code changes, but essential for confidence)

- **P5.11** [ ] **NEW** — Missing acceptance tests for secondary SA exposure classes. Covered bonds, PSE, RGLA, MDB, high-risk items, and other items (Art. 134) have 60-120 unit tests each but ZERO end-to-end acceptance tests. Need CRR and B31 acceptance scenarios. **Effort: M**
- **P5.12** [ ] **NEW** — Missing B31 acceptance tests for Art. 129A covered bond changes (SCRA-derived unrated RW). Only unit tests exist. **Effort: S**
- **P5.13** [ ] **NEW** — Missing acceptance tests for Art. 124A-124L RE treatment scenarios under B31 (income-dependent/non-dependent, commercial sub-types, Other RE Art. 124J). Only unit tests. **Effort: S**
- **P5.14** [ ] **NEW** — No integration/acceptance tests for COREP or Pillar III reporting generators. All 663+ COREP tests and 197+ Pillar III tests are unit tests with synthetic data. No test validates full pipeline → reporting output. **Effort: M**
- **P5.15** [ ] **NEW** — Art. 123A(1)(b)(ii) 0.2% portfolio granularity sub-condition not implemented or tracked. The retail qualifying check only enforces the GBP 880k threshold, not the condition that no single exposure may exceed 0.2% of the total retail portfolio. The spec claims "Condition 2 (granularity threshold): Implemented" without noting the 0.2% is missing. Low impact (most portfolios satisfy this naturally). **Effort: M**

### Tier 3 — COREP Reporting Completeness

- **P2.14** [ ] **NEW** — CRR engine applies Art. 128 high-risk 150% RW despite UK omission (D3.12). Art. 128 was removed from UK onshored CRR by SI 2021/1078 effective 1 Jan 2022 — no legal basis for the HIGH_RISK exposure class under CRR until Basel 3.1 reintroduces it from 2027. Conservative overstatement (150% vs whatever the alternative classification would yield). **Effort: S** | Ref: SI 2021/1078, `calculator.py:1051-1055`
- **P2.13** [~] **UPGRADED TO P1.123** — FCCM exposure volatility haircut (HE) upgraded to P1 (Tier 1) as P1.123 after Phase 7 audit confirmed SFT capital understatement impact.
- **P2.12** [ ] **NEW** — C 07.00 / OF 07.00 missing col 0020 "Exposures deducted from own funds". Standard column between 0010 (Original exposure) and 0030 (Value adjustments). Template submission validation will flag this. **Effort: S**
- **P2.1** [~] COREP template rework — generator uses simplified column sets vs full-width template definitions. Multiple sub-gaps: C 08.01 col 0120 (off-BS EAD), B31 CIU sub-rows 0284/0285, OF 08.01 off-BS CCF sub-rows 0031-0035, slotting FCCM cols 0101-0104. **Effort: L**
- **P2.5** [~] COREP missing row structure — OF 02.00 sub-class breakdown rows (0295-0297, 0355-0356, 0382-0385) need `cp_is_fse`/`is_sme` pipeline columns. OF 08.01 revolving row 0017 needs pipeline column. **Effort: M**
- **P2.7** [~] COREP pre-credit-derivative RWEA (row 0310) — approximated as total RWEA. Accurate split requires per-exposure pre/post CD tracking in CRM pipeline. **Effort: M**
- **P2.17** [ ] **NEW** — CRR payroll/pension loan 35% RW not applied in CRR code path. `calculator.py:993-995` applies flat 75% to all CRR retail. CRR2 (Reg 2019/876) introduced Art. 123 second subparagraph giving 35% for qualifying payroll/pension loans. `is_payroll_loan` flag and 35% logic exist only in B31 branch (line 831-834). Conservative overstatement (75% vs 35%). **Effort: S** | Ref: CRR Art. 123 (CRR2 amendment)
- **P2.16** [ ] **NEW** — Output floor edge cases: (a) GCRA cap not enforced when S-TREA=0 (`_floor.py:77` passes GCRA uncapped; should be 0.0 per "1.25% of S-TREA"); (b) S-TREA fallback to `rwa_final` when `sa_rwa` absent (`aggregator.py:138`) skews GCRA cap on audit path. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P2.15** [ ] **NEW** — Equity transitional Rules 4.7-4.8 (CIU underlyings for IRB-permissioned firms) not implemented. Code excludes CIU look-through/mandate-based from transitional floor entirely — correct for SA-only firms (Rules 4.1-4.3) but wrong for IRB firms where Art. 155 CIU underlyings should use higher-of IRB/transitional SA. Also, opt-out election (Rules 4.9-4.10) has no config flag. **Effort: S** | Ref: PRA PS1/26 Rules 4.7-4.10, `calculator.py:690-693`
- **P2.18** [ ] **NEW** — Art. 226(1) non-daily revaluation haircut scaling missing. When collateral revalued less frequently than daily, supervisory haircuts should be scaled by `sqrt((NR + T_m - 1) / T_m)`. `haircuts.py` scales by liquidation period but has no NR (revaluation frequency) factor. No `revaluation_frequency_days` input field. **Effort: S** | Ref: CRR Art. 226(1)
- **P2.19** [ ] **NEW** — Higher-risk equity Art. 133(4) definition relies on pre-classified `equity_type` instead of evaluating regulatory conditions dynamically. No `is_held_for_short_term_resale` or `is_derived_from_derivative` flags in schema. If input data doesn't pre-classify correctly, unlisted equity held for short-term resale gets 250% instead of 400%. **Effort: S** | Ref: PRA PS1/26 Art. 133(4)
- **P2.20** [ ] **NEW** — `OutputFloorSummary.total_rwa_post_floor` field name misleading — only contains floored IRB+slotting component, excludes SA and equity RWA. Consumers expecting total portfolio RWA will be misled. **Effort: S** | Ref: `_floor.py:253`
- **P2.21** [ ] **NEW** — Pipeline error conversion drops ALL `CalculationError` metadata (not just `regulatory_reference`). `pipeline.py:348-356` uses `getattr(error, "error_type", "unknown")` and `getattr(error, "context", {})` but `CalculationError` has no such attributes — it has `code`, `severity`, `category`, `exposure_reference`, etc. All fields resolve to defaults. Audit trail severely degraded. **Effort: S**
- **P1.137** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.2/4.3 SA ladder not implemented. `data/tables/b31_equity_rw.py` + `engine/equity/calculator.py` apply fully-phased-in weights from day one. PS1/26 Rule 4.2 (SA standard equity 160% 2027 / 190% 2028 / 220% 2029 → 250% 2030) and Rule 4.3 (higher-risk equity 220% 2027 / 280% 2028 / 340% 2029 → 400% 2030) are not applied. **Capital overstatement in transitional 2027-2029 for SA-only firms.** Related to (but distinct from) P2.15. **Effort: M** | Ref: PRA PS1/26 Rule 4.2-4.3
- **P1.138** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.6 IRB higher-of not implemented. IRB firms holding Art. 155 permission on 31 Dec 2026 should take `max(legacy Art. 155 RW, Rule 4.2/4.3 transitional SA RW)` through 2029. Code transitions instantly to new Art. 133 treatment. **Effort: M** | Ref: PRA PS1/26 Rule 4.4-4.6
- **P1.139** [ ] **NEW (Phase 9)** — Equity transitional Rule 4.8 CIU higher-of not implemented. Look-through / mandate-based CIU firms should take `max(legacy Art. 155(2) simple RW, new Rule 4.2/4.3 RW)` during transitional period. Related to P2.15 but distinct: P2.15 notes IRB-permissioned CIU underlyings excluded from floor; P1.139 is the core RW calculation. **Effort: M** | Ref: PRA PS1/26 Rule 4.7-4.8
- **P1.140** [ ] **NEW (Phase 9)** — ADC classification flag-only; no derivation logic. `engine/classifier.py` has zero `is_adc` logic. User must pre-tag; a mis-flagged CRE/RRE development loan silently routes to corporate 75-100% instead of the 150% ADC weight. **Capital understatement** for mis-tagged land-acquisition/development/construction loans. **Effort: M** | Ref: PRA PS1/26 Art. 124(3), Art. 124K
- **P1.141** [ ] **NEW (Phase 9)** — Art. 124(4) mixed residential/commercial RE splitting not implemented. No code splits a mixed-use exposure into RRE/CRE portions proportional to collateral value. Mixed-use routed wholly to either RRE or CRE based on the dominant flag. **Effort: M** | Ref: PRA PS1/26 Art. 124(4)
- **P1.142** [ ] **NEW (Phase 9)** — Art. 124E three-property limit for "materially dependent" not automated. Natural-person obligors with 4+ BTL (or similar income-dependent) properties should be pushed to Art. 124G (income-dependent) risk weights. Currently there is no derivation — caller must manually set `is_income_producing_re`. **Understates capital** where the three-property test is not correctly pre-tagged. **Effort: M** | Ref: PRA PS1/26 Art. 124E(2)
- **P1.143** [ ] **NEW (Phase 9)** — Rule 4.11 unfunded credit protection grandfathering window (1 Jan 2027 – 30 Jun 2028) not honoured. Legacy CP entered into before 1 Jan 2027 should read Art. 213(1)(c)(i)/183(1A)(b) with "or change" omitted. No code implements this transitional window. Distinct from P1.10 (which is also not implemented — P1.10 is the underlying Art. 213 eligibility check; P1.143 is the transitional date-gated relaxation that depends on it). **Effort: M** | Ref: PRA PS1/26 Rule 4.11
- **P1.144** [ ] **NEW (Phase 9)** — EL fallback to gross EAD when `ead_final` absent. `engine/irb/calculator.py:211-218` uses gross EAD when `ead_final` is missing, but the downstream `_el_summary` consumer expects `ead_final`. **Divergence produces inconsistent EL vs RWA bases** (Art. 158/159 mismatch between calculator and aggregator). **Effort: S** | Ref: CRR Art. 158, Art. 159
- **P1.145** [ ] **NEW (Phase 9)** — Classifier `unique(subset=[exposure_reference], keep="first")` non-deterministic on duplicate permissions. `engine/classifier.py:832-844`. When `model_permissions` has duplicate rows for the same exposure, `keep="first"` depends on row order — which is not guaranteed. Changing input order can silently flip IRB↔SA. **Effort: S** | Ref: classifier model_permissions resolution
- **P1.146** [ ] **NEW (Phase 9)** — `is_guaranteed` null filter drops rows in CRM reporting. `engine/aggregator/_crm_reporting.py:138,166,212` filters on `is_guaranteed == True`. `engine/crm/guarantees.py:260` doesn't `fill_null(False)` before feeding the aggregator. Guaranteed exposures with null `is_guaranteed` are silently dropped from CR7/CR7A Pillar III disclosures. **Effort: S** | Ref: CR7/CR7A guarantee reporting
- **P1.147** [ ] **NEW (Phase 9)** — `ValidationRequest` does not require `model_permissions` for IRB permission mode. `src/rwa_calc/api/validation.py`. Missing file silently falls back to SA for all exposures when users have requested IRB. **Silent capital overstatement**. **Effort: S** | Ref: IRB permission gating
- **P2.22** [ ] **NEW (Phase 8)** — Supporting factors `min()` instead of Art. 501(2) substitution rule. `supporting_factors.py:324` uses `pl.min_horizontal(sme_factor, infra_factor)` when both SME and infrastructure factors apply. CRR Art. 501(2) second subparagraph says "multiply by the factor in Article 501a **instead**" — meaning infrastructure replaces SME when both qualify. `min()` picks SME 0.7619 over infra 0.75 — **capital understatement** (should use 0.75). Rare overlap. **Effort: S** | Ref: CRR Art. 501(2), Art. 501a(1)
- **P2.23** [ ] **NEW (Phase 8)** — Equity exposures excluded from output floor U-TREA/S-TREA. `_schemas.py:30-35` `FLOOR_ELIGIBLE_APPROACHES` only includes IRB/slotting. Equity gets `approach_applied="EQUITY"` which is not floor-eligible. Under B31, Art. 155 is blank (equity is SA-only), so IRB Simple equity doesn't exist post-2027. CRR equity IRB Simple RWA should be in U-TREA but isn't. Impact limited to CRR + transitional period. Additionally, S-TREA omits market (ASA), op (SMA), and CVA components entirely — `FLOOR_ELIGIBLE_APPROACHES` at `_schemas.py:30–35` lists only IRB/slotting. This calculator-scope limitation should be surfaced on `OutputFloorSummary` even if components remain out of scope. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P2.24** [ ] **NEW (Phase 8)** — Hierarchy resolver counterparty join may fan out on duplicate org_mappings. `hierarchy.py:491-501` joins counterparties with `org_mappings` without deduplicating by `child_counterparty_reference`. Multiple parent mappings (data quality issue) silently multiply exposure rows. **Effort: S**
- **P2.25** [ ] **NEW (Phase 9)** — CR5 special disclosure rules not implemented. `reporting/pillar3/generator.py:325-359` omits: (a) currency mismatch multiplier exposures reported at pre-multiplier RW with post-multiplier RWEA; (b) regulatory RE not-materially-dependent split up to / above 55% LTV; (c) equity transitional reported at end-state RW. **Effort: M** | Ref: PRA PS1/26 Annex XX §CR5
- **P2.26** [ ] **NEW (Phase 9)** — COREP Annex II sign-convention violated for (-) labelled columns. `reporting/corep/generator.py:3140-3214, 3385-3406` emits positive sums for columns 0030/0035/0050/0060/0070/0080/0090/0130/0140/0290, which are declared negative in Annex II §1.3. **PRA DPM validation will reject returns.** **Effort: S** | Ref: COREP Annex II §1.3
- **P2.27** [ ] **NEW (Phase 9)** — OF 08.01 col 0275 uses IRB EAD not SA-equivalent. `reporting/corep/generator.py:3615`. Annex II §OF 08.01 col 0275 requires SA-equivalent post-CCF / post-CRM EAD. Using IRB EAD overstates the non-modelled exposure denominator for the output floor. **Effort: S** | Ref: COREP Annex II §OF 08.01 col 0275
- **P2.28** [ ] **NEW (Phase 9)** — CR9 row taxonomy incomplete. `reporting/pillar3/templates.py:565-580` missing AIRB RE 4-way sub-class split (resi SME, resi non-SME, comm SME, comm non-SME) and FIRB "financial / large corporates" sub-row. **Effort: S** | Ref: PRA PS1/26 Annex XXII §CR9
- **P2.29** [ ] **NEW (Phase 9)** — OV1 equity sub-approach rows hard-coded null. `reporting/pillar3/generator.py:275-277`. B31 OV1 rows 11 (IRB Trans), 12 (LTA), 13 (MBA), 14 (Fall-back) always null despite the pipeline having the source columns. Rows 26/27 (floor multiplier / OF-ADJ) also null. **Effort: S** | Ref: PRA PS1/26 Annex XX §OV1
- **P2.30** [ ] **NEW (Phase 9)** — CCF Annex I row discrimination incomplete: Row 3 (non-credit-substitute issued OBS, 50%) not distinguishable from Row 4 (NIFs/RUFs). `domain/enums.py:346-403` exposes only 6 `RiskType` values versus the Annex I taxonomy. Reporting-only impact (RWA unaffected) but prevents Annex I-faithful disclosure. **Effort: S** | Ref: CRR Annex I
- **P2.31** [ ] **NEW (Phase 9)** — No Annex I concrete-item-to-risk-type mapping table in code or spec. `engine/ccf.py:76-122`. Users must manually map acceptances, performance bonds, warranties, tender bonds, etc. to the right Annex I row. **Silent misclassification risk** under CCF. **Effort: M** | Ref: CRR Annex I
- **P2.32** [ ] **NEW (Phase 9)** — CCF Art. 166(5) / Art. 166E(5) purchased-receivables 40%/10% not implemented. `engine/ccf.py` has no purchased-receivables branch. **Effort: M** | Ref: CRR Art. 166(5), PRA PS1/26 Art. 166E(5)
- **P2.33** [ ] **NEW (Phase 9)** — CCF UK residential mortgage commitment Row 4(b) 50% PRA deviation not enforceable. No flag or derivation for "UK residential mortgage commitment"; caller must manually tag as MR else falls through to OC = 40%. **UK-specific capital understatement risk** when un-tagged. **Effort: S** | Ref: PRA PS1/26 Annex I Row 4(b)
- **P2.34** [ ] **NEW (Phase 9)** — Output validation has no regulatory output-bounds checker. `src/rwa_calc/contracts/validation.py` validates inputs only; there is no `validate_aggregated_bundle` asserting RW ≤ 12.5, RWA ≥ 0, `ead_final` non-null. Corrupt results can leave the pipeline undetected. **Effort: S** | Ref: internal contract hardening
- **P2.35** [ ] **NEW (Phase 9)** — Hierarchy silently truncates at `max_depth=10`. `engine/hierarchy.py:233, 1908, 1942`. No error emitted when a parent chain exceeds 10 hops — rating inheritance and threshold aggregation simply stop. **Effort: S** | Ref: internal hierarchy contract
- **P2.36** [ ] **NEW** — Sovereign/institution PD floors not first-class config fields. `src/rwa_calc/contracts/config.py` `PDFloors`. No `sovereign`/`institution` fields; correct 0.05% floor applied by accident via corporate-floor fallback. **Effort: S** | Ref: PRA PS1/26 Art. 160(1)
- **P2.37** [ ] **NEW** — Art. 155(4) Internal Models Approach (CRR equity) entirely absent. `src/rwa_calc/engine/equity/`. VaR-based equity capital with PRA-permission gate. Lower priority than P1.153 (PD/LGD approach) as firms commonly use IRB Simple or PD/LGD first. **Effort: L** | Ref: CRR Art. 155(4)
- **P2.38** [ ] **NEW** — Non-trading-book short-position netting (Art. 155(2)) not modelled. `src/rwa_calc/engine/equity/`. Long equity holdings may be offset by qualifying hedged short positions. **Effort: M** | Ref: CRR Art. 155(2)
- **P2.39** [ ] **NEW** — Art. 147A(1)(h) equity SA-only not a hard block. `src/rwa_calc/engine/classifier.py:1039`, `_b31_sa_only`. Currently relies on absence of IRB permissions in `full_irb_b31()`. Add explicit `EQUITY` guard in `_b31_sa_only`. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(h)
- **P2.40** [ ] **NEW** — model_id precedence chain incomplete. `src/rwa_calc/engine/hierarchy.py:1288–1295`. Only counterparty-level `internal_model_id` consulted; spec specifies exposure → facility → loan → model_permissions default. **Effort: M** | Ref: model_permissions spec
- **P2.41** [ ] **NEW** — `exposure_subclass` for Art. 147A(1)(e)/(f) COREP split. `src/rwa_calc/engine/classifier.py`, `domain/enums.py`. Note: previously attributed to existing P2.28, but P2.28 actually covers CR9 row taxonomy. This is a separate need. **Effort: M** | Ref: PRA PS1/26 Art. 147A(1)(e)/(f)
- **P2.42** [ ] **NEW** — OF 02.01 col 0030 U-TREA should be 0010+0020 sum. `src/rwa_calc/engine/reporting/corep/generator.py:2988–2993`. Currently col 0030 copies `modelled_rwa` only; should be arithmetic sum per COREP instructions. **Effort: S** | Ref: COREP OF 02.01 instructions
- **P2.43** [ ] **NEW (D3.56 doc-writer, P19-07 closure)** — PSM LGD source switch (Art. 236(1)(a)(i) option (i)) not exposed. PRA PS1/26 Art. 236(1)(a)(i) gives firms a *choice* of LGD source for the covered portion: option (i) borrower-unprotected LGD (carry through borrower's modelled or supervisory LGD), option (ii) guarantor F-IRB LGD scalar. Only option (ii) is wired up in `engine/irb/guarantee.py::_apply_parameter_substitution`. Adding a `psm_lgd_source` switch on `IRBPermissions` (or `CalculationConfig`) would let firms elect option (i) where it produces a lower covered-portion charge. Distinct from P1.160 (which is about routing the right *table row* under option (ii)) — P2.43 is about supporting option (i) as an alternative source entirely. **Effort: S** | Ref: PRA PS1/26 Art. 236(1)(a)(i); `src/rwa_calc/contracts/config.py` (IRBPermissions); `src/rwa_calc/engine/irb/guarantee.py`
- **P2.44** [ ] **NEW (D4.59 doc-writer closure, 2026-05-03)** — Art. 139(2B) ECAI rating-attribution disapplication for SA specialised lending not enforced. PRA PS1/26 Art. 139(2B) (Appendix 1 p. 71) reads "Paragraphs 2 and 2A do not apply for the purposes of Article 122B(1)" — i.e. when an IRB firm routes an SA SL exposure through the rated pathway in Art. 122B(1) (Table 5A short-term ECRA), the engine must use only **directly applicable** ECAI assessments and ignore Art. 139(2)/(2A) inferred fallback ratings (issue-rating-based fallbacks etc.). Engine status: `src/rwa_calc/engine/sa/namespace.py` and the upstream loader at `src/rwa_calc/engine/loader.py` accept a single `external_cqs` field per exposure with no flag distinguishing a directly applicable rating from an Art. 139(2)/(2A) fallback, so SA SL exposures get whatever rating is supplied. Structurally identical to D3.60 (Art. 138(1)(g) / Art. 139(6) implicit-support flag) — preferred resolution is option (ii): add a `rating_is_issue_specific: Bool` (and/or `rating_is_inferred: Bool`) to the `Loan` / `Contingent` schema and gate Art. 122B(1) routing on it; integrates with the planned D3.60 fix. Cross-ref: D4.59 docs closure. **Effort: S–M** | Ref: PRA PS1/26 Art. 122B(1), Art. 139(2)/(2A)/(2B); `src/rwa_calc/engine/sa/namespace.py`, `src/rwa_calc/engine/loader.py`, `src/rwa_calc/data/schemas.py`
- **P2.45** [ ] **NEW (D4.60 doc-writer closure, 2026-05-03)** — Art. 143(6) Overseas Model Approach (OMA) not represented in the engine. PRA PS1/26 Art. 143(6)(a)–(k) (Appendix 1 p. 83) establishes a new B31 IRB permission allowing UK-parent groups to apply a foreign-supervisor-approved IRB approach to **retail and SME corporate exposures** of equivalent-jurisdiction overseas subsidiaries, capped at **7.5% of group RWA and 7.5% of group exposure value pre-output-floor**. Art. 143(7) auto-grandfathers pre-2027 CRR Art. 143 PRA permissions via deeming (no code needed); Art. 143(8) requires ongoing compliance. Engine status: no `ApproachType.OVERSEAS_MODEL_APPROACH` in `src/rwa_calc/domain/enums.py`, no jurisdiction-equivalence flag on `Loan` / `Contingent` / `model_permissions` (Art. 143(6)(b)), no aggregate-cap validation against the 7.5% group ceilings. Suggested resolution: (i) add OMA as a distinct routing option / approach enum value, (ii) jurisdiction-equivalence Boolean on `Loan` / `Contingent`, (iii) post-aggregation 7.5%-of-group RWA / exposure-value cap validation in `src/rwa_calc/engine/aggregator/`, (iv) Art. 143(6)(c)–(k) condition checks (likely Pillar III disclosure rather than blocking). Cross-ref: D4.60 docs closure. **Effort: M** | Ref: PRA PS1/26 Art. 143(6)(a)–(k), Art. 143(7), Art. 143(8), Glossary p. 79; `src/rwa_calc/domain/enums.py`, `src/rwa_calc/data/schemas.py`, `src/rwa_calc/engine/aggregator/`
- **P2.46** [ ] **NEW (D4.64 doc-writer closure, 2026-05-03)** — CRR Art. 150(1) PPU provenance enum on `model_permissions` data source. COREP OF 08.07 / C 08.07 col 0050 ("of which: Exposures under permanent partial use of SA") aggregates all SA-routed IRB-class exposures together — the engine cannot today distinguish Art. 150(1) PPU exposures (immaterial counterparties / equity carve-outs / sovereign exemption / etc.) from Art. 148 sequential roll-out exposures from no-permission-at-all SA exposures. A `ppu_reason` enum column on the `model_permissions` data source — values e.g. `art_150_1_a` (sovereign), `art_150_1_d` (immaterial), `art_150_1_h` (equity carve-out, CRR-only), `art_148_rollout`, `none` — would make col 0050 deterministically populable under the CRR pathway and unblock related disclosure rows. Sub-finding: **Art. 150(2) firm-level equity materiality test (10% / 5% of own funds) is not enforced anywhere in the engine.** This is a firm-level governance test — likely intentionally out of scope for the per-exposure RWA pipeline — but should be captured as an explicit non-goal in `docs/specifications/architecture.md` (or equivalent) rather than a silent gap. Engine touch points: `src/rwa_calc/data/sources.py`, `src/rwa_calc/contracts/config.py`, `src/rwa_calc/engine/reporting/corep/generator.py` (col 0050 emission). Cross-ref: D4.64 docs closure. **Effort: S–M** | Ref: CRR Art. 150(1)(a)–(j), Art. 150(2); PRA PS1/26 Art. 150(1A); `src/rwa_calc/data/sources.py`, `src/rwa_calc/contracts/config.py`
- **P2.47** [ ] **NEW (D4.74 doc-writer closure, 2026-05-03)** — Art. 136 ECAI grade strings and Art. 137 OECD MEIP direct-to-RW lookup not implemented; Art. 138 multi-assessment second-best selection also absent. The engine accepts only a raw integer `credit_quality_step` / `cp_sovereign_cqs` on sovereign and institution inputs (`src/rwa_calc/data/schemas.py:210, 745`); a grep across `src/rwa_calc/` for `MEIP|eca_score|export_credit|art_137|Art\. 136|Art\. 137` returns no functional matches. PRA PS1/26 (and CRR onshored, retained verbatim) requires three distinct lookup paths beyond CQS integers: **(a) Art. 136** — ECAI grade strings (e.g. "AAA", "BBB+") mapped to CQS via the PRA technical standard; **(b) Art. 137 Table 9** — OECD ECA / MEIP integers 0-7 mapping *directly* to risk weights `0%/0%/20%/50%/100%/100%/100%/150%` (this is **not** a CQS detour — MEIP 0/1 → 0%, MEIP 2 → 20%, MEIP 3 → 50%, MEIP 4-6 → 100%, MEIP 7 → 150%); **(c) Art. 121 sovereign-derived institution propagation** — when a sovereign is rated only by ECA, the same Table 9 RW must propagate to unrated institutions in the same jurisdiction under Art. 121(1) (CRR sovereign-derivation pathway, retained for institutions in jurisdictions still using sovereign-derived weights); **(d) Art. 138 second-best selection** — where two or more ECAI/ECA assessments apply, the second-best (i.e. higher-RW of the two best) must be chosen across both ECAI and ECA inputs. **Distinct from P1.100**: P1.100 is the narrow "ECA score → CQS" fallback for unrated sovereigns (treats ECA as a CQS proxy); P2.47 is the broader Art. 136/137/138 lookup architecture that distinguishes ECAI-grade-string input from MEIP-integer input from CQS-integer input and applies Table 9 *directly* (not via CQS) per Art. 137. **Capital impact:** unrated sovereigns and Art. 121 sovereign-derived institutions with low MEIP scores currently default to 100% instead of potentially 0% (MEIP 0-1) or 20% (MEIP 2); without Art. 138 second-best, exposures with multiple ratings may pick the lower (more favourable) rating contrary to regulation. Resolution: (i) new optional schema fields on `Loan` / `Contingent` loaders for ECAI grade string (resolvable via Art. 136 mapping table) and Art. 137 MEIP integer 0-7, both of which take precedence over a raw `credit_quality_step` when present; (ii) static `ART_137_MEIP_RW` table in `src/rwa_calc/data/tables/` with Decimal values per Table 9; (iii) classifier / SA calculator wiring so MEIP routes directly to Table 9 on Art. 114 sovereigns and propagates via Art. 121 to unrated institutions in the same jurisdiction; (iv) Art. 138 second-best selector across ECAI + ECA inputs. **Acceptance scenarios:** MEIP 0 (UK Export Finance equivalent → 0% sovereign), MEIP 3 (→ 50% sovereign), MEIP 7 (→ 150% sovereign), and an Art. 121 case where the sovereign is rated only by ECA and the institution inherits the sovereign-derived weight. Cross-ref: D4.74 docs closure (closed 2026-05-03 in batch b89fe59); P1.100 (narrow ECA-to-CQS fallback). **Effort: M** | Ref: PRA PS1/26 Art. 136, Art. 137 Table 9, Art. 138, Art. 121; CRR Art. 136-138 (onshored, retained); `src/rwa_calc/data/schemas.py`, `src/rwa_calc/engine/sa/calculator.py`, `src/rwa_calc/engine/classifier.py`
- **P2.48** [ ] **NEW (D4.82 doc-writer closure, 2026-05-03)** — Pillar III CR8 RWEA flow statement only populates closing row; rows 1 (opening) and 2-8 (flow drivers) emitted as `None`. `src/rwa_calc/reporting/pillar3/generator.py::_generate_cr8` (lines 690-718, verified 2026-05-03) iterates `CR8_ROWS` and assigns `closing_rwa` only to row 9; rows 1 and 2-8 fall through to `values = {"a": None}` because no multi-period comparison data is wired into the pipeline. PRA PS1/26 Annex XXII §11 (UKB CR8) requires the seven flow-driver rows to be populated for IRB firms: **row 1** opening RWEA, **row 2** asset size, **row 3** asset quality, **row 4** model updates, **row 5** methodology and policy, **row 6** acquisitions and disposals, **row 7** foreign-exchange movements, **row 8** other. **Sign-convention requirement:** flow values must follow the Annex XXII signed convention — increases positive, decreases negative. A £15m RWEA decrease must emit as `-15` (not `15` or `|15|`). The signed convention is documented in `docs/specifications/output-reporting.md` lines 349 / 356-366 and now also in `docs/features/pillar3-disclosures.md` (added in D4.82 closure, batch b89fe59); the engine implementation must respect it on emit. Resolution: (i) extend the Pillar 3 reporting boundary with an optional `previous_period_results: AggregatedResultBundle | None` input (likely on `CreditRiskCalc` / report-generation entry point) so a prior-period bundle can be passed alongside the current one; (ii) compute the seven CR8 flow drivers per Annex XXII §11 by diffing the two bundles along the published taxonomy (asset size = pure volume delta on unchanged exposures; asset quality = PD/LGD migration delta; model updates = parameter recalibration delta; methodology and policy = framework / policy delta; acquisitions and disposals = portfolio in/out delta; FX movements = currency-translation delta on unchanged-currency exposures; other = residual); (iii) emit each row as a signed Decimal, with decreases negative; (iv) preserve the existing row 9 closing RWEA path. **Acceptance scenarios:** (a) a portfolio with positive net flow (RWEA growth → all flow rows positive, row 9 = row 1 + sum(rows 2-8)); (b) a portfolio with a £15m RWEA decrease driven by asset disposal (row 6 = -15, row 9 = row 1 - 15); (c) a defaulted-exposure migration triggering an asset-quality (row 3) movement with the correct sign. Cross-ref: D4.82 docs closure (closed 2026-05-03 in batch b89fe59); P3.5 (CR9.1 generator stub, similar Pillar III completeness gap). **Effort: M** | Ref: PRA PS1/26 Annex XXII §11 (UKB CR8); `src/rwa_calc/reporting/pillar3/generator.py:690-718`, `src/rwa_calc/reporting/pillar3/templates.py` (CR8_ROWS, CR8_COLUMNS); `docs/specifications/output-reporting.md:349,356-366`; `docs/features/pillar3-disclosures.md`
- **P2.49** [ ] **NEW (D4.84 doc-writer closure, 2026-05-03)** — CR9 column-`a` row taxonomy missing F-IRB and A-IRB sub-classes mandated by PRA PS1/26 Annex XXII pp. 19-20. `src/rwa_calc/reporting/pillar3/templates.py::CR9_FIRB_CLASSES` (lines 574-580) and `CR9_AIRB_CLASSES` (lines 565-572) under-emit relative to the Annex XXII column-`a` row definitions: **F-IRB missing** sub-class 2.2 "Financial corporates and large corporates" (Art. 147(2)(c)(ii) / Art. 147A driver — note this is the same gap flagged at a high level by P2.28's "FIRB financial/large corporates sub-row", which P2.49 supersedes with the explicit Annex XXII row label) and sub-class 2.4 "Other general corporates — non-SMEs" (Art. 147(2)(c)(iii)); **A-IRB missing** sub-class 1.3 "Other general corporates — non-SMEs" and the seven mandated retail sub-classes currently collapsed into `retail_mortgage` / `retail_qrre` / `retail_other` — namely 2.1 RRE-SME, 2.2 RRE-non-SME, 2.3 CRE-SME, 2.4 CRE-non-SME, 2.5 QRRE, 2.6 Other-SME, 2.7 Other-non-SME (P2.28's "AIRB RE 4-way split" captured the four RRE/CRE × SME/non-SME rows but missed QRRE and the two Other-SME / Other-non-SME rows; P2.49 expresses the full seven-row retail taxonomy). **Supersedes P2.28** — P2.28 should be marked `[~] Superseded by P2.49` once P2.49 lands. **Work scope:** (i) extend `CR9_FIRB_CLASSES` with sub-classes 2.2 and 2.4; (ii) extend `CR9_AIRB_CLASSES` with sub-class 1.3 and the seven retail sub-classes; (iii) update `_generate_cr9` aggregation in `src/rwa_calc/reporting/pillar3/generator.py` so each new sub-class receives the correct exposure-class filter; (iv) add unit tests in `tests/unit/reporting/pillar3/` for each new row; (v) verify that the corresponding classifier columns exist on the exposures frame (financial corporate flag, large corporate flag, retail RRE/CRE/QRRE/Other × SME/non-SME) — flag any missing classifier inputs as a follow-up P-coded item. Cross-ref: closes the code-side residual of D4.84 (docs-side fix landed in `docs/features/pillar3-disclosures.md` 2026-05-03). **Effort: M** | Ref: PRA PS1/26 Annex XXII paras 12-15 and column-`a` row definitions on pp. 19-20 of `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`; PS1/26 Appendix 1 Art. 147(2)(b)-(d) and Art. 147A; `src/rwa_calc/reporting/pillar3/templates.py:565-580`, `src/rwa_calc/reporting/pillar3/generator.py`
- **P2.9** [ ] OF 34.07 — IRB CCR template. CCR is out of scope; document as known gap or add placeholder. **Effort: S**
- **P4.20** [ ] C 08.02 PD bands use fixed buckets instead of firm-specific internal rating grades. **Effort: M**

### Tier 4 — Pillar III Disclosure Gaps

- **P3.5** [ ] **NEW** — CR9.1 (ECAI-based PD backtesting) has template definitions but no generator method, no bundle field, no stub. P3.2 marked [x] Complete but CR9.1 is not callable. **Effort: S**
- **P3.3** [~] Missing qualitative tables UKB CRD (SA qualitative, Art. 444(a-d)) and UKB CRE (IRB qualitative, Art. 452(a-f)). CR6 AIRB purchased receivables sub-row missing. CR5 rows 18-33 not detailed. **Effort: M**
- **P3.6** [ ] **NEW (Phase 9)** — CR5 / CR9 / OV1 disclosure gaps overlap with P2.25/P2.28/P2.29. Pillar III tables cannot faithfully reproduce Annex XX / XXII rows without: (a) pre-multiplier RW column for currency-mismatch disclosure, (b) equity transitional end-state RW column, (c) AIRB RE 4-way sub-class split, (d) FIRB financial/large-corp sub-rows, (e) OV1 equity sub-approach populations. Track alongside the P2 items but call out for Pillar III sign-off. **Effort: M** | Ref: PRA PS1/26 Annex XX §CR5/OV1, Annex XXII §CR9

### Tier 5 — Documentation & Consistency

- **P4.2** [~] Stale version numbers — `overview.md` says 0.1.37, `prd.md` says 0.1.28; `IMPLEMENTATION_PLAN.md` header previously said 0.1.202; current `pyproject.toml` is **0.2.6** (master branch, 2026-05-03). Plan header re-baselined this pass; docs side still drifted. **Effort: S**
- **P4.3** [~] Stale `docs/plans/implementation-plan.md` — shows items as incomplete that are done. **Effort: S**
- **P4.4** [~] Stale PRD FR statuses. **Effort: S**
- **P4.8** [~] COREP template spec thin in `output-reporting.md` — detailed in `corep-reporting.md` feature doc. Cross-reference needed. **Effort: S**
- **P4.9** [~] Type checker inconsistency — docs disagree with CLAUDE.md (`mypy` vs `ty`). **Effort: S**
- **P4.10** [~] `model_permissions` not in architecture spec. **Effort: S**
- **P4.23** [ ] **NEW** — Stale test counts in `regulatory-compliance.md` (shows 97 CRR, 116 B31, 275 total; actual: 169 CRR, 212 B31, 497 acceptance). **Effort: S**
- **P4.24** [ ] **NEW** — Stale NFR metrics in `nfr.md` (shows 1,844+ total tests; actual: 5,188). Also: protocol count mismatch — NFR claims "All 6 stages"; actual is 9 stage protocols in `contracts/protocols.py`. Polars namespace count mismatch — NFR-5.3 claims 8 namespaces; actual is 2 (`slotting`, `irb`). `src/rwa_calc/engine/slotting/namespace.py`, `engine/irb/namespace.py`. **Effort: S**
- **P4.25** [ ] **NEW** — Stale acceptance test scenario counts in `index.md` (spec says 97 CRR, 116 B31). **Effort: S**
- **P4.26** [ ] **NEW** — Stale PD floor values in `irb/formulas.py` docstring (says retail mortgage 0.05%, should be 0.10%; QRRE transactor 0.03%, should be 0.05%). Runtime code is correct. **Effort: S**
- **P4.27** [ ] **NEW** — Stale PD floor values in `.claude/skills/basel31/references/irb-changes.md`. Same P4.5 error not fixed in skill reference. **Effort: S**
- **P4.28** [ ] **NEW** — Stale column count in `reporting/corep/templates.py` docstring (says "24/22 columns" for C 07.00, actual is 27/27). **Effort: S**
- **P4.29** [ ] **NEW** — Stale "Not Yet Implemented" in `docs/user-guide/regulatory/basel31.md` for currency mismatch (line 186-187) and defaulted treatment (line 196). Both are implemented. **Effort: S**
- **P4.30** [ ] **NEW** — Regulatory compliance matrix (`docs/specifications/regulatory-compliance.md`) severely outdated: claims 97 CRR / 116 B31 tests, actual is 169 CRR / 212 B31. Missing groups B31-K (defaulted), B31-L (equity), B31-M (model permissions), CRR-J (equity), CRR-D2 (advanced CRM). Undermines regulatory evidence. **Effort: S**
- **P4.31** [ ] **NEW** — Skill reference `slotting-changes.md` shows BCBS pre-op PF weights (80/100/120/350%) as PRA B31; PRA has no separate pre-op table (verified from PDF page 103). **Effort: S**
- **P4.32** [ ] **NEW** — Skill reference files (`references/*.md`) need systematic audit for stale BCBS-derived values. **Effort: S**
- **P4.33** [ ] **NEW** — Stale BCBS output floor references in source code docstrings. `comparison.py:18` says "50% (2027) to 72.5% (2032+)", `bundles.py:489` same, `ui/marimo/comparison_app.py:14-15` same, `docs/specifications/technical-reference.md` (contains BCBS 6-year transitional schedule references). Runtime code uses correct PRA schedule. **Effort: S**
- **P4.47** [ ] **NEW (Phase 9)** — Informational: PS1/26 output-floor transitional is ONLY 3 years (60% 2027, 65% 2028, 70% 2029 per Art. 92(5)); 2030+ falls back to Art. 92(2A) 72.5%. Plan text elsewhere correctly states 55%→72.5% for BCBS — note that **Art. 92(5)(d) does not exist** in PRA PS1/26 (the PRA schedule has only sub-clauses (a)-(c)). Audit any spec/docstring that cites Art. 92(5)(d) and correct to Art. 92(5)(a)-(c) + Art. 92(2A). **Effort: S** | Ref: PRA PS1/26 Art. 92(5), Art. 92(2A)
- **P4.48** [ ] **NEW** — Covered bond Art. 161(1B) references. `src/rwa_calc/engine/irb/firb_lgd.py:256, 263, 698, 717, 776, 804`. Article number doesn't exist; correct reference is Art. 161(1)(d). Value (11.25%) is correct. **Effort: S**
- **P4.49** [ ] **NEW** — CCF docstrings cite Art. 166(9) for 20% trade LC. `src/rwa_calc/engine/irb/ccf.py:7, 132, 150, 164, 189`. Correct reference is Art. 166(8)(b). Art. 166(9) is the overlapping-commitment lower-of rule. **Effort: S**
- **P4.51** [ ] **NEW** — `ExposureClass` docstring letter typos. `src/rwa_calc/domain/enums.py:52, 76, 91`. `HIGH_RISK` docstring cites Art. 112(l) → should be (k). `INSTITUTION` cites (d) → should be (f). **Effort: S**
- **P4.52** [ ] **NEW** — `ciu_holdings` table absent from `docs/specifications/architecture.md`. Data-model section does not list `CIUHoldings` despite bundle field and full pipeline integration. **Effort: S**
- **P4.53** [ ] **NEW** — Undocumented CalculationConfig fields. `docs/specifications/configuration.md`. `PostModelAdjustmentConfig` (PRA PS9/24 PMAs), `collect_engine`, `spill_dir` (streaming execution) not in spec. **Effort: S**
- **P4.54** [ ] **NEW** — fastexcel vs xlsxwriter inconsistency. `docs/specifications/overview.md` vs `docs/specifications/output-reporting.md`. Pick one library and align both spec pages. **Effort: S**
- **P4.55** [ ] **NEW** — Document new B3.1 sovereign/institution PD floors (pairs with P2.36). `docs/specifications/basel31/firb-calculation.md` and `airb-calculation.md`. **Effort: S**

### Tier 6 — Code Quality

- **P6.15** [~] 3 missing schema fields — see Tier 1 above.
- **P6.16** [ ] **NEW (Phase 9)** — `approach_applied="EQUITY"` uppercase while all other approaches are lowercase. `engine/aggregator/_equity_prep.py:23`. Breaks `FLOOR_ELIGIBLE_APPROACHES` set-membership and any group-by comparison that assumes case-normalised values. **Effort: S**
- **P6.17** [ ] **NEW (Phase 9)** — Pre-floor `rwa_final` naming collision. `engine/pipeline.py:487-490`. Consumers reading `sa_results` / `irb_results` see pre-floor values under the label `rwa_final`, creating ambiguity against the post-floor `rwa_final` on the aggregated bundle. **Effort: S**
- **P6.18** [ ] **NEW (Phase 9)** — Loader `_load_file_optional` swallows all exceptions. `engine/loader.py:232-234`. Bare `except Exception` silently turns a corrupt optional file into "absent", hiding data-quality issues. Replace with narrow `(FileNotFoundError,)` + logged `CalculationError` for anything else. **Effort: S**
- **P6.19** [ ] **NEW (Phase 9)** — `DataSourceRegistry` missing `ciu_holdings` entry. `config/data_sources.py:44-141`. Registry-driven loading silently drops CIU look-through data. **Effort: S**
- **P6.20** [ ] **NEW (Phase 9)** — `CreditRiskCalc.base_currency` never forwarded. `api/service.py:76-86, 165-182`. User setting a non-GBP base currency is a silent no-op. **Effort: S**
- **P6.21** [ ] **NEW (Phase 9)** — `_compute_portfolio_waterfall` eagerly collects mid-pipeline. `engine/comparison.py:754-763, 387`. Breaks the LazyFrame-first contract in `CLAUDE.md`. Should operate on LazyFrame and only collect at the API boundary. **Effort: S**
- **P6.22** [ ] **NEW (Phase 9)** — `CapitalImpactAnalyzer` supporting-factor attribution divides by 1.06 for CRR IRB. `engine/comparison.py:693-698`. Under-attributes supporting-factor impact by ~6% in the waterfall (diagnostic output only, not regulatory RWA). **Effort: S**
- **P6.23** [ ] **NEW (Phase 9)** — `_TRANSITIONAL_REPORTING_DATES` hardcoded to mid-year. `engine/comparison.py:231-236`. Uses `date(YYYY, 6, 30)` but PRA effective dates are 1 Jan. Comparison reports show stale floor multipliers for H1 of each transitional year. **Effort: S** | Ref: PRA PS1/26 Art. 92(5)
- **P6.24** [ ] **NEW** — `LazyFrameResult` mutability across stage boundaries. `src/rwa_calc/contracts/errors.py:86`. Not `frozen=True`; exposes `add_error`/`add_errors` mutation methods; crosses stage boundaries via `CRMProcessorProtocol.apply_crm`. Contradicts immutable-bundle architecture principle. **Effort: S**
- **P6.25** [ ] **NEW (D3.52 doc-writer, P19-03 closure)** — Factory-method asymmetry for CRM/A-IRB collateral knobs. `CalculationConfig.crr()` (`src/rwa_calc/contracts/config.py:895`) does expose `crm_collateral_method` but NOT `airb_collateral_method`; `CalculationConfig.basel_3_1()` (`:953`) exposes both. Doc-writer flagged that some users reach for `dataclasses.replace` to set these knobs because the asymmetry hides the option, which is inconsistent with the existing `enable_double_default` (CRR-only) and `use_investment_grade_assessment` (B31-only) factory args. Action: add explicit framework-appropriate defaults to both factory signatures and document the no-op semantics where applicable (e.g. `airb_collateral_method=None` under CRR is a deliberate no-op until A-IRB permission gating is in place). Aligns with D3.50/D3.51 follow-ups. **Effort: S** | Ref: `src/rwa_calc/contracts/config.py:838,843,895-906,953-971`; `src/rwa_calc/domain/enums.py` (`CRMCollateralMethod`, `AIRBCollateralMethod`)
- **P6.26** [ ] **NEW (curator audit 2026-05-03)** — Lone source-tree TODO marker contradicting plan header's "0 TODO/FIXME/HACK" claim. `engine/hierarchy.py:2034` reads `# TODO(qrre-coupling): also set in _undrawn_select_expressions; consolidate.` inside the QRRE undrawn-flag derivation block. The TODO references duplication between the QRRE flag computation and `_undrawn_select_expressions`, which compose `is_revolving` / `is_qrre_transactor` / `facility_limit` defaults independently. The duplication is a maintainability risk (changing the QRRE coupling rule in one place but not the other), not a calculation bug. Action: refactor the two sites to share a single helper, or mark the TODO closed if the duplication is intentional and document why. **Effort: S** | Ref: `src/rwa_calc/engine/hierarchy.py:2030-2050`

**Note on P6.16–P6.23 ID collision (identified 2026-04-18):** The Tier 6 bullet list entries P6.16–P6.23 added in Phase 9 (this file lines ~199–206) conflict with pre-existing detailed `### P6.16` through `### P6.21` subsections (lines 1517–1562, all `[x]` Complete). The Phase 9 entries are distinct new items but reuse the completed IDs. This collision has NOT been silently fixed; it is documented here for a future renumbering pass. Downstream references to P6.16–P6.21 are ambiguous until resolved.

### Tier 7 — Future / v2.0 (Not Yet Planned)

- **P7.1** [ ] Stress testing integration (M4.3)
- **P7.2** [ ] Portfolio-level concentration metrics (M4.4)
- **P7.3** [ ] REST API (M4.5)
- **P7.4** [ ] Additional exposure classes: securitisation, CIU beyond fallback, purchased receivables, dilution risk
- **P7.5** [ ] **NEW** — Additional CRM methods not in scope: Art. 217 basket credit derivatives (first/nth-to-default), Art. 219 on-balance-sheet netting, Art. 214 counter-guarantees by sovereigns, Art. 215(2) mutual guarantee schemes, Art. 222(5) derivative cash collateral 0%, Art. 230(3) UK IRB 50% RW property option, Art. 197(4) unrated bond eligibility route
- **P7.5** [ ] **NEW** — Art. 150(1A) materiality/immateriality thresholds for IRB firms using SA for immaterial classes. Currently only in COREP templates, not in the engine. **Effort: M**
- **P7.6** [ ] **NEW** — Art. 147B roll-out class tracking in the classification engine (currently only in COREP reporting). **Effort: M**
- **P7.7** [ ] **UPGRADED TO P1.105** — moved to Tier 1 (Table 4A can produce *higher* RWs than Table 4 fallback for CQS 2-3, causing risk understatement).

---

**Open P1 items: 37 total (23S + 12M + 1L + 1 verification).** P1.92 fixed in v0.1.62; P1.135 and P1.136 fixed in v0.1.63; P1.111 fixed in v0.1.197; P1.133 fixed in v0.1.201. Phase 9 added 13 new P1 items (P1.135-P1.147). Highest priority (Phase 9 remaining): **P1.137 (equity transitional Rule 4.2/4.3 SA ladder — M, 2027-2029 capital overstatement for SA-only firms)**, **P1.140 (ADC classification flag-only — M, mis-tagging silently routes development loans to 75-100%)**, **P1.142 (Art. 124E three-property limit not automated — M)**, **P1.141 (Art. 124(4) mixed RE splitting — M)**. Remaining priority (prior phases): **P1.123 (FCCM HE for SFTs — M, capital understatement)**, **P1.122 (guarantee substitution no B31 branching — M, multiple incorrect RWs)**, **P1.130 (aggregator summaries pre-floor — S, reporting inconsistency)**, **P1.109 (guarantee maturity mismatch — M)**, **P1.124 (guarantee eligibility rejection — S)**, **P1.128 (SCRA trade finance <=6m — S)**, P1.93 (core market participant — M), P1.95 (guarantor SCRA — M, subsumed by P1.122), P1.96 (covered bond haircut — S, DOWNGRADED), P1.97 (B31 slotting subgrade — S), P1.98 (subordinated LGD floor — S), P1.99 (CRR short-term institution — S), P1.100 (ECA score — S), P1.101 (non-daily revaluation — S), P1.103 (Table 6A — S), P1.104 (FCSM maturity — S), P1.105 (Table 4A — S), P1.106 (FCSM institution UK — S), P1.107 (FCSM B31 corp CQS 3 — S), P1.108 (CRR retail 1.06 — S, DISPUTED), P1.110 (guarantee CQS table — S, subsumed by P1.122), P1.112 (PSE/RGLA sovereign — S), P1.114 (classifier null — S), P1.117 (HVCRE subgrades — S), P1.118 (Art. 162(3) maturity — M), P1.121 (CRR unrated inst short-term — S), P1.125 (FSE column warning — S), P1.126 (null revenue — S), P1.127 (Pool B composition — S, verification), P1.138 (equity Rule 4.6 IRB higher-of — M), P1.139 (equity Rule 4.8 CIU higher-of — M), P1.143 (Rule 4.11 unfunded CP grandfathering — M), P1.144 (EL fallback ead_final — S), P1.145 (classifier duplicate-permission non-determinism — S), P1.146 (is_guaranteed null drops rows — S), P1.147 (ValidationRequest model_permissions not required — S), P1.30(e) (tranching — L), P1.10 (transitional — M).

**Phase 9 audit (2026-04-18):** Lead-auditor review with 4 Sonnet sub-agents plus 2 verification agents. All 30 open P1 items from Phase 8 re-verified as still open; P1.115 and P1.89/P1.132 fixes confirmed correct; no silent fixes detected. Package version 0.1.193.

Phase 9 added **13 new P1 items** (P1.135–P1.147), **11 new P2 items** (P2.25–P2.35), **1 new P3 item** (P3.6), **1 new P4 item** (P4.47), and **8 new P6 items** (P6.16–P6.23):

High-impact capital correctness (P1):
- **P1.135** FX haircut on collateral silently zero after FX conversion — Art. 224 8% H_fx NEVER applied to FX-mismatched secured exposures. HIGH capital understatement.
- **P1.136** FXConverter `original_currency` preserved only for exposures/guarantees, not collateral/provisions/equity — root cause of P1.135.
- **P1.137/P1.138/P1.139** Equity transitional ladder missing across SA (Rule 4.2/4.3), IRB higher-of (Rule 4.6), and CIU higher-of (Rule 4.8). Capital overstatement 2027–2029 for SA-only firms; understatement for legacy-permissioned IRB/CIU firms.
- **P1.140** ADC classification flag-only — mis-tagged CRE/RRE development loans silently weighted 75-100% instead of 150%.
- **P1.141** Art. 124(4) mixed RE splitting not implemented.
- **P1.142** Art. 124E three-property BTL rule not automated.
- **P1.143** Rule 4.11 unfunded-CP grandfathering window not honoured (distinct from P1.10 which is the underlying Art. 213 eligibility).
- **P1.144** EL fallback to gross EAD when `ead_final` absent — divergence from `_el_summary` consumer.
- **P1.145** Classifier `unique(..., keep="first")` non-deterministic on duplicate permissions — row order flips IRB↔SA.
- **P1.146** `is_guaranteed` null filter drops rows from CR7/CR7A.
- **P1.147** `ValidationRequest` does not require `model_permissions` — silent SA fallback for IRB requests.

Reporting completeness (P2 / P3):
- **P2.25** CR5 special disclosure rules (currency mismatch pre-multiplier RW, RE ≤/> 55% LTV split, equity end-state RW).
- **P2.26** COREP Annex II sign-convention violated for (-) labelled columns — PRA DPM will reject returns.
- **P2.27** OF 08.01 col 0275 uses IRB EAD, requires SA-equivalent.
- **P2.28** CR9 row taxonomy incomplete (AIRB RE 4-way + FIRB financial/large-corp).
- **P2.29** OV1 equity sub-approach rows 11-14 and 26/27 hard-coded null.
- **P2.30/P2.31** CCF Annex I row discrimination + concrete-item mapping gap.
- **P2.32** CCF Art. 166(5) / 166E(5) purchased-receivables 40%/10% not implemented.
- **P2.33** CCF UK residential mortgage commitment Row 4(b) 50% deviation not enforceable.
- **P2.34** Output validation has no regulatory output-bounds checker.
- **P2.35** Hierarchy silently truncates at `max_depth=10`.
- **P3.6** Pillar III CR5/CR9/OV1 overlap with P2.25/28/29 — call-out for Pillar III sign-off.

Documentation / informational (P4.47): PS1/26 output-floor transitional is 3 years only (Art. 92(5)(a)-(c)); Art. 92(5)(d) does not exist. Audit any citation referencing 92(5)(d).

Code quality (P6.16-P6.23): EQUITY casing mismatch, pre-floor `rwa_final` naming collision, loader broad `except Exception`, `DataSourceRegistry` missing `ciu_holdings`, `CreditRiskCalc.base_currency` silent no-op, `_compute_portfolio_waterfall` eager collect, CapitalImpactAnalyzer 1.06 mis-division, `_TRANSITIONAL_REPORTING_DATES` mid-year.

Phase 9 verification findings:
- All 30 open P1 items from Phase 8 remain open (no silent fixes, no drift from stated line numbers).
- P1.115 (CRR Art. 230 subordinated F-IRB LGDS) fix confirmed correct in v0.1.191.
- P1.89 (B31 PE/VC 400%) and P1.132 (B31 government-supported equity 250%) fixes confirmed correct.
- No new regressions detected in Phase 8 fixes.

---

**Phase 8 audit (2026-04-10):** Full spec-vs-PDF-vs-code cross-audit with 20+ Sonnet + 3 Opus parallel agents. Test run: 5,178 passed, 21 skipped, 11 deselected. Zero TODO/FIXME/HACK in source.

Phase 8 added **7 new P1 items**, **3 new P2 items**, and **5 spec file corrections**:
- **P1.128** (B31 SCRA short-term missing Art. 121(4) trade finance <=6m extension — capital overstatement for 3-6m trade finance).
- **P1.129** (B31 ADC pre-sold 100% concession not restricted to residential — capital understatement for commercial ADC).
- **P1.130** (Aggregator summaries use pre-floor RWA — reporting inconsistency when floor is binding).
- **P1.131** (Pipeline bundle reconstruction drops `output_floor_summary` — silently discards floor data on error accumulation).

Phase 8 spec file corrections:
- **B31 sa-risk-weights.md**: Added PSE/RGLA sovereign-derived RW section (FR-1.14/1.15/1.16), covered bond section (Art. 129 rated Table 7 + unrated SCRA derivation + Art. 129(4A) due diligence), fixed SCRA article references (Art. 120(2A) → Art. 121).
- **B31 provisions.md**: Added bug admonition flagging `_el_summary.py` 50/50 CET1/T2 split as wrong (should be 100% CET1 per Art. 36(1)(d)).
- **B31 slotting-approach.md**: Corrected HVCRE EL table — removed spurious short-maturity EL columns (EL is flat per Art. 158(6) Table B), fixed Good EL from 0.4% to 0.8%.
- **CRR sa-risk-weights.md**: Fixed ECA score mapping typo (CQS 4-5 → CQS 4-6).

Phase 8 PDF-driven corrections to existing P1 items:
- **P1.93 corrected**: Article reference changed from "Art. 222(4)(d)" to "Art. 222(4)/(6)" — PRA PS1/26 Art. 222 has no sub-clause (d). Core market participant distinction is in Art. 222(4)+Art. 227(3), not a separate sub-clause.
- **P1.96 downgraded**: PDF confirms covered bonds are NOT listed in PRA PS1/26 Art. 197 as eligible financial collateral. Impact limited to narrow Art. 207(2) repo scenario.
- **P1.115 confirmed bug**: PRA PS1/26 Art. 230 has no subordinated LGDS (code correct for B31). CRR PDF (p.228) confirms Table 5 retains subordinated LGDS: receivables 65%, RE 65%, other physical 70%. Code only has senior rows — CRR-only capital understatement.

Phase 8 additional PDF-driven corrections:
- **P1.113 corrected**: Detailed subsection had stale CQS values (said code has CQS 4=25%, CQS 5=35%). Actual code has CQS 4=50%, CQS 5=50% (correct). Only CQS 2 (15%→20%) and CQS 6 (50%→100%) are bugs. Also added Art. 129A→Art. 129(4) reference fix and DataFrame line numbers.
- **P1.132 NEW**: B31 government-supported equity applies 100% RW but PRA PS1/26 Art. 133 has no 100% legislative category. Old CRR Art. 133(3)(c) removed in B31. Should be 250% (standard). Capital understatement.
- **B31 sa-risk-weights.md**: Fixed SME threshold typo — "GBP 440m" → "GBP 44m" (two locations). Code correctly uses `44_000_000`.

Phase 8 Opus deep-analysis agents (SA/aggregator, IRB/CRM, equity/slotting):
- SA Opus agent found **2 new P1 items**: P1.133 (short-term maturity uses residual instead of original), P1.134 (B31 unrated CB with rated issuer → 100% instead of CQS-derived).
- Aggregator/pipeline Opus agent found **3 new P2 items**: P2.22 (supporting factors min→substitution), P2.23 (equity excluded from floor U-TREA), P2.24 (hierarchy join fan-out). P2.21 expanded from `regulatory_reference` only to all CalculationError metadata loss.
- IRB/CRM agent found **no new issues** beyond existing P1 items — comprehensive validation of Phase 5-7 IRB/CRM findings.
- All existing P1 items re-verified against current codebase — no regressions, all issues still present as documented.
- Detailed P1.119-P1.131 subsections added to the Priority 1 section with Status, Impact, File:Line, Spec ref, Fix, and Tests needed.

**Phase 7 audit (2026-04-10):** Full regulatory PDF extraction + spec correction + Opus code verification. 15 spec files updated. Test run: 5,178 passed, 21 skipped, 11 deselected. Zero TODO/FIXME/HACK in source.

Phase 7 added **7 new P1 items**, **4 new P2 items**, upgraded P2.13→P1.123, corrected P1.113 description:
- **P1.121** (CRR Art. 121(3) unrated institution short-term 20% missing — capital overstated by up to 100%).
- **P1.122** (Guarantee substitution has no B31 framework branching at all — subsumes P1.95/P1.110; multiple incorrect B31 guarantee RWs).
- **P1.123** (FCCM missing exposure volatility haircut HE for SFTs — upgraded from P2.13; understates E* for SFT portfolios).
- **P1.124** (Art. 237(2) guarantee ineligibility conditions not enforced — short-dated guarantees accepted when they should be rejected).
- **P1.125** (Classifier missing FSE column warning — FSEs silently get A-IRB when column absent).
- **P1.126** (Classifier null revenue → A-IRB permitted for potentially large corporates).
- **P1.127** (Art. 159 Pool B upstream composition — two-branch rule may be wrong if AVA not in per-exposure shortfall).
- **P1.113 corrected**: Only CQS 2 (15%→20%) and CQS 6 (50%→100%) are wrong; CQS 4/5 are already correct at 50%.
- **P2.18** (Art. 226(1) non-daily revaluation haircut scaling — NR factor missing).
- **P2.19** (Higher-risk equity Art. 133(4) input flags missing — relies on pre-classification).
- **P2.20** (`total_rwa_post_floor` naming misleading — excludes SA/equity).
- **P2.21** (Pipeline error conversion drops `regulatory_reference`).

Phase 7 also confirmed via Opus code verification + CRR PDF extraction:
- **P1.108 DISPUTED**: UK-onshored CRR Art. 154(1) text includes 1.06 in retail formula (page 151). BCBS CRE31.23 does not. Code may be correct under UK CRR. Needs PRA legal clarification.
- F-IRB FSE vs non-FSE LGD (45%/40%): **correctly implemented** in `firb_lgd.py:46-63`
- SME correlation GBP thresholds (4.4-44M): **correctly implemented** in `formulas.py:509-511`
- Retail LGD floors (resi 5%, QRRE 50%, other 30%): **correctly implemented** in `config.py:134-137`
- Retail PD floors (QRRE revolvers 0.1%, transactors 0.05%, mortgage 0.1%): **correctly implemented**
- UK residential RW floor 10%: **implemented via PMA** in `adjustments.py:205-229`
- Art. 159 two-branch rule: **correctly implemented** in `_el_summary.py:217-231`
- Art. 159(d) 0.6% T2 cap: **correctly implemented** in `_el_summary.py:236`
- Double default A-IRB restriction: **correctly implemented** in `guarantee.py:371-379`
- Output floor PRA 4-year transitional: **correctly implemented** in `config.py:429-434`

Phase 6 added **6 new P1 items**, **6 new P4 items**, and **1 new P5 item:**
- **P1.113** (B31 rated covered bond RW uses BCBS CRE20.28 values — CQS 2 = 15% vs PRA 20%, CQS 6 = 50% vs PRA 100%. Capital understatement).
- **P1.114** (Classifier null propagation in str.contains() for model_permissions — silent SA fallback when country_code/book_code is null).
- **P1.115** (CRR Art. 230 Table 5 subordinated F-IRB LGDS missing — 35%/35%/40% used for all seniorities, should be 65%/65%/70% for subordinated. Capital understatement).
- **P1.116** ~~(EL shortfall deduction 50% CET1 + 50% T2 instead of 100% CET1 per Art. 36(1)(d). Affects OF-ADJ)~~ **FIXED v0.1.185** — corrected to 100% CET1 per Art. 36(1)(d); also corrected OF-ADJ cascading impact.
- **P1.117** (B31 HVCRE short-maturity subgrades — distinct from P1.97; Strong A=70%/B=95%, Good C=95%/D=120%).
- **P1.118** (Art. 162(3) short-maturity IRB override — qualified short-term exposures should use actual maturity not M=2.5).
- **P1.119** ~~(CIU fallback RW wrong under BOTH frameworks)~~ **FIXED v0.1.184** — corrected to 1,250% per Art. 132(2).
- **P1.120** (B31 SA defaulted provision-ratio denominator uses unsecured_ead instead of gross_outstanding_amount per Art. 127(1). Capital overstatement for collateralised defaults. D3.19).
- **P4.34-P4.39** (6 documentation items: SCRA article ref, currency mismatch article ref, slotting flat weight contradiction, retail PD floor article ref, provisions Pool A/B labelling, slotting EL rate table).
- **P5.15** (Art. 123A(1)(b)(ii) 0.2% portfolio granularity sub-condition not implemented).

Phase 5 added **7 new P1 items** and **1 new P4 item:**
- **P1.108** (CRR 1.06 scaling applied to retail IRB — 6% overstatement, most impactful finding). Affects all CRR retail IRB exposures — non-defaulted path uniformly applies 1.06 but Art. 154(1) has no 1.06 for retail. Defaulted path already correctly exempts retail.
- **P1.109** (guarantee maturity mismatch missing — capital understatement). Art. 237-238 maturity mismatch is applied to collateral but NOT to guarantees/CDS. Significant scope: any guarantee with shorter maturity than the exposure.
- **P1.110** (B31 guarantee CQS table uses CRR corporate weights). CQS 3 corporate guarantor substitution uses 100% under B31 instead of 75% per Table 6. Conservative overstatement.
- **P1.106** (FCSM institution bond UK deviation — conservative overstatement).
- **P1.107** (FCSM B31 corporate CQS 3 — conservative overstatement).
- **P1.111** ~~(RRE income-producing junior multiplier capped at 105% instead of 131.25% — capital understatement for junior liens at high LTV)~~ **FIXED v0.1.197**.
- **P1.112** (non-UK unrated PSE/RGLA default to 100% instead of sovereign-derived CQS lookup — capital overstatement).
- **P4.33** (stale BCBS output floor docstrings in 3 source files).

Sovereign/institution PD floor behaviour confirmed correct — falls through to corporate floor (0.05% B31 / 0.03% CRR) per regulation.

## Status Legend
- [ ] Not started
- [~] Partial / needs rework
- [x] Complete

---

## Priority 1 -- Calculation Correctness Gaps

These items affect regulatory calculation accuracy under CRR or Basel 3.1.

### P1.9 Output Floor -- OF-ADJ, portfolio-level application, U-TREA/S-TREA
- **Status:** [~] Partial (1 sub-issue remains; (a), (b), (d) complete)
- **Fixed (a) and (b):** 2026-04-07
- **Impact:** The output floor implementation has four related gaps:
  - **(a) OF-ADJ implemented:** FIXED (2026-04-07). OF-ADJ = 12.5 × (IRB_T2 - IRB_CET1 - GCRA + SA_T2) now computed and applied to the floor formula. IRB_T2 (Art. 62(d) excess provisions, capped) and IRB_CET1 (Art. 36(1)(d) shortfall + Art. 40 supervisory add-on) are derived from the internal EL summary. GCRA (general credit risk adjustments, capped at 1.25% of S-TREA per Art. 92 para 2A) and SA_T2 (Art. 62(c) SA T2 credit) are institution-level config inputs on `OutputFloorConfig`. `compute_of_adj()` function exported from `_floor.py`. EL summary now computed BEFORE the output floor in the aggregator (was after). `OutputFloorSummary` extended with `of_adj`, `irb_t2_credit`, `irb_cet1_deduction`, `gcra_amount`, `sa_t2_credit` fields. `CalculationConfig.basel_3_1()` accepts `gcra_amount`, `sa_t2_credit`, `art_40_deductions` params. 28 new unit tests in `tests/unit/test_of_adj.py`.
  - **(b) Floor is exposure-level, not portfolio-level:** FIXED. Previously `_floor.py` applied `max(rwa_pre_floor, floor_rwa)` per exposure row, systematically overstating capital. Now computes portfolio-level U-TREA and S-TREA, applies `TREA = max(U-TREA, x * S-TREA)`, and distributes any shortfall pro-rata by `sa_rwa` share. Slotting exposures now included in floor scope via `FLOOR_ELIGIBLE_APPROACHES` (were previously excluded). `OutputFloorSummary` dataclass added to `contracts/bundles.py` with `u_trea`, `s_trea`, `floor_pct`, `floor_threshold`, `shortfall`, `portfolio_floor_binding`, `total_rwa_post_floor` fields, and attached to `AggregatedResultBundle`.
  - **(c) U-TREA/S-TREA COREP export:** `OutputFloorSummary` is now on `AggregatedResultBundle` so U-TREA/S-TREA are accessible. Full `OF 02.01` COREP template wiring (4-column comparison) not yet done — tracked under P2.
  - **(d) Transitional floor rates are permissive, not mandatory:** FIXED (2026-04-08). Art. 92 para 5 says institutions "may apply" the 60/65/70% transitional rates. `OutputFloorConfig.basel_3_1(skip_transitional=True)` bypasses the PRA 4-year transitional schedule and applies 72.5% immediately. `CalculationConfig.basel_3_1(skip_transitional_floor=True)` propagates. When skipped, `get_floor_percentage()` returns 72.5% for any date (no transitional_start_date gate). Docstrings document Art. 92 para 5 optionality. 28 new tests in `tests/unit/test_output_floor_skip_transitional.py`.
- **File:Line:** `engine/aggregator/_floor.py`, `engine/aggregator/_schemas.py`, `engine/aggregator/aggregator.py`, `contracts/bundles.py`
- **Spec ref:** `docs/specifications/output-reporting.md` lines 28-46, PRA PS1/26 Art. 92 para 2A/3A/5
- **Fix remaining:** None — all sub-items (a), (b), (d) complete. Only (c) U-TREA/S-TREA COREP template wiring remains (tracked under P2).
- **Tests:** 24 new unit tests in `tests/unit/test_portfolio_level_floor.py`. Acceptance test B31-F2 updated (`is_floor_binding` now portfolio-level flag). All tests pass.

### P1.10 Unfunded credit protection transitional (PRA Rule 4.11)
- **Status:** [ ] Not implemented (low priority — underlying eligibility checks not yet implemented)
- **Impact:** PRA PS1/26 Rule 4.11 is a **narrow eligibility-condition carve-out**, not a broad permission to use CRR calculation methods. During 1 Jan 2027 to 30 Jun 2028, it reads Art. 213(1)(c)(i) and Art. 183(1A)(b) with the words "or change" omitted for unfunded credit protection entered before 1 Jan 2027. This means legacy contracts that allow the provider to *change* (but not cancel) the protection remain eligible during the transitional window. All other Basel 3.1 CRM calculation changes (haircuts, method taxonomy, parameter substitution LGD) apply from day one regardless. The underlying eligibility checks (Art. 213(1)(c)(i) "change clause" check) are not yet implemented in the calculator, making this transitional provision currently moot.
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 Rule 4.11, Art. 213(1)(c)(i), Art. 183(1A)(b)
- **Fix:** Implement Art. 213 eligibility validation first (with "change clause" check). Then add `protection_inception_date` field and transitional date logic to relax the check for legacy contracts.
- **Tests needed:** Unit tests for eligibility validation + transitional date logic.

### P1.30 CRM method selection decision tree (Art. 191A)
- **Status:** [~] Partial — (a)(b)(c)(d)(f) complete; (e) remains
- **Impact:** Basel 3.1 Art. 191A defines a formal four-part CRM method selection: CCR/non-CCR split, on-BS netting, FCCM vs FCSM election, Foundation Collateral Method for immovable property/receivables/other physical under IRB, life insurance/institutional instrument method. `crm/processor.py` hardwires Comprehensive Method for funded CRM and risk-weight/parameter substitution for unfunded. `CRMCollateralMethod` config enum supports COMPREHENSIVE/SIMPLE election.
  **CRM sub-methods status:**
  - (a) FCSM (Art. 222) — **COMPLETE** (P1.7). 20% RW floor, SA-only, qualifying repo 0% (Art. 222(4)/(6)).
  - (b) Life insurance method (Art. 232) — **COMPLETE** (2026-04-07). `life_insurance` collateral type added to schemas, constants, haircut calculator. SA treatment: mapped risk weight table (insurer RW → secured portion RW: 20%→20%, 30%/50%→35%, 65%/100%/135%→70%, 150%→150%) with no 20% floor unlike FCSM. No SA EAD reduction (life insurance excluded from eligible financial collateral). F-IRB treatment: LGDS = 40% in Art. 231 waterfall. A-IRB: own LGD estimate. Life insurance gets 0% supervisory haircut (surrender value is the effective collateral value). FX mismatch haircut still applies. `compute_life_insurance_columns()` pre-computes `life_ins_collateral_value` and `life_ins_secured_rw` per exposure. SA calculator `_apply_life_insurance_rw_mapping()` blends risk weight. New module: `engine/crm/life_insurance.py`. Schema additions: `insurer_risk_weight` (Float64), `credit_event_reduction` (Float64).
  - (c) Credit-linked notes (Art. 218) — **COMPLETE** (2026-04-07). CLN type normalized to "cash" in haircut calculator (0% haircut). Added to `FINANCIAL_TYPES` in constants.py for correct category classification (financial collateral, LGDS = 0%). Added to `VALID_COLLATERAL_TYPES`. Convention: users set `market_value = nominal_value - credit_event_reduction`.
  - (d) Art. 227 zero-haircut conditions — **COMPLETE** (2026-04-07). Institution certifies all 8 conditions (a)-(h) via `qualifies_for_zero_haircut` Boolean on collateral schema. Calculator validates collateral type eligibility (cash/deposit or CQS ≤ 1 sovereign bond). Both H_c and H_fx set to 0% for qualifying items. Works in both pipeline (LazyFrame) and single-item paths. 34 unit tests.
  - (e) Partial protection tranching (Art. 234) — structured protection covering only part of the loss range. Not modelled. Spec notes this as future enhancement.
  - (f) Foundation Collateral Method for IRB (immovable property/receivables/other physical). Already implemented via LGDS/OC ratio system in collateral.py; not separately named.
- **File:Line:** `engine/crm/processor.py`, `engine/crm/collateral.py`, `engine/crm/constants.py`, `engine/crm/haircuts.py` (Art. 227 + Art. 232), `engine/crm/simple_method.py` (FCSM), `engine/crm/life_insurance.py` (Art. 232), `engine/sa/calculator.py` (life insurance RW mapping)
- **Spec ref:** PRA PS1/26 Art. 191A, Art. 218, Art. 227, Art. 232, `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix remaining:** Add partial protection tranching (Art. 234).
- **Tests:** 34 Art. 227 tests in `tests/unit/crm/test_art227_zero_haircut.py`, 49 FCSM tests in `tests/unit/crm/test_simple_method.py`, 35 life insurance + CLN tests in `tests/unit/crm/test_life_insurance.py`.

### P1.93 FCSM Art. 222(4) SFT zero-haircut 0%/10% and Art. 222(6) same-currency exceptions
- **Status:** [ ] Not started (2026-04-08 — identified in audit; article refs corrected 2026-04-10 per PDF extraction)
- **Impact:** PRA PS1/26 Art. 222(4) allows 0% RW for SFTs meeting Art. 227 zero-haircut conditions; 10% if counterparty is not a core market participant per Art. 227(3). Art. 222(6) allows 0% for same-currency cash or 0%-weighted sovereign debt with 20% market value discount. The code's `_is_zero_rw_exception_expr()` partially covers Art. 222(6)(a)/(b) but does not implement the Art. 222(4) SFT/Art. 227 branch at all. No `is_core_market_participant` field exists in schema. Note: PRA Art. 222 has no sub-clause "(d)" — the original P1.93 description incorrectly referenced "Art. 222(4)(d)".
- **File:Line:** `engine/crm/simple_method.py:134` (`_is_zero_rw_exception_expr`)
- **Spec ref:** PRA PS1/26 Art. 222(4)/(6), Art. 227(2)/(3)
- **Fix:** Add `is_core_market_participant` Boolean to COUNTERPARTY_SCHEMA (or derive from entity_type per Art. 227(3) list). Add SFT+Art.227 branch: 0% if core market participant, 10% otherwise. Verify Art. 222(6) gating is complete.
- **Tests needed:** Unit tests for SFT with core market participant (0%), non-core (10%), same-currency cash (0%), and mixed scenarios.

### P1.94 B31 currency mismatch 1.5x missing 150% cap — CONFIRMED
- **Status:** [ ] Not started — confirmed from PS1/26 final rules text (2026-04-08)
- **Impact:** `_apply_currency_mismatch_multiplier()` at `sa/calculator.py:1762` applies `risk_weight * 1.5` without any cap. PS1/26 Art. 123B final text explicitly states "capped at 150%". Exposures with base RW > 100% (e.g., defaulted 150%) produce 225% instead of the correct 150%.
- **File:Line:** `engine/sa/calculator.py:1762`
- **Spec ref:** PRA PS1/26 Art. 123B
- **Fix:** Add `.clip(upper_bound=1.50)` after the `* 1.5` multiplication in `_apply_currency_mismatch_multiplier()`.
- **Tests needed:** Unit tests for currency mismatch on exposures with base RW > 100%.

### P1.95 B31 guarantee substitution uses CRR CQS-based RW for unrated institution guarantors instead of SCRA
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** Under Basel 3.1, unrated institution guarantors should use SCRA grades (A→40%, B→75%, C→150%) for the substituted risk weight. The current implementation at `sa/calculator.py:1568-1582` applies 40% (UK CQS 2 deviation) for all unrated institution guarantors regardless of framework. This means B31 exposures guaranteed by SCRA grade B or C institutions get an incorrect (too low) substituted risk weight.
- **File:Line:** `engine/sa/calculator.py:1568-1582`
- **Spec ref:** PRA PS1/26 Art. 121 (SCRA risk weights), Art. 235 (guarantee substitution)
- **Fix:** In the guarantee substitution logic, add a B31 branch: when `framework == "basel_3_1"` and guarantor is an unrated institution, look up SCRA grade from `guarantor_scra_grade` column instead of using the CQS-based sovereign fallback. Requires adding `guarantor_scra_grade` to the schema if not already present.
- **Tests needed:** Acceptance tests for B31 guarantee substitution with SCRA grade A, B, and C institution guarantors.

### P1.96 Covered bond collateral haircut falls through to `other_physical`
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `_normalize_collateral_type_expr` in `engine/crm/haircuts.py` does not recognise `covered_bond` or `covered_bonds` as a distinct collateral type. They fall through to the `otherwise(pl.lit("other_physical"))` branch and receive a 40% supervisory haircut. CRR Art. 197(1)(d)/224(1) assigns covered bonds a specific lower haircut based on CQS (e.g., CQS 1: 1%, CQS 2: 4.5%). This means covered bond collateral is significantly undervalued, leading to higher-than-required RWA for covered-bond-secured exposures. Note: the LGD waterfall in `collateral.py` correctly assigns LGDS=11.25% for covered bonds — only the haircut lookup is wrong.
- **File:Line:** `engine/crm/haircuts.py:_normalize_collateral_type_expr`
- **Spec ref:** CRR Art. 197(1)(d), 224(1); PRA PS1/26 CRE22 Table 10
- **Fix:** Add `covered_bond`/`covered_bonds` to the normalisation expression mapping to a `"covered_bond"` key, and add covered bond rows to the supervisory haircut lookup table with CQS-dependent values.
- **Tests needed:** Unit tests for covered bond haircut lookup at each CQS level; integration test verifying end-to-end EAD with covered bond collateral.

### P1.97 B31 slotting missing non-HVCRE subgrade maturity differentiation (Art. 153(5)(d))
- **Status:** [ ] Not started (2026-04-08; PRA PDF verified 2026-04-08)
- **Impact:** PRA PS1/26 Art. 153(5) Table A uses subgrade columns A/B (Strong) and C/D (Good) for maturity-based differentiation. Art. 153(5)(d) says firms "may" use column A/C (short-maturity <2.5yr) instead of B/D (>=2.5yr) — optional but should be supported. Non-HVCRE subgrades: Strong A=50% vs B=70%, Good C=70% vs D=90%. Satisfactory/Weak/Default have no maturity split. The CRR implementation correctly has 4 table variants (`SLOTTING_RISK_WEIGHTS`, `_SHORT`, `_HVCRE`, `_HVCRE_SHORT`), but B31 only has 3 (`B31_SLOTTING_RISK_WEIGHTS`, `_PREOP`, `_HVCRE`) — no `_SHORT` variants. The `lookup_rw()` method in `namespace.py:408-416` ignores `is_short` for B31. Impact: Strong non-HVCRE uses 70% instead of 50% (<2.5yr), Good uses 90% instead of 70% — up to 40% RW overstatement on well-rated short-dated SL. HVCRE subgrades tracked separately as P1.117.
- **Note:** `B31_SLOTTING_RISK_WEIGHTS_PREOP` correctly uses same weights as operational — PRA PS1/26 does NOT adopt BCBS CRE33.7 separate pre-operational PF table (confirmed from PRA PDF page 103: all SL types including PF use the same Table A).
- **File:Line:** `data/tables/b31_slotting.py` (missing SHORT table), `engine/slotting/namespace.py:408-416` (B31 branch ignores `is_short`), `engine/slotting/namespace.py:217-221` (missing `is_short` arg for B31)
- **Spec ref:** PRA PS1/26 Art. 153(5)(c)-(d) Table A columns A-D
- **Fix:** Add `B31_SLOTTING_RISK_WEIGHTS_SHORT` (Strong=50%, Good=70%, Satisfactory=115%, Weak=250%) to `b31_slotting.py`. Update `lookup_rw()` B31 non-HVCRE branch to check `is_short`. Update caller to pass `is_short=col("is_short_maturity")` for B31. HVCRE SHORT table tracked in P1.117.
- **Tests needed:** Unit tests for B31 non-HVCRE short-maturity slotting RW lookup; acceptance tests for B31-E slotting scenarios with <2.5yr residual maturity.

### P1.98 Subordinated corporate A-IRB LGD floor fallback uses 50% instead of 25%
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `_lgd_floor_expression` in `engine/irb/formulas.py:157-166` has a fallback path (when `exposure_class` column is absent but `seniority` is present) that applies `floors.subordinated_unsecured` (50%) to subordinated exposures. PRA PS1/26 Art. 161(5) states 25% floor for all corporate unsecured (senior and subordinated) — there is no 50% subordinated distinction for corporate A-IRB. The 50% floor only applies to retail QRRE unsecured. The primary path (when `exposure_class` IS present) correctly routes all corporate to 25%. Conservative overstatement — no capital understatement.
- **File:Line:** `engine/irb/formulas.py:157-166` (fallback branch), `contracts/config.py:126` (`subordinated_unsecured` default)
- **Spec ref:** PRA PS1/26 Art. 161(5); `docs/specifications/crr/airb-calculation.md` lines 50-51
- **Fix:** Remove seniority-based branching in the fallback path — apply `floors.unsecured` (25%) for all corporate regardless of seniority. Consider removing `subordinated_unsecured` from `LGDFloors` or renaming to `retail_qrre_unsecured` if it's only valid for QRRE.
- **Tests needed:** Unit test for LGD floor on subordinated corporate exposure without `exposure_class` column.

### P1.99 CRR short-term institution risk weights (Art. 120) not applied
- **Status:** [x] **CLOSED 2026-05-03 — silently fixed (curator audit)**
- **Verification:** `INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR` exists at `data/tables/crr_risk_weights.py:140-147` with CQS1-3 = 20%, CQS4-5 = 50%, CQS6 = 150% per Art. 120(2) Table 4. The CRR SA chain at `engine/sa/namespace.py:486-494` applies it via `chain.when(is_institution & is_rated & (residual_mty <= 0.25))`. Audit pass 2026-05-03 confirmed implementation matches Table 4 from PS1/26 Art. 120 PDF extract (page 41 of `docs/assets/ps126app1.pdf`). No remaining work.

### P1.100 Art. 137 ECA score-to-CQS mapping not implemented
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** Unrated sovereigns with Export Credit Agency (ECA) consensus risk scores (0-7) should be mapped to CQS 1-6 via CRR Art. 137 Table 9: ECA 0-1 → CQS 1 (0%), ECA 2 → CQS 2 (20%), ECA 3 → CQS 3 (50%), ECA 4-6 → CQS 4-6 (100%), ECA 7 → CQS 7 (150%). No `eca_score` field exists in the counterparty or ratings schema. Unrated sovereigns currently default to 100%, which overstates capital for low-risk unrated sovereigns (ECA 0-2).
- **File:Line:** `data/schemas.py` (missing field), `engine/sa/calculator.py` (sovereign RW logic)
- **Spec ref:** CRR Art. 137, Table 9
- **Fix:** Add `eca_score` optional field to counterparty or ratings schema. In sovereign RW logic, when CQS is null, check for ECA score and map to CQS equivalent. The ECA-to-CQS mapping table is static and small.
- **Tests needed:** Unit tests for unrated sovereign with ECA scores 0-7.

### P1.101 Art. 226(1) non-daily revaluation haircut adjustment not implemented
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** CRR Art. 226(1) requires supervisory haircuts to be scaled when collateral is revalued less frequently than daily: `H_adj = H_m × sqrt((NR + T_m - 1) / T_m)` where NR = number of business days between revaluations and T_m = liquidation period. Code implements Art. 226(2) liquidation period scaling but has no reference to NR (revaluation frequency). When collateral is marked-to-market weekly (NR=5) instead of daily (NR=1), the haircut should be ~22% larger (for T_m=10), leading to understatement of haircuts and thus understatement of capital requirements.
- **File:Line:** `engine/crm/haircuts.py` (liquidation period scaling section)
- **Spec ref:** CRR Art. 226(1); PRA PS1/26 preserves this treatment
- **Fix:** Add `revaluation_frequency_days` optional field to collateral schema (default=1 for daily). Apply NR scaling alongside existing liquidation period scaling.
- **Tests needed:** Unit tests for haircut with weekly/monthly revaluation frequencies.

### P1.109 Art. 237-238 maturity mismatch not applied to unfunded credit protection
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5 by Opus SA/CRM analysis agent)
- **Impact:** **Capital understatement for exposures with short-dated guarantees/CDS.** CRR Art. 237-238 require maturity mismatch treatment for ALL credit protection (funded AND unfunded). The current implementation applies the Art. 238 adjustment formula `GA = G* × (t - 0.25) / (T - 0.25)` only to **collateral** (via `haircuts.py:apply_maturity_mismatch()` called from `collateral.py:267`). Guarantees in `guarantees.py` apply FX haircut and restructuring exclusion haircut but NO maturity mismatch. Art. 237(2) ineligibility conditions are also not checked for guarantees: (a) residual maturity < 3 months → guarantee is ineligible, (b) original maturity < 1 year → guarantee is ineligible. This means a guarantee with 6 months remaining is treated as fully effective when it should be ineligible, and a guarantee with 2 years remaining on a 5-year exposure is treated at 100% instead of `(2 - 0.25) / (5 - 0.25) = 37%` effectiveness.
- **File:Line:** `engine/crm/guarantees.py` (no maturity mismatch logic), `engine/crm/processor.py` (guarantee processing path has no maturity mismatch step)
- **Spec ref:** CRR Art. 237(2) (ineligibility conditions), Art. 238 (adjustment formula); PRA PS1/26 preserves Art. 237-238
- **Fix:** Add `_apply_guarantee_maturity_mismatch()` function to `guarantees.py` following the collateral pattern in `haircuts.py:apply_maturity_mismatch()`. Check Art. 237(2) ineligibility conditions first (residual < 3m → zero, original < 1y → zero). Then apply Art. 238 adjustment to `guaranteed_portion`. Needs `guarantee_maturity_date` and `exposure_maturity_date` columns (both available in current schemas). Wire into `apply_guarantees()` after FX haircut.
- **Tests needed:** Unit tests for guarantee maturity mismatch (ineligibility at <3m, adjustment formula, no mismatch when guarantee >= exposure). Acceptance test CRM-D5b for guarantee maturity mismatch scenario.

### P1.110 B31 guarantee substitution CQS table uses CRR corporate weights
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5 by Opus SA/CRM analysis agent)
- **Impact:** **Conservative capital overstatement under B31.** The guarantee substitution logic in `sa/calculator.py:1630-1631` maps corporate guarantor CQS 3-4 to 100% risk weight. Under B31 Art. 122(2) Table 6, CQS 3 = 75% (not 100%). The guarantee substitution method at line ~1420 takes `config` but never branches on `config.is_basel_3_1` for corporate CQS weights, always using the CRR table. This means B31 exposures guaranteed by CQS 3 corporate guarantors get substituted RW of 100% instead of 75%. Related to but distinct from P1.95 (which is about unrated institution guarantors and SCRA grades). Impact: exposures with base RW between 75%-100% will miss beneficial guarantee substitution, and exposures with base RW > 100% will get 100% instead of 75%.
- **File:Line:** `engine/sa/calculator.py:1630-1631` (corporate guarantor CQS branch)
- **Spec ref:** PRA PS1/26 Art. 122(2) Table 6 (CQS 3 = 75%), Art. 235 (guarantee substitution)
- **Fix:** In the guarantee substitution method, add a B31 branch for corporate guarantor CQS weights: CQS 1 → 20%, CQS 2 → 50%, CQS 3 → 75%, CQS 4 → 100%, CQS 5 → 150%, CQS 6 → 150%. Use the same B31 table already in `_apply_risk_weights()`.
- **Tests needed:** Unit tests for B31 guarantee substitution with CQS 3 corporate guarantor (should get 75%, not 100%).

### P1.108 CRR 1.06 scaling factor incorrectly applied to retail IRB exposures
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5 by Opus IRB analysis agent)
- **Impact:** **Capital overstatement for retail IRB under CRR (6% overstated).** CRR Art. 153(1) defines the IRB RWA formula with 1.06 scaling for corporate, institution, and sovereign exposure classes. CRR Art. 154(1) defines a separate retail formula: `RWA = K × 12.5 × EAD` — no 1.06 factor and no maturity adjustment. The current code applies 1.06 uniformly to ALL exposure classes under CRR. Three code paths affected:
  - `formulas.py:360`: `scaling_factor = 1.06 if apply_scaling else 1.0` (bulk vectorized path)
  - `namespace.py:488`: `scaling_factor = 1.06 if config.is_crr else 1.0` (Polars namespace path)
  - `formulas.py:1033`: `scaling = 1.06 if apply_scaling_factor else 1.0` (scalar path)
  The defaulted exposure path at `adjustments.py:83` correctly exempts retail: `pl.when(is_retail).then(pl.lit(1.0)).otherwise(pl.lit(1.06))`. This is the same pattern needed in the non-defaulted path. Basel 3.1 is unaffected (1.06 removed entirely). The spec at `firb-calculation.md` line 168 also incorrectly states the 1.06 formula without qualifying it as non-retail only.
- **File:Line:** `engine/irb/formulas.py:360` (bulk), `engine/irb/namespace.py:488` (namespace), `engine/irb/formulas.py:1033` (scalar)
- **Spec ref:** CRR Art. 153(1) (non-retail with 1.06), CRR Art. 154(1) (retail without 1.06)
- **Fix:** In all three paths, condition the 1.06 scaling on exposure class: apply 1.06 only when CRR AND NOT retail (i.e., not containing "RETAIL", "MORTGAGE", "QRRE"). Use the same `is_retail` check pattern already in `adjustments.py:74-80`. Also update `firb-calculation.md` to note 1.06 is non-retail only.
- **Tests needed:** Unit tests verifying retail CRR IRB gets scaling=1.0, non-retail CRR IRB gets 1.06, all B31 gets 1.0. Regression tests for affected acceptance tests.

### P1.106 FCSM collateral RW for institution bonds ignores framework differentiation
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5; revised 2026-04-18 after P1.149 clarification)
- **Impact:** **Conservative capital overstatement under B31 only.** `_derive_collateral_rw_expr()` in `engine/crm/simple_method.py:90-91` maps institution bonds CQS 2-3 to 50% risk weight under both frameworks. Under PRA PS1/26 ECRA (B31), CQS 2 institutions are 30%, so FCSM-collateralised B31 exposures backed by CQS 2 institution bonds get RW = max(50%, 20%) = 50% instead of max(30%, 20%) = 30%. CRR Art. 120 Table 3 correctly gives CQS 2 = 50% (no deviation). Note: this differs from the original ticket framing — there is no CRR "UK deviation"; the 30% value applies only under Basel 3.1 / PRA PS1/26.
- **File:Line:** `engine/crm/simple_method.py:90-91` (institution CQS 2-3 both mapped to 50%)
- **Spec ref:** PRA PS1/26 Art. 120 ECRA Table 3
- **Fix:** In `_derive_collateral_rw_expr()`, when `is_basel_3_1=True`, map CQS 2 institutions to 30% instead of 50%. CRR branch unchanged.
- **Tests needed:** Unit tests for FCSM collateral RW with B31 institution CQS 2 bonds (expect 30%); regression guard for CRR branch (expect 50%).

### P1.107 FCSM collateral RW for B31 corporate CQS 3 bonds uses 100% instead of 75%
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5)
- **Impact:** **Conservative capital overstatement.** `_derive_collateral_rw_expr()` in `engine/crm/simple_method.py:110-111` maps corporate CQS 3 to 100%. Under B31 Art. 122(2) Table 6, CQS 3 = 75%. When `is_basel_3_1=True`, only CQS 5 is updated (100% → 150%) but CQS 3 is not (remains at CRR 100% instead of B31 75%). Impact: secured portion RW = max(100%, 20%) = 100% instead of max(75%, 20%) = 75%. Overstates capital by 25 percentage points on the secured portion for B31 FCSM exposures backed by CQS 3 corporate bonds.
- **File:Line:** `engine/crm/simple_method.py:110-111` (corporate CQS 3 = 100%, not framework-aware)
- **Spec ref:** PRA PS1/26 Art. 122(2) Table 6 (CQS 3 = 75%)
- **Fix:** In the `is_basel_3_1` branch, add CQS 3 → 75% for corporate bonds. Also verify CQS 4 (CRR 100% vs B31 100% — no change needed).
- **Tests needed:** Unit tests for FCSM collateral RW with B31 corporate CQS 3 bonds.

### P1.113 B31 rated covered bond risk weights use BCBS CRE20.28 values, not PRA Table 7
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** **Capital understatement for CQS 2 and CQS 6 covered bonds under B31.** `b31_risk_weights.py:276-283` defines covered bond risk weights as: CQS 1=10%, CQS 2=15%, CQS 3=20%, CQS 4=50%, CQS 5=50%, CQS 6=50%. PRA PS1/26 Art. 129(4) Table 7 specifies: CQS 1=10%, CQS 2=20%, CQS 3=20%, CQS 4=50%, CQS 5=50%, CQS 6=100%. **Two bugs:** CQS 2 (15% vs 20%, 33% understatement) and CQS 6 (50% vs 100%, 50% understatement). CQS 1/3/4/5 are correct. Code comment and DataFrame at line 311 also reference non-existent "Art. 129A" — should be Art. 129(4). Both dict (`B31_COVERED_BOND_RISK_WEIGHTS`) and DataFrame (`_create_b31_covered_bond_df`) affected.
- **File:Line:** `data/tables/b31_risk_weights.py:276-283` (dict), `:308-313` (DataFrame)
- **Spec ref:** PRA PS1/26 Art. 129(4) Table 7
- **Fix:** Update CQS 2 → `Decimal("0.20")` and CQS 6 → `Decimal("1.00")` in both the dict and DataFrame. Fix article reference from "Art. 129A" to "Art. 129(4)".
- **Tests needed:** Unit tests for B31 covered bond risk weights at each CQS level; acceptance tests verifying end-to-end RWA for covered bonds.

### P1.114 Classifier null propagation in str.contains() for model_permissions resolution
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** When `cp_country_code` or `book_code` is null on an exposure row and the model_permissions field is non-null, `str.contains(null)` propagates null into `permission_valid` in the classifier model_permissions resolution logic at `classifier.py:805,809`. This causes the entire permission check to evaluate to null, which then causes silent SA fallback for exposures that should qualify for IRB based on other permission criteria (e.g., exposure class match alone). Primarily affects exposures with incomplete counterparty data that have valid model permissions.
- **File:Line:** `engine/classifier.py:805,809`
- **Spec ref:** Classifier model_permissions resolution logic
- **Fix:** Add `.fill_null("")` on the `cp_country_code` and `book_code` columns before they enter `str.contains()` in the permission validation expression. Empty string will not match any country/book restriction, correctly failing the geographic constraint rather than propagating null.
- **Tests needed:** Unit tests for model_permissions resolution with null country_code and null book_code.

### P1.117 B31 HVCRE short-maturity subgrades not implemented
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** PRA PS1/26 Art. 153(5)(d) Table A defines HVCRE maturity-based subgrades distinct from non-HVCRE (tracked in P1.97). HVCRE subgrades: Strong A=70% (<2.5yr) vs B=95% (>=2.5yr), Good C=95% (<2.5yr) vs D=120% (>=2.5yr). Currently `namespace.py:408-416` ignores `is_short` for ALL B31 slotting including HVCRE. No `B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` table exists in `b31_slotting.py`. Using 95% instead of 70% for short-maturity Strong HVCRE overstates by 36%; using 120% instead of 95% for short-maturity Good HVCRE overstates by 26%.
- **File:Line:** `data/tables/b31_slotting.py` (missing HVCRE_SHORT table), `engine/slotting/namespace.py:408-416` (ignores is_short for B31)
- **Spec ref:** PRA PS1/26 Art. 153(5)(d) Table A columns A-D
- **Fix:** Add `B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` table (Strong=70%, Good=95%, Satisfactory=140%, Weak=250%) to `b31_slotting.py`. Update `lookup_rw()` B31 HVCRE branch to check `is_short`. Coordinate with P1.97 fix (non-HVCRE SHORT table).
- **Tests needed:** Unit tests for B31 HVCRE short-maturity slotting RW lookup; acceptance tests for B31-E HVCRE scenarios with <2.5yr maturity.

### P1.118 Art. 162(3) short-maturity IRB override not implemented
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** CRR Art. 162(3) and PRA PS1/26 Art. 162(3) specify that qualified short-term exposures should use M = actual maturity value (often << 2.5 years) instead of the default M = 2.5 in the IRB capital formula. Qualified exposures include: (a) OTC derivative contracts with maturity <= 1 year, (b) securities financing transactions (repos, securities lending) with maturity <= 1 year, (c) short-term self-liquidating trade finance, (d) certain FX settlement exposures. The `has_one_day_maturity_floor` flag exists in the schema but only affects CRM maturity mismatch treatment, not the maturity adjustment (MA) component of the IRB K formula. Without this, short-term repos and trade finance exposures get M=2.5 instead of their actual maturity, significantly overstating the maturity adjustment.
- **File:Line:** `engine/irb/formulas.py` (maturity adjustment calculation), `data/schemas.py` (has_one_day_maturity_floor)
- **Spec ref:** CRR Art. 162(3), PRA PS1/26 Art. 162(3)
- **Fix:** Add `is_qualified_short_term` Boolean field (or derive from exposure characteristics). In the IRB maturity adjustment calculation, when `is_qualified_short_term=True`, use actual residual maturity (floored at 1 day per Art. 162(3)) instead of default M=2.5. Requires `residual_maturity_years` field on exposures.
- **Tests needed:** Unit tests for IRB MA with qualified short-term exposures (repos, trade finance); acceptance tests verifying M != 2.5 for qualified exposures.

### P1.120 B31 SA defaulted provision-ratio denominator wrong (D3.19)
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 6)
- **Impact:** **Capital overstatement for collateralised defaulted exposures.** Art. 127(1) requires `specific_provisions / gross_outstanding_amount` but code uses `unsecured_ead` (post-provision, post-CRM). For partially collateralised exposures, the smaller denominator can push the ratio below 20%, inflating RW from 100% to 150%.
- **File:Line:** `engine/sa/calculator.py:1250-1275` (defaulted provision ratio calculation)
- **Spec ref:** PRA PS1/26 Art. 127(1), `docs/specifications/basel31/defaulted-exposures.md` D3.19
- **Fix:** Replace `unsecured_ead` with `gross_outstanding_amount` in the provision ratio denominator. Add `gross_outstanding_amount` field to schema if not already present, or derive from existing fields (`drawn + interest + nominal`).
- **Tests needed:** Unit tests for provision ratio with partially collateralised defaulted exposures; acceptance test confirming correct 100% vs 150% boundary at 20% provision ratio.

### P1.121 CRR Art. 121(3) unrated institution short-term 20% not applied
- **Status:** [x] **CLOSED 2026-05-03 — silently fixed (curator audit)**
- **Verification:** `INSTITUTION_SHORT_TERM_UNRATED_RW_CRR = Decimal("0.20")` declared at `data/tables/crr_risk_weights.py:151` and applied at `engine/sa/namespace.py:495-499` (`chain.when(is_institution & is_unrated & (original_mty <= 0.25)).then(pl.lit(_SA_CRR_RW["inst_unrated_st"]))`). Note: implementation gates on **original** maturity (`original_maturity_years` derived from `maturity_date - value_date`), matching Art. 121(3) "original effective maturity" wording, not "residual" as the original bullet stated. No remaining work.

### P1.122 Guarantee substitution has no B31 framework branching
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7)
- **Impact:** **Multiple incorrect B31 guarantee RWs.** `_apply_guarantee_substitution()` at `sa/calculator.py:1428-1709` has zero `is_basel_3_1` checks. Uses a single CQS table for both CRR and B31. Affected: (a) corporate CQS 3 = 100% (should be 75% under B31 per Table 6), (b) unrated institutions use CRR sovereign-derived RW (should use SCRA grades A→40%, B→75%, C→150%), (c) no short-term guarantor institution treatment under B31. P1.95 and P1.110 are symptoms of this broader issue.
- **File:Line:** `engine/sa/calculator.py:1428-1709` (`_apply_guarantee_substitution`)
- **Spec ref:** PRA PS1/26 Art. 122(2) Table 6, Art. 121 (SCRA grades), Art. 235
- **Fix:** Add `is_basel_3_1` branching in guarantee substitution. Under B31: (a) use B31 Table 6 for corporate guarantor CQS (CQS 3=75%), (b) use SCRA grades for unrated institution guarantors, (c) add short-term institution guarantor treatment. Subsumes P1.95 and P1.110.
- **Tests needed:** Acceptance tests for B31 guarantee substitution with corporate CQS 3 guarantor (75%), unrated institution guarantor (SCRA grades), short-term institution guarantor. Contrast with CRR equivalents.

### P1.123 FCCM missing exposure volatility haircut (HE) for SFT exposures
- **Status:** [ ] Not started (2026-04-10 — upgraded from P2.13 in Phase 7)
- **Impact:** **Capital understatement for SFT portfolios.** Art. 223(5) formula: `E* = max(0, E(1+HE) - CVA(1-HC-HFX))`. `collateral.py` omits the `(1+HE)` gross-up on the exposure side. HE=0 for standard lending (correct), but HE>0 for SFTs where the exposure is a debt security. Without HE, E* is understated, leading to lower RWA.
- **File:Line:** `engine/crm/collateral.py` (FCCM E* formula — missing `(1+HE)`)
- **Spec ref:** CRR Art. 223(5), PRA PS1/26 Art. 223(5)
- **Fix:** Add `exposure_haircut` (HE) parameter to the FCCM E* calculation. For SFTs, HE is the supervisory volatility haircut for the lent security (looked up from the same haircut tables as collateral haircuts). For standard lending, HE=0 (no change). Add `is_sft` Boolean field to schema or derive from exposure type.
- **Tests needed:** Unit tests for FCCM E* with HE > 0 (SFT debt security exposure); acceptance tests comparing SFT RWA with and without HE.

### P1.124 Art. 237(2) guarantee ineligibility conditions not enforced
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7)
- **Impact:** **Capital understatement.** Art. 237(2) requires that guarantees with residual maturity < 3 months or original maturity < 1 year be rejected entirely (ineligible for CRM). `guarantees.py` has no maturity eligibility check. Short-dated guarantees are incorrectly recognised, reducing capital requirements. Distinct from P1.109 (which is the maturity mismatch *adjustment* for eligible guarantees).
- **File:Line:** `engine/crm/guarantees.py` (no maturity eligibility check)
- **Spec ref:** CRR Art. 237(2)
- **Fix:** Before applying guarantee substitution, check: (a) `guarantee_residual_maturity >= 3 months`, (b) `guarantee_original_maturity >= 1 year`. Reject guarantee (treat exposure as unprotected) if either fails. Requires `guarantee_original_maturity` field.
- **Tests needed:** Unit tests for guarantee rejection at maturity boundaries (2.9m, 3m, 11m original, 12m original); acceptance tests confirming ineligible guarantees produce unprotected RW.

### P1.125 Classifier missing FSE column warning under B31
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7)
- **Impact:** **Silent A-IRB permission for FSEs.** When `cp_is_financial_sector_entity` column is absent, `classifier.py:989-994` silently defaults `_is_fse = pl.lit(False)`, letting all FSEs get A-IRB instead of the required F-IRB per Art. 147A(1)(e). The classifier already emits warnings for missing QRRE and retail pool management columns but not for FSE.
- **File:Line:** `engine/classifier.py:989-994`
- **Spec ref:** PRA PS1/26 Art. 147A(1)(e)
- **Fix:** Emit a `CalculationError(code="CLS006", severity=WARNING, category=DATA_QUALITY)` when `cp_is_financial_sector_entity` is absent under B31, analogous to existing CLS004/CLS005 warnings.
- **Tests needed:** Unit tests for CLS006 warning emission when FSE column absent under B31; no warning under CRR.

### P1.126 Classifier Art. 147A(1)(d) null revenue defaults to "not large" (A-IRB permitted)
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7)
- **Impact:** **Potential A-IRB where F-IRB required.** `classifier.py:995-997` uses `fill_null(False)` on the large corporate check (`revenue > GBP 440m`). Corporates with unknown revenue that actually exceed GBP 440m could get A-IRB instead of the required F-IRB. Should either conservatively treat null as "large" or emit a data quality warning.
- **File:Line:** `engine/classifier.py:995-997`
- **Spec ref:** PRA PS1/26 Art. 147A(1)(d)
- **Fix:** Either: (a) change `fill_null(False)` to `fill_null(True)` (conservative — treat unknown as large → F-IRB), or (b) keep `fill_null(False)` but emit a warning when `revenue` is null for B31 corporates with IRB permissions. Option (b) preferred — doesn't change default behaviour but alerts users.
- **Tests needed:** Unit tests for null revenue warning/conservative treatment under B31; no change under CRR.

### P1.127 Art. 159 Pool B composition — upstream per-exposure EL shortfall may not include AVA
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7; requires verification)
- **Impact:** **Potentially incorrect two-branch EL rule evaluation.** Aggregator `_el_summary.py:197-201` correctly implements the two-branch rule but relies on upstream `el_shortfall`/`el_excess` columns. If IRB/slotting calculators compute shortfall as `max(0, EL - provisions)` without including AVA (Art. 34/105) and other own funds reductions in Pool B, the two-branch condition may be incorrectly evaluated. Art. 159(1) defines Pool B as "expected loss amounts" which includes all own-funds-reducing items.
- **File:Line:** `engine/aggregator/_el_summary.py:197-201`, `engine/irb/calculator.py` (EL shortfall computation)
- **Spec ref:** CRR Art. 159(1), Art. 34, Art. 105
- **Fix:** Verify that upstream EL shortfall calculation includes AVA and other Art. 34/105 deductions in Pool B. If not, add an `ava_deduction` field or document as a known limitation with config input.
- **Tests needed:** Unit tests verifying Pool B includes AVA; integration test with non-zero AVA showing correct two-branch evaluation.

### P1.128 B31 SCRA short-term missing Art. 121(4) trade finance <=6m extension
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 8 cross-audit)
- **Impact:** **Capital overstatement** for unrated institution trade finance exposures with 3-6m residual maturity. The ECRA branch at `sa/calculator.py:730-739` correctly includes `is_short_term_trade_lc & residual_maturity_years <= 0.5` for the <=6m trade finance exception. The SCRA branch at `sa/calculator.py:751-754` only checks `residual_maturity_years <= 0.25` (3 months), omitting the Art. 121(4) trade goods <=6m exception that applies equally to SCRA-graded institutions.
- **File:Line:** `engine/sa/calculator.py:751-754` (SCRA short-term branch)
- **Spec ref:** PRA PS1/26 Art. 121(4)
- **Fix:** Add `| (is_short_term_trade_lc & (residual_maturity_years <= 0.5))` to the SCRA short-term condition at line 751-754, mirroring the ECRA branch logic.
- **Tests needed:** Unit tests for SCRA trade finance at 4m, 5m, 6m residual maturity (should get short-term RW); acceptance test contrasting SCRA with/without trade finance flag at 5m maturity.

### P1.129 B31 ADC pre-sold 100% concession not restricted to residential (Art. 124K(2))
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 8 cross-audit)
- **Impact:** **Capital understatement** for pre-sold commercial ADC exposures (100% vs 150%). Art. 124K(2) restricts the pre-sold 100% concession to **residential** ADC only; commercial ADC must always receive 150% regardless of pre-sold status.
- **File:Line:** `data/tables/b31_risk_weights.py:546` (`b31_adc_rw_expr()` — applies 100% for ALL `is_presold=True`)
- **Spec ref:** PRA PS1/26 Art. 124K(2)
- **Fix:** Add `& is_residential_property` (or equivalent) condition to the `is_presold=True` branch in `b31_adc_rw_expr()`. Only residential ADC with `is_presold=True` gets 100%; commercial ADC remains at 150%.
- **Tests needed:** Unit tests for residential vs commercial ADC with `is_presold=True` (residential=100%, commercial=150%); acceptance test for pre-sold commercial ADC at 150%.

### P1.130 Aggregator summaries use pre-floor RWA
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 8 cross-audit)
- **Impact:** **Reporting inconsistency — understates reported RWA when output floor is binding.** `aggregator.py:92-96` generates `summary_by_class` and `summary_by_approach` from `post_crm_detailed` BEFORE the output floor is applied at line 152. Since Polars LazyFrames are immutable, `apply_floor_with_impact()` returns a new LazyFrame that doesn't affect the pre-existing summary plans. Consumers expecting post-floor totals in summaries will see pre-floor RWA.
- **File:Line:** `engine/aggregator/aggregator.py:92-96` (summaries generated before floor), `engine/aggregator/aggregator.py:152` (floor applied after)
- **Spec ref:** PRA PS1/26 Art. 92(2A)
- **Fix:** Move summary generation (lines 92-96) to AFTER the output floor application (after line 161). Or regenerate summaries from the post-floor `combined` LazyFrame. Both approaches ensure summaries reflect the floored RWA.
- **Tests needed:** Integration test with binding output floor verifying `summary_by_class` RWA totals match post-floor `results` RWA total.

### P1.131 Pipeline bundle reconstruction drops output_floor_summary
- **Status:** [x] **CLOSED 2026-05-03 — closed-claim-invalid (curator audit)**
- **Verification:** The bullet's premise was wrong. `engine/pipeline.py:318` reads `result = replace(result, errors=all_errors)` using `dataclasses.replace` (imported at `pipeline.py:31`). `dataclasses.replace` constructs a new instance copying *every* field of `result` and overriding only the named keyword arguments. Only `errors` is overridden; all other fields — including `output_floor_summary`, `floor_impact`, `el_summary`, `summary_by_class`, `summary_by_approach`, etc. — are preserved by reference. The original "Phase 8 cross-audit" finding was filed against earlier code that may have used explicit constructor reconstruction, but the current code path does not have this bug. Closure summary captured here.
- **Original ref:** PRA PS1/26 Art. 92(2A); `engine/pipeline.py:31, 318`

### P1.132 B31 government-supported/legislative equity applies 100% instead of 250%
- **Status:** [x] **CLOSED 2026-05-03 — silently fixed (curator audit)**
- **Verification:** `data/tables/b31_equity_rw.py:44` now reads `EquityType.GOVERNMENT_SUPPORTED: Decimal("2.50"),  # Art. 133(3): 250% standard`. PDF re-extract from `docs/assets/ps126app1.pdf` (page 67-68) confirms PRA PS1/26 Art. 133(3) sets the standard equity weight at 250% with no government-supported / legislative-programme carve-out (only Art. 133(6) deduction / 1,250% / 250% threshold-rule exclusions). Module docstring (line 7) and inline comments correctly cite "Art. 133(3): 250% standard (including government-supported)". B31_SA_EQUITY_RISK_WEIGHTS dict shows all standard categories (LISTED, EXCHANGE_TRADED, GOVERNMENT_SUPPORTED, UNLISTED, OTHER) at 2.50. No remaining work. Note: skill reference table at `.claude/skills/basel31/references/sa-risk-weights.md:147` still shows "Legislative equity (govt mandate) | 100%" — flagged as docs/skill staleness, surface to docs plan via P4.32 (skill reference audit).
- **Original ref:** PRA PS1/26 Art. 133(3)/(6); `data/tables/b31_equity_rw.py:39-51`; cross-ref P4.32 (skill ref audit)
- **Fix:** Change `GOVERNMENT_SUPPORTED: Decimal("1.00")` to `Decimal("2.50")` in `B31_SA_EQUITY_RISK_WEIGHTS`. Also verify the central bank 0% (line 40) references the correct article — Art. 133(6) is not a 0% weight provision. Update docstring at line 12 ("Legislative programme equity = 100%" → removed under B31).
- **Tests needed:** Unit test confirming B31 government-supported equity gets 250%; acceptance test for B31-L equity scenario with government-supported type.

### P1.137 Equity transitional Rule 4.2/4.3 SA ladder not implemented
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Capital overstatement 2027-2029 for SA-only firms.** PRA PS1/26 Rule 4.2 phases in the 250% standard-equity weight (Art. 133(3)): 160% in 2027, 190% in 2028, 220% in 2029, 250% from 2030. Rule 4.3 phases in higher-risk 400% (Art. 133(4)/(5)): 220% 2027 / 280% 2028 / 340% 2029 / 400% 2030. Code in `data/tables/b31_equity_rw.py` and `engine/equity/calculator.py` applies the fully-phased-in weights from day one.
- **File:Line:** `data/tables/b31_equity_rw.py`, `engine/equity/calculator.py:_apply_b31_equity_weights_sa`, `engine/equity/calculator.py:_apply_transitional_floor`
- **Spec ref:** PRA PS1/26 Rule 4.2, Rule 4.3
- **Fix:** Add a `B31_SA_EQUITY_TRANSITIONAL_RW` date-keyed table (2027/2028/2029/2030+) with standard and higher-risk columns. Add `reporting_date`-gated branch to `_apply_b31_equity_weights_sa()` selecting the appropriate weight. Integrate with existing transitional-floor opt-out flag. Distinct from P2.15 which concerns floor U-TREA/S-TREA eligibility.
- **Tests needed:** Parametrised unit tests for (2027/2028/2029/2030+) × (standard/higher-risk). B31-L acceptance extended with transitional scenarios. Regression assertion that post-2030 weights remain 250%/400%.

### P1.138 Equity transitional Rule 4.6 IRB higher-of not implemented
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Silent regime change.** PRA PS1/26 Rule 4.6 says IRB firms holding Art. 155 permission on 31 Dec 2026 should take `max(legacy Art. 155 RW, Rule 4.2/4.3 transitional SA RW)` through 2029. Code transitions instantly to new Art. 133 SA treatment. Depends on P1.137 being implemented first.
- **File:Line:** `engine/equity/calculator.py`
- **Spec ref:** PRA PS1/26 Rule 4.4–4.6
- **Fix:** Introduce a `had_art_155_permission` boolean on EQUITY_EXPOSURE_SCHEMA. When true AND reporting_date in 2027-2029 AND framework is B31, compute the legacy Art. 155 RW (simple/PD-LGD/IMA) and take max against the Rule 4.2/4.3 RW. Config flag on `CalculationConfig.basel_3_1()` to indicate IRB permissions existed pre-transition.
- **Tests needed:** Unit tests for each Art. 155 sub-method × transitional year; acceptance test B31-L with legacy permission; regression test asserting non-permissioned firms unaffected.

### P1.140 ADC classification flag-only; no derivation logic
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Capital understatement for mis-tagged development exposures.** The classifier requires the caller to set `is_adc` manually. If set to False (or null), land-acquisition / development / construction exposures flow through to standard CRE or RRE corporate weights (75-100%) instead of the 150% ADC weight. There is no derivation from product-type, purpose-of-loan, or pre-sold-percentage signals.
- **File:Line:** `engine/classifier.py` (no `is_adc` derivation), `engine/sa/calculator.py` (ADC branch expects pre-tagged flag)
- **Spec ref:** PRA PS1/26 Art. 124(3), Art. 124K
- **Fix:** Add derivation logic in the classifier: `is_adc = pl.col("purpose_code").is_in(ADC_PURPOSE_CODES) | pl.col("is_land_acquisition_development_construction").fill_null(False) | ...`. Define `ADC_PURPOSE_CODES` in `data/schemas.py`. Emit a warning if `is_adc` is null AND product indicates development lending. Pair with P1.129 (residential-only 100% concession, already fixed).
- **Tests needed:** Unit tests: purpose_code routing, explicit flag overrides derivation, warning emitted on ambiguous rows. Acceptance test with mixed residential/commercial ADC under B31.

### P1.141 Art. 124(4) mixed residential/commercial RE splitting not implemented
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Mis-weighting of mixed-use exposures.** Art. 124(4) requires splitting an exposure secured by mixed residential/commercial property into RRE and CRE portions proportional to the collateral values. The current RE pipeline routes each exposure wholly to either RRE or CRE based on the dominant property flag.
- **File:Line:** `engine/sa/calculator.py` RE branches, `engine/classifier.py` property-type resolution
- **Spec ref:** PRA PS1/26 Art. 124(4)
- **Fix:** Introduce `mixed_property_residential_share` (Float64, 0-1) on CONTINGENTS_SCHEMA / LOAN_SCHEMA. Where present, split the exposure EAD and run both RRE and CRE legs, then recombine for RWA. Impact on LTV computation must use the proportional collateral value per leg.
- **Tests needed:** Unit tests: pure residential, pure commercial, 50/50 split, 30/70 split. Acceptance test with mixed-use retail branch scenario.

### P1.142 Art. 124E three-property limit not automated
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Silent mis-classification.** PRA PS1/26 Art. 124E(2) says a natural-person obligor with mortgages on 4+ income-producing residential properties must treat all such exposures as materially dependent on property cash flows (Art. 124G weights), not standard RRE. Code currently trusts the caller to set `is_income_producing_re` manually. No derivation counts obligor properties.
- **File:Line:** `engine/classifier.py`, `engine/hierarchy.py` (obligor aggregation)
- **Spec ref:** PRA PS1/26 Art. 124E(2)
- **Fix:** Add post-hierarchy aggregation: count distinct RRE exposures per natural-person obligor; where count ≥ 4, force `is_income_producing_re = True`. Requires `obligor_is_natural_person` flag on counterparties schema. Document precedence vs. caller-provided flag (derivation should only promote, not demote).
- **Tests needed:** Unit tests: 1, 3, 4, 10 properties per natural-person obligor; legal-entity obligor unaffected; caller override preserved.

### P1.143 Rule 4.11 unfunded credit protection grandfathering window not honoured
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Narrow transitional relief not available.** PRA PS1/26 Rule 4.11 relaxes eligibility conditions for unfunded credit protection entered into before 1 Jan 2027, during the window 1 Jan 2027 – 30 Jun 2028: Art. 213(1)(c)(i) and Art. 183(1A)(b) should be read with the "or change" language omitted. No code implements this. Distinct from P1.10 (the underlying Art. 213 eligibility check, also not implemented). P1.143 depends on P1.10.
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 Rule 4.11, Art. 213(1)(c)(i), Art. 183(1A)(b)
- **Fix:** After implementing P1.10, add transitional gating: if `protection_inception_date < 2027-01-01` AND `reporting_date ∈ [2027-01-01, 2028-06-30]`, apply the relaxed eligibility rule. Needs new `protection_inception_date` field on guarantees schema (already noted in P6.15).
- **Tests needed:** Parametrised date-boundary unit tests (pre/during/after window, pre/post 2027 inception).

### P1.144 EL fallback to gross EAD when `ead_final` absent
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **Inconsistent EL base.** `engine/irb/calculator.py:211-218` falls back to gross EAD when `ead_final` is missing. Downstream `_el_summary` consumer expects `ead_final`. Result: Pool A/B/C/D compositions and shortfall calcs use a different EAD basis than the RWA calc (Art. 158/159 internal inconsistency).
- **File:Line:** `engine/irb/calculator.py:211-218`
- **Spec ref:** CRR Art. 158, Art. 159
- **Fix:** Raise a `CalculationError(code="IRB006", severity=ERROR)` when `ead_final` absent rather than silently falling back. Alternatively compute `ead_final` with a documented default and emit a warning — but match the fallback in `_el_summary` so both consumers see the same value.
- **Tests needed:** Unit test: missing `ead_final` now emits IRB006; unit test: both calculator and aggregator see identical EAD base.

### P2.26 COREP Annex II sign-convention violated for (-) labelled columns
- **Status:** [ ] Not started (2026-04-18 — identified in Phase 9 audit)
- **Impact:** **PRA DPM validation will reject returns.** `reporting/corep/generator.py:3140-3214, 3385-3406` emits positive sums for columns declared negative in Annex II §1.3: 0030/0035/0050/0060/0070/0080/0090/0130/0140/0290. Any COREP submission from the generator in its current form will fail DPM sign-convention checks on ingestion.
- **File:Line:** `reporting/corep/generator.py:3140-3214` (C 07.00 / OF 07.00 column writes), `reporting/corep/generator.py:3385-3406` (C 08 column writes)
- **Spec ref:** COREP Annex II §1.3 "Sign convention for columns"
- **Fix:** Add a `NEGATIVE_COLUMNS` frozenset to `reporting/corep/templates.py` listing the (-) columns per template. In the generator column-write helper, multiply by -1 when the column is in that set. Verify against DPM XSD. Update Pillar III equivalents where applicable.
- **Tests needed:** Per-column unit tests asserting negative sign on all (-) columns. DPM-validation integration test (if DPM schema available).

---

## Priority 2 -- COREP Reporting Completeness

### P2.1 COREP template rework -- structure alignment
- **Status:** [~] Needs rework
- **Impact:** Current COREP generator (`reporting/corep/generator.py`) uses simplified column sets and one-row-per-class structure. Only C 07.00, C 08.01, C 08.02 (and their OF variants) are implemented. Full-width CRR/B31 column definitions exist in `templates.py` (lines 1-651) but generator uses backward-compatibility aliases. Specific sub-gaps:
  - C 08.01 col `0120` ("Of which: off balance sheet") still null (`generator.py:1289-1290`) — needs off-BS EAD pipeline column
  - B31 OF 08.02 missing columns `0001` and `0101-0105` (per-grade CCF breakdown) (`templates.py:646-651`)
  - B31 C 08.01 off-BS CCF sub-rows `0031-0035` always null (`generator.py:521`)
  - C 07.00 B31 CIU sub-rows `0284/0285` defined in `templates.py:348-353` but never populated by generator
  - Equity transitional rows `0371-0374` and currency mismatch row `0380` implemented (filter on `equity_transitional_approach` and `currency_mismatch_multiplier_applied` columns — null only when pipeline columns absent)
  - ~~C 07.00 memorandum rows 0290/0300/0310/0320 permanently null~~ — **FIXED** in P2.8 (2026-04-08)
  - ~~CRR supporting factor "of which" rows 0030/0035 permanently null~~ — **FIXED** in P2.8 (2026-04-08)
  - ~~CRR RWEA columns 0215-0217 permanently null due to column name mismatch~~ — **FIXED** in P2.8 (2026-04-08)
  - B31 slotting FCCM cols `0101-0104` in C 08.01 still null (`generator.py:1281-1283`) — pipeline FCCM for slotting not yet wired
  **Additional from PDF comparison:** OF 07.00 has 22 columns in spec vs ~29 actual (missing cols 0230/0235/0240 ECAI breakdown, col 0235 "ECAI not available" new in B31). OF 09.02 has 15 cols in spec vs 13 actual (missing col 0107 defaulted EV; remove SF cols). OF 08.01 missing cols 0254 (unrecognised exposure adjustments, NOT PD floors), 0265, 0282 (total post-adjustment EL, NOT PD/LGD floors); col 0280 renamed. OF 02.00 needs rows 0034 (Yes/No indicator), 0035 (multiplier %), 0036 (monetary OF-ADJ). OF 08.06 CRR risk weight column 0070 removed in B3.1; col 0031 FCCM is a deduction column. OF 08.07 cols 0160-0180 require consolidated-basis-only reporting. OF 09.01 missing col 0061 (additional value adjustments).
- **File:Line:** `reporting/corep/generator.py`, `reporting/corep/templates.py`
- **Fix:** Migrate generator to use full template definitions. Rework row/column logic. Add missing pipeline columns for equity transitional and currency mismatch reporting. Remove dead alias objects. Correct column counts per PDF comparison.
- **Tests needed:** Rewrite COREP tests (~250 tests in `tests/unit/test_corep.py`).

### P2.2 COREP templates C 02.00, C 08.03-08.07, OF 02.01
- **Status:** [~] Partial (OF 02.01, C 08.03, C 08.04, C 08.05, C 08.06, and C 08.07 complete; only C 08.04 RWEA flow drivers require prior-period data)
- **Templates:**
  - C 02.00 / OF 02.00 -- Own Funds Requirements (OF 02.00 adds rows 0034-0036 for floor indicator/multiplier/OF-ADJ)
  - OF 02.01 -- Output Floor: 4 columns (modelled RWA, SA RWA, U-TREA, S-TREA) x 8 risk-type rows
  - C 08.03 / OF 08.03 -- CR IRB PD ranges
  - C 08.04 / OF 08.04 -- CR IRB RWEA flow statements
  - **C 08.05 / OF 08.05** -- CR IRB PD backtesting. 5 columns: col 0010 arithmetic avg PD (OF: post-input floor), col 0020 obligors at end of previous year, col 0030 of which defaulted, col 0040 observed avg default rate, col 0050 avg historical annual default rate. CRR equivalent C 08.05 exists (not "no CRR equivalent"). **Now documented in spec.**
  - **OF 08.05.1** -- PD backtesting for ECAI-based estimates (Art. 180(1)(f)). Col 0005 = firm-defined PD ranges (variable-width), col 0006 = one column per ECAI. **Now documented in spec.**
  - C 08.06 / OF 08.06 -- CR IRB specialised lending slotting
  - C 08.07 / OF 08.07 -- CR IRB scope of use (cols 0160-0180 consolidated-basis only)
  - **OF 34.07** -- IRB CCR exposures by exposure class and PD scale. 7 columns: exposure value, EWA PD (post-floor), obligors, EWA LGD, EWA maturity (years), RWEA, density (RWEA/EV). Applies to F-IRB/A-IRB CCR regardless of valuation method; excludes CCP-cleared. **Now documented in spec.**
- **OF 02.01 — COMPLETE (2026-04-08):** Output floor comparison template implemented. 4 columns (modelled RWA, SA RWA, U-TREA, S-TREA) × 8 risk-type rows. Credit risk row (0010) and Total row (0080) populated from pipeline `rwa_pre_floor` and `sa_rwa` columns. CCR/CVA/securitisation/market/op risk/other rows are null (out of scope). Basel 3.1 only (returns None under CRR). Template definitions in `templates.py` (`OF_02_01_COLUMNS`, `OF_02_01_ROW_SECTIONS`, `OF_02_01_COLUMN_REFS`). Generator method `_generate_of_02_01()` in `generator.py`. `COREPTemplateBundle.of_02_01` field (single DataFrame, not per-class). Excel export via `_write_single_template_sheet()`. 42 new tests across 5 test classes. All 4,306 tests pass (was 4,264). COREP tests: 319 (was 277).
- **C 08.03 / OF 08.03 — COMPLETE (2026-04-08):** IRB PD range distribution template implemented. 17 fixed regulatory PD range buckets (0.00-0.03% through 100% Default) × 11 columns (on/off-BS exposure, avg CCF, EAD, avg PD, obligors, avg LGD, avg maturity, RWEA, EL, provisions). One DataFrame per IRB exposure class. Slotting exposures excluded. Basel 3.1 key distinction: row allocation uses pre-input-floor PD (`irb_pd_original`) while col 0050 reports post-input-floor PD (`irb_pd_floored`); CRR uses floored PD for both. Template definitions: `C08_03_PD_RANGES` (17 buckets with row refs 0010-0170), `CRR_C08_03_COLUMNS` / `B31_C08_03_COLUMNS` (11 columns), `C08_03_COLUMN_REFS`, `get_c08_03_columns()`. Generator methods: `_generate_all_c08_03()` and `_generate_c08_03_for_class()` with `_compute_c08_03_values()` helper. `COREPTemplateBundle.c08_03` field (dict[str, pl.DataFrame]). Excel export via `_write_template_sheets()`. 43 new tests across 6 test classes (TestC0803TemplateDefinitions: 9, TestC0803Generation: 5, TestC0803PDRangeAssignment: 6, TestC0803ColumnValues: 12, TestC0803B31Features: 4, TestC0803EdgeCases: 7). All 4,417 tests pass (was 4,374). COREP tests: 362 (was 319).
- **C 08.04 / OF 08.04 — COMPLETE (2026-04-08):** IRB RWEA flow statements implemented. 1 column (RWEA) × 9 rows (opening, 7 movement drivers, closing) per IRB exposure class. Closing RWEA (row 0090) populated from `rwa_final` sum per class. Opening (row 0010) and movement driver rows (0020-0080) are null — they require prior-period comparison data that a single pipeline run cannot produce. Slotting exposures excluded (C 08.06 covers SL separately). CRR column name includes "after supporting factors"; B31 removes that qualifier. Template definitions: `CRR_C08_04_COLUMNS` / `B31_C08_04_COLUMNS` (1 column each), `C08_04_ROWS` (9 rows), `C08_04_COLUMN_REFS`, `get_c08_04_columns()`. Generator methods: `_generate_all_c08_04()` and `_generate_c08_04_for_class()`. `COREPTemplateBundle.c08_04` field (dict[str, pl.DataFrame]). Excel export via `_write_template_sheets()` with framework-aware prefix (C 08.04 for CRR, OF 08.04 for B31). 41 new tests across 6 test classes (TestC0804TemplateDefinitions: 13, TestC0804Generation: 5, TestC0804ClosingRWEA: 4, TestC0804NullDriverRows: 9, TestC0804B31Features: 3, TestC0804EdgeCases: 7). COREP tests: 555 (was 514).
- **C 08.05 / OF 08.05 — COMPLETE (2026-04-08):** IRB PD backtesting template implemented. 17 fixed regulatory PD range buckets (reuses `C08_03_PD_RANGES`) × 5 columns (arithmetic avg PD, obligors at end of previous year, of which defaulted, observed default rate, historical annual default rate). One DataFrame per IRB exposure class. Slotting exposures excluded. Basel 3.1 key distinction: row allocation uses pre-input-floor PD (`irb_pd_original`), col 0010 reports arithmetic average of post-input-floor PD (`irb_pd_floored`); CRR uses floored PD for both. Default detection uses `is_defaulted` column with fallback to `PD >= 1.0`. Obligor counting uses `counterparty_reference.n_unique()`. Historical data columns (`prior_year_obligor_count`, `historical_annual_default_rate`) supported when available; falls back to current-period data. Template definitions: `CRR_C08_05_COLUMNS` / `B31_C08_05_COLUMNS` (5 columns), `C08_05_COLUMN_REFS`, `get_c08_05_columns()`. Generator methods: `_generate_all_c08_05()` and `_generate_c08_05_for_class()` with `_compute_c08_05_values()` helper. `COREPTemplateBundle.c08_05` field (dict[str, pl.DataFrame]). Excel export via `_write_template_sheets()` with framework-aware prefix (C 08.05 for CRR, OF 08.05 for B31). 42 new tests across 6 test classes (TestC0805TemplateDefinitions: 9, TestC0805Generation: 5, TestC0805PDRangeAssignment: 6, TestC0805ColumnValues: 11, TestC0805B31Features: 4, TestC0805EdgeCases: 7). All 4,788 tests pass (was 4,746). COREP tests: 514 (was 472).
  - **C 08.06 / OF 08.06 — COMPLETE (2026-04-08):** IRB specialised lending slotting template implemented. One DataFrame per SL type. CRR: 4 SL types (PF, IPRE+HVCRE combined, OF, CF), 12 rows (5 categories × 2 maturity bands + 2 totals), 10 columns. Basel 3.1: 5 SL types (HVCRE separated from IPRE), 14 rows (adds "substantially stronger" sub-rows 0015/0025), 11 columns (adds col 0031 FCCM deduction; supporting factors removed from RWEA label). Template definitions: `CRR_C08_06_COLUMNS` / `B31_C08_06_COLUMNS`, `CRR_C08_06_ROWS` / `B31_C08_06_ROWS`, `CRR_SL_TYPES` / `B31_SL_TYPES`, `C08_06_CATEGORY_MAP`, `C08_06_COLUMN_REFS`, `get_c08_06_columns()`, `get_c08_06_rows()`, `get_c08_06_sl_types()`. Generator methods: `_generate_all_c08_06()` and `_generate_c08_06_for_type()` with `_compute_c08_06_values()` helper. `COREPTemplateBundle.c08_06` field (dict[str, pl.DataFrame]). Excel export via `_write_template_sheets()` with SL type display names. Known gaps: col 0031 FCCM is null (pipeline FCCM for slotting not yet wired); "substantially stronger" sub-rows (0015/0025) are zero (pipeline has no `is_substantially_stronger` flag). 65 new tests across 7 test classes (TestC0806TemplateDefinitions: 19, TestC0806Generation: 8, TestC0806RowAssignment: 8, TestC0806ColumnValues: 12, TestC0806B31Features: 9, TestC0806SupportingFactors: 2, TestC0806EdgeCases: 7). All 4,482 tests pass (was 4,417). COREP tests: 427 (was 362).
- **C 08.07 / OF 08.07 — COMPLETE (2026-04-08):** IRB scope of use template implemented. Shows per-class split between SA and IRB approaches with coverage percentages. CRR: 5 columns (exposure values + coverage %) × 17 rows (Art. 147(2) exposure classes). Basel 3.1: 18 columns (adds RWEA decomposition cols 0060-0150 by SA-use reason, materiality cols 0160-0180) × 11 rows (Art. 147B roll-out classes + materiality). Template definitions: `CRR_C08_07_COLUMNS` / `B31_C08_07_COLUMNS`, `CRR_C08_07_ROWS` / `B31_C08_07_ROWS`, `C08_07_COLUMN_REFS` / `B31_C08_07_COLUMN_REFS`, `C08_07_IRB_APPROACHES`, `C08_07_CRR_RETAIL_CLASSES`, `get_c08_07_columns()`, `get_c08_07_rows()`. Generator method: `_generate_c08_07()` with `_compute_c08_07_values()` helper. `COREPTemplateBundle.c08_07` field (single DataFrame, not per-class). Excel export via `_write_single_template_sheet()` with framework-aware sheet name (C 08.07 for CRR, OF 08.07 for B31). Known gaps: SA RWEA breakdown (cols 0070-0130) reports all SA RWEA in "other" (col 0140) — requires `sa_use_reason` pipeline column for per-reason split. Materiality columns (0160-0180) null — requires institutional-level configuration. CRR sub-rows without direct exposure class mapping (0060 SL excl. slotting, 0100/0130 SME retail) report null. 51 new tests across 5 test classes (TestC0807TemplateDefinitions: 17, TestC0807Generation: 8, TestC0807ColumnValues: 12, TestC0807B31Features: 8, TestC0807EdgeCases: 6). All 4,533 tests pass (was 4,482). COREP tests: 478 (was 427).
- **C 02.00 / OF 02.00 — COMPLETE (2026-04-08):** Own Funds Requirements (CA2) master capital template implemented. Aggregates RWEA by approach (SA, F-IRB, A-IRB, slotting, equity) with per-class breakdown rows. CRR: 1 column (col 0010 — all approaches). Basel 3.1: 3 columns (col 0010 all approaches / U-TREA, col 0020 SA-equivalent / S-TREA, col 0030 output floor). CRR row structure: 3 sections (Total+Credit Risk with 20 SA class rows, IRB with 14 approach rows, Other Risk Types with 6 null rows). Basel 3.1 row structure: 6 sections (Total+Output Floor with indicator rows 0034/0035/0036, SA with 19 class rows + specialised lending 0131, F-IRB with 9 breakdown rows 0271/0290/0295-0297, A-IRB with 16 breakdown rows incl. retail RE 0382-0385/QRRE 0390/other SME 0400/non-SME 0410, Slotting with 7 per-type rows 0411-0416, Other Risk Types with 6 null rows). Template definitions: `CRR_C02_00_COLUMNS`/`B31_C02_00_COLUMNS`, `CRR_C02_00_ROW_SECTIONS`/`B31_C02_00_ROW_SECTIONS`, `C02_00_SA_CLASS_MAP`, `C02_00_CREDIT_RISK_ROWS`, `get_c02_00_columns()`, `get_c02_00_row_sections()`. Generator: `_generate_c_02_00()` aggregates from pipeline `rwa_final`, `approach_applied`, `exposure_class` (mandatory) and `sa_rwa`/`rwa_pre_floor`/`sl_type` (optional B31). `COREPTemplateBundle.c_02_00` field (single DataFrame, not per-class). Excel export: `_write_single_template_sheet()` with "C 02.00" (CRR) or "OF 02.00" (B31) prefix. Known gaps: F-IRB/A-IRB sub-class breakdown rows (0295-0297 financial/large/SME, 0355-0356 corp SME/non-SME, 0382-0385 retail RE SME/non-SME) report fallback values (all to "other" rows) — needs `cp_is_fse` and `is_sme` pipeline columns for per-sub-class split. Indicator rows 0035 (floor multiplier) and 0036 (OF-ADJ) are placeholder zero — needs `OutputFloorConfig` propagation to generator. 59 new tests across 8 test classes (TestC0200TemplateDefinitions: 16, TestC0200Generation: 8, TestC0200TotalRow: 5, TestC0200SABreakdown: 6, TestC0200IRBBreakdown: 8, TestC0200B31Features: 5, TestC0200NullRows: 6, TestC0200EdgeCases: 5). All 4,746 tests pass (was 4,687). COREP tests: 472 (was 413).
- **Fix remaining:** Add OF 08.05.1/OF 34.07 to `docs/features/corep-reporting.md`. C 08.04 flow drivers (rows 0020-0080) require prior-period data for multi-period comparison.

### P2.5 COREP missing row structure across multiple templates
- **Status:** [~] Partial (template definitions exist; generator population improved)
- **Impact:** Template row definitions for all missing rows already existed in `templates.py`. The real gaps were in the generator's population logic:
  **Fixed in 0.1.173:**
  - **OF 02.00 IRB sub-rows (8 rows):** Rows 0295-0297 (F-IRB corporate: FSE/large, SME, non-SME), 0355-0356 (A-IRB corporate: SME, non-SME), 0382-0385 (A-IRB retail RE: resi SME/non-SME, comm SME/non-SME), 0400/0410 (retail other SME/non-SME) — now populated using `is_sme` and `apply_fi_scalar` pipeline columns via finer-grained IRB aggregation in `_generate_c_02_00()`.
  - **OF 02.00 floor indicator rows:** Row 0035 (floor multiplier %) and 0036 (OF-ADJ monetary value) now populated from `OutputFloorSummary` when provided via new `output_floor_summary` parameter on `generate_from_lazyframe()`.
  - **OF 07.00 RE sub-rows (10 rows):** `_filter_re()` now falls back to `has_income_cover` (SA calculator proxy) or `is_income_producing` (raw input) when `materially_dependent_on_property` column is absent. Rows 0331/0332, 0341-0344, 0351-0354 now populate from existing pipeline data.
  - **OF 07.00 equity transitional rows (4 rows):** Equity calculator `_apply_transitional_floor()` now writes `equity_transitional_approach` ("sa_transitional"/"irb_transitional") and `equity_higher_risk` (Boolean) annotation columns. Rows 0371-0374 can now populate.
  **Remaining gaps (require new pipeline columns or data):**
  - OF 02.00 rows 0295/0296 (F-IRB FSE/SME) still show 0.0 when `apply_fi_scalar`/`is_sme` absent from pipeline output
  - OF 08.01 rows 0017 (revolving), 0031-0035 (off-BS CCF sub-rows), 0175 (purchased receivables), 0180 (dilution risk) — need pipeline columns
  - OF 08.01 col 0120 ("Of which: off balance sheet") — need off-BS EAD
  - OF 08.07 rows 0180-0250 (roll-out classes), 0260 (total), 0270 (immateriality %)
- **File:Line:** `reporting/corep/generator.py` (_generate_c_02_00, _filter_re, _irb_sub_split, _irb_re_sub_split, _irb_other_sme_split), `engine/equity/calculator.py` (_apply_transitional_floor)
- **Spec ref:** PRA PS1/26 Art. 92 para 2A (OF 02.00), CRR Art. 124-126 (OF 07.00 RE), PRA Rules 4.1-4.10 (equity transitional)
- **Tests:** 24 new tests in `tests/unit/test_corep.py`: TestOF0200IRBSubRowSplits (15), TestOF0200FloorIndicatorRows (4), TestOF0700RESubRowFallback (4), TestEquityTransitionalColumns (1). All tests pass.

### P2.6 COREP CCR rows (0090-0130 in C 07.00, CCR section in C 08.01)
- **Status:** [ ] Not implemented (CCR engine out of scope)
- **Decision needed:** Accept null CCR rows as out-of-scope, or add placeholder documentation.

### P2.7 COREP pre-credit-derivative RWEA approximation (row 0310)
- **Status:** [~] Lower-bound approximation
- **Impact:** `generator.py:1460-1472` approximates pre-CD RWEA as total RWEA. Without per-exposure pre/post tracking for credit-derivative substitution benefit, the regulatory split cannot be accurately reported.
- **File:Line:** `reporting/corep/generator.py:1460-1472`
- **Fix:** Track pre-CD and post-CD RWEA in the CRM/IRB pipeline.

### P2.9 COREP OF 34.07 missing (IRB CCR exposures by exposure class and PD scale)
- **Status:** [ ] Not started
- **Impact:** OF 34.07 is a Basel 3.1 COREP template for IRB CCR. 7 columns: col 0010 exposure value, col 0020 EWA PD (post-floor), col 0030 number of obligors, col 0040 EWA LGD, col 0050 EWA maturity (years), col 0060 RWEA, col 0070 density of RWEA (col 0060/col 0010). Scope: any firm using F-IRB or A-IRB for CCR regardless of CCR valuation method (SA-CCR, IMM, etc.). Excludes CCP-cleared exposures. While CCR is generally out of scope (noted in P2.6), this template should at minimum be documented as a known gap. **Now documented in spec.**
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 COREP reporting framework
- **Fix:** Add OF 34.07 to COREP template inventory in `docs/features/corep-reporting.md`. Document as out-of-scope (CCR dependency) or add placeholder template definition.
- **Tests needed:** None until CCR is implemented.

### P2.12 C 07.00 / OF 07.00 missing col 0020 "Exposures deducted from own funds"
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** Standard EBA/PRA column between 0010 (Original exposure) and 0030 (Value adjustments) is absent from both CRR C 07.00 and B31 OF 07.00 template definitions. Template submission validation tools will flag the missing column.
- **File:Line:** `reporting/corep/templates.py` (C07 column definitions)
- **Spec ref:** PRA COREP reporting framework C 07.00 / OF 07.00
- **Fix:** Add column 0020 to CRR_C07_COLUMNS and B31_C07_COLUMNS. The value is the amount of exposures deducted from own funds per Art. 36/48/49 — may be zero for most rows or require config input.
- **Tests needed:** Template definition tests for column count and ordering.

---

## Priority 3 -- Pillar III Disclosures

### P3.3 Pillar III spec gaps -- qualitative tables and detailed field rules
- **Status:** [~] Spec is accurate but incomplete for some details
- **Impact:** Comparison against PRA disclosure PDFs found:
  - **UKB CRD** (SA qualitative, Art. 444(a-d)) — 4 rows: (a) ECAI/ECA names, (b) exposure classes for ECAI use, (c) issuer/issue assessment process, (d) ECAI-to-CQS mapping. Entirely absent from spec.
  - **UKB CRE** (IRB qualitative, Art. 452(a-f)) — 6 rows: (a) scope of PRA permission, (b) control mechanisms, (c) model development roles, (d) management reporting, (e) internal rating system description (PD/LGD/CCF methodology), (f) equity approach assignment. Entirely absent from spec.
  - CR6 AIRB purchased receivables sub-row (under corporates) missing from spec's CR6 row table
  - CR5 rows 18-33 not detailed in spec (additional risk weight allocation breakdowns)
  - CR5 col (ae) "unrated" definition imprecise — should specify "without ECAI credit assessment" not "with substituted risk weights"
  - CR7-A off-BS CRM scaling rule (CCF x CRM, EAD/nominal cap) not documented
  - CR6 col h (LGD) exposure-level RW floor cross-references (Art. 160(4)/163(4)) missing
  - CR6 col g obligor counting edge cases (facility-level default, split rating) not documented
  - CR7 row granularity understated -- SME/non-SME sub-rows within each approach block
  - CR10 CRR col (b) Art. 166(8)-(10) CCF sub-rules not documented
  - KM1, INS1, INS2, OVC templates from CRR not in spec (out of credit risk scope)
  - `crr-pillar3-irb-credit-risk-instructions.pdf` referenced in spec as source but does not exist in `docs/assets/`
  - CR7-A PDF typo: column "n" duplicated (should be "o" and "p") -- spec already resolves correctly
- **Fix:** Update `docs/features/pillar3-disclosures.md` with missing qualitative tables (CRD, CRE), purchased receivables sub-row, CR5 rows 18-33, and field-level precision fixes.

### P3.5 CR9.1 (ECAI-based PD backtesting) — template only, no generator
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** `CR9_1_COLUMNS` and `CR9_1_COLUMN_REFS` exist in `reporting/pillar3/templates.py` (lines 562-574) but the generator has no `_generate_cr9_1()` method and `Pillar3TemplateBundle` has no `cr9_1` field. P3.2 is marked [x] Complete but CR9.1 is not callable. Only needed for firms using Art. 180(1)(f) ECAI-based PD estimation.
- **File:Line:** `reporting/pillar3/templates.py:562-574` (template defs), `reporting/pillar3/generator.py` (no generate method)
- **Spec ref:** PRA PS1/26 Art. 180(1)(f), Annex XXII
- **Fix:** Add `cr9_1: dict[str, pl.DataFrame] | None` field to bundle. Add `_generate_cr9_1()` stub that returns empty dict (data depends on ECAI mapping not yet in pipeline). Document as known gap.
- **Tests needed:** Bundle field exists, generator returns empty, Excel export handles None.

---

## Priority 4 -- Documentation & Consistency Fixes

### P4.2 Stale version numbers across docs
- **Status:** [~] Multiple files outdated
- **Impact:** `docs/specifications/overview.md` says 0.1.37, `docs/plans/prd.md` says 0.1.28, `milestones.md` says 0.1.28. Actual is 0.1.64.
- **Fix:** Update version references or remove hardcoded versions.

### P4.3 Stale implementation plan (`docs/plans/implementation-plan.md`)
- **Status:** [~] Shows items as incomplete that are Done
- **Fix:** Update or deprecate in favour of this file.

### P4.4 Stale PRD (`docs/plans/prd.md`)
- **Status:** [~] Many FR statuses outdated
- **Fix:** Update FR status values.

### P4.8 COREP template spec
- **Status:** [~] Thin in output-reporting.md -- detailed in corep-reporting.md feature doc
- **Fix:** Expand or cross-reference.

### P4.9 Type checker inconsistency in docs
- **Status:** [~] Docs disagree with CLAUDE.md
- **Fix:** Reconcile tool references.

### P4.10 model_permissions not documented in architecture spec
- **Status:** [~] Missing from data model
- **Fix:** Add to architecture spec and configuration spec.

### P4.11 SA risk weight spec missing ECA Art. 137 section
- **Status:** [~] Mostly complete (2026-04-08 — stale claims corrected)
- **Impact:** Previous description claimed RGLA/PSE/MDB/IntOrg/Art.134 had no code implementation. **Investigation (2026-04-08) proved all are fully implemented:**
  - Art. 115 RGLA: `crr_risk_weights.py:164-222` — Tables 1A/1B, UK devolved 0%, domestic currency 20%, unrated fallback. Calculator `sa/calculator.py:676-696` (CRR) and `976-1020` (B31).
  - Art. 116 PSE: `crr_risk_weights.py:108-160` — Tables 2/2A, short-term 20%, unrated sovereign-derived. Calculator `659-675`.
  - Art. 117 MDB: `crr_risk_weights.py:225-267` — Table 2B (CQS 2=30%), 16 named MDBs 0%, unrated 50%. Calculator `697-711`.
  - Art. 118 IntOrg: `crr_risk_weights.py:270-277` — EU/IMF/BIS/EFSF/ESM all 0%. Calculator `701-707`.
  - Art. 134 Other Items: `crr_risk_weights.py:326-333` — cash/gold 0%, collection 20%, tangible 100%, leased residual 1/t×100%. Calculator `860-888` (B31) and `1036-1064` (CRR).
  - Art. 120 Tables 4/4A, Art. 128 High-risk 150%, Art. 129 Covered bonds: all in spec and code.
  **Only genuinely missing:** Art. 137 ECA Table 9 (MEIP score to CQS mapping). Calculator requires ECAI CQS directly; ECA-to-CQS derivation for unrated sovereigns is a future enhancement.
- **Fix remaining:** Add Art. 137 ECA Table 9 section to SA risk weight spec. Implement ECA score lookup (low priority — niche feature for unrated sovereigns).

### P4.12 Equity spec misattributes BCBS CRE60 concepts to PRA Art. 133
- **Status:** [~] Partially fixed
- **Impact:** SA risk weight spec includes "100% legislative equity (Art. 133(6))" and "CQS 1-2/3-6 speculative equity" tiers. Neither exists in PRA PS1/26 Art. 133 -- these are BCBS CRE60 categories. Art. 133(6) is actually a carve-out for government-mandated holdings, not a 100% weight.
  **Spec fixes (2026-04-06):**
  - Higher-risk equity definition corrected from "held <5yr" to "undertaking's business age <5yr" (the 5yr threshold is about the issuing company's age, not the investor's holding period)
  - Equity transitional scope corrected from vintage-based ("held as at 31 Dec 2026") to time-period-based (PRA Rules 4.1-4.3 apply to all equity in the reporting period)
  - Classification decision tree updated with corrected definitions
  **Remaining:** CQS speculative tiers still referenced in equity-approach.md (minor); legislative equity description still slightly imprecise
- **Fix:** Remove remaining BCBS-only CQS speculative concepts from PRA spec. Also: no dedicated equity spec file — equity content is spread across slotting and framework-differences. Consolidate when EQ-P1-01 / EQ-P2-02 land.

### P4.14 Stale key-differences.md implementation status claims
- **Status:** [~] Reopened (2026-04-18 — Phase 2a docs audit)
- **Impact:** `key-differences.md` claims "Not Yet Implemented" for:
  - (a) Currency mismatch 1.5x multiplier -- implemented at `engine/sa/calculator.py:900-966`
  - (b) SA Specialised Lending Art. 122A-122B -- implemented at `engine/sa/calculator.py:528-533`
  - (c) Provision-coverage-based defaulted treatment CRE20.87-90 -- implemented at `engine/sa/calculator.py:451-461`
- **Fix (partial, 2026-04-07):** `key-differences.md` was updated previously, but `docs/specifications/basel31/key-differences.md` still lists currency-mismatch, SA SL, and provision-based defaulted as "Not Yet Implemented" — these are implemented. Reopened after Phase 2a docs audit.
- **Fix remaining:** Remove "Not Yet Implemented" markers from `docs/specifications/basel31/key-differences.md` for the three features.

### P4.20 COREP C 08.02 PD bands use fixed buckets instead of firm-specific rating grades
- **Status:** [ ] Not started
- **Impact:** COREP reporting agent notes C 08.02 implementation uses 8 fixed PD buckets instead of firm-specific internal rating grades. The regulatory requirement is to report by the firm's own internal rating scale. Fixed buckets may not align with a firm's actual rating grade structure.
- **File:Line:** `reporting/corep/generator.py` (C 08.02 generation)
- **Spec ref:** PRA COREP reporting requirements
- **Fix:** Make PD band definitions configurable based on firm's internal rating grade structure. Add rating grade configuration to CalculationConfig or as a separate reporting config.
- **Tests needed:** Unit tests with custom PD band definitions.

### P4.26 Stale PD floor values in irb/formulas.py docstring
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** `_pd_floor_expression()` docstring says "Retail mortgage: 0.05%" and "QRRE transactors: 0.03%". Runtime config values are correct (0.10% and 0.05% per Art. 163(1)(b)/(c)), but the docstring is misleading.
- **File:Line:** `engine/irb/formulas.py:62-63`
- **Fix:** Update docstring to show correct PD floor values.

### P4.27 Stale PD floor values in skill reference file
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `.claude/skills/basel31/references/irb-changes.md` shows wrong PD floors (mortgage 0.05% → should be 0.10%, QRRE transactor 0.03% → should be 0.05%). Same P4.5 error not fixed in skill file.
- **Fix:** Update skill reference file with correct values.

### P4.28 Stale column count in COREP templates.py docstring
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `reporting/corep/templates.py` line 5 says "C 07.00 / OF 07.00: SA credit risk -- 24/22 columns" but actual counts are 27/27. Not updated after successive implementation rounds.
- **File:Line:** `reporting/corep/templates.py:5`
- **Fix:** Update docstring column counts to match actual template definitions.

### P4.29 Stale "Not Yet Implemented" warnings in user-guide/regulatory/basel31.md
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** Lines 186-187 say "The currency mismatch risk weight multiplier is not yet implemented" — it IS implemented in `sa/calculator.py:1703-1769`. Line 196 says "Provision-coverage-based differentiation is not currently implemented in the SA calculator" — it IS implemented.
- **File:Line:** `docs/user-guide/regulatory/basel31.md:186-197`
- **Fix:** Remove stale "Not Yet Implemented" warnings.

### P4.31 Skill reference `slotting-changes.md` has wrong B31 pre-op weights
- **Status:** [ ] Not started (2026-04-08 — identified in phase 3 PRA PDF cross-check)
- **Impact:** `.claude/skills/basel31/references/slotting-changes.md` lines 29-35 show PF pre-operational weights as 80%/100%/120%/350% (BCBS CRE33.7 values). PRA PS1/26 Art. 153(5) Table A was verified from the PDF — it has NO separate pre-operational PF table. All SL types (PF/OF/CF/IPRE) use the same Table A weights (Strong=70%, Good=90%, Satisfactory=115%, Weak=250%). The skill reference conflates BCBS with PRA. The code's `b31_slotting.py` is correct.
- **File:Line:** `.claude/skills/basel31/references/slotting-changes.md:29-35`
- **Fix:** Remove "Project Finance Pre-Operational" as a separate table. Document that PRA did not adopt BCBS pre-op distinction. The subgrade maturity differentiation (columns A-D) is the correct PRA mechanism.

### P4.32 Skill reference `references/` files may have stale BCBS-derived values
- **Status:** [ ] Not started (2026-04-08 — identified in phase 3 audit)
- **Impact:** The P4.27 fix for PD floor values in `irb-changes.md` is still outstanding. Other skill reference files (`output-floor.md`, `crm-changes.md`) may also have BCBS values where PRA-specific values should be used. Needs systematic audit of all `.claude/skills/basel31/references/*.md` files against PRA PS1/26.
- **File:Line:** `.claude/skills/basel31/references/` (all files)
- **Fix:** Audit and correct all skill reference files to use PRA PS1/26 values, not BCBS.

### P4.33 Stale BCBS output floor references in source code docstrings
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5)
- **Impact:** Three source code files have stale BCBS 6-year output floor schedule in docstrings/comments. Runtime code correctly uses PRA 4-year schedule.
  - `engine/comparison.py:18` — "phases in from 50% (2027) to 72.5% (2032+)"
  - `contracts/bundles.py:489` — "PRA PS1/26 phases in the output floor from 50% (2027) to 72.5% (2032+)"
  - `ui/marimo/comparison_app.py:14-15` — "from 50% (2027) to 72.5% (2032+)"
  All should say "60% (2027) to 72.5% (2030+)" per PRA schedule.
- **File:Line:** `engine/comparison.py:18`, `contracts/bundles.py:489`, `ui/marimo/comparison_app.py:14-15`
- **Fix:** Update all three docstrings to PRA 4-year schedule: 60% (2027) to 72.5% (2030+).

### P4.34 SCRA Grade A Enhanced article reference wrong in B31 spec
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** `docs/specifications/crr/sa-risk-weights.md` references Art. 120(2A) for the SCRA Grade A Enhanced rate but the correct article is Art. 121(5). Art. 120 covers ECRA (rated institutions), Art. 121 covers SCRA (unrated institutions). Misleading regulatory reference.
- **Fix:** Update article reference from Art. 120(2A) to Art. 121(5) in the SA risk weights spec.

### P4.35 Currency mismatch article reference wrong in both specs
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** Multiple locations in spec files reference Art. 123A for currency mismatch but the correct article is Art. 123B. Art. 123A is "Regulatory Retail Exposures" (retail qualifying criteria). Art. 123B is "Currency mismatch". Incorrect cross-references.
- **Fix:** Find and replace all currency mismatch references from Art. 123A to Art. 123B in spec files.

### P4.36 B31 slotting spec says "flat weights regardless of maturity" but PRA preserves maturity differentiation
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** The B31 slotting specification claims flat risk weights regardless of maturity, but PRA PS1/26 Art. 153(5)(c)-(d) preserves maturity differentiation via Table A columns A-D. The "flat" behaviour is BCBS CRE33 only, not PRA. Internal contradiction in the spec that has led to P1.97/P1.117 code issues.
- **Fix:** Correct the spec to document PRA maturity differentiation (Table A columns A/B for Strong, C/D for Good) and remove "flat regardless of maturity" language.

### P4.37 CRR PD floor article reference wrong for retail
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** `docs/specifications/crr/firb-calculation.md` cites Art. 160(1) for all PD floors including retail. The retail PD floor is Art. 163(1), not Art. 160(1). Art. 160 covers corporate/institution/sovereign PD estimation; Art. 163 covers retail PD estimation.
- **Fix:** Add Art. 163(1) reference for retail PD floor alongside the existing Art. 160(1) reference for non-retail.

### P4.38 B31 provisions spec Pool A/B labelling inverted
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** `docs/specifications/crr/provisions.md` labels Pool A as non-defaulted EL and Pool B as defaulted provisions. The regulation is the opposite: Pool A = provisions for defaulted exposures (Art. 159(1)), Pool B = EL for non-defaulted exposures (Art. 158). Inverted labelling creates confusion for readers cross-referencing with regulatory text.
- **Fix:** Swap Pool A/B labels to match regulation: Pool A = defaulted provisions, Pool B = non-defaulted EL.

### P4.39 B31 slotting spec EL rate table incomplete
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** The slotting EL rate table in the spec shows only >=2.5yr EL values (Strong=0.4%, Good=0.8%, Satisfactory=2.8%, Weak=8.0%) but omits short-maturity values (Strong=0%, Good=0.4%, Satisfactory=2.8%, Weak=8.0%). The short-maturity EL rates differ for Strong and Good categories.
- **Fix:** Add short-maturity (<2.5yr) column to the EL rate table in the slotting spec.

---

## Priority 5 -- Test Coverage Gaps

### P5.14 No integration/acceptance tests for COREP or Pillar III generators
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** All 663+ COREP tests and 197+ Pillar III tests are unit tests with synthetic LazyFrames. No test validates the full pipeline path: loader → classifier → CRM → calculator → aggregator → COREP/Pillar III generator. This means a regression in any pipeline stage that changes column names, exposure class values, or approach labels could silently break reporting output without any test failure.
- **Fix:** Add 2-3 integration tests per generator that run the full pipeline with fixture data and verify the COREP/Pillar III output has expected row counts, non-null key columns, and correct aggregation.
- **Tests needed:** ~10 integration tests in `tests/integration/test_reporting_integration.py`.

### P5.15 Art. 123A(1)(b)(ii) 0.2% portfolio granularity sub-condition not implemented
- **Status:** [ ] Not started (2026-04-10 — identified in regulatory PDF cross-check)
- **Impact:** PRA PS1/26 Art. 123A(1)(b)(ii) requires that no single exposure to a counterparty exceeds 0.2% of the total regulatory retail portfolio for the exposure to qualify as retail. The current retail qualifying check (implemented in P1.91) only enforces the GBP 880k threshold (Art. 123A(1)(b)(i)), not the 0.2% granularity condition. The spec claims "Condition 2 (granularity threshold): Implemented" without noting the 0.2% sub-condition is missing. Low practical impact — most retail portfolios naturally satisfy this condition due to diversification.
- **File:Line:** `engine/classifier.py` (_build_qualifies_as_retail_expr)
- **Spec ref:** PRA PS1/26 Art. 123A(1)(b)(ii)
- **Fix:** The 0.2% check requires knowledge of total retail portfolio size at classification time. Two approaches: (a) two-pass classification (first pass sums potential retail EAD, second pass checks 0.2%), or (b) accept the portfolio size as config input (simpler). Add the check to `_build_qualifies_as_retail_expr()` with the chosen approach. Document the limitation for single-exposure calculations.
- **Tests needed:** Unit tests for the 0.2% granularity check with small/large portfolios; edge case where a single exposure exceeds 0.2%.

---

## Priority 6 -- Code Quality & Type Safety

### P6.9 Provision pro-rata weight uses pre-CCF approximation
- **Status:** [~] Approximation differs from spec
- **Impact:** `crm/provisions.py:165-166` uses `drawn_amount + interest + nominal_amount` as weight proxy. Spec says pro-rata by `ead_gross`. At provision resolution time, `ead_gross` is not yet computed (provisions run before CCF). Reasonable approximation but differs from spec.
- **Fix:** Either update spec to match implementation, or move provision step post-CCF.

### P6.15 4 missing schema fields for plan items
- **Status:** [~] Partially resolved
- **Impact:** Implementation plan items reference schema fields that do not yet exist in `data/schemas.py`:
  - `prior_charge_amount` (P1.6 junior charges)
  - `protection_inception_date` (P1.10 unfunded CRM transitional)
  - `contractual_termination_date` (P1.20 revolving maturity)
  - ~~`is_payroll_loan`~~ (P1.19 — now added)
  - ~~`is_financial_sector_entity`~~ (P1.4/P1.32 — now added as `cp_is_financial_sector_entity`)
  - ~~`includes_restructuring`~~ (P1.41 — now added)
  - ~~`has_one_day_maturity_floor`~~ (P1.40 — now added)
  - ~~`original_maturity_years`~~ (P1.40 — now added to COLLATERAL_SCHEMA)
  - ~~`due_diligence_override_rw`~~ (P1.49 — now added as `due_diligence_override_rw` + `due_diligence_performed`)
  - `liquidation_period` (P1.39 haircut dependency)
  - ~~`institution_cqs`~~ (P1.86 — now added to COUNTERPARTY_SCHEMA as pl.Int8 nullable; classifier propagates as `cp_institution_cqs`)
- **File:Line:** `data/schemas.py`
- **Fix:** Add all missing fields with appropriate types and defaults. Some fields are prerequisites for their corresponding P1 items.
- **Tests needed:** Schema validation tests for new fields.

## Priority 7 -- Future / v2.0 (Not Yet Planned)

### P7.1 Stress testing integration
- **Status:** [ ] Not started (Milestone v2.0 M4.3)

### P7.2 Portfolio-level concentration metrics
- **Status:** [ ] Not started (Milestone v2.0 M4.4)

### P7.3 REST API
- **Status:** [ ] Not started (Milestone v2.0 M4.5)

### P7.4 Additional exposure classes
- **Status:** [ ] Future enhancement
- **Scope:** Securitisation, CIU (beyond 250% fallback), covered bonds (beyond current), high-risk items.

### P7.5 Art. 150(1A) materiality/immateriality thresholds
- **Status:** [ ] Not started
- **Impact:** Under Basel 3.1, Art. 150(1A) allows IRB firms to use SA for immaterial exposure classes (below a PRA-defined threshold). Currently only reflected in COREP templates (C 08.07 cols 0160-0180 consolidated-basis-only). Not implemented in the classification engine — all exposures with IRB permission use IRB regardless of materiality.
- **Fix:** Add materiality assessment to classifier. Add `is_material_class` Boolean to output. Gate IRB routing on materiality when configured.
- **Spec ref:** PRA PS1/26 Art. 150(1A)

### P7.6 Art. 147B roll-out class tracking
- **Status:** [ ] Not started
- **Impact:** Art. 147B defines roll-out classes for B31 IRB scope-of-use reporting. Currently only mapped in COREP templates.py (`C08_07_ROWS`), not tracked in the classification engine. Exposures do not carry a `roll_out_class` column.
- **Fix:** Add roll-out class derivation to classifier Phase 2. Add `roll_out_class` column to classified output.
- **Spec ref:** PRA PS1/26 Art. 147B

### P7.7 Short-term ECAI institution risk weights (Table 4A)
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** B31 Table 4A defines different risk weights for institutions assessed on short-term ECAI ratings vs standard ratings (Table 4). The schema lacks `has_short_term_ecai` Boolean, so the code silently falls back to Table 4 for all institutions. Comment at `data/tables/b31_risk_weights.py:194` documents this gap.
- **File:Line:** `data/tables/b31_risk_weights.py:194`
- **Spec ref:** PRA PS1/26 Art. 121A Table 4A
- **Fix:** Add `has_short_term_ecai` Boolean to COUNTERPARTY_SCHEMA or RATING_SCHEMA. Add Table 4A lookup branch in B31 institution risk weight determination.

### P7.8 CRR Art. 121(4) trade finance preferential RW for unrated institutions not implemented
- **Status:** [ ] Not started (2026-05-03 — surfaced when closing DOCS_IMPLEMENTATION_PLAN.md D4.55; implementation-status callout added in `docs/specifications/crr/sa-risk-weights.md` at the "Trade Finance Preferential Treatment for Unrated Institutions (CRR Art. 121(4))" subsection, lines ~260-407)
- **Impact:** **Capital overstatement (CRR-only) for self-liquidating trade-finance exposures to unrated foreign institutions.** CRR Art. 121(4), in concert with Art. 162(3) second subparagraph point (b) and the Art. 4(1)(80) "trade finance" definition, assigns a flat 50% RW where residual maturity ≤ 1 year and a flat 20% RW where residual maturity ≤ 3 months — independent of the sovereign CQS ladder that Art. 121(1) Table 5 would otherwise impose. The CRR SA calculator routes every unrated institution through the Art. 121(1) sovereign-derived ladder with only the Art. 121(3) 20% short-term override, so unrated trade-finance exposures in CQS 2-6 jurisdictions are over-weighted (e.g. CQS 3 sovereign yields 100% in code vs the Art. 121(4) 50%). Affected population is small (UK firms on SA with material trade-finance books to unrated foreign institutions) and the rule sunsets on 31 Dec 2026 — PS1/26 restructures Art. 121 around SCRA Grade A/B/C and has no flat-50% successor.
- **File:Line:** `src/rwa_calc/data/schemas.py` (no `is_trade_finance` field on Loan/Contingent/Facility — confirm naming consistency with the ECRA branch's `is_short_term_trade_lc` flag before adding); `src/rwa_calc/data/tables/crr_risk_weights.py` (no flat 50%/20% trade-finance constants for unrated institutions); `src/rwa_calc/engine/sa/calculator.py` and `src/rwa_calc/engine/sa/namespace.py` (CRR institution branch has no Art. 121(4) check — unrated institutions currently get the Art. 121(1) Table 5 sovereign-derived ladder, with only the Art. 121(3) 20% short-term override).
- **Spec ref:** CRR Art. 121(4); Art. 162(3) second subparagraph point (b); Art. 4(1)(80) "trade finance" definition. Sunset 31 Dec 2026 (CRR-only — no PS1/26 successor at the same flat 50%; closest B31 analogue is PS1/26 Art. 121(4) movement-of-goods short-term within the SCRA ladder, tracked by D2.41 / D3.57 / P1.128).
- **Fix:** Add `is_trade_finance` Boolean to `Loan`/`Contingent`/`Facility` schemas (verify against existing `is_short_term_trade_lc` flag — keep one canonical name). Add `CRR_ART_121_4_UNRATED_TRADE_FINANCE_RW` constants (`Decimal("0.50")` and `Decimal("0.20")`) to `data/tables/crr_risk_weights.py`. In the CRR institution branch of `sa/calculator.py`, before the Art. 121(1) sovereign-derived ladder, gate on `is_unrated AND is_trade_finance AND is_self_liquidating`: assign 20% when `residual_maturity_years <= 0.25`, else 50% when `residual_maturity_years <= 1.0`. Skip the branch under B31. Add a fixture row and an acceptance test scenario contrasting a CRR unrated-institution trade-finance exposure at 9m vs 2m residual maturity.
- **Tests needed:** Unit tests for the CRR Art. 121(4) flat-50%/20% lookup; one CRR-only acceptance scenario (unrated foreign institution, self-liquidating LC, 9m and 2m residual maturity) verifying 50% and 20% RWs and confirming the sovereign-CQS ladder is not consulted; a parallel B31 scenario asserting Art. 121(4) does **not** fire (SCRA grades take over). Cross-ref: closes the `is_trade_finance` schema gap noted in D4.55; sibling code gap on the SCRA branch is D3.57 / P1.128 (B31 ECRA already correct, B31 SCRA missing the <=6m extension).

---

## New Items — Test Coverage (P5.11-P5.13)

### P5.11 Missing acceptance tests for secondary SA exposure classes
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit)
- **Impact:** The following exposure classes have 60-120 unit tests each but ZERO end-to-end acceptance tests: covered bonds (CRR Art. 129, B31 Art. 129A), PSE (Art. 116), RGLA (Art. 115), MDB (Art. 117), high-risk items (Art. 128), other items (Art. 134). Unit tests verify individual risk weight lookup functions; acceptance tests validate the full pipeline (loader → classifier → CRM → SA calculator → aggregator) for these classes. Without acceptance tests, a regression in any pipeline stage (e.g., classifier failing to route MDB entity types to the correct exposure class) would go undetected.
- **Fix:** Add CRR-K (secondary SA classes) and B31-N (secondary SA classes) acceptance test files with 6-10 scenarios each covering: CQS-based RW (covered bond, PSE, MDB), domestic currency derivation (RGLA), unrated fallback (covered bond SCRA-derived), 150% high-risk, leased residual/tangible/cash (other items).
- **Spec ref:** CRR Art. 112-134, PRA PS1/26 Art. 112-134
- **Tests needed:** ~40-60 new acceptance tests across CRR-K and B31-N.

### P5.12 Missing B31 acceptance tests for covered bond Art. 129A changes
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** Basel 3.1 Art. 129A changes the unrated covered bond risk weight derivation from institution CQS-based (CRR Art. 129(5)) to SCRA grade-based. Unit tests in `test_covered_bonds.py` cover the lookup function, but no acceptance test validates the full pipeline routing an unrated covered bond through SCRA-derived weights under B31.
- **Fix:** Include as part of P5.11 B31-N scenarios.

### P5.13 Missing acceptance tests for B31 RE treatment variations
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** Art. 124A-124L defines extensive RE treatment variants: income-dependent vs non-dependent, general vs income-producing, commercial sub-types, Other RE (Art. 124J), social housing (Art. 124L). Unit tests exist (`test_b31_re_junior_charges.py`, `test_b31_other_re.py`) but no acceptance tests validate full pipeline routing for these B31-specific RE variants.
- **Fix:** Include as part of P5.11 B31-N scenarios or a dedicated B31-O (RE variants) file.

---

## New Items — Documentation (P4.23-P4.25)

### P4.23 Stale test counts in regulatory-compliance.md
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `regulatory-compliance.md` shows outdated acceptance test counts:
  - CRR: 97 (actual: 169 — missing groups CRR-D2 advanced CRM, CRR-J equity)
  - B31: 116 (actual: 212 — missing groups B31-D7, B31-K defaulted, B31-L equity, B31-M model permissions)
  - Comparison: 62 (actual: 60)
  - Missing entirely: stress tests (56), fixture integrity (20)
- **Fix:** Update tables to reflect actual test counts. Add missing test groups to the scenario table.

### P4.24 Stale NFR metrics in nfr.md
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `nfr.md` shows:
  - NFR-3.1: "> 1,000 tests (1,844+ total: ~1,414 unit, 275 acceptance, 123 contracts, 5 integration, 27 benchmarks)"
  - Actual: 5,188 selectable (4,397 unit, 497 acceptance, 145 contracts, 122 integration, 11 benchmarks)
- **Fix:** Update NFR-3.1 metric and NFR-2.1 acceptance count.

### P4.25 Stale acceptance test scenario counts in index.md
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** `specifications/index.md` references test counts from the early implementation phase. Group tables list original scenario counts but not the expanded test suites added in 0.1.64-0.1.179.
- **Fix:** Update or remove hardcoded counts, cross-reference to `regulatory-compliance.md` for authoritative counts.

---

## Completed Items (Reference)

Closed items pruned from this file on 2026-05-03. Closure summaries remain in git history (commits referencing `[x] FIXED`, `[x] Complete`, etc.). For per-version closure detail see `docs/appendix/changelog.md`.

### Curator audit 2026-05-03 closures

Three silent fixes and one closed-claim-invalid identified by the curator audit pass on 2026-05-03. Detailed `### P-code` subsections retained above (status flipped to `[x] CLOSED`) for the audit trail; full descriptions remain so a future audit can verify the closure rationale.

- **P1.99** — CRR Art. 120 Table 4 short-term rated institution weights silently fixed; `INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR` wired in `engine/sa/namespace.py:486-494`.
- **P1.121** — CRR Art. 121(3) unrated institution short-term silently fixed; `INSTITUTION_SHORT_TERM_UNRATED_RW_CRR` (20%) wired in `engine/sa/namespace.py:495-499`.
- **P1.131** — closed-claim-invalid: pipeline reconstruction uses `dataclasses.replace(result, errors=…)` which preserves all other fields including `output_floor_summary`. Bullet was wrong when filed.
- **P1.132** — B31 government-supported equity silently fixed at `data/tables/b31_equity_rw.py:44` (now 250%, not 100%); PDF re-extract from `docs/assets/ps126app1.pdf` p.67-68 confirms PRA Art. 133 has no 100% legislative carve-out.

Sub-claim closures within open items:
- **P1.94 sub-claim (c)** — closed-claim-invalid: auto-detection from `borrower_income_currency` vs `currency` IS implemented at `engine/sa/namespace.py:1582-1606`; the `currency_mismatch_unhedged` flag the bullet referenced does not exist in the source tree.
- **P1.118 partial implementation** — `has_one_day_maturity_floor` IS now consulted by the IRB MA formula at `engine/irb/formulas.py:705-707` (suppresses the 1y M floor for carve-out rows); the bullet's stated premise that the flag "only affects CRM maturity mismatch" is no longer true. Re-scoped to remaining gap: M=2.5 default for qualifying short-term exposures without the flag.

