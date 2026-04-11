# Equity Approach Specification

Basel 3.1 equity treatment: new SA risk weight regime (250%/400%), removal of IRB equity
approaches, transitional phase-in schedule, and CIU treatment.

**Regulatory Reference:** PRA PS1/26 Art. 132–133, Art. 147A(1)(a), Rules 4.1–4.10
**Test Group:** B31-L

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-9.1 | SA equity risk weights by sub-category (Art. 133) | P0 | Done |
| FR-9.2 | IRB equity approaches removed (Art. 147A(1)(a)) | P0 | Done |
| FR-9.3 | Transitional phase-in schedule (Rules 4.1–4.10, 2027–2030) | P0 | Done |
| FR-9.4 | CIU fallback treatment (Art. 132(2)) | P0 | Done |
| FR-9.5 | CIU mandate-based treatment (Art. 132(4)) | P0 | Done |
| FR-9.6 | CIU look-through treatment (Art. 132a) | P0 | Done |
| FR-9.7 | Transitional exclusions (central bank, subordinated debt, CIU non-fallback) | P0 | Done |
| FR-9.8 | Higher-risk classification (unlisted + business < 5 years) | P0 | Done |

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
| SA equity (higher risk) | 100% flat | **400%** | Art. 133(4) |
| Subordinated debt / non-equity own funds | 100% | **150%** | Art. 133(5) |
| Government-supported equity | 100% | **250%** (standard) | Art. 133(3) |
| IRB Simple approach | Available (Art. 155) | **Removed** | Art. 147A(1)(a) |
| IRB PD/LGD approach | Available | **Removed** | Art. 147A(1)(a) |
| CIU fallback | 1,250% (Art. 132(2)) | **1,250%** (unchanged) | Art. 132(2) |

---

## SA Equity Risk Weights (Art. 133)

### Risk Weight Table

| Equity Sub-Category | Risk Weight | Reference |
|--------------------|-------------|-----------|
| Subordinated debt / non-equity own funds | **150%** | Art. 133(5) |
| Standard equity (listed, exchange-traded, government-supported) | **250%** | Art. 133(3) |
| Unlisted equity (non-higher-risk) | **250%** | Art. 133(3) |
| Other equity | **250%** | Art. 133(3) |
| Higher-risk equity (unlisted + business < 5 years — see [definition below](#higher-risk-classification-art-1334)) | **400%** | Art. 133(4) |

!!! warning "Correction: Art. 133(6) is NOT a 100% Risk Weight (Fixed v0.1.189)"
    Art. 133(6) is an **exclusion clause** that scopes out exposures already handled
    elsewhere: (a) own funds deductions per Chapter 3, (b) 1,250% per Art. 89(3),
    (c) 250% per Art. 48(4). It does **not** assign a 100% risk weight.
    CRR Art. 133(3)(c) had a 100% legislative equity carve-out, but B31 Art. 133
    removes it. Government-supported equity is standard 250% equity under B31.

### Higher-Risk Classification (Art. 133(4))

An equity exposure is classified as **higher risk** (400%) if **both** of the following
conditions are met (PRA PS1/26 Glossary, p.5):

1. **Not listed on a recognised exchange**, AND
2. The underlying **business has existed for less than five years**

The five-year clock starts from the date the business was first established within the
undertaking. Where the business was transferred from another entity, the start date depends
on whether the risk profile substantially changed on transfer (Glossary p.5, conditions
(a)–(b)).

!!! warning "Correction: Higher-Risk Definition (Fixed D1.38)"
    This section previously defined higher-risk equity as "unlisted AND (short-term resale
    OR derivative position), OR PE/VC". That was the **BCBS CRE60.20** definition, not PRA.
    PRA PS1/26 Glossary (p.5) defines higher-risk equity solely by two criteria: unlisted
    + business < 5 years. There is no short-term resale, derivative position, or automatic
    PE/VC criterion. PE/VC is only higher-risk if it meets both conditions.

!!! warning "No CQS Speculative Tiers in PRA"
    The BCBS framework (CRE60.20) includes speculative unlisted equity tiers differentiated
    by CQS. PRA PS1/26 Art. 133 does **not** use CQS-based speculative tiers for equity.
    All non-subordinated equity is either standard (250%, Art. 133(3))
    or higher-risk (400%, Art. 133(4)). The calculator's `is_speculative` flag maps to
    the Art. 133(4) higher-risk definition, not a BCBS CQS tier.

!!! warning "Code Divergence: PE/VC Always Mapped to 400%"
    The equity calculator (`calculator.py:570–574`) assigns 400% to **all** `private_equity`
    and `private_equity_diversified` equity types regardless of business age. Under the PRA
    definition, only PE/VC where the business has existed for less than five years qualifies
    as higher-risk. Long-established PE holdings should receive standard 250%. See D3.37.

All other equity (not subordinated debt, not higher-risk) receives the standard **250%**
weight under Art. 133(3), including listed equity, government-supported equity, and
unlisted PE/VC where the business has existed for five years or more.

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

## Transitional Phase-In (Rules 4.1–4.10)

The full Basel 3.1 equity weights (250%/400%) are phased in over 4 years (2027–2030).
The transitional has distinct pathways depending on whether the firm had IRB equity
permission at 31 December 2026.

### Phase-In Schedule (Rules 4.2–4.3)

| Year | Standard RW Floor (Rule 4.2) | Higher-Risk RW Floor (Rule 4.3) |
|------|------------------------------|--------------------------------|
| 2027 | **160%** | **220%** |
| 2028 | **190%** | **280%** |
| 2029 | **220%** | **340%** |
| 2030+ | **250%** | **400%** |

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
- **Subordinated debt / non-equity own funds** (150%) — fixed rate (Art. 133(5))
- **CIU look-through** — weight derives from underlying assets, not Art. 133
- **CIU mandate-based** — weight derives from fund mandate, not Art. 133

### SA Transitional (Rules 4.1–4.3) — Firms Without IRB Permission

Rule 4.1 restricts Rules 4.2–4.3 to firms that **did not** have permission to use the
IRB Approach (Art. 143 of CRR) on 31 December 2026. These firms apply the phase-in
schedule above directly to all equity exposures.

### IRB Transitional (Rules 4.4–4.6) — Firms With IRB Permission

Rule 4.4 scopes Rules 4.5–4.6 to firms that **had** IRB permission on 31 December 2026.
These firms bifurcate their equity portfolio per Rule 4.5:

1. **SA equities** (Rule 4.5(1)): Equity exposures that were on the Standardised Approach
   (Art. 148 or Art. 150 of CRR) at 31 Dec 2026 use the same phase-in schedule as
   Rules 4.2/4.3 above.
2. **IRB equities** (Rules 4.5(2) + 4.6): Equity exposures that were on the IRB Approach
   (Art. 143 of CRR) at 31 Dec 2026 use the **higher of**:
     - the risk weight from the firm's legacy IRB methodology (Art. 155 of CRR, as in
       force on 31 Dec 2026), and
     - the transitional SA risk weight from Rules 4.2 or 4.3.

This "higher of" test provides a floor-based transition — IRB firms cannot produce risk
weights below the transitional SA schedule, but retain their legacy IRB weights where
those are higher.

### CIU Transitional (Rules 4.7–4.8)

During the 3-year transition period (2027–2029), Rules 4.7–4.8 apply to firms with IRB
permission at 31 December 2026. For CIU equity underlyings that were subject to the
simple risk weight approach (Art. 155(2) of CRR, as in force before 1 Jan 2027), the
firm assigns the **higher of**:

- the old simple risk weight (CRR Art. 155(2)), and
- the transitional SA equity weight from Rules 4.2/4.3.

This applies when using look-through (Art. 132A(1) / Art. 152(4)) or mandate-based
(Art. 132A(2) / Art. 152(5)) approaches.

### Opt-Out (Rules 4.9–4.10)

Instead of Rules 4.5–4.6 and 4.8, a firm may elect to apply:

- full steady-state Art. 133 weights immediately (250%/400%) for direct equity, and
- standard CIU treatment (Art. 132A / Art. 152) without the simple risk weight floor.

This election is **irrevocable** and requires prior PRA notification (Rule 4.10).
The opt-out covers both direct equity and CIU underlyings — a firm cannot opt out of
one while retaining the other.

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

!!! note "Fixed in v0.1.181"
    The CIU fallback is correctly applied as **1,250%** under both CRR and Basel 3.1,
    matching PRA PS1/26 Art. 132(2): "shall assign a risk weight of 1,250%
    ('fall-back approach')". Prior to v0.1.181 the code incorrectly applied Art. 133
    equity weights (250%/400%) instead.

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
2. **Central bank / sovereign equity** — 0% (sovereign treatment, not Art. 133)
3. **Equity** (Art. 133) — 250%/400% by sub-category, including subordinated debt (150%,
   Art. 133(5)). Art. 133(6) is an exclusion clause, not a risk weight.
4. **High-risk** (Art. 128) — 150% (re-introduced in B31, see [SA Risk Weights](sa-risk-weights.md))

Equity exposures take priority over high-risk classification. PE/VC that meets the
higher-risk definition (unlisted + business < 5 years) is classified as equity
(Art. 133(4), 400%), not high-risk (Art. 128, 150%). PE/VC that does not meet the
higher-risk definition receives standard 250% (Art. 133(3)).

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-L1 | Exchange-traded equity (standard) | 250% |
| B31-L2 | Private equity (higher risk — business < 5yr) | 400% |
| B31-L3 | Speculative unlisted (higher risk) | 400% |
| B31-L4 | Central bank equity | 0% |
| B31-L5 | Government-supported equity | 250% |
| B31-L6 | Subordinated debt | 150% |
| B31-L7 | Unlisted equity (standard) | 250% |
| B31-L8 | CIU look-through (diversified fund) | Weighted average of underlyings |
| B31-L9 | CIU mandate-based | Mandate RW |
| B31-L10 | CIU mandate-based with third-party calc | Mandate RW × 1.2 |
| B31-L11 | CIU fallback (listed) | 1,250% |
| B31-L12 | CIU fallback (unlisted) | 1,250% |
| B31-L13 | 2027 transitional: standard equity | max(250%, 160%) = 250% |
| B31-L14 | 2027 transitional: higher-risk equity | max(400%, 220%) = 400% |
| B31-L15 | 2027 transitional: standard below floor | Floor binds at 160% |
| B31-L16 | Central bank excluded from transitional | 0% (no floor) |
| B31-L17 | Government-supported subject to transitional | 250% (exceeds all floors) |
| B31-L18 | CIU look-through excluded from transitional | Look-through RW (no floor) |
| B31-L19 | PE diversified (higher risk — business < 5yr) | 400% |
| B31-L20 | Other equity (catch-all) | 250% |
| B31-L21 | Leveraged fund look-through | RW grossed up by leverage |
| B31-L22 | Listed equity (standard) | 250% |
| B31-L23 | 2028 transitional: standard equity floor | max(assigned, 190%) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-L: Equity Approach | L1–L23 | 49 | 100% (49/49) |
