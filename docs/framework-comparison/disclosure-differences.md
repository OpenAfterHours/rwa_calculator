# Disclosure Differences

Under Basel 3.1, Pillar III credit risk disclosure templates are renamed from the **UK** prefix
to **UKB** and undergo structural changes reflecting the new regulatory framework. This page
summarises the key differences. For complete column and row definitions, see the
[full Pillar III disclosure specification](../features/pillar3-disclosures.md).

## Template Overview

| Template | CRR Name | Basel 3.1 Name | Purpose |
|----------|----------|----------------|---------|
| **OV1** | UK OV1 | UKB OV1 | Overview of RWEAs |
| **CR4** | UK CR4 | UKB CR4 | SA exposure & CRM effects |
| **CR5** | UK CR5 | UKB CR5 | SA risk weight allocation |
| **CR6** | UK CR6 | UKB CR6 | IRB exposures by PD range |
| **CR6-A** | UK CR6-A | UKB CR6-A | Scope of IRB/SA use |
| **CR7** | UK CR7 | UKB CR7 | Credit derivatives effect on RWEA |
| **CR7-A** | UK CR7-A | UKB CR7-A | Extent of CRM techniques (IRB) |
| **CR8** | UK CR8 | UKB CR8 | RWEA flow statements (IRB) |
| **CR9** | UK CR9 | UKB CR9 | IRB back-testing of PD per exposure class |
| **CR9.1** | UK CR9.1 | UKB CR9.1 | IRB back-testing where Art. 180(1)(f) ECAI mapping applies |
| **CR10** | UK CR10 | UKB CR10 | Slotting approach exposures |

---

## Structural Summary

| Area | CRR (UK templates) | Basel 3.1 (UKB templates) |
|------|-------------------|--------------------------|
| **Naming prefix** | UK (e.g., UK CR6) | UKB (e.g., UKB CR6) |
| **OV1 equity rows** | Row UK 4a (equity simple RW) | Rows 11-14 (IRB transitional, CIU fund approaches) |
| **OV1 output floor** | Not applicable | Row 26 (floor multiplier), row 27 (floor adjustment) |
| **OV1 pre-floor ratios** | Not applicable | Rows 4a, 5a-b, 6a-b, 7a-b |
| **CR5 risk weight columns** | 15 buckets (a-o) | 29 buckets (a-ac) — adds 14 granular weights |
| **CR5 exposure breakdown** | Total only (p, q) | Total + on-BS/off-BS/avg CCF/total (ad-ae, ba-bd) |
| **CR6 PD allocation** | Based on estimated PD | Based on **pre-input-floor** PDs |
| **CR6 RWEA** | Includes supporting factors | Includes **post-model adjustments**; no supporting factors |
| **CR6 F-IRB breakdown** | Corporates: SME, SL, other | F-IRB: institutions + 4 corporate sub-classes (**SL, financial+large, SME, non-SME**); A-IRB: 3 corporate sub-classes + 7 retail sub-classes — see [CR6 sub-template structure](#cr6-sub-template-structure-firb-vs-airb) |
| **CR6-A row structure** | By exposure class (Art. 147) | By **roll-out class** (Art. 147B) |
| **CR7 approach categories** | F-IRB, A-IRB (2 subtotals) | F-IRB, A-IRB, **slotting** (3 subtotals) |
| **CR7-A columns** | a-n (14 columns) | a-p (**16 columns** — adds slotting FCP/UFCP) |
| **CR7-A CRM basis** | Pre-CCF | **Post-conversion-factor** basis |
| **CR7-A financial collateral** | Financial collateral only | Includes **on-balance sheet netting** |
| **CR7-A retail RE split** | "Secured by immovable property" | **Residential** vs **commercial** immovable property |
| **CR7-A new rows** | — | **Purchased receivables** (corporate and retail) |
| **CR10 sub-templates** | 5 (PF, IPRE+HVCRE, OF, CF, equity) | 5 (PF, IPRE, OF, CF, **HVCRE**) — equity removed |
| **CR10 RWEA** | After supporting factors | **No supporting factors** |
| **Supporting factors** | Reflected in CR6 col j, CR10 col e | **Removed** throughout |

---

## OV1 — Overview of RWEAs

### Row Changes

| Change | Row(s) | Description |
|--------|--------|-------------|
| **Removed** | UK 4a | Equities under simple risk-weighted approach |
| **Added** | 11 | Equity positions under IRB Transitional Approach |
| **Added** | 12 | Equity investments in funds — look-through approach |
| **Added** | 13 | Equity investments in funds — mandate-based approach |
| **Added** | 14 | Equity investments in funds — fall-back approach |
| **Added** | 4a | Total RWEAs (pre-floor) |
| **Added** | 5a-b, 6a-b, 7a-b | Pre-floor capital ratios (CET1, Tier 1, Total) |
| **Added** | 26 | Output floor multiplier |
| **Added** | 27 | Output floor adjustment |

---

## CR4 — SA Exposure & CRM Effects

### Row Changes

| Change | Description |
|--------|-------------|
| **Added** | "Of which: specialised lending" under corporates (Art. 122A-122B) |
| **Added** | "Of which: residential RE — not materially dependent" (Art. 124F, 124J(2)) |
| **Added** | "Of which: residential RE — materially dependent" (Art. 124G, 124J(1)) |
| **Added** | "Of which: commercial RE — not materially dependent" (Art. 124H, 124J(3)) |
| **Added** | "Of which: commercial RE — materially dependent" (Art. 124I, 124J(1)) |
| **Added** | "Of which: land acquisition, development and construction" (Art. 124K) |

Column structure unchanged (a-f).

---

## CR5 — SA Risk Weight Allocation

### Column Changes

| Change | Col(s) | Description |
|--------|--------|-------------|
| **Expanded** | a-ac | 29 risk weight buckets (was a-o, 15 buckets). Adds 15%, 25%, 30%, 40%, 45%, 60%, 65%, 80%, 85%, 105%, 110%, 130%, 135%, 400%. Removes 370%. |
| **Renamed** | ad | Total (was col p) |
| **Renamed** | ae | Of which: unrated (was col q) |
| **Added** | ba | On-BS exposure amount (pre-CF/CRM) |
| **Added** | bb | Off-BS exposure amount (pre-CF) |
| **Added** | bc | Weighted average conversion factor |
| **Added** | bd | Total post CF and CRM |

### Reporting Rules

- Regulatory RE (not dependent on cash flows): reported in two parts — portion up to 55%
  LTV and portion above 55% LTV
- Currency mismatch exposures: reported against the risk weight that would apply
  *without* the 1.5x multiplier, but RWEA reflects the multiplier
- Equity exposures under transitional provisions: reported against end-state SA risk
  weights, but RWEA reflects transitional provisions

---

## CR6 — IRB Exposures by PD Range

### Column Changes

| Change | Col(s) | Description |
|--------|--------|-------------|
| **Changed** | a | PD bucket allocation uses **pre-input-floor** PDs (was estimated PD) |
| **Changed** | f | Weighted average PD uses **post-input-floor** PDs (Art. 160(1), 163(1)) |
| **Changed** | h | LGD includes **input floors** (Art. 161(5), 164(4)) |
| **Changed** | j | RWEA includes **post-model adjustments**, mortgage RW floor; no supporting factors |
| **Changed** | l | Expected loss includes **post-model adjustments** (Art. 158(6A)) |

### Row Changes

| Change | Description |
|--------|-------------|
| **Added** | F-IRB: financial corporates and large corporates (Art. 147(2)(c)(ii)) |
| **Added** | A-IRB retail: commercial immovable property (SME/non-SME) |
| **Changed** | Slotting exposures **excluded** (was included under corporates — now in CR10) |
| **Removed** | Supporting factor adjustments from RWEA |

### CR6 sub-template structure (FIRB vs AIRB)

Under UKB CR6 the institution discloses a **separate template per
exposure-class category**, with each category closed off by a "Total"
row. The FIRB and AIRB category lists are **not symmetric** — they
diverge in three ways: FIRB carries an institutions sub-template that
AIRB does not, AIRB carries a retail sub-template that FIRB does not,
and the corporate sub-class breakdown differs (FIRB has a fourth
"financial corporates and large corporates" sub-row that AIRB lacks).

The lists below are taken verbatim from PRA PS1/26 Annex XXII
(`docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`),
pp. 6–7.

=== "FIRB sub-templates"

    | # | Sub-template | Article reference |
    |---|--------------|-------------------|
    | **1.** | Institutions | Art. 147(2)(b) |
    | **2.** | Corporates | Art. 147(2)(c) |
    | **2.1** | Specialised lending (incl. SL exposures subject to slotting) | Art. 147(2)(c)(i) |
    | **2.2** | Financial corporates and large corporates | Art. 147(2)(c)(ii) |
    | **2.3** | Other general corporates — SMEs | Art. 147(2)(c)(iii) read with Glossary SME definition |
    | **2.4** | Other general corporates — non-SMEs | Art. 147(2)(c)(iii), residual to 2.3 |
    | **3.** | Total | — |

=== "AIRB sub-templates"

    | # | Sub-template | Article reference |
    |---|--------------|-------------------|
    | **1.** | Corporates | Art. 147(2)(c) |
    | **1.1** | Specialised lending | Art. 147(2)(c)(i) |
    | **1.2** | Other general corporates — SMEs | Art. 147(2)(c)(iii) read with Glossary SME definition |
    | **1.3** | Other general corporates — non-SMEs | Art. 147(2)(c)(iii), residual to 1.1 / 1.2 |
    | **2.** | Retail | Art. 147(2)(d) |
    | **2.1** | Secured by residential immovable property — SMEs | Art. 147(2)(d)(ii) read with Glossary SME definition |
    | **2.2** | Secured by residential immovable property — non-SMEs | Art. 147(2)(d)(ii), residual to 2.1 |
    | **2.3** | Secured by commercial immovable property — SMEs | Art. 147(2)(d), residual to 2.1 / 2.2 |
    | **2.4** | Secured by commercial immovable property — non-SMEs | Art. 147(2)(d), residual to 2.1 / 2.2 / 2.3 |
    | **2.5** | Qualifying revolving retail exposures (QRRE) | Art. 147(2)(d)(i) |
    | **2.6** | Other — SMEs | Art. 147(2)(d) |
    | **2.7** | Other — non-SMEs | Art. 147(2)(d)(iii), residual to 2.6 |
    | **3.** | Total | — |

!!! warning "FIRB and AIRB CR6 row structures are not interchangeable"

    Three asymmetries should be highlighted to anyone consuming UKB CR6:

    1. **Institutions appear only under FIRB.** Exposures to
       institutions (Art. 147(2)(b)) are not eligible for A-IRB under
       PRA PS1/26 Art. 147A — there is no A-IRB institutions
       sub-template. Mapping a CRR "institutions" disclosure into a
       UKB CR6 AIRB section is a category error.
    2. **Retail appears only under AIRB.** Retail exposures
       (Art. 147(2)(d)) are A-IRB-only under Basel 3.1; there is no
       FIRB retail sub-template. The AIRB retail breakdown also gains
       commercial-RE SME/non-SME rows (2.3, 2.4) that did not exist in
       the legacy CRR template.
    3. **Corporates differ by one sub-class.** FIRB has **four**
       corporate sub-classes (SL, financial+large, SME, non-SME);
       AIRB has **three** (SL, SME, non-SME). The "financial
       corporates and large corporates" sub-row at FIRB 2.2
       (Art. 147(2)(c)(ii)) has **no AIRB counterpart** — under
       PRA PS1/26 financial corporates and large corporates are
       restricted to F-IRB (see [Model Permissions](../specifications/basel31/model-permissions.md)).

    Numerically: FIRB produces **6** numbered rows (1, 2, 2.1, 2.2,
    2.3, 2.4) plus a Total; AIRB produces **12** numbered rows (1,
    1.1, 1.2, 1.3, 2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7) plus a Total.
    Re-using a single row-key map across both approaches will silently
    mis-align sub-class numbering.

    The same FIRB / AIRB asymmetry applies to UKB CR9 — see the
    [General Reporting Rules](#cr9-irb-back-testing-of-pd-per-exposure-class)
    bullet on F-IRB and A-IRB sub-templates.

---

## CR6-A — Scope of IRB/SA Use

### Row Changes

| Change | Description |
|--------|-------------|
| **Changed** | Row structure based on **roll-out classes** (Art. 147B) instead of exposure classes |
| **Changed** | IRB approach column includes F-IRB, A-IRB, and slotting (no longer includes equity simple RW) |

### Column Definitions (UKB CR6-A, cols a–e)

The 5-column structure is fixed; column labels match the legacy CRR template, but
the underlying definitions differ. Definitions below are taken verbatim from PRA
PS1/26 Annex XXII (Pillar III IRB disclosure instructions), pages 7–9.

| Col | Column | Definition (UKB CR6-A) |
|-----|--------|------------------------|
| **a** | IRB exposure value | Exposure value as defined in **Article 166A to 166D** of the Credit Risk: Internal Ratings Based Approach (CRR) Part for exposures subject to the Internal Ratings Based Approach. Disclosed per roll-out class. |
| **b** | Total exposure value (SA + IRB) | Total exposure value in accordance with **Article 429(4)** of the Leverage Ratio (CRR) Part, including exposures under both the SA and the IRB approach, for each roll-out class. |
| **c** | % subject to permanent partial use of SA | Percentage of the total exposure value for each roll-out class that is subject to the SA in accordance with a permission granted under **Article 150(1)** of the Credit Risk: Internal Ratings Based Approach (CRR) Part. Calculated as (SA exposure value for the roll-out class) ÷ (col b). |
| **d** | % subject to IRB approach | Percentage of the total exposure value for each roll-out class that is subject to the IRB approach (under permission granted under Rule 1.1 and **Article 143(1)**). Includes A-IRB, F-IRB and **slotting** exposures. Calculated as (IRB exposure value for the roll-out class) ÷ (col b). |
| **e** | % subject to a roll-out plan | Percentage of the total exposure value for each roll-out class subject to an IRB roll-out plan in accordance with **Article 148(1)**. Numerator includes exposures **currently subject to the SA** where the institution's roll-out plan states it intends to apply the A-IRB, F-IRB or slotting approach. Calculated as (roll-out plan exposure value for the roll-out class) ÷ (col b). |

Source: PRA PS1/26 Annex XXII — Credit Risk IRB Disclosure Instructions
(`docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`),
paragraphs 3–6 and column-reference table, pp. 7–9.

!!! warning "Column labels are stable, definitions are not"

    Readers comparing legacy **UK CR6-A** (CRR) to **UKB CR6-A** (Basel 3.1) must
    not assume column-by-column equivalence. Specifically:

    - **Col a** — CRR cited *Article 166* (single article, F-IRB exposure value);
      Basel 3.1 cites the new *Articles 166A–166D* sub-divisions covering F-IRB
      exposure value, A-IRB EAD, F-IRB CCFs, and A-IRB CCFs respectively.
    - **Col d** — CRR's "% subject to IRB" included **equity under the simple
      risk-weighted approach**; Basel 3.1 removes equity IRB entirely (equity is
      SA-only at 250%/400% — see [Key Differences](key-differences.md)) and
      instead includes **slotting** exposures alongside F-IRB / A-IRB.
    - **Cols c, d, e denominators** — both versions use col b, but col b's
      population in Basel 3.1 is bucketed by **roll-out class** (Art. 147B), not
      by exposure class (Art. 147), so the same numerical percentage describes
      a different sub-population.

    Cross-mapping a CRR CR6-A row directly into a UKB CR6-A row by column
    position will produce mis-stated percentages.

---

## CR7 — Credit Derivatives Effect on RWEA

| Change | Description |
|--------|-------------|
| **Added** | Slotting as third approach category with its own subtotal row |
| **Changed** | Rows restructured: F-IRB (rows 1-3), A-IRB (rows 4-6), slotting (row 7), total (row 8) |

---

## CR7-A — Extent of CRM Techniques

### Column Changes

| Change | Col(s) | Description |
|--------|--------|-------------|
| **Changed** | b | Financial collateral now includes **on-balance sheet netting** (Art. 219) |
| **Added** | o | Part of exposure covered by funded CP — slotting only (FCCM + netting) |
| **Added** | p | Part of exposure covered by unfunded CP — slotting only |

!!! warning "PDF labelling typo — Annex XXII p. 14"

    PRA PS1/26 Annex XXII
    (`docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`),
    p. 14, contains a column-letter typo in the UKB CR7-A column reference
    table. After defining col **(o)** as "Part of the exposure covered by
    funded credit protection (FCP) — slotting", the PDF then defines the
    next column — "Part of the exposure covered by unfunded credit
    protection (UFCP) — slotting" — using the letter **(n)** a second
    time. The intended label is **(p)**: col (n) is already used earlier
    on the same page for "RWEA with substitution effects".

    The corrected sequence is the **a–p (16 columns)** sequence shown in
    the table above and in the
    [Structural Summary](#structural-summary). Implementors should
    follow the corrected **o/p** sequence in this documentation, not the
    literal letter as printed in the PDF — populating a column keyed
    "(n)" twice will silently overwrite the substitution-effects RWEA
    cell with the slotting unfunded-CP percentage.

### Row Changes

| Change | Description |
|--------|-------------|
| **Added** | Slotting section (separate from F-IRB and A-IRB) |
| **Added** | Purchased receivables rows (corporate and retail) |
| **Changed** | Retail RE split into residential (SME/non-SME) and commercial (SME/non-SME) |
| **Changed** | All CRM percentages on **post-conversion-factor** basis |
| **Changed** | F-IRB uses **Foundation Collateral Method** (Ci after haircuts, capped at exposure) |
| **Changed** | A-IRB uses **LGD Modelling Collateral Method** (estimated market value, capped) |

---

## CR8 — RWEA Flow Statements

| Change | Description |
|--------|-------------|
| **No structural changes** | Same 9-row flow statement (opening, 7 drivers, closing) |
| **Changed** | RWEA no longer includes supporting factor adjustments |

---

## CR9 — IRB Back-Testing of PD per Exposure Class

UKB CR9 discloses, per exposure class, the realised one-year default rates against
the PDs assigned at the start of the period. The template is **fixed** (column
structure unchanged from the legacy CRR template), but several column definitions
now incorporate the new Basel 3.1 PD input floors and exposure-level RW floors.

### General Reporting Rules

- One template **per exposure class**, **per approach** (F-IRB and A-IRB disclosed
  as two separate sets — Annex XXII para. 12).
- F-IRB sub-templates: institutions; corporates (specialised lending; financial
  corporates and large corporates; other general corporates SMEs; other general
  corporates non-SMEs); total.
- A-IRB sub-templates: corporates (SL; other general corporates SME/non-SME); retail
  (residential RE SME/non-SME; commercial RE SME/non-SME; QRRE; other SME; other
  non-SME); total.
- **Excludes** counterparty credit risk exposures, securitisation positions, other
  non-credit-obligation assets, and equity exposures (Annex XXII para. 15).
- Defaulted exposures are placed in the **PD = 100%** bucket of the fixed PD range.

### Column Definitions (UKB CR9, cols a–h)

Definitions below are taken verbatim from PRA PS1/26 Annex XXII (Pillar III IRB
disclosure instructions), pages 18–22.

| Col | Column | Definition (UKB CR9) |
|-----|--------|----------------------|
| **a** | Exposure classes | Designation of the F-IRB / A-IRB exposure class or sub-class for which a separate template is being disclosed (corporates / SL / financial-and-large corporates / SME / non-SME, retail RE SME/non-SME, retail commercial RE, QRRE, other retail). Institutions disclose **one template per class** plus a "Total" row. |
| **b** | PD range | **Fixed PD range** which shall not be altered. Exposures are allocated to a bucket based on the **PD estimated at the beginning of the disclosure period** for each obligor (without considering CRM substitution effects). All defaulted exposures fall into the PD = 100% bucket. |
| **c** | Number of obligors at the end of the previous year | Number of separately rated legal entities or obligors allocated to each PD bucket at the **end of the previous year**, regardless of the number of loans or exposures granted. Joint obligors are treated the same as for PD calibration. Where different exposures to the same obligor are separately rated (e.g. retail with facility-level default per Art. 178(1) last sentence, or different obligor grades per Art. 172(1)(e) second sentence), they are counted **separately**. |
| **d** | Of which: number of obligors that defaulted during the year | **Subset of column c** representing the number of obligors which defaulted during the year preceding the disclosure date. Default is determined per Art. 178 IRB. Each defaulted obligor is counted **only once** in the numerator and denominator of the one-year default rate, even if it defaulted more than once during the period. |
| **e** | Observed average default rate (%) | **Arithmetic average of one-year default rates** (as defined in CRR Art. 4(1)(78)) observed within the available dataset. Denominator: number of non-defaulted obligors with any credit obligation observed at the **beginning of the one-year observation period** (on-BS principal/interest/fees plus off-BS items including issued guarantees). Numerator: those obligors that had **at least one default event** during the year. Institutions choose between **overlapping** and **non-overlapping** one-year time windows. |
| **f** | Exposure-weighted average PD (%) | Same value as **column f of UKB CR6**. For all exposures in each PD bucket, the average PD estimate of each obligor weighted by the **exposure value post-CCF and CRM** (col e of UKB CR6). **PD input floors** per Art. 160(1) and 163(1) IRB **and exposure-level risk weight floors** per Art. 160(4) (referred to in Art. 161(3)) and Art. 163(4) (referred to in Art. 164(5)) **shall be taken into account**. |
| **g** | Average PD at the disclosure date (%) | **Arithmetic average** of PD at the beginning of the disclosure period for the obligors falling within the bucket and counted in **column d** (i.e. weighted by **number of obligors**, not by exposure). **PD input floors shall be taken into account**. |
| **h** | Average historical annual default rate (%) | **Simple average of the annual default rate of the five most recent years** (obligors at the beginning of each year that defaulted during that year ÷ total number of obligors at the beginning of the year). Institutions may use a **longer historical period** consistent with their actual risk management practices, in which case they shall explain and clarify this in the accompanying narrative. |

Source: PRA PS1/26 Annex XXII — Credit Risk IRB Disclosure Instructions
(`docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`),
paragraphs 12–15 and column-reference table, pp. 18–22.

!!! warning "Floor application differs across columns f, g, h"

    The three "average PD" columns are **not** computed on a single PD value — each
    column applies (or omits) different regulatory floors and uses a different
    weighting basis:

    - **Col b (bucket assignment)** uses the **estimated PD at the beginning of
      the period**, **without** CRM substitution effects. The plan-item
      description that this is "pre-floor" is correct only in the sense that
      bucket allocation is driven by the modelled PD before the CR6 column-a
      pre-input-floor allocation logic is itself applied; PRA Annex XXII para.
      "b" does not explicitly invoke Art. 160(1) / 163(1) floors at the bucket
      step.
    - **Col f (EWA PD)** is **post-input-floor** and additionally applies
      **exposure-level RW floors** (Art. 160(4) / 163(4) — the residential RE
      mortgage exposure-level floor referenced in Art. 161(3) / 164(5)). It
      mirrors UKB CR6 col f exactly.
    - **Col g (avg PD at disclosure date)** applies **PD input floors only** and
      is weighted by **obligor count** (not exposure value), restricted to the
      obligor population in **column d**.
    - **Col h (5-year historical default rate)** is a **realised** rate; floors
      do not apply, but the disclosing institution may extend the window beyond
      five years if consistent with its risk-management practice (must be
      narrated).

    Mechanically backing out a single "model PD" from cols f, g and h is
    therefore **not valid** — they answer different questions on different
    populations.

### CRR vs Basel 3.1 Deltas

| Area | CRR (UK CR9) | Basel 3.1 (UKB CR9) |
|------|--------------|---------------------|
| **Column count** | 8 (a–h) | 8 (a–h) — same fixed structure |
| **Col f PD floors** | Art. 160(1) / 163(1) PD floor of **0.03%** uniformly | **Differentiated PD floors** (Art. 160(1), 163(1)) — class-specific (0.05% retail, 0.10% corporate / institution / sovereign) plus **exposure-level RW floors** for residential RE per Art. 161(3) / 164(5) |
| **Col d "of which defaulted"** | Per Art. 178 (CRR) | Per Art. 178 IRB — definition unchanged in substance |
| **Sub-templates (rows)** | Corporates row (no SL split inside CR9 by approach) | F-IRB adds **financial corporates and large corporates** sub-row (Art. 147(2)(c)(ii)); A-IRB retail adds **commercial immovable property SME/non-SME** rows |
| **CR9.1 ECAI variant** | Same scope | Unchanged — disclosed where Art. 180(1)(f) ECAI mapping is used; col b becomes internal-grade ranges and one column added per ECAI |

### Relationship to COREP C 08.05 / OF 08.05

UKB CR9 is the **Pillar III** (public disclosure) back-testing template. The
**COREP** equivalent is **C 08.05 / OF 08.05** (PD back-testing for IRB), which
has a **5-column structure** (average PD, number of obligors, of which defaulted,
observed default rate, historical default rate) — narrower than UKB CR9's 8
columns because COREP omits the PD-bucket-range column (b), the obligor-weighted
PD-at-disclosure-date column (g), and the explicit exposure-class designator
column (a). For the COREP C 08.05 / OF 08.05 column structure, see
[Reporting Differences](reporting-differences.md).

---

## CR10 — Slotting Approach Exposures

### Sub-Template Changes

| CRR | Basel 3.1 | Change |
|-----|-----------|--------|
| CR10.1 — Project finance | CR10.1 — Project finance | Unchanged |
| CR10.2 — IPRE and HVCRE | CR10.2 — Income-producing RE | HVCRE separated out |
| CR10.3 — Object finance | CR10.3 — Object finance | Unchanged |
| CR10.4 — Commodities finance | CR10.4 — Commodities finance | Unchanged |
| CR10.5 — **Equity** (simple RW) | CR10.5 — **HVCRE** | Equity removed; HVCRE takes slot |

### Column Changes

| Change | Col(s) | Description |
|--------|--------|-------------|
| **Changed** | d | Exposure value now includes **post-CRM** effects |
| **Changed** | e | RWEA no longer includes supporting factors |

---

## Key Themes

The disclosure template changes reflect four Basel 3.1 themes:

1. **Output floor transparency** — OV1 gains rows 26-27 and pre-floor ratio rows,
   giving market participants visibility into the floor's capital impact

2. **Granular real estate and specialised lending** — CR4, CR5, and CR7-A gain
   detailed sub-rows for regulatory RE categories (residential/commercial, cash-flow
   dependency, ADC) and SA specialised lending (Art. 122A-122B)

3. **Equity transitional treatment** — equity moves from the simple risk-weighted
   approach (OV1 row UK 4a, CR10.5) to the IRB Transitional Approach (OV1 rows 11-14)
   or end-state SA (CR4/CR5)

4. **Removal of capital relief mechanisms** — supporting factors (Art. 501, 501a)
   removed from CR6 RWEA and CR10 RWEA; post-model adjustments replace them
   as the regulatory overlay mechanism

## See Also

- [Full Pillar III disclosure specification](../features/pillar3-disclosures.md) — complete
  column and row definitions
- [Reporting Differences](reporting-differences.md) — CRR vs Basel 3.1 COREP template changes
- [Key Differences](key-differences.md) — regulatory parameter comparison
