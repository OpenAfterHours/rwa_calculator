"""
Aggregator utility functions.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl


def resolve_rwa_col(col_names: frozenset[str] | list[str] | set[str]) -> str | None:
    """
    Resolve which RWA column to use with a consistent fallback chain.

    Order: rwa_post_factor -> rwa_final -> rwa.

    Returns:
        Column name, or None if no RWA column found.
    """
    names = col_names if isinstance(col_names, (frozenset, set)) else set(col_names)
    if "rwa_post_factor" in names:
        return "rwa_post_factor"
    if "rwa_final" in names:
        return "rwa_final"
    if "rwa" in names:
        return "rwa"
    return None


def col_or_default(
    name: str,
    cols: frozenset[str] | set[str],
    default: pl.Expr | None = None,
    dtype: pl.DataType = pl.String,
) -> pl.Expr:
    """
    Return ``pl.col(name)`` if the column exists, otherwise a default expression.

    Args:
        name: Column name to look for.
        cols: Available column names.
        default: Default expression. If None, uses ``pl.lit(None).cast(dtype)``.
        dtype: Data type for the null literal when no default is provided.
    """
    if name in cols:
        return pl.col(name)
    if default is not None:
        return default.alias(name)
    return pl.lit(None).cast(dtype).alias(name)


def empty_frame(schema: dict[str, pl.DataType]) -> pl.LazyFrame:
    """Create an empty LazyFrame from a schema dict."""
    return pl.LazyFrame({name: pl.Series([], dtype=dtype) for name, dtype in schema.items()})
