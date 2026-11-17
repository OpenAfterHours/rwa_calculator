# Changelog

All notable changes to `rwa-filer` are recorded here. The package is versioned
and released independently of `rwa-calc`; its release tags are prefixed
`rwa-filer-v`.

## [Unreleased]

### Added
- (Next release changes will go here)
- **The Bank of England's validations deny list, per release.** The Bank changes
  how its gateway runs some rules after a taxonomy is published: it deactivates
  a rule, or downgrades it to a warning. `rwa-filer` now ships that list for each
  taxonomy release (`boe/data/deny/<release>.json`; 4.1.1 is built from the
  November 2026 workbook, 16 entries) and applies it.
  - `validate_return` (`rwa-filer validate`, `build`) applies it after the rules
    are evaluated, on the run date; `submission_date=` / `--submission-date`
    sets another date. The return's reference date never decides: the list is
    the gateway's configuration on the day of submission. An entry with no date,
    a later date or another module is listed and not applied.
  - A deactivated rule is `NOT_EVALUATED` with reason `deactivated_by_publisher`.
    Like `closed_by_formula`, it is not an evaluability gap and does not count
    against template coverage. A downgraded rule keeps running, as a Warning
    (`VAL002`), and its message says so.
  - The published verdict is kept on the new `RuleResult.formula`.
    `Rule.fingerprint` does not change.
  - `compare` (`compare_returns(submission_date=...)`, `--submission-date`)
    judges both returns by the list in force. A rule switched off that day is
    not a shared break; if its published formula breaks in either return it is
    listed in `ReturnComparison.switched_off`, so the switch is never silent.
  - The referee compares Arelle with the published verdict, since Arelle runs the
    taxonomy's formulas, which still contain the deny-listed rules.
  - Every surface that lists rules says what the Bank did, with the date and the
    known-issue number: the text report, the JSON report and the evidence
    (`deny_list` and `formula` on rules, `summary.deny_list`,
    `identity.deny_list`), `rules list`, `rulebook list` (a deny-listed column),
    and the dashboard's rules, overview, reference and compare pages.
    `evidence_id` covers the entries in force, not the date or the file.
  - New `rulebook deny-list [import|check]`: imports the Bank's workbook by
    column name, matches each code to a rule of its module, reports and keeps any
    code that matches none, and joins the known-issues log for the issue number.
    One typo in the November 2026 list is resolved by a stated rule
    (`boe_b04006_1/_2` is MRL001 `boe_b4006_1/_2`, which known issue #23
    corroborates); the Bank's spelling is kept as `published_code`. `check`
    compares a packaged list with the workbook.
  - Building a release (`rwa_filer.release_build`) keeps a release's list on
    rebuild and removes it when the release is retired.
- **A register of known issues with the Bank's published rules, and a label on
  every result one explains.** `boe/data/issues/4.1.1.json` holds 40 issues
  (PI-01 to PI-40): 32 defects, 4 clarification questions and 4 the Bank has
  already acknowledged in its known-issues log. Each names its rules, pinned by
  `Rule.fingerprint` and severity, quotes the instructions and the rules with
  their PDF page, and carries a worked example whose result Arelle 2.47.5
  measured against the Bank's v4.1.1 package.
  - **No verdict changes.** A finding inside an issue's footprint carries
    `publisher_issues` and a sentence saying what the issue is. A draft issue
    reads "identified by rwa-filer, not yet raised with the Bank of England"; a
    clarification reads "Open question with the published rule". The labels are
    in the JSON report, the text report, the evidence, the filing manifest and
    the dashboard (a chip and a callout), and outside `evidence_id`.
  - `rwa-filer rulebook issues [ISSUE] --format text|json|markdown`.
  - Library: `rwa_filer.boe.issues.issues_for(release, module, rule_id)`, which
    returns a tuple of issues (several issues can name one rule).
  - Schema: `publisher-issues-1.schema.json`. A new release gets an empty
    register and a WARNING; retiring a release removes its register.
  - The repository's `docs/rwa-filer/publisher-issues.md` is generated from the
    register and is the copy to send to the Bank.
- `ValidationRule.always_execute`, read from the Bank's extract ("Always
  execute"); `False` for every EBA rule, as for the Bank's own restatements
  of EBA rules, none of which is always-execute.
- **Choosing the taxonomy release.** `rwa-filer` can now ship several taxonomy
  releases, and a run uses one: the one `--taxonomy VERSION` names, on every
  command that reads a return (`validate`, `build`, `diff`, `compare`, `dash`,
  `template`, `referee`), or by default the release **live** for the return's
  module on the day of the run. A module with no live release uses its only
  future one; with several, the run stops and asks for a version. Status
  belongs to a module (in 4.1.1, PRA001 and PRA116 are future until 1 January
  2027; the other twelve modules are live). Library: `rwa_filer.release`
  (`resolve_release`, `Release`, `shipped_releases`, `ReleaseNotFoundError`),
  and `taxonomy=` / `today=` (or `release=`) on `validate_return`,
  `build_filing`, `write_instance`, `read_instance`, `open_source` and
  `compare_returns`. The shipped releases are listed in `releases.json`;
  those no longer shipped in `retired.json`, so naming one says which
  `rwa-filer` version last shipped it.
- **Every run says which release it used and why.** The text report (after the
  verdict and the status line), `build`, `compare` and `template` print the release, how
  it was chosen and the module's status in it, and each other shipped release
  with the option that selects it. The JSON report and the build manifest
  carry it in their `taxonomy` block (`status`, `applies_from`, `applies_to`,
  `run_date`, `chosen_by`, `shipped`, `covers_reference_date`). `taxonomy list`
  shows every shipped release's modules with their status and which one a run
  uses by default (`--module` narrows it); `--version` lists the releases. The
  dashboard shows the release in the top bar, offers a switch that opens the
  return again against another release, has a release choice on its open
  form, and lists the reference pages per release.
- **`STR011`** (Warning): the return's reference date is outside the dates the
  chosen release gives its module. Reported in `ReturnValidation.release_findings`;
  it never blocks a build.
- **Building a release from the Bank's files** (`rwa_filer.release_build`, run
  by the repository's `scripts/build_filer_release.py`): compile every module,
  package it only when the Bank's sample agrees, import every rule book, and
  `--check` that a packaged release is exactly what the files give — run on the
  4.1.1 downloads, it is byte for byte. Each release's measured numbers are
  kept beside its tests.

### Changed
- (Next release changes will go here)
- **The template-level engine's enforced population moves with the date.**
  `load_rules(framework, on=...)` reads the same packaged deny list for the BoE
  extract's release: a deactivated rule is not enforced, and a downgraded one is
  a Warning. `RuleSet.enforced` is therefore 795 BoE rules on 16 November 2026,
  not 800. `RuleSet.published_in_force` keeps the extract's own population. The
  extract's `status` field is not changed.
- JSON report schema 2.0 → 2.1 and evidence schema 1.0 → 1.1. Every new field is
  optional.
- **Breaking:** `taxonomy.pack.resolve_pack` / `select_pack` and
  `boe.catalogue.rulebook_for_module` are removed; use
  `rwa_filer.release.resolve_release`, which returns the pack and the rule book
  of one release together. `rulebook_for_module` took the first rule book by
  file name, so a second shipped release would have paired its pack with an
  older release's rules. `ReturnValidation`, `InstanceReading` and
  `SourceReading` carry the `release` (their `pack` is now read from it), and
  lookup failures raise `ReleaseNotFoundError` in place of `PackNotFoundError`.
- A reference date outside the release's dates is the `STR011` Warning. It was
  a blocking `STR008` for an XBRL file and a hard stop (`PackNotFoundError`) for
  any other input. `rwa-filer template` no longer needs `--reference-date`; given,
  it only warns when the release does not cover it.
- The 14 packaged `pack.json` files record the taxonomy package under the name the
  Bank publishes it as, `boe-banking-v411.zip`; no other part of them changed.
- The template-level engine reads the Bank's workbook by column name instead of
  position, so a column the Bank adds or moves no longer shifts a field, and
  finds its Basel 3.1 extract as the newest one packaged.

### Performance
- **Referee workers run at once.** `run_referee(jobs=...)` and `rwa-filer
  referee --jobs N` set how many Arelle workers run side by side; by default
  (`None`) as many as fit in the memory available, less 1.5 GB, at the
  per-worker cap `max_rss_gb`, and no more than one per CPU — one where
  `/proc/meminfo` cannot be read (`rwa_filer.referee.resolve_jobs`). Available
  is the kernel's `MemAvailable`, or the room under a cgroup memory limit on
  the process (a container's `--memory`, v1 or v2, on its own group or an
  ancestor) where that is less: the OOM killer enforces the limit, which
  `MemAvailable` does not see. An explicit number over that budget is run as
  asked, with one warning. Every worker keeps its own memory and
  time guard and its own Arelle configuration folder, and the results are
  merged in plan order, so a verdict, a message's order and the lost rules do
  not depend on which worker finishes first. Several instances can share one
  pool: `prepare_referee` each, then `run_referees` them all, a result each.
  An interrupt kills the workers that are running, within about half a second:
  the pool is waited on half a second at a time, as a signal delivered to
  another thread (polars keeps several) does not wake an unbounded wait. New
  `interrupt_on_sigterm()` makes SIGTERM do the same — `rwa-filer referee`
  runs inside it — since a worker runs in a session of its own and SIGTERM's
  default action would leave every running worker behind.
- **A referee worker ends as soon as its result is written.** It used to close
  the Arelle session and tear the interpreter down first, freeing a model of
  several GB object by object: about 13 seconds of a minute-long worker on
  PRA001, after the result was on disk. The result is read before the session
  would close, so it is unchanged; `worker.main` called in-process still
  closes the session.
- **A referee worker runs Arelle with Python's cyclic garbage collector off.**
  Arelle keeps nearly everything it allocates until the worker ends, so the
  collector's passes freed little: off, a PRA001 worker loads and evaluates
  about 14% faster for about 7% more peak memory (3.89 GB against 3.64 on the
  largest chunk measured), with the same verdicts. In-process callers get the
  collector back when the session ends.
- **A referee worker's result can be reused.** With `cache_dir=` on
  `run_referee` / `run_referees`, a worker's raw result is stored under a
  SHA-256 of everything it depends on — the bytes of the instance, the
  taxonomy package, the overlay's members and the filing-rule plug-in, the
  worker's settings, every distribution installed in the worker interpreter
  (`name==version`: an `arelle-release==X` install leaves lxml, regex,
  pyparsing and the rest unpinned, and a new release of any of them must
  re-run Arelle), its Python version and locale, and the referee's own code —
  and of no path. A run that
  finds the key reuses the result, byte for byte, and launches no worker
  (`ChunkStat.cached`); the merge and any comparison run as before. Only a
  worker that finished is stored, and not even one of those that left an
  assertion unanswered or logged an error-level or exception message — a
  stored result is replayed by every later run, so nothing that may not
  happen again is kept. An entry is a digest line and the raw result, written
  whole or not at all; one whose digest does not match, or that does not read
  back as a result, is recomputed.
  `referee_cache_dir` reads the folder from `RWA_FILER_REFEREE_CACHE`. The
  library default is no cache.

---

### Fixed
- **Rules the Bank has switched off at its gateway are no longer enforced.**
  Before this release, `boe_b0710`, `_1`, `_2`, `_3` and `boe_b0746` (deactivated
  19 October 2026; known issue #22), `boe_b0272` and `boe_b0274` (16 November
  2026), the PRA116 `boe_b0063_ss` family and PRA115 `boe_b1014` / `boe_b1022`
  failed returns the gateway accepts, and MRL001 `boe_b4006_1/_2` and
  `boe_b4008_1/_2` blocked where the gateway only warns. `compare` reported
  `boe_b0710` as a break in both returns.
- **A plain `sum()` or `abs()` in a rule carries no rounding allowance.** The
  engine read them as `isum()` / `iabs()`, so the summed facts kept their
  allowances and a rounded return passed where the gateway fails it. Affected:
  PRA001 `boe_b0770`, `boe_b0794`, `boe_b0820`–`boe_b0823`, `boe_b0829`; PRA116
  `boe_b0794`, `boe_b1037_ss`. Measured against Arelle on returns built with
  rounded figures (`tests/releases/4.1.1/oracles/rounding_and_default_oracle.json`).
  Plain `max` / `min` are unchanged: no published rule calls them, so Arelle
  cannot be asked.
- **OF 08.06's "all types" sheet is its own sheet.** A fact with no member on
  OF 08.06's open axis is the axis default (`eba_TA:x0`). The engine gave it no
  place, so it was added into every type's sums, and `boe_b0815` and
  `boe_b1042` failed a correct return. A failure on that sheet is reported with
  no open key, as the return reports it.
- **The template-level engine no longer fails a Bank rule where none of its cells
  is reported.** It read every unreported cell as zero, so `boe_b0778` (an
  OF 08.07 roll-out class's three shares total 1) failed every class with no
  exposure, where the shares are rightly empty. For a BoE rule that is not
  always-execute, a failing place whose cells are all unreported is now
  `NOT_EVALUATED` with reason `nothing_reported` (`SKIP_NOTHING_REPORTED`), as the
  gateway skips it (XBRL Variables 1.0 §4: a variable set whose fact variables
  have all fallen back is not evaluated); a place that holds stays `VACUOUS`.
  EBA rules read the same way, so `v09796_m`, the EBA twin of `boe_b0778`, no
  longer fails an empty C 08.07 roll-out class either.
- **A sum in a published rule adds up what the rule's formula says, not what
  its text suggests.** On a table with one row per obligor grade, securitisation
  or entity, a summed reference either adds up every row or stays on the row
  the rest of the rule is read at, and the workbook writes both the same way.
  `rwa_filer.boe` always added up every row, so `boe_b0760`-`boe_b0763` on
  OF 08.02 (each grade's total outflow, exposure after CRM, expected loss after
  PMAs and RWEA after adjustments against its own parts) failed every grade of
  every sheet with more than one grade, where the Bank's gateway passes them.
  The same misreading hit `v7372_m`-`v7377_m` (C 14.01 against C 14.00, per
  securitisation), `v11871_m` (C 06.02, per entity), their SDDT twins
  `boe_b0117_ss`-`boe_b0122_ss` and `v11871_m`, and MREL's `boe_b4101` and
  `boe_b4102` (BR 01.00, per instrument). On OF 08.06, which is filed once per
  type of specialised lending, the opposite: `boe_b0816`-`boe_b0822` and
  `boe_b1043` add up every type, and were read one type at a time. 28 rules in
  all. The packaged rule books now record, for each summed variable of each
  rule's XBRL formula, the dimensions it covers (`spans`, read by
  `rulebook import --taxonomy-package`; `Rule.spans_by_variable`), and the
  engine reads the sum from that. A rule book built without the taxonomy
  package is read from the text, as before. On returns built to have several
  rows, the engine and Arelle now agree on all 28; before, they disagreed on
  all 28 (`tests/releases/4.1.1/oracles/summed_references_oracle.json`).

## [0.1.3] - 2026-11-15

### Added
- **Evidence export**: `rwa-filer validate --evidence FILE` (and `build
  --evidence FILE`) writes everything a validation executed as JSON Lines
  (`.jsonl`, or `.jsonl.gz`), schema `rwa-filer/evidence` 1.0. It holds every
  enforced rule, passes included; every evaluation, satisfied or not,
  uncapped; and every comparison each evaluation executed, with both
  operands' values and rounding allowances, the difference, the tolerance the
  `i` prefix allowed, the excess beyond it, and the branch of the rule it was
  in. It also holds every reported cell read, once, with the `decimals` it was
  compared at and where that came from (stated by the fact, the run's
  accuracy, or an integer's unit), and every cell read at its default. It is
  written from the same evaluation pass as the verdict. A trailer digest over
  every line makes a cut or altered file detectable, and without a creation
  time (`--no-timestamp`) the same inputs give the same bytes. Library:
  `rwa_filer.evidence.collect_evidence`, `write_evidence`, `read_evidence`.
- **Evidence identity**: the validation report and the evidence header carry an
  `identity` block. It holds SHA-256 digests of the facts and header
  (independent of row order and file format), the source file, the taxonomy
  pack's files and the rule book (with the Bank's workbook and formula-package
  digests it was built from), plus the accuracy in effect and the generator
  version. `evidence_id` is one digest over the inputs. Each rule carries a
  `rule_sha256`, so a changed formula under an unchanged code shows.
- **Validation status**: `ReturnValidation.status` is `CLEAN`, `INCOMPLETE` or
  `BLOCKED`. `ReturnValidation.completeness` names each cause of an incomplete
  check (`no_rulebook`, `rules_unsupported`, `rules_table_not_in_taxonomy`,
  `linked_templates_missing`, `coverage_shortfall`) with every rule and template
  it covers. The text summary states it on its second line, the JSON gives
  `status` and `completeness`, and the dashboard overview shows it.
  `validate --require-complete` exits `3` on an incomplete check.
- `VAL005` (Warning): enforced rules the engine could not evaluate (one it does
  not implement, or one reading a table the taxonomy pack lacks).
- `Finding.positions`: every fact a structure (`STR…`) or reading (`XBR…`)
  finding is about, uncapped, each with what it holds and, where it differs
  fact by fact, what is wrong with it. Messages still quote the first five; the
  report gives `positions_total`, the evidence lists them all.
- `validate --monetary-decimals N --percentage-decimals N`, the options `build`
  takes, from one definition. A rule on the rounding boundary can hold at
  thousands and break at units, and `validate` could not be told which.
- JSON Schemas for the validation report and the evidence, in the package:
  `rwa_filer.schemas.load_schema`.
- `build --evidence` records the evidence file's checksum and `evidence_id` in
  the manifest, so a sign-off covers it. The manifest also gains `identity`,
  `validation.status` and `validation.completeness`. The dashboard offers the
  evidence for an opened return as **Download evidence**.

### Changed
- `rwa-filer dash`, Templates: the selected-cell panel now explains each broken
  rule where it stands, instead of only linking to the Rules page. Every rule
  carries the publisher's description, and **Read the rule** expands it in
  place: how many evaluations broke, the break that read this cell with the
  value of each cell it read (each a link to that cell on the grid, this one
  outlined), and the expression and scope as the Bank's workbook states them.
  The panel widens while a rule is open; a rule opened on one cell stays open
  on the next within the tab. The rule focused with **Show only this rule's
  cells** opens expanded. The link to the Rules page is kept. Library:
  `dash.grid.CellDetail.rules` (`CellRule`), `dash.views.rule_detail`.
- **The validation report's `rules` lists every enforced rule, passes included**
  (it listed only the rules that did not pass), each with `rule_sha256`,
  `evaluations`, `tables` and, for each kept failure, its cell `addresses`. The
  report declares `"schema": {"name": "rwa-filer/validation-report", "version":
  "2.0"}`. Code that read `rules` as "the rules that did not pass" must filter on
  `status`.
- **A module no rule book covers is no longer reported as clean.**
  `validate_return` returned `submittable` with only the structure checked, and
  logged a warning. It now raises `VAL003` with subject `no_rulebook` (Error),
  as it does when no rule runs. Every packaged taxonomy pack has a packaged rule
  book, so this changes nothing for a packaged module; it affects a caller that
  passes its own pack.
- `rwa-filer dash` — every page of a return now shows it as a build would file
  it now: the Overview, the Rules, the template grid's marks, the Build & sign
  off page and the top-bar verdict are all worked out with the drafted
  overrides applied. Before this, they kept showing the validation from when
  the file was opened, so an override that cleared a break left it showing
  everywhere except one button's preview. A banner says how many overrides are
  applied and how many blocking findings the return had as opened. The return
  is re-validated once per change to its overrides (`Workspace.working`,
  `WorkingReturn`). Compare still compares the files as they were opened, and
  now says so while overrides are drafted.
- `rwa-filer dash` — Build & sign off says what the drafted overrides change
  without being asked: the blocking findings and rule breaks before and after,
  then each rule they fix, each they newly break, and each broken rule they
  stopped from running. A rule whose figures were taken out does not run, so
  it is listed as no longer run, never as fixed. The *Check the return with
  these overrides* button is gone. The *write it anyway* option is offered
  only while the return, with its overrides, is still blocked.

---

## [0.1.2] - 2026-11-14

### Added
- `rwa-filer compare BASELINE CANDIDATE`: a return beside the one another
  system produced, or beside the filing it replaces, and why they differ.
  Every cell goes into one category: the same, within the rounding the files
  state, a zero against a blank, in a template only one reports, or material.
  The material differences are grouped into findings, each saying which return
  the Bank's own rules point at, checked place by place in both files. A
  finding is one of: differences that move together (with the row a figure
  moved between, and the change that move implies where the rows are rates);
  a cell that does not equal what a rule says it must, split into what its
  components explain and what is in the cell alone; a column only one return
  fills; zeros where the Bank expects nothing; or a rule that breaks in one
  file only. Every material cell is in exactly one finding. Facts the reader
  could not place are listed, never dropped. Exit `0` only when the two are
  equivalent. `--tolerance` for sources that state no accuracy;
  `--format json`. Library: `workflow.compare.compare_returns`,
  `ReturnComparison`; `workflow.explain`.
- `boe.engine.trace_rules` and `Evaluation` / `RuleTrace`: `evaluate_rules`'s
  results with every evaluation behind them: where it was made, whether it
  held, the comparison at the top of the rule, and the cells and number each
  side of it read, uncapped. `Failure.addresses` now comes from the same code.
- `VAL004` (Warning) — a template the return leaves out that enforced rules
  check a reported template against: OF 09.02 for a return holding OF 08.01
  without it, say. A rule runs only when every template it reads is filed, so
  those rules were switched off rather than failed, here and at the gateway, and
  the return would be accepted without the template's figures. One finding per
  missing template, naming the rules and the reported templates they read; a
  template declared not filed is not named. Shown on `rwa-filer validate`'s
  summary line, in the JSON report (`summary.templates_missing`, also
  `RuleReport.templates_missing`), and on the dashboard overview as **Linked
  templates not in this return**.

### Changed
- `rwa-filer dash` — Compare now opens with the comparison's findings, each
  with what it points at, its rules and a link to its cells, and the cell list
  filters by category and by finding. The comparison is worked out once per
  pair per session.

---

## [0.1.1] - 2026-11-14

### Added
- `rwa-filer dash` — a local web dashboard (`uvx rwa-filer@latest dash return.xbrl`).
  Open a return from a file or a path; see whether anything blocks submission
  with the counts behind the verdict, including how many rules ran and why the
  rest did not; filter and search the rules, each with its expression and the
  cells it read; and see any table of the return on its template grid, laid out
  from the taxonomy pack, with cells the sheet does not accept hatched and every
  cell a broken rule read outlined. Listens on `127.0.0.1` only — there is no
  option to listen on a network, which plain HTTP would expose — and answers
  only the browser holding the session token the command prints. Dark by
  default, with a light theme. Guide: `docs/rwa-filer/dash.md`.
- `rwa-filer dash` — Build & sign off: draft cell overrides from the template
  grid, each with its reason and checked as a batch when it is made; see the
  return validated with them; build the package with the options
  `rwa-filer build` takes (byte-identical to the command's build); sign it off
  and verify it; follow the audit ledger; download the files the build wrote.
- `rwa-filer dash` — Compare: this return beside another version, cell by cell
  (`rwa-filer diff`'s counts) and rule by rule (fixed, newly broken, blocking
  findings before and after). Referee: Arelle's verdict on an instance the
  return has, run in the background with its progress shown, set beside the
  native engine's rule by rule. Taxonomies & rules: every packaged pack and rule
  book, each module's tables, and its enforced rules, searchable.
- `referee.report.verdict_line` (was private): the run's verdict in one line.
- `workflow.acts` — `record_build`, `record_signoff`, `verify_filing`: the
  build, sign-off and verify bookkeeping, shared by the command line and the
  dashboard so the two cannot record the same act differently.
- `workflow.signoff.check_signoff`: the sign-off preconditions, without
  recording anything.
- `boe.engine.CellAddress` and `Failure.addresses`: each failing evaluation now
  records where the cells it read are (table, sheet, open-axis key, row,
  column), up to `MAX_ADDRESSES`, and whether each was reported or read at its
  default. `Failure.cells` still describes them in words.
- `readers.open_source` and `readers.HeaderFields`: read a file the way
  `rwa-filer validate` does — check it exists and is supported, require a
  header for a fact table, apply any header field given over the file's own.
  The command line and the dashboard share it.
- `rwa_filer.extras.MissingExtraError`, raised by everything that opens a
  workbook when openpyxl (the `excel` extra) is not installed. It is a
  `ModuleNotFoundError`, so code that catches that keeps working.

### Fixed
- A command that needs the `excel` extra, run without it, now prints one line
  on stderr and exits 1, as any other refusal does. Before, it ended in a
  Python traceback with the useful message on its last line. This covers
  `validate`, `build` and `diff` given an `.xlsx`, `template`,
  `taxonomy compile`, `rulebook import` / `check` and `rules import` / `check`.
  The message is now the same wherever a workbook is opened.
  `rulebook import` / `check` used to fail with Python's bare
  `No module named 'openpyxl'`, and `taxonomy compile` still gave
  `pip install`. Each one now names the command to run:
  `uvx "rwa-filer[excel]@latest" <command> ...`, or
  `uv add "rwa-filer[excel]"` in a project.
- **`taxonomy compile`, `rules import` / `check` and `rulebook import` / `check`
  report an input they refuse in one line, not a traceback.** Each now ends as
  every other refusal does: one `rwa-filer: ...` line on stderr saying what is
  wrong with which file, and exit 1.
  - `taxonomy compile` given a `--module` that the workbook's Table of Contents
    does not list, or that the taxonomy package has no entry point for, names
    the module.
  - Given a `--dictionary` that is not a DPM dictionary, it names the sheets
    that are missing.
  - `rules import` / `check` given a workbook that is not laid out as the
    `--publisher`'s rule workbook used to fail with `KeyError`, `StopIteration`
    or `IndexError`. That covers another publisher's workbook, an empty rule
    sheet, or one narrower than the columns a rule is read from. It now names
    the sheet it looked for and what it found there.
  - `rulebook import` / `check` given a workbook whose data sheet is empty now
    report the required columns it lacks.
- A file that is not what the command reads now ends in one line on stderr
  that names it, and exit 1:
  `rwa-filer: annotated.xlsx is not a readable .xlsx workbook`. Before,
  `validate`, `build` and `diff` given such an `.xlsx`, `rules import` /
  `check`, `rulebook import` / `check` and `taxonomy compile` ended in a
  traceback: `zipfile.BadZipFile: File is not a zip file` for a file that is
  not a zip, `InvalidFileException` for a `.csv`, `KeyError` for a zip that
  holds no workbook. The same now holds for a `--taxonomy` or
  `--taxonomy-package` that is not a zip, and for a taxonomy package with a
  linkbase that is not well-formed XML. `taxonomy compile` takes three
  inputs, and the message is what says which one is wrong. Called as a
  library, `read_workbook`, `compile_pack`, `boe.importer.import_workbook` and
  `rules.importer.extract` raise a `ValueError` naming the file in place of
  those exceptions.
- An output option naming a path that writing would certainly fail on is
  refused in one line before the command does any work, and the file in the
  way is left alone. That is an existing file where a directory is written
  (`build`, `taxonomy compile` and `rulebook import --out`), a directory where
  a file is (`template` and `rules import --out`, `validate --report`,
  `build --ledger`), or a path beneath a file. Before, it ended in
  `FileExistsError` or `IsADirectoryError`, for `taxonomy compile` only once
  the whole compile had run.
- `rwa-filer signoff` recorded a sign-off entry in the audit ledger before
  checking that the sign-off would be given, so a refused sign-off (for
  example, a not-submittable package without `--acknowledge-findings`) left
  the ledger claiming an approval that never happened. The checks now run
  first, and a refused sign-off records nothing.

### Changed
- Starlette, uvicorn, Jinja2 and python-multipart are now dependencies, for the
  dashboard. They are required rather than an extra so that `uvx rwa-filer dash`
  works as typed; nothing outside `rwa_filer.dash` imports them.
- The README runs the command with `uvx rwa-filer@latest`, in place of
  `pip install rwa-filer`. `@latest` makes each run check PyPI and use the
  newest release, so a return is checked with the newest rules and taxonomy
  without anyone having to notice that a release came out; a bare
  `uvx rwa-filer` can keep running an older copy, including one installed with
  `uv tool install`. Each example names the extra it needs
  (`uvx "rwa-filer[excel]@latest" template ...`). `uv add rwa-filer` remains for
  use as a library, and `uv tool install rwa-filer` (with `uv tool upgrade`) for
  a machine that has to run it offline.
- The messages shown when the `excel` or `arelle` extra is missing give the uv
  commands (`uvx "rwa-filer[excel]@latest" ...`, or `uv add "rwa-filer[excel]"`
  in a project) in place of `pip install`, which has no lasting environment to
  install into when the command was run with `uvx`.
- The package metadata now carries a `Documentation` link, so the PyPI page
  points to the rwa-filer docs
  (<https://openafterhours.github.io/rwa_calculator/rwa-filer/>), and the README
  links to them too.

---

## [0.1.0] - 2026-11-14

### Added
- Package scaffold: the `rwa_filer` import package, the `rwa-filer` command
  (`--version`, `--help`) and an isolated test suite that runs with `rwa-calc`
  absent.
- `rwa_filer.rules` — the published supervisory validation rules as package
  data (EBA DPM 3.0(3.0.1) for CRR: 1,011 rules, 741 enforced; BoE
  banking_reporting v4.1.1 for Basel 3.1: 816 rules, 800 enforced), normalised
  onto one `ValidationRule` shape by `load_rules(framework)`.
- `rwa_filer.validate` — the rule engine, moved here unchanged from
  `rwa_calc.reporting.validations`. `TemplateIndex` is the one shape a return is
  read through (frames, table bindings and sheet-code maps, all supplied by the
  source of the figures); `evaluate_index` returns one outcome per enforced rule
  (`PASS` / `FAIL` / `VACUOUS` / `NOT_EVALUATED`) and `check_index` returns
  `Finding` records: `VAL001` (Error-severity rule broken), `VAL002`
  (Warning-severity) and `VAL003` (coverage insufficient, so an empty result is
  never mistaken for a clean one).
- `rwa_filer.rules.importer` and the `rwa-filer rules list | import | check`
  commands — rebuild an extract from a publisher's rule workbook, or fail if
  the packaged one is not exactly what the workbook yields. Reading a workbook
  needs the new `rwa-filer[excel]` extra (openpyxl); validation does not.
- `rwa_filer.taxonomy` — taxonomy packs: the tables, reportable cells and data
  points of a reporting module, as package data. Ships `PRA001` for the Bank of
  England banking taxonomy v4.1.1 (applies from 1 January 2027): 104 tables,
  61,615 reportable cells, 61,428 data points, 83 filing indicators.
  `resolve_pack(module, reference_date)` selects the version in force; a date
  no pack covers raises `PackNotFoundError` and never falls back.
  `rwa-filer taxonomy list | compile` — the compiler builds a pack from the
  Bank's annotated templates, DPM dictionary and taxonomy package, and is
  byte-reproducible.
- `rwa_filer.model` — the canonical return: a `ReturnHeader` (entity, reference
  date, module, currency) and one fact per reported cell (`table`, `sheet`,
  `open_key`, `row`, `column`, `value`, `text_value`).
- `rwa_filer.validate.structure` — structure checks `STR001`–`STR009`: every
  fact sits in a table, sheet, open-axis member and cell the taxonomy accepts,
  is of the cell's type, is reported once, and agrees with any other cell that
  reports the same data point; every row of an open-row table has a key of the
  right type that no other row repeats; the header carries a checksum-valid LEI.
- `rwa_filer.validate.returns.validate_return` — structure, then the published
  rules, in one pass over a canonical return.
- `rwa_filer.readers` — read a return from Parquet, CSV or an Excel workbook in
  the template layout.
- `rwa-filer validate FILE` (text or JSON output, exit code `1` when anything
  blocks submission) and `rwa-filer template` (a blank workbook for a module,
  with the cells the taxonomy does not accept shaded grey).
- `rwa_filer.xbrl.writer.write_instance` — a structurally clean return as an
  XBRL 2.1 instance that follows the Bank of England XBRL Filing Manual: one
  fact per data point, dimensions in the scenario, open-axis members and
  open-row keys filled in, a dimension's default member never written, no
  unused context, unit or namespace prefix, `decimals` on every number. The
  output is deterministic. Monetary `decimals` defaults to `-3`, the convention
  of the Bank's own samples.
- `rwa_filer.xbrl.reader.read_instance` — an XBRL instance (or a zip holding
  one) from any system back into the canonical return, by the taxonomy its own
  `schemaRef` names. Findings `XBR001` (a fact that is no data point of the
  module), `XBR002` (a fact only unreported templates show) and `XBR003` (a
  Filing Manual breach visible without the taxonomy). A document type
  declaration is refused.
- `rwa_filer.filing.build_filing` and `rwa-filer build FILE --out DIR` —
  validate, then write the instance, a zip where the Filing Manual requires one
  (over 10 MB), and a manifest with checksums and the validation result.
  Nothing is written while a structure finding stands, or — without `--force` —
  while a rule check fails.
- The canonical fact table gains an optional `decimals` column, and a return
  may declare its filing indicators. `STR010` reports a declared indicator the
  module lacks, or a fact in a template not declared as reported.
- `rwa_filer.boe` — the Bank of England's validation rules, evaluated as the
  taxonomy evaluates them.
  - Rule books for taxonomy v4.1.1 as package data: all 3,813 rules of all 11
    return families (24 modules), imported from the Bank's workbooks by header
    name. `rwa-filer rulebook list | import | check`.
  - A parser for the rule language as published (the raw `Expression`, `Scope`,
    `Join` and `Where` cells): conditionals, `and` / `or` / `not`, interval and
    exact operators, per-reference defaults, sequence references, filters,
    enumeration and boolean cells, `isNull`, `count`, `matches`, `exp`, `log`.
    Every one of the 3,810 complete expressions parses; the other three are
    cells the publisher's export cut at the spreadsheet limit, none enforced.
  - An engine with the taxonomy's semantics: a rule runs only when every
    template it reads is reported; it runs once per combination of cells it
    leaves open; an unreported cell is what its own reference says it is;
    interval comparisons allow for rounding by each fact's `decimals`; a figure
    shown in two cells is one fact. No enforced rule of a packaged module is
    unsupported, and a register test keeps it so.
  - Checked against Arelle on the Bank's own sample instances, counting
    satisfied and unsatisfied evaluations per rule: every one of the 1,441
    rules PRA001 enforces, on a carve of all 104 of its tables, and all 254
    rules of twelve further modules on their whole samples. The counts are
    fixtures in the suite, with the two measured Arelle behaviours they allow
    for stated beside them.
  - Formula reach (`rwa_filer.boe.formulas`): `rwa-filer rulebook import
    --taxonomy-package ZIP` also reads each rule's XBRL formula and records
    which dimensions it fixes to "not applicable". A rule whose formula closes
    a dimension its own cells carry cannot fire at the gateway and is not
    evaluated here either (`closed_by_formula`). In v4.1.1 that is seven PRA001
    rules on table OF 91.01, held in a two-way register test. The packaged rule
    books are built with the taxonomy package.
  - Codes listed inside a reference range over that reference alone, as the
    formula's per-variable filters do; codes listed in the scope are shared.
  - A rule that names one member of an open axis (the all-countries total,
    say) reads its other references across every member: a sequence reference
    takes all of them at once, a single-cell reference ranges over them by
    itself. Found by the referee on a return generated by `rwa-calc`: the
    engine had been summing one country at a time.
- `rwa_filer.referee` and `rwa-filer referee INSTANCE --taxonomy-package ZIP` —
  a second opinion from the Arelle XBRL processor on a written instance:
  validity, filing rules, a verdict on every rule its templates trigger, and a
  rule-by-rule differential against the native engine
  (`rwa_filer.referee.differential.compare`). Arelle is optional
  (`rwa-filer[arelle]`, or its own environment named by
  `RWA_FILER_ARELLE_PYTHON`) and runs as a subprocess, in memory-bounded
  workers over a trimmed entry point. A worker names no file: the runner hands
  it its spec on standard input and takes its result from standard output,
  and whatever Arelle prints during the session goes to the worker's log. A worker that is killed, or that returns
  no verdict for a rule, makes the run incomplete, and an incomplete run is
  never reported as agreement. The referee loads Arelle's math-functions
  plug-in and repairs its `matchAny` match filter; both are named in every
  result.
- `rwa_filer.workflow` — the preparer's workflow.
  - Adjustments: cell-level overrides read from a file with a `reason` per
    row, applied whole or not at all, with the before and after of each cell
    recorded in the manifest (`rwa-filer build --adjustments FILE --author NAME`).
  - An append-only, hash-chained audit ledger (`<name>.ledger.jsonl`) of
    adjustments, builds and sign-offs. Altering, removing or re-ordering an
    entry is detected; a ledger that does not verify is never extended.
  - `rwa-filer signoff`: an approval bound to the SHA-256 of the instance.
    A package that is not submittable is signed only with
    `--acknowledge-findings`.
  - `rwa-filer verify`: the instance, zip, manifest, sign-off and ledger must
    all describe the same bytes.
  - `rwa-filer diff PREVIOUS CURRENT`: the cells added, removed and changed
    between two versions of a return, across file formats.
- Taxonomy packs for thirteen more modules: `PRA116`, `PRA112`–`PRA114`,
  `PRA117`, `PRA118`, `LVR001`, `LVR002`, `MRL001`, `MRL003`, `PRA_IFRS`,
  `PRA_GAAP`, `PRA_MEM`. For each, every fact of the Bank's sample instance is
  a data point of the pack, and rewriting the sample reproduces it exactly.
  `PRA110`, `PRA115` and `RFB001`–`RFB008` are not packaged: their compiled
  packs do not yet account for every sample fact.

### Changed
- `validate_return` and `rwa-filer validate` / `build` now run the v4.1.1 rule
  books through the new engine. Verdicts change, and are stricter: an
  unreported cell is zero to a rule that says so, where the earlier engine
  skipped the rule. The report lists `satisfied` and `unsatisfied` evaluation
  counts per rule; the `VACUOUS` status is gone. `validate_return` takes
  `rulebook=` (a `rwa_filer.boe.catalogue.RuleBook`) in place of `ruleset=`,
  and `accuracy=` for the default `decimals`.
- Row, column and sheet codes are matched as each table writes them: most
  tables use four digits, the MREL and older tables three. A code that differs
  from one of its table's only in leading zeros is taken as that code.
- The template-level engine (`TemplateIndex`, `check_index`, the EBA and BoE
  template-level extracts) is unchanged and remains what `rwa-calc` runs on its own
  frames.

### Fixed
- **A same-sheet reference to a sheet the referenced table does not carry is
  skipped, not widened.** In the template-level engine (`rwa_filer.validate`), a
  rule evaluated on one sheet that sums another table's column without naming a
  sheet reads that table on the same sheet; where the table did not carry it,
  the engine summed every one of its sheets instead. It now reports the
  reference as `sheet_not_emitted`. A coordinate with no sheet on that axis
  still spans every sheet.
- **A fact is read in every reported table that shows its data point.** The
  taxonomy shows some data points in two tables (the A-IRB total is a row of
  OF 02.00 and the total of an OF 08.01 sheet), and such a figure is one fact
  wherever it is shown. `rwa_filer.boe` read it only in the cell the return
  named, so on a return built cell by cell a rule comparing the two cells
  failed against the reference's default of zero — while the same return read
  back from its XBRL file passed, as it does in Arelle. A return and the same
  return read back from its file now get the same verdict. A cell the return
  names itself is never overwritten (two values for one data point remains
  `STR007`), and a table that is not reported gains nothing.

---
