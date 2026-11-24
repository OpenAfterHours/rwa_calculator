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
  For non-IR asset classes the bucket is left null (deferred to equity /
  credit / commodity batches; FX has no maturity sub-bucketing — its hedging
  set is keyed on the currency pair instead).
- Compose a stable ``hedging_set_id`` per Art. 277(1):
    * IR:        ``"<asset_short>-<netting_set_id>-<currency>-<maturity_bucket>"``
                 — one per (currency, maturity bucket).
    * FX:        ``"FX-<netting_set_id>-<pair>"`` where ``<pair>`` is the
                 order-independent ``min(currency, currency_leg2)/max(...)`` —
                 one hedging set per currency pair (Art. 277(3)(a)). A trade
                 flagged ``fx_own_hedging_set`` (a leg with no spot rate, or a
                 missing second-leg notional the rule needs, so its adjusted
                 notional is an estimate, or no second leg, so it states no
                 pair) is its own hedging set,
                 ``"FX-<netting_set_id>-<pair>-trade-<trade_id>"``: it
                 offsets nothing (P1.406).
    * Credit:    ``"CR-<netting_set_id>"``               — Art. 277(2)(c)
    * Equity:    ``"EQ-<netting_set_id>"``               — Art. 277(2)(d)
    * Commodity: ``"CO-<netting_set_id>-<bucket>"``      — Art. 277(3)(b)

  Single-name vs index discrimination for credit / equity is deferred to
  the aggregation step (Art. 277a + Art. 280a/b) and does not partition
  the hedging set here.

References:
- CRR Art. 277(1): hedging-set definition (one per currency within IR).
- CRR Art. 277(2): IR maturity bucket thresholds LT_1Y / 1Y_5Y / GT_5Y.
- CRR Art. 277(2)(c)-(d): credit / equity — one hedging set per asset
  class per netting set.
- CRR Art. 277(3)(a) / BCBS CRE52.34: FX hedging set = currency pair, no
  maturity sub-bucketing.
- CRR Art. 277a(1)(b): FX trades share a hedging set "only where their primary
  risk driver ... is based on the same currency pair".
- CRR Art. 277(3)(b) / BCBS CRE52.67: commodity hedging set keyed on
  commodity_type bucket (ELECTRICITY / OIL_GAS / METALS / AGRICULTURAL /
  OTHER).
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import ASSET_CLASS_SHORT_CODE
from rwa_calc.engine.ccr.adjusted_notional import FX_OWN_HEDGING_SET

logger = logging.getLogger(__name__)

# Written by compute_adjusted_notional_fx; frames built without that branch (unit
# tests) read as no unconverted leg.
_OPTIONAL_COLUMNS = {FX_OWN_HEDGING_SET: ColumnSpec(pl.Boolean, default=False, required=False)}


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
    e.g. ``"IR-NS-IR-01-GBP-GT_5Y"``. FX, credit, equity and commodity rows
    take the keys listed in the module docstring.

    An FX trade flagged ``fx_own_hedging_set`` gets its own hedging set,
    ``"FX-<netting_set_id>-<pair>-trade-<trade_id>"`` (the pair dropped when no
    leg has a currency; the ``trade`` token keeps the key off every pair key).
    Its adjusted notional is an estimate — a leg with no spot rate entered
    unconverted, or a stated second leg has no notional and the rule needs it
    (a reporting-currency second leg does not: Art. 279b(1)(b)(ii) takes the
    first leg, and that trade is not flagged) — or it states no second
    currency, so no pair (Art. 277a(1)(b)); either way it is kept out of
    the pair's netting, as a trade with an unknown risk driver is kept out of
    the other-risks netting (``engine/ccr/risk_categories.py::compute_addon_other``).
    Netted, the estimate could offset a correctly priced trade and lower the
    netting set's add-on below its value with complete inputs (P1.406).

    Args:
        trades: LazyFrame with ``trade_id``, ``asset_class``,
            ``netting_set_id``, ``currency``, ``currency_leg2``,
            ``years_to_maturity`` columns, and optionally
            ``fx_own_hedging_set`` (absent reads as False).

    Returns:
        The input LazyFrame with new ``maturity_bucket: Utf8`` and
        ``hedging_set_id: Utf8`` columns.

    References:
        CRR Art. 277(1)-(2); CRR Art. 277a(1)(b); BCBS CRE52.30-32.
    """
    trades = assign_ir_maturity_bucket(ensure_columns(trades, _OPTIONAL_COLUMNS))

    # Defensive: upstream stages that pre-date the credit/equity/commodity
    # branches may pass frames without ``commodity_type``. The column is
    # required only by the commodity branch and may be safely treated as
    # all-null when absent — Polars evaluates the dispatch ladder eagerly
    # at plan-resolve time, so the column must exist on the schema.
    schema_names = trades.collect_schema().names()
    if "commodity_type" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Utf8).alias("commodity_type"))

    asset_short = pl.col("asset_class").replace_strict(
        ASSET_CLASS_SHORT_CODE, default=None, return_dtype=pl.Utf8
    )

    # Order-independent currency pair for FX hedging-set keying (Art. 277(3)(a)).
    # ``min/max`` of the two ISO-4217 strings collapses EUR/USD and USD/EUR
    # into a single hedging set per netting set.
    fx_pair = pl.concat_str(
        [
            pl.min_horizontal(pl.col("currency"), pl.col("currency_leg2")),
            pl.lit("/"),
            pl.max_horizontal(pl.col("currency"), pl.col("currency_leg2")),
        ]
    )

    ir_hs = pl.concat_str(
        [
            asset_short,
            pl.col("netting_set_id"),
            pl.col("currency"),
            pl.col("maturity_bucket"),
        ],
        separator="-",
    )

    fx_hs = pl.concat_str(
        [pl.lit("FX"), pl.col("netting_set_id"), fx_pair],
        separator="-",
    )
    # A trade priced with an unconverted leg: its own hedging set. ignore_nulls
    # keeps the trade id in the key when no leg has a currency (pair null).
    isolated_fx_hs = pl.concat_str(
        [pl.lit("FX"), pl.col("netting_set_id"), fx_pair, pl.lit("trade"), pl.col("trade_id")],
        separator="-",
        ignore_nulls=True,
    )

    credit_hs = pl.concat_str(
        [pl.lit("CR"), pl.col("netting_set_id")],
        separator="-",
    )

    equity_hs = pl.concat_str(
        [pl.lit("EQ"), pl.col("netting_set_id")],
        separator="-",
    )

    commodity_hs = pl.concat_str(
        [pl.lit("CO"), pl.col("netting_set_id"), pl.col("commodity_type")],
        separator="-",
    )

    hedging_set_id = (
        pl.when(pl.col("asset_class") == "interest_rate")
        .then(pl.when(pl.col("maturity_bucket").is_not_null()).then(ir_hs).otherwise(None))
        .when(pl.col("asset_class") == "fx")
        .then(pl.when(pl.col(FX_OWN_HEDGING_SET)).then(isolated_fx_hs).otherwise(fx_hs))
        .when(pl.col("asset_class") == "credit")
        .then(credit_hs)
        .when(pl.col("asset_class") == "equity")
        .then(equity_hs)
        .when(pl.col("asset_class") == "commodity")
        .then(pl.when(pl.col("commodity_type").is_not_null()).then(commodity_hs).otherwise(None))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("hedging_set_id")
    )

    return trades.with_columns(hedging_set_id)
