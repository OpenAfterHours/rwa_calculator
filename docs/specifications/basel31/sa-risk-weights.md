# SA Risk Weights Specification

Basel 3.1 Standardised Approach risk weight changes: ECRA/SCRA for institutions,
corporate sub-categories, real estate loan-splitting, SA specialised lending,
currency mismatch multiplier, and SME corporate class.

**Regulatory Reference:** PRA PS1/26 Art. 112–134, CRE20
**Test Group:** B31-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | Sovereign risk weights (unchanged from CRR, flat 100% unrated) | P0 | Done |
| FR-1.2 | Institution ECRA risk weights (Art. 120, Table 3) | P0 | Done |
| FR-1.3 | Institution SCRA risk weights (Art. 121, grades A–C) | P0 | Done |
| FR-1.4 | Corporate CQS-based risk weights with PRA CQS 5 = 150% | P0 | Done |
| FR-1.5 | Corporate sub-categories: IG 65%, non-IG unrated 135%, SME 85% | P0 | Done |
| FR-1.6 | Retail 75%, salary/pension 35% (Art. 123(4), carried from CRR2) | P0 | Done |
| FR-1.7 | Residential RE loan-splitting (Art. 124F–124G) | P0 | Done |
| FR-1.8 | Commercial RE loan-splitting and income-producing (Art. 124H–124I) | P0 | Done |
| FR-1.9 | SA Specialised Lending (Art. 122A–122B) | P0 | Done |
| FR-1.10 | Currency mismatch multiplier 1.5× (Art. 123B) | P0 | Done |
| FR-1.11 | Defaulted provision-coverage split (Art. 127) | P0 | Done |
| FR-1.12 | Real estate qualifying criteria routing (Art. 124A, 124J) | P0 | Done |
| FR-1.13 | ADC exposures 150% / qualifying residential 100% (Art. 124K) | P0 | Done |
| FR-1.14 | Covered bond rated risk weights (Art. 129(4), Table 7) — PRA values = CRR values | P0 | Done (spec correct; code bug P1.113) |
| FR-1.15 | Covered bond unrated derivation (Art. 129(5)) — expanded 7-entry table for SCRA | P0 | Done |
| FR-1.16 | Non-UK unrated PSE/RGLA: sovereign CQS-derived weights, not flat 100% | P1 | Code bug P1.112 |

---

## Sovereign Risk Weights (Art. 114)

Largely unchanged from CRR. The key Basel 3.1 clarification is the treatment of unrated sovereigns.

**Table 1 — Sovereign Risk Weights (Art. 114)**

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 0% |
| CQS 2 | 20% |
| CQS 3 | 50% |
| CQS 4 | 100% |
| CQS 5 | 100% |
| CQS 6 | 150% |
| Unrated | 100% |

!!! note "No OECD Bifurcation"
    PRA PS1/26 Art. 114(1) assigns a flat **100%** to unrated sovereigns. There is no OECD
    bifurcation (0% OECD / 100% non-OECD) — that was a Basel I/II legacy not carried forward
    into CRR or Basel 3.1. Domestic currency exemption (Art. 114(4)) is a separate provision
    allowing 0% for GBP-denominated UK government exposures.

---

## PSE and RGLA Risk Weights (Art. 115–116)

PSE (Public Sector Entities) and RGLA (Regional Governments and Local Authorities)
risk weights are largely unchanged from CRR. The key Basel 3.1 clarification concerns
non-UK unrated exposures.

!!! warning "Non-UK Unrated PSE/RGLA — Sovereign-Derived, Not Flat 100%"
    Unrated non-UK PSE and RGLA exposures should use **sovereign CQS-derived weights**
    (Art. 115(1)(a) Table 1A for RGLA, Art. 116(1) Table 2 for PSE), not a flat 100%.
    The sovereign CQS maps to the following risk weights:

    **RGLA sovereign-derived (Art. 115(1)(a), Table 1A):**

    | Sovereign CQS | RGLA Risk Weight |
    |---------------|-----------------|
    | CQS 1 | 20% |
    | CQS 2 | 50% |
    | CQS 3 | 100% |
    | CQS 4 | 100% |
    | CQS 5 | 100% |
    | CQS 6 | 150% |
    | Unrated sovereign | 100% |

    **PSE sovereign-derived (Art. 116(1), Table 2):**

    | Sovereign CQS | PSE Risk Weight |
    |---------------|----------------|
    | CQS 1 | 20% |
    | CQS 2 | 50% |
    | CQS 3 | 100% |
    | CQS 4 | 100% |
    | CQS 5 | 100% |
    | CQS 6 | 150% |
    | Unrated sovereign | 100% |

    UK PSEs and RGLAs are entitled to preferential treatment per Art. 115(5) /
    Art. 116(3) (20% for sterling-denominated short-term). See the CRR spec for
    full table details: [CRR SA Risk Weights — RGLA/PSE](../crr/sa-risk-weights.md).

!!! warning "Code Issue — P1.112"
    The calculator currently defaults non-UK unrated PSE/RGLA to a flat **100%**
    instead of performing the sovereign CQS lookup. This overstates capital for
    non-UK PSE/RGLA backed by well-rated (CQS 1–2) sovereigns (e.g., Germany: 20%
    vs incorrectly assigned 100%). See P1.112 in IMPLEMENTATION_PLAN.md.

---

## Institution Risk Weights — ECRA (Art. 120)

The External Credit Risk Assessment (ECRA) approach uses the institution's own ECAI rating.

**Table 3 — Institution ECRA Risk Weights (Art. 120(1))**

| CQS | Risk Weight | Change from CRR |
|-----|-------------|-----------------|
| CQS 1 | 20% | Unchanged |
| CQS 2 | **30%** | CRR = 50% |
| CQS 3 | 50% | Unchanged |
| CQS 4 | 100% | Unchanged |
| CQS 5 | 100% | Unchanged |
| CQS 6 | 150% | Unchanged |

!!! warning "CQS 2 Change from CRR"
    The CRR CQS 2 rate for institutions is **50%** (Art. 120 Table 3, confirmed from UK onshored
    CRR PDF p.119). Basel 3.1 reduces this to **30%** (PRA PS1/26 Art. 120 Table 3, p.40).
    This 20pp reduction for well-rated (A-range) institutions is a deliberate Basel 3.1 change,
    not a pre-existing UK CRR deviation. See D3.17 for the code bug where CRR uses 30%.

### ECRA Short-Term (Art. 120(2), Table 4)

For exposures with an original maturity ≤ 3 months:

| CQS | Short-Term RW |
|-----|--------------|
| CQS 1 | 20% |
| CQS 2 | 20% |
| CQS 3 | 20% |
| CQS 4 | 50% |
| CQS 5 | 50% |
| CQS 6 | 150% |

### ECRA Short-Term ECAI (Art. 120(2B), Table 4A)

New in Basel 3.1 — for exposures with a specific short-term ECAI assessment:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| CQS 4 | 150% |
| CQS 5 | 150% |

!!! note "Table 4A Schema Gap"
    The `has_short_term_ecai` schema field is not yet implemented. The calculator
    currently falls back to Table 4 (general short-term preferential) for all short-term
    institution exposures. See D3.8.

---

## Institution Risk Weights — SCRA (Art. 121)

The Standardised Credit Risk Assessment (SCRA) approach applies when ECAI ratings are not available.
This replaces the CRR sovereign-derived approach (CRR Art. 121, Table 5).

| Grade | Risk Weight | Short-Term (≤3m) | Criteria |
|-------|-------------|------------------|----------|
| Grade A enhanced | **30%** | 20% | CET1 ≥ 14%, leverage ratio ≥ 5% (Art. 121(5)) |
| Grade A | **40%** | 20% | Meets all minimum prudential requirements and buffers (Art. 121(2)(b)) |
| Grade B | **75%** | 50% | Does not meet Grade A criteria but not materially deficient |
| Grade C | **150%** | 150% | Material deficiency in prudential standards |

!!! info "Grade A vs Grade A Enhanced"
    Grade A enhanced (30%, Art. 121(5)) requires **quantitative** thresholds: CET1 ≥ 14% and
    leverage ratio ≥ 5%. Grade A (40%) requires only **qualitative** compliance: the institution
    meets all minimum requirements and capital buffers. This distinction is new in Basel 3.1
    (CRE20.19).

### SCRA Short-Term Trade Finance Exception (Art. 121(4))

Self-liquidating trade-related exposures arising from the movement of goods with an
original maturity ≤ 6 months may receive the short-term risk weight applicable to
Table 5A (Grade A/A enhanced: 20%, Grade B: 50%, Grade C: 150%) even if the exposure
is not otherwise eligible for short-term preferential treatment. This exception ensures
trade finance exposures are not penalised by the full-term SCRA weights.

---

## Corporate Risk Weights (Art. 122)

### CQS-Based Table (Art. 122(1), Table 6)

| CQS | Risk Weight |
|-----|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 75% |
| CQS 4 | 100% |
| CQS 5 | **150%** |
| CQS 6 | 150% |
| Unrated | 100% |

!!! warning "PRA Deviation — CQS 5 = 150%"
    BCBS CRE20.42 reduced corporate CQS 5 from 150% to 100%. The PRA retained **150%** per
    PRA PS1/26 Art. 122(1) Table 6.

### Corporate Sub-Categories (Art. 122(4)–(11))

New in Basel 3.1 — corporates are divided into sub-categories with differentiated risk weights:

| Sub-Category | Risk Weight | Conditions | Reference |
|-------------|-------------|------------|-----------|
| SME corporate | **85%** | Turnover ≤ GBP 44m (previously EUR 50m threshold for SF) | Art. 122(4) |
| Investment grade (IG) | **65%** | PRA permission + internal IG assessment (Art. 122(9)–(10)) | Art. 122(6)(a) |
| Non-IG unrated | **135%** | PRA permission + internal assessment determines non-IG | Art. 122(6)(b) |
| General unrated | **100%** | Default without PRA permission (Art. 122(5)) | Art. 122(5) |

!!! warning "PRA Permission Required for IG/Non-IG Differentiation"
    The 65% IG and 135% non-IG rates require **prior PRA permission** (Art. 122(6)).
    Without permission, all unrated corporates receive the default 100% (Art. 122(5)).
    Investment grade is determined by the **institution's own internal assessment**
    (Art. 122(9)–(10)), not by external rating. SME 85% overrides IG/non-IG regardless
    (Art. 122(11)). IRB output floor firms may elect the IG/non-IG split via Art. 122(8).

### Short-Term Corporate ECAI (Art. 122(3), Table 6A)

New in Basel 3.1 — for exposures with a specific short-term ECAI assessment:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

CRR has no equivalent short-term corporate ECAI table — all corporate exposures use the
long-term CQS mapping (Art. 122(1), Table 6) regardless of assessment tenor. The Table 6A
structure mirrors institution short-term ECRA (Art. 120(2), Table 4) with the same weight
progression.

!!! warning "Not Yet Implemented — Schema Gap"
    Short-term corporate ECAI (Art. 122(3), Table 6A) is not yet implemented. No
    `has_short_term_ecai` schema field exists for corporate exposures (same gap as
    institution Table 4A — see D3.8). The calculator falls back to long-term Table 6 for
    all corporate exposures. No `B31_CORPORATE_SHORT_TERM_RISK_WEIGHTS` constant exists
    in the codebase.

---

## Retail Risk Weights (Art. 123)

| Category | Risk Weight | Reference |
|----------|-------------|-----------|
| Regulatory retail (non-transactor) | **75%** | Art. 123(3)(b) |
| QRRE transactors | **45%** | Art. 123(3)(a) |
| Payroll / pension loans | **35%** | Art. 123(4) |
| Non-regulatory retail | **100%** | Art. 123(3)(c) |

!!! info "CRR2 Continuity"
    The 35% payroll/pension treatment is **not new** in Basel 3.1. It was introduced by CRR2
    (Regulation (EU) 2019/876) in CRR Art. 123 second subparagraph and carried forward unchanged
    to PRA PS1/26 Art. 123(4). The four qualifying conditions (unconditional salary/pension
    deduction, insurance, payments ≤ 20% of net income, maturity ≤ 10 years) are identical.

The retail threshold is changed from EUR 1m to **GBP 880,000** under PRA PS1/26 Art. 123(1)(b)(ii).

### Currency Mismatch Multiplier (Art. 123B)

New in Basel 3.1. For unhedged retail and residential RE exposures where the borrower's income
currency differs from the lending currency:

```
RW_adjusted = min(RW x 1.5, 150%)
```

The 1.5x multiplier is **capped at 150%** — exposures already at or above 150% RW are not
further increased by this multiplier.

Triggered by setting `cp_borrower_income_currency` in the input data to a currency different
from the exposure currency. Output column: `currency_mismatch_multiplier_applied`.

---

## Real Estate — Qualifying Criteria (Art. 124A)

Basel 3.1 introduces a gating requirement for preferential real estate risk weights. An
exposure is a **regulatory real estate exposure** only if it is NOT an ADC exposure
(Art. 124K) and meets **all six** criteria in Art. 124A(1). Exposures failing any criterion
are "other real estate" under Art. 124J with less favourable treatment.

**Regulatory Reference:** PRA PS1/26 Art. 124A (p.51), Art. 124D (pp.52–53)

### The Six Qualifying Criteria (Art. 124A(1))

| Criterion | Requirement | Detail |
|-----------|-------------|--------|
| **(a)** Property condition | Property is not held for development/construction, OR development is complete, OR it is a self-build exposure | Art. 124A(1)(a)(i)–(iii) |
| **(b)** Legal certainty | Charge is enforceable in all relevant jurisdictions AND institution can likely realise collateral value within a reasonable period following default | Art. 124A(1)(b)(i)–(ii) |
| **(c)** Charge conditions | One of the conditions in Art. 124A(2) is met (see below) | Art. 124A(1)(c) |
| **(d)** Valuation | Property valued per Art. 124D requirements (independent, at or below market value) | Art. 124A(1)(d) |
| **(e)** Borrower independence | Property value does NOT materially depend on borrower performance | Art. 124A(1)(e) |
| **(f)** Insurance monitoring | Institution has procedures to monitor adequate property insurance against damage | Art. 124A(1)(f) |

### Charge Conditions (Art. 124A(2))

Criterion (c) is satisfied if **any** of the following apply:

| Condition | Requirement |
|-----------|-------------|
| **(a)** First charge | Exposure is secured by a first-ranking charge over the property |
| **(b)** All prior charges held | Institution holds all charges ranking ahead of the exposure's charge |
| **(c)** Junior charge alternative | (i) Charge provides legally enforceable claim constituting effective CRM; (ii) each charge-holder can independently initiate sale; (iii) sale must seek fair market value or best price |

### Valuation Requirements (Art. 124D)

The valuation standard required by criterion (d):

- Valuation at origination by an independent qualified valuer or robust statistical method
- Must not exceed market value; for purchase financing, the lower of market value and purchase price
- Must not reflect expectations of speculative price increases
- Re-valuation triggers: material value reduction events, market decrease >10%, exposures >GBP 2.6m after 3 years, or all exposures every 5 years
- Self-build: value = higher of (underlying land value, 0.8 × latest qualifying valuation)

### Consequence of Failing — Other Real Estate (Art. 124J)

Exposures that fail any Art. 124A criterion are "other real estate":

| Sub-Type | Risk Weight | Reference |
|----------|-------------|-----------|
| Income-dependent (any property type) | **150%** | Art. 124J(1) |
| Residential, not income-dependent | Counterparty RW per Art. 124L | Art. 124J(2) |
| Commercial, not income-dependent | max(60%, counterparty RW) | Art. 124J(3) |

!!! warning "Input Field: `is_qualifying_re`"
    The calculator uses a single Boolean field `is_qualifying_re` in the input data.
    When `False`, the exposure is routed to Art. 124J treatment **before** the standard
    RE branches. The six Art. 124A(1) criteria must be pre-evaluated by the reporting
    institution — the calculator does not validate individual criteria. If the field is
    omitted, the exposure defaults to qualifying (`True`) for backward compatibility.

## Real Estate — ADC Exposures (Art. 124K)

ADC (Acquisition, Development, and Construction) exposures are loans to corporates or SPEs
financing land acquisition for development and construction, or financing development and
construction of residential or commercial real estate. ADC exposures are explicitly excluded
from the regulatory real estate framework (Art. 124A) and receive standalone treatment.

**Regulatory Reference:** PRA PS1/26 Art. 124K (p.58), Glossary definition (p.3)

### Risk Weights

| Scenario | Risk Weight | Conditions | Reference |
|----------|-------------|------------|-----------|
| Standard (non-qualifying) ADC | **150%** | Default for all ADC exposures | Art. 124K(1) |
| Qualifying residential ADC | **100%** | Residential RE only, subject to both conditions below | Art. 124K(2) |

### Qualifying Conditions for 100% (Art. 124K(2))

The reduced 100% risk weight is available **only** for ADC exposures financing land
acquisition for residential RE development/construction, or financing residential RE
development/construction. **Both** of the following must be met:

**(a) Prudent underwriting** (Art. 124K(2)(a)):

- The exposure is subject to prudent underwriting standards, including for the valuation of
  any real estate used as security for the exposure.

**(b) At least one of** (Art. 124K(2)(b)):

| Condition | Requirement |
|-----------|-------------|
| **(b)(i)** Pre-sales/pre-leases | Legally binding pre-sale or pre-lease contracts, where the purchaser/tenant has made a **substantial cash deposit subject to forfeiture** if the contract is terminated, amount to a **significant portion** of total contracts |
| **(b)(ii)** Borrower equity at risk | The borrower has **substantial equity at risk** |

!!! info "Key Restrictions"
    - **Residential only:** The 100% concession is not available for commercial ADC exposures.
      Commercial ADC always receives 150%.
    - **Corporate/SPE obligors:** ADC exposures are defined as loans to corporates or SPEs —
      natural persons cannot have ADC exposures per the PRA glossary definition.
    - **No regulatory RE treatment:** ADC exposures cannot qualify for LTV-based loan-splitting
      (Art. 124F–124H) or income-producing tables (Art. 124I) regardless of collateral quality.

### CRR Comparison

Under current UK CRR (pre-2027), Art. 128 (high-risk items including speculative immovable
property financing) was omitted by SI 2021/1078 effective 1 Jan 2022. Without Art. 128,
ADC-type exposures fall to standard corporate treatment (100% unrated). Basel 3.1 Art. 124K
re-introduces explicit ADC treatment at a higher 150% default, with a 100% concession for
qualifying residential exposures.

See also: [CRR ADC treatment](../crr/sa-risk-weights.md#adc-exposures-art-124k)

### Implementation

The calculator uses two input fields:

| Field | Type | Description |
|-------|------|-------------|
| `is_adc` | Boolean | Flags the exposure as ADC — routes to Art. 124K treatment, bypassing all RE LTV-band logic |
| `is_presold` | Boolean | Flags the ADC exposure as meeting Art. 124K(2) qualifying conditions — reduces RW from 150% to 100% |

**Code:** `b31_adc_rw_expr()` in `data/tables/b31_risk_weights.py` dispatches on `is_presold`.
ADC sits at priority 4 in the Basel 3.1 SA when-chain (`engine/sa/calculator.py`), after
subordinated debt but before all other RE branches — `is_adc=True` overrides any LTV-based
or income-producing treatment.

!!! warning "Qualifying assessment is external"
    The calculator does not validate whether Art. 124K(2) conditions are met. The reporting
    institution must pre-evaluate prudent underwriting standards and pre-sale/equity-at-risk
    thresholds, then set `is_presold = True` accordingly. PRA does not define quantitative
    thresholds for "substantial" or "significant portion" — these are institution-level
    judgements subject to supervisory review.

### Key Scenarios

| ID | Scenario | is_adc | is_presold | Expected RW | Reference |
|----|----------|--------|------------|-------------|-----------|
| B31-A12 | Standard ADC exposure | True | False | 150% | Art. 124K(1) |
| B31-A13 | Qualifying residential ADC (pre-sold) | True | True | 100% | Art. 124K(2) |
| B31-A14 | ADC overrides RE LTV treatment | True | False | 150% | Art. 124K(1) priority |

---

## Real Estate — Residential (Art. 124F–124G)

All residential RE risk weights below require the exposure to meet the
[Art. 124A qualifying criteria](#real-estate--qualifying-criteria-art-124a).

### General Residential — Loan-Splitting (Art. 124F)

Not materially dependent on cash flows. The exposure is split into a secured portion
(up to 55% of property value) and a residual portion:

| Portion | Risk Weight | Reference |
|---------|-------------|-----------|
| Secured (up to 55% of property value) | **20%** | Art. 124F(1) |
| Residual (above 55% of property value) | Counterparty RW | Art. 124L |

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.20 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Counterparty risk weight** (Art. 124L):

| Counterparty Type | RW |
|-------------------|----|
| Natural person (non-SME) | 75% |
| Retail-qualifying SME | 75% |
| Other SME (unrated) | 85% |
| Social housing / cooperative | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

**Junior charges** (Art. 124F(2)): If a prior or pari passu charge exists that the
institution does not hold, the 55% threshold is reduced by the amount of the prior
charge. This decreases the secured portion, increasing the blended risk weight.

### Income-Producing Residential — Whole-Loan (Art. 124G, Table 6B)

Materially dependent on cash flows (e.g., buy-to-let). Whole-loan approach — single
risk weight on entire exposure:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50–60% | 35% |
| 60–70% | 40% |
| 70–80% | 50% |
| 80–90% | 60% |
| 90–100% | 75% |
| > 100% | 105% |

**Junior charge multiplier** (Art. 124G(2)): Where prior-ranking charges exist that the
institution does not hold, the whole-loan risk weight is multiplied by **1.25×** for
LTV > 50%. The multiplied risk weight is **not capped** at the table maximum (105%) —
it may exceed the highest table band (e.g., 105% x 1.25 = 131.25%).

---

## Real Estate — Commercial (Art. 124H–124I)

All commercial RE risk weights below require the exposure to meet the
[Art. 124A qualifying criteria](#real-estate--qualifying-criteria-art-124a).

### CRE Loan-Splitting (Art. 124H(1))

| Portion | Risk Weight | Reference |
|---------|-------------|-----------|
| Secured (up to 60% LTV) | **60%** | Art. 124H(1) |
| Unsecured (above 60% LTV) | Counterparty RW | Art. 124H(2) |

### CRE Income-Producing (Art. 124I)

For income-dependent commercial RE (cash flows from the property):

**PRA Art. 124I — 2-Band Table**

| LTV | Risk Weight |
|-----|-------------|
| ≤ 80% | **100%** |
| > 80% | **110%** |

!!! warning "PRA Deviation from BCBS"
    BCBS CRE20.86 uses a 3-band table (≤60%: 70%, >60–80%: 90%, >80%: 110%).
    The PRA simplifies to 2 bands with higher weights for the lower LTV tiers.

### Junior Charge Multiplier for Income-Producing CRE (Art. 124I(3))

Where there are prior-ranking charges that the institution does not hold, the risk weight
is multiplied by a band-dependent factor:

| LTV Band | Junior Charge Multiplier |
|----------|------------------------|
| ≤ 60% | 1.0x (no adjustment) |
| 60–80% | 1.25x |
| > 80% | 1.375x |

### Large Corporate CRE (Art. 124H(3))

For non-natural-person, non-SME borrowers with non-cash-flow-dependent CRE:

```
RW = max(60%, min(counterparty_rw, income_producing_rw))
```

This is a distinct third path alongside loan-splitting and income-producing tables.

---

## SA Specialised Lending (Art. 122A–122B)

New exposure class in Basel 3.1. Unrated specialised lending exposures receive type-specific
SA risk weights:

| SL Type | Risk Weight | Reference |
|---------|-------------|-----------|
| Project finance (pre-operational) | **130%** | Art. 122A(1)(a) |
| Project finance (operational) | **100%** | Art. 122A(1)(b) |
| Project finance (high-quality operational) | **80%** | Art. 122B(4)–(5) |
| Object finance | **100%** | Art. 122A(2) |
| Commodities finance | **100%** | Art. 122A(3) |
| IPRE (income-producing) | Follows Art. 124H–124I | Art. 122B |

**High-quality operational project finance** (Art. 122B(4)–(5)): A reduced 80% risk weight
applies to operational project finance exposures that meet **all** of the following criteria:

- **(a)** The obligor can meet its financial obligations even under severely stressed conditions
- **(b)** The obligor has sufficient reserve funds or other financial arrangements to cover contingency funding and working capital requirements over the lifetime of the project
- **(c)** The cash flows generated by the project are predictable

These conditions are assessed by the institution; no specific quantitative thresholds are
prescribed by the PRA. The assessment must reflect the project's ability to service debt under
adverse scenarios.

**Rated** specialised lending falls through to the corporate CQS table per Art. 122A(3).

---

## Covered Bond Exposures (Art. 129)

PRA PS1/26 modifies Art. 129 in-place — there is no separate "Art. 129A".

### Rated Covered Bonds (Art. 129(4), Table 7)

PRA PS1/26 Art. 129(4) Table 7 values are **identical** to the CRR Table 6A values.
The PRA did **not** adopt the BCBS CRE20.28–29 reductions.

| CQS of Issuing Institution | Risk Weight |
|-----------------------------|-------------|
| CQS 1 | 10% |
| CQS 2 | **20%** |
| CQS 3 | 20% |
| CQS 4 | **50%** |
| CQS 5 | **50%** |
| CQS 6 | **100%** |

!!! warning "PRA Deviation from BCBS — PRA Table 7 Unchanged from CRR"
    BCBS CRE20.28–29 reduced certain rated covered bond risk weights (CQS 2: 20%→15%,
    CQS 4: 50%→25%, CQS 5: 50%→35%, CQS 6: 100%→50%). The PRA retained all six
    CRR values unchanged in PRA PS1/26 Art. 129(4) Table 7.

!!! success "P1.113 Fixed"
    `B31_COVERED_BOND_RISK_WEIGHTS` in `b31_risk_weights.py` now uses the correct PRA
    Table 7 values (identical to CRR). Previously used BCBS CRE20 values which
    understated capital for CQS 2 (15%→20%) and CQS 6 (50%→100%).

### Unrated Covered Bonds (Art. 129(5))

The derivation table is expanded from 4 to 7 entries to accommodate new institution
risk weights from ECRA and SCRA:

| Institution Senior Unsecured RW | Covered Bond RW | Art. 129(5) Sub-Para | Change |
|---------------------------------|-----------------|----------------------|--------|
| 20% | 10% | (a) | Unchanged |
| 30% | 15% | (aa) | **New** (ECRA CQS 2) |
| 40% | 20% | (ab) | **New** (SCRA Grade A) |
| 50% | 25% | (b) | ↓ from CRR 20% |
| 75% | 35% | (ba) | **New** (SCRA Grade B) |
| 100% | 50% | (c) | Unchanged |
| 150% | 100% | (d) | Unchanged |

### New Due Diligence Requirement (Art. 129(4A))

Institutions must conduct due diligence on external credit assessments. If analysis
reflects higher risk than the CQS implies, the institution must assign at least one
CQS step higher than the external assessment.

---

## Defaulted Exposures (Art. 127)

See [Defaulted Exposures Specification](defaulted-exposures.md) for the full treatment.

Summary: provision-coverage split — ≥20% provisions → 100% RW, <20% → 150% RW.
Secured portion retains collateral-based RW. RESI RE non-income exception: flat 100%.

---

## CIU Exposures (Art. 132)

Under Basel 3.1, CIU (Collective Investment Undertaking) exposures that cannot be looked
through receive a **1,250%** fallback risk weight (Art. 132(2)). This is a significant
increase from the CRR treatment and differs from the equity risk weights (250%/400%)
that might otherwise apply.

!!! warning "CIU Fallback = 1,250%"
    The 1,250% fallback applies to CIUs where the institution cannot apply the
    look-through approach (Art. 132a) or the mandate-based approach (Art. 132b).
    This is equivalent to a full capital deduction and applies regardless of the
    underlying asset composition of the fund.

---

## Equity (Art. 133)

See [Equity Approach Specification](equity-approach.md) for the full treatment.

Summary: exchange-traded/listed/unlisted 250%, higher-risk/PE/VC 400%, subordinated debt 150%,
central bank 0%, government-supported 100%. Transitional phase-in 2027–2030. The end-state
risk weights apply from **1 January 2030**:

| Equity Type | End-State RW | Reference |
|-------------|-------------|-----------|
| Standard equity (listed/unlisted) | 250% | Art. 133(3) |
| Higher risk (PE/VC, unlisted <5yr) | 400% | Art. 133(5) |
| Subordinated debt / non-equity own funds | 150% | Art. 133(1) |

---

## Basel 3.1 Changes Summary

- **Institution ECRA** (Art. 120): CQS 2 reduced to 30% — Done
- **Institution SCRA** (Art. 121): New grade-based approach with Grade A enhanced 30% — Done
- **Corporate sub-categories** (Art. 122(4)–(11)): SME 85%, IG 65%, non-IG 135% — Done
- **RE qualifying criteria** (Art. 124A): 6-criteria gate for preferential RE weights — Done
- **Other RE fallback** (Art. 124J): 150% / counterparty RW / max(60%, cpty RW) — Done
- **RRE loan-splitting** (Art. 124F–124G): Secured 20% / unsecured counterparty — Done
- **CRE loan-splitting** (Art. 124H): Secured 60% / unsecured counterparty — Done
- **CRE income-producing** (Art. 124I): PRA 2-band (100%/110%) — Done
- **SA Specialised Lending** (Art. 122A–122B): Type-specific weights, incl. 80% high-quality PF — Done
- **Currency mismatch** (Art. 123B): 1.5× multiplier, 150% cap — Done
- **Defaulted provision-coverage** (Art. 127): 100%/150% split — Done
- **Retail threshold** (Art. 123): Changed to GBP 880,000 — Done
- **CIU fallback** (Art. 132(2)): 1,250% for non-look-through CIUs — Documented
- **Short-term ECAI** (Art. 120(2B), Art. 122(3)): New Tables 4A / 6A for short-term assessments — Schema gap
- **SCRA trade finance** (Art. 121(4)): ≤6m trade goods exception for short-term weights — Documented
- **Supporting factors removed** (Art. 501/501a): SME replaced by 85% class — Done
- **Covered bonds rated** (Art. 129(4), Table 7): PRA retains CRR values — spec correct; code bug P1.113
- **Covered bonds unrated** (Art. 129(5)): Expanded 7-entry derivation table for SCRA weights — Done
- **Non-UK unrated PSE/RGLA**: Sovereign CQS-derived weights apply; flat 100% incorrect — code bug P1.112

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-A1 | UK Sovereign CQS 1 | 0% |
| B31-A2 | UK Sovereign unrated | 100% |
| B31-A3 | UK Institution CQS 2 (ECRA) | 30% |
| B31-A4 | Rated corporate CQS 3 | 75% |
| B31-A5 | Unrated corporate (general, no PRA permission) | 100% |
| B31-A6 | Residential RE, 70% LTV (loan-splitting) | Blended: 20% secured + counterparty unsecured |
| B31-A7 | Income-producing commercial RE, 75% LTV | 100% |
| B31-A8 | Retail exposure | 75% |
| B31-A9 | SME corporate (turnover ≤ £44m) | 85% |
| B31-A10 | SME retail (under GBP 880k threshold) | 85% |
| B31-A11 | Non-qualifying income-producing RE (`is_qualifying_re=False`) | 150% (Art. 124J(1)) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: Standardised Approach | A1–A10 | 14 | 100% (14/14) |
