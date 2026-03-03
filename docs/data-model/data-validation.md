# Data Validation Guide

This guide explains how data validation works in the RWA calculator, the complete set of
validation functions, and how to troubleshoot data issues.

> **Source of truth**: All validation utilities are in `src/rwa_calc/contracts/validation.py`.
> Valid value constraints are defined in `COLUMN_VALUE_CONSTRAINTS` in `src/rwa_calc/data/schemas.py`.

## Overview

The RWA calculator validates input data at multiple stages:

1. **Load-time validation** — Schema checks when data is loaded
2. **Pipeline boundary validation** — Checks at each processing stage
3. **Business rule validation** — Domain-specific constraints (PD/LGD ranges, risk type codes)
4. **Column value validation** — Categorical values against allowed sets

Validation is performed **without materialising data** where possible, using Polars LazyFrame
schema inspection for efficiency. Only column value validation requires `.collect()`.

---

## Schema Validation Functions

### `validate_schema()`

Validates a LazyFrame's schema against an expected schema dictionary without materialising data.

```python
from rwa_calc.contracts.validation import validate_schema
from rwa_calc.data.schemas import FACILITY_SCHEMA
import polars as pl

facilities = pl.scan_parquet("data/exposures/facilities.parquet")

errors = validate_schema(
    lf=facilities,
    expected_schema=FACILITY_SCHEMA,
    context="facilities",
    strict=False  # Set True to flag unexpected extra columns
)

if errors:
    for error in errors:
        print(f"  - {error}")
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `lf` | `pl.LazyFrame` | LazyFrame to validate |
| `expected_schema` | `dict[str, pl.DataType]` | Expected column names and types |
| `context` | `str` | Label for error messages (e.g., `"facilities"`) |
| `strict` | `bool` | If `True`, flags unexpected extra columns |

**Returns:** `list[str]` — plain string error messages (empty if valid).

### `validate_required_columns()`

Checks that specific columns are present (without type checking).

```python
from rwa_calc.contracts.validation import validate_required_columns

missing = validate_required_columns(
    lf=counterparties,
    required_columns=["counterparty_reference", "entity_type", "country_code"],
    context="counterparties"
)
```

**Returns:** `list[str]` — missing-column error messages.

### `validate_schema_to_errors()`

Same logic as `validate_schema()` but returns structured `CalculationError` objects for
integration with the pipeline error accumulation pattern.

```python
from rwa_calc.contracts.validation import validate_schema_to_errors
from rwa_calc.data.schemas import LOAN_SCHEMA

errors = validate_schema_to_errors(
    lf=loans,
    expected_schema=LOAN_SCHEMA,
    context="loans"
)

for error in errors:
    print(f"Code: {error.code}, Field: {error.field_name}")
    print(f"Expected: {error.expected_value}, Actual: {error.actual_value}")
```

**Returns:** `list[CalculationError]` — with category `SCHEMA_VALIDATION`, severity `ERROR`.

---

## Bundle Validation Functions

These functions validate entire pipeline bundles at stage boundaries, checking that
expected columns exist after each transformation.

### `validate_raw_data_bundle()`

Validates all LazyFrames in a `RawDataBundle` against expected schemas.

```python
from rwa_calc.contracts.validation import validate_raw_data_bundle

errors = validate_raw_data_bundle(bundle, schemas)
```

Validates up to 11 named frames: `facilities`, `loans`, `contingents`, `counterparties`,
`collateral`, `guarantees`, `provisions`, `ratings`, `facility_mappings`, `org_mappings`,
`lending_mappings`.

**Returns:** `list[CalculationError]`

### `validate_resolved_hierarchy_bundle()`

Validates that hierarchy columns exist in a `ResolvedHierarchyBundle.exposures` LazyFrame.

```python
from rwa_calc.contracts.validation import validate_resolved_hierarchy_bundle

hierarchy_columns = [
    "counterparty_has_parent", "parent_counterparty_reference",
    "ultimate_parent_reference", "counterparty_hierarchy_depth",
    "rating_inherited", "rating_source_counterparty",
]

errors = validate_resolved_hierarchy_bundle(bundle, hierarchy_columns)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `bundle` | `ResolvedHierarchyBundle` | Bundle to validate |
| `expected_columns` | `list[str]` | Hierarchy columns to check for |

**Returns:** `list[CalculationError]`

### `validate_classified_bundle()`

Validates classification columns across `all_exposures`, `sa_exposures`, and
`irb_exposures` in a `ClassifiedExposuresBundle`.

```python
from rwa_calc.contracts.validation import validate_classified_bundle

classification_columns = [
    "exposure_class", "approach_applied", "cqs", "pd", "is_sme",
]

errors = validate_classified_bundle(bundle, classification_columns)
```

**Returns:** `list[CalculationError]`

### `validate_crm_adjusted_bundle()`

Validates CRM-related columns across `exposures`, `sa_exposures`, and `irb_exposures`
in a `CRMAdjustedBundle`.

```python
from rwa_calc.contracts.validation import validate_crm_adjusted_bundle

crm_columns = [
    "ccf_applied", "gross_ead", "final_ead",
    "collateral_adjusted_value", "ead_after_collateral",
]

errors = validate_crm_adjusted_bundle(bundle, crm_columns)
```

**Returns:** `list[CalculationError]`

---

## Business Rule Validators

These functions add boolean validation flag columns to LazyFrames without materialising data.
The flag columns follow the naming convention `_valid_{column_name}`.

### `validate_non_negative_amounts()`

Adds validation flag columns for non-negative amount checks.

```python
from rwa_calc.contracts.validation import validate_non_negative_amounts

validated = validate_non_negative_amounts(
    lf=loans,
    amount_columns=["drawn_amount", "limit"],
    context="loans"
)
# Adds _valid_drawn_amount and _valid_limit boolean columns
```

**Returns:** `pl.LazyFrame` — with added `_valid_{col}` flag columns.

### `validate_pd_range()`

Validates that PD values are in [0, 1].

```python
from rwa_calc.contracts.validation import validate_pd_range

validated = validate_pd_range(lf=ratings, pd_column="pd", min_pd=0.0, max_pd=1.0)
valid_ratings = validated.filter(pl.col("_valid_pd"))
```

**Returns:** `pl.LazyFrame` — with `_valid_pd` column.

### `validate_lgd_range()`

Validates that LGD values are in [0, 1.25]. The upper bound exceeds 1.0 because LGD
can legitimately exceed 100% in certain Basel scenarios.

```python
from rwa_calc.contracts.validation import validate_lgd_range

validated = validate_lgd_range(lf=exposures, lgd_column="lgd", min_lgd=0.0, max_lgd=1.25)
```

**Returns:** `pl.LazyFrame` — with `_valid_lgd` column.

### `validate_risk_type()`

Validates that risk type values are one of the recognised codes (`FR`, `MR`, `MLR`, `LR`)
or full values (`full_risk`, `medium_risk`, `medium_low_risk`, `low_risk`).
Comparison is case-insensitive.

```python
from rwa_calc.contracts.validation import validate_risk_type

validated = validate_risk_type(lf=facilities, column="risk_type")
# Adds _valid_risk_type boolean column
```

**Returns:** `pl.LazyFrame` — with `_valid_risk_type` column.

### `validate_ccf_modelled()`

Validates that modelled CCF values are in [0.0, 1.5]. Null values are treated as valid
since the field is optional. The 150% cap accommodates Retail IRB CCFs that can exceed
100% due to additional drawdown behaviour during stress.

```python
from rwa_calc.contracts.validation import validate_ccf_modelled

validated = validate_ccf_modelled(lf=facilities, column="ccf_modelled")
# Adds _valid_ccf_modelled boolean column
```

**Returns:** `pl.LazyFrame` — with `_valid_ccf_modelled` column.

### `normalize_risk_type()`

Normalises risk type short codes to canonical full values. First lowercases the column,
then maps: `FR` → `full_risk`, `MR` → `medium_risk`, `MLR` → `medium_low_risk`,
`LR` → `low_risk`. Values already in full form pass through unchanged.

```python
from rwa_calc.contracts.validation import normalize_risk_type

normalized = normalize_risk_type(lf=facilities, column="risk_type")
```

**Constants used:**

| Short Code | Full Value |
|-----------|------------|
| `fr` | `full_risk` |
| `mr` | `medium_risk` |
| `mlr` | `medium_low_risk` |
| `lr` | `low_risk` |

**Returns:** `pl.LazyFrame` — with normalised `risk_type` column.

---

## Column Value Validation

These functions check actual data values against allowed sets. They are the only
validation functions that materialise data (call `.collect()`).

### `validate_column_values()`

Validates that all non-null values in a column belong to a set of allowed values.
Performs case-insensitive comparison. Groups invalid values by distinct value with counts.

```python
from rwa_calc.contracts.validation import validate_column_values
from rwa_calc.data.schemas import VALID_ENTITY_TYPES

errors = validate_column_values(
    lf=counterparties,
    column="entity_type",
    valid_values=VALID_ENTITY_TYPES,
    context="counterparties"
)

for error in errors:
    print(f"Invalid value '{error.actual_value}' found {error.message}")
```

**Returns:** `list[CalculationError]` — with code `ERROR_INVALID_COLUMN_VALUE`,
severity `WARNING`, category `DATA_QUALITY`.

### `validate_bundle_values()`

Validates all categorical column values across an entire `RawDataBundle` in one call.
Uses the `COLUMN_VALUE_CONSTRAINTS` registry from `data/schemas.py` by default.

```python
from rwa_calc.contracts.validation import validate_bundle_values

# Using default constraints from COLUMN_VALUE_CONSTRAINTS
errors = validate_bundle_values(bundle)

# Or with custom constraints
custom_constraints = {
    "counterparties": {"entity_type": {"corporate", "institution"}},
}
errors = validate_bundle_values(bundle, constraints=custom_constraints)
```

The function validates these tables (when present in the bundle):

| Table | Validated Columns |
|-------|-------------------|
| `facilities` | `seniority` |
| `loans` | `seniority` |
| `contingents` | `seniority`, `bs_type` |
| `counterparties` | `entity_type` |
| `collateral` | `collateral_type`, `property_type`, `issuer_type`, `valuation_type`, `beneficiary_type` |
| `provisions` | `provision_type`, `beneficiary_type` |
| `ratings` | `rating_type` |
| `specialised_lending` | `sl_type`, `slotting_category` |
| `equity_exposures` | `equity_type` |
| `guarantees` | `beneficiary_type` |
| `facility_mappings` | `child_type` |

**Performance:** Internally uses `_validate_table_columns_batched()` which checks
multiple columns per table in a single `.collect()` call.

**Returns:** `list[CalculationError]`

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
Load → [validate_raw_data_bundle] → Hierarchy → [validate_resolved_hierarchy_bundle]
     → Classify → [validate_classified_bundle] → CRM → [validate_crm_adjusted_bundle] → ...
```

If validation fails, the pipeline:

1. **Accumulates errors** — Does not fail immediately
2. **Continues where possible** — Processes valid records
3. **Reports all issues** — Returns complete error list in the result bundle

---

## Common Validation Issues

### 1. Missing Column

```
[facilities] Missing column: 'risk_type' (expected type: String)
```

**Fix:** Add the missing column with a default value:

```python
facilities = facilities.with_columns(
    pl.lit("MR").alias("risk_type")
)
```

### 2. Type Mismatch

```
[loans] Type mismatch for 'drawn_amount': expected Float64, got String
```

**Fix:** Cast the column to the correct type:

```python
loans = loans.with_columns(
    pl.col("drawn_amount").cast(pl.Float64)
)
```

### 3. Invalid Categorical Values

```
[counterparties] Invalid value 'CORP' for entity_type (expected one of: corporate, ...)
```

**Fix:** Map invalid values to valid ones:

```python
counterparties = counterparties.with_columns(
    pl.col("entity_type").str.to_lowercase().replace({"corp": "corporate"})
)
```

### 4. Date Format Issues

```
[facilities] Type mismatch for 'maturity_date': expected Date, got String
```

**Fix:** Parse dates from strings:

```python
facilities = facilities.with_columns(
    pl.col("maturity_date").str.strptime(pl.Date, "%Y-%m-%d")
)
```

### 5. Invalid PD/LGD Values

```
PD value -0.01 is below minimum 0.0
LGD value 1.5 exceeds maximum 1.25
```

**Fix:** Clip values to valid ranges:

```python
data = data.with_columns(
    pl.col("pd").clip(0.0, 1.0),
    pl.col("lgd").clip(0.0, 1.25),
)
```

---

## Debugging Tips

### Inspect Schema Before Validation

```python
import polars as pl

lf = pl.scan_parquet("data/facilities.parquet")

print("Actual schema:")
for name, dtype in lf.collect_schema().items():
    print(f"  {name}: {dtype}")
```

### Compare Expected vs Actual

```python
from rwa_calc.data.schemas import FACILITY_SCHEMA

expected_cols = set(FACILITY_SCHEMA.keys())
actual_cols = set(lf.collect_schema().names())

print(f"Missing columns: {expected_cols - actual_cols}")
print(f"Extra columns: {actual_cols - expected_cols}")
```

### Check Value Distributions

```python
pd_stats = ratings.select([
    pl.col("pd").min().alias("min"),
    pl.col("pd").max().alias("max"),
    pl.col("pd").mean().alias("mean"),
    pl.col("pd").null_count().alias("nulls"),
]).collect()
print(pd_stats)
```

---

## Next Steps

- [Input Schemas](input-schemas.md) — Complete schema definitions
- [Data Flow](../architecture/data-flow.md) — How data moves through pipeline
- [Error Handling](../api/contracts.md#error-handling) — Error types and handling
