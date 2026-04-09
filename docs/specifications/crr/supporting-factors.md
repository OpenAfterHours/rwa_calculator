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

- Turnover < EUR 50m (converted from GBP at the configured FX rate)
- Aggregated at counterparty level, not per-exposure

!!! info "Regulatory Scope vs Implementation"
    CRR Art. 501 applies the factor to **all** exposures to SMEs, including corporate, retail,
    and real-estate-secured classes. The implementation applies the factor only to exposures
    classified as `CORPORATE_SME` via the `is_sme` flag. Retail-origin entities that fail the
    retail qualification test are reclassified to `CORPORATE_SME` by the classifier and receive
    the factor (see CRR-F4). Retail-qualifying SMEs that remain in `RETAIL_OTHER`,
    `RETAIL_MORTGAGE`, or `RETAIL_QRRE` do not currently receive the Art. 501 discount — their
    75% risk weight already provides favourable treatment compared to corporate exposures.

### Tiered Application

| Tier | Exposure Threshold | Factor |
|------|-------------------|--------|
| Tier 1 | Up to EUR 2.5m (GBP ~2.2m) | 0.7619 |
| Tier 2 | Above EUR 2.5m | 0.85 |

### Blended Formula

For exposures that span both tiers:

```
SF = [min(D, threshold) x 0.7619 + max(D - threshold, 0) x 0.85] / D
```

Where `D` is the on-balance-sheet amount (`max(0, drawn_amount) + interest`) aggregated at counterparty level, and `threshold` is EUR 2.5m (or GBP equivalent).

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
| CRR-F1 | Small SME — Tier 1 only (exposure ≤ EUR 2.5m) | 0.7619 |
| CRR-F2 | Medium SME — blended tiers (exposure spans threshold) | Blended (weighted average of 0.7619 and 0.85) |
| CRR-F3 | Large SME — Tier 2 dominant (exposure well above EUR 2.5m) | → 0.85 |
| CRR-F4 | Retail-origin SME — reclassified to `CORPORATE_SME`, Tier 1 factor applied | 0.7619 |
| CRR-F5 | Infrastructure — flat factor (not tiered) | 0.75 (Art. 501a) |
| CRR-F6 | Large corporate — no SME factor (turnover > EUR 50m threshold) | 1.0 (no discount) |
| CRR-F7 | Boundary — exposure exactly at EUR 2.5m (GBP ~£2.18m) threshold | Tier 1 factor (0.7619) applies up to threshold |

!!! note "Combined Factors"
    When both SME and infrastructure factors apply, the calculator uses the minimum (most beneficial) factor. This is validated within CRR-F5 where infrastructure exposures may also qualify as SME.

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-F: Supporting Factors | F1–F7 | 15 | 100% (15/15) |
