# SA Risk Weights Specification

Standardised Approach risk weights by exposure class and credit quality step.

**Regulatory Reference:** CRR Articles 112-134

**Test Group:** CRR-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | SA risk weight calculation for all 9 exposure classes (CRR Art. 112–134) | P0 | Done |
| FR-1.2 | SA risk weight calculation for Basel 3.1 (CRE20–22), including LTV-based RE weights | P0 | Partial (RE done) |

---

## Sovereign Exposures (CRR Art. 114)

| CQS | Rating Equivalent | Risk Weight |
|-----|-------------------|-------------|
| 1 | AAA to AA- | 0% |
| 2 | A+ to A- | 20% |
| 3 | BBB+ to BBB- | 50% |
| 4 | BB+ to BB- | 100% |
| 5 | B+ to B- | 100% |
| 6 | CCC+ and below | 150% |
| Unrated | — | 100% |

## Institution Exposures (CRR Art. 120-121)

!!! note "UK Deviation"
    CQS 2 institutions receive a 30% risk weight under the UK CRR, rather than the standard 50% under EU CRR.

| CQS | Risk Weight (UK) | Risk Weight (EU Standard) |
|-----|-------------------|--------------------------|
| 1 | 20% | 20% |
| 2 | **30%** | 50% |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% | 100% |

UK unrated institutions default to 40% (derived from sovereign CQS 2).

## Corporate Exposures (CRR Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 150% |
| 6 | 150% |
| Unrated | 100% |

## Retail Exposures (CRR Art. 123)

All qualifying retail exposures receive a flat **75%** risk weight.

## Residential Mortgage Exposures (CRR Art. 125)

Risk weight depends on LTV ratio with a split at 80%:

| LTV | Treatment |
|-----|-----------|
| LTV ≤ 80% | 35% on whole exposure |
| LTV > 80% | Split: 35% on portion up to 80% LTV, 75% on excess |

**Blended formula for LTV > 80%:**

```
avg_RW = 0.35 x (0.80 / LTV) + 0.75 x ((LTV - 0.80) / LTV)
```

## Commercial Real Estate (CRR Art. 126)

| Condition | Risk Weight |
|-----------|-------------|
| LTV ≤ 50% and rental income ≥ 1.5x interest costs | 50% |
| All other CRE | 100% |

## Basel 3.1 Residential Real Estate (CRE20.73)

### General Residential (CRE20.73)

Whole-loan approach (PRA PS9/24):

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 20% |
| 50-60% | 25% |
| 60-70% | 25% |
| 70-80% | 30% |
| 80-90% | 40% |
| 90-100% | 50% |
| > 100% | 70% |

### Income-Producing Residential (CRE20.82)

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50-60% | 35% |
| 60-70% | 45% |
| 70-80% | 50% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

### Commercial RE — General (CRE20.85)

| Condition | Risk Weight |
|-----------|-------------|
| LTV ≤ 60% | min(60%, counterparty RW) |
| LTV > 60% | Counterparty RW |

### Commercial RE — Income-Producing (CRE20.86)

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 60% | 70% |
| 60-80% | 90% |
| > 80% | 110% |

### ADC Exposures (CRE20.87-88)

| Condition | Risk Weight |
|-----------|-------------|
| Default | 150% |
| Pre-sold/pre-let | 100% |

## Basel 3.1 Changes

- **LTV-based residential RE weights** (CRE20.71): Risk weights vary by loan-to-value ratio — Done
- **Revised corporate/bank risk weights**: Updated CQS mapping — Partial
- **Removal of SME supporting factor**: No longer applicable
- **Removal of 1.06 scaling factor**: Scaling factor set to 1.0

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| CRR-A1 | UK Sovereign CQS 1 | 0% |
| CRR-A4 | UK Institution CQS 2 (UK deviation) | 30% |
| CRR-A | Corporate unrated | 100% |
| CRR-A | Retail exposure | 75% |
| CRR-A | Residential mortgage LTV 60% | 35% |
| CRR-A | CRE with income cover, LTV 45% | 50% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 86% (12/14, 2 skip) |

Skipped: A7 (commercial RE), A8 (OBS CCF)
