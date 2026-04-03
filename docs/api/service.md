# Service API

The Service API is the recommended entry point for RWA calculations. It wraps the
low-level pipeline with a clean facade that handles configuration, data loading,
validation, caching, and result formatting.

**Import path:** `from rwa_calc.api import ...`

## CreditRiskCalc

Single entry point for credit risk RWA calculations. Takes all parameters in the
constructor and exposes `calculate()` and `validate()` methods.

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

response = CreditRiskCalc(
    data_path="/path/to/data",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    permission_mode="irb",
).calculate()
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_path` | `str \| Path` | *required* | Path to directory containing input data files |
| `framework` | `"CRR" \| "BASEL_3_1"` | *required* | Regulatory framework |
| `reporting_date` | `date` | *required* | As-of date for the calculation |
| `permission_mode` | `"standardised" \| "irb"` | `"standardised"` | Permission mode (see table below) |
| `data_format` | `"parquet" \| "csv"` | `"parquet"` | Format of input files |
| `base_currency` | `str` | `"GBP"` | Reporting currency |
| `eur_gbp_rate` | `Decimal` | `0.8732` | EUR/GBP exchange rate |
| `cache_dir` | `Path \| None` | temp dir | Directory for caching result parquet files |

**Permission mode options:**

| Value | Description |
|-------|-------------|
| `"standardised"` | All exposures use the Standardised Approach (default) |
| `"irb"` | Approach routing is driven by the `model_permissions` input table. Each model's approved approach (AIRB, FIRB, slotting) is resolved per-exposure. Exposures without a matching model permission fall back to SA. |

!!! note "Model permissions required for IRB mode"
    When `permission_mode="irb"`, the calculator requires `model_permissions` input data
    to determine which exposures use FIRB, AIRB, or slotting. Models are linked to
    counterparties via `model_id` on the **ratings schema**. The rating inheritance
    pipeline flows `model_id` through to exposures. Exposures without a matching model
    permission fall back to SA. If no `model_permissions` file is provided, all exposures
    fall back to SA with a warning. See
    [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema)
    for the schema.

### Methods

#### calculate

Run the RWA calculation.

```python
response = calc.calculate()
```

**Returns:** `CalculationResponse`

#### validate

Validate the data path for calculation readiness.

```python
validation = calc.validate()
```

**Returns:** `ValidationResponse`

### Examples

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

# CRR with SA only
response = CreditRiskCalc(
    data_path="/data/exposures",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
).calculate()

# Basel 3.1 with IRB
response = CreditRiskCalc(
    data_path="/data/exposures",
    framework="BASEL_3_1",
    reporting_date=date(2027, 1, 1),
    permission_mode="irb",
).calculate()

# CSV input
response = CreditRiskCalc(
    data_path="/data/csv-exports",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    data_format="csv",
).calculate()
```

---

## Module Functions

### get_supported_frameworks

List available regulatory frameworks.

```python
from rwa_calc.api import get_supported_frameworks

frameworks = get_supported_frameworks()
# [{"id": "CRR", "name": "CRR (Basel 3.0)", ...}, ...]
```

**Returns:** `list[dict[str, str]]`

### get_default_config

Get default configuration values for a framework.

```python
from rwa_calc.api import get_default_config

defaults = get_default_config("CRR", date(2026, 12, 31))
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `framework` | `"CRR" \| "BASEL_3_1"` | Regulatory framework |
| `reporting_date` | `date` | As-of date |

**Returns:** `dict` with keys like `framework`, `reporting_date`, `pd_floors`, etc.

---

## Request Models

### ValidationRequest

Request for data path validation.

```python
from rwa_calc.api import ValidationRequest

request = ValidationRequest(
    data_path="/path/to/data",
    data_format="parquet",
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `data_path` | `str \| Path` | *required* | Directory to validate |
| `data_format` | `"parquet" \| "csv"` | `"parquet"` | Expected file format |

---

## Response Models

### CalculationResponse

Main response from `CreditRiskCalc.calculate()`.

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether calculation completed without critical errors |
| `framework` | `str` | Framework used |
| `reporting_date` | `date` | As-of date |
| `summary` | `SummaryStatistics` | Aggregated summary metrics |
| `results_path` | `Path` | Path to cached results parquet |
| `errors` | `list[APIError]` | Errors and warnings |
| `performance` | `PerformanceMetrics \| None` | Timing metrics |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `scan_results()` | `pl.LazyFrame` | Lazy-scan the results parquet |
| `collect_results()` | `pl.DataFrame` | Collect full results into memory |
| `scan_summary_by_class()` | `pl.LazyFrame \| None` | Lazy-scan class summary |
| `scan_summary_by_approach()` | `pl.LazyFrame \| None` | Lazy-scan approach summary |
| `to_parquet(output_dir)` | `ExportResult` | Export to Parquet files |
| `to_csv(output_dir)` | `ExportResult` | Export to CSV files |
| `to_excel(output_path)` | `ExportResult` | Export to Excel workbook |
| `to_corep(output_path)` | `ExportResult` | Export COREP regulatory templates |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `has_warnings` | `bool` | True if any warnings present |
| `has_errors` | `bool` | True if any errors (not warnings) present |
| `warning_count` | `int` | Number of warnings |
| `error_count` | `int` | Number of errors |

### SummaryStatistics

Aggregated summary metrics from the calculation.

| Field | Type | Description |
|-------|------|-------------|
| `total_ead` | `Decimal` | Total Exposure at Default |
| `total_rwa` | `Decimal` | Total Risk-Weighted Assets |
| `exposure_count` | `int` | Number of exposures processed |
| `average_risk_weight` | `Decimal` | Average risk weight (RWA / EAD) |
| `total_ead_sa` | `Decimal` | EAD from Standardised Approach |
| `total_ead_irb` | `Decimal` | EAD from IRB approaches |
| `total_ead_slotting` | `Decimal` | EAD from Slotting approach |
| `total_rwa_sa` | `Decimal` | RWA from Standardised Approach |
| `total_rwa_irb` | `Decimal` | RWA from IRB approaches |
| `total_rwa_slotting` | `Decimal` | RWA from Slotting approach |
| `floor_applied` | `bool` | Whether output floor was binding |
| `floor_impact` | `Decimal` | Additional RWA from output floor |
| `total_el_shortfall` | `Decimal` | EL shortfall for IRB exposures |
| `total_el_excess` | `Decimal` | EL excess for IRB exposures |
| `t2_credit` | `Decimal` | EL excess addable to T2 capital |

### ValidationResponse

Response from `CreditRiskCalc.validate()`.

| Field | Type | Description |
|-------|------|-------------|
| `valid` | `bool` | Whether data path is ready for calculation |
| `data_path` | `str` | The validated path |
| `files_found` | `list[str]` | Required files that were found |
| `files_missing` | `list[str]` | Required files that are missing |
| `errors` | `list[APIError]` | Validation errors |

| Property | Type | Description |
|----------|------|-------------|
| `missing_count` | `int` | Number of missing files |
| `found_count` | `int` | Number of found files |

### APIError

User-friendly error representation.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Error code (e.g., `"DQ006"`, `"CRM001"`) |
| `message` | `str` | Human-readable error message |
| `severity` | `"warning" \| "error" \| "critical"` | Error severity |
| `category` | `str` | Category for grouping |
| `details` | `dict` | Additional context |

### PerformanceMetrics

Timing and throughput metrics.

| Field | Type | Description |
|-------|------|-------------|
| `started_at` | `datetime` | Calculation start time |
| `completed_at` | `datetime` | Calculation end time |
| `duration_seconds` | `float` | Total time in seconds |
| `exposure_count` | `int` | Number of exposures |

| Property | Type | Description |
|----------|------|-------------|
| `exposures_per_second` | `float` | Processing throughput |

---

## Export

### ResultExporter

Exports calculation results to various formats.

```python
from rwa_calc.api import ResultExporter

exporter = ResultExporter()
result = exporter.export_to_parquet(response, Path("output/"))
result = exporter.export_to_csv(response, Path("output/"))
result = exporter.export_to_excel(response, Path("output/results.xlsx"))
result = exporter.export_to_corep(response, Path("output/corep.xlsx"))
```

### ExportResult

Result of an export operation.

| Field | Type | Description |
|-------|------|-------------|
| `format` | `str` | Export format (`"parquet"`, `"csv"`, `"excel"`) |
| `files` | `list[Path]` | Files written |
| `row_count` | `int` | Total rows exported |

---

## Usage Examples

### Basic Calculation

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

response = CreditRiskCalc(
    data_path="/data/exposures",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
).calculate()

if response.success:
    print(f"Total RWA: {response.summary.total_rwa:,.0f}")
```

### Validation Before Calculation

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

calc = CreditRiskCalc(
    data_path="/data/exposures",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
)

validation = calc.validate()
if not validation.valid:
    print(f"Missing: {validation.files_missing}")
else:
    response = calc.calculate()
```

### Export to Multiple Formats

```python
from datetime import date
from pathlib import Path
from rwa_calc.api import CreditRiskCalc

response = CreditRiskCalc(
    data_path="/data/exposures",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    permission_mode="irb",
).calculate()

if response.success:
    response.to_parquet(Path("output/parquet/"))
    response.to_csv(Path("output/csv/"))
    response.to_excel(Path("output/results.xlsx"))
    response.to_corep(Path("output/corep.xlsx"))
```

### Framework Comparison

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

crr = CreditRiskCalc(
    data_path="/data/exposures",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    permission_mode="irb",
).calculate()

b31 = CreditRiskCalc(
    data_path="/data/exposures",
    framework="BASEL_3_1",
    reporting_date=date(2027, 1, 1),
    permission_mode="irb",
).calculate()

if crr.success and b31.success:
    delta = b31.summary.total_rwa - crr.summary.total_rwa
    print(f"CRR RWA:       {crr.summary.total_rwa:,.0f}")
    print(f"Basel 3.1 RWA: {b31.summary.total_rwa:,.0f}")
    print(f"Impact:        {delta:+,.0f}")
```
