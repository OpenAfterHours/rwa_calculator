"""
Explaining differences — two returns' material differences as findings a reviewer can act on.

Pipeline position:
    compare.compare_returns  ->  each cell's CellDifference + both files' RuleTrace
        ->  explain_differences  ->  Discrepancy per finding

Key responsibilities:
- Turn a list of differing cells into a handful of findings, each one thing a
  person has to explain, and put every material difference in exactly one.
- Say which side the evidence points at, using the Bank's own rules as the
  referee: a rule that holds in one file and breaks in the other at the same
  place points at the file it breaks in.
- Never decide which return is right. Two returns that agree with every rule
  can still both be wrong; a finding says where to look, and why.

How differences are linked into one finding
- A Bank equality (``total = a + b``) checked at the same place in both files,
  and holding in both, ties together every differing cell it read: the files
  agree on how those figures relate, so they differ for one reason.
- Where such a total agrees and two of its components differ by equal and
  opposite amounts, the same figure is reported in a different row: a MOVE.
- Differing cells on one row of one sheet, cells that are one data point shown
  in two places, and the same difference on an open-axis sheet and its total,
  are the same figure and are linked too.
- An equality that breaks in one file only is not a link. Its gap is the part
  of the difference at its total that the components do not explain.

References:
- rwa_filer.boe.engine.trace_rules — the evaluations, and the cells each read
- Bank of England Banking Taxonomy v4.1.1 — the validation rules
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from rwa_filer.boe.engine import CellAddress, Evaluation
    from rwa_filer.taxonomy.pack import TaxonomyPack

# =============================================================================
# Constants
# =============================================================================

#: The same figure, or the same text, in both returns.
CATEGORY_SAME: Final = "same"
#: Two figures within the rounding the two files state for them.
CATEGORY_ROUNDING: Final = "rounding"
#: A zero in one return where the other reports nothing.
CATEGORY_ZERO_OR_BLANK: Final = "zero_or_blank"
#: A cell of a template only one of the two returns reports.
CATEGORY_SCOPE: Final = "scope"
#: A difference that needs explaining.
CATEGORY_MATERIAL: Final = "material"
#: Every category, in the order a summary lists them.
CATEGORIES: Final = (
    CATEGORY_SAME,
    CATEGORY_ROUNDING,
    CATEGORY_ZERO_OR_BLANK,
    CATEGORY_SCOPE,
    CATEGORY_MATERIAL,
)

SIDE_BASELINE: Final = "baseline"
SIDE_CANDIDATE: Final = "candidate"
#: Both files are consistent: the figures were calculated differently.
POINTS_AT_INPUTS: Final = "inputs"
#: Nothing in either file says which is right.
POINTS_AT_NEITHER: Final = "neither"

#: Differing cells that move together; every rule linking them holds in both.
KIND_CALCULATION: Final = "calculation"
#: A cell that does not equal what a Bank rule says it must, in one file only.
KIND_DOES_NOT_ADD_UP: Final = "does_not_add_up"
#: A column one return fills in and the other leaves empty.
KIND_ONE_SIDED: Final = "one_sided"
#: Zeros reported where the Bank expects the cell to be left empty.
KIND_UNEXPECTED_ZERO: Final = "unexpected_zero"
#: Differing cells nothing links to another difference.
KIND_UNLINKED: Final = "unlinked"
#: A rule that breaks in one file only, that no other finding cites.
KIND_RULE_ONLY: Final = "rule_only"

STANDING_HOLDS: Final = "holds"
STANDING_BREAKS: Final = "breaks"
STANDING_NOT_RUN: Final = "not evaluated"

#: A cell's full address: table, sheet, open-axis key, row, column.
Cell = tuple[str, str | None, str | None, str, str]

#: Fewest one-sided cells in one column for the column to be a finding of its own.
_ONE_SIDED_COLUMN_MIN: Final = 2
#: A row label that is a single rate, e.g. "75%".
_RATE_LABEL: Final = re.compile(r"^(\d+(?:\.\d+)?)%$")
_EQUALS: Final = "="


# =============================================================================
# Public types
# =============================================================================


@dataclass(frozen=True)
class CellDifference:
    """One cell as the two returns report it.

    Attributes:
        cell: The cell's address.
        category: One of ``CATEGORIES``.
        baseline / candidate: The figure (or text) each return reports;
            ``None`` where it reports nothing.
        delta: ``candidate - baseline`` for a figure (a missing figure taken as
            zero); ``None`` for text.
        allowance: The rounding the two files state for the cell, together.
        held_by: For a cell one return reports, that return's side.
    """

    cell: Cell
    category: str
    baseline: float | str | None
    candidate: float | str | None
    delta: float | None
    allowance: float = 0.0
    held_by: str | None = None


@dataclass(frozen=True)
class RuleStanding:
    """One rule as each return stands against it: holds, breaks or not evaluated."""

    rule_id: str
    baseline: str
    candidate: str


@dataclass(frozen=True)
class RowMove:
    """A figure the two returns report in different rows of one sheet.

    Attributes:
        table / sheet / open_key: The sheet the move is on.
        baseline_row / candidate_row: Where each return reports it.
        columns: The columns it moved in.
        amount: How much moved (the largest across ``columns``).
    """

    table: str
    sheet: str | None
    open_key: str | None
    baseline_row: str
    candidate_row: str
    columns: tuple[str, ...]
    amount: float


@dataclass(frozen=True)
class RateCheck:
    """Whether a move between two rate rows accounts for the change in another column.

    Where the moved rows are labelled with a single rate each (a risk weight,
    "50%" and "75%"), the move implies a change of ``amount`` times the
    difference in rates in the column that applies the rate.
    """

    column: str
    implied: float
    observed: float
    consistent: bool


@dataclass(frozen=True)
class TotalBreakdown:
    """The difference at a total, split into what its components explain and what they do not."""

    cell: Cell
    delta: float
    explained: float
    unexplained: float


@dataclass(frozen=True)
class Discrepancy:
    """One finding: differences that have one explanation, and what the evidence points at.

    Attributes:
        number: The finding's number, from 1, in the order they are listed.
        kind: One of the ``KIND_*`` constants.
        points_at: ``baseline`` / ``candidate`` — the file a rule breaks in —
            ``inputs`` when both files are consistent, or ``neither``.
        title: The finding in one sentence.
        detail: What the evidence is, in a sentence or two.
        cells: The differing cells it explains.
        rules: The rules that stand differently in the two files, with both standings.
        moves: Figures reported in a different row.
        breakdown: For a total that does not add up, what its components explain.
        gap: How far the cell is from what the rule says it must equal, in the
            file the rule breaks in.
        rate_check: Whether a move between rate rows accounts for the other column.
    """

    number: int
    kind: str
    points_at: str
    title: str
    detail: str
    cells: tuple[Cell, ...] = ()
    rules: tuple[RuleStanding, ...] = ()
    moves: tuple[RowMove, ...] = ()
    breakdown: tuple[TotalBreakdown, ...] = ()
    gap: float | None = None
    rate_check: RateCheck | None = None


@dataclass(frozen=True)
class Names:
    """What the two returns are called in the words of a finding."""

    baseline: str = "the baseline"
    candidate: str = "the candidate"

    def of(self, side: str) -> str:
        return self.baseline if side == SIDE_BASELINE else self.candidate


# =============================================================================
# Public entry point
# =============================================================================


def explain_differences(
    differences: Mapping[Cell, CellDifference],
    baseline_trace: Sequence[Evaluation],
    candidate_trace: Sequence[Evaluation],
    pack: TaxonomyPack,
    *,
    names: Names | None = None,
) -> tuple[Discrepancy, ...]:
    """Group the material differences into findings, numbered in the order listed.

    Every material cell is in exactly one finding, and every rule that breaks in
    one file only is cited by at least one.
    """
    context = _Context(differences, pack, names or Names())
    links = _Links(context, _pair(baseline_trace, candidate_trace))
    drafts = [
        *links.calculation_findings(),
        *links.total_findings(),
        *links.one_sided_findings(),
        *links.zero_findings(),
        *links.unlinked_findings(),
        *links.rule_only_findings(),
    ]
    return tuple(replace(draft, number=index) for index, draft in enumerate(drafts, start=1))


# =============================================================================
# Private helpers — the two traces, paired place by place
# =============================================================================


@dataclass
class _Check:
    """One rule at one place, as each file evaluated it."""

    rule_id: str
    by_side: dict[str, Evaluation] = field(default_factory=dict)

    def standing(self, side: str) -> str:
        found = self.by_side.get(side)
        if found is None:
            return STANDING_NOT_RUN
        return STANDING_HOLDS if found.holds else STANDING_BREAKS

    @property
    def holds_everywhere(self) -> bool:
        return all(item.holds for item in self.by_side.values())

    @property
    def broken_on(self) -> str | None:
        """The one side this check breaks on, if it breaks on exactly one."""
        broken = [side for side, item in self.by_side.items() if not item.holds]
        return broken[0] if len(broken) == 1 else None

    @property
    def is_equality(self) -> bool:
        return all(item.relation == _EQUALS for item in self.by_side.values())

    def cells(self, part: str = "all") -> set[Cell]:
        found: set[Cell] = set()
        for item in self.by_side.values():
            addresses = {"left": item.left, "right": item.right}.get(part, item.left + item.right)
            found |= {_cell(address) for address in addresses}
        return found

    def reported_right(self, side: str) -> bool:
        item = self.by_side.get(side)
        return item is not None and any(address.reported for address in item.right)


def _pair(baseline: Iterable[Evaluation], candidate: Iterable[Evaluation]) -> list[_Check]:
    checks: dict[tuple[str, tuple[tuple[str, str], ...]], _Check] = {}
    for side, evaluations in ((SIDE_BASELINE, baseline), (SIDE_CANDIDATE, candidate)):
        for item in evaluations:
            key = (item.rule_id, item.place)
            checks.setdefault(key, _Check(item.rule_id)).by_side[side] = item
    return list(checks.values())


def _one_sided(checks: list[_Check]) -> list[_Check]:
    """The checks that break in one return and not the other.

    Where both returns evaluate the place, one breaking and the other holding
    is one-sided. Where only one return has the place at all — a row only it
    reports — the break is one-sided only if the other return does not break
    the same rule anywhere: a figure moved from one row to another takes its
    breaks with it, and that is the same rule broken in both.
    """
    broken = {
        side: {check.rule_id for check in checks if check.standing(side) == STANDING_BREAKS}
        for side in (SIDE_BASELINE, SIDE_CANDIDATE)
    }
    found = []
    for check in checks:
        side = check.broken_on
        if side is None:
            continue
        other = SIDE_CANDIDATE if side == SIDE_BASELINE else SIDE_BASELINE
        if other in check.by_side or check.rule_id not in broken[other]:
            found.append(check)
    return found


def _one_sided_points(holder: str, broken_on: set[str | None]) -> str | None:
    """Which return a column only ``holder`` reports points at, from the rules it breaks.

    The return that lacks the column, when a rule breaks there; else the one
    that has it, when its figures break a rule; else neither.
    """
    lacking = SIDE_CANDIDATE if holder == SIDE_BASELINE else SIDE_BASELINE
    if lacking in broken_on:
        return lacking
    return holder if holder in broken_on else None


def _rule_only_reason(ids: set[str], differing: set[Cell]) -> str:
    """Why a one-sided break no other finding cites is listed on its own."""
    if not differing:
        them = "them" if len(ids) > 1 else "it"
        return (
            f"No differing cell is behind {them}: the same figures are judged differently "
            "because of what else each return reports."
        )
    reads = "They read" if len(ids) > 1 else "It reads"
    cells = f"{len(differing)} cells that differ" if len(differing) > 1 else "1 cell that differs"
    return f"{reads} {cells}, in the findings above."


def _cell(address: CellAddress) -> Cell:
    return (address.table, address.sheet, address.open_key, address.row, address.column)


# =============================================================================
# Private helpers — words
# =============================================================================


class _Context:
    """The differences, the taxonomy that labels them, and the names of the two sides."""

    def __init__(
        self, differences: Mapping[Cell, CellDifference], pack: TaxonomyPack, names: Names
    ) -> None:
        self.differences = differences
        self.pack = pack
        self.names = names
        self.material = {
            cell for cell, item in differences.items() if item.category == CATEGORY_MATERIAL
        }

    def delta(self, cell: Cell) -> float:
        item = self.differences.get(cell)
        return 0.0 if item is None or item.delta is None else item.delta

    def allowance(self, cell: Cell) -> float:
        item = self.differences.get(cell)
        return 0.0 if item is None else item.allowance

    def row_label(self, table: str, row: str) -> str:
        found = self.pack.table(table)
        return dict(found.rows).get(row, row) if found is not None else row

    def column_label(self, table: str, column: str) -> str:
        found = self.pack.table(table)
        label = dict(found.columns).get(column, column) if found is not None else column
        return label.split(" / ")[-1]

    def sheet_label(self, table: str, sheet: str | None, open_key: str | None) -> str | None:
        if open_key:
            return open_key
        found = self.pack.table(table)
        axis = found.fixed_axis if found is not None else None
        if sheet is None or axis is None:
            return None
        return next((item.label for item in axis.sheets if item.code == sheet), sheet)

    def where(self, cell: Cell) -> str:
        table, sheet, open_key, row, column = cell
        on = self.sheet_label(table, sheet, open_key)
        sheet_part = f" {on}," if on else ""
        return (
            f"{table}{sheet_part} row {row} ({_sentence(self.row_label(table, row))}), "
            f"column {column} ({self.column_label(table, column)})"
        )


def _sentence(text: str) -> str:
    """A label as it reads inside a sentence: ALL-CAPS headings in sentence case."""
    return text[:1] + text[1:].lower() if text.isupper() else text


def _amount(value: float) -> str:
    if abs(value) >= 1 or value == 0:
        return f"{value:,.0f}"
    return f"{value:.6g}"


def _signed(value: float) -> str:
    return f"+{_amount(value)}" if value > 0 else _amount(value)


def _breaks(rule_ids: Iterable[str]) -> str:
    """``"boe_b1 breaks"`` / ``"boe_b1 and boe_b2 break"``."""
    ids = set(rule_ids)
    return f"{_listed(ids)} {'break' if len(ids) > 1 else 'breaks'}"


def _listed(rule_ids: Iterable[str]) -> str:
    ids = sorted(set(rule_ids))
    if len(ids) > 1:
        return ", ".join(ids[:-1]) + f" and {ids[-1]}"
    return ids[0] if ids else ""


# =============================================================================
# Private helpers — linking differences into findings
# =============================================================================


class _Links:
    """The material differences, linked; and the findings they make."""

    def __init__(self, context: _Context, checks: list[_Check]) -> None:
        self.context = context
        self.checks = checks
        self.one_sided = _one_sided(checks)
        self.cited: set[int] = set()
        self.placed: set[Cell] = set()
        self.columns = self._one_sided_columns()
        self.linkable = context.material - {
            cell for cells in self.columns.values() for cell in cells
        }
        self._parent = {cell: cell for cell in self.linkable}
        self.explained: dict[Cell, set[Cell]] = defaultdict(set)
        self.moves: list[tuple[str, Cell, list[Cell]]] = []
        self._link_by_rules()
        self._link_same_row()
        self._link_same_datapoint()
        self._link_open_siblings()

    # -- union-find ---------------------------------------------------------------

    def _find(self, cell: Cell) -> Cell:
        while self._parent[cell] != cell:
            self._parent[cell] = self._parent[self._parent[cell]]
            cell = self._parent[cell]
        return cell

    def _join(self, cells: Iterable[Cell]) -> None:
        items = sorted(cells, key=_order)
        for first, second in zip(items, items[1:], strict=False):
            self._parent[self._find(first)] = self._find(second)

    def groups(self) -> list[list[Cell]]:
        found: dict[Cell, list[Cell]] = defaultdict(list)
        for cell in self.linkable:
            found[self._find(cell)].append(cell)
        return sorted(
            (sorted(items, key=_order) for items in found.values()),
            key=lambda items: (-len(items), _order(items[0])),
        )

    # -- links ----------------------------------------------------------------------

    def _one_sided_columns(self) -> dict[tuple[str, str, str], list[Cell]]:
        """Columns whose every material cell only one return reports, the same one."""
        by_column: dict[tuple[str, str], list[Cell]] = defaultdict(list)
        for cell in self.context.material:
            by_column[(cell[0], cell[4])].append(cell)
        found = {}
        for (table, column), cells in by_column.items():
            holders = {self.context.differences[cell].held_by for cell in cells}
            if len(cells) >= _ONE_SIDED_COLUMN_MIN and len(holders) == 1 and None not in holders:
                found[(table, column, holders.pop() or "")] = sorted(cells, key=_order)
        return found

    def _link_by_rules(self) -> None:
        for check in self.checks:
            if not (check.is_equality and check.holds_everywhere):
                continue
            read = check.cells() & self.linkable
            self._join(read)
            left = check.cells("left")
            if len(left) != 1:
                continue
            total = next(iter(left))
            parts = [cell for cell in check.cells("right") & self.context.material if cell != total]
            if total in self.context.material and parts:
                self.explained[total].update(parts)
            elif total not in self.context.material and len(parts) > 1:
                net = sum(self.context.delta(cell) for cell in parts)
                tolerance = sum(self.context.allowance(cell) for cell in parts)
                scale = sum(abs(self.context.delta(cell)) for cell in parts)
                if abs(net) <= tolerance + 1e-9 * scale:
                    self.moves.append((check.rule_id, total, parts))

    def _link_same_row(self) -> None:
        rows: dict[tuple[str, str | None, str | None, str], list[Cell]] = defaultdict(list)
        for cell in self.linkable:
            rows[cell[:4]].append(cell)
        for cells in rows.values():
            self._join(cells)

    def _link_same_datapoint(self) -> None:
        fixed = [
            cell
            for cell in self.linkable
            if cell[2] is None
            and (table := self.context.pack.table(cell[0])) is not None
            and not table.open_rows
        ]
        if not fixed:
            return
        frame = pl.DataFrame(
            [(cell[0], cell[1], cell[3], cell[4]) for cell in fixed],
            schema=["table", "sheet", "row", "column"],
            orient="row",
        )
        points = frame.join(
            self.context.pack.cells.select("table", "sheet", "row", "column", "datapoint"),
            on=["table", "sheet", "row", "column"],
            how="inner",
            nulls_equal=True,
        )
        by_point: dict[int, list[Cell]] = defaultdict(list)
        for table, sheet, row, column, point in points.iter_rows():
            by_point[point].append((table, sheet, None, row, column))
        for cells in by_point.values():
            self._join(cells)

    def _link_open_siblings(self) -> None:
        siblings: dict[tuple[str, str | None, str, str], list[Cell]] = defaultdict(list)
        for cell in self.linkable:
            if cell[2] is not None:
                siblings[(cell[0], cell[1], cell[3], cell[4])].append(cell)
        for cells in siblings.values():
            for first in cells:
                for second in cells:
                    gap = abs(self.context.delta(first) - self.context.delta(second))
                    if _order(first) < _order(second) and gap <= (
                        self.context.allowance(first) + self.context.allowance(second)
                    ):
                        self._join((first, second))

    # -- findings ---------------------------------------------------------------------

    def calculation_findings(self) -> list[Discrepancy]:
        drafts = []
        for cells in self.groups():
            if len(cells) < 2:  # noqa: PLR2004 - a group is two or more
                continue
            members = set(cells)
            cells = sorted(cells, key=lambda cell: (bool(self.explained.get(cell)), _order(cell)))
            moves = self._moves_in(members)
            rate = self._rate_check(moves[0]) if moves else None
            title, detail = self._calculation_words(cells, moves, rate)
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_CALCULATION,
                    points_at=POINTS_AT_INPUTS,
                    title=title,
                    detail=detail,
                    cells=tuple(cells),
                    moves=tuple(moves),
                    rate_check=rate,
                )
            )
            self.placed |= members
        return drafts

    def total_findings(self) -> list[Discrepancy]:
        groups: dict[tuple[str, float], list[_Check]] = defaultdict(list)
        for index, check in enumerate(self.one_sided):
            side = check.broken_on or ""
            item = check.by_side[side]
            if not (check.is_equality and check.reported_right(side) and len(item.left) == 1):
                continue
            if item.left_value is None or item.right_value is None:
                continue
            groups[(side, round(item.left_value - item.right_value, 2))].append(check)
            self.cited.add(index)
        drafts = []
        for (side, gap), checks in groups.items():
            totals = sorted({_cell(check.by_side[side].left[0]) for check in checks}, key=_order)
            breakdown = tuple(self._breakdown(total, checks) for total in totals)
            title, detail = self._total_words(side, gap, totals[0], breakdown, checks)
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_DOES_NOT_ADD_UP,
                    points_at=side,
                    title=title,
                    detail=detail,
                    cells=tuple(cell for cell in totals if cell in self.context.material),
                    rules=self._standings(checks),
                    breakdown=tuple(item for item in breakdown if item is not None),
                    gap=gap,
                )
            )
            self.placed |= {cell for cell in totals if cell in self.context.material}
        return drafts

    def one_sided_findings(self) -> list[Discrepancy]:
        drafts = []
        for (table, column, holder), cells in sorted(self.columns.items()):
            members = set(cells)
            checks = self._citing(members)
            points = _one_sided_points(holder, {check.broken_on for check in checks})
            title = (
                f"Only {self.context.names.of(holder)} reports {table} column {column} "
                f"({self.context.column_label(table, column)}): {len(cells)} cells"
            )
            detail = self._one_sided_detail(holder, points, checks)
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_ONE_SIDED,
                    points_at=points or POINTS_AT_NEITHER,
                    title=title,
                    detail=detail,
                    cells=tuple(cells),
                    rules=self._standings(checks),
                )
            )
            self.placed |= members
        return drafts

    def zero_findings(self) -> list[Discrepancy]:
        by_side: dict[str, list[tuple[int, _Check, set[Cell]]]] = defaultdict(list)
        for index, check in enumerate(self.one_sided):
            if index in self.cited:
                continue
            side = check.broken_on or ""
            zeros = {
                cell
                for cell in check.cells()
                if (item := self.context.differences.get(cell)) is not None
                and item.category == CATEGORY_ZERO_OR_BLANK
                and item.held_by == side
            }
            if zeros:
                by_side[side].append((index, check, zeros))
        drafts = []
        for side, items in sorted(by_side.items()):
            zeros = set().union(*(cells for _, _, cells in items))
            checks = [check for _, check, _ in items]
            self.cited |= {index for index, _, _ in items}
            name = self.context.names.of(side)
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_UNEXPECTED_ZERO,
                    points_at=side,
                    title=(
                        f"Zero reported by {name} in {len(zeros):,} cells the Bank expects "
                        "to be left empty"
                    ),
                    detail=(
                        f"A zero is a reported figure. {_breaks(c.rule_id for c in checks)} in "
                        f"{name} only, because these cells are not reported on that sheet."
                    ),
                    cells=tuple(sorted(zeros, key=_order)),
                    rules=self._standings(checks),
                )
            )
        return drafts

    def unlinked_findings(self) -> list[Discrepancy]:
        by_table: dict[str, list[Cell]] = defaultdict(list)
        for cell in self.context.material - self.placed:
            by_table[cell[0]].append(cell)
        drafts = []
        for table, cells in sorted(by_table.items()):
            ordered = sorted(cells, key=_order)
            checks = self._citing(set(ordered))
            sides = {check.broken_on for check in checks}
            points = sides.pop() if len(sides) == 1 else None
            largest = max(ordered, key=lambda cell: abs(self.context.delta(cell)))
            title = (
                f"{len(ordered)} cell{'s' if len(ordered) > 1 else ''} of {table} "
                f"differ{'' if len(ordered) > 1 else 's'} with nothing linking "
                f"{'them' if len(ordered) > 1 else 'it'} to another difference"
            )
            detail = f"The largest is {_signed(self.context.delta(largest))} at {self.context.where(largest)}."
            if points:
                detail += (
                    f" {_breaks(check.rule_id for check in checks)} in "
                    f"{self.context.names.of(points)} only."
                )
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_UNLINKED,
                    points_at=points or POINTS_AT_NEITHER,
                    title=title,
                    detail=detail,
                    cells=tuple(ordered),
                    rules=self._standings(checks),
                )
            )
            self.placed |= set(ordered)
        return drafts

    def rule_only_findings(self) -> list[Discrepancy]:
        # A rule a finding already cites, on the same side, is that finding's: its
        # other places add nothing a reviewer would act on separately.
        cited = {
            (self.one_sided[index].rule_id, self.one_sided[index].broken_on) for index in self.cited
        }
        by_side: dict[str, list[_Check]] = defaultdict(list)
        for index, check in enumerate(self.one_sided):
            if index not in self.cited and (check.rule_id, check.broken_on) not in cited:
                by_side[check.broken_on or ""].append(check)
        drafts = []
        for side, checks in sorted(by_side.items()):
            ids = {check.rule_id for check in checks}
            name = self.context.names.of(side)
            differing = set().union(*(check.cells() for check in checks)) & self.context.material
            detail = f"{_breaks(ids)} in {name} and not in the other return. " + _rule_only_reason(
                ids, differing
            )
            drafts.append(
                Discrepancy(
                    number=0,
                    kind=KIND_RULE_ONLY,
                    points_at=side,
                    title=(
                        f"{len(ids)} {'rules break' if len(ids) > 1 else 'rule breaks'} "
                        f"in {name} only"
                    ),
                    detail=detail,
                    rules=self._standings(checks),
                )
            )
        return drafts

    # -- finding parts -----------------------------------------------------------------

    def _one_sided_detail(self, holder: str, points: str | None, checks: list[_Check]) -> str:
        names = self.context.names
        rules = _listed(check.rule_id for check in checks)
        if points is None:
            return (
                "No Bank rule depends on these cells, so this is a choice between the two "
                "returns, not an error in either."
            )
        if points == holder:
            return f"The figures {names.of(holder)} reports there break {rules}."
        them = "it" if len({check.rule_id for check in checks}) == 1 else "them"
        return (
            f"Without these cells, {names.of(points)} breaks {rules}; {names.of(holder)}, "
            f"which reports them, satisfies {them}."
        )

    def _citing(self, cells: set[Cell]) -> list[_Check]:
        found = []
        for index, check in enumerate(self.one_sided):
            if check.cells() & cells:
                found.append(check)
                self.cited.add(index)
        return found

    @staticmethod
    def _standings(checks: Iterable[_Check]) -> tuple[RuleStanding, ...]:
        found: dict[str, RuleStanding] = {}
        for check in checks:
            standing = RuleStanding(
                check.rule_id, check.standing(SIDE_BASELINE), check.standing(SIDE_CANDIDATE)
            )
            previous = found.get(check.rule_id)
            if previous is None or STANDING_BREAKS in (standing.baseline, standing.candidate):
                found[check.rule_id] = standing
        return tuple(found[key] for key in sorted(found))

    def _moves_in(self, members: set[Cell]) -> list[RowMove]:
        combined: dict[tuple[str, str | None, str | None, str, str], dict[str, float]] = (
            defaultdict(dict)
        )
        for _rule, _total, parts in self.moves:
            if not set(parts) <= members:
                continue
            up = max(parts, key=self.context.delta)
            down = min(parts, key=self.context.delta)
            combined[(up[0], up[1], up[2], down[3], up[3])][up[4]] = self.context.delta(up)
        moves = [
            RowMove(
                table=table,
                sheet=sheet,
                open_key=open_key,
                baseline_row=baseline_row,
                candidate_row=candidate_row,
                columns=tuple(sorted(columns)),
                amount=max(columns.values()),
            )
            for (table, sheet, open_key, baseline_row, candidate_row), columns in combined.items()
        ]
        return sorted(moves, key=lambda move: (-move.amount, move.table, move.sheet or ""))

    def _rate_check(self, move: RowMove) -> RateCheck | None:
        """Where both rows are a single rate, whether the move explains the column applying it."""
        rates = [
            _RATE_LABEL.match(self.context.row_label(move.table, row))
            for row in (move.baseline_row, move.candidate_row)
        ]
        if not all(rates):
            return None
        baseline_rate, candidate_rate = (float(match.group(1)) for match in rates if match)
        net: dict[str, float] = defaultdict(float)
        for cell in self.linkable:
            on_sheet = (cell[0], cell[1], cell[2]) == (move.table, move.sheet, move.open_key)
            if on_sheet and cell[3] in (move.baseline_row, move.candidate_row):
                net[cell[4]] += self.context.delta(cell)
        applied = [
            column
            for column, total in net.items()
            if column not in move.columns and abs(total) > 1e-9 * move.amount
        ]
        if len(applied) != 1:
            return None
        column = applied[0]
        implied = move.amount * (candidate_rate - baseline_rate) / 100
        observed = net[column]
        tolerance = sum(
            self.context.allowance(cell)
            for cell in self.linkable
            if cell[4] == column and cell[3] in (move.baseline_row, move.candidate_row)
        )
        return RateCheck(
            column=column,
            implied=implied,
            observed=observed,
            consistent=abs(implied - observed) <= max(tolerance, 1e-6 * abs(implied)),
        )

    def _breakdown(self, total: Cell, checks: list[_Check]) -> TotalBreakdown | None:
        if total not in self.context.material:
            return None
        gaps = {SIDE_BASELINE: 0.0, SIDE_CANDIDATE: 0.0}
        for check in checks:
            if {_cell(address) for item in check.by_side.values() for address in item.left} != {
                total
            }:
                continue
            for side, item in check.by_side.items():
                if item.left_value is not None and item.right_value is not None:
                    gaps[side] = item.left_value - item.right_value
            break
        unexplained = gaps[SIDE_CANDIDATE] - gaps[SIDE_BASELINE]
        delta = self.context.delta(total)
        return TotalBreakdown(
            cell=total, delta=delta, explained=delta - unexplained, unexplained=unexplained
        )

    # -- words --------------------------------------------------------------------------

    def _calculation_words(
        self, cells: list[Cell], moves: list[RowMove], rate: RateCheck | None
    ) -> tuple[str, str]:
        names = self.context.names
        tables = sorted({cell[0] for cell in cells})
        detail = (
            f"{len(cells)} cells in {', '.join(tables)} differ together. Every Bank rule that "
            "links them holds in both returns, so neither file is put together wrongly: the "
            "figures were calculated differently, so look at the inputs and treatment behind them."
        )
        if not moves:
            largest = max(cells, key=lambda cell: abs(self.context.delta(cell)))
            title = (
                f"{len(cells)} differences that move together, the largest "
                f"{_signed(self.context.delta(largest))} at {self.context.where(largest)}"
            )
            return title, detail
        move = next(
            (
                item
                for item in moves
                if not (
                    self.context.sheet_label(item.table, item.sheet, item.open_key) or ""
                ).startswith("Total")
            ),
            moves[0],
        )
        on = self.context.sheet_label(move.table, move.sheet, move.open_key)
        title = (
            f"{_amount(move.amount)} is reported in {move.table}{f' {on}' if on else ''} row "
            f"{move.candidate_row} ({_sentence(self.context.row_label(move.table, move.candidate_row))}) "
            f"by {names.candidate} and row {move.baseline_row} "
            f"({_sentence(self.context.row_label(move.table, move.baseline_row))}) by {names.baseline}"
        )
        if rate is not None:
            label = self.context.column_label(move.table, rate.column)
            verdict = "which accounts for" if rate.consistent else "which does NOT account for"
            detail += (
                f" The move implies {_signed(rate.implied)} in column {rate.column} ({label}), "
                f"{verdict} the {_signed(rate.observed)} difference there."
            )
        return title, detail

    def _total_words(
        self,
        side: str,
        gap: float,
        total: Cell,
        breakdown: tuple[TotalBreakdown | None, ...],
        checks: list[_Check],
    ) -> tuple[str, str]:
        name = self.context.names.of(side)
        table, _sheet, _key, row, _column = total
        title = (
            f"In {name}, {table} row {row} ({_sentence(self.context.row_label(table, row))}) is "
            f"{_amount(abs(gap))} {'more' if gap > 0 else 'less'} than the figures a Bank rule "
            "says it must equal"
        )
        detail = f"{_breaks(check.rule_id for check in checks)} in {name} only."
        shown = next((item for item in breakdown if item is not None), None)
        if shown is not None:
            detail += (
                f" Of the {_signed(shown.delta)} difference at this cell, "
                f"{_signed(shown.explained)} is explained by those figures and "
                f"{_signed(shown.unexplained)} is in this cell alone, typical of an adjustment "
                "booked to a total rather than to a component."
            )
        return title, detail


def _order(cell: Cell) -> tuple[str, ...]:
    return tuple(part or "" for part in cell)
