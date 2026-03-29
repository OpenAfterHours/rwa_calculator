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
- **C 07.00 / OF 07.00** — CR SA: one submission per SA exposure class. 24 columns (CRR) / 22 columns (Basel 3.1) covering original exposure, provisions, CRM substitution effects, Financial Collateral Comprehensive Method, CCF breakdown, exposure value, and RWEA. 5 row sections: totals, exposure types (on-BS/off-BS/CCR), risk weights (15 bands CRR / 29 bands Basel 3.1), CIU approach, memorandum items.
- **C 08.01 / OF 08.01** — CR IRB totals: one submission per IRB exposure class × own-estimates filter. 33 columns (CRR) / 40+ columns (Basel 3.1) covering PD, original exposure, CRM substitution effects, CRM in LGD estimates (detailed collateral breakdown), exposure value, LGD, maturity, RWEA, expected loss, provisions, obligor count. Basel 3.1 adds post-model adjustment and output floor columns.
- **C 08.02 / OF 08.02** — CR IRB by obligor grade: same columns as C 08.01 with dynamic rows (one per firm-specific internal rating grade/pool, ordered by PD).

### Reference Documents
- `docs/assets/corep-own-funds.xlsx` — CRR template layouts (sheets "7", "8.1", "8.2")
- `docs/assets/annex-ii-instructions-for-reporting-on-own-funds.pdf` — CRR reporting instructions
- `docs/assets/annex-i-of-07-00-credit-risk-sa-reporting-template.xlsx` — Basel 3.1 OF 07.00 layout
- `docs/assets/annex-ii-reporting-instructions.pdf` — Basel 3.1 reporting instructions

### Status
- Generator: Needs rework — current implementation uses simplified column set and one-row-per-class structure. See `IMPLEMENTATION_PLAN.md` for phased rework plan.
- Template definitions: Needs rework — column refs and row structure don't match actual EBA/PRA templates.
- Excel export: Needs update to match per-exposure-class template structure.
- Integration: Done (`ResultExporter.export_to_corep()`, `CalculationResponse.to_corep()`)
- Tests: Need rewrite to validate correct template structure.
- Detailed feature docs: Done — see [COREP Reporting](../features/corep-reporting.md)

## Export

### Status
- Parquet export: Done
- CSV export: Done
- Excel (XLSX) export via xlsxwriter: Done
