# Advanced IRB Specification

Advanced IRB calculation with internal LGD and CCF estimates.

**Regulatory Reference:** CRR Articles 153-154

**Test Group:** CRR-C

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.4 | A-IRB capital requirement: own-estimate PD, LGD, EAD with PD floors | P0 | Done |
| FR-1.5 | A-IRB LGD floors per Basel 3.1 (CRE32) | P1 | Done |
| FR-1.8 | Defaulted exposure A-IRB: K=max(0, LGD−BEEL) | P0 | Done |
| FR-1.9 | Differentiated PD floors per Basel 3.1 | P1 | Done |

---

## Overview

A-IRB uses the same capital requirement formula and correlation functions as F-IRB, but the bank provides its own estimates for LGD and (optionally) maturity and CCF, rather than using supervisory values.

## Key Differences from F-IRB

| Parameter | F-IRB | A-IRB (CRR) | A-IRB (Basel 3.1) |
|-----------|-------|-------------|-------------------|
| PD | Bank estimate (floored) | Bank estimate (floored) | Bank estimate (floored) |
| LGD | Supervisory | Bank estimate, **no floor** | Bank estimate, **with floors** |
| CCF | Supervisory | Bank estimate | Bank estimate |
| Maturity | Supervisory (2.5y default) | Bank estimate (clamped 1-5y) | Bank estimate (clamped 1-5y) |

## LGD Floors (Basel 3.1 Only)

Under CRR, A-IRB has **no LGD floors**. Under Basel 3.1, the following floors apply:

### Corporate A-IRB LGD Floors (Art. 161(5))

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured (Senior) | **25%** |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 10% |
| Other physical | 15% |

!!! warning "Correction: No 50% Subordinated Floor for Corporate"
    The 25% floor applies to **all** corporate unsecured exposures (both senior and subordinated) under Art. 161(5). The "50% subordinated" floor does not exist for corporate A-IRB — the 50% floor applies to **retail QRRE unsecured** exposures (see below).

### Retail A-IRB LGD Floors (Art. 164(4))

| Retail Sub-Class | Collateral | LGD Floor | Reference |
|-----------------|-----------|-----------|-----------|
| Residential real estate (RRE) | RRE secured | **5%** | Art. 164(4)(a) |
| QRRE (unsecured) | None | **50%** | Art. 164(4)(b)(i) |
| Other retail (unsecured) | None | **30%** | Art. 164(4)(b)(ii) |
| Any retail (non-RRE collateral) | Other collateral | Blended (see below) | Art. 164(4)(c) |

### Retail "Other Secured" LGD Floor — Art. 164(4)(c)

For retail exposures secured by collateral other than RRE, the LGD floor is a blended value
combining the secured collateral floor (LGDS) and the unsecured floor (LGDU = **30%**), weighted
by the secured and unsecured portions of the exposure — the same structure as the Foundation
Collateral Method in Art. 230.

The LGDS values by collateral type are:

| Collateral Type | LGDS (Secured Floor) |
|----------------|----------------------|
| Financial collateral | 0% |
| Receivables | 10% |
| Immovable property (non-RRE) | 10% |
| Other physical | 15% |

Where no split between secured/unsecured portions is available, the conservative approach is
to apply the relevant collateral-type LGDS directly (or LGDU=30% if unsecured).

**Implementation:** `src/rwa_calc/engine/irb/formulas.py` — `_lgd_floor_blended_expression()` computes the weighted-average floor using the `crm_alloc_*` columns from the Art. 231 sequential waterfall. The formula: `LGD_floor = (E_unsecured / EAD) × LGDU + Σ_i (E_i / EAD) × LGDS_i`. Applies to `retail_other` (LGDU=30%) and `retail_qrre` (LGDU=50%) with collateral present. Falls back to single-type floor when allocation columns are absent.

!!! note "Scope of Corporate vs Institution LGD Floors"
    Art. 161(5) specifies the 25% unsecured LGD floor for "unsecured exposures to **corporates**". Institution exposures are restricted to F-IRB under Art. 147A(1)(c), so A-IRB LGD floors are not applicable to institutions. All financial sector entities are restricted to F-IRB under Art. 147A(1)(e). Art. 161(4) is "[Note: Provision left blank]" in PRA PS1/26 — only Art. 161(5) is active.

!!! note "RRE LGD Floor"
    The PRA PS1/26 retail RRE LGD floor is **5%** per Art. 164(4)(a). This was changed from 10% in the near-final rules to 5% in the final PS1/26 rules. BCBS CRE32.25 also specifies 5%.

!!! note "Implementation Status"
    All four Art. 164(4) retail LGD floors are fully implemented (P1.87 complete). Floor values
    are configured in `src/rwa_calc/contracts/config.py` (`LGDFloorConfig`, `basel_3_1()` factory).
    The Art. 164(4)(c) blended formula uses `crm_alloc_*` columns from the Art. 231 waterfall
    to compute the weighted secured/unsecured floor. 27 dedicated tests in
    `tests/unit/test_lgd_floor_blended.py`.

## FI Scalar

The **1.25x correlation multiplier** for large/unregulated financial sector entities applies equally to A-IRB and F-IRB (Art. 153(2), CRE31.5). "Large FSE" is defined as total assets ≥ EUR 70bn (CRR Art. 4(1)(146)). The 1.25 factor is applied to the asset correlation coefficient R, which has a non-linear effect on the capital requirement K.

!!! note "Distinct from Art. 147A approach restrictions"
    The correlation multiplier (EUR 70bn total assets, Art. 153(2)) is not the same as the Art. 147A(1)(d) large corporate threshold (GBP 440m revenue), which restricts A-IRB eligibility but does not affect the correlation formula. See [F-IRB Specification](firb-calculation.md#fi-scalar-crr-art-1532) for full details.

## Calculation

The capital requirement formula, correlation functions, maturity adjustment, and RWA computation are identical to F-IRB. See [F-IRB Specification](firb-calculation.md) for full details.

## Post-Model Adjustments (Basel 3.1)

### Mortgage Risk Weight Floor (Art. 154(4A)(b))

Basel 3.1 introduces a minimum risk weight floor for UK residential property exposures under IRB:

- **Regulatory floor**: **10%** per Art. 154(4A)(b) for non-defaulted IRB residential mortgage exposures
- **Scope**: All non-defaulted IRB exposures secured by residential immovable property
- **Formula**: `floor_adjustment = max(0, floor_rw - modelled_rw) × EAD`
- **RWEA**: `RWEA_adjusted = RWEA_modelled + floor_adjustment`
- **Reported**: COREP column 0253 (adjustment for mortgage RW floor)
- **Configurable**: Via `PostModelAdjustmentConfig.mortgage_rw_floor` (default should be 10%)

!!! warning "Correction"
    The regulatory floor is **10%**, not 15%. Art. 154(4A)(b) specifies the 10% minimum risk weight for residential property exposures under A-IRB. The previous 15% was an early implementation assumption.

### General Post-Model Adjustments (Art. 146(3) / Art. 158(6A))

Art. 146(3) establishes the root obligation: firms using IRB must apply post-model adjustments to compensate for known model deficiencies. Art. 158(6A) specifies the EL monotonicity constraint. Firms must apply PMAs to both RWEA and EL:

- **PMA on RWEA**: `RWEA_adjusted = RWEA_modelled × (1 + pma_rwa_scalar)`
- **PMA on EL**: `EL_adjusted = EL_modelled × (1 + pma_el_scalar)`
- **Reported**: COREP column 0252 (adjustment for post-model adjustments)

### Adjustment Sequencing (Art. 153(5A) / Art. 154(4A))

Art. 154(4A) prescribes the following sequential order for RWEA adjustments:

1. **Mortgage RW floor** — Art. 154(4A)(b): applied first to establish the post-floor RWEA base
2. **General PMA scalars and unrecognised-exposure adjustments** — Art. 154(4A)(a): applied to the post-floor RWEA from step 1

!!! warning "Sequencing is mandatory"
    The mortgage floor (step 1) must be computed before general PMAs (step 2) are applied. PMAs scale the already-floored RWEA, not the raw modelled RWEA.

!!! note "EL monotonicity — Art. 158(6A)"
    PMA adjustments to Expected Loss can only **increase** EL, never decrease it. The PMA EL scalar must satisfy `pma_el_scalar ≥ 0`. An adjustment that would reduce EL below the pre-PMA model output is not permitted.

!!! note "Implementation Status"
    Sequential ordering (mortgage floor before PMA scalars) and EL monotonicity are both **implemented**.

### Double Default Removal (Basel 3.1)

CRR Art. 153(3) provided a double-default treatment for guaranteed exposures. Under PRA PS1/26, Art. 153(3) is **"[Note: Provision left blank]"** — the double-default treatment has been removed. Any exposures that previously benefited from double-default must fall back to standard parameter substitution (Art. 236) or risk weight substitution (Art. 235).

## A-IRB CCF Restrictions (Basel 3.1)

Under Basel 3.1, own CCF estimates are **only permitted for revolving facilities** (Art. 166D). All non-revolving off-balance sheet items must use SA CCFs from Table A1. See [CCF Specification](credit-conversion-factors.md) for full details including the 50% floor on A-IRB CCF estimates.

## Key Scenarios

| Scenario ID | Description | Key Parameters |
|-------------|-------------|----------------|
| CRR-C1 | Corporate A-IRB with own LGD estimate | PD modelled, LGD=35% (own estimate), M=2.5y |
| CRR-C2 | Retail A-IRB with own PD and LGD estimates | PD=0.30%, LGD=15% (own estimate) |
| CRR-C3 | Specialised lending A-IRB — project finance | SL routed to A-IRB (with permission) instead of slotting |

Additional spec scenarios validated through the above and B31-C group:

- **Internal CCF**: Own-estimate CCF used for revolving facilities (validated within C1/C2 pipeline)
- **FI scalar (1.25x)**: Correlation uplift for large/unregulated FSEs (validated through B31-B7 and pipeline tests)
- **A-IRB vs F-IRB comparison**: Same exposure with supervisory vs own LGD (validated through comparison test group M3.1)

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-C: Advanced IRB | C1–C3 | 7 | 100% (7/7) |
