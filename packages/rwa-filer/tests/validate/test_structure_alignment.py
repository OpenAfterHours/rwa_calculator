"""
Code alignment: a row, column or sheet code is read the way its own table writes it.

Pipeline position:
    CanonicalReturn + TaxonomyPack  ->  check_structure / resolve_datapoints
    Alignment is the first thing both do: every later check, the rule engine
    and the XBRL writer see the codes it leaves.

Key responsibilities:
- A code that lost its leading zeros (``10`` from a spreadsheet) or gained
  some (``0010`` for a table that writes ``010``) names the same row, column,
  sheet or key column, on every axis and for either width.
- A code that names nothing (``99999``, ``x10``) is reported exactly as the
  source wrote it, also when another code of the same return is rewritten.
- A row identifier of an open-row table is the filer's own and is never
  rewritten, even where it looks like a published code.
- A code is matched against ITS OWN table: the same text can need a zero in
  one table and be right as it stands in another.

Why this file exists: before it, the alignment step could be deleted outright
and every test of the package still passed. Each test asserts first that its
input really differs from the table's own spelling — on a four-digit pack a
well-formed return gives alignment nothing to do, so a test without that
check would pass with the step removed.

References:
- Bank of England Banking Taxonomy v4.1.1 — MRL001 and MRL003 write their
  codes at three digits, every other module at four
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import build_pack, build_return
from rwa_filer.taxonomy.pack import TaxonomyPack, load_packaged
from rwa_filer.validate.structure import (
    FINDING_CELL_NOT_REPORTABLE,
    FINDING_DUPLICATE_FACT,
    FINDING_SHEET_INVALID,
    IS_KEY,
    check_structure,
    resolve_datapoints,
)
from structure_builders import (
    T01,
    T02,
    T04,
    T08,
    build_alignment_pack,
    fact_frame,
    packaged_return,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn

#: A code as a source may write it, for a table that writes it ``0010``-style.
LOST_AND_GAINED = pytest.mark.parametrize("zeros", ["lost", "gained"])
#: Codes that differ from every published code by more than leading zeros.
NAMES_NOTHING = pytest.mark.parametrize("written", ["99999", "x10"])

#: The three-digit tables of the packaged MREL modules.
MRL001_TABLE = "MR02.01.01.01"
MRL003_OPEN_ROW_TABLE = "BR01.00.01.01"


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def respelt(code: str, zeros: str) -> str:
    """``code`` with its leading zeros lost, or with one more than its table writes."""
    return code.lstrip("0") if zeros == "lost" else "0" + code


def placed(ret: CanonicalReturn, pack: TaxonomyPack) -> list[tuple[object, ...]]:
    """Each fact as ``(table, sheet, row, column, data point, is key)`` after resolution."""
    return (
        resolve_datapoints(ret, pack)
        .select("table", "sheet", "row", "column", "datapoint", IS_KEY)
        .rows()
    )


# ---------------------------------------------------------------------------
# Lost and gained zeros, one axis each
# ---------------------------------------------------------------------------


@LOST_AND_GAINED
def test_a_row_code_is_read_the_way_its_table_writes_it(pack: TaxonomyPack, zeros: str) -> None:
    # Arrange
    written = respelt("0020", zeros)
    assert written not in pack.tables[T01].row_codes, "the input must differ from the table's own"
    ret = build_return(fact_frame((T01, None, None, written, "0010", 1.0, None)))

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert resolved == [(T01, None, "0020", "0010", 3, False)]


@LOST_AND_GAINED
def test_a_column_code_is_read_the_way_its_table_writes_it(pack: TaxonomyPack, zeros: str) -> None:
    # Arrange
    written = respelt("0020", zeros)
    assert written not in pack.tables[T01].column_codes, (
        "the input must differ from the table's own"
    )
    ret = build_return(fact_frame((T01, None, None, "0010", written, 0.25, None)))

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert resolved == [(T01, None, "0010", "0020", 1, False)]


@LOST_AND_GAINED
def test_a_sheet_code_is_read_the_way_its_table_writes_it(pack: TaxonomyPack, zeros: str) -> None:
    # Arrange
    written = respelt("0002", zeros)
    assert written not in pack.tables[T02].sheet_codes, "the input must differ from the table's own"
    ret = build_return(fact_frame((T02, written, None, "0010", "0010", 40.0, None)))

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert resolved == [(T02, "0002", "0010", "0010", 10, False)]


@LOST_AND_GAINED
def test_a_key_column_code_of_an_open_row_table_is_read_the_way_its_table_writes_it(
    pack: TaxonomyPack, zeros: str
) -> None:
    """The key column carries no data point, so only the table's key codes can name it."""
    # Arrange
    written = respelt("0005", zeros)
    table = pack.tables[T04]
    assert written not in table.key_codes
    assert "0005" not in table.column_codes
    ret = build_return(
        fact_frame(
            (T04, None, None, "1", written, 7.0, None),
            (T04, None, None, "1", "0010", 5.0, None),
        )
    )

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert sorted(resolved, key=str) == [
        (T04, None, "1", "0005", None, True),
        (T04, None, "1", "0010", 14, False),
    ]


def test_one_cell_written_under_two_spellings_is_reported_twice(pack: TaxonomyPack) -> None:
    """Alignment runs before the duplicate check, so the two spellings meet."""
    # Arrange
    ret = build_return(
        fact_frame(
            (T01, None, None, "0010", "0010", 1.0, None),
            (T01, None, None, "10", "10", 1.0, None),
        )
    )

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert [finding.code for finding in findings] == [FINDING_DUPLICATE_FACT]
    assert "[r0010][c0010]" in findings[0].message


# ---------------------------------------------------------------------------
# A code that names nothing is left for the finding to report
# ---------------------------------------------------------------------------


@NAMES_NOTHING
def test_a_row_code_that_names_no_row_is_reported_as_written(
    pack: TaxonomyPack, written: str
) -> None:
    # Arrange — a second fact whose row IS rewritten, so the rewrite really runs.
    ret = build_return(
        fact_frame(
            (T01, None, None, "20", "0010", 1.0, None),
            (T01, None, None, written, "0010", 2.0, None),
        )
    )

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert [finding.code for finding in findings] == [FINDING_CELL_NOT_REPORTABLE]
    assert [(position.row, position.column) for position in findings[0].positions] == [
        (written, "0010")
    ]


@NAMES_NOTHING
def test_a_column_code_that_names_no_column_is_reported_as_written(
    pack: TaxonomyPack, written: str
) -> None:
    # Arrange — a second fact whose column IS rewritten, so the rewrite really runs.
    ret = build_return(
        fact_frame(
            (T01, None, None, "0010", "20", 0.25, None),
            (T01, None, None, "0020", written, 2.0, None),
        )
    )

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert [finding.code for finding in findings] == [FINDING_CELL_NOT_REPORTABLE]
    assert [(position.row, position.column) for position in findings[0].positions] == [
        ("0020", written)
    ]


@NAMES_NOTHING
def test_a_sheet_code_that_names_no_sheet_is_reported_as_written(
    pack: TaxonomyPack, written: str
) -> None:
    # Arrange — a second fact whose sheet IS rewritten, so the rewrite really runs.
    ret = build_return(
        fact_frame(
            (T02, "1", None, "0010", "0010", 60.0, None),
            (T02, written, None, "0020", "0010", 2.0, None),
        )
    )

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert [finding.code for finding in findings] == [FINDING_SHEET_INVALID]
    assert [(position.sheet, position.row) for position in findings[0].positions] == [
        (written, "0020")
    ]


# ---------------------------------------------------------------------------
# Whose code it is: the table's own, and never an open row's identifier
# ---------------------------------------------------------------------------


def test_an_open_row_tables_row_identifiers_are_never_rewritten(tmp_path: Path) -> None:
    """Two rows a filer called ``10`` and ``0010`` stay two rows."""
    # Arrange — the table PUBLISHES row 0010, so "10" would match it in a closed table.
    pack = build_alignment_pack(tmp_path)
    assert pack.tables[T04].open_rows
    assert "0010" in pack.tables[T04].row_codes
    ret = build_return(
        fact_frame(
            (T04, None, None, "10", "0005", 1.0, None),
            (T04, None, None, "10", "0010", 5.0, None),
            (T04, None, None, "0010", "0005", 2.0, None),
            (T04, None, None, "0010", "0010", 6.0, None),
        )
    )

    # Act
    findings, resolved = check_structure(ret, pack), resolve_datapoints(ret, pack)

    # Assert
    assert findings == []
    assert resolved.sort("value")["row"].to_list() == ["10", "0010", "10", "0010"]


def test_an_open_row_identifier_is_untouched_where_another_table_rewrites_the_same_text(
    pack: TaxonomyPack,
) -> None:
    # Arrange — "10" is row 0010 of the closed table and a filer's own row id of the open one.
    ret = build_return(
        fact_frame(
            (T01, None, None, "10", "0010", 100.0, None),
            (T04, None, None, "10", "0005", 1.0, None),
            (T04, None, None, "10", "0010", 5.0, None),
        )
    )

    # Act
    findings, resolved = check_structure(ret, pack), resolve_datapoints(ret, pack)

    # Assert
    assert findings == []
    assert dict(resolved.select("table", "row").unique().rows()) == {T01: "0010", T04: "10"}


def test_each_table_reads_the_same_text_in_its_own_width(tmp_path: Path) -> None:
    """``010`` is right as it stands in a three-digit table and lacks a zero in a four-digit one."""
    # Arrange
    pack = build_alignment_pack(tmp_path)
    assert "010" in pack.tables[T08].row_codes
    assert "0010" in pack.tables[T01].row_codes
    ret = build_return(
        fact_frame(
            (T01, None, None, "010", "010", 100.0, None),
            (T08, "001", None, "010", "010", 1.0, None),
            (T08, "0002", None, "0010", "0010", 2.0, None),
        )
    )

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert sorted(resolved, key=str) == [
        (T01, None, "0010", "0010", 0, False),
        (T08, "001", "010", "010", 21, False),
        (T08, "002", "010", "010", 22, False),
    ]


# ---------------------------------------------------------------------------
# The packaged three-digit modules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "column"), [("5", "10"), ("0005", "0010")], ids=["unpadded", "padded"]
)
def test_a_packaged_three_digit_tables_codes_are_aligned_padded_or_not(
    row: str, column: str
) -> None:
    # Arrange
    pack = load_packaged("mrl001-4.1.1")
    table = pack.tables[MRL001_TABLE]
    assert "005" in table.row_codes
    assert "010" in table.column_codes
    assert row not in table.row_codes
    assert column not in table.column_codes
    ret = packaged_return("MRL001", fact_frame((MRL001_TABLE, None, None, row, column, 1.0, None)))

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert resolved == [(MRL001_TABLE, None, "005", "010", 0, False)]


def test_codes_read_as_numbers_land_on_a_three_digit_tables_cells() -> None:
    """A numeric code column is padded to four digits on the way in; the table writes three."""
    # Arrange
    pack = load_packaged("mrl001-4.1.1")
    frame = pl.DataFrame({"table": [MRL001_TABLE], "row": [30], "column": [20], "value": [1.0]})
    ret = packaged_return("MRL001", frame)
    assert ret.facts.select("row", "column").rows() == [("0030", "0020")], (
        "not padded on the way in"
    )

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert resolved == [(MRL001_TABLE, None, "030", "020", 8, False)]


def test_the_key_column_of_a_packaged_three_digit_open_row_table_is_aligned() -> None:
    """MRL003: key column ``999`` and data column ``010``, both arriving as numbers."""
    # Arrange
    pack = load_packaged("mrl003-4.1.1")
    table = pack.tables[MRL003_OPEN_ROW_TABLE]
    assert table.open_rows
    assert table.key_codes == ("999",)
    assert "010" in table.column_codes
    frame = pl.DataFrame(
        {
            "table": [MRL003_OPEN_ROW_TABLE, MRL003_OPEN_ROW_TABLE],
            "row": ["7", "7"],
            "column": [999, 10],
            "text_value": ["XS0000000001", "an instrument"],
        }
    ).with_columns(pl.lit(None, dtype=pl.Float64).alias("value"))
    ret = packaged_return("MRL003", frame)
    assert ret.facts["column"].to_list() == ["0999", "0010"], "not padded on the way in"

    # Act
    findings, resolved = check_structure(ret, pack), placed(ret, pack)

    # Assert
    assert findings == []
    assert sorted(resolved, key=str) == [
        (MRL003_OPEN_ROW_TABLE, None, "7", "010", 0, False),
        (MRL003_OPEN_ROW_TABLE, None, "7", "999", None, True),
    ]
