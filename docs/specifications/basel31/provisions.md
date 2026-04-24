# Provisions Specification

Basel 3.1 provision treatment: expected loss calculation with revised LGD parameters,
Art. 158(6A) EL monotonicity, and EL shortfall/excess comparison.

**Regulatory Reference:** PRA PS1/26 Art. 158–159, Art. 36(1)(d), Art. 62(d)
**Test Group:** B31-G

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-7.1 | F-IRB EL calculation with revised LGD (40% non-FSE senior) | P0 | Done |
| FR-7.2 | EL shortfall: full CET1 deduction (Art. 36(1)(d)) | P0 | Done |
| FR-7.3 | EL excess: T2 credit (cap at 0.6% of IRB RWA) | P0 | Done |
| FR-7.4 | Art. 158(6A) EL monotonicity for A-IRB PMA | P0 | Done |
| FR-7.5 | SA provision deduction from exposure (unchanged from CRR) | P0 | Done |

---

## Overview

Basel 3.1 modifies the provision and expected loss (EL) framework primarily through the
**reduction of F-IRB supervisory LGD** from 45% to 40% for non-FSE senior unsecured exposures.
This change flows through to the EL calculation, reducing expected loss estimates and
consequently affecting the EL shortfall/excess comparison.

### Key Changes from CRR

| Feature | CRR | Basel 3.1 | Reference |
|---------|-----|-----------|-----------|
| F-IRB senior LGD (non-FSE) | 45% | 40% | Art. 161(1)(aa) |
| F-IRB senior LGD (FSE) | 45% | 45% | Art. 161(1)(a) |
| 1.06 scaling factor | Applied | Removed | Art. 153(1) |
| EL monotonicity (A-IRB PMA) | Not required | Required (Art. 158(6A)) | Art. 158(6A) |
| EL shortfall treatment | Full CET1 deduction | Full CET1 deduction (unchanged) | Art. 36(1)(d) |
| EL excess T2 cap | 0.6% of IRB RWA | Unchanged (0.6%) | Art. 62(d) |
| SA provision deduction | Art. 111(1)(a)–(b) | Unchanged | Art. 111(1)(a)–(b) |

---

## SA Provision Treatment (Unchanged)

For SA exposures, provisions are deducted from the exposure value before risk weighting:

```
EAD_net = EAD_gross - specific_provisions - other_provisions_allocated
```

This is the drawn-first deduction approach per Art. 111(1)(a)–(b):

1. Specific credit risk adjustments reduce the exposure value
2. General credit risk adjustments may be included in Tier 2 capital

No changes from CRR for the SA provision mechanism.

---

## IRB Expected Loss Calculation

### F-IRB Expected Loss

```
EL = PD x LGD x EAD
```

Where LGD is the supervisory LGD from the [F-IRB Specification](firb-calculation.md):

| Collateral Type | CRR LGD | Basel 3.1 LGD | Reference |
|----------------|---------|---------------|-----------|
| Senior unsecured (non-FSE) | 45% | **40%** | Art. 161(1)(aa) |
| Senior unsecured (FSE) | 45% | **45%** | Art. 161(1)(a) |
| Subordinated | 75% | 75% | Art. 161(1)(b) |
| Covered bonds | 11.25% | **11.25%** | Art. 161(1)(d) → Art. 161(1B) |

The reduction from 45% to 40% for non-FSE senior exposures directly reduces F-IRB expected
loss by approximately 11% ((45−40)/45 ≈ 11.1%), leading to:

- Lower EL shortfall (or higher EL excess)
- More capital available as Tier 2 credit
- Structural reduction in the capital penalty for under-provisioned portfolios

### A-IRB Expected Loss

A-IRB uses the firm's own LGD estimates, subject to LGD floors (see [A-IRB Specification](airb-calculation.md)):

```
EL = PD x LGD_floored x EAD
```

### Art. 158(6A) — EL Monotonicity

**Basel 3.1 addition.** When post-model adjustments (PMA) are applied to A-IRB exposures:

```
EL_adjusted >= EL_unadjusted
```

PMA can increase RWA and EL but must **never decrease EL** below the pre-adjustment level.
This ensures that conservative overlays do not inadvertently reduce expected loss estimates.

!!! note "Implementation"
    EL monotonicity is enforced in the A-IRB calculator after PMA application.
    Source: `src/rwa_calc/engine/irb/`

---

## EL Shortfall / Excess Comparison (Art. 159)

The comparison of total expected loss against total provisions determines the capital impact:

### EL Excess (Provisions > EL)

When total provisions exceed total expected loss:

```
el_excess = total_provisions - total_el
t2_credit_cap = total_irb_rwa x 0.006
t2_credit = min(el_excess, t2_credit_cap)
```

The excess (up to the cap) is added to Tier 2 capital per Art. 62(d).

### EL Shortfall (EL > Provisions)

When total expected loss exceeds total provisions:

```
el_shortfall = total_el - total_provisions
cet1_deduction = el_shortfall      (full amount)
```

!!! note "Full CET1 Deduction"
    Art. 36(1)(d) requires the **full** EL shortfall to be deducted from CET1. This is
    **unchanged from CRR** — the 50/50 CET1/T2 split was a Basel II treatment that was
    superseded by the CRR. Art. 62(d) addresses only EL excess (positive amounts), not
    shortfall. There is no T2 deduction for shortfall under either framework.

!!! success "Code Correct (P1.116)"
    `src/rwa_calc/engine/aggregator/_el_summary.py` line 241: `cet1_deduction =
    effective_shortfall` (full amount). Line 252: `t2_deduction = Decimal("0")`.
    Previously this code computed a 50/50 split — that was a Basel II-era error,
    corrected under P1.116.

### Art. 159 Component Definitions

The Art. 159 comparison uses four labelled amounts (A, B, C, D):

| Label | Definition | Source |
|-------|-----------|--------|
| **A** | EL amounts for **non-defaulted** exposures | PD x LGD x EAD (Art. 158) |
| **B** | Provisions for **non-defaulted** exposures | General CRAs + specific CRAs + AVA (Art. 34) + other own funds reductions |
| **C** | EL amounts for **defaulted** exposures | BEEL for A-IRB (Art. 158(5)); PD x LGD for F-IRB |
| **D** | Specific CRAs for **defaulted** exposures | Specific credit risk adjustments |

!!! info "GCRA vs SCRA classification"
    The general/specific CRA split that determines which amounts go into Pool B (general +
    non-defaulted specific), Pool D (defaulted specific only), and the `SA_T2` / `GCRA`
    terms of OF-ADJ is set by **Commission Delegated Regulation (EU) No 183/2014** and
    Art. 110. See the
    [Output Floor spec — GCRA Qualifying Criteria](output-floor.md#general-credit-risk-adjustments-gcra-qualifying-criteria)
    for the verbatim definitions, IFRS 9 Stage 1/2/3 mapping, mixed-approach allocation
    (Art. 110(3)), and double-count avoidance rules.

!!! warning "Previous Spec Error Corrected (P4.38)"
    This table previously labelled Pool A as "non-defaulted EL" and Pool B as
    "defaulted provisions". The regulation uses A/B for non-defaulted (EL vs provisions)
    and C/D for defaulted (EL vs specific CRAs). The labels are now corrected to match
    the Art. 159 text.

### Art. 159(3) — Two-Branch Rule

When **A > B** (non-defaulted EL exceeds non-defaulted provisions) **AND** **D > C**
(defaulted provisions exceed defaulted EL) simultaneously:

- **(a)** Non-defaulted shortfall = **A - B** → deducted from CET1 (Art. 36(1)(d))
- **(b)** Defaulted excess = **D - C** → recognised in T2 (Art. 62(d))

The defaulted excess must **not** offset the non-defaulted shortfall. This prevents
cross-subsidisation between the non-defaulted and defaulted pools.

In **all other cases** (combined treatment):

- **(c)** If (A + C) > (B + D): total shortfall → CET1 deduction (Art. 36(1)(d))
- **(d)** If (B + D) > (A + C): total excess → T2 recognition, **capped at 0.6% of
  credit-risk IRB RWA** (Art. 62(d))

### Art. 159(2) — Exclusions from Provisions (B and D)

The following amounts are **excluded** from the provisions side (B and D):

- Defaulted balance sheet discounts (Art. 166A(2))
- Provisions relating to securitised exposures
- Portions covered by CRM risk-weight substitution

### BEEL Exception (Pool C — Art. 158(5))

For **A-IRB defaulted exposures**, Pool C of the Art. 159 comparison uses the
institution's own **BEEL** (Best Estimate of Expected Loss), not `PD x LGD`. The
defaulted EL amount feeding the provisions-vs-EL shortfall/excess test is therefore:

```
Pool C (A-IRB defaulted) = Σ (BEEL_i × EAD_i)
Pool C (F-IRB defaulted) = Σ (1 × LGD_i × EAD_i)   # standard Art. 158(5) formula, PD = 1
```

!!! quote "PRA PS1/26 Art. 158(5) verbatim (ps126app1.pdf p. 107)"
    "[E]xcept for defaulted exposures (PD = 1) where the institution uses the Advanced
    IRB Approach, EL shall be BEEL."

**BEEL is an Art. 158(5) / Art. 181(1)(h)(ii) parameter**, defined in the PRA Rulebook
(Credit Risk: IRB Approach (CRR) Part, Rule 1.3) as *"an institution's best estimate of
expected loss for a defaulted exposure as referred to in point (h)(ii) of Article
181(1)"*. The estimation standards (downturn conditions, unexpected additional
loss during the recovery period, governance and back-testing) are set out in
Art. 181(1)(h)(ii). Under pre-revocation CRR the same parameter was called **`ELBE`**;
PS1/26 renames it to `BEEL` with no substantive change.

**Scope — A-IRB only.** The BEEL substitution operates solely on the Pool C EL
**amount**. F-IRB defaulted exposures use `1 × LGD` (supervisory) for Pool C, since
they do not benefit from own-LGD estimation permissions. The distinct A-IRB
**capital formula** `K = max(0, LGD − BEEL)` (Art. 154(1)(i)) lives in the
defaulted-exposures spec, not here — see
[Defaulted Exposures — BEEL](defaulted-exposures.md#beel-best-estimate-of-expected-loss-art-1585-art-1811hii).

**Interaction with Art. 158(6A).** The BEEL-based Pool C total is **increased** by any
post-model adjustments recognised under Art. 146(3)(c) before entering the Art. 159
test (see [Art. 158(6A) — EL Monotonicity](#art-1586a-el-monotonicity) above).

!!! info "Sovereign/central-bank carve-out"
    Under Art. 147A(1)(a), sovereign, central-bank, RGLA, PSE, MDB and
    international-organisation exposures cannot use A-IRB, so BEEL does not arise for
    these classes — any defaulted quasi-sovereign exposure is handled under SA
    (Art. 127) with no Pool C contribution from the IRB side.

---

## Key Scenarios

| Scenario ID | Description | Expected Outcome |
|-------------|-------------|------------------|
| B31-G1 | SA provision deduction (unchanged from CRR) | EAD reduced by provisions |
| B31-G2 | F-IRB EL shortfall: LGD 40% (was 45%), shortfall lower than CRR | Full CET1 deduction (Art. 36(1)(d)) |
| B31-G3 | F-IRB EL excess: T2 credit capped at 0.6% of IRB RWA | T2 credit = min(excess, cap) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-G: Provisions | G1–G3 | 24 | 100% (24/24) |
