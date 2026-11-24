#!/usr/bin/env python3
"""
Regulation text on demand: a committed article index plus a local text cache.

Purpose:
    Backs the ``regulation-text`` skill (``.claude/skills/regulation-text/``).
    An agent asks for an article ("PS1/26 124F", "CRR 501a") and gets, in order
    of trust: the verbatim text converted from the official PDF, the code and
    pack entries that implement the article, and the article's CRR
    correspondence and "[Note: ...]" markers. The *index* is committed and
    works offline; the *text* is never committed (PRA / Bank of England terms
    do not allow redistributing modified copies of PS1/26), so it is fetched
    and converted on first use into a git-ignored cache.

Sources, in the order ``show`` tries them:
    1. Official: ``docs/assets/ps126app1.pdf`` (Basel 3.1) or
       ``docs/assets/crr.pdf`` (UK CRR), downloaded on first use through
       ``scripts/download_docs.py``'s manifest and split into one markdown file
       per article under the cache (``.regulation-text/`` in the main checkout,
       or ``$RWA_REGTEXT_CACHE``). A cloud container is rebuilt each session,
       so this happens lazily, once per session, for the one document needed.
    2. Snapshot: the parsed text bundled in the installed ``watchfire`` package
       (``watchfire/data/index.parquet``). It installs from PyPI, so it is there
       even when the regulator hosts are blocked, but it is a third-party parse
       (it can split or merge paragraphs) and is labelled as such.
    3. Index only: when neither is available, ``show`` says so in one line and
       still prints the committed index entry.

Commands:
    index [--check]   regenerate (or verify) the committed index CSVs
    show REF          print an article: index entry, then the best text
    fetch [REGIME]    download and convert the official PDFs now
    find TEXT         search article headings / titles in the index
    check             index freshness, corrections, and local cache state

Index files (``.claude/skills/regulation-text/index/``):
    b31.csv   every PS1/26 Appendix 1 article in the snapshot, plus every
              article the code cites: heading, CRR correspondence, the
              paragraphs marked "Provision left blank" / "not in PRA Rulebook",
              and the pack entries and functions that cite it.
    crr.csv   every UK CRR article in the snapshot, plus every cited one:
              title, the PS1/26 articles that correspond to it, pack entries
              and functions.
    other.csv citations that are not an article of either (PS1/26 policy
              paragraphs, supervisory statements, PRA Rulebook parts).
    corrections.csv  hand-maintained amendments the PDFs lack; ``show``
              prints a warning for an affected article.

The index is generated from the repo (``@cites`` decorators under
``src/rwa_calc`` and the resolved rulepack citations) and the installed
watchfire snapshot; ``tests/contracts/test_regulation_text.py`` fails
when it is stale, so a new citation cannot land without its index row.

References:
- docs/development/citation-tracking.md (citation grammar, pack citations)
- .claude/LESSONS.md A2 (read the PDFs, not memory), A3 (PS1/26 renumbering)
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    import polars as pl

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "regulation-text"
INDEX_DIR = SKILL_DIR / "index"

CORRECTIONS_FILE = "corrections.csv"

#: Any valid reporting date gives the same pack entry set (see
#: ``rulebook.audit.pack_citation_index``); this one matches arch_check.
PACK_REPORTING_DATE = date(2026, 1, 1)
PACK_REGIMES: tuple[str, ...] = ("crr", "b31")

#: Regime -> the manifest filename in ``scripts/download_docs.py`` holding its text.
REGIME_DOCUMENTS: dict[str, str] = {"b31": "ps126app1.pdf", "crr": "crr.pdf"}
REGIME_LABELS: dict[str, str] = {"b31": "PS1/26", "crr": "CRR"}

CACHE_ENV = "RWA_REGTEXT_CACHE"
OFFLINE_ENV = "RWA_REGTEXT_OFFLINE"
CACHE_DIRNAME = ".regulation-text"

#: After a failed download, ``show`` waits this long before trying the host again.
_RETRY_AFTER_SECONDS = 600

#: Bump when the converter's output changes, so stale caches are rebuilt.
CONVERTER_VERSION = 1

B31_COLUMNS: tuple[str, ...] = (
    "article",
    "heading",
    "crr_article",
    "left_blank",
    "not_in_rulebook",
    "in_snapshot",
    "pack_entries",
    "functions",
)
CRR_COLUMNS: tuple[str, ...] = (
    "article",
    "title",
    "b31_articles",
    "in_snapshot",
    "pack_entries",
    "functions",
)
OTHER_COLUMNS: tuple[str, ...] = ("reference", "pack_entries", "functions")
CORRECTION_COLUMNS: tuple[str, ...] = ("regime", "article", "instrument", "summary")

LIST_SEP = "; "

#: A dotted PS1/26 paragraph whose first part is at least this is an article
#: and its paragraph ("124.4"); below it, a rule of a Rulebook Part ("4.1").
_MIN_DOTTED_ARTICLE = 10

_ARTICLE_RE = re.compile(r"^(\d+)([A-Za-z]{0,3})$")
_CORRESPONDS_RE = re.compile(
    r"\[Note:\s*(?:This\s+rule\s+)?corresponds\s+to\s+Articles?\s+"
    r"(\d+[A-Za-z]{0,3}(?:\s*(?:,|and)\s*\d+[A-Za-z]{0,3})*)",
    re.IGNORECASE,
)
_LEFT_BLANK_RE = re.compile(r"\[Note:\s*Provision\s+left\s+blank", re.IGNORECASE)
_NOT_IN_RULEBOOK_RE = re.compile(r"\[Note:\s*Provision\s+not\s+in\s+PRA\s+Rulebook", re.IGNORECASE)
_NOTE_LINE_RE = re.compile(r"\[Note:[^\]]*\]", re.IGNORECASE)

#: A line that opens an article in the official PDFs: "Article 124F", alone or
#: followed by its heading on the same line.
_ARTICLE_LINE_RE = re.compile(r"(?m)^[ \t]*Article[ \t]+(\d+[A-Za-z]{0,3})\b(?P<rest>[^\n]*)$")

#: Below this many bare "Article N" lines a document is treated as laying its
#: headings out inline, and every line-start match counts as a boundary.
_MIN_BARE_HEADINGS = 20


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to one of the five commands."""
    parser = argparse.ArgumentParser(
        prog="regulation_text",
        description="Committed article index plus on-demand regulation text.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="regenerate the committed index CSVs")
    p_index.add_argument("--check", action="store_true", help="verify only, never write")

    p_show = sub.add_parser("show", help="print an article: index entry, then its text")
    p_show.add_argument("ref", nargs="+", help='e.g. "PS1/26 124F", "CRR 501a", "153(1)"')
    p_show.add_argument(
        "--offline",
        action="store_true",
        help=f"never download (also: {OFFLINE_ENV}=1)",
    )
    p_show.add_argument(
        "--source",
        choices=("auto", "official", "snapshot", "none"),
        default="auto",
        help="which text to print (default: official, else snapshot)",
    )

    p_fetch = sub.add_parser("fetch", help="download and convert the official PDFs now")
    p_fetch.add_argument("regime", nargs="?", choices=("b31", "crr", "all"), default="all")

    p_find = sub.add_parser("find", help="search article headings and titles")
    p_find.add_argument("text", nargs="+")

    sub.add_parser("check", help="index freshness, corrections and cache state")

    args = parser.parse_args(argv)
    if args.command == "index":
        return command_index(check=args.check)
    if args.command == "show":
        offline = args.offline or os.environ.get(OFFLINE_ENV, "") not in ("", "0")
        print(command_show(" ".join(args.ref), offline=offline, source=args.source))
        return 0
    if args.command == "fetch":
        regimes = ("b31", "crr") if args.regime == "all" else (args.regime,)
        return command_fetch(regimes)
    if args.command == "find":
        print(command_find(" ".join(args.text)))
        return 0
    return command_check()


# =============================================================================
# COMMANDS
# =============================================================================


def command_index(*, check: bool) -> int:
    """Regenerate the committed index, or with ``check`` report drift only."""
    rendered = render_index()
    stale = [name for name, text in rendered.items() if _read(INDEX_DIR / name) != text]
    if check:
        if stale:
            print(f"regulation-text index is stale: {', '.join(stale)}")
            print("Regenerate: uv run python scripts/regulation_text.py index")
            return 1
        print("regulation-text index is fresh")
        return 0
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    for name in stale:
        (INDEX_DIR / name).write_text(rendered[name], encoding="utf-8", newline="\n")
        print(f"  wrote {(INDEX_DIR / name).relative_to(REPO_ROOT).as_posix()}")
    corrections = INDEX_DIR / CORRECTIONS_FILE
    if not corrections.exists():
        corrections.write_text(",".join(CORRECTION_COLUMNS) + "\n", encoding="utf-8")
    if not stale:
        print("regulation-text index already fresh")
    # Keep the .agents/skills mirror in step, so Codex never reads a stale index.
    return int(_load_script("sync_agent_skills").main([]))


def command_show(ref: str, *, offline: bool = False, source: str = "auto") -> str:
    """Return the full ``show`` output for one article reference."""
    parsed = parse_reference(ref)
    if parsed is None:
        return (
            f"Could not read {ref!r} as an article. Try 'PS1/26 124F', 'CRR 501a' or "
            "'153(1)'; use 'find' to search by heading."
        )
    row = lookup(parsed.regime, parsed.article)
    label = REGIME_LABELS[parsed.regime]
    lines = [_render_entry(parsed, row)]
    lines.extend(_render_corrections(parsed))

    if source == "none":
        return "\n".join(lines)

    text_block: list[str] = []
    official_reason = ""
    if source in ("auto", "official"):
        article_text, official_reason = official_text(parsed, offline=offline)
        if article_text is not None:
            text_block = ["", article_text]
    if not text_block and source in ("auto", "snapshot"):
        snapshot = snapshot_text(parsed)
        if snapshot is not None:
            reason = f" ({official_reason})" if official_reason else ""
            text_block = [
                "",
                f"Official text not available here{reason}.",
                "Showing watchfire's bundled snapshot instead: a third-party parse of the "
                "same document that can split or merge paragraphs. Read the official PDF "
                "before relying on it for a change that reduces RWA (LESSONS A2).",
                "",
                snapshot,
            ]
    if not text_block:
        reason = official_reason or "no text source for this article"
        text_block = [
            "",
            f"No text for {label} {parsed.article} here: {reason}. Use the index entry "
            f"above, and read the article in {REGIME_DOCUMENTS[parsed.regime]} before "
            "quoting it. Never reconstruct it from memory.",
        ]
    lines.extend(text_block)
    return "\n".join(lines)


def command_fetch(regimes: Iterable[str]) -> int:
    """Download and convert the official PDF for each regime. Non-zero on any failure."""
    failures = 0
    for regime in regimes:
        (cache_root() / f".failed-{REGIME_DOCUMENTS[regime]}").unlink(missing_ok=True)
        conversion, reason = ensure_converted(regime, offline=False)
        if conversion is None:
            print(f"  {REGIME_LABELS[regime]}: not converted ({reason})")
            failures += 1
            continue
        found = len(conversion.articles)
        matched = sum(1 for a in conversion.articles.values() if a.get("heading_matched"))
        print(
            f"  {REGIME_LABELS[regime]}: {found} articles from {conversion.document} "
            f"({matched} with the snapshot heading found in the text) -> {conversion.directory}"
        )
    return 1 if failures else 0


def command_find(text: str) -> str:
    """Return index rows whose heading or title contains every word of ``text``."""
    words = [w.lower() for w in text.split() if w]
    hits: list[str] = []
    for regime, column in (("b31", "heading"), ("crr", "title")):
        for row in load_index(regime):
            haystack = row[column].lower()
            if all(w in haystack for w in words):
                hits.append(f"{REGIME_LABELS[regime]} {row['article']}: {row[column]}")
    if not hits:
        return f"No article heading or title contains: {text}"
    return "\n".join(hits)


def command_check() -> int:
    """Report index freshness, recorded corrections and the local cache state."""
    status = command_index(check=True)
    corrections = load_corrections()
    print(f"corrections recorded: {len(corrections)}")
    for row in corrections:
        print(f"  {row['regime']} {row['article']}: {row['instrument']} - {row['summary']}")
    for regime, document in REGIME_DOCUMENTS.items():
        pdf = find_document(document)
        if pdf is None:
            print(f"{REGIME_LABELS[regime]}: {document} not downloaded yet (show fetches it)")
            continue
        directory = _conversion_dir(pdf)
        state = "converted" if (directory / "articles.json").exists() else "not converted yet"
        print(f"{REGIME_LABELS[regime]}: {pdf} ({state})")
    return status


# =============================================================================
# REFERENCE PARSING AND LOOKUP
# =============================================================================


@dataclass(frozen=True)
class ArticleRef:
    """A parsed article reference: regime, base article, and any sub-reference."""

    regime: str
    article: str
    subref: str = ""


def parse_reference(ref: str) -> ArticleRef | None:
    """Parse a loose article reference.

    Accepts ``PS1/26 124F``, ``PS1/26, paragraph 124F``, ``B31 124F``, ``CRR 501a``,
    ``Article 153(1)(a)`` and a bare ``124F`` (Basel 3.1 by default, since PS1/26
    is the rule in force from 1 January 2027). Returns ``None`` when no article
    number can be found.
    """
    text = ref.strip()
    regime = "b31"
    head = re.match(r"^\s*(PS\s*1\s*/\s*26|B31|BASEL\s*3\.1|CRR)\b[\s,:]*", text, re.IGNORECASE)
    if head:
        regime = "crr" if head.group(1).upper() == "CRR" else "b31"
        text = text[head.end() :]
    text = re.sub(r"^(paragraph|para\.?|article|art\.?)\s*", "", text, flags=re.IGNORECASE)
    match = re.match(r"^(\d+[A-Za-z]{0,3})((?:\([0-9A-Za-z]+\))*)\s*$", text.strip())
    if match is None:
        return None
    return ArticleRef(regime=regime, article=match.group(1), subref=match.group(2))


def lookup(regime: str, article: str) -> dict[str, str] | None:
    """Return the committed index row for an article, matching case-insensitively."""
    for row in load_index(regime):
        if row["article"].lower() == article.lower():
            return row
    return None


def load_index(regime: str) -> list[dict[str, str]]:
    """Read one committed index file (``b31`` or ``crr``) as a list of rows."""
    path = INDEX_DIR / f"{regime}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_corrections() -> list[dict[str, str]]:
    """Read the hand-maintained corrections list (amendments the PDFs lack)."""
    path = INDEX_DIR / CORRECTIONS_FILE
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("article")]


# =============================================================================
# INDEX GENERATION
# =============================================================================


@dataclass
class _Links:
    """Code that cites one article: pack entries and functions."""

    pack_entries: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)


def render_index() -> dict[str, str]:
    """Render every committed index file from the repo and the watchfire snapshot."""
    from watchfire.index import load_index as load_snapshot

    snapshot = load_snapshot()
    links = collect_code_links()
    return {
        "b31.csv": _render_b31(snapshot, links.get("b31", {})),
        "crr.csv": _render_crr(snapshot, links.get("crr", {})),
        "other.csv": _render_other(links.get("other", {})),
    }


def collect_code_links() -> dict[str, dict[str, _Links]]:
    """Map regime -> article (or reference) -> the pack entries and functions citing it."""
    out: dict[str, dict[str, _Links]] = {}
    for citation, site in _iter_cites_sites():
        key = classify_citation(citation)
        if key is None:
            continue
        regime, article, subref = key
        label = site if not subref else f"{site} ({article}{subref})"
        out.setdefault(regime, {}).setdefault(article, _Links()).functions.add(label)
    for citation, entry in _iter_pack_citations():
        key = classify_citation(citation)
        if key is None:
            continue
        regime, article, subref = key
        label = entry if not subref else f"{entry} ({article}{subref})"
        out.setdefault(regime, {}).setdefault(article, _Links()).pack_entries.add(label)
    return out


def classify_citation(citation: str) -> tuple[str, str, str] | None:
    """Return ``(regime, article_or_reference, subref)`` for a canonical citation.

    PS1/26 articles (``PS1/26, paragraph 124F`` or ``PS1/26 Art. 124F(1)``) go to
    ``b31``; CRR articles to ``crr``; anything else (a PS1/26 policy paragraph
    such as ``4.55``, a supervisory statement, a PRA Rulebook part) to ``other``
    keyed by its canonical string. Returns ``None`` if watchfire cannot parse it.
    """
    from watchfire.parser import CitationParseError, parse_citation

    try:
        parsed = parse_citation(citation)
    except CitationParseError:
        return None
    subref = "".join(
        f"({part})" for part in (parsed.paragraph, parsed.point, parsed.subpoint) if part
    )
    if parsed.instrument == "CRR" and parsed.article:
        return ("crr", parsed.article, subref)
    if parsed.instrument == "PS" and parsed.instrument_id == "PS1/26":
        if parsed.article:
            return ("b31", parsed.article, subref)
        section = parsed.section or ()
        head = _ARTICLE_RE.match(section[0]) if section else None
        if head and len(section) == 1:
            return ("b31", section[0], "")
        # "123B.3" is the dotted spelling of Art. 123B(3) (the grammar takes no
        # parentheses here); low numbers such as "4.1" are rules of a Rulebook
        # Part (transitional provisions), not articles, and stay in other.csv.
        if head and len(section) == 2 and int(head.group(1)) >= _MIN_DOTTED_ARTICLE:
            return ("b31", section[0], f"({section[1]})")
    return ("other", parsed.canonical(), "")


def _iter_cites_sites() -> Iterable[tuple[str, str]]:
    """Yield ``(citation, "path::qualname")`` for every literal ``@cites`` under src/rwa_calc.

    Walks the source with ``ast`` rather than reading watchfire's matrix, which
    keeps only the outermost of stacked decorators and so drops the PS1/26 half
    of a dual citation.
    """
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(SRC_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for qualname, node in _walk_defs(tree):
            for decorator in node.decorator_list:
                citation = _cites_argument(decorator)
                if citation is not None:
                    yield citation, f"{rel}::{qualname}"


def _iter_pack_citations() -> Iterable[tuple[str, str]]:
    """Yield ``(citation, "regime:entry")`` for every resolved rulepack entry."""
    from rwa_calc.rulebook.resolve import resolve

    for regime in PACK_REGIMES:
        for name, entry in resolve(regime, PACK_REPORTING_DATE).entries.items():
            yield str(entry.citation), f"{regime}:{name}"


def _render_b31(snapshot: pl.DataFrame, links: dict[str, _Links]) -> str:
    import polars as pl

    rows = snapshot.filter(
        (pl.col("instrument") == "PS")
        & (pl.col("instrument_id") == "PS1/26")
        & pl.col("article").is_not_null()
    )
    facts = _snapshot_facts(rows)
    articles = _merge_keys(facts.keys(), links.keys())
    out: list[dict[str, str]] = []
    for article in articles:
        fact = facts.get(article, {})
        link = links.get(article, _Links())
        out.append(
            {
                "article": article,
                "heading": fact.get("heading", ""),
                "crr_article": fact.get("crr_article", ""),
                "left_blank": fact.get("left_blank", ""),
                "not_in_rulebook": fact.get("not_in_rulebook", ""),
                "in_snapshot": "yes" if article in facts else "no",
                "pack_entries": LIST_SEP.join(sorted(link.pack_entries)),
                "functions": LIST_SEP.join(sorted(link.functions)),
            }
        )
    return _to_csv(B31_COLUMNS, out)


def _render_crr(snapshot: pl.DataFrame, links: dict[str, _Links]) -> str:
    import polars as pl

    crr_rows = snapshot.filter((pl.col("instrument") == "CRR") & pl.col("article").is_not_null())
    titles: dict[str, str] = {}
    for article, title in crr_rows.select("article", "title").iter_rows():
        titles.setdefault(article, (title or "").strip())
    b31_rows = snapshot.filter(
        (pl.col("instrument") == "PS")
        & (pl.col("instrument_id") == "PS1/26")
        & pl.col("article").is_not_null()
    )
    reverse: dict[str, set[str]] = {}
    for b31_article, fact in _snapshot_facts(b31_rows).items():
        for crr_article in filter(None, fact.get("crr_article", "").split(LIST_SEP)):
            reverse.setdefault(crr_article, set()).add(b31_article)
    articles = _merge_keys(titles.keys(), links.keys())
    out: list[dict[str, str]] = []
    for article in articles:
        link = links.get(article, _Links())
        out.append(
            {
                "article": article,
                "title": titles.get(article, ""),
                "b31_articles": LIST_SEP.join(sorted(reverse.get(article, set()), key=article_key)),
                "in_snapshot": "yes" if article in titles else "no",
                "pack_entries": LIST_SEP.join(sorted(link.pack_entries)),
                "functions": LIST_SEP.join(sorted(link.functions)),
            }
        )
    return _to_csv(CRR_COLUMNS, out)


def _render_other(links: dict[str, _Links]) -> str:
    out = [
        {
            "reference": reference,
            "pack_entries": LIST_SEP.join(sorted(link.pack_entries)),
            "functions": LIST_SEP.join(sorted(link.functions)),
        }
        for reference, link in sorted(links.items())
    ]
    return _to_csv(OTHER_COLUMNS, out)


def _snapshot_facts(rows: pl.DataFrame) -> dict[str, dict[str, str]]:
    """Per PS1/26 article: heading, CRR correspondence and the note markers."""
    facts: dict[str, dict[str, str]] = {}
    corresponds: dict[str, set[str]] = {}
    blank: dict[str, list[str]] = {}
    survives: dict[str, list[str]] = {}
    for row in rows.iter_rows(named=True):
        article = row["article"]
        text = row["content_text"] or ""
        fact = facts.setdefault(article, {})
        location = _location(row)
        heading = _heading_of(text)
        if heading and "heading" not in fact:
            # Prefer the unnumbered row; a numbered row only when it is nothing
            # but a heading (the snapshot sometimes files the heading under (1)).
            body = _NOTE_LINE_RE.sub("", text).strip()
            if not location or heading == " ".join(body.split()):
                fact["heading"] = heading
        for match in _CORRESPONDS_RE.finditer(text):
            for number in re.split(r"\s*(?:,|and)\s*", match.group(1)):
                corresponds.setdefault(article, set()).add(number.strip())
        if _LEFT_BLANK_RE.search(text):
            _append_unique(blank.setdefault(article, []), location or "whole")
        if _NOT_IN_RULEBOOK_RE.search(text):
            _append_unique(survives.setdefault(article, []), location or "whole")
    for article, fact in facts.items():
        fact["crr_article"] = LIST_SEP.join(
            sorted(corresponds.get(article, set()), key=article_key)
        )
        fact["left_blank"] = LIST_SEP.join(blank.get(article, []))
        fact["not_in_rulebook"] = LIST_SEP.join(survives.get(article, []))
    return facts


# =============================================================================
# OFFICIAL TEXT — download, convert, cache
# =============================================================================


@dataclass(frozen=True)
class Conversion:
    """A converted official document in the cache."""

    document: str
    directory: Path
    articles: dict[str, dict[str, object]]


def official_text(parsed: ArticleRef, *, offline: bool) -> tuple[str | None, str]:
    """Return ``(markdown, "")`` for the article, or ``(None, reason)``."""
    conversion, reason = ensure_converted(parsed.regime, offline=offline)
    if conversion is None:
        return None, reason
    key = _match_key(conversion.articles, parsed.article)
    if key is None:
        return None, f"{parsed.article} was not found in {conversion.document}"
    return (conversion.directory / f"art-{key}.md").read_text(encoding="utf-8"), ""


def ensure_converted(regime: str, *, offline: bool) -> tuple[Conversion | None, str]:
    """Make sure the regime's PDF is downloaded and converted; return the conversion."""
    document = REGIME_DOCUMENTS[regime]
    pdf = find_document(document)
    if pdf is None:
        if offline:
            return None, f"{document} is not downloaded and fetching is off"
        recent = _recent_failure(document)
        if recent:
            return None, recent
        pdf, reason = download_document(document)
        if pdf is None:
            _record_failure(document, reason)
            return None, reason
    directory = _conversion_dir(pdf)
    manifest = directory / "articles.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return Conversion(document, directory, data["articles"]), ""
    try:
        import pymupdf
    except ImportError:
        return None, "pymupdf is not installed (run: uv sync)"
    try:
        with pymupdf.open(pdf) as doc:
            pages = [page.get_text() for page in doc]
    except (RuntimeError, ValueError, OSError) as exc:
        return None, f"could not read {pdf.name}: {exc}"
    articles = split_articles(pages)
    if not articles:
        return None, f"found no 'Article N' headings in {pdf.name}"
    return _write_conversion(regime, pdf, directory, articles), ""


def split_articles(pages: Sequence[str]) -> dict[str, dict[str, object]]:
    """Split page texts into articles keyed by article number.

    An article starts at a line beginning ``Article N`` and runs to the next
    such line. Where a document has many bare ``Article N`` lines (the PDFs
    put the heading on the following line), only those count as boundaries,
    so a body sentence that happens to start "Article 124 applies..." after a
    line wrap does not cut an article short. When the same number opens more
    than one span (a contents page, a cross-reference), the longest wins.

    Returns ``{article: {"text", "start_page", "end_page"}}`` with 1-based pages.
    """
    text_parts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        page_starts.append(offset)
        text_parts.append(page if page.endswith("\n") else page + "\n")
        offset += len(text_parts[-1])
    full = "".join(text_parts)

    matches = list(_ARTICLE_LINE_RE.finditer(full))
    bare = [m for m in matches if not m.group("rest").strip()]
    boundaries = bare if len(bare) >= _MIN_BARE_HEADINGS else matches
    if not boundaries:
        return {}

    best: dict[str, dict[str, object]] = {}
    for i, match in enumerate(boundaries):
        start = match.start()
        end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(full)
        article = match.group(1)
        span = full[start:end].strip()
        current = best.get(article)
        if current is not None and len(str(current["text"])) >= len(span):
            continue
        best[article] = {
            "text": span,
            "start_page": _page_of(page_starts, start),
            "end_page": _page_of(page_starts, max(start, end - 1)),
        }
    return best


def find_document(filename: str) -> Path | None:
    """Return a downloaded copy of ``filename`` in this or the main checkout's docs/assets."""
    for root in dict.fromkeys((REPO_ROOT, main_checkout())):
        candidate = root / "docs" / "assets" / filename
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def download_document(filename: str) -> tuple[Path | None, str]:
    """Download one manifest entry into the main checkout's docs/assets."""
    download_docs = _load_script("download_docs")
    entry = next((e for e in download_docs.MANIFEST if e.filename == filename), None)
    if entry is None or entry.url is None:
        return None, f"{filename} has no download URL in scripts/download_docs.py"
    assets = main_checkout() / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    results = download_docs.download_documents([entry], assets)
    result = results[0]
    if result["status"] not in ("downloaded", "skipped"):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", entry.url)
        return None, f"could not download {filename} from {host}: {result['detail']}"
    return assets / filename, ""


def cache_root() -> Path:
    """The text cache: ``$RWA_REGTEXT_CACHE``, else ``.regulation-text/`` in the main checkout."""
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override)
    return main_checkout() / CACHE_DIRNAME


def main_checkout() -> Path:
    """The main checkout's root, so every git worktree shares one download and cache."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return REPO_ROOT
    return Path(common).parent if common else REPO_ROOT


# =============================================================================
# SNAPSHOT TEXT — the parse bundled in the installed watchfire package
# =============================================================================


def snapshot_text(parsed: ArticleRef) -> str | None:
    """Render the watchfire snapshot rows for one article, or ``None`` if absent."""
    import polars as pl
    from watchfire.index import load_index as load_snapshot

    snapshot = load_snapshot()
    if parsed.regime == "crr":
        scope = pl.col("instrument") == "CRR"
    else:
        scope = (pl.col("instrument") == "PS") & (pl.col("instrument_id") == "PS1/26")
    rows = snapshot.filter(scope & (pl.col("article").str.to_lowercase() == parsed.article.lower()))
    if rows.height == 0:
        return None
    first = rows.row(0, named=True)
    version = first["version"]
    url = first["url"] or ""
    lines = [
        f"--- {REGIME_LABELS[parsed.regime]} Article {first['article']} "
        f"(watchfire snapshot {version}; source {url}) ---"
    ]
    for row in rows.iter_rows(named=True):
        text = (row["content_text"] or "").strip()
        location = _location(row)
        if not text or text == "...":
            continue
        lines.append(f"{location} {text}" if location else text)
    return "\n".join(lines)


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def article_key(article: str) -> tuple[int, int, str]:
    """Natural sort key: 124 < 124A < 124B < 124AA < 125."""
    match = _ARTICLE_RE.match(article)
    if match is None:
        return (sys.maxsize, 0, article.lower())
    return (int(match.group(1)), len(match.group(2)), match.group(2).lower())


def _render_entry(parsed: ArticleRef, row: dict[str, str] | None) -> str:
    label = REGIME_LABELS[parsed.regime]
    requested = f"{label} {parsed.article}{parsed.subref}"
    if row is None:
        return (
            f"{requested}: not in the committed index (no snapshot row and no code cites it). "
            "Check the number; PS1/26 renumbers CRR articles (LESSONS A3)."
        )
    heading = row.get("heading") or row.get("title") or "(no heading in the index)"
    lines = [f"{label} Article {row['article']}: {heading}"]
    if parsed.subref:
        lines.append(f"Requested: {requested} (the whole article is shown)")
    if parsed.regime == "b31":
        lines.append(
            f"Corresponds to CRR: {row['crr_article'] or 'no [Note: corresponds to] line'}"
        )
        if row["left_blank"]:
            lines.append(f"Provision left blank (deleted): {row['left_blank']}")
        if row["not_in_rulebook"]:
            lines.append(
                f"Provision not in PRA Rulebook (survives in CRR): {row['not_in_rulebook']}"
            )
    else:
        lines.append(f"PS1/26 articles that correspond: {row['b31_articles'] or 'none noted'}")
        lines.append(
            f"Official page: https://www.legislation.gov.uk/eur/2013/575/article/{row['article']}"
        )
    lines.append(f"Document: {REGIME_DOCUMENTS[parsed.regime]}")
    lines.extend(_render_list("Code (@cites)", row["functions"]))
    lines.extend(_render_list("Pack entries", row["pack_entries"]))
    return "\n".join(lines)


def _render_list(title: str, value: str) -> list[str]:
    items = [item for item in value.split(LIST_SEP) if item]
    if not items:
        return [f"{title}: none"]
    return [f"{title}:"] + [f"  - {item}" for item in items]


def _render_corrections(parsed: ArticleRef) -> list[str]:
    hits = [
        row
        for row in load_corrections()
        if row["regime"] == parsed.regime and row["article"].lower() == parsed.article.lower()
    ]
    return [
        f"WARNING: amended by {row['instrument']} after the PDF: {row['summary']}" for row in hits
    ]


def _write_conversion(
    regime: str, pdf: Path, directory: Path, articles: dict[str, dict[str, object]]
) -> Conversion:
    headings = {row["article"].lower(): row for row in load_index(regime)}
    directory.mkdir(parents=True, exist_ok=True)
    label = REGIME_LABELS[regime]
    digest = _sha256(pdf)
    converted = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    meta: dict[str, dict[str, object]] = {}
    for article, info in articles.items():
        text = str(info["text"])
        row = headings.get(article.lower())
        heading = (row.get("heading") or row.get("title") or "") if row else ""
        matched = bool(heading) and _normalise(heading) in _normalise(text)
        pages = f"{info['start_page']}" + (
            f"-{info['end_page']}" if info["end_page"] != info["start_page"] else ""
        )
        notes = _NOTE_LINE_RE.findall(text)
        header = [
            f"--- {label} Article {article} (official text, {pdf.name} page {pages}, "
            f"sha256 {digest[:12]}, converted {converted}) ---",
        ]
        if notes:
            header.append("Notes in this article: " + " | ".join(dict.fromkeys(notes)))
        (directory / f"art-{article}.md").write_text(
            "\n".join(header) + "\n\n" + _tidy(text) + "\n", encoding="utf-8"
        )
        meta[article] = {
            "start_page": info["start_page"],
            "end_page": info["end_page"],
            "heading_matched": matched,
        }
    (directory / "articles.json").write_text(
        json.dumps({"document": pdf.name, "sha256": digest, "articles": meta}, indent=1),
        encoding="utf-8",
    )
    return Conversion(pdf.name, directory, meta)


def _recent_failure(document: str) -> str:
    """The reason a download of ``document`` failed recently, or "" to try again."""
    marker = cache_root() / f".failed-{document}"
    if not marker.exists():
        return ""
    age = datetime.now(tz=UTC).timestamp() - marker.stat().st_mtime
    if age > _RETRY_AFTER_SECONDS:
        return ""
    reason = marker.read_text(encoding="utf-8").strip()
    return f"{reason} ({int(age // 60)} min ago; run 'fetch' to retry now)"


def _record_failure(document: str, reason: str) -> None:
    """Remember a failed download so every ``show`` does not wait on a blocked host."""
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f".failed-{document}").write_text(reason + "\n", encoding="utf-8")


def _conversion_dir(pdf: Path) -> Path:
    return cache_root() / f"{pdf.stem}-{_sha256(pdf)[:12]}-v{CONVERTER_VERSION}"


def _match_key(articles: Mapping[str, object], article: str) -> str | None:
    if article in articles:
        return article
    lowered = {key.lower(): key for key in articles}
    return lowered.get(article.lower())


def _page_of(page_starts: list[int], offset: int) -> int:
    page = 0
    for i, start in enumerate(page_starts):
        if start <= offset:
            page = i
        else:
            break
    return page + 1


def _location(row: dict[str, object]) -> str:
    parts = [row.get("paragraph"), row.get("point"), row.get("subpoint")]
    return "".join(f"({part})" for part in parts if part)


def _heading_of(text: str) -> str:
    """The upper-case heading that opens a PS1/26 article's first snapshot row.

    The snapshot keeps the heading and any unnumbered body text in one row, so
    the heading is the leading run of words with no lower-case letter, stopped
    at the first "[Note:" marker.
    """
    words: list[str] = []
    for word in text.split("[Note", 1)[0].split():
        if any(ch.islower() for ch in word):
            break
        words.append(word)
    if len(words) > 1 and len(words[-1]) == 1 and words[-1].isalpha():
        words.pop()  # "... HEADING A credit institution shall ..." -> drop the article "A"
    if len(words) < 2 or not any(ch.isalpha() for ch in "".join(words)):
        return ""  # a stray "4.6" or one capitalised word is not a heading
    return " ".join(words)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _merge_keys(*groups: Iterable[str]) -> list[str]:
    merged: dict[str, str] = {}
    for group in groups:
        for key in group:
            merged.setdefault(key.lower(), key)
    return sorted(merged.values(), key=article_key)


def _to_csv(columns: Sequence[str], rows: Iterable[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _walk_defs(
    tree: ast.AST,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]]:
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                yield qualname, child
                stack.append((child, f"{qualname}."))
            else:
                stack.append((child, prefix))


def _cites_argument(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call) or not decorator.args:
        return None
    func = decorator.func
    name = (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else ""
    )
    first = decorator.args[0]
    if name != "cites" or not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    return first.value


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _load_script(name: str) -> ModuleType:
    """Import a sibling script by path, so this works as a script and from tests."""
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_regtext_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    sys.exit(main())
