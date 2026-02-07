# Supporting Factors Specification

SME supporting factor and infrastructure supporting factor under CRR.

**Regulatory Reference:** CRR Articles 501, 501a

**Test Group:** CRR-F

---

!!! warning "CRR Only"
    Supporting factors are **not available under Basel 3.1**. They are disabled automatically when using the Basel 3.1 configuration.

## SME Supporting Factor (CRR Art. 501)

A tiered discount applied to RWA for qualifying SME exposures.

### Eligibility

- Counterparty must be classified as Corporate SME
- Turnover < EUR 50m (converted from GBP at the configured FX rate)
- Aggregated at counterparty level, not per-exposure

### Tiered Application

| Tier | Exposure Threshold | Factor |
|------|-------------------|--------|
| Tier 1 | Up to EUR 2.5m (GBP ~2.2m) | 0.7619 |
| Tier 2 | Above EUR 2.5m | 0.85 |

### Blended Formula

For exposures that span both tiers:

```
SF = [min(E, threshold) x 0.7619 + max(E - threshold, 0) x 0.85] / E
```

Where `E` is the total aggregated exposure and `threshold` is EUR 2.5m (or GBP equivalent).

## Infrastructure Supporting Factor (CRR Art. 501a)

A flat **0.75** factor applied to qualifying infrastructure lending exposures.

### Eligibility

- Exposure must be flagged as `is_infrastructure = true`
- Applied regardless of exposure size

## Combined Application

When both factors apply to an exposure, the calculator uses the **minimum** (most beneficial) factor.

## Key Scenarios

| Scenario ID | Description | Expected Factor |
|-------------|-------------|-----------------|
| CRR-F | SME below EUR 2.5m threshold | 0.7619 |
| CRR-F | SME above EUR 2.5m threshold | 0.85 |
| CRR-F | SME spanning both tiers | Blended |
| CRR-F | Infrastructure exposure | 0.75 |
| CRR-F | Combined SME + infrastructure | min(SME, 0.75) |
