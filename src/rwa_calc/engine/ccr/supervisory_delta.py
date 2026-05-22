"""
Supervisory delta for SA-CCR trades.

Pipeline position:
    Classifier -> CCRCalculator (delta) -> ...

Key responsibilities:
- Assign the linear-instrument supervisory delta (+/- 1) per CRR Art. 279a(1).

This batch (P8.4) ships the stub signature only; the linear (and
option / CDO tranche) bodies land in P8.13.

References:
- CRR Art. 279a: Supervisory delta
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


@cites("CRR Art. 279a")
def compute_supervisory_delta_linear(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for linear trades (stub).

    Args:
        trades: LazyFrame at trade grain with a ``direction`` indicator.

    Raises:
        NotImplementedError: Body lands in P8.13 (linear +/- 1 sub-piece
            per Art. 279a(1)).
    """
    raise NotImplementedError("P8.13 — linear ±1 sub-piece per Art. 279a(1)")
