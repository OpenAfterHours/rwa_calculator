"""
Equity result preparation.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.domain.enums import ApproachType


def prepare_equity_results(equity_results: pl.LazyFrame) -> pl.LazyFrame:
    """Add equity approach tag, ensure exposure_class exists, and normalize RWA.

    Equity rows enter the results frame via this path (concatenated at the
    aggregator), NOT through hierarchy/unify, so the reconciliation base
    ``source_exposure_reference`` must be populated here too — equity is
    base-grain, so it equals ``exposure_reference``. Without this, equity rows
    would carry an injected null base and any base-grain reconciliation key
    would collapse every equity exposure into one null-keyed group.
    """
    cols = set(equity_results.collect_schema().names())
    rwa_col = "rwa" if "rwa" in cols else "rwa_final"

    result = equity_results
    if "exposure_class" not in cols:
        result = result.with_columns([pl.lit("equity").alias("exposure_class")])

    return result.with_columns(
        [
            pl.lit(ApproachType.EQUITY.value).alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
            # Equity is base-grain, so its reconciliation base equals its own
            # reference (set unconditionally — no presence guard).
            pl.col("exposure_reference").alias("source_exposure_reference"),
        ]
    )
