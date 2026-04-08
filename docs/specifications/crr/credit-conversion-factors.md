# Credit Conversion Factors Specification

CCF application for off-balance sheet exposures under SA, F-IRB, and A-IRB.

**Regulatory Reference:** CRR Articles 111, 166; PRA PS1/26 Art. 111 Table A1, Art. 166C, Art. 166D

**Test Group:** CRR-D (partial)

---

## SA Approach (CRR Art. 111)

| CCF Category | CCF | Description |
|-------------|-----|-------------|
| Full Risk (FR) | 100% | Direct credit substitutes, guarantees, acceptances |
| Full Risk Commitment (FRC) | 100% | Certain-drawdown commitments: repos, factoring, forward deposits/purchases, partly-paid shares (Annex I para 2) |
| Medium Risk (MR) | 50% | Undrawn commitments > 1 year |
| Medium-Low Risk (MLR) | 20% | Undrawn commitments ≤ 1 year, trade-related LCs |
| Low Risk (LR) | 0% | Unconditionally cancellable commitments |

## F-IRB Approach (CRR Art. 166(8)-(9))

| CCF Category | CCF | Notes |
|-------------|-----|-------|
| Full Risk (FR) | 100% | Same as SA |
| Full Risk Commitment (FRC) | 100% | Same as SA — repos, factoring, forward deposits (Annex I para 2) |
| Medium Risk (MR) | 75% | Higher than SA 50% |
| Medium-Low Risk (MLR) | 75% | Higher than SA 20% (general case) |
| MLR (trade LCs) | 20% | Short-term trade LCs for goods movement (Art. 166(9) exception) |
| Low Risk (LR) | 0% | Same as SA |

## Basel 3.1 SA Changes (PRA PS1/26 Art. 111 Table A1)

| Row | CCF Category | CRR | Basel 3.1 | Description |
|-----|-------------|-----|-----------|-------------|
| 1 | Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees, acceptances, endorsements, credit derivatives, standby LCs serving as financial guarantees |
| 2 | Certain Drawdown (FRC) | 100% | **100%** | Commitments with certain drawdown: factoring facilities, outright forward asset purchases, repos, forward deposits, partly-paid shares/securities |
| 3 | Other OBS (MR) | 50% | **50%** | Other issued OBS items not of credit-substitute character: NIFs, RUFs, UK residential mortgage commitments |
| 4 | Medium-Low Risk (MLR) | 20% | 20% | Short-term self-liquidating trade LCs arising from movement of goods |
| 5 | Other Commitments (OC) | 50%/20%* | **40%** | All other commitments not falling into another category |
| 6 | Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

*\* Under CRR, "other commitments" were split by maturity: 50% for >1 year (MR), 20% for <=1 year (MLR). Basel 3.1 replaces this with a flat 40% regardless of maturity.*

!!! warning "B31 Maturity Distinction Removed"
    CRR distinguished between commitments > 1 year (50% MR) and ≤ 1 year (20% MLR). Basel 3.1 **removes** this maturity-based split entirely. The commitment type alone determines the CCF category, not its maturity. All commitments not classified in another row receive the 40% "Other Commitments" CCF (Row 5).

!!! note "Row 2 — Certain Drawdown Commitments"
    Row 2 captures commitments where drawdown is certain (e.g., factoring facilities, forward asset purchases, repos, partly-paid shares). These receive 100% CCF because the credit exposure will materialise with certainty. Under CRR these were classified as FRC in Annex I para 2; Basel 3.1 Table A1 Row 2 carries forward the same treatment.

!!! note "Row 3 — Other OBS Items"
    Row 3 captures off-balance sheet items issued by the firm that are not direct credit substitutes (Row 1) and not commitments. This includes note issuance facilities (NIFs), revolving underwriting facilities (RUFs), and UK residential mortgage commitments. Under CRR these were the 50% "Medium Risk" category; Basel 3.1 retains the 50% CCF.

### Commitment-to-Issue Lower-Of Rule (Art. 111(1)(c))

A commitment to provide an off-balance sheet item receives the **lower of** the two applicable CCFs: the CCF of the commitment itself and the CCF of the item it commits to provide.

**Formula:**

```
CCF_applied = min(CCF_commitment, CCF_underlying)
```

Where:

- **CCF_commitment**: The SA CCF for the commitment's own risk type (e.g., OC = 40%)
- **CCF_underlying**: The SA CCF for the OBS item the commitment is to issue (e.g., FR = 100%)

**Examples:**

| Commitment | Underlying OBS Item | CCF_commitment | CCF_underlying | Applied CCF |
|-----------|-------------------|---------------|---------------|-------------|
| Other commitment (OC) | Guarantee (FR) | 40% | 100% | **40%** |
| Full Risk (FR) | UCC (LR) | 100% | 10% | **10%** |
| Medium Risk (MR) | Trade LC (MLR) | 50% | 20% | **20%** |

**Implementation:** Requires `underlying_risk_type` field on the exposure input. When present and non-null, the CCF is capped at the underlying item's Table A1 CCF. When absent or null, no cap is applied (backward compatible). The lower-of rule flows through to all approaches:

- **SA:** Direct cap on the SA CCF
- **F-IRB (Basel 3.1):** Cap on SA CCFs used per Art. 166C
- **F-IRB (CRR):** Cap on the CRR F-IRB CCF ladder
- **A-IRB:** Affects the SA CCF used for the 50% floor (CRE32.27) and for non-revolving exposures

## Basel 3.1 F-IRB Changes (PRA PS1/26 Art. 166C)

Under Basel 3.1, F-IRB CCFs are aligned to **SA CCFs** (Art. 166C). The separate higher F-IRB CCFs from CRR are removed:

| Row | CCF Category | CRR F-IRB | Basel 3.1 F-IRB | Description |
|-----|-------------|-----------|-----------------|-------------|
| 1 | Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees, acceptances, endorsements |
| 2 | Certain Drawdown (FRC) | 100% | **100%** | Commitments with certain drawdown: factoring, repos, forward purchases, partly-paid shares |
| 3 | Other OBS (MR) | 75% | **50%** | Other issued OBS items: NIFs, RUFs, UK residential mortgage commitments |
| 4 | Medium-Low Risk (MLR) | 75%/20%* | **20%** | Short-term self-liquidating trade LCs arising from movement of goods |
| 5 | Other Commitments (OC) | 0% | **40%** | All other commitments not falling into another category |
| 6 | Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

*\* Under CRR F-IRB, MLR was 75% for the general case (Art. 166(8)), with a 20% exception for short-term trade LCs arising from goods movement (Art. 166(9)). Basel 3.1 blanks Art. 166(9) and applies the SA Table A1 MLR value of 20% uniformly.*

!!! warning "Critical Change — F-IRB CCFs Aligned to SA"
    Under Basel 3.1, Art. 166C states: *"the conversion factor for each type [of off-balance sheet item] shall be the same as the value set out in Article 111(1)"* (i.e., SA Table A1). F-IRB no longer has its own distinct CCF schedule. The CRR F-IRB 75% rate for MR and MLR commitments is eliminated. All six rows above match the SA Table A1 values exactly.

!!! warning "Art. 166(9) Trade LC Exception — Removed"
    CRR Art. 166(9) provided a 20% CCF exception for short-term trade LCs under F-IRB (overriding the general 75% rate). PRA PS1/26 **blanks Art. 166(9)** — the exception text is removed. Under Basel 3.1, the 20% MLR rate for trade-related LCs is retained, but it now comes from SA Table A1 Row 4 (applied uniformly via Art. 166C), not from a separate F-IRB exception.

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

### Provision-Adjusted EAD (Art. 111(1)(a)-(b))

When provisions are present (SA only), they are resolved **before** CCF application using a drawn-first deduction:

```
provision_on_drawn = min(provision_allocated, max(0, Drawn Amount))
provision_on_nominal = min(provision_allocated - provision_on_drawn, Undrawn Amount)
nominal_after_provision = Undrawn Amount - provision_on_nominal

EAD = (max(0, Drawn Amount) - provision_on_drawn) + Accrued Interest
      + (nominal_after_provision × CCF)
```

This ensures that provisions reduce the nominal amount before the CCF multiplier is applied, compliant with CRR Art. 111(1)(a)-(b). For IRB/Slotting exposures, provisions are tracked but not deducted — the standard EAD formula applies.

## Key Scenarios

### CRR Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-D | Full risk CCF (100%) on guarantee |
| CRR-D | Medium risk undrawn commitment (50% SA, 75% F-IRB) |
| CRR-D | Trade LC at 20% under F-IRB Art. 166(9) exception |
| CRR-D | Unconditionally cancellable (0% SA, 0% F-IRB) |

### Basel 3.1 Scenarios

| Scenario ID | Description |
|-------------|-------------|
| B31-D | Full risk CCF (100%) on guarantee — unchanged from CRR |
| B31-D | Other OBS (MR) at 50% — NIFs, RUFs (same as CRR SA; F-IRB aligned down from 75%) |
| B31-D | Trade LC (MLR) at 20% — from Table A1 Row 4 (no separate F-IRB exception) |
| B31-D | Other commitments (OC) at 40% — replaces CRR maturity-based 50%/20% split |
| B31-D | Unconditionally cancellable (LR) at 10% — up from CRR 0% |
| B31-D | F-IRB uses SA CCFs — Art. 166C alignment (no distinct F-IRB schedule) |
| B31-D | Certain drawdown (FRC) at 100% — factoring, repos, forward purchases |
| B31-D | Commitment-to-issue: OC to issue FR → min(40%,100%) = 40% (Art. 111(1)(c)) |
