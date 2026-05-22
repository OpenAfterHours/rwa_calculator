"""
SA-CCR EAD top-level calculator.

Pipeline position:
    Classifier -> CCRCalculator -> CRMProcessor

Key responsibilities:
- Combine replacement cost (RC) and potential future exposure (PFE) into
  Exposure at Default per CRR Art. 274: ``EAD = alpha * (RC + PFE)``.

This batch (P8.4) ships the stub signature only; the body lands in P8.17
once RC, PFE and the alpha multiplier sub-pieces are all in place.

References:
- CRR Art. 274: SA-CCR EAD = alpha * (RC + PFE)
"""

from __future__ import annotations

import logging

import polars as pl

from rwa_calc.contracts.config import CCRConfig

logger = logging.getLogger(__name__)


# NOTE: No ``@cites("CRR Art. 274")`` — watchfire's bundled rulebook index
# (rulebook_version 2026-05-15) does not yet contain CRR Art. 274. Article
# attribution is preserved in the docstring; re-extending the watchfire CRR
# index for Art. 274 is a separate follow-up (mirrors the P8.7 fix-commit
# pattern for Art. 280a/b/c).
def compute_ead(netting_sets: pl.LazyFrame, config: CCRConfig | None = None) -> pl.LazyFrame:
    """SA-CCR Exposure at Default (stub).

    Args:
        netting_sets: LazyFrame at netting-set grain carrying RC and PFE.
        config: CCR configuration (alpha multiplier, supervisory factors).
            Optional during the scaffold phase; required from P8.17 onwards.

    Raises:
        NotImplementedError: Body lands in P8.17
            (alpha * (RC + PFE) per CRR Art. 274).
    """
    raise NotImplementedError("P8.17 — α×(RC+PFE) lands in next first-batch ticket")
