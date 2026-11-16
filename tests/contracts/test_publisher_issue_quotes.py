"""
Every quote in rwa-filer's publisher-issue registers is on the page it names.

Pipeline position:
    packages/rwa-filer/src/rwa_filer/boe/data/issues/<release>.json (authority quotes)
        ->  docs/rwa-filer/publisher-issues.md, the write-up shared with the Bank

The write-up quotes the reporting instructions and the PRA Rulebook to the Bank
that publishes them, so a paraphrase presented as a quote, or a quote on the
wrong page, is the error a reader at the Bank is best placed to catch. This
reads each quoted PDF with pymupdf (``.claude/LESSONS.md`` A2) and requires
every quote, whitespace- and typography-normalised, on its ``pdf_page`` — or,
for one that runs over a page break, starting on ``pdf_page`` and ending on
``pdf_page_end``. A quote with an ellipsis must have its parts in order. Every
entry of the Bank's known-issues log an issue quotes is checked against the
log itself (its 'Issue description', 'Solution' and publication date).

The PDFs are git-ignored (``docs/assets``), so each document's quotes skip when
its PDF is absent: this is a local and pre-share gate, not a CI one.

References:
- rwa_filer.boe.issues — the register and its ``Authority`` entries
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path

import pytest

from rwa_filer.boe.issues import load_issues
from rwa_filer.release import shipped_releases

ASSETS = Path(__file__).resolve().parents[2] / "docs" / "assets"

#: Typography a PDF's text layer and a typed quote spell differently.
_SAME = {
    "‘": "'",
    "’": "'",
    "‛": "'",
    "´": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "‟": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "•": " ",
    "": " ",
}
_ELLIPSIS = re.compile(r"\s*(?:\[\.\.\.\]|\[…\]|\.\.\.|…)\s*")


def _quotes() -> list[tuple[str, str, str, int, int | None, str]]:
    found = []
    for version in shipped_releases():
        register = load_issues(version)
        for issue in register.issues:
            for item in issue.authority:
                document = register.documents[item.document]
                if item.pdf_page is None or document.file is None:
                    continue
                found.append(
                    (
                        version,
                        issue.id,
                        document.file,
                        item.pdf_page,
                        item.pdf_page_end,
                        item.quote,
                    )
                )
    return found


QUOTES = _quotes()


@pytest.mark.parametrize(
    ("version", "issue_id", "file", "page", "page_end", "quote"),
    QUOTES,
    ids=[f"{issue}-{file}-p{page}" for _v, issue, file, page, _e, _q in QUOTES],
)
def test_each_quote_is_on_the_page_it_names(  # noqa: PLR0913 - one parameter per quote field
    version: str, issue_id: str, file: str, page: int, page_end: int | None, quote: str
) -> None:
    # Arrange
    path = ASSETS / file
    if not path.is_file():
        pytest.skip(f"{file} is not in docs/assets (git-ignored): run scripts/download_docs.py")
    pages = _pages(path)

    # Act
    if page_end is None:
        placed = _on(pages[page - 1], quote)
    else:
        placed = _spans(pages[page - 1], pages[page_end - 1], quote)

    # Assert
    assert placed, f"{version} {issue_id}: not on page {page} of {file}: {quote[:120]!r}"


def _log_entries() -> list[tuple[str, str, int, str, str]]:
    found = []
    for version in shipped_releases():
        for issue in load_issues(version).issues:
            for entry in issue.publisher_log:
                found.append(
                    (version, issue.id, entry.entry, entry.published.isoformat(), entry.statement)
                )
    return found


LOG_ENTRIES = _log_entries()
KNOWN_ISSUES_LOG = "boe-banking-known-issues-november-2026.xlsx"


@pytest.mark.parametrize(
    ("version", "issue_id", "entry", "published", "statement"),
    LOG_ENTRIES,
    ids=[f"{issue}-log{entry}" for _v, issue, entry, _p, _s in LOG_ENTRIES],
)
def test_each_known_issues_log_entry_is_quoted_verbatim(  # noqa: PLR0913 - one per entry field
    version: str, issue_id: str, entry: int, published: str, statement: str
) -> None:
    """What the write-up says the Bank's log says is what the log says (whitespace normalised).

    An acknowledged issue rests on the Bank's own words, so the 'Issue description'
    and 'Solution' it quotes, and the publication date, are checked against the
    log's cells - the workbook is git-ignored, so this skips without it.
    """
    # Arrange
    path = ASSETS / KNOWN_ISSUES_LOG
    if not path.is_file():
        pytest.skip(f"{KNOWN_ISSUES_LOG} is not in docs/assets (git-ignored)")
    log = _known_issues(path)

    # Act
    row = log.get(entry)

    # Assert
    assert row is not None, f"{version} {issue_id}: the log has no entry {entry}"
    expected = f"Issue description: {row['Issue description']}\n\nSolution: {row['Solution']}"
    assert _normalised(statement) == _normalised(expected)
    day, month, year = row["Publication date of the issue"].split(".")
    assert published == f"{year}-{month}-{day}"


def test_quotes_to_check_were_found() -> None:
    """The parametrisation is not empty: a register with no quote would check nothing."""
    assert QUOTES


@cache
def _known_issues(path: Path) -> dict[int, dict[str, str]]:
    """The log's 'Known Issues' sheet: each entry's cells, by number."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    header: tuple[object, ...] | None = None
    found: dict[int, dict[str, str]] = {}
    for row in workbook["Known Issues"].iter_rows(values_only=True):
        if row and row[0] == "#":
            header = row
            continue
        if header is not None and isinstance(row[0], int | float):
            found[int(row[0])] = {
                str(name): "" if value is None else str(value)
                for name, value in zip(header, row, strict=False)
                if name is not None
            }
    return found


@cache
def _pages(path: Path) -> tuple[str, ...]:
    fitz = pytest.importorskip("fitz")
    with fitz.open(str(path)) as document:
        return tuple(_normalised(page.get_text()) for page in document)


def _normalised(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(_SAME.get(character, character) for character in text)
    text = re.sub(r"-\s*\n\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _on(text: str, quote: str) -> bool:
    """Every part of the quote (split at an ellipsis) is in ``text``, in order."""
    position = 0
    for part in (item for item in _ELLIPSIS.split(_normalised(quote)) if item):
        found = text.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def _spans(first: str, second: str, quote: str) -> bool:
    """The quote starts on ``first`` and ends on ``second``, split between two words."""
    words = _normalised(quote).split(" ")
    return any(
        _on(first, " ".join(words[:cut])) and _on(second, " ".join(words[cut:]))
        for cut in range(len(words) - 1, 0, -1)
    )
