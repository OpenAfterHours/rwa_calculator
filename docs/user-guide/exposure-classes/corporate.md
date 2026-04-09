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

Corporate risk weights range from 20% (CQS 1) to 150% (CQS 6), with 100% for unrated. Basel 3.1 reduces CQS 3 from 100% to 75%. PRA PS1/26 Art. 122(2) Table 6 retains CQS 5 at 150% (BCBS CRE20.42 reduced to 100%, but the PRA did not adopt this reduction). Basel 3.1 also introduces new sub-categories: investment grade (65%) and SME corporate (85%).

Basel 3.1 additionally introduces a **short-term corporate ECAI table** (Art. 122(3), Table 6A) for exposures with a specific short-term credit assessment: CQS 1 = 20%, CQS 2 = 50%, CQS 3 = 100%, Others = 150%. CRR has no equivalent short-term corporate table. This feature is not yet implemented in the calculator.

> **Details:** See [Key Differences — Corporate](../../framework-comparison/key-differences.md#corporate) for the complete CRR vs Basel 3.1 comparison, new sub-categories, and Table 6A.

## IRB Treatment

F-IRB uses supervisory LGD (45% senior, 75% subordinated) with PD floors of 0.03% (CRR) / 0.05% (Basel 3.1). SME corporates (turnover €5m–€50m) benefit from a correlation reduction of up to 4 percentage points.

!!! warning "Large Corporate Restriction"
    Under Basel 3.1, corporates with consolidated revenues > EUR 500m (GBP 440m) are restricted to **F-IRB only**. A-IRB is no longer permitted for these exposures.

> **Details:** See [IRB Approach](../methodology/irb-approach.md) for the full formula, correlation, maturity adjustment, and SME size adjustment details.

## SME Supporting Factor (CRR Only)

Eligible SME corporates (turnover ≤ EUR 50m, not in default) receive a tiered RWA reduction: 0.7619 for the first ~GBP 2.2m of exposure, 0.85 for the remainder. This factor is **removed** under Basel 3.1.

> **Details:** See [Supporting Factors](../methodology/supporting-factors.md) for the full eligibility criteria, calculation formula, and worked examples.

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
