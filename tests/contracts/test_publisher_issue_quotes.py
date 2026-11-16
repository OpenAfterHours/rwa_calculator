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
``pdf_page_end``. A quote with an ellipsis must have its parts in order.

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


def test_quotes_to_check_were_found() -> None:
    """The parametrisation is not empty: a register with no quote would check nothing."""
    assert QUOTES


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
