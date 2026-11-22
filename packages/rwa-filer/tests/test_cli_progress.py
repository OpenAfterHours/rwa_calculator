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
  cleared before the result; anywhere else, nothing, unless ``--progress`` asks;
- a return the taxonomy does not accept is told so on stderr as soon as the
  structure check returns, before the rules run — one line that stays — and
  stdout, the report, the evidence and the exit code are the same bytes with
  progress as without.
"""

from __future__ import annotations

import io
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

import rwa_filer.dash
from dash_builders import BROKEN_CSV, CLEAN_CSV, HEADER_ARGS_CLI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path

#: A return the taxonomy does not accept: facts in rows their tables do not
#: have, in two tables. Its rules still run, and break.
MALFORMED_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,9990,0010,5\n"
    "OF07.00.01.01,0008,9991,0010,6\n"
    "OF02.01.01.01,,9990,0010,7\n"
)
#: How the note on a malformed return starts, after the step it belongs to.
NOTE_LEAD = "Checking the structure against taxonomy 4.1.1: "


class _Terminal(io.StringIO):
    """A stream that says it is a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def broken_csv(tmp_path: Path) -> Path:
    path = tmp_path / "broken.csv"
    path.write_text(BROKEN_CSV)
    return path


@pytest.fixture
def malformed_csv(tmp_path: Path) -> Path:
    path = tmp_path / "malformed.csv"
    path.write_text(MALFORMED_CSV)
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


# ---------------------------------------------------------------------------
# A return the taxonomy does not accept: told after the structure check
# ---------------------------------------------------------------------------


def test_a_malformed_return_is_told_so_before_the_rules_run(
    tmp_path: Path, malformed_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    report = tmp_path / "report.json"

    # Act
    code = main(
        ["validate", str(malformed_csv), *HEADER_ARGS_CLI, "--progress", "--report", str(report)]
    )

    # Assert — the note says what the report says: how many, and the first.
    lines = capsys.readouterr().err.splitlines()
    record = json.loads(report.read_text())
    count = record["summary"]["structure_findings"]
    first = record["findings"][record["summary"]["release_findings"]]
    assert code == EXIT_FAILED and count > 1 and first["code"].startswith("STR")
    notes = [index for index, line in enumerate(lines) if line.startswith(NOTE_LEAD)]
    rules = [index for index, line in enumerate(lines) if line.startswith("Evaluating")]
    assert len(notes) == 1, lines
    assert rules, "no rule ran: there was nothing for the note to come before"
    assert notes[0] < rules[0]
    assert lines[notes[0]].startswith(
        f"{NOTE_LEAD}{count} finding(s); the first: [{first['code']}] {first['severity']}: "
    )


@pytest.mark.parametrize("output", ["text", "json"])
def test_with_and_without_progress_a_malformed_return_gives_the_same_bytes(
    output: str, tmp_path: Path, malformed_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """stdout, the report, the evidence and the exit code: progress only ever adds to stderr."""
    # Arrange
    runs = {}

    # Act
    for switch in ("--progress", "--no-progress"):
        folder = tmp_path / switch.strip("-")
        folder.mkdir()
        code = main(
            [
                "validate",
                str(malformed_csv),
                *HEADER_ARGS_CLI,
                "--format",
                output,
                "--report",
                str(folder / "report.json"),
                "--evidence",
                str(folder / "run.evidence.jsonl"),
                "--no-timestamp",
                switch,
            ]
        )
        captured = capsys.readouterr()
        runs[switch] = (
            code,
            captured.out,
            (folder / "report.json").read_bytes(),
            (folder / "run.evidence.jsonl").read_bytes(),
            captured.err,
        )

    # Assert — the note was told in one run and not the other (stderr carries
    # the evidence file's summary line in both); nothing else differs.
    watched, unwatched = runs["--progress"], runs["--no-progress"]
    assert NOTE_LEAD in watched[4] and NOTE_LEAD not in unwatched[4]
    assert watched[0] == EXIT_FAILED and watched[1]
    assert watched[:4] == unwatched[:4]


def test_on_a_terminal_the_note_stays_and_the_live_line_is_still_cleared(
    malformed_csv: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    terminal = _as_stderr(monkeypatch)

    # Act
    main(["validate", str(malformed_csv), *HEADER_ARGS_CLI])

    # Assert — one line kept, the note; the live line after it blanked before the result.
    kept, live = terminal.getvalue().split("\n")
    assert kept.rsplit("\r", 1)[1].startswith(NOTE_LEAD + "2 finding(s); the first: [STR")
    assert "\rEvaluating the published rules" in live
    assert live.endswith("\r")
    assert capsys.readouterr().out.startswith("BLOCKED")


def test_a_malformed_return_says_nothing_on_stderr_when_progress_is_off(
    malformed_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act — stderr is not a terminal, and --progress was not asked for.
    code = main(["validate", str(malformed_csv), *HEADER_ARGS_CLI])

    # Assert
    captured = capsys.readouterr()
    assert code == EXIT_FAILED and captured.out.startswith("BLOCKED")
    assert captured.err == ""
