# Basel 3.1 Framework Differences

Key differences from CRR including output floor, PD/LGD floors, and removal of supporting factors.

**Regulatory Reference:** PRA PS1/26

---

## Overview

Basel 3.1 (effective 1 January 2027 in the UK) introduces significant changes to the credit risk framework. The calculator supports both regimes via a configuration toggle.

## Key Differences

| Parameter | CRR (Current) | Basel 3.1 | Reference |
|-----------|---------------|-----------|-----------|
| RWA Scaling Factor | 1.06 | Removed | — |
| SME Supporting Factor | 0.7619 / 0.85 | Removed | CRR Art. 501 |
| Infrastructure Factor | 0.75 | Removed | CRR Art. 501a |
| Output Floor | None | 72.5% of SA | PRA PS1/26 |
| PD Floor | 0.03% (all classes) | Differentiated | CRE30.55 |
| A-IRB LGD Floors | Portfolio-level only (Art. 164(4)) | Per-exposure input floors (by collateral type) | CRE30.41 |
| Slotting Risk Weights | Maturity-differentiated | HVCRE-differentiated (no pre-op distinction) | PRA PS1/26 |

## Differentiated PD Floors (Basel 3.1)

PRA PS1/26 Art. 160(1) (corporate, sovereign, institution) and Art. 163(1) (retail):

| Exposure Class | PD Floor | Reference |
|---------------|----------|-----------|
| Corporate | 0.05% | Art. 160(1) |
| Corporate SME | 0.05% | Art. 160(1) |
| Sovereign | 0.05% | Art. 160(1) |
| Institution | 0.05% | Art. 160(1) |
| Retail Mortgage | 0.10% | Art. 163(1)(b) |
| Retail Other | 0.05% | Art. 163(1)(c) |
| QRRE (Transactors) | 0.05% | Art. 163(1)(c) |
| QRRE (Revolvers) | 0.10% | Art. 163(1)(a) |

!!! warning "Sovereign Row is Regulatory Dead Letter (Art. 147A(1)(a))"
    Sovereign exposures (Art. 147(2)(a)) are **restricted to the Standardised Approach** by
    Art. 147A(1)(a); F-IRB and A-IRB are both unavailable and PS1/26 provides no grandfathering
    or transitional carve-out. The sovereign PD floor row above is retained for completeness
    and CRR cross-reference only and cannot bind on any live Basel 3.1 exposure.

    Institutions (Art. 147(2)(b)) are capped at F-IRB by Art. 147A(1)(b) (A-IRB unavailable;
    SA applies only where permission has been granted under Art. 148 or Art. 150). The 0.05%
    institution PD floor applies normally to F-IRB institution exposures.

    See the [IRB Approach Restrictions](key-differences.md#irb-approach-restrictions) section
    for the full Art. 147A(1) class mapping.

## A-IRB LGD Floors (Basel 3.1)

**Corporate / Institution (Art. 161(5)):**

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10%* |
| Commercial real estate | 10%* |
| Residential real estate | 10%* |
| Other physical | 15%* |

!!! note "No senior/subordinated distinction"
    Art. 161(5)(a) sets a flat 25% floor for **all** corporate unsecured exposures. Unlike F-IRB supervisory LGD (which distinguishes non-FSE senior 40% / FSE senior 45% / subordinated 75%), A-IRB LGD floors have no subordinated uplift.

**Retail (Art. 164(4)):**

| Exposure Type | Collateral | LGD Floor | Sub-paragraph |
|---------------|------------|-----------|---------------|
| Residential RE mortgage (flat) | RE secured | 5% | Art. 164(4)(a) |
| QRRE (transactor and revolver) | Unsecured | 50% | Art. 164(4)(b)(i) |
| Other retail | Unsecured | 30% | Art. 164(4)(b)(ii) |
| Other retail (LGDU in LGD* formula) | Partially unsecured | 30% | Art. 164(4)(c)(iii) |
| Other retail | Financial collateral | 0% | Art. 164(4)(c)(iv)(1) |
| Other retail | Receivables | 10%* | Art. 164(4)(c)(iv)(2) |
| Other retail | Immovable property (CRE / RRE as collateral) | 10%* | Art. 164(4)(c)(iv)(3) |
| Other retail | Other physical | 15%* | Art. 164(4)(c)(iv)(4) |

!!! info "Secured-retail blended floor (Art. 164(4)(c))"
    For retail exposures outside the flat-5% RRE mortgage path, the LGD floor is the
    variable LGD\* produced by the Foundation Collateral Method (Art. 230 single-collateral
    or Art. 231 multi-collateral), with LGDU = 30% and the LGDS values above substituted
    into the blended formula:

    ```
    LGD_floor = (E_u / E) x 30% + sum_i (E_s_i / E) x LGDS_i
    ```

    The canonical 8-row table and formula derivation live in the
    [B31 A-IRB spec](../specifications/basel31/airb-calculation.md#retail-a-irb-lgd-floors-art-1644).
    Art. 164(4A) additionally requires Art. 193(7) multi-facility collateral allocation
    when the same collateral backs multiple facilities.

!!! note "CRR comparison (Art. 164(4), pre-revocation)"
    CRR used **portfolio exposure-weighted-average** floors: ≥ 10% for retail RRE-secured,
    ≥ 15% for retail CRE-secured, excluding central-government-guaranteed exposures.
    Basel 3.1 replaces these aggregate tests with the per-exposure input floors above
    applied individually before the capital formula.

*Values reflect PRA PS1/26 implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%).

## F-IRB Supervisory LGD (Art. 161)

### Art. 161 LGD Values

| Exposure Type | CRR | Basel 3.1 | Reference |
|---------------|-----|-----------|-----------|
| Financial Sector Entity (Senior) | 45% | 45% | Art. 161(1)(a) |
| Other Corporate/Institution (Senior) | 45% | 40% | Art. 161(1)(aa) |
| Corporate/Institution (Subordinated) | 75% | 75% | Art. 161(1)(b) |
| Covered Bonds | 11.25% | 11.25% | Art. 161(1)(d) → Art. 161(1B) |
| Senior purchased corporate receivables | 45% | 40% | Art. 161(1)(e) |
| Subordinated purchased corporate receivables | 100% | 100% | Art. 161(1)(f) |
| Dilution risk | 75% | 100% | Art. 161(1)(g) |

### Art. 230 LGDS Values (Secured Portions)

| Collateral Type | CRR LGDS (Senior) | CRR LGDS (Sub.) | Basel 3.1 LGDS | Reference |
|----------------|-------------------|-----------------|----------------|-----------|
| Financial Collateral | 0% | 0% | 0% | Art. 230 Table 5 / Art. 230(2) |
| Receivables | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.9 |
| CRE/RRE | 35% | 65% | 20% | Art. 230 Table 5 / CRE32.10-11 |
| Other Physical | 40% | 70% | 25% | Art. 230 Table 5 / CRE32.12 |

!!! note "FSE Distinction — New in Basel 3.1"
    Basel 3.1 Art. 161(1)(aa) reduces the senior unsecured LGD from 45% to 40% for non-FSE
    corporates only. Financial sector entities (Art. 4(1)(27)) retain 45% under Art. 161(1)(a),
    reflecting higher observed loss severity for financial institution defaults. Institutions are
    implicitly FSEs. See [Key Differences](key-differences.md#f-irb-supervisory-lgd) for change
    summary.

!!! info "Purchased Receivables and Dilution Risk (Art. 161(1)(e)–(g))"
    Basel 3.1 recasts the triggering condition of each sub-paragraph. CRR Art. 161(1)(e)/(f)
    apply where "the institution is not able to estimate PDs or the institution's PD estimates
    do not meet the requirements set out in Section 6", and Art. 161(1)(g) applies
    unconditionally. PS1/26 re-anchors each trigger to the specific Art. 160 PD-determination
    method:

    | Sub-paragraph | CRR trigger | PS1/26 trigger | LGD (CRR → PS1/26) |
    |---------------|-------------|----------------|--------------------|
    | 161(1)(e) senior | unable to estimate PDs / Section 6 fail | PD per **Art. 160(2)(a)** (EL ÷ LGD) | 45% → 40% |
    | 161(1)(f) subordinated | unable to estimate PDs / Section 6 fail | PD per **Art. 160(2)(b)** (PD = EL) | 100% → 100% |
    | 161(1)(g) dilution | unconditional | PD per **first sentence of Art. 160(6)** | 75% → 100% |

    Art. 160(2)'s chapeau preserves the CRR "not able to estimate PDs / Section 6 fail" trigger
    as the precondition for using 160(2)(a)/(b), so the substance of when (e)/(f) apply is
    unchanged; only the drafting is cascaded through Art. 160. PS1/26 Art. 161(2)(a) also adds
    a new explicit A-IRB → F-IRB LGD mapping absent in CRR. See
    [CRR F-IRB spec](../specifications/crr/firb-calculation.md#art-1611-lgd-values) and
    [B31 F-IRB spec](../specifications/basel31/firb-calculation.md#supervisory-lgd-art-161)
    for the full Art. 161(1)(a)–(g) breakdown.

!!! info "B31 Art. 230 — Subordinated LGDS Distinction Removed"
    CRR Art. 230 Table 5 has separate "senior" and "subordinated" LGDS columns (e.g.,
    receivables 35% senior / 65% subordinated). PRA PS1/26 Art. 230(2) replaces this with a
    single LGDS per collateral type with no subordinated distinction. Under Basel 3.1, the
    subordination effect is captured solely through the LGDU term (75%, Art. 161(1)(b)).

## Output Floor

The output floor ensures IRB RWA cannot fall below a percentage of what the SA would produce:

```
RWA_final = max(RWA_IRB, floor_percentage x RWA_SA)
```

### Transitional Schedule (PRA PS1/26 Art. 92 para 5)

The PRA compressed the BCBS 6-year phase-in to a 4-year schedule:

| Year | Floor Percentage |
|------|-----------------|
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

Note: Art. 92 para 5 says institutions "may apply" these transitional rates — they are
permissive. Firms can voluntarily use 72.5% from day one.

### Output Floor Adjustment (OF-ADJ)

The full output floor formula from PRA PS1/26 Art. 92(2A) is:

```
TREA = max{U-TREA; x × S-TREA + OF-ADJ}
```

Where:

- **U-TREA** = un-floored total risk exposure amount (Art. 92(3))
- **S-TREA** = standardised total risk exposure amount (Art. 92(3A)) — calculated without IRB, SFT VaR, SEC-IRBA, IAA, IMM, or IMA
- **x** = floor percentage (see transitional schedule above)
- **OF-ADJ** = `12.5 × (IRB_T2 – IRB_CET1 – GCRA + SA_T2)`

The OF-ADJ reconciles the different treatment of provisions under IRB and SA:

| Component | Description | Regulatory Ref |
|-----------|-------------|----------------|
| IRB_T2 | IRB excess provisions T2 credit (provisions > EL), capped at 0.6% of IRB RWAs | Art. 62(d) |
| IRB_CET1 | IRB EL shortfall CET1 deductions (EL > provisions) + Art. 40 additional deductions | Art. 36(1)(d), Art. 40 |
| GCRA | General credit risk adjustments in T2, gross of tax effects, capped at **1.25% of S-TREA** | Art. 62(c), Art. 92(2A) |
| SA_T2 | SA general credit risk adjustments T2 credit | Art. 62(c) |

Under IRB, EL shortfall adds to capital requirements (CET1 deduction) while excess provisions
provide T2 relief. Under SA, general credit risk adjustments provide T2 relief directly. The
12.5 multiplier converts own-funds amounts to risk-weighted equivalents. Without this adjustment,
the floor comparison would not be on a like-for-like basis.

For COREP template mapping of OF-ADJ components, see the
[output reporting spec](../specifications/output-reporting.md#output-floor-adjustment-of-adj).

### Entity-Type Carve-Outs (Art. 92(2A)(b)–(d))

The output floor does **not** apply universally. Art. 92(2A) specifies which entity/basis
combinations must use the floored TREA formula; all others use U-TREA directly:

**Floor applies (Art. 92(2A)(a)):**

- Standalone UK institution — individual basis
- Ring-fenced body in sub-consolidation group — sub-consolidated basis
- CRR consolidation entity (not international subsidiary) — consolidated basis

**Exempt — use U-TREA only (Art. 92(2A)(b)–(d)):**

- **(b)** Non-ring-fenced institution — sub-consolidated basis
- **(c)** Ring-fenced body in sub-consolidation group; non-standalone UK institution — individual basis
- **(d)** CRR consolidation entity that is an international subsidiary — consolidated basis

!!! info "Implementation"
    Set `institution_type` and `reporting_basis` on `OutputFloorConfig` to activate the carve-out
    logic. When both are `None`, the floor defaults to applicable. See the
    [output floor spec](../specifications/basel31/output-floor.md#entity-type-carve-outs) for the
    full applicability table.

## Supervisory Haircut Comparison

### CRR Haircuts (3 maturity bands)

| Collateral Type | 0-1y | 1-5y | 5y+ |
|-----------------|------|------|-----|
| Govt bonds CQS 1 | 0.5% | 2% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 6% |
| Corp bonds CQS 1 | 1% | 4% | 8% |
| Corp bonds CQS 2-3 | 2% | 6% | 12% |
| Main index equities | 15% | — | — |
| Other equities | 25% | — | — |
| Gold | 15% | — | — |
| Cash | 0% | — | — |

### Basel 3.1 Haircuts (5 maturity bands)

PRA PS1/26 Art. 224 Table 3 (10-day holding period):

| Collateral Type | 0-1y | 1-3y | 3-5y | 5-10y | 10y+ |
|-----------------|------|------|------|-------|------|
| Govt bonds CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 4% | 6% | **12%** |
| Corp bonds CQS 1 | 1% | 4% | 6% | **10%** | **12%** |
| Corp bonds CQS 2-3 | 2% | 6% | 8% | **15%** | **15%** |
| Main index equities | **20%** | — | — | — | — |
| Other equities | **30%** | — | — | — | — |
| Gold | **20%** | — | — | — | — |
| Cash | 0% | — | — | — | — |

Currency mismatch haircut remains 8% under both frameworks (CRR Art. 224 / CRE22.54).

## Volatility Scaling (Art. 226)

Supervisory haircuts from Art. 224 assume daily revaluation and a 10-day holding period.
Two scaling adjustments may apply:

### Art. 226(2) — Liquidation Period Scaling

Scales haircuts between holding periods (e.g., 10-day table value to 5-day repo period):

```
H_m = H_n × sqrt(T_m / T_n)
```

| Variable | Definition |
|----------|-----------|
| T_m | Liquidation period for the transaction type |
| T_n | Reference period from haircut table (10 days for Art. 224 Table 3) |
| H_n | Table haircut at period T_n |
| H_m | Scaled haircut at period T_m |

| Transaction Type | T_m | Scaling Factor (vs 10-day) |
|-----------------|-----|---------------------------|
| Repo / SFT | 5 days | × 0.707 (`sqrt(0.5)`) |
| Capital market | 10 days | × 1.000 (no scaling) |
| Secured lending | 20 days | × 1.414 (`sqrt(2)`) |

**Implementation:** `scale_haircut_for_liquidation_period()` in `data/tables/haircuts.py`;
applied via `liquidation_period_days` column in `engine/crm/haircuts.py`.

### Art. 226(1) — Non-Daily Revaluation Adjustment

When collateral is revalued less frequently than daily, an additional scaling applies
**on top of** the liquidation period adjustment:

```
H = H_m × sqrt((N_R + T_m − 1) / T_m)
```

| Variable | Definition |
|----------|-----------|
| H | Final volatility adjustment to apply |
| H_m | Haircut after liquidation period scaling (daily revaluation basis) |
| N_R | Actual number of business days between revaluations |
| T_m | Liquidation period (business days) |

**Example:** Government bond CQS 1 (0-1y), weekly revaluation (N_R = 5), repo (T_m = 5):

- Table haircut (10-day): 0.5%
- After Art. 226(2): 0.5% × sqrt(5/10) = 0.354%
- After Art. 226(1): 0.354% × sqrt((5 + 5 - 1)/5) = 0.354% × 1.342 = **0.475%**

!!! warning "Not Yet Implemented"
    Art. 226(1) non-daily revaluation scaling is not implemented. No
    `revaluation_frequency_days` schema field exists. All haircuts assume daily
    revaluation (N_R = 1). See IMPLEMENTATION_PLAN.md P1.101.

### CRR vs Basel 3.1 Structural Change

CRR Art. 226 was a single (unnumbered) article covering non-daily revaluation only.
The liquidation period scaling formula was in Art. 225(2)(c) (own-estimates approach).
PRA PS1/26 removes Art. 225 entirely (own-estimates approach no longer permitted) and
restructures Art. 226 into two numbered paragraphs: (1) non-daily revaluation, (2)
liquidation period scaling. The formulas themselves are unchanged.

See [CRR CRM spec](../specifications/crr/credit-risk-mitigation.md#volatility-scaling-crr-art-226)
and [B31 CRM spec](../specifications/basel31/credit-risk-mitigation.md#volatility-scaling-art-226)
for full regulatory text.

## SA Residential Real Estate Risk Weights (Basel 3.1)

Basel 3.1 replaces CRR Art. 125 (flat 35% up to 80% LTV) with two distinct residential RE treatments:

**General (not income-dependent) — Art. 124F: Loan-Splitting**

- Secured portion (up to **55% of property value**) → **20%** RW
- Residual portion → **counterparty RW** (75% for individuals per Art. 124L)

**Income-producing (cash-flow dependent) — Art. 124G, Table 6B: Whole-Loan**

| LTV | ≤50% | 50–60% | 60–70% | 70–80% | 80–90% | 90–100% | >100% |
|-----|------|--------|--------|--------|--------|---------|-------|
| RW  | 30%  | 35%    | 40%    | 50%    | 60%    | 75%     | 105%  |

!!! info "Junior Charge Multiplier (Art. 124G(2))"
    Where prior-ranking charges exist that the institution does not hold, the Table 6B risk
    weight is multiplied by **1.25×** when LTV > 50%. At LTV ≤ 50% the 30% weight applies
    without uplift. The multiplied weight is **not capped** — it may exceed 105%
    (e.g. 105% × 1.25 = **131.25%** at LTV > 100% with a junior charge).
    **Example:** junior charge at 75% LTV → 50% × 1.25 = **62.5%** whole-loan.
    CRR has no equivalent junior-charge mechanism for residential RE (Art. 125 applies flat
    35% regardless of lien position).
    See [key-differences](key-differences.md#residential-real-estate) for the full CRR vs
    Basel 3.1 comparison.

## SA Commercial Real Estate Risk Weights (Basel 3.1)

Basel 3.1 replaces CRR Art. 126 (proportion-based split: 50% on portion up to 50% MV,
counterparty RW on excess — applied uniformly to all CRE) with entity-type-differentiated
treatment under Art. 124H:

| Counterparty Type | Treatment | Risk Weight | Reference |
|-------------------|-----------|-------------|-----------|
| Natural person / SME | Loan-splitting | 60% secured (≤55% LTV) + counterparty RW residual | Art. 124H(1)–(2) |
| Other (large corporate, institution) | Whole-loan | max(60%, min(counterparty RW, income-producing RW)) | Art. 124H(3) |
| Income-dependent (any counterparty) | Whole-loan LTV table | 100% (≤80%) / 110% (>80%) | Art. 124I |

!!! info "Art. 124H(3) — Large Corporate CRE"
    The Art. 124H(3) path applies to the **entirety** of the exposure — no portion-based splitting.
    The `income_producing_rw` in the formula is the Art. 124I rate for the same LTV band.
    The calculator routes automatically when `cp_is_natural_person = False` and `is_sme = False`.
    See [key-differences](key-differences.md#commercial-real-estate) for the full CRR vs Basel 3.1
    comparison.

Exposures failing Art. 124A qualifying criteria fall to Art. 124J: 150% (income-dependent),
counterparty RW (residential non-income-dependent), or max(60%, counterparty RW) (commercial
non-income-dependent).

## Slotting Risk Weights (Basel 3.1)

PRA PS1/26 Art. 153(5) Table A defines two slotting weight tables — non-HVCRE and HVCRE:

### Non-HVCRE (OF, CF, PF, IPRE)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
| Default | 0% (EL) |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Slotting Table"
    BCBS CRE33.6 Table 6 defines separate elevated slotting weights for pre-operational
    project finance (Strong 80%, Good 100%, Satisfactory 120%, Weak 350%). **PRA PS1/26
    does not adopt this distinction** — all project finance uses the standard non-HVCRE
    table regardless of operational status. The pre-operational / operational distinction
    only applies under the SA approach (Art. 122B(2)(c): 130% pre-op, 100% operational,
    80% high-quality operational).

### HVCRE

!!! info "HVCRE — Introduced by PRA PS1/26"
    UK CRR has no HVCRE concept — Art. 153(5) contains only Table 1 for all SL types.
    HVCRE is **newly introduced** by PRA PS1/26 Table A. See
    [Key Differences](key-differences.md#hvcre) for details and code divergence note.

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |
| Default | 0% (EL) |

### Slotting Subgrades (Table A Columns A/B/C/D)

PRA PS1/26 Art. 153(5) Table A splits **Strong** into columns A and B, and **Good** into
columns C and D:

| Exposure Type | Strong A | Strong B | Good C | Good D | Satisfactory | Weak | Default |
|---------------|----------|----------|--------|--------|--------------|------|---------|
| OF, CF, PF, IPRE | 50% | 70% | 70% | 90% | 115% | 250% | 0% |
| HVCRE | 70% | 95% | 95% | 120% | 140% | 250% | 0% |

**Column B/D** is the default assignment (Art. 153(5)(c)). Column A/C may be used when:

- **< 2.5yr** remaining maturity (Art. 153(5)(d)) — optional for all SL types
- **IPRE** Strong meets **all four** sub-conditions of Art. 153(5)(e): (i) substantially stronger underwriting, (ii) very low LTV, (iii) investment-grade income stream *including* tenant income ≥ 100% of the obligor's debt service obligations, and (iv) no ADC characteristics
- **PF** Strong meets Art. 153(5)(f) — substantially stronger underwriting and characteristics; no additional quantitative sub-conditions

For non-HVCRE types, the values are identical to CRR — PRA restructured the format from
maturity-split tables to A/B/C/D columns but preserved all risk weight values. The HVCRE row
is a PRA PS1/26 introduction (UK CRR has no HVCRE table). See [Key Differences](key-differences.md#slotting-subgrades-table-a-column-structure-art-1535) for the full comparison and [Slotting Approach spec](../specifications/basel31/slotting-approach.md#subgrade-treatment-table-a-columns-abcd) for implementation details.

!!! warning "Not Yet Implemented — Column A/C Concession (Non-HVCRE and HVCRE)"
    The Basel 3.1 calculator assigns every slotting exposure to columns B/D, regardless
    of HVCRE status or remaining maturity. Short-maturity concessions in both sub-tables
    are absent: non-HVCRE uses col B/D values instead of A/C (IMPLEMENTATION_PLAN P1.97);
    HVCRE uses col B/D values instead of A/C (P1.117 — Strong 95% instead of 70%, Good
    120% instead of 95%). CRR short-maturity differentiation is fully implemented.

## Financial Institution Correlation Multiplier (Art. 153(2))

The 1.25x correlation multiplier applies to exposures to **financial institutions** only (not non-financial corporates):

- **Large financial sector entities (LFSEs)** — regulated FSEs meeting a total-assets threshold
  that is framework-specific (see table below).
- **Unregulated financial sector entities** — regardless of size.

| Framework | LFSE threshold | Citation |
| --- | --- | --- |
| CRR | Total assets ≥ **EUR 70 billion** | CRR Art. 142(1)(4) |
| Basel 3.1 | Total assets ≥ **GBP 79 billion** | PRA PS1/26 Glossary p. 78 (Note: "corresponds to Article 142(1)(4) of CRR") |

!!! info "Threshold precision differs between frameworks"
    PS1/26 fixes the LFSE threshold as a **GBP 79 billion** absolute value in its Glossary;
    this is not an FX conversion of the CRR EUR 70 billion figure and will not fluctuate with
    exchange rates. The BCBS standard (CRE31.5) sets the international baseline at
    **USD 100 billion**, but the PRA's UK implementation uses GBP 79bn — treat USD 100bn as
    the BCBS-only number, not the applicable UK threshold. Under CRR the threshold remains
    EUR 70 billion per Art. 142(1)(4), converted to GBP via the configured EUR/GBP rate.

This multiplier is already implemented via the `requires_fi_scalar` flag in the classifier and `_polars_correlation_expr()` in the IRB formulas. It applies under both CRR and Basel 3.1 frameworks.

!!! warning "Code divergence: Basel 3.1 threshold not enforced in engine"
    `src/rwa_calc/contracts/config.py` defines `RegulatoryThresholds.basel_3_1()` with
    `lfse_total_assets_threshold = Decimal("0")` — the GBP 79 billion value is **not**
    currently held in code. The Basel 3.1 calculator relies exclusively on the upstream
    `apply_fi_scalar` flag on the counterparty record; firms are responsible for determining
    LFSE status against the GBP 79 billion threshold prior to ingest. Tracked as code-side
    finding (D3.58 / IMPLEMENTATION_PLAN.md).

Note: There is no separate "large corporate" correlation multiplier for non-financial corporates in either the BCBS standard or PRA PS1/26. See [key-differences.md § Financial Sector Correlation Multiplier](key-differences.md#financial-sector-correlation-multiplier) for the parallel CRR/B31 comparison and the distinction from the Art. 147A(1)(e) GBP 440m revenue approach restriction.

## Credit Conversion Factors (Art. 111 Table A1)

PRA PS1/26 replaces CRR Annex I with a 7-row Table A1. Key changes: CRR maturity-based commitment split (50%/>1yr, 20%/≤1yr) replaced by flat 40% "other commitments" bucket; UCC from 0% to 10%; F-IRB CCFs aligned to SA (Art. 166C). UK residential mortgage commitments carved out at **50%** (Row 4(b)) — a PRA-specific addition preventing the maturity-removal from reducing capital for irrevocable mortgage offers (BCBS would assign 40%). See [CCF specification](../specifications/crr/credit-conversion-factors.md#basel-31-sa-changes-pra-ps126-art-111-table-a1) for full Table A1.

### A-IRB CCF Floor (CRE32.27)

A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type.

## Post-Model Adjustments (Art. 146(3), 153(5A), 154(4A), 158(6A))

Basel 3.1 introduces mandatory post-model adjustments (PMAs) — conservative overlays on
A-IRB model outputs with no CRR equivalent. PMAs address material model non-compliance
without requiring full model re-estimation.

### Components

| Component | Formula | Article |
|-----------|---------|---------|
| Mortgage RW floor | `RW = max(RW_modelled, mortgage_rw_floor)` | Art. 154(4A)(b) |
| General RWA scalar | `RWEA_adj = RWEA × (1 + pma_rwa_scalar)` | Art. 153(5A) / 154(4A)(a) |
| EL scalar | `EL_adj = EL × (1 + pma_el_scalar)` | Art. 158(6A) |

The mortgage RW floor default is **10%** for UK residential mortgage exposures (PRA supervisory
parameter). The general scalars are set per model via `PostModelAdjustmentConfig`.

### Sequencing (Mandatory)

Art. 154(4A) prescribes a strict ordering:

1. **Step 1 — Mortgage floor** (Art. 154(4A)(b)): Floor the modelled risk weight
2. **Step 2 — PMA scalar** (Art. 154(4A)(a)): Scale the floor-adjusted RWEA

The PMA scalar amplifies the post-floor RWEA, not the raw model output. Reversing the
order would produce incorrect results because the scalar would inflate a sub-floor RW
before the floor is applied.

### EL Monotonicity (Art. 158(6A))

```
EL_adjusted >= EL_unadjusted
```

PMAs cannot decrease expected loss. The `pma_el_scalar` must be ≥ 0, ensuring conservative
RWA overlays do not inadvertently reduce EL shortfall calculations (Art. 159).

### Defaulted EL — BEEL Substitution (Art. 158(5))

| Approach | Defaulted EL amount | Source |
|----------|---------------------|--------|
| F-IRB defaulted | `1 × LGD × EAD` | Standard Art. 158(5) formula with PD = 1 |
| A-IRB defaulted | `BEEL × EAD` | Art. 158(5) closing proviso |

**BEEL** (Best Estimate of Expected Loss) is the A-IRB firm's own estimate of post-default
economic loss, estimated under the Art. 181(1)(h)(ii) standards. The substitution applies
**only** to the A-IRB Pool C EL amount in the Art. 159 comparison; the A-IRB capital
formula `K = max(0, LGD − BEEL)` (Art. 154(1)(i)) uses BEEL in the RW structure
separately. Pre-revocation CRR used the symbol `ELBE`; PS1/26 renames to `BEEL` with no
substantive change. Sovereigns and other Art. 147A(1)(a) quasi-sovereign classes are
excluded from A-IRB, so BEEL never arises for them.

See the [Defaulted Exposures spec — BEEL](../specifications/basel31/defaulted-exposures.md#beel-best-estimate-of-expected-loss-art-1585-art-1811hii)
for estimation standards and required inputs.

### Output Floor Interaction

PMAs are included in the un-floored TREA (U-TREA) used for the output floor comparison.
They cannot be avoided by flooring to SA — the floor applies to the post-PMA total.

See the [A-IRB specification](../specifications/basel31/airb-calculation.md#post-model-adjustments-art-1463-1544a-1586a) for the complete implementation detail and COREP column mapping.

## IRB Effective Maturity (Art. 162)

PRA PS1/26 substantially rewrites Art. 162. The most significant structural change is the
**deletion of F-IRB fixed supervisory maturities** — all IRB firms must now calculate M.

| Aspect | CRR | Basel 3.1 | Change |
|--------|-----|-----------|--------|
| F-IRB fixed maturities (§1) | 0.5yr repo / 2.5yr other | **Deleted** | All IRB firms calculate M |
| Scope | A-IRB only (Art. 143) | F-IRB and A-IRB (Art. 147A) | Expanded |
| Cash-flow schedule (§2A(a)) | `M = max(1, min(Σ(t×CF_t)/Σ(CF_t), 5))` | Same | Unchanged |
| Revolving exposures (§2A(k)) | Repayment date of current drawing | **Max contractual termination date** | Increases M |
| Mixed MNA (§2A(da)) | Not addressed | **10-day floor** | New |
| Purchased receivables min M (§2A(e)) | 90 days | **1 year** | Raised |
| Collateral daily condition (§2A(c)/(d)) | Re-margining **and** revaluation | Re-margining **or** revaluation | Wider scope |
| SME simplification (§4) | Available (EUR 500m threshold) | **Deleted** | Removed |
| One-day floor (§3) | Daily remargined + revalued repos/derivatives | Same (with OR condition) | Unchanged |
| Floor | 1 year (general) | 1 year (general) | Unchanged |
| Cap | 5 years | 5 years | Unchanged |

The revolving maturity change (Art. 162(2A)(k)) typically increases M for revolving
facilities, leading to higher maturity adjustments and therefore higher capital. The deletion
of the F-IRB 0.5-year repo maturity means repo exposures will use the full cash-flow or
contractual calculation, generally increasing M from 0.5 to ≥ 1 year.

!!! warning "Revolving Facility Precedence — (k) over (a)"
    Art. 162(2)(c) mandates that "where an exposure falls within both points (a) and (k)
    of paragraph 2A, it shall calculate M in accordance with point (k) of paragraph 2A."
    Art. 162(2A)(k) further states that "for revolving exposures, M shall be determined
    using the maximum contractual termination date of the facility. An institution shall
    not use the repayment date of the current drawing."

    This precedence rule means a revolving facility **cannot** fall back to the cash-flow
    schedule formula in (a), even when an explicit CF schedule exists — M is anchored to
    the facility termination date. The calculator reads this via the
    `facility_termination_date` input field; when non-null and the exposure is flagged
    revolving, (k) is applied in preference to any cash-flow path.

    Full precedence chain under Art. 162(2): (g)/(h) > (b), (c), (d), (da); (c) > (b);
    (k) > (a). See the [Basel 3.1 F-IRB spec](../specifications/basel31/firb-calculation.md#art-1622a-calculation-methods)
    for the method table and implementation notes.

!!! info "One-Day Floor Exceptions (Art. 162(3))"
    Both CRR and Basel 3.1 allow a **one-day** maturity floor (overriding the general 1-year
    floor) for daily-margined repos, derivatives, and margin lending, plus qualifying
    short-term exposures (FX settlement, trade finance ≤ 1yr, securities settlement). Basel 3.1
    widens the trigger condition from re-margining **and** revaluation to re-margining **or**
    revaluation. See the [CRR F-IRB spec](../specifications/crr/firb-calculation.md#art-1623--one-day-maturity-floor-exceptions)
    for the full qualifying exposure list.

See the [CRR F-IRB specification](../specifications/crr/firb-calculation.md#effective-maturity-crr-art-162)
and [Basel 3.1 F-IRB specification](../specifications/basel31/firb-calculation.md#effective-maturity-art-162)
for full regulatory text and implementation details.

## Configuration

Switch between frameworks using the configuration factory:

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR (current)
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Basel 3.1
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```
