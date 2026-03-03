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
>
> **2026-03-03 update:** Priority 3 items 3.1-3.3 completed. COREP reporting docs created and
> verified (`docs/features/corep-reporting.md`, `docs/api/reporting.md`). Comparison & impact
> analysis docs verified (`docs/features/comparison.md`). FX conversion already documented.
> Priority 5 items 5.1-5.3 completed: test count inconsistencies fixed, LGD floor subordination
> distinction fixed, `CapitalImpactBundle` docstring corrected, mkdocs.yml and features index
> updated.

---

## Priority 1 — Critical: API Reference Out of Sync with Source

**COMPLETED 2026-03-02.** All API reference docs rewritten to match source code.

- [x] **1.1** `docs/api/contracts.md` — Bundles: All 10+ bundles rewritten (RawDataBundle, ResolvedHierarchyBundle, ClassifiedExposuresBundle, CRMAdjustedBundle, SAResultBundle, IRBResultBundle, SlottingResultBundle, AggregatedResultBundle). Added 5 missing bundles (CounterpartyLookup, ComparisonBundle, TransitionalScheduleBundle, CapitalImpactBundle, ELPortfolioSummary) and `create_empty_*()` helpers.
- [x] **1.2** `docs/api/contracts.md` — Errors: Rewrote CalculationError (10+ fields), added LazyFrameResult, all error code constants, factory functions. Removed non-existent CalculationWarning.
- [x] **1.3** `docs/api/contracts.md` — Protocols: Updated all protocol signatures, added 6 missing protocols (ComparisonRunnerProtocol, CapitalImpactAnalyzerProtocol, PipelineProtocol, SchemaValidatorProtocol, DataQualityCheckerProtocol, ResultExporterProtocol).
- [x] **1.4** `docs/api/engine.md` — All engine modules rewritten: CCF, CRM, SA, IRB, Slotting, Equity, Aggregator, Loader, Comparison, FX, utilities.
- [x] **1.5** `docs/api/configuration.md` — All config classes rewritten: CalculationConfig (13 fields), PDFloors, LGDFloors, SupportingFactors, OutputFloorConfig, RetailThresholds, IRBPermissions, PolarsEngine.
- [x] **1.6** `docs/api/domain.md` — Added 7 missing enums (CollateralType, IFRSStage, SlottingCategory, SpecialisedLendingType, PropertyType, Seniority, SCRAGrade). Fixed existing enums to StrEnum.

---

## Priority 2 — High: Data Model Schemas Use Wrong Column Names

**COMPLETED 2026-03-02.** All data model docs rewritten to match source code.

- [x] **2.1** `docs/data-model/intermediate-schemas.md` — All `_id` suffixes replaced with `_reference`. Added Raw Exposure, Resolved Hierarchy (14+ columns), Classified Exposure, CRM Adjusted, and Specialised Lending schemas.
- [x] **2.2** `docs/data-model/output-schemas.md` — SA/IRB/Slotting result schemas rewritten. Added full Calculation Output Schema (~100 columns), framework-specific additions, AggregatedResultBundle (15 fields), ELPortfolioSummary, ComparisonBundle, TransitionalScheduleBundle, CapitalImpactBundle.
- [x] **2.3** `docs/data-model/input-schemas.md` — Fixed Counterparty (added scra_grade, is_investment_grade), Facility (added is_qrre_transactor), Contingent (removed non-existent fields, added bs_type), Loan, and Equity schemas.
- [x] **2.4** `docs/data-model/data-validation.md` — Added 4 missing bundle validators, validate_risk_type, validate_ccf_modelled, normalize_risk_type, validate_column_values, validate_bundle_values with COLUMN_VALUE_CONSTRAINTS.
- [x] **2.5** `docs/data-model/regulatory-tables.md` — Fixed CRR corporate CQS 3 (75%->100%), slotting maturity differentiation, HVCRE weights. Added Basel 3.1 SCRA, LTV bands, equity tables, haircut 5-band maturity, F-IRB LGD, overcollateralisation requirements.

---

## Priority 3 — Medium: Missing Feature Documentation

### 3.1 Add COREP Reporting documentation

**COMPLETED 2026-03-03.**

- [x] Created `docs/features/corep-reporting.md` (168 lines) — user-facing guide covering C 07.00 (SA), C 08.01 (IRB totals), C 08.02 (IRB PD grade bands) templates, generation workflow, Excel export, regulatory references
- [x] Created `docs/api/reporting.md` (134 lines) — `COREPGenerator` class, `COREPTemplateBundle` output structure, `COREPRow` definitions
- [x] Minor column name fixes applied (C 07.00 col 030 and 060). Total row clarification for C 08.02
- [x] Updated `mkdocs.yml` nav to include new pages (see 5.2)
- [x] Updated `docs/features/index.md` feature matrix (see 5.3)

### 3.2 Add Comparison & Impact Analysis documentation

**COMPLETED 2026-03-03.**

- [x] Verified `docs/features/comparison.md` (220 lines) — all class signatures, bundle fields, waterfall drivers, timeline columns match source code
- [x] Comparison module already documented in `docs/api/engine.md` (DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner)
- [x] Updated `docs/features/index.md` feature matrix (see 5.3)

### 3.3 Add FX Conversion documentation

**COMPLETED 2026-03-03.**

- [x] Already documented in `docs/api/engine.md` (FXConverter section with convert_exposures, convert_collateral, convert_guarantees, convert_provisions, convert_equity_exposures)
- [x] Already documented in `docs/user-guide/methodology/fx-conversion.md`

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

**COMPLETED 2026-03-03.** Synced `docs/specifications/` from `specs/` (2026-03-02) and fixed internal inconsistencies (2026-03-03).

- [x] Synced all 11 stale `docs/specifications/` files to match `specs/` (canonical)
- [x] Fixed test count inconsistencies in `specs/milestones.md` and `specs/nfr.md` (91->97 CRR, 112->116 B31, 265->275 total, 1,834->1,844 total tests)
- [x] Fixed LGD floor subordination distinction in `specs/crr/airb-calculation.md`
- [x] Fixed `CapitalImpactBundle` docstring step order in source code

**Remaining work** — verify `specs/` files themselves against source code (not urgent since
`specs/` was already maintained):

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

**COMPLETED 2026-03-03.**

- [x] Added COREP reporting page to Features section
- [x] Added Comparison & Impact Analysis page to Features section
- [x] Added Reporting API page
- [ ] Verify all existing nav entries still point to valid files

### 5.3 Update `docs/features/index.md`

**COMPLETED 2026-03-03.**

- [x] Added Reporting & Analysis Features section (COREP reporting, comparison & impact analysis)
- [ ] Verify technology stack list is current

### 5.4 Update `docs/appendix/changelog.md`

- [ ] Add entry for documentation overhaul
- [ ] Verify recent changelog entries are accurate

---

## Execution Order

1. **Priority 1** (API Reference): COMPLETED 2026-03-02
2. **Priority 2** (Data Model): COMPLETED 2026-03-02
3. **Priority 3** (Missing Features): 3.1-3.3 COMPLETED 2026-03-03; 3.4 remaining
4. **Priority 4** (User Guide): Review and fix methodology/architecture accuracy
5. **Priority 5** (Housekeeping): 5.1-5.3 COMPLETED 2026-03-03; 5.4 and spec verification remaining

## Estimated Scope

- ~15 files needed significant rewrites (Priority 1-2) — **DONE**
- ~5 new files needed creation (Priority 3) — **3 DONE, 2 remaining**
- ~25 files need review and minor corrections (Priority 4-5) — **3 done, ~22 remaining**
- Total: ~45 documentation files affected
