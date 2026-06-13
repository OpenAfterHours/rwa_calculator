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

    from polars._typing import PolarsDataType


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

    dtype: PolarsDataType
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


def dtypes_of(schema: Mapping[str, ColumnSpec]) -> dict[str, PolarsDataType]:
    """Project a ColumnSpec schema down to ``{column_name: dtype}``.

    Polars constructors (``pl.DataFrame(..., schema=...)``, ``pl.LazyFrame``)
    accept a plain dtype dict; this helper is the bridge for those call sites.
    """
    return {name: spec.dtype for name, spec in schema.items()}


def apply_boolean_column_defaults(
    lf: pl.LazyFrame, schema: Mapping[str, ColumnSpec]
) -> pl.LazyFrame:
    """Fill nulls in present Boolean columns with their schema defaults.

    Pipeline position:
        Called by ``loader.enforce_schema`` strictly *after* the cast pass:
        ``ensure_columns -> cast -> apply_boolean_column_defaults``. The
        order matters — running before cast against an inferred ``pl.Null``
        column would fail to type-coerce the literal cleanly.

    Why Boolean-only:
        A naive helper that filled nulls on every ``ColumnSpec(default=...)``
        column would also fill ``Float64`` defaults of ``0.0`` (e.g.
        ``LOAN_SCHEMA.drawn_amount``, ``PROVISION_SCHEMA.amount``). That is
        anti-conservative for EAD and provisions: a null in a parquet today
        propagates and surfaces in arithmetic as a null-bearing EAD (caught
        by validation); a silent ``0.0`` does not. Float and String defaults
        are intentionally **not** filled by this helper — broadening it
        requires Risk sign-off.

        The Boolean-only boundary is enforced by
        ``tests/contracts/test_boolean_defaults_only.py`` which asserts that
        non-Boolean defaults are NOT filled by this helper. Any future
        contributor who needs to broaden it must update both this helper
        and the contract test, surfacing the change for explicit review.

    Args:
        lf: LazyFrame to fill nulls on.
        schema: ColumnSpec schema. Only Boolean columns with a non-None
            default are filled; non-Boolean entries are silently skipped
            (the contract test pins this behaviour). Columns absent from
            ``lf`` are not added (use ``ensure_columns`` for that).

    Returns:
        LazyFrame with nulls filled in present Boolean columns.
    """
    existing = set(lf.collect_schema().names())

    fill_exprs = [
        pl.col(name).fill_null(pl.lit(spec.default).cast(pl.Boolean)).alias(name)
        for name, spec in schema.items()
        if spec.default is not None and spec.dtype == pl.Boolean and name in existing
    ]

    if not fill_exprs:
        return lf
    return lf.with_columns(fill_exprs)
