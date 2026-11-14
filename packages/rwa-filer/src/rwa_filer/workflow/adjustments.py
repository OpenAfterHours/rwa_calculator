"""
Adjustments — cell-level overrides to a return, each with its reason, before and after.

Pipeline position:
    adjustments file (.csv / .parquet)  ->  read_adjustments
    CanonicalReturn + adjustments       ->  apply_adjustments
        ->  (adjusted CanonicalReturn, AppliedAdjustment per override)

Key responsibilities:
- Let a preparer set, change or remove individual cells without touching the
  source system's output, and without the change being invisible afterwards.
- Refuse an adjustment that does not say why, that targets a cell twice, or
  that removes a cell that is not there. A batch is applied whole or not at
  all: a half-applied batch is a return nobody can describe.
- Record, for every override, exactly what the cell held before and holds
  after — the record the manifest and the ledger carry.

An adjustment changes the RETURN, not the rules it is held to: the adjusted
return is validated like any other, and an adjustment that breaks a published
rule is reported as that rule breaking.

References:
- rwa_filer.model — the canonical fact schema an adjustment addresses
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.model import COORDINATE_COLUMNS, FACT_SCHEMA, CanonicalReturn

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

ACTION_SET: Final = "set"
ACTION_CHANGE: Final = "change"
ACTION_REMOVE: Final = "remove"
ACTION_NONE: Final = "no_change"

#: Columns of an adjustments file beyond the fact schema's own.
COLUMN_REASON: Final = "reason"
COLUMN_REMOVE: Final = "remove"

_TRUE: Final = frozenset({"true", "yes", "y", "1"})


class AdjustmentError(ValueError):
    """A batch of adjustments that cannot be applied. Carries every problem found."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__(
            f"{len(problems)} problem(s) with the adjustments; none was applied: "
            + "; ".join(problems[:5])
            + (" ..." if len(problems) > 5 else "")  # noqa: PLR2004
        )
        self.problems = tuple(problems)


# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class Adjustment:
    """One override: the cell, what it should hold, and why.

    ``remove`` takes the cell out of the return — it becomes unreported, which
    is not the same as reporting zero. Otherwise exactly one of ``value`` and
    ``text_value`` is given. ``decimals`` optionally restates the accuracy.
    """

    table: str
    row: str
    column: str
    reason: str
    sheet: str | None = None
    open_key: str | None = None
    value: float | None = None
    text_value: str | None = None
    decimals: int | None = None
    remove: bool = False

    @property
    def cell(self) -> tuple[str, str | None, str | None, str, str]:
        return (self.table, self.sheet, self.open_key, self.row, self.column)

    def describe(self) -> str:
        """The cell's address, e.g. ``OF07.00.01.01[z0008][r0010][c0010]``."""
        sheet = f"[z{self.sheet}]" if self.sheet else ""
        key = f"[{self.open_key}]" if self.open_key else ""
        return f"{self.table}{sheet}{key}[r{self.row}][c{self.column}]"


@dataclass(frozen=True)
class AppliedAdjustment:
    """An adjustment as applied: what the cell held before, and holds after."""

    adjustment: Adjustment
    action: str
    before: float | str | None
    after: float | str | None

    def as_record(self) -> dict[str, Any]:
        """A JSON-ready record, for a manifest or a ledger."""
        adjustment = self.adjustment
        return {
            "cell": adjustment.describe(),
            "table": adjustment.table,
            "sheet": adjustment.sheet,
            "open_key": adjustment.open_key,
            "row": adjustment.row,
            "column": adjustment.column,
            "action": self.action,
            "before": self.before,
            "after": self.after,
            "reason": adjustment.reason,
        }


def read_adjustments(path: Path) -> list[Adjustment]:
    """Read an adjustments file: a fact table with a ``reason`` column.

    The columns are the canonical fact columns (``table``, ``sheet``,
    ``open_key``, ``row``, ``column``, ``value``, ``text_value``, ``decimals``)
    plus ``reason`` (required) and ``remove`` (optional; yes / true to take the
    cell out). CSV or Parquet.

    Raises:
        ValueError: the file type is not supported or a required column is
            missing.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pl.read_csv(path, infer_schema=False)
    elif suffix == ".parquet":
        frame = pl.read_parquet(path)
    else:
        raise ValueError(f"Unsupported adjustments file type {suffix!r}; expected .csv or .parquet")
    frame = frame.rename({name: name.strip().lower() for name in frame.columns})
    missing = [
        name for name in ("table", "row", "column", COLUMN_REASON) if name not in frame.columns
    ]
    if missing:
        raise ValueError(f"{path.name} is missing column(s) {', '.join(missing)}")

    def text(row: dict[str, Any], name: str) -> str | None:
        value = row.get(name)
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    def number(row: dict[str, Any], name: str) -> float | None:
        value = text(row, name)
        try:
            return None if value is None else float(value)
        except ValueError:
            return None

    adjustments: list[Adjustment] = []
    for row in frame.iter_rows(named=True):
        decimals = number(row, "decimals")
        value = number(row, "value")
        # A figure that is not a number is kept as text, so it is reported as a
        # value of the wrong type rather than dropped.
        unparsed = text(row, "value") if value is None else None
        adjustments.append(
            Adjustment(
                table=text(row, "table") or "",
                row=text(row, "row") or "",
                column=text(row, "column") or "",
                reason=text(row, COLUMN_REASON) or "",
                sheet=text(row, "sheet"),
                open_key=text(row, "open_key"),
                value=value,
                text_value=text(row, "text_value") or unparsed,
                decimals=None if decimals is None else int(decimals),
                remove=(text(row, COLUMN_REMOVE) or "").lower() in _TRUE,
            )
        )
    logger.info("read %d adjustment(s) from %s", len(adjustments), path.name)
    return adjustments


def apply_adjustments(
    ret: CanonicalReturn, adjustments: Iterable[Adjustment]
) -> tuple[CanonicalReturn, tuple[AppliedAdjustment, ...]]:
    """Apply ``adjustments`` to ``ret``; return the adjusted return and what was done.

    The batch is applied whole or not at all.

    Raises:
        AdjustmentError: an adjustment has no reason, has no cell, gives both
            or neither of a value and a text value, repeats another's cell, or
            removes a cell the return does not report.
    """
    batch = list(adjustments)
    current = {
        tuple(row[name] for name in COORDINATE_COLUMNS): row
        for row in ret.facts.iter_rows(named=True)
    }
    problems = _problems(batch, set(current))
    if problems:
        raise AdjustmentError(problems)

    applied: list[AppliedAdjustment] = []
    for adjustment in batch:
        existing = current.get(adjustment.cell)
        before = None if existing is None else _held(existing)
        if adjustment.remove:
            del current[adjustment.cell]
            applied.append(AppliedAdjustment(adjustment, ACTION_REMOVE, before, None))
            continue
        after: float | str | None = (
            adjustment.value if adjustment.value is not None else adjustment.text_value
        )
        decimals = adjustment.decimals
        if decimals is None and existing is not None:
            decimals = existing["decimals"]
        current[adjustment.cell] = {
            **dict(zip(COORDINATE_COLUMNS, adjustment.cell, strict=True)),
            "value": adjustment.value,
            "text_value": adjustment.text_value,
            "decimals": decimals,
        }
        if existing is None:
            action = ACTION_SET
        else:
            action = ACTION_NONE if before == after else ACTION_CHANGE
        applied.append(AppliedAdjustment(adjustment, action, before, after))

    frame = pl.DataFrame(list(current.values()), schema=FACT_SCHEMA, orient="row")
    logger.info("applied %d adjustment(s)", len(applied))
    return CanonicalReturn.from_frame(ret.header, frame, ret.indicators), tuple(applied)


# =============================================================================
# Private helpers
# =============================================================================


def _held(row: dict[str, Any]) -> float | str | None:
    return row["value"] if row["value"] is not None else row["text_value"]


def _problems(batch: list[Adjustment], reported: set[tuple[Any, ...]]) -> list[str]:
    problems: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    for number, adjustment in enumerate(batch, start=1):
        label = f"adjustment {number} ({adjustment.describe()})"
        if not (adjustment.table and adjustment.row and adjustment.column):
            problems.append(f"adjustment {number} does not name a table, row and column")
            continue
        if not adjustment.reason.strip():
            problems.append(f"{label} gives no reason")
        if adjustment.cell in seen:
            problems.append(f"{label} repeats a cell an earlier adjustment already sets")
        seen.add(adjustment.cell)
        given = (adjustment.value is not None) + (adjustment.text_value is not None)
        if adjustment.remove:
            if given:
                problems.append(f"{label} both removes the cell and gives it a value")
            if adjustment.cell not in reported:
                problems.append(f"{label} removes a cell the return does not report")
        elif given != 1:
            problems.append(f"{label} must give exactly one of a value and a text value")
    return problems
