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

`@latest` has a cost: `uvx` asks PyPI for the newest release on every run,
which added about half a second to each command when it was measured (0.7-0.8 s
for `rwa-filer --version` against 0.24 s installed). That is most of the wait on
a small return, so for repeated, interactive use install the command with
`uv tool install` and upgrade it when a release is out.

Each `rwa-filer` command runs with Python's garbage collector switched off,
because nearly everything it builds lives until it exits; reading a workbook is
the exception, and is collected. `RWA_FILER_COLLECTOR=on` in the environment
keeps the collector on for a run. `rwa-filer dash` turns it back on before it
serves.

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

### Seeing how far a check has got

A typical PRA001 return validates in under a second, most of it start-up:
Python, Polars and loading the taxonomy pack. The published rules take a
fraction of a second there, and most of the time only on large returns: one
reporting 200 countries takes about one and a half seconds. `validate`, `build`
and `dash FILE` say on stderr which step they are on and how many rules are
done:

```text
Evaluating the published rules: 612 of 1,441 (42%) - 8s
```

In a terminal this is one line, rewritten as the work goes and cleared before
the result is printed. Anywhere else (a log, a CI job, a pipe) nothing is shown
unless asked for, so scripts that read stderr see what they always did.

| Option | Effect |
|--------|--------|
| `--progress` | Always show it. Outside a terminal, one line per step and per tenth of the rules, so a log reads top to bottom. |
| `--no-progress` | Never show it, even in a terminal. |

Progress never goes to stdout, so `--format json` piped into another program
is unaffected. The steps are reading the file, checking its structure,
evaluating the rules and, for `build`, writing the package. When the structure
check finds something, a line says so as soon as it returns, before the rules
run, naming how many findings there are and the first:

```text
Checking the structure against taxonomy 4.1.1: 11 finding(s); the first: [STR004] ERROR: ...
```

The findings themselves are in the report, as always; the line is only there so
that a return with a malformed file is not a wait for the whole rule run. Only the rules are
counted: the others are single steps, reported as they start. The count moves
unevenly, since a few rules that read whole templates take seconds each.

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

Nine things follow from that, and each changes verdicts.

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
  such figures allows for both. A figure stated to the penny contributes half a penny. An interval
  equality between two such figures accepts a one-penny difference, including
  the boundary. A point comparison has zero rounding allowance. The accuracy is the fact's `decimals`, or the default for its type.
  A total written `isum(...)` allows for every figure it adds. One written
  `sum(...)` allows for none of them: its formula uses XPath's own `sum`, whose
  result is a plain number, not a reported figure. The same is true of `abs`
  against `iabs`. In taxonomy 4.1.1 six enforced PRA001 rules compare a `sum`
  with rounding allowed (`boe_b0770`, `boe_b0820` to `boe_b0823` and
  `boe_b0829`), `boe_b0794` does the same with `abs` (in PRA001 and PRA116),
  and so does the SDDT rule `boe_b1037_ss` with `sum`. Figures rounded to
  thousands can break these rules where the sibling rules written with `isum`
  hold.
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
- **A sheet filed with no member is a sheet of its own.** OF 08.06 is filed
  once per type of specialised lending. Its axis also accepts the dimension's
  default, "all types", which a file reports by giving no type at all. Where a
  return files that sheet, each rule runs on it separately, like on any other
  sheet. Its figures are not added into any type's runs.
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

    Every figure in those returns is exact to the unit, where `sum` and `isum`
    allow the same, and none files an all-types OF 08.06 sheet. Four further
    returns cover both cases: two with figures rounded to thousands, for PRA001
    and PRA116, and two with an all-types OF 08.06 sheet beside two types, one
    where that sheet has its own category rows and one where it has only its
    total. Their Arelle counts are kept too, and the engine agrees with Arelle
    on every rule they were built for.

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

### A fact table with several rows per cell

A firm's figures rarely arrive one row per cell. They come from several
systems and business units, with journals on top. Give `validate` or `build`
the columns that say where each row came from, and the fact table is read as a
detail: the rows of a cell are added together, and the sum is the figure
validated and filed.

```csv
table,sheet,row,column,value,business_unit,source,line_id
OF07.00.01.01,0008,0070,0200,33090000,Asset Finance,LEASING-SYS,LS-00412
OF07.00.01.01,0008,0070,0200,12770000,Asset Finance,LEASING-SYS,LS-00413
OF07.00.01.01,0008,0070,0200,3500000,Commercial Banking,JNL-2027-0412,JN-0412-07
```

```bash
uvx rwa-filer@latest validate detail.csv --breakdown business_unit,source --line-ref line_id \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001
```

After the usual report, each broken rule is traced to the members that break it
on their own figures — the rule run again on each member's rows alone:

```text
Where the breaks come from, by business_unit: 18 of 18 broken evaluation(s) break on one business_unit's figures alone (6 member(s), 87 rule(s) run again).
  boe_b0471 (Error), 4 break(s)
    This represents the calculation of end exposure value post CRM post off-Balance sheet conversion factors
    Asset Finance breaks all 4, out by +6,000,000
  ...
Hold in the return, break on one business_unit's figures alone: 12 evaluation(s).
  boe_b0708 (Error), 4 place(s)
    Corporate & Institutional breaks all 4, out by +250,000
    Private Banking breaks all 4, out by -250,000
```

The second list is what a total hides: a rule the return meets that a member's
own figures break, usually two figures wrong in opposite directions. Only rules
over amounts are searched. `--format json` and `--report` carry the same under
`breakdown`; the dashboard's Investigate page lays it out
([The dashboard](dash.md)).

#### When the file already contains the group return

Give the reporting-unit column and its group code to either `validate` or `build`.
For a file with `Group`, `Retail` and `Commercial` in `reporting_unit`, run:

```bash
rwa-filer validate detail.csv --breakdown reporting_unit --group-code Group \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001
```

Only the group rows supply the return, including its comments, percentages, zeros and
absent cells. A repeated group fact goes through the usual duplicate-fact check.
Specify one breakdown column in this mode. The group code matches case-sensitively
after trimming spaces. An unknown code stops the load.

The other codes identify units. Each can report its own text, dates, percentages
and row identifiers for the same cell. Monetary lines within a unit are added.
Line-reference checks apply within each unit. Blank unit codes appear as their own
member. Open rows are compared by the taxonomy's row keys.

The report traces failed group rules to the units. Where a unit lacks an input the
group evaluation read, the dashboard shows **Insufficient detail**. For additive
monetary comparisons, any difference between the group gap and the assessed unit
gaps is shown as unexplained. The JSON report includes group and unit text under
`breakdown.text_cells`. On the dashboard use **Open a return → Reporting unit breakdown → Load
choices from file** to select the column and group, then **Investigate** to review
the unit results or read the text.

#### When the detail supplies the return

- **Breakdown columns** are matched ignoring case and surrounding spaces. A row
  that leaves one empty is a member of its own, named `no <column>`. A fact
  column (`table`, `row`, ...) cannot be one.
- **Only amounts are added.** Several rows for a cell whose data type is not
  monetary — a percentage, a count, a date, an enumeration, text — stop the
  file and name the cells. Give such a cell one row.
- **A line reference** (`--line-ref`) is the identifier each line has in its own
  system: a loan, a lease, a journal line. One loan feeds many cells, so a
  reference appears once in each cell it feeds. The same reference twice in one
  cell is the same line counted twice, and stops the file, naming the cells and
  the file's lines. With `--on-repeat keep-one`, a repeat that agrees with the
  earlier row on everything is dropped instead (the count is reported), and one
  that differs still stops the file. The check matters because no published
  rule catches a whole extract loaded twice: every total doubles with its parts.
- **Without a line reference** every row counts: two rows that agree on
  everything are two amounts, and both are added.
- **Asked for nothing**, a fact table is read exactly as before: one row per
  cell, and a cell given twice is structure finding `STR005`.

Breakdown columns are read from a fact table (`.parquet` or `.csv`) only. A
workbook or an XBRL instance carries only the summed figures. `build` takes the
same options, and the manifest records the detail file, its columns and how
many rows made the return under `detail`; a manifest built without one has no
`detail` entry.

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

To follow a long validation, pass `progress=`: a callable that receives a
`rwa_filer.progress.Progress` for each step, and for each rule as it is
evaluated. `validate_return`, `collect_evidence`, `build_filing` and
`open_source` all take it. It is called on the thread doing the work, so keep it
quick:

```python
from rwa_filer.progress import Progress

def show(event: Progress) -> None:
    print(event.describe())  # "Evaluating the published rules: 612 of 1,441 (42%)"

result = validate_return(ret, progress=show)
```

`rwa_filer.progress.StreamProgress(sys.stderr, live=True)` is the printer the
command line uses, and can be passed as `progress=` directly.

## Rules the Bank has switched off: the validations deny list

After a taxonomy is published, the Bank of England keeps a **validations deny
list**: the rules its gateway no longer runs, or now runs as warnings. Its
words, from the workbook's Note sheet:

> These validation execution amendments are applied post-taxonomy publication
> and therefore override the information provided in the relevant taxonomy and
> the taxonomy validations spreadsheet. Validation logic and scope will never be
> altered in this document, only their execution configuration (severity).

A rule can be on it in one of two ways.

- **Deactivated.** "The rule will not be executed in the data collection system
  and reporters are not expected to meet the requirements of this rule."
- **Downgraded to Warning.** An Error the gateway now treats as a Warning:
  "submissions that fail this rule will be accepted in the system."

`rwa-filer` ships the list for each taxonomy release, beside its rule books,
and applies it to every validation. For taxonomy 4.1.1 the Bank's November 2026
list has these entries. Each one links to the known-issues log entry that
explains it.

| Module | Rules | What the Bank did | Applied | Known issue |
|---|---|---|---|---|
| PRA001 | `boe_b0710`, `boe_b0710_1`, `boe_b0710_2`, `boe_b0710_3` | deactivated | 19 October 2026 | #22 |
| PRA001 | `boe_b0746` | deactivated | 19 October 2026 | #26 |
| PRA001 | `boe_b0272` | deactivated | 16 November 2026 | #29 |
| PRA001 | `boe_b0274` | deactivated | 16 November 2026 | #30 |
| PRA116 | `boe_b0063_ss`, `boe_b0063-1_ss`, `boe_b0063-2_ss` | deactivated | 19 October 2026 | #21 |
| PRA115 | `boe_b1014`, `boe_b1022` | deactivated | 14 May 2026 | #15 |
| MRL001 | `boe_b4006_1`, `boe_b4006_2` | downgraded to Warning | 19 October 2026 | #23 |
| MRL001 | `boe_b4008_1`, `boe_b4008_2` | downgraded to Warning | 19 October 2026 | #24 |

`rwa-filer rulebook deny-list` prints the packaged list, and says which entries
are in force on a date (`--on`).

**What changes in a validation.** A deactivated rule is reported as not
evaluated, with the reason `deactivated_by_publisher`. It is not a finding, and
it is not a gap that makes the check incomplete, because the gateway would not
run it however complete the check was. A downgraded rule that breaks is a
`VAL002` warning, which does not block. Its message says the Bank downgraded it.
The text report gives one line for each rule on the list, with the date, the
known-issue number, and what the published rule finds on the return.

**Which date decides.** The list is the gateway's configuration on the day a
return is submitted. It says nothing about the return itself. So an entry
applies from its "Date Applied" on the run date, never on the return's reference
date. The release a run uses is chosen by the run date for the same reason. For
a return that will be submitted later, `--submission-date` (on `validate`,
`build` and `compare`, and `submission_date=` in Python) names the day. An entry with no date
has been identified by the Bank but not yet applied: it is listed as pending,
and never applied.

**What does not change.**

- **The rule.** Its expression, its scope and its `rule_sha256` are the
  taxonomy's. The list changes how a rule is run, not what it checks. Each rule
  record says which entry applied (`deny_list`). Where the entry changed the
  outcome, the record also gives the published rule's own verdict (`formula`).
- **The referee comparison.** Arelle runs the taxonomy's formulas, and those
  still contain every rule on the list. The referee therefore compares Arelle's
  verdict with the published rule's verdict, not with the configured one, and
  says what the Bank did beside the comparison.
- **The evidence export.** It holds no evaluations of a deactivated rule,
  because nothing that rule found is behind the verdict. The rule's own record
  keeps the counts of the published rule.
- **The template-level engine.** It reads the same packaged list: a deactivated
  rule is not enforced and a downgraded one is a warning. The DPM variant
  columns are still derived from the published rules, because the list never
  changes a rule's scope.

**Where it comes from.** The packaged file is
`rwa_filer/boe/data/deny/<release>.json`. It is imported from the Bank's workbook
(`boe-banking-validations-deny-list-<month>-<year>.xlsx`, published on the
Bank's banking reporting page beside the known-issues log) and joined to the
log for the issue numbers. It is never edited by hand.

- `rwa-filer rulebook deny-list import WORKBOOK --release 4.1.1 --known-issues LOG --out DIR`
  builds it.
- `... check` fails when the packaged file is not exactly what the workbook gives.

Every code the workbook lists is matched to a rule of its module in that
release, and a code that matches none is reported and kept under `unmatched`.
One kind of typo is resolved, by a fixed rule. The Bank's rule numbers have four
digits, so a longer number with extra leading zeros is read as the four-digit
code, but only when the code as written names no rule and the four-digit code
does. The November 2026 list writes `boe_b04006_1` and `boe_b04006_2`. MRL001's
rules are `boe_b4006_1` and `boe_b4006_2`, as known issue #23 names them. The
entry keeps the Bank's spelling as `published_code`.

## Known issues with the published rules

Some published rules are wrong: a return that follows the reporting
instructions fails them, they pass figures the rules do not permit, or they
never run. `rwa-filer` ships, for each taxonomy release, a **register** of the
ones it knows about, with the evidence for each, and labels every result one of
them explains. **The verdict never changes:** a rule that breaks still breaks,
with the same severity, code and figures, and a return it blocks is still
blocked. Only the words beside the result change, so the reader knows the break
is the published rule's, not the return's.

```bash
# Every known issue of every shipped release, one per line
uvx rwa-filer@latest rulebook issues

# One issue in full: the rule, the instructions quoted with their page, why a
# correct return fails, the smallest correct return, the proposed fix
uvx rwa-filer@latest rulebook issues PI-05

# The register as the write-up to share with the Bank (Markdown), or as JSON
uvx rwa-filer@latest rulebook issues --format markdown > known-issues.md
uvx rwa-filer@latest rulebook issues --format json --module PRA001
```

**What an issue says.** Each has an id (`PI-05`), a kind, a title, the rules it
names (each pinned by its `rule_sha256`, so an issue never labels a changed rule
that kept its code), the instructions and rules it rests on, quoted with the
page of the PDF, why a correct return fails (or, for a question, what is open),
a worked example, what the Bank could change, EBA precedent, reach, and what a
firm can do meanwhile. Its **kind** says how sure the case is:

| Kind | Meaning |
|---|---|
| `defect` | the published rule is wrong: a return that follows the instructions breaks it, passes figures it should not, or it never runs |
| `clarification` | an open question with the published rule: the instructions can be read so that a correct return breaks it, and the Bank is asked which reading it intends. Its label says "Open question", and says the break "may be" the rule's, never that it is |
| `acknowledged` | the Bank's own known-issues log records it; the log's entry is quoted word for word |

Its **status** says where it stands with the Bank:

| Status | Meaning |
|---|---|
| `draft` | identified by rwa-filer, not yet raised with the Bank of England |
| `raised` | raised with the Bank, on the date given |
| `acknowledged` | in the Bank's own known-issues log (the entry is quoted) |
| `fixed` | fixed by the Bank in a later taxonomy release |

A rule the Bank has **deactivated** at its gateway is told by the deny list
above, not by a label: it is not run, so there is no break to label.

**Which results are labelled.** An issue's *effect* decides:

- a rule that **fails correct returns** labels a FAIL;
- a rule that **passes wrong returns** labels a PASS ("this pass is no evidence
  ...");
- a rule that **never runs** labels the rule not evaluated because its formula
  cannot fire or nothing it reads is reported;
- an issue in the instructions or the taxonomy alone labels nothing; it is in
  the register and the write-up only.

**Where a break is explained.** An issue may apply to part of a rule only - a
column, some rows, some sheets (its *footprint*). Every unsatisfied evaluation,
not only the five a result keeps, is classed inside or outside it: "4 of 14
unsatisfied evaluation(s) are where the published rule is known to be wrong; 10
are not, and are not explained by it". A break outside every footprint is a
break in the return, and the label says so. Where an issue cannot tell its own
break from one in the return, the label says the break "may be" the issue.

**Where the label appears.**

- The finding's message gains one sentence per issue, and the finding names the
  issues (`publisher_issues`).
- The text report adds a line per labelled result after the counts; the verdict
  line is unchanged.
- The JSON report: each rule's `publisher_issues`, each finding's
  `publisher_issues`, `summary.publisher_issues` (by issue, with the breaks
  inside and outside), and `identity.publisher_issues` (the register's file and
  SHA-256 - outside `evidence_id`, because a label is not a check).
- The evidence export: each rule record's labels, and on each unsatisfied
  evaluation of a labelled break the issues whose footprint holds it (`[]` when
  none does).
- The dashboard: a "Known issue" chip ("Open question" for a clarification) on
  the rules list, the overview and the module reference page; a callout in the
  rule detail and in the cell panel.
- The filing manifest, which copies the report's findings and summary.

There is no separate exit code: `validate`'s exit code is the verdict's. A
script that must tell "blocked only by breaks a known issue explains" from the
rest reads `summary.publisher_issues` (or `ReturnValidation.publisher_issues`
in Python).

**Where it comes from, and what holds it to the evidence.** The register is
`rwa_filer/boe/data/issues/<release>.json` (schema
`schemas/publisher-issues-1.schema.json`), curated by hand from findings, never
imported. The package's tests hold it to the release: every rule it names is a
rule of that module at that fingerprint and severity, every footprint names
cells of the module's pack, and each status agrees with its fields. Each
issue's worked example was run once through Arelle against the Bank's taxonomy
package, and CI holds the engine to Arelle's counts and the issue to its claim -
a defect's rules at issue unsatisfied on it, a clarification's the outcome it
states, and every rule the write-up calls a control holding on it - so a release
in which the Bank fixes a rule fails until the issue is closed. No issue names a
data point by rwa-filer's own pack index, which the Bank's DPM does not know. In
the repository,
`tests/contracts/test_publisher_issue_quotes.py` checks every quote is on its
page of the PDF. The write-up is generated as
[`publisher-issues.md`](publisher-issues.md) by
`scripts/generate_publisher_issues.py`, grouped as defects, clarification
questions and issues the Bank has already acknowledged; it stays out of the site
navigation until it is signed off.

## The validation report and the evidence export

`--report FILE` (or `--format json`) writes the **validation report**: one JSON
document per return, small enough to keep with each run. `--evidence FILE`
writes the **evidence export**: everything the validation executed, for a system
that wants to rely on this engine's results rather than recompute them.

### The validation report

The report declares its shape (`"schema": {"name": "rwa-filer/validation-report", "version": "2.1"}`),
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
  or a `.zip` share one id. `deny_list` records the validations deny list
  applied: its file, the date, and the entries in force for the module. Only
  the entries in force count towards `evidence_id`, so a run on another day
  has the same id unless the gateway changed in between.
- `status`, `submittable` and `completeness`: the verdict, and each cause of an
  incomplete check with every rule and template it covers. The causes are
  `no_rulebook`, `rules_unsupported`, `rules_table_not_in_taxonomy`,
  `linked_templates_missing` and `coverage_shortfall`. Some rules that are not
  run are not gaps, because the gateway does not run them either: a rule with
  no data, a rule the taxonomy's own formula cannot fire on the return, a rule
  the Bank has deactivated, and a rule that reads only templates the return does
  not report.
- `rules`: **every** enforced rule, passes included, each with its status,
  evaluation counts, `rule_sha256` (a digest of everything that decides how the
  rule runs, so a changed formula under an unchanged code shows) and the first
  five failing evaluations with their cell coordinates. Since 2.1 each rule
  also has `deny_list`, the Bank's entry for it or null, and `formula`, the
  published rule's verdict where that entry changed the outcome, or null.
  `summary.deny_list` lists what the list deactivated, what it downgraded and
  what it did not apply. Each rule also has `publisher_issues`: the labels known
  issues with the published rule put on it (see above).
- `findings`: every finding, each with `positions_total`, the number of facts
  it is about, and `publisher_issues`, the known issues that label it.

### The evidence export

The evidence is a JSON Lines file (`.jsonl`, or gzip-compressed `.jsonl.gz`),
one record per line. It is written from the same evaluation pass that reached
the verdict, so it cannot describe a different run:

| `record` | One per | Holds |
|----------|---------|-------|
| `header` | file | the schema (`rwa-filer/evidence` 1.1), the same `identity` as the report, the status and completeness, and how many records of each kind follow |
| `cell` | reported cell any evaluation read | its coordinates, data point, metric and type, its value, the `decimals` it was compared at, where that came from (`stated` by the fact, the run's `accuracy`, or `integer`), and its rounding allowance |
| `rule` | enforced rule | as in the report (`deny_list` and `formula` included, since 1.1), plus the expression, scope, `where` and join |
| `evaluation` | evaluation, satisfied or not, uncapped | where it was made (`place`), whether it held, the cells each side read, and every comparison it executed. A rule the Bank has deactivated has none: its published rule's counts are on its `rule` record, under `formula` |
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
offers the same file as **Download evidence**: it is collected once for each
validation of the return and served from then on, so a second click is
immediate and two clicks at once get the same whole file. Each validation's file
is kept in the dashboard's session folder until the dashboard stops.

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
| `--progress` / `--no-progress` | Show, or never show, how far the build has got on stderr (see [Seeing how far a check has got](#seeing-how-far-a-check-has-got)). Shown by default in a terminal. |

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

Both returns are judged by the rules as the Bank's gateway runs them on the
submission date, as `validate` judges one (`--submission-date`, default
today). A rule the validations deny list switches off that day points at
neither return. If its published formula breaks in either, it is listed as
switched off, so the comparison never hides it. A rule the list downgrades to a
warning still runs at the gateway, and is compared like any other.

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
in several workers, each held to a memory limit (`--max-rss-gb`, default 9 GB).
Expect a few minutes and up to 3.9 GB per worker for a credit-risk return.
Workers run as many at once as fit in the memory available at that limit (or
under a container's memory limit, where that is less), one per CPU at most;
`--jobs N` sets the number. Ctrl-C or SIGTERM kills the running workers. A
worker that is killed, or that returns no verdict for a rule, makes the run
incomplete, and an incomplete run never counts as agreement.

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
each one, and uses one tolerance for a whole rule. It also reads a Bank rule's
default value (`dv`) once for the whole rule rather than per reference, refuses
67 of the 800 Bank rules in force on their grammar (`isNull`, `if`/`then`,
`and`/`or`, dimensional filters other than the all-geographies total), and
cannot see that one data point is shown in two tables. `validate_return` does
not use it.

Like the gateway, it does not break a rule at a place where none of the cells
the rule reads is reported, unless the rule is marked "always execute" (35 of
the Bank's 816 rules, and none of the EBA's): a failing comparison there is not
evaluated, with the reason `nothing_reported`. A reported zero is a fact and is
evaluated. A comparison over unreported cells that holds is still counted as
vacuous, so a template cell nothing ever fills stays visible.

This holds for the CRR (EBA) rules too. XBRL Variables 1.0, section 4, says: "If
a variable set contains fact variables but all of the fact variables in it
evaluate to fallback values, then the variable set is not deemed to have been
evaluated." An EBA "treat as zero" rule is such a variable set, each cell
falling back to 0. The Bank's own package restates 46 of those rules under the
EBA's ids, 45 with a default on every reference and none marked "always
execute". Arelle runs one of them, `v09779_m` (the C 08.04 flow total), on a
filed C 08.04 and counts no evaluation where no cell is reported, but one where
a single cell is reported as 0. So `v09796_m`
(`{c0030} + {c0040} + {c0050} = 1` on C 08.07) is not broken on a roll-out
class that has no exposure and reports no share.

It honours the Bank's validations deny list, from the same packaged file, as it
stands on the day the rules are loaded (`load_rules(framework, on=...)`,
defaulting to today). A deactivated rule is not in `RuleSet.enforced`, and a
downgraded one has `severity` Warning. `RuleSet.published_in_force` is the
extract's own population, before the list.

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
| `STR012` | A monetary fact states fewer decimals than the module permits, either in its own accuracy or in the run default. The affected cells block filing, including a forced build. |

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

# A fact table of several rows per cell: summed, then each break traced to the
# business units and sources that make it
uvx rwa-filer@latest validate detail.csv --breakdown business_unit,source --line-ref line_id \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# A return beside the one your current system produces, and why they differ
uvx rwa-filer@latest compare current-system.xbrl rwa-filer.xbrl

# The packaged Bank of England rule books: modules, rules, rules enforced, and
# how many the Bank's validations deny list switches off or downgrades today
uvx rwa-filer@latest rulebook list

# The Bank's validations deny list, entry by entry, as it stands on a date
uvx rwa-filer@latest rulebook deny-list --module PRA001 --on 2027-03-31

# The known issues with the published rules: every one, one in full, or the
# register as the write-up to share
uvx rwa-filer@latest rulebook issues
uvx rwa-filer@latest rulebook issues PI-05
uvx rwa-filer@latest rulebook issues --format markdown

# Rebuild a release's deny list from the Bank's workbook, joined to the
# known-issues log; or fail if the packaged one is not what it yields. Without
# --known-issues, check compares every entry but not the known-issue numbers
uvx "rwa-filer[excel]@latest" rulebook deny-list import deny-list.xlsx --release 4.1.1 \
    --known-issues known-issues.xlsx --out deny/
uvx "rwa-filer[excel]@latest" rulebook deny-list check deny-list.xlsx --release 4.1.1 \
    --known-issues known-issues.xlsx

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
4. Import the Bank's validations deny list for the release:
   `uv run python scripts/build_filer_release.py <version> --deny-list`. It reads
   the newest deny list and known-issues log in `docs/assets/` (git-ignored;
   `uv run python scripts/download_docs.py` fetches them) and writes
   `boe/data/deny/<version>.json`. Every code it cannot match to a rule is
   printed. A release cannot ship without one. Re-run it whenever the Bank
   publishes a new list, and `--deny-list --check` fails when the packaged file
   is out of date. Rebuilding a release leaves its deny list alone, and retiring
   a release removes it.
5. Review the diff and release `rwa-filer`.

`--check` rebuilds a packaged release in a scratch folder and fails on any file
that differs: run against the Bank's 4.1.1 files, it reproduces the packaged
release byte for byte. `--measure-only` re-measures a packaged release without the
Bank's files. To retire a release, remove it from `releases.json` and rebuild the
newest one: its data is removed and recorded in `retired.json` with the last
`rwa-filer` version that shipped it. Tests hold the packaged data to
`releases.json` exactly, and to a 50 MB compressed size budget in place of a cap on
the number of releases.
