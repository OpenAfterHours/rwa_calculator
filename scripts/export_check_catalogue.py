"""
Export the check catalogue — every check the calculator runs, and the evidence behind it.

Pipeline position:
    (not a pipeline stage) — a read-only report over the code, written as one
    Excel workbook a reviewer can sort and filter:

        uv run python scripts/export_check_catalogue.py   # -> dist/check-catalogue.xlsx

Key responsibilities:
- Read every check from the place the code keeps it, at generation time, so the
  workbook is a view of the code and never a second copy of it:
  - the error and warning codes declared anywhere under ``src/rwa_calc``, with
    the comment the code carries for each, the severities its raise sites set,
    and the modules that use it;
  - every input column's declared type, requiredness and admissible domain
    (``data/schemas.py::TABLE_SCHEMAS``), with the code a violation publishes;
  - the published supervisory rules: the EBA (CRR) and BoE (Basel 3.1)
    template-level extracts ``validate_submission`` runs, and the Bank's PRA001
    rule book the filing package runs;
  - the cross-template tie-outs, and the template pairs deliberately not tied;
  - the independent evidence in the test estate: the hand-derived oracle, the
    classification decision table, the cell re-derivations, the invariant
    tests, the per-article coverage join and an inventory of every test.
- State WHERE each runtime family runs, derived from the call sites found in
  ``src/rwa_calc`` — so a check that is defined but not wired into a production
  path says so in the workbook, and stops saying so the day it is wired.
- Put the banked coverage measures on the front sheet, each with the file it
  was read from, so a reader sees how much of the estate the checks can see.

Why generated: a hand-maintained list of checks is a list that drifts from the
checks. This file states no check of its own; the only prose it adds is the
heading text that says what each sheet's rows are. Re-run it and the workbook
is current.

What the workbook does NOT say. It lists what is checked, not what a check
found on your data — for that, run ``ResultExporter.validate_submission`` and
``export_validation_report`` on a calculation. And a check being listed is not
evidence that the check is right; the test-estate sheets and the coverage
measures are the evidence, and they say how far it goes.

The output path is fixed (``dist/``, git-ignored): ``arch_check`` check 19 bans
a command-line path argument in ``scripts/``. A caller that needs another
location imports :func:`export_check_catalogue` and passes one.

References:
- docs/development/check-catalogue.md — what each sheet holds and how to read it
- docs/plans/independent-validation-system.md — why the evidence layers exist
- docs/reference/validation-rules/index.md — the published rule extracts
- .claude/LESSONS.md C8 — a measurement and the claim attached to it are
  separate; the workbook states only what its sources record
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from xlsxwriter.workbook import Workbook
    from xlsxwriter.worksheet import Worksheet

# =============================================================================
# Constants
# =============================================================================

SRC_ROOT: Final = REPO_ROOT / "src" / "rwa_calc"
TESTS_ROOT: Final = REPO_ROOT / "tests"
FILER_TESTS_ROOT: Final = REPO_ROOT / "packages" / "rwa-filer" / "tests"

#: Where the workbook is written. Fixed, and git-ignored (``dist/`` and
#: ``*.xlsx`` are both in the root ``.gitignore``) — see the module docstring.
DEFAULT_OUTPUT: Final = REPO_ROOT / "dist" / "check-catalogue.xlsx"

ORACLE_VALUES: Final = TESTS_ROOT / "oracle" / "expected_values.json"
ORACLE_TEST: Final = TESTS_ROOT / "oracle" / "test_oracle.py"
CLASSIFICATION_TABLE: Final = TESTS_ROOT / "conformance" / "classification_table.toml"
CELL_REDERIVATION: Final = TESTS_ROOT / "conformance" / "cell_rederivation.toml"
PROPERTIES_DIR: Final = TESTS_ROOT / "properties"
CONFIDENCE_SNAPSHOT: Final = TESTS_ROOT / "contracts" / "data" / "confidence_snapshot.json"
VALIDATION_REGISTER: Final = (
    TESTS_ROOT / "expected_outputs" / "reporting" / "validation_known_breaks.json"
)
COVERAGE_BASELINE: Final = REPO_ROOT / "scripts" / "coverage_baseline.json"
FILING_MAPPING_BASELINE: Final = REPO_ROOT / "scripts" / "filing_mapping_baseline.json"
REFEREE_BASELINE: Final = REPO_ROOT / "scripts" / "referee_differential_baseline.json"
INJECTION_BASELINE: Final = REPO_ROOT / "scripts" / "injection_baseline.json"

#: An error code as the estate spells them: a 2-4 letter domain prefix and a
#: three-digit number (``DQ001``, ``CRM022``, ``SCP004``).
ERROR_CODE_PATTERN: Final = re.compile(r"^[A-Z]{2,4}\d{3}$")

#: The module that declares the estate's codes; every declaration there counts.
ERRORS_MODULE: Final = "contracts/errors.py"
#: A constant NAMED as a code (``CCR_WWR_SPECIFIC_ERROR_CODE``) counts too.
_CODE_CONSTANT_NAME: Final = re.compile(r"(ERROR|CODE)")

#: Excel's hard limits.
MAX_CELL_CHARS: Final = 32_767
MAX_SHEET_NAME: Final = 31
#: Kept well under the cell limit so the truncation marker always fits.
_TRUNCATE_AT: Final = 32_000

#: The validation register keys a regime as ``crr`` / ``b31``.
_REGISTER_REGIME: Final[dict[str, str]] = {"CRR": "crr", "BASEL_3_1": "b31"}

#: Directories under ``tests/`` that hold data or harness code, not tests.
_NOT_TEST_SUITES: Final = frozenset({"fixtures", "expected_outputs", "mutations"})

_RUNS_IN_TESTS: Final = "Test suite only. Runs under pytest in CI; it does not run on your data."


# =============================================================================
# Shapes
# =============================================================================


@dataclass(frozen=True)
class Column:
    """One column of a catalogue sheet.

    Attributes:
        header: Column heading, as written in the workbook.
        width: Excel column width, in characters.
        wrap: Wrap long text inside the cell.
    """

    header: str
    width: int = 18
    wrap: bool = False


@dataclass(frozen=True)
class Sheet:
    """One family of checks, ready to write as a worksheet.

    Attributes:
        name: Worksheet tab name (Excel caps it at 31 characters).
        what: What one row of the sheet is.
        runs: Where the family runs. For a runtime family this is derived from
            the call sites in ``src/rwa_calc``; it is never asserted.
        source: Where in the repository the rows were read from.
        columns: The sheet's columns, in order.
        rows: One tuple per row, aligned with ``columns``.
    """

    name: str
    what: str
    runs: str
    source: str
    columns: tuple[Column, ...]
    rows: tuple[tuple[object, ...], ...]


@dataclass(frozen=True)
class Measure:
    """One banked coverage measure, read from the file that banks it.

    Attributes:
        name: What is measured.
        value: The banked value, as read.
        meaning: How to read the value — including what it does NOT show.
        source: The file the value was read from.
    """

    name: str
    value: str
    meaning: str
    source: str


@dataclass(frozen=True)
class Catalogue:
    """The whole workbook: provenance, measures and one sheet per family."""

    generated_at: datetime
    versions: Mapping[str, str]
    commit: str
    pack_hashes: Mapping[str, str]
    measures: tuple[Measure, ...]
    sheets: tuple[Sheet, ...]


# =============================================================================
# Main entry point
# =============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """Build the catalogue and write it to :data:`DEFAULT_OUTPUT`."""
    parser = argparse.ArgumentParser(
        description=(
            "Export every check the calculator runs, read from the code, as an Excel "
            f"workbook at {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}."
        )
    )
    parser.parse_args(argv)

    catalogue = build_catalogue()
    path = export_check_catalogue(catalogue)
    print(f"check catalogue written: {path.relative_to(REPO_ROOT)}")
    for sheet in catalogue.sheets:
        print(f"  {sheet.name:<28} {len(sheet.rows):>6} rows")
    return 0


def build_catalogue() -> Catalogue:
    """Read every check family from the code and return the catalogue."""
    index = SourceIndex(SRC_ROOT)
    sheets = (
        error_code_sheet(index),
        input_column_sheet(index),
        template_rule_sheet(index, "CRR"),
        template_rule_sheet(index, "BASEL_3_1"),
        filing_rule_sheet(index),
        tie_out_sheet(index),
        oracle_sheet(),
        classification_sheet(),
        cell_rederivation_sheet(),
        invariant_test_sheet(),
        article_coverage_sheet(),
        test_inventory_sheet(),
    )
    return Catalogue(
        generated_at=datetime.now(UTC).replace(microsecond=0),
        versions={name: _distribution_version(name) for name in ("rwa-calc", "rwa-filer")},
        commit=_git_commit(),
        pack_hashes=_pack_hashes(),
        measures=coverage_measures(),
        sheets=sheets,
    )


def export_check_catalogue(catalogue: Catalogue, path: Path = DEFAULT_OUTPUT) -> Path:
    """Write ``catalogue`` as an .xlsx workbook at ``path`` and return the path."""
    import xlsxwriter

    path.parent.mkdir(parents=True, exist_ok=True)
    # Formula and URL conversion are OFF: a rule expression such as
    # "{r0010, c0010} = ..." would otherwise be written as a broken formula.
    workbook = xlsxwriter.Workbook(
        str(path),
        {"strings_to_formulas": False, "strings_to_urls": False, "strings_to_numbers": False},
    )
    workbook.set_properties(
        {
            "title": "RWA calculator — check catalogue",
            "subject": "Every check the calculator runs, read from the code",
            "created": catalogue.generated_at.replace(tzinfo=None),
        }
    )
    formats = _Formats(workbook)
    _write_read_me(workbook.add_worksheet("Read me"), catalogue, formats)
    for sheet in catalogue.sheets:
        _write_sheet(workbook.add_worksheet(sheet.name[:MAX_SHEET_NAME]), sheet, formats)
    workbook.close()
    return path


# =============================================================================
# Runtime check families
# =============================================================================


def error_code_sheet(index: SourceIndex) -> Sheet:
    """Every error / warning code declared under ``src/rwa_calc``.

    A code is a module-level string constant spelled like one
    (:data:`ERROR_CODE_PATTERN`) that ``contracts/errors.py`` declares, that a
    raise site passes as ``code=``, or whose name says it is one. Its
    description is the comment block the code carries above the declaration;
    its severity and category are the ones its raise sites state literally.
    Whether it is raised at all is read from the code too — see
    :meth:`SourceIndex.raise_status`. Nothing here is typed by hand.
    """
    from rwa_calc.api.errors import ERROR_MESSAGE_OVERRIDES

    raise_sites = index.raise_sites()
    rows = []
    for decl in sorted(index.error_codes, key=lambda d: (_code_prefix(d.code), d.code)):
        sites = raise_sites.get(decl.code, _RaiseSites())
        used_in = index.references(decl)
        rows.append(
            (
                decl.code,
                _code_prefix(decl.code),
                decl.group,
                decl.description,
                ERROR_MESSAGE_OVERRIDES.get(decl.code, ""),
                ", ".join(sorted(sites.severities)),
                ", ".join(sorted(sites.categories)),
                index.raise_status(decl),
                "; ".join(sorted(used_in)),
                decl.constant,
                f"{decl.module}:{decl.line}",
            )
        )
    return Sheet(
        name="Error codes",
        what=(
            "One row per error or warning code the calculator declares. A raised code is "
            "added to the run's error list; it never stops the run."
        ),
        runs=(
            "During a calculation, at the stage that owns the code ('Raised in' says "
            "where, or that nothing raises it). Severity and category are read from raise "
            "sites that state them literally; a blank means they are set at run time."
        ),
        source="Module-level code constants under src/rwa_calc (chiefly contracts/errors.py)",
        columns=(
            Column("Code", 9),
            Column("Prefix", 7),
            Column("Group", 30, wrap=True),
            Column("Description (from the code's own comment)", 80, wrap=True),
            Column("Message shown by the API", 40, wrap=True),
            Column("Severity", 10),
            Column("Category", 16),
            Column("Raised in", 50, wrap=True),
            Column("Referenced in", 45, wrap=True),
            Column("Constant", 38),
            Column("Declared at", 38),
        ),
        rows=tuple(rows),
    )


def input_column_sheet(index: SourceIndex) -> Sheet:
    """Every input column: type, requiredness, and the domain the input gate checks."""
    from rwa_calc.contracts.errors import ERROR_INVALID_COLUMN_VALUE

    # The gate's own (column -> code, severity) mapping. Private, and imported
    # rather than restated, because a restated mapping is one that drifts.
    from rwa_calc.contracts.validation import _reporting_for
    from rwa_calc.data.schemas import COLUMN_VALUE_CONSTRAINTS, TABLE_SCHEMAS

    severities = index.raise_sites().get(ERROR_INVALID_COLUMN_VALUE, _RaiseSites()).severities
    categorical_severity = ", ".join(sorted(severities))
    rows = []
    for table, schema in TABLE_SCHEMAS.items():
        allowed_by_column = COLUMN_VALUE_CONSTRAINTS.get(table, {})
        for column, spec in schema.items():
            domain = spec.domain
            domain_text = domain.describe() if domain is not None else ""
            basis = domain.reason if domain is not None else ""
            domain_code = ""
            if domain is not None:
                code, severity = _reporting_for(column)
                domain_code = f"{code} ({severity.value})"
            allowed = allowed_by_column.get(column)
            rows.append(
                (
                    table,
                    column,
                    str(spec.dtype),
                    "Required" if spec.required else "Optional",
                    "" if spec.required or spec.default is None else repr(spec.default),
                    domain_text,
                    basis,
                    domain_code,
                    ", ".join(sorted(allowed)) if allowed else "",
                    (f"{ERROR_INVALID_COLUMN_VALUE} ({categorical_severity})" if allowed else ""),
                )
            )
    return Sheet(
        name="Input columns",
        what=(
            "One row per column of every input table: its type, whether it must be "
            "supplied, and the values the input gate accepts."
        ),
        runs=_runs_at(index, "validate_bundle_values"),
        source="src/rwa_calc/data/schemas.py (TABLE_SCHEMAS, COLUMN_VALUE_CONSTRAINTS)",
        columns=(
            Column("Table", 22),
            Column("Column", 34),
            Column("Type", 14),
            Column("Required", 10),
            Column("Default if absent", 16),
            Column("Declared domain", 30, wrap=True),
            Column("Basis for the domain", 80, wrap=True),
            Column("Code if outside the domain", 18),
            Column("Allowed values (categorical check)", 50, wrap=True),
            Column("Code if not an allowed value", 18),
        ),
        rows=tuple(rows),
    )


def template_rule_sheet(index: SourceIndex, framework: str) -> Sheet:
    """The published template-level rules ``validate_submission`` runs for ``framework``."""
    from rwa_filer.rules import EXTRACT_FILES, is_currently_enforced, load_rules

    parked = _parked_rule_notes(framework)
    rule_set = load_rules(framework)
    rows = []
    for rule in rule_set.rules:
        rows.append(
            (
                rule.rule_id,
                rule.publisher,
                rule.severity,
                "Yes" if is_currently_enforced(rule) else "No",
                _describe_status(rule.status, rule.reactivated_on),
                rule.rule_type,
                ", ".join(rule.tables),
                rule.expression or "",
                _describe_table_scopes(rule.table_scopes),
                ", ".join(rule.prerequisites),
                rule.missing_value,
                rule.label or "",
                parked.get(rule.rule_id, ""),
            )
        )
    label = "CRR" if framework == "CRR" else "Basel 3.1"
    return Sheet(
        name=f"Template rules - {label}",
        what=(
            f"One row per published {label} validation rule in the credit-risk extract. "
            "'Enforced' rules run; an ERROR-severity break means the supervisor would "
            "reject the return."
        ),
        runs=_runs_at(index, "evaluate_all", "check_supervisory_validations"),
        source=f"packages/rwa-filer/src/rwa_filer/rules/data/{EXTRACT_FILES[framework]}",
        columns=(
            Column("Rule", 16),
            Column("Publisher", 9),
            Column("Severity", 9),
            Column("Enforced", 9),
            Column("Status", 14),
            Column("Rule type", 11),
            Column("Tables", 22, wrap=True),
            Column("Expression", 70, wrap=True),
            Column("Scope (rows / columns / sheets)", 40, wrap=True),
            Column("Prerequisites", 18, wrap=True),
            Column("If value missing", 12),
            Column("Publisher's description", 50, wrap=True),
            Column("Parked in our test register", 60, wrap=True),
        ),
        rows=tuple(rows),
    )


def filing_rule_sheet(index: SourceIndex) -> Sheet:
    """The Bank's rules the gateway runs on a PRA001 return — the filing package's check."""
    from rwa_calc.reporting.filing.canonical import FILING_MODULE
    from rwa_filer.boe.catalogue import rulebook_for_module

    rulebook = rulebook_for_module(FILING_MODULE)
    rows = []
    for rule in rulebook.enforced(FILING_MODULE):
        parse_error = rule.parse_error
        rows.append(
            (
                rule.rule_id,
                rule.severity(FILING_MODULE),
                ", ".join(rule.tables),
                rule.expression,
                rule.scope or "",
                rule.where or "",
                rule.join or "",
                "Yes" if rule.always_execute else "No",
                rule.label or "",
                "Yes" if parse_error is None else f"No — {parse_error}",
            )
        )
    return Sheet(
        name=f"Filing rules - {FILING_MODULE}",
        what=(
            f"One row per rule the Bank's gateway runs on a {FILING_MODULE} return "
            f"(rule book {rulebook.framework_version} {rulebook.taxonomy}). A rule runs "
            "only when every table it reads is in the return."
        ),
        runs=_runs_at(index, "build_filing_package"),
        source=f"packages/rwa-filer/src/rwa_filer/boe/data ({rulebook.framework_version})",
        columns=(
            Column("Rule", 16),
            Column("Severity", 9),
            Column("Tables", 22, wrap=True),
            Column("Expression", 70, wrap=True),
            Column("Scope", 40, wrap=True),
            Column("Where", 24, wrap=True),
            Column("Join", 24, wrap=True),
            Column("Runs even if unreported", 12),
            Column("Bank's description", 50, wrap=True),
            Column("Readable by our engine", 30, wrap=True),
        ),
        rows=tuple(rows),
    )


def tie_out_sheet(index: SourceIndex) -> Sheet:
    """The in-house cross-template identities, and the pairs deliberately not tied."""
    from rwa_calc.reporting.tieouts import NON_COMPARABLE_PAIRS, TIE_OUTS

    rows: list[tuple[object, ...]] = [
        (
            "Tie-out (checked)",
            tie.name,
            ", ".join(tie.templates),
            ", ".join(tie.frameworks),
            tie.description,
            tie.lhs_label,
            tie.rhs_label,
            f"rtol {tie.rtol:g}, atol {tie.atol:g}",
            tie.regulatory_reference,
        )
        for tie in TIE_OUTS
    ]
    rows.extend(
        (
            "Not comparable (deliberately not tied)",
            "",
            ", ".join(pair.pair),
            "",
            pair.reason,
            "",
            "",
            "",
            pair.regulatory_reference,
        )
        for pair in NON_COMPARABLE_PAIRS
    )
    return Sheet(
        name="Tie-outs",
        what=(
            "One row per identity that must hold between two generated templates, plus "
            "the template pairs recorded as NOT comparable and why."
        ),
        runs=_runs_at(index, "check_cross_template_consistency"),
        source="src/rwa_calc/reporting/tieouts.py (TIE_OUTS, NON_COMPARABLE_PAIRS)",
        columns=(
            Column("Kind", 22, wrap=True),
            Column("Name", 30),
            Column("Templates", 22, wrap=True),
            Column("Frameworks", 16),
            Column("Identity / reason", 80, wrap=True),
            Column("Left side", 40, wrap=True),
            Column("Right side", 40, wrap=True),
            Column("Tolerance", 20),
            Column("Reference", 50, wrap=True),
        ),
        rows=tuple(rows),
    )


# =============================================================================
# Test-estate evidence
# =============================================================================


def oracle_sheet() -> Sheet:
    """The hand-derived oracle: expected values written from the regulation, not the engine."""
    payload = json.loads(ORACLE_VALUES.read_text(encoding="utf-8"))
    disagreements = _oracle_disagreements()
    rows = []
    for case in payload["oracles"]:
        case_id = case["exposure_id"]
        reason = disagreements.get(case_id)
        status = (
            "Asserted: the test fails if the engine differs"
            if reason is None
            else f"Known disagreement (strict xfail): {reason}"
        )
        rows.append(
            (
                case_id,
                case.get("phase", ""),
                case.get("framework", ""),
                case.get("approach", ""),
                case.get("exposure_class", ""),
                case.get("regulation", ""),
                _key_values(case.get("inputs", {})),
                _key_values(case.get("expected", {})),
                status,
            )
        )
    return Sheet(
        name="Oracle cases",
        what=(
            "One row per independently hand-derived case. The expected values come from "
            "the regulation's text through a stdlib-only calculator that may not import "
            "the engine; the engine must reproduce them within "
            f"relative error {payload.get('tolerance_relative', '')}."
        ),
        runs=_RUNS_IN_TESTS + " Test: tests/oracle/test_oracle.py.",
        source=(
            "tests/oracle/expected_values.json (hash-locked to ORACLE_DERIVATIONS.md); "
            "KNOWN_DISAGREEMENTS in tests/oracle/test_oracle.py"
        ),
        columns=(
            Column("Case", 10),
            Column("Phase", 7),
            Column("Regime", 11),
            Column("Approach", 10),
            Column("Exposure class", 24),
            Column("Regulation", 40, wrap=True),
            Column("Inputs", 60, wrap=True),
            Column("Expected values", 50, wrap=True),
            Column("Status", 60, wrap=True),
        ),
        rows=tuple(rows),
    )


def classification_sheet() -> Sheet:
    """The classification decision table, authored from the article text."""
    from tests.conformance.table import _RULE_SECTION

    table = tomllib.loads(CLASSIFICATION_TABLE.read_text(encoding="utf-8"))
    field_for_section = {section: name for name, section in _RULE_SECTION.items()}
    rows: list[tuple[object, ...]] = []
    for section, field_name in field_for_section.items():
        for order, rule in enumerate(table.get(section, []), start=1):
            rows.append(
                (
                    "Rule (first match wins)",
                    field_name,
                    order,
                    rule.get("id", ""),
                    _describe_when(rule.get("when", {})),
                    rule.get("verdict", ""),
                    rule.get("sourcing", ""),
                    rule.get("citation", ""),
                    _clean_text(rule.get("note", "")),
                )
            )
    for exclusion in table.get("exclusion", []):
        rows.append(
            (
                "Exclusion (input not admitted)",
                "",
                "",
                exclusion.get("id", ""),
                _describe_when(exclusion.get("when", {})),
                "",
                "",
                exclusion.get("citation", ""),
                _clean_text(exclusion.get("reason", "")),
            )
        )
    for known in table.get("known_disagreement", []):
        rows.append(
            (
                "Known disagreement (parked)",
                known.get("field", ""),
                "",
                known.get("id", ""),
                _describe_when(known.get("when", {})),
                f"expected {known.get('expected', '')}; engine gives {known.get('observed', '')}",
                "",
                known.get("citation", ""),
                _clean_text(known.get("detail", "")),
            )
        )
    return Sheet(
        name="Classification table",
        what=(
            "One row per rule of the exposure-class and approach decision table. Every "
            "generated combination of inputs must match a rule; a combination with no "
            "rule is a test failure, not a default."
        ),
        runs=_RUNS_IN_TESTS + " Test: tests/conformance/test_classification_conformance.py.",
        source="tests/conformance/classification_table.toml",
        columns=(
            Column("Kind", 22, wrap=True),
            Column("Field asserted", 20),
            Column("Order", 7),
            Column("ID", 34, wrap=True),
            Column("When", 50, wrap=True),
            Column("Verdict", 30, wrap=True),
            Column("Sourcing", 11),
            Column("Citation", 36, wrap=True),
            Column("Note", 80, wrap=True),
        ),
        rows=tuple(rows),
    )


def cell_rederivation_sheet() -> Sheet:
    """Template money cells re-derived from the instruction text, separately from the generator."""
    table = tomllib.loads(CELL_REDERIVATION.read_text(encoding="utf-8"))
    rows = [
        (
            cell.get("id", ""),
            cell.get("template", ""),
            cell.get("member", ""),
            cell.get("row", ""),
            cell.get("column", ""),
            ", ".join(cell.get("regimes", [])),
            _describe_carrier(cell),
            _describe_where(cell.get("where", [])),
            cell.get("citation", ""),
            _clean_text(cell.get("note", "")),
            _clean_text(cell.get("basis", "")),
            _clean_text(cell.get("known_difference", "")),
        )
        for cell in table.get("cell", [])
    ]
    return Sheet(
        name="Cell re-derivations",
        what=(
            "One row per template money cell rebuilt from the published instructions by "
            "a second, separately written rule. The generated cell must equal it."
        ),
        runs=_RUNS_IN_TESTS + " Test: tests/conformance/test_cell_rederivation.py.",
        source="tests/conformance/cell_rederivation.toml",
        columns=(
            Column("ID", 22),
            Column("Template", 10),
            Column("Sheet", 18),
            Column("Row", 7),
            Column("Column", 8),
            Column("Regimes", 10),
            Column("Metric", 34, wrap=True),
            Column("Rows included", 50, wrap=True),
            Column("Citation", 36, wrap=True),
            Column("Instruction text", 70, wrap=True),
            Column("What this does not settle", 50, wrap=True),
            Column("Known difference", 50, wrap=True),
        ),
        rows=tuple(rows),
    )


def invariant_test_sheet() -> Sheet:
    """The regulation-derived properties that must hold for any portfolio."""
    rows = [
        (
            test.module_summary,
            test.name,
            test.summary,
            ", ".join(test.markers),
            test.location,
        )
        for test in _collect_tests(PROPERTIES_DIR)
    ]
    return Sheet(
        name="Invariant tests",
        what=(
            "One row per property test: conservation, monotonicity, homogeneity, "
            "output-floor identities and structural bounds that must hold for any book, "
            "including generated ones."
        ),
        runs=_RUNS_IN_TESTS + " Tests: tests/properties/.",
        source="tests/properties/test_*.py (test names and docstrings)",
        columns=(
            Column("Property family", 50, wrap=True),
            Column("Test", 60),
            Column("What it asserts", 80, wrap=True),
            Column("Markers", 18),
            Column("Location", 50),
        ),
        rows=tuple(rows),
    )


def article_coverage_sheet() -> Sheet:
    """Per article: which evidence layers cite it, and the resulting confidence tier."""
    snapshot = json.loads(CONFIDENCE_SNAPSHOT.read_text(encoding="utf-8"))
    scoring = snapshot.get("scoring_rule", {})
    rows = [
        (
            article["framework"],
            article["article"],
            article["confidence"],
            scoring.get(article["confidence"], ""),
            len(article.get("code_functions", [])),
            len(article.get("pack_entries", [])),
            len(article.get("source_files", [])),
            len(article.get("oracle_cases", [])),
            len(article.get("test_files", [])),
            ", ".join(article.get("oracle_cases", [])),
        )
        for article in snapshot["articles"]
    ]
    return Sheet(
        name="Article coverage",
        what=(
            "One row per regulatory article, with the number of places each evidence "
            "layer cites it. The test-file count is a text match, not an executed link."
        ),
        runs="Not a check. A join of the other evidence layers, regenerated from the code.",
        source=(
            "tests/contracts/data/confidence_snapshot.json (scripts/generate_confidence_matrix.py)"
        ),
        columns=(
            Column("Framework", 10),
            Column("Article", 9),
            Column("Confidence", 11),
            Column("Tier rule", 50, wrap=True),
            Column("Code functions", 9),
            Column("Pack entries", 9),
            Column("Source files", 9),
            Column("Oracle cases", 9),
            Column("Test files", 9),
            Column("Oracle case IDs", 40, wrap=True),
        ),
        rows=tuple(rows),
    )


def test_inventory_sheet() -> Sheet:
    """Every test function in the repository, with its one-line docstring."""
    rows = []
    for root, label in ((TESTS_ROOT, None), (FILER_TESTS_ROOT, "rwa-filer")):
        for test in _collect_tests(root):
            suite = label or test.path.relative_to(TESTS_ROOT).parts[0]
            if suite in _NOT_TEST_SUITES:
                continue
            rows.append(
                (
                    suite,
                    _relative(test.path),
                    test.class_name,
                    test.name,
                    test.summary,
                    ", ".join(test.markers),
                )
            )
    return Sheet(
        name="Test inventory",
        what=(
            "One row per test function. A parametrised test (marker 'parametrize') runs "
            "once per case, so the number of test runs is larger than the number of rows."
        ),
        runs=(
            "Test suite only. CI runs every suite except tests marked slow, benchmark or "
            "robustness; the robustness search runs nightly."
        ),
        source="tests/**/test_*.py and packages/rwa-filer/tests/**/test_*.py",
        columns=(
            Column("Suite", 14),
            Column("File", 60),
            Column("Class", 30),
            Column("Test", 60),
            Column("What it checks (docstring)", 80, wrap=True),
            Column("Markers", 20),
        ),
        rows=tuple(rows),
    )


def coverage_measures() -> tuple[Measure, ...]:
    """The banked measures of how much of the estate the checks can see."""
    coverage = _read_json(COVERAGE_BASELINE)
    filing = _read_json(FILING_MAPPING_BASELINE)
    referee = _read_json(REFEREE_BASELINE)
    injection = _read_json(INJECTION_BASELINE)
    oracle = json.loads(ORACLE_VALUES.read_text(encoding="utf-8"))
    disagreements = _oracle_disagreements()

    runs = len(coverage.get("provenance", {}).get("portfolios", []))
    returns = referee.get("portfolios", {})
    compared = sum(entry.get("rules_compared", 0) for entry in returns.values())
    disagreeing = sum(len(entry.get("disagreements", [])) for entry in returns.values())
    arelle_errors = sum(len(entry.get("arelle_errors", [])) for entry in returns.values())
    return (
        Measure(
            "Published rules that reach a pass or fail — CRR",
            str(coverage.get("union_binding_rules_crr", "")),
            f"Distinct rules reaching a pass or a fail on at least one of the {runs} test "
            "portfolio runs; a vacuous pass is not counted. A rule no run reaches is not "
            "checked by the test estate.",
            _relative(COVERAGE_BASELINE),
        ),
        Measure(
            "Published rules that reach a pass or fail — Basel 3.1",
            str(coverage.get("union_binding_rules_b31", "")),
            "As above, for the BoE Basel 3.1 extract.",
            _relative(COVERAGE_BASELINE),
        ),
        Measure(
            "Published rules never evaluated",
            str(coverage.get("never_evaluated_rules", "")),
            "Rules not evaluated on any of the test portfolio runs.",
            _relative(COVERAGE_BASELINE),
        ),
        Measure(
            "Template cells populated by a test portfolio",
            str(coverage.get("cells_live", "")),
            "Declared template cells that carry a figure in at least one test run.",
            _relative(COVERAGE_BASELINE),
        ),
        Measure(
            "Template cells never populated",
            str(coverage.get("dead_cells", "")),
            "Declared cells no test run fills. A figure in such a cell on your return "
            "has no test-estate evidence behind it.",
            _relative(COVERAGE_BASELINE),
        ),
        Measure(
            "Golden-return cells placed in the PRA001 taxonomy",
            str(filing.get("placed_cells", "")),
            "Figures in the generated Basel 3.1 golden returns that land on a taxonomy data point.",
            _relative(FILING_MAPPING_BASELINE),
        ),
        Measure(
            "Golden-return figures with no taxonomy cell",
            str(filing.get("unplaced_figures", "")),
            "Cells carrying a non-zero figure that the taxonomy has no place for, so they "
            "cannot be filed as generated.",
            _relative(FILING_MAPPING_BASELINE),
        ),
        Measure(
            "Error-severity rule breaks on the golden returns",
            str(filing.get("error_rule_breaks", "")),
            "ERROR-severity Bank rules the placed golden Basel 3.1 returns break, counted "
            "as (rule, return) pairs; error_rules_by_rule in the source file names them.",
            _relative(FILING_MAPPING_BASELINE),
        ),
        Measure(
            "Arelle referee: rule verdicts compared / disagreements / Arelle errors",
            f"{compared} / {disagreeing} / {arelle_errors} over {len(returns)} golden returns",
            "Arelle, an independent XBRL processor, loads each golden return against the "
            "Bank's taxonomy package and its verdict on every rule is compared with ours. "
            "This checks the filing validator, not the capital figures.",
            _relative(REFEREE_BASELINE),
        ),
        Measure(
            "Hand-derived oracle cases / parked disagreements",
            f"{len(oracle.get('oracles', []))} / {len(disagreements)}",
            "Independent expected values; a parked disagreement is a known engine "
            "difference held as a strict xfail.",
            f"{_relative(ORACLE_VALUES)}; {_relative(ORACLE_TEST)}",
        ),
        Measure(
            "Defect-injection detection rate",
            str(injection.get("status", "")) or "banked",
            "UNBANKED means no campaign has been measured, so the share of realistic "
            "defects the gates catch is not yet known.",
            _relative(INJECTION_BASELINE),
        ),
    )


# =============================================================================
# Source index — what the code under src/rwa_calc declares and calls
# =============================================================================


@dataclass(frozen=True)
class CodeDeclaration:
    """One error-code constant and the comment the code carries for it."""

    code: str
    constant: str
    module: str
    line: int
    group: str
    description: str


@dataclass
class _RaiseSites:
    """What the ``CalculationError(...)`` sites raising one code state literally."""

    severities: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)


class SourceIndex:
    """Parsed view of every module under one source root, built in one pass and queried.

    Module names are paths relative to the root (``contracts/errors.py``).
    Each module is parsed once and walked once; every query below is a lookup
    over the facts that walk recorded.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @cached_property
    def modules(self) -> dict[str, _ModuleFacts]:
        """The recorded facts of every module, keyed by relative path."""
        facts: dict[str, _ModuleFacts] = {}
        for path in sorted(self._root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            facts[path.relative_to(self._root).as_posix()] = _ModuleFacts.of(
                ast.parse(text), text.splitlines()
            )
        return facts

    @cached_property
    def declarations(self) -> tuple[CodeDeclaration, ...]:
        """Every module-level string constant whose value is an error code."""
        found = []
        for module, facts in self.modules.items():
            for node in facts.tree.body:
                target, value = _simple_assignment(node)
                if target is None or not isinstance(value, ast.Constant):
                    continue
                if not isinstance(value.value, str) or not ERROR_CODE_PATTERN.match(value.value):
                    continue
                group, description = _comment_context(facts.lines, node.lineno - 1)
                found.append(
                    CodeDeclaration(
                        code=value.value,
                        constant=target,
                        module=module,
                        line=node.lineno,
                        group=group,
                        description=description,
                    )
                )
        return tuple(found)

    @cached_property
    def error_codes(self) -> tuple[CodeDeclaration, ...]:
        """The declarations that ARE error codes, not merely spelled like one.

        ``PRA001`` (the filing module) has the same shape as ``CRM001``. A
        declaration counts when ``contracts/errors.py`` makes it, when a raise
        site passes it as ``code=``, or when its constant is named as a code.
        """
        sites = self.raise_sites()
        return tuple(
            decl
            for decl in self.declarations
            if decl.module == ERRORS_MODULE
            or decl.code in sites
            or _CODE_CONSTANT_NAME.search(decl.constant)
        )

    def raise_status(self, decl: CodeDeclaration) -> str:
        """Whether anything raises ``decl``, and where, as read from the call sites.

        Four outcomes, because they mean different things to a reader:
        a direct raise site; a module that raises a code it looks up at run
        time (a mapping or a spec table) and names this one; references that
        never raise it; and no reference at all.
        """
        direct = self.raise_sites().get(decl.code)
        if direct is not None:
            return "Raised in " + "; ".join(sorted(direct.modules))
        used_in = self.references(decl)
        dynamic = sorted(used_in & self._dynamic_raisers)
        if dynamic:
            return "Raised through a code mapping in " + "; ".join(dynamic)
        if used_in:
            return "Not raised: no raise site found; referenced only as listed"
        return "Not raised: declared, with no other reference in src/rwa_calc"

    @cached_property
    def _dynamic_raisers(self) -> frozenset[str]:
        """Modules that raise a code chosen at run time rather than written at the site."""
        constants = {d.constant: d.code for d in self.declarations}
        factories = {f.name: f for facts in self.modules.values() for f in facts.factories}
        raisers = set()
        for module, facts in self.modules.items():
            for node in facts.call_nodes:
                if id(node) in facts.factory_calls:
                    continue
                name = _call_name(node)
                keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                if name == "CalculationError":
                    argument = keywords.get("code")
                elif name in factories:
                    argument = factories[name].argument(node, keywords)
                else:
                    continue
                if argument is not None and _resolve_code(argument, constants) is None:
                    raisers.add(module)
        return frozenset(raisers)

    @cached_property
    def _sites(self) -> dict[str, _RaiseSites]:
        constants = {d.constant: d.code for d in self.declarations}
        factories = {f.name: f for facts in self.modules.values() for f in facts.factories}
        sites: dict[str, _RaiseSites] = defaultdict(_RaiseSites)
        for module, facts in self.modules.items():
            for node in facts.call_nodes:
                name = _call_name(node)
                keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                if name == "CalculationError":
                    code = _resolve_code(keywords.get("code"), constants)
                    severity = _enum_member(keywords.get("severity"), "ErrorSeverity")
                    category = _enum_member(keywords.get("category"), "ErrorCategory")
                elif name in factories:
                    factory = factories[name]
                    code = _resolve_code(factory.argument(node, keywords), constants)
                    severity, category = factory.severity, factory.category
                else:
                    continue
                if code is None:
                    continue
                entry = sites[code]
                entry.modules.add(module)
                if severity:
                    entry.severities.add(severity.lower())
                if category:
                    entry.categories.add(category.lower())
        return dict(sites)

    def raise_sites(self) -> dict[str, _RaiseSites]:
        """Per code, the severities and categories its raise sites state.

        A raise site is a ``CalculationError(...)`` call, or a call of a factory
        helper — a function that passes its own parameter as ``code=`` to a
        ``CalculationError(...)`` it builds (``crm_warning(code, ...)``), whose
        severity and category are then the helper's. ``code=ERROR_X`` resolves
        through the declared constants and a literal ``code="CCR020"`` as
        itself. A site whose severity or category is not a literal
        ``ErrorSeverity.X`` / ``ErrorCategory.X`` contributes nothing to that
        column, so a blank means "set at run time", never "none".
        """
        return self._sites

    def references(self, decl: CodeDeclaration) -> set[str]:
        """Modules that use ``decl``'s constant or literal code, other than the declaration itself.

        A use inside the declaring module counts (a factory function there is a
        use); the declaration's own name and value do not.
        """
        found = set()
        for module, facts in self.modules.items():
            literal_lines = facts.code_literals.get(decl.code, set())
            if module == decl.module:
                literal_lines = literal_lines - {decl.line}
            if decl.constant in facts.names or literal_lines:
                found.add(module)
        return found

    def call_sites(self, function: str) -> list[str]:
        """``module::enclosing function`` for every call of ``function``, outside its definer."""
        sites = {
            f"{module}::{scope}" if scope else module
            for module, facts in self.modules.items()
            if function not in facts.defined
            for scope, name in facts.calls
            if name == function
        }
        return sorted(sites)


@dataclass(frozen=True)
class _ModuleFacts:
    """What one walk of a module records for the queries ``SourceIndex`` answers.

    Attributes:
        tree / lines: The parsed module and its source lines.
        names: Every name the module READS (``Load`` context) or imports.
        code_literals: Each error-code-shaped string literal -> the lines it is on.
        calls: ``(enclosing scope, called name)`` for every call.
        call_nodes: Every call node.
        defined: Every function name the module defines.
        factories: The module's error factory helpers (see ``_Factory``).
        factory_calls: ``id()`` of the ``CalculationError(...)`` node inside each
            factory — the one that passes the factory's parameter on as the code.
    """

    tree: ast.Module
    lines: list[str]
    names: frozenset[str]
    code_literals: dict[str, set[int]]
    calls: tuple[tuple[str, str], ...]
    call_nodes: tuple[ast.Call, ...]
    defined: frozenset[str]
    factories: tuple[_Factory, ...]
    factory_calls: frozenset[int]

    @classmethod
    def of(cls, tree: ast.Module, lines: list[str]) -> _ModuleFacts:
        names: set[str] = set()
        literals: dict[str, set[int]] = defaultdict(set)
        calls: list[tuple[str, str]] = []
        defined: set[str] = set()
        call_nodes: list[ast.Call] = []
        factories: list[_Factory] = []
        for scope, node in _walk_with_scope(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.alias):
                names.add(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if ERROR_CODE_PATTERN.match(node.value):
                    literals[node.value].add(node.lineno)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                defined.add(node.name)
                factories.extend(_Factory.find(node))
            elif isinstance(node, ast.Call):
                calls.append((scope, _call_name(node)))
                call_nodes.append(node)
        return cls(
            tree=tree,
            lines=lines,
            names=frozenset(names),
            code_literals=dict(literals),
            calls=tuple(calls),
            call_nodes=tuple(call_nodes),
            defined=frozenset(defined),
            factories=tuple(factories),
            factory_calls=frozenset(f.node_id for f in factories),
        )


@dataclass(frozen=True)
class _Factory:
    """A helper that builds a ``CalculationError`` around a code it is handed.

    Attributes:
        name: The helper's function name.
        parameter: The parameter it passes on as ``code=``.
        position: That parameter's positional index, or ``None`` if keyword-only.
        severity / category: The literal ``ErrorSeverity`` / ``ErrorCategory``
            member the helper sets, or empty when it sets one at run time.
    """

    name: str
    parameter: str
    position: int | None
    severity: str
    category: str
    node_id: int

    @classmethod
    def find(cls, function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_Factory]:
        positional = [a.arg for a in (*function.args.posonlyargs, *function.args.args)]
        parameters = {*positional, *(a.arg for a in function.args.kwonlyargs)}
        found = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or _call_name(node) != "CalculationError":
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            code = keywords.get("code")
            if not isinstance(code, ast.Name) or code.id not in parameters:
                continue
            found.append(
                cls(
                    name=function.name,
                    parameter=code.id,
                    position=positional.index(code.id) if code.id in positional else None,
                    severity=_enum_member(keywords.get("severity"), "ErrorSeverity"),
                    category=_enum_member(keywords.get("category"), "ErrorCategory"),
                    node_id=id(node),
                )
            )
        return found

    def argument(self, call: ast.Call, keywords: Mapping[str, ast.expr]) -> ast.expr | None:
        """The expression ``call`` passes for the code parameter, if it passes one."""
        if self.parameter in keywords:
            return keywords[self.parameter]
        if self.position is not None and self.position < len(call.args):
            return call.args[self.position]
        return None


# =============================================================================
# Workbook writing
# =============================================================================


class _Formats:
    """The handful of cell formats the workbook uses, created once per workbook."""

    def __init__(self, workbook: Workbook) -> None:
        add = workbook.add_format
        self.title = add({"bold": True, "font_size": 14})
        self.label = add({"bold": True, "valign": "top"})
        self.text = add({"valign": "top"})
        self.wrap = add({"valign": "top", "text_wrap": True})
        self.header = add(
            {
                "bold": True,
                "valign": "top",
                "text_wrap": True,
                "bg_color": "#DDE4EE",
                "bottom": 1,
            }
        )


def _write_read_me(ws: Worksheet, catalogue: Catalogue, formats: _Formats) -> None:
    """The front sheet: provenance, how to read the workbook, sheet guide, measures."""
    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 70)
    ws.set_column(2, 2, 60)
    ws.set_column(3, 4, 40)
    row = 0
    ws.write_string(row, 0, "RWA calculator — check catalogue", formats.title)
    row += 2
    provenance: list[tuple[str, str]] = [
        ("Generated (UTC)", catalogue.generated_at.isoformat()),
        ("Git commit", catalogue.commit),
        *[(f"{name} version", version) for name, version in catalogue.versions.items()],
        *[(f"Rulepack {regime} content hash", h) for regime, h in catalogue.pack_hashes.items()],
        ("Regenerate with", "uv run python scripts/export_check_catalogue.py"),
    ]
    for label, value in provenance:
        ws.write_string(row, 0, label, formats.label)
        ws.write_string(row, 1, value, formats.text)
        row += 1

    row += 1
    ws.write_string(row, 0, "How to read this workbook", formats.label)
    for line in _READ_ME_NOTES:
        ws.write_string(row, 1, line, formats.wrap)
        row += 1

    row += 1
    for col, header in enumerate(
        ("Sheet", "What one row is", "Where it runs", "Read from", "Rows")
    ):
        ws.write_string(row, col, header, formats.header)
    row += 1
    for sheet in catalogue.sheets:
        ws.write_string(row, 0, sheet.name, formats.label)
        ws.write_string(row, 1, sheet.what, formats.wrap)
        ws.write_string(row, 2, sheet.runs, formats.wrap)
        ws.write_string(row, 3, sheet.source, formats.wrap)
        ws.write_number(row, 4, len(sheet.rows), formats.text)
        row += 1

    row += 1
    ws.write_string(row, 0, "Banked coverage measures", formats.label)
    row += 1
    for col, header in enumerate(("Measure", "Value", "How to read it", "Read from")):
        ws.write_string(row, col, header, formats.header)
    row += 1
    for measure in catalogue.measures:
        ws.write_string(row, 0, measure.name, formats.wrap)
        ws.write_string(row, 1, measure.value, formats.text)
        ws.write_string(row, 2, measure.meaning, formats.wrap)
        ws.write_string(row, 3, measure.source, formats.wrap)
        row += 1


#: The only free prose in the workbook: how to read it. Every check and every
#: number comes from the code or a banked file.
_READ_ME_NOTES: Final[tuple[str, ...]] = (
    "Each sheet lists one family of checks, read from the code when this file was "
    "generated. Nothing in it is typed by hand, so re-running the script brings it up "
    "to date.",
    "'Where it runs' is worked out from the call sites in src/rwa_calc. If a family "
    "has no production call site, the sheet says so.",
    "Sheets marked 'Test suite only' are the evidence that the calculator is right: "
    "independent expected values, decision tables and invariants. They run in CI, not "
    "on your data.",
    "This workbook lists WHAT is checked. For what the checks found on your own return, "
    "run ResultExporter.validate_submission and export_validation_report.",
    "A listed check is not evidence that the check itself is right. The coverage "
    "measures below say how much of the estate the checks can see.",
)


def _write_sheet(ws: Worksheet, sheet: Sheet, formats: _Formats) -> None:
    """One family: a four-line heading, then a filterable, frozen table."""
    ws.write_string(0, 0, sheet.name, formats.title)
    for offset, (label, value) in enumerate(
        (
            ("What one row is", sheet.what),
            ("Where it runs", sheet.runs),
            ("Read from", sheet.source),
        ),
        start=1,
    ):
        ws.write_string(offset, 0, label, formats.label)
        ws.write_string(offset, 1, value, formats.text)

    header_row = 5
    for col, column in enumerate(sheet.columns):
        ws.set_column(col, col, column.width, formats.wrap if column.wrap else formats.text)
        ws.write_string(header_row, col, column.header, formats.header)
    for offset, values in enumerate(sheet.rows, start=1):
        for col, value in enumerate(values):
            _write_value(ws, header_row + offset, col, value)
    last_row = header_row + max(len(sheet.rows), 1)
    ws.autofilter(header_row, 0, last_row, len(sheet.columns) - 1)
    ws.freeze_panes(header_row + 1, 1)


def _write_value(ws: Worksheet, row: int, col: int, value: object) -> None:
    """Write numbers as numbers and everything else as plain, truncated text."""
    if isinstance(value, bool):
        ws.write_string(row, col, "Yes" if value else "No")
    elif isinstance(value, int | float):
        ws.write_number(row, col, value)
    elif value is None or value == "":
        return
    else:
        ws.write_string(row, col, _fit(str(value)))


# =============================================================================
# Private helpers
# =============================================================================


@dataclass(frozen=True)
class _TestFunction:
    """One collected test function."""

    path: Path
    location: str
    class_name: str
    name: str
    summary: str
    module_summary: str
    markers: tuple[str, ...]


def _collect_tests(root: Path) -> Iterator[_TestFunction]:
    """Every ``test_*`` function in ``test_*.py`` files under ``root``, in file order."""
    if not root.exists():
        return
    for path in sorted(root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_summary = _first_paragraph(ast.get_docstring(tree))
        module_marks = _module_markers(tree)
        location = path.relative_to(REPO_ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_marks = _decorator_markers(node)
                for item in node.body:
                    if _is_test_function(item):
                        yield _TestFunction(
                            path=path,
                            location=f"{location}::{node.name}::{item.name}",
                            class_name=node.name,
                            name=item.name,
                            summary=_first_paragraph(ast.get_docstring(item)),
                            module_summary=module_summary,
                            markers=_merge(module_marks, class_marks, _decorator_markers(item)),
                        )
            elif _is_test_function(node):
                yield _TestFunction(
                    path=path,
                    location=f"{location}::{node.name}",
                    class_name="",
                    name=node.name,
                    summary=_first_paragraph(ast.get_docstring(node)),
                    module_summary=module_summary,
                    markers=_merge(module_marks, _decorator_markers(node)),
                )


def _is_test_function(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
        "test_"
    )


def _decorator_markers(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [name for d in node.decorator_list if (name := _mark_name(d))]


def _module_markers(tree: ast.Module) -> list[str]:
    """Markers from a module-level ``pytestmark = ...`` (one mark or a list)."""
    for node in tree.body:
        target, value = _simple_assignment(node)
        if target != "pytestmark" or value is None:
            continue
        values = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        return [name for v in values if (name := _mark_name(v))]
    return []


def _mark_name(node: ast.expr) -> str:
    """``slow`` for ``pytest.mark.slow`` or ``pytest.mark.slow(...)``; empty otherwise."""
    if isinstance(node, ast.Call):
        node = node.func
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    ):
        return node.attr
    return ""


def _merge(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for group in groups for name in group))


def _simple_assignment(node: ast.stmt) -> tuple[str | None, ast.expr | None]:
    """``(name, value)`` for ``NAME = value`` / ``NAME: T = value``; ``(None, None)`` otherwise."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
        return node.target.id, node.value
    return None, None


def _oracle_disagreements() -> dict[str, str]:
    """The oracle's parked disagreements, read from the test module that parks them.

    Imported rather than parsed: the reasons are built from f-strings, so the
    dict is not a literal, and the imported value is exactly what the strict
    xfail marks carry.
    """
    import importlib

    module = importlib.import_module("tests.oracle.test_oracle")
    return {case: _clean_text(reason) for case, reason in module.KNOWN_DISAGREEMENTS.items()}


def _comment_context(lines: Sequence[str], index: int) -> tuple[str, str]:
    """``(group, description)`` for the declaration on ``lines[index]``.

    Declarations sit in blank-line-separated paragraphs. A comment block that
    opens a paragraph of SEVERAL declarations is the group's heading, not the
    first declaration's description; a comment block directly above a single
    declaration is its description. The group label is the heading's first
    sentence.
    """
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1

    lead: list[str] = []
    for line in lines[start : end + 1]:
        if not line.lstrip().startswith("#"):
            break
        lead.append(line)

    own: list[str] = []
    cursor = index - 1
    while cursor >= start and lines[cursor].lstrip().startswith("#"):
        own.insert(0, lines[cursor])
        cursor -= 1
    own_is_lead = cursor < start

    declarations = sum(1 for line in lines[start : end + 1] if _DECLARATION.match(line))
    group = _first_sentence(_join_comment(lead))
    if own_is_lead and declarations > 1:
        return group, ""
    return group, _join_comment(own)


_DECLARATION: Final = re.compile(r"^[A-Z][A-Z0-9_]*\s*(:[^=]+)?=\s*[\"'][A-Z]{2,4}\d{3}[\"']")


def _join_comment(lines: Iterable[str]) -> str:
    """Comment lines as prose: markers stripped, wrapped lines joined, ``#`` lines as breaks."""
    paragraphs: list[list[str]] = [[]]
    for line in lines:
        text = line.strip().removeprefix("#:").removeprefix("#").strip()
        if not text:
            paragraphs.append([])
            continue
        paragraphs[-1].append(text)
    return _plain("\n".join(" ".join(p) for p in paragraphs if p))


def _plain(text: str) -> str:
    """Drop reStructuredText roles and literal markup: ``:func:`f``` and ````x```` -> ``f``, ``x``."""
    text = re.sub(r":[a-z]+:`([^`]+)`", r"\1", text)
    return text.replace("``", "")


def _first_sentence(text: str) -> str:
    """Up to the first full stop or colon that ends a sentence.

    A stop only ends a sentence when an upper-case letter or the end of the
    text follows it, so ``Art. 230`` and ``e.g. a`` do not split.
    """
    first = text.split("\n", 1)[0]
    match = re.match(r"(.+?)[.:](\s+[A-Z(]|\s*$)", first)
    return match.group(1) if match else first


def _first_paragraph(docstring: str | None) -> str:
    if not docstring:
        return ""
    return _plain(" ".join(docstring.strip().split("\n\n", 1)[0].split()))


def _clean_text(text: str) -> str:
    """Unwrap hard-wrapped TOML / docstring prose, keeping paragraph breaks."""
    paragraphs = [" ".join(p.split()) for p in str(text).strip().split("\n\n")]
    return "\n".join(p for p in paragraphs if p)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _resolve_code(node: ast.expr | None, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if ERROR_CODE_PATTERN.match(node.value) else None
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Attribute):
        return constants.get(node.attr)
    return None


def _enum_member(node: ast.expr | None, enum: str) -> str:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == enum
    ):
        return node.attr
    return ""


def _walk_with_scope(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """Every node, with the dotted name of the function or class enclosing it."""
    stack: list[tuple[str, ast.AST]] = [("", tree)]
    while stack:
        scope, node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                child_scope = f"{scope}.{child.name}" if scope else child.name
            else:
                child_scope = scope
            yield scope, child
            stack.append((child_scope, child))


def _runs_at(index: SourceIndex, *functions: str) -> str:
    """Where ``functions`` are called from in ``src/rwa_calc``, or a statement that nothing calls them."""
    sites = sorted({site for function in functions for site in index.call_sites(function)})
    names = " / ".join(f"{f}()" for f in functions)
    if not sites:
        return (
            f"No production call site: nothing in src/rwa_calc calls {names}. It is "
            "defined and exported, and is exercised only by the test suite."
        )
    return f"{names}, called from: " + "; ".join(sites)


def _describe_table_scopes(scopes: Iterable[object]) -> str:
    parts = []
    for scope in scopes:
        axes = []
        for axis in ("rows", "columns", "sheets"):
            rule_scope = getattr(scope, axis)
            if rule_scope.kind == "all":
                axes.append(f"{axis}: all")
            elif rule_scope.kind == "list":
                axes.append(f"{axis}: {';'.join(rule_scope.ids)}")
        if axes:
            parts.append(f"{scope.table} — {', '.join(axes)}")  # type: ignore[attr-defined]
    return "\n".join(parts)


def _describe_status(status: Iterable[str], reactivated_on: str | None) -> str:
    text = ", ".join(status)
    return f"{text} (reactivated {reactivated_on})" if reactivated_on else text


def _describe_when(when: Mapping[str, object]) -> str:
    return "; ".join(
        f"{dimension} in [{', '.join(map(str, value))}]"
        if isinstance(value, list)
        else f"{dimension} = {value}"
        for dimension, value in when.items()
    )


def _describe_carrier(cell: Mapping[str, object]) -> str:
    carrier = cell.get("carrier", "")
    carriers = " + ".join(carrier) if isinstance(carrier, list) else str(carrier)
    scale = cell.get("scale", 1.0)
    scaled = "" if scale in (1, 1.0, None) else f" x {scale}"
    return f"{cell.get('metric', '')}({carriers}){scaled}"


def _describe_where(clauses: Iterable[Mapping[str, object]]) -> str:
    parts = []
    for clause in clauses:
        target = clause.get("values", clause.get("value", ""))
        shown = ", ".join(map(str, target)) if isinstance(target, list) else str(target)
        parts.append(f"{clause.get('column', '')} {clause.get('op', '')} {shown}".strip())
    return " AND ".join(parts) if parts else "all rows"


def _key_values(mapping: Mapping[str, object]) -> str:
    return "; ".join(f"{key}={value}" for key, value in mapping.items())


def _parked_rule_notes(framework: str) -> dict[str, str]:
    """Rule id -> the register's note, for rules parked as broken or vacuous on our portfolios."""
    regime = _REGISTER_REGIME[framework]
    register = _read_json(VALIDATION_REGISTER)
    notes: dict[str, list[str]] = defaultdict(list)
    for kind, key in (
        ("Known break", "known_broken_rules"),
        ("Never binds", "known_vacuous_rules"),
    ):
        for entry in register.get(key, []):
            if entry.get("regime") != regime:
                continue
            portfolios = ", ".join(entry.get("portfolios", []))
            notes[entry["rule_id"]].append(
                f"{kind} on {portfolios}: {_clean_text(entry.get('reason', ''))}"
            )
    return {rule_id: "\n".join(text) for rule_id, text in notes.items()}


def _code_prefix(code: str) -> str:
    return code.rstrip("0123456789")


def _fit(text: str) -> str:
    if len(text) <= MAX_CELL_CHARS:
        return text
    return text[:_TRUNCATE_AT] + " … [truncated: Excel's cell limit; see the source file]"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _git_commit() -> str:
    """The checked-out commit, flagged when the tree has uncommitted changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown (not a git checkout)"
    return f"{commit} (uncommitted changes present)" if dirty else commit


def _pack_hashes() -> dict[str, str]:
    """Each regime pack's content hash, resolved at the regime's reference date."""
    from generate_regulatory_tables import REGIME_DATES, REGIME_LABELS

    from rwa_calc.rulebook.resolve import resolve

    return {
        f"{REGIME_LABELS[regime]} @ {on.isoformat()}": resolve(regime, on).content_hash
        for regime, on in REGIME_DATES
    }


if __name__ == "__main__":
    raise SystemExit(main())
