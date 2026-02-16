# Framework Comparison

This page provides a comprehensive comparison between CRR (Basel 3.0) and Basel 3.1 frameworks.

## Overview

| Aspect | CRR (Basel 3.0) | Basel 3.1 |
|--------|-----------------|-----------|
| **Effective** | Until 31 Dec 2026 | From 1 Jan 2027 |
| **Philosophy** | Risk sensitivity | Comparability + floors |
| **IRB Benefit** | Unlimited | Floored at 72.5% of SA |
| **Supporting Factors** | SME + Infrastructure | None |
| **Scaling** | 1.06 multiplier | None |

## IRB Treatment

### Scaling Factor

=== "CRR"

    ```python
    # 6% uplift on all IRB RWA
    RWA = K × 12.5 × EAD × MA × 1.06
    ```

=== "Basel 3.1"

    ```python
    # No scaling factor
    RWA = K × 12.5 × EAD × MA
    ```

**Impact:** ~5.7% reduction in IRB RWA (before output floor)

### Output Floor

=== "CRR"

    No output floor. IRB RWA can be significantly below SA.

    ```
    Example:
    - SA RWA: £100m
    - IRB RWA: £30m
    - Final RWA: £30m (70% capital saving)
    ```

=== "Basel 3.1"

    72.5% floor limits IRB benefit.

    ```
    Example:
    - SA RWA: £100m
    - IRB RWA: £30m
    - Floor: £100m × 72.5% = £72.5m
    - Final RWA: £72.5m (27.5% capital saving only)
    ```

### PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Large Corporate | 0.03% | 0.05% |
| Institution/Bank | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.05% |
| Retail QRRE (Transactor) | 0.03% | 0.03% |
| Retail QRRE (Revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

### LGD Floors (A-IRB Only)

| Collateral Type | CRR | Basel 3.1 |
|-----------------|-----|-----------|
| Unsecured Senior | None | 25% |
| Unsecured Subordinated | None | 50% |
| Financial Collateral | None | 0% |
| Receivables | None | 15% |
| Commercial RE | None | 15% |
| Residential RE | None | 10% |
| Other Physical | None | 20% |

### IRB Approach Restrictions

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Large Corporate (>£500m) | F-IRB or A-IRB | **F-IRB only** |
| Bank/Institution | F-IRB or A-IRB | **F-IRB only** |
| Equity | IRB | **SA only** |

## Supporting Factors

### SME Supporting Factor

=== "CRR (Article 501)"

    **Eligibility:**
    - Turnover ≤ EUR 50m
    - Corporate, Retail, or Real Estate secured

    **Calculation:**
    ```python
    # Tiered approach
    threshold = EUR 2.5m  # GBP 2.2m

    if exposure <= threshold:
        factor = 0.7619  # 23.81% reduction
    else:
        factor = (threshold × 0.7619 + (exposure - threshold) × 0.85) / exposure
    ```

    | Exposure | Factor | RWA Reduction |
    |----------|--------|---------------|
    | £1m | 0.7619 | 23.81% |
    | £2.2m | 0.7619 | 23.81% |
    | £5m | 0.811 | 18.9% |
    | £10m | 0.831 | 16.9% |

=== "Basel 3.1"

    **SME Supporting Factor: REMOVED**

    No capital relief for SME exposures.

### Infrastructure Supporting Factor

=== "CRR"

    **Eligibility:**
    - Qualifying infrastructure project finance
    - Revenues in EUR/GBP or hedged

    **Calculation:**
    ```python
    factor = 0.75  # 25% reduction
    RWA_adjusted = RWA × 0.75
    ```

=== "Basel 3.1"

    **Infrastructure Factor: REMOVED**

    No capital relief for infrastructure projects.

## SA Risk Weights

### Corporate

| CQS | CRR | Basel 3.1 | Change |
|-----|-----|-----------|--------|
| CQS1 (AAA-AA-) | 20% | 20% | - |
| CQS2 (A+-A-) | 50% | 50% | - |
| CQS3 (BBB+-BBB-) | 75% | 75% | - |
| CQS4 (BB+-BB-) | 100% | 100% | - |
| CQS5 (B+-B-) | 150% | **100%** | -50pp |
| CQS6 (CCC+/Below) | 150% | 150% | - |
| Unrated | 100% | 100% | - |

### Residential Real Estate

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| LTV ≤ 50% | 35% | **20%** |
| LTV 50-60% | 35% | **25%** |
| LTV 60-70% | 35% | **30%** |
| LTV 70-80% | 35% | **40%** |
| LTV 80-90% | 75% | **50%** |
| LTV 90-100% | 75% | **70%** |
| LTV > 100% | Cpty RW | Cpty RW |

### Commercial Real Estate

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| LTV ≤ 60%, Income-Producing | 100% | **70%** |
| LTV > 60%, Income-Producing | 100% | **110%** |

### Subordinated Debt

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Subordinated Debt | 100-150% | **150%** |
| Equity-like | 150% | **250%** |

## Credit Conversion Factors

| Item Type | CRR | Basel 3.1 |
|-----------|-----|-----------|
| Unconditionally Cancellable | 0% | **10%** |
| Other Commitments < 1yr | 20% | 40% |
| Other Commitments ≥ 1yr | 50% | 40% |
| Trade Letters of Credit | 20% | 20% |
| NIFs/RUFs | 50% | 50% |
| Direct Credit Substitutes | 100% | 100% |

## Slotting Risk Weights

### Project Finance

| Category | CRR | Basel 3.1 (Pre-Op) | Basel 3.1 (Operational) |
|----------|-----|---------------------|------------------------|
| Strong | 70% | **80%** | 70% |
| Good | 70% | **100%** | 70% |
| Satisfactory | 115% | **120%** | 115% |
| Weak | 250% | **350%** | 250% |

### Other Specialised Lending

| Category | CRR | Basel 3.1 |
|----------|-----|-----------|
| Strong | 70% | 70% |
| Good | 70% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |

### HVCRE

| Category | CRR | Basel 3.1 |
|----------|-----|-----------|
| Strong | 70% | 95% |
| Good | 70% | 120% |
| Satisfactory | 115% | 140% |
| Weak | 250% | 250% |

**Note:** Under CRR, HVCRE uses the same weights as standard specialised lending (Strong=Good=70%).

## Impact Analysis

### Low-Risk Portfolios (Strong IRB Models)

```
Scenario: High-quality corporate portfolio
- PD: 0.10%
- LGD: 40%
- SA RW equivalent: 80%

CRR:
- IRB K: ~2%
- IRB RW: ~25% (after 1.06)
- Capital saving vs SA: 69%

Basel 3.1:
- IRB K: ~1.9% (no scaling)
- IRB RW: ~24%
- Floor: 80% × 72.5% = 58%
- Final RW: 58%
- Capital saving vs SA: 28%
```

### SME Portfolio

```
Scenario: £5m SME exposure, 100% SA RW

CRR:
- SME Factor: 0.811
- Effective RW: 81.1%
- Saving: 18.9%

Basel 3.1:
- SME Factor: None
- Effective RW: 100%
- Saving: 0%
```

### Infrastructure Project

```
Scenario: Qualifying infrastructure, 100% SA RW

CRR:
- Infrastructure Factor: 0.75
- Effective RW: 75%
- Saving: 25%

Basel 3.1:
- Infrastructure Factor: None
- Effective RW: 100%
- Saving: 0%
```

## Configuration Comparison

=== "CRR"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
        apply_sme_supporting_factor=True,
        apply_infrastructure_factor=True,
    )

    # Internally sets:
    # - scaling_factor: 1.06
    # - output_floor: None
    # - pd_floor: 0.0003 (uniform)
    # - lgd_floors: None
    ```

=== "Basel 3.1"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1),
        output_floor_percentage=0.725,
    )

    # Internally sets:
    # - scaling_factor: 1.0 (none)
    # - output_floor: 72.5%
    # - pd_floors: differentiated by class
    # - lgd_floors: by collateral type
    ```

## Summary of Capital Impact

| Exposure Type | CRR → Basel 3.1 Impact |
|---------------|------------------------|
| Low-risk IRB | **Increase** (output floor) |
| SME | **Increase** (factor removal) |
| Infrastructure | **Increase** (factor removal) |
| High LTV Mortgages | **Decrease** (better SA RWs) |
| Low LTV Mortgages | **Decrease** (better SA RWs) |
| High-risk Corporate | **Decrease** (CQS5 reduction) |
| Standard Corporate | Neutral |

## Transition Planning

### Key Dates

| Date | Event |
|------|-------|
| Sep 2024 | PRA PS9/24 published |
| 2025-2026 | Parallel running recommended |
| 1 Jan 2027 | Basel 3.1 effective |
| 2027-2032 | Output floor phase-in |

### Recommended Actions

1. **Impact Assessment**: Run calculations under both frameworks
2. **Data Quality**: Ensure LTV data available for SA RE
3. **Model Updates**: Review IRB models for floor compliance
4. **Process Changes**: Update reporting for dual calculation

## Next Steps

- [CRR Details](crr.md) - Current framework in depth
- [Basel 3.1 Details](basel31.md) - Future framework in depth
- [Configuration Guide](../configuration.md) - Setting up both frameworks
