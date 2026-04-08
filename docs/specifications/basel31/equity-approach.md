# Equity Approach Specification

Basel 3.1 equity treatment: new SA risk weight regime (250%/400%), removal of IRB equity
approaches, transitional phase-in schedule, and CIU treatment.

**Regulatory Reference:** PRA PS1/26 Art. 132–133, Art. 147A(1)(a), Rules 4.1–4.8
**Test Group:** B31-L

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-9.1 | SA equity risk weights by sub-category (Art. 133) | P0 | Done |
| FR-9.2 | IRB equity approaches removed (Art. 147A(1)(a)) | P0 | Done |
| FR-9.3 | Transitional phase-in schedule (Rules 4.1–4.3, 2027–2030) | P0 | Done |
| FR-9.4 | CIU fallback treatment (Art. 132(2)) | P0 | Done |
| FR-9.5 | CIU mandate-based treatment (Art. 132(4)) | P0 | Done |
| FR-9.6 | CIU look-through treatment (Art. 132a) | P0 | Done |
| FR-9.7 | Transitional exclusions (central bank, government-supported, CIU non-fallback) | P0 | Done |
| FR-9.8 | Higher-risk classification (speculative, PE/VC) | P0 | Done |

---

## Overview

Basel 3.1 fundamentally changes equity treatment by:

1. **Removing IRB equity** — Art. 147A(1)(a) prohibits use of IRB approaches for equity
2. **Introducing differentiated SA weights** — replacing CRR's flat 100% (Art. 133(2)) with
   sub-category-specific weights (250%/400%)
3. **Adding a transitional schedule** — phasing in the higher weights over 2027–2030

### Key Changes from CRR

| Feature | CRR | Basel 3.1 | Reference |
|---------|-----|-----------|-----------|
| SA equity (standard) | 100% flat | **250%** | Art. 133(3) |
| SA equity (higher risk) | 100% flat | **400%** | Art. 133(4)–(5) |
| Subordinated debt | 100% | **150%** | Art. 133(1) |
| Central bank equity | 100% | **0%** | Art. 133(6) |
| IRB Simple approach | Available (Art. 155) | **Removed** | Art. 147A(1)(a) |
| IRB PD/LGD approach | Available | **Removed** | Art. 147A(1)(a) |
| CIU fallback | 1,250% (Art. 132(2)) | 1,250% (unchanged) | Art. 132(2) |

---

## SA Equity Risk Weights (Art. 133)

### Risk Weight Table

| Equity Sub-Category | Risk Weight | Reference |
|--------------------|-------------|-----------|
| Central bank | **0%** | Art. 133(6) |
| Government-supported | **100%** | Legislative programme |
| Subordinated debt | **150%** | Art. 133(1) |
| Exchange-traded / listed | **250%** | Art. 133(3) |
| Unlisted | **250%** | Art. 133(3) |
| Other | **250%** | Art. 133(3) |
| Speculative | **400%** | Art. 133(4) |
| Private equity (PE) | **400%** | Art. 133(5) |
| Private equity (diversified) | **400%** | Art. 133(5) |

!!! note "Government-Supported at 100%"
    The `GOVERNMENT_SUPPORTED` category at 100% reflects legislatively-mandated holdings
    (e.g., government-backed investment programmes). This is a PRA-specific treatment with
    no direct Art. 133 paragraph reference.

### Higher-Risk Classification

An equity exposure is classified as **higher risk** (400%) if:

- `is_speculative = True` — speculative unlisted equity (Art. 133(4)), OR
- `equity_type` is `PRIVATE_EQUITY` or `PRIVATE_EQUITY_DIVERSIFIED` — PE/VC holdings (Art. 133(5))

All other equity (not central bank, not government-supported, not subordinated debt) receives
the standard **250%** weight.

---

## IRB Equity Removal (Art. 147A(1)(a))

Under Basel 3.1, **all equity exposures must use the Standardised Approach**. The following
CRR approaches are no longer available:

- **IRB Simple** (Art. 155) — exchange-traded 290%, PE diversified 190%, other 370%
- **IRB PD/LGD** — modelled PD with 90% LGD floor
- **Internal Models** — VaR-based equity capital

The removal is implemented in the equity calculator's approach determination:

```python
# Under Basel 3.1, always returns EquityApproach.SA
if config.is_basel_3_1:
    return EquityApproach.SA
```

Under CRR, the calculator returns `IRB_SIMPLE` if any exposure class has F-IRB or A-IRB permission.

---

## Transitional Phase-In (Rules 4.1–4.3)

The full Basel 3.1 equity weights (250%/400%) are phased in over 4 years:

| Year | Standard RW Floor | Higher-Risk RW Floor | Rule |
|------|-------------------|---------------------|------|
| 2027 | **160%** | **220%** | Rule 4.1(a) |
| 2028 | **190%** | **280%** | Rule 4.1(b) |
| 2029 | **220%** | **340%** | Rule 4.1(c) |
| 2030+ | **250%** | **400%** | Fully phased |

The transitional works as a **floor**:

```
final_rw = max(assigned_rw, transitional_floor_rw)
```

During the transitional period, the floor ensures exposures receive at least the
phase-in weight, even if the calculator would assign a lower weight.

### Transitional Exclusions

The following equity sub-categories are **excluded** from the transitional floor
(their weights apply directly without a phase-in floor):

- **Central bank** (0%) — already below the floor, exclusion is moot
- **Government-supported** (100%) — legislative programme holdings
- **Subordinated debt** (150%) — already has a fixed rate
- **CIU look-through** — weight derives from underlying assets, not Art. 133
- **CIU mandate-based** — weight derives from fund mandate, not Art. 133

### Scope Restriction (Rules 4.2–4.3)

Rules 4.2–4.3 (SA transitional) apply only to firms **without** IRB equity permission at
31 December 2026. Firms with prior IRB equity permission use Rules 4.4–4.6 (IRB transitional)
instead, which may produce different phase-in weights.

---

## CIU Treatment (Art. 132, 132a, 132b)

Collective Investment Undertakings (CIUs) — funds, ETFs, unit trusts — have three treatment
options depending on the firm's knowledge of the fund's holdings:

### 1. Look-Through Approach (Art. 132a)

When the firm can identify the CIU's underlying holdings:

- Each underlying is risk-weighted per its own exposure class and CQS
- A **value-weighted average RW** is computed across all holdings
- **Leverage adjustment** (Art. 132a(3)): when `fund_nav > 0`, RWA is grossed up
  by dividing total value by NAV, capturing the effect of fund leverage

```
ciu_rw = sum(holding_value_i x rw_i) / fund_nav
```

Fallback if look-through data is incomplete: **250%** (B31) / **150%** (CRR).

### 2. Mandate-Based Approach (Art. 132b)

When the firm knows the fund's investment mandate but not individual holdings:

- The fund's mandate defines the maximum risk-weight-applicable class
- `ciu_mandate_rw` is set based on the mandate's highest-risk category
- **Third-party calculation factor** (Art. 132(4)): if the RW is calculated by a third party
  (not the firm), multiply by **1.2×**

Default mandate RW if not specified: **250%** (B31) / **150%** (CRR).

### 3. Fallback Approach (Art. 132(2))

When neither look-through nor mandate-based is available:

| Condition | Risk Weight | Reference |
|-----------|-------------|-----------|
| Regulatory CIU fallback | **1,250%** | Art. 132(2) |

!!! warning "Code Divergence — CIU Fallback"
    The regulatory CIU fallback is **1,250%** under both CRR2 (Regulation 2019/876) and
    PRA PS1/26 (PDF p.62: "shall assign a risk weight of 1,250% ('fall-back approach')").
    The code currently applies 250% (listed) / 400% (unlisted) under Basel 3.1, and 150%
    under CRR. These values correspond to Art. 133 equity weights, not the Art. 132(2) CIU
    fallback. See D3.15 for the code bug.

### CIU Approach Selection

The approach is determined by the `ciu_approach` input column:

| Value | Approach | Transitional Floor |
|-------|----------|-------------------|
| `look_through` | Look-through (Art. 132a) | Excluded |
| `mandate_based` | Mandate-based (Art. 132b) | Excluded |
| `fallback` | Fallback (Art. 132(2)) | Applied |
| null / unset | Defaults to fallback | Applied |

---

## Waterfall Precedence

When classifying equity exposures, the following priority order applies:

1. **CIU** (Art. 132) — if the exposure is a fund holding
2. **Central bank** (Art. 133(6)) — 0%
3. **Equity** (Art. 133) — 250%/400% by sub-category
4. **High-risk** (Art. 128) — 150% (re-introduced in B31, see [SA Risk Weights](sa-risk-weights.md))

Equity exposures take priority over high-risk classification. PE/VC is classified as equity
(Art. 133(5), 400%), not high-risk (Art. 128, 150%).

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-L1 | Exchange-traded equity (standard) | 250% |
| B31-L2 | Private equity (higher risk) | 400% |
| B31-L3 | Speculative unlisted (higher risk) | 400% |
| B31-L4 | Central bank equity | 0% |
| B31-L5 | Government-supported equity | 100% |
| B31-L6 | Subordinated debt | 150% |
| B31-L7 | Unlisted equity (standard) | 250% |
| B31-L8 | CIU look-through (diversified fund) | Weighted average of underlyings |
| B31-L9 | CIU mandate-based | Mandate RW |
| B31-L10 | CIU mandate-based with third-party calc | Mandate RW × 1.2 |
| B31-L11 | CIU fallback (listed) | 250% (code) / 1,250% (regulation) |
| B31-L12 | CIU fallback (unlisted) | 400% (code) / 1,250% (regulation) |
| B31-L13 | 2027 transitional: standard equity | max(250%, 160%) = 250% |
| B31-L14 | 2027 transitional: higher-risk equity | max(400%, 220%) = 400% |
| B31-L15 | 2027 transitional: standard below floor | Floor binds at 160% |
| B31-L16 | Central bank excluded from transitional | 0% (no floor) |
| B31-L17 | Government-supported excluded from transitional | 100% (no floor) |
| B31-L18 | CIU look-through excluded from transitional | Look-through RW (no floor) |
| B31-L19 | PE diversified | 400% |
| B31-L20 | Other equity (catch-all) | 250% |
| B31-L21 | Leveraged fund look-through | RW grossed up by leverage |
| B31-L22 | Listed equity (standard) | 250% |
| B31-L23 | 2028 transitional: standard equity floor | max(assigned, 190%) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-L: Equity Approach | L1–L23 | 49 | 100% (49/49) |
