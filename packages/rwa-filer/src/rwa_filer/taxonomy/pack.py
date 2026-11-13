"""
Taxonomy pack — the on-disk format, the loader, and the resolver by reference date.

Pipeline position:
    compiler.compile_pack  ->  write_pack  ->  taxonomy/data/<module>-<version>/
    resolve_pack(module, reference_date)  ->  TaxonomyPack
        ->  validate.structure / xbrl writer

Key responsibilities:
- Define what a pack IS at runtime: for one reporting module at one taxonomy
  version, every table with its rows, columns and sheet (z) axes, and for every
  reportable cell the data point it maps to — a metric plus dimension members.
- Persist a compiled pack as three small files and read them back unchanged:
  ``pack.json`` (everything a human might review — tables, axes, metrics,
  dimensions), ``cells.arrow`` and ``datapoints.arrow`` (the two large tables,
  as Arrow IPC files, which Polars reads directly).
- Resolve the pack in force on a reference date. A return is always read
  against the taxonomy that applied on its own date, never "the latest".

Why package data and not a taxonomy parser: an XBRL taxonomy for one module is
hundreds of megabytes of linkbase XML, and loading it is the slow, memory-hungry
step. Everything this package needs from it is a few hundred kilobytes once
compiled, and compiling is a one-off, offline, reviewable step — the same
bargain the rule extracts in ``rwa_filer.rules`` make.

Open members. A data point normally fixes every dimension member. Where the
filer chooses the member, the pack holds a placeholder instead:
``*open`` (an explicit dimension whose member comes from the sheet or key),
``*open?`` (the same, but the dimension's default is allowed, so it may be
absent) and ``*typed:<element>`` (a typed dimension taking any value).

References:
- Bank of England Banking Taxonomy — DPM dictionary, annotated templates, XBRL
  taxonomy package
- BoE XBRL Filing Manual — the entry point a report's ``schemaRef`` must name
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from importlib.resources.abc import Traversable
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The compiled-pack layout this module reads and writes.
PACK_FORMAT: Final = 1

#: Where packaged packs live: one directory per ``<module>-<version>``.
PACKS_PACKAGE: Final = "rwa_filer.taxonomy"
PACKS_DIRECTORY: Final = "data"

PACK_FILE: Final = "pack.json"
#: The two large tables are Arrow IPC files. Deliberately NOT Parquet: this
#: repository git-ignores ``*.parquet`` (its test fixtures are build artefacts),
#: and the build backend honours that ignore file — a Parquet pack would be
#: neither committed nor shipped in the wheel, and would work only on the
#: machine that compiled it.
CELLS_FILE: Final = "cells.arrow"
DATAPOINTS_FILE: Final = "datapoints.arrow"

#: Sheet (z) axis kinds.
AXIS_FIXED: Final = "fixed"
AXIS_OPEN: Final = "open"

#: Dimension kinds.
DIMENSION_EXPLICIT: Final = "explicit"
DIMENSION_TYPED: Final = "typed"

#: Placeholders a data point holds where the filer supplies the member.
MEMBER_OPEN: Final = "*open"
MEMBER_OPEN_OPTIONAL: Final = "*open?"
MEMBER_TYPED_PREFIX: Final = "*typed:"

#: Where a cell's reportability was established.
SOURCE_WORKBOOK: Final = "workbook"
SOURCE_LINKBASE: Final = "linkbase"

#: The cell table, in column order. ``sheet`` is null for a table with no fixed
#: sheet axis; ``row`` is null for an open-row table, whose rows the filer keys.
CELL_SCHEMA: Final = pl.Schema(
    {
        "table": pl.String,
        "row": pl.String,
        "column": pl.String,
        "sheet": pl.String,
        "datapoint": pl.UInt32,
        "source": pl.String,
    }
)

#: The data-point table. ``dimensions`` and ``members`` are parallel lists,
#: sorted by dimension QName.
DATAPOINT_SCHEMA: Final = pl.Schema(
    {
        "datapoint": pl.UInt32,
        "metric": pl.String,
        "dimensions": pl.List(pl.String),
        "members": pl.List(pl.String),
    }
)


class PackNotFoundError(LookupError):
    """No packaged taxonomy applies to the requested module and reference date."""


# =============================================================================
# The pack
# =============================================================================


@dataclass(frozen=True)
class PackInfo:
    """What a pack is, and when it applies.

    Attributes:
        module: The reporting module (entry point) code, e.g. ``"PRA001"``.
        title: The publisher's name for the module.
        taxonomy: The taxonomy family, e.g. ``"boe-banking"``.
        version: The taxonomy release, e.g. ``"4.1.1"``.
        entry_point: The URL a report's ``schemaRef`` must name.
        valid_from: First reference date the pack applies to.
        valid_to: Last reference date it applies to; ``None`` while it is the
            current release.
    """

    module: str
    title: str
    taxonomy: str
    version: str
    entry_point: str
    valid_from: date
    valid_to: date | None = None

    @property
    def key(self) -> str:
        """The pack's directory name: ``<module>-<version>``, lower case."""
        return f"{self.module}-{self.version}".lower()

    def applies_to(self, reference_date: date) -> bool:
        """Whether a return for ``reference_date`` is read against this pack."""
        if reference_date < self.valid_from:
            return False
        return self.valid_to is None or reference_date <= self.valid_to


@dataclass(frozen=True)
class Metric:
    """One metric (the primary item a fact reports).

    ``data_type`` is the DPM type: ``monetary`` / ``percentage`` / ``integer`` /
    ``decimal`` / ``string`` / ``boolean`` / ``date`` / ``enumeration``. An
    enumeration metric names the hierarchy its value must come from.
    """

    qname: str
    data_type: str
    period: str
    label: str
    enumeration: str | None = None

    @property
    def is_numeric(self) -> bool:
        """Whether a fact for this metric carries a number rather than text."""
        return self.data_type in _NUMERIC_TYPES


@dataclass(frozen=True)
class Dimension:
    """One dimension: explicit (members from a domain) or typed (any value)."""

    qname: str
    label: str
    domain: str | None
    kind: str
    default: str | None = None
    typed_element: str | None = None
    typed_type: str | None = None


@dataclass(frozen=True)
class Sheet:
    """One sheet of a fixed z-axis: its code and the members it fixes."""

    code: str
    label: str
    members: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ZAxis:
    """One sheet (z) axis of a table.

    A ``fixed`` axis is a closed list of ``sheets``, each addressed by its code.
    An ``open`` axis has the filer choose a member of ``dimension`` from
    ``members``; ``default_allowed`` says the dimension's default member is in
    that list, i.e. a sheet for "all" / "total" exists and is reported with the
    dimension absent.
    """

    kind: str
    code: str
    label: str
    sheets: tuple[Sheet, ...] = ()
    dimension: str | None = None
    members: tuple[str, ...] = ()
    default_allowed: bool = False


@dataclass(frozen=True)
class OpenKey:
    """One key column of an open-row table — the dimension a row is keyed by."""

    code: str
    label: str
    dimension: str
    kind: str
    typed_element: str | None = None
    typed_type: str | None = None
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class Table:
    """One table of a module, in the publisher's own coordinates.

    ``filing_indicator`` is the code reported when the table is filed; several
    tables can share one. ``open_rows`` marks a table with no fixed row list,
    whose rows are keyed by ``open_keys``.
    """

    code: str
    title: str
    group: str
    filing_indicator: str
    rows: tuple[tuple[str, str], ...]
    columns: tuple[tuple[str, str], ...]
    open_rows: bool = False
    open_keys: tuple[OpenKey, ...] = ()
    z_axes: tuple[ZAxis, ...] = ()

    @property
    def fixed_axis(self) -> ZAxis | None:
        """The table's fixed sheet axis, if it has one."""
        return next((axis for axis in self.z_axes if axis.kind == AXIS_FIXED), None)

    @property
    def open_axis(self) -> ZAxis | None:
        """The table's open sheet axis, if it has one."""
        return next((axis for axis in self.z_axes if axis.kind == AXIS_OPEN), None)

    @property
    def sheet_codes(self) -> tuple[str, ...]:
        """The codes of the fixed sheets, in the publisher's order."""
        axis = self.fixed_axis
        return tuple(sheet.code for sheet in axis.sheets) if axis else ()

    @property
    def row_codes(self) -> tuple[str, ...]:
        """The fixed row codes, in the publisher's order."""
        return tuple(code for code, _label in self.rows)

    @property
    def column_codes(self) -> tuple[str, ...]:
        """The column codes, in the publisher's order."""
        return tuple(code for code, _label in self.columns)

    @property
    def key_codes(self) -> tuple[str, ...]:
        """The key-column codes of an open-row table; empty for any other."""
        return tuple(key.code for key in self.open_keys)

    @property
    def entry_columns(self) -> tuple[tuple[str, str], ...]:
        """Every column a filer fills in: the key columns first, then the data columns.

        The key columns of an open-row table carry no data point of their own
        — a key is the dimension member the row's facts are reported under —
        so ``columns`` does not list them.
        """
        listed = set(self.column_codes)
        keys = tuple((key.code, key.label) for key in self.open_keys if key.code not in listed)
        return keys + self.columns


@dataclass(frozen=True)
class DataPoint:
    """A metric plus its dimension members — what one XBRL fact reports."""

    metric: str
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TaxonomyPack:
    """One module's data-point model at one taxonomy version.

    ``cells`` is the reportable-cell table (``CELL_SCHEMA``): one row per
    (table, row, column, sheet) the regulator accepts, with the index of the
    data point it maps to. ``datapoints`` is indexed by that number. The same
    data point can appear in more than one cell — some figures are shown in two
    tables — and is then reported once.
    """

    info: PackInfo
    namespaces: Mapping[str, str]
    metrics: Mapping[str, Metric]
    dimensions: Mapping[str, Dimension]
    enumerations: Mapping[str, tuple[str, ...]]
    tables: Mapping[str, Table]
    cells: pl.DataFrame
    datapoints: tuple[DataPoint, ...]

    def table(self, code: str) -> Table | None:
        """The table with this code, or ``None`` if the module has none."""
        return self.tables.get(code)

    def datapoint(self, index: int) -> DataPoint:
        """The data point a cell's ``datapoint`` index refers to."""
        return self.datapoints[index]

    @property
    def filing_indicators(self) -> tuple[str, ...]:
        """Every filing-indicator code of the module, sorted and distinct."""
        return tuple(sorted({table.filing_indicator for table in self.tables.values()}))

    def datapoint_frame(self) -> pl.DataFrame:
        """The data points as a frame (``DATAPOINT_SCHEMA``), for joins."""
        return _datapoint_frame(self.datapoints)


# =============================================================================
# Public API — resolve and load
# =============================================================================


def resolve_pack(module: str, reference_date: date) -> TaxonomyPack:
    """The packaged taxonomy that applies to ``module`` on ``reference_date``.

    Raises:
        PackNotFoundError: no packaged pack covers that module and date. The
            message lists what IS packaged, because the usual cause is a
            reference date before the first packaged release.
    """
    return load_packaged(select_pack(available_packs(), module, reference_date).key)


def select_pack(infos: Iterable[PackInfo], module: str, reference_date: date) -> PackInfo:
    """Choose, from ``infos``, the pack for ``module`` on ``reference_date``.

    The module code is matched case-insensitively. Where two releases both
    cover the date — a packaging mistake — the later release wins, so the
    answer is at least deterministic, and it is logged.

    Raises:
        PackNotFoundError: none of ``infos`` covers that module and date.
    """
    candidates = tuple(infos)
    wanted = module.upper()
    matches = [
        info
        for info in candidates
        if info.module.upper() == wanted and info.applies_to(reference_date)
    ]
    if not matches:
        packaged = ", ".join(_describe(info) for info in candidates) or "none"
        raise PackNotFoundError(
            f"No taxonomy pack for module {module!r} on {reference_date.isoformat()}. "
            f"Packaged: {packaged}."
        )
    chosen = max(matches, key=lambda info: (info.valid_from, info.version))
    if len(matches) > 1:
        logger.warning(
            "%d taxonomy packs cover %s on %s; using %s",
            len(matches),
            module,
            reference_date.isoformat(),
            chosen.version,
        )
    return chosen


@cache
def available_packs() -> tuple[PackInfo, ...]:
    """Every packaged pack's ``PackInfo``, ordered by module then validity."""
    root = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY)
    if not root.is_dir():
        return ()
    infos = [
        _info_from_json(json.loads(entry.joinpath(PACK_FILE).read_text(encoding="utf-8"))["info"])
        for entry in root.iterdir()
        if entry.is_dir() and entry.joinpath(PACK_FILE).is_file()
    ]
    return tuple(sorted(infos, key=lambda info: (info.module, info.valid_from, info.version)))


@cache
def load_packaged(key: str) -> TaxonomyPack:
    """Load the packaged pack in directory ``key`` (``<module>-<version>``)."""
    directory = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, key)
    if not directory.joinpath(PACK_FILE).is_file():
        raise PackNotFoundError(f"No packaged taxonomy pack named {key!r}")
    return load_pack(directory)


def load_pack(directory: Traversable | Path) -> TaxonomyPack:
    """Read a pack from ``directory`` (the three files ``write_pack`` produces).

    Raises:
        ValueError: the directory holds a pack in a format this version cannot
            read. (A packaging error, not a data condition, so it raises.)
    """
    payload = json.loads(directory.joinpath(PACK_FILE).read_text(encoding="utf-8"))
    if payload.get("format") != PACK_FORMAT:
        raise ValueError(
            f"Taxonomy pack format {payload.get('format')!r} is not supported "
            f"(this version reads format {PACK_FORMAT})"
        )
    cells = pl.read_ipc(io.BytesIO(directory.joinpath(CELLS_FILE).read_bytes()))
    datapoints = pl.read_ipc(io.BytesIO(directory.joinpath(DATAPOINTS_FILE).read_bytes()))
    return TaxonomyPack(
        info=_info_from_json(payload["info"]),
        namespaces=dict(payload["namespaces"]),
        metrics={qname: _metric(qname, raw) for qname, raw in payload["metrics"].items()},
        dimensions={qname: _dimension(qname, raw) for qname, raw in payload["dimensions"].items()},
        enumerations={name: tuple(members) for name, members in payload["enumerations"].items()},
        tables={code: _table(code, raw) for code, raw in payload["tables"].items()},
        cells=cells.select(CELL_SCHEMA.names()).cast(CELL_SCHEMA),
        datapoints=_datapoints_from_frame(datapoints),
    )


# =============================================================================
# Public API — write
# =============================================================================


def write_pack(
    compiled: Mapping[str, Any],
    directory: Path,
    *,
    valid_from: date,
    valid_to: date | None = None,
) -> PackInfo:
    """Persist a compiled pack (``compiler.compile_pack``'s output) to ``directory``.

    The validity window is supplied here, not compiled: it is a fact about when
    the regulator requires a taxonomy, which no DPM file states.

    ``pack.json`` is written sorted, indented and pure ASCII so a taxonomy
    refresh shows up as a readable diff. The two Arrow files are written from
    frames sorted on their keys, so an unchanged compile yields equal content.

    Returns:
        The written pack's ``PackInfo``.

    Raises:
        ValueError: ``compiled`` is not a format-``PACK_FORMAT`` compiled pack.
    """
    if compiled.get("format") != PACK_FORMAT:
        raise ValueError(
            f"Expected a format-{PACK_FORMAT} compiled pack, got {compiled.get('format')!r}"
        )
    info = dict(compiled["info"])
    info["valid_from"] = valid_from.isoformat()
    info["valid_to"] = valid_to.isoformat() if valid_to is not None else None

    tables: dict[str, Any] = {}
    cell_rows: list[tuple[str, str | None, str, str | None, int, str]] = []
    for code, raw in compiled["tables"].items():
        tables[code] = {key: value for key, value in raw.items() if key != "cells"}
        for cell in raw["cells"]:
            row, column, sheet, datapoint = cell[:4]
            source = cell[4] if len(cell) > 4 else SOURCE_WORKBOOK
            cell_rows.append((code, row, column, sheet, datapoint, source))

    payload = {
        "format": PACK_FORMAT,
        "info": info,
        "namespaces": compiled["namespaces"],
        "metrics": compiled["metrics"],
        "dimensions": compiled["dimensions"],
        "enumerations": compiled["enumerations"],
        "tables": tables,
    }
    cells = pl.DataFrame(cell_rows, schema=CELL_SCHEMA, orient="row").sort(
        "table", "row", "column", "sheet", nulls_last=False
    )
    datapoints = _datapoint_frame(
        tuple(
            DataPoint(metric, tuple(zip(flat[0::2], flat[1::2], strict=True)))
            for metric, flat in compiled["datapoints"]
        )
    )

    directory.mkdir(parents=True, exist_ok=True)
    (directory / PACK_FILE).write_text(
        json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    cells.write_ipc(directory / CELLS_FILE, compression="zstd")
    datapoints.write_ipc(directory / DATAPOINTS_FILE, compression="zstd")
    written = _info_from_json(info)
    logger.info(
        "wrote taxonomy pack %s: %d tables, %d cells, %d data points",
        written.key,
        len(tables),
        cells.height,
        datapoints.height,
    )
    return written


# =============================================================================
# Private helpers
# =============================================================================

_NUMERIC_TYPES: Final[frozenset[str]] = frozenset({"monetary", "percentage", "integer", "decimal"})


def _describe(info: PackInfo) -> str:
    """One pack, as it reads in an error message."""
    until = info.valid_to.isoformat() if info.valid_to else "onwards"
    return f"{info.module} {info.version} ({info.valid_from.isoformat()} to {until})"


def _info_from_json(raw: Mapping[str, Any]) -> PackInfo:
    """Build a ``PackInfo`` from the ``info`` block of ``pack.json``."""
    valid_to = raw.get("valid_to")
    return PackInfo(
        module=raw["module"],
        title=raw.get("title", ""),
        taxonomy=raw.get("taxonomy", ""),
        version=raw["version"],
        entry_point=raw["entry_point"],
        valid_from=date.fromisoformat(raw["valid_from"]),
        valid_to=date.fromisoformat(valid_to) if valid_to else None,
    )


def _metric(qname: str, raw: Mapping[str, Any]) -> Metric:
    return Metric(
        qname=qname,
        data_type=raw["type"],
        period=raw.get("period", "instant"),
        label=raw.get("label", ""),
        enumeration=raw.get("enumeration"),
    )


def _dimension(qname: str, raw: Mapping[str, Any]) -> Dimension:
    return Dimension(
        qname=qname,
        label=raw.get("label", ""),
        domain=raw.get("domain"),
        kind=raw["kind"],
        default=raw.get("default"),
        typed_element=raw.get("typed_element"),
        typed_type=raw.get("typed_type"),
    )


def _table(code: str, raw: Mapping[str, Any]) -> Table:
    return Table(
        code=code,
        title=raw.get("title", ""),
        group=raw.get("group", ""),
        filing_indicator=raw["filing_indicator"],
        rows=tuple((row[0], row[1]) for row in raw.get("rows", ())),
        columns=tuple((column[0], column[1]) for column in raw.get("columns", ())),
        open_rows=bool(raw.get("open_rows", False)),
        open_keys=tuple(_open_key(key) for key in raw.get("open_keys", ())),
        z_axes=tuple(_z_axis(axis) for axis in raw.get("z", ())),
    )


def _open_key(raw: Mapping[str, Any]) -> OpenKey:
    return OpenKey(
        code=raw["code"],
        label=raw.get("label", ""),
        dimension=raw["dimension"],
        kind=raw["kind"],
        typed_element=raw.get("typed_element"),
        typed_type=raw.get("typed_type"),
        members=tuple(raw.get("members") or ()),
    )


def _z_axis(raw: Mapping[str, Any]) -> ZAxis:
    return ZAxis(
        kind=raw["kind"],
        code=raw.get("code", ""),
        label=raw.get("label", ""),
        sheets=tuple(
            Sheet(
                code=sheet["code"],
                label=sheet.get("label", ""),
                members=tuple((member[0], member[1]) for member in sheet.get("members", ())),
            )
            for sheet in raw.get("sheets", ())
        ),
        dimension=raw.get("dimension"),
        members=tuple(raw.get("members") or ()),
        default_allowed=bool(raw.get("default_allowed", False)),
    )


def _datapoint_frame(datapoints: tuple[DataPoint, ...]) -> pl.DataFrame:
    """Data points as a ``DATAPOINT_SCHEMA`` frame, indexed in order."""
    return pl.DataFrame(
        {
            "datapoint": list(range(len(datapoints))),
            "metric": [point.metric for point in datapoints],
            "dimensions": [[dim for dim, _member in point.dimensions] for point in datapoints],
            "members": [[member for _dim, member in point.dimensions] for point in datapoints],
        },
        schema=DATAPOINT_SCHEMA,
    )


def _datapoints_from_frame(frame: pl.DataFrame) -> tuple[DataPoint, ...]:
    """Rebuild the indexed data points from their frame, checking the index is dense."""
    ordered = frame.sort("datapoint")
    indices = ordered["datapoint"].to_list()
    if indices != list(range(len(indices))):
        raise ValueError("Taxonomy pack data points are not densely indexed from 0")
    return tuple(
        DataPoint(metric, tuple(zip(dimensions, members, strict=True)))
        for metric, dimensions, members in zip(
            ordered["metric"].to_list(),
            ordered["dimensions"].to_list(),
            ordered["members"].to_list(),
            strict=True,
        )
    )
