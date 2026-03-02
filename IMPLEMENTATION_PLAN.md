# Documentation Update Implementation Plan

Full audit of `docs/` vs `src/rwa_calc/` completed 2026-03-02. This plan covers all
discrepancies, outdated content, and missing documentation.

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
- [ ] Read current `contracts/bundles.py` and update every bundle definition to match source
- [ ] Add documentation for all 5 missing bundles
- [ ] Add documentation for `create_empty_*()` helper functions
- [ ] Verify all type annotations match source (`pl.LazyFrame | None`, `list[CalculationError]`, etc.)

### 1.2 Update `docs/api/contracts.md` — Error handling outdated

**Source**: `src/rwa_calc/contracts/errors.py`

Current docs show a simplistic `CalculationError` with 4 fields (`exposure_id`, `stage`, `message`, `details`). Source has:

- `CalculationError` (frozen dataclass): `code`, `message`, `severity`, `category`, `exposure_reference`, `counterparty_reference`, `regulatory_reference`, `field_name`, `expected_value`, `actual_value`
- `LazyFrameResult` class — combines LazyFrame with accumulated errors (properties: `has_errors`, `has_critical_errors`, `warnings`, `critical_errors`; methods: `errors_by_category()`, `errors_by_exposure()`, `add_error()`, `merge()`)
- Error code constants: `DQ001`-`DQ006`, `HIE001`-`HIE003`, `CLS001`-`CLS003`, `CRM001`-`CRM005`, `IRB001`-`IRB005`, `SA001`-`SA003`, `CFG001`-`CFG002`
- Factory functions: `missing_field_error()`, `invalid_value_error()`, `business_rule_error()`, `hierarchy_error()`, `crm_warning()`

**Steps:**
- [ ] Rewrite `CalculationError` section with all 10+ fields
- [ ] Add `LazyFrameResult` documentation with properties and methods
- [ ] Document all error code constants organised by domain
- [ ] Document factory functions
- [ ] Remove `CalculationWarning` (does not exist in source — severity is a field on `CalculationError`)

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
- [ ] Update all existing protocol signatures to match source
- [ ] Add all missing protocols
- [ ] Fix `CRMProcessorProtocol.process()` → `apply_crm()` / `get_crm_adjusted_bundle()`

### 1.4 Update `docs/api/engine.md` — Method signatures outdated

**Source**: `src/rwa_calc/engine/`

| Component | Doc Signature | Source Signature | Issue |
|-----------|--------------|-----------------|-------|
| `CCFCalculator` | `get_ccf(item_type, is_unconditionally_cancellable, ...)` | `sa_ccf_expression()`, `CCFCalculator` class, `drawn_for_ead()`, `on_balance_ead()` | Completely different API |
| `CRMProcessor` | `process(classified, config) → CRMAdjustedBundle` | `apply_crm(data, config) → LazyFrameResult`, `get_crm_adjusted_bundle(data, config) → CRMAdjustedBundle` | Wrong method name and signature |
| `SACalculator` | `calculate(exposures: LazyFrame, config)` | `calculate(data: CRMAdjustedBundle, config)`, plus `get_sa_result_bundle()`, `calculate_unified()`, `calculate_branch()` | Wrong input type, missing methods |
| `IRBCalculator` | (need to verify) | `calculate(data: CRMAdjustedBundle, config)`, `get_irb_result_bundle()`, `calculate_unified()`, `calculate_branch()`, `calculate_expected_loss()` | Likely same issues |
| `SlottingCalculator` | (need to verify) | Similar pattern to SA/IRB | Likely same issues |
| `EquityCalculator` | (need to verify) | `calculate(data, config)`, `get_equity_result_bundle()` | Likely same issues |
| `OutputAggregator` | (need to verify) | `aggregate()`, `aggregate_with_audit()`, `apply_output_floor()` | Likely same issues |

**Missing engine modules not documented:**
- `engine/comparison.py` — `DualFrameworkRunner`, `CapitalImpactAnalyzer`, `TransitionalScheduleRunner`
- `engine/fx_converter.py` — `FXConverter` class with `convert_exposures()`, `convert_collateral()`, etc.
- `engine/utils.py` — `has_rows()`, `has_required_columns()`

**Steps:**
- [ ] Update CCF section with actual API (`sa_ccf_expression()`, `CCFCalculator`, helper functions)
- [ ] Update CRM processor signatures (`apply_crm`, `get_crm_adjusted_bundle`)
- [ ] Update SA/IRB/Slotting/Equity calculator signatures with all methods
- [ ] Update Aggregator with `aggregate_with_audit()` and `apply_output_floor()`
- [ ] Add `comparison.py` section (DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner)
- [ ] Add `fx_converter.py` section
- [ ] Add `utils.py` section

### 1.5 Update `docs/api/configuration.md` — Missing config fields and classes

**Source**: `src/rwa_calc/contracts/config.py`

**Missing `CalculationConfig` fields:**
- `base_currency` — reporting currency
- `apply_fx_conversion` — FX conversion toggle
- `retail_thresholds` — `RetailThresholds` object
- `irb_permissions` — `IRBPermissions` object
- `collect_engine` — Polars engine selection (`PolarsEngine` type)

**Missing configuration classes:**
- `RetailThresholds` — `.crr()` (EUR 1m) / `.basel_3_1()` (GBP 880k) factory methods
- `IRBPermissions` — `is_permitted()`, `get_permitted_approaches()`, `.sa_only()`, `.full_irb()`, `.firb_only()`, `.airb_only()`, `.retail_airb_corporate_firb()`
- `PolarsEngine` type alias — `Literal["cpu", "gpu", "streaming"]`

**Steps:**
- [ ] Add all missing `CalculationConfig` fields
- [ ] Add `RetailThresholds` class with factory methods
- [ ] Add `IRBPermissions` class with all factory methods
- [ ] Add `PolarsEngine` type alias documentation
- [ ] Verify `PDFloors`, `LGDFloors`, `SupportingFactors`, `OutputFloorConfig` are complete and accurate

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
- [ ] Add all 7 missing enums with members and descriptions
- [ ] Verify existing enum members are complete

---

## Priority 2 — High: Data Model Schemas Use Wrong Column Names

### 2.1 Fix `docs/data-model/intermediate-schemas.md` — Column names don't match source

The intermediate schema docs use `exposure_id`, `counterparty_id`, `facility_id`, `loan_id`.
Source code consistently uses `exposure_reference`, `counterparty_reference`, `facility_reference`, `loan_reference`.

Also uses `ultimate_parent_id` vs source `ultimate_parent_reference`, `parent_chain` (doesn't exist), `hierarchy_level` vs `hierarchy_depth`, `inherited_rating` (doesn't exist as column), `group_total_exposure` vs different naming, `lending_group_id` (wrong).

**Steps:**
- [ ] Cross-reference every column name against actual pipeline output columns
- [ ] Update Resolved Hierarchy Schema with correct column names from `hierarchy.py`
- [ ] Update Classified Exposure Schema with correct columns from `classifier.py`
- [ ] Add CRM intermediate schema (columns added by `crm/processor.py`)
- [ ] Document the classification output columns (24 columns added per source)

### 2.2 Fix `docs/data-model/output-schemas.md` — Column names don't match source

Same `_id` vs `_reference` issue. Also:
- SA schema likely missing columns (e.g., `sa_risk_weight` prefix convention)
- IRB schema may have wrong column names for formulas output
- Slotting and Equity schemas need verification
- Aggregated output schema needs to match `AggregatedResultBundle`

**Steps:**
- [ ] Cross-reference SA output columns against `engine/sa/namespace.py` and `engine/sa/calculator.py`
- [ ] Cross-reference IRB output columns against `engine/irb/namespace.py` and `engine/irb/calculator.py`
- [ ] Cross-reference Slotting output columns against `engine/slotting/namespace.py`
- [ ] Cross-reference Equity output columns against `engine/equity/namespace.py`
- [ ] Add aggregated output schema matching `AggregatedResultBundle`
- [ ] Document EL summary output columns

### 2.3 Verify `docs/data-model/input-schemas.md` against `data/schemas.py`

Input schemas doc is substantial (807 lines) but needs column-by-column verification against `FACILITY_SCHEMA`, `LOAN_SCHEMA`, `CONTINGENTS_SCHEMA`, `COUNTERPARTY_SCHEMA`, `COLLATERAL_SCHEMA`, etc. in source.

**Steps:**
- [ ] Verify each schema table column-by-column against source `data/schemas.py`
- [ ] Verify `COLUMN_VALUE_CONSTRAINTS` are documented (valid values per categorical column)
- [ ] Check `SPECIALISED_LENDING_SCHEMA` and `EQUITY_EXPOSURE_SCHEMA` are documented
- [ ] Ensure `FX_RATES_SCHEMA` is documented
- [ ] Verify entity type list matches `VALID_ENTITY_TYPES` in source

### 2.4 Update `docs/data-model/data-validation.md`

Docs reference `validate_schema()` — need to verify all validation functions are documented:

**Source functions to check against docs:**
- `validate_schema()`, `validate_required_columns()`, `validate_schema_to_errors()`
- `validate_raw_data_bundle()`, `validate_resolved_hierarchy_bundle()`, `validate_classified_bundle()`, `validate_crm_adjusted_bundle()`
- `validate_non_negative_amounts()`, `validate_pd_range()`, `validate_lgd_range()`
- `validate_risk_type()`, `validate_ccf_modelled()`
- `normalize_risk_type()`, `validate_column_values()`, `validate_bundle_values()`
- `COLUMN_VALUE_CONSTRAINTS` dict

**Steps:**
- [ ] Verify all validation functions from `contracts/validation.py` are documented
- [ ] Document `validate_bundle_values()` and `COLUMN_VALUE_CONSTRAINTS`
- [ ] Document `normalize_risk_type()` and related constants (`VALID_RISK_TYPE_CODES`, `RISK_TYPE_CODE_TO_VALUE`)

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

24 specification files exist. These were written as design specs and may not reflect the final implementation:

**CRR specs (8 files):**
- [ ] `specifications/crr/sa-risk-weights.md` — verify against `data/tables/crr_risk_weights.py`
- [ ] `specifications/crr/supporting-factors.md` — verify against `engine/sa/supporting_factors.py`
- [ ] `specifications/crr/firb-calculation.md` — verify against `engine/irb/formulas.py`
- [ ] `specifications/crr/airb-calculation.md` — verify against `engine/irb/calculator.py`
- [ ] `specifications/crr/credit-conversion-factors.md` — verify against `engine/ccf.py`
- [ ] `specifications/crr/credit-risk-mitigation.md` — verify against `engine/crm/`
- [ ] `specifications/crr/slotting-approach.md` — verify against `engine/slotting/`
- [ ] `specifications/crr/provisions.md` — verify against provision logic in CRM

**Basel 3.1 specs (1 file):**
- [ ] `specifications/basel31/framework-differences.md` — verify against implementation

**Common specs (1 file):**
- [ ] `specifications/common/hierarchy-classification.md` — verify against `engine/hierarchy.py` and `engine/classifier.py`

**Project specs (14 files):**
- [ ] Review `overview.md`, `architecture.md`, `configuration.md`, `interfaces.md`, `nfr.md`, `milestones.md`, `regulatory-compliance.md`, `glossary.md`, `output-reporting.md` for staleness
- [ ] Mark any superseded specs with a deprecation notice pointing to the relevant docs section

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
