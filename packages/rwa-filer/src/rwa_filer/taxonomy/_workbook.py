"""
DPM workbook reader — the publisher's two .xlsx files as plain, immutable records.

Pipeline position:
    annotated-templates .xlsx  ->  read_annotated_workbook  ->  AnnotatedWorkbook
    DPM dictionary .xlsx       ->  read_dictionary          ->  Dictionary
        ->  compiler.compile_pack

Key responsibilities:
- Read every table sheet of an annotated-templates workbook into a ``SheetGrid``:
  cell strings, which cells carry a fill (headers and non-reportable cells are
  the same solid grey), merged ranges, dropdown lists and cell comments.
- Recover the two things ``openpyxl`` discards and the compiler cannot work
  without: the x14-extension list validations (they point each z-axis and each
  enumeration cell at a row of the hidden ``Enumerations`` sheet) and the legacy
  cell comments (they name the dimension of an open-row key column). Both are
  read straight from the workbook's zip parts.
- Read the Table of Contents: one column per reporting module (entry point),
  group rows and table rows.
- Read the dictionary workbook: metric data types and enumeration hierarchies,
  each dimension's domain, typed-domain element and default member.

This module only reads. It decides nothing about table layout — that is
``compiler`` — and it holds the one ``openpyxl`` import of the taxonomy package
(the ``rwa-filer[excel]`` extra), made lazily so the runtime never needs it.

References:
- Bank of England Banking Taxonomy: annotated templates and DPM dictionary
  workbooks (https://www.bankofengland.co.uk/statistics/data-collection)
- ECMA-376 SpreadsheetML: ``extLst`` data validations, ``comments`` parts
"""

from __future__ import annotations

import posixpath
import re
import warnings
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

#: ``(row, column)``, both 1-based, as a worksheet addresses a cell.
type Cell = tuple[int, int]
#: ``(first row, first column, last row, last column)`` of a cell range, inclusive.
type Bounds = tuple[int, int, int, int]

CONTENTS_SHEET = "Table of Contents"
ENUMERATIONS_SHEET = "Enumerations"
NOTE_SHEET = "Note"
#: Sheets that are not tables. ``MAPPING`` (some workbooks) lists table / ordinate
#: code / spreadsheet position and carries nothing the compiler needs.
NON_TABLE_SHEETS = frozenset({NOTE_SHEET, CONTENTS_SHEET, ENUMERATIONS_SHEET, "MAPPING"})

#: Dictionary "Data type" spellings -> the pack's lower-case type names.
DATA_TYPES = {
    "MONETARY": "monetary",
    "PERCENTAGE": "percentage",
    "INTEGER": "integer",
    "DECIMAL": "decimal",
    "STRING": "string",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "ENUMERATION": "enumeration",
}

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
_XM = "http://schemas.microsoft.com/office/excel/2006/main"
_RANGE = re.compile(r"^\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$")
_ENUMERATION_REF = re.compile(rf"^'?{ENUMERATIONS_SHEET}'?!(.+)$")
_MEMBER_SHEET = re.compile(r"^(eba|boe)_([A-Z]{2})$")


# ── Records ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SheetGrid:
    """One worksheet: its cell strings and the formatting the compiler reads."""

    name: str
    values: Mapping[Cell, str]
    grey: frozenset[Cell]
    dropdowns: tuple[tuple[Bounds, str], ...]
    comments: Mapping[Cell, str]
    merged: tuple[Bounds, ...]

    def value(self, row: int, column: int) -> str | None:
        """The cell's string, or ``None`` when the cell is empty."""
        return self.values.get((row, column))

    def is_grey(self, row: int, column: int) -> bool:
        """Whether the cell carries a fill (a header, or a non-reportable cell)."""
        return (row, column) in self.grey

    def dropdown_at(self, row: int, column: int) -> str | None:
        """The list-validation formula covering the cell, if any."""
        for (row1, column1, row2, column2), formula in self.dropdowns:
            if row1 <= row <= row2 and column1 <= column <= column2:
                return formula
        return None

    def row_label(self, row: int, code_column: int) -> str:
        """The grey text left of a row's code; a vertically merged cell above counts."""
        parts = [
            self.values[(row, column)].strip()
            for column in range(1, code_column)
            if (row, column) in self.values and (row, column) in self.grey
        ]
        if parts:
            return " ".join(parts)
        return " ".join(
            self.values[(row1, column1)].strip()
            for row1, column1, row2, column2 in self.merged
            if row1 < row <= row2 and column2 < code_column and (row1, column1) in self.values
        )

    def column_label(self, code_row: int, column: int, left_limit: int) -> str:
        """The grey header text above a column's code, group headers first."""
        parts: list[str] = []
        for row in range(3, code_row):
            own = self.values.get((row, column))
            if own and (row, column) in self.grey:
                parts.append(own.strip())
                continue
            for row1, column1, row2, column2 in self.merged:
                anchor = (row1, column1)
                spans = row1 <= row <= row2 and column1 <= column <= column2
                if not spans or anchor == (row, column) or column1 <= left_limit:
                    continue
                text = self.values.get(anchor, "").strip()
                if text and anchor in self.grey and text not in parts:
                    parts.append(text)
        return " / ".join(parts)


@dataclass(frozen=True)
class TableOfContents:
    """A workbook's modules, and each table's group and module membership."""

    modules: Mapping[str, str]
    group_of: Mapping[str, str | None]
    modules_of: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class AnnotatedWorkbook:
    """An annotated-templates workbook, fully read and detached from the file."""

    file_name: str
    title: str | None
    contents: TableOfContents
    sheets: Mapping[str, SheetGrid]
    enumeration_rows: Mapping[int, tuple[str, ...]]

    def enumeration(self, formula: str) -> tuple[str, ...] | None:
        """Resolve ``Enumerations!$A$35:$P$35`` to that range's cell strings."""
        match = _ENUMERATION_REF.match(formula)
        bounds = parse_range(match.group(1)) if match else None
        if bounds is None:
            return None
        row1, column1, row2, column2 = bounds
        cells: list[str] = []
        for row in range(row1, row2 + 1):
            line = self.enumeration_rows.get(row, ())
            cells.extend(
                line[column - 1] if column <= len(line) else ""
                for column in range(column1, column2 + 1)
            )
        return tuple(cells)


@dataclass(frozen=True)
class MetricInfo:
    """A metric as the dictionary describes it."""

    type: str | None
    period: str | None
    label: str | None
    enumeration: str | None


@dataclass(frozen=True)
class DimensionInfo:
    """A dimension as the dictionary describes it."""

    label: str | None
    domain: str | None
    kind: str | None
    default: str | None
    typed_element: str | None
    typed_type: str | None


@dataclass(frozen=True)
class Dictionary:
    """The DPM dictionary workbook: metrics and dimensions keyed by prefixed QName."""

    file_name: str
    metrics: Mapping[str, MetricInfo]
    dimensions: Mapping[str, DimensionInfo]


# ── Public entry points ───────────────────────────────────────────────────────


def read_annotated_workbook(path: Path) -> AnnotatedWorkbook:
    """Read every table sheet, the Table of Contents and the enumeration lists."""
    extras = _read_zip_extras(path)
    workbook = _load_workbook(path, read_only=False)
    try:
        sheets = {
            sheet.title: _read_sheet(sheet, *extras.get(sheet.title, ((), {})))
            for sheet in workbook.worksheets
            if sheet.title not in NON_TABLE_SHEETS
        }
        names = set(workbook.sheetnames)
        enumeration_rows: dict[int, tuple[str, ...]] = {}
        if ENUMERATIONS_SHEET in names:
            for number, row in enumerate(
                workbook[ENUMERATIONS_SHEET].iter_rows(values_only=True), 1
            ):
                enumeration_rows[number] = tuple("" if v is None else str(v) for v in row)
        contents = (
            _read_contents(list(workbook[CONTENTS_SHEET].iter_rows(values_only=True)))
            if CONTENTS_SHEET in names
            else TableOfContents({}, {}, {})
        )
        title = _first_text(workbook[NOTE_SHEET]) if NOTE_SHEET in names else None
    finally:
        workbook.close()
    return AnnotatedWorkbook(path.name, title, contents, sheets, enumeration_rows)


def read_dictionary(path: Path) -> Dictionary:
    """Read metric types and each dimension's domain, typed element and default member."""
    workbook = _load_workbook(path, read_only=True)
    try:
        domains = {row["Code"]: row for row in _header_rows(workbook["Domains"]) if row.get("Code")}
        defaults: dict[str, str] = {}
        for sheet in workbook.worksheets:
            match = _MEMBER_SHEET.match(sheet.title)
            if not match:
                continue
            for row in _header_rows(sheet):
                if row.get("Code") and str(row.get("Default")) == "True":
                    defaults[match.group(2)] = member_qname(
                        str(row.get("Owner")), match.group(1), match.group(2), str(row["Code"])
                    )
        dimensions = {
            f"{row.get('Owner')}_dim:{row['Code']}": _dimension_info(row, domains, defaults)
            for row in _header_rows(workbook["Dimensions"])
            if row.get("Code")
        }
        metrics = {
            f"{row.get('Owner')}_met:{row['Code']}": _metric_info(row)
            for row in _header_rows(workbook["Metrics"])
            if row.get("Code")
        }
    finally:
        workbook.close()
    return Dictionary(path.name, metrics, dimensions)


# ── Supporting public functions ───────────────────────────────────────────────


def parse_range(reference: str) -> Bounds | None:
    """``F9:AD73`` / ``$A$35:$P$35`` / ``B3`` -> ``(row1, column1, row2, column2)``."""
    match = _RANGE.match(reference.strip())
    if not match:
        return None
    first_column, first_row, last_column, last_row = match.groups()
    row1, column1 = int(first_row), column_number(first_column)
    row2 = int(last_row) if last_row else row1
    column2 = column_number(last_column) if last_column else column1
    return (row1, column1, row2, column2)


def column_number(letters: str) -> int:
    """Spreadsheet column letters to a 1-based number (``A`` -> 1, ``AA`` -> 27)."""
    number = 0
    for letter in letters:
        number = number * 26 + (ord(letter) - ord("A") + 1)
    return number


def column_letters(number: int) -> str:
    """A 1-based column number to spreadsheet letters (27 -> ``AA``)."""
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def address(row: int, column: int) -> str:
    """A1-style address of a cell, for irregularity messages."""
    return f"{column_letters(column)}{row}"


def member_qname(member_owner: str, domain_owner: str, domain: str, code: str) -> str:
    """Prefixed QName of a domain member.

    A member the domain's own owner defined is ``eba_AP:x1``; a member another
    owner added to that domain carries both prefixes — ``boe_eba_AP:x10050``.
    """
    if member_owner == domain_owner:
        return f"{domain_owner}_{domain}:{code}"
    return f"{member_owner}_{domain_owner}_{domain}:{code}"


# ── Private helpers ───────────────────────────────────────────────────────────


def _load_workbook(path: Path, *, read_only: bool) -> Any:
    """Open a workbook, with a clear message when openpyxl is absent."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the extra
        raise ModuleNotFoundError(
            "Compiling a taxonomy pack reads the publisher's .xlsx workbooks and needs "
            "openpyxl. Install it with: pip install 'rwa-filer[excel]'"
        ) from exc
    with warnings.catch_warnings():
        # openpyxl warns that it drops the x14 validations; _read_zip_extras reads them.
        warnings.simplefilter("ignore")
        return load_workbook(path, read_only=read_only, data_only=True)


def _read_sheet(
    sheet: Any, dropdowns: tuple[tuple[Bounds, str], ...], comments: Mapping[Cell, str]
) -> SheetGrid:
    """Copy one openpyxl worksheet into a ``SheetGrid``."""
    values: dict[Cell, str] = {}
    grey: set[Cell] = set()
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is not None:
                values[(cell.row, cell.column)] = str(cell.value)
            if cell.fill is not None and cell.fill.fill_type:
                grey.add((cell.row, cell.column))
    merged = tuple(
        (rng.min_row, rng.min_col, rng.max_row, rng.max_col) for rng in sheet.merged_cells.ranges
    )
    return SheetGrid(sheet.title, values, frozenset(grey), dropdowns, comments, merged)


def _first_text(sheet: Any) -> str | None:
    """The first non-empty string on a sheet (the workbook's title line)."""
    for row in sheet.iter_rows(values_only=True):
        for value in row:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _read_contents(rows: list[tuple[Any, ...]]) -> TableOfContents:
    """Parse the Table of Contents.

    The header row is the one whose column A reads ``Template code``; module codes
    follow from column C and their titles sit in the row above. A row with a value
    under a module column is a table of that module; a row with none is a group
    heading, and applies to the table rows beneath it.
    """
    head = next((i for i, row in enumerate(rows) if row and row[0] == "Template code"), None)
    if head is None:
        return TableOfContents({}, {}, {})
    module_columns = {i: str(v).strip() for i, v in enumerate(rows[head]) if i >= 2 and v}
    titles = rows[head - 1] if head else ()
    modules = {
        code: str(titles[i]).strip() if i < len(titles) and titles[i] else ""
        for i, code in module_columns.items()
    }
    group_of: dict[str, str | None] = {}
    modules_of: dict[str, tuple[str, ...]] = {}
    group: str | None = None
    for row in rows[head + 1 :]:
        if not row or row[0] is None:
            continue
        code = str(row[0]).strip()
        members = tuple(m for i, m in module_columns.items() if i < len(row) and row[i])
        if members:
            group_of[code] = group
            modules_of[code] = members
        else:
            group = code
    return TableOfContents(modules, group_of, modules_of)


def _read_zip_extras(
    path: Path,
) -> dict[str, tuple[tuple[tuple[Bounds, str], ...], dict[Cell, str]]]:
    """Per sheet name: list-validation dropdowns and cell comments, from the zip parts."""
    extras: dict[str, tuple[tuple[tuple[Bounds, str], ...], dict[Cell, str]]] = {}
    with zipfile.ZipFile(path) as archive:
        parts = set(archive.namelist())
        targets = {
            rel.get("Id"): rel.get("Target", "")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).iter(f"{{{_MAIN}}}sheet"):
            part = _resolve_target("xl", targets.get(sheet.get(f"{{{_RELS}}}id"), ""))
            if part not in parts:
                continue
            root = ET.fromstring(archive.read(part))
            comments: dict[Cell, str] = {}
            rels = posixpath.join(
                posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
            )
            if rels in parts:
                for rel in ET.fromstring(archive.read(rels)):
                    target = _resolve_target(posixpath.dirname(part), rel.get("Target", ""))
                    if rel.get("Type", "").endswith("/comments") and target in parts:
                        comments.update(_read_comments(archive.read(target)))
            extras[sheet.get("name", "")] = (tuple(_read_dropdowns(root)), comments)
    return extras


def _resolve_target(base: str, target: str) -> str:
    """A relationship target as a zip member path: absolute (``/xl/…``) or relative to ``base``."""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base, target))


def _read_dropdowns(root: ET.Element) -> Iterator[tuple[Bounds, str]]:
    """List validations of a worksheet part: x14-extension ones first, then classic."""
    found: list[tuple[str, str]] = []
    for validation in root.iter(f"{{{_X14}}}dataValidation"):
        if validation.get("type") == "list":
            formula = validation.findtext(f"{{{_X14}}}formula1/{{{_XM}}}f")
            found.append((validation.findtext(f"{{{_XM}}}sqref") or "", formula or ""))
    for validation in root.iter(f"{{{_MAIN}}}dataValidation"):
        if validation.get("type") == "list":
            formula = validation.findtext(f"{{{_MAIN}}}formula1")
            found.append((validation.get("sqref") or "", formula or ""))
    for references, formula in found:
        for reference in references.split():
            bounds = parse_range(reference)
            if bounds is not None and formula:
                yield bounds, formula


def _read_comments(part: bytes) -> dict[Cell, str]:
    """Cell comments of a ``comments*.xml`` part, keyed by the commented cell."""
    comments: dict[Cell, str] = {}
    for comment in ET.fromstring(part).iter(f"{{{_MAIN}}}comment"):
        bounds = parse_range(comment.get("ref", ""))
        if bounds is not None:
            text = "".join(run.text or "" for run in comment.iter(f"{{{_MAIN}}}t"))
            comments[(bounds[0], bounds[1])] = text
    return comments


def _header_rows(sheet: Any) -> Iterator[dict[str, Any]]:
    """Rows of a dictionary sheet as dicts keyed by its header row.

    A dictionary sheet is two tables side by side that reuse header names (the
    item list, then its hierarchies); the FIRST column of each name wins, which
    is the item list.
    """
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        return
    index: dict[str, int] = {}
    for position, name in enumerate(header):
        if name is not None and str(name) not in index:
            index[str(name)] = position
    for row in rows:
        yield {name: row[i] if i < len(row) else None for name, i in index.items()}


def _dimension_info(
    row: Mapping[str, Any], domains: Mapping[str, Mapping[str, Any]], defaults: Mapping[str, str]
) -> DimensionInfo:
    """Build a dimension record; a typed domain yields its ``<owner>_typ:<code>`` element."""
    code = str(row.get("Domain code"))
    domain = domains.get(code, {})
    label = None if row.get("Label (en)") is None else str(row.get("Label (en)"))
    domain_name = f"{row.get('Domain owner')}_{code}"
    if domain.get("Type") == "typed":
        data_type = domain.get("Data type")
        typed_type = DATA_TYPES.get(str(data_type), None if data_type is None else str(data_type))
        return DimensionInfo(
            label, domain_name, "typed", None, f"{domain.get('Owner')}_typ:{code}", typed_type
        )
    default = defaults.get(code)
    if row.get("Default member code"):
        default = member_qname(
            str(row.get("Default member owner")),
            str(row.get("Domain owner")),
            code,
            str(row.get("Default member code")),
        )
    kind = None if domain.get("Type") is None else str(domain.get("Type"))
    return DimensionInfo(label, domain_name, kind, default, None, None)


def _metric_info(row: Mapping[str, Any]) -> MetricInfo:
    """Build a metric record; an enumeration metric names its member hierarchy."""
    data_type = row.get("Data type")
    enumeration = None
    if row.get("Referenced hierarchy code"):
        enumeration = (
            f"{row.get('Referenced domain owner')}_{row.get('Referenced domain code')}:"
            f"{row.get('Referenced hierarchy owner')}_{row.get('Referenced hierarchy code')}"
        )
    return MetricInfo(
        type=DATA_TYPES.get(str(data_type), None if data_type is None else str(data_type)),
        period=None if row.get("Period type") is None else str(row.get("Period type")),
        label=None if row.get("Label (en)") is None else str(row.get("Label (en)")),
        enumeration=enumeration,
    )
