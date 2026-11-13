"""
Diff — two versions of a return, cell by cell.

Pipeline position:
    previous CanonicalReturn + current CanonicalReturn  ->  diff_returns  ->  ReturnDiff

Key responsibilities:
- Say exactly what changed between a filing and its resubmission: which cells
  were added, which removed, which hold a different figure and by how much.
- Compare like with like. Both returns are addressed in the taxonomy's own
  coordinates, so a cell is the same cell whichever system or file format each
  version came from.
- Report header changes separately: a different entity or reference date is
  not a cell change, and usually means the wrong two files are being compared.

References:
- rwa_filer.model — the canonical fact schema
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.model import COORDINATE_COLUMNS

if TYPE_CHECKING:
    from rwa_filer.model import CanonicalReturn

# =============================================================================
# Constants
# =============================================================================

CHANGE_ADDED: Final = "added"
CHANGE_REMOVED: Final = "removed"
CHANGE_CHANGED: Final = "changed"

#: The change table, in column order. ``before`` / ``after`` are the figures;
#: the ``_text`` pair carries cells that hold text. ``delta`` is after - before
#: for a figure that changed.
CHANGE_SCHEMA: Final = pl.Schema(
    {
        "table": pl.String,
        "sheet": pl.String,
        "open_key": pl.String,
        "row": pl.String,
        "column": pl.String,
        "change": pl.String,
        "before": pl.Float64,
        "after": pl.Float64,
        "delta": pl.Float64,
        "before_text": pl.String,
        "after_text": pl.String,
    }
)


# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class ReturnDiff:
    """What differs between two versions of a return.

    Attributes:
        header: ``{field: (previous, current)}`` for each header field that
            differs.
        changes: One row per cell that differs (``CHANGE_SCHEMA``), in
            coordinate order.
        unchanged: Cells present in both with the same content.
    """

    header: dict[str, tuple[str | None, str | None]]
    changes: pl.DataFrame
    unchanged: int

    @property
    def is_identical(self) -> bool:
        """Whether the two returns have the same header and the same cells."""
        return not self.header and self.changes.is_empty()

    def counts(self) -> dict[str, int]:
        """Cells per kind of change, always with all three kinds."""
        found = dict(self.changes.group_by("change").len().iter_rows())
        return {kind: found.get(kind, 0) for kind in (CHANGE_ADDED, CHANGE_REMOVED, CHANGE_CHANGED)}

    def by_table(self) -> dict[str, int]:
        """Changed cells per table, most first."""
        counts = (
            self.changes.group_by("table").len().sort(["len", "table"], descending=[True, False])
        )
        return dict(counts.iter_rows())

    def as_record(self) -> dict[str, Any]:
        """A JSON-ready record of the whole diff."""
        return {
            "identical": self.is_identical,
            "header": {name: list(pair) for name, pair in self.header.items()},
            "counts": self.counts(),
            "unchanged": self.unchanged,
            "by_table": self.by_table(),
            "changes": self.changes.to_dicts(),
        }


def diff_returns(previous: CanonicalReturn, current: CanonicalReturn) -> ReturnDiff:
    """Compare two returns cell by cell.

    A cell is "changed" when it is in both and its figure or its text differs;
    a change of stated accuracy alone (``decimals``) is not a change of content.
    """
    coordinates = list(COORDINATE_COLUMNS)
    before = previous.facts.select(
        *coordinates, pl.col("value").alias("before"), pl.col("text_value").alias("before_text")
    ).with_columns(pl.lit(True).alias("_in_before"))
    after = current.facts.select(
        *coordinates, pl.col("value").alias("after"), pl.col("text_value").alias("after_text")
    ).with_columns(pl.lit(True).alias("_in_after"))
    joined = before.join(after, on=coordinates, how="full", coalesce=True, nulls_equal=True)

    in_before = pl.col("_in_before").fill_null(False)
    in_after = pl.col("_in_after").fill_null(False)
    same = pl.col("before").eq_missing(pl.col("after")) & pl.col("before_text").eq_missing(
        pl.col("after_text")
    )
    kind = (
        pl.when(~in_before)
        .then(pl.lit(CHANGE_ADDED))
        .when(~in_after)
        .then(pl.lit(CHANGE_REMOVED))
        .when(~same)
        .then(pl.lit(CHANGE_CHANGED))
        .otherwise(None)
    )
    labelled = joined.with_columns(kind.alias("change"))
    changes = (
        labelled.filter(pl.col("change").is_not_null())
        .with_columns((pl.col("after") - pl.col("before")).alias("delta"))
        .select(CHANGE_SCHEMA.names())
        .cast(CHANGE_SCHEMA)
        .sort(coordinates, nulls_last=False)
    )
    return ReturnDiff(
        header=_header_changes(previous, current),
        changes=changes,
        unchanged=labelled.filter(pl.col("change").is_null()).height,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _header_changes(
    previous: CanonicalReturn, current: CanonicalReturn
) -> dict[str, tuple[str | None, str | None]]:
    before, after = previous.header.as_fields(), current.header.as_fields()
    return {
        name: (before.get(name), after.get(name))
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }
