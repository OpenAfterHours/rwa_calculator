"""
Progress: a long check says which step it is on and how far through it it is.

What is pinned, and against what:

- The steps a validation reports come from the validation itself, on the real
  PRA001 rule book: the rule count it reports is ``RuleReport.rules_enforced``,
  the rule book's own number, not one this test counts — so a step that skipped
  or double-counted rules cannot agree with it.
- The verdict is the same with a watcher as without: progress is told, never
  asked, so it cannot change what is found.
- The printer is driven by a hand-wound clock, so throttling is measured, not
  slept through.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest

from dash_builders import BROKEN_CSV, CLEAN_CSV, HEADER
from rwa_filer.evidence import collect_evidence
from rwa_filer.filing import build_filing
from rwa_filer.progress import (
    PHASE_READING,
    PHASE_RULES,
    PHASE_STRUCTURE,
    PHASE_WRITING,
    Progress,
    StreamProgress,
    elapsed,
)
from rwa_filer.readers import open_source
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.readers import SourceReading


@pytest.fixture
def broken(tmp_path: Path) -> SourceReading:
    path = tmp_path / "broken.csv"
    path.write_text(BROKEN_CSV)
    return open_source(path, HEADER)


@pytest.fixture
def clean(tmp_path: Path) -> SourceReading:
    path = tmp_path / "clean.csv"
    path.write_text(CLEAN_CSV)
    return open_source(path, HEADER)


class _Clock:
    """A clock that moves only when told to."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# What a validation reports
# ---------------------------------------------------------------------------


def test_a_validation_reports_the_structure_then_every_rule_one_by_one(
    broken: SourceReading,
) -> None:
    # Arrange
    heard: list[Progress] = []

    # Act
    validation = validate_return(broken.ret, release=broken.release, progress=heard.append)

    # Assert
    assert validation.report is not None
    enforced = validation.report.rules_enforced
    assert enforced > 1, "a rule book of one rule cannot show the count moving"
    assert heard[0] == Progress(PHASE_STRUCTURE, subject=broken.release.version)
    rules = heard[1:]
    assert {event.phase for event in rules} == {PHASE_RULES}
    assert [event.done for event in rules] == list(range(enforced + 1))
    assert {event.total for event in rules} == {enforced}


def test_watching_a_validation_does_not_change_its_verdict(broken: SourceReading) -> None:
    # Act
    watched = validate_return(broken.ret, release=broken.release, progress=lambda _event: None)
    unwatched = validate_return(broken.ret, release=broken.release)

    # Assert
    assert watched.report is not None and unwatched.report is not None
    assert watched.report.results == unwatched.report.results
    assert watched.findings == unwatched.findings


def test_collecting_evidence_reports_the_same_steps_as_a_validation(
    broken: SourceReading,
) -> None:
    # Arrange
    validated: list[Progress] = []
    traced: list[Progress] = []
    validate_return(broken.ret, release=broken.release, progress=validated.append)

    # Act
    collect_evidence(broken.ret, release=broken.release, progress=traced.append)

    # Assert
    assert traced == validated


def test_a_build_that_writes_reports_writing_after_the_rules(
    clean: SourceReading, tmp_path: Path
) -> None:
    # Arrange
    heard: list[Progress] = []

    # Act
    package = build_filing(
        clean.ret, tmp_path / "out", release=clean.release, progress=heard.append
    )

    # Assert
    assert package.written
    assert [event.phase for event in heard][-2:] == [PHASE_RULES, PHASE_WRITING]


def test_a_build_refused_by_its_rules_never_reports_writing(
    broken: SourceReading, tmp_path: Path
) -> None:
    # Arrange
    heard: list[Progress] = []

    # Act
    package = build_filing(
        broken.ret, tmp_path / "out", release=broken.release, progress=heard.append
    )

    # Assert
    assert not package.written
    assert heard, "the build was not watched at all"
    assert PHASE_WRITING not in {event.phase for event in heard}


# ---------------------------------------------------------------------------
# How a step reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "line"),
    [
        (Progress(PHASE_READING, subject="return.xbrl"), "Reading return.xbrl"),
        (Progress(PHASE_READING), "Reading the file"),
        (
            Progress(PHASE_STRUCTURE, subject="4.1.1"),
            "Checking the structure against taxonomy 4.1.1",
        ),
        (
            Progress(PHASE_RULES, 612, 1441),
            "Evaluating the published rules: 612 of 1,441 (42%)",
        ),
        (Progress(PHASE_WRITING), "Writing the filing package"),
    ],
)
def test_each_step_reads_as_a_sentence(event: Progress, line: str) -> None:
    assert event.describe() == line


def test_a_count_is_never_rounded_up_to_finished() -> None:
    # Act
    almost = Progress(PHASE_RULES, 1440, 1441)

    # Assert
    assert almost.percent == 99


def test_a_step_that_is_not_counted_has_no_percentage() -> None:
    assert Progress(PHASE_STRUCTURE).percent is None


@pytest.mark.parametrize(("seconds", "text"), [(0.4, "0s"), (59.9, "59s"), (65, "1m 05s")])
def test_elapsed_time_reads_at_a_glance(seconds: float, text: str) -> None:
    assert elapsed(seconds) == text


# ---------------------------------------------------------------------------
# The printer
# ---------------------------------------------------------------------------


def test_a_terminal_line_is_rewritten_in_place_and_cleared_at_the_end() -> None:
    # Arrange
    stream, clock = io.StringIO(), _Clock()
    printer = StreamProgress(stream, live=True, clock=clock)

    # Act
    printer(Progress(PHASE_STRUCTURE, subject="4.1.1"))
    clock.now = 1.0
    printer(Progress(PHASE_RULES, 1, 3))
    printer.close()

    # Assert
    written = stream.getvalue()
    assert "\n" not in written
    first = "\rChecking the structure against taxonomy 4.1.1 - 0s"
    second = "\rEvaluating the published rules: 1 of 3 (33%) - 1s"
    assert written.startswith(first + second)
    assert written.endswith("\r" + " " * len(first.strip("\r")) + "\r")


def test_a_terminal_line_is_not_redrawn_faster_than_it_can_be_read() -> None:
    # Arrange
    stream, clock = io.StringIO(), _Clock()
    printer = StreamProgress(stream, live=True, clock=clock)
    printer(Progress(PHASE_RULES, 0, 100))

    # Act — the same step, a hundredth of a second later, then a tenth.
    clock.now = 0.01
    printer(Progress(PHASE_RULES, 1, 100))
    clock.now = 0.2
    printer(Progress(PHASE_RULES, 2, 100))

    # Assert
    written = stream.getvalue()
    assert "0 of 100" in written and "2 of 100" in written
    assert "1 of 100" not in written


def test_the_end_of_a_counted_step_is_always_drawn() -> None:
    # Arrange
    stream, clock = io.StringIO(), _Clock()
    printer = StreamProgress(stream, live=True, clock=clock)
    printer(Progress(PHASE_RULES, 0, 2))

    # Act — finished within the redraw interval.
    printer(Progress(PHASE_RULES, 2, 2))

    # Assert
    assert "2 of 2 (100%)" in stream.getvalue()


def test_a_shorter_line_blanks_what_the_longer_one_left() -> None:
    # Arrange
    stream, clock = io.StringIO(), _Clock()
    printer = StreamProgress(stream, live=True, clock=clock)
    printer(Progress(PHASE_STRUCTURE, subject="4.1.1"))
    longer = len("Checking the structure against taxonomy 4.1.1 - 0s")

    # Act
    printer(Progress(PHASE_WRITING))

    # Assert
    shorter = "Writing the filing package - 0s"
    assert stream.getvalue().endswith("\r" + shorter + " " * (longer - len(shorter)))


def test_a_log_gets_one_line_per_step_and_per_tenth_of_the_rules() -> None:
    # Arrange
    stream = io.StringIO()
    printer = StreamProgress(stream, live=False, clock=_Clock())

    # Act
    printer(Progress(PHASE_READING, subject="return.xbrl"))
    printer(Progress(PHASE_STRUCTURE, subject="4.1.1"))
    for done in range(201):
        printer(Progress(PHASE_RULES, done, 200))
    printer.close()

    # Assert
    lines = stream.getvalue().splitlines()
    assert "\r" not in stream.getvalue()
    assert lines[:2] == [
        "Reading return.xbrl - 0s",
        "Checking the structure against taxonomy 4.1.1 - 0s",
    ]
    rules = [line for line in lines if line.startswith("Evaluating")]
    assert [line.split("(")[1].split(")")[0] for line in rules] == [
        f"{tenth * 10}%" for tenth in range(11)
    ]
