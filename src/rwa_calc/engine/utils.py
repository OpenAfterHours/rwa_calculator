"""
Shared utility functions for the RWA calculation engine.

Provides common LazyFrame validation helpers used across
loader, pipeline, hierarchy, and CRM modules.
"""

from __future__ import annotations

from typing import Optional

import polars as pl


def has_rows(lf: pl.LazyFrame) -> bool:
    """
    Check if a LazyFrame has any rows.

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


def is_valid_optional_data(
    data: Optional[pl.LazyFrame],
    required_columns: Optional[set[str]] = None,
) -> bool:
    """
    Check if optional data is valid for processing.

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
