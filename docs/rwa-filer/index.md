# rwa-filer

`rwa-filer` validates regulatory returns against the supervisor's own published
rules and writes them in the format the regulator accepts. It is a separate
package from the calculator: it depends on Polars alone, never imports
`rwa_calc`, and is released on its own version. `rwa-calc` uses it to check the
returns it generates; any other system that can produce template-level figures
can use it the same way.

```bash
pip install rwa-filer
```

!!! warning "The regulator's validation is authoritative"
    A clean result from `rwa-filer` is evidence that a return is well-formed. It
    is not a guarantee that the regulator will accept it: the checks run on
    upload are the ones that count.

## What it does today

| Capability | Status |
|------------|--------|
| The published validation rules as package data (EBA DPM 3.0 for CRR, BoE banking v4.0.0 for Basel 3.1) | Available |
| Rule engine: evaluate every enforced rule against a return's templates | Available |
| `rwa-filer rules` — inspect, rebuild and check the rule extracts | Available |
| Taxonomy pack, file readers (Parquet, CSV, Excel) and `rwa-filer validate` | Planned |
| XBRL submission file and the Arelle referee | Planned |

## How a return reaches the engine

The engine reads a return through one shape, a `TemplateIndex`: the return's
frames, the publisher table code each one answers to, and — where the source
keys its sheets by something other than the publisher's sheet codes — a map
between the two. Whoever holds the figures builds it. The engine never sees
where they came from.

```python
import polars as pl
from rwa_filer.validate import SINGLE_SHEET, TableBinding, TemplateIndex, check_index

c02 = pl.DataFrame({"row_ref": ["0010"], "0010": [1_000.0]})

index = TemplateIndex(
    framework="CRR",
    frames={"own_funds_requirements": {SINGLE_SHEET: c02}},
    bindings={"C 02.00": TableBinding("own_funds_requirements", per_sheet=False)},
)

for finding in check_index(index):
    print(finding.code, finding.severity, finding.message)
```

Each frame has a `row_ref` column and one column per reported column reference.
`rwa-calc` builds its index from its generated template bundles in
`rwa_calc.reporting.filing`, which is the one place that knows how the
calculator's sheets map onto the published sheet codes.

## Findings

`check_index` returns a list of `Finding` records. It never raises for a
condition in the data.

| Code | Severity | Meaning |
|------|----------|---------|
| `VAL001` | Error | An Error-severity published rule is broken. The regulator rejects the return. |
| `VAL002` | Warning | A Warning-severity published rule is broken. It must be explained. |
| `VAL003` | Error | Coverage is insufficient: no rule could be executed at all, or a reported template had no rule executed against it. |

`VAL003` is what makes an empty list safe to read as "checked and clean". Without
it, a return on which no rule could run would produce no breaks and look
identical to a clean one.

`evaluate_index` returns the full `ValidationReport` behind the findings: one
outcome per enforced rule, with four distinct statuses.

| Status | Meaning |
|--------|---------|
| `PASS` | The rule ran on real figures and holds. |
| `FAIL` | The rule ran and is broken. |
| `VACUOUS` | The rule ran, but every operand was null or zero. This is not counted as a pass. |
| `NOT_EVALUATED` | The rule could not run, with a recorded reason (a template, sheet, row or column the return does not carry, or grammar the engine does not yet support). |

A cell the return does not carry is a skip, never a zero. The publisher's own
choice between "treat a missing value as zero" and "do not run the rule" is
honoured per rule, as is the choice between a rounding-tolerant and an exact
comparison.

## The `rwa-filer` command

```bash
# The packaged rule extracts
rwa-filer rules list

# Rebuild an extract from a publisher's rule workbook (needs rwa-filer[excel])
rwa-filer rules import --publisher boe rules.xlsx --out extract.json

# Fail if the packaged extract is not exactly what the workbook yields
rwa-filer rules check --publisher boe rules.xlsx
```

The rule workbooks are the publishers' own files and are not redistributed. The
JSON extracts built from them ship inside the package, so validating a return
needs no spreadsheet and no network access. See
[Reporting Validation Rules](../reference/validation-rules/index.md) for the
extract schema and the two rule grammars.

## In this repository

`rwa-filer` lives at `packages/rwa-filer` as a uv workspace member. See
[Workspace & Packages](../development/workspace.md) for how the two packages
share one repository and are released separately.
