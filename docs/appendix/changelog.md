# Changelog

All notable changes to the RWA Calculator are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.183] — 2026-04-10

### Changed
- **Classifier**: Moved `B31_LARGE_CORPORATE_REVENUE_THRESHOLD_GBP` (PRA PS1/26 Art. 147A(1)(d)) and `B31_SME_TURNOVER_THRESHOLD_GBP` (PRA PS1/26 Art. 153(4)) from `engine/classifier.py` to `data/tables/b31_risk_weights.py` for consistency with other B31 regulatory thresholds. Converted from `float` to `Decimal`.

## [0.1.182] — 2026-04-10

### Changed
- **Pipeline**: Renamed private methods in `PipelineOrchestrator` to remove stale fan-out/single-pass terminology: `_run_crm_processor_unified` -> `_run_crm_processor`, `_run_single_pass` -> `_run_calculators`, `_aggregate_single_pass` -> `_aggregate_results`. Section header renamed from "Single-Pass Pipeline" to "Calculation".
- **Pipeline**: Removed dead code `_run_sa_calculator` and `_run_irb_calculator` (never called from production; superseded by `calculate_branch()` in the single-pass path). Associated tests removed.

## [0.1.181] — 2026-04-09

### Fixed
- **Classifier**: Exposures with internal ratings no longer silently route to Standardised Approach when `permission_mode="irb"` is set on `CreditRiskCalc`. Two independent bugs are addressed:
  - **Pipeline downgrade (Bug #1)**: `PipelineOrchestrator.run_with_data` used `dataclasses.replace(config, permission_mode=STANDARDISED)` when `model_permissions` was absent, which re-ran `CalculationConfig.__post_init__` and wiped `irb_permissions` to `sa_only()`. The pipeline now preserves the user's org-wide IRB permissions and emits a `missing_model_permissions` pipeline error explaining that per-model gating is disabled.
  - **Silent classifier join failure (Bug #2)**: `ExposureClassifier._resolve_model_permissions` joined `exposure.model_id` LEFT against `model_permissions.model_id`. Null or unmatched `model_id` values produced no match and silently routed to SA with no diagnostic. The classifier now tags each IRB-eligible miss with one of three causes (`null_model_id`, `unmatched_model_id`, `filter_rejected`) and emits a rolled-up `CLS006` (`ERROR_MODEL_PERMISSION_UNMATCHED`) classification warning per cause with targeted remediation guidance.
- **Tests**: Added `TestModelPermissionsDiagnostics` (4 integration tests) and `TestPipelineIRBWithoutModelPermissions` (1 integration test) in `tests/integration/test_model_permissions_pipeline.py`, plus a regression guard `test_irb_mode_preserves_full_irb_after_pipeline_init` in `tests/unit/test_irb_approach_selection.py`.

## [0.1.180] — 2026-04-09

### Fixed
- **Docs**: Replaced fabricated double-default formula in `crm.md` with correct CRR Art. 153(3) formula `K_dd = K_obligor × (0.15 + 160 × PD_guarantor)` (D3.7). Added eligibility requirements (Art. 202/217), guarantor RW floor, and Basel 3.1 removal warning with cross-link to A-IRB spec.

## [0.1.179] — 2026-04-09

### Fixed
- **Docs**: SA specialised lending waterfall position documented in `key-differences.md` (D2.20). Waterfall item 15 annotated with Art. 122–122B SA SL sub-classification cross-reference. New admonition added explaining SA SL sits within corporates (row 15, Art. 112(1)(g)), with IPRE excluded per Art. 122A(1) ("not a real estate exposure") — IPRE is caught at row 7 (real estate, Art. 124–124L) instead. SA SL section expanded with:
  - Art. 122A(1) 4-part definition criteria (SPV structure, asset dependency, lender control, asset income repayment)
  - Art. 122A(2) sub-type classification (OF, CF, PF)
  - IPRE exclusion warning admonition with cross-reference to real estate section
  - Art. 122B(1) rated SL fallthrough to corporate CQS table
  - Art. 122B(2) unrated risk weight table with article references per row
  - Art. 122B(3) operational phase definition (positive net cash-flow + declining LT debt)
  - Art. 122B(4)–(5) high-quality PF criteria (8 structural conditions)

## [0.1.178] — 2026-04-08

### Fixed
- **Docs**: Art. 128 (high-risk items, 150%) UK CRR omission clarified across 6 files (D1.28, D4.9). Art. 128 was omitted from UK onshored CRR by SI 2021/1078, reg. 6(3)(a), effective 1 January 2022 — the high-risk exposure class is a dead letter under current UK CRR. Re-introduced under PRA PS1/26 (Basel 3.1, from 1 January 2027) with paragraphs 1 and 3 retained (paragraph 2 left blank). Files updated:
  - `specifications/crr/sa-risk-weights.md`: Added omission admonition, B31 re-introduction note, code bug cross-reference (D3.12), and exposure class waterfall clarification (equity priority 3 > high-risk priority 4)
  - `user-guide/exposure-classes/other.md`: Restructured "Items Associated with High Risk" section — added framework applicability warning, corrected table to Art. 128 items only (speculative RE, PRA-designated), added waterfall note explaining PE/VC are equity (Art. 133), not high-risk
  - `framework-comparison/key-differences.md`: Corrected equity table row (removed "(or 150% if Art. 128 high-risk)" — PE/VC is equity per waterfall), added Art. 128 re-introduction admonition to priority waterfall section
  - `user-guide/regulatory/crr.md`: Added "Omitted Provisions" section documenting Art. 128 and Art. 132 omissions by SI 2021/1078
  - `specifications/crr/equity-approach.md`: Corrected Art. 128 note to explain waterfall precedence (equity > high-risk) and UK CRR omission
  - `specifications/common/hierarchy-classification.md`: Updated calculator coverage note with Art. 128 framework status and CRR legal basis issue

## [0.1.177] — 2026-04-08

### Added
- **COREP**: Reporting basis conditionality for output floor (P1.38(c)). `COREPGenerator` now accepts `output_floor_config: OutputFloorConfig` to gate floor-related COREP template content on entity-type applicability per Art. 92 para 2A:
  - **OF 02.00 rows 0034-0036** (floor activated/multiplier/OF-ADJ) show 0.0 for exempt entities (international subsidiaries, ring-fenced bodies on individual basis, etc.)
  - **OF 02.01** (output floor comparison) returns None for exempt entities — only applicable entities report the floor comparison
  - **C 08.07 materiality columns 0160-0180** documented as consolidated-basis-only (Art. 150(1A)), threaded with `is_consolidated` flag for future population
  - **COREPTemplateBundle** extended with `reporting_basis` and `institution_type` metadata fields
  - **ResultExporterProtocol** and **ResultExporter** accept `output_floor_config` keyword parameter
- **Tests**: 38 new tests in `tests/unit/test_corep_reporting_basis.py` across 7 test classes: COREPTemplateBundleMetadata (7), OF0201FloorApplicability (6), OF0200FloorIndicatorRows (7), C0807MaterialityColumns (4), BackwardCompatibility (3), EntityTypeCombinations (9 parametrized), ExporterProtocolCompliance (2). Total: 5,125 (was 5,087). Contract tests: 145.

## [0.1.176] — 2026-04-08

### Fixed
- **Docs**: Documentation accuracy sweep correcting wrong regulatory values across 13 files (P4.5, P4.6, P4.22):
  - **PD floors (P4.5)**: Retail mortgage Basel 3.1 PD floor corrected from 0.05% to **0.10%** (Art. 163(1)(b)) in 5 files. QRRE transactor Basel 3.1 PD floor corrected from 0.03% to **0.05%** (Art. 163(1)(c)) in 5 files. Affected: `api/configuration.md`, `user-guide/configuration.md`, `user-guide/exposure-classes/retail.md`, `data-model/regulatory-tables.md`.
  - **LGD floors (P4.6)**: Corporate LGD floor code example corrected (RECEIVABLES 15%→10%, CRE 15%→10%, OTHER_PHYSICAL 20%→15%) in `user-guide/configuration.md`. Corporate `residential_real_estate` field corrected from 0.05 to **0.10** (Art. 161(5)) in `api/configuration.md` — was showing retail floor instead of corporate floor.
  - **Output floor schedule (P4.22)**: BCBS 6-year schedule (50%/55%/60%/65%/70%/72.5%, 2027–2032) replaced with PRA 4-year schedule (**60%/65%/70%/72.5%**, 2027–2030) across 12 files. Affected: `plans/implementation-plan.md`, `api/engine.md`, `api/contracts.md`, `framework-comparison/reporting-differences.md`, `plans/prd.md`, `specifications/index.md`, `features/index.md`, `specifications/regulatory-compliance.md`, `framework-comparison/index.md`, `appendix/index.md`, `framework-comparison/impact-analysis.md`, `user-guide/configuration.md`.

## [0.1.175] — 2026-04-08

### Fixed
- **CRM**: Decoupled `is_main_index` from `is_eligible_financial_collateral` for equity collateral haircuts (P6.21). Added `is_main_index` Boolean field to `COLLATERAL_SCHEMA`. When present, drives haircut lookup directly: `True` = main-index (CRR 15%, B31 20%), `False` = other-listed (CRR 25%, B31 30%). When absent, falls back to `is_eligible_financial_collateral` for backward compatibility. Previously all eligible equity was forced to the main-index haircut tier.

### Added
- **Tests**: 26 new tests in `tests/unit/crm/test_equity_main_index.py` across 7 test classes: schema validation, CRR/B31 haircut verification for main-index and other-listed, backward compatibility, precedence over eligibility flag, mixed collateral, and full pipeline end-to-end (other-listed EAD = 625k vs main-index EAD = 575k on 1M exposure with 500k equity collateral). Total: 5,087 (was 5,061).

## [0.1.174] — 2026-04-08

### Added
- **Tests**: 36 new CRM acceptance tests in `tests/acceptance/crr/test_scenario_crr_d2_crm_advanced.py` across 13 test classes covering advanced CRM scenarios not tested by the basic D1-D6/G1-G3 groups: non-beneficial guarantee (guarantor RW = borrower RW), sovereign guarantee 0% substitution, CDS restructuring exclusion (40% haircut, Art. 216(1)/233(2)), CDS with restructuring (no haircut contrast), gold collateral (15% CRR haircut), equity collateral (main-index 15%), overcollateralisation (EAD=0), full CRM chain (provision+collateral+guarantee), mixed collateral types (cash+bond), SA provision EAD deduction, multiple provisions summed, provision+collateral combined, and structural baseline validation. CRR acceptance: 169 (was 133). Total: 5,061 (was 5,025). (P5.3)

### Found
- **CRM**: Equity collateral `is_eligible_financial_collateral` was overloaded as `is_main_index` proxy in haircut lookup (`haircuts.py:282-285`). Fixed in v0.1.175 (P6.21).

## [0.1.173] — 2026-04-08

### Fixed
- **COREP**: OF 02.00 IRB sub-row splits — rows 0295-0297 (FSE/large, SME, non-SME corporates), 0355-0356 (retail RE SME/non-SME), 0382-0385 (corporate RE sub-splits), 0400/0410 (other retail SME/non-SME) now populated from pipeline data instead of hardcoded 0.0. Uses finer-grained aggregation keyed by (approach, exposure_class, is_sme, apply_fi_scalar, property_type).
- **COREP**: OF 02.00 floor indicator rows 0035/0036 — floor_pct and of_adj now populated from `OutputFloorSummary` when provided, instead of hardcoded 0.0.
- **COREP**: `_filter_re()` fallback chain — gracefully degrades from `materially_dependent_on_property` → `has_income_cover` → `is_income_producing` when pipeline columns vary. Null handling corrected: only fallback columns use `fill_null(False)`, preserving null-as-unclassified semantics for the primary column.
- **Equity**: `_apply_transitional_floor()` now emits `equity_transitional_approach` and `equity_higher_risk` annotation columns for COREP OF 07.00 rows 0371-0374.
- **Tests**: 24 new COREP tests across 4 classes (IRB sub-row splits, floor indicators, RE fallback, equity transitional columns). COREP tests: 687 (was 663). Total: 5,025 (was 5,001). (P2.5)

## [0.1.170] — 2026-04-08

### Added
- **COREP**: C 09.01 / OF 09.01 — CR GB 1 geographical breakdown SA. One DataFrame per country code + TOTAL. CRR: 13 columns (0010-0090 incl. supporting factors), 23 rows. Basel 3.1: 10 columns (removes supporting factors), 29 rows (adds SL sub-rows 0071-0073, RE sub-rows 0091-0094, removes short-term row). Uses `cp_country_code` from counterparty schema. Template definitions, generator methods, class maps, framework selectors.
- **COREP**: C 09.02 / OF 09.02 — CR GB 2 geographical breakdown IRB. One DataFrame per country code + TOTAL. CRR: 17 columns (incl. PD, LGD, EL, supporting factors), 16 rows (incl. equity). Basel 3.1: 15 columns (adds 0107 defaulted EV, removes supporting factors), 19 rows (adds corporate sub-rows, restructures retail RE, removes equity).
- **Tests**: 80 new COREP tests for C 09.01/09.02 across 10 test classes. COREP tests: 635 (was 555). Total: 4,953 (was 4,873). (P2.3)

## [0.1.169] — 2026-04-08

### Added
- **COREP**: C 08.04 / OF 08.04 — CR IRB RWEA flow statements. 1 column (RWEA) × 9 rows (opening, 7 movement drivers, closing) per IRB exposure class. Closing RWEA (row 0090) populated from pipeline; opening and drivers null (require prior-period data). Slotting excluded. CRR column names "after supporting factors"; Basel 3.1 removes supporting factors reference. Template definitions: `CRR_C08_04_COLUMNS`, `B31_C08_04_COLUMNS`, `C08_04_ROWS`, `C08_04_COLUMN_REFS`, `get_c08_04_columns()`. Generator: `_generate_all_c08_04()`, `_generate_c08_04_for_class()`. `COREPTemplateBundle.c08_04` field (dict[str, pl.DataFrame]). Excel export with C 08.04 / OF 08.04 prefix.
- **Tests**: 41 new COREP tests for C 08.04 across 6 test classes (TestC0804TemplateDefinitions: 13, TestC0804Generation: 5, TestC0804ClosingRWEA: 4, TestC0804NullDriverRows: 9, TestC0804B31Features: 3, TestC0804EdgeCases: 7). COREP tests: 555 (was 514). (P2.2)

## [0.1.168] — 2026-04-08

### Added
- **Pillar III**: UKB CR9 — IRB PD backtesting per exposure class (Art. 452(h)). 8 columns × 17 PD buckets + total row. Basel 3.1 only. Separate F-IRB and A-IRB template sets. Uses `irb_pd_original` for bucket allocation (beginning-of-period proxy). Includes obligor count, default count, observed default rate, EAD-weighted average PD, arithmetic mean PD, historical annual default rate.
- **Pillar III**: UKB CR9.1 — ECAI mapping PD backtesting (Art. 180(1)(f)). Template definitions only; generation deferred until pipeline provides firm-specific ECAI mapping data.
- **Pillar III**: `Pillar3TemplateBundle.cr9` field added (dict of approach–class keyed DataFrames)
- **Pillar III**: CR9 Excel export via `export_to_excel()` with human-readable sheet names (e.g., "UKB CR9 F-IRB Corp")
- **Tests**: 44 new tests for CR9/CR9.1 across 7 test classes (definitions, generation, column values, PD allocation, edge cases, bundle integration, Excel export). Total: 4,832 (was 4,788). (P3.2)

## [Unreleased]

### Added
- **Pillar III**: CMS1 — Output floor comparison by risk type (Art. 456(1)(a)). 4 columns × 8 rows. Basel 3.1 only. Only credit risk row populated from pipeline.
- **Pillar III**: CMS2 — Output floor comparison by asset class (Art. 456(1)(b)). 4 columns × 17 rows. Basel 3.1 only. Full asset class breakdown with FIRB/AIRB/slotting sub-rows.
- **Pillar III**: `Pillar3TemplateBundle.cms1` and `.cms2` fields added
- **Pillar III**: CMS1/CMS2 Excel export via `export_to_excel()` (UKB CMS1, UKB CMS2 sheets)
- **Tests**: 47 new tests for CMS1/CMS2 (7 CMS1 definition, 13 CMS1 generation, 8 CMS2 definition, 16 CMS2 generation, 3 end-to-end). Total: 4,687 (was 4,640). (P3.4)

### Added
- **SA**: Implement Art. 110A due diligence risk weight override (Basel 3.1 only). Two new optional schema fields (`due_diligence_performed`, `due_diligence_override_rw`) allow firms to flag DD assessment status and override SA risk weights upward where due diligence reveals higher risk. Override uses max(calculated_rw, override_rw) — can only increase, never decrease. SA004 warning emitted when DD assessment status is absent under B31. 25 new unit tests (P1.49)

### Fixed
- **IRB**: `IRBCalculator.calculate_expected_loss()` now emits IRB004/IRB005 warnings when PD/LGD columns are absent, instead of silently defaulting to PD=1%/LGD=45% with no error reporting (P1.88)
- **Spec**: Fix CCF spec incorrect F-IRB Basel 3.1 table values (75%→50%, 40%→10% per Art. 166C), add missing Table A1 rows (P4.13)
- **Spec**: Fix key-differences.md stale implementation status — currency mismatch, SA specialised lending, provision-based defaulted treatment now correctly shown as implemented (P4.14)
- **Spec**: Fix SA risk weights spec stale Basel 3.1 status markers for completed features

### Added
- **CRM**: Implement Financial Collateral Simple Method (Art. 222) — `CRMCollateralMethod` enum (`COMPREHENSIVE`/`SIMPLE`) on `CalculationConfig`, new `engine/crm/simple_method.py` module with collateral RW derivation by type/CQS, Art. 222(4) zero-RW exceptions, multi-level allocation, 20% RW floor, blended secured/unsecured risk weight substitution in SA calculator, COREP row 0070 reporting. 49 new unit tests
- **UI**: Add template workbench — duplicate read-only template workbooks into editable user workspace with full Python and SQL support via `marimo edit`
- **UI**: Add workspace management REST API (`/api/templates`, `/api/workbooks`, `/api/workbooks/duplicate`, `/api/workbooks/{name}`)
- **UI**: Add "Workbench" link to sidebar navigation in all template apps

### Changed
- **API**: Replace `RWAService` + `CalculationRequest` + `quick_calculate` + `create_service` with single `CreditRiskCalc` class. Usage: `CreditRiskCalc(data_path=..., framework=..., reporting_date=...).calculate()`. All response models (`CalculationResponse`, `SummaryStatistics`, etc.) are unchanged.
- **Config**: Replace granular `IRBPermissions` config (with `sa_only()`, `full_irb()`, `firb_only()`, etc.) with a simple two-mode `PermissionMode` enum (`STANDARDISED` / `IRB`). The `permission_mode` parameter on `CalculationConfig.crr()` and `.basel_3_1()` replaces the old `irb_permissions` parameter. In IRB mode, `model_permissions` input data drives all approach routing (AIRB, FIRB, slotting); without it, the pipeline falls back to SA with a warning. `IRBPermissions` remains as an internal implementation detail but is no longer part of the public API.
- **Classifier**: Add `model_slotting_permitted` flag to model permissions resolution, enabling slotting to be driven by per-model permissions alongside AIRB and FIRB
- **Model Permissions**: Add `"slotting"` as a valid `approach` value (alongside `"foundation_irb"` and `"advanced_irb"`)
- **Comparison**: `TransitionalScheduleRunner.run()` now accepts `permission_mode` instead of `irb_permissions`

### Added
- **Engine**: Add `materialise.py` module with strategy-aware materialization barriers — supports disk-spill (`sink_parquet` → `scan_parquet`) for out-of-core datasets and in-memory (`collect().lazy()`) for backward compatibility, controlled by `config.collect_engine`
- **Config**: Add `spill_dir` field to `CalculationConfig` for configuring temp file directory during streaming materialization
- **Tests**: Add unit tests for `materialise_barrier`, `materialise_branches`, and `cleanup_spill_files`

### Changed
- **Data Tables**: Consolidate slotting risk weights — `engine/slotting/namespace.py` now sources all risk weights from `data/tables/` instead of defining them inline, consistent with SA/IRB/Equity engines
- **Data Tables**: Export all 4 CRR slotting weight dicts and convenience functions from `data/tables/__init__.py` (previously only 2 of 4 were exported)

### Added
- **Data Tables**: Add `b31_slotting.py` with Basel 3.1 slotting risk weights (base, pre-operational, HVCRE) per BCBS CRE33
- **Tests**: Add unit tests for Basel 3.1 slotting tables and extend CRR slotting short-maturity test coverage

### Removed
- **Engine**: Remove unused `calculate_unified()` from `SlottingCalculator`, `IRBCalculator`, and their protocols — only SA uses this method (for the output floor). Simplifies the slotting and IRB calculator interfaces.
- **Engine**: Remove unused `calculate()` from `SlottingCalculator` and its protocol — the pipeline uses `calculate_branch()` directly. Also remove dead `_run_slotting_calculator()` from pipeline.

### Added
- **Docs**: Add OF 02.00 and OF 02.01 output floor reporting documentation — master own funds requirements template with new SA-only and output floor columns, dedicated output floor comparison template (U-TREA vs S-TREA), flow diagram showing how IRB output floor columns feed into total capital, Pillar III cross-reference (UKB OV1/KM1)
- **Docs**: Add CIU exposure treatment to key-differences — three approaches (look-through, mandate-based, 1250% fallback), impact of IRB equity removal on CIU underlyings, and CIU transitional (Art. 4.7–4.8)
- **Docs**: Add IRB equity transitional to key-differences — floor-based transition for firms with existing IRB permission (Art. 4.4–4.6), irrevocable opt-out (Art. 4.9–4.10)
- **Docs**: Add post-model adjustments (PMAs) section to key-differences — new Basel 3.1 concept (Art. 146(3)) with no CRR equivalent
- **Docs**: Add retail-specific A-IRB LGD floor table to key-differences — 5% mortgage, 50% QRRE, 30% other unsecured, 30% LGDU
- **Docs**: Add "Why Basel 3.1?" section to framework comparison index — explains the rationale for transitioning from CRR (risk-weight variability, inadequate capital, IRB complexity) and how Basel 3.1 responds

### Fixed
- **Docs**: Add missing sovereign (central govts, central banks, quasi-sovereigns) SA-only restriction to IRB approach tables — Art. 147A(1)(a) mandates SA for all sovereign exposures under Basel 3.1, removing F-IRB and A-IRB
- **Docs**: Add missing IPRE/HVCRE specialised lending Slotting-only restriction — Art. 147A(1)(c); replaces misleading "Specialised Lending (no PD)" row which conflated all SL sub-types
- **Docs**: Correct large corporate revenue threshold in `basel31.md` from >£500m to >£440m (Art. 147(4C))
- **Docs**: Correct equity transitional schedule — 2027 starts at 160%/220% (not 130%/160%) after implementation date shifted to 2027
- **Docs**: Split F-IRB senior LGD into financial entities (45%, unchanged) and other corporates (40%) — previously shown as single 40% row
- **Docs**: Correct large corporate threshold from >£500m to >£440m (Art. 147(4C))
- **Docs**: Correct correlation multiplier scope — 1.25x applies to financial sector entities (Art. 153(2)), not all large corporates
- **Docs**: Correct PD floor for retail mortgage from 0.05% to 0.10% (PRA Art. 163(1)(b))
- **Docs**: Correct PD floor for QRRE transactor from 0.03% to 0.05% (falls under "all other retail")
- **Docs**: Correct unfunded credit protection terminology — "cancel or change" (Art. 213(1)(c)(i)), not "change of control"
- **Docs**: Add Pillar III disclosure documentation covering 9 quantitative credit risk templates (OV1, CR4, CR5, CR6, CR6-A, CR7, CR7-A, CR8, CR10) with CRR and Basel 3.1 column/row definitions
- **Docs**: Add CRR vs Basel 3.1 disclosure differences page — template naming (UK→UKB), output floor rows, expanded risk weight columns, post-model adjustments, slotting CRM, equity transitional treatment
- **Docs**: Expand COREP template comparison documentation to cover all 9 key credit risk templates (C 07.00, C 08.01–08.07, C 09.01–09.02) — previously only C 07.00, C 08.01, C 08.02 were documented
- **Docs**: Add full CRR vs Basel 3.1 column/row reference for C 08.03 (PD ranges), C 08.04 (RWEA flow), C 08.06 (slotting), C 08.07 (scope of use), C 09.01 (geo SA), C 09.02 (geo IRB)

### Fixed
- **Docs**: Correct Template Overview in reporting-differences.md — C 08.03 exists in CRR (PD ranges breakdown), not a new Basel 3.1 slotting template

### Changed
- **Engine**: Simplify IRB engine module structure — extract `adjustments.py` (defaulted treatment, post-model adjustments, EL shortfall) and `guarantee.py` (guarantee substitution) from `namespace.py`, deduplicate correlation/K/maturity-adjustment formulas in `formulas.py`, remove dead code (`_norm_cdf`, `_norm_ppf`, `IRBCalculationError`)

### Removed
- **Engine**: Remove unused `HierarchyLazyFrame` namespace (`hierarchy_namespace.py`) — duplicated logic from `hierarchy.py` and was not used in production code
- **Engine**: Remove unused `CRMLazyFrame` namespace (`crm/namespace.py`) and `HaircutsLazyFrame`/`HaircutsExpr` namespaces (`crm/haircuts_namespace.py`) — independent reimplementations not used in production pipeline (CRMProcessor is the sole production API)
- **Engine**: Remove unused `SALazyFrame`/`SAExpr` namespaces (`sa/namespace.py`) — SACalculator uses private methods directly

### Added
- **Docs**: New top-level "CRR vs Basel 3.1" section consolidating all framework comparison content — key differences, reporting differences, impact analysis, and technical reference
- **Docs**: New reporting differences page documenting COREP template changes between C-prefix (CRR) and OF-prefix (Basel 3.1) templates
- **Docs**: Add retail transactor (45%) and payroll/pension (35%) risk weights to framework comparison and Basel 3.1 guide
- **Docs**: Add equity risk weight section with 250%/400% structure and 2027-2029 transitional phase-in schedule
- **Docs**: Add currency mismatch 1.5x risk weight multiplier for unhedged FX retail/residential RE exposures
- **Docs**: Add SA specialised lending risk weights (Art. 122A-122B: object/commodities/project finance)
- **Docs**: Add CRM structural changes — Foundation Collateral Method, Parameter Substitution Method, overcollateralisation thresholds, change of control provisions
- **Docs**: Add exposure class priority waterfall restructuring (real estate as standalone class)
- **Docs**: Add institution ECRA/SCRA risk weight detail with short-term exposure weights
- **Docs**: Add financial sector entities to IRB A-IRB restrictions table
- **Docs**: Add IRB 10% RW floor for UK residential mortgages (PRA-specific)
- **Docs**: Add regional government/local authority and covered bond risk weight changes
- **Docs**: Add output floor OF-ADJ formula detail to technical reference
- **Docs**: Add full supervisory haircut comparison tables (CRR 3-band vs Basel 3.1 5-band)
- **Docs**: Add IRB maturity calculation changes (revolving: M = max contractual termination date)
- **Docs**: Add slotting subgrade detail (Strong A/B, Good C/D for residual maturity)

### Changed
- **Regulatory**: Update all Basel 3.1 references from PRA PS9/24 (near-final) to PRA PS1/26 (final rules) across source code, documentation, tests, and workbooks
- **Regulatory**: Replace old PS9/24 and CP16/22 URLs with PS1/26 final rules links (policy statement, Appendix 1, Appendix 17)
- **Regulatory**: Mark CP16/22 consultation paper as superseded where retained for historical context
- **CI**: Add version consistency validation step to publish workflow
- **CI**: Add step to generate test fixtures in CI pipeline
- **CI**: Replace mypy with ty for type checking
- **Docs**: Migrate documentation from mkdocs to zensical (`zensical.toml` replaces `mkdocs.yml`)

### Removed
- **Docs**: Remove completed development roadmap (`docs/plans/roadmap.md`) to reduce maintenance burden

### Fixed
- **Regulatory**: Replace incorrect BCBS whole-loan LTV-band approach for general residential RE with PRA-mandated loan-splitting (Art. 124F) — secured portion (up to 55% of property value) at 20%, residual at counterparty RW
- **Regulatory**: Fix income-producing residential RE 60-70% LTV band risk weight from 45% to 40% per PRA Table 6B (Art. 124G)
- **Docs**: Fix incorrect Basel 3.1 haircut table in `basel31.md` — equity haircuts are 25%/35% (not 15%/25%), long-dated bond haircuts also increased
- **Docs**: Fix defaulted exposure comparison table to show residential RE flat 100% under Basel 3.1
- **Docs**: Fix residential RE tables to describe PRA loan-splitting instead of BCBS whole-loan table
- **Docs**: Fix mermaid diagrams not rendering by adding `custom_fences` configuration for `pymdownx.superfences`
- **Style**: Update theme color palette to orange

### Refactored
- Improve risk weight dictionary creation in test helpers
- Clean up code formatting and assertions in tests

---












## [0.1.55] - 2026-04-09

### Changed
- Version bump for PyPI release

---

## [0.1.54] - 2026-04-08

### Changed
- Version bump for PyPI release

---

## [0.1.53] - 2026-04-07

### Changed
- Version bump for PyPI release

---

## [0.1.52] - 2026-04-06

### Changed
- Version bump for PyPI release

---

## [0.1.51] - 2026-04-05

### Changed
- Version bump for PyPI release

---

## [0.1.50] - 2026-04-01

### Changed
- Version bump for PyPI release

---

## [0.1.49] - 2026-03-30

### Changed
- Version bump for PyPI release

---

## [0.1.48] - 2026-03-29

### Changed
- Version bump for PyPI release

---

## [0.1.47] - 2026-03-28

### Changed
- Version bump for PyPI release

---

## [0.1.46] - 2026-03-28

### Changed
- Version bump for PyPI release

---

## [0.1.45] - 2026-03-27

### Added

#### CCP Guarantor Risk Weight Support (CRR Art. 306 / CRE54.14-15)
CCP guarantors now receive the prescribed QCCP risk weight (2% proprietary / 4% client-cleared) instead of being treated as generic unrated institutions (40% RW). The guarantee substitution when/then chain in both the SA calculator and IRB namespace checks `guarantor_entity_type == "ccp"` before the institution/MDB branch, applying `QCCP_PROPRIETARY_RW` (2%) or `QCCP_CLIENT_CLEARED_RW` (4%) based on `guarantor_is_ccp_client_cleared`.

- CRM processor and namespace propagate `is_ccp_client_cleared` from guarantor counterparty data
- Entity type normalization (`.str.to_lowercase()`) applied to guarantor entity type joins

---

## [0.1.44] - 2026-03-25

### Added

#### ~~Article 114(4)~~ Article 114(7) EU domestic currency 0% risk weight for EU sovereigns

!!! warning "Correction (D4.35)"
    The original entry cited Art. 114(4). In the UK-onshored CRR, Art. 114(4)
    covers only the UK central government and Bank of England in sterling.
    EU member state domestic-currency treatment is provided by **Art. 114(7)**
    (third-country reciprocity).

EU member state central government and central bank exposures denominated in that member state's domestic currency now receive 0% risk weight regardless of CQS, per CRR Art. 114(7). Covers all 27 EU member states: eurozone members (EUR) and non-euro members in their national currencies (PLN, SEK, CZK, DKK, HUF, BGN, RON). EU domestic sovereign exposures are also forced to the Standardised Approach, preventing internal models from overriding the regulatory 0% treatment. Applies to both direct exposures and guarantor risk weight substitution (SA and IRB).

- `is_ccp_client_cleared` field added to data generators

### Fixed
- CCP exposures now forced to SA approach with correct risk weights (was falling through to generic corporate treatment)

---

## [0.1.43] - 2026-03-24

### Fixed

#### Guarantee application expanded to facility and counterparty levels
Guarantee application previously only matched at direct (loan/exposure/contingent) level. Guarantees linked at facility or counterparty level were silently ignored. Now supports multi-level beneficiary matching: direct, facility (pro-rata across facility's exposures), and counterparty (pro-rata across all counterparty exposures).

---

## [0.1.42] - 2026-03-22

### Fixed

#### Slotting maturity not derived from `maturity_date`
The `is_short_maturity` flag for CRR Art. 153(5) specialised lending was never calculated from exposure `maturity_date`. It defaulted to `False`, causing all exposures to receive the >= 2.5yr risk weights regardless of actual remaining maturity. Strong category exposures with <2.5yr maturity now correctly receive 50% RW (was 70%), Good receives 70% (was 90%), HVCRE Strong receives 70% (was 95%), and HVCRE Good receives 95% (was 120%).

- `prepare_columns()` now accepts `CalculationConfig` and derives `is_short_maturity` from `maturity_date` and `reporting_date`
- Extracted `exact_fractional_years_expr` to shared `engine/utils.py` (reused by IRB and slotting)
- Added `remaining_maturity_years` column to slotting audit trail
- Added CRR-E5 through CRR-E8 acceptance scenarios for short-maturity slotting

#### UK govt guarantee exposure marked "not beneficial" for non-sovereign entity types
Guarantor risk weight lookup used regex matching on `guarantor_entity_type` (e.g., `contains("SOVEREIGN")`), which only matched `sovereign` but not `central_bank`, `bank`, `company`, or `mdb`. These entity types produced `null` guarantor RW, causing beneficial guarantees to be incorrectly skipped. The lookup now uses `guarantor_exposure_class` (derived from the existing `ENTITY_TYPE_TO_SA_CLASS` mapping), ensuring all valid entity types resolve to the correct SA risk weight. Also adds Art. 114(4) domestic sovereign treatment: UK CGCB guarantors in GBP receive 0% RW regardless of CQS. *(Correction (D4.35): original entry cited Art. 114(3); Art. 114(3) is the ECB provision, Art. 114(4) is UK domestic currency.)* Both SA calculator and IRB namespace are fixed. CRM processor and namespace now propagate `guarantor_country_code` from counterparty data.

---

## [0.1.41] - 2026-03-22

### Added

#### ~~Article 114(3)~~ Article 114(4) domestic currency 0% risk weight for UK sovereign

!!! warning "Correction (D4.35)"
    The original entry cited Art. 114(3). CRR Art. 114(3) is the **ECB** 0%
    provision. The UK domestic currency provision is **Art. 114(4)**.

UK central government and central bank exposures denominated in GBP now receive 0% risk weight regardless of CQS, per CRR Art. 114(4). Previously, 0% was only assigned via CQS 1 external rating lookup. The override applies in both CRR and Basel 3.1 SA risk weight chains. Foreign-currency UK sovereign exposures continue to use the standard CQS-based risk weight table.

---

## [0.1.40] - 2026-03-22

### Changed

#### Specialised lending now input-driven via `counterparty_reference`
Specialised lending metadata (`sl_type`, `slotting_category`, `is_hvcre`) is now supplied as an input file (`exposures/specialised_lending.parquet`) keyed by `counterparty_reference`, rather than being derived from counterparty reference naming conventions. This allows a corporate counterparty to have both SL and non-SL exposures, aligning with CRR Art. 147(8) and BCBS CRE30.6.

- **New input file**: `ratings/specialised_lending.parquet`
- **Schema change**: `exposure_reference` replaced with `counterparty_reference`; `remaining_maturity_years` removed (sourced from loan/facility data)
- **Removed dead code**: `_build_slotting_category_expr()`, `_build_sl_type_expr()`, and counterparty reference naming convention logic in the classifier

### Fixed

#### FI scalar (`apply_fi_scalar`) not applied to IRB correlation
The `apply_fi_scalar` counterparty flag was gated on `is_financial_sector_entity`, which required the `entity_type` to be an institution-like value. Counterparties with `entity_type="corporate"` and `apply_fi_scalar=True` silently received no 1.25x correlation multiplier. The classifier now derives `requires_fi_scalar` directly from the user-supplied `apply_fi_scalar` flag.

**Removed dead code**: `FINANCIAL_SECTOR_ENTITY_TYPES`, `is_financial_sector_entity`, and `is_large_financial_sector_entity` — set in the classifier but never consumed by any calculation engine.

---

## [0.1.39] - 2026-03-21

### Fixed
- SME managed-as-retail 75% RW now correctly gated on EUR 1m turnover threshold check (was applying 75% RW without verifying threshold)

### Changed
- Documentation aligned with current codebase state

---

## [0.1.38] - 2026-03-20

### Fixed
- Null `slotting_category` and `sl_type` for non-slotting exposures (was leaving stale values from classification)
- Defaulted exposure treatment for SA risk weights now correctly implemented
- Case-insensitive column value validation (lowercase valid values set before comparison)
- `country_codes` and `excluded_book_codes` columns in `model_permissions` input are now truly optional — when absent, treated as null (all geographies permitted, no book code exclusions). Previously caused `ColumnNotFoundError`
- Documentation aligned with code schemas across 13 files

---






## [0.1.37] - 2026-03-17

### Fixed
- Validation error messages now correctly convert file paths to string (was raising `TypeError` for `Path` objects)

---

## [0.1.36] - 2026-03-15

### Changed

#### Model ID moved from counterparty to ratings level (Breaking)
`model_id` has been moved from `COUNTERPARTY_SCHEMA` to `RATINGS_SCHEMA`. The rating inheritance pipeline now carries `model_id` alongside `internal_pd` through parent-child inheritance, eliminating the redundant counterparty-to-exposure propagation path.

- **Removed**: `model_id` from `COUNTERPARTY_SCHEMA`
- **Added**: `model_id` to `RATINGS_SCHEMA`
- **Updated**: Rating inheritance pipeline carries `internal_model_id` through coalesce (own → parent)
- **Updated**: `_unify_exposures()` sources `model_id` from rating inheritance instead of counterparty join
- **Updated**: Fixture generators, integration tests, benchmark data generators, and documentation
- Counterparty data handling consolidated

---

## [0.1.35] - 2026-03-11

### Added

#### Integration Test Infrastructure
Comprehensive integration test suite covering the full pipeline from loader to output:

- **Phase 1**: Hierarchy → Classifier flow tests
- **Phase 2**: Classifier → CRM and CRM → Calculators flow tests
- **Phase 3**: Loader → Hierarchy, model permissions, and output floor tests
- **Phase 4**: Equity flow integration tests
- Integration test strategy document and shared infrastructure

### Changed
- `model_id` added to counterparty-level schema (subsequently moved to ratings in 0.1.36)

---

## [0.1.34] - 2026-03-10

### Added

#### Model-Level IRB Permissions
Per-model IRB approach gating replaces the org-wide `IRBPermissions` config when a `model_permissions` input file is provided:

- **New schema**: `MODEL_PERMISSIONS_SCHEMA` with `model_id`, `exposure_class`, `approach`, `country_codes`, `excluded_book_codes`
- **New column**: `model_id` on `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA` — links exposures to their IRB model
- **Classifier**: `_resolve_model_permissions()` joins exposures with model permissions, filters by geography and book code, gates approach on both permission and data availability (AIRB requires `internal_pd` + `lgd`; FIRB requires only `internal_pd`)
- **Backward compatible**: When no `model_permissions` file is present, org-wide `IRBPermissions` fallback applies
- **Validation**: `model_permissions` included in `validate_raw_data_bundle()` and `validate_bundle_values()` for schema and value validation
- `model_permissions` fixtures and `model_id` added to exposure generators
- API documentation updated
- 10 unit tests covering AIRB/FIRB gating, geography filters, book code exclusions, and backward compatibility

#### Rename `is_regulated` → `apply_fi_scalar`
Simplified FI scalar control on `COUNTERPARTY_SCHEMA`:

- **Schema**: `is_regulated` renamed to `apply_fi_scalar` — direct user-controlled flag replacing the intermediate boolean
- **Classifier**: `requires_fi_scalar` now derives from `is_financial_sector_entity AND cp_apply_fi_scalar` (simpler than the previous two-condition inference from `is_regulated`)
- **Documentation**: All references updated across input schemas, architecture, and classification docs

---

## [0.1.33] - 2026-03-09

### Added

#### Dual Per-Type Rating Resolution
Rating inheritance now resolves best internal and best external rating per counterparty independently. CQS is an external-only concept; internal ratings carry PD values without internal CQS.

- Per-type columns: `internal_pd`, `internal_rating_value`, `external_cqs`, `external_rating_value`
- Per-type inheritance: own internal → parent internal, own external → parent external (independent chains)
- Removed internal CQS references throughout the codebase

### Changed
- Enhanced netting facility handling in loan data

---

## [0.1.32] - 2026-03-08

### Added
- `netting_facility_reference` field added to `LOAN_SCHEMA` and loan data for explicit netting group assignment

---

## [0.1.31] - 2026-03-07

### Added
- Enhanced netting logic for facility siblings (pro-rata allocation within netting groups)
- `interest_for_ead` function in CCF module to handle negative interest values

---

## [0.1.30] - 2026-03-06

### Added

#### Basel 3.1 Engine
Full Basel 3.1 framework implementation alongside existing CRR support:

- **Revised SA risk weight tables** (CRE20.7-26) with LTV-band risk weights for residential and commercial real estate
- **Basel 3.1 supervisory haircuts** and F-IRB LGD framework dispatch
- **Output floor**: SA-equivalent RWA calculation on all IRB rows with phase-in schedule
- **Basel 3.1 acceptance tests**: B31-B (F-IRB), B31-C (A-IRB), B31-D (CRM), B31-E (slotting), B31-G (provisions), B31-H (complex scenarios) — 116 tests total
- **IRB**: A-IRB LGD floors gated on `is_airb` column (CRE30.41)
- **IRB**: QRRE transactor/revolver PD floor distinction (CRR Art. 147(5), CRE30.55)

#### Dual-Framework Comparison and Analysis
- **M3.1**: CRR vs Basel 3.1 side-by-side comparison with per-exposure RWA delta
- **M3.2**: Capital impact analysis with driver attribution
- **M3.3**: Transitional floor schedule modelling with year-by-year phase-in
- **M3.4**: Enhanced Marimo workbook for interactive impact analysis

#### EL Shortfall/Excess (CRR Art. 158-159)
Expected loss shortfall/excess computation for IRB portfolios, with portfolio-level Tier 2 credit cap per CRR Art. 62(d).

#### COREP Template Generation (FR-4.6 / M4.1)
Regulatory reporting templates for CRR firms following EBA/PRA COREP structure (Regulation (EU) 2021/451):

- **C 07.00** — SA credit risk: original exposure, SA EAD, RWA by exposure class, plus risk weight band breakdown
- **C 08.01** — IRB totals: original exposure, IRB EAD, RWA, expected loss, weighted-average PD/LGD/maturity by exposure class
- **C 08.02** — IRB PD grade breakdown: obligor-grade-level detail with standard PD bands and exposure-weighted averages
- `COREPGenerator` class with `generate()` and `export_to_excel()` methods
- `ResultExporter.export_to_corep()` for multi-sheet Excel export
- `CalculationResponse.to_corep()` convenience method

#### Programmatic Export API (FR-4.7)
Export calculation results to Parquet, CSV, and Excel formats programmatically.

#### On-Balance Sheet Netting (CRR Article 195)
Support for on-balance sheet netting of mutual claims when a legally enforceable netting agreement exists:

- **New fields**: `has_netting_agreement` and `netting_facility_reference` on `LOAN_SCHEMA` and `Loan` fixture
- **Synthetic cash collateral**: Negative-drawn netting-eligible loans generate cash collateral that reduces all positive-drawn sibling exposures pro-rata within the same netting facility
- **Netting facility resolution**: Priority chain — explicit `netting_facility_reference` → `root_facility_reference` → `parent_facility_reference`
- **SA**: EAD reduced by netting pool (cash = 0% haircut)
- **F-IRB**: LGD reduced via cash collateral path (0% LGD)
- **FX mismatch**: 8% haircut applied when currencies differ

#### Service API Documentation
Restructured user-facing documentation to promote the high-level Service API (`quick_calculate`, `RWAService`) as the primary entry point:

- **Quick Start** rewritten with 3-tier progression: `quick_calculate` one-liner, `RWAService` with more control, full example with validation/export
- **New page: `docs/api/service.md`** — complete Service API reference
- **API Reference index** features Service API as first module

#### Basel 3.1 Parameter Substitution for IRB Guarantors (CRE22.70-85)
IRB guarantee substitution parameters updated for Basel 3.1 framework.

#### CI/CD Pipeline
GitHub Actions workflow with lint, typecheck, and test jobs.

### Changed
- Replaced `Enum` with `StrEnum` and `IntEnum` throughout the codebase
- Centralised data source configuration with `DataSourceRegistry` replacing `RequiredFiles`
- Introduced `BaseRequest` class to reduce duplication in request models
- Error factory functions updated to support `Path` types alongside `str`
- Tests migrated to use `Path` for file paths

### Fixed
- Corporate bond haircut CQS grouping corrected per CRR Art. 224
- PD floors and transitional schedule corrected to PRA PS1/26
- Output floor `sa_rwa` computation fixed for acceptance tests
- Benchmark data generators now include all schema columns (`is_buy_to_let`, `interest`, `bs_type`, `pledge_percentage`, `is_qrre_transactor`)
- Benchmark tests updated for current API: `_unify_exposures` signature (added `facilities` arg), `CRMProcessor.get_crm_adjusted_bundle`
- Protocol test stubs updated to include `calculate_branch` method

---

## [0.1.29] - 2026-02-28

### Added
- F-IRB acceptance tests and expected outputs (CRR-B1 through B7)

### Changed
- Pipeline refactored to single-pass calculation for unified frame (filter-process-merge pattern)
- Classifier exposure classification logic optimized
- Hierarchy collateral allocation logic simplified
- RWA calculations simplified with filter-process-merge approach

### Performance
- Pipeline optimizations: pre-computed classifier intermediates, deferred audit string, slimmed counterparty join, eliminated unnecessary `collect_schema()` calls
- Full CRR pipeline at 100K: ~1.7s mean (SA-only ~1.7s, CRR ~1.9s)

---

## [0.1.28] - 2026-02-24

### Added
- Benchmarking module for RWA Calculator performance testing

### Performance
- Optimized aggregation data collection and processing
- Optimized hierarchy graph traversal methods
- Optimized exposure enrichment methods
- Optimized pledge resolution and validation in pipeline

---

## [0.1.27] - 2026-02-22

### Added
- Results caching with lazy loading for improved pipeline performance

### Changed
- Replaced custom validation methods with shared utility functions across hierarchy, loader, pipeline, and processor
- Replaced `enable_irb` boolean config with `irb_approach` enum for clearer IRB permission modelling
- Optimized data materialization to reduce redundant `.collect()` calls
- Multiple speed optimization PRs merged (aggregator, formatters, validation)

---

## [0.1.26] - 2026-02-21

### Performance
- Optimized aggregator processing for large result sets
- Optimized formatter output generation
- Streamlined validation data processing to reduce overhead
- UI speed improvements for interactive calculator

---

## [0.1.25] - 2026-02-20

### Added

#### IRB Defaulted Exposure Treatment (CRR Art. 153(1)(ii), 154(1)(i))
- Defaulted exposures (PD=1.0) receive K=0 under F-IRB and K=max(0, LGD-BEEL) under A-IRB
- Expected loss = LGD × EAD for defaulted exposures
- CRR 1.06 scaling factor correctly applied to defaulted corporate exposures
- New CRR-I acceptance test group with 9 tests (I1 F-IRB corporate, I2 A-IRB retail, I3 A-IRB corporate with CRR scaling)

### Fixed
- SME supporting factor now correctly uses drawn amount (not EAD) for tier threshold calculation

---

## [0.1.24] - 2026-02-19

### Added

#### Multi-Level SA Collateral Allocation
- Multi-level collateral allocation for SA EAD reduction with overcollateralisation compliance
- Haircut calculator enhancements for multi-level processing

---

## [0.1.23] - 2026-02-17

### Added

#### SA Provision Handling — Art. 111(1)(a)-(b) Compliance
Provisions are now resolved **before** CCF application using a drawn-first deduction approach, compliant with CRR Art. 111(1)(a)-(b):

**Pipeline reorder:**
```
resolve_provisions → CCF → initialize_ead → collateral → guarantees → finalize_ead
```

**New method:** `resolve_provisions()` with multi-level beneficiary resolution:
- **Direct** (loan/exposure/contingent): provision matched to specific exposure
- **Facility**: distributed pro-rata across facility's exposures
- **Counterparty**: distributed pro-rata across all counterparty exposures

**SA drawn-first deduction:**
- `provision_on_drawn = min(provision, max(0, drawn))` — absorbs provision against drawn first
- Remainder → `provision_on_nominal` — reduces nominal before CCF
- `nominal_after_provision = nominal_amount - provision_on_nominal` feeds into CCF

**IRB/Slotting:** Provisions tracked (`provision_allocated`) but NOT deducted from EAD (feeds EL shortfall/excess comparison)

**New columns:**
| Column | Type | Description |
|--------|------|-------------|
| `provision_on_drawn` | Float64 | Provision absorbed by drawn (SA only) |
| `provision_on_nominal` | Float64 | Provision reducing nominal before CCF (SA only) |
| `nominal_after_provision` | Float64 | `nominal_amount - provision_on_nominal` |
| `provision_deducted` | Float64 | Total = `provision_on_drawn + provision_on_nominal` |
| `provision_allocated` | Float64 | Total provision matched to this exposure |

**Other changes:**
- `finalize_ead()` no longer subtracts provisions (already baked into `ead_pre_crm`)
- `_initialize_ead()` preserves existing provision columns if set by `resolve_provisions`
- 14 unit tests in `tests/unit/crm/test_provisions.py`
- CCF test suite expanded to 57 tests

---

## [0.1.22] - 2026-02-16

### Changed
- Slotting risk weights updated for remaining maturity splits (CRR Art. 153(5))
- Config enhancements for slotting maturity bands

## [0.1.21] - 2026-02-16

### Added

#### Pledge Percentage for Collateral Valuation
- Introduced `pledge_percentage` field to allow collateral to be specified as a percentage of the beneficiary's EAD
- Collateral processing resolves `pledge_percentage` to absolute market values based on beneficiary type (loan, facility, or counterparty level)
- Updated input schemas and CRM methodology documentation to reflect the new field
- 403 lines of new tests covering pledge percentage resolution across different beneficiary levels

## [0.1.20] - 2026-02-14

### Added

#### Equity Exposure FX Conversion
- New `convert_equity_exposures()` method in FX converter for converting equity exposure values to reporting currency
- Updated classifier and hierarchy to support equity exposures in FX conversion pipeline
- Enhanced FX rate configuration with equity-specific handling
- Comprehensive tests for equity exposure conversion and currency handling

## [0.1.19] - 2026-02-11

### Added

#### Buy-to-Let Flag
- New `is_buy_to_let` boolean flag in hierarchy and schemas for identifying BTL exposures
- BTL exposures excluded from SME supporting factor discount
- Unit tests verifying BTL flag behaviour in supporting factor calculations

#### On-Balance EAD Helper
- New `on_balance_ead()` helper function in CCF module calculating EAD as `max(0, drawn) + interest`
- Updated CRM processor and namespace to use the new helper
- Comprehensive tests covering various on-balance EAD scenarios

### Changed
- Updated implementation plan and roadmap documentation with current test results and fixture completion status

## [0.1.18] - 2026-02-10

### Added

#### Facility Hierarchy Enhancements
- Facility root lookup and undrawn calculations for full facility hierarchy resolution
- Include contingent liabilities in facility undrawn calculations
- Enhanced facility hierarchy resolution logic

## [0.1.17] - 2026-02-10

### Added
- CCF: handle negative drawn amounts in EAD calculations

### Fixed
- Hierarchy: resolve duplicate mapping issues in facility calculations

## [0.1.16] - 2026-02-09

### Added

#### Cross-Approach CCF Substitution
- SA CCF expression and cross-approach substitution for guaranteed IRB exposures
- When an IRB exposure is guaranteed by an SA counterparty, the guaranteed portion uses SA CCFs
- New columns: `ccf_original`, `ccf_guaranteed`, `ccf_unguaranteed`, `guarantee_ratio`, `guarantor_approach`, `guarantor_rating_type`

#### Aggregator Enhancements
- Updated summaries for post-CRM reporting
- Enhanced approach handling for IRB results

## [0.1.15] - 2026-02-08

### Added
- Correlation: rename sovereign exposure class to central govt/central bank
- CI: add GitHub Actions workflow for documentation deployment

## [0.1.14] - 2026-02-07

### Added

#### Overcollateralisation Requirements (CRR Art. 230 / CRE32.9-12)
Non-financial collateral now requires overcollateralisation to receive CRM benefit:

| Collateral Type | Overcollateralisation Ratio | Minimum Threshold |
|----------------|---------------------------|-------------------|
| Financial | 1.0x | No minimum |
| Receivables | 1.25x | No minimum |
| Real estate | 1.4x | 30% of EAD |
| Other physical | 1.4x | 30% of EAD |

- `effectively_secured = adjusted_value / overcollateralisation_ratio`
- Financial vs non-financial collateral tracked separately for threshold checks
- Multi-level allocation respects overcollateralisation at each level

### Changed
- Standardized `collateral_type` casing and descriptions across codebase

## [0.1.13] - 2026-02-07

### Added

#### Input Value Validation
- `validate_bundle_values()` validates all categorical columns against `COLUMN_VALUE_CONSTRAINTS`
- Error code `DQ006` for invalid column values
- Pipeline calls `_validate_input_data()` as non-blocking step (errors collected, not raised)

### Fixed
- Prevented row duplication in exposure joins when `facility_reference = loan_reference` (#71)

## [0.1.12] - 2026-02-02

### Added

#### Equity Exposure Calculator
Complete equity exposure RWA calculation supporting two regulatory approaches:

**Article 133 - Standardised Approach (SA):**
| Equity Type | Risk Weight |
|-------------|-------------|
| Central bank | 0% |
| Listed/Exchange-traded/Government-supported | 100% |
| Unlisted/Private equity | 250% |
| Speculative | 400% |

**Article 155 - IRB Simple Risk Weight Method:**
| Equity Type | Risk Weight |
|-------------|-------------|
| Central bank | 0% |
| Private equity (diversified portfolio) | 190% |
| ~~Government-supported~~ | ~~190%~~ |
| Exchange-traded/Listed | 290% |
| Other equity | 370% |

!!! warning "Correction (D1.27)"
    "Government-supported: 190%" was incorrectly listed as an Art. 155 category. Art. 155(2) has only three categories: (a) exchange-traded 290%, (b) PE diversified 190%, (c) all other 370%. No "government-supported" category exists in Art. 155.

**New Components:**
- `EquityCalculator` class (`src/rwa_calc/engine/equity/calculator.py`)
- `EquityLazyFrame` namespace (`lf.equity`) for fluent calculations
- `EquityExpr` namespace (`expr.equity`) for column-level operations
- `EquityResultBundle` for equity calculation results
- `crr_equity_rw.py` lookup tables

**Features:**
- Automatic approach determination based on IRB permissions
- Diversified portfolio treatment for private equity (190% vs 370%)
- Full audit trail generation
- Single exposure calculation convenience method

#### Pre/Post CRM Tracking for Guarantees
Enhanced guarantee processing with full tracking of exposure amounts before and after CRM application:
- `rwa_pre_crm`: RWA calculated on original exposure before guarantee
- `rwa_post_crm`: RWA calculated after guarantee substitution
- `guarantee_rwa_benefit`: Reduction in RWA from guarantee protection
- Supports both covered and uncovered portion tracking

### Changed
- Pipeline now includes equity calculator between CRM and aggregator
- `CRMAdjustedBundle` extended with `equity_exposures` field

## [0.1.11] - 2026-01-28

### Added
- Namespace: add exact fractional years calculation
- Config: add MCP server configuration

## [0.1.10] - 2026-01-28

### Added
- CCF: include interest in EAD calculations

## [0.1.8] - 2026-01-28

### Added
- Data: add script to generate sample data in parquet format
- Correlation: add SME adjustment with EUR/GBP conversion
- Orgs: make org_mappings optional in data loaders

### Fixed
- Config: update EUR to GBP exchange rate

## [0.1.7] - 2026-01-27

### Added
- Tests: add unit tests for API error handling and validation
- Protocols: update aggregation method with new bundles
- Loader: enhance data loading with validation checks
- BDD: add specifications for CRR provisions, risk weights, and supporting factors

### Changed
- Loans: update loan schema and documentation

## [0.1.6] - 2026-01-25

### Added
- Stats: implement backend detection for statistical functions
- Documentation: add detailed implementation plan and project roadmap

### Changed
- Stats: remove dual stats backend implementation
- Documentation: update optional dependencies and installation instructions

## [0.1.5] - 2026-01-25

### Added
- Counterparties: enhance counterparty schema and classification
- Documentation: add logo to documentation theme

### Changed
- CCF: remove unused CCF module and tests
- Contingents: remove ccf_category and update risk_type

### Performance
- Benchmark: update results with improved metrics

## [0.1.4] - 2026-01-25

### Added
- Deploy: add automated deployment script

### Performance
- Benchmark: transition to pure Polars expressions

## [0.1.3] - 2025-01-24

### Added

#### Documentation Code Linking
- Updated documentation to link code examples to actual source implementations
- Added `pymdownx.snippets` for embedding real code from source files
- Added `mkdocstrings` auto-generated API documentation
- New `docs/development/documentation-conventions.md` guide for contributors
- Source code references with GitHub line number links throughout docs

#### Mandatory `risk_type` Column for CCF Determination

The `risk_type` column is now the authoritative source for CCF (Credit Conversion Factor) determination across all facility inputs:

**New Columns:**
- `risk_type` (mandatory) - Off-balance sheet risk category: FR, MR, MLR, LR
- `ccf_modelled` (optional) - A-IRB modelled CCF estimate (0.0-1.5, Retail IRB can exceed 100%)
- `is_short_term_trade_lc` (optional) - CRR Art. 166(9) exception flag

**Risk Type Values (CRR Art. 111):**

| Code | SA CCF | F-IRB CCF | Description |
|------|--------|-----------|-------------|
| FR | 100% | 100% | Full risk - guarantees, credit substitutes |
| MR | 50% | 75% | Medium risk - NIFs, RUFs, committed undrawn |
| MLR | 20% | 75% | Medium-low risk - documentary credits, trade |
| LR | 0% | 0% | Low risk - unconditionally cancellable |

**F-IRB Rules:**
- CRR Art. 166(8): MR and MLR both become 75% CCF under F-IRB
- CRR Art. 166(9): Short-term trade LCs for goods movement retain 20% (set `is_short_term_trade_lc=True`)

**A-IRB Support:**
- When `ccf_modelled` is provided and approach is A-IRB, this value takes precedence

### Removed

#### `commitment_type` Column and Legacy CCF Functions

The following have been removed as `risk_type` is now the authoritative CCF source:

**Removed from schemas:**
- `commitment_type` column from FACILITY_SCHEMA and all intermediate schemas

**Removed from `crr_ccf.py`:**
- `lookup_ccf()` function
- `lookup_firb_ccf()` function
- `calculate_ead_off_balance_sheet()` function
- `create_ccf_type_mapping_df()` function

**Removed from `ccf.py`:**
- `calculate_single_ccf()` method
- `CCFResult` dataclass

**Migration:** Replace `commitment_type` with `risk_type`:
- `unconditionally_cancellable` → `LR` (low_risk)
- `committed_other` → `MR` (medium_risk) or `MLR` (medium_low_risk)

#### FX Conversion Support (14 new tests)

Multi-currency portfolio support with configurable FX conversion:

**FXConverter Module** (`src/rwa_calc/engine/fx_converter.py`)
- `convert_exposures()` - Converts drawn, undrawn, and nominal amounts
- `convert_collateral()` - Converts market and nominal values
- `convert_guarantees()` - Converts covered amounts
- `convert_provisions()` - Converts provision amounts
- Factory function `create_fx_converter()`

**Features:**
- Configurable target currency via `CalculationConfig.base_currency`
- Enable/disable via `CalculationConfig.apply_fx_conversion`
- Full audit trail: `original_currency`, `original_amount`, `fx_rate_applied`
- Graceful handling of missing FX rates (values unchanged, rate = null)
- Early pipeline integration (HierarchyResolver) for consistent threshold calculations

**Data Support:**
- New `FX_RATES_SCHEMA` in `src/rwa_calc/data/schemas.py`
- `fx_rates` field added to `RawDataBundle`
- `fx_rates_file` config in `DataSourceConfig`
- Test fixtures in `tests/fixtures/fx_rates/`

**Tests:**
- 14 unit tests covering all conversion scenarios
- Tests for exposure, collateral, guarantee, and provision conversion
- Multi-currency batch conversion tests
- Alternative base currency tests (EUR, USD)

#### Polars Namespace Extensions (8 namespaces, 139 new tests)

The calculator now provides comprehensive Polars namespace extensions for fluent, chainable calculations across all approaches:

**SA Namespace** (`lf.sa`, `expr.sa`)
- `SALazyFrame` namespace for Standardised Approach calculations
- Methods: `prepare_columns`, `apply_risk_weights`, `apply_residential_mortgage_rw`, `apply_cqs_based_rw`, `calculate_rwa`, `apply_supporting_factors`, `apply_all`
- UK deviation handling for institution CQS 2 (30% vs 50%)
- 29 unit tests

**IRB Namespace** (`lf.irb`, `expr.irb`)
- `IRBLazyFrame` namespace for IRB calculations
- Methods: `classify_approach`, `apply_firb_lgd`, `prepare_columns`, `apply_pd_floor`, `apply_lgd_floor`, `calculate_correlation`, `calculate_k`, `calculate_maturity_adjustment`, `calculate_rwa`, `calculate_expected_loss`, `apply_all_formulas`
- Expression methods: `floor_pd`, `floor_lgd`, `clip_maturity`
- 33 unit tests

**CRM Namespace** (`lf.crm`)
- `CRMLazyFrame` namespace for EAD waterfall processing
- Methods: `initialize_ead_waterfall`, `apply_collateral`, `apply_guarantees`, `apply_provisions`, `finalize_ead`, `apply_all_crm`
- SA vs IRB treatment differences handled automatically
- 20 unit tests

**Haircuts Namespace** (`lf.haircuts`)
- `HaircutsLazyFrame` namespace for collateral haircut calculations
- Methods: `classify_maturity_band`, `apply_collateral_haircuts`, `apply_fx_haircut`, `apply_maturity_mismatch`, `calculate_adjusted_value`, `apply_all_haircuts`
- CRR Article 224 supervisory haircuts
- 24 unit tests

**Slotting Namespace** (`lf.slotting`, `expr.slotting`)
- `SlottingLazyFrame` namespace for specialised lending
- Methods: `prepare_columns`, `apply_slotting_weights`, `calculate_rwa`, `apply_all`
- CRR vs Basel 3.1 risk weight differences
- HVCRE treatment
- 26 unit tests

**Hierarchy Namespace** (`lf.hierarchy`)
- `HierarchyLazyFrame` namespace for hierarchy resolution
- Methods: `resolve_ultimate_parent`, `calculate_hierarchy_depth`, `inherit_ratings`, `coalesce_ratings`, `calculate_lending_group_totals`, `add_lending_group_reference`, `add_collateral_ltv`
- Pure LazyFrame join-based traversal (no Python recursion)
- 13 unit tests

**Aggregator Namespace** (`lf.aggregator`)
- `AggregatorLazyFrame` namespace for result combination
- Methods: `combine_approach_results`, `apply_output_floor`, `calculate_floor_impact`, `generate_summary_by_class`, `generate_summary_by_approach`, `generate_supporting_factor_impact`
- Basel 3.1 output floor support
- 12 unit tests

**Audit Namespace** (`lf.audit`, `expr.audit`)
- `AuditLazyFrame` namespace for audit trail generation
- Methods: `build_sa_calculation`, `build_irb_calculation`, `build_slotting_calculation`, `build_crm_calculation`, `build_haircut_calculation`, `build_floor_calculation`
- `AuditExpr` namespace for column formatting: `format_currency`, `format_percent`, `format_ratio`, `format_bps`
- 15 unit tests

### Changed
- **All calculators** can now use namespace-based fluent APIs
- Improved code readability with chainable method calls
- Test count increased from 635 to 826 (139 namespace tests + 14 FX converter tests + 38 other tests)

## [0.1.2] - 2025-01-24

### Added

#### Interactive UI Console Command
- New `rwa-calc-ui` console script for starting the UI server when installed from PyPI
- `main()` function added to `server.py` for entry point

#### Documentation Improvements
- New `docs/user-guide/interactive-ui.md` - comprehensive UI guide with prerequisites, all three apps, troubleshooting
- Updated quickstart with "Choose Your Approach" section (UI vs Python API)
- Added Interactive UI to user guide navigation and recommendations
- Updated all server startup commands to show both PyPI and source installation methods

### Changed
- Installation instructions clarified for PyPI vs source installations
- UI documentation moved from Development section to User Guide for better discoverability

---

## [0.1.1] - 2025-01-22

### Added
- FX conversion support for multi-currency portfolios
- Polars namespace extensions (8 namespaces)
- Retail classification flag (`cp_is_managed_as_retail`)

---

## [0.1.0] - 2025-01-18

### Added

#### Core Framework
- Dual-framework support (CRR and Basel 3.1 configuration)
- Pipeline architecture with discrete processing stages
- Protocol-based component interfaces
- Immutable data contracts (bundles)

#### Data Loading
- Parquet file loader
- Schema validation
- Optional file handling
- Metadata tracking

#### Hierarchy Resolution
- Counterparty hierarchy resolution (up to 10 levels)
- Rating inheritance from parent
- Lending group aggregation
- LazyFrame-based join optimization

#### Classification
- All exposure classes supported
- Approach determination (SA/F-IRB/A-IRB/Slotting)
- SME identification
- Retail eligibility checking
- EAD calculation with CCFs

#### Standardised Approach
- Complete risk weight tables
- Sovereign, Institution, Corporate, Retail classes
- Real estate treatments
- Defaulted exposure handling

#### IRB Approach
- K formula implementation
- Asset correlation with SME adjustment
- Maturity adjustment
- PD and LGD floors
- Expected loss calculation
- 1.06 scaling factor (CRR)

#### Slotting Approach
- All specialised lending types
- Category-based risk weights
- HVCRE treatment
- Pre-operational project finance

#### Credit Risk Mitigation
- Financial collateral (comprehensive method)
- Supervisory haircuts
- Currency mismatch handling
- Guarantees (substitution approach)
- Maturity mismatch adjustment
- Provision allocation

#### Supporting Factors (CRR)
- SME supporting factor (tiered calculation)
- Infrastructure factor

#### Output
- Aggregated results
- Breakdown by approach/class/counterparty
- Export to Parquet/CSV/JSON
- Error accumulation and reporting

#### Configuration
- Factory methods (crr/basel_3_1)
- EUR/GBP rate configuration
- Configurable supporting factors
- PD floor configuration

#### Testing
- 468+ test cases
- Unit tests for all components
- Contract tests for interfaces
- Acceptance test framework
- Test fixtures generation

#### Documentation
- MkDocs with Material theme
- User guide for all audiences
- API reference
- Architecture documentation
- Development guide

### Technical
- Python 3.13+ support
- Polars LazyFrame optimization
- Pydantic validation
- Type hints throughout
- Ruff formatting/linting

## Version History

| Version | Date | Status |
|---------|------|--------|
| 0.1.55 | 2026-04-09 | Current |
| 0.1.54 | 2026-04-09 | Previous |
| 0.1.53 | 2026-04-08 | - |
| 0.1.52 | 2026-04-07 | - |
| 0.1.51 | 2026-04-06 | - |
| 0.1.50 | 2026-04-05 | - |
| 0.1.49 | 2026-04-01 | - |
| 0.1.48 | 2026-03-30 | - |
| 0.1.47 | 2026-03-29 | - |
| 0.1.46 | 2026-03-28 | - |
| 0.1.45 | 2026-03-28 | - |
| 0.1.44 | 2026-03-25 | - |
| 0.1.43 | 2026-03-24 | - |
| 0.1.42 | 2026-03-22 | - |
| 0.1.41 | 2026-03-22 | - |
| 0.1.40 | 2026-03-22 | - |
| 0.1.39 | 2026-03-21 | - |
| 0.1.38 | 2026-03-20 | - |
| 0.1.37 | 2026-03-17 | - |
| 0.1.36 | 2026-03-15 | - |
| 0.1.35 | 2026-03-11 | - |
| 0.1.34 | 2026-03-10 | - |
| 0.1.33 | 2026-03-09 | - |
| 0.1.32 | 2026-03-08 | - |
| 0.1.31 | 2026-03-07 | - |
| 0.1.30 | 2026-03-06 | - |
| 0.1.29 | 2026-02-28 | - |
| 0.1.28 | 2026-02-24 | - |
| 0.1.27 | 2026-02-22 | - |
| 0.1.26 | 2026-02-21 | - |
| 0.1.25 | 2026-02-20 | - |
| 0.1.24 | 2026-02-19 | - |
| 0.1.23 | 2026-02-17 | - |
| 0.1.22 | 2026-02-16 | - |
| 0.1.21 | 2026-02-16 | - |
| 0.1.20 | 2026-02-14 | - |
| 0.1.19 | 2026-02-11 | - |
| 0.1.18 | 2026-02-10 | - |
| 0.1.17 | 2026-02-10 | - |
| 0.1.16 | 2026-02-09 | - |
| 0.1.15 | 2026-02-08 | - |
| 0.1.14 | 2026-02-07 | - |
| 0.1.13 | 2026-02-07 | - |
| 0.1.12 | 2026-02-02 | - |
| 0.1.11 | 2026-01-28 | - |
| 0.1.10 | 2026-01-28 | - |
| 0.1.8  | 2026-01-28 | - |
| 0.1.7  | 2026-01-27 | - |
| 0.1.6  | 2026-01-25 | - |
| 0.1.5  | 2026-01-25 | - |
| 0.1.4  | 2026-01-25 | - |
| 0.1.3  | 2025-01-24 | - |
| 0.1.2  | 2025-01-24 | - |
| 0.1.1  | 2025-01-22 | - |
| 0.1.0  | 2025-01-18 | Initial |

## Migration Notes

### From Previous Versions

This is the initial release. No migration required.

### CRR to Basel 3.1

When transitioning calculations from CRR to Basel 3.1:

1. **Update configuration:**
   ```python
   # Before (CRR)
   config = CalculationConfig.crr(date(2026, 12, 31))

   # After (Basel 3.1)
   config = CalculationConfig.basel_3_1(date(2027, 1, 1))
   ```

2. **Review impacted exposures:**
   - SME exposures (factor removal)
   - Infrastructure exposures (factor removal)
   - Low-risk IRB portfolios (output floor)

3. **Update data requirements:**
   - LTV data for Basel 3.1 real estate weights
   - Transactor/revolver flags for QRRE

## Deprecation Notices

### CRR-Specific Features (End of 2026)

The following CRR-specific features will be removed from active use after December 2026:

- SME supporting factor
- Infrastructure supporting factor
- 1.06 scaling factor

These will remain available for historical calculations and comparison.

## Contributing

See [Development Guide](../development/index.md) for contribution guidelines.

## Support

For issues and feature requests, please use the project's issue tracker.
