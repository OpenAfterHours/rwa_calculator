"""
Labels on a verdict — where a known issue with the published rule explains a result.

Pipeline position:
    boe.engine results (after validate.execution's deny list)
        + the release's publisher-issue register (boe.issues)
        + every unsatisfied evaluation of a rule an issue applies to only in part
        ->  label_results  ->  IssueNote per (rule, issue)
        ->  validate.returns (RuleReport.issue_notes, the finding's message)
        ->  validate.report / evidence / dash / the filing manifest

Key responsibilities:
- Never change a verdict. A label is words and an issue id beside a result:
  the status, severity, counts, finding code, blocking and every fingerprint
  are exactly what they are without the register.
- Label only the result an issue is about (see ``boe.issues`` for the effects):
  a FAIL for an issue that fails correct returns, a PASS for one that passes
  wrong ones, a rule not run for one whose rule never runs. A rule the Bank has
  deactivated at its gateway is told by the deny list, never by a label.
- Label only the rule the issue pinned: a rule whose fingerprint differs is
  another rule, and gets no label (a WARNING says so).
- Classify EVERY unsatisfied evaluation, not the few a result records, as
  inside or outside the issue's footprint, so a break the issue does not
  explain is never excused by it: "4 of 14 are where the published rule is
  known to be wrong; 10 are not, and are not explained by it".
- Word it one way for every surface (``IssueNote.sentence``).

References:
- rwa_filer.boe.issues — the register, its effects and footprints
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    REASON_NO_DATA,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
)
from rwa_filer.boe.issues import (
    ATTRIBUTION_POSSIBLE,
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_PASSES_WRONG_RETURNS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.boe.engine import Evaluation, RuleResult
    from rwa_filer.boe.issues import IssueRegister, IssueRule, PublisherIssue

logger = logging.getLogger(__name__)

#: The not-evaluated reasons an issue whose rule never runs labels: the formula
#: cannot fire, or nothing it reads is reported. Never ``deactivated_by_publisher``.
NEVER_RUNS_REASONS: Final = (REASON_CLOSED_BY_FORMULA, REASON_NO_DATA)

#: Where a reader finds the whole issue.
_COMMAND: Final = "rwa-filer rulebook issues"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class IssueNote:
    """One known issue's label on one rule's result.

    Attributes:
        rule_id: The rule.
        issue_id: The issue, e.g. ``PI-15a``.
        title: What is wrong, in one line.
        status: Where the issue stands with the Bank (``boe.issues.STATUSES``).
        status_text: The same, in words.
        effect: What the issue does to a result (``boe.issues.EFFECTS``).
        attribution: ``certain`` or ``possible`` (see ``boe.issues``).
        unsatisfied: The rule's unsatisfied evaluations.
        inside: Of those, the ones inside the issue's footprint; ``None`` for a
            label on a result that is not a break.
        outside: The rest; ``None`` likewise.
        fixed_in: The release the Bank fixed it in, where it has.
        sentence: The label, in the words every surface uses.
    """

    rule_id: str
    issue_id: str
    title: str
    status: str
    status_text: str
    effect: str
    attribution: str
    unsatisfied: int
    inside: int | None
    outside: int | None
    fixed_in: str | None
    sentence: str

    @property
    def explains_a_break(self) -> bool:
        """Whether some unsatisfied evaluation is inside the issue's footprint."""
        return bool(self.inside)


@dataclass(frozen=True)
class IssueTally:
    """One issue across a validation: the rules it labelled and the breaks it explains."""

    issue_id: str
    status: str
    effect: str
    rules: tuple[str, ...]
    breaks_inside: int
    breaks_outside: int

    def record(self) -> dict[str, Any]:
        return {
            "issue": self.issue_id,
            "status": self.status,
            "effect": self.effect,
            "rules": list(self.rules),
            "breaks_inside": self.breaks_inside,
            "breaks_outside": self.breaks_outside,
        }


def label_results(
    results: Iterable[RuleResult],
    rulebook: RuleBook,
    register: IssueRegister,
    module: str,
    *,
    evaluations: Iterable[Evaluation] | None,
) -> tuple[IssueNote, ...]:
    """The labels ``register`` puts on ``results``, in the results' order.

    Args:
        results: The results as the gateway runs them (after the deny list).
        rulebook: The rule book the results came from: each issue applies only
            to the rule it pinned, by fingerprint.
        register: The release's publisher-issue register.
        module: The return's module.
        evaluations: Every evaluation of each broken rule an issue applies to
            only in part (its footprint). ``None`` when none was traced: an
            issue with a footprint then classifies nothing as inside.
    """
    if not register.issues:
        return ()
    unsatisfied = _unsatisfied(evaluations)
    notes: list[IssueNote] = []
    for result in results:
        for issue in register.for_rule(module, result.rule_id):
            entry = issue.rule(module, result.rule_id)
            if entry is None or not _labels(issue, result):
                continue
            rule = rulebook.rule(result.rule_id)
            if rule is None or not entry.applies_to(rule, module):
                logger.warning(
                    "publisher issue %s pins %s at another fingerprint: not labelled",
                    issue.id,
                    result.rule_id,
                )
                continue
            notes.append(_note(issue, entry, result, unsatisfied.get(result.rule_id, ())))
    return tuple(notes)


def tally(notes: Iterable[IssueNote]) -> tuple[IssueTally, ...]:
    """The labels grouped by issue, in the order each issue was first met."""
    grouped: dict[str, list[IssueNote]] = {}
    for note in notes:
        grouped.setdefault(note.issue_id, []).append(note)
    return tuple(
        IssueTally(
            issue_id=issue_id,
            status=items[0].status,
            effect=items[0].effect,
            rules=tuple(sorted({item.rule_id for item in items})),
            breaks_inside=sum(item.inside or 0 for item in items),
            breaks_outside=sum(item.outside or 0 for item in items),
        )
        for issue_id, items in grouped.items()
    )


def needs_trace(results: Iterable[RuleResult], register: IssueRegister, module: str) -> set[str]:
    """The broken rules an issue applies to only in part: their breaks must be classified."""
    return {
        result.rule_id
        for result in results
        if result.status == STATUS_FAIL
        for issue in register.for_rule(module, result.rule_id)
        if issue.effect == EFFECT_FAILS_CORRECT_RETURNS
        and (entry := issue.rule(module, result.rule_id)) is not None
        and entry.footprint is not None
    }


def evaluation_issues(
    evaluation: Evaluation, notes: Iterable[IssueNote], register: IssueRegister, module: str
) -> tuple[str, ...] | None:
    """The issues whose footprint holds an unsatisfied evaluation of a labelled break.

    ``None`` when there is nothing to say: the evaluation held, or no issue
    labelled the rule's break. An empty tuple means no issue explains it.
    """
    breaks = [
        note for note in notes if note.rule_id == evaluation.rule_id and note.inside is not None
    ]
    if evaluation.holds or not breaks:
        return None
    cells = evaluation.cells
    return tuple(
        note.issue_id
        for note in breaks
        if (issue := register.issue(note.issue_id)) is not None
        and (entry := issue.rule(module, evaluation.rule_id)) is not None
        and entry.inside(cells)
    )


def note_record(note: IssueNote) -> dict[str, Any]:
    """The label as the report and the evidence record it."""
    return {
        "issue": note.issue_id,
        "title": note.title,
        "status": note.status,
        "status_text": note.status_text,
        "effect": note.effect,
        "attribution": note.attribution,
        "unsatisfied": note.unsatisfied,
        "breaks_inside": note.inside,
        "breaks_outside": note.outside,
        "fixed_in": note.fixed_in,
        "sentence": note.sentence,
    }


# =============================================================================
# Private helpers
# =============================================================================


def _labels(issue: PublisherIssue, result: RuleResult) -> bool:
    """Whether the issue's effect is about this result (see the module docstring)."""
    if not issue.labels:
        return False
    if issue.effect == EFFECT_FAILS_CORRECT_RETURNS:
        return result.status == STATUS_FAIL
    if issue.effect == EFFECT_PASSES_WRONG_RETURNS:
        return result.status == STATUS_PASS
    if issue.effect == EFFECT_NEVER_RUNS:
        return result.status == STATUS_NOT_EVALUATED and result.reason in NEVER_RUNS_REASONS
    return False


def _unsatisfied(evaluations: Iterable[Evaluation] | None) -> dict[str, list[Evaluation]]:
    found: dict[str, list[Evaluation]] = {}
    for evaluation in evaluations or ():
        if not evaluation.holds:
            found.setdefault(evaluation.rule_id, []).append(evaluation)
    return found


def _note(
    issue: PublisherIssue,
    entry: IssueRule,
    result: RuleResult,
    broken: Iterable[Evaluation],
) -> IssueNote:
    inside: int | None = None
    outside: int | None = None
    if result.status == STATUS_FAIL:
        if entry.footprint is None:
            inside = result.unsatisfied
        else:
            counted = Counter(entry.inside(evaluation.cells) for evaluation in broken)
            inside = counted[True]
            if inside + counted[False] != result.unsatisfied:
                logger.warning(
                    "publisher issue %s: %d of %s's %d break(s) were classified",
                    issue.id,
                    inside + counted[False],
                    result.rule_id,
                    result.unsatisfied,
                )
        outside = result.unsatisfied - inside
    return IssueNote(
        rule_id=result.rule_id,
        issue_id=issue.id,
        title=issue.title,
        status=issue.status,
        status_text=issue.status_text,
        effect=issue.effect,
        attribution=entry.attribution,
        unsatisfied=result.unsatisfied,
        inside=inside,
        outside=outside,
        fixed_in=issue.fixed_in,
        sentence=_sentence(issue, entry, result, inside, outside),
    )


def _sentence(
    issue: PublisherIssue,
    entry: IssueRule,
    result: RuleResult,
    inside: int | None,
    outside: int | None,
) -> str:
    lead = f"Known issue with the published rule ({issue.id}, {issue.status_text}): {issue.title}."
    see = f"See `{_COMMAND} {issue.id}`."
    if issue.effect == EFFECT_PASSES_WRONG_RETURNS:
        return f"{lead} This pass is no evidence that the return is right on what the rule checks. {see}"
    if issue.effect == EFFECT_NEVER_RUNS:
        return (
            f"{lead} The published rule never runs on a return like this, so it checks nothing "
            f"here. {see}"
        )
    total = result.unsatisfied
    inside = inside or 0
    outside = outside or 0
    if inside == 0:
        counts = (
            f"None of its {total} unsatisfied evaluation(s) is where that issue applies: these "
            "breaks are not explained by it."
        )
    elif entry.attribution == ATTRIBUTION_POSSIBLE:
        counts = (
            f"{inside} of {total} unsatisfied evaluation(s) may be where the published rule is "
            "known to be wrong, or may be the return's own - the issue cannot tell them apart, "
            "so check them" + (f"; {outside} are not explained by it." if outside else ".")
        )
    elif outside == 0:
        counts = (
            f"All {total} unsatisfied evaluation(s) are where a return that follows the "
            "reporting instructions breaks it."
        )
    else:
        counts = (
            f"{inside} of {total} unsatisfied evaluation(s) are where the published rule is "
            f"known to be wrong; {outside} are not, and are not explained by it."
        )
    return f"{lead} {counts} {see}"
