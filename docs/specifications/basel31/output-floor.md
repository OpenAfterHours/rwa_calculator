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
| FR-6.6 | Unrated corporate S-TREA election — flat 100% vs IG/non-IG split with PRA notification (Art. 122(7)–(8)) | P2 | Done (documentation — firm governance upstream; no dedicated engine switch — S-TREA inherits the firm's Art. 122(5)/(6) branch) |

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
| IRB_CET1 | IRB EL shortfall CET1 deduction (EL > provisions) per Art. 36(1)(d). Art. 40 is the technical clarifier — see [Art. 40 — no DTA grossing-up](#art-40-no-deferred-tax-grossing-up-of-the-el-shortfall-deduction). | Art. 36(1)(d), Art. 40 |
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

### Art. 40 — no deferred-tax grossing-up of the EL-shortfall deduction

PRA PS1/26 Art. 92(2A) defines the `IRB CET1` input to OF-ADJ as "amounts calculated in
accordance with point (d) of paragraph 1 of Article 36 **and Article 40** of Own Funds (CRR)
Part" (PS1/26 App 1, p. 13). Art. 40 is **not** a separate prudential filter or supervisory
deduction — it is a one-line technical clarifier that ring-fences how the Art. 36(1)(d) EL-
shortfall deduction is measured.

!!! quote "CRR Art. 40 — verbatim (legislation.gov.uk, eur/2013/575)"
    "**Article 40 — Deduction of negative amounts resulting from the calculation of expected
    loss amounts.**

    The amount to be deducted in accordance with point (d) of Article 36(1) shall not be
    reduced by a rise in the level of deferred tax assets that rely on future profitability,
    or other additional tax effects, that could occur if provisions were to rise to the level
    of expected losses referred to in Section 3 of Chapter 3 of Title II of Part Three."

In practical terms, Art. 40 forbids the firm from netting a hypothetical deferred-tax benefit
against the EL-shortfall CET1 deduction. The deduction is the **gross** EL-minus-provisions
amount; the firm cannot argue that "if we had topped provisions up to EL, we would have
recognised a DTA, so the net CET1 hit is smaller" — that DTA does not exist and Art. 40
prevents it from being imputed.

#### Effect on the OF-ADJ denominator

The PS1/26 Art. 92(2A) cross-reference to Art. 40 ensures the `IRB CET1` term in OF-ADJ is the
same gross figure that would be deducted from CET1 under the Own Funds Part:

```
IRB CET1 (in OF-ADJ) = Art. 36(1)(d) EL-shortfall deduction (gross of imputed DTA per Art. 40)
                     = max(0, EL - eligible provisions)        # Art. 159 Pool A/B/C/D outcome
```

Because OF-ADJ enters the floor formula as `12.5 × (IRB T2 − IRB CET1 − GCRA + SA T2)`, any
under-statement of `IRB CET1` (for example, by netting a hypothetical DTA) would understate
the CET1 add-back and inflate the floored TREA. Art. 40 closes that arbitrage: the same gross
EL-shortfall figure that hits CET1 under Art. 36(1)(d) is the figure that flows into the
OF-ADJ denominator.

!!! note "Engine inputs"
    The `IRB CET1` term is assembled inside the aggregator
    (`src/rwa_calc/engine/aggregator/aggregator.py`) from two sources:

    - **Art. 36(1)(d) deduction** — derived from the Art. 159 EL-vs-provisions comparison
      (`ELPortfolioSummary.cet1_deduction`, computed in
      `src/rwa_calc/engine/aggregator/_el_summary.py`). This is the gross EL-shortfall figure
      that Art. 40 protects from DTA grossing-up.
    - **`OutputFloorConfig.art_40_deductions`** (`src/rwa_calc/contracts/config.py`) — an
      institution-supplied scalar, defaulting to `0.0`. This slot is provided to let firms
      pass through any additional Art. 36(1)(d)/Art. 40 amount that the engine has not
      derived from exposure-level Pool A/B/C/D data (for example, when the EL summary is
      computed outside the engine and only the residual is supplied). Reconciliation between
      the engine-derived figure, this override, and the firm's Own Funds Art. 36(1)(d) line
      is an upstream control — the calculator does not re-derive the deduction from
      first principles when this field is set.

### T2 Component Caps — Art. 62(c) and Art. 62(d)

!!! info "Clarification, not a new mechanic"
    The OF-ADJ formula above is unchanged. This subsection makes explicit the
    pre-existing Tier 2 caps that govern the `IRB T2` and `SA T2` inputs
    **before** they are substituted into the OF-ADJ expression. These caps live
    in Own Funds (CRR) Part Art. 62(c) and (d) — the same provisions that
    Art. 92(2A) names in its OF-ADJ definition — and are applied by the firm
    upstream of the calculator, alongside the GCRA cap that is applied inside
    `compute_of_adj()`.

`IRB T2`, `SA T2`, and `GCRA` are each capped relative to a different RWA base.
The three caps interact but never reduce a positive OF-ADJ below itself by a
single combined ceiling — each input is capped independently before the formula
is evaluated:

| Input | Cap | Reference | Applied where |
|-------|-----|-----------|---------------|
| `IRB T2` (excess provisions) | **0.6% of IRB credit-risk RWA** | Own Funds (CRR) Part Art. 62(d) | Upstream of the engine — the firm passes the post-cap amount via `OutputFloorConfig.irb_t2_credit`. |
| `SA T2` (general credit risk adjustments admitted as Tier 2) | **1.25% of SA credit-risk RWA** | Own Funds (CRR) Part Art. 62(c) | Upstream of the engine — the firm passes the post-cap amount via `OutputFloorConfig.sa_t2_credit`. |
| `GCRA` (general credit risk adjustments) | **1.25% of S-TREA** | PRA PS1/26 Art. 92(2A) | Inside `compute_of_adj()` (`src/rwa_calc/engine/aggregator/_floor.py`) — callers pass the **uncapped** amount. |

!!! quote "PRA PS1/26 Art. 92(2A) — verbatim definitions of the OF-ADJ T2 inputs (PS1/26 App 1, p. 13)"
    "**IRB T2** = amounts calculated in accordance with point (d) of Own Funds
    (CRR) Part Article 62;
    [...]
    **SA T2** = amounts calculated in accordance with point (c) of Own Funds
    (CRR) Part Article 62."

#### Distinguishing `GCRA` from `SA T2`

`GCRA` and `SA T2` both capture general credit risk adjustments, but they enter
OF-ADJ at different points and under different caps:

- **`SA T2`** is the Art. 62(c) Tier 2 credit — GCRAs that the firm admits to
  Tier 2 capital, capped at 1.25% of SA credit-risk RWA. It enters OF-ADJ
  with a positive sign (adding to the Tier 2 base on the SA side of the
  reconciliation).
- **`GCRA`** is the same population of general credit risk adjustments
  measured **gross of tax effects** and capped at 1.25% of S-TREA — the
  output-floor reference base. It enters OF-ADJ with a negative sign
  (subtracting the GCRA element that would otherwise be double-counted on
  the SA side).

The two caps reference different RWA bases (SA credit-risk RWA vs S-TREA),
so the input figures `sa_t2_credit` and `gcra_amount` will not in general be
equal even when they describe the same provisions.

#### Worked illustration

```
Inputs (post Art. 62 caps applied upstream):
  irb_t2_credit       = £20m   (already capped at 0.6% of IRB RWA per Art. 62(d))
  irb_cet1_deduction  = £15m
  gcra_amount         = £40m   (uncapped — engine applies 1.25% of S-TREA)
  sa_t2_credit        = £30m   (already capped at 1.25% of SA RWA per Art. 62(c))
  s_trea              = £2,400m

Engine GCRA cap (Art. 92(2A)):
  gcra_cap     = 1.25% × £2,400m = £30m
  gcra_capped  = min(£40m, £30m) = £30m

OF-ADJ:
  = 12.5 × (irb_t2_credit − irb_cet1_deduction − gcra_capped + sa_t2_credit)
  = 12.5 × (20 − 15 − 30 + 30)
  = 12.5 × 5
  = £62.5m
```

If the firm passed an `irb_t2_credit` or `sa_t2_credit` that exceeded the
Art. 62(d) / Art. 62(c) caps, the engine would not detect or correct it —
the post-cap discipline is institution-side. Reconciliation between the OF-ADJ
inputs and the Tier 2 line items in the firm's COREP own funds template is the
audit gate; see the
[output reporting spec](../output-reporting.md#output-floor-adjustment-of-adj)
for the OF 02.00 / OF 02.01 mapping that consumes these post-cap values.

!!! note "CRR has no equivalent"
    CRR (the framework that applies until 31 December 2026) has no output
    floor and therefore no OF-ADJ. The Art. 62(c) / Art. 62(d) Tier 2 caps
    themselves exist under both CRR and the PRA PS1/26 Own Funds (CRR) Part
    — they are own-funds rules independent of the floor — but the
    cross-link between those caps and the floor reconciliation is a
    Basel 3.1 / PS1/26 construct only.

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

## Unrated Corporate Election (Art. 122(8))

**Art. 122(7)–(8)**

Art. 122(8) governs how **IRB firms** treat unrated non-SME corporate exposures
(Art. 112(1)(g)) in the `S-TREA` leg of the output floor. The election is
output-floor-specific — it does not alter how the same exposures are risk-weighted
for `U-TREA` (IRB) or for SA firms' regular SA capital.

!!! quote "Art. 122(8) — verbatim (PRA PS1/26 p. 45)"
    "For the purposes of calculating the output floor, an institution with permission
    to use the IRB Approach shall, for exposures to which it applies the IRB Approach
    within the exposure class set out in point (g) of Article 112(1), subject to
    paragraph 11:

    (a) assign a 100% risk weight to all exposures for which a credit assessment by a
    nominated ECAI is not available; or

    (b) assign the risk weights in points (a) or (b) of paragraph 6 to all exposures
    for which a credit assessment by a nominated ECAI is not available. **An
    institution that assigns, or ceases to assign, risk weights in accordance with
    this point (b) shall give notice to the PRA.**"

### Two Branches

| Branch | S-TREA weight for unrated non-SME corporates | Requires Art. 122(6) permission? | PRA notification |
|--------|----------------------------------------------|----------------------------------|------------------|
| Art. 122(8)(a) | Flat **100%** (mirrors Art. 122(5) default) | No | Not required |
| Art. 122(8)(b) | **65%** IG / **135%** non-IG (Art. 122(6)(a)/(b) split) | Yes | **Required on adoption *and* on cessation** |

Art. 122(11) SME corporates (turnover ≤ GBP 44m) retain the 85% weight under both
branches — the (a)/(b) election only governs the unrated non-SME population.

### Notification Obligation

Art. 122(8)(b)'s final sentence requires a notification to the PRA whenever the firm
**starts or stops** applying the IG/non-IG split in S-TREA. This is in addition to the
Art. 122(6) prior-permission requirement and the Art. 122(7) sound-processes
obligation. Because the notification is symmetric, the firm must keep a record of
every branch switch — for example, a firm that elects branch (b) for 2027 and
reverts to branch (a) for 2028 owes the PRA two notifications (one at adoption, one
at cessation). This is a firm-governance step upstream of the calculator; the
engine does not emit or record the notification.

### Consistency — Portfolio-wide

Both Art. 122(8)(a) and (b) apply to "**all** exposures for which a credit assessment
by a nominated ECAI is not available". The election is portfolio-wide within the
output-floor corporate population. A firm that has Art. 122(6) permission but
assesses no obligor as IG still applies 135% to every unrated non-SME corporate
under branch (b) — it cannot cherry-pick branch (a) for non-IG obligors while using
branch (b) for IG obligors.

### Why This Matters for Floor-Binding IRB Firms

The S-TREA leg determines the minimum RWA when the output floor binds. Branch (a)
fixes every unrated non-SME corporate at 100%, which is conservative relative to an
IG-heavy portfolio. Branch (b) lets the firm recognise its internal IG assessment
(65%) in S-TREA — typically reducing floor impact materially — at the cost of the
135% penalty on any obligor assessed as non-IG. Firms that expect the floor to bind
should compare the portfolio-weighted 100% against the portfolio-weighted
`w_IG × 65% + w_nonIG × 135%` before electing.

!!! note "Implementation — no dedicated engine switch"
    The engine derives S-TREA by running the SA calculator over the IRB population
    and honouring the firm's Art. 122(5)/(6) branch choice. Firms that already apply
    the IG/non-IG split to their regular SA exposures (i.e., hold Art. 122(6)
    permission and assess internal IG status) automatically get branch (b) in
    S-TREA; firms on Art. 122(5) flat 100% get branch (a). The Art. 122(8) drafting
    permits a firm to elect branch (b) **only** for S-TREA while retaining flat 100%
    for its regular SA unrated corporates, but this split is not supported by a
    single pipeline run — it would require two runs combined externally. See the
    [B31 SA spec](sa-risk-weights.md#output-floor-election-for-unrated-corporates-art-12278)
    for the full treatment including Art. 122(7) sound-processes obligation.

## SA Specialised Lending in S-TREA (Art. 122A–122B, Art. 139(2B))

**Art. 122A, Art. 122B, Art. 139(2B)**

When an IRB firm computes the `S-TREA` leg of the output floor, exposures that
the firm risk-weights via SL slotting under IRB (Art. 153(5)) must be re-mapped
to the **SA specialised-lending regime** in Art. 122A–122B, because S-TREA is the
SA-equivalent quantity (Art. 92(3A) excludes the IRB approach). This subsection
records the rule that determines whether a given SL exposure picks up an
ECAI-driven weight or the unrated SL ladder when it crosses into S-TREA.

!!! warning "Plan-item misattribution corrected"
    `DOCS_IMPLEMENTATION_PLAN.md` item D4.59 originally described an
    "Art. 139(2B) SA specialised lending **exclusion** from the output floor"
    in which IRB firms applying SA SL via Art. 122A "do not include those
    exposures in the output floor SA-RWA calculation". **No such exclusion
    exists in PS1/26 App 1.** Verbatim Art. 139(2B) reads (PS1/26 App 1 p. 71):

    > "Paragraphs 2 and 2A do not apply for the purposes of Article 122B(1)."

    Art. 139(2B) is therefore an **ECAI-rating routing rule** that constrains
    which credit assessments can be used to invoke the rated-SL pathway in
    Art. 122B(1); it is not a carve-out from the output floor and does not
    remove SL exposures from the SA-RWA leg. SA SL exposures continue to enter
    `S-TREA` in full — the only thing Art. 139(2B) governs is **which row of the
    Art. 122A–122B table** they land on once they get there.

### Mechanic

Art. 122B(1) routes a rated SA SL exposure to the rated corporate ECAI table in
Art. 122(2): "Where a relevant issue-specific credit assessment by a nominated
ECAI is available for a specialised lending exposure, an institution shall apply
the risk weight treatment set out in Article 122(2)" (PS1/26 App 1 p. 46). Under
the general ECAI rules, Art. 139(2) and Art. 139(2A) would let the firm fall
back to an issuer-level rating (or a rating on a different issue) where no
directly applicable issue-specific rating exists. Art. 139(2B) **switches both
fallbacks off** for the purposes of Art. 122B(1):

- **Art. 139(2)** — issuer-level rating, or rating from a different issue, where
  the exposure ranks pari passu / senior — **disapplied for SA SL**.
- **Art. 139(2A)** — issuer-level rating that applies only to a limited class of
  liabilities — **disapplied for SA SL**.
- **Art. 122B(1)** therefore requires a **directly issue-specific credit
  assessment** on the SL exposure itself before the rated corporate table is
  used; otherwise the exposure falls to the unrated SL ladder in Art. 122B(2).

### Numerical effect on S-TREA

The practical consequence for IRB firms computing `S-TREA` is that more SL
exposures end up on the **unrated SL ladder** than they would under the
general ECAI rules:

| Path | Without Art. 139(2B) (counterfactual) | With Art. 139(2B) (actual) |
|------|----------------------------------------|-----------------------------|
| SL exposure with issuer-level rating only, no issue-specific rating | Rated corporate table per Art. 122(2) (e.g. CQS 1 → 20%, CQS 3 → 75%) via 139(2) fallback | Unrated SL ladder per Art. 122B(2): OF/CF 100%, PF pre-op 130%, PF op 100%, high-quality op PF 80% |
| SL exposure with directly issue-specific rating | Rated corporate table per Art. 122(2) | **Unchanged** — rated corporate table per Art. 122(2) (Art. 139(2B) does not bite) |
| SL exposure with no rating at all | Unrated SL ladder per Art. 122B(2) | **Unchanged** — unrated SL ladder per Art. 122B(2) |

Because Art. 122B(2) weights cluster at 100% (object/commodities finance and
operational PF) and 130% (pre-operational PF), Art. 139(2B) is generally
**conservative** — it prevents firms from using a low-CQS issuer rating to
weight an unrated PF tranche at 20%–50% in S-TREA. The 80% high-quality
operational PF weight under Art. 122B(4) remains available where the Art.
122B(5) criteria are met, but it is not an ECAI fallback — it is a
structural-quality test on the unrated path.

The rule applies to both branches of the floor formula via S-TREA: it shapes
the SA-equivalent input to `x × S-TREA + OF-ADJ` and is unaffected by the
transitional `x` in Art. 92(5). U-TREA is computed using IRB SL slotting (Art.
153(5)) and is not touched by Art. 139(2B).

### Engine status

The engine's S-TREA path runs the SA calculator over the IRB-permissioned
population, so SL exposures classified under Art. 122A automatically pick up the
Art. 122B(2)/(4) ladder when no rated SA path applies. The Art. 139(2B)
constraint on the rated-SL fallback is **not currently encoded as a dedicated
rating-eligibility check** — the engine treats the firm-supplied
`external_cqs` as already reflecting Art. 138 / Art. 139 routing (consistent
with how Art. 139(6) implicit-support handling is treated upstream — see
[Art. 138(1)(g) / Art. 139(6) treatment in the SA spec](sa-risk-weights.md#ecai-assessment-implicit-government-support-art-1381g-art-1396)).

Firms must therefore either (i) pre-adjust `external_cqs` for SL exposures so
that issuer-level / cross-issue ratings are suppressed before the S-TREA run,
or (ii) model the SL population as unrated and rely on Art. 122B(2)/(4). This
is a documentation gap in `IMPLEMENTATION_PLAN.md` (no dedicated code item
filed at the time of writing) and should be tracked there as a follow-up if
firms in scope of the output floor are observed to rely on Art. 139(2)/(2A)
fallbacks for SL.

!!! note "What this rule is not"
    Art. 139(2B) does **not**:

    - exclude SA SL exposures from S-TREA;
    - reduce S-TREA by the SL RWA;
    - introduce a separate add-on or carve-out term in the
      `TREA = max{U-TREA; x × S-TREA + OF-ADJ}` formula;
    - change the IRB slotting treatment that drives U-TREA.

    It governs ECAI rating eligibility within the unchanged Art. 122B(1) entry
    point only.

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
