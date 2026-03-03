# COREP Reporting

The RWA Calculator generates COREP (COmmon REPorting) credit risk templates for regulatory
submissions. These templates follow the EBA DPM taxonomy as defined in Regulation (EU) 2021/451.

## Why COREP Matters

UK-regulated banks submit quarterly COREP returns to the PRA as part of ongoing supervisory
reporting. The credit risk templates require firms to aggregate their exposure-level RWA
calculations into standardised row/column formats by exposure class. Manual aggregation is
error-prone and audit-unfriendly — generating templates directly from calculation results
ensures consistency between the RWA engine output and the reported figures.

## Supported Templates

| Template | Title | Purpose |
|----------|-------|---------|
| **C 07.00** | CR SA | SA credit risk — one row per SA exposure class. Columns: original exposure, provisions, EAD, RWA, CRM funded/unfunded, ECAI-rated RWA. |
| **C 07.00 RW** | CR SA Risk Weight Breakdown | SA exposure value pivoted by 14 standard risk weight bands (0% to 1250%). |
| **C 08.01** | CR IRB Totals | IRB totals — one row per IRB exposure class. EAD-weighted average PD, LGD, maturity; totals for EAD, RWA, expected loss, obligor count. |
| **C 08.02** | CR IRB by PD Grade | Same columns as C 08.01, disaggregated by 8 PD bands per exposure class. |

## Template Structure

### C 07.00 Row Mapping

Each SA exposure class maps to a COREP row reference:

| Row Ref | Exposure Class | Description |
|---------|---------------|-------------|
| 0010 | `central_govt_central_bank` | Central governments or central banks |
| 0020 | `rgla` | Regional governments or local authorities |
| 0030 | `pse` | Public sector entities |
| 0040 | `mdb` | Multilateral development banks |
| 0060 | `institution` | Institutions |
| 0070 | `corporate` | Corporates |
| 0071 | `corporate_sme` | Of which: SME corporates |
| 0080 | `retail_mortgage` | Secured by mortgages on immovable property |
| 0090 | `retail_other` | Retail |
| 0091 | `retail_qrre` | Of which: Qualifying revolving |
| 0100 | `defaulted` | Exposures in default |
| 0110 | `equity` | Equity exposures |
| 0120 | `other` | Other items |
| 0000 | `TOTAL` | Portfolio total (auto-generated) |

### C 07.00 Columns (CRR Art. 112–134)

| Col Ref | Column | Source |
|---------|--------|--------|
| 010 | Original exposure pre conversion factors | `drawn_amount + undrawn_amount` |
| 020 | (-) Value adjustments and provisions | `scra_provision_amount + gcra_provision_amount` |
| 030 | Exposure net of value adjustments and provisions | Column 010 - Column 020 |
| 040 | (-) Funded credit protection (collateral) | `collateral_adjusted_value` |
| 050 | (-) Unfunded credit protection (guarantees) | `guaranteed_portion` |
| 060 | Net exposure after CRM substitution effects | Original - provisions - funded - unfunded |
| 070 | Exposure value (E*) post CCF | `ead_final` |
| 080 | Risk weighted exposure amount (RWEA) | `rwa_final` |
| 090 | Of which: with ECAI credit assessment | RWA where `sa_cqs` is not null |

### C 07.00 Risk Weight Bands

The breakdown template pivots exposure value across 14 standard risk weight bands:

0%, 2%, 4%, 10%, 20%, 35%, 50%, 70%, 75%, 100%, 150%, 250%, 370%, 1250%, Other.

### C 08.01/C 08.02 IRB Row Mapping

| Row Ref | Exposure Class | Description |
|---------|---------------|-------------|
| 0010 | `central_govt_central_bank` | Central governments and central banks |
| 0020 | `institution` | Institutions |
| 0030 | `corporate` | Corporates — Other |
| 0040 | `corporate_sme` | Corporates — SME |
| 0050 | `specialised_lending` | Corporates — Specialised lending |
| 0060 | `retail_mortgage` | Retail — Secured by immovable property |
| 0070 | `retail_qrre` | Retail — Qualifying revolving (QRRE) |
| 0080 | `retail_other` | Retail — Other |
| 0000 | `TOTAL` | Portfolio total (auto-generated) |

### C 08.01 Columns (CRR Art. 142–191)

| Col Ref | Column | Calculation |
|---------|--------|-------------|
| 010 | Weighted average PD (%) | EAD-weighted average of `irb_pd_floored` |
| 020 | Original exposure pre conversion factors | `drawn_amount + undrawn_amount` |
| 030 | (-) Value adjustments and provisions | `scra_provision_amount + gcra_provision_amount` |
| 040 | Exposure value (EAD) | `ead_final` |
| 050 | Exposure-weighted average LGD (%) | EAD-weighted average of `irb_lgd_floored` |
| 060 | Exposure-weighted average maturity (years) | EAD-weighted average of `irb_maturity_m` |
| 070 | Risk weighted exposure amount (RWEA) | `rwa_final` |
| 080 | Expected loss amount | `irb_expected_loss` |
| 090 | (-) Provisions allocated | `provision_held` |
| 100 | Number of obligors | `n_unique()` of `counterparty_reference` |
| 110 | EL shortfall (-) / excess (+) | `el_excess - el_shortfall` |

### C 08.02 PD Bands

C 08.02 disaggregates C 08.01 into 8 PD bands:

| PD Band | Range |
|---------|-------|
| Band 1 | 0.00% – 0.15% |
| Band 2 | 0.15% – 0.25% |
| Band 3 | 0.25% – 0.50% |
| Band 4 | 0.50% – 0.75% |
| Band 5 | 0.75% – 2.50% |
| Band 6 | 2.50% – 10.00% |
| Band 7 | 10.00% – 99.99% |
| Band 8 | Default (100%) |

## Usage

### Generate from Pipeline Results

```python
from rwa_calc.reporting import COREPGenerator

generator = COREPGenerator()

# From a LazyFrame of calculation results
bundle = generator.generate_from_lazyframe(results, framework="CRR")

# From a CalculationResponse (uses cached Parquet)
bundle = generator.generate(response)

# Access templates as DataFrames
print(bundle.c07_00)      # C 07.00 SA credit risk
print(bundle.c08_01)      # C 08.01 IRB totals
print(bundle.c08_02)      # C 08.02 IRB by PD grade
print(bundle.c07_rw_breakdown)  # C 07.00 risk weight breakdown
```

### Export to Excel

```python
from pathlib import Path
from rwa_calc.reporting import COREPGenerator

generator = COREPGenerator()
bundle = generator.generate_from_lazyframe(results)

# Export multi-sheet Excel workbook
result = generator.export_to_excel(bundle, Path("corep_templates.xlsx"))
# Creates sheets: "C 07.00", "C 07.00 RW Breakdown", "C 08.01", "C 08.02"

print(result.format)      # "corep_excel"
print(result.row_count)   # Total rows across all sheets
```

!!! note "Excel dependency"
    Excel export requires `xlsxwriter`. Install via `uv add xlsxwriter`.

### Total Row

C 07.00, C 07.00 RW, and C 08.01 automatically include a total row (`row_ref="0000"`).
Numeric columns are summed; weighted average columns (PD, LGD, maturity) are set to `None`
in the total row because weighted averages cannot be meaningfully summed. C 08.02 does not
include a total row since it disaggregates by PD band within each exposure class.

## Regulatory References

| Reference | Topic |
|-----------|-------|
| Regulation (EU) 2021/451, Annex I | COREP template layouts |
| Regulation (EU) 2021/451, Annex II | COREP reporting instructions |
| CRR Art. 112–134 | SA exposure classes and risk weights |
| CRR Art. 142–191 | IRB exposure classes and capital requirements |
| PRA CP16/22 Chapter 12 | Basel 3.1 reporting amendments |
