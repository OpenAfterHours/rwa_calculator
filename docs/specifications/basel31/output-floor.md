# Output Floor Specification

Basel 3.1 output floor mechanism limiting the benefit of internal models relative to the Standardised Approach.

**Regulatory Reference:** PRA PS1/26 Art. 92(2A)–(2D), Rules 3.1–3.3
**Test Group:** B31-F

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6.1 | Output floor calculation — RWA_floored = max(RWA_IRB, floor% × RWA_SA) | P0 | Done |
| FR-6.2 | PRA 4-year transitional schedule (60%–72.5%, 2027–2030) | P0 | Done |
| FR-6.3 | OF-ADJ own funds adjustment | P1 | Done |
| FR-6.4 | Entity-type carve-outs (Art. 92(2A)(b)–(d)) | P2 | Done |

---

## Overview

The output floor prevents IRB firms from reducing their total RWA below a specified percentage of what
the Standardised Approach would produce. This addresses the concern that internal models can produce
unjustifiably low capital requirements.

!!! warning "PRA vs BCBS Schedule"
    The PRA adopts a **4-year** transitional schedule (2027–2030), not the BCBS 6-year schedule
    (2023–2028). All PRA dates are shifted to align with the UK implementation timeline.

## Floor Calculation

The floored RWA for an IRB firm is:

```
RWA_floored = max(RWA_IRB, floor_percentage x RWA_SA)
```

Where:

- `RWA_IRB` = total RWA calculated under the firm's approved IRB approach
- `RWA_SA` = total RWA that would apply if the entire portfolio were under the Standardised Approach
- `floor_percentage` = the applicable transitional or fully-phased floor rate

The floor applies at the **consolidated level**, not to individual exposures. The output floor
impact is the additional RWA needed:

```
floor_impact = max(0, floor_percentage x RWA_SA - RWA_IRB)
```

## PRA Transitional Schedule

**Art. 92(2A), Rules 3.1–3.3**

| Year | Floor Percentage | Rule Reference |
|------|-----------------|----------------|
| 2027 | 60% | Rule 3.1(a) |
| 2028 | 65% | Rule 3.1(b) |
| 2029 | 70% | Rule 3.1(c) |
| 2030+ | 72.5% | Rule 3.1(d) — fully phased |

!!! note "Configuration"
    The floor percentage is set via `CalculationConfig.basel_3_1(output_floor_percentage=0.725)`.
    Transitional percentages are selected by setting the appropriate year's value.
    Source: `src/rwa_calc/contracts/config.py`

## OF-ADJ Capital Adjustment

**Art. 92(2B)–(2D)**

When the output floor binds (i.e., floor RWA > IRB RWA), an adjustment to own funds requirements
is needed to avoid double-counting provisions already deducted under IRB:

```
OF-ADJ = max(0, SA_T2 - IRB_T2 + GCRA + IRB_CET1)
```

Where:

- `SA_T2` = Tier 2 credit for SA provisions (excess of provisions over expected credit losses under SA)
- `IRB_T2` = Tier 2 credit for IRB EL excess (Art. 62(d), capped at 0.6% of IRB RWA)
- `GCRA` = General credit risk adjustment (provisions not allocated to specific exposures)
- `IRB_CET1` = CET1 deduction for IRB EL shortfall (50% of shortfall per Art. 36(1)(d))

The OF-ADJ is added back to own funds when the floor binds, preventing a firm from being penalised
twice for the same provisions under both the IRB and SA frameworks.

## Entity-Type Carve-Outs

**Art. 92(2A)(b)–(d)**

Certain entity types may be excluded from the output floor calculation:

- **(b)** Investment firms meeting specific conditions
- **(c)** Central counterparties (CCPs)
- **(d)** Firms with no IRB permission (floor is moot — they already use SA)

!!! note "Implementation Status"
    Entity-type carve-outs are implemented in the output floor calculator.
    Source: `src/rwa_calc/engine/output_floor/`

## Structural Invariants

The output floor has two structural invariants verified by acceptance tests:

1. **Non-reduction invariant** — The floor can only increase total RWA, never decrease it:
   `RWA_floored >= RWA_IRB`
2. **Non-negative impact** — The floor impact is always ≥ 0:
   `floor_impact >= 0`

These invariants hold regardless of portfolio composition or floor percentage.

---

## Key Scenarios

| Scenario ID | Description | Expected Outcome |
|-------------|-------------|------------------|
| B31-F1 | Low-PD corporate: SA RW × 72.5% > IRB RW — floor binds | RWA = 72.5% × SA RWA |
| B31-F2 | High-PD exposure: IRB RW > SA RW × 72.5% — floor does not bind | RWA = IRB RWA (unchanged) |
| B31-F3 | 2027 transitional: same portfolio as F1 at 60% floor | RWA = 60% × SA RWA |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-F: Output Floor | F1–F3 | 6 | 100% (6/6) |
