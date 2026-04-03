# CRR Credit Conversion Factors

Quick-reference for SA and F-IRB CCF tables under CRR.

**Regulatory Reference:** CRR Articles 111, 166

---

## SA CCFs (Art. 111)

| CCF Category | CCF | Description |
|-------------|-----|-------------|
| Full Risk (FR) | 100% | Direct credit substitutes, guarantees |
| Medium Risk (MR) | 50% | Undrawn commitments > 1 year |
| Medium-Low Risk (MLR) | 20% | Undrawn commitments <= 1 year, trade-related LCs |
| Low Risk (LR) | 0% | Unconditionally cancellable commitments |

## F-IRB CCFs (Art. 166(8)-(9))

| CCF Category | CCF | Notes |
|-------------|-----|-------|
| Full Risk (FR) | 100% | Same as SA |
| Medium Risk (MR) | 75% | Higher than SA 50% |
| Medium-Low Risk (MLR) | 75% | Higher than SA 20% (general) |
| MLR (trade LCs) | 20% | Short-term trade LCs for goods (Art. 166(9) exception) |
| Low Risk (LR) | 0% | Same as SA |

## EAD Formula

```
EAD = Drawn Amount + Accrued Interest + (Undrawn Amount x CCF)
```

When provisions are present (SA only), they are deducted before CCF application
via the drawn-first deduction approach (see provisions reference).

---

> **Full detail:** `docs/specifications/crr/credit-conversion-factors.md`
