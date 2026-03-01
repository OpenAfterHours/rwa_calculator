# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0) — COMPLETE

All Priority 1 items are done. **87/87 CRR acceptance tests pass (100%)**. CI/CD pipeline deployed. All 3 quality gates pass: ruff clean, mypy clean, all tests pass.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps — COMPLETE

Completed: PD floor per exposure class, LGD floor per collateral type, F-IRB supervisory LGD, A-IRB CCF floor, CCF for unconditionally cancellable commitments, Equity calculator Basel 3.1 routing, A-IRB LGD floor enforcement (gated on `is_airb`, subordinated unsecured 50%).

### 2b. SA risk weight revisions — COMPLETE

- [x] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71-88) — Done.
- [x] **Revised SA risk weight tables** (FR-1.2 / CRE20.7-26) — Done.

### 2c. CRM Basel 3.1 adjustments — PARTIAL

Done:

- [x] **Revised supervisory haircut tables** (CRE22.52-53) — Basel 3.1 table uses 5 maturity bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+) vs CRR's 3 bands. Higher equity haircuts: main index 25% (was 15%), other listed 35% (was 25%). Bond haircuts diverge significantly for maturities >5y. 33 unit tests in `tests/unit/crm/test_crm_basel31.py`.
- [x] **F-IRB supervisory LGD framework dispatch** (CRE32.9-12) — Senior unsecured 40% (was 45%), receivables 20%, real estate 20%, other physical 25%. Subordinated 75% and financial collateral unchanged. Lookup dispatches on `is_basel_3_1` flag.
- [x] **Framework-conditional HaircutCalculator and CRMProcessor** — `CRMProcessor(is_basel_3_1=True)` controls both haircut table selection and F-IRB supervisory LGD values. Pipeline auto-creates processor with `config.is_basel_3_1`.

Remaining (needs specification work before implementation):

- [ ] **SFT minimum haircut floors** (CRE56) — New Basel 3.1 requirement for securities financing transactions. Needs detailed specification from PRA PS9/24 CRE56 mapping.
- [ ] **Unfunded credit protection eligibility restrictions** (CRE22.70-85) — Revised eligibility criteria for guarantees and credit derivatives under Basel 3.1. Needs specification work.
- [x] **A-IRB LGD floor enforcement** (CRE30.41) — Done. LGD floors now gated on `is_airb` column: only A-IRB own-estimate LGDs are floored; F-IRB supervisory LGDs pass through unchanged. Subordinated unsecured detection (50% floor vs 25% senior) added via `has_seniority` parameter. 24 unit tests (was 16). Fixed in `formulas.py` (apply_irb_formulas), `namespace.py` (apply_lgd_floor, apply_all_formulas).

### 2d. Testing and validation

- [x] **Output floor phase-in validation tests** (M2.6) — Done. 11 tests covering all 6 transitional years plus edge cases.
- [~] **Basel 3.1 expected outputs** (M2.1) — Expected outputs JSON exists at `tests/expected_outputs/basel31/expected_rwa_b31.json` with 13 scenarios (10 SA, 3 output floor). Workbook structure at `workbooks/basel31_expected_outputs/` defines 39 scenarios across 8 groups (A-H). **Remaining:** Verify workbook calculations for groups B-H against regulatory formulas; extend JSON with verified values.
- [x] **Basel 3.1 acceptance tests** (M2.5) — Done. 20 tests across 2 test files: `test_scenario_b31_a_sa.py` (14 tests) and `test_scenario_b31_f_output_floor.py` (6 tests). All 20 pass. Remaining groups B-H need test files.

### 2e. Output floor engine — COMPLETE

- [x] **Output floor sa_rwa computation** — Fixed. `sa_rwa` column stored for all rows when output floor is enabled. Floor binding/non-binding detection works correctly.

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

## Test Counts

| Suite | Passed | Skipped |
|---|---|---|
| Unit | 1,302 | 1 |
| Contracts | 123 | 0 |
| Acceptance (CRR) | 87 | 0 |
| Acceptance (Basel 3.1) | 20 | 0 |
| Integration | 5 | 0 |
| Benchmarks | 4 | 21 |
| **Total** | **1,541** | **22** |

## Learnings

- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the engine uses vectorized `_pd_floor_expression()` / `_lgd_floor_expression()` helpers instead.
- Slotting calculator is the best-implemented Basel 3.1 area (3 differentiated risk weight tables, proper framework branching).
- CRM haircut table uses 3 maturity bands for CRR (0-1y, 1-5y, 5y+) and 5 bands for Basel 3.1 (0-1y, 1-3y, 3-5y, 5-10y, 10y+). Bond haircuts diverge significantly for maturities >5y. Equity haircuts increase from 15%/25% (CRR) to 25%/35% (Basel 3.1).
- `CRMProcessor(is_basel_3_1=True)` controls both haircut table selection AND F-IRB supervisory LGD values. Pipeline auto-creates processor with `config.is_basel_3_1`.
- **Output floor bug (fixed):** `calculate_unified()` computed SA risk weights for all rows but only calculated `rwa_pre_factor` for SA rows. Fix: store `sa_rwa = ead x risk_weight` for all rows before IRB calculator overwrites `risk_weight`; use inline `sa_rwa` in aggregator.
- **B31-F test exposure mismatch (fixed):** B31-F1/F3 tests used LOAN_CORP_UK_001 (CQS 1, 20% SA RW) expecting floor to bind. Changed to LOAN_CORP_UK_003 (CQS 2, 50% SA RW) where floor = 36.25% > IRB RW 24.8%.
- **Workbook schedule inconsistency:** `workbooks/basel31_expected_outputs/data/regulatory_params.py` uses BCBS schedule (starts 2025) while engine uses PRA PS9/24 UK schedule (starts 2027). Engine is correct for UK firms.
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral.
- For QRRE PD floors, `is_qrre_transactor` column does not exist yet. Defaults to revolver floor (0.10%) which is conservative.
- For LGD floors, `collateral_type` column may not be available at IRB stage. Default unsecured floor (25%) is applied when absent. Subordinated unsecured gets 50% floor when `seniority` column is present.
- **A-IRB LGD floor bug (fixed):** LGD floors were applied to ALL Basel 3.1 IRB rows (F-IRB and A-IRB). Fixed to only apply to A-IRB rows using `is_airb` column gating. F-IRB supervisory LGDs are regulatory values and don't need flooring (CRE30.41). Without `is_airb` column, defaults to no floor (conservative).
- Investment-grade corporate 65% only applies to unrated corporates. SCRA grading only applies to unrated institutions.
- Subordinated debt 150% is checked first in Basel 3.1 override chain because it overrides ALL other treatments.
