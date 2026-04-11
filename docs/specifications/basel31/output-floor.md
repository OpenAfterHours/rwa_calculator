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

The full TREA formula from PRA PS1/26 Art. 92(2A) is:

```
TREA = max{U-TREA; x × S-TREA + OF-ADJ}
```

Where:

- **U-TREA** = un-floored total risk exposure amount (Art. 92(3))
- **S-TREA** = standardised total risk exposure amount (Art. 92(3A)) — calculated without IRB, SFT VaR, SEC-IRBA, IAA, IMM, or IMA
- **x** = 72.5% fully phased (or transitional rate per Art. 92(5))
- **OF-ADJ** = own-funds adjustment reconciling IRB vs SA provisions treatment — see [below](#of-adj-capital-adjustment)

At the RWA level (ignoring OF-ADJ for simplicity):

```
RWA_floored = max(RWA_IRB, floor_percentage × RWA_SA)
floor_impact = max(0, floor_percentage × RWA_SA - RWA_IRB)
```

The floor applies at the **portfolio level** (per entity/basis combination — see
[Entity-Type Applicability](#entity-type-applicability)), not to individual exposures.
The floor impact is allocated pro-rata to IRB exposures by their share of S-TREA.

## PRA Transitional Schedule

**Art. 92(5), Rules 3.1–3.3**

!!! warning "Article Number Correction (P4.46)"
    The transitional schedule is in **Art. 92(5)**, not Art. 92(2A). Art. 92(2A) contains
    the output floor **formula** (`TREA = max{U-TREA; x * S-TREA + OF-ADJ}`).
    Art. 92(5) is the transitional **opt-in** allowing institutions to apply reduced
    floor percentages during the phase-in period.

The transitional percentages are **permissive** ("may apply"), not mandatory. An institution
may elect to apply the full 72.5% floor from day one. If the transitional is elected, the
following schedule applies:

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

**Art. 92(2A)**

The TREA formula includes an OF-ADJ term that reconciles the different treatment of provisions
under IRB and SA, ensuring the floor comparison is on a like-for-like own-funds basis:

```
OF-ADJ = 12.5 x (IRB_T2 - IRB_CET1 - GCRA + SA_T2)
```

| Component | Description | Regulatory Ref |
|-----------|-------------|----------------|
| IRB_T2 | IRB excess provisions T2 **credit** (provisions > EL): Art. 62(d) excess, i.e., where provisions exceed EL amounts | Art. 62(d) |
| IRB_CET1 | IRB EL shortfall CET1 deduction (EL > provisions) per Art. 36(1)(d), plus any supervisory deductions under Art. 40 | Art. 36(1)(d), Art. 40 |
| GCRA | General credit risk adjustments included in T2, gross of tax effects. **Capped at 1.25% of S-TREA** (the standardised total risk exposure amount). | Art. 62(c), Art. 92(2A) |
| SA_T2 | SA general credit risk adjustments recognised as T2 capital under Art. 62(c) | Art. 62(c) |

!!! note "GCRA Cap"
    The GCRA component is capped at **1.25% of S-TREA** (not 1.25% of IRB RWA). This cap
    prevents the OF-ADJ from being inflated by large general provisions relative to the
    standardised risk exposure base.

The 12.5 multiplier converts own-funds amounts to risk-weighted equivalents (the inverse of the 8%
minimum capital ratio). Under IRB, EL shortfall adds to capital requirements (via CET1 deduction)
while excess provisions provide T2 relief. Under SA, general credit risk adjustments provide T2
relief directly. Without OF-ADJ, switching from IRB to SA in the floor comparison would change
the own-funds base, making the TREA comparison inconsistent.

!!! info "Full formula context"
    The complete output floor formula is `TREA = max{U-TREA; x × S-TREA + OF-ADJ}` — see the
    [Floor Calculation](#floor-calculation) section above and the
    [output reporting spec](../output-reporting.md#output-floor-adjustment-of-adj) for COREP
    template mapping.

## Entity-Type Applicability

**Art. 92(2A)(a)–(d)**

The output floor formula applies only to specific entity/basis combinations. All other
combinations use U-TREA (the un-floored amount) directly.

### Floor Applies To

| Art. 92 Para | Entity Type | Reporting Basis |
|--------------|-------------|-----------------|
| 2A(a)(i) | Standalone UK institution; ring-fenced body not in sub-consolidation group | Individual |
| 2A(a)(ii) | Ring-fenced body in sub-consolidation group | Sub-consolidated |
| 2A(a)(iii) | CRR consolidation entity (**not** an international subsidiary) | Consolidated |

### Floor Does NOT Apply To

| Art. 92 Para | Entity Type | Reporting Basis | Reason |
|--------------|-------------|-----------------|--------|
| 2A(b) | Institution other than a ring-fenced body | Sub-consolidated | Non-RFB on sub-consolidated basis |
| 2A(c) | Ring-fenced body in sub-consolidation group; non-standalone UK institution | Individual | Individual basis where sub-consolidation applies |
| 2A(d) | CRR consolidation entity that is an international subsidiary | Consolidated | International subsidiary exemption |

!!! note "Implementation"
    Entity-type carve-outs are implemented via `OutputFloorConfig.is_floor_applicable()` which
    checks the `institution_type` / `reporting_basis` combination against the applicable set.
    When both are `None`, the floor defaults to applicable (backward-compatible mode).
    Source: `src/rwa_calc/contracts/config.py`

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
