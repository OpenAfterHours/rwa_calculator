"""
Supervisory validation checker — the public entry point over the rule estate.

Pipeline position:
    COREPGenerator + Pillar3Generator
        ->  evaluate_all           ->  ValidationReport (per-rule outcomes)
        ->  check_supervisory_validations  ->  list[CalculationError]

Key responsibilities:
- Run every currently-enforced published validation rule for a framework against
  the templates this run generated, and return one outcome per rule.
- Adapt the Error / Warning outcomes onto the project's error channel as
  ``VAL001`` / ``VAL002`` findings — accumulated, never raised, following the
  same contract as ``reporting/tieouts.py``.
- Guarantee that an EMPTY finding list is meaningful, by reporting insufficient
  coverage as ``VAL003``. Without it the obvious gate —
  ``if not check_supervisory_validations(...): submit()`` — fails OPEN: an estate
  on which every rule was NOT_EVALUATED produces no breaks and is indistinguishable
  from a clean one. The guard belongs here rather than in each caller.

Why this is critical path: these are the supervisor's own checks, run at
submission. An Error-severity break REJECTS the whole return, so a ``VAL001``
finding is a blocking defect in the filing, not a quality nit. ``tieouts.py``
is the hand-curated in-house ancestor of this module — five cross-template
identities we derived ourselves; this is the published, exhaustive form.

What is deliberately NOT reported:
- A rule whose template, sheet, row or column this run never emitted is
  NOT_EVALUATED with that reason. "Row not emitted" is not "row emitted as
  zero", and treating it as zero produces false breaks on rules that sum market,
  operational and settlement risk rows a credit-risk calculator does not produce.
- A rule whose operands are all null or zero is VACUOUS. It is not counted as a
  pass, because a vacuous pass is no evidence of correctness.

References:
- docs/reference/validation-rules/index.md — the rule grammar and provenance
- COREP Annex II; PRA PS1/26 Annex II — the templates the rules address
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from rwa_calc.contracts.errors import (
    ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
    ERROR_VALIDATION_RULE_ERROR,
    ERROR_VALIDATION_RULE_WARNING,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.reporting.validations.evaluate import (
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
from rwa_calc.reporting.validations.rules import (
    SEVERITY_ERROR,
    build_rule_reference,
    load_rules,
)
from rwa_calc.reporting.validations.scope import (
    build_template_index,
    expand_rule,
)

if TYPE_CHECKING:
    from typing import Literal

    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
    from rwa_calc.reporting.validations.evaluate import CoordinateOutcome
    from rwa_calc.reporting.validations.rules import ValidationRule
    from rwa_calc.reporting.validations.scope import TemplateIndex

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


# =============================================================================
# Public entry point
# =============================================================================


def check_supervisory_validations(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> list[CalculationError]:
    """Run the published validation rules and return the breaks as findings.

    A thin ``CalculationError`` adapter over ``evaluate_all``. Only FAIL
    outcomes yield findings — one per broken rule, following the roll-up pattern
    (a single code per failure mode, the rule id on ``field_name``, both figures
    in the message), so a rule that breaks on 40 sheets is one finding, not 40.

    An EMPTY result means "the estate was checked and holds" — and nothing else.
    The naive gate ``if not check_supervisory_validations(...): submit()`` would
    otherwise pass an estate on which NOTHING ran: every rule NOT_EVALUATED
    yields no FAIL and therefore no finding. A ``VAL003`` coverage finding closes
    that, so an empty list is safe to read as a green light.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar 3 bundle (carried for contract symmetry;
            no published rule addresses a Pillar 3 template — see
            ``scope.build_template_index``).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        ``VAL001`` (Error-severity rule broken — blocks the submission),
        ``VAL002`` (Warning-severity rule broken) and ``VAL003`` (the estate was
        not checked well enough for an empty result to mean anything) findings;
        empty only when every enforced rule that could run did run and holds.
        Never raises.
    """
    report = evaluate_all(corep, pillar3, framework)
    findings = [_finding(outcome) for outcome in report.outcomes if outcome.status == STATUS_FAIL]
    shortfall = _coverage_finding(report)
    if shortfall is not None:
        findings.insert(0, shortfall)
    return findings


def evaluate_all(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> ValidationReport:
    """Evaluate every currently-enforced rule for ``framework`` and report.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar 3 bundle (see above).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        A ``ValidationReport`` carrying one ``RuleOutcome`` per enforced rule —
        status, both figures, the coordinates and, for anything not evaluated,
        the reason — plus the per-template coverage the run achieved. Never
        raises for a data condition.
    """
    ruleset = load_rules(framework)
    index = build_template_index(corep, pillar3, framework)
    enforced = ruleset.enforced
    outcomes = tuple(_evaluate_rule(rule, index) for rule in enforced)
    emitted, covered = _template_coverage(outcomes, index)
    logger.info(
        "supervisory validations (%s): %d enforced, %d executed, %d failed, %d/%d templates covered",
        framework,
        len(enforced),
        sum(1 for outcome in outcomes if outcome.status != STATUS_NOT_EVALUATED),
        sum(1 for outcome in outcomes if outcome.status == STATUS_FAIL),
        len(covered),
        len(emitted),
    )
    return ValidationReport(
        framework=framework,
        publisher=ruleset.publisher,
        rules_loaded=len(ruleset.rules),
        rules_enforced=len(enforced),
        outcomes=outcomes,
        templates_emitted=emitted,
        templates_covered=covered,
    )


# =============================================================================
# Report shapes
# =============================================================================


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


def _coverage_finding(report: ValidationReport) -> CalculationError | None:
    """Build the VAL003 finding for whatever ``report.coverage_shortfall`` says.

    The predicate lives on ``ValidationReport.coverage_shortfall`` and is read —
    never re-derived — here. That is the whole point: the finding, an API
    submission gate and an exported report all consume ONE implementation, so a
    third limb added later cannot reach some consumers and miss others. The
    machine reason travels on the finding's ``field_name``, so a caller holding
    only the error channel still gets the structured verdict rather than having
    to parse this message.

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
    from rwa_calc.contracts.errors import CalculationError

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
    return CalculationError(
        code=ERROR_VALIDATION_COVERAGE_INSUFFICIENT,
        message=(
            f"Supervisory validation coverage is insufficient for {report.framework} "
            f"({report.publisher}) [{shortfall}]: {report.rules_executed} of "
            f"{report.rules_enforced} enforced rules executed, "
            f"{len(report.outcomes) - report.rules_executed} not evaluated "
            f"({reasons}); {cause}. An absent finding is therefore NOT evidence the return is "
            "valid — do not treat an empty validation result as a pass."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.BUSINESS_RULE,
        regulatory_reference=(
            "COREP Annex II / PRA PS1/26 Annex II — supervisory validation rule coverage"
        ),
        field_name=shortfall,
        expected_value=f"every one of {len(report.templates_emitted)} emitted template(s) covered",
        actual_value=(
            f"{len(report.templates_covered)} covered, {report.rules_executed} rules executed"
        ),
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


def _finding(outcome: RuleOutcome) -> CalculationError:
    """Build the VAL001 / VAL002 CalculationError for one broken rule."""
    from rwa_calc.contracts.errors import CalculationError

    first = outcome.failures[0]
    blocking = outcome.severity == SEVERITY_ERROR
    code = ERROR_VALIDATION_RULE_ERROR if blocking else ERROR_VALIDATION_RULE_WARNING
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
    return CalculationError(
        code=code,
        message=(
            f"Supervisory validation rule '{outcome.rule_id}' "
            f"({outcome.publisher}, {outcome.severity}) failed on {outcome.failed} of "
            f"{outcome.evaluated} evaluated cell(s): {outcome.expression}; "
            f"left = {lhs} vs right = {rhs} at {where}; {consequence}.{label}"
        ),
        severity=ErrorSeverity.ERROR if blocking else ErrorSeverity.WARNING,
        category=ErrorCategory.BUSINESS_RULE,
        regulatory_reference=build_rule_reference(outcome.publisher, outcome.tables),
        field_name=outcome.rule_id,
        expected_value=rhs,
        actual_value=lhs,
    )
