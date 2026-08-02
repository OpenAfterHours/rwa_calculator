"""
The fixed regulatory PD scale row axis shared by COREP C 08.03 and C 08.05.

Pipeline position:
    OutputAggregator -> corep.c08 (C 08.03 / C 08.05) -> COREPTemplateBundle

Key responsibilities:
- Derive the two PD-band label columns an exposure frame needs to key the
  hierarchical row axis (``c08_pd_range`` = leaf band, ``c08_pd_parent`` =
  enclosing parent band)
- Return the populated rows in published template order, sparse

Why two columns: the published scale is HIERARCHICAL, not a partition. Four of
its top-level bands repeat their span as a finer sub-breakdown on the rows
immediately below, so a parent row overlaps its children and equals their sum
(EBA v09753-v09756 / BoE boe_b0767-boe_b0770). An exposure sits in exactly one
LEAF band, but a parent row spans several leaves, so no single label column can
key every row. Splitting the label into leaf and parent keeps every row a single
equality term, which is the shape ``SheetPlan.row_terms`` and the rebuilt
drill-down predicates both require.

References:
- Regulation (EU) 2021/451 Annex I, template C 08.03 (row axis)
- PRA PS1/26 Annex I, template OF 08.03 (row axis; splits the first sub-band)
- PRA PS1/26 Annex II §3.3.5, "PD RANGE (PRE-INPUT FLOOR) (%)" row instructions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.corep.templates import (
    C08_03_PD_PARENT_REFS,
    get_c08_03_pd_ranges,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

#: The derived leaf-band label column: the one band an exposure actually sits in.
PD_LEAF_COL = "c08_pd_range"

#: The derived parent-band label column: the enclosing aggregate band, or
#: "Unassigned" for a PD outside every parent's span (the 0.15-0.75 and
#: 100%-default bands stand alone).
PD_PARENT_COL = "c08_pd_parent"

#: The residual row for a null / out-of-scale PD.
UNASSIGNED = "Unassigned"

_Band = tuple[float, float, str, str]


def banded_rows(
    class_df: pl.DataFrame, alloc_pd_col: str, framework: str
) -> tuple[list[tuple[str, str, str]], pl.DataFrame]:
    """Assign the fixed PD scale to ``class_df``.

    Returns the populated ``(row_ref, label, term_column)`` rows in published
    template order — plus a trailing 9999 "Unassigned" row when any PD falls
    outside the scale — and the frame with both label columns added.

    Rows stay sparse (only populated bands emit). A populated leaf always
    populates its parent, so a parent never emits without at least one child.
    """
    ranges = get_c08_03_pd_ranges(framework)
    leaves = [band for band in ranges if band[2] not in C08_03_PD_PARENT_REFS]
    parents = [band for band in ranges if band[2] in C08_03_PD_PARENT_REFS]
    banded = class_df.with_columns(
        _band_label_expr(leaves, alloc_pd_col).alias(PD_LEAF_COL),
        _band_label_expr(parents, alloc_pd_col).alias(PD_PARENT_COL),
    )
    present = {
        PD_LEAF_COL: set(banded[PD_LEAF_COL].to_list()),
        PD_PARENT_COL: set(banded[PD_PARENT_COL].to_list()),
    }
    rows: list[tuple[str, str, str]] = []
    for _lower, _upper, ref, label in ranges:
        column = PD_PARENT_COL if ref in C08_03_PD_PARENT_REFS else PD_LEAF_COL
        if label in present[column]:
            rows.append((ref, label, column))
    if UNASSIGNED in present[PD_LEAF_COL]:
        rows.append(("9999", UNASSIGNED, PD_LEAF_COL))
    return rows, banded


def _band_label_expr(bands: Sequence[_Band], alloc_pd_col: str) -> pl.Expr:
    """A label expression over half-open ``[lower, upper)`` bands.

    Falls through to "Unassigned" outside every band, which is also where a null
    PD lands.
    """
    expr: pl.Expr = pl.lit(UNASSIGNED)
    for lower, upper, _ref, label in reversed(bands):
        expr = (
            pl.when((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
            .then(pl.lit(label))
            .otherwise(expr)
        )
    return expr
