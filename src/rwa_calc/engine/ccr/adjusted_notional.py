"""
Per-trade adjusted notional for SA-CCR (interest-rate asset class).

Pipeline position:
    Classifier -> CCRCalculator (adjusted notional) -> ...

Key responsibilities:
- Compute the interest-rate adjusted notional ``d_i`` per CRR Art. 279b,
  i.e. the trade notional scaled by the supervisory duration factor.

This batch (P8.4) ships the stub signature only; the formula body and the
``SA_CCR_SUPERVISORY_DURATION_RATE`` constant land in P8.12.

References:
- CRR Art. 279b: Adjusted notional amount (IR / FX)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


# Watchfire's bundled CRR index does not yet contain Art. 279b; collapse the
# ``@cites`` to the parent Art. 279 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 279")
def compute_adjusted_notional_ir(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Adjusted notional for IR trades (stub).

    Args:
        trades: LazyFrame at trade grain with IR trade attributes.

    Raises:
        NotImplementedError: Body lands in P8.12 (IR adjusted notional via
            Art. 279b duration formula).
    """
    raise NotImplementedError("P8.12 — IR adjusted notional via Art. 279b duration formula")
