"""
Validate a canonical return — structure first, then the published rules.

Pipeline position:
    CanonicalReturn  ->  validate_return
        ->  release.choose_release (the release's pack AND its rule book)
        ->  structure.check_structure
        ->  boe.engine.evaluate_rules
        ->  ReturnValidation

Key responsibilities:
- Be the one call that answers "is this return fit to submit?" for a return in
  canonical form, whatever file or system it came from.
- Run every rule the module ENFORCES, with the taxonomy's own semantics, and
  report each as passed, failed or not evaluated — with the reason. The rules
  always come from the same taxonomy release as the pack the return is read
  against.
- Keep the two kinds of finding apart in the result — structure (the taxonomy
  rejects it) and rules (the supervisor's arithmetic does not hold) — and say
  plainly whether anything blocks submission.
- Never let an empty finding list stand for "clean" when little or nothing was
  checked: ``VAL003`` reports a return on which no rule ran, or a reported
  template none of whose rules ran.
- Name every template the return leaves out that its reported templates are
  checked against (``VAL004``, a Warning). The gateway runs a rule only when
  every template it reads is filed, so leaving one out does not fail those
  rules — it switches them off, and the regulator receives the return without
  that template's figures. Whether the firm must report the template is not
  something the rules can say, so this warns rather than blocks; a template the
  return declares not filed is the return saying so, and is not named.

References:
- BoE XBRL Filing Manual v1.0.1
- Bank of England Banking Taxonomy v4.1.1; validation rule workbooks
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rwa_filer.boe.catalogue import SEVERITY_ERROR, SEVERITY_WARNING
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    REASON_NOT_REPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
    evaluate_rules,
)
from rwa_filer.release import choose_release
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_LINKED_TEMPLATE_MISSING,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    Finding,
)
from rwa_filer.validate.structure import check_reference_date, check_structure, filing_indicators

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import CoverageShortfall

logger = logging.getLogger(__name__)

#: Not-evaluated reasons quoted in a coverage finding (commonest first).
_REASONS_QUOTED = 4
#: Rule codes quoted in a missing-template finding; the report holds them all.
_RULES_QUOTED = 3


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
        templates_missing: Templates the return does not report, and does not
            declare not filed, that enforced rules check a reported template
            against — by filing indicator.
    """

    module: str
    framework_version: str
    taxonomy: str
    rules_loaded: int
    results: tuple[RuleResult, ...]
    templates_reported: tuple[str, ...] = ()
    templates_ruled: tuple[str, ...] = ()
    templates_covered: tuple[str, ...] = ()
    templates_missing: tuple[MissingTemplate, ...] = ()

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
class MissingTemplate:
    """A template left out of the return that the reported templates are checked against.

    Attributes:
        code: Its filing indicator, e.g. ``OF09.02.01``.
        rules: The enforced rules that read it with a reported template, and
            did not run because it is absent.
        linked_from: The reported templates those rules read.
    """

    code: str
    rules: tuple[str, ...]
    linked_from: tuple[str, ...]


@dataclass(frozen=True)
class ReturnValidation:
    """Everything validating one return established.

    Attributes:
        release: The taxonomy release the return was read against: its pack,
            the rule book the rules came from, and why it was chosen.
        structure: Structure findings (``STR...``), and any finding from reading
            the return's source (``XBR...``).
        report: The per-rule report, or ``None`` when the release packages no
            rule book for the module.
        rules: Rule findings (``VAL...``), from ``report``.
        release_findings: Findings about the release chosen for the return —
            ``STR011`` when its reference date is outside the release's dates
            for the module. Warnings: they never block.
    """

    release: Release
    structure: tuple[Finding, ...]
    report: RuleReport | None
    rules: tuple[Finding, ...]
    release_findings: tuple[Finding, ...] = ()

    @property
    def pack(self) -> TaxonomyPack:
        """The taxonomy pack the return was read against."""
        return self.release.pack

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every finding: the release first, then structure, then the rules."""
        return (*self.release_findings, *self.structure, *self.rules)

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
    release: Release | None = None,
    taxonomy: str | None = None,
    today: date | None = None,
    accuracy: Accuracy | None = None,
    source_findings: Sequence[Finding] = (),
) -> ReturnValidation:
    """Validate ``ret``: structure against the taxonomy, then the published rules.

    Args:
        ret: The return, in canonical form.
        pack: The taxonomy pack to read it against. Its rules come from the
            same release. Give at most one of ``pack``, ``release`` and
            ``taxonomy``.
        rulebook: The rules to run, in place of the release's own. A release
            with no rule book for the module has only its structure checked.
        release: A release already resolved (``rwa_filer.release``), e.g. the
            one an XBRL instance was read against.
        taxonomy: The release to use, by version (``"4.1.1"``). With none of
            the three given, the default release for the module: the one live
            on ``today``.
        today: The run date the default and the statuses are worked out for.
            Defaults to today.
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
        ReleaseNotFoundError: the release could not be resolved — see
            ``rwa_filer.release.resolve_release``.
    """
    chosen = choose_release(
        ret.header.module,
        release=release,
        pack=pack,
        rulebook=rulebook,
        taxonomy=taxonomy,
        today=today,
    )
    pack = chosen.pack
    structure = (*source_findings, *check_structure(ret, pack))
    release_findings = tuple(check_reference_date(ret, pack))
    module = pack.info.module
    if chosen.rulebook is None:
        logger.warning(
            "taxonomy %s packages no rule book for module %s; rules not run", chosen.version, module
        )
        return ReturnValidation(
            release=chosen,
            structure=structure,
            report=None,
            rules=(),
            release_findings=release_findings,
        )

    enforced = chosen.rulebook.enforced(module)
    results = tuple(evaluate_rules(ret, pack, enforced, accuracy=accuracy))
    report = _report(ret, pack, chosen.rulebook, results)
    return ReturnValidation(
        release=chosen,
        structure=structure,
        report=report,
        rules=tuple(findings_for(report)),
        release_findings=release_findings,
    )


def findings_for(report: RuleReport) -> list[Finding]:
    """The findings a report yields: what was not checked first, then each broken rule.

    The coverage shortfall (``VAL003``) leads, then one ``VAL004`` per missing
    linked template, then one finding per broken rule, however many times it
    was unsatisfied: the rule code is on ``subject`` and the first unsatisfied
    evaluation is quoted.
    """
    shortfall = _coverage_finding(report)
    return [
        *([shortfall] if shortfall is not None else []),
        *(_missing_finding(missing, report) for missing in report.templates_missing),
        *(
            _rule_finding(result, report)
            for result in report.results
            if result.status == STATUS_FAIL
        ),
    ]


# =============================================================================
# Private helpers
# =============================================================================


def _report(
    ret: CanonicalReturn, pack: TaxonomyPack, rulebook: RuleBook, results: tuple[RuleResult, ...]
) -> RuleReport:
    """The results with which reported templates the rules reached, and which they missed."""
    declared = filing_indicators(ret, pack)
    reported = tuple(code for code, filed in declared.items() if filed)

    ruled: set[str] = set()
    covered: set[str] = set()
    for result in results:
        # A rule its own formula cannot fire is not one the gateway runs on
        # the template either: it is not a rule this check failed to reach.
        if result.reason == REASON_CLOSED_BY_FORMULA:
            continue
        ruled |= _indicators(result, pack)
        if result.status != STATUS_NOT_EVALUATED:
            covered |= _indicators(result, pack)
    return RuleReport(
        module=pack.info.module,
        framework_version=rulebook.framework_version,
        taxonomy=rulebook.taxonomy,
        rules_loaded=len(rulebook.rules),
        results=results,
        templates_reported=reported,
        templates_ruled=tuple(code for code in reported if code in ruled),
        templates_covered=tuple(code for code in reported if code in covered),
        templates_missing=_missing_templates(results, pack, set(reported), set(declared)),
    )


def _indicators(result: RuleResult, pack: TaxonomyPack) -> set[str]:
    """The filing indicators of the templates a rule reads."""
    return {pack.tables[table].filing_indicator for table in result.tables if table in pack.tables}


def _missing_templates(
    results: Sequence[RuleResult], pack: TaxonomyPack, reported: set[str], declared: set[str]
) -> tuple[MissingTemplate, ...]:
    """The templates left unsaid that rules read together with a reported one.

    A rule not run because a template it reads is absent says nothing about
    the return when it reads no reported template either — it is about
    templates this firm does not file. Only a rule that ALSO reads a reported
    template ties the absence to this return. A template the return declares
    not filed is not missing: the return has said so.
    """
    rules: dict[str, set[str]] = {}
    linked: dict[str, set[str]] = {}
    for result in results:
        if result.reason != REASON_NOT_REPORTED:
            continue
        codes = _indicators(result, pack)
        present = codes & reported
        if not present:
            continue
        for code in codes - declared:
            rules.setdefault(code, set()).add(result.rule_id)
            linked.setdefault(code, set()).update(present)
    return tuple(
        MissingTemplate(
            code=code, rules=tuple(sorted(rules[code])), linked_from=tuple(sorted(linked[code]))
        )
        for code in sorted(rules)
    )


def _missing_finding(missing: MissingTemplate, report: RuleReport) -> Finding:
    """``VAL004`` for one template the reported ones are checked against."""
    count = len(missing.rules)
    quoted = ", ".join(missing.rules[:_RULES_QUOTED])
    more = f" and {count - _RULES_QUOTED} more" if count > _RULES_QUOTED else ""
    return Finding(
        code=FINDING_LINKED_TEMPLATE_MISSING,
        severity=SEVERITY_WARNING,
        message=(
            f"Template {missing.code} is not in this return, but {count} enforced rule(s) "
            f"check {', '.join(missing.linked_from)} against it ({quoted}{more}). None of them "
            f"ran, and the gateway does not run them either while {missing.code} is not filed: "
            f"the return can be accepted with them unchecked, and without {missing.code}'s "
            f"figures. Report {missing.code} if the firm is required to; if it is not, a "
            "negative filing indicator for it records that."
        ),
        reference=(
            f"Bank of England Banking Taxonomy v{report.taxonomy}, validation rules "
            f"({report.framework_version}) — rules reading {missing.code} with a reported "
            "template"
        ),
        subject=missing.code,
        expected=f"{missing.code} reported, or declared not filed",
        actual=f"{missing.code} not reported; {count} rule(s) not run",
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
