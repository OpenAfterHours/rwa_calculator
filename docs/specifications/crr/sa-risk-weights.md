# SA Risk Weights Specification

Standardised Approach risk weights by exposure class and credit quality step.

**Regulatory Reference:** CRR Articles 112-134

**Test Group:** CRR-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | SA risk weight calculation for all 9 exposure classes (CRR Art. 112–134) | P0 | Done |
| FR-1.2 | SA risk weight calculation for Basel 3.1 (CRE20–22), including LTV-based RE weights | P0 | Done |

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

## Basel 3.1 Residential Real Estate (PRA PS1/26 Art. 124F-124G)

### General Residential — Loan-Splitting (Art. 124F)

Not materially dependent on cash flows from the property. PRA adopted the **loan-splitting approach** (not the BCBS CRE20.73 whole-loan table):

- **Secured portion** (up to 55% of property value): **20%** risk weight
- **Residual portion** (above 55% of property value): **counterparty risk weight** (Art. 124L)

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.20 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Counterparty risk weight** (Art. 124L):

| Counterparty Type | RW |
|-------------------|----|
| Natural person (non-SME) | 75% |
| Retail-qualifying SME | 75% |
| Other SME (unrated) | 85% |
| Social housing | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

**Junior charges** (Art. 124F(2)): If a prior or pari passu charge exists, the 55% threshold is reduced by the amount of the prior charge. Not yet modelled.

### Income-Producing Residential — Whole-Loan (Art. 124G, Table 6B)

Materially dependent on cash flows from the property (e.g., buy-to-let). Whole-loan approach — single risk weight on entire exposure:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50-60% | 35% |
| 60-70% | 40% |
| 70-80% | 50% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

**Junior charge multiplier** (Art. 124G(2)): 1.25× on income-dependent RESI RE if LTV > 50% and prior/pari passu charges exist. Not yet modelled.

### Commercial RE — General, Loan-Splitting (Art. 124H)

Not materially dependent on cash flows:

**Natural person / SME**: Split approach — **60%** on portion up to 55% of property value, counterparty RW on remainder.

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.60 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Other counterparties**: `max(60%, min(counterparty_RW, Art 124I income-producing RW))`

### Commercial RE — Income-Producing (Art. 124I)

Materially dependent on cash flows:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 80% | 100% |
| > 80% | 110% |

**Junior charge multiplier** (Art. 124I(3)):

| LTV Band | Multiplier |
|----------|------------|
| ≤ 60% | 1.0× (100%) |
| 60-80% | 1.25× (125%) |
| > 80% | 1.375× (137.5%) |

### Other Real Estate (Art. 124J)

Non-regulatory real estate (doesn't meet Art. 124A requirements):

| Type | Risk Weight |
|------|-------------|
| Income-dependent | 150% |
| RESI non-dependent | Counterparty RW |
| CRE non-dependent | max(60%, counterparty RW) |

### ADC Exposures (Art. 124K)

| Condition | Risk Weight |
|-----------|-------------|
| Default | 150% |
| Residential with pre-sales/equity at risk | 100% |

## Basel 3.1 Corporate Exposures (CRE20.42-49)

| CQS | Rating Equivalent | CRR Risk Weight | Basel 3.1 Risk Weight |
|-----|-------------------|-----------------|----------------------|
| 1 | AAA to AA- | 20% | 20% |
| 2 | A+ to A- | 50% | 50% |
| 3 | BBB+ to BBB- | **100%** | **75%** |
| 4 | BB+ to BB- | 100% | 100% |
| 5 | B+ to B- | **150%** | **100%** |
| 6 | CCC+ and below | 150% | 150% |
| Unrated | — | 100% | 100% |

### Additional Basel 3.1 Corporate Treatments

| Treatment | Risk Weight | Condition |
|-----------|-------------|-----------|
| Investment-grade corporate (CRE20.44) | 65% | Unrated, investment-grade designation |
| SME corporate (CRE20.47) | 85% | SME qualifying corporate (replaces CRR 100% + 0.7619 SF) |
| Subordinated debt (CRE20.49) | 150% | Overrides all other treatments |

## Basel 3.1 Institution Exposures (CRE20.16-21)

Rated institutions use ECRA (same CQS table as CRR, including UK CQS 2 = 30% deviation). Unrated institutions use SCRA:

| SCRA Grade | Risk Weight | Criteria |
|------------|-------------|----------|
| A | 40% | CET1 > 14%, Leverage > 5% |
| B | 75% | CET1 > 5.5%, Leverage > 3% |
| C | 150% | Below minimum requirements |

ECRA (rated) takes precedence over SCRA (unrated). SCRA does not apply under CRR.

## Basel 3.1 Changes Summary

- **Residential RE loan-splitting** (Art. 124F): 20% on ≤55% LTV, counterparty RW on residual — Done
- **Residential RE income-producing** (Art. 124G): Whole-loan LTV table (30%-105%) — Done
- **Commercial RE loan-splitting** (Art. 124H): 60% on ≤55% LTV, counterparty RW on residual — Done
- **Commercial RE income-producing** (Art. 124I): 100%/110% at ≤80%/>80% — Done
- **Revised corporate CQS mapping** (CRE20.42): CQS 3 from 100% to 75%, CQS 5 from 150% to 100% — Done
- **SCRA for unrated institutions** (CRE20.18): Grade A/B/C risk weights replace flat 40% — Done
- **Investment-grade corporates** (CRE20.44): 65% for unrated investment-grade — Done
- **SME corporate** (CRE20.47): 85% flat weight, replaces CRR 100% + supporting factor — Done
- **Subordinated debt** (CRE20.49): 150% flat, overrides all other treatments — Done
- **Removal of SME supporting factor**: No longer applicable under Basel 3.1
- **Removal of 1.06 scaling factor**: Scaling factor set to 1.0 under Basel 3.1

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| CRR-A1 | UK Sovereign CQS 1 | 0% |
| CRR-A4 | UK Institution CQS 2 (UK deviation) | 30% |
| CRR-A | Corporate unrated | 100% |
| CRR-A | Retail exposure | 75% |
| CRR-A | Residential mortgage LTV 60% | 35% |
| CRR-A | CRE with income cover, LTV 45% | 50% |
| B31-A2 | Corporate CQS 2 (Basel 3.1) | 50% |
| B31-A3 | UK Institution CQS 2 (Basel 3.1 ECRA) | 30% |
| B31-A8 | SME corporate (Basel 3.1) | 85% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 100% (14/14) |
| B31-A: Basel 3.1 SA | A1–A10 | 14 | 100% (14/14) |
