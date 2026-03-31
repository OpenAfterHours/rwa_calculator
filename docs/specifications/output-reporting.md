# Output & Reporting

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-4.1 | Aggregated RWA by approach (SA, F-IRB, A-IRB, Slotting, Equity) | P0 | Done |
| FR-4.2 | Aggregated RWA by exposure class (9 classes) | P0 | Done |
| FR-4.3 | Basel 3.1 output floor calculation with transitional phase-in schedule | P1 | Done |
| FR-4.4 | Pre/post-CRM RWA breakdown with guarantee benefit attribution | P1 | Done |
| FR-4.5 | Exposure-level detail output with all intermediate calculations | P1 | Done |
| FR-4.6 | COREP template generation (CRR reporting) | P3 | Done |
| FR-4.7 | Excel / Parquet export of results | P2 | Done |

## Output Floor (Basel 3.1)

### Description
IRB RWA must be at least X% of what SA-equivalent RWA would produce. Transitional phase-in:

| Year | Floor Percentage |
|------|-----------------|
| 2027 | 50% |
| 2028 | 55% |
| 2029 | 60% |
| 2030 | 65% |
| 2031 | 70% |
| 2032+ | 72.5% |

### Status
- Engine implemented — Done
- Phase-in schedule validation tests — Done (6 acceptance tests in `test_scenario_b31_f_output_floor.py`)

## COREP Templates

### Description
Regulatory reporting templates for CRR / Basel 3.1 firms following the EBA/PRA COREP structure.
CRR templates use the **C** prefix (Regulation (EU) 2021/451); Basel 3.1 templates use the **OF**
prefix (PRA PS1/26).

Each template is submitted **once per exposure class** — the exposure class acts as a filter, not
a row dimension. Within each submission, rows are organised into sections (totals, exposure type
breakdown, risk weight breakdown, memorandum items).

### Templates
- **C 02.00 / OF 02.00** — Own Funds Requirements: master template aggregating RWEA across all risk types. 1 column (CRR) / 3 columns (Basel 3.1). Basel 3.1 adds col 0020 (SA-only RWEA for floor comparison) and col 0030 (output floor RWEA after applying floor multiplier and OF-ADJ). Rows restructured: FIRB/AIRB/Slotting separated, corporate and retail subclass breakdowns added, slotting by 5 SL types, market risk expanded for ASA/IMA.
- **OF 02.01** — Output Floor (**new**, no CRR equivalent): dedicated output floor comparison for IM firms. 4 columns: modelled RWA (0010), SA portfolio RWA (0020), U-TREA (0030), S-TREA (0040). 8 rows by risk type (credit, CCR, CVA, securitisation, market, op risk, residual, total). Does not apply the floor multiplier — provides raw comparison data for OF 02.00.
- **C 07.00 / OF 07.00** — CR SA: one submission per SA exposure class. 24 columns (CRR) / 22 columns (Basel 3.1) covering original exposure, provisions, CRM substitution effects, Financial Collateral Comprehensive Method, CCF breakdown, exposure value, and RWEA. 5 row sections: totals, exposure types (on-BS/off-BS/CCR), risk weights (15 bands CRR / 29 bands Basel 3.1), CIU approach, memorandum items.
- **C 08.01 / OF 08.01** — CR IRB totals: one submission per IRB exposure class × own-estimates filter. 33 columns (CRR) / 40+ columns (Basel 3.1) covering PD, original exposure, CRM substitution effects, CRM in LGD estimates (detailed collateral breakdown), exposure value, LGD, maturity, RWEA, expected loss, provisions, obligor count. Basel 3.1 adds post-model adjustment and output floor columns.
- **C 08.02 / OF 08.02** — CR IRB by obligor grade: same columns as C 08.01 with dynamic rows (one per firm-specific internal rating grade/pool, ordered by PD).
- **C 08.03 / OF 08.03** — CR IRB PD ranges: one submission per IRB exposure class. 11 columns covering on/off-BS, avg CCF, exposure value, avg PD, obligors, avg LGD, avg maturity, RWEA, EL, provisions. Rows are 17 fixed PD range buckets (0.00–0.15 through 100% default). Basel 3.1: PD and LGD columns reflect input floors, supporting factors removed, slotting excluded.
- **C 08.04 / OF 08.04** — CR IRB RWEA flow statements: one submission per IRB exposure class. 1 column (RWEA), 9 rows (previous period, 7 movement categories, current period). Virtually identical between CRR and Basel 3.1 (supporting factors no longer mentioned).
- **C 08.06 / OF 08.06** — CR IRB specialised lending slotting: one submission per SL type. 10 columns (CRR) / 11 columns (Basel 3.1 adds FCCM). Rows by slotting category (1–5) × maturity band. Basel 3.1 adds "substantially stronger" sub-categories and separates HVCRE from IPRE (5 SL types vs 4).
- **C 08.07 / OF 08.07** — CR IRB scope of use: one submission covering all exposure/roll-out classes. 5 columns (CRR) / 18 columns (Basel 3.1 — significantly expanded with RWEA breakdown by SA reason and materiality thresholds). Rows change from exposure classes to roll-out classes (Art 147B).
- **C 09.01 / OF 09.01** — CR GB 1 geographical breakdown SA: one submission per country. 13 columns (CRR) / 10 columns (Basel 3.1) covering original exposure, defaults, provisions, exposure value, RWEA. Rows by SA exposure class. Basel 3.1: supporting factor columns removed, real estate rows restructured (regulatory residential/commercial RE sub-rows).
- **C 09.02 / OF 09.02** — CR GB 2 geographical breakdown IRB: one submission per country. 17 columns (CRR) / 15 columns (Basel 3.1) covering exposure, defaults, provisions, PD, LGD, RWEA, EL. Basel 3.1: adds defaulted exposure value column, removes supporting factors, adds corporate sub-rows, restructures retail RE rows, removes equity.

### Reference Documents
- `docs/assets/CRR - corep-own-funds.xlsx` — CRR template layouts (sheets "7", "8.1", "8.2", "8.3", "8.4", "8.6", "8.7", "9.1", "9.2")
- `docs/assets/crr-annex-ii-reporting-instructins.pdf` — CRR reporting instructions
- `docs/assets/0F07 - annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx` — Basel 3.1 OF 07.00 layout
- `docs/assets/OF0801-annex-i-of-08-01-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.01 layout
- `docs/assets/OF0802-annex-i-of-08-02-credit-risk-irb-reporting-template.xlsx` — Basel 3.1 OF 08.02 layout
- `docs/assets/ps1-26-annex-ii-reporting-instructions.pdf` — Basel 3.1 reporting instructions

### Status
- Generator: Needs rework — current implementation uses simplified column set and one-row-per-class structure. Covers C 07.00, C 08.01, C 08.02 only. Templates 08.03–09.02 are documented but not yet implemented in the generator.
- Template definitions: Needs rework — column refs and row structure don't match actual EBA/PRA templates.
- Excel export: Needs update to match per-exposure-class template structure.
- Integration: Done (`ResultExporter.export_to_corep()`, `CalculationResponse.to_corep()`)
- Tests: Need rewrite to validate correct template structure.
- Detailed feature docs: Done — see [COREP Reporting](../features/corep-reporting.md) (all 9 templates documented)

## Pillar III Disclosure Templates

### Description
Public disclosure templates under CRR Part 8 / Disclosure (CRR) Part for market transparency.
CRR templates use the **UK** prefix; Basel 3.1 templates use the **UKB** prefix. These complement
COREP supervisory returns with publicly available credit risk data.

### Templates
- **OV1** — Overview of risk-weighted exposure amounts (Art. 438(d))
- **CR4** — SA exposure and CRM effects (Art. 444(e), 453(g-i))
- **CR5** — SA risk weight allocation (Art. 444(e))
- **CR6** — IRB exposures by exposure class and PD range (Art. 452(g))
- **CR6-A** — Scope of IRB and SA use (Art. 452(b))
- **CR7** — Credit derivatives effect on RWEA (Art. 453(j))
- **CR7-A** — Extent of CRM techniques for IRB (Art. 453(g))
- **CR8** — RWEA flow statements for IRB (Art. 438(h))
- **CR10** — Slotting approach exposures (Art. 438(e))

### Reference Documents
- CRR: `docs/assets/crr-annex-xx-instructions-regarding-disclosure.PDF`, `crr-pillar3-irb-credit-risk-instructions.pdf`, `crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf`, `crr-pillar3-specialised-lending-instructions.pdf`
- Basel 3.1: `docs/assets/ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf`, `ps1-26-annex-xxii-credit-risk-irb-disclosure-instructions.pdf`, `ps1-26-annex-xxiv-credit-risk-irb-disclosure-instructions.pdf`, `ps1-26-annex-ii-output-floor-and-capital-summaries-disclosure-instructions.pdf`

### Status
- Documentation: Done — see [Pillar III Disclosures](../features/pillar3-disclosures.md)
- Code implementation: Not started

## Export

### Status
- Parquet export: Done
- CSV export: Done
- Excel (XLSX) export via xlsxwriter: Done
