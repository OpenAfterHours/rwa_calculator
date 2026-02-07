# Credit Conversion Factors Specification

CCF application for off-balance sheet exposures under SA and F-IRB.

**Regulatory Reference:** CRR Articles 111, 166

**Test Group:** CRR-D (partial)

---

## SA Approach (CRR Art. 111)

| CCF Category | CCF | Description |
|-------------|-----|-------------|
| Full Risk (FR) | 100% | Direct credit substitutes, guarantees |
| Medium Risk (MR) | 50% | Undrawn commitments > 1 year |
| Medium-Low Risk (MLR) | 20% | Undrawn commitments ≤ 1 year, trade-related LCs |
| Low Risk (LR) | 0% | Unconditionally cancellable commitments |

## F-IRB Approach (CRR Art. 166(8)-(9))

| CCF Category | CCF | Notes |
|-------------|-----|-------|
| Full Risk (FR) | 100% | Same as SA |
| Medium Risk (MR) | 75% | Higher than SA 50% |
| Medium-Low Risk (MLR) | 75% | Higher than SA 20% (general case) |
| MLR (trade LCs) | 20% | Short-term trade LCs for goods movement (Art. 166(9) exception) |
| Low Risk (LR) | 0% | Same as SA |

## A-IRB Approach

- Uses modelled CCF if provided by the bank
- Falls back to SA CCFs if not available

## EAD Calculation

```
EAD = Drawn Amount + Accrued Interest + (Undrawn Amount x CCF)
```

Where:

- **Drawn Amount**: Current outstanding balance
- **Accrued Interest**: Interest due but not yet paid
- **Undrawn Amount**: Committed but undrawn facility limit minus drawn amount

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-D | Full risk CCF (100%) on guarantee |
| CRR-D | Medium risk undrawn commitment (50% SA, 75% F-IRB) |
| CRR-D | Trade LC at 20% under F-IRB exception |
| CRR-D | Unconditionally cancellable (0%) |
