"""``rwa-filer validate`` / ``build`` with ``--breakdown``: a detail file summed, and its breaks traced."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from detail_builders import HEADER_ARGS, detail_rows, write_detail
from rwa_filer.cli import EXIT_FAILED, main

if TYPE_CHECKING:
    from pathlib import Path


def test_validate_with_a_breakdown_traces_each_broken_rule_to_its_members(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")

    # Act
    code = main(["validate", str(path), *HEADER_ARGS, "--breakdown", "business_unit,source"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_FAILED, "boe_b0471 is an Error-severity break"
    assert "Where the breaks come from, by business_unit: 22 of 22" in out
    assert "Asset Finance breaks all 4, out by +100,000" in out
    assert "Where the breaks come from, by source" in out
    assert "JNL-1 breaks all 8, out by +50,000" in out


def test_validate_json_carries_the_detail_and_each_attribution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")

    # Act
    main(["validate", str(path), *HEADER_ARGS, "--breakdown", "business_unit", "--format", "json"])

    # Assert
    record = json.loads(capsys.readouterr().out)
    assert record["breakdown"]["detail"]["rows_read"] == len(detail_rows())
    assert [item["dimension"] for item in record["breakdown"]["by"]] == ["business_unit"]


def test_validate_without_a_breakdown_reports_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange: the same file, one row per cell is not what it holds — read as a
    # return, its repeated cells are duplicate facts, as they always were.
    path = write_detail(tmp_path / "detail.csv")

    # Act
    code = main(["validate", str(path), *HEADER_ARGS, "--format", "json"])

    # Assert
    record = json.loads(capsys.readouterr().out)
    assert code == EXIT_FAILED
    assert "breakdown" not in record
    assert "STR005" in {finding["code"] for finding in record["findings"]}


def test_a_line_reference_given_twice_in_a_cell_stops_validate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    rows = detail_rows()
    path = write_detail(tmp_path / "detail.csv", rows + rows[:1])

    # Act
    code = main(
        [
            "validate",
            str(path),
            *HEADER_ARGS,
            "--breakdown",
            "business_unit",
            "--line-ref",
            "line_id",
        ]
    )

    # Assert
    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert "line reference 'L0001' is given 2 times" in captured.err
    assert captured.out == ""


def test_keep_one_validates_a_file_whose_repeats_agree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    rows = detail_rows()
    path = write_detail(tmp_path / "detail.csv", rows + rows[:3])

    # Act
    main(
        [
            "validate",
            str(path),
            *HEADER_ARGS,
            "--breakdown",
            "business_unit",
            "--line-ref",
            "line_id",
            "--on-repeat",
            "keep-one",
            "--format",
            "json",
        ]
    )

    # Assert
    record = json.loads(capsys.readouterr().out)
    assert record["breakdown"]["detail"]["repeats_dropped"] == 3


def test_build_records_the_detail_in_the_manifest_and_only_then(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = write_detail(tmp_path / "detail.csv")
    args = ["--force", "--no-timestamp", "--name", "return"]

    # Act
    main(
        [
            "build",
            str(path),
            *HEADER_ARGS,
            "--out",
            str(tmp_path / "a"),
            "--breakdown",
            "source",
            *args,
        ]
    )
    summed = tmp_path / "summed.csv"
    summed.write_text(
        "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n", encoding="utf-8"
    )
    main(["build", str(summed), *HEADER_ARGS, "--out", str(tmp_path / "b"), *args])
    capsys.readouterr()

    # Assert
    with_detail = json.loads((tmp_path / "a" / "return.manifest.json").read_text(encoding="utf-8"))
    without = json.loads((tmp_path / "b" / "return.manifest.json").read_text(encoding="utf-8"))
    assert with_detail["detail"]["file"] == "detail.csv"
    assert with_detail["detail"]["breakdown"] == ["source"]
    assert "detail" not in without
