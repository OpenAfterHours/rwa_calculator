"""
FX rate synchronisation helper.

Pipeline position:
    Loader -> (fx_rate_sync) -> PipelineOrchestrator.run_with_data

Key responsibilities:
- Extract the EUR->GBP rate from a loaded fx_rates LazyFrame so the pipeline
  can keep ``CalculationConfig.eur_gbp_rate`` consistent with the FX data used
  for amount conversion.

The scalar ``config.eur_gbp_rate`` feeds the IRB SME correlation expression
(CRR Art. 153) and the GBP equivalents of EUR regulatory thresholds
(``RegulatoryThresholds.crr``). Keeping it aligned with the ``fx_rates`` table
avoids silent divergence between amount conversion and threshold derivation.

References:
- CRR Art. 153(4): SME correlation adjustment (EUR-denominated thresholds)
- RegulatoryThresholds.crr(): threshold derivation at contracts/config.py
"""

from __future__ import annotations

import logging
from decimal import Decimal

import polars as pl

logger = logging.getLogger(__name__)


def extract_eur_gbp_rate(fx_rates: pl.LazyFrame | None) -> Decimal | None:
    """Return the EUR->GBP rate from the fx_rates table, or None.

    Args:
        fx_rates: LazyFrame with columns ``currency_from``, ``currency_to``,
            ``rate`` (per ``FX_RATES_SCHEMA``), or None.

    Returns:
        The rate as ``Decimal`` when exactly one ``(EUR, GBP)`` row is
        present. Returns None when the table is missing, has no matching
        row, or has more than one (the latter is logged at WARNING so the
        caller can see why auto-sync was skipped).
    """
    if fx_rates is None:
        return None

    matches = (
        fx_rates.filter((pl.col("currency_from") == "EUR") & (pl.col("currency_to") == "GBP"))
        .select("rate")
        .collect()
    )

    if matches.height == 0:
        return None
    if matches.height > 1:
        logger.warning(
            "fx_rates table has %d (EUR, GBP) rows; skipping eur_gbp_rate auto-sync",
            matches.height,
        )
        return None

    return Decimal(str(matches.item(0, 0)))
