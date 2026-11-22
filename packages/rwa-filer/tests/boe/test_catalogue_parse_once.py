"""
A rule's cells are parsed once, and the trees they give are never replaced.

``Rule.parse_error`` is the first thing the engine asks of every enforced rule,
and answering it means parsing the expression, the scope, the join and the
where. Three things about what happens to that work are held here.

- COST, by call count. The parse is kept: ``tree``, ``scope_groups``, ``joins``
  and ``where_tree`` hand back what was parsed instead of parsing again,
  whichever of the five is read first. Counted on every readable rule of every
  packaged rule book, and on a cold engine run of the enforced rules of every
  packaged taxonomy pack.
- IDENTITY. The engine keys a rule's selectors by ``id()`` of the reference
  nodes of the tree it was handed, so the tree must stay ONE object however
  often and in whatever order the rule is read.
- THREADS. Two threads that read an unread rule at once both parse it. The
  first tree stored must be the one both are given, and nothing may replace it
  afterwards: an unlocked ``functools.cached_property`` stores the second
  thread's tree over the first's, and the first thread then looks its selectors
  up by nodes that are no longer the rule's — ``KeyError`` in the engine, 3 in
  52 trials of two validations started together. The interleaving is forced
  here with two events, so the test fails every time on a rule that can be
  overwritten, not three times in fifty-two.

What is kept is no part of the rule: its fields, equality and frozenness are
as they were, and ``dataclasses.replace`` gives a rule with nothing kept.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "Parse each rule once"
- .claude/LESSONS.md C11 — every count below first shows its path is live
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date
from importlib import resources
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from boe_builders import T01, T02, T04, ref, rule, scope
from pack_builders import SAMPLE_MODULE, VALID_LEI
from rwa_filer.boe import catalogue
from rwa_filer.boe.catalogue import (
    RULEBOOKS_DIRECTORY,
    RULEBOOKS_PACKAGE,
    Rule,
    available_rulebooks,
    rulebook_from,
)
from rwa_filer.boe.engine import (
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    evaluate_rules,
)
from rwa_filer.boe.grammar import GrammarError, parse_expression
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.release import release_rulebook
from rwa_filer.taxonomy.pack import available_packs, load_packaged

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

FIELDS = [
    "rule_id",
    "framework_version",
    "expression",
    "severities",
    "tables",
    "scope",
    "where",
    "join",
    "in_xbrl",
    "deactivated",
    "always_execute",
    "label",
    "truncated",
    "closed",
    "closed_by_variable",
    "spans_by_variable",
]

#: The four parsed parts, with the cell each is parsed from and the parser.
PARSED = {
    "tree": "parse_expression",
    "scope_groups": "parse_scope",
    "joins": "parse_join",
    "where_tree": "parse_expression",
}
ORDERS = {
    "as-the-engine-reads": ("parse_error", "joins", "scope_groups", "tree", "where_tree"),
    "parse-error-last": ("tree", "scope_groups", "joins", "where_tree", "parse_error"),
    "back-to-front": ("where_tree", "joins", "parse_error", "scope_groups", "tree"),
}
BROKEN = "{t: T01.00.01.01, r: 0010"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """How often the rule model asks the grammar to parse a cell, by parser."""
    counted: Counter[str] = Counter()
    for parser in sorted(set(PARSED.values())):
        monkeypatch.setattr(catalogue, parser, _counting(getattr(catalogue, parser), counted))
    return counted


# =============================================================================
# Cost — one parse per cell
# =============================================================================


@pytest.mark.parametrize("order", ORDERS.values(), ids=ORDERS.keys())
def test_reading_a_rule_parses_each_of_its_cells_once(
    calls: Counter[str], order: Sequence[str]
) -> None:
    # Arrange — every rule of every packaged rule book that is not cut short,
    # built afresh so nothing has read it.
    rules = [
        fresh for name in available_rulebooks() for fresh in _unread(name) if not fresh.truncated
    ]
    wheres = sum(1 for fresh in rules if fresh.where)
    assert len(rules) > 3_000, "the packaged rule books are not what is counted"
    assert wheres > 0, "the packaged rule books are not what is counted"

    # Act — every part in the order given, then every part again.
    for fresh in rules:
        for part in (*order, *order):
            getattr(fresh, part)

    # Assert — the path was live (every rule read, none refused), and each cell
    # went to the grammar once: the expression, the where cell where there is
    # one, and the scope and join cells, which are parsed even when empty.
    assert all(fresh.parse_error is None for fresh in rules)
    assert calls == {
        "parse_expression": len(rules) + wheres,
        "parse_scope": len(rules),
        "parse_join": len(rules),
    }


def test_a_cold_engine_run_parses_each_cell_of_each_enforced_rule_once(
    calls: Counter[str],
) -> None:
    # Arrange — for every packaged taxonomy pack, the module's enforced rules,
    # unread, and a return that declares every template reported, so no rule is
    # turned away before the engine reads it.
    turned_away = (REASON_UNSUPPORTED, REASON_UNKNOWN_TABLE, REASON_NOT_REPORTED)
    parsed: dict[str, dict[str, int]] = {}
    expected: dict[str, dict[str, int]] = {}
    unrun: list[tuple[str, str]] = []

    # Act
    for info in available_packs():
        pack = load_packaged(info.key)
        packaged = release_rulebook(info.version, info.module)
        assert packaged is not None
        assert packaged.file is not None
        rules = rulebook_from(_payload(packaged.file)).enforced(info.module)
        header = ReturnHeader(VALID_LEI, max(info.valid_from, date(2027, 3, 31)), info.module)
        empty = CanonicalReturn(
            header, pl.DataFrame(schema=FACT_SCHEMA), dict.fromkeys(pack.filing_indicators, True)
        )
        calls.clear()
        results = evaluate_rules(empty, pack, rules)
        parsed[info.key] = dict(calls)
        expected[info.key] = {
            "parse_expression": len(rules) + sum(1 for enforced in rules if enforced.where),
            "parse_scope": len(rules),
            "parse_join": len(rules),
        }
        unrun += [(info.key, result.rule_id) for result in results if result.reason in turned_away]

    # Assert — every rule of every pack reached its evaluation, which reads all
    # four parts; and each cell went to the grammar once.
    assert len(expected) > 10
    assert sum(pack["parse_scope"] for pack in expected.values()) > 2_000
    assert not unrun, unrun[:10]
    assert parsed == expected


# =============================================================================
# Identity — one tree per rule
# =============================================================================


@pytest.mark.parametrize("order", ORDERS.values(), ids=ORDERS.keys())
def test_a_rules_parts_are_the_same_objects_in_whatever_order_they_are_read(
    order: Sequence[str],
) -> None:
    # Arrange
    full = _full_rule()

    # Act — read in one order; make ``parse_error`` work its answer out again;
    # read in the opposite order.
    first = {part: getattr(full, part) for part in order}
    del vars(full)["parse_error"]
    again = {part: getattr(full, part) for part in reversed(order)}

    # Assert
    assert first["parse_error"] is None
    assert again["parse_error"] is None
    for part in PARSED:
        assert first[part], f"{part} is empty: one empty tuple is every empty tuple"
        assert again[part] is first[part], part


@pytest.mark.parametrize("part", PARSED)
def test_two_threads_reading_a_part_at_once_are_given_one_object(
    monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    # Arrange — the first thread to parse is held inside its parse until the
    # second has read the part and gone on to use it.
    full = _full_rule()
    parsing, read_elsewhere = _hold_the_first_parse(monkeypatch, PARSED[part])
    given: dict[str, object] = {}
    first = threading.Thread(target=lambda: given.update(first=getattr(full, part)))

    # Act
    first.start()
    assert parsing.wait(10), "the first thread never reached the grammar"
    given["second"] = getattr(full, part)
    read_elsewhere.set()
    first.join(10)

    # Assert — both were given the object the rule still holds.
    assert given["second"], f"{part} is empty: one empty tuple is every empty tuple"
    assert given["first"] is given["second"] is getattr(full, part)


def test_a_thread_still_checking_a_rule_does_not_replace_what_another_has_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — the first thread is held inside ``parse_error``, having parsed
    # the expression, until the second has read all four parts.
    full = _full_rule()
    parsing, read_elsewhere = _hold_the_first_parse(monkeypatch, "parse_expression")
    answers: list[str | None] = []
    first = threading.Thread(target=lambda: answers.append(full.parse_error))

    # Act
    first.start()
    assert parsing.wait(10), "the first thread never reached the grammar"
    read = {part: getattr(full, part) for part in PARSED}
    read_elsewhere.set()
    first.join(10)

    # Assert
    assert answers == [None]
    for part, held in read.items():
        assert getattr(full, part) is held, part


# =============================================================================
# What is kept is no part of the rule
# =============================================================================


def test_what_a_rule_keeps_is_not_a_field_and_does_not_survive_a_copy() -> None:
    # Arrange — one rule read in full, one never read.
    read, unread = _full_rule(), _full_rule()
    for part in ("parse_error", *PARSED):
        getattr(read, part)
    read.fingerprint(SAMPLE_MODULE)

    # Act
    copy = replace(read)

    # Assert — something IS kept on the rule that was read; none of it is a
    # field, counts towards equality, or is carried to the copy.
    assert vars(read).keys() > set(FIELDS)
    assert [field.name for field in fields(Rule)] == FIELDS
    assert read == unread == copy
    assert vars(copy).keys() == vars(unread).keys() == set(FIELDS)


def test_a_rule_is_still_frozen_compared_by_its_fields_and_unhashable() -> None:
    # Arrange
    full = _full_rule()
    _ = full.parse_error

    # Assert
    parameters = Rule.__dataclass_params__  # type: ignore[attr-defined]
    assert (parameters.frozen, parameters.eq, parameters.unsafe_hash) == (True, True, False)
    with pytest.raises(FrozenInstanceError):
        full.expression = BROKEN  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable"):
        hash(full)


def test_a_copy_with_another_cell_is_parsed_for_itself() -> None:
    # Arrange — a readable rule, read.
    full = _full_rule()
    assert full.parse_error is None
    assert full.tree

    # Act — the same rule with another expression, and with one that cannot be read.
    reworded = replace(full, expression=f"{ref(T02, '0020', '0010')} != 0")
    broken = replace(full, expression=BROKEN)

    # Assert — each copy answers from its own cells, not from what the original kept.
    assert reworded.parse_error is None
    assert reworded.tree == parse_expression(reworded.expression) != full.tree
    assert "unterminated reference" in (broken.parse_error or "")
    with pytest.raises(GrammarError):
        _ = broken.tree


# =============================================================================
# A rule that cannot be read
# =============================================================================


def test_a_part_that_cannot_be_read_is_refused_on_every_read_and_never_kept(
    calls: Counter[str],
) -> None:
    # Arrange
    broken = rule("r", BROKEN, tables=(T01,))

    # Act / Assert
    assert "unterminated reference" in (broken.parse_error or "")
    for _ in range(2):
        with pytest.raises(GrammarError, match="unterminated reference"):
            _ = broken.tree
    assert "tree" not in vars(broken)
    assert calls["parse_expression"] == 3


@pytest.mark.parametrize(
    ("cells", "reported"),
    [
        ({"expression": BROKEN, "scope": "scope(", "join": "join(", "where": "("}, "unterminated"),
        ({"scope": "scope()", "join": "join(", "where": "("}, "a scope cell must read"),
        ({"join": "join()", "where": "("}, "a join cell must read"),
        ({"where": "(("}, "the expression ends too soon"),
    ],
    ids=["expression", "scope", "join", "where"],
)
def test_the_first_cell_that_cannot_be_read_is_the_one_reported(
    cells: dict[str, str], reported: str
) -> None:
    """Expression, scope, join, where: the order a report's reason depends on."""
    # Arrange
    broken = replace(_full_rule(), **cells)

    # Act
    reason = broken.parse_error

    # Assert — and a part before the broken one is still there to be read.
    assert reason is not None, reason
    assert reason.startswith(reported), reason
    if "expression" not in cells:
        assert broken.tree == _full_rule().tree


# =============================================================================
# Helpers
# =============================================================================


def _full_rule() -> Rule:
    """A rule with every cell written, so no part of it is an empty tuple or ``None``."""
    return rule(
        "full",
        f"{ref(T01, '0010', '0010')} >= {ref(T02, '0010', '0010')}",
        tables=(T01, T02),
        scope=scope(T01, c="0010;0020"),
        join=f"join(JoinDimensions({ref(T04, c='0010')}, [tst_dim:OGR]))",
        where=f"{ref(T01, '0020', '0010')} != 0",
    )


def _payload(name: str) -> dict[str, Any]:
    resource = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY, name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _unread(name: str) -> tuple[Rule, ...]:
    """The rules of one packaged rule book as new objects, which nothing has read."""
    return rulebook_from(_payload(name)).rules


def _counting(real: Callable[[str], object], counted: Counter[str]) -> Callable[[str], object]:
    def parse(text: str) -> object:
        counted[real.__name__] += 1
        return real(text)

    return parse


def _hold_the_first_parse(
    monkeypatch: pytest.MonkeyPatch, parser: str
) -> tuple[threading.Event, threading.Event]:
    """Make the first call of ``parser`` wait, parsed but not returned, for the second event.

    The first event is set once that call has its result in hand. Later calls
    go straight through.
    """
    real = getattr(catalogue, parser)
    parsing, go_on = threading.Event(), threading.Event()

    def parse(text: str) -> object:
        parsed = real(text)
        if not parsing.is_set():
            parsing.set()
            assert go_on.wait(10), "the held parse was never released"
        return parsed

    monkeypatch.setattr(catalogue, parser, parse)
    return parsing, go_on
