# Data Model

This section documents the data schemas used throughout the RWA calculator, including input requirements, intermediate structures, and output formats.

## Overview

The calculator uses Polars schemas to define and validate data at each stage:

```mermaid
flowchart LR
    A[Input Schemas] --> B[Intermediate Schemas] --> C[Output Schemas]
```

## Schema Categories

### Input Schemas

Define the structure of data loaded from external sources:

- [**Input Schemas**](input-schemas.md)
  - Counterparty Schema
  - Facility Schema
  - Loan Schema
  - Contingent Schema
  - Collateral Schema
  - Guarantee Schema
  - Provision Schema
  - Rating Schema
  - FX Rates Schema
  - Specialised Lending Schema
  - Equity Exposure Schema
  - Mapping Schemas (Facility, Org, Lending)

### Data Validation

Validation rules and troubleshooting:

- [**Data Validation Guide**](data-validation.md)
  - Schema Validation Functions
  - Business Rule Validators
  - Common Errors and Fixes
  - Debugging Tips

### Intermediate Schemas

Define internal data structures used during processing:

- [**Intermediate Schemas**](intermediate-schemas.md)
  - Resolved Hierarchy Schema
  - Classified Exposure Schema
  - CRM Adjusted Schema

### Output Schemas

Define the structure of calculation results:

- [**Output Schemas**](output-schemas.md)
  - SA Result Schema
  - IRB Result Schema
  - Slotting Result Schema
  - Aggregated Result Schema

### Regulatory Tables

Lookup tables for risk weights and parameters:

- [**Regulatory Tables**](regulatory-tables.md)
  - Risk Weight Tables
  - CCF Tables
  - Haircut Tables
  - Slotting Tables
  - F-IRB LGD Tables

## Schema Usage

### Validation

Schema *shape* is enforced by the loader edge seal, not by a validator you call: a
missing required column becomes a typed null plus a `DQ001` error, and declared columns
are cast to their declared dtype. What you call explicitly is the input-*domain* gate.

```python
from rwa_calc.contracts.validation import validate_bundle_values

# Categorical and numeric column domains across the whole raw bundle
errors = validate_bundle_values(bundle)

for error in errors:
    print(f"{error.code} {error.field_name}: {error.message}")
```

Both pipeline entries run this already — the file loader attaches its errors to the
returned `RawDataBundle`, and `PipelineOrchestrator.run_with_data` runs it for in-memory
bundles. Call it directly only when validating a bundle outside a run.

### Type Checking

```python
import polars as pl
from rwa_calc.data.schemas import FACILITY_SCHEMA

# Create DataFrame with explicit schema
facilities = pl.DataFrame({
    "facility_reference": ["F001", "F002"],
    "counterparty_reference": ["C001", "C001"],
    "limit": [1_000_000.0, 500_000.0],
}).cast(FACILITY_SCHEMA)
```

## Data Types

| Polars Type | Python Type | Usage |
|-------------|-------------|-------|
| `pl.String` | `str` | IDs, names, codes |
| `pl.Float64` | `float` | Amounts, rates, weights |
| `pl.Int8` | `int` | CQS values, IFRS 9 stages |
| `pl.Boolean` | `bool` | Flags, indicators |
| `pl.Date` | `date` | Dates |
| `pl.Datetime` | `datetime` | Timestamps |

## Nullable Fields

Optional fields are marked with `| None` in schemas:

```python
COUNTERPARTY_SCHEMA = {
    "counterparty_reference": pl.String,  # Required
    "annual_revenue": pl.Float64,         # Optional (can be null)
    "entity_type": pl.String,             # Required
}
```

## Next Steps

- [Input Schemas](input-schemas.md) - Required input data formats
- [Data Validation Guide](data-validation.md) - Validation and troubleshooting
- [Output Schemas](output-schemas.md) - Result data formats
- [Regulatory Tables](regulatory-tables.md) - Lookup table reference
