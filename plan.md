# RWA Calculator Implementation Plan

## Overview

This plan follows a **test-first approach** starting with User Acceptance Tests (UATs) that define expected inputs and outputs, then establishing contracts between components to enable isolated development and testing.

**Regulatory Framework Prioritisation**: The implementation follows a phased approach:
1. **Phase A: CRR (Basel 3.0)** - Current UK implementation (effective until 31 Dec 2026)
2. **Phase B: Basel 3.1** - Future UK implementation (effective from 1 Jan 2027 per PRA PS9/24)

This ensures we can validate against the current regulatory framework before extending to Basel 3.1.

---

## Regulatory Framework Differences

### Key Differences Between CRR (Basel 3.0) and Basel 3.1

| Area | CRR (Basel 3.0) | Basel 3.1 |
|------|-----------------|-----------|
| **1.06 Scaling Factor** | **Applies to ALL IRB RWA** (+6%) | **Removed** |
| **Output Floor** | None | 72.5% of SA RWA |
| **IRB Scope** | All exposure classes permitted | Excludes central govt exposures, equity, large/mid corporates (revenue >€500m), CIUs |
| **PD Floors** | 0.03% (all) | Differentiated: 0.03% corp, 0.05% retail, 0.10% QRRE |
| **LGD Floors (A-IRB)** | Supervisory LGDs for F-IRB only | New A-IRB LGD floors (0%-25% by collateral) |
| **SME Supporting Factor** | Tiered: 0.7619 (≤€2.5m) / 0.85 (>€2.5m) | Withdrawn |
| **Infrastructure Supporting Factor** | Applies (0.75 factor, flat) | Withdrawn |
| **Retail Threshold** | €1m aggregate exposure | £880k aggregate exposure |
| **SA Risk Weights** | CRR Tables | Revised tables (more granular LTV bands, due diligence requirements) |
| **Real Estate** | Whole loan approach | Split by LTV bands, ADC treatment |
| **Institutions** | ECRA with CQS | ECRA with SCRA fallback |
| **Specialised Lending** | Slotting approach | Slotting with revised weights |

### Critical IRB Formula Difference: 1.06 Scaling Factor

**CRR (Basel 3.0)** applies a **1.06 scaling factor** to all IRB risk-weighted assets. This factor was introduced in Basel II to provide a buffer during the transition to IRB approaches and has been retained in CRR.

**IRB RWA Formula:**
```
CRR:      RWA = K × 12.5 × 1.06 × EAD
Basel 3.1: RWA = K × 12.5 × EAD
```

Where K is the capital requirement from the IRB formula.

**Impact**: The 1.06 factor increases IRB RWA by 6% compared to the base formula. This means:
- A £100m IRB portfolio under CRR has 6% higher RWA than the same portfolio under Basel 3.1 (before considering other differences)
- The removal of the 1.06 factor in Basel 3.1 is partially offset by the introduction of the output floor (72.5% of SA RWA)

**Regulatory References:**
- CRR Art. 153(1): "...multiplied by 1.06"
- Basel 3.1 CRE30: No scaling factor applied

### UK-Specific Deviations (Both Frameworks)

| Area | Standard Basel | UK Implementation |
|------|---------------|-------------------|
| Institution CQS 2 | 50% RW | 30% RW |
| SME Threshold | €50m turnover | £44m turnover |
| Retail Aggregate | €1m / £880k | £880k (Basel 3.1) |

---

## Current Status

### Phase 1.1: Test Data Fixtures - COMPLETE

All test data fixtures have been created with Python generators and parquet output files.

| Fixture Type | Status | Records | Generator |
|--------------|--------|---------|-----------|
| Counterparty - Sovereign | Complete | 9 | `counterparty/sovereign.py` |
| Counterparty - Institution | Complete | 12 | `counterparty/institution.py` |
| Counterparty - Corporate | Complete | 24 | `counterparty/corporate.py` |
| Counterparty - Retail | Complete | 26 | `counterparty/retail.py` |
| Counterparty - Specialised Lending | Complete | 14 | `counterparty/specialised_lending.py` |
| Exposures - Facilities | Complete | 17 | `exposures/facilities.py` |
| Exposures - Loans | Complete | 28 | `exposures/loans.py` |
| Exposures - Contingents | Complete | 17 | `exposures/contingents.py` |
| Exposures - Facility Mapping | Complete | 15 | `exposures/facility_mapping.py` |
| Collateral | Complete | 22 | `collateral/collateral.py` |
| Guarantee | Complete | 15 | `guarantee/guarantee.py` |
| Provision | Complete | 18 | `provision/provision.py` |
| Ratings | Complete | 73 | `ratings/ratings.py` |
| Mapping - Org | Complete | 8 | `mapping/org_mapping.py` |
| Mapping - Lending | Complete | 7 | `mapping/lending_mapping.py` |

### Phase 1.2A: CRR Acceptance Test Scenarios - COMPLETE

CRR expected outputs workbook structure created with calculation modules and Marimo scenarios.
All CRR scenario groups (A through H) have been implemented.

#### CRR Acceptance Tests - COMPLETE

Pytest acceptance tests created that validate production calculator outputs against expected values.
Tests are structured as stub tests that skip until the production calculator is implemented.

| Test File | Scenario Group | Stub Tests | Validation Tests | Status |
|-----------|----------------|------------|------------------|--------|
| `test_scenario_crr_a_sa.py` | CRR-A (SA) | 12 | 4 | Complete |
| `test_scenario_crr_b_firb.py` | CRR-B (F-IRB) | 6 | 6 | Complete |
| `test_scenario_crr_c_airb.py` | CRR-C (A-IRB) | 3 | 4 | Complete |
| `test_scenario_crr_d_crm.py` | CRR-D (CRM) | 6 | 3 | Complete |
| `test_scenario_crr_e_slotting.py` | CRR-E (Slotting) | 4 | 5 | Complete |
| `test_scenario_crr_f_supporting_factors.py` | CRR-F (Supporting Factors) | 7 | 8 | Complete |
| `test_scenario_crr_g_provisions.py` | CRR-G (Provisions) | 3 | 4 | Complete |
| `test_scenario_crr_h_complex.py` | CRR-H (Complex) | 4 | 4 | Complete |
| `conftest.py` | Shared fixtures | - | - | Complete |

**Test Results:**
- **38 validation tests PASS** - Verify expected outputs structure is correct
- **45 stub tests SKIP** - Await production calculator implementation (Phase 3)

**Test Pattern:**
Each acceptance test follows the pattern:
1. Load fixture inputs (loan, counterparty, collateral, etc.)
2. Call production calculator (TODO - marked with `pytest.skip`)
3. Compare output against pre-calculated expected values

Run tests: `uv run pytest tests/acceptance/crr/ -v`

#### CRR-A: Standardised Approach (SA) - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-A1 | UK Sovereign - 0% RW | Complete |
| CRR-A2 | Unrated Corporate - 100% RW | Complete |
| CRR-A3 | Rated Corporate CQS 2 - 50% RW | Complete |
| CRR-A4 | UK Institution CQS 2 - 30% RW (UK deviation) | Complete |
| CRR-A5 | Residential Mortgage 60% LTV - 35% RW | Complete |
| CRR-A6 | Residential Mortgage 85% LTV - Split treatment | Complete |
| CRR-A7 | Commercial RE 40% LTV - 50% RW | Complete |
| CRR-A8 | Off-balance sheet - 50% CCF | Complete |
| CRR-A9 | Retail - 75% RW | Complete |
| CRR-A10 | SME Corporate with supporting factor (0.7619) | Complete |
| CRR-A11 | SME Retail with supporting factor (0.7619) | Complete |
| CRR-A12 | Large Corporate (no supporting factor) | Complete |

#### CRR-B: Foundation IRB (F-IRB) - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-B1 | Corporate F-IRB - Low PD (0.10%) | Complete |
| CRR-B2 | Corporate F-IRB - High PD (5.00%) | Complete |
| CRR-B3 | Subordinated Exposure - 75% LGD | Complete |
| CRR-B4 | SME Corporate F-IRB - Firm size adjustment | Complete |
| CRR-B5 | SME Corporate F-IRB - Both adjustments (firm size + SF) | Complete |
| CRR-B6 | Corporate at SME threshold (EUR 50m boundary) | Complete |
| CRR-B7 | Long Maturity Exposure (7Y -> 5Y cap) | Complete |

**Note**: F-IRB only applies to wholesale exposures (corporate, institution, sovereign). Retail exposures require A-IRB (internal LGD) or Standardised Approach.

#### CRR-C: Advanced IRB (A-IRB) - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-C1 | Corporate A-IRB - own LGD estimate (35%) | Complete |
| CRR-C2 | Retail A-IRB - own estimates (PD 0.3%, LGD 15%) | Complete |
| CRR-C3 | Specialised lending A-IRB - project finance | Complete |

**Note**: CRR A-IRB has NO LGD floors (unlike Basel 3.1 which has 25% unsecured floor).

#### CRR-D: Credit Risk Mitigation (CRM) - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-D1 | Cash collateral - 0% haircut | Complete |
| CRR-D2 | Government bond collateral - 4% haircut | Complete |
| CRR-D3 | Equity collateral (main index) - 15% haircut | Complete |
| CRR-D4 | Bank guarantee - substitution approach | Complete |
| CRR-D5 | Maturity mismatch adjustment | Complete |
| CRR-D6 | Currency mismatch - 8% FX haircut | Complete |

#### CRR-E: Specialised Lending (Slotting) - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-E1 | Project finance - Strong (70% RW) | Complete |
| CRR-E2 | Project finance - Good (70% RW) | Complete |
| CRR-E3 | IPRE - Weak (250% RW) | Complete |
| CRR-E4 | HVCRE - Strong (70% RW) | Complete |

**Note**: CRR has same RW for Strong and Good (both 70%). Basel 3.1 differentiates (50%/70%).

#### CRR-F: Supporting Factors - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-F1 | SME Tier 1 only - small exposure (£2m ≤ £2.2m) | Complete |
| CRR-F2 | SME blended tiers - medium exposure (£4m) | Complete |
| CRR-F3 | SME Tier 2 dominant - large exposure (£10m) | Complete |
| CRR-F4 | SME retail with Tier 1 factor (£500k) | Complete |
| CRR-F5 | Infrastructure supporting factor (0.75) | Complete |
| CRR-F6 | Large corporate - no SME factor (turnover > £44m) | Complete |
| CRR-F7 | At exposure threshold boundary (£2.2m exactly) | Complete |

**CRR SME Supporting Factor - Tiered Approach (CRR2 Art. 501):**
- **Tier 1**: Exposures up to €2.5m (£2.2m): factor of 0.7619 (23.81% RWA reduction)
- **Tier 2**: Exposures above €2.5m (£2.2m): factor of 0.85 (15% RWA reduction)

**Formula**: `factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E`

This tiered approach means smaller SME exposures get proportionally more capital relief than larger exposures.

**Note**: Infrastructure factor (0.75) is flat, not tiered. Both factors are NOT available under Basel 3.1.

#### CRR-G: Provisions & Impairments - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-G1 | SA with specific provision - net EAD | Complete |
| CRR-G2 | IRB EL shortfall - CET1/T2 deduction | Complete |
| CRR-G3 | IRB EL excess - T2 credit (capped) | Complete |

#### CRR-H: Complex/Combined - COMPLETE

| Scenario ID | Description | Status |
|-------------|-------------|--------|
| CRR-H1 | Facility with multiple loans - hierarchy | Complete |
| CRR-H2 | Counterparty group - rating inheritance | Complete |
| CRR-H3 | SME chain with supporting factor | Complete |
| CRR-H4 | Full CRM chain - collateral + guarantee + provision | Complete |

### CRR Workbook Implementation Status

| Component | Location | Status |
|-----------|----------|--------|
| Fixture Loader | `workbooks/shared/fixture_loader.py` | Complete |
| CRR Parameters | `workbooks/crr_expected_outputs/data/crr_params.py` | Complete |
| SA Risk Weights | `workbooks/crr_expected_outputs/calculations/crr_risk_weights.py` | Complete |
| CCF Tables | `workbooks/crr_expected_outputs/calculations/crr_ccf.py` | Complete |
| Supporting Factors | `workbooks/crr_expected_outputs/calculations/crr_supporting_factors.py` | Complete |
| CRM Haircuts | `workbooks/crr_expected_outputs/calculations/crr_haircuts.py` | Complete |
| IRB Formulas (shared) | `workbooks/shared/irb_formulas.py` | Complete |
| CRR IRB (wrapper) | `workbooks/crr_expected_outputs/calculations/crr_irb.py` | Complete |
| Correlation (shared) | `workbooks/shared/correlation.py` | Complete |
| Output Generator | `workbooks/crr_expected_outputs/generate_outputs.py` | Complete |
| CRR-A SA Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_a_sa.py` | Complete |
| CRR-B F-IRB Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_b_firb.py` | Complete |
| CRR-C A-IRB Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_c_airb.py` | Complete |
| CRR-D CRM Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_d_crm.py` | Complete |
| CRR-E Slotting Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_e_slotting.py` | Complete |
| CRR-F Supporting Factors | `workbooks/crr_expected_outputs/scenarios/group_crr_f_supporting_factors.py` | Complete |
| CRR-G Provision Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_g_provisions.py` | Complete |
| CRR-H Complex Scenarios | `workbooks/crr_expected_outputs/scenarios/group_crr_h_complex.py` | Complete |

### Key CRR Implementation Details

1. **1.06 Scaling Factor**: Implemented in IRB formulas - applies to ALL exposure classes under CRR (removed in Basel 3.1)
2. **SME Firm Size Adjustment**: R_adjusted = R - 0.04 × (1 - (max(S, 5) - 5) / 45) for turnover < EUR 50m
3. **SME Supporting Factor (Tiered)**: Per CRR2 Art. 501:
   - Tier 1: Factor 0.7619 for exposures ≤ €2.5m (£2.2m)
   - Tier 2: Factor 0.85 for exposures > €2.5m (£2.2m)
   - Effective factor calculated as: `[min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E`
   - NOT available under Basel 3.1
4. **Infrastructure Supporting Factor**: 0.75 (flat, not tiered) - NOT available under Basel 3.1
5. **PD Floor**: Single 0.03% floor for all exposure classes (Basel 3.1 has differentiated floors)
6. **F-IRB LGDs**: 45% unsecured senior, 75% subordinated
7. **Maturity**: Floor 1 year, Cap 5 years

### Expected Output Files Generated

| File | Location |
|------|----------|
| CSV | `tests/expected_outputs/crr/expected_rwa_crr.csv` |
| JSON | `tests/expected_outputs/crr/expected_rwa_crr.json` |
| Parquet | `tests/expected_outputs/crr/expected_rwa_crr.parquet` |

### Phase 1.2B: Basel 3.1 Acceptance Test Scenarios - NOT STARTED

### Phase 2: Process Contracts - COMPLETE

Interfaces and contracts between RWA calculator components have been implemented to enable:
- Isolated unit testing of each component
- Parallel development of different components
- Clear data flow boundaries
- Dual-framework support (CRR + Basel 3.1)

| Component | Location | Status |
|-----------|----------|--------|
| Domain Enums | `src/rwa_calc/domain/enums.py` | Complete |
| Error Contracts | `src/rwa_calc/contracts/errors.py` | Complete |
| Configuration Contracts | `src/rwa_calc/contracts/config.py` | Complete |
| Bundle Contracts | `src/rwa_calc/contracts/bundles.py` | Complete |
| Protocol Definitions | `src/rwa_calc/contracts/protocols.py` | Complete |
| Validation Utilities | `src/rwa_calc/contracts/validation.py` | Complete |
| Intermediate Schemas | `src/rwa_calc/data/schemas.py` | Complete |
| Contract Tests | `tests/contracts/` | Complete (97 tests) |

**Key Design Decisions:**
- **Protocol-based interfaces**: Structural typing with `@runtime_checkable` for easy mocking
- **Frozen dataclasses**: Immutable configuration and data bundles
- **Result pattern**: `LazyFrameResult` accumulates errors without exceptions
- **Factory methods**: `CalculationConfig.crr()` and `.basel_3_1()` for self-documenting configuration

### Phase 3: Implementation - NOT STARTED

---

## Phase 1: User Acceptance Tests

Define end-to-end acceptance tests that verify the complete calculation pipeline produces correct RWA outputs for known inputs.

### 1.1 Test Data Fixtures - COMPLETE

Test datasets have been created covering key regulatory scenarios. Each fixture type has:
- A Python generator module with dataclass definitions
- A `create_*()` function returning a Polars DataFrame
- A `save_*()` function writing to parquet format
- A `generate_all.py` runner script with summary output

```
tests/
├── fixtures/
│   ├── counterparty/
│   │   ├── sovereign.py              # UK Govt, US Govt, Brazil, Argentina, etc.
│   │   ├── institution.py            # Banks (Barclays, HSBC, JPMorgan), CCPs
│   │   ├── corporate.py              # Large corp, SME, unrated, org hierarchy groups
│   │   ├── retail.py                 # Individuals, mortgages, SME retail, lending groups
│   │   ├── specialised_lending.py    # Project finance, IPRE, HVCRE, object finance
│   │   ├── __init__.py
│   │   └── generate_all.py
│   ├── exposures/
│   │   ├── facilities.py             # RCFs, term facilities, mortgages, hierarchy test
│   │   ├── loans.py                  # Drawn exposures for all acceptance scenarios
│   │   ├── contingents.py            # Off-balance sheet (LCs, guarantees, commitments)
│   │   ├── facility_mapping.py       # Facility-to-loan/contingent relationships
│   │   ├── __init__.py
│   │   └── generate_all.py
│   ├── collateral/
│   │   ├── collateral.py             # Cash, bonds, equity, real estate, receivables
│   │   ├── __init__.py
│   │   └── generate_all.py
│   ├── guarantee/
│   │   ├── guarantee.py              # Sovereign, bank, corporate guarantees
│   │   ├── __init__.py
│   │   └── generate_all.py
│   ├── provision/
│   │   ├── provision.py              # SCRA/GCRA, IFRS9 stages 1-3
│   │   ├── __init__.py
│   │   └── generate_all.py
│   ├── ratings/
│   │   ├── ratings.py                # External (S&P/Moody's) and internal ratings
│   │   ├── __init__.py
│   │   └── generate_all.py
│   └── mapping/
│       ├── org_mapping.py            # Parent-subsidiary relationships
│       ├── lending_mapping.py        # Retail lending group connections
│       ├── __init__.py
│       └── generate_all.py
```

### 1.2A CRR (Basel 3.0) Acceptance Test Scenarios

Each scenario defines **specific inputs** and **expected outputs** with hand-calculated values based on current CRR rules (EU 575/2013 as onshored into UK law).

#### Scenario Group CRR-A: Standardised Approach (SA) - CRR

| ID | Description | Key Inputs | Expected RWA | Regulatory Basis |
|----|-------------|------------|--------------|------------------|
| CRR-A1 | UK Sovereign exposure | £1m loan to UK Govt, CQS1 | £0 (0% RW) | CRR Art. 114 |
| CRR-A2 | Unrated corporate | £1m loan, no rating, no SME | £1m (100% RW) | CRR Art. 122 |
| CRR-A3 | Rated corporate CQS2 | £1m loan, A-rated | £500k (50% RW) | CRR Art. 122 |
| CRR-A4 | Institution ECRA CQS2 | £1m loan to UK bank, A-rated | £300k (30% RW) | CRR Art. 120 + UK deviation |
| CRR-A5 | Residential mortgage ≤80% LTV | £500k loan, 75% LTV | £175k (35% RW) | CRR Art. 125 |
| CRR-A6 | Residential mortgage >80% LTV | £850k loan, 85% LTV | £425k (50% avg RW) | CRR Art. 125 |
| CRR-A7 | Commercial real estate ≤50% LTV | £600k loan, 50% LTV | £300k (50% RW) | CRR Art. 126 |
| CRR-A8 | Off-balance sheet commitment | £1m undrawn (>1yr), 50% CCF | £500k EAD | CRR Art. 111 |
| CRR-A9 | Retail exposure | £50k loan to individual | £37.5k (75% RW) | CRR Art. 123 |
| CRR-A10 | SME with supporting factor | £1m loan, SME <€50m turnover | £761.9k (100% × 0.7619) | CRR Art. 501 |

**CRR-Specific Notes:**
- CRR uses 35%/50% split for residential mortgages (not LTV bands like Basel 3.1)
- SME supporting factor (0.7619) applies to SME exposures
- Infrastructure supporting factor (0.75) applies to qualifying infrastructure
- Off-balance sheet CCFs: 0%, 20%, 50%, 100% (simpler than Basel 3.1)

#### Scenario Group CRR-B: Foundation IRB (F-IRB) - CRR

**Important**: F-IRB only applies to wholesale exposures (corporate, institution, sovereign). Retail exposures must use A-IRB (with internal LGD estimates) or Standardised Approach.

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-B1 | Corporate unsecured - low PD | PD=0.10%, LGD=45%, M=2.5y, EAD=£25m | £7.86m | CRR Art. 153, 161-163 |
| CRR-B2 | Corporate unsecured - high PD | PD=5.00%, LGD=45%, M=3.0y, EAD=£5m | £8.26m | CRR Art. 153, 161-162 |
| CRR-B3 | Subordinated exposure | PD=1.00%, LGD=75%, M=4.0y, EAD=£2m | £3.93m | CRR Art. 153, 161 |
| CRR-B4 | SME Corporate - firm size adj | PD=1.50%, LGD=45%, M=2.5y, T=€25m | Reduced R | CRR Art. 153(4), 161 |
| CRR-B5 | SME Corporate - both adjustments | PD=2.00%, LGD=45%, M=3.0y, T=€15m | R adj + SF 0.7619 | CRR Art. 153(4), 501 |
| CRR-B6 | Corporate at SME threshold | PD=1.00%, LGD=45%, M=2.5y, T=€50m | No firm size adj | CRR Art. 153, 161 |
| CRR-B7 | Long maturity exposure | PD=0.80%, LGD=45%, M=7y (capped 5y) | Maturity capped | CRR Art. 153, 162 |

**CRR F-IRB Notes:**
- Supervisory LGDs: Unsecured 45%, Subordinated 75%
- Secured LGDs vary by collateral type (0% cash, 35% receivables/RE)
- PD floor: 0.03% for all classes (single floor)
- 1.06 scaling factor applied to all exposures (RWA = K × 12.5 × 1.06 × EAD × MA)
- SME firm size adjustment: R = R - 0.04 × (1 - (max(S,5)-5)/45) for turnover < EUR 50m
- No A-IRB LGD floors under CRR

#### Scenario Group CRR-C: Advanced IRB (A-IRB) - CRR

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-C1 | Corporate own estimates | PD=1%, LGD=35%, M=2.5y | Bank-estimated | CRR Art. 143 |
| CRR-C2 | Retail own estimates | PD=0.3%, LGD=15%, EAD=£100k | Retail formula | CRR Art. 154 |
| CRR-C3 | Specialised lending A-IRB | PD=1.5%, LGD=25% | Project finance | CRR Art. 153 |

**CRR A-IRB Notes:**
- No LGD floors under CRR A-IRB (unlike Basel 3.1)
- Full scope of A-IRB permitted for all exposure classes
- Own LGD, EAD, and CCF estimates allowed

#### Scenario Group CRR-D: Credit Risk Mitigation (CRM) - CRR

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-D1 | Cash collateral (SA) | £1m exposure, £500k cash | £500k EAD | CRR Art. 207 |
| CRR-D2 | Govt bond collateral | £1m exp, £600k gilts (5y) | Haircut applied | CRR Art. 224 |
| CRR-D3 | Equity collateral (main index) | £1m exp, £400k listed equity | 15% haircut | CRR Art. 224 |
| CRR-D4 | Guarantee substitution | £1m corp, £600k bank guarantee | Split RW | CRR Art. 213 |
| CRR-D5 | Maturity mismatch | £1m exp 5y, £500k collateral 2y | Adjusted value | CRR Art. 238 |
| CRR-D6 | Currency mismatch | £1m GBP exp, €500k collateral | 8% FX haircut | CRR Art. 224 |

**CRR CRM Notes:**
- Comprehensive approach permitted for SA and IRB
- Supervisory haircuts (can use own-estimates under conditions)
- Main index equity haircut: 15% (vs 25% for other equity)

#### Scenario Group CRR-E: Specialised Lending (Slotting) - CRR

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-E1 | Project finance - Strong | £10m, Strong category | £7m (70% RW) | CRR Art. 153(5) |
| CRR-E2 | Project finance - Good | £10m, Good category | £7m (70% RW) | Same as Strong |
| CRR-E3 | IPRE - Weak | £5m, Weak category | £5.75m (115% RW) | CRR Art. 153(5) |
| CRR-E4 | HVCRE - Strong | £5m, High volatility CRE | £3.5m (70% RW) | CRR Art. 153(5) |

**CRR Slotting Risk Weights:**

| Category | Non-HVCRE | HVCRE |
|----------|-----------|-------|
| Strong | 70% | 70% |
| Good | 70% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% (EL) | 0% (EL) |

#### Scenario Group CRR-G: Provisions & Impairments - CRR

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-G1 | SA with specific provision | £1m exposure, £50k provision | £950k net | CRR Art. 110 |
| CRR-G2 | IRB EL shortfall | EL > provisions | T2 deduction | CRR Art. 159 |
| CRR-G3 | IRB EL excess | Provisions > EL | T2 credit (capped) | CRR Art. 62(d) |

#### Scenario Group CRR-H: Complex/Combined - CRR

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| CRR-H1 | Facility with multiple loans | £5m facility, 3 loans | Aggregate | Hierarchy test |
| CRR-H2 | Counterparty group | Parent + 2 subs | Rating inheritance | Org hierarchy |
| CRR-H3 | SME chain with factor | SME corp + supporting factor | 0.7619 applied | CRR Art. 501 |
| CRR-H4 | Full CRM chain | Exp + coll + guar + prov | All CRM steps | Integration |

### 1.2B Basel 3.1 Acceptance Test Scenarios

These scenarios test the Basel 3.1 implementation per PRA PS9/24, effective 1 Jan 2027.

#### Scenario Group B31-A: Standardised Approach (SA) - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Regulatory Basis |
|----|-------------|------------|--------------|------------------|
| B31-A1 | UK Sovereign exposure | £1m loan to UK Govt, CQS1 | £0 (0% RW) | CRE20.7 |
| B31-A2 | Unrated corporate | £1m loan, no rating, no SME | £1m (100% RW) | CRE20.26 |
| B31-A3 | Rated corporate CQS2 | £1m loan, A-rated | £500k (50% RW) | CRE20.25 |
| B31-A4 | Institution ECRA CQS2 | £1m loan to UK bank, A-rated | £300k (30% RW) | UK deviation |
| B31-A5 | Residential mortgage 60% LTV | £500k loan, £833k property | £100k (20% RW) | CRE20.71 |
| B31-A6 | Residential mortgage 85% LTV | £850k loan, £1m property | £297.5k (35% RW) | CRE20.71 |
| B31-A7 | Commercial RE 60% LTV | £600k loan, £1m property | £360k (60% RW) | CRE20.83 |
| B31-A8 | Off-balance sheet commitment | £1m undrawn, 40% CCF | £400k EAD | CRE20.94 |
| B31-A9 | Retail exposure | £50k loan to individual | £37.5k (75% RW) | CRE20.66 |
| B31-A10 | SME (no supporting factor) | £1m loan, SME | £1m (100% RW) | No factor in B3.1 |

**Basel 3.1 SA Notes:**
- New LTV-based risk weights for real estate
- 40% CCF for commitments (revised from 50%)
- No SME/infrastructure supporting factors
- Due diligence requirements for external ratings

#### Scenario Group B31-B: Foundation IRB (F-IRB) - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-B1 | Corporate unsecured | PD=1%, LGD=40%, M=2.5y | Supervisory LGD | Revised 40% |
| B31-B2 | Corporate with collateral | PD=1%, £500k cash | LGD=0% | CRE32 |
| B31-B3 | Corporate with RE | PD=1%, 60% LTV | LGD=20% | CRE32 |
| B31-B4 | Retail mortgage | PD=0.5%, LGD=10% | Retail formula | CRE30 |
| B31-B5 | QRRE | PD=0.5%, LGD=50% | QRRE formula | CRE30 |
| B31-B6 | PD floor test | Internal PD=0.01% | Floor=0.03% | CRE30.52 |

**Basel 3.1 F-IRB Notes:**
- Revised supervisory LGD: 40% unsecured (down from 45%)
- PD floors: 0.03% corp, 0.05% retail, 0.10% QRRE

#### Scenario Group B31-C: Advanced IRB (A-IRB) - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-C1 | Corporate (restricted) | Revenue <€500m, own LGD | LGD floor 25% | CRE36 |
| B31-C2 | LGD floor test | Internal LGD=5% | Floor=25% | CRE36.11 |
| B31-C3 | Retail own estimates | PD=0.3%, LGD=15% | Floor=5% secured | CRE36 |

**Basel 3.1 A-IRB Notes:**
- Restricted scope: excludes large/mid corporates (>€500m revenue)
- New LGD floors: 25% unsecured, 0-15% secured
- Input floors for all parameters

#### Scenario Group B31-D: Credit Risk Mitigation (CRM) - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-D1 | Cash collateral | £1m exp, £500k cash | 0% haircut | CRE22 |
| B31-D2 | Govt bond collateral | £1m exp, £600k gilts | Revised haircuts | CRE22 |
| B31-D3 | Equity collateral | £1m exp, £400k equity | 25% haircut | CRE22 |
| B31-D4 | Guarantee substitution | £1m corp, £600k bank guar | Substitution | CRE22 |
| B31-D5 | Maturity mismatch | 5y exp, 2y collateral | Adjusted | CRE22 |
| B31-D6 | Currency mismatch | GBP exp, EUR collateral | 8% FX haircut | CRE22 |

#### Scenario Group B31-E: Specialised Lending (Slotting) - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-E1 | Project finance - Strong | £10m, Strong | £5m (50% RW) | CRE33 |
| B31-E2 | Project finance - Good | £10m, Good | £7m (70% RW) | CRE33 |
| B31-E3 | IPRE - Speculative | £5m, Speculative | £5.75m (115% RW) | CRE33 |
| B31-E4 | HVCRE | £5m, HVCRE Good | £5m (100% RW) | CRE33 |

**Basel 3.1 Slotting Risk Weights:**

| Category | Non-HVCRE | HVCRE |
|----------|-----------|-------|
| Strong | 50% | 70% |
| Good | 70% | 95% |
| Satisfactory | 100% | 120% |
| Weak | 150% | 175% |
| Default | 350% | 350% |

#### Scenario Group B31-F: Output Floor - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-F1 | Floor binding | IRB=£50m, SA=£100m | £72.5m | 72.5% floor |
| B31-F2 | Floor not binding | IRB=£80m, SA=£100m | £80m | IRB > floor |
| B31-F3 | Transitional 2027 | Year 2027, 50% floor | Phased floor | PRA PS9/24 |

**Output Floor Phase-In:**

| Year | Floor % |
|------|---------|
| 2027 | 50% |
| 2028 | 55% |
| 2029 | 60% |
| 2030 | 65% |
| 2031 | 70% |
| 2032+ | 72.5% |

#### Scenario Group B31-G: Provisions - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-G1 | SA net of provisions | £1m exp, £50k prov | Net EAD | CRE20 |
| B31-G2 | IRB Stage 1 | £1m exp, Stage 1 ECL | EL comparison | CRE35 |
| B31-G3 | Defaulted IRB | £1m defaulted, Stage 3 | In-default LGD | CRE35 |

#### Scenario Group B31-H: Complex/Combined - Basel 3.1

| ID | Description | Key Inputs | Expected RWA | Notes |
|----|-------------|------------|--------------|-------|
| B31-H1 | Facility hierarchy | £5m facility, 3 loans | Aggregate | Hierarchy |
| B31-H2 | Counterparty group | Parent + 2 subs | Inheritance | Org hierarchy |
| B31-H3 | Mixed SA/IRB | Portfolio split | Correct routing | Approach |
| B31-H4 | Full CRM + Floor | All CRM + output floor | Integration | Full chain |

---

## Phase 2: Process Contracts

Define clear interfaces between components to enable isolated testing and parallel development.

### 2.1 Output Schema Strategy

The calculator will support both CRR and Basel 3.1 with a unified output schema that includes all fields, with framework-specific fields clearly marked.

```python
# Approach: Single comprehensive schema with framework indicators

@dataclass
class CalculationOutputSchema:
    """Output schema supporting both CRR and Basel 3.1."""

    # Framework identification
    regulatory_framework: Literal["CRR", "BASEL_3_1"]
    reporting_date: date

    # Common fields (both frameworks)
    exposure_reference: str
    counterparty_reference: str
    exposure_class: str
    approach: Literal["SA", "FIRB", "AIRB"]
    ead: Decimal
    risk_weight: Decimal
    rwa: Decimal

    # CRR-specific fields
    sme_supporting_factor_applied: bool | None  # CRR only
    infrastructure_supporting_factor_applied: bool | None  # CRR only
    crr_ccf_category: str | None  # CRR CCF categories

    # Basel 3.1-specific fields
    output_floor_applicable: bool | None  # B3.1 only
    rwa_pre_floor: Decimal | None  # B3.1 only
    rwa_sa_equivalent: Decimal | None  # B3.1 only
    rwa_floor_impact: Decimal | None  # B3.1 only
    ltv_band: str | None  # B3.1 granular LTV
    pd_floor_applied: Decimal | None  # B3.1 differentiated floors
    lgd_floor_applied: Decimal | None  # B3.1 A-IRB floors
```

### 2.2 Contract Definitions

Each contract specifies:
- **Input schema** (Polars DataFrame schema)
- **Output schema** (Polars DataFrame schema)
- **Invariants** (rules that must always hold)
- **Error handling** (how failures are communicated)

### 2.3 Core Contracts

#### Contract 1: Data Loader Contract

```python
# src/rwa_calc/contracts/loader_contract.py

from dataclasses import dataclass
from typing import Protocol
import polars as pl


@dataclass
class LoaderOutput:
    """Output contract for data loaders."""
    counterparties: pl.LazyFrame
    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    contingents: pl.LazyFrame
    collateral: pl.LazyFrame
    guarantees: pl.LazyFrame
    provisions: pl.LazyFrame
    ratings: pl.LazyFrame
    facility_mappings: pl.LazyFrame
    org_mappings: pl.LazyFrame
    lending_mappings: pl.LazyFrame


class LoaderProtocol(Protocol):
    """Contract that all loaders must implement."""

    def load(self) -> LoaderOutput:
        """Load and return all required data."""
        ...

    def validate(self) -> list[str]:
        """Validate loaded data, return list of validation errors."""
        ...
```

#### Contract 2: Configuration Contract

```python
# src/rwa_calc/contracts/config_contract.py

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass
class CalculationConfig:
    """Configuration contract for RWA calculations."""

    # Framework selection
    regulatory_framework: Literal["CRR", "BASEL_3_1"]
    reporting_date: date

    # CRR-specific
    apply_sme_supporting_factor: bool = True  # Default True for CRR
    apply_infrastructure_factor: bool = True

    # Basel 3.1-specific
    output_floor_percentage: float = 0.725  # 72.5% at full implementation
    transitional_floor_year: int | None = None  # For phase-in

    @property
    def is_crr(self) -> bool:
        return self.regulatory_framework == "CRR"

    @property
    def is_basel_31(self) -> bool:
        return self.regulatory_framework == "BASEL_3_1"
```

#### Contract 3: Hierarchy Builder Contract

```python
# src/rwa_calc/contracts/hierarchy_contract.py

from dataclasses import dataclass
import polars as pl


@dataclass
class ExposureHierarchyOutput:
    """Output contract for exposure hierarchy builder."""
    exposures: pl.LazyFrame
    # Schema additions:
    #   - exposure_reference: str
    #   - facility_reference: str | None
    #   - exposure_type: Literal["loan", "contingent"]
    #   - ead: Decimal
    #   - hierarchy_level: int


@dataclass
class CounterpartyHierarchyOutput:
    """Output contract for counterparty hierarchy builder."""
    counterparties: pl.LazyFrame
    # Schema additions:
    #   - ultimate_parent_reference: str
    #   - effective_rating: str
    #   - effective_cqs: int
    #   - lending_group_reference: str | None
    #   - lending_group_total_exposure: Decimal
```

#### Contract 4: Classification Contract

```python
# src/rwa_calc/contracts/classification_contract.py

from dataclasses import dataclass
from typing import Literal
import polars as pl


# CRR Exposure Classes (Art. 112)
CRRExposureClass = Literal[
    "CENTRAL_GOVERNMENTS_CENTRAL_BANKS",
    "REGIONAL_GOVERNMENTS_LOCAL_AUTHORITIES",
    "PUBLIC_SECTOR_ENTITIES",
    "MULTILATERAL_DEVELOPMENT_BANKS",
    "INTERNATIONAL_ORGANISATIONS",
    "INSTITUTIONS",
    "CORPORATES",
    "RETAIL",
    "SECURED_BY_REAL_ESTATE",
    "PAST_DUE",
    "HIGHER_RISK_CATEGORIES",
    "COVERED_BONDS",
    "SECURITISATION",
    "INSTITUTIONS_CORPORATES_SHORT_TERM",
    "COLLECTIVE_INVESTMENT_UNDERTAKINGS",
    "EQUITY",
    "OTHER",
]

# Basel 3.1 Exposure Classes
Basel31ExposureClass = Literal[
    "SOVEREIGN",
    "PSE",
    "MDB",
    "INSTITUTION",
    "CORPORATE",
    "CORPORATE_SME",
    "SPECIALISED_LENDING",
    "RETAIL",
    "RETAIL_MORTGAGE",
    "RETAIL_QRRE",
    "RETAIL_SME",
    "REAL_ESTATE",
    "EQUITY",
    "SUBORDINATED_DEBT",
    "OTHER",
    "DEFAULTED",
]


@dataclass
class ClassificationOutput:
    """Output contract for exposure classifier."""
    classified_exposures: pl.LazyFrame
    # Schema:
    #   - exposure_class: str (framework-appropriate class)
    #   - approach: Literal["SA", "FIRB", "AIRB"]
    #   - is_defaulted: bool
    #   - classification_reason: str
```

#### Contract 5: CRM Processor Contract

```python
# src/rwa_calc/contracts/crm_contract.py

from dataclasses import dataclass
import polars as pl


@dataclass
class CRMOutput:
    """Output contract for CRM processor."""
    mitigated_exposures: pl.LazyFrame
    # Schema:
    #   - ead_pre_crm: Decimal
    #   - ead_post_crm: Decimal
    #   - collateral_value_adjusted: Decimal
    #   - guarantee_value_adjusted: Decimal
    #   - provision_deducted: Decimal
    #   - lgd_adjusted: Decimal (for IRB)
    #   - substitute_rw: Decimal | None
    #   - crm_details: str (JSON audit trail)
```

#### Contract 6: SA Calculator Contract

```python
# src/rwa_calc/contracts/sa_contract.py

from dataclasses import dataclass
import polars as pl


@dataclass
class SACalculatorInput:
    """Input for SA calculator."""
    mitigated_exposures: pl.LazyFrame
    config: "CalculationConfig"

    # Framework-specific lookups
    risk_weight_tables: dict[str, pl.LazyFrame]


@dataclass
class SACalculatorOutput:
    """Output contract for SA calculator."""
    sa_results: pl.LazyFrame
    # Schema:
    #   - exposure_reference: str
    #   - exposure_class: str
    #   - ead: Decimal
    #   - risk_weight: Decimal
    #   - rwa: Decimal
    #   - supporting_factor: Decimal (1.0 if none, 0.7619 for SME, etc.)
    #   - rw_lookup_key: str
```

#### Contract 7: IRB Calculator Contract

```python
# src/rwa_calc/contracts/irb_contract.py

from dataclasses import dataclass
import polars as pl


@dataclass
class IRBCalculatorOutput:
    """Output contract for IRB calculator."""
    irb_results: pl.LazyFrame
    # Schema:
    #   - exposure_reference: str
    #   - exposure_class: str
    #   - approach: Literal["FIRB", "AIRB"]
    #   - pd_raw: Decimal
    #   - pd_floored: Decimal
    #   - lgd_raw: Decimal
    #   - lgd_floored: Decimal (Basel 3.1 only for A-IRB)
    #   - ead: Decimal
    #   - maturity: Decimal
    #   - correlation: Decimal
    #   - k: Decimal
    #   - rwa: Decimal
```

#### Contract 8: Output Floor Contract (Basel 3.1 only)

```python
# src/rwa_calc/contracts/output_floor_contract.py

from dataclasses import dataclass
import polars as pl


@dataclass
class OutputFloorOutput:
    """Output contract for output floor calculation (Basel 3.1 only)."""
    floored_results: pl.LazyFrame
    # Schema additions:
    #   - rwa_irb: Decimal
    #   - rwa_sa_equivalent: Decimal
    #   - rwa_floor: Decimal
    #   - rwa_final: Decimal
    #   - is_floor_binding: bool

    summary: dict
    # Total RWA impact, floor binding %
```

---

## Phase 3: Implementation Order

With acceptance tests and contracts defined, implement components in dependency order.

**Architecture Notes:**
- All engines implement protocols defined in `src/rwa_calc/contracts/protocols.py`
- Data flows through bundles defined in `src/rwa_calc/contracts/bundles.py`
- Configuration from `src/rwa_calc/contracts/config.py` (use `.crr()` factory)
- Validation using `src/rwa_calc/contracts/validation.py`
- Calculation logic can be adapted from `workbooks/` modules

### 3.1 CRR Implementation (Priority)

Implement CRR first to enable testing against current regulatory framework.

#### 3.1.A Foundation Layer (Already Complete in Phase 2)

| Step | Component | Location | Status |
|------|-----------|----------|--------|
| 3.1.A1 | Domain enums | `src/rwa_calc/domain/enums.py` | Complete |
| 3.1.A2 | Protocols | `src/rwa_calc/contracts/protocols.py` | Complete |
| 3.1.A3 | Bundles | `src/rwa_calc/contracts/bundles.py` | Complete |
| 3.1.A4 | Config | `src/rwa_calc/contracts/config.py` | Complete |
| 3.1.A5 | Validation | `src/rwa_calc/contracts/validation.py` | Complete |
| 3.1.A6 | Schemas | `src/rwa_calc/data/schemas.py` | Complete |

#### 3.1.B Data Layer

| Step | Component | Location | Description | Status |
|------|-----------|----------|-------------|--------|
| 3.1.B1 | Risk weight tables | `src/rwa_calc/data/tables/crr_risk_weights.py` | Art. 112-134 lookup tables as Polars DataFrames | Complete |
| 3.1.B2 | CCF tables | `src/rwa_calc/data/tables/crr_ccf.py` | Art. 111 conversion factors | Complete |
| 3.1.B3 | CRM haircuts | `src/rwa_calc/data/tables/crr_haircuts.py` | Art. 224 supervisory haircuts | Complete |
| 3.1.B4 | Slotting tables | `src/rwa_calc/data/tables/crr_slotting.py` | Art. 153(5) slotting risk weights | Complete |
| 3.1.B5 | F-IRB LGDs | `src/rwa_calc/data/tables/crr_firb_lgd.py` | Supervisory LGD by collateral type | Complete |

#### 3.1.C Engine Layer - Pipeline Stages

Implement in dependency order (each stage produces output consumed by next):

| Step | Component | Protocol | Location | Description | Status |
|------|-----------|----------|----------|-------------|--------|
| 3.1.C1 | Data Loader | `LoaderProtocol` | `src/rwa_calc/engine/loader.py` | Load from Parquet/CSV, returns `RawDataBundle` | Complete |
| 3.1.C2 | Hierarchy Resolver | `HierarchyResolverProtocol` | `src/rwa_calc/engine/hierarchy.py` | Resolve org/facility hierarchies, rating inheritance | Complete |
| 3.1.C3 | Exposure Classifier | `ClassifierProtocol` | `src/rwa_calc/engine/classifier.py` | Classify exposures, assign approach (SA/IRB) | Complete |
| 3.1.C4 | CRM Processor | `CRMProcessorProtocol` | `src/rwa_calc/engine/crm/processor.py` | Apply collateral, guarantees, provisions, CCFs | Not Started |
| 3.1.C5 | SA Calculator | `SACalculatorProtocol` | `src/rwa_calc/engine/sa/calculator.py` | SA risk weights, supporting factors | Not Started |
| 3.1.C6 | IRB Calculator | `IRBCalculatorProtocol` | `src/rwa_calc/engine/irb/calculator.py` | F-IRB/A-IRB K formula, 1.06 scaling | Not Started |
| 3.1.C7 | Slotting Calculator | `SlottingCalculatorProtocol` | `src/rwa_calc/engine/slotting/calculator.py` | Specialised lending slotting approach | Not Started |
| 3.1.C8 | Output Aggregator | `OutputAggregatorProtocol` | `src/rwa_calc/engine/aggregator.py` | Combine results, apply supporting factors | Not Started |
| 3.1.C9 | Pipeline Orchestrator | `PipelineProtocol` | `src/rwa_calc/engine/pipeline.py` | Wire stages together, run full calculation | Not Started |

#### 3.1.D Supporting Modules

| Step | Component | Location | Description | Status |
|------|-----------|----------|-------------|--------|
| 3.1.D1 | IRB Formulas | `src/rwa_calc/engine/irb/formulas.py` | Core K calculation, maturity adjustment | Not Started |
| 3.1.D2 | Correlation | `src/rwa_calc/engine/irb/correlation.py` | Asset correlation by exposure class | Not Started |
| 3.1.D3 | CRM Haircuts | `src/rwa_calc/engine/crm/haircuts.py` | Apply supervisory haircuts to collateral | Not Started |
| 3.1.D4 | CCF Calculator | `src/rwa_calc/engine/crm/ccf.py` | Calculate EAD from undrawn | Not Started |
| 3.1.D5 | Supporting Factors | `src/rwa_calc/engine/sa/supporting_factors.py` | SME/infrastructure factor calculation | Not Started |

#### 3.1.E Unit Tests (TDD)

| Step | Component | Location | Description | Status |
|------|-----------|----------|-------------|--------|
| 3.1.E1 | Data table tests | `tests/unit/crr/test_crr_tables.py` | Test lookup tables | Complete (77 tests) |
| 3.1.E2 | Loader tests | `tests/unit/test_loader.py` | Test data loading | Complete (35 tests) |
| 3.1.E3 | Hierarchy tests | `tests/unit/test_hierarchy.py` | Test hierarchy resolution | Complete (21 tests) |
| 3.1.E4 | Classifier tests | `tests/unit/test_classifier.py` | Test classification logic | Complete (20 tests) |
| 3.1.E5 | CRM tests | `tests/unit/crr/test_crr_crm.py` | Test CRM processor | Not Started |
| 3.1.E6 | SA tests | `tests/unit/crr/test_crr_sa.py` | Test SA calculator | Not Started |
| 3.1.E7 | IRB tests | `tests/unit/crr/test_crr_irb.py` | Test IRB calculator | Not Started |
| 3.1.E8 | Slotting tests | `tests/unit/crr/test_crr_slotting.py` | Test slotting calculator | Not Started |
| 3.1.E9 | Pipeline tests | `tests/unit/test_pipeline.py` | Test full pipeline | Not Started |

#### Implementation Notes for 3.1.C

**3.1.C1 Data Loader:**
- Implement `LoaderProtocol` from `contracts/protocols.py`
- Load from fixture parquet files: loans, counterparties, collateral, guarantees, provisions, ratings, mappings
- Return `RawDataBundle` with all LazyFrames
- Validate schemas using `validation.py`

**3.1.C2 Hierarchy Resolver:**
- Implement `HierarchyResolverProtocol`
- Resolve counterparty org hierarchy (parent-child relationships)
- Inherit ratings from parents where child is unrated
- Resolve facility-to-exposure mappings
- Calculate lending group total exposure for retail threshold
- Return `ResolvedHierarchyBundle`

**3.1.C3 Exposure Classifier:**
- Implement `ClassifierProtocol`
- Map counterparty type to exposure class using `ExposureClass` enum
- Determine approach (SA, F-IRB, A-IRB, slotting) based on config permissions
- Check SME criteria (turnover < £44m for UK / €50m for EU)
- Check retail criteria (< £880k aggregate)
- Return `ClassifiedExposuresBundle` with separate SA/IRB/slotting frames

**3.1.C4 CRM Processor:**
- Implement `CRMProcessorProtocol`
- Apply CCFs to undrawn commitments
- Calculate adjusted collateral value (with haircuts)
- Handle maturity mismatch and currency mismatch
- Apply guarantee substitution
- Deduct provisions from EAD
- Return `CRMAdjustedBundle`

**3.1.C5 SA Calculator:**
- Implement `SACalculatorProtocol`
- Lookup risk weights by exposure class and CQS
- Handle UK deviations (30% for institutions CQS2)
- Apply LTV-based weights for real estate
- Apply SME supporting factor (tiered: 0.7619/0.85)
- Apply infrastructure factor (0.75)
- Return `SAResultBundle`

**3.1.C6 IRB Calculator:**
- Implement `IRBCalculatorProtocol`
- Apply PD floor (0.03% for CRR)
- Use supervisory LGD for F-IRB (45%/75%)
- Calculate correlation using `correlation.py`
- Apply maturity adjustment
- Calculate K using IRB formula
- Apply 1.06 scaling factor (CRR-specific)
- Return `IRBResultBundle`

**3.1.C7 Slotting Calculator:**
- Implement `SlottingCalculatorProtocol`
- Map slotting category to risk weight
- Handle HVCRE/non-HVCRE distinction
- Return `SlottingResultBundle`

**3.1.C8 Output Aggregator:**
- Implement `OutputAggregatorProtocol`
- Combine SA + IRB + Slotting results
- Calculate totals by exposure class
- Generate audit trail
- Return `AggregatedResultBundle`

**3.1.C9 Pipeline Orchestrator:**
- Implement `PipelineProtocol`
- Wire all stages together
- Handle errors from each stage
- Collect validation warnings
- Return final `AggregatedResultBundle`

### 3.2 Basel 3.1 Extension

After CRR is complete, extend for Basel 3.1. The protocol-based architecture allows most components to be reused with different configuration.

| Step | Component | Description | Status |
|------|-----------|-------------|--------|
| 3.2.1 | B3.1 risk weight tables | CRE20 revised tables with LTV bands | Not Started |
| 3.2.2 | B3.1 CCF tables | Revised CCFs (40% for commitments) | Not Started |
| 3.2.3 | B3.1 CRM haircuts | CRE22 revised haircuts | Not Started |
| 3.2.4 | B3.1 classifier updates | Restricted IRB scope, equity exclusions | Not Started |
| 3.2.5 | B3.1 PD floors | Differentiated floors (0.03%/0.05%/0.10%) | Not Started |
| 3.2.6 | B3.1 LGD floors | A-IRB LGD floors (0%-25%) | Not Started |
| 3.2.7 | B3.1 slotting | CRE33 revised weights (50%/70%/100%) | Not Started |
| 3.2.8 | Output floor calculator | 72.5% floor with transitional schedule | Not Started |
| 3.2.9 | B3.1 pipeline config | Use `CalculationConfig.basel_3_1()` | Not Started |

### 3.3 Reporting & Workbooks

| Step | Component | Description | Status |
|------|-----------|-------------|--------|
| 3.3.1 | CRR workbook | Marimo notebook for CRR calculations | Not Started |
| 3.3.2 | B3.1 workbook | Marimo notebook for Basel 3.1 | Not Started |
| 3.3.3 | Comparison workbook | CRR vs B3.1 impact analysis | Not Started |
| 3.3.4 | COREP generator | Regulatory reporting templates | Not Started |
| 3.3.5 | PRA CAP+ generator | UK reporting | Not Started |

---

## Phase 4: Testing Strategy

### 4.1 Test Pyramid

```
                    ┌─────────────────┐
                    │   Acceptance    │  ← Phase 1 scenarios
                    │     Tests       │     (E2E, slow)
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │        Contract Tests       │  ← Phase 2 contracts
              │    (Integration, medium)    │     (Component boundaries)
              └──────────────┬──────────────┘
                             │
    ┌────────────────────────┴────────────────────────┐
    │                   Unit Tests                    │  ← Phase 3 implementation
    │           (Fast, isolated, many)                │     (Individual functions)
    └─────────────────────────────────────────────────┘
```

### 4.2 Test File Structure

```
tests/
├── acceptance/
│   ├── crr/
│   │   ├── test_scenario_crr_a_sa.py
│   │   ├── test_scenario_crr_b_firb.py
│   │   ├── test_scenario_crr_c_airb.py
│   │   ├── test_scenario_crr_d_crm.py
│   │   ├── test_scenario_crr_e_slotting.py
│   │   ├── test_scenario_crr_f_supporting_factors.py
│   │   ├── test_scenario_crr_g_provisions.py
│   │   └── test_scenario_crr_h_complex.py
│   └── basel31/
│       ├── test_scenario_b31_a_sa.py
│       ├── test_scenario_b31_b_firb.py
│       ├── test_scenario_b31_c_airb.py
│       ├── test_scenario_b31_d_crm.py
│       ├── test_scenario_b31_e_slotting.py
│       ├── test_scenario_b31_f_output_floor.py
│       ├── test_scenario_b31_g_provisions.py
│       └── test_scenario_b31_h_complex.py
├── contracts/
│   ├── test_loader_contract.py
│   ├── test_hierarchy_contract.py
│   ├── test_classification_contract.py
│   ├── test_crm_contract.py
│   ├── test_sa_contract.py
│   └── test_irb_contract.py
├── unit/
│   ├── crr/
│   │   ├── test_crr_risk_weights.py
│   │   ├── test_crr_ccf.py
│   │   ├── test_crr_haircuts.py
│   │   ├── test_crr_supporting_factors.py
│   │   └── test_crr_classification.py
│   ├── basel31/
│   │   ├── test_b31_risk_weights.py
│   │   ├── test_b31_ltv_bands.py
│   │   ├── test_b31_pd_floors.py
│   │   ├── test_b31_lgd_floors.py
│   │   └── test_b31_output_floor.py
│   └── common/
│       ├── test_hierarchy_builders.py
│       ├── test_irb_formulas.py
│       └── test_provisions.py
├── fixtures/
│   └── ... (existing test data)
└── expected_outputs/
    ├── crr/
    │   └── expected_rwa_crr.parquet
    └── basel31/
        └── expected_rwa_b31.parquet
```

---

## Phase 5: Workbook Structure

### 5.1 CRR Workbook

```
workbooks/
├── crr_rwa_calculator/
│   ├── main.py                    # Main orchestrator
│   ├── data/
│   │   ├── fixture_loader.py      # Shared loader
│   │   └── crr_params.py          # CRR regulatory parameters
│   ├── calculations/
│   │   ├── crr_risk_weights.py    # CRR SA risk weights
│   │   ├── crr_ccf.py             # CRR CCF tables
│   │   ├── crr_haircuts.py        # CRR CRM haircuts
│   │   ├── crr_supporting_factors.py  # SME, infrastructure
│   │   └── irb_formulas.py        # Shared IRB formulas
│   └── scenarios/
│       ├── group_crr_a_sa.py
│       ├── group_crr_b_firb.py
│       ├── group_crr_c_airb.py
│       ├── group_crr_d_crm.py
│       ├── group_crr_e_slotting.py
│       ├── group_crr_f_supporting_factors.py
│       ├── group_crr_g_provisions.py
│       └── group_crr_h_complex.py
```

### 5.2 Basel 3.1 Workbook

```
workbooks/
├── basel31_rwa_calculator/
│   ├── main.py
│   ├── data/
│   │   ├── fixture_loader.py
│   │   └── b31_params.py          # Basel 3.1 regulatory parameters
│   ├── calculations/
│   │   ├── b31_risk_weights.py    # Basel 3.1 SA risk weights
│   │   ├── b31_ltv_bands.py       # Granular LTV treatment
│   │   ├── b31_ccf.py             # Basel 3.1 CCF tables
│   │   ├── b31_haircuts.py        # Basel 3.1 CRM haircuts
│   │   ├── b31_pd_floors.py       # Differentiated PD floors
│   │   ├── b31_lgd_floors.py      # A-IRB LGD floors
│   │   ├── output_floor.py        # Output floor logic
│   │   └── irb_formulas.py        # Shared IRB formulas
│   └── scenarios/
│       ├── group_b31_a_sa.py
│       ├── group_b31_b_firb.py
│       ├── group_b31_c_airb.py
│       ├── group_b31_d_crm.py
│       ├── group_b31_e_slotting.py
│       ├── group_b31_f_output_floor.py
│       ├── group_b31_g_provisions.py
│       └── group_b31_h_complex.py
```

### 5.3 Comparison Workbook

```
workbooks/
├── framework_comparison/
│   ├── main.py                    # Side-by-side comparison
│   ├── impact_analysis.py         # CRR vs B3.1 RWA impact
│   └── transition_planning.py     # Transition period analysis
```

---

## Appendix A: CRR Regulatory Parameters

### CRR SA Risk Weights (Art. 112-134)

#### Sovereigns (Art. 114)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 0% |
| 2 | 20% |
| 3 | 50% |
| 4-5 | 100% |
| 6 | 150% |
| Unrated | 100% |

#### Institutions (Art. 120-121)

**ECRA (External Credit Rating Approach):**

| CQS | Risk Weight | UK Deviation |
|-----|-------------|--------------|
| 1 | 20% | 20% |
| 2 | 50% | **30%** |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% (CQS2 of sovereign) | 40% |

#### Corporates (Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 150% |
| 6 | 150% |
| Unrated | 100% |

#### Retail (Art. 123)

- Standard retail: 75%
- Must meet criteria in Art. 123

#### Real Estate (Art. 125-126)

**Residential (Art. 125):**
- LTV ≤80%: 35%
- LTV >80%: Split treatment (35% on 80%, 75% on excess)

**Commercial (Art. 126):**
- LTV ≤50%: 50% (where rental income >1.5x interest)
- Otherwise: 100%

### CRR CCFs (Art. 111)

| Category | CCF |
|----------|-----|
| Full risk | 100% |
| Medium risk | 50% |
| Medium-low risk | 20% |
| Low risk | 0% |

### CRR Supervisory Haircuts (Art. 224)

| Collateral Type | Haircut |
|-----------------|---------|
| Cash | 0% |
| CQS 1 govt bonds ≤1y | 0.5% |
| CQS 1 govt bonds 1-5y | 2% |
| CQS 1 govt bonds >5y | 4% |
| Main index equity | 15% |
| Other equity | 25% |
| Currency mismatch | +8% |

### CRR F-IRB LGDs

| Collateral Type | LGD |
|-----------------|-----|
| Unsecured senior | 45% |
| Subordinated | 75% |
| Financial collateral | 0% |
| Receivables | 35% |
| Commercial/residential RE | 35% |

---

## Appendix B: Key Test Data References

### Test Data to Scenario Mapping (Updated for Dual Framework)

| Fixture ID | CRR Scenario | Basel 3.1 Scenario | Purpose |
|------------|--------------|-------------------|---------|
| SOV_UK_001 | CRR-A1 | B31-A1 | UK Sovereign 0% RW |
| CORP_UR_001 | CRR-A2 | B31-A2 | Unrated corporate |
| CORP_UK_003 | CRR-A3 | B31-A3 | Rated corporate CQS2 |
| INST_UK_003 | CRR-A4 | B31-A4 | Institution 30% UK |
| RTL_MTG_001 | CRR-A5 | B31-A5 | Mortgage 60% LTV |
| RTL_MTG_002 | CRR-A6 | B31-A6 | Mortgage 85% LTV |
| CORP_SME_001 | CRR-A10 | B31-A10 | SME (factor vs no factor) |
| COLL_CASH_001 | CRR-D1 | B31-D1 | Cash collateral |
| GUAR_BANK_001 | CRR-D4 | B31-D4 | Bank guarantee |

---

## Next Steps

### Completed
- [x] Create test fixtures directory structure
- [x] Implement counterparty fixtures
- [x] Implement exposure fixtures
- [x] Implement CRM fixtures
- [x] Implement ratings fixtures
- [x] Implement mapping fixtures
- [x] Restructure plan for CRR-first approach
- [x] Create CRR workbook structure (`workbooks/crr_expected_outputs/`)
- [x] Implement CRR regulatory parameter tables
- [x] Implement shared IRB formulas with 1.06 scaling factor
- [x] Implement correlation calculation with SME firm size adjustment
- [x] Implement CRR SA risk weights (Art. 112-134)
- [x] Implement CRR CCF tables (Art. 111)
- [x] Implement CRR SME supporting factor - tiered approach (CRR2 Art. 501)
- [x] Implement CRR infrastructure supporting factor (Art. 501a)
- [x] Create CRR-A (SA) scenarios (12 scenarios)
- [x] Create CRR-B (F-IRB) scenarios (7 scenarios - wholesale only)
- [x] Create CRR-C (A-IRB) scenarios (3 scenarios)
- [x] Create CRR-D (CRM) scenarios (6 scenarios)
- [x] Create CRR-E (Slotting) scenarios (4 scenarios)
- [x] Create CRR-F (Supporting Factors) scenarios (7 scenarios)
- [x] Create CRR-G (Provisions) scenarios (3 scenarios)
- [x] Create CRR-H (Complex/Combined) scenarios (4 scenarios)
- [x] Generate expected output files (CSV, JSON, Parquet)
- [x] Create fixture loader for Marimo workbooks
- [x] Create pytest acceptance tests for CRR scenarios (45 scenarios, 83 total tests)
- [x] Integrate all scenario groups into main workbook output generator
- [x] **Phase 2**: Define process contracts (domain enums, bundles, config, protocols, validation)
- [x] **Phase 2**: Create contract tests (97 tests passing)
- [x] **Phase 2**: Add intermediate pipeline schemas to `data/schemas.py`
- [x] **Phase 2**: Add `py.typed` marker for PEP 561 compliance

### In Progress
- [ ] **Phase 3.1.C**: Engine Layer - Pipeline stages

### Completed (Phase 3.1.B - Data Layer)
- [x] Create `src/rwa_calc/data/tables/` directory structure
- [x] Implement CRR risk weight tables (`crr_risk_weights.py`)
- [x] Implement CRR CCF tables (`crr_ccf.py`)
- [x] Implement CRR CRM haircuts (`crr_haircuts.py`)
- [x] Implement CRR slotting tables (`crr_slotting.py`)
- [x] Implement F-IRB supervisory LGDs (`crr_firb_lgd.py`)
- [x] Create unit tests for data tables (77 tests passing)

### Up Next (CRR Priority - Ordered by Dependency)

**Phase 3.1.C - Engine Layer (in dependency order):**
1. [x] Implement Data Loader (`engine/loader.py`) - `LoaderProtocol` - Complete (35 tests)
2. [x] Implement Hierarchy Resolver (`engine/hierarchy.py`) - `HierarchyResolverProtocol` - Complete (21 tests)
3. [x] Implement Exposure Classifier (`engine/classifier.py`) - `ClassifierProtocol` - Complete (20 tests)
4. [ ] Implement CRM Processor (`engine/crm/processor.py`) - `CRMProcessorProtocol`
5. [ ] Implement SA Calculator (`engine/sa/calculator.py`) - `SACalculatorProtocol`
6. [ ] Implement IRB Calculator (`engine/irb/calculator.py`) - `IRBCalculatorProtocol`
7. [ ] Implement Slotting Calculator (`engine/slotting/calculator.py`) - `SlottingCalculatorProtocol`
8. [ ] Implement Output Aggregator (`engine/aggregator.py`) - `OutputAggregatorProtocol`
9. [ ] Implement Pipeline Orchestrator (`engine/pipeline.py`) - `PipelineProtocol`

**Phase 3.1.D - Supporting Modules:**
1. [ ] IRB Formulas (`engine/irb/formulas.py`)
2. [ ] Correlation (`engine/irb/correlation.py`)
3. [ ] CRM Haircuts (`engine/crm/haircuts.py`)
4. [ ] CCF Calculator (`engine/crm/ccf.py`)
5. [ ] Supporting Factors (`engine/sa/supporting_factors.py`)

**Phase 3.1.E - Unit Tests (TDD alongside implementation):**
1. [x] Data table tests (77 tests)
2. [x] Loader tests (35 tests)
3. [x] Hierarchy tests (21 tests)
4. [x] Classifier tests (20 tests)
5. [ ] CRM tests
6. [ ] SA tests
7. [ ] IRB tests
8. [ ] Slotting tests
9. [ ] Pipeline tests

**Phase 3.1.F - Acceptance Test Activation:**
1. [ ] Remove `pytest.skip` markers as components are implemented
2. [ ] All 45 CRR acceptance tests passing

**Phase 3.1.G - Performance Benchmarks:**
1. [ ] Set up pytest-benchmark infrastructure
2. [ ] Implement synthetic data generators for scale testing
3. [ ] Create hierarchy resolver benchmarks (100K, 1M, 10M counterparties)
4. [ ] Add memory profiling benchmarks
5. [ ] Configure CI/CD benchmark workflow (nightly/on-merge)

---

## Phase 3.G: Performance Benchmarks

### Overview

Performance is critical for production RWA calculations. This phase establishes benchmark testing infrastructure to:
- Detect performance regressions early
- Validate scalability to production data volumes
- Track memory usage for large datasets

### Tool Selection: pytest-benchmark

**Why pytest-benchmark:**
- Seamless integration with existing pytest infrastructure
- Pedantic mode for long-running tests (10M+ records)
- Statistical analysis (mean, std, min, max, IQR)
- JSON export for CI/CD comparison
- Regression detection with threshold failures

### 3.G.1 Infrastructure Setup

| Step | Task | Location | Status |
|------|------|----------|--------|
| 3.G.1.1 | Add pytest-benchmark dependency | `pyproject.toml` | Not Started |
| 3.G.1.2 | Configure default benchmark settings | `pyproject.toml` | Not Started |
| 3.G.1.3 | Create benchmark test directory | `tests/benchmarks/` | Not Started |
| 3.G.1.4 | Add benchmark conftest.py | `tests/benchmarks/conftest.py` | Not Started |
| 3.G.1.5 | Create data generators module | `tests/benchmarks/data_generators.py` | Not Started |

### 3.G.2 Synthetic Data Generators

Efficient generators using numpy vectorized operations:

```python
# tests/benchmarks/data_generators.py
def generate_counterparties(n: int, hierarchy_depth: int = 4) -> pl.LazyFrame
def generate_org_mappings(counterparties: pl.LazyFrame, depth: int = 4) -> pl.LazyFrame
def generate_loans(counterparties: pl.LazyFrame, per_counterparty: int = 3) -> pl.LazyFrame
def generate_facility_mappings(loans: pl.LazyFrame) -> pl.LazyFrame
def generate_ratings(counterparties: pl.LazyFrame, rated_pct: float = 0.7) -> pl.LazyFrame
```

### 3.G.3 Hierarchy Resolver Benchmarks

| Scale | Counterparties | Loans | Org Mappings | Target Time | Status |
|-------|----------------|-------|--------------|-------------|--------|
| 100K | 100,000 | 300,000 | ~95,000 | < 5s | Not Started |
| 1M | 1,000,000 | 3,000,000 | ~950,000 | < 60s | Not Started |
| 10M | 10,000,000 | 30,000,000 | ~9,500,000 | < 10min | Not Started |

**Test Structure:**
```
tests/benchmarks/
├── __init__.py
├── conftest.py                    # Benchmark fixtures, skip markers
├── data_generators.py             # Synthetic data generation
├── test_hierarchy_benchmark.py    # Hierarchy resolver benchmarks
├── test_classifier_benchmark.py   # Classifier benchmarks (later)
├── test_crm_benchmark.py          # CRM processor benchmarks (later)
├── test_pipeline_benchmark.py     # Full pipeline benchmarks (later)
└── test_memory_benchmark.py       # Memory usage tracking
```

**Benchmark Categories:**
1. **Component benchmarks** - Individual methods (e.g., `_build_parent_lookups`)
2. **Integration benchmarks** - Full `resolve()` method
3. **Memory benchmarks** - Peak memory usage tracking
4. **Throughput benchmarks** - Records processed per second

### 3.G.4 Configuration

**pyproject.toml additions:**
```toml
[tool.pytest.ini_options]
addopts = "-v --tb=short --benchmark-skip"  # Skip benchmarks by default
markers = [
    "benchmark: mark test as a benchmark",
    "slow: mark test as slow (10M+ scale)",
]

[tool.pytest-benchmark]
benchmark_disable_gc = true
benchmark_warmup = "on"
benchmark_min_rounds = 3
```

**Running benchmarks:**
```bash
# Run all benchmarks
uv run pytest tests/benchmarks/ --benchmark-only

# Run specific scale
uv run pytest tests/benchmarks/ -k "100k" --benchmark-only

# Compare against baseline
uv run pytest tests/benchmarks/ --benchmark-only --benchmark-compare=baseline

# Save new baseline
uv run pytest tests/benchmarks/ --benchmark-only --benchmark-save=baseline

# Fail if regression > 15%
uv run pytest tests/benchmarks/ --benchmark-only --benchmark-compare-fail=min:15%
```

### 3.G.5 CI/CD Integration

**GitHub Actions workflow** (`.github/workflows/benchmark.yml`):
- Triggered on: merge to main, nightly schedule, manual dispatch
- Timeout: 60 minutes
- Saves results as artifacts
- Comments on PR if regression detected
- Fails build if regression > 15%

### 3.G.6 Memory Profiling

Using `tracemalloc` for cross-platform memory tracking:
- Track peak memory during hierarchy resolution
- Log memory per 100K counterparties
- Alert if memory exceeds thresholds

**Memory targets:**
| Scale | Peak Memory Target |
|-------|-------------------|
| 100K | < 500 MB |
| 1M | < 4 GB |
| 10M | < 32 GB |

### 3.G.7 Implementation Order

1. **First:** Hierarchy resolver benchmarks (most critical for performance)
2. **Second:** Full pipeline benchmarks
3. **Third:** Individual component benchmarks (classifier, CRM, calculators)
4. **Fourth:** Memory profiling benchmarks

### Later (Basel 3.1)
1. **Phase 1.2B**: Create Basel 3.1 acceptance test shells
2. **Phase 3.2**: Extend for Basel 3.1 (differentiated PD/LGD floors, no 1.06 factor, output floor)
3. **Phase 3.2**: Basel 3.1 Marimo workbook
4. **Phase 3.3**: Framework comparison workbook

---

## Fixture Generator Commands

To regenerate all fixtures:
```bash
uv run python tests/fixtures/generate_all.py
```
