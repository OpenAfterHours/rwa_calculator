# Changelog

All notable changes to the RWA Calculator are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- (Next release changes will go here)

---



## [0.1.28] - 2026-02-24

### Changed
- Version bump for PyPI release

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

### Planned
- Basel 3.1 full implementation
- Differentiated PD floors
- A-IRB LGD floors
- Revised SA real estate risk weights

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
| 0.1.28 | 2026-02-24 | Current |
| 0.1.27 | 2026-02-24 | Previous |
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
