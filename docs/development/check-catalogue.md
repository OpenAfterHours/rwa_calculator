# Check Catalogue

The check catalogue is an Excel workbook listing every check the calculator runs, and the
evidence behind them. It is written for a reviewer who needs to see exactly what is checked:
a risk or finance team, model validation, internal audit, or the person signing a return.

It is **generated from the code** each time you run the script, so it describes what the
code does at that commit. Nothing in it is typed by hand. When a check is added, removed or
wired into a new place, re-running the script updates the workbook.

```bash
uv run python scripts/export_check_catalogue.py
```

The workbook is written to `dist/check-catalogue.xlsx`. That path is fixed and git-ignored:
`arch_check` check 19 bans `scripts/` from building a file path out of a command-line
argument. To write somewhere else, import the function and pass a path:

```python
from pathlib import Path

from scripts.export_check_catalogue import build_catalogue, export_check_catalogue

export_check_catalogue(build_catalogue(), Path("review/check-catalogue.xlsx"))
```

## What is in it

The first sheet, **Read me**, records where the workbook came from: when it was generated,
the git commit (marked if the tree had uncommitted changes), the `rwa-calc` and `rwa-filer`
versions, and the content hash of each regime's rulepack. It also has a guide to the other
sheets and the banked coverage measures described [below](#coverage-measures).

Every other sheet opens with three lines: what one row is, where the family runs, and the
file it was read from. Below them is a table with a filter and frozen headings.

### Checks that run on your data

| Sheet | One row per | Read from |
|---|---|---|
| **Error codes** | Error or warning code the calculator declares | Code constants under `src/rwa_calc`, chiefly `contracts/errors.py` |
| **Input columns** | Column of every input table: type, required or optional, the accepted domain and the code a bad value raises | `data/schemas.py` (`TABLE_SCHEMAS`, `COLUMN_VALUE_CONSTRAINTS`) |
| **Template rules - CRR** | Published EBA validation rule in the CRR credit-risk extract | `rwa_filer/rules/data/` |
| **Template rules - Basel 3.1** | Published BoE validation rule in the Basel 3.1 credit-risk extract | `rwa_filer/rules/data/` |
| **Filing rules - PRA001** | Rule the Bank's gateway runs on a PRA001 return | `rwa_filer/boe/data/` |
| **Tie-outs** | In-house identity between two generated templates, plus each template pair recorded as not comparable, with the reason | `reporting/tieouts.py` |

### Evidence from the test suite

These sheets don't run on your data. They are the evidence that the calculator computes the
right numbers, and they run in CI.

| Sheet | One row per | Read from |
|---|---|---|
| **Oracle cases** | Case hand-derived from the regulation by a calculator that may not import the engine. Parked disagreements are marked | `tests/oracle/` |
| **Classification table** | Rule, exclusion or parked disagreement in the exposure-class and approach decision table | `tests/conformance/classification_table.toml` |
| **Cell re-derivations** | Template money cell rebuilt from the published instructions by a separately written rule | `tests/conformance/cell_rederivation.toml` |
| **Invariant tests** | Property that must hold for any portfolio: conservation, monotonicity, homogeneity, output-floor identities, structural bounds | `tests/properties/` |
| **Article coverage** | Regulatory article, with how many places each evidence layer cites it | `tests/contracts/data/confidence_snapshot.json` (the [Confidence & Evidence Matrix](confidence-matrix.md)) |
| **Test inventory** | Test function in `tests/` and `packages/rwa-filer/tests/`, with its docstring summary and markers | The test files |

## How the code-derived columns work

A few columns state something about the code instead of copying a value. Each is worked out
when the workbook is generated, so it changes when the code does.

**Where it runs.** For each runtime family, the script finds every call of the family's
entry point in `src/rwa_calc` and names the calling module and function. If nothing calls
it, the sheet reads "No production call site": the family is defined and tested, but no
calculation runs it. Once something calls it, the sheet names the caller instead.

**Raised in** (Error codes). Each code gets one of four outcomes:

| Outcome | Meaning |
|---|---|
| `Raised in <modules>` | A `CalculationError(...)` call, or a factory helper such as `crm_warning(code, ...)`, passes this code |
| `Raised through a code mapping in <modules>` | A module raises a code it looks up at run time, from a mapping or a spec table, and that module names this code |
| `Not raised: no raise site found; referenced only as listed` | The code is named somewhere, for example in the API's user-message table, but nothing raises it |
| `Not raised: declared, with no other reference` | Nothing outside the declaration mentions the code |

**Severity and Category** (Error codes) come from raise sites that state them literally
(`ErrorSeverity.WARNING`). A blank means the site sets them at run time, not that the code
has none.

**Code if outside the domain** (Input columns) comes from the input gate's own mapping in
`contracts/validation.py`. The script imports that mapping instead of restating it.

## Coverage measures

The **Read me** sheet carries the measures already banked by the project's ratchets. Each
value is read from the file that banks it, and that file is named next to the value:

- how many published rules reach a pass or fail on at least one test portfolio run, and how
  many are never evaluated (`scripts/coverage_baseline.json`);
- how many template cells any test portfolio populates, and how many none does;
- how much of the generated Basel 3.1 return has a place in the PRA001 taxonomy, and the
  error-severity rule breaks on the golden returns (`scripts/filing_mapping_baseline.json`);
- the Arelle referee result (`scripts/referee_differential_baseline.json`);
- the number of oracle cases and parked disagreements;
- whether a defect-injection detection rate has been measured
  (`scripts/injection_baseline.json`).

Read these before relying on the rest. A check that no test portfolio reaches has no
evidence behind it, and a cell no portfolio populates has never been tested.

## What it does not tell you

- **What the checks found on your return.** The workbook lists what is checked, not the
  outcome. For outcomes on your own data, run `ResultExporter.validate_submission` and
  `export_validation_report`.
- **That each check is right.** A listed check is a statement of what the code does. The
  test-suite sheets and the coverage measures are the evidence for correctness, and they show
  how far it goes.

## Keeping it honest

`tests/contracts/test_check_catalogue.py` holds each sheet to its source of truth. It doesn't
reuse the script's own logic to do so:

- each sheet's population is compared with the loaded rule sets, schemas, registers and
  TOML tables;
- the "not raised" and "no production call site" statements are checked against a
  tokenised text search of `src/rwa_calc`, which never touches the AST walk the script uses;
- the written workbook is read back to confirm that identifiers such as row `0010` stay text.

Each of those tests was observed to fail under a deliberately injected defect before it was
accepted.
