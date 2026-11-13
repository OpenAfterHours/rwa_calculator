"""
Taxonomy pack compiler — the publisher's DPM workbooks and taxonomy, compiled to a pack.

Pipeline position:
    annotated templates .xlsx + DPM dictionary .xlsx + XBRL taxonomy package
        ->  compile_pack(..., module="PRA001")  ->  compiled pack (format 1, a plain dict)
        ->  pack (on-disk format, loader, resolver)

Key responsibilities:
- For every reportable cell of every table of one reporting module, emit the XBRL
  data point it maps to: the metric QName and its dimension members.
- Read each annotated-template sheet's LAYOUT from the workbook: the column-code
  row and row-code column (or the key columns of an open-row table), the z-axis
  ("sheet") rows above the grid, and the three annotation blocks — below the grid
  per column, right of it per row, and one hidden ``Enumerations`` row per z-axis.
  A cell's data point is the union of its column, row and sheet annotations.
- Take REPORTABILITY from the taxonomy, not from the workbook's grey shading: a
  cell is emitted when the table's definition-linkbase hypercubes accept its data
  point. A greyed cell they accept is emitted and flagged ``"linkbase"``; a white
  cell they reject is dropped and recorded.
- Take from the taxonomy what the workbook does not hold at all: each table's
  filing indicator, the entry point's schemaRef URL, and the code and label of a
  fixed z-axis' all-default ("Total") sheet.
- Resolve metric data types, typed-dimension elements and default members from
  the dictionary workbook; a default member an annotation states explicitly is
  dropped, because an instance never reports a dimension default.
- Record every data condition in ``info.irregularities`` instead of raising, and
  emit everything in a stable order so two compiles of the same inputs are equal.

Ordering of the result: tables by code; a table's cells by (row, column, sheet)
code; data points in first-use order under that cell order; rows, columns and
z-axes in the workbook's own (template) order; a fixed axis' sheets by code.

References:
- Bank of England Banking Taxonomy: annotated templates, DPM dictionary and XBRL
  taxonomy package (https://www.bankofengland.co.uk/statistics/data-collection)
- EBA DPM / XBRL taxonomy architecture: metrics, dimensions, default members,
  open (typed / explicit) axes, filing indicators
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.taxonomy import _linkbase, _workbook
from rwa_filer.taxonomy.pack import (
    MEMBER_OPEN,
    MEMBER_OPEN_OPTIONAL,
    MEMBER_TYPED_PREFIX,
    PACK_FORMAT,
    SOURCE_LINKBASE,
    SOURCE_WORKBOOK,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from rwa_filer.taxonomy._linkbase import Hypercubes, ModuleTable, TaxonomyPackage
    from rwa_filer.taxonomy._workbook import AnnotatedWorkbook, Dictionary, SheetGrid

logger = logging.getLogger(__name__)

#: The compiled layout number, the cell-source flags and the open-member
#: placeholders are defined ONCE, in ``pack``: the loader reads what this module
#: writes, so the two must not be able to drift apart.
TAXONOMY_NAME: Final = "boe-banking"

METRICS_HEADER: Final = "Metrics"
EBA_DICTIONARY: Final = "http://www.eba.europa.eu/xbrl/crr/dict"
BOE_DICTIONARY: Final = "http://www.bankofengland.co.uk/data/xbrl/dict"
ZERO_WIDTH_NON_JOINER: Final = "\N{ZERO WIDTH NON-JOINER}"

# Basel 3.1-era tables use 4-digit ordinate codes; some older modules 3-digit ones.
CODE = re.compile(r"^\d{3,4}$")
TITLE = re.compile(r"^(?P<code>\S+)(?: - (?P<title>.*))?$", re.S)
VERSION = re.compile(r"\bv(\d+(?:\.\d+)+)")
KEY_HEADER = re.compile(r'^(?P<label>.*?)\s*"mandatory"\s*\((?P<code>\d{3,4})\)', re.S)
AXIS_LABEL = re.compile(r"^(?P<label>.*?)\s*\((?P<code>Z\d+|\d{3,4})\)\s*$", re.S)
DIMENSION_HEADER = re.compile(r"^(?P<qname>\w+_dim:\w+) \(.*\)$", re.S)
METRIC = re.compile(r"^(?P<qname>\w+_met:\w+) \(.*?\)(?: \[(?P<enumeration>\w+:\w+)\])?$", re.S)
MEMBER = re.compile(r"^(?P<qname>\w+:[\w.\-]+) \(.*\)$", re.S)
SHEET_PART = re.compile(
    r"^(?P<label>.*) \((?P<code>\d{3,4})\): (?P<dimension>\w+_dim:\w+) \((?P<rest>.*)$", re.S
)
# a dimension label may itself contain brackets: the member is the first ") <qname> ("
SHEET_MEMBER = re.compile(r"\) (?P<member>\w+:[\w.\-]+) \(.*\)$", re.S)
KEY_COMMENT = re.compile(r"^(?P<dimension>\w+_dim:\w+) \(.*?\)(?P<listed> = eba_exp:.*)?$", re.S)


# ── Records ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GridLine:
    """One row or column of a table grid: its code, label and worksheet index."""

    code: str | None
    label: str
    index: int


@dataclass(frozen=True)
class Grid:
    """A sheet's table grid, in 1-based worksheet coordinates.

    An open-row table has no row-code column: ``rows`` is empty, ``key_columns``
    are the columns whose header names a key, and the single blank row under the
    code row stands for every row a filer adds.
    """

    code_row: int
    code_column: int | None
    rows: tuple[GridLine, ...]
    columns: tuple[GridLine, ...]
    key_columns: tuple[int, ...]

    @property
    def data_rows(self) -> tuple[GridLine, ...]:
        """The coded rows, or the one template row of an open-row table."""
        return self.rows or (GridLine(None, "", self.code_row + 1),)

    @property
    def last_row(self) -> int:
        return self.data_rows[-1].index

    @property
    def last_column(self) -> int:
        return self.columns[-1].index


@dataclass(frozen=True)
class Annotation:
    """The metric and dimension members annotated on one row or one column."""

    metric: str | None = None
    enumeration: str | None = None
    dims: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SheetEntry:
    """One sheet of a fixed z-axis. ``code`` is ``None`` for the all-default sheet
    until the taxonomy supplies it."""

    code: str | None
    label: str | None
    members: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FixedAxis:
    """A z-axis with a closed list of sheets, each a combination of members."""

    code: str | None
    label: str
    sheets: tuple[SheetEntry, ...]


@dataclass(frozen=True)
class OpenAxis:
    """A z-axis on one explicit dimension whose member the filer chooses."""

    code: str | None
    label: str
    dimension: str
    members: tuple[str, ...]
    default_allowed: bool


@dataclass(frozen=True)
class OpenKey:
    """A key column of an open-row table: the dimension that identifies a row."""

    code: str
    label: str
    dimension: str
    kind: str
    typed_element: str | None
    typed_type: str | None
    members: tuple[str, ...]
    default_allowed: bool


@dataclass(frozen=True)
class TableLayout:
    """Everything the workbook says about one table, before reportability."""

    code: str
    title: str
    grid: Grid
    axes: tuple[FixedAxis | OpenAxis, ...]
    open_keys: tuple[OpenKey, ...]
    column_annotations: Mapping[int, Annotation]
    row_annotations: Mapping[int, Annotation]


@dataclass(frozen=True)
class CompiledCell:
    """A reportable cell and the signature of its data point."""

    row: str | None
    column: str | None
    sheet: str | None
    metric: str
    dims: tuple[str, ...]
    source: str

    @property
    def order(self) -> tuple[str, str, str]:
        return (self.row or "", self.column or "", self.sheet or "")


@dataclass(frozen=True)
class CompiledTable:
    """One table ready for assembly into the pack."""

    layout: TableLayout
    group: str | None
    filing_indicator: str | None
    cells: tuple[CompiledCell, ...]
    enumerations: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Recorder:
    """Appends one table's irregularities to the shared list.

    Data conditions are recorded, never raised: one odd sheet must not hide the
    other hundred.
    """

    table: str
    sink: list[str]

    def __call__(self, message: str) -> None:
        self.sink.append(f"{self.table}: {message}")


# ── Public entry point ────────────────────────────────────────────────────────


def compile_pack(
    annotated_workbook: Path,
    dictionary_workbook: Path,
    taxonomy_package: Path,
    *,
    module: str,
) -> dict[str, Any]:
    """Compile one reporting module into a pack (format 1).

    Args:
        annotated_workbook: the publisher's annotated-templates .xlsx.
        dictionary_workbook: the publisher's DPM dictionary .xlsx.
        taxonomy_package: the XBRL taxonomy package, as a .zip or an extracted tree.
        module: the entry-point code, a column of the workbook's Table of Contents
            (``"PRA001"``).

    Returns:
        A plain dict — ``format``, ``info``, ``namespaces``, ``metrics``,
        ``dimensions``, ``enumerations``, ``tables`` and ``datapoints``. A table's
        ``cells`` are ``[row, column, sheet, datapoint index, source]``; ``row`` is
        null in an open-row table and ``sheet`` is null without a fixed z-axis. A
        data point is ``[metric, [dim, member, dim, member, ...]]`` with the
        dimensions sorted by QName; a member is a placeholder where the filer
        supplies the value — ``*typed:<element>`` (typed dimension), ``*open``
        (explicit, from the axis' member list) or ``*open?`` (the same, and the
        dimension may be absent because the list includes its default).

    Raises:
        FileNotFoundError: an input path does not exist.
        ValueError: the workbook or the taxonomy package has no such module.
    """
    for path in (annotated_workbook, dictionary_workbook, taxonomy_package):
        if not path.exists():
            raise FileNotFoundError(f"taxonomy compiler input not found: {path}")
    workbook = _workbook.read_annotated_workbook(annotated_workbook)
    if module not in workbook.contents.modules:
        raise ValueError(
            f"module {module!r} is not a Table of Contents column of {workbook.file_name}; "
            f"it lists {sorted(workbook.contents.modules)}"
        )
    dictionary = _workbook.read_dictionary(dictionary_workbook)
    irregularities: list[str] = []
    package = _linkbase.TaxonomyPackage.open(taxonomy_package)
    try:
        listing = _linkbase.read_module(package, module)
        codes = sorted(
            c for c, modules in workbook.contents.modules_of.items() if module in modules
        )
        tables = [
            table
            for code in codes
            if (
                table := _compile_table(
                    code, workbook, dictionary, package, listing.tables, irregularities
                )
            )
        ]
    finally:
        package.close()
    for code in sorted(set(listing.tables) - set(codes)):
        irregularities.append(f"{code}: taxonomy table of {module} is not in the Table of Contents")
    sections = _assemble(tables, dictionary, irregularities)
    info = {
        "module": module,
        "title": workbook.contents.modules[module],
        "taxonomy": TAXONOMY_NAME,
        "version": _version(workbook, irregularities),
        "entry_point": listing.entry_point,
        "sources": {
            "annotated_workbook": workbook.file_name,
            "dictionary_workbook": dictionary.file_name,
            "taxonomy_package": taxonomy_package.name,
        },
        "irregularities": irregularities,
    }
    logger.info(
        "compiled %s: %d tables, %d cells, %d data points, %d irregularities",
        module,
        len(sections["tables"]),
        sum(len(table["cells"]) for table in sections["tables"].values()),
        len(sections["datapoints"]),
        len(irregularities),
    )
    return {"format": PACK_FORMAT, "info": info, **sections}


# ── Supporting public functions: layout ───────────────────────────────────────


def read_table_layout(
    sheet: SheetGrid, workbook: AnnotatedWorkbook, dictionary: Dictionary, note: Recorder
) -> TableLayout | None:
    """Read one sheet's grid, z-axes, open keys and annotations.

    Returns ``None`` (after recording why) when the sheet has no recognisable grid.
    """
    heading = TITLE.match((sheet.value(1, 1) or "").strip())
    if heading is None:
        note("skipped - A1 is not '<code> - <title>'")
        return None
    code, title = heading.group("code"), (heading.group("title") or "").strip()
    if code != sheet.name:
        note(f"A1 table code {code!r} differs from the sheet name")
    if title.startswith(code):
        title = title[len(code) :].lstrip(" -").strip()
    if ZERO_WIDTH_NON_JOINER in title:
        note("title contains a zero-width non-joiner (U+200C); stripped")
        title = title.replace(ZERO_WIDTH_NON_JOINER, "")
    grid = detect_grid(sheet, note)
    if grid is None:
        return None
    column_annotations, row_annotations = _read_annotations(sheet, grid, note)
    return TableLayout(
        code=sheet.name,
        title=title,
        grid=grid,
        axes=_read_axes(sheet, workbook, dictionary, grid, note),
        open_keys=_read_open_keys(sheet, workbook, dictionary, grid, note),
        column_annotations=column_annotations,
        row_annotations=row_annotations,
    )


def detect_grid(sheet: SheetGrid, note: Recorder) -> Grid | None:
    """Find the column-code row and the row-code column, or an open-row table's keys.

    Codes are grey cells holding a 3- or 4-digit string. A closed table is the
    (row, column) pair with the most codes to its right times codes beneath it; if
    no pair exists the codes sit in one row and the key headers — grey cells
    reading ``<label> "mandatory" (NNNN)`` in that row — mark an open-row table.
    """
    codes = {
        cell: value
        for cell, value in sheet.values.items()
        if cell[0] >= 3 and CODE.match(value) and cell in sheet.grey
    }
    code_rows = sorted({row for row, _ in codes})
    code_columns = sorted({column for _, column in codes})
    best: tuple[int, int, int, list[int], list[int]] | None = None
    for code_row in code_rows:
        for code_column in code_columns:
            if (code_row, code_column) in codes:
                continue
            across = [c for c in code_columns if c > code_column and (code_row, c) in codes]
            down = [r for r in code_rows if r > code_row and (r, code_column) in codes]
            if across and down and (best is None or len(across) * len(down) > best[0]):
                best = (len(across) * len(down), code_row, code_column, across, down)
    if best is not None:
        _, code_row, code_column, across, down = best
        grid = Grid(
            code_row=code_row,
            code_column=code_column,
            rows=tuple(
                GridLine(codes[(r, code_column)], sheet.row_label(r, code_column), r) for r in down
            ),
            columns=tuple(
                GridLine(codes[(code_row, c)], sheet.column_label(code_row, c, code_column), c)
                for c in across
            ),
            key_columns=(),
        )
        stray = len(codes) - len(across) - len(down)
        if stray:
            note(f"{stray} grey code cells lie outside the detected code row and column")
    elif len(code_rows) == 1:
        code_row = code_rows[0]
        keys = tuple(
            column
            for (row, column), value in sorted(sheet.values.items())
            if row == code_row and (row, column) in sheet.grey and KEY_HEADER.match(value)
        )
        if not keys:
            note("skipped - one code row but no '<label> \"mandatory\" (NNNN)' key header")
            return None
        grid = Grid(
            code_row=code_row,
            code_column=None,
            rows=(),
            columns=tuple(
                GridLine(codes[(code_row, c)], sheet.column_label(code_row, c, max(keys)), c)
                for c in code_columns
            ),
            key_columns=keys,
        )
    else:
        note(f"skipped - no table grid: grey code cells in rows {code_rows}")
        return None
    for what, lines in (("row", grid.rows), ("column", grid.columns)):
        codes_seen = [line.code for line in lines]
        if len(set(codes_seen)) != len(codes_seen):
            note(f"duplicate {what} codes")
    return grid


# ── Supporting public functions: parsing one cell ─────────────────────────────


def parse_metric(text: str) -> tuple[str, str | None] | None:
    """``eba_met:ei555 (Type of entity) [eba_ZZ:eba_ZZ14]`` -> (metric, enumeration)."""
    match = METRIC.match(text)
    return (match.group("qname"), match.group("enumeration")) if match else None


def parse_dimension_header(text: str) -> str | None:
    """``eba_dim:BAS (Base)`` -> ``eba_dim:BAS``; ``None`` for anything else."""
    match = DIMENSION_HEADER.match(text)
    return match.group("qname") if match else None


def parse_member(text: str) -> str | None:
    """``eba_BA:x9 (Exposures)`` -> ``eba_BA:x9``; ``None`` for a metric or dimension."""
    match = MEMBER.match(text)
    if match is None or match.group("qname").partition(":")[0].endswith(("_dim", "_met")):
        return None
    return match.group("qname")


def parse_sheet_entry(entry: str) -> SheetEntry | None:
    """Parse one entry of a fixed z-axis list.

    An entry is ``Label (0003): dim (..) member (..)`` repeated per dimension and
    joined by `` | ``. An EMPTY entry is the sheet whose members are all dimension
    defaults: it parses to a ``SheetEntry`` with no code, label or members.
    Returns ``None`` when a non-empty entry does not parse.
    """
    if not entry.strip():
        return SheetEntry(None, None, ())
    code: str | None = None
    label: str | None = None
    members: list[tuple[str, str]] = []
    for part in entry.split(" | "):
        head = SHEET_PART.match(part)
        member = SHEET_MEMBER.search(head.group("rest")) if head else None
        if head is None or member is None:
            return None
        if code is not None and (head.group("code"), head.group("label")) != (code, label):
            return None
        code, label = head.group("code"), head.group("label")
        members.append((head.group("dimension"), member.group("member")))
    return SheetEntry(code, label, tuple(sorted(members)))


def parse_axis_label(text: str) -> tuple[str | None, str]:
    """``Sheets (Z1)`` / ``Country "mandatory" (0001)`` -> (code, label)."""
    match = KEY_HEADER.match(text) or AXIS_LABEL.match(text)
    if match is None:
        return None, text.strip()
    return match.group("code"), match.group("label").strip()


def parse_key_comment(text: str) -> tuple[str, bool] | None:
    """An open-row key's cell comment -> (dimension, whether it lists its members).

    ``eba_dim:LGS (Entity)`` is a typed key; ``eba_dim:IGS (..) = eba_exp:BT - BT3
    (..)`` is an explicit key whose members come from the cell's dropdown.
    """
    match = KEY_COMMENT.match(text.strip())
    return (match.group("dimension"), match.group("listed") is not None) if match else None


def drop_default_members(
    dims: Mapping[str, str], defaults: Mapping[str, str | None]
) -> dict[str, str]:
    """Remove ``dimension = its default member`` pairs from a data point."""
    return {dim: member for dim, member in dims.items() if defaults.get(dim) != member}


def namespace_for_prefix(prefix: str) -> str:
    """The namespace URI of a DPM prefix, by the publishers' naming rule.

    ``eba_met`` / ``eba_dim`` / ``eba_typ`` are the EBA dictionary folders and
    ``eba_XX`` its domain XX; ``boe_…`` the same under the BoE dictionary; and
    ``boe_eba_XX`` holds the members the BoE added to the EBA's domain XX.
    """
    if prefix.startswith("boe_eba_"):
        return f"{BOE_DICTIONARY}/dom/eba_{prefix.removeprefix('boe_eba_')}"
    owner, _, rest = prefix.partition("_")
    base = {"eba": EBA_DICTIONARY, "boe": BOE_DICTIONARY}.get(owner)
    if base is None:
        return ""
    return f"{base}/{rest}" if rest in {"met", "dim", "typ", "exp"} else f"{base}/dom/{rest}"


# ── Private helpers: one table ────────────────────────────────────────────────


def _compile_table(
    code: str,
    workbook: AnnotatedWorkbook,
    dictionary: Dictionary,
    package: TaxonomyPackage,
    module_tables: Mapping[str, ModuleTable],
    irregularities: list[str],
) -> CompiledTable | None:
    """Compile one table, or record why it could not be."""
    note = Recorder(code, irregularities)
    sheet = workbook.sheets.get(code)
    if sheet is None:
        note("skipped - the Table of Contents lists it but the workbook has no such sheet")
        return None
    layout = read_table_layout(sheet, workbook, dictionary, note)
    if layout is None:
        return None
    module_table = module_tables.get(code)
    if module_table is None or not package.has(module_table.definition):
        note("skipped - the taxonomy package has no table (or no definition linkbase) of this code")
        return None
    layout = replace(layout, axes=_name_default_sheets(layout.axes, package, module_table, note))
    with package.stream(module_table.definition) as stream:
        cubes = _linkbase.read_hypercubes(stream)
    defaults = {dim: info.default for dim, info in dictionary.dimensions.items()}
    cells, enumerations = _reportable_cells(layout, sheet, workbook, cubes, defaults, note)
    logger.debug("table %s: %d reportable cells", code, len(cells))
    return CompiledTable(
        layout=layout,
        group=workbook.contents.group_of.get(code),
        filing_indicator=module_table.filing_indicator,
        cells=tuple(sorted(cells, key=lambda cell: cell.order)),
        enumerations=enumerations,
    )


def _reportable_cells(
    layout: TableLayout,
    sheet: SheetGrid,
    workbook: AnnotatedWorkbook,
    cubes: Hypercubes,
    defaults: Mapping[str, str | None],
    note: Recorder,
) -> tuple[list[CompiledCell], dict[str, tuple[str, ...]]]:
    """Every grid cell x sheet whose data point the table's hypercubes accept."""
    fixed_axes = [axis for axis in layout.axes if isinstance(axis, FixedAxis)]
    if len(fixed_axes) > 1:
        note("more than one fixed z-axis; only the first is expanded")
    sheets = fixed_axes[0].sheets if fixed_axes else (SheetEntry(None, None, ()),)
    placeholders = _placeholders(layout)
    cells: list[CompiledCell] = []
    enumerations: dict[str, tuple[str, ...]] = {}
    conflicts: set[str] = set()
    rejected: list[str] = []
    promoted: list[str] = []
    unannotated = 0
    for row in layout.grid.data_rows:
        on_row = layout.row_annotations.get(row.index, Annotation())
        for column in layout.grid.columns:
            on_column = layout.column_annotations.get(column.index, Annotation())
            white = not sheet.is_grey(row.index, column.index)
            metric = on_column.metric or on_row.metric
            if metric is None:
                unannotated += white
                continue
            if on_column.metric and on_row.metric:
                conflicts.add("a metric is annotated on both a row and a column")
            hierarchy = on_column.enumeration or on_row.enumeration
            if white and hierarchy:
                _collect_enumeration(
                    enumerations, hierarchy, sheet, workbook, row.index, column.index, conflicts
                )
            base = _merge(on_column.dims, on_row.dims, "row and column", conflicts)
            for entry in sheets:
                dims = _merge(base, dict(entry.members), "sheet and row/column", conflicts)
                stated = sorted(d for d in dims if defaults.get(d) == dims[d] or d in placeholders)
                conflicts.update(
                    f"{d} is an open axis but also has a fixed member"
                    if d in placeholders
                    else f"annotation states the default member {d}={dims[d]} (dropped)"
                    for d in stated
                )
                fixed = {
                    d: m
                    for d, m in drop_default_members(dims, defaults).items()
                    if d not in placeholders
                }
                where = f"r{row.code or '*'}/c{column.code}" + (
                    f"/s{entry.code}" if entry.code else ""
                )
                if not _linkbase.accepts(cubes, metric, fixed, placeholders.keys(), defaults):
                    if white:
                        rejected.append(where)
                    continue
                if not white:
                    promoted.append(where)
                signature = fixed | placeholders
                cells.append(
                    CompiledCell(
                        row=row.code,
                        column=column.code,
                        sheet=entry.code,
                        metric=metric,
                        dims=tuple(
                            part for dim in sorted(signature) for part in (dim, signature[dim])
                        ),
                        source=SOURCE_WORKBOOK if white else SOURCE_LINKBASE,
                    )
                )
    for conflict in sorted(conflicts):
        note(conflict)
    repeats = len(cells) - len({(cell.metric, cell.dims) for cell in cells})
    if repeats:
        note(f"{repeats} cells repeat the data point of another cell of this table")
    if unannotated:
        note(f"{unannotated} white grid cells have no metric annotation (not reportable)")
    if rejected:
        note(
            f"{len(rejected)} white cells are rejected by the definition linkbase and were "
            f"dropped: {_listing(rejected)}"
        )
    if promoted:
        note(
            f"{len(promoted)} cells greyed in the workbook are accepted by the definition "
            f"linkbase and are emitted as 'linkbase' cells: {_listing(promoted)}"
        )
    return cells, enumerations


def _placeholders(layout: TableLayout) -> dict[str, str]:
    """dimension -> placeholder for every open z-axis and open-row key of a table."""
    placeholders: dict[str, str] = {}
    for axis in layout.axes:
        if isinstance(axis, OpenAxis):
            placeholders[axis.dimension] = (
                MEMBER_OPEN_OPTIONAL if axis.default_allowed else MEMBER_OPEN
            )
    for key in layout.open_keys:
        if key.kind == "typed":
            placeholders[key.dimension] = f"{MEMBER_TYPED_PREFIX}{key.typed_element}"
        else:
            placeholders[key.dimension] = (
                MEMBER_OPEN_OPTIONAL if key.default_allowed else MEMBER_OPEN
            )
    return placeholders


def _merge(
    first: Mapping[str, str], second: Mapping[str, str], what: str, conflicts: set[str]
) -> dict[str, str]:
    """Union of two annotation sets; the second wins, and a disagreement is recorded."""
    merged = dict(first)
    for dim, member in second.items():
        if merged.get(dim, member) != member:
            conflicts.add(f"{dim} has different members on {what}")
        merged[dim] = member
    return merged


def _collect_enumeration(
    enumerations: dict[str, tuple[str, ...]],
    hierarchy: str,
    sheet: SheetGrid,
    workbook: AnnotatedWorkbook,
    row: int,
    column: int,
    conflicts: set[str],
) -> None:
    """Record an enumeration metric's allowed members from the cell's dropdown."""
    formula = sheet.dropdown_at(row, column)
    entries = workbook.enumeration(formula) if formula else None
    if entries is None:
        conflicts.add(f"enumeration {hierarchy} has no dropdown list on a reportable cell")
        return
    members = tuple(m for m in map(parse_member, entries) if m)
    if enumerations.setdefault(hierarchy, members) != members:
        conflicts.add(f"enumeration {hierarchy} has different dropdown lists in one table")


def _listing(items: list[str], limit: int = 12) -> str:
    """A bounded, order-preserving sample of cell references for a message."""
    unique = list(dict.fromkeys(items))
    return ", ".join(unique[:limit]) + (
        f", ... ({len(unique)} in all)" if len(unique) > limit else ""
    )


def _name_default_sheets(
    axes: tuple[FixedAxis | OpenAxis, ...],
    package: TaxonomyPackage,
    module_table: ModuleTable,
    note: Recorder,
) -> tuple[FixedAxis | OpenAxis, ...]:
    """Give the all-default sheet of a fixed axis its code and label from the taxonomy."""
    named: list[FixedAxis | OpenAxis] = []
    for axis in axes:
        if isinstance(axis, FixedAxis) and any(entry.code is None for entry in axis.sheets):
            totals = _linkbase.read_default_sheets(package, module_table.rendering)
            unnamed = [entry for entry in axis.sheets if entry.code is None]
            if len(unnamed) == 1 and len(totals) == 1 and totals[0][0]:
                code, label = totals[0]
                sheets = [
                    replace(e, code=code, label=label) if e.code is None else e for e in axis.sheets
                ]
                axis = replace(axis, sheets=tuple(sorted(sheets, key=lambda e: e.code or "")))
                note(f"the all-default sheet has no code in the workbook; taxonomy names it {code}")
            else:
                note(
                    f"{len(unnamed)} all-default sheets in the workbook against {len(totals)} "
                    "aspect-less z nodes in the table linkbase - left without a code"
                )
        named.append(axis)
    return tuple(named)


# ── Private helpers: reading a sheet ──────────────────────────────────────────


def _read_axes(
    sheet: SheetGrid,
    workbook: AnnotatedWorkbook,
    dictionary: Dictionary,
    grid: Grid,
    note: Recorder,
) -> tuple[FixedAxis | OpenAxis, ...]:
    """Read the z-axis rows between the title and the column headers.

    A z-axis row has its label in column A and a dropdown in column B listing a row
    of the ``Enumerations`` sheet. For the k-th axis, row 1 column C+k names the
    dimension of an OPEN axis and is empty for a fixed list of sheets.
    """
    axes: list[FixedAxis | OpenAxis] = []
    for row in range(3, grid.code_row):
        formula = sheet.dropdown_at(row, 2)
        if formula is None:
            continue
        position = len(axes)
        code, label = parse_axis_label(sheet.value(row, 1) or "")
        entries = workbook.enumeration(formula)
        if entries is None:
            note(f"z-axis dropdown {formula!r} does not point at the Enumerations sheet")
            entries = ()
        dimension = parse_dimension_header(sheet.value(1, 3 + position) or "")
        if dimension is not None:
            members = tuple(m for m in map(parse_member, entries) if m)
            info = dictionary.dimensions.get(dimension)
            default = info.default if info else None
            axes.append(OpenAxis(code, label, dimension, members, default in members))
            continue
        if sheet.value(1, 3 + position):
            note(f"row-1 z-dimension cell is not a dimension: {sheet.value(1, 3 + position)!r}")
        sheets: list[SheetEntry] = []
        for number, entry in enumerate(entries, 1):
            parsed = parse_sheet_entry(entry)
            if parsed is None:
                note(f"z-axis entry {number} does not parse and was ignored: {entry[:80]!r}")
            else:
                sheets.append(parsed)
        if len({entry.code for entry in sheets}) != len(sheets):
            note("duplicate sheet codes on a fixed z-axis")
        axes.append(FixedAxis(code, label, tuple(sorted(sheets, key=lambda e: e.code or ""))))
    return tuple(axes)


def _read_open_keys(
    sheet: SheetGrid,
    workbook: AnnotatedWorkbook,
    dictionary: Dictionary,
    grid: Grid,
    note: Recorder,
) -> tuple[OpenKey, ...]:
    """Read open-row key columns: code and label from the header, dimension from its comment."""
    keys: list[OpenKey] = []
    for column in grid.key_columns:
        header = KEY_HEADER.match(sheet.value(grid.code_row, column) or "")
        comment = parse_key_comment(sheet.comments.get((grid.code_row, column), ""))
        where = _workbook.address(grid.code_row, column)
        if header is None or comment is None:
            note(f"open-row key {where} has no comment naming its dimension; key ignored")
            continue
        dimension, listed = comment
        info = dictionary.dimensions.get(dimension)
        if info is None:
            note(f"key dimension {dimension} is not in the dictionary")
        members: tuple[str, ...] = ()
        if listed:
            formula = sheet.dropdown_at(grid.code_row + 1, column)
            entries = workbook.enumeration(formula) if formula else None
            if entries is None:
                note(f"explicit open-row key {dimension} has no dropdown list")
            members = tuple(m for m in map(parse_member, entries or ()) if m)
        elif info is None or info.typed_element is None:
            note(
                f"key dimension {dimension} lists no members but the dictionary has no typed element"
            )
        keys.append(
            OpenKey(
                code=header.group("code"),
                label=header.group("label").strip(),
                dimension=dimension,
                kind="explicit" if listed else "typed",
                typed_element=None if listed or info is None else info.typed_element,
                typed_type=None if listed or info is None else info.typed_type,
                members=members,
                default_allowed=bool(listed and info and info.default in members),
            )
        )
    return tuple(keys)


def _read_annotations(
    sheet: SheetGrid, grid: Grid, note: Recorder
) -> tuple[dict[int, Annotation], dict[int, Annotation]]:
    """Read the per-column block below the grid and the per-row block right of it.

    A block is headed by white cells reading ``Metrics`` or ``<dimension> (label)``:
    stacked in one column below the grid (values under each data column), or side
    by side in one row right of it (values on each data row).
    """
    headers = {
        cell: METRICS_HEADER if value == METRICS_HEADER else parse_dimension_header(value)
        for cell, value in sheet.values.items()
        if cell[0] >= 3 and cell not in sheet.grey
    }
    below = {c: h for c, h in headers.items() if h and c[0] > grid.last_row}
    right = {
        c: h for c, h in headers.items() if h and c[1] > grid.last_column and c[0] <= grid.last_row
    }
    if sum(1 for h in headers.values() if h == METRICS_HEADER) != 1:
        note("expected exactly one 'Metrics' header")
    if len({column for _, column in below}) > 1 or len({row for row, _ in right}) > 1:
        note("annotation headers are not aligned in one column (below) or one row (right)")
    columns = {line.index for line in grid.columns}
    rows = {line.index for line in grid.data_rows}
    on_columns: dict[int, dict[str, str]] = {}
    on_rows: dict[int, dict[str, str]] = {}
    for (row, column), value in sheet.values.items():
        if (
            (row, column) in sheet.grey
            or not value
            or (row, column) in headers
            and headers[(row, column)]
        ):
            continue
        for (header_row, header_column), header in below.items():
            if row == header_row and column > header_column and column in columns:
                _annotate(on_columns.setdefault(column, {}), header, value, row, column, note)
        for (header_row, header_column), header in right.items():
            if column == header_column and row > header_row and row in rows:
                _annotate(on_rows.setdefault(row, {}), header, value, row, column, note)
    return (
        {index: _to_annotation(found) for index, found in on_columns.items()},
        {index: _to_annotation(found) for index, found in on_rows.items()},
    )


def _annotate(
    found: dict[str, str],
    header: str,
    value: str,
    row: int,
    column: int,
    note: Recorder,
) -> None:
    """File one annotation value under its header (a metric or a dimension's member)."""
    if header == METRICS_HEADER:
        metric = parse_metric(value)
        if metric is None:
            note(f"metric cell {_workbook.address(row, column)} does not parse: {value[:60]!r}")
            return
        found[METRICS_HEADER] = metric[0]
        if metric[1]:
            found["[]"] = metric[1]
        return
    member = parse_member(value)
    if member is None:
        note(f"member cell {_workbook.address(row, column)} does not parse: {value[:60]!r}")
        return
    found[header] = member


def _to_annotation(found: Mapping[str, str]) -> Annotation:
    """Freeze the values collected for one row or column."""
    return Annotation(
        metric=found.get(METRICS_HEADER),
        enumeration=found.get("[]"),
        dims={k: v for k, v in found.items() if k not in {METRICS_HEADER, "[]"}},
    )


# ── Private helpers: assembling the pack ──────────────────────────────────────


def _assemble(
    tables: list[CompiledTable],
    dictionary: Dictionary,
    irregularities: list[str],
) -> dict[str, Any]:
    """Intern data points in first-use order and build the pack's sections."""
    index: dict[tuple[str, tuple[str, ...]], int] = {}
    enumerations: dict[str, tuple[str, ...]] = {}
    out_tables: dict[str, Any] = {}
    for table in tables:
        cells = [
            [c.row, c.column, c.sheet, index.setdefault((c.metric, c.dims), len(index)), c.source]
            for c in table.cells
        ]
        for hierarchy, members in table.enumerations.items():
            if enumerations.setdefault(hierarchy, members) != members:
                irregularities.append(
                    f"{table.layout.code}: enumeration {hierarchy} differs from another table's list"
                )
        out_tables[table.layout.code] = _table_section(table, cells)
    metrics: dict[str, Any] = {}
    dimensions: dict[str, Any] = {}
    for metric, dims in index:
        if metric not in metrics:
            metrics[metric] = _metric_section(metric, dictionary, irregularities)
        for dim in dims[0::2]:
            if dim not in dimensions:
                dimensions[dim] = _dimension_section(dim, dictionary, irregularities)
    for metric, section in metrics.items():
        if section["enumeration"] and section["enumeration"] not in enumerations:
            irregularities.append(f"enumeration metric {metric} has no member list in the workbook")
    qnames = [q for metric, dims in index for q in (metric, *dims)]
    qnames += [m for members in enumerations.values() for m in members]
    qnames += [q for d in dimensions.values() for q in (d["default"], d["typed_element"]) if q]
    for table in tables:
        for axis in table.layout.axes:
            qnames += list(axis.members) if isinstance(axis, OpenAxis) else []
        qnames += [m for key in table.layout.open_keys for m in key.members]
    prefixes = sorted(
        {q.removeprefix(MEMBER_TYPED_PREFIX).partition(":")[0] for q in qnames if ":" in q[1:]}
    )
    return {
        "namespaces": {prefix: namespace_for_prefix(prefix) for prefix in prefixes},
        "metrics": dict(sorted(metrics.items())),
        "dimensions": dict(sorted(dimensions.items())),
        "enumerations": {h: list(m) for h, m in sorted(enumerations.items())},
        "tables": out_tables,
        "datapoints": [[metric, list(dims)] for metric, dims in index],
    }


def _table_section(table: CompiledTable, cells: list[list[Any]]) -> dict[str, Any]:
    """One table of the pack, in the documented key order."""
    layout = table.layout
    axes: list[dict[str, Any]] = []
    for axis in layout.axes:
        if isinstance(axis, FixedAxis):
            sheets = [
                {"code": e.code, "label": e.label, "members": [list(m) for m in e.members]}
                for e in axis.sheets
            ]
            axes.append({"kind": "fixed", "code": axis.code, "label": axis.label, "sheets": sheets})
        else:
            axes.append({"kind": "open", **asdict(axis), "members": list(axis.members)})
    keys = [
        {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in asdict(key).items()
            if k != "default_allowed"
        }
        for key in layout.open_keys
    ]
    return {
        "title": layout.title,
        "group": table.group,
        "filing_indicator": table.filing_indicator,
        "rows": [[line.code, line.label] for line in layout.grid.rows],
        "columns": [[line.code, line.label] for line in layout.grid.columns],
        "open_rows": bool(layout.grid.key_columns),
        "open_keys": keys,
        "z": axes,
        "cells": cells,
    }


def _metric_section(
    metric: str, dictionary: Dictionary, irregularities: list[str]
) -> dict[str, Any]:
    """A metric's data type, period, label and enumeration hierarchy."""
    info = dictionary.metrics.get(metric)
    if info is None:
        irregularities.append(f"metric {metric} is not in the dictionary")
        return {"type": None, "period": None, "label": None, "enumeration": None}
    return asdict(info)


def _dimension_section(
    dim: str, dictionary: Dictionary, irregularities: list[str]
) -> dict[str, Any]:
    """A dimension's label, domain, kind, default member and typed element."""
    info = dictionary.dimensions.get(dim)
    if info is None:
        irregularities.append(f"dimension {dim} is not in the dictionary")
        return {
            "label": None,
            "domain": None,
            "kind": "explicit",
            "default": None,
            "typed_element": None,
            "typed_type": None,
        }
    return asdict(info)


def _version(workbook: AnnotatedWorkbook, irregularities: list[str]) -> str | None:
    """The taxonomy version, from the workbook's title line or else its file name."""
    for text in (workbook.title or "", workbook.file_name):
        match = VERSION.search(text)
        if match:
            return match.group(1)
    irregularities.append("no 'vN.N.N' version in the workbook title or file name")
    return None
