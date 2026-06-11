"""
Column discovery helpers shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (called at generator entry to resolve which result columns are present)

Key responsibilities:
- Materialise the set of available column names from a LazyFrame schema
  without collecting the frame
- Resolve the first present column name from an ordered candidate list
  (pipeline results expose the same quantity under historical aliases,
  e.g. ``ead_final`` / ``final_ead`` / ``ead``)

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations

import polars as pl


def available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from *candidates* that exists in *cols*."""
    for c in candidates:
        if c in cols:
            return c
    return None
