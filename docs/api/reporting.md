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
- `framework` — `"CRR"` or `"BASEL_3_1"`. Determines which template variant to generate
  (C prefix for CRR, OF prefix for Basel 3.1) and which columns/rows to include.

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

Creates sheets per template per exposure class (e.g., `"C 07.00 - Corporate"`,
`"C 08.01 - Corporate"`, `"C 08.02 - Corporate"`).

Requires `xlsxwriter` — raises `ModuleNotFoundError` with install instructions if missing.
Creates parent directories automatically.

Returns `ExportResult(format="corep_excel", files=[output_path], row_count=total_rows)`.

## COREPTemplateBundle

Frozen dataclass containing all generated templates.

```python
@dataclass(frozen=True)
class COREPTemplateBundle:
    c07_00: pl.DataFrame     # C 07.00 / OF 07.00 — SA credit risk
    c08_01: pl.DataFrame     # C 08.01 / OF 08.01 — IRB totals
    c08_02: pl.DataFrame     # C 08.02 / OF 08.02 — IRB by obligor grade
    framework: str = "CRR"   # "CRR" or "BASEL_3_1"
    errors: list[str] = field(default_factory=list)
```

!!! note "Implementation status"
    The generator is being reworked to match the actual EBA/PRA template structures.
    See [COREP Reporting](../features/corep-reporting.md) for the correct template
    structures and `IMPLEMENTATION_PLAN.md` for the phased rework plan. Key changes:

    - Templates are per-exposure-class submissions (not one-row-per-class)
    - Column refs use 4-digit COREP numbering (0010-0240 for C 07.00, 0010-0310 for C 08.01)
    - C 07.00 has 24 columns (CRR) / 22 columns (Basel 3.1), not 9
    - C 08.01 has 33 columns (CRR) / 40+ columns (Basel 3.1), not 11
    - Risk weight breakdown is Section 3 within C 07.00, not a separate template

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
    ref: str   # Column reference (e.g., "0010")
    name: str  # Display name
```

### Row and Column Mappings

| Constant | Purpose |
|----------|---------|
| `SA_EXPOSURE_CLASS_ROWS` | Maps `ExposureClass.value` → `(row_ref, display_name)` — used as filter values for per-class template generation |
| `IRB_EXPOSURE_CLASS_ROWS` | Maps `ExposureClass.value` → `(row_ref, display_name)` — filter values for C 08.01/C 08.02 |
| `CRR_C07_COLUMNS` | 24 column definitions for CRR C 07.00 (refs 0010-0240) |
| `B31_C07_COLUMNS` | 22 column definitions for Basel 3.1 OF 07.00 |
| `CRR_C08_COLUMNS` | 33 column definitions for CRR C 08.01 (refs 0010-0310) |
| `B31_C08_COLUMNS` | 40+ column definitions for Basel 3.1 OF 08.01 |
| `SA_RISK_WEIGHT_BANDS` | 15 CRR risk weight bands (0%-1250% + Other) |
| `B31_SA_RISK_WEIGHT_BANDS` | 29 Basel 3.1 risk weight bands |
| `PD_BANDS` | 8 PD bands for C 08.02 aggregation (contiguous, 0%-100%) |

## Import Paths

```python
# Core classes (recommended)
from rwa_calc.reporting import COREPGenerator, COREPTemplateBundle

# Template constants
from rwa_calc.reporting.corep.templates import (
    SA_EXPOSURE_CLASS_ROWS,
    IRB_EXPOSURE_CLASS_ROWS,
    CRR_C07_COLUMNS,
    CRR_C08_COLUMNS,
    PD_BANDS,
    SA_RISK_WEIGHT_BANDS,
)
```
