"""Statistical function backend abstraction for IRB formulas.

Provides normal_cdf() and normal_ppf() expressions with automatic backend detection.
Tries polars-normal-stats first (native, fast), falls back to scipy (universal).

Usage:
    from rwa_calc.engine.irb.stats_backend import normal_cdf, normal_ppf, get_backend

    # In expressions
    result = df.with_columns(normal_cdf(pl.col("x")).alias("cdf"))

    # Check which backend is active
    backend = get_backend()  # Returns "polars-normal-stats" or "scipy"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    pass


# =============================================================================
# BACKEND DETECTION
# =============================================================================

_BACKEND: str | None = None


def _detect_backend() -> str:
    """Detect available statistical backend at import time."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    # Try polars-normal-stats first (native Polars, fastest)
    try:
        import polars_normal_stats  # noqa: F401

        _BACKEND = "polars-normal-stats"
        return _BACKEND
    except ImportError:
        pass

    # Fall back to scipy (universal)
    try:
        import scipy.stats  # noqa: F401

        _BACKEND = "scipy"
        return _BACKEND
    except ImportError:
        pass

    msg = (
        "No statistical backend available. "
        "Install either 'polars-normal-stats' or 'scipy':\n"
        "  uv add polars-normal-stats  # Recommended: native Polars\n"
        "  uv add scipy                # Fallback: universal"
    )
    raise ImportError(msg)


def get_backend() -> str:
    """Return the name of the active statistical backend.

    Returns:
        "polars-normal-stats" or "scipy"

    Raises:
        ImportError: If no backend is available
    """
    return _detect_backend()


# =============================================================================
# SCIPY BACKEND IMPLEMENTATION
# =============================================================================


def _scipy_normal_cdf(expr: pl.Expr) -> pl.Expr:
    """Apply normal CDF using scipy via map_batches."""
    from scipy.stats import norm

    def _cdf_batch(s: pl.Series) -> pl.Series:
        values = s.to_numpy()
        result = norm.cdf(values)
        return pl.Series(name=s.name, values=result)

    return expr.map_batches(_cdf_batch, return_dtype=pl.Float64)


def _scipy_normal_ppf(expr: pl.Expr) -> pl.Expr:
    """Apply normal PPF (inverse CDF) using scipy via map_batches."""
    from scipy.stats import norm

    def _ppf_batch(s: pl.Series) -> pl.Series:
        values = s.to_numpy()
        result = norm.ppf(values)
        return pl.Series(name=s.name, values=result)

    return expr.map_batches(_ppf_batch, return_dtype=pl.Float64)


# =============================================================================
# PUBLIC API
# =============================================================================


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
    backend = _detect_backend()

    if backend == "polars-normal-stats":
        from polars_normal_stats import normal_cdf as native_cdf

        return native_cdf(expr)
    else:
        return _scipy_normal_cdf(expr)


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
    backend = _detect_backend()

    if backend == "polars-normal-stats":
        from polars_normal_stats import normal_ppf as native_ppf

        return native_ppf(expr)
    else:
        return _scipy_normal_ppf(expr)


# =============================================================================
# MODULE INITIALIZATION
# =============================================================================

# Detect backend at import time to fail fast
_detect_backend()
