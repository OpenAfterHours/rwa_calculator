"""
Validate a canonical return — structure first, then the published rules.

Pipeline position:
    CanonicalReturn  ->  validate_return
        ->  release.choose_release (the release's pack, rule book and deny list)
        ->  structure.check_structure
        ->  boe.engine.evaluate_rules
        ->  validate.execution.apply_deny_list
        ->  validate.issue_labels.label_results (the release's publisher issues)
        ->  ReturnValidation
    the same, keeping every evaluation  ->  trace_return
        ->  (ReturnValidation, boe.engine.RuleTrace)  ->  rwa_filer.evidence

Key responsibilities:
- Be the one call that answers "is this return fit to submit?" for a return in
  canonical form, whatever file or system it came from.
- Run every rule the module ENFORCES, with the taxonomy's own semantics, and
  report each as passed, failed or not evaluated — with the reason. The rules
  always come from the same taxonomy release as the pack the return is read
  against.
- Then configure each result as the Bank's gateway runs it on the run (or
  submission) date: a rule the Bank's deny list deactivates is not evaluated
  (``deactivated_by_publisher``) and is no gap in the check; one it downgrades
  breaks as a Warning (``validate.execution``).
- Then label each result a known issue with the published rule explains
  (``validate.issue_labels``): the release's register names the issue, every
  unsatisfied evaluation is classified inside or outside its footprint, and the
  finding's message says so. A label never changes the verdict: status,
  severity, counts, blocking and the finding's code are untouched.
- Keep the two kinds of finding apart in the result — structure (the taxonomy
  rejects it) and rules (the supervisor's arithmetic does not hold) — and say
  plainly whether anything blocks submission.
- Never let an empty finding list stand for "clean" when little or nothing was
  checked: ``VAL003`` reports a return on which no rule ran — including one
  whose module has no rule book at all — or a reported template none of whose
  rules ran.
- Say whether the check was COMPLETE, separately from whether it passed
  (``ReturnValidation.status``: ``CLEAN`` / ``INCOMPLETE`` / ``BLOCKED``).
  Every cause of incompleteness — no rule book, rules this engine cannot
  evaluate, rules reading a table the pack lacks, linked templates left out, a
  coverage shortfall — is named with the rules and templates it covers, by one
  implementation (``RuleReport.completeness``) that ``VAL003``–``VAL005`` and
  the status all read. ``VAL005`` (a Warning) names the rules that could not be
  evaluated.
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
from dataclasses import dataclass, field, replace
from datetime import date
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.catalogue import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    REASON_DEACTIVATED_BY_PUBLISHER,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
    evaluate_rules,
    trace_rules,
)
from rwa_filer.release import choose_release
from rwa_filer.validate.checker import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_NO_RULEBOOK,
    COVERAGE_TEMPLATE_NOT_COVERED,
    FINDING_COVERAGE_INSUFFICIENT,
    FINDING_LINKED_TEMPLATE_MISSING,
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    FINDING_RULES_NOT_EVALUABLE,
    Finding,
)
from rwa_filer.validate.execution import apply_deny_list, formula_result, trace_as_run
from rwa_filer.validate.issue_labels import label_results, needs_trace, tally
from rwa_filer.validate.structure import check_reference_date, check_structure, filing_indicators

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.boe.engine import RuleResult, RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import CoverageShortfall
    from rwa_filer.validate.identity import SourceIdentity
    from rwa_filer.validate.issue_labels import IssueNote, IssueTally

logger = logging.getLogger(__name__)

#: Not-evaluated reasons quoted in a coverage finding (commonest first).
_REASONS_QUOTED = 4
#: Rule codes quoted in a missing-template finding; the report holds them all.
_RULES_QUOTED = 3

#: What a validation established, in one word. ``BLOCKED``: a finding stops the
#: return being submitted. ``INCOMPLETE``: nothing blocks it, but some of what
#: the module requires checking was not checked (``completeness`` says what).
#: ``CLEAN``: nothing blocks it and nothing was left unchecked.
VERDICT_CLEAN: Final = "CLEAN"
VERDICT_INCOMPLETE: Final = "INCOMPLETE"
VERDICT_BLOCKED: Final = "BLOCKED"

#: Why a validation is incomplete — ``IncompleteCause.code``.
INCOMPLETE_NO_RULEBOOK: Final = "no_rulebook"
INCOMPLETE_RULES_UNSUPPORTED: Final = "rules_unsupported"
INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY: Final = "rules_table_not_in_taxonomy"
INCOMPLETE_LINKED_TEMPLATES_MISSING: Final = "linked_templates_missing"
INCOMPLETE_COVERAGE_SHORTFALL: Final = "coverage_shortfall"

#: The not-evaluated reasons that leave a validation incomplete, and the cause
#: each is reported under. The others are not gaps: ``no_data`` (nothing to
#: check), ``closed_by_formula`` and ``deactivated_by_publisher`` (the gateway
#: never runs the rule either) and ``template_not_reported`` (a gap only where a
#: reported template is read with the absent one — ``linked_templates_missing``).
_NOT_EVALUABLE: Final = (
    (REASON_UNSUPPORTED, INCOMPLETE_RULES_UNSUPPORTED),
    (REASON_UNKNOWN_TABLE, INCOMPLETE_RULES_TABLE_NOT_IN_TAXONOMY),
)


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
        issue_notes: The labels known issues with the published rules put on
            the results (``validate.issue_labels``), in the results' order.
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
    issue_notes: tuple[IssueNote, ...] = ()

    def notes_for(self, rule_id: str) -> tuple[IssueNote, ...]:
        """The labels on ``rule_id``'s result; empty when no known issue explains it."""
        return tuple(note for note in self.issue_notes if note.rule_id == rule_id)

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

    @property
    def completeness(self) -> tuple[IncompleteCause, ...]:
        """Why the check is incomplete, cause by cause; empty when it is complete.

        THE one implementation of "incomplete" for a return with a rule book.
        It reads the same predicates ``VAL003`` (``coverage_shortfall``),
        ``VAL004`` (``templates_missing``) and ``VAL005`` are built from.
        """
        causes: list[IncompleteCause] = []
        shortfall = self.coverage_shortfall
        if shortfall is not None:
            causes.append(
                IncompleteCause(
                    INCOMPLETE_COVERAGE_SHORTFALL,
                    templates=self.templates_uncovered,
                    detail=shortfall,
                )
            )
        for reason, code in _NOT_EVALUABLE:
            rules = tuple(
                result.rule_id
                for result in self.results
                if result.status == STATUS_NOT_EVALUATED and result.reason == reason
            )
            if rules:
                causes.append(IncompleteCause(code, rules=rules, detail=reason))
        if self.templates_missing:
            causes.append(
                IncompleteCause(
                    INCOMPLETE_LINKED_TEMPLATES_MISSING,
                    rules=tuple(
                        sorted({rule for item in self.templates_missing for rule in item.rules})
                    ),
                    templates=tuple(item.code for item in self.templates_missing),
                    detail=REASON_NOT_REPORTED,
                )
            )
        return tuple(causes)

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
class IncompleteCause:
    """One reason a validation did not check everything the module requires.

    Attributes:
        code: One of the ``INCOMPLETE_*`` constants.
        rules: Every enforced rule the cause left unrun, where it is about rules.
        templates: The filing indicators it is about, where it is about templates.
        detail: The machine reason behind it — the not-evaluated reason, or the
            coverage shortfall.
    """

    code: str
    rules: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class ReturnValidation:
    """Everything validating one return established.

    Attributes:
        release: The taxonomy release the return was read against: its pack,
            its rule book, and why it was chosen.
        structure: Structure findings (``STR...``), and any finding from reading
            the return's source (``XBR...``).
        report: The per-rule report, or ``None`` when no rule book is packaged
            for the module.
        rules: Rule findings (``VAL...``), from ``report`` — or, with no rule
            book, the ``VAL003`` that says no rule ran.
        accuracy: The accuracy the rules' comparisons allowed for, where a
            fact does not state its own.
        accuracy_given: Whether the caller chose ``accuracy``, rather than it
            being the default.
        rulebook: The rule book the rules came from.
        source: The file the return was read from, where the caller said.
        release_findings: Findings about the release chosen for the return —
            ``STR011`` when its reference date is outside the release's dates
            for the module. Warnings: they never block.
        deny_date: The date the release's deny list was applied for — the
            submission date when one was given, else the run date. ``None``
            when no rule ran.
    """

    release: Release
    structure: tuple[Finding, ...]
    report: RuleReport | None
    rules: tuple[Finding, ...]
    accuracy: Accuracy = field(default_factory=Accuracy)
    accuracy_given: bool = False
    rulebook: RuleBook | None = field(default=None, compare=False, repr=False)
    source: SourceIdentity | None = None
    release_findings: tuple[Finding, ...] = ()
    deny_date: date | None = None

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

    @property
    def completeness(self) -> tuple[IncompleteCause, ...]:
        """Why the check is incomplete; empty when everything required was checked."""
        if self.report is None:
            return (
                IncompleteCause(
                    INCOMPLETE_NO_RULEBOOK,
                    detail=f"no rule book covers module {self.pack.info.module}",
                ),
            )
        return self.report.completeness

    @property
    def publisher_issues(self) -> tuple[IssueTally, ...]:
        """The known issues with the published rules that label this validation, by issue.

        For a script that must tell "blocked only by breaks a known issue
        explains" from the rest: the verdict itself never says so.
        """
        return tally(self.report.issue_notes) if self.report is not None else ()

    @property
    def status(self) -> str:
        """``BLOCKED``, else ``INCOMPLETE``, else ``CLEAN`` (see ``VERDICT_*``)."""
        if self.blocking:
            return VERDICT_BLOCKED
        return VERDICT_INCOMPLETE if self.completeness else VERDICT_CLEAN


def validate_return(  # noqa: PLR0913 - each a way of saying which release, or how
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    rulebook: RuleBook | None = None,
    release: Release | None = None,
    taxonomy: str | None = None,
    today: date | None = None,
    accuracy: Accuracy | None = None,
    source_findings: Sequence[Finding] = (),
    source: SourceIdentity | None = None,
    submission_date: date | None = None,
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
        source: The file the return was read from (``identity.source_identity``),
            for the report to fingerprint.
        submission_date: The day the return will be submitted. The Bank's
            deny list as it stands on that day decides which rules its gateway
            runs, and as what (``validate.execution``). Defaults to the run
            date — the release's ``run_date``, i.e. ``today``. The return's
            reference date never decides it: the deny list is the gateway's
            configuration, not a property of the return. To validate against
            the taxonomy's rules as published, pass a ``release`` whose
            ``deny_list`` is empty.

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
    validation, _trace = _validate(
        ret, chosen, accuracy, source_findings, source, trace=False, on=submission_date
    )
    return validation


def trace_return(  # noqa: PLR0913 - validate_return's arguments
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    rulebook: RuleBook | None = None,
    release: Release | None = None,
    taxonomy: str | None = None,
    today: date | None = None,
    accuracy: Accuracy | None = None,
    source_findings: Sequence[Finding] = (),
    source: SourceIdentity | None = None,
    submission_date: date | None = None,
) -> tuple[ReturnValidation, RuleTrace | None]:
    """``validate_return``, keeping every evaluation the verdict was reached by.

    One evaluation pass gives both: the validation's rule results ARE the
    trace's, so the evidence cannot describe a different run from the verdict.
    A rule the Bank's deny list deactivates has no evaluations in the trace: it
    is not run at the gateway, so nothing it found is behind the verdict (its
    formula's counts stay on ``RuleResult.formula``). The trace is ``None``
    when the release has no rule book for the module.
    """
    chosen = choose_release(
        ret.header.module,
        release=release,
        pack=pack,
        rulebook=rulebook,
        taxonomy=taxonomy,
        today=today,
    )
    return _validate(ret, chosen, accuracy, source_findings, source, trace=True, on=submission_date)


def findings_for(report: RuleReport) -> list[Finding]:
    """The findings a report yields: what was not checked first, then each broken rule.

    The coverage shortfall (``VAL003``) leads, then one ``VAL004`` per missing
    linked template, then one ``VAL005`` per kind of rule that could not be
    evaluated, then one finding per broken rule, however many times it was
    unsatisfied: the rule code is on ``subject`` and the first unsatisfied
    evaluation is quoted.
    """
    shortfall = _coverage_finding(report)
    not_evaluable = {code for _reason, code in _NOT_EVALUABLE}
    return [
        *([shortfall] if shortfall is not None else []),
        *(_missing_finding(missing, report) for missing in report.templates_missing),
        *(
            _not_evaluable_finding(cause, report)
            for cause in report.completeness
            if cause.code in not_evaluable
        ),
        *(
            _rule_finding(result, report)
            for result in report.results
            if result.status == STATUS_FAIL
        ),
    ]


# =============================================================================
# Private helpers
# =============================================================================


def _validate(
    ret: CanonicalReturn,
    chosen: Release,
    accuracy: Accuracy | None,
    source_findings: Sequence[Finding],
    source: SourceIdentity | None,
    *,
    trace: bool,
    on: date | None,
) -> tuple[ReturnValidation, RuleTrace | None]:
    pack = chosen.pack
    structure = (*source_findings, *check_structure(ret, pack))
    release_findings = tuple(check_reference_date(ret, pack))
    module = pack.info.module
    effective = accuracy or Accuracy()
    given = accuracy is not None
    rulebook = chosen.rulebook
    if rulebook is None:
        logger.warning(
            "taxonomy %s packages no rule book for module %s; no rule can run",
            chosen.version,
            module,
        )
        unchecked = ReturnValidation(
            release=chosen,
            structure=structure,
            report=None,
            rules=(_no_rulebook_finding(module),),
            accuracy=effective,
            accuracy_given=given,
            source=source,
            release_findings=release_findings,
        )
        return unchecked, None

    enforced = rulebook.enforced(module)
    traced = trace_rules(ret, pack, enforced, accuracy=accuracy) if trace else None
    published = (
        traced.results
        if traced is not None
        else tuple(evaluate_rules(ret, pack, enforced, accuracy=accuracy))
    )
    # The gateway's execution configuration, after evaluation: the published
    # verdict stays on each result it changes (``RuleResult.formula``).
    deny_date = on or chosen.run_date
    results = apply_deny_list(published, chosen.deny_list, module, deny_date)
    traced = trace_as_run(traced, results) if traced is not None else None
    notes = _issue_notes(ret, chosen, rulebook, results, traced, accuracy)
    report = replace(_report(ret, pack, rulebook, results), issue_notes=notes)
    validation = ReturnValidation(
        release=chosen,
        structure=structure,
        report=report,
        rules=tuple(findings_for(report)),
        accuracy=effective,
        accuracy_given=given,
        rulebook=rulebook,
        source=source,
        release_findings=release_findings,
        deny_date=deny_date,
    )
    return validation, traced


def _issue_notes(  # noqa: PLR0913 - the parts of one validation the labels read
    ret: CanonicalReturn,
    chosen: Release,
    rulebook: RuleBook,
    results: tuple[RuleResult, ...],
    traced: RuleTrace | None,
    accuracy: Accuracy | None,
) -> tuple[IssueNote, ...]:
    """The labels the release's publisher issues put on ``results``.

    A broken rule an issue applies to only in part (a footprint) has every
    unsatisfied evaluation classified, so it is traced: from the trace when
    there is one, else by ONE more pass over just those rules. That pass is a
    deterministic re-run, never a second verdict — its counts are checked
    against the results, and a difference is logged.
    """
    register = chosen.issues
    module = chosen.pack.info.module
    if not register.issues:
        return ()
    if traced is not None:
        return label_results(results, rulebook, register, module, evaluations=traced.evaluations)
    wanted = needs_trace(results, register, module)
    rules = [rule for rule in rulebook.enforced(module) if rule.rule_id in wanted]
    evaluations = ()
    if rules:
        again = trace_rules(ret, chosen.pack, rules, accuracy=accuracy)
        published = {result.rule_id: formula_result(result) for result in results}
        for result in again.results:
            first = published[result.rule_id]
            if (result.satisfied, result.unsatisfied) != (first.satisfied, first.unsatisfied):
                logger.warning(
                    "tracing %s again for its publisher-issue label gave other counts",
                    result.rule_id,
                )
        evaluations = again.evaluations
    return label_results(results, rulebook, register, module, evaluations=evaluations)


def _report(
    ret: CanonicalReturn, pack: TaxonomyPack, rulebook: RuleBook, results: tuple[RuleResult, ...]
) -> RuleReport:
    """The results with which reported templates the rules reached, and which they missed."""
    declared = filing_indicators(ret, pack)
    reported = tuple(code for code, filed in declared.items() if filed)

    ruled: set[str] = set()
    covered: set[str] = set()
    for result in results:
        # A rule its own formula cannot fire, or one the Bank has deactivated,
        # is not one the gateway runs on the template either: it is not a rule
        # this check failed to reach.
        if result.reason in (REASON_CLOSED_BY_FORMULA, REASON_DEACTIVATED_BY_PUBLISHER):
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
    # A downgrade says so: the published rule is an Error.
    denied = f" The rule was {result.deny.describe()}." if result.deny is not None else ""
    # A known issue with the published rule says so too, and never changes the rest.
    notes = report.notes_for(result.rule_id)
    labels = "".join(f" {note.sentence}" for note in notes)
    return Finding(
        code=FINDING_RULE_ERROR if blocking else FINDING_RULE_WARNING,
        severity=result.severity,
        message=(
            f"Validation rule {result.rule_id} does not hold in {result.unsatisfied} of "
            f"{result.evaluations} evaluation(s) — {consequence}. First{where}{cells}.{denied}"
            f"{labels}"
        ),
        reference=(
            f"Bank of England Banking Taxonomy v{report.taxonomy}, validation rule "
            f"{result.rule_id} ({report.framework_version})"
        ),
        subject=result.rule_id,
        expected="the rule to hold in every evaluation",
        actual=f"{result.unsatisfied} unsatisfied evaluation(s)",
        publisher_issues=tuple(note.issue_id for note in notes),
    )


def _no_rulebook_finding(module: str) -> Finding:
    """``VAL003`` for a module no rule book covers: nothing was checked but structure."""
    return Finding(
        code=FINDING_COVERAGE_INSUFFICIENT,
        severity=SEVERITY_ERROR,
        message=(
            f"Validation coverage is insufficient for {module} [{COVERAGE_NO_RULEBOOK}]: no rule "
            f"book covers the module, so none of its published rules was run. Only the "
            "structure was checked. An absent break is not evidence that the return holds."
        ),
        reference=f"Validation rules for {module} — rule coverage",
        subject=COVERAGE_NO_RULEBOOK,
        expected="a rule book for the module, and its rules run",
        actual="no rule book; 0 rules executed",
    )


def _not_evaluable_finding(cause: IncompleteCause, report: RuleReport) -> Finding:
    """``VAL005`` for the enforced rules one kind of gap left unevaluated."""
    count = len(cause.rules)
    quoted = ", ".join(cause.rules[:_RULES_QUOTED])
    more = f" and {count - _RULES_QUOTED} more" if count > _RULES_QUOTED else ""
    why = (
        "use something this engine does not implement"
        if cause.code == INCOMPLETE_RULES_UNSUPPORTED
        else "read a table the taxonomy pack does not have"
    )
    return Finding(
        code=FINDING_RULES_NOT_EVALUABLE,
        severity=SEVERITY_WARNING,
        message=(
            f"{count} enforced rule(s) {why} ({quoted}{more}), so they were neither passed nor "
            "failed. The gateway runs them; this result says nothing about them, and is "
            "incomplete until they are checked another way."
        ),
        reference=(
            f"Bank of England Banking Taxonomy v{report.taxonomy}, validation rules "
            f"({report.framework_version}) — rules not evaluated: {cause.detail}"
        ),
        subject=cause.code,
        expected="every enforced rule evaluated",
        actual=f"{count} rule(s) not evaluable ({cause.detail})",
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
