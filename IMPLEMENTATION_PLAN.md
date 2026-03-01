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

### 2d. Testing and validation — COMPLETE

- [x] **Output floor phase-in validation tests** (M2.6) — Done. 11 tests covering all 6 transitional years plus edge cases.
- [x] **Basel 3.1 expected outputs** (M2.1) — Expected outputs JSON at `tests/expected_outputs/basel31/expected_rwa_b31.json` with 38 scenarios across 8 groups (10 SA, 7 F-IRB, 3 A-IRB, 6 CRM, 4 slotting, 3 output floor, 3 provisions, 2 complex/combined).
- [x] **Basel 3.1 acceptance tests** (M2.5) — **111 tests across 8 test files**, all passing:
  - `test_scenario_b31_a_sa.py` (14): SA risk weight revisions
  - `test_scenario_b31_b_firb.py` (16): F-IRB revised LGD/PD floors
  - `test_scenario_b31_c_airb.py` (13): A-IRB LGD floor enforcement
  - `test_scenario_b31_d_crm.py` (15): CRM revised haircuts
  - `test_scenario_b31_e_slotting.py` (13): Slotting operational/HVCRE tables
  - `test_scenario_b31_f_output_floor.py` (6): Output floor phase-in
  - `test_scenario_b31_g_provisions.py` (20): Provision EAD deduction, EL shortfall/excess with B31 LGD, el_shortfall/el_excess column validation
  - `test_scenario_b31_h_complex.py` (10): Facility aggregation, SME SF removal impact

### 2e. Output floor engine — COMPLETE

- [x] **Output floor sa_rwa computation** — Fixed. `sa_rwa` column stored for all rows when output floor is enabled. Floor binding/non-binding detection works correctly.

## Priority 3 — Dual-Framework Comparison (v1.2)

### 3a. Side-by-side comparison — COMPLETE

- [x] **Side-by-side CRR vs Basel 3.1 comparison output** (M3.1) — Done. `DualFrameworkRunner` in `engine/comparison.py` orchestrates two separate `PipelineOrchestrator` instances (one per framework) on the same `RawDataBundle`. Produces `ComparisonBundle` with per-exposure deltas (delta_rwa, delta_risk_weight, delta_ead, delta_rwa_pct) and summary views by exposure class and approach. 22 unit tests + 19 acceptance tests (SA and F-IRB comparison scenarios).

### 3b. Remaining (not started)

- [ ] **Capital impact analysis** (M3.2) — Not Started. Depends on M3.1 (done). Would add delta attribution by driver (PD floor changes, LGD floor changes, scaling factor removal, supporting factor removal, output floor binding).
- [ ] **Transitional floor schedule modelling** (M3.3) — Not Started. Would run the same B31 portfolio across 2027-2032 reporting dates to show how the output floor progressively tightens.
- [ ] **Enhanced Marimo workbooks for impact analysis** (M3.4) — Not Started. Would add comparison visualization, floor schedule slider, drill-down from portfolio delta to exposure-level drivers.

## Priority 4 — Output & Export

- [~] **Excel / Parquet export** (FR-4.7) — Partial. No programmatic export API yet.
- [ ] **COREP template generation** (FR-4.6) — Not Started. Deferred to v2.0.

## Infrastructure & Cleanup

- [ ] **BDD test scaffold** — Empty scaffold, no actual BDD tests. Low priority.
- [ ] **Runtime skip pattern inconsistency** — Audit remaining runtime skips.

### 2f. EL shortfall/excess computation — COMPLETE

- [x] **EL shortfall/excess per exposure** (CRR Art. 158-159, Art. 62(d)) — Done. `compute_el_shortfall_excess()` added to IRB namespace. Computes `el_shortfall = max(0, EL - provision_allocated)` and `el_excess = max(0, provision_allocated - EL)` for every IRB exposure. Called in all 3 IRB calculator paths (`get_irb_result_bundle`, `calculate_unified`, `calculate_branch`). 14 unit tests, 9 acceptance tests (4 CRR-G, 5 B31-G). Aggregator `_generate_summary_by_approach()` extended to sum `total_el_shortfall` / `total_el_excess`.

## Test Counts

| Suite | Passed | Skipped |
|---|---|---|
| Unit | 1,338 | 1 |
| Contracts | 123 | 0 |
| Acceptance (CRR) | 91 | 0 |
| Acceptance (Basel 3.1) | 111 | 0 |
| Acceptance (Comparison) | 19 | 0 |
| Integration | 5 | 0 |
| Benchmarks | 4 | 21 |
| **Total** | **1,687** | **22** |

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
- **CRM processor F-IRB LGD bug (fixed):** `_apply_collateral_unified` and `_calculate_irb_lgd_with_collateral` hardcoded `pl.lit(0.45)` for senior unsecured LGD fallback, ignoring Basel 3.1's 40% value. The framework-conditional variable `lgd_unsecured` was correctly computed earlier in each method but not used in the `.otherwise()` fallback. Fixed 3 locations in `processor.py`. The `_apply_firb_supervisory_lgd_no_collateral` path was already correct but only triggered when zero collateral rows existed portfolio-wide.
- F-IRB acceptance tests require `IRBPermissions.firb_only()` (not `full_irb()`) and reporting date 2027-06-30 to get meaningful maturities from fixture loans (maturity dates 2028-2033). Using `full_irb()` routes to A-IRB; using dates after 2032 causes all maturities to floor at 1.0.
- Workbook `regulatory_params.py` PD floor discrepancy: uses `PD_FLOORS["CORPORATE"] = 0.0003` (CRR 0.03%) while production config correctly uses `0.0005` (Basel 3.1 0.05% per CRE30.20). Workbook needs updating.
- **B31-D CRM test pattern:** D-scenario loans use `sa_results_df` with `rwa_post_factor` column (matching B31-A pattern). CRM adjustments are reflected in EAD before SA calculator runs. The `pipeline_results_df` has `rwa_final` (aggregated). Only D3 (equity haircut 25% vs CRR 15%) produces different RWA; D1/D2/D4/D5/D6 are unchanged because their specific haircut values happen to be the same across frameworks.
- **Orphaned collateral/guarantee fixtures:** `LOAN_COLL_TEST_CORP_*`, `LOAN_GUAR_TEST_*`, `LOAN_PROV_TEST_*` beneficiary references in fixtures point to non-existent loans. These are "dedicated test loans" that were never created. Safe to ignore; does not affect test outcomes.
- **B31-G provision tests use same fixtures as CRR-G:** The provision fixture data (`LOAN_PROV_G1/G2/G3`) is shared across frameworks. The pipeline config (`CalculationConfig.basel_3_1()`) drives different IRB results (LGD 40% vs 45%, no 1.06 scaling). SA provision deduction (G1) is identical across frameworks.
- **B31-G2/G3 maturity differs from CRR:** With F-IRB reporting_date=2027-06-30 and loan maturity_date=2028-06-30, effective maturity = 1.0027y (vs CRR 2.5y). At M≈1.0, the maturity adjustment MA = 1.0 (numerator equals denominator). This dramatically reduces IRB RWA: G2 RWA drops from £6.1M (CRR) to £4.3M (B31) — 30% reduction.
- **B31-H3 SME impact quantified:** Basel 3.1 SME corporates get 85% RW (vs CRR 100%) but lose the 0.7619 supporting factor. Net effect: effective RW rises from 76.19% to 85%, a 12% RWA increase. This is material for banks with large SME portfolios.
- **EL shortfall/excess columns (implemented):** `el_shortfall` and `el_excess` are computed by `IRBLazyFrame.compute_el_shortfall_excess()` in the IRB namespace. Called after `apply_all_formulas()` in all IRB calculator paths. Guards against missing `provision_allocated` (defaults to 0) and missing `expected_loss` (both columns default to 0). T2 credit cap (0.6% of IRB RWA per CRR Art. 62(d)) is not yet computed at portfolio level — only per-exposure shortfall/excess is tracked.
- **Pre-existing formatting issues:** `formulas.py` and `namespace.py` in `engine/irb/` had ruff format violations. Fixed as part of this increment.
- **DualFrameworkRunner design:** Uses two separate `PipelineOrchestrator` instances (one per framework) because `_ensure_components_initialized()` caches the `CRMProcessor` with the first config's `is_basel_3_1` flag and never recreates it. The `run_with_data()` method shares the same `RawDataBundle` between both runs, halving I/O cost. Comparison join is on `exposure_reference` using a full outer join to handle mismatched exposure sets.
- **Approach column values:** `approach_applied` column uses enum string values: `"standardised"`, `"foundation_irb"`, `"advanced_irb"`, `"slotting"` — not the enum names `"SA"`, `"FIRB"`, etc. Tests must filter on the `.value` form.
- **Spec inconsistencies found:** `specs/regulatory-compliance.md` is stale (says B31 tests not started, but 111 pass). `specs/nfr.md` test count outdated (says 1,050 but 1,687 pass). `specs/milestones.md` CRR count stale (says 71/74 but 91 pass). Slotting risk weight tables differ between `specs/crr/slotting-approach.md` and `specs/basel31/framework-differences.md`.
