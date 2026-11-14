# Changelog

All notable changes to `rwa-filer` are recorded here. The package is versioned
and released independently of `rwa-calc`; its release tags are prefixed
`rwa-filer-v`.

## [Unreleased]

### Added
- Package scaffold: the `rwa_filer` import package, the `rwa-filer` command
  (`--version`, `--help`) and an isolated test suite that runs with `rwa-calc`
  absent.
- `rwa_filer.rules` — the published supervisory validation rules as package
  data (EBA DPM 3.0(3.0.1) for CRR: 1,011 rules, 741 enforced; BoE
  banking_reporting v4.0.0 for Basel 3.1: 820 rules, 808 enforced), normalised
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
  workers over a trimmed entry point. A worker that is killed, or that returns
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
- (Next release changes will go here)
- The referee's worker process takes its spec on standard input and writes its
  result to a fixed name (`worker.RESULT_FILE`) in the working directory the
  runner starts it in. No path reaches it from its command line or from the
  spec, which clears SonarCloud's `pythonsecurity:S8707` and `S2083` findings on
  `referee/worker.py`. A hand-run worker is now `python -I worker.py < SPEC.json`.
  The files a run leaves in its workdir are unchanged.
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
  v4.0.0 extracts) is unchanged and remains what `rwa-calc` runs on its own
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
