"""
``--progress``: the commands that validate say on stderr how far they have got.

A full PRA001 return takes tens of seconds to validate, almost all of it in the
published rules, and a command that prints nothing for that long reads as a
hang. What is pinned:

- ``validate``, ``build`` and ``dash FILE`` report each step, and count the
  rules up to the number the report itself says were enforced;
- progress goes to stderr only, so stdout stays exactly the result — a JSON
  report piped onwards still parses;
- the default follows stderr: on a terminal, a line rewritten in place and
  cleared before the result; anywhere else, nothing, unless ``--progress`` asks.
"""

from __future__ import annotations

import io
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

import rwa_filer.dash
from dash_builders import BROKEN_CSV, CLEAN_CSV, HEADER_ARGS_CLI
from rwa_filer.cli import EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path


class _Terminal(io.StringIO):
    """A stream that says it is a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def broken_csv(tmp_path: Path) -> Path:
    path = tmp_path / "broken.csv"
    path.write_text(BROKEN_CSV)
    return path


def _as_stderr(monkeypatch: pytest.MonkeyPatch) -> _Terminal:
    """Make stderr a terminal a person is watching, and return it.

    Called in the test body, not a fixture: pytest's capture puts its own
    streams back at the start of the call phase, over a fixture's.
    """
    stream = _Terminal()
    monkeypatch.setattr(sys, "stderr", stream)
    return stream


def _enforced(report: Path) -> int:
    return json.loads(report.read_text())["summary"]["rules_enforced"]


def test_validate_reports_each_step_and_counts_every_rule_when_asked(
    tmp_path: Path, broken_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    report = tmp_path / "report.json"

    # Act
    main(["validate", str(broken_csv), *HEADER_ARGS_CLI, "--progress", "--report", str(report)])

    # Assert
    err = capsys.readouterr().err
    enforced = _enforced(report)
    lines = err.splitlines()
    assert lines[0].startswith("Reading broken.csv - ")
    assert lines[1].startswith("Checking the structure against taxonomy 4.1.1 - ")
    assert f"Evaluating the published rules: 0 of {enforced:,} (0%)" in err
    assert f"Evaluating the published rules: {enforced:,} of {enforced:,} (100%)" in err


def test_progress_never_reaches_stdout(
    broken_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(broken_csv), *HEADER_ARGS_CLI, "--progress", "--format", "json"])

    # Assert
    captured = capsys.readouterr()
    assert "Evaluating the published rules" in captured.err
    assert json.loads(captured.out)["status"] == "BLOCKED"


def test_validate_is_silent_on_stderr_by_default_when_it_is_not_a_terminal(
    broken_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(broken_csv), *HEADER_ARGS_CLI])

    # Assert
    assert capsys.readouterr().err == ""


def test_on_a_terminal_progress_is_one_line_cleared_before_the_result(
    broken_csv: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    terminal = _as_stderr(monkeypatch)

    # Act
    main(["validate", str(broken_csv), *HEADER_ARGS_CLI])

    # Assert
    shown = terminal.getvalue()
    assert "\rEvaluating the published rules" in shown
    assert "\n" not in shown, "a live line never scrolls"
    assert shown.endswith("\r"), "the line is blanked before the result is printed"
    assert capsys.readouterr().out.startswith("BLOCKED")


def test_no_progress_silences_it_on_a_terminal(
    broken_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    terminal = _as_stderr(monkeypatch)

    # Act
    main(["validate", str(broken_csv), *HEADER_ARGS_CLI, "--no-progress"])

    # Assert
    assert terminal.getvalue() == ""


def test_build_reports_writing_the_package_after_the_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    clean = tmp_path / "clean.csv"
    clean.write_text(CLEAN_CSV)

    # Act
    code = main(
        ["build", str(clean), *HEADER_ARGS_CLI, "--out", str(tmp_path / "out"), "--progress"]
    )

    # Assert
    lines = capsys.readouterr().err.splitlines()
    assert code == EXIT_OK
    assert lines[-2].startswith("Evaluating the published rules")
    assert lines[-1].startswith("Writing the filing package - ")


def test_dash_reports_how_far_opening_its_file_has_got_before_serving(
    tmp_path: Path,
    broken_csv: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — record that serving started, instead of serving.
    served: list[Any] = []
    monkeypatch.setattr(rwa_filer.dash, "serve", lambda workspace, **_options: served.append(1))

    # Act
    main(
        [
            "dash",
            str(broken_csv),
            *HEADER_ARGS_CLI,
            "--no-browser",
            "--workdir",
            str(tmp_path / "w"),
            "--progress",
        ]
    )

    # Assert
    err = capsys.readouterr().err
    assert served == [1]
    assert "Reading broken.csv" in err
    assert "(100%)" in err
