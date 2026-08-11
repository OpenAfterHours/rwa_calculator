"""
Loader and evaluator for the independent cell re-derivations (C4b).

Pipeline position:
    cell_rederivation.toml -> CellDerivation -> evaluated over the sealed
    aggregator-exit ledger -> compared against the generated template cell

Key responsibilities:
- Parse the re-derivation data file into typed values, enforcing the authoring
  contract (every cell carries a citation and names a real ledger carrier).
- Evaluate one cell's predicate and metric over a collected ledger frame,
  using only the declared operators — no expression eval, no import from
  ``reporting/cellspec.py``. If this module could reach the executor the second
  opinion would not be a second opinion.

References:
- docs/plans/independent-validation-system.md §C4b
- .claude/LESSONS.md E2 (a breakdown cell must sum the carrier its parent sums)
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_DERIVATION_PATH = Path(__file__).with_name("cell_rederivation.toml")

#: The complete operator set. Deliberately tiny — a richer DSL would let a
#: mistake in this file look like a mistake in the engine. The three numeric
#: forms exist because two template axes are numeric intervals rather than
#: string categories (C 07.00's risk-weight rows, C 08.02's PD bands) and
#: cannot be expressed with string equality at all.
_OPERATORS: frozenset[str] = frozenset(
    {
        "in",
        "not_in",
        "equals",
        "not_equals",
        "not_starts_with",
        "is_true",
        "is_false",
        "eq_num",
        "ge",
        "lt",
    }
)

#: Operators whose values are parsed as floats, not compared as strings.
_NUMERIC_OPERATORS: frozenset[str] = frozenset({"eq_num", "ge", "lt"})

#: Operators that take no value at all — the clause is the column's truth.
_NULLARY_OPERATORS: frozenset[str] = frozenset({"is_true", "is_false"})

#: Tolerance for ``eq_num``. Risk weights and PD grades are Float64 values
#: derived from decimal literals, so bit equality is not safe.
_NUMERIC_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Clause:
    """One AND-ed predicate clause over a sealed ledger column."""

    column: str
    op: str
    values: tuple[str, ...]

    def expr(self) -> pl.Expr:
        """The Polars predicate for this clause, with nulls resolving to False."""
        column = pl.col(self.column)
        if self.op == "in":
            return column.is_in(list(self.values)).fill_null(False)
        if self.op == "not_in":
            return (~column.is_in(list(self.values))).fill_null(False)
        if self.op == "equals":
            return (column == self.values[0]).fill_null(False)
        if self.op == "not_equals":
            return (column != self.values[0]).fill_null(False)
        if self.op == "is_true":
            # A null Boolean satisfies NEITHER limb: ``reporting_on_balance_sheet``
            # is null on the legs that are outside the on/off-balance-sheet credit
            # scope entirely (CCR, settlement), and those belong in neither row.
            return (column == True).fill_null(False)  # noqa: E712
        if self.op == "is_false":
            return (column == False).fill_null(False)  # noqa: E712
        if self.op == "eq_num":
            return ((column - float(self.values[0])).abs() < _NUMERIC_TOLERANCE).fill_null(False)
        if self.op == "ge":
            return (column >= float(self.values[0])).fill_null(False)
        if self.op == "lt":
            return (column < float(self.values[0])).fill_null(False)
        return (~column.str.starts_with(self.values[0])).fill_null(True)


@dataclass(frozen=True)
class CellDerivation:
    """One template money cell, rebuilt from the ledger."""

    id: str
    template: str
    member: str
    row: str
    column: str
    regimes: tuple[str, ...]
    metric: str
    carriers: tuple[str, ...]
    scale: float
    where: tuple[Clause, ...]
    citation: str
    note: str
    basis: str
    known_difference: str

    @property
    def address(self) -> str:
        """The template address a reader can look up in the submission."""
        sheet = f"[{self.member}]" if self.member else ""
        return f"{self.template}{sheet} r{self.row}/c{self.column}"

    def evaluate(self, ledger: pl.DataFrame) -> float:
        """The re-derived value of this cell over ``ledger``.

        Several template columns are additive over more than one sealed carrier
        — "original exposure pre-conversion factors" is an on-balance-sheet and
        an off-balance-sheet quantity added together (CRR Art. 111 / Art. 166),
        and no single ledger column holds it. A null carrier counts as zero,
        matching the single-carrier convention: for a SUM over rows, an absent
        component contributes nothing.
        """
        frame = ledger
        for clause in self.where:
            frame = frame.filter(clause.expr())
        if not frame.height:
            return 0.0
        total = sum(float(frame[carrier].fill_null(0.0).sum()) for carrier in self.carriers)
        return total * self.scale


@lru_cache(maxsize=1)
def load_derivations() -> tuple[CellDerivation, ...]:
    """Parse and validate ``cell_rederivation.toml``."""
    raw = tomllib.loads(_DERIVATION_PATH.read_text(encoding="utf-8"))
    cells = tuple(_cell(entry) for entry in raw.get("cell", ()))
    _validate(cells)
    return cells


@lru_cache(maxsize=1)
def derivation_meta() -> Mapping[str, object]:
    """The data file's ``[meta]`` block, including its stated limits."""
    return tomllib.loads(_DERIVATION_PATH.read_text(encoding="utf-8"))["meta"]


def _cell(entry: Mapping[str, object]) -> CellDerivation:
    return CellDerivation(
        id=str(entry["id"]),
        template=str(entry["template"]),
        member=str(entry.get("member", "")),
        row=str(entry["row"]),
        column=str(entry["column"]),
        regimes=tuple(str(r) for r in entry["regimes"]),  # ty: ignore[not-iterable]
        metric=str(entry["metric"]),
        carriers=_carriers(entry["carrier"]),
        scale=float(entry["scale"]),  # ty: ignore[invalid-argument-type]
        where=tuple(_clause(c) for c in entry["where"]),  # ty: ignore[not-iterable]
        citation=str(entry["citation"]),
        note=str(entry.get("note", "")),
        basis=str(entry.get("basis", "")),
        known_difference=str(entry.get("known_difference", "")),
    )


def _carriers(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(c) for c in raw)  # ty: ignore[not-iterable]


def _clause(raw: Mapping[str, object]) -> Clause:
    if "values" in raw:
        values = raw["values"]
    elif "value" in raw:
        values = [raw["value"]]
    else:
        values = []
    return Clause(
        column=str(raw["column"]),
        op=str(raw["op"]),
        values=tuple(str(v) for v in values),  # ty: ignore[not-iterable]
    )


def _validate(cells: Sequence[CellDerivation]) -> None:
    """Enforce the authoring contract before anything is asserted against it."""
    seen: set[str] = set()
    assert cells, "no cell re-derivations authored"
    for cell in cells:
        assert cell.id not in seen, f"duplicate cell id {cell.id}"
        seen.add(cell.id)
        assert cell.citation, f"{cell.id}: every cell must carry a citation"
        assert cell.metric == "sum", f"{cell.id}: unsupported metric {cell.metric!r}"
        assert cell.regimes, f"{cell.id}: a cell must name at least one regime"
        assert cell.carriers, f"{cell.id}: a cell must name at least one carrier"
        assert cell.basis, (
            f"{cell.id}: every cell must record in `basis` what its agreement "
            f"does NOT independently settle — a green run must not over-claim"
        )
        for clause in cell.where:
            assert clause.op in _OPERATORS, f"{cell.id}: unknown operator {clause.op!r}"
            if clause.op in _NULLARY_OPERATORS:
                assert not clause.values, (
                    f"{cell.id}: {clause.op} on {clause.column} takes no value"
                )
                continue
            assert clause.values, f"{cell.id}: clause on {clause.column} has no value"
            if clause.op in _NUMERIC_OPERATORS:
                float(clause.values[0])
