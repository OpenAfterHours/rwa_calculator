"""
Page models for a return opened with breakdown columns — the cell panel's split and the Investigate page.

Pipeline position:
    OpenedReturn.detail (readers.detail)  +  Attribution (workflow.attribution)
        ->  cell_split / cell_breaks / investigate_page / breakdown_summary
        ->  templates.html, investigate.html, overview.html

Key responsibilities:
- Split the picked cell by one breakdown column: each member's amount, its
  share, and the part of the figure that is in no member's rows — an override
  drafted on the summed figure.
- Set each member's figures beside the return's for the broken rules that read
  the picked cell, and say in one sentence where the break is.
- Lay out the Investigate page: which members break which rules, by how much,
  what the total hides, and a note to send to the person who owns a member's
  figures, with every figure taken from the attribution.
- Count and arrange, never judge: every verdict comes from the engine, through
  ``workflow.attribution``.

References:
- rwa_filer.workflow.attribution — what a member breaking a rule means
- rwa_filer.readers.detail — the rows a return was summed from
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, replace
from itertools import groupby
from operator import attrgetter
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.boe.catalogue import SEVERITY_ERROR
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.views import rule_label
from rwa_filer.readers.detail import address
from rwa_filer.release import long_date
from rwa_filer.workflow.attribution import amount_text, member_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.dash.workspace import OpenedReturn, WorkingReturn
    from rwa_filer.readers.detail import Cell, Member, ReturnDetail
    from rwa_filer.validate.review import ReviewFilter
    from rwa_filer.workflow.attribution import Attribution, Standing, TracedBreak

#: Hidden breaks the Investigate page lists, the largest first.
HIDDEN_SHOWN: Final = 40
#: Members named in the line under the table that break nothing.
CLEAN_NAMED: Final = 12
_DUST: Final = 1e-6


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class ShareRow:
    """One member's part of the picked cell."""

    label: str
    value: str
    share: str
    width: float
    rows: int
    flagged: bool


@dataclass(frozen=True)
class CellSplit:
    """The picked cell split by one breakdown column.

    Attributes:
        dimension: The column it is split by.
        dimensions: Every breakdown column, for the switch between them.
        rows: Each member's part, the largest first.
        detail_rows: How many rows of the file make the cell.
        unexplained: The cell's figure less the rows' total, where they
            differ — an override drafted on the summed figure; empty otherwise.
    """

    dimension: str
    dimensions: tuple[str, ...]
    rows: tuple[ShareRow, ...]
    detail_rows: int
    unexplained: str = ""


@dataclass(frozen=True)
class StandingRow:
    """One line of a "who breaks it" table."""

    label: str
    left: str
    right: str
    gap: str
    breaks: bool
    evaluated: bool


@dataclass(frozen=True)
class BreakSplit:
    """One broken evaluation of a rule, each member's figures beside the return's."""

    rule_id: str
    place: str
    left_label: str
    right_label: str
    verdict: str
    rows: tuple[StandingRow, ...]
    whole: StandingRow
    unexplained: str = ""


@dataclass(frozen=True)
class MatrixCell:
    """One member against one broken rule: how many of its breaks, and by how much."""

    count: int
    of: int
    amount: str
    tone: str


@dataclass(frozen=True)
class MatrixColumn:
    """A member the Investigate table has a column for."""

    index: int
    label: str
    selected: bool


@dataclass(frozen=True)
class MatrixRow:
    """One broken rule of the Investigate table."""

    rule_id: str
    severity: str
    label: str
    breaks: int
    cells: tuple[MatrixCell | None, ...]
    whole: str
    unexplained: str


@dataclass(frozen=True)
class HiddenRow:
    """A rule the total hides a break of."""

    rule_id: str
    severity: str
    label: str
    places: int
    members: str
    where: str


@dataclass(frozen=True)
class MemberBreak:
    """One rule a member breaks on its own figures, as its panel lists it."""

    rule_id: str
    severity: str
    places: int
    sentence: str
    cell: Cell | None = None


@dataclass(frozen=True)
class MemberPanel:
    """The picked member: what it breaks, and the note to send about it."""

    index: int
    label: str
    rows: int
    breaks: tuple[MemberBreak, ...]
    broken_count: int
    hidden_count: int
    note: str


@dataclass(frozen=True)
class InvestigatePage:
    """What the Investigate page draws for one breakdown column."""

    dimension: str
    dimensions: tuple[str, ...]
    members: int
    broken: int
    traced: int
    error_rules: int
    warning_rules: int
    breaking: tuple[str, ...]
    columns: tuple[MatrixColumn, ...]
    rows: tuple[MatrixRow, ...]
    clean: tuple[str, ...]
    hidden: tuple[HiddenRow, ...]
    hidden_count: int
    hiding: tuple[str, ...]
    panel: MemberPanel | None
    rules_run: int


@dataclass(frozen=True)
class CellBreakdown:
    """The cell panel's additions for a return opened with breakdown columns.

    Attributes:
        dimension: The column the cell is split by.
        dimensions: Every breakdown column, for the switch between them.
        split: The cell's figure by member; ``None`` when no row of the detail
            is in the cell.
        breaks: For each broken rule that reads the cell, its evaluations that
            read it, member by member.
    """

    dimension: str
    dimensions: tuple[str, ...]
    split: CellSplit | None
    breaks: dict[str, tuple[BreakSplit, ...]]


@dataclass(frozen=True)
class BreakdownSummary:
    """The overview's account of a detail: what was read, and how far it splits."""

    file: str
    rows_read: int
    rows_summed: int
    repeats_dropped: int
    cells: int
    summed_cells: int
    line_ref: str | None
    on_repeat: str
    dimensions: tuple[tuple[str, int, int], ...]


def breakdown_summary(detail: ReturnDetail) -> BreakdownSummary:
    """The overview's account of ``detail``: each column, its members, and its shared cells."""
    return BreakdownSummary(
        file=detail.file,
        rows_read=detail.rows_read,
        rows_summed=detail.rows.height,
        repeats_dropped=detail.repeats_dropped,
        cells=detail.cells,
        summed_cells=detail.summed_cells,
        line_ref=detail.spec.line_ref,
        on_repeat=detail.spec.on_repeat,
        dimensions=tuple(
            (dimension, len(detail.members(dimension)), detail.fed_by_several(dimension))
            for dimension in detail.dimensions
        ),
    )


def pick_dimension(detail: ReturnDetail, asked: str) -> str:
    """The breakdown column the address asks for, else the first."""
    return asked if asked in detail.dimensions else detail.dimensions[0]


def cell_split(
    working: WorkingReturn,
    cell: Cell,
    dimension: str,
    flagged: frozenset[Member] = frozenset(),
) -> CellSplit | None:
    """``cell`` split by ``dimension``, or ``None`` when the detail has no figure for it.

    ``flagged`` names the members to mark: those that break, on their own
    figures, a broken rule that reads the cell.
    """
    detail = working.opened.detail
    if detail is None:
        return None
    shares = detail.shares(cell, dimension)
    if not shares:
        return None
    total = math.fsum(share.value for share in shares)
    largest = max(abs(share.value) for share in shares) or 1.0
    held = _value(working.current, cell)
    difference = None if held is None else held - total
    return CellSplit(
        dimension=dimension,
        dimensions=detail.dimensions,
        rows=tuple(
            ShareRow(
                label=member_label(dimension, share.member),
                value=amount_text(share.value),
                share=f"{100 * share.value / total:.1f}%" if total else "",
                width=round(100 * abs(share.value) / largest, 1),
                rows=share.rows,
                flagged=share.member in flagged,
            )
            for share in shares
        ),
        detail_rows=sum(share.rows for share in shares),
        unexplained=amount_text(difference, signed=True)
        if difference is not None and abs(difference) > _DUST * max(1.0, abs(total))
        else "",
    )


def cell_breakdown(
    working: WorkingReturn,
    cell: Cell,
    dimension: str,
    rule_ids: tuple[str, ...],
    attribution: Attribution | None,
) -> CellBreakdown:
    """The picked cell split by ``dimension``, with each broken rule's evaluations beside it.

    ``attribution`` is by ``dimension`` and holds at least the rules in
    ``rule_ids``; ``None`` when no broken rule reads the cell.
    """
    detail = working.opened.detail
    assert detail is not None  # noqa: S101 - only drawn for a return with a detail
    flagged = (
        flagged_members(attribution, cell, rule_ids) if attribution is not None else frozenset()
    )
    return CellBreakdown(
        dimension=dimension,
        dimensions=detail.dimensions,
        split=cell_split(working, cell, dimension, flagged),
        breaks={
            rule_id: cell_breaks(attribution, cell, rule_id)
            for rule_id in rule_ids
            if attribution is not None
        },
    )


def reviewed_attribution(
    opened: OpenedReturn, attribution: Attribution, review: ReviewFilter
) -> Attribution:
    """Filter whole-return breaks after attribution so its shared cache stays complete."""
    report = opened.validation.report
    if not review.active or report is None:
        return attribution
    # Validation and attribution both record failures in engine evaluation order
    # within each rule. Two places can have the same display label.
    hidden = {
        (result.rule_id, index)
        for result in report.results
        if result.status == STATUS_FAIL
        for index, failure in enumerate(result.failures)
        if review.hides(result.severity, failure)
    }
    return replace(
        attribution,
        broken=tuple(
            item
            for rule_id, occurrences in groupby(attribution.broken, key=attrgetter("rule_id"))
            for index, item in enumerate(occurrences)
            if (rule_id, index) not in hidden
        ),
    )


def cell_breaks(attribution: Attribution, cell: Cell, rule_id: str) -> tuple[BreakSplit, ...]:
    """Each broken evaluation of ``rule_id`` that read ``cell``, member by member."""
    return tuple(_break_split(attribution, item) for item in attribution.reading(cell, rule_id))


def flagged_members(
    attribution: Attribution, cell: Cell, rule_ids: tuple[str, ...]
) -> frozenset[Member]:
    """The members that break, on their own figures, a broken rule that reads ``cell``."""
    return frozenset(
        standing.member
        for rule_id in rule_ids
        for item in attribution.reading(cell, rule_id)
        for standing in item.breaking
    )


def investigate_page(
    opened: OpenedReturn, attribution: Attribution, picked: int | None
) -> InvestigatePage:
    """The Investigate page for one column: the members against the broken rules.

    ``picked`` is the member's index in ``attribution.members``; ``None``
    picks the first member that breaks something.
    """
    detail = opened.detail
    assert detail is not None  # noqa: S101 - the page is drawn only for a return with one
    breaking = attribution.breaking_members
    columns_for = [
        index for index, member in enumerate(attribution.members) if member in set(breaking)
    ]
    if picked is None or not 0 <= picked < len(attribution.members):
        picked = columns_for[0] if columns_for else None
    rules = _rules(attribution.broken)
    error_rules = sum(1 for items in rules.values() if items[0].severity == SEVERITY_ERROR)
    return InvestigatePage(
        dimension=attribution.dimension,
        dimensions=detail.dimensions,
        members=len(attribution.members),
        broken=len(attribution.broken),
        traced=attribution.traced,
        error_rules=error_rules,
        warning_rules=len(rules) - error_rules,
        breaking=tuple(attribution.label(member) for member in breaking),
        columns=tuple(
            MatrixColumn(
                index=index,
                label=attribution.label(attribution.members[index]),
                selected=index == picked,
            )
            for index in columns_for
        ),
        rows=tuple(
            _matrix_row(opened, attribution, rule_id, items, columns_for)
            for rule_id, items in rules.items()
        ),
        clean=tuple(
            attribution.label(member)
            for member in attribution.members
            if member not in set(breaking)
        ),
        hidden=_hidden_rows(opened, attribution),
        hidden_count=len(attribution.hidden),
        hiding=tuple(attribution.label(member) for member in attribution.hiding_members),
        panel=_panel(opened, attribution, picked) if picked is not None else None,
        rules_run=attribution.rules_run,
    )


def breaks_csv(attribution: Attribution, picked: int | None = None) -> str:
    """Every evaluation the attribution traced, member by member, as CSV.

    One line per evaluation and member: the return's figures beside the
    member's. ``picked`` keeps one member's lines only.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            attribution.dimension,
            "rule_id",
            "severity",
            "in_the_return",
            "place",
            "cells",
            "member_breaks",
            "member_left",
            "member_right",
            "member_gap",
            "return_left",
            "return_right",
            "return_gap",
        ]
    )
    members = attribution.members
    chosen = members[picked] if picked is not None and 0 <= picked < len(members) else None
    for kind, items in (("breaks", attribution.broken), ("holds", attribution.hidden)):
        for item in items:
            for standing in item.standings:
                if picked is not None and standing.member != chosen:
                    continue
                if not standing.evaluated:
                    continue
                writer.writerow(
                    [
                        attribution.label(standing.member),
                        item.rule_id,
                        item.severity,
                        kind,
                        item.place_text,
                        " ".join(address(cell) for cell in item.cells),
                        "yes" if standing.breaks else "no",
                        _plain(standing.left),
                        _plain(standing.right),
                        _plain(standing.gap),
                        _plain(item.left),
                        _plain(item.right),
                        _plain(item.gap),
                    ]
                )
    return buffer.getvalue()


# =============================================================================
# Private helpers
# =============================================================================


def _value(opened: OpenedReturn, cell: Cell) -> float | None:
    table, sheet, key, row, column = cell
    found = opened.ret.facts.filter(
        (pl.col("table") == table)
        & pl.col("sheet").eq_missing(sheet)
        & pl.col("open_key").eq_missing(key)
        & (pl.col("row") == row)
        & (pl.col("column") == column)
    )
    return found["value"][0] if found.height else None


def _break_split(attribution: Attribution, item: TracedBreak) -> BreakSplit:
    dimension = attribution.dimension
    ordered = sorted(
        (standing for standing in item.standings if standing.evaluated),
        key=lambda standing: (not standing.breaks, -abs(standing.left or 0.0)),
    )
    return BreakSplit(
        rule_id=item.rule_id,
        place=item.place_text,
        left_label=_side_label(item.left_cells, item),
        right_label=_side_label(item.right_cells, item),
        verdict=_verdict(attribution, item),
        rows=tuple(
            _standing_row(attribution.label(standing.member), standing) for standing in ordered
        ),
        whole=StandingRow(
            label="The return",
            left=amount_text(item.left),
            right=amount_text(item.right),
            gap=amount_text(item.gap, signed=True),
            breaks=True,
            evaluated=True,
        ),
        unexplained=_unexplained(item, dimension),
    )


def _standing_row(label: str, standing: Standing) -> StandingRow:
    gap = standing.gap
    return StandingRow(
        label=label,
        left=amount_text(standing.left),
        right=amount_text(standing.right),
        gap=amount_text(gap, signed=True) if standing.breaks else "—",
        breaks=standing.breaks,
        evaluated=standing.evaluated,
    )


def _verdict(attribution: Attribution, item: TracedBreak) -> str:
    """Where the break is, in one sentence."""
    dimension = attribution.dimension
    breaking = item.breaking
    others = sum(1 for standing in item.standings if standing.evaluated) - len(breaking)
    rest = (
        f" The other {others} {dimension} member{'s' if others != 1 else ''} meet the rule on "
        "their own figures."
        if others
        else ""
    )
    if not breaking:
        return (
            f"No single {dimension} breaks it on its own figures: it breaks only when "
            "they are added together."
        )
    if len(breaking) == 1:
        standing = breaking[0]
        whole = item.gap
        if whole is not None and standing.gap is not None and _same(standing.gap, whole):
            return (
                f"All of the {amount_text(abs(whole))} is in {attribution.label(standing.member)}."
                + rest
            )
        return (
            f"{attribution.label(standing.member)} breaks it on its own figures, out by "
            f"{amount_text(standing.gap, signed=True)}." + rest
        )
    named = ", ".join(
        f"{attribution.label(standing.member)} ({amount_text(standing.gap, signed=True)})"
        for standing in breaking
    )
    return f"{len(breaking)} {dimension} members break it on their own figures: {named}." + rest


def _unexplained(item: TracedBreak, dimension: str) -> str:
    remainder = item.unexplained
    if not remainder:
        return ""
    return (
        f"{amount_text(remainder, signed=True)} of the return's gap is in no {dimension}'s rows: "
        "an override drafted on a figure the rule reads, or a rule that is not a plain sum."
    )


def _side_label(cells: tuple[Cell, ...], item: TracedBreak) -> str:
    """A side of the comparison named by its one cell's coordinates, else by its size."""
    if len(cells) != 1:
        return f"{len(cells)} cells" if cells else "—"
    _table, _sheet, _key, row, column = cells[0]
    place = dict(item.place)
    if place.get("r") == row:
        return f"c{column}"
    if place.get("c") == column:
        return f"r{row}"
    return f"r{row} c{column}"


def _rules(items: tuple[TracedBreak, ...]) -> dict[str, list[TracedBreak]]:
    grouped: dict[str, list[TracedBreak]] = {}
    for item in items:
        grouped.setdefault(item.rule_id, []).append(item)
    return grouped


def _matrix_row(
    opened: OpenedReturn,
    attribution: Attribution,
    rule_id: str,
    items: list[TracedBreak],
    columns: list[int],
) -> MatrixRow:
    cells: list[MatrixCell | None] = []
    tone = "error" if items[0].severity == SEVERITY_ERROR else "warning"
    for index in columns:
        member = attribution.members[index]
        gaps = [
            standing.gap
            for item in items
            if (standing := item.standing(member)) is not None and standing.breaks
        ]
        if not gaps:
            cells.append(None)
            continue
        cells.append(MatrixCell(count=len(gaps), of=len(items), amount=_amounts(gaps), tone=tone))
    whole = [item.gap for item in items]
    unexplained = [item.unexplained for item in items if item.unexplained]
    return MatrixRow(
        rule_id=rule_id,
        severity=items[0].severity,
        label=rule_label(opened.pack.info, rule_id),
        breaks=len(items),
        cells=tuple(cells),
        whole=_amounts(whole),
        unexplained=_amounts(unexplained) if unexplained else "",
    )


def _amounts(gaps: Sequence[float | None]) -> str:
    """One amount if every gap is the same, else the largest, as ``up to``."""
    numbers = [gap for gap in gaps if gap is not None]
    if not numbers:
        return ""
    largest = max(numbers, key=abs)
    if all(_same(gap, largest) for gap in numbers):
        return amount_text(largest, signed=True)
    return f"up to {amount_text(largest, signed=True)}"


def _hidden_rows(opened: OpenedReturn, attribution: Attribution) -> tuple[HiddenRow, ...]:
    rows: list[HiddenRow] = []
    for rule_id, items in _rules(attribution.hidden).items():
        members: dict[Member, list[float | None]] = {}
        for item in items:
            for standing in item.breaking:
                members.setdefault(standing.member, []).append(standing.gap)
        named = "; ".join(
            f"{attribution.label(member)} {_amounts(gaps)}".strip()
            for member, gaps in members.items()
        )
        places = sorted({item.place_text for item in items})
        where = ", ".join(places[:3]) + (f" and {len(places) - 3} more" if len(places) > 3 else "")
        rows.append(
            HiddenRow(
                rule_id=rule_id,
                severity=items[0].severity,
                label=rule_label(opened.pack.info, rule_id),
                places=len(items),
                members=named,
                where=where,
            )
        )
    return tuple(rows[:HIDDEN_SHOWN])


def _panel(opened: OpenedReturn, attribution: Attribution, index: int) -> MemberPanel:
    member = attribution.members[index]
    label = attribution.label(member)
    detail = opened.detail
    assert detail is not None  # noqa: S101 - the page is drawn only for a return with one
    rows = detail.rows.filter(pl.col(attribution.dimension).eq_missing(member)).height
    breaks = [
        MemberBreak(
            rule_id=rule_id,
            severity=items[0].severity,
            places=len(items),
            sentence=_member_sentence(items[0], member),
            cell=items[0].cells[0] if items[0].cells else None,
        )
        for rule_id, items in _rules(attribution.member_breaks(member)).items()
    ]
    hidden = attribution.member_hidden(member)
    return MemberPanel(
        index=index,
        label=label,
        rows=rows,
        breaks=tuple(breaks),
        broken_count=len(attribution.member_breaks(member)),
        hidden_count=len(hidden),
        note=_note(opened, attribution, member, breaks, hidden, rows),
    )


def _member_sentence(item: TracedBreak, member: Member) -> str:
    standing = item.standing(member)
    if standing is None:
        return ""
    where = f"At {item.place_text}" if item.place_text else "Over the whole template"
    tables = sorted({cell[0] for cell in item.cells})
    on = f" of {', '.join(tables)}" if tables else ""
    if standing.left is None or standing.right is None:
        return f"{where}{on}: the rule does not hold on these figures."
    return (
        f"{where}{on}: {amount_text(standing.left)} against {amount_text(standing.right)}, "
        f"out by {amount_text(standing.gap, signed=True)}."
    )


def _note(  # noqa: PLR0913 - the parts of one note, each from its own source
    opened: OpenedReturn,
    attribution: Attribution,
    member: Member,
    breaks: list[MemberBreak],
    hidden: tuple[TracedBreak, ...],
    rows: int,
) -> str:
    """A plain-text note about one member's breaks, to paste into a message."""
    header = opened.ret.header
    detail = opened.detail
    file = detail.file if detail is not None else opened.name
    label = attribution.label(member)
    lines = [
        f"{header.module} return of {header.entity_identifier} at "
        f"{long_date(header.reference_date)}.",
        f"On {label}'s figures alone ({rows:,} rows of {file}, {attribution.dimension} = "
        f"{label}), {len(breaks)} published rule{'s' if len(breaks) != 1 else ''} break:",
    ]
    for item in breaks:
        name = rule_label(opened.pack.info, item.rule_id)
        lines.append(
            f"- {item.rule_id} ({item.severity.capitalize()}), at {item.places} place"
            f"{'s' if item.places != 1 else ''}" + (f": {name}" if name else "")
        )
        lines.append(f"  {item.sentence}")
    if hidden:
        rule_ids = ", ".join(sorted({item.rule_id for item in hidden}))
        lines.append(
            f"These figures also break {rule_ids} at {len(hidden)} place"
            f"{'s' if len(hidden) != 1 else ''} where the return as a whole meets "
            "the rule: another part of the return offsets them."
        )
    return "\n".join(lines)


def _same(one: float, other: float) -> bool:
    return abs(one - other) < _DUST * max(1.0, abs(other))


def _plain(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".")
