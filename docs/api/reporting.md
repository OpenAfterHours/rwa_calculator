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

!!! note "Template structure"
    The templates follow the published EBA/PRA structures. Three consequences are
    worth stating, because each is a shape a caller can get wrong:

    - Templates are **per-exposure-class submissions** — the exposure class is a
      sheet dimension, not a row (see *Exposure-class axis maps* below)
    - Row and column references use the 4-digit COREP numbering, and both differ
      between the CRR and Basel 3.1 variants of the same template
    - The risk-weight breakdown is a row *section* within C 07.00, not a separate
      template

    See [COREP Reporting](../features/corep-reporting.md) for the template detail.

## Template Constants

These constants define the regulatory template structure. All of them are
re-exported from the package `rwa_calc.reporting.corep`, which is the import path
to prefer. Their module homes are `corep/templates.py` (rows, columns, bands and
the exposure-class maps) and `corep/sheet_labels.py` (display names for the
C 07.00 / OF 07.00 sheet axis).

### `COREPRow`

```python
@dataclass(frozen=True)
class COREPRow:
    ref: str                                  # Row reference, e.g. "0010"
    name: str                                 # Display name
    exposure_class_value: str | None = None   # Maps to ExposureClass.value
```

### `COREPColumn`

```python
@dataclass(frozen=True)
class COREPColumn:
    ref: str         # Column reference, e.g. "0010" (4-digit COREP refs)
    name: str        # Display name
    group: str = ""  # Logical group (e.g. "Exposure", "CRM Substitution")
```

### Exposure-class axis maps

The SA and IRB templates are submitted **once per exposure class**, so the class
is a *sheet* dimension rather than a row: an `ExposureClass` value is folded onto
a sheet key, and the sheet key is separately named for display. Those are two
jobs and two maps — a map that carries both a row ref and a name for this axis is
describing a template that does not exist.

| Constant | Purpose |
|----------|---------|
| `C07_00_SA_SHEET_MAP` | `ExposureClass.value` → C 07.00 / OF 07.00 **sheet key**, i.e. the CRR Art. 112(1) class the exposure is reported under. Total over `ExposureClass`, and several members fan into one key: `corporate_sme` and `specialised_lending` → `corporate`; `retail_qrre` and `retail_other` → `retail`; `retail_mortgage`, `residential_mortgage` and `commercial_mortgage` → `real_estate`. Applied in `corep/c07.py` |
| `C07_00_SA_SHEET_KEYS` | The sheet keys that map can produce. A key outside this set reached the axis through the pass-through limb — it is not an Art. 112(1) class |
| `get_c07_sheet_labels(framework)` | Display name per C 07.00 sheet key, resolved **per regime**: PS1/26 renames four of the Art. 112(1) classes, so `"CRR"` and `"BASEL_3_1"` return different strings. Feeds the Excel tab name and the UI sheet picker. Callers fall back to the raw key for an unmapped sheet |
| `IRB_EXPOSURE_CLASS_LABELS` | Display name per Art. 147(2) IRB class, for the C 08.01–C 08.05 tabs. Labels only, and one map for both regimes |
| `C02_00_SA_CLASS_MAP` | `ExposureClass.value` → C 02.00 / OF 02.00 SA class **row ref** — C 02.00 carries the same Art. 112 fan-in on rows rather than on sheets |

!!! warning "`SA_EXPOSURE_CLASS_ROWS` and `IRB_EXPOSURE_CLASS_ROWS` no longer exist"
    Both mapped `ExposureClass.value` → `(row_ref, display_name)`, and neither set
    of row refs addressed a live template — `SA_EXPOSURE_CLASS_ROWS` gave `equity`
    ref 0110, which C 09.01 spends on high-risk exposures. `SA_EXPOSURE_CLASS_ROWS`
    is deleted; `IRB_EXPOSURE_CLASS_ROWS` is narrowed to the label half above. See
    the [changelog](../appendix/changelog.md).

### Row and column definitions

Prefer the framework accessors — `get_c07_columns(framework)`,
`get_c08_columns(framework)` and their siblings — over the underlying constants,
so a caller does not have to branch on the regime itself.

| Constant | Purpose |
|----------|---------|
| `CRR_C07_COLUMNS` / `B31_C07_COLUMNS` | Column definitions for CRR C 07.00 and Basel 3.1 OF 07.00 (4-digit refs from 0010) |
| `CRR_C08_COLUMNS` / `B31_C08_COLUMNS` | Column definitions for CRR C 08.01 and Basel 3.1 OF 08.01 |
| `SA_RISK_WEIGHT_BANDS` | CRR SA risk weight bands as `(risk_weight_decimal, label)`, 0% through 1250% |
| `B31_SA_RISK_WEIGHT_BANDS` | Basel 3.1 SA risk weight bands — a finer scale over the same 0%–1250% range |
| `PD_BANDS` | Contiguous PD bands as `(lower, upper, label)`, 0% through default. Keys the C 08.02 rows only when the data carries no obligor grade; where a grade is present the grades themselves are the rows |

## Import Paths

```python
# Core classes (recommended)
from rwa_calc.reporting import COREPGenerator, COREPTemplateBundle

# Template constants — all re-exported from the package
from rwa_calc.reporting.corep import (
    C02_00_SA_CLASS_MAP,
    C07_00_SA_SHEET_KEYS,
    C07_00_SA_SHEET_MAP,
    IRB_EXPOSURE_CLASS_LABELS,
    PD_BANDS,
    SA_RISK_WEIGHT_BANDS,
    get_c07_columns,
    get_c07_sheet_labels,
    get_c08_columns,
)
```
