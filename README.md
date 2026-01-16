# UK Credit Risk RWA Calculator

A high-performance Risk-Weighted Assets (RWA) calculator for UK credit risk, supporting both current regulations and future Basel 3.1 implementation. Built with Python using Polars for vectorized performance.

## Regulatory Scope

This calculator supports two regulatory regimes:

| Regime | Effective Period | UK Implementation |
|--------|------------------|-------------------|
| **Basel 3.0** (Current) | Until 31 December 2026 | UK CRR (EU 575/2013 as onshored) |
| **Basel 3.1** (Future) | From 1 January 2027 | PRA PS9/24 |

A configuration toggle allows switching between calculation modes, enabling:
- Current regulatory reporting under UK CRR
- Impact analysis and parallel running ahead of Basel 3.1 go-live
- Seamless transition when Basel 3.1 becomes effective

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


### Key Differences Between Regimes

| Area | Basel 3.0 (UK CRR) | Basel 3.1 (PRA PS9/24) |
|------|-------------------|------------------------|
| **Output Floor** | None | 72.5% of SA equivalent |
| **IRB Scope** | All exposure classes eligible | Central govs, Equity, CIUs must use SA |
| **PD Floors** | Varies | Standardised floors (0.03%-0.10%) |
| **LGD Floors** | Varies | New A-IRB floors (0%-25%) |
| **SA Risk Weights** | CRR Part Three, Title II | Revised tables per PS9/24 |
| **Retail Threshold** | €1m exposure | £880k exposure |
| **SME Support Factor** | Applies | Withdrawn |

## How it works:

- Counterparty hierarchies allow for lending groups (for Retail classification) and org groups 
(for parent ratings) to be calculated
- Facilities and loans are combined into a hierarchy internally
- Drawn amounts aggregate bottom-up from loans to facilities
- Undrawn amounts are calculated at the root facility level
- RWA is calculated on both drawn (loans) and undrawn (facilities) exposures
- Collateral is prorated to optimise RWA calculation
- Provisions are allocated to optimise the RWA calculation. 

### Project Structure

```
src/rwa_calc/
├── domain/                         # Core domain models
│   └── enums.py                    # ExposureClass, ApproachType, CQS, etc.
├── data/                           # Data loading & schemas
│   ├── results.py                  # DataFrame-based calculation results
│   ├── loaders.py                  # File, DuckDB, InMemory loaders
│   └── schemas.py                  # Polars schemas (Facility, Loan, Counterparty, etc.)
├── engine/                         # Vectorized calculation engines
│   ├── orchestrator.py             # Main calculation pipeline
│   ├── hierarchy_counterparty.py   # Counterparty hierarchy operations
|   ├── hierarchy_exposure.py       # Exposure hierarchy operations (DuckDB CTEs)
│   ├── classification.py           # Exposure class & approach determination
│   │                               
│   ├── sa/                         # Standardised Approach
|   |   ├── basel_3_calculator.py   # SA risk weights, CCF, EAD, RWA for current (up to Dec 2026)
│   │   └── basel_31_calculator.py  # SA risk weights, CCF, EAD, RWA for Basel 3.1 (from Jan 2027)
│   ├── irb/                        # IRB Approach
|   |   ├── basel_3_calculator.py   # IRB formula, correlation, maturity adjustment for current (up to Dec 2026)
│   │   └── basel_3_calculator.py   # IRB formula, correlation, maturity adjustment for Basel 3.1 (from Jan 2027)
│   ├── crm/                        # Credit Risk Mitigation
│   │   └── processor.py            # Haircuts, eligibility, substitution
│   └── provisions.py               # Provisions & Impairments
│                                   
├── config/
│   └── regulatory_params.py        # All PRA PS9/24 parameters/current Basel 3.0
├── reporting/                      # Output generation (future)
│   ├── pra/                        # CAP+
│   └── corep/                      # COREP templates
└── ui/                             # Frontend (planned) + Marimo workbooks for investigations
```

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

**RWA Benefit:** £2M × 100% = **£2M RWA saved** (allocated to highest RW exposure first)

### Example: Facility-Level Collateral

**Setup:**
```
FAC001 (Master Facility)
├── LOAN_A (£500k drawn, RW=100%)
└── LOAN_B (£300k drawn, RW=50%)

Collateral: £400k cash linked to facility_id=FAC001
```

**Allocation Result (RWA-optimized):**

| Exposure | Drawn | Risk Weight | Collateral Allocated | Net Exposure |
|----------|-------|-------------|---------------------|--------------|
| LOAN_A   | £500k | 100%        | £400k (priority)    | £100k        |
| LOAN_B   | £300k | 50%         | £0                  | £300k        |
| FAC001   | £0    | -           | £0                  | £0           |

**RWA Benefit:** £400k × 100% = **£400k RWA saved**

### Example: Loan-Level Collateral

**Setup:**
```
Collateral: £200k cash linked to exposure_ids="LOAN_A,LOAN_B"
- LOAN_A: £300k drawn, RW=75%
- LOAN_B: £200k drawn, RW=100%
```

**Allocation Result (RWA-optimized):**

| Exposure | Drawn | Risk Weight | Collateral Allocated | Net Exposure |
|----------|-------|-------------|---------------------|--------------|
| LOAN_B   | £200k | 100%        | £200k (priority)    | £0           |
| LOAN_A   | £300k | 75%         | £0                  | £300k        |

**RWA Benefit:** £200k × 100% = **£200k RWA saved**

### Collateral Data Format
TBC

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
   - SCRA coverage >= 20% of unsecured portion → **100% RW**
   - SCRA coverage < 20% of unsecured portion → **150% RW**


### IRB Provisions (PRA PS9/24 Chapter 5)

For IRB exposures, provisions are compared to Expected Loss:

1. **Regulatory EL**: Calculated as `PD × LGD × EAD`
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
effective_lgd = coverage × lgd_secured + (1 - coverage) × 45%
```

**Example: 50% Collateralised by Cash**
```
Exposure: £1,000,000 (senior)
Collateral: £500,000 cash
Coverage ratio: 50%

Effective LGD = 50% × 0% + 50% × 45% = 22.5%
```

The CRM processor automatically tracks the `primary_collateral_type` (highest allocation value) for each exposure, which flows through to the F-IRB LGD calculation.


## Key Regulatory Parameters

The following parameters are specific to the **Basel 3.1** regime (PRA PS9/24). Basel 3.0/UK CRR parameters are maintained separately in `config/regulatory_params.py`.

| Parameter | Value | Reference |
|-----------|-------|-----------|
| Output Floor | 72.5% | PS9/24 Ch. 6 (Basel 3.1 only - not in current UK CRR) |
| PD Floor (Corporate) | 0.03% | PS9/24 Ch. 5 |
| PD Floor (Retail) | 0.05% | PS9/24 Ch. 5 |
| PD Floor (QRRE) | 0.10% | PS9/24 Ch. 5 |
| LGD Floor (Senior Unsecured) | 25% | PS9/24 Ch. 5 |
| Institution CQS2 RW | 30% | PS9/24 Ch. 3.3 (UK deviation) |
| FX Haircut | 8% | PS9/24 Ch. 4 |
| **F-IRB Supervisory LGD** | | |
| F-IRB LGD (Financial Collateral) | 0% | PS9/24 Ch. 5 |
| F-IRB LGD (Receivables/RE) | 35% | PS9/24 Ch. 5 |
| F-IRB LGD (Other Physical) | 40% | PS9/24 Ch. 5 |
| F-IRB LGD (Unsecured) | 45% | PS9/24 Ch. 5 |
| F-IRB LGD (Subordinated) | 75% | PS9/24 Ch. 5 |
| **A-IRB LGD Floors** | | |
| A-IRB Floor (Financial Collateral) | 0% | PS9/24 Ch. 5 |
| A-IRB Floor (Residential RE) | 5% | PS9/24 Ch. 5 |
| A-IRB Floor (Receivables) | 10% | PS9/24 Ch. 5 |
| A-IRB Floor (Commercial RE) | 10% | PS9/24 Ch. 5 |
| A-IRB Floor (Other Physical) | 15% | PS9/24 Ch. 5 |
| A-IRB Floor (Unsecured) | 25% | PS9/24 Ch. 5 |
| A-IRB Floor (Subordinated) | 25% | PS9/24 Ch. 5 |
| **Provisions Parameters** | | |
| Defaulted SCRA Coverage Threshold | 20% | PS9/24 Ch. 3 |
| EL Excess Tier 2 Cap | 0.6% of IRB RWA | PS9/24 Ch. 5 |
| **IRB Classification Thresholds** | | |
| Large Corporate Revenue | £440m | PS9/24 Ch. 5 (3-year average) |
| Retail SME Exposure | £0.88m | PS9/24 Ch. 5 (excl. residential secured) |
| QRRE Max Individual Exposure | £90,000 | PS9/24 Ch. 5 (including undrawn) |


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

### Residential Mortgages (LTV-based)
| LTV | ≤50% | ≤60% | ≤70% | ≤80% | ≤90% | ≤100% | >100% |
|-----|------|------|------|------|------|-------|-------|
| RW  | 20% | 25% | 30% | 35% | 40% | 50% | 70% |

## IRB Formula

The IRB capital requirement (K) is calculated as:

```
K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
```

Where:
- `N(x)` = Standard normal cumulative distribution
- `G(x)` = Inverse standard normal
- `R` = Asset correlation (varies by exposure class - see below)
- `PD` = Probability of Default (floored)
- `LGD` = Loss Given Default

Risk Weight = K × 12.5

### Asset Correlation (R) by Exposure Class

The correlation parameter R varies by exposure class and determines the sensitivity to systematic risk:

| Exposure Class | Correlation Formula | Parameters |
|----------------|---------------------|------------|
| **Corporate / Institution** | R = 0.12 × f(PD) + 0.24 × (1 - f(PD)) | R_min=12%, R_max=24% |
| **Corporate SME** | R_corp × [1 - 0.04 × (1 - (min(S,50)-5)/45)] | Firm-size adjustment |
| **Retail Mortgage** | R = 0.15 (fixed) | 15% |
| **QRRE** | R = 0.04 (fixed) | 4% |
| **Other Retail** | R = 0.03 × f(PD) + 0.16 × (1 - f(PD)) | R_min=3%, R_max=16% |

**PD-dependent function:**
- Corporate/Institution: `f(PD) = (1 - e^(-50×PD)) / (1 - e^(-50))`
- Other Retail: `f(PD) = (1 - e^(-35×PD)) / (1 - e^(-35))`

**SME Firm-Size Adjustment:**
- S = Annual turnover in EUR millions
- Applied when turnover < EUR 50m
- Reduces correlation by up to 4% for smallest firms (S=5m)

**Correlation Interpretation:**
- Higher correlation → Higher RW (more systematic risk)
- QRRE (4%) has lowest correlation - reflects granular, idiosyncratic risk
- Mortgages (15%) are fixed - residential RE portfolio shows consistent systematic behaviour
- Corporates/Institutions (12-24%) have highest correlation - more exposed to economic cycles

### Maturity Adjustment (Non-Retail Only)

```
MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
where b = (0.11852 - 0.05478 × ln(PD))²
```

- M = Effective maturity (F-IRB: 2.5 years default; A-IRB: bank estimate, 1-5 years)
- **Retail exposures do not have maturity adjustment** (MA = 1.0)

## Output Floor (PRA PS9/24 Chapter 6)

The output floor ensures IRB RWA is at least 72.5% of what SA RWA would be:

```
Total Standardised Equivalent = SA RWA + IRB SA Equivalent RWA
Floor = 72.5% × Total Standardised Equivalent
Final RWA = max(Actual RWA, Floor)
```

The `OutputFloorResult` provides full visibility:

| Field | Description |
|-------|-------------|
| `sa_rwa` | RWA for exposures using SA approach |
| `irb_rwa` | RWA for exposures using IRB approach |
| `irb_sa_equivalent_rwa` | What IRB exposures would have been under SA |
| `total_standardised_equivalent` | SA RWA + IRB SA Equivalent |
| `floor_rwa` | 72.5% × Total Standardised Equivalent |
| `floor_binding` | True if floor > actual RWA |
| `final_rwa` | max(actual, floor) |
| `irb_benefit` | RWA reduction from using IRB |

## Development Status


## License

[MIT license]

## References

### Current Regulations (Basel 3.0 / UK CRR)
- [PRA Rulebook - CRR Firms](https://www.prarulebook.co.uk/pra-rules/crr-firms)
- [UK CRR - Regulation (EU) No 575/2013 as onshored](https://www.legislation.gov.uk/eur/2013/575/contents)

### Basel 3.1 Implementation (January 2027)
- [PRA PS9/24 - Implementation of the Basel 3.1 standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- [PRA CP16/22 - Implementation of Basel 3.1 Standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards)
- [Basel Committee - CRE: Calculation of RWA for credit risk](https://www.bis.org/basel_framework/chapter/CRE/20.htm)