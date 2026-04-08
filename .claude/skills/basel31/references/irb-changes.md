# Basel 3.1 IRB Changes

All IRB parameter changes from CRR to Basel 3.1.

**Regulatory Reference:** PRA PS1/26, BCBS CRE30-36

---

## Differentiated PD Floors (Art. 163(1), CRE30.55)

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Corporate SME | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |
| QRRE (Transactors) | 0.03% | 0.05% |
| QRRE (Revolvers) | 0.03% | 0.10% |

## A-IRB LGD Floors (CRE32, Art. 161(5), 164(4))

**Corporate / Institution:**

| Collateral Type | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Unsecured (Senior) | None | 25% |
| Financial collateral | None | 0% |
| Receivables | None | 10%* |
| Commercial RE | None | 10%* |
| Residential RE | None | 10%* |
| Other physical | None | 15%* |

**Retail:**

| Exposure Type | CRR | Basel 3.1 |
|--------------|-----|-----------|
| Secured by RESI RE (flat) | None | 5% |
| QRRE unsecured | None | 50% |
| Other unsecured retail | None | 30% |
| Secured — LGDU in LGD* formula | None | 30% |
| Secured — financial collateral | None | 0% |
| Secured — receivables | None | 10%* |
| Secured — immovable property | None | 10%* |
| Secured — other physical | None | 15%* |

*PRA PS1/26 values. BCBS standard values differ slightly.

## F-IRB Supervisory LGD Changes (CRE32)

| Exposure Type | CRR | Basel 3.1 | Change |
|--------------|-----|-----------|--------|
| Financial sector entity (senior) | 45% | 45% | — |
| Other corporate (senior) | 45% | 40% | -5pp |
| Subordinated | 75% | 75% | — |
| Secured - financial collateral | 0% | 0% | — |
| Secured - receivables | 35% | 20% | -15pp |
| Secured - CRE/RRE | 35% | 20% | -15pp |
| Secured - other physical | 40% | 25% | -15pp |

## IRB Approach Restrictions (Art. 147A)

Basel 3.1 restricts IRB in two ways: complete IRB removal (SA only) and A-IRB
removal (F-IRB only). IPRE/HVCRE specialised lending is restricted to Slotting.

| Exposure Type | CRR | Basel 3.1 |
|--------------|-----|-----------|
| Central govts, central banks & quasi-sovereigns | F-IRB or A-IRB | **SA only** |
| Bank / Institution | F-IRB or A-IRB | **F-IRB only** |
| IPRE / HVCRE (Specialised Lending) | F-IRB, A-IRB, or Slotting | **Slotting only** |
| Other SL (Object/Project/Commodities) | F-IRB, A-IRB, or Slotting | F-IRB, A-IRB, or Slotting |
| Financial sector entities | F-IRB or A-IRB | **F-IRB only** |
| Large corporate (>GBP 440m) | F-IRB or A-IRB | **F-IRB only** |
| Equity | IRB | **SA only** |

Quasi-sovereign scope (Art. 147(3)): regional govts, local authorities, PSEs,
MDBs, and international organisations with 0% SA risk weight.

## Scaling Factor

- **CRR:** `RWA = K x 12.5 x EAD x MA x 1.06`
- **Basel 3.1:** `RWA = K x 12.5 x EAD x MA` (1.06 removed)

~5.7% reduction in IRB RWA (before output floor).

## UK Residential Mortgage RW Floor (PRA-specific)

Non-defaulted retail exposures secured by UK residential property: minimum **10%** risk
weight under IRB, regardless of model output. Applied as a post-model adjustment.

## A-IRB CCF Floor (CRE32.27)

Own-estimate CCFs must be at least **50% of the SA CCF** for the same item type.

A-IRB own CCFs permitted only for revolving facilities; all other items use SA CCFs.

## Post-Model Adjustments (Art. 146(3))

New concept with no CRR equivalent. When IRB models don't comply with requirements:

| PMA Component | Covers |
|---------------|--------|
| (a) Corporate/Institution RWA | Model deficiencies on corp/institution |
| (b) Retail RWA | Model deficiencies on retail |
| (c) Expected Loss | Model deficiencies affecting EL |

PMAs are included in the output floor calculation base.

## FI Correlation Multiplier

**Unchanged:** 1.25x on correlation for large/unregulated financial sector entities
(CRR Art. 153(2) / BCBS CRE31.5).

## IRB Maturity Changes (Art. 162)

| Aspect | CRR | Basel 3.1 |
|--------|-----|-----------|
| Revolving maturity | Repayment date of current drawing | Maximum contractual termination date |
| Floor/cap | 1yr / 5yr | 1yr / 5yr (unchanged) |

Revolving change typically increases M -> higher maturity adjustments -> higher capital.

---

> **Full detail:** `docs/framework-comparison/key-differences.md` and `docs/specifications/crr/airb-calculation.md`
