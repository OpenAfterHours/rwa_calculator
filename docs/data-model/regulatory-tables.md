# Regulatory Tables

This page documents the lookup tables used for regulatory risk weight assignment, CCF,
supervisory haircuts, LGD, and slotting.

> **Source of truth**: All table implementations are in `src/rwa_calc/data/tables/`.

## Risk Weight Tables

### Sovereign Risk Weights (CRR Art. 114)

Sovereign weights are identical under CRR and Basel 3.1.

| CQS | Risk Weight |
|-----|------------|
| 1 | 0% |
| 2 | 20% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**Source**: `CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS` in `data/tables/crr_risk_weights.py`

### Institution Risk Weights (CRR Art. 120–121)

| CQS | CRR (Art. 120) | Basel 3.1 ECRA |
|-----|----------------|----------------|
| 1 | 20% | 20% |
| 2 | 50% | **30%** |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% (sovereign-derived) | SCRA (see below) |

!!! warning "Code Divergence"
    The code (`INSTITUTION_RISK_WEIGHTS_UK`) currently uses 30% for CRR CQS 2, labelled as
    a "UK deviation". PDF verification of UK onshored CRR Art. 120 Table 3 confirms CQS 2 = **50%**.
    The 30% value matches Basel 3.1 ECRA (PRA PS1/26 Art. 120 Table 3), not CRR. This is a known
    code bug — see D1.30 in the docs implementation plan.

**Basel 3.1 SCRA** (for unrated institutions, CRE20.16-21):

| Grade | Risk Weight |
|-------|------------|
| A | 40% |
| B | 75% |
| C | 150% |

**Source**: `INSTITUTION_RISK_WEIGHTS_UK`, `B31_SCRA_RISK_WEIGHTS` in `data/tables/`

### Short-Term Institution ECAI (Basel 3.1 Art. 120(2)/(2B))

**Table 4** — long-term ECAI applied to short-term exposure (≤3m, or ≤6m trade finance):

| CQS | Risk Weight |
|-----|-------------|
| CQS 1-3 | 20% |
| CQS 4-5 | 50% |
| CQS 6 | 150% |

**Table 4A** — specific short-term ECAI assessment (Art. 120(2B)):

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

Art. 120(3) governs the interaction: Table 4 applies when no short-term assessment exists;
Table 4A applies when a short-term assessment yields a more favourable or equal weight.

!!! warning "Not Yet Implemented — Schema Gap"
    No `has_short_term_ecai` schema field or `B31_ECRA_SHORT_TERM_TABLE_4A` lookup table
    exists. All short-term institution exposures fall back to Table 4 weights, understating
    risk for CQS 2 (20% applied vs correct 50%) and CQS 3 (20% vs 100%).
    See [B31 SA Risk Weights spec](../specifications/basel31/sa-risk-weights.md#ecra-short-term-ecai-art-1202b-table-4a).

**Source**: `B31_ECRA_SHORT_TERM_RISK_WEIGHTS` in `data/tables/b31_risk_weights.py` (Table 4 only)

### Corporate Risk Weights (CRR Art. 122)

| CQS | CRR | Basel 3.1 | Change |
|-----|-----|-----------|--------|
| 1 | 20% | 20% | — |
| 2 | 50% | 50% | — |
| 3 | **100%** | **75%** | Reduced |
| 4 | 100% | 100% | — |
| 5 | 150% | **150%** | — |
| 6 | 150% | 150% | — |
| Unrated | 100% | 100% | — |

!!! warning "PRA Deviation — CQS 5 = 150%"
    BCBS CRE20.42 reduced corporate CQS 5 from 150% to 100%. The PRA **retained 150%** per
    PRA PS1/26 Art. 122(2) Table 6. The code constant `B31_CORPORATE_RISK_WEIGHTS` correctly
    uses `Decimal("1.50")` for CQS 5.

**Basel 3.1 corporate sub-categories (Art. 122(4)–(11)):**

| Category | Risk Weight | Reference | Conditions |
|----------|------------|-----------|------------|
| Investment grade | 65% | Art. 122(6)(a) | PRA permission required; internal IG assessment (Art. 122(9)–(10)) |
| Non-investment grade | **135%** | Art. 122(6)(b) | PRA permission required; internal non-IG assessment |
| SME corporate | 85% | Art. 122(4) | Turnover ≤ EUR 50m, unrated |
| General unrated | 100% | Art. 122(5) | Default without PRA IG/non-IG permission |

!!! info "Subordinated debt"
    Subordinated debt (150%) is classified under the **equity exposure class** (Art. 133(1)),
    not the corporate class. It sits at priority 3 in the Art. 112 Table A2 waterfall, above
    corporates at priority 16. See the [equity section below](#sa-equity-code-constants).

**Source**: `CORPORATE_RISK_WEIGHTS`, `B31_CORPORATE_RISK_WEIGHTS`, `B31_CORPORATE_INVESTMENT_GRADE_RW`,
`B31_CORPORATE_NON_INVESTMENT_GRADE_RW`, `B31_CORPORATE_SME_RW` in `data/tables/`

### Short-Term Corporate ECAI (Basel 3.1 Art. 122(3), Table 6A)

New in Basel 3.1 — for corporate exposures with a specific short-term ECAI assessment:

| Short-Term CQS | Risk Weight |
|----------------|-------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

CRR has no short-term corporate ECAI table. Not yet implemented — no lookup table or
schema field exists. See [B31 SA Risk Weights spec](../specifications/basel31/sa-risk-weights.md#short-term-corporate-ecai-art-1223-table-6a).

### Retail Risk Weights

| Exposure Type | CRR | Basel 3.1 | Reference |
|---------------|-----|-----------|-----------|
| Retail Mortgage (LTV ≤ 80%) | 35% | LTV-based (see below) | Art. 125 / Art. 124F |
| QRRE Transactors | 75% | 45% | — / Art. 123(3)(a) |
| Payroll / Pension Loans | 35% | 35% | Art. 123 (CRR2) / Art. 123(4) |
| Retail QRRE (non-transactor) | 75% | 75% | Art. 123 / Art. 123(3)(b) |
| Retail Other | 75% | 75% | Art. 123 / Art. 123(3)(b) |
| Non-Regulatory Retail | — | 100% | — / Art. 123(3)(c) |

!!! info "CRR2 Payroll/Pension Treatment"
    The 35% payroll/pension risk weight was introduced by CRR2 (Regulation (EU) 2019/876) and
    carried forward unchanged to PRA PS1/26 Art. 123(4). The CRR code path does not implement
    this treatment — see [CRR SA spec](../specifications/crr/sa-risk-weights.md#payroll--pension-loans-crr-art-123-crr2).

**Source**: `RETAIL_RISK_WEIGHT` in `data/tables/crr_risk_weights.py`, `B31_RETAIL_PAYROLL_LOAN_RW` / `B31_RETAIL_TRANSACTOR_RW` in `data/tables/b31_risk_weights.py`

### CRR Residential Mortgage (CRR Art. 125)

Under CRR, residential mortgages use a split treatment based on 80% LTV threshold:

- LTV ≤ 80%: 35% risk weight
- LTV > 80%: 35% on the secured portion, 75% on the unsecured excess

**Source**: `RESIDENTIAL_MORTGAGE_PARAMS` in `data/tables/crr_risk_weights.py`

### CRR Commercial Real Estate (CRR Art. 126)

Under CRR, commercial RE uses a proportion-based split analogous to Art. 125 for residential.
Art. 126(2)(d): the 50% RW applies only to the part of the loan not exceeding 50% of market
value (or 60% of MLV). The remainder falls to the counterparty's standard exposure class weight.

- LTV ≤ 50%: 50% risk weight (entire loan within secured portion)
- LTV > 50%: 50% on portion up to 50% MV, counterparty RW on excess

Art. 126(2)(a)–(c) qualifying conditions must also be met (property value independence from
borrower credit quality, repayment not dependent on property cash flows, Art. 208/229
compliance).

**Source**: `COMMERCIAL_RE_PARAMS` in `data/tables/crr_risk_weights.py`

!!! bug "Code Divergence (D3.36)"
    The calculator implements Art. 126 as a binary whole-loan treatment (50% if LTV ≤ 50%
    with income cover, 100% otherwise) rather than the regulatory proportion-based split.

### Basel 3.1 Residential Real Estate (PRA PS1/26 Art. 124F-124G)

#### General — Loan-Splitting (Art. 124F)

The PRA adopted loan-splitting (not the BCBS whole-loan table) for general residential:

- Secured portion (up to **55% of property value**) → **20%** risk weight
- Residual → **counterparty risk weight** (75% for individuals per Art. 124L)

**Source**: `B31_RESIDENTIAL_GENERAL_SECURED_RW`, `B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO` in `data/tables/b31_risk_weights.py`

#### Income-producing — Whole-Loan (Art. 124G, Table 6B)

| LTV | Risk Weight |
|-----|------------|
| ≤ 50% | 30% |
| 50–60% | 35% |
| 60–70% | 40% |
| 70–80% | 50% |
| 80–90% | 60% |
| 90–100% | 75% |
| > 100% | 105% |

**Junior Charge Multiplier (Art. 124G(2)):**

| LTV | Multiplier | Effective RW (example) |
|-----|-----------|------------------------|
| ≤ 50% | 1.0× | 30% (no uplift) |
| > 50% | 1.25× | e.g. 50% × 1.25 = 62.5% (at 70–80% LTV) |

The multiplied weight is **not capped** at the Table 6B ceiling — it may exceed 105%
(e.g. 105% × 1.25 = **131.25%** at LTV > 100% with a junior charge).

!!! warning "Code Divergence (P1.111)"
    The current implementation incorrectly caps the multiplied risk weight at 105%.
    Art. 124G(2) has no express cap — the correct result for LTV > 100% with a junior
    charge is 131.25%, not 105%. See IMPLEMENTATION_PLAN.md P1.111.

**Source**: `B31_RESI_INCOME_JUNIOR_MULTIPLIER`, `B31_RESI_INCOME_JUNIOR_LTV_THRESHOLD` in `data/tables/b31_risk_weights.py`

### Basel 3.1 Commercial Real Estate (PRA Art. 124H–124K)

#### General — Natural Person/SME (Art. 124H(1)–(2) — Loan-Splitting)

| LTV | Risk Weight |
|-----|------------|
| ≤ 55% (secured portion) | 60% |
| > 55% (unsecured portion) | counterparty RW |

!!! info "Other Counterparties — Art. 124H(3)"
    For non-natural-person, non-SME borrowers (e.g. large corporates, institutions), no
    loan-splitting applies. The **entire** exposure receives a whole-loan risk weight:
    `RW = max(60%, min(counterparty_rw, income_producing_rw))` where `income_producing_rw`
    is the Art. 124I rate (100% if LTV ≤ 80%, 110% if LTV > 80%). The calculator routes
    automatically when `cp_is_natural_person = False` and `is_sme = False`.

#### Income-Producing (Art. 124I — Whole-Loan)

| LTV | Risk Weight |
|-----|------------|
| ≤ 80% | 100% |
| > 80% | 110% |

!!! warning "PRA vs BCBS deviation"
    BCBS CRE20.86 uses a 3-band table (≤60%: 70%, 60–80%: 90%, >80%: 110%).
    The PRA simplified this to a **2-band table** in Art. 124I.

**Junior Charge Multiplier (Art. 124I(3)):**

| LTV | Multiplier | Effective RW |
|-----|-----------|--------------|
| ≤ 60% | 1.0× | 100% |
| 60–80% | 1.25× | 125% |
| > 80% | 1.375× | 137.5% |

#### ADC Exposures

| Condition | Risk Weight |
|-----------|------------|
| ADC (standard) | 150% |
| ADC (pre-sold) | 100% |

#### Other Real Estate (Art. 124J)

Exposures failing the [Art. 124A qualifying criteria](../specifications/basel31/sa-risk-weights.md#real-estate--qualifying-criteria-art-124a):

| Sub-Type | Risk Weight |
|----------|------------|
| Income-dependent (any property type) | 150% |
| Residential, non-income-dependent | Counterparty RW |
| Commercial, non-income-dependent | max(60%, counterparty RW) |

**Source**: `B31_COMMERCIAL_INCOME_LTV_BANDS`, `B31_ADC_RISK_WEIGHT`, `B31_ADC_PRESOLD_RISK_WEIGHT` in `data/tables/b31_risk_weights.py`

---

## Credit Conversion Factors

### Risk Type Categories (CRR Art. 111)

| Code | Full Value | SA CCF | F-IRB CCF | Description |
|------|------------|--------|-----------|-------------|
| `FR` | `full_risk` | 100% | 100% | Direct credit substitutes, guarantees, acceptances |
| `MR` | `medium_risk` | 50% | 75% | NIFs, RUFs, standby LCs, committed undrawn |
| `MLR` | `medium_low_risk` | 20% | 75% | Documentary credits, trade finance |
| `LR` | `low_risk` | 0% | 0% | Unconditionally cancellable commitments |

**F-IRB 75% Rule (CRR Art. 166(8)):** Under F-IRB, both MR and MLR categories use 75% CCF.

**F-IRB Exception (CRR Art. 166(9)):** Short-term letters of credit arising from the
movement of goods retain 20% CCF under F-IRB. Flag these with `is_short_term_trade_lc = True`.

---

## Supervisory Haircuts (CRR Art. 224 / CRE22.52-53)

### CRR Financial Collateral Haircuts (3 maturity bands)

| Collateral Type | ≤ 1yr | 1–5yr | > 5yr |
|-----------------|-------|-------|-------|
| Cash | 0% | 0% | 0% |
| Government CQS 1 | 0.5% | 2% | 4% |
| Government CQS 2-3 | 1% | 3% | 6% |
| Corporate CQS 1 | 1% | 4% | 8% |
| Corporate CQS 2-3 | 2% | 6% | 12% |
| Equity (main index) | 15% | — | — |
| Equity (other) | 25% | — | — |
| Gold | 15% | — | — |

### Basel 3.1 Financial Collateral Haircuts (5 maturity bands)

| Collateral Type | ≤ 1yr | 1–3yr | 3–5yr | 5–10yr | > 10yr |
|-----------------|-------|-------|-------|--------|--------|
| Cash | 0% | 0% | 0% | 0% | 0% |
| Government CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Government CQS 2-3 | 1% | 3% | 4% | 6% | 12% |
| Corporate CQS 1-2 | 1% | 4% | 6% | 10% | 12% |
| Corporate CQS 3 | 2% | 6% | 8% | 15% | 15% |
| Equity (main index) | **20%** | — | — | — | — |
| Equity (other) | **30%** | — | — | — | — |
| Gold | **20%** | — | — | — | — |

### Non-Financial Collateral Haircuts

| Collateral Type | Haircut |
|-----------------|--------|
| Receivables | 20% |
| Other physical | 40% |

### Additional Haircuts

| Condition | Haircut |
|-----------|--------|
| Currency mismatch | +8% |

**Source**: `COLLATERAL_HAIRCUTS`, `BASEL31_COLLATERAL_HAIRCUTS`, `FX_HAIRCUT` in `data/tables/haircuts.py`

---

## Slotting Risk Weights

### CRR Specialised Lending (CRR Art. 153(5) Table 1)

UK CRR Art. 153(5) has a single table covering all SL types, differentiated by remaining maturity (≥ 2.5 years vs < 2.5 years).

| Category | ≥ 2.5yr | < 2.5yr |
|----------|---------|---------|
| Strong | 70% | **50%** |
| Good | **90%** | **70%** |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% | 0% |

### CRR HVCRE — EU CRR Table 2 (No UK Legal Basis)

!!! warning "UK CRR Has No HVCRE Table"
    The values below are from the **original EU CRR** Table 2. The UK onshored CRR does
    **not** contain this table — "high volatility commercial real estate" does not appear
    in the UK CRR text. All SL types under UK CRR use Table 1 above. HVCRE is introduced
    by PRA PS1/26 Table A (see [Basel 3.1 HVCRE below](#basel-31-hvcre)). The code applies
    these weights for CRR `is_hvcre=True` exposures (code divergence D3.22).

| Category | ≥ 2.5yr | < 2.5yr |
|----------|---------|---------|
| Strong | **95%** | **70%** |
| Good | **120%** | **95%** |
| Satisfactory | **140%** | **140%** |
| Weak | 250% | 250% |
| Default | 0% | 0% |

### Basel 3.1 Non-HVCRE (PRA PS1/26 Art. 153(5) Table A)

Applies to all non-HVCRE SL types (PF, IPRE, OF, CF) regardless of operational status.

| Category | Risk Weight | EL Component |
|----------|------------|-------------|
| Strong | 70% | 0.4% |
| Good | **90%** | 0.8% |
| Satisfactory | 115% | 2.8% |
| Weak | 250% | 8.0% |
| Default | 0% | 50.0% |

!!! warning "No Separate Pre-Operational Table"
    BCBS CRE33.6 Table 6 defines elevated pre-operational PF weights
    (Strong 80%, Good 100%, Satisfactory 120%, Weak 350%). PRA PS1/26
    **does not adopt this distinction** — all project finance uses the
    standard non-HVCRE weights above regardless of operational status.
    The SA calculator handles pre-operational PF separately via
    Art. 122B(2)(c) (130% unrated pre-op, 100% operational, 80% high-quality).
    See [B31 slotting spec](../specifications/basel31/slotting-approach.md)
    for details (FR-5.2).

!!! info "Subgrade Columns (Art. 153(5)(c)–(f))"
    Table A has a 7-column structure with subgrade columns A/B/C/D.
    The weights above are the **default** column B (Strong) and D (Good)
    values per Art. 153(5)(c). Column A (Strong 50%) and C (Good 70%)
    are available for short-maturity (< 2.5yr) exposures and certain
    enhanced-criteria IPRE/PF exposures. Column A/C concessions are
    not yet implemented — see
    [key-differences](../framework-comparison/key-differences.md#slotting-subgrades--table-a-column-structure-art-1535).

### Basel 3.1 HVCRE (PRA PS1/26 Art. 153(5) Table A)

!!! info "Introduced by PRA PS1/26"
    UK CRR has no HVCRE concept. PRA PS1/26 introduces HVCRE as a new
    sub-type with elevated risk weights. See
    [CRR HVCRE note above](#crr-hvcre--eu-crr-table-2-no-uk-legal-basis).

| Category | Risk Weight | EL Component |
|----------|------------|-------------|
| Strong | 95% | 0.4% |
| Good | 120% | 0.8% |
| Satisfactory | 140% | 2.8% |
| Weak | 250% | 8.0% |
| Default | 0% | 50.0% |

**Source (CRR)**: `SLOTTING_RISK_WEIGHTS`, `SLOTTING_RISK_WEIGHTS_SHORT`, `SLOTTING_RISK_WEIGHTS_HVCRE`, `SLOTTING_RISK_WEIGHTS_HVCRE_SHORT` in `data/tables/crr_slotting.py`

**Source (B31)**: `B31_SLOTTING_RISK_WEIGHTS`, `B31_SLOTTING_RISK_WEIGHTS_PREOP`, `B31_SLOTTING_RISK_WEIGHTS_HVCRE` in `data/tables/b31_slotting.py`

---

## F-IRB Supervisory LGD (CRR Art. 161)

### CRR Art. 161 Values

| Category | LGD | Reference |
|----------|-----|-----------|
| Senior unsecured | 45% | Art. 161(1)(a) |
| Subordinated unsecured | 75% | Art. 161(1)(b) |
| Covered bonds (Art. 129(4)/(5)) | 11.25% | Art. 161(1)(d) |
| Senior purchased corporate receivables | 45% | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | 100% | Art. 161(1)(f) |
| Dilution risk of purchased corporate receivables | 75% | Art. 161(1)(g) |

### CRR Art. 230 Table 5 LGDS Values (Secured Portions)

| Collateral Type | LGDS (Senior) | LGDS (Subordinated) |
|----------------|---------------|---------------------|
| Financial collateral | 0% | 0% |
| Receivables | 35% | 65% |
| Residential RE | 35% | 65% |
| Commercial RE | 35% | 65% |
| Other physical | 40% | 70% |

### Basel 3.1 Values (PRA PS1/26)

| Category | LGD | Change |
|----------|-----|--------|
| Senior unsecured (non-FSE) | **40%** | ↓ from 45% |
| Senior unsecured (FSE) | **45%** | — |
| Subordinated | 75% | — |
| Covered bonds | **11.25%** | Art. 161(1)(d) → Art. 161(1B) |
| Senior purchased receivables | **40%** | ↓ from 45% |
| Subordinated purchased receivables | 100% | — |
| Dilution risk | **100%** | ↑ from 75% |
| Secured — Financial collateral | 0% | — |
| Secured — Receivables | **20%** | ↓ from 35% |
| Secured — Residential RE | **20%** | ↓ from 35% |
| Secured — Commercial RE | **20%** | ↓ from 35% |
| Secured — Other physical | **25%** | ↓ from 40% |

!!! info "B31 Art. 230 — Subordinated LGDS Distinction Removed"
    Basel 3.1 Art. 230(2) provides a single LGDS per collateral type with no
    senior/subordinated distinction. The CRR Table 5 subordinated column (65%/70%) is
    not carried forward.

### Overcollateralisation Requirements

| Collateral Type | Min Ratio | Min Threshold |
|-----------------|-----------|---------------|
| Financial | 1.0x | 0% of EAD |
| Covered bonds | 1.0x | 0% of EAD |
| Receivables | 1.25x | 0% of EAD |
| Real estate | 1.4x | 30% of EAD |
| Other physical | 1.4x | 30% of EAD |

**Source**: `FIRB_SUPERVISORY_LGD`, `BASEL31_FIRB_SUPERVISORY_LGD`, `FIRB_OVERCOLLATERALISATION_RATIOS` in `data/tables/firb_lgd.py`

---

## A-IRB LGD Floors

### CRR Portfolio-Level Floors (Art. 164(4))

CRR Art. 164(4) (as amended by CRR2) imposes **portfolio-level** minimum LGD requirements for
retail property-secured exposures: exposure-weighted average LGD ≥ **10%** (residential RE) and
≥ **15%** (commercial RE). These are not per-exposure input floors — they operate at the aggregate
portfolio level. Exposures benefiting from central government guarantees are excluded.

!!! warning "Code Divergence (D3.38)"
    The calculator does not implement CRR portfolio-level LGD floors. `LGDFloors.crr()` returns
    all zeros. See [A-IRB Specification](../specifications/crr/airb-calculation.md#crr-portfolio-level-lgd-floors-art-1644) for details.

### Basel 3.1 Per-Exposure Input Floors

Basel 3.1 replaces the CRR portfolio-level mechanism with per-exposure input floors:

**Corporate / Institution (Art. 161(5)):**

| Collateral Type | LGD Floor |
|-----------------|-----------|
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 10% |
| Other physical | 15% |

Art. 161(5)(a) sets a flat 25% for all corporate unsecured — no senior/subordinated distinction.

**Retail (Art. 164(4)):**

| Exposure Type | LGD Floor |
|---------------|-----------|
| Secured by residential RE | 5% |
| QRRE unsecured | 50% |
| Other unsecured retail | 30% |

---

## PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Sovereign | 0.03% | 0.05% |
| Institution | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.10% |
| Retail QRRE (transactor) | 0.03% | 0.05% |
| Retail QRRE (revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

**Source**: `CRR_PD_FLOOR` in `data/tables/firb_lgd.py`, `PDFloors` in `contracts/config.py`

---

## Equity Risk Weights

### SA Equity (Code Constants)

!!! warning "Code Values vs Regulation"
    This table reflects the **code constants** in `SA_EQUITY_RISK_WEIGHTS` and
    `B31_SA_EQUITY_RISK_WEIGHTS`. Under CRR Art. 133(2), all equity receives a flat
    **100%** — the differentiated weights (250%/400%) apply only under **Basel 3.1**
    Art. 133. The CIU fallback (Art. 132(2)) is **1,250%** per regulation, but the
    code uses 150% (CRR) / 250% (B31). See [Equity Approach](../specifications/crr/equity-approach.md)
    for the regulatory specification.

**CRR SA (Art. 133(2) — flat 100%):**

| Equity Type | Code Value | Regulatory Value |
|------------|-----------|-----------------|
| Central bank | 0% | 0% |
| All other equity | 100% | 100% (Art. 133(2)) |
| CIU (fallback) | 150% | 1,250% (Art. 132(2)) |

**Basel 3.1 SA (Art. 133):**

| Equity Type | Code Value | Regulatory Value |
|------------|-----------|-----------------|
| Central bank | 0% | 0% (Art. 133(6)) |
| Legislative programme | 100% | 100% (Art. 133(6)) |
| Subordinated debt | 150% | 150% (Art. 133(1)) |
| Standard (listed) | 250% | 250% (Art. 133(3)) |
| Higher risk (unlisted + business < 5yr) | 400% | 400% (Art. 133(4)) |
| CIU (fallback) | 250% | 1,250% (Art. 132(2)) |

### IRB Simple Equity (CRR Art. 155)

Art. 155(2) defines exactly three risk weight categories:

| Equity Category | Risk Weight | Reference |
|----------------|-------------|-----------|
| Exchange-traded / listed | 290% | Art. 155(2)(a) |
| Private equity (diversified portfolios) | 190% | Art. 155(2)(b) |
| All other equity | 370% | Art. 155(2)(c) |

**Code mapping** (`IRB_SIMPLE_EQUITY_RISK_WEIGHTS` in `data/tables/crr_equity_rw.py`):

The code maps the `EquityType` enum to these three buckets:

| EquityType enum value | Code RW | Art. 155 bucket |
|----------------------|---------|-----------------|
| `CENTRAL_BANK` | 0% | *(exempt — sovereign treatment)* |
| `PRIVATE_EQUITY_DIVERSIFIED` | 190% | Art. 155(2)(b) |
| `GOVERNMENT_SUPPORTED` | 190% | *(no Art. 155 basis — see D3.4)* |
| `LISTED`, `EXCHANGE_TRADED` | 290% | Art. 155(2)(a) |
| `UNLISTED`, `PRIVATE_EQUITY`, `SPECULATIVE`, `CIU`, `OTHER` | 370% | Art. 155(2)(c) |

!!! warning "Code deviation: GOVERNMENT_SUPPORTED"
    The `GOVERNMENT_SUPPORTED` type is mapped to 190% in the IRB Simple table, but Art. 155 has no "government-supported" category. This is a code-specific mapping (treating it as PE diversified). See [D3.4](../../DOCS_IMPLEMENTATION_PLAN.md).

**Note:** Under Basel 3.1, IRB equity approaches are withdrawn. All equity falls to SA.

**Source**: `SA_EQUITY_RISK_WEIGHTS`, `IRB_SIMPLE_EQUITY_RISK_WEIGHTS` in `data/tables/crr_equity_rw.py`

---

## IRB Parameters

### Maturity Bounds

| Parameter | Value |
|-----------|-------|
| PD floor (CRR) | 0.03% |
| Maturity floor | 1 year |
| Maturity cap | 5 years |

**Source**: `CRR_PD_FLOOR`, `CRR_MATURITY_FLOOR`, `CRR_MATURITY_CAP` in `data/tables/firb_lgd.py`

---

## API Functions

### Risk Weight Lookup

```python
from rwa_calc.data.tables.crr_risk_weights import lookup_risk_weight

rw = lookup_risk_weight(
    exposure_class="corporate",
    cqs=2,
    use_uk_deviation=True
)
# Returns: Decimal("0.50") (50%)
```

### Residential Mortgage RW (CRR)

```python
from rwa_calc.data.tables.crr_risk_weights import calculate_residential_mortgage_rw
from decimal import Decimal

rw, description = calculate_residential_mortgage_rw(ltv=Decimal("0.85"))
# Returns: (blended_rw, "split_treatment")
```

### Basel 3.1 Residential RW

```python
from rwa_calc.data.tables.b31_risk_weights import lookup_b31_residential_rw
from decimal import Decimal

rw, band = lookup_b31_residential_rw(ltv=Decimal("0.65"), is_income_producing=False)
# Returns: (Decimal("0.25"), "60-70%")
```

### Haircut Lookup

```python
from rwa_calc.data.tables.haircuts import lookup_collateral_haircut

haircut = lookup_collateral_haircut(
    collateral_type="bond",
    cqs=1,
    residual_maturity_years=3.0,
    is_main_index=False,
    is_basel_3_1=False
)
# Returns: Decimal("0.04") (4% for govt CQS1 1-5yr)
```

### F-IRB LGD Lookup

```python
from rwa_calc.data.tables.firb_lgd import lookup_firb_lgd

lgd = lookup_firb_lgd(
    collateral_type="residential_re",
    is_subordinated=False,
    is_basel_3_1=False
)
# Returns: Decimal("0.35") (35% CRR) or Decimal("0.20") (20% Basel 3.1)
```

### Slotting Lookup

```python
from rwa_calc.data.tables.crr_slotting import lookup_slotting_rw

rw = lookup_slotting_rw(
    category="good",
    is_hvcre=False,
    is_short_maturity=False
)
# Returns: Decimal("0.90") (90%)
```

### Equity RW Lookup

```python
from rwa_calc.data.tables.crr_equity_rw import lookup_equity_rw

rw = lookup_equity_rw(equity_type="listed", approach="sa")
# Returns: Decimal("1.00") (100%)

rw = lookup_equity_rw(equity_type="listed", approach="irb_simple")
# Returns: Decimal("2.90") (290%)
```

## Next Steps

- [API Reference](../api/index.md)
- [Standardised Approach](../user-guide/methodology/standardised-approach.md)
- [IRB Approach](../user-guide/methodology/irb-approach.md)
