# Implementation Plan

**Last updated:** 2026-04-08 (P3.4 CMS1/CMS2 output floor comparison templates implemented)
**Current version:** 0.1.165 | **Test suite:** 4,687 passed, 21 skipped | P1.3, P1.4, P1.5, P1.6, P1.7, P1.8, P1.11, P1.12, P1.13, P1.14, P1.15, P1.16, P1.17, P1.18, P1.19, P1.20, P1.23, P1.26, P1.27, P1.28, P1.29, P1.30b, P1.30c, P1.30d, P1.31, P1.32, P1.34, P1.35, P1.37, P1.38a, P1.38b, P1.39, P1.40, P1.41, P1.44, P1.48, P1.49, P1.50, P1.59, P1.60, P1.61, P1.62, P1.64, P1.65, P1.67, P1.70, P1.71, P1.73, P1.74, P1.78, P1.81, P1.82, P1.83, P1.84, P1.85, P1.86, P1.87, P1.88, P1.9a, P2.2a, P2.2b, P2.2c, P2.2d, P2.4, P2.10, P3.1, P3.4, P4.1, P4.5, P4.13, P4.14, P4.15, P5.1, P5.4, P5.6, P5.7, P5.8, P5.9, P5.10, P6.1, P6.2, P6.3, P6.4, P6.5, P6.6, P6.10, P6.11, P6.12, P6.13, P6.14, P6.16, P6.18, P6.19, P6.17, P6.20 fixed.
**CRR acceptance:** 100% (133 tests) | **Basel 3.1 acceptance:** 100% (212 tests) | **Comparison:** 100% (60 tests)
**Acceptance tests skipped at runtime:** 0 (was ~12; slotting fixture ratings added)
**Environment note:** Tests running on Python 3.14.3 with polars. Ruff binary unavailable in sandbox (exec format error).
**Test corrections in 0.1.64 increment (2026-04-06):** Pre-existing test expectations were corrected for P1.1 (retail_mortgage 0.05%→0.10%, retail_qrre_transactor 0.03%→0.05%), P1.33 (mortgage RW floor 15%→10%), P1.46 (CQS 5 corporate RW 100%→150%), and CIU fallback (tests expected 1250% but code correctly implements 150% per CRR Art. 132(2); the 1250% deduction treatment, if needed, must be tracked separately). Test count increased from ~2,283 to ~2,344.

**Gap summary:** P1 (calculation correctness): 88 items total (3 open: P1.10, P1.30(e), P1.38(c)) | P2 (COREP): 11 (P2.2a/P2.2b/P2.2c/P2.2d/P2.4/P2.10/P2.11 complete) | P3 (Pillar III): 4 (P3.1/P3.4 complete) | P4 (docs): 20 | P5 (tests): 9 (P5.1/P5.4/P5.5 resolved) | P6 (code quality): 20 (P6.7/P6.11 now complete) | P7 (future): 4
**Critical items by impact type:**
- *Capital understatement (exposures get lower RWA than they should):* [P1.56, P1.55, P1.54, P1.53, P1.52, P1.46, P1.42, P1.51, P1.66, P1.79, P1.24, P1.25, P1.45, P1.69, P1.16, P1.2 (QRRE 50% vs 25%, retail_other 30% vs 25%) now fixed/verified; P1.85 (PMA sequencing now fixed); P1.86 (unrated covered bond Art. 129(5) derivation now wired); P1.87 (blended retail LGD floor now implemented)]
- *Capital overstatement (conservative but wrong):* [P1.36, P1.33, P1.22, P1.72, P1.80, P1.32, P1.71, P1.2 (retail_mortgage 5% vs 25% previously applied) now fixed/verified; P1.48 defaulted secured/unsecured split now fixed; P1.83 Art. 159(1) Pool B AVAs now fixed]
- *CRM formula/value errors:* [P1.69 receivables haircut fixed — B31 corrected from 20% to 40%; CRR kept at 20% as C*/C** approximation; P1.77 sequential fill now implemented; P1.70 per-type overcollateralisation threshold now fixed; P1.81 two-branch EL shortfall/excess now fixed; P1.41 CDS restructuring exclusion haircut now implemented; P1.40 Art. 237(2) maturity mismatch ineligibility now implemented; P1.73 B31 gold haircut corrected from 15% to 20% now fixed; P1.74 B31 equity main-index/other haircuts corrected to 20%/30% now fixed; P1.39 liquidation period haircut scaling (5/10/20-day) now implemented; P1.78 FX mismatch on guarantees now fixed; P1.75 LGD* formula single-LGD not blended now fixed; P1.76 bond haircut 3 bands vs 5 now fixed]
- *Needs regulatory verification:* [P1.71 now fixed — was 1.5x-4x capital overstatement for CRR equity]
- *Missing B31 features (whole categories absent):* P1.9 (output floor: OF-ADJ (a) fixed; (d) fixed), P1.30 (CRM method selection: (a)(b)(c)(d)(f) complete; (e) Art. 234 tranching remains), P1.39 (liquidation period scaling now fixed) [P1.7 Financial Collateral Simple Method now fixed] [P1.12 SCRA enhanced/short-term now fixed] [P1.29 40% CCF now fixed] [P1.38(a) GCRA cap now fixed; (b) entity-type carve-outs now fixed; (c) reporting basis remains] [P1.14 Other RE Art. 124J now fixed] [P1.6 Junior charges Art. 124F(2)/G(2)/I(3)/L now fixed] [P1.67 SA SL classification now fixed] [P1.65 SA Table A1 Row 2 FRC 100% CCF now fixed]
- *Other critical:* [P1.43, P1.47 now fixed]

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
- **Status:** [~] Partial ((a) and (b) complete; (c) remains)
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
  - **(c) Reporting basis (Rule 2.2A):** Output floor reporting must be on the same basis as Art. 92 para 3A — not always individual basis. Ring-fenced bodies report sub-consolidated; international subsidiaries do not report at all. Not yet implemented.
- **File:Line:** `domain/enums.py` (InstitutionType, ReportingBasis), `contracts/config.py` (OutputFloorConfig.is_floor_applicable, CalculationConfig.basel_3_1), `engine/aggregator/aggregator.py` (is_floor_applicable check)
- **Spec ref:** PRA PS1/26 Art. 92 para 2A(a)-(d), Reporting (CRR) Part Rule 2.2A
- **Tests:** 50 new unit tests in `tests/unit/test_output_floor_entity_type.py`: 18 is_floor_applicable unit tests (CRR, B31 default, None params backward compat, 3 applicable combos, 3 exempt combos, 6 wrong-basis combos), 4 CalculationConfig integration tests, 10 end-to-end aggregator tests (exempt entities keep original RWA, applicable entities get floored, backward compat), 15 parametrized exhaustive all-combinations test, 4 enum value tests. All 3057 tests pass. Test count: 3057 (was 3007).
- **Fix remaining:** (c) Add reporting basis conditionality to COREP output.

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

---

## Priority 2 -- COREP Reporting Completeness

### P2.1 COREP template rework -- structure alignment
- **Status:** [~] Needs rework
- **Impact:** Current COREP generator (`reporting/corep/generator.py`) uses simplified column sets and one-row-per-class structure. Only C 07.00, C 08.01, C 08.02 (and their OF variants) are implemented. Full-width CRR/B31 column definitions exist in `templates.py` (lines 1-651) but generator uses backward-compatibility aliases. Specific sub-gaps:
  - C 08.01 col `0120` ("Of which: off balance sheet") permanently null (`generator.py:1289-1290`)
  - B31 OF 08.02 missing columns `0001` and `0101-0105` (per-grade CCF breakdown) (`templates.py:646-651`)
  - B31 C 08.01 off-BS CCF sub-rows `0031-0035` always null (`generator.py:521`)
  - C 07.00 B31 CIU sub-rows `0284/0285` defined in `templates.py:348-353` but never populated by generator
  - Equity transitional rows `0371-0374` and currency mismatch row `0380` null due to missing pipeline columns (`equity_transitional_approach`, `currency_mismatch_multiplier_applied`)
  - B31 slotting FCCM cols `0101-0104` in C 08.01 always null (`generator.py:1281-1283`)
  - Dead backward-compatibility aliases (`C07_COLUMNS`, `C08_01_COLUMNS`, `C08_02_COLUMNS`) at `templates.py:661-689` still exported but unused
  **Additional from PDF comparison:** OF 07.00 has 22 columns in spec vs ~29 actual (missing cols 0230/0235/0240 ECAI breakdown, col 0235 "ECAI not available" new in B31). OF 09.02 has 15 cols in spec vs 13 actual (missing col 0107 defaulted EV; remove SF cols). OF 08.01 missing cols 0254 (unrecognised exposure adjustments, NOT PD floors), 0265, 0282 (total post-adjustment EL, NOT PD/LGD floors); col 0280 renamed. OF 02.00 needs rows 0034 (Yes/No indicator), 0035 (multiplier %), 0036 (monetary OF-ADJ). OF 08.06 CRR risk weight column 0070 removed in B3.1; col 0031 FCCM is a deduction column. OF 08.07 cols 0160-0180 require consolidated-basis-only reporting. OF 09.01 missing col 0061 (additional value adjustments).
- **File:Line:** `reporting/corep/generator.py`, `reporting/corep/templates.py`
- **Fix:** Migrate generator to use full template definitions. Rework row/column logic. Add missing pipeline columns for equity transitional and currency mismatch reporting. Remove dead alias objects. Correct column counts per PDF comparison.
- **Tests needed:** Rewrite COREP tests (~250 tests in `tests/unit/test_corep.py`).

### P2.2 COREP templates C 02.00, C 08.03-08.07, OF 02.01
- **Status:** [~] Partial (OF 02.01, C 08.03, C 08.06, and C 08.07 complete; remaining templates not started)
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
- **C 08.06 / OF 08.06 — COMPLETE (2026-04-08):** IRB specialised lending slotting template implemented. One DataFrame per SL type. CRR: 4 SL types (PF, IPRE+HVCRE combined, OF, CF), 12 rows (5 categories × 2 maturity bands + 2 totals), 10 columns. Basel 3.1: 5 SL types (HVCRE separated from IPRE), 14 rows (adds "substantially stronger" sub-rows 0015/0025), 11 columns (adds col 0031 FCCM deduction; supporting factors removed from RWEA label). Template definitions: `CRR_C08_06_COLUMNS` / `B31_C08_06_COLUMNS`, `CRR_C08_06_ROWS` / `B31_C08_06_ROWS`, `CRR_SL_TYPES` / `B31_SL_TYPES`, `C08_06_CATEGORY_MAP`, `C08_06_COLUMN_REFS`, `get_c08_06_columns()`, `get_c08_06_rows()`, `get_c08_06_sl_types()`. Generator methods: `_generate_all_c08_06()` and `_generate_c08_06_for_type()` with `_compute_c08_06_values()` helper. `COREPTemplateBundle.c08_06` field (dict[str, pl.DataFrame]). Excel export via `_write_template_sheets()` with SL type display names. Known gaps: col 0031 FCCM is null (pipeline FCCM for slotting not yet wired); "substantially stronger" sub-rows (0015/0025) are zero (pipeline has no `is_substantially_stronger` flag). 65 new tests across 7 test classes (TestC0806TemplateDefinitions: 19, TestC0806Generation: 8, TestC0806RowAssignment: 8, TestC0806ColumnValues: 12, TestC0806B31Features: 9, TestC0806SupportingFactors: 2, TestC0806EdgeCases: 7). All 4,482 tests pass (was 4,417). COREP tests: 427 (was 362).
- **C 08.07 / OF 08.07 — COMPLETE (2026-04-08):** IRB scope of use template implemented. Shows per-class split between SA and IRB approaches with coverage percentages. CRR: 5 columns (exposure values + coverage %) × 17 rows (Art. 147(2) exposure classes). Basel 3.1: 18 columns (adds RWEA decomposition cols 0060-0150 by SA-use reason, materiality cols 0160-0180) × 11 rows (Art. 147B roll-out classes + materiality). Template definitions: `CRR_C08_07_COLUMNS` / `B31_C08_07_COLUMNS`, `CRR_C08_07_ROWS` / `B31_C08_07_ROWS`, `C08_07_COLUMN_REFS` / `B31_C08_07_COLUMN_REFS`, `C08_07_IRB_APPROACHES`, `C08_07_CRR_RETAIL_CLASSES`, `get_c08_07_columns()`, `get_c08_07_rows()`. Generator method: `_generate_c08_07()` with `_compute_c08_07_values()` helper. `COREPTemplateBundle.c08_07` field (single DataFrame, not per-class). Excel export via `_write_single_template_sheet()` with framework-aware sheet name (C 08.07 for CRR, OF 08.07 for B31). Known gaps: SA RWEA breakdown (cols 0070-0130) reports all SA RWEA in "other" (col 0140) — requires `sa_use_reason` pipeline column for per-reason split. Materiality columns (0160-0180) null — requires institutional-level configuration. CRR sub-rows without direct exposure class mapping (0060 SL excl. slotting, 0100/0130 SME retail) report null. 51 new tests across 5 test classes (TestC0807TemplateDefinitions: 17, TestC0807Generation: 8, TestC0807ColumnValues: 12, TestC0807B31Features: 8, TestC0807EdgeCases: 6). All 4,533 tests pass (was 4,482). COREP tests: 478 (was 427).
- **Fix remaining:** Add C 02.00, C 08.04-08.05 template definitions and generator methods. Add C 08.05/OF 08.05/OF 08.05.1/OF 34.07 to `docs/features/corep-reporting.md`.

### P2.3 COREP C 09.01-09.02 (Geographical Breakdown)
- **Status:** [ ] May require `country_of_exposure` field not in schema
- **Fix:** Add field if missing. Add template definitions and generator methods.

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
- **Status:** [ ] Missing RE sub-classification and many other row IDs
- **Impact:** Multiple templates have missing row IDs beyond just "other real estate":
  - OF 02.00: Missing rows 0271/0290/0295-0297 (FIRB breakdown), 0355-0356 (AIRB corporate), 0382-0385 (AIRB retail), 0411-0416 (slotting by 5 SL types), 0034-0036 (floor indicator/multiplier/OF-ADJ — different data types: Yes/No, %, monetary)
  - OF 07.00: Missing IDs for rows 0021-0026 (SL sub-types, hierarchical under PF), 0331-0344 (RE sub-types incl. SME sub-rows 0343/0344), 0351-0354 (other RE sub-breakdown), 0371-0374 (equity transitional, expire 1 Jan 2030), 0380 (currency mismatch)
  - OF 08.01: Missing rows 0017 (revolving loan commitments), 0031-0035 (off-BS CCF sub-rows), 0175 (purchased receivables), 0180 (dilution risk), 0190 (ECAI not available), 0200 (investment grade)
  - OF 08.07: Missing row IDs 0180-0250 (roll-out classes per Art. 147B, not exposure classes), 0260 (total), 0270 (aggregate immateriality %)
  - OF 09.01: Missing row IDs 0071-0073 (SL), 0091-0094 (RE), 0170 (total)
  - OF 09.02: Missing rows 0042/0045 (SL excl/incl slotting), 0048 (financial/large corp), 0049 (purchased receivables, NOT SME), 0050/0055 (SME/non-SME), 0071-0074 (retail RE SME/non-SME), 0100 (QRRE), 0105 (purchased receivables retail), 0120/0130 (other SME/non-SME), 0150 (total); equity rows removed
  - COREP rows 0350-0354 ("other real estate") blocked by missing RE sub-classification (P1.14)
- **File:Line:** `reporting/corep/templates.py`, `reporting/corep/generator.py:663`
- **Fix:** Add RE sub-classification to classifier. Add all missing row IDs to template definitions. Populate rows from pipeline data.

### P2.6 COREP CCR rows (0090-0130 in C 07.00, CCR section in C 08.01)
- **Status:** [ ] Not implemented (CCR engine out of scope)
- **Decision needed:** Accept null CCR rows as out-of-scope, or add placeholder documentation.

### P2.7 COREP pre-credit-derivative RWEA approximation (row 0310)
- **Status:** [~] Lower-bound approximation
- **Impact:** `generator.py:1460-1472` approximates pre-CD RWEA as total RWEA. Without per-exposure pre/post tracking for credit-derivative substitution benefit, the regulatory split cannot be accurately reported.
- **File:Line:** `reporting/corep/generator.py:1460-1472`
- **Fix:** Track pre-CD and post-CD RWEA in the CRM/IRB pipeline.

### P2.8 COREP memorandum rows (0300, 0320)
- **Status:** [ ] Not implemented (confirmed at `generator.py:411`)
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

### P3.2 UKB CR9 / CR9.1 (PD back-testing) missing from spec and plan
- **Status:** [ ] Not in spec -- mandatory Basel 3.1 template
- **Impact:** PRA PS1/26 Annex XXII defines **UKB CR9** (PD back-testing per exposure class, 8 columns: (a) exposure class/PD range, (b) PD range (fixed), (c) obligors at end of previous year, (d) of which defaulted, (e) observed average default rate, (f) exposure-weighted avg PD (cross-ref CR6 col f), (g) avg PD at disclosure date (includes PD floors), (h) avg historical annual default rate (5-year simple average)). **UKB CR9.1** (supplementary back-testing for Art. 180(1)(f) ECAI mapping) adds one column per ECAI showing external rating to which internal PD ranges are mapped. These are mandatory under Art. 452(h).
  **Key distinction:** CR9 col (b) allocates exposures by PD estimated at **beginning of the disclosure period** — contrast with CR6 col (a) which uses **pre-PD input floor** PD. This temporal difference is critical for backtesting accuracy.
  Neither template is in `docs/features/pillar3-disclosures.md` or `docs/specifications/output-reporting.md`. Note: `output-reporting.md` lists `OF 08.05` / `OF 08.05.1` in "Missing Templates" — these are the COREP equivalents, not the Pillar III templates (UKB CR9 / CR9.1). They must be listed separately.
- **Spec ref:** PRA PS1/26 Annex XXII pages 18-22
- **Fix:** Add CR9 and CR9.1 template definitions to `docs/features/pillar3-disclosures.md`. Include in P3.1 implementation scope. Note: CR9 requires historical default rate data (5-year lookback) not currently in the pipeline.
- **Tests needed:** Unit tests for CR9/CR9.1 templates.

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
- **Status:** [~] Mostly complete (2026-04-08 — one remaining file)
- **Impact:** `technical-reference.md` shows retail mortgage PD floor as 0.05% -- should be **0.10%** per PRA Art. 163(1)(b). The `key-differences.md` table correctly shows 0.10%. Code also wrong (P1.1).
- **Fix:** Fixed retail mortgage PD floor 0.05%→0.10% (Art. 163(1)(b)) and QRRE transactor 0.03%→0.05% (Art. 163(1)(c)) in technical-reference.md, basel31.md. Fixed PDFloors docstring in config.py. key-differences.md already had correct values.
- **Remaining:** `docs/api/configuration.md` lines 161 and 185 still show QRRE transactor PD floor as 0.03% (should be 0.05% per Art. 163(1)(c)). Code in `config.py:98` correctly uses 0.05%.

### P4.6 LGD floor documentation discrepancy
- **Status:** [~] Docs inconsistent with PRA
- **Impact:** `technical-reference.md` and `key-differences.md` list retail RRE LGD floor as 5% (correct per Art. 164(4)(a)), but code uses 10% (same as corporate). The footnote "Values reflect PRA PS1/26 implementation" is incorrect for the retail entry.
- **Fix:** Update docs to clarify corporate vs retail LGD floor distinction. Fix code per P1.2.

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
- **Fix:** Remove remaining BCBS-only CQS speculative concepts from PRA spec.

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
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `key-differences.md` claims "Not Yet Implemented" for:
  - (a) Currency mismatch 1.5x multiplier -- implemented at `engine/sa/calculator.py:900-966`
  - (b) SA Specialised Lending Art. 122A-122B -- implemented at `engine/sa/calculator.py:528-533`
  - (c) Provision-coverage-based defaulted treatment CRE20.87-90 -- implemented at `engine/sa/calculator.py:451-461`
- **Fix:** `key-differences.md` now correctly shows currency mismatch, SA specialised lending, and provision-based defaulted treatment as implemented. All three features confirmed complete with file/line references.

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
- **Status:** [~] Partially fixed (2026-04-08)
- **Impact:** Multiple doc files had wrong Basel 3.1 supervisory haircut values: main index equities 25%→20%, other equities 35%→30%, gold 15%→20%. Fixed in technical-reference.md, key-differences.md, basel31.md, regulatory-tables.md, input-schemas.md. ~10 secondary doc files still reference BCBS 6-year output floor schedule (2032, 50%): framework-comparison/index.md, reporting-differences.md, appendix/index.md, api/contracts.md, api/engine.md, plans/prd.md, plans/implementation-plan.md, specifications/index.md, features/index.md, framework-comparison/impact-analysis.md.
- **Fix remaining:** Update remaining ~10 secondary doc files with PRA 4-year schedule values.

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
- **Status:** [~] Pre-existing errors
- **Fix:** Fix or regenerate affected fixtures.

### P5.3 CRR CRM guarantee/provision test placeholders
- **Status:** [~] Documented as placeholders
- **Fix:** Audit and expand test coverage.

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
- **Status:** [~] Spec tracking field not surfaced
- **Impact:** Spec requires `guarantor_rating_type` in cross-approach CCF substitution output. CRM audit at `processor.py:789-796` includes `guarantor_approach` but not rating type (external CQS vs internal PD).
- **Fix:** Add `guarantor_rating_type` column to CRM audit trail.

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

---

## Completed Items (Reference)

These items are verified complete. Items with **[!]** have known gaps documented in P1/P2:

**P1 items complete (moved from active section):** P1.1, P1.2, P1.3, P1.4, P1.5, P1.6, P1.7, P1.8, P1.9a, P1.9d, P1.11, P1.12, P1.13, P1.14, P1.15, P1.16, P1.17, P1.18, P1.19, P1.20, P1.21, P1.22, P1.23, P1.24, P1.25, P1.26, P1.27, P1.28, P1.29, P1.31, P1.32, P1.33, P1.34, P1.35, P1.36, P1.37, P1.39, P1.40, P1.41, P1.42, P1.43, P1.44, P1.45, P1.46, P1.47, P1.48, P1.49, P1.50, P1.51, P1.52, P1.53, P1.54, P1.55, P1.56, P1.59, P1.60, P1.61, P1.62, P1.63, P1.64, P1.65, P1.66, P1.67, P1.68, P1.69, P1.70, P1.71, P1.72, P1.73, P1.74, P1.75, P1.76, P1.77, P1.78, P1.79, P1.80, P1.81, P1.82, P1.83, P1.84, P1.85, P1.86, P1.87

**P4 items complete:** P4.1, P4.5, P4.7, P4.13, P4.14, P4.15, P4.16, P4.17, P4.18, P4.19, P4.21

**P5 items complete:** P5.1, P5.4, P5.5, P5.6, P5.7, P5.8, P5.9, P5.10

- [x] All 8 pipeline stages (loader, hierarchy, classifier, CRM, SA/IRB/slotting/equity, aggregator)
- [x] **[!]** CRR SA risk weights (core classes: sovereign, institution, corporate, retail, RE, defaulted, equity; PSE/RGLA/MDB/Int.Org/Other Items pending -- see P1.52-P1.55)
- [x] **[!]** Basel 3.1 SA risk weights (residential/commercial RE loan-splitting, ECRA/SCRA, corporate sub-categories, ADC, equity transitional; SCRA enhanced sub-grade/short-term missing -- see P1.12, P1.26; equity B31 weights now implemented -- see P1.42 [fixed])
- [x] Basel 3.1 SA specialised lending (Art. 122A-122B) -- OF/CF=100%, PF pre-op=130%, PF op=100%, PF high-quality=80%
- [x] Basel 3.1 provision-coverage-based defaulted treatment (CRE20.87-90) -- 100% RW / 150% RW; threshold 20%, denominator EAD only -- see P1.51 [fixed]
- [x] Currency mismatch 1.5x RW multiplier (Art. 123B / CRE20.93) -- Basel 3.1 only, retail + RE classes
- [x] F-IRB calculation (supervisory LGD, PD floors, correlation, maturity adjustment, FI scalar)
- [x] A-IRB calculation (own LGD/CCF, LGD floors, post-model adjustments; mortgage RW floor 10% -- see P1.33 [fixed])
- [x] Slotting (CRR 4 tables + Basel 3.1 3 tables + subgrades)
- [x] **[!]** Equity (SA Art. 133, IRB Simple Art. 155, CIU fallback 250%; CIU look-through/mandate partial -- see P1.61; B31 equity SA weights implemented -- see P1.42 [fixed]; transitional floor applied in pipeline -- see P1.43 [fixed]; subordinated debt 150% + transitional floor exclusion -- P1.59 [fixed])
- [x] **[!]** CRM (collateral haircuts CRR 3-band + Basel 3.1 5-band, FX mismatch, maturity mismatch, multi-level allocation, guarantee substitution, netting, provisions, Art. 232 life insurance method, Art. 218 CLN-as-cash; gold haircut wrong -- P1.73; LGD* formula doesn't blend -- P1.75; P1.77 sequential fill fixed; P1.70 per-type OC threshold fixed; see also P1.7, P1.11, P1.30, P1.39-P1.41, P1.56)
- [x] Basel 3.1 parameter substitution (CRE22.70-85) -- including EL adjustment for guaranteed portion
- [x] Double default (CRR Art. 153(3), Art. 202-203)
- [x] **[!]** Output floor with PRA transitional schedule (60%/65%/70%/72.5%) -- exposure-level only, not portfolio-level; OF-ADJ/U-TREA/S-TREA missing -- see P1.9
- [x] Supporting factors (CRR SME + infrastructure, removed under Basel 3.1)
- [x] **[!]** CCF (SA/FIRB/AIRB, Basel 3.1 UCC changes; F-IRB B31 CCF now uses SA CCFs -- P1.36 [fixed]; A-IRB revolving gate missing -- P1.3; 40% CCF category missing -- P1.29)
- [x] Provisions (multi-level, SA drawn-first deduction, IRB EL comparison, T2 credit cap)
- [x] Dual-framework comparison (DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner)
- [x] COREP C 07.00 / C 08.01 / C 08.02 / C 08.03 / C 08.06 / C 08.07 (basic structure, CRR + Basel 3.1 OF variants); OF 02.01 output floor comparison template (P2.2a/P2.2b/P2.2c/P2.2d complete; P2.4/P2.10/P2.11 complete)
- [x] API (CreditRiskCalc, export to Parquet/CSV/Excel, results cache)
- [x] Model permissions (per-model FIRB/AIRB/slotting, fallback to SA)
- [x] Marimo UI (RWA app, comparison app, template workbench, landing page)
- [x] Schema validation, bundle validation, column value constraints
- [x] FX conversion (multi-currency support)
- [x] Materialisation barriers (CPU + streaming modes)
