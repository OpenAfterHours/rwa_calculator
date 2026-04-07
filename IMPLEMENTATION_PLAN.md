# Implementation Plan

**Last updated:** 2026-04-07 (P5.10 B31 defaulted acceptance tests)
**Current version:** 0.1.142 | **Test suite:** 3,927 passed, 33 skipped | P1.3, P1.4, P1.5, P1.6, P1.7, P1.8, P1.11, P1.12, P1.13, P1.14, P1.15, P1.16, P1.17, P1.18, P1.19, P1.20, P1.23, P1.26, P1.27, P1.28, P1.29, P1.30b, P1.30c, P1.30d, P1.31, P1.32, P1.34, P1.35, P1.37, P1.38a, P1.38b, P1.39, P1.40, P1.41, P1.44, P1.48, P1.50, P1.59, P1.60, P1.61, P1.62, P1.64, P1.65, P1.67, P1.70, P1.71, P1.73, P1.74, P1.78, P1.81, P1.82, P1.83, P1.84, P1.85, P1.86, P1.87, P1.9a, P5.6, P5.10, P6.1, P6.5, P6.10, P6.12, P6.14, P6.16, P6.18, P6.19, P6.17 fixed.
**CRR acceptance:** 100% (101 tests) | **Basel 3.1 acceptance:** 100% (147 tests) | **Comparison:** 100% (60 tests)
**Acceptance tests skipped at runtime:** ~90 (conditional `pytest.skip()` when fixture data unavailable)
**Environment note:** Tests running on Python 3.14.3 with polars. Ruff binary unavailable in sandbox (exec format error).
**Test corrections in 0.1.64 increment (2026-04-06):** Pre-existing test expectations were corrected for P1.1 (retail_mortgage 0.05%→0.10%, retail_qrre_transactor 0.03%→0.05%), P1.33 (mortgage RW floor 15%→10%), P1.46 (CQS 5 corporate RW 100%→150%), and CIU fallback (tests expected 1250% but code correctly implements 150% per CRR Art. 132(2); the 1250% deduction treatment, if needed, must be tracked separately). Test count increased from ~2,283 to ~2,344.

**Gap summary:** P1 (calculation correctness): 77 (+P1.9a sub-item, +P1.86; P1.5, P1.47 fixed, P1.62 fixed, P1.66/P1.79 closed as false positives, P1.19 implemented, P1.82 closed as false positive, P1.67 SA SL classification now fixed, P1.65 FRC 100% CCF now fixed, P1.83 Art. 159(1) Pool B AVAs now fixed, P1.9a OF-ADJ now fixed) | P2 (COREP): 11 | P3 (Pillar III): 4 | P4 (docs): 21 | P5 (tests): 10 | P6 (code quality): 20 | P7 (future): 4
**Critical items by impact type:**
- *Capital understatement (exposures get lower RWA than they should):* [P1.56, P1.55, P1.54, P1.53, P1.52, P1.46, P1.42, P1.51, P1.66, P1.79, P1.24, P1.25, P1.45, P1.69, P1.16, P1.2 (QRRE 50% vs 25%, retail_other 30% vs 25%) now fixed/verified; P1.85 (PMA sequencing now fixed); P1.86 (unrated covered bond Art. 129(5) derivation now wired); P1.87 (blended retail LGD floor now implemented)]
- *Capital overstatement (conservative but wrong):* [P1.36, P1.33, P1.22, P1.72, P1.80, P1.32, P1.71, P1.2 (retail_mortgage 5% vs 25% previously applied) now fixed/verified; P1.48 defaulted secured/unsecured split now fixed; P1.83 Art. 159(1) Pool B AVAs now fixed]
- *CRM formula/value errors:* [P1.69 receivables haircut fixed — B31 corrected from 20% to 40%; CRR kept at 20% as C*/C** approximation; P1.77 sequential fill now implemented; P1.70 per-type overcollateralisation threshold now fixed; P1.81 two-branch EL shortfall/excess now fixed; P1.41 CDS restructuring exclusion haircut now implemented; P1.40 Art. 237(2) maturity mismatch ineligibility now implemented; P1.73 B31 gold haircut corrected from 15% to 20% now fixed; P1.74 B31 equity main-index/other haircuts corrected to 20%/30% now fixed; P1.39 liquidation period haircut scaling (5/10/20-day) now implemented; P1.78 FX mismatch on guarantees now fixed] P1.75 (LGD* formula single-LGD not blended), P1.76 (bond haircut 3 bands vs 5)
- *Needs regulatory verification:* [P1.71 now fixed — was 1.5x-4x capital overstatement for CRR equity]
- *Missing B31 features (whole categories absent):* P1.9 (output floor: OF-ADJ (a) fixed; (d) documentation remains), P1.30 (CRM method selection: (a)(b)(c)(d)(f) complete; (e) Art. 234 tranching remains), P1.39 (liquidation period scaling now fixed) [P1.7 Financial Collateral Simple Method now fixed] [P1.12 SCRA enhanced/short-term now fixed] [P1.29 40% CCF now fixed] [P1.38(a) GCRA cap now fixed; (b) entity-type carve-outs now fixed; (c) reporting basis remains] [P1.14 Other RE Art. 124J now fixed] [P1.6 Junior charges Art. 124F(2)/G(2)/I(3)/L now fixed] [P1.67 SA SL classification now fixed] [P1.65 SA Table A1 Row 2 FRC 100% CCF now fixed]
- *Other critical:* [P1.43, P1.47 now fixed]

## Status Legend
- [ ] Not started
- [~] Partial / needs rework
- [x] Complete

---

## Priority 1 -- Calculation Correctness Gaps

These items affect regulatory calculation accuracy under CRR or Basel 3.1.

### P1.36 **CRITICAL** -- F-IRB CCF under Basel 3.1 uses wrong values (Art. 166C)
- **Status:** [x] Complete (2026-04-06)

### P1.46 Corporate CQS 5 risk weight 100% in code, PRA PS1/26 says 150% (Art. 122(2))
- **Status:** [x] Complete (2026-04-06)

### P1.51 B31 defaulted provision threshold 20% not 50% AND denominator wrong (Art. 127)
- **Status:** [x] Complete (2026-04-06)

### P1.42 Basel 3.1 equity SA weights wrong -- listed equity gets 100% instead of 250%
- **Status:** [x] Complete (2026-04-06)

### P1.43 Equity `get_equity_result_bundle` skips transitional floor (bug)
- **Status:** [x] Complete (2026-04-06)

### P1.47 Slotting PF pre-operational table uses BCBS values not in PRA PS1/26
- **Status:** [x] Complete (2026-04-06)

### P1.52 PSE risk weight tables missing from code (Art. 116)
- **Status:** [x] Complete (2026-04-06)

### P1.53 RGLA risk weight tables missing from code (Art. 115)
- **Status:** [x] Complete (2026-04-06)

### P1.54 MDB 0% risk weight lookup missing from code (Art. 117-118)
- **Status:** [x] Complete (2026-04-06)

### P1.56 CQS 5-6 bond ineligibility + CQS 4 government bond eligibility (Art. 197)
- **Status:** [x] Complete (2026-04-06)

### P1.1 PD floor values incorrect for Basel 3.1 (PRA Art. 160/163)
- **Status:** [x] Complete (2026-04-06)

### P1.2 Retail LGD floors missing (PRA Art. 164(4))
- **Status:** [x] Complete (2026-04-06)

### P1.3 A-IRB CCF revolving restriction (Art. 166D(1)(a))
- **Status:** [x] Complete (2026-04-06)

### P1.4 Basel 3.1 approach restrictions not enforced (Art. 147A)
- **Status:** [x] Complete (2026-04-06)

### P1.5 IRB guarantor PD substitution for expected loss (CRR path)
- **Status:** [x] Complete (2026-04-06)

### P1.6 Junior charges for residential RE loan-splitting (Art. 124F(2))
- **Status:** [x] Complete (2026-04-07)

### P1.7 Financial Collateral Simple Method (Art. 222)
- **Status:** [x] Complete (2026-04-07)

### P1.8 LGDFloors residential vs commercial RE distinction
- **Status:** [x] Complete (2026-04-07)

### P1.9 Output Floor -- OF-ADJ, portfolio-level application, U-TREA/S-TREA
- **Status:** [~] Partial (2 sub-issues remain; (a) and (b) complete)
- **Fixed (a) and (b):** 2026-04-07
- **Impact:** The output floor implementation has four related gaps:
  - **(a) OF-ADJ implemented:** FIXED (2026-04-07). OF-ADJ = 12.5 × (IRB_T2 - IRB_CET1 - GCRA + SA_T2) now computed and applied to the floor formula. IRB_T2 (Art. 62(d) excess provisions, capped) and IRB_CET1 (Art. 36(1)(d) shortfall + Art. 40 supervisory add-on) are derived from the internal EL summary. GCRA (general credit risk adjustments, capped at 1.25% of S-TREA per Art. 92 para 2A) and SA_T2 (Art. 62(c) SA T2 credit) are institution-level config inputs on `OutputFloorConfig`. `compute_of_adj()` function exported from `_floor.py`. EL summary now computed BEFORE the output floor in the aggregator (was after). `OutputFloorSummary` extended with `of_adj`, `irb_t2_credit`, `irb_cet1_deduction`, `gcra_amount`, `sa_t2_credit` fields. `CalculationConfig.basel_3_1()` accepts `gcra_amount`, `sa_t2_credit`, `art_40_deductions` params. 28 new unit tests in `tests/unit/test_of_adj.py`.
  - **(b) Floor is exposure-level, not portfolio-level:** FIXED. Previously `_floor.py` applied `max(rwa_pre_floor, floor_rwa)` per exposure row, systematically overstating capital. Now computes portfolio-level U-TREA and S-TREA, applies `TREA = max(U-TREA, x * S-TREA)`, and distributes any shortfall pro-rata by `sa_rwa` share. Slotting exposures now included in floor scope via `FLOOR_ELIGIBLE_APPROACHES` (were previously excluded). `OutputFloorSummary` dataclass added to `contracts/bundles.py` with `u_trea`, `s_trea`, `floor_pct`, `floor_threshold`, `shortfall`, `portfolio_floor_binding`, `total_rwa_post_floor` fields, and attached to `AggregatedResultBundle`.
  - **(c) U-TREA/S-TREA COREP export:** `OutputFloorSummary` is now on `AggregatedResultBundle` so U-TREA/S-TREA are accessible. Full `OF 02.01` COREP template wiring (4-column comparison) not yet done — tracked under P2.
  - **(d) Transitional floor rates are permissive, not mandatory:** Art. 92 para 5 says institutions "may apply" the 60/65/70% transitional rates — firms can voluntarily use 72.5% from day one. `OutputFloorConfig` should document this optionality.
- **File:Line:** `engine/aggregator/_floor.py`, `engine/aggregator/_schemas.py`, `engine/aggregator/aggregator.py`, `contracts/bundles.py`
- **Spec ref:** `docs/specifications/output-reporting.md` lines 28-46, PRA PS1/26 Art. 92 para 2A/3A/5
- **Fix remaining:** (d) Document optionality in `OutputFloorConfig`.
- **Tests:** 24 new unit tests in `tests/unit/test_portfolio_level_floor.py`. Acceptance test B31-F2 updated (`is_floor_binding` now portfolio-level flag). All tests pass.

### P1.9a EL T2 credit cap uses pre-floor IRB RWA
- **Status:** [x] False positive — pre-floor basis is correct
- **Verified:** 2026-04-07
- **Description:** The original claim that T2 cap should use post-floor RWA was incorrect. Art. 62(d) explicitly references "risk-weighted exposure amounts **calculated under Chapter 3 of Title II of Part Three**" — Chapter 3 is the IRB chapter, not the output floor (Art. 92(2A) is in Part Two). Using post-floor TREA would also create a circular dependency: OF-ADJ = f(IRB T2 credit) → T2 credit = f(T2 cap) → T2 cap = f(TREA) → TREA = f(OF-ADJ). PRA reporting instructions (Annex II, row 0160) confirm: "risk weighted exposure amounts calculated with the IRB Approach" — the IRB amounts, not TREA. The code is correct: `compute_el_portfolio_summary` receives pre-floor IRB/slotting frames. See P1.84 for the full analysis and 10 unit tests confirming this.
- **File:Line:** `engine/aggregator/_el_summary.py:229-232`, `engine/aggregator/aggregator.py:114-127`
- **Spec ref:** CRR Art. 62(d), PRA PS1/26 Art. 92(2A), PRA Annex II row 0160

### P1.10 Unfunded credit protection transitional (PRA Rule 4.11)
- **Status:** [ ] Not implemented (low priority — underlying eligibility checks not yet implemented)
- **Impact:** PRA PS1/26 Rule 4.11 is a **narrow eligibility-condition carve-out**, not a broad permission to use CRR calculation methods. During 1 Jan 2027 to 30 Jun 2028, it reads Art. 213(1)(c)(i) and Art. 183(1A)(b) with the words "or change" omitted for unfunded credit protection entered before 1 Jan 2027. This means legacy contracts that allow the provider to *change* (but not cancel) the protection remain eligible during the transitional window. All other Basel 3.1 CRM calculation changes (haircuts, method taxonomy, parameter substitution LGD) apply from day one regardless. The underlying eligibility checks (Art. 213(1)(c)(i) "change clause" check) are not yet implemented in the calculator, making this transitional provision currently moot.
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 Rule 4.11, Art. 213(1)(c)(i), Art. 183(1A)(b)
- **Fix:** Implement Art. 213 eligibility validation first (with "change clause" check). Then add `protection_inception_date` field and transitional date logic to relax the check for legacy contracts.
- **Tests needed:** Unit tests for eligibility validation + transitional date logic.

### P1.11 CRM maturity mismatch hardcoded exposure maturity (Art. 238)
- **Status:** [x] Complete (2026-04-06)

### P1.12 SCRA enhanced sub-grade and short-term maturity weights (Basel 3.1)
- **Status:** [x] Complete (2026-04-06)

### P1.13 CRE general "other counterparties" formula (Art. 124H)
- **Status:** [x] Complete (2026-04-07)

### P1.14 "Other Real Estate" exposure class (Art. 124J)
- **Status:** [x] Complete (2026-04-07)

### P1.15 Rated SA specialised lending fallback (Art. 122A(3))
- **Status:** [x] Complete (2026-04-06)

### P1.16 CRR unrated institution standard risk weight (Art. 120)
- **Status:** [x] Complete (2026-04-07)

### P1.17 Unrated covered bond derivation table not wired (CRR Art. 129)
- **Status:** [x] Complete (2026-04-06)

### P1.18 Defaulted RESI RE always-100% exception (Basel 3.1 Art. 127 / CRE20.88)
- **Status:** [x] Complete (2026-04-06)

### P1.19 Payroll/pension loan retail category (Basel 3.1 Art. 123)
- **Status:** [x] Complete (2026-04-06)

### P1.20 Revolving maturity change (Basel 3.1 Art. 162(2A)(k))
- **Status:** [x] Complete (2026-04-07)

### P1.21 A-IRB CCF floor enforcement (CRE32.27 -- 50% of SA CCF)
- **Status:** [x] Complete (2026-04-06)

### P1.22 IRB maturity default inconsistency (5.0 vs 2.5)
- **Status:** [x] Complete (2026-04-06)

### P1.23 Duplicated IRB defaulted treatment code
- **Status:** [x] Complete (2026-04-07)

### P1.24 Non-investment-grade corporate 135% risk weight (Art. 122(6)(b))
- **Status:** [x] Complete (2026-04-06)

### P1.25 Non-regulatory retail 100% risk weight (Art. 123(3)(c))
- **Status:** [x] Complete (2026-04-06)

### P1.26 Short-term institution ECRA/SCRA tables (Art. 120/121)
- **Status:** [x] Complete (2026-04-06)

### P1.27 Sovereign RW floor for FX unrated institution exposures (Art. 121(6))
- **Status:** [x] Complete (2026-04-07)

### P1.28 Output floor -- IRB corporate SA RW choice (Art. 122(8))
- **Status:** [x] Complete (2026-04-07)

### P1.29 Basel 3.1 SA "Other Commitments" 40% CCF category (Art. 111)
- **Status:** [x] Complete (2026-04-06)

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

### P1.31 SME supporting factor silent per-exposure fallback (CRR Art. 501)
- **Status:** [x] Complete (2026-04-07)

### P1.32 F-IRB supervisory LGD: FSE 45% vs non-FSE corporate 40% (Art. 161(1))
- **Status:** [x] Complete (2026-04-06)

### P1.33 Mortgage RW floor is 10%, not 15% (Art. 154(4A)(b))
- **Status:** [x] Complete (2026-04-06)

### P1.34 SME correlation adjustment uses EUR parameters under B31 (Art. 153(4))
- **Status:** [x] Complete (2026-04-06)

### P1.35 Slotting expected loss rates (Table B)
- **Status:** [x] Complete (2026-04-06)

### P1.37 CCF commitment-to-issue lower-of rule (Art. 111(1)(c))
- **Status:** [x] Complete (2026-04-07)

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

### P1.39 CRM haircut liquidation period dependency not modelled (Art. 224)
- **Status:** [x] Complete (2026-04-07)

### P1.40 CRM maturity mismatch additional ineligibility conditions (Art. 237(2))
- **Status:** [x] Complete (2026-04-06)

### P1.41 Credit derivative restructuring exclusion haircut (Art. 233(2))
- **Status:** [x] Complete (2026-04-06)

### P1.44 Infrastructure supporting factor not applied to slotting exposures
- **Status:** [x] Complete (2026-04-07)

### P1.45 SCRA null grade defaults to Grade A (most favourable) instead of Grade C
- **Status:** [x] Complete (2026-04-06)

### P1.48 CRR defaulted exposure secured/unsecured split (Art. 127)
- **Status:** [x] Complete (2026-04-07)

### P1.49 Art. 110A due diligence obligation (new SA requirement)
- **Status:** [ ] Not started
- **Impact:** PRA PS1/26 Art. 110A introduces a new mandatory due diligence obligation for SA credit risk. Institutions must perform due diligence to ensure risk weights appropriately reflect the risk of the exposure. No spec file, no code, no validation exists for this requirement. While primarily a governance/process requirement, it may have calculable implications (e.g., if due diligence reveals risk weight is not adequate, the institution must apply a higher weight).
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 Art. 110A
- **Fix:** At minimum, document the requirement in the SA risk weight spec. Optionally, add a `due_diligence_override_rw` field to schema allowing institutions to override SA risk weights upward where due diligence indicates inadequacy. Add validation that flags exposures where no due diligence assessment has been performed.
- **Tests needed:** Validation tests for due diligence flag. Documentation test that spec covers Art. 110A.

### P1.50 Art. 169A/169B LGD Modelling Collateral Method (new Basel 3.1 AIRB method)
- **Status:** [x] Complete (2026-04-07)

### P1.55 Art. 134 "Other Items" risk weights missing (cash 0%, items in collection 20%, residual lease)
- **Status:** [x] Complete (2026-04-06)

### P1.59 EquityType.SUBORDINATED_DEBT + B31 150% weight + transitional floor exclusion
- **Status:** [x] Complete (2026-04-07)

### P1.60 No B31 FIRB LGD DataFrame generator
- **Status:** [x] Complete (2026-04-07)

### P1.61 CIU look-through leverage adjustment and transitional floor fix (Art. 132a(3))
- **Status:** [x] Complete (2026-04-07)

### P1.62 Art. 128 high-risk items 150% risk weight missing
- **Status:** [x] Complete (2026-04-06)

### P1.63 A-IRB revolving 100% SA carve-out from own-estimate permission (Art. 166D(1)(a))
- **Status:** [x] Complete (2026-04-06)

### P1.64 A-IRB EAD floor tests incomplete — 2 of 3 tests missing (Art. 166D(5))
- **Status:** [x] Complete (2026-04-06)

### P1.65 SA Table A1 Row 2 (100% CCF) instrument types incomplete
- **Status:** [x] Complete (2026-04-07)

### P1.66 Basel 3.1 QRRE threshold wrong — GBP 100k in code, should be GBP 90k (Art. 147(5A)(c))
- **Status:** [x] Complete (2026-04-06)

### P1.67 SA specialised lending classified as corporate sub-type (Art. 112)
- **Status:** [x] Complete (2026-04-07)

### P1.68 IRB guarantee LGD substitution incomplete (Art. 236)
- **Status:** [x] Complete (2026-04-06)

### P1.69 Receivables haircut 20% in code, should be 40% (Art. 230); equity_other 25% vs 30%
- **Status:** [x] Complete (2026-04-06)

### P1.70 Overcollateralisation 30% threshold applied globally, not per collateral type (Art. 230)
- **Status:** [x] Complete (2026-04-06)

### P1.71 CRR SA equity weights wrong — all used Basel 3.1 values instead of Art. 133(2) flat 100%
- **Status:** [x] Complete (2026-04-06)

### P1.72 CIU fallback 1250% in code, should be 150% (CRR) / 250%-400% (B31)
- **Status:** [x] Complete (2026-04-06)

### P1.73 Gold haircut 0% in code/spec, PRA Art. 224 Table 3 says 20%
- **Status:** [x] Complete (2026-04-07)

### P1.74 Main index equity haircut 15% in spec, PRA Art. 224 Table 3 says 20%
- **Status:** [x] Complete (2026-04-07)

### P1.75 LGD* formula does not blend LGDU/LGDS — single LGD applied to residual
- **Status:** [x] Complete (2026-04-06)

### P1.76 Corporate bond haircut table uses 3 maturity bands, PRA has 5 bands
- **Status:** [x] Complete (2026-04-06)

### P1.77 Mixed collateral pool uses pro-rata allocation, Art. 231 requires sequential fill
- **Status:** [x] Complete (2026-04-06)

### P1.78 FX mismatch haircut not applied to guarantee/CDS amounts (Art. 233(3-4))
- **Status:** [x] Complete (2026-04-06)

### P1.81 Art. 159(3) two-branch EL shortfall/excess comparison not implemented
- **Status:** [x] Complete (2026-04-06)

### P1.82 BEEL exception for A-IRB defaulted EL not implemented (Art. 158(5))
- **Status:** [x] Complete (2026-04-06)

### P1.83 EL comparison pool 'B' excludes AVAs and own funds reductions (Art. 159(1))
- **Status:** [x] Complete (2026-04-07)

### P1.84 T2 credit cap must use un-floored IRB RWA (Art. 62(d) / Art. 92(2A))
- **Status:** [x] Complete (2026-04-07)

### P1.79 CRR corporate PD floor 0.03% in code, CRR Art. 160(1) says 0.05%
- **Status:** [x] Complete (2026-04-06)

### P1.80 Corporate subordinated exposures get 50% LGD floor, should be 25% (Art. 161(5))
- **Status:** [x] Complete (2026-04-06)

### P1.85 PMA adjustment sequencing wrong + EL monotonicity missing (Art. 153(5A)/154(4A)/158(6A))
- **Status:** [x] Complete (2026-04-07)

### P1.86 CRR unrated covered bond RW hardcoded to 20% — Art. 129(5) derivation not wired
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `engine/sa/calculator.py:968-972` previously hardcoded 0.20 (20%) for ALL unrated covered bonds under CRR. Art. 129(5) requires derivation from the issuing institution's risk weight: institution 20% → CB 10%, institution 30% → CB 15%, institution 40% → CB 20%, institution 50% → CB 25%, institution 75% → CB 35%, institution 100% → CB 50%, institution 150% → CB 100%. The code's 20% was only correct when the institution gets 40% RW (UK unrated sovereign-derived). For non-UK issuers with 100% or 150% RW, capital was **understated** (20% vs 50% or 100%).
- **Fix:** Added `institution_cqs` field (pl.Int8, nullable) to `COUNTERPARTY_SCHEMA` in `data/schemas.py`. Classifier propagates it as `cp_institution_cqs` to exposure rows. SA calculator's `_crr_unrated_cb_rw_expr()` helper builds a Polars expression that chains institution CQS → institution RW (via Art. 120 Table 3/4, respecting UK deviation) → covered bond RW (via `COVERED_BOND_UNRATED_DERIVATION`). When `cp_institution_cqs` is null (unrated institution), uses sovereign-derived institution RW: UK 40% → CB 20%, standard 100% → CB 50%. Backward compatible: null field gives same 20% result for UK firms as before.
- **File:Line:** `engine/sa/calculator.py:107-142` (helper function), `engine/sa/calculator.py:1012-1019` (expression), `data/schemas.py:192` (schema), `engine/classifier.py:327-328` (propagation), `tests/fixtures/single_exposure.py:68,100` (test helper)
- **Spec ref:** CRR Art. 129(5), CRR Art. 120 Tables 3/4
- **Tests:** 18 new tests added to `tests/unit/test_covered_bonds.py`: 6 UK institution CQS parametrized tests, 6 standard institution CQS parametrized tests, 1 UK unrated institution fallback, 1 standard unrated institution fallback, 1 rated-ignores-institution-cqs, 1 UK-vs-standard RWA comparison, 3 table consistency cross-checks. All 3705 tests pass (was 3687).

### P1.87 A-IRB blended LGD floor for retail with mixed collateral (Art. 164(4)(c))
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `_lgd_floor_expression_with_collateral()` in `engine/irb/formulas.py` used a single `collateral_type` column to select ONE floor value per exposure. Art. 164(4)(c) requires a weighted-average floor using the per-type coverage proportions from the Art. 231 waterfall: `LGD_floor = (E_unsecured/EAD) × LGDU + Σ(E_i/EAD) × LGDS_i`. For retail_other (LGDU=30%) and retail_qrre (LGDU=50%), the single-type approach could understate capital — e.g., an exposure 60% covered by physical collateral (15% floor) and 40% unsecured got floor=15% instead of correct blended floor=21%. The `retail_lgdu` config field (Decimal("0.30")) was defined but never used.
- **Fix:** CRM waterfall allocation columns (`crm_alloc_financial`, `crm_alloc_covered_bond`, `crm_alloc_receivables`, `crm_alloc_real_estate`, `crm_alloc_other_physical`, `crm_alloc_life_insurance`) now preserved through CRM output (previously dropped). New `_lgd_floor_blended_expression()` function in `formulas.py` computes weighted average floor using these allocations. Wired into both `apply_lgd_floor()` in namespace.py and `apply_all_formulas()` in formulas.py. Returns null for non-eligible exposures (corporate, retail_mortgage), falling through to single-type floor. `retail_lgdu` config field now consumed.
- **File:Line:** `engine/crm/collateral.py:700-710` (preserve alloc columns), `engine/crm/constants.py:254-264` (CRM_ALLOC_COLUMNS), `engine/irb/formulas.py:245-339` (blended expression), `engine/irb/namespace.py:360-370,613-623` (dispatch wiring)
- **Spec ref:** PRA PS1/26 Art. 164(4)(c)
- **Tests:** 32 new unit tests in `tests/unit/test_lgd_floor_blended.py`: 15 direct blended expression tests (CRR zero, unsecured null, fully secured financial/physical, mixed physical+unsecured, financial+receivables, three-type mix, all-six-types, QRRE 50% LGDU, mortgage/corporate null, zero EAD, overcollateralised), 6 namespace integration tests (A-IRB blended applied, LGD above floor, F-IRB not floored, CRR no floor, corporate single-type, mortgage flat 5%), 1 CRM column mapping test, 10 edge cases (null columns, precision, parametrized two-type mix, receivables+RE blend, life insurance, covered bonds). All 3,737 tests pass (was 3,705).

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
- **Status:** [ ] Not implemented
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
- **Fix:** Add template definitions and generator methods. Add C 08.05/OF 08.05/OF 08.05.1/OF 34.07 to `docs/features/corep-reporting.md`.

### P2.3 COREP C 09.01-09.02 (Geographical Breakdown)
- **Status:** [ ] May require `country_of_exposure` field not in schema
- **Fix:** Add field if missing. Add template definitions and generator methods.

### P2.4 COREP C 08.01 Section 3 "Calculation Approaches"
- **Status:** [ ] Entirely null output (confirmed at `generator.py:524`)
- **File:Line:** `reporting/corep/generator.py:524`
- **Fix:** Populate from approach assignment data.

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
- **Status:** [ ] Not started
- **Impact:** The `ResultExporterProtocol` in `contracts/protocols.py` does not include an `export_to_corep()` method. The COREP generator exists (`reporting/corep/generator.py`) but is not integrated into the protocol-driven pipeline. Any code calling the exporter protocol cannot produce COREP output without bypassing the protocol.
- **File:Line:** `contracts/protocols.py` (ResultExporterProtocol definition)
- **Spec ref:** Project architecture (protocol-driven pipeline)
- **Fix:** Add `export_to_corep()` method to ResultExporterProtocol. Implement in the concrete exporter class.
- **Tests needed:** Contract test verifying protocol compliance. Integration test for COREP export via protocol.

### P2.11 COREP backward-compatibility aliases are dead code
- **Status:** [ ] Not started
- **Impact:** `C07_COLUMNS`, `C08_01_COLUMNS`, `C08_02_COLUMNS` at `templates.py:661-689` are still exported but unused by any code. These are CRR-era simplified column sets superseded by the full template definitions.
- **File:Line:** `reporting/corep/templates.py:661-689`
- **Fix:** Remove dead alias exports. Update any imports.
- **Tests needed:** Verify no imports reference the removed aliases.

---

## Priority 3 -- Pillar III Disclosures

### P3.1 Pillar III disclosure code
- **Status:** [ ] Not started -- no code exists in `src/`, no `reporting/pillar3/` directory
- **Impact:** 9 disclosure templates specified: OV1, CR4, CR5, CR6, CR6-A, CR7, CR7-A, CR8, CR10. Full column/row definitions in `docs/features/pillar3-disclosures.md` with CRR (UK prefix) and Basel 3.1 (UKB prefix) variants.
- **Spec ref:** `docs/specifications/output-reporting.md`, `docs/features/pillar3-disclosures.md`
- **Fix:** Create `src/rwa_calc/reporting/pillar3/` package with generator, templates, and protocol. Add to `ResultExporterProtocol`.
- **Tests needed:** Unit tests for each template. Acceptance tests.

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

### P3.4 UKB CMS1 / CMS2 (output floor comparison) missing from spec and plan
- **Status:** [ ] Not in spec -- mandatory Basel 3.1 Pillar III templates
- **Impact:** PRA PS1/26 Art. 456 and Art. 2a define two mandatory output floor comparison templates:
  - **UKB CMS1**: Comparison of SA vs. modelled RWEs by risk type (Art. 456(1)(a), Art. 2a(1))
  - **UKB CMS2**: Comparison of SA vs. modelled RWEs for credit risk at asset class level (Art. 456(1)(b), Art. 2a(2))
  These are new Basel 3.1-specific Pillar III templates with no CRR equivalent. Neither is in `docs/features/pillar3-disclosures.md` or `docs/specifications/output-reporting.md`.
- **Spec ref:** PRA PS1/26 Art. 456, Art. 2a (page 467 of PS1/26 App 1)
- **Fix:** Add CMS1 and CMS2 template definitions to Pillar III spec. Include in P3.1 implementation scope.
- **Tests needed:** Unit tests for CMS1/CMS2 templates.

---

## Priority 4 -- Documentation & Consistency Fixes

### P4.1 Output floor transitional schedule inconsistency
- **Status:** [~] Code is correct; docs disagree
- **Impact:** Code uses PRA compressed 4-year schedule (60%/65%/70%/72.5% for 2027-2030). But `docs/framework-comparison/technical-reference.md` lines 72-78 show BCBS 6-year schedule (50%-72.5% for 2027-2032). `TransitionalScheduleBundle` docstring references 50% (2027). Data tables agent confirms: output floor PRA 4-year phase-in schedule in code is correct.
- **Fix:** Update technical-reference.md, stale docs, and bundle docstring to match PRA schedule.

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
- **Status:** [~] Multiple docs wrong
- **Impact:** `technical-reference.md` shows retail mortgage PD floor as 0.05% -- should be **0.10%** per PRA Art. 163(1)(b). The `key-differences.md` table correctly shows 0.10%. Code also wrong (P1.1).
- **Fix:** Update technical-reference.md line 33 to 0.10%. Also update the PDFloors docstring at `config.py:46` which says "Retail non-QRRE: 0.05%" -- should say "Retail mortgage: 0.10%".

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

### P4.11 SA risk weight spec missing 10+ exposure class sections (also CODE gaps)
- **Status:** [ ] Incomplete
- **Impact:** `docs/specifications/crr/sa-risk-weights.md` is missing dedicated sections for:
  - Art. 115 RGLA: Two RW tables (sovereign-derived Table 1A + rated Table 1B), UK devolved government 0%, UK local authorities 20%
  - Art. 116 PSE: Three sub-treatments (unrated sovereign-derived, rated, short-term <=3m = 20%)
  - Art. 117 MDB: Rated table (CQS 2 = 30%, not 50%), unrated = 50%, 0% list (16 named MDBs)
  - Art. 118 International Organisations: 0% list (EU, IMF, BIS, EFSF, ESM)
  - Art. 120 Tables 4/4A: Short-term rated institution tables
  - Art. 128 High-risk exposures: 150%
  - Art. 129 Covered bonds: Rated Table 7 (10-100%) + unrated stepdown table
  - Art. 134(4-6): Gold bullion 0%, repo/forward asset RW, nth-to-default basket
  - Art. 137 ECA Table 9: MEIP score to RW mapping
  Code has `ExposureClass` enum members for RGLA/PSE/MDB but risk weight tables are not in `data/tables/`.
  **Note:** These are not just SPEC gaps but also CODE gaps -- the SA calculator has no implementation for PSE/RGLA/MDB/Art.134 risk weights. See P1.52, P1.53, P1.54, P1.55.
- **Fix:** Add missing sections to SA risk weight spec. Author risk weight tables in `data/tables/`.

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
- **Status:** [~] Multiple rows and rules missing
- **Impact:** `credit-conversion-factors.md` vs PRA PS1/26 Art. 111 Table A1:
  - Row 2 (100% -- commitments with certain drawdowns: factoring, forward purchases, repos) missing
  - Row 3 (50% -- other issued OBS items, not credit-substitute character) missing
  - B31 removal of maturity-based distinction (>1yr/<=1yr) not documented
  - F-IRB B31 table **wrong**: shows 75% for medium risk (should be 50% per Art. 166C), shows 40% UCC (should be 10%)
  - Art. 166(9) trade LC exception is blanked in PS1/26 -- spec still references it
- **Fix:** Rewrite CCF spec tables to match Table A1. Correct F-IRB B31 table.

### P4.14 Stale key-differences.md implementation status claims
- **Status:** [~] Three features marked "Not Yet Implemented" that ARE complete
- **Impact:** `key-differences.md` claims "Not Yet Implemented" for:
  - (a) Currency mismatch 1.5x multiplier -- implemented at `engine/sa/calculator.py:900-966`
  - (b) SA Specialised Lending Art. 122A-122B -- implemented at `engine/sa/calculator.py:528-533`
  - (c) Provision-coverage-based defaulted treatment CRE20.87-90 -- implemented at `engine/sa/calculator.py:451-461`
- **Fix:** Update key-differences.md to mark these as implemented.

### P4.15 CRM spec extensive gaps vs PRA PS1/26 (Art. 192-239)
- **Status:** [ ] Major rewrite needed
- **Impact:** Comparison of `credit-risk-mitigation.md` against PDF (pp. 162-223) found 26 gaps:
  - **Critical values wrong:** Other equity haircut (25% in spec, 30% in PDF 10-day), non-financial collateral HC values (receivables 20% vs 40%, RE 0% vs 40%), overcollateralisation ratios (1.25x/1.4x) have no basis in PS1/26
  - **Missing tables:** LGDS values (0%/20%/20%/25%), CQS4 govt bond haircuts, short-term ECAI Table 2, securitisation haircuts, 5-maturity-band table (CRR uses 3 bands, PDF uses 5)
  - **Missing formulas:** Full LGD* formula (Art. 230), mixed pools formula (Art. 231), volatility scaling (Art. 226), G* = G x (1-Hfx) for unfunded (Art. 233(3))
  - **Missing rules:** FCSM mutual exclusivity with FCCM (Art. 222(1)), 0% FCSM for repos (Art. 222(4)/(6)), Art. 227 zero-haircut conditions, partial protection tranching (Art. 234), credit-linked notes (Art. 218), Part 4 capping rule
  - **Inaccurate descriptions:** Rule 4.11 scope, parameter substitution LGD choice (Art. 236)
  - **Code bug triggered by spec gap:** CQS 4-6 bond haircut silently returns 20% instead of ineligibility error (`crr_haircuts.py`) -- see P1.56
- **Fix:** Comprehensive rewrite of CRM spec with all regulatory table values and formulas.

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

---

## Priority 5 -- Test Coverage Gaps

### P5.1 Stress / performance acceptance tests
- **Status:** [ ] Empty directory (`tests/acceptance/stress/` -- only `__pycache__`)
- **Impact:** Source files `test_scenario_m43_stress.py` and `tests/unit/test_stress_testing.py` were deleted but orphaned `.pyc` bytecode files remain in `__pycache__/`. The stress tests existed previously and were lost.
- **Fix:** Add acceptance-level stress tests (100K, 1M row portfolios). Clean up orphaned `.pyc` files.

### P5.2 Fixture referential integrity
- **Status:** [~] Pre-existing errors
- **Fix:** Fix or regenerate affected fixtures.

### P5.3 CRR CRM guarantee/provision test placeholders
- **Status:** [~] Documented as placeholders
- **Fix:** Audit and expand test coverage.

### P5.4 Conditional pytest.skip() in acceptance tests
- **Status:** [~] ~90 conditional skips
- **Fix:** Audit which scenarios are always skipped; ensure fixture data exists for all.

### P5.5 Polars venv broken (environment issue)
- **Status:** [~] Import error
- **Impact:** `ImportError: cannot import name 'POLARS_STORAGE_CONFIG_KEYS' from 'polars.io.cloud._utils'`. The entire test suite cannot run. Likely caused by partial polars/deltalake package update.
- **Fix:** Run `uv sync` or reinstall polars packages.

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
- **Status:** [ ] Not started
- **Impact:** CRM submodules (`guarantees.py`, `provisions.py`, `collateral.py`) are only tested indirectly through CRMProcessor integration. No direct unit tests for individual CRM functions like haircut calculation, maturity mismatch formula, guarantee substitution logic, provision allocation. The 120 CRM unit tests are all at the processor level.
- **File:Line:** `tests/unit/crm/` (no submodule test files)
- **Fix:** Add unit tests for: (a) `crm/collateral.py` -- haircut application, eligible collateral check; (b) `crm/guarantees.py` -- substitution logic, beneficiality check; (c) `crm/provisions.py` -- allocation, pro-rata calculation; (d) `crm/haircuts.py` -- maturity mismatch formula, FX haircut.
- **Tests needed:** This IS the test gap item.

### P5.8 No model_permissions-specific acceptance tests under Basel 3.1
- **Status:** [ ] Not started
- **Impact:** Model permissions (per-model FIRB/AIRB/slotting with SA fallback) were implemented in v0.1.64 but no Basel 3.1 acceptance test scenarios exist for model permissions interactions with Art. 147A restrictions. E.g., what happens when a model grants AIRB permission for institutions but B31 restricts to FIRB?
- **File:Line:** `tests/acceptance/` (no model_permissions B31 scenarios)
- **Fix:** Add acceptance test scenarios for model permissions under B31, specifically testing Art. 147A override behavior.
- **Tests needed:** This IS the test gap item.

### P5.9 No equity acceptance tests (CRR or Basel 3.1)
- **Status:** [ ] Not started
- **Impact:** `tests/unit/crr/test_crr_equity.py` has 49 unit tests, but no end-to-end acceptance scenario exists for equity under either framework. Given the multiple equity bugs (P1.42, P1.43, P1.71, P1.72), acceptance tests are critical for regression detection.
- **Fix:** Add acceptance test scenarios for: CRR SA equity (listed/unlisted/PE), CRR IRB simple equity, B31 SA equity (250%/400%/150%/100%), equity transitional schedule, CIU look-through/mandate/fallback.

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
- **Status:** [~] Several classes not re-exported
- **Impact:** Not exported from `contracts/__init__.py`: `EquityResultBundle`, `EquityCalculatorProtocol`, `OutputAggregatorProtocol`, `ResultExporterProtocol`, `EquityTransitionalConfig`, `PostModelAdjustmentConfig`, `IRBPermissions`. Not exported from `domain/__init__.py`: `SCRAGrade`, `EquityType`, `EquityApproach`. Additionally, `ResultExporterProtocol` needs an `export_to_corep()` method added to the protocol definition itself (see P2.10).
- **Fix:** Add missing re-exports. See P2.10 for protocol method addition.

### P6.3 `CalculationConfig.collect_engine` docstring error
- **Status:** [~] Contradictory description
- **Fix:** Correct the docstring.

### P6.4 `EquityResultBundle.approach` uses `str` instead of `EquityApproach` enum
- **Status:** [~] Weakens type safety
- **Fix:** Change to `EquityApproach`.

### P6.5 `ELPortfolioSummary` uses `float` instead of `Decimal`
- **Status:** [x] Complete (2026-04-07)
- **Impact:** All 16 numeric fields on `ELPortfolioSummary` were `float`, violating the project convention that regulatory parameters and capital-related values use `Decimal` for precision. The EL portfolio summary feeds into T2 credit cap, OF-ADJ, and CET1/T2 deduction calculations — critical regulatory capital paths.
- **Fix:** Changed all 16 numeric fields from `float` to `Decimal` in `contracts/bundles.py`. `_el_summary.py` now converts Polars-collected float values to `Decimal(str(...))` at the construction boundary via `_to_decimal()` helper. `aggregator.py` converts back to `float()` at the OF-ADJ computation boundary (where other inputs from `OutputFloorConfig` are float). `api/formatters.py` simplified — no longer needs redundant `Decimal(str(...))` wrapping since fields are already `Decimal`.
- **File:Line:** `contracts/bundles.py:282-351`, `engine/aggregator/_el_summary.py:30-37,252-270`, `engine/aggregator/aggregator.py:122-126`, `api/formatters.py:272-279`
- **Tests:** 9 test files updated (~145 assertions) to use `float()` wrapping on ELPortfolioSummary field accesses in `pytest.approx` comparisons and float arithmetic. All 3,748 tests pass, 125 contract tests pass.

### P6.6 `CalculationError.to_dict()` returns bare `dict`
- **Status:** [~] Minor type safety gap
- **Fix:** Add type parameters.

### P6.7 `is_guarantee_beneficial` absent from CRM bundle
- **Status:** [~] Tracking field missing
- **Impact:** The CRM spec lists `is_guarantee_beneficial` as a CRM tracking field. The CRM processor's `apply_guarantees()` unconditionally sets `guaranteed_portion` without a beneficiality check -- it's deferred to SA/IRB calculators (`sa/calculator.py:839`, `irb/guarantee.py:103`). The CRM audit trail always shows the full covered amount even when non-beneficial.
- **Fix:** Add `is_guarantee_beneficial` to CRM audit output. Optionally move beneficiality check earlier.

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
- **Status:** [~] Gap
- **Impact:** `ApproachType` enum (`enums.py:92-107`) has no EQUITY member. Equity exposures in loan/contingent tables get classified via standard SA/IRB approach assignment rather than being routed to the equity calculator. Only the separate `data.equity_exposures` LazyFrame bypasses this. This means equity positions in main tables go to SA/IRB, not the equity calculator.
- **Fix:** Add `ApproachType.EQUITY` and route equity-classified exposures in classifier.

### P6.12 QRRE classification silently disabled when columns absent
- **Status:** [x] Complete (2026-04-07)
- **Impact:** `classifier.py:497-508` sets `is_qrre = pl.lit(False)` when `is_revolving` or `facility_limit` columns are absent. Previously no warning or error was logged. All QRRE exposures would silently receive non-QRRE treatment (higher capital). Cross-ref P1.25 -- `qualifies_as_retail` defaults to True when no lending group data (`classifier.py:350-363`), masking non-regulatory retail.
- **Fix:** Classifier now emits `CalculationError(code="CLS004", severity=WARNING, category=CLASSIFICATION)` when `is_revolving` and/or `facility_limit` columns are missing. Warning message specifies which column(s) are absent and the impact on QRRE classification. Added `ErrorCategory.CLASSIFICATION` enum member to `domain/enums.py`. Added `ERROR_QRRE_COLUMNS_MISSING = "CLS004"` constant and `classification_warning()` factory function to `contracts/errors.py`. Classifier's `classification_errors` list (previously always empty) is now populated. Warning fires under both CRR and Basel 3.1 frameworks.
- **File:Line:** `engine/classifier.py:206-225` (warning check), `contracts/errors.py:176,300-313` (error code + factory), `domain/enums.py:220-221` (CLASSIFICATION category)
- **Spec ref:** CRR Art. 147(5)
- **Tests:** 11 new tests in `tests/unit/test_classifier_qrre_warnings.py`: 8 warning attribute tests (both missing, only is_revolving missing, only facility_limit missing, both present no warning, severity, category, regulatory reference, Basel 3.1 compat), 3 classification behavior tests (without columns all retail_other, with columns revolving is QRRE, non-revolving not QRRE).

### P6.13 Dead `TYPE_CHECKING` block in config.py
- **Status:** [~] Dead code
- **Fix:** Remove.

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
  - `due_diligence_override_rw` (P1.49 Art. 110A)
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
- **Status:** [ ] Not started
- **Impact:** Both `get_crm_adjusted_bundle` and `get_crm_unified_bundle` (`processor.py:461,566`) set `collateral_allocation=None` with a comment "Would be populated from collateral processing." Downstream reporting cannot access per-exposure collateral allocation details.
- **File:Line:** `engine/crm/processor.py:461,566`
- **Fix:** Populate `collateral_allocation` from the collateral processing results.
- **Tests needed:** Unit test verifying collateral allocation is populated.

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

These items are verified complete as of 0.1.64. Items with **[!]** have known gaps documented in P1/P2:

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
- [x] COREP C 07.00 / C 08.01 / C 08.02 (basic structure, CRR + Basel 3.1 OF variants)
- [x] API (CreditRiskCalc, export to Parquet/CSV/Excel, results cache)
- [x] Model permissions (per-model FIRB/AIRB/slotting, fallback to SA)
- [x] Marimo UI (RWA app, comparison app, template workbench, landing page)
- [x] Schema validation, bundle validation, column value constraints
- [x] FX conversion (multi-currency support)
- [x] Materialisation barriers (CPU + streaming modes)
