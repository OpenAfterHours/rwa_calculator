# Standardised Approach

The **Standardised Approach (SA)** uses regulatory-prescribed risk weights based on external credit ratings and exposure characteristics. It is the default approach for institutions without IRB approval.

## Overview

```
RWA = EAD × Risk Weight × Supporting Factors
```

The SA calculation involves:
1. Determining the **Exposure Class**
2. Mapping to a **Credit Quality Step (CQS)** if rated
3. Looking up the **Risk Weight**
4. Applying **Supporting Factors** (CRR only)

## Risk Weight Determination

```mermaid
flowchart TD
    A[Exposure] --> B{Has External Rating?}
    B -->|Yes| C[Map to CQS]
    B -->|No| D[Unrated Treatment]
    C --> E[Lookup RW by Class + CQS]
    D --> F[Default RW for Class]
    E --> G[Apply Supporting Factors]
    F --> G
    G --> H[Calculate RWA]
```

## Credit Quality Steps (CQS)

External ratings are mapped to Credit Quality Steps:

| CQS | S&P/Fitch | Moody's | Description |
|-----|-----------|---------|-------------|
| CQS 1 | AAA to AA- | Aaa to Aa3 | Prime/High Grade |
| CQS 2 | A+ to A- | A1 to A3 | Upper Medium Grade |
| CQS 3 | BBB+ to BBB- | Baa1 to Baa3 | Lower Medium Grade |
| CQS 4 | BB+ to BB- | Ba1 to Ba3 | Non-Investment Grade |
| CQS 5 | B+ to B- | B1 to B3 | Highly Speculative |
| CQS 6 | CCC+ and below | Caa1 and below | Substantial Risk |

## Risk Weights by Exposure Class

Risk weights depend on the exposure class and the counterparty's Credit Quality Step (CQS). Under Basel 3.1, several classes receive revised weights — notably more granular LTV-based treatment for real estate, reduced weights for CQS 3 corporates, and differentiated retail categories.

> **Details:** See [SA Risk Weights](../../specifications/crr/sa-risk-weights.md) for the complete risk weight tables by exposure class, and [Key Differences](../../framework-comparison/key-differences.md) for CRR vs Basel 3.1 changes.

Key points:

- **Sovereign**: 0% (CQS 1) to 150% (CQS 6); UK Government always 0% in GBP
- **Institution**: 20%-150% by CQS; Basel 3.1 introduces ECRA/SCRA for unrated
- **Corporate**: 20%-150% by CQS; Basel 3.1 reduces CQS 3 from 100% to 75%
- **Retail**: CRR 75% (35% for payroll/pension since CRR2); Basel 3.1 adds 45% transactor sub-category
- **Residential RE**: CRR flat 35%; Basel 3.1 uses LTV-based bands (20%-105%)
- **Defaulted**: 100%-150% based on provision coverage
- **Equity**: CRR 100%; Basel 3.1 250%/400%

## EAD Calculation

### On-Balance Sheet

```python
EAD = Gross_Carrying_Amount - Specific_Provisions
```

### Off-Balance Sheet

```python
EAD = Committed_Amount × CCF
```

**Credit Conversion Factors by Risk Type (CRR Art. 111):**

The `risk_type` column determines the CCF for off-balance sheet exposures:

| Risk Type | Code | SA CCF | Description |
|-----------|------|--------|-------------|
| Full Risk | FR | 100% | Guarantees, acceptances, credit derivatives |
| Medium Risk | MR | 50% | NIFs, RUFs, standby LCs, committed undrawn |
| Medium-Low Risk | MLR | 20% | Documentary credits, short-term trade finance |
| Low Risk | LR | 0% | Unconditionally cancellable commitments |

**Basel 3.1 Changes:**

| Item Type | CRR CCF | Basel 3.1 CCF |
|-----------|---------|---------------|
| Unconditionally Cancellable | 0% | 10% |
| Trade Finance (ST) | 20% | 20% |
| Undrawn Commitments (<1yr) | 20% | 40% |
| Undrawn Commitments (≥1yr) | 50% | 40% |
| NIFs/RUFs | 50% | 50% |
| Direct Credit Substitutes | 100% | 100% |

## Credit Risk Mitigation

SA allows several CRM techniques — financial collateral (simple and comprehensive methods), guarantees (substitution approach), and provisions (drawn-first deduction).

> **Details:** See [Credit Risk Mitigation](crm.md) for the full treatment including haircut tables, overcollateralisation ratios, maturity mismatch adjustments, and worked examples.

## Supporting Factors (CRR Only)

Supporting factors are implemented in [`sa/supporting_factors.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sa/supporting_factors.py).

### SME Supporting Factor

Reduces RWA for SME exposures (CRR Art. 501):

!!! info "Conceptual Logic"
    The following illustrates the SME factor calculation. See the actual implementation for
    the full Polars-based processing.

```python
# Check eligibility
if turnover <= EUR_50m and is_sme:
    threshold = EUR_2.5m  # ~GBP 2.18m (converted via eur_gbp_rate)

    if exposure <= threshold:
        factor = 0.7619
    else:
        factor = (threshold * 0.7619 + (exposure - threshold) * 0.85) / exposure

    RWA = RWA * factor
```

??? example "Actual Implementation (supporting_factors.py)"
    ```python
    --8<-- "src/rwa_calc/engine/sa/supporting_factors.py"
    ```

### Infrastructure Factor

Reduces RWA for qualifying infrastructure (CRR Art. 501a):

```python
if is_qualifying_infrastructure:
    RWA = RWA * 0.75
```

## Calculation Example

**Exposure:**
- Corporate loan, £10m drawn
- Rated A+ (CQS 2)
- SME counterparty (turnover £30m)
- Unsecured

**Calculation:**
```python
# Step 1: EAD
EAD = £10,000,000

# Step 2: Risk Weight (CQS 2 Corporate)
RW = 50%

# Step 3: Base RWA
Base_RWA = £10,000,000 × 50% = £5,000,000

# Step 4: SME Factor (CRR only)
# Exposure > threshold, so tiered
threshold = EUR 2,500,000 × 0.8732 = £2,183,000
factor = (2,183,000 × 0.7619 + 7,817,000 × 0.85) / 10,000,000
factor = (1,663,427 + 6,644,450) / 10,000,000
factor = 0.831

# Step 5: Final RWA (CRR)
Final_RWA = £5,000,000 × 0.831 = £4,153,939

# Basel 3.1 (no SME factor)
Final_RWA_B31 = £5,000,000
```

## Implementation Notes

### Calculator Usage

The SA calculator is implemented in [`sa/calculator.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/sa/calculator.py).

```python
import polars as pl
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.contracts.config import CalculationConfig
from datetime import date

# Create SA calculator
calculator = SACalculator()

# Calculate RWA for a single exposure via calculate_branch()
df = pl.DataFrame({
    "exposure_reference": ["EX1"],
    "ead": [10_000_000.0],
    "exposure_class": ["CORPORATE"],
    "cqs": [2],
    "is_sme": [True],
}).lazy()

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
result = calculator.calculate_branch(df, config).collect().to_dicts()[0]

# Access results
print(f"Risk Weight: {result['risk_weight']}")
print(f"RWA: {result['rwa']}")
```

### Risk Weight Lookup

Risk weights are defined in:

- **CRR**: `data/tables/crr_risk_weights.py` — `get_combined_cqs_risk_weights()`
- **Basel 3.1**: `data/tables/b31_risk_weights.py` — `get_b31_combined_cqs_risk_weights()`

```python
from rwa_calc.data.tables.crr_risk_weights import get_combined_cqs_risk_weights

# Get CRR risk weight lookup table (Art. 120 Table 3 for institutions)
rw_table = get_combined_cqs_risk_weights()

# Table includes: exposure_class, cqs, risk_weight
# Example: CORPORATE, CQS 2 -> 50%
```

??? example "Actual Risk Weight Application (calculator.py)"
    See the `_apply_risk_weights` method in `src/rwa_calc/engine/sa/calculator.py` for the
    full implementation of risk weight lookups by exposure class and CQS.

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Risk weight assignment | Art. 113-134 | CRE20-22 |
| CCFs | Art. 111 | CRE20.10 |
| CRM | Art. 192-241 | CRE22 |
| SME factor | Art. 501 | N/A |
| Real estate | Art. 124-125 | CRE20.70-90 |

## Next Steps

- [IRB Approach](irb-approach.md) - Internal ratings-based methodology
- [Credit Risk Mitigation](crm.md) - CRM techniques in detail
- [Supporting Factors](supporting-factors.md) - SME and infrastructure factors
