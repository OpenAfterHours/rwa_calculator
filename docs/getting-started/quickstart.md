# Quick Start

This guide will help you run your first RWA calculation in just a few minutes.

## Basic Usage

### Step 1: Import the Required Modules

```python
from datetime import date
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig
```

### Step 2: Create a Configuration

Choose the regulatory framework for your calculation:

=== "CRR (Current)"

    ```python
    # For calculations under current CRR rules (until Dec 2026)
    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31)
    )
    ```

=== "Basel 3.1 (Future)"

    ```python
    # For calculations under Basel 3.1 (from Jan 2027)
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1)
    )
    ```

### Step 3: Create and Run the Pipeline

```python
# Create the pipeline
pipeline = create_pipeline()

# Run the calculation
result = pipeline.run(config)
```

### Step 4: Access Results

```python
# Total RWA
print(f"Total RWA: {result.total_rwa:,.2f}")

# RWA by approach
print(f"SA RWA: {result.sa_rwa:,.2f}")
print(f"IRB RWA: {result.irb_rwa:,.2f}")
print(f"Slotting RWA: {result.slotting_rwa:,.2f}")

# Get detailed breakdown
df = result.to_dataframe()
print(df.head())
```

## Complete Example

Here's a complete working example:

```python
from datetime import date
from pathlib import Path

from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

def calculate_rwa():
    """Calculate RWA for credit exposures."""

    # Configure for CRR framework
    config = CalculationConfig.crr(
        reporting_date=date(2026, 12, 31),
        apply_sme_supporting_factor=True,
        apply_infrastructure_factor=True
    )

    # Create the pipeline
    pipeline = create_pipeline()

    # Run the calculation
    result = pipeline.run(config)

    # Print summary
    print("=" * 50)
    print("RWA Calculation Results")
    print("=" * 50)
    print(f"Reporting Date: {config.reporting_date}")
    print(f"Framework: {config.framework.value}")
    print("-" * 50)
    print(f"Total RWA: GBP {result.total_rwa:,.2f}")
    print(f"  - SA RWA: GBP {result.sa_rwa:,.2f}")
    print(f"  - IRB RWA: GBP {result.irb_rwa:,.2f}")
    print(f"  - Slotting RWA: GBP {result.slotting_rwa:,.2f}")
    print("=" * 50)

    return result

if __name__ == "__main__":
    calculate_rwa()
```

## Working with Custom Data

### Loading from Parquet Files

```python
from pathlib import Path
from rwa_calc.engine.loader import ParquetLoader

# Specify your data directory
data_path = Path("./your_data")

# Create a loader
loader = ParquetLoader(data_path)

# Load data
raw_data = loader.load()

# Run pipeline with your data
result = pipeline.run_with_data(raw_data, config)
```

### Required Data Files

The calculator expects the following Parquet files:

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

## Configuration Options

### CRR Configuration

```python
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),

    # Supporting factors (CRR-specific)
    apply_sme_supporting_factor=True,    # Article 501 SME factor
    apply_infrastructure_factor=True,     # Infrastructure factor

    # FX conversion
    eur_gbp_rate=Decimal("0.88"),         # EUR to GBP rate
)
```

### Basel 3.1 Configuration

```python
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 1, 1),

    # Output floor (Basel 3.1-specific)
    output_floor_percentage=0.725,        # 72.5% floor
    transitional_floor_year=2027,         # Phase-in year
)
```

## Understanding Results

The result object provides several views of the calculated RWA:

### Summary Statistics

```python
# Total figures
result.total_rwa          # Total risk-weighted assets
result.total_ead          # Total exposure at default
result.total_expected_loss # Total expected loss (IRB only)

# By approach
result.sa_rwa             # Standardised Approach RWA
result.irb_rwa            # IRB RWA (before scaling/floor)
result.slotting_rwa       # Slotting RWA
```

### Detailed Breakdown

```python
# Get as Polars DataFrame
df = result.to_dataframe()

# Filter by exposure class
corporate = df.filter(pl.col("exposure_class") == "CORPORATE")

# Aggregate by any dimension
by_approach = df.group_by("approach").agg(
    pl.col("rwa").sum().alias("total_rwa"),
    pl.col("ead").sum().alias("total_ead")
)
```

### Export Results

```python
# To Parquet
result.to_parquet("results.parquet")

# To CSV
result.to_csv("results.csv")

# To JSON
result.to_json("results.json")
```

## Error Handling

The calculator accumulates errors rather than failing fast:

```python
result = pipeline.run(config)

# Check for errors
if result.has_errors:
    for error in result.errors:
        print(f"Error: {error.message}")
        print(f"  Exposure: {error.exposure_id}")
        print(f"  Stage: {error.stage}")

# Check for warnings
if result.has_warnings:
    for warning in result.warnings:
        print(f"Warning: {warning.message}")
```

## Next Steps

- [Concepts](concepts.md) - Understand key terminology
- [Configuration Guide](../user-guide/configuration.md) - Advanced configuration options
- [Calculation Methodology](../user-guide/methodology/index.md) - How calculations work
