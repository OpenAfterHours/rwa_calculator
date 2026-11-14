"""
The template grid — one table of a return, laid out as the taxonomy lays it out.

Pipeline position:
    OpenedReturn (facts + pack + rule results)  ->  template_grid
        ->  dash/templates/templates.html

Key responsibilities:
- Lay a table out in the publisher's own rows, columns and sheets, from the
  taxonomy pack — the same layout ``rwa-filer template`` writes as a workbook.
- Show which cells the taxonomy accepts on each sheet, so a figure in a cell
  it does not accept is visible as such, and an empty reportable cell is told
  apart from one that cannot be reported.
- Mark every cell a broken rule read, from the addresses the engine records
  for each failing evaluation — including the empty cells a rule read at its
  default, which are often what the break is about.

References:
- rwa_filer.taxonomy.pack — ``Table`` (rows, columns, sheets) and ``cells``
- rwa_filer.boe.engine — ``Failure.addresses``
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.boe.catalogue import SEVERITY_ERROR
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.views import title_case

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.dash.workspace import OpenedReturn
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack
    from rwa_filer.workflow.adjustments import Adjustment

#: A cell's coordinates within one table: sheet, open-axis key, row, column.
_Place = tuple[str | None, str | None, str, str]

_PERCENTAGE: Final = "percentage"
_INTEGER: Final = "integer"
_MONETARY: Final = "monetary"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class Mark:
    """A broken rule that read a cell."""

    rule_id: str
    severity: str
    reported: bool

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR


@dataclass(frozen=True)
class GridCell:
    """One cell of the grid as drawn."""

    column: str
    text: str
    reportable: bool
    marks: tuple[Mark, ...]
    selected: bool
    dimmed: bool
    override: str | None = None

    @property
    def tone(self) -> str:
        """``"error"``, ``"warning"`` or ``""`` — how the cell is marked."""
        if not self.marks or self.dimmed:
            return ""
        return "error" if any(mark.is_error for mark in self.marks) else "warning"


@dataclass(frozen=True)
class GridRow:
    """One row of the grid."""

    code: str
    label: str
    cells: tuple[GridCell, ...]


@dataclass(frozen=True)
class GridPage:
    """One sheet of a table, or one member of its open axis."""

    sheet: str | None
    open_key: str | None
    label: str
    marks: int


@dataclass(frozen=True)
class TableChoice:
    """A table the return reports, for the table picker."""

    code: str
    title: str
    marks: int


@dataclass(frozen=True)
class CellDetail:
    """The cell the person picked, in full."""

    row: str
    row_label: str
    column: str
    column_label: str
    value: str
    data_type: str
    reportable: bool
    marks: tuple[Mark, ...]
    override: Adjustment | None = None


@dataclass(frozen=True)
class TemplateGrid:
    """One table of the return as the template viewer draws it."""

    table: str
    title: str
    choices: tuple[TableChoice, ...]
    pages: tuple[GridPage, ...]
    page: GridPage
    columns: tuple[tuple[str, str], ...]
    rows: tuple[GridRow, ...]
    cell: CellDetail | None
    focus: str
    values: int


def template_grid(  # noqa: PLR0913 - one keyword per coordinate the page takes
    opened: OpenedReturn,
    *,
    drafts: Sequence[Adjustment] = (),
    table: str = "",
    sheet: str = "",
    key: str = "",
    row: str = "",
    column: str = "",
    focus: str = "",
) -> TemplateGrid | None:
    """The grid for ``table`` (default: the first with a broken rule), or ``None``.

    ``drafts`` are overrides drafted but not yet built: each cell one targets
    shows what it will hold. ``None`` only for a return with no fact in any
    table the taxonomy knows.
    """
    pack = opened.pack
    marks = failure_marks(opened)
    facts = opened.ret.facts.filter(pl.col("table").is_in(list(pack.tables)))
    codes = sorted(set(facts["table"].to_list()))
    if not codes:
        return None
    marked = Counter(place[0] for place in marks)
    choices = tuple(
        TableChoice(code=code, title=title_case(pack.tables[code].title), marks=marked[code])
        for code in codes
    )
    if table not in codes:
        table = next((code for code in codes if marked[code]), codes[0])
    definition = pack.tables[table]
    table_facts = facts.filter(pl.col("table") == table)
    table_marks = {place[1:]: found for place, found in marks.items() if place[0] == table}
    pages = _pages(definition, table_facts, table_marks)
    page = _pick_page(pages, sheet or None, key or None)
    page_facts = table_facts.filter(_on_page(page))
    page_marks = {
        (place[2], place[3]): found
        for place, found in table_marks.items()
        if place[0] == page.sheet and place[1] == page.open_key
    }
    columns = definition.entry_columns if definition.open_rows else definition.columns
    rows = _row_labels(definition, page_facts)
    types = _data_types(pack, table, page.sheet)
    reportable = (
        {(code, column_code) for code, _ in rows for column_code, _ in columns}
        if definition.open_rows
        else set(types)
    )
    values = {
        (fact["row"], fact["column"]): display_value(
            fact["value"], fact["text_value"], types.get((fact["row"], fact["column"]), "")
        )
        for fact in page_facts.iter_rows(named=True)
    }
    overrides = {
        (item.row, item.column): item
        for item in drafts
        if (item.table, item.sheet, item.open_key) == (table, page.sheet, page.open_key)
    }
    picked = (row, column) if (row, column) in reportable | set(values) else None
    if picked is None and page_marks:
        picked = min(page_marks, key=lambda place: _order(rows, columns, place))
    grid_rows = tuple(
        GridRow(
            code=code,
            label=label,
            cells=tuple(
                GridCell(
                    column=column_code,
                    text=values.get((code, column_code), ""),
                    reportable=(code, column_code) in reportable,
                    marks=page_marks.get((code, column_code), ()),
                    selected=picked == (code, column_code),
                    dimmed=bool(focus)
                    and all(
                        mark.rule_id != focus for mark in page_marks.get((code, column_code), ())
                    ),
                    override=_override_text(
                        overrides.get((code, column_code)), types.get((code, column_code), "")
                    ),
                )
                for column_code, _ in columns
            ),
        )
        for code, label in rows
    )
    return TemplateGrid(
        table=table,
        title=title_case(definition.title),
        choices=choices,
        pages=pages,
        page=page,
        columns=columns,
        rows=grid_rows,
        cell=_detail(picked, rows, columns, values, types, reportable, page_marks, overrides),
        focus=focus,
        values=page_facts.height,
    )


def failure_marks(
    opened: OpenedReturn,
) -> dict[tuple[str, str | None, str | None, str, str], tuple[Mark, ...]]:
    """Every cell a broken rule read, with the rules that read it.

    Keyed by ``(table, sheet, open_key, row, column)``. A rule that read a cell
    in several of its failing evaluations marks it once.
    """
    report = opened.validation.report
    found: dict[tuple[str, str | None, str | None, str, str], dict[str, Mark]] = {}
    for result in report.results if report else ():
        if result.status != STATUS_FAIL:
            continue
        for failure in result.failures:
            for address in failure.addresses:
                place = (
                    address.table,
                    address.sheet,
                    address.open_key,
                    address.row,
                    address.column,
                )
                marks = found.setdefault(place, {})
                known = marks.get(result.rule_id)
                reported = address.reported or (known is not None and known.reported)
                marks[result.rule_id] = Mark(result.rule_id, result.severity, reported)
    return {place: tuple(marks.values()) for place, marks in found.items()}


def display_value(value: float | None, text: str | None, data_type: str) -> str:
    """A fact as the grid shows it: grouped digits, percentages as percentages."""
    if value is None:
        return text or ""
    if data_type == _PERCENTAGE:
        return f"{value * 100:,.2f}%"
    if data_type in (_INTEGER, _MONETARY) and float(value).is_integer():
        return f"{value:,.0f}"
    if data_type == _MONETARY:
        return f"{value:,.2f}"
    return f"{value:,.6g}" if abs(value) < 1e6 else f"{value:,.0f}"


# =============================================================================
# Private helpers
# =============================================================================


def _pages(
    definition: Table,
    facts: pl.DataFrame,
    marks: dict[_Place, tuple[Mark, ...]],
) -> tuple[GridPage, ...]:
    """The table's sheets (or open-axis members) that carry a fact or a mark."""
    present = {(sheet, key) for sheet, key in facts.select("sheet", "open_key").iter_rows()}
    present |= {(place[0], place[1]) for place in marks}
    if not present:
        present = {(None, None)}
    counts = Counter((place[0], place[1]) for place in marks)
    order = {code: index for index, code in enumerate(definition.sheet_codes)}
    labels = (
        {sheet.code: sheet.label for sheet in definition.fixed_axis.sheets}
        if definition.fixed_axis
        else {}
    )
    axis = definition.open_axis
    pages = [
        GridPage(
            sheet=sheet,
            open_key=key,
            label=_page_label(sheet, key, labels, axis.label if axis else ""),
            marks=counts[(sheet, key)],
        )
        for sheet, key in present
    ]
    return tuple(
        sorted(
            pages,
            key=lambda page: (
                order.get(page.sheet or "", len(order)),
                page.sheet or "",
                page.open_key or "",
            ),
        )
    )


def _page_label(sheet: str | None, key: str | None, labels: dict[str, str], axis: str) -> str:
    parts = []
    if sheet is not None:
        parts.append(labels.get(sheet, f"Sheet {sheet}"))
    if key is not None:
        parts.append(f"{axis or 'Key'} {key}")
    return " · ".join(parts) or "The whole table"


def _pick_page(pages: tuple[GridPage, ...], sheet: str | None, key: str | None) -> GridPage:
    chosen = next((page for page in pages if (page.sheet, page.open_key) == (sheet, key)), None)
    if chosen is not None:
        return chosen
    return next((page for page in pages if page.marks), pages[0])


def _on_page(page: GridPage) -> pl.Expr:
    sheet = pl.col("sheet").is_null() if page.sheet is None else pl.col("sheet") == page.sheet
    key = (
        pl.col("open_key").is_null()
        if page.open_key is None
        else pl.col("open_key") == page.open_key
    )
    return sheet & key


def _row_labels(definition: Table, facts: pl.DataFrame) -> tuple[tuple[str, str], ...]:
    """The fixed rows, or for an open-row table the rows the return reports."""
    if not definition.open_rows:
        return definition.rows
    return tuple((code, f"Row {code}") for code in sorted(set(facts["row"].to_list())))


def _data_types(pack: TaxonomyPack, table: str, sheet: str | None) -> dict[tuple[str, str], str]:
    """Each reportable cell of one sheet, with its data type."""
    cells = pack.cells.filter(
        (pl.col("table") == table)
        & (pl.col("sheet").is_null() if sheet is None else pl.col("sheet") == sheet)
    )
    types: dict[tuple[str, str], str] = {}
    for row, column, point in cells.select("row", "column", "datapoint").iter_rows():
        metric = pack.metrics.get(pack.datapoints[point].metric)
        types[(row, column)] = metric.data_type if metric else ""
    return types


def _order(
    rows: tuple[tuple[str, str], ...], columns: tuple[tuple[str, str], ...], place: tuple[str, str]
) -> tuple[int, int]:
    row_index = {code: index for index, (code, _) in enumerate(rows)}
    column_index = {code: index for index, (code, _) in enumerate(columns)}
    return row_index.get(place[0], len(row_index)), column_index.get(place[1], len(column_index))


def _override_text(adjustment: Adjustment | None, data_type: str) -> str | None:
    """What a drafted override will make a cell show, or ``None`` for no override."""
    if adjustment is None:
        return None
    if adjustment.remove:
        return "removed"
    return display_value(adjustment.value, adjustment.text_value, data_type)


def _detail(  # noqa: PLR0913 - the parts of one cell, each from its own source
    picked: tuple[str, str] | None,
    rows: tuple[tuple[str, str], ...],
    columns: tuple[tuple[str, str], ...],
    values: dict[tuple[str, str], str],
    types: dict[tuple[str, str], str],
    reportable: set[tuple[str, str]],
    marks: dict[tuple[str, str], tuple[Mark, ...]],
    overrides: dict[tuple[str, str], Adjustment],
) -> CellDetail | None:
    if picked is None:
        return None
    row_labels = dict(rows)
    column_labels = dict(columns)
    return CellDetail(
        row=picked[0],
        row_label=row_labels.get(picked[0], ""),
        column=picked[1],
        column_label=column_labels.get(picked[1], ""),
        value=values.get(picked, ""),
        data_type=types.get(picked, ""),
        reportable=picked in reportable,
        marks=marks.get(picked, ()),
        override=overrides.get(picked),
    )
