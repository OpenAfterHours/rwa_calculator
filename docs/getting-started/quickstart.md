# Quick Start

This guide will help you run your first RWA calculation in just a few minutes.

## Choose Your Approach

There are two ways to run RWA calculations:

| Approach | Best For | Guide |
|----------|----------|-------|
| **Interactive UI** | Quick analysis, exploring results, non-developers | [See below](#using-the-interactive-ui) |
| **Python API** | Automation, integration, custom workflows | [See below](#using-the-python-api) |

---

## Using the Interactive UI

The fastest way to get started is the web-based interface.

### Step 1: Install with UI Support

```bash
pip install rwa-calc[ui]
# Or with uv
uv add rwa-calc --extra ui
```

### Step 2: Start the Server

```bash
# If installed from PyPI
rwa-calc-ui

# Or from source
uv run python src/rwa_calc/ui/marimo/server.py
```

### Step 3: Open Your Browser

Navigate to [http://localhost:8000](http://localhost:8000) to access:

- **RWA Calculator** (`/`) - Run calculations on your data
- **Results Explorer** (`/results`) - Filter and analyze results
- **Framework Reference** (`/reference`) - View regulatory parameters

For detailed UI documentation, see the [Interactive UI Guide](../user-guide/interactive-ui.md).

---

## Using the Python API

### Quickest Start

Run a complete RWA calculation in one call:

```python
from rwa_calc.api import quick_calculate

response = quick_calculate("/path/to/data")
print(f"Total RWA: {response.summary.total_rwa:,.0f}")
```

That's it. `quick_calculate` loads your data, runs the full pipeline, and returns a
`CalculationResponse` with summary statistics and detailed results.

### More Control with RWAService

For more control over framework, permission mode, and reporting date, use `RWAService`:

```python
from datetime import date
from pathlib import Path
from rwa_calc.api import RWAService, CalculationRequest, create_service

service = create_service()
response = service.calculate(
    CalculationRequest(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2026, 12, 31),
        permission_mode="irb",
    )
)

if response.success:
    print(f"Total RWA: {response.summary.total_rwa:,.0f}")
    print(f"SA RWA:    {response.summary.total_rwa_sa:,.0f}")
    print(f"IRB RWA:   {response.summary.total_rwa_irb:,.0f}")
```

### Complete Example

Here's a full script with validation, error handling, and export:

```python
from datetime import date
from pathlib import Path

from rwa_calc.api import (
    RWAService,
    CalculationRequest,
    create_service,
)


def calculate_rwa():
    """Calculate RWA for credit exposures using the Service API."""

    # Create the service (cache_dir defaults to a temp directory)
    service = create_service()

    # Build request
    request = CalculationRequest(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2026, 12, 31),
        permission_mode="irb",
    )

    # Run calculation
    response = service.calculate(request)

    # Check for errors
    if not response.success:
        for error in response.errors:
            print(f"[{error.code}] {error.severity}: {error.message}")
        return

    # Print summary
    summary = response.summary
    print("=" * 50)
    print("RWA Calculation Results")
    print("=" * 50)
    print(f"Framework:      {response.framework}")
    print(f"Reporting Date: {response.reporting_date}")
    print(f"Exposures:      {summary.exposure_count}")
    print("-" * 50)
    print(f"Total RWA:      GBP {summary.total_rwa:,.0f}")
    print(f"  SA RWA:       GBP {summary.total_rwa_sa:,.0f}")
    print(f"  IRB RWA:      GBP {summary.total_rwa_irb:,.0f}")
    print(f"  Slotting RWA: GBP {summary.total_rwa_slotting:,.0f}")
    print(f"Avg Risk Weight: {summary.average_risk_weight:.1%}")
    print("=" * 50)

    # Print warnings if any
    if response.has_warnings:
        print(f"\n{response.warning_count} warnings:")
        for error in response.errors:
            if error.severity == "warning":
                print(f"  [{error.code}] {error.message}")

    # Export results
    export = response.to_parquet(Path("output/"))
    print(f"\nExported {export.row_count} rows to {export.files}")

    # Work with detailed results as a Polars DataFrame
    df = response.collect_results()
    print(f"\nDetailed results: {df.shape}")


if __name__ == "__main__":
    calculate_rwa()
```

## Working with Custom Data

### Specifying Data Format

By default, the service reads Parquet files. To use CSV:

```python
from rwa_calc.api import quick_calculate

response = quick_calculate("/path/to/csv-data", data_format="csv")
```

Or with `CalculationRequest`:

```python
request = CalculationRequest(
    data_path="/path/to/csv-data",
    data_format="csv",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
)
```

### Required Data Files

The calculator expects the following files in your data directory:

| File | Description | Required |
|------|-------------|----------|
| `counterparties.parquet` | Counterparty information | Yes |
| `facilities.parquet` | Credit facilities | Yes |
| `loans.parquet` | Individual loans/draws | Yes |
| `contingents.parquet` | Off-balance sheet items | No |
| `collateral.parquet` | Collateral holdings | No |
| `guarantees.parquet` | Guarantee information | No |
| `provisions.parquet` | Provision allocations | No |
| `ratings.parquet` | Credit ratings | No |
| `org_mapping.parquet` | Organization hierarchy | No |
| `lending_mapping.parquet` | Retail lending groups | No |

### Validating Data Before Calculation

```python
from rwa_calc.api import create_service, ValidationRequest

service = create_service()
validation = service.validate_data_path(
    ValidationRequest(data_path="/path/to/data")
)

if validation.valid:
    print(f"Ready: {validation.found_count} files found")
else:
    print(f"Missing files: {validation.files_missing}")
```

## Configuration Options

### CRR Framework

```python
from rwa_calc.api import quick_calculate

# CRR with default settings
response = quick_calculate("/path/to/data", framework="CRR")

# CRR with IRB routing (requires model_permissions input data)
response = quick_calculate(
    "/path/to/data",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    permission_mode="irb",
)
```

### Basel 3.1 Framework

```python
from rwa_calc.api import quick_calculate

response = quick_calculate(
    "/path/to/data",
    framework="BASEL_3_1",
    reporting_date=date(2027, 1, 1),
)
```

### Permission Mode

| Value | Description |
|-------|-------------|
| `"standardised"` | All exposures use the Standardised Approach (default) |
| `"irb"` | Approach routing is driven by `model_permissions` input data. Each model's approved approach (AIRB, FIRB, slotting) is resolved per-exposure. Exposures without a matching model permission fall back to SA. |

!!! note "Model permissions required for IRB mode"
    When `permission_mode="irb"`, provide a `model_permissions` input table to control
    which exposures use FIRB, AIRB, or slotting. Without it, all exposures fall back to SA
    with a warning. See [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema).

## Understanding Results

The `CalculationResponse` provides several ways to access results:

### Summary Statistics

```python
response = quick_calculate("/path/to/data")

summary = response.summary
summary.total_rwa           # Total risk-weighted assets
summary.total_ead           # Total exposure at default
summary.exposure_count      # Number of exposures processed
summary.average_risk_weight # Average risk weight (RWA / EAD)

# By approach
summary.total_rwa_sa        # Standardised Approach RWA
summary.total_rwa_irb       # IRB RWA
summary.total_rwa_slotting  # Slotting RWA

# Output floor (Basel 3.1)
summary.floor_applied       # Whether output floor was binding
summary.floor_impact        # Additional RWA from output floor
```

### Detailed Breakdown

```python
import polars as pl

# Get as Polars DataFrame
df = response.collect_results()

# Or use lazy scanning for large result sets
lf = response.scan_results()
corporate = lf.filter(pl.col("exposure_class") == "CORPORATE").collect()

# Aggregate by any dimension
by_approach = df.group_by("approach").agg(
    pl.col("rwa").sum().alias("total_rwa"),
    pl.col("ead").sum().alias("total_ead"),
)
```

### Export Results

```python
from pathlib import Path

# To Parquet
response.to_parquet(Path("output/"))

# To CSV
response.to_csv(Path("output/"))

# To Excel (requires xlsxwriter)
response.to_excel(Path("output/results.xlsx"))

# To COREP regulatory templates (requires xlsxwriter)
response.to_corep(Path("output/corep.xlsx"))
```

## Error Handling

The calculator accumulates errors rather than failing fast:

```python
response = quick_calculate("/path/to/data")

# Check overall success
if not response.success:
    print("Calculation failed")

# Check for errors
if response.has_errors:
    for error in response.errors:
        if error.severity in ("error", "critical"):
            print(f"[{error.code}] {error.message}")

# Check for warnings
if response.has_warnings:
    for error in response.errors:
        if error.severity == "warning":
            print(f"Warning [{error.code}]: {error.message}")
```

## Advanced: Pipeline API

For users who need to customise individual pipeline components, the low-level pipeline API
provides direct access to the orchestrator:

```python
from datetime import date
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

# Create configuration
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Create and run the pipeline
pipeline = create_pipeline()
result = pipeline.run(config)

# Access the aggregated result bundle directly
print(f"Total RWA: {result.total_rwa:,.2f}")
```

This gives you access to the full `PipelineOrchestrator` and `AggregatedResultBundle`,
which is useful for custom loaders, alternative data sources, or when integrating into
an existing data pipeline. See the [Pipeline API Reference](../api/pipeline.md) for details.

## Next Steps

- [Concepts](concepts.md) - Understand key terminology
- [Service API Reference](../api/service.md) - Full service API documentation
- [Configuration Guide](../user-guide/configuration.md) - Advanced configuration options
- [Calculation Methodology](../user-guide/methodology/index.md) - How calculations work
