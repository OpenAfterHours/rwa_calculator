"""
The Bank's current deny list and known-issues log reach a gate: the fetch, the check, the job.

Pipeline position:
    (no pipeline stage — contract tests on ``scripts/check_bank_publications.py``,
    the ``--deny-list --check`` mode of ``scripts/build_filer_release.py``, and
    ``.github/workflows/bank-publications.yml``)

The Bank publishes its validations deny list and its known-issues log between
taxonomy releases, monthly, and both override the taxonomy. Until P5.77 the
check that rwa-filer's packaged list is the Bank's ran only after someone
downloaded a newer workbook by hand, so a list published next month reached no
gate (escape log, 2026-11-16). What is held here, none of it needing the network
or the Bank's files:

- the check fails on a newer list than the one packaged, passes on the one it
  imported, and fails closed on a file it cannot date - a ``-v2`` suffix would
  otherwise leave the older file checked green;
- the fetch finds each file by the name the Bank's page gives it, fails closed on
  none, two, or a name the check cannot date, and checks every shipped release;
- the workflow runs both on a schedule and on demand, and runs the known-issues
  accounting with the files required.

References:
- docs/development/escape-log.md — 2026-11-16, the deny-list entry
- tests/contracts/test_known_issues_dispositions.py — the accounting the job runs
- IMPLEMENTATION_PLAN.md P5.77
"""

from __future__ import annotations

import logging
import re
import urllib.error
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from scripts import build_filer_release, check_bank_publications
from tests.contracts._bank_files import REQUIRED_ENV, newest_bank_file
from tests.contracts._ci_workflow import REPO_ROOT, run_commands, without_comments

from rwa_filer.release import shipped_releases

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "bank-publications.yml"
RELEASE = shipped_releases()[0]
DENY = "boe-banking-validations-deny-list"
ISSUES = "boe-banking-known-issues"
FOLDER = "/-/media/boe/files/prudential-regulation/regulatory-reporting/banking/"


@pytest.fixture(autouse=True)
def _restore_package_logging() -> Iterator[None]:
    """``build_filer_release.main`` points rwa-filer's logger at stdout; undo it after each test."""
    package_logger = logging.getLogger("rwa_filer")
    handlers, level = list(package_logger.handlers), package_logger.level
    yield
    package_logger.handlers[:] = handlers
    package_logger.setLevel(level)


@pytest.fixture
def bank_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty stand-in for ``docs/assets``, and a scratch target for the packaged list."""
    folder = tmp_path / "bank"
    folder.mkdir()
    monkeypatch.setattr(build_filer_release, "ASSETS", folder)
    monkeypatch.setattr(build_filer_release, "DENY_LISTS", {RELEASE: tmp_path / "deny.json"})
    return folder


# ---------------------------------------------------------------------------
# build_filer_release.py --deny-list --check
# ---------------------------------------------------------------------------


def test_the_check_passes_on_the_list_it_imported(
    bank_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    _deny_workbook(bank_folder / f"{DENY}-november-2026.xlsx", [_ROW_B0710])
    _issues_workbook(bank_folder / f"{ISSUES}-november-2026.xlsx")
    assert build_filer_release.main([RELEASE, "--deny-list"]) == 0
    capsys.readouterr()

    # Act
    status = build_filer_release.main([RELEASE, "--deny-list", "--check"])

    # Assert
    assert status == 0
    assert "[OK]" in capsys.readouterr().out


def test_the_check_fails_on_a_newer_list_than_the_one_packaged(
    bank_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The red the escape log's OPEN limb waited for: the Bank publishes, the check sees it."""
    # Arrange
    _deny_workbook(bank_folder / f"{DENY}-november-2026.xlsx", [_ROW_B0710])
    _issues_workbook(bank_folder / f"{ISSUES}-november-2026.xlsx")
    assert build_filer_release.main([RELEASE, "--deny-list"]) == 0
    _deny_workbook(bank_folder / f"{DENY}-december-2026.xlsx", [_ROW_B0710, _ROW_B1041])
    capsys.readouterr()

    # Act
    status = build_filer_release.main([RELEASE, "--deny-list", "--check"])

    # Assert
    out = capsys.readouterr().out
    diff = _diff_line(out)
    assert status == 1
    assert f"Deny list {DENY}-december-2026.xlsx" in out
    assert diff.startswith(f"[DIFF] {build_filer_release.DENY_LISTS[RELEASE]} is out of date")
    assert f"{DENY}-december-2026.xlsx" in diff and ISSUES not in diff, diff


def test_a_newer_known_issues_log_alone_fails_the_check_and_the_diff_names_the_log(
    bank_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The packaged list records the log it was joined to, so a new log alone is a DIFF.

    The line names the file that moved. It used to name the deny-list workbook
    whichever moved, which sent the reader of a red run to the wrong file.
    """
    # Arrange
    _deny_workbook(bank_folder / f"{DENY}-november-2026.xlsx", [_ROW_B0710])
    _issues_workbook(bank_folder / f"{ISSUES}-november-2026.xlsx")
    assert build_filer_release.main([RELEASE, "--deny-list"]) == 0
    _issues_workbook(bank_folder / f"{ISSUES}-december-2026.xlsx", updated=datetime(2026, 12, 14))
    capsys.readouterr()

    # Act
    status = build_filer_release.main([RELEASE, "--deny-list", "--check"])

    # Assert
    diff = _diff_line(capsys.readouterr().out)
    assert status == 1
    assert f"{ISSUES}-december-2026.xlsx" in diff and DENY not in diff, diff


def test_a_bank_file_the_check_cannot_date_fails_it_rather_than_being_skipped(
    bank_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-december-2026-v2.xlsx`` used to be ignored and the November list checked green."""
    # Arrange
    _deny_workbook(bank_folder / f"{DENY}-november-2026.xlsx", [_ROW_B0710])
    _issues_workbook(bank_folder / f"{ISSUES}-november-2026.xlsx")
    assert build_filer_release.main([RELEASE, "--deny-list"]) == 0
    _deny_workbook(bank_folder / f"{DENY}-december-2026-v2.xlsx", [_ROW_B0710, _ROW_B1041])
    capsys.readouterr()

    # Act
    status = build_filer_release.main([RELEASE, "--deny-list", "--check"])

    # Assert
    assert status == 1
    assert f"cannot date {DENY}-december-2026-v2.xlsx" in capsys.readouterr().err


def test_the_newest_file_is_read_by_the_month_and_year_its_name_ends_with(
    bank_folder: Path,
) -> None:
    # Arrange - alphabetical order would pick march; the newest is august 2026.
    for name in ("december-2025", "march-2026", "august-2026"):
        (bank_folder / f"{ISSUES}-{name}.xlsx").write_bytes(b"")

    # Act
    newest = build_filer_release.newest_bank_file(
        build_filer_release.KNOWN_ISSUES_PATTERN, bank_folder
    )

    # Assert
    assert newest == bank_folder / f"{ISSUES}-august-2026.xlsx"


@pytest.mark.parametrize("release", shipped_releases())
def test_each_packaged_deny_list_is_what_the_banks_newest_files_yield(
    release: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Local, and in the Bank Publications job: red as soon as a newer list is downloaded."""
    # Arrange
    newest_bank_file(build_filer_release.DENY_LIST_PATTERN)

    # Act
    status = build_filer_release.main([release, "--deny-list", "--check"])

    # Assert
    assert status == 0, capsys.readouterr().out


# ---------------------------------------------------------------------------
# check_bank_publications.py — finding the Bank's current files
# ---------------------------------------------------------------------------


def test_the_current_files_are_found_by_the_names_the_banks_page_gives_them() -> None:
    # Arrange
    page = _page(f"{FOLDER}{DENY}-december-2026.xlsx", f"{FOLDER}{ISSUES}-december-2026.xlsx")

    # Act
    found = check_bank_publications.discover_publications(page)

    # Assert
    assert found == {
        "deny_list": f"{DENY}-december-2026.xlsx",
        "known_issues": f"{ISSUES}-december-2026.xlsx",
    }


def test_a_link_on_the_banks_host_with_a_query_and_a_repeated_link_are_one_file() -> None:
    # Arrange
    host = "https://www.bankofengland.co.uk"
    page = _page(
        f"{host}{FOLDER}{DENY}-january-2027.xlsx?la=en&amp;hash=AB12",
        f"{FOLDER}{DENY}-january-2027.xlsx",
        f"{FOLDER}{ISSUES}-january-2027.xlsx",
    )

    # Act
    found = check_bank_publications.discover_publications(page)

    # Assert
    assert found["deny_list"] == f"{DENY}-january-2027.xlsx"


@pytest.mark.parametrize(
    ("links", "message"),
    [
        ([f"{FOLDER}{ISSUES}-december-2026.xlsx"], f"links no {DENY}"),
        (
            [
                f"{FOLDER}{DENY}-november-2026.xlsx",
                f"{FOLDER}{DENY}-december-2026.xlsx",
                f"{FOLDER}{ISSUES}-december-2026.xlsx",
            ],
            f"links 2 files named {DENY}",
        ),
        (
            [f"{FOLDER}{DENY}-december-2026-v2.xlsx", f"{FOLDER}{ISSUES}-december-2026.xlsx"],
            f"cannot date {DENY}-december-2026-v2.xlsx",
        ),
        (
            [
                f"https://example.com{FOLDER}{DENY}-december-2026.xlsx",
                f"{FOLDER}{ISSUES}-december-2026.xlsx",
            ],
            "is not in the Bank's banking reporting folder",
        ),
    ],
    ids=["none", "two", "undated", "elsewhere"],
)
def test_the_fetch_fails_closed_where_it_cannot_tell_which_file_is_current(
    links: list[str], message: str
) -> None:
    # Arrange
    page = _page(*links)

    # Act / Assert
    with pytest.raises(check_bank_publications.PublicationError, match=re.escape(message)):
        check_bank_publications.discover_publications(page)


# ---------------------------------------------------------------------------
# check_bank_publications.py — the job
# ---------------------------------------------------------------------------


def test_the_job_fetches_both_files_and_checks_every_shipped_release(
    bank_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange - two releases, or "every release" could not be told from "the first".
    fetched = _serve(monkeypatch, "december-2026")
    checked = _record_checks(monkeypatch, status=0)
    monkeypatch.setattr(check_bank_publications, "shipped_releases", lambda: ("4.2.0", "4.1.1"))

    # Act
    status = check_bank_publications.main([])

    # Assert
    assert status == 0
    assert fetched == [
        check_bank_publications.BOE_BANKS_REPORTING_LANDING,
        f"{build_filer_release.BANK_FILES_URL}{DENY}-december-2026.xlsx",
        f"{build_filer_release.BANK_FILES_URL}{ISSUES}-december-2026.xlsx",
    ]
    assert (bank_folder / f"{DENY}-december-2026.xlsx").read_bytes() == b"deny list bytes"
    assert (bank_folder / f"{ISSUES}-december-2026.xlsx").read_bytes() == b"known issues bytes"
    assert checked == [
        ["4.2.0", "--deny-list", "--check"],
        ["4.1.1", "--deny-list", "--check"],
    ]


def test_a_packaged_list_out_of_date_fails_the_job(
    bank_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _serve(monkeypatch, "december-2026")
    _record_checks(monkeypatch, status=1)

    # Act
    status = check_bank_publications.main([])

    # Assert
    assert status == 1


def test_a_newer_file_in_docs_assets_than_the_bank_lists_fails_the_job(
    bank_folder: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check reads the newest file there; it must be the one the Bank lists now."""
    # Arrange
    (bank_folder / f"{DENY}-january-2027.xlsx").write_bytes(b"")
    _serve(monkeypatch, "december-2026")
    checked = _record_checks(monkeypatch, status=0)

    # Act
    status = check_bank_publications.main([])

    # Assert
    assert status == 1
    assert checked == []
    assert f"would check {DENY}-january-2027.xlsx" in capsys.readouterr().err


def test_an_unreachable_page_fails_the_job(
    bank_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    def refuse(url: str) -> bytes:
        raise urllib.error.URLError(f"refused: {url}")

    monkeypatch.setattr(check_bank_publications, "_fetch", refuse)
    checked = _record_checks(monkeypatch, status=0)

    # Act
    status = check_bank_publications.main([])

    # Assert
    assert status == 1
    assert checked == []


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------


def test_the_workflow_runs_on_a_schedule_and_on_demand() -> None:
    # Arrange
    assert WORKFLOW_PATH.exists(), f"no workflow at {WORKFLOW_PATH}"

    # Act
    live = without_comments(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # Assert
    assert re.search(r"^  schedule:\n    - cron: '\d+ \d+ \* \* \S+'$", live, re.MULTILINE)
    assert re.search(r"^  workflow_dispatch:", live, re.MULTILINE)


def test_the_workflow_fetches_and_checks_then_runs_the_accounting_with_the_files_required() -> None:
    """Read structurally: a commented-out command, or a step that cannot fail, does not count."""
    # Arrange
    live = without_comments(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # Act
    commands = run_commands(live)
    fetch = _index(commands, r"^uv run python scripts/check_bank_publications\.py$")
    accounting = _index(
        commands, r"^uv run pytest tests/contracts/test_known_issues_dispositions\.py\b"
    )

    # Assert
    assert fetch is not None, commands
    assert accounting is not None and accounting > fetch, commands
    assert f'{REQUIRED_ENV}: "1"' in live, "a missing file would skip the accounting green"
    assert "continue-on-error" not in live
    conditions = re.findall(r"^[ \t]*(?:-[ \t]+)?if:[ \t]*(.*)$", live, re.MULTILINE)
    assert conditions == ["${{ !cancelled() }}"], conditions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROW_B0710 = ("boe_b0710", datetime(2026, 10, 19), "Deactivated", "PRA001")
_ROW_B1041 = ("boe_b1041", datetime(2026, 12, 1), "Deactivated", "PRA001")


def _deny_workbook(path: Path, rows: list[tuple[object, ...]]) -> None:
    """A deny list laid out as the Bank's is: a Note sheet, then one sheet per release."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.active.title = "Note"
    sheet = workbook.create_sheet(f"Version {RELEASE} ")
    sheet.append(["Validation Code", "Date Applied", "Deny Type", "Module"])
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)


def _issues_workbook(path: Path, *, updated: datetime = datetime(2026, 11, 16)) -> None:
    """A known-issues log with the one entry the deny rows name."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Known Issues"
    sheet.append(["Last updated:", None, updated])
    sheet.append([])
    sheet.append(["#", "Affected version", "Entry point", "Affected artefact", "Issue title"])
    sheet.append([22, RELEASE, "PRA001", "Validation rules", "validation rules\nboe_b0710"])
    workbook.save(path)


def _diff_line(out: str) -> str:
    """The check's one ``[DIFF]`` line, stripped."""
    lines = [line.strip() for line in out.splitlines() if "[DIFF]" in line]
    assert len(lines) == 1, out
    return lines[0]


def _page(*links: str) -> str:
    anchors = "".join(f'<li><a href="{link}">a file</a></li>' for link in links)
    return f'<html><body><a href="/about">About</a><ul>{anchors}</ul></body></html>'


def _serve(monkeypatch: pytest.MonkeyPatch, dated: str) -> list[str]:
    """Stand in for the Bank's site: the page lists both files ``dated``; record each fetch."""
    fetched: list[str] = []
    files = {
        f"{build_filer_release.BANK_FILES_URL}{DENY}-{dated}.xlsx": b"deny list bytes",
        f"{build_filer_release.BANK_FILES_URL}{ISSUES}-{dated}.xlsx": b"known issues bytes",
        check_bank_publications.BOE_BANKS_REPORTING_LANDING: _page(
            f"{FOLDER}{DENY}-{dated}.xlsx", f"{FOLDER}{ISSUES}-{dated}.xlsx"
        ).encode(),
    }

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return files[url]

    monkeypatch.setattr(check_bank_publications, "_fetch", fetch)
    return fetched


def _record_checks(monkeypatch: pytest.MonkeyPatch, *, status: int) -> list[list[str]]:
    """Stand in for ``build_filer_release.main``: record each argv, answer ``status``."""
    checked: list[list[str]] = []

    def check(argv: list[str] | None = None) -> int:
        checked.append(list(argv or []))
        return status

    monkeypatch.setattr(build_filer_release, "main", check)
    return checked


def _index(commands: list[str], pattern: str) -> int | None:
    return next(
        (index for index, command in enumerate(commands) if re.search(pattern, command)), None
    )
