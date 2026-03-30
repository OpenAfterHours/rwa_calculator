# Changelog

All notable changes to the RWA Calculator are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

#### Article 114(4) EU domestic currency 0% risk weight for EU sovereigns
EU member state central government and central bank exposures denominated in that member state's domestic currency now receive 0% risk weight regardless of CQS, per CRR Art. 114(4). Covers all 27 EU member states: eurozone members (EUR) and non-euro members in their national currencies (PLN, SEK, CZK, DKK, HUF, BGN, RON). EU domestic sovereign exposures are also forced to the Standardised Approach, preventing internal models from overriding the regulatory 0% treatment. Applies to both direct exposures and guarantor risk weight substitution (SA and IRB).

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
Guarantor risk weight lookup used regex matching on `guarantor_entity_type` (e.g., `contains("SOVEREIGN")`), which only matched `sovereign` but not `central_bank`, `bank`, `company`, or `mdb`. These entity types produced `null` guarantor RW, causing beneficial guarantees to be incorrectly skipped. The lookup now uses `guarantor_exposure_class` (derived from the existing `ENTITY_TYPE_TO_SA_CLASS` mapping), ensuring all valid entity types resolve to the correct SA risk weight. Also adds Art. 114(3) domestic sovereign treatment: UK CGCB guarantors in GBP receive 0% RW regardless of CQS. Both SA calculator and IRB namespace are fixed. CRM processor and namespace now propagate `guarantor_country_code` from counterparty data.

---

## [0.1.41] - 2026-03-22

### Added

#### Article 114(3) domestic currency 0% risk weight for UK sovereign
UK central government and central bank exposures denominated in GBP now receive 0% risk weight regardless of CQS, per CRR Art. 114(3). Previously, 0% was only assigned via CQS 1 external rating lookup. The override applies in both CRR and Basel 3.1 SA risk weight chains. Foreign-currency UK sovereign exposures continue to use the standard CQS-based risk weight table.

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

#### SA Provision Handling — Art. 111(2) Compliance
Provisions are now resolved **before** CCF application using a drawn-first deduction approach, compliant with CRR Art. 111(2):

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
| Government-supported | 190% |
| Exchange-traded/Listed | 290% |
| Other equity | 370% |

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
| 0.1.48 | 2026-03-29 | Current |
| 0.1.47 | 2026-03-29 | Previous |
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
