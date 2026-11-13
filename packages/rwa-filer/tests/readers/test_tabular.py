"""Parquet and CSV readers: every code as written, and no fact lost silently."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from pack_builders import build_header
from rwa_filer.model import FACT_SCHEMA
from rwa_filer.readers import read_return
from rwa_filer.readers.tabular import read_csv, read_parquet


def test_csv_codes_keep_their_leading_zeros(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("table,sheet,row,column,value\nT02.00.01.01,0001,0010,0010,60\n")

    # Act
    facts = read_csv(path, build_header()).facts

    # Assert
    assert facts.schema == FACT_SCHEMA
    assert facts.row(0) == ("T02.00.01.01", "0001", None, "0010", "0010", 60.0, None)


def test_csv_column_names_are_matched_case_insensitively(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("Table, Row ,COLUMN,Value,Open_Key\nT03.00.01.01,0010,0010,7,GB\n")

    # Act
    facts = read_csv(path, build_header()).facts

    # Assert
    assert (facts["open_key"][0], facts["value"][0]) == ("GB", 7.0)


def test_a_csv_value_with_thousands_separators_is_a_number(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text('table,row,column,value\nT01.00.01.01,0010,0010,"1,234,567.5"\n')

    # Act / Assert
    assert read_csv(path, build_header()).facts["value"][0] == 1234567.5


def test_an_unparseable_csv_value_is_kept_as_text_not_dropped(tmp_path: Path) -> None:
    """Dropping it would turn a filer's typo into an unreported figure."""
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("table,row,column,value\nT01.00.01.01,0010,0010,n/a\n")

    # Act
    facts = read_csv(path, build_header()).facts

    # Assert
    assert facts.height == 1
    assert (facts["value"][0], facts["text_value"][0]) == (None, "n/a")


def test_an_explicit_text_value_is_not_overwritten_by_the_rescue(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("table,row,column,value,text_value\nT01.00.01.01,0010,0030,,a comment\n")

    # Act
    facts = read_csv(path, build_header()).facts

    # Assert
    assert (facts["value"][0], facts["text_value"][0]) == (None, "a comment")


def test_an_empty_csv_cell_is_not_a_fact(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("table,row,column,value\nT01.00.01.01,0010,0010,\nT01.00.01.01,0020,0010,5\n")

    # Act / Assert
    assert read_csv(path, build_header()).facts["row"].to_list() == ["0020"]


def test_parquet_round_trips_the_canonical_frame(tmp_path: Path) -> None:
    # Arrange
    frame = pl.DataFrame(
        {
            "table": ["T02.00.01.01", "T01.00.01.01"],
            "sheet": ["0001", None],
            "open_key": [None, None],
            "row": ["0010", "0010"],
            "column": ["0010", "0030"],
            "value": [60.0, None],
            "text_value": [None, "a comment"],
        },
        schema=FACT_SCHEMA,
    )
    path = tmp_path / "facts.parquet"
    frame.write_parquet(path)

    # Act
    facts = read_parquet(path, build_header()).facts

    # Assert
    assert facts.equals(frame)


def test_read_return_dispatches_on_the_suffix(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.CSV"
    path.write_text("table,row,column,value\nT01.00.01.01,0010,0010,1\n")

    # Act / Assert
    assert read_return(path, build_header()).facts.height == 1


def test_a_fact_table_without_a_header_is_a_usage_error(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "facts.csv"
    path.write_text("table,row,column,value\nT01.00.01.01,0010,0010,1\n")

    # Act / Assert
    with pytest.raises(ValueError, match="supply the return header"):
        read_return(path)


def test_an_unsupported_suffix_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_return(tmp_path / "facts.json", build_header())
