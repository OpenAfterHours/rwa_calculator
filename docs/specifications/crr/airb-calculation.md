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

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured (Senior) | 25% |
| Unsecured (Subordinated) | 50% |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 10% |
| Other physical | 15% |

## FI Scalar

The **1.25x correlation multiplier** for large/unregulated financial sector entities applies equally to A-IRB and F-IRB (Art. 153(2), CRE31.5). The 1.25 factor is applied to the asset correlation coefficient R, which has a non-linear effect on the capital requirement K.

## Calculation

The capital requirement formula, correlation functions, maturity adjustment, and RWA computation are identical to F-IRB. See [F-IRB Specification](firb-calculation.md) for full details.

## Post-Model Adjustments (Basel 3.1)

### Mortgage Risk Weight Floor (Art. 153(5A) / Art. 154(4A))

Basel 3.1 introduces a minimum risk weight floor for UK residential property exposures under IRB:

- **Default floor**: 15% (configurable via `PostModelAdjustmentConfig.mortgage_rw_floor`)
- **Scope**: All IRB exposures secured by UK residential immovable property
- **Formula**: `floor_adjustment = max(0, floor_rw - modelled_rw) × EAD`
- **RWEA**: `RWEA_adjusted = RWEA_modelled + floor_adjustment`
- **Reported**: COREP column 0253 (adjustment for mortgage RW floor)

### General Post-Model Adjustments (Art. 158(6A))

Firms must apply post-model adjustments (PMAs) to compensate for known model deficiencies:

- **PMA on RWEA**: `RWEA_adjusted = RWEA_modelled × (1 + pma_rwa_scalar)`
- **PMA on EL**: `EL_adjusted = EL_modelled × (1 + pma_el_scalar)`
- **Reported**: COREP column 0252 (adjustment for post-model adjustments)

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-C | A-IRB with internal LGD |
| CRR-C | A-IRB with internal CCF |
| CRR-C | FI scalar (1.25x) for large financial institution |
| CRR-C | A-IRB vs F-IRB comparison (same exposure, different LGD) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-C: Advanced IRB | C1–C3 | 7 | 100% (7/7) |
