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
Regulatory reporting templates for CRR firms following EBA/PRA COREP structure (Regulation (EU) 2021/451).

### Templates
- **C 07.00** — SA credit risk: original exposure, SA EAD, RWA by exposure class. Plus risk weight band breakdown.
- **C 08.01** — IRB totals: original exposure, IRB EAD, RWA, EL, weighted-average PD/LGD/maturity by exposure class.
- **C 08.02** — IRB PD grade breakdown: obligor-grade-level detail with PD bands, exposure-weighted averages.

### Status
- Generator: Done (`reporting/corep/generator.py`)
- Template definitions: Done (`reporting/corep/templates.py`)
- Excel export: Done (multi-sheet via xlsxwriter)
- Integration: Done (`ResultExporter.export_to_corep()`, `CalculationResponse.to_corep()`)
- Tests: 48 passed + 4 conditional (xlsxwriter)

## Export

### Status
- Parquet export: Done
- CSV export: Done
- Excel (XLSX) export via xlsxwriter: Done
