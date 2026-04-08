# Pillar III Disclosures

Pillar III requires banks to publish quantitative credit risk data to the market, complementing
the confidential COREP returns submitted to the PRA. While both draw on the same underlying
RWA calculations, Pillar III templates are structured for public consumption and comparability
across firms.

## COREP vs Pillar III

| Aspect | COREP (Pillar I Reporting) | Pillar III (Public Disclosure) |
|--------|---------------------------|-------------------------------|
| **Audience** | PRA (confidential) | Market participants (public) |
| **Purpose** | Supervisory monitoring | Market discipline and transparency |
| **Frequency** | Quarterly | Quarterly, semi-annual, or annual (by firm size) |
| **CRR prefix** | C (e.g., C 07.00) | UK (e.g., UK OV1) |
| **Basel 3.1 prefix** | OF (e.g., OF 07.00) | UKB (e.g., UKB OV1) |
| **Granularity** | Exposure-class level submissions | Cross-approach summaries and PD-range breakdowns |
| **Legal basis** | Regulation (EU) 2021/451 | CRR Part 8 / Disclosure (CRR) Part |

!!! info "Template Naming"
    Under CRR, disclosure templates use the **UK** prefix (e.g., UK CR6).
    Under Basel 3.1 (PRA PS1/26), they use the **UKB** prefix (e.g., UKB CR6).
    The structure and purpose are equivalent but columns, rows, and exposure class
    breakdowns differ as detailed below.

## Template Overview

The calculator's outputs can populate the following credit risk disclosure templates. Templates
are grouped by the approach they cover.

```mermaid
flowchart TD
    P["Pipeline Output"] --> OV1["<b>OV1</b><br/>Overview of RWEAs<br/><i>All approaches</i>"]

    P --> SA["SA Templates"]
    SA --> CR4["<b>CR4</b><br/>Exposure & CRM Effects"]
    SA --> CR5["<b>CR5</b><br/>Risk Weight Allocation"]

    P --> IRB["IRB Templates"]
    IRB --> CR6["<b>CR6</b><br/>Exposures by PD Range"]
    IRB --> CR6A["<b>CR6-A</b><br/>Scope of IRB/SA Use"]
    IRB --> CR7["<b>CR7</b><br/>Credit Derivatives Effect"]
    IRB --> CR7A["<b>CR7-A</b><br/>CRM Technique Extent"]
    IRB --> CR8["<b>CR8</b><br/>RWEA Flow Statements"]
    IRB --> CR9["<b>CR9</b><br/>PD Back-Testing"]
    IRB --> CR9_1["<b>CR9.1</b><br/>PD Back-Testing (ECAI)"]

    P --> SL["Slotting"]
    SL --> CR10["<b>CR10</b><br/>Slotting Exposures"]

    style OV1 fill:#e8f5e9,stroke:#43a047
    style CR4 fill:#fff3e0,stroke:#fb8c00
    style CR5 fill:#fff3e0,stroke:#fb8c00
    style CR6 fill:#e3f2fd,stroke:#1e88e5
    style CR6A fill:#e3f2fd,stroke:#1e88e5
    style CR7 fill:#e3f2fd,stroke:#1e88e5
    style CR7A fill:#e3f2fd,stroke:#1e88e5
    style CR8 fill:#e3f2fd,stroke:#1e88e5
    style CR9 fill:#e3f2fd,stroke:#1e88e5
    style CR9_1 fill:#e3f2fd,stroke:#1e88e5
    style CR10 fill:#f3e5f5,stroke:#8e24aa
```

| Template | CRR Name | Basel 3.1 Name | Purpose | Format | CRR Article |
|----------|----------|----------------|---------|--------|-------------|
| **OV1** | UK OV1 | UKB OV1 | Overview of risk-weighted exposure amounts | Fixed | Art. 438(d) |
| **CR4** | UK CR4 | UKB CR4 | SA exposure and CRM effects | Fixed | Art. 444(e), 453(g-i) |
| **CR5** | UK CR5 | UKB CR5 | SA risk weight allocation | Fixed | Art. 444(e) |
| **CR6** | UK CR6 | UKB CR6 | IRB exposures by exposure class and PD range | Fixed | Art. 452(g) |
| **CR6-A** | UK CR6-A | UKB CR6-A | Scope of IRB and SA use | Fixed | Art. 452(b) |
| **CR7** | UK CR7 | UKB CR7 | Credit derivatives effect on RWEA | Fixed | Art. 453(j) |
| **CR7-A** | UK CR7-A | UKB CR7-A | Extent of CRM techniques (IRB) | Fixed | Art. 453(g) |
| **CR8** | UK CR8 | UKB CR8 | RWEA flow statements (IRB) | Fixed | Art. 438(h) |
| **CR9** | --- | UKB CR9 | IRB PD back-testing per exposure class | Fixed | Art. 452(h) |
| **CR9.1** | --- | UKB CR9.1 | IRB PD back-testing for ECAI mapping | Fixed | Art. 452(h), Art. 180(1)(f) |
| **CR10** | UK CR10 | UKB CR10 | Slotting approach exposures | Fixed | Art. 438(e) |

---

## OV1 — Overview of Risk-Weighted Exposure Amounts

The OV1 template provides a high-level summary of RWEAs and own funds requirements
across all risk categories. It is the top-level disclosure from which credit risk rows
(1-5) link to the detailed CR templates.

### Column Structure

=== "CRR (UK OV1)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | RWEAs | Risk-weighted exposure amounts at reporting date |
    | b | RWEAs (T-1) | RWEAs as disclosed in the previous period |
    | c | Total own funds requirements | Own funds requirements corresponding to RWEAs |

=== "Basel 3.1 (UKB OV1)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | RWEAs (T) | Risk-weighted exposure amounts at reporting date |
    | b | RWEAs (T-1) | RWEAs as disclosed in the previous period |
    | c | Total own funds requirements | Own funds requirements corresponding to RWEAs |

    No column changes — structure is identical.

### Row Structure (Credit Risk Rows)

=== "CRR (UK OV1)"

    | Row | Description |
    |-----|-------------|
    | 1 | Credit risk (excluding CCR) — total |
    | 2 | Of which: standardised approach |
    | 3 | Of which: foundation IRB (FIRB) approach |
    | 4 | Of which: slotting approach |
    | UK 4a | Of which: equities under the simple risk-weighted approach |
    | 5 | Of which: advanced IRB (AIRB) approach |
    | 24 | Amounts below deduction thresholds (250% RW) — memo |
    | 29 | **Total** |

=== "Basel 3.1 (UKB OV1)"

    | Row | Description |
    |-----|-------------|
    | 1 | Credit risk (excluding CCR) — total (excludes equity rows 11-14) |
    | 2 | Of which: standardised approach (SA) |
    | 3 | Of which: FIRB approach |
    | 4 | Of which: slotting approach |
    | 5 | Of which: AIRB approach |
    | **11** | **Equity positions under the IRB Transitional Approach** |
    | **12** | **Equity investments in funds — look-through approach** |
    | **13** | **Equity investments in funds — mandate-based approach** |
    | **14** | **Equity investments in funds — fall-back approach** |
    | 24 | Amounts below deduction thresholds (250% RW) — memo |
    | **26** | **Output floor multiplier** |
    | **27** | **Output floor adjustment** |
    | 29 | **Total** |

    Key Basel 3.1 additions (bold): equity transitional rows (11-14), output floor
    rows (26-27). Row UK 4a (equities under simple RW) is removed — equity goes to
    rows 11-14 or SA (row 2).

!!! note "Scope"
    OV1 covers all risk categories (credit, CCR, CVA, market, operational).
    Only the credit risk rows (1-5, 11-14, 24) are directly populated from the
    RWA calculator output.

### Reference Documents

- CRR: `docs/assets/crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf` (Annex II)
- Basel 3.1: `docs/assets/ps1-26-annex-ii-output-floor-and-capital-summaries-disclosure-instructions.pdf`

---

## CR4 — SA Exposure and CRM Effects

CR4 shows SA exposures before and after the application of credit conversion factors (CCFs)
and credit risk mitigation (CRM), by exposure class. It demonstrates the net effect of CRM
on the firm's SA credit risk.

### Column Structure

=== "CRR (UK CR4)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | On-BS exposures before CCF and CRM | Gross on-balance sheet per Art. 111, after provisions |
    | b | Off-BS exposures before CCF and CRM | Gross off-balance sheet, before CCFs and CRM |
    | c | On-BS amount post CCF and post CRM | Net on-BS after all CRM and CCFs applied |
    | d | Off-BS amount post CCF and post CRM | Net off-BS after all CRM and CCFs applied |
    | e | RWEAs | Risk-weighted exposure amounts |
    | f | RWEA density | Ratio: col e / (col c + col d) |

=== "Basel 3.1 (UKB CR4)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | On-BS exposures before CF and CRM | Gross on-balance sheet per Art. 111, after provisions |
    | b | Off-BS exposures before CF and CRM | Gross off-balance sheet, before CFs and CRM |
    | c | On-BS amount post CF and post CRM | Net on-BS after all CRM and CFs applied |
    | d | Off-BS amount post CF and post CRM | Net off-BS after all CRM and CFs applied |
    | e | RWEAs | Risk-weighted exposure amounts |
    | f | RWEA density | Ratio: col e / (col c + col d) |

    Column structure is unchanged. The key difference is in the row breakdowns.

### Row Structure

=== "CRR (UK CR4)"

    Rows 1-16 by exposure class per Article 112 CRR (excluding securitisation).
    Row 16 is "Other items" (Art. 134 assets, items below deduction thresholds).

=== "Basel 3.1 (UKB CR4)"

    Rows 1-16 by exposure class per Article 112 of the Credit Risk: SA (CRR) Part,
    with additional "of which" breakdowns:

    - **Specialised lending** (under corporates, Art. 122A-122B)
    - **Residential RE — not materially dependent** on cash flows (Art. 124F, 124J(2))
    - **Residential RE — materially dependent** on cash flows (Art. 124G, 124J(1))
    - **Commercial RE — not materially dependent** on cash flows (Art. 124H, 124J(3))
    - **Commercial RE — materially dependent** on cash flows (Art. 124I, 124J(1))
    - **Land acquisition, development and construction** (Art. 124K)

### Reference Documents

- CRR: `docs/assets/crr-annex-xx-instructions-regarding-disclosure.PDF` (Annex XX)
- Basel 3.1: `docs/assets/ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf`

---

## CR5 — SA Risk Weight Allocation

CR5 shows the allocation of post-CRM SA exposure values across risk weight buckets, by
exposure class. It reveals the distribution of risk across the portfolio.

### Column Structure

=== "CRR (UK CR5)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a-o | Risk weights 0%-1250% | Exposure value allocated to each risk weight (15 buckets) |
    | p | Total | Total exposure value post CRM and post CCF |
    | q | Of which: unrated | Exposures without ECAI credit assessment |

=== "Basel 3.1 (UKB CR5)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a-ac | Risk weights 0%-1250% | Exposure value allocated to each risk weight (**29 buckets**) |
    | ad | Total | Total exposure value post CRM and post CF |
    | ae | Of which: unrated | Exposures without ECAI credit assessment |
    | **ba** | **On-BS exposure amount** | On-BS after provisions (pre-CF/CRM) |
    | **bb** | **Off-BS exposure amount** | Off-BS pre-conversion factors |
    | **bc** | **Weighted average CF** | Average conversion factor for reported row |
    | **bd** | **Total post CF and CRM** | On-BS + off-BS after CFs and CRM |

    Key changes:

    - Risk weight buckets expand from **15 to 29** — adds 15%, 25%, 30%, 40%, 45%,
      60%, 65%, 80%, 85%, 105%, 110%, 130%, 135%, 400% (removes 370%)
    - New columns **ba-bd** provide an on-BS/off-BS breakdown with average CCF
    - Split reporting for regulatory real estate (portion up to 55% LTV vs above)
    - Currency mismatch exposures reported against the weight that would apply
      without the 1.5x multiplier (RWEA still reflects it)

### Row Structure

Rows 1-16 by SA exposure class. Basel 3.1 adds the same "of which" real estate and
specialised lending sub-rows as CR4, plus rows 18-33 for additional risk weight
allocation breakdowns.

### Reference Documents

- CRR: `docs/assets/crr-annex-xx-instructions-regarding-disclosure.PDF` (Annex XX)
- Basel 3.1: `docs/assets/ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf`

---

## CR6 — IRB Exposures by Exposure Class and PD Range

CR6 is the most detailed IRB disclosure template, showing exposure values, risk
parameters (PD, LGD, maturity), RWEAs, and expected loss by fixed PD buckets for each
exposure class. Separate templates are disclosed for F-IRB and A-IRB exposures.

### Column Structure

=== "CRR (UK CR6)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | PD range | Fixed PD range (not alterable) |
    | b | On-BS exposures | Pre-provisions, pre-CCF, pre-CRM |
    | c | Off-BS exposures pre-CCF | Nominal off-BS before conversion factors |
    | d | Exposure-weighted average CCF | Average CCF weighted by off-BS exposure |
    | e | Exposure value post CCF and CRM | Per Art. 166, sum of on-BS + off-BS post CCF/CRM |
    | f | Exposure-weighted average PD (%) | Average PD weighted by exposure value |
    | g | Number of obligors | Count of rated legal entities per PD bucket |
    | h | Exposure-weighted average LGD (%) | Final LGD after CRM and downturn, weighted by exposure |
    | i | Exposure-weighted average maturity (years) | Per Art. 162, not disclosed for retail |
    | j | RWEAs | After supporting factors (Art. 501, 501a) |
    | k | RWEA density | Ratio: col j / col e |
    | l | Expected loss amount | Per Art. 158 |
    | m | Value adjustments and provisions | Specific + general credit risk adjustments |

=== "Basel 3.1 (UKB CR6)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | PD range | Fixed PD range — allocation uses **pre-input-floor PDs** |
    | b | On-BS exposures | Pre-provisions, pre-CCF, pre-CRM |
    | c | Off-BS exposures pre-CCF | Nominal off-BS values per Art. 166C(1), 166D(1) |
    | d | Exposure-weighted average CCF | Average CCF weighted by off-BS exposure |
    | e | Exposure value post CCF and CRM | Per Art. 166A-166D |
    | f | Exposure-weighted average PD (%) | **Post-input-floor PDs** (Art. 160(1), 163(1)) |
    | g | Number of obligors | Count of rated legal entities per PD bucket |
    | h | Exposure-weighted average LGD (%) | After CRM, **including LGD input floors** (Art. 161(5), 164(4)) |
    | i | Exposure-weighted average maturity (years) | Per Art. 162, not disclosed for retail |
    | j | RWEAs | **Includes post-model adjustments** and mortgage RW floor; no supporting factors |
    | k | RWEA density | Ratio: col j / col e |
    | l | Expected loss amount | Per Art. 158, **including post-model adjustments** (Art. 158(6A)) |
    | m | Value adjustments and provisions | Specific + general credit risk adjustments |

    Key changes:

    - PD bucket allocation uses **pre-input-floor** PDs, but weighted average PD (col f)
      uses **post-floor** PDs
    - RWEA (col j) includes post-model adjustments, unrecognised exposure adjustments,
      and the mortgage RW floor — no longer includes supporting factors
    - Expected loss (col l) includes post-model adjustments per Art. 158(6A)
    - Slotting exposures are **excluded** (reported in CR10)

### Row Structure — Exposure Class Breakdown

=== "CRR (UK CR6)"

    Separate template per exposure class, further broken down:

    - **Corporates**: SME, specialised lending, other
    - **Retail**: SME secured by immovable property, non-SME secured by immovable
      property, qualifying revolving, SME other, non-SME other

=== "Basel 3.1 (UKB CR6)"

    **A-IRB** — separate template per category:

    1. Corporates: specialised lending, other general corporates (SME), other general corporates (non-SME)
    2. Retail: secured by residential immovable property (SME/non-SME), secured by
       commercial immovable property (SME/non-SME), qualifying revolving,
       other (SME/non-SME)

    **F-IRB** — separate template per category:

    1. Institutions
    2. Corporates: specialised lending, **financial corporates and large corporates**,
       other general corporates (SME/non-SME)

    Key change: F-IRB adds **financial corporates and large corporates** as a
    separate sub-class (Art. 147(2)(c)(ii)), reflecting the Basel 3.1 restriction
    to F-IRB only for these counterparties.

### Reference Documents

- CRR: `docs/assets/crr-pillar3-irb-credit-risk-instructions.pdf` (Annex XXII)
- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`

---

## CR6-A — Scope of IRB and SA Use

CR6-A shows the split of exposures between IRB and SA approaches, including permanent
partial use and roll-out plans.

### Column Structure

=== "CRR (UK CR6-A)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | Exposure value (Art. 166) for IRB exposures | IRB exposure value only |
    | b | Total exposure value (Art. 429(4)) | Both SA and IRB exposures |
    | c | % subject to permanent partial use of SA | SA exposures / total |
    | d | % subject to IRB approach | IRB exposures / total (F-IRB, A-IRB, slotting, equity simple RW) |
    | e | % subject to roll-out plan | Exposures planned for future IRB transition |

=== "Basel 3.1 (UKB CR6-A)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | Exposure value (Art. 166A-166D) for IRB exposures | IRB exposure value only |
    | b | Total exposure value (Art. 429(4)) | Both SA and IRB exposures |
    | c | % subject to permanent partial use of SA | SA exposures / total |
    | d | % subject to IRB approach | IRB exposures / total (F-IRB, A-IRB, slotting) |
    | e | % subject to roll-out plan | Exposures planned for future IRB transition |

    Column structure unchanged. Row breakdown restructured around **roll-out classes**
    (Art. 147B) instead of exposure classes.

### Row Structure

=== "CRR (UK CR6-A)"

    Rows by IRB exposure class per Art. 147(2).

=== "Basel 3.1 (UKB CR6-A)"

    Rows 3.9-3.16 by **roll-out class** per Art. 147B, with row 5 for totals.

### Reference Documents

- CRR: `docs/assets/crr-pillar3-irb-credit-risk-instructions.pdf` (Annex XXII)
- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`

---

## CR7 — Credit Derivatives Effect on RWEA

CR7 shows the impact of credit derivatives used as CRM on risk-weighted exposure amounts
under the IRB approach. Excludes CCR, securitisation, and equity exposures.

### Column Structure

| Col | Column | Description |
|-----|--------|-------------|
| a | Pre-credit derivatives RWEA | Hypothetical RWEA assuming no credit derivative recognition |
| b | Actual/Post-credit derivatives RWEA | RWEA after credit derivative CRM effects |

Column structure is identical under both CRR and Basel 3.1.

### Row Structure

=== "CRR (UK CR7)"

    | Row | Description |
    |-----|-------------|
    | 1 | F-IRB subtotal |
    | 2-5 | F-IRB exposure classes (central govt, institutions, corporates with breakdown) |
    | 6 | A-IRB subtotal |
    | 7-9 | A-IRB exposure classes (corporates with breakdown, retail with breakdown) |
    | 10 | **Total** (F-IRB + A-IRB) |

=== "Basel 3.1 (UKB CR7)"

    | Row | Description |
    |-----|-------------|
    | 1 | F-IRB subtotal |
    | 2-3 | F-IRB exposure classes |
    | 4 | A-IRB subtotal |
    | 5-6 | A-IRB exposure classes |
    | **7** | **Slotting subtotal** |
    | 8 | **Total** (F-IRB + A-IRB + Slotting) |

    Key change: adds **slotting** as a third approach category with its own subtotal row.
    Exposure subclass breakdowns include SME/non-SME splits where applicable.

### Reference Documents

- CRR: `docs/assets/crr-pillar3-irb-credit-risk-instructions.pdf` (Annex XXII)
- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`

---

## CR7-A — Extent of CRM Techniques (IRB)

CR7-A discloses the extent to which different types of funded and unfunded credit protection
cover IRB exposures. Disclosed separately for F-IRB, A-IRB, and (under Basel 3.1) slotting.

### Column Structure

=== "CRR (UK CR7-A)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | Total exposures | Exposure value post CCF (pre-CRM), per Art. 166-167 |
    | b | FCP: Financial collateral (%) | % covered by financial collateral (Art. 197-198) |
    | c | FCP: Other eligible collateral (%) | Sum of cols d + e + f |
    | d | FCP: Immovable property (%) | % covered by immovable property collateral |
    | e | FCP: Receivables (%) | % covered by receivables (Art. 199(5)) |
    | f | FCP: Other physical collateral (%) | % covered by other physical collateral |
    | g | FCP: Other funded CP (%) | Sum of cols h + i + j |
    | h | FCP: Cash on deposit (%) | % covered by cash held by third party |
    | i | FCP: Life insurance policies (%) | % covered by life insurance policies |
    | j | FCP: Instruments held by third party (%) | % covered by repurchasable instruments |
    | k | UFCP: Guarantees (%) | % covered by guarantees (Art. 213-215) |
    | l | UFCP: Credit derivatives (%) | % covered by credit derivatives (Art. 204) |
    | m | RWEA post all CRM (obligor class) | RWEA in original obligor exposure class |
    | n | RWEA with substitution effects | RWEA in protection provider exposure class |

=== "Basel 3.1 (UKB CR7-A)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | Total exposures | Exposure value post CCF (pre-CRM), per Art. 166A-166D |
    | b | FCP: Financial collateral (%) | Includes **on-balance sheet netting** (Art. 219) |
    | c | FCP: Other eligible collateral (%) | Sum of cols d + e + f |
    | d | FCP: Immovable property (%) | % covered by immovable property collateral |
    | e | FCP: Receivables (%) | % covered by receivables |
    | f | FCP: Other physical collateral (%) | % covered by other physical collateral |
    | g | FCP: Other funded CP (%) | Sum of cols h + i + j |
    | h | FCP: Cash on deposit (%) | % covered by cash held by third party |
    | i | FCP: Life insurance policies (%) | % covered by life insurance policies |
    | j | FCP: Instruments held by third party (%) | % covered by repurchasable instruments |
    | k | UFCP: Guarantees (%) | % covered by guarantees (Art. 203) |
    | l | UFCP: Credit derivatives (%) | % covered by credit derivatives (Art. 204) |
    | m | RWEA post all CRM (obligor class) | RWEA in original obligor exposure class |
    | n | RWEA with substitution effects | RWEA in protection provider exposure class |
    | **o** | **FCP for slotting (%)** | % covered by FCCM or on-BS netting (slotting only) |
    | **p** | **UFCP for slotting (%)** | % covered by guarantees/credit derivatives (slotting only) |

    Key changes:

    - **On-balance sheet netting** included in financial collateral (col b)
    - **Post-conversion-factor basis**: CRM values multiplied by CCF where applicable
    - **Slotting FCP/UFCP columns** (o, p) added for slotting approach exposures
    - FIRB collateral valued under **Foundation Collateral Method** (Ci after haircuts)
    - AIRB collateral valued under **LGD Modelling Collateral Method** (estimated market value)

### Row Structure

=== "CRR (UK CR7-A)"

    Separate disclosure for A-IRB and F-IRB. Exposure class breakdowns:

    - **Corporates**: SME, specialised lending (excl. slotting), other
    - **Retail**: SME secured by immovable property, non-SME secured by immovable
      property, qualifying revolving, SME other, non-SME other

=== "Basel 3.1 (UKB CR7-A)"

    Separate disclosure for A-IRB, F-IRB, and **slotting**. Expanded breakdowns:

    - **Corporates (A-IRB)**: specialised lending, **purchased receivables**, other
      general corporates (SME/non-SME)
    - **Retail**: secured by **residential** immovable property (SME/non-SME),
      secured by **commercial** immovable property (SME/non-SME), qualifying
      revolving, **purchased receivables**, other (SME/non-SME)
    - **Corporates (F-IRB)**: specialised lending, **financial corporates and large
      corporates**, other general corporates (SME/non-SME)

    Key additions: purchased receivables rows, residential/commercial RE split,
    financial corporates sub-class.

### Reference Documents

- CRR: `docs/assets/crr-pillar3-irb-credit-risk-instructions.pdf` (Annex XXII)
- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`

---

## CR8 — RWEA Flow Statements (IRB)

CR8 explains the drivers of change in IRB RWEAs between disclosure periods.
Institutions must supplement it with a narrative explaining material movements.

### Column Structure

| Col | Column | Description |
|-----|--------|-------------|
| a | RWEA | Total IRB risk-weighted exposure amount for credit risk |

Single column — each row explains a driver of RWEA change.

### Row Structure

| Row | Driver | Description |
|-----|--------|-------------|
| 1 | RWEA at end of previous period | Opening balance |
| 2 | Asset size (+/-) | Organic changes in book size and composition |
| 3 | Asset quality (+/-) | Rating grade migration and borrower risk changes |
| 4 | Model updates (+/-) | New models, model changes, scope changes |
| 5 | Methodology and policy (+/-) | Regulatory methodology changes (excl. models) |
| 6 | Acquisitions and disposals (+/-) | Book size changes from M&A |
| 7 | Foreign exchange movements (+/-) | Currency translation effects |
| 8 | Other (+/-) | Residual — must be explained in narrative |
| 9 | RWEA at end of disclosure period | Closing balance |

The structure is identical under CRR and Basel 3.1. The only difference is that
Basel 3.1 RWEAs in rows 1 and 9 no longer include supporting factor adjustments
(Art. 501, 501a removed).

### Reference Documents

- CRR: `docs/assets/crr-pillar3-irb-credit-risk-instructions.pdf` (Annex XXII)
- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`

---

## CR9 — IRB PD Back-Testing per Exposure Class

CR9 is a **mandatory Basel 3.1 disclosure** (Art. 452(h)) with no CRR equivalent. It provides
PD back-testing data per exposure class, showing how well the institution's PD estimates
predicted actual defaults. Separate templates are disclosed for F-IRB and A-IRB approaches,
with one template per exposure class within each approach.

### Column Structure

| Col | Column | Description |
|-----|--------|-------------|
| a | Exposure class | AIRB or FIRB exposure class label |
| b | PD range | Fixed PD range (same 17 buckets as CR6). Allocation based on PD at **beginning of disclosure period** |
| c | Number of obligors at end of previous year | Legal entities separately rated at end of previous year |
| d | Of which: defaulted during the year | Subset of col c defaulted per Art. 178. Each defaulted obligor counted only once |
| e | Observed average default rate (%) | Arithmetic average of one-year default rates (col d / col c) |
| f | Exposure-weighted average PD (%) | Same as CR6 col f — post-input-floor PDs (Art. 160(1), 163(1)) |
| g | Average PD at disclosure date (%) | Arithmetic average PD of obligors, obligor-weighted (post input floors) |
| h | Average historical annual default rate (%) | Simple average of annual default rates over the 5 most recent years |

### Row Structure — Exposure Class Breakdown

=== "Basel 3.1 (UKB CR9) — A-IRB"

    Separate template per exposure class:

    1. **Corporates**: specialised lending, other general corporates (SME/non-SME)
    2. **Retail**: secured by residential immovable property (SME/non-SME),
       secured by commercial immovable property (SME/non-SME),
       qualifying revolving, other (SME/non-SME)
    3. **Total**

=== "Basel 3.1 (UKB CR9) — F-IRB"

    Separate template per exposure class:

    1. **Institutions**
    2. **Corporates**: specialised lending (including slotting),
       financial corporates and large corporates,
       other general corporates (SME/non-SME)
    3. **Total**

### Key Differences from CR6

- **PD allocation**: CR9 uses PD at the **beginning of the disclosure period**,
  while CR6 uses the **pre-input-floor** PD. The pipeline approximates
  beginning-of-period PD with `irb_pd_original` (pre-floor model output).
- **Back-testing focus**: CR9 is about model validation (predicted vs actual defaults),
  not risk parameter disclosure.
- **Historical data**: Col h requires a 5-year lookback of annual default rates.
  When historical data is absent, the current-period observed rate is used as a
  single-period approximation.

### Known Approximations

- Beginning-of-period PD (col b allocation) approximated by `irb_pd_original`
- Historical annual default rate (col h) falls back to current-period observed rate
- Prior-year obligor count (col c) falls back to current-period count

### Reference Documents

- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf` (paras 12-15)

---

## CR9.1 — IRB PD Back-Testing for ECAI Mapping

CR9.1 is supplementary to CR9, required only when an institution uses Art. 180(1)(f)
of the Credit Risk: IRB Part for PD estimation based on ECAI mappings. **Basel 3.1 only**.

### Structure

Same as CR9 with the following exceptions:

- **Col b**: PD ranges based on the firm's **internal grades** mapped to the ECAI scale
  (variable-width, not the fixed 17-bucket structure)
- **Additional columns**: One column per ECAI considered, showing the external rating
  to which internal PD ranges are mapped

### Implementation Status

CR9.1 template definitions are in place but generation requires ECAI mapping data
not currently available in the pipeline. The template will return no data until
the pipeline provides firm-defined PD range to internal grade mapping and ECAI
names with their rating scale mappings.

### Reference Documents

- Basel 3.1: `docs/assets/ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf` (para 15)

---

## CR10 — Slotting Approach Exposures

CR10 discloses specialised lending exposures under the slotting approach (and, under
CRR only, equity exposures under the simple risk-weighted approach).

### Column Structure

=== "CRR (UK CR10)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | On-BS exposures | On-balance sheet exposure value (Art. 166(1)-(7), 167(1)) |
    | b | Off-BS exposures | Off-balance sheet exposure value pre-CCF |
    | c | Risk weight | Fixed column — per Art. 153(5) for slotting, Art. 155(2) for equity |
    | d | Exposure value | Post CCF — sum of on-BS + off-BS post conversion |
    | e | RWEA | After supporting factors (Art. 501, 501a) for slotting; per Art. 155(2) for equity |
    | f | Expected loss amount | Per Art. 158(6) for slotting, Art. 158(7) for equity |

=== "Basel 3.1 (UKB CR10)"

    | Col | Column | Description |
    |-----|--------|-------------|
    | a | On-BS exposures | On-balance sheet exposure value |
    | b | Off-BS exposures | Off-balance sheet exposure value pre-CCF (Art. 166A-166C) |
    | c | Risk weight | Fixed column — per Table A, Art. 153(5) |
    | d | Exposure value | Post CCF and CRM |
    | e | RWEA | Per Art. 153(5) — **no supporting factors** |
    | f | Expected loss amount | Per Art. 158(6) |

    Key changes:

    - **No supporting factors** in RWEA (Art. 501, 501a removed)
    - Exposure value (col d) includes **post-CRM** effects
    - **No equity** sub-template — equity exposures reported under the IRB
      Transitional Approach (OV1 row 11) or SA (CR4/CR5)

### Sub-Templates

=== "CRR (UK CR10)"

    | Template | Exposure Type |
    |----------|---------------|
    | CR10.1 | Project finance |
    | CR10.2 | Income-producing real estate and HVCRE |
    | CR10.3 | Object finance |
    | CR10.4 | Commodities finance |
    | CR10.5 | **Equity** under simple risk-weighted approach |

    Rows by regulatory category (Strong, Good, Satisfactory, Weak, Default) with
    fixed risk weights per Art. 153(5) Table 1 (slotting) or Art. 155(2) (equity).

=== "Basel 3.1 (UKB CR10)"

    | Template | Exposure Type |
    |----------|---------------|
    | CR10.1 | Project finance |
    | CR10.2 | Income-producing real estate |
    | CR10.3 | Object finance |
    | CR10.4 | Commodities finance |
    | **CR10.5** | **High volatility commercial real estate (HVCRE)** |

    Key changes:

    - HVCRE separated into its own sub-template (was combined with IPRE in CRR)
    - **Equity removed** — goes to IRB Transitional Approach or end-state SA
    - Rows by regulatory category per Art. 153(5) Table A

### Reference Documents

- CRR: `docs/assets/crr-pillar3-specialised-lending-instructions.pdf` (Annex XXIV)
- Basel 3.1: `docs/assets/ps1-26-annex-xxiv-credit-risk-irb-disclosure-instructions.pdf`

---

## UKB CMS1 — Output Floor Comparison by Risk Type (Art. 456(1)(a))

Basel 3.1 only — no CRR equivalent. Institutions subject to the output floor must disclose a
comparison between full standardised RWA and modelled RWA by risk type.

**Regulatory basis:** PRA PS1/26 Art. 456(1)(a), Art. 2a(1)

### Column Structure

| Col | Title |
|-----|-------|
| a | RWA for modelled approaches |
| b | RWA for portfolios where standardised approaches are used |
| c | Total actual RWA |
| d | RWA calculated using full standardised approach |

### Row Structure

| Row | Description |
|-----|-------------|
| 0010 | Credit risk (excluding CCR) |
| 0020 | Counterparty credit risk |
| 0030 | Credit valuation adjustment |
| 0040 | Securitisation exposures in the banking book |
| 0050 | Market risk |
| 0060 | Operational risk |
| 0070 | Residual RWA |
| 0080 | Total |

### Implementation Notes

- Only row 0010 (credit risk) and 0080 (total) are populated from the pipeline
- Rows 0020–0070 (CCR, CVA, securitisation, market risk, op risk, residual) are null — require
  data beyond credit risk scope
- Col a: RWA from IRB + slotting exposures (modelled approaches)
- Col b: RWA from SA-only portfolios
- Col c: Sum of cols a and b
- Col d: sa_rwa for all exposures (full SA recalculation)

---

## UKB CMS2 — Output Floor Comparison by Asset Class (Art. 456(1)(b))

Basel 3.1 only — no CRR equivalent. Breaks down the credit risk comparison at asset class level.

**Regulatory basis:** PRA PS1/26 Art. 456(1)(b), Art. 2a(2)

### Column Structure

| Col | Title |
|-----|-------|
| a | RWA for modelled approaches (IRB incl. slotting) |
| b | RWA for column (a) re-computed using SA |
| c | Total actual RWA |
| d | RWA calculated using full standardised approach |

### Row Structure

| Row | Description |
|-----|-------------|
| 0010 | Sovereign |
| 0011 | Of which: MDB/PSE in SA |
| 0020 | Institutions |
| 0030 | Subordinated debt, equity and other own funds |
| 0040 | Corporates |
| 0041 | Of which are FIRB |
| 0042 | Of which are AIRB |
| 0043 | Of which: specialised lending |
| 0044 | Of which: IPRE and HVCRE |
| 0045 | Of which: purchased receivables |
| 0050 | Retail |
| 0051 | Of which: qualifying revolving retail |
| 0052 | Of which: other retail |
| 0053 | Of which: retail secured by residential immovable property |
| 0054 | Of which: purchased receivables |
| 0060 | Others (non-credit obligation assets) |
| 0070 | Total |

### Implementation Notes

- Col a: IRB + slotting RWA per exposure class
- Col b: sa_rwa for modelled exposures (SA-equivalent recalculation)
- Col c: Modelled RWA + SA portfolio RWA per class
- Col d: sa_rwa for all exposures in each class
- Sub-rows 0041/0042 filter by approach (F-IRB/A-IRB within corporates)
- Sub-rows 0044, 0045, 0054 are null (require pipeline data not yet available)
- Excludes CCR, CVA, and securitisation exposures

---

## See Also

- [COREP Reporting](corep-reporting.md) — supervisory return templates (C 07.00, C 08.01, C 08.02)
- [Reporting Differences](../framework-comparison/reporting-differences.md) — CRR vs Basel 3.1 COREP changes
- [Disclosure Differences](../framework-comparison/disclosure-differences.md) — CRR vs Basel 3.1 Pillar III changes
- [Reporting API](../api/reporting.md) — `COREPGenerator` and `COREPTemplateBundle` classes
