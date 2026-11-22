"""
Taxonomy pack — the on-disk format, the loader, and the packaged-pack index.

Pipeline position:
    compiler.compile_pack  ->  write_pack  ->  taxonomy/data/<module>-<version>/
    rwa_filer.release.resolve_release  ->  load_packaged(key)  ->  TaxonomyPack
        ->  validate.structure / xbrl writer

Key responsibilities:
- Define what a pack IS at runtime: for one reporting module at one taxonomy
  version, every table with its rows, columns and sheet (z) axes, and for every
  reportable cell the data point it maps to — a metric plus dimension members.
- Persist a compiled pack as three small files and read them back unchanged:
  ``pack.json`` (everything a human might review — tables, axes, metrics,
  dimensions), ``cells.arrow`` and ``datapoints.arrow`` (the two large tables,
  as Arrow IPC files, which Polars reads directly).
- Index the packaged packs by ``<module>-<version>`` and read each one's
  identity and dates (``pack_info``) without loading its tables. Which pack a
  run uses is ``rwa_filer.release``'s decision, made by release, never here.
- Be the one home for what other modules work out from a loaded pack and want
  to keep (``TaxonomyPack.derived``): kept in the pack object, so it lasts
  exactly as long as the pack does.

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

import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import date
from functools import cache, cached_property
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer._gc import collector_paused

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
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
#: The files a pack is, in the order its digest reads them.
_PACK_FILES: Final = (PACK_FILE, CELLS_FILE, DATAPOINTS_FILE)

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

#: Where a pack object keeps what has been worked out from it
#: (``TaxonomyPack.derived``): an entry of the instance dictionary that is not a
#: field, so equality, ``repr``, ``dataclasses.fields`` and
#: ``dataclasses.replace`` never see it.
_DERIVED: Final = "_derived"

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
    """No pack is packaged under the requested ``<module>-<version>`` key."""


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

    The sheet axes and the code tuples are worked out from the fields on first
    use and kept on the table (``cached_property``): they are read for every
    fact placed and every code looked up, and the fields they come from never
    change. A table made with ``dataclasses.replace`` is a new object that has
    kept nothing. The class must therefore stay without ``__slots__``.
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

    @cached_property
    def fixed_axis(self) -> ZAxis | None:
        """The table's fixed sheet axis, if it has one."""
        return next((axis for axis in self.z_axes if axis.kind == AXIS_FIXED), None)

    @cached_property
    def open_axis(self) -> ZAxis | None:
        """The table's open sheet axis, if it has one."""
        return next((axis for axis in self.z_axes if axis.kind == AXIS_OPEN), None)

    @cached_property
    def sheet_codes(self) -> tuple[str, ...]:
        """The codes of the fixed sheets, in the publisher's order."""
        axis = self.fixed_axis
        return tuple(sheet.code for sheet in axis.sheets) if axis else ()

    @cached_property
    def row_codes(self) -> tuple[str, ...]:
        """The fixed row codes, in the publisher's order."""
        return tuple(code for code, _label in self.rows)

    @cached_property
    def column_codes(self) -> tuple[str, ...]:
        """The column codes, in the publisher's order."""
        return tuple(code for code, _label in self.columns)

    def row_code(self, written: str) -> str:
        """``written`` as this table writes that row code (see ``match_code``)."""
        return match_code(self.row_codes, written)

    def column_code(self, written: str) -> str:
        """``written`` as this table writes that column code."""
        return match_code(self._key_and_column_codes, written)

    def sheet_code(self, written: str) -> str:
        """``written`` as this table writes that sheet code."""
        return match_code(self.sheet_codes, written)

    @cached_property
    def key_codes(self) -> tuple[str, ...]:
        """The key-column codes of an open-row table; empty for any other."""
        return tuple(key.code for key in self.open_keys)

    @cached_property
    def _key_and_column_codes(self) -> tuple[str, ...]:
        """Every code a column lookup is matched against: the key codes, then the column codes."""
        return (*self.key_codes, *self.column_codes)

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
    #: SHA-256 over the pack's three files as loaded (see ``load_pack``), so a
    #: report names exactly the pack it was validated against; ``None`` for a
    #: pack built in memory.
    content_sha256: str | None = None

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

    def derived[T](self, build: Callable[[TaxonomyPack], T]) -> T:
        """``build(self)``, worked out on first request and kept with this pack.

        The one home for a value that is a pure function of the pack and
        costly to rebuild, such as an index over its data points. ``build`` is
        both the recipe and the key: pass a module-level function or a class.
        A lambda or closure made at the call site is a new key every time, so
        it would be rebuilt on every call and every result kept.

        Where the value lives. In the pack object and nowhere else: there is
        no table beside the packs and nothing is keyed by ``id()``, so a value
        lasts exactly as long as its pack. A pack made with
        ``dataclasses.replace`` is a new object and starts with nothing; so
        does a copied or unpickled pack (``__getstate__``). The pack's
        equality, ``repr`` and ``dataclasses.fields`` read its fields and are
        unchanged by anything kept here.

        Written once. Two threads that ask at the same moment may both run
        ``build``, but both are handed the object stored first, so every
        caller in the process holds the same one. ``build`` must therefore be
        safe to run twice, and what it returns is shared by every user of the
        pack: it must never be changed afterwards.
        """
        kept: dict[Callable[..., Any], Any] = self.__dict__.setdefault(_DERIVED, {})
        try:
            return kept[build]
        except KeyError:
            return kept.setdefault(build, build(self))

    def __getstate__(self) -> dict[str, Any]:
        """The fields alone, so a copy or a pickle of a pack carries nothing derived.

        What has been derived can be large and need not be picklable; leaving
        it behind keeps copying and pickling a pack exactly what they were.
        """
        return {name: value for name, value in self.__dict__.items() if name != _DERIVED}


def match_code(codes: Sequence[str], written: str) -> str:
    """``written`` as one of ``codes`` writes it, where it differs only in leading zeros.

    Row, column and sheet codes are numbers written at a fixed width, and the
    width is not the same everywhere: most tables write four digits (``0010``),
    some of the older ones three (``010``). A code that has lost or gained
    leading zeros on the way — ``10`` from a spreadsheet, ``0010`` for a
    three-digit table — still names exactly one row.

    Returns ``written`` unchanged when it is already one of ``codes``, is not
    a number, or matches none or more than one of them: an unknown code stays
    as the source wrote it, for the structure check to report.
    """
    if written in codes or not written.isdigit():
        return written
    number = int(written)
    matches = [code for code in codes if code.isdigit() and int(code) == number]
    return matches[0] if len(matches) == 1 else written


# =============================================================================
# Public API — resolve and load
# =============================================================================


@cache
def available_packs() -> tuple[PackInfo, ...]:
    """Every packaged pack's ``PackInfo``, ordered by module then validity."""
    root = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY)
    if not root.is_dir():
        return ()
    infos = [info for entry in root.iterdir() if (info := pack_info(entry.name)) is not None]
    return tuple(sorted(infos, key=lambda info: (info.module, info.valid_from, info.version)))


@cache
def pack_info(key: str) -> PackInfo | None:
    """The ``PackInfo`` of the pack packaged under ``key``, or ``None`` if there is none.

    Reads only the pack's ``info`` block: the tables, cells and data points
    are not loaded.
    """
    resource = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, key, PACK_FILE)
    if not resource.is_file():
        return None
    return _info_from_json(json.loads(resource.read_text(encoding="utf-8"))["info"])


@cache
def load_packaged(key: str) -> TaxonomyPack:
    """Load the packaged pack in directory ``key`` (``<module>-<version>``)."""
    directory = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, key)
    if not directory.joinpath(PACK_FILE).is_file():
        raise PackNotFoundError(f"No packaged taxonomy pack named {key!r}")
    return load_pack(directory)


@collector_paused()
def load_pack(directory: Traversable | Path) -> TaxonomyPack:
    """Read a pack from ``directory`` (the three files ``write_pack`` produces).

    Runs with the cyclic garbage collector paused (``rwa_filer._gc``): a pack
    is tens of thousands of objects that are kept and hold no cycles, and the
    collector re-walking them as they were built was about half of a cold
    load. The collector is left as the caller had it.

    Raises:
        ValueError: the directory holds a pack in a format this version cannot
            read. (A packaging error, not a data condition, so it raises.)
    """
    raw = {name: directory.joinpath(name).read_bytes() for name in _PACK_FILES}
    payload = json.loads(raw[PACK_FILE].decode("utf-8"))
    if payload.get("format") != PACK_FORMAT:
        raise ValueError(
            f"Taxonomy pack format {payload.get('format')!r} is not supported "
            f"(this version reads format {PACK_FORMAT})"
        )
    cells = pl.read_ipc(io.BytesIO(raw[CELLS_FILE]))
    datapoints = pl.read_ipc(io.BytesIO(raw[DATAPOINTS_FILE]))
    return TaxonomyPack(
        info=_info_from_json(payload["info"]),
        namespaces=dict(payload["namespaces"]),
        metrics={qname: _metric(qname, raw) for qname, raw in payload["metrics"].items()},
        dimensions={qname: _dimension(qname, raw) for qname, raw in payload["dimensions"].items()},
        enumerations={name: tuple(members) for name, members in payload["enumerations"].items()},
        tables={code: _table(code, raw) for code, raw in payload["tables"].items()},
        cells=cells.select(CELL_SCHEMA.names()).cast(CELL_SCHEMA),
        datapoints=_datapoints_from_frame(datapoints),
        content_sha256=_content_digest(raw),
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


def _content_digest(raw: Mapping[str, bytes]) -> str:
    """SHA-256 over each file's name, length and bytes, in ``_PACK_FILES`` order."""
    digest = hashlib.sha256()
    for name in _PACK_FILES:
        content = raw[name]
        digest.update(f"{name}\0{len(content)}\0".encode())
        digest.update(content)
    return digest.hexdigest()


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
    """Rebuild the indexed data points from their frame, checking the index is dense.

    Equal (dimension, member) pairs are one shared tuple. PRA001's 61,428 data
    points name 518,270 pairs of which 1,442 are distinct, and building a tuple
    for each one was most of a cold pack load. The value is the same either
    way — ``tests/taxonomy/test_pack_datapoints.py`` holds every data point of
    every packaged pack to a row-by-row build — and a table the shared build
    cannot take (see ``_shared_pairs``) is read one row at a time, as before.
    """
    ordered = _in_index_order(frame)
    metrics = ordered["metric"].to_list()
    dimensions, members = ordered["dimensions"], ordered["members"]
    shared = _shared_pairs(dimensions, members)
    if shared is None:
        return tuple(
            DataPoint(metric, tuple(zip(named, chosen, strict=True)))
            for metric, named, chosen in zip(
                metrics, dimensions.to_list(), members.to_list(), strict=True
            )
        )
    pairs, sizes = shared
    points: list[DataPoint] = []
    start = 0
    for metric, size in zip(metrics, sizes, strict=True):
        points.append(DataPoint(metric, pairs[start : start + size]))
        start += size
    return tuple(points)


def _in_index_order(frame: pl.DataFrame) -> pl.DataFrame:
    """``frame`` in data-point order, once its index is known to be dense from 0.

    ``write_pack`` writes the table in that order, so the sort — a copy of every
    list in it — is skipped when a whole-number index already reads 0, 1, 2, ...
    Such an index is strictly increasing, so sorting by it would change nothing.
    """
    dense = list(range(frame.height))
    if "datapoint" in frame.columns:
        index = frame["datapoint"]
        if index.dtype.is_integer() and index.to_list() == dense:
            return frame
    ordered = frame.sort("datapoint")
    if ordered["datapoint"].to_list() != dense:
        raise ValueError("Taxonomy pack data points are not densely indexed from 0")
    return ordered


def _shared_pairs(
    dimensions: pl.Series, members: pl.Series
) -> tuple[tuple[tuple[str, str], ...], list[int]] | None:
    """Every data point's pairs laid end to end, equal pairs one object, and each point's count.

    ``None`` for a table this cannot be done for: columns that are not lists of
    strings, a null list, lists of unequal length, or a null inside a list. The
    caller reads such a table row by row, so a damaged pack gives exactly the
    value or the error it always gave.
    """
    listed = pl.List(pl.String)
    if dimensions.dtype != listed or members.dtype != listed:
        return None
    if dimensions.null_count() or members.null_count():
        return None
    sizes = dimensions.list.len().to_list()
    if sizes != members.list.len().to_list():
        return None
    # Empty lists are dropped before the lists are laid end to end, so the two
    # spellings of ``explode`` below give the same rows.
    filled = pl.DataFrame({"dimensions": dimensions, "members": members}).filter(
        pl.col("dimensions").list.len() > 0
    )
    try:
        flat = filled.explode("dimensions", "members", empty_as_null=False)
    except TypeError:
        # A Polars from before ``explode`` took ``empty_as_null``. Newer ones
        # warn when it is left out, which is why it is tried first.
        flat = filled.explode("dimensions", "members")
    if flat["dimensions"].null_count() or flat["members"].null_count():
        return None
    distinct = flat.unique(maintain_order=True).with_row_index("_pair")
    # A join does not promise to keep the left table's order on every Polars
    # this package runs on; the row number restores it.
    numbered = (
        flat.with_row_index("_at")
        .join(distinct, on=["dimensions", "members"], how="left")
        .sort("_at")
    )
    values = list(zip(distinct["dimensions"].to_list(), distinct["members"].to_list(), strict=True))
    return tuple([values[number] for number in numbered["_pair"].to_list()]), sizes
