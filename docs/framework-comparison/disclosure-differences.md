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
| **CR6 F-IRB breakdown** | Corporates: SME, SL, other | Adds **financial corporates and large corporates** |
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

---

## CR6-A — Scope of IRB/SA Use

| Change | Description |
|--------|-------------|
| **Changed** | Row structure based on **roll-out classes** (Art. 147B) instead of exposure classes |
| **Changed** | IRB approach column includes F-IRB, A-IRB, and slotting (no longer includes equity simple RW) |

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
