# SA Risk Weights Specification

Standardised Approach risk weights by exposure class and credit quality step.

**Regulatory Reference:** CRR Articles 112-134

**Test Group:** CRR-A

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | SA risk weight calculation for all 9 exposure classes (CRR Art. 112–134) | P0 | Done |
| FR-1.2 | SA risk weight calculation for Basel 3.1 (CRE20–22), including LTV-based RE weights | P0 | Done |

---

## Due Diligence Obligation (Basel 3.1 Art. 110A)

Under Basel 3.1, firms must perform due diligence to ensure they understand the risk profile of their counterparties. Where due diligence is inadequate, the firm must apply a **higher risk weight** than would otherwise apply. This applies to all SA exposure classes and is a precondition for reliance on external ratings.

### Implementation

Two optional input fields support Art. 110A:

| Field | Type | Description |
|-------|------|-------------|
| `due_diligence_performed` | Boolean | Whether the firm has completed its DD assessment for this exposure |
| `due_diligence_override_rw` | Float64 | Override risk weight (as decimal, e.g. 1.50 = 150%) when DD reveals higher risk |

**Override behaviour:**
- The override is applied as the **final risk weight modification** — after all standard RW determination, CRM adjustments, and currency mismatch multiplier
- The override can only **increase** the risk weight: `RW_final = max(RW_calculated, RW_override)`
- Null override values are silently ignored (no override applied)
- The override is a **floor**, not a replacement — if the calculated RW already exceeds the override, the calculated RW is retained

**Validation:**
- Under Basel 3.1, if the `due_diligence_performed` column is absent from the input data, a `SA004` warning is emitted (severity: WARNING, category: DATA_QUALITY)
- Under CRR, no warning is emitted (Art. 110A does not exist under CRR)

**Audit:**
- When the override column is present, a `due_diligence_override_applied` Boolean audit column is added to the output, indicating which exposures had their risk weight overridden

**Sequencing in the SA calculator:**
1. Standard risk weight determination (CQS lookup, class-specific rules)
2. FCSM / life insurance / guarantee substitution (CRM)
3. Currency mismatch multiplier (Art. 123B)
4. **Due diligence override (Art. 110A)** ← applied here
5. RWA calculation (EAD × RW)

## Sovereign Exposures (CRR Art. 114)

| CQS | Rating Equivalent | Risk Weight |
|-----|-------------------|-------------|
| 1 | AAA to AA- | 0% |
| 2 | A+ to A- | 20% |
| 3 | BBB+ to BBB- | 50% |
| 4 | BB+ to BB- | 100% |
| 5 | B+ to B- | 100% |
| 6 | CCC+ and below | 150% |
| Unrated | — | 100% |

**Domestic currency**: Sovereign exposures denominated and funded in the domestic currency of that sovereign may receive **0%** risk weight (Art. 114(4)).

## RGLA Exposures (CRR Art. 115)

Regional governments and local authorities. Two possible treatments:

### Sovereign-Derived Treatment — Table 1A (Art. 115(1)(a))

Where RGLA exposures lack their own ECAI rating, use the **sovereign's CQS** with Table 1A:

| Sovereign CQS | RGLA Risk Weight |
|---------------|-----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |

Under PRA rules, UK devolved administrations (Scotland, Wales, Northern Ireland) receive **0%** risk weight.

### Own-Rating Treatment — Table 1B (Art. 115(1)(b))

Where RGLA exposures have their own ECAI rating, use Table 1B:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | 100% |

**UK local authorities**: All UK local authorities receive **20%** risk weight per PRA designation.

**Sterling-funded short-term**: RGLA exposures of the UK denominated and funded in **sterling** receive **20%** regardless of CQS (Art. 115(5)).

## PSE Exposures (CRR Art. 116)

Public sector entities have three sub-treatments:

### Sub-treatment 1 — Sovereign-Derived — Table 2 (Art. 116(1))

UK PSEs without own ECAI rating use the **sovereign's CQS** with Table 2:

| Sovereign CQS | PSE Risk Weight |
|---------------|----------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |

### Sub-treatment 2 — Own-Rating — Table 2A (Art. 116(2))

UK PSEs with own ECAI rating use Table 2A:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |

!!! note "Art. 116(4) left blank"
    PRA PS1/26 leaves Art. 116(4) blank — there is no "institution-equivalent" PSE sub-treatment under the PRA rules. UK PSEs use Tables 2/2A above.

**Short-term exposures (≤ 3 months)**: UK PSE exposures with original effective maturity ≤ 3 months receive **20%** risk weight (Art. 116(3)). No domestic currency condition required for PSEs.

## MDB Exposures (CRR Art. 117)

### Named MDBs at 0% (Art. 117(2))

The following 16 MDBs receive a **0%** risk weight:

1. International Bank for Reconstruction and Development (IBRD / World Bank)
2. International Finance Corporation (IFC)
3. Inter-American Development Bank (IDB)
4. Asian Development Bank (ADB)
5. African Development Bank (AfDB)
6. Council of Europe Development Bank (CEB)
7. Nordic Investment Bank (NIB)
8. Caribbean Development Bank (CDB)
9. European Bank for Reconstruction and Development (EBRD)
10. European Investment Bank (EIB)
11. European Investment Fund (EIF)
12. Multilateral Investment Guarantee Agency (MIGA)
13. International Finance Facility for Immunisation (IFFIm)
14. Islamic Development Bank (IsDB)
15. Asian Infrastructure Investment Bank (AIIB)
16. International Development Association (IDA)

### Rated MDBs — Table 2B (Art. 117(1))

Other MDBs not on the 0% list use Table 2B:

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | **30%** |
| 3 | 50% |
| 4 | 100% |
| 5 | 100% |
| 6 | 150% |
| Unrated | **50%** |

!!! note "MDB Table Differs from Institution Table"
    MDB Table 2B has CQS 2 = 30% (same as UK institutions) and unrated = **50%** (not 40% like UK institutions). Do not use the institution table for MDB lookups.

## International Organisations (CRR Art. 118)

The following international organisations receive a **0%** risk weight:

- European Union (EU)
- International Monetary Fund (IMF)
- Bank for International Settlements (BIS)
- European Financial Stability Facility (EFSF)
- European Stability Mechanism (ESM)

## Institution Exposures (CRR Art. 120-121)

!!! note "UK Deviation"
    CQS 2 institutions receive a 30% risk weight under the UK CRR, rather than the standard 50% under EU CRR.

| CQS | Risk Weight (UK) | Risk Weight (EU Standard) |
|-----|-------------------|--------------------------|
| 1 | 20% | 20% |
| 2 | **30%** | 50% |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 40% | 100% |

UK unrated institutions default to 40% (derived from sovereign CQS 2).

### Short-Term Institution Exposures (CRR Art. 120(2), Art. 121(3))

Rated institutions with residual maturity ≤ 3 months receive preferential risk weights
under Art. 120(2). Unrated institutions with maturity ≤ 3 months receive 20% under
Art. 121(3).

**Table 4 — Short-Term Preferential (CRR Art. 120(2))**

| Institution CQS | Short-Term RW |
|-----------------|---------------|
| 1 | 20% |
| 2 | 20% |
| 3 | 20% |
| 4-5 | 50% |
| 6 | 150% |
| Unrated | 20% (Art. 121(3)) |

!!! warning "Correction: CRR has no Table 4A"
    CRR Tables 3 and 4 both use the **institution's own ECAI rating** — Table 3 for
    general maturities (Art. 120(1)), Table 4 for short-term (Art. 120(2)). The
    sovereign-derived approach for **unrated** institutions is Art. 121 (Table 5).
    Earlier versions of this spec incorrectly labelled Table 4 as "Sovereign-Derived"
    and included a non-existent "Table 4A".

!!! info "Basel 3.1 — Table 4A: Short-Term ECAI Assessments (Art. 120(2B))"
    Basel 3.1 introduces Table 4A for institutions with a specific **short-term ECAI
    assessment** (as opposed to a long-term rating applied to a short-term exposure).
    Table 4A uses the short-term CQS scale with only 3 steps:

    | Short-Term CQS | 1 | 2 | 3 | Others |
    |----------------|---|---|---|--------|
    | Risk Weight | 20% | 50% | 100% | 150% |

    Art. 120(3) governs the interaction: where no short-term rating exists, Table 4
    applies; where a short-term rating yields a lower or equal RW, Table 4A applies;
    where it yields a worse RW, unrated short-term claims against that obligor also
    receive the higher weight.

## Corporate Exposures (CRR Art. 122)

| CQS | Risk Weight |
|-----|-------------|
| 1 | 20% |
| 2 | 50% |
| 3 | 100% |
| 4 | 100% |
| 5 | 150% |
| 6 | 150% |
| Unrated | 100% |

## Retail Exposures (CRR Art. 123)

All qualifying retail exposures receive a flat **75%** risk weight.

### Basel 3.1 Retail Sub-Treatments (Art. 123)

| Sub-Treatment | Risk Weight | Condition | Reference |
|---------------|-------------|-----------|-----------|
| Regulatory retail | 75% | Meets all 4 qualifying criteria (Art. 123A) | Art. 123(1) |
| QRRE transactors | 45% | Qualifying revolving, balance repaid monthly | Art. 123(2) (Basel 3.1) |
| QRRE non-transactors | 75% | Qualifying revolving, non-transactor | Art. 123(2) |
| Payroll / pension loans | 35% | Loans secured by assignment of borrower's payroll or pension income | Art. 123(3)(a-b) |
| Non-regulatory retail | 100% | Retail exposure that fails Art. 123A qualifying criteria | Art. 123(3)(c) |

## Covered Bond Exposures (CRR Art. 129)

Covered bonds backed by eligible collateral pools receive preferential risk weights:

### CRR Covered Bond Risk Weights (Art. 129(4))

| CQS of Issuing Institution | Risk Weight |
|-----------------------------|-------------|
| 1 | 10% |
| 2 | 20% |
| 3 | 20% |
| 4 | 50% |
| 5 | 50% |
| 6 | 100% |
| Unrated | 20% (if institution CQS 1-2 equivalent) |

### Eligibility Conditions (Art. 129(1)-(3))

Covered bonds must meet the following to qualify for preferential treatment:

- Issued by a credit institution with registered office in the UK or EEA
- Subject to special public supervision protecting bond holders
- Backed by one of: (a) residential mortgage loans ≤ 80% LTV, (b) commercial mortgage loans ≤ 60% LTV, (c) exposures to central/regional governments ≤ CQS 1-2, (d) exposures to credit institutions ≤ CQS 1-2
- Bond holders have priority claim in the event of issuer default

### Basel 3.1 Covered Bond Changes (Art. 129A)

Under Basel 3.1, covered bond risk weights are reduced and the CQS mapping is simplified:

| CQS of Issuing Institution | Risk Weight |
|-----------------------------|-------------|
| 1 | 10% |
| 2 | 15% |
| 3 | 20% |
| 4-6 | 50% |
| Unrated | Derived from issuer (A_ENHANCED→15%, A→20%, B→35%, C→100%) |

!!! note "Implementation Status"
    Covered bonds are implemented as a separate exposure class under Art. 112(m).
    Both CRR and Basel 3.1 rated risk weights are wired via CQS join tables.
    B31 unrated derivation uses SCRA grade → institution RW → CB RW chain
    per Art. 129(5) with values traced to COVERED_BOND_UNRATED_DERIVATION table.

## High-Risk Exposures (Art. 128)

Exposures associated with particularly high risk receive **150%** risk weight. Assessment
criteria per Art. 128(3): (a) high risk of loss from obligor default; (b) impossible to
adequately assess whether (a) applies.

Examples of high-risk items include speculative immovable property financing and other
exposures designated by the PRA. Under the Art. 112 Table A2 exposure class waterfall,
equity (priority 3) takes precedence over high-risk items (priority 4) — venture capital
and private equity exposures are classified as equity under Art. 133, not as high-risk
items under Art. 128.

!!! warning "Art. 128 Omitted from UK CRR (SI 2021/1078)"
    Art. 128 was **omitted from UK onshored CRR** by The Capital Requirements Regulation
    (Amendment) Regulations 2021 (SI 2021/1078), reg. 6(3)(a), effective 1 January 2022.
    The high-risk exposure class is a **dead letter under current UK CRR** (pre-2027).
    Exposures that would otherwise be classified as high-risk should fall through to
    their counterparty's standard exposure class (e.g., equity at 100% per Art. 133(2),
    or corporate at the applicable CQS weight).

    Under **PRA PS1/26** (Basel 3.1, effective 1 January 2027), Art. 128 is **re-introduced**
    with paragraphs 1 and 3 retained (paragraph 2 left blank — the original EU CRR
    Art. 128(2) list of specific categories such as venture capital and speculative RE
    is not carried forward). The 150% risk weight applies from 2027.

!!! bug "Code Note (D3.12)"
    The calculator's CRR engine path currently applies Art. 128 (150%) to HIGH_RISK
    exposures despite the UK CRR omission. Under strict UK CRR treatment, these
    exposures should fall through to their standard exposure class. The Basel 3.1
    engine path correctly applies Art. 128.

## Residential Mortgage Exposures (CRR Art. 125)

Risk weight depends on LTV ratio with a split at 80%:

| LTV | Treatment |
|-----|-----------|
| LTV ≤ 80% | 35% on whole exposure |
| LTV > 80% | Split: 35% on portion up to 80% LTV, 75% on excess |

**Blended formula for LTV > 80%:**

```
avg_RW = 0.35 x (0.80 / LTV) + 0.75 x ((LTV - 0.80) / LTV)
```

## Commercial Real Estate (CRR Art. 126)

| Condition | Risk Weight |
|-----------|-------------|
| LTV ≤ 50% and rental income ≥ 1.5x interest costs | 50% |
| All other CRE | 100% |

## Basel 3.1 Residential Real Estate (PRA PS1/26 Art. 124F-124G)

### General Residential — Loan-Splitting (Art. 124F)

Not materially dependent on cash flows from the property. PRA adopted the **loan-splitting approach** (not the BCBS CRE20.73 whole-loan table):

- **Secured portion** (up to 55% of property value): **20%** risk weight
- **Residual portion** (above 55% of property value): **counterparty risk weight** (Art. 124L)

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
| Social housing | max(75%, unsecured RW) |
| Other | Unsecured counterparty RW |

**Junior charges** (Art. 124F(2)): If a prior or pari passu charge exists, the 55% threshold is reduced by the amount of the prior charge. The effective secured portion decreases, increasing the blended risk weight.

### Income-Producing Residential — Whole-Loan (Art. 124G, Table 6B)

Materially dependent on cash flows from the property (e.g., buy-to-let). Whole-loan approach — single risk weight on entire exposure:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 50% | 30% |
| 50-60% | 35% |
| 60-70% | 40% |
| 70-80% | 50% |
| 80-90% | 60% |
| 90-100% | 75% |
| > 100% | 105% |

**Junior charge multiplier** (Art. 124G(2)): **1.25x** applied to the whole-loan risk weight when LTV > 50% and prior/pari passu charges exist.

### Commercial RE — General, Loan-Splitting (Art. 124H)

Not materially dependent on cash flows:

**Natural person / SME**: Split approach — **60%** on portion up to 55% of property value, counterparty RW on remainder.

```
secured_share = min(1.0, 0.55 / LTV)
RW = 0.60 × secured_share + counterparty_RW × (1.0 - secured_share)
```

**Other counterparties** (Art. 124H(3)):

```
RW = max(60%, min(counterparty_RW, income_producing_RW))
```

Where `income_producing_RW` is the Art. 124I whole-loan weight for the same LTV band. This formula ensures the RW is at least 60% (the secured portion floor) but no more than the lower of the counterparty's unsecured RW or the income-producing table rate.

### Commercial RE — Income-Producing (Art. 124I)

Materially dependent on cash flows:

| LTV Band | Risk Weight |
|----------|-------------|
| ≤ 80% | 100% |
| > 80% | 110% |

**Junior charge multiplier** (Art. 124I(3)):

| LTV Band | Multiplier |
|----------|------------|
| ≤ 60% | 1.0× (100%) |
| 60-80% | 1.25× (125%) |
| > 80% | 1.375× (137.5%) |

### Other Real Estate (Art. 124J)

Non-regulatory real estate (doesn't meet Art. 124A requirements):

| Type | Risk Weight |
|------|-------------|
| Income-dependent | 150% |
| RESI non-dependent | Counterparty RW |
| CRE non-dependent | max(60%, counterparty RW) |

### ADC Exposures (Art. 124K)

| Condition | Risk Weight |
|-----------|-------------|
| Default | 150% |
| Residential with pre-sales/equity at risk | 100% |

## Basel 3.1 Corporate Exposures (PRA PS1/26 Art. 122(2) Table 6)

| CQS | Rating Equivalent | CRR Risk Weight | Basel 3.1 Risk Weight (PRA) |
|-----|-------------------|-----------------|---------------------------|
| 1 | AAA to AA- | 20% | 20% |
| 2 | A+ to A- | 50% | 50% |
| 3 | BBB+ to BBB- | **100%** | **75%** |
| 4 | BB+ to BB- | 100% | 100% |
| 5 | B+ to B- | **150%** | **150%** |
| 6 | CCC+ and below | 150% | 150% |
| Unrated | — | 100% | 100% |

!!! warning "PRA vs BCBS Deviation for CQS 5"
    BCBS CRE20.42 sets CQS 5 = **100%** (reduced from CRR 150%). However, PRA PS1/26 Art. 122(2) Table 6 retains CQS 5 = **150%** (same as CQS 6). The PRA did not adopt the BCBS reduction for this credit quality step. The calculator must use the PRA value (150%), not the BCBS value (100%).

### Additional Basel 3.1 Corporate Treatments

| Treatment | Risk Weight | Condition |
|-----------|-------------|-----------|
| Investment-grade corporate (Art. 122(6)(a)) | 65% | Unrated, institution IG assessment, requires PRA permission |
| Non-investment-grade corporate (Art. 122(6)(b)) | **135%** | Unrated, assessed as non-IG, requires PRA permission |
| SME corporate (Art. 122(11)) | 85% | SME qualifying corporate (replaces CRR 100% + 0.7619 SF) |
| Subordinated debt (CRE20.49) | 150% | Overrides all other treatments |

!!! note "PRA Permission Required for Investment Grade Assessment (Art. 122(6)–(10))"
    The 65%/135% split requires **prior PRA permission** and demonstration of sound credit
    risk management practices (Art. 122(6)). Without permission, all unrated non-SME corporates
    receive **100%** (Art. 122(5)). The investment grade definition (Art. 122(9)) requires
    adequate capacity to meet financial commitments, robust against adverse economic cycles —
    this is the institution's own internal assessment (Art. 122(10)), not an external rating.
    SME corporates (Art. 122(11)) receive **85%** regardless of IG status. For IRB output
    floor S-TREA (Art. 122(8)), firms may elect the 65%/135% split instead of flat 100%.

## Basel 3.1 Institution Exposures (CRE20.16-21)

Rated institutions use ECRA (same CQS table as CRR, including UK CQS 2 = 30% deviation). Unrated institutions use SCRA:

| SCRA Grade | Risk Weight (>3m) | Risk Weight (≤3m) | Criteria |
|------------|--------------------|--------------------|----------|
| A | 40% | 20% | Meets all minimum requirements + buffers |
| A (enhanced) | 30% | 20% | CET1 ≥ 14% AND leverage ratio ≥ 5% |
| B | 75% | 50% | Meets minimum requirements |
| C | 150% | 150% | Below minimum requirements |

ECRA (rated) takes precedence over SCRA (unrated). SCRA does not apply under CRR.

## Equity Exposures (CRR Art. 133 / PRA PS1/26 Art. 133)

### CRR Equity Risk Weights

Art. 133(2) assigns a **flat 100%** to all equity. Art. 133 has only 3 paragraphs — references to "Art. 133(3)" or "Art. 133(4)" with differentiated weights are erroneous (those values belong to Art. 155 IRB Simple).

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Central bank / sovereign equity | 0% | Sovereign treatment |
| All other equity (listed, unlisted, PE, etc.) | 100% | Art. 133(2) flat |
| CIU (fallback) | 1,250% | Art. 132(2) |

!!! warning "Previous Spec Error Corrected"
    This table previously showed Unlisted=150% (Art. 133(3)) and PE/VC=190% (Art. 133(4)). These paragraph numbers and values were fabricated. The 150%/190% values are from **Art. 155** (IRB Simple Method), not Art. 133. PE/VC that qualifies as high-risk is treated under Art. 128 (150%), not Art. 133. See [Equity Approach Specification](equity-approach.md) for full details.

### Basel 3.1 Equity Risk Weights (PRA PS1/26 Art. 133)

| Equity Type | Risk Weight | Reference |
|-------------|-------------|-----------|
| Subordinated debt / non-equity own funds | 150% | Art. 133(1) |
| Standard equity (listed) | 250% | Art. 133(3) |
| Higher risk (unlisted AND held < 5yr, or PE/VC) | 400% | Art. 133(5) |
| Legislative equity (carve-out for govt-mandated holdings) | 100% | Art. 133(6) |

!!! warning "PRA Deviation from BCBS"
    PRA Art. 133 does **not** include the BCBS "CQS 1-2 speculative unlisted = 100%" or "CQS 3-6/unrated speculative = 150%" tiers. PRA uses a simpler structure: listed = 250%, higher-risk (unlisted <5yr / PE/VC) = 400%.

**Note:** Basel 3.1 removes IRB equity approaches (Art. 147A). All equity uses SA risk weights. See [Equity Approach](equity-approach.md) for full details including CIU treatment and transitional schedule.

## Defaulted Exposures (CRR Art. 127 / PRA PS1/26 Art. 127)

### CRR Default Risk Weights

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ 20% of (EAD + provision_deducted) | 100% |
| Specific provisions < 20% | 150% |

### Basel 3.1 Default Risk Weights (PRA PS1/26 Art. 127)

| Condition | Risk Weight |
|-----------|-------------|
| Specific provisions ≥ **20%** of exposure value | 100% |
| Specific provisions < **20%** | 150% |
| RESI RE non-dependent (Art. 124F) in default | **100% (always)** — regardless of provision level |

!!! warning "Threshold Difference from CRR"
    The Basel 3.1 provision threshold for defaulted exposures is **20%** (same as CRR). Note that the threshold denominator changes: CRR uses `EAD + provision_deducted`, while Basel 3.1 uses `exposure value`.

## Basel 3.1 SA Specialised Lending (Art. 122A-122B)

New Basel 3.1 SA exposure class with risk weights distinct from general corporates:

| SL Type | Phase | Risk Weight |
|---------|-------|-------------|
| Object finance | — | 100% |
| Commodities finance | — | 100% |
| Project finance | Pre-operational | 130% |
| Project finance | Operational | 100% |
| Project finance | High-quality operational | 80% |

Rated specialised lending exposures use the corporate CQS table (Art. 122A(3)).

## Other Items (CRR Art. 134 / PRA PS1/26 Art. 134)

| Item | Risk Weight | Reference |
|------|-------------|-----------|
| Cash and equivalent (notes, coins) | 0% | Art. 134(1) |
| Gold bullion (held in own vaults or allocated) | 0% | Art. 134(4) |
| Items in course of collection | 20% | Art. 134(3) |
| Repo-style transactions — RW of underlying asset | Asset RW | Art. 134(5) |
| Nth-to-default basket credit derivatives | Per Art. 266-270 | Art. 134(5) |
| Tangible assets (premises, equipment) | 100% | Art. 134(2) |
| Prepaid expenses, accrued income | 100% | Art. 134(2) |
| Residual value of leased assets | 1/t × 100% (t = remaining lease years, min 1) | Art. 134(6) |
| All other | 100% | Art. 134(2) |

## ECA Consensus Risk Scores (CRR Art. 137 / Table 9)

Export Credit Agency (ECA) consensus risk scores are mapped to CQS for sovereign exposures when no ECAI rating is available:

| ECA Risk Score | CQS Mapping | Risk Weight |
|---------------|-------------|-------------|
| 0-1 | CQS 1 | 0% |
| 2 | CQS 2 | 20% |
| 3 | CQS 3 | 50% |
| 4-6 | CQS 4-5 | 100% |
| 7 | CQS 6 | 150% |

This mapping is used for sovereign exposures (Art. 114) and for deriving institution risk weights from their sovereign's ECA score where the sovereign lacks an ECAI rating.

!!! note "Implementation Status"
    ECA score lookup is not yet implemented. The calculator currently requires ECAI CQS for rated exposures. ECA-to-CQS mapping is a future enhancement.

## Basel 3.1 Changes Summary

- **Due diligence obligation** (Art. 110A): New prerequisite for all SA risk weight assignments — Done
- **Residential RE loan-splitting** (Art. 124F): 20% on ≤55% LTV, counterparty RW on residual — Done
- **Residential RE income-producing** (Art. 124G): Whole-loan LTV table (30%-105%) — Done
- **Commercial RE loan-splitting** (Art. 124H): 60% on ≤55% LTV, counterparty RW on residual — Done
- **Commercial RE other counterparties** (Art. 124H(3)): max/min formula — Done
- **Commercial RE income-producing** (Art. 124I): 100%/110% at ≤80%/>80% — Done
- **Junior charge multipliers** (Art. 124F/G/I): 1.25x / 1.375x for subordinate liens — Done
- **Other Real Estate** (Art. 124J): 150% income-dependent, counterparty RW otherwise — Done
- **Revised corporate CQS mapping** (Art. 122(2) Table 6): CQS 3 from 100% to 75% — Done. **Note:** PRA retains CQS 5 = 150% (BCBS CRE20.42 reduced to 100%, but PRA did not adopt this reduction)
- **SCRA for unrated institutions** (CRE20.18): Grade A/B/C risk weights replace flat 40% — Done
- **SCRA enhanced Grade A** (CRE20.19): 30% for CET1 ≥ 14% and leverage ratio ≥ 5% — Done
- **SCRA short-term maturity** (CRE20.20): Grade A/A_ENHANCED 20%, Grade B 50% for ≤3m exposures — Done
- **Investment-grade corporates** (Art. 122(6)(a)): 65% for unrated investment-grade (PRA permission required) — Done
- **Non-investment-grade corporates** (Art. 122(6)(b)): 135% for unrated non-IG (PRA permission required) — Done
- **SME corporate** (Art. 122(11)): 85% flat weight, replaces CRR 100% + supporting factor — Done
- **Subordinated debt** (CRE20.49): 150% flat, overrides all other treatments — Done
- **Equity** (Art. 133): 250% standard, 400% higher risk, 150% subordinated — Done
- **Retail transactor/non-transactor** (Art. 123): 45% QRRE transactors vs 75% non-transactors — Done
- **Payroll/pension loans** (Art. 123): 35% — Done
- **Non-regulatory retail** (Art. 123(3)(c)): 100% — Done
- **SA Specialised Lending** (Art. 122A-122B): OF/CF=100%, PF pre-op=130%, PF op=100% — Done
- **Default exposures** (Art. 127): Provision-based 100%/150% with RESI RE always-100% exception — Done
- **Other items** (Art. 134): Cash=0%, gold=0%, collection=20%, tangible=100% — Done
- **Covered bonds** (Art. 129/129A): CQS-based risk weights, eligibility criteria — Added
- **RGLA/PSE/MDB/Int'l Org tables** (Art. 115-118): Missing from original spec — Added
- **ECA consensus scores** (Art. 137 Table 9): ECA-to-CQS mapping for unrated sovereigns — Added
- **Removal of SME supporting factor**: No longer applicable under Basel 3.1
- **Removal of 1.06 scaling factor**: Scaling factor set to 1.0 under Basel 3.1

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| CRR-A1 | UK Sovereign CQS 1 | 0% |
| CRR-A4 | UK Institution CQS 2 (UK deviation) | 30% |
| CRR-A | Corporate unrated | 100% |
| CRR-A | Retail exposure | 75% |
| CRR-A | Residential mortgage LTV 60% | 35% |
| CRR-A | CRE with income cover, LTV 45% | 50% |
| B31-A2 | Corporate CQS 2 (Basel 3.1) | 50% |
| B31-A3 | UK Institution CQS 2 (Basel 3.1 ECRA) | 30% |
| B31-A8 | SME corporate (Basel 3.1) | 85% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 100% (14/14) |
| B31-A: Basel 3.1 SA | A1–A10 | 14 | 100% (14/14) |
