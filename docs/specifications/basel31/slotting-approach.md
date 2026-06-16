# Slotting Approach Specification

Basel 3.1 revised risk weights for specialised lending slotting categories, with subgrade
maturity differentiation and no separate pre-operational project finance distinction.

**Regulatory Reference:** PRA PS1/26 Art. 147(8), Art. 153(5), CRE33
**Test Group:** B31-E

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-5.1 | Revised slotting risk weight tables (subgrade maturity differentiation) | P0 | Done |
| FR-5.2 | No separate pre-operational PF table (PRA deviation from BCBS) | P0 | Done |
| FR-5.3 | HVCRE elevated risk weights | P0 | Done |
| FR-5.4 | Default category EL treatment (0% RW) | P0 | Done |

---

## Overview

Basel 3.1 revises the specialised lending slotting approach risk weights. The key changes are:

1. **Maturity differentiation preserved via subgrades** — PRA PS1/26 Art. 153(5) Table A uses
   A/B columns (Strong) and C/D columns (Good) to preserve maturity-based differentiation.
   Column A/C (short maturity < 2.5yr) may be used optionally; column B/D (standard, >= 2.5yr)
   is the default assignment per Art. 153(5)(c).
2. **No pre-operational PF distinction** — PRA does not adopt the BCBS separate table for
   pre-operational project finance (CRE33.6 Table 6); all PF uses the standard non-HVCRE table
3. **HVCRE introduced** — elevated weights for high-volatility commercial real estate

!!! warning "Correction: PRA Retains Maturity Differentiation"
    This section previously stated "maturity split removed" and "flat weights regardless of
    maturity". This was **wrong** — it described the BCBS CRE33 approach, not the PRA PS1/26
    approach. PRA PS1/26 Art. 153(5)(c)-(d) preserves maturity-based differentiation through
    the subgrade column structure (A/B for Strong, C/D for Good). See
    [Subgrade Treatment](#subgrade-treatment-table-a-columns-abcd) for full details.

### Key Changes from CRR

| Category | CRR (< 2.5yr / ≥ 2.5yr) | Basel 3.1 (B/D default) | Basel 3.1 (A/C short maturity) | Change |
|----------|--------------------------|-------------------------|-------------------------------|--------|
| Strong | 50% / 70% | 70% | 50% | Same structure, subgrade columns |
| Good | 70% / 90% | 90% | 70% | Same structure, subgrade columns |
| Satisfactory | 115% / 115% | 115% | 115% | Unchanged |
| Weak | 250% / 250% | 250% | 250% | Unchanged |
| Default | 0% (EL) / 0% (EL) | 0% (EL) | 0% (EL) | Unchanged |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Table"
    BCBS CRE33.6 Table 6 defines separate elevated weights for pre-operational project finance
    (80%/100%/120%/350%). The PRA **does not adopt** this distinction — all project finance uses
    the standard non-HVCRE table regardless of operational status. This is confirmed by the
    absence of a separate pre-operational table in PRA PS1/26.

---

## Risk Weight Tables

### Non-HVCRE Specialised Lending (PF, IPRE, OF, CF)

**Art. 153(5), Table A**

Applies to: Project Finance, Income-Producing Real Estate, Object Finance, Commodities Finance.
Default assignment uses column B (Strong) / D (Good) per Art. 153(5)(c). Short maturity
(< 2.5yr) may use column A (Strong) / C (Good) per Art. 153(5)(d).

| Slotting Category | RW (>= 2.5yr, col B/D) | RW (< 2.5yr, col A/C) | EL (>= 2.5yr, col B) | EL (< 2.5yr, col A) |
|-------------------|------------------------|------------------------|----------------------|---------------------|
| Strong | 70% | 50% | 0.4% | 0% |
| Good | 90% | 70% | 0.8% | 0.4% |
| Satisfactory | 115% | 115% | 2.8% | 2.8% |
| Weak | 250% | 250% | 8.0% | 8.0% |
| Default | 0% | 0% | 50.0% | 50.0% |

### HVCRE Specialised Lending

**Art. 153(5), HVCRE Table**

!!! info "HVCRE Introduced by PRA PS1/26"
    HVCRE is **newly introduced** by PRA PS1/26 Art. 153(5) Table A. The UK onshored CRR
    has no HVCRE concept — Art. 153(5) contains only Table 1 (a single table for all SL types).
    The original EU CRR had a separate Table 2, but it was not retained in UK onshoring.
    See [CRR Slotting spec](../crr/slotting-approach.md#table-1-art-1535) for details.

High-Volatility Commercial Real Estate receives elevated weights to reflect the higher risk profile.
Default assignment uses column B (Strong) / D (Good) per Art. 153(5)(c). Short maturity
(< 2.5yr) may use column A (Strong) / C (Good) per Art. 153(5)(d).

| Slotting Category | RW col A (Strong < 2.5yr) | RW col B (Strong default) | RW col C (Good < 2.5yr) | RW col D (Good default) | EL col A | EL col B | EL col C | EL col D |
|-------------------|---------------------------|---------------------------|--------------------------|--------------------------|----------|----------|----------|----------|
| Strong | 70% | 95% | — | — | 0.4% | 0.4% | — | — |
| Good | — | — | 95% | 120% | — | — | 0.4% | 0.4% |
| Satisfactory | 140% | 140% | 140% | 140% | 2.8% | 2.8% | 2.8% | 2.8% |
| Weak | 250% | 250% | 250% | 250% | 8.0% | 8.0% | 8.0% | 8.0% |
| Default | 0% | 0% | 0% | 0% | 50.0% | 50.0% | 50.0% | 50.0% |

Read together with Table A (RW) and Table B (EL) verbatim from PS1/26 Appendix 1
pp. 103 and 108: HVCRE risk weights split A/B for Strong (70%/95%) and C/D for Good
(95%/120%), but HVCRE expected loss is flat at 0.4% across all four subgrade columns
(A=B=C=D=0.4%). The subgrade structure is therefore present in RW but **collapses on
the EL side** for HVCRE only — non-HVCRE retains the EL split (col A=0%/0.4%,
col B=0.4%, col C=0.4%, col D=0.8%).

!!! info "HVCRE Short-Maturity Subgrades — Implemented (Art. 153(5)(d), P1.117 closed)"
    HVCRE Table A has distinct short-maturity values in columns A and C (Strong A = 70%,
    Good C = 95%) — see the same rows above. The calculator now honours these: the b31
    pack supplies a distinct `slotting_rw_hvcre_short` entry, and
    `engine/slotting/transforms.py::lookup_rw` fires the `weights["hvcre_short"]` branch
    when `is_short` is set for an HVCRE exposure (with `is_short_maturity` derived from
    `remaining_maturity < 2.5`). Short-maturity HVCRE Strong exposures therefore receive
    70% (col A) and Good exposures 95% (col C). See
    [Subgrade Treatment](#subgrade-treatment-table-a-columns-abcd) below for the
    consolidated column A/C behaviour covering both HVCRE and non-HVCRE.

!!! quote "Art. 158(6) Table B — verbatim (PS1/26 Appendix 1 p. 108)"
    Rating grades: Strong (A | B), Good (C | D), Satisfactory, Weak, Default

    | Exposure | A | B | C | D | Satisfactory | Weak | Default |
    |----------|---|---|---|---|--------------|------|---------|
    | Object finance | 0% | 0.4% | 0.4% | 0.8% | 2.8% | 8% | 50% |
    | Project finance | 0% | 0.4% | 0.4% | 0.8% | 2.8% | 8% | 50% |
    | Commodities finance | 0% | 0.4% | 0.4% | 0.8% | 2.8% | 8% | 50% |
    | IPRE | 0% | 0.4% | 0.4% | 0.8% | 2.8% | 8% | 50% |
    | HVCRE | 0.4% | 0.4% | 0.4% | 0.4% | 2.8% | 8% | 50% |

!!! note "HVCRE EL — No Maturity Split AND No Strong/Good Differentiation"
    Unlike non-HVCRE, the HVCRE EL row in PRA PS1/26 Art. 158(6) Table B is flat
    (no < 2.5yr / >= 2.5yr distinction) **and** Strong and Good both carry the same
    0.4% rate — see the verbatim quote above. The HVCRE row reads
    0.4% / 0.4% / 0.4% / 0.4% / 2.8% / 8% / 50% across columns
    A | B | C | D | Satisfactory | Weak | Default. The subgrade differentiation
    collapses on the EL side even though risk weights (Table A) still carry distinct
    subgrade values (col A = 70%, col B = 95%, col C = 95%, col D = 120%).

!!! warning "Resolved 2026-04-18 (P1.150)"
    Prior versions of this table and the underlying constants used HVCRE Good = 0.8%,
    mirroring non-HVCRE long-maturity. That was wrong; PRA PS1/26 Table B HVCRE row
    is flat at 0.4% across both Strong and Good. The EL shortfall for HVCRE Good
    exposures was overstated by a factor of two before this fix.

!!! note "HVCRE vs Non-HVCRE"
    HVCRE is distinguished from standard CRE by the volatility of the underlying property
    cash flows and the speculative nature of the development. The classification is determined
    during the hierarchy/classification stage based on the `specialised_lending_type` input field.

### Subgrade Treatment (Table A Columns A/B/C/D)

PRA PS1/26 Art. 153(5) Table A uses subgrade columns for **Strong** (columns A and B) and
**Good** (columns C and D). Satisfactory, Weak, and Default have single columns. The full
Table A structure:

| Exposure Type | Strong A | Strong B | Good C | Good D | Satisfactory | Weak | Default |
|---------------|----------|----------|--------|--------|--------------|------|---------|
| OF, CF, PF, IPRE | 50% | 70% | 70% | 90% | 115% | 250% | 0% |
| HVCRE | 70% | 95% | 95% | 120% | 140% | 250% | 0% |

**Column assignment rules (Art. 153(5)(c)–(f)):**

- **(c) Default:** Strong → column **B**; Good → column **D**; Satisfactory and Weak use
  their single columns. These are the risk weights in the non-HVCRE and HVCRE tables above.
- **(d) Short maturity:** If remaining maturity **< 2.5 years**, firms **may** assign column
  **A** (Strong) or **C** (Good) instead — providing lower risk weights. Available for
  **all** specialised lending categories (OF, CF, PF, IPRE, HVCRE).
- **(e) IPRE enhanced:** IPRE Strong exposures **may** use column **A** if **all four**
  sub-conditions (i)–(iv) are met — see verbatim quote below. The test combines (i) an
  underwriting-quality bar, (ii) a very-low-LTV bar, (iii) an investment-grade **income
  stream** bar that expressly **includes** tenant income ≥ 100% of the obligor's debt
  service obligations, and (iv) exclusion of ADC (land acquisition, development and
  construction of commercial real estate) characteristics.
- **(f) PF enhanced:** PF Strong exposures **may** use column **A** if the institution's
  underwriting and the exposure's other characteristics are substantially stronger than
  required by the Strong rating grade. Unlike (e), Art. 153(5)(f) contains **no**
  quantitative sub-conditions — it is a single substance-over-form test.

!!! quote "Art. 153(5)(c)–(f) — verbatim (PS1/26 Appendix 1 pp. 102–103)"
    **(c)** subject to points (d) to (f) of this paragraph an institution shall:

    - (i) assign the relevant risk weight in column B of Table A to exposures assigned to
      the 'Strong' rating grade;
    - (ii) assign the relevant risk weight in column D of Table A to exposures assigned to
      the 'Good' rating grade;
    - (iii) assign the relevant risk weight in the 'Satisfactory' column of Table A to
      exposures assigned to the 'Satisfactory' rating grade; and
    - (iv) assign the relevant risk weight in the 'Weak' column of Table A to exposures
      assigned to the 'Weak' rating grade.

    **(d)** an institution may, for all categories of specialised lending exposures, if
    less than 2.5 years remain until maturity of an exposure:

    - (i) for exposures assigned to the 'Strong' rating grade: assign the relevant risk
      weight in column A of Table A to the exposure instead of the risk weight in column
      B of Table A; and
    - (ii) for exposures assigned to the 'Good' rating grade: assign the relevant risk
      weight in column C of Table A to the exposure instead of the risk weight in column
      D of Table A;

    **(e)** an institution may, for IPRE exposures assigned to the 'Strong' rating grade,
    assign the relevant risk weight in column A of Table A to the exposure instead of the
    risk weight in column B of Table A if:

    - (i) the institution's underwriting of the exposure and the exposure's other
      characteristics are substantially stronger than required by the 'Strong' rating
      grade;
    - (ii) the loan to value ratio is very low for the property type;
    - (iii) the income stream on which the repayment of the obligation depends is
      consistent with that which the institution would reasonably expect for an investment
      grade exposure, including that the tenant income from the property is at least 100%
      of the obligor's debt service obligations; and
    - (iv) the exposure does not finance the land acquisition, development and
      construction ('ADC') of commercial real estate;

    **(f)** an institution may, for project finance exposures assigned to the 'Strong'
    rating grade, assign the relevant risk weight in column A of Table A to the exposure
    instead of the risk weight in column B of Table A if the institution's underwriting
    of the exposure and the exposure's other characteristics are substantially stronger
    than required by the 'Strong' rating grade;

!!! info "Asymmetry between (e) and (f) — why IPRE carries four tests but PF only one"
    Art. 153(5)(e) overlays three **additional** quantitative tests on top of the
    substantial-strength bar in (i): LTV floor (ii), investment-grade income-stream /
    tenant-coverage test (iii), and ADC exclusion (iv). Art. 153(5)(f) stops at the
    substantial-strength bar alone. The difference reflects IPRE's dependence on
    identifiable property-level cash flows (tenant income, LTV) — which lend themselves to
    hard quantitative gates — whereas project-finance cash flows derive from a sponsor's
    completed project and are evaluated holistically in the slotting factor lists
    (Appendix 1 List 2). Firms cannot import the (e)(ii)–(iv) tests into (f) by analogy.

!!! warning "Art. 153(5)(e)(iii) — the income-stream test is not just 'tenant ≥ 100%'"
    A common paraphrase of (e)(iii) reduces it to "investment-grade tenant income (≥ 100%
    debt service)". That conflates two requirements. The **primary** test is that the
    income stream on which repayment depends is consistent with an investment-grade
    exposure — the tenant-income coverage at ≥ 100% of the **obligor's** (not the
    property's) debt service obligations is one component ("including that...") of that
    broader investment-grade test, not the whole test. A property with a single
    non-investment-grade tenant paying 110% of debt service would fail (e)(iii) despite
    clearing the numerical threshold.

!!! info "PRA vs BCBS — Maturity Differentiation Preserved"
    BCBS CRE33 removes maturity-based differentiation entirely and uses flat risk weights.
    PRA PS1/26 **retains** the maturity-based differentiation from CRR by structuring Table A
    with A/B/C/D columns. The values are identical to the CRR maturity-split tables
    (CRR "≥ 2.5yr" = column B/D; CRR "< 2.5yr" = column A/C). Column A/C assignment is
    explicitly optional ("may") under Art. 153(5)(d)–(f).

!!! info "Column A/C Concession — Maturity Subgrades Implemented; Enhanced-Underwriting Concession Outstanding"
    Maturity-based column A/C assignment is now implemented for Basel 3.1 slotting via
    `engine/slotting/transforms.py::lookup_rw`, which dispatches on `is_short`
    (`is_short_maturity` derived from `remaining_maturity < 2.5`) against distinct
    short-maturity weight entries supplied by the b31 pack:

    - **Non-HVCRE short maturity (P1.97 closed):** the b31 pack supplies a
      `slotting_rw_short` entry; `lookup_rw` fires `weights["short"]` for short-dated
      non-HVCRE exposures. Short-dated Strong receives 50% (col A) and Good 70% (col C).
    - **HVCRE short maturity (P1.117 closed):** the b31 pack supplies a
      `slotting_rw_hvcre_short` entry; `lookup_rw` fires `weights["hvcre_short"]` for
      short-dated HVCRE exposures. Short-dated Strong receives 70% (col A) and Good
      95% (col C).
    - **Enhanced-underwriting concessions** (Art. 153(5)(e) IPRE, Art. 153(5)(f) PF)
      remain **not implemented** — no input field exists to mark an exposure as meeting
      the enhanced-criteria threshold.

    CRR maturity-based differentiation is implemented the same way, via the crr pack's
    `slotting_rw_short` / `slotting_rw_hvcre_short` entries read by the CRR branch of
    `lookup_rw`.

## Default Category (0% RW, EL Treatment)

For defaulted specialised lending exposures assigned to the Default slotting category:

- Risk weight = **0%** (no capital charge via RWA)
- Expected loss = **50%** of EAD
- The capital impact is captured through the EL shortfall/excess mechanism (Art. 159),
  not through the risk weight

This treatment is unchanged from CRR.

## Routing to Slotting

Under Basel 3.1, exposures are routed to slotting based on specialised lending type:

**IPRE / HVCRE (Art. 147A(2)):** Must use slotting. These sub-types cannot use F-IRB or A-IRB
under Basel 3.1 (unless the firm has specific A-IRB approval, which is rare).

**PF, OF, CF:** Routed to slotting when:

1. The exposure is classified as specialised lending
2. The firm does **not** have A-IRB permission for the sub-class
3. The firm has F-IRB or slotting permission — PF/OF/CF may use F-IRB if the firm has F-IRB
   permission and can estimate PD

If the firm has A-IRB permission for the specific SL sub-class, the exposure may use A-IRB
instead of slotting (see [Model Permissions](model-permissions.md)).

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-E1 | PF Strong, operational | 70% |
| B31-E2 | IPRE Good | 90% |
| B31-E3 | IPRE Weak | 250% |
| B31-E4 | HVCRE Strong | 95% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-E: Slotting Approach | E1–E4 | 13 | 100% (13/13) |
