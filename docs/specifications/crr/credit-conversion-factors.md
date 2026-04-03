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

## Basel 3.1 SA Changes (PRA PS1/26 Art. 111 Table A1)

| CCF Category | CRR | Basel 3.1 | Description |
|-------------|-----|-----------|-------------|
| Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees |
| Medium Risk (MR) | 50% | 50% | NIFs, RUFs, UK resi mortgage commitments |
| Medium-Low Risk (MLR) | 20% | 20% | Trade-related LCs, performance bonds |
| Other commitments | 0% | **40%** | All other commitments not in other categories |
| Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

## Basel 3.1 F-IRB Changes (PRA PS1/26 Art. 166C)

| CCF Category | CRR | Basel 3.1 | Description |
|-------------|-----|-----------|-------------|
| Full Risk (FR) | 100% | 100% | Same as SA |
| Medium Risk (MR) | 75% | 75% | General undrawn commitments |
| MLR (trade LCs) | 20% | 20% | Short-term trade LCs (Art. 166(9) / 166C exception) |
| Low Risk (LR) | 0% | **40%** | Unconditionally cancellable commitments |

## Basel 3.1 A-IRB Changes (PRA PS1/26 Art. 166D)

- Own CCF estimates **only permitted for revolving facilities**
- All other off-balance sheet items must use **SA CCFs**
- EAD floor: drawn + 50% of off-balance sheet using F-IRB CCF
- Falls back to SA CCFs if not available

## EAD Calculation

```
EAD = Drawn Amount + Accrued Interest + (Undrawn Amount × CCF)
```

Where:

- **Drawn Amount**: Current outstanding balance
- **Accrued Interest**: Interest due but not yet paid
- **Undrawn Amount**: Committed but undrawn facility limit minus drawn amount

### Provision-Adjusted EAD (Art. 111(2))

When provisions are present (SA only), they are resolved **before** CCF application using a drawn-first deduction:

```
provision_on_drawn = min(provision_allocated, max(0, Drawn Amount))
provision_on_nominal = min(provision_allocated - provision_on_drawn, Undrawn Amount)
nominal_after_provision = Undrawn Amount - provision_on_nominal

EAD = (max(0, Drawn Amount) - provision_on_drawn) + Accrued Interest
      + (nominal_after_provision × CCF)
```

This ensures that provisions reduce the nominal amount before the CCF multiplier is applied, compliant with CRR Art. 111(2). For IRB/Slotting exposures, provisions are tracked but not deducted — the standard EAD formula applies.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-D | Full risk CCF (100%) on guarantee |
| CRR-D | Medium risk undrawn commitment (50% SA, 75% F-IRB) |
| CRR-D | Trade LC at 20% under F-IRB exception |
| CRR-D | Unconditionally cancellable (0%) |
