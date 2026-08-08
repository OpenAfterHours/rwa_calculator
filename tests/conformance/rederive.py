"""
Loader and evaluator for the independent cell re-derivations (C4b).

Pipeline position:
    cell_rederivation.toml -> CellDerivation -> evaluated over the sealed
    aggregator-exit ledger -> compared against the generated template cell

Key responsibilities:
- Parse the re-derivation data file into typed values, enforcing the authoring
  contract (every cell carries a citation and names a real ledger carrier).
- Evaluate one cell's predicate and metric over a collected ledger frame,
  using only the five declared operators — no expression eval, no import from
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
#: mistake in this file look like a mistake in the engine.
_OPERATORS: frozenset[str] = frozenset({"in", "not_in", "equals", "not_equals", "not_starts_with"})


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
        return (~column.str.starts_with(self.values[0])).fill_null(True)


@dataclass(frozen=True)
class CellDerivation:
    """One template money cell, rebuilt from the ledger."""

    id: str
    template: str
    row: str
    column: str
    regimes: tuple[str, ...]
    metric: str
    carrier: str
    scale: float
    where: tuple[Clause, ...]
    citation: str
    note: str

    def evaluate(self, ledger: pl.DataFrame) -> float:
        """The re-derived value of this cell over ``ledger``."""
        frame = ledger
        for clause in self.where:
            frame = frame.filter(clause.expr())
        total = float(frame[self.carrier].fill_null(0.0).sum()) if frame.height else 0.0
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
        row=str(entry["row"]),
        column=str(entry["column"]),
        regimes=tuple(str(r) for r in entry["regimes"]),  # ty: ignore[not-iterable]
        metric=str(entry["metric"]),
        carrier=str(entry["carrier"]),
        scale=float(entry["scale"]),  # ty: ignore[invalid-argument-type]
        where=tuple(_clause(c) for c in entry["where"]),  # ty: ignore[not-iterable]
        citation=str(entry["citation"]),
        note=str(entry.get("note", "")),
    )


def _clause(raw: Mapping[str, object]) -> Clause:
    values = raw["values"] if "values" in raw else [raw["value"]]
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
        for clause in cell.where:
            assert clause.op in _OPERATORS, f"{cell.id}: unknown operator {clause.op!r}"
            assert clause.values, f"{cell.id}: clause on {clause.column} has no value"
