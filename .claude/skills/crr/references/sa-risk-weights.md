# CRR SA Risk Weights

Quick-reference tables for all CRR SA risk weights by exposure class.

**Regulatory Reference:** CRR Articles 112-134

---

## Sovereign Exposures (Art. 114)

| CQS | Rating Equivalent | Risk Weight |
|-----|-------------------|-------------|
| 1 | AAA to AA- | 0% |
| 2 | A+ to A- | 20% |
| 3 | BBB+ to BBB- | 50% |
| 4 | BB+ to BB- | 100% |
| 5 | B+ to B- | 100% |
| 6 | CCC+ and below | 150% |
| Unrated | — | 100% |

## Institution Exposures (Art. 120-121)

**UK Deviation:** CQS 2 institutions receive **30%** (not 50% as in EU CRR).

| CQS | Risk Weight (UK) |
|-----|------------------|
| 1 | 20% |
| 2 | **30%** |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 40% |

## Corporate Exposures (Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 150% |
| 6 | 150% |
| Unrated | 100% |

## Retail Exposures (Art. 123)

Flat **75%** for all qualifying retail exposures.

## Residential Mortgage (Art. 125)

| LTV | Risk Weight |
|-----|-------------|
| LTV <= 80% | 35% on whole exposure |
| LTV > 80% | 35% on portion up to 80% LTV, 75% on excess |

Blended formula for LTV > 80%: `avg_RW = 0.35 x (0.80/LTV) + 0.75 x ((LTV-0.80)/LTV)`

## Commercial Real Estate (Art. 126)

| Condition | Risk Weight |
|-----------|-------------|
| LTV <= 50% and rental income >= 1.5x interest costs | 50% |
| All other CRE | 100% |

## Equity Exposures (Art. 133)

| Equity Type | Risk Weight |
|-------------|-------------|
| Central bank / sovereign | 0% |
| Listed / exchange-traded | 100% |
| Government-supported | 100% |

## Defaulted Exposures (Art. 127)

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions >= 20% of (EAD + provision_deducted) | 100% |
| Specific provisions < 20% | 150% |

## Other Items (Art. 134)

| Item | Risk Weight |
|------|-------------|
| Cash (notes, coins, gold bullion) | 0% |
| Items in course of collection | 20% |
| Tangible assets, prepaid expenses, other | 100% |

---

> **Full detail:** `docs/specifications/crr/sa-risk-weights.md`
