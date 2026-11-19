"""
SA-CCR risk-category mapping, conservative input fallbacks and the other-risks category.

Pipeline position:
    ccr_rows_to_exposures: map_trade_risk_categories -> compute_adjusted_notional_*
    (incl. compute_adjusted_notional_other) -> supervisory delta -> maturity factor
    -> assign_hedging_set -> compute_addon_per_asset_class (incl. compute_addon_other)

Key responsibilities:
- Map every trade to one of the six CRR Art. 277(1) risk categories. The
  ``asset_class`` input is matched case-insensitively (the input gate's DQ006
  check is case-insensitive, so the engine must read the same values); a missing
  or unrecognised value is priced in the Art. 277(1)(f) other-risks category
  instead of contributing no add-on at all (review CC-06; reported as CCR021 by
  ``contracts/ccr_input_checks.py``).
- Conservative risk-factor fallbacks (reported as CCR022): a credit trade whose
  ``credit_quality`` is missing or unrecognised takes the highest supervisory
  factor of its sub-class table (single name -> NON_RATED, index -> HY); a
  commodity trade whose ``commodity_type`` is missing or unrecognised is assigned
  to the commodity hedging set with the highest supervisory factor (ELECTRICITY).
  Before CC-06 each of these contributed a zero add-on with no error.
- The other-risks category itself: adjusted notional per Art. 279b(1)(d) and the
  add-on per Art. 280f (SF_Other 8%, one hedging set per identical primary risk
  driver per Art. 277a(1)(f)).

References:
- CRR Art. 277(1): "Institutions shall map each transaction of a netting set to
  one of the following risk categories ... (f) other risks."
- CRR Art. 277a(1)(f): other-risks hedging sets — same set "only where their
  primary risk driver ... is identical".
- CRR Art. 279b(1)(d): other-risks adjusted notional — "the most appropriate
  method among the methods set out in points (a), (b) and (c)".
- CRR Art. 280f(2): "SF Other = ... 8%".
- PS1/26 Annex R leaves Art. 277-280f unamended (regime-invariant).
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import TRADE_SCHEMA, VALID_SA_CCR_ASSET_CLASSES
from rwa_calc.rulebook.compile import lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Regime-invariant SA-CCR parameters (CRR Art. 279b / 280 / 280f) resolved from
# the rulepack once at module load.
_PACK = resolve("crr", date(2026, 1, 1))
_SF_OTHER = scalar_value(_PACK.scalar_param("sa_ccr_supervisory_factor_other"))
_SUPERVISORY_DURATION_RATE = scalar_value(_PACK.scalar_param("sa_ccr_supervisory_duration_rate"))
_START_FLOOR_YEARS = scalar_value(_PACK.scalar_param("sa_ccr_start_floor_years"))
_SF_CREDIT_SN = lookup_float_map(_PACK.lookup("sa_ccr_supervisory_factors_credit_sn"))
_SF_CREDIT_IDX = lookup_float_map(_PACK.lookup("sa_ccr_supervisory_factors_credit_idx"))
_SF_COMMODITY = lookup_float_map(_PACK.lookup("sa_ccr_supervisory_factors_commodity"))

#: The Art. 277(1)(f) category token, and the asset class a trade is priced in
#: when its own asset_class is missing or unrecognised.
OTHER_RISK_CATEGORY: str = "other"

# Conservative fallback labels, DERIVED from the pack tables rather than restated:
# the key carrying the highest supervisory factor of each table.
_CREDIT_SN_FALLBACK = str(max(_SF_CREDIT_SN, key=lambda key: _SF_CREDIT_SN[key]))
_CREDIT_IDX_FALLBACK = str(max(_SF_CREDIT_IDX, key=lambda key: _SF_CREDIT_IDX[key]))
_COMMODITY_FALLBACK = str(max(_SF_COMMODITY, key=lambda key: _SF_COMMODITY[key]))
_CREDIT_QUALITIES = [str(key) for key in {**_SF_CREDIT_SN, **_SF_CREDIT_IDX}]
_COMMODITY_TYPES = [str(key) for key in _SF_COMMODITY]

# Optional TRADE_SCHEMA columns this module reads; minimal unit-test frames may
# omit them, so they are injected as typed nulls (no presence guard).
_OPTIONAL_TRADE_COLUMNS = {
    name: TRADE_SCHEMA[name]
    for name in (
        "credit_quality",
        "commodity_type",
        "is_index",
        "underlying_reference",
        "market_price",
        "number_of_units",
    )
}


@cites("CRR Art. 277")
def map_trade_risk_categories(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Normalise the SA-CCR risk-category inputs and apply the conservative fallbacks.

    Rewrites three trade columns in place (all other columns pass through):

    - ``asset_class``: trimmed and lower-cased; a value outside
      ``VALID_SA_CCR_ASSET_CLASSES`` (or null) becomes ``"other"`` (Art. 277(1)(f)).
    - ``credit_quality`` (credit trades): trimmed and upper-cased; a value outside
      the pack's credit-quality keys (or null) becomes the key carrying the highest
      supervisory factor of the trade's sub-class table — ``NON_RATED`` for a
      single name, ``HY`` for an index (``is_index`` null reads as single name).
    - ``commodity_type`` (commodity trades): trimmed and upper-cased; a value
      outside the pack's commodity keys (or null) becomes the key carrying the
      highest supervisory factor (``ELECTRICITY``).

    Non-credit / non-commodity rows keep their (case-folded) value unchanged.

    Args:
        trades: Trade-grain LazyFrame (TRADE_SCHEMA).

    Returns:
        ``trades`` with the three columns normalised as above.

    References:
        CRR Art. 277(1); CRR Art. 277a(1)(c)/(e); CRR Art. 280 (supervisory factors).
    """
    trades = ensure_columns(trades, _OPTIONAL_TRADE_COLUMNS)
    asset = pl.col("asset_class").cast(pl.String).str.strip_chars().str.to_lowercase()
    quality = pl.col("credit_quality").cast(pl.String).str.strip_chars().str.to_uppercase()
    commodity = pl.col("commodity_type").cast(pl.String).str.strip_chars().str.to_uppercase()
    is_index = pl.coalesce(pl.col("is_index"), pl.lit(False))

    mapped = trades.with_columns(
        pl.when(asset.is_in(sorted(VALID_SA_CCR_ASSET_CLASSES)))
        .then(asset)
        .otherwise(pl.lit(OTHER_RISK_CATEGORY))
        .alias("asset_class")
    )
    return mapped.with_columns(
        pl.when(pl.col("asset_class") != "credit")
        .then(quality)
        .when(quality.is_in(_CREDIT_QUALITIES))
        .then(quality)
        .when(is_index)
        .then(pl.lit(_CREDIT_IDX_FALLBACK))
        .otherwise(pl.lit(_CREDIT_SN_FALLBACK))
        .alias("credit_quality"),
        pl.when(pl.col("asset_class") != "commodity")
        .then(commodity)
        .when(commodity.is_in(_COMMODITY_TYPES))
        .then(commodity)
        .otherwise(pl.lit(_COMMODITY_FALLBACK))
        .alias("commodity_type"),
    )


@cites("CRR Art. 279")
def compute_adjusted_notional_other(trades: pl.LazyFrame, reporting_date: date) -> pl.LazyFrame:
    """Adjusted notional for other-risks trades per CRR Art. 279b(1)(d).

    Art. 279b(1)(d): "the most appropriate method among the methods set out in
    points (a), (b) and (c), depending on the nature and characteristics of the
    underlying instrument". With no characterisation of the underlying beyond the
    trade's own columns, the engine takes:

    - method (c) — ``|market_price × number_of_units|`` — when both are supplied;
    - otherwise the larger of method (c)'s notional limb (``|notional|``) and
      method (a)'s duration-scaled notional (``|notional| × SD(S, E)``), so the
      choice of method can never lower the add-on.

    Coalesce-safe overlay: only ``asset_class == "other"`` rows are written; any
    value an earlier branch put on another row is preserved.

    Args:
        trades: Trade-grain LazyFrame carrying ``asset_class``, ``notional``,
            ``start_date``, ``maturity_date`` and an ``adjusted_notional`` column
            from the earlier branches.
        reporting_date: Calculation date for the Art. 279b(1)(a) year fractions.

    Returns:
        ``trades`` with ``adjusted_notional`` populated for other-risks rows.

    References:
        CRR Art. 279b(1)(a), (c), (d).
    """
    trades = ensure_columns(trades, _OPTIONAL_TRADE_COLUMNS)
    years_to_start = (pl.col("start_date") - pl.lit(reporting_date)).dt.total_days() / 365.25
    years_to_maturity = (pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25
    s_floored = pl.max_horizontal(years_to_start, pl.lit(_START_FLOOR_YEARS))
    rate = _SUPERVISORY_DURATION_RATE
    supervisory_duration = ((-rate * s_floored).exp() - (-rate * years_to_maturity).exp()) / rate

    unit_priced = (pl.col("market_price") * pl.col("number_of_units")).abs()
    notional_based = pl.col("notional").abs() * pl.max_horizontal(pl.lit(1.0), supervisory_duration)
    other_adjusted = pl.coalesce(unit_priced, notional_based)

    return trades.with_columns(
        pl.when(pl.col("asset_class") == OTHER_RISK_CATEGORY)
        .then(other_adjusted)
        .otherwise(pl.col("adjusted_notional"))
        .alias("adjusted_notional")
    )


@cites("CRR Art. 280")
def compute_addon_other(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Other-risks category add-on per CRR Art. 280f.

    Hedging sets (Art. 277a(1)(f)): trades share a hedging set "only where their
    primary risk driver ... is identical" — keyed on ``underlying_reference``; a
    trade with no ``underlying_reference`` (including every CCR021 fallback trade,
    whose risk driver is unknown) is its own hedging set, so it offsets nothing.

        EffNot_j    = sum_i in j ( delta_i × d_i × MF_i )
        AddOn_j     = SF_Other × |EffNot_j|              (epsilon_j = 1)
        AddOn_Other = sum_j AddOn_j

    Args:
        trades: Trade-grain LazyFrame with ``netting_set_id``, ``trade_id``,
            ``asset_class``, ``supervisory_delta``, ``adjusted_notional`` and
            ``maturity_factor``.

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="other"``) with
        ``asset_class_addon: Float64``. Non-other rows are filtered out.

    References:
        CRR Art. 277a(1)(f); CRR Art. 280f(1)-(2) (SF_Other = 8%).
    """
    trades = ensure_columns(trades, _OPTIONAL_TRADE_COLUMNS)
    other = trades.filter(pl.col("asset_class") == OTHER_RISK_CATEGORY).with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("_effective_notional"),
        pl.coalesce(pl.col("underlying_reference"), pl.col("trade_id")).alias("_risk_driver"),
    )
    per_hedging_set = other.group_by(["netting_set_id", "asset_class", "_risk_driver"]).agg(
        pl.col("_effective_notional").sum().alias("_eff_not")
    )
    return (
        per_hedging_set.with_columns((_SF_OTHER * pl.col("_eff_not").abs()).alias("_addon_hs"))
        .group_by(["netting_set_id", "asset_class"])
        .agg(pl.col("_addon_hs").sum().alias("asset_class_addon"))
        .select(["netting_set_id", "asset_class", "asset_class_addon"])
    )
