"""
One look-up per place — the engine's cell memo and kept operands, held to fresh work.

Pipeline position:
    engine_corpus (open axes, open rows, cells with no member, where clauses,
        conditionals, defaults, division)
        ->  boe.engine.evaluate_rules / trace_rules, with ``_Evaluation`` watched

Key responsibilities:
- FRESHNESS: every cell ``_Evaluation._cell`` answers with — kept from earlier
  at this place, or not — is the cell a fresh ``_Evaluation._locate`` finds at
  the place it was asked about. Binding, evaluating, tracing each side and
  describing a failure all ask for the same cell at one place, so it is looked
  up once and kept until ``run`` moves to the next place.
- COUNT: ``_locate`` runs at most once per (evaluation, selector, place), in
  evaluation and in trace mode. NEVER the only guard: a memo that is never
  emptied looks up LESS and passes any count; only freshness sees it.
- KEPT OPERANDS: for every traced evaluation of a rule that is one comparison,
  the two values the trace states (``left_value`` / ``right_value``) equal each
  side evaluated afresh at that place. The trace takes them from the comparison
  the verdict made instead of evaluating each side again.

These name private parts of the engine on purpose: they guard a convention —
"one place per iteration of ``run``" — that no output-level test can tell from
a memo that is right only by luck, and a later change that evaluates part of a
rule at another place inside one evaluation must fail here, loudly.

Observed red before it was trusted (2026-11-22, one mutant at a time; the
mutant harness is in the X2 report): the memo never emptied between places
(freshness red; the count stays green, as said above); the memo off (count
red); the two kept operands swapped, kept only at the first evaluation, or
kept from the first comparison run rather than the rule's own (kept-operands
red).

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — engine-01, trace-01,
  rulings R2 / R3
- .claude/LESSONS.md C11 (assert the fixture's adequacy), C12 (a green probe
  needs evidence)
"""

from __future__ import annotations

from collections import Counter
from functools import cache
from typing import TYPE_CHECKING

import pytest

from engine_corpus import MODULE, build_corpus, corpus_release, corpus_rulebook
from rwa_filer.boe import engine
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS, evaluate_rules, trace_rules
from rwa_filer.boe.grammar import Binary

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.grammar import Node

#: A cell's key in a table, as the engine gives it: (sheet, member, row, column).
CellKey = tuple[str | None, str | None, str, str]
#: Evaluated rules the corpus must hold for the guards to see their paths.
WHERE_RULE = "corpus_where"
DIVISION_RULE = "corpus_idivide"


def test_every_cell_the_engine_answers_with_is_the_one_a_fresh_look_up_finds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over a traced corpus with open axes and open rows, no answer is a stale one."""
    # Arrange
    answers: list[tuple[engine._Selector, CellKey | None, CellKey | None]] = []
    looked_up = [0]
    cell, locate = engine._Evaluation._cell, engine._Evaluation._locate

    def checked(
        self: engine._Evaluation, selector: engine._Selector, env: Mapping[str, str]
    ) -> CellKey | None:
        answer = cell(self, selector, env)
        answers.append((selector, answer, locate(self, selector, env)))
        return answer

    def counted(
        self: engine._Evaluation, selector: engine._Selector, env: Mapping[str, str]
    ) -> CellKey | None:
        looked_up[0] += 1
        return locate(self, selector, env)

    monkeypatch.setattr(engine._Evaluation, "_cell", checked)
    monkeypatch.setattr(engine._Evaluation, "_locate", counted)

    # Act
    results = _traced_corpus()

    # Assert - adequacy first: the memo answered, on open rows and an open
    # axis, and a where clause was evaluated (LESSONS C11).
    assert len(answers) > looked_up[0] > 0, "no answer came from the memo - nothing is tested"
    found = [selector for selector, answer, _fresh in answers if answer is not None]
    assert any(selector.table.open_rows for selector in found), "no cell of an open-row table read"
    assert any(selector.table.open_axis is not None for selector in found), "no open-axis cell read"
    assert results[WHERE_RULE] in (STATUS_PASS, STATUS_FAIL), "the where clause was not evaluated"
    stale = [(answer, fresh) for _selector, answer, fresh in answers if answer != fresh]
    assert not stale, (
        f"{len(stale)} of {len(answers)} cells the engine read were not the cell at the place "
        f"asked about, e.g. {stale[:3]} - a cell kept from another place was answered with"
    )


@pytest.mark.parametrize("tracing", [False, True], ids=["evaluate", "trace"])
def test_a_cell_is_looked_up_at_most_once_per_selector_and_place(
    monkeypatch: pytest.MonkeyPatch, *, tracing: bool
) -> None:
    """Binding, evaluating, tracing and describing a failure share one look-up per place."""
    # Arrange
    counts: Counter[tuple[int, int, tuple[tuple[str, str], ...]]] = Counter()
    # Kept alive, so no id() is reused for another evaluation or selector.
    alive: list[tuple[engine._Evaluation, engine._Selector]] = []
    asked = [0]
    cell, locate = engine._Evaluation._cell, engine._Evaluation._locate

    def asking(
        self: engine._Evaluation, selector: engine._Selector, env: Mapping[str, str]
    ) -> CellKey | None:
        asked[0] += 1
        return cell(self, selector, env)

    def counting(
        self: engine._Evaluation, selector: engine._Selector, env: Mapping[str, str]
    ) -> CellKey | None:
        alive.append((self, selector))
        counts[(id(self), id(selector), tuple(sorted(env.items())))] += 1
        return locate(self, selector, env)

    monkeypatch.setattr(engine._Evaluation, "_cell", asking)
    monkeypatch.setattr(engine._Evaluation, "_locate", counting)

    # Act
    pack = corpus_release().pack
    for item in build_corpus().values():
        run = trace_rules if tracing else evaluate_rules
        run(item.ret, pack, _rules(), accuracy=item.accuracy)

    # Assert - adequacy: the same cell is asked for more than once at a place,
    # memo or no memo, so sharing the look-up is something to test.
    assert asked[0] > len(counts) > 0, "no cell was asked for twice at a place - nothing is tested"
    repeated = {key: count for key, count in counts.items() if count > 1}
    assert not repeated, (
        f"{len(repeated)} (evaluation, selector, place) were looked up more than once, "
        f"up to {max(repeated.values())} times - the look-up is no longer shared at a place"
    )


def test_each_side_s_value_in_a_trace_is_that_side_evaluated_afresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``left_value`` / ``right_value`` are the values compared, side by side, place by place."""
    # Arrange
    checked: list[tuple[str, tuple[object, object], tuple[object, object]]] = []
    defaulted: set[str] = set()
    traced = engine._Evaluation._traced

    def spying(
        self: engine._Evaluation,
        env: tuple[tuple[str, str], ...],
        *,
        holds: bool,
        comparisons: tuple[engine.Comparison, ...] = (),
    ) -> engine.Evaluation:
        evaluation = traced(self, env, holds=holds, comparisons=comparisons)
        tree = self._tree
        if isinstance(tree, Binary) and tree.is_comparison:
            values = dict(env)
            fresh = (_figure(self, tree.left, values), _figure(self, tree.right, values))
            checked.append(
                (evaluation.rule_id, (evaluation.left_value, evaluation.right_value), fresh)
            )
            if any(not address.reported for address in (*evaluation.left, *evaluation.right)):
                defaulted.add(evaluation.rule_id)
        return evaluation

    monkeypatch.setattr(engine._Evaluation, "_traced", spying)

    # Act
    _traced_corpus()

    # Assert - adequacy: the checked evaluations include a side read at its
    # default, a side that is no number, a quotient, a where clause, and rules
    # whose values differ between places (so a value kept from another place
    # would show).
    rules = {rule_id for rule_id, _kept, _fresh in checked}
    assert {WHERE_RULE, DIVISION_RULE} <= rules, sorted({WHERE_RULE, DIVISION_RULE} - rules)
    assert defaulted, "no traced side read a cell at its default"
    assert any(None in kept for _rule, kept, _fresh in checked), "every side was a number"
    varying = Counter(rule_id for rule_id, kept in {(r, k) for r, k, _f in checked})
    assert sum(count > 1 for count in varying.values()) > 10, "too few rules vary by place"
    wrong = [(rule_id, kept, fresh) for rule_id, kept, fresh in checked if kept != fresh]
    assert not wrong, (
        f"{len(wrong)} of {len(checked)} traced evaluations state side values that are not "
        f"the sides evaluated at their place, e.g. {wrong[:3]}"
    )


# =============================================================================
# Helpers
# =============================================================================


@cache
def _rules() -> tuple[Rule, ...]:
    return corpus_rulebook().enforced(MODULE)


def _traced_corpus() -> dict[str, str]:
    """Trace every corpus return; each rule's status where it was evaluated anywhere."""
    pack = corpus_release().pack
    statuses: dict[str, str] = {}
    for item in build_corpus().values():
        for result in trace_rules(item.ret, pack, _rules(), accuracy=item.accuracy).results:
            if result.status in (STATUS_PASS, STATUS_FAIL) or result.rule_id not in statuses:
                statuses[result.rule_id] = result.status
    return statuses


def _figure(evaluation: engine._Evaluation, node: Node, env: Mapping[str, str]) -> float | None:
    """``node`` evaluated again at ``env``, as a number — how the trace once stated each side."""
    try:
        amount = engine._amount(evaluation._value(node, env))
    except (engine._NotBound, ZeroDivisionError):
        return None
    return None if amount is None else float(amount.value)
