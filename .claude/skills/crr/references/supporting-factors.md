# CRR Supporting Factors

Quick-reference for SME and infrastructure supporting factors.

**Regulatory Reference:** CRR Articles 501, 501a

**CRR only** — supporting factors are removed under Basel 3.1.

---

## SME Supporting Factor (Art. 501)

### Eligibility

- Counterparty classified as Corporate SME
- Group turnover < EUR 50m (converted from GBP)

### Tiered Application

| Tier | Exposure Threshold | Factor |
|------|-------------------|--------|
| Tier 1 | Up to EUR 2.5m (~GBP 2.2m) | 0.7619 |
| Tier 2 | Above EUR 2.5m | 0.85 |

### Blended Formula

For exposures spanning both tiers:

```
SF = [min(D, threshold) x 0.7619 + max(D - threshold, 0) x 0.85] / D
```

Where D = on-balance-sheet amount aggregated at counterparty level.

## Infrastructure Supporting Factor (Art. 501a)

Flat **0.75** factor for qualifying infrastructure lending.

- Applied regardless of exposure size
- Exposure must be flagged as `is_infrastructure = true`

## Combined Application

When both factors apply, the calculator uses the **minimum** (most beneficial) factor.

---

> **Full detail:** `docs/specifications/crr/supporting-factors.md`
