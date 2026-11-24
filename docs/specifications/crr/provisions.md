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

Under the Standardised Approach, **specific** credit risk adjustments are deducted with a
**drawn-first** approach. General credit risk adjustments are not: Art. 110(1) sends SA general
CRA to Tier 2 under Art. 62(c), and Art. 111(1) values an asset item "after specific credit risk
adjustments" and an off-balance sheet item at "its nominal value after reduction of specific
credit risk adjustments".

Two amounts are therefore allocated to each exposure, on the same levels and pro-rata basis:

- `provision_allocated` — every provision row, specific and general. The IRB / slotting
  EL comparison reads it (Art. 159 Pool B includes general CRA).
- `provision_specific_allocated` — rows whose `provision_type` is `scra` (any case) or null.
  A null type is what the loader injects when a book omits the optional column; it is treated as
  specific, as untyped provisions always were. A `gcra` row is excluded, and so is a row with any
  other label (the input validator reports it as a DQ006 warning and keeps the row).

```
# Step 1: Absorb the specific provision against drawn amount first
provision_on_drawn = min(provision_specific_allocated, max(0, drawn_amount))

# Step 2: Remainder reduces nominal before CCF (capped at nominal)
provision_on_nominal = min(provision_specific_allocated - provision_on_drawn, nominal_amount)
nominal_after_provision = nominal_amount - provision_on_nominal

# Step 3: CCF applied to adjusted nominal
ead_from_ccf = nominal_after_provision × CCF

# Step 4: Final EAD (provisions already baked in)
EAD = (max(0, drawn) - provision_on_drawn) + interest + ead_from_ccf
```

The `finalize_ead()` step does **not** subtract provisions again — they are already reflected in `ead_pre_crm` via the drawn-first deduction.

The Art. 127(1) defaulted-exposure test ("the sum of specific credit risk adjustments ... is less
than 20 %") reads `provision_specific_allocated` as its numerator too, so a general CRA can
neither reduce an SA exposure value nor move a defaulted exposure from 150% to 100% (P1.208).
Example: a defaulted unrated corporate drawn 100,000 with SCRA 15,000 and GCRA 10,000 has
EAD 85,000 and coverage 15% < 20%, so 150% (RWA 127,500).

### New Columns (SA)

| Column | Type | Description |
|--------|------|-------------|
| `provision_on_drawn` | `Float64` | Provision absorbed by drawn amount |
| `provision_on_nominal` | `Float64` | Provision reducing nominal before CCF |
| `nominal_after_provision` | `Float64` | `nominal_amount - provision_on_nominal` |
| `provision_deducted` | `Float64` | Total = `provision_on_drawn + provision_on_nominal` (specific CRA only) |
| `provision_allocated` | `Float64` | Total provision matched to this exposure (specific + general) |
| `provision_specific_allocated` | `Float64` | Specific CRA matched to this exposure, all approaches; CRM-stage carrier, not on the results frame |

## IRB Approach (Art. 158-159)

!!! info "Legal Basis"
    Art. 158 references here cite the PRA Rulebook (CRR Firms) equivalent — the CRR
    version was omitted by SI 2021/1078 (see header admonition). Art. 159 remains in
    UK CRR.

!!! info "Default Definition — Art. 178"
    The Art. 159 EL-vs-provisions comparison partitions exposures into non-defaulted
    (Pool A) and defaulted (Pool C) sides based on the Art. 178 default trigger. The
    formal two-limb trigger, UTP indicators, materiality threshold, and return-to-
    non-defaulted conditions are documented in the shared
    [Default Definition (Art. 178) specification](../common/default-definition.md).
    Default status enters the pipeline via the upstream `is_defaulted` flag.

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
    For **A-IRB defaulted exposures** (PD=1), EL shall be the institution's **best
    estimate of expected loss (BEEL)**, not `PD × LGD` (which would give `1 × LGD`).
    F-IRB defaulted exposures use the standard `1 × LGD × EAD` formula. The spec's
    `EL = PD × LGD × EAD` applies only to non-defaulted exposures and F-IRB defaulted.

    **Article location note.** CRR Art. 158 was omitted on 1 Jan 2022 (SI 2021/1078)
    and migrated to the PRA Rulebook's Credit Risk: Internal Ratings Based Approach
    (CRR) Part — the live article text with the BEEL substitution lives at
    [Basel 3.1 spec — BEEL Exception](../basel31/provisions.md#beel-exception-pool-c-art-1585)
    and [Basel 3.1 Defaulted Exposures — BEEL](../basel31/defaulted-exposures.md#beel-best-estimate-of-expected-loss-art-1585-art-1811hii).
    Pre-revocation CRR used the symbol `ELBE`; PRA PS1/26 renames to `BEEL` with no
    substantive change to the estimation standards in Art. 181(1)(h)(ii). CRR Art. 159
    in the UK-onshored text still cross-references `Art. 158(5)` by that number even
    though the substantive rule now lives in the PRA Rulebook.

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

### Art. 159(3) — Two-Branch Comparison Rule

Art. 159 partitions the EL-vs-provisions comparison into four labelled amounts:

| Label | Definition | Source |
|-------|-----------|--------|
| **A** | EL amounts for **non-defaulted** exposures | Art. 158(5), (6), (10) (PD × LGD × EAD) |
| **B** | Provisions for **non-defaulted** exposures | General CRAs (Art. 110) + specific CRAs for non-defaulted exposures + AVAs (Art. 34) + other own funds reductions |
| **C** | EL amounts for **defaulted** exposures | Art. 158(5), (6), (10) (BEEL for A-IRB; 1 × LGD × EAD for F-IRB) |
| **D** | Specific CRAs for **defaulted** exposures | Art. 110 |

Art. 159(3) sets out **two distinct branches** depending on whether the
non-defaulted and defaulted pools are aligned in sign:

```
Branch 1 — split branch (A > B AND D > C, simultaneously):
    negative amount = B − A    (non-defaulted shortfall)
    positive amount = D − C    (defaulted excess)

Branch 2 — combined branch (all other cases):
    if (A + C) > (B + D):
        negative amount = (B + D) − (A + C)
    if (B + D) > (A + C):
        positive amount = (B + D) − (A + C)
```

The split branch prevents specific CRAs on defaulted exposures from offsetting
expected loss amounts on other (non-defaulted) exposures.

!!! quote "Art. 159(3) — verbatim (UK CRR, as substituted by Reg (EU) 2019/630; mirrored in PRA Rulebook IRB Approach (CRR) Part Art. 159(3))"
    "Where 'A' > 'B' and 'D' > 'C', an institution shall, in order to compare
    expected loss amounts with credit risk adjustments, additional value
    adjustments and other own fund reductions, such that specific credit risk
    adjustments on exposures in default are not used to cover expected loss
    amounts on other exposures:

    (a) calculate the following negative amount: 'B' – 'A'; and

    (b) calculate the following positive amount: 'D' – 'C'.

    In all other cases, an institution shall, in order to compare expected loss
    amounts with credit risk adjustments, additional value adjustments and
    other own fund reductions:

    (c) if ('A' + 'C') > ('B' + 'D'), calculate the following negative amount:
    ('B' + 'D') – ('A' + 'C');

    (d) if ('B' + 'D') > ('A' + 'C'), calculate the following positive amount:
    ('B' + 'D') – ('A' + 'C')."

The **negative amount** (shortfall) is deducted in full from CET1 under
Art. 36(1)(d). The **positive amount** (excess) is added to T2 under
Art. 62(d), subject to the cap defined below.

!!! success "Implemented (P1.81)"
    Art. 159(3) two-branch rule is implemented. When the split branch holds,
    `effective_shortfall = non_defaulted_shortfall = A − B` and
    `effective_excess = defaulted_excess = D − C` — no cross-pool netting.
    The `art_159_3_applies` flag on `ELPortfolioSummary` indicates when the
    split branch is triggered.

### Art. 62(d) — T2 Cap on EL Excess

The Art. 159(3) **positive amount** (EL excess) is admissible to Tier 2
capital under Art. 62(d), but only up to a hard ceiling expressed as a
percentage of IRB credit-risk RWA:

```
T2_credit_cap = 0.006 × IRB_credit_risk_RWA
T2_credit     = min(EL_excess, T2_credit_cap)
```

!!! quote "Art. 62(d) — verbatim (UK CRR; substantive text now in PRA Rulebook Own Funds (CRR) Part Art. 62(d))"
    "(d) credit risk adjustments and provisions for the exposures referred to
    in Article 110(2) … not exceeding 0.6 % of risk weighted exposure amounts
    calculated under Article 153 [the IRB approach]."

The 0.6% cap is **calculated on the un-floored IRB credit-risk RWA**, not
on the post-CCB or post-output-floor TREA. CRR has no output floor, so
this distinction does not arise here — under CRR the IRB RWA base for the
cap is simply the IRB credit-risk RWA from Art. 153.

#### Worked example — both branches

**Scenario A: combined branch with shortfall (CET1 deduction)**

```
Inputs (£m):
  A = 100   (non-defaulted EL)
  B =  60   (non-defaulted provisions + AVAs + other reductions)
  C =  40   (defaulted EL)
  D =  30   (defaulted specific CRAs)
  IRB credit-risk RWA = 12,500

Branch test: A > B (100 > 60) AND D > C? D = 30, C = 40, so D < C.
  → Split branch does NOT apply. Use combined branch.

(A + C) − (B + D) = 140 − 90 = 50 > 0
  → Negative amount = (B + D) − (A + C) = −50.
  → CET1 deduction (Art. 36(1)(d)) = £50m.
  → No T2 credit. T2 cap not engaged.
```

**Scenario B: combined branch with excess, cap binds (T2 credit at cap)**

```
Inputs (£m):
  A =  60
  B = 100
  C =  20
  D =  40
  IRB credit-risk RWA = 12,500

Branch test: A > B? 60 < 100, so split branch does NOT apply.

(B + D) − (A + C) = 140 − 80 = 60 > 0
  → Positive amount (EL excess) = £60m.

T2 cap (Art. 62(d)):
  T2_credit_cap = 0.006 × £12,500m = £75m
  T2_credit     = min(£60m, £75m)  = £60m   (cap not binding)

If instead IRB RWA = £8,000m:
  T2_credit_cap = 0.006 × £8,000m  = £48m
  T2_credit     = min(£60m, £48m)  = £48m   (cap binds — £12m of excess unrecognised)
```

**Scenario C: split branch (Art. 159(3)(a)/(b))**

```
Inputs (£m):
  A = 100   (non-defaulted EL)
  B =  60   (non-defaulted provisions)
  C =  20   (defaulted EL)
  D =  50   (defaulted specific CRAs)
  IRB credit-risk RWA = 10,000

Branch test: A > B (100 > 60) AND D > C (50 > 20)? Yes — split branch applies.

Negative amount (a) = B − A = 60 − 100 = −40   (non-defaulted shortfall £40m)
Positive amount (b) = D − C = 50 − 20 =  30    (defaulted excess £30m)

Capital impact:
  CET1 deduction (Art. 36(1)(d)) = £40m  (full non-defaulted shortfall)
  T2 cap (Art. 62(d)) = 0.006 × £10,000m = £60m
  T2 credit          = min(£30m, £60m) = £30m  (cap not binding)

Note: The £30m defaulted excess is NOT netted against the £40m non-defaulted
shortfall. Cross-pool netting is precisely what Art. 159(3) split branch
prohibits — both the full deduction and the (capped) credit flow through.
```

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
| `t2_credit_cap` | `total_irb_rwa × 0.006` (un-floored IRB credit-risk RWA — CRR has no output floor) | CRR Art. 62(d) |
| `t2_credit` | `min(total_el_excess, t2_credit_cap)` — see [Art. 62(d) — T2 Cap on EL Excess](#art-62d-t2-cap-on-el-excess) for the formula and worked examples | CRR Art. 62(d) |
| `cet1_deduction` | `total_el_shortfall` (full amount) | Art. 36(1)(d) |
| `t2_deduction` | `Decimal(0)` — always zero | — |

!!! warning "Correction: No 50/50 Split Under CRR"
    This table previously showed `cet1_deduction = total_el_shortfall × 0.5` and
    `t2_deduction = total_el_shortfall × 0.5`. That was **wrong** — it described a
    **Basel II** treatment that was superseded by the CRR. CRR Art. 36(1)(d) requires
    the **full** EL shortfall ("negative amounts resulting from the calculation laid down
    in Articles 158 and 159") to be deducted from CET1. Art. 62(d) addresses only
    EL **excess** (positive amounts), not shortfall. There is no T2 deduction for
    shortfall under either CRR or Basel 3.1. The code is correct: `cet1_deduction =
    effective_shortfall`, `t2_deduction = Decimal("0")`.

!!! note "Citation Note"
    Art. 159 computes the shortfall ("negative amount") and excess ("positive amount").
    Art. 36(1)(d) directs the shortfall deduction from CET1. Art. 62(d) directs the
    excess recognition in T2 (capped at 0.6% of IRB RWA). These are distinct provisions
    — Art. 36(1)(d) applies to the full shortfall, not half of it.

## Slotting Approach

Same as IRB: provisions are tracked but not deducted from EAD.

## Key Scenarios

| Scenario ID | Description | Key Validation |
|-------------|-------------|----------------|
| CRR-G1 | SA with specific provision — drawn-first deduction | Provision reduces drawn amount first, remainder reduces nominal before CCF (Art. 111(1)(a)-(b)). Net EAD reflects deduction. |
| CRR-G2 | IRB EL shortfall — provisions < expected loss | EL shortfall = EL − provisions; full CET1 deduction (Art. 36(1)(d)) |
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
