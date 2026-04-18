# Retail Exposures

**Retail exposures** are claims on individuals or small businesses that meet specific criteria for size, product type, and portfolio management.

## Definition

Retail exposures must meet ALL of the following criteria:

| Criterion | Requirement |
|-----------|-------------|
| **Counterparty** | Individual or small business |
| **Product** | Revolving credit, personal loans, mortgages, or small business facilities |
| **Size** | Total exposure ≤ EUR 1m (CRR, FX-converted) or ≤ GBP 880k (Basel 3.1, fixed) |
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

### SA Risk Weights

CRR uses a flat 35% (LTV ≤ 80%) or 75% (LTV > 80%). Basel 3.1 introduces LTV-based bands from 20% to 70%+ for general mortgages, and 30% to 105% for income-producing (buy-to-let).

> **Details:** See [Key Differences — Residential Real Estate](../../framework-comparison/key-differences.md#residential-real-estate) for the complete LTV tables.

### IRB Treatment

Retail mortgage correlation is fixed at 15% with no maturity adjustment. PD floors: 0.03% (CRR) / 0.10% (Basel 3.1, Art. 163(1)(b)). Basel 3.1 introduces a 5% LGD floor for residential RE.

> **Details:** See [IRB Approach](../methodology/irb-approach.md) for the full formula and parameter details.

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

| Framework | Non-Transactor | Transactor |
|-----------|----------------|------------|
| CRR | **75%** | 75% (no split) |
| Basel 3.1 | **75%** (Art. 123(3)(b)) | **45%** (Art. 123(3)(a)) |

### Transactor vs Non-Transactor (Basel 3.1)

Basel 3.1 introduces a 45% preferential SA risk weight (and a 0.05% IRB PD floor) for **transactor** QRRE exposures. The PRA Glossary (PS1/26 Appendix 1, p. 9) defines a transactor via one of two behavioural tests over the **previous 12-month period**:

1. A revolving facility (credit cards, charge cards, and similar) where the obligor has **repaid the balance in full at each scheduled repayment date for the previous 12-month period**; or
2. An **overdraft facility** that the obligor **has not drawn down over the previous 12-month period**.

Accounts that fail either test — including newly originated accounts with less than 12 months of repayment history (Art. 154(4)) — are **non-transactor** exposures. Set `is_qrre_transactor = True` in the input only when the 12-month history has been verified by the institution; the calculator does not validate the underlying behaviour. See the [Basel 3.1 SA Risk Weights spec](../../specifications/basel31/sa-risk-weights.md#transactor-exposure-eligibility-art-1233a-pra-glossary) for full details.

### IRB Treatment

QRRE correlation is fixed at 4%. PD floors: 0.03% (CRR all), 0.05% (Basel 3.1 transactors, Art. 163(1)(c)), 0.10% (Basel 3.1 revolvers). Bank-estimated LGD subject to 50% floor (Basel 3.1 unsecured). The same transactor definition (PRA Glossary) governs the IRB PD-floor split; Art. 154(4) requires any account with less than 12 months of repayment history to be classified as non-transactor for IRB purposes.

## Retail Other

### Definition

All retail exposures not qualifying as mortgage or QRRE:
- Personal loans
- Auto finance
- Consumer durable financing
- Small business facilities (below retail threshold: EUR 1m CRR / GBP 880k Basel 3.1)

### SA Risk Weight

| Framework | Risk Weight |
|-----------|-------------|
| CRR | **75%** |
| Basel 3.1 | **75%** |

### IRB Treatment

Other retail correlation is PD-dependent (3%–16%), decreasing as PD increases. No maturity adjustment for retail.

> **Details:** See [IRB Approach — Retail Correlations](../methodology/irb-approach.md#retail-correlations) for the formula and correlation values by PD.

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

## Lending Groups and Retail Threshold

### Retail Lending Groups

For retail SME exposures, total exposure is calculated across the **lending group**:
- Connected individuals/entities
- Common ownership or control
- Aggregated for threshold purposes

!!! info "CRR vs Basel 3.1 Retail Threshold"
    Under **CRR** (Art. 123(c)), the retail aggregate exposure limit is **EUR 1,000,000** dynamically
    converted to GBP at the prevailing EUR/GBP rate (default 0.8732 → ~GBP 873k). Under **Basel 3.1**
    (Art. 123(1)(b)(ii)), the PRA replaces this with a fixed **GBP 880,000** — no FX conversion
    required. This eliminates exchange rate volatility from retail classification boundaries.
    The QRRE individual limit also changes from EUR 100k to **GBP 90,000** (Art. 147(5A)(c)).
    See [Key Differences — Retail Classification Threshold](../../framework-comparison/key-differences.md#retail-exposures)
    for the full comparison.

### Residential Property Exclusion (CRR Art. 123(c))

**Important:** Exposures secured by residential property are **excluded** from the retail threshold calculation when they are assigned to the residential property exposure class under the Standardised Approach.

This exclusion applies because:
- Per CRR Art. 123(c), exposures "fully and completely secured on residential property collateral that have been assigned to the exposure class laid down in point (i) of Article 112" are excluded from the aggregation
- This means the **collateral value** (capped at the exposure amount) is deducted from the total amount owed

**Key Rules:**

| Approach | Residential Property Treatment |
|----------|-------------------------------|
| **SA** | Excluded from retail threshold; stays as residential mortgage |
| **IRB** | NOT excluded from retail threshold (per EBA Q&A 2018_4012) |

!!! info "Conceptual Logic"
    The following illustrates the residential property exclusion logic. For the actual implementation,
    see [`hierarchy.py:692-789`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/hierarchy.py#L692-L789).

```python
# Conceptual overview - actual implementation in HierarchyResolver._calculate_residential_property_coverage
def calculate_adjusted_exposure(exposures, residential_collateral):
    """
    Per CRR Art. 123(c), residential property secured exposures (SA)
    are excluded from the retail threshold calculation.
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

# Must be ≤ threshold for retail treatment
# CRR: EUR 1m (FX-converted); Basel 3.1: GBP 880k (fixed)
if adjusted_group_exposure <= retail_threshold:
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
| Retail definition | Art. 123 (CRR) / Art. 123(1) (B31) | CRE20.50-60 | - |
| Retail threshold | Art. 123(c) (EUR 1m) / Art. 123(1)(b)(ii) (GBP 880k) | CRE20.65 | 2016_2626 |
| Residential property exclusion | Art. 123(c), Art. 112(i) | - | 2013_72, 2018_4012 |
| Retail mortgage | Art. 125 | CRE20.70-75 | - |
| QRRE | Art. 154 | CRE31.10-12 | - |
| Retail IRB | Art. 154 | CRE31 | - |
| Correlation | Art. 154 | CRE31.13-15 | - |

## Next Steps

- [Other Exposure Classes](other.md)
- [IRB Approach](../methodology/irb-approach.md)
- [Credit Risk Mitigation](../methodology/crm.md)
