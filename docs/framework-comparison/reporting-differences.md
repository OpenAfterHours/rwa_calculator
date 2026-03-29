# Reporting Differences

Under Basel 3.1, COREP credit risk templates are renamed from the **C** prefix to **OF**
(Own Funds) and undergo significant structural changes. This page summarises the key
differences. For complete column and row definitions, see the
[full COREP template specification](../features/corep-reporting.md).

## Template Overview

| Template | CRR Name | Basel 3.1 Name | Purpose |
|----------|----------|----------------|---------|
| **07.00** | C 07.00 | OF 07.00 | SA credit risk |
| **08.01** | C 08.01 | OF 08.01 | IRB totals |
| **08.02** | C 08.02 | OF 08.02 | IRB by obligor grade |
| **08.03** | — | OF 08.03 | Slotting approach (**new**) |

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
| **Slotting excluded** | Slotting exposures reported separately (new OF 08.03) |
| **Alt RE removed** | CRR exclusion for alternative RE treatment no longer applies |
| **Double default** | Column 0220 removed (same as OF 08.01) |
| **Supporting factors** | Columns 0255–0257 removed (same as OF 08.01) |
| **Post-model adj** | New columns 0251–0254, 0281–0282 (same as OF 08.01) |
| **Output floor** | New columns 0275–0276 (same as OF 08.01) |

---

## Key Themes

The template changes reflect four Basel 3.1 themes:

1. **Removal of capital relief mechanisms** — supporting factor columns (0215–0217, 0255–0257)
   and double default (0220) are removed
2. **Output floor infrastructure** — new columns (0275–0276) report SA-equivalent values
   for floor calculation
3. **Greater granularity** — expanded risk weight bands (15 → 29), detailed real estate
   breakdowns (8 → 26+ "of which" rows), specialised lending sub-categories
4. **Post-model oversight** — new adjustment columns (0251–0254, 0281–0282) capture
   model overlays and regulatory floors separately from raw model output

## See Also

- [Full COREP template specification](../features/corep-reporting.md) — complete column
  and row definitions with source code references
- [Key Differences](key-differences.md) — regulatory parameter comparison
- [Reporting API](../api/reporting.md) — `COREPGenerator` and `COREPTemplateBundle` classes
