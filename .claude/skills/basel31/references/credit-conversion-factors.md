# Basel 3.1 Credit Conversion Factors

CCF comparison tables with deltas from CRR.

**Regulatory Reference:** PRA PS1/26 Art. 111, 166C, 166D

---

## SA CCFs (Art. 111, Table A1)

| CCF Category | CRR SA | Basel 3.1 SA | Description |
|-------------|--------|-------------|-------------|
| Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees |
| Full Risk Commitment (FRC) | 100% | 100% | Certain-drawdown: repos, factoring, forward deposits |
| Medium Risk (MR) | 50% | 50% | NIFs, RUFs, UK resi mortgage commitments |
| Other Commitments (OC) | 50%/20%* | **40%** | All other commitments not in other categories |
| Medium-Low Risk (MLR) | 20% | 20% | Trade-related LCs, performance bonds |
| Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

*\* Under CRR, OC had no separate category. These commitments were classified by maturity: >1yr → MR (50%), ≤1yr → MLR (20%). Basel 3.1 replaces this with a flat 40%.*

Key change: UCC goes from 0% to 10%; "other commitments" unified at 40%.

## F-IRB CCFs (Art. 166C)

| CCF Category | CRR F-IRB | Basel 3.1 F-IRB | Notes |
|-------------|-----------|-----------------|-------|
| Full Risk (FR/FRC) | 100% | 100% | Unchanged |
| Medium Risk (MR) | 75% | **50%** | Down from 75% (Art. 166C = SA) |
| Other Commitments (OC) | 75%* | **40%** | New Table A1 Row 5 category |
| Medium-Low Risk (MLR) | 75%/20%* | **20%** | Down from 75% (Art. 166C = SA) |
| Low Risk (LR) | 0% | **10%** | Up from 0% (Art. 166C = SA) |

*\* Under CRR, OC had no separate F-IRB category (mapped to MR/MLR at 75%). MLR was 75% general with 20% for trade LCs (Art. 166(9)). Basel 3.1 aligns all F-IRB CCFs to SA Table A1 via Art. 166C.*

Key change: F-IRB no longer has distinct CCF schedule; all aligned to SA Table A1.

## A-IRB CCFs (Art. 166D)

- Own CCF estimates **only permitted for revolving facilities**
- All other off-balance sheet items must use **SA CCFs**
- **EAD floor:** drawn + 50% of off-balance sheet using F-IRB CCF
- **CCF floor:** own estimate must be >= 50% of SA CCF for the same item type

---

> **Full detail:** `docs/specifications/crr/credit-conversion-factors.md`
