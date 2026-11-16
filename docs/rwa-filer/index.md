# rwa-filer

`rwa-filer` validates regulatory returns against the supervisor's own published
rules and writes them in the format the regulator accepts. It is a separate
package from the calculator: it depends on Polars and, for its dashboard, a small
web stack (Starlette, uvicorn, Jinja2); it never imports `rwa_calc`, and is
released on its own version. `rwa-calc` uses it to check the
returns it generates; any other system that can produce template-level figures
can use it the same way.

```bash
uvx rwa-filer@latest --help
```

`@latest` makes each run check PyPI and use the newest release of `rwa-filer`,
with every taxonomy release it carries; which of them a run uses is described in
[Taxonomy releases](#taxonomy-releases). A new taxonomy release reaches you as a
new `rwa-filer` release, and nothing else tells you one is out. Without `@latest`, `uvx` may run a copy it already has: one it fetched
recently, or one installed with `uv tool install`, for as long as that stays
installed. Extras go in quotes, so the shell leaves the brackets alone:
`uvx "rwa-filer[excel]@latest" ...`.

The manifest `build` writes records the version that wrote it. To repeat a run
on that version, name it in place of `latest`: `uvx rwa-filer@0.1.0 ...`.

```bash
# As a library in a uv project. The lock file holds it at one version;
# `uv lock --upgrade-package rwa-filer` moves it to the newest release
uv add rwa-filer

# As a command on your PATH, for a machine that has to run it offline. It
# stays on the version installed until you upgrade it
uv tool install rwa-filer
uv tool upgrade rwa-filer
```

The command examples on this page run `uvx rwa-filer@latest`. If you installed
it with `uv tool install`, type `rwa-filer` in its place, with any extra the
example names installed (`uv tool install "rwa-filer[excel]"`); in a uv
project, type `uv run rwa-filer`.

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
| The EBA (CRR) and BoE v4.1.1 rule extracts, and the template-level engine `rwa-calc` uses on its own frames | Available |
| Structure checks: every fact sits in a cell the taxonomy accepts | Available |
| File readers (Parquet, CSV, Excel, XBRL) and `rwa-filer validate` | Available |
| Evidence export: every rule outcome, evaluation and comparison behind a verdict, fingerprinted and versioned (`--evidence`) | Available |
| XBRL submission file: `rwa-filer build` writes the instance, a zip where required, and a manifest | Available |
| Preparer workflow: cell adjustments with reasons, an audit ledger, sign-off, a diff between two versions, and a comparison with another system's return that says why they differ | Available |
| Arelle referee: `rwa-filer referee` runs an independent XBRL processor on a written file and compares its verdict on every rule with this package's own | Available (needs Arelle and the Bank's taxonomy package) |
| Local web dashboard: `rwa-filer dash` — the verdict, the rules and the template grid in a browser ([guide](dash.md)) | Available |

## Validating a file

```bash
# A long-format fact table: one row per reported cell
uvx rwa-filer@latest validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# A workbook in the template layout carries its own header
uvx "rwa-filer[excel]@latest" validate return.xlsx --format json --report findings.json

# An XBRL instance from any system, bare or zipped
uvx rwa-filer@latest validate return.xbrl
```

The exit code is `0` when nothing blocks submission and `1` when something
does. `--report` writes the [validation report](#the-validation-report-and-the-evidence-export)
as JSON whatever the outcome, and `--evidence FILE.jsonl` writes the evidence
behind it.

A fact table states no accuracy of its own, so the rules' rounding allowances
come from the accuracy the file will be written with. `validate` takes the
same `--monetary-decimals` and `--percentage-decimals` as `build`, and reaches
the same verdict at the same setting. A rule can hold at thousands and break at
units, so validate at the accuracy you will file at:

```bash
uvx rwa-filer@latest validate return.parquet --monetary-decimals 0 \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001
```

The second line of the output is the **status**, which keeps "nothing failed"
apart from "everything was checked":

| Status | Meaning |
|--------|---------|
| `CLEAN` | Nothing blocks submission, and every check the module requires was run. |
| `INCOMPLETE` | Nothing blocks submission, but something was left unchecked: a linked template is not in the return, or a rule could not be evaluated. The status line names each cause. |
| `BLOCKED` | A finding stops the return being submitted. |

`--require-complete` makes an `INCOMPLETE` result exit `3`, so a pipeline can
refuse it without reading the JSON. Without the flag the exit codes are as
above.

A return is checked in two steps. **Structure** comes first: each fact is looked
up in the module's taxonomy pack, in the release the run uses. **Rules** follow:
the same release's published validation rules run over the same facts. A
structure finding does not stop the rules from running, so one pass reports
everything.

## Taxonomy releases

`rwa-filer` ships each taxonomy release it supports (today the Bank of England
banking taxonomy 4.1.1), and a run uses one of them. `--taxonomy VERSION` names it
on every command that reads a return (`validate`, `build`, `diff`, `compare`,
`dash`, `template` and `referee`); in Python, `taxonomy=` does the same. A run
always takes the taxonomy pack and the rules from the same release.

Without `--taxonomy`, a run uses the release **live** for the return's module: the
newest shipped release whose pack for that module applies on the day of the run.
Live, future and superseded belong to a module, not to a release. In 4.1.1, PRA001
and PRA116 apply from 1 January 2027, so they are *future* until then, while the
other twelve modules already apply. A module with no live release uses its only
future release; if it has several, the run stops and asks for a version.
`rwa-filer` never chooses between releases for you.

The return's reference date never chooses the release. When it falls outside the
dates the chosen release gives the module, the run reports `STR011`, a Warning:
the return is checked against the release asked for (to try next year's rules on
this year's return, say), but the regulator accepts a filing only against the
release in force on its reference date. `STR011` does not stop a build.

Every run says which release it used and why, after the verdict and the check's
status, with a line for each other shipped release and the option that selects it:

```text
BLOCKED: PRA001 for 5493001KJTIIGC8Y1R12 at 2027-03-31 (taxonomy 4.1.1, 2 facts, 1 tables)
  status: BLOCKED — linked templates not reported (3 template(s), 93 rule(s))
Taxonomy 4.1.1 (default) — PRA001 future from 1 January 2027; no live release shipped
```

The JSON report and the `build` manifest record the same in their `taxonomy`
block: `version`, `status`, `applies_from`, `applies_to`, `run_date`, `chosen_by`
(`default`; `version` when named; `pack` when a library caller passed the pack
itself), `shipped`, and `covers_reference_date`. `diff` uses a release only to read
an XBRL file, and prints no release line.

```bash
# Each shipped release's modules, their status today, and which a run uses
uvx rwa-filer@latest taxonomy list --module PRA001

# Validate against a named release
uvx rwa-filer@latest validate return.xbrl --taxonomy 4.1.1
```

An XBRL file names its entry point in its `schemaRef`, and only a release with
that entry point can read it. Without `--taxonomy` the default is chosen among
those releases; a named release with another entry point is refused, with both
entry points in the message.

A release `rwa-filer` no longer ships is recorded with the last version that
shipped it, and naming it says so: run that version, e.g.
`uvx "rwa-filer@0.2.0" validate return.xbrl --taxonomy 4.1.1`.

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

Eight things follow from that, and each changes verdicts.

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
- **Codes listed inside one reference belong to that reference alone.** A rule
  may name the same four columns in two references. The taxonomy's formula then
  reads every pair of them, sixteen runs, and not four runs column by column.
  Codes listed in the rule's scope are different: those are shared, and the
  rule runs once per code.
- **Naming one sheet of an open axis changes how the others are read.** Some
  tables are filed once per country, or per currency. A rule that never
  mentions the country runs once per country. A rule that names one, usually
  the all-countries total, makes the country part of the rule: a sum in the
  same rule is then taken over every country at once, and the rule runs once.
  "The sum over all countries, less the total, equals the total" is such a
  rule.
- **What a sum adds up is the formula's to say, not the workbook's.** On a
  table with one row per obligor grade, per securitisation or per entity, a sum
  in a rule either adds up every row or stays on the row the rest of the rule
  is read at, and the workbook writes both the same way. "OF 08.01's class total
  equals the sum over every grade of OF 08.02" adds up every row. "Each grade's
  total outflow equals the sum of its guarantees, credit derivatives and other
  funded protection" (`boe_b0761`) stays on the grade. The formula says which:
  it either covers the grade on the summed term or leaves it to be matched.
  The same holds for a table filed once per type of specialised lending, where
  OF 08.06's sums take every type at once although the rule names none. Read
  from the workbook alone, 28 rules come out wrong.
- **A rule the taxonomy's own formula cannot fire is not run.** The formula
  fixes most dimensions to "not applicable". If it does that to a dimension the
  rule's own cells carry, no reported fact can ever match, and the gateway never
  evaluates the rule. In taxonomy 4.1.1 this is the case for seven PRA001 rules
  on table OF 91.01, whose formulas fix the table's sheet dimension. They are
  reported as not evaluated, with the reason `closed_by_formula`. Evaluated from
  the workbook text alone, they could block a return the gateway accepts.

The fourth point means the verdict depends on the accuracy the file will state.
`rwa-filer build --monetary-decimals` sets it, and the validation that decides
whether the file is written uses the same value.

The last two points need the taxonomy package as well as the workbook, because
the workbook does not say what a formula fixes or what its sums cover. The
packaged rule books are built with both.

!!! note "How the engine is checked"
    Arelle is an independent XBRL processor that executes the Bank's own formula
    files. On the Bank's sample files, `rwa-filer` and Arelle were compared rule
    by rule, counting satisfied and unsatisfied runs. They agree on every rule
    PRA001 enforces, all 1,441, on a carve of all 104 tables of the Bank's
    sample, and exactly on all 254 rules of twelve further modules, each run on
    the Bank's whole sample for it. Those counts are kept in the test suite and
    re-checked wherever the Bank's files are available. The engine needs about
    20 seconds for all 1,441 PRA001 rules over the Bank's 61,428-fact sample.

    Two qualifications are recorded with the counts. For six rules Arelle
    reports more unsatisfied runs when it evaluates many rules in one session
    than when it evaluates each alone; the verdict is the same, and the counts
    kept are the ones from running each alone. For twelve rules that join two
    tables on a desk number, stock Arelle matches nothing and reports a break
    whatever is filed; the referee corrects that, as described under
    [The referee](#the-referee), and with the correction Arelle and the engine
    agree.

    Arelle has not completed the Bank's whole 61,428-fact PRA001 sample within
    ordinary memory, which is why that module is checked on a carve.

    The Bank's samples have one row in each table with a row per grade,
    securitisation or entity, and no type of specialised lending on OF 08.06. On
    them, a sum over every row and a sum over one row give the same count, so
    they cannot show which one the engine takes. Three more returns are built
    with several rows, for PRA001, PRA116 and MRL003, and Arelle's counts on them
    are kept beside the others. On those returns the engine and Arelle agree on
    every one of the 28 rules whose sums the workbook alone misreads.

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
uvx "rwa-filer[excel]@latest" template --module PRA001 --reference-date 2027-03-31 \
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

## The validation report and the evidence export

`--report FILE` (or `--format json`) writes the **validation report**: one JSON
document per return, small enough to keep with each run. `--evidence FILE`
writes the **evidence export**: everything the validation executed, for a system
that wants to rely on this engine's results rather than recompute them.

### The validation report

The report declares its shape (`"schema": {"name": "rwa-filer/validation-report", "version": "2.0"}`),
and its JSON Schema ships in the package:
`rwa_filer.schemas.load_schema(rwa_filer.schemas.VALIDATION_REPORT_SCHEMA)`.
Within a major version the report only gains fields. It holds:

- `identity`: what the verdict was computed from, each part by SHA-256. That is
  the facts and header (`facts_sha256`, independent of row order and file
  format), the source file's bytes, the taxonomy pack's files, the rule book
  (the packaged file, plus the Bank's workbook and formula-package digests it
  was built from), the accuracy in effect and whether it was the default, and
  the generator version. `evidence_id` is one digest over the inputs: two runs
  with the same `evidence_id` ran the same checks on the same figures. The
  source file is recorded but is not part of it, so the same facts as a `.xbrl`
  or a `.zip` share one id.
- `status`, `submittable` and `completeness`: the verdict, and each cause of an
  incomplete check with every rule and template it covers. The causes are
  `no_rulebook`, `rules_unsupported`, `rules_table_not_in_taxonomy`,
  `linked_templates_missing` and `coverage_shortfall`. A rule not run because it
  has no data, because the taxonomy's own formula cannot fire on the return, or
  because it reads only templates the return does not report, is not a gap: the
  gateway does not run it either.
- `rules`: **every** enforced rule, passes included, each with its status,
  evaluation counts, `rule_sha256` (a digest of everything that decides how the
  rule runs, so a changed formula under an unchanged code shows) and the first
  five failing evaluations with their cell coordinates.
- `findings`: every finding, each with `positions_total`, the number of facts
  it is about.

### The evidence export

The evidence is a JSON Lines file (`.jsonl`, or gzip-compressed `.jsonl.gz`),
one record per line. It is written from the same evaluation pass that reached
the verdict, so it cannot describe a different run:

| `record` | One per | Holds |
|----------|---------|-------|
| `header` | file | the schema (`rwa-filer/evidence` 1.0), the same `identity` as the report, the status and completeness, and how many records of each kind follow |
| `cell` | reported cell any evaluation read | its coordinates, data point, metric and type, its value, the `decimals` it was compared at, where that came from (`stated` by the fact, the run's `accuracy`, or `integer`), and its rounding allowance |
| `rule` | enforced rule | as in the report, plus the expression, scope, `where` and join |
| `evaluation` | evaluation, satisfied or not, uncapped | where it was made (`place`), whether it held, the cells each side read, and every comparison it executed |
| `finding` | finding | as in the report, with its index |
| `structure_exception` | fact a finding is about, uncapped | the finding's index and code, the fact's coordinates or source reference, its value, and what is wrong with it |
| `trailer` | file | the counts again, and `content_sha256` over every line before it |

Each comparison records its `operator`, whether it carries the `i` prefix
(`interval`), the branch of the rule it was in (`rule`, `rule/if`,
`rule/then`, ...), both operands (value, allowance, the cells read and the
cells read at their default), the `difference` (left − right), the `tolerance`
the prefix allowed, the `excess` beyond it and whether it held. The verdict
follows from the numbers: with `d` the difference and `t` the tolerance, `=`
holds when `|d| ≤ t`, `<=` when `d ≤ t`, `>=` when `d ≥ −t`, and so on; `t` is
both operands' allowances with the prefix and zero without it. A comparison
`and`/`or` never reached, or a branch not taken, is not recorded.

```python
import polars as pl

evaluations = pl.read_ndjson("evidence.jsonl").filter(pl.col("record") == "evaluation")
```

`rwa_filer.evidence.read_evidence(path)` reads a file back and refuses one that
is cut short or altered (the trailer's digest no longer matches). Without a
creation time (`--no-timestamp`) the same inputs give the same bytes. From
Python:

```python
from pathlib import Path

from rwa_filer.evidence import collect_evidence, write_evidence

evidence = collect_evidence(ret)  # validate_return's arguments
write_evidence(evidence, Path("evidence.jsonl.gz"))
print(evidence.validation.status, evidence.identity["evidence_id"])
```

`build --evidence FILE` writes the evidence whether or not the return is
written, and records its checksum and `evidence_id` in the manifest, so a
sign-off of the manifest covers the evidence too. The dashboard's overview
offers the same file as **Download evidence**.

## Writing the submission file

```bash
uvx rwa-filer@latest build return.parquet --out filing/ \
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
uvx rwa-filer@latest build return.parquet --out filing/ \
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
uvx rwa-filer@latest signoff filing/5493001KJTIIGC8Y1R12_PRA001_2027-03-31.manifest.json \
    --approver "C. Approver" --role "Head of Regulatory Reporting"
```

This writes `<name>.signoff.json`: who approved, in what capacity, when, and the
SHA-256 of the instance approved. A package the validation found not
submittable is signed only with `--acknowledge-findings`, and the record says
so.

```bash
uvx rwa-filer@latest verify filing/5493001KJTIIGC8Y1R12_PRA001_2027-03-31.manifest.json
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
uvx rwa-filer@latest diff filed.xbrl resubmission.xbrl
```

`diff` compares two versions of a return cell by cell and lists the cells
added, removed and changed, with the figures. Each side may be any file
`validate` reads, so a source table can be compared with the instance built
from it. The exit code is `0` when the two are identical and `1` otherwise.
`--format json` gives every change.

### Is this return the same as the one we file today?

```bash
uvx rwa-filer@latest compare current-system.xbrl rwa-filer.xbrl
```

`compare` is for proving a new way of producing a return against the old one,
during a parallel run, or a resubmission against the filing it replaces. The
first file is the **baseline**, the return already trusted. The second is the
**candidate**. Each may be any file `validate` reads, so the current system's
XBRL instance can be compared with rwa-filer's, or with a fact table.

`diff` answers "which cells differ". On two systems' returns that is usually
thousands of cells: one rounds to thousands, one files explicit zeros, one
does not file a template the other does. `compare` answers "what does a
reviewer have to explain". Every cell either return reports goes into one
category:

| Category | Meaning |
|---|---|
| the same | the same figure or text |
| rounding | within the accuracy both files state (`decimals`), plus `--tolerance` |
| zero or blank | a zero in one return, nothing in the other |
| scope | a template only one of the two reports |
| material | a difference to explain |

Then the material differences are grouped into **findings**, and each finding
says which side the Bank's own rules point at. Both returns are evaluated
against the packaged rule book, check by check. A check that holds in one file
and breaks in the other at the same place points at the file it breaks in.

| Finding | What it means | Points at |
|---|---|---|
| Differences that move together | Every rule linking the cells holds in both files, so neither is put together wrongly. The figures were calculated differently. Where a figure sits in another row (a 75% risk-weight row in one, 50% in the other), the move is named, and where the rows are rates the change it implies in the column applying them is checked. | the inputs |
| A cell that does not equal what a rule says it must | A total and its components disagree in one file only. The difference at the total is split into what the components explain and what is in the total alone, which is typical of an adjustment booked to a total. | that file |
| A column only one return reports | Points at the return that breaks a rule because of it, or at neither when no rule depends on it. | the file breaking a rule, or neither |
| Zeros where the Bank expects nothing | A zero is a reported figure, and some cells must not be reported on some sheets. | the file filing them |
| Rules that break in one file only | A one-sided break no other finding cites. Never dropped. | that file |

Every material cell is in exactly one finding. A fact the reader could not
place in the module, such as a member from an older template, is listed beside
the comparison, never dropped: the regulator's checks would not see it either.
Rules that break in both files are listed too: not a difference, but neither
return satisfies them.

The exit code is `0` only when the two are equivalent: the same header and
templates, nothing unplaced, no material difference, and no rule that breaks
in one file only. `--format json` gives the whole comparison, every finding and
every cell that is not the same. A fact table states no accuracy, so its
figures are compared exactly. `--tolerance 500` treats figures within 500 of
each other as the same.

!!! note "A finding says where to look, not who is right"
    Two returns that agree on every rule can still both be wrong. The
    comparison shows where they part and what the Bank's rules say about each
    side. Whether the figures are right rests on how they were calculated.

### Reading an XBRL file

`rwa-filer validate` accepts an `.xbrl` file, or a `.zip` holding one, written
by any system. Each fact is put back in the cell the taxonomy shows it in, and
the same structure checks and rules then run. The release must have the entry
point the file's own `schemaRef` names (see [Taxonomy releases](#taxonomy-releases)).

Three findings are specific to a file. All are Errors.

| Code | Meaning |
|------|---------|
| `XBR001` | A fact is not a data point of the module: no reportable cell has that metric with those dimension members. |
| `XBR002` | A fact appears only in templates the file does not declare as reported. |
| `XBR003` | The file breaks a Filing Manual rule the reader can see without loading the taxonomy: more than one entity or date, a `segment`, `precision` instead of `decimals`, a `nil` or empty fact, an unused context, an undefined unit, or one fact reported twice with different values. |

The reader does not load the taxonomy's own schemas, so it cannot say that a
file is valid XBRL against them. That is what the referee is for.

## The referee

`rwa-filer referee` gives a written file a second opinion. It runs
[Arelle](https://arelle.org), the reference open-source XBRL processor, on the
file against the Bank's published taxonomy package, and reports three things.

- Whether the file is valid: XBRL 2.1, the taxonomy's dimensions, and the
  filing rules.
- Arelle's verdict on every published rule the file's templates trigger.
- Where that verdict differs from this package's own, rule by rule.

```bash
uvx rwa-filer@latest referee 5493001KJTIIGC8Y1R12_PRA001_2027-03-31.xbrl \
    --taxonomy-package boe-banking-v411.zip \
    --arelle-python /opt/arelle/bin/python
```

```text
Referee: Arelle on 5493001KJTIIGC8Y1R12_PRA001_2027-03-31.xbrl — complete
  rules         356 evaluated (56 held, 2 broken, 298 never fired), 1085 skipped (template not filed), 0 lost
  messages      0 (0 at an error level)
Differential: the native engine beside Arelle
  compared      1441 rule(s): 1441 agree, 0 same verdict over a different count, 0 DISAGREE
Verdict: Arelle accepts the instance and the two engines agree on every rule compared.
```

The exit code is zero only when the run finished, Arelle raised nothing at an
error level, and the two engines agree. A rule that is broken is a finding
about the figures, not about the file, and does not change the exit code.
`--no-compare` reports Arelle alone. `--rules REGEX` runs a subset.

Arelle is optional and is never imported: it is run as a separate process.
Run the command with the `arelle` extra,
`uvx "rwa-filer[arelle]@latest" referee ...` (or `uv add "rwa-filer[arelle]"` in
a project), or keep Arelle in an environment of its own and name that
interpreter with `--arelle-python` or the `RWA_FILER_ARELLE_PYTHON` variable, as
the example above does. `uv tool install arelle-release` makes such an
environment; its interpreter is under the directory `uv tool dir` prints, at
`arelle-release/bin/python` (`arelle-release\Scripts\python.exe` on Windows).
The taxonomy package is the zip the Bank publishes; it is not redistributed with
`rwa-filer`.

A large module is slow and heavy. PRA001 is 741 MB of taxonomy XML, so the
referee trims the entry point to the rules the file can trigger and runs them
in several workers, each held to a memory limit. Expect a few minutes and about
3 GB for a credit-risk return. A worker that is killed, or that returns no
verdict for a rule, makes the run incomplete, and an incomplete run never
counts as agreement.

The referee changes Arelle's behaviour in two places, both measured on
arelle-release 2.47.5 and both stated in every result.

- It loads Arelle's math-functions plug-in. Two PRA001 rules call a logarithm
  function that is off by default, and without it Arelle evaluates none of the
  rules that share a session with them.
- It hands a match filter marked `matchAny` its single matched fact as a list of
  one. Without that, Arelle matches nothing, and twelve PRA001 rules that join
  two tables on a desk number are reported broken whatever is filed.

It also drops one filing-rule message, `EBA.3.1` ("only one currency"), which
Arelle raises on the Bank's own multi-currency MREL sample.

!!! warning "What agreement does and does not show"
    Arelle is not the Bank's gateway. Agreement shows that two independent
    readings of the published rules reach the same verdicts on this file. The
    regulator's own validation on upload remains the authority.

## Taxonomy packs

A taxonomy pack is the regulator's data point model for one reporting module,
compiled into three small files: which tables the module has, which cells of
each table are reportable, and which data point each cell reports. It ships
inside the package, so validation needs no network access.

```bash
uvx rwa-filer@latest taxonomy list
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

A run uses the pack of the release it uses (see
[Taxonomy releases](#taxonomy-releases)); the "applies from" dates say only
whether the module is live, future or superseded in that release. They are the
dates in each framework's taxonomy entry point, except for the two Basel 3.1
returns, which apply from 1 January 2027.

A pack is compiled from three files the Bank of England publishes: the annotated
templates, the DPM dictionary and the XBRL taxonomy package. The taxonomy is
authoritative for which cells are reportable. The compile is reproducible: the
same three files always give byte-identical output.

```bash
uvx "rwa-filer[excel]@latest" taxonomy compile --module PRA001 --valid-from 2027-01-01 \
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
| `VAL003` | Error | Coverage is insufficient: no rule could be executed at all, a reported template that has rules had none of them executed, or (`subject` `no_rulebook`, from `validate_return` only) no rule book covers the module. |
| `VAL004` | Warning | A template the return does not report is one that enforced rules check a reported template against, so those rules did not run. One finding per missing template; `subject` is its filing indicator. Raised by `validate_return` only. |
| `VAL005` | Warning | Enforced rules the engine could not evaluate: a rule that uses something it does not implement (`subject` `rules_unsupported`), or one that reads a table the taxonomy pack lacks (`rules_table_not_in_taxonomy`). They are neither passed nor failed, so the check is incomplete. Raised by `validate_return` only. |

`VAL003` is what makes an empty list safe to read as "checked and clean". Without
it, a return on which no rule could run would produce no breaks and look
identical to a clean one.

`VAL004` covers the return that holds only some of its templates. A rule runs
only when every template it reads is filed, at the Bank's gateway as here, so a
return holding OF 08.01 without OF 09.02 does not fail the 43 rules that read
both: they are switched off. The file is accepted with those checks unrun, and
the regulator receives it without OF 09.02's figures. Whether a firm must report
a template depends on its permissions and thresholds, which the rules do not
record, so this is a Warning, not an Error. A template the return declares not
filed (a negative filing indicator) is the return saying so, and is not named.
The JSON report lists the same templates under `summary.templates_missing`, each
with its rules and the reported templates they read.

`validate_return` adds the structure findings. All are Errors: the regulator
rejects a file that has any of them. Each names the first five facts in its
message; `Finding.positions` holds every one, uncapped, with what it holds and,
where it differs fact by fact, what is wrong with it. A fact an XBRL instance
holds that has no cell in the module is located by `source_ref` (its metric and
dimension members, or the context it is in) instead of coordinates. It also adds
`STR011`, a Warning about the release chosen, which is reported apart from the
structure findings (in `release_findings`) and never blocks.

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
| `STR011` | Warning. The return's reference date is outside the dates the chosen taxonomy release gives its module. The return is checked against that release; to file it, choose the release in force on its date. |

Each fact is reported once, against its root cause. A fact in an unknown table
is `STR001` only; it is not also reported as an unknown cell.

The report behind the findings has one result per enforced rule.

| Status | Meaning |
|--------|---------|
| `PASS` | The rule ran at least once and every run was satisfied. |
| `FAIL` | At least one run was unsatisfied. The result lists the first few, with the cells involved. |
| `NOT_EVALUATED` | The rule did not run. The reason is `template_not_reported` (a template it reads is not reported), `no_data` (none of its cells is reported), `closed_by_formula` (the taxonomy's own formula cannot match the cells the rule names, so the gateway does not run it either), or `unsupported`. |

No enforced rule of a supported module is `unsupported` today. That is held by a
test: a rule the engine cannot evaluate must be entered in a register by name,
and the register is empty.

## The `rwa-filer` command

```bash
# The dashboard in a browser, with a return opened in it (see the dashboard guide)
uvx rwa-filer@latest dash return.xbrl

# A return beside the one your current system produces, and why they differ
uvx rwa-filer@latest compare current-system.xbrl rwa-filer.xbrl

# The packaged Bank of England rule books: modules, rules, rules enforced
uvx rwa-filer@latest rulebook list

# Rebuild a rule book from one of the Bank's validation workbooks. With the
# taxonomy package it also records what each rule's formula fixes, and what
# each of its sums covers
uvx "rwa-filer[excel]@latest" rulebook import "Validations Banking Reporting v4.1.1.xlsx" \
    --out rulebooks/ --taxonomy-package boe-banking-v411.zip

# Fail if the packaged rule book is not exactly what the workbook yields.
# Without --taxonomy-package only the workbook content is compared
uvx "rwa-filer[excel]@latest" rulebook check "Validations Banking Reporting v4.1.1.xlsx" \
    --taxonomy-package boe-banking-v411.zip

# Have Arelle check a written file and compare its verdicts with this package's
uvx "rwa-filer[arelle]@latest" referee return.xbrl --taxonomy-package boe-banking-v411.zip

# The packaged rule extracts used by the template-level engine
uvx rwa-filer@latest rules list

# Rebuild an extract from a publisher's rule workbook
uvx "rwa-filer[excel]@latest" rules import --publisher boe rules.xlsx --out extract.json

# Fail if the packaged extract is not exactly what the workbook yields
uvx "rwa-filer[excel]@latest" rules check --publisher boe rules.xlsx
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

### Packaging a taxonomy release

The shipped releases are the ones `packages/rwa-filer/src/rwa_filer/releases.json`
lists; it is the one file edited by hand. To add a release:

1. Put the Bank's four downloads for it in `.taxonomy/boe-banking-<version>/` at the
   repository root (git-ignored): the taxonomy package, and the DPM, validations
   and sample-instances zips.
2. Add the release to `releases.json`, with an `applies_from` date for any module
   whose entry point does not state when it applies.
3. Run `uv run python scripts/build_filer_release.py <version>`. It compiles every
   module the Bank's annotated workbooks list, packages each only when the Bank's
   sample for it agrees (and reports the ones it refuses, with the reason),
   imports every rule book under the release's own version, regenerates the
   template-level extract for the newest release, sets end dates where a newer
   release changes a module's entry point, and writes the release's measurement
   file under `packages/rwa-filer/tests/releases/<version>/`.
4. Review the diff and release `rwa-filer`.

`--check` rebuilds a packaged release in a scratch folder and fails on any file
that differs: run against the Bank's 4.1.1 files, it reproduces the packaged
release byte for byte. `--measure-only` re-measures a packaged release without the
Bank's files. To retire a release, remove it from `releases.json` and rebuild the
newest one: its data is removed and recorded in `retired.json` with the last
`rwa-filer` version that shipped it. Tests hold the packaged data to
`releases.json` exactly, and to a 50 MB compressed size budget in place of a cap on
the number of releases.
