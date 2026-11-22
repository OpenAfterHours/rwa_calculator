"""
``rwa-filer compare`` on returns the corporates fixtures cannot express.

Pipeline position:
    two fact tables on disk  ->  cli.main(["compare", ...])  ->  text / JSON on stdout

Key responsibilities:
- A comparison whose differing cells all sit in a table with no sheets prints
  its findings. It used to end in a traceback, with the exit code that also
  means "the returns differ", so a script could not tell a crash from an answer.
- The JSON record is the same whatever Python's hash seed: where two rows of a
  move differ by the same amount, which one is named is decided by cell order.

References:
- tests/test_cli_compare.py — the command on the corporates returns
- tests/test_evidence.py — the same two-seed check for the evidence file
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from compare_builders import (
    ALL_COUNTRIES,
    COUNTRIES,
    RETAIL,
    TIED_MOVE,
    geographical_csv,
    own_funds_csv,
)
from dash_builders import HEADER_ARGS_CLI
from rwa_filer.cli import EXIT_FAILED, main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_a_difference_in_a_table_with_no_sheets_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    (tmp_path / "filed.csv").write_text(own_funds_csv(1_000_000.0))
    (tmp_path / "resubmitted.csv").write_text(own_funds_csv(1_500_000.0))
    paths = [str(tmp_path / "filed.csv"), str(tmp_path / "resubmitted.csv")]

    # Act
    code = main(["compare", *paths, *HEADER_ARGS_CLI])

    # Assert
    text = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert text.startswith("DIFFERENT: 1 finding to explain (1 at the inputs)")
    assert "4 differences that move together" in text


def test_the_json_record_is_the_same_whatever_the_hash_seed(tmp_path: Path) -> None:
    # Arrange - two processes: string hashing differs, the record must not. The
    # submission date is given, so a run either side of midnight cannot differ by it.
    (tmp_path / "baseline.csv").write_text(geographical_csv())
    (tmp_path / "candidate.csv").write_text(geographical_csv(restated=TIED_MOVE))
    script = "import sys; from rwa_filer.cli import main; sys.exit(main(sys.argv[1:]))"
    command = [sys.executable, "-c", script, "compare"]
    command += [str(tmp_path / "baseline.csv"), str(tmp_path / "candidate.csv")]
    command += [*HEADER_ARGS_CLI, "--format", "json", "--submission-date", "2027-05-01"]

    def run(seed: str) -> str:
        done = subprocess.run(
            command,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == EXIT_FAILED, done.stderr
        return done.stdout

    # Act
    first, second = run("1"), run("2")

    # Assert - adequacy first: the pair holds a move with tied rows, or the seeds prove nothing.
    moves = [move for item in json.loads(first)["findings"] for move in item["moves"]]
    sheets = {move["open_key"] for move in moves}
    assert sheets == {*COUNTRIES, ALL_COUNTRIES}, f"moves found on {sorted(sheets)} only"
    assert {move["baseline_row"] for move in moves} == {RETAIL}
    assert first == second
