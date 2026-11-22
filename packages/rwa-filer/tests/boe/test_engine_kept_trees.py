"""
An evaluation reads the trees it was built from, whatever happens to the rule afterwards.

Pipeline position:
    Rule (its parsed parts kept on the object)
        ->  boe.engine._Evaluation (selectors keyed by ``id()`` of the
            reference nodes of the trees it was handed)
        ->  every evaluation of the rule, and its trace

What is pinned:
- An ``_Evaluation`` reads the expression tree and the where tree it built its
  selectors from, and never reads them off the rule again: replacing ``tree``
  or ``where_tree`` in the rule's ``__dict__`` with a fresh parse of the same
  text, after the evaluation is built, changes nothing it finds — counts,
  failures and every traced evaluation.
- Through the public entry points, a rule whose parts are parsed afresh on
  EVERY read, so that no two reads give one tree, is evaluated and traced
  exactly as the rule itself is.

Why: ``functools.cached_property`` has no lock. Two threads validating at once
in a cold process could each parse a rule, and the second write replaced
``rule.tree`` after the first thread had keyed its selectors by the old tree's
nodes: ``KeyError`` at ``self._selectors[id(reference)]`` in 3 of 52 trials of
two validations started together, and the dashboard runs each task in its own
thread. The catalogue now keeps the first parse (``catalogue._keep_first``);
this file pins the engine's half, which must hold whatever the catalogue does.
Neither test needs a thread: the replacement is made where the race made it.

Observed red before the fix (2026-11-22, the engine reading ``self._rule.tree``
and ``self._rule.where_tree`` at each evaluation): every case here raised
``KeyError`` from ``_Evaluation._selectors``.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md (release, MISSED: "Two
  threads validating at once in a cold process crash the installed code")
- rwa_filer.boe.catalogue._keep_first — the parse-once half
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T02, ref, rule
from pack_builders import build_pack, build_return
from rwa_filer.boe import engine
from rwa_filer.boe.catalogue import Rule
from rwa_filer.boe.engine import STATUS_FAIL, Accuracy, evaluate_rules, trace_rules
from rwa_filer.boe.grammar import parse_expression, parse_join, parse_scope, references
from rwa_filer.model import DECIMALS_EXACT

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.boe.engine import CellAddress, CellFact, Evaluation, Failure
    from rwa_filer.boe.grammar import JoinEquality, JoinKey, Node, ScopeGroup
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
#: Row 0010 equals row 0020 on each sheet, where row 0010 is positive: both
#: trees read cells, so a lookup by a node of either can miss.
EXPRESSION = f"{ref(T02, '0010')} i= {ref(T02, '0020')}"
WHERE = f"{ref(T02, '0010')} > 0"

#: What one evaluation of the rule found: (satisfied, failures, unsatisfied),
#: every traced evaluation, and every reported cell the trace read.
_Run = tuple[tuple[int, list["Failure"], int], list["Evaluation"], dict["CellAddress", "CellFact"]]


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


@pytest.fixture
def broken_once() -> CanonicalReturn:
    """Sheet 0001 breaks the rule (10 against 20); sheet 0002 meets it (10 and 10)."""
    rows = [
        ("0001", "0010", 10.0),
        ("0001", "0020", 20.0),
        ("0002", "0010", 10.0),
        ("0002", "0020", 10.0),
    ]
    frame = pl.DataFrame(
        [(T02, sheet, None, row, "0010", value, None, None) for sheet, row, value in rows],
        schema={
            "table": pl.String,
            "sheet": pl.String,
            "open_key": pl.String,
            "row": pl.String,
            "column": pl.String,
            "value": pl.Float64,
            "text_value": pl.String,
            "decimals": pl.Int64,
        },
        orient="row",
    )
    return build_return(frame)


@pytest.mark.parametrize(
    ("part", "text"),
    [
        pytest.param("tree", EXPRESSION, id="expression"),
        pytest.param("where_tree", WHERE, id="where"),
    ],
)
def test_an_evaluation_reads_the_tree_it_was_built_from_after_the_rule_is_given_another(
    pack: TaxonomyPack, broken_once: CanonicalReturn, part: str, text: str
) -> None:
    # Arrange - the same run on a rule left alone, then the rule's tree replaced
    # between building the evaluation and running it.
    expected = _run(_rule(), pack, broken_once)
    swapped = _rule()
    store = engine._Store(broken_once, pack, EXACT)
    cells: dict[CellAddress, CellFact] = {}
    evaluation = engine._Evaluation(swapped, store, cells)
    kept = swapped.__dict__[part]
    swapped.__dict__[part] = parse_expression(text)

    # Adequacy: the new tree reads as the old one, and is made of other nodes,
    # so a lookup by one of its references cannot find the old one's selector.
    replacement = swapped.__dict__[part]
    assert replacement == kept
    assert {id(node) for node in references(replacement)}.isdisjoint(
        id(node) for node in references(kept)
    ), "the fresh parse shares reference nodes with the kept tree - replacing it proves nothing"
    assert expected[0][2] == 1, "the rule must break once, so its failure is reported and traced"

    # Act
    trace: list[Evaluation] = []
    found = (evaluation.run(trace, None), trace, cells)

    # Assert
    assert found == expected


def test_a_rule_parsed_afresh_at_every_read_is_evaluated_and_traced_as_the_rule_itself(
    pack: TaxonomyPack, broken_once: CanonicalReturn
) -> None:
    # Arrange
    plain = _rule()
    fresh = _Reparsing(**{field.name: getattr(plain, field.name) for field in fields(plain)})

    # Adequacy: two reads of the rule's tree give equal trees, never one tree.
    first_read, second_read = fresh.tree, fresh.tree
    assert first_read == second_read
    assert first_read is not second_read
    assert fresh.where_tree is not fresh.where_tree

    # Act
    evaluated = evaluate_rules(broken_once, pack, [fresh], accuracy=EXACT)
    traced = trace_rules(broken_once, pack, [fresh], accuracy=EXACT, max_failures=None)

    # Assert
    assert [result.status for result in evaluated] == [STATUS_FAIL]
    assert evaluated == evaluate_rules(broken_once, pack, [plain], accuracy=EXACT)
    assert traced == trace_rules(broken_once, pack, [plain], accuracy=EXACT, max_failures=None)


# =============================================================================
# Helpers
# =============================================================================


class _Reparsing(Rule):
    """A rule whose parts are parsed again on every read: what an unlocked cache can hand out."""

    @property
    def tree(self) -> Node:
        return parse_expression(self.expression)

    @property
    def where_tree(self) -> Node | None:
        return parse_expression(self.where) if self.where else None

    @property
    def scope_groups(self) -> tuple[ScopeGroup, ...]:
        return parse_scope(self.scope or "")

    @property
    def joins(self) -> tuple[JoinKey | JoinEquality, ...]:
        return parse_join(self.join or "")


def _rule() -> Rule:
    """The rule under test, newly built: nothing parsed or kept on it yet."""
    return rule("kept_trees", EXPRESSION, tables=(T02,), where=WHERE)


def _run(subject: Rule, pack: TaxonomyPack, ret: CanonicalReturn) -> _Run:
    """One evaluation of ``subject`` over ``ret``, traced, keeping every failure."""
    cells: dict[CellAddress, CellFact] = {}
    trace: list[Evaluation] = []
    evaluation = engine._Evaluation(subject, engine._Store(ret, pack, EXACT), cells)
    return evaluation.run(trace, None), trace, cells
