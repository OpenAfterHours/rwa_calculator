# Equity Approach Specification

Equity exposure treatment under SA and IRB, including CIU look-through and Basel 3.1 transitional schedule.

**Regulatory Reference:** CRR Articles 132-133, 155; PRA PS1/26 Articles 132-133, 147A

**Test Group:** CRR-E (partial)

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.7 | Equity risk weights: SA (Art. 133) and IRB Simple (Art. 155) | P1 | Done |
| FR-1.7a | Basel 3.1 equity SA weights (Art. 133(3)-(6)) | P1 | Done |
| FR-1.7b | CIU treatment (Art. 132/132A/132B) | P2 | Done |
| FR-1.7c | Equity transitional schedule (PRA Rules 4.1-4.3) | P2 | Done |

---

## CRR SA Equity Risk Weights (Art. 133)

Art. 133(2): "Equity exposures shall be assigned a risk weight of **100%**, unless they are
required to be deducted in accordance with Part Two, assigned a 250% risk weight in accordance
with Article 48(4), assigned a 1250% risk weight in accordance with Article 89(3) or treated
as high risk items in accordance with Article 128."

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Central bank / sovereign equity | 0% | Sovereign treatment |
| All other equity (listed, unlisted, PE, etc.) | 100% | Art. 133(2) flat |
| CIU (fallback) | 150% | Art. 132(2) |
| CIU (look-through) | Underlying RW | Art. 132(1) |
| CIU (mandate-based) | Mandate RW | Art. 132A |

!!! warning "Previous Spec Error Corrected"
    This table previously claimed CRR Art. 133 had differentiated weights: unlisted=150%
    (Art. 133(3)) and PE/VC=190% (Art. 133(4)). These paragraph numbers and values were
    fabricated. CRR Art. 133 has only 3 paragraphs and assigns a **flat 100%** to all equity.
    The 150%/190% values are from Art. 155 (IRB Simple Method), not Art. 133.
    PE/VC that qualifies as high-risk is treated under Art. 128 (150%), not Art. 133.

## Basel 3.1 SA Equity Risk Weights (PRA PS1/26 Art. 133)

Significant increase in equity risk weights under Basel 3.1:

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Subordinated debt / non-equity own funds instruments | 150% | Art. 133(1) |
| Standard equity (listed, exchange-traded) | 250% | Art. 133(3) |
| Higher risk equity | 400% | Art. 133(5) |
| Legislative equity (carve-out, see below) | 100% | Art. 133(6) |

!!! warning "Correction: PRA vs BCBS Equity Categories"
    - **No "CQS 1-2 speculative" tier in PRA**: The BCBS framework (CRE60.20) includes speculative unlisted equity tiers differentiated by CQS. PRA PS1/26 Art. 133 does **not** include these tiers — all non-legislative, non-subordinated equity is either listed (250%) or higher-risk (400%).
    - **Higher-risk definition**: Under PRA Art. 133(5), "higher risk" equity means equity in an **unlisted undertaking with a business age of less than 5 years** (or private equity / venture capital). The 5-year threshold refers to the **undertaking's age** (time since incorporation/establishment), not the holding period of the investment.
    - **Art. 133(6) is a carve-out**: Legislative equity at 100% is a carve-out for government-mandated holdings (e.g., holdings required by national development policy legislation). It is not a general 100% weight category.

### Classification Decision Tree

```
Is it subordinated debt / non-equity own funds?
  → Yes: 150%
Is it legislative equity (government-mandated, Art. 133(6) carve-out)?
  → Yes: 100%
Is it listed / exchange-traded?
  → Yes: 250%
Is it higher risk (unlisted AND undertaking business age < 5yr, OR PE/VC)?
  → Yes: 400%
Otherwise (unlisted, undertaking business age >= 5yr, non-PE):
  → 250%
```

!!! note "Unlisted >= 5yr Treatment"
    For unlisted equity in an **undertaking with business age of 5 years or more** that is not PE/VC and not legislative, the PRA treatment defaults to 250% (standard equity rate) rather than 400%. The BCBS framework would assign 150% via the CQS speculative tiers, but PRA does not use that structure.

## CRR IRB Simple Risk Weight Method (Art. 155)

Under CRR, firms with IRB approval may use the IRB Simple method for equity exposures:

| Equity Category | Risk Weight | Reference |
|----------------|-------------|-----------|
| Exchange-traded / listed equity | 290% | Art. 155(2)(a) |
| Private equity (diversified portfolios) | 190% | Art. 155(2)(b) |
| All other equity (unlisted, speculative) | 370% | Art. 155(2)(c) |

### IRB Simple Removal Under Basel 3.1

Under Basel 3.1 (PRA PS1/26 Art. 147A), the IRB equity approaches (Simple, PD/LGD, Internal Models) are **removed**. All equity exposures must use SA risk weights. This is a mandatory restriction — firms cannot opt to continue using IRB equity methods.

## CIU Treatment (Art. 132 / 132A / 132B)

Collective Investment Undertakings (CIUs / funds) have three possible treatments:

### Look-Through Approach (Art. 132A)

Where the firm has sufficient information about the CIU's underlying holdings:

- Each underlying exposure is risk-weighted as if directly held
- The CIU's leverage is applied to gross up the risk weights
- Requires daily knowledge of the fund's composition

### Mandate-Based Approach (Art. 132B)

Where full look-through is not available but the fund's mandate is known:

- The fund is assumed to invest to the **maximum extent permitted** by its mandate in the highest-risk asset class
- Then the next highest-risk class, and so on until the maximum total investment capacity is filled
- This produces a conservative weighted-average risk weight

### Fallback Approach (Art. 132(2))

Where neither look-through nor mandate-based approaches are feasible:

| CIU Type | CRR Risk Weight | Basel 3.1 Risk Weight |
|----------|-----------------|----------------------|
| Standard CIU fallback | 150% | 250% (listed) / 400% (unlisted) |

Under Basel 3.1, the fallback weights align with the equity SA table (Art. 133).

## Equity Transitional Schedule (PRA Rules 4.1-4.3)

PRA PS1/26 provides a transitional phase-in for the increased equity risk weights:

### Standard Equity (Listed) — Rule 4.1

| Period | Risk Weight |
|--------|-------------|
| 2027 (Year 1) | 160% |
| 2028 (Year 2) | 190% |
| 2029 (Year 3) | 220% |
| 2030+ (Steady state) | 250% |

### Higher Risk Equity (Unlisted/PE) — Rule 4.2

| Period | Risk Weight |
|--------|-------------|
| 2027 (Year 1) | 220% |
| 2028 (Year 2) | 280% |
| 2029 (Year 3) | 340% |
| 2030+ (Steady state) | 400% |

### Scope and Conditions (Rule 4.3)

- The transitional is **time-period-based**, not vintage-based — all equity exposures receive the transitional weight applicable to the reporting period, regardless of when they were acquired
- Year 1 = 2027, Year 2 = 2028, Year 3 = 2029, steady state from 2030
- The transitional schedule does not apply to legislative equity (always 100%) or subordinated debt (always 150%)

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| CRR-E | Listed equity SA (CRR) | 100% |
| CRR-E | Unlisted equity SA (CRR) | 150% |
| CRR-E | PE / VC equity SA (CRR) | 190% |
| CRR-E | Listed equity IRB Simple (CRR) | 290% |
| B31-E | Listed equity SA (Basel 3.1) | 250% |
| B31-E | Unlisted/higher-risk equity SA (Basel 3.1) | 400% |
| B31-E | Legislative equity (Basel 3.1) | 100% |
| B31-E | Subordinated debt (Basel 3.1) | 150% |
| B31-E | Listed equity transitional Year 1 | 160% |
| B31-E | CIU look-through | Varies |
| B31-E | CIU fallback (Basel 3.1) | 250%/400% |
