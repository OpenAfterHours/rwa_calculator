# Provisions Specification

Provision treatment, expected loss calculation, and EL vs provisions comparison.

**Regulatory Reference:** CRR Articles 110, 111(1)(a)-(b), 158-159

**Test Group:** CRR-G

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-2.7 | Provision resolution: drawn-first deduction for SA, EL shortfall/excess for IRB | P0 | Done |
| FR-2.8 | Portfolio-level EL summary with T2 credit cap (CRR Art. 62(d), Art. 159) | P1 | Done |

---

## Pipeline Position

Provisions are resolved **before** CCF application in the pipeline:

```
resolve_provisions → CCF → initialize_ead → collateral → guarantees → finalize_ead
```

This ordering complies with CRR Art. 111(1)(a) (on-balance sheet: accounting value after specific CRA) and Art. 111(1)(b) (off-balance sheet: nominal after specific CRA, then × CCF). Note: Art. 111(2) governs derivative exposure values, not provisions.

!!! warning "Previous Citation Was Wrong"
    The regulatory reference was previously cited as "Art. 111(2)". The drawn-first provision deduction derives from Art. 111(1)(a) and 111(1)(b), not paragraph 2.

## Multi-Level Beneficiary Resolution

Provisions can be allocated at different levels and are resolved in priority order:

| Level | Resolution | Description |
|-------|-----------|-------------|
| **Direct** | `loan` / `exposure` / `contingent` | Matched directly to a specific exposure |
| **Facility** | `facility` | Distributed pro-rata across the facility's exposures by `ead_gross` |
| **Counterparty** | `counterparty` | Distributed pro-rata across all counterparty exposures by `ead_gross` |

Direct allocations are applied first. Facility-level and counterparty-level provisions are distributed proportionally based on each exposure's share of the total `ead_gross`.

## SA Approach (CRR Art. 110, 111(1))

Under the Standardised Approach, provisions use a **drawn-first deduction** approach:

```
# Step 1: Absorb provision against drawn amount first
provision_on_drawn = min(provision_allocated, max(0, drawn_amount))

# Step 2: Remainder reduces nominal before CCF (capped at nominal)
provision_on_nominal = min(provision_allocated - provision_on_drawn, nominal_amount)
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

!!! warning "BEEL Exception for A-IRB Defaulted (Art. 158(5))"
    For **A-IRB defaulted exposures** (PD=1), EL shall be the institution's **best estimate of expected loss (BEEL)**, not PD × LGD (which would give 1 × LGD). F-IRB defaulted exposures use the standard formula. The spec's `EL = PD × LGD × EAD` applies only to non-defaulted exposures and F-IRB defaulted.

### Basel 3.1: Post-Model EL Adjustment (Art. 158(6A))

Under Basel 3.1, total EL amounts must be increased to reflect any post-model adjustments on EL required under Art. 146(3)(c). This is a B31 addition not present under CRR.

### EL vs Provisions Comparison (Art. 159)

The comparison pool 'B' (provisions side) includes:
- General credit risk adjustments (CRA)
- Specific CRA for non-defaulted exposures
- Additional value adjustments (AVAs per Art. 34)
- Other own funds reductions

!!! warning "AVAs Not Implemented"
    The current implementation uses only `provision_allocated` as the offset against EL. AVAs (Art. 34) and other own funds reductions are not included, which **overstates EL shortfall** for banks with material AVA positions.

### Art. 159(3) Two-Branch Comparison

When non-defaulted EL exceeds non-defaulted provisions (A>B) AND defaulted provisions exceed defaulted EL (D>C) simultaneously, Art. 159(3) requires **separate computation** of the non-defaulted shortfall and defaulted excess. The defaulted excess must **not** offset the non-defaulted shortfall.

!!! warning "Not Implemented"
    The current implementation uses a single combined comparison (`sum(el_shortfall)` vs `sum(el_excess)`) across all exposures, which allows cross-subsidisation between defaulted and non-defaulted books.

### Portfolio-Level Summary (ELPortfolioSummary)

The aggregator computes a portfolio-level `ELPortfolioSummary` with:

| Field | Formula | Regulatory Reference |
|-------|---------|---------------------|
| `total_el_shortfall` | `sum(el_shortfall)` across all IRB exposures | CRR Art. 159 |
| `total_el_excess` | `sum(el_excess)` across all IRB exposures | CRR Art. 62(d) |
| `t2_credit_cap` | `total_irb_rwa × 0.006` (must use **un-floored** IRB RWA, not post-output-floor TREA) | CRR Art. 62(d) |
| `t2_credit` | `min(total_el_excess, t2_credit_cap)` | CRR Art. 62(d) |
| `cet1_deduction` | `total_el_shortfall × 0.5` | Art. 36(1)(d) |
| `t2_deduction` | `total_el_shortfall × 0.5` | Art. 62(d) |

!!! note "Citation Correction"
    The 50/50 split derives from Art. 36(1)(d) (CET1 deduction) and Art. 62(d) (T2 deduction), not Art. 159. Art. 159 only produces the "negative amount" (shortfall) and "positive amount" (excess).

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

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-G: Provisions | G1–G3 | 17 | 100% |
| B31-G: Provisions | G1–G3 | 24 | 100% |
