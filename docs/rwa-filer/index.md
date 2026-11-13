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
| Taxonomy pack: the tables, cells and data points of a reporting module (PRA001, taxonomy v4.1.1) | Available |
| Structure checks: every fact sits in a cell the taxonomy accepts | Available |
| File readers (Parquet, CSV, Excel) and `rwa-filer validate` | Available |
| XBRL submission file and the Arelle referee | Planned |

## Validating a file

```bash
# A long-format fact table: one row per reported cell
rwa-filer validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# A workbook in the template layout carries its own header
rwa-filer validate return.xlsx --format json --report findings.json
```

The exit code is `0` when nothing blocks submission and `1` when something
does. `--report` writes every finding as JSON whatever the outcome.

A return is checked in two steps. **Structure** comes first: each fact is looked
up in the taxonomy pack for the module and reference date. **Rules** follow: the
published validation rules run over the same facts. A structure finding does not
stop the rules from running, so one pass reports everything.

### The fact table

A Parquet or CSV return is a table with one row per reported cell.

| Column | Required | Meaning |
|--------|----------|---------|
| `table` | Yes | The published table code, e.g. `OF07.00.01.01` |
| `row` | Yes | Row code, e.g. `0010` (a bare `10` is padded) |
| `column` | Yes | Column code, e.g. `0010` |
| `value` | Yes | The figure. Leave empty for a text cell. |
| `sheet` | For tables with a sheet axis | The published sheet code, e.g. `0008` |
| `open_key` | For tables with an open axis | The open-axis member, e.g. a country code |
| `text_value` | For text cells | The cell's text |

A fact table carries no header, so the reporting entity, reference date and
module are given on the command line.

Some tables have open rows: the template lists no rows, and the filer adds one
per obligor grade, counterparty or similar. For these, `row` is any identifier
that is unique within the table and sheet, and each row also carries a fact in
every key column (for example the obligor grade in column `0005` of
`OF08.02.01.01`). The key is what the row's figures are reported under.

### The workbook

`rwa-filer template` writes a blank workbook for a module: one worksheet per
table and sheet, laid out as the published template, with the cells the
taxonomy does not accept shaded grey. Fill it in and pass it to `validate`.

```bash
rwa-filer template --module PRA001 --reference-date 2027-03-31 \
    --tables OF02.00.01.01 OF07.00.01.01 --out return.xlsx
```

Reading and writing workbooks needs the `rwa-filer[excel]` extra.

### From Python

```python
from datetime import date

import polars as pl
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.validate.returns import validate_return

header = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), "PRA001")
facts = pl.DataFrame(
    {"table": ["OF02.00.01.01"], "row": ["0010"], "column": ["0010"], "value": [1_000.0]}
)

result = validate_return(CanonicalReturn.from_frame(header, facts))
print(result.is_submittable)
for finding in result.findings:
    print(finding.code, finding.message)
```

This one-cell return prints `False` and a single `VAL003`: the cell is valid,
but no published rule can run on one cell, and a return nothing was checked
against is not reported as clean.

## Taxonomy packs

A taxonomy pack is the regulator's data point model for one reporting module,
compiled into three small files: which tables the module has, which cells of
each table are reportable, and which data point each cell reports. It ships
inside the package, so validation needs no network access.

```bash
rwa-filer taxonomy list
```

| Module | Taxonomy | Applies from | Tables | Reportable cells |
|--------|----------|--------------|--------|------------------|
| `PRA001` | Bank of England banking v4.1.1 | 1 January 2027 | 104 | 61,615 |

The pack is chosen by the return's module and reference date. A reference date
before a pack applies has no pack, and validation says so and stops there:
it does not fall back to a different version.

A pack is compiled from three files the Bank of England publishes: the annotated
templates, the DPM dictionary and the XBRL taxonomy package. The taxonomy is
authoritative for which cells are reportable. The compile is reproducible: the
same three files always give byte-identical output.

```bash
rwa-filer taxonomy compile --module PRA001 --valid-from 2027-01-01 \
    --annotated "Annotated Templates.xlsx" --dictionary "DPM dictionary.xlsx" \
    --taxonomy taxonomy-package.zip --out pra001-4.1.1/
```

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

`validate_return` builds the index itself from a canonical return, so a caller
holding a fact table does not need to.

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

`validate_return` adds the structure findings. All are Errors: the regulator
rejects a file that has any of them.

| Code | Meaning |
|------|---------|
| `STR001` | The return names a table the module does not have. |
| `STR002` | A fact sits in a cell the taxonomy does not accept: an unknown row or column, or a greyed-out cell. |
| `STR003` | A fact names a sheet the table does not have, or omits one it needs. |
| `STR004` | A fact's open-axis member is not one the table accepts, or a row of an open-row table has a key that is missing or of the wrong type. |
| `STR005` | The same cell is reported more than once, or two rows of an open-row table carry the same key. |
| `STR006` | A value is not of the cell's type, for example a fraction in a whole-number cell. |
| `STR007` | One data point is reported in two cells with different values. |
| `STR008` | The header is invalid: the identifier is not a valid LEI, or the module is unknown. |
| `STR009` | The return carries no facts. |

Each fact is reported once, against its root cause. A fact in an unknown table
is `STR001` only; it is not also reported as an unknown cell.

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
