"""
Supervisory delta for SA-CCR trades.

Pipeline position:
    Classifier -> CCRCalculator (delta) -> ...

Key responsibilities:
- Assign the linear-instrument supervisory delta (+/- 1) per CRR Art. 279a(1).

This batch (P8.13) ships the linear (+/- 1) sub-piece of Art. 279a(1).
The European-option Black-Scholes Phi(d1) branch (Art. 279a(2),
``option_strike.is_not_null()`` rows) and the CDO-tranche formula are
deferred to a future P-item — option rows currently fall through to the
linear placeholder.

References:
- CRR Art. 279a: Supervisory delta
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


# NOTE: The option Phi(d1) branch (rows where ``option_strike`` is not null)
# and the CDO-tranche formula are deferred. The linear +/- 1 expression below
# is applied to all rows until the option sub-piece lands.
@cites("CRR Art. 279a")
def compute_supervisory_delta_linear(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for non-option directional trades per CRR Art. 279a(1).

    delta = +1 for long positions in the primary risk driver
    delta = -1 for short positions in the primary risk driver

    The European-option Black-Scholes Phi(d1) branch (for rows where
    ``option_strike`` is not null) and the CDO-tranche formula are
    explicitly deferred to the next batch after CCR-A1.

    Args:
        trades: LazyFrame containing an ``is_long`` Boolean column.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(1); BCBS CRE52.41-43.
    """
    return trades.with_columns(
        pl.when(pl.col("is_long")).then(1.0).otherwise(-1.0).alias("supervisory_delta")
    )
