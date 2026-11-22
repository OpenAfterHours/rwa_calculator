"""
Contract and behaviour tests for the regulation-text skill's script.

Pipeline position:
    Outside the calculation pipeline: guards ``scripts/regulation_text.py`` and
    the committed article index under ``.claude/skills/regulation-text/index/``.

Key responsibilities:
- The committed index is exactly what the generator renders from today's
  ``@cites`` decorators, rulepack citations and watchfire snapshot, so a new
  citation cannot land without its index row.
- Every code citation resolves to an index row.
- ``show`` degrades cleanly: official text when the PDF is converted, the
  labelled snapshot when it is not, and the index entry alone when neither is
  available; a failed download is not retried on every lookup.
- The PDF splitter cuts articles at "Article N" lines and keeps page numbers.

References:
- .claude/skills/regulation-text/SKILL.md
- .claude/LESSONS.md A2, A3

Citation strings below are built with ``_ps`` / ``_crr`` on purpose: the
confidence matrix scans ``tests/`` for written-out citations, and these tests
exercise the parser, not an article's implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import regulation_text as rt

if TYPE_CHECKING:
    from pathlib import Path


def _ps(reference: str) -> str:
    return "PS1/26, paragraph " + reference


def _crr(reference: str) -> str:
    return "CRR Art. " + reference


# =============================================================================
# The committed index
# =============================================================================


def test_committed_index_matches_the_generator() -> None:
    """The index CSVs are regenerated, never hand-edited, and must be fresh."""
    # Arrange
    rendered = rt.render_index()

    # Act
    stale = [
        name
        for name, text in rendered.items()
        if (rt.INDEX_DIR / name).read_text(encoding="utf-8") != text
    ]

    # Assert
    assert not stale, (
        f"regulation-text index is stale: {stale}. "
        "Regenerate: uv run python scripts/regulation_text.py index"
    )


def test_every_code_citation_has_an_index_row() -> None:
    """Each @cites decorator and pack citation maps to a row of the committed index."""
    # Arrange
    rows = {
        "b31": {row["article"] for row in rt.load_index("b31")},
        "crr": {row["article"] for row in rt.load_index("crr")},
        "other": {row["reference"] for row in _read_other()},
    }
    citations = [c for c, _ in rt._iter_cites_sites()] + [c for c, _ in rt._iter_pack_citations()]

    # Act
    missing = sorted(
        {
            f"{key[0]}:{key[1]} ({citation})"
            for citation in citations
            if (key := rt.classify_citation(citation)) is not None and key[1] not in rows[key[0]]
        }
    )

    # Assert
    assert citations, "found no citations at all: the AST walk or pack resolve is broken"
    assert not missing, f"citations with no index row: {missing}"


def test_corrections_file_has_its_header() -> None:
    """corrections.csv is hand-kept, so its columns are pinned here."""
    header = (rt.INDEX_DIR / rt.CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == list(rt.CORRECTION_COLUMNS)


def test_index_carries_the_renumbering_notes() -> None:
    """The b31 index records CRR correspondence and note markers from the snapshot."""
    rows = rt.load_index("b31")
    assert sum(1 for row in rows if row["crr_article"]) > 100
    assert any(row["left_blank"] for row in rows)
    assert any(row["not_in_rulebook"] for row in rows)


# =============================================================================
# Reference parsing and citation classification
# =============================================================================


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("PS1/26 124F", rt.ArticleRef("b31", "124F")),
        ("ps1/26, paragraph 124F", rt.ArticleRef("b31", "124F")),
        ("B31 153(1)(a)", rt.ArticleRef("b31", "153", "(1)(a)")),
        ("153", rt.ArticleRef("b31", "153")),
        ("CRR 501a", rt.ArticleRef("crr", "501a")),
        ("CRR Article 92(3)", rt.ArticleRef("crr", "92", "(3)")),
    ],
)
def test_parse_reference_reads_loose_forms(ref: str, expected: rt.ArticleRef) -> None:
    assert rt.parse_reference(ref) == expected


def test_parse_reference_rejects_text_without_an_article() -> None:
    assert rt.parse_reference("real estate") is None


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        (_ps("124F"), ("b31", "124F", "")),
        (_ps("123B.3"), ("b31", "123B", "(3)")),
        (_ps("4.1"), ("other", _ps("4.1"), "")),
        (_crr("153(1)"), ("crr", "153", "(1)")),
        ("SS1/23, paragraph 2.5", ("other", "SS1/23, paragraph 2.5", "")),
    ],
)
def test_classify_citation_routes_each_form(citation: str, expected: tuple[str, str, str]) -> None:
    assert rt.classify_citation(citation) == expected


# =============================================================================
# The PDF splitter
# =============================================================================


def test_split_articles_cuts_at_article_lines_and_keeps_pages() -> None:
    # Arrange: inline headings ("Article N HEADING"), an article spanning two pages
    pages = [
        "Article 9001 FIRST THING\n1. Text of the first.\nArticle 9002 SECOND THING\n1. Starts",
        "here and carries on.\n2. More.\nArticle 9003 THIRD\nBody.",
    ]

    # Act
    articles = rt.split_articles(pages)

    # Assert
    assert sorted(articles) == ["9001", "9002", "9003"]
    assert articles["9002"]["start_page"] == 1
    assert articles["9002"]["end_page"] == 2
    assert "carries on" in str(articles["9002"]["text"])
    assert "SECOND" not in str(articles["9001"]["text"])


def test_split_articles_prefers_the_longest_span_over_a_contents_entry() -> None:
    # Arrange: a contents page names the article before its body appears
    pages = [
        "Contents\nArticle 9001 FIRST\nArticle 9002 SECOND\n",
        "Article 9001 FIRST\n1. The real body of the first article, which is longer.\n"
        "Article 9002 SECOND\n1. The real body of the second.\n",
    ]

    # Act
    articles = rt.split_articles(pages)

    # Assert
    assert articles["9001"]["start_page"] == 2
    assert "real body" in str(articles["9001"]["text"])


def test_split_articles_uses_only_bare_heading_lines_when_the_document_has_them() -> None:
    # Arrange: bare "Article N" lines, and a body line that starts "Article 9002 applies"
    body = "".join(f"Article {n}\nHEADING {n}\nText.\n" for n in range(9100, 9100 + 25))
    pages = [body + "Article 9001\nHEADING\nArticle 9002 applies to this case.\nMore text.\n"]

    # Act
    articles = rt.split_articles(pages)

    # Assert
    assert "9002" not in articles
    assert "applies to this case" in str(articles["9001"]["text"])


# =============================================================================
# show: official text, snapshot fallback, index only
# =============================================================================


def test_show_prints_official_text_from_a_converted_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: a two-page PDF standing in for ps126app1.pdf
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "ps126app1.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Article 124F TEST HEADING\n1. Page one text.")
        doc.new_page().insert_text(
            (72, 72), "2. Page two text.\n[Note: Provision left blank]\nArticle 124G NEXT\nBody."
        )
        doc.save(pdf)
    monkeypatch.setattr(rt, "find_document", lambda filename: pdf)
    monkeypatch.setenv(rt.CACHE_ENV, str(tmp_path / "cache"))

    # Act
    output = rt.command_show("PS1/26 124F", offline=True)

    # Assert
    assert "official text, ps126app1.pdf page 1-2" in output
    assert "Page two text." in output
    assert "Notes in this article: [Note: Provision left blank]" in output
    assert "NEXT" not in output.split("official text", 1)[1]


def test_show_falls_back_to_the_labelled_snapshot_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(rt, "find_document", lambda filename: None)
    monkeypatch.setenv(rt.CACHE_ENV, str(tmp_path))

    # Act
    output = rt.command_show("PS1/26 124F", offline=True)

    # Assert
    assert output.startswith("PS1/26 Article 124F")
    assert "watchfire's bundled snapshot" in output
    assert "fetching is off" in output


def test_show_gives_the_index_entry_alone_when_no_text_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: an article the snapshot lacks, with no PDF
    row = next(r for r in rt.load_index("b31") if r["in_snapshot"] == "no")
    monkeypatch.setattr(rt, "find_document", lambda filename: None)
    monkeypatch.setenv(rt.CACHE_ENV, str(tmp_path))

    # Act
    output = rt.command_show(f"PS1/26 {row['article']}", offline=True)

    # Assert
    assert "Code (@cites)" in output
    assert "Never reconstruct it from memory" in output


def test_a_failed_download_is_not_retried_on_every_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    calls: list[str] = []

    def blocked(filename: str) -> tuple[None, str]:
        calls.append(filename)
        return None, "host blocked"

    monkeypatch.setattr(rt, "find_document", lambda filename: None)
    monkeypatch.setattr(rt, "download_document", blocked)
    monkeypatch.setenv(rt.CACHE_ENV, str(tmp_path))

    # Act
    first = rt.command_show("PS1/26 124F")
    second = rt.command_show("PS1/26 124F")

    # Assert
    assert calls == ["ps126app1.pdf"]
    assert "host blocked" in first
    assert "run 'fetch' to retry now" in second


def test_show_warns_on_a_recorded_correction(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    correction = {"regime": "b31", "article": "124F", "instrument": "TEST", "summary": "x"}
    monkeypatch.setattr(rt, "load_corrections", lambda: [correction])

    # Act
    output = rt.command_show("PS1/26 124F", source="none")

    # Assert
    assert "WARNING: amended by TEST after the PDF: x" in output


def _read_other() -> list[dict[str, str]]:
    import csv

    with (rt.INDEX_DIR / "other.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
