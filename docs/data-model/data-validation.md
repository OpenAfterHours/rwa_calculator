# Data Validation Guide

This guide explains how data validation works in the RWA calculator, common validation errors, and how to troubleshoot data issues.

## Overview

The RWA calculator validates input data at multiple stages:

1. **Load-time validation** - Schema checks when data is loaded
2. **Pipeline boundary validation** - Checks at each processing stage
3. **Business rule validation** - Domain-specific constraints (PD/LGD ranges, etc.)

Validation is performed **without materialising data** where possible, using Polars LazyFrame schema inspection for efficiency.

---

## Validation Functions

The validation utilities are in `src/rwa_calc/contracts/validation.py`.

### Schema Validation

Validates that a LazyFrame has the expected columns and types:

```python
from rwa_calc.contracts.validation import validate_schema
from rwa_calc.data.schemas import FACILITY_SCHEMA
import polars as pl

# Load your data
facilities = pl.scan_parquet("data/exposures/facilities.parquet")

# Validate against expected schema
errors = validate_schema(
    lf=facilities,
    expected_schema=FACILITY_SCHEMA,
    context="facilities",
    strict=False  # Set True to flag unexpected columns
)

if errors:
    print("Validation errors found:")
    for error in errors:
        print(f"  - {error}")
else:
    print("Schema validation passed")
```

### Required Columns Check

Validates that specific columns are present (without type checking):

```python
from rwa_calc.contracts.validation import validate_required_columns

required = ["counterparty_reference", "entity_type", "country_code"]
missing = validate_required_columns(
    lf=counterparties,
    required_columns=required,
    context="counterparties"
)

if missing:
    print("Missing columns:", missing)
```

### Structured Error Objects

For integration with the pipeline, use error objects:

```python
from rwa_calc.contracts.validation import validate_schema_to_errors
from rwa_calc.data.schemas import LOAN_SCHEMA

errors = validate_schema_to_errors(
    lf=loans,
    expected_schema=LOAN_SCHEMA,
    context="loans"
)

for error in errors:
    print(f"Code: {error.code}")
    print(f"Message: {error.message}")
    print(f"Field: {error.field_name}")
    print(f"Expected: {error.expected_value}")
    print(f"Actual: {error.actual_value}")
```

---

## Error Types

### Schema Errors

| Error Code | Description | Example |
|------------|-------------|---------|
| `MISSING_FIELD` | Required column not present | `Missing column 'counterparty_reference'` |
| `TYPE_MISMATCH` | Column has wrong data type | `Type mismatch for 'limit': expected Float64, got String` |

### Business Rule Errors

| Error Code | Description | Example |
|------------|-------------|---------|
| `INVALID_VALUE` | Value outside valid range | `PD value 1.5 exceeds maximum 1.0` |
| `INVALID_REFERENCE` | Foreign key not found | `counterparty_reference 'CORP_999' not found` |
| `DUPLICATE_KEY` | Duplicate primary key | `Duplicate facility_reference: 'FAC_001'` |

---

## Common Validation Issues

### 1. Missing Column

**Error:**
```
[facilities] Missing column: 'risk_type' (expected type: String)
```

**Cause:** The input file is missing a required column.

**Fix:** Add the missing column to your data:

```python
import polars as pl

# Add missing column with default value
facilities = facilities.with_columns(
    pl.lit("MR").alias("risk_type")  # MR = medium risk (50% SA, 75% F-IRB)
)
```

---

### 2. Type Mismatch

**Error:**
```
[loans] Type mismatch for 'drawn_amount': expected Float64, got String
```

**Cause:** The column contains string values instead of numbers (common with CSV imports).

**Fix:** Cast the column to the correct type:

```python
import polars as pl

loans = loans.with_columns(
    pl.col("drawn_amount").cast(pl.Float64)
)
```

---

### 3. Column Name Case Mismatch

**Error:**
```
[counterparties] Missing column: 'counterparty_reference' (expected type: String)
```

**Cause:** Column names are case-sensitive. `Counterparty_Reference` is not the same as `counterparty_reference`.

**Fix:** Rename columns to match expected names:

```python
import polars as pl

counterparties = counterparties.rename({
    "Counterparty_Reference": "counterparty_reference",
    "Country_Code": "country_code",
})
```

---

### 4. Date Format Issues

**Error:**
```
[facilities] Type mismatch for 'maturity_date': expected Date, got String
```

**Cause:** Dates are stored as strings instead of proper date types.

**Fix:** Parse dates from strings:

```python
import polars as pl

facilities = facilities.with_columns(
    pl.col("maturity_date").str.strptime(pl.Date, "%Y-%m-%d")
)

# For different formats:
# "%d/%m/%Y" for 31/12/2024
# "%m/%d/%Y" for 12/31/2024
```

---

### 5. Invalid PD/LGD Values

**Error:**
```
PD value -0.01 is below minimum 0.0
LGD value 1.5 exceeds maximum 1.25
```

**Cause:** Risk parameters are outside valid ranges.

**Fix:** Clip or filter invalid values:

```python
import polars as pl

# Clip PD to valid range [0, 1]
data = data.with_columns(
    pl.col("pd").clip(0.0, 1.0)
)

# Or filter out invalid rows
valid_data = data.filter(
    (pl.col("pd") >= 0.0) & (pl.col("pd") <= 1.0)
)
```

---

### 6. Missing Reference (Foreign Key)

**Error:**
```
counterparty_reference 'CORP_999' in loans not found in counterparties
```

**Cause:** A loan references a counterparty that doesn't exist.

**Fix:** Either add the missing counterparty or filter orphan records:

```python
import polars as pl

# Get valid counterparty references
valid_refs = counterparties.select("counterparty_reference").collect()

# Filter loans to only valid references
loans = loans.filter(
    pl.col("counterparty_reference").is_in(valid_refs["counterparty_reference"])
)
```

---

### 7. Negative Amounts

**Error:**
```
Invalid value: drawn_amount cannot be negative
```

**Cause:** Amount columns contain negative values.

**Fix:** Take absolute value or filter:

```python
import polars as pl

# Take absolute value
loans = loans.with_columns(
    pl.col("drawn_amount").abs()
)

# Or filter
loans = loans.filter(pl.col("drawn_amount") >= 0)
```

---

## Business Rule Validators

The calculator includes validators for domain-specific rules:

### Non-Negative Amounts

```python
from rwa_calc.contracts.validation import validate_non_negative_amounts

# Returns LazyFrame with validation flag columns
validated = validate_non_negative_amounts(
    lf=loans,
    amount_columns=["drawn_amount", "limit"],
    context="loans"
)

# Check validation results
result = validated.select([
    "_valid_drawn_amount",
    "_valid_limit"
]).collect()
```

### PD Range Validation

```python
from rwa_calc.contracts.validation import validate_pd_range

validated = validate_pd_range(
    lf=ratings,
    pd_column="pd",
    min_pd=0.0,
    max_pd=1.0
)

# Filter to only valid PDs
valid_ratings = validated.filter(pl.col("_valid_pd"))
```

### LGD Range Validation

```python
from rwa_calc.contracts.validation import validate_lgd_range

validated = validate_lgd_range(
    lf=exposures,
    lgd_column="lgd",
    min_lgd=0.0,
    max_lgd=1.25  # Can exceed 1.0 in some cases
)
```

---

## Pre-Flight Validation

Before running the full pipeline, validate your entire data bundle:

```python
from rwa_calc.contracts.validation import validate_raw_data_bundle
from rwa_calc.data.schemas import (
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    COUNTERPARTY_SCHEMA,
    COLLATERAL_SCHEMA,
)

# Define schemas to validate
schemas = {
    "facilities": FACILITY_SCHEMA,
    "loans": LOAN_SCHEMA,
    "counterparties": COUNTERPARTY_SCHEMA,
    "collateral": COLLATERAL_SCHEMA,
}

# Validate entire bundle
errors = validate_raw_data_bundle(bundle, schemas)

if errors:
    print(f"Found {len(errors)} validation errors:")
    for error in errors:
        print(f"  [{error.category}] {error.message}")
else:
    print("All data validated successfully")
```

---

## Type Compatibility

The validator allows some type flexibility:

| Expected Type | Allowed Actual Types |
|---------------|---------------------|
| `Int64` | `Int8`, `Int16`, `Int32`, `Int64` |
| `Float64` | `Float32`, `Float64` |
| `String` | `Utf8`, `String` |

This means if your file has `Int32` but the schema expects `Int64`, validation will pass.

---

## Validation in the Pipeline

The pipeline validates data at stage boundaries:

```
Load → [Validate Raw] → Hierarchy → [Validate Resolved] → Classify → ...
```

If validation fails, the pipeline:

1. **Accumulates errors** - Does not fail immediately
2. **Continues where possible** - Processes valid records
3. **Reports all issues** - Returns complete error list

Access validation results:

```python
result = pipeline.run(config)

if result.has_errors:
    for error in result.errors:
        if error.category == "SCHEMA_VALIDATION":
            print(f"Schema error: {error.message}")
        elif error.category == "BUSINESS_RULE":
            print(f"Business rule violation: {error.message}")
```

---

## Debugging Tips

### 1. Inspect Schema Before Validation

```python
import polars as pl

lf = pl.scan_parquet("data/facilities.parquet")

# View actual schema
print("Actual schema:")
for name, dtype in lf.collect_schema().items():
    print(f"  {name}: {dtype}")
```

### 2. Compare Expected vs Actual

```python
from rwa_calc.data.schemas import FACILITY_SCHEMA

print("\nExpected schema:")
for name, dtype in FACILITY_SCHEMA.items():
    print(f"  {name}: {dtype}")

print("\nActual schema:")
for name, dtype in lf.collect_schema().items():
    print(f"  {name}: {dtype}")

# Find differences
expected_cols = set(FACILITY_SCHEMA.keys())
actual_cols = set(lf.collect_schema().names())

print(f"\nMissing columns: {expected_cols - actual_cols}")
print(f"Extra columns: {actual_cols - expected_cols}")
```

### 3. Sample Invalid Rows

```python
import polars as pl

# Find rows with negative amounts
invalid = loans.filter(pl.col("drawn_amount") < 0).collect()
print(f"Found {len(invalid)} rows with negative drawn_amount")
print(invalid.head())

# Find rows with null required fields
null_refs = loans.filter(pl.col("counterparty_reference").is_null()).collect()
print(f"Found {len(null_refs)} rows with null counterparty_reference")
```

### 4. Check Value Distributions

```python
import polars as pl

# Check PD distribution
pd_stats = ratings.select([
    pl.col("pd").min().alias("min_pd"),
    pl.col("pd").max().alias("max_pd"),
    pl.col("pd").mean().alias("mean_pd"),
    pl.col("pd").null_count().alias("null_count"),
]).collect()

print(pd_stats)
```

---

## Strict Mode

For production use, enable strict validation to catch unexpected columns:

```python
errors = validate_schema(
    lf=facilities,
    expected_schema=FACILITY_SCHEMA,
    context="facilities",
    strict=True  # Flag unexpected columns
)
```

Unexpected columns might indicate:
- Data from a different version
- Leftover columns from transformations
- Incorrectly named columns

---

## Next Steps

- [Input Schemas](input-schemas.md) - Complete schema definitions
- [Data Flow](../architecture/data-flow.md) - How data moves through pipeline
- [Error Handling](../api/contracts.md#error-handling) - Error types and handling
