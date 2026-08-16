"""Regenerate the per-article confidence / evidence matrix.

The project already carries four *independent* evidence layers that each cite
regulatory articles, but nothing joins them, so nobody can answer "which
articles are backed by an implementation *and* a hand-derived golden, and which
are cited by a test with no code behind them at all?". This script builds that
join deterministically and renders it two ways:

1. ``docs/development/confidence-matrix.md`` — a human-readable page grouping
   articles by instrument (CRR, PS1/26) with an evidence row and a derived
   confidence tier per article, plus a gap list.
2. ``tests/contracts/data/confidence_snapshot.json`` — the machine-readable
   evidence join, keyed by article, with the full member lists per layer.

The four evidence layers (see the page header for the scoring rule):

- **Code** — ``@cites`` annotations, read from the committed
  ``tests/contracts/data/citation_snapshot.json`` (never shelled out to
  watchfire, which needs ``uv``).
- **Pack** — every cited entry in the resolved rulepacks
  (``rwa_calc.rulebook.resolve.resolve``), walked the same way
  ``scripts/generate_regulatory_tables.py`` walks them (whose ``REGIME_DATES``
  / ``REGIME_LABELS`` this script imports rather than copies).
- **Oracle** — the ``regulation`` field of every record in
  ``tests/oracle/expected_values.json`` (hand-derived golden values).
- **Tests (heuristic)** — a text scan of ``tests/**/*.py`` for citation
  patterns. Marked heuristic everywhere it appears because it is a lexical
  match, not an executed link.

Determinism is load-bearing: the outputs embed the package version and each
pack's content hash but **no timestamp**, so re-running on an unchanged tree is
byte-identical and ``tests/contracts/test_confidence_matrix_freshness.py`` can
gate freshness by simple string equality. Because the test-scan layer reads the
live ``tests/`` tree, adding a test that cites a new article makes the page
stale until regenerated — which is exactly what the freshness gate is for.

Usage:
    uv run python scripts/generate_confidence_matrix.py           # rewrite both
    uv run python scripts/generate_confidence_matrix.py --check   # exit 1 if stale

Exit codes:
    0 = artefacts written (or already fresh under --check)
    1 = --check found the page or snapshot stale

References:
- docs/development/citation-tracking.md (the citation grammar the layers share)
- scripts/generate_citation_matrix.py (the @cites snapshot this joins against)
- scripts/generate_regulatory_tables.py (the pack-walking pattern reused here)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_regulatory_tables import REGIME_DATES, REGIME_LABELS  # noqa: E402

from rwa_calc.rulebook.resolve import resolve  # noqa: E402

PAGE_PATH = REPO_ROOT / "docs" / "development" / "confidence-matrix.md"
SNAPSHOT_PATH = REPO_ROOT / "tests" / "contracts" / "data" / "confidence_snapshot.json"
CITATION_SNAPSHOT_PATH = REPO_ROOT / "tests" / "contracts" / "data" / "citation_snapshot.json"
ORACLE_PATH = REPO_ROOT / "tests" / "oracle" / "expected_values.json"
TESTS_ROOT = REPO_ROOT / "tests"
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"

#: Instrument groups, in page order — mirrors generate_citation_matrix.py.
INSTRUMENTS: tuple[tuple[str, str], ...] = (
    ("CRR", "CRR (Capital Requirements Regulation)"),
    ("PS1/26", "PS1/26 (PRA Policy Statement)"),
)

#: Confidence tiers in descending order of corroboration. ``UNCITED`` sits
#: between the citable tiers and ``GAP``: the article is implemented (named in
#: production source) but carries no ``@cites`` annotation and no pack value.
TIERS: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW", "UNCITED", "GAP")

#: Article token as used in the canonical citation grammar: a numeric base with
#: an optional single-letter amendment suffix (147A), any number of
#: parenthesised sub-references (154(4A)(b)), and any PS1/26 decimal paragraph
#: sub-number (166.5).
_ARTICLE_CORE = r"\d+[A-Za-z]?(?:\([0-9A-Za-z]+\))*(?:\.\d+)*"

#: A framework-tagged citation for the heuristic test scan and the oracle
#: parser: an explicit instrument, a separator (``Art.`` / ``paragraph``), then
#: an article core. Requiring the instrument prefix keeps the lexical scan from
#: matching bare "Art. 5" prose that is not a regulatory citation.
_TAGGED_CITE_RE = re.compile(
    rf"(?P<fw>CRR|PS1/26|PS\s*1/26)\s*(?:,\s*paragraph\s*|\s*Art\.\s*)(?P<art>{_ARTICLE_CORE})"
)

#: A bare ``Art. <n>`` reference with no instrument prefix — used only by the
#: oracle parser, which inherits the framework from the preceding tagged token.
_BARE_ART_RE = re.compile(rf"Art\.\s*(?P<art>{_ARTICLE_CORE})")

#: Map the oracle ``framework`` field to a citation-grammar instrument, used as
#: the fallback when a regulation string opens with a bare ``Art.`` token.
_ORACLE_FRAMEWORK = {"CRR": "CRR", "BASEL_3_1": "PS1/26"}

#: The phrase engine modules use to document a *deliberately uncitable* article:
#: the rule is implemented, but watchfire's bundled CRR index does not (yet)
#: contain the article, so ``@cites`` cannot be applied. Every such note in
#: ``src/rwa_calc/`` is a CRR article, so the article numbers on a matching line
#: are attributed to CRR. Purely additive — it annotates ``UNCITED`` rows.
_WATCHFIRE_GAP_RE = re.compile(r"does not (?:yet )?contain", re.IGNORECASE)


@dataclass(frozen=True)
class ArticleEvidence:
    """The joined evidence for one ``(framework, article)`` across all layers.

    ``article`` is the *base* article (``122`` for a ``122(2) Table 1``
    citation): the layers cite the same rule at differing sub-reference
    granularity, so the join collapses to the base article and preserves the
    full member lists per layer for audit. Each member tuple is sorted so the
    rendered outputs are deterministic.

    Two anchor notions matter. A *citable* anchor (``code_functions`` or
    ``pack_entries``) is a machine-verifiable link. A *source* anchor
    (``source_files``) is weaker: the article is merely named in production code
    — enough to prove it is implemented, but not annotated. The SA-CCR /
    CCR domain is implemented but largely uncitable because watchfire's bundled
    index omits those CRR articles (``watchfire_index_gap`` flags the ones the
    code documents as such).
    """

    framework: str
    article: str
    code_functions: tuple[str, ...]
    pack_entries: tuple[str, ...]
    source_files: tuple[str, ...]
    oracle_cases: tuple[str, ...]
    test_files: tuple[str, ...]
    watchfire_index_gap: bool

    @property
    def has_citable_anchor(self) -> bool:
        """True when a machine-verifiable anchor (``@cites`` or a pack value) exists."""
        return bool(self.code_functions or self.pack_entries)

    @property
    def is_implemented(self) -> bool:
        """True when the article is cited or at least named in production source."""
        return self.has_citable_anchor or bool(self.source_files)

    @property
    def layer_count(self) -> int:
        """How many of the five evidence layers reference this article."""
        return sum(
            bool(members)
            for members in (
                self.code_functions,
                self.pack_entries,
                self.source_files,
                self.oracle_cases,
                self.test_files,
            )
        )

    @property
    def confidence(self) -> str:
        """The derived tier — see :data:`_SCORING_RULE` for the documented rule."""
        if self.has_citable_anchor:
            if self.oracle_cases:
                return "HIGH"
            if self.test_files:
                return "MEDIUM"
            return "LOW"
        if self.source_files:
            return "UNCITED"
        return "GAP"

    def as_dict(self) -> dict[str, object]:
        """A stable, sort-keyed mapping for the machine-readable snapshot."""
        return {
            "framework": self.framework,
            "article": self.article,
            "confidence": self.confidence,
            "layer_count": self.layer_count,
            "watchfire_index_gap": self.watchfire_index_gap,
            "code_functions": list(self.code_functions),
            "pack_entries": list(self.pack_entries),
            "source_files": list(self.source_files),
            "oracle_cases": list(self.oracle_cases),
            "test_files": list(self.test_files),
        }


def build_matrix() -> list[ArticleEvidence]:
    """Join the five evidence layers into one sorted list of article rows."""
    code = _code_evidence()
    pack = _pack_evidence()
    source = _source_evidence()
    oracle = _oracle_evidence()
    tests = _test_evidence()
    index_gaps = _watchfire_index_gap_articles()

    keys = set(code) | set(pack) | set(source) | set(oracle) | set(tests)
    rows = [
        ArticleEvidence(
            framework=framework,
            article=article,
            code_functions=_sorted(code.get((framework, article))),
            pack_entries=_sorted(pack.get((framework, article))),
            source_files=_sorted(source.get((framework, article))),
            oracle_cases=_sorted(oracle.get((framework, article))),
            test_files=_sorted(tests.get((framework, article))),
            watchfire_index_gap=(framework, article) in index_gaps,
        )
        for framework, article in keys
    ]
    return sorted(rows, key=lambda r: (r.framework, _article_sort_key(r.article)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed page or snapshot differs from a fresh render",
    )
    args = parser.parse_args()

    rows = build_matrix()
    page = _render_page(rows)
    snapshot = _render_snapshot(rows)

    if args.check:
        stale = [
            path.relative_to(REPO_ROOT)
            for path, fresh in ((PAGE_PATH, page), (SNAPSHOT_PATH, snapshot))
            if _read(path) != fresh
        ]
        if stale:
            listing = ", ".join(str(p) for p in stale)
            sys.stderr.write(
                f"{listing} stale — regenerate with\n"
                "  uv run python scripts/generate_confidence_matrix.py\n"
            )
            return 1
        return 0

    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAGE_PATH.write_text(page, encoding="utf-8")
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(snapshot, encoding="utf-8")
    sys.stderr.write(
        f"wrote {PAGE_PATH.relative_to(REPO_ROOT)} and "
        f"{SNAPSHOT_PATH.relative_to(REPO_ROOT)} ({len(rows)} articles)\n"
    )
    return 0


# ---------------------------------------------------------------------------
# Evidence layers
# ---------------------------------------------------------------------------


def _code_evidence() -> dict[tuple[str, str], set[str]]:
    """``(framework, article) -> {module::attr}`` from the ``@cites`` snapshot."""
    snapshot: dict[str, list[str]] = json.loads(_read(CITATION_SNAPSHOT_PATH))
    out: dict[tuple[str, str], set[str]] = {}
    for func_key, citations in snapshot.items():
        for citation in citations:
            key = _parse_canonical(citation)
            if key is not None:
                out.setdefault(key, set()).add(func_key)
    return out


def _pack_evidence() -> dict[tuple[str, str], set[str]]:
    """``(framework, article) -> {entry_name@regime}`` from the resolved packs."""
    out: dict[tuple[str, str], set[str]] = {}
    for regime, on in REGIME_DATES:
        pack = resolve(regime, on)
        for name, entry in pack.entries.items():
            citation = entry.citation
            key = (citation.framework, _base_article(citation.article))
            out.setdefault(key, set()).add(f"{name}@{regime}")
            # Per-KEY provenance, where individual parameters of a bundle derive
            # from a different article than the bundle (P1.302). Without this the
            # matrix credits every parameter to the bundle's citation, so an
            # article that governs only some keys — CRR/PS1/26 Art. 163(1), which
            # floors retail where Art. 160(1) floors corporates and institutions —
            # shows NO pack evidence at all and reads as unimplemented.
            for param_key, param_citation in getattr(entry, "key_citations", {}).items():
                sub = (param_citation.framework, _base_article(param_citation.article))
                out.setdefault(sub, set()).add(f"{name}.{param_key}@{regime}")
    return out


def _source_evidence() -> dict[tuple[str, str], set[str]]:
    """``(framework, article) -> {source file}`` from a scan of production code.

    An article named anywhere in ``src/rwa_calc/`` — a docstring ``References:``
    line, an inline comment, a ``@cites`` argument — is evidence the rule is
    implemented, even where ``@cites`` cannot be applied. This is what
    distinguishes a genuine coverage gap (nobody has built it) from an
    implemented-but-unannotated article (built, but uncitable).
    """
    out: dict[tuple[str, str], set[str]] = {}
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(SRC_ROOT).as_posix()
        for match in _TAGGED_CITE_RE.finditer(text):
            key = (_normalise_framework(match["fw"]), _base_article(match["art"]))
            out.setdefault(key, set()).add(rel)
    return out


def _watchfire_index_gap_articles() -> set[tuple[str, str]]:
    """``{(framework, article)}`` the engine documents as uncitable index gaps.

    Scans production source for the ``does not (yet) contain`` note the CCR
    modules carry, and attributes the article numbers on that line to CRR (the
    bundled watchfire index is CRR-only). Used to annotate ``UNCITED`` rows with
    the reason they cannot be cited, rather than to change any tier.
    """
    out: set[tuple[str, str]] = set()
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        for line in py_file.read_text(encoding="utf-8").splitlines():
            if _WATCHFIRE_GAP_RE.search(line):
                for match in _BARE_ART_RE.finditer(line):
                    out.add(("CRR", _base_article(match["art"])))
    return out


def _oracle_evidence() -> dict[tuple[str, str], set[str]]:
    """``(framework, article) -> {exposure_id}`` from the oracle regulation fields.

    Parenthetical *contrast* notes ("... -> 250% (CRR Art. 133(2) assigned
    100%)") are stripped first: they cite a rule for comparison, not as the
    derivation basis, so counting them would inflate that article's oracle
    coverage. Sub-reference parens ("133(3)", "154(4A)(b)") never contain the
    ``Art.``/``paragraph`` keyword and so survive.
    """
    oracle = json.loads(_read(ORACLE_PATH))
    out: dict[tuple[str, str], set[str]] = {}
    for record in oracle["oracles"]:
        regulation = _strip_contrast_notes(record.get("regulation", ""))
        fallback = _ORACLE_FRAMEWORK.get(record.get("framework", ""))
        exposure_id = record.get("exposure_id", "?")
        for key in _parse_regulation(regulation, fallback):
            out.setdefault(key, set()).add(exposure_id)
    return out


def _test_evidence() -> dict[tuple[str, str], set[str]]:
    """``(framework, article) -> {test file}`` from a heuristic text scan of tests/.

    Purely lexical: any ``tests/**/*.py`` file whose text contains a
    framework-tagged citation counts as a reference to that article. This is the
    one layer that is not an executed link, hence flagged heuristic throughout.
    """
    out: dict[tuple[str, str], set[str]] = {}
    for py_file in sorted(TESTS_ROOT.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        for match in _TAGGED_CITE_RE.finditer(text):
            key = (_normalise_framework(match["fw"]), _base_article(match["art"]))
            out.setdefault(key, set()).add(rel)
    return out


# ---------------------------------------------------------------------------
# Citation parsing
# ---------------------------------------------------------------------------


def _parse_canonical(citation: str) -> tuple[str, str] | None:
    """Parse a canonical ``@cites`` string into ``(framework, base_article)``.

    Recognises the two grammars watchfire emits — ``CRR Art. <n>`` and
    ``PS1/26, paragraph <n>`` — plus the ``PS1/26 Art. <n>`` variant. Returns
    ``None`` for anything else so the caller can report it as ambiguous.
    """
    match = _TAGGED_CITE_RE.match(citation.strip())
    if match is None:
        return None
    return _normalise_framework(match["fw"]), _base_article(match["art"])


def _strip_contrast_notes(text: str) -> str:
    """Remove top-level parenthetical groups that contain a citation keyword.

    A contrast note like ``(CRR Art. 133(2) assigned 100%)`` cites a rule for
    comparison, not as the derivation basis; left in, its article bleeds into
    that rule's oracle count. A sub-reference paren (``(3)``, ``(4A)(b)``) never
    contains ``Art.``/``paragraph`` and is preserved. Groups are matched by
    tracking paren depth so a nested ``(2)`` inside a stripped note goes with it.
    """
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    for i, char in enumerate(text):
        if char == "(":
            if depth == 0:
                start = i
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                if re.search(r"Art\.|paragraph", text[start + 1 : i], re.IGNORECASE):
                    spans.append((start, i + 1))
                start = -1
    if not spans:
        return text
    parts: list[str] = []
    prev = 0
    for span_start, span_end in spans:
        parts.append(text[prev:span_start])
        parts.append(" ")
        prev = span_end
    parts.append(text[prev:])
    return "".join(parts)


def _parse_regulation(regulation: str, fallback: str | None) -> set[tuple[str, str]]:
    """Parse an oracle ``regulation`` string into ``{(framework, base_article)}``.

    Oracle strings tag the leading article with an instrument
    (``CRR Art. 153(1)`` / ``PS1/26 Art. 154(1)(a)``) and may chain further bare
    ``Art. <n>`` references that inherit the most recent instrument
    (``... with Art. 161(1)(a) and Art. 162(1)``). A string that opens with a
    bare ``Art.`` falls back to the record's ``framework`` field.
    """
    keys: set[tuple[str, str]] = set()
    current = fallback
    for token in _iter_regulation_tokens(regulation):
        framework, article = token
        if framework is not None:
            current = framework
        if current is not None:
            keys.add((current, _base_article(article)))
    return keys


def _iter_regulation_tokens(regulation: str) -> list[tuple[str | None, str]]:
    """Yield ``(framework_or_None, article)`` tokens left-to-right in one string.

    A tagged citation carries its instrument; a bare ``Art. <n>`` carries
    ``None`` so :func:`_parse_regulation` can attach the running instrument.
    Overlapping matches are avoided by consuming the string position-wise.
    """
    tokens: list[tuple[str | None, str]] = []
    pos = 0
    while pos < len(regulation):
        tagged = _TAGGED_CITE_RE.search(regulation, pos)
        bare = _BARE_ART_RE.search(regulation, pos)
        if tagged is not None and (bare is None or tagged.start() <= bare.start()):
            tokens.append((_normalise_framework(tagged["fw"]), tagged["art"]))
            pos = tagged.end()
        elif bare is not None:
            tokens.append((None, bare["art"]))
            pos = bare.end()
        else:
            break
    return tokens


def _normalise_framework(raw: str) -> str:
    """Collapse ``PS 1/26`` spacing variants to the canonical ``PS1/26``."""
    return "PS1/26" if raw.replace(" ", "") == "PS1/26" else raw


def _base_article(article: str) -> str:
    """Reduce a full article reference to its base ``\\d+[A-Za-z]?`` token."""
    match = re.match(r"\s*(\d+[A-Za-z]?)", article)
    return match.group(1) if match is not None else article.strip()


def _article_sort_key(article: str) -> tuple[int, str]:
    """Sort articles numerically, then lexically (so 147 precedes 147A)."""
    match = re.match(r"(\d+)", article)
    return (int(match.group(1)) if match is not None else 0, article)


# ---------------------------------------------------------------------------
# Rendering — markdown page
# ---------------------------------------------------------------------------

_SCORING_RULE = (
    "An article has a **citable anchor** when the *Code* (`@cites`) or *Pack* "
    "layer cites it — a machine-verifiable link. Being named in production "
    "*Source* is a **weaker signal**: usually an implementation footprint, but a "
    "docstring `References:` mention alone can also produce it. The tier is:\n\n"
    "| Tier | Rule |\n"
    "|---|---|\n"
    "| **HIGH** | citable anchor **and** an oracle case exists |\n"
    "| **MEDIUM** | citable anchor **and** a (heuristic) test reference, but no "
    "oracle case |\n"
    "| **LOW** | citable anchor, but no oracle case and no test reference |\n"
    "| **UNCITED** | no citable anchor, but named in production source — "
    "usually implemented yet un-annotated, though a `References:`-only mention "
    "lands here too (the SA-CCR cluster is here: watchfire's index omits those "
    "CRR articles, so `@cites` cannot be applied) |\n"
    "| **GAP** | not implemented at all — cited only by the oracle and/or a test, "
    "with no code, pack, or source reference behind it |\n\n"
    "Only **GAP** is an actionable coverage hole. **UNCITED** is a citation-debt "
    "signal, not a missing-implementation one."
)


def _render_page(rows: list[ArticleEvidence]) -> str:
    """Render the whole confidence-matrix page from the joined rows."""
    lines = _page_header(rows)
    for framework, heading in INSTRUMENTS:
        lines.extend(_render_instrument(framework, heading, rows))
    lines.append(
        "† = watchfire index gap: the article is implemented but its CRR number"
        " is absent from watchfire's bundled index, so `@cites` cannot be applied."
        " See the section below."
    )
    lines.append("")
    lines.extend(_render_uncited(rows))
    lines.extend(_render_gaps(rows))
    lines.extend(_render_warnings())
    return "\n".join(lines).rstrip("\n") + "\n"


def _page_header(rows: list[ArticleEvidence]) -> list[str]:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    lines = [
        "# Confidence & Evidence Matrix",
        "",
        "<!-- GENERATED FILE — DO NOT EDIT."
        " Regenerate: uv run python scripts/generate_confidence_matrix.py -->",
        "",
        "Per-article view of the **independent evidence layers** that already exist"
        " in this project, joined so a reader can see, for each regulatory article,"
        " whether it is backed by an implementation, a hand-derived golden, and/or a"
        " test — and where those layers disagree. **This page is generated** from"
        " those layers; a wrong row is a finding in one of the sources, never a docs"
        " edit.",
        "",
        "## Evidence layers",
        "",
        "| Layer | Source | Nature |",
        "|---|---|---|",
        "| **Code** | `tests/contracts/data/citation_snapshot.json`"
        " (`@cites` annotations) | citable anchor — a decorated function |",
        "| **Pack** | resolved rulepacks via `rwa_calc.rulebook.resolve` | citable"
        " anchor — a cited regulatory value |",
        "| **Source** | text scan of `src/rwa_calc/**/*.py` | implementation"
        " footprint — the article is named in production code (not necessarily"
        " `@cites`-annotated) |",
        "| **Oracle** | `tests/oracle/expected_values.json` (`regulation` field) |"
        " a hand-derived golden (parenthetical contrast notes excluded) |",
        "| **Tests** | text scan of `tests/**/*.py` | **heuristic** — a lexical"
        " citation match, not an executed link |",
        "",
        "## Scoring rule",
        "",
        _SCORING_RULE,
        "",
        "Articles are grouped by the citing instrument and keyed by *base* article"
        " (`122` for a `122(2)` citation); the layers cite the same rule at"
        " different sub-reference granularity, so the machine-readable snapshot at"
        " `tests/contracts/data/confidence_snapshot.json` preserves the full member"
        " list per layer for audit.",
        "",
        f"Package version `{version}`. Resolved packs:",
        "",
    ]
    for regime, on in REGIME_DATES:
        pack = packs[regime]
        lines.append(
            f"- **{REGIME_LABELS[regime]}** (`{regime}` @ {on.isoformat()}) — "
            f"content hash `{pack.content_hash[:16]}`"
        )
    lines.append("")
    lines.extend(_render_summary(rows))
    return lines


def _render_summary(rows: list[ArticleEvidence]) -> list[str]:
    lines = [
        "## Summary",
        "",
        "| Instrument | HIGH | MEDIUM | LOW | UNCITED | GAP | Total |",
        "|---|---|---|---|---|---|---|",
    ]
    for framework, heading in INSTRUMENTS:
        group = [r for r in rows if r.framework == framework]
        counts = {tier: sum(r.confidence == tier for r in group) for tier in TIERS}
        lines.append(
            f"| {heading} | {counts['HIGH']} | {counts['MEDIUM']} | {counts['LOW']} "
            f"| {counts['UNCITED']} | {counts['GAP']} | {len(group)} |"
        )
    lines.append("")
    return lines


def _render_instrument(framework: str, heading: str, rows: list[ArticleEvidence]) -> list[str]:
    group = [r for r in rows if r.framework == framework]
    lines = [f"## {heading}", ""]
    if not group:
        lines.extend(["_No cited articles for this instrument._", ""])
        return lines
    label = "Art." if framework == "CRR" else "para."
    lines.append(f"| {label} | Code fns | Pack | Src | Oracle | Tests | Confidence |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in group:
        tier = row.confidence + (" †" if row.watchfire_index_gap else "")
        lines.append(
            f"| {row.article} | {len(row.code_functions)} | {len(row.pack_entries)} "
            f"| {len(row.source_files)} | {len(row.oracle_cases)} | {len(row.test_files)} "
            f"| {tier} |"
        )
    lines.append("")
    return lines


def _render_uncited(rows: list[ArticleEvidence]) -> list[str]:
    uncited = [r for r in rows if r.confidence == "UNCITED"]
    lines = [
        "## Named in source but uncited (UNCITED)",
        "",
        "These articles are named in `src/rwa_calc/` production source but carry"
        " no `@cites` annotation and no pack value, so no machine-verifiable"
        " citation links them. Being named in source is a **weaker implementation"
        " signal than `@cites`**: most rows are genuinely implemented code, but a"
        " docstring `References:` mention can promote a context-only article here"
        " (e.g. a governance requirement the calculator does not compute). Treat"
        " a row as implemented only after reading the named modules. They are"
        " **not** coverage gaps. Two causes dominate: (1) the SA-CCR / CCR domain"
        " (marked †),"
        " implemented in `engine/ccr/` but uncitable because watchfire's bundled"
        " index omits those CRR articles — each module documents this with a"
        " `does not yet contain Art. N` note; (2) a rule that survives from CRR"
        " into PS1/26, cited as `PS1/26 Art. N` by the oracle/tests while the"
        " packs and code annotate it under `CRR Art. N` — the *Anchored as* column"
        " names that citable twin. Rows are ordered by oracle then test weight.",
        "",
    ]
    if not uncited:
        lines.extend(["_None._", ""])
        return lines
    citable_keys = {(r.framework, r.article) for r in rows if r.has_citable_anchor}
    ordered = sorted(
        uncited,
        key=lambda r: (-len(r.oracle_cases), -len(r.test_files), _article_sort_key(r.article)),
    )
    lines.append("| Article | Src | Oracle | Tests | Watchfire gap | Anchored as |")
    lines.append("|---|---|---|---|---|---|")
    for row in ordered:
        label = f"{row.framework} {row.article}"
        gap_flag = "yes" if row.watchfire_index_gap else "—"
        cross = _cross_instrument_anchor(row, citable_keys)
        lines.append(
            f"| {label} | {len(row.source_files)} | {len(row.oracle_cases)} "
            f"| {len(row.test_files)} | {gap_flag} | {cross} |"
        )
    lines.append("")
    return lines


def _render_gaps(rows: list[ArticleEvidence]) -> list[str]:
    gaps = [r for r in rows if r.confidence == "GAP"]
    lines = [
        "## Gaps — cited but not implemented",
        "",
        "The actionable list: articles referenced **only** by the oracle and/or a"
        " (heuristic) test, with no `@cites` annotation, no pack value, and no"
        " mention anywhere in production source. Implemented-but-unannotated"
        " articles are **not** here — they are in the UNCITED section above. Many"
        " rows below are definitional / scope / own-funds articles that a test"
        " docstring names in passing and that this calculator does not compute;"
        " the *Anchored as* column flags the rare case where the same number is"
        " citable under the other instrument. Rows are ordered by oracle then test"
        " weight.",
        "",
    ]
    if not gaps:
        lines.extend(["_None — every cited article is implemented._", ""])
        return lines
    citable_keys = {(r.framework, r.article) for r in rows if r.has_citable_anchor}
    ordered = sorted(
        gaps,
        key=lambda r: (-len(r.oracle_cases), -len(r.test_files), _article_sort_key(r.article)),
    )
    lines.append("| Article | Oracle cases | Test refs | Anchored as |")
    lines.append("|---|---|---|---|")
    for row in ordered:
        label = f"{row.framework} {row.article}"
        cross = _cross_instrument_anchor(row, citable_keys)
        lines.append(f"| {label} | {len(row.oracle_cases)} | {len(row.test_files)} | {cross} |")
    lines.append("")
    return lines


def _cross_instrument_anchor(row: ArticleEvidence, citable_keys: set[tuple[str, str]]) -> str:
    """Return the other-instrument citable anchor for an article, or ``—`` if none.

    A rule that survives from CRR into PS1/26 keeps its number, so an article
    that is un-anchored under one instrument is often the same rule cited under
    the other. A match here means the row is a framework-attribution artifact,
    not a missing implementation.
    """
    other = "PS1/26" if row.framework == "CRR" else "CRR"
    if (other, row.article) in citable_keys:
        label = "para." if other == "PS1/26" else "Art."
        return f"{other} {label} {row.article}"
    return "—"


def _render_warnings() -> list[str]:
    warnings = _ambiguous_citations()
    if not warnings:
        return []
    return [
        "## Generator warnings",
        "",
        "Citation strings that could not be parsed into a `(framework, article)`"
        " pair and were dropped from the join. Fix the source or extend the"
        " parser.",
        "",
        *(f"- `{w}`" for w in warnings),
        "",
    ]


def _ambiguous_citations() -> list[str]:
    """Canonical ``@cites`` strings the parser could not resolve to an article."""
    snapshot: dict[str, list[str]] = json.loads(_read(CITATION_SNAPSHOT_PATH))
    unresolved = {
        citation
        for citations in snapshot.values()
        for citation in citations
        if _parse_canonical(citation) is None
    }
    return sorted(unresolved)


# ---------------------------------------------------------------------------
# Rendering — machine-readable snapshot
# ---------------------------------------------------------------------------


def _render_snapshot(rows: list[ArticleEvidence]) -> str:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    payload = {
        "_doc": (
            "Generated by scripts/generate_confidence_matrix.py. Do NOT hand-edit. "
            "Regenerate: uv run python scripts/generate_confidence_matrix.py"
        ),
        "package_version": version,
        "pack_content_hashes": {regime: packs[regime].content_hash for regime, _ in REGIME_DATES},
        "scoring_rule": {
            "HIGH": "citable anchor (code or pack) and an oracle case",
            "MEDIUM": "citable anchor and a heuristic test reference, no oracle case",
            "LOW": "citable anchor, no oracle case and no test reference",
            "UNCITED": "no citable anchor, but named in production source (implemented, un-annotated)",
            "GAP": "not implemented — cited only by the oracle and/or a test, no source reference",
        },
        "articles": [row.as_dict() for row in rows],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _sorted(members: set[str] | None) -> tuple[str, ...]:
    return tuple(sorted(members)) if members else ()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


if __name__ == "__main__":
    raise SystemExit(main())
