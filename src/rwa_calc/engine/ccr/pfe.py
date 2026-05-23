"""
Potential Future Exposure (PFE) skeleton for SA-CCR.

Pipeline position:
    Classifier -> CCRCalculator (PFE) -> CRMProcessor

Key responsibilities:
- Aggregate per-trade adjusted-notional / delta / maturity-factor /
  supervisory-factor terms into per-netting-set add-ons and apply the
  PFE multiplier per CRR Art. 278.
- Per CRR Art. 277a(1)(a), aggregate per-bucket effective notionals
  D_b into per-asset-class add-ons using the supervisory cross-bucket
  correlation matrix.

This batch (P8.4) ships the stub signature only; the body lands across
P8.10 (sub-piece aggregation) and P8.16 (full PFE with multiplier).

References:
- CRR Art. 277a(1)(a): asset-class add-on cross-bucket aggregation.
- CRR Art. 278: Potential future exposure (multiplier + add-on)
- CRR Art. 280-280f: Asset-class add-ons (IR singleton path scoped here)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.data.tables.sa_ccr_factors import (
    SA_CCR_IR_BUCKET_CORRELATION_12,
    SA_CCR_IR_BUCKET_CORRELATION_13,
    SA_CCR_IR_BUCKET_CORRELATION_23,
    SA_CCR_SUPERVISORY_FACTOR_IR,
)

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


# Watchfire's bundled CRR index does not yet contain Art. 277a; collapse the
# ``@cites`` to the parent Art. 277 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 277")
def compute_addon_per_asset_class(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Per-asset-class SA-CCR add-on aggregated from bucket effective notionals.

    Implements CRR Art. 277a(1)(a) for the interest-rate asset class:

        D_b      = sum_i ( delta_i * d_i * MF_i )  over trades in bucket b
        AddOn_IR = SF_IR * sqrt(
                        D_B1^2 + D_B2^2 + D_B3^2
                        + 2 * rho_12 * D_B1 * D_B2
                        + 2 * rho_23 * D_B2 * D_B3
                        + 2 * rho_13 * D_B1 * D_B3
                   )

    where ``B1=LT_1Y``, ``B2=1Y_5Y``, ``B3=GT_5Y``; ``rho_12 = rho_23 = 0.7``
    and ``rho_13 = 0.3`` are the supervisory cross-bucket correlations.

    Non-IR asset classes are currently emitted with a null
    ``asset_class_addon`` and will be filled by the FX / credit / equity /
    commodity batches.

    Args:
        trades: LazyFrame at trade grain with at minimum ``netting_set_id``,
            ``asset_class``, ``maturity_bucket``, ``supervisory_delta``,
            ``adjusted_notional`` and ``maturity_factor`` columns.

    Returns:
        LazyFrame with one row per (``netting_set_id``, ``asset_class``)
        and columns ``netting_set_id``, ``asset_class``,
        ``asset_class_addon: Float64``.

    References:
        CRR Art. 277a(1)(a); CRR Art. 280 Table 1 (SF_IR = 0.5%); BCBS CRE52.55-58.
    """
    rho_12 = float(SA_CCR_IR_BUCKET_CORRELATION_12)
    rho_23 = float(SA_CCR_IR_BUCKET_CORRELATION_23)
    rho_13 = float(SA_CCR_IR_BUCKET_CORRELATION_13)
    sf_ir = float(SA_CCR_SUPERVISORY_FACTOR_IR)

    # Per-trade effective notional = delta * d * MF (Art. 277a(1)(a)).
    trade_terms = trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # D_b per (netting_set_id, asset_class, maturity_bucket).
    d_b = trade_terms.group_by(["netting_set_id", "asset_class", "maturity_bucket"]).agg(
        pl.col("effective_notional_trade").sum().alias("d_bucket")
    )

    # Pivot the three IR buckets into wide columns per (netting_set_id, asset_class).
    d_lt_1y = d_b.filter(pl.col("maturity_bucket") == "LT_1Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b1")]
    )
    d_1y_5y = d_b.filter(pl.col("maturity_bucket") == "1Y_5Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b2")]
    )
    d_gt_5y = d_b.filter(pl.col("maturity_bucket") == "GT_5Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b3")]
    )

    # Base keys: every (netting_set_id, asset_class) that appears in the input,
    # so that asset classes with no IR buckets still emit a row (currently null).
    keys = trades.select(["netting_set_id", "asset_class"]).unique()

    joined = (
        keys.join(d_lt_1y, on=["netting_set_id", "asset_class"], how="left")
        .join(d_1y_5y, on=["netting_set_id", "asset_class"], how="left")
        .join(d_gt_5y, on=["netting_set_id", "asset_class"], how="left")
        .with_columns(
            [
                pl.col("d_b1").fill_null(0.0),
                pl.col("d_b2").fill_null(0.0),
                pl.col("d_b3").fill_null(0.0),
            ]
        )
    )

    inner = (
        pl.col("d_b1") ** 2
        + pl.col("d_b2") ** 2
        + pl.col("d_b3") ** 2
        + 2.0 * rho_12 * pl.col("d_b1") * pl.col("d_b2")
        + 2.0 * rho_23 * pl.col("d_b2") * pl.col("d_b3")
        + 2.0 * rho_13 * pl.col("d_b1") * pl.col("d_b3")
    )

    addon_ir = sf_ir * inner.sqrt()

    return joined.with_columns(
        pl.when(pl.col("asset_class") == "interest_rate")
        .then(addon_ir)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("asset_class_addon")
    ).select(["netting_set_id", "asset_class", "asset_class_addon"])
