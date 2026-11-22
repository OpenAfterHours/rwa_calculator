"""
A rule's fingerprint: digested once for each severity, and the digest it has always been.

``Rule.fingerprint(module)`` is written into every validation report, evidence
file and manifest, and is how a publisher issue recognises the rule it is
about. It is a SHA-256 over the rule's cells and its severity for the module,
and it used to be worked out afresh on every call: once per rule per report.
The rule now keeps each digest after first use. A kept answer is only as good
as its key, so four things are held here.

- VALUE. Every fingerprint of every rule of every packaged rule book, for each
  of the rule book's modules, a module the rule book does not have and a module
  written in lower case, is the one banked from the code BEFORE anything was
  kept (commit 85cfe58). One digest per rule book; a sample by name.
- FRESHNESS. Asked for again, a fingerprint is the one first worked out, and it
  equals what a new copy of the rule, with nothing kept, works out for itself.
  The modules are asked in turn on ONE rule object, so an answer kept under too
  coarse a key would be handed to the wrong module.
- THE KEY. A fingerprint depends on the module only through the rule's severity
  there: two modules with one severity share a digest, two with different
  severities do not, and a copy of the rule with another severity or another
  cell has another fingerprint.
- COST, by call count: one digest per rule per severity, however often asked.

The banked digests move only when a rule book is added or replaced, or the
fingerprint is MEANT to change — which changes every report's rule identities
and every publisher issue's pin. Re-bank with::

    uv run python packages/rwa-filer/tests/boe/test_rule_fingerprint.py

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "a memo ... ships with
  a freshness check: every memoised answer equals an unmemoised lookup"
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any, Final

import pytest

from rwa_filer.boe import catalogue
from rwa_filer.boe.catalogue import (
    RULEBOOKS_DIRECTORY,
    RULEBOOKS_PACKAGE,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Rule,
    RuleBook,
    available_rulebooks,
    rulebook_from,
)

GOLDEN: Final = Path(__file__).parent / "data" / "test_rule_fingerprints_golden.json"

#: A module no rule book has: every rule is an Error there, by default.
NO_SUCH_MODULE: Final = "XYZ999"
#: Every Nth rule of a rule book has its fingerprints banked by name.
SAMPLE_EVERY: Final = 64

EXPRESSION: Final = "{t: T01.00.01.01, r: 0010, c: 0010, dv: 0, seq: False} >= 0"


# =============================================================================
# Value — the banked digests
# =============================================================================


def test_every_packaged_fingerprint_is_the_banked_one() -> None:
    # Arrange
    banked = json.loads(GOLDEN.read_text(encoding="utf-8"))

    # Act
    now = measure()

    # Assert — by rule book, then the sampled rules by name.
    moved = sorted(
        name
        for name in now["books"].keys() | banked["books"].keys()
        if now["books"].get(name) != banked["books"].get(name)
    )
    named = sorted(
        f"{name}/{rule_id}"
        for name in now["sample"].keys() & banked["sample"].keys()
        for rule_id in now["sample"][name]
        if now["sample"][name][rule_id] != banked["sample"][name].get(rule_id)
    )
    assert not moved, f"fingerprints moved in {moved}"
    assert not named, f"sampled rules whose fingerprints moved: {named[:20]}"


# =============================================================================
# Freshness — a kept answer is the answer
# =============================================================================


def test_a_fingerprint_asked_for_again_is_what_a_rule_with_nothing_kept_works_out() -> None:
    # Arrange
    books = [_unread(name) for name in available_rulebooks()]
    stale: list[tuple[str, str]] = []
    asked = 0
    module_dependent = 0

    # Act — each module in turn on the SAME rule object, twice; against a new
    # copy of the rule, which has nothing kept, asked once.
    for book in books:
        for packaged in book.rules:
            first = [packaged.fingerprint(module) for module in _modules(book)]
            again = [packaged.fingerprint(module) for module in _modules(book)]
            fresh = [replace(packaged).fingerprint(module) for module in _modules(book)]
            asked += len(first)
            module_dependent += len(set(first)) > 1
            if not first == again == fresh:
                stale.append((book.framework_version, packaged.rule_id))

    # Assert — the corpus can see a wrong key: it holds rules whose fingerprint
    # differs from one module asked to the next.
    assert asked > 5_000, (asked, module_dependent)
    assert module_dependent > 500, (asked, module_dependent)
    assert not stale, stale[:20]


def test_a_copy_of_a_rule_with_another_severity_or_cell_has_another_fingerprint() -> None:
    # Arrange — a rule whose fingerprint has been asked for, and so is kept.
    original = _rule({"A": SEVERITY_ERROR})
    kept = original.fingerprint("A")

    # Act
    milder = replace(original, severities={"A": SEVERITY_WARNING})
    reworded = replace(original, expression=f"{EXPRESSION} + 1")
    same = replace(original)

    # Assert — a copy answers for its own fields, not from what the original kept.
    assert len({kept, milder.fingerprint("A"), reworded.fingerprint("A")}) == 3
    assert same.fingerprint("A") == original.fingerprint("A") == kept


# =============================================================================
# The key — the module counts only through the severity
# =============================================================================


@pytest.mark.parametrize(
    "order", [("A", "B", "C"), ("C", "B", "A"), ("B", "A", "C")], ids=["ABC", "CBA", "BAC"]
)
def test_the_fingerprint_follows_the_severity_of_the_module_asked_for(
    order: tuple[str, ...],
) -> None:
    # Arrange — a Warning for A, an Error for B, and no severity for C: an Error.
    mixed = _rule({"A": SEVERITY_WARNING, "B": SEVERITY_ERROR})

    # Act — in every order, so no module is answered from another's kept digest.
    digests = {module: mixed.fingerprint(module) for module in order}

    # Assert
    assert digests["A"] != digests["B"]
    assert digests["C"] == digests["B"]
    assert digests == {module: replace(mixed).fingerprint(module) for module in "ABC"}


# =============================================================================
# Cost — one digest per rule per severity
# =============================================================================


def test_a_fingerprint_is_digested_once_for_each_severity_however_often_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — every rule of every packaged rule book, unread, and a count of
    # the digests taken. A rule is asked at each of ``_modules``; what it needs
    # is one digest for each severity those modules give it.
    books = [_unread(name) for name in available_rulebooks()]
    asks = [
        (packaged, module) for book in books for packaged in book.rules for module in _modules(book)
    ]
    severities = sum(
        len({packaged.severity(module) for module in _modules(book)})
        for book in books
        for packaged in book.rules
    )
    rules = sum(len(book.rules) for book in books)
    digested: Counter[str] = Counter()
    real = catalogue.canonical_sha256

    def counting(content: object) -> str:
        digested["canonical_sha256"] += 1
        return real(content)

    monkeypatch.setattr(catalogue, "canonical_sha256", counting)
    assert rules > 3_000, (rules, severities, len(asks))
    assert rules < severities < len(asks), (rules, severities, len(asks))

    # Act — three reports' worth.
    taken = []
    for _ in range(3):
        prints = [packaged.fingerprint(module) for packaged, module in asks]
        taken.append(digested["canonical_sha256"])

    # Assert — the path was live, and every digest was taken in the first pass:
    # one for each rule at each severity, none again.
    assert all(len(fingerprint) == 64 for fingerprint in prints)
    assert taken == [severities, severities, severities]


# =============================================================================
# Measuring, and re-banking
# =============================================================================


def measure() -> dict[str, Any]:
    """Every packaged fingerprint, from rules nothing has read: digests and a sample."""
    books: dict[str, dict[str, Any]] = {}
    sample: dict[str, dict[str, dict[str, str]]] = {}
    for name in available_rulebooks():
        book = _unread(name)
        digest = hashlib.sha256()
        sample[name] = {}
        count = 0
        for position, packaged in enumerate(book.rules):
            prints = {module: packaged.fingerprint(module) for module in _modules(book)}
            for module, fingerprint in prints.items():
                digest.update(f"{packaged.rule_id}\t{module}\t{fingerprint}\n".encode())
            count += len(prints)
            if position % SAMPLE_EVERY == 0:
                sample[name][packaged.rule_id] = prints
        books[name] = {
            "rules": len(book.rules),
            "fingerprints": count,
            "sha256": digest.hexdigest(),
        }
    return {"books": books, "sample": sample}


def main() -> int:
    """Write the golden from the code on the path. Read the diff before keeping it."""
    golden = {
        "_comment": (
            "Rule.fingerprint(module) for every rule of every packaged rule book, for each "
            "of the rule book's modules, a module it does not have and its first module in "
            "lower case: one digest per rule book over 'rule\\tmodule\\tfingerprint' lines, "
            "and every 64th rule by name. Banked from the code before fingerprints were "
            "kept on the rule (commit 85cfe58). Re-banked with "
            "tests/boe/test_rule_fingerprint.py's main, never by hand."
        ),
        **measure(),
    }
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {GOLDEN}\n")
    return 0


def _rule(severities: dict[str, str]) -> Rule:
    return Rule("r", "test", EXPRESSION, severities, tables=("T01.00.01.01",))


def _unread(name: str) -> RuleBook:
    """One packaged rule book built afresh, so no rule has anything kept."""
    resource = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY, name)
    return rulebook_from(json.loads(resource.read_text(encoding="utf-8")))


def _modules(book: RuleBook) -> tuple[str, ...]:
    """The modules a rule of ``book`` is asked at: its own, one it lacks, one in lower case."""
    own = sorted(book.modules)
    return (*own, NO_SUCH_MODULE, own[0].lower())


if __name__ == "__main__":
    raise SystemExit(main())
