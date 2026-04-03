# Basel 3.1 SA Risk Weights

All Basel 3.1 SA risk weight tables.

**Regulatory Reference:** PRA PS1/26 Art. 112-134, BCBS CRE20

---

## Sovereign Exposures (Art. 114)

Unchanged from CRR — same CQS table (0%/20%/50%/100%/100%/150%, unrated 100%).

## Institution Exposures (Art. 120-121, CRE20.16-21)

### ECRA — Rated Institutions

| CQS | RW (>3m) | RW (<=3m) |
|-----|----------|-----------|
| 1 | 20% | 20% |
| 2 | **30%** | 20% |
| 3 | 50% | 20% |
| 4 | 100% | 50% |
| 5 | 100% | 50% |
| 6 | 150% | 150% |

ECRA (rated) takes precedence over SCRA (unrated).

### SCRA — Unrated Institutions

| Grade | RW (>3m) | RW (<=3m) | Criteria |
|-------|----------|-----------|----------|
| A | 40% | 20% | Meets all minimum requirements + buffers |
| A (enhanced) | 30% | 20% | CET1 >= 14% AND leverage ratio >= 5% |
| B | 75% | 50% | Meets minimum requirements |
| C | 150% | 150% | Below minimum requirements |

Replaces CRR sovereign-based approach for unrated institutions.

## Corporate Exposures (Art. 122, CRE20.42-49)

| CQS | CRR RW | Basel 3.1 RW |
|-----|--------|--------------|
| 1 (AAA-AA-) | 20% | 20% |
| 2 (A+-A-) | 50% | 50% |
| 3 (BBB+-BBB-) | 100% | **75%** |
| 4 (BB+-BB-) | 100% | 100% |
| 5 (B+-B-) | 150% | **100%** |
| 6 (CCC+/below) | 150% | 150% |
| Unrated | 100% | 100% |

### Corporate Sub-Categories

| Treatment | RW | Condition |
|-----------|-----|-----------|
| Investment-grade (CRE20.44) | 65% | Unrated, investment-grade designation |
| SME corporate (CRE20.47) | 85% | Turnover <= EUR 50m, replaces CRR 100% + SF |
| Subordinated debt (CRE20.49) | 150% | Overrides all other treatments |

## Residential RE — General, Loan-Splitting (Art. 124F)

Not cash-flow dependent. PRA uses loan-splitting (not BCBS whole-loan table):

- **Secured portion** (up to 55% of property value): **20%**
- **Residual portion**: counterparty risk weight (Art. 124L)

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.20 x secured_share + counterparty_RW x (1.0 - secured_share)
```

**Counterparty risk weight (Art. 124L):**

| Counterparty Type | RW |
|-------------------|----|
| Natural person (non-SME) | 75% |
| Retail-qualifying SME | 75% |
| Other SME (unrated) | 85% |
| Social housing | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

## Residential RE — Income-Producing, Whole-Loan (Art. 124G)

Cash-flow dependent (e.g., buy-to-let):

| LTV Band | Risk Weight |
|----------|-------------|
| <= 50% | 30% |
| 50-60% | 35% |
| 60-70% | 40% |
| 70-80% | 50% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

Junior charge multiplier (Art. 124G(2)): 1.25x if LTV > 50%.

## Commercial RE — General, Loan-Splitting (Art. 124H)

Not cash-flow dependent. Natural person/SME: **60%** on portion up to 55% LTV, counterparty RW on remainder.

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.60 x secured_share + counterparty_RW x (1.0 - secured_share)
```

Other counterparties: `max(60%, min(counterparty_RW, income-producing RW))`

## Commercial RE — Income-Producing (Art. 124I)

| LTV Band | RW | Junior Charge Multiplier |
|----------|----|-------------------------|
| <= 60% | 100% | 1.0x |
| 60-80% | 100% | 1.25x |
| > 80% | 110% | 1.375x |

## Other RE (Art. 124J)

| Type | RW |
|------|----|
| Income-dependent | 150% |
| RESI non-dependent | Counterparty RW |
| CRE non-dependent | max(60%, counterparty RW) |

## ADC Exposures (Art. 124K)

| Condition | RW |
|-----------|-----|
| Default | 150% |
| Residential with pre-sales/equity | 100% |

## Retail Exposures

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| QRRE | 75% | 75% |
| Transactor | 75% | **45%** |
| Payroll/pension loans | 75% | **35%** |
| Other retail | 75% | 75% |

## Equity Exposures (Art. 133)

| Equity Type | RW |
|-------------|-----|
| Standard (listed) | 250% |
| Higher risk (unlisted, <5yr, PE, speculative) | 400% |
| Subordinated debt / non-equity own funds | 150% |
| Legislative equity (govt mandate) | 100% |

IRB equity approaches removed. SA only.

## SA Specialised Lending (Art. 122A-122B)

| SL Type | Phase | RW |
|---------|-------|----|
| Object finance | — | 100% |
| Commodities finance | — | 100% |
| Project finance | Pre-operational | 130% |
| Project finance | Operational | 100% |
| Project finance | High-quality operational | 80% |

Rated SL exposures use the corporate CQS table.

## Defaulted Exposures (Art. 127)

| Condition | RW |
|-----------|-----|
| Provisions >= 20% | 100% |
| Provisions < 20% | 150% |
| RESI RE non-dependent in default | 100% (always) |

## Other Items (Art. 134)

Unchanged from CRR (cash 0%, collection 20%, tangible 100%).

---

> **Full detail:** `docs/specifications/crr/sa-risk-weights.md` (covers both CRR + Basel 3.1)
