# Retail Exposures

**Retail exposures** are claims on individuals or small businesses that meet specific criteria for size, product type, and portfolio management.

## Definition

Retail exposures must meet ALL of the following criteria:

| Criterion | Requirement |
|-----------|-------------|
| **Counterparty** | Individual or small business |
| **Product** | Revolving credit, personal loans, mortgages, or small business facilities |
| **Size** | Total exposure ≤ EUR 1m (GBP 880k) |
| **Management** | Managed as part of a portfolio with similar characteristics |

```python
def is_retail(exposure, counterparty):
    return (
        counterparty.type in ["INDIVIDUAL", "SMALL_BUSINESS"] and
        total_exposure(counterparty) <= 1_000_000 and  # EUR
        is_managed_as_retail_pool(exposure)
    )
```

## Retail Sub-Classes

| Sub-Class | Description | IRB Correlation |
|-----------|-------------|-----------------|
| **Retail Mortgage** | Residential mortgages | 15% |
| **Retail QRRE** | Qualifying revolving retail | 4% |
| **Retail Other** | All other retail | 3-16% |

## Retail Mortgage

### Definition

Exposures secured by residential property that is or will be:
- Occupied by the borrower, OR
- Rented out

### SA Risk Weights (CRR)

| Criterion | Risk Weight |
|-----------|-------------|
| LTV ≤ 80%, performing | **35%** |
| LTV > 80% | **75%** |
| Non-performing | **100%** |

### SA Risk Weights (Basel 3.1)

**Whole Loan Approach:**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 50% | **20%** |
| 50-60% | **25%** |
| 60-70% | **30%** |
| 70-80% | **40%** |
| 80-90% | **50%** |
| 90-100% | **70%** |
| > 100% | Counterparty RW |

**Income-Producing (Buy-to-Let):**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 50% | **30%** |
| 50-60% | **35%** |
| 60-70% | **45%** |
| 70-80% | **60%** |
| 80-90% | **75%** |
| 90-100% | **105%** |
| > 100% | Counterparty RW |

### IRB Treatment

**Parameters:**
- PD: Bank estimate (floor 0.03% CRR / 0.05% Basel 3.1)
- LGD: Bank estimate (floor 10% Basel 3.1)
- Correlation: **15%** (fixed)

```python
# Retail mortgage correlation (fixed)
R = 0.15
```

**No maturity adjustment** for retail exposures.

## QRRE (Qualifying Revolving Retail Exposures)

### Definition

To qualify as QRRE, ALL criteria must be met:

| Criterion | Requirement |
|-----------|-------------|
| **Counterparty** | Individual (not corporate) |
| **Product** | Revolving credit line |
| **Maximum limit** | ≤ EUR 100,000 |
| **Security** | Unsecured |
| **Cancellability** | Unconditionally cancellable |

Examples:
- Credit cards
- Personal overdrafts
- Revolving personal lines

### SA Risk Weight

| Framework | Risk Weight |
|-----------|-------------|
| CRR | **75%** |
| Basel 3.1 | **45-75%** (depends on transactor/revolver status) |

**Basel 3.1 Transactor/Revolver:**

| Type | Definition | Risk Weight |
|------|------------|-------------|
| Transactor | Pays full balance monthly | 45% |
| Revolver | Carries balance | 75% |

### IRB Treatment

**Parameters:**
- PD: Bank estimate
  - Floor: 0.03% (CRR/Basel 3.1 transactor)
  - Floor: 0.10% (Basel 3.1 revolver)
- LGD: Bank estimate
- Correlation: **4%** (fixed)

```python
# QRRE correlation (fixed, low due to diversification)
R = 0.04
```

## Retail Other

### Definition

All retail exposures not qualifying as mortgage or QRRE:
- Personal loans
- Auto finance
- Consumer durable financing
- Small business facilities (< EUR 1m total exposure)

### SA Risk Weight

| Framework | Risk Weight |
|-----------|-------------|
| CRR | **75%** |
| Basel 3.1 | **75%** |

### IRB Treatment

**Parameters:**
- PD: Bank estimate (floor 0.03% CRR / 0.05% Basel 3.1)
- LGD: Bank estimate (floor varies by collateral)
- Correlation: **PD-dependent** (3% to 16%)

```python
# Other retail correlation formula
R = 0.03 × (1 - exp(-35 × PD)) / (1 - exp(-35)) +
    0.16 × [1 - (1 - exp(-35 × PD)) / (1 - exp(-35))]
```

| PD | Correlation |
|----|-------------|
| 0.03% | 16% |
| 0.5% | 12.4% |
| 2% | 7.2% |
| 10% | 3.6% |
| 20%+ | 3% |

## Calculation Examples

### Example 1: Residential Mortgage (SA)

**Exposure:**
- £250,000 mortgage
- Property value: £350,000
- LTV: 71.4%
- Owner-occupied

**CRR Calculation:**
```python
# LTV ≤ 80%, so 35% RW
Risk_Weight = 35%
EAD = £250,000
RWA = £250,000 × 35% = £87,500
```

**Basel 3.1 Calculation:**
```python
# LTV 70-80% band
Risk_Weight = 40%
RWA = £250,000 × 40% = £100,000
```

### Example 2: Credit Card (QRRE)

**Exposure:**
- £15,000 credit limit
- £8,000 current balance
- Unconditionally cancellable
- Revolver (carries balance)

**CRR Calculation:**
```python
# QRRE 75% RW
# CCF = 0% for unconditionally cancellable (CRR)
EAD = £8,000  # Current balance only
Risk_Weight = 75%
RWA = £8,000 × 75% = £6,000
```

**Basel 3.1 Calculation:**
```python
# CCF = 10% for unconditionally cancellable
Undrawn = £15,000 - £8,000 = £7,000
EAD = £8,000 + (£7,000 × 10%) = £8,700

# Revolver = 75% RW
Risk_Weight = 75%
RWA = £8,700 × 75% = £6,525
```

### Example 3: Retail IRB

**Exposure:**
- £50,000 personal loan
- Bank PD: 2%
- Bank LGD: 40%
- "Other retail" category

**Calculation:**
```python
# Correlation (PD = 2%)
R = 0.03 × (1 - exp(-35 × 0.02)) / (1 - exp(-35)) +
    0.16 × (1 - (1 - exp(-35 × 0.02)) / (1 - exp(-35)))
R = 0.072  # 7.2%

# K calculation (no maturity adjustment for retail)
K ≈ 0.0285

# RWA
RWA = K × 12.5 × EAD
RWA = 0.0285 × 12.5 × £50,000
RWA = £17,813

# Risk Weight equivalent
RW = 35.6%
```

## Lending Groups

### Retail Lending Groups

For retail SME exposures, total exposure is calculated across the **lending group**:
- Connected individuals/entities
- Common ownership or control
- Aggregated for threshold purposes

```python
# Total exposure to lending group
total_group_exposure = sum(
    exposure for entity in lending_group
    for exposure in entity.exposures
)

# Must be ≤ EUR 1m for retail treatment
if total_group_exposure <= 1_000_000:
    treatment = "RETAIL"
else:
    treatment = "CORPORATE_SME"
```

## CRM for Retail

### Eligible Collateral

| Collateral Type | Treatment |
|-----------------|-----------|
| Residential property | Mortgage RW |
| Financial collateral | Haircut method |
| Physical collateral | LGD reduction (IRB) |

### Guarantees

Limited guarantee recognition for retail:
- Government guarantees accepted
- Institution guarantees under conditions
- Individual guarantees generally not recognized

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Retail definition | Art. 123 | CRE20.50-60 |
| Retail mortgage | Art. 125 | CRE20.70-75 |
| QRRE | Art. 154 | CRE31.10-12 |
| Retail IRB | Art. 154 | CRE31 |
| Correlation | Art. 154 | CRE31.13-15 |

## Next Steps

- [Other Exposure Classes](other.md)
- [IRB Approach](../methodology/irb-approach.md)
- [Credit Risk Mitigation](../methodology/crm.md)
