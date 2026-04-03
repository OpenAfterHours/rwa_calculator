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

| SCRA Grade | Risk Weight (>3m) | Risk Weight (≤3m) | Criteria |
|------------|--------------------|--------------------|----------|
| A | 40% | 20% | Meets all minimum requirements + buffers |
| A (enhanced) | 30% | 20% | CET1 ≥ 14% AND leverage ratio ≥ 5% |
| B | 75% | 50% | Meets minimum requirements |
| C | 150% | 150% | Below minimum requirements |

ECRA (rated) takes precedence over SCRA (unrated). SCRA does not apply under CRR.

## Equity Exposures (CRR Art. 133 / PRA PS1/26 Art. 133)

### CRR Equity Risk Weights

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Central bank/sovereign | 0% | Art. 133(1) |
| Listed/exchange-traded | 100% | Art. 133(2) |
| Government-supported | 100% | Art. 133(3) |

### Basel 3.1 Equity Risk Weights (Art. 133)

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Standard equity (listed) | 250% | Art. 133(3) |
| Higher risk (unlisted, <5yr, PE, speculative) | 400% | Art. 133(5) |
| Subordinated debt / non-equity own funds | 150% | Art. 133(1) |
| Legislative equity (govt mandate) | 100% | Art. 133(6) |
| CQS 1-2 speculative unlisted | 100% | Art. 133(4)(a) |
| CQS 3-6/unrated speculative | 150% | Art. 133(4)(b) |

**Note:** Basel 3.1 removes IRB equity approaches. All equity uses SA risk weights.

## Defaulted Exposures (CRR Art. 127 / PRA PS1/26 Art. 127)

### CRR Default Risk Weights

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ 20% of (EAD + provision_deducted) | 100% |
| Specific provisions < 20% | 150% |

### Basel 3.1 Default Risk Weights

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ 20% of exposure value | 100% |
| Specific provisions < 20% | 150% |
| RESI RE non-dependent (Art. 124F) in default | 100% (always) |

## Basel 3.1 SA Specialised Lending (Art. 122A-122B)

New Basel 3.1 SA exposure class with risk weights distinct from general corporates:

| SL Type | Phase | Risk Weight |
|---------|-------|-------------|
| Object finance | — | 100% |
| Commodities finance | — | 100% |
| Project finance | Pre-operational | 130% |
| Project finance | Operational | 100% |
| Project finance | High-quality operational | 80% |

Rated specialised lending exposures use the corporate CQS table (Art. 122A(3)).

## Other Items (CRR Art. 134 / PRA PS1/26 Art. 134)

| Item | Risk Weight |
|------|-------------|
| Cash and equivalent (notes, coins, gold bullion) | 0% |
| Items in course of collection | 20% |
| Tangible assets (premises, equipment) | 100% |
| Prepaid expenses, accrued income | 100% |
| Residual value of leased assets | 1/t × 100% (t = remaining lease years) |
| All other | 100% |

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
- **Equity** (Art. 133): 250% standard, 400% higher risk, 150% subordinated — Done
- **SA Specialised Lending** (Art. 122A-122B): OF/CF=100%, PF pre-op=130%, PF op=100% — Pending
- **Default exposures** (Art. 127): Provision-based 100%/150% with RESI RE exception — Done
- **Other items** (Art. 134): Cash=0%, collection=20%, tangible=100% — Done
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
