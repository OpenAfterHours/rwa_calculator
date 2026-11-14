"""Cell adjustments: applied whole or not at all, with the before and after kept."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from pack_builders import build_return
from rwa_filer.model import CanonicalReturn
from rwa_filer.workflow.adjustments import (
    ACTION_CHANGE,
    ACTION_NONE,
    ACTION_REMOVE,
    ACTION_SET,
    Adjustment,
    AdjustmentError,
    apply_adjustments,
    read_adjustments,
)

T01 = "T01.00.01.01"
T02 = "T02.00.01.01"


def base() -> CanonicalReturn:
    return build_return(
        pl.DataFrame(
            {
                "table": [T01, T01, T02],
                "sheet": [None, None, "0001"],
                "row": ["0010", "0020", "0010"],
                "column": ["0010", "0010", "0010"],
                "value": [100.0, 60.0, 5.0],
                "decimals": [2, None, None],
            }
        )
    )


def cells(ret: CanonicalReturn) -> dict[tuple[str, str | None, str], float | None]:
    return {
        (table, sheet, row): value
        for table, sheet, row, value in ret.facts.select("table", "sheet", "row", "value").rows()
    }


def test_a_cell_is_changed_set_or_removed_and_the_rest_is_untouched() -> None:
    # Arrange
    batch = [
        Adjustment(T01, "0010", "0010", "Restated after the ledger close", value=110.0),
        Adjustment(T01, "0030", "0010", "Part two was omitted by the feed", value=50.0),
        Adjustment(T02, "0010", "0010", "Not our exposure", sheet="0001", remove=True),
    ]

    # Act
    adjusted, applied = apply_adjustments(base(), batch)

    # Assert
    assert cells(adjusted) == {
        (T01, None, "0010"): 110.0,
        (T01, None, "0020"): 60.0,
        (T01, None, "0030"): 50.0,
    }
    assert [(item.action, item.before, item.after) for item in applied] == [
        (ACTION_CHANGE, 100.0, 110.0),
        (ACTION_SET, None, 50.0),
        (ACTION_REMOVE, 5.0, None),
    ]


def test_the_original_return_is_not_modified() -> None:
    # Arrange
    original = base()

    # Act
    apply_adjustments(original, [Adjustment(T01, "0010", "0010", "why", value=1.0)])

    # Assert
    assert cells(original)[(T01, None, "0010")] == 100.0


def test_a_changed_cell_keeps_its_stated_accuracy_unless_restated() -> None:
    # Act
    kept, _ = apply_adjustments(base(), [Adjustment(T01, "0010", "0010", "why", value=1.0)])
    restated, _ = apply_adjustments(
        base(), [Adjustment(T01, "0010", "0010", "why", value=1.0, decimals=-3)]
    )

    # Assert
    def accuracy(ret: CanonicalReturn) -> int | None:
        return ret.facts.filter(pl.col("row") == "0010", pl.col("table") == T01)["decimals"][0]

    assert (accuracy(kept), accuracy(restated)) == (2, -3)


def test_setting_a_cell_to_what_it_already_holds_is_recorded_as_no_change() -> None:
    _, applied = apply_adjustments(base(), [Adjustment(T01, "0010", "0010", "why", value=100.0)])

    assert applied[0].action == ACTION_NONE


def test_the_record_of_an_adjustment_carries_the_cell_the_figures_and_the_reason() -> None:
    _, applied = apply_adjustments(
        base(), [Adjustment(T02, "0010", "0010", "Wrong class", sheet="0001", value=7.0)]
    )

    assert applied[0].as_record() == {
        "cell": f"{T02}[z0001][r0010][c0010]",
        "table": T02,
        "sheet": "0001",
        "open_key": None,
        "row": "0010",
        "column": "0010",
        "action": ACTION_CHANGE,
        "before": 5.0,
        "after": 7.0,
        "reason": "Wrong class",
    }


@pytest.mark.parametrize(
    ("adjustment", "problem"),
    [
        (Adjustment(T01, "0010", "0010", " ", value=1.0), "gives no reason"),
        (Adjustment(T01, "0010", "0010", "why"), "exactly one of a value and a text value"),
        (
            Adjustment(T01, "0010", "0010", "why", value=1.0, text_value="x"),
            "exactly one of a value and a text value",
        ),
        (Adjustment(T01, "0099", "0010", "why", remove=True), "does not report"),
        (Adjustment(T01, "0010", "0010", "why", value=1.0, remove=True), "both removes"),
        (Adjustment("", "0010", "0010", "why", value=1.0), "does not name a table"),
    ],
    ids=["no-reason", "no-value", "two-values", "remove-absent", "remove-and-set", "no-cell"],
)
def test_an_adjustment_that_cannot_be_applied_stops_the_whole_batch(
    adjustment: Adjustment, problem: str
) -> None:
    # Arrange — a good adjustment first: it must not be applied either.
    good = Adjustment(T01, "0020", "0010", "why", value=61.0)

    # Act / Assert
    with pytest.raises(AdjustmentError, match=problem) as raised:
        apply_adjustments(base(), [good, adjustment])
    assert len(raised.value.problems) == 1


def test_two_adjustments_to_one_cell_are_refused() -> None:
    batch = [
        Adjustment(T01, "0010", "0010", "first", value=1.0),
        Adjustment(T01, "0010", "0010", "second", value=2.0),
    ]

    with pytest.raises(AdjustmentError, match="repeats a cell"):
        apply_adjustments(base(), batch)


def test_adjustments_are_read_from_csv(tmp_path: Path) -> None:
    # Arrange — codes as a spreadsheet leaves them; a blank value with remove.
    path = tmp_path / "adjustments.csv"
    path.write_text(
        "Table,Sheet,Row,Column,Value,Text_Value,Reason,Remove\n"
        f"{T01},,0010,0010,110.5,,Restated,\n"
        f"{T02},0001,0010,0010,,,Not ours,yes\n"
        f"{T01},,0010,0030,,a note,Comment added,\n"
    )

    # Act
    batch = read_adjustments(path)

    # Assert
    assert batch == [
        Adjustment(T01, "0010", "0010", "Restated", value=110.5),
        Adjustment(T02, "0010", "0010", "Not ours", sheet="0001", remove=True),
        Adjustment(T01, "0010", "0030", "Comment added", text_value="a note"),
    ]


def test_an_adjustments_file_needs_a_reason_column(tmp_path: Path) -> None:
    path = tmp_path / "adjustments.csv"
    path.write_text("table,row,column,value\nT,1,1,1\n")

    with pytest.raises(ValueError, match="missing column.*reason"):
        read_adjustments(path)
    with pytest.raises(ValueError, match="Unsupported adjustments file type"):
        read_adjustments(tmp_path / "adjustments.json")
