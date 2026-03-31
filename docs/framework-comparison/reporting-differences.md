# Reporting Differences

Under Basel 3.1, COREP credit risk templates are renamed from the **C** prefix to **OF**
(Own Funds) and undergo significant structural changes. This page summarises the key
differences. For complete column and row definitions, see the
[full COREP template specification](../features/corep-reporting.md).

## Template Overview

| Template | CRR Name | Basel 3.1 Name | Purpose |
|----------|----------|----------------|---------|
| **02.00** | C 02.00 | OF 02.00 | Own funds requirements (all risk types) |
| **02.01** | — | OF 02.01 | Output floor comparison (**new**) |
| **07.00** | C 07.00 | OF 07.00 | SA credit risk |
| **08.01** | C 08.01 | OF 08.01 | IRB totals by exposure class |
| **08.02** | C 08.02 | OF 08.02 | IRB by obligor grade |
| **08.03** | C 08.03 | OF 08.03 | IRB breakdown by PD ranges |
| **08.04** | C 08.04 | OF 08.04 | IRB RWEA flow statements |
| **08.06** | C 08.06 | OF 08.06 | Specialised lending slotting |
| **08.07** | C 08.07 | OF 08.07 | Scope of use of IRB and SA |
| **09.01** | C 09.01 | OF 09.01 | Geographical breakdown SA |
| **09.02** | C 09.02 | OF 09.02 | Geographical breakdown IRB |

---

## Structural Summary

| Area | CRR (C templates) | Basel 3.1 (OF templates) |
|------|-------------------|--------------------------|
| **SA columns** | 24 (0010–0240) | 22 — adds 0035, 0171, 0235; removes 0215–0217 |
| **SA risk weight rows** | 15 (0%–1250% + Other) | 29 — adds 15 new granular weights, removes 370% |
| **SA "of which" rows** | 8 | 26+ — adds specialised lending and detailed RE breakdowns |
| **IRB columns** | 33 (0010–0310) | 40+ — adds netting, slotting CRM, defaults, post-model adj, output floor |
| **IRB approach filter** | Binary (Foundation / Advanced) | Three-way (FIRB / AIRB / Slotting) |
| **Supporting factors** | SME (Art 501) + Infrastructure (Art 501a) | **Removed** |
| **Double default** | Column 0220 | **Removed** |
| **Output floor** | Not applicable | Columns 0275–0276 (SA-equivalent for floor calculation) |
| **Post-model adjustments** | Not applicable | Columns 0251–0254 (RWEA), 0281–0282 (EL) |
| **CCF buckets (SA)** | 0%, 20%, 50%, 100% | 10%, 20%, 40%, 50%, 100% |
| **PD ranges (08.03) columns** | 11 (0010–0110) | 11 — col names updated (PD post input floor, LGD with floors, RWEA without factors) |
| **RWEA flow (08.04)** | 1 column, 9 rows | Virtually identical — supporting factors removed from RWEA description |
| **Slotting (08.06) columns** | 10 (0010–0100) | 11 — adds 0031 (FCCM change); supporting factors removed |
| **Slotting SL types** | 4 (PF, IPRE/HVCRE, OF, CF) | 5 — HVCRE separated from IPRE |
| **Scope of use (08.07) columns** | 5 (0010–0050) | 18 — adds RWEA breakdown by SA reason, IRB RWEA, materiality thresholds |
| **Scope of use rows** | 17 by exposure class | Restructured to roll-out classes (Art 147B) |
| **Geo SA (09.01) columns** | 13 (0010–0090) | 10 — removes 0080–0082 (supporting factors) |
| **Geo SA rows** | 18 by SA exposure class | Adds SL sub-rows, restructures RE rows (0091–0094), removes short-term |
| **Geo IRB (09.02) columns** | 17 (0010–0130) | 15 — removes supporting factors (0110, 0121, 0122); adds 0107 (defaulted) |
| **Geo IRB rows** | 15 by IRB exposure class | Adds corporate sub-rows (0048, 0049, 0055), restructures retail RE rows, removes equity |

---

## C 07.00 / OF 07.00 — CR SA

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0035 | On-balance sheet netting — separated from original exposure |
| **Added** | 0171 | 40% CCF bucket — new Basel 3.1 conversion factor |
| **Added** | 0235 | Unrated RWEA — separate reporting of exposures without ECAI |
| **Changed** | 0160 | CCF 0% bucket becomes **10%** (minimum 10% for unconditionally cancellable) |
| **Changed** | 0040 | Now also nets on-balance sheet netting (col 0035) |
| **Changed** | 0220 | No longer "after supporting factors" — factors removed |
| **Removed** | 0215 | RWEA pre supporting factors |
| **Removed** | 0216 | SME supporting factor adjustment |
| **Removed** | 0217 | Infrastructure supporting factor adjustment |

### Row Changes

#### Section 1 — "Of Which" Breakdowns

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0021–0026 | Specialised lending breakdown (object finance, commodities, project finance with pre-op/operational/HQOP) |
| **Added** | 0330–0360 | Detailed real estate breakdown (regulatory RRE/CRE with materiality and cash-flow dependency splits, ADC) |
| **Removed** | 0030 | SME supporting factor exposures |
| **Removed** | 0035 | Infrastructure supporting factor exposures |
| **Removed** | 0040 | Secured by residential mortgages (replaced by 0330–0360 breakdown) |

#### Section 3 — Risk Weight Bands

CRR defines **15** risk weight rows. Basel 3.1 expands to **29** rows:

| New Weights | Removed |
|-------------|---------|
| 15%, 25%, 30%, 40%, 45%, 60%, 65%, 80%, 85%, 105%, 110%, 130%, 135%, 400% | 370% |

The additional bands reflect Basel 3.1's more granular LTV-based real estate weights,
corporate sub-categories (investment grade 65%, SME 85%), and income-producing property
weights.

#### Section 4 — CIU Approach

CRR has **3** rows; Basel 3.1 has **5** — adds "of which: exposures to relevant CIUs"
sub-rows (0284, 0285) under look-through and mandate-based approaches.

#### Section 5 — Memorandum Items

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0371–0374 | Equity transitional items (SA/IRB higher risk and other equity) |
| **Added** | 0380 | Retail and RE subject to currency mismatch multiplier |
| **Removed** | 0290 | Secured by commercial RE (replaced by Section 1 breakdown) |
| **Removed** | 0310 | Secured by residential RE (replaced by Section 1 breakdown) |

---

## C 08.01 / OF 08.01 — CR IRB Totals

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0035 | On-balance sheet netting (same as OF 07.00) |
| **Added** | 0101–0104 | Financial Collateral Comprehensive Method columns for slotting approach |
| **Added** | 0125, 0265 | "Of which: defaulted" for exposure value and RWEA |
| **Added** | 0251–0254 | Post-model adjustment columns (pre-adj RWEA, post-model adj, mortgage RW floor, unrecognised exposure adj) |
| **Added** | 0275–0276 | Output floor columns (SA-equivalent exposure value and RWEA) |
| **Added** | 0281–0282 | Post-model adjustments to expected loss |
| **Removed** | 0010 | PD column — moved to OF 08.02 only |
| **Removed** | 0220 | Double default treatment (removed in Basel 3.1) |
| **Removed** | 0255–0257 | Supporting factor columns (SME and infrastructure factors removed) |

### Row Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0017 | Revolving loan commitments breakdown |
| **Added** | 0031–0035 | Off-balance sheet CCF bucket breakdown rows |
| **Added** | 0175 | Purchased receivables (explicit row) |
| **Added** | 0190, 0200 | Corporates without ECAI / investment grade (output floor) |
| **Removed** | 0015 | SME supporting factor |
| **Removed** | 0016 | Infrastructure supporting factor |
| **Removed** | 0160 | Alternative treatment: Secured by real estate |

---

## C 08.02 / OF 08.02 — CR IRB by Obligor Grade

| Change | Description |
|--------|-------------|
| **PD column** | Retained in OF 08.02 (removed from OF 08.01 totals only) |
| **CCF breakdown** | New columns 0001, 0101–0105 for off-BS items by CCF bucket |
| **PD ordering** | Basel 3.1 uses PDs without input floor adjustments |
| **Slotting excluded** | Slotting exposures reported separately in OF 08.06 |
| **Alt RE removed** | CRR exclusion for alternative RE treatment no longer applies |
| **Double default** | Column 0220 removed (same as OF 08.01) |
| **Supporting factors** | Columns 0255–0257 removed (same as OF 08.01) |
| **Post-model adj** | New columns 0251–0254, 0281–0282 (same as OF 08.01) |
| **Output floor** | New columns 0275–0276 (same as OF 08.01) |

---

## C 08.03 / OF 08.03 — CR IRB PD Ranges

This template aggregates IRB exposures into fixed PD range buckets for disclosure purposes.
It excludes slotting exposures (reported in C 08.06 / OF 08.06) and CCR exposures.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Changed** | 0050 | Renamed to "Exposure weighted average PD (post input floor)" — reflects new PD input floors (Art 160(1), 163(1)) |
| **Changed** | 0070 | LGD now explicitly includes CRM effects, input floors, and downturn conditions |
| **Changed** | 0090 | "RWEA" — no longer "after supporting factors" (factors removed) |

### Row Changes

| Change | Description |
|--------|-------------|
| **Changed** | PD range allocation now uses PDs **without** input floor adjustments (pre-floor PD determines bucket, post-floor PD used in calculation) |
| **Unchanged** | Same 17 fixed PD range rows (0010–0170) with identical sub-band structure |

---

## C 08.04 / OF 08.04 — CR IRB RWEA Flow Statements

This template reports quarter-over-quarter movements in IRB RWEA, decomposed into
seven driver categories. It excludes CCR exposures.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Changed** | 0010 | "RWEA" — no longer references supporting factors (Art 501, 501a removed) |

### Row Changes

No row changes. The same 9 rows (0010–0090) are used in both frameworks:
previous period RWEA, asset size, asset quality, model updates, methodology and policy,
acquisitions and disposals, FX movements, other, current period RWEA.

---

## C 08.06 / OF 08.06 — CR IRB Specialised Lending Slotting

This template reports specialised lending exposures subject to the supervisory slotting
criteria, broken down by slotting category and remaining maturity.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0031 | (-) Change in exposure due to FCCM — Financial Collateral Comprehensive Method adjustment |
| **Changed** | 0080 | "RWEA" — no longer "after supporting factors" (factors removed) |

### Row Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0015 | Category 1 "substantially stronger" sub-row (≥ 2.5 years only, 50% RW) |
| **Added** | 0025 | Category 2 "substantially stronger" sub-row (≥ 2.5 years only, 70% RW) |
| **Changed** | — | SL types expanded from 4 to 5: HVCRE separated from IPRE (previously combined). Types are now: object finance, project finance, commodities finance, IPRE, HVCRE |

---

## C 08.07 / OF 08.07 — CR IRB Scope of Use

This template reports the split of exposures between SA and IRB approaches, showing
coverage percentages and RWEA attribution. **Significantly expanded in Basel 3.1.**

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Unchanged** | 0010 | Total exposure value subject to IRB |
| **Unchanged** | 0020 | Total exposure value subject to SA and IRB |
| **Unchanged** | 0030 | % subject to permanent partial use of SA |
| **Unchanged** | 0040 | % subject to roll-out plan |
| **Unchanged** | 0050 | % subject to IRB approach |
| **Added** | 0060 | Total RWEA for exposures subject to SA or IRB |
| **Added** | 0070 | RWEA for SA: connected counterparties (Art 150(1)(e)) |
| **Added** | 0080 | RWEA for SA: all exposures in roll-out classes — SA does not result in significantly lower capital |
| **Added** | 0090 | RWEA for SA: all exposures in roll-out classes — cannot reasonably model |
| **Added** | 0100 | RWEA for SA: all exposures in roll-out classes — immaterial |
| **Added** | 0110 | RWEA for SA: all exposures in types — cannot reasonably model |
| **Added** | 0120 | RWEA for SA: all exposures in types — immaterial in aggregate |
| **Added** | 0130 | RWEA for SA: due to roll-out plan |
| **Added** | 0140 | RWEA for SA: other |
| **Added** | 0150 | RWEA for exposures subject to IRB |
| **Added** | 0160 | Materiality of roll-out class (Art 150(1A)(c) threshold) |
| **Added** | 0170 | % subject to permanent partial use (type of exposures) |
| **Added** | 0180 | % subject to permanent partial use (immaterial in aggregate) |

### Row Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Changed** | 0180–0250 | Rows restructured from **exposure classes** (CRR Art 147(2)) to **roll-out classes** (Basel 3.1 Art 147B). Roll-out classes align with the exposure classes but the regulatory basis differs. |
| **Added** | 0260 | Total row (sum of 0180–0250) |
| **Added** | 0270 | Percentage subject to permanent partial use (immateriality in aggregate) |
| **Removed** | 0010–0170 | CRR exposure class rows replaced by roll-out class structure |

---

## C 09.01 / OF 09.01 — CR GB 1 (Geographical Breakdown SA)

This template provides a geographical breakdown of SA exposures by country of obligor
residence. Submitted once at total level and once per material country.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0075 | Exposure value (was implicit in CRR, now explicit column ref) |
| **Removed** | 0080 | RWEA pre supporting factors |
| **Removed** | 0081 | (-) SME supporting factor adjustment |
| **Removed** | 0082 | (-) Infrastructure supporting factor adjustment |
| **Changed** | 0090 | "Risk-weighted exposure amount" — no longer "after supporting factors" |

### Row Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0071 | of which: specialised lending — object finance (under corporates) |
| **Added** | 0072 | of which: specialised lending — commodities finance |
| **Added** | 0073 | of which: specialised lending — project finance |
| **Changed** | 0090 | Renamed from "Secured by mortgages on immovable property" to "Real estate exposures" |
| **Added** | 0091 | of which: regulatory residential real estate |
| **Added** | 0092 | of which: regulatory commercial real estate |
| **Added** | 0093 | of which: other real estate |
| **Added** | 0094 | of which: land acquisition, development and construction |
| **Changed** | 0150 | Renamed from "Equity exposures" to "Subordinated debt, equity and other own funds instruments" |
| **Removed** | 0130 | Claims on institutions and corporates with a short-term credit assessment |

---

## C 09.02 / OF 09.02 — CR GB 2 (Geographical Breakdown IRB)

This template provides a geographical breakdown of IRB exposures by country of obligor
residence. Submitted once at total level and once per material country.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0107 | Of which: defaulted (exposure value for defaulted exposures) |
| **Removed** | 0110 | RWEA pre supporting factors |
| **Removed** | 0121 | (-) SME supporting factor adjustment |
| **Removed** | 0122 | (-) Infrastructure supporting factor adjustment |
| **Changed** | 0125 | "Risk-weighted exposure amount" — no longer "after supporting factors" |

### Row Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Added** | 0048 | Financial corporates and large corporates (Art 147(4C)) |
| **Added** | 0049 | Purchased receivables (corporate, Art 157) |
| **Changed** | 0050 | Renamed from "Of Which: SME" to "Other general corporates — SME" (Art 147(4E)(c)) |
| **Added** | 0055 | Other general corporates — non-SME (Art 147(4E)) |
| **Changed** | 0071–0074 | Retail RE restructured: residential RE SME (0071), residential RE non-SME (0072), commercial RE SME (0073), commercial RE non-SME (0074) — replaces CRR rows 0070/0080/0090 |
| **Added** | 0105 | Retail — purchased receivables (Art 157) |
| **Removed** | 0140 | Equity row removed (equity no longer an IRB exposure class under Basel 3.1) |

---

## C 02.00 / OF 02.00 — Own Funds Requirements (CA2)

This is the master template aggregating RWEA across all risk types. Under Basel 3.1, it
gains two new columns for the output floor calculation — this is where the floor is
actually applied at the total capital level.

### Column Changes

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Unchanged** | 0010 | All approaches — RWEA using actual modelled/SA mix |
| **Added** | 0020 | Standardised approaches only — SA-equivalent RWEA per row (for floor comparison) |
| **Added** | 0030 | Output floor — RWEA after applying floor multiplier and OF-ADJ per Art. 92 |

Under CRR, C 02.00 had only column 0010. The two new columns enable the supervisory
comparison between modelled and standardised RWEA at each row level.

### Row Changes — Credit Risk

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Restructured** | 0240–0297 | F-IRB rows now broken out by subclass: institutions (0271), corporates — specialised lending (0290), financial/large corporates (0295), other general SME (0296), other general non-SME (0297) |
| **Restructured** | 0310–0410 | A-IRB rows broken out: corporates — specialised lending (0350), other general SME (0355), non-SME (0356); retail — RIP SME (0382), RIP non-SME (0383), CRE SME (0384), CRE non-SME (0385), QRRE (0390), other SME (0400), other non-SME (0410) |
| **Added** | 0411–0416 | Slotting separated from IRB: PF (0412), OF (0413), CF (0414), IPRE (0415), HVCRE (0416) |
| **Added** | 0131 | SA corporates — of which: specialised lending |
| **Unchanged** | 0070–0211 | SA exposure class breakdown (central govts through other items) |

### Row Changes — Non-Credit Risk

| Change | Ref(s) | Description |
|--------|--------|-------------|
| **Expanded** | 0530–5898 | Market risk rows expanded: SSA (0530), ASA for ASA desks (0571), IMA (0580), ASA for all desks / output floor (5860), ASA for IMA desks (5870) |
| **Added** | 5898 | Capital charge for switching positions between trading and non-trading book |
| **Restructured** | 0640–0643 | CVA risk broken out: SA (0641), BA (0642), AA (0643) |

### How the Output Floor Flows Through

```
OF 08.01 / 08.02 cols 0275–0276     →  SA-equivalent RWEA per IRB exposure class
  ↓ aggregated into
OF 02.00 col 0020 (SA-only RWEA)    →  S-TREA components by risk type
  ↓ compared against
OF 02.00 col 0010 (all approaches)  →  U-TREA components by risk type
  ↓ floor applied
OF 02.00 col 0030 (output floor)    →  TREA = max(U-TREA, x × S-TREA + OF-ADJ)
```

---

## OF 02.01 — Output Floor (New)

A **new** template with no CRR equivalent. Provides the output floor comparison at the
total risk type level for firms using internal models. This template does NOT apply the
floor multiplier — it provides the raw comparison data. The actual floor application
happens in OF 02.00 column 0030.

**Scope:** OF 02.01 is required for IM firms in scope of the output floor, applied on:

- consolidated basis at the UK group level
- individual basis for UK standalone firms
- sub-consolidated basis for ring-fenced bank (RFB) sub-groups

### Columns

| Ref | Description |
|-----|-------------|
| 0010 | RWA for modelled approaches only |
| 0020 | RWA for portfolios on standardised approaches |
| 0030 | Total RWA (**U-TREA**) = col 0010 + col 0020 |
| 0040 | Standardised total RWA (**S-TREA**) — entire portfolio recalculated using SA only, **without** floor multiplier |

### Rows

| Ref | Description |
|-----|-------------|
| 0010 | Credit risk (excluding CCR) |
| 0020 | Counterparty credit risk |
| 0030 | Credit valuation adjustment |
| 0040 | Securitisation exposures (banking book) |
| 0050 | Market risk |
| 0060 | Operational risk |
| 0070 | Residual RWA (equity in funds, settlement risk, etc.) |
| 0080 | **Total** (sum of rows 0010–0070) |

The floor is then calculated externally:
`TREA = max(row 0080 col 0030, x × row 0080 col 0040 + OF-ADJ)` where `x` is the
transitional floor percentage (50% in 2027 → 72.5% in 2032+).

### Relationship to Pillar III Disclosure

| COREP (Supervisory) | Pillar III (Public) | Relationship |
|---------------------|---------------------|-------------|
| OF 02.00 col 0030 (output floor RWEA) | UKB OV1 row 29 (total RWEA) | Final floored RWEA |
| OF 02.01 row 0080 col 0030 (U-TREA) | UKB KM1 row 4a (pre-floor RWEA) | Un-floored total |
| Floor multiplier (Art. 92(5)) | UKB OV1 row 26 | Output floor % |
| Floor adjustment (OF-ADJ) | UKB OV1 row 27 | Provision reconciliation |

---

## Key Themes

The template changes across all nine credit risk templates reflect five Basel 3.1 themes:

1. **Removal of capital relief mechanisms** — supporting factor columns removed across all
   templates: SA (0215–0217), IRB (0255–0257), slotting (0080), PD ranges (0090),
   geographical SA (0080–0082), geographical IRB (0110, 0121–0122). Double default (0220)
   also removed.
2. **Output floor infrastructure** — new columns (0275–0276) in IRB templates report
   SA-equivalent values for floor calculation. These feed into **OF 02.00** columns 0020/0030
   (output floor at total capital level) and the new **OF 02.01** template (U-TREA vs S-TREA
   comparison).
3. **Greater granularity** — expanded SA risk weight bands (15 → 29), detailed real estate
   breakdowns replacing broad mortgage rows (OF 07.00 rows 0330–0360, OF 09.01 rows
   0091–0094), specialised lending sub-categories across SA and IRB geo breakdowns,
   new corporate sub-rows in OF 09.02 (financial corporates, purchased receivables).
4. **Post-model oversight** — new adjustment columns (0251–0254, 0281–0282) in IRB
   templates capture model overlays and regulatory floors separately from raw model output.
5. **Expanded scope-of-use transparency** — OF 08.07 expands from 5 to 18 columns,
   requiring firms to decompose their SA RWEA by reason for SA use (connected
   counterparties, immaterial exposures, roll-out plan, etc.) and report materiality
   thresholds. Rows restructured from exposure classes to roll-out classes (Art 147B).

## See Also

- [Full COREP template specification](../features/corep-reporting.md) — complete column
  and row definitions with source code references
- [Key Differences](key-differences.md) — regulatory parameter comparison
- [Reporting API](../api/reporting.md) — `COREPGenerator` and `COREPTemplateBundle` classes
