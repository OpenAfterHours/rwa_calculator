"""
Maturity factor for SA-CCR trades (unmargined netting sets).

Pipeline position:
    Classifier -> CCRCalculator (maturity factor) -> ...

Key responsibilities:
- Compute ``MF = sqrt(min(M, 1y) / 1y)`` per CRR Art. 279c(1) for trades
  in unmargined netting sets.

This batch (P8.4) ships the stub signature only; the body lands in P8.14.

References:
- CRR Art. 279c(1): Maturity factor (unmargined)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


# Watchfire's bundled CRR index does not yet contain Art. 279c; collapse the
# ``@cites`` to the parent Art. 279 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 279")
def compute_maturity_factor_unmargined(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Maturity factor for unmargined trades (stub).

    Args:
        trades: LazyFrame at trade grain with a residual-maturity column.

    Raises:
        NotImplementedError: Body lands in P8.14
            (MF = sqrt(min(M, 1y) / 1y)).
    """
    raise NotImplementedError("P8.14 — MF = sqrt(min(M, 1y) / 1y)")
