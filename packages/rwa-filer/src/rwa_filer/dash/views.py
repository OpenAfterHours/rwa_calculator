"""
Page models for one validated return — the overview and the rules.

Pipeline position:
    OpenedReturn (ReturnValidation + RuleReport)  ->  overview / rules_page
        ->  the Jinja templates under dash/templates

Key responsibilities:
- Turn a validation into what a page shows, with every figure taken from the
  validation itself: these functions count and group, they never judge.
- Never let "no breaks" stand alone: the overview always carries how many rules
  ran, how many could not, and why — the same rule ``render_text`` keeps.
- Name the templates the return leaves out that its reported templates are
  checked against, so loading only some templates is never silent.
- Say, on every rule the Bank's validations deny list touches, what the Bank
  did and when — so a rule that is not run, or only warns, is never mistaken
  for one this return passed or this engine could not read.
- Say, on every result a known issue with the published rule explains, which
  issue, where it stands with the Bank and how many of the breaks it explains
  (``validate.issue_labels``) — the verdict beside it unchanged.
- Keep paging, filtering and lookup out of the templates, so a template is
  layout and nothing else.

References:
- rwa_filer.validate.returns — ``ReturnValidation`` / ``RuleReport``
- rwa_filer.validate.report — the text and JSON forms of the same result
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from functools import cache
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.catalogue import SEVERITY_ERROR
from rwa_filer.boe.engine import (
    MAX_FAILURES,
    REASON_CLOSED_BY_FORMULA,
    REASON_DEACTIVATED_BY_PUBLISHER,
    REASON_NO_DATA,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
)
from rwa_filer.release import release_rulebook
from rwa_filer.validate.checker import FINDING_COVERAGE_INSUFFICIENT
from rwa_filer.validate.execution import published_finding
from rwa_filer.validate.report import status_line
from rwa_filer.validate.review import SHOW_ALL, ReviewFilter

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import Failure, RuleResult
    from rwa_filer.boe.issues import PublisherIssue
    from rwa_filer.dash.workspace import OpenedReturn
    from rwa_filer.taxonomy.pack import PackInfo, TaxonomyPack
    from rwa_filer.validate.checker import Finding
    from rwa_filer.validate.issue_labels import IssueNote
    from rwa_filer.validate.returns import MissingTemplate, RuleReport

#: The rule statuses, in the order the pages list them.
STATUSES: Final = (STATUS_FAIL, STATUS_PASS, STATUS_NOT_EVALUATED)
STATUS_LABELS: Final = {
    STATUS_FAIL: "Failed",
    STATUS_PASS: "Passed",
    STATUS_NOT_EVALUATED: "Not evaluated",
}
#: Why a rule was not evaluated, in words.
REASON_TEXT: Final = {
    REASON_NOT_REPORTED: "it reads a template this return does not file",
    REASON_NO_DATA: "every cell it reads is empty in this return",
    REASON_CLOSED_BY_FORMULA: "the taxonomy's own formula cannot bind the cells reported here",
    REASON_UNKNOWN_TABLE: "it reads a table this module's taxonomy does not have",
    REASON_UNSUPPORTED: "it uses something this engine does not implement",
    REASON_DEACTIVATED_BY_PUBLISHER: (
        "the Bank of England has switched it off at its gateway: firms are not expected to meet it"
    ),
}
#: Rules listed per page of the rules list.
RULES_PER_PAGE: Final = 100
#: Broken rules quoted on the overview.
BREAKS_SHOWN: Final = 8
#: Breaks of the picked rule the rules page lists — as many as a report records.
#: The workspace keeps every one, for the grid; the page says how many there are.
FAILURES_LISTED: Final = MAX_FAILURES


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class TemplateSummary:
    """One reported template: its cells and the rules that touch it."""

    code: str
    title: str
    tables: tuple[str, ...]
    cells: int
    passed: int
    failed: int
    visible_failed: int
    not_evaluated: int

    @property
    def rules(self) -> int:
        return self.passed + self.failed + self.not_evaluated


@dataclass(frozen=True)
class MissingSummary:
    """A template left out that the reported templates are checked against."""

    code: str
    title: str
    rules: int
    linked_from: tuple[str, ...]


@dataclass(frozen=True)
class RuleRow:
    """One rule as a list shows it."""

    rule_id: str
    severity: str
    status: str
    label: str
    templates: tuple[str, ...]
    satisfied: int
    unsatisfied: int
    reason: str
    #: What the Bank's validations deny list did to the rule, in words; empty
    #: when it is not on the list.
    deny: str = ""
    #: The known issues with the published rule that label its result.
    issues: tuple[IssueNote, ...] = ()
    hidden: int = 0

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    @property
    def evaluations(self) -> int:
        return self.satisfied + self.unsatisfied


@dataclass(frozen=True)
class Overview:
    """Whether a return is fit to file, and the counts behind the answer."""

    submittable: bool
    status: str
    status_line: str
    blocking: int
    structure: tuple[Finding, ...]
    rule_findings: tuple[Finding, ...]
    shortfall: Finding | None
    rule_book: str | None
    enforced: int
    executed: int
    status_counts: dict[str, int]
    reasons: tuple[tuple[str, int, str], ...]
    templates: tuple[TemplateSummary, ...]
    missing: tuple[MissingSummary, ...]
    missing_rules: int
    breaks: tuple[RuleRow, ...]
    errors: int
    warnings: int

    def share(self, status: str) -> float:
        """The share of enforced rules with ``status``, as a percentage."""
        return 100 * self.status_counts.get(status, 0) / self.enforced if self.enforced else 0.0


@dataclass(frozen=True)
class RuleDetail:
    """One rule in full: what it says, and where it broke.

    ``published`` is what the published rule found on this return where the
    Bank's deny list changed its outcome (e.g. ``the published rule breaks 3 of
    7 evaluation(s) here``); empty otherwise.
    """

    row: RuleRow
    expression: str
    scope: str | None
    detail: str
    reason_text: str
    failures: tuple[Failure, ...]
    published: str = ""
    #: Each known issue that labels the result, with the issue itself.
    issues: tuple[IssueCallout, ...] = ()


@dataclass(frozen=True)
class IssueCallout:
    """A known issue's label on a rule, with the issue it comes from, for a callout."""

    note: IssueNote
    issue: PublisherIssue

    @property
    def quote(self) -> str:
        """The first passage of the instructions the issue rests on; empty if none."""
        return self.issue.authority[0].quote if self.issue.authority else ""


@dataclass(frozen=True)
class RulesPage:
    """The rules list as filtered, one page of it, and the rule picked."""

    status: str
    severity: str
    query: str
    template: str
    counts: dict[str, int]
    templates: tuple[str, ...]
    rows: tuple[RuleRow, ...]
    matched: int
    page: int
    pages: int
    selected: RuleDetail | None
    review: ReviewFilter
    hidden_errors: int
    hidden_warnings: int


def overview(opened: OpenedReturn, *, review: ReviewFilter = SHOW_ALL) -> Overview:
    """The overview of one validated return."""
    validation = opened.validation
    report = validation.report
    results = report.results if report else ()
    rows = [_row(result, opened.pack, report, review) for result in results]
    breaks = sorted(
        (row for row in rows if row.status == STATUS_FAIL),
        key=lambda row: (not row.is_error, row.rule_id),
    )
    shortfall = next(
        (item for item in validation.rules if item.code == FINDING_COVERAGE_INSUFFICIENT), None
    )
    missing = report.templates_missing if report else ()
    return Overview(
        submittable=validation.is_submittable,
        status=validation.status,
        status_line=status_line(validation),
        blocking=len(validation.blocking),
        structure=validation.structure,
        rule_findings=validation.rules,
        shortfall=shortfall,
        rule_book=f"{report.framework_version} {report.taxonomy}" if report else None,
        enforced=report.rules_enforced if report else 0,
        executed=report.rules_executed if report else 0,
        status_counts=report.status_counts() if report else {},
        reasons=tuple(
            (reason, count, REASON_TEXT.get(reason, reason))
            for reason, count in (report.not_evaluated_reasons() if report else {}).items()
        ),
        templates=_templates(opened, rows),
        missing=_missing(opened.pack, missing),
        missing_rules=len({rule_id for item in missing for rule_id in item.rules}),
        breaks=tuple(row for row in breaks if row.unsatisfied > row.hidden)[:BREAKS_SHOWN],
        errors=sum(row.is_error for row in breaks),
        warnings=sum(not row.is_error for row in breaks),
    )


def rules_page(  # noqa: PLR0913 - one keyword per filter the page takes
    opened: OpenedReturn,
    *,
    status: str = STATUS_FAIL,
    severity: str = "",
    query: str = "",
    template: str = "",
    rule_id: str = "",
    page: int = 1,
    review: ReviewFilter = SHOW_ALL,
) -> RulesPage:
    """The rules page: ``status`` filtered by severity, template and text, paged."""
    report = opened.validation.report
    results = report.results if report else ()
    status = status if status in STATUSES else STATUS_FAIL
    if review.errors_only:
        severity = ""  # The return-wide setting takes precedence over a tab's previous selection.
    rows = [
        _row(result, opened.pack, report, review)
        for result in results
        if result.status == STATUS_FAIL or not review.hides_severity(result.severity)
    ]
    counts = Counter(row.status for row in rows)
    matched = _matched(rows, status, severity, template, query)
    hidden_errors = hidden_warnings = 0
    if status == STATUS_FAIL and review.active:
        hidden_errors = sum(row.hidden for row in matched if row.is_error)
        hidden_warnings = sum(row.hidden for row in matched if not row.is_error)
        matched = [row for row in matched if row.unsatisfied > row.hidden]
    pages = max(1, math.ceil(len(matched) / RULES_PER_PAGE))
    page = min(max(page, 1), pages)
    shown = matched[(page - 1) * RULES_PER_PAGE : page * RULES_PER_PAGE]
    picked = next((row for row in matched if row.rule_id == rule_id), None)
    if picked is None and rule_id and not review.active:
        picked = next((row for row in rows if row.rule_id == rule_id), None)
    if picked is None and shown:
        picked = shown[0]
    detail = (
        _detail(opened, picked, next(r for r in results if r.rule_id == picked.rule_id), review)
        if picked
        else None
    )
    return RulesPage(
        review=review,
        hidden_errors=hidden_errors,
        hidden_warnings=hidden_warnings,
        status=status,
        severity=severity,
        query=query,
        template=template,
        counts={item: counts.get(item, 0) for item in STATUSES},
        templates=tuple(sorted({code for row in rows for code in row.templates})),
        rows=tuple(shown),
        matched=len(matched),
        page=page,
        pages=pages,
        selected=_listed(detail) if detail else None,
    )


def failed_rule_details(
    opened: OpenedReturn, *, severity: str, template: str, query: str, review: ReviewFilter
) -> tuple[RuleDetail, ...]:
    """Every visible failure for the current filters, before either display limit."""
    report = opened.validation.report
    if report is None:
        return ()
    failed = {result.rule_id: result for result in report.results if result.status == STATUS_FAIL}
    rows = [_row(result, opened.pack, report, review) for result in failed.values()]
    matches = _matched(rows, STATUS_FAIL, "" if review.errors_only else severity, template, query)
    return tuple(
        _detail(opened, row, failed[row.rule_id], review)
        for row in matches
        if row.unsatisfied > row.hidden
    )


def _matched(
    rows: list[RuleRow], status: str, severity: str, template: str, query: str
) -> list[RuleRow]:
    needle = query.strip().lower()
    matched = [
        row
        for row in rows
        if row.status == status
        and (not severity or row.severity == severity)
        and (not template or template in row.templates)
        and (not needle or needle in f"{row.rule_id} {row.label}".lower())
    ]
    if status == STATUS_FAIL:
        matched.sort(key=lambda row: (not row.is_error, row.rule_id))
    return matched


def rule_detail(
    opened: OpenedReturn, rule_id: str, review: ReviewFilter = SHOW_ALL
) -> RuleDetail | None:
    """One rule of the return in full, or ``None`` when the report holds no result for it.

    In full includes every break the validation recorded — all of them, in the
    workspace — so the grid's cell panel can find the ones that read its cell.
    """
    report = opened.validation.report
    results = report.results if report else ()
    result = next((item for item in results if item.rule_id == rule_id), None)
    return (
        _detail(opened, _row(result, opened.pack, report, review), result, review)
        if result
        else None
    )


def rule_label(info: PackInfo, rule_id: str) -> str:
    """The publisher's short description of a rule, or empty when it gives none.

    ``info`` is the pack the return was read against: the rule is looked up in
    the same release's rule book.
    """
    rule = _rule(info.version, info.module, rule_id)
    return (rule.label or "").rstrip("|").strip() if rule else ""


def title_case(title: str) -> str:
    """A taxonomy title in sentence case, its parenthesised short name kept as is.

    The publisher writes most titles in capitals; ``"OWN FUNDS REQUIREMENTS
    (CA2)"`` reads as ``"Own funds requirements (CA2)"``.
    """
    head, bracket, tail = title.partition("(")
    sentence = head.strip().lower().capitalize()
    for acronym in ("irb", "sa", "pd", "rwa", "crm", "sme", "ccr"):
        sentence = " ".join(
            word.upper() if word.strip(",:;") == acronym else word for word in sentence.split(" ")
        )
    return f"{sentence} ({tail}" if bracket else sentence


# =============================================================================
# Private helpers
# =============================================================================


def _row(
    result: RuleResult, pack: TaxonomyPack, report: RuleReport | None, review: ReviewFilter
) -> RuleRow:
    return RuleRow(
        rule_id=result.rule_id,
        severity=result.severity,
        status=result.status,
        label=rule_label(pack.info, result.rule_id),
        templates=tuple(
            sorted(
                {
                    pack.tables[table].filing_indicator
                    for table in result.tables
                    if table in pack.tables
                }
            )
        ),
        satisfied=result.satisfied,
        unsatisfied=result.unsatisfied,
        hidden=review.hidden_count(result) if result.status == STATUS_FAIL else 0,
        reason=result.reason,
        deny=result.deny.describe() if result.deny is not None else "",
        issues=report.notes_for(result.rule_id) if report is not None else (),
    )


def _detail(
    opened: OpenedReturn, row: RuleRow, result: RuleResult, review: ReviewFilter
) -> RuleDetail:
    rule = _rule(opened.release.version, opened.pack.info.module, row.rule_id)
    return RuleDetail(
        row=row,
        expression=rule.expression if rule else "",
        scope=rule.scope if rule else None,
        detail=result.detail,
        reason_text=REASON_TEXT.get(result.reason, result.reason),
        failures=review.visible(result) if row.status == STATUS_FAIL else result.failures,
        published=published_finding(result.formula) if result.formula is not None else "",
        issues=tuple(
            IssueCallout(note=note, issue=issue)
            for note in row.issues
            if (issue := opened.release.issues.issue(note.issue_id)) is not None
        ),
    )


def _listed(detail: RuleDetail) -> RuleDetail:
    """``detail`` with its first ``FAILURES_LISTED`` breaks, as the rules page lists them."""
    return replace(detail, failures=detail.failures[:FAILURES_LISTED])


def _rule(version: str, module: str, rule_id: str) -> Rule | None:
    return _rules_by_id(version, module).get(rule_id)


@cache
def _rules_by_id(version: str, module: str) -> dict[str, Rule]:
    """Release ``version``'s rule book for the module, by rule code.

    Cached: packaged rule books never change.
    """
    rulebook = release_rulebook(version, module)
    return {rule.rule_id: rule for rule in rulebook.rules} if rulebook is not None else {}


def _templates(opened: OpenedReturn, rows: list[RuleRow]) -> tuple[TemplateSummary, ...]:
    pack = opened.pack
    report = opened.validation.report
    statuses: dict[str, Counter[str]] = {}
    visible_failed: Counter[str] = Counter()
    for row in rows:
        for code in row.templates:
            statuses.setdefault(code, Counter())[row.status] += 1
            if row.status == STATUS_FAIL and row.unsatisfied > row.hidden:
                visible_failed[code] += 1
    facts = opened.ret.facts
    tables_by_indicator: dict[str, list[str]] = {}
    cells: Counter[str] = Counter()
    for table, count in facts.group_by("table").len().iter_rows():
        indicator = pack.tables[table].filing_indicator if table in pack.tables else table
        tables_by_indicator.setdefault(indicator, []).append(table)
        cells[indicator] += count
    reported = report.templates_reported if report else tuple(sorted(tables_by_indicator))
    summaries = []
    for code in reported:
        tables = tuple(sorted(tables_by_indicator.get(code, ())))
        title = pack.tables[tables[0]].title if tables and tables[0] in pack.tables else code
        counts = statuses.get(code, Counter())
        summaries.append(
            TemplateSummary(
                code=code,
                title=title_case(title),
                tables=tables,
                cells=cells.get(code, 0),
                passed=counts[STATUS_PASS],
                failed=counts[STATUS_FAIL],
                visible_failed=visible_failed[code],
                not_evaluated=counts[STATUS_NOT_EVALUATED],
            )
        )
    return tuple(summaries)


def _missing(
    pack: TaxonomyPack, missing: tuple[MissingTemplate, ...]
) -> tuple[MissingSummary, ...]:
    """The missing linked templates with their titles, the most-checked first."""
    titles: dict[str, str] = {}
    for code in sorted(pack.tables):
        titles.setdefault(pack.tables[code].filing_indicator, pack.tables[code].title)
    ranked = sorted(missing, key=lambda item: (-len(item.rules), item.code))
    return tuple(
        MissingSummary(
            code=item.code,
            title=title_case(titles[item.code]) if item.code in titles else item.code,
            rules=len(item.rules),
            linked_from=item.linked_from,
        )
        for item in ranked
    )
