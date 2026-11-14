"""
Comparing two versions of a return — the page model of the Compare page.

Pipeline position:
    two OpenedReturns  ->  compare_page  ->  workflow.diff.diff_returns
                                          ->  workflow.compare (Workspace.comparison)
        ->  dash/templates/compare.html

Key responsibilities:
- Say why the two differ, before listing how: the comparison's findings, each
  with what the Bank's rules point at (the earlier return, the later one, the
  inputs both were calculated from, or neither), and every cell's category —
  the same, rounding, a zero against a blank, scope, or material.
- Say, cell by cell, what changed between an earlier and a later version — the
  difference ``rwa-filer diff`` prints — filtered by kind of change, category,
  finding and table, and paged.
- Say what the change did to the verdict: which broken rules the later version
  fixed, which it newly breaks, and the blocking findings before and after —
  the question a resubmission has to answer.

The earlier return is the comparison's baseline and the later its candidate:
the filing already made against its resubmission, or the current system's
return against rwa-filer's.

References:
- rwa_filer.workflow.diff — what "changed" means
- rwa_filer.workflow.compare / explain — the categories and the findings
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.context import format_count
from rwa_filer.dash.views import rule_label
from rwa_filer.workflow.compare import compare_returns
from rwa_filer.workflow.diff import CHANGE_ADDED, CHANGE_CHANGED, CHANGE_REMOVED, diff_returns
from rwa_filer.workflow.explain import (
    CATEGORY_MATERIAL,
    CATEGORY_ROUNDING,
    CATEGORY_SAME,
    CATEGORY_SCOPE,
    CATEGORY_ZERO_OR_BLANK,
    POINTS_AT_INPUTS,
    SIDE_BASELINE,
    SIDE_CANDIDATE,
    Discrepancy,
    Names,
)

if TYPE_CHECKING:
    from rwa_filer.dash.workspace import OpenedReturn
    from rwa_filer.workflow.compare import ReturnComparison

#: The kinds of change, in the order the page lists them.
KINDS: Final = (CHANGE_CHANGED, CHANGE_ADDED, CHANGE_REMOVED)
#: Changed cells listed per page.
CHANGES_PER_PAGE: Final = 100
#: The categories a cell can be filtered by, as the page names them.
CATEGORY_LABELS: Final = {
    CATEGORY_MATERIAL: "Material",
    CATEGORY_ROUNDING: "Within rounding",
    CATEGORY_ZERO_OR_BLANK: "Zero or blank",
    CATEGORY_SCOPE: "Template filed by one side",
    CATEGORY_SAME: "Same",
}
#: How a finding's "points at" is drawn.
_POINTS_CHIP: Final = {
    SIDE_BASELINE: "chip-warn",
    SIDE_CANDIDATE: "chip-warn",
    POINTS_AT_INPUTS: "chip-accent",
}


@dataclass(frozen=True)
class TableChanges:
    """How many cells of one table changed, by kind."""

    table: str
    changed: int
    added: int
    removed: int

    @property
    def total(self) -> int:
        return self.changed + self.added + self.removed


@dataclass(frozen=True)
class ChangedCell:
    """One cell that differs, as the page lists it."""

    table: str
    sheet: str | None
    open_key: str | None
    row: str
    column: str
    change: str
    before: str
    after: str
    delta: str
    category: str = ""
    finding: int | None = None

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, "")

    @property
    def address(self) -> str:
        sheet = f"[z{self.sheet}]" if self.sheet else ""
        key = f"[{self.open_key}]" if self.open_key else ""
        return f"{self.table}{sheet}{key}[r{self.row}][c{self.column}]"


@dataclass(frozen=True)
class RuleChange:
    """A broken rule one version has and the other does not."""

    rule_id: str
    severity: str
    label: str


@dataclass(frozen=True)
class RuleStandingView:
    """A rule as each version stands against it, with the publisher's label."""

    rule_id: str
    label: str
    earlier: str
    later: str


@dataclass(frozen=True)
class FindingView:
    """One finding of the comparison, as the page lists it."""

    number: int
    points_at: str
    chip: str
    title: str
    detail: str
    cells: int
    rules: tuple[RuleStandingView, ...]


@dataclass(frozen=True)
class ComparePage:
    """Two versions of a return, side by side."""

    earlier: OpenedReturn
    later: OpenedReturn
    identical: bool
    counts: dict[str, int]
    unchanged: int
    header: dict[str, tuple[str | None, str | None]]
    tables: tuple[TableChanges, ...]
    cells: tuple[ChangedCell, ...]
    matched: int
    kind: str
    table: str
    page: int
    pages: int
    fixed: tuple[RuleChange, ...]
    broken: tuple[RuleChange, ...]
    still_broken: int
    blocking_before: int
    blocking_after: int
    comparison: ReturnComparison
    findings: tuple[FindingView, ...]
    category: str = ""
    finding: int = 0

    @property
    def categories(self) -> list[tuple[str, str, int]]:
        """``(category, label, cells)`` for every category with a cell in it."""
        counts = self.comparison.counts()
        return [(key, label, counts[key]) for key, label in CATEGORY_LABELS.items() if counts[key]]


def compare_page(  # noqa: PLR0913 - the two returns and every filter of the page
    earlier: OpenedReturn,
    later: OpenedReturn,
    *,
    kind: str = "",
    table: str = "",
    page: int = 1,
    category: str = "",
    finding: int = 0,
    comparison: ReturnComparison | None = None,
) -> ComparePage:
    """What changed from ``earlier`` to ``later``, why, cell by cell and rule by rule.

    ``comparison`` is the pair's comparison when the caller holds it already
    (the workspace keeps one per pair); otherwise it is worked out here.
    """
    if comparison is None:
        comparison = compare_returns(
            earlier.reading, later.reading, names=Names(earlier.name, later.name)
        )
    difference = diff_returns(earlier.ret, later.ret)
    changes = _with_categories(difference.changes, comparison)
    tables = _tables(changes)
    shown = changes
    if kind in KINDS:
        shown = shown.filter(pl.col("change") == kind)
    if category in CATEGORY_LABELS:
        shown = shown.filter(pl.col("category") == category)
    if finding:
        shown = shown.filter(pl.col("finding") == finding)
    if table:
        shown = shown.filter(pl.col("table") == table)
    pages = max(1, math.ceil(shown.height / CHANGES_PER_PAGE))
    page = min(max(page, 1), pages)
    window = shown.slice((page - 1) * CHANGES_PER_PAGE, CHANGES_PER_PAGE)
    before_breaks = _broken(earlier)
    after_breaks = _broken(later)
    module = later.pack.info.module
    return ComparePage(
        earlier=earlier,
        later=later,
        identical=difference.is_identical,
        counts=difference.counts(),
        unchanged=difference.unchanged,
        header=difference.header,
        tables=tables,
        cells=tuple(_cell(row) for row in window.iter_rows(named=True)),
        matched=shown.height,
        kind=kind if kind in KINDS else "",
        table=table,
        page=page,
        pages=pages,
        fixed=_rule_changes(module, before_breaks, set(after_breaks)),
        broken=_rule_changes(module, after_breaks, set(before_breaks)),
        still_broken=len(set(before_breaks) & set(after_breaks)),
        blocking_before=len(earlier.validation.blocking),
        blocking_after=len(later.validation.blocking),
        comparison=comparison,
        findings=tuple(_finding(item, comparison, module) for item in comparison.findings),
        category=category if category in CATEGORY_LABELS else "",
        finding=finding,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _tables(changes: pl.DataFrame) -> tuple[TableChanges, ...]:
    counts: dict[str, dict[str, int]] = {}
    for table, change, number in changes.group_by("table", "change").len().iter_rows():
        counts.setdefault(table, {})[change] = number
    return tuple(
        TableChanges(
            table=table,
            changed=found.get(CHANGE_CHANGED, 0),
            added=found.get(CHANGE_ADDED, 0),
            removed=found.get(CHANGE_REMOVED, 0),
        )
        for table, found in sorted(counts.items())
    )


def _with_categories(changes: pl.DataFrame, comparison: ReturnComparison) -> pl.DataFrame:
    """Each changed cell with its category and the finding that explains it."""
    coordinates = ["table", "sheet", "open_key", "row", "column"]
    found = comparison.cells.select(*coordinates, "category", "finding")
    return changes.join(found, on=coordinates, how="left", nulls_equal=True)


def _finding(item: Discrepancy, comparison: ReturnComparison, module: str) -> FindingView:
    names = comparison.names
    points = {
        SIDE_BASELINE: names.baseline,
        SIDE_CANDIDATE: names.candidate,
        POINTS_AT_INPUTS: "the inputs",
    }.get(item.points_at, "neither return")
    return FindingView(
        number=item.number,
        points_at=points,
        chip=_POINTS_CHIP.get(item.points_at, "chip-ne"),
        title=item.title,
        detail=item.detail,
        cells=len(item.cells),
        rules=tuple(
            RuleStandingView(
                rule_id=rule.rule_id,
                label=rule_label(module, rule.rule_id),
                earlier=rule.baseline,
                later=rule.candidate,
            )
            for rule in item.rules
        ),
    )


def _cell(row: dict[str, Any]) -> ChangedCell:
    return ChangedCell(
        table=row["table"],
        sheet=row["sheet"],
        open_key=row["open_key"],
        row=row["row"],
        column=row["column"],
        change=row["change"],
        before=_figure(row["before"], row["before_text"]),
        after=_figure(row["after"], row["after_text"]),
        delta="" if row["delta"] is None else _signed(row["delta"]),
        category=row.get("category") or "",
        finding=row.get("finding"),
    )


def _figure(value: float | None, text: str | None) -> str:
    """A figure as the page shows it: whole amounts grouped, ratios to six places."""
    if value is None:
        return text or ""
    if float(value).is_integer():
        return format_count(round(value))
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.6g}"


def _signed(delta: float) -> str:
    shown = _figure(abs(delta), None)
    return f"+{shown}" if delta > 0 else (f"−{shown}" if delta < 0 else "0")


def _broken(opened: OpenedReturn) -> dict[str, str]:
    """The rules a version breaks, with their severity."""
    report = opened.validation.report
    return {
        result.rule_id: result.severity
        for result in (report.results if report else ())
        if result.status == STATUS_FAIL
    }


def _rule_changes(module: str, breaks: dict[str, str], other: set[str]) -> tuple[RuleChange, ...]:
    return tuple(
        RuleChange(rule_id, severity, rule_label(module, rule_id))
        for rule_id, severity in sorted(breaks.items())
        if rule_id not in other
    )
