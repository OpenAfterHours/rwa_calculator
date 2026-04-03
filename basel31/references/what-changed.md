# Basel 3.1 — What Changed from CRR

Master delta summary. Every major parameter change in one place.

---

## Framework-Level Changes

| Parameter | CRR | Basel 3.1 | Impact |
|-----------|-----|-----------|--------|
| RWA scaling factor | 1.06 | Removed | IRB RWA -5.7% |
| Output floor | None | 72.5% of SA | IRB benefit capped |
| SME supporting factor | 0.7619 / 0.85 | Removed | SME RWA increase |
| Infrastructure factor | 0.75 | Removed | Infra RWA increase |
| PD floor | 0.03% (uniform) | 0.05%-0.10% (differentiated) | Higher floors |
| A-IRB LGD floors | None | 0%-50% by type | New constraint |
| A-IRB scope | All exposure classes | Restricted (no large corp, FI, bank) | More to F-IRB |
| Equity IRB | PD/LGD + simple RW | Removed (SA only) | 250%/400% |
| Double default | Available | Removed | Higher RWA |

## SA Risk Weight Changes

| Exposure | CRR RW | Basel 3.1 RW | Change |
|----------|--------|--------------|--------|
| Corporate CQS 3 | 100% | 75% | -25pp |
| Corporate CQS 5 | 150% | 100% | -50pp |
| Investment-grade corporate | 100% | 65% | -35pp |
| SME corporate | 100% + 0.7619 SF | 85% | ~+8pp net |
| Subordinated debt | 100-150% | 150% (flat) | Standardised |
| Institution (unrated) | 40% (sovereign-based) | SCRA: 40/75/150% | Method change |
| Retail transactor | 75% | 45% | -30pp |
| Payroll/pension loans | 75% | 35% | -40pp |
| Equity (standard) | 100% | 250% | +150pp |
| Equity (higher risk) | 250-400% | 400% | Standardised |
| RESI RE (general) | 35% flat | 20% secured / cpty RW residual | Loan-splitting |
| CRE (income-producing) | 100% | 100%/110% by LTV | LTV-based |
| ADC | 100% | 150% | +50pp |

## IRB Parameter Changes

| Parameter | CRR | Basel 3.1 | Change |
|-----------|-----|-----------|--------|
| PD floor (corporate) | 0.03% | 0.05% | +0.02pp |
| PD floor (retail mortgage) | 0.03% | 0.10% | +0.07pp |
| PD floor (QRRE revolver) | 0.03% | 0.10% | +0.07pp |
| F-IRB LGD senior corp (non-FI) | 45% | 40% | -5pp |
| F-IRB LGD receivables | 35% | 20% | -15pp |
| F-IRB LGD CRE/RRE | 35% | 20% | -15pp |
| F-IRB LGD other physical | 40% | 25% | -15pp |
| A-IRB LGD floor (unsecured) | None | 25% | New |
| A-IRB LGD floor (RESI RE) | None | 5% | New |
| A-IRB LGD floor (QRRE unsecured) | None | 50% | New |
| A-IRB CCF | Own estimate | Floor: 50% of SA CCF | New constraint |
| UK RESI RE IRB RW floor | None | 10% (PRA-specific) | New |
| Post-model adjustments | None | Mandatory (Art. 146(3)) | New concept |

## CCF Changes

| Item Type | CRR | Basel 3.1 | Change |
|-----------|-----|-----------|--------|
| Unconditionally cancellable (SA) | 0% | 10% | +10pp |
| Other commitments (SA) | 0%/20%/50% | 40% | Unified |
| Low risk (F-IRB) | 0% | 40% | +40pp |
| A-IRB own estimates | All items | Revolving only | Restricted |

## CRM Changes

| Aspect | CRR | Basel 3.1 | Change |
|--------|-----|-----------|--------|
| Haircut maturity bands | 3 (0-1y, 1-5y, 5y+) | 5 (0-1y, 1-3y, 3-5y, 5-10y, 10y+) | More granular |
| Main index equity haircut | 15% | 25% | +10pp |
| Other equity haircut | 25% | 35% | +10pp |
| Unfunded protection | Cancellable test | +changeable test | Stricter |
| Method names | Various | FCM, PSM, LGD-AM | Clarified |

## Capital Impact Summary

| Portfolio Type | Direction | Driver |
|---------------|-----------|--------|
| Low-risk IRB | Increase | Output floor |
| SME | Increase | Factor removal |
| Infrastructure | Increase | Factor removal |
| Equity | Increase | 250%/400% from 100% |
| Unhedged FX retail/RE | Increase | 1.5x multiplier |
| High LTV mortgages | Decrease | Better SA RWs |
| Low LTV mortgages | Decrease | Better SA RWs |
| High-risk corporate | Decrease | CQS 5: 150% -> 100% |
| Retail transactor | Decrease | 75% -> 45% |
| Standard corporate | Neutral | — |

---

> **Full detail:** `docs/framework-comparison/key-differences.md`
