"""
The structure check works table by table, and only on the tables the return names.

Pipeline position:
    CanonicalReturn + TaxonomyPack  ->  check_structure / resolve_datapoints
    The sheet and open-key checks read each table's facts on their own, and
    every join reads only the cells of the tables the return has facts for.

Key responsibilities:
- The split by table hands each table exactly its own rows, in the order the
  frame holds them.
- Facts of several tables that break the sheet and open-key rules in mixed
  ways are each reported under their own table, every one of them a position.
- A table the return does not name changes nothing: the same return gives the
  same findings and the same placed facts against a module with many more
  tables, for a return naming one table, several, or one the module lacks.
- The frames the check builds from a pack belong to that pack: a pack rebuilt
  with other cells is checked against its own.

Positions of facts that share all their coordinates are compared as a set:
their order comes from an unstable sort and is not part of what is promised.

References:
- BoE XBRL Filing Manual v1.0.1 — facts outside the reported tables
- Bank of England Banking Taxonomy — the reportable cells of each table
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import build_pack, build_return
from rwa_filer.validate.structure import (
    FINDING_CELL_NOT_REPORTABLE,
    FINDING_DUPLICATE_FACT,
    FINDING_INCONSISTENT_DATAPOINT,
    FINDING_OPEN_KEY_INVALID,
    FINDING_SHEET_INVALID,
    FINDING_UNKNOWN_TABLE,
    FINDING_VALUE_TYPE,
    _split_by_table,
    check_structure,
    resolve_datapoints,
)
from structure_builders import T01, T02, T03, T04, T07, build_wide_pack, fact_frame

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding

T05_FIRST = "T05.00.01.01"
T05_SECOND = "T05.00.01.02"
T06 = "T06.00.01.01"
#: Extra copies of three sample tables in the wide pack: 98 tables against the sample's 8.
WIDE_COPIES = 30

#: One fact on each table, the sheet and open-key rules broken in every way they can be.
MIXED_OFFENDERS = fact_frame(
    (T01, None, None, "0010", "0010", 1.0, None),
    (T01, "0001", None, "0020", "0010", 2.0, None),  # a sheet on a table with no sheet axis
    (T01, "0001", "eba_GA:GB", "0030", "0010", 3.0, None),  # ... and an open key as well
    (T01, None, "eba_GA:GB", "0020", "0020", 0.5, None),  # an open key, no open axis
    (T02, "0001", None, "0010", "0010", 4.0, None),
    (T02, None, None, "0020", "0010", 5.0, None),  # the sheet it needs is missing
    (T02, "0002", "eba_GA:GB", "0020", "0010", 5.5, None),  # a sheeted table has no open axis
    (T02, "0009", None, "0010", "0010", 6.0, None),  # a sheet it does not have, twice
    (T02, "0009", None, "0010", "0010", 7.0, None),
    (T03, None, "eba_GA:GB", "0010", "0010", 8.0, None),
    (T03, None, None, "0010", "0010", 9.0, None),  # the key it needs is missing
    (T03, None, "DE", "0020", "0010", 10.0, None),  # a key it does not accept
    (T07, None, None, "0010", "0010", 11.0, None),  # no key: the "all" sheet
    (T07, None, "tst_TA:x9", "0010", "0010", 12.0, None),  # a key it does not accept
    (T07, "0001", "x1", "0010", "0010", 13.0, None),  # a sheet on a table with no sheet axis
)

RETURNS: dict[str, pl.DataFrame] = {
    "one table": fact_frame(
        (T02, "0001", None, "0010", "0010", 4.0, None),
        (T02, "0002", None, "0020", "0010", 5.0, None),
        (T02, "0003", None, "0020", "0010", 6.0, None),
    ),
    "several tables": fact_frame(
        (T01, None, None, "0010", "0010", 1.0, None),
        (T02, "0001", None, "0010", "0010", 4.0, None),
        (T02, "0003", None, "0020", "0010", 5.0, None),
        (T03, None, "eba_GA:GB", "0010", "0010", 8.0, None),
        (T03, None, "DE", "0020", "0010", 10.0, None),
        (T04, None, None, "1", "0005", 7.0, None),
        (T04, None, None, "1", "0010", 70.0, None),
        (T04, None, None, "2", "0010", 80.0, None),
        (T04, None, None, "3", "0005", None, "seven"),
        (T05_FIRST, None, None, "0010", "0010", 100.0, None),
        (T05_SECOND, None, None, "0010", "0010", 101.0, None),
        (T06, None, None, "0010", "0010", None, "maybe"),
        (T07, None, None, "0010", "0040", 11.0, None),
    ),
    "a table the module lacks": fact_frame(
        (T01, None, None, "0010", "0010", 1.0, None),
        ("T99.00.01.01", None, None, "0010", "0010", 2.0, None),
    ),
}

#: ``(code, table, count)`` of each finding, in the order the check returns them.
EXPECTED: dict[str, list[tuple[str, str, str]]] = {
    "one table": [(FINDING_SHEET_INVALID, T02, "1 fact(s)")],
    "several tables": [
        (FINDING_SHEET_INVALID, T02, "1 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T03, "1 fact(s)"),
        (FINDING_CELL_NOT_REPORTABLE, T07, "1 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T04, "1 fact(s)"),  # a row with no key
        (FINDING_OPEN_KEY_INVALID, T04, "1 fact(s)"),  # a key not of its type
        (FINDING_VALUE_TYPE, T06, "1 fact(s)"),
        (FINDING_INCONSISTENT_DATAPOINT, T05_FIRST, "1 fact(s)"),
        (FINDING_INCONSISTENT_DATAPOINT, T05_SECOND, "1 fact(s)"),
    ],
    "a table the module lacks": [(FINDING_UNKNOWN_TABLE, "T99.00.01.01", "1 fact(s)")],
}


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


@pytest.fixture(scope="module")
def wide(tmp_path_factory: pytest.TempPathFactory) -> TaxonomyPack:
    return build_wide_pack(tmp_path_factory.mktemp("wide"), copies=WIDE_COPIES)


def summary(findings: list[Finding]) -> list[tuple[str, str, str]]:
    return [(finding.code, finding.subject, finding.actual) for finding in findings]


def coordinates(finding: Finding) -> list[tuple[str | None, ...]]:
    """Where each position is, in order: facts that share coordinates repeat them."""
    return [
        (position.table, position.sheet, position.open_key, position.row, position.column)
        for position in finding.positions
    ]


def held(finding: Finding) -> Counter[tuple[object, ...]]:
    """Every position with what it holds, as a multiset: no order among equal coordinates."""
    return Counter(
        (
            (position.table, position.sheet, position.open_key, position.row, position.column),
            position.value,
            position.text_value,
            position.detail,
        )
        for position in finding.positions
    )


# ---------------------------------------------------------------------------
# The split by table
# ---------------------------------------------------------------------------


def test_the_split_by_table_keeps_each_tables_rows_in_the_frames_own_order() -> None:
    """Every part holds exactly its table's rows, in the order they came; parts by first sight."""
    # Arrange — twelve tables interleaved, each row numbered in the order it came.
    tables = [f"T{(number * 7) % 12:02d}.00.01.01" for number in range(60)]
    frame = pl.DataFrame({"table": tables, "at": list(range(len(tables)))})

    # Act
    parts = _split_by_table(frame)

    # Assert
    assert list(parts) == list(dict.fromkeys(tables))
    for table, part in parts.items():
        assert part["at"].to_list() == [at for at, code in enumerate(tables) if code == table]


# ---------------------------------------------------------------------------
# Sheet and open-key offenders, mixed over several tables
# ---------------------------------------------------------------------------


def test_sheet_and_open_key_offenders_of_several_tables_are_each_reported_under_their_table(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    ret = build_return(MIXED_OFFENDERS)

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert summary(findings) == [
        (FINDING_DUPLICATE_FACT, T02, "1 fact(s)"),
        (FINDING_SHEET_INVALID, T01, "2 fact(s)"),
        (FINDING_SHEET_INVALID, T02, "3 fact(s)"),
        (FINDING_SHEET_INVALID, T07, "1 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T01, "2 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T02, "1 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T03, "2 fact(s)"),
        (FINDING_OPEN_KEY_INVALID, T07, "1 fact(s)"),
    ]
    sheets = {finding.subject: finding for finding in findings[1:4]}
    keys = {finding.subject: finding for finding in findings[4:]}
    assert coordinates(sheets[T01]) == [
        (T01, "0001", None, "0020", "0010"),
        (T01, "0001", "eba_GA:GB", "0030", "0010"),
    ]
    assert coordinates(sheets[T02]) == [
        (T02, None, None, "0020", "0010"),
        (T02, "0009", None, "0010", "0010"),
        (T02, "0009", None, "0010", "0010"),
    ]
    assert held(sheets[T02]) == Counter(
        {
            ((T02, None, None, "0020", "0010"), 5.0, None, ""): 1,
            ((T02, "0009", None, "0010", "0010"), 6.0, None, ""): 1,
            ((T02, "0009", None, "0010", "0010"), 7.0, None, ""): 1,
        }
    )
    assert held(sheets[T07]) == Counter({((T07, "0001", "x1", "0010", "0010"), 13.0, None, ""): 1})
    assert held(keys[T01]) == Counter(
        {
            ((T01, None, "eba_GA:GB", "0020", "0020"), 0.5, None, ""): 1,
            ((T01, "0001", "eba_GA:GB", "0030", "0010"), 3.0, None, ""): 1,
        }
    )
    assert held(keys[T02]) == Counter(
        {((T02, "0002", "eba_GA:GB", "0020", "0010"), 5.5, None, ""): 1}
    )
    assert coordinates(keys[T03]) == [
        (T03, None, None, "0010", "0010"),
        (T03, None, "DE", "0020", "0010"),
    ]
    assert held(keys[T07]) == Counter(
        {((T07, None, "tst_TA:x9", "0010", "0010"), 12.0, None, ""): 1}
    )


# ---------------------------------------------------------------------------
# Tables the return does not name change nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(RETURNS))
def test_a_module_with_many_more_tables_gives_the_same_findings(
    pack: TaxonomyPack, wide: TaxonomyPack, name: str
) -> None:
    # Arrange
    assert len(wide.tables) >= 10 * len(pack.tables), "the wide module must dwarf the sample"
    assert wide.cells.height >= 10 * pack.cells.height
    ret = build_return(RETURNS[name])

    # Act
    small, large = check_structure(ret, pack), check_structure(ret, wide)

    # Assert
    assert summary(small) == EXPECTED[name]
    assert large == small


@pytest.mark.parametrize("name", list(RETURNS))
def test_a_module_with_many_more_tables_places_every_fact_on_the_same_cell(
    pack: TaxonomyPack, wide: TaxonomyPack, name: str
) -> None:
    # Arrange
    ret = build_return(RETURNS[name])

    # Act
    small, large = resolve_datapoints(ret, pack), resolve_datapoints(ret, wide)

    # Assert
    assert small["datapoint"].is_not_null().any(), "no fact was placed: nothing is compared"
    assert large.equals(small)


# ---------------------------------------------------------------------------
# The frames built from a pack belong to that pack
# ---------------------------------------------------------------------------


def test_a_pack_rebuilt_with_other_cells_is_checked_against_its_own_cells(
    pack: TaxonomyPack,
) -> None:
    # Arrange — check once first, so whatever the check keeps for ``pack`` exists.
    ret = build_return(fact_frame((T01, None, None, "0020", "0010", 1.0, None)))
    assert check_structure(ret, pack) == []
    cut = dataclasses.replace(
        pack, cells=pack.cells.filter(~((pl.col("table") == T01) & (pl.col("row") == "0020")))
    )

    # Act
    findings = check_structure(ret, cut)

    # Assert
    assert summary(findings) == [(FINDING_CELL_NOT_REPORTABLE, T01, "1 fact(s)")]
    assert check_structure(ret, pack) == []
