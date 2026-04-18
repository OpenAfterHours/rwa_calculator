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
| CIU (fallback) | **1,250%** | Art. 132(2) |
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
| Standard equity (listed, exchange-traded) | 250% | Art. 133(3) |
| Higher-risk equity | 400% | Art. 133(4) |
| Subordinated debt / non-equity own funds instruments | 150% | Art. 133(5) |
| Legislative equity (carve-out, see below) | 100% | Art. 133(6) |

!!! warning "Correction: PRA vs BCBS Equity Categories"
    - **No "CQS 1-2 speculative" tier in PRA**: The BCBS framework (CRE60.20) includes speculative unlisted equity tiers differentiated by CQS. PRA PS1/26 Art. 133 does **not** include these tiers — all non-legislative, non-subordinated equity is either standard (250%, Art. 133(3)) or higher-risk (400%, Art. 133(4)).
    - **Higher-risk definition**: Under PRA PS1/26 Glossary (p.5), "higher risk equity exposure" means equity that is (1) **not listed on a recognised exchange** AND (2) the underlying **business has existed for less than five years**. PE/VC is only higher-risk if it meets both criteria — there is no automatic PE/VC = 400% rule. The prior definition here (short-term resale / derivative position / PE-VC) was the BCBS CRE60.20 definition, not PRA.
    - **Art. 133(5) is subordinated debt / non-equity own funds**: 150% risk weight for subordinated debt and capital instruments that are not classified as equity exposures.
    - **Art. 133(6) is a carve-out**: Legislative equity at 100% is a carve-out for government-mandated holdings (e.g., holdings required by national development policy legislation). It is not a general 100% weight category.

### Classification Decision Tree

```
Is it subordinated debt / non-equity own funds instruments?
  → Yes: 150% (Art. 133(5))
Is it legislative equity (government-mandated, Art. 133(6) carve-out)?
  → Yes: 100% (Art. 133(6))
Is it listed on a recognised exchange?
  → Yes: 250% (Art. 133(3))
Is it higher risk (unlisted AND business < 5 years)?
  → Yes: 400% (Art. 133(4))
Otherwise (unlisted, business ≥ 5 years, including PE/VC not meeting higher-risk criteria):
  → 250% (Art. 133(3))
```

!!! note "Unlisted Non-Higher-Risk Treatment"
    Unlisted equity where the business has existed for **five years or more** receives
    the standard **250%** weight under Art. 133(3), including PE/VC holdings in
    established businesses. Only unlisted equity in undertakings whose business has
    existed for less than five years qualifies as higher-risk (400%). The BCBS framework
    would differentiate via CQS speculative tiers, but PRA does not use that structure.

## CRR IRB Equity Approaches (Art. 155)

Art. 155(1) gives firms with IRB permission three approaches for equity, to be chosen
consistently and not for regulatory arbitrage:

1. **Simple Risk Weight Approach** (Art. 155(2))
2. **PD/LGD Approach** (Art. 155(3))
3. **Internal Models Approach** (Art. 155(4))

Equity exposures deducted under Part Two or assigned 250% under Art. 48 are excluded from
Art. 155 altogether.

### Simple Risk Weight Approach — Art. 155(2)

| Equity Category | Risk Weight | Reference |
|----------------|-------------|-----------|
| Private equity in sufficiently diversified portfolios | **190%** | Art. 155(2), RW bullet 1 |
| Exchange-traded equity | **290%** | Art. 155(2), RW bullet 2 |
| All other equity exposures | **370%** | Art. 155(2), RW bullet 3 |

Short cash positions and derivatives held in the non-trading book may offset long positions
in the same individual stock provided the hedge is explicit and covers at least one year.
Other short positions are treated as long with the relevant RW applied to their absolute
value.

### PD/LGD Approach — Art. 155(3)

Under the PD/LGD approach, equity risk-weighted exposure amounts are calculated using the
**Art. 153(1) corporate IRB formula** (same `K × 12.5 × 1.06 × EAD × MA` mechanics), with
equity-specific PD floors (Art. 165(1)) and LGD values (Art. 165(2)):

| Equity Category | PD Floor (Art. 165(1)) | LGD (Art. 155(3) / 165(2)) |
|-----------------|------------------------|-----------------------------|
| Exchange-traded, long-term customer relationship | 0.09% | 90% (65% if in sufficiently diversified PE portfolio, Art. 155(3)) |
| Non-exchange-traded, returns from regular/periodic cash flows (not capital gains) | 0.09% | 90% (65% if diversified) |
| Exchange-traded equity (other short positions in Art. 155(2)) | 0.40% | 90% (65% if diversified) |
| All other equity exposures | 1.25% | 90% (65% if diversified) |

**Key rules (Art. 155(3)):**

- `M = 5 years` for all equity under PD/LGD (Art. 165(3)).
- Where the firm does not have sufficient information to use the default definition in
  Art. 178, a **scaling factor of 1.5** is applied to the risk weights.
- The per-exposure capital is capped: `EL × 12.5 + RWEA ≤ EAD × 12.5` — i.e. the PD/LGD
  output cannot require more capital than a 100% loss assumption.
- Unfunded credit protection may be recognised per Chapter 4 but the **guarantor LGD is
  90%** (65% only if the hedged exposure is PE in a sufficiently diversified portfolio).
- EL = PD × LGD (using the Art. 165 PD floor and the relevant 65%/90% LGD); EL is not
  deducted — for equity, EL enters the expected-loss cover test against provisions under
  the general IRB machinery.

### Internal Models Approach — Art. 155(4)

The IMA risk-weighted exposure amount is **12.5 × potential loss** on the institution's
equity exposures, where potential loss is derived from an internal VaR model at the
**99th percentile, one-tailed confidence level** on the difference between quarterly
returns and an appropriate risk-free rate, computed over a long-term sample period.

**Floor (Art. 155(4)):** The portfolio-level RWEA under IMA must **not be lower than the sum of**:

- the RWEA that would be produced under the PD/LGD approach (Art. 155(3)), and
- the corresponding expected-loss amounts × 12.5,

each computed using the Art. 165(1) PD values and Art. 165(2) LGD values.

IMA requires **PRA permission** (embedded in the general Art. 143 IRB permission).
Unfunded credit protection may be recognised on an equity position.

### Art. 165 — Equity Minimum PD Values and LGDs

Art. 165 sets the IRB equity-specific inputs referenced by Art. 155(3) and (4):

| Paragraph | Parameter | Value(s) |
|-----------|-----------|----------|
| 165(1)(a) | PD floor — exchange-traded, long-term customer relationship | **0.09%** |
| 165(1)(b) | PD floor — non-exchange-traded, returns from regular cash flows | **0.09%** |
| 165(1)(c) | PD floor — exchange-traded equity incl. other short positions (155(2)) | **0.40%** |
| 165(1)(d) | PD floor — all other equity incl. other short positions (155(2)) | **1.25%** |
| 165(2) | LGD — private equity in sufficiently diversified portfolios | **65%** |
| 165(2) | LGD — all other equity exposures | **90%** |
| 165(3) | Maturity for all equity exposures | **M = 5 years** |

The 0.09% / 0.40% / 1.25% values in Art. 165(1) are the PD floors used inside Art. 155(3)
(PD/LGD) and as inputs to the Art. 155(4) IMA floor; they do not modify the flat risk
weights of Art. 155(2), which are already calibrated.

### Art. 153(3) — Double-Default Adjustment for Guaranteed Exposures

Art. 153(3) provides a **double-default credit-protection adjustment** for IRB exposures
(including equity under Art. 155(3)) meeting the Articles 202 and 217 requirements on the
guarantor and the protection contract:

```
Risk-weighted exposure amount (double-default) = RW × exposure value × (0.15 + 160 × PD_pp)
```

where `PD_pp` is the PD of the protection provider and `RW` is the risk weight computed
from the obligor's PD but the guarantor's LGD (comparable direct exposure). The maturity
factor `b` uses the lower of the obligor and protection-provider PD.

!!! note "Double-default — practical status"
    The full Art. 153(3) formula is recorded here for completeness; the current calculator
    does not apply the `(0.15 + 160 × PD_pp)` double-default adjustment and instead falls
    back to Art. 236 parameter substitution or Art. 235 risk-weight substitution. Under
    PRA PS1/26 (Basel 3.1), Art. 153(3) is "[Provision left blank]" and the double-default
    treatment is removed entirely.

### IRB Equity Removal Under Basel 3.1

Under Basel 3.1 (PRA PS1/26 Art. 147A), **all three** IRB equity approaches (Simple,
PD/LGD, Internal Models) are removed. All equity exposures must use SA risk weights
(Art. 133). This is a mandatory restriction — firms cannot opt to continue using IRB
equity methods.

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

!!! note "Fixed in v0.1.181"
    The CIU fallback is correctly applied as **1,250%** for both CRR and Basel 3.1,
    matching Art. 132(2). Prior to v0.1.181 the code incorrectly applied Art. 133
    equity weights (150% CRR / 250%–400% Basel 3.1) for `ciu_approach = "fallback"`.

## Equity Transitional Schedule (PRA Rules 4.1–4.10)

PRA PS1/26 provides a transitional phase-in for the increased equity risk weights
from 2027 to 2030. The transitional has two distinct pathways depending on whether
the firm had IRB permission at 31 December 2026.

### SA Transitional (Rules 4.1–4.3) — Firms Without IRB Permission

Rule 4.1 restricts Rules 4.2–4.3 to firms that **did not** have IRB permission under
Art. 143 of CRR on 31 December 2026.

**Standard equity (Rule 4.2 — modifies Art. 133(3)):**

| Period | Risk Weight |
|--------|-------------|
| 2027 | 160% |
| 2028 | 190% |
| 2029 | 220% |
| 2030+ (Steady state) | 250% |

**Higher-risk equity (Rule 4.3 — modifies Art. 133(4)):**

| Period | Risk Weight |
|--------|-------------|
| 2027 | 220% |
| 2028 | 280% |
| 2029 | 340% |
| 2030+ (Steady state) | 400% |

### IRB Transitional (Rules 4.4–4.6) — Firms With IRB Permission

Rule 4.4 scopes Rules 4.5–4.6 to firms that **had** IRB permission on 31 December 2026.
These firms bifurcate their equity portfolio per Rule 4.5:

- **SA equities** (Rule 4.5(1)): Equity exposures on the Standardised Approach
  (Art. 148/150) at 31 Dec 2026 use the same phase-in schedule as Rules 4.2/4.3 above.
- **IRB equities** (Rules 4.5(2) + 4.6): Equity exposures on IRB at 31 Dec 2026 use the
  **higher of**:
    - the risk weight from the firm's legacy IRB methodology (Art. 155, as in force on
      31 Dec 2026), and
    - the transitional SA risk weight from Rules 4.2/4.3.

### CIU Transitional (Rules 4.7–4.8)

During the 3-year transition period (2027–2029), Rules 4.7–4.8 apply to firms with IRB
permission at 31 December 2026. CIU equity underlyings that were subject to the simple
risk weight approach (Art. 155(2)) use the **higher of** the old simple risk weight and
the transitional SA equity weight from Rules 4.2/4.3.

### Opt-Out (Rules 4.9–4.10)

Firms may elect to skip the transitional and apply full Basel 3.1 steady-state weights
(Art. 133: 250%/400%) immediately. This election is **irrevocable** and requires prior PRA
notification. The opt-out covers both direct equity (Rules 4.5–4.6) and CIU underlyings
(Rule 4.8).

!!! note "Transitional Scope"
    The transitional is **time-period-based**, not vintage-based — all equity exposures
    receive the transitional weight applicable to the reporting period, regardless of
    when they were acquired. The schedule does not apply to legislative equity (100%,
    Art. 133(6)) or subordinated debt (150%, Art. 133(5)).

See the [Basel 3.1 Equity Approach Specification](../basel31/equity-approach.md#transitional-phase-in-rules-4110)
for detailed requirements and acceptance test scenarios.

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
| CRR-J9 | CIU fallback SA (Art. 132(2)) | `ciu` | £600,000 | 1,250% | £7,500,000 |

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
| CRR-J17 | CIU no approach set (default fallback) | `None` | — | £100,000 | 1,250% | £1,250,000 |

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
