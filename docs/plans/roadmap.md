# Development Roadmap

This page tracks the development status and progress of the RWA Calculator across all implementation phases.

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Test Infrastructure | Complete |
| Phase 2 | Process Contracts | Complete |
| Phase 3 | Implementation | Complete |
| Phase 4 | Acceptance Testing | Complete |

---

## Phase 1: Test Infrastructure

| Component | Status | Details |
|-----------|--------|---------|
| Test Data Fixtures | Complete | 15 fixture types covering all counterparty, exposure, CRM, and mapping scenarios |
| CRR Expected Outputs | Complete | 38 scenarios across 8 groups (SA, A-IRB, CRM, Slotting, Supporting Factors, Provisions, Complex, Defaulted) |
| CRR Acceptance Tests | Complete | 74 tests (71 pass, 3 skip) |
| Basel 3.1 Expected Outputs | Not Started | Planned for Phase 1.2B |

---

## Phase 2: Process Contracts

Interfaces and contracts between RWA calculator components have been implemented:

| Component | Location | Tests |
|-----------|----------|-------|
| Domain Enums | `src/rwa_calc/domain/enums.py` | - |
| Error Contracts | `src/rwa_calc/contracts/errors.py` | 20 |
| Configuration | `src/rwa_calc/contracts/config.py` | 20 |
| Data Bundles | `src/rwa_calc/contracts/bundles.py` | 24 |
| Protocols | `src/rwa_calc/contracts/protocols.py` | 14 |
| Validation | `src/rwa_calc/contracts/validation.py` | 19 |
| **Total** | **6 modules** | **97 tests** |

### Key Features

- `CalculationConfig.crr()` and `.basel_3_1()` factory methods for framework-specific configuration
- Protocol-based interfaces (`LoaderProtocol`, `ClassifierProtocol`, etc.) for dependency injection
- `LazyFrameResult` for error accumulation without exceptions
- Intermediate pipeline schemas for data validation at component boundaries

---

## Phase 3: Implementation

| Component | Location | CRR Status | Basel 3.1 Status | Tests |
|-----------|----------|------------|------------------|-------|
| Domain enums | `domain/enums.py` | Complete | Complete | - |
| Risk weight tables | `data/tables/crr_risk_weights.py` | Complete | Planned | - |
| CCF tables | `engine/ccf.py` | Complete | Complete | 57 |
| Data Loader | `engine/loader.py` | Complete | Complete | 31 |
| Hierarchy Resolver | `engine/hierarchy.py` | Complete | Complete | 66 |
| Exposure Classifier | `engine/classifier.py` | Complete | Complete | 24 |
| CRM Processor | `engine/crm/processor.py` | Complete | Complete | - |
| Haircut Calculator | `engine/crm/haircuts.py` | Complete | Complete | - |
| SA Calculator | `engine/sa/calculator.py` | Complete | Complete | - |
| IRB Calculator | `engine/irb/calculator.py` | Complete | Complete | - |
| Slotting Calculator | `engine/slotting/calculator.py` | Complete | Complete | - |
| Equity Calculator | `engine/equity/calculator.py` | Complete | N/A | - |
| Supporting Factors | `engine/sa/supporting_factors.py` | Complete | N/A | - |
| FX Converter | `engine/fx_converter.py` | Complete | Complete | 14 |
| Input Validation | `contracts/validation.py` | Complete | Complete | - |
| Output Aggregator | `engine/aggregator.py` | Complete | Complete | 21 |
| Output floor | `engine/aggregator.py` | N/A | Complete | - |
| Pipeline Orchestrator | `engine/pipeline.py` | Complete | Complete | 30 |

### Key Implementation Features

- **Pure LazyFrame Operations**: Hierarchy resolution uses iterative Polars joins instead of Python dicts for 50-100x performance improvement
- **Multi-Level Facility Hierarchy**: Facility root lookup traverses facility-to-facility hierarchies (up to 10 levels), aggregates drawn amounts to root, and excludes sub-facilities from undrawn output
- **Cross-Approach CCF Substitution**: When an IRB exposure is guaranteed by an SA counterparty, the guaranteed portion uses SA CCFs (CRR Art. 166/194)
- **Overcollateralisation**: CRR Art. 230 / CRE32.9-12 ratios (1.0x financial, 1.25x receivables, 1.4x RE/physical) with minimum thresholds
- **Equity Calculator**: Article 133 (SA) and Article 155 (IRB Simple) risk weight methods with diversified portfolio treatment
- **Pre/Post CRM Tracking**: Full tracking of guarantee impact on RWA with covered/uncovered portions
- **Output Floor**: Full Basel 3.1 output floor with transitional schedule support (50% to 72.5%, 2027-2032)
- **Supporting Factors**: CRR SME tiered factor (0.7619/0.85) and infrastructure factor (0.75)
- **Input Value Validation**: `validate_bundle_values()` with `DQ006` error code for invalid categorical values
- **Retail A-IRB / Corporate F-IRB**: Hybrid IRB permissions with corporate-to-retail reclassification for qualifying exposures
- **FX Conversion**: Multi-currency portfolio support with configurable target currency and full audit trail
- **Pipeline Orchestrator**: Complete pipeline wiring with error accumulation and audit trail
- **8 Polars Namespace Extensions**: Fluent, chainable APIs for SA, IRB, CRM, Haircuts, Slotting, Hierarchy, Aggregator, and Audit

---

## Phase 4: Acceptance Testing

CRR acceptance tests validate production pipeline outputs against expected values:

| Group | Description | Tests | Status |
|-------|-------------|-------|--------|
| CRR-A | Standardised Approach | 14 | **12 PASS, 2 SKIP** |
| CRR-C | Advanced IRB | 7 | **6 PASS, 1 SKIP** |
| CRR-D | Credit Risk Mitigation | 9 | **9 PASS** |
| CRR-E | Specialised Lending (Slotting) | 9 | **9 PASS** |
| CRR-F | Supporting Factors | 15 | **15 PASS** |
| CRR-G | Provisions & Impairments | 7 | **7 PASS** |
| CRR-H | Complex/Combined | 4 | **4 PASS** |
| CRR-I | Defaulted Exposures | 9 | **9 PASS** |
| | **Total** | **74** | **71 PASS, 3 SKIP** |

### Remaining Skipped Tests

| Test | Reason |
|------|--------|
| CRR-A7 | Commercial RE low LTV — fixture data needed |
| CRR-A8 | Off-balance sheet commitment CCF — fixture data needed |
| CRR-C3 | Specialised lending A-IRB — fixture data needed |

### Key Achievements

- Pipeline-based testing using session-scoped fixtures
- Scenario-to-exposure reference mapping for all scenarios
- 96% acceptance test pass rate (71/74)
- All major calculation approaches validated end-to-end (SA, A-IRB, CRM, Slotting, Supporting Factors, Provisions, Defaulted Exposures)
- F-IRB scenarios covered within A-IRB and Defaulted Exposure test groups

---

## CRR Workbook Components

Reference implementations for expected output generation:

| Component | Location | Status |
|-----------|----------|--------|
| CRR Parameters | `workbooks/crr_expected_outputs/data/crr_params.py` | Complete |
| SA Risk Weights | `workbooks/crr_expected_outputs/calculations/crr_risk_weights.py` | Complete |
| CCF Tables | `workbooks/crr_expected_outputs/calculations/crr_ccf.py` | Complete |
| Supporting Factors | `workbooks/crr_expected_outputs/calculations/crr_supporting_factors.py` | Complete |
| CRM Haircuts | `workbooks/crr_expected_outputs/calculations/crr_haircuts.py` | Complete |
| IRB Formulas | `workbooks/shared/irb_formulas.py` | Complete |
| Correlation | `workbooks/shared/correlation.py` | Complete |
| All Scenario Groups | `workbooks/crr_expected_outputs/scenarios/` | Complete |

---

## Test Results Summary

**Total: 1,286 tests** (1,050 unit + 74 acceptance + 162 benchmark)

| Category | Tests | Status |
|----------|-------|--------|
| Unit tests | 1,050 | All passing |
| Acceptance tests | 74 | 71 pass, 3 skip |
| Benchmark tests | 162 | All passing |

Run all tests:
```bash
uv run pytest -v
```

---

## Recent Completions

### v0.1.27
- [x] **Results Caching**: Pipeline results caching with lazy loading for performance
- [x] **Validation Refactor**: Replaced custom validation methods with shared utility functions
- [x] **IRB Config**: Replaced `enable_irb` boolean with `irb_approach` enum
- [x] **Data Materialization**: Optimized to reduce redundant `.collect()` calls

### v0.1.26
- [x] **Performance Optimization**: Aggregator, formatter, and validation processing speed improvements
- [x] **UI Speed**: Improved interactive calculator responsiveness

### v0.1.25
- [x] **Defaulted Exposures**: IRB defaulted treatment per CRR Art. 153(1)(ii) and 154(1)(i)
- [x] **CRR-I Acceptance Tests**: 9 new tests for F-IRB and A-IRB defaulted exposures
- [x] **SME Factor Fix**: Drawn amount used for tier threshold (not EAD)

### v0.1.24
- [x] **Multi-Level SA Collateral**: Collateral allocation for SA EAD reduction
- [x] **Haircut Enhancements**: Multi-level processing in haircut calculator

### v0.1.23
- [x] **Provision Resolution**: SA provision handling compliant with CRR Art. 111(2)
- [x] **Multi-Level Beneficiary**: Direct, facility, and counterparty provision resolution
- [x] **Drawn-First Deduction**: Provisions absorbed by drawn amount before reducing nominal
- [x] **14 Provision Tests**: Full test coverage in `tests/unit/crm/test_provisions.py`

### v0.1.22
- [x] **Slotting Maturity Splits**: Risk weights updated for remaining maturity bands (CRR Art. 153(5))
- [x] **Slotting Config**: Enhanced configuration for maturity band parameters

### v0.1.21
- [x] **Pledge Percentage**: Collateral valuation as percentage of beneficiary EAD
- [x] **Multi-Level Pledges**: Resolution across loan, facility, and counterparty levels

### v0.1.20
- [x] **Equity FX Conversion**: Currency conversion for equity exposure values
- [x] **Equity Pipeline**: Classifier and hierarchy support for equity in FX conversion

### v0.1.19
- [x] **Buy-to-Let Flag**: BTL identification and exclusion from SME supporting factor
- [x] **On-Balance EAD Helper**: `on_balance_ead()` function in CCF module

### v0.1.18
- [x] **Facility Root Lookup**: Multi-level facility hierarchy traversal (up to 10 levels)
- [x] **Undrawn Aggregation**: Drawn amounts from sub-facility loans aggregated to root facility
- [x] **Sub-Facility Exclusion**: Only root/standalone facilities produce undrawn exposure records
- [x] **Contingent Liabilities**: Included in facility undrawn calculations

### v0.1.17
- [x] **Negative Drawn Amounts**: Clamped to zero in EAD calculations (negative balances don't increase headroom)
- [x] **Duplicate Mapping Fix**: Resolved duplicate mapping issues in facility calculations

### v0.1.16
- [x] **Cross-Approach CCF Substitution**: SA CCFs applied to guaranteed portion of IRB exposures
- [x] **Guarantor Approach Detection**: Based on IRB permissions, exposure class, and rating type
- [x] **Aggregator Enhancements**: Updated summaries for post-CRM reporting

### v0.1.15
- [x] **Exposure Class Rename**: Sovereign → Central Govt / Central Bank for regulatory accuracy
- [x] **CI/CD**: GitHub Actions workflow for documentation deployment

### v0.1.14
- [x] **Overcollateralisation**: CRR Art. 230 / CRE32.9-12 overcollateralisation ratios and minimum thresholds
- [x] **Collateral standardization**: Consistent `collateral_type` casing and descriptions

### v0.1.13
- [x] **Input Value Validation**: `validate_bundle_values()` with error code DQ006
- [x] **Row Duplication Fix**: Prevented duplicate exposures when `facility_reference = loan_reference` (#71)

### v0.1.12
- [x] **Equity Calculator**: Article 133 (SA) and Article 155 (IRB Simple) risk weight methods
- [x] **Equity Namespace**: Polars LazyFrame namespace (`lf.equity`) for fluent calculations
- [x] **Pre/Post CRM Tracking**: Guarantee impact tracking with `rwa_pre_crm`, `rwa_post_crm`, `guarantee_rwa_benefit`
- [x] **Equity Risk Weight Tables**: `crr_equity_rw.py` with SA and IRB Simple lookups

---

## Upcoming Work

### Basel 3.1 Implementation

- [ ] Basel 3.1 expected outputs
- [ ] Basel 3.1 acceptance tests
- [ ] Updated risk weight tables (LTV-based real estate)
- [ ] Differentiated PD floors
- [ ] A-IRB LGD floors
- [ ] Output floor phase-in validation

### Remaining Fixture Completion

- [ ] Commercial RE low LTV fixture data (CRR-A7)
- [ ] Off-balance sheet commitment CCF fixture data (CRR-A8)
- [ ] Specialised lending A-IRB fixture data (CRR-C3)

---

## Next Steps

- [Testing Guide](../development/testing.md) - How to run tests
- [Benchmark Tests](../development/benchmarks.md) - Performance testing
- [Architecture](../architecture/index.md) - System design
