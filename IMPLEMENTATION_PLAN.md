# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0, target 100% acceptance pass rate)

Current state: **91/91 CRR acceptance tests pass (100%)**, 0 skipped, 0 failures. All Priority 1 acceptance test gaps resolved.

- [ ] **CI/CD pipeline** (M1.6) — Only 2 workflows exist: `docs.yml` (MkDocs deploy) and `publish.yml` (PyPI publish). **No workflow runs pytest, ruff, or mypy.** No PR checks. **Action:** Create `.github/workflows/ci.yml` with: (1) ruff check + ruff format --check, (2) mypy --strict, (3) pytest tests/ --benchmark-skip, triggered on push and PR. See `specs/milestones.md`.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps (must be fixed for Basel 3.1 correctness)

- [x] **PD floor per exposure class in engine** (FR-1.9 / FR-5.4, CRE30.55) — Implemented. Added `_pd_floor_expression(config)` helper in `formulas.py` that builds a Polars `when/then` chain mapping `exposure_class` to the correct PD floor. CRR uses uniform 0.03%; Basel 3.1 differentiates (corporate 0.05%, QRRE revolver 0.10%, retail mortgage 0.05%). Updated `apply_irb_formulas()`, `namespace.apply_pd_floor()`, and `namespace.apply_all_formulas()`. 17 unit tests cover all exposure classes and both frameworks.
- [x] **LGD floor per collateral type in engine** (FR-1.5 / FR-5.4, CRE30.41) — Implemented. Added `_lgd_floor_expression(config)` (default unsecured 25%) and `_lgd_floor_expression_with_collateral(config)` (maps `collateral_type` column to per-type floors: financial 0%, RRE 5%, CRE 10%, receivables 10%, other physical 15%). CRR returns 0% (no floors). Used in `apply_irb_formulas()`, `namespace.apply_lgd_floor()`, and `namespace.apply_all_formulas()`. 18 unit tests.
- [x] **F-IRB supervisory LGD for Basel 3.1** (CRE32.9-12) — Implemented. Added `BASEL31_FIRB_SUPERVISORY_LGD` dictionary with revised values (senior 40%, receivables 20%, RE 20%, other physical 25%). Added `get_firb_lgd_table_for_framework()`. Updated `lookup_firb_lgd()` with `is_basel_3_1` parameter. IRB namespace `apply_firb_lgd()` uses framework-appropriate values. 25 unit tests.
- [x] **A-IRB CCF floor** (CRE32.27) — Implemented. Under Basel 3.1, A-IRB modelled CCFs are floored at 50% of the SA CCF for the same item type: `ccf = max(ccf_modelled, 0.5 * sa_ccf)`. Added in `CCFCalculator.apply_ccf()` with `is_b31` conditional. 5 unit tests cover floor scenarios.
- [x] **CCF for unconditionally cancellable commitments** (CRE20.88) — Implemented. `sa_ccf_expression()` now accepts `is_basel_3_1` parameter. LR/low_risk CCF: 0% under CRR, 10% under Basel 3.1. F-IRB LR CCF also updated. 4 unit tests.
- [x] **Equity calculator Basel 3.1 routing** (CRE20.58-62) — Implemented. Added early return `if config.is_basel_3_1: return "sa"` in `_determine_approach()`. Under Basel 3.1, IRB Simple (Art. 155) is removed; all equity uses SA (Art. 133). 11 unit tests.
- [ ] **Large corporate correlation multiplier** (CRE31.5) — Basel 3.1 requires 1.25x correlation multiplier for corporates belonging to groups with total consolidated assets > EUR 500m (separate from existing FI scalar). Not implemented. **Action:** Need `consolidated_assets` or equivalent field on counterparty data; add threshold check and 1.25x multiplier in `_polars_correlation_expr()`. Requires schema extension for the assets column.

### 2b. SA risk weight revisions

- [ ] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71–81) — Current SA calculator implements only CRR Art. 125 (35%/75% split at 80% LTV). Basel 3.1 requires granular LTV-band risk weights (20%/25%/30%/40%/50%/70%) with separate tables for whole-loan vs loan-splitting, and income-producing vs general residential. The schema (`data/schemas.py:980`) references LTV bands but the calculator doesn't use them. **Action:** Implement Basel 3.1 LTV-band SA risk weight tables and calculator logic. See `specs/crr/sa-risk-weights.md`.
- [~] **Revised SA risk weight tables** (FR-1.2 / CRE20.7–26) — `data/tables/crr_risk_weights.py` is CRR-only. Basel 3.1 introduces SCRA-based institution weights, investment-grade corporate at 65%, subordinated debt at 150%, granular CRE LTV bands. **Action:** Create Basel 3.1 SA risk weight data tables and add framework-conditional lookup in SA calculator. See `specs/crr/sa-risk-weights.md`.

### 2c. CRM Basel 3.1 adjustments

- [ ] **CRM processor Basel 3.1 updates** — `engine/crm/` has zero Basel 3.1 conditional logic. Key changes: revised supervisory haircut tables, minimum haircut floors for SFTs, revised eligibility for unfunded credit protection, revised F-IRB overcollateralisation. **Action:** Research PRA PS9/24 CRM changes; add framework-conditional logic to haircuts and processor. See `specs/crr/credit-risk-mitigation.md`, `specs/basel31/framework-differences.md`.

### 2d. Testing and validation

- [ ] **Output floor phase-in validation tests** (M2.6) — Engine implements output floor correctly. Unit tests cover only 1 of 6 transitional years (2029 at 60%). **Action:** Add parametrized test sweeping 2027–2032 schedule (50%/55%/60%/65%/70%/72.5%) plus pre-2027 edge case. See `specs/output-reporting.md`.
- [ ] **Basel 3.1 expected outputs** (M2.1) — Workbook structure exists at `workbooks/basel31_expected_outputs/` but values are hardcoded stubs, not verified hand calculations. `tests/expected_outputs/basel31/` directory doesn't exist. **Action:** Verify workbook calculations against regulatory formulas; generate expected output CSV/JSON files. See `specs/milestones.md`.
- [ ] **Basel 3.1 acceptance tests** (M2.5) — `tests/acceptance/basel31/` directory doesn't exist. No B31 tests anywhere. **Action:** Create acceptance test suite for B31-A (SA revised, 10 scenarios) and B31-F (output floor, 3 scenarios). See `specs/regulatory-compliance.md`.

## Priority 3 — Dual-Framework Comparison (v1.2)

No code exists for any M3.x milestone. The infrastructure supports dual execution (separate factory methods `CalculationConfig.crr()` / `.basel_3_1()`), but no comparison logic exists.

- [ ] **Side-by-side CRR vs Basel 3.1 comparison output** (M3.1) — Not Started. Run same portfolio through both frameworks, produce comparison DataFrame. See `specs/milestones.md`.
- [ ] **Capital impact analysis** (M3.2) — Not Started. Delta RWA by approach, exposure class, portfolio segment. See `specs/milestones.md`.
- [ ] **Transitional floor schedule modelling** (M3.3) — Not Started. Year-by-year output floor impact 2027–2032. See `specs/milestones.md`.
- [ ] **Enhanced Marimo workbooks for impact analysis** (M3.4) — Not Started. See `specs/milestones.md`.

## Priority 4 — Output & Export

- [~] **Excel / Parquet export** (FR-4.7) — Parquet used for fixture I/O; Marimo UI offers CSV/Parquet download. `fastexcel>=0.19.0` is a dependency but `write_excel`/`to_excel` is never called — no XLSX export. No programmatic export API. **Action:** Implement `export_results(bundle, format, path)` in API layer supporting CSV, Parquet, and XLSX. See `specs/output-reporting.md`.
- [ ] **COREP template generation** (FR-4.6) — Not Started. Deferred to v2.0. See `specs/output-reporting.md`.

## Infrastructure & Cleanup

- [ ] **BDD test scaffold** — `tests/bdd/conftest.py` references `docs/specifications/` which is being deleted (git status shows `D docs/specifications/*.md`). No actual BDD step definitions or feature files exist. **Action:** Either implement BDD tests or remove the empty scaffold. Low priority.
- [ ] **Runtime skip pattern inconsistency** — CRR-A tests used `@pytest.mark.skip` for known gaps; CRR-C/D/E/F/G/H use `if result is None: pytest.skip()` inside test body, silently skipping if pipeline doesn't produce results. CRR-A7/A8 skips now resolved. **Action:** Audit remaining runtime skips to ensure they are visible and justified.
- [ ] **Pre-existing lint errors in SA calculator** — `src/rwa_calc/engine/sa/calculator.py` has 4 ruff violations: unused `ExposureClass` import, unsorted import blocks, extraneous parentheses. All pre-existing, not from recent changes.

## Learnings

- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the config layer is ahead of the engine layer for Basel 3.1. The engine now uses vectorized `_pd_floor_expression()` / `_lgd_floor_expression()` helpers instead, which are more efficient for bulk processing.
- Slotting calculator is the best-implemented Basel 3.1 area (3 differentiated risk weight tables, proper framework branching).
- Output floor engine code is correct; the gap is purely in test coverage (only 1 of 6 transitional years tested).
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral. The SA calculator detects CRE via `property_type == "commercial"` propagated from collateral through hierarchy enrichment.
- `IRBPermissions.full_irb()` should include AIRB for specialised lending under CRR (Art. 153(5) allows A-IRB when PD can be reliably estimated). The `airb_only()` method correctly excludes SL AIRB for Basel 3.1 per CRE33.5.
- Hierarchy `_add_collateral_ltv()` now propagates three columns from collateral: `ltv` (property_ltv), `property_type`, and `has_income_cover` (is_income_producing). This enrichment supports both residential mortgage and commercial RE risk weight calculations.
- For QRRE PD floors, the `is_qrre_transactor` column does not exist in the pipeline yet. The PD floor expression defaults to the revolver floor (0.10% under Basel 3.1), which is the conservative choice. When transactor/revolver classification is added to the data model, the expression can be extended with a `when(is_qrre_transactor)` branch.
- For LGD floors, the `collateral_type` column may not be available at the IRB calculation stage since the CRM processor consumes collateral data but doesn't propagate a single `collateral_type` to each exposure row. The default unsecured floor (25%) is applied when the column is absent, which is conservative. Future work: propagate `primary_collateral_type` from CRM processor to IRB stage.
- The large corporate correlation multiplier (CRE31.5) requires knowledge of the counterparty group's total consolidated assets (not revenue). The threshold is EUR 500m. This needs a schema extension (`consolidated_assets` field on counterparty data) before it can be implemented.
- F-IRB supervisory LGD revisions affect the overcollateralisation-based effective LGD calculation. The `calculate_effective_lgd_secured()` function in `crr_firb_lgd.py` still uses CRR values via `lookup_firb_lgd()`. It will automatically pick up Basel 3.1 values when called with `is_basel_3_1=True`.
