# Implementation Plan

Status legend: `[ ]` = not started, `[~]` = partial, `[x]` = done

## Priority 1 — CRR Completion (v1.0) — COMPLETE

All Priority 1 items are done. **91/91 CRR acceptance tests pass (100%)**. CI/CD pipeline deployed.

All items complete including CI/CD pipeline (M1.6). All 3 quality gates pass: ruff clean, mypy clean, all tests pass.

## Priority 2 — Basel 3.1 Core (v1.1)

### 2a. Engine gaps (must be fixed for Basel 3.1 correctness)

Completed: PD floor per exposure class, LGD floor per collateral type, F-IRB supervisory LGD, A-IRB CCF floor, CCF for unconditionally cancellable commitments, Equity calculator Basel 3.1 routing.

### 2b. SA risk weight revisions

- [x] **LTV-based residential RE risk weights** (FR-1.2 / CRE20.71–88) — Done. Implemented Basel 3.1 LTV-band risk weights (CRE20.73/82/85/86/87-88) in `data/tables/b31_risk_weights.py` and `engine/sa/calculator.py`. Covers general residential (7 bands: 20%-70%), income-producing residential (7 bands: 30%-105%), general commercial RE (min(60%, cp_rw) if LTV <= 60%), income-producing commercial RE (3 bands: 70%/90%/110%), and ADC (150%/100% pre-sold). 59 unit tests in `tests/unit/test_b31_sa_risk_weights.py`. All 1444 tests pass.
- [x] **Revised SA risk weight tables** (FR-1.2 / CRE20.7–26) — Done. Covers: revised CQS-based corporate weights (CQS3→75%, CQS5→100%) via `get_b31_combined_cqs_risk_weights()` in `b31_risk_weights.py`; SCRA-based institution weights for unrated institutions (Grade A 40%, Grade B 75%, Grade C 150%) with new `SCRAGrade` enum and `scra_grade` counterparty field; investment-grade corporate 65% for qualifying unrated corporates with `is_investment_grade` counterparty field; SME corporate 85% (was 100% under CRR); subordinated debt flat 150% for institution/corporate. All overrides framework-conditional in SA calculator. 95 B31 SA risk weight tests pass (36 new). All 1480 tests pass.

### 2c. CRM Basel 3.1 adjustments

- [ ] **CRM processor Basel 3.1 updates** — `engine/crm/` has zero Basel 3.1 conditional logic. Key changes: revised supervisory haircut tables, minimum haircut floors for SFTs, revised eligibility for unfunded credit protection, revised F-IRB overcollateralisation. **Action:** Research PRA PS9/24 CRM changes; add framework-conditional logic to haircuts and processor. See `specs/crr/credit-risk-mitigation.md`, `specs/basel31/framework-differences.md`.

### 2d. Testing and validation

- [x] **Output floor phase-in validation tests** (M2.6) — Done. 11 tests covering all 6 transitional years plus edge cases.
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
- [x] **Pre-existing lint/format/type errors across codebase** — Done. All CI gates pass.

## Learnings

- `PDFloors.get_floor()` and `LGDFloors.get_floor()` exist in config but are never called by the engine — the config layer is ahead of the engine layer for Basel 3.1. The engine now uses vectorized `_pd_floor_expression()` / `_lgd_floor_expression()` helpers instead, which are more efficient for bulk processing.
- Slotting calculator is the best-implemented Basel 3.1 area (3 differentiated risk weight tables, proper framework branching).
- Output floor engine code is correct. Phase-in tests now cover all 6 transitional years plus edge cases (11 tests).
- **Workbook schedule inconsistency:** `workbooks/basel31_expected_outputs/data/regulatory_params.py` uses the original BCBS schedule (starts 2025: 50%/55%/60%/65%/70%/72.5%) while the engine config (`OutputFloorConfig.basel_3_1()`) uses the PRA PS9/24 UK schedule (starts 2027). The engine is correct for UK firms. The workbook schedule needs aligning to PRA dates.
- CRR Art. 126 CRE treatment: Commercial RE is not a separate exposure class — it's a corporate exposure with commercial property collateral. The SA calculator detects CRE via `property_type == "commercial"` propagated from collateral through hierarchy enrichment.
- `IRBPermissions.full_irb()` should include AIRB for specialised lending under CRR (Art. 153(5) allows A-IRB when PD can be reliably estimated). The `airb_only()` method correctly excludes SL AIRB for Basel 3.1 per CRE33.5.
- Hierarchy `_add_collateral_ltv()` now propagates three columns from collateral: `ltv` (property_ltv), `property_type`, and `has_income_cover` (is_income_producing). This enrichment supports both residential mortgage and commercial RE risk weight calculations.
- For QRRE PD floors, the `is_qrre_transactor` column does not exist in the pipeline yet. The PD floor expression defaults to the revolver floor (0.10% under Basel 3.1), which is the conservative choice. When transactor/revolver classification is added to the data model, the expression can be extended with a `when(is_qrre_transactor)` branch.
- For LGD floors, the `collateral_type` column may not be available at the IRB calculation stage since the CRM processor consumes collateral data but doesn't propagate a single `collateral_type` to each exposure row. The default unsecured floor (25%) is applied when the column is absent, which is conservative. Future work: propagate `primary_collateral_type` from CRM processor to IRB stage.
- The large corporate correlation multiplier (CRE31.5) requires knowledge of the counterparty group's total consolidated assets (not revenue). The threshold is EUR 500m. This needs a schema extension (`consolidated_assets` field on counterparty data) before it can be implemented.
- F-IRB supervisory LGD revisions affect the overcollateralisation-based effective LGD calculation. The `calculate_effective_lgd_secured()` function in `crr_firb_lgd.py` still uses CRR values via `lookup_firb_lgd()`. It will automatically pick up Basel 3.1 values when called with `is_basel_3_1=True`.
- The SA calculator now branches on `config.is_basel_3_1` in `_apply_risk_weights()` — CRR uses Art. 125/126 split treatment while Basel 3.1 uses LTV-band lookups from `b31_risk_weights.py`. The CQS join is common to both.
- For Basel 3.1 general CRE (CRE20.85), the counterparty's CQS-based risk weight is saved before the override chain as `_cqs_risk_weight` and used in the `min(60%, counterparty_rw)` logic. This column is cleaned up after the override chain.
- The `calculate_single_exposure()` method now accepts `has_income_cover`, `property_type`, `is_adc`, and `is_presold` parameters for convenient single-exposure Basel 3.1 testing.
- Investment-grade corporate 65% treatment only applies to unrated corporates — rated corporates use the revised CQS table (where CQS 1 = 20% already beats 65%). The SA calculator checks `cqs IS NULL` before applying the investment-grade override.
- SCRA grading only applies to unrated institutions under Basel 3.1. Rated institutions continue to use ECRA (same as CRR). The SA calculator checks `cqs IS NULL` AND `scra_grade IS NOT NULL` before applying SCRA weights.
- Subordinated debt 150% is checked first in the Basel 3.1 override chain because it overrides ALL other treatments (CQS, investment-grade, SME). It only applies to INSTITUTION and CORPORATE exposure classes (not sovereign).
- The `scra_grade` and `is_investment_grade` fields are optional in the counterparty schema. When absent, the classifier and SA calculator add defaults (null/False), ensuring backward compatibility with existing test data.
