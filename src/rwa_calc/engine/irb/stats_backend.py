"""Statistical functions for IRB formulas.

Provides normal_cdf() and normal_ppf() expressions using polars-normal-stats.
"""

from __future__ import annotations

import polars as pl
from polars_normal_stats import normal_cdf as _native_cdf
from polars_normal_stats import normal_ppf as _native_ppf


def normal_cdf(expr: pl.Expr) -> pl.Expr:
    """Standard normal CDF (cumulative distribution function).

    Computes P(X <= x) for standard normal distribution.

    Args:
        expr: Polars expression containing x values

    Returns:
        Polars expression with CDF values in [0, 1]

    Example:
        df.with_columns(normal_cdf(pl.col("z_score")).alias("probability"))
    """
    return _native_cdf(expr)


def normal_ppf(expr: pl.Expr) -> pl.Expr:
    """Standard normal PPF (percent point function / inverse CDF).

    Computes the z-score such that P(X <= z) = p.

    Args:
        expr: Polars expression containing probability values in (0, 1)

    Returns:
        Polars expression with z-scores

    Example:
        df.with_columns(normal_ppf(pl.col("probability")).alias("z_score"))
    """
    return _native_ppf(expr)
