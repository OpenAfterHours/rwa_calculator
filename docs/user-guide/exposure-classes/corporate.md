# Corporate Exposures

**Corporate exposures** are claims on companies that do not qualify as sovereigns, institutions, or retail. This includes large corporates, SMEs, and specialised lending.

## Definition

Corporate exposures include:

| Entity Type | Description |
|-------------|-------------|
| Large corporates | Companies with turnover > EUR 50m |
| Corporate SMEs | Companies with turnover ≤ EUR 50m |
| Unincorporated businesses | Partnerships, sole traders (non-retail) |
| Non-profit organisations | Charities, associations |
| Special purpose vehicles | SPVs not qualifying as specialised lending |

## SME Definition

An entity qualifies as an **SME** if:

| Criterion | Threshold (EUR) | Threshold (GBP @ 0.88) |
|-----------|-----------------|------------------------|
| Annual turnover | ≤ EUR 50m | ≤ GBP 44m |
| **OR** Total assets | ≤ EUR 43m | ≤ GBP 37.84m |

```python
def is_sme(counterparty):
    return (
        counterparty.annual_turnover <= 50_000_000 or  # EUR
        counterparty.total_assets <= 43_000_000         # EUR
    )
```

## Risk Weights (SA)

### Rated Corporates

| CQS | S&P/Fitch | Moody's | CRR | Basel 3.1 |
|-----|-----------|---------|-----|-----------|
| CQS 1 | AAA to AA- | Aaa to Aa3 | **20%** | 20% |
| CQS 2 | A+ to A- | A1 to A3 | **50%** | 50% |
| CQS 3 | BBB+ to BBB- | Baa1 to Baa3 | **75%** | 75% |
| CQS 4 | BB+ to BB- | Ba1 to Ba3 | **100%** | 100% |
| CQS 5 | B+ to B- | B1 to B3 | **150%** | **100%** |
| CQS 6 | CCC+ and below | Caa1 and below | **150%** | 150% |

### Unrated Corporates

| Framework | Risk Weight |
|-----------|-------------|
| CRR | 100% |
| Basel 3.1 | 100% |

!!! note "Investment Grade"
    Basel 3.1 introduces an "investment grade" corporate category with potentially lower risk weights for qualifying unrated corporates meeting specific criteria.

## IRB Treatment

### F-IRB Parameters

| Parameter | Source | Value |
|-----------|--------|-------|
| PD | Bank estimate | Floor 0.03% (CRR) / 0.05% (Basel 3.1) |
| LGD | Supervisory | 45% (senior), 75% (subordinated) |
| M | Effective maturity | 1-5 years |

### A-IRB Parameters

| Parameter | Source | Basel 3.1 Restrictions |
|-----------|--------|------------------------|
| PD | Bank estimate | Floor 0.05% |
| LGD | Bank estimate | Floor 25% (unsecured) |
| EAD | Bank estimate | CCF floors apply |

!!! warning "Large Corporate Restriction"
    Under Basel 3.1, corporates with consolidated revenues > EUR 500m (GBP 440m) are restricted to **F-IRB only**. A-IRB is no longer permitted for these exposures.

### Correlation

**Standard Corporate:**
```python
R = 0.12 × (1 - exp(-50 × PD)) / (1 - exp(-50)) +
    0.24 × [1 - (1 - exp(-50 × PD)) / (1 - exp(-50))]
```

**SME Correlation Adjustment:**
```python
# Size adjustment for corporates with turnover £5m-£50m
S = min(50, max(5, turnover_millions))
adjustment = 0.04 × (1 - (S - 5) / 45)
R_sme = R - adjustment
```

| Turnover (£m) | Correlation Reduction |
|---------------|----------------------|
| 5 | 4.0 pp |
| 15 | 3.1 pp |
| 25 | 2.2 pp |
| 35 | 1.3 pp |
| 45 | 0.4 pp |
| ≥50 | 0.0 pp |

## SME Supporting Factor (CRR Only)

### Eligibility

- Counterparty is SME (turnover ≤ EUR 50m)
- Exposure class: Corporate, Corporate SME, or secured by RE
- Not in default

### Tiered Calculation

```python
threshold = EUR_2_500_000  # GBP 2,200,000

if total_exposure <= threshold:
    factor = 0.7619  # 23.81% reduction
else:
    factor = (threshold × 0.7619 + (total_exposure - threshold) × 0.85) / total_exposure
```

### Factor Examples

| Total Exposure | Factor | RWA Reduction |
|----------------|--------|---------------|
| GBP 1m | 0.7619 | 23.81% |
| GBP 2.2m | 0.7619 | 23.81% |
| GBP 5m | 0.811 | 18.9% |
| GBP 10m | 0.831 | 16.9% |
| GBP 50m | 0.843 | 15.7% |

## Calculation Examples

### Example 1: Rated Large Corporate (SA)

**Exposure:**
- £75m term loan to Tesco PLC
- Rating: BBB (CQS 3)
- Undrawn commitment: £25m

**Calculation:**
```python
# Drawn portion
EAD_drawn = £75,000,000

# Undrawn (50% CCF for committed facilities)
EAD_undrawn = £25,000,000 × 50% = £12,500,000

# Total EAD
EAD = £87,500,000

# Risk weight (CQS 3)
Risk_Weight = 75%

# RWA
RWA = £87,500,000 × 75% = £65,625,000
```

### Example 2: SME with Supporting Factor (SA)

**Exposure:**
- £8m loan to regional SME
- Turnover: £30m (qualifies as SME)
- Unrated (100% RW)

**Calculation:**
```python
# Base RWA
EAD = £8,000,000
Base_RWA = £8,000,000 × 100% = £8,000,000

# SME factor (tiered)
threshold = £2,200,000
factor = (2,200,000 × 0.7619 + 5,800,000 × 0.85) / 8,000,000
factor = (1,676,180 + 4,930,000) / 8,000,000 = 0.826

# Adjusted RWA (CRR)
Adjusted_RWA = £8,000,000 × 0.826 = £6,606,400

# Basel 3.1 (no factor)
B31_RWA = £8,000,000
```

### Example 3: Corporate IRB

**Exposure:**
- £50m corporate loan
- Bank PD estimate: 0.75%
- F-IRB (LGD = 45%)
- Maturity: 4 years
- Turnover: £100m (no SME adjustment)

**Calculation:**
```python
# Step 1: PD (above floor)
PD = 0.0075

# Step 2: Correlation
R = 0.12 × (1 - exp(-50 × 0.0075)) / (1 - exp(-50)) +
    0.24 × (1 - (1 - exp(-50 × 0.0075)) / (1 - exp(-50)))
R = 0.12 × 0.313 + 0.24 × 0.687 = 0.202

# Step 3: K calculation
K ≈ 0.0445  # From IRB formula

# Step 4: Maturity adjustment
b = (0.11852 - 0.05478 × ln(0.0075))^2 = 0.149
MA = (1 + (4 - 2.5) × 0.149) / (1 - 1.5 × 0.149) = 1.29

# Step 5: RWA (CRR)
RWA_CRR = 0.0445 × 12.5 × £50,000,000 × 1.29 × 1.06
RWA_CRR = £38,107,313

# Basel 3.1 (no scaling)
RWA_B31 = £35,950,295
```

### Example 4: SME Corporate IRB

**Exposure:**
- £15m loan
- PD: 1.5%
- F-IRB (LGD = 45%)
- Maturity: 3 years
- Turnover: £20m (SME)

**Calculation:**
```python
# SME correlation adjustment
S = 20
R_base = 0.179
adjustment = 0.04 × (1 - (20 - 5) / 45) = 0.027
R_sme = 0.179 - 0.027 = 0.152

# Results in lower K, lower RWA
# Plus SME Supporting Factor on final RWA (CRR)
```

## Subordinated Debt

| Instrument Type | CRR Treatment | Basel 3.1 |
|-----------------|---------------|-----------|
| Senior unsecured | Standard corporate RW | Standard |
| Subordinated debt | Corporate RW + premium | 150% |
| Mezzanine | Corporate RW + premium | 150% |
| Equity-like | 150% | 250% |

## CRM for Corporates

### Eligible Collateral

| Collateral Type | SA | F-IRB LGD |
|-----------------|:--:|-----------|
| Cash | :white_check_mark: | 0% |
| Government bonds | :white_check_mark: | 0% |
| Corporate bonds | :white_check_mark: | Varies |
| Listed equity | :white_check_mark: | Varies |
| Real estate | :white_check_mark: | 35% |
| Receivables | :white_check_mark: | 35% |
| Other physical | Limited | 40% |

### Guarantees

Corporate exposures can benefit from guarantees by:
- Sovereigns (0% if CQS 1)
- Institutions (if better rated)
- Parent companies (under conditions)

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Corporate definition | Art. 122 | CRE20.35-40 |
| Risk weights | Art. 122 | CRE20.41-45 |
| SME definition | Art. 501(2) | N/A |
| SME factor | Art. 501 | N/A |
| IRB corporate | Art. 153 | CRE31 |
| Correlation | Art. 153(3) | CRE31.5 |

## Next Steps

- [Retail Exposures](retail.md)
- [Supporting Factors](../methodology/supporting-factors.md)
- [IRB Approach](../methodology/irb-approach.md)
