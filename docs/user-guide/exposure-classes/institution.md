# Institution Exposures

**Institution exposures** are claims on banks, investment firms, and other regulated financial institutions.

## Definition

Institution exposures include:

| Entity Type | Description |
|-------------|-------------|
| Credit institutions | Banks, building societies |
| Investment firms | Broker-dealers, asset managers |
| Central counterparties (CCPs) | Clearing houses |
| Financial holding companies | Bank holding companies |
| Insurance companies | Subject to certain conditions |

## Risk Weights (SA)

### External Credit Risk Assessment Approach (ECRA)

| CQS | S&P/Fitch | Moody's | CRR Risk Weight | Basel 3.1 |
|-----|-----------|---------|-----------------|-----------|
| CQS 1 | AAA to AA- | Aaa to Aa3 | **20%** | 20% |
| CQS 2 | A+ to A- | A1 to A3 | **30%*** | 30% |
| CQS 3 | BBB+ to BBB- | Baa1 to Baa3 | **50%** | 50% |
| CQS 4 | BB+ to BB- | Ba1 to Ba3 | **100%** | 100% |
| CQS 5 | B+ to B- | B1 to B3 | **100%** | 100% |
| CQS 6 | CCC+ and below | Caa1 and below | **150%** | 150% |

*UK deviation: CQS 2 receives 30% RW instead of standard Basel 50%

### Unrated Institutions

**CRR:** Apply due diligence assessment
**Basel 3.1:** Use Standardised Credit Risk Assessment Approach (SCRA)

### SCRA (Basel 3.1)

| Grade | Criteria | Risk Weight |
|-------|----------|-------------|
| A | CET1 > 14%, Leverage > 5%, meets requirements | **40%** |
| B | CET1 > 5.5%, Leverage > 3%, meets minimums | **75%** |
| C | Below minimum requirements | **150%** |

```python
# SCRA classification
if cet1_ratio > 0.14 and leverage_ratio > 0.05:
    scra_grade = "A"
    risk_weight = 0.40
elif cet1_ratio > 0.055 and leverage_ratio > 0.03:
    scra_grade = "B"
    risk_weight = 0.75
else:
    scra_grade = "C"
    risk_weight = 1.50
```

## IRB Treatment

### F-IRB Parameters

| Parameter | Source | Value |
|-----------|--------|-------|
| PD | Bank estimate | Floor 0.03% (CRR) / 0.05% (Basel 3.1) |
| LGD | Supervisory | 45% (senior), 75% (subordinated) |
| M | Effective maturity | 1-5 years |

### A-IRB Restrictions

!!! warning "Basel 3.1"
    A-IRB is **no longer permitted** for institution exposures under Basel 3.1. Only SA or F-IRB may be used.

### Correlation

```python
# Institution correlation (same as corporate)
R = 0.12 × (1 - exp(-50 × PD)) / (1 - exp(-50)) +
    0.24 × [1 - (1 - exp(-50 × PD)) / (1 - exp(-50))]
```

## Short-Term Exposures

Exposures with original maturity ≤ 3 months may receive preferential treatment:

| CQS | Standard RW | Short-Term RW |
|-----|-------------|---------------|
| CQS 1 | 20% | 20% |
| CQS 2 | 30% | 20% |
| CQS 3 | 50% | 20% |
| CQS 4-6 | 100-150% | 50% |

**Eligibility:**
- Original maturity ≤ 3 months
- Funded in domestic currency
- Cleared through domestic payments system

## Interbank Exposures

### Due From Banks

| Exposure Type | Treatment |
|---------------|-----------|
| Nostro balances | Standard institution RW |
| Interbank loans | Standard institution RW |
| Money market placements | May qualify for short-term |
| Repo/reverse repo | CRM treatment may apply |

### Trade Finance

| Item | CCF | Risk Weight |
|------|-----|-------------|
| Documentary credits | 20% | Institution RW |
| Standby LCs | 50-100% | Institution RW |
| Guarantees | 100% | Institution RW |

## Covered Bonds

Covered bonds issued by institutions receive preferential treatment:

| CQS of Covered Bond | Risk Weight |
|---------------------|-------------|
| CQS 1 | 10% |
| CQS 2 | 20% |
| CQS 3 | 20% |
| CQS 4-6 | 50% |
| Unrated | 50% |

**Eligibility criteria:**
- Issued by eligible credit institution
- Subject to special public supervision
- Backed by qualifying assets (mortgages, PSE exposures)
- Overcollateralization requirements met

## Central Counterparties (CCPs)

### Qualifying CCPs (QCCPs)

| Exposure Type | Risk Weight |
|---------------|-------------|
| Trade exposures | 2% |
| Default fund contributions | Risk-sensitive calculation |

### Non-QCCPs

| Exposure Type | Treatment |
|---------------|-----------|
| Trade exposures | Bilateral institution RW |
| Default fund contributions | 1250% (or deduction) |

## CRM for Institutions

### Bank Guarantees

Exposures guaranteed by better-rated institutions:

```python
if guarantee.type == "INSTITUTION" and guarantee.cqs < counterparty.cqs:
    # Substitution approach
    guaranteed_rw = institution_risk_weight(guarantee.cqs)
```

### Bank Collateral

Bonds issued by institutions as collateral:

| Collateral Rating | Haircut (1-5yr) |
|-------------------|-----------------|
| CQS 1-2 | 4% |
| CQS 3 | 6% |
| CQS 4+ | Not eligible |

## Calculation Examples

**Example 1: Rated Bank**
- £25m placement with Deutsche Bank
- Rating: A+ (CQS 2)
- Maturity: 6 months

```python
# CQS 2 institution under CRR
Risk_Weight = 30%  # UK deviation
EAD = £25,000,000
RWA = £25,000,000 × 30% = £7,500,000
```

**Example 2: Unrated Bank (Basel 3.1)**
- £10m loan to regional bank
- No external rating
- SCRA assessment: CET1 = 16%, Leverage = 6%

```python
# SCRA Grade A
Risk_Weight = 40%
RWA = £10,000,000 × 40% = £4,000,000
```

**Example 3: Short-Term**
- £50m overnight placement
- Counterparty: CQS 3 bank
- Original maturity: 1 day

```python
# Short-term preferential treatment
Risk_Weight = 20%  # vs. standard 50%
RWA = £50,000,000 × 20% = £10,000,000
```

## Subordinated Debt

Exposures to subordinated debt of institutions:

| Instrument Type | CRR | Basel 3.1 |
|-----------------|-----|-----------|
| Tier 2 instruments | Institution RW + premium | 150% |
| AT1 instruments | Institution RW + premium | 150% |
| Equity-like | 150% | 250% |

## Regulatory References

| Topic | CRR Article | BCBS CRE |
|-------|-------------|----------|
| Institution definition | Art. 119 | CRE20.15-20 |
| Risk weights | Art. 119-121 | CRE20.21-25 |
| Short-term treatment | Art. 119(2) | CRE20.26 |
| Covered bonds | Art. 129 | CRE20.27-30 |
| CCPs | Art. 300-311 | CRE54 |

## Next Steps

- [Corporate Exposures](corporate.md)
- [Standardised Approach](../methodology/standardised-approach.md)
- [Credit Risk Mitigation](../methodology/crm.md)
