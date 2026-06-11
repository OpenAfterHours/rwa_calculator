"""
Shared utility functions for the RWA calculation engine.

Provides common LazyFrame validation helpers and date utilities used across
loader, pipeline, hierarchy, CRM, IRB, and slotting modules.
"""

from __future__ import annotations

from datetime import date

import polars as pl

# Partition keys that can carry null values in the engine's frames. A naked
# ``.over(key)`` on any of these will collapse all null-keyed rows into one
# bucket, silently pooling unrelated rows in pro-rata aggregates. Use
# ``partition_by_nullable`` to guard window aggregates over these keys.
#
# This set is the single source of truth for the AST contract test at
# ``tests/contracts/test_no_raw_over_on_nullable_keys.py`` — keep both in sync.
# Membership is derived from ``ColumnSpec(required=False)`` columns and
# left-join nullable inputs in ``data/schemas.py``.
NULLABLE_PARTITION_KEYS: frozenset[str] = frozenset(
    {
        "parent_facility_reference",
        "lending_group_reference",
        "counterparty_reference",
    }
)


def partition_by_nullable(
    agg_expr: pl.Expr,
    key: str,
    else_expr: pl.Expr,
) -> pl.Expr:
    """Guard a window aggregate against null-partition collapse.

    Polars ``.over(key)`` collapses ALL null-keyed rows into a single
    partition, so an unguarded ``.sum()`` over a nullable key silently
    aggregates unrelated rows together — typically producing wrong pro-rata
    weights downstream. This helper wraps an ``agg_expr`` (which already
    contains ``.over(key)``) in a ``pl.when(key.is_not_null())`` conditional,
    falling back to ``else_expr`` for null-keyed rows.

    The shape is intentionally a thin ``pl.when`` shim, not an ``.over``
    injector: call sites with compound additive aggregates (e.g.
    ``drawn.over(K) + nominal.over(K)``) or multi-key partitions can
    construct ``agg_expr`` themselves and pass it in fully formed.

    Args:
        agg_expr: The window aggregate expression. Must contain ``.over(key)``.
        key: The partition column name; must match ``agg_expr``'s ``.over`` arg.
        else_expr: Expression evaluated for rows where ``key`` is null. Accepts
            any ``pl.Expr`` — column references, literals (wrap scalars in
            ``pl.lit``), or other ``.over()`` expressions (e.g. a fallback
            aggregation over a different key).

    Returns:
        A conditional Polars expression safe against null-partition collapse.
    """
    return pl.when(pl.col(key).is_not_null()).then(agg_expr).otherwise(else_expr)


def exact_fractional_years_expr(
    start_date: date,
    end_col: str,
) -> pl.Expr:
    """
    Calculate fractional years between a fixed start date and an end date column.

    Uses the year fraction method where each day represents 1/365 of a year,
    regardless of leap years. This provides consistent treatment across all
    periods and is standard for regulatory maturity calculations (CRR Article 162).

    Formula:
        years = (end_year - start_year) + (end_ordinal/365) - (start_ordinal/365)

    Works with LazyFrames and streaming (pure expression-based).

    Args:
        start_date: The fixed start date (e.g., reporting_date from config)
        end_col: Name of the end date column

    Returns:
        Polars expression calculating fractional years
    """
    end = pl.col(end_col)

    start_year = start_date.year
    start_ordinal = start_date.timetuple().tm_yday
    start_frac = start_ordinal / 365.0

    end_year = end.dt.year()
    end_ordinal = end.dt.ordinal_day()
    end_frac = end_ordinal.cast(pl.Float64) / 365.0

    return (end_year - start_year).cast(pl.Float64) + (end_frac - pl.lit(start_frac))


def has_rows(lf: pl.LazyFrame) -> bool:
    """
    Check if a LazyFrame has any rows.

    Note: This triggers a `.head(1).collect()` — prefer schema-only checks
    in the pipeline. Retained for loader use where file-scan limit pushdown
    makes this efficient.

    Args:
        lf: LazyFrame to check

    Returns:
        True if LazyFrame has at least one row, False otherwise
    """
    try:
        schema = lf.collect_schema()
        if len(schema) == 0:
            return False
        return lf.head(1).collect().height > 0
    except Exception:
        return False


def has_required_columns(
    data: pl.LazyFrame | None,
    required_columns: set[str] | None = None,
) -> bool:
    """
    Check if a LazyFrame is not None and has the required columns.

    Schema-only check — does not materialise any data. Preferred in
    pipeline stages where premature ``.collect()`` calls should be avoided.

    Args:
        data: Optional LazyFrame to validate
        required_columns: Column names that must be present (optional)

    Returns:
        True if data is not None and contains all required columns
    """
    if data is None:
        return False
    if required_columns is None:
        return True
    try:
        schema = data.collect_schema()
        return required_columns.issubset(set(schema.names()))
    except Exception:
        return False
