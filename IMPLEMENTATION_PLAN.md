# Documentation Update Implementation Plan

Full audit of `docs/` vs `src/rwa_calc/` completed 2026-03-02. This plan covers all
discrepancies, outdated content, and missing documentation.

> **2026-03-02 update:** All Priority 1 items completed (1.1-1.6). All API reference docs now
> match source code: bundles, errors, protocols, domain enums, engine modules (calculators, CCF,
> CRM, comparison, FX, utils), configuration (CalculationConfig, PDFloors, LGDFloors,
> SupportingFactors, OutputFloorConfig, RetailThresholds, IRBPermissions, PolarsEngine).
>
> **2026-03-02 update (continued):** All Priority 2 items completed (2.1-2.5). All data model
> docs now match source code: intermediate schemas (hierarchy, classification, CRM columns),
> output schemas (SA/IRB/Slotting/Equity result schemas, CALCULATION_OUTPUT_SCHEMA, framework
> additions), input schemas (fixed Contingent, Counterparty, Facility, Loan, Equity schemas),
> validation functions (all 17 functions documented), regulatory tables (fixed CRR corporate
> CQS 3, HVCRE weights, slotting maturity differentiation; added Basel 3.1 SCRA, LTV bands,
> equity tables, haircut 5-band maturity, F-IRB LGD comparison).

---

## Priority 1 — Critical: API Reference Out of Sync with Source

These docs contain **wrong** information — field names, method signatures, and class
structures that no longer match the source code. Users following these docs will hit errors.

### 1.1 Update `docs/api/contracts.md` — Bundles are heavily outdated

**Source**: `src/rwa_calc/contracts/bundles.py`

| Bundle | Doc Fields | Source Fields | Gap |
|--------|-----------|--------------|-----|
| `RawDataBundle` | 10 fields (`org_mapping`, `lending_mapping`) | 14+ fields (`facility_mappings`, `org_mappings`, `lending_mappings`, `fx_rates`, `equity_exposures`, `specialised_lending`) | Field names wrong, 4+ fields missing |
| `ResolvedHierarchyBundle` | 4 fields (`counterparties`, `facilities`, `loans`, `exposures`) | `exposures`, `counterparty_lookup`, `lending_group_totals`, `collateral`, `guarantees`, `provisions`, `errors` | Completely different structure |
| `ClassifiedExposuresBundle` | 4 fields | 11 fields (adds `equity_exposures`, `collateral`, `guarantees`, `provisions`, `counterparty_lookup`, `classification_audit`, `classification_errors`) | 7 fields missing |
| `CRMAdjustedBundle` | 3 fields | 8 fields (adds `exposures`, `equity_exposures`, `crm_audit`, `collateral_allocation`, `crm_errors`) | 5 fields missing |
| `SAResultBundle` | `data` field | `results`, `calculation_audit`, `errors` | Wrong field names |
| `IRBResultBundle` | `data` field | `results`, `expected_loss`, `calculation_audit`, `errors` | Wrong field names, missing `expected_loss` |
| `SlottingResultBundle` | `data` field | `results`, `calculation_audit`, `errors` | Wrong field names |
| `AggregatedResultBundle` | 3 fields (`data`, `errors`, `warnings`) | 15+ fields (`results`, `sa_results`, `irb_results`, `slotting_results`, `equity_results`, `floor_impact`, `supporting_factor_impact`, `summary_by_class`, `summary_by_approach`, `pre_crm_summary`, `post_crm_detailed`, `post_crm_summary`, `el_summary`, `errors`) | Almost entirely wrong |

**Missing bundles not documented at all:**
- `CounterpartyLookup` — 4 fields: `counterparties`, `parent_mappings`, `ultimate_parent_mappings`, `rating_inheritance`
- `ComparisonBundle` — dual-framework comparison results
- `TransitionalScheduleBundle` — output floor transitional schedule
- `CapitalImpactBundle` — RWA delta decomposition
- `ELPortfolioSummary` — expected loss T2 credit cap

**Missing helper functions:**
- `create_empty_raw_data_bundle()`
- `create_empty_counterparty_lookup()`
- `create_empty_resolved_hierarchy_bundle()`
- `create_empty_classified_bundle()`
- `create_empty_crm_adjusted_bundle()`

**Steps:**
- [x] Read current `contracts/bundles.py` and update every bundle definition to match source
- [x] Add documentation for all 5 missing bundles
- [x] Add documentation for `create_empty_*()` helper functions
- [x] Verify all type annotations match source (`pl.LazyFrame | None`, `list[CalculationError]`, etc.)

### 1.2 Update `docs/api/contracts.md` — Error handling outdated

**Source**: `src/rwa_calc/contracts/errors.py`

Current docs show a simplistic `CalculationError` with 4 fields (`exposure_id`, `stage`, `message`, `details`). Source has:

- `CalculationError` (frozen dataclass): `code`, `message`, `severity`, `category`, `exposure_reference`, `counterparty_reference`, `regulatory_reference`, `field_name`, `expected_value`, `actual_value`
- `LazyFrameResult` class — combines LazyFrame with accumulated errors (properties: `has_errors`, `has_critical_errors`, `warnings`, `critical_errors`; methods: `errors_by_category()`, `errors_by_exposure()`, `add_error()`, `merge()`)
- Error code constants: `DQ001`-`DQ006`, `HIE001`-`HIE003`, `CLS001`-`CLS003`, `CRM001`-`CRM005`, `IRB001`-`IRB005`, `SA001`-`SA003`, `CFG001`-`CFG002`
- Factory functions: `missing_field_error()`, `invalid_value_error()`, `business_rule_error()`, `hierarchy_error()`, `crm_warning()`

**Steps:**
- [x] Rewrite `CalculationError` section with all 10+ fields
- [x] Add `LazyFrameResult` documentation with properties and methods
- [x] Document all error code constants organised by domain
- [x] Document factory functions
- [x] Remove `CalculationWarning` (does not exist in source — severity is a field on `CalculationError`)

### 1.3 Update `docs/api/contracts.md` — Protocols outdated

**Source**: `src/rwa_calc/contracts/protocols.py`

Current docs show simplified protocol signatures. Source has many more methods per protocol and additional protocols:

**Missing methods on existing protocols:**
- `SACalculatorProtocol`: missing `get_sa_result_bundle()`, `calculate_unified()`, `calculate_branch()`
- `IRBCalculatorProtocol`: missing `get_irb_result_bundle()`, `calculate_unified()`, `calculate_branch()`, `calculate_expected_loss()`
- `SlottingCalculatorProtocol`: missing `get_slotting_result_bundle()`, `calculate_unified()`, `calculate_branch()`
- `OutputAggregatorProtocol`: missing `aggregate_with_audit()`, `apply_output_floor()`
- `CRMProcessorProtocol`: shows `process()` but source has `apply_crm()` and `get_crm_adjusted_bundle()`

**Missing protocols entirely:**
- `ComparisonRunnerProtocol` — `compare()` method
- `CapitalImpactAnalyzerProtocol` — `analyze()` method
- `PipelineProtocol` — `run()`, `run_with_data()` methods
- `SchemaValidatorProtocol`
- `DataQualityCheckerProtocol`
- `ResultExporterProtocol`

**Steps:**
- [x] Update all existing protocol signatures to match source
- [x] Add all missing protocols
- [x] Fix `CRMProcessorProtocol.process()` → `apply_crm()` / `get_crm_adjusted_bundle()`

### 1.4 Update `docs/api/engine.md` — Method signatures outdated

**Status: COMPLETED** (2026-03-02)

All engine module documentation rewritten to match source code:
- [x] CCF section rewritten: `CCFCalculator.apply_ccf()`, `sa_ccf_expression()`, `drawn_for_ead()`, `on_balance_ead()`, `create_ccf_calculator()`
- [x] CRM processor: `apply_crm()`, `get_crm_adjusted_bundle()`, `get_crm_unified_bundle()`, `apply_collateral()`, `apply_guarantees()`, `resolve_provisions()`
- [x] SA calculator: `calculate(data: CRMAdjustedBundle)`, `get_sa_result_bundle()`, `calculate_unified()`, `calculate_branch()`, `calculate_single_exposure()`
- [x] IRB calculator: all methods including `calculate_expected_loss()` and `calculate_single_exposure()`
- [x] Slotting calculator: all methods including maturity-band differentiation in weight table
- [x] Equity calculator: verified and updated
- [x] Aggregator: `aggregate()`, `aggregate_with_audit()`, `apply_output_floor()` with T2 credit cap
- [x] Loader: updated to show `ParquetLoader.__init__(base_path, config, enforce_schemas)`, `CSVLoader`, `DataSourceConfig`, helper functions
- [x] Added comparison module section: `DualFrameworkRunner`, `CapitalImpactAnalyzer`, `TransitionalScheduleRunner`
- [x] Updated FX converter: signatures corrected to use `config: CalculationConfig`, added `convert_equity_exposures()`
- [x] Added engine utilities section: `has_rows()`, `has_required_columns()`

### 1.5 Update `docs/api/configuration.md` — Missing config fields and classes

**Status: COMPLETED** (2026-03-02)

All configuration documentation rewritten to match source code:
- [x] `CalculationConfig`: added all 13 fields (was 8), updated factory methods (`.crr()` now takes `irb_permissions`, `.basel_3_1()` auto-configures output floor)
- [x] `PDFloors`: fixed to show `corporate_sme` field, corrected `get_floor()` signature with `is_qrre_transactor` param
- [x] `LGDFloors`: fixed field names (`unsecured` not `unsecured_senior`, `commercial_real_estate` not `cre`, etc.) and corrected PRA values
- [x] `SupportingFactors`: fixed field names (`sme_factor_under_threshold`, `enabled`, etc.), added `basel_3_1()` factory
- [x] `OutputFloorConfig`: rewritten with `enabled`, `transitional_start_date`, `transitional_floor_schedule`, `get_floor_percentage(calculation_date)` method, `.crr()` / `.basel_3_1()` factories
- [x] Added `RetailThresholds` class with `.crr()` / `.basel_3_1()` factory methods
- [x] Added `IRBPermissions` class with all 5 factory methods and regulatory constraints documentation
- [x] Added `PolarsEngine` type alias
- [x] Added `is_crr`, `is_basel_3_1` properties and `get_output_floor_percentage()` method
- [x] Updated usage examples for new API signatures

### 1.6 Update `docs/api/domain.md` — Missing enums

**Source**: `src/rwa_calc/domain/enums.py`

Documented: `RegulatoryFramework`, `ExposureClass`, `ApproachType`, `CQS`, `ErrorSeverity`, `ErrorCategory`

**Missing enums:**
- `CollateralType` — `FINANCIAL`, `IMMOVABLE`, `RECEIVABLES`, `OTHER_PHYSICAL`, `OTHER`
- `IFRSStage` (IntEnum) — `STAGE_1`, `STAGE_2`, `STAGE_3`
- `SlottingCategory` — `STRONG`, `GOOD`, `SATISFACTORY`, `WEAK`, `DEFAULT`
- `SpecialisedLendingType` — `PROJECT_FINANCE`, `OBJECT_FINANCE`, `COMMODITIES_FINANCE`, `IPRE`, `HVCRE`
- `PropertyType` — `RESIDENTIAL`, `COMMERCIAL`, `ADC`
- `Seniority` — `SENIOR`, `SUBORDINATED`
- `SCRAGrade` — `A`, `B`, `C`

**Steps:**
- [x] Add all 7 missing enums with members and descriptions
- [x] Verify existing enum members are complete (corrected to StrEnum, fixed member values, removed non-existent enums: GuarantorType, ProvisionType, FacilityType, CounterpartyType)

---

## Priority 2 — High: Data Model Schemas Use Wrong Column Names

**Status: COMPLETED** (2026-03-02)

All data model documentation rewritten to match source code:

### 2.1 Fix `docs/data-model/intermediate-schemas.md`

- [x] Rewrote entire file — all `_id` suffixes replaced with `_reference`
- [x] Added Raw Exposure Schema section (exposure unification from loans/contingents/facilities)
- [x] Resolved Hierarchy Schema: added all 14+ hierarchy columns (counterparty hierarchy, facility hierarchy, rating inheritance, lending group)
- [x] Classified Exposure Schema: corrected to show `approach_applied`/`approach_permitted` (not `approach_type`), added `exposure_class_reason`, `approach_selection_reason`, `rating_agency`, `rating_value`, `is_retail_eligible`
- [x] CRM Adjusted Schema: rewritten with full EAD waterfall columns (CCF, collateral, guarantee, LGD), plus Pre/Post CRM reporting columns
- [x] Specialised Lending Schema: corrected `sl_type` (not `lending_type`), added `remaining_maturity_years`
- [x] Updated all transformation examples with correct column names

### 2.2 Fix `docs/data-model/output-schemas.md`

- [x] Rewrote entire file — all `_id` suffixes replaced with `_reference`
- [x] SA Result Schema: rewritten with `sa_cqs`, `sa_base_risk_weight`, `sa_rw_adjustment`, `sa_final_risk_weight`, `sa_rw_regulatory_ref`, `sa_rwa`
- [x] IRB Result Schema: rewritten with full formula breakdown (`irb_pd_*`, `irb_lgd_*`, `irb_correlation_r`, `irb_capital_k`, `irb_maturity_adj_b`, `irb_scaling_factor`, `irb_risk_weight`, `irb_rwa`, `irb_expected_loss`)
- [x] Slotting Result Schema: corrected columns (`sl_base_risk_weight`, `sl_maturity_adjusted_rw`, `sl_final_risk_weight`, `sl_rwa`)
- [x] Added full Calculation Output Schema (~100 columns) with all sections
- [x] Added CRR and Basel 3.1 framework-specific output additions
- [x] Rewrote AggregatedResultBundle documentation (15 fields including all summaries and EL)
- [x] Added ELPortfolioSummary documentation with T2 credit cap
- [x] Added ComparisonBundle, TransitionalScheduleBundle, CapitalImpactBundle

### 2.3 Verify `docs/data-model/input-schemas.md`

- [x] Added missing `scra_grade` and `is_investment_grade` to Counterparty Schema (Basel 3.1)
- [x] Added missing `is_qrre_transactor` to Facility Schema
- [x] Removed non-existent `contract_type` and `ccf_category` from Contingent Schema
- [x] Added missing `bs_type` column to Contingent Schema
- [x] Fixed Loan example (removed `risk_type`/`ccf_modelled` which don't apply to loans, added `interest`/`is_buy_to_let`)
- [x] Added 5 missing equity types (`central_bank`, `exchange_traded`, `government_supported`, `private_equity_diversified`, `other`)
- [x] Added missing `hvcre` to valid `sl_type` values

### 2.4 Update `docs/data-model/data-validation.md`

- [x] Added 4 missing bundle validators: `validate_resolved_hierarchy_bundle()`, `validate_classified_bundle()`, `validate_crm_adjusted_bundle()` with signatures and examples
- [x] Added `validate_risk_type()` with valid codes documentation
- [x] Added `validate_ccf_modelled()` with range [0, 1.5] and null handling
- [x] Added `normalize_risk_type()` with code-to-value mapping table
- [x] Added `validate_column_values()` with materialisation note
- [x] Added `validate_bundle_values()` with `COLUMN_VALUE_CONSTRAINTS` table (11 tables, all constrained columns)

### 2.5 Update `docs/data-model/regulatory-tables.md`

- [x] **Fixed CRR corporate CQS 3**: was 75% (wrong), corrected to 100% per CRR Art. 122
- [x] **Fixed CRR slotting**: Strong/Good are NOT both 70% — Strong=70%, Good=90% at ≥2.5yr; added maturity differentiation tables
- [x] **Fixed HVCRE**: CRR HVCRE has its own higher weight table (95/120/140 at ≥2.5yr), NOT same as standard SL
- [x] Added Basel 3.1 SCRA weights (A=40%, B=75%, C=150%)
- [x] Added Basel 3.1 corporate additions (investment grade 65%, SME 85%, subordinated 150%)
- [x] Added Basel 3.1 supervisory LGD table with changes from CRR
- [x] Added Basel 3.1 collateral haircuts with 5 maturity bands (vs CRR's 3)
- [x] Added equity risk weight tables (SA Art. 133 and IRB Simple Art. 155)
- [x] Added CRR residential mortgage split treatment and commercial RE details
- [x] Added Basel 3.1 commercial RE (general + income-producing + ADC)
- [x] Added overcollateralisation requirements table
- [x] Added API function examples with correct signatures

### 2.5 Update `docs/data-model/regulatory-tables.md`

Verify against source reference tables in `data/tables/`:
- `crr_risk_weights.py` — CRR SA risk weights, LTV bands
- `b31_risk_weights.py` — Basel 3.1 SA risk weights, SCRA weights, revised LTV bands
- `crr_firb_lgd.py` — F-IRB supervisory LGD
- `crr_haircuts.py` — Collateral haircut tables (CRR and Basel 3.1)
- `crr_slotting.py` — Slotting RW by category/type/maturity
- `crr_equity_rw.py` — Equity RW by type

**Steps:**
- [ ] Verify sovereign/institution/corporate risk weight tables match source for both frameworks
- [ ] Verify residential/commercial/ADC LTV band tables match source
- [ ] Add Basel 3.1 specific tables: SCRA weights, investment grade, SME corporate, subordinated debt
- [ ] Add F-IRB supervisory LGD table
- [ ] Add collateral haircut tables (both frameworks, verify maturity bands match)
- [ ] Add equity risk weight tables (SA Art. 133 and IRB Simple Art. 155)
- [ ] Add slotting RW tables (by category, HVCRE/non-HVCRE, maturity)

---

## Priority 3 — Medium: Missing Feature Documentation

### 3.1 Add COREP Reporting documentation

**Source**: `src/rwa_calc/reporting/corep/generator.py` and `templates.py`

The COREP reporting module is entirely undocumented. It generates:
- **C 07.00** — SA credit risk template
- **C 08.01** — IRB totals template
- **C 08.02** — IRB PD grade bands template

**Steps:**
- [ ] Create `docs/features/corep-reporting.md` — user-facing guide
  - Overview of COREP credit risk templates
  - Template structure (rows = exposure classes, columns = risk parameters)
  - How to generate templates from calculation results
  - Export to Excel
  - Regulatory references (EU 2021/451, CRR Art. 112, Art. 147)
- [ ] Add COREP section to `docs/api/engine.md` or create `docs/api/reporting.md`
  - `COREPGenerator` class and methods
  - `COREPTemplateBundle` output structure
  - `COREPRow` template definitions
- [ ] Update `mkdocs.yml` nav to include new pages
- [ ] Update `docs/features/index.md` feature matrix to include COREP reporting

### 3.2 Add Comparison & Impact Analysis documentation

**Source**: `src/rwa_calc/engine/comparison.py`

Three classes for dual-framework analysis are undocumented:

- **`DualFrameworkRunner`** (M3.1): Runs CRR and Basel 3.1 side-by-side, joins on exposure_reference
- **`CapitalImpactAnalyzer`** (M3.2): Decomposes RWA deltas into drivers (scaling, supporting factors, floor, methodology)
- **`TransitionalScheduleRunner`** (M3.3): Models year-by-year output floor from 2027-2032

**Steps:**
- [ ] Create `docs/features/comparison.md` — user-facing guide
  - When and why to use dual-framework comparison
  - How to run comparisons
  - Understanding impact analysis output
  - Transitional schedule modelling
- [ ] Add comparison module to `docs/api/engine.md`
  - `DualFrameworkRunner.compare()` API
  - `CapitalImpactAnalyzer.analyze()` API
  - `TransitionalScheduleRunner.run()` API
  - Output bundles: `ComparisonBundle`, `CapitalImpactBundle`, `TransitionalScheduleBundle`
- [ ] Update `docs/features/index.md` to list comparison capabilities

### 3.3 Add FX Conversion documentation

**Source**: `src/rwa_calc/engine/fx_converter.py`

The FX converter is mentioned in methodology docs but has no dedicated API documentation.

**Steps:**
- [ ] Add `FXConverter` section to `docs/api/engine.md`
  - `convert_exposures()`, `convert_collateral()`, `convert_guarantees()`, `convert_provisions()`, `convert_equity_exposures()`
  - Audit trail columns (`original_currency`, `original_amount`, `fx_rate_applied`)
- [ ] Verify `docs/user-guide/methodology/fx-conversion.md` references correct API

### 3.4 Document `api/` subpackage modules

**Source**: `src/rwa_calc/api/`

Several API modules lack documentation:
- `api/export.py` — Result exporters (Parquet/CSV/Excel)
- `api/results_cache.py` — `ResultsCache` for Parquet caching
- `api/formatters.py` — `ResultFormatter` for response formatting
- `api/validation.py` — `DataPathValidator`
- `api/errors.py` — API-level error handling

**Steps:**
- [ ] Add export section to `docs/api/service.md` (or create separate page)
- [ ] Document `ResultsCache` — caching behaviour, cache directory, invalidation
- [ ] Document `DataPathValidator` and data directory structure expectations
- [ ] Document `ResultFormatter` for custom formatting

---

## Priority 4 — Low: User Guide & Architecture Accuracy Check

### 4.1 Review User Guide Methodology pages against source

These pages are substantial but may reference outdated APIs or have minor inaccuracies:

- [ ] `docs/user-guide/methodology/standardised-approach.md` (394 lines) — verify risk weight tables, formulas, and code examples match `engine/sa/`
- [ ] `docs/user-guide/methodology/irb-approach.md` (497 lines) — verify IRB formula, stats backend, PD/LGD floors match `engine/irb/`
- [ ] `docs/user-guide/methodology/crm.md` (599 lines) — verify CRM pipeline order, provision logic, overcollateralisation match `engine/crm/`
- [ ] `docs/user-guide/methodology/specialised-lending.md` (293 lines) — verify slotting categories and RWs match `engine/slotting/`
- [ ] `docs/user-guide/methodology/equity.md` (80 lines) — verify equity RWs match `engine/equity/`
- [ ] `docs/user-guide/methodology/supporting-factors.md` (331 lines) — verify factors match `engine/sa/supporting_factors.py`
- [ ] `docs/user-guide/methodology/fx-conversion.md` (95 lines) — verify FX conversion details

### 4.2 Review Architecture pages for accuracy

- [ ] `docs/architecture/components.md` (748 lines) — verify component descriptions, namespace table, method signatures
- [ ] `docs/architecture/pipeline.md` (503 lines) — verify pipeline stages and code snippets
- [ ] `docs/architecture/data-flow.md` (471 lines) — verify data transformation descriptions
- [ ] `docs/architecture/pipeline-collect-barriers.md` (121 lines) — verify collect barrier strategy matches current implementation (single CRM collect, `pl.collect_all` for branches)

### 4.3 Review User Guide Exposure Classes

- [ ] `docs/user-guide/exposure-classes/central-govt-central-bank.md` (220 lines)
- [ ] `docs/user-guide/exposure-classes/institution.md` (232 lines)
- [ ] `docs/user-guide/exposure-classes/corporate.md` (284 lines)
- [ ] `docs/user-guide/exposure-classes/retail.md` (393 lines)
- [ ] `docs/user-guide/exposure-classes/other.md` (358 lines)

Verify entity type mappings, risk weights, and classification criteria match `classifier.py` and `data/schemas.py`.

### 4.4 Review User Guide Regulatory Framework pages

- [ ] `docs/user-guide/regulatory/crr.md` (285 lines) — verify against CRR config
- [ ] `docs/user-guide/regulatory/basel31.md` (336 lines) — verify against Basel 3.1 config
- [ ] `docs/user-guide/regulatory/comparison.md` (407 lines) — verify comparison details

### 4.5 Review Development pages

- [ ] `docs/development/testing.md` (536 lines) — verify test counts, fixture paths, markers
- [ ] `docs/development/extending.md` (585 lines) — verify extension patterns match current architecture
- [ ] `docs/development/workbooks.md` (275 lines) — verify Marimo app references match `ui/marimo/`
- [ ] `docs/development/benchmarks.md` (390 lines) — verify benchmark configuration
- [ ] `docs/development/code-style.md` (436 lines) — verify against `pyproject.toml` ruff config

---

## Priority 5 — Housekeeping: Specifications & Navigation

### 5.1 Audit Specifications section against source

**Status: PARTIALLY COMPLETED** (2026-03-02)

`docs/specifications/` was found to be a stale copy of `specs/` (the canonical source).
11 of 20 files had diverged, some with factual errors. All 11 files synced from `specs/`:

- [x] Synced all 11 stale `docs/specifications/` files to match `specs/` (canonical)
  - Fixed wrong CRR slotting weights, wrong Basel 3.1 correlation multiplier naming
  - Updated milestones, test counts, and implementation statuses throughout

**Remaining work** — verify `specs/` files themselves against source code (not urgent since
`specs/` was already maintained, but minor internal inconsistencies were noted):

- [ ] `specifications/crr/sa-risk-weights.md` — verify against `data/tables/crr_risk_weights.py`
- [ ] `specifications/crr/supporting-factors.md` — verify against `engine/sa/supporting_factors.py`
- [ ] `specifications/crr/firb-calculation.md` — verify against `engine/irb/formulas.py`
- [ ] `specifications/crr/airb-calculation.md` — verify against `engine/irb/calculator.py`
- [ ] `specifications/crr/credit-conversion-factors.md` — verify against `engine/ccf.py`
- [ ] `specifications/crr/credit-risk-mitigation.md` — verify against `engine/crm/`
- [ ] `specifications/crr/slotting-approach.md` — verify against `engine/slotting/`
- [ ] `specifications/crr/provisions.md` — verify against provision logic in CRM
- [ ] `specifications/basel31/framework-differences.md` — verify against implementation
- [ ] `specifications/common/hierarchy-classification.md` — verify against `engine/hierarchy.py` and `engine/classifier.py`
- [ ] Review remaining project specs for accuracy against current code

**Internal inconsistencies noted in `specs/`:**
- Acceptance test group numbering: `index.md` lists groups A-H but compliance matrix has A, C-I (missing B, adding I)
- Provisions test count: `crr/provisions.md` lists CRR-G=17 but compliance matrix lists CRR-G=7

### 5.2 Update `mkdocs.yml` navigation

- [ ] Add COREP reporting page to Features section
- [ ] Add Comparison & Impact Analysis page to Features section
- [ ] Add Reporting API page if created separately
- [ ] Verify all existing nav entries still point to valid files

### 5.3 Update `docs/index.md` homepage

- [ ] Verify feature matrix matches current implementation
- [ ] Add COREP reporting to feature list
- [ ] Add comparison/impact analysis to feature list
- [ ] Verify technology stack list is current

### 5.4 Update `docs/appendix/changelog.md`

- [ ] Add entry for documentation overhaul
- [ ] Verify recent changelog entries are accurate

---

## Execution Order

1. **Priority 1** (API Reference): Fix first — these cause immediate user confusion
   - Start with contracts (1.1-1.3) as they define types used everywhere
   - Then engine (1.4), configuration (1.5), domain (1.6)
2. **Priority 2** (Data Model): Fix column names and schema accuracy
3. **Priority 3** (Missing Features): Add COREP, comparison, FX converter docs
4. **Priority 4** (User Guide): Review and fix methodology/architecture accuracy
5. **Priority 5** (Housekeeping): Audit specs, update nav, homepage, changelog

## Estimated Scope

- ~15 files need significant rewrites (Priority 1-2)
- ~5 new files need creation (Priority 3)
- ~25 files need review and minor corrections (Priority 4-5)
- Total: ~45 documentation files affected
