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
| FR-6.5 | GCRA qualifying criteria (Art. 110, Reg (EU) 183/2014) documented | P1 | Done (documentation — institution-supplied input) |

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
| 2027 | 60% | Art. 92(5)(a) |
| 2028 | 65% | Art. 92(5)(b) |
| 2029 | 70% | Art. 92(5)(c) |
| 2030+ | 72.5% | Art. 92(2A) — fully phased |

!!! warning "Art. 92(5) has only three transitional steps"
    PS1/26 App 1 Art. 92(5) (p.15) enumerates three periods only — (a) 60% from
    1 Jan 2027 to 31 Dec 2027, (b) 65% from 1 Jan 2028 to 31 Dec 2028, and
    (c) 70% from 1 Jan 2029 to 31 Dec 2029. There is **no Art. 92(5)(d)**. From
    1 Jan 2030 onwards the transitional election falls away and the fully
    phased 72.5% applies directly under Art. 92(2A). The `2030+ / 72.5%` row
    above reflects the steady-state Art. 92(2A) formula, not a fourth
    transitional step.

    Verbatim PDF quote (PS1/26 App 1, p.15):

    > "When calculating TREA for the purposes of paragraph 2A(a), an
    > institution or CRR consolidation entity **may** apply the following
    > factor x during the periods specified below:
    > (a) 60% during the period from 1 January 2027 to 31 December 2027;
    > (b) 65% during the period from 1 January 2028 to 31 December 2028;
    > (c) 70% during the period from 1 January 2029 to 31 December 2029."

!!! note "Configuration"
    The floor percentage is set via `CalculationConfig.basel_3_1(output_floor_percentage=0.725)`.
    Transitional percentages are selected by setting the appropriate year's value.
    The `skip_transitional` config flag on `OutputFloorConfig` bypasses the
    Art. 92(5) election and forces the steady-state 72.5% from day one. Source:
    `src/rwa_calc/engine/aggregator/_floor.py` and
    `src/rwa_calc/contracts/config.py:OutputFloorConfig`.

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

## General Credit Risk Adjustments (GCRA) — Qualifying Criteria

**Art. 110(1)–(3A), Art. 62(c), Commission Delegated Regulation (EU) No 183/2014**

The OF-ADJ `GCRA` term (capped at 1.25% of S-TREA) and the `SA_T2` term both aggregate
**general credit risk adjustments only** — specific credit risk adjustments (SCRAs) follow a
different capital path via exposure-value reduction (SA) or Pool D of Art. 159 (IRB defaulted).
Incorrectly classifying an SCRA as GCRA (or vice versa) produces a mis-stated OF-ADJ, so the
GCRA/SCRA boundary and its IFRS 9 mapping must be established upstream of the engine.

### GCRA vs SCRA Definition

The general/specific CRA split is fixed by **Commission Delegated Regulation (EU) No 183/2014**
— the "RTS on credit risk adjustments", onshored under UK law and cross-referenced by
Art. 110 and Art. 159(1). Reg (EU) 183/2014 superseded EBA GL 2013/04, which had set the
same framework prior to CRR2.

| Category | Scope (Reg (EU) 183/2014) | Typical IFRS 9 source |
|----------|---------------------------|-----------------------|
| **General CRA (GCRA)** | Loss allowances covering incurred-but-not-yet-identified losses on the **non-defaulted** portfolio, **not allocated to any specific exposure**, and "freely and fully available with regard to timing and amount" to absorb credit losses that have not yet materialised (Reg 183/2014 Art. 1(5)(b)). | Stage 1 (12-month ECL) pool allowances; Stage 2 ECL produced by a **collective** model and not attached to a named obligor. |
| **Specific CRA (SCRA)** | Loss allowances that have been **allocated to a specific exposure or group of exposures** because credit deterioration has been identified (Reg 183/2014 Art. 1(5)(a)). Always tied to a named obligor, facility, or homogeneous sub-pool. | Stage 2 individually assessed (watch-list); Stage 3 (credit-impaired) allowances. |

!!! note "IFRS 9 staging does not map mechanically"
    Stage 1 is almost always GCRA because it is measured on a 12-month collective basis and
    does not identify losses on specific exposures. Stage 3 is almost always SCRA because it
    covers exposures that have already met the credit-impaired / default test under Art. 178.
    **Stage 2 is the ambiguous bucket.** A Stage 2 allowance produced by a lifetime-ECL
    collective model and held at portfolio level is GCRA; a Stage 2 allowance derived from
    individual obligor review (for example, a watch-list SICR overlay) is SCRA. Institutions
    must document the Stage 2 split methodology and apply it consistently across reporting
    periods.

!!! warning "Exclusion — funds for general banking risk"
    Funds for general banking risk (contingency reserves held as free capital rather than
    against specific credit exposures) are **not** GCRA and must be excluded. See
    Art. 110(2) final sentence: "general and specific credit risk adjustments shall exclude
    funds for general banking risk."

### Framework Treatment by Approach

Art. 110 routes each CRA category to a different capital path depending on whether the
underlying exposure is measured under SA or IRB:

| Category | SA exposures | IRB exposures |
|----------|-------------|---------------|
| **GCRA** | T2 credit per Art. 62(c) — populates `SA_T2` in OF-ADJ. (The separate `GCRA` term in OF-ADJ is the portion of GCRA that is carried as T2 gross of the 1.25% S-TREA cap.) | Enters Pool B of Art. 159 per Art. 110(2); if `A + C > B + D` → CET1 deduction (Art. 36(1)(d)); if `B + D > A + C` → T2 credit capped at 0.6% of IRB credit-risk RWA (Art. 62(d)). |
| **SCRA — non-defaulted** | Reduces exposure value: `EAD_net = EAD_gross − SCRA` (Art. 111(1)(a)). Does **not** flow to `SA_T2`. | Enters Pool B of Art. 159 together with GCRA; does not reduce EAD. |
| **SCRA — defaulted** | Reduces exposure value (Art. 111(1)(a)); may also drive the 20% provision-coverage split under Art. 127(1)(a). | Enters Pool D of Art. 159 — drives the defaulted-EL vs provisions comparison for defaulted exposures. |

See the [Provisions Specification](provisions.md#el-shortfall--excess-comparison-art-159)
for full Art. 159 Pool A / B / C / D mechanics.

### Mixed-Approach Allocation (Art. 110(3), (3A))

Institutions that apply IRB to some exposures and SA to others must split GCRA between
the two capital paths **before** OF-ADJ is computed. The allocation is prescriptive:

- **Art. 110(3)(a)** — GCRA of a subsidiary that exclusively applies IRB → IRB treatment (Art. 159 + Art. 62(d)).
- **Art. 110(3)(b)** — GCRA of a subsidiary that exclusively applies SA → SA treatment (Art. 62(c)).
- **Art. 110(3)(c)** — The remainder (unallocated parent-level GCRA) is pro-rated across IRB and SA by the share of risk-weighted exposure amounts subject to each approach.
- **Art. 110(3A)** — Where the IRB firm uses the Risk-Weight Substitution Method (Art. 235), the covered portion of an exposure is treated **as if it were under SA** for the purposes of the GCRA allocation. The substituted RW drives the classification, not the original obligor's approach.

### Double-Count Avoidance

The GCRA / SCRA framework is designed to recognise each loss allowance exactly once.
The key invariants are:

1. **SCRAs reduce EAD at the exposure level under SA** (Art. 111(1)(a)). They do **not**
   additionally flow into `SA_T2` or the `GCRA` term in OF-ADJ. The same amount cannot
   be used twice.
2. **GCRAs never reduce EAD** under either approach. They are a capital-side item only,
   feeding `SA_T2` for SA exposures (Art. 62(c)) and Pool B of Art. 159 for IRB exposures.
3. **Under IRB, neither GCRA nor SCRA reduces EAD.** Both feed Pool B (non-defaulted) or
   Pool D (defaulted SCRA only) in the Art. 159 comparison — see Art. 159(1) Pool B items
   (i) general CRAs, (ii) specific CRAs for non-defaulted exposures.
4. **Securitisation exclusion** (Art. 159(2)(b)) — general and specific CRAs that relate
   to securitised exposures are excluded from both B and D; the securitisation framework
   handles those provisions separately.
5. **Risk-Weight Substitution exclusion** (Art. 159(2)(c)) — CRAs on the portion of an
   exposure covered by Art. 235 substitution are excluded from B and D because the
   covered portion is already reflected via the guarantor's risk weight.

### Input Source and Validation

!!! warning "Engine inputs are institution-supplied"
    The calculator does **not** derive GCRA from IFRS 9 balances. Classification under
    Reg (EU) 183/2014 and Art. 110 must be performed upstream, and the resulting
    GCRA-qualifying amounts supplied to the engine through two fields on
    `OutputFloorConfig`:

    - `OutputFloorConfig.gcra_amount` — the institution's total qualifying GCRA (gross of
      tax effects). The engine applies the 1.25% S-TREA cap inside `compute_of_adj()`
      (`src/rwa_calc/engine/aggregator/_floor.py`); callers should pass the **uncapped**
      qualifying amount and let the engine cap it.
    - `OutputFloorConfig.sa_t2_credit` — the SA-side GCRA recognised under Art. 62(c).
      For firms with no IRB exposure (or whose IRB GCRA allocation per Art. 110(3)(a)
      is zero) this equals the total qualifying GCRA; for mixed-approach firms it is
      the portion attributable to SA under Art. 110(3)(a)–(c).

    Both inputs must reconcile to the same Reg (EU) 183/2014 classification. COREP
    CMS1/CMS2 column d and OF 02.01 row 0040 ("GCRA included in T2") are reported from
    these two fields post-cap — see the
    [output reporting spec](../output-reporting.md#output-floor-adjustment-of-adj).

!!! info "Config factories"
    `CalculationConfig.basel_3_1()` defaults both `gcra_amount` and `sa_t2_credit` to
    zero, producing a conservative OF-ADJ that omits the T2 benefit. Firms that hold
    qualifying GCRA must pass explicit values — for example:

    ```python
    from rwa_calc.contracts.config import CalculationConfig

    cfg = CalculationConfig.basel_3_1(
        gcra_amount=50_000_000.0,   # £50m Reg 183/2014-qualifying GCRA
        sa_t2_credit=50_000_000.0,  # same amount if fully SA-allocated
    )
    ```

    The CRR factory (`CalculationConfig.crr()`) does not expose `gcra_amount` / `sa_t2_credit`
    because CRR has no output floor (OF-ADJ = 0).

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

## Per-exposure vs portfolio-level reporting

!!! warning "Per-exposure `floor_rwa` does NOT include OF-ADJ"
    The output aggregator exposes a per-exposure `floor_rwa` column on IRB rows,
    computed as the pro-rata SA-share of `floor_percentage × S-TREA`. This
    column **does not** allocate the `OF-ADJ` capital adjustment across
    exposures — OF-ADJ is an own-funds reconciliation defined at the
    portfolio/entity level (Art. 92(2A)) and has no meaningful per-exposure
    decomposition. Only the portfolio-level `shortfall` (the amount that the
    floored TREA exceeds un-floored TREA) reflects the full
    `x × S-TREA + OF-ADJ` formula.

    Consumers that need a floor number inclusive of OF-ADJ must read
    `OutputFloorSummary.of_adj` and `OutputFloorSummary.floored_trea` at the
    portfolio level, not sum the per-exposure `floor_rwa` column. This is
    particularly relevant for COREP C 02.00 row mapping where OF-ADJ is a
    separate line item and must not be mingled with per-exposure floor
    numerators.

    See `OutputFloorSummary` in `src/rwa_calc/contracts/bundles.py` for the
    portfolio-level fields, and the
    [output reporting spec](../output-reporting.md#output-floor-adjustment-of-adj)
    for COREP mapping.

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
