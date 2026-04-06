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

| Row | CCF Category | CRR | Basel 3.1 | Description |
|-----|-------------|-----|-----------|-------------|
| 1 | Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees |
| 2 | Commitments | — | **100%** | Commitments to lend, purchase securities, provide guarantees or acceptances |
| 3 | Other OBS | — | **50%** | Other off-balance sheet items (NIFs, RUFs, UK resi mortgage commitments) |
| 4 | Medium-Low Risk (MLR) | 20% | 20% | Trade-related LCs, performance bonds |
| 5 | Other commitments | 0% | **40%** | All other commitments not in other categories |
| 6 | Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

!!! note "B31 Maturity Distinction Removed"
    CRR distinguished between commitments > 1 year (50% MR) and ≤ 1 year (20% MLR). Basel 3.1 removes this maturity-based distinction — the commitment type determines the CCF category, not its maturity.

### Commitment-to-Issue Lower-Of Rule (Art. 111(1)(c))

A commitment to provide an off-balance sheet item receives the **lower of** the two applicable CCFs: the CCF of the commitment itself and the CCF of the item it commits to provide.

## Basel 3.1 F-IRB Changes (PRA PS1/26 Art. 166C)

Under Basel 3.1, F-IRB CCFs are aligned to **SA CCFs** (Art. 166C). The separate higher F-IRB CCFs from CRR are removed:

| CCF Category | CRR F-IRB | Basel 3.1 F-IRB | Description |
|-------------|-----------|-----------------|-------------|
| Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees |
| Commitments (Row 2) | 75% | **100%** | Commitments to lend, purchase securities, provide guarantees |
| Medium Risk (MR) | 75% | **50%** | NIFs, RUFs, UK resi mortgage commitments |
| Medium-Low Risk (MLR) | 20% | 20% | Trade-related LCs, performance bonds |
| Other commitments | — | **40%** | All other commitments not in other categories |
| Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

!!! warning "Critical Change"
    The CRR F-IRB 75% medium risk CCF is replaced by SA-aligned values under Basel 3.1. F-IRB no longer has its own distinct CCF schedule — it uses SA Table A1 values per Art. 166C.

**Note:** Art. 166(9) trade LC exception: PS1/26 blanks the trade LC exception text. The 20% MLR rate for trade-related LCs continues under the general SA Table A1 MLR category.

## Basel 3.1 A-IRB Changes (PRA PS1/26 Art. 166D / CRE32.27)

- Own CCF estimates **only permitted for revolving facilities** (Art. 166D(1)(a))
- **Exception**: revolving facilities subject to **100% SA CCF** (Table A1 Row 2 — factoring, repos, forward deposits) **cannot** use own-estimate CCFs even though revolving
- All other off-balance sheet items must use **SA CCFs** (Table A1)
- The revolving-only restriction is a data classification concern — exposures should carry an `is_revolving` flag; non-revolving AIRB facilities must use SA CCFs regardless of modelled estimates

### A-IRB CCF Floor (CRE32.27)

Modelled CCF estimates are subject to a **50% floor** relative to the SA CCF:

```
CCF_applied = max(CCF_modelled, 0.50 × CCF_SA)
```

Where `CCF_SA` is the applicable SA CCF from Table A1 for that off-balance sheet item category. This floor applies to all A-IRB CCF estimates including revolving facilities.

### A-IRB EAD Floors (Art. 166D(5))

Three separate floor tests apply:

1. **(a) CCF floor**: Own CCF estimates ≥ 50% × SA CCF (see above)
2. **(b) Facility-level EAD floor** (for partially/fully undrawn revolving facilities using Art. 166D(3) single EAD): EAD ≥ on-balance-sheet EAD + 50% × F-IRB off-balance-sheet EAD
3. **(c) Fully-drawn EAD floor** (for fully drawn revolving facilities using Art. 166D(4)): EAD ≥ on-balance-sheet EAD (ignoring Art. 166D)

### Full-Facility EAD Approach (Art. 166D(3)/(4))

As an alternative to the CCF approach, A-IRB firms may compute a **single EAD estimate** for the entire revolving facility:

- Art. 166D(3): for partially/fully undrawn revolving facilities — a single EAD combining on-BS and off-BS components
- Art. 166D(4): for fully drawn revolving facilities — the own EAD estimate replaces the on-BS accounting value

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
