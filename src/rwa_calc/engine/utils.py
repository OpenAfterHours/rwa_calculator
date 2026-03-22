"""
Shared utility functions for the RWA calculation engine.

Provides common LazyFrame validation helpers and date utilities used across
loader, pipeline, hierarchy, CRM, IRB, and slotting modules.
"""

from __future__ import annotations

from datetime import date

import polars as pl


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

        if required_columns is not None and not required_columns.issubset(set(schema.names())):
            return False

        return data.head(1).collect().height > 0
    except Exception:
        return False
