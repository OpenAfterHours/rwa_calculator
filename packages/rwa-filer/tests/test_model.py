"""The canonical return: header round trip and fact-table normalisation."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from pack_builders import VALID_LEI, build_header
from rwa_filer.model import FACT_SCHEMA, LEI_SCHEME, CanonicalReturn, ReturnHeader

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def test_header_defaults_to_the_lei_scheme_and_sterling() -> None:
    # Act
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), "PRA001")

    # Assert
    assert (header.entity_scheme, header.currency) == (LEI_SCHEME, "GBP")


def test_header_fields_round_trip() -> None:
    # Arrange
    header = build_header(entity_name="Example Bank", consolidation_basis="consolidated")

    # Act
    rebuilt = ReturnHeader.from_fields(header.as_fields())

    # Assert
    assert rebuilt == header


def test_optional_header_fields_are_omitted_when_unset() -> None:
    # Act
    fields = build_header().as_fields()

    # Assert
    assert "Entity name" not in fields and "Consolidation basis" not in fields


def test_header_labels_are_read_case_insensitively_and_dates_may_carry_a_time() -> None:
    # Arrange
    fields = {
        "ENTITY IDENTIFIER": VALID_LEI,
        "reference date": "2027-03-31 00:00:00",
        "Module": " PRA001 ",
    }

    # Act
    header = ReturnHeader.from_fields(fields)

    # Assert
    assert (header.reference_date, header.module) == (date(2027, 3, 31), "PRA001")


@pytest.mark.parametrize("missing", ["Entity identifier", "Reference date", "Module"])
def test_a_missing_required_header_field_is_named(missing: str) -> None:
    # Arrange
    fields = build_header().as_fields()
    del fields[missing]

    # Act / Assert
    with pytest.raises(ValueError, match=missing):
        ReturnHeader.from_fields(fields)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _frame(**columns: list[object]) -> pl.DataFrame:
    return pl.DataFrame(columns)


def test_from_frame_yields_exactly_the_fact_schema() -> None:
    # Arrange — only the required columns, in a scrambled order, with an extra.
    frame = _frame(value=[1.0], column=["0010"], extra=["x"], row=["0010"], table=["T01"])

    # Act
    ret = CanonicalReturn.from_frame(build_header(), frame)

    # Assert
    assert ret.facts.schema == FACT_SCHEMA
    assert ret.facts.row(0) == ("T01", None, None, "0010", "0010", 1.0, None, None)


def test_codes_read_as_numbers_get_their_leading_zeros_back() -> None:
    """A CSV or spreadsheet round trip is the usual way ``0010`` becomes ``10``."""
    # Arrange
    frame = _frame(table=["T01"], sheet=[8], row=[10], column=[30], value=[1.0])

    # Act
    facts = CanonicalReturn.from_frame(build_header(), frame).facts

    # Assert
    assert (facts["sheet"][0], facts["row"][0], facts["column"][0]) == ("0008", "0010", "0030")


def test_codes_that_arrive_as_text_are_left_exactly_as_written() -> None:
    """Padding text would hide a filer's wrong code from the structure check."""
    # Arrange
    frame = _frame(table=["T01"], row=["10"], column=[" 0010 "], value=[1.0])

    # Act
    facts = CanonicalReturn.from_frame(build_header(), frame).facts

    # Assert
    assert (facts["row"][0], facts["column"][0]) == ("10", "0010")


def test_an_unreported_cell_is_not_a_fact() -> None:
    # Arrange — a null value with no text, and a blank text value.
    frame = _frame(
        table=["T01", "T01", "T01"],
        row=["0010", "0020", "0030"],
        column=["0010", "0010", "0010"],
        value=[1.0, None, None],
        text_value=[None, None, "   "],
    )

    # Act
    facts = CanonicalReturn.from_frame(build_header(), frame).facts

    # Assert
    assert facts["row"].to_list() == ["0010"]


def test_a_reported_zero_is_a_fact() -> None:
    # Arrange
    frame = _frame(table=["T01"], row=["0010"], column=["0010"], value=[0.0])

    # Act
    facts = CanonicalReturn.from_frame(build_header(), frame).facts

    # Assert
    assert facts.height == 1 and facts["value"][0] == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_number_is_not_a_reportable_figure(bad: float) -> None:
    # Arrange
    frame = _frame(table=["T01"], row=["0010"], column=["0010"], value=[bad])

    # Act
    facts = CanonicalReturn.from_frame(build_header(), frame).facts

    # Assert
    assert facts.is_empty()


@pytest.mark.parametrize("missing", ["table", "row", "column", "value"])
def test_a_frame_without_a_required_column_is_refused(missing: str) -> None:
    # Arrange
    columns = {"table": ["T01"], "row": ["0010"], "column": ["0010"], "value": [1.0]}
    del columns[missing]

    # Act / Assert
    with pytest.raises(ValueError, match=missing):
        CanonicalReturn.from_frame(build_header(), pl.DataFrame(columns))


def test_tables_lists_the_distinct_table_codes_sorted() -> None:
    # Arrange
    frame = _frame(
        table=["T02", "T01", "T02"],
        row=["0010"] * 3,
        column=["0010", "0010", "0020"],
        value=[1.0, 2.0, 3.0],
    )

    # Act
    ret = CanonicalReturn.from_frame(build_header(), frame)

    # Assert
    assert ret.tables == ("T01", "T02")
    assert ret.table_facts("T02").height == 2


def test_decimals_is_optional_and_kept_as_given() -> None:
    # Arrange
    frame = pl.DataFrame(
        {
            "table": ["T01", "T01"],
            "row": ["0010", "0020"],
            "column": ["0010", "0010"],
            "value": [1000.0, 2.5],
            "decimals": [-3, None],
        }
    )

    # Act
    ret = CanonicalReturn.from_frame(build_header(), frame)

    # Assert
    assert ret.facts["decimals"].to_list() == [-3, None]
    assert ret.facts.schema["decimals"] == pl.Int32


def test_filing_indicators_default_to_unset_and_are_kept_when_declared() -> None:
    # Arrange
    frame = pl.DataFrame({"table": ["T01"], "row": ["0010"], "column": ["0010"], "value": [1.0]})

    # Act
    derived = CanonicalReturn.from_frame(build_header(), frame)
    declared = CanonicalReturn.from_frame(build_header(), frame, {"T01.00": True, "T02.00": False})

    # Assert
    assert derived.indicators is None
    assert declared.indicators == {"T01.00": True, "T02.00": False}
