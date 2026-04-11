# Framework Comparison

This page provides a comprehensive comparison between CRR (Basel 3.0) and Basel 3.1 frameworks.

## Overview

| Aspect | CRR (Basel 3.0) | Basel 3.1 |
|--------|-----------------|-----------|
| **Effective** | Until 31 Dec 2026 | From 1 Jan 2027 |
| **Philosophy** | Risk sensitivity | Comparability + floors |
| **IRB Benefit** | Unlimited | Floored at 72.5% of SA |
| **Supporting Factors** | SME + Infrastructure | None |
| **Scaling** | 1.06 multiplier | None |

## Exposure Class Restructuring

Basel 3.1 restructures SA exposure classes with an explicit priority waterfall
(PRA PS1/26 Art. 112, Table A2). The most significant structural change is that
**real estate** becomes a standalone exposure class, rather than being a sub-treatment
of secured corporate or retail exposures under CRR Art. 125/126.

**New priority waterfall (highest to lowest):**

1. Securitisation positions
2. CIU units/shares
3. Subordinated debt, equity and own funds instruments
4. Exposures associated with particularly high risk
5. Exposures in default
6. Eligible covered bonds
7. **Real estate exposures** (new standalone class)
8. International organisations
9. Multilateral development banks
10. Institutions
11. Central governments / central banks
12. Regional governments / local authorities
13. Public sector entities
14. Retail exposures
15. Corporates (including [SA specialised lending](#sa-specialised-lending-art-122a-122b) — Art. 122–122B)
16. Other items

Where an exposure meets multiple criteria, the highest-priority class applies.

!!! info "Art. 128 Re-introduction"
    Priority 4 (high-risk items) was omitted from UK CRR by SI 2021/1078 effective
    1 January 2022. Basel 3.1 re-introduces Art. 128 with paragraphs 1 and 3 retained
    (paragraph 2 left blank). The 150% risk weight for particularly high risk
    exposures applies from 1 January 2027.

!!! note "SA Specialised Lending Waterfall Position"
    SA specialised lending (Art. 122A–122B) is classified within the **corporate**
    exposure class (Art. 112(1)(g), row 15) — there is no separate exposure class for
    SA SL. Art. 122A(1) explicitly defines SA SL as "a corporate exposure that is **not
    a real estate exposure**", which means IPRE secured by real estate is caught at
    row 7 (real estate, Art. 124–124L) instead. Only object finance, commodities
    finance, and unsecured project finance reach row 15 for SA SL treatment.
    See [SA Specialised Lending (Art. 122A-122B)](#sa-specialised-lending-art-122a-122b)
    for risk weights and the [Hierarchy & Classification spec](../specifications/common/hierarchy-classification.md#basel-31-exposure-class-priority-art-112)
    for the full priority table.

## IRB Treatment

### Scaling Factor

=== "CRR"

    ```python
    # 6% uplift on all IRB RWA
    RWA = K × 12.5 × EAD × MA × 1.06
    ```

=== "Basel 3.1"

    ```python
    # No scaling factor
    RWA = K × 12.5 × EAD × MA
    ```

**Impact:** ~5.7% reduction in IRB RWA (before output floor)

### Output Floor

=== "CRR"

    No output floor. IRB RWA can be significantly below SA.

    ```
    Example:
    - SA RWA: £100m
    - IRB RWA: £30m
    - Final RWA: £30m (70% capital saving)
    ```

=== "Basel 3.1"

    72.5% floor limits IRB benefit (phased in: 60%/65%/70%/72.5% over 2027–2030).

    ```
    Full formula (Art. 92(2A)):
    TREA = max{U-TREA; x × S-TREA + OF-ADJ}

    Example (fully phased):
    - SA RWA (S-TREA): £100m
    - IRB RWA (U-TREA): £30m
    - Floor: £100m × 72.5% = £72.5m
    - Final RWA: £72.5m (27.5% capital saving only)
    ```

    The **OF-ADJ** term (`12.5 × (IRB_T2 – IRB_CET1 – GCRA + SA_T2)`) reconciles the
    different treatment of provisions under IRB and SA. See the
    [Technical Reference](technical-reference.md#output-floor-adjustment-of-adj) for the
    component breakdown.

!!! warning "Entity-Type Carve-Outs (Art. 92(2A)(b)–(d))"
    The output floor does **not** apply to all entities. Art. 92(2A)(b)–(d) exempts:
    non-ring-fenced institutions on sub-consolidated basis, ring-fenced bodies at individual
    level (when in a sub-consolidation group), and international subsidiaries on consolidated
    basis. Exempt entities use U-TREA (un-floored amount) directly. See the
    [output floor spec](../specifications/basel31/output-floor.md#entity-type-carve-outs) for
    the full applicability table.

!!! note "Transitional Rates Are Permissive"
    Art. 92 para 5 says institutions "may apply" the transitional rates — firms can
    voluntarily use 72.5% from day one.

### PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Large Corporate | 0.03% | 0.05% |
| Sovereign | 0.03% | 0.05% |
| Institution | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | **0.10%** |
| Retail QRRE (Transactor) | 0.03% | 0.05% |
| Retail QRRE (Revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

!!! note "Sovereign and Institution PD Floors"
    Under Basel 3.1, sovereign exposures are restricted to SA only (Art. 147A) and institution
    exposures to F-IRB only. PD floors for these classes (Art. 160(1)) remain relevant for any
    grandfathered or transitional IRB treatment. See the
    [F-IRB specification](../specifications/basel31/firb-calculation.md#pd-floors-art-160-163)
    for the complete table.

### LGD Floors (A-IRB Only)

!!! note "CRR Portfolio-Level Floors vs Basel 3.1 Per-Exposure Input Floors"
    CRR Art. 164(4) (as amended by CRR2) imposes **portfolio-level** minimum LGD
    requirements: exposure-weighted average LGD ≥ 10% (retail residential RE) and ≥ 15%
    (retail commercial RE). These are **not** per-exposure input floors — they operate at
    the aggregate portfolio level and exclude exposures benefiting from central government
    guarantees. Basel 3.1 Art. 164(4) **replaces** this with per-exposure input floors
    applied to each exposure individually before the capital formula.

**Corporate / Institution:**

| Collateral Type | CRR | Basel 3.1 |
|-----------------|-----|-----------|
| Unsecured | No per-exposure floor | 25% |
| Financial Collateral (LGDS) | No per-exposure floor | 0% |
| Receivables (LGDS) | No per-exposure floor | 10%* |
| Commercial/Residential RE (LGDS) | No per-exposure floor | 10%* |
| Other Physical (LGDS) | No per-exposure floor | 15%* |

**Retail:**

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Secured by Residential RE (flat) | Portfolio avg ≥ 10% | **5%** (per-exposure) |
| Secured by Commercial RE | Portfolio avg ≥ 15% | Via LGD* formula |
| QRRE Unsecured | No floor | **50%** |
| Other Unsecured Retail | No floor | **30%** |
| Secured — LGDU in LGD* formula | No floor | **30%** |
| Secured — Financial Collateral (LGDS) | No floor | 0% |
| Secured — Receivables (LGDS) | No floor | 10%* |
| Secured — Immovable Property (LGDS) | No floor | 10%* |
| Secured — Other Physical (LGDS) | No floor | 15%* |

Note: The retail unsecured LGDU used in the LGD* formula for secured exposures is
**30%** (Art. 164(4)(c)), compared to 25% for corporates (Art. 161(5)(b)).

*LGDS values reflect PRA PS1/26 implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%).

### F-IRB Supervisory LGD

#### Art. 161 LGD Values

| Exposure Type | CRR | Basel 3.1 | Change |
|---------------|-----|-----------|--------|
| Financial Sector Entity (Senior) | 45% | **45%** | — |
| Other Corporate (Senior) | 45% | **40%** | -5pp |
| Corporate/Institution (Subordinated) | 75% | **75%** | — |
| Covered Bonds | 11.25% | **11.25%** | Art. restructured |
| Senior purchased corporate receivables | 45% | **40%** | -5pp |
| Subordinated purchased corporate receivables | 100% | **100%** | — |
| Dilution risk | 75% | **100%** | +25pp |

#### Art. 230 LGDS Values (Secured Portions)

| Collateral Type | CRR | Basel 3.1 | Change |
|----------------|-----|-----------|--------|
| Secured - Financial Collateral | 0% | **0%** | — |
| Secured - Receivables | 35% | **20%** | -15pp |
| Secured - CRE/RRE | 35% | **20%** | -15pp |
| Secured - Other Physical | 40% | **25%** | -15pp |

!!! info "Covered Bond LGD — Article Restructured, Value Unchanged"
    CRR Art. 161(1)(d) already assigns 11.25% LGD for covered bonds eligible under
    Art. 129(4) or (5) — this is not a Basel 3.1 introduction. Basel 3.1 restructures
    the provision into a new Art. 161(1B) paragraph but retains the identical 11.25% value.
    The CRR text uses permissive language ("may be assigned"); the B31 text may formalise this
    as mandatory. See [CRR F-IRB spec](../specifications/crr/firb-calculation.md#art-1611-lgd-values)
    for the full Art. 161(1)(a)–(g) breakdown.

!!! info "Purchased Receivables and Dilution Risk Changes"
    Art. 161(1)(e)/(f) apply where PD cannot be estimated for the purchased receivables pool
    (Art. 160(2)). Basel 3.1 aligns senior purchased receivables with the new non-FSE rate
    (45% → 40%). The dilution risk LGD increases significantly from 75% to **100%**
    (Art. 161(1)(g)). Subordinated purchased receivables remain at 100%.

!!! info "B31 Art. 230 — Subordinated LGDS Distinction Removed"
    CRR Art. 230 Table 5 has separate senior/subordinated LGDS columns (receivables 35%/65%,
    RE 35%/65%, other 40%/70%). PRA PS1/26 Art. 230(2) removes the subordinated distinction —
    only a single LGDS per collateral type remains. Under Basel 3.1, the subordination effect
    is captured solely through LGDU (75%, Art. 161(1)(b)).

### IRB Approach Restrictions

Basel 3.1 introduces two levels of IRB restriction (Art. 147A):

- **Complete IRB removal** — certain exposure classes must use the Standardised Approach;
  IRB (both F-IRB and A-IRB) is no longer permitted.
- **A-IRB removal** — own-LGD estimates are removed; only F-IRB (supervisory LGD) is allowed.

| Exposure Type | CRR | Basel 3.1 | Reference |
|---------------|-----|-----------|-----------|
| Central Govts, Central Banks & Quasi-Sovereigns | F-IRB or A-IRB | **SA only** | Art. 147A(1)(a) |
| Bank/Institution | F-IRB or A-IRB | **F-IRB only** | Art. 147A(1)(b) |
| IPRE / HVCRE (Specialised Lending) | F-IRB, A-IRB, or Slotting | **Slotting only** | Art. 147A(1)(c) |
| Other SL (Object/Project/Commodities) | F-IRB, A-IRB, or Slotting | F-IRB, A-IRB, or Slotting | Art. 147A(1)(d) |
| Financial Sector Entities | F-IRB or A-IRB | **F-IRB only** | Art. 147A(1)(e) |
| Large Corporate (>£440m) | F-IRB or A-IRB | **F-IRB only** | Art. 147A(1)(e) |
| Other General Corporates | F-IRB or A-IRB | F-IRB or A-IRB | Art. 147A(1)(f) |
| Retail (all subclasses) | A-IRB | A-IRB | Art. 147A(1)(g) |
| Equity | IRB | **SA only** | Art. 147A(1)(h) |

**Quasi-sovereign scope (Art. 147(3)):** The central governments/central banks class includes
regional governments, local authorities, PSEs, MDBs, and international organisations that
receive a 0% SA risk weight. Under Basel 3.1, all of these entities are mandatorily SA.

**IRB 10% RW floor for UK residential mortgages (PRA-specific):** Non-defaulted retail exposures
secured by UK residential property must have a minimum risk weight of **10%** under IRB,
regardless of model output (applied as post-model adjustment).

### Financial Sector Correlation Multiplier

Under both CRR and Basel 3.1, **large financial sector entities** (total assets ≥ EUR 70bn per
Art. 4(1)(146)) and **unregulated financial sector entities** receive a **1.25x** correlation
multiplier on their asset correlation (Art. 153(2) / CRE31.5). This is unchanged between
frameworks.

!!! warning "Two distinct thresholds — do not conflate"
    - **EUR 70bn total assets** → 1.25x correlation uplift (Art. 153(2)). Applies to the asset correlation coefficient R for large/unregulated FSEs.
    - **GBP 440m annual revenue** → F-IRB only approach restriction (Art. 147A(1)(d), Basel 3.1 only). Does not affect correlation.

    These are entirely separate mechanisms applying to different entity populations and parameters.

### A-IRB CCF Floor

Under Basel 3.1, A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type (CRE32.27). This constrains A-IRB benefit from low CCF estimates.

### Post-Model Adjustments (PMAs)

Basel 3.1 introduces mandatory **post-model adjustments** (Art. 146(3)) — a new concept
with no CRR equivalent. When an IRB rating system does not comply with IRB requirements
and the non-compliance causes a material reduction in RWA or EL, the institution must
quantify additive adjustments to offset the impact:

| PMA Component | Covers | Added via |
|---------------|--------|----------|
| Mortgage RW floor | Min 10% RW for UK residential mortgage exposures | Art. 154(4A)(b) |
| (a) Corporate/Institution RWA | Model deficiencies on corporate/institution exposures | Art. 153(5A) |
| (b) Retail RWA | Model deficiencies on retail exposures | Art. 154(4A)(a) |
| (c) Expected Loss | Model deficiencies affecting EL amounts | Art. 158(6A) |

#### Sequencing (Art. 154(4A))

The mortgage RW floor and general PMA scalars must be applied in a **mandatory order**:

1. **First:** Mortgage risk weight floor (Art. 154(4A)(b)) — `RW = max(RW_modelled, 0.10)`
2. **Then:** General PMA RWA/EL scalar (Art. 154(4A)(a) / Art. 153(5A) / Art. 158(6A))

The PMA scalar operates on the floor-adjusted RWEA, not the raw modelled RWEA. Reversing
the order would allow the scalar to amplify a sub-floor RW, producing an incorrectly low
result. See the [A-IRB specification](../specifications/basel31/airb-calculation.md#adjustment-sequencing-art-1535a--art-1544a) for the full formula chain.

#### EL Monotonicity (Art. 158(6A))

EL after PMA must satisfy `EL_adjusted >= EL_unadjusted`. PMAs cannot decrease expected
loss, preventing conservative RWA overlays from inadvertently reducing EL shortfall.

PMAs are included in the output floor calculation base, so they cannot be avoided by
flooring to SA. They persist until the model non-compliance is remediated.

### Effective Maturity (Art. 162)

PRA PS1/26 substantially rewrites Art. 162. The most significant change is the **deletion
of F-IRB fixed supervisory maturities** — all IRB firms must now calculate M.

| Aspect | CRR | Basel 3.1 | Change |
|--------|-----|-----------|--------|
| F-IRB fixed maturities (§1) | 0.5yr repo / 2.5yr other | **Deleted** | All IRB firms calculate M |
| Scope | A-IRB only (Art. 143) | F-IRB and A-IRB (Art. 147A) | Expanded |
| Revolving exposures (§2A(k)) | Repayment date of current drawing | **Max contractual termination date** | Increases M |
| Mixed MNA (§2A(da)) | Not addressed | **10-day floor** | New |
| Purchased receivables min M (§2A(e)) | 90 days | **1 year** | Raised |
| Collateral daily condition (§2A(c)/(d)) | Re-margining **and** revaluation | Re-margining **or** revaluation | Wider scope |
| SME simplification (§4) | Available (EUR 500m threshold) | **Deleted** | Removed |
| One-day floor (§3) | Daily remargined repos/derivatives | Retained (wider trigger) | Unchanged |
| General floor / cap | 1yr / 5yr | 1yr / 5yr | Unchanged |

!!! info "Impact of Deleting F-IRB Fixed Maturities"
    Under CRR, F-IRB repo-style transactions received a fixed M = 0.5 years (below the
    general 1-year floor), significantly reducing their maturity adjustment. Under Basel 3.1,
    these exposures must be calculated from cash flows or contractual terms, subject to the
    1-year general floor — roughly doubling the effective M for short-dated repos.

See the [Technical Reference](technical-reference.md#irb-effective-maturity-art-162) for
additional detail and the [F-IRB specifications](../specifications/crr/firb-calculation.md#effective-maturity-crr-art-162) for the full regulatory text.

## Supporting Factors

### SME Supporting Factor

=== "CRR (Article 501)"

    **Eligibility:**
    - Turnover ≤ EUR 50m
    - Corporate, Retail, or Real Estate secured

    **Calculation:**
    ```python
    # Tiered approach
    threshold = EUR 2.5m  # GBP 2.2m

    if exposure <= threshold:
        factor = 0.7619  # 23.81% reduction
    else:
        factor = (threshold × 0.7619 + (exposure - threshold) × 0.85) / exposure
    ```

    | Exposure | Factor | RWA Reduction |
    |----------|--------|---------------|
    | £1m | 0.7619 | 23.81% |
    | £2.2m | 0.7619 | 23.81% |
    | £5m | 0.811 | 18.9% |
    | £10m | 0.831 | 16.9% |

=== "Basel 3.1"

    **SME Supporting Factor: REMOVED**

    No capital relief for SME exposures.

### Infrastructure Supporting Factor

=== "CRR"

    **Eligibility:**
    - Qualifying infrastructure project finance
    - Revenues in EUR/GBP or hedged

    **Calculation:**
    ```python
    factor = 0.75  # 25% reduction
    RWA_adjusted = RWA × 0.75
    ```

=== "Basel 3.1"

    **Infrastructure Factor: REMOVED**

    No capital relief for infrastructure projects.

## SA Risk Weights

### Corporate

| CQS | CRR | Basel 3.1 | Change |
|-----|-----|-----------|--------|
| CQS1 (AAA-AA-) | 20% | 20% | - |
| CQS2 (A+-A-) | 50% | 50% | - |
| CQS3 (BBB+-BBB-) | 100% | 75% | -25pp |
| CQS4 (BB+-BB-) | 100% | 100% | - |
| CQS5 (B+-B-) | 150% | 150% | - |
| CQS6 (CCC+/Below) | 150% | 150% | - |
| Unrated | 100% | 100% | - |

!!! note "PRA vs BCBS Deviation for CQS 5"
    BCBS CRE20.42 reduced CQS 5 from 150% to 100%. However, PRA PS1/26 Art. 122(2) Table 6 **retains CQS 5 at 150%**. The PRA did not adopt this reduction.

#### New Basel 3.1 Corporate Sub-Categories (Art. 122(6)–(11))

| Sub-Category | Basel 3.1 RW | Criteria |
|-------------|-------------|----------|
| Investment Grade (Art. 122(6)(a)) | **65%** | Unrated, institution IG assessment, PRA permission required |
| Non-Investment Grade (Art. 122(6)(b)) | **135%** | Unrated, assessed as non-IG, PRA permission required |
| SME Corporate (Art. 122(11)) | **85%** | Turnover ≤ EUR 50m, unrated |

!!! note "PRA Permission Required"
    The 65%/135% investment grade split requires **prior PRA permission** (Art. 122(6)).
    Without permission, all unrated non-SME corporates receive 100% (Art. 122(5)).
    Investment grade is assessed by the institution's own internal credit assessment
    (Art. 122(9)–(10)), not by external ratings. SME corporates receive 85% regardless.

#### Short-Term Corporate ECAI (Art. 122(3), Table 6A) — New in Basel 3.1

CRR has no short-term corporate ECAI table. Basel 3.1 introduces Table 6A for corporate
exposures with a specific short-term credit assessment:

| Short-Term CQS | Basel 3.1 RW |
|----------------|--------------|
| CQS 1 | 20% |
| CQS 2 | 50% |
| CQS 3 | 100% |
| Others | 150% |

This mirrors the institution short-term ECRA table (Art. 120(2), Table 4) but applies to
corporate exposures. Under CRR, short-term corporate exposures use the standard Table 6
long-term CQS mapping — there is no tenor-specific treatment.

!!! warning "Not Yet Implemented"
    Short-term corporate ECAI (Art. 122(3), Table 6A) is not yet implemented in the
    calculator. No `has_short_term_ecai` schema field exists for corporate exposures.
    All corporate exposures currently use the long-term CQS table (Art. 122(2), Table 6).
    See [B31 SA Risk Weights spec](../specifications/basel31/sa-risk-weights.md#short-term-corporate-ecai-art-1223-table-6a)
    for details.

### Institution Exposures

Basel 3.1 replaces the CRR institution risk weight approach with two distinct methods:

**Rated institutions — ECRA (External Credit Risk Assessment Approach):**

| CQS | CRR | Basel 3.1 | Basel 3.1 (≤3m) | Change |
|-----|-----|-----------|-----------------|--------|
| CQS 1 | 20% | 20% | 20% | — |
| CQS 2 | 50% | **30%** | 20% | -20pp |
| CQS 3 | 50% | 50% | 20% | — |
| CQS 4 | 100% | 100% | 50% | — |
| CQS 5 | 100% | 100% | 50% | — |
| CQS 6 | 150% | 150% | 150% | — |

!!! warning "Table 4A — Short-Term ECAI Assessment (Art. 120(2B))"
    The "Basel 3.1 (≤3m)" column above shows **Table 4** weights — a long-term ECAI
    rating applied to a short-term exposure. Basel 3.1 also introduces **Table 4A** for
    institutions with a specific short-term credit assessment:
    CQS 1 = 20%, CQS 2 = **50%**, CQS 3 = **100%**, Others = **150%**.
    Art. 120(3) governs the interaction: where no short-term assessment exists, Table 4
    applies; where a short-term assessment yields a more favourable or equal RW, Table 4A
    applies for that exposure only.
    **Not yet implemented** — the `has_short_term_ecai` schema field does not exist. All
    short-term institution exposures currently fall back to Table 4 weights. See
    [B31 SA Risk Weights spec](../specifications/basel31/sa-risk-weights.md#ecra-short-term-ecai-art-1202b-table-4a).

**Unrated institutions — SCRA (Standardised Credit Risk Assessment Approach):**

| Grade | Risk Weight (>3m) | Risk Weight (≤3m) | Criteria |
|-------|-------------------|-------------------|----------|
| A | 40% | 20% | Meets all minimum requirements + buffers |
| A (enhanced) | 30% | 20% | CET1 ≥ 14% AND leverage ratio ≥ 5% |
| B | 75% | 50% | Meets minimum requirements (excluding buffers) but not Grade A (Art. 121(1)(b)) |
| C | 150% | 150% | Does not meet minimum requirements, or adverse audit opinion (Art. 121(1)(c)) |

!!! warning "Correction: Grade B Has No Quantitative Thresholds"
    Prior documentation incorrectly stated Grade B criteria as "CET1 ≥ 5.5%, Leverage ≥ 3%".
    These thresholds **do not appear** in PRA PS1/26 Art. 121 or BCBS CRE20. Grade B is a
    **qualitative** assessment: the institution meets published minimum regulatory requirements
    (excluding buffers) but does not qualify for Grade A. Only Grade A enhanced (30%) has
    quantitative thresholds (CET1 ≥ 14%, leverage ≥ 5% per Art. 121(5)). If minimum
    requirements are not publicly disclosed, the institution must be classified as Grade C.

Under CRR, unrated institutions use the sovereign-based approach. The SCRA represents
a fundamentally different methodology based on the institution's own capital adequacy.

**Sovereign floor (Art. 121(6)):** Unrated institution risk weights cannot be lower than their sovereign's
risk weight for foreign-currency exposures. Self-liquidating trade finance ≤1yr excluded.

### Residential Real Estate

!!! info "Material Dependency Classification (Art. 124E) — New in Basel 3.1"
    Basel 3.1 introduces Art. 124E, a formal test for routing RE exposures between
    loan-splitting (non-dependent) and whole-loan (income-producing) treatment. CRR
    has no equivalent — the distinction between Art. 125 (general) and Art. 126
    (income-producing) was not gated by a structured classification rule.

    **Residential RE** is materially dependent by default. The five exceptions for
    non-dependent classification are: (a) primary residence, (b) natural person with
    ≤3 non-primary qualifying properties (three-property limit), (c) SPE with natural
    person guarantor meeting the same limit, (d) social housing, (e) cooperative for
    primary residence use. Each housing unit counts as a separate property even under
    a single charge (Art. 124E(4)).

    **Commercial RE** is materially dependent unless the borrower uses each property
    predominantly for its own business purpose, excluding rental income (Art. 124E(6)).

    See [Art. 124E specification](../specifications/basel31/sa-risk-weights.md#real-estate--material-dependency-classification-art-124e).

!!! warning "Art. 124A Qualifying Gate"
    All preferential RE risk weights below (Art. 124F–124I) require the exposure to be a
    **regulatory real estate exposure** per Art. 124A — meeting 6 criteria: (a) property
    condition, (b) legal certainty, (c) charge conditions per Art. 124A(2), (d) valuation
    per Art. 124D, (e) value independence from borrower, (f) insurance monitoring.
    Exposures failing any criterion receive Art. 124J treatment: **150%** if income-dependent,
    counterparty RW if RESI non-dependent, or max(60%, counterparty RW) if CRE non-dependent.
    See [SA Risk Weights — Art. 124A](../specifications/basel31/sa-risk-weights.md#real-estate--qualifying-criteria-art-124a)
    for the full criteria.

**General (not cash-flow dependent) — PRA Art. 124F: Loan-Splitting**

The PRA adopted loan-splitting (not the BCBS whole-loan LTV-band table):

| Component | CRR | Basel 3.1 (Art. 124F) |
|-----------|-----|----------------------|
| Secured portion (up to 55% of property value) | 35% (flat up to 80% LTV) | **20%** |
| Residual portion | 75% (or counterparty RW) | **Counterparty RW** (75% for individuals per Art. 124L) |

Example: At 80% LTV, secured share = 55%/80% = 68.75%. Weighted RW = 20%×0.6875 + 75%×0.3125 = **37.2%** (vs CRR 35%).

**Income-producing (cash-flow dependent) — PRA Art. 124G, Table 6B: Whole-Loan**

| LTV | CRR | Basel 3.1 |
|-----|-----|-----------|
| ≤ 50% | 35% | **30%** |
| 50-60% | 35% | **35%** |
| 60-70% | 35% | **40%** |
| 70-80% | 35% | **50%** |
| 80-90% | 75% | **60%** |
| 90-100% | 75% | **75%** |
| > 100% | Cpty RW | **105%** |

!!! info "Junior Charge Multiplier (Art. 124G(2))"
    Where prior-ranking charges exist that the institution does not hold (i.e. a junior lien),
    the Table 6B risk weight is multiplied by **1.25×** when LTV > 50%.
    At LTV ≤ 50% the 30% weight applies without uplift.
    The multiplied weight is **not capped** at the Table 6B ceiling — it may exceed 105%
    (e.g. 105% × 1.25 = **131.25%** at LTV > 100% with a junior charge).
    **Example:** junior charge at 75% LTV → 50% × 1.25 = **62.5%** whole-loan.
    CRR has no equivalent junior-charge multiplier for residential RE.
    See [B31 SA spec](../specifications/basel31/sa-risk-weights.md#income-producing-residential--whole-loan-art-124g-table-6b)
    for full details.

### Commercial Real Estate

#### CRE Loan-Splitting — Natural Person/SME (Art. 124H(1)–(2))

| Portion | CRR (Art. 126) | Basel 3.1 (Art. 124H) | Change |
|---------|----------------|----------------------|--------|
| Secured portion | 50% (≤50% MV / 60% MLV) | **60%** (≤55% property value) | Higher RW, higher threshold |
| Unsecured residual | Counterparty RW | Counterparty RW (Art. 124L) | Explicit lookup table added |

CRR Art. 126(2)(d) applies a proportion-based split to all qualifying CRE regardless of
counterparty type: the 50% RW applies only to the part of the loan not exceeding 50% of
market value (or 60% of MLV), with the excess falling to the counterparty's standard
exposure class weight. Basel 3.1 Art. 124H(1)–(2) restricts loan-splitting to natural
persons and SMEs, with a higher secured RW (60% vs 50%) and a higher threshold (55% vs 50%).

!!! info "Art. 124H(3) — Large Corporate CRE (Non-Natural-Person, Non-SME)"
    For counterparties that are **not** natural persons and **not** SMEs (e.g. large corporates,
    institutions), Basel 3.1 does not apply loan-splitting. Instead, Art. 124H(3) assigns a
    **whole-loan** risk weight to the entirety of the exposure:

    `RW = max(60%, min(counterparty_rw, income_producing_rw))`

    where `income_producing_rw` is the Art. 124I rate for the same LTV band (100% if LTV ≤ 80%,
    110% if LTV > 80%). This ensures the risk weight is at least 60% but does not exceed the
    lower of the counterparty's unsecured weight and the income-producing table rate.

    **CRR has no equivalent entity-type distinction** — all CRE uses the same Art. 126 split
    regardless of counterparty type.

    The calculator routes automatically: when `cp_is_natural_person = False` **and**
    `is_sme = False` (or both absent), the Art. 124H(3) path applies. No separate input flag
    is required.

    See: [B31 specification](../specifications/basel31/sa-risk-weights.md#large-corporate-cre-art-124h3)

#### Income-Producing CRE (PRA Art. 124I) — Whole-Loan

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| LTV ≤ 80%, Income-Producing | 100% | **100%** |
| LTV > 80%, Income-Producing | 100% | **110%** |

!!! warning "PRA vs BCBS deviation"
    BCBS CRE20.86 uses a 3-band table for CRE income-producing (≤60%: 70%, 60–80%: 90%, >80%: 110%).
    The PRA simplified this to a **2-band table** (≤80%: 100%, >80%: 110%) in Art. 124I.

**Junior Charge Multiplier (Art. 124I(3)):** Where prior-ranking charges exist that are not held by the institution, the risk weight is multiplied:

| LTV | Multiplier | Effective RW |
|-----|-----------|--------------|
| ≤ 60% | 1.0× | 100% |
| 60–80% | 1.25× | 125% |
| > 80% | 1.375× | 137.5% |

### Other Real Estate (Art. 124J)

Exposures that fail any [Art. 124A qualifying criterion](../specifications/basel31/sa-risk-weights.md#real-estate--qualifying-criteria-art-124a) are classified as "other real estate" and receive punitive treatment:

| Sub-Type | Risk Weight | Reference |
|----------|-------------|-----------|
| Income-dependent (any property type) | **150%** | Art. 124J(1) |
| Residential, not income-dependent | Counterparty RW (Art. 124L) | Art. 124J(2) |
| Commercial, not income-dependent | max(60%, counterparty RW) | Art. 124J(3) |

!!! warning "No CRR Equivalent"
    CRR does not have qualifying criteria for RE treatment — the Art. 124A/124J qualifying gate
    and punitive fallback is entirely new in Basel 3.1. Set `is_qualifying_re = False` in the
    input data to route exposures to Art. 124J treatment. When omitted, defaults to `True`.

See: [B31 specification — Other Real Estate](../specifications/basel31/sa-risk-weights.md#consequence-of-failing--other-real-estate-art-124j)

### ADC Exposures (Art. 124K)

Basel 3.1 introduces explicit ADC (Acquisition, Development, and Construction) treatment
under Art. 124K, replacing the CRR high-risk item approach (Art. 128, omitted from UK law
by SI 2021/1078).

| Type | CRR | Basel 3.1 | Change |
|------|-----|-----------|--------|
| ADC (standard) | 100% (corporate unrated) | **150%** | Art. 128 omitted → Art. 124K(1) |
| ADC (qualifying residential, pre-sold/equity at risk) | — | **100%** | New concession (Art. 124K(2)) |
| ADC (commercial) | 100% (corporate unrated) | **150%** | No qualifying reduction available |

!!! info "Art. 124K(2) Qualifying Conditions — Residential ADC Only"
    The 100% concession requires **both**: (a) prudent underwriting standards including
    property valuation; **and** (b) at least one of: (i) legally binding pre-sale/pre-lease
    contracts with substantial forfeitable deposits covering a significant portion of total
    contracts, or (ii) the borrower has substantial equity at risk. Commercial ADC always
    receives 150% — no qualifying reduction exists.

!!! warning "ADC Exclusion from Regulatory RE"
    ADC exposures are explicitly excluded from regulatory real estate treatment (Art. 124A).
    They cannot qualify for LTV-based loan-splitting (Art. 124F–124H) or income-producing
    tables (Art. 124I). The `is_adc` flag takes priority over all other RE classification.

See also: [B31 ADC specification](../specifications/basel31/sa-risk-weights.md#real-estate--adc-exposures-art-124k)

### Retail Exposures

#### Classification Threshold

| Parameter | CRR (Art. 123(c)) | Basel 3.1 (Art. 123(1)(b)(ii)) | Change |
|-----------|-------------------|-------------------------------|--------|
| Aggregate exposure limit | EUR 1m (FX-converted) | **GBP 880,000** (fixed) | Currency-fixed |
| QRRE individual limit | EUR 100k (FX-converted) | **GBP 90,000** (Art. 147(5A)(c)) | Currency-fixed |

Under CRR, the retail threshold is EUR 1m dynamically converted to GBP at the prevailing EUR/GBP
rate (default 0.8732, yielding ~GBP 873k). Under Basel 3.1, the PRA replaces this with a fixed
**GBP 880,000** threshold — no FX conversion is required.

!!! warning "PRA deviation from BCBS"
    The BCBS framework (CRE20.65) retains EUR 1m. The PRA's fixed GBP threshold eliminates
    FX volatility from retail classification, ensuring stable portfolio boundaries regardless of
    exchange rate movements.

Both thresholds apply to the total amount owed by the obligor or connected group, **excluding**
residential real estate exposures assigned to the RE exposure class (Art. 123(c) CRR /
Art. 123(1)(b)(ii) Basel 3.1).

#### Risk Weights

| Type | CRR | Basel 3.1 | Change |
|------|-----|-----------|--------|
| Regulatory Retail QRRE | 75% | 75% | — |
| Regulatory Retail Transactor | 75% | **45%** | -30pp |
| Payroll / Pension Loans | 35% | 35% | Unchanged from CRR2 |
| Retail Other | 75% | 75% | — |

Transactor status requires full repayment each billing cycle. Payroll/pension loans (35%)
were introduced by CRR2 (Regulation (EU) 2019/876) and carried forward unchanged to Basel 3.1.
CRR Art. 123 second subparagraph → PRA PS1/26 Art. 123(4). Four conditions apply: unconditional
salary/pension deduction, insurance coverage, payments ≤ 20% of net income, maturity ≤ 10 years.

!!! warning "Code Divergence — CRR Path"
    The CRR code path does not implement the 35% payroll/pension treatment — all CRR retail
    exposures receive flat 75%. The `is_payroll_loan` flag is only checked in the Basel 3.1
    branch. See [CRR SA Risk Weights spec](../specifications/crr/sa-risk-weights.md#payroll--pension-loans-crr-art-123-crr2).

### Currency Mismatch Multiplier (CRE20.76)

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| Unhedged FX retail / residential RE | No adjustment | **1.5x RW multiplier** (max 150% RW) |

Applies when lending currency differs from borrower's income currency and the
exposure is not hedged. Distinct from the 8% FX collateral haircut in CRM.

### Subordinated Debt

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Subordinated Debt | 100-150% | **150%** (flat) |

### Equity Exposures

| Type | CRR (Art. 133(2)) | Basel 3.1 (Fully Phased) | Change |
|------|-----|--------------------------|--------|
| Standard listed equities | 100% | **250%** | +150pp |
| Higher-risk (unlisted + business < 5 years) | 100% | **400%** | +300pp |

!!! warning "Correction: Higher-Risk Definition (Fixed D1.38)"
    This table previously had two higher-risk rows ("Higher-risk (unlisted, PE, etc.)" and
    "Speculative / venture capital"). PRA PS1/26 Glossary (p.5) defines "higher risk equity
    exposure" solely as: (1) not listed on a recognised exchange AND (2) business has existed
    for less than five years. PE/VC is **not** automatically higher-risk — only if it meets
    both criteria. See [Equity Approach Specification](../specifications/basel31/equity-approach.md#higher-risk-classification-art-1334).

IRB is **removed** for equity under Basel 3.1 — SA only. The PD/LGD method (CRR Art. 155)
is blanked in the final rules.

**SA transitional phase-in schedule (Art. 4.2/4.3):**

| Year | Standard | Higher-Risk |
|------|----------|-------------|
| 2027 | 160% | 220% |
| 2028 | 190% | 280% |
| 2029 | 220% | 340% |
| 2030+ | 250% | 400% |

**IRB transitional (Art. 4.4–4.6):** Firms that had IRB permission for equities on
31 December 2026 use the **higher of**:

- the risk weight from their old IRB methodology (PD/LGD method under CRR Art. 155,
  as in force on 31 Dec 2026), and
- the transitional SA risk weight from the schedule above.

This provides a floor-based transition — IRB firms don't immediately jump to SA weights,
but cannot produce risk weights below the transitional SA schedule.

**Opt-out (Art. 4.9–4.10):** Firms may elect to skip the transitional and apply full Basel 3.1
weights immediately. This election is **irrevocable** and requires prior PRA notification.

### CIU Exposures

Basel 3.1 retains the same three approaches for CIUs as CRR, but the removal of IRB
for equity underlyings has a material impact:

| Approach | Treatment | Change from CRR |
|----------|-----------|-----------------|
| Look-through (Art. 132A(1) / 152(2)) | RW each underlying as if held directly | Equity underlyings now get **SA RWs** (250%/400%) instead of IRB PD/LGD |
| Mandate-based (Art. 132A(2) / 152(5)) | Worst-case allocation per mandate limits | Equity underlyings use SA RWs |
| Fall-back (Art. 132(2)) | **1,250%** | Unchanged from CRR2 |

!!! info "Art. 132 UK Law Status"
    CRR Art. 132 was **omitted from UK retained law** by SI 2021/1078 (effective 1 Jan 2022)
    and moved to the PRA Rulebook (CRR Firms). The 1,250% fallback originates from CRR2
    (Regulation 2019/876). PRA PS1/26 Art. 132(2) reinstates the same 1,250% fallback.

    The 1,250% fallback applies only where neither look-through nor mandate-based
    approaches are feasible. CIU equity exposures **excluded** under Art. 132B(2)
    (e.g., sovereign entities, legislative programme holdings) instead receive
    Art. 133 equity treatment (250% standard / 400% higher-risk under Basel 3.1).

!!! warning "Implementation Note"
    The calculator currently applies 150% (CRR) / 250%-400% (Basel 3.1) for
    `ciu_approach = "fallback"`, which corresponds to **Art. 133 equity weights**
    rather than the true Art. 132(2) penalty of 1,250%. This is a known code
    divergence — see [Equity Approach Specification](../specifications/crr/equity-approach.md)
    for regulatory details.

Under CRR, IRB firms could apply the **simple risk weight approach** (Art. 155(2)) to
equity underlyings in CIUs, producing lower risk weights via PD/LGD. Under Basel 3.1,
Art. 155 is removed — equity underlyings must use SA 250%/400% even when applying
look-through under IRB.

**CIU transitional (Art. 4.7–4.8):** During the 3-year transition period (2027–2029), for
firms with IRB permission on 31 December 2026, CIU equity underlyings that were subject
to the simple risk weight approach use the **higher of**:

- the old simple risk weight (CRR Art. 155(2), as in force before 1 Jan 2027), and
- the transitional SA equity weights from the schedule above.

The same opt-out (Art. 4.9–4.10) applies — firms can skip the CIU transitional alongside
the equity transitional, but the election covers both and is irrevocable.

### Defaulted Exposures

| Scenario | CRR | Basel 3.1 |
|----------|-----|-----------|
| Unsecured, provisions ≥ 20% | 100% | 100% |
| Unsecured, provisions < 20% | 150% | 150% |
| Residential RE (not cash-flow dependent) | 100-150% | **100%** (flat) |

The provision-coverage ratio determines whether a 100% or 150% risk weight applies to
the unsecured portion of defaulted exposures (CRE20.87-90). The flat 100% for defaulted
residential RE (not cash-flow dependent) is a Basel 3.1 simplification.

!!! info "Provision Threshold Denominator"
    The 20% threshold denominator differs between frameworks:

    - **CRR Art. 127(1):** "the unsecured part of the exposure value if those specific
      credit risk adjustments and deductions were not applied" — the **pre-provision
      unsecured** exposure value
    - **PRA PS1/26 Art. 127(1):** "the outstanding amount of the item or facility" —
      the **gross outstanding** amount (the full facility)

    The PRA denominator is typically larger, making it easier to reach the 20% threshold.
    See [Defaulted Exposures Specification](../specifications/basel31/defaulted-exposures.md)
    for details.

### Regional Governments and Local Authorities

Basel 3.1 introduces a tiered approach (PRA PS1/26 Art. 115):

| Type | CRR | Basel 3.1 |
|------|-----|-----------|
| Scottish/Welsh/NI governments | Sovereign-based | **0%** (treated as UK sovereign) |
| UK local authorities (GBP) | Sovereign-based | **20%** |
| Rated RGLAs | Sovereign-based | Own ECAI rating (20-150%) |
| Unrated RGLAs | Sovereign-based | Based on sovereign CQS |

### Covered Bonds (Art. 129)

!!! warning "PRA Deviation from BCBS — Rated Risk Weights Unchanged"
    BCBS CRE20.28–29 reduced rated covered bond risk weights (CQS 2: 20%→15%, CQS 4–6:
    collapsed to 50%). **PRA PS1/26 Art. 129(4) Table 7 did not adopt these reductions** — all
    six rated CQS values are identical to CRR Table 6A.

| CQS | CRR (Table 6A) | Basel 3.1 (Table 7) | Change |
|-----|----------------|---------------------|--------|
| CQS 1 | 10% | 10% | Unchanged |
| CQS 2 | 20% | 20% | Unchanged |
| CQS 3 | 20% | 20% | Unchanged |
| CQS 4 | 50% | 50% | Unchanged |
| CQS 5 | 50% | 50% | Unchanged |
| CQS 6 | 100% | 100% | Unchanged |

**Unrated (Art. 129(5)):** Risk weight is derived from the issuing institution's senior
unsecured RW. Basel 3.1 expands the derivation table from 4 to 7 entries to accommodate
new institution RWs (ECRA 30%, SCRA 40%/75%):

| Institution RW | CRR CB RW | B31 CB RW | Change |
|---------------|-----------|-----------|--------|
| 20% | 10% | 10% | Unchanged |
| 30% | — | **15%** | New (Art. 129(5)(aa)) |
| 40% | — | **20%** | New (Art. 129(5)(ab)) |
| 50% | 20% | **25%** | ↑ from 20% |
| 75% | — | **35%** | New (Art. 129(5)(ba)) |
| 100% | 50% | 50% | Unchanged |
| 150% | 100% | 100% | Unchanged |

!!! info "Art. 129(4A) — New Due Diligence Requirement"
    Basel 3.1 adds Art. 129(4A): institutions must assess whether external ratings
    adequately reflect creditworthiness. If due diligence reveals higher risk, the institution
    must assign at least one CQS step higher.

!!! success "P1.113 Fixed — B31 Rated Values"
    `B31_COVERED_BOND_RISK_WEIGHTS` now uses PRA Table 7 values (identical to CRR).
    Previously used BCBS CRE20 values (CQS 2=15%, CQS 6=50%) which understated capital.

## Credit Conversion Factors

PRA PS1/26 Art. 111 Table A1 replaces CRR Annex I with a 7-row structure. Key changes: maturity distinction removed (CRR 50%/>1yr and 20%/≤1yr merged to single 40% bucket), UCC up from 0% to 10%, and UK residential mortgage commitments carved out at 50%.

| Table A1 Row | Item Type | CRR | Basel 3.1 | Change |
|-------------|-----------|-----|-----------|--------|
| Row 1 | Full Risk — issued items (guarantees, credit derivatives) | 100% | 100% | Unchanged |
| Row 2 | Certain Drawdown (factoring, repos, forward purchases) | 100% | 100% | Renamed from Annex I para 2 |
| Row 3 | Other issued OBS items (non-credit substitute) | 50% | 50% | Unchanged |
| Row 4 | NIFs/RUFs and **UK residential mortgage commitments** | 50% | **50%** | Row 4(b) is PRA-specific |
| Row 5 | Other Commitments | 50%/20%* | **40%** | Maturity split removed |
| Row 6 | Trade LCs, warranties, performance bonds | 20% | 20% | Unchanged |
| Row 7 | Unconditionally Cancellable | 0% | **10%** | Up from 0% |

*\* CRR split by maturity: >1yr = 50% (MR), ≤1yr = 20% (MLR). Basel 3.1 replaces with flat 40% regardless of maturity.*

!!! warning "PRA Deviation — UK Residential Mortgage Commitments (Row 4(b))"
    Table A1 Row 4(b) is a **PRA-specific addition** not in the BCBS framework. Under BCBS, residential mortgage commitments would fall into "any other commitment" at **40%** (Row 5). The PRA carved them out at **50%** to prevent the maturity-distinction removal from reducing capital for irrevocable mortgage offer letters. Only applies to commitments not unconditionally cancellable (Row 7) and not certain-drawdown (Row 2). See [CCF specification](../specifications/crr/credit-conversion-factors.md#basel-31-sa-changes-pra-ps126-art-111-table-a1) for full Table A1.

### F-IRB CCF Alignment (Art. 166C)

Under CRR, F-IRB has its own supervisory CCF schedule (Art. 166(8)): **75%** for both MR
and MLR commitments, with a 20% carve-out for short-term trade LCs (Art. 166(9)). Basel 3.1
**eliminates** this separate F-IRB schedule — Art. 166C aligns F-IRB CCFs to the SA Table A1
values above.

| Risk Type | CRR F-IRB (Art. 166(8)) | Basel 3.1 F-IRB (Art. 166C = SA Table A1) | Change |
|-----------|-------------------------|-------------------------------------------|--------|
| FR / FRC | 100% | 100% | Unchanged |
| MR | 75% | **50%** | Down from 75% |
| MLR | 75% | **20%** | Down from 75% |
| OC | 0% | **40%** | New Table A1 Row 5 category |
| LR (UCC) | 0% | **10%** | Up from 0% |

!!! info "Art. 166(9) Trade LC Exception Removed"
    CRR Art. 166(9) is **blanked by PRA PS1/26**. The 20% short-term trade LC carve-out
    no longer applies under Basel 3.1 — these exposures receive the standard SA CCF for
    their risk type via the Table A1 mapping. The `is_short_term_trade_lc` flag has no
    effect under Basel 3.1.

See [CCF specification](../specifications/crr/credit-conversion-factors.md#basel-31-f-irb-changes-pra-ps126-art-166c)
for the full F-IRB CCF comparison and [IRB Approach](../user-guide/methodology/irb-approach.md#exposure-at-default-ead)
for implementation details.

## Slotting Risk Weights

### Project Finance

| Category | CRR (≥2.5yr) | CRR (<2.5yr) | Basel 3.1 |
|----------|--------------|--------------|-----------|
| Strong | 70% | 50% | 70% |
| Good | 90% | 70% | 90% |
| Satisfactory | 115% | 115% | 115% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% (EL) |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Slotting Distinction"
    BCBS CRE33.6 Table 6 defines separate elevated slotting weights for pre-operational
    project finance (Strong 80%, Good 100%, Satisfactory 120%, Weak 350%). **PRA PS1/26
    does not adopt this distinction** — all project finance uses the standard non-HVCRE
    Table A (Art. 153(5)) regardless of operational status. The pre-operational / operational
    distinction only applies under the SA approach (Art. 122B(2)(c)).

### Other Specialised Lending (OF, CF, IPRE)

| Category | CRR (≥2.5yr) | CRR (<2.5yr) | Basel 3.1 |
|----------|--------------|--------------|-----------|
| Strong | 70% | 50% | 70% |
| Good | 90% | 70% | 90% |
| Satisfactory | 115% | 115% | 115% |
| Weak | 250% | 250% | 250% |
| Default | 0% | 0% | 0% (EL) |

### HVCRE

| Category | CRR | Basel 3.1 |
|----------|-----|-----------|
| Strong | N/A | 95% |
| Good | N/A | 120% |
| Satisfactory | N/A | 140% |
| Weak | N/A | 250% |
| Default | N/A | 0% (EL) |

!!! warning "HVCRE — PRA PS1/26 Introduction, Not CRR Continuation"
    The UK onshored CRR has **no HVCRE concept**. The term "high volatility commercial real
    estate" does not appear in the UK CRR text — Art. 153(5) contains only Table 1
    (a single table for all SL types). The original EU CRR had a separate Table 2 with
    elevated HVCRE weights (Strong: 95%/70%, Good: 120%/95%, Satisfactory: 140%, Weak: 250%),
    but this was **not retained** in UK onshoring. Under UK CRR, all SL uses Table 1.

    PRA PS1/26 **introduces** HVCRE as a new sub-type in Table A (Art. 153(5)(a)(i)) with the
    higher weights shown above. This is a Basel 3.1 change with no UK CRR predecessor.

    **Code divergence (D3.22):** The calculator applies EU CRR Table 2 weights for CRR
    exposures with `is_hvcre=True`, which is more conservative than UK CRR requires.

### Slotting Subgrades — Table A Column Structure (Art. 153(5))

PRA PS1/26 restructures the CRR maturity-split tables into a single **Table A** with
7 columns. **Strong** is split into columns **A** and **B**; **Good** into **C** and **D**.
Satisfactory, Weak, and Default have a single column each.

The comparison tables above show the **default column** values (B/D). The full Table A
includes optional lower-weight columns (A/C):

| Exposure Type | Strong A | Strong B | Good C | Good D | Satisfactory | Weak | Default |
|---------------|----------|----------|--------|--------|--------------|------|---------|
| OF, CF, PF, IPRE | 50% | 70% | 70% | 90% | 115% | 250% | 0% |
| HVCRE | 70% | 95% | 95% | 120% | 140% | 250% | 0% |

**Column assignment rules (Art. 153(5)(c)–(f)):**

- **(c) Default:** Strong → column **B** (70% / 95%); Good → column **D** (90% / 120%)
- **(d) Short maturity:** If remaining maturity **< 2.5 years**, firms **may** use column **A** for Strong (50% / 70%) or column **C** for Good (70% / 95%)
- **(e) IPRE enhanced:** IPRE exposures in Strong **may** use column **A** if all criteria met: substantially stronger underwriting, very low LTV, investment-grade tenant income (≥ 100% debt service), and no ADC characteristics
- **(f) PF enhanced:** PF exposures in Strong **may** use column **A** if underwriting and characteristics are substantially stronger than required for Strong

!!! info "CRR vs PRA PS1/26 — Format Change, Non-HVCRE Values Preserved"
    Under CRR, the short-maturity concession was expressed as separate maturity bands in Table 1 (≥ 2.5yr vs < 2.5yr). PRA PS1/26 consolidates these into a single Table A with A/B/C/D subgrade columns. For non-HVCRE types, the **values are identical** — CRR "≥ 2.5yr" = Table A column B/D; CRR "< 2.5yr" = Table A column A/C. The column A/C concession is explicitly **optional** ("may") under both frameworks. The HVCRE row in Table A is a **PRA PS1/26 introduction** — UK CRR has no HVCRE table.

!!! warning "Not Yet Implemented — Column A/C Concession"
    The calculator currently assigns all Basel 3.1 slotting exposures to columns B/D (the default per Art. 153(5)(c)). The optional column A/C short-maturity concession (Art. 153(5)(d)) and enhanced-underwriting concessions (Art. 153(5)(e)/(f)) are not yet implemented. CRR maturity-based differentiation IS implemented via separate short/long maturity tables.

## SA Specialised Lending (Art. 122A-122B)

Basel 3.1 introduces explicit SA risk weights for specialised lending, separate from
the IRB slotting approach above. SA SL sits within the **corporate** exposure class
(Art. 112(1)(g), [waterfall](#exposure-class-restructuring) row 15) — it is not a
standalone exposure class.

### Definition Criteria (Art. 122A(1))

A corporate exposure qualifies as SA specialised lending if it has **all four**
characteristics (in legal form or economic substance):

1. **SPV structure** — the exposure is to an entity created specifically to finance
   and/or operate physical assets (Art. 122A(1)(a))
2. **Asset dependency** — the borrowing entity has little or no other material assets
   or activities, and therefore little or no independent capacity to repay (Art. 122A(1)(b))
3. **Lender control** — the obligation terms give the lender substantial control over
   the asset(s) and income generated (Art. 122A(1)(c))
4. **Asset income repayment** — the primary source of repayment is income generated by
   the financed asset(s), not the broader enterprise (Art. 122A(1)(d))

Art. 122A(2) classifies SA SL into three sub-types: **object finance** (OF),
**commodities finance** (CF), and **project finance** (PF).

!!! warning "IPRE Excluded from SA SL"
    Art. 122A(1) defines SA SL as "a corporate exposure that is **not a real estate
    exposure**". Income-producing real estate (IPRE) is therefore caught at waterfall
    row 7 (real estate, Art. 124–124L) rather than row 15 (corporates). IPRE follows
    Art. 124H–124I risk weight tables, not Art. 122B. See
    [Real Estate](#residential-real-estate) for RE treatment details.

### Unrated SA SL Risk Weights (Art. 122B(2))

| Type | CRR (SA) | Basel 3.1 (SA) | Art. Reference |
|------|----------|----------------|----------------|
| Object Finance | Corporate RW | **100%** | Art. 122B(2)(a) |
| Commodities Finance | Corporate RW | **100%** | Art. 122B(2)(b) |
| Project Finance (pre-operational) | Corporate RW | **130%** | Art. 122B(2)(c) |
| Project Finance (operational) | Corporate RW | **100%** | Art. 122B(2)(c) |
| Project Finance (high-quality operational) | Corporate RW | **80%** | Art. 122B(4) |

Under CRR, specialised lending under SA simply uses the corporate risk weight
(Art. 122). Basel 3.1 provides differentiated weights that recognise the specific
risk profile of each sub-type.

### Rated SA SL (Art. 122B(1))

Where a nominated ECAI issue-specific rating is available, rated SA SL exposures
fall through to the **corporate CQS risk weight table** (Art. 122(2)) — the same
table used for rated corporates. The SA SL type-specific weights above apply only
to unrated exposures.

### Operational Phase Definition (Art. 122B(3))

A project finance exposure is in the **operational phase** when the entity has:

- (a) positive net cash-flow sufficient to cover remaining contractual obligations
  for project completion; **and**
- (b) declining long-term debt.

### High-Quality PF Criteria (Art. 122B(4)–(5))

The 80% weight requires the PF exposure to be in the operational phase **and** to
satisfy all conditions in Art. 122B(5):

- (a) The entity can meet financial commitments in a timely manner, robust against
  adverse economic cycles
- (b) Eight structural conditions (Art. 122B(5)(b)(i)–(viii)):
    - (i) Restricted from acting to detriment of creditors (no additional debt without
      consent)
    - (ii) Sufficient reserve funds for contingency and working capital
    - (iii) Revenues subject to rate-of-return regulation, take-or-pay, or
      availability-based contract (defined in Art. 122B(6))
    - (iv) Revenue depends on one main counterparty rated ≤ 80% RW (sovereign, RGLA,
      PSE, MDB at 0%, international org at 0%, or corporate ≤ 80%)
    - (v) Contractual provisions provide high creditor protection on default
    - (vi) Main counterparty protects creditors from termination losses
    - (vii) All assets and contracts pledged to creditors (to extent permitted by law)
    - (viii) Creditors may assume control of the entity on default

## Credit Risk Mitigation Changes

### Method Taxonomy

Basel 3.1 restructures CRM with clearer method names and explicit applicability rules
(PRA PS1/26 Art. 191A):

| Method | CRR Name | Applies To |
|--------|----------|-----------|
| Financial Collateral Simple | Same | SA only |
| Financial Collateral Comprehensive | Same | SA + IRB |
| **Foundation Collateral Method** | Various IRB collateral articles | F-IRB |
| **Parameter Substitution Method** | Art. 236 substitution | F-IRB (unfunded) |
| **LGD Adjustment Method** | Art. 183 | A-IRB (unfunded) |

### Haircut Changes

Significant increases for equities, gold, and long-dated bonds
(CRR Art. 224 Table 4 / PRA PS1/26 Art. 224 Table 3).
Maturity bands expand from 3 to 5.

| Collateral Type | CRR | Basel 3.1 | Change |
|-----------------|-----|-----------|--------|
| Main index equities | 15% | **20%** | +5pp |
| Other listed equities | 25% | **30%** | +5pp |
| Gold | 15% | **20%** | +5pp |
| Govt bonds CQS 2-3 (10y+) | 6% | **12%** | +6pp |
| Corp bonds CQS 1 (10y+) | 8% | **12%** | +4pp |
| Corp bonds CQS 2-3 (5-10y / 10y+) | 12% | **15%** | +3pp |

CRR maturity bands: 0-1y, 1-5y, 5y+.
Basel 3.1 maturity bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+.

See [Supervisory Haircut Comparison](technical-reference.md#supervisory-haircut-comparison)
for the full haircut tables across all maturity bands.

### Volatility Scaling and Non-Daily Revaluation (Art. 226)

When collateral is revalued less frequently than daily, supervisory haircuts must be
scaled up using a square-root-of-time formula. The non-daily revaluation formula is
**unchanged** between CRR and Basel 3.1:

```
H = H_m × sqrt((N_R + T_m − 1) / T_m)
```

Where `N_R` is the number of business days between revaluations and `T_m` is the
liquidation period. For weekly revaluation (N_R = 5) on a 10-day holding period, this
increases haircuts by ~22% (`sqrt(14/10) ≈ 1.183`).

The structural change under Basel 3.1 is the **removal of Art. 225** (own-estimates
approach for volatility adjustments). The liquidation period scaling formula previously
in Art. 225(2)(c) is relocated to Art. 226(2):

| Aspect | CRR | Basel 3.1 | Change |
|--------|-----|-----------|--------|
| Non-daily revaluation | Art. 226 | Art. 226(1) | Unchanged (renumbered) |
| Liquidation period scaling | Art. 225(2)(c) | Art. 226(2) | Moved |
| Own-estimates volatility | Art. 225 | — | **Removed** |

!!! warning "Not Yet Implemented — Art. 226(1)"
    Non-daily revaluation adjustment is not implemented in either framework. No
    `revaluation_frequency_days` input field exists. Haircuts are understated for
    collateral not marked-to-market daily. See
    [B31 CRM spec](../specifications/basel31/credit-risk-mitigation.md#art-2261--non-daily-revaluation-adjustment)
    for full formula and variable definitions.

See [Volatility Scaling](technical-reference.md#volatility-scaling-art-226) for
developer-facing formula details and code references.

### Overcollateralisation (Foundation Collateral Method)

| Collateral Type | Overcoll. Ratio | Minimum EAD Coverage |
|-----------------|-----------------|---------------------|
| Financial | 1.0x | None |
| Receivables | 1.25x | None |
| RE / Other Physical | 1.4x | 30% of EAD |

### Unfunded Credit Protection

New requirement: unfunded credit protection must not be unilaterally **cancellable or
changeable** by the protection provider (Art. 213(1)(c)(i)). The "or change" condition is
new in Basel 3.1. Transitional relief for contracts entered before 1 January 2027 until
June 2028 waives the "or change" requirement for legacy contracts.

## Impact Analysis

### Low-Risk Portfolios (Strong IRB Models)

```
Scenario: High-quality corporate portfolio
- PD: 0.10%
- LGD: 40%
- SA RW equivalent: 80%

CRR:
- IRB K: ~2%
- IRB RW: ~25% (after 1.06)
- Capital saving vs SA: 69%

Basel 3.1:
- IRB K: ~1.9% (no scaling)
- IRB RW: ~24%
- Floor: 80% × 72.5% = 58%
- Final RW: 58%
- Capital saving vs SA: 28%
```

### SME Portfolio

```
Scenario: £5m SME exposure, 100% SA RW

CRR:
- SME Factor: 0.811
- Effective RW: 81.1%
- Saving: 18.9%

Basel 3.1:
- SME Factor: None
- Effective RW: 100%
- Saving: 0%
```

### Infrastructure Project

```
Scenario: Qualifying infrastructure, 100% SA RW

CRR:
- Infrastructure Factor: 0.75
- Effective RW: 75%
- Saving: 25%

Basel 3.1:
- Infrastructure Factor: None
- Effective RW: 100%
- Saving: 0%
```

## Configuration Comparison

=== "CRR"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
    )

    # Internally sets:
    # - scaling_factor: 1.06
    # - output_floor: None
    # - pd_floor: 0.0003 (uniform)
    # - lgd_floors: None
    ```

=== "Basel 3.1"

    ```python
    from datetime import date
    from rwa_calc.contracts.config import CalculationConfig

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1),
    )

    # Internally sets:
    # - scaling_factor: 1.0 (removed)
    # - output_floor: 72.5%
    # - pd_floors: differentiated by class
    # - lgd_floors: by collateral type
    ```

## Summary of Capital Impact

| Exposure Type | CRR → Basel 3.1 Impact |
|---------------|------------------------|
| Low-risk IRB | **Increase** (output floor) |
| SME | **Increase** (factor removal) |
| Infrastructure | **Increase** (factor removal) |
| Equity | **Increase** (250%/400% from 100%) |
| Unhedged FX Retail/RE | **Increase** (1.5x multiplier) |
| High LTV Mortgages | **Decrease** (better SA RWs) |
| Low LTV Mortgages | **Decrease** (better SA RWs) |
| High-risk Corporate | Neutral (PRA retains CQS 5 at 150%; BCBS reduced to 100% but PRA did not adopt) |
| Retail Transactor | **Decrease** (45% from 75%) |
| Standard Corporate | Neutral |

## Transition Planning

### Key Dates

| Date | Event |
|------|-------|
| Sep 2024 | PRA PS1/26 published |
| 2025-2026 | Parallel running recommended |
| 1 Jan 2027 | Basel 3.1 effective |
| 2027-2030 | Output floor phase-in (PRA 4-year schedule) |

### Recommended Actions

1. **Impact Assessment**: Run calculations under both frameworks
2. **Data Quality**: Ensure LTV data available for SA RE
3. **Model Updates**: Review IRB models for floor compliance
4. **Process Changes**: Update reporting for dual calculation

## See Also

- [CRR Details](../user-guide/regulatory/crr.md) — current framework in depth
- [Basel 3.1 Details](../user-guide/regulatory/basel31.md) — future framework in depth
- [Reporting Differences](reporting-differences.md) — COREP template changes
- [Impact Analysis](impact-analysis.md) — comparison tooling and capital attribution
- [Technical Reference](technical-reference.md) — developer-facing parameter specification
- [Configuration Guide](../user-guide/configuration.md) — setting up both frameworks
