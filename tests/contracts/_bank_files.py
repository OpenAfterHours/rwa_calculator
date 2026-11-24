"""
The Bank of England's between-release files, as the contract tests read them.

Pipeline position:
    (no pipeline stage — shared by the contract tests that read the Bank's
    validations deny list or its banking known-issues log from ``docs/assets``)

The Bank publishes both files between taxonomy releases, and both change
monthly. They are git-ignored, so a fresh clone holds neither:
``scripts/check_bank_publications.py`` fetches the current ones and
``scripts/download_docs.py`` the ones the manifest names. A test reads the
NEWEST of each, by the month and year that end the Bank's file name, the way
``scripts/build_filer_release.py --deny-list`` does: a file name typed into a
test keeps checking one month's log after a newer one is downloaded, which is
how ``test_publisher_issue_quotes.py`` read only the November 2026 log.

A test that needs a file skips without it, except where ``RWA_BANK_FILES_REQUIRED``
is set. The scheduled Bank Publications workflow sets it: that job downloads the
files first, so a skip there would be a failed download reported as a pass.

References:
- scripts/build_filer_release.py — ``newest_bank_file``, the one dating rule
- .github/workflows/bank-publications.yml
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

import pytest
from scripts import build_filer_release

if TYPE_CHECKING:
    from pathlib import Path

#: Set (to anything) where a missing file must fail a test rather than skip it.
REQUIRED_ENV = "RWA_BANK_FILES_REQUIRED"
#: The known-issues log's sheet for the banking taxonomy (the AS and FV sheets
#: are the statistics taxonomy's).
KNOWN_ISSUES_SHEET = "Known Issues"


def newest_bank_file(pattern: str) -> Path:
    """The newest of the Bank's files matching ``pattern`` in ``docs/assets``.

    Skips when there is none, or fails where ``RWA_BANK_FILES_REQUIRED`` is set.
    A file the pattern matches whose name cannot be dated raises
    ``UndatedBankFileError``: it may be the newest, so it is never skipped over.
    """
    path = build_filer_release.newest_bank_file(pattern, build_filer_release.ASSETS)
    if path is not None:
        return path
    message = (
        f"no {pattern} in docs/assets (git-ignored): "
        "run scripts/check_bank_publications.py to fetch the Bank's current files"
    )
    if os.environ.get(REQUIRED_ENV):
        pytest.fail(f"{message} - {REQUIRED_ENV} is set, so a missing file is a failure")
    pytest.skip(message)


def newest_known_issues_log() -> Path:
    """The newest banking known-issues log in ``docs/assets`` (see ``newest_bank_file``)."""
    return newest_bank_file(build_filer_release.KNOWN_ISSUES_PATTERN)


@cache
def known_issues_rows(path: Path) -> dict[int, dict[str, str]]:
    """The log's 'Known Issues' sheet: each entry's cells by column header, by entry number."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook[KNOWN_ISSUES_SHEET].iter_rows(values_only=True))
    finally:
        workbook.close()
    header: tuple[object, ...] | None = None
    found: dict[int, dict[str, str]] = {}
    for row in rows:
        if row and row[0] == "#":
            header = row
            continue
        if header is not None and row and isinstance(row[0], int | float):
            found[int(row[0])] = {
                str(name): "" if value is None else str(value)
                for name, value in zip(header, row, strict=False)
                if name is not None
            }
    return found
