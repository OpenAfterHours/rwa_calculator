"""
Per-trade adjusted notional for SA-CCR (interest-rate, FX, and credit asset classes).

Pipeline position:
    Classifier -> CCRCalculator (adjusted notional) -> ...

Key responsibilities:
- IR (``compute_adjusted_notional_ir``): trade notional scaled by the supervisory
  duration factor ``SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05`` where
  ``S`` is the years-to-start floored at 10 business days (= 10/250 = 0.04y)
  and ``E`` is the years-to-maturity. Per CRR Art. 279b(1)(a).
- FX (``compute_adjusted_notional_fx``): with two legs, the non-reporting
  leg's notional when the other leg is in the reporting currency
  (``CalculationConfig.base_currency``) (Art. 279b(1)(b)(ii)), else the larger
  of the two legs' notionals (Art. 279b(1)(b)(iii)) — each converted at spot
  (Art. 279b(3)) from ``FX_RATES_SCHEMA`` rows with
  ``currency_to == base_currency``. A trade with no second-leg notional takes
  its first leg's notional: the contract notional of a transaction of one
  payment leg (Art. 279b(1)(b)(i)) when no second leg is stated (reported
  CCR036); with the stated second leg in the reporting currency, rule (ii)'s
  own value — "the notional amount of the other payment leg", the first leg at
  spot — so the missing notional is never needed; otherwise an estimate of the
  second leg's notional (reported CCR037). A leg with no rate (or no table at
  all) enters unconverted and the larger of the legs is taken (reported CCR026
  by ``engine/ccr/reporting_currency.py`` unless the run sets
  ``apply_fx_conversion=False``, which reports no currency), so a missing input
  never leaves the trade's adjusted notional null. Each trade whose value is an estimate, or
  that states no pair, is flagged ``fx_own_hedging_set`` and kept out of every
  pair's hedging-set netting (P1.406).
- Credit (``compute_adjusted_notional_credit``): same supervisory-duration
  kernel as IR — Art. 279b(1)(a) covers both asset classes. Gated on
  ``asset_class == "credit"`` and coalesce-safe with the IR / FX branches.
- Equity / commodity (``compute_adjusted_notional_equity`` /
  ``_commodity``): market price x number of units, or — for a trade with no
  price x units, read as contractually expressed as a notional amount — the
  absolute notional (Art. 279b(1)(c); reported CCR035 by the input gate, or
  CCR038 when that notional is 0 / null and the trade is priced at zero). Unlike
  Art. 279b(1)(a) and the other-risks notional (``|notional| x max(1, SD)``,
  ``engine/ccr/risk_categories.py``) the limb carries no supervisory duration.

References:
- CRR Art. 279b(1)(a): Adjusted notional amount (IR and credit derivatives)
- CRR Art. 279b(1)(b)(i)/(ii)/(iii), 279b(3): Adjusted notional amount (FX)
- CRR Art. 279b(1)(c): Adjusted notional amount (equity and commodity)
- BCBS CRE52.40: 250-business-day year convention for the start-date floor
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import TRADE_SCHEMA
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# SA-CCR supervisory-duration parameters (CRR Art. 279b(1)(a)) resolved from the
# rulepack once at module load. The start-date floor is pre-computed
# (10 BD / 250 BD-year = 0.04 year fraction); the 250-BD-year basis lives with
# the maturity-factor module.
_PACK = resolve("crr", date(2026, 1, 1))
_SUPERVISORY_DURATION_RATE = scalar_value(_PACK.scalar_param("sa_ccr_supervisory_duration_rate"))
_START_FLOOR_YEARS = scalar_value(_PACK.scalar_param("sa_ccr_start_floor_years"))

#: Trade-grain Boolean written by :func:`compute_adjusted_notional_fx`: True for an
#: FX trade that must not net in a currency pair's hedging set — a leg entered
#: unconverted (no spot rate to the reporting currency), or no second-leg notional
#: (a stated second leg whose notional the rule needs but is unknown, or no second
#: leg, so no pair). A stated second leg in the reporting currency with no
#: notional is not flagged: Art. 279b(1)(b)(ii) needs only the first leg.
#: ``assign_hedging_set`` gives such a trade its own hedging set, so it offsets
#: nothing (P1.406).
FX_OWN_HEDGING_SET = "fx_own_hedging_set"

#: The optional FX second-leg columns the FX branch reads: injected as typed nulls
#: when a frame omits them (an in-memory ``run_with_data`` book with no FX trades),
#: since the branch runs on every call.
_FX_LEG2_COLUMNS = {name: TRADE_SCHEMA[name] for name in ("notional_leg2", "currency_leg2")}


# Watchfire's bundled CRR index does not yet contain Art. 279b; collapse the
# ``@cites`` to the parent Art. 279 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 279")
def compute_adjusted_notional_ir(
    trades: pl.LazyFrame,
    reporting_date: date,
) -> pl.LazyFrame:
    """SA-CCR adjusted notional for interest-rate trades per CRR Art. 279b(1)(a).

    For ``asset_class == "interest_rate"``:

        d = notional * SD(S, E)
        SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05

    where ``S`` is the years-to-start floored at 10 business days
    (10/250 = 0.04y) and ``E`` is the years-to-maturity. FX / credit / equity
    / commodity branches return null (deferred to subsequent batches).

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``start_date``, ``maturity_date``.
        reporting_date: As-of date for the calculation; used to compute the
            year fractions ``S`` (start) and ``E`` (maturity).

    Returns:
        The input LazyFrame with a new ``adjusted_notional: Float64`` column;
        null for non-IR rows.

    References:
        - CRR Art. 279b(1)(a)
        - BCBS CRE52.40 (footnote: 250-business-day year for the start floor)
    """
    rate = _SUPERVISORY_DURATION_RATE
    s_floor = _START_FLOOR_YEARS

    # Calendar-day -> year fraction. 365.25 is the standard SA-CCR convention
    # for year fractions; the 250-business-day year applies only to the
    # 10-BD start-date floor, which is pre-computed into ``s_floor`` above.
    years_to_start = (pl.col("start_date") - pl.lit(reporting_date)).dt.total_days() / 365.25
    years_to_maturity = (pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25

    # S floored at 10 BD = 10/250 = 0.04y per Art. 279b(1)(a).
    s_floored = pl.max_horizontal(years_to_start, pl.lit(s_floor))

    # SD(S, E) = (exp(-rate*S) - exp(-rate*E)) / rate
    sd = ((-rate * s_floored).exp() - (-rate * years_to_maturity).exp()) / rate
    d = pl.col("notional") * sd

    return trades.with_columns(
        pl.when(pl.col("asset_class") == "interest_rate")
        .then(d)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("adjusted_notional")
    )


@cites("CRR Art. 279")
def compute_adjusted_notional_fx(
    trades: pl.LazyFrame,
    base_currency: str,
    fx_rates: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """SA-CCR adjusted notional for FX trades per CRR Art. 279b(1)(b) and (3).

    For ``asset_class == "fx"``, with every leg converted to the base
    (reporting) currency at spot (Art. 279b(3)):

    - Two legs, one in the base currency (Art. 279b(1)(b)(ii)): the *other*
      leg's notional.
    - Two legs, both in non-base currencies (Art. 279b(1)(b)(iii)): the larger
      of the two legs' notionals.
    - No second-leg notional (``notional_leg2`` null): the first leg's
      notional ``|notional|`` at spot. With ``currency_leg2`` null too the trade
      is read as a transaction of one payment leg, whose adjusted notional is
      the contract notional (Art. 279b(1)(b)(i); reported CCR036 WARNING by the
      input gate, since the engine cannot see whether the contract really has
      one leg). With ``currency_leg2`` stated and equal to the reporting
      currency (the first leg not), rule (ii) takes "the notional amount of the
      other payment leg" — the first leg, converted at spot — so the value is
      the rule's, the missing notional is never needed and the trade nets in
      its pair like a complete one (nothing reported). With any other stated
      ``currency_leg2`` the rule needs the second leg's notional, which is
      unknown, so the first leg's notional — the value the contract exchanges
      for it — is an estimate (reported CCR037 ERROR).

    A leg whose currency is null or has no rate to the base currency enters
    **unconverted** (the CCR026 pass-through every other CCR amount takes), and
    the adjusted notional is then the larger of the two legs' notionals, each
    converted where it has a rate. With no spot rate the leg's reporting-currency
    value is unknown: its unconverted notional and the other leg's notional (the
    value the contract exchanges for it) are the two estimates the trade
    carries, and taking the larger means a missing rate can never price this
    trade's adjusted notional below either estimate (P1.406).

    Each such bound is the trade's alone: netted against a pair's other trades,
    an estimate can lower the hedging set's add-on, and a trade that states no
    second currency has no pair to share (Art. 277a(1)(b): "only where their
    primary risk driver ... is based on the same currency pair"). So every FX
    trade except one carrying its rule value — a complete two-leg trade with a
    spot rate for each leg, or a first leg with a rate against a stated
    reporting-currency second leg (ii) — is flagged ``fx_own_hedging_set`` and
    ``engine/ccr/hedging_sets.py::assign_hedging_set`` makes it its own hedging
    set; isolation can only raise the add-on (sum |d_i| >= |sum d_i|). Before
    P1.406 a leg with no rate, or a missing second leg with the first leg in
    the reporting currency, was null: the trade added nothing to Art. 278(1)'s
    FX add-on (with both legs foreign only the other leg counted). Only a first
    leg with no rate was reported (CCR026 read ``currency`` alone); a second
    leg with no rate, or a missing second leg, was not.

    Direction lives on ``is_long`` / ``delta``; the adjusted-notional value
    itself is taken in absolute terms per the regulatory comparison rule.

    FX rates are sourced from ``FX_RATES_SCHEMA`` rows where
    ``currency_to == base_currency``; an identity row
    ``{currency_from: base_currency, rate: 1.0}`` is added so a leg already
    in the base currency converts trivially. ``fx_rates`` None (the run has no
    table) leaves only that identity row.

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``currency`` and optionally ``notional_leg2`` /
            ``currency_leg2`` (absent reads as null: no second leg).
        base_currency: ISO-4217 reporting currency (e.g. ``"GBP"``) — typically
            ``CalculationConfig.base_currency``.
        fx_rates: LazyFrame conforming to ``FX_RATES_SCHEMA`` with columns
            ``currency_from``, ``currency_to``, ``rate``, or None.

    Returns:
        The input LazyFrame with a new ``adjusted_notional: Float64`` column
        populated for ``asset_class == "fx"`` rows only (null elsewhere), and
        ``fx_own_hedging_set: Boolean`` — True for an FX trade with a present
        leg that has no rate, or with no second-leg notional unless its stated
        second leg is the reporting currency (rule (ii) needs only the first
        leg), False on every other row.

    References:
        - CRR Art. 279b(1)(b)(i): one payment leg.
        - CRR Art. 279b(1)(b)(ii): one leg in the reporting currency.
        - CRR Art. 279b(1)(b)(iii): both legs foreign, largest converted leg.
        - CRR Art. 279b(3): conversion at the prevailing spot rate.
        - CRR Art. 277a(1)(b): FX hedging set = the same currency pair.
    """
    rate_lookup = _fx_rate_lookup(base_currency, fx_rates)
    trades = ensure_columns(trades, _FX_LEG2_COLUMNS)

    # Join twice — once for each leg currency. Left joins: a missing rate stays
    # null on ``_rate_leg*`` and is resolved explicitly below.
    enriched = trades.join(
        rate_lookup.rename({"rate_to_base": "_rate_leg1"}),
        left_on="currency",
        right_on="currency_from",
        how="left",
    ).join(
        rate_lookup.rename({"rate_to_base": "_rate_leg2"}),
        left_on="currency_leg2",
        right_on="currency_from",
        how="left",
    )

    # Absolute notional per leg in the base currency; a leg with no rate is
    # taken unconverted (rate 1.0).
    abs_leg1 = pl.col("notional").abs() * pl.coalesce(pl.col("_rate_leg1"), pl.lit(1.0))
    abs_leg2 = pl.col("notional_leg2").abs() * pl.coalesce(pl.col("_rate_leg2"), pl.lit(1.0))

    no_leg2_notional = pl.col("notional_leg2").is_null()
    # A present leg with no rate (a null currency included) enters unconverted.
    leg_unconverted = pl.col("_rate_leg1").is_null() | (
        ~no_leg2_notional & pl.col("_rate_leg2").is_null()
    )
    # Art. 279b(1)(b)(ii) with the stated second leg in the reporting currency:
    # "the notional amount of the other payment leg" is the first leg's, so a
    # missing notional_leg2 is never needed and abs_leg1 is the rule value (a
    # first leg with no rate is still caught by leg_unconverted).
    leg1_is_base = pl.col("currency").eq_missing(pl.lit(base_currency))
    leg2_is_base = pl.col("currency_leg2").eq_missing(pl.lit(base_currency))
    leg2_notional_not_needed = leg2_is_base & ~leg1_is_base

    fx_adjusted = (
        # No second-leg notional -> the first leg's at spot: Art. 279b(1)(b)(i)'s
        # contract notional when no second leg is stated (CCR036); (ii)'s value
        # when the stated second leg is the reporting currency; else an estimate
        # (CCR037).
        pl.when(no_leg2_notional)
        .then(abs_leg1)
        # Art. 279b(1)(b)(ii): one leg in the reporting currency -> the other leg.
        .when(~leg_unconverted & (pl.col("currency") == pl.lit(base_currency)))
        .then(abs_leg2)
        .when(~leg_unconverted & (pl.col("currency_leg2") == pl.lit(base_currency)))
        .then(abs_leg1)
        # Art. 279b(1)(b)(iii): both legs foreign -> the larger converted leg;
        # also every two-leg trade with a leg that has no rate (see docstring).
        .otherwise(pl.max_horizontal(abs_leg1, abs_leg2))
    )

    # Gate on asset_class == "fx"; preserve any existing adjusted_notional from
    # the IR branch via coalesce — callers may have run the IR branch first.
    is_fx = pl.col("asset_class") == "fx"
    out = enriched.with_columns(
        pl.when(is_fx)
        .then(fx_adjusted)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_fx_adjusted_notional"),
        pl.when(is_fx)
        .then(leg_unconverted | (no_leg2_notional & ~leg2_notional_not_needed))
        .otherwise(pl.lit(False))
        .alias(FX_OWN_HEDGING_SET),
    )

    # If the input already has an adjusted_notional column (e.g. from the IR
    # branch), preserve non-null values and overlay FX where applicable.
    if "adjusted_notional" in trades.collect_schema().names():
        out = out.with_columns(
            pl.coalesce(pl.col("adjusted_notional"), pl.col("_fx_adjusted_notional")).alias(
                "adjusted_notional"
            )
        )
    else:
        out = out.rename({"_fx_adjusted_notional": "adjusted_notional"})

    return out.drop("_rate_leg1", "_rate_leg2", strict=False).drop(
        "_fx_adjusted_notional", strict=False
    )


@cites("CRR Art. 279")
def compute_adjusted_notional_credit(
    trades: pl.LazyFrame,
    reporting_date: date,
) -> pl.LazyFrame:
    """SA-CCR adjusted notional for credit derivatives per CRR Art. 279b(1)(a).

    For ``asset_class == "credit"``:

        d = notional * SD(S, E)
        SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05

    where ``S`` is the years-to-start floored at 10 business days
    (10/250 = 0.04y) and ``E`` is the years-to-maturity. The supervisory-
    duration kernel is shared with the interest-rate asset class — Art. 279b(1)(a)
    covers both. Coalesce-safe with the IR / FX branches when run in sequence:
    the credit branch only overlays rows where ``asset_class == "credit"``.

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``start_date``, ``maturity_date``.
        reporting_date: As-of date for the calculation; used to compute the
            year fractions ``S`` (start) and ``E`` (maturity).

    Returns:
        The input LazyFrame with a new (or coalesced) ``adjusted_notional: Float64``
        column. Non-credit rows preserve any existing value from a prior branch
        (IR / FX) or remain null.

    References:
        - CRR Art. 279b(1)(a)
        - BCBS CRE52.41-43 (supervisory duration shared with IR)
    """
    rate = _SUPERVISORY_DURATION_RATE
    s_floor = _START_FLOOR_YEARS

    # Calendar-day -> year fraction. 365.25 is the standard SA-CCR convention
    # for year fractions; the 250-business-day year applies only to the
    # 10-BD start-date floor, which is pre-computed into ``s_floor`` above.
    years_to_start = (pl.col("start_date") - pl.lit(reporting_date)).dt.total_days() / 365.25
    years_to_maturity = (pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25

    # S floored at 10 BD = 10/250 = 0.04y per Art. 279b(1)(a).
    s_floored = pl.max_horizontal(years_to_start, pl.lit(s_floor))

    # SD(S, E) = (exp(-rate*S) - exp(-rate*E)) / rate
    sd = ((-rate * s_floored).exp() - (-rate * years_to_maturity).exp()) / rate
    d = pl.col("notional") * sd

    credit_adjusted = (
        pl.when(pl.col("asset_class") == "credit").then(d).otherwise(pl.lit(None, dtype=pl.Float64))
    )

    # Preserve any existing adjusted_notional column from upstream IR / FX
    # branches via coalesce; otherwise emit a fresh column.
    if "adjusted_notional" in trades.collect_schema().names():
        return trades.with_columns(
            pl.coalesce(pl.col("adjusted_notional"), credit_adjusted).alias("adjusted_notional")
        )
    return trades.with_columns(credit_adjusted.alias("adjusted_notional"))


@cites("CRR Art. 279")
def compute_adjusted_notional_equity(trades: pl.LazyFrame) -> pl.LazyFrame:
    """SA-CCR adjusted notional for equity trades per CRR Art. 279b(1)(c).

    For ``asset_class == "equity"``:

        d = abs(market_price * number_of_units)     when both are supplied
        d = abs(notional)                           otherwise

    Art. 279b(1)(c): "where a transaction mapped to the equity risk category or
    commodity risk category is contractually expressed as a notional amount,
    institutions shall use the notional amount of the transaction". A trade
    with a null ``market_price`` or ``number_of_units`` is read as expressed as
    a notional amount (reported CCR035 by the input gate,
    ``contracts/ccr_input_checks.py``; CCR038 ERROR when that notional is 0 or
    null, so ``d`` is 0 / null and the trade adds nothing); before P1.406 the
    null product left the trade out of the equity add-on with no error. Market
    price x units stays first, so a trade carrying both limbs prices exactly as
    before. The notional is the rule's value, so the trade nets in its hedging
    set like any other: where it offsets another trade, pricing it lowers the
    add-on. It is the face value at any residual maturity — no supervisory
    duration, unlike Art. 279b(1)(a) and the other-risks ``|notional| x
    max(1, SD)`` (pinned at five years, where SD is about 4.38, by
    ``tests/acceptance/ccr/test_p1_406_incomplete_notional_inputs.py``).

    Direction lives on ``is_long`` / ``supervisory_delta``; the adjusted-notional
    value itself is taken in absolute terms per the regulatory rule.

    When the input frame already carries an ``adjusted_notional`` column from a
    prior IR / FX branch, this function coalesces — non-null upstream values
    are preserved and the equity result only overlays where the upstream value
    is null (equity rows).

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``market_price`` and ``number_of_units``.

    Returns:
        The input LazyFrame with an ``adjusted_notional: Float64`` column
        populated for ``asset_class == "equity"`` rows; existing non-null
        values from upstream branches are preserved.

    References:
        - CRR Art. 279b(1)(c): equity adjusted notional d = market_price × units,
          or the notional of a transaction expressed as a notional amount.
    """
    equity_adjusted = pl.coalesce(
        (pl.col("market_price") * pl.col("number_of_units")).abs(), pl.col("notional").abs()
    )

    out = trades.with_columns(
        pl.when(pl.col("asset_class") == "equity")
        .then(equity_adjusted)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_eq_adjusted_notional")
    )

    if "adjusted_notional" in trades.collect_schema().names():
        out = out.with_columns(
            pl.coalesce(pl.col("adjusted_notional"), pl.col("_eq_adjusted_notional")).alias(
                "adjusted_notional"
            )
        )
    else:
        out = out.rename({"_eq_adjusted_notional": "adjusted_notional"})

    return out.drop("_eq_adjusted_notional", strict=False)


@cites("CRR Art. 279")
def compute_adjusted_notional_commodity(trades: pl.LazyFrame) -> pl.LazyFrame:
    """SA-CCR adjusted notional for commodity trades per CRR Art. 279b(1)(c).

    For ``asset_class == "commodity"``:

        d = market_price × number_of_units          when both are supplied
        d = |notional|                              otherwise

    A trade with a null ``market_price`` or ``number_of_units`` is read as
    contractually expressed as a notional amount, whose notional Art. 279b(1)(c)
    uses instead (reported CCR035 by the input gate; CCR038 ERROR when that
    notional is 0 or null, so ``d`` is 0 / null and the trade adds nothing);
    before P1.406 the null product left the trade out of the commodity add-on
    with no error. Market price x units stays first, so a trade carrying both
    limbs prices exactly as before. The notional is the face value at any
    residual maturity: no supervisory duration (see the equity branch).

    ``market_price`` and ``notional`` reach this function already rebased to the
    reporting currency (Art. 279b(3), ``engine/ccr/reporting_currency.py``).
    Direction lives on ``is_long`` / ``delta`` — the adjusted-notional value
    itself is the unsigned product per Art. 279b(1)(c).

    Coalesce-safe overlay: when the input already carries an
    ``adjusted_notional`` column from a prior IR / FX / credit / equity branch,
    non-null values on non-commodity rows are preserved.

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``market_price`` and ``number_of_units``.

    Returns:
        The input LazyFrame with a (possibly overlaid) ``adjusted_notional:
        Float64`` column populated for ``asset_class == "commodity"`` rows
        only; null on non-commodity rows when no prior branch populated them.

    References:
        - CRR Art. 279b(1)(c)
        - BCBS CRE52.46-48
    """
    co_adjusted = pl.coalesce(
        pl.col("market_price") * pl.col("number_of_units"), pl.col("notional").abs()
    )

    out = trades.with_columns(
        pl.when(pl.col("asset_class") == "commodity")
        .then(co_adjusted)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_co_adjusted_notional")
    )

    if "adjusted_notional" in trades.collect_schema().names():
        out = out.with_columns(
            pl.coalesce(pl.col("adjusted_notional"), pl.col("_co_adjusted_notional")).alias(
                "adjusted_notional"
            )
        )
    else:
        out = out.rename({"_co_adjusted_notional": "adjusted_notional"})

    return out.drop("_co_adjusted_notional", strict=False)


def _fx_rate_lookup(base_currency: str, fx_rates: pl.LazyFrame | None) -> pl.LazyFrame:
    """Spot rates to ``base_currency`` keyed ``currency_from``, plus the identity row.

    Args:
        base_currency: The reporting currency.
        fx_rates: The run's ``FX_RATES_SCHEMA`` frame, or None (identity only).

    Returns:
        LazyFrame ``(currency_from, rate_to_base)``.
    """
    identity = pl.LazyFrame(
        {"currency_from": [base_currency], "rate_to_base": [1.0]},
        schema={"currency_from": pl.String, "rate_to_base": pl.Float64},
    )
    if fx_rates is None:
        return identity
    fx_to_base = fx_rates.filter(pl.col("currency_to") == pl.lit(base_currency)).select(
        pl.col("currency_from"),
        pl.col("rate").alias("rate_to_base"),
    )
    return pl.concat([fx_to_base, identity], how="vertical_relaxed")
