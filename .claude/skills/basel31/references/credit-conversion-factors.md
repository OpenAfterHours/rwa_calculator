# Basel 3.1 Credit Conversion Factors

CCF comparison tables with deltas from CRR.

**Regulatory Reference:** PRA PS1/26 Art. 111, 166C, 166D

---

## SA CCFs (Art. 111, Table A1)

| CCF Category | CRR | Basel 3.1 | Description |
|-------------|-----|-----------|-------------|
| Full Risk (FR) | 100% | 100% | Direct credit substitutes, guarantees |
| Medium Risk (MR) | 50% | 50% | NIFs, RUFs, UK resi mortgage commitments |
| Medium-Low Risk (MLR) | 20% | 20% | Trade-related LCs, performance bonds |
| Other commitments | 0% | **40%** | All other commitments not in other categories |
| Low Risk (LR) | 0% | **10%** | Unconditionally cancellable commitments |

Key change: UCC goes from 0% to 10%; "other commitments" unified at 40%.

## F-IRB CCFs (Art. 166C)

| CCF Category | CRR | Basel 3.1 | Notes |
|-------------|-----|-----------|-------|
| Full Risk (FR) | 100% | 100% | Unchanged |
| Medium Risk (MR) | 75% | 75% | Unchanged |
| MLR (trade LCs) | 20% | 20% | Art. 166C exception |
| Low Risk (LR) | 0% | **40%** | Major increase |

Key change: LR goes from 0% to 40% under F-IRB.

## A-IRB CCFs (Art. 166D)

- Own CCF estimates **only permitted for revolving facilities**
- All other off-balance sheet items must use **SA CCFs**
- **EAD floor:** drawn + 50% of off-balance sheet using F-IRB CCF
- **CCF floor:** own estimate must be >= 50% of SA CCF for the same item type

---

> **Full detail:** `docs/specifications/crr/credit-conversion-factors.md`
