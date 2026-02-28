# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0, target 100% acceptance pass rate)

Current state: **91/91 CRR acceptance tests pass (100%)**, 0 skipped, 0 failures. All Priority 1 acceptance test gaps resolved.

- [x] **CRR-B: F-IRB acceptance tests** — 13 tests (7 formula + 6 validation) all passing.
- [x] **CRR-A7: Commercial RE acceptance test** — Implemented. Created `LOAN_CRE_001` loan fixture, `CORP_CRE_001` counterparty, and `COLL_CRE_A7` collateral (commercial property, 40% LTV, income-producing). Extended hierarchy `_add_collateral_ltv()` to propagate `property_type` and `has_income_cover` from collateral to exposures. Updated SA calculator CRE detection to match on `property_type == "commercial"` in addition to exposure_class string matching — because CRE is not a separate exposure class under CRR, it's a corporate with preferential treatment per Art. 126.
- [x] **CRR-A8: OBS CCF acceptance test** — Implemented. Created `CONT_CCF_001` contingent fixture (undrawn commitment, MR risk type, £1m nominal) and `CORP_OBS_001` counterparty (unrated large corporate). Pipeline correctly applies 50% CCF → EAD £500k, 100% RW → RWA £500k.
- [x] **CRR-C3: SL A-IRB acceptance test** — Fixed. Root cause: `IRBPermissions.full_irb()` excluded `ApproachType.AIRB` for `ExposureClass.SPECIALISED_LENDING`, causing the classifier to route SL exposures to slotting instead of A-IRB. Under CRR Art. 153(5), firms can use A-IRB for SL if they can reliably estimate PD. Added AIRB to full_irb() permissions for SL. Updated unit test accordingly.
- [x] **CRR-E slotting expected outputs** — Fixed 4 pre-existing failures. Root cause: expected outputs for CRR-E2 (Good) and CRR-E4 (HVCRE Strong) used wrong risk weights. Fixtures have 5yr maturity (>=2.5yr), so correct weights are: Good=90% (not 70%), HVCRE Strong=95% (not 70%). Updated expected outputs JSON/CSV/Parquet and workbook params. Production calculator was already correct.
- [ ] **CI/CD pipeline** (M1.6) — Only 2 workflows exist: `docs.yml` (MkDocs deploy) and `publish.yml` (PyPI publish). **No workflow runs pytest, ruff, or mypy.** No PR checks. **Action:** Create `.github/workflows/ci.yml` with: (1) ruff check + ruff format --check, (2) mypy --strict, (3) pytest tests/ --benchmark-skip, triggered on push and PR. See `specs/milestones.md`.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps (must be fixed for Basel 3.1 correctness)

- [ ] **PD floor per exposure class in engine** (FR-1.9 / FR-5.4) — `PDFloors` config correctly defines differentiated floors (corporate 0.05%, QRRE transactor 0.03%, QRRE revolver 0.10%) with `get_floor(exposure_class)` method. But the engine (`engine/irb/formulas.py:74`, `engine/irb/namespace.py:299`, `engine/irb/calculator.py:380`) always uses `config.pd_floors.corporate` uniformly. Under Basel 3.1, QRRE revolvers get 0.05% instead of the correct 0.10%. **Action:** Refactor IRB formula code to apply per-row PD floor based on `exposure_class` column, calling `PDFloors.get_floor()` logic via a Polars `when/then` chain.
- [ ] **LGD floor per collateral type in engine** (FR-1.5 / FR-5.4) — `LGDFloors` config defines per-collateral floors (unsecured 25%, financial 0%, receivables 10%, CRE 10%, RRE 5%, other physical 15%). But `engine/irb/formulas.py:97` always uses `config.lgd_floors.unsecured` (25%). Financial collateral (should be 0%) and RRE (should be 5%) get floored at 25%. **Action:** Refactor to apply per-row LGD floor based on collateral type column using Polars expressions.
- [ ] **F-IRB supervisory LGD for Basel 3.1** — `data/tables/crr_firb_lgd.py` has no framework branching. CRR values (senior 45%, subordinated 75%) are hardcoded. Basel 3.1 revises: senior 45%→40%, receivables 35%→20%, CRE/RRE 35%→20%, other physical 40%→25%. **Action:** Add framework parameter to LGD lookup; return Basel 3.1 values when `config.is_basel_3_1`. See `specs/basel31/framework-differences.md`.
- [ ] **Large corporate correlation multiplier** (CRE31.5) — Basel 3.1 requires 1.25x correlation multiplier for corporates with consolidated revenue > EUR 500m (separate from existing FI scalar). Not implemented anywhere. **Action:** Add `is_large_corporate` flag detection and correlation multiplier in IRB formulas. See `specs/basel31/framework-differences.md`.
- [ ] **A-IRB CCF floor** (CRE32.27) — Basel 3.1 requires A-IRB modelled CCFs to be at least 50% of the SA CCF for the same item type. `engine/ccf.py` has no framework logic. **Action:** Add floor enforcement after modelled CCF application when `config.is_basel_3_1`. See `specs/basel31/framework-differences.md`.
- [ ] **CCF for unconditionally cancellable commitments** — CRR: 0% (LR). Basel 3.1: 10%. `engine/ccf.py` hardcodes 0% for LR with no framework check. **Action:** Add framework-conditional LR CCF (0% CRR, 10% Basel 3.1). See `specs/basel31/framework-differences.md`.
- [ ] **Equity calculator Basel 3.1 routing** — Under Basel 3.1, equity IRB is removed; all equity exposures must use SA. `engine/equity/calculator.py` has no framework logic — approach is determined solely by `config.irb_permissions`. **Action:** Add `config.is_basel_3_1` check to force SA for all equity. See `specs/crr/slotting-approach.md`.

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

- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the config layer is ahead of the engine layer for Basel 3.1.
- Slotting calculator is the best-implemented Basel 3.1 area (3 differentiated risk weight tables, proper framework branching).
- Output floor engine code is correct; the gap is purely in test coverage (only 1 of 6 transitional years tested).
- CRR-B (F-IRB) was a previously uncounted gap — now resolved with 13 passing tests.
- CRR-B tests compare pre-factor RWA because the pipeline computes the tiered SME supporting factor using counterparty-level aggregated drawn exposure (window function over `counterparty_reference`), which differs from per-exposure workbook calculations. SF is tested separately in CRR-F.
- With `IRBPermissions.full_irb()`, the classifier routes all exposures as `advanced_irb` not `foundation_irb`. This doesn't affect formula results when fixture LGD values already match supervisory levels — the IRB K formula is approach-agnostic given the same inputs.
- CRR-E slotting had 4 failures caused by wrong expected outputs (Good=70% should be 90%, HVCRE Strong=70% should be 95% for >=2.5yr maturity). The production calculator was correct — only the expected outputs and workbook params needed fixing.
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral. The SA calculator detects CRE via `property_type == "commercial"` propagated from collateral through hierarchy enrichment, or via exposure_class string matching for future-proofing.
- `IRBPermissions.full_irb()` should include AIRB for specialised lending under CRR (Art. 153(5) allows A-IRB when PD can be reliably estimated). The `airb_only()` method correctly excludes SL AIRB for Basel 3.1 per CRE33.5.
- Hierarchy `_add_collateral_ltv()` now propagates three columns from collateral: `ltv` (property_ltv), `property_type`, and `has_income_cover` (is_income_producing). This enrichment supports both residential mortgage and commercial RE risk weight calculations.
- The codebase is very clean: only one `TODO` found across all source files (`config.py:149`, verifying against PRA PS1/26 final rules).
