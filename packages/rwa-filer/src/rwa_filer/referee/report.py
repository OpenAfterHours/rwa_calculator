"""
Referee report — what Arelle found, and where it parts from the native engine.

Pipeline position:
    referee.run_referee -> RefereeResult  \\
                                           >  to_record / render_text  ->  CLI, CI log
    referee.differential.compare -> Differential  /

Key responsibilities:
- Say in one place whether a referee run SUPPORTS the instance: every worker
  finished, Arelle raised nothing at an error level, and — where the native
  engine's verdicts were set beside Arelle's — the two agree.
- Render the run for a reader and for a machine, from the same facts.

References:
- packages/rwa-filer/src/rwa_filer/referee/runner.py, differential.py
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.referee.runner import VERDICT_FAIL, VERDICT_NEVER_FIRED, VERDICT_PASS

if TYPE_CHECKING:
    from rwa_filer.referee.differential import Differential, RuleComparison
    from rwa_filer.referee.runner import RefereeResult

#: Messages and rule comparisons listed in the text form; the record has them all.
_LISTED: Final = 20

# =============================================================================
# Public entry point
# =============================================================================


def is_supported(result: RefereeResult, differential: Differential | None = None) -> bool:
    """Whether the run supports the instance, and the native verdicts if compared.

    False for a run that did not finish or raised an error-level message, and
    for a comparison that is not clean. Arelle's own rule verdicts do not enter
    into it: a broken rule is a finding about the data, reported as such.
    """
    if not result.complete or result.errors:
        return False
    return differential is None or differential.is_clean


def to_record(result: RefereeResult, differential: Differential | None = None) -> dict[str, Any]:
    """The run, and the comparison when there is one, as a JSON-ready dict."""
    record: dict[str, Any] = {
        "supported": is_supported(result, differential),
        "referee": result.to_record(),
    }
    if differential is not None:
        record["differential"] = differential.to_record()
    return record


def render_text(
    instance: str, result: RefereeResult, differential: Differential | None = None
) -> str:
    """The run as a short report: what ran, what Arelle said, where the engines part."""
    statuses = Counter(verdict.status for verdict in result.rules.values())
    lines = [
        f"Referee: Arelle on {instance} — {'complete' if result.complete else 'INCOMPLETE'}",
        f"  entry point   {result.schema_ref}",
        f"  templates     {len(result.filing_indicators)} filed",
        f"  rules         {len(result.rules)} evaluated "
        f"({statuses[VERDICT_PASS]} held, {statuses[VERDICT_FAIL]} broken, "
        f"{statuses[VERDICT_NEVER_FIRED]} never fired), "
        f"{len(result.skipped)} skipped (template not filed), {len(result.lost)} lost",
        f"  workers       {len(result.chunks)} ({result.mode}), "
        f"{sum(not chunk.ok for chunk in result.chunks)} failed",
        f"  messages      {len(result.messages)} ({len(result.errors)} at an error level)",
    ]
    lines += [
        f"    [{message.code}] {message.level}: {message.text}"
        for message in result.messages[:_LISTED]
    ]
    if len(result.messages) > _LISTED:
        lines.append(f"    ... and {len(result.messages) - _LISTED} more")
    if differential is not None:
        lines += _differential_lines(differential)
    lines.append(_verdict_line(result, differential))
    return "\n".join(lines)


# =============================================================================
# Private helpers
# =============================================================================


def _differential_lines(differential: Differential) -> list[str]:
    outcomes = differential.counts()
    lines = [
        "Differential: the native engine beside Arelle",
        f"  compared      {differential.compared} rule(s): {outcomes['agree']} agree, "
        f"{outcomes['count_differs']} same verdict over a different count, "
        f"{outcomes['disagree']} DISAGREE",
        f"  not compared  {outcomes['not_compared']} (no Arelle verdict: not asked about, or lost)",
    ]
    lines += [_comparison_line(item) for item in differential.disagreements[:_LISTED]]
    if len(differential.disagreements) > _LISTED:
        lines.append(f"    ... and {len(differential.disagreements) - _LISTED} more")
    lines += [_comparison_line(item) for item in differential.count_differences[:_LISTED]]
    return lines


def _comparison_line(item: RuleComparison) -> str:
    referee = "" if item.referee_counts is None else f" {item.referee_counts}"
    note = f" — {item.note}" if item.note else ""
    return (
        f"    {item.outcome:<13} {item.rule_id}: native {item.native} {item.native_counts}, "
        f"Arelle {item.referee}{referee}{note}"
    )


def _verdict_line(result: RefereeResult, differential: Differential | None) -> str:
    if not result.complete:
        return "Verdict: NOT ESTABLISHED — the referee run did not finish; see the lost rules."
    if result.errors:
        return f"Verdict: REJECTED — Arelle raised {len(result.errors)} error-level message(s)."
    if differential is None:
        return "Verdict: Arelle accepts the instance (the native engine was not compared)."
    if differential.disagreements:
        return (
            f"Verdict: DISAGREEMENT — the two engines differ on "
            f"{len(differential.disagreements)} rule(s); one of them has misread each."
        )
    if not differential.is_clean:
        return "Verdict: NOT ESTABLISHED — no rule could be compared."
    return "Verdict: Arelle accepts the instance and the two engines agree on every rule compared."
