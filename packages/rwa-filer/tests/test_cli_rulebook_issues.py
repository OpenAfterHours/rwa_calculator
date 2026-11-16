"""
The command line lists the known issues with the published rules, and labels a break with one.

Pipeline position:
    rwa-filer rulebook issues [ISSUE] / rwa-filer validate
        ->  the packaged publisher-issue register (``boe/data/issues/<release>.json``)

What is pinned: ``rulebook issues`` lists every issue of every shipped release,
shows one in full, renders the register as Markdown for sharing (the same text
``boe.issues_document`` renders) and as JSON, and refuses an unknown issue or
release with one line on stderr; ``validate`` names the issue on a break it
explains, and the exit code is the verdict's, unchanged.

References:
- rwa_filer.boe.issues — the register
- rwa_filer.boe.issues_document — the shareable rendering
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from compare_builders import corporate_csv
from pack_builders import VALID_LEI
from rwa_filer.boe.issues import load_issues
from rwa_filer.boe.issues_document import render_document
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main

if TYPE_CHECKING:
    from pathlib import Path

HEADER_ARGS = [
    "--entity",
    VALID_LEI,
    "--reference-date",
    "2027-03-31",
    "--module",
    "PRA001",
    "--taxonomy",
    "4.1.1",
]


def test_rulebook_issues_lists_every_issue_of_the_release(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Act
    code = main(["rulebook", "issues"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert all(issue.id in out for issue in load_issues("4.1.1").issues)
    assert "PI-15a" in out
    assert "acknowledged" in out


def test_rulebook_issues_shows_one_issue_in_full(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    issue = load_issues("4.1.1").issue("PI-15a")
    assert issue is not None

    # Act
    code = main(["rulebook", "issues", "PI-15a"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert issue.title in out
    assert issue.authority[0].quote in out
    assert "PI-16a" not in out


def test_an_unknown_issue_or_release_exits_1_with_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Act
    unknown_issue = main(["rulebook", "issues", "PI-99"])
    unknown_issue_err = capsys.readouterr().err
    unknown_release = main(["rulebook", "issues", "--taxonomy", "9.9.9"])
    unknown_release_err = capsys.readouterr().err

    # Assert
    assert (unknown_issue, unknown_release) == (EXIT_FAILED, EXIT_FAILED)
    assert len(unknown_issue_err.strip().splitlines()) == 1
    assert "PI-99" in unknown_issue_err
    assert "9.9.9" in unknown_release_err


def test_rulebook_issues_markdown_is_the_shareable_rendering(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Act
    code = main(["rulebook", "issues", "--format", "markdown"])

    # Assert
    assert code == EXIT_OK
    assert capsys.readouterr().out == render_document([load_issues("4.1.1")])


def test_rulebook_issues_json_round_trips(capsys: pytest.CaptureFixture[str]) -> None:
    # Act
    code = main(["rulebook", "issues", "--format", "json", "--module", "PRA001"])

    # Assert
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert [item["release"] for item in payload] == ["4.1.1"]
    assert [issue["id"] for issue in payload[0]["issues"]] == [
        issue.id for issue in load_issues("4.1.1").issues
    ]


def test_a_known_publisher_issue_is_named_in_the_text_and_does_not_change_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before the Bank deactivated boe_b0710, a break of it blocks - and says it is PI-15a."""
    # Arrange
    path = tmp_path / "corporates.csv"
    path.write_text(corporate_csv(ecai_columns=True), encoding="utf-8")

    # Act
    code = main(["validate", str(path), *HEADER_ARGS, "--submission-date", "2026-10-18"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert out.startswith("BLOCKED:")
    assert "Known issue with the published rule (PI-15a" in out
    assert "acknowledged by the Bank of England (known issues log #22" in out
