# Equity Approach Specification

Equity exposure treatment under SA and IRB, including CIU look-through and Basel 3.1 transitional schedule.

**Regulatory Reference:** CRR Articles 132-133, 155; PRA PS1/26 Articles 132-133, 147A

**Test Group:** CRR-J

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
| CIU (fallback) | 1,250% | Art. 132(2) |
| CIU (look-through) | Underlying RW | Art. 132(1) |
| CIU (mandate-based) | Mandate RW | Art. 132A |

!!! warning "Previous Spec Error Corrected"
    This table previously claimed CRR Art. 133 had differentiated weights: unlisted=150%
    (Art. 133(3)) and PE/VC=190% (Art. 133(4)). These paragraph numbers and values were
    fabricated. CRR Art. 133 has only 3 paragraphs and assigns a **flat 100%** to all equity.
    The 150%/190% values are from Art. 155 (IRB Simple Method), not Art. 133.
    Under the Art. 112 Table A2 waterfall, equity (priority 3) takes precedence over
    high-risk items (priority 4). PE/VC is classified as equity under Art. 133, not
    as a high-risk item under Art. 128. Note: Art. 128 was omitted from UK CRR by
    SI 2021/1078 (effective 1 Jan 2022) and is only active under Basel 3.1 (from 2027).

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
| Standard CIU fallback | 1,250% | 1,250% |

The 1,250% fallback originates from CRR2 (Regulation 2019/876) and is carried forward
unchanged in PRA PS1/26 Art. 132(2). This is a punitive weight designed to incentivise
firms to use look-through or mandate-based approaches.

!!! info "Art. 132B(2) Exclusion — Not the Same as Fallback"
    CIU equity exposures **excluded** from CIU treatment under Art. 132B(2) (e.g.,
    0% sovereign entities, legislative programme holdings) receive standard **Art. 133
    equity treatment** instead: 100% (CRR) / 250% listed or 400% unlisted (Basel 3.1).
    These are NOT the Art. 132(2) "fallback" — they are reclassified equity exposures.

!!! warning "Implementation Divergence"
    The calculator currently applies 150% (CRR) / 250% listed or 400% unlisted
    (Basel 3.1) for `ciu_approach = "fallback"`. These values correspond to
    Art. 133 equity weights, not the true Art. 132(2) fallback of 1,250%. The
    code constants are in `crr_equity_rw.py` (`CIU: 1.50`) and `b31_equity_rw.py`
    (`CIU: 2.50`). This should be corrected to 12.50 (1,250%) for both frameworks.

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

### CRR SA Equity (Art. 133) — CRR-J1 to CRR-J9

| Scenario ID | Description | Equity Type | EAD | Expected RW | Expected RWA |
|-------------|-------------|-------------|-----|-------------|--------------|
| CRR-J1 | Listed equity SA | `listed` | £500,000 | 100% | £500,000 |
| CRR-J2 | Unlisted equity SA | `unlisted` | £300,000 | 100% | £300,000 |
| CRR-J3 | Exchange-traded equity SA | `exchange_traded` | £200,000 | 100% | £200,000 |
| CRR-J4 | Private equity SA | `private_equity` | £100,000 | 100% | £100,000 |
| CRR-J5 | Government-supported equity SA | `government_supported` | £400,000 | 100% | £400,000 |
| CRR-J6 | Speculative equity SA | `speculative` | £150,000 | 100% | £150,000 |
| CRR-J7 | Central bank equity SA (sovereign treatment) | `central_bank` | £1,000,000 | 0% | £0 |
| CRR-J8 | Subordinated debt SA | `subordinated_debt` | £250,000 | 100% | £250,000 |
| CRR-J9 | CIU fallback SA (Art. 132(2)) | `ciu` | £600,000 | 150% | £900,000 |

!!! warning "CRR-J9 Implementation Divergence"
    The CIU fallback should be **1,250%** per Art. 132(2), but the calculator applies 150% (the Art. 133
    equity weight). See D3.15 for the code bug. The test expects the current code behaviour (150%),
    not the regulatory value (1,250%).

### CRR IRB Simple Equity (Art. 155) — CRR-J10 to CRR-J14

| Scenario ID | Description | Equity Type | Key Flags | EAD | Expected RW | Expected RWA |
|-------------|-------------|-------------|-----------|-----|-------------|--------------|
| CRR-J10 | Exchange-traded equity IRB Simple | `exchange_traded` | `is_exchange_traded=True` | £200,000 | 290% | £580,000 |
| CRR-J11 | Diversified PE equity IRB Simple | `private_equity` | `is_diversified=True` | £100,000 | 190% | £190,000 |
| CRR-J12 | Other (unlisted) equity IRB Simple | `unlisted` | — | £100,000 | 370% | £370,000 |
| CRR-J13 | Central bank equity IRB Simple (sovereign treatment) | `central_bank` | — | £500,000 | 0% | £0 |
| CRR-J14 | Government-supported equity IRB Simple | `government_supported` | `is_government_supported=True` | £300,000 | 190% | £570,000 |

!!! note "CRR-J14 Government-Supported Mapping"
    The calculator maps `government_supported` to Art. 155(2)(b) (diversified PE) at 190%.
    Art. 155 has no "government-supported" category — only exchange-traded (a), PE diversified (b),
    and all other (c). See D3.4 for the code mapping issue.

### CIU Specific Tests — CRR-J15 to CRR-J17

| Scenario ID | Description | CIU Approach | Key Parameters | EAD | Expected RW | Expected RWA |
|-------------|-------------|--------------|----------------|-----|-------------|--------------|
| CRR-J15 | CIU mandate-based SA (Art. 132A) | `mandate_based` | `ciu_mandate_rw=0.80` | £200,000 | 80% | £160,000 |
| CRR-J16 | CIU mandate-based + third-party 1.2× multiplier | `mandate_based` | `ciu_mandate_rw=0.80`, `ciu_third_party_calc=True` | £200,000 | 96% | £192,000 |
| CRR-J17 | CIU no approach set (default fallback) | `None` | — | £100,000 | 150% | £150,000 |

CRR-J16 calculation: the 1.2× third-party multiplier (Art. 132(4)) scales the mandate risk weight:
`RW = 0.80 × 1.2 = 0.96 (96%)`.

### RWA Arithmetic Verification — CRR-J18 to CRR-J20

| Scenario ID | Description | Approach | EAD | Expected RW | Expected RWA |
|-------------|-------------|----------|-----|-------------|--------------|
| CRR-J18 | SA RWA arithmetic verification | SA | £1,234,567 | 100% | £1,234,567 |
| CRR-J19 | IRB Simple RWA arithmetic verification | IRB Simple | £750,000 | 370% | £2,775,000 |
| CRR-J20 | Zero EAD produces zero RWA | IRB Simple | £0 | 370% | £0 |

### Basel 3.1 Equity Scenarios

Basel 3.1 equity scenarios are documented in the dedicated [Basel 3.1 Equity Approach](../basel31/equity-approach.md) specification (test group B31-L).

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-J: Equity | J1–J20 | 32 | 100% |
