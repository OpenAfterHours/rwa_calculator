"""
Supervisory validation checker — the public entry point over the rule estate.

Pipeline position:
    TemplateIndex
        ->  evaluate_index  ->  ValidationReport (per-rule outcomes)
        ->  findings_for    ->  list[Finding]

Key responsibilities:
- Run every currently-enforced published validation rule for a framework against
  the templates a return carries, and return one outcome per rule.
- Turn the Error / Warning outcomes into ``Finding`` records — ``VAL001`` /
  ``VAL002`` — returned, never raised.
- Guarantee that an EMPTY finding list is meaningful, by reporting insufficient
  coverage as ``VAL003``. Without it the obvious gate —
  ``if not check_index(...): submit()`` — fails OPEN: a return on which every
  rule was NOT_EVALUATED produces no breaks and is indistinguishable from a
  clean one. The guard belongs here rather than in each caller.

Why this is critical path: these are the supervisor's own checks, run at
submission. An Error-severity break REJECTS the whole return, so a ``VAL001``
finding is a blocking defect in the filing, not a quality nit.

What is deliberately NOT reported:
- A rule whose template, sheet, row or column the return does not carry is
  NOT_EVALUATED with that reason. "Row not reported" is not "row reported as
  zero", and treating it as zero produces false breaks on rules that sum market,
  operational and settlement risk rows a credit-risk return does not carry.
- A rule whose operands are all null or zero is VACUOUS. It is not counted as a
  pass, because a vacuous pass is no evidence of correctness.

``Finding`` is this package's own record. A host application maps it onto its
own error channel (``rwa-calc`` maps it to ``CalculationError`` in
``rwa_calc.reporting.filing``).

References:
- COREP Annex II; PRA PS1/26 Annex II — the templates the rules address
- EBA DPM validation rules; BoE Banking Taxonomy validation rules
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from rwa_filer.rules.catalogue import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    build_rule_reference,
    load_rules,
)
from rwa_filer.validate.evaluate import (
    SKIP_PRECONDITION_UNSUPPORTED,
    SKIP_WHERE_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    UnsupportedExpression,
    evaluate_at,
    parse_expression,
)
from rwa_filer.validate.index import expand_rule

if TYPE_CHECKING:
    from typing import Literal

    from rwa_filer.rules.catalogue import RuleSet, ValidationRule
    from rwa_filer.validate.evaluate import CoordinateOutcome
    from rwa_filer.validate.index import TemplateIndex

logger = logging.getLogger(__name__)

#: Failing coordinates kept per rule. A broken identity usually breaks on every
#: sheet at once, so the first few are diagnostic and the rest are noise; the
#: full counts stay on the outcome.
MAX_RECORDED_FAILURES: Final = 5

#: Why a run's validation coverage is insufficient. A machine-readable reason,
#: not a message to be parsed: the two limbs call for completely different
#: responses, so every consumer — the ``VAL003`` finding, an API submission
#: gate, an exported report — reads the same vocabulary.
#:
#: A PEP 695 alias deliberately: its right-hand side is evaluated lazily, so
#: ``Literal`` stays a type-only import that the ``ruff --fix`` hook cannot strip
#: into a runtime ``NameError`` during an edit where the usage briefly vanishes.
type CoverageShortfall = Literal["no_rule_executed", "template_not_covered"]

#: Nothing ran at all: the estate was absent or unreadable, so no finding of any
#: kind is evidence of anything. This is the fail-open case.
COVERAGE_NO_RULE_EXECUTED: Final[CoverageShortfall] = "no_rule_executed"
#: The estate was reachable, but specific emitted templates had no rule executed
#: against them and would go into the submission unexamined.
COVERAGE_TEMPLATE_NOT_COVERED: Final[CoverageShortfall] = "template_not_covered"

#: Finding codes. An Error-severity published rule is broken — the regulator
#: rejects the return.
FINDING_RULE_ERROR: Final = "VAL001"
#: A Warning-severity published rule is broken — it must be explained.
FINDING_RULE_WARNING: Final = "VAL002"
#: The return was not checked well enough for an empty result to mean anything.
FINDING_COVERAGE_INSUFFICIENT: Final = "VAL003"

#: The reference quoted on a coverage finding, which no single rule owns.
COVERAGE_REFERENCE: Final = (
    "COREP Annex II / PRA PS1/26 Annex II — supervisory validation rule coverage"
)


# =============================================================================
# Public entry points
# =============================================================================


def check_index(index: TemplateIndex, ruleset: RuleSet | None = None) -> list[Finding]:
    """Run the published validation rules over ``index`` and return the findings.

    ``findings_for(evaluate_index(index))`` in one call.

    An EMPTY result means "the return was checked and holds" — and nothing else.
    The naive gate ``if not check_index(...): submit()`` would otherwise pass a
    return on which NOTHING ran: every rule NOT_EVALUATED yields no FAIL and
    therefore no finding. A ``VAL003`` coverage finding closes that, so an empty
    list is safe to read as a green light.

    Returns:
        ``VAL001`` (Error-severity rule broken — blocks the submission),
        ``VAL002`` (Warning-severity rule broken) and ``VAL003`` (the return was
        not checked well enough for an empty result to mean anything) findings;
        empty only when every enforced rule that could run did run and holds.
        Never raises for a data condition.
    """
    return findings_for(evaluate_index(index, ruleset))


def evaluate_index(index: TemplateIndex, ruleset: RuleSet | None = None) -> ValidationReport:
    """Evaluate every currently-enforced rule for ``index.framework`` and report.

    Args:
        index: The return's frames, bound to publisher table codes.
        ruleset: The rules to run. Defaults to the packaged extract for
            ``index.framework``.

    Returns:
        A ``ValidationReport`` carrying one ``RuleOutcome`` per enforced rule —
        status, both figures, the coordinates and, for anything not evaluated,
        the reason — plus the per-template coverage achieved. Never raises for a
        data condition.
    """
    ruleset = ruleset if ruleset is not None else load_rules(index.framework)
    enforced = ruleset.enforced
    outcomes = tuple(_evaluate_rule(rule, index) for rule in enforced)
    emitted, covered = _template_coverage(outcomes, index)
    logger.info(
        "supervisory validations (%s): %d enforced, %d executed, %d failed, %d/%d templates covered",
        index.framework,
        len(enforced),
        sum(1 for outcome in outcomes if outcome.status != STATUS_NOT_EVALUATED),
        sum(1 for outcome in outcomes if outcome.status == STATUS_FAIL),
        len(covered),
        len(emitted),
    )
    return ValidationReport(
        framework=index.framework,
        publisher=ruleset.publisher,
        rules_loaded=len(ruleset.rules),
        rules_enforced=len(enforced),
        outcomes=outcomes,
        templates_emitted=emitted,
        templates_covered=covered,
    )


def findings_for(report: ValidationReport) -> list[Finding]:
    """The findings a report yields: the coverage shortfall first, then each break.

    Only FAIL outcomes yield rule findings — one per broken rule, following the
    roll-up pattern (a single code per failure mode, the rule id on ``subject``,
    both figures in the message), so a rule that breaks on 40 sheets is one
    finding, not 40.
    """
    findings = [_finding(outcome) for outcome in report.outcomes if outcome.status == STATUS_FAIL]
    shortfall = _coverage_finding(report)
    if shortfall is not None:
        findings.insert(0, shortfall)
    return findings


# =============================================================================
# Report shapes
# =============================================================================


@dataclass(frozen=True)
class Finding:
    """One reportable result of validating a return.

    Attributes:
        code: ``VAL001`` / ``VAL002`` / ``VAL003``.
        severity: ``"ERROR"`` (blocks the submission) or ``"WARNING"``.
        message: The full human-readable finding.
        reference: The regulatory source the finding rests on.
        subject: What the finding is about, machine-readable — the rule id for a
            broken rule, the ``CoverageShortfall`` reason for ``VAL003``.
        expected: The figure or state the rule requires.
        actual: The figure or state the return carries.
    """

    code: str
    severity: str
    message: str
    reference: str
    subject: str
    expected: str
    actual: str

    @property
    def is_blocking(self) -> bool:
        """Whether this finding stops the return being submitted."""
        return self.severity == SEVERITY_ERROR


@dataclass(frozen=True)
class RuleOutcome:
    """The result of running one validation rule against this run's templates.

    Attributes:
        status: ``PASS`` / ``FAIL`` / ``VACUOUS`` / ``NOT_EVALUATED``.
        reason: For NOT_EVALUATED, the machine reason (``table_not_emitted``,
            ``sheet_index_map_unknown``, ``unsupported_grammar``, …).
        detail: Free text expanding on ``reason``.
        evaluated: Coordinates that produced a verdict (pass, fail or vacuous).
        failures: Up to ``MAX_RECORDED_FAILURES`` broken coordinates.
    """

    rule_id: str
    publisher: str
    framework: str
    severity: str
    rule_type: str
    tables: tuple[str, ...]
    expression: str | None
    label: str | None
    status: str
    reason: str = ""
    detail: str = ""
    evaluated: int = 0
    passed: int = 0
    failed: int = 0
    vacuous: int = 0
    skipped: int = 0
    failures: tuple[CoordinateOutcome, ...] = ()

    @property
    def coordinates(self) -> tuple[str, ...]:
        """Human addresses of the recorded failing coordinates."""
        return tuple(outcome.coordinate.describe() for outcome in self.failures)


@dataclass(frozen=True)
class ValidationReport:
    """Every rule outcome for one framework, plus the catalogue and coverage counts.

    Attributes:
        templates_emitted: Bundle members this run actually produced — the
            templates that would go in the submission.
        templates_covered: Those of them against which at least one rule was
            executed. The difference is what makes an empty finding list
            meaningless, so it is reported, not inferred.
    """

    framework: str
    publisher: str
    rules_loaded: int
    rules_enforced: int
    outcomes: tuple[RuleOutcome, ...]
    templates_emitted: tuple[str, ...] = ()
    templates_covered: tuple[str, ...] = ()

    @property
    def rules_executed(self) -> int:
        """Rules that reached a verdict — PASS, FAIL or VACUOUS."""
        return sum(1 for outcome in self.outcomes if outcome.status != STATUS_NOT_EVALUATED)

    @property
    def templates_uncovered(self) -> tuple[str, ...]:
        """Emitted templates no rule was executed against."""
        covered = set(self.templates_covered)
        return tuple(name for name in self.templates_emitted if name not in covered)

    @property
    def coverage_shortfall(self) -> CoverageShortfall | None:
        """Why this run was not checked well enough, or ``None`` when it was.

        THE one implementation of the coverage predicate. ``VAL003`` is emitted
        from exactly this property rather than re-deriving the condition, so the
        finding and the report can never disagree — and a caller deciding
        whether to submit reads the same verdict the finding was built from,
        without parsing a message string.

        The two reasons demand different responses from a filer, which is why
        this is structured rather than a bare boolean: ``no_rule_executed``
        means the estate could not be reached at all (a plumbing problem —
        nothing was checked), while ``template_not_covered`` means specific
        templates in an otherwise-checked estate went out unexamined.
        """
        if not self.rules_executed:
            return COVERAGE_NO_RULE_EXECUTED
        if self.templates_uncovered:
            return COVERAGE_TEMPLATE_NOT_COVERED
        return None

    @property
    def is_coverage_sufficient(self) -> bool:
        """Whether an absent break is meaningful evidence that the estate holds."""
        return self.coverage_shortfall is None

    def by_status(self, status: str) -> tuple[RuleOutcome, ...]:
        """Outcomes with the given status."""
        return tuple(outcome for outcome in self.outcomes if outcome.status == status)

    def status_counts(self) -> dict[str, int]:
        """Rule counts per status, in a stable order."""
        counts = Counter(outcome.status for outcome in self.outcomes)
        return {
            status: counts.get(status, 0)
            for status in (STATUS_PASS, STATUS_FAIL, STATUS_VACUOUS, STATUS_NOT_EVALUATED)
        }

    def not_evaluated_reasons(self) -> dict[str, int]:
        """NOT_EVALUATED rule counts per reason, commonest first."""
        counts = Counter(
            outcome.reason for outcome in self.outcomes if outcome.status == STATUS_NOT_EVALUATED
        )
        return dict(counts.most_common())


# =============================================================================
# Private helpers
# =============================================================================


def _evaluate_rule(rule: ValidationRule, index: TemplateIndex) -> RuleOutcome:
    """Parse, expand and evaluate one rule; every refusal is a reason, not a raise."""
    if rule.precondition:
        return _not_evaluated(rule, SKIP_PRECONDITION_UNSUPPORTED, rule.precondition)
    if rule.where:
        return _not_evaluated(rule, SKIP_WHERE_UNSUPPORTED, rule.where)

    try:
        expression = parse_expression(rule.expression)
    except UnsupportedExpression as unsupported:
        return _not_evaluated(rule, unsupported.reason, unsupported.detail)

    expansion = expand_rule(
        rule,
        index,
        needs_row_axis=expression.needs_row_axis,
        needs_column_axis=expression.needs_column_axis,
        needs_sheet_axis=expression.needs_sheet_axis,
    )
    if expansion.skip_reason is not None:
        return _not_evaluated(rule, expansion.skip_reason, expansion.detail)

    outcomes = [
        evaluate_at(
            expression,
            coordinate,
            index,
            missing_value=rule.missing_value,
            arithmetic=rule.arithmetic,
        )
        for coordinate in expansion.coordinates
    ]
    return _roll_up(rule, outcomes)


def _roll_up(rule: ValidationRule, outcomes: list[CoordinateOutcome]) -> RuleOutcome:
    """Aggregate per-coordinate verdicts into the rule's single status."""
    failures = tuple(o for o in outcomes if o.status == STATUS_FAIL)
    passes = sum(1 for o in outcomes if o.status == STATUS_PASS)
    vacuous = sum(1 for o in outcomes if o.status == STATUS_VACUOUS)
    skipped = [o for o in outcomes if o.status == STATUS_NOT_EVALUATED]
    evaluated = len(failures) + passes + vacuous

    if failures:
        status, reason, detail = STATUS_FAIL, "", failures[0].detail
    elif evaluated == 0:
        reasons = Counter(o.reason for o in skipped)
        commonest = reasons.most_common(1)
        reason = commonest[0][0] if commonest else "no_coordinates"
        detail = next((o.detail for o in skipped if o.reason == reason), "")
        status = STATUS_NOT_EVALUATED
    elif passes == 0:
        status, reason, detail = STATUS_VACUOUS, "", "every operand was null or zero"
    else:
        status, reason, detail = STATUS_PASS, "", ""

    return RuleOutcome(
        rule_id=rule.rule_id,
        publisher=rule.publisher,
        framework=rule.framework,
        severity=rule.severity,
        rule_type=rule.rule_type,
        tables=rule.tables,
        expression=rule.expression,
        label=rule.label,
        status=status,
        reason=reason,
        detail=detail,
        evaluated=evaluated,
        passed=passes,
        failed=len(failures),
        vacuous=vacuous,
        skipped=len(skipped),
        failures=failures[:MAX_RECORDED_FAILURES],
    )


def _template_coverage(
    outcomes: tuple[RuleOutcome, ...], index: TemplateIndex
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (templates emitted, templates with at least one executed rule).

    A template counts as covered when an EXECUTED rule names it. Naming is the
    right test rather than the rule's home table: a rule only reaches a verdict
    if every one of its references resolved, so an executed cross-table rule
    genuinely exercised both sides.
    """
    emitted = tuple(sorted(index.frames))
    covered: set[str] = set()
    for outcome in outcomes:
        if outcome.status == STATUS_NOT_EVALUATED:
            continue
        for table in outcome.tables:
            binding = index.binding(table)
            if binding is not None and binding.attribute in index.frames:
                covered.add(binding.attribute)
    return emitted, tuple(sorted(covered))


def _coverage_finding(report: ValidationReport) -> Finding | None:
    """Build the VAL003 finding for whatever ``report.coverage_shortfall`` says.

    The predicate lives on ``ValidationReport.coverage_shortfall`` and is read —
    never re-derived — here. That is the whole point: the finding, an API
    submission gate and an exported report all consume ONE implementation, so a
    third limb added later cannot reach some consumers and miss others. The
    machine reason travels on the finding's ``subject``, so a caller holding
    only the findings still gets the structured verdict rather than having to
    parse this message.

    Why the shortfall is defined the way it is:

    - **Nothing executed.** An absent or unreadable estate produces 741
      NOT_EVALUATED outcomes and therefore zero findings — the fail-open case.
      This limb also catches a bundle that emitted no template at all, where a
      per-template test is vacuously satisfied.
    - **An emitted template was not covered.** A bare executed-rule count is
      gameable: an estate could execute hundreds of rules while every rule
      touching one template silently went unevaluated, and the count would look
      healthy. The guarantee that matters is per-template.

    Deliberately NOT a hard-coded list of must-run rule ids. The extracts are
    regenerated from the published workbooks, so a pinned id that the publisher
    later deactivates becomes permanently unsatisfiable — a standing false alarm,
    which is how a gate stops being believed. Per-template coverage is derived
    from what the run emitted, so it stays honest as both the estate and the
    rule set change.
    """
    shortfall = report.coverage_shortfall
    if shortfall is None:
        return None

    reasons = ", ".join(
        f"{reason}={count}" for reason, count in list(report.not_evaluated_reasons().items())[:4]
    )
    if shortfall == COVERAGE_NO_RULE_EXECUTED:
        cause = (
            f"no rule could be executed at all against the {len(report.templates_emitted)} "
            "template(s) this run produced"
        )
    else:
        cause = (
            f"emitted template(s) with no executed rule: {', '.join(report.templates_uncovered)}"
        )
    return Finding(
        code=FINDING_COVERAGE_INSUFFICIENT,
        message=(
            f"Supervisory validation coverage is insufficient for {report.framework} "
            f"({report.publisher}) [{shortfall}]: {report.rules_executed} of "
            f"{report.rules_enforced} enforced rules executed, "
            f"{len(report.outcomes) - report.rules_executed} not evaluated "
            f"({reasons}); {cause}. An absent finding is therefore NOT evidence the return is "
            "valid — do not treat an empty validation result as a pass."
        ),
        severity=SEVERITY_ERROR,
        reference=COVERAGE_REFERENCE,
        subject=shortfall,
        expected=f"every one of {len(report.templates_emitted)} emitted template(s) covered",
        actual=f"{len(report.templates_covered)} covered, {report.rules_executed} rules executed",
    )


def _not_evaluated(rule: ValidationRule, reason: str, detail: str) -> RuleOutcome:
    """Build a NOT_EVALUATED outcome for a rule that never reached a coordinate."""
    return RuleOutcome(
        rule_id=rule.rule_id,
        publisher=rule.publisher,
        framework=rule.framework,
        severity=rule.severity,
        rule_type=rule.rule_type,
        tables=rule.tables,
        expression=rule.expression,
        label=rule.label,
        status=STATUS_NOT_EVALUATED,
        reason=reason,
        detail=detail,
    )


def _finding(outcome: RuleOutcome) -> Finding:
    """Build the VAL001 / VAL002 finding for one broken rule."""
    first = outcome.failures[0]
    blocking = outcome.severity == SEVERITY_ERROR
    code = FINDING_RULE_ERROR if blocking else FINDING_RULE_WARNING
    consequence = (
        "an Error-severity break rejects the submission"
        if blocking
        else "a Warning-severity break must be explained to the supervisor"
    )
    lhs = "n/a" if first.lhs is None else f"{first.lhs:,.4f}"
    rhs = "n/a" if first.rhs is None else f"{first.rhs:,.4f}"
    where = ", ".join(outcome.coordinates)
    # The publisher's own narrative/short label carries typographic dashes and
    # curly quotes; fold it to ASCII so a cp1252 log handler or console can never
    # mangle (or raise on) a finding message.
    label = f" {outcome.label.encode('ascii', 'replace').decode()}" if outcome.label else ""
    return Finding(
        code=code,
        message=(
            f"Supervisory validation rule '{outcome.rule_id}' "
            f"({outcome.publisher}, {outcome.severity}) failed on {outcome.failed} of "
            f"{outcome.evaluated} evaluated cell(s): {outcome.expression}; "
            f"left = {lhs} vs right = {rhs} at {where}; {consequence}.{label}"
        ),
        severity=SEVERITY_ERROR if blocking else SEVERITY_WARNING,
        reference=build_rule_reference(outcome.publisher, outcome.tables),
        subject=outcome.rule_id,
        expected=rhs,
        actual=lhs,
    )
