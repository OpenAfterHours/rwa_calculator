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
| The Bank of England's validation rules for taxonomy v4.1.1: all 3,813 rules of all 11 return families, as package data | Available |
| Rule engine that evaluates those rules as the Bank's gateway does, on any return in canonical form | Available for 14 modules |
| Taxonomy packs: the tables, cells and data points of a reporting module | Available for 14 modules |
| The EBA (CRR) and BoE v4.0.0 rule extracts, and the template-level engine `rwa-calc` uses on its own frames | Available |
| Structure checks: every fact sits in a cell the taxonomy accepts | Available |
| File readers (Parquet, CSV, Excel, XBRL) and `rwa-filer validate` | Available |
| XBRL submission file: `rwa-filer build` writes the instance, a zip where required, and a manifest | Available |
| Preparer workflow: cell adjustments with reasons, an audit ledger, sign-off, and a diff between two versions | Available |
| Arelle referee: run an independent XBRL processor on a written file from the command line | Planned |

## Validating a file

```bash
# A long-format fact table: one row per reported cell
rwa-filer validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# A workbook in the template layout carries its own header
rwa-filer validate return.xlsx --format json --report findings.json

# An XBRL instance from any system, bare or zipped
rwa-filer validate return.xbrl
```

The exit code is `0` when nothing blocks submission and `1` when something
does. `--report` writes every finding as JSON whatever the outcome.

A return is checked in two steps. **Structure** comes first: each fact is looked
up in the taxonomy pack for the module and reference date. **Rules** follow: the
Bank's published validation rules run over the same facts. A structure finding
does not stop the rules from running, so one pass reports everything.

## Modules

| Module | Return | Rules enforced | Validated and written |
|--------|--------|---------------:|-----------------------|
| `PRA001` | Banking reporting (COREP own funds, credit risk, market risk and the rest) | 1,441 | Yes |
| `PRA116` | Banking reporting for SDDTs | 531 | Yes |
| `PRA112`, `PRA113`, `PRA114` | Capital+ | 46, 18, 3 | Yes |
| `PRA117`, `PRA118` | Capital+ for SDDTs | 13, 9 | Yes |
| `LVR001`, `LVR002` | Leverage ratio; contingent leverage | 61, 48 | Yes |
| `MRL001`, `MRL003` | MREL | 15, 11 | Yes |
| `PRA_IFRS`, `PRA_GAAP`, `PRA_MEM` | Financial statements | 13, 15, 2 | Yes |
| `PRA110` | Liquidity Pillar II | 1,108 | Not yet |
| `PRA115` | Step-in risk | 26 | Not yet |
| `RFB001`–`RFB008` | Ring-fencing | 370 in total | Not yet |

For the ten modules marked "not yet", the rules are packaged but the taxonomy
pack is not: the compiled pack does not yet account for every fact of the Bank's
own sample file for that module, and a pack that rejects valid facts is not
shipped. Validating a return for one of those modules stops with a clear error.

## How the rules are evaluated

The Bank publishes each rule twice: as a formula inside the XBRL taxonomy, which
its gateway executes, and as a row in a workbook that says the same thing more
compactly. `rwa-filer` reads the workbook and evaluates the rule the way the
taxonomy's formula is evaluated, so that a rule passes or fails here when it
would pass or fail on upload.

Four things follow from that, and each changes verdicts.

- **A rule runs only when every template it reads is reported.** If one is not,
  the gateway does not run the rule. It is reported as not evaluated, with the
  reason `template_not_reported`.
- **A rule runs once for every combination of cells it leaves open.** A rule
  written for a column runs once per row and per sheet. Each run is satisfied
  or unsatisfied; the rule fails if any run is unsatisfied.
- **An unreported cell is what the rule says it is.** Usually zero. A total
  reported without its parts therefore breaks the rule that the total equals
  the sum of the parts. Some references have no such default, and then the rule
  is not run where that cell is missing.
- **Comparisons allow for rounding, by the accuracy each figure states.** A
  figure stated to thousands may be off by up to 500, and a rule comparing two
  such figures allows for both. A figure stated to the penny gets no such
  allowance. The accuracy is the fact's `decimals`, or the default for its type.

The last point means the verdict depends on the accuracy the file will state.
`rwa-filer build --monetary-decimals` sets it, and the validation that decides
whether the file is written uses the same value.

!!! note "How the engine is checked"
    Arelle is an independent XBRL processor that executes the Bank's own formula
    files. On the Bank's sample files, `rwa-filer` and Arelle were compared rule
    by rule, counting satisfied and unsatisfied runs. They agree exactly on all
    254 rules of twelve modules, each run on the Bank's whole sample for it, and
    on all 456 PRA001 rules triggered by the four credit-risk template groups.
    Those counts are kept in the test suite and re-checked wherever the Bank's
    files are available. The engine needs about 20 seconds for all 1,441 PRA001
    rules over the Bank's 61,428-fact sample.

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
| `decimals` | No | The accuracy a number is stated to: `-3` is thousands, `2` is pence. Empty means the default for the cell's type. |

A monetary value is in units of the reporting currency, never thousands or
millions. A percentage or ratio is a decimal fraction: 9.31% is `0.0931`.

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

## Writing the submission file

```bash
rwa-filer build return.parquet --out filing/ \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001
```

`build` validates the return and, if nothing stands in the way, writes three
files into the output directory:

| File | What it is |
|------|------------|
| `<entity>_<module>_<date>.xbrl` | The XBRL instance. |
| `<entity>_<module>_<date>.zip` | The instance, zipped. Written when the instance is over 10 MB, which the Bank requires, or when `--zip` is given. This is then the file to upload. |
| `<entity>_<module>_<date>.manifest.json` | What was filed: the taxonomy, the fact and template counts, the SHA-256 of each file, and the full validation result. |

Nothing is written while a structure finding stands: such a return cannot be
expressed in the taxonomy. Nothing is written while a rule check fails either,
unless `--force` is given. A forced file is still reported as not submittable,
in the exit code and in the manifest.

| Option | Effect |
|--------|--------|
| `--monetary-decimals N` | The accuracy monetary figures are stated to. The default is `-3` (thousands), the convention of the Bank's own sample files. Use `0` for units or `2` for pence. |
| `--percentage-decimals N` | The accuracy of percentages and ratios. The default, and the minimum the Bank accepts, is `4`. |
| `--declare-unreported` | Also declare every template the return does not report as not reported. |
| `--zip` | Write a zip whatever the size. |
| `--force` | Write the instance even though a rule check fails. |
| `--no-timestamp` | Leave out the creation time, so the same return always gives byte-identical files. |

The file follows the Bank of England XBRL Filing Manual. Each data point is
written once, even where the templates show it in two tables. Values are
written as known, in units, with `decimals` stating their accuracy; the unit is
the reporting currency for money and `pure` for everything else. A positive
filing indicator is written for every template that has a fact.

!!! note "How the writer is checked"
    The Bank publishes a sample PRA001 file holding one fact for every data
    point of the module: 61,428 facts across all 104 tables. Reading that file
    and writing it back through `rwa-filer` reproduces every fact exactly, with
    the same metric, dimension members, value and decimals. That test runs
    locally against the Bank's file, which is not redistributed.

## Adjusting, signing off and comparing

A filing is rarely the unedited output of a system. These commands make each
manual step a recorded act.

### Adjustments

An adjustments file is a fact table with a `reason` column. Each row sets or
changes one cell, or removes it with `remove` set to `yes`.

```csv
table,sheet,row,column,value,reason,remove
OF07.00.01.01,0008,0010,0010,0,Booked to the wrong class,
OF07.00.01.01,0008,0010,0030,,Follows the exposure,yes
```

```bash
rwa-filer build return.parquet --out filing/ \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001 \
    --adjustments adjustments.csv --author "A. Preparer"
```

The adjustments are applied first, and the adjusted return is validated like
any other. The batch is applied whole or not at all: it is refused if any row
gives no reason, targets a cell twice, or removes a cell that is not reported.
The manifest lists every adjustment with what the cell held before and after.

### The audit ledger

When `--author` is given, `build` appends to `<name>.ledger.jsonl` beside the
files: one entry for the adjustments and one for the build, with the author,
the time and the instance's SHA-256. `signoff` adds a third.

Each entry carries the hash of the entry before it and a hash of its own
content. Changing, removing or re-ordering an entry breaks the chain, and
`verify` reports where. A ledger that does not verify is never extended.

### Sign-off

```bash
rwa-filer signoff filing/5493001KJTIIGC8Y1R12_PRA001_2027-03-31.manifest.json \
    --approver "C. Approver" --role "Head of Regulatory Reporting"
```

This writes `<name>.signoff.json`: who approved, in what capacity, when, and the
SHA-256 of the instance approved. A package the validation found not
submittable is signed only with `--acknowledge-findings`, and the record says
so.

```bash
rwa-filer verify filing/5493001KJTIIGC8Y1R12_PRA001_2027-03-31.manifest.json
```

`verify` checks that the instance and the zip are the files the manifest
describes, that the sign-off was given for exactly them, and that the ledger is
intact. It exits `1` if any of that fails. Run it immediately before upload.

!!! warning "A sign-off is a record, not a digital signature"
    It shows what was approved and that the file has not changed since. It does
    not prove who wrote the sign-off file, and it does not stop someone who can
    write the files from rebuilding all of them. Keep the files where the people
    who prepare a filing cannot rewrite its history.

### What changed since the last filing

```bash
rwa-filer diff filed.xbrl resubmission.xbrl
```

`diff` compares two versions of a return cell by cell and lists the cells
added, removed and changed, with the figures. Each side may be any file
`validate` reads, so a source table can be compared with the instance built
from it. The exit code is `0` when the two are identical and `1` otherwise.
`--format json` gives every change.

### Reading an XBRL file

`rwa-filer validate` accepts an `.xbrl` file, or a `.zip` holding one, written
by any system. Each fact is put back in the cell the taxonomy shows it in, and
the same structure checks and rules then run. The taxonomy version comes from
the file's own `schemaRef`.

Three findings are specific to a file. All are Errors.

| Code | Meaning |
|------|---------|
| `XBR001` | A fact is not a data point of the module: no reportable cell has that metric with those dimension members. |
| `XBR002` | A fact appears only in templates the file does not declare as reported. |
| `XBR003` | The file breaks a Filing Manual rule the reader can see without loading the taxonomy: more than one entity or date, a `segment`, `precision` instead of `decimals`, a `nil` or empty fact, an unused context, an undefined unit, or one fact reported twice with different values. |

The reader does not load the taxonomy's own schemas, so it cannot say that a
file is valid XBRL against them. That is what the referee is for.

## Taxonomy packs

A taxonomy pack is the regulator's data point model for one reporting module,
compiled into three small files: which tables the module has, which cells of
each table are reportable, and which data point each cell reports. It ships
inside the package, so validation needs no network access.

```bash
rwa-filer taxonomy list
```

| Module | Applies from | Tables | Reportable cells |
|--------|--------------|-------:|-----------------:|
| `PRA001` | 1 January 2027 | 104 | 61,615 |
| `PRA116` | 1 January 2027 | 26 | 23,165 |
| `PRA112` / `PRA113` / `PRA114` | 27 February 2026 | 6 / 6 / 5 | 1,681 / 788 / 62 |
| `PRA117` / `PRA118` | 27 February 2026 | 5 / 5 | 539 / 41 |
| `LVR001` | 27 February 2026 | 8 | 329 |
| `LVR002` | 11 May 2023 | 5 | 159 |
| `MRL001` / `MRL003` | 22 June 2026 | 3 / 2 | 277 / 59 |
| `PRA_IFRS` / `PRA_GAAP` / `PRA_MEM` | 31 July 2021 | 5 / 5 / 3 | 152 / 182 / 43 |

All are compiled from the Bank of England banking taxonomy v4.1.1. A module is
packaged only when every fact of the Bank's own sample file for it is a data
point of the compiled pack.

The pack is chosen by the return's module and reference date. A reference date
before a pack applies has no pack, and validation says so and stops there:
it does not fall back to a different version. The "applies from" dates are the
dates in each framework's taxonomy entry point, except for the two Basel 3.1
returns, which apply from 1 January 2027.

A pack is compiled from three files the Bank of England publishes: the annotated
templates, the DPM dictionary and the XBRL taxonomy package. The taxonomy is
authoritative for which cells are reportable. The compile is reproducible: the
same three files always give byte-identical output.

```bash
rwa-filer taxonomy compile --module PRA001 --valid-from 2027-01-01 \
    --annotated "Annotated Templates.xlsx" --dictionary "DPM dictionary.xlsx" \
    --taxonomy taxonomy-package.zip --out pra001-4.1.1/
```

## The template-level engine

`rwa-filer` also carries an older, simpler engine that `rwa-calc` uses to check
its own template frames, including the EBA's rules for CRR. It reads a return
through one shape, a `TemplateIndex`: the return's frames, the publisher table
code each one answers to, and — where the source keys its sheets by something
other than the publisher's sheet codes — a map between the two.

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

This engine works on whole template frames rather than on facts. It treats a
missing cell as a skip, sums a list of cells where the Bank's gateway would test
each one, and uses one tolerance for a whole rule. `validate_return` does not
use it.

## Findings

Validation returns a list of `Finding` records. It never raises for a condition
in the data.

| Code | Severity | Meaning |
|------|----------|---------|
| `VAL001` | Error | An Error-severity published rule is broken. The regulator rejects the return. |
| `VAL002` | Warning | A Warning-severity published rule is broken. It must be explained. |
| `VAL003` | Error | Coverage is insufficient: no rule could be executed at all, or a reported template that has rules had none of them executed. |

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
| `STR010` | The return declares its filing indicators, and one of them is not a template of the module, or a fact sits in a template not declared as reported. |

Each fact is reported once, against its root cause. A fact in an unknown table
is `STR001` only; it is not also reported as an unknown cell.

The report behind the findings has one result per enforced rule.

| Status | Meaning |
|--------|---------|
| `PASS` | The rule ran at least once and every run was satisfied. |
| `FAIL` | At least one run was unsatisfied. The result lists the first few, with the cells involved. |
| `NOT_EVALUATED` | The rule did not run. The reason is `template_not_reported` (a template it reads is not reported), `no_data` (none of its cells is reported), or `unsupported`. |

No enforced rule of a supported module is `unsupported` today. That is held by a
test: a rule the engine cannot evaluate must be entered in a register by name,
and the register is empty.

## The `rwa-filer` command

```bash
# The packaged Bank of England rule books: modules, rules, rules enforced
rwa-filer rulebook list

# Rebuild a rule book from one of the Bank's validation workbooks
rwa-filer rulebook import "Validations Banking Reporting v4.1.1.xlsx" --out rulebooks/

# Fail if the packaged rule book is not exactly what the workbook yields
rwa-filer rulebook check "Validations Banking Reporting v4.1.1.xlsx"

# The packaged rule extracts used by the template-level engine
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
