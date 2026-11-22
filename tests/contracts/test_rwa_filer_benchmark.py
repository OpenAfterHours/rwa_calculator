"""
The rwa-filer benchmark times commands the command line still accepts.

Pipeline position:
    (no pipeline stage — a contract on ``scripts/rwa_filer_benchmark.py``)

Key responsibilities:
- Every case the benchmark times parses with the ``rwa-filer`` argument parser
  as it stands, so a renamed option or sub-command fails here rather than
  turning a case into a usage error that the benchmark would time as a
  three-hundred-millisecond "command".

References:
- scripts/rwa_filer_benchmark.py
- docs/plans/rwa-filer-performance-review-2026-11-22.md
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import rwa_filer_benchmark as benchmark

from rwa_filer.cli import build_parser


@pytest.mark.parametrize("case", benchmark.CASES, ids=lambda case: case.name)
def test_every_benchmark_case_is_a_command_the_cli_accepts(case: benchmark.Case) -> None:
    """A case's arguments parse to a sub-command with a handler."""
    # Arrange
    parser = build_parser()
    argv = case.arguments(Path("returns"), Path("out"))

    # Act
    if argv == ["--help"]:
        with pytest.raises(SystemExit) as stopped:
            parser.parse_args(argv)
        # Assert
        assert stopped.value.code == 0
        return
    parsed = parser.parse_args(argv)

    # Assert
    assert getattr(parsed, "handler", None) is not None, f"{case.name} names no command"


def test_the_benchmark_covers_every_command_the_review_measured() -> None:
    """The table the review quotes has a row for each kind of command."""
    # Arrange
    commands = {case.argv[0] for case in benchmark.CASES}

    # Assert
    assert {"validate", "build", "compare", "diff", "taxonomy", "--help"} <= commands
