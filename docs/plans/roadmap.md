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
| CRR Expected Outputs | Complete | 45 scenarios across 8 groups (SA, F-IRB, A-IRB, CRM, Slotting, Supporting Factors, Provisions, Complex) |
| CRR Acceptance Tests | Complete | 83 tests (38 validation, 45 implementation stubs) |
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
| CCF tables | `engine/ccf.py` | Complete | Complete | 15 |
| Data Loader | `engine/loader.py` | Complete | Complete | 31 |
| Hierarchy Resolver | `engine/hierarchy.py` | Complete | Complete | 17 |
| Exposure Classifier | `engine/classifier.py` | Complete | Complete | 19 |
| CRM Processor | `engine/crm/processor.py` | Complete | Complete | - |
| SA Calculator | `engine/sa/calculator.py` | Complete | Complete | - |
| IRB Calculator | `engine/irb/calculator.py` | Complete | Complete | - |
| Slotting Calculator | `engine/slotting/calculator.py` | Complete | Complete | - |
| **Equity Calculator** | `engine/equity/calculator.py` | **Complete** | N/A | - |
| Supporting Factors | `engine/sa/supporting_factors.py` | Complete | N/A | - |
| Output Aggregator | `engine/aggregator.py` | Complete | Complete | 21 |
| Output floor | `engine/aggregator.py` | N/A | Complete | - |
| Pipeline Orchestrator | `engine/pipeline.py` | Complete | Complete | 30 |

### Key Implementation Features

- **Pure LazyFrame Operations**: Hierarchy resolution uses iterative Polars joins instead of Python dicts for 50-100x performance improvement
- **Output Floor**: Full Basel 3.1 output floor with transitional schedule support (50% to 72.5%, 2027-2032)
- **Supporting Factors**: CRR SME tiered factor (0.7619/0.85) and infrastructure factor (0.75)
- **Summary Generation**: RWA aggregation by exposure class and calculation approach
- **Pipeline Orchestrator**: Complete pipeline wiring with error accumulation and audit trail
- **Equity Calculator**: Article 133 (SA) and Article 155 (IRB Simple) risk weight methods with diversified portfolio treatment
- **Pre/Post CRM Tracking**: Full tracking of guarantee impact on RWA with covered/uncovered portions

---

## Phase 4: Acceptance Testing

CRR acceptance tests validate production pipeline outputs against expected values:

| Group | Description | Scenarios | Status |
|-------|-------------|-----------|--------|
| CRR-A | Standardised Approach | 12 | **10 PASS, 2 SKIP** |
| CRR-B | Foundation IRB | 6 | 6 SKIP (needs PD data) |
| CRR-C | Advanced IRB | 3 | 3 SKIP (needs fixtures) |
| CRR-D | Credit Risk Mitigation | 6 | 6 SKIP (needs fixtures) |
| CRR-E | Specialised Lending (Slotting) | 4 | 4 SKIP (needs fixtures) |
| CRR-F | Supporting Factors | 7 | 7 SKIP (needs fixtures) |
| CRR-G | Provisions & Impairments | 3 | 3 SKIP (needs fixtures) |
| CRR-H | Complex/Combined | 4 | 4 SKIP (needs fixtures) |

### Key Achievements

- Pipeline-based testing using session-scoped fixtures
- Scenario-to-exposure reference mapping for all 46 scenarios
- CRR-A (SA) tests fully operational with 10 passing tests
- Remaining tests skipped pending fixture data (PD values for IRB, collateral/guarantee data for CRM)

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

**Total: 1,081 tests**

Run all tests:
```bash
uv run pytest -v
```

---

## Recent Completions

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
- [ ] Updated risk weight tables
- [ ] Output floor phase-in validation

### Fixture Completion

- [ ] IRB fixture data (PD values)
- [ ] CRM fixture data (collateral, guarantees)
- [ ] Slotting fixture data
- [ ] Provisions fixture data

---

## Next Steps

- [Testing Guide](../development/testing.md) - How to run tests
- [Benchmark Tests](../development/benchmarks.md) - Performance testing
- [Architecture](../architecture/index.md) - System design
