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
| 1 | Full Risk — issued items (FR) | 100% | 100% | Financial guarantees with character of credit substitutes; credit derivatives; acceptances; endorsements; irrevocable standby LCs serving as financial guarantees; other issued items with credit-substitute character |
| 2 | Full Risk — commitments (FRC) | 100% | **100%** | Commitments with certain drawdown: factoring facilities, outright forward asset purchases, repos, forward deposits, partly-paid shares/securities |
| 3 | Other issued OBS items (MR) | 50% | **50%** | Other issued OBS items that do not have the character of credit substitutes |
| 4 | NIFs/RUFs / UK resi mortgage (MR) | 50% | **50%** | (a) NIFs and RUFs; (b) UK residential mortgage commitments not subject to a CCF of 10% or 100% |
| 5 | Other Commitments (OC) | 50%/20%* | **40%** | Any other commitment not subject to a CCF of 10%, 50%, or 100% |
| 6 | Medium/Low Risk — issued items (MLR) | 20% | **20%** | (a) Documentary credits and other self-liquidating transactions; (b) warranties, tender/performance bonds, advance payment/retention guarantees; (c) irrevocable standby LCs (non-credit substitute); (d) shipping guarantees, customs and tax bonds |
| 7 | Unconditionally Cancellable (LR) | 0% | **10%** | Undrawn commitments cancellable unconditionally at any time without notice, or with automatic cancellation due to obligor creditworthiness deterioration |

*\* Under CRR, "other commitments" were split by maturity: 50% for >1 year (MR), 20% for <=1 year (MLR). Basel 3.1 replaces this with a flat 40% regardless of maturity.*

!!! warning "B31 Maturity Distinction Removed"
    CRR distinguished between commitments > 1 year (50% MR) and ≤ 1 year (20% MLR). Basel 3.1 **removes** this maturity-based split entirely. The commitment type alone determines the CCF category, not its maturity. All commitments not classified in another row receive the 40% "Other Commitments" CCF (Row 5).

!!! note "Row 2 — Certain Drawdown Commitments"
    Row 2 captures commitments where drawdown is certain (e.g., factoring facilities, forward asset purchases, repos, partly-paid shares). These receive 100% CCF because the credit exposure will materialise with certainty. Under CRR these were classified as FRC in Annex I para 2; Basel 3.1 Table A1 Row 2 carries forward the same treatment.

!!! note "Row 3 — Other Issued OBS Items"
    Row 3 captures off-balance sheet **items** (not commitments) issued by the firm that do not have the character of credit substitutes (Row 1). Under CRR these were part of the "Medium Risk" category; Basel 3.1 retains the 50% CCF.

!!! note "Row 4 — NIFs/RUFs and UK Residential Mortgage Commitments"
    Row 4 captures two specific **commitment** types at 50%: (a) note issuance facilities (NIFs) and revolving underwriting facilities (RUFs); (b) UK residential mortgage commitments. Under CRR, NIFs/RUFs were Medium Risk (50%) in Annex I. Residential mortgage commitments had no separate CRR category — they were classified by maturity (>1yr = MR 50%, ≤1yr = MLR 20%). Both sub-categories map to `risk_type = MR` (medium_risk) in the code.

!!! warning "PRA Deviation — UK Residential Mortgage Commitments (Row 4(b))"
    Row 4(b) is a **PRA-specific addition** not present in the BCBS framework (CRE20.93–20.98). Under BCBS, residential mortgage commitments would fall into the "any other commitment" bucket at 40% (Row 5). The PRA carved them out at **50%** to maintain a more conservative treatment, consistent with the CRR treatment for commitments >1 year. This prevents the Basel 3.1 maturity-distinction removal from inadvertently reducing capital for irrevocable mortgage offer letters. The Row 4(b) carve-out only applies to commitments that are not unconditionally cancellable (Row 7, 10%) and not certain-drawdown (Row 2, 100%).

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
| Full Risk (FR) | UCC (LR, Row 7) | 100% | 10% | **10%** |
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
| 1 | Full Risk — issued items (FR) | 100% | 100% | Financial guarantees, credit derivatives, acceptances, endorsements |
| 2 | Full Risk — commitments (FRC) | 100% | **100%** | Commitments with certain drawdown: factoring, repos, forward purchases, partly-paid shares |
| 3 | Other issued OBS items (MR) | 75% | **50%** | Other issued OBS items not of credit-substitute character |
| 4 | NIFs/RUFs / UK resi mortgage (MR) | 75% | **50%** | (a) NIFs and RUFs; (b) UK residential mortgage commitments not subject to 10% or 100% CCF |
| 5 | Other Commitments (OC) | 75%* | **40%** | Any other commitment not subject to 10%, 50%, or 100% CCF |
| 6 | Medium/Low Risk — issued items (MLR) | 75%/20%* | **20%** | Documentary credits, warranties, tender/performance bonds, guarantees (non-credit substitute), shipping guarantees |
| 7 | Unconditionally Cancellable (LR) | 0% | **10%** | Undrawn commitments cancellable unconditionally at any time without notice |

*\* Under CRR, "Other Commitments" had no separate F-IRB category. These commitments were classified by maturity: >1yr → MR (75%), ≤1yr → MLR (75%). Both received 75% under F-IRB Art. 166(8). Under CRR F-IRB, MLR was 75% for the general case (Art. 166(8)), with a 20% exception for short-term trade LCs arising from goods movement (Art. 166(9)). Basel 3.1 blanks Art. 166(9) and applies the SA Table A1 MLR value of 20% uniformly via Art. 166C.*

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

As an alternative to the CCF approach (drawn + undrawn × CCF), A-IRB firms **may**
estimate a single facility-level EAD that combines both on-balance sheet and
off-balance sheet components into one figure:

- **Art. 166D(3)** — Partially/fully undrawn revolving facilities: a single EAD
  estimate replaces the separate on-BS item (Art. 166A(2)) and the revolving loan
  commitment (Art. 166D(1)). Activated by providing a non-null `ead_modelled` value.
- **Art. 166D(4)** — Fully drawn revolving facilities: the own EAD estimate replaces
  the on-BS accounting value, recognising that a revolving facility's exposure can
  exceed its current drawn balance due to repayment-and-redraw dynamics.

The `ead_modelled` input field (`Float64`, nullable) controls this routing:

- **Non-null:** Calculator uses the modelled EAD, subject to floors (b)/(c) below
- **Null or absent:** Calculator uses standard CCF-based EAD (drawn + undrawn × CCF)

**Floors for full-facility EAD:**

| Floor | Condition | Formula | Reference |
|-------|----------|---------|-----------|
| (b) | Partially/fully undrawn (para 3) | `EAD ≥ EAD_on_BS + 50% × (nominal × CCF_SA)` | Art. 166D(5)(b) |
| (c) | Fully drawn (para 4) | `EAD ≥ EAD_on_BS` | Art. 166D(5)(c) |

Floor (b) mirrors the 50%-of-SA-CCF principle from floor (a) — the off-balance sheet
component receives at least half the SA conversion. Floor (c) prevents the modelled EAD
from falling below the current balance sheet exposure.

For the full regulatory detail — including Art. 166D(2) expected drawdown incorporation,
Art. 166D(6) unrecognised exposure adjustment, and worked implementation formulas — see
the [A-IRB specification § Full-Facility EAD](../basel31/airb-calculation.md#full-facility-ead-approach-art-166d34).

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

!!! note "Test Coverage"
    CCF scenarios are validated implicitly through the CRM acceptance test group (CRR-D, B31-D) and pipeline integration tests. CCF application is a prerequisite step for EAD calculation in all CRM scenarios. The IDs below use a `.CCF` sub-designation to distinguish them from the CRM collateral/guarantee scenarios (CRR-D1–D14) in [`credit-risk-mitigation.md`](credit-risk-mitigation.md).

### CRR Scenarios

| Scenario ID | CCF Category | SA CCF | F-IRB CCF | Reference |
|-------------|-------------|--------|-----------|-----------|
| CRR-D.CCF1 | Full Risk (FR) — guarantee | 100% | 100% | Art. 111, Art. 166(8) |
| CRR-D.CCF2 | Medium Risk (MR) — undrawn commitment >1yr | 50% | 75% | Art. 111, Art. 166(8) |
| CRR-D.CCF3 | Medium-Low Risk (MLR) — trade LC for goods movement | 20% | 20% | Art. 111, Art. 166(9) |
| CRR-D.CCF4 | Low Risk (LR) — unconditionally cancellable | 0% | 0% | Art. 111, Art. 166(8) |
| CRR-D.CCF5 | Other Commitments (OC) >1yr | 50% | 75% | Art. 111, Art. 166(8); maturity-dependent |
| CRR-D.CCF6 | Other Commitments (OC) <=1yr | 20% | 75% | Art. 111, Art. 166(8); maturity-dependent |

### Basel 3.1 Scenarios

| Scenario ID | Table A1 Row | CCF Category | SA/F-IRB CCF | Key Change from CRR | Reference |
|-------------|-------------|-------------|-------------|---------------------|-----------|
| B31-D.CCF1 | Row 1 | Full Risk (FR) — guarantee | 100% | Unchanged | Art. 111 Table A1 |
| B31-D.CCF2 | Row 2 | Certain Drawdown (FRC) — factoring, repos | 100% | Renamed from Annex I para 2 | Art. 111 Table A1 |
| B31-D.CCF3 | Row 3/4 | Other OBS / NIFs / RUFs (MR) | 50% | F-IRB aligned down from 75% | Art. 111 Table A1 |
| B31-D.CCF4 | Row 6 | Medium/Low Risk (MLR) — trade LCs, warranties | 20% | Art. 166(9) exception removed | Art. 111 Table A1 |
| B31-D.CCF5 | Row 5 | Other Commitments (OC) | 40% | Replaces CRR 50%/>1yr / 20%/≤1yr split | Art. 111 Table A1 |
| B31-D.CCF6 | Row 7 | Unconditionally Cancellable (LR) | 10% | Up from CRR 0% | Art. 111 Table A1 |
| B31-D.CCF7 | — | F-IRB uses SA CCFs (Art. 166C alignment) | Per SA table | No distinct F-IRB schedule | Art. 166C |
| B31-D.CCF8 | — | Commitment-to-issue lower-of rule | min(CCF_commitment, CCF_underlying) | New Art. 111(1)(c) | Art. 111(1)(c) |
| B31-D.CCF9 | Row 4(b) | UK residential mortgage commitment (MR) | 50% | PRA-specific: carved out from 40% OC | Art. 111 Table A1 |
