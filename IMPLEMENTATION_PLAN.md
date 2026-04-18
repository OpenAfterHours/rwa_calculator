# Implementation Plan

**Last updated:** 2026-04-18 (Phase 9 audit — FX haircut, equity transitional ladder, CR5/OV1/OF 08.01 reporting, COREP sign convention, classifier ADC/mixed-RE, plus 24 additional findings)
**Package version:** 0.1.193 (pyproject.toml) | **Test suite:** 5,239 selectable (5,239 total, 11 deselected benchmarks)
**Test run (2026-04-11):** 5,207 passed, 21 skipped (conditional fixture guards), 11 deselected (benchmarks)
**CRR acceptance:** 100% (169 tests) | **Basel 3.1 acceptance:** 100% (212 tests) | **Comparison:** 100% (60 tests) | **Stress:** 56 tests (+ 4 slow)
**Unit:** 4,397 | **Contract:** 145 | **Integration:** 122 | **Acceptance:** 497 selectable
**Acceptance tests skipped at runtime:** 21 (all conditional fixture-data guards — B31 FIRB 8, CRR FIRB 7, B31 CRM 7, provisions 15, output floor 4, stress 2; no unconditional skips)
**Source code TODO/FIXME/HACK count:** 0 (confirmed 2026-04-10; only "not implemented" markers are CCR rows in COREP generator, acknowledged out-of-scope)

---

## Remaining Work — Prioritized Bullet List

Items are sorted by priority. Each item notes its ID, status, and effort estimate (S/M/L).

### Tier 1 — Calculation Correctness (must fix for regulatory accuracy)

- **P1.92** [x] **FIXED v0.1.194** — FCSM 20% floor moved to per-item application in `compute_fcsm_columns()` so that Art. 222(4)/(6) carve-out items (same-currency cash, 0%-RW sovereign) flow through at 0% and are not re-floored after the weighted average. `_apply_fcsm_rw_substitution()` no longer re-imposes the aggregate floor. Bundles the P4.50 labelling fix (Art. 222(4) vs PRA PS1/26 Art. 222(6)) into the same change. | Ref: CRR Art. 222(1)/(4); PRA PS1/26 Art. 222(3)/(6)
- **P1.93** [ ] **NEW** — FCSM Art. 222(4) SFT zero-haircut 0%/10% exception not implemented. SFTs meeting Art. 227 zero-haircut conditions should get 0% RW (or 10% if counterparty is not a core market participant per Art. 227(3)). Art. 222(6) same-currency cash/sovereign 0% also not gated. No `is_core_market_participant` field in schema. **Effort: M** | Ref: PRA PS1/26 Art. 222(4)/(6), Art. 227(3)
- **P1.94** [~] **PARTIAL (150% cap fixed v0.1.192; remaining gaps open)** — B31 currency mismatch 1.5x now capped at 150%. `sa/calculator.py:1796` uses `.clip(upper_bound=1.50)` per Art. 123B. Defaulted retail (150% base) with currency mismatch no longer inflated to 225%. New test `test_currency_mismatch_capped_at_150_pct` validates the cap. Remaining work:
  - (a) `is_hedged` flag missing from schema; multiplier fires on hedged exposures. `src/rwa_calc/engine/sa/calculator.py:1766–1768`, `schemas.py:190`.
  - (b) 90%-coverage hedge test (Art. 123B(2)) not implemented.
  - (c) Auto-detection via `borrower_income_currency` vs loan currency missing; code requires explicit `currency_mismatch_unhedged` flag (`calculator.py:1749`).
  - (d) Revolving-facility instalment rule (Art. 123B(2A)) not implemented.
  - (e) Pre-2027 portfolio fallback (Art. 123B(3)) not implemented.
  - (f) Scope check too broad — `contains("COMMERCIAL")` catches non-RRE CRE; should be retail (h) and residential RE (i) only. `calculator.py:1758–1764`.
  - (g) CR5 reporting convention (base RW with multiplied RWEA) missing; OF 02.00 row 0380 memo not populated. `reporting/pillar3/generator.py:325–358`, `reporting/corep/generator.py`.
  **Effort: S** | Ref: PRA PS1/26 Art. 123B
- **P1.95** [ ] **NEW** — B31 guarantee substitution uses CRR CQS-based institution RW instead of SCRA grades for unrated institution guarantors. `sa/calculator.py:1568-1582` applies 40% (UK deviation) for unrated institution guarantors regardless of framework. Under B31, unrated institutions use SCRA grades (A→40%, B→75%, C→150%), not CQS-derived sovereign fallback. **Effort: M** | Ref: PRA PS1/26 Art. 121/235
- **P1.96** [~] **DOWNGRADED** — Covered bond collateral haircut falls through to `other_physical` (40% default). `haircuts.py:_normalize_collateral_type_expr` does not recognise `covered_bond`/`covered_bonds` as a distinct collateral type. However, PDF extraction confirms covered bonds are **NOT listed** in PRA PS1/26 Art. 197 as eligible financial collateral for FCCM/FCSM. They only appear in Art. 207(2) (repo exception) and Art. 161(1)(d) (F-IRB LGD 11.25%). Impact is limited to the narrow Art. 207(2) repo scenario where covered bonds are used as collateral. **Effort: S** | Ref: PRA PS1/26 Art. 197, 207(2), 224
- **P1.97** [ ] **NEW** — B31 slotting missing non-HVCRE subgrade maturity differentiation (Art. 153(5)(d)). PRA Table A has columns A/B (Strong) and C/D (Good) with maturity-based subgrades: Strong A=50% (<2.5yr) vs B=70% (>=2.5yr), Good C=70% vs D=90%. Code has no B31 `_SHORT` table variants and `namespace.py:408-416` ignores `is_short` for B31. Art. 153(5)(d) says firms "may" use lower weights — optional but should be supported. Non-HVCRE only; HVCRE subgrades tracked separately as P1.117. **Effort: S** | Ref: PRA PS1/26 Art. 153(5)(d) Table A columns A-D
- **P1.98** [ ] **NEW** — Subordinated corporate A-IRB LGD floor fallback uses 50% instead of 25%. `formulas.py:157-166` applies `floors.subordinated_unsecured` (50%) when `exposure_class` absent and `seniority` contains "sub". Art. 161(5) makes no senior/subordinated distinction — all corporate unsecured = 25%. Only affects fallback path but is regulatory non-compliant. **Effort: S** | Ref: PRA PS1/26 Art. 161(5)
- **P1.99** [ ] **NEW** — CRR short-term institution risk weights (Art. 120 Table 4) not applied. Short-term (<= 3 months) domestic-currency institution exposures should get lower RW (e.g., CQS 2 = 20% instead of 30%). CRR code path has no short-term institution treatment — falls through to long-term table. **Effort: S** | Ref: CRR Art. 120(1)-(2)
- **P1.100** [ ] **NEW** — Art. 137 ECA score-to-CQS mapping not implemented. Unrated sovereigns with ECA risk scores 0-7 should map to CQS 1-6 per Table 9. No `eca_score` field in schema. Unrated sovereigns default to 100% instead of potentially 0% (ECA 0-1). **Effort: S** | Ref: CRR Art. 137
- **P1.101** [ ] **NEW** — Art. 226(1) non-daily revaluation haircut adjustment not implemented. When collateral is revalued less frequently than daily, supervisory haircuts should be scaled by `sqrt((NR + T_m - 1) / T_m)`. No `revaluation_frequency_days` input field. Understates haircuts for infrequently revalued collateral. **Effort: S** | Ref: CRR Art. 226(1)
- **P1.102** [x] **FIXED v0.1.190** — CRR defaulted A-IRB non-retail: 1.06 scaling removed from defaulted path. Art. 153(1)(ii) defaulted formula `RW = max(0, 12.5 × (LGD - ELBE))` has no 1.06 — the 1.06 only appears in the non-defaulted Vasicek formula Art. 153(1)(iii). Removed `scaling` variable and dead `config` parameter from `apply_defaulted_treatment()`. Updated 3 call sites. Corrected CRR-I3 acceptance and unit tests from 993,750 to 937,500. Updated B31-K11 comparison test (CRR and B31 now produce identical defaulted RWA). **Effort: S** | Ref: CRR Art. 153(1)(ii)
- **P1.103** [ ] **NEW** — Art. 122(3) Table 6A short-term corporate ECAI risk weights not implemented. PRA PS1/26 introduces Table 6A: CQS1=20%, CQS2=50%, CQS3=100%, Others=150%. Neither spec nor code references Table 6A. Code falls through to long-term CQS table. **Effort: S** | Ref: PRA PS1/26 Art. 122(3)
- **P1.104** [ ] **NEW** — FCSM Art. 222(7) maturity eligibility check missing. Simple Method requires collateral residual maturity >= exposure residual maturity (no mismatch allowed). `simple_method.py:compute_fcsm_columns()` never checks maturity relationship. Collateral with shorter maturity than exposure is incorrectly recognised. **Effort: S** | Ref: CRR Art. 222(7)
- **P1.106** [ ] **NEW** — FCSM collateral RW for institution bonds ignores UK deviation. `simple_method.py:90-91` uses CQS 2-3 = 50% for all institution bonds. CRR Art. 119 with UK deviation gives CQS 2 = 30%. Conservative overstatement (50% > 30%). `_derive_collateral_rw_expr()` takes `is_basel_3_1` but not `use_uk_deviation`. **Effort: S** | Ref: CRR Art. 119, UK CRR deviation
- **P1.107** [ ] **NEW** — FCSM collateral RW for B31 corporate CQS 3 bonds uses 100% instead of 75%. `simple_method.py:110-111` gives CQS 3 = 100%. B31 Art. 122 Table 6 gives CQS 3 = 75%. Conservative overstatement. **Effort: S** | Ref: PRA PS1/26 Art. 122(2) Table 6
- **P1.108** [~] **DISPUTED** — CRR 1.06 scaling factor applied to retail IRB exposures. `formulas.py:360` and `namespace.py:488` apply 1.06 to ALL CRR exposure classes including retail. BCBS CRE31.23 (retail formula) has NO 1.06, but **UK-onshored CRR Art. 154(1) text (page 151 of CRR PDF) includes `× 12.5 × 1.06` in the retail formula**. If the UK CRR text is authoritative, the code is CORRECT. Needs PRA legal clarification on whether this is a transcription artefact or intentional UK deviation. B31 unaffected (1.06 removed entirely). Defaulted path at `adjustments.py:83` correctly exempts retail. **Effort: S (if confirmed as bug)** | Ref: CRR Art. 153(1), Art. 154(1), BCBS CRE31.23
- **P1.109** [ ] **NEW** — Art. 237-238 maturity mismatch not applied to unfunded credit protection (guarantees/CDS). `guarantees.py` applies FX haircut but NO maturity mismatch. When guarantee maturity < exposure maturity, Art. 238 requires `GA = G* × (t-0.25)/(T-0.25)` reduction. Art. 237(2) requires ineligibility when residual < 3 months or original < 1 year. **Understates capital** for exposures with short-dated guarantees. **Effort: M** | Ref: CRR Art. 237-238
- **P1.110** [ ] **NEW** — B31 guarantee substitution CQS table uses CRR corporate weights (CQS 3=100%). `sa/calculator.py:1630-1631` maps corporate guarantor CQS 3-4 to 100% under both CRR and B31. B31 Table 6 gives CQS 3=75%. **Overstates capital** for B31 exposures with CQS 3 corporate guarantors. Related to P1.95 (SCRA) but distinct: P1.95 is about unrated institution guarantors, P1.110 is about rated corporate guarantors. **Effort: S** | Ref: PRA PS1/26 Art. 122(2) Table 6, Art. 235
- **P1.111** [x] **FIXED v0.1.197** — Art. 124G(2) junior RRE 1.25x multiplier no longer capped at 105%. Both `b31_residential_rw_expr()` (Polars expr, `data/tables/b31_risk_weights.py:463`) and `lookup_b31_residential_rw()` (scalar, `:671`) now return `base_income * junior_multiplier` directly, so LTV > 100% with a junior lien correctly resolves to 131.25% (105% × 1.25) instead of being capped at the 105% table maximum. Existing guard test `test_multiplier_capped_at_105` renamed to `test_multiplier_not_capped_at_105` (asserts 1.3125) and new scalar test `test_rre_scalar_income_junior_uncapped_high_ltv` added. Stale "Code Divergence" admonition in `docs/data-model/regulatory-tables.md` converted to "Resolved". **Effort: S** | Ref: PRA PS1/26 Art. 124G(2)
- **P1.112** [ ] **NEW** — Non-UK unrated PSE/RGLA default to 100% instead of sovereign-derived lookup. `sa/calculator.py:676-680` (B31 PSE), `696-700` (B31 RGLA), `996-1000` (CRR PSE), `1013-1017` (CRR RGLA) all use `cp_country_code == "GB" → 20%, otherwise → 100%`. Art. 116(1) Table 2 / Art. 115(1)(a) Table 1A require sovereign CQS-derived weights (e.g., CQS 1 sovereign → 20%). `cp_sovereign_cqs` field is available in schema. **Overstates capital** for non-UK PSE/RGLA with low sovereign CQS. **Effort: S** | Ref: CRR Art. 115(1)(a), Art. 116(1)
- **P1.113** [x] **FIXED v0.1.187** — B31 rated covered bond risk weights corrected from BCBS CRE20.28 to PRA Table 7. `b31_risk_weights.py` dict and DataFrame both updated: CQS 2 from 15%→20%, CQS 6 from 50%→100%. PRA PS1/26 Art. 129(4) Table 7 is identical to CRR Table 6A (PRA did NOT adopt BCBS reductions). All 77 covered bond tests updated and passing. 3 stale doc warnings converted to "Fixed" admonitions. **Effort: S** | Ref: PRA PS1/26 Art. 129(4) Table 7
- **P1.114** [ ] **NEW** — Classifier null propagation in `str.contains()` for book_code/country_code silently routes to SA. `classifier.py:805,809` — when `cp_country_code` or `book_code` is null on an exposure row and the model_permissions field is non-null, `str.contains(null)` propagates null into `permission_valid`, causing silent SA fallback. Fix: add `.fill_null("")` on exposure columns before `str.contains()`. Effort: S | Ref: classifier model_permissions resolution
- **P1.115** [x] **FIXED v0.1.191** — CRR Art. 230 subordinated F-IRB LGDS implemented. CRR Table 5 subordinated rows added: receivables 65%, RE 65%, other physical 70%. `lookup_firb_lgd()` now returns correct LGDS for subordinated collateralised exposures. PRA PS1/26 correct (no subordinated LGDS). **CRR-only capital understatement resolved.** Effort: S | Ref: CRR Art. 230 Table 5
- **P1.116** [x] **FIXED v0.1.185** — EL shortfall deduction corrected from 50/50 CET1/T2 to 100% CET1 per Art. 36(1)(d). Also corrected OF-ADJ cascading impact (CET1 deduction doubled, making floor threshold more conservative). `_el_summary.py:239-241` previously applied `effective_shortfall * 0.5` to both. Effort: S | Ref: CRR Art. 36(1)(d), Art. 159
- **P1.117** [ ] **NEW** — B31 HVCRE short-maturity subgrades not implemented (distinct from P1.97). P1.97 covers non-HVCRE (Strong A=50%/B=70%, Good C=70%/D=90%). HVCRE Table A also has maturity-based subgrades: Strong A=70%/B=95%, Good C=95%/D=120%. No `B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` table exists. `namespace.py:408-416` ignores `is_short` for all B31 slotting. Effort: S | Ref: PRA PS1/26 Art. 153(5)(d)
- **P1.118** [ ] **NEW** — Art. 162(3) short-maturity IRB override not implemented. Qualified short-term exposures (FX settlement, trade finance <=1yr, repos) should get M = maturity value per Art. 162(3) instead of default M = 2.5. The `has_one_day_maturity_floor` flag exists but only affects CRM maturity mismatch, not the IRB capital formula. Also covers Art. 162(3) one-day maturity floor on M; `has_one_day_maturity_floor` column currently only consulted for CRM maturity-mismatch ineligibility, not IRB M computation. Effort: M | Ref: CRR Art. 162(3), PRA PS1/26 Art. 162(3)
- **P1.119** [x] **FIXED v0.1.184** — CIU fallback risk weight corrected to 1,250% under both CRR and B31 (Art. 132(2)). Was 150% CRR / 250%-400% B31. Extracted shared `CIU_FALLBACK_RW` constant and `_append_ciu_branches()` helper. All CIU tests updated. **Effort: S** | Ref: CRR Art. 132(2), PRA PS1/26 Art. 132(2)
- **P1.120** [ ] **NEW** — B31 SA defaulted provision-ratio denominator wrong (D3.19). Art. 127(1) requires `specific_provisions / gross_outstanding_amount` but code uses `unsecured_ead` (post-provision, post-CRM). For partially collateralised exposures, the smaller denominator can push the ratio below 20%, inflating RW from 100% to 150%. **Impact: Capital overstatement for collateralised defaulted exposures**. **Effort: S** | Ref: PRA PS1/26 Art. 127(1), `calculator.py:1250-1275`
- **P1.121** [ ] **NEW** — CRR Art. 121(3) unrated institution short-term 20% not applied. CRR code path has no handling for unrated institutions with residual maturity <= 3 months denominated in domestic currency. These should get 20% instead of 40% (UK) or 100% (standard). Capital overstated by up to 100%. **Effort: S** | Ref: CRR Art. 121(3)
- **P1.122** [ ] **NEW** — Guarantee substitution has no B31 framework branching. `_apply_guarantee_substitution()` at `sa/calculator.py:1428-1709` has zero `is_basel_3_1` checks. Uses single CQS table for both CRR and B31. Affects: (a) corporate CQS 3 = 100% (should be 75% under B31 per Table 6), (b) unrated institutions use CRR sovereign-derived (should use SCRA grades), (c) no short-term guarantor institution treatment. P1.95 and P1.110 are symptoms of this broader issue. **Effort: M** | Ref: PRA PS1/26 Art. 122/121/235
- **P1.123** [ ] **NEW** — FCCM missing exposure volatility haircut (HE) for SFT exposures. Art. 223(5) formula: `E* = max(0, E(1+HE) - CVA(1-HC-HFX))`. `collateral.py` omits the `(1+HE)` gross-up on the exposure side. HE=0 for standard lending (correct), but HE>0 for SFTs where exposure is a debt security. **Understates E* and hence RWA for SFT portfolios.** **Effort: M** | Ref: CRR Art. 223(5)
- **P1.124** [ ] **NEW** — Art. 237(2) guarantee ineligibility conditions not enforced. Guarantees with residual maturity < 3 months or original maturity < 1 year should be rejected entirely. Collateral maturity checks are correctly implemented in `haircuts.py:476-480`, but `guarantees.py` has no equivalent maturity eligibility check. Subset of P1.109 but distinct: P1.109 is the maturity mismatch *adjustment*, this is the eligibility *rejection*. **Effort: S** | Ref: CRR Art. 237(2)
- **P1.125** [ ] **NEW** — Classifier missing FSE column warning under B31. When `cp_is_financial_sector_entity` column is absent, `classifier.py:989-994` silently defaults `_is_fse = pl.lit(False)`, letting all FSEs get A-IRB instead of F-IRB (Art. 147A(1)(e)). Classifier already emits warnings for missing QRRE columns and retail pool management columns but not for FSE. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(e)
- **P1.126** [ ] **NEW** — Classifier Art. 147A(1)(d) null revenue defaults to "not large" (A-IRB permitted). `classifier.py:995-997` uses `fill_null(False)` on the large corporate check. Corporates with unknown revenue that exceed GBP 440m could get A-IRB instead of F-IRB. Should either conservatively treat null as "large" or emit a warning. **Effort: S** | Ref: PRA PS1/26 Art. 147A(1)(d)
- **P1.127** [ ] **NEW** — Art. 159 Pool B composition: upstream per-exposure EL shortfall may not include AVA/other own funds reductions. Aggregator `_el_summary.py:197-201` correctly implements the two-branch rule but relies on upstream `el_shortfall`/`el_excess` columns. If IRB/slotting calculators compute shortfall as `max(0, EL - provisions)` without including AVA (Art. 34/105) and other own funds reductions in Pool B, the two-branch condition may be incorrectly evaluated. **Needs upstream verification.** **Effort: S** | Ref: CRR Art. 159(1)
- **P1.128** [ ] **NEW (Phase 8)** — B31 SCRA short-term missing Art. 121(4) trade finance <=6m extension. `sa/calculator.py:751-754` checks `residual_maturity_years <= 0.25` for SCRA (unrated institution) short-term but does NOT include the trade goods <=6m exception. The ECRA branch at `sa/calculator.py:730-739` correctly has `is_short_term_trade_lc & residual_maturity_years <= 0.5` but the SCRA branch omits this. Art. 121(4) grants the same exception to SCRA-graded institutions. **Overstates capital** for unrated institution trade finance exposures with 3-6m residual maturity. **Effort: S** | Ref: PRA PS1/26 Art. 121(4)
- **P1.129** [x] **FIXED v0.1.186** — B31 ADC pre-sold 100% concession now restricted to residential only (Art. 124K(2)). `b31_adc_rw_expr()` checks `property_type == "residential"` before granting 100% concession. Commercial/null property_type ADC always gets 150%. Uses `PropertyType.RESIDENTIAL` enum, named constants, and `.str.to_lowercase()` for consistency. 3 new tests (residential 100%, commercial 150%, null 150%). **Effort: S** | Ref: PRA PS1/26 Art. 124K(2)
- **P1.130** [ ] **NEW (Phase 8)** — Aggregator summaries use pre-floor RWA. `aggregator.py:92-96` generates `summary_by_class` and `summary_by_approach` from `post_crm_detailed` BEFORE the output floor is applied at line 152. Since Polars LazyFrames are immutable, `apply_floor_with_impact()` returns a new LazyFrame that doesn't affect the pre-existing summary plans. Consumers expecting post-floor totals in summaries will see pre-floor RWA. **Understates reported RWA** when output floor is binding. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P1.131** [x] **FIXED v0.1.193** — Pipeline bundle reconstruction now uses `dataclasses.replace(result, errors=all_errors)` instead of manual 15-field copy. Previously omitted `output_floor_summary`, silently discarding the computed floor summary when loader/pipeline errors existed. Affected COREP OF 02.00 rows 0035/0036. Regression test added (`test_output_floor_summary_preserved_with_errors`). Using `replace()` prevents this class of bug for any future fields added to `AggregatedResultBundle`. **Effort: S** | Ref: PRA PS1/26 Art. 92(2A)
- **P1.132** [x] **FIXED v0.1.189** — B31 government-supported equity corrected from 100% to 250% per Art. 133(3). Art. 133(6) is an exclusion clause (own funds deductions, Art. 89(3), Art. 48(4)), not a 100% risk weight. CRR Art. 133(3)(c) legislative equity carve-out has no B31 equivalent. Government-supported equity removed from transitional floor exclusion (now subject to floor as standard equity; 250% exceeds all transitional floors). Art. 133 paragraph references corrected: subordinated debt = Art. 133(5) not 133(1); PE/VC = Art. 133(4) not 133(5). **Effort: S** | Ref: PRA PS1/26 Art. 133(3)/(6)
- **P1.30(e)** [ ] Art. 234 partial protection tranching — structured protection covering only part of the loss range. Not modelled. **Effort: L** | Ref: PRA PS1/26 Art. 234
- **P1.105** [ ] **NEW** — B31 Table 4A short-term institution ECAI risk weights not applied. `has_short_term_ecai` flag missing from schema. Table 4A gives CQS2=50%, CQS3=100% vs Table 4 fallback of 20% for both — current code *understates* risk for CQS 2-3 short-term-rated institutions. Also blocks Art. 122(3) Table 6A (P1.103). **Effort: S** | Ref: PRA PS1/26 Art. 120(2B), Art. 122(3)
- **P1.10** [ ] Unfunded credit protection transitional (PRA Rule 4.11) — narrow eligibility carve-out for legacy contracts during 1 Jan 2027–30 Jun 2028. Requires Art. 213 eligibility validation first. **Effort: M** | Ref: PRA PS1/26 Rule 4.11
- **P1.148** [x] **FIXED v0.1.195** — Art. 124I(3) junior-charge CRE >80% LTV double-multiplication eliminated. Replaced `B31_CRE_INCOME_JUNIOR_MULTIPLIER_{LOW,MID,HIGH}` (1.0/1.25/1.375 multipliers) with absolute RW constants `B31_CRE_INCOME_JUNIOR_RW_{LOW,MID,HIGH}` (1.00/1.25/1.375) in `data/tables/b31_risk_weights.py`. Both the Polars expression `b31_commercial_rw_expr()` and scalar `lookup_b31_commercial_rw()` now assign the absolute junior RW directly instead of multiplying against the Art. 124I(1)/(2) base. Resolves +13.75pp over-capital at LTV>80% (previously 110% × 1.375 = 151.25%; now 137.5% absolute). Unit tests updated to expect 1.375 absolute; regression guard comments added. **Effort: S** | Ref: PRA PS1/26 Art. 124I(3) (ps126app1.pdf p.57)
- **P1.149** [ ] **NEW** — CRR Institution CQS 2 risk weight wrong. `src/rwa_calc/engine/sa/crr_risk_weights.py:121`. Code uses 30%; CRR Art. 120 Table 3 requires 50%. Affects CRR-config SA calculations for A-rated institutions. **Effort: S** | Ref: CRR Art. 120 Table 3
- **P1.150** [ ] **NEW** — HVCRE Good slotting EL rate wrong. `src/rwa_calc/engine/slotting/b31_slotting.py:93`, `crr_slotting.py:93–98`. Code has 0.8%; PRA PS1/26 Art. 158(6) Table B (Appendix 1 page 108, verified 2026-04-18) gives 0.4% for HVCRE Good (both columns C and D). Fix: 0.8% → 0.4%. **Effort: S** | Ref: PRA PS1/26 Art. 158(6) Table B
- **P1.151** [ ] **NEW** — Purchased receivables / dilution-risk LGD missing (Art. 161(1)(e)–(g)). `src/rwa_calc/engine/irb/firb_lgd.py`. No `purchased_receivables_senior`, `_subordinated`, `dilution_risk` keys. Exposures default to 45% senior. B3.1 dilution-risk LGD = 100% not applied. **Effort: M** | Ref: PRA PS1/26 Art. 161(1)(e)-(g)
- **P1.152** [x] **FIXED (2026-04-18)** — F-IRB repo maturity fixed at 2.5y. Implemented per CRR Art. 162(1): new `is_sft` boolean flag on Facility/Loan/Contingent inputs propagates through hierarchy → unified exposures; `irb.prepare_columns()` overrides M → 0.5y for F-IRB SFTs under CRR only (B3.1 deleted Art. 162(1); F-IRB under B3.1 calculates M per Art. 162(2A)). Files: `src/rwa_calc/data/schemas.py`, `src/rwa_calc/engine/hierarchy.py`, `src/rwa_calc/engine/irb/namespace.py`. Regression: `tests/unit/irb/test_firb_sft_maturity.py` (6 tests). **Effort: S** | Ref: CRR Art. 162(1)
- **P1.153** [ ] **NEW** — Art. 155(3) PD/LGD equity approach entirely absent. `src/rwa_calc/engine/equity/`. No `EquityApproach.PD_LGD` enum, no Art. 165 floor table (0.09%/0.40%/1.25%), no M=5y equity handling, no EL×12.5+RWEA cap. Required under CRR; removed under B3.1. **Effort: L** | Ref: CRR Art. 155(3), Art. 165
- **P1.154** [ ] **NEW** — `international_org` collapsed into MDB. `src/rwa_calc/engine/classifier.py:80, 119`, `src/rwa_calc/domain/enums.py`. Art. 112(1)(e) international organisations (IMF, BIS) misclassified as MDB. Add `ExposureClass.INTERNATIONAL_ORGANISATION`; route SA and IRB mappings accordingly. **Effort: M** | Ref: CRR Art. 112(1)(e), Art. 117-118
- **P1.155** [ ] **NEW** — Art. 224 haircut table four wrong values. `src/rwa_calc/engine/crm/haircuts.py:93–116`. Corrections: sovereign CQS2-3 >10y 12%→6%; corporate CQS2-3 5-10y 15%→12%; corporate CQS2-3 >10y 15%→20%; government bond 3-5y 4%→3%. **Effort: S** | Ref: CRR Art. 224 Table 1
- **P1.156** [ ] **NEW** — PSM guarantor LGD hard-coded 40%. `src/rwa_calc/engine/irb/guarantee.py:302, 462`. Art. 236 requires seniority-aware LGD: 40% non-FSE senior / 45% FSE senior / 75% subordinated, or borrower's unprotected LGD (option 1). **Effort: S** | Ref: CRR Art. 236
- **P1.157** [ ] **NEW** — PSM PD uplift "no better than direct" missing (Art. 160(4)). `src/rwa_calc/engine/irb/guarantee.py:316`. PSM-guaranteed PD must be floored at direct-exposure PD to avoid PSM producing lower capital than direct exposure to guarantor. **Effort: S** | Ref: CRR Art. 160(4)
- **P1.158** [ ] **NEW** — Null collateral maturity defaults to 5y. `src/rwa_calc/engine/crm/haircuts.py:449`. Art. 224 conservative fallback should be >10y band, not 5y (produces lower haircut than intended when maturity is missing). **Effort: S** | Ref: CRR Art. 224
- **P6.9** [~] Provision pro-rata weight uses pre-CCF approximation (`drawn + interest + nominal`) instead of spec's `ead_gross`. Reasonable but diverges from spec. **Effort: S** | Ref: CRM spec
- **P6.15** [~] 3 missing schema fields: `protection_inception_date` (P1.10), `contractual_termination_date` (P1.20 revolving maturity), `liquidation_period` as config (P1.39 dependency). **Effort: S**

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
- **P1.133** [ ] **NEW (Phase 8)** — Short-term PSE/institution treatment uses `residual_maturity_years` instead of `original_maturity_years`. `calculator.py:677,734,754,999` all check `residual_maturity_years <= 0.25`. CRR Art. 116(3)/120(1) specify "original effective maturity" of 3 months. A 5-year bond with 2 months remaining incorrectly gets short-term weight. `original_maturity_years` is in schema but unused by SA calculator. **Understates capital.** **Effort: S** | Ref: CRR Art. 116(3), Art. 120(1)
- **P1.134** [x] **FIXED v0.1.188** — B31 unrated covered bond with rated issuer defaults to 100% instead of CQS-derived weight. Added `_b31_unrated_cb_rw_expr()` that checks ECRA first (`cp_institution_cqs`), then SCRA fallback (`cp_scra_grade`). Rated institutions now correctly get CQS-derived weight via Art. 129(5) derivation table (e.g., CQS 1 → 10%). 7 new tests (6 ECRA parametrized CQS 1–6 + 1 ECRA-priority-over-SCRA test). **Effort: S** | Ref: PRA PS1/26 Art. 129(5)
- **P1.135** [x] **FIXED v0.1.63** — FX haircut on collateral silently zero after FX conversion. Fixed alongside P1.136: `FXConverter.convert_collateral/guarantees/provisions/equity_exposures` now all preserve `original_currency` on both the conversion and no-conversion paths. `engine/crm/processor.py::_build_exposure_lookups` populates the collateral-side `exposure_currency` from the exposure's `original_currency` (falling back to `currency`). `engine/crm/haircuts.py` compares the collateral's `original_currency` against `exposure_currency` (falling back to `currency` when absent). `engine/hierarchy.py` no longer branches on `apply_fx_conversion` for the audit column — the converters handle the fall-through consistently. 5 new regression tests in `tests/unit/crm/test_collateral_fx_mismatch.py` + 2 new fx_converter tests. Art. 224 8% H_fx now correctly fires on FX-mismatched secured exposures. **Effort: S** | Ref: CRR Art. 224, PRA PS1/26 Art. 224
- **P1.136** [x] **FIXED v0.1.63** — Bundled with P1.135. FXConverter now preserves `original_currency` symmetrically across exposures, collateral, guarantees, provisions and equity exposures. Downstream consumption is live for collateral (processor + haircut comparison); provisions/equity retain the audit column for future Art. 233/195 FX-mismatch extensions. **Effort: S** | Ref: CRR Art. 224
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
- **P2.9** [ ] OF 34.07 — IRB CCR template. CCR is out of scope; document as known gap or add placeholder. **Effort: S**
- **P4.20** [ ] C 08.02 PD bands use fixed buckets instead of firm-specific internal rating grades. **Effort: M**

### Tier 4 — Pillar III Disclosure Gaps

- **P3.5** [ ] **NEW** — CR9.1 (ECAI-based PD backtesting) has template definitions but no generator method, no bundle field, no stub. P3.2 marked [x] Complete but CR9.1 is not callable. **Effort: S**
- **P3.3** [~] Missing qualitative tables UKB CRD (SA qualitative, Art. 444(a-d)) and UKB CRE (IRB qualitative, Art. 452(a-f)). CR6 AIRB purchased receivables sub-row missing. CR5 rows 18-33 not detailed. **Effort: M**
- **P3.6** [ ] **NEW (Phase 9)** — CR5 / CR9 / OV1 disclosure gaps overlap with P2.25/P2.28/P2.29. Pillar III tables cannot faithfully reproduce Annex XX / XXII rows without: (a) pre-multiplier RW column for currency-mismatch disclosure, (b) equity transitional end-state RW column, (c) AIRB RE 4-way sub-class split, (d) FIRB financial/large-corp sub-rows, (e) OV1 equity sub-approach populations. Track alongside the P2 items but call out for Pillar III sign-off. **Effort: M** | Ref: PRA PS1/26 Annex XX §CR5/OV1, Annex XXII §CR9

### Tier 5 — Documentation & Consistency

- **P4.2** [~] Stale version numbers — `overview.md` says 0.1.37, `prd.md` says 0.1.28. **Effort: S**
- **P4.3** [~] Stale `docs/plans/implementation-plan.md` — shows items as incomplete that are done. **Effort: S**
- **P4.4** [~] Stale PRD FR statuses. **Effort: S**
- **P4.8** [~] COREP template spec thin in `output-reporting.md` — detailed in `corep-reporting.md` feature doc. Cross-reference needed. **Effort: S**
- **P4.9** [~] Type checker inconsistency — docs disagree with CLAUDE.md (`mypy` vs `ty`). **Effort: S**
- **P4.10** [~] `model_permissions` not in architecture spec. **Effort: S**
- **P4.11** [x] SA risk weight spec missing Art. 137 ECA Table 9. **FIXED (Phase 7)** — Added Art. 131 Table 7 and Art. 137 ECA/MEIP content to CRR SA spec.
- **P4.12** [x] Equity spec BCBS CQS speculative tier references. **FIXED (Phase 7)** — Removed from both CRR and B31 equity specs; replaced with PRA Art. 133(4) higher-risk definition.
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
- **P4.34** [x] SCRA Grade A Enhanced article reference wrong in B31 spec. **FIXED (Phase 7)** — Changed Art. 120(2A) to Art. 121(5) in B31 SA spec.
- **P4.35** [x] Currency mismatch article reference wrong. **FIXED (Phase 7)** — Changed Art. 123A to Art. 123B in B31 SA spec (3 locations).
- **P4.36** [x] B31 slotting spec "flat weights" error. **FIXED (Phase 7)** — Corrected to maturity-differentiated 7-column Table A with A/B/C/D subgrades. Added correction warning.
- **P4.37** [x] CRR PD floor article reference wrong for retail. **FIXED (Phase 7)** — Added Art. 163(1) for retail alongside Art. 160(1) for corporate/institution.
- **P4.38** [x] B31 provisions spec Pool A/B labelling inverted. **FIXED (Phase 7)** — Replaced with regulation's A/B/C/D scheme. Added correction admonition.
- **P4.39** [x] B31 slotting spec EL table incomplete. **FIXED (Phase 7)** — Added short-maturity EL values (Strong=0%, Good=0.4%).
- **P4.41** [x] B31 SA spec missing 80% high-quality PF. **FIXED (Phase 7)** — Added 80% row with Art. 122B(4)-(5) qualifying criteria.
- **P4.42** [x] B31 SA spec Art. 124I junior charge wrong. **FIXED (Phase 7)** — Replaced single multiplier with 3-band table.
- **P4.43** [x] CRR SA spec RGLA unrated fallback missing. **FIXED (Phase 7)** — Added "Unrated = 100%" rows to RGLA and PSE tables.
- **P4.44** [x] B31 SA spec missing Art. 121(4) trade goods ≤6m exception. **FIXED (Phase 7)** — Added SCRA short-term trade finance subsection.
- **P4.45** [x] B31 provisions spec missing Art. 159(3) two-branch rule. **FIXED (Phase 7)** — Fully documented all four branches with cross-subsidisation prevention.
- **P4.46** [x] Output floor spec article numbers conflated. **FIXED (Phase 7)** — Corrected: Art. 92(2A) = formula, Art. 92(5) = transitional opt-in. Added permissive note.
- **P4.40** [x] Equity spec Art. 133 paragraph numbering. **FIXED (Phase 7)** — Corrected CRR and B31 specs: higher-risk → Art. 133(4), subordinated → Art. 133(5), legislative → Art. 133(6).
- **P4.48** [ ] **NEW** — Covered bond Art. 161(1B) references. `src/rwa_calc/engine/irb/firb_lgd.py:256, 263, 698, 717, 776, 804`. Article number doesn't exist; correct reference is Art. 161(1)(d). Value (11.25%) is correct. **Effort: S**
- **P4.49** [ ] **NEW** — CCF docstrings cite Art. 166(9) for 20% trade LC. `src/rwa_calc/engine/irb/ccf.py:7, 132, 150, 164, 189`. Correct reference is Art. 166(8)(b). Art. 166(9) is the overlapping-commitment lower-of rule. **Effort: S**
- **P4.50** [x] **FIXED v0.1.194** — Art. 222 FCSM labelling corrected in `crm/simple_method.py` docstrings: same-currency cash and 0%-RW sovereign carve-outs are cited as CRR Art. 222(4) / PRA PS1/26 Art. 222(6). Bundled with P1.92. | Ref: PRA PS1/26 Art. 222(6)
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

**Open P1 items: 39 total (25S + 12M + 1L + 1 verification).** P1.92 fixed in v0.1.62; P1.135 and P1.136 fixed in v0.1.63; P1.111 fixed in v0.1.197. Phase 9 added 13 new P1 items (P1.135-P1.147). Highest priority (Phase 9 remaining): **P1.137 (equity transitional Rule 4.2/4.3 SA ladder — M, 2027-2029 capital overstatement for SA-only firms)**, **P1.140 (ADC classification flag-only — M, mis-tagging silently routes development loans to 75-100%)**, **P1.142 (Art. 124E three-property limit not automated — M)**, **P1.141 (Art. 124(4) mixed RE splitting — M)**. Remaining priority (prior phases): **P1.123 (FCCM HE for SFTs — M, capital understatement)**, **P1.122 (guarantee substitution no B31 branching — M, multiple incorrect RWs)**, **P1.130 (aggregator summaries pre-floor — S, reporting inconsistency)**, **P1.109 (guarantee maturity mismatch — M)**, **P1.124 (guarantee eligibility rejection — S)**, **P1.128 (SCRA trade finance <=6m — S)**, P1.93 (core market participant — M), P1.95 (guarantor SCRA — M, subsumed by P1.122), P1.96 (covered bond haircut — S, DOWNGRADED), P1.97 (B31 slotting subgrade — S), P1.98 (subordinated LGD floor — S), P1.99 (CRR short-term institution — S), P1.100 (ECA score — S), P1.101 (non-daily revaluation — S), P1.103 (Table 6A — S), P1.104 (FCSM maturity — S), P1.105 (Table 4A — S), P1.106 (FCSM institution UK — S), P1.107 (FCSM B31 corp CQS 3 — S), P1.108 (CRR retail 1.06 — S, DISPUTED), P1.110 (guarantee CQS table — S, subsumed by P1.122), P1.112 (PSE/RGLA sovereign — S), P1.114 (classifier null — S), P1.117 (HVCRE subgrades — S), P1.118 (Art. 162(3) maturity — M), P1.121 (CRR unrated inst short-term — S), P1.125 (FSE column warning — S), P1.126 (null revenue — S), P1.127 (Pool B composition — S, verification), P1.133 (short-term original maturity — S), P1.138 (equity Rule 4.6 IRB higher-of — M), P1.139 (equity Rule 4.8 CIU higher-of — M), P1.143 (Rule 4.11 unfunded CP grandfathering — M), P1.144 (EL fallback ead_final — S), P1.145 (classifier duplicate-permission non-determinism — S), P1.146 (is_guaranteed null drops rows — S), P1.147 (ValidationRequest model_permissions not required — S), P1.30(e) (tranching — L), P1.10 (transitional — M).

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

### P1.38 Output floor GCRA 1.25% cap and entity-type carve-outs (Art. 92)
- **Status:** [x] Complete ((a), (b), (c) all complete)
- **Fixed (a):** 2026-04-07 (implemented as part of P1.9a OF-ADJ)
- **Fixed (b):** 2026-04-07
- **Impact:** Three output floor gaps from PDF analysis:
  - **(a) GCRA cap:** FIXED. GCRA component of OF-ADJ is capped at **1.25% of S-TREA** (para 3A amounts, not U-TREA). Implemented in `compute_of_adj()` in `_floor.py` as part of the P1.9a OF-ADJ work. The cap is applied before GCRA enters the OF-ADJ formula.
  - **(b) Entity-type carve-outs:** FIXED. Art. 92 para 2A defines THREE entity categories where the floor formula applies: (i) stand-alone UK institution on individual basis, (ii) ring-fenced body in sub-consolidation group on sub-consolidated basis, (iii) non-international-subsidiary CRR consolidation entity on consolidated basis. All OTHER entities use U-TREA (no floor). Implementation:
    - `InstitutionType` enum (5 members) and `ReportingBasis` enum (3 members) added to `domain/enums.py`
    - `OutputFloorConfig` extended with `institution_type` and `reporting_basis` fields
    - `is_floor_applicable()` method encodes Art. 92 para 2A rules via frozen set of 3 applicable (institution_type, reporting_basis) pairs
    - Aggregator uses `is_floor_applicable()` instead of raw `enabled` check
    - `CalculationConfig.basel_3_1()` accepts and propagates `institution_type` and `reporting_basis` params
    - Backward compatible: when institution_type/reporting_basis are None, floor defaults to applicable
  - **(c) Reporting basis (Rule 2.2A):** FIXED (2026-04-08). Output floor reporting now conditioned on reporting basis per Art. 92 para 3A. Implementation:
    - **COREP generator** accepts `output_floor_config: OutputFloorConfig | None` on both `generate()` and `generate_from_lazyframe()`. Threaded to `_generate_c08_07`, `_generate_c_02_00`, and `_generate_of_02_01`.
    - **OF 02.00 rows 0034-0036** (floor activated/multiplier/OF-ADJ) gated on `is_floor_applicable()`. Exempt entities show 0.0 for all three indicators. Applicable entities preserve existing floor-detection logic.
    - **OF 02.01** (output floor comparison) returns `None` for exempt entities — per Art. 92 para 2A, entities outside the 3 applicable (institution_type, reporting_basis) combinations do not report floor comparison.
    - **C 08.07 materiality columns 0160-0180** explicitly documented as consolidated-basis-only (Art. 150(1A)). `is_consolidated` flag threaded to `_compute_c08_07_values()` for future population when institutional materiality data becomes available.
    - **COREPTemplateBundle** extended with `reporting_basis: str | None` and `institution_type: str | None` metadata fields so downstream consumers know the reporting basis.
    - **ResultExporterProtocol** and **ResultExporter** (`api/export.py`) extended with `output_floor_config` keyword-only parameter. Backward compatible: `None` preserves all existing behaviour.
    - **StubResultExporter** in contract tests updated.
- **File:Line:** `domain/enums.py` (InstitutionType, ReportingBasis), `contracts/config.py` (OutputFloorConfig.is_floor_applicable, CalculationConfig.basel_3_1), `engine/aggregator/aggregator.py` (is_floor_applicable check), `reporting/corep/generator.py` (output_floor_config threading, floor gating, materiality gating, bundle metadata), `contracts/protocols.py` (export_to_corep output_floor_config param), `api/export.py` (export_to_corep output_floor_config param)
- **Spec ref:** PRA PS1/26 Art. 92 para 2A(a)-(d), Art. 150(1A), Reporting (CRR) Part Rule 2.2A
- **Tests:** 50 existing tests in `tests/unit/test_output_floor_entity_type.py` (P1.38(a)/(b)). 38 new tests in `tests/unit/test_corep_reporting_basis.py` across 7 test classes: TestCOREPTemplateBundleMetadata (7), TestOF0201FloorApplicability (6), TestOF0200FloorIndicatorRows (7), TestC0807MaterialityColumns (4), TestBackwardCompatibility (3), TestEntityTypeCombinations (9 parametrized), TestExporterProtocolCompliance (2). All 5,125 tests pass (was 5,087). Contract tests: 145.
- **Fix remaining:** None — all sub-items (a), (b), (c) complete.

### P1.49 Art. 110A due diligence obligation (new SA requirement)
- **Status:** [x] Complete (2026-04-08)
- **Impact:** PRA PS1/26 Art. 110A introduces a new mandatory due diligence obligation for SA credit risk. Institutions must perform due diligence to ensure risk weights appropriately reflect the risk of the exposure.
- **Fix:** Implemented as a risk weight override mechanism with validation warnings:
  - **Schema:** Added `due_diligence_performed` (Boolean) and `due_diligence_override_rw` (Float64) to both LOAN_SCHEMA and CONTINGENTS_SCHEMA in `data/schemas.py`.
  - **SA calculator:** Added `_apply_due_diligence_override()` method to `engine/sa/calculator.py`. The override is applied as the final RW modification (after standard RW, CRM, currency mismatch, before RWA calculation). Uses `max(calculated_rw, override_rw)` — can only increase risk weight, never reduce it. Null override values are silently ignored. Audit column `due_diligence_override_applied` added when override column is present.
  - **Validation:** Under Basel 3.1, when `due_diligence_performed` column is absent, emits `CalculationError(code="SA004", severity=WARNING, category=DATA_QUALITY)` with regulatory reference to Art. 110A. No warning under CRR.
  - **Wiring:** Override method wired into all three SA calculation paths: `get_sa_result_bundle()` (with error collection), `calculate_unified()`, and `calculate_branch()`.
  - **Error code:** `ERROR_DUE_DILIGENCE_NOT_PERFORMED = "SA004"` added to `contracts/errors.py`.
- **File:Line:** `data/schemas.py` (LOAN_SCHEMA, CONTINGENTS_SCHEMA), `contracts/errors.py:197` (SA004), `engine/sa/calculator.py` (_apply_due_diligence_override)
- **Spec ref:** PRA PS1/26 Art. 110A, `docs/specifications/crr/sa-risk-weights.md` (updated with implementation details)
- **Tests:** 25 new tests in `tests/unit/test_due_diligence.py`: 7 override application tests (higher/lower/equal/null/mixed/absent column/CRR no-op), 5 audit column tests (true/false/null/CRR absent/column missing), 9 warning tests (absent B31/severity/category/regulatory ref/field name/CRR no warning/present no warning/None errors/once not per row), 4 edge cases (zero override/very high/with DD false/preserves columns). All 4,131 tests pass (was 4,106).

### P1.88 IRBCalculator.calculate_expected_loss silently defaults PD/LGD without warning
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `IRBCalculator.calculate_expected_loss()` (lines 170-173) silently defaulted PD to 0.01 (1%) and LGD to 0.45 (45%) when those columns were absent from IRB exposures. The method returned `errors=[]` — no indication that EL figures were based on placeholder values rather than actual model outputs or supervisory parameters. Follows the P6.10 pattern (IRB EL shortfall warnings).
- **Fix:** Now emits `CalculationError(code="IRB004", severity=WARNING, category=DATA_QUALITY)` when PD column is absent and `CalculationError(code="IRB005", severity=WARNING, category=DATA_QUALITY)` when LGD column is absent. Warnings include regulatory references (CRR Art. 160/161), field names, and actual default values. Error list propagated through `LazyFrameResult.errors`.
- **File:Line:** `engine/irb/calculator.py:149-215`
- **Spec ref:** CRR Art. 160 (PD), Art. 161 (LGD), Art. 158 (EL)
- **Tests:** 10 new tests in `tests/unit/test_irb_el_silent_defaults.py`: missing PD emits IRB004, missing LGD emits IRB005, both missing emits both, both present no warnings, PD default 0.01 used, LGD default 0.45 used, ead_final preferred, regulatory references present, actual values documented, Basel 3.1 config compatible. All 4,014 tests pass (was 4,004).

### P1.89 B31 private equity / venture capital risk weight 250% instead of 400%
- **Status:** [x] Complete (2026-04-08)
- **Impact:** **Capital understatement.** Under Basel 3.1 Art. 133(5), PE/VC is explicitly "higher-risk" equity requiring 400% RW. The calculator assigned 250% (the standard equity rate) because `_apply_b31_equity_weights_sa()` had no branch for `private_equity` or `private_equity_diversified` — both fell through to `.otherwise(pl.lit(2.50))`. This caused a **37.5% capital understatement** (250/400 = 62.5%) on all PE/VC equity exposures under Basel 3.1. The data table `B31_SA_EQUITY_RISK_WEIGHTS` was also wrong (Decimal("2.50") for both PE types). The `EquityType` enum docstrings documented "250% B31 SA" for both types. Pre-existing tests asserted 250% — all were wrong.
- **Fix:** Four changes:
  1. **Calculator** (`engine/equity/calculator.py`): Added two `private_equity` → 4.00 and `private_equity_diversified` → 4.00 branches in `_apply_b31_equity_weights_sa()`, placed after `is_speculative`/`speculative` checks (all are Art. 133(4)/(5) higher-risk). Updated `_apply_transitional_floor()` to classify PE/VC as higher-risk for correct transitional schedule selection (220%/280%/340%/400% vs 160%/190%/220%/250%).
  2. **Data table** (`data/tables/b31_equity_rw.py`): Changed `PRIVATE_EQUITY` and `PRIVATE_EQUITY_DIVERSIFIED` from `Decimal("2.50")` to `Decimal("4.00")`. Module docstring updated.
  3. **Enum** (`domain/enums.py`): Fixed `PRIVATE_EQUITY` and `PRIVATE_EQUITY_DIVERSIFIED` docstrings from "250% B31 SA" to "400% B31 SA (Art. 133(5))".
  4. **Tests:** Corrected pre-existing test expectations from 250% to 400%: `test_b31_equity_weights.py` (data table + calculator), `test_scenario_b31_l_equity.py` (B31-L8 acceptance). Added `test_b31_l8_rwa` acceptance test (400% × 150k = 600k).
- **File:Line:** `engine/equity/calculator.py:557-560` (PE branches), `engine/equity/calculator.py:660-665` (transitional is_hr), `data/tables/b31_equity_rw.py:43-44`, `domain/enums.py:456-460`
- **Spec ref:** PRA PS1/26 Art. 133(5), `docs/specifications/crr/equity-approach.md`
- **Tests:** All 5,145 tests pass (was 5,140). B31 acceptance: 216 (was 212).

### P1.90 B31 CIU fallback flat 250% instead of 250% listed / 400% unlisted
- **Status:** [x] Complete (2026-04-08)
- **Impact:** **Capital understatement for unlisted CIUs.** Under Basel 3.1, the CIU fallback weight aligns with the equity SA table (Art. 133): listed CIUs get 250% (standard equity, Art. 133(3)), unlisted CIUs get 400% (higher-risk, Art. 133(5)). The calculator applied a flat 250% for all CIU fallback regardless of listing status. The equity-approach spec documented "250% (listed) / 400% (unlisted)" but the code did not implement the split.
- **Fix:** Split the CIU fallback branch in `_apply_b31_equity_weights_sa()`:
  - Listed CIU (`is_exchange_traded == True`): 250% (Art. 132(2)/133(3))
  - Unlisted CIU (`is_exchange_traded == False/null`): 400% (Art. 132(2)/133(5))
  Uses existing `is_exchange_traded` Boolean field from EQUITY_EXPOSURE_SCHEMA (no schema change needed). CRR CIU fallback (150%) is unchanged.
- **File:Line:** `engine/equity/calculator.py:568-577` (CIU fallback split)
- **Spec ref:** PRA PS1/26 Art. 132(2), Art. 133(3)/(5), `docs/specifications/crr/equity-approach.md`
- **Tests:** Corrected pre-existing CIU tests: `test_b31_equity_weights.py` (split into `test_ciu_fallback_unlisted_400_percent` + `test_ciu_fallback_listed_250_percent`), B31-L17 acceptance (split into unlisted/listed tests), B31-L23 regression contrast (split into unlisted/listed CIU vs CRR). All 5,145 tests pass.

### P1.91 Art. 123A Basel 3.1 retail qualifying criteria not enforced
- **Status:** [x] Complete (2026-04-08)
- **Impact:** **Capital understatement.** Under Basel 3.1, Art. 123A defines two-path qualifying criteria for retail classification. Previously, `qualifies_as_retail` in `classifier.py` only checked the lending group threshold (condition 2). Two gaps: (1) Art. 123A(1)(a) SME auto-qualification was implicit (threshold-only) with no explicit bypass — fragile against future changes. (2) Art. 123A(1)(b)(iii) pool management condition was not enforced — non-SME natural person exposures with `cp_is_managed_as_retail=False` incorrectly received 75% retail RW instead of 100% corporate RW.
- **Fix:** Three changes:
  1. **Classifier Phase 2** (`engine/classifier.py`): `_build_qualifies_as_retail_expr()` method replaces inline expression. Under Basel 3.1: (a) threshold check first; (b) SME entities (revenue > 0 and < GBP 44m) auto-qualify per Art. 123A(1)(a); (c) non-SME entities must have `cp_is_managed_as_retail=True` per Art. 123A(1)(b)(iii); null defaults to True for backward compatibility. CRR behavior unchanged (threshold only).
  2. **Classifier Phase 1** (`engine/classifier.py`): `is_managed_as_retail` propagation made optional (was unconditionally required). When absent from counterparty data, `cp_is_managed_as_retail` column added as null. Warning `CLS005` emitted under Basel 3.1 when the field is absent.
  3. **Error code** (`contracts/errors.py`): Added `ERROR_RETAIL_POOL_MGMT_MISSING = "CLS005"`.
- **File:Line:** `engine/classifier.py` (_build_qualifies_as_retail_expr, _add_counterparty_attributes, classify), `contracts/errors.py:177` (CLS005)
- **Spec ref:** PRA PS1/26 Art. 123A(1)(a)-(b), `docs/specifications/common/hierarchy-classification.md`
- **Tests:** 22 new tests in `tests/unit/test_art123a_retail_criteria.py` across 5 test classes: TestCondition3PoolManagement (4: not-managed fails/managed passes/null defaults/reclassified to corporate), TestSMEAutoQualification (5: SME bypasses condition 3/null/near threshold/non-SME fails/zero revenue), TestCRRUnchanged (2: CRR ignores condition 3), TestPoolManagementWarning (6: column absent/severity/category/reference/present no warning/CRR no warning), TestThresholdAndCondition3Interaction (3: above threshold/below with/below without), TestRiskWeightImpact (2: qualifying 75%/non-qualifying corporate). All 5,167 tests pass (was 5,145). Contract tests: 145.

### P1.92 FCSM Art. 222(4) 0% exception incorrectly floored to 20%
- **Status:** [x] **FIXED v0.1.194**
- **Impact (pre-fix):** Capital overstatement for FCSM cash-collateralised exposures. Art. 222(1) provides a 20% risk weight floor for FCSM-protected exposures "except as specified in paragraphs 4 to 6". The per-item logic in `compute_fcsm_columns()` correctly gave 0% for Art. 222(4)(a) same-currency cash and Art. 222(4)(b) 0%-RW sovereign bonds, but `_apply_fcsm_rw_substitution()` re-imposed a 20% floor on the weighted-average collateralised RW, bumping pure-carve-out portfolios back to 20%.
- **File:Line:** `engine/crm/simple_method.py` (step 6 now applies per-item floor with carve-out bypass); `engine/sa/calculator.py:_apply_fcsm_rw_substitution` (aggregate floor removed).
- **Spec ref:** CRR Art. 222(1)/(4); PRA PS1/26 Art. 222(3)/(6)
- **Resolution:** Relocated the 20% floor from the aggregate blend to per-item application inside `compute_fcsm_columns()`, using `_is_zero_rw_exception_expr()` to bypass the floor for carve-out items. `_apply_fcsm_rw_substitution()` now consumes the already-floored per-item RW without re-flooring.
- **Tests:** `tests/unit/crm/test_simple_method.py` — pure same-currency cash → 0%; cross-currency cash → 20% floor; mixed carve-out + low-RW bond regression; end-to-end regression through SA substitution; simple-vs-comprehensive convergence for same-currency cash.

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
- **Status:** [ ] Not started (2026-04-08)
- **Impact:** CRR Art. 120(1)-(2) provides lower risk weights for short-term (<= 3 months residual maturity) institution exposures denominated in domestic currency: CQS 1 = 20% (vs 20% long-term — no change), CQS 2 = 20% (vs 30% UK deviation), CQS 3 = 20% (vs 50%). The CRR code path in SA calculator has no short-term institution treatment — all institution exposures use the long-term Table 3 weights. The B31 ECRA path correctly handles short-term via `B31_ECRA_SHORT_TERM_RISK_WEIGHTS`, but the CRR path lacks an equivalent.
- **File:Line:** `engine/sa/calculator.py` (CRR `_apply_risk_weights` institution branch)
- **Spec ref:** CRR Art. 120(1)-(2), Table 4
- **Fix:** Add a `.when()` branch for CRR institutions checking `is_short_term_institution` (or `residual_maturity_months <= 3 AND currency == domestic`). Apply Table 4 short-term weights. Requires schema field for residual maturity or a pre-computed short-term flag.
- **Tests needed:** Unit tests for CQS 2/3 short-term CRR institution exposures.

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

### P1.106 FCSM collateral RW for institution bonds ignores UK deviation
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 5)
- **Impact:** **Conservative capital overstatement.** `_derive_collateral_rw_expr()` in `engine/crm/simple_method.py:90-91` maps institution bonds CQS 2-3 to 50% risk weight. Under CRR Art. 119 with the UK deviation, CQS 2 institutions get 30% (not 50%). The function takes `is_basel_3_1: bool` but has no `use_uk_deviation` parameter. Impact: the secured portion of FCSM-protected exposures backed by CQS 2 institution bonds gets RW = max(50%, 20%) = 50% instead of the correct max(30%, 20%) = 30%. This overstates capital by 20 percentage points on the secured portion. Under B31, this is moot (ECRA/SCRA replaces the CQS table). Narrow scope: only affects firms using FCSM (Art. 222) with CQS 2 institution bonds under CRR.
- **File:Line:** `engine/crm/simple_method.py:90-91` (institution CQS 2-3 both mapped to 50%)
- **Spec ref:** CRR Art. 119, UK CRR deviation (Art. 119(1) Table 3 UK-specific column)
- **Fix:** Add `use_uk_deviation: bool = True` parameter to `_derive_collateral_rw_expr()`. When True and `is_basel_3_1=False`, map CQS 2 institutions to 30%. Thread from `compute_fcsm_columns()` which has access to `config`.
- **Tests needed:** Unit tests for FCSM collateral RW with UK deviation institution bonds.

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

### P1.115 CRR Art. 230 subordinated F-IRB LGDS missing for collateralised exposures
- **Status:** [x] FIXED v0.1.191 (2026-04-11)
- **Impact:** **Capital understatement for CRR subordinated collateralised F-IRB exposures.** CRR PDF extraction (p.228) confirms UK-onshored CRR Art. 230 Table 5 retains subordinated LGDS: receivables 65%, RE 65%, other physical 70%. The code's `firb_lgd.py` DataFrame (lines 113-191) has collateral-specific LGD rows for `seniority="senior"` only — no subordinated rows. `lookup_firb_lgd()` returns 75% (unsecured subordinated LGDU) for all subordinated regardless of collateral, but Table 5 subordinated LGDS (65%/65%/70%) are lower than LGDU (75%) for collateralised portions. PRA PS1/26 Art. 230 has **no subordinated LGDS** — code is correct for B31. This is CRR-only.
- **File:Line:** `data/tables/firb_lgd.py:113-191` (DataFrame missing subordinated rows), `:25-40` (dict missing subordinated collateral entries)
- **Spec ref:** CRR Art. 230 Table 5 (confirmed from PDF p.228); PRA PS1/26 Art. 230 (no subordinated — correct)
- **Fix:** Add subordinated rows to the CRR F-IRB LGD DataFrame and dict: `receivables_subordinated: 0.65`, `residential_re_subordinated: 0.65`, `commercial_re_subordinated: 0.65`, `other_physical_subordinated: 0.70`. Update `lookup_firb_lgd()` to use collateral-specific subordinated LGDS when both `is_subordinated=True` and collateral is present.
- **Tests needed:** Unit tests for CRR subordinated collateralised LGD lookup at each collateral type; acceptance test for CRR F-IRB subordinated exposure with RE collateral (expect 65% not 75%).

### P1.116 EL shortfall deduction corrected from 50/50 CET1/T2 to 100% CET1
- **Status:** [x] **FIXED v0.1.185** (2026-04-11)
- **Impact:** `_el_summary.py:239-241` previously applied `effective_shortfall * 0.5` to both `cet1_deduction` and `t2_deduction`. CRR Art. 36(1)(d) requires the full EL shortfall (EL > provisions) to be deducted from CET1. The 50/50 split was an older Basel II treatment; current CRR requires 100% CET1 deduction. This directly affects the OF-ADJ calculation which uses `el_summary.cet1_deduction` — understating the CET1 deduction by 50% means OF-ADJ is too favourable. Also corrected OF-ADJ cascading impact (CET1 deduction doubled, making floor threshold more conservative).
- **File:Line:** `engine/aggregator/_el_summary.py:239-241`
- **Spec ref:** CRR Art. 36(1)(d), Art. 159
- **Fix:** Change `cet1_deduction = effective_shortfall * 1.0` (full amount to CET1) and `t2_deduction = Decimal("0")` (no T2 deduction). Review downstream consumers of `t2_deduction` field for any impact.
- **Tests needed:** Unit tests for EL shortfall deduction split; integration test verifying OF-ADJ computation with corrected CET1 deduction.

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

### P1.119 CIU fallback risk weight wrong under BOTH frameworks
- **Status:** [x] **FIXED in v0.1.184** (2026-04-11)
- **Impact:** Was severe capital understatement (3-8x). Now corrected.
- **What changed:** CIU fallback RW corrected from 150% (CRR) / 250%-400% (B31) to 1,250% per Art. 132(2). Extracted `CIU_FALLBACK_RW = 12.50` constant and `_append_ciu_branches()` shared helper to eliminate CRR/B31 CIU code duplication. Updated both data tables (`crr_equity_rw.py`, `b31_equity_rw.py`), calculator (`equity/calculator.py`), and `_resolve_look_through_rw()`. Updated 27 unit tests, 7 acceptance tests, and both equity spec docs.
- **Files changed:** `data/tables/crr_equity_rw.py`, `data/tables/b31_equity_rw.py`, `engine/equity/calculator.py`, `tests/unit/test_ciu_treatment.py`, `tests/unit/crr/test_crr_equity.py`, `tests/unit/test_b31_equity_weights.py`, `tests/acceptance/crr/test_scenario_crr_j_equity.py`, `tests/acceptance/basel31/test_scenario_b31_l_equity.py`, `docs/specifications/crr/equity-approach.md`, `docs/specifications/basel31/equity-approach.md`

### P1.120 B31 SA defaulted provision-ratio denominator wrong (D3.19)
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 6)
- **Impact:** **Capital overstatement for collateralised defaulted exposures.** Art. 127(1) requires `specific_provisions / gross_outstanding_amount` but code uses `unsecured_ead` (post-provision, post-CRM). For partially collateralised exposures, the smaller denominator can push the ratio below 20%, inflating RW from 100% to 150%.
- **File:Line:** `engine/sa/calculator.py:1250-1275` (defaulted provision ratio calculation)
- **Spec ref:** PRA PS1/26 Art. 127(1), `docs/specifications/basel31/defaulted-exposures.md` D3.19
- **Fix:** Replace `unsecured_ead` with `gross_outstanding_amount` in the provision ratio denominator. Add `gross_outstanding_amount` field to schema if not already present, or derive from existing fields (`drawn + interest + nominal`).
- **Tests needed:** Unit tests for provision ratio with partially collateralised defaulted exposures; acceptance test confirming correct 100% vs 150% boundary at 20% provision ratio.

### P1.121 CRR Art. 121(3) unrated institution short-term 20% not applied
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 7)
- **Impact:** **Capital overstatement by up to 100%.** CRR Art. 121(3) gives unrated institutions with residual maturity <= 3 months denominated in domestic currency a 20% RW. Code has no short-term handling for unrated institutions under CRR — falls through to 40% (UK deviation) or 100% (standard).
- **File:Line:** `engine/sa/calculator.py` (CRR institution risk weight assignment — no short-term branch for unrated)
- **Spec ref:** CRR Art. 121(3)
- **Fix:** Add a short-term branch in the CRR institution RW logic: when `is_unrated AND residual_maturity_years <= 0.25 AND is_domestic_currency`, assign 20%.
- **Tests needed:** Unit tests for CRR unrated institution short-term 20%; acceptance test contrasting short vs long maturity unrated institution exposures.

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
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 8 cross-audit)
- **Impact:** **Silently discards computed floor summary.** `pipeline.py:274-289` reconstructs `AggregatedResultBundle` to append errors but omits `output_floor_summary=result.output_floor_summary`. Defaults to `None`, silently discarding the computed floor summary when any non-critical pipeline errors exist. Affects COREP OF 02.00 reporting.
- **File:Line:** `engine/pipeline.py:274-289` (bundle reconstruction missing `output_floor_summary`)
- **Spec ref:** PRA PS1/26 Art. 92(2A)
- **Fix:** Add `output_floor_summary=result.output_floor_summary` to the `AggregatedResultBundle` reconstruction at line 274-289. Also verify all other fields are propagated (check for any other omissions in the reconstruction).
- **Tests needed:** Unit test confirming `output_floor_summary` survives pipeline error accumulation; integration test with floor-applicable config + pipeline warnings verifying floor summary present in final bundle.

### P1.132 B31 government-supported/legislative equity applies 100% instead of 250%
- **Status:** [ ] Not started (2026-04-10 — identified in Phase 8 PDF cross-audit)
- **Impact:** **Capital understatement for government-supported equity under B31 (100% vs 250%).** `b31_equity_rw.py:44` sets `EquityType.GOVERNMENT_SUPPORTED: Decimal("1.00")`. CRR Art. 133(3)(c) provided a 100% RW for equity held under legislative programmes, but PRA PS1/26 Art. 133 removes this category entirely. B31 Art. 133(3) assigns 250% to all standard equity; Art. 133(4) assigns 400% to higher-risk. Art. 133(6) is an exclusion clause listing items treated elsewhere (own-funds deductions, 1,250% items, threshold deduction 250% items) — not a 100% weight. Government-supported equity that isn't excluded under Art. 133(6) should receive 250%.
- **File:Line:** `data/tables/b31_equity_rw.py:44` (dict entry), `engine/equity/calculator.py` (if separate branch exists)
- **Spec ref:** PRA PS1/26 Art. 133(3)/(6)
- **Fix:** Change `GOVERNMENT_SUPPORTED: Decimal("1.00")` to `Decimal("2.50")` in `B31_SA_EQUITY_RISK_WEIGHTS`. Also verify the central bank 0% (line 40) references the correct article — Art. 133(6) is not a 0% weight provision. Update docstring at line 12 ("Legislative programme equity = 100%" → removed under B31).
- **Tests needed:** Unit test confirming B31 government-supported equity gets 250%; acceptance test for B31-L equity scenario with government-supported type.

### P1.135 FX haircut on collateral silently zero after FX conversion
- **Status:** [x] FIXED v0.1.63 (2026-04-18). Bundled with P1.136 as they share a root cause.
- **Impact when fixed:** **HIGH capital understatement avoided.** Before the fix, `FXConverter.convert_collateral()` and `convert_exposures()` both rewrote `currency` to the reporting currency before the haircut calculator ran. `engine/crm/haircuts.py` compared `currency != exposure_currency` which was always false post-conversion, so Art. 224 8% H_fx was never applied to FX-mismatched secured exposures.
- **Files touched:** `engine/fx_converter.py` (4 methods now preserve `original_currency` on both branches), `engine/hierarchy.py` (removed the branching path — converters handle the no-conversion case uniformly), `engine/crm/processor.py::_build_exposure_lookups` (exposure-side currency sourced from `original_currency` with fallback), `engine/crm/haircuts.py::apply_haircuts` (compares collateral `original_currency` with fallback).
- **Spec ref:** CRR Art. 224, PRA PS1/26 Art. 224
- **Tests added:** `tests/unit/crm/test_collateral_fx_mismatch.py` — 5 tests covering post-conversion H_fx firing, fallback to plain `currency`, and the processor lookup's pre-conversion currency propagation. `tests/unit/test_fx_converter.py` — 2 tests for `convert_collateral` preserving `original_currency` (both enabled and disabled paths). 5294 tests pass.

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

### P2.3 COREP C 09.01-09.02 (Geographical Breakdown)
- **Status:** [x] Complete (2026-04-08)
- **Impact:** COREP geographical breakdown templates were entirely missing. C 09.01 (SA) and C 09.02 (IRB) provide per-country exposure breakdowns by exposure class — a standard regulatory reporting requirement.
- **Implementation:**
  - **No schema change needed:** The `country_code` field already exists on COUNTERPARTY_SCHEMA and flows through the classifier as `cp_country_code` to results.
  - **C 09.01 / OF 09.01 (SA Geographical Breakdown):** One DataFrame per country code + TOTAL. CRR: 13 columns (0010-0090 incl. supporting factors 0080-0082), 23 rows (SA exposure classes). Basel 3.1: 10 columns (removes 3 supporting factor columns), 29 rows (adds SL sub-rows 0071-0073, RE sub-rows 0091-0094, removes short-term row 0130, renames equity/RE rows). Template definitions: `CRR_C09_01_COLUMNS`/`B31_C09_01_COLUMNS`, `CRR_C09_01_ROWS`/`B31_C09_01_ROWS`, `C09_01_COLUMN_REFS`/`B31_C09_01_COLUMN_REFS`, `C09_01_SA_CLASS_MAP`, `get_c09_01_columns()`, `get_c09_01_rows()`. Generator methods: `_generate_all_c09_01()` and `_generate_c09_01_for_country()` with `_filter_c09_01_row()` and `_compute_c09_01_values()` helpers.
  - **C 09.02 / OF 09.02 (IRB Geographical Breakdown):** One DataFrame per country code + TOTAL. CRR: 17 columns (incl. PD, LGD, EL, supporting factors), 16 rows (IRB classes incl. equity). Basel 3.1: 15 columns (adds 0107 defaulted EV, removes 3 supporting factor columns), 19 rows (adds corporate sub-rows 0048/0049/0055, restructures retail RE to 4 sub-rows 0071-0074, removes equity). Template definitions: `CRR_C09_02_COLUMNS`/`B31_C09_02_COLUMNS`, `CRR_C09_02_ROWS`/`B31_C09_02_ROWS`, `C09_02_COLUMN_REFS`/`B31_C09_02_COLUMN_REFS`, `C09_02_IRB_CLASS_MAP`, `get_c09_02_columns()`, `get_c09_02_rows()`. Generator methods: `_generate_all_c09_02()` and `_generate_c09_02_for_country()` with `_filter_c09_02_row()` and `_compute_c09_02_values()` helpers.
  - **Bundle:** `COREPTemplateBundle.c09_01` and `.c09_02` fields (both `dict[str, pl.DataFrame]`, keyed by country code). Excel export via per-country sheets with framework-aware prefix (C 09.01/C 09.02 for CRR, OF 09.01/OF 09.02 for B31).
  - **Known gaps:** Temporal columns (0040 new defaults, 0060 write-offs, 0061 AVAs, 0070 new default adjustments) are null — require multi-period data. Supporting factor adjustment columns (0081/0082 for C 09.01; 0121/0122 for C 09.02) are null. B31 sub-rows requiring pipeline data not yet available (SL sub-types, RE sub-types, purchased receivables) return null.
- **File:Line:** `reporting/corep/templates.py` (CRR/B31 column/row definitions, class maps, selectors), `reporting/corep/generator.py` (_generate_all_c09_01, _generate_all_c09_02, _compute_c09_01_values, _compute_c09_02_values, _filter_c09_01_row, _filter_c09_02_row), `reporting/corep/__init__.py` (exports)
- **Spec ref:** Regulation (EU) 2021/451 Annex I/II (C 09.01, C 09.02), PRA PS1/26 Annex I/II (OF 09.01, OF 09.02), `docs/features/corep-reporting.md`
- **Tests:** 80 new tests in `tests/unit/test_corep.py` across 10 test classes: TestC0901TemplateDefinitions (17), TestC0901Generation (8), TestC0901ColumnValues (8), TestC0901B31Features (3), TestC0901EdgeCases (6), TestC0902TemplateDefinitions (16), TestC0902Generation (6), TestC0902ColumnValues (8), TestC0902B31Features (3), TestC0902EdgeCases (5). All 4,953 tests pass. COREP tests: 635 (was 555).

### P2.4 COREP C 08.01 Section 3 "Calculation Approaches"
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Section 3 was entirely null. Now populates rows from pipeline approach data:
  - **Row 0070** (obligor grades/pools): Filters `approach_applied IN ("foundation_irb", "advanced_irb")` — all PD/LGD model-based exposures. Computes full C 08.01 column set via `_compute_c08_values()`.
  - **Row 0080** (slotting): Filters `approach_applied == "slotting"`. Same column computation.
  - **Row 0160** (alternative RE treatment, CRR only): Remains null — requires pipeline flag for Art. 124-126 alternative treatment not yet available.
  - **Row 0170** (free deliveries): Remains null — requires free delivery identification not yet in pipeline.
  - **Row 0175** (purchased receivables, B31 only): Remains null — requires purchased receivable tracking.
  - **Row 0180** (dilution risk): Remains null — requires dilution risk tracking.
  - **Row 0190** (corporates without ECAI, B31 only): Filters `exposure_class CONTAINS "corporate" AND sa_cqs IS NULL`. Falls back to all corporates when `sa_cqs` absent.
  - **Row 0200** (investment grade, B31 only): Subset of 0190 filtered by `cp_is_investment_grade` or PD ≤ 0.5% proxy.
  Key property: row 0070 EAD + row 0080 EAD = total row 0010 EAD (verified by tests).
- **File:Line:** `reporting/corep/generator.py:536-548` (Section 3 loop), `generator.py:903-1002` (`_filter_section3_row` helper)
- **Spec ref:** CRR Art. 142-191 (IRB approach assignment), PRA PS1/26 Art. 122D (investment grade), `docs/features/corep-reporting.md`
- **Tests:** 27 new tests in `tests/unit/test_corep.py::TestSection3CalculationApproaches`: 6 row 0070 tests (EAD/RWEA/PD/obligor count/institution class/excludes slotting), 4 row 0080 tests (EAD/RWEA/SL class/null when no slotting), 2 additive integrity tests (EAD/RWEA sum to total), 3 null-row tests (0160/0170/0180 remain null), 3 B31 row 0190 tests (unrated EAD/excludes rated/not in CRR), 3 B31 row 0200 tests (investment grade/subset of 0190/not in CRR), 6 edge cases (basic data/no slotting/provisions/0175 in B31/0160 in CRR/row 0070 matches total). All 4,264 tests pass (was 4,237). COREP tests: 277 (was 250).

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

### P2.8 COREP C 07.00 / OF 07.00 memorandum rows and supporting factor rows
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Six previously-null rows in the primary SA credit risk COREP template are now populated from pipeline data, plus the CRR RWEA supporting factor columns (0216/0217) now work with pipeline-available column names.
- **Implementation:**
  - **Row 0300** (CRR + B31): "Exposures in default subject to RW of 100%" — filters defaulted exposures via `_filter_defaulted()` then by `risk_weight ≈ 1.00` (4-decimal rounding for float tolerance).
  - **Row 0320** (CRR + B31): "Exposures in default subject to RW of 150%" — same pattern, `risk_weight ≈ 1.50`.
  - **Row 0290** (CRR only): "Exposures secured by mortgages on commercial immovable property" — filters by `property_type == "commercial"`.
  - **Row 0310** (CRR only): "Exposures secured by mortgages on residential immovable property" — filters by `property_type == "residential"`.
  - **Row 0030** (CRR only): "of which: Exposures subject to SME-supporting factor" — filters by `is_sme == True AND supporting_factor_applied == True`.
  - **Row 0035** (CRR only): "of which: Exposures subject to infrastructure supporting factor" — filters by `is_infrastructure == True AND supporting_factor_applied == True`.
  - **RWEA col 0216** (CRR C 07.00 + C 08.01): SME factor adjustment now falls back to `is_sme + supporting_factor_applied + rwa_pre_factor` when legacy `sme_supporting_factor_applied` column absent.
  - **RWEA col 0217** (CRR C 07.00 + C 08.01): Infrastructure factor adjustment now falls back to `is_infrastructure + supporting_factor_applied + rwa_pre_factor`.
  - **RWEA col 0215** (CRR C 07.00): Pre-factor RWEA now also tries `rwa_pre_factor` (pipeline name) in addition to `rwa_before_sme_factor` (legacy name).
  - **New helper functions:** `_filter_defaulted_at_rw()`, `_filter_re_secured()`, `_filter_supporting_factor()` in `generator.py`.
- **File:Line:** `reporting/corep/generator.py` (Section 1 rows 0030/0035 handling, Section 5 memorandum rows 0290/0300/0310/0320 handling, RWEA columns 0215-0217 fallback logic, 3 new helper functions)
- **Spec ref:** CRR Art. 127 (defaulted RW), Art. 124-126 (immovable property), Art. 501/501a (supporting factors)
- **Tests:** 28 new tests in `tests/unit/test_corep.py` across 3 test classes: TestC0700MemorandumRows (14 tests: defaulted at RW 100%/150%, CRR commercial/residential RE, B31 rows present/populated, null when no defaults, float precision, column completeness), TestC0700SupportingFactorRows (8 tests: SME/infrastructure filter, exclusion, null fallback, B31 absent, missing column handling, original exposure), TestC0700SupportingFactorRWEA (7 tests: pre-factor from pipeline, SME/infra adjustments, post-factor total, arithmetic identity, null without columns, B31 absent). All 4,981 tests pass (was 4,953). COREP tests: 663 (was 635).
- **File:Line:** `reporting/corep/generator.py:411`
- **Fix:** Implement memorandum item aggregation.

### P2.9 COREP OF 34.07 missing (IRB CCR exposures by exposure class and PD scale)
- **Status:** [ ] Not started
- **Impact:** OF 34.07 is a Basel 3.1 COREP template for IRB CCR. 7 columns: col 0010 exposure value, col 0020 EWA PD (post-floor), col 0030 number of obligors, col 0040 EWA LGD, col 0050 EWA maturity (years), col 0060 RWEA, col 0070 density of RWEA (col 0060/col 0010). Scope: any firm using F-IRB or A-IRB for CCR regardless of CCR valuation method (SA-CCR, IMM, etc.). Excludes CCP-cleared exposures. While CCR is generally out of scope (noted in P2.6), this template should at minimum be documented as a known gap. **Now documented in spec.**
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 COREP reporting framework
- **Fix:** Add OF 34.07 to COREP template inventory in `docs/features/corep-reporting.md`. Document as out-of-scope (CCR dependency) or add placeholder template definition.
- **Tests needed:** None until CCR is implemented.

### P2.10 ResultExporterProtocol missing export_to_corep method
- **Status:** [x] Complete (2026-04-08)
- **Impact:** The `ResultExporterProtocol` in `contracts/protocols.py` did not include an `export_to_corep()` method. The COREP generator existed (`reporting/corep/generator.py`) but was not integrated into the protocol-driven pipeline. Any code calling the exporter protocol could not produce COREP output without bypassing the protocol.
- **Fix:** Added `export_to_corep(response, output_path) -> ExportResult` method to `ResultExporterProtocol` with full docstring referencing CRR Art. 99 and PRA PS1/26. Updated protocol class docstring to mention COREP regulatory submissions. The concrete `ResultExporter` in `api/export.py` already implemented this method, so only the protocol definition was missing.
  - `StubResultExporter` added to `tests/contracts/test_protocols.py` with all 4 export methods
  - 9 new contract tests: protocol satisfaction, isinstance checks, 4 return type tests, negative test (incomplete exporter fails isinstance), concrete exporter compliance test
- **File:Line:** `contracts/protocols.py:700-727` (protocol method), `tests/contracts/test_protocols.py` (StubResultExporter + 9 tests)
- **Spec ref:** Project architecture (protocol-driven pipeline), CRR Art. 99 (COREP reporting obligation)
- **Tests:** Contract tests: 144 (was 135). All 4,237 tests pass (was 4,228).

### P2.11 COREP backward-compatibility aliases are dead code
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Investigation found `C07_COLUMNS` and `C08_01_COLUMNS` are NOT dead — they are imported in `__init__.py`, re-exported via `__all__`, and used in `tests/unit/test_corep.py` (lines 429, 435). Only `C08_02_COLUMNS` at `templates.py:689` was truly dead (never imported outside templates.py).
- **Fix:** Removed dead `C08_02_COLUMNS` alias. Left `C07_COLUMNS` and `C08_01_COLUMNS` as live code.
- **File:Line:** `reporting/corep/templates.py:688-689` (removed)

### P2.12 C 07.00 / OF 07.00 missing col 0020 "Exposures deducted from own funds"
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** Standard EBA/PRA column between 0010 (Original exposure) and 0030 (Value adjustments) is absent from both CRR C 07.00 and B31 OF 07.00 template definitions. Template submission validation tools will flag the missing column.
- **File:Line:** `reporting/corep/templates.py` (C07 column definitions)
- **Spec ref:** PRA COREP reporting framework C 07.00 / OF 07.00
- **Fix:** Add column 0020 to CRR_C07_COLUMNS and B31_C07_COLUMNS. The value is the amount of exposures deducted from own funds per Art. 36/48/49 — may be zero for most rows or require config input.
- **Tests needed:** Template definition tests for column count and ordering.

---

## Priority 3 -- Pillar III Disclosures

### P3.1 Pillar III disclosure code
- **Status:** [x] Complete (2026-04-08)
- **Impact:** All 9 disclosure templates implemented: OV1, CR4, CR5, CR6, CR6-A, CR7, CR7-A, CR8, CR10. Full CRR (UK prefix) and Basel 3.1 (UKB prefix) framework switching via selector functions.
- **Implementation:**
  - **Package:** `src/rwa_calc/reporting/pillar3/` — three-layer architecture mirroring COREP pattern: `templates.py` (column/row definitions, framework selectors), `generator.py` (Pillar3Generator, Pillar3TemplateBundle), `__init__.py` (public exports).
  - **Templates:** `templates.py` defines P3Column/P3Row frozen dataclasses, SA_DISCLOSURE_CLASSES (16 Art. 112 mappings), IRB_EXPOSURE_CLASSES (8 mappings), CR6_PD_RANGES (17 fixed buckets), CR10_SLOTTING_ROWS (6), plus all CRR/B31 column/row variants. 13 framework selector functions (`get_ov1_rows`, `get_cr4_columns`, `get_cr5_columns`, etc.).
  - **Generator:** Stateless `Pillar3Generator` class with `generate(response)` → `Pillar3TemplateBundle` and `generate_from_lazyframe(results, *, framework)` for direct LazyFrame input. `export_to_excel(bundle, output_path)` → `ExportResult`. Templates: OV1 (RWA by approach + 8% own funds), CR4 (SA exposure class breakdown), CR5 (risk weight bucket allocation), CR6 (per-IRB-class PD range breakdown), CR6-A (IRB/SA scope split), CR7 (pre/post credit derivative RWEA), CR7-A (per-approach CRM coverage), CR8 (flow statement), CR10 (per-SL-type slotting breakdown).
  - **Integration:** `ResultExporterProtocol.export_to_pillar3()` added to protocols.py. `ResultExporter.export_to_pillar3()` wired in `api/export.py`. `reporting/__init__.py` updated with Pillar3 exports.
  - **Known approximations:** CR7 pre-credit-derivative RWEA approximated as equal to post-CD (pipeline doesn't track pre-CRM RWA separately). CR8 flow statement only populates closing balance (historical data not available from single pipeline run).
- **Spec ref:** `docs/specifications/output-reporting.md`, `docs/features/pillar3-disclosures.md`, CRR Part 8 Art. 438, 444, 452, 453
- **Tests:** 106 new tests in `tests/unit/test_pillar3.py` across 14 test classes: TestTemplateDefinitions (38), TestFrameworkSelectors (13), TestPillar3Bundle (2), TestOV1Generation (7), TestCR4Generation (7), TestCR5Generation (6), TestCR6Generation (8), TestCR6AGeneration (4), TestCR7Generation (4), TestCR7AGeneration (4), TestCR8Generation (4), TestCR10Generation (6), TestGeneratorEndToEnd (5), TestExcelExport (2). Contract tests updated (StubResultExporter, protocol compliance). All 4,640 tests pass.

### P3.2 UKB CR9 / CR9.1 (PD back-testing)
- **Status:** [x] Complete (2026-04-08)
- **Impact:** PRA PS1/26 Annex XXII defines **UKB CR9** (mandatory PD back-testing per exposure class, Art. 452(h)) and **UKB CR9.1** (supplementary ECAI mapping back-testing, Art. 180(1)(f)). Both are Basel 3.1 only (no CRR equivalent). CR9 is the Pillar III counterpart of COREP template OF 08.05.
- **Implementation:**
  - **Templates (`reporting/pillar3/templates.py`):** `CR9_COLUMNS` (8 columns: a-h), `CR9_COLUMN_REFS`, `CR9_AIRB_CLASSES` (6 AIRB exposure class definitions), `CR9_FIRB_CLASSES` (4 FIRB exposure class definitions), `CR9_APPROACH_DISPLAY` (approach display names for Excel), `CR9_1_COLUMNS` (8 base columns for future ECAI extension), `CR9_1_COLUMN_REFS`. Reuses `CR6_PD_RANGES` (17 fixed PD range buckets).
  - **Generator (`reporting/pillar3/generator.py`):** `_generate_all_cr9()` and `_generate_cr9_for_class()` methods. Separate DataFrames per approach-class combination, keyed as `"{approach} - {class_key}"` (e.g., `"foundation_irb - corporate"`). Returns empty dict under CRR. `_compute_cr9_values()` helper computes all 8 columns: obligor counting via `counterparty_reference.n_unique()`, default detection via `is_defaulted` with PD >= 1.0 fallback, observed default rate, EAD-weighted average PD (post-floor), arithmetic average PD (obligor-weighted), historical annual default rate with current-period fallback.
  - **Bundle:** `Pillar3TemplateBundle.cr9: dict[str, pl.DataFrame]` field added. Excel export via `_write_dict_sheets()` with `_cr9_display_names()` helper for human-readable sheet names.
  - **PD allocation:** Uses `irb_pd_original` (pre-input-floor model PD) as closest proxy for beginning-of-period PD. Reported PD (cols f, g) uses `irb_pd_floored` (post-floor).
  - **CR9.1:** Template definitions in place. Generation returns no data until pipeline provides ECAI mapping data (firm-defined PD ranges and ECAI rating scale mappings). Documented as known gap.
  - **Known approximations:** Beginning-of-period PD approximated by `irb_pd_original`. Historical annual default rate (col h) falls back to current-period observed rate when `historical_annual_default_rate` column is absent. Prior-year obligor count (col c) falls back to current-period count when `prior_year_obligor_count` column is absent.
- **File:Line:** `reporting/pillar3/templates.py` (CR9_COLUMNS, CR9_AIRB_CLASSES, CR9_FIRB_CLASSES, CR9_1_COLUMNS), `reporting/pillar3/generator.py` (_generate_all_cr9, _generate_cr9_for_class, _compute_cr9_values, _cr9_display_names, Pillar3TemplateBundle.cr9)
- **Spec ref:** PRA PS1/26 Art. 452(h), Annex XXII paras 12-15
- **Docs updated:** `docs/features/pillar3-disclosures.md` (CR9/CR9.1 sections, mermaid flowchart, template table), `docs/specifications/output-reporting.md` (CR9/CR9.1 in Pillar III template list)
- **Tests:** 44 new tests in `tests/unit/test_pillar3.py` across 6 test classes: TestCR9TemplateDefinitions (15), TestCR9Generation (6), TestCR9ColumnValues (10), TestCR9PDAllocation (3), TestCR9EdgeCases (7), TestCR9BundleIntegration (3) + TestCR9ExcelExport (1). All 4,832 tests pass (was 4,788). Pillar III tests: 197 (was 153).

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

### P3.4 UKB CMS1 / CMS2 (output floor comparison)
- **Status:** [x] Complete (2026-04-08)
- **Impact:** PRA PS1/26 Art. 456 and Art. 2a define two mandatory output floor comparison templates. Both are new Basel 3.1-specific Pillar III templates with no CRR equivalent.
- **Implementation:**
  - **UKB CMS1** — Comparison of SA vs modelled RWA by risk type (Art. 456(1)(a), Art. 2a(1)). 4 columns (a: modelled RWA, b: SA portfolio RWA, c: total actual RWA, d: full SA RWA) × 8 rows (credit risk, CCR, CVA, securitisation, market risk, op risk, residual, total). Only credit risk row (0010) and total row (0080) populated from pipeline; other risk type rows are null (beyond credit risk scope). Returns None under CRR.
  - **UKB CMS2** — Comparison of SA vs modelled RWA for credit risk at asset class level (Art. 456(1)(b), Art. 2a(2)). 4 columns × 17 rows covering sovereign, institutions, subordinated debt/equity, corporates (with FIRB/AIRB/SL/IPRE sub-rows), retail (with QRRE/other/mortgage sub-rows), others, and total. Sub-rows 0044 (IPRE/HVCRE), 0045 (purchased receivables corp), 0054 (purchased receivables retail) are null (require pipeline data not yet available).
  - **Bundle:** `Pillar3TemplateBundle.cms1` and `.cms2` fields added (both `pl.DataFrame | None`).
  - **Excel export:** CMS1/CMS2 exported via `export_to_excel()` with `UKB CMS1` and `UKB CMS2` sheet names.
  - **Data source:** Uses `rwa_pre_floor` (modelled RWA), `sa_rwa` (SA-equivalent RWA), and per-exposure `approach_applied`/`exposure_class` columns from the pipeline results LazyFrame. Same data source as COREP OF 02.01.
- **File:Line:** `reporting/pillar3/templates.py` (CMS1_COLUMNS, CMS1_ROWS, CMS2_COLUMNS, CMS2_ROWS, CMS2_SA_CLASS_MAP), `reporting/pillar3/generator.py` (_generate_cms1, _generate_cms2, Pillar3TemplateBundle.cms1/.cms2)
- **Spec ref:** PRA PS1/26 Art. 456, Art. 2a (page 467 of PS1/26 App 1)
- **Tests:** 47 new tests in `tests/unit/test_pillar3.py`: TestCMS1TemplateDefinitions (7), TestCMS1Generation (13), TestCMS2TemplateDefinitions (8), TestCMS2Generation (16), plus 3 end-to-end tests. Total: 4,687 (was 4,640). Pillar III tests: 153 (was 106).

### P3.5 CR9.1 (ECAI-based PD backtesting) — template only, no generator
- **Status:** [ ] Not started (2026-04-08 — identified in comprehensive audit phase 2)
- **Impact:** `CR9_1_COLUMNS` and `CR9_1_COLUMN_REFS` exist in `reporting/pillar3/templates.py` (lines 562-574) but the generator has no `_generate_cr9_1()` method and `Pillar3TemplateBundle` has no `cr9_1` field. P3.2 is marked [x] Complete but CR9.1 is not callable. Only needed for firms using Art. 180(1)(f) ECAI-based PD estimation.
- **File:Line:** `reporting/pillar3/templates.py:562-574` (template defs), `reporting/pillar3/generator.py` (no generate method)
- **Spec ref:** PRA PS1/26 Art. 180(1)(f), Annex XXII
- **Fix:** Add `cr9_1: dict[str, pl.DataFrame] | None` field to bundle. Add `_generate_cr9_1()` stub that returns empty dict (data depends on ECAI mapping not yet in pipeline). Document as known gap.
- **Tests needed:** Bundle field exists, generator returns empty, Excel export handles None.

---

## Priority 4 -- Documentation & Consistency Fixes

### P4.1 Output floor transitional schedule inconsistency
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Code uses PRA compressed 4-year schedule (60%/65%/70%/72.5% for 2027-2030). But `docs/framework-comparison/technical-reference.md` lines 72-78 show BCBS 6-year schedule (50%-72.5% for 2027-2032). `TransitionalScheduleBundle` docstring references 50% (2027). Data tables agent confirms: output floor PRA 4-year phase-in schedule in code is correct.
- **Fix:** Fixed BCBS 6-year schedule (50%/55%/60%/65%/70%/72.5%) to PRA 4-year (60%/65%/70%/72.5%) in 7 doc files: technical-reference.md, key-differences.md, basel31.md, configuration.md, overview.md, api/configuration.md, appendix/index.md (Gantt chart). Added Art. 92 para 5 permissive note.

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

### P4.5 PD floor documentation discrepancy
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Multiple doc files showed wrong Basel 3.1 PD floor values for retail mortgage (0.05% instead of 0.10%, Art. 163(1)(b)) and QRRE transactor (0.03% instead of 0.05%, Art. 163(1)(c)).
- **Fix:** Corrected PD floor values across 5 doc files (10 locations): `api/configuration.md` (basel_3_1() docstring: mortgage 0.05%→0.10%, transactor 0.03%→0.05%; code example comment 0.0300%→0.0500%), `user-guide/configuration.md` (RETAIL_MORTGAGE 0.0005→0.0010, RETAIL_QRRE_TRANSACTOR 0.0003→0.0005, custom floors example 0.0005→0.0010), `user-guide/exposure-classes/retail.md` (mortgage IRB 0.05%→0.10%, QRRE clarified CRR 0.03% vs B31 0.05%), `data-model/regulatory-tables.md` (mortgage B31 0.05%→0.10%, transactor B31 0.03%→0.05%).

### P4.6 LGD floor documentation discrepancy
- **Status:** [x] Complete (2026-04-08)
- **Impact:** `user-guide/configuration.md` LGD floor code example showed BCBS values instead of PRA PS1/26 values. `api/configuration.md` showed residential_real_estate as 0.05 (retail floor) instead of 0.10 (corporate floor, Art. 161(5)).
- **Fix:** Fixed 2 files: `user-guide/configuration.md` LGD floor example corrected (RECEIVABLES 15%→10%, CRE 15%→10%, OTHER_PHYSICAL 20%→15%, RRE annotated as corporate 10% with note about retail 5%). `api/configuration.md` residential_real_estate corrected from 0.05 to 0.10 with Art. 161(5) annotation. Note: code correctly uses 0.10 for corporate (residential_real_estate field) and 0.05 for retail (retail_rre field) — these are separate LGDFloors fields.

### P4.7 Spec file for equity approach
- **Status:** [x] Complete

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

### P4.13 CCF spec incomplete -- missing Table A1 rows and structural changes
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `credit-conversion-factors.md` vs PRA PS1/26 Art. 111 Table A1:
  - Row 2 (100% -- commitments with certain drawdowns: factoring, forward purchases, repos) missing
  - Row 3 (50% -- other issued OBS items, not credit-substitute character) missing
  - B31 removal of maturity-based distinction (>1yr/<=1yr) not documented
  - F-IRB B31 table **wrong**: shows 75% for medium risk (should be 50% per Art. 166C), shows 40% UCC (should be 10%)
  - Art. 166(9) trade LC exception is blanked in PS1/26 -- spec still references it
- **Fix:** CCF spec corrected: F-IRB B31 table values fixed (75%→50% for medium risk, 40%→10% for UCC). Missing Table A1 rows added (Row 2: 100% factoring/forward purchases/repos; Row 3: 50% other OBS items not of credit-substitute character). B31 removal of maturity-based distinction (>1yr/<=1yr) now documented. Art. 166(9) trade LC exception noted as blanked in PS1/26.

### P4.14 Stale key-differences.md implementation status claims
- **Status:** [~] Reopened (2026-04-18 — Phase 2a docs audit)
- **Impact:** `key-differences.md` claims "Not Yet Implemented" for:
  - (a) Currency mismatch 1.5x multiplier -- implemented at `engine/sa/calculator.py:900-966`
  - (b) SA Specialised Lending Art. 122A-122B -- implemented at `engine/sa/calculator.py:528-533`
  - (c) Provision-coverage-based defaulted treatment CRE20.87-90 -- implemented at `engine/sa/calculator.py:451-461`
- **Fix (partial, 2026-04-07):** `key-differences.md` was updated previously, but `docs/specifications/basel31/key-differences.md` still lists currency-mismatch, SA SL, and provision-based defaulted as "Not Yet Implemented" — these are implemented. Reopened after Phase 2a docs audit.
- **Fix remaining:** Remove "Not Yet Implemented" markers from `docs/specifications/basel31/key-differences.md` for the three features.

### P4.15 CRM spec extensive gaps vs PRA PS1/26 (Art. 192-239)
- **Status:** [x] Complete (2026-04-08)
- **Fixed:** Comprehensive rewrite of `credit-risk-mitigation.md`. All 26 originally identified gaps addressed:
  - Separated CRR and Basel 3.1 supervisory haircut tables throughout — previously tables were mixed or used wrong-regime values
  - Fixed corporate/institution bond 5-band haircut values — old spec showed values matching neither CRR nor Basel 3.1; now shows correct CRR 3-band and B31 5-band tables separately
  - Added CRR LGDS values (35%/35%/40%) alongside Basel 3.1 values (20%/20%/25%) — previously only B31 LGDS shown
  - Added CRR vs B31 distinctions for gold (CRR 15% → B31 20%), equity main-index/other (CRR 15%/25% → B31 20%/30%), and LGDU (CRR 45% uniform → B31 40%/45% FSE split)
  - Documented overcollateralisation ratios with regulatory basis (Art. 230(2)) — previously flagged as having "no basis in PS1/26"
  - Cleaned up 6 "Warning — Previous Description Was Wrong" admonition boxes into concise notes — spec corrections are now established fact, not pending corrections
  - Fixed AIRB section stale "known gap" language for Art. 164(4)(c) blended LGD floor — P1.87 is complete; updated accordingly

### P4.16 IRB spec inaccuracies vs PRA PS1/26 PDF
- **Status:** [x] Complete
- **Fixed:** 2026-04-07 (all remaining issues resolved)
- **Impact:** All spec inaccuracies fixed:
  - `firb-calculation.md` CRR PD floor: already shows correct 0.03% (verified; no "0.05% Correction" box exists)
  - `airb-calculation.md` subordinated LGD floor: already corrected with warning admonition (25% for corporate, 50% only for retail QRRE)
  - `airb-calculation.md` mortgage RW floor: already shows 10% with correction warning
  - `firb-calculation.md` SME formula: already has both EUR (CRR) and GBP (B31) sections
  - Art. 146(3): added as root PMA obligation reference in PMA section heading (Art. 146(3) / Art. 158(6A))
  - All other sub-items were already fixed in earlier increments (strikethrough entries)
  - Stale spec markers fixed: Art. 147A 'Critical Gap' → 'Implemented (P1.4)', FSE 'not implemented' → 'implemented'. Equity-approach.md FR-1.7a/b/c updated to Done.

### P4.17 Hierarchy-classification spec missing Art. 123A retail qualifying criteria
- **Status:** [x] Complete

### P4.18 Hierarchy-classification spec does not reference Art. 147A
- **Status:** [x] Complete

### P4.19 Exposure class priority ordering (Art. 112 Table A2) not documented
- **Status:** [x] Complete

### P4.20 COREP C 08.02 PD bands use fixed buckets instead of firm-specific rating grades
- **Status:** [ ] Not started
- **Impact:** COREP reporting agent notes C 08.02 implementation uses 8 fixed PD buckets instead of firm-specific internal rating grades. The regulatory requirement is to report by the firm's own internal rating scale. Fixed buckets may not align with a firm's actual rating grade structure.
- **File:Line:** `reporting/corep/generator.py` (C 08.02 generation)
- **Spec ref:** PRA COREP reporting requirements
- **Fix:** Make PD band definitions configurable based on firm's internal rating grade structure. Add rating grade configuration to CalculationConfig or as a separate reporting config.
- **Tests needed:** Unit tests with custom PD band definitions.

### P4.21 firb-calculation.md CRR PD floor "correction" is itself wrong
- **Status:** [x] Complete

### P4.22 Basel 3.1 haircut values wrong in documentation + remaining stale output floor references
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Multiple doc files had wrong Basel 3.1 supervisory haircut values (already fixed in primary files) and BCBS 6-year output floor schedule (50%/2032) instead of PRA 4-year (60%/2030).
- **Fix:** Haircut values were previously corrected. Output floor schedule corrected across 12 files (13 locations): `plans/implementation-plan.md` (B31-F3 50%→60%, full 6-year table→4-year table), `api/engine.md` (docstring 50%→60%, 2032→2030), `api/contracts.md` (TransitionalScheduleBundle docstring 50%→60%, 2032→2030), `framework-comparison/reporting-differences.md` (50%→60%, 2032→2030), `plans/prd.md` (scope table 50%→60%, feature row 50%→60%, milestone 2032→2030), `specifications/index.md` (B31-F 50%→60%, M3.3 2032→2030), `features/index.md` (50%→60%, 2032→2030), `specifications/regulatory-compliance.md` (50%→60%), `framework-comparison/index.md` (2032→2030), `appendix/index.md` (2027-2032→2027-2030, 1 Jan 2032→2030), `framework-comparison/impact-analysis.md` (2032→2030), `user-guide/configuration.md` (code examples: 55%→65% for 2028, explicit 0.55→0.65).

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

### P5.1 Stress / performance acceptance tests
- **Status:** [x] Complete (2026-04-08)
- **Impact:** The `tests/acceptance/stress/` directory was empty. No stress tests existed to validate pipeline correctness at scale.
- **Fix:** Added 56 stress tests (+ 4 slow/100K tests) across 14 test classes in `tests/acceptance/stress/`:
  - **Data generation:** `conftest.py` generates synthetic datasets at 10K/100K counterparty scale using numpy-vectorized generators. Counterparties cover 5 entity types (corporate 35%, individual 30%, institution 15%, sovereign 10%, specialised_lending 10%). Loans (3x CPs), facilities (1x CPs), contingents (0.5x CPs), ratings (70% rated, 40% internal), org_mappings (40% hierarchy), and facility_mappings (30% mapped) are all generated. IRB mode enriches ratings with model_id and attaches full IRB model_permissions via `irb_test_helpers.py`.
  - **TestRowCountPreservation (8 tests):** Verifies loan count, contingent count, exposure type classification, and facility_undrawn generation across CRR SA/IRB and B31 SA/IRB.
  - **TestColumnCompleteness (4 tests):** All required output columns (exposure_reference, exposure_class, risk_weight, ead_final, rwa_final, approach_applied) present across 4 framework/permission combos.
  - **TestNumericalStability (10 tests):** No NaN/inf/null/negative values in rwa_final, ead_final, risk_weight. Sums are finite and positive.
  - **TestRiskWeightBounds (4 tests):** SA risk weights in [0%, 1250%], IRB risk weights non-negative.
  - **TestApproachDistribution (5 tests):** SA-only mode produces only SA; IRB mode routes to IRB approaches; IRB exposures have positive RWA.
  - **TestExposureClassCoverage (4 tests):** Multiple exposure classes present; corporate and retail classes verified.
  - **TestOutputFloorAtScale (7 tests):** B31 IRB has output floor summary with positive U-TREA/S-TREA; floor percentage valid (50%-72.5%); post-floor RWA >= U-TREA; CRR has no floor; SA-only has zero shortfall.
  - **TestErrorAccumulation (4 tests):** Errors are list, bounded (<1000), pipeline succeeds despite warnings.
  - **TestSummaryConsistency (2 tests):** Summary RWA matches detailed results; summary approaches cover all result approaches.
  - **TestEADConsistency (4 tests):** Non-negative, non-null, non-NaN EAD; positive total EAD.
  - **TestDeterminism (1 test):** Two identical pipeline runs produce identical RWA totals.
  - **TestFrameworkComparison (1 test):** B31 SA RWA differs from CRR SA (different risk weights).
  - **TestExposureReferenceUniqueness (2 tests):** No duplicate exposure references in output.
  - **TestLargeScale100K (4 tests, @pytest.mark.slow):** 100K row count, numerical stability, memory bounded (<4GB), B31 output floor — excluded from normal runs.
  - Session-scoped fixtures cache 4 pipeline results (CRR SA/IRB, B31 SA/IRB at 10K scale) for fast test execution (~7s total).
- **File:Line:** `tests/acceptance/stress/__init__.py`, `tests/acceptance/stress/conftest.py`, `tests/acceptance/stress/test_stress_pipeline.py`
- **Key learning:** IRB routing requires both `model_permissions` and internal ratings with `model_id`. Without model_permissions, all exposures fall back to SA regardless of `permission_mode=IRB`. Internal ratings must have `pd` column non-null for `internal_pd` to propagate via hierarchy resolver.
- **Tests:** All 4,362 tests pass (was 4,306). Stress tests: 56 normal + 4 slow. Contract tests: 144.

### P5.2 Fixture referential integrity
- **Status:** [x] Complete (2026-04-08)
- **Impact:** 12 CRM fixture records (5 collateral, 4 guarantee, 3 provision) referenced "dedicated test loans" that were never added to the loan fixture. All had `beneficiary_type="loan"` pointing to `LOAN_COLL_TEST_*`, `LOAN_GUAR_TEST_*`, and `LOAN_PROV_TEST_*` references that did not exist in `tests/fixtures/exposures/loans.py`. These orphaned references meant CRM processing silently ignored these records during acceptance test pipeline runs.
- **Fix:** Added `_dedicated_test_loans()` function with 12 new loan records to `loans.py`:
  - **5 collateral test loans:** `LOAN_COLL_TEST_CORP_001` (gilt bond target), `LOAN_COLL_TEST_CORP_002` (equity target), `LOAN_COLL_TEST_CORP_003` (cash target), `LOAN_COLL_TEST_SME_001` (SME cash target), `LOAN_COLL_TEST_RTL_001` (receivables target). Counterparties: `CORP_UR_001` (corporate), `CORP_SME_001` (SME), `RTL_SME_001` (retail SME).
  - **4 guarantee test loans:** `LOAN_GUAR_TEST_SOV_001` (sovereign guarantee target, £5m), `LOAN_GUAR_TEST_001` (bank guarantee 60% target, £1m), `LOAN_GUAR_TEST_002` (bank guarantee 50% target, £2m SME), `LOAN_GUAR_TEST_RTL_001` (corporate guarantee target, £500k retail). Loan sizes match guarantee comments.
  - **3 provision test loans:** `LOAN_PROV_TEST_CORP_001` (stage 2 £50k = 5% of £1m), `LOAN_PROV_TEST_CORP_002` (stage 1 £25k = 0.1% of £25m), `LOAN_PROV_TEST_SME_001` (stage 2 £25k = 5% of £500k). Loan sizes match provision amount comments.
  - All loans use existing counterparties (`CORP_UR_001`, `CORP_SME_001`, `RTL_SME_001`) to avoid adding new counterparty fixtures. All use standard defaults (senior, LGD 0.45, GBP, maturity 2029-12-31).
  - Regenerated `loans.parquet` (67 → 79 records). `generate_all.py` integrity check now reports all 13 checks passed.
- **Regression prevention:** Added `tests/integration/test_fixture_integrity.py` with 20 tests across 5 test classes:
  - **TestCounterpartyReferences (4 tests):** loan/facility/contingent/rating counterparty refs → counterparties
  - **TestCRMBeneficiaryReferences (6 tests):** collateral loan/facility refs, guarantee loan/facility/guarantor refs, provision loan refs → loans/facilities/counterparties
  - **TestMappingReferences (4 tests):** facility mapping parent/child, org mapping, lending mapping → facilities/loans/counterparties
  - **TestModelIDReferences (1 test):** rating model_ids → model_permissions
  - **TestFixtureDataQuality (5 tests):** no duplicate references in loans/facilities/collateral/guarantees/provisions
- **File:Line:** `tests/fixtures/exposures/loans.py` (_dedicated_test_loans function), `tests/integration/test_fixture_integrity.py` (20 tests)
- **Tests:** All 5,001 tests pass (was 4,981). Integration tests: 121 (was 101). Contract tests: 145.

### P5.3 CRR CRM guarantee/provision test placeholders
- **Status:** [x] Complete (2026-04-08)
- **Impact:** CRM acceptance tests covered only 6 basic scenarios (D1-D6: cash/bond/equity collateral, bank guarantee, maturity mismatch, FX mismatch) and 3 provision scenarios (G1-G3: SA deduction, IRB shortfall, IRB excess). Advanced CRM flows (non-beneficial guarantees, sovereign guarantee substitution, CDS restructuring exclusion, gold/equity collateral, overcollateralisation, full CRM chain, mixed collateral, multi-provision, provision+collateral combo) were untested at acceptance level.
- **Fix:** Added 36 new end-to-end acceptance tests in `tests/acceptance/crr/test_scenario_crr_d2_crm_advanced.py` across 13 test classes using the inline data pipeline pattern (self-contained, no fixture regeneration required):
  - **TestCRRD7_NonBeneficialGuarantee (3 tests):** Unrated corporate guarantor (100% RW) on unrated corporate borrower (100% RW) → no substitution benefit. Verifies RWA unchanged, RW unchanged, EAD not reduced.
  - **TestCRRD8_SovereignGuarantee (3 tests):** UK sovereign (CQS 0, 0% RW) fully guarantees corporate → RWA near zero. Tests full substitution to 0% RW.
  - **TestCRRD9_CDSRestructuringExclusion (3 tests):** CDS from CQS 1 institution without restructuring clause → 40% protection reduction (Art. 216(1)/233(2)). RWA between fully-protected and unprotected.
  - **TestCRRD9b_CDSWithRestructuring (2 tests):** Same CDS with restructuring included → no haircut, full protection. Contrast with D9.
  - **TestCRRD10_GoldCollateral (3 tests):** Gold at CRR 15% haircut. EAD = 1M - 500k × 0.85 = 575k. RWA consistent with EAD.
  - **TestCRRD11_EquityCollateral (3 tests):** Main-index equity at CRR 15% haircut. Same EAD as gold (both 15% CRR).
  - **TestCRRD12_Overcollateralised (2 tests):** Cash 700k > loan 500k → EAD = 0, RWA = 0. Tests EAD floor.
  - **TestCRRD13_FullCRMChain (4 tests):** Provision (100k) + cash collateral (300k) + bank guarantee (200k at 20% RW) on 1M corporate. All three CRM mechanisms reduce capital.
  - **TestCRRD14_MixedCollateral (3 tests):** Cash (0% haircut) + CQS 1 sovereign bond 6yr (4% haircut) on 2M exposure. EAD = 2M - 500k - 480k = 1.02M.
  - **TestCRRG4_ProvisionSADeduction (3 tests):** 150k provision on 500k drawn → EAD = 350k.
  - **TestCRRG5_MultipleProvisions (2 tests):** Two provisions (100k + 50k) summed → EAD = 850k.
  - **TestCRRG6_ProvisionAndCollateral (3 tests):** 200k provision + 300k cash on 1M → EAD = 500k.
  - **TestCRRD2_StructuralValidation (2 tests):** Unprotected baseline 1M corporate validates test infrastructure.
- **Finding:** Equity collateral haircut always uses main-index rate (CRR 15% / B31 20%) because `is_eligible_financial_collateral` is overloaded as the `is_main_index` proxy in `haircuts.py:282-285`. Other-listed equity (CRR 25% / B31 30%) cannot be specified through the standard schema — a dedicated `is_main_index` Boolean field is needed on COLLATERAL_SCHEMA.
- **File:Line:** `tests/acceptance/crr/test_scenario_crr_d2_crm_advanced.py` (36 tests, ~740 lines)
- **Spec ref:** CRR Art. 110, Art. 213-217, Art. 224 Table 4, Art. 233(2)/Art. 216(1), Art. 233A, Art. 235
- **Tests:** All 5,061 tests pass (was 5,025). CRR acceptance: 169 (was 133). Contract tests: 145.

### P5.4 Conditional pytest.skip() in acceptance tests
- **Status:** [x] Complete (2026-04-08)
- **Impact:** 12 slotting acceptance tests (8 CRR, 4 Basel 3.1) were permanently skipping because the 8 slotting scenario counterparties (SL_PF_STRONG, SL_PF_GOOD, SL_IPRE_WEAK, SL_HVCRE_STRONG + 4 SHORT variants) had no internal ratings in the fixture data. Without ratings, `enrich_ratings_with_model_id()` could not stamp `model_id`, so the classifier could not grant slotting permission via `model_permissions` — all exposures fell back to SA. Under Basel 3.1, IPRE/HVCRE were rescued by the Art. 147A(1)(c) forced-slotting override, but PF exposures and all CRR exposures still fell through.
- **Fix:** Added `_slotting_scenario_internal_ratings()` function to `tests/fixtures/ratings/ratings.py` with 8 new internal ratings (one per scenario counterparty). Each rating has `rating_type="internal"` and `model_id=None` so that `enrich_ratings_with_model_id()` stamps `"TEST_FULL_IRB"`, which the classifier matches against `create_slotting_only_model_permissions()` granting slotting for specialised lending. PD values are indicative only (slotting uses category-based weights). Regenerated `ratings.parquet` (84 → 92 records).
- **File:Line:** `tests/fixtures/ratings/ratings.py` (_slotting_scenario_internal_ratings function)
- **Tests:** All 4,374 tests pass (was 4,362). Skipped: 21 (was 33 — 12 fewer). The remaining 21 skips are all benchmark tests intentionally disabled via `--benchmark-disable` in pyproject.toml. CRR acceptance: 133 (0 skips). B31 acceptance: 212 (was 208, 0 skips). All 12 slotting scenarios now validated end-to-end: CRR-E1 PF Strong 70%, CRR-E2 PF Good 90%, CRR-E3 IPRE Weak 250%, CRR-E4 HVCRE Strong 95%, CRR-E5-E8 short-maturity variants (50%/70%/70%/95%). B31-E1/E2 PF 70%/90%, B31-E3 IPRE 250%, B31-E4 HVCRE 95%.

### P5.5 Polars venv broken (environment issue)
- **Status:** [x] Resolved (2026-04-08 — stale; venv is working)
- **Impact:** Previously reported `ImportError` for `POLARS_STORAGE_CONFIG_KEYS`. Investigation (2026-04-08) confirmed this is **stale** — polars 1.37.1 is installed and working, 4,237 tests pass. The issue was resolved in a prior `uv sync` cycle.
- **Fix:** No action needed. Environment is healthy.

### P5.6 IRB unit tests extremely low (~72 tests)
- **Status:** [x] Complete (2026-04-07)
- **Impact:** IRB unit test count was ~322 across 12 files, but key areas had zero or minimal coverage. `irb/stats_backend.py` had **zero** tests. PD floor per-class enforcement under Basel 3.1, LGD floor per-class/collateral enforcement, correlation FI scalar, SME B31 GBP thresholds, F-IRB FSE/non-FSE LGD distinction, and full pipeline integration were all untested or under-tested.
- **Fix:** Added 138 new unit tests in `tests/unit/irb/test_irb_formulas.py` covering:
  - (a) **Stats backend** (14 tests): `normal_cdf` and `normal_ppf` — known values, symmetry, monotonicity, CDF(0)=0.5, PPF(0.999)≈G_999, CDF↔PPF roundtrip identity, critical quantiles
  - (b) **PD floors** (17 tests): CRR uniform 0.03% across 7 exposure classes, Basel 3.1 per-class (corporate 0.05%, mortgage 0.10%, QRRE transactor 0.05%, revolver 0.10%, retail_other 0.05%), null→corporate fallback, missing transactor column→revolver default
  - (c) **LGD floors** (13 tests): CRR no floors, B31 corporate unsecured 25%, retail mortgage 5%, QRRE 50%, retail_other 30%, F-IRB not floored, financial collateral 0%, other_physical 15%, subordinated with/without exposure_class
  - (d) **Correlation** (23 tests): all 5 exposure class families (corporate [0.12-0.24], mortgage fixed 0.15, QRRE fixed 0.04, retail_other [0.03-0.16], institution/sovereign→corporate), SME adjustment (CRR EUR vs B31 GBP thresholds, max 0.04 reduction, null turnover, only corporate), FI scalar (1.25× multiplier, can exceed 0.24), get_correlation_params() substring matching
  - (e) **Capital K** (12 tests): positivity, PD=0→0, PD=1→LGD, LGD=0→0, monotonicity (PD, LGD, correlation), K≤LGD always, K≥0 always, realistic range, manual formula verification, vectorized-scalar consistency
  - (f) **Maturity adjustment** (10 tests): MA=1 at M=1.0 floor, MA>1 at M=2.5/5.0, monotonicity, floor/cap clipping, low PD higher sensitivity, always positive, manual formula verification, vectorized-scalar consistency
  - (g) **Double default** (4 tests): formula 0.15+160×PD_g, low PD_g, zero K_obligor, investment-grade reduction
  - (h) **Expected loss** (4 tests): EL=PD×LGD×EAD, zero inputs
  - (i) **calculate_irb_rwa scalar** (9 tests): CRR/B31 scaling, PD/LGD floor application, MA toggle, risk weight/RWA formula consistency, zero EAD
  - (j) **F-IRB LGD pipeline** (8 tests): CRR senior 45%, CRR subordinated 75%, B31 non-FSE 40%, B31 FSE 45%, B31 subordinated 75%, A-IRB own LGD, lgd_post_crm, missing FSE column
  - (k) **Full pipeline integration** (10 tests): all output columns, CRR end-to-end, B31 vs CRR 6% scaling ratio, retail no MA, default maturity, missing turnover, mixed classes, row count, FI scalar
  - (l) **Config factories** (11 tests): PDFloors.crr/basel_3_1 values, get_floor QRRE transactor/revolver, LGDFloors.crr/basel_3_1 values, get_floor retail_mortgage_immovable/corporate_immovable/QRRE/retail_other
- **File:Line:** `tests/unit/irb/test_irb_formulas.py` (138 tests, ~1040 lines)
- **Tests:** All 3,886 tests pass (was 3,748). IRB test count now ~460 across 13 files.
- **Learnings:** MA=1.0 at maturity floor M=1.0 (not M=2.5 as commonly assumed — formula numerator (M-2.5)×b cancels denominator only at M=1.0). Subordinated corporate LGD floor is 25% when exposure_class present (Art. 161(5) applies uniformly); the 50% subordinated_unsecured config value is only a conservative fallback when exposure_class is absent.

### P5.7 No direct CRM submodule unit tests
- **Status:** [x] Complete (2026-04-07)
- **Impact:** CRM submodules (`guarantees.py`, `provisions.py`, `collateral.py`) were only tested indirectly through CRMProcessor integration. No direct unit tests for individual CRM functions like guarantee FX haircut, restructuring exclusion, multi-level resolution, pro-rata allocation, cross-approach CCF substitution, netting collateral generation, or supervisory LGD assignment.
- **Fix:** Added 92 new direct unit tests across 3 test files:
  - **`tests/unit/crm/test_guarantee_submodules.py` (52 tests):** Direct tests for 7 guarantee sub-functions: `_apply_guarantee_fx_haircut` (10 tests: cross-currency 8% haircut, same currency no haircut, null currency, zero guaranteed portion, column-absent early returns, original_currency priority, unguaranteed recalculation, constant value, full guarantee), `_apply_restructuring_exclusion_haircut` (10 tests: CD without restructuring 40%, with restructuring no haircut, guarantee type no haircut, null defaults to True, zero portion, column-absent early returns, recalculation, constant value), `_resolve_guarantees_multi_level` (7 tests: absent beneficiary_type, direct pass-through, counterparty pro-rata, facility pro-rata, facility skipped without column, case-insensitive, mixed levels), `_allocate_guarantees_pro_rata` (5 tests: single exposure, weighted, zero EAD, no matches, beneficiary_type overwrite), `_resolve_guarantee_amount_expr` (7 tests: no percentage, null amount, percentage when null, near-zero amount, both present, both null, zero percentage), `_apply_guarantee_splits` (6 tests: no guarantees, single partial, single full, multiple sub-rows, exceeding EAD pro-rata, percentage fallback), `_apply_cross_approach_ccf` (7 tests: risk_type absent, SA+SA no-op, IRB+IRB no-op, IRB+SA substitution, zero portion, zero nominal, AIRB+SA).
  - **`tests/unit/crm/test_collateral_submodules.py` (24 tests):** Direct tests for `generate_netting_collateral` (9 tests: missing columns return None, no negative drawn, basic netting cash collateral, currency grouping, netting flag required, NETTING_ prefix, eligibility flags, pro-rata allocation) and `apply_firb_supervisory_lgd_no_collateral` (15 tests: CRR senior 45%, subordinated 75%, B31 non-FSE 40%, FSE 45%, B31 subordinated 75%, absent seniority, SA unchanged, CRR AIRB keeps modelled, B31 AIRB Foundation election, LGD modelling insufficient data, sufficient data, zero collateral columns, junior=subordinated, config None, FSE absent).
  - **`tests/unit/crm/test_provision_submodules.py` (16 tests):** Direct tests for `resolve_provisions`: direct allocation (4 tests: loan/exposure/contingent/case-insensitive), multi-level (4 tests: three levels sum, facility pro-rata, counterparty pro-rata, zero weight), SA deduction (3 tests: fully absorbed, spill to nominal, capped), IRB tracking (2 tests: FIRB/AIRB not deducted), backward compat (2 tests), no parent_facility_reference (1 test).
- **File:Line:** `tests/unit/crm/test_guarantee_submodules.py`, `tests/unit/crm/test_collateral_submodules.py`, `tests/unit/crm/test_provision_submodules.py`
- **Tests:** CRM unit test count: 562 (was 470). All 4,106 tests pass (was 4,014). 135 contract tests pass.

### P5.8 No model_permissions-specific acceptance tests under Basel 3.1
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Model permissions (per-model FIRB/AIRB/slotting with SA fallback) had no Basel 3.1 acceptance tests covering Art. 147A interactions. Investigation also revealed that model_permissions could bypass class-level Art. 147A restrictions (CGCB/PSE/MDB/RGLA forced SA, Institution forced FIRB) because these were only enforced in the org-wide `IRBPermissions.full_irb_b31()`, not in the classifier when model_permissions were active.
- **Fix:** Two changes:
  1. **Classifier fix (engine/classifier.py:899-918):** Added Art. 147A(1)(a) enforcement: CGCB, PSE, MDB, RGLA exposure classes now have both AIRB and FIRB blocked when B31 is active, forcing SA regardless of model_permissions. Added Art. 147A(1)(b) enforcement: Institution exposure class now has AIRB blocked, forcing FIRB. These supplement the existing FSE/large-corp (Art. 147A(1)(d)/(e)) and IPRE/HVCRE (Art. 147A(1)(c)) checks. Redundant but harmless under org-wide permissions (which already encode these restrictions).
  2. **Acceptance tests (tests/acceptance/basel31/test_scenario_b31_m_model_permissions.py):** 16 end-to-end tests across 12 scenarios: B31-M1 FSE→FIRB, B31-M2 large-corp→FIRB, B31-M3 institution→FIRB (class-level block, not FSE), B31-M4 IPRE→slotting, B31-M5 HVCRE→slotting, B31-M6 sovereign→SA (non-domestic), B31-M7 normal corporate AIRB (positive), B31-M8 PF AIRB (positive), B31-M9 FSE+large-corp combined→FIRB, B31-M10 threshold boundary (440m→AIRB, 440m+1→FIRB), B31-M11 no model_permissions fallback→SA, B31-M12 PSE→SA. All tests create inline data and run the full pipeline.
- **File:Line:** `engine/classifier.py:899-918` (Art. 147A blocks), `tests/acceptance/basel31/test_scenario_b31_m_model_permissions.py` (16 tests)
- **Spec ref:** PRA PS1/26 Art. 147A(1)(a)-(e), `docs/specifications/common/hierarchy-classification.md`
- **Tests:** All 4,204 tests pass (was 4,188). B31 acceptance: 208 (was 192). Contract tests: 135.

### P5.9 No equity acceptance tests (CRR or Basel 3.1)
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `tests/unit/crr/test_crr_equity.py` has 49 unit tests, but no end-to-end acceptance scenario existed for equity under either framework. Given the multiple equity bugs (P1.42, P1.43, P1.71, P1.72), acceptance tests are critical for regression detection.
- **Fix:** Added 77 acceptance tests across 2 files:
  - **CRR equity (`tests/acceptance/crr/test_scenario_crr_j_equity.py`, 32 tests):** 20 scenarios across SA (CRR-J1 to J9: listed/unlisted/exchange-traded/PE/govt-supported/speculative/central_bank/subordinated_debt/CIU fallback — all flat 100% except central_bank 0% and CIU 150%), IRB Simple (CRR-J10 to J14: exchange-traded 290%, diversified PE 190%, other 370%, central_bank 0%, govt-supported 190%), CIU (CRR-J15 to J17: mandate-based 80%, third-party 1.2× multiplier, no-approach fallback 150%), and RWA arithmetic (CRR-J18 to J20: SA/IRB precision, zero EAD).
  - **Basel 3.1 equity (`tests/acceptance/basel31/test_scenario_b31_l_equity.py`, 45 tests):** 23 scenarios across SA weights (B31-L1 to L9: listed 250%, exchange-traded 250%, unlisted 250%, speculative 400%, govt-supported 100%, subordinated_debt 150%, central_bank 0%, PE 250%, is_speculative flag override), Art. 147A IRB removal (B31-L10: IRB config→SA 250%, not 290%), transitional schedule (B31-L11 to L16: year 1-3 floor never bites for 250%/400% base weights, subordinated_debt/govt-supported/central_bank excluded across all years), CIU (B31-L17 to L19: fallback 250%, mandate-based, third-party 1.2×), RWA/edge cases (B31-L20 to L22: arithmetic, zero EAD), CRR vs B31 regression contrast (B31-L23: listed 100%→250%, CIU 150%→250%, subordinated 100%→150%).
- **File:Line:** `tests/acceptance/crr/test_scenario_crr_j_equity.py` (32 tests), `tests/acceptance/basel31/test_scenario_b31_l_equity.py` (45 tests)
- **Tests:** All 4,004 tests pass (was 3,927). CRR acceptance: 133 (was 101). B31 acceptance: 192 (was 147).

### P5.10 No Basel 3.1 defaulted exposure acceptance tests
- **Status:** [x] Complete (2026-04-07)
- **Impact:** CRR has `test_scenario_crr_i_defaulted.py` (9 tests) but no B31 equivalent existed. Given the P1.51 bugs (threshold 50%→20%, denominator wrong), B31 defaulted acceptance tests are essential for regression prevention.
- **Fix:** Added `tests/acceptance/basel31/test_scenario_b31_k_defaulted.py` with 31 tests across 12 scenarios:
  - **SA defaulted (B31-K1 to K8):** Corporate high/low/zero provision (100%/150%), RESI RE non-income flat 100% exception (CRE20.88), RESI RE non-income with collateral (exception overrides split), RESI RE income-dependent (no exception, uses provision test), corporate with RE collateral blended RW (Art. 127(2) secured/unsecured split), B31 provision denominator vs CRR contrast (EAD vs EAD+provision_deducted)
  - **IRB defaulted (B31-K9 to K12):** F-IRB corporate K=0/RWA=0, A-IRB retail K=max(0,LGD-BEEL), A-IRB corporate NO 1.06 scaling (key B31 vs CRR difference, 937,500 vs CRR 993,750), A-IRB BEEL>LGD floor at K=0
- **File:Line:** `tests/acceptance/basel31/test_scenario_b31_k_defaulted.py` (31 tests)
- **Tests:** All 3,927 tests pass (was 3,896). B31 acceptance tests: 147 (was 116).

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

### P6.1 Unparameterized `list` types in bundles and protocols
- **Status:** [x] Complete (2026-04-07)
- **Impact:** 11 bare `list` fields in `contracts/bundles.py` should be `list[CalculationError]` (one already fixed: CRMAdjustedBundle.crm_errors per P6.19).
- **Fix:** All 10 remaining bare `list` fields in `contracts/bundles.py` changed to `list[CalculationError]`: `ResolvedHierarchyBundle.hierarchy_errors`, `ClassifiedExposuresBundle.classification_errors`, `SAResultBundle.errors`, `IRBResultBundle.errors`, `SlottingResultBundle.errors`, `EquityResultBundle.errors`, `AggregatedResultBundle.errors`, `ComparisonBundle.errors`, `TransitionalScheduleBundle.errors`, `CapitalImpactBundle.errors`. Also fixed `DataQualityCheckerProtocol.check()` return type from bare `list` to `list[CalculationError]` in `contracts/protocols.py`. Added `CalculationError` to TYPE_CHECKING imports in protocols.py. All 3705 tests pass, 125 contract tests pass.

### P6.2 Missing exports from `contracts/__init__.py` and `domain/__init__.py`
- **Status:** [x] Complete (2026-04-07)
- **Impact:** 13 public types were not re-exported from their package `__init__.py` files, forcing consumers to import from internal submodules. This broke the public API contract — types like `EquityResultBundle`, `OutputFloorSummary`, `IRBPermissions`, and `PostModelAdjustmentConfig` are field types on exported classes (`AggregatedResultBundle`, `CalculationConfig`), so consumers couldn't type-hint against them without reaching into internals.
- **Fix:** Added all missing re-exports:
  - `contracts/__init__.py`: `EquityResultBundle`, `OutputFloorSummary` (bundles); `EquityCalculatorProtocol`, `OutputAggregatorProtocol`, `ResultExporterProtocol` (protocols); `IRBPermissions`, `PostModelAdjustmentConfig`, `EquityTransitionalConfig` (config)
  - `domain/__init__.py`: `SCRAGrade`, `EquityType`, `EquityApproach`, `CRMCollateralMethod`, `AIRBCollateralMethod` (enums)
  - `ResultExporterProtocol` still needs `export_to_corep()` method — tracked under P2.10.
- **File:Line:** `contracts/__init__.py`, `domain/__init__.py`
- **Tests:** All 4,014 tests pass. 135 contract tests pass.

### P6.3 `CalculationConfig.collect_engine` docstring error
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Three `collect_engine` docstrings (class-level Attributes line 755, `crr()` Args line 851, `basel_3_1()` Args line 927) all described `'cpu'` as both "for memory efficiency" and "for in-memory processing" — self-contradictory. The alternative engine `'streaming'` was never named.
- **Fix:** All three docstrings corrected to: `'cpu' (default) for in-memory processing, 'streaming' for batched lower-memory execution.`
- **File:Line:** `contracts/config.py:755,851,927`

### P6.4 `EquityResultBundle.approach` uses `str` instead of `EquityApproach` enum
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `EquityResultBundle.approach` was typed as `str` with default `"sa"`, allowing any string value. The `EquityApproach` StrEnum with matching values (`SA="sa"`, `IRB_SIMPLE="irb_simple"`) existed but was unused.
- **Fix:** Changed field type from `str` to `EquityApproach` in `contracts/bundles.py`. Updated `_determine_approach()` return type to `EquityApproach` in `engine/equity/calculator.py`. All string literal comparisons and assignments replaced with enum members (`EquityApproach.SA`, `EquityApproach.IRB_SIMPLE`). `_build_audit()` approach parameter updated. Since `EquityApproach` is a `StrEnum`, all existing string comparisons in tests (`== "sa"`, `== "irb_simple"`) continue to work without modification.
- **File:Line:** `contracts/bundles.py:279` (field type), `engine/equity/calculator.py:46,174,200-232,708,733` (enum usage)
- **Tests:** All 4,014 tests pass. 135 contract tests pass. 139 equity tests pass.

### P6.5 `ELPortfolioSummary` uses `float` instead of `Decimal`
- **Status:** [x] Complete (2026-04-07)
- **Impact:** All 16 numeric fields on `ELPortfolioSummary` were `float`, violating the project convention that regulatory parameters and capital-related values use `Decimal` for precision. The EL portfolio summary feeds into T2 credit cap, OF-ADJ, and CET1/T2 deduction calculations — critical regulatory capital paths.
- **Fix:** Changed all 16 numeric fields from `float` to `Decimal` in `contracts/bundles.py`. `_el_summary.py` now converts Polars-collected float values to `Decimal(str(...))` at the construction boundary via `_to_decimal()` helper. `aggregator.py` converts back to `float()` at the OF-ADJ computation boundary (where other inputs from `OutputFloorConfig` are float). `api/formatters.py` simplified — no longer needs redundant `Decimal(str(...))` wrapping since fields are already `Decimal`.
- **File:Line:** `contracts/bundles.py:282-351`, `engine/aggregator/_el_summary.py:30-37,252-270`, `engine/aggregator/aggregator.py:122-126`, `api/formatters.py:272-279`
- **Tests:** 9 test files updated (~145 assertions) to use `float()` wrapping on ELPortfolioSummary field accesses in `pytest.approx` comparisons and float arithmetic. All 3,748 tests pass, 125 contract tests pass.

### P6.6 `CalculationError.to_dict()` returns bare `dict`
- **Status:** [x] Complete (2026-04-08)
- **Impact:** `to_dict()` at `contracts/errors.py:69` returned bare `dict` (equivalent to `dict[Any, Any]`), losing type information for downstream type checkers.
- **Fix:** Changed return type from `dict` to `dict[str, str | None]` — all keys are `str`, all values are `str` (from `.value` on enums) or `str | None` (optional fields).
- **File:Line:** `contracts/errors.py:69`

### P6.7 `is_guarantee_beneficial` absent from CRM bundle
- **Status:** [x] Complete (already implemented)
- **Impact:** Investigation (2026-04-08) found `is_guarantee_beneficial` is actively used in 11 places: defined in `data/schemas.py:794`, computed in `engine/sa/calculator.py` (lines 1636, 1651, 1672, 1677) and `engine/irb/guarantee.py` (lines 115, 125, 447, 475, 528, 535, 552). The beneficiality check is performed in the SA/IRB calculators (correct — CRM stage applies the guarantee, calculators decide if it reduces capital). The field is present and functional.
- **Fix:** No changes needed. Plan description was stale.

### P6.8 `guarantor_rating_type` output field missing from CRM audit
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Spec requires `guarantor_rating_type` in cross-approach CCF substitution output. CRM audit at `processor.py:967-1005` included `guarantor_approach` but not rating type (external CQS vs internal PD).
- **Fix:** Added `guarantor_rating_type` column derived from guarantor rating data:
  - **`guarantees.py:200-209`:** Column derived alongside `guarantor_approach`. Logic: `guarantor_internal_pd IS NOT NULL` → "internal", `guarantor_cqs IS NOT NULL` → "external", otherwise null. Internal takes precedence when both exist.
  - **`processor.py:867`:** Initialized to `null` (String) in the no-guarantee path (`_initialize_guarantee_columns`).
  - **`processor.py:1003`:** Added to `_build_crm_audit` select list between `guarantor_approach` and `protection_type`.
- **File:Line:** `engine/crm/guarantees.py:200-209` (derivation), `engine/crm/processor.py:867` (initialization), `engine/crm/processor.py:1003` (audit)
- **Spec ref:** `docs/specifications/crr/credit-risk-mitigation.md` line 348, `docs/user-guide/methodology/crm.md` line 366, CRR Art. 153(3) / Art. 233A
- **Tests:** 15 new tests in `tests/unit/crm/test_guarantor_rating_type.py` across 4 test classes: TestGuarantorRatingTypeDerivation (6: internal/external/null/precedence/alignment/no_ri), TestGuarantorRatingTypeB31 (2: internal/external), TestGuarantorRatingTypeInAudit (3: column present/value external/null no guarantees), TestGuarantorRatingTypeEdgeCases (4: dtype String/unguaranteed null/constrained values/mixed multi-exposure). All tests pass. CRM unit tests: 627.

### P6.9 Provision pro-rata weight uses pre-CCF approximation
- **Status:** [~] Approximation differs from spec
- **Impact:** `crm/provisions.py:165-166` uses `drawn_amount + interest + nominal_amount` as weight proxy. Spec says pro-rata by `ead_gross`. At provision resolution time, `ead_gross` is not yet computed (provisions run before CCF). Reasonable approximation but differs from spec.
- **Fix:** Either update spec to match implementation, or move provision step post-CCF.

### P6.10 IRB EL shortfall silently returns zero when `expected_loss` column absent
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `irb/adjustments.py:329-336` — when `expected_loss` column is not present, function returned `el_shortfall=0, el_excess=0` with no warning. In pipelines where EL was not computed upstream (e.g., missing provision step), this silently zeroed the EL shortfall rather than flagging missing computation. Affected T2 credit cap.
- **Fix:** Added `errors: list[CalculationError] | None = None` parameter to `compute_el_shortfall_excess()` in both `irb/adjustments.py` and `slotting/namespace.py`. When `expected_loss` column is absent, emits `CalculationError(code="IRB006", severity=WARNING, category=DATA_QUALITY)` with regulatory reference CRR Art. 158-159. Error wired through IRB namespace, IRB calculator chain (`_run_irb_chain` passes `sf_errors`), slotting calculator (`calculate_branch` and `get_slotting_result_bundle` pass errors). Backward compatible: `errors=None` default means no crash for existing callers.
- **File:Line:** `engine/irb/adjustments.py:292-348`, `engine/irb/namespace.py:539-556`, `engine/irb/calculator.py:194-203`, `engine/slotting/namespace.py:248-291`, `engine/slotting/calculator.py:77-108,196-206`, `contracts/errors.py:190`
- **Tests:** 12 new unit tests in `tests/unit/test_el_shortfall_error_reporting.py`: IRB direct (6 tests: emits warning, returns zeros, no warning when present, None param compat, omitted param compat, regulatory reference), slotting namespace (4 tests: emits warning, no warning when present, returns zeros, no errors param compat), IRB namespace wrapper (2 tests: passes errors through, no errors when present). All 3687 tests pass (was 3675).

### P6.11 No `ApproachType.EQUITY` enum value
- **Status:** [x] Complete (2026-04-08)
- **Impact:** `ApproachType` enum had no EQUITY member. Equity exposures in loan/contingent tables silently got wrong risk weight: 100% under both CRR and Basel 3.1 (via the default fallback), instead of 100% CRR / 250% Basel 3.1. The SA calculator's when-chain had no EQUITY branch, so equity-class rows fell through to `otherwise(risk_weight.fill_null(1.0))`.
- **Fix:** Four changes:
  1. **Enum:** Added `ApproachType.EQUITY = "equity"` to `domain/enums.py`.
  2. **Classifier:** Added equity branch in approach expression — `ExposureClass.EQUITY → ApproachType.EQUITY`. Updated `sa_exposures` filter to include EQUITY approach alongside SA, so equity rows from main tables flow through the SA calculator.
  3. **SA calculator:** Added explicit equity risk weight branches in both B31 (`_uc == "EQUITY" → 250%`, Art. 133(3)) and CRR (`_uc == "EQUITY" → 100%`, Art. 133(2)) when-chains, placed before the default `.otherwise()`. For type-specific weights (central_bank 0%, subordinated_debt 150%, speculative 400%), CIU approaches, transitional floor, and IRB Simple, users should use the dedicated `equity_exposures` input table.
  4. **Warning:** `SA005` (`ERROR_EQUITY_IN_MAIN_TABLE`) emitted via `_warn_equity_in_main_table()` when equity-approach rows detected in the SA bundle path. Lightweight `head(1).collect()` check avoids false positives. Severity=WARNING, category=DATA_QUALITY.
- **File:Line:** `domain/enums.py:112-114` (EQUITY enum), `engine/classifier.py:940-943` (approach branch), `engine/classifier.py:258-260` (sa filter), `engine/sa/calculator.py:889-895` (B31 RW), `engine/sa/calculator.py:1073-1077` (CRR RW), `engine/sa/calculator.py:1844-1887` (warning method), `contracts/errors.py:198` (SA005)
- **Spec ref:** CRR Art. 133(2), PRA PS1/26 Art. 133(3)
- **Tests:** 29 new tests in `tests/unit/test_equity_routing.py`: 4 enum tests (exists, value, distinct from SA, in members), 5 B31 RW tests (250%, RWA, multiple rows, no corporate impact, zero EAD), 3 CRR RW tests (100%, RWA, no corporate impact), 7 warning tests (emitted/severity/category/regulatory ref/no equity/no approach col/message), 3 classifier tests (entity mapping, expression logic, sa filter), 3 pipeline tests (not IRB, not slotting, falls to SA), 4 edge cases (CQS override B31/CRR, regression test, column preservation). All 4,188 tests pass (was 4,159).

### P6.12 QRRE classification silently disabled when columns absent
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `classifier.py:497-508` sets `is_qrre = pl.lit(False)` when `is_revolving` or `facility_limit` columns are absent. Previously no warning or error was logged. All QRRE exposures would silently receive non-QRRE treatment (higher capital). Cross-ref P1.25 -- `qualifies_as_retail` defaults to True when no lending group data (`classifier.py:350-363`), masking non-regulatory retail.
- **Fix:** Classifier now emits `CalculationError(code="CLS004", severity=WARNING, category=CLASSIFICATION)` when `is_revolving` and/or `facility_limit` columns are missing. Warning message specifies which column(s) are absent and the impact on QRRE classification. Added `ErrorCategory.CLASSIFICATION` enum member to `domain/enums.py`. Added `ERROR_QRRE_COLUMNS_MISSING = "CLS004"` constant and `classification_warning()` factory function to `contracts/errors.py`. Classifier's `classification_errors` list (previously always empty) is now populated. Warning fires under both CRR and Basel 3.1 frameworks.
- **File:Line:** `engine/classifier.py:206-225` (warning check), `contracts/errors.py:176,300-313` (error code + factory), `domain/enums.py:220-221` (CLASSIFICATION category)
- **Spec ref:** CRR Art. 147(5)
- **Tests:** 11 new tests in `tests/unit/test_classifier_qrre_warnings.py`: 8 warning attribute tests (both missing, only is_revolving missing, only facility_limit missing, both present no warning, severity, category, regulatory reference, Basel 3.1 compat), 3 classification behavior tests (without columns all retail_other, with columns revolving is QRRE, non-revolving not QRRE).

### P6.13 Dead `TYPE_CHECKING` block in config.py
- **Status:** [x] Complete (2026-04-08)
- **Impact:** `contracts/config.py:35-36` had `if TYPE_CHECKING: pass` — the block body was empty, and `TYPE_CHECKING` was imported but unused.
- **Fix:** Removed the `if TYPE_CHECKING: pass` block and the `TYPE_CHECKING` import. `from typing import Literal` remains.
- **File:Line:** `contracts/config.py:21,35-36`

### P6.14 Missing enum values across domain/enums.py
- **Status:** [x] Complete (2026-04-07)
- **Impact:** Multiple enum classes were reported as missing values. Investigation confirmed most are already present:
  - `ExposureClass`: SECURITISATION, INTERNATIONAL_ORGANISATION, CIU — intentionally out of scope (tracked in P7.4).
  - ~~`SCRAGrade`: A_ENHANCED~~ — **already exists** (line 313 of enums.py, added for P1.12).
  - ~~`RiskType`: OTHER_COMMIT~~ — **already exists** as `RiskType.OC` with value `"other_commit"` (line 388, added for P1.29).
  - ~~`EquityType`: SUBORDINATED_DEBT~~ — **already exists** (line 459, added for P1.59).
  - `EquityType`: LEGISLATIVE — **not needed as separate value**. The existing `GOVERNMENT_SUPPORTED` handles Art. 133(6) legislative equity (100% B31 weight, excluded from transitional floor). Calculator comments explicitly call it "Government-supported (legislative programme)".
  - `CollateralType` vs `VALID_COLLATERAL_TYPES` — **by design**: `CollateralType` enum represents CRM category groupings (FINANCIAL, IMMOVABLE, etc.) while `VALID_COLLATERAL_TYPES` represents granular input strings (cash, gold, bond, etc.). No misalignment.
  - `PropertyType.ADC` was in enum but missing from `VALID_PROPERTY_TYPES` validator — **fixed** (2026-04-07), `"adc"` added to `VALID_PROPERTY_TYPES`.
- **File:Line:** `data/schemas.py:499` (VALID_PROPERTY_TYPES), `domain/enums.py` (all verified)
- **Tests:** 1 new test in `tests/contracts/test_validation.py` for ADC property type acceptance.

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

### P6.16 risk_type/scra_grade/ciu_approach not in COLUMN_VALUE_CONSTRAINTS
- **Status:** [x] Complete (2026-04-07)
- **Impact:** Investigation found that `risk_type` (facilities, contingents) and `scra_grade` (counterparties) were **already validated** in COLUMN_VALUE_CONSTRAINTS. Only `ciu_approach` was missing — invalid CIU approach values (e.g., "invalid") would pass silently and be ignored by the equity calculator, potentially masking data quality issues.
- **Fix:** Added `VALID_CIU_APPROACHES = {"look_through", "mandate_based", "fallback"}` constant to `data/schemas.py`. Added `"ciu_approach": VALID_CIU_APPROACHES` to the `equity_exposures` entry in `COLUMN_VALUE_CONSTRAINTS`. The validation is case-insensitive and null-tolerant (null ciu_approach is valid for non-CIU equity).
- **File:Line:** `data/schemas.py:549` (VALID_CIU_APPROACHES constant), `data/schemas.py:592` (constraint entry)
- **Tests:** 10 new tests in `tests/contracts/test_validation.py`: valid ciu_approach accepted, invalid ciu_approach detected, ADC property type accepted, invalid property type detected, valid risk_type accepted, invalid risk_type detected, valid scra_grade accepted, invalid scra_grade detected, null ciu_approach skipped, equity_exposures multiple constraints. All 3,896 tests pass (was 3,886). Contract tests: 135 (was 125).

### P6.17 Pipeline _run_crm_processor() is dead code
- **Status:** [x] Complete
- **Fixed:** 2026-04-07
- **Impact:** `pipeline.py` contains `_run_crm_processor()` which is never called -- the pipeline uses a different CRM invocation path. Dead code creates maintenance burden and confusion.
- **File:Line:** `engine/pipeline.py` (_run_crm_processor function)
- **Fix:** Remove the dead function. Verify no tests reference it.
- **Tests needed:** Verify pipeline tests pass after removal.
- **Description:** Dead _run_crm_processor() method removed from pipeline.py. Test updated to use _run_crm_processor_unified() instead.

### P6.18 get_crm_unified_bundle not declared in CRMProcessorProtocol
- **Status:** [x] Complete
- **Fixed:** 2026-04-07
- **Impact:** `get_crm_unified_bundle` method was called by the pipeline (pipeline.py line 539) but not declared in `CRMProcessorProtocol`. Added the method to the protocol with full docstring. Added method to `StubCRMProcessor` in contract tests. Added compliance test `test_crm_processor_unified_bundle_protocol_satisfied`. All 3,626 tests pass (was 3,625).
- **File:Line:** `contracts/protocols.py:184-202` (protocol method), `tests/contracts/test_protocols.py:79-84` (stub), `tests/contracts/test_protocols.py:174-182` (test)

### P6.19 `apply_crm()` silently discards CRMErrors
- **Status:** [x] Complete
- **Fixed:** 2026-04-07
- **Impact:** `engine/crm/processor.py:340-343` returns `LazyFrameResult(frame=..., errors=[])` with a comment about needing conversion from `CRMError` to `CalculationError`. Any CRM errors accumulated in the `errors: list[CRMError]` list are silently dropped. This means CRM data quality issues (ineligible collateral, missing fields, constraint violations) are invisible to callers using the `apply_crm()` interface. The `get_crm_unified_bundle` path may preserve errors differently.
- **File:Line:** `engine/crm/processor.py:340-343`
- **Fix:** Convert `CRMError` instances to `CalculationError` and include in the returned result's errors list. Alternatively, use `CalculationError` directly in the CRM module.
- **Tests needed:** Unit test verifying CRM errors propagate to callers.
- **Description:** CRMError class removed. CRM processor now uses CalculationError (via crm_warning() factory) directly. apply_crm() propagates errors from CRMAdjustedBundle.crm_errors. Error emissions added for: collateral data with missing required columns (CRM001), guarantee data with missing required columns (CRM005), guarantee data with missing counterparty lookup (CRM005). CRMAdjustedBundle.crm_errors typed as list[CalculationError]. Pipeline getattr defensive access replaced with direct attribute access. 14 new tests in tests/unit/crm/test_crm_error_propagation.py.

### P6.20 `collateral_allocation` always None in CRM output bundles
- **Status:** [x] Complete (2026-04-08)
- **Impact:** Both `get_crm_adjusted_bundle` and `get_crm_unified_bundle` set `collateral_allocation=None`, meaning downstream reporting and audit could not access per-exposure collateral allocation details without parsing the full exposure frame.
- **Fix:** Added `_build_collateral_allocation()` method to `CRMProcessor` that extracts a focused 23-column LazyFrame from the processed exposures containing: 4 identifiers (`exposure_reference`, `counterparty_reference`, `approach`, `ead_gross`), 6 Art. 231 waterfall allocation columns (`crm_alloc_*` — EAD absorbed per collateral type), 2 coverage totals (`total_collateral_for_lgd`, `collateral_coverage_pct`), 7 post-haircut value columns (`collateral_adjusted_value`, `collateral_market_value`, `collateral_financial_value`, `collateral_cash_value`, `collateral_re_value`, `collateral_receivables_value`, `collateral_other_physical_value`), and 4 LGD impact columns (`lgd_secured`, `lgd_unsecured`, `lgd_post_crm`, `ead_after_collateral`). Only populated when `apply_collateral` actually ran (valid collateral present); remains `None` when no collateral or invalid collateral. Wired into both `get_crm_adjusted_bundle` and `get_crm_unified_bundle` via `collateral_applied` boolean flag.
- **File:Line:** `engine/crm/processor.py:919-963` (_build_collateral_allocation method), `processor.py:440,556,614,700` (wiring)
- **Spec ref:** CRR Art. 230-231, PRA PS1/26 Art. 230-231
- **Tests:** 24 new tests in `tests/unit/crm/test_collateral_allocation_bundle.py`: 5 population tests (populated/LazyFrame type/None without collateral/None with invalid collateral/row count), 6 column tests (identifiers/waterfall/coverage/values/LGD/no extra columns), 6 value tests (cash financial allocation/coverage pct/SA EAD reduction/FIRB LGD impact/zero allocation/matches exposure frame), 3 unified bundle tests (populated/None/values match), 4 edge cases (overcollateralised/mixed types/empty exposures/preserves references). All 4,228 tests pass (was 4,204). Contract tests: 135.

### P6.21 Equity collateral `is_main_index` proxy overloads `is_eligible_financial_collateral`
- **Status:** [x] Complete (2026-04-08)
- **Impact:** `haircuts.py:282-285` used `is_eligible_financial_collateral` as the `is_main_index` lookup key for equity collateral. When True → main-index haircut (CRR 15%, B31 20%). When False → the collateral was marked ineligible for SA EAD reduction, so "other equity" (CRR 25%, B31 30%) could not be specified through the standard schema. All eligible equity collateral was forced to the main-index haircut tier.
- **Fix:** Added `is_main_index` Boolean field to COLLATERAL_SCHEMA (`data/schemas.py`). Updated haircut lookup in `haircuts.py:_apply_collateral_haircuts()` to use `is_main_index` directly when available, falling back to `is_eligible_financial_collateral` for backward compatibility when the column is absent. Null `is_main_index` defaults to `True` (main-index) to preserve backward-compatible behavior. `is_eligible_financial_collateral` now only controls SA EAD reduction gating (in `collateral.py`) — fully decoupled from haircut tier selection.
- **File:Line:** `data/schemas.py:218` (is_main_index field), `engine/crm/haircuts.py:265-289` (is_main_index lookup with fallback)
- **Spec ref:** CRR Art. 224 Table 4 (main-index 15%, other 25%), PRA PS1/26 Art. 224 Table 3 (main-index 20%, other 30%)
- **Tests:** 26 new tests in `tests/unit/crm/test_equity_main_index.py` across 7 test classes: TestIsMainIndexSchema (3: field exists, type boolean, distinct from eligibility), TestCRREquityHaircutsWithMainIndex (6: main-index 15%, other-listed 25%, null default, decoupled eligibility, lookup function), TestB31EquityHaircutsWithMainIndex (4: main-index 20%, other-listed 30%, null default, decoupled eligibility), TestBackwardCompatNoMainIndexColumn (4: CRR/B31 eligible/ineligible fallback), TestMainIndexOverridesEligibility (3: eligible+not-main→25%, main+ineligible→15%, B31 eligible+not-main→30%), TestMultipleEquityCollateral (2: mixed main/other CRR/B31), TestOtherListedEquityPipeline (4: main-index EAD 575k, other-listed EAD 625k, EAD ordering, RWA ordering). Acceptance test docstring updated. All 5,087 tests pass (was 5,061). Contract tests: 145.

---

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

These items are verified complete. Items with **[!]** have known gaps documented in P1/P2:

**P1 items complete (moved from active section):** P1.1, P1.2, P1.3, P1.4, P1.5, P1.6, P1.7, P1.8, P1.9a, P1.9d, P1.11, P1.12, P1.13, P1.14, P1.15, P1.16, P1.17, P1.18, P1.19, P1.20, P1.21, P1.22, P1.23, P1.24, P1.25, P1.26, P1.27, P1.28, P1.29, P1.31, P1.32, P1.33, P1.34, P1.35, P1.36, P1.37, P1.38, P1.39, P1.40, P1.41, P1.42, P1.43, P1.44, P1.45, P1.46, P1.47, P1.48, P1.49, P1.50, P1.51, P1.52, P1.53, P1.54, P1.55, P1.56, P1.59, P1.60, P1.61, P1.62, P1.63, P1.64, P1.65, P1.66, P1.67, P1.68, P1.69, P1.70, P1.71, P1.72, P1.73, P1.74, P1.75, P1.76, P1.77, P1.78, P1.79, P1.80, P1.81, P1.82, P1.83, P1.84, P1.85, P1.86, P1.87, P1.88, P1.89, P1.90, P1.91

**P3 items complete:** P3.1, P3.2, P3.4

**P4 items complete:** P4.1, P4.5, P4.6, P4.7, P4.13, P4.15, P4.16, P4.17, P4.18, P4.19, P4.21, P4.22 (P4.14 reopened 2026-04-18)

**P5 items complete:** P5.1, P5.2, P5.3, P5.4, P5.5, P5.6, P5.7, P5.8, P5.9, P5.10

**P6 items complete:** P6.1, P6.2, P6.3, P6.4, P6.5, P6.6, P6.7, P6.10, P6.11, P6.12, P6.13, P6.14, P6.16, P6.17, P6.18, P6.19, P6.20, P6.21

- [x] All 8 pipeline stages (loader, hierarchy, classifier, CRM, SA/IRB/slotting/equity, aggregator)
- [x] **[!]** CRR SA risk weights (core classes: sovereign, institution, corporate, retail, RE, defaulted, equity; PSE/RGLA/MDB/Int.Org/Other Items pending -- see P1.52-P1.55)
- [x] **[!]** Basel 3.1 SA risk weights (residential/commercial RE loan-splitting, ECRA/SCRA, corporate sub-categories, ADC, equity transitional; SCRA enhanced sub-grade/short-term missing -- see P1.12, P1.26; equity B31 weights now implemented -- see P1.42 [fixed])
- [x] Basel 3.1 SA specialised lending (Art. 122A-122B) -- OF/CF=100%, PF pre-op=130%, PF op=100%, PF high-quality=80%
- [x] Basel 3.1 provision-coverage-based defaulted treatment (CRE20.87-90) -- 100% RW / 150% RW; threshold 20%, denominator EAD only -- see P1.51 [fixed]
- [x] Currency mismatch 1.5x RW multiplier (Art. 123B / CRE20.93) -- Basel 3.1 only, retail + RE classes
- [x] F-IRB calculation (supervisory LGD, PD floors, correlation, maturity adjustment, FI scalar)
- [x] A-IRB calculation (own LGD/CCF, LGD floors, post-model adjustments; mortgage RW floor 10% -- see P1.33 [fixed])
- [x] Slotting (CRR 4 tables + Basel 3.1 3 tables + subgrades)
- [x] Equity (SA Art. 133, IRB Simple Art. 155, CIU fallback listed 250%/unlisted 400%; CIU look-through/mandate partial -- see P1.61; B31 equity SA weights implemented -- see P1.42 [fixed]; transitional floor applied in pipeline -- see P1.43 [fixed]; subordinated debt 150% + transitional floor exclusion -- P1.59 [fixed]; PE/VC 400% -- P1.89 [fixed]; CIU listed/unlisted split -- P1.90 [fixed])
- [x] **[!]** CRM (collateral haircuts CRR 3-band + Basel 3.1 5-band, FX mismatch, maturity mismatch, multi-level allocation, guarantee substitution, netting, provisions, Art. 232 life insurance method, Art. 218 CLN-as-cash; gold haircut wrong -- P1.73; LGD* formula doesn't blend -- P1.75; P1.77 sequential fill fixed; P1.70 per-type OC threshold fixed; see also P1.7, P1.11, P1.30, P1.39-P1.41, P1.56)
- [x] Basel 3.1 parameter substitution (CRE22.70-85) -- including EL adjustment for guaranteed portion
- [x] Double default (CRR Art. 153(3), Art. 202-203)
- [x] Output floor with PRA transitional schedule (60%/65%/70%/72.5%) -- portfolio-level with OF-ADJ/U-TREA/S-TREA complete (P1.9a/b/d, P1.38 all done); entity-type carve-outs and reporting basis implemented
- [x] Supporting factors (CRR SME + infrastructure, removed under Basel 3.1)
- [x] CCF (SA/FIRB/AIRB, Basel 3.1 UCC changes; F-IRB B31 CCF uses SA CCFs -- P1.36 [fixed]; A-IRB revolving gate -- P1.3 [fixed]; 40% OC CCF category -- P1.29 [fixed])
- [x] Provisions (multi-level, SA drawn-first deduction, IRB EL comparison, T2 credit cap)
- [x] Dual-framework comparison (DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner)
- [x] COREP C 07.00 / C 08.01 / C 08.02 / C 08.03 / C 08.05 / C 08.06 / C 08.07 (basic structure, CRR + Basel 3.1 OF variants); OF 02.01 output floor comparison template (P2.2a/P2.2b/P2.2c/P2.2d/P2.2e/P2.2f complete; P2.4/P2.10/P2.11 complete)
- [x] API (CreditRiskCalc, export to Parquet/CSV/Excel, results cache)
- [x] Model permissions (per-model FIRB/AIRB/slotting, fallback to SA)
- [x] Marimo UI (RWA app, comparison app, template workbench, landing page)
- [x] Schema validation, bundle validation, column value constraints
- [x] FX conversion (multi-currency support)
- [x] Materialisation barriers (CPU + streaming modes)
