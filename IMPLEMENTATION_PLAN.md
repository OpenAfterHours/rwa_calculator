# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0) — COMPLETE

All Priority 1 items are done. **91/91 CRR acceptance tests pass (100%)**. CI/CD pipeline deployed.

All items complete including CI/CD pipeline (M1.6). All 3 quality gates pass: ruff clean, mypy clean, all tests pass.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps — COMPLETE

Completed: PD floor per exposure class, LGD floor per collateral type, F-IRB supervisory LGD, A-IRB CCF floor, CCF for unconditionally cancellable commitments, Equity calculator Basel 3.1 routing.

### 2b. SA risk weight revisions — COMPLETE

- [x] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71–88) — Done.
- [x] **Revised SA risk weight tables** (FR-1.2 / CRE20.7–26) — Done.

### 2c. CRM Basel 3.1 adjustments

- [ ] **CRM processor Basel 3.1 updates** — `engine/crm/` has zero Basel 3.1 conditional logic. Key changes: revised supervisory haircut tables, minimum haircut floors for SFTs, revised eligibility for unfunded credit protection, revised F-IRB overcollateralisation. **Action:** Research PRA PS9/24 CRM changes; add framework-conditional logic to haircuts and processor. See `specs/crr/credit-risk-mitigation.md`, `specs/basel31/framework-differences.md`.

### 2d. Testing and validation

- [x] **Output floor phase-in validation tests** (M2.6) — Done. 11 tests covering all 6 transitional years plus edge cases.
- [~] **Basel 3.1 expected outputs** (M2.1) — Expected outputs JSON exists at `tests/expected_outputs/basel31/expected_rwa_b31.json` with 13 scenarios (10 SA, 3 output floor). Workbook structure at `workbooks/basel31_expected_outputs/` defines 39 scenarios across 8 groups (A-H). **Remaining:** Verify workbook calculations for groups B-H against regulatory formulas; extend JSON with verified values.
- [x] **Basel 3.1 acceptance tests** (M2.5) — Done. 20 tests across 2 test files: `test_scenario_b31_a_sa.py` (14 tests: 10 SA scenarios + 4 structural) and `test_scenario_b31_f_output_floor.py` (6 tests: 3 floor scenarios + 3 structural invariants). All 20 pass. Remaining groups B-H need test files (workbook defines scenarios but no test implementations yet).

### 2e. Output floor engine — FIXED

- [x] **Output floor sa_rwa computation** — Fixed critical bug where `sa_rwa` was not stored for IRB rows in `calculate_unified()`. Added `sa_rwa` column (EAD × SA risk weight) for all rows when output floor is enabled. Fixed `_apply_floor_with_impact()` in aggregator to use inline `sa_rwa` column instead of broken self-join. Floor binding/non-binding detection now works correctly. All 20 B31 acceptance tests pass.

## Priority 3 — Dual-Framework Comparison (v1.2)

No code exists for any M3.x milestone. The infrastructure supports dual execution (separate factory methods `CalculationConfig.crr()` / `.basel_3_1()`), but no comparison logic exists.

- [ ] **Side-by-side CRR vs Basel 3.1 comparison output** (M3.1) — Not Started.
- [ ] **Capital impact analysis** (M3.2) — Not Started.
- [ ] **Transitional floor schedule modelling** (M3.3) — Not Started.
- [ ] **Enhanced Marimo workbooks for impact analysis** (M3.4) — Not Started.

## Priority 4 — Output & Export

- [~] **Excel / Parquet export** (FR-4.7) — Partial. No programmatic export API yet.
- [ ] **COREP template generation** (FR-4.6) — Not Started. Deferred to v2.0.

## Infrastructure & Cleanup

- [ ] **BDD test scaffold** — Empty scaffold, no actual BDD tests. Low priority.
- [ ] **Runtime skip pattern inconsistency** — Audit remaining runtime skips.
- [x] **Pre-existing lint/format/type errors across codebase** — Done. All CI gates pass.
- [x] **Fixture parquet generation** — Parquet files must be generated via `uv run python tests/fixtures/generate_all.py` before acceptance tests can run. Not auto-generated; 3 integrity warnings exist for test-only collateral/guarantee/provision references.

## Learnings

- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the engine uses vectorized `_pd_floor_expression()` / `_lgd_floor_expression()` helpers instead.
- Slotting calculator is the best-implemented Basel 3.1 area (3 differentiated risk weight tables, proper framework branching).
- **Output floor bug (fixed):** `calculate_unified()` computed SA risk weights for all rows via `_apply_risk_weights()` but only calculated `rwa_pre_factor` for SA rows (guarded by `is_sa`). IRB rows had `rwa_pre_factor = None`. The `_aggregate_single_pass()` method passed `combined` as both `combined` and `sa_results` args to `_apply_floor_with_impact()`, creating a self-join that found the IRB row's own null `rwa_post_factor`. Fix: store `sa_rwa = ead × risk_weight` for all rows in `calculate_unified()` before IRB calculator overwrites `risk_weight`; use inline `sa_rwa` in aggregator when available.
- **B31-F test exposure mismatch (fixed):** B31-F1/F3 tests used LOAN_CORP_UK_001 (CORP_UK_001, CQS 1, 20% SA RW) expecting floor to bind. But with 20% SA RW, floor = 14.5% < IRB RW 18.67%. Changed to LOAN_CORP_UK_003 (CQS 2, 50% SA RW) where floor = 36.25% > IRB RW 24.8% — floor correctly binds.
- **Workbook schedule inconsistency:** `workbooks/basel31_expected_outputs/data/regulatory_params.py` uses BCBS schedule (starts 2025) while engine uses PRA PS9/24 UK schedule (starts 2027). Engine is correct for UK firms.
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral.
- For QRRE PD floors, the `is_qrre_transactor` column does not exist yet. Defaults to revolver floor (0.10%) which is conservative.
- For LGD floors, `collateral_type` column may not be available at IRB stage. Default unsecured floor (25%) is applied when absent.
- Investment-grade corporate 65% only applies to unrated corporates. SCRA grading only applies to unrated institutions.
- Subordinated debt 150% is checked first in Basel 3.1 override chain because it overrides ALL other treatments.
