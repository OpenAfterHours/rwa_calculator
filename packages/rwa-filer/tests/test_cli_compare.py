"""
``rwa-filer compare`` — a return beside a baseline, from the command line.

The returns are the comparison tests' corporates returns written as CSV fact
tables, the form a person most often has from another system.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from compare_builders import corporate_csv
from dash_builders import HEADER_ARGS_CLI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main


@pytest.fixture
def files(tmp_path: Path) -> dict[str, str]:
    written = {
        "baseline": corporate_csv(risk_weight_row="0200", ecai_columns=True),
        "same": corporate_csv(risk_weight_row="0200", ecai_columns=True),
        "candidate": corporate_csv(risk_weight_row="0220"),
    }
    for name, text in written.items():
        (tmp_path / f"{name}.csv").write_text(text)
    return {name: str(tmp_path / f"{name}.csv") for name in written}


def test_two_equivalent_returns_exit_zero(
    files: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", files["baseline"], files["same"], *HEADER_ARGS_CLI])

    assert code == EXIT_OK
    assert capsys.readouterr().out.startswith("EQUIVALENT")


def test_differing_returns_list_their_findings_and_what_each_points_at(
    files: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", files["baseline"], files["candidate"], *HEADER_ARGS_CLI])

    text = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert text.startswith("DIFFERENT: 2 findings to explain (1 at candidate.csv, 1 at the inputs)")
    assert (
        "[points at the inputs] 1,000,000 is reported in OF07.00.01.01 Corporates row 0220" in text
    )
    assert "[points at candidate.csv] Only baseline.csv reports OF07.00.01.01 column 0230" in text
    assert "boe_b0703     baseline.csv: holds   candidate.csv: breaks" in text


def test_the_json_record_carries_the_verdict_and_every_finding(
    files: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["compare", files["baseline"], files["candidate"], *HEADER_ARGS_CLI, "--format", "json"])

    record = json.loads(capsys.readouterr().out)
    assert record["equivalent"] is False
    assert [item["points_at"] for item in record["findings"]] == ["inputs", "candidate"]
    assert record["names"] == {"baseline": "baseline.csv", "candidate": "candidate.csv"}


def test_a_tolerance_absorbs_differences_a_source_rounded_away(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fact table states no accuracy; --tolerance says how close counts as the same."""
    (tmp_path / "a.csv").write_text(corporate_csv())
    (tmp_path / "b.csv").write_text(corporate_csv(nudge=400.0))
    paths = [str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]

    exact = main(["compare", *paths, *HEADER_ARGS_CLI])
    tolerant = main(["compare", *paths, *HEADER_ARGS_CLI, "--tolerance", "500"])

    capsys.readouterr()
    assert (exact, tolerant) == (EXIT_FAILED, EXIT_OK)


def test_a_missing_file_is_refused_in_one_line(
    files: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", str(tmp_path / "absent.csv"), files["same"], *HEADER_ARGS_CLI])

    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert "absent.csv" in captured.err
    assert captured.out == ""
