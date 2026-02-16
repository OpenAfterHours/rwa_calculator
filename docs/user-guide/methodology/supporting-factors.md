# Supporting Factors

**Supporting Factors** are capital relief mechanisms under CRR that reduce RWA for qualifying exposures. These factors are **removed** under Basel 3.1.

!!! warning "Basel 3.1 Impact"
    Both the SME Supporting Factor and Infrastructure Factor are withdrawn from 1 January 2027 under Basel 3.1 (PRA PS9/24).

## SME Supporting Factor

The SME Supporting Factor (Article 501 CRR) provides capital relief for exposures to Small and Medium Enterprises.

### Eligibility Criteria

| Criterion | Requirement |
|-----------|-------------|
| **Counterparty** | SME (turnover ≤ EUR 50m / GBP 44m) |
| **Exposure class** | Corporate, Retail, or Secured by Real Estate |
| **Approach** | SA or IRB |
| **Exposure type** | Not in default |
| **Not buy-to-let** | `is_buy_to_let = False` (BTL exposures excluded per CRR Art. 501) |

### Calculation

The factor is **tiered** based on total exposure to the counterparty:

```python
threshold = EUR 2,500,000  # GBP 2,200,000

if total_exposure <= threshold:
    factor = 0.7619  # 23.81% reduction
else:
    factor = (threshold × 0.7619 + (total_exposure - threshold) × 0.85) / total_exposure
```

### Factor Values

| Total Exposure | Factor | RWA Reduction |
|----------------|--------|---------------|
| ≤ GBP 2.2m | 0.7619 | 23.81% |
| GBP 3m | 0.789 | 21.1% |
| GBP 5m | 0.811 | 18.9% |
| GBP 10m | 0.831 | 16.9% |
| GBP 25m | 0.840 | 16.0% |
| GBP 50m | 0.843 | 15.7% |

### Graphical Representation

```
Factor
1.00 |
     |
0.90 |
     |                    ....----------------
0.85 |                ....
     |            ....
0.80 |        ....
     |    ....
0.76 |....
     |___________________________________
     0      2.2m   5m    10m   25m   50m  Exposure
```

### Calculation Example

**Exposure:**
- SME corporate with turnover £30m
- Total exposure: £8m
- Base RWA: £6.4m (80% average RW)

**SME Factor Calculation:**
```python
threshold = 2,200,000

# Tiered calculation
portion_1 = 2,200,000 × 0.7619 = 1,676,180
portion_2 = (8,000,000 - 2,200,000) × 0.85 = 4,930,000

total_weighted = 1,676,180 + 4,930,000 = 6,606,180
factor = 6,606,180 / 8,000,000 = 0.826

# Apply to RWA
Adjusted_RWA = 6,400,000 × 0.826 = £5,286,400

# Saving: £1,113,600 (17.4%)
```

### SME Definition

An entity qualifies as an SME if:
- Annual turnover ≤ EUR 50m (GBP 44m), OR
- Total assets ≤ EUR 43m (GBP 37.84m)

**Turnover Source:**
1. Audited financial statements (preferred)
2. Management accounts
3. Tax returns
4. Estimated based on relationship data

## Infrastructure Supporting Factor

The Infrastructure Supporting Factor (Article 501a CRR) provides capital relief for qualifying infrastructure project finance.

### Eligibility Criteria

| Criterion | Requirement |
|-----------|-------------|
| **Exposure type** | Project finance |
| **Entity type** | Project entity or High Quality Project Entity |
| **Revenue** | Predictable, predominantly EUR/GBP (or hedged) |
| **Contracts** | Robust contractual framework |
| **Cash flows** | Reliable debt service |

### Factor Value

A **flat 0.75 factor** (25% RWA reduction) applies to the entire exposure:

```python
if is_qualifying_infrastructure:
    factor = 0.75
    Adjusted_RWA = RWA × 0.75
```

### High Quality Project Entity (HQPE)

Additional criteria for maximum benefit:

| Criterion | HQPE Requirement |
|-----------|------------------|
| Revenues | Highly predictable |
| Contractual framework | Comprehensive protection |
| Equity cushion | Adequate for risk |
| Operating risk | Limited or mitigated |
| Refinancing risk | Limited or covered |

### Qualifying Infrastructure

| Category | Examples |
|----------|----------|
| **Transport** | Roads, railways, ports, airports |
| **Energy** | Power generation, transmission, distribution |
| **Water** | Treatment, distribution, drainage |
| **Social** | Hospitals, schools, housing |
| **Communications** | Telecoms, broadband |

### Non-Qualifying Examples

| Exclusion | Reason |
|-----------|--------|
| Speculative development | Cash flow uncertainty |
| Mining/extraction | Commodity price risk |
| Merchant power | Revenue volatility |
| Early-stage tech | Unproven technology |

### Calculation Example

**Exposure:**
- Infrastructure project finance
- Toll road concession
- Base RWA: £15m (slotting category "Satisfactory", 115% RW)
- Qualifies for infrastructure factor

**Calculation:**
```python
factor = 0.75

Adjusted_RWA = 15,000,000 × 0.75 = £11,250,000

# Saving: £3,750,000 (25%)
```

## Interaction of Factors

### SME + Infrastructure

Both factors can potentially apply:

```python
# Corporate SME with infrastructure characteristics
if is_sme and is_qualifying_infrastructure:
    # Apply SME factor to corporate exposure
    # Infrastructure factor applies to project finance only
    # Generally mutually exclusive by exposure type
```

### With CRM

Supporting factors apply **after** CRM:

```python
# Order of operations
1. Apply CRM (reduce exposure/RW)
2. Calculate base RWA
3. Apply supporting factors
```

### With IRB

Factors apply to IRB RWA **before** the 1.06 scaling:

```python
# IRB with SME factor
RWA_base = K × 12.5 × EAD × MA
RWA_with_sme = RWA_base × SME_factor
RWA_final = RWA_with_sme × 1.06  # CRR scaling applied last
```

!!! note "IRB SME Adjustment"
    For IRB, the SME size adjustment to correlation is separate from the SME Supporting Factor. Both can apply to the same exposure.

## Implementation

### Enabling Supporting Factors

```python
from rwa_calc.contracts.config import CalculationConfig

# Enable both factors (CRR default)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=True,
    apply_infrastructure_factor=True
)

# Disable for comparison
config_no_factors = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=False,
    apply_infrastructure_factor=False
)
```

### Basel 3.1 Configuration

```python
# Basel 3.1 - factors not available
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 1, 1)
)

# apply_sme_supporting_factor is ignored
# apply_infrastructure_factor is ignored
```

### Calculating Factors

```python
from rwa_calc.engine.sa.supporting_factors import (
    calculate_sme_factor,
    is_qualifying_infrastructure
)

# SME factor
sme_factor = calculate_sme_factor(
    total_exposure=8_000_000,
    counterparty_turnover=30_000_000,
    eur_gbp_rate=0.8732
)

# Infrastructure check
infra_eligible = is_qualifying_infrastructure(
    exposure_type="PROJECT_FINANCE",
    revenue_stability="HIGH",
    contractual_framework="COMPREHENSIVE"
)
```

## EUR/GBP Conversion

Thresholds are defined in EUR and converted to GBP:

```python
# Default rate (matches CalculationConfig.eur_gbp_rate)
EUR_GBP_RATE = 0.8732

# Thresholds
SME_TURNOVER_EUR = 50_000_000
SME_TURNOVER_GBP = 50_000_000 × 0.8732 ≈ 43_660_000

SME_EXPOSURE_EUR = 2_500_000
SME_EXPOSURE_GBP = 2_500_000 × 0.8732 ≈ 2_183_000
```

### Configuring FX Rate

```python
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    eur_gbp_rate=Decimal("0.85")  # Custom rate
)
```

## Impact Analysis

### Portfolio Impact

| Portfolio Type | SME Factor Impact | Infra Factor Impact |
|----------------|-------------------|---------------------|
| SME-heavy | 15-24% RWA reduction | N/A |
| Infrastructure | N/A | 25% RWA reduction |
| Mixed | Weighted average | Weighted average |

### Basel 3.1 Transition

For portfolios heavily reliant on supporting factors:

```python
# Estimate impact
CRR_RWA = base_rwa × sme_factor  # e.g., £8m × 0.83 = £6.64m
B31_RWA = base_rwa  # £8m (no factor)

Impact = B31_RWA - CRR_RWA  # £1.36m increase (20.5%)
```

## Regulatory References

| Topic | CRR Article |
|-------|-------------|
| SME Supporting Factor | Art. 501 (CRR2) |
| SME definition | Art. 501(2) |
| Tiered calculation | Art. 501(1) |
| Infrastructure Factor | Art. 501a |
| HQPE definition | Art. 501a(1) |

## Next Steps

- [Framework Comparison](../regulatory/comparison.md) - CRR vs Basel 3.1 impact
- [Configuration Guide](../configuration.md) - Enabling/disabling factors
- [IRB Approach](irb-approach.md) - SME correlation adjustment
