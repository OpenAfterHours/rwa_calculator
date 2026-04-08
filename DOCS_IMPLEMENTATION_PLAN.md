# Documentation Implementation Plan

Last updated: 2026-04-08 (Phase 2 — 5 parallel verification agents cross-checked PDFs, code, and all doc files)

Comprehensive audit of `docs/` against regulatory PDFs (PS1/26 Appendix 1, CRR, PRA comparison document) and source code (`src/rwa_calc/`). Findings verified against PDF text extraction where critical.

---

## Priority 1: Critical Gaps (incorrect regulatory values or missing material content)

### Wrong Risk Weight / Parameter Values in Docs

- [ ] **D1.1** — Corporate CQS 5 shown as 100% (BCBS) in `key-differences.md` (line 263), `basel31.md` (line 121), `corporate.md` (line 36). PRA PS1/26 Art. 122 Table 6 confirms CQS 5 = **150%**. The spec `sa-risk-weights.md` is correct; the three user-facing files are wrong.
- [ ] **D1.2** — Equity transitional 2027 row in `basel31.md` (lines 278-280) shows Standard=130%, Higher-Risk=160%. Correct values (confirmed in `key-differences.md`, `equity-approach.md`, code): Standard=**160%**, Higher-Risk=**220%**.
- [ ] **D1.3** — CRE income-producing table in `key-differences.md` (lines 330-332) and `basel31.md` (lines 163-165) shows "LTV <=60%: 70%, >60%: 110%". Art. 124I actual: <=80%: 100%, >80%: 110%. The 70% value does not exist in Art. 124I.
- [ ] **D1.4** — Sovereign unrated in `basel31.md` (lines 234-235) shows OECD bifurcation (0% OECD / 100% non-OECD). Basel 3.1 Art. 114 = flat **100%** for all unrated sovereigns; no OECD bifurcation. Art. 114(5) is left blank in PRA rules.
- [ ] **D1.5** — Corporate A-IRB subordinated LGD floor shown as 50% in `technical-reference.md` (line 43), `basel31.md` (line 87). Art. 161(5) sets **25%** for all corporate unsecured (no senior/subordinated distinction). The `airb-calculation.md` correction note is right; four other files are wrong.
- [ ] **D1.6** — Large corporate correlation multiplier in `irb-approach.md` (lines 211-213): says 1.25x applies to "large corporates (>GBP500m)". Wrong on two counts: (a) applies to **financial sector entities**, not large non-financial corporates; (b) B31 threshold is EUR 500m / **GBP440m**, not GBP500m. `key-differences.md` and `technical-reference.md` are correct. **Also wrong in:** `basel31.md` (line 213) — same error.
- [ ] **D1.7** — SCRA Grade A enhanced (30%) missing from `key-differences.md` SCRA table (lines 290-295) and `basel31.md` (line 254). Only shows A=40%, B=75%, C=150%. The spec `sa-risk-weights.md` has the full 4-row table (A/A-enhanced/B/C).
- [ ] **D1.8** — CRR equity SA table in user guide `equity.md` (lines 22-29) shows 250%/400% for unlisted/speculative. These are Basel 3.1 values. CRR Art. 133 = flat **100%** for all equity. The spec `equity-approach.md` was corrected; `equity.md` was not. The section header "Article 133 - Standardised Approach (SA)" combined with B31 values is especially misleading.
- [ ] **D1.9** — CRR equity in `sa-risk-weights.md` (lines 461-483) still shows "Unlisted: 150%, PE/VC: 190%" referencing non-existent "Art. 133(3)/(4)". These are Art. 155 IRB Simple values. The spec `equity-approach.md` correction was not propagated here.

### Stale "Not Yet Implemented" Warnings

- [ ] **D1.10** — `basel31.md` (line 187): currency mismatch multiplier marked "Not Yet Implemented". **IS implemented** (`sa/calculator.py` lines 253, 318, 383, 1701). Remove warning.
- [ ] **D1.11** — `basel31.md` (lines 374-377): SA specialised lending marked "Not Yet Implemented". **IS implemented** (`b31_risk_weights.py`, `sa/calculator.py` line 807). Remove warning.
- [ ] **D1.12** — `basel31.md` (lines 195-196): Defaulted provision-coverage split marked "not implemented". **IS implemented** per `sa-risk-weights.md` and code. Remove warning.

### Skill Reference Errors (affect agent-generated regulatory guidance)

- [ ] **D1.13** — `skills/basel31/references/irb-changes.md` (line 15): Retail mortgage PD floor = 0.05%. Correct: **0.10%**. Also QRRE transactors = 0.03%, correct: **0.05%**.
- [ ] **D1.14** — `skills/basel31/references/crm-changes.md` and `what-changed.md`: equity haircuts shown as 25%/35% (BCBS CRE22.53). PRA PS1/26 Art. 224 Table 3 confirmed: **20%/30%**. Fix skill references.
- [ ] **D1.15** — `skills/basel31/references/output-floor.md` and skill index: show BCBS 6-year transitional schedule (50%-72.5%, 2027-2032). PRA PS1/26 uses **4-year** schedule (60%-72.5%, 2027-2030). Fix skill references. **Also wrong in:** `skills/basel31/SKILL.md` index file (same BCBS 6-year schedule).
- [ ] **D1.16** — `skills/basel31/references/slotting-changes.md`: shows BCBS pre-op PF weights (80/100/120/350%). PRA has **no separate pre-op table** (uses standard non-HVCRE table). Fix skill reference.
- [ ] **D1.17** — `skills/crr/references/credit-risk-mitigation.md` (lines 37-43): invents "receivables: 20%" haircut under Art. 224. Non-financial collateral does NOT use Art. 224 supervisory haircuts — it uses Foundation Collateral Method (Art. 230). Remove.
- [ ] **D1.18** — `skills/crr/references/slotting-and-equity.md` (line 49): lists "Government-supported: 100%" as CRR equity sub-category. No such category in Art. 133.
- [ ] **D1.19** — `skills/crr/references/provisions-and-el.md` (line 27): cites "Art. 111(2)" for SA provision deduction. Correct: Art. 111(1)(a)-(b). Art. 111(2) governs derivative exposure values. **Same error in:** `docs/user-guide/methodology/crm.md` (line 374) and `docs/specifications/crr/credit-conversion-factors.md` (line 149).

### New Critical Findings (Phase 2)

- [ ] **D1.20** — CIU fallback in `key-differences.md` (line 409) shows **1,250%** for both CRR and Basel 3.1, labelled "Unchanged". CRR Art. 132(2) fallback = **150%**; Basel 3.1 aligns CIU fallback to equity SA weights (250%/400%). The 1,250% applies only to securitisation residuals, not general CIU fallback.
- [ ] **D1.21** — Art. 122(6)(b) non-investment grade unrated corporate = **135%** entirely absent from all docs. PDF Art. 122(6)(b): "Exposures to corporates which the institution has assessed as not being investment grade shall be assigned a risk weight of 135%." Files affected: `sa-risk-weights.md`, `key-differences.md`, `basel31.md`.
- [ ] **D1.22** — `sa-risk-weights.md` (lines 220-229): Table 4A mislabelled as "Own-Rating Based (CRR Art. 120(2))". Actual Table 4A is for **short-term ECAI assessments** (Art. 120(2B)): CQS1=20%, CQS2=50%, CQS3=100%, Others=150%. Current values (20/20/20/50/150/20%) are from the general short-term preferential treatment (Table 4).
- [ ] **D1.23** — Rated covered bond CQS 6 = **50%** in `key-differences.md` (line 457). Art. 129 Table 7 confirms CQS 6 = **100%**.
- [ ] **D1.24** — `crr.md` (line 107): unrated institution RW says "See due diligence approach". Under CRR, unrated institutions = flat **40%** (sovereign-derived from UK CQS 2). "Due diligence approach" is a Basel 3.1/SCRA framing, not CRR.
- [ ] **D1.25** — `other.md` (lines 43-49): B31 equity example shows exchange-traded equity at **100%** RW. This is the CRR SA value. Under Basel 3.1, exchange-traded equity = **250%** (or 160% transitionally in 2027).
- [ ] **D1.26** — `basel31.md` (lines 252-256): SCRA Grade A criteria mislabelled. Quantitative thresholds (CET1 >=14%, Leverage >=5%) shown as the criteria for 40% (standard Grade A). These are actually the criteria for **30% (Grade A Enhanced)**. Standard Grade A (40%) requires only a qualitative assessment.
- [ ] **D1.27** — `equity.md` (line 47): "Government-supported: 190%" under Art. 155 IRB Simple. Art. 155 has only three categories: exchange-traded (290%), PE diversified (190%), all other (370%). No "Government-supported" category exists.

---

## Priority 2: Basel 3.1 Specification Parity (B31 specs matching CRR depth)

### Missing B31 Specification Files

- [ ] **D2.1** — `docs/specifications/` has 9 dedicated CRR spec files but **zero** dedicated B31 spec files. All 212 B31 acceptance tests have no standalone spec to trace to. Create `docs/specifications/basel31/` with equivalent depth, or explicitly document which CRR spec files cover B31 and add B31-specific sections within them with "unchanged" markers where rules carry over.

### Scenario ID and Test Traceability Gaps

- [ ] **D2.2** — **224 acceptance tests** have no corresponding spec entry: CRR-D2 (36 tests), CRR-J equity (32), B31-K defaulted (31), B31-L equity (49), B31-M model permissions (16), stress pipeline (60). Add scenario ID definitions and spec entries for all.
- [ ] **D2.3** — Scenario ID namespace collision: `CRR-E` assigned to both slotting and equity in specs. Tests use `CRR-J` for equity. Update equity spec from `CRR-E (partial)` to `CRR-J`. Same issue: `B31-E` assigned to slotting and equity; tests use `B31-L`. Update.
- [ ] **D2.4** — 9 spec files use only group-level scenario IDs (e.g., `CRR-B`) with no numbered scenarios. Add numbered scenario IDs (CRR-B1, CRR-B2, etc.) to: `firb-calculation.md`, `airb-calculation.md`, `credit-risk-mitigation.md`, `slotting-approach.md`, `supporting-factors.md`, `provisions.md`, `credit-conversion-factors.md`, `hierarchy-classification.md`, `configuration.md`.

### Regulatory Compliance Matrix

- [ ] **D2.5** — `regulatory-compliance.md` severely outdated: claims 97 CRR / 116 B31 / 275 total tests. Actual: **169 CRR / 212 B31 / ~501 total**. Missing groups: B31-K, B31-L, B31-M, CRR-J, CRR-D2. Update all counts and add missing groups.
- [ ] **D2.6** — `index.md` scenario count table similarly stale (shows 97 CRR, 116 B31). Update.

### Missing Regulatory Content in Docs

- [ ] **D2.7** — Art. 124A qualifying criteria for real estate (9-point list: first-lien requirement, completed property, LTV monitoring, legal certainty, etc.) not documented anywhere. These determine whether exposures qualify for preferential RE risk weights (Art. 124F-124L) vs. 150%/counterparty RW fallback. Add to `sa-risk-weights.md` and/or a new B31 RE spec.
- [ ] **D2.8** — F-IRB supervisory LGD FSE distinction missing from `technical-reference.md` and `basel31.md`. Art. 161(1)(aa)/(a): non-FSE senior = 40%, FSE senior = 45%. Both files collapse to "40%".
- [ ] **D2.9** — Covered bond F-IRB LGD (11.25%, Art. 161(1B)) absent from all comparison tables except `firb-calculation.md`. Add to `key-differences.md` and `technical-reference.md`.
- [ ] **D2.10** — PD floors for sovereign and institution classes (0.05%) missing from all comparison tables in `key-differences.md`, `technical-reference.md`, `basel31.md`. Only `firb-calculation.md` documents them.
- [ ] **D2.11** — Art. 169A/169B (LGD Modelling vs Foundation Collateral Method for A-IRB) documented in `credit-risk-mitigation.md` but not cross-referenced in `airb-calculation.md` or `irb-approach.md`. A-IRB readers won't know the method exists.
- [ ] **D2.12** — A-IRB CCF restriction nuance: revolving facilities classified at 100% SA CCF (Table A1 Row 2 — factoring, repos) cannot use own-estimate CCFs even though revolving. Missing from `airb-calculation.md`.
- [ ] **D2.13** — Art. 166D(3)/(4) full-facility EAD approach for revolving facilities absent from `airb-calculation.md`. Only in `credit-conversion-factors.md`.
- [ ] **D2.14** — PMA sequencing (mortgage floor before PMA scalar, Art. 154(4A)(b) then (a)) absent from `key-differences.md` and skill references. Only `airb-calculation.md` documents ordering.
- [ ] **D2.15** — OF-ADJ formula with four named components (IRB_T2, IRB_CET1, GCRA, SA_T2) only in `output-reporting.md`. Add cross-reference in `key-differences.md`, `technical-reference.md`, and `basel31.md`.
- [ ] **D2.16** — Entity-type carve-outs for output floor (Art. 92 para 2A(b)-(d)) only in `output-reporting.md`. Add to `key-differences.md` and `technical-reference.md`.
- [ ] **D2.17** — B31 pre-op PF table in user guide `specialised-lending.md` (lines 99-107) shows BCBS weights (80/100/120/350%). PRA does NOT adopt separate pre-op table. Code is correct; user guide is wrong. **Same error in:** `key-differences.md` (lines 472-501), `technical-reference.md` (lines 140-186), `basel31.md` (lines 363-366). All show BCBS pre-op table as PRA.
- [ ] **D2.18** — Rule 4.11 unfunded CRM transitional documented in spec but no "not implemented" status note. Add implementation status note to `credit-risk-mitigation.md` (lines 468-475).
- [ ] **D2.19** — Art. 122(3) Table 6A (short-term corporate ECAI risk weights: CQS1=20%, CQS2=50%, CQS3=100%, Others=150%) not documented anywhere. The PDF confirms this table exists.
- [ ] **D2.20** — SA Specialised Lending waterfall position missing from `key-differences.md` Art. 112 Table A2 waterfall list. SA SL is a new B31 class (Art. 122A-122B).
- [ ] **D2.21** — Art. 124K ADC pre-sales/equity qualifying conditions not documented in `key-differences.md`. Only `sa-risk-weights.md` mentions 100% pre-sales exception.

### New Phase 2 Findings: Missing Regulatory Content

- [ ] **D2.22** — Art. 124H(3): Large corporate (non-natural person, non-SME) non-cash-flow-dependent CRE treatment undocumented. RW = max(60%, min(counterparty RW, income-producing RW)). This is a distinct third path alongside loan-splitting and income-producing tables. Absent from `key-differences.md` and `technical-reference.md`.
- [ ] **D2.23** — Art. 124J: "Other real estate" sub-cases missing from comparison docs. Income-producing other RE = 150%. Non-income-producing residential (fails Art. 124A) = counterparty RW. Non-income-producing commercial = max(60%, counterparty RW). Only ADC (150%) is documented.
- [ ] **D2.24** — Art. 122(6) investment-grade corporate 65% is **PRA permission-gated** but this caveat is absent from `key-differences.md`, `basel31.md`, and `sa-risk-weights.md`. All show 65% as a standard sub-category without noting that PRA permission is required.
- [ ] **D2.25** — Equity transitional scope restriction missing: Rules 4.2/4.3 (SA transitional) only apply to firms **without** IRB permission at 31 Dec 2026. IRB firms use Rules 4.4-4.6 instead. No doc file makes this distinction. Affects `key-differences.md` (lines 378-385), `equity-approach.md`.
- [ ] **D2.26** — UK residential mortgage commitments: **50% CCF** (Art. 111 Table A1 Row 4) is a PRA-specific deviation from the general "Other Commitments" 40% CCF. Absent from `key-differences.md` CCF table and `credit-conversion-factors.md`.
- [ ] **D2.27** — Retail threshold changed from EUR 1m to **GBP 880,000** under PRA PS1/26 Art. 123(1)(b)(ii). Not documented in any comparison file. Only the code config reflects this.
- [ ] **D2.28** — CRE loan-splitting secured portion uses **60%** RW (Art. 124H(1) for commercial RE), vs 20% for residential RE. Comparison docs only discuss RRE loan-splitting. The 60% CRE secured rate is absent from `key-differences.md`.
- [ ] **D2.29** — Slotting Table A subgrade A-column values (Strong A and Good C) absent from `key-differences.md` comparison table. Only B-column values shown. `technical-reference.md` includes subgrades but the main comparison table is incomplete.
- [ ] **D2.30** — Art. 124G(2) junior-charge uplift (1.25x) for income-producing residential RE absent from `key-differences.md` and `technical-reference.md`. PDF confirms: where there are prior-ranking charges not held by the institution, Table 6B RW is multiplied by 1.25 for LTV > 50%.
- [ ] **D2.31** — PRA deviation from BCBS on CRE income-producing: PRA Art. 124I uses <=80%: 100%, >80%: 110%, while BCBS CRE20.76 uses <=60%: 70%, >60%-80%: 90%, >80%: 110%. This PRA-specific simplification is not noted in comparison docs.

---

## Priority 3: Code-Docs Alignment (mismatches between docs and source)

### Code Correct, Docs Wrong

- [ ] **D3.1** — `formulas.py` line 62-63 docstring: retail mortgage PD floor = 0.05%, QRRE transactors PD floor = 0.03%. Correct values: **0.10%** and **0.05%** respectively. Code and all other docs correctly use the right values.
- [ ] **D3.2** — `config.py` line 125: `subordinated_unsecured = 0.50` as "conservative fallback" contradicts `airb-calculation.md` correction note that 25% applies to all corporate unsecured. The `technical-reference.md` table still shows 50%. Align: either remove the fallback or document it as intentionally conservative with rationale.
- [ ] **D3.3** — `crr_firb_lgd.py` line 30: CRR `FIRB_SUPERVISORY_LGD` includes `covered_bond: 11.25%`, but `firb-calculation.md` CRR table shows "—" for covered bonds (implying B31-only addition). Clarify whether CRR covered bond LGD exists and update docs.
- [ ] **D3.4** — IRB Simple `GOVERNMENT_SUPPORTED: 190%` in `crr_equity_rw.py` line 64 has no corresponding entry in the spec's Art. 155 table. Document or remove.

### Docs Correct, Code Has Known Issue (cross-ref to IMPLEMENTATION_PLAN.md)

- [ ] **D3.5** — Art. 234 tranched coverage: spec correctly flags as "not yet implemented" (credit-risk-mitigation.md lines 311-322). Cross-reference P1.30(e) in IMPLEMENTATION_PLAN.md.
- [ ] **D3.6** — CRR receivables haircut 0.20 in `crr_haircuts.py` line 71 is an "ad-hoc approximation" with no regulatory basis. The spec correctly states non-financial collateral does not use Art. 224 haircuts. Cross-reference as a code-quality item.

### Double Default Formula

- [ ] **D3.7** — `crm.md` (lines 207-213) shows `PD_joint = PD_obligor x PD_guarantor x (1 + correlation)` which is NOT the Art. 153(3) / 202-203 regulatory double-default formula. Fix or remove the illustrative formula.

### New Phase 2 Code-Docs Findings

- [ ] **D3.8** — `b31_risk_weights.py` line 194: code notes `has_short_term_ecai` schema field is missing, so Table 4A institution weights (CQS1=20%, CQS2=50%, CQS3=100%, Others=150%) cannot be applied. Code silently falls back to Table 4 (sovereign-derived). No doc notes this schema gap or the silent fallback.
- [ ] **D3.9** — `corep/generator.py` lines 1558, 1735: COREP C07/C08 counterparty credit risk rows (0090-0130) produce null values ("CCR rows — not implemented"). No documentation warning about this omission.
- [ ] **D3.10** — `crr_firb_lgd.py` F-IRB LGD table and `technical-reference.md` lines 54-60: both missing subordinated purchased corporate receivables LGD = **100%** (Art. 161(1)(f)). Extends D4.12.

---

## Priority 4: Minor Fixes (article references, formatting, stale metadata)

### Stale Version Numbers and Test Counts

- [ ] **D4.1** — `overview.md` says version 0.1.37; `prd.md` says 0.1.28. Actual: 0.1.54+. (Cross-ref P4.2)
- [ ] **D4.2** — `nfr.md` shows 1,844+ total tests. Actual: **5,188**. (Cross-ref P4.24)
- [ ] **D4.3** — Stale BCBS output floor references in docstrings: `comparison.py:18`, `bundles.py:489`, `ui/marimo/comparison_app.py:14-15` say "50% (2027) to 72.5% (2032+)". Code uses correct PRA schedule. (Cross-ref P4.33)
- [ ] **D4.4** — Stale column count in `reporting/corep/templates.py` docstring: says "24/22 columns", actual 27/27. (Cross-ref P4.28)
- [ ] **D4.5** — `model_permissions` not mentioned in `architecture.md` spec. (Cross-ref P4.10)
- [ ] **D4.6** — Type checker inconsistency: docs disagree with CLAUDE.md (`mypy` vs `ty`). (Cross-ref P4.9)

### Article Reference Corrections

- [ ] **D4.7** — `firb-calculation.md` (lines 21-32): per-collateral-type LGD values cited as "CRR Art. 161" but they are Art. 230 Table 5 LGDS values. Also missing subordinated LGDS values (65%/70%) entirely.
- [ ] **D4.8** — ~~`credit-risk-mitigation.md` CRR haircut table (lines 43-48): CQS 4 government bond haircut (15%) missing.~~ **REVIEW:** CQS 4 row (15%/15%/15%) appears to be present in current version. Verify whether this was already fixed or whether the finding references a different table within the file.
- [ ] **D4.9** — Art. 128 (high-risk items): `sa-risk-weights.md` (lines 300-307) documents it without context. Under the **CRR** (pre-2027 UK), Art. 128 may have been removed by UK onshoring. Under **PRA PS1/26** (post-2027), Art. 128 is confirmed active (PDF page 59). Add clarifying note about which framework version it applies to.
- [ ] **D4.10** — Art. 158 omitted from UK CRR as of 2022. `provisions.md` header still cites it. Update to post-2022 retained reference.
- [ ] **D4.11** — F-IRB default maturity: repo/SFT = 0.5 years (Art. 162), not just the generic 2.5. `firb-calculation.md` (line 159) only mentions 2.5.
- [ ] **D4.12** — Art. 161 subordinated purchased corporate receivables LGD (100%) missing from `firb-calculation.md` and `technical-reference.md`.
- [ ] **D4.13** — `credit-risk-mitigation.md` Art. 230 Table 5: missing subordinated LGDS values (receivables/RE senior=35%/subordinated=65%, other physical senior=40%/subordinated=70%).
- [ ] **D4.14** — MDB list in `other.md` missing 4-6 named institutions compared to `sa-risk-weights.md`.
- [ ] **D4.15** — Institution short-term table in `institution.md`: CQS 6 shown as 50%, should be **150%**.
- [ ] **D4.16** — Equity transitional rule numbering inconsistent across files (`Rule 4.1` vs `Art. 4.2/4.3`). CIU transitional (Art. 4.7-4.8) absent from `basel31.md`.
- [ ] **D4.17** — `irb-approach.md` F-IRB CCF section still uses CRR framing (75% MR/MLR, Art. 166(9)); doesn't note B31 Art. 166C alignment to SA CCFs.
- [ ] **D4.18** — Gold haircut increase (15%->20% B31) missing from `key-differences.md` CRM table. Present in `technical-reference.md` and `basel31.md`.
- [ ] **D4.19** — `sa-risk-weights.md` Art. 123 salary/pension 35% treatment labelled as B31-only. It exists in CRR Art. 123 already.
- [ ] **D4.20** — Covered bond unrated row in `sa-risk-weights.md` CRR table: spec says "20% if CQS 1-2 equivalent" but Art. 129 Table 6a has no unrated row. Clarify regulatory basis.
- [ ] **D4.21** — `exposure-classes/other.md` PSE/RGLA sections have no risk weight tables. The sovereign-derived Tables 1A/1B (RGLA) and 2/2A (PSE) from `sa-risk-weights.md` are absent.
- [ ] **D4.22** — `other.md` equity example uses 190% (IRB Simple) but labels it "CRR (Simple Approach) SA". Mislabel.
- [ ] **D4.23** — HVCRE Table 2 in `slotting-approach.md` and `crr.md`: verify against UK CRR Art. 153(5). May only exist in original EU CRR, not UK onshored version.
- [ ] **D4.24** — `crr.md` CCF table (lines 138-147) conflates MR and MLR categories. Lists "Undrawn credit facilities: 20%" when >1yr = 50% (MR) and <=1yr = 20% (MLR).
- [ ] **D4.25** — Art. 226 non-daily revaluation adjustment absent from `key-differences.md` and `technical-reference.md`. Only in `credit-risk-mitigation.md`.

### New Phase 2 Minor Findings

- [ ] **D4.26** — `crr.md` (lines 149-157): F-IRB supervisory LGD table groups CRE/RRE as single row. Inconsistent with `firb-calculation.md` spec which lists them separately. Minor presentation issue.
- [ ] **D4.27** — `crr.md` (line 33): SME supporting factor eligibility listed as "Corporate, Retail, or Secured by Real Estate". The spec `supporting-factors.md` narrows to "Corporate SME" only. CRR Art. 501 covers corporate AND retail but the spec deliberately narrows scope. Add clarifying note to one or both.
- [ ] **D4.28** — `crr.md` (lines 63-67): infrastructure factor eligibility criteria include "Revenues predominantly in EUR/GBP or hedged" (Art. 501a condition). This currency criterion is not validated in the spec or code. Document the gap or remove the criterion from user guide.
- [ ] **D4.29** — `firb-calculation.md` (lines 45-48): Basel 3.1 F-IRB collateral-type LGD values cited as "CRE32.9-12" (BCBS references). PRA regulatory reference should be Art. 161 and Art. 230. Minor citation improvement.
- [ ] **D4.30** — `slotting-approach.md` CRR table: Default category shows "0%" without EL annotation. B31 table says "0% (EL)". Inconsistent annotation — add EL context to CRR table too.

---

## Completed

_No items completed yet._

---

## Notes

- Equity haircut values (20%/30%) confirmed correct against PRA PS1/26 Art. 224 Table 3 (10-day liquidation period). BCBS CRE22.53 values are 25%/35% — skill references used BCBS values in error.
- Corporate CQS 5 = 150% confirmed from PRA PS1/26 Art. 122 Table 6. BCBS CRE20.42 reduced to 100% but PRA did not adopt.
- PRA output floor transitional schedule: 4-year (60/65/70/72.5%, 2027-2030), not BCBS 6-year.
- PRA slotting pre-op PF: no separate table (uses standard non-HVCRE), not BCBS CRE33 elevated weights.
- Cross-references to `IMPLEMENTATION_PLAN.md` items noted where doc issues overlap with code issues (P4.x series).
- PRA deviation from BCBS on CRE income-producing: PRA Art. 124I uses <=80%: 100%, >80%: 110%. BCBS uses <=60%: 70%, >60%-80%: 90%, >80%: 110%.
- Large FSE threshold for FI scalar: confirmed from PRA definitions (page 78) — applies to financial sector entities, not large non-financial corporates.
- Art. 128 (high-risk 150%) is confirmed active in PRA PS1/26 (page 59, paras 1 and 3); para 2 left blank. Status in pre-2027 UK CRR requires separate verification.
- D4.8 flagged for review: CQS 4 govt bond haircut row appears present in current version of `credit-risk-mitigation.md`.
