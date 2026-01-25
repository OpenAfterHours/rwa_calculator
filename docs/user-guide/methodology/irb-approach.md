# IRB Approach

The **Internal Ratings-Based (IRB)** approach allows banks with regulatory approval to use their own risk estimates for calculating RWA. This provides greater risk sensitivity than the Standardised Approach.

## Overview

Two IRB variants are available:

| Approach | PD | LGD | EAD | CCF |
|----------|:--:|:---:|:---:|:---:|
| **Foundation IRB (F-IRB)** | Bank | Supervisory | Supervisory | Supervisory |
| **Advanced IRB (A-IRB)** | Bank | Bank | Bank | Bank |

!!! warning "Basel 3.1 Restrictions"
    Under Basel 3.1, A-IRB is no longer permitted for:
    - Large corporates (revenue > £500m)
    - Banks/Financial Institutions
    - Equity exposures

## IRB Formula

The core IRB formula calculates the capital requirement (K). See [`irb/formulas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/irb/formulas.py) for the pure Polars implementation using `polars-normal-stats`.

```
K = [LGD × N((1-R)^(-0.5) × G(PD) + (R/(1-R))^0.5 × G(0.999)) - LGD × PD] × MA
```

Where:
- **N()** = Standard normal cumulative distribution function
- **G()** = Inverse standard normal distribution function
- **R** = Asset correlation
- **PD** = Probability of Default
- **LGD** = Loss Given Default
- **MA** = Maturity Adjustment (for non-retail)

Then:
```
RWA = K × 12.5 × EAD × Scaling Factor
```

??? example "Capital K Formula Implementation (formulas.py)"
    ```python
    --8<-- "src/rwa_calc/engine/irb/formulas.py:260:291"
    ```

## Risk Parameters

### Probability of Default (PD)

PD is the likelihood of default within one year.

**Floors:**

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Large Corporate | 0.03% | 0.05% |
| Bank/Institution | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.05% |
| Retail QRRE (Transactor) | 0.03% | 0.03% |
| Retail QRRE (Revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

```python
PD_effective = max(PD_estimated, PD_floor)
```

### Loss Given Default (LGD)

LGD is the percentage of exposure lost after recoveries.

**F-IRB Supervisory LGD:**

| Exposure Type | LGD |
|---------------|-----|
| Senior Unsecured | 45% |
| Subordinated | 75% |
| Secured by Financial Collateral | 0% |
| Secured by Receivables | 35% |
| Secured by CRE/RRE | 35% |
| Secured by Other Collateral | 40% |

**A-IRB LGD Floors (Basel 3.1 only):**

| Collateral Type | LGD Floor |
|-----------------|-----------|
| Unsecured Senior | 25% |
| Unsecured Subordinated | 50% |
| Financial Collateral | 0% |
| Receivables | 15% |
| Commercial Real Estate | 15% |
| Residential Real Estate | 10% |
| Other Physical | 20% |

### Exposure at Default (EAD)

**F-IRB:**
- On-Balance Sheet: Gross carrying amount
- Off-Balance Sheet: Regulatory CCFs apply based on `risk_type`:

| Risk Type | SA CCF | F-IRB CCF | Notes |
|-----------|--------|-----------|-------|
| FR (full_risk) | 100% | 100% | Guarantees, credit substitutes |
| MR (medium_risk) | 50% | 75% | Committed undrawn, NIFs, RUFs |
| MLR (medium_low_risk) | 20% | 75% | Documentary credits, trade finance |
| LR (low_risk) | 0% | 0% | Unconditionally cancellable |

**CRR Art. 166(8):** Under F-IRB, MR and MLR categories both use 75% CCF.

**CRR Art. 166(9) Exception:** Short-term letters of credit arising from the movement of goods retain 20% CCF under F-IRB. Flag these exposures with `is_short_term_trade_lc = True`.

**A-IRB:**
- Bank estimates EAD using internal models
- Provide modelled CCF in `ccf_modelled` column (0.0-1.5, can exceed 100% for Retail IRB)
- When `ccf_modelled` is provided, it takes precedence over risk_type lookup
- Subject to CCF floors under Basel 3.1

### Maturity (M)

Effective maturity affects capital through the maturity adjustment.

- **Range:** 1 year (floor) to 5 years (cap)
- **Retail exemption:** No maturity adjustment for retail

```python
# Effective maturity calculation
M = max(1, min(5, weighted_average_life))
```

## Asset Correlation

Asset correlation (R) determines how sensitive the exposure is to systematic risk. See [`_polars_correlation_expr()`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/irb/formulas.py) for the pure Polars implementation.

### Corporate/Bank Correlation

```python
R = 0.12 × (1 - exp(-50 × PD)) / (1 - exp(-50)) +
    0.24 × [1 - (1 - exp(-50 × PD)) / (1 - exp(-50))]
```

This produces:
- R = 24% for very low PD
- R = 12% for high PD

### SME Size Adjustment

For SME corporates (turnover £5m-£50m):

```python
# Size adjustment factor
S = min(50, max(5, turnover_millions))

R_adjusted = R - 0.04 × (1 - (S - 5) / 45)
```

This reduces correlation by up to 4 percentage points for smaller firms.

### Retail Correlations

| Retail Type | Correlation |
|-------------|-------------|
| Residential Mortgage | 15% |
| QRRE | 4% |
| Other Retail | 3-16% (PD-dependent) |

**Other Retail:**
```python
R = 0.03 × (1 - exp(-35 × PD)) / (1 - exp(-35)) +
    0.16 × [1 - (1 - exp(-35 × PD)) / (1 - exp(-35))]
```

??? example "Actual Correlation Implementation (formulas.py)"
    ```python
    --8<-- "src/rwa_calc/engine/irb/formulas.py:323:365"
    ```

## Maturity Adjustment

For non-retail exposures. See [`_polars_maturity_adjustment_expr()`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/irb/formulas.py) for the pure Polars implementation.

```python
# Maturity factor b
b = (0.11852 - 0.05478 × ln(PD))^2

# Maturity adjustment
MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
```

Where M is effective maturity in years.

??? example "Actual Maturity Adjustment (formulas.py)"
    ```python
    --8<-- "src/rwa_calc/engine/irb/formulas.py:445:457"
    ```

**Example values:**

| PD | M=1yr | M=2.5yr | M=5yr |
|----|-------|---------|-------|
| 0.03% | 0.853 | 1.000 | 1.221 |
| 0.10% | 0.880 | 1.000 | 1.177 |
| 1.00% | 0.934 | 1.000 | 1.099 |
| 5.00% | 0.966 | 1.000 | 1.050 |

## Scaling Factor

| Framework | Scaling Factor |
|-----------|----------------|
| CRR | **1.06** |
| Basel 3.1 | **1.00** (none) |

```python
# CRR
RWA = K × 12.5 × EAD × MA × 1.06

# Basel 3.1
RWA = K × 12.5 × EAD × MA
```

## Expected Loss (EL)

IRB requires calculation of Expected Loss:

```
EL = PD × LGD × EAD
```

EL is compared to provisions:
- **EL > Provisions:** Shortfall deducted from capital
- **EL < Provisions:** Excess added to Tier 2 (with limits)

## Detailed Calculation Example

**Exposure:**
- Corporate loan, £50m
- Bank-estimated PD: 0.50%
- F-IRB (LGD = 45%)
- Maturity: 3 years
- Counterparty turnover: £25m (SME)

**Step 1: Apply PD Floor**
```python
PD = max(0.0050, 0.0003) = 0.0050  # 0.50%
```

**Step 2: Calculate Asset Correlation**
```python
# Base correlation
R_base = 0.12 × (1 - exp(-50 × 0.005)) / (1 - exp(-50)) +
         0.24 × (1 - (1 - exp(-50 × 0.005)) / (1 - exp(-50)))
R_base = 0.12 × 0.221 + 0.24 × 0.779 = 0.214

# SME adjustment (turnover £25m)
S = 25
adjustment = 0.04 × (1 - (25 - 5) / 45) = 0.04 × 0.556 = 0.022
R = 0.214 - 0.022 = 0.192
```

**Step 3: Calculate Capital Requirement (K)**
```python
# Intermediate calculations
G_PD = norm.ppf(0.005) = -2.576
G_999 = norm.ppf(0.999) = 3.090

term1 = (1 - R)^(-0.5) × G_PD = 1.113 × (-2.576) = -2.867
term2 = (R / (1-R))^0.5 × G_999 = 0.487 × 3.090 = 1.505

K_pre = LGD × N(term1 + term2) - LGD × PD
K_pre = 0.45 × N(-1.362) - 0.45 × 0.005
K_pre = 0.45 × 0.0867 - 0.00225
K_pre = 0.0390 - 0.00225 = 0.0367
```

**Step 4: Calculate Maturity Adjustment**
```python
b = (0.11852 - 0.05478 × ln(0.005))^2 = (0.11852 + 0.290)^2 = 0.167
MA = (1 + (3 - 2.5) × 0.167) / (1 - 1.5 × 0.167)
MA = 1.0835 / 0.7495 = 1.446
```

**Step 5: Calculate RWA**
```python
# CRR
RWA_CRR = K × 12.5 × EAD × MA × 1.06
RWA_CRR = 0.0367 × 12.5 × 50,000,000 × 1.446 × 1.06
RWA_CRR = £35,142,968

RW_CRR = RWA / EAD = 70.3%

# Basel 3.1 (no scaling)
RWA_B31 = 0.0367 × 12.5 × 50,000,000 × 1.446 × 1.00
RWA_B31 = £33,154,688

RW_B31 = 66.3%
```

**Step 6: Check Output Floor (Basel 3.1)**
```python
# SA equivalent RWA (assume 100% RW corporate)
RWA_SA = 50,000,000 × 100% = £50,000,000

# Output floor (72.5%)
Floor = 50,000,000 × 0.725 = £36,250,000

# Final RWA
RWA_final = max(33,154,688, 36,250,000) = £36,250,000
```

## Implementation

### Using the IRB Namespace (Recommended)

The IRB module provides a Polars namespace extension for fluent, chainable calculations:

```python
import polars as pl
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.irb.namespace  # Registers .irb namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Create sample exposure data
exposures = pl.LazyFrame({
    "exposure_reference": ["EXP001"],
    "pd": [0.005],
    "lgd": [0.45],
    "ead_final": [50_000_000.0],
    "maturity": [3.0],
    "exposure_class": ["CORPORATE"],
    "turnover_m": [25.0],  # Annual turnover in millions
})

# Fluent IRB calculation pipeline
result = (
    exposures
    .irb.classify_approach(config)   # Determine F-IRB vs A-IRB
    .irb.apply_firb_lgd(config)      # Apply supervisory LGD for F-IRB
    .irb.prepare_columns(config)     # Ensure required columns exist
    .irb.apply_all_formulas(config)  # Run full IRB calculation
    .collect()
)

# Access results
print(result.select([
    "pd_floored", "correlation", "k", "maturity_adjustment", "rwa", "expected_loss"
]))
```

**Individual formula steps** can also be chained:

```python
result = (
    exposures
    .irb.apply_pd_floor(config)
    .irb.apply_lgd_floor(config)
    .irb.calculate_correlation(config)
    .irb.calculate_k(config)
    .irb.calculate_maturity_adjustment(config)
    .irb.calculate_rwa(config)
    .irb.calculate_expected_loss(config)
)
```

### Using the IRB Calculator

```python
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.contracts.config import CalculationConfig

# Create calculator
calculator = IRBCalculator()

# Calculate
result = calculator.calculate(
    exposures=classified_exposures,
    config=CalculationConfig.crr(reporting_date=date(2026, 12, 31))
)

# Results
print(f"IRB RWA: {result.total_rwa:,.2f}")
print(f"Expected Loss: {result.total_expected_loss:,.2f}")
```

### Using IRB Formulas Directly

The IRB formulas are implemented in [`irb/formulas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/irb/formulas.py). Both scalar functions and pure Polars expression functions are available, using `polars-normal-stats` for statistical operations.

```python
from rwa_calc.engine.irb.formulas import (
    calculate_k,
    calculate_correlation,
    calculate_maturity_adjustment,
    calculate_irb_rwa,  # Convenience function for single exposures
)

# Calculate components
R = calculate_correlation(
    pd=0.005,
    exposure_class="CORPORATE",
    turnover_m=25.0  # Turnover in millions
)

MA = calculate_maturity_adjustment(pd=0.005, maturity=3)

K = calculate_k(pd=0.005, lgd=0.45, correlation=R)

# Calculate RWA
rwa = K * 12.5 * ead * MA * scaling_factor

# Or use the convenience function for complete calculation
result = calculate_irb_rwa(
    ead=50_000_000,
    pd=0.005,
    lgd=0.45,
    correlation=R,
    maturity=3.0,
    apply_scaling_factor=True,  # CRR 1.06 factor
)
print(f"RWA: {result['rwa']:,.0f}")
```

??? example "Scalar K Calculation (formulas.py)"
    ```python
    --8<-- "src/rwa_calc/engine/irb/formulas.py:429:443"
    ```

## Expected Loss Calculation

```python
from rwa_calc.engine.irb.calculator import calculate_expected_loss

el = calculate_expected_loss(
    pd=0.005,
    lgd=0.45,
    ead=50_000_000
)
# el = 0.005 × 0.45 × 50,000,000 = £112,500
```

## F-IRB vs A-IRB Comparison

| Parameter | F-IRB | A-IRB |
|-----------|-------|-------|
| PD | Bank estimate | Bank estimate |
| LGD | Supervisory (45%/75%) | Bank estimate (floored) |
| EAD | Regulatory | Bank estimate |
| CCF | Regulatory | Bank estimate |
| Typical RW | Higher | Lower |
| Complexity | Lower | Higher |
| Approval | Easier | Harder |

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| IRB approach overview | Art. 142-150 | CRE30 |
| K formula | Art. 153 | CRE31 |
| PD estimation | Art. 178-180 | CRE32 |
| LGD estimation | Art. 181 | CRE32 |
| Correlation | Art. 153 | CRE31 |
| Maturity adjustment | Art. 162 | CRE31 |
| Supervisory LGD | Art. 161 | CRE32 |

## Next Steps

- [Standardised Approach](standardised-approach.md) - Compare with SA
- [Credit Risk Mitigation](crm.md) - CRM under IRB
- [Supporting Factors](supporting-factors.md) - SME correlation adjustment
