"""
Replacement Cost (RC) for SA-CCR netting sets.

Pipeline position:
    Classifier -> CCRCalculator (RC) -> CRMProcessor

Key responsibilities:
- Compute ``rc_unmargined = max(V_net - C_net, 0)`` at netting-set grain
  per CRR Art. 275(1).
- Compute ``rc_margined = max(V_net - C_net, TH + MTA - NICA, 0)`` for
  margined netting sets per CRR Art. 275(2); null for unmargined rows.

References:
- CRR Art. 275(1): RC_unmargined = max(V_net - C_net, 0)
- CRR Art. 275(2): RC_margined = max(V - C, TH + MTA - NICA, 0)
- BCBS CRE52.11: RC formula for margined netting sets
"""

from __future__ import annotations

import logging

import polars as pl

logger = logging.getLogger(__name__)


# NOTE: No ``@cites("CRR Art. 275")`` — watchfire's bundled rulebook index
# (rulebook_version 2026-05-15) does not yet contain CRR Art. 275. Article
# attribution is preserved in the docstring; re-extending the watchfire CRR
# index for Art. 275 is a separate follow-up (mirrors the P8.7 fix-commit
# pattern for Art. 280a/b/c).
def compute_rc_unmargined(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """Replacement Cost for unmargined transactions (Art. 275(1)).

    Adds an ``rc_unmargined`` column to ``netting_sets`` containing
    ``max(v_net - c_net, 0)``.

    Args:
        netting_sets: LazyFrame with at least ``v_net`` and ``c_net`` columns
            at netting-set grain.

    Returns:
        LazyFrame with an additional ``rc_unmargined`` Float64 column.
    """
    return netting_sets.with_columns(
        pl.max_horizontal(pl.col("v_net") - pl.col("c_net"), pl.lit(0.0)).alias("rc_unmargined")
    )


# NOTE: No ``@cites("CRR Art. 275")`` — see waiver rationale on
# ``compute_rc_unmargined`` above. Same article, same index gap.
def compute_rc_margined(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """Replacement Cost for margined transactions (Art. 275(2)).

    Adds an ``rc_margined`` column to ``netting_sets`` containing
    ``max(v_net - c_net, margin_threshold + minimum_transfer_amount - nica, 0)``
    for rows with ``is_margined=True``; null for unmargined rows.

    Args:
        netting_sets: LazyFrame with ``v_net``, ``c_net``, ``is_margined``,
            ``margin_threshold``, ``minimum_transfer_amount``, and ``nica``
            columns at netting-set grain.

    Returns:
        LazyFrame with an additional ``rc_margined`` Float64 column.
    """
    return netting_sets.with_columns(
        pl.when(pl.col("is_margined"))
        .then(
            pl.max_horizontal(
                pl.col("v_net") - pl.col("c_net"),
                pl.col("margin_threshold") + pl.col("minimum_transfer_amount") - pl.col("nica"),
                pl.lit(0.0),
            )
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("rc_margined")
    )
