"""
Null-safe summation helpers shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (applied to collected result subsets to populate template cells)

Key responsibilities:
- Sum a single column, distinguishing "column absent" (None) from
  "column present but zero / empty" (0.0)
- Sum a group of columns, skipping absent ones

Behaviour variants: the two generators deliberately disagree on what a
missing input means for a template cell, and unifying them would change
report output, so both semantics are kept here explicitly:

- COREP reports 0.0 for an empty subset and 0.0 when none of a column
  group exists (``col_sum`` default, ``safe_sum``).
- Pillar 3 reports a null cell for an empty subset
  (``col_sum(..., empty_as_none=True)``) and a null cell when none of a
  column group exists (``safe_sum_or_none``).

Nulls within a present column always count as 0.0 (Polars ``sum`` ignores
nulls; an all-null or empty column sums to 0.0, never null).

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations

import polars as pl


def col_sum(
    data: pl.DataFrame,
    cols: set[str],
    col_name: str | None,
    *,
    empty_as_none: bool = False,
) -> float | None:
    """Sum a single column, returning None when the column is absent.

    With ``empty_as_none=True`` an empty *data* frame also yields None
    (Pillar 3 semantics: empty subset -> null cell); the default yields
    0.0 (COREP semantics: empty subset -> zero cell).
    """
    if col_name is None or col_name not in cols:
        return None
    if empty_as_none and data.height == 0:
        return None
    return float(data[col_name].fill_null(0.0).sum())


def safe_sum(data: pl.DataFrame, cols: set[str], *col_names: str) -> float:
    """Sum multiple columns, skipping absent ones; 0.0 when none is present.

    COREP semantics: a column group with no member present reports 0.0.
    See ``safe_sum_or_none`` for the Pillar 3 null-cell variant.
    """
    total = 0.0
    for c in col_names:
        if c in cols:
            total += float(data[c].fill_null(0.0).sum())
    return total


def safe_sum_or_none(data: pl.DataFrame, cols: set[str], *col_names: str) -> float | None:
    """Sum multiple columns, skipping absent ones; None when none is present.

    Pillar 3 semantics: a column group with no member present reports a
    null cell. See ``safe_sum`` for the COREP zero-cell variant.
    """
    found = False
    total = 0.0
    for c in col_names:
        if c in cols:
            total += float(data[c].fill_null(0.0).sum())
            found = True
    return total if found else None
