"""
The parser's output, pinned: every published rule cell, and a generated corpus beside it.

``boe.grammar`` finds the end of a reference and splits its parts with compiled
scans instead of walking the text one character at a time. The scans must give
the tree, the refusal and the refusal's position the character walk gave, on
every input — and the published rule books cannot show that they do. Not one of
the 13,656 references in them holds a comma inside a bracket or a string, a
bracket without its partner, a brace in a string or a quote that is never
closed, so a scan that mishandles one leaves every published tree as it was. A
split that overlooks ``[`` was measured doing exactly that: no outcome changes
on the 11,446 published cells and every other test of the grammar passes, while
284 inputs of the corpus below parse differently.

So two things are held here, as digests banked from the parser BEFORE the scans
replaced the walks (commit 85cfe58):

- every expression, scope, join and where cell of every rule of every packaged
  rule book — one digest per rule book and kind, so a difference is localised,
  and one per rule for a fixed sample, so it can be named;
- a seeded corpus of inputs built to reach what the published cells do not:
  published cells with a character inserted, removed, replaced or repeated;
  short runs of the language's tokens in no order; and references written part
  by part with commas at depth, strings holding braces, brackets without a
  partner, empty parts, text that is not ASCII, and thousands of codes.

A digest covers, in order, each input's outcome: the ``repr`` of the tree, or
the ``GrammarError`` message AND position.

The corpus is itself a claim, so it is tested too: by counts of what it holds,
and by seven scans made blind to one character each, every one of which it must
tell from the parser. A corpus edited until it no longer could would fail here
rather than pass quietly above.

A digest that moves is a finding to explain, never a number to re-bank. The
golden is re-banked only when the trees are MEANT to change — a rule book is
added or replaced, or the language or the tree gains a form::

    uv run python packages/rwa-filer/tests/boe/test_grammar_golden.py

and the diff of the JSON is then read line by line: a rule book or kind that
moved without a reason is a parser regression.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "Guards that land with
  the changes"
- .claude/LESSONS.md C11, C12 — a corpus is a claim; assert its adequacy
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

from rwa_filer.boe import grammar
from rwa_filer.boe.catalogue import RULEBOOKS_DIRECTORY, RULEBOOKS_PACKAGE, available_rulebooks
from rwa_filer.boe.grammar import GrammarError, parse_expression, parse_join, parse_scope

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

GOLDEN: Final = Path(__file__).parent / "data" / "test_grammar_parse_golden.json"

#: One seed for the whole corpus; each family reads its own stream from it, so
#: resizing one family leaves the others' inputs as they were.
SEED: Final = 20261122
MUTATED_INPUTS: Final = 16_000
SOUP_INPUTS: Final = 40_000
CRAFTED_INPUTS: Final = 12_000

#: A published cell longer than this is not mutated: the time goes on length,
#: and the scans are no different at the far end of a long cell.
MUTATED_SOURCE_LIMIT: Final = 1_500
#: Every Nth rule of a rule book has its own digest banked, with every rule that
#: is refused and every rule with a where cell.
SAMPLE_EVERY: Final = 16

KINDS: Final = ("expression", "scope", "join", "where")
_PARSERS: Final[dict[str, Callable[[str], object]]] = {
    "expression": parse_expression,
    "scope": parse_scope,
    "join": parse_join,
    "where": parse_expression,
}

#: The refusals the two scans raise or cause, counted so the corpus is known to
#: reach each of them.
SCAN_REFUSALS: Final = (
    "unterminated reference",
    "unterminated string inside a reference",
    "a reference inside a reference",
    "an empty part in a reference",
)

#: Each of the parser's two scans with one of the characters it must stop at
#: left out — the mistakes the generated corpus exists to catch. None of them
#: changes what a single published cell parses to.
BLIND_SCANS: Final = {
    "split-overlooks-open-bracket": ("_NESTING", r'["()\]]'),
    "split-overlooks-close-bracket": ("_NESTING", r'["()\[]'),
    "split-overlooks-open-parenthesis": ("_NESTING", r'[")\[\]]'),
    "split-overlooks-close-parenthesis": ("_NESTING", r'["(\[\]]'),
    "split-overlooks-quote": ("_NESTING", r"[()\[\]]"),
    "end-overlooks-second-reference": ("_REFERENCE_STOP", r'["}]'),
    "end-overlooks-string": ("_REFERENCE_STOP", r"[{}]"),
}
#: How many crafted inputs each blind scan is run on: a fifth of the family is
#: enough for every one of them to be seen, and keeps the seven runs short.
BLIND_INPUTS: Final = 2_400


# =============================================================================
# The golden
# =============================================================================


@pytest.fixture(scope="module")
def measured() -> dict[str, Any]:
    """What the parser under test gives for the published cells and the corpus."""
    return measure()


@pytest.fixture(scope="module")
def banked() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_every_published_cell_parses_to_the_banked_tree(
    measured: dict[str, Any], banked: dict[str, Any]
) -> None:
    # Act
    moved = _moved_groups(measured["published"], banked["published"])
    named = _moved_rules(measured["published_sample"], banked["published_sample"])

    # Assert — every rule book and kind, then the sampled rules by name.
    assert not moved and not named, (
        f"published cells parse differently in {moved}; sampled rules that moved: {named[:20]}"
    )


def test_the_generated_corpus_parses_to_the_banked_outcomes(
    measured: dict[str, Any], banked: dict[str, Any]
) -> None:
    # Act — each banked figure that is no longer what is measured.
    moved = _moved_figures(measured["generated"], banked["generated"])

    # Assert — a tree, a refusal's text or a refusal's position moved.
    assert not moved, "generated inputs parse differently, banked -> now:\n" + "\n".join(moved)


# =============================================================================
# Adequacy — the corpus is a claim
# =============================================================================


def test_the_published_cells_are_every_cell_of_every_packaged_rule_book(
    measured: dict[str, Any],
) -> None:
    # Arrange
    books = measured["published"]
    rules = {name: len(_entries(name)) for name in available_rulebooks()}

    # Assert — every packaged rule book, three cells a rule and its where cell.
    assert books.keys() == rules.keys() and len(rules) >= 11
    for name, count in rules.items():
        assert [books[name][kind]["cells"] for kind in ("expression", "scope", "join")] == [
            count,
            count,
            count,
        ], name
        assert measured["published_sample"][name], f"no rule of {name} is sampled"
    assert sum(group["cells"] for book in books.values() for group in book.values()) > 10_000
    assert sum(book["where"]["cells"] for book in books.values()) > 0


def test_the_generated_corpus_reaches_what_no_published_cell_does(
    measured: dict[str, Any],
) -> None:
    # Arrange
    generated = measured["generated"]
    features = generated["crafted"]["features"]
    refused = {
        message: sum(family["refusals"][message] for family in generated.values())
        for message in SCAN_REFUSALS
    }

    # Assert — commas at depth and very long references that PARSE: a split that
    # goes wrong there changes a tree, not only a refusal.
    for feature, floor in (("comma_in_brackets", 500), ("comma_in_parentheses", 500), ("long", 20)):
        assert features[feature]["parsed"] >= floor, (feature, features[feature])
    # Assert — the walk's other branches: a string holding a comma or a brace, a
    # quote never closed, a reference in a reference, an empty part, text beyond
    # ASCII.
    for feature, floor in (
        ("comma_in_string", 300),
        ("brace_in_string", 300),
        ("unterminated_string", 200),
        ("nested_reference", 200),
        ("unterminated_reference", 200),
        ("empty_part", 200),
        ("unicode", 300),
    ):
        assert features[feature]["inputs"] >= floor, (feature, features[feature])
    # Assert — references whose ONLY quote, bracket or parenthesis is of one kind:
    # the inputs a split that overlooks that one kind gets wrong.
    for name in _NESTING.values():
        assert features[f"only_{name}"]["inputs"] >= 50, (name, features.get(f"only_{name}"))
    # Assert — each refusal a scan raises is reached often, at many positions.
    for message, count in refused.items():
        assert count >= 1_000, (message, count)
    # Assert — and no family is all refusals or all trees.
    for name, family in generated.items():
        assert 0 < family["errors"] < family["inputs"], (name, family["errors"])


@pytest.fixture(scope="module")
def sighted() -> str:
    """The digest of the first crafted inputs, with the parser as it is."""
    return _crafted(_Dice(SEED + 3), BLIND_INPUTS).record()["sha256"]


@pytest.mark.parametrize(("scan", "pattern"), BLIND_SCANS.values(), ids=BLIND_SCANS.keys())
def test_the_crafted_references_catch_a_scan_that_overlooks_one_character(
    monkeypatch: pytest.MonkeyPatch, sighted: str, scan: str, pattern: str
) -> None:
    # Arrange — the parser, with one character missing from one of its scans.
    assert getattr(grammar, scan).pattern != pattern, "the scan already reads this way"
    monkeypatch.setattr(grammar, scan, re.compile(pattern))

    # Act
    blind = _crafted(_Dice(SEED + 3), BLIND_INPUTS).record()["sha256"]

    # Assert — the same inputs no longer give the same outcomes: the golden
    # above would have gone red.
    assert blind != sighted


# =============================================================================
# Measuring
# =============================================================================


def measure() -> dict[str, Any]:
    """The golden's content, computed with the parser under test."""
    published: dict[str, dict[str, dict[str, Any]]] = {}
    sample: dict[str, dict[str, str]] = {}
    sources: list[tuple[str, str]] = []
    for name in available_rulebooks():
        groups = {kind: _Group() for kind in KINDS}
        sample[name] = {}
        for position, entry in enumerate(_entries(name)):
            outcomes = []
            for kind in KINDS:
                text = entry.get(kind) or ""
                if kind == "where" and not text:
                    outcomes.append("NONE")
                    continue
                outcomes.append(groups[kind].add(kind, text))
                if text and len(text) <= MUTATED_SOURCE_LIMIT:
                    sources.append((kind, text))
            refused = any(outcome.startswith("ERR") for outcome in outcomes)
            if position % SAMPLE_EVERY == 0 or refused or outcomes[-1] != "NONE":
                sample[name][entry["id"]] = _digest_of(outcomes)[:16]
        published[name] = {kind: group.record() for kind, group in groups.items()}
    return {
        "published": published,
        "published_sample": sample,
        "generated": {
            "mutated": _mutated(_Dice(SEED + 1), sources).record(),
            "soup": _soup(_Dice(SEED + 2)).record(),
            "crafted": _crafted(_Dice(SEED + 3)).record(),
        },
    }


class _Group:
    """An ordered run of parse outcomes: its digest, and what the outcomes were."""

    def __init__(self, *, generated: bool = False) -> None:
        self._generated = generated
        self._digest = hashlib.sha256()
        self._inputs = 0
        self._errors = 0
        self._refusals = dict.fromkeys(SCAN_REFUSALS, 0)
        self._features: dict[str, dict[str, int]] = {}

    def add(self, kind: str, text: str, features: Sequence[str] = ()) -> str:
        outcome = _outcome(kind, text)
        self._digest.update(outcome.encode("utf-8"))
        self._digest.update(b"\0")
        self._inputs += 1
        parsed = outcome.startswith("OK")
        self._errors += not parsed
        for message in SCAN_REFUSALS:
            self._refusals[message] += outcome.startswith(f"ERR {message} @")
        for feature in features:
            counts = self._features.setdefault(feature, {"inputs": 0, "parsed": 0})
            counts["inputs"] += 1
            counts["parsed"] += parsed
        return outcome

    def record(self) -> dict[str, Any]:
        digest = {"errors": self._errors, "sha256": self._digest.hexdigest()}
        if not self._generated:
            return {"cells": self._inputs, **digest}
        return {
            "inputs": self._inputs,
            **digest,
            "refusals": dict(self._refusals),
            "features": dict(sorted(self._features.items())),
        }


def _outcome(kind: str, text: str) -> str:
    """The tree, or the refusal with its position; any other exception by its type."""
    try:
        return f"OK {_PARSERS[kind](text)!r}"
    except GrammarError as error:
        return f"ERR {error} @{error.position}"
    except Exception as error:  # noqa: BLE001 - a crash is an outcome to pin too
        return f"EXC {type(error).__name__} {error}"


def _digest_of(outcomes: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(outcomes).encode("utf-8")).hexdigest()


def _entries(name: str) -> list[dict[str, Any]]:
    """The rules of one packaged rule book, as the file states them."""
    resource = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY, name)
    return json.loads(resource.read_text(encoding="utf-8"))["rules"]


def _moved_groups(now: dict[str, Any], was: dict[str, Any]) -> list[str]:
    """``book/kind`` for each group that differs, and each book only one side has."""
    moved = sorted(now.keys() ^ was.keys())
    for name in sorted(now.keys() & was.keys()):
        moved.extend(f"{name}/{kind}" for kind in KINDS if now[name][kind] != was[name][kind])
    return moved


def _moved_figures(now: object, was: object, path: str = "") -> list[str]:
    """``path: banked -> now`` for each leaf of two nested records that differs."""
    if not (isinstance(now, dict) and isinstance(was, dict)):
        return [] if now == was else [f"{path}: {was} -> {now}"]
    return [
        line
        for key in sorted(now.keys() | was.keys())
        for line in _moved_figures(now.get(key), was.get(key), f"{path}/{key}".lstrip("/"))
    ]


def _moved_rules(now: dict[str, dict[str, str]], was: dict[str, dict[str, str]]) -> list[str]:
    return sorted(
        f"{name}/{rule_id}"
        for name in now.keys() & was.keys()
        for rule_id in now[name].keys() | was[name].keys()
        if now[name].get(rule_id) != was[name].get(rule_id)
    )


# =============================================================================
# The generated corpus
# =============================================================================


class _Dice:
    """A seeded stream of choices.

    It reads ``Random.random`` alone: the one method whose sequence for a given
    seed Python guarantees across versions, so the corpus is the same inputs on
    any interpreter.
    """

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed).random

    def below(self, bound: int) -> int:
        return int(self._random() * bound)

    def pick[T](self, items: Sequence[T]) -> T:
        return items[self.below(len(items))]

    def chance(self, probability: float) -> bool:
        return self._random() < probability


_STRUCTURAL: Final = ('"', "(", ")", "[", "]", "{", "}", ",")
_INSERTS: Final = (
    *_STRUCTURAL * 3,
    *(";", ":", " ", "=", "<", ">", "!", "+", "-", "*", "/", ".", "$", "_", "0", "1", "a", "t"),
    *("dv: ", "seq: True", "[a, b]", '"x,y"', "(p, q)", "é", "\n"),
)


def _mutated(dice: _Dice, sources: Sequence[tuple[str, str]]) -> _Group:
    """Published cells, each with one edit: a token in, a character out, a slice twice."""
    group = _Group(generated=True)
    for _ in range(MUTATED_INPUTS):
        kind, text = dice.pick(sources)
        at = dice.below(len(text) + 1)
        end = min(len(text), at + 1 + dice.below(40))
        edit = dice.below(5)
        if edit == 0:
            text = text[:at] + dice.pick(_INSERTS) + text[at:]
        elif edit == 1:
            text = text[:at] + text[at + 1 :]
        elif edit == 2:
            text = text[:at] + dice.pick(_INSERTS) + text[at + 1 :]
        elif edit == 3:
            text = text[:at] + text[end:]
        else:
            text = text[:end] + text[at:]
        group.add(kind, text)
    return group


_SOUP: Final = (
    *("{", "}", '"', "(", ")", "[", "]", ",", ";", ":", " ", "=", "!=", "\\", "'", "\t", "\n"),
    *("t", "r", "c", "z", "x", "d", "dv", "id", "seq", "filter", "True", "False", "and", "sum"),
    *("0010", "010", "C 01.00", "v1", "eba_met:mi53", "[eba_GA:GB]", "isum", "$a", "é", ""),
    *("{{", "}}", '""'),
)


def _soup(dice: _Dice) -> _Group:
    """Short runs of the language's tokens in no order — every pair of neighbours."""
    group = _Group(generated=True)
    for _ in range(SOUP_INPUTS):
        body = "".join(dice.pick(_SOUP) for _ in range(1 + dice.below(13)))
        group.add("expression", body if dice.chance(0.3) else "{" + body + "}")
    return group


#: (what a ``dv`` part holds, what the reference then carries)
_DEFAULTS: Final = (
    ("0", ()),
    ("emptySequence()", ()),
    ("false()", ()),
    ('""', ()),
    ("\"''\"", ()),
    ("[eba_GA:x1]", ()),
    ("$[Default]", ()),
    ("CreateDate(2027, 1, 31)", ("comma_in_parentheses",)),
    ("[eba_GA:x1, eba_GA:x2]", ("comma_in_brackets",)),
    ("[eba_GA:é]", ()),
    ('"a,b"', ("comma_in_string",)),
    ('"}"', ("brace_in_string",)),
    ('"{t: A, r: 0010}"', ("brace_in_string", "comma_in_string")),
)
_FILTERS: Final = (
    ("this() = [eba_GA:GB]", ()),
    ("dim(this(), [eba_dim:GA]) = [eba_GA:GB]", ("comma_in_parentheses",)),
    ("not(dim(this(), [eba_dim:GA]) = [eba_GA:GB])", ("comma_in_parentheses",)),
    ("this() = [eba_GA:GB, eba_GA:FR]", ("comma_in_brackets",)),
    ("dim(this(), [eba_dim:GA, x]) = [eba_GA:GB, y]", ("comma_in_brackets",)),
    ("dim(this(), [eba_dim:Gä]) = [eba_GA:ü]", ("comma_in_parentheses",)),
    ('matches(this(), "^a,b}$") = [x:y]', ("comma_in_string", "brace_in_string")),
)
#: Mostly as published; the last is a comma and a no-break space, which is white
#: space the parser strips.
_SEPARATORS: Final = (*(", ",) * 30, ",", ",", " , ", ",\n  ", ",\N{NO-BREAK SPACE}")
_LONE_BRACKETS: Final = ("[", "]", "(", ")")
#: What makes a comma something other than a separator, by name.
_NESTING: Final = {
    '"': "quote",
    "[": "open_bracket",
    "]": "close_bracket",
    "(": "open_parenthesis",
    ")": "close_parenthesis",
}
_TABLES: Final = ("T1", "T1", "T2", "C 01.00", "C 01.00", "OF 08.01.a", "OF 08.01.a", "Tä1")

#: (the parser, the text) — ``<A>``, ``<B>`` and ``<C>`` each stand for a reference.
_SHAPES: Final = (
    *(("expression", "<A>"),) * 4,
    ("expression", "<A> >= 0"),
    ("expression", "<A> i= <B> i+ <C>"),
    ("expression", "if <A> > 0 then sum(<B>, <C>) != 0 else true()"),
    ("expression", 'matches(<A>, "^[A-Z]{2}, }$") and not(isNull(<B>))'),
    ("expression", "(<A> i* 0.5) < - <B> or <C> = .25"),
    ("expression", "((((((((<A> i* 0.5)))))))) < - (((<B>))) or <C> = .25"),
    ("scope", "scope(<A>, <B>)"),
    ("join", "join(JoinDimensions(<A>, [d:D]), dim(<B>, [d:D]) = dim(<C>, [d:E]))"),
    ("expression", "$[eba_GA:x1] != <A> and [Default] = <B>"),
)


def _crafted(dice: _Dice, inputs: int = CRAFTED_INPUTS) -> _Group:
    """References written part by part, alone and inside expressions, scopes and joins."""
    group = _Group(generated=True)
    for _ in range(inputs):
        kind, text = dice.pick(_SHAPES)
        features: set[str] = set()
        for marker in ("<A>", "<B>", "<C>"):
            if marker in text:
                text = text.replace(marker, _reference(dice, features))
        group.add(kind, text, sorted(features))
    return group


def _reference(dice: _Dice, features: set[str]) -> str:
    """One reference; ``features`` gains a label for each thing it was built to hold."""
    parts: list[str] = []
    if dice.chance(0.1):
        parts.append(f"d: {dice.pick(('[eba_dim:GA]', '$[eba_dim:GA]', '[eba_dim:é]'))}")
    elif dice.chance(0.15):
        parts.append(f"T{dice.below(9)}")
    else:
        parts.append(f"t: {dice.pick(_TABLES)}")
    if dice.chance(0.006):
        codes = "; ".join(f"{1 + step:04d}" for step in range(500 + dice.below(2_500)))
        parts.append(f"r: {codes}")
        features.add("long")
    elif dice.chance(0.7):
        parts.append(f"r: {dice.pick(('0010', '0010; 0020; 0030', '010', '0010;0020'))}")
    if dice.chance(0.7):
        parts.append(f"{dice.pick(('c', 'x'))}: {dice.pick(('0010', '010; 020', '0070'))}")
    if dice.chance(0.2):
        parts.append("z: 0001")
    if dice.chance(0.6):
        default, labels = dice.pick(_DEFAULTS)
        parts.append(f"dv: {default}")
        features.update(labels)
    if dice.chance(0.35):
        written, labels = dice.pick(_FILTERS)
        parts.append(f"filter: {written}")
        features.update(labels)
    parts.append(f"seq: {dice.pick(('True', 'False', 'true', 'FALSE'))}")
    if dice.chance(0.5):
        parts.append(f"id: v{dice.below(4)}")
    if dice.chance(0.5):
        parts.extend(("f: banking", "fv: banking_reporting"))
    if dice.chance(0.04):
        parts.insert(dice.below(len(parts) + 1), dice.pick(("", " ")))
        features.add("empty_part")
    if dice.chance(0.1):
        at = dice.below(len(parts))
        parts[at] = dice.pick(_LONE_BRACKETS) + parts[at]
        features.add("lone_bracket")
    if dice.chance(0.04):
        at = dice.below(len(parts))
        parts[at] = parts[at] + '"'
        features.add("unterminated_string")
    if dice.chance(0.04):
        at = dice.below(len(parts))
        parts[at] = "{" + parts[at]
        features.add("nested_reference")
    body = parts[0]
    for part in parts[1:]:
        body += dice.pick(_SEPARATORS) + part
    if not body.isascii():
        features.add("unicode")
    nesting = {char for char in body if char in _NESTING}
    if len(nesting) == 1 and "," in body:
        features.add(f"only_{_NESTING[nesting.pop()]}")
    if dice.chance(0.05):
        features.add("unterminated_reference")
        return "{" + body
    return "{" + body + "}"


# =============================================================================
# Re-banking
# =============================================================================


def main() -> int:
    """Write the golden from the parser on the path. Read the diff before keeping it."""
    golden = {
        "_comment": (
            "Digests of what boe.grammar gives for every cell of every packaged rule book "
            "and for a seeded generated corpus: the repr of the tree, or the GrammarError "
            "message and position, in order. Banked from the parser before its character "
            "walks became compiled scans (commit 85cfe58). Re-banked only when the trees "
            "are meant to change, with tests/boe/test_grammar_golden.py's main - never by "
            "hand, and never to make a moved digest green."
        ),
        "seed": SEED,
        **measure(),
    }
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {GOLDEN}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
