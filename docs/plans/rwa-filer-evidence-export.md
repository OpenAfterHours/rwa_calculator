# rwa-filer evidence export: a complete, versioned record of what validation executed

**Status:** Implemented 2026-11-15 in rwa-filer, for release as 0.2.0. See
[Outcome](#outcome-what-landed) at the end for what landed and where it differs
from the design below. Every measurement in the diagnosis was taken on
`rwa-filer` 0.1.2 at `22b43d1` (master, 2026-11-15) in an environment holding the
member alone (`uv sync --package rwa-filer`), and is reproducible with the
commands in the appendix.

**Origin:** user feedback on 0.1.2. Their summary: the validation engine already
provides most of what they need, and they would rather reuse its evidence than
build a second calculation engine. What is missing is a **complete, stable
evidence export**. They asked for five things, plus one CLI fix:

1. A detailed JSON report with **every** rule outcome, including passes.
2. **Uncapped**, structured exceptions for both structure checks and rule checks.
3. **Structured calculation evidence**: operands, comparison operator, signed
   difference, effective decimals, rounding allowances, and reported versus
   defaulted cells.
4. **Versioned evidence identity**: report schema, taxonomy pack, rule book and
   input fingerprints, plus the accuracy settings in effect.
5. An **explicit incomplete status**, so missing rule books, unsupported rules and
   missing required inputs can be told apart from a clean result.
6. `rwa-filer validate` should take the same accuracy options as `build`.

## The finding in one sentence

The engine already works out almost all of this while it evaluates. It holds both
operands of every comparison with their rounding allowances, knows where each
fact's `decimals` came from, and visits every evaluation in a deterministic order.
The gaps sit in the **two serialisation layers**, `validate/report.py::to_record`
and `boe/engine.py::_traced`, plus **one hole in the verdict**. So this is a
capture-and-export project, not new arithmetic.

## What 0.1.2 does today, measured

A synthetic PRA001 return (132 facts in C 01.00 and C 03.00, including 7 facts in
cells the taxonomy does not accept) was run through the real CLI:
`rwa-filer validate … --report report.json`.

| Ask | Today | Where |
|---|---|---|
| 1. Every rule outcome | **Passing rules are left out.** The report lists 1,420 of 1,441 enforced rules: the 21 that passed are missing, so the JSON cannot show the full set of rules that ran. | `to_record` filters `result.status != STATUS_PASS` |
| 2. Uncapped rule exceptions | `v3685_s` fails in **47 of 52** evaluations, but only **5** are kept. Each kept failure is a sentence, and summed references are cut short (`r0070;0080;0090;..`, with only a total). | `MAX_FAILURES = 5`, `MAX_ADDRESSES = 64`, `cells[:8]` in `boe/engine.py` |
| 2. Rule exception coordinates | `Failure.addresses` (structured `CellAddress` values) is **computed and then thrown away**: `to_record` writes only `place` and `cells`. | `validate/report.py` |
| 2. Uncapped structure exceptions | STR002 reports "7 fact(s)… (first 5 of 7)". The positions exist **only inside the message text**, and `actual` is just `"7 fact(s)"`. `Finding` has no field for positions. | `MAX_EXAMPLES = 5` in `validate/structure.py` and `xbrl/reader.py` |
| 3. Calculation evidence | `trace_rules` keeps every evaluation, but only `relation`, `left_value` and `right_value`. It **drops the `i` (interval) prefix and the allowances**, and keeps no per-cell values, decimals or default values. | `Evaluation` / `_traced` in `boe/engine.py` |
| 4. Evidence identity | No fingerprint of any kind in the report. It has the `generator` version and taxonomy module/version/entry point, and nothing on the input, pack or rule book, or the accuracy used. | `to_record` |
| 5. Incomplete status | `submittable` is the only verdict, and it is a yes/no. See the next section. | `validate/returns.py` |
| 6. Accuracy on `validate` | `validate_return(accuracy=…)` exists, but the `validate` command never passes it. `build` does (`--monetary-decimals`, `--percentage-decimals`). | `cli.py::_validate` vs `filing.py::build_filing` |

### Four findings that shape the design

**F1 — `validate` and `build` disagree on an Error-severity rule for the same
return.** Rule `v0174_m` checks `C 01.00 r0070 i= r0080 i+ r0090 i+ r0091`. On the
synthetic return that is 9,000 against 0 + 8,000 + 3,000 = 11,000, a difference of
−2,000. With `validate`'s default accuracy (−3: each fact has an allowance of 500),
the allowance is 4 × 500 = 2,000, so the rule holds and passes. Built with
`--monetary-decimals 0`, the file states each fact to the unit, the allowance
becomes 4 × 0.5 = 2, and the rule fails. It is Error severity, so it blocks
submission. Measured: status counts go from 21 PASS / 22 FAIL at −3 to 20 PASS /
23 FAIL at 0 or 2, and `v0174_m` is the only rule that changes. `build` is
consistent with itself, but `validate` cannot be made to agree with it. The same
example shows why ask 3 matters: anyone reading the current trace sees
`= 9000.0 11000.0` and concludes the rule broke.

**F2 — A missing rule book is reported as clean.** When `rulebook_for_module`
raises, `validate_return` logs a WARNING and returns `report=None, rules=()`, so
`is_submittable` is `True` whenever the structure checks are clean. The module's
own docstring says "Never let an empty finding list stand for 'clean' when little
or nothing was checked", and VAL003 exists to enforce that, but this path skips
VAL003 entirely. It is also the log-line-as-gate trap (`.claude/LESSONS.md` B9).
Reachability, measured: **every one of the 14 packaged taxonomy packs has a
packaged rule book**, so `validate` on a packaged module cannot hit it today. It
is reachable from `validate_return(ret, pack=<caller's own pack>)`, and from any
future release that ships a pack before its rule book.

**F3 — "Unsupported" is zero in practice today, so completeness has to be framed
honestly.** Across all 24 (rule book, module) pairs, 0 enforced rules fail to
parse and 0 call an unimplemented function. The PRA001 oracle test asserts
"nothing is unsupported" on the Bank's own sample. So the incompleteness a user
actually meets today is **linked templates left out of the return** (VAL004, a
Warning that does not affect `submittable`) and the F2 hole. Unsupported rules and
rules that read a table the pack lacks are real code paths, but they come up only
with a rule book built by `rulebook import` or with a future release. The model
below covers all of them, without claiming the rare ones are common.

**F4 — Volume rules out one pretty-printed document.** On a thin carve of the
Bank's PRA001 sample (22,870 facts), Arelle records **28,627 evaluations**, with
up to 3,055 for a single rule. The full sample has 61,428 facts. A summed
(`seq: True`) reference can read hundreds of cells in one evaluation. Complete
evidence therefore has to be **streamed, with each cell written once**, and kept
separate from the summary that `--format json` prints to stdout.

## Design principles

- **One evaluation pass.** Evidence is captured inside the evaluation that
  produced the verdict, through the hook `trace_rules` already uses. It is never
  recomputed afterwards. This is what lets the user's team rely on our engine
  instead of building their own, and it becomes a tested invariant: an
  evidence-collecting run's `RuleResult`s equal `evaluate_rules`'s.
- **Costs nothing when switched off.** Capture is opt-in. The default
  `validate` / `build` path has the same cost as today, and a benchmark holds
  that in place.
- **Two outputs, two jobs.** The **summary report** (`--report`, `--format json`,
  the build manifest) stays small and readable by people and CI. The **evidence
  export** (`--evidence FILE`) is complete and machine-oriented. Both carry the
  same identity block, so each can be matched to the other.
- **A versioned contract.** Both declare a schema name and version. Their JSON
  Schemas ship in the wheel. Within a major version, changes only add fields.
- **Completeness as its own axis**, implemented once. Following the
  `RuleReport.coverage_shortfall` pattern ("THE one implementation of the coverage
  predicate"), VAL003, VAL004, the new status and the CLI exit code all read one
  property, so they cannot disagree.
- **Deterministic bytes.** The same input, pack, rule book and settings give
  byte-identical evidence. Evaluation order is already sorted
  (`_environments` returns `sorted(...)`). Timestamps stay outside the hashed
  content, and `--no-timestamp` works as it does for `build`.

## Proposed design

### 1. Every rule outcome (ask 1)

The summary report's `rules` array lists **every enforced rule**, passes included,
in rule book order. Each entry gains `evaluations` and `rule_sha256` (see §4). At
1,441 rules and about 150 bytes each, that is roughly 200 KB for PRA001: small
enough to stay in `--report`, so proving the full set of rules that ran does not
need the large evidence file. Code that relied on `rules` holding only non-passes
must now filter on `status`. That is a breaking change in meaning, so it ships
with `schema_version: 2` (today's unversioned shape counts as 1) and a "Changed"
changelog entry. Nothing in the repository reads `rules`: rwa-calc's
`api/rest.py::_filing_payload` reads `taxonomy`, `summary` and `findings`, and the
manifest embeds `summary` and `findings`.

### 2. Uncapped structured exceptions (ask 2)

**Rule checks.** Every unsatisfied evaluation is an `evaluation` record with
`holds: false` in the evidence export (§6), carrying every cell it read. The caps
stay where people read the output (`RuleResult.failures`, finding messages, the
dashboard) and do not apply to the evidence. In the summary report, the kept
failures gain the `addresses` the engine already computes.

**Structure checks.** `Finding` gains a field that defaults to empty, so existing
code keeps working:

```python
@dataclass(frozen=True)
class FactPosition:
    """One fact a structure finding is about, in the filer's coordinates."""
    table: str
    sheet: str | None
    open_key: str | None
    row: str | None
    column: str | None
    value: float | None = None
    text_value: str | None = None
    detail: str = ""             # e.g. "expected monetary, got 'n/a'"; "same cell as fact 12 (7,000)"
    source_ref: str | None = None  # XBRL fact id / context id, for XBR findings

# Finding gains:  positions: tuple[FactPosition, ...] = ()
```

`_roll_up`, `_duplicates`, `_unknown_tables`, `_type_findings`,
`_row_key_findings`, `_inconsistent_datapoints` and `_indicator_findings` fill it
in from frames they already hold, without caps. The XBRL reader's XBR001–XBR003
findings fill it in with `source_ref`, because a fact the module does not have has
no table coordinates. Messages keep their first-five examples, so text output does
not change. The summary report carries `positions_total`, and the evidence export
carries every position as a `structure_exception` record.

### 3. Structured calculation evidence (ask 3)

New capture types in `boe/engine.py`. They add to `Evaluation` without changing
its existing fields, so `workflow.compare` and `workflow.explain` are unaffected:

```python
@dataclass(frozen=True)
class Operand:
    value: float | str | bool | None   # the side's value as the rule language saw it
    allowance: float                   # as the engine propagated it (0 without the i prefix)
    cells: tuple[int, ...]             # ids into the cell dictionary: reported facts read
    defaulted: tuple[DefaultedCell, ...]  # cells read at the reference's dv

@dataclass(frozen=True)
class Comparison:
    operator: str        # "=", "!=", "<=", "<", ">=", ">"
    interval: bool       # the i prefix
    left: Operand
    right: Operand
    difference: float | None   # left - right, numeric operands only
    tolerance: float           # left.allowance + right.allowance if interval else 0.0
    excess: float | None       # how far outside the tolerance; 0.0 when it holds
    holds: bool
    branch: str                # "rule" | "where" | "if" | "then" | "else", with depth for nesting

# Evaluation gains:  comparisons: tuple[Comparison, ...] = ()
```

- **Where it is captured:** in the `Binary`/`is_comparison` branch of
  `_Evaluation._value`, the one place `_compare` receives both `_Amount`s. Because
  `and` / `or` short-circuit there, the log holds exactly the comparisons the
  engine executed, in order. For a rule like `boe_b0076`
  (`if … then a i= exp(…) else true()`), the decisive comparison is inside the
  `then` branch and is recorded with `branch: "then"`. Today's top-of-rule
  `relation` cannot show that.
- **Interval semantics, stated rather than implied.** The schema documents the
  engine's own predicates (`_compare`): `=` holds iff `|d| ≤ t`; `!=` iff
  `|d| > t`; `<=` iff `d ≤ t`; `<` iff `d < t`; `>=` iff `d ≥ −t`; `>` iff
  `d > −t`, where `d = difference` and `t = tolerance`. Equivalently, each side is
  the interval `[value − allowance, value + allowance]` and `i=` holds iff the two
  intervals overlap. A reader can check every recorded `holds` from the record
  alone, which is what "show precisely why a check failed" requires.
- **Products and quotients:** their allowances are propagated by the engine (the
  quotient uses the corner method in `_arithmetic`). They are recorded as computed
  and not re-derived. A per-node arithmetic breakdown can be added later without
  breaking the format.
- **Per-cell accuracy.** The cell dictionary (§6) records each fact's **effective**
  `decimals` and where it came from: `stated` (the fact's own `decimals`),
  `accuracy` (the run's `Accuracy` default for its data type), `integer` (integers
  are exact to the unit), or `exact` (`DECIMALS_EXACT`). It also records the
  resulting allowance. That is the information `_typed` / `_allowance` use now and
  then throw away.
- **Reported versus defaulted:** a cell read at its default appears in
  `Operand.defaulted` with its address and the default used (`0`, `false`, or the
  empty sequence), and contributes an allowance of 0. That is the engine's rule,
  and it is often what the break is really about.

The `v0174_m` example as it would be recorded at the default accuracy:

```json
{"record": "evaluation", "rule_id": "v0174_m", "seq": 0, "place": {}, "holds": true,
 "comparisons": [{"operator": "=", "interval": true, "branch": "rule",
   "left":  {"value": 9000.0,  "allowance": 500.0,  "cells": [41], "defaulted": []},
   "right": {"value": 11000.0, "allowance": 1500.0, "cells": [42, 43, 44], "defaulted": []},
   "difference": -2000.0, "tolerance": 2000.0, "excess": 0.0, "holds": true}]}
```

At `--monetary-decimals 0` the same record reads `"tolerance": 2.0,
"excess": 1998.0, "holds": false`. That single record makes F1 visible.

### 4. Versioned evidence identity (ask 4)

The summary report and the evidence header both carry the same `identity` block:

```json
"identity": {
  "evidence_id": "sha256 of the canonical JSON of everything below except generated_at",
  "schema":    {"name": "rwa-filer/validation-report", "version": "2.0"},
  "generator": {"package": "rwa-filer", "version": "0.2.0"},
  "input": {"file": "return.parquet", "format": "parquet", "file_sha256": "…",
            "facts_sha256": "…", "facts": 132,
            "header": {"entity": "…", "reference_date": "2027-03-31", "module": "PRA001", "currency": "GBP"}},
  "taxonomy": {"module": "PRA001", "version": "4.1.1", "pack": "pra001-4.1.1",
               "entry_point": "…", "sha256": "over pack.json, cells.arrow, datapoints.arrow"},
  "rulebook": {"file": "banking_reporting-4.1.1.json", "framework_version": "banking_reporting",
               "taxonomy": "4.1.1", "sha256": "of the packaged file that ran",
               "workbook_sha256": "c1165095…", "formulas_package_sha256": "b414cf87…",
               "rules_loaded": 1486, "rules_enforced": 1441},
  "settings": {"accuracy": {"monetary_decimals": -3, "percentage_decimals": 4, "source": "default"}}
},
"generated_at": "2026-11-15T14:00:00Z"
```

- `file_sha256` identifies the bytes. `facts_sha256` is a canonical digest of the
  `CanonicalReturn` (facts sorted by coordinates, values in a canonical text
  form). It shows whether a re-export of the same figures in another file format
  is the same input.
- The rule book's `workbook_sha256` and `formulas_package_sha256` already exist in
  every packaged rule book (`source.sha256`, `source.formulas.package_sha256`), and
  are exported as they are. The pack has no digest today. It is computed when the
  pack loads (at most about 1.5 MB to hash, for PRA001, and cached), which also
  covers a pack the caller compiled with `taxonomy compile`.
- **Per-rule `rule_sha256`** over expression, scope, where, join, closed
  dimensions and the module's severity. `boe/catalogue.py` says a rule's identity
  is "its framework version AND its code". Across package updates the same code
  can carry a changed formula, and this digest is how a comparison of two runs
  catches that.
- `accuracy.source` is `default`, `cli` or `caller`. `evidence_id` is identical
  for identical (input, pack, rule book, settings, engine version), so two runs
  can be compared by id before any detail is read.

### 5. Explicit completeness (ask 5)

```python
type ValidationStatus = Literal["CLEAN", "INCOMPLETE", "BLOCKED"]

@dataclass(frozen=True)
class IncompleteCause:
    code: str                    # see table
    rules: tuple[str, ...]       # the rules affected, every one
    templates: tuple[str, ...]   # filing indicators, where the cause is a template
    detail: str

# RuleReport.completeness -> tuple[IncompleteCause, ...]   (THE one implementation)
# ReturnValidation.status  -> "BLOCKED" if blocking findings,
#                             else "INCOMPLETE" if completeness causes, else "CLEAN"
```

| Cause | Population | Today |
|---|---|---|
| `no_rulebook` | No rule book for the module: no rules ran | Silently `submittable` (F2) |
| `rules_unsupported` | Enforced rules with reason `unsupported` | A count in `not_evaluated_reasons` only |
| `rules_table_not_in_taxonomy` | Enforced rules reading a table the pack lacks (rule book and pack out of step) | A count only |
| `linked_templates_missing` | VAL004's population: rules not run because a template read with a reported one is absent | VAL004 Warning |
| `coverage_shortfall` | VAL003's population | VAL003 Error (already blocking) |

These are **not** causes, and the documentation will say why: `no_data`,
`closed_by_formula`, and `template_not_reported` where none of the templates the
rule reads is reported. The gateway does not run those rules either, and they say
nothing about this return, so treating them as gaps would make every return
incomplete. An alarm that fires on every return tells the reader nothing (B9).

Behaviour changes:

- `no_rulebook` also raises **VAL003** with a new shortfall
  `no_rulebook` (Error). This closes F2. It changes nothing for packaged modules
  (measured above) and blocks the custom-pack path that is currently reported as
  clean.
- A new **VAL005** (Warning) names the unsupported and pack-mismatched rules, so
  they reach the findings, the dashboard and the text summary rather than a count
  alone.
- Text summary: a `status:` line, e.g.
  `INCOMPLETE — linked templates not reported (2 templates, 16 rules)`. JSON
  output gains `status` and `completeness`.
- **Exit codes:** by default nothing changes (0 = nothing blocks, 1 = blocked).
  The opt-in `--require-complete` makes `INCOMPLETE` exit **3**, so a pipeline can
  tell "clean" from "clean but incomplete" without parsing JSON. VAL004 is a
  Warning on purpose ("whether the firm must report the template is not something
  the rules can say"), so making INCOMPLETE fail by default would override that
  decision. See decision D2.

### 6. The evidence export

**Format: JSON Lines** (`.jsonl`, or `.jsonl.gz`), one typed record per line, in
this order:

| `record` | Count | Content |
|---|---|---|
| `header` | 1 | `identity`, `generated_at`, schema URL, record counts to expect |
| `cell` | one per reported fact any evaluation read | `id`, address, data point, metric, data type, value / text, effective `decimals`, `decimals_source`, `allowance` |
| `rule` | one per enforced rule (passes included) | `rule_id`, label, severity, status, reason, detail, satisfied / unsatisfied / evaluations, tables, expression, `rule_sha256` |
| `evaluation` | one per evaluation, satisfied or not | `rule_id`, `seq`, `place`, `holds`, `comparisons`, cells read |
| `structure_exception` | one per affected fact | finding code, finding index, `FactPosition` |
| `finding` | one per finding | as the summary report has it, with `positions_total` |
| `trailer` | 1 | final counts, `status`, `completeness`, and `content_sha256` over every line before it |

Why JSON Lines: it can be written in constant memory as evaluations happen (F4),
and it loads directly into the tools the user's team is likely to use
(`pl.read_ndjson(path).filter(pl.col("record") == "evaluation")`, DuckDB
`read_json_auto`, `jq`). The trailer's digest makes a truncated or edited file
detectable. Writing each cell once keeps a 300-cell sum to 300 integers. A single
JSON document can be offered as `--evidence-format json` if the user needs it
(decision D1).

**API.** The new public module `rwa_filer.evidence` declares `__all__`. Today
`trace_rules` lives in `boe.engine` and `validate_return` in `validate.returns`,
and neither module declares a public surface. A declared, documented entry point
is part of what "stable" means here.

```python
def collect_evidence(ret, pack=None, *, rulebook=None, accuracy=None,
                     source_findings=(), source: SourceIdentity | None = None) -> Evidence
def write_evidence(evidence: Evidence, path: Path, *, timestamp: bool = True) -> EvidenceFile  # path, sha256, counts
def read_evidence(path: Path) -> Evidence     # round-trips; verifies the trailer digest
EVIDENCE_SCHEMA_VERSION: Final = "1.0"
REPORT_SCHEMA_VERSION: Final = "2.0"
```

`Evidence` is a frozen dataclass holding the `ReturnValidation` (so the verdict
and the evidence come from one run), the identity, cells, evaluations and
structure exceptions. `read_evidence` is for the user's team and for our own
consistency tests.

**CLI.**

```bash
rwa-filer validate FILE [--monetary-decimals N] [--percentage-decimals N]
    [--evidence FILE.jsonl[.gz]] [--require-complete] [--no-timestamp]
rwa-filer build FILE --out DIR … [--evidence FILE.jsonl[.gz]]
```

The two accuracy options come from one shared `_add_accuracy_arguments` helper,
so their help text and defaults cannot drift between `validate` and `build`. The
`referee` command's own validation pass uses them too. When `build` writes
evidence, the manifest records its file name and SHA-256. `signoff` already binds
the manifest's checksum, so a sign-off covers the evidence as well, with no change
to `signoff`.

**JSON Schemas** ship in the wheel at
`rwa_filer/schemas/validation-report-2.schema.json` and
`rwa_filer/schemas/evidence-1.schema.json`, and are published on the docs site.
Compatibility policy: a minor version only adds fields or record types; renaming,
removing or changing the meaning of anything bumps the major version.

## Phasing

Each phase ships on its own. Release rwa-filer before any rwa-calc change that
depends on it.

| Phase | Scope | Asks | Size |
|---|---|---|---|
| **P1 — quick wins** | `validate` accuracy options (F1); every rule in `--report`; serialise `failures[].addresses`; `schema_version`; the `identity` block with all fingerprints; `no_rulebook` → VAL003 (F2) | 1, 4, 6, part of 5 | Small: `report.py`, `returns.py`, `cli.py`, digests in `taxonomy/pack.py` and `boe/catalogue.py` |
| **P2 — completeness** | `IncompleteCause`, `RuleReport.completeness`, `ReturnValidation.status`, VAL005, `--require-complete` (exit 3), text `status:` line, dashboard badge | 5 | Small to medium |
| **P3 — calculation evidence** | `Operand` / `Comparison` capture in `_value`; cell dictionary with decimals provenance; `rwa_filer.evidence` collect / write / read; `--evidence`; evidence JSON Schema | 2 (rules), 3 | Medium: the only phase that touches `boe/engine.py`'s evaluation path |
| **P4 — structure exceptions** | `FactPosition`, `Finding.positions` filled in by every STR and XBR check, `structure_exception` records | 2 (structure) | Medium: seven call sites in `structure.py`, three in `xbrl/reader.py` |
| **P5 — integration** | `build --evidence` and the manifest binding; evidence download on the dashboard; rwa-calc `export_filing_package(evidence=…)`, plus `status` / `completeness` in `api/rest.py` | — | Small |

P1 is one minor release (0.2.0, because `rules` changes meaning) and gives the
user a full rule inventory, fingerprints and consistent accuracy right away.
P3 is the core of what they asked for.

## Testing and gates

Written test-first, in `packages/rwa-filer/tests/`:

- **Same verdicts:** `collect_evidence(...).validation` equals
  `validate_return(...)` rule by rule (status, satisfied, unsatisfied) on every
  fixture, and on the Bank's samples where `RWA_FILER_BOE_DIR` is set.
- **The evidence explains itself:** a checker written **from the schema
  alone**, importing nothing from the engine, recomputes every `Comparison.holds`
  from `difference`, `tolerance` and `operator`, recomputes each rule's
  satisfied / unsatisfied counts from its `evaluation` records, and recomputes
  each side's allowance where it is a sum of cells. This is the property the user
  wants to rely on, so we test it rather than assume it. Mutation evidence as
  C1.11 requires: drop the `i` flag in capture, or cap evaluations at 5, and each
  probe must turn this test red, with the reason checked.
- **Today's flip, pinned:** the `v0174_m` return run through
  `validate --monetary-decimals N` and `build --monetary-decimals N` gives the same
  verdict for N in {−3, 0, 2}. Red today: `validate` rejects the option.
- **F2, pinned:** a pack with no rule book is not `CLEAN`, and produces VAL003
  `no_rulebook`. Red today.
- **Determinism:** two runs with `--no-timestamp` under different
  `PYTHONHASHSEED`s give byte-identical evidence and the same `evidence_id`.
- **Schema:** every report and evidence file the tests produce validates against
  the shipped schema. `jsonschema` is in `uv.lock` already but must be declared in
  `packages/rwa-filer/pyproject.toml`'s dev group, or CI's `rwa-filer (isolated)`
  job will not have it.
- **Cost:** a benchmark of the default `validate` path confirms capture adds
  nothing when off, and a large synthetic return confirms evidence writing stays
  within a fixed memory bound.

Repository gates this touches: the `rwa-filer` suite; `arch_check` (check 23:
`rwa_filer` imports no `rwa_calc`); the clean-environment wheel install (no new
runtime dependencies: `hashlib`, `gzip` and `json` are standard library); the
**referee differential**, which runs on any change under `rwa_filer/boe`, where a
changed verdict is a finding to explain and never a number to re-bank; and
docs: `docs/rwa-filer/index.md` gains an "Evidence export" section and a schema
reference, plus `packages/rwa-filer/CHANGELOG.md`.

## Decisions for the package owner

- **D1 — Evidence format:** JSON Lines (recommended: streams, and loads straight
  into Polars or DuckDB) or one JSON document (closer to the user's words, but it
  must be held whole to be written or parsed at full-sample scale). Both can be
  offered, with one default.
- **D2 — What `INCOMPLETE` exits with by default:** 0, with `--require-complete`
  giving 3 (recommended: keeps VAL004 as the deliberate Warning it is), or 3
  without the flag.
- **D3 — Severity of `no_rulebook`:** blocking VAL003 (recommended: it is the
  package's own invariant) or a Warning.
- **D4 — Which facts the evidence holds:** only cells that some evaluation read,
  plus `facts_sha256` (recommended), or a full copy of the return behind
  `--evidence-all-facts`.
- **D5 — `rules` in the summary report:** change its meaning in place under
  schema 2 (recommended; nothing in the repository reads it), or add a new
  `rule_outcomes` key and deprecate `rules`.

## Out of scope

A second calculation engine, or any re-derivation of allowances outside the
engine. The referee's Arelle evidence, which has its own report. The older
template-level engine (`rwa_filer.validate.{index,evaluate,checker}`) that rwa-calc
maps onto `VAL001`–`VAL003` in `reporting/filing/checks.py`: completeness here
applies to the BoE path that `validate`, `build` and `validate_return` use.

## Outcome: what landed

All five phases landed in rwa-filer. Decisions D1–D5 were taken as recommended:
JSON Lines, exit `3` only with `--require-complete`, `no_rulebook` as a blocking
`VAL003`, only the cells some evaluation read, and `rules` changed in place
under report schema 2.0.

- **F1 is closed and pinned.** `tests/test_cli_accuracy.py` checks that the
  measured return really sits on the rounding boundary (PASS at −3, FAIL at 0),
  and that `validate` and `build` agree at −3, 0 and 2. It was red before the
  change: `validate` rejected the option.
- **F2 is closed and pinned.** The test that asserted a module with no rule
  book is submittable now asserts `VAL003` `no_rulebook`. `tests/test_filing.py`,
  whose docstring relied on the hole, now hands its builds an explicit rule
  book.
- **The evidence explains itself, and that is tested.** `tests/test_evidence.py`
  holds a checker that imports nothing from `rwa_filer`. It validates every line
  against the shipped schema, recomputes every recorded comparison verdict from
  its recorded numbers, and recomputes every rule's counts from its evaluation
  records. Three single-change mutations of the capture each turn it red:
  recording `tolerance` as 0, recording `interval` as `False`, and keeping only
  `MAX_FAILURES` failing evaluations. Each was measured, and the test's
  docstring records which tests each one reddens.
- **Determinism** is checked across two processes with different
  `PYTHONHASHSEED` values, for `.jsonl` and `.jsonl.gz`.

Where the implementation differs from the design:

- **`referee` did not get the accuracy options.** An instance must state
  `decimals` on every numeric fact (Filing Manual rule 2.18, which the reader
  checks), so the referee's own validation already compares at the accuracy the
  file states. `validate` and `build` share the options through one helper.
- **`evidence_id` does not depend on how the accuracy was chosen.** It covers
  the accuracy's value. `settings.accuracy.source` (`default` / `given`) is
  recorded beside it, so `validate` at the default and `build`, which always
  passes its accuracy, give one id for one input.
- **The evidence is collected in memory, then streamed to disk.** The trace
  holds every evaluation, as `trace_rules` already did, and `write_evidence`
  writes it line by line. Capture during evaluation in constant memory was not
  built, and no memory-bound test was added. The default path traces nothing:
  it pays one `is None` check per comparison and per conditional branch. It was
  not benchmarked separately.
- **rwa-calc's side of P5 is not in this change.** rwa-calc pins
  `rwa-filer>=0.1,<0.2`, and an installed rwa-calc resolves rwa-filer from PyPI.
  Exposing `status` and `completeness` in `api/rest.py`'s filing payload, and
  evidence from `export_filing_package`, follows the rwa-filer 0.2.0 release
  together with the pin bump, as CLAUDE.md's release order requires.
- **Positions are not attached to header findings, to unknown declared filing
  indicators, or to `VAL…` findings.** Those are not about facts. A rule
  finding's facts are its failing evaluations in the evidence.

## Appendix: reproducing the measurements

```bash
# An environment holding rwa-filer alone, outside the repository's .venv
UV_PROJECT_ENVIRONMENT=/tmp/filer-venv uv sync --package rwa-filer --frozen

# Counts per rule book: enforced rules, parse errors, unsupported functions,
# and packs without a rule book (0 / 0 / none at 22b43d1)
#   load each rulebook with boe.catalogue.load_rulebook, run
#   boe.engine._check_functions over each enforced rule's tree

# F1: the same return, two accuracies
#   validate_return(ret, pack)                          -> v0174_m PASS
#   validate_return(ret, pack, accuracy=Accuracy(0, 4)) -> v0174_m FAIL

# F4: evaluation volume on the Bank's sample carve
#   packages/rwa-filer/tests/boe/data/pra001_sample_all_tables_oracle.json
#   (sum of [satisfied, unsatisfied] over "rules" = 28,627; max per rule 3,055)
```

The synthetic return was built from the PRA001 pack's `cells` frame: every
numeric cell without a sheet in C 01.00.01.01 and C 03.00.01.01, with values
drawn from multiples of 1,000 using a fixed seed, plus seven facts on rows that do
not exist in C 01.00.01.01 to trigger STR002. It is a scratch artefact and is not committed. Any return that reports
C 01.00 r0070 and r0080–r0091 with a difference of exactly 2,000 reproduces F1.
