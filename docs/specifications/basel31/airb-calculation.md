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
| FR-4.10 | Full-facility EAD approach with floors (Art. 166D(3)–(5)) | P0 | Done |
| FR-4.11 | Expected drawdown incorporation in CCF (Art. 166D(2)) | P0 | Done |

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

### Expected Drawdown Incorporation (Art. 166D(2))

Where both an on-balance sheet item and a revolving loan commitment relate to the same
facility, the firm's own CCF estimate must incorporate any **expected increase in the
on-balance sheet value** at the point of default. This means the CCF applied to the
undrawn portion should already account for the likelihood that the drawn balance will
increase before default — the CCF is not applied to a static snapshot of the current
undrawn amount.

### Full-Facility EAD Approach (Art. 166D(3)/(4))

As an alternative to the standard CCF approach (drawn + undrawn × CCF), A-IRB firms
**may** estimate a single facility-level EAD that combines both on-balance sheet and
off-balance sheet components into one figure. This "full-facility EAD" replaces the
separate drawn/undrawn decomposition.

The approach has two variants depending on the facility's drawdown state:

#### Partially or Fully Undrawn Facilities (Art. 166D(3))

For revolving facilities that are partially drawn or fully undrawn, the firm assigns
a **single EAD estimate** to the entire facility. This replaces both:

- The exposure value of any related on-balance sheet item (Art. 166A(2))
- The exposure value of the revolving loan commitment (Art. 166D(1))

The single EAD must be the firm's own estimate provided in accordance with Section 6
(model validation requirements).

#### Fully Drawn Facilities (Art. 166D(4))

For revolving facilities that are currently **fully drawn** (no undrawn commitment
remains), the firm assigns an own EAD estimate that replaces the on-balance sheet
accounting value. This recognises that a revolving facility's exposure can exceed
its current drawn balance — the borrower may repay and redraw, and the facility
limit itself may fluctuate.

!!! info "Why Full-Facility EAD Matters"
    The standard CCF approach (drawn + undrawn × CCF) assumes a fixed split between
    drawn and undrawn amounts. For revolving facilities, this split is volatile — a
    borrower can repay and redraw repeatedly. The full-facility approach lets the model
    estimate total exposure at default directly, capturing drawdown dynamics that a
    static CCF may miss. This is particularly relevant for credit cards, overdrafts,
    and revolving credit lines where utilisation patterns drive EAD.

#### Input Field: `ead_modelled`

To use the full-facility approach, provide the `ead_modelled` field (type: `Float64`,
nullable) on the facility or contingent input record:

- **When present (non-null):** The calculator uses this as the facility-level EAD,
  subject to the floors below
- **When absent or null:** The calculator falls back to the standard CCF-based
  EAD calculation (drawn + undrawn × CCF)

The field is propagated through the pipeline via `FACILITY_SCHEMA` →
`RAW_EXPOSURE_SCHEMA` → `RESOLVED_HIERARCHY_SCHEMA` → `CLASSIFIED_EXPOSURE_SCHEMA`.
For drawn loans without a facility commitment, `ead_modelled` is set to null
(full-facility EAD is not applicable).

### EAD Floors (Art. 166D(5))

Art. 166D(5) specifies three separate floor tests ensuring A-IRB EAD estimates
do not fall below prudent minimums. Each floor maps to a specific EAD approach:

| Floor | Applies To | Formula | Reference |
|-------|-----------|---------|-----------|
| (a) CCF floor | Own-estimate CCFs (para 1(a)) | `CCF ≥ 50% × CCF_SA` | Art. 166D(5)(a) |
| (b) Facility EAD floor | Full-facility EAD for partially/fully undrawn (para 3) | `EAD ≥ EAD_on_BS + 50% × EAD_off_BS_FIRB` | Art. 166D(5)(b) |
| (c) Fully-drawn floor | Full-facility EAD for fully drawn (para 4) | `EAD ≥ EAD_on_BS` | Art. 166D(5)(c) |

#### Floor (a): CCF Floor

See [CCF Floor](#ccf-floor-art-166d5a--cre3227) above. The modelled CCF must be
at least 50% of the SA CCF for the same commitment type.

#### Floor (b): Facility-Level EAD Floor (Art. 166D(5)(b))

When using the full-facility approach for partially or fully undrawn facilities
(Art. 166D(3)), the modelled EAD must not be lower than:

```
EAD_floor_b = EAD_on_BS + 50% × EAD_off_BS_FIRB
```

Where:

- **`EAD_on_BS`** = exposure value of the on-balance sheet item calculated per
  Art. 166A(2), disregarding Art. 166D (i.e., the drawn balance as it would be
  calculated without the full-facility approach)
- **`EAD_off_BS_FIRB`** = exposure value of the off-balance sheet item under the
  **Foundation IRB Approach** per Art. 166C(1) (i.e., undrawn nominal × SA CCF,
  since F-IRB CCFs are aligned to SA under Basel 3.1)

The 50% factor on the off-balance sheet component mirrors the 50%-of-SA-CCF floor
in floor (a) — both enforce a minimum credit conversion of half the SA rate.

**Implementation:**

```
floor_b = on_balance_sheet_ead + nominal_after_provision × sa_ccf × 0.5
ead_pre_crm = max(ead_modelled, floor_b)
```

#### Floor (c): Fully-Drawn EAD Floor (Art. 166D(5)(c))

When using the full-facility approach for fully drawn facilities (Art. 166D(4)),
the modelled EAD must not be lower than the on-balance sheet exposure value:

```
EAD_floor_c = EAD_on_BS
```

Where **`EAD_on_BS`** is calculated per Art. 166A(2), disregarding Art. 166D.
This prevents the modelled EAD from falling below what the firm currently has
on its balance sheet — the model may estimate higher EAD (reflecting potential
redraw risk), but never lower.

**Implementation:**

```
ead_pre_crm = max(ead_modelled, on_balance_sheet_ead)
```

!!! note "Floor Interaction"
    When `ead_modelled` is provided, both floor (b) and floor (c) are evaluated
    and the binding floor is the higher of the two. In practice, floor (b) is
    typically binding for partially-drawn facilities (where there is material
    undrawn commitment), while floor (c) is binding for fully-drawn facilities
    (where the undrawn component is zero, making floor (b) collapse to just
    the on-balance sheet value).

### Unrecognised Exposure Adjustment (Art. 166D(6))

A-IRB firms must assess EADs arising from facilities or relationships that were
**not captured in exposure values** prior to drawdown — for example, where a
credit exposure materialises from a facility not originally intended to create
credit risk. Where such amounts are material, the firm must quantify an
**unrecognised exposure adjustment** reflecting the additional RWA required.
This adjustment is allocated to exposure classes on a best-efforts basis.

!!! warning "Not Yet Implemented"
    Art. 166D(6) unrecognised exposure adjustment is not implemented in the
    calculator. This provision requires institution-specific judgement about
    which facilities fall outside normal exposure capture — it cannot be
    automated without additional input data identifying uncaptured exposures.

See also the [CCF specification](../crr/credit-conversion-factors.md#basel-31-a-irb-changes-pra-ps126-art-166d--cre3227)
for context on how the A-IRB CCF regime fits within the broader CCF framework.

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
