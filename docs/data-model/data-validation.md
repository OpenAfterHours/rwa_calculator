# Data Validation Guide

This guide explains how data validation works in the RWA calculator, the complete set of
validation functions, and how to troubleshoot data issues.

> **Source of truth**: All validation utilities are in `src/rwa_calc/contracts/validation.py`.
> Valid value constraints are defined in `COLUMN_VALUE_CONSTRAINTS` in `src/rwa_calc/data/schemas.py`.

## Overview

The RWA calculator validates input data at three points:

1. **Load-time schema seal** — every raw table is conformed to its loader edge contract
   (`contracts/edges.py`, `RAW_TABLE_EDGES`). Missing required columns become typed nulls
   plus a `DQ001` error; declared columns are cast to their declared dtype. This is what
   makes the bundle's *shape* trustworthy, so nothing downstream re-checks it.
2. **Input-domain gate** — categorical and numeric column domains, run by
   `validate_bundle_values()` at both pipeline entries (the file loader, and
   `PipelineOrchestrator.run_with_data` for in-memory bundles).
3. **Output-bounds gate** — `validate_aggregated_bundle()` at the pipeline exit, checking
   the regulatory bounds on the aggregated results frame.

Validation never raises: every issue becomes a `CalculationError` on the result bundle.

!!! note "Schema-shape validators were removed"
    `validate_schema()`, `validate_schema_to_errors()`, `validate_required_columns()`,
    `validate_raw_data_bundle()` and `validate_resolved_hierarchy_bundle()` were deleted in
    Phase 0 of the test-space correctness plan. They ran *after* the edge seal, which
    already injects missing columns and casts dtypes, so neither of their limbs could fire —
    they were guard-shaped dead code with green unit tests. Use the loader's `DQ001` errors
    for missing required columns; a producer stage breaking its own output contract raises
    `EdgeContractViolation` instead.

---

## Business Rule Validators

These four functions add boolean validation flag columns to LazyFrames without
materialising data; the flag columns follow the naming convention `_valid_{column_name}`.
They are driven on the bundle path by `_validate_numeric_ranges()`, the private collector
inside `validate_bundle_values()` that turns those flags into row-named `CalculationError`s
(one `.collect()` per table, capped at five sampled rows per column plus an omitted-count
summary). Call them directly when you want the flags rather than the errors.

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

Validates that PD values are in [0, 1]. The lower bound is **closed**: CRR Art. 160(1)
floors the PD of "an exposure to a corporate or an institution" and has no
central-government / central-bank limb, so the CRR rulepack carries
`pd_floors["sovereign"] = 0` and a PD of exactly 0 is an admissible sovereign IRB input.

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

!!! note "Risk-type validation lives in the data layer"
    Input `risk_type` values are validated by the bundle-level value validation
    below (`COLUMN_VALUE_CONSTRAINTS` in `data/schemas.py` defines
    `VALID_RISK_TYPES_INPUT` and `RISK_TYPE_SYNONYMS`), and short codes are
    normalised inside the CCF lookup (`engine/ccf.py::_normalize_risk_type`,
    using `RISK_TYPE_SYNONYMS` from `data/schemas.py`). The former
    standalone `validate_risk_type()` / `normalize_risk_type()` helpers were
    dead code and have been removed.

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

## Type Handling

Dtypes are not compared — they are **coerced**. The loader edge seal casts every declared
column to its declared dtype with `strict=False`, so an `Int32` column where the schema
declares `Int64` is simply cast. A value that cannot be cast (a `"1.5%"` string in a
`Float64` column) becomes null, which currently carries no error of its own; treat the
source feed's dtypes as part of the input contract.

---

## Validation in the Pipeline

The pipeline validates data at stage boundaries:

```
Load → [seal_lenient: DQ001 + dtype cast] → [scrub_non_finite_values: DQ011]
     → [validate_bundle_values: DQ006/DQ010/DQ012/IRB001/IRB002/IRB003/IRB008/CRM009-011]
     → Hierarchy → Classify → CRM → Calculators → Aggregate
     → [validate_aggregated_bundle: OUT001-004]
```

Stage-to-stage column contracts are enforced by the producer seal
(`contracts/edges.py`), not by bundle validators: a stage that fails to emit a declared
column raises `EdgeContractViolation` at its own exit, which is a programming error rather
than a data-quality one.

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
