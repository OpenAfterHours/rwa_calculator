# UK Credit Risk RWA Calculator

A high-performance Risk-Weighted Assets (RWA) calculator for UK credit risk, supporting both current regulations and future Basel 3.1 implementation. Built with Python using Polars for vectorized performance.

## Regulatory Scope

This calculator supports two regulatory regimes:

| Regime | Effective Period | UK Implementation | Status |
|--------|------------------|-------------------|--------|
| **CRR (Basel 3.0)** | Until 31 December 2026 | UK CRR (EU 575/2013 as onshored) | **Active Development** |
| **Basel 3.1** | From 1 January 2027 | PRA PS9/24 | Planned |

A configuration toggle allows switching between calculation modes, enabling:
- Current regulatory reporting under UK CRR
- Impact analysis and parallel running ahead of Basel 3.1 go-live
- Seamless transition when Basel 3.1 becomes effective

---

## Development Status

The project follows a **phased, test-first approach** prioritising CRR (Basel 3.0) implementation before extending to Basel 3.1.

### Phase 1: Test Infrastructure - COMPLETE

| Component | Status | Details |
|-----------|--------|---------|
| Test Data Fixtures | Complete | 15 fixture types covering all counterparty, exposure, CRM, and mapping scenarios |
| CRR Expected Outputs | Complete | 45 scenarios across 8 groups (SA, F-IRB, A-IRB, CRM, Slotting, Supporting Factors, Provisions, Complex) |
| CRR Acceptance Tests | Complete | 83 tests (38 validation, 45 implementation stubs) |
| Basel 3.1 Expected Outputs | Not Started | Planned for Phase 1.2B |

### Phase 2: Process Contracts - IN PROGRESS

Defining interfaces between components (loader, hierarchy, classification, CRM, SA, IRB) to enable isolated testing and parallel development.

### Phase 3: Implementation - NOT STARTED

| Component | CRR Status | Basel 3.1 Status |
|-----------|------------|------------------|
| Domain enums | Not Started | Not Started |
| Risk weight tables | Not Started | Not Started |
| CCF tables | Not Started | Not Started |
| CRM processor | Not Started | Not Started |
| SA calculator | Not Started | Not Started |
| IRB calculator | Not Started | Not Started |
| Output floor | N/A | Not Started |
| Orchestrator | Not Started | Not Started |

### CRR Workbook Components - COMPLETE

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

## Key Differences Between Regimes

| Area | CRR (Basel 3.0) | Basel 3.1 (PRA PS9/24) |
|------|-----------------|------------------------|
| **1.06 Scaling Factor** | **Applies to ALL IRB RWA** | Removed |
| **Output Floor** | None | 72.5% of SA RWA |
| **IRB Scope** | All exposure classes permitted | Excludes central govt, equity, large corporates (>EUR 500m), CIUs |
| **PD Floors** | 0.03% (single floor) | Differentiated: 0.03% corp, 0.05% retail, 0.10% QRRE |
| **LGD Floors (A-IRB)** | None | 0%-25% by collateral type |
| **SME Supporting Factor** | Tiered: 0.7619 (<=EUR 2.5m) / 0.85 (>EUR 2.5m) | Withdrawn |
| **Infrastructure Factor** | 0.75 (flat) | Withdrawn |
| **Retail Threshold** | EUR 1m aggregate exposure | GBP 880k aggregate exposure |
| **SA Risk Weights** | CRR Part Three, Title II | Revised tables (granular LTV bands) |
| **Real Estate** | Whole loan approach | Split by LTV bands, ADC treatment |
| **Slotting (Strong)** | 70% RW | 50% RW (differentiated from Good) |

---

## CRR Implementation Details

### EUR to GBP Conversion

CRR specifies regulatory thresholds in EUR. For UK implementation, these are converted to GBP using a configurable exchange rate.

**Configuration:** `src/rwa_calc/config/fx_rates.py`

```python
EUR_GBP_RATE = Decimal("0.88")  # 1 EUR = 0.88 GBP
```

| Threshold | EUR (Regulatory) | GBP (Derived) |
|-----------|------------------|---------------|
| SME Exposure Threshold | EUR 2,500,000 | GBP 2,200,000 |
| SME Turnover Threshold | EUR 50,000,000 | GBP 44,000,000 |

To update the rate, modify `EUR_GBP_RATE` in the config file. All dependent GBP thresholds will automatically reflect the new rate.

**Note:** Basel 3.1 (PRA PS9/24) specifies thresholds directly in GBP, so FX conversion is not required for Basel 3.1 calculations.

### CRR SME Supporting Factor (Tiered Approach)

Per CRR2 Art. 501, the SME supporting factor uses a tiered structure:

- **Tier 1:** Exposures up to EUR 2.5m: factor of 0.7619 (23.81% RWA reduction)
- **Tier 2:** Exposures above EUR 2.5m: factor of 0.85 (15% RWA reduction)

**Formula:**
```
effective_factor = [min(E, threshold) x 0.7619 + max(E - threshold, 0) x 0.85] / E
```

This tiered approach means smaller SME exposures get proportionally more capital relief than larger exposures.

### CRR IRB 1.06 Scaling Factor

CRR applies a **1.06 scaling factor** to all IRB risk-weighted assets (Art. 153(1)). This factor was introduced in Basel II and retained in CRR.

```
CRR:      RWA = K x 12.5 x 1.06 x EAD x MA
Basel 3.1: RWA = K x 12.5 x EAD x MA
```

Impact: IRB RWA is 6% higher under CRR compared to the base formula.

---

## Overview

The calculator implements the full credit risk framework for both regimes as adopted by the UK Prudential Regulation Authority (PRA). It supports both Standardised Approach (SA) and Internal Ratings-Based (IRB) approaches with full Credit Risk Mitigation (CRM) capabilities.

### Key Features

- **Dual Regulatory Compliance**: Full support for UK CRR (Basel 3.0) and PRA PS9/24 (Basel 3.1) with UK-specific deviations
- **High Performance**: Polars-native vectorized calculations - no row-by-row iteration - utilising LazyFrame optimisations
- **Dual Approach Support**: Both Standardised (SA) and IRB (F-IRB & A-IRB) approaches
- **Complete CRM**: Collateral at counterparty/facility/loan level with supervisory haircuts and RWA-optimized allocation
- **Provisions/Impairments**: Full IFRS 9 ECL integration with EL comparison for IRB
- **Complex Hierarchies**: Support for multi-level exposure and counterparty hierarchies
- **Dynamic Classification**: Exposure class and approach determined from counterparty attributes
- **Audit Trail**: Full calculation transparency for regulatory review

### Project Structure

```
rwa_calculator/
├── src/rwa_calc/
│   ├── config/                         # Configuration
│   │   └── fx_rates.py                 # EUR/GBP FX rate configuration
│   ├── domain/                         # Core domain models
│   │   └── enums.py                    # ExposureClass, ApproachType, CQS, etc.
│   ├── data/                           # Data loading & schemas
│   │   ├── results.py                  # DataFrame-based calculation results
│   │   ├── loaders.py                  # File, DuckDB, InMemory loaders
│   │   └── schemas.py                  # Polars schemas
│   ├── engine/                         # Vectorized calculation engines
│   │   ├── orchestrator.py             # Main calculation pipeline
│   │   ├── hierarchy_counterparty.py   # Counterparty hierarchy operations
│   │   ├── hierarchy_exposure.py       # Exposure hierarchy operations
│   │   ├── classification.py           # Exposure class & approach determination
│   │   ├── sa/                         # Standardised Approach
│   │   │   ├── basel_3_calculator.py   # CRR SA calculator
│   │   │   └── basel_31_calculator.py  # Basel 3.1 SA calculator
│   │   ├── irb/                        # IRB Approach
│   │   │   ├── basel_3_calculator.py   # CRR IRB calculator
│   │   │   └── basel_31_calculator.py  # Basel 3.1 IRB calculator
│   │   ├── crm/                        # Credit Risk Mitigation
│   │   │   └── processor.py            # Haircuts, eligibility, substitution
│   │   └── provisions.py               # Provisions & Impairments
│   ├── reporting/                      # Output generation
│   │   ├── pra/                        # CAP+
│   │   └── corep/                      # COREP templates
│   └── ui/                             # Frontend + Marimo workbooks
│
├── workbooks/                          # Reference implementations
│   ├── shared/                         # Common utilities
│   │   ├── fixture_loader.py           # Test data loader
│   │   ├── irb_formulas.py             # IRB K calculation
│   │   └── correlation.py              # Asset correlation
│   ├── crr_expected_outputs/           # CRR (Basel 3.0) workbook
│   │   ├── data/
│   │   │   └── crr_params.py           # CRR regulatory parameters
│   │   ├── calculations/
│   │   │   ├── crr_risk_weights.py     # SA risk weights
│   │   │   ├── crr_ccf.py              # Credit conversion factors
│   │   │   ├── crr_haircuts.py         # CRM haircuts
│   │   │   ├── crr_supporting_factors.py
│   │   │   └── crr_irb.py              # CRR IRB wrapper
│   │   └── scenarios/                  # Expected output scenarios
│   │       ├── group_crr_a_sa.py       # SA scenarios
│   │       ├── group_crr_b_firb.py     # F-IRB scenarios
│   │       ├── group_crr_c_airb.py     # A-IRB scenarios
│   │       ├── group_crr_d_crm.py      # CRM scenarios
│   │       ├── group_crr_e_slotting.py # Slotting scenarios
│   │       ├── group_crr_f_supporting_factors.py
│   │       ├── group_crr_g_provisions.py
│   │       └── group_crr_h_complex.py  # Complex/combined
│   └── basel31_expected_outputs/       # Basel 3.1 workbook (planned)
│
├── tests/
│   ├── acceptance/
│   │   ├── crr/                        # CRR acceptance tests
│   │   │   ├── test_scenario_crr_a_sa.py
│   │   │   ├── test_scenario_crr_b_firb.py
│   │   │   └── ... (8 test files)
│   │   └── basel31/                    # Basel 3.1 acceptance tests (planned)
│   ├── fixtures/                       # Test data generators
│   │   ├── counterparty/               # Sovereign, institution, corporate, retail
│   │   ├── exposures/                  # Facilities, loans, contingents
│   │   ├── collateral/                 # Cash, bonds, equity, RE
│   │   ├── guarantee/                  # Guarantees
│   │   ├── provision/                  # IFRS 9 provisions
│   │   ├── ratings/                    # External/internal ratings
│   │   └── mapping/                    # Org and lending hierarchies
│   └── expected_outputs/
│       ├── crr/                        # CRR expected outputs
│       │   ├── expected_rwa_crr.csv
│       │   ├── expected_rwa_crr.json
│       │   └── expected_rwa_crr.parquet
│       └── basel31/                    # Basel 3.1 expected outputs (planned)
│
└── ref_docs/                           # Regulatory reference documents
```

---

## CRR Acceptance Test Scenarios

### Scenario Groups

| Group | Description | Scenarios | Status |
|-------|-------------|-----------|--------|
| CRR-A | Standardised Approach | 12 | Complete |
| CRR-B | Foundation IRB | 7 | Complete |
| CRR-C | Advanced IRB | 3 | Complete |
| CRR-D | Credit Risk Mitigation | 6 | Complete |
| CRR-E | Specialised Lending (Slotting) | 4 | Complete |
| CRR-F | Supporting Factors | 7 | Complete |
| CRR-G | Provisions & Impairments | 3 | Complete |
| CRR-H | Complex/Combined | 4 | Complete |

### Running Tests

```bash
# Run all CRR acceptance tests
uv run pytest tests/acceptance/crr/ -v

# Run specific scenario group
uv run pytest tests/acceptance/crr/test_scenario_crr_a_sa.py -v
```

**Test Results:**
- 38 validation tests PASS - Verify expected outputs structure
- 45 stub tests SKIP - Await production calculator implementation (Phase 3)

---

## How It Works

- Counterparty hierarchies allow for lending groups (for Retail classification) and org groups
(for parent ratings) to be calculated
- Facilities and loans are combined into a hierarchy internally
- Drawn amounts aggregate bottom-up from loans to facilities
- Undrawn amounts are calculated at the root facility level
- RWA is calculated on both drawn (loans) and undrawn (facilities) exposures
- Collateral is prorated to optimise RWA calculation
- Provisions are allocated to optimise the RWA calculation

## Counterparty Hierarchies

### Lending Groups (Retail Classification)

Used to determine retail eligibility based on aggregate group exposure:

```
Lending Group Lead
├── Counterparty A (exposure: £400k)
├── Counterparty B (exposure: £200k)
└── Sub-Group Lead
    └── Counterparty C (exposure: £150k)
Total: £750k - below £880k threshold, qualifies for retail treatment
```

- Exposure aggregated to root group level
- Threshold comparison determines retail eligibility (£880k per PRA PS9/24)
- No rating inheritance from lead

### Org Hierarchy (Rating & Turnover Inheritance)

Used for rating and SME classification:

```
Org Lead (CQS 2, turnover: £80M)
├── Subsidiary A (inherits CQS 2, £80M)
├── Subsidiary B (inherits CQS 2, £80M)
└── Sub-Org Lead (inherits CQS 2, £80M)
    └── Subsidiary C (inherits CQS 2, £80M)
```

- Rating cascades from root through entire hierarchy
- Turnover cascades for SME classification


## Exposure Hierarchy Model

The calculator uses a **facilities + loans** hierarchy model where:
- **Facilities** define committed credit limits (parent nodes)
- **Loans** represent actual drawings (leaf nodes)

### Data Model

Facilities and loans are loaded as separate files and combined internally:

```yaml
# rwa_config.yaml
data_paths:
  facilities: "data/{period}/facilities.parquet"   # Required
  loans: "data/{period}/loans.parquet"             # Required
  counterparties: "data/{period}/counterparties.parquet"
```

The hierarchy supports unlimited nesting:

```
Master Facility (committed: £10M)
├── Sub-Facility A (committed: £6M)
│   ├── Loan A1 (drawn: £2M)
│   └── Loan A2 (drawn: £1.5M)
└── Sub-Facility B (committed: £4M)
    └── Loan B1 (drawn: £3M)
```

### Reporting View Output

The `extract_reporting_view()` function produces a flattened view for RWA calculation with **both facilities and loans**:

| external_id | node_type | drawn_amount | undrawn_amount |
|-------------|-----------|--------------|----------------|
| MASTER_FAC  | facility  | 0            | £3.5M          |
| LOAN_A1     | loan      | £2M          | 0              |
| LOAN_A2     | loan      | £1.5M        | 0              |
| LOAN_B1     | loan      | £3M          | 0              |

**Key principles:**
- **Root facilities** carry the undrawn exposure (committed minus total drawn)
- **Loans** carry the drawn exposure
- RWA is calculated on both drawn and undrawn portions separately
- Intermediate sub-facilities are excluded from the reporting view (their committed amounts are reflected in the root facility's undrawn)

### Amount Calculation

- **Drawn amounts**: Aggregated bottom-up from loans to facilities
- **Undrawn amounts**: Calculated at root facility level as `committed - aggregated_drawn`
- **Risk parameters**: Inherited top-down (exposure_class, pd, lgd, cqs)


## Credit Risk Mitigation

Collateral can be linked at three levels in the exposure hierarchy, providing flexibility in how security is allocated.

### Allocation Levels

| Level | Link Field | Behaviour |
|-------|------------|-----------|
| **Counterparty** | `counterparty_id` | Expands to all exposures of the counterparty |
| **Facility** | `facility_id` | Expands to facility + all descendant loans |
| **Loan** | `exposure_ids` | Direct allocation to specific exposures |

**Priority:** If multiple fields are populated, the most specific wins: `exposure_ids` > `facility_id` > `counterparty_id`

### Example: Counterparty-Level Collateral

**Setup:**
```
Counterparty: CPTY001
├── FAC001 (Master Facility, £0 drawn, £5M committed)
│   ├── LOAN_A (£2M drawn, RW=100%)
│   └── LOAN_B (£1M drawn, RW=50%)
└── FAC002 (Master Facility, £0 drawn, £2M committed)
    └── LOAN_C (£1.5M drawn, RW=75%)

Collateral: £2M cash linked to counterparty_id=CPTY001
```

**Allocation Result (RWA-optimized):**

| Exposure | Drawn | Risk Weight | Collateral Allocated | Net Exposure |
|----------|-------|-------------|---------------------|--------------|
| LOAN_A   | £2M   | 100%        | £2M (priority)      | £0           |
| LOAN_B   | £1M   | 50%         | £0                  | £1M          |
| LOAN_C   | £1.5M | 75%         | £0                  | £1.5M        |
| FAC001   | £0    | -           | £0                  | £0           |
| FAC002   | £0    | -           | £0                  | £0           |

**RWA Benefit:** £2M x 100% = **£2M RWA saved** (allocated to highest RW exposure first)

### Two-Pass Optimization

When collateral covers multiple exposures, the calculator uses a two-pass approach:

1. **Pass 1:** Calculate preliminary risk weights (without CRM)
2. **Pass 2:** Allocate collateral to highest risk-weight exposures first

This maximises capital benefit per Basel CRE22 guidance.


## Exposure Classification

Exposure class and approach are dynamically determined from counterparty attributes:

### Classification Logic

1. **SA Exposure Class** (determined in precedence order):
   TBC

2. **IRB Exposure Class** (for IRB-permitted exposures):
   - Corporates: Sub-classified by revenue threshold (£440m) and specialised lending criteria
   - Retail: Sub-classified by property security, QRRE criteria, and SME threshold (£0.88m)
   - **Note**: Central govs, Equity, CIUs must use SA (IRB withdrawn) for Basel 3.1

3. **Approach** (from IRB permissions + data availability):
   - A-IRB: Permitted + `has_internal_rating` + `has_internal_lgd`
   - F-IRB: Permitted + `has_internal_rating`
   - Standardised: Default fallback


## Provisions & Impairments

The calculator fully integrates IFRS 9 provisions/impairments into both SA and IRB calculations.

### SA Provisions (PRA PS9/24 Chapter 3)

For Standardised Approach exposures:

1. **Exposure Value Reduction**: Gross exposure is reduced by eligible provisions (SCRA + GCRA)
2. **Defaulted Exposure Risk Weight**: Based on SCRA coverage ratio
   - SCRA coverage >= 20% of unsecured portion -> **100% RW**
   - SCRA coverage < 20% of unsecured portion -> **150% RW**


### IRB Provisions (PRA PS9/24 Chapter 5)

For IRB exposures, provisions are compared to Expected Loss:

1. **Regulatory EL**: Calculated as `PD x LGD x EAD`
2. **EL Shortfall** (Provisions < EL): Deducted from CET1 capital
3. **EL Excess** (Provisions > EL): Added to Tier 2 capital (capped at 0.6% of IRB RWA)


### F-IRB Collateral-Based LGD (PRA PS9/24 Chapter 5)

For F-IRB exposures, supervisory LGD values depend on the collateral type securing the exposure:

| Collateral Type | Supervisory LGD |
|-----------------|-----------------|
| Cash, Gold, Securities | 0% |
| Receivables | 35% |
| Commercial/Residential RE | 35% |
| Other Physical | 40% |
| Unsecured | 45% |
| **Subordinated (any)** | **75%** |

When an exposure is partially secured, the effective LGD is blended:

```
effective_lgd = coverage x lgd_secured + (1 - coverage) x 45%
```

---

## Key Regulatory Parameters

### CRR (Basel 3.0) Parameters

| Parameter | Value | Reference |
|-----------|-------|-----------|
| **1.06 Scaling Factor** | Applies to all IRB | CRR Art. 153(1) |
| PD Floor (all classes) | 0.03% | CRR Art. 163 |
| F-IRB LGD (Unsecured) | 45% | CRR Art. 161 |
| F-IRB LGD (Subordinated) | 75% | CRR Art. 161 |
| SME Turnover Threshold | EUR 50m (GBP 44m) | CRR Art. 501 |
| SME Exposure Threshold | EUR 2.5m (GBP 2.2m) | CRR2 Art. 501 |
| SME Factor Tier 1 | 0.7619 | CRR2 Art. 501 |
| SME Factor Tier 2 | 0.85 | CRR2 Art. 501 |
| Infrastructure Factor | 0.75 | CRR Art. 501a |
| Institution CQS2 RW (UK) | 30% | UK deviation |
| FX Haircut | 8% | CRR Art. 224 |

### Basel 3.1 Parameters (PRA PS9/24)

| Parameter | Value | Reference |
|-----------|-------|-----------|
| **Output Floor** | 72.5% of SA equivalent | PS9/24 Ch. 6 |
| PD Floor (Corporate) | 0.03% | PS9/24 Ch. 5 |
| PD Floor (Retail) | 0.05% | PS9/24 Ch. 5 |
| PD Floor (QRRE) | 0.10% | PS9/24 Ch. 5 |
| LGD Floor (Senior Unsecured) | 25% | PS9/24 Ch. 5 |
| Institution CQS2 RW | 30% | PS9/24 Ch. 3.3 (UK deviation) |
| FX Haircut | 8% | PS9/24 Ch. 4 |
| Large Corporate Revenue | £440m | PS9/24 Ch. 5 |
| Retail SME Exposure | £0.88m | PS9/24 Ch. 5 |
| QRRE Max Individual Exposure | £90,000 | PS9/24 Ch. 5 |

### Output Floor Phase-In (Basel 3.1)

| Year | Floor % |
|------|---------|
| 2027 | 50% |
| 2028 | 55% |
| 2029 | 60% |
| 2030 | 65% |
| 2031 | 70% |
| 2032+ | 72.5% |

---

## SA Risk Weight Tables

### Sovereigns (CQS-based)
| CQS | 1 | 2 | 3 | 4 | 5 | 6 | Unrated |
|-----|---|---|---|---|---|---|---------|
| RW  | 0% | 20% | 50% | 100% | 100% | 150% | 100% |

### Institutions (ECRA)
| CQS | 1 | 2 | 3 | 4 | 5 | 6 | Unrated |
|-----|---|---|---|---|---|---|---------|
| RW  | 20% | 30%* | 50% | 100% | 100% | 150% | 50% |

*UK deviation from Basel 50%

### Residential Mortgages (Basel 3.1 LTV-based)
| LTV | <=50% | <=60% | <=70% | <=80% | <=90% | <=100% | >100% |
|-----|------|------|------|------|------|-------|-------|
| RW  | 20% | 25% | 30% | 35% | 40% | 50% | 70% |

### CRR Residential Mortgages (Simpler)
| LTV | <=80% | >80% |
|-----|-------|------|
| RW  | 35% | Split: 35% on 80%, 75% on excess |

---

## IRB Formula

The IRB capital requirement (K) is calculated as:

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

Where:
- `N(x)` = Standard normal cumulative distribution
- `G(x)` = Inverse standard normal
- `R` = Asset correlation (varies by exposure class)
- `PD` = Probability of Default (floored)
- `LGD` = Loss Given Default

Risk Weight = K x 12.5 (x 1.06 for CRR)

### Asset Correlation (R) by Exposure Class

| Exposure Class | Correlation Formula | Parameters |
|----------------|---------------------|------------|
| **Corporate / Institution** | R = 0.12 x f(PD) + 0.24 x (1 - f(PD)) | R_min=12%, R_max=24% |
| **Corporate SME** | R_corp x [1 - 0.04 x (1 - (min(S,50)-5)/45)] | Firm-size adjustment |
| **Retail Mortgage** | R = 0.15 (fixed) | 15% |
| **QRRE** | R = 0.04 (fixed) | 4% |
| **Other Retail** | R = 0.03 x f(PD) + 0.16 x (1 - f(PD)) | R_min=3%, R_max=16% |

**SME Firm-Size Adjustment:**
- S = Annual turnover in EUR millions
- Applied when turnover < EUR 50m
- Reduces correlation by up to 4% for smallest firms (S=5m)

### Maturity Adjustment (Non-Retail Only)

```
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
where b = (0.11852 - 0.05478 x ln(PD))^2
```

- M = Effective maturity (F-IRB: 2.5 years default; A-IRB: bank estimate, 1-5 years)
- **Retail exposures do not have maturity adjustment** (MA = 1.0)

---

## Output Floor (Basel 3.1 Only)

The output floor ensures IRB RWA is at least 72.5% of what SA RWA would be:

```
Total Standardised Equivalent = SA RWA + IRB SA Equivalent RWA
Floor = 72.5% x Total Standardised Equivalent
Final RWA = max(Actual RWA, Floor)
```

The `OutputFloorResult` provides full visibility:

| Field | Description |
|-------|-------------|
| `sa_rwa` | RWA for exposures using SA approach |
| `irb_rwa` | RWA for exposures using IRB approach |
| `irb_sa_equivalent_rwa` | What IRB exposures would have been under SA |
| `total_standardised_equivalent` | SA RWA + IRB SA Equivalent |
| `floor_rwa` | 72.5% x Total Standardised Equivalent |
| `floor_binding` | True if floor > actual RWA |
| `final_rwa` | max(actual, floor) |
| `irb_benefit` | RWA reduction from using IRB |

---

## License

[MIT license]

## References

### Current Regulations (CRR / Basel 3.0)
- [PRA Rulebook - CRR Firms](https://www.prarulebook.co.uk/pra-rules/crr-firms)
- [UK CRR - Regulation (EU) No 575/2013 as onshored](https://www.legislation.gov.uk/eur/2013/575/contents)

### Basel 3.1 Implementation (January 2027)
- [PRA PS9/24 - Implementation of the Basel 3.1 standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- [PRA CP16/22 - Implementation of Basel 3.1 Standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards)
- [Basel Committee - CRE: Calculation of RWA for credit risk](https://www.bis.org/basel_framework/chapter/CRE/20.htm)
