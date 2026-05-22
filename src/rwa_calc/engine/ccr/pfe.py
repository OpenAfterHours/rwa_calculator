"""
Potential Future Exposure (PFE) skeleton for SA-CCR.

Pipeline position:
    Classifier -> CCRCalculator (PFE) -> CRMProcessor

Key responsibilities:
- Aggregate per-trade adjusted-notional / delta / maturity-factor /
  supervisory-factor terms into per-netting-set add-ons and apply the
  PFE multiplier per CRR Art. 278.

This batch (P8.4) ships the stub signature only; the body lands across
P8.10 (sub-piece aggregation) and P8.16 (full PFE with multiplier).

References:
- CRR Art. 278: Potential future exposure (multiplier + add-on)
- CRR Art. 280-280f: Asset-class add-ons (IR singleton path scoped here)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


@cites("CRR Art. 278")
def compute_pfe_ir_singleton(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """Potential Future Exposure for the single-trade IR path (stub).

    Args:
        netting_sets: LazyFrame at netting-set grain.

    Raises:
        NotImplementedError: Full PFE body lands in P8.16; the per-trade
            sub-pieces (P8.10-P8.14) must be in place first.
    """
    raise NotImplementedError(
        "P8.10-P8.14 sub-pieces required first; full PFE per Art. 278 is P8.16"
    )
