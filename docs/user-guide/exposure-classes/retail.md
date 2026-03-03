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

!!! info "Conceptual Logic"
    The following illustrates the retail classification decision logic. For the actual implementation,
    see [`classifier.py:285-392`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/classifier.py#L285-L392).

```python
# Conceptual overview - actual implementation in ExposureClassifier._apply_retail_classification
def is_retail(exposure, counterparty, lending_group_adjusted_exposure):
    return (
        counterparty.type in ["individual", "retail", "small_business"] and
        lending_group_adjusted_exposure <= 1_000_000 and  # EUR threshold
        is_managed_as_retail_pool(exposure)  # cp_is_managed_as_retail flag
    )
```

??? example "Actual Implementation (classifier.py)"
    ```python
    --8<-- "src/rwa_calc/engine/classifier.py:285:343"
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
| Basel 3.1 | **75%** |

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

## Lending Groups and EUR 1m Threshold

### Retail Lending Groups

For retail SME exposures, total exposure is calculated across the **lending group**:
- Connected individuals/entities
- Common ownership or control
- Aggregated for threshold purposes

### Residential Property Exclusion (CRR Art. 123(c))

**Important:** Exposures secured by residential property are **excluded** from the EUR 1m threshold calculation when they are assigned to the residential property exposure class under the Standardised Approach.

This exclusion applies because:
- Per CRR Art. 123(c), exposures "fully and completely secured on residential property collateral that have been assigned to the exposure class laid down in point (i) of Article 112" are excluded from the aggregation
- This means the **collateral value** (capped at the exposure amount) is deducted from the total amount owed

**Key Rules:**

| Approach | Residential Property Treatment |
|----------|-------------------------------|
| **SA** | Excluded from EUR 1m threshold; stays as residential mortgage |
| **IRB** | NOT excluded from EUR 1m threshold (per EBA Q&A 2018_4012) |

!!! info "Conceptual Logic"
    The following illustrates the residential property exclusion logic. For the actual implementation,
    see [`hierarchy.py:692-789`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/hierarchy.py#L692-L789).

```python
# Conceptual overview - actual implementation in HierarchyResolver._calculate_residential_property_coverage
def calculate_adjusted_exposure(exposures, residential_collateral):
    """
    Per CRR Art. 123(c), residential property secured exposures (SA)
    are excluded from the EUR 1m retail threshold calculation.
    """
    for exposure in exposures:
        # Get residential collateral securing this exposure
        res_collateral_value = residential_collateral.get(exposure.id, 0)

        # Cap at exposure amount (can't exclude more than exposure)
        exclusion = min(res_collateral_value, exposure.amount)

        # Adjusted exposure for threshold
        exposure.for_retail_threshold = exposure.amount - exclusion

    return exposures
```

??? example "Actual Implementation (hierarchy.py)"
    The real implementation uses Polars LazyFrames for efficient processing:

    ```python
    --8<-- "src/rwa_calc/engine/hierarchy.py:692:789"
    ```

**Lending Group Threshold Check:**

```python
# Total adjusted exposure to lending group (from hierarchy resolver)
adjusted_group_exposure = sum(
    exp.exposure_for_retail_threshold for entity in lending_group
    for exp in entity.exposures
)

# Must be ≤ EUR 1m for retail treatment
if adjusted_group_exposure <= 1_000_000:
    treatment = "RETAIL"
else:
    treatment = "CORPORATE_SME"  # SMEs retain firm-size adjustment
```

### Treatment When Threshold Exceeded

| Counterparty Type | Exceeds Threshold | Treatment |
|-------------------|-------------------|-----------|
| **Individual (mortgage)** | Yes | Stays as RETAIL_MORTGAGE (SA Art. 112(i)) |
| **Individual (other)** | Yes | Reclassified to CORPORATE |
| **SME (any product)** | Yes | Reclassified to CORPORATE_SME |

**Regulatory References:**
- CRR Art. 123(c) - Retail exclusion for residential property
- EBA Q&A 2013_72 - SA residential property exclusion clarification
- EBA Q&A 2018_4012 - IRB residential property NOT excluded

### Example: Threshold Calculation with Exclusion

**Scenario:** Lending group with EUR 2m total exposure

| Exposure | Amount | Residential Collateral | For Threshold |
|----------|--------|----------------------|---------------|
| Term loan | EUR 1m | EUR 0 | EUR 1m |
| Mortgage | EUR 1m | EUR 1m | EUR 0 |
| **Total** | **EUR 2m** | | **EUR 1m** |

**Result:** Adjusted exposure = EUR 1m (at threshold) - qualifies as retail

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

| Topic | CRR Article | BCBS CRE | EBA Q&A |
|-------|-------------|----------|---------|
| Retail definition | Art. 123 | CRE20.50-60 | - |
| EUR 1m threshold | Art. 123(c) | CRE20.65 | 2016_2626 |
| Residential property exclusion | Art. 123(c), Art. 112(i) | - | 2013_72, 2018_4012 |
| Retail mortgage | Art. 125 | CRE20.70-75 | - |
| QRRE | Art. 154 | CRE31.10-12 | - |
| Retail IRB | Art. 154 | CRE31 | - |
| Correlation | Art. 154 | CRE31.13-15 | - |

## Next Steps

- [Other Exposure Classes](other.md)
- [IRB Approach](../methodology/irb-approach.md)
- [Credit Risk Mitigation](../methodology/crm.md)
