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

Institution risk weights range from 20% (CQS 1) to 150% (CQS 6). Under CRR Art. 120 Table 3, CQS 2 receives **50%**. Basel 3.1 ECRA (PRA PS1/26 Art. 120 Table 3) reduces CQS 2 to **30%**.

Under CRR, unrated institutions receive **40%** via the sovereign-derived approach (Art. 121, Table 5). Under Basel 3.1, this is replaced by the **Standardised Credit Risk Assessment Approach (SCRA)** based on capital adequacy (Grade A: 40%, Grade A enhanced: 30%, Grade B: 75%, Grade C: 150%). Grade A enhanced requires CET1 ≥ 14% and leverage ratio ≥ 5%.

!!! warning "Code Divergence"
    The code currently uses 30% for CRR CQS 2 (labelled "UK deviation"). PDF verification of UK
    onshored CRR Art. 120 Table 3 confirms CQS 2 = **50%**. The 30% value is correct for Basel 3.1
    ECRA only. See D1.30 in the docs implementation plan.

> **Details:** See [Key Differences — Institution Exposures](../../framework-comparison/key-differences.md#institution-exposures) for the complete ECRA/SCRA comparison tables.

## IRB Treatment

F-IRB uses supervisory LGD (45% senior, 75% subordinated) with PD floors of 0.03% (CRR) / 0.05% (Basel 3.1). Institution correlation uses the corporate formula.

!!! warning "Basel 3.1"
    A-IRB is **no longer permitted** for institution exposures under Basel 3.1. Only SA or F-IRB may be used.

> **Details:** See [IRB Approach](../methodology/irb-approach.md) for the full formula and parameter details.

## Short-Term Exposures

Exposures with original maturity ≤ 3 months may receive preferential treatment:

| CQS | CRR RW | B31 ECRA RW | Short-Term RW |
|-----|--------|-------------|---------------|
| CQS 1 | 20% | 20% | 20% |
| CQS 2 | 50% | 30% | 20% |
| CQS 3 | 50% | 50% | 20% |
| CQS 4-5 | 100% | 100% | 50% |
| CQS 6 | 150% | 150% | 150% |

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

Covered bonds issued by institutions receive preferential treatment, ranging from 10% (CQS 1) to 50% (CQS 4-6 / unrated). Eligibility requires the issuer to be a regulated credit institution, with the bonds subject to special public supervision and backed by qualifying assets.

> **Details:** See [Key Differences — Covered Bonds](../../framework-comparison/key-differences.md#covered-bonds) for the full CQS table and CRR vs Basel 3.1 comparison.

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
# CQS 2 institution under CRR (Art. 120 Table 3)
Risk_Weight = 50%
EAD = £25,000,000
RWA = £25,000,000 × 50% = £12,500,000
# Under Basel 3.1 ECRA: 30% → RWA = £7,500,000
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
