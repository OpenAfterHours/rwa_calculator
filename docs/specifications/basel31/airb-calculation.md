# Advanced IRB Specification

Basel 3.1 Advanced IRB changes: LGD floors, post-model adjustments (PMA),
CCF floor at 50% of SA, double default removal, and EL monotonicity.

**Regulatory Reference:** PRA PS1/26 Art. 153–154, 161(5), 164(4), 166D, CRE31–32
**Test Group:** B31-C

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-4.1 | Corporate A-IRB LGD floors (Art. 161(5)) | P0 | Done |
| FR-4.2 | Retail A-IRB LGD floors (Art. 164(4)) | P0 | Done |
| FR-4.3 | Post-model adjustments — RWA and EL scalars | P0 | Done |
| FR-4.4 | Mortgage risk weight floor (Art. 154(4A)(b)) | P0 | Done |
| FR-4.5 | PMA sequencing: mortgage floor before PMA scalar | P0 | Done |
| FR-4.6 | A-IRB CCF floor at 50% of SA CCF (Art. 166D, CRE32.27) | P0 | Done |
| FR-4.7 | Double default treatment removal | P0 | Done |
| FR-4.8 | EL monotonicity under PMA (Art. 158(6A)) | P0 | Done |
| FR-4.9 | FI scalar (1.25× correlation) retained | P0 | Done |

---

## Overview

Basel 3.1 constrains A-IRB flexibility by introducing **LGD floors** that prevent internal
estimates from falling below supervisory minimums, and **post-model adjustments** (PMA) that
allow PRA to impose conservative overlays. The double default treatment is removed, replaced
by parameter substitution for IRB guarantors (see [CRM Specification](credit-risk-mitigation.md)).
For funded credit protection (collateral), A-IRB firms may use **LGD modelling** under
Art. 169A/169B or fall back to the **Foundation Collateral Method** (FCM, Art. 230) — see
[CRM Specification § LGD Modelling Collateral Method](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b).

### Key Differences from F-IRB

| Parameter | F-IRB | A-IRB CRR | A-IRB Basel 3.1 |
|-----------|-------|-----------|-----------------|
| PD | Internal (floored) | Internal (floored) | Internal (floored, higher floors) |
| LGD | Supervisory | Internal | Internal **(with floors)** |
| CCF | Supervisory (CRR) / SA-aligned (B31) | Internal | **Revolving only** (floor: 50% of SA); others use SA |
| Maturity | Default 2.5y | Internal (retail: no MA) | Internal (retail: no MA) |
| Double default | Available | Available | **Removed** |
| PMA | N/A | N/A | **New: RWA/EL scalars + mortgage floor** |

---

## LGD Floors (Basel 3.1 Only)

### Corporate A-IRB LGD Floors (Art. 161(5))

A-IRB firms must ensure their internal LGD estimates do not fall below these floors:

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured | **25%** |
| Financial collateral | **0%** |
| Receivables | **10%** |
| Residential RE | **10%** |
| Commercial RE | **10%** |
| Other physical | **15%** |

!!! note "No Senior/Subordinated Distinction"
    Unlike F-IRB supervisory LGD (which distinguishes senior 40% from subordinated 75%),
    the A-IRB LGD floor is a flat **25%** for all unsecured corporate exposures regardless
    of seniority. There is no 50% subordinated floor — this was a previous documentation
    error corrected in D1.5.

For partially secured exposures, the blended LGD floor is:

```
LGD_floor = (E_unsecured / EAD) x LGDU_floor + sum_i((E_i / EAD) x LGDS_floor_i)
```

!!! info "Interaction with CRM Methods"
    These LGD floors apply **after** any CRM adjustment. Under A-IRB, the LGD input may be
    determined by the firm's own LGD model incorporating collateral effects (Art. 169A/169B) or
    by the Foundation Collateral Method (Art. 230). Either way, the resulting LGD is then floored
    per the tables above. Art. 169B requires that the LGD Modelling Collateral Method produce
    estimates at least as conservative as the FCM. See
    [CRM Specification](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b)
    for the full method taxonomy and requirements.

### Retail A-IRB LGD Floors (Art. 164(4))

| Retail Sub-Class | Collateral | LGD Floor |
|-----------------|------------|-----------|
| Residential RE mortgage | RE secured | **5%** |
| QRRE (transactor and revolver) | Unsecured | **50%** |
| Other retail | Unsecured | **30%** |
| Other retail | Receivables | **10%** |
| Other retail | Residential RE | **10%** |
| Other retail | Commercial RE | **10%** |
| Other retail | Other physical | **15%** |
| Other retail | Financial | **0%** |

!!! note "Scope of Corporate vs Retail Floors"
    Corporate LGD floors (Art. 161(5)) and retail LGD floors (Art. 164(4)) are separate
    regulatory provisions. Institution exposures under A-IRB use the corporate floor table.
    Sovereign exposures are restricted to SA under Basel 3.1 (Art. 147A), so sovereign
    A-IRB LGD floors are moot.

---

## Post-Model Adjustments (Art. 146(3), 154(4A), 158(6A))

PMA is a Basel 3.1 mechanism allowing the PRA to impose conservative overlays on A-IRB
model outputs without requiring full model re-estimation.

### Mortgage Risk Weight Floor (Art. 154(4A)(b))

A minimum risk weight is applied to residential mortgage exposures before general PMA:

```
RW_floored = max(RW_modelled, mortgage_rw_floor)
```

The mortgage RW floor is set by the PRA as a supervisory parameter. Default: **10%**.

### General PMA Scalar (Art. 146(3) / Art. 158(6A))

After the mortgage floor, PMA scalars are applied to both RWA and EL:

```
RWEA_adjusted = RWEA_modelled x (1 + pma_rwa_scalar)
EL_adjusted = EL_modelled x (1 + pma_el_scalar)
```

Where `pma_rwa_scalar` and `pma_el_scalar` are set per model via configuration.

### Adjustment Sequencing (Art. 153(5A) / Art. 154(4A))

The order of adjustments is **mandatory**:

1. **First:** Apply mortgage risk weight floor (Art. 154(4A)(b))
2. **Then:** Apply PMA RWA/EL scalar (Art. 154(4A)(a))

!!! warning "Sequencing is Mandatory"
    Reversing the order would produce different results because the PMA scalar amplifies
    the floor-adjusted RW, not the raw modelled RW. The correct sequence ensures the floor
    is never "scaled away" by a PMA scalar less than expected.

### EL Monotonicity (Art. 158(6A))

PMA application must satisfy:

```
EL_adjusted >= EL_unadjusted
```

EL must never decrease as a result of post-model adjustments. This prevents conservative
RWA overlays from inadvertently reducing expected loss estimates, which would distort the
EL shortfall/excess comparison (Art. 159).

---

## A-IRB CCF Restrictions (Art. 166D)

Under Basel 3.1, A-IRB own-estimate CCFs are **restricted to revolving facilities only**
(Art. 166D(1)(a)). All other off-balance sheet items must use SA CCFs from
[Table A1](../crr/credit-conversion-factors.md) (Art. 166D(1)(b)).

### Revolving Facility Eligibility (Art. 166D(1)(a))

Own-estimate CCFs are permitted only where **both** conditions are met:

1. The facility is a **revolving loan commitment** — set `is_revolving = True` in input data
2. The facility's SA CCF (per Art. 111 Table A1) is **less than 100%**

!!! warning "Table A1 Row 2 Carve-Out"
    Revolving facilities classified at **100% SA CCF** under Table A1 Row 2
    (factoring facilities, repos, forward asset purchases, partly-paid shares)
    **cannot use own-estimate CCFs** even though they are revolving. These always
    receive the full 100% SA CCF. The 100% reflects certain-drawdown commitments
    where the full nominal is economically equivalent to on-balance sheet exposure —
    there is no estimation benefit.

Non-revolving A-IRB facilities (term loans, non-revolving commitments, guarantees, etc.)
must use SA CCFs from Table A1 regardless of the firm's A-IRB permission. The
`is_revolving` flag in the input data controls this routing in the calculator.

!!! info "Definition: Revolving Loan Commitment (PRA PS1/26 Art. 1.3)"
    A commitment arising from a revolving loan facility — including credit cards, charge
    cards, and overdrafts — that lets a borrower decide how often to draw and at what
    intervals. Facilities allowing prepayments and subsequent redraws are considered
    revolving.

### CCF Floor (Art. 166D(5)(a) / CRE32.27)

For eligible revolving facilities, the own-estimate CCF is subject to a floor:

```
CCF_applied = max(CCF_modelled, 0.50 × CCF_SA)
```

The A-IRB CCF must be at least **50% of the corresponding SA CCF** (Art. 166D(5)(a)).

### EAD Floor (Art. 166D(5))

The exposure at default must not fall below the current drawn amount:

```
EAD >= current_drawn_amount
```

Art. 166D(5) specifies three separate floor tests for A-IRB revolving facilities:

| Floor | Applies To | Formula | Reference |
|-------|-----------|---------|-----------|
| (a) CCF floor | Own-estimate CCFs (para 1(a)) | CCF ≥ 50% × SA CCF | Art. 166D(5)(a) |
| (b) Facility EAD floor | Full-facility EAD (para 3) | EAD ≥ on-BS + 50% × F-IRB off-BS | Art. 166D(5)(b) |
| (c) Fully-drawn floor | Fully-drawn revolving (para 4) | EAD ≥ on-BS exposure value | Art. 166D(5)(c) |

See the [CRR CCF specification](../crr/credit-conversion-factors.md) for full
implementation detail including the full-facility EAD approach (Art. 166D(3)/(4)),
the `ead_modelled` input field, and all three floor calculations.

---

## Double Default Removal

Under CRR, the double default treatment (Art. 153(3) / Art. 202–203) allowed firms to
recognise the joint probability of both obligor and guarantor defaulting:

```
K_dd = K_obligor x (0.15 + 160 x PD_guarantor)  [CRR only]
```

Basel 3.1 **removes double default entirely**. For guaranteed exposures under IRB, firms
must use **parameter substitution** instead — see [CRM Specification](credit-risk-mitigation.md).

---

## Capital Formula

The A-IRB capital formula is identical to F-IRB (see [F-IRB Specification](firb-calculation.md)):

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
RW = K x 12.5 x MA
```

The differences are:

- `LGD` = firm's own estimate, subject to LGD floors (above) and CRM adjustments ([Art. 169A/169B](../crr/credit-risk-mitigation.md#lgd-modelling-collateral-method-basel-31-art-169a169b) or FCM)
- `PD` = firm's own estimate, subject to the same PD floors as F-IRB
- `MA` = 1.0 for retail (no maturity adjustment); internal estimate for non-retail
- Scaling factor = 1.0 (removed under Basel 3.1)
- FI scalar = 1.25× correlation for large/unregulated FSEs (retained)

---

## Key Scenarios

| Scenario ID | Description | Key Feature |
|-------------|-------------|-------------|
| B31-C1 | Corporate A-IRB: LGD floor binding (internal LGD < 25%) | LGD floored to 25% |
| B31-C2 | Retail other: LGD floor 30% unsecured, own LGD preserved when above | Floor non-binding |
| B31-C3 | Specialised lending A-IRB routing over slotting | A-IRB takes priority when permitted |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-C: Advanced IRB | C1–C3 | 13 | 100% (13/13) |
