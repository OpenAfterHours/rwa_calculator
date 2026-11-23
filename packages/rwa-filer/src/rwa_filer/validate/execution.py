"""
The gateway's execution configuration — the Bank's deny list, applied after the rules are evaluated.

Pipeline position:
    boe.engine.evaluate_rules / trace_rules  ->  RuleResult per rule (the
    taxonomy's formula, as published)
        ->  apply_deny_list (the Bank's deny list in force on the run date)
        ->  RuleResult per rule (as the gateway runs it)  ->  validate.returns
    referee.differential  ->  formula_result (back to the published verdict)

Key responsibilities:
- Turn each rule the Bank has DEACTIVATED at its gateway into NOT_EVALUATED,
  reason ``deactivated_by_publisher``: the gateway does not run it, and a
  reporter is not expected to meet it. Not a gap in the check either — the
  gateway would not check it however complete the engine was.
- Turn each rule the Bank has DOWNGRADED into a Warning: the gateway still runs
  it, but a break no longer rejects the submission.
- Keep what the formula found beside the new result (``RuleResult.formula``),
  so the comparison with an XBRL processor that runs the taxonomy's formulas
  (Arelle, which has no deny list) stays like with like, and a report can say
  what the published rule would have found.
- Keep the evidence consistent with the verdict: the evaluations of a rule the
  gateway does not run are not evidence behind the verdict, so they leave the
  trace.

Why AFTER evaluation, not by filtering the rules first: the deny list changes
the execution of a rule, never its logic or scope ("Validation logic and scope
will never be altered in this document, only their execution configuration" —
the deny list's Note sheet). Evaluating every published rule and configuring
the result keeps the published verdict available for the referee and for a
reader, and keeps ``Rule.fingerprint`` the taxonomy's.

References:
- Bank of England, "Banking validations deny list", sheet "Note"
- rwa_filer.boe.deny — the packaged list and when an entry is in force
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from rwa_filer.boe.catalogue import SEVERITY_ERROR, SEVERITY_WARNING
from rwa_filer.boe.engine import (
    REASON_DEACTIVATED_BY_PUBLISHER,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from rwa_filer.boe.deny import DenyEntry, DenyList
    from rwa_filer.boe.engine import RuleResult, RuleTrace

logger = logging.getLogger(__name__)


# =============================================================================
# Public entry point
# =============================================================================


def apply_deny_list(
    results: Iterable[RuleResult], deny_list: DenyList, module: str, day: date
) -> tuple[RuleResult, ...]:
    """``results`` as the Bank's gateway runs them on ``day``, in the order given.

    Args:
        results: The engine's results for ``module``'s enforced rules.
        deny_list: The release's deny list.
        module: The return's module: an entry applies to its own module only.
        day: The run (or submission) date. An entry applies from its Date
            Applied on; one with no date is pending and never applies.

    Returns:
        One result per rule. A rule with no entry in force is returned as it is.
    """
    in_force = deny_list.in_force(module, day)
    applied = tuple(_applied(result, in_force.get(result.rule_id)) for result in results)
    changed = sum(item.deny is not None for item in applied)
    if changed:
        logger.info(
            "deny list %s on %s: %d rule(s) of %s deactivated or downgraded at the gateway",
            deny_list.release,
            day.isoformat(),
            changed,
            module,
        )
    return applied


def formula_result(result: RuleResult) -> RuleResult:
    """The result as the taxonomy's formula has it, whatever the deny list did to it."""
    return result.formula if result.formula is not None else result


def trace_as_run(trace: RuleTrace, results: tuple[RuleResult, ...]) -> RuleTrace:
    """``trace`` with ``results``, and without the evaluations of deactivated rules.

    The evidence records the evaluations behind the verdict; a rule the gateway
    does not run has none. Its formula's counts stay on its result
    (``RuleResult.formula``). A cell only those evaluations read leaves too.
    The trace is rebuilt by its own class, so it stays the kind it was: a lean
    trace (``boe.engine._trace_lean``) stays one, and can still be told apart.
    ``RuleTrace``'s three fields are all given here; a test holds the class to
    those three, so a field added later cannot be dropped silently.
    """
    switched_off = {
        result.rule_id
        for result in results
        if result.reason == REASON_DEACTIVATED_BY_PUBLISHER and result.formula is not None
    }
    kind = type(trace)
    if not switched_off:
        return kind(results=results, evaluations=trace.evaluations, cells=trace.cells)
    kept = tuple(item for item in trace.evaluations if item.rule_id not in switched_off)
    read = {address for evaluation in kept for address in evaluation.cells}
    return kind(
        results=results,
        evaluations=kept,
        cells={address: fact for address, fact in trace.cells.items() if address in read},
    )


def published_finding(result: RuleResult) -> str:
    """What the published rule found on the return, in words, e.g. ``... breaks 3 of 7 ...``."""
    if result.status == STATUS_FAIL:
        return (
            f"the published rule breaks {result.unsatisfied} of {result.evaluations} "
            "evaluation(s) here"
        )
    if result.status == STATUS_PASS:
        return f"the published rule holds in all {result.evaluations} evaluation(s) here"
    return f"the published rule is not evaluated here ({result.reason})"


# =============================================================================
# Private helpers
# =============================================================================


def _applied(result: RuleResult, entry: DenyEntry | None) -> RuleResult:
    if entry is None:
        return result
    if entry.is_deactivation:
        return replace(
            result,
            status=STATUS_NOT_EVALUATED,
            reason=REASON_DEACTIVATED_BY_PUBLISHER,
            detail=_deactivated_detail(result, entry),
            satisfied=0,
            unsatisfied=0,
            failures=(),
            deny=entry,
            formula=result,
        )
    if result.severity != SEVERITY_ERROR:
        # Already a warning: the downgrade changes nothing, but is still said.
        return replace(result, deny=entry)
    return replace(result, severity=SEVERITY_WARNING, deny=entry, formula=result)


def _deactivated_detail(result: RuleResult, entry: DenyEntry) -> str:
    """Why the rule was not run, and what the published rule found here."""
    return (
        f"{entry.describe()}: the gateway does not run it and reporters are not expected to "
        f"meet it; {published_finding(result)}"
    )
