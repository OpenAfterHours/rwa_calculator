# Advanced IRB Specification

Advanced IRB calculation with internal LGD and CCF estimates.

**Regulatory Reference:** CRR Articles 153-154

**Test Group:** CRR-C

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
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 5% |
| Other physical | 15% |

## FI Scalar

The **1.25x** capital multiplier for large/unregulated financial sector entities applies equally to A-IRB and F-IRB (Art. 153(2)).

## Calculation

The capital requirement formula, correlation functions, maturity adjustment, and RWA computation are identical to F-IRB. See [F-IRB Specification](firb-calculation.md) for full details.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-C | A-IRB with internal LGD |
| CRR-C | A-IRB with internal CCF |
| CRR-C | FI scalar (1.25x) for large financial institution |
| CRR-C | A-IRB vs F-IRB comparison (same exposure, different LGD) |
