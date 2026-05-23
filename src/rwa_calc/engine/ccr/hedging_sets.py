"""
SA-CCR hedging-set partition and IR maturity-bucket assignment.

Pipeline position:
    compute_adjusted_notional -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class

Key responsibilities:
- Assign each trade to a maturity bucket per CRR Art. 277(2) for the
  interest-rate asset class:
      LT_1Y    : residual maturity M < 1 year
      1Y_5Y    : 1 year <= M <= 5 years
      GT_5Y    : M > 5 years
  For non-IR asset classes the bucket is left null (deferred to FX/equity/
  credit/commodity batches).
- Compose a stable ``hedging_set_id`` per Art. 277(1) of the form
  ``"<asset_short>-<netting_set_id>-<currency>-<maturity_bucket>"`` so that
  the downstream add-on aggregator can group D_b sums by bucket.

References:
- CRR Art. 277(1): hedging-set definition (one per currency within IR).
- CRR Art. 277(2): IR maturity bucket thresholds LT_1Y / 1Y_5Y / GT_5Y.
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


# Asset-class short codes used in the composite ``hedging_set_id`` string.
_ASSET_CLASS_SHORT: dict[str, str] = {
    "interest_rate": "IR",
    "foreign_exchange": "FX",
    "credit": "CR",
    "equity": "EQ",
    "commodity": "CO",
}


@cites("CRR Art. 277")
def assign_ir_maturity_bucket(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Assign an IR maturity bucket per CRR Art. 277(2).

    For ``asset_class == "interest_rate"`` rows, derive ``maturity_bucket``
    from ``years_to_maturity``:

        LT_1Y : M < 1
        1Y_5Y : 1 <= M <= 5
        GT_5Y : M > 5

    Non-IR rows receive a null bucket (extended in subsequent batches).

    Args:
        trades: LazyFrame with ``asset_class`` and ``years_to_maturity``
            columns.

    Returns:
        The input LazyFrame with a new ``maturity_bucket: Utf8`` column.

    References:
        CRR Art. 277(2)(a)-(c); BCBS CRE52.32.
    """
    is_ir = pl.col("asset_class") == "interest_rate"
    m = pl.col("years_to_maturity")

    bucket = (
        pl.when(is_ir & (m < 1.0))
        .then(pl.lit("LT_1Y"))
        .when(is_ir & (m <= 5.0))
        .then(pl.lit("1Y_5Y"))
        .when(is_ir & (m > 5.0))
        .then(pl.lit("GT_5Y"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("maturity_bucket")
    )

    return trades.with_columns(bucket)


@cites("CRR Art. 277")
def assign_hedging_set(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Assign a composite ``hedging_set_id`` per CRR Art. 277(1).

    Pipeline-position note: ``years_to_maturity`` must already be on the
    input frame (the upstream maturity-factor stage adds it).

    The hedging-set identifier composes the asset-class short code, the
    netting-set id, the trade currency and the maturity bucket as
    ``"<asset_short>-<netting_set_id>-<currency>-<maturity_bucket>"`` —
    e.g. ``"IR-NS-IR-01-GBP-GT_5Y"``. Non-IR rows receive a null
    ``hedging_set_id`` until the corresponding asset-class batch lands.

    Args:
        trades: LazyFrame with ``asset_class``, ``netting_set_id``,
            ``currency``, ``years_to_maturity`` columns.

    Returns:
        The input LazyFrame with new ``maturity_bucket: Utf8`` and
        ``hedging_set_id: Utf8`` columns.

    References:
        CRR Art. 277(1)-(2); BCBS CRE52.30-32.
    """
    trades = assign_ir_maturity_bucket(trades)

    asset_short = pl.col("asset_class").replace_strict(
        _ASSET_CLASS_SHORT, default=None, return_dtype=pl.Utf8
    )

    hedging_set_id = (
        pl.when(pl.col("maturity_bucket").is_not_null())
        .then(
            pl.concat_str(
                [
                    asset_short,
                    pl.col("netting_set_id"),
                    pl.col("currency"),
                    pl.col("maturity_bucket"),
                ],
                separator="-",
            )
        )
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("hedging_set_id")
    )

    return trades.with_columns(hedging_set_id)
