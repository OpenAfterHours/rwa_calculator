# Provisions Specification

Provision treatment, expected loss calculation, and EL vs provisions comparison.

**Regulatory Reference:** CRR Articles 110, 111(1)(a)-(b), 159; PRA Rulebook (CRR Firms) Art. 158

**Test Group:** CRR-G

!!! warning "Art. 158 Omitted from UK CRR (SI 2021/1078)"
    CRR Art. 158 (expected loss — treatment by exposure type) was **omitted** from UK retained
    law on 1 January 2022 by The Capital Requirements Regulation (Amendment) Regulations 2021
    (SI 2021/1078), reg. 6(3)(e). The expected loss calculation rules are now contained in the
    PRA Rulebook (CRR Firms). Art. 159 (EL vs provisions comparison) **remains** in UK CRR as
    substituted by Regulation (EU) 2019/630. PRA PS1/26 reinstates Art. 158 with modifications
    — including new para 6A (EL monotonicity) — effective 1 January 2027. References to
    "Art. 158" in this specification refer to the PRA Rulebook equivalent of the omitted CRR
    provision. See also: [Basel 3.1 Provisions Spec](../basel31/provisions.md).

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

## IRB Approach (Art. 158-159)

!!! info "Legal Basis"
    Art. 158 references here cite the PRA Rulebook (CRR Firms) equivalent — the CRR
    version was omitted by SI 2021/1078 (see header admonition). Art. 159 remains in
    UK CRR.

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

!!! success "Pool B Complete (P1.83)"
    All four Art. 159(1) Pool B components are now included in the EL comparison:
    `pool_b = provision_allocated + ava_amount + other_own_funds_reductions`.
    When `ava_amount` or `other_own_funds_reductions` columns are absent, they
    default to 0.0 (backward compatible). The `ELPortfolioSummary` reports
    `total_ava_amount`, `total_other_own_funds_reductions`, and `total_pool_b`.

### Art. 159(3) Two-Branch Comparison

When non-defaulted EL exceeds non-defaulted provisions (A>B) AND defaulted provisions exceed defaulted EL (D>C) simultaneously, Art. 159(3) requires **separate computation** of the non-defaulted shortfall and defaulted excess. The defaulted excess must **not** offset the non-defaulted shortfall.

!!! success "Implemented (P1.81)"
    Art. 159(3) two-branch rule is implemented. When the condition holds,
    `effective_shortfall = non_defaulted_shortfall` and `effective_excess =
    defaulted_excess` — no cross-pool netting. The `art_159_3_applies` flag
    on `ELPortfolioSummary` indicates when the two-branch rule is triggered.

### Portfolio-Level Summary (ELPortfolioSummary)

The aggregator computes a portfolio-level `ELPortfolioSummary` with:

| Field | Formula | Regulatory Reference |
|-------|---------|---------------------|
| `total_provisions_allocated` | `sum(provision_allocated)` across all IRB exposures | CRR Art. 159(1)(a-b) |
| `total_ava_amount` | `sum(ava_amount)` across all IRB exposures | CRR Art. 159(1)(c), Art. 34 |
| `total_other_own_funds_reductions` | `sum(other_own_funds_reductions)` across all IRB exposures | CRR Art. 159(1)(d) |
| `total_pool_b` | `provisions + AVA + other_own_funds_reductions` | CRR Art. 159(1) |
| `total_el_shortfall` | `sum(el_shortfall)` after Art. 159(3) rule | CRR Art. 159 |
| `total_el_excess` | `sum(el_excess)` after Art. 159(3) rule | CRR Art. 62(d) |
| `t2_credit_cap` | `total_irb_rwa × 0.006` (must use **un-floored** IRB RWA, not post-output-floor TREA) | CRR Art. 62(d) |
| `t2_credit` | `min(total_el_excess, t2_credit_cap)` | CRR Art. 62(d) |
| `cet1_deduction` | `total_el_shortfall × 0.5` | Art. 36(1)(d) |
| `t2_deduction` | `total_el_shortfall × 0.5` | Art. 62(d) |

!!! note "Citation Correction"
    The 50/50 split derives from Art. 36(1)(d) (CET1 deduction) and Art. 62(d) (T2 deduction), not Art. 159. Art. 159 only produces the "negative amount" (shortfall) and "positive amount" (excess).

## Slotting Approach

Same as IRB: provisions are tracked but not deducted from EAD.

## Key Scenarios

| Scenario ID | Description | Key Validation |
|-------------|-------------|----------------|
| CRR-G1 | SA with specific provision — drawn-first deduction | Provision reduces drawn amount first, remainder reduces nominal before CCF (Art. 111(1)(a)-(b)). Net EAD reflects deduction. |
| CRR-G2 | IRB EL shortfall — provisions < expected loss | EL shortfall = EL − provisions; 50/50 CET1/T2 deduction (Art. 36(1)(d), Art. 62(d)) |
| CRR-G3 | IRB EL excess — provisions > expected loss | EL excess credited to T2, capped at 0.6% of IRB RWA (Art. 62(d)) |

Additional spec scenarios validated through the above:

- **SA OBS provision deduction**: Provision reduces nominal before CCF application (validated within G1 pipeline — drawn-first mechanics apply to OBS)
- **Multi-level beneficiary resolution**: Direct, facility, and counterparty-level provisions resolved in priority order with pro-rata distribution (validated through G1 pipeline and unit tests)
- **Art. 159(3) two-branch rule**: Non-defaulted shortfall and defaulted excess computed separately when conditions hold (validated through G2/G3 and dedicated unit tests)

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-G: Provisions | G1–G3 | 17 | 100% |
| B31-G: Provisions | G1–G3 | 24 | 100% |
