"""
Shared utility functions for the RWA calculation engine.

Provides common LazyFrame validation helpers used across
loader, pipeline, hierarchy, and CRM modules.
"""

from __future__ import annotations

import polars as pl


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

    Schema-only check — does not materialise any data. Use this instead
    of ``is_valid_optional_data`` in pipeline stages where premature
    ``.collect()`` calls should be avoided.

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


def is_valid_optional_data(
    data: pl.LazyFrame | None,
    required_columns: set[str] | None = None,
) -> bool:
    """
    Check if optional data is valid for processing.

    .. deprecated::
        Use :func:`has_required_columns` instead — it avoids premature
        ``.collect()`` calls that defeat lazy evaluation.

    Validates that data:
    - Is not None
    - Has required columns (if specified)
    - Has at least one row

    Args:
        data: Optional LazyFrame to validate
        required_columns: Set of column names that must be present (optional)

    Returns:
        True if data is valid for processing, False otherwise
    """
    if data is None:
        return False

    try:
        schema = data.collect_schema()

        if required_columns is not None:
            if not required_columns.issubset(set(schema.names())):
                return False

        return data.head(1).collect().height > 0
    except Exception:
        return False
