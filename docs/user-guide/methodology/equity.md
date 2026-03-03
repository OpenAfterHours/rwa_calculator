# Equity Exposures

**Equity exposures** receive dedicated risk weight treatment separate from credit risk. Under CRR, the calculator supports SA (Article 133) and IRB Simple (Article 155). Under Basel 3.1, only SA applies.

## Overview

Equity exposures are routed directly from classification to the equity calculator, bypassing CRM processing (collateral is not applied to equity holdings).

```mermaid
flowchart LR
    A[Classified Exposures] --> B{Exposure Class}
    B -->|Equity| C[Equity Calculator]
    B -->|Other| D[CRM Processor]
    C --> E[Aggregator]
    D --> E
```

## Article 133 - Standardised Approach (SA)

The default approach for firms without IRB approval. Risk weights are based on equity type:

| Equity Type | Risk Weight | Description |
|-------------|-------------|-------------|
| Central bank | 0% | Central bank equity holdings |
| Listed / Exchange-traded | 100% | Publicly traded on recognised exchanges |
| Government-supported | 100% | Government-backed equity investments |
| Unlisted / Private equity | 250% | Non-publicly traded equities |
| Speculative | 400% | Venture capital, high-risk investments |

**Calculation:**
```
RWA = EAD x Risk Weight
```

## Article 155 - IRB Simple Risk Weight Method

For firms with IRB permission, a different risk weight schedule applies:

| Equity Type | Risk Weight | Description |
|-------------|-------------|-------------|
| Central bank | 0% | Central bank equity holdings |
| Private equity (diversified) | 190% | Diversified portfolio treatment |
| Government-supported | 190% | Government-backed equity investments |
| Exchange-traded / Listed | 290% | Publicly traded equities |
| Unlisted / Private equity | 370% | Non-publicly traded equities |
| Speculative / CIU | 370% | Venture capital, collective investments |
| Other equity | 370% | All other equity holdings |

### Diversified Portfolio Treatment

Private equity holdings in a diversified portfolio receive a reduced risk weight of **190%** (vs 370% for non-diversified). This is flagged via the `is_diversified_portfolio` attribute.

!!! note "CRR Only"
    The IRB Simple Risk Weight Method (Article 155) applies only under CRR. Under Basel 3.1, all equity exposures use Article 133 SA treatment.

## Approach Determination

The equity approach depends on the regulatory framework and IRB permissions:

| Framework | IRB Permission | Equity Approach |
|-----------|----------------|-----------------|
| CRR | SA only | Article 133 (SA) |
| CRR | IRB permitted | Article 155 (IRB Simple) |
| Basel 3.1 | Any | Article 133 (SA) — IRB equity removed |

## Example

**Equity holding:** Listed shares, £2m

**SA Treatment (Article 133):**
```
RWA = £2,000,000 x 100% = £2,000,000
```

**IRB Simple Treatment (Article 155):**
```
RWA = £2,000,000 x 290% = £5,800,000
```

## Regulatory References

| Topic | Reference |
|-------|-----------|
| SA equity treatment | CRR Art. 133 |
| IRB simple risk weight | CRR Art. 155 |
| Strategic equity treatment | EBA Q&A 2023_6716 |
