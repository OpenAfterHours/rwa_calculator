"""
Detail files - construct a return from contributions or select its supplied group.

Pipeline position:
    detail file (.parquet / .csv)  ->  read_detail  ->  (CanonicalReturn, ReturnDetail)
        ->  readers.open_source  ->  check_amounts (against the release's taxonomy)
        ->  validate (the summed return, like any other)
        ->  workflow.attribution (the rules again, on each part of the detail)

Key responsibilities:
- Read a fact table whose rows are parts of cells. Each row says where it came
  from in columns the person names — a business unit, a source system — and
  may carry a line reference that tells one line from another.
- Sum the rows of each cell into the one figure that is validated and filed,
  and keep the rows, so any figure can be split by any of those columns.
- Refuse what cannot be summed honestly, naming every case: the same line
  reference twice in one cell, several rows for a cell that is not an amount,
  a cell some rows give a number and others text. A refusal stops the whole
  file: a return with some of its rows quietly left out is one nobody can
  describe.
- With a group code, take the group's facts as supplied and keep the other
  units separately. Repeats and monetary aggregation are scoped to each unit.

What a line reference is: the identifier the source system gives each line — a
loan, a lease, a journal line. One loan is reported in many cells (its total,
its exposure type, its risk weight, on its class's sheet and the total sheet),
so a reference appears once in each cell it feeds. The same reference twice in
ONE cell is the same line counted twice. That is why it is checked: an extract
loaded twice breaks no published rule, because every total doubles with its
parts, and the return files the doubled figures.

Why only amounts are summed: a percentage, a count, a date or a piece of text
has no sum. Two rows for a PD cell are two answers, not two parts of one.

References:
- rwa_filer.model — the canonical fact schema the rows are summed onto
- rwa_filer.readers.tabular — how the file itself is read
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.model import (
    COORDINATE_COLUMNS,
    FACT_SCHEMA,
    CanonicalReturn,
    normalise_facts,
)
from rwa_filer.readers.tabular import read_table, table_columns

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import BinaryIO

    from rwa_filer.model import ReturnHeader
    from rwa_filer.taxonomy.pack import TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: A line reference repeated in one cell refuses the file.
ON_REPEAT_STOP: Final = "stop"
#: A repeat that agrees with the earlier row on everything is dropped; one that
#: differs refuses the file.
ON_REPEAT_KEEP_ONE: Final = "keep-one"
ON_REPEAT_CHOICES: Final = (ON_REPEAT_STOP, ON_REPEAT_KEEP_ONE)

#: The files a detail is read from.
DETAIL_SUFFIXES: Final = (".parquet", ".csv")

#: The one data type whose figures add up.
SUMMABLE_TYPE: Final = "monetary"

#: Problems quoted in a refusal; the count is always the full number.
MAX_PROBLEMS: Final = 8

#: A cell's full address: table, sheet, open-axis key, row, column.
type Cell = tuple[str, str | None, str | None, str, str]
#: A member of a breakdown column; ``None`` for a row that leaves the column empty.
type Member = str | None

#: Working column: where each row is in the file, for a refusal to point at.
LINE_COLUMN: Final = "_line"
_ROWS: Final = "_rows"
_COUNT: Final = "_count"
_KINDS: Final = "_kinds"
_NTH: Final = "_nth"


class DetailError(ValueError):
    """A detail file that cannot be summed into a return. Carries every problem found."""

    def __init__(self, file: str, problems: Sequence[str]) -> None:
        shown = "; ".join(problems[:MAX_PROBLEMS])
        more = f"; and {len(problems) - MAX_PROBLEMS} more" if len(problems) > MAX_PROBLEMS else ""
        super().__init__(f"{file}: {len(problems)} problem(s), so nothing was read: {shown}{more}.")
        self.problems = tuple(problems)


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class DetailSpec:
    """Which of a fact table's extra columns to read, and how.

    Attributes:
        breakdown: The columns that say where each row came from, in the order
            they are offered. Matched to the file's columns ignoring case and
            surrounding spaces.
        line_ref: The column that holds each line's reference, or ``None``.
        on_repeat: What a reference repeated in one cell does:
            ``ON_REPEAT_STOP`` refuses the file; ``ON_REPEAT_KEEP_ONE`` keeps
            the first of rows that agree on everything and refuses rows that
            do not.

    A spec with neither breakdown columns nor a line reference asks for
    nothing: the file is read as a fact table, one row per cell.
    """

    breakdown: tuple[str, ...] = ()
    line_ref: str | None = None
    on_repeat: str = ON_REPEAT_STOP
    #: Value of the reporting-unit column that contains the authoritative return.
    group_code: str | None = None

    def __post_init__(self) -> None:
        if self.group_code is not None and (
            len(self.breakdown) != 1 or not self.group_code.strip()
        ):
            raise ValueError("a group code requires one breakdown column and a non-empty code")
        if self.on_repeat not in ON_REPEAT_CHOICES:
            choices = ", ".join(ON_REPEAT_CHOICES)
            raise ValueError(f"on a repeated line reference: {self.on_repeat!r} is not {choices}")
        folded = [name.strip().lower() for name in self.breakdown]
        if len(set(folded)) != len(folded):
            raise ValueError("a breakdown column is named twice")
        if self.line_ref is not None and self.line_ref.strip().lower() in folded:
            raise ValueError(
                f"{self.line_ref!r} cannot be both a breakdown column and the line reference"
            )

    @property
    def active(self) -> bool:
        """Whether the file is read as a detail: rows summed into cells."""
        return bool(self.breakdown) or self.line_ref is not None

    @classmethod
    def from_text(
        cls,
        breakdown: str | None = None,
        line_ref: str | None = None,
        on_repeat: str | None = None,
        group_code: str | None = None,
    ) -> DetailSpec:
        """A spec from what a person typed: ``business_unit, source`` and a column name.

        Raises:
            ValueError: ``on_repeat`` is not one of ``ON_REPEAT_CHOICES``, or a
                column is named twice.
        """
        names = tuple(part.strip() for part in (breakdown or "").split(",") if part.strip())
        return cls(
            breakdown=names,
            line_ref=(line_ref or "").strip() or None,
            on_repeat=(on_repeat or "").strip() or ON_REPEAT_STOP,
            group_code=group_code.strip() if group_code is not None else None,
        )

    def as_record(self) -> dict[str, Any]:
        """A JSON-ready record, for a manifest or a report."""
        return {
            "breakdown": list(self.breakdown),
            "line_reference": self.line_ref,
            "on_repeat": self.on_repeat,
            **({"group_code": self.group_code} if self.group_code is not None else {}),
        }


@dataclass(frozen=True)
class Share:
    """One member's part of a cell: how much, from how many rows."""

    member: Member
    value: float
    rows: int


@dataclass(frozen=True, eq=False)
class ReturnDetail:
    """The rows a return was summed from, and what reading them established.

    Attributes:
        file: The detail file's name.
        spec: The columns read, named as the file names them.
        rows: The rows summed: ``FACT_SCHEMA``'s columns, each breakdown
            column, the line reference where there is one, and
            ``LINE_COLUMN`` — where the row is in the file.
        rows_read: Rows of the file that carry a figure.
        repeats_dropped: Rows dropped as exact repeats of an earlier one
            (``ON_REPEAT_KEEP_ONE``).

    Two details are equal only when they are the same object: their rows are
    a frame, which has no single truth value to compare by.
    """

    file: str
    spec: DetailSpec
    rows: pl.DataFrame
    rows_read: int
    repeats_dropped: int = 0
    group_rows: int = 0
    aligned_rows: pl.DataFrame | None = None

    @property
    def dimensions(self) -> tuple[str, ...]:
        """The breakdown columns, in the order they were asked for."""
        return self.spec.breakdown

    @property
    def comparison_rows(self) -> pl.DataFrame:
        """Unit rows in comparable coordinates; `rows` keeps the file's original addresses."""
        return self.aligned_rows if self.aligned_rows is not None else self.rows

    @property
    def cells(self) -> int:
        """How many cells the rows make."""
        return self.comparison_rows.select(COORDINATE_COLUMNS).unique().height

    @property
    def summed_cells(self) -> int:
        """How many cells are made of more than one row."""
        return (
            self.comparison_rows.group_by(COORDINATE_COLUMNS).len().filter(pl.col("len") > 1).height
        )

    def members(self, dimension: str) -> tuple[Member, ...]:
        """Every member of ``dimension``, by name, then ``None`` for rows that leave it empty.

        Raises:
            KeyError: ``dimension`` is not a breakdown column.
        """
        column = self._column(dimension)
        named = sorted(self.rows[column].drop_nulls().unique().to_list())
        blank = self.rows[column].null_count() > 0
        return (*named, *((None,) if blank else ()))

    def fed_by_several(self, dimension: str) -> int:
        """How many cells hold rows of more than one member of ``dimension``."""
        column = self._column(dimension)
        return (
            self.comparison_rows.group_by(COORDINATE_COLUMNS)
            .agg(pl.col(column).n_unique().alias(_COUNT))
            .filter(pl.col(_COUNT) > 1)
            .height
        )

    def cell_rows(self, cell: Cell) -> pl.DataFrame:
        """The rows of one cell, in the order the file gives them."""
        return self.comparison_rows.filter(_at(cell))

    def shares(self, cell: Cell, dimension: str) -> tuple[Share, ...]:
        """``cell`` split by ``dimension``: each member's amount, the largest first.

        Empty for a cell the detail has no figure for.
        """
        column = self._column(dimension)
        found = (
            self.cell_rows(cell)
            .filter(pl.col("value").is_not_null())
            .group_by(column)
            .agg(pl.col("value").sum(), pl.len().alias(_ROWS))
        )
        shares = [
            Share(member=member, value=float(value), rows=int(rows))
            for member, value, rows in found.iter_rows()
        ]
        return tuple(
            sorted(
                shares, key=lambda share: (-abs(share.value), share.member is None, share.member)
            )
        )

    def member_facts(self, dimension: str, member: Member) -> pl.DataFrame:
        """The facts ``member``'s rows alone make, summed as the return is (``FACT_SCHEMA``)."""
        column = self._column(dimension)
        return summed_facts(self.comparison_rows.filter(pl.col(column).eq_missing(member)))

    def as_record(self) -> dict[str, Any]:
        """A JSON-ready summary, for a manifest or a report."""
        return {
            "file": self.file,
            **self.spec.as_record(),
            "rows_read": self.rows_read,
            **(
                {"group_rows": self.group_rows, "unit_rows": self.rows.height}
                if self.spec.group_code is not None
                else {"rows_summed": self.rows.height}
            ),
            "repeats_dropped": self.repeats_dropped,
            "cells": self.cells,
            "cells_from_several_rows": self.summed_cells,
            "members": {dimension: len(self.members(dimension)) for dimension in self.dimensions},
        }

    def text_cells(self, ret: CanonicalReturn) -> list[dict[str, Any]]:
        """Reported text in the group and its units, including unit-only comments."""
        dimension = self.dimensions[0]
        columns = [*COORDINATE_COLUMNS, "text_value", dimension]
        group = ret.facts.filter(pl.col("text_value").is_not_null()).with_columns(
            pl.lit(self.spec.group_code, dtype=pl.String).alias(dimension)
        )
        units = self.rows.filter(pl.col("text_value").is_not_null())
        return pl.concat([group.select(columns), units.select(columns)]).to_dicts()

    def _column(self, dimension: str) -> str:
        if dimension not in self.spec.breakdown:
            raise KeyError(f"{dimension!r} is not a breakdown column of {self.file}")
        return dimension


def read_detail(
    path: Path, header: ReturnHeader, spec: DetailSpec
) -> tuple[CanonicalReturn, ReturnDetail]:
    """Read contributions or take the named reporting unit as the return.

    Args:
        path: A ``.parquet`` or ``.csv`` fact table with several rows per cell.
        header: Who is reporting and for which date; a fact table carries none.
        spec: The breakdown columns and line reference to read.

    Raises:
        ValueError: the file is not a fact table, or a column the spec names
            is not in it (or is one of the fact columns).
        DetailError: rows that cannot be summed, each named.
    """
    require_fact_table(path)
    frame = read_table(path)
    resolved = _resolve(spec, frame.columns, path.name)
    # A CSV's first line is its header, so the first data row is line 2: the
    # number a spreadsheet shows beside it. A Parquet file's rows count from 1.
    first = 2 if path.suffix.lower() == ".csv" else 1
    kept = [*resolved.breakdown, *((resolved.line_ref,) if resolved.line_ref else ())]
    rows = normalise_facts(
        frame.with_row_index(LINE_COLUMN, offset=first), keep=[*kept, LINE_COLUMN]
    ).with_columns(pl.col(LINE_COLUMN).cast(pl.Int64))
    rows_read = rows.height
    where = "line" if first == 2 else "row"  # noqa: PLR2004 - the offset chosen above
    group = None
    if resolved.group_code is not None:
        column = resolved.breakdown[0]
        selected = pl.col(column).eq_missing(resolved.group_code)
        if not frame.select(
            pl.col(column).cast(pl.String).str.strip_chars().eq_missing(resolved.group_code).any()
        ).item():
            raise ValueError(f"{path.name}: no {column} has group code {resolved.group_code!r}")
        group = rows.filter(selected).select(FACT_SCHEMA.names())
        rows = rows.filter(~selected)
    rows, dropped, problems = _drop_repeats(rows, resolved, where)
    scope = resolved.breakdown if group is not None else ()
    problems.extend(_unsummable(rows, where, scope))
    if problems:
        raise DetailError(path.name, problems)
    ret = CanonicalReturn.from_frame(header, group if group is not None else summed_facts(rows))
    detail = ReturnDetail(
        file=path.name,
        spec=resolved,
        rows=rows,
        rows_read=rows_read,
        repeats_dropped=dropped,
        group_rows=group.height if group is not None else 0,
    )
    logger.info(
        "read %d row(s) of %s with %d return fact(s); %d repeat(s) dropped",
        rows_read,
        path.name,
        ret.facts.height,
        dropped,
    )
    return ret, detail


# =============================================================================
# Supporting public functions
# =============================================================================


def check_amounts(detail: ReturnDetail, pack: TaxonomyPack) -> None:
    """Refuse a detail that sums several rows into a cell that is not an amount.

    A cell the taxonomy does not have is left alone here: the structure check
    reports it, as it reports any other.

    Raises:
        DetailError: each cell of several rows whose data type is not monetary.
    """
    scope = detail.dimensions if detail.spec.group_code is not None else ()
    several = (
        detail.rows.group_by([*COORDINATE_COLUMNS, *scope], maintain_order=True)
        .agg(pl.len().alias(_ROWS), pl.col(LINE_COLUMN))
        .filter(pl.col(_ROWS) > 1)
    )
    if several.is_empty():
        return
    cells: list[Cell] = [
        (row["table"], row["sheet"], row["open_key"], row["row"], row["column"])
        for row in several.iter_rows(named=True)
    ]
    types = cell_data_types(pack, cells)
    row_keys = {(table.code, key.code) for table in pack.tables.values() for key in table.open_keys}
    where = "line" if detail.file.lower().endswith(".csv") else "row"
    problems = [
        f"{address(cell)} is {kind}, so its {rows} rows cannot be added together "
        f"({where}s {_lines(lines)})"
        for cell, rows, lines in zip(cells, several[_ROWS], several[LINE_COLUMN], strict=True)
        if (kind := "row identifier" if (cell[0], cell[4]) in row_keys else types.get(cell))
        and kind != SUMMABLE_TYPE
    ]
    if problems:
        raise DetailError(detail.file, problems)


def cell_data_types(pack: TaxonomyPack, cells: Iterable[Cell]) -> dict[Cell, str]:
    """The data type of each of ``cells`` the taxonomy has (``monetary``, ``percentage``, ...).

    A cell the taxonomy does not have is left out. For an open-row table the
    row is the filer's own key, so the cell is looked up by its column alone.
    """
    wanted = pl.DataFrame(
        list(cells),
        schema=dict.fromkeys(COORDINATE_COLUMNS, pl.String),
        orient="row",
    ).unique()
    if wanted.is_empty():
        return {}
    known = pack.cells.select("table", "sheet", "row", "column", "datapoint")
    fixed = wanted.join(
        known.filter(pl.col("row").is_not_null()),
        on=["table", "sheet", "row", "column"],
        how="inner",
        nulls_equal=True,
    )
    open_rows = wanted.join(
        known.filter(pl.col("row").is_null()).drop("row"),
        on=["table", "sheet", "column"],
        how="inner",
        nulls_equal=True,
    )
    found = pl.concat([fixed, open_rows.select(fixed.columns)], how="vertical")
    metric_of = {
        point: pack.datapoints[point].metric for point in found["datapoint"].unique().to_list()
    }
    types: dict[Cell, str] = {}
    for table, sheet, key, row, column, point in found.select(
        *COORDINATE_COLUMNS, "datapoint"
    ).iter_rows():
        metric = pack.metrics.get(metric_of[point])
        if metric is not None:
            types[(table, sheet, key, row, column)] = metric.data_type
    return types


def summed_facts(rows: pl.DataFrame) -> pl.DataFrame:
    """``rows`` summed into one fact per cell, in the order cells first appear (``FACT_SCHEMA``).

    A cell's value is the sum of its rows' values; its text, the one row's text
    (a cell of several rows has none: ``read_detail`` refuses it); its
    accuracy, the least accurate of its rows', as a sum is no more accurate
    than its least accurate part.
    """
    return (
        rows.group_by(COORDINATE_COLUMNS, maintain_order=True)
        .agg(
            pl.when(pl.col("value").is_not_null().any())
            .then(pl.col("value").sum())
            .otherwise(None)
            .alias("value"),
            pl.col("text_value").drop_nulls().first().alias("text_value"),
            pl.col("decimals").min().alias("decimals"),
        )
        .select(FACT_SCHEMA.names())
        .cast(FACT_SCHEMA)
    )


def require_fact_table(path: Path) -> None:
    """Refuse a file a detail cannot be read from.

    Raises:
        ValueError: ``path`` is not a ``.parquet`` or ``.csv`` fact table.
    """
    if path.suffix.lower() not in DETAIL_SUFFIXES:
        accepted = " or ".join(DETAIL_SUFFIXES)
        raise ValueError(
            f"breakdown columns and line references are read from a fact table ({accepted}); "
            f"{path.name} is not one"
        )


def unread_columns(path: Path) -> tuple[str, ...]:
    """The columns of a fact table that reading it as a return leaves out, as written.

    These are the columns a person could break the return down by. Empty for
    a file that is not a fact table.
    """
    if path.suffix.lower() not in DETAIL_SUFFIXES:
        return ()
    canonical = {name.lower() for name in FACT_SCHEMA.names()}
    return tuple(
        name for name in table_columns(path) if name.strip().lower() not in canonical and name
    )


def breakdown_options(source: Path | BinaryIO, suffix: str, column: str) -> dict[str, list[str]]:
    """Read column names and the selected column's distinct codes for the dashboard picker."""
    if suffix not in DETAIL_SUFFIXES:
        raise ValueError("Choose a CSV or Parquet fact table to see its reporting units.")
    if suffix == ".parquet":
        names = list(pl.read_parquet_schema(source))
    else:
        names = pl.read_csv(source, n_rows=0, infer_schema=False, encoding="utf8-lossy").columns
    columns = [name for name in names if name.strip().lower() not in FACT_SCHEMA]
    selected = [name for name in columns if name.strip().lower() == column.strip().lower()]
    codes: list[str] = []
    if len(selected) == 1:
        if not isinstance(source, Path):
            source.seek(0)
        frame = (
            pl.read_parquet(source, columns=selected)
            if suffix == ".parquet"
            else pl.read_csv(source, columns=selected, infer_schema=False, encoding="utf8-lossy")
        )
        values = frame.to_series().cast(pl.String).str.strip_chars().drop_nulls()
        codes = values.filter(values != "").unique().sort().to_list()
    return {"columns": columns, "codes": codes}


def address(cell: Cell) -> str:
    """A cell's address as a person writes it: ``OF07.00.01.01[z0008][r0070][c0200]``."""
    table, sheet, key, row, column = cell
    on_sheet = f"[z{sheet}]" if sheet else ""
    on_key = f"[{key}]" if key else ""
    return f"{table}{on_sheet}{on_key}[r{row}][c{column}]"


# =============================================================================
# Private helpers
# =============================================================================


def _resolve(spec: DetailSpec, columns: Sequence[str], file: str) -> DetailSpec:
    """``spec`` with each column named as ``file`` names it.

    Raises:
        ValueError: a named column is not in the file, is one of the fact
            columns, or matches two of the file's columns.
    """
    fact_columns = {name.lower() for name in FACT_SCHEMA.names()}
    by_name: dict[str, list[str]] = {}
    for column in columns:
        by_name.setdefault(column.strip().lower(), []).append(column)

    def find(name: str) -> str:
        folded = name.strip().lower()
        if folded in fact_columns:
            raise ValueError(f"{name!r} is a fact column of {file}; it cannot also be a breakdown")
        matches = by_name.get(folded, [])
        if not matches:
            extra = sorted(
                column for column in columns if column.strip().lower() not in fact_columns
            )
            offered = ", ".join(extra) if extra else "none"
            raise ValueError(f"{file} has no column {name!r} (its other columns: {offered})")
        if len(matches) > 1:
            raise ValueError(f"{file} has {len(matches)} columns named like {name!r}")
        return matches[0]

    return replace(
        spec,
        breakdown=tuple(find(name) for name in spec.breakdown),
        line_ref=find(spec.line_ref) if spec.line_ref else None,
    )


def _drop_repeats(
    rows: pl.DataFrame, spec: DetailSpec, where: str
) -> tuple[pl.DataFrame, int, list[str]]:
    """``rows`` with exact repeats dropped where asked, the number dropped, and the refusals.

    A repeat is a line reference given twice in one cell. A row with no
    reference cannot be told from another, so it is always kept.
    """
    reference = spec.line_ref
    if reference is None:
        return rows, 0, []
    scope = spec.breakdown if spec.group_code is not None else ()
    keys = [*scope, *COORDINATE_COLUMNS, reference]
    content = ["value", "text_value", "decimals", *spec.breakdown]
    marked = rows.with_columns(
        pl.len().over(keys).alias(_COUNT),
        pl.struct(content).n_unique().over(keys).alias(_KINDS),
        pl.col(LINE_COLUMN).rank("ordinal").over(keys).alias(_NTH),
    )
    repeated = pl.col(reference).is_not_null() & (pl.col(_COUNT) > 1)
    if spec.on_repeat == ON_REPEAT_STOP:
        offending = marked.filter(repeated)
        verb = "is given"
    else:
        offending = marked.filter(repeated & (pl.col(_KINDS) > 1))
        verb = "is given differently"
    problems = [
        f"line reference {ref!r} {verb} {count} times in {address(tuple(cell[len(scope) :]))} "
        f"({where}s {_lines(lines)})"
        for (*cell, ref), count, lines in _grouped(offending, keys)
    ]
    if spec.on_repeat == ON_REPEAT_STOP or problems:
        return rows, 0, problems
    drop = repeated & (pl.col(_KINDS) == 1) & (pl.col(_NTH) > 1)
    kept = marked.filter(~drop).drop(_COUNT, _KINDS, _NTH)
    return kept, rows.height - kept.height, []


def _unsummable(rows: pl.DataFrame, where: str, scope: tuple[str, ...]) -> list[str]:
    """A refusal for each cell of several rows that any row gives as text."""
    keys = [*scope, *COORDINATE_COLUMNS]
    offending = rows.with_columns(
        pl.len().over(keys).alias(_COUNT),
        pl.col("text_value").is_not_null().any().over(keys).alias(_KINDS),
    ).filter((pl.col(_COUNT) > 1) & pl.col(_KINDS))
    return [
        f"{address(tuple(cell[len(scope) :]))} has {count} rows and at least one is not a number, "
        f"so they cannot be added together ({where}s {_lines(lines)})"
        for cell, count, lines in _grouped(offending, keys)
    ]


def _grouped(frame: pl.DataFrame, keys: Sequence[str]) -> list[tuple[Any, int, list[int]]]:
    """Each group of ``frame`` by ``keys``: its key, how many rows, and their lines."""
    if frame.is_empty():
        return []
    grouped = (
        frame.group_by(keys, maintain_order=True)
        .agg(pl.len().alias(_ROWS), pl.col(LINE_COLUMN).sort())
        .sort(LINE_COLUMN)
    )
    return [
        (tuple(row[name] for name in keys), row[_ROWS], row[LINE_COLUMN])
        for row in grouped.iter_rows(named=True)
    ]


def _lines(lines: Sequence[int]) -> str:
    """``[4, 9, 12]`` as ``4, 9 and 12``; the first few of a long list."""
    shown = [f"{line:,}" for line in sorted(lines)[:6]]
    if len(lines) > len(shown):
        return f"{', '.join(shown)} and {len(lines) - len(shown)} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def _at(cell: Cell) -> pl.Expr:
    """Rows of ``cell``: each coordinate equal, a null equal to a null."""
    expression = pl.lit(value=True)
    for name, value in zip(COORDINATE_COLUMNS, cell, strict=True):
        expression &= pl.col(name).eq_missing(value)
    return expression
