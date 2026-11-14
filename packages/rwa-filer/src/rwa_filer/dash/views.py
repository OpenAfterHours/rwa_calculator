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
- Keep paging, filtering and lookup out of the templates, so a template is
  layout and nothing else.

References:
- rwa_filer.validate.returns — ``ReturnValidation`` / ``RuleReport``
- rwa_filer.validate.report — the text and JSON forms of the same result
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.catalogue import SEVERITY_ERROR, RuleBookNotFoundError, rulebook_for_module
from rwa_filer.boe.engine import (
    REASON_CLOSED_BY_FORMULA,
    REASON_NO_DATA,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
)
from rwa_filer.validate.checker import FINDING_COVERAGE_INSUFFICIENT

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import Failure, RuleResult
    from rwa_filer.dash.workspace import OpenedReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding

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
}
#: Rules listed per page of the rules list.
RULES_PER_PAGE: Final = 100
#: Broken rules quoted on the overview.
BREAKS_SHOWN: Final = 8


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
    not_evaluated: int

    @property
    def rules(self) -> int:
        return self.passed + self.failed + self.not_evaluated


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
    breaks: tuple[RuleRow, ...]
    errors: int
    warnings: int

    def share(self, status: str) -> float:
        """The share of enforced rules with ``status``, as a percentage."""
        return 100 * self.status_counts.get(status, 0) / self.enforced if self.enforced else 0.0


@dataclass(frozen=True)
class RuleDetail:
    """One rule in full: what it says, and where it broke."""

    row: RuleRow
    expression: str
    scope: str | None
    detail: str
    reason_text: str
    failures: tuple[Failure, ...]


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


def overview(opened: OpenedReturn) -> Overview:
    """The overview of one validated return."""
    validation = opened.validation
    report = validation.report
    results = report.results if report else ()
    rows = [_row(result, opened.pack) for result in results]
    breaks = sorted(
        (row for row in rows if row.status == STATUS_FAIL),
        key=lambda row: (not row.is_error, row.rule_id),
    )
    shortfall = next(
        (item for item in validation.rules if item.code == FINDING_COVERAGE_INSUFFICIENT), None
    )
    return Overview(
        submittable=validation.is_submittable,
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
        templates=_templates(opened, results),
        breaks=tuple(breaks[:BREAKS_SHOWN]),
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
) -> RulesPage:
    """The rules page: ``status`` filtered by severity, template and text, paged."""
    report = opened.validation.report
    results = report.results if report else ()
    status = status if status in STATUSES else STATUS_FAIL
    rows = [_row(result, opened.pack) for result in results]
    counts = Counter(row.status for row in rows)
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
    pages = max(1, math.ceil(len(matched) / RULES_PER_PAGE))
    page = min(max(page, 1), pages)
    shown = matched[(page - 1) * RULES_PER_PAGE : page * RULES_PER_PAGE]
    picked = next((row for row in matched if row.rule_id == rule_id), None)
    if picked is None and rule_id:
        picked = next((row for row in rows if row.rule_id == rule_id), None)
    if picked is None and shown:
        picked = shown[0]
    return RulesPage(
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
        selected=_detail(opened, picked, results) if picked else None,
    )


def rule_label(module: str, rule_id: str) -> str:
    """The publisher's short description of a rule, or empty when it gives none."""
    rule = _rule(module, rule_id)
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


def _row(result: RuleResult, pack: TaxonomyPack) -> RuleRow:
    return RuleRow(
        rule_id=result.rule_id,
        severity=result.severity,
        status=result.status,
        label=rule_label(pack.info.module, result.rule_id),
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
        reason=result.reason,
    )


def _detail(opened: OpenedReturn, row: RuleRow, results: tuple[RuleResult, ...]) -> RuleDetail:
    result = next(item for item in results if item.rule_id == row.rule_id)
    rule = _rule(opened.pack.info.module, row.rule_id)
    return RuleDetail(
        row=row,
        expression=rule.expression if rule else "",
        scope=rule.scope if rule else None,
        detail=result.detail,
        reason_text=REASON_TEXT.get(result.reason, result.reason),
        failures=result.failures,
    )


def _rule(module: str, rule_id: str) -> Rule | None:
    return _rules_by_id(module).get(rule_id)


@cache
def _rules_by_id(module: str) -> dict[str, Rule]:
    """The module's rule book by rule code. Cached: packaged rule books never change."""
    try:
        return {rule.rule_id: rule for rule in rulebook_for_module(module).rules}
    except RuleBookNotFoundError:
        return {}


def _templates(
    opened: OpenedReturn, results: tuple[RuleResult, ...]
) -> tuple[TemplateSummary, ...]:
    pack = opened.pack
    report = opened.validation.report
    statuses: dict[str, Counter[str]] = {}
    for result in results:
        for code in {pack.tables[t].filing_indicator for t in result.tables if t in pack.tables}:
            statuses.setdefault(code, Counter())[result.status] += 1
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
                not_evaluated=counts[STATUS_NOT_EVALUATED],
            )
        )
    return tuple(summaries)
