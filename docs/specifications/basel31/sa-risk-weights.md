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
| FR-1.3 | Institution SCRA risk weights (Art. 120(2A), grades A–C) | P0 | Done |
| FR-1.4 | Corporate CQS-based risk weights with PRA CQS 5 = 150% | P0 | Done |
| FR-1.5 | Corporate sub-categories: IG 65%, non-IG unrated 135%, SME 85% | P0 | Done |
| FR-1.6 | Retail 75%, salary/pension 35% (Art. 123) | P0 | Done |
| FR-1.7 | Residential RE loan-splitting (Art. 124F–124G) | P0 | Done |
| FR-1.8 | Commercial RE loan-splitting and income-producing (Art. 124H–124I) | P0 | Done |
| FR-1.9 | SA Specialised Lending (Art. 122A–122B) | P0 | Done |
| FR-1.10 | Currency mismatch multiplier 1.5× (Art. 123A) | P0 | Done |
| FR-1.11 | Defaulted provision-coverage split (Art. 127) | P0 | Done |
| FR-1.12 | Real estate qualifying criteria routing (Art. 124A, 124J) | P0 | Done |

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
| Others | 150% |

!!! note "Table 4A Schema Gap"
    The `has_short_term_ecai` schema field is not yet implemented. The calculator
    currently falls back to Table 4 (general short-term preferential) for all short-term
    institution exposures. See D3.8.

---

## Institution Risk Weights — SCRA (Art. 120(2A))

The Standardised Credit Risk Assessment (SCRA) approach applies when ECAI ratings are not available.
This replaces the CRR sovereign-derived approach (Art. 121, Table 5).

| Grade | Risk Weight | Short-Term (≤3m) | Criteria |
|-------|-------------|------------------|----------|
| Grade A enhanced | **30%** | 20% | CET1 ≥ 14%, leverage ratio ≥ 5% (Art. 120(2A)(a)) |
| Grade A | **40%** | 20% | Meets all minimum prudential requirements and buffers (Art. 120(2A)(b)) |
| Grade B | **75%** | 50% | Does not meet Grade A criteria but not materially deficient |
| Grade C | **150%** | 150% | Material deficiency in prudential standards |

!!! info "Grade A vs Grade A Enhanced"
    Grade A enhanced (30%, Art. 120(2A)) requires **quantitative** thresholds: CET1 ≥ 14% and
    leverage ratio ≥ 5%. Grade A (40%) requires only **qualitative** compliance: the institution
    meets all minimum requirements and capital buffers. This distinction is new in Basel 3.1
    (CRE20.19).

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
| SME corporate | **85%** | Turnover ≤ GBP 440m (previously EUR 50m threshold for SF) | Art. 122(4) |
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

---

## Retail Risk Weights (Art. 123)

| Category | Risk Weight | Reference |
|----------|-------------|-----------|
| General retail | **75%** | Art. 123(1) |
| Salary/pension secured | **35%** | Art. 123(1)(c) |

The retail threshold is changed from EUR 1m to **GBP 880,000** under PRA PS1/26 Art. 123(1)(b)(ii).

### Currency Mismatch Multiplier (Art. 123A)

New in Basel 3.1. For unhedged retail and residential RE exposures where the borrower's income
currency differs from the lending currency:

```
RW_adjusted = min(RW x 1.5, 150%)
```

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
LTV > 50%.

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

### Junior Charge Multiplier for Income-Producing RE (Art. 124I(3))

Where there are prior-ranking charges, the risk weight is multiplied by **1.25×** for LTV > 50%.

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
| Object finance | **100%** | Art. 122A(2) |
| Commodities finance | **100%** | Art. 122A(3) |
| IPRE (income-producing) | Follows Art. 124H–124I | Art. 122B |

**Rated** specialised lending falls through to the corporate CQS table per Art. 122A(3).

---

## Defaulted Exposures (Art. 127)

See [Defaulted Exposures Specification](defaulted-exposures.md) for the full treatment.

Summary: provision-coverage split — ≥20% provisions → 100% RW, <20% → 150% RW.
Secured portion retains collateral-based RW. RESI RE non-income exception: flat 100%.

---

## Equity (Art. 133)

See [Equity Approach Specification](equity-approach.md) for the full treatment.

Summary: exchange-traded/listed/unlisted 250%, higher-risk/PE/VC 400%, subordinated debt 150%,
central bank 0%, government-supported 100%. Transitional phase-in 2027–2030.

---

## Basel 3.1 Changes Summary

- **Institution ECRA** (Art. 120): CQS 2 reduced to 30% — Done
- **Institution SCRA** (Art. 120(2A)): New grade-based approach with Grade A enhanced 30% — Done
- **Corporate sub-categories** (Art. 122(4)–(11)): SME 85%, IG 65%, non-IG 135% — Done
- **RE qualifying criteria** (Art. 124A): 6-criteria gate for preferential RE weights — Done
- **Other RE fallback** (Art. 124J): 150% / counterparty RW / max(60%, cpty RW) — Done
- **RRE loan-splitting** (Art. 124F–124G): Secured 20% / unsecured counterparty — Done
- **CRE loan-splitting** (Art. 124H): Secured 60% / unsecured counterparty — Done
- **CRE income-producing** (Art. 124I): PRA 2-band (100%/110%) — Done
- **SA Specialised Lending** (Art. 122A–122B): Type-specific weights — Done
- **Currency mismatch** (Art. 123A): 1.5× multiplier, 150% cap — Done
- **Defaulted provision-coverage** (Art. 127): 100%/150% split — Done
- **Retail threshold** (Art. 123): Changed to GBP 880,000 — Done
- **Supporting factors removed** (Art. 501/501a): SME replaced by 85% class — Done

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
| B31-A9 | SME corporate (turnover ≤ £440m) | 85% |
| B31-A10 | SME retail (under GBP 880k threshold) | 85% |
| B31-A11 | Non-qualifying income-producing RE (`is_qualifying_re=False`) | 150% (Art. 124J(1)) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: Standardised Approach | A1–A10 | 14 | 100% (14/14) |
