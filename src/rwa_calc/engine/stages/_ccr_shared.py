"""
Shared helpers for the CCR-variant stages (SA-CCR and SFT FCCM).

Pipeline position:
    hierarchy_resolver -> ccr_sa_ccr -> sft_fccm -> classifier

Key responsibilities:
- ``enrich_ccr_rows_with_ratings``: join the resolved counterparty rating
  columns onto synthetic CCR/SFT exposure rows, mirroring the per-exposure
  rating attach that ``hierarchy._attach_counterparty_rating`` performs for
  traditional lending rows. Both the SA-CCR stage (``engine/stages/ccr.py``)
  and the SFT FCCM stage (``engine/stages/sft.py``) append synthetic rows
  AFTER hierarchy resolution, so each needs this enrichment before the
  classifier and SA institution lookup run — lifted here so the two stages
  share one implementation (SFT/FCCM separation Phase 5).

References:
- CRR Art. 120(1) Table 3 — rated institution risk-weight lookup (keyed off cqs)
- CRR Art. 121(1) — unrated institution fallback (the 100% default this avoids)
- CRR Art. 143 — IRB routing (keyed off internal_pd)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup

logger = logging.getLogger(__name__)


def enrich_ccr_rows_with_ratings(
    ccr_exposure_rows: pl.LazyFrame,
    counterparty_lookup: CounterpartyLookup,
) -> pl.LazyFrame:
    """Join the resolved counterparty rating columns onto CCR/SFT rows.

    Mirrors the per-exposure rating attach performed by
    ``hierarchy._attach_counterparty_rating`` for traditional lending
    rows. The CCR/SFT stages run AFTER hierarchy resolution and append
    synthetic rows via ``diagonal_relaxed`` concat, so without this
    enrichment those rows reach the SA calculator with ``cqs=None``
    / ``external_cqs=None`` / ``internal_pd=None`` and the institution
    risk-weight lookup falls through to its unrated 100% fallback
    (CRR Art. 121(1)) instead of the rated CQS table
    (CRR Art. 120(1) Table 3).
    """
    cp_schema = set(counterparty_lookup.counterparties.collect_schema().names())
    rating_cols = [c for c in ("cqs", "pd", "internal_pd", "external_cqs") if c in cp_schema]
    if not rating_cols:
        return ccr_exposure_rows
    cp_select = [pl.col("counterparty_reference"), *(pl.col(c) for c in rating_cols)]
    return ccr_exposure_rows.join(
        counterparty_lookup.counterparties.select(cp_select),
        on="counterparty_reference",
        how="left",
    )
