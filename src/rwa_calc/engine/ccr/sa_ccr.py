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
def compute_ead(
    netting_sets: pl.LazyFrame,
    config: CCRConfig | None = None,
) -> pl.LazyFrame:
    """SA-CCR exposure value per CRR Art. 274(2): EAD = α × (RC + PFE).

    Pure composition layer that consumes pre-computed netting-set-grain
    columns ``rc_unmargined`` (Art. 275) and ``pfe_addon`` (Art. 278; for
    CCR-A1 the PFE multiplier of Art. 278(3) is 1, so ``pfe_addon`` equals
    the asset-class AddOn aggregate). α defaults to 1.4 (Art. 274(2)) but
    may be overridden via ``config.alpha``.

    Args:
        netting_sets: LazyFrame at netting-set grain with columns
            ``rc_unmargined: Float64`` and ``pfe_addon: Float64``.
        config: Optional CCRConfig; when provided ``config.alpha`` overrides
            the default α=1.4.

    Returns:
        Input LazyFrame with a new ``ead_ccr: Float64`` column.

    References:
        CRR Art. 274(2); BCBS CRE52.
    """
    alpha_value = float(config.alpha) if config is not None else 1.4
    return netting_sets.with_columns(
        (pl.lit(alpha_value) * (pl.col("rc_unmargined") + pl.col("pfe_addon"))).alias("ead_ccr")
    )
