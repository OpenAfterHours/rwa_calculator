"""
The table accessors: worked out once per table, and equal to working them out afresh.

Pipeline position:
    TaxonomyPack.tables  ->  Table.row_codes / column_codes / sheet_codes / key_codes /
        fixed_axis / open_axis  ->  the structure check, the rule engine, the readers

Why this exists: a table's code tuples and its two sheet axes are read once per
fact, per rule selector and per code lookup, so a table works each out once and
keeps the answer. A kept answer can go wrong in ways a recomputed one cannot —
it can be kept for the wrong table, or outlive the fields it was worked out
from — so these tests hold every kept answer of every packaged table to a
recomputation written here from the table's own fields, show that a table made
with ``dataclasses.replace`` answers from ITS fields, and count that a second
read computes nothing.
"""

from __future__ import annotations

import dataclasses
import sys
from typing import TYPE_CHECKING, Any

import pytest

from pack_builders import build_pack
from rwa_filer.taxonomy import pack as pack_module
from rwa_filer.taxonomy.pack import (
    AXIS_FIXED,
    AXIS_OPEN,
    OpenKey,
    Table,
    ZAxis,
    available_packs,
    load_packaged,
    match_code,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

PACKAGED_KEYS = sorted(info.key for info in available_packs())
#: The six derived attributes of a table.
ACCESSORS = ("fixed_axis", "open_axis", "sheet_codes", "row_codes", "column_codes", "key_codes")
#: The sample tables with a fixed sheet axis and with key columns (``pack_builders``).
FIXED_SHEETS_TABLE = "T02.00.01.01"
OPEN_ROWS_TABLE = "T04.00.01.01"


# ---------------------------------------------------------------------------
# The recomputation
# ---------------------------------------------------------------------------


def _axis(table: Table, kind: str) -> ZAxis | None:
    """The table's first sheet axis of ``kind``, straight from its fields."""
    for axis in table.z_axes:
        if axis.kind == kind:
            return axis
    return None


def _recomputed(table: Table) -> dict[str, Any]:
    """Every accessor's answer, worked out from the table's fields and nothing else."""
    fixed = _axis(table, AXIS_FIXED)
    return {
        "fixed_axis": fixed,
        "open_axis": _axis(table, AXIS_OPEN),
        "sheet_codes": tuple([sheet.code for sheet in fixed.sheets]) if fixed else (),
        "row_codes": tuple([row[0] for row in table.rows]),
        "column_codes": tuple([column[0] for column in table.columns]),
        "key_codes": tuple([key.code for key in table.open_keys]),
    }


def _spellings(codes: Sequence[str]) -> list[str]:
    """Each code as written, with its leading zeros lost and with one too many."""
    written = {"", "0", "9999", "abc"}
    for code in codes:
        written.update((code, code.lstrip("0") or "0", f"0{code}"))
    return sorted(written)


def _calls_into_the_pack_module(action: Callable[[], object]) -> int:
    """How many Python-level calls ``action`` makes into ``taxonomy/pack.py``."""
    source = pack_module.__file__
    count = 0

    def watch(frame: Any, event: str, _argument: object) -> None:
        nonlocal count
        if event == "call" and frame.f_code.co_filename == source:
            count += 1

    previous = sys.getprofile()
    sys.setprofile(watch)
    try:
        action()
    finally:
        sys.setprofile(previous)
    return count


# ---------------------------------------------------------------------------
# Every packaged table
# ---------------------------------------------------------------------------


def test_the_packaged_tables_have_every_shape_the_accessors_answer_for() -> None:
    """Fixed sheets, open sheets, both at once, and key columns: all are present."""
    # Act
    tables = [table for key in PACKAGED_KEYS for table in load_packaged(key).tables.values()]

    # Assert
    assert any(_axis(table, AXIS_FIXED) and _axis(table, AXIS_OPEN) for table in tables)
    assert any(_axis(table, AXIS_FIXED) and not _axis(table, AXIS_OPEN) for table in tables)
    assert any(_axis(table, AXIS_OPEN) and not _axis(table, AXIS_FIXED) for table in tables)
    assert any(table.open_keys for table in tables)
    assert any(not table.z_axes for table in tables)


@pytest.mark.parametrize("key", PACKAGED_KEYS)
def test_every_accessor_of_a_packaged_table_equals_a_fresh_recomputation(key: str) -> None:
    # Arrange
    tables = load_packaged(key).tables
    assert tables, "the pack has no tables - nothing would be compared"

    # Act
    differing = [
        (code, name)
        for code, table in tables.items()
        for name, expected in _recomputed(table).items()
        # Read twice: the first read may compute, the second is the kept answer.
        for answer in (getattr(table, name), getattr(table, name))
        if answer != expected or type(answer) is not type(expected)
    ]

    # Assert
    assert differing == []


@pytest.mark.parametrize("key", PACKAGED_KEYS)
def test_the_sheet_axes_are_the_tables_own_axis_objects(key: str) -> None:
    """The same ``ZAxis`` object the table holds, never a copy of it."""
    # Arrange
    tables = load_packaged(key).tables.values()

    # Act
    copied = [
        table.code
        for table in tables
        if table.fixed_axis is not _axis(table, AXIS_FIXED)
        or table.open_axis is not _axis(table, AXIS_OPEN)
    ]

    # Assert
    assert copied == []


@pytest.mark.parametrize("key", PACKAGED_KEYS)
def test_a_code_lookup_equals_matching_against_freshly_built_codes(key: str) -> None:
    """Rows against the row codes, columns against key then column codes, sheets against sheets."""
    # Arrange
    tables = load_packaged(key).tables

    # Act
    differing = []
    for code, table in tables.items():
        fresh = _recomputed(table)
        entered = (*fresh["key_codes"], *fresh["column_codes"])
        for lookup, codes in (
            (table.row_code, fresh["row_codes"]),
            (table.column_code, entered),
            (table.sheet_code, fresh["sheet_codes"]),
        ):
            differing += [
                (code, lookup.__name__, written)
                for written in _spellings(codes)
                if lookup(written) != match_code(codes, written)
            ]

    # Assert
    assert differing == []


def test_a_key_code_that_is_also_a_column_code_is_matched_as_it_always_was() -> None:
    """No packaged table has one, so the packs cannot pin it.

    The code is then listed twice — once as a key, once as a column — and a
    spelling that has lost its zeros matches both, so it is left as written.
    """
    # Arrange
    key = OpenKey(code="0005", label="Key", dimension="tst_dim:OGR", kind="typed")
    table = Table(
        code="T99.00.01.01",
        title="Key listed as a column",
        group="T99.00.01",
        filing_indicator="T99.00.01",
        rows=(),
        columns=(("0005", "Key"), ("0010", "Amount")),
        open_rows=True,
        open_keys=(key,),
    )
    codes = ("0005", "0005", "0010")

    # Act
    answers = {written: table.column_code(written) for written in _spellings(codes)}

    # Assert
    assert answers == {written: match_code(codes, written) for written in _spellings(codes)}
    assert (answers["5"], answers["0005"], answers["10"]) == ("5", "0005", "0010")


# ---------------------------------------------------------------------------
# A kept answer belongs to one table
# ---------------------------------------------------------------------------


def test_a_replaced_table_starts_with_nothing_kept(tmp_path: Path) -> None:
    # Arrange
    table = build_pack(tmp_path).tables[FIXED_SHEETS_TABLE]
    for name in ACCESSORS:
        getattr(table, name)
    table.column_code("10")
    assert set(vars(table)) > {field.name for field in dataclasses.fields(Table)}, (
        "the table kept nothing - a copy with nothing kept would prove nothing"
    )

    # Act
    replaced = dataclasses.replace(table, title="Renamed")

    # Assert
    assert set(vars(replaced)) == {field.name for field in dataclasses.fields(Table)}


def test_a_replaced_table_answers_from_its_own_fields(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    table, keyed = pack.tables[FIXED_SHEETS_TABLE], pack.tables[OPEN_ROWS_TABLE]
    before = {name: getattr(table, name) for name in ACCESSORS}

    # Act
    replaced = dataclasses.replace(
        table,
        rows=(("0990", "Other"),),
        columns=(("0770", "Other"),),
        open_keys=keyed.open_keys,
        z_axes=(),
    )

    # Assert
    assert {name: getattr(replaced, name) for name in ACCESSORS} == _recomputed(replaced)
    assert (replaced.row_code("990"), replaced.column_code("5")) == ("0990", "0005")
    assert replaced.sheet_code("1") == "1"
    assert {name: getattr(table, name) for name in ACCESSORS} == before


def test_equal_tables_stay_equal_whatever_each_has_kept(tmp_path: Path) -> None:
    """Equality, hashing and ``repr`` read the fields, not what a table has worked out."""
    # Arrange
    table = build_pack(tmp_path).tables[FIXED_SHEETS_TABLE]
    untouched = dataclasses.replace(table)
    before = (repr(untouched), hash(untouched))

    # Act
    for name in ACCESSORS:
        getattr(table, name)

    # Assert
    assert table == untouched
    assert (repr(table), hash(table)) == before


# ---------------------------------------------------------------------------
# A second read computes nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ACCESSORS)
def test_reading_an_accessor_again_computes_nothing(tmp_path: Path, name: str) -> None:
    """A count of Python calls, not a clock: the kept answer is read, not rebuilt."""
    # Arrange — a replaced table has kept nothing, whatever the loader read on the way.
    table = dataclasses.replace(build_pack(tmp_path).tables[FIXED_SHEETS_TABLE])
    first = _calls_into_the_pack_module(lambda: getattr(table, name))
    assert first >= 1, "the first read ran no code of the pack module - the counter sees nothing"

    # Act
    again = _calls_into_the_pack_module(lambda: [getattr(table, name) for _ in range(100)])

    # Assert
    assert again == 0


@pytest.mark.parametrize(
    ("table_code", "lookup", "written"),
    [
        (FIXED_SHEETS_TABLE, "row_code", "0010"),
        (OPEN_ROWS_TABLE, "column_code", "0005"),
        (FIXED_SHEETS_TABLE, "sheet_code", "0002"),
    ],
)
def test_a_code_lookup_matches_against_one_kept_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table_code: str, lookup: str, written: str
) -> None:
    """A construction count: a hundred lookups are matched against one tuple, built once."""
    # Arrange
    table = build_pack(tmp_path).tables[table_code]
    handed: list[Sequence[str]] = []

    def recording(codes: Sequence[str], code: str) -> str:
        handed.append(codes)
        return match_code(codes, code)

    monkeypatch.setattr(pack_module, "match_code", recording)

    # Act
    answers = {getattr(table, lookup)(written) for _ in range(100)}

    # Assert
    assert answers == {written}
    assert len(handed) == 100 and all(handed), "the lookups did not reach the matcher with codes"
    assert len({id(codes) for codes in handed}) == 1
