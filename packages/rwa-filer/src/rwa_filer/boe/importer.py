"""
Importer — a Bank of England validation-rule workbook as a packaged rule book.

Pipeline position:
    "Bank of England Banking Taxonomy Validations <family> v<version>.xlsx"
        -> import_workbook -> rule-book dict -> write_rulebook -> data/<name>.json
        -> boe.catalogue.load_rulebook

Key responsibilities:
- Read every rule of a workbook as published: the RAW expression, the scope,
  join and where cells, the three flags and the severity per module. Nothing is
  filtered out and nothing is rewritten — which rules are enforced, and what
  they mean, is decided when the rule book is loaded and evaluated.
- Read by HEADER NAME. The eleven workbooks do not share a column layout: the
  Step-in Risk workbook has no precondition columns and the number of table
  columns varies from one to four.
- Write deterministically, one rule per line, so that a new publication shows
  up as a readable diff and ``is_rulebook_current`` can say whether a packaged
  rule book is exactly what its workbook yields.

The workbooks are the Bank's own files and are not redistributed; the rule
books built from them are package data.

References:
- Bank of England Banking Taxonomy v4.1.1 — validation rule workbooks
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.formulas import (
    KEY_CLOSED,
    KEY_DIMENSIONS,
    KEY_FORMULAS,
    KEY_OPEN,
    read_formula_reach,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

RULEBOOK_FORMAT: Final = 1

#: The sheet every workbook carries beside its one data sheet.
NOTE_SHEET: Final = "Note"

COLUMN_RULE: Final = "Rule code"
COLUMN_FRAMEWORK: Final = "Framework code"
COLUMN_FRAMEWORK_VERSION: Final = "Framework version code"
COLUMN_SCOPE: Final = "Scope"
COLUMN_WHERE: Final = "Where"
COLUMN_JOIN: Final = "Join"
COLUMN_EXPRESSION: Final = "Expression"
COLUMN_IN_XBRL: Final = "Include in XBRL"
COLUMN_DEACTIVATED: Final = "Deactivated"
COLUMN_ALWAYS_EXECUTE: Final = "Always execute"
COLUMN_LABEL: Final = "Label"
COLUMN_SEVERITY: Final = "Severity and modules"

#: Columns a workbook must have to be a rule workbook at all.
REQUIRED_COLUMNS: Final = (
    COLUMN_RULE,
    COLUMN_FRAMEWORK_VERSION,
    COLUMN_EXPRESSION,
    COLUMN_IN_XBRL,
    COLUMN_DEACTIVATED,
    COLUMN_ALWAYS_EXECUTE,
    COLUMN_SEVERITY,
)

#: A spreadsheet cell holds at most 32,767 characters; the publisher's export
#: cuts a longer expression at 32,700. Such a cell is not a whole expression.
CELL_LIMIT: Final = 32_700

_TABLE_COLUMN: Final = re.compile(r"^T\d+$")
#: ``ERROR - PRA001|``. The module group keeps its surrounding blanks (the
#: reader strips them), so no two adjacent quantifiers compete for a character.
_SEVERITY_LINE: Final = re.compile(r"^\s*([A-Za-z]+)\s*-([^|]*)(?:\|\s*)?$")
_VERSION: Final = re.compile(r"v(\d+\.\d+\.\d+)")
_SHORT_LABEL: Final = re.compile(
    r"SHORT_LABEL\(en\)\s*-\s*(.*?)(?:\s*\|\s*[A-Z_]+\(en\)\s*-|$)", re.DOTALL
)


# =============================================================================
# Public API
# =============================================================================


def import_workbook(
    workbook: Path,
    *,
    taxonomy_version: str | None = None,
    taxonomy_package: Path | None = None,
) -> dict[str, Any]:
    """Read every rule of a validation workbook into a rule-book dict.

    Args:
        workbook: The ``.xlsx`` file.
        taxonomy_version: The taxonomy release the workbook belongs to, e.g.
            ``"4.1.1"``. Defaults to the version in the file name.
        taxonomy_package: The publisher's taxonomy package zip. When given,
            each rule also records which dimensions its XBRL formula closes
            (``boe.formulas``), so that a rule the formula cannot fire is not
            evaluated from its text. The packaged rule books are built with it.

    Raises:
        ModuleNotFoundError: ``openpyxl`` is not installed (``rwa-filer[excel]``).
        ValueError: the file is not a rule workbook — it has no single data
            sheet, lacks a required column, or mixes framework versions; or
            ``taxonomy_package`` holds no formula for any of its rules.
    """
    from openpyxl import load_workbook

    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        data_sheets = [sheet for sheet in book.worksheets if sheet.title != NOTE_SHEET]
        if len(data_sheets) != 1:
            raise ValueError(
                f"{workbook.name}: expected one data sheet beside {NOTE_SHEET!r}, found "
                f"{[sheet.title for sheet in data_sheets]}"
            )
        sheet = data_sheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise ValueError(f"{workbook.name}: no column(s) {', '.join(missing)}")
        index = {name: position for position, name in enumerate(header) if name}
        table_columns = [
            position for position, name in enumerate(header) if _TABLE_COLUMN.match(name)
        ]
        rules = [
            _rule(row, index, table_columns)
            for row in rows
            if row is not None and _text(row, index[COLUMN_RULE])
        ]
    finally:
        book.close()

    framework_versions = sorted({rule.pop("_framework_version") for rule in rules})
    if len(framework_versions) != 1:
        raise ValueError(
            f"{workbook.name}: expected one framework version, found {framework_versions}"
        )
    version = taxonomy_version or _version_of(workbook.name)
    rules.sort(key=lambda rule: rule["id"])
    logger.info("imported %d rule(s) from %s", len(rules), workbook.name)
    rulebook = {
        "format": RULEBOOK_FORMAT,
        "source": {
            "publisher": "Bank of England",
            "taxonomy": version,
            "workbook": workbook.name,
            "sheet": sheet.title,
            "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
        },
        "framework_version": framework_versions[0],
        "modules": sorted({module for rule in rules for module in rule["severity"]}),
        "rules": rules,
    }
    if taxonomy_package is not None:
        _record_formula_reach(rulebook, taxonomy_package)
    return rulebook


def dump_rulebook(rulebook: dict[str, Any]) -> str:
    """The rule book as text: stable key order, one rule per line."""
    head = {key: value for key, value in rulebook.items() if key != "rules"}
    lines = [json.dumps(rule, ensure_ascii=False, sort_keys=True) for rule in rulebook["rules"]]
    body = json.dumps(head, ensure_ascii=False, sort_keys=True, indent=1)
    return body[:-2] + ',\n "rules": [\n' + ",\n".join(lines) + "\n ]\n}\n"


def write_rulebook(rulebook: dict[str, Any], path: Path) -> None:
    """Write ``rulebook`` to ``path`` in the packaged form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_rulebook(rulebook), encoding="utf-8", newline="\n")


def is_rulebook_current(rulebook: dict[str, Any], path: Path) -> bool:
    """Whether ``path`` holds exactly what ``rulebook`` would be written as.

    A ``rulebook`` imported WITHOUT a taxonomy package says nothing about
    formula reach, so it is compared with the file's workbook content only —
    the file's reach is neither confirmed nor contradicted. ``has_formula_reach``
    tells the two cases apart.
    """
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if text == dump_rulebook(rulebook):
        return True
    if has_formula_reach(rulebook):
        return False
    return dump_rulebook(without_formula_reach(json.loads(text))) == dump_rulebook(rulebook)


def has_formula_reach(rulebook: dict[str, Any]) -> bool:
    """Whether ``rulebook`` was built with a taxonomy package."""
    return KEY_FORMULAS in rulebook["source"]


def without_formula_reach(rulebook: dict[str, Any]) -> dict[str, Any]:
    """``rulebook`` as its workbook alone yields it: no formula reach recorded."""
    stripped = {key: value for key, value in rulebook.items() if key != KEY_DIMENSIONS}
    stripped["source"] = {
        key: value for key, value in rulebook["source"].items() if key != KEY_FORMULAS
    }
    stripped["rules"] = [
        {key: value for key, value in rule.items() if key not in (KEY_OPEN, KEY_CLOSED)}
        for rule in rulebook["rules"]
    ]
    return stripped


def rulebook_file_name(rulebook: dict[str, Any]) -> str:
    """``<framework version>-<taxonomy>.json``, safe as a file name."""
    stem = re.sub(r"[^a-z0-9]+", "_", str(rulebook["framework_version"]).lower()).strip("_")
    return f"{stem}-{rulebook['source']['taxonomy']}.json"


# =============================================================================
# Private helpers
# =============================================================================


def _record_formula_reach(rulebook: dict[str, Any], package: Path) -> None:
    """Add to ``rulebook`` what each rule's formula closes, read from ``package``.

    Nearly every formula closes the same hundred-odd dimensions and leaves a
    handful open, so the file states the whole set once (``formula_dimensions``)
    and, per rule, only the ones that rule leaves OPEN.
    """
    reach = read_formula_reach(
        package, [rule["id"] for rule in rulebook["rules"] if rule["in_xbrl"]]
    )
    dimensions = set(reach.dimensions)
    # The package by what it holds, not by what the file is called: the same
    # publication under another name yields the same rule book.
    rulebook["source"][KEY_FORMULAS] = {
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "folder": reach.folder,
    }
    rulebook[KEY_DIMENSIONS] = sorted(dimensions)
    for rule in rulebook["rules"]:
        found = reach.rules.get(rule["id"])
        if found is None:
            continue
        if found.closed:
            rule[KEY_OPEN] = sorted(dimensions - found.closed)
        if found.closed_by_variable:
            rule[KEY_CLOSED] = {
                variable: sorted(closed) for variable, closed in found.closed_by_variable.items()
            }


def _rule(row: tuple[Any, ...], index: dict[str, int], table_columns: list[int]) -> dict[str, Any]:
    expression = _text(row, index[COLUMN_EXPRESSION]) or ""
    rule: dict[str, Any] = {
        "id": _text(row, index[COLUMN_RULE]),
        "_framework_version": _text(row, index[COLUMN_FRAMEWORK_VERSION]) or "",
        "expression": expression,
        "severity": _severities(_text(row, index[COLUMN_SEVERITY]) or ""),
        "tables": [code for position in table_columns if (code := _text(row, position))],
        "in_xbrl": _flag(row, index[COLUMN_IN_XBRL]),
        "deactivated": _flag(row, index[COLUMN_DEACTIVATED]),
        "always_execute": _flag(row, index[COLUMN_ALWAYS_EXECUTE]),
    }
    for key, column in (("scope", COLUMN_SCOPE), ("where", COLUMN_WHERE), ("join", COLUMN_JOIN)):
        if column in index and (value := _text(row, index[column])):
            rule[key] = value
    if COLUMN_LABEL in index and (label := _short_label(_text(row, index[COLUMN_LABEL]))):
        rule["label"] = label
    if len(expression) >= CELL_LIMIT:
        rule["truncated"] = True
    return rule


def _text(row: tuple[Any, ...], position: int) -> str | None:
    if position >= len(row) or row[position] is None:
        return None
    text = str(row[position]).strip()
    return text or None


def _flag(row: tuple[Any, ...], position: int) -> bool:
    return (_text(row, position) or "").lower() == "yes"


def _severities(cell: str) -> dict[str, str]:
    """``{module: severity}`` from ``"ERROR - PRA001|"``, one module per line."""
    severities: dict[str, str] = {}
    for line in cell.splitlines():
        match = _SEVERITY_LINE.match(line)
        module = match.group(2).strip() if match is not None else ""
        if match is not None and module:
            severities[module] = match.group(1).upper()
    return dict(sorted(severities.items()))


def _short_label(cell: str | None) -> str | None:
    """The English short label of a ``SHORT_LABEL(en) - ..|DESCRIPTION(en) - ..`` cell."""
    if not cell:
        return None
    match = _SHORT_LABEL.search(cell)
    text = (match.group(1) if match else cell).strip()
    return re.sub(r"\s+", " ", text) or None


def _version_of(file_name: str) -> str:
    match = _VERSION.search(file_name)
    if match is None:
        raise ValueError(
            f"{file_name}: no version in the file name; pass taxonomy_version explicitly"
        )
    return match.group(1)
