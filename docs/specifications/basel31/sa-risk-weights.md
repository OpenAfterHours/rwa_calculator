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

## Real Estate — Residential (Art. 124F–124G)

### Loan-Splitting Mechanism

Basel 3.1 introduces **loan-splitting** for residential real estate, replacing CRR's flat
35% treatment. The exposure is split into a secured portion (up to LTV threshold) and an
unsecured portion (remainder):

| Portion | Risk Weight | Reference |
|---------|-------------|-----------|
| Secured (up to 80% LTV) | **20%** | Art. 124F(1) |
| Unsecured (above 80% LTV) | Counterparty RW | Art. 124F(2) |

```
secured_ead = min(ead, 0.80 x property_value)
unsecured_ead = max(0, ead - secured_ead)
rwa = secured_ead x 0.20 + unsecured_ead x counterparty_rw
```

!!! note "Art. 124A Qualifying Criteria"
    Preferential RE risk weights require the property to meet the 6 qualifying criteria in
    Art. 124A(1): (a) property condition, (b) legal certainty, (c) charge conditions,
    (d) valuation per Art. 124D, (e) value independence from borrower, (f) insurance monitoring.
    Non-qualifying residential RE receives the counterparty risk weight (no preferential treatment).

### Junior Charge Uplift (Art. 124G(2))

Where there are prior-ranking charges not held by the institution, the secured portion RW
for LTV > 50% is multiplied by **1.25×**:

```
if has_prior_charges and ltv > 50%:
    secured_rw = 20% x 1.25 = 25%
```

---

## Real Estate — Commercial (Art. 124H–124I)

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

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-A: Standardised Approach | A1–A10 | 14 | 100% (14/14) |
