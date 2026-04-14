"""
Column specification for schema-driven DataFrame defaults.

Pipeline position:
    Shared data-layer primitive — used by data/schemas.py declarations and
    by engine stages (loader, calculators) that need to ensure columns exist
    before calculation.

Key responsibilities:
- Declare per-column metadata (dtype, default, required) in one place
- Fill missing optional columns on a LazyFrame with declared defaults
- Project a ColumnSpec schema down to a plain dtype dict for
  Polars constructors that require {name: dtype}

References:
- CLAUDE.md — data/engine separation; data/tables and data/schemas are the
  only modules permitted to declare regulatory / pipeline-default values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Declarative metadata for a single DataFrame column.

    Attributes:
        dtype: Polars dtype the column is cast to on load.
        default: Fill value applied by ``ensure_columns`` when the column is
            absent. Ignored when ``required`` is True.
        required: When True, a missing column is a data-quality error; the
            loader must fail (or emit a CalculationError). When False, a
            missing column is filled via ``ensure_columns`` using ``default``.
    """

    dtype: pl.DataType
    default: object = None
    required: bool = True


def ensure_columns(lf: pl.LazyFrame, schema: Mapping[str, ColumnSpec]) -> pl.LazyFrame:
    """Add optional columns from ``schema`` that are missing on ``lf``.

    Required columns are never added — the loader is responsible for raising
    a data-quality error when a required input column is missing. Columns
    already present on ``lf`` are left untouched (including their existing
    dtype — this function does not re-cast).
    """
    existing = set(lf.collect_schema().names())
    missing = [
        pl.lit(spec.default).cast(spec.dtype).alias(name)
        for name, spec in schema.items()
        if not spec.required and name not in existing
    ]
    if not missing:
        return lf
    return lf.with_columns(missing)


def dtypes_of(schema: Mapping[str, ColumnSpec]) -> dict[str, pl.DataType]:
    """Project a ColumnSpec schema down to ``{column_name: dtype}``.

    Polars constructors (``pl.DataFrame(..., schema=...)``, ``pl.LazyFrame``)
    accept a plain dtype dict; this helper is the bridge for those call sites.
    """
    return {name: spec.dtype for name, spec in schema.items()}
