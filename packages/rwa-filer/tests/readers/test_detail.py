"""A detail file: rows summed into cells, kept beside the return, and refused where they cannot be."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from detail_builders import (
    ASSET_FINANCE,
    COMMERCIAL,
    CORPORATES,
    HEADER_FIELDS,
    TABLE,
    detail_rows,
    summed,
    write_detail,
)
from pack_builders import VALID_LEI
from rwa_filer.model import ReturnHeader
from rwa_filer.readers import DetailSpec, open_source
from rwa_filer.readers.detail import (
    ON_REPEAT_KEEP_ONE,
    DetailError,
    cell_data_types,
    read_detail,
)
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return
from rwa_filer.validate.structure import FINDING_DUPLICATE_FACT

if TYPE_CHECKING:
    from pathlib import Path

HEADER = ReturnHeader(VALID_LEI, date(2027, 3, 31), "PRA001")
BY_UNIT = DetailSpec(breakdown=("business_unit",))
#: OF 07.00 corporates, on-balance-sheet exposure value.
ON_BALANCE_VALUE = (TABLE, CORPORATES, None, "0070", "0200")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Summing
# ---------------------------------------------------------------------------


def test_the_return_is_the_rows_summed_cell_by_cell(tmp_path: Path) -> None:
    # Arrange
    rows = detail_rows()
    path = write_detail(tmp_path / "detail.csv", rows)
    expected = summed(rows)

    # Act
    ret, detail = read_detail(path, HEADER, BY_UNIT)

    # Assert
    joined = ret.facts.join(expected, on=["table", "sheet", "row", "column"], suffix="_rows")
    assert joined.height == expected.height == ret.facts.height
    assert (joined["value"] - joined["value_rows"]).abs().max() == 0
    assert detail.rows_read == len(rows)


def test_a_cell_splits_by_member_into_amounts_that_add_up_to_it(tmp_path: Path) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")
    ret, detail = read_detail(path, HEADER, BY_UNIT)
    figure = ret.facts.filter(
        (pl.col("sheet") == CORPORATES) & (pl.col("row") == "0070") & (pl.col("column") == "0200")
    )["value"][0]

    # Act
    shares = detail.shares(ON_BALANCE_VALUE, "business_unit")

    # Assert
    assert sum(share.value for share in shares) == figure
    assert [share.member for share in shares][:2] == [COMMERCIAL, ASSET_FINANCE]
    assert shares[0].value == 990_000 + 50_000, "the unit's loan and its late-booked facility"


def test_a_sum_is_stated_to_the_accuracy_of_its_least_accurate_row(tmp_path: Path) -> None:
    # Arrange
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,decimals,unit\n"
        "OF07.00.01.01,0008,0010,0010,1000.25,2,A\n"
        "OF07.00.01.01,0008,0010,0010,3000,-3,B\n",
    )

    # Act
    ret, _ = read_detail(path, HEADER, DetailSpec(breakdown=("unit",)))

    # Assert
    assert ret.facts.select("value", "decimals").row(0) == (4000.25, -3)


def test_breakdown_columns_are_matched_ignoring_case_and_kept_as_the_file_names_them(
    tmp_path: Path,
) -> None:
    # Arrange
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value, Business_Unit \nOF07.00.01.01,0008,0010,0010,5,A\n",
    )

    # Act
    _, detail = read_detail(path, HEADER, DetailSpec(breakdown=("business_unit",)))

    # Assert
    assert detail.dimensions == (" Business_Unit ",)
    assert detail.members(" Business_Unit ") == ("A",)


def test_a_row_that_leaves_a_breakdown_column_empty_is_a_member_of_its_own(
    tmp_path: Path,
) -> None:
    # Arrange
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,unit\n"
        "OF07.00.01.01,0008,0010,0010,5,A\n"
        "OF07.00.01.01,0008,0010,0010,7,\n",
    )

    # Act
    _, detail = read_detail(path, HEADER, DetailSpec(breakdown=("unit",)))

    # Assert
    assert detail.members("unit") == ("A", None)
    assert detail.member_facts("unit", None)["value"].to_list() == [7.0]


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------


def test_a_column_the_file_does_not_have_is_refused_with_the_ones_it_has(tmp_path: Path) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")

    # Act / Assert
    with pytest.raises(ValueError, match="no column 'desk'.*business_unit, line_id, source"):
        read_detail(path, HEADER, DetailSpec(breakdown=("desk",)))


def test_a_fact_column_cannot_be_a_breakdown_column(tmp_path: Path) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")

    # Act / Assert
    with pytest.raises(ValueError, match="'Row' is a fact column"):
        read_detail(path, HEADER, DetailSpec(breakdown=("Row",)))


def test_a_line_reference_twice_in_one_cell_stops_the_file_and_names_the_lines(
    tmp_path: Path,
) -> None:
    # Arrange: the leasing extract loaded twice, the CSV's own line numbers.
    rows = detail_rows()
    leasing = [row for row in rows if row["source"] == "LEASING"]
    path = write_detail(tmp_path / "detail.csv", rows + leasing)
    first = rows.index(leasing[0]) + 2

    # Act
    with pytest.raises(DetailError) as raised:
        read_detail(path, HEADER, DetailSpec(breakdown=("business_unit",), line_ref="line_id"))

    # Assert
    assert len(raised.value.problems) == len(leasing)
    assert f"lines {first} and {len(rows) + 2}" in raised.value.problems[0]
    assert "nothing was read" in str(raised.value)


def test_one_line_reference_in_many_cells_is_one_line_reported_in_many_places(
    tmp_path: Path,
) -> None:
    # Arrange: a loan's reference on every cell it feeds, as a loan-level extract writes it.
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,unit,loan\n"
        "OF07.00.01.01,0008,0010,0010,100,A,LN-1\n"
        "OF07.00.01.01,0008,0010,0040,100,A,LN-1\n"
        "OF07.00.01.01,0001,0010,0010,100,A,LN-1\n",
    )

    # Act
    ret, detail = read_detail(path, HEADER, DetailSpec(breakdown=("unit",), line_ref="loan"))

    # Assert
    assert ret.facts.height == 3
    assert detail.repeats_dropped == 0


def test_keep_one_drops_a_repeat_that_agrees_on_everything(tmp_path: Path) -> None:
    # Arrange
    rows = detail_rows()
    leasing = [row for row in rows if row["source"] == "LEASING"]
    path = write_detail(tmp_path / "detail.csv", rows + leasing)
    spec = DetailSpec(
        breakdown=("business_unit",), line_ref="line_id", on_repeat=ON_REPEAT_KEEP_ONE
    )

    # Act
    ret, detail = read_detail(path, HEADER, spec)

    # Assert
    once, _ = read_detail(write_detail(tmp_path / "once.csv", rows), HEADER, spec)
    assert detail.repeats_dropped == len(leasing)
    assert ret.facts.equals(once.facts)


def test_keep_one_refuses_a_repeat_that_differs(tmp_path: Path) -> None:
    # Arrange
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,unit,ref\n"
        "OF07.00.01.01,0008,0010,0010,100,A,R1\n"
        "OF07.00.01.01,0008,0010,0010,150,A,R1\n",
    )
    spec = DetailSpec(breakdown=("unit",), line_ref="ref", on_repeat=ON_REPEAT_KEEP_ONE)

    # Act / Assert
    with pytest.raises(DetailError, match="'R1' is given differently 2 times"):
        read_detail(path, HEADER, spec)


def test_several_rows_for_a_cell_given_as_text_are_refused(tmp_path: Path) -> None:
    # Arrange
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,unit\n"
        "OF07.00.01.01,0008,0010,0010,n/a,A\n"
        "OF07.00.01.01,0008,0010,0010,5,B\n",
    )

    # Act / Assert
    with pytest.raises(DetailError, match=r"\[r0010\]\[c0010\] has 2 rows and at least one is not"):
        read_detail(path, HEADER, DetailSpec(breakdown=("unit",)))


def test_several_rows_for_a_percentage_cell_are_refused_once_the_taxonomy_is_known(
    tmp_path: Path,
) -> None:
    # Arrange: OF 08.01 column 0010 is a PD — a percentage, which has no sum.
    path = _write(
        tmp_path / "detail.csv",
        "table,sheet,row,column,value,unit\n"
        "OF08.01.01.01,0001,0001,0010,0.01,A\n"
        "OF08.01.01.01,0001,0001,0010,0.02,B\n",
    )

    # Act / Assert
    with pytest.raises(DetailError, match="is percentage, so its 2 rows cannot be added"):
        open_source(path, HEADER_FIELDS, detail=DetailSpec(breakdown=("unit",)))


def test_a_detail_is_read_from_a_fact_table_only(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "return.xlsx"
    path.write_bytes(b"not read")

    # Act / Assert
    with pytest.raises(ValueError, match=r"read from a fact table \(.parquet or .csv\)"):
        open_source(path, HEADER_FIELDS, detail=BY_UNIT)


def test_an_answer_to_a_repeat_that_is_not_a_choice_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="'skip' is not stop, keep-one"):
        DetailSpec.from_text("unit", "ref", "skip")


# ---------------------------------------------------------------------------
# Nothing asked: the file is read as before
# ---------------------------------------------------------------------------


def test_without_a_breakdown_a_fact_table_reads_as_before_and_names_its_other_columns(
    tmp_path: Path,
) -> None:
    # Arrange: one row per cell, so the file is a valid return on its own.
    path = _write(
        tmp_path / "facts.csv",
        "table,sheet,row,column,value,business_unit\nOF07.00.01.01,0008,0010,0010,5,A\n",
    )

    # Act
    plain = open_source(path, HEADER_FIELDS)
    asked_for_nothing = open_source(path, HEADER_FIELDS, detail=DetailSpec())

    # Assert
    assert plain.detail is None and asked_for_nothing.detail is None
    assert plain.unread_columns == ("business_unit",)
    assert plain.ret.facts.equals(asked_for_nothing.ret.facts)


def test_without_a_breakdown_two_rows_for_one_cell_are_still_a_duplicate_fact(
    tmp_path: Path,
) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")

    # Act
    source = open_source(path, HEADER_FIELDS)
    validation = validate_return(source.ret, release=source.release)

    # Assert
    assert FINDING_DUPLICATE_FACT in {finding.code for finding in validation.structure}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


def test_cell_data_types_reads_each_cells_type_from_the_taxonomy() -> None:
    # Arrange
    pack = resolve_release("PRA001", None).pack
    amount = (TABLE, CORPORATES, None, "0010", "0200")
    pd = ("OF08.01.01.01", "0001", None, "0001", "0010")
    nowhere = (TABLE, CORPORATES, None, "9999", "0200")

    # Act
    types = cell_data_types(pack, [amount, pd, nowhere])

    # Assert
    assert types == {amount: "monetary", pd: "percentage"}
