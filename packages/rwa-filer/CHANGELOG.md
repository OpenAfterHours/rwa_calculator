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

### Changed
- (Next release changes will go here)

---
