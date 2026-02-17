# Provisions Specification

Provision treatment, expected loss calculation, and EL vs provisions comparison.

**Regulatory Reference:** CRR Articles 110, 111(2), 158-159

**Test Group:** CRR-G

---

## Pipeline Position

Provisions are resolved **before** CCF application in the pipeline:

```
resolve_provisions → CCF → initialize_ead → collateral → guarantees → finalize_ead
```

This ordering complies with CRR Art. 111(2), which requires provisions to reduce the exposure value before credit conversion factors are applied to off-balance sheet items.

## Multi-Level Beneficiary Resolution

Provisions can be allocated at different levels and are resolved in priority order:

| Level | Resolution | Description |
|-------|-----------|-------------|
| **Direct** | `loan` / `exposure` / `contingent` | Matched directly to a specific exposure |
| **Facility** | `facility` | Distributed pro-rata across the facility's exposures by `ead_gross` |
| **Counterparty** | `counterparty` | Distributed pro-rata across all counterparty exposures by `ead_gross` |

Direct allocations are applied first. Facility-level and counterparty-level provisions are distributed proportionally based on each exposure's share of the total `ead_gross`.

## SA Approach (CRR Art. 110, 111(2))

Under the Standardised Approach, provisions use a **drawn-first deduction** approach:

```
# Step 1: Absorb provision against drawn amount first
provision_on_drawn = min(provision_allocated, max(0, drawn_amount))

# Step 2: Remainder reduces nominal before CCF
provision_on_nominal = provision_allocated - provision_on_drawn
nominal_after_provision = nominal_amount - provision_on_nominal

# Step 3: CCF applied to adjusted nominal
ead_from_ccf = nominal_after_provision × CCF

# Step 4: Final EAD (provisions already baked in)
EAD = (max(0, drawn) - provision_on_drawn) + interest + ead_from_ccf
```

The `finalize_ead()` step does **not** subtract provisions again — they are already reflected in `ead_pre_crm` via the drawn-first deduction.

### New Columns (SA)

| Column | Type | Description |
|--------|------|-------------|
| `provision_on_drawn` | `Float64` | Provision absorbed by drawn amount |
| `provision_on_nominal` | `Float64` | Provision reducing nominal before CCF |
| `nominal_after_provision` | `Float64` | `nominal_amount - provision_on_nominal` |
| `provision_deducted` | `Float64` | Total = `provision_on_drawn + provision_on_nominal` |
| `provision_allocated` | `Float64` | Total provision matched to this exposure |

## IRB Approach (CRR Art. 158-159)

Under IRB, provisions are tracked (`provision_allocated`) but **not deducted** from EAD. The provision columns are set to zero:

```
provision_deducted = 0
provision_on_drawn = 0
provision_on_nominal = 0
```

Instead, the calculator computes Expected Loss for comparison:

```
EL = PD × LGD × EAD
```

### EL vs Provisions Comparison

- **EL > Provisions (shortfall):** The difference reduces CET1 capital
- **EL < Provisions (excess):** The surplus may be added to Tier 2 capital (subject to caps)

The calculator tracks both values to support this regulatory comparison.

## Slotting Approach

Same as IRB: provisions are tracked but not deducted from EAD.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-G | SA exposure with drawn-first provision deduction |
| CRR-G | SA off-balance sheet: provision reduces nominal before CCF |
| CRR-G | Multi-level beneficiary resolution (direct, facility, counterparty) |
| CRR-G | IRB expected loss calculation (provisions not deducted) |
| CRR-G | EL vs provisions: shortfall case |
| CRR-G | EL vs provisions: excess case |
