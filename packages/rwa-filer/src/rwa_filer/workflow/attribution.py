"""
Attributing breaks — which part of a return's detail each broken rule comes from.

Pipeline position:
    ReturnValidation of the summed return  +  ReturnDetail (the rows it was summed from)
        ->  attribute  ->  Attribution
        ->  the dashboard's Investigate page and cell panel, ``rwa-filer validate --breakdown``

Key responsibilities:
- Run each rule the return breaks again on every member's rows alone — one
  business unit, one source system — and set each member's figures beside the
  return's. A member that breaks the rule on its own figures is where to look;
  one that meets it is not.
- Say how much of each break the members account for. For a rule that is a
  sum or a difference, the members' gaps add up to the return's. What they do
  not account for — an override drafted on the summed figure, a rule that is
  not a plain sum — is its own amount (``TracedBreak.unexplained``), never
  spread over the members.
- Find what the total hides: an evaluation that holds in the return but
  breaks on one member's figures alone, usually two figures wrong in opposite
  directions. Only where every reported cell the evaluation reads is an
  amount: a rule over a percentage or a count cannot be judged on part of the
  rows, and flagging those would flag every return.
- Never change a verdict. The return's verdict is the validation's; this only
  explains it.

How the work is kept small: only the rules that matter are run again — the
broken ones, plus those that hold when the search for hidden breaks is asked
for, or only the ones a caller names — and every run goes through the engine's
indexed trace. One-shot callers index one member at a time. The dashboard can
prepare those indexes once and trace further rules as cells are selected.

References:
- rwa_filer.boe.engine.trace_rules — the evaluations, and the cells each read
- rwa_filer.readers.detail — the rows and their members
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe import grammar
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS, _Store, _trace_indexed, evaluation_place
from rwa_filer.model import CanonicalReturn
from rwa_filer.progress import PHASE_BREAKDOWN, Progress, notify
from rwa_filer.readers.detail import SUMMABLE_TYPE, address, cell_data_types

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import CellAddress, Evaluation
    from rwa_filer.progress import ProgressCallback
    from rwa_filer.readers.detail import Cell, Member, ReturnDetail
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.returns import ReturnValidation, RuleReport
    from rwa_filer.validate.review import ReviewFilter

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: How a member left empty is named, after the column: "no business_unit".
NO_MEMBER_PREFIX: Final = "no "
#: Below this, a gap is rounding dust in a sum of floats, not an amount.
_DUST: Final = 1e-6

#: An evaluation's identity in two returns: its rule and its place.
type _Key = tuple[str, tuple[tuple[str, str], ...]]


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class Standing:
    """One member's figures for one evaluation, on its rows alone.

    Attributes:
        member: The member; ``None`` for the rows that leave the column empty.
        evaluated: Whether the rule was evaluated there on the member's rows.
            A member with no figure in any cell the rule reads is not: it has
            no part in the break.
        holds: Whether the evaluation held on the member's rows; ``None``
            when it was not evaluated.
        left / right: The two sides of the rule's comparison on the member's
            rows, where the rule is one comparison of two numbers.
    """

    member: Member
    evaluated: bool
    holds: bool | None
    left: float | None = None
    right: float | None = None

    @property
    def breaks(self) -> bool:
        """Whether the member breaks the rule on its own figures."""
        return self.evaluated and self.holds is False

    @property
    def gap(self) -> float | None:
        """``left - right``; 0 for a member not evaluated; ``None`` where there is no number."""
        if not self.evaluated:
            return 0.0
        return _gap(self.left, self.right)


@dataclass(frozen=True)
class TracedBreak:
    """One evaluation of the return, and every member's standing in it.

    Attributes:
        rule_id: The rule.
        severity: ``ERROR`` or ``WARNING``, as the return's validation ran it.
        place: The evaluation's place, ``(axis, value)`` pairs.
        relation: The comparison at the top of the rule; ``None`` for a rule
            that is not one comparison.
        holds: Whether it held in the return.
        left / right: The return's two sides, where they are numbers.
        cells: The reported cells of the return it read.
        standings: Each member's standing, in member order.
        left_cells / right_cells: The cells each side of the comparison reads,
            reported or not, in rule order; a rule that is not one comparison
            has every cell on the left.
    """

    rule_id: str
    severity: str
    place: tuple[tuple[str, str], ...]
    relation: str | None
    holds: bool
    left: float | None
    right: float | None
    cells: tuple[Cell, ...]
    standings: tuple[Standing, ...]
    left_cells: tuple[Cell, ...] = ()
    right_cells: tuple[Cell, ...] = ()
    additive: bool = True

    @property
    def gap(self) -> float | None:
        """The return's ``left - right``; ``None`` where there is no number."""
        return _gap(self.left, self.right)

    @property
    def breaking(self) -> tuple[Standing, ...]:
        """The members that break the rule here on their own figures."""
        return tuple(standing for standing in self.standings if standing.breaks)

    @property
    def explained(self) -> float | None:
        """The members' gaps added up; ``None`` where a member's has no number."""
        if not self.additive:
            return None
        gaps = [standing.gap for standing in self.standings]
        if any(gap is None for gap in gaps):
            return None
        return math.fsum(gap for gap in gaps if gap is not None)

    @property
    def unexplained(self) -> float | None:
        """The part of the return's gap no member accounts for; ``None`` without numbers.

        Zero for a rule that is a sum or a difference of the detail's figures.
        Not zero where an override changed a figure the rule reads, or where
        the rule is not a plain sum (an absolute value, a minimum).
        """
        gap, explained = self.gap, self.explained
        if gap is None or explained is None:
            return None
        remainder = gap - explained
        return 0.0 if abs(remainder) < _DUST * max(1.0, abs(gap)) else remainder

    @property
    def place_text(self) -> str:
        """The place as the rule pages write it: ``row 0070, sheet 0008``."""
        return place_text(self.place)

    def reads(self, cell: Cell) -> bool:
        """Whether the evaluation read ``cell`` as a reported figure."""
        return cell in self.cells

    def standing(self, member: Member) -> Standing | None:
        """``member``'s standing here, if it is a member."""
        return next((item for item in self.standings if item.member == member), None)


@dataclass(frozen=True)
class Attribution:
    """A return's breaks, each set against every member of one breakdown column.

    Attributes:
        dimension: The breakdown column.
        members: Its members, in the detail's order.
        broken: Every evaluation that breaks in the return, in rule order then
            place order, of the rules run.
        hidden: Evaluations that hold in the return and break on at least one
            member's figures, over amounts only; empty unless searched for.
        searched_hidden: Whether ``hidden`` was looked for.
        rules_run: How many rules were run again.
    """

    dimension: str
    members: tuple[Member, ...]
    broken: tuple[TracedBreak, ...]
    hidden: tuple[TracedBreak, ...] = ()
    searched_hidden: bool = False
    rules_run: int = 0
    group_code: str | None = None

    def reviewed(self, validation: ReturnValidation, review: ReviewFilter) -> Attribution:
        """Select breaks for display while retaining the full attribution for evidence."""
        report = validation.report
        if not review.active or report is None:
            return self
        # Both paths record occurrences in evaluation order. Display labels can repeat.
        hidden = {
            (result.rule_id, index)
            for result in report.results
            if result.status == STATUS_FAIL and not review.hides_severity(result.severity)
            for index, failure in enumerate(result.failures)
            if review.hides(result.severity, failure)
        }
        return replace(
            self,
            broken=tuple(
                item
                for rule_id, occurrences in _by_rule(self.broken)
                for index, item in enumerate(occurrences)
                if not review.hides_severity(item.severity) and (rule_id, index) not in hidden
            ),
            hidden=tuple(item for item in self.hidden if not review.hides_severity(item.severity)),
        )

    @property
    def traced(self) -> int:
        """How many of the broken evaluations break on at least one member's figures."""
        return sum(1 for item in self.broken if item.breaking)

    @property
    def breaking_members(self) -> tuple[Member, ...]:
        """The members that break at least one broken evaluation, in member order."""
        found = {standing.member for item in self.broken for standing in item.breaking}
        return tuple(member for member in self.members if member in found)

    @property
    def hiding_members(self) -> tuple[Member, ...]:
        """The members behind at least one hidden break, in member order."""
        found = {standing.member for item in self.hidden for standing in item.breaking}
        return tuple(member for member in self.members if member in found)

    def member_breaks(self, member: Member) -> tuple[TracedBreak, ...]:
        """The broken evaluations ``member`` breaks on its own figures."""
        return tuple(item for item in self.broken if _breaks(item, member))

    def member_hidden(self, member: Member) -> tuple[TracedBreak, ...]:
        """The hidden breaks ``member`` is behind."""
        return tuple(item for item in self.hidden if _breaks(item, member))

    def reading(self, cell: Cell, rule_id: str) -> tuple[TracedBreak, ...]:
        """The broken evaluations of ``rule_id`` that read ``cell``."""
        return tuple(item for item in self.broken if item.rule_id == rule_id and item.reads(cell))

    def label(self, member: Member) -> str:
        """A member as a person reads it; the rows that leave the column empty, named so."""
        return member_label(self.dimension, member)


def attribute(  # noqa: PLR0913 - the return, its detail, and how much of it to run
    ret: CanonicalReturn,
    validation: ReturnValidation,
    detail: ReturnDetail,
    dimension: str,
    *,
    rule_ids: Collection[str] | None = None,
    search_hidden: bool | None = None,
    progress: ProgressCallback | None = None,
) -> Attribution:
    """Set every break of ``ret`` against each member of ``dimension``.

    Args:
        ret: The return the validation is of — the summed return, with any
            drafted overrides applied.
        validation: Its validation: the rules it ran, their severities, the
            taxonomy and the accuracy.
        detail: The rows ``ret`` was summed from.
        dimension: The breakdown column to attribute by.
        rule_ids: Run only these rules; ``None`` for every rule the search
            needs.
        search_hidden: Also run the rules that hold, to find the breaks the
            total hides. Costs one run of each rule that held, per member.
        progress: Told how many of the return and its members are done
            (``PHASE_BREAKDOWN``).

    Raises:
        KeyError: ``dimension`` is not one of the detail's breakdown columns.
    """
    base, rules, severity = _plan(validation, detail, dimension, rule_ids, search_hidden)
    stores = _stores(ret, validation, detail, base)
    return _attribute_rules(base, validation, rules, severity, stores, progress)


class PreparedAttribution:
    """Reusable inputs and completed rule results for one validated return and column."""

    def __init__(
        self,
        ret: CanonicalReturn,
        validation: ReturnValidation,
        detail: ReturnDetail,
        dimension: str,
    ) -> None:
        self._base, self._rules, self._severity = _plan(validation, detail, dimension, None, None)
        self._validation = validation
        self._stores = tuple(_stores(ret, validation, detail, self._base)) if self._rules else ()
        self._results: dict[str, Attribution] = {}
        self._lock = threading.Lock()

    def select(
        self, rule_ids: Collection[str] | None, progress: ProgressCallback | None = None
    ) -> Attribution:
        """Trace missing rules together, then assemble completed results in publisher order."""
        rules = [r for r in self._rules if rule_ids is None or r.rule_id in rule_ids]
        # Finished rules are immutable and never removed. Reading them need not wait for
        # Investigate to finish a different batch on the same stores.
        if any(rule.rule_id not in self._results for rule in rules):
            self._trace_missing(rules, progress)
        parts = [self._results[r.rule_id] for r in rules]
        return replace(
            self._base,
            broken=tuple(item for part in parts for item in part.broken),
            hidden=tuple(item for part in parts for item in part.hidden),
            rules_run=len(parts),
        )

    def _trace_missing(self, rules: list[Rule], progress: ProgressCallback | None) -> None:
        # Only one trace uses these stores' lazy address indexes at once. Recheck what
        # is missing after taking the lock: another cell may just have traced it.
        with self._lock:
            missing = [rule for rule in rules if rule.rule_id not in self._results]
            if not missing:
                return
            batch = _attribute_rules(
                self._base, self._validation, missing, self._severity, self._stores, progress
            )
            broken, hidden = dict(_by_rule(batch.broken)), dict(_by_rule(batch.hidden))
            self._results.update(
                {
                    rule.rule_id: replace(
                        self._base,
                        broken=tuple(broken.get(rule.rule_id, ())),
                        hidden=tuple(hidden.get(rule.rule_id, ())),
                        rules_run=1,
                    )
                    for rule in missing
                }
            )


# =============================================================================
# Supporting public functions
# =============================================================================


def member_label(dimension: str, member: Member) -> str:
    """``Asset Finance``; ``no business_unit`` for the rows that leave the column empty."""
    return member if member is not None else f"{NO_MEMBER_PREFIX}{dimension}"


def place_text(place: tuple[tuple[str, str], ...]) -> str:
    """An evaluation's place as the rule pages write it: ``row 0070, sheet 0008``.

    Empty for an evaluation over the whole template.
    """
    return evaluation_place(place)


def amount_text(value: float | None, *, signed: bool = False) -> str:
    """A figure as the pages write it: ``6,000,000``; ``+250,000`` when ``signed``."""
    if value is None:
        return "—"
    rounded = round(value)
    text = f"{rounded:,.0f}" if abs(value - rounded) < _DUST else f"{value:,.2f}"
    return f"+{text}" if signed and value > 0 else text


def describe(attribution: Attribution, *, labels: Mapping[str, str] | None = None) -> list[str]:
    """The attribution as lines of text, for ``rwa-filer validate --breakdown``.

    One line per broken rule naming the members that break it, then the
    breaks the total hides. ``labels`` gives each rule's published label.
    """
    labels = labels or {}
    dimension = attribution.dimension
    lines = [
        f"Where the breaks come from, by {dimension}: {attribution.traced} of "
        f"{len(attribution.broken)} broken evaluation(s) break on one {dimension}'s "
        f"figures alone ({len(attribution.members)} member(s), "
        f"{attribution.rules_run} rule(s) run again)."
    ]
    for rule_id, items in _by_rule(attribution.broken):
        lines.append(f"  {rule_id} ({_severity(items[0].severity)}), {len(items)} break(s)")
        if label := labels.get(rule_id):
            lines.append(f"    {label}")
        lines.extend(f"    {text}" for text in _members_line(attribution, items))
        lines.extend(_incomplete_lines(attribution, items))
        unexplained = [item.unexplained for item in items if item.unexplained]
        if unexplained:
            lines.append(
                f"    not accounted for by any {dimension}: "
                f"{amount_text(max(unexplained, key=abs), signed=True)}"
                + (" (largest)" if len(set(unexplained)) > 1 else "")
            )
    if attribution.searched_hidden:
        lines.append(
            f"Hold in the return, break on one {dimension}'s figures alone: "
            f"{len(attribution.hidden)} evaluation(s)."
        )
        for rule_id, items in _by_rule(attribution.hidden):
            lines.append(f"  {rule_id} ({_severity(items[0].severity)}), {len(items)} place(s)")
            lines.extend(f"    {text}" for text in _members_line(attribution, items))
    return lines


def as_record(attribution: Attribution) -> dict[str, Any]:
    """A JSON-ready record of the attribution, for a report."""

    def standing(item: Standing) -> dict[str, Any]:
        return {
            "member": item.member,
            "evaluated": item.evaluated,
            "holds": item.holds,
            "left": item.left,
            "right": item.right,
            "gap": item.gap if item.evaluated or attribution.group_code is None else None,
        }

    def traced(item: TracedBreak) -> dict[str, Any]:
        return {
            "rule_id": item.rule_id,
            "severity": item.severity,
            "place": item.place_text,
            "relation": item.relation,
            "left": item.left,
            "right": item.right,
            "gap": item.gap,
            "unexplained": item.unexplained,
            "cells": [address(cell) for cell in item.cells],
            "breaking": [member.member for member in item.breaking],
            "members": [standing(member) for member in item.standings],
        }

    return {
        "dimension": attribution.dimension,
        "members": list(attribution.members),
        "rules_run": attribution.rules_run,
        "broken": [traced(item) for item in attribution.broken],
        "hidden": [traced(item) for item in attribution.hidden]
        if attribution.searched_hidden
        else None,
    }


# =============================================================================
# Private helpers
# =============================================================================


def _plan(
    validation: ReturnValidation,
    detail: ReturnDetail,
    dimension: str,
    rule_ids: Collection[str] | None,
    search_hidden: bool | None,
) -> tuple[Attribution, list[Rule], dict[str, str]]:
    base = Attribution(
        dimension, detail.members(dimension), broken=(), group_code=detail.spec.group_code
    )
    report, rulebook = validation.report, validation.rulebook
    if report is None or rulebook is None:
        return base, [], {}
    if search_hidden is None:
        search_hidden = detail.spec.group_code is None
    severity = _rule_severities(report, rule_ids, search_hidden)
    enforced = rulebook.enforced(validation.pack.info.module)
    rules = [rule for rule in enforced if rule.rule_id in severity]
    return replace(base, searched_hidden=search_hidden), rules, severity


def _stores(
    ret: CanonicalReturn, validation: ReturnValidation, detail: ReturnDetail, base: Attribution
) -> Iterator[_Store]:
    yield _Store(ret, validation.pack, validation.accuracy)
    for member in base.members:
        facts = detail.member_facts(base.dimension, member)
        yield _Store(
            CanonicalReturn.from_frame(ret.header, facts), validation.pack, validation.accuracy
        )


def _attribute_rules(  # noqa: PLR0913 - one batch over the return and its members
    base: Attribution,
    validation: ReturnValidation,
    rules: list[Rule],
    severity: Mapping[str, str],
    stores: Iterable[_Store],
    progress: ProgressCallback | None,
) -> Attribution:
    if not rules:
        return base
    dimension, members = base.dimension, base.members
    steps = len(members) + 1
    notify(progress, Progress(PHASE_BREAKDOWN, 0, steps, subject="the return"))
    indexed = iter(stores)
    whole = _evaluations(next(indexed), rules)
    group_mode = base.group_code is not None
    additive_checks = _additive_checks(rules, whole, validation.pack) if group_mode else set()
    by_member: list[dict[_Key, Evaluation]] = []
    for done, (member, store) in enumerate(zip(members, indexed, strict=True), start=1):
        by_member.append(_evaluations(store, rules))
        notify(
            progress,
            Progress(PHASE_BREAKDOWN, done, steps, subject=member_label(dimension, member)),
        )

    broken: list[TracedBreak] = []
    candidates: list[tuple[Evaluation, tuple[Standing, ...]]] = []
    for key, evaluation in whole.items():
        required = _reported(evaluation.cells) if group_mode else None
        standings = tuple(
            _standing(member, found.get(key), required)
            for member, found in zip(members, by_member, strict=True)
        )
        if not evaluation.holds:
            broken.append(
                _traced(
                    evaluation,
                    severity[evaluation.rule_id],
                    standings,
                    additive=not group_mode or key in additive_checks,
                )
            )
        elif base.searched_hidden and any(standing.breaks for standing in standings):
            candidates.append((evaluation, standings))

    hidden = _over_amounts(candidates, validation, severity)
    logger.info(
        "attributed %d break(s) by %s over %d member(s), %d rule(s) run; %d hidden",
        len(broken),
        dimension,
        len(members),
        len(rules),
        len(hidden),
    )
    return replace(base, broken=tuple(broken), hidden=hidden, rules_run=len(rules))


def _rule_severities(
    report: RuleReport, rule_ids: Collection[str] | None, search_hidden: bool
) -> dict[str, str]:
    """Select the rules to trace and retain their reported severities."""
    wanted = {STATUS_FAIL, STATUS_PASS} if search_hidden else {STATUS_FAIL}
    return {
        result.rule_id: result.severity
        for result in report.results
        if result.status in wanted and (rule_ids is None or result.rule_id in rule_ids)
    }


def _evaluations(store: _Store, rules: list[Rule]) -> dict[_Key, Evaluation]:
    """Every evaluation of the selected rules over these indexed facts, by rule and place."""
    trace = _trace_indexed(store, rules, max_failures=0)
    return {(item.rule_id, item.place): item for item in trace.evaluations}


def _standing(
    member: Member, evaluation: Evaluation | None, required: set[Cell] | None
) -> Standing:
    if evaluation is None or (
        required is not None
        and (not required or not required.issubset(_reported(evaluation.cells)))
    ):
        return Standing(member=member, evaluated=False, holds=None)
    return Standing(
        member=member,
        evaluated=True,
        holds=evaluation.holds,
        left=evaluation.left_value,
        right=evaluation.right_value,
    )


def _additive_checks(
    rules: list[Rule], whole: dict[_Key, Evaluation], pack: TaxonomyPack
) -> set[_Key]:
    """Group breaks whose reported inputs and rule both permit summing unit gaps."""
    additive_rules = {rule.rule_id for rule in rules if _additive_rule(rule.expression)}
    cells = {
        key: _reported(evaluation.cells)
        for key, evaluation in whole.items()
        if not evaluation.holds and evaluation.rule_id in additive_rules
    }
    types = cell_data_types(pack, {cell for required in cells.values() for cell in required})
    return {
        key
        for key, required in cells.items()
        if required and all(types.get(cell) == SUMMABLE_TYPE for cell in required)
    }


def _additive_rule(expression: str) -> bool:
    """Only sum unit gaps for comparisons of sums and differences of amounts."""

    def additive(node: grammar.Node) -> bool:
        match node:
            case grammar.Reference():
                return True
            case grammar.Number(value=0):
                return True
            case grammar.Negate(operand):
                return additive(operand)
            case grammar.Binary(operator="+" | "-", left=left, right=right):
                return additive(left) and additive(right)
            case grammar.Call(name="sum" | "isum", arguments=args):
                return all(additive(arg) for arg in args)
            case _:
                return False

    try:
        tree = grammar.parse_expression(expression)
    except grammar.GrammarError:
        return False
    return (
        isinstance(tree, grammar.Binary)
        and tree.operator in grammar.COMPARISONS
        and (additive(tree.left) and additive(tree.right))
    )


def _traced(
    evaluation: Evaluation, severity: str, standings: tuple[Standing, ...], *, additive: bool = True
) -> TracedBreak:
    return TracedBreak(
        rule_id=evaluation.rule_id,
        severity=severity,
        place=evaluation.place,
        relation=evaluation.relation,
        holds=evaluation.holds,
        left=evaluation.left_value,
        right=evaluation.right_value,
        cells=tuple(sorted(_reported(evaluation.cells), key=_sort_key)),
        standings=standings,
        additive=additive,
        left_cells=tuple(_coordinates(cell) for cell in evaluation.left),
        right_cells=tuple(_coordinates(cell) for cell in evaluation.right),
    )


def _over_amounts(
    candidates: list[tuple[Evaluation, tuple[Standing, ...]]],
    validation: ReturnValidation,
    severity: Mapping[str, str],
) -> tuple[TracedBreak, ...]:
    """The candidates whose every reported cell is an amount, as hidden breaks."""
    if not candidates:
        return ()
    cells = {cell for evaluation, _ in candidates for cell in _reported(evaluation.cells)}
    types = cell_data_types(validation.pack, cells)
    return tuple(
        _traced(evaluation, severity[evaluation.rule_id], standings)
        for evaluation, standings in candidates
        if all(types.get(cell) == SUMMABLE_TYPE for cell in _reported(evaluation.cells))
    )


def _reported(cells: Collection[CellAddress]) -> set[Cell]:
    return {_coordinates(cell) for cell in cells if cell.reported}


def _coordinates(cell: CellAddress) -> Cell:
    return (cell.table, cell.sheet, cell.open_key, cell.row, cell.column)


def _sort_key(cell: Cell) -> tuple[str, ...]:
    return tuple(part or "" for part in cell)


def _gap(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _breaks(item: TracedBreak, member: Member) -> bool:
    standing = item.standing(member)
    return standing is not None and standing.breaks


def _by_rule(items: tuple[TracedBreak, ...]) -> list[tuple[str, list[TracedBreak]]]:
    grouped: dict[str, list[TracedBreak]] = {}
    for item in items:
        grouped.setdefault(item.rule_id, []).append(item)
    return list(grouped.items())


def _incomplete_lines(attribution: Attribution, items: list[TracedBreak]) -> list[str]:
    if attribution.group_code is None:
        return []
    lines = []
    for member in attribution.members:
        incomplete = sum(1 for item in items if (s := item.standing(member)) and not s.evaluated)
        if incomplete:
            lines.append(
                f"    {attribution.label(member)}: insufficient detail for "
                f"{incomplete} of {len(items)} evaluation(s)"
            )
    return lines


def _members_line(attribution: Attribution, items: list[TracedBreak]) -> list[str]:
    """Each member that breaks ``items``: how many, and by how much."""
    found: list[str] = []
    for member in attribution.members:
        gaps = [
            standing.gap
            for item in items
            if (standing := item.standing(member)) is not None and standing.breaks
        ]
        if not gaps:
            continue
        numbers = [gap for gap in gaps if gap is not None]
        amount = ""
        if numbers:
            largest = max(numbers, key=abs)
            same = all(abs(gap - largest) < _DUST * max(1.0, abs(largest)) for gap in numbers)
            amount = f", out by {'' if same else 'up to '}{amount_text(largest, signed=True)}"
        found.append(f"{attribution.label(member)} breaks {_share(len(gaps), len(items))}{amount}")
    return found or [f"no single {attribution.dimension} breaks it on its own figures"]


def _severity(severity: str) -> str:
    return severity.capitalize()


def _share(part: int, whole: int) -> str:
    """``all 4``, ``both``, ``it`` or ``2 of 4``."""
    if part < whole:
        return f"{part} of {whole}"
    return {1: "it", 2: "both"}.get(whole, f"all {whole}")
