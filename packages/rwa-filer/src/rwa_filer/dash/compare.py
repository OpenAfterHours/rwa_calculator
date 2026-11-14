"""
Comparing two versions of a return — the page model of the Compare page.

Pipeline position:
    two OpenedReturns  ->  compare_page  ->  workflow.diff.diff_returns
        ->  dash/templates/compare.html

Key responsibilities:
- Say, cell by cell, what changed between an earlier and a later version — the
  difference ``rwa-filer diff`` prints — filtered by kind of change and table,
  and paged.
- Say what the change did to the verdict: which broken rules the later version
  fixed, which it newly breaks, and the blocking findings before and after —
  the question a resubmission has to answer.

References:
- rwa_filer.workflow.diff — what "changed" means
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.context import format_count
from rwa_filer.dash.views import rule_label
from rwa_filer.workflow.diff import CHANGE_ADDED, CHANGE_CHANGED, CHANGE_REMOVED, diff_returns

if TYPE_CHECKING:
    from rwa_filer.dash.workspace import OpenedReturn

#: The kinds of change, in the order the page lists them.
KINDS: Final = (CHANGE_CHANGED, CHANGE_ADDED, CHANGE_REMOVED)
#: Changed cells listed per page.
CHANGES_PER_PAGE: Final = 100


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


def compare_page(
    earlier: OpenedReturn,
    later: OpenedReturn,
    *,
    kind: str = "",
    table: str = "",
    page: int = 1,
) -> ComparePage:
    """What changed from ``earlier`` to ``later``, cell by cell and rule by rule."""
    difference = diff_returns(earlier.ret, later.ret)
    changes = difference.changes
    tables = _tables(changes)
    shown = changes
    if kind in KINDS:
        shown = shown.filter(pl.col("change") == kind)
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
