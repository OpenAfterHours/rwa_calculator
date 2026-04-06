# Implementation Plan

**Last updated:** 2026-04-06 (P1.3 A-IRB CCF revolving restriction implemented)
**Current version:** 0.1.83 | **Test suite:** ~2,634 collected (~2,137 unit + 265 acceptance + 124 contracts + 102 integration + 35 benchmarks), ~33 skipped | P1.3, P1.4, P1.32, P1.34 fixed.
**CRR acceptance:** 100% (101 tests) | **Basel 3.1 acceptance:** 100% (116 tests) | **Comparison:** 100% (60 tests)
**Acceptance tests skipped at runtime:** ~90 (conditional `pytest.skip()` when fixture data unavailable)
**Environment note:** Polars venv currently broken (delta import error) -- needs `uv sync` or package reinstall
**Test corrections in 0.1.64 increment (2026-04-06):** Pre-existing test expectations were corrected for P1.1 (retail_mortgage 0.05%→0.10%, retail_qrre_transactor 0.03%→0.05%), P1.33 (mortgage RW floor 15%→10%), P1.46 (CQS 5 corporate RW 100%→150%), and CIU fallback (tests expected 1250% but code correctly implements 150% per CRR Art. 132(2); the 1250% deduction treatment, if needed, must be tracked separately). Test count increased from ~2,283 to ~2,344.

**Gap summary:** P1 (calculation correctness): 80 (+P1.9a sub-item; P1.47 fixed, P1.66/P1.79 closed as false positives) | P2 (COREP): 11 | P3 (Pillar III): 4 | P4 (docs): 21 | P5 (tests): 10 | P6 (code quality): 20 | P7 (future): 4
**Critical items by impact type:**
- *Capital understatement (exposures get lower RWA than they should):* [P1.56, P1.55, P1.54, P1.53, P1.52, P1.46, P1.42, P1.51, P1.66, P1.79, P1.24, P1.25, P1.45, P1.69, P1.2 (QRRE 50% vs 25%, retail_other 30% vs 25%) now fixed/verified]
- *Capital overstatement (conservative but wrong):* [P1.36, P1.33, P1.22, P1.72, P1.80, P1.32, P1.2 (retail_mortgage 5% vs 25% previously applied) now fixed/verified]
- *CRM formula/value errors:* [P1.69 receivables haircut fixed — B31 corrected from 20% to 40%; CRR kept at 20% as C*/C** approximation] P1.73 (gold haircut — code 15%, spec corrected to 20%; may be false positive), P1.74 (main-index equity — code 15%/25%, spec corrected to 20%; may be false positive), P1.75 (LGD* formula single-LGD not blended), P1.76 (bond haircut 3 bands vs 5), P1.77 (mixed pool pro-rata vs sequential), P1.78 (FX mismatch on guarantees missing)
  (P1.73/P1.74 may be false positives — code matches CRM changes reference for 10-day liquidation period)
- *Needs regulatory verification:* P1.71 (CRR equity unlisted 250% vs spec 150%, PE 250% vs spec 190%)
- *Missing B31 features (whole categories absent):* P1.9 (output floor portfolio-level), P1.12 (SCRA enhanced/short-term), P1.29 (40% CCF category), P1.30 (CRM method selection)
- *Other critical:* [P1.43, P1.47 now fixed]

## Status Legend
- [ ] Not started
- [~] Partial / needs rework
- [x] Complete

---

## Priority 1 -- Calculation Correctness Gaps

These items affect regulatory calculation accuracy under CRR or Basel 3.1.

### P1.36 **CRITICAL** -- F-IRB CCF under Basel 3.1 uses wrong values (Art. 166C)
- **Status:** [x] Complete
- **Impact:** PRA PS1/26 Art. 166C mandates that F-IRB off-balance-sheet items use **SA CCFs** (Table A1). Under B31, `_compute_ccf` now uses `sa_ccf_expression(is_basel_3_1=True)` for F-IRB, giving FR=100%, MR=50%, MLR=20%, LR(UCC)=10%. CRR path unchanged.
- **File:Line:** `engine/ccf.py:215-234`
- **Spec ref:** PRA PS1/26 Art. 166C
- **Fixed:** 2026-04-06

### P1.46 Corporate CQS 5 risk weight 100% in code, PRA PS1/26 says 150% (Art. 122(2))
- **Status:** [x] Complete
- **Impact:** `b31_risk_weights.py` CQS 5 now correctly set to `Decimal("1.50")` (150%) per PRA PS1/26 Art. 122(2) Table 6. Pre-existing test expectations that assumed 100% were corrected in this increment.
- **File:Line:** `data/tables/b31_risk_weights.py`
- **Spec ref:** PRA PS1/26 Art. 122(2) Table 6
- **Fixed:** 2026-04-06

### P1.51 B31 defaulted provision threshold 20% not 50% AND denominator wrong (Art. 127)
- **Status:** [x] Complete
- **Impact:** Both bugs now fixed in `engine/sa/calculator.py` and `data/tables/b31_risk_weights.py`: (1) threshold changed from 50% to 20% per B31 Art. 127; (2) B31 path denominator now uses EAD alone (not EAD + provision_deducted). Pre-existing test expectations corrected.
- **File:Line:** `engine/sa/calculator.py`, `data/tables/b31_risk_weights.py`
- **Spec ref:** PRA PS1/26 Art. 127
- **Fixed:** 2026-04-06

### P1.42 Basel 3.1 equity SA weights wrong -- listed equity gets 100% instead of 250%
- **Status:** [x] Complete
- **Impact:** B31 SA equity weights now implemented with framework branching in `_apply_equity_weights_sa` → `_apply_b31_equity_weights_sa`. New data table at `data/tables/b31_equity_rw.py`. Weights applied: listed/exchange-traded = 250%, speculative unlisted = 400%, government-supported = 100%, CIU fallback = 250%. Note: subordinated debt (150%) is deferred pending `EquityType.SUBORDINATED_DEBT` enum addition (see P1.59).
- **File:Line:** `engine/equity/calculator.py`, `data/tables/b31_equity_rw.py`
- **Spec ref:** PRA PS1/26 Art. 133(3)-(5)
- **Fixed:** 2026-04-06

### P1.43 Equity `get_equity_result_bundle` skips transitional floor (bug)
- **Status:** [x] Complete
- **Impact:** `get_equity_result_bundle` now calls `_apply_transitional_floor` before `_calculate_rwa`, matching `calculate_branch` behaviour. Both entry points now produce identical results.
- **File:Line:** `engine/equity/calculator.py`
- **Spec ref:** PRA PS1/26 equity transitional schedule
- **Fixed:** 2026-04-06

### P1.47 Slotting PF pre-operational table uses BCBS values not in PRA PS1/26
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Description:** `B31_SLOTTING_RISK_WEIGHTS_PREOP` now uses the same standard PRA PS1/26 Art. 153(5) Table A weights as operational SL (Strong=70%, Good=90%, Satisfactory=115%, Weak=250%). The BCBS CRE33 pre-op distinction (Strong=80%, Good=100%, Satisfactory=120%, Weak=350%) was not adopted by PRA — PRA PS1/26 Art. 153(5) Table A has no separate pre-operational PF row. Tests, specs, and docstrings all updated.
- **File:Line:** `engine/slotting/b31_slotting.py:37-43`
- **Spec ref:** PRA PS1/26 Art. 153(5) Table A

### P1.52 PSE risk weight tables missing from code (Art. 116)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** PSE risk weights now implemented with full Art. 116 treatment:
  - Rated PSEs (CQS 1-6): Table 2A own-rating weights via CQS join (CQS 3 = 50%)
  - Unrated UK PSEs: 20% sovereign-derived (UK sovereign CQS=1, Table 2)
  - Unrated non-UK PSEs: 100% conservative default (sovereign CQS unknown)
  - Short-term (≤3m): 20% flat (Art. 116(3)), overrides all CQS-based weights
  - PSE guarantor substitution: Table 2A for rated, sovereign-derived for unrated
- **File:Line:** `data/tables/crr_risk_weights.py` (PSE tables + _create_pse_df), `engine/sa/calculator.py` (PSE branches in both B31 and CRR when-chains + guarantee substitution)
- **Spec ref:** CRR Art. 116, PRA PS1/26 Art. 116
- **Tests:** 29 new unit tests: 9 data table tests, 11 CRR calculator tests, 9 B31 calculator tests. All pass. Test count: 2389 (was 2360).
- **Limitation:** Non-UK unrated PSEs get 100% conservative default. Full sovereign-CQS lookup requires a `sovereign_cqs` column (not yet in schema). UK PSEs are the primary use case for a PRA-regulated calculator.

### P1.53 RGLA risk weight tables missing from code (Art. 115)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** RGLA risk weights now implemented with full Art. 115 treatment:
  - Rated RGLAs (CQS 1-6): Table 1B own-rating weights via CQS join (CQS 3 = 50%)
  - Unrated UK RGLAs: 20% sovereign-derived (UK sovereign CQS=1, Table 1A)
  - Unrated non-UK RGLAs: 100% conservative default (sovereign CQS unknown)
  - UK devolved administrations (Scotland, Wales, NI): 0% (PRA designation, via entity_type=rgla_sovereign)
  - Domestic-currency (GB+GBP, EU+EUR): 20% (Art. 115(5)), overrides CQS-based weights
  - RGLA guarantor substitution: Table 1B for rated, sovereign-derived for unrated
- **File:Line:** `data/tables/crr_risk_weights.py` (RGLA tables + _create_rgla_df), `engine/sa/calculator.py` (RGLA branches in B31/CRR when-chains + guarantee substitution), `data/tables/b31_risk_weights.py` (RGLA in combined B31 table)
- **Spec ref:** CRR Art. 115, PRA PS1/26 Art. 115
- **Tests:** 30 new unit tests: 11 data table tests, 10 CRR calculator tests, 9 B31 calculator tests. All pass. Test count: 1925 unit (was 1895).
- **Limitation:** Non-UK unrated RGLAs get 100% conservative default. Full sovereign-CQS lookup requires a `sovereign_cqs` column (not yet in schema). UK RGLAs are the primary use case for a PRA-regulated calculator.

### P1.54 MDB 0% risk weight lookup missing from code (Art. 117-118)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** MDB and International Organisation risk weights now fully implemented:
  - Named MDBs (Art. 117(2)): 0% unconditional via `mdb_named` entity_type (16 named MDBs: World Bank, EIB, EBRD, etc.)
  - Rated non-named MDBs (Art. 117(1)): Table 2B CQS lookup (CQS 2=30%, unrated=50%)
  - International Organisations (Art. 118): 0% unconditional (EU, IMF, BIS, EFSF, ESM)
  - MDB CQS table added to both CRR and B31 combined risk weight tables
  - MDB/IO branches added to SA calculator when-chains (both frameworks)
  - Guarantor substitution: MDB separated from institution (MDB unrated=50%, institution unrated=40%)
  - Named MDB/IO guarantors: 0% unconditional
- **File:Line:** `data/tables/crr_risk_weights.py` (MDB_RISK_WEIGHTS_TABLE_2B, _create_mdb_df), `data/tables/b31_risk_weights.py` (combined table), `engine/sa/calculator.py` (MDB/IO branches + guarantor substitution), `data/schemas.py` (mdb_named entity_type), `engine/classifier.py` (mdb_named mapping)
- **Spec ref:** CRR Art. 117-118, PRA PS1/26 Art. 117-118
- **Tests:** 30 new unit tests: 10 data table tests, 11 CRR calculator tests, 9 B31 calculator tests. All pass. Test count: 1955 unit (was 1925).
- **Limitation:** Named MDB identification relies on `mdb_named` entity_type. The 16-MDB list is not hardcoded in the calculator — institutions must classify their MDB counterparties correctly in input data.

### P1.56 CQS 5-6 bond ineligibility + CQS 4 government bond eligibility (Art. 197)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Bond collateral eligibility now enforced per CRR Art. 197 at three levels:
  - **Scalar lookup** (`lookup_collateral_haircut`): Returns `None` for ineligible bonds (CQS 5-6 govt, CQS 4-6 corp/institution, unrated bonds). CQS 4 govt bonds now explicitly return 15% haircut.
  - **Pipeline** (`HaircutCalculator._apply_collateral_haircuts`): Ineligible bonds detected via CQS expression; `value_after_haircut` zeroed out; `is_eligible_financial_collateral` set to `False`.
  - **Single-item calculator** (`calculate_single_haircut`): Returns `adjusted_value=0` with `INELIGIBLE` description.
  - **Data tables**: CQS 4 govt bond rows added to both CRR (3 bands) and Basel 3.1 (5 bands) haircut DataFrames.
  - New `is_bond_eligible_as_financial_collateral()` function encapsulates Art. 197 eligibility rules.
- **File:Line:** `data/tables/crr_haircuts.py` (CQS 4 rows + eligibility function + scalar lookup fix), `engine/crm/haircuts.py` (pipeline ineligibility enforcement + single-item handling)
- **Spec ref:** CRR Art. 197(1)(b)-(d), Art. 224 Table 1
- **Tests:** 46 new unit tests in `tests/unit/crm/test_bond_eligibility.py`: 15 eligibility function tests, 12 scalar lookup tests, 4 DataFrame table tests, 5 single-item calculator tests, 10 pipeline LazyFrame tests. All pass. Test count: 2519 (was 2473).

### P1.1 PD floor values incorrect for Basel 3.1 (PRA Art. 160/163)
- **Status:** [x] Complete
- **Impact:** `PDFloors.basel_3_1()` now uses correct values: `retail_mortgage` = 0.10% and `retail_qrre_transactor` = 0.05% per PRA PS1/26 Art. 163(1). Pre-existing test expectations that assumed old values were corrected in this increment.
- **File:Line:** `contracts/config.py`
- **Spec ref:** PRA PS1/26 Art. 163(1), Art. 160(1)
- **Fixed:** 2026-04-06
- **Doc fix:** Update `docs/framework-comparison/technical-reference.md` PD floor table (line 33 shows 0.05% for retail mortgage -- should be 0.10%). Fix `docs/specifications/crr/firb-calculation.md` if it references specific values.

### P1.2 Retail LGD floors missing (PRA Art. 164(4))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Retail-specific LGD floors now implemented per PRA PS1/26 Art. 164(4):
  - (a) RRE-secured retail: **5%** floor (Art. 164(4)(a)) — new `retail_rre` field
  - (b)(i) QRRE unsecured: **50%** floor (Art. 164(4)(b)(i)) — new `retail_qrre_unsecured` field
  - (b)(ii) Other retail unsecured: **30%** floor (Art. 164(4)(b)(ii)) — new `retail_other_unsecured` field
  - (c) LGDU for secured retail formula: **30%** (Art. 164(4)(c)) — new `retail_lgdu` field
  - LGDS values for retail same as corporate (0%/10%/10%/15%)
  Both `_lgd_floor_expression` and `_lgd_floor_expression_with_collateral` now route by exposure_class when available, returning retail-specific floors for retail_mortgage/retail_qrre/retail_other. `get_floor()` accepts optional `exposure_class` parameter. All QRRE exposures get 50% regardless of seniority (not just subordinated). Retail_mortgage with RRE collateral gets 5% (corporate gets 10%). Factory methods updated with retail fields.
- **File:Line:** `contracts/config.py:101-210` (LGDFloors), `engine/irb/formulas.py:117-242` (expressions)
- **Spec ref:** PRA PS1/26 Art. 164(4), Art. 161(5)
- **Tests:** 10 new unit tests in `test_basel31_engine.py` (TestLGDFloors): retail_mortgage 5%, retail_qrre 50%, retail_other 30%, RRE collateral retail vs corporate, retail financial collateral 0%, retail via namespace, retail above floor unchanged. 1 new contract test in `test_config.py` (get_floor_retail_exposure_classes). Existing QRRE test updated (senior QRRE now correctly gets 50%). Acceptance test B31-C2 updated from 25% to 30% for LOAN_RTL_AIRB_001 (retail_other). Test count: 2545 (was 2535).
- **Limitation:** Art. 164(4)(c) blended LGD* formula for partially-collateralised retail not yet implemented — requires secured/unsecured proportion data. LGDS values applied as simple per-collateral floors for now.

### P1.3 A-IRB CCF revolving restriction (Art. 166D(1)(a))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Basel 3.1 Art. 166D(1)(a) now enforced: own-estimate CCFs restricted to revolving facilities only. Three-way gate in `_compute_ccf`:
  - **Non-revolving A-IRB:** uses SA CCFs from Table A1 (not modelled)
  - **Revolving with SA CCF = 100%:** uses SA CCF (Table A1 Row 2 carve-out — factoring, repos, forward deposits)
  - **Revolving with SA CCF < 100%:** uses own-estimate with 50% SA floor (CRE32.27)
  - **CRR path:** unchanged (all A-IRB use modelled CCFs regardless of is_revolving)
  - `_ensure_columns` now adds `is_revolving=False` default when column absent (conservative: non-revolving)
- **File:Line:** `engine/ccf.py:257-277` (A-IRB CCF gate), `engine/ccf.py:186` (is_revolving default)
- **Spec ref:** PRA PS1/26 Art. 166D(1)(a), CRE32.27, `docs/specifications/crr/credit-conversion-factors.md`
- **Tests:** 11 new unit tests in `test_ccf.py` (TestAIRBCCFBasel31Revolving): non-revolving MR/MLR/LR use SA, revolving uses modelled with floor, revolving FR uses SA 100%, null is_revolving defaults to non-revolving, missing column defaults to non-revolving, CRR ignores revolving flag, mixed batch test. 4 existing tests in `test_basel31_engine.py` updated (added is_revolving=True; FR test updated to expect SA 100% per Art. 166D carve-out). All 2634 tests pass. Test count: 2634 (was 2623).

### P1.4 Basel 3.1 approach restrictions not enforced (Art. 147A)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** PRA PS1/26 Art. 147A approach restrictions now enforced at two levels:
  - **Permission level** (`IRBPermissions.full_irb_b31()`): Sovereign/PSE/MDB/RGLA → SA only, Institution → FIRB only, Equity → SA only. `CalculationConfig.basel_3_1()` now automatically selects B31 permissions when `permission_mode=IRB`.
  - **Classifier level** (`_determine_approach_and_finalize()`): IPRE/HVCRE → Slotting only (overrides model permissions), FSE corporate → FIRB only (no A-IRB), Large corporate (>GBP 440m) → FIRB only (no A-IRB). Null `is_financial_sector_entity` defaults to non-FSE (permissive).
  - **Schema**: Added `is_financial_sector_entity` boolean to counterparty schema
  - **Fixture**: `CORP_AIRB_001` revenue reduced from GBP 800m to GBP 200m (below B31 large corporate threshold) so A-IRB acceptance tests correctly test non-large-corporate behavior
- **File:Line:** `contracts/config.py:527-583` (full_irb_b31), `contracts/config.py:598-603` (__post_init__), `engine/classifier.py:118-127` (constants), `engine/classifier.py:805-830` (B31 restrictions), `data/schemas.py:162` (FSE field)
- **Spec ref:** PRA PS1/26 Art. 147A
- **Tests:** 44 new unit tests in `test_b31_approach_restrictions.py`: 11 permission tests, 4 config integration tests, 2 sovereign SA-only, 3 quasi-sovereign SA-only, 4 institution FIRB-only, 5 IPRE/HVCRE slotting-only, 5 FSE FIRB-only, 6 large corporate FIRB-only, 2 no-IRB-data fallback, 2 absent FSE column. Test count: 2591 (was 2545).
- **Limitation:** Art. 147A(1)(d) quasi-sovereign consolidation (RGLA/PSE/MDB with 0% RW classified as sovereign) is handled at permission level (SA-only for all quasi-sovereign classes), not by dynamic 0% RW check. Institutions with financial_institution entity_type are already routed to INSTITUTION exposure class (FIRB-only); FSE restriction catches corporates that are financial sector entities.

### P1.5 IRB guarantor PD substitution for expected loss (CRR path)
- **Status:** [~] Basel 3.1 implemented; CRR not implemented
- **Impact:** Under CRR Art. 161(3), when an IRB guarantor provides unfunded credit protection, EL should use the guarantor's PD for the protected portion. The CRR code path in `engine/irb/guarantee.py:467-484` only adjusts EL for SA guarantors (line 475: `guarantor_approach == "sa"`). IRB guarantor EL is left unchanged under CRR. The Basel 3.1 parameter substitution path (lines 440-465) correctly blends IRB EL using guarantor PD.
- **Evidence:** `tests/unit/irb/test_irb_el_guarantee.py:136-160` explicitly tests and documents gap with docstring "PD substitution not yet implemented".
- **File:Line:** `engine/irb/guarantee.py:467-484`
- **Spec ref:** CRR Art. 161(3) / CRE36. `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** In the CRR branch of `_adjust_expected_loss()`, apply guarantor PD substitution for IRB guarantors.
- **Tests needed:** Update `test_irb_guarantor_el_unchanged` to expect adjusted EL.

### P1.6 Junior charges for residential RE loan-splitting (Art. 124F(2))
- **Status:** [ ] Not modelled
- **Impact:** Under Basel 3.1, the 55% secured ratio threshold for residential RE loan-splitting should be reduced when a junior/second charge exists. `b31_risk_weights.py:49` has explicit comment: "Junior charges (Art. 124F(2)) reduce the 55% threshold but are not yet modelled." Both `b31_residential_rw_expr()` (line 228) and `b31_commercial_rw_expr()` (line 285) hardcode `0.55` with no lien position adjustment.
  **Additional scope from agent findings:** Also missing:
  - Art. 124G(2) junior charge **1.25x multiplier** for residential income-producing
  - Art. 124H(2) other counterparties max/min formula for CRE
  - Art. 124I(3) junior charge **1.25x/1.375x multipliers** for CRE income-producing
  - Art. 124L counterparty type table for RRE residual RW: `b31_risk_weights.py:261` caps at 75% for all types, but Art. 124L specifies: natural person/retail SME=75%, other SME (unrated)=85%, social housing=max(75%, unsecured RW), other=full unsecured CP RW
- **File:Line:** `engine/sa/b31_risk_weights.py:49,228,285`
- **Spec ref:** PRA PS1/26 Art. 124F(2), Art. 124G(2), Art. 124H(2), Art. 124I(3). `docs/specifications/crr/sa-risk-weights.md`
- **Fix:** Add `prior_charge_amount` or `lien_position` field to loan/facility schema. In `b31_residential_rw_expr()`, reduce the 55% threshold by the prior charge amount. Also implement the **pari passu pro-rata formula** from Art. 124F(2)(b): eligible amount = `(55% - prior_charges) x (charges_not_held / total_pari_passu_charges)`. Implement RW multipliers for junior positions per Art. 124G(2) and Art. 124I(3).
- **Tests needed:** Unit tests for junior charge, pari passu, and RW multiplier scenarios. Acceptance tests in B31-A.

### P1.7 Financial Collateral Simple Method (Art. 222)
- **Status:** [ ] Not implemented
- **Impact:** CRR Art. 222 / CRM method taxonomy Part A allows a Simple Method for financial collateral (20% RW floor, SA-only). Only the Comprehensive (haircut) Method is implemented. COREP generator at line 1046 confirms: "simple method not implemented -> always 0".
- **File:Line:** `engine/crm/collateral.py`, `reporting/corep/generator.py:1046`
- **Spec ref:** `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Add configuration option to select Simple vs Comprehensive. Implement Simple Method in `engine/crm/collateral.py`. Update COREP row 0070.
- **Tests needed:** Unit and acceptance tests.

### P1.8 LGDFloors residential vs commercial RE distinction
- **Status:** [~] Field exists but routing incomplete
- **Impact:** `LGDFloors.get_floor()` at `config.py:125` maps `CollateralType.IMMOVABLE` solely to `self.commercial_real_estate`. There is no `CollateralType` member for residential RE. `PropertyType` has RESIDENTIAL/COMMERCIAL but `CollateralType` only has IMMOVABLE. Currently both corporate LGD floors are 10% so no incorrect result, but code cannot distinguish when floors diverge (and retail RRE floor IS 5% per P1.2).
- **File:Line:** `contracts/config.py:125`
- **Spec ref:** PRA PS1/26 Art. 161(5), Art. 164(4)
- **Fix:** Either split `CollateralType.IMMOVABLE` into `IMMOVABLE_RESIDENTIAL` / `IMMOVABLE_COMMERCIAL`, or add a secondary lookup parameter to `get_floor()`.
- **Tests needed:** Unit tests for residential vs commercial collateral LGD floor.

### P1.9 Output Floor -- OF-ADJ, portfolio-level application, U-TREA/S-TREA
- **Status:** [ ] Not implemented (4 sub-issues)
- **Impact:** The output floor implementation has four related gaps:
  - **(a) OF-ADJ not implemented:** PRA PS1/26 Art. 92 para 2A defines `TREA = max(U-TREA, x * S-TREA + OF-ADJ)` where `OF-ADJ = 12.5 x (IRB_T2 - IRB_CET1 - GCRA + SA_T2)`. No code computes any OF-ADJ component. **Additional from PDF comparison:** `IRB_CET1` must include Art. 40 deductions (additional shortfall provisions), not just Art. 36(1)(d). `IRB_T2` = Art. 62(d) excess provisions (a T2 **credit/addition**, not a deduction — the spec description is backwards). `SA_T2` = Art. 62(c) general credit risk adjustments. The Art. 62(d) IRB T2 credit is **capped at 0.6% of IRB credit RWAs** — this cap is binding for many institutions and must be applied.
  - **(b) Floor is exposure-level, not portfolio-level:** `_floor.py:67-96` applies `max(rwa_pre_floor, floor_rwa)` per exposure row. The regulatory formula operates on portfolio-level totals (U-TREA vs x × S-TREA). Exposure-level flooring **systematically overstates** capital for institutions near but above the aggregate floor.
  - **(c) U-TREA/S-TREA not computed:** Neither `u_trea` nor `s_trea` fields exist in `_floor.py`, `_schemas.py`, or `AggregatedResultBundle`. The `OF 02.01` COREP template (requiring 4-column U-TREA/S-TREA comparison) cannot be produced.
  - **(d) Transitional floor rates are permissive, not mandatory:** Art. 92 para 5 says institutions "may apply" the 60/65/70% transitional rates — firms can voluntarily use 72.5% from day one. `OutputFloorConfig` should document this optionality.
- **File:Line:** `engine/aggregator/_floor.py:67-96`
- **Spec ref:** `docs/specifications/output-reporting.md` lines 28-46, PRA PS1/26 Art. 92 para 2A/3A/5
- **Fix:** Restructure `_floor.py` to compute portfolio-level U-TREA and S-TREA, apply the max formula with OF-ADJ (including Art. 62(d) 0.6% IRB T2 cap and Art. 40 CET1 deductions), then distribute the floor add-on back to exposures pro-rata. Add U-TREA/S-TREA to `AggregatedResultBundle` or a new `OutputFloorBundle`. Requires capital-tier data (EL shortfall, equity deductions, GCRA). Fix spec description of IRB_T2 from "deductions" to "T2 credit (excess provisions)".
- **Tests needed:** Unit tests for portfolio-level floor, OF-ADJ components, IRB T2 0.6% cap. Update acceptance tests in B31-F.

### P1.9a EL T2 credit cap uses pre-floor IRB RWA
- **Status:** [~] Potentially understated
- **Impact:** `_el_summary.py:36-64` computes `t2_credit_cap = total_irb_rwa x 0.006` using pre-floor IRB results. Under a binding floor, the regulatory capital base should arguably use final (floored) RWA. CRR Art. 62(d) references IRB credit-risk RWA in the context of final capital requirements. Current code understates the cap when floor binds, allowing less T2 credit.
- **File:Line:** `engine/aggregator/_el_summary.py:36-64`
- **Spec ref:** CRR Art. 62(d)
- **Fix:** Compute T2 credit cap using post-floor IRB RWA. Requires floor computation to run before EL summary.
- **Tests needed:** Unit test with binding floor verifying cap basis.

### P1.10 Unfunded credit protection transitional (PRA Rule 4.11)
- **Status:** [ ] Not implemented
- **Impact:** PRA PS1/26 Rule 4.11 provides transitional treatment for unfunded credit protection entered into before 1 Jan 2027: such protection continues to receive CRR treatment until 30 June 2028. No code references Rule 4.11 or inception-date-based CRM treatment selection.
- **File:Line:** No code exists
- **Spec ref:** `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Add `protection_inception_date` field. In CRM and guarantee processing, when `is_b31=True` and `reporting_date < 2028-07-01` and `inception_date < 2027-01-01`, apply CRR treatment.
- **Tests needed:** Unit tests for transitional date logic.

### P1.11 CRM maturity mismatch hardcoded exposure maturity (Art. 238)
- **Status:** [~] Simplified -- conservative but incorrect
- **Impact:** `engine/crm/haircuts.py:312` hardcodes T=5 years in `(pl.col("coll_maturity") - 0.25) / (5.0 - 0.25)` instead of using actual `exposure_maturity` column (available in data). CRR Art. 238 formula is `CVAM = CVA x (t - 0.25) / (T - 0.25)` where T = residual maturity of exposure (capped at 5). T=5 gives most conservative result; shorter-maturity exposures get too much CRM benefit reduction.
- **File:Line:** `engine/crm/haircuts.py:312`
- **Spec ref:** CRR Art. 238 / `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Replace `5.0` with `pl.col("exposure_maturity").clip(upper_bound=5.0)`. Guard against null (fall back to 5.0).
- **Tests needed:** Unit tests for maturity mismatch with varying exposure maturities.

### P1.12 SCRA enhanced sub-grade and short-term maturity weights (Basel 3.1)
- **Status:** [ ] Not implemented
- **Impact:** Basel 3.1 SCRA has four rows: Grade A (40%), **Grade A enhanced (30%, CET1 >= 14% AND leverage >= 5%)**, Grade B (75%), Grade C (150%). Short-term (<=3m) weights also differ: Grade A = 20%, Grade B = 50%. `SCRAGrade` enum (`domain/enums.py:295`) only has A/B/C -- no enhanced sub-grade. `B31_SCRA_RISK_WEIGHTS` dict (`b31_risk_weights.py:133-137`) has three entries. No <=3m maturity fork anywhere for SCRA. The SA calculator (`calculator.py:504-509`) tests A/B/default-C with no enhanced-A path. Data tables agent confirms no short-term institution CQS table exists for Art. 121(2) <=3m domestic currency.
- **File:Line:** `domain/enums.py:295` (SCRAGrade), `engine/sa/b31_risk_weights.py:133-137`, `engine/sa/calculator.py:504-509`
- **Spec ref:** `docs/specifications/crr/sa-risk-weights.md` (SCRA table), PRA PS1/26 Art. 120A
- **Fix:** Add `A_ENHANCED` to `SCRAGrade` enum. Add short-term SCRA weights to `b31_risk_weights.py`. Fork SA calculator on residual maturity <=3m for institution exposures.
- **Tests needed:** Unit tests for enhanced-A and short-term maturity SCRA paths.

### P1.13 CRE general "other counterparties" formula (Art. 124H)
- **Status:** [ ] Not implemented
- **Impact:** For CRE general (non-income-producing), Basel 3.1 specifies two distinct treatments: **natural person/SME** uses loan-splitting at 55% with 60% secured weight, but **other counterparties** (e.g. rated corporates) use `max(60%, min(counterparty_RW, income-producing_RW))`. Code at `b31_commercial_rw_expr()` (`b31_risk_weights.py:285-314`) applies loan-splitting unconditionally. No `is_natural_person`/`is_sme` fork exists. Comment at `b31_risk_weights.py:86-88` acknowledges "Other counterparties".
- **File:Line:** `engine/sa/b31_risk_weights.py:285-314`
- **Spec ref:** PRA PS1/26 Art. 124H, `docs/specifications/crr/sa-risk-weights.md`
- **Fix:** Add counterparty type check. For non-natural-person/non-SME, apply the max/min formula.
- **Tests needed:** Unit tests for both counterparty types. Acceptance test in B31-A.

### P1.14 "Other Real Estate" exposure class (Art. 124J)
- **Status:** [ ] Not implemented
- **Impact:** RE that doesn't meet Art. 124A qualifying criteria has three treatments under Basel 3.1: income-dependent = 150%, RESI non-dependent = counterparty RW, CRE non-dependent = max(60%, counterparty RW). No `OTHER_RE` exposure class or risk weight logic exists. COREP generator at `generator.py:663` confirms gap. Also blocks COREP rows 0350-0354 (see P2.5).
- **File:Line:** `engine/sa/calculator.py`, `reporting/corep/generator.py:663`
- **Spec ref:** PRA PS1/26 Art. 124J, `docs/specifications/crr/sa-risk-weights.md`
- **Fix:** Add "other RE" classification to classifier. Add risk weight logic to SA calculator.
- **Tests needed:** Unit and acceptance tests.

### P1.15 Rated SA specialised lending fallback (Art. 122A(3))
- **Status:** [ ] Not implemented
- **Impact:** Rated specialised lending exposures under SA should use the **corporate CQS table** (Art. 122A(3)), not the SL-specific weights. Code at `calculator.py:528-533` enters the SL branch whenever `sl_type` is non-null, and `b31_sa_sl_rw_expr()` always returns type-specific weights regardless of CQS. A rated SL exposure with CQS 3 gets 100% (SL weight) instead of 75% (corporate CQS 3).
- **File:Line:** `engine/sa/calculator.py:528-533`
- **Spec ref:** PRA PS1/26 Art. 122A(3)
- **Fix:** In SA calculator, check if exposure has a valid CQS before entering the SL-specific branch. If rated, use corporate CQS table.
- **Tests needed:** Unit tests for rated vs unrated SL exposures.

### P1.16 CRR unrated institution standard risk weight (Art. 120)
- **Status:** [~] UK treatment correct; EU standard wrong
- **Impact:** Under CRR, EU standard for unrated institutions is **100%**. UK gets 40% (derived from sovereign CQS 2). `crr_risk_weights.py:77` maps `CQS.UNRATED -> 0.40` in `INSTITUTION_RISK_WEIGHTS_STANDARD`, same as UK. Should be 100% for standard (non-UK).
- **File:Line:** `data/tables/crr_risk_weights.py:77`
- **Spec ref:** CRR Art. 120(2)
- **Fix:** Set `INSTITUTION_RISK_WEIGHTS_STANDARD[CQS.UNRATED] = Decimal("1.00")`. The UK-specific table already correctly has 40%.
- **Tests needed:** Unit test for EU-standard unrated institution RW.

### P1.17 Unrated covered bond derivation table not wired (CRR Art. 129)
- **Status:** [~] Table defined but unused
- **Impact:** `COVERED_BOND_UNRATED_DERIVATION` table at `crr_risk_weights.py:279-287` maps issuer institution RW to covered bond RW (20%->10%, 50%->25%, 100%->50%). But `calculator.py:551-563` uses SCRA grade shortcut and defaults to 20% when no grade exists. The derivation table is never used. SA calculator agent confirms: hardcoded 20% at `calculator.py:662`.
- **File:Line:** `data/tables/crr_risk_weights.py:279-287`, `engine/sa/calculator.py:551-563,662`
- **Spec ref:** CRR Art. 129(5)
- **Fix:** Wire derivation table into covered bond RW calculation. Look up issuer institution RW and derive covered bond RW per the table.
- **Tests needed:** Unit tests for unrated covered bond derivation.

### P1.18 Defaulted RESI RE always-100% exception (Basel 3.1 Art. 124F)
- **Status:** [ ] Not implemented
- **Impact:** Under Basel 3.1, defaulted general residential RE (non-income-dependent) gets **100% flat** regardless of provision coverage. Code at `calculator.py:454-461` applies provision-based test uniformly for all exposure classes (100%/150% based on 50% threshold -- but see P1.51 for threshold bug). No fork for RESI RE type.
- **File:Line:** `engine/sa/calculator.py:454-461`
- **Spec ref:** PRA PS1/26 Art. 124F, `docs/specifications/crr/sa-risk-weights.md`
- **Fix:** Add exception in defaulted branch: if RESI RE (general, non-income-dependent), apply 100% flat.
- **Tests needed:** Unit test for defaulted RESI RE under Basel 3.1.

### P1.19 Payroll/pension loan retail category (Basel 3.1 Art. 123)
- **Status:** [ ] Not implemented
- **Impact:** Basel 3.1 introduces a 35% risk weight for payroll/pension loans (loans repaid directly from salary or pension). No `is_payroll_loan` flag exists in the schema, no 35% RW branch in the SA calculator. This is a new Basel 3.1 retail sub-category per PRA PS1/26 Art. 123.
- **File:Line:** `data/schemas.py` (no field), `engine/sa/calculator.py` (no branch)
- **Spec ref:** `docs/framework-comparison/key-differences.md` (Retail Exposures table)
- **Fix:** Add `is_payroll_loan` boolean to facility schema. In SA calculator, when `is_b31=True` and `is_payroll_loan`, apply 35% RW.
- **Tests needed:** Unit tests in SA calculator. Acceptance test in B31-A.

### P1.20 Revolving maturity change (Basel 3.1 Art. 162(2A)(k))
- **Status:** [ ] Not implemented
- **Impact:** Under Basel 3.1, IRB effective maturity (M) for revolving exposures must use the **maximum contractual termination date** of the facility, not the repayment date of the current drawing (CRR approach). This typically increases M, leading to higher maturity adjustments and capital. The current maturity calculation in `engine/irb/formulas.py` does not distinguish revolving from non-revolving for maturity purposes. PRA PS1/26 Art. 162(2A)(k) is explicit: "for revolving exposures, M shall be determined using the maximum contractual termination date of the facility."
  **Spec fix (2026-04-06):** firb-calculation.md corrected — removed incorrect "1 year" maturity default, replaced with "maximum contractual termination date" per Art. 162(2A)(k).
- **File:Line:** `engine/irb/formulas.py`
- **Spec ref:** PRA PS1/26 Art. 162(2A)(k), `docs/specifications/crr/firb-calculation.md`
- **Fix:** Add `contractual_termination_date` to facility schema. In IRB maturity calculation, when `is_b31=True` and `is_revolving=True`, use termination date to derive M instead of drawing repayment date.
- **Tests needed:** Unit tests for revolving vs non-revolving maturity under Basel 3.1.

### P1.21 A-IRB CCF floor enforcement (CRE32.27 -- 50% of SA CCF)
- **Status:** [x] Implemented
- **Impact:** Under Basel 3.1, A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type (CRE32.27).
- **File:Line:** `engine/ccf.py:247-251`
- **Evidence:** `airb_ccf = pl.max_horizontal(ccf_modelled_expr.fill_null(sa_ccf), sa_ccf * 0.5)` — correctly implements the 50% floor. Comment at line 245 says "with Basel 3.1 floor (CRE32.27)".
- **Verified:** 2026-04-06 by code audit agent.

### P1.22 IRB maturity default inconsistency (5.0 vs 2.5)
- **Status:** [x] Complete
- **Impact:** Both locations in `engine/irb/namespace.py` now default to 2.5 years (CRR Art. 162(2) supervisory default). Pre-existing test expectations corrected.
- **File:Line:** `engine/irb/namespace.py`
- **Spec ref:** CRR Art. 162(2)
- **Fixed:** 2026-04-06

### P1.23 Duplicated IRB defaulted treatment code
- **Status:** [~] Divergence risk
- **Impact:** IRB defaulted treatment (K=0 for FIRB, K=max(0,LGD-BEEL) for AIRB) is implemented in TWO places: inline in `formulas.py:325-378` (scalar path) and separately in `adjustments.py:34-129` (vectorized path). The pipeline uses only the `adjustments.py` version via `namespace.py:618`. The `formulas.py` version is functionally identical but creates divergence risk if one is updated without the other. IRB engine agent confirms: `apply_irb_formulas` is legacy/redundant function exported from `__init__.py`; production uses namespace chain.
- **File:Line:** `engine/irb/formulas.py:325-378`, `engine/irb/adjustments.py:34-129`, `engine/irb/__init__.py:34`
- **Spec ref:** CRR Art. 158(5)/(6)
- **Fix:** Remove the inline defaulted treatment from `formulas.py:apply_irb_formulas()` or extract to a shared function. Consider removing the legacy `apply_irb_formulas` export entirely.
- **Tests needed:** Verify pipeline behavior unchanged after refactor.

### P1.24 Non-investment-grade corporate 135% risk weight (Art. 122(6)(b))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Art. 122(6) IG assessment is now an explicit config election (`use_investment_grade_assessment`). When active: unrated IG corporates → 65% (Art. 122(6)(a)), non-IG → 135% (Art. 122(6)(b)). When inactive (default): all unrated corporates → 100%. The 65% path is now gated behind the election flag to enforce the paired 65%/135% regulatory requirement — institutions cannot cherry-pick the IG benefit without the non-IG penalty.
- **File:Line:** `contracts/config.py` (use_investment_grade_assessment flag), `data/tables/b31_risk_weights.py` (B31_CORPORATE_NON_INVESTMENT_GRADE_RW constant), `engine/sa/calculator.py` (65%/135% when-chain gated behind config flag)
- **Spec ref:** PRA PS1/26 Art. 122(6)(a)-(b)
- **Tests:** 8 new/updated unit tests in `test_b31_sa_risk_weights.py`: IG 65% with assessment, non-IG 135%, flag-off default 100%, null IG treated as non-IG, rated corp unaffected, SME unaffected.

### P1.25 Non-regulatory retail 100% risk weight (Art. 123(3)(c))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Summary:** Added 100% risk weight path for `qualifies_as_retail=False` retail exposures in BOTH Basel 3.1 and CRR branches of the SA calculator. Added `B31_RETAIL_NON_REGULATORY_RW` constant to `b31_risk_weights.py`. The non-regulatory retail 100% branch is inserted BEFORE the generic 75% retail fallback in the when-chain. Null `qualifies_as_retail` defaults to qualifying (75% RW) — conservative assumption when flag is absent. 6 new unit tests: non-regulatory 100%, regulatory still 75%, non-regulatory QRRE 100%, transactor qualifying still 45%, null defaults to qualifying, CRR non-regulatory 100%.
- **File:Line:** `engine/sa/calculator.py` (B31 branch ~line 559, CRR branch ~line 670), `data/tables/b31_risk_weights.py:152`
- **Spec ref:** PRA PS1/26 Art. 123(3)(c), Art. 123A

### P1.26 Short-term institution ECRA/SCRA tables (Art. 120/121)
- **Status:** [ ] Not implemented
- **Impact:** Institutions with residual maturity <=3 months get reduced risk weights under both ECRA and SCRA:
  - ECRA rated <=3m (Table 4): CQS 1-5 all = 20%, CQS 6 = 150%
  - Short-term ECAI (Table 4A): CQS 1=20%, 2=50%, 3=100%, other=150%
  - SCRA <=3m: Grade A=20%, Grade B=50% (already noted in P1.12 for SCRA)
  - Trade finance <=6m: same as <=3m treatment
  No residual maturity check exists anywhere in the SA calculator for institution exposures.
- **File:Line:** `engine/sa/calculator.py` (no maturity check for institutions)
- **Spec ref:** PRA PS1/26 Art. 120 Tables 4/4A, Art. 121(5)
- **Fix:** Add `residual_maturity` column check in institution risk weight logic. Apply short-term tables when <=3m (or <=6m for trade finance).
- **Tests needed:** Unit tests for short-term vs long-term institution exposures.

### P1.27 Sovereign RW floor for FX unrated institution exposures (Art. 121(6))
- **Status:** [ ] Not implemented
- **Impact:** Under CRR/Basel 3.1, unrated institution exposures denominated in a foreign currency (not local currency of debtor's jurisdiction) cannot receive a risk weight lower than the sovereign RW of the institution's jurisdiction. Exception: self-liquidating trade items with original maturity <1 year. No sovereign-floor check exists in the SA calculator or SCRA logic. Classifier and SA calculator agents both confirm: no sovereign-floor check exists anywhere.
- **File:Line:** `engine/sa/calculator.py` (no sovereign-floor check)
- **Spec ref:** PRA PS1/26 Art. 121(6)
- **Fix:** After computing institution SCRA RW, apply `max(scra_rw, sovereign_rw)` when exposure currency != institution's local currency.
- **Tests needed:** Unit tests for FX vs domestic currency unrated institution exposures.

### P1.28 Output floor -- IRB corporate SA RW choice (Art. 122(8))
- **Status:** [ ] Not implemented
- **Impact:** When computing the SA-equivalent RWA for the output floor, IRB institutions must choose between (a) 100% flat for all unrated corporates, or (b) 65%/135% based on investment-grade assessment (Art. 122(6)). This is a configuration choice that must be declared to the PRA. No such option exists in `CalculationConfig` or the output floor code.
- **File:Line:** `contracts/config.py` (CalculationConfig), `engine/aggregator/_floor.py`
- **Spec ref:** PRA PS1/26 Art. 122(8)
- **Fix:** Add configuration flag for output floor corporate SA treatment. Implement in floor SA-RWA calculation.
- **Tests needed:** Unit tests for both output floor corporate treatment options.

### P1.29 Basel 3.1 SA "Other Commitments" 40% CCF category (Art. 111)
- **Status:** [ ] Not implemented
- **Impact:** Basel 3.1 introduces a fifth SA CCF category: "other commitments" at **40%**, distinct from unconditionally cancellable (10%). `ccf.py:82-95` only handles FR (100%), MR (50%), MLR (20%), LR (10%). No `OTHER_COMMIT` member in `RiskType` enum (`domain/enums.py:330-363`). `CommitmentType.COMMITTED` (enums.py:321) documents "40% or higher CCF" but is not wired into CCF calculation. Exposures falling into this bucket currently default to MR (50%) -- an overstatement.
- **File:Line:** `engine/ccf.py:82-95`, `domain/enums.py:330-363,321`
- **Spec ref:** `docs/specifications/crr/credit-conversion-factors.md` Basel 3.1 SA Changes
- **Fix:** Add `OTHER_COMMIT` to `RiskType` enum. Add 40% branch to `sa_ccf_expression()`. Map `CommitmentType.COMMITTED` to the new category.
- **Tests needed:** Unit tests for 40% CCF category in SA Basel 3.1.

### P1.30 CRM method selection decision tree (Art. 191A)
- **Status:** [ ] Not implemented
- **Impact:** Basel 3.1 Art. 191A defines a formal four-part CRM method selection: CCR/non-CCR split, on-BS netting, FCCM vs FCSM election, Foundation Collateral Method for immovable property/receivables/other physical under IRB, life insurance/institutional instrument method. `crm/processor.py` hardwires Comprehensive Method for funded CRM and risk-weight/parameter substitution for unfunded. No `crm_method` configuration or election hook.
  **Missing CRM sub-methods confirmed by code inspection:**
  - (a) FCSM (Art. 222) — 20% RW floor, SA-only, qualifying repo 0% (Art. 222(4)/(6)). COREP `generator.py:1046` confirms always 0.
  - (b) Life insurance method (Art. 232) — surrender-value-based haircut + insurer RW substitution. No `life_insurance` collateral type exists.
  - (c) Credit-linked notes (Art. 218) — funded credit protection with embedded issuer credit risk. No CLN handling in collateral processing.
  - (d) Art. 227 zero-haircut conditions — supervised institutions in repo agreements with daily revaluation/margining under standard master agreements. No code references Art. 227.
  - (e) Partial protection tranching (Art. 234) — structured protection covering only part of the loss range. Not modelled.
  - (f) Foundation Collateral Method for IRB (immovable property/receivables/other physical). Not distinct from FCCM.
- **File:Line:** `engine/crm/processor.py`, `engine/crm/collateral.py`, `engine/crm/constants.py`
- **Spec ref:** PRA PS1/26 Art. 191A, `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** Add CRM method selector to `CalculationConfig` or `CRMProcessorProtocol`. Implement method routing in processor. Add missing collateral types (CLN, life insurance).
- **Tests needed:** Unit tests for method selection routing and each sub-method.

### P1.31 SME supporting factor silent per-exposure fallback (CRR Art. 501)
- **Status:** [~] Silent correctness issue
- **Impact:** `supporting_factors.py:231-249` aggregates drawn amounts at counterparty level for the EUR 2.5m SME threshold. When `counterparty_reference` is absent, code silently falls back to per-exposure drawn amounts with no warning. This can **under-apply the threshold** -- individual exposures may appear under EUR 2.5m when the counterparty aggregate is above it, producing an incorrectly low supporting factor (0.7619 instead of 0.85 or vice versa).
- **File:Line:** `engine/sa/supporting_factors.py:231-249`
- **Spec ref:** CRR Art. 501, `docs/specifications/crr/supporting-factors.md` line 39
- **Fix:** Record a `CalculationError` when `counterparty_reference` is missing and fallback fires. Consider making the field mandatory for SME exposures.
- **Tests needed:** Unit test for missing counterparty_reference with aggregate above threshold.

### P1.32 F-IRB supervisory LGD: FSE 45% vs non-FSE corporate 40% (Art. 161(1))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** PRA PS1/26 Art. 161(1)(a) vs (aa) FSE/non-FSE distinction now implemented:
  - **FSE senior unsecured:** 45% under Basel 3.1 (Art. 161(1)(a)) — unchanged from CRR
  - **Non-FSE corporate senior unsecured:** 40% under Basel 3.1 (Art. 161(1)(aa))
  - **Covered bonds:** 11.25% (Art. 161(1)(d)) added to both CRR and Basel 3.1 tables
  - Under CRR, all senior unsecured remains 45% (no FSE distinction)
  - `cp_is_financial_sector_entity` column (from P1.4) now used for LGD routing
  - Null FSE flag defaults to non-FSE (40% — permissive/conservative)
  Three layers updated: data tables (`crr_firb_lgd.py`, `constants.py`), CRM collateral (`collateral.py` both no-collateral and collateralised paths), IRB namespace (`namespace.py` apply_firb_lgd)
- **File:Line:** `data/tables/crr_firb_lgd.py` (FSE key + covered_bond + lookup), `engine/crm/constants.py` (FSE + covered_bond + COVERED_BOND_TYPES), `engine/crm/collateral.py` (FSE-aware LGDU in both paths), `engine/irb/namespace.py` (FSE-aware apply_firb_lgd)
- **Spec ref:** PRA PS1/26 Art. 161(1)(a), (aa), (d)
- **Tests:** 22 new unit tests: 7 FSE CRM processor tests (TestFSESupervisoryLGD), 4 covered bond tests (TestCoveredBondLGD), 5 lookup dispatch tests (TestLookupFIRBLGDFSE), 6 namespace tests (B31 FSE/non-FSE/CRR + covered bond dict + FSE key). All pass. Test count: 2613 (was 2591).
- **Limitation:** Covered bond F-IRB LGD 11.25% is in the data tables and lookup functions but not yet wired into the pipeline for exposure-level covered bond classification (covered bonds are currently SA-only per Art. 147A). FSE routing in the collateralised path uses the same `cp_is_financial_sector_entity` column for LGDU blending.

### P1.33 Mortgage RW floor is 10%, not 15% (Art. 154(4A)(b))
- **Status:** [x] Complete
- **Impact:** `PostModelAdjustmentConfig.basel_3_1()` now defaults `mortgage_rw_floor` to `Decimal("0.10")` (10%) per PRA PS1/26 Art. 154(4A)(b). Pre-existing test expectations corrected.
- **File:Line:** `contracts/config.py`
- **Spec ref:** PRA PS1/26 Art. 154(4A)(b)
- **Fixed:** 2026-04-06

### P1.34 SME correlation adjustment uses EUR parameters under B31 (Art. 153(4))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** PRA PS1/26 Art. 153(4) mandates GBP-native parameters for the SME correlation adjustment. Previously the code always used the CRR EUR-based formula (EUR 50m/5m/45 with FX conversion). Now:
  - **Formula** (`_correlation_expr_from_pd`): Added `is_b31` parameter. When True, uses GBP turnover directly: `s = max(4.4, min(turnover_GBP, 44))`, `adjustment = 0.04 × (1 - (s - 4.4) / 39.6)`. CRR path unchanged (EUR conversion via `eur_gbp_rate`).
  - **All call sites** updated: `_polars_correlation_expr`, `_parametric_irb_risk_weight_expr`, `apply_irb_formulas`, `namespace.calculate_correlation`, `namespace.apply_all_formulas`, `guarantee._apply_b31_parameter_substitution`, and scalar `calculate_correlation` all propagate `is_b31=config.is_basel_3_1`.
  - **Classifier** (`classifier.py`): SME classification threshold now uses GBP 44m directly under B31 (was EUR 50m × 0.8732 ≈ GBP 43.66m). Both Phase 3 (`_classify_sme_and_retail`) and Phase 4 (`_reclassify_corporate_to_retail`) updated.
  - **Boundary fix**: Firms with turnover between GBP 43.66m and GBP 44m now correctly classified as SME under B31 (previously missed due to EUR-converted threshold).
- **File:Line:** `engine/irb/formulas.py:423-490` (correlation expr), `engine/irb/namespace.py:390-394,614-618` (namespace calls), `engine/irb/guarantee.py:296-301` (guarantee call), `engine/classifier.py:424-430,549-555` (classifier thresholds)
- **Spec ref:** PRA PS1/26 Art. 153(4)
- **Tests:** 10 new unit tests in `test_basel31_engine.py` (TestB31SMECorrelation): floor max adjustment, below floor, at threshold, above threshold, midpoint partial, no FX conversion, CRR uses FX, B31 vs CRR numerical difference, namespace integration, boundary 43.66m vs 44m. All existing CRR tests (9 correlation + 4 namespace) unchanged. Test count: 2136 unit (was 2126).

### P1.35 Slotting expected loss rates (Table B) missing
- **Status:** [~] Spec fixed; code not implemented
- **Impact:** PRA PS1/26 Art. 158(6), Table B defines slotting EL rates:
  - OF/PF/CF/IPRE: Strong <2.5y=0%, Strong >=2.5y=0.4%, Good <2.5y=0.4%, Good >=2.5y=0.8%, Satisfactory=2.8%, Weak=8%, Default=50%
  - HVCRE: Strong=0.4%, Good=0.8%, Satisfactory=2.8%, Weak=8%, Default=50%
  The slotting engine (`engine/slotting/`) computes risk weights but not expected loss. No `el_rate` or Table B data exists anywhere in the slotting module. This affects IRB EL comparison and T2 credit cap for slotting exposures.
  **Spec fix (2026-04-06):** `slotting-approach.md` Table B corrected from flat BCBS CRE33 values (5%/10%/35%/50%/50%) to correct PRA maturity-dependent values. Previous BCBS values were 6-12x too high for Strong/Good categories.
- **File:Line:** `engine/slotting/` (no EL code)
- **Spec ref:** PRA PS1/26 Art. 158(6), Table B. `docs/specifications/crr/slotting-approach.md`
- **Fix:** Add Table B EL rates to slotting data. Compute EL in slotting calculator. Include in EL summary aggregation. **Aggregator wiring note:** `aggregator.py:112` calls `compute_el_portfolio_summary(irb_results)` with only IRB results — slotting results are a separate branch. When slotting EL is implemented, the aggregator must also pass slotting EL into the portfolio summary to include it in T2 credit / CET1 deduction calculations.
- **Tests needed:** Unit tests for slotting EL by category and grade. Integration test for slotting EL in portfolio EL summary.

### P1.37 CCF commitment-to-issue lower-of rule (Art. 111(1)(c))
- **Status:** [ ] Not implemented
- **Impact:** Art. 111(1)(c) states that when a commitment is to issue another off-balance-sheet item (e.g., a commitment to issue a guarantee), the CCF is the **lower** of the CCF for the underlying OBS item and the CCF for the commitment type. No code implements this rule.
- **File:Line:** `engine/ccf.py`
- **Spec ref:** PRA PS1/26 Art. 111(1)(c)
- **Fix:** Add logic to detect commitment-to-issue-OBS items and apply the lower-of CCF rule.
- **Tests needed:** Unit test for nested commitment CCF.

### P1.38 Output floor GCRA 1.25% cap and entity-type carve-outs (Art. 92)
- **Status:** [ ] Not implemented
- **Impact:** Two output floor gaps from PDF analysis:
  - **(a) GCRA cap:** GCRA component of OF-ADJ is capped at **1.25% of S-TREA** (para 3A amounts, not U-TREA). No cap logic exists.
  - **(b) Entity-type carve-outs (CRITICAL):** Art. 92 para 2A defines THREE entity categories where the floor formula applies: (i) stand-alone UK institution on individual basis, (ii) ring-fenced body in sub-consolidation group on sub-consolidated basis, (iii) non-international-subsidiary CRR consolidation entity on consolidated basis. All OTHER entities use U-TREA (no floor):
    - Para 2A(b): Non-ring-fenced institution on sub-consolidated basis → U-TREA (no floor)
    - Para 2A(c): Ring-fenced body at individual level, or non-stand-alone institution → U-TREA (no floor)
    - Para 2A(d): International subsidiary CRR consolidation entity → U-TREA (no floor)
    This is **materially wrong for major UK retail banks** (ring-fenced bodies) and international subsidiaries. No entity-type check exists anywhere in the code.
  - **(c) Reporting basis (Rule 2.2A):** Output floor reporting must be on the same basis as Art. 92 para 3A — not always individual basis. Ring-fenced bodies report sub-consolidated; international subsidiaries do not report at all.
- **File:Line:** `engine/aggregator/_floor.py`, `contracts/config.py` (no entity-type config)
- **Spec ref:** PRA PS1/26 Art. 92 para 2A(a)-(d), Reporting (CRR) Part Rule 2.2A
- **Fix:** Add GCRA 1.25% cap to OF-ADJ computation (P1.9). Add `entity_type` / `reporting_basis` configuration to `CalculationConfig`. Implement floor applicability check based on entity type and consolidation basis. Add reporting basis configuration for COREP output.
- **Tests needed:** Unit tests for GCRA cap. Unit tests for each entity-type carve-out. Tests for reporting basis conditionality.

### P1.39 CRM haircut liquidation period dependency not modelled (Art. 224)
- **Status:** [ ] Not implemented
- **Impact:** Art. 224 Tables 1-4 define three liquidation-period-dependent haircut columns: **20-day** (secured lending), **10-day** (capital market transactions), **5-day** (repo/SFT). Code uses single haircut values per instrument type with no liquidation period dimension. FX mismatch haircut also varies: 11.3%/8%/5.66% by period -- code uses flat 8%. Equity haircuts differ similarly. B31 `equity_other = 0.35` in code doesn't match any PDF column exactly (10-day = 30%, 20-day = 42.4%).
- **File:Line:** `data/tables/crr_haircuts.py`, `engine/crm/haircuts.py`
- **Spec ref:** PRA PS1/26 Art. 224 Tables 1-4, Art. 226
- **Fix:** Add `liquidation_period` parameter to haircut lookup. Restructure haircut tables to include all three columns. Default to 10-day for capital market transactions.
- **Tests needed:** Unit tests for each liquidation period.

### P1.40 CRM maturity mismatch additional ineligibility conditions (Art. 237(2))
- **Status:** [ ] Not implemented
- **Impact:** Art. 237(2) adds two ineligibility conditions beyond the existing 3-month residual maturity test: (a) **original maturity of protection < 1 year** -> not eligible where maturity mismatch exists; (b) exposures with **1-day IRB maturity floor** (Art. 162(3)) -> protection ineligible. Code only checks 3-month residual maturity.
- **File:Line:** `engine/crm/haircuts.py`
- **Spec ref:** PRA PS1/26 Art. 237(2)
- **Fix:** Add original maturity and 1-day M floor checks to maturity mismatch evaluation in `haircuts.py`.
- **Tests needed:** Unit tests for each ineligibility condition.

### P1.41 Credit derivative restructuring exclusion haircut (Art. 233(2))
- **Status:** [ ] Not implemented
- **Impact:** Art. 233(2): if a credit derivative does not include restructuring as a credit event, protection is **reduced by 40%** (protection value capped at 60% of notional). No restructuring-exclusion haircut exists in guarantee or credit derivative processing.
- **File:Line:** `engine/crm/` (guarantee/credit derivative processing)
- **Spec ref:** PRA PS1/26 Art. 233(2)
- **Fix:** Add `includes_restructuring` flag to credit derivative schema. Apply 40% reduction when `False`.
- **Tests needed:** Unit tests for restructuring-included vs excluded.

### P1.44 Infrastructure supporting factor not applied to slotting exposures
- **Status:** [ ] Not applied
- **Impact:** Under CRR, infrastructure project finance may qualify for 0.75 infrastructure supporting factor (Art. 501a). The slotting pipeline (`pipeline.py:608-613`) calls `calculate_branch` -> `_standardize_branch_output` with no hook for `SupportingFactorCalculator`. The supporting factor is only applied to SA/IRB branches, not slotting. Infrastructure PF exposures in the slotting branch silently miss the 0.75 factor.
- **File:Line:** `engine/pipeline.py:608-613`
- **Spec ref:** CRR Art. 501a
- **Fix:** Apply `SupportingFactorCalculator` to slotting output in pipeline, or document that slotting exposures are excluded from supporting factors with regulatory justification.
- **Tests needed:** Unit test for infrastructure PF with slotting approach.

### P1.45 SCRA null grade defaults to Grade A (most favourable) instead of Grade C
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Removed `.is_not_null()` guard on SCRA grade check in the B31 SA calculator's unrated institution branch. Null SCRA grade now falls through the inner when-chain to `otherwise(scra_c_rw)` = 150% (Grade C), the most conservative treatment. Previously, null SCRA fell through to the CQS table default of 40% (Grade A equivalent), causing capital understatement on any institution exposure with missing SCRA data. Covered bond path was already correct (null SCRA → 100% = Grade C derivation).
- **File:Line:** `engine/sa/calculator.py:498-511`
- **Spec ref:** PRA PS1/26 Art. 120A
- **Tests:** Existing test expectation corrected (40% → 150%). 2 new tests added: null SCRA RWA verification (institution), null SCRA covered bond (100%). Test count: 2360 (was 2358).

### P1.48 CRR defaulted exposure secured/unsecured split (Art. 127)
- **Status:** [ ] Not implemented
- **Impact:** CRR Art. 127 requires splitting defaulted exposures into secured and unsecured portions -- the collateral RW applies to the secured part, while the provision-coverage 100%/150% test applies only to the unsecured portion. Code at `sa/calculator.py:590-600` applies the provision-coverage RW to the entire EAD without splitting. This can overstate capital for well-collateralised defaulted exposures.
- **File:Line:** `engine/sa/calculator.py:590-600`
- **Spec ref:** CRR Art. 127
- **Fix:** Split defaulted EAD into secured (collateral RW) and unsecured (provision-coverage RW) portions.
- **Tests needed:** Unit tests for collateralised defaulted exposures.

### P1.49 Art. 110A due diligence obligation (new SA requirement)
- **Status:** [ ] Not started
- **Impact:** PRA PS1/26 Art. 110A introduces a new mandatory due diligence obligation for SA credit risk. Institutions must perform due diligence to ensure risk weights appropriately reflect the risk of the exposure. No spec file, no code, no validation exists for this requirement. While primarily a governance/process requirement, it may have calculable implications (e.g., if due diligence reveals risk weight is not adequate, the institution must apply a higher weight).
- **File:Line:** No code exists
- **Spec ref:** PRA PS1/26 Art. 110A
- **Fix:** At minimum, document the requirement in the SA risk weight spec. Optionally, add a `due_diligence_override_rw` field to schema allowing institutions to override SA risk weights upward where due diligence indicates inadequacy. Add validation that flags exposures where no due diligence assessment has been performed.
- **Tests needed:** Validation tests for due diligence flag. Documentation test that spec covers Art. 110A.

### P1.50 Art. 169A/169B LGD Modelling Collateral Method (new Basel 3.1 AIRB method)
- **Status:** [ ] Not started
- **Impact:** PRA PS1/26 Art. 169A/169B introduces a new AIRB method for recognising collateral directly in LGD estimates (LGD Modelling Collateral Method). This is an alternative to the Foundation Collateral Method for AIRB firms. No spec file exists, no code exists. Firms using AIRB with collateral would need this method to correctly model LGD. Without it, AIRB collateral recognition may be incomplete.
- **File:Line:** No code exists; would go in `engine/irb/` or `engine/crm/`
- **Spec ref:** PRA PS1/26 Art. 169A/169B
- **Fix:** Create spec document for LGD Modelling Collateral Method. Implement in IRB calculator as an alternative collateral recognition path for AIRB exposures. Should integrate with CRM method selection (P1.30).
- **Tests needed:** Unit tests for LGD modelling collateral method. Acceptance tests comparing FCCM vs LGD modelling results.

### P1.55 Art. 134 "Other Items" risk weights missing (cash 0%, items in collection 20%, residual lease)
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Art. 134 "Other Items" risk weights now fully implemented with sub-type routing via entity_type:
  - `other_cash` / `other_gold`: 0% (Art. 134(1)/(4))
  - `other_items_in_collection`: 20% (Art. 134(3))
  - `other_tangible`: 100% (Art. 134(2))
  - `other_residual_lease`: 1/t × 100% where t = max(residual_maturity_years, 1) (Art. 134(6))
  - Generic OTHER (unrecognized sub-type): 100% (Art. 134(2))
  Both CRR and B31 SA calculator paths handle all sub-types identically (Art. 134 is unchanged by PRA PS1/26).
- **File:Line:** `data/tables/crr_risk_weights.py` (5 constants: OTHER_ITEMS_CASH_RW, GOLD, COLLECTION, TANGIBLE, DEFAULT), `engine/sa/calculator.py` (OTHER branches in both B31 and CRR when-chains), `engine/classifier.py` (5 entity_type → OTHER mappings), `data/schemas.py` (5 entity_type values added to VALID_ENTITY_TYPES)
- **Spec ref:** CRR Art. 134, PRA PS1/26 Art. 134
- **Tests:** 24 new unit tests: 6 data table/constant tests, 10 CRR calculator tests, 8 B31 calculator tests. All pass. Test count: 1979 unit (was 1955).
- **Limitation:** Repo-style transactions (Art. 134(5), asset RW) and nth-to-default credit derivatives (Art. 134(5), Art. 266-270) not implemented — these require underlying asset risk weight lookup which is architecturally non-trivial.

### P1.59 IRB_SIMPLE_EQUITY_RISK_WEIGHTS exported under B31 config
- **Status:** [ ] Not started (deferred)
- **Impact:** Under Basel 3.1, equity exposures must use SA only (Art. 147A removes IRB for equity). The IRB Simple equity risk weight table (`crr_equity_rw.py`) is still exported and available under B31 configuration. While the equity calculator does not invoke it for B31 (P1.42 now implements B31 SA weights), the presence of the export is misleading and could lead to incorrect usage. Additionally, the `EquityType.SUBORDINATED_DEBT` enum member needed for the 150% subordinated debt weight (Art. 133(5)) is not yet added -- deferred from P1.42.
- **File:Line:** `data/tables/crr_equity_rw.py`, `contracts/config.py`
- **Spec ref:** PRA PS1/26 Art. 147A, Art. 133(5)
- **Fix:** Gate the IRB_SIMPLE_EQUITY_RISK_WEIGHTS export behind a CRR-only check, or remove from B31 config namespace. Add a CalculationError if IRB equity is attempted under B31. Add `EquityType.SUBORDINATED_DEBT` enum member and wire 150% weight.
- **Tests needed:** Unit test that B31 config does not expose IRB equity weights. Unit test for subordinated debt 150% RW.

### P1.60 No B31 FIRB LGD DataFrame generator
- **Status:** [ ] Not started
- **Impact:** B31 FIRB LGD values exist as a Python dict in `constants.py` but there is no DataFrame generator equivalent to the CRR version (`crr_firb_lgd.py`). The CRM module uses the dict directly rather than a structured DataFrame. This is inconsistent with the pattern used for other data tables and makes it harder to validate/test LGD values systematically.
- **File:Line:** `data/tables/crr_firb_lgd.py` (CRR version exists); `engine/irb/constants.py` (B31 dict only)
- **Spec ref:** PRA PS1/26 Art. 161(1)
- **Fix:** Create `b31_firb_lgd.py` DataFrame generator following the `crr_firb_lgd.py` pattern. Include FSE vs non-FSE distinction (45% vs 40% per P1.32). Add covered bond LGD 11.25%.
- **Tests needed:** Unit tests for B31 FIRB LGD DataFrame contents and FSE/non-FSE routing.

### P1.61 CIU look-through and mandate-based approach incomplete (Art. 132A/132B)
- **Status:** [~] Fallback implemented; look-through/mandate partial
- **Impact:** The completed items claim CIU look-through/mandate/fallback as done, but the equity spec (FR-1.7b) marks CIU treatment as **Partial**. Art. 132A (look-through) requires: (a) sufficient knowledge of underlying holdings, (b) risk-weighting each underlying per its own exposure class, (c) leverage gross-up of underlying RWs. Art. 132B (mandate-based) requires: (a) assuming maximum mandate allocation to highest-risk classes, (b) applying RW to the hypothetical portfolio. The 250% CIU fallback works, but look-through and mandate-based paths are not fully implemented -- they require decomposing fund holdings into sub-exposures and routing each through the SA/IRB calculator, which is architecturally non-trivial.
- **File:Line:** `engine/equity/calculator.py` (CIU treatment)
- **Spec ref:** CRR Art. 132A/132B, `docs/specifications/crr/equity-approach.md` (FR-1.7b)
- **Fix:** Implement full look-through decomposition (Art. 132A) with per-holding risk weight calculation and leverage adjustment. Implement mandate-based maximum-risk-allocation (Art. 132B). Both need integration with SA calculator for underlying exposure RW lookup.
- **Tests needed:** Unit tests for CIU look-through with mixed underlying exposures. Unit tests for mandate-based approach with leverage. Acceptance tests comparing look-through vs mandate vs fallback.

### P1.62 Art. 128 high-risk items 150% risk weight missing
- **Status:** [ ] Not started
- **Impact:** CRR Art. 128 defines items attracting 150% risk weight including: (a) investments in venture capital firms, (b) investments in AIFs not treated as equity, (c) CIU holdings not treated under Art. 132-132B, (d) equity instruments in a trading book exempted from the trading book regime. The SA calculator has no high-risk exposure branch. These exposures would default to their base exposure class RW (potentially 100% or lower) instead of the regulatory 150%.
- **File:Line:** `engine/sa/calculator.py` (no high-risk branch); `domain/enums.py` (ExposureClass has no HIGH_RISK member)
- **Spec ref:** CRR Art. 128, PRA PS1/26 Art. 128
- **Fix:** Add HIGH_RISK to ExposureClass enum or add a `is_high_risk` flag. Add 150% branch in SA calculator.
- **Tests needed:** Unit tests for high-risk item classification and 150% RW application.

### P1.63 A-IRB revolving 100% SA carve-out from own-estimate permission (Art. 166D(1)(a))
- **Status:** [ ] Not started
- **Impact:** PRA PS1/26 Art. 166D(1)(a) permits A-IRB own CCF estimates only for revolving commitments "which would not be subject to a 100% conversion factor" under SA Table A1. This means revolving facilities that fall under SA Table A1 Row 2 (100% CCF — factoring, repos, forward deposits) cannot use own-estimate CCFs even though they are revolving. No code checks for this 100% SA carve-out when applying A-IRB CCF permission. Without this, a revolving documentary LC or revolving repo-like facility at 100% SA could be incorrectly modelled under A-IRB with a lower own-estimate CCF, **understating capital**.
- **File:Line:** `engine/ccf.py` (A-IRB CCF path)
- **Spec ref:** PRA PS1/26 Art. 166D(1)(a)
- **Fix:** In A-IRB CCF path, when `is_revolving=True`, check if the SA CCF for the item type is 100%. If so, do not permit own-estimate CCF — use SA 100% instead.
- **Tests needed:** Unit tests for revolving items with 100% SA CCF carve-out.

### P1.64 A-IRB EAD floor tests incomplete — 2 of 3 tests missing (Art. 166D(5))
- **Status:** [ ] Not started
- **Impact:** Art. 166D(5) defines three EAD floor tests for A-IRB: (a) CCF floor = 50% × SA CCF, (b) facility-level EAD floor = on-BS EAD + 50% × F-IRB off-BS EAD, (c) fully-drawn EAD floor = on-BS EAD ignoring Art. 166D. Only floor (a) is documented in the spec and partially implemented. Floors (b) and (c) are entirely absent. Without these, A-IRB models could produce EADs below regulatory minimums for partially or fully drawn revolving facilities.
- **File:Line:** `engine/ccf.py` (no facility-level EAD floor)
- **Spec ref:** PRA PS1/26 Art. 166D(5)(b)-(c)
- **Fix:** Implement facility-level EAD floor (b) and fully-drawn EAD floor (c) in the A-IRB EAD computation path.
- **Tests needed:** Unit tests for each of the three floor conditions.

### P1.65 SA Table A1 Row 2 (100% CCF) instrument types incomplete
- **Status:** [ ] Not started
- **Impact:** SA Table A1 Row 2 (100% CCF) covers: factoring/invoice discount facilities, outright forward purchase agreements, asset sale and repurchase agreements, forward deposits, partly-paid shares/securities, and other commitments with "certain drawdowns." The spec and code describe this row as "commitments to lend, purchase securities, provide guarantees" which conflates it with Row 1 (guarantees). Factoring, repos, and forward deposits would be incorrectly assigned to the 40-50% buckets instead of 100%, **understating capital**.
- **File:Line:** `engine/ccf.py` (SA CCF assignment); `docs/specifications/crr/credit-conversion-factors.md` (Row 2 description)
- **Spec ref:** PRA PS1/26 Art. 111 Table A1 Row 2
- **Fix:** Add instrument-type classification logic to CCF assignment. Map factoring, repos, forward deposits, and partly-paid shares to 100% CCF. Add `commitment_type` refinements for these instrument types.
- **Tests needed:** Unit tests for each Row 2 instrument type.

### P1.66 Basel 3.1 QRRE threshold wrong — GBP 100k in code, should be GBP 90k (Art. 147(5A)(c))
- **Status:** [x] Complete — false positive on the value; per-facility vs portfolio-level remains a separate consideration
- **Verified:** 2026-04-06
- **Description:** `RetailThresholds.basel_3_1()` already correctly uses `qrre_max_limit=Decimal("90000")` (GBP 90k per Art. 147(5A)(c)). The dataclass default of 100000 remains in the field definition but is never used directly — the factory method always overrides it with 90000. The value bug was a false positive. The per-facility vs portfolio-level check (classifier applies per-facility rather than checking the max single-obligor across the sub-portfolio) remains as a separate architectural consideration and is not a value correctness bug.
- **File:Line:** `contracts/config.py` (RetailThresholds.basel_3_1), `engine/classifier.py` (per-facility check)
- **Spec ref:** PRA PS1/26 Art. 147(5A)(c)

### P1.67 SA specialised lending misclassified as separate exposure class (Art. 112)
- **Status:** [~] Spec fixed; code may still use separate class
- **Impact:** Under SA, specialised lending is a **corporate sub-type** (Art. 112(1)(g)) with distinct risk weights via Art. 122A-122B. It is NOT a separate SA exposure class — Art. 112 Table A2 has no row for SL. Code at `domain/enums.py` has `SPECIALISED_LENDING` as a separate `ExposureClass` member, and the classifier routes SL exposures as a distinct class. Under IRB, SL is a legitimate separate sub-class (Art. 147(8)), but under SA it should be corporate with SL-specific risk weight lookup.
  **Spec fix (2026-04-06):** hierarchy-classification.md corrected — removed invented Art. 112(1)(ga), SL now documented as corporate sub-type. Table A2 reduced from 17 to 16 rows.
- **File:Line:** `domain/enums.py` (ExposureClass.SPECIALISED_LENDING), `engine/classifier.py`, `engine/sa/calculator.py`
- **Spec ref:** PRA PS1/26 Art. 112 Table A2
- **Fix:** Under SA, SL exposures should be classified as CORPORATE and then sub-routed to SL risk weights. The separate `SPECIALISED_LENDING` class may need to remain for IRB routing, but SA classification should go through CORPORATE. Review classifier and SA calculator to ensure correct routing.
- **Tests needed:** Unit tests for SA SL classification as corporate sub-type.

### P1.68 IRB guarantee LGD substitution incomplete (Art. 236)
- **Status:** [ ] Not implemented
- **Impact:** Under F-IRB, when a guarantee provides credit protection, the **covered portion's LGD** should be set to the supervisory LGD of a senior unsecured claim on the guarantor (40% non-FSE / 45% FSE under B31 per Art. 161(1)). Under A-IRB, the covered LGD should be the firm's own LGD estimate for a senior unsecured claim on the guarantor. `engine/crm/guarantees.py:120-148` propagates guarantor PD/CQS for attribute lookup but never sets a distinct `lgd_covered` for the guaranteed portion. The IRB guarantee module (`engine/irb/guarantee.py`) applies parameter substitution on PD but the LGD substitution is incomplete. This **understates capital** for IRB exposures where the guarantor's unsecured LGD is higher than the exposure's collateralised LGD.
- **File:Line:** `engine/crm/guarantees.py:120-148`, `engine/irb/guarantee.py`
- **Spec ref:** PRA PS1/26 Art. 236, `docs/specifications/crr/credit-risk-mitigation.md`
- **Fix:** In the CRM guarantee processing or IRB guarantee module, set the covered portion's LGD to the supervisory LGD of the guarantor (F-IRB) or own-estimate LGD of the guarantor (A-IRB). Requires `is_financial_sector_entity` flag for FSE/non-FSE LGD distinction.
- **Tests needed:** Unit tests for IRB guarantee LGD substitution under F-IRB and A-IRB.

### P1.69 Receivables haircut 20% in code, should be 40% (Art. 230); equity_other 25% vs 30%
- **Status:** [x] Complete (receivables fixed; equity_other deferred pending liquidation period verification)
- **Fixed:** 2026-04-06
- **Impact:** Basel 3.1 receivables haircut corrected from 20% to 40% per PRA PS1/26 Art. 230(2) explicit HC table. The code confused HC (collateral haircut = 40%) with LGDS (secured LGD = 20%). CRR value kept at 20% as an approximation of the C*/C** threshold mechanism (Table 5) since CRR Art. 230 does not use HC-based formula.
- **File:Line:** `data/tables/crr_haircuts.py` (B31 dict line 108, B31 DataFrame line 635)
- **Spec ref:** PRA PS1/26 Art. 230(2)
- **Tests:** 13 new unit tests: 11 in `test_crm_basel31.py` (TestBasel31ReceivablesHaircut class), 2 in `test_crr_tables.py` (receivables + other_physical dict assertions). All pass. Test count: 2531 (was 2519).
- **Equity_other deferred:** CRR equity_other (25%) and B31 equity_other (35%) discrepancy vs spec (30%) needs regulatory PDF verification per different liquidation periods (Art. 224 Tables 1-4). Cross-ref P1.39.
- **Note:** Under B31, the code still applies BOTH the 40% haircut AND the 1.25x overcollateralisation ratio, which is double-counting — PRA PS1/26 Art. 230 replaced the CRR C*/C** threshold mechanism with the HC-based formula. The OC ratio should not apply under B31. This is tracked separately (see spec warning in credit-risk-mitigation.md line 170-171).

### P1.70 Overcollateralisation 30% threshold applied globally, not per collateral type (Art. 230)
- **Status:** [~] Wrong aggregation level
- **Impact:** `engine/crm/collateral.py:557-569` checks `_raw_nf_a >= 0.30 * ead_gross` treating all non-financial collateral as one pool. Art. 230 requires the 30% minimum threshold to apply **per collateral type** (real estate separately, other physical separately, receivables separately). A mix of small RE + large other-physical could pass the combined test when individual types each fail their 30% threshold, allowing ineligible collateral to reduce EAD.
- **File:Line:** `engine/crm/collateral.py:557-569`
- **Spec ref:** PRA PS1/26 Art. 230
- **Fix:** Split the 30% threshold check to apply per non-financial collateral type rather than across the aggregated pool.
- **Tests needed:** Unit tests for mixed non-financial collateral pools where individual types fail the threshold.

### P1.71 CRR SA equity unlisted=250% and PE=250% in code, CRR Art. 133 says 150%/190%
- **Status:** [~] Needs regulatory verification
- **Impact:** `data/tables/crr_equity_rw.py:40-41` defines unlisted equity = 250% and PE/VC = 250%. CRR Art. 133 specifies unlisted = **150%** (Art. 133(3)) and PE/VC = **190%** (Art. 133(4)). The 250% values are Basel 3.1 standard equity weights, not CRR. Acceptance tests (`test_unlisted_250_percent`, `test_private_equity_250_percent`) are written to match the code, so they would also need updating. **Needs verification against UK-onshored CRR Art. 133 text** before confirming as a code bug vs spec error.
- **File:Line:** `data/tables/crr_equity_rw.py:40-41`, `engine/equity/calculator.py:459-463`
- **Spec ref:** CRR Art. 133(3)-(4), `docs/specifications/crr/equity-approach.md` lines 28-30
- **Fix:** If spec is correct (150%/190%): update `crr_equity_rw.py` and acceptance tests. If code is correct: update spec. Regulatory PDF verification required.
- **Tests needed:** Verify against CRR legislation. Update whichever is wrong.

### P1.72 CIU fallback 1250% in code, should be 150% (CRR) / 250%-400% (B31)
- **Status:** [x] Complete — already resolved
- **Impact:** Code audit (2026-04-06) confirmed CRR fallback = 150% (pl.lit(1.50)) and B31 fallback = 250% (pl.lit(2.50)). All 16 CIU unit tests pass with these values. The 1250% reference in test docstrings is a documentation-only issue. The 150% CRR value aligns with Art. 132 generic equity treatment for CIUs; the 1250% Art. 132(2) deduction treatment is tracked separately. Also: CIU look-through (`_resolve_look_through_rw` at lines 345-425) does not apply the leverage multiplier required by Art. 132A, and the mandate-based approach (lines 472-480) does not implement the conservative fill-up algorithm from Art. 132B.
- **File:Line:** `engine/equity/calculator.py:466-470`, `345-425`, `472-480`
- **Spec ref:** CRR Art. 132(2), PRA PS1/26 Art. 133, `docs/specifications/crr/equity-approach.md` §Fallback/Look-Through/Mandate-Based

### P1.73 Gold haircut 0% in code/spec, PRA Art. 224 Table 3 says 20%
- **Status:** [~] Needs regulatory PDF verification — code may be correct
- **Impact:** Code has 15% for gold haircut, which matches CRR Art. 224 (10-day liquidation period) per the CRM changes reference (crm-changes.md confirms CRR gold = 15%). The spec was corrected to 20% on 2026-04-06, but this may reflect the 20-day liquidation period value (Art. 224 Table 3 gives 20% at 10-day, 28.28% at 20-day, 14.14% at 5-day). If the code uses the 10-day period, 15% is the correct CRR value; the capital understatement claim was premature. The spec fix may have introduced a wrong value. Requires verification against the regulatory PDF to confirm which liquidation period the code targets.
  **Spec fix (2026-04-06):** credit-risk-mitigation.md corrected — gold haircut changed from 0% to 20% (may need re-verification).
- **File:Line:** `data/tables/crr_haircuts.py` (gold haircut entry)
- **Spec ref:** PRA PS1/26 Art. 224, Table 3
- **Fix:** Verify gold haircut value against regulatory PDF for 10-day liquidation period. Confirm whether 15% (code) or 20% (spec) is correct. Add liquidation-period variants (cross-ref P1.39).
- **Tests needed:** Unit test for gold collateral haircut confirming correct liquidation-period basis.

### P1.74 Main index equity haircut 15% in spec, PRA Art. 224 Table 3 says 20%
- **Status:** [~] Needs regulatory PDF verification — code may be correct
- **Impact:** Code has 15% (CRR) and 25% (B31) for main index equity haircut, both matching the CRM changes reference (crm-changes.md confirms CRR equity main index = 15% and B31 = 15%). The spec was corrected to 20% on 2026-04-06, but this may reflect the 20-day liquidation period value rather than the standard 10-day period. If the code uses the 10-day period, 15% may be the correct CRR value. The capital understatement claim was premature. Requires verification against the regulatory PDF to confirm which liquidation period applies.
  **Spec fix (2026-04-06):** credit-risk-mitigation.md corrected — main index equity haircut changed from 15% to 20% (may need re-verification).
- **File:Line:** `data/tables/crr_haircuts.py` (equity_main_index haircut entry)
- **Spec ref:** PRA PS1/26 Art. 224, Table 3
- **Fix:** Verify main index equity haircut against regulatory PDF for 10-day liquidation period. Confirm whether 15% (code/CRM reference) or 20% (spec correction) is correct. Cross-ref P1.39.
- **Tests needed:** Unit test for main index equity haircut confirming correct liquidation-period basis.

### P1.75 LGD* formula does not blend LGDU/LGDS — single LGD applied to residual
- **Status:** [~] Wrong formula in spec (fixed) — code needs verification
- **Impact:** The Foundation Collateral Method formula in Art. 230 blends LGDU (unsecured) and LGDS (secured) across the secured and unsecured portions: `LGD* = LGDU × (EU / E(1+HE)) + LGDS × (ES / E(1+HE))`. The previous spec formula `LGD* = LGD × (E*/E)` applies a single LGD to the residual fraction, which is only correct when LGDS = LGDU. For non-financial collateral (LGDS=20-25%, LGDU=40-45%), this produces wrong LGD* values. Code at `engine/crm/collateral.py` likely implements the old formula.
  **Spec fix (2026-04-06):** credit-risk-mitigation.md corrected with proper blending formula.
- **File:Line:** `engine/crm/collateral.py`
- **Spec ref:** PRA PS1/26 Art. 230 para 1
- **Fix:** Verify code implements LGDU/LGDS blending. If not, rework the collateral-adjusted LGD calculation.
- **Tests needed:** Unit tests for mixed LGDU/LGDS blending with non-financial collateral.

### P1.76 Corporate bond haircut table uses 3 maturity bands, PRA has 5 bands
- **Status:** [~] Wrong structure in spec (fixed) — code needs verification
- **Impact:** PRA Art. 224 Table 1 defines 5 maturity bands for corporate/institution bonds: ≤1yr, 1-3yr, 3-5yr, 5-10yr, >10yr. The spec previously used 3 bands (0-1yr, 1-5yr, 5+yr) which collapses 1-3yr and 3-5yr (understating 1-3yr haircut by 1-2pp per CQS) and omits >10yr entirely (CQS 1=12%, CQS 2-3=20%). Code likely uses the same collapsed structure.
  **Spec fix (2026-04-06):** credit-risk-mitigation.md corrected with 5 maturity bands.
- **File:Line:** `data/tables/crr_haircuts.py`
- **Spec ref:** PRA PS1/26 Art. 224, Table 1
- **Fix:** Verify and expand haircut table to 5 maturity bands. Cross-ref P1.39 (liquidation period).
- **Tests needed:** Unit tests for each maturity band including >10yr bonds.

### P1.77 Mixed collateral pool uses pro-rata allocation, Art. 231 requires sequential fill
- **Status:** [~] Wrong algorithm in spec (fixed) — code needs verification
- **Impact:** Art. 231 requires sequential (waterfall) allocation of collateral: `ES_i = min(C_i, E(1+HE) - sum(ES_k))`. The spec previously used pro-rata allocation (`E_i = E × C_i / sum(C_all)`). Sequential and pro-rata give different LGD* when total collateral < total exposure. The institution may choose ordering (most favourable = lowest LGDS first). Code at `engine/crm/collateral.py` likely implements pro-rata.
  **Spec fix (2026-04-06):** credit-risk-mitigation.md corrected with sequential fill formula.
- **File:Line:** `engine/crm/collateral.py`
- **Spec ref:** PRA PS1/26 Art. 231 para 1
- **Fix:** Verify and correct collateral allocation to use sequential fill. Allow ordering by LGDS.
- **Tests needed:** Unit tests for mixed pools where total collateral < exposure comparing sequential vs pro-rata.

### P1.78 FX mismatch haircut not applied to guarantee/CDS amounts (Art. 233(3-4))
- **Status:** [ ] Not started
- **Impact:** When a guarantee or credit derivative is denominated in a different currency from the exposure, the guaranteed amount must be reduced: `G* = G × (1 - H_fx)` where H_fx = 8% (10-day) scaled by Art. 226(1) if not daily revalued. The guarantee substitution code at `engine/crm/guarantees.py` does not apply any FX haircut to the guarantee amount. This **overstates protection value** for cross-currency guarantees.
  **Spec fix (2026-04-06):** New section "FX Mismatch for Guarantees/CDS" added to credit-risk-mitigation.md.
- **File:Line:** `engine/crm/guarantees.py`
- **Spec ref:** PRA PS1/26 Art. 233(3-4)
- **Fix:** Add FX mismatch check to guarantee processing. Apply H_fx reduction when guarantee currency ≠ exposure currency.
- **Tests needed:** Unit tests for cross-currency and same-currency guarantees.

### P1.81 Art. 159(3) two-branch EL shortfall/excess comparison not implemented
- **Status:** [ ] Not started
- **Impact:** Art. 159(3) requires that when non-defaulted EL exceeds non-defaulted provisions (A>B) AND defaulted provisions exceed defaulted EL (D>C) simultaneously, the shortfall and excess must be computed **separately**. The defaulted excess must NOT offset the non-defaulted shortfall. The current implementation uses a single combined comparison (`sum(el_shortfall)` vs `sum(el_excess)` across all exposures), which allows cross-subsidisation between defaulted and non-defaulted books. This **understates CET1 deductions** when both conditions hold simultaneously.
  **Spec fix (2026-04-06):** provisions.md updated with Art. 159(3) two-branch rule and warning.
- **File:Line:** `engine/irb/adjustments.py`, `engine/aggregator/`
- **Spec ref:** CRR Art. 159(3), `docs/specifications/crr/provisions.md`
- **Fix:** Split EL comparison into non-defaulted and defaulted pools. When A>B AND D>C, compute shortfall from non-defaulted pool only and excess from defaulted pool only.
- **Tests needed:** Unit tests for: (a) combined pool where only one condition holds, (b) simultaneous A>B AND D>C where cross-subsidisation would occur.

### P1.82 BEEL exception for A-IRB defaulted EL not implemented (Art. 158(5))
- **Status:** [ ] Not started
- **Impact:** Art. 158(5) specifies that for A-IRB defaulted exposures (PD=1), EL = BEEL (best estimate of expected loss), NOT PD × LGD (which gives 1 × LGD). F-IRB defaulted uses the standard formula. The code applies `PD × LGD × EAD` universally. Using LGD instead of BEEL overstates or understates EL depending on whether BEEL differs from LGD. No `beel` input field exists in the schema.
  **Spec fix (2026-04-06):** provisions.md updated with BEEL exception warning.
- **File:Line:** `engine/irb/adjustments.py`, `data/schemas.py` (missing `beel` field)
- **Spec ref:** PRA PS1/26 Art. 158(5)
- **Fix:** Add `beel` field to loan/exposure schema. For A-IRB defaulted exposures, use `BEEL × EAD` instead of `PD × LGD × EAD`. For F-IRB defaulted, keep standard formula.
- **Tests needed:** Unit tests for A-IRB defaulted EL using BEEL vs F-IRB defaulted using PD×LGD.

### P1.83 EL comparison pool 'B' excludes AVAs and own funds reductions (Art. 159(1))
- **Status:** [ ] Not started
- **Impact:** Art. 159(1) defines comparison pool 'B' as including: (i) general CRA, (ii) specific CRA for non-defaulted, (iii) additional value adjustments (AVAs per Art. 34), (iv) other own funds reductions. The code uses only `provision_allocated`. Banks with material AVA positions have their EL shortfall **overstated** because the AVA buffer is not included as an EL offset.
  **Spec fix (2026-04-06):** provisions.md updated with AVA warning.
- **File:Line:** `engine/irb/adjustments.py`, `data/schemas.py` (missing AVA field)
- **Spec ref:** CRR Art. 159(1), Art. 34
- **Fix:** Add `ava_amount` and `other_own_funds_reductions` fields to exposure/counterparty schema. Include in EL comparison pool B.
- **Tests needed:** Unit tests for EL comparison with and without AVAs.

### P1.84 T2 credit cap must use un-floored IRB RWA (Art. 62(d) / Art. 92(2A))
- **Status:** [~] Not explicitly documented in code
- **Impact:** The T2 credit cap = `total_irb_rwa × 0.006` (Art. 62(d)). For output-floor-bound banks, this must use **un-floored** (U-TREA) IRB RWA, not post-floor TREA. Using post-floor RWA would overstate the cap and allow too much T2 credit. The code uses `total_irb_rwa` which is pre-floor, but this is not documented or enforced.
  **Spec fix (2026-04-06):** provisions.md updated with "un-floored" clarification in T2 cap row.
- **File:Line:** `engine/aggregator/` (T2 cap computation)
- **Spec ref:** CRR Art. 62(d), Art. 92(2A)
- **Fix:** Add assertion/comment in aggregator confirming T2 cap uses pre-floor IRB RWA. If output floor code modifies `total_irb_rwa`, ensure the T2 cap computation receives the original un-floored value.
- **Tests needed:** Unit test verifying T2 cap uses pre-floor RWA when output floor binds.

### P1.79 CRR corporate PD floor 0.03% in code, CRR Art. 160(1) says 0.05%
- **Status:** [x] False positive — CRR value is correct
- **Verified:** 2026-04-06
- **Description:** The CRR PD floor of 0.03% (`Decimal("0.0003")`) in `PDFloors.crr()` is CORRECT per the original CRR Art. 160(1). The 0.05% floor is the Basel 3.1 value (PRA PS1/26 Art. 160(1) as amended). This distinction was already resolved and documented in P4.21. The code at `PDFloors.crr()` with `Decimal("0.0003")` is correct for the CRR framework; `PDFloors.basel_3_1()` correctly uses `Decimal("0.0005")`. No code change required.
- **File:Line:** `contracts/config.py:53,80-85`
- **Spec ref:** CRR Art. 160(1) (0.03%), PRA PS1/26 Art. 160(1) as amended (0.05%); see also P4.21

### P1.80 Corporate subordinated exposures get 50% LGD floor, should be 25% (Art. 161(5))
- **Status:** [x] Complete
- **Fixed:** 2026-04-06
- **Impact:** Both `_lgd_floor_expression` and `_lgd_floor_expression_with_collateral` now accept `has_exposure_class` parameter. When `exposure_class` column is available, the 50% subordinated floor is gated behind retail QRRE only (Art. 164(4)(b)(i)). Corporate/institution/sovereign subordinated exposures receive the standard 25% unsecured floor (Art. 161(5)), matching senior treatment. Backward-compatible: without exposure_class column, conservative 50% fallback is preserved.
- **File:Line:** `engine/irb/formulas.py:119-168` (both floor functions), `engine/irb/namespace.py:322-330,554-570` (callers pass has_exposure_class)
- **Spec ref:** PRA PS1/26 Art. 161(5) (corporate = 25%), Art. 164(4)(b)(i) (retail QRRE = 50%)
- **Tests:** 4 new unit tests in `test_basel31_engine.py`: corporate subordinated 25% with collateral_type, corporate subordinated 25% no collateral_type, retail QRRE subordinated 50% with exposure_class, corporate subordinated via namespace. All pass. Test count: 2535 (was 2531).

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
- **Status:** [x] Authored
- **Fix:** `docs/specifications/crr/equity-approach.md` created with CRR SA, B31 SA, IRB Simple, CIU treatment, transitional schedule, classification decision tree, and key scenarios.

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
- **Status:** [~] Multiple spec values wrong
- **Impact:** Comparison of IRB specs against PS1/26 PDF found:
  - `firb-calculation.md` was recently edited to say CRR PD floor = **0.05%** with a "Correction" warning -- but this correction is itself wrong. CRR Art. 160(1) specifies **0.03%** (3 basis points) for all classes. The 0.05% value is the *Basel 3.1* corporate floor, not CRR. Code at `config.py:80` correctly uses 0.03%. The spec's "Correction" box and the CRR column in Table (lines 64-69) need reverting to 0.03%. Also references Art. 163 (retail) instead of Art. 160 (corporate).
  - `airb-calculation.md` LGD floor table says "Unsecured (Subordinated): 50%" -- Art. 161(5) has **flat 25%** for all unsecured corporate. The 50% is retail QRRE (Art. 164(4)(b)(i)), not corporate.
  - `airb-calculation.md` mortgage RW floor corrected to 10% in spec, but **code** still defaults to 15% (see P1.33)
  - `firb-calculation.md` SME formula uses EUR 50m/5m/45 -- should be **GBP 44m/4.4m/39.6** under PS1/26
  - ~~Slotting EL rates (Table B) not documented in `slotting-approach.md`~~ (fixed 2026-04-06)
  - ~~Large FSE threshold (GBP 79bn per Art. 1.3) not mentioned in FI scalar spec~~ (fixed 2026-04-06)
  - Art. 146(3) (root PMA obligation) not referenced in PMA section
  - ~~Double default (Art. 153(3)) blanked in PS1/26~~ (fixed 2026-04-06 — added to airb-calculation.md)
  - ~~Art. 161(1A) wrong reference for subordinated LGD~~ (fixed 2026-04-06 — corrected to Art. 161(1)(b))
  - ~~Art. 161(4) cited in A-IRB LGD floors but blank in regulation~~ (fixed 2026-04-06 — corrected to Art. 161(5) only)
  - ~~Revolving maturity described as "1 year" default, should be "max contractual termination date"~~ (fixed 2026-04-06)
  - ~~Retail "other secured" LGD floor (Art. 164(4)(c)) absent from A-IRB spec~~ (fixed 2026-04-06)
  - ~~PMA sequencing (Art. 153(5A)/154(4A)) and unrecognised exposure adjustment not documented~~ (fixed 2026-04-06)
- **Fix:** Correct all spec values. Add missing tables and references.

### P4.17 Hierarchy-classification spec missing Art. 123A retail qualifying criteria
- **Status:** [x] Fixed
- **Impact:** `hierarchy-classification.md` now documents the correct two-path Art. 123A structure: (a) SME auto-qualifies, (b) natural persons need 3 conditions (product type, granularity, pool management). Previous spec incorrectly stated 4 criteria with a non-existent Art. 123A(d).
- **File:Line:** `docs/specifications/common/hierarchy-classification.md`
- **Spec ref:** PRA PS1/26 Art. 123A

### P4.18 Hierarchy-classification spec does not reference Art. 147A
- **Status:** [x] Fixed (with corrections)
- **Impact:** Art. 147A approach restriction table added to classification spec and corrected:
  - ALL FSEs are F-IRB only (not just "large FSEs > GBP 79bn" — that threshold is for correlation)
  - Quasi-sovereigns (RGLA, PSE, MDB, Int'l Org) are SA-only via Art. 147(3) consolidation
  - OF/PF/CF default is Slotting (not free choice); A-IRB requires explicit permission
  - Other general corporates default to F-IRB (A-IRB requires Art. 143(2A)/(2B) permission)
- **File:Line:** `docs/specifications/common/hierarchy-classification.md`

### P4.19 Exposure class priority ordering (Art. 112 Table A2) not documented
- **Status:** [x] Fixed (with corrections)
- **Impact:** Art. 112 Table A2 priority ordering added to classification spec. Key corrections:
  - **Removed invented Art. 112(1)(ga)** — specialised lending is NOT a separate SA exposure class; it is a corporate sub-type with distinct risk weights via Art. 122A-122B. Table A2 has 16 rows, not 17.
  - **Real estate** reference corrected from "(i), (j)" to "(i)" only — (j) is "exposures in default"
  - **MDB and international organisations** split into distinct SA classes (Art. 117 vs Art. 118)
- **Spec ref:** CRR Art. 112, PRA PS1/26 Art. 112

### P4.20 COREP C 08.02 PD bands use fixed buckets instead of firm-specific rating grades
- **Status:** [ ] Not started
- **Impact:** COREP reporting agent notes C 08.02 implementation uses 8 fixed PD buckets instead of firm-specific internal rating grades. The regulatory requirement is to report by the firm's own internal rating scale. Fixed buckets may not align with a firm's actual rating grade structure.
- **File:Line:** `reporting/corep/generator.py` (C 08.02 generation)
- **Spec ref:** PRA COREP reporting requirements
- **Fix:** Make PD band definitions configurable based on firm's internal rating grade structure. Add rating grade configuration to CalculationConfig or as a separate reporting config.
- **Tests needed:** Unit tests with custom PD band definitions.

### P4.21 firb-calculation.md CRR PD floor "correction" is itself wrong
- **Status:** [x] Fixed
- **Impact:** `docs/specifications/crr/firb-calculation.md` was recently edited to add a "Correction" warning box claiming CRR corporate PD floor = 0.05% (Art. 160(1)), stating that 0.03% is wrong. **This "correction" was incorrect.** CRR Art. 160(1) specifies **0.03%** (3 basis points) for all exposure classes -- this is the well-established CRR value confirmed by: (a) `key-differences.md` lines 92-98 (CRR column = 0.03%), (b) code at `config.py:80` (Decimal("0.0003")), (c) `technical-reference.md`. The 0.05% value is the **Basel 3.1** corporate floor (PRA Art. 160(1) as *amended*), not the current CRR floor.
- **File:Line:** `docs/specifications/crr/firb-calculation.md:55-69`
- **Resolution:** Reverted incorrect "Correction" warning. Restored CRR PD floor to 0.03%. Fixed CRR column in PD floor comparison table to show 0.03% for all classes. B31 column values correctly show differentiated floors.

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
- **Status:** [ ] Not started
- **Impact:** ~72 IRB unit tests total (30 in `tests/unit/irb/` + 42 in `crr/test_crr_irb.py`). The IRB engine is one of the most complex modules with `formulas.py`, `adjustments.py`, `namespace.py`, `config.py`, `guarantee.py`, and `calculator.py`. Key untested areas: correlation formulas, maturity adjustment, FI scalar application, PD floor enforcement, LGD floor enforcement, defaulted treatment branching, K formula edge cases. `irb/stats_backend.py` (44 lines, `normal_cdf`/`normal_ppf` wrappers) has **zero** test coverage.
- **File:Line:** `tests/unit/irb/` (only 3 test files)
- **Fix:** Add comprehensive unit tests for: (a) `irb/formulas.py` -- K formula, correlation, maturity adjustment; (b) `irb/adjustments.py` -- defaulted treatment, EL shortfall; (c) `irb/config.py` -- PD/LGD floor selection; (d) `irb/namespace.py` -- pipeline chain; (e) `irb/stats_backend.py` -- CDF/PPF wrappers. Target at least 150 IRB unit tests.
- **Tests needed:** This IS the test gap item.

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
- **Status:** [ ] Not started
- **Impact:** CRR has `test_scenario_crr_i_defaulted.py` (9 tests) but no B31 equivalent exists. Given the P1.51 bugs (threshold 50%→20%, denominator wrong), B31 defaulted acceptance tests are essential.
- **Fix:** Add B31 defaulted acceptance test scenario covering: provision threshold at 15%/20%/25%, RESI RE always-100% exception (P1.18), secured/unsecured split.

---

## Priority 6 -- Code Quality & Type Safety

### P6.1 Unparameterized `list` types in bundles and protocols
- **Status:** [~] Weakens type safety
- **Impact:** 12 bare `list` fields in `contracts/bundles.py` should be `list[CalculationError]`.
- **Fix:** Add `CalculationError` type parameter to all error list fields.

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
- **Status:** [~] Convention violation
- **Fix:** Change all 9 fields to `Decimal`.

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
- **Status:** [~] Silent failure
- **Impact:** `irb/adjustments.py:297-304` -- when `expected_loss` column is not present, function returns `el_shortfall=0, el_excess=0` with no warning. In pipelines where EL was not computed upstream (e.g., missing provision step), this silently zeros the EL shortfall rather than flagging missing computation. Affects T2 credit cap.
- **Fix:** Emit a `CalculationError` when `expected_loss` is absent but IRB exposures exist.

### P6.11 No `ApproachType.EQUITY` enum value
- **Status:** [~] Gap
- **Impact:** `ApproachType` enum (`enums.py:92-107`) has no EQUITY member. Equity exposures in loan/contingent tables get classified via standard SA/IRB approach assignment rather than being routed to the equity calculator. Only the separate `data.equity_exposures` LazyFrame bypasses this. This means equity positions in main tables go to SA/IRB, not the equity calculator.
- **Fix:** Add `ApproachType.EQUITY` and route equity-classified exposures in classifier.

### P6.12 QRRE classification silently disabled when columns absent
- **Status:** [~] Silent failure
- **Impact:** `classifier.py:412-416` sets `is_qrre = pl.lit(False)` when `is_revolving` or `facility_limit` columns are absent. No warning or error logged. All QRRE exposures would silently receive non-QRRE treatment (higher capital). Cross-ref P1.25 -- `qualifies_as_retail` defaults to True when no lending group data (`classifier.py:350-363`), masking non-regulatory retail.
- **Fix:** Record a `CalculationError` when QRRE columns are missing but retail exposures exist.

### P6.13 Dead `TYPE_CHECKING` block in config.py
- **Status:** [~] Dead code
- **Fix:** Remove.

### P6.14 Missing enum values across domain/enums.py
- **Status:** [ ] Not started
- **Impact:** Multiple enum classes are missing values needed for full regulatory coverage:
  - `ExposureClass`: SECURITISATION, INTERNATIONAL_ORGANISATION, CIU (CIU may exist as fallback only)
  - `SCRAGrade`: A_ENHANCED (needed for P1.12)
  - `RiskType`: OTHER_COMMIT (needed for P1.29 40% CCF)
  - `EquityType`: SUBORDINATED_DEBT, LEGISLATIVE (needed for P1.42 B31 equity weights)
  - `CollateralType`: misaligned with VALID_COLLATERAL_TYPES string set
- **File:Line:** `domain/enums.py` (multiple classes)
- **Fix:** Add all missing enum members. Ensure consistency between enum members and string-based validation sets. Note: A_ENHANCED and OTHER_COMMIT are prerequisites for P1.12 and P1.29 respectively.
- **Tests needed:** Contract tests verifying enum completeness against regulatory tables. Unit tests for new enum values in risk weight lookups.

### P6.15 8 missing schema fields for plan items
- **Status:** [ ] Not started
- **Impact:** Implementation plan items reference schema fields that do not yet exist in `data/schemas.py`:
  - `prior_charge_amount` (P1.6 junior charges)
  - `protection_inception_date` (P1.10 unfunded CRM transitional)
  - `contractual_termination_date` (P1.20 revolving maturity)
  - `is_payroll_loan` (P1.19 payroll/pension retail)
  - `is_financial_sector_entity` (P1.4/P1.32 FSE flag)
  - `includes_restructuring` (P1.41 credit derivative restructuring)
  - `due_diligence_override_rw` (P1.49 Art. 110A)
  - `liquidation_period` (P1.39 haircut dependency)
- **File:Line:** `data/schemas.py`
- **Fix:** Add all missing fields with appropriate types and defaults. Some fields are prerequisites for their corresponding P1 items.
- **Tests needed:** Schema validation tests for new fields.

### P6.16 risk_type/scra_grade/ciu_approach not in COLUMN_VALUE_CONSTRAINTS
- **Status:** [ ] Not started
- **Impact:** Three columns that accept enum-like values are not validated by COLUMN_VALUE_CONSTRAINTS in `data/schemas.py`. Invalid values in these columns would pass schema validation silently, potentially causing incorrect risk weight assignment downstream.
- **File:Line:** `data/schemas.py` (COLUMN_VALUE_CONSTRAINTS dict)
- **Fix:** Add validation entries for `risk_type` (against RiskType enum values), `scra_grade` (against SCRAGrade enum values), and `ciu_approach` (against valid CIU approach strings).
- **Tests needed:** Unit tests for invalid values in these columns being caught by validation.

### P6.17 Pipeline _run_crm_processor() is dead code
- **Status:** [ ] Not started
- **Impact:** `pipeline.py` contains `_run_crm_processor()` which is never called -- the pipeline uses a different CRM invocation path. Dead code creates maintenance burden and confusion.
- **File:Line:** `engine/pipeline.py` (_run_crm_processor function)
- **Fix:** Remove the dead function. Verify no tests reference it.
- **Tests needed:** Verify pipeline tests pass after removal.

### P6.18 get_crm_unified_bundle not declared in CRMProcessorProtocol
- **Status:** [ ] Not started
- **Impact:** The CRM processor exposes a `get_crm_unified_bundle()` method that is called by the pipeline, but this method is not declared in the `CRMProcessorProtocol`. This means the protocol is incomplete -- any alternative CRM processor implementation would not know to implement this method.
- **File:Line:** `contracts/protocols.py` (CRMProcessorProtocol); `engine/crm/processor.py` (method exists)
- **Fix:** Add `get_crm_unified_bundle()` to CRMProcessorProtocol with appropriate signature.
- **Tests needed:** Contract test verifying protocol compliance.

### P6.19 `apply_crm()` silently discards CRMErrors
- **Status:** [ ] Not started
- **Impact:** `engine/crm/processor.py:340-343` returns `LazyFrameResult(frame=..., errors=[])` with a comment about needing conversion from `CRMError` to `CalculationError`. Any CRM errors accumulated in the `errors: list[CRMError]` list are silently dropped. This means CRM data quality issues (ineligible collateral, missing fields, constraint violations) are invisible to callers using the `apply_crm()` interface. The `get_crm_unified_bundle` path may preserve errors differently.
- **File:Line:** `engine/crm/processor.py:340-343`
- **Fix:** Convert `CRMError` instances to `CalculationError` and include in the returned result's errors list. Alternatively, use `CalculationError` directly in the CRM module.
- **Tests needed:** Unit test verifying CRM errors propagate to callers.

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
- [x] **[!]** Equity (SA Art. 133, IRB Simple Art. 155, CIU fallback 250%; CIU look-through/mandate partial -- see P1.61; B31 equity SA weights implemented -- see P1.42 [fixed]; transitional floor applied in pipeline -- see P1.43 [fixed]; IRB equity table still exported under B31 -- see P1.59)
- [x] **[!]** CRM (collateral haircuts CRR 3-band + Basel 3.1 5-band, FX mismatch, maturity mismatch, multi-level allocation, guarantee substitution, netting, provisions; gold haircut wrong -- P1.73; LGD* formula doesn't blend -- P1.75; mixed pool pro-rata not sequential -- P1.77; see also P1.7, P1.11, P1.30, P1.39-P1.41, P1.56)
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
