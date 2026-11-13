"""
Workbook reader and writer — a return as one worksheet per table and sheet.

Pipeline position:
    taxonomy pack  ->  write_workbook  ->  blank or filled .xlsx
    filled .xlsx   ->  read_workbook   ->  CanonicalReturn

Key responsibilities:
- Write a workbook a person can fill in: one worksheet for each table and each
  of its sheets, laid out as the published template is — row codes down the
  side, column codes across the top, labels beside both, and the cells the
  taxonomy does not accept shaded grey.
- Read such a workbook back into a canonical return. The two are a round trip:
  a return written and read again is the same return.
- Read by MARKERS, not by position or worksheet name. A worksheet is a template
  sheet if it carries a ``Table`` marker; its sheet code, open key and header
  row are found by their labels. Renaming a tab, or inserting a note above the
  grid, does not change what is read.

The layout of one worksheet
    A1  Table      B1  <table code>     C1  <title>
    A2  Sheet      B2  <sheet code>     C2  <sheet label>     (B2 empty: no sheet axis)
    A3  Open key   B3  <member>         C3  <what to enter>   (B3 empty: no open axis)
    A5  Row        B5  Row label        C5… <column codes>
                                        C6… <column labels>
    A7… <row code> B7… <row label>      C7… the figures

The ``Return`` worksheet holds the header as label / value pairs.

An open-axis table (one sheet per country, say) is written once with an empty
``Open key``; copy the worksheet for each member reported. An open-row table
has no published rows: enter any identifier in column A, unique within the
worksheet, and the row's key values in the key columns.

Reading and writing a workbook needs ``openpyxl`` (the ``rwa-filer[excel]``
extra).

References:
- rwa_filer.model — the canonical fact schema
- Bank of England Banking Taxonomy — the annotated templates this layout follows
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.model import CODE_WIDTH, FACT_SCHEMA, CanonicalReturn, ReturnHeader

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from rwa_filer.taxonomy.pack import Table, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The worksheet holding the return header.
RETURN_SHEET: Final = "Return"

MARKER_TABLE: Final = "Table"
MARKER_SHEET: Final = "Sheet"
MARKER_OPEN_KEY: Final = "Open key"
MARKER_ROW: Final = "Row"
_ROW_LABEL_HEADING: Final = "Row label"

#: How far down a worksheet the markers are looked for.
_MARKER_SCAN_ROWS: Final = 25
#: First column that holds figures (A = row code, B = row label).
_FIRST_DATA_COLUMN: Final = 2

_GREY_FILL: Final = "FFBBBBBB"
_SHEET_NAME_INVALID: Final = re.compile(r"[\[\]:*?/\\]")
_SHEET_NAME_MAX: Final = 31


# =============================================================================
# Public API — read
# =============================================================================


def read_workbook(path: Path, header: ReturnHeader | None = None) -> CanonicalReturn:
    """Read a workbook in the template layout into a canonical return.

    Args:
        path: The ``.xlsx`` file.
        header: Overrides the header on the ``Return`` worksheet. Required when
            the workbook has no such worksheet.

    Raises:
        ValueError: the workbook has no ``Return`` worksheet and no ``header``
            was given, or its header is incomplete. (A usage error.)
    """
    workbook = _load_workbook(path)
    try:
        resolved = header or _read_header(workbook)
        rows: list[dict[str, Any]] = []
        for worksheet in workbook.worksheets:
            if worksheet.title == RETURN_SHEET:
                continue
            grid = [list(row) for row in worksheet.iter_rows(values_only=True)]
            facts = _read_grid(grid)
            if facts is None:
                logger.info("worksheet %r has no %r marker; skipped", worksheet.title, MARKER_TABLE)
                continue
            rows.extend(facts)
    finally:
        workbook.close()

    frame = pl.DataFrame(rows, schema=FACT_SCHEMA) if rows else pl.DataFrame(schema=FACT_SCHEMA)
    logger.info("read %d facts from %s", frame.height, path.name)
    return CanonicalReturn.from_frame(resolved, frame)


# =============================================================================
# Public API — write
# =============================================================================


def write_workbook(
    pack: TaxonomyPack,
    path: Path,
    *,
    tables: Sequence[str] | None = None,
    ret: CanonicalReturn | None = None,
) -> int:
    """Write a workbook in the template layout: blank, or filled from ``ret``.

    Args:
        pack: The taxonomy whose tables are laid out.
        path: Where to write the ``.xlsx``.
        tables: The table codes to include. Defaults to the tables ``ret``
            reports; with no ``ret`` either, to every table of the module —
            which for a large module is several hundred worksheets.
        ret: A return to fill in. Its header is written to the ``Return``
            worksheet and its facts to their cells. A fact in a table that is
            not laid out, or in a cell the layout does not have, is NOT written
            — check a return's structure before relying on its workbook.

    Returns:
        The number of table worksheets written.

    Raises:
        ValueError: ``tables`` names a table the module does not have.
    """
    wanted = (
        list(tables) if tables is not None else (list(ret.tables) if ret else list(pack.tables))
    )
    unknown = [code for code in wanted if code not in pack.tables]
    if tables is not None and unknown:
        raise ValueError(f"Not a {pack.info.module} table: {', '.join(unknown)}")

    openpyxl = _openpyxl()
    workbook = openpyxl.Workbook()
    front = workbook.active
    front.title = RETURN_SHEET
    _write_header(front, ret.header if ret else None, pack)

    grey = openpyxl.styles.PatternFill("solid", start_color=_GREY_FILL, end_color=_GREY_FILL)
    bold = openpyxl.styles.Font(bold=True)
    names: set[str] = {RETURN_SHEET}
    written = 0
    for code in wanted:
        table = pack.tables.get(code)
        if table is None:
            continue
        facts = ret.table_facts(code) if ret else None
        reportable = _reportable_cells(pack, code)
        for sheet_code, sheet_label, open_key in _worksheets_for(table, facts):
            worksheet = workbook.create_sheet(_worksheet_name(code, sheet_code, open_key, names))
            _write_table_sheet(
                worksheet,
                table,
                sheet_code=sheet_code,
                sheet_label=sheet_label,
                open_key=open_key,
                reportable=reportable,
                facts=_facts_for(facts, sheet_code, open_key),
                grey=grey,
                bold=bold,
            )
            written += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    logger.info("wrote %d worksheet(s) to %s", written, path.name)
    return written


# =============================================================================
# Private helpers — reading
# =============================================================================


def _read_header(workbook: Any) -> ReturnHeader:
    """The header from the ``Return`` worksheet's label / value rows."""
    if RETURN_SHEET not in workbook.sheetnames:
        raise ValueError(
            f"The workbook has no {RETURN_SHEET!r} worksheet; supply the return header "
            "(entity identifier, reference date, module)"
        )
    fields: dict[str, str] = {}
    for row in workbook[RETURN_SHEET].iter_rows(values_only=True):
        if len(row) >= 2 and row[0] is not None and row[1] is not None:
            fields[str(row[0])] = _cell_text(row[1])
    return ReturnHeader.from_fields(fields)


def _read_grid(grid: list[list[Any]]) -> list[dict[str, Any]] | None:
    """The facts on one worksheet, or ``None`` if it is not a template sheet."""
    markers = _find_markers(grid)
    table = markers.get(MARKER_TABLE)
    header_index = markers.get(MARKER_ROW)
    if table is None or header_index is None:
        return None

    table_code = _cell_text(grid[table][1]) if len(grid[table]) > 1 else ""
    if not table_code:
        return None
    sheet = _marker_value(grid, markers.get(MARKER_SHEET), as_code=True)
    open_key = _marker_value(grid, markers.get(MARKER_OPEN_KEY), as_code=False)

    header = grid[header_index]
    columns = {
        index: _code(cell)
        for index, cell in enumerate(header)
        if index >= _FIRST_DATA_COLUMN and cell is not None and _cell_text(cell)
    }
    facts: list[dict[str, Any]] = []
    for row in grid[header_index + 1 :]:
        if not row or row[0] is None or not _cell_text(row[0]):
            continue  # the label banner, a spacer, or a note — not a data row
        row_code = _code(row[0])
        for index, column in columns.items():
            if index >= len(row) or row[index] is None:
                continue
            value, text = _split_value(row[index])
            if value is None and text is None:
                continue
            facts.append(
                {
                    "table": table_code,
                    "sheet": sheet,
                    "open_key": open_key,
                    "row": row_code,
                    "column": column,
                    "value": value,
                    "text_value": text,
                }
            )
    return facts


def _find_markers(grid: list[list[Any]]) -> dict[str, int]:
    """Row index of each marker label found in column A near the top."""
    wanted = {
        marker.lower(): marker
        for marker in (MARKER_TABLE, MARKER_SHEET, MARKER_OPEN_KEY, MARKER_ROW)
    }
    found: dict[str, int] = {}
    for index, row in enumerate(grid[:_MARKER_SCAN_ROWS]):
        if not row or not isinstance(row[0], str):
            continue
        marker = wanted.get(row[0].strip().lower())
        if marker is not None and marker not in found:
            found[marker] = index
    return found


def _marker_value(grid: list[list[Any]], index: int | None, *, as_code: bool) -> str | None:
    """The value in column B of a marker row (``None`` when absent or blank)."""
    if index is None or len(grid[index]) < 2 or grid[index][1] is None:
        return None
    text = _code(grid[index][1]) if as_code else _cell_text(grid[index][1])
    return text or None


def _code(cell: Any) -> str:
    """A row / column / sheet code as the publisher writes it.

    A code typed into a spreadsheet is routinely stored as a number, which
    loses its leading zeros; a numeric cell is restored to the padded form.
    """
    if isinstance(cell, bool):
        return _cell_text(cell)
    if isinstance(cell, int):
        return str(cell).zfill(CODE_WIDTH)
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell)).zfill(CODE_WIDTH)
    return _cell_text(cell)


def _split_value(cell: Any) -> tuple[float | None, str | None]:
    """One worksheet cell as ``(value, text_value)`` — exactly one is set.

    A number is a value. Everything else is kept as text, in the form the
    canonical schema uses: ``true`` / ``false`` for a boolean, an ISO date for
    a date. A blank string is nothing at all.
    """
    if isinstance(cell, bool):
        return None, "true" if cell else "false"
    if isinstance(cell, int | float):
        return float(cell), None
    if isinstance(cell, dt.datetime):
        return None, cell.date().isoformat()
    if isinstance(cell, dt.date):
        return None, cell.isoformat()
    text = _cell_text(cell)
    return None, text or None


def _cell_text(cell: Any) -> str:
    """A cell as trimmed text (a date as ISO, ``None`` as the empty string)."""
    if cell is None:
        return ""
    if isinstance(cell, dt.datetime):
        return cell.date().isoformat()
    if isinstance(cell, dt.date):
        return cell.isoformat()
    return str(cell).strip()


# =============================================================================
# Private helpers — writing
# =============================================================================


def _write_header(worksheet: Any, header: ReturnHeader | None, pack: TaxonomyPack) -> None:
    """The ``Return`` worksheet: the header fields, blank for a template."""
    blank = ReturnHeader(entity_identifier="", reference_date=pack.info.valid_from, module="")
    fields = (header or blank).as_fields()
    if header is None:
        fields = {**dict.fromkeys(fields, ""), "Module": pack.info.module, "Currency": "GBP"}
    for label, value in fields.items():
        worksheet.append([label, value])
    worksheet.append([])
    worksheet.append(["Taxonomy", f"{pack.info.taxonomy} {pack.info.version}"])
    worksheet.column_dimensions["A"].width = 28
    worksheet.column_dimensions["B"].width = 40


def _worksheets_for(
    table: Table, facts: pl.DataFrame | None
) -> Iterable[tuple[str | None, str, str | None]]:
    """``(sheet code, sheet label, open key)`` for each worksheet a table needs.

    Blank: every fixed sheet, with one empty open key where the table has an
    open axis. Filled: only the (sheet, open key) pairs the return reports.
    """
    fixed = table.fixed_axis
    labels = {sheet.code: sheet.label for sheet in fixed.sheets} if fixed else {}
    if facts is not None and not facts.is_empty():
        pairs = facts.select("sheet", "open_key").unique().sort("sheet", "open_key")
        for sheet_code, open_key in pairs.iter_rows():
            yield sheet_code, labels.get(sheet_code or "", ""), open_key
        return
    for sheet_code in table.sheet_codes or (None,):
        yield sheet_code, labels.get(sheet_code or "", ""), None


def _facts_for(
    facts: pl.DataFrame | None, sheet_code: str | None, open_key: str | None
) -> pl.DataFrame | None:
    """The facts belonging on one worksheet."""
    if facts is None:
        return None
    return facts.filter(
        pl.col("sheet").eq_missing(pl.lit(sheet_code, pl.String))
        & pl.col("open_key").eq_missing(pl.lit(open_key, pl.String))
    )


def _reportable_cells(pack: TaxonomyPack, table: str) -> dict[str | None, set[tuple[str, str]]]:
    """``{sheet code: {(row, column)}}`` of the cells the taxonomy accepts."""
    cells: dict[str | None, set[tuple[str, str]]] = {}
    for sheet, row, column in (
        pack.cells.filter(pl.col("table") == table).select("sheet", "row", "column").iter_rows()
    ):
        cells.setdefault(sheet, set()).add((row, column))
    return cells


def _write_table_sheet(
    worksheet: Any,
    table: Table,
    *,
    sheet_code: str | None,
    sheet_label: str,
    open_key: str | None,
    reportable: dict[str | None, set[tuple[str, str]]],
    facts: pl.DataFrame | None,
    grey: Any,
    bold: Any,
) -> None:
    """Lay one table sheet out and, where given, fill its facts in."""
    open_axis = table.open_axis
    hint = f"a member of {open_axis.dimension}" if open_axis else ""
    worksheet.append([MARKER_TABLE, table.code, table.title])
    worksheet.append([MARKER_SHEET, sheet_code, sheet_label])
    worksheet.append([MARKER_OPEN_KEY, open_key, hint])
    worksheet.append([])
    columns = table.entry_columns
    worksheet.append([MARKER_ROW, _ROW_LABEL_HEADING, *(code for code, _label in columns)])
    worksheet.append([None, None, *(label for _code, label in columns)])
    for cell in worksheet[5]:
        cell.font = bold
    for marker_row in (1, 2, 3):
        worksheet.cell(row=marker_row, column=1).font = bold

    values = _fact_lookup(facts)
    column_index = {code: 3 + offset for offset, (code, _label) in enumerate(columns)}
    accepted = reportable.get(sheet_code, set())

    if table.open_rows:
        row_ids = sorted({row for row, _column in values}) if values else []
        for offset, row_id in enumerate(row_ids):
            worksheet.cell(row=7 + offset, column=1, value=row_id)
            for code, index in column_index.items():
                if (row_id, code) in values:
                    worksheet.cell(row=7 + offset, column=index, value=values[(row_id, code)])
    else:
        for offset, (row_code, row_label) in enumerate(table.rows):
            excel_row = 7 + offset
            worksheet.cell(row=excel_row, column=1, value=row_code)
            worksheet.cell(row=excel_row, column=2, value=row_label)
            for code, index in column_index.items():
                cell = worksheet.cell(row=excel_row, column=index)
                if (row_code, code) in values:
                    cell.value = values[(row_code, code)]
                if (row_code, code) not in accepted:
                    cell.fill = grey

    worksheet.freeze_panes = "C7"
    worksheet.column_dimensions["A"].width = 12
    worksheet.column_dimensions["B"].width = 48


def _fact_lookup(facts: pl.DataFrame | None) -> dict[tuple[str, str], float | str]:
    """``{(row, column): figure}`` for one worksheet's facts."""
    if facts is None or facts.is_empty():
        return {}
    return {
        (row, column): value if value is not None else text
        for row, column, value, text in facts.select(
            "row", "column", "value", "text_value"
        ).iter_rows()
        if row is not None
    }


def _worksheet_name(table: str, sheet: str | None, open_key: str | None, used: set[str]) -> str:
    """A worksheet name: unique, at most 31 characters, free of forbidden characters.

    The name is for the person reading the workbook. The reader never relies on
    it — the table, sheet and open key are read from the markers.
    """
    parts = [table]
    if sheet:
        parts.append(f"z{sheet}")
    if open_key:
        parts.append(open_key)
    base = _SHEET_NAME_INVALID.sub("_", " ".join(parts))[:_SHEET_NAME_MAX]
    name, suffix = base, 2
    while name in used:
        tail = f" ({suffix})"
        name = base[: _SHEET_NAME_MAX - len(tail)] + tail
        suffix += 1
    used.add(name)
    return name


def _load_workbook(path: Path) -> Any:
    """Open a workbook read-only, values only."""
    return _openpyxl().load_workbook(path, read_only=True, data_only=True)


def _openpyxl() -> Any:
    """Import openpyxl, with a clear message when the extra is not installed."""
    try:
        import openpyxl
        import openpyxl.styles  # noqa: F401 - the styles submodule is used via the package
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the extra
        raise ModuleNotFoundError(
            "Reading or writing a workbook needs openpyxl. Install it with: "
            "pip install 'rwa-filer[excel]'"
        ) from exc
    return openpyxl
