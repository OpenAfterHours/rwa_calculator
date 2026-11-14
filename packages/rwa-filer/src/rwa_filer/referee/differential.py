"""
Differential — rwa-filer's rule verdicts set beside Arelle's, rule by rule.

Pipeline position:
    boe.engine.evaluate_rules -> RuleResult ...  \\
                                                  >  compare  ->  Differential
    referee.run_referee       -> RefereeResult   /

Key responsibilities:
- Say, for every rule either engine knows, whether the two reached the same
  VERDICT on one instance: held, broken, or never evaluated.
- Keep three things apart that are easy to blur: a disagreement (one of the two
  has misread a rule — the finding this module exists to produce), a difference
  in the NUMBER of evaluations behind the same verdict (reported, not a
  finding: see ``COUNT_DIFFERS``), and a rule that could not be compared at
  all because the referee lost it or was not asked.
- Never read "nothing compared" as "nothing disagrees": ``is_clean`` is false
  for a differential with no compared rule, and for a referee run that did not
  finish.

References:
- Bank of England Banking Taxonomy — the same rules, as workbook rows (what the
  native engine reads) and as XBRL formula assertions (what Arelle runs)
- XBRL Formula 1.0
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS
from rwa_filer.referee.runner import VERDICT_FAIL, VERDICT_NEVER_FIRED, VERDICT_PASS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.referee.runner import RefereeResult

# =============================================================================
# Constants
# =============================================================================

#: Same verdict, same number of satisfied and unsatisfied evaluations.
AGREE: Final = "agree"
#: Same verdict, reached over a different number of evaluations. Reported, not
#: a finding. Measured on arelle-release 2.47.5: a formula run that evaluates
#: many assertions in one session reports MORE evaluations for a handful of
#: rules than the same rules run alone do (six of PRA001's 1,441 on the Bank's
#: sample instance), and the isolated counts are the native engine's. A count
#: is therefore weaker evidence than a verdict.
COUNT_DIFFERS: Final = "count_differs"
#: The two engines reached different verdicts.
DISAGREE: Final = "disagree"
#: The referee has no verdict to compare: it lost the rule, or was not asked.
NOT_COMPARED: Final = "not_compared"

#: Referee-side standings a rule can have besides Arelle's three verdicts.
REFEREE_SKIPPED: Final = "SKIPPED"
REFEREE_LOST: Final = "LOST"
REFEREE_ABSENT: Final = "ABSENT"
#: Native-side standing of a rule only the referee knows.
NATIVE_ABSENT: Final = "ABSENT"

_HELD: Final = "held"
_BROKEN: Final = "broken"
_SILENT: Final = "silent"

_NATIVE_VERDICTS: Final = {
    STATUS_PASS: _HELD,
    STATUS_FAIL: _BROKEN,
    STATUS_NOT_EVALUATED: _SILENT,
}
_REFEREE_VERDICTS: Final = {
    VERDICT_PASS: _HELD,
    VERDICT_FAIL: _BROKEN,
    VERDICT_NEVER_FIRED: _SILENT,
    # A filing-indicator precondition that is false: the rule is not run.
    REFEREE_SKIPPED: _SILENT,
}


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class RuleComparison:
    """One rule, as each engine left it.

    Attributes:
        rule_id: The rule code.
        outcome: ``AGREE``, ``COUNT_DIFFERS``, ``DISAGREE`` or ``NOT_COMPARED``.
        native: The native engine's status, or ``ABSENT``.
        referee: Arelle's verdict, or ``SKIPPED`` / ``LOST`` / ``ABSENT``.
        native_counts: Satisfied and unsatisfied evaluations, native.
        referee_counts: The same from Arelle; ``None`` where it has none.
        note: What a reader needs beyond the two standings; often empty.
    """

    rule_id: str
    outcome: str
    native: str
    referee: str
    native_counts: tuple[int, int] = (0, 0)
    referee_counts: tuple[int, int] | None = None
    note: str = ""

    def as_record(self) -> dict[str, Any]:
        """A JSON-serialisable form."""
        return {
            "rule": self.rule_id,
            "outcome": self.outcome,
            "native": self.native,
            "referee": self.referee,
            "native_counts": list(self.native_counts),
            "referee_counts": None if self.referee_counts is None else list(self.referee_counts),
            "note": self.note,
        }


@dataclass(frozen=True)
class Differential:
    """Every rule's comparison for one instance.

    Attributes:
        comparisons: One per rule either engine knows, by rule code.
        referee_complete: Whether every referee worker ran to the end.
    """

    comparisons: tuple[RuleComparison, ...]
    referee_complete: bool = True

    @property
    def disagreements(self) -> tuple[RuleComparison, ...]:
        """The rules on which the two engines reached different verdicts."""
        return self._with(DISAGREE)

    @property
    def count_differences(self) -> tuple[RuleComparison, ...]:
        """The rules with one verdict and two evaluation counts."""
        return self._with(COUNT_DIFFERS)

    @property
    def not_compared(self) -> tuple[RuleComparison, ...]:
        """The rules the referee has no verdict for."""
        return self._with(NOT_COMPARED)

    @property
    def compared(self) -> int:
        """Rules on which both engines have a standing."""
        return sum(item.outcome != NOT_COMPARED for item in self.comparisons)

    @property
    def is_clean(self) -> bool:
        """Whether the comparison supports "the two engines agree".

        False while anything disagrees — and false, too, where the comparison
        proves nothing: no rule compared, a rule the referee lost, or a
        referee run that did not finish. A rule the referee was simply not
        asked about does not make the differential unclean.
        """
        if not self.referee_complete or not self.compared or self.disagreements:
            return False
        return not any(item.referee == REFEREE_LOST for item in self.comparisons)

    def counts(self) -> dict[str, int]:
        """Rules per outcome, in a stable order."""
        seen = Counter(item.outcome for item in self.comparisons)
        return {
            outcome: seen.get(outcome, 0)
            for outcome in (AGREE, COUNT_DIFFERS, DISAGREE, NOT_COMPARED)
        }

    def to_record(self) -> dict[str, Any]:
        """A JSON-serialisable form: the totals, then every rule that did not simply agree."""
        return {
            "is_clean": self.is_clean,
            "referee_complete": self.referee_complete,
            "rules": len(self.comparisons),
            "compared": self.compared,
            "outcomes": self.counts(),
            "disagreements": [item.as_record() for item in self.disagreements],
            "count_differences": [item.as_record() for item in self.count_differences],
            "not_compared": [item.as_record() for item in self.not_compared],
        }

    def _with(self, outcome: str) -> tuple[RuleComparison, ...]:
        return tuple(item for item in self.comparisons if item.outcome == outcome)


def compare(native: Iterable[RuleResult], referee: RefereeResult) -> Differential:
    """Set the native engine's results beside the referee's, rule by rule.

    Args:
        native: The native engine's result for every rule the module enforces
            (``RuleReport.results``).
        referee: What Arelle concluded on the same instance.

    Returns:
        A ``Differential`` with one comparison per rule either engine knows.
        A rule only Arelle evaluated is a disagreement: the native rule book
        does not hold a rule the taxonomy runs.
    """
    results = {result.rule_id: result for result in native}
    skipped, lost = set(referee.skipped), set(referee.lost)
    known = sorted(set(results) | set(referee.rules) | skipped | lost)
    comparisons = tuple(
        _comparison(rule_id, results.get(rule_id), referee, skipped, lost) for rule_id in known
    )
    return Differential(comparisons=comparisons, referee_complete=referee.complete)


# =============================================================================
# Private helpers
# =============================================================================


def _comparison(
    rule_id: str,
    result: RuleResult | None,
    referee: RefereeResult,
    skipped: set[str],
    lost: set[str],
) -> RuleComparison:
    standing, counts = _referee_standing(rule_id, referee, skipped, lost)
    if result is None:
        silent = _REFEREE_VERDICTS.get(standing) == _SILENT
        return RuleComparison(
            rule_id=rule_id,
            # A rule Arelle did not evaluate either is not evidence of anything.
            outcome=NOT_COMPARED if silent or standing == REFEREE_LOST else DISAGREE,
            native=NATIVE_ABSENT,
            referee=standing,
            referee_counts=counts,
            note="not among the rules the native rule book enforces for this module",
        )
    native_counts = (result.satisfied, result.unsatisfied)
    if standing in (REFEREE_LOST, REFEREE_ABSENT):
        note = (
            "the referee's worker for this rule did not finish"
            if standing == REFEREE_LOST
            else "the referee was not asked about this rule"
        )
        return RuleComparison(
            rule_id, NOT_COMPARED, result.status, standing, native_counts, note=note
        )
    same_verdict = _NATIVE_VERDICTS[result.status] == _REFEREE_VERDICTS[standing]
    if not same_verdict:
        outcome = DISAGREE
    elif counts is not None and counts != native_counts:
        outcome = COUNT_DIFFERS
    else:
        outcome = AGREE
    return RuleComparison(
        rule_id=rule_id,
        outcome=outcome,
        native=result.status,
        referee=standing,
        native_counts=native_counts,
        referee_counts=counts,
        note=result.reason if outcome == DISAGREE else "",
    )


def _referee_standing(
    rule_id: str, referee: RefereeResult, skipped: set[str], lost: set[str]
) -> tuple[str, tuple[int, int] | None]:
    """Where the referee left ``rule_id``, and its evaluation counts if it has any."""
    verdict = referee.rules.get(rule_id)
    if verdict is not None:
        return verdict.status, (verdict.satisfied, verdict.unsatisfied)
    if rule_id in lost:
        return REFEREE_LOST, None
    if rule_id in skipped:
        return REFEREE_SKIPPED, None
    return REFEREE_ABSENT, None
