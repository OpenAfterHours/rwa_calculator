"""
Equity result preparation.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.domain.enums import ApproachType


def prepare_equity_results(
    equity_results: pl.LazyFrame,
    *,
    include_sa_equivalent: bool = False,
) -> pl.LazyFrame:
    """Add equity approach tag, ensure exposure_class exists, and normalize RWA.

    Equity rows enter the results frame via this path (concatenated at the
    aggregator), NOT through hierarchy/unify, so the reconciliation base
    ``source_exposure_reference`` must be populated here too — equity is
    base-grain, so it equals ``exposure_reference``. Without this, equity rows
    would carry an injected null base and any base-grain reconciliation key
    would collapse every equity exposure into one null-keyed group.

    When ``include_sa_equivalent`` is set the equity leg's standardised-equivalent
    RWA (``sa_rwa``) is populated as its own pre-floor RWA. Under Basel 3.1 the IRB
    equity treatment is removed (Art. 147A / CRE20.58-62), so equity is
    standardised-only and its standardised-equivalent RWA IS the RWA the equity
    calculator already produced. The SA calculator never runs on equity legs, so
    without this ``sa_rwa`` stays null and the disclosed S-TREA (OF 02.01 col 0040,
    C 02.00 col 0020, CMS1/CMS2 col d) would silently drop equity. The flag mirrors
    the SA calculator's own ``output_floor``-Feature gate on ``sa_rwa`` so no
    ``sa_rwa`` column is minted on CRR frames that never carry one. Equity is not
    floor-eligible, so this leaves the output-floor base and ``rwa_final`` unchanged.
    """
    cols = set(equity_results.collect_schema().names())
    rwa_col = "rwa" if "rwa" in cols else "rwa_final"

    result = equity_results
    if "exposure_class" not in cols:
        result = result.with_columns([pl.lit("equity").alias("exposure_class")])

    prepared = [
        pl.lit(ApproachType.EQUITY.value).alias("approach_applied"),
        pl.col(rwa_col).alias("rwa_final"),
        # Equity is base-grain, so its reconciliation base equals its own
        # reference (set unconditionally — no presence guard).
        pl.col("exposure_reference").alias("source_exposure_reference"),
    ]
    if include_sa_equivalent:
        prepared.append(pl.col(rwa_col).alias("sa_rwa"))

    return result.with_columns(prepared)
