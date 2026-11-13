"""
Validate a canonical return — structure first, then the published rules.

Pipeline position:
    CanonicalReturn  ->  validate_return
        ->  taxonomy.resolve_pack(module, reference date)
        ->  structure.check_structure
        ->  boe.catalogue.rulebook_for_module  ->  boe.engine.evaluate_rules
        ->  ReturnValidation

Key responsibilities:
- Be the one call that answers "is this return fit to submit?" for a return in
  canonical form, whatever file or system it came from.
- Run every rule the module ENFORCES, with the taxonomy's own semantics, and
  report each as passed, failed or not evaluated — with the reason.
- Keep the two kinds of finding apart in the result — structure (the taxonomy
  rejects it) and rules (the supervisor's arithmetic does not hold) — and say
  plainly whether anything blocks submission.
- Never let an empty finding list stand for "clean" when little or nothing was
  checked: ``VAL003`` reports a return on which no rule ran, or a reported
  template none of whose rules ran.

References:
- BoE XBRL Filing Manual v1.0.1
- Bank of England Banking Taxonomy v4.1.1; validation rule workbooks
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rwa_filer.boe.catalogue import SEVERITY_ERROR, RuleBookNotFoundError, rulebook_for_module
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
    evaluate_rules,
)
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    Finding,
)
from rwa_filer.validate.structure import check_structure, filing_indicators

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import CoverageShortfall

logger = logging.getLogger(__name__)

#: Not-evaluated reasons quoted in a coverage finding (commonest first).
_REASONS_QUOTED = 4


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class RuleReport:
    """Every enforced rule's result for one return, with the coverage behind it.

    Attributes:
        module: The reporting module.
        framework_version: The rule book the rules came from.
        taxonomy: The taxonomy release of that rule book.
        rules_loaded: Rules in the rule book.
        results: One result per rule the module enforces.
        templates_reported: The filing indicators the return reports.
        templates_ruled: Those of them the rule book has an enforced rule for
            that the taxonomy's formula can fire on this return.
        templates_covered: Those of them at least one rule was executed on.
    """

    module: str
    framework_version: str
    taxonomy: str
    rules_loaded: int
    results: tuple[RuleResult, ...]
    templates_reported: tuple[str, ...] = ()
    templates_ruled: tuple[str, ...] = ()
    templates_covered: tuple[str, ...] = ()

    @property
    def rules_enforced(self) -> int:
        return len(self.results)

    @property
    def rules_executed(self) -> int:
        """Rules that reached a verdict: evaluated at least once."""
        return sum(result.status != STATUS_NOT_EVALUATED for result in self.results)

    @property
    def templates_uncovered(self) -> tuple[str, ...]:
        """Reported templates that have enforced rules, none of which was executed."""
        covered = set(self.templates_covered)
        return tuple(code for code in self.templates_ruled if code not in covered)

    @property
    def coverage_shortfall(self) -> CoverageShortfall | None:
        """Why the return was not checked well enough, or ``None`` when it was.

        THE one implementation of the coverage predicate: ``VAL003`` is built
        from this, so the finding and the report cannot disagree.
        """
        if not self.rules_executed:
            return COVERAGE_NO_RULE_EXECUTED
        if self.templates_uncovered:
            return COVERAGE_TEMPLATE_NOT_COVERED
        return None

    def status_counts(self) -> dict[str, int]:
        """Rule counts per status, in a stable order."""
        counts = Counter(result.status for result in self.results)
        return {
            status: counts.get(status, 0)
            for status in (STATUS_PASS, STATUS_FAIL, STATUS_NOT_EVALUATED)
        }

    def not_evaluated_reasons(self) -> dict[str, int]:
        """Not-evaluated rule counts per reason, commonest first."""
        counts = Counter(
            result.reason for result in self.results if result.status == STATUS_NOT_EVALUATED
        )
        return dict(counts.most_common())


@dataclass(frozen=True)
class ReturnValidation:
    """Everything validating one return established.

    Attributes:
        pack: The taxonomy the return was read against.
        structure: Structure findings (``STR...``), and any finding from reading
            the return's source (``XBR...``).
        report: The per-rule report, or ``None`` when no rule book is packaged
            for the module.
        rules: Rule findings (``VAL...``), from ``report``.
    """

    pack: TaxonomyPack
    structure: tuple[Finding, ...]
    report: RuleReport | None
    rules: tuple[Finding, ...]

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every finding, structure first."""
        return (*self.structure, *self.rules)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """The findings that stop the return being submitted."""
        return tuple(finding for finding in self.findings if finding.is_blocking)

    @property
    def is_submittable(self) -> bool:
        """Whether nothing found blocks submission.

        True is evidence the return is well-formed, not a guarantee of
        acceptance: the regulator's own validation on upload is authoritative.
        """
        return not self.blocking


def validate_return(
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    rulebook: RuleBook | None = None,
    accuracy: Accuracy | None = None,
    source_findings: Sequence[Finding] = (),
) -> ReturnValidation:
    """Validate ``ret``: structure against the taxonomy, then the published rules.

    Args:
        ret: The return, in canonical form.
        pack: The taxonomy to read it against. Defaults to the packaged pack in
            force for the return's module on its reference date.
        rulebook: The rules to run. Defaults to the packaged rule book for the
            module; a module with none packaged has only its structure checked.
        accuracy: The accuracy facts are stated to where they do not state
            their own (their ``decimals``). It sets the rounding allowance the
            rules' comparisons use, and should be what the file will be written
            with. Defaults to the XBRL writer's defaults.
        source_findings: What reading the return's source found — an XBRL
            instance holding a fact the module does not have, say. They are
            reported first, with the structure findings.

    Returns:
        A ``ReturnValidation``. Never raises for a condition in the data.

    Raises:
        PackNotFoundError: no ``pack`` was given and none is packaged for the
            module and reference date.
    """
    pack = pack or resolve_pack(ret.header.module, ret.header.reference_date)
    structure = (*source_findings, *check_structure(ret, pack))
    module = pack.info.module
    if rulebook is None:
        try:
            rulebook = rulebook_for_module(module)
        except RuleBookNotFoundError:
            logger.warning("no packaged rule book for module %s; rules not run", module)
            return ReturnValidation(pack=pack, structure=structure, report=None, rules=())

    enforced = rulebook.enforced(module)
    results = tuple(evaluate_rules(ret, pack, enforced, accuracy=accuracy))
    report = _report(ret, pack, rulebook, results)
    return ReturnValidation(
        pack=pack, structure=structure, report=report, rules=tuple(findings_for(report))
    )


def findings_for(report: RuleReport) -> list[Finding]:
    """The findings a report yields: the coverage shortfall first, then each broken rule.

    One finding per broken rule, however many times it was unsatisfied: the
    rule code is on ``subject`` and the first unsatisfied evaluation is quoted.
    """
    findings = [
        _rule_finding(result, report) for result in report.results if result.status == STATUS_FAIL
    ]
    shortfall = _coverage_finding(report)
    if shortfall is not None:
        findings.insert(0, shortfall)
    return findings


# =============================================================================
# Private helpers
# =============================================================================


def _report(
    ret: CanonicalReturn, pack: TaxonomyPack, rulebook: RuleBook, results: tuple[RuleResult, ...]
) -> RuleReport:
    """The results with which reported templates the rules reached."""
    reported = tuple(code for code, filed in filing_indicators(ret, pack).items() if filed)

    def indicators(result: RuleResult) -> set[str]:
        return {
            pack.tables[table].filing_indicator for table in result.tables if table in pack.tables
        }

    ruled: set[str] = set()
    covered: set[str] = set()
    for result in results:
        # A rule its own formula cannot fire is not one the gateway runs on
        # the template either: it is not a rule this check failed to reach.
        if result.reason == REASON_CLOSED_BY_FORMULA:
            continue
        ruled |= indicators(result)
        if result.status != STATUS_NOT_EVALUATED:
            covered |= indicators(result)
    return RuleReport(
        module=pack.info.module,
        framework_version=rulebook.framework_version,
        taxonomy=rulebook.taxonomy,
        rules_loaded=len(rulebook.rules),
        results=results,
        templates_reported=reported,
        templates_ruled=tuple(code for code in reported if code in ruled),
        templates_covered=tuple(code for code in reported if code in covered),
    )


def _rule_finding(result: RuleResult, report: RuleReport) -> Finding:
    blocking = result.severity == SEVERITY_ERROR
    consequence = (
        "an Error-severity break rejects the submission"
        if blocking
        else "a Warning-severity break must be explained"
    )
    first = result.failures[0] if result.failures else None
    where = f" at {first.place}" if first is not None and first.place else ""
    cells = f": {'; '.join(first.cells)}" if first is not None and first.cells else ""
    return Finding(
        code=FINDING_RULE_ERROR if blocking else FINDING_RULE_WARNING,
        severity=result.severity,
        message=(
            f"Validation rule {result.rule_id} does not hold in {result.unsatisfied} of "
            f"{result.evaluations} evaluation(s) — {consequence}. First{where}{cells}."
        ),
        reference=(
            f"Bank of England Banking Taxonomy v{report.taxonomy}, validation rule "
            f"{result.rule_id} ({report.framework_version})"
        ),
        subject=result.rule_id,
        expected="the rule to hold in every evaluation",
        actual=f"{result.unsatisfied} unsatisfied evaluation(s)",
    )


def _coverage_finding(report: RuleReport) -> Finding | None:
    """``VAL003`` for whatever ``report.coverage_shortfall`` says."""
    shortfall = report.coverage_shortfall
    if shortfall is None:
        return None
    reasons = ", ".join(
        f"{reason}={count}"
        for reason, count in list(report.not_evaluated_reasons().items())[:_REASONS_QUOTED]
    )
    if shortfall == COVERAGE_NO_RULE_EXECUTED:
        cause = "no rule could be executed at all"
    else:
        cause = (
            "reported template(s) none of whose rules was executed: "
            f"{', '.join(report.templates_uncovered)}"
        )
    return Finding(
        code=FINDING_COVERAGE_INSUFFICIENT,
        severity=SEVERITY_ERROR,
        message=(
            f"Validation coverage is insufficient for {report.module} [{shortfall}]: "
            f"{report.rules_executed} of {report.rules_enforced} enforced rules executed "
            f"({reasons or 'none not evaluated'}); {cause}. An absent break is not evidence "
            "that the return holds."
        ),
        reference=(
            f"Bank of England Banking Taxonomy v{report.taxonomy} validation rules "
            f"({report.framework_version}) — rule coverage"
        ),
        subject=shortfall,
        expected="at least one rule executed on every reported template that has rules",
        actual=f"{report.rules_executed} rule(s) executed",
    )
