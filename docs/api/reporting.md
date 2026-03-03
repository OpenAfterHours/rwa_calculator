# Reporting API

The reporting module generates regulatory templates from calculation results.

## COREPGenerator

Transforms exposure-level RWA results into COREP-formatted DataFrames for regulatory
reporting. Stateless — no constructor parameters required.

```python
from rwa_calc.reporting import COREPGenerator

generator = COREPGenerator()
```

### `generate_from_lazyframe()`

Primary entry point for generating COREP templates from pipeline output.

```python
def generate_from_lazyframe(
    self,
    results: pl.LazyFrame,
    *,
    framework: str = "CRR",
) -> COREPTemplateBundle:
```

**Parameters:**

- `results` — LazyFrame containing exposure-level calculation results. The generator is
  resilient to column naming variations (e.g., `ead_final` or `final_ead` or `ead`).
- `framework` — `"CRR"` or `"BASEL_3_1"`. Stored in the output bundle for reference.

**Approach filtering:** SA templates filter on `approach_applied == "standardised"`;
IRB templates filter on `approach_applied in ("foundation_irb", "advanced_irb", "slotting")`.

### `generate()`

Convenience method that generates from a `CalculationResponse` (scans cached Parquet).

```python
def generate(
    self,
    response: CalculationResponse,
) -> COREPTemplateBundle:
```

### `export_to_excel()`

Writes templates to a multi-sheet Excel workbook.

```python
def export_to_excel(
    self,
    bundle: COREPTemplateBundle,
    output_path: Path,
) -> ExportResult:
```

Creates 4 sheets: `"C 07.00"`, `"C 07.00 RW Breakdown"`, `"C 08.01"`, `"C 08.02"`.

Requires `xlsxwriter` — raises `ModuleNotFoundError` with install instructions if missing.
Creates parent directories automatically.

Returns `ExportResult(format="corep_excel", files=[output_path], row_count=total_rows)`.

## COREPTemplateBundle

Frozen dataclass containing all generated templates.

```python
@dataclass(frozen=True)
class COREPTemplateBundle:
    c07_00: pl.DataFrame           # C 07.00 — SA credit risk
    c08_01: pl.DataFrame           # C 08.01 — IRB totals
    c08_02: pl.DataFrame           # C 08.02 — IRB by PD grade
    c07_rw_breakdown: pl.DataFrame # C 07.00 risk weight breakdown
    framework: str = "CRR"         # "CRR" or "BASEL_3_1"
    errors: list[str] = field(default_factory=list)
```

## Template Constants

These constants define the regulatory template structure and are available from
`rwa_calc.reporting.corep.templates`:

### `COREPRow`

```python
@dataclass(frozen=True)
class COREPRow:
    ref: str                            # Row reference (e.g., "0010")
    name: str                           # Display name
    exposure_class_value: str | None    # Maps to ExposureClass.value
```

### `COREPColumn`

```python
@dataclass(frozen=True)
class COREPColumn:
    ref: str   # Column reference (e.g., "010")
    name: str  # Display name
```

### Row and Column Mappings

| Constant | Purpose |
|----------|---------|
| `SA_EXPOSURE_CLASS_ROWS` | Maps `ExposureClass.value` → `(row_ref, display_name)` for C 07.00 |
| `IRB_EXPOSURE_CLASS_ROWS` | Maps `ExposureClass.value` → `(row_ref, display_name)` for C 08.01/C 08.02 |
| `C07_COLUMNS` | 9 column definitions for C 07.00 |
| `C08_01_COLUMNS` | 11 column definitions for C 08.01 |
| `C08_02_COLUMNS` | Same as `C08_01_COLUMNS` |
| `SA_RISK_WEIGHT_BANDS` | 14 standard risk weight bands for C 07.00 breakdown |
| `PD_BANDS` | 8 PD bands for C 08.02 (contiguous, covering 0%–100%) |

## Import Paths

```python
# Core classes (recommended)
from rwa_calc.reporting import COREPGenerator, COREPTemplateBundle

# Template constants
from rwa_calc.reporting.corep.templates import (
    SA_EXPOSURE_CLASS_ROWS,
    IRB_EXPOSURE_CLASS_ROWS,
    C07_COLUMNS,
    C08_01_COLUMNS,
    PD_BANDS,
    SA_RISK_WEIGHT_BANDS,
)
```
