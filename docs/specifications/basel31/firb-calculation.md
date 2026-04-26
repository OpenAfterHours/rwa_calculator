# Foundation IRB Specification

Basel 3.1 Foundation IRB changes: reduced senior LGD, higher PD floors, covered bond LGD,
1.06 scaling removal, and GBP-native SME correlation thresholds.

**Regulatory Reference:** PRA PS1/26 Art. 153–163, 178, CRE31–32
**Test Group:** B31-B

!!! info "Default Definition — Art. 178"
    Defaulted-exposure routing (K = 0) is triggered by the Art. 178 default definition.
    PS1/26 Art. 178 introduces hardcoded materiality thresholds (retail GBP 0 / 0%;
    non-retail GBP 440 / 1%), explicit DPD-counter suspensions (Art. 178(1A)–(1D)), and
    a 1-year distressed-restructuring probation (Art. 178(5A)–(5C)). See the
    [Default Definition (Art. 178) specification](../common/default-definition.md).

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-3.1 | Revised supervisory LGD: 40% non-FSE senior (was 45%) | P0 | Done |
| FR-3.2 | FSE senior LGD distinction: 45% (Art. 161(1)(a)) | P0 | Done |
| FR-3.3 | PD floor increase: 0.05% corporate (was 0.03%) | P0 | Done |
| FR-3.4 | Retail PD floors: mortgage 0.10%, QRRE revolver 0.10%, other 0.05% | P0 | Done |
| FR-3.5 | 1.06 scaling factor removed | P0 | Done |
| FR-3.6 | Covered bond LGD: 11.25% — Art. 161(1)(d), unchanged from CRR | P0 | Done |
| FR-3.7 | Collateral-type LGDS reductions (receivables, RE, other physical) | P0 | Done |
| FR-3.8 | GBP-native SME correlation thresholds (£4.4m–£44m) | P0 | Done |

---

## Overview

Basel 3.1 makes significant changes to the F-IRB framework, primarily reducing the benefit of
internal models by tightening supervisory parameters and removing the scaling factor.

### Key Changes from CRR

| Parameter | CRR | Basel 3.1 | Reference |
|-----------|-----|-----------|-----------|
| Senior unsecured LGD (non-FSE) | 45% | **40%** | Art. 161(1)(aa) |
| Senior unsecured LGD (FSE) | 45% | **45%** | Art. 161(1)(a) |
| Subordinated LGD | 75% | 75% | Art. 161(1)(b) |
| Covered bond LGD | 11.25% | **11.25%** | Art. 161(1)(d) (unchanged from CRR) |
| Senior purchased receivables LGD | 45% | **40%** | Art. 161(1)(e) |
| Subordinated purchased receivables LGD | 100% | 100% | Art. 161(1)(f) |
| Dilution risk LGD | 75% | **100%** | Art. 161(1)(g) |
| Corporate PD floor | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign/institution PD floor | 0.03% | **0.05%** | Art. 160(1) |
| Scaling factor | 1.06 | **1.00** (removed) | Art. 153(1) |
| SME turnover range | EUR 5m–50m | **GBP 4.4m–44m** | Art. 153(4) |

---

## Supervisory LGD (Art. 161)

### Unsecured Exposures

| Category | LGD | Reference |
|----------|-----|-----------|
| Senior unsecured (non-FSE) | **40%** | Art. 161(1)(aa) |
| Senior unsecured (FSE) | **45%** | Art. 161(1)(a) |
| Subordinated | **75%** | Art. 161(1)(b) |
| Covered bonds | **11.25%** | Art. 161(1)(d) |
| Senior purchased corporate receivables | **40%** | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | **100%** | Art. 161(1)(f) |
| Dilution risk of purchased corporate receivables | **100%** | Art. 161(1)(g) |

!!! info "Covered Bond LGD — Art. 161(1)(d)"
    The 11.25% covered bond LGD remains at PRA PS1/26 Art. 161(1)(d) (verified against
    ps126app1.pdf p.110, 17 Apr 2026). Earlier drafts of this spec cited a standalone
    "Art. 161(1B)" — that sub-paragraph does not exist in the onshored text; the rule
    sits at point (d) of paragraph (1), unchanged from CRR Art. 161(1)(d).

!!! note "FSE Distinction — New in Basel 3.1"
    Basel 3.1 introduces a new distinction for financial sector entities (FSEs). Non-FSE senior
    unsecured exposures benefit from a reduced 40% LGD, while FSE senior unsecured retains the
    CRR 45% rate. This recognises the higher loss severity observed for financial institution
    defaults. FSE is defined per Art. 4(1)(27); "large FSE" per PS1/26 Glossary p. 78
    (total assets ≥ GBP 79 billion; corresponds to CRR Art. 142(1)(4) which sets EUR 70bn).

!!! info "Purchased Receivables Changes (Art. 161(1)(e)–(g))"
    Art. 161(1)(e) aligns the senior purchased receivables LGD with the new non-FSE rate
    (CRR 45% → B31 40%). The condition changes from "PD estimates do not meet Section 6
    requirements" to "PD is determined in accordance with Art. 160(2)(a)". Art. 161(1)(g)
    increases the dilution risk LGD from CRR 75% to **100%**, aligning with the subordinated
    rate and reflecting the PRA's position that dilution losses receive no recovery benefit.
    Art. 161(1)(f) (subordinated purchased receivables at 100%) is unchanged.

### Collateral-Type LGDS Values (Art. 230, CRE32.9–12)

When exposures are secured by eligible collateral, the F-IRB supervisory LGDS values apply:

| Collateral Type | CRR LGDS | Basel 3.1 LGDS | Reference |
|----------------|----------|----------------|-----------|
| Financial collateral / cash | 0% | 0% | — |
| Receivables | 35% | **20%** | CRE32.9 |
| Residential RE | 35% | **20%** | CRE32.10 |
| Commercial RE | 35% | **20%** | CRE32.11 |
| Other physical | 40% | **25%** | CRE32.12 |

### Overcollateralisation Requirements

Unchanged from CRR:

| Collateral Type | OC Ratio | Min Threshold |
|----------------|----------|---------------|
| Financial | 1.00× | 0% |
| Receivables | 1.25× | 0% |
| Residential RE | 1.40× | 30% |
| Commercial RE | 1.40× | 30% |
| Other physical | 1.40× | 30% |

### Blended LGD Formula (Art. 230)

For partially secured exposures, the effective LGD blends secured and unsecured components:

```
LGD_effective = (E_unsecured / EAD) x LGDU + sum_i((E_i / EAD) x LGDS_i)
```

Where:

- `LGDU` = unsecured LGD (40% non-FSE senior, 45% FSE, 75% subordinated)
- `LGDS_i` = secured LGD for collateral type i
- `E_unsecured` = exposure amount not covered by collateral
- `E_i` = exposure amount secured by collateral type i

See [CRM Specification](credit-risk-mitigation.md) for haircut application details.

---

## PD Floors (Art. 160, 163)

### Corporate, Sovereign, and Institution

| Exposure Class | CRR Floor | Basel 3.1 Floor | Reference |
|---------------|-----------|-----------------|-----------|
| Corporate | 0.03% | **0.05%** | Art. 160(1) |
| Corporate SME | 0.03% | **0.05%** | Art. 160(1) |
| Sovereign | 0.03% | **0.05%** | Art. 160(1) |
| Institution | 0.03% | **0.05%** | Art. 160(1) |

!!! warning "Sovereign PD Floor is Regulatory Dead Letter (Art. 147A(1)(a))"
    Under Basel 3.1, central-government, central-bank and quasi-sovereign exposures
    (Art. 147(2)(a)) are **restricted to the Standardised Approach** by Art. 147A(1)(a).
    F-IRB and A-IRB are both unavailable, and PS1/26 provides **no grandfathering or
    transitional carve-out** for pre-existing sovereign IRB models. The 0.05% sovereign
    PD floor row above is retained for completeness and CRR cross-reference only — under
    Basel 3.1 it cannot bind on any live exposure.

    Institution exposures (Art. 147(2)(b)) are capped at F-IRB by Art. 147A(1)(b)
    (A-IRB unavailable; SA applies only where permission has been granted under
    Art. 148 or Art. 150). The 0.05% institution PD floor therefore applies normally
    to F-IRB institution exposures and is **not** dead letter.

    See [framework-comparison — IRB approach restrictions](../../framework-comparison/key-differences.md#irb-approach-restrictions)
    for the full Art. 147A(1) class-by-class mapping.

### Retail

| Retail Sub-Class | CRR Floor | Basel 3.1 Floor | Reference |
|-----------------|-----------|-----------------|-----------|
| Retail mortgage (residential) | 0.03% | **0.10%** | Art. 163(1)(b) |
| QRRE revolver | 0.03% | **0.10%** | Art. 163(1)(a) |
| QRRE transactor | 0.03% | **0.05%** | Art. 163(1)(c) |
| Retail other | 0.03% | **0.05%** | Art. 163(1)(c) |

!!! note "QRRE Transactor vs Revolver"
    Basel 3.1 introduces differentiated PD floors for qualifying revolving retail exposures (QRRE).
    Revolvers (borrowers who carry balances) receive a higher 0.10% floor, while transactors
    (borrowers who pay in full each period) receive the lower 0.05% floor. This reflects the
    lower observed default rates for transactor populations.

---

## Capital Formula (Art. 153)

The IRB capital formula is unchanged in structure but the 1.06 scaling factor is removed:

```
K = LGD x N[(1-R)^(-0.5) x G(PD) + (R/(1-R))^(0.5) x G(0.999)] - PD x LGD
```

```
RW = K x 12.5 x MA
```

Where:

- `N[.]` = cumulative normal distribution function
- `G(.)` = inverse cumulative normal distribution (PPF)
- `R` = asset correlation (see below)
- `MA` = maturity adjustment factor
- `PD` = probability of default (floored)
- `LGD` = loss given default (supervisory or floored internal)

!!! warning "1.06 Scaling Factor Removed"
    Under CRR, the final RW was multiplied by 1.06 (Art. 153(1)). Basel 3.1 removes this factor
    entirely. The scaling factor column in output will show 1.0 for all Basel 3.1 calculations.

### Asset Correlation (Art. 153(2)–(4))

**Corporate, Sovereign, Institution:**

```
R = 0.12 x f(PD) + 0.24 x (1 - f(PD))
where f(PD) = (1 - exp(-50 x PD)) / (1 - exp(-50))
```

**SME Correlation Adjustment (Art. 153(4)):**

```
SME_adj = 0.04 x (1 - (s - 4.4) / 39.6)
R_SME = R_corporate - SME_adj
```

Where `s = clip(turnover_GBP, 4.4, 44.0)` (millions GBP).

!!! note "GBP-Native Thresholds"
    CRR uses EUR thresholds (5m–50m, denominator 45). Basel 3.1 uses GBP-native thresholds
    (4.4m–44m, denominator 39.6) per PRA PS1/26 Art. 153(4). This eliminates FX conversion
    for UK firms.

**Retail Mortgage / Residential RE:** Fixed R = 0.15

**QRRE:** Fixed R = 0.04

**Retail Other:**

```
R = 0.03 x f(PD) + 0.16 x (1 - f(PD))
where f(PD) = (1 - exp(-35 x PD)) / (1 - exp(-35))
```

### FI Scalar (Art. 153(2))

For large or unregulated financial sector entities, a **1.25× multiplier** is applied to the
asset correlation:

```
R_fse = R x 1.25
```

Triggered by `apply_fi_scalar = True` in the input data. Applies to large FSEs (total assets
≥ **GBP 79 billion** per PS1/26 Glossary p. 78, which corresponds to CRR Art. 142(1)(4) at
EUR 70bn) and all unregulated FSEs (Art. 153(2)). See
[Model Permissions](model-permissions.md) for the distinction between the FI scalar
(correlation multiplier) and Art. 147A approach restrictions (all FSEs → F-IRB only).

### Effective Maturity (Art. 162)

PRA PS1/26 substantially rewrites Art. 162, requiring **all** IRB firms (F-IRB and A-IRB)
to calculate effective maturity — the CRR F-IRB fixed-maturity option is deleted.

#### Key Changes from CRR Art. 162

| Aspect | CRR | Basel 3.1 | Reference |
|--------|-----|-----------|-----------|
| F-IRB fixed maturities (§1) | 0.5yr repo / 2.5yr other | **Deleted** — all IRB firms must calculate M | Art. 162(1) blanked |
| Scope | A-IRB only (Art. 143) | **F-IRB and A-IRB** (Art. 147A) | Art. 162(2) |
| Revolving exposures | Repayment date of current drawing | **Max contractual termination date** | Art. 162(2A)(k) |
| Mixed MNA (derivatives + repos) | Not addressed | **10-day floor** | Art. 162(2A)(da) |
| Purchased receivables minimum M | 90 days | **1 year** | Art. 162(2A)(e) |
| Collateral daily condition (§2A(c)/(d)) | Re-margining **and** revaluation | Re-margining **or** revaluation | Art. 162(2A)(c)/(d) |
| SME maturity simplification (§4) | Available (EUR 500m) | **Deleted** | Art. 162(4) blanked |

!!! warning "F-IRB Fixed Maturities Deleted"
    Under CRR Art. 162(1), F-IRB firms assigned M = 0.5 years for repo-style transactions
    and M = 2.5 years for all other exposures. PRA PS1/26 blanks Art. 162(1) entirely —
    all IRB firms must now calculate M using Art. 162(2A). The 2.5-year fallback in the code
    (`namespace.py:259`) should only apply when `maturity_date` is null, not as a general
    F-IRB default.

#### Art. 162(2A) Calculation Methods

| Method | Applies To | Minimum M |
|--------|-----------|-----------|
| (a) Cash-flow schedule | Known cash flow instruments | 1 year |
| (b) Derivatives under MNA | Weighted average remaining maturity | 1 year |
| (c) Fully collateralised derivatives/margin lending (MNA) | Daily re-margining **or** revaluation, prompt liquidation | **10 days** |
| (d) Repos/SFTs under MNA | Daily re-margining **or** revaluation, prompt liquidation | **5 days** |
| (da) Mixed MNA (derivatives + repos) | Netting agreement covering both (c) and (d) types | **10 days** |
| (e) Purchased corporate receivables | Drawn amounts; with/without effective protections | **1 year** |
| (f) Other instruments | Max remaining time to discharge | 1 year |
| (g) IMM netting sets | Longest-dated > 1 year | Per formula |
| (h) Internal CVA model | Effective credit duration (PRA permission required) | — |
| (ha) Short-maturity netting sets | All contracts original maturity < 1 year | Per (a) |
| (i) BA-CVA / SA-CVA | Netting sets contributing to CVA capital | M may be capped at 1 |
| (k) Revolving exposures | **Max contractual termination date** — not current drawing repayment | 1 year |

**Precedence rules** (Art. 162(2)):

- (g)/(h) take precedence over (b), (c), (d), (da)
- (c) takes precedence over (b)
- (k) takes precedence over (a) — revolving exposures always use facility termination date

#### Art. 162(3) — One-Day Maturity Floor

Retained from CRR with a wider trigger condition (re-margining **or** revaluation, vs CRR's
**and**). Applies to daily-margined repos/derivatives/margin lending and qualifying short-term
exposures (FX settlement, trade finance ≤ 1yr, securities settlement, electronic payments).

See [CRR F-IRB specification](../crr/firb-calculation.md#art-1623--one-day-maturity-floor-exceptions)
for the full qualifying short-term exposure list.

#### Maturity Adjustment Formula

```
b = (0.11852 - 0.05478 x ln(PD))^2
MA = (1 + (M - 2.5) x b) / (1 - 1.5 x b)
```

Where:

- `M` = effective maturity, floored at 1.0 year and capped at **5.0 years**
- Default maturity in code (when `maturity_date` null): 2.5 years
- Retail exposures: MA = 1.0 (no maturity adjustment)

!!! info "Implementation Note — Revolving Maturity"
    The code implements the Art. 162(2A)(k) revolving maturity change via the
    `facility_termination_date` input field (`schemas.py:83`). For Basel 3.1 revolving
    exposures with a non-null termination date, M is calculated from `facility_termination_date`
    instead of `maturity_date` (`namespace.py:248-279`).

---

## Purchased Receivables (Pool Treatment & Dilution Risk)

PS1/26 carries forward the CRR top-down treatment for purchased receivables: a pool of
receivables purchased from a third-party seller is risk-weighted as a single exposure on the
basis of pool-level PD, LGD and dilution-risk parameters, rather than by rating each
individual obligor. Two parallel risk components apply:

1. **Default risk** of the underlying obligors (treated like other corporate or retail IRB
   exposures, but parameterised at pool level when individual PDs are not estimable).
2. **Dilution risk** — the risk that the receivable amount is reduced by credits, returns,
   set-offs, or counter-claims unrelated to obligor default — calculated as a **separate
   exposure** with its own EAD, PD, LGD and 1-year maturity (Art. 157).

The treatment splits along corporate vs retail receivables, with two key linkages back to the
F-IRB framework already specified above: senior / subordinated / dilution LGD values from
Art. 161(1)(e)–(g) (40% / 100% / 100% under PS1/26) and the 0.05% corporate PD floor from
Art. 160(1).

!!! warning "Implementation Status — Pool/Dilution EAD Not Modelled"
    The current input schema treats every IRB row as an obligor-level exposure with a single
    PD and LGD. There is no field for **dilution-risk EAD as a separate component** alongside
    default-risk EAD, no pool-level rollup of obligor PDs, and no flag to route an exposure
    to Art. 161(1)(e)/(f)/(g) (the senior 40% / subordinated 100% / dilution 100%
    purchased-receivables LGD paths). Purchased-receivables pools therefore currently fall
    through to the standard senior unsecured LGD (40% non-FSE / 45% FSE) and the dilution
    component is omitted entirely. See [CRR F-IRB spec — Art. 161(1) LGD Values](../crr/firb-calculation.md#art-1611-lgd-values) for the corresponding LGD-side gap (D3.10) and
    [`schemas.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/data/schemas.py)
    for the input field surface area.

### (a) Pool as a Single Exposure (Top-Down Treatment)

PS1/26 Art. 154(5)–(7) (retail) and the corporate analogues in Art. 160(2) / Art. 161(1)(e)–(f)
treat the pool, not its individual obligors, as the unit of measurement. Eligibility of the
pool is conditional on the operational requirements in Art. 184, summarised below:

| Operational Requirement | PS1/26 Reference |
|-------------------------|------------------|
| Effective ownership and control of cash remittances; bankruptcy-remote structure | Art. 184(2) |
| Monitoring of seller and servicer financial condition; periodic reviews | Art. 184(3)(a)–(b) |
| Pool-level monitoring: over-advances, arrears, dilutions, contra-accounts | Art. 184(3)(c)–(e) |
| Single-obligor concentration limits within and across pools | Art. 184(3)(d) |
| Early-warning systems for seller deterioration; covenant monitoring | Art. 184(4) |
| Written advance-rate, eligible-collateral, documentation and concentration policies | Art. 184(5) |
| Independent internal audit of the receivables purchase programme | Art. 184(6) |

If the institution has **full recourse to the seller** for both default risk and dilution risk,
the exposure is treated as a collateralised exposure to the seller and Articles 151(2),
152 and 158(1)–(4) cease to apply at pool level (Art. 151(2), final sentence).

### (b) Dilution Risk as a Separate Component

Art. 157 establishes that dilution risk is calculated as a **distinct exposure** alongside the
default-risk exposure on the same pool. The two components have independent parameters:

| Parameter | Default-Risk Exposure | Dilution-Risk Exposure |
|-----------|----------------------|------------------------|
| Formula | Art. 153(1) corporate / Art. 154(1) retail | Art. 153(1) (corporate formula) for both pool types |
| PD | Pool PD per Art. 160(2) (corporate) / Art. 163 (retail) | EL for dilution per Art. 160(6) (corporate) / Art. 163(3) (retail) |
| LGD | Art. 161(1)(e)/(f) (corporate) / own estimates (retail) | **100%** — Art. 161(1)(g) (corporate) / Art. 164(1)(b) (retail) |
| EAD | Art. 166A(5) — drawn amount minus dilution own-funds requirement | Drawn pool balance (no separate netting) |
| Maturity (M) | Art. 162(2A)(e) — minimum **1 year** for purchased corporate receivables | Art. 157(4) — **1 year** if dilution can be resolved within a year, otherwise the period over which it can be resolved, capped at **5 years** |

!!! info "EAD Interaction — Art. 166A(5)"
    For the default-risk exposure, the EAD is the drawn pool value **minus** the own-funds
    requirement for dilution risk, computed before credit risk mitigation. This avoids
    double-counting capital across the two components. Undrawn purchase commitments for
    revolving pools attract a **40% CCF** (or **10%** if the commitment qualifies as
    unconditionally cancellable under Art. 111 Table A1 row 7).

!!! note "Materiality Carve-Out — Art. 157(5)"
    Where dilution risk is immaterial for a given type of purchased corporate or retail
    receivable, the institution is **not required** to calculate or recognise risk-weighted
    exposure amounts for the dilution component. PS1/26 removes the CRR requirement for prior
    competent-authority exemption — the firm self-assesses materiality.

### (c) Art. 160(2) / 160(6) — Estimating PD and EL for the Dilution Component

When the institution **cannot** estimate PD for the obligors in the pool (or the estimates do
not meet the Section 6 IRB requirements), Art. 160(2) provides three top-down PD methods for
purchased corporate receivables:

| Method | PD Definition | Pairs With LGD |
|--------|--------------|----------------|
| **Art. 160(2)(a)** — Senior claims | PD = institution's EL estimate ÷ LGD for the receivables | Art. 161(1)(e) — **40%** (senior, non-FSE rate; was 45% under CRR) |
| **Art. 160(2)(b)** — Subordinated claims | PD = institution's EL estimate (LGD is 100%) | Art. 161(1)(f) — **100%** |
| **Art. 160(2)(c)** — A-IRB decomposition | PD = decomposed PD from EL where the firm can split EL into PD and LGD reliably | LGD also from the decomposition (Art. 161(2)(b)(i)) |

For the **dilution-risk component** specifically (Art. 160(6)):

```
PD_dilution = EL_estimate_for_dilution_risk
LGD_dilution = 100% (Art. 161(1)(g)) under Foundation IRB
```

A-IRB firms operating under Art. 147A may, **as an alternative**, decompose the dilution EL
into PD and LGD components reliably and use the decomposed PD with the matching decomposed
LGD (Art. 161(2)(b)(ii)), subject to the same Art. 184 operational requirements. Unfunded
credit protection on the dilution PD is recognised under Credit Risk Mitigation (CRR) Part
Article 191A.

!!! warning "Dilution LGD Increased under PS1/26"
    Art. 161(1)(g) was **75% under CRR** and is **100% under PS1/26**. The PRA's stated
    rationale is that dilution losses (returns, credit notes, set-offs) are not mitigated by
    collateral recovery and should receive the same severity as subordinated unsecured claims.
    See [Art. 161 Purchased Receivables Changes](#supervisory-lgd-art-161) above.

### (d) Art. 154(5)–(7) — Retail Pool Eligibility Conditions

To qualify for the retail risk-weight function (Art. 154(1)) at pool level, the purchased
receivables must satisfy the operational requirements of Art. 184 **plus** the four pool
eligibility conditions in Art. 154(5):

| Condition | Requirement | Reference |
|-----------|-------------|-----------|
| (a) Third-party origination | Pool purchased from unrelated third-party sellers; the institution has no direct or indirect originating exposure to the underlying obligor | Art. 154(5)(a) |
| (b) Arm's-length generation | Receivables generated arm's-length between seller and obligor; **inter-company and contra-account receivables ineligible** | Art. 154(5)(b) |
| (c) Cash-flow claim | Purchasing institution has a claim on all proceeds (or a pro-rata interest) from the purchased receivables | Art. 154(5)(c) |
| (d) Diversification | Pool is sufficiently diversified | Art. 154(5)(d) |

Pools that meet (a)–(d) are routed through the retail F-IRB / A-IRB risk-weight function with
correlation per Art. 154(1) (general retail) and the relevant retail PD floor from Art. 163(1)
(0.10% mortgage / 0.10% QRRE revolver / 0.05% other).

!!! info "First-Loss Protection — Art. 154(6)"
    Refundable purchase price discounts, collateral or partial guarantees that provide
    first-loss protection for default losses, dilution losses, or both, may be treated as
    first-loss protection by the purchaser (or by the beneficiary of the collateral or
    guarantee) under Subsections 2 and 3 of Section 3 of Chapter 5 of Title II of Part Three
    of CRR. The seller providing the discount, or the provider of the collateral or guarantee,
    treats it as an exposure to a first-loss position — i.e. the protection is recognised
    symmetrically on both sides of the transaction.

!!! note "Hybrid Pools — Art. 154(7)"
    Where a purchasing institution **cannot** separate retail-mortgage / QRRE exposures from
    other retail exposures within a hybrid pool, Art. 154(7) requires application of the retail
    risk-weight function producing the **highest** capital requirement for the entire pool.
    This is a conservative carve-out to discourage classification arbitrage on mixed pools.

### Cross-Reference Summary

| Article | Topic | Where Else in This Spec |
|---------|-------|-------------------------|
| Art. 154(5)–(7) | Retail pool eligibility, first-loss protection, hybrid pools | This section only |
| Art. 157 | RWA for dilution risk (separate component, M = 1y default / 5y max) | This section only |
| Art. 158(10) | EL for dilution risk (`EL = PD x LGD`, EL amount = `EL x EAD`) | This section only |
| Art. 160(1) | 0.05% corporate PD floor | [PD Floors](#pd-floors-art-160-163) |
| Art. 160(2) | Top-down PD for purchased corporate receivables | This section only |
| Art. 160(6) | PD = EL for corporate dilution (or A-IRB decomposition) | This section only |
| Art. 161(1)(e)–(g) | LGD 40% / 100% / 100% — senior / sub / dilution corporate | [Supervisory LGD](#supervisory-lgd-art-161) |
| Art. 163(3) | PD = EL for retail dilution | [PD Floors](#pd-floors-art-160-163) |
| Art. 164(1)(b)–(c) | LGD 100% for retail dilution (or decomposed) | A-IRB spec |
| Art. 166A(5) | EAD net of dilution own-funds requirement; 40%/10% CCF on undrawn revolving commitments | This section only |
| Art. 162(2A)(e) | Minimum **1 year** M for purchased corporate receivables (CRR was 90 days) | [Effective Maturity](#effective-maturity-art-162) |
| Art. 184 | Operational requirements for purchased receivables (governance, monitoring, audit) | This section only |

---

## Key Scenarios

| Scenario ID | Description | Key Parameter |
|-------------|-------------|---------------|
| B31-B1 | Corporate senior unsecured, non-FSE — LGD 40% | LGD = 40% (was 45%) |
| B31-B2 | PD floor test: PD input < 0.05% | PD floored to 0.05% |
| B31-B3 | 1.06 scaling removed | Scaling = 1.0 |
| B31-B4 | SME firm-size correlation adjustment (GBP thresholds) | Turnover in £4.4m–44m range |
| B31-B5 | SME corporate with no supporting factor | SF = 1.0 (removed in B31) |
| B31-B6 | Long maturity (5Y cap) | M capped at 5.0 |
| B31-B7 | FSE senior unsecured — LGD 45% retained | LGD = 45% (FSE distinction) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-B: Foundation IRB | B1–B7 | 16 | 100% (16/16) |
