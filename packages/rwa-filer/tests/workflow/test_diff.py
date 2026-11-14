"""The resubmission diff: what changed between two versions of a return."""

from __future__ import annotations

import polars as pl

from pack_builders import build_return
from rwa_filer.workflow.diff import (
    CHANGE_ADDED,
    CHANGE_CHANGED,
    CHANGE_REMOVED,
    CHANGE_SCHEMA,
    diff_returns,
)

T01 = "T01.00.01.01"
T02 = "T02.00.01.01"
COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]


def ret(*rows: tuple[object, ...], **header: object):  # noqa: ANN201 - a CanonicalReturn
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"), **header)


FILED = ret(
    (T01, None, None, "0010", "0010", 100.0),
    (T01, None, None, "0020", "0010", 60.0),
    (T01, None, None, "0010", "0030", None, "first note"),
    (T02, "0001", None, "0010", "0010", 5.0),
)


def test_a_return_does_not_differ_from_itself() -> None:
    # Act
    difference = diff_returns(FILED, FILED)

    # Assert
    assert difference.is_identical and difference.unchanged == 4
    assert difference.changes.schema == CHANGE_SCHEMA
    assert difference.counts() == {CHANGE_ADDED: 0, CHANGE_REMOVED: 0, CHANGE_CHANGED: 0}


def test_changed_added_and_removed_cells_are_each_named() -> None:
    # Arrange — one figure restated, one cell added, one dropped, one note reworded.
    resubmitted = ret(
        (T01, None, None, "0010", "0010", 110.0),
        (T01, None, None, "0020", "0010", 60.0),
        (T01, None, None, "0030", "0010", 50.0),
        (T01, None, None, "0010", "0030", None, "second note"),
    )

    # Act
    difference = diff_returns(FILED, resubmitted)
    rows = {
        (row["table"], row["row"], row["column"]): row
        for row in difference.changes.iter_rows(named=True)
    }

    # Assert
    assert difference.counts() == {CHANGE_ADDED: 1, CHANGE_REMOVED: 1, CHANGE_CHANGED: 2}
    assert difference.unchanged == 1 and not difference.is_identical
    restated = rows[(T01, "0010", "0010")]
    assert (restated["change"], restated["before"], restated["after"], restated["delta"]) == (
        CHANGE_CHANGED,
        100.0,
        110.0,
        10.0,
    )
    assert rows[(T01, "0030", "0010")]["change"] == CHANGE_ADDED
    assert rows[(T02, "0010", "0010")]["change"] == CHANGE_REMOVED
    note = rows[(T01, "0010", "0030")]
    assert (note["before_text"], note["after_text"]) == ("first note", "second note")
    assert difference.by_table() == {T01: 3, T02: 1}


def test_a_cell_is_matched_on_its_sheet_as_well_as_its_row_and_column() -> None:
    # Arrange — the same row and column, on a different sheet.
    moved = ret(
        (T01, None, None, "0010", "0010", 100.0),
        (T01, None, None, "0020", "0010", 60.0),
        (T01, None, None, "0010", "0030", None, "first note"),
        (T02, "0002", None, "0010", "0010", 5.0),
    )

    # Act
    difference = diff_returns(FILED, moved)

    # Assert — one removed from sheet 0001, one added on sheet 0002.
    assert difference.counts() == {CHANGE_ADDED: 1, CHANGE_REMOVED: 1, CHANGE_CHANGED: 0}
    assert sorted(difference.changes["sheet"].to_list()) == ["0001", "0002"]


def test_restating_only_the_accuracy_is_not_a_change_of_content() -> None:
    restated = ret(
        (T01, None, None, "0010", "0010", 100.0, None, 2),
        (T01, None, None, "0020", "0010", 60.0, None, 2),
        (T01, None, None, "0010", "0030", None, "first note"),
        (T02, "0001", None, "0010", "0010", 5.0),
    )

    assert diff_returns(FILED, restated).is_identical


def test_a_different_header_is_reported_apart_from_the_cells() -> None:
    """Usually it means the wrong two files are being compared."""
    # Arrange
    other = ret(*FILED.facts.rows(), entity_identifier="213800ABCDEFGHIJKL12")

    # Act
    difference = diff_returns(FILED, other)

    # Assert
    assert difference.changes.is_empty() and not difference.is_identical
    assert difference.header == {
        "Entity identifier": ("5493001KJTIIGC8Y1R12", "213800ABCDEFGHIJKL12")
    }


def test_the_record_is_json_ready() -> None:
    # Arrange
    resubmitted = ret((T01, None, None, "0010", "0010", 110.0))

    # Act
    record = diff_returns(FILED, resubmitted).as_record()

    # Assert
    assert record["identical"] is False
    assert record["counts"] == {CHANGE_ADDED: 0, CHANGE_REMOVED: 3, CHANGE_CHANGED: 1}
    assert len(record["changes"]) == 4 and record["by_table"] == {T01: 3, T02: 1}
