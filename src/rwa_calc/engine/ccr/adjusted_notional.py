"""
Per-trade adjusted notional for SA-CCR (interest-rate, FX, and credit asset classes).

Pipeline position:
    Classifier -> CCRCalculator (adjusted notional) -> ...

Key responsibilities:
- IR (``compute_adjusted_notional_ir``): trade notional scaled by the supervisory
  duration factor ``SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05`` where
  ``S`` is the years-to-start floored at 10 business days (= 10/250 = 0.04y)
  and ``E`` is the years-to-maturity. Per CRR Art. 279b(1)(a).
- FX (``compute_adjusted_notional_fx``): both legs converted to the reporting
  currency (``CalculationConfig.base_currency``) at the prevailing spot rate;
  when one leg already equals the reporting currency, the non-reporting leg's
  converted notional is taken (Art. 279b(1)(b)(i)); when both legs differ from
  the reporting currency, the larger of the two converted notionals is taken
  (Art. 279b(1)(b)(ii)). FX rates source: ``FX_RATES_SCHEMA`` rows joined on
  ``currency_to == base_currency``. Missing rate joins produce a null
  ``adjusted_notional`` for that row; the orchestrator surfaces a
  ``CalculationError`` at the pipeline-adapter boundary.
- Credit (``compute_adjusted_notional_credit``): same supervisory-duration
  kernel as IR — Art. 279b(1)(a) covers both asset classes. Gated on
  ``asset_class == "credit"`` and coalesce-safe with the IR / FX branches.

References:
- CRR Art. 279b(1)(a): Adjusted notional amount (IR and credit derivatives)
- CRR Art. 279b(1)(b)(i)/(ii): Adjusted notional amount (FX)
- BCBS CRE52.40: 250-business-day year convention for the start-date floor
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.data.tables.sa_ccr_factors import (
    SA_CCR_BUSINESS_DAYS_PER_YEAR,
    SA_CCR_START_FLOOR_YEARS,
    SA_CCR_SUPERVISORY_DURATION_RATE,
)

logger = logging.getLogger(__name__)


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
    rate = float(SA_CCR_SUPERVISORY_DURATION_RATE)
    s_floor = float(SA_CCR_START_FLOOR_YEARS)
    # SA_CCR_BUSINESS_DAYS_PER_YEAR is referenced as the basis of the derived
    # ``s_floor`` constant; touching it here keeps the import meaningful.
    _ = SA_CCR_BUSINESS_DAYS_PER_YEAR

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
    fx_rates: pl.LazyFrame,
) -> pl.LazyFrame:
    """SA-CCR adjusted notional for FX trades per CRR Art. 279b(1)(b).

    For ``asset_class == "fx"``:

    - If at least one leg is in the reporting (base) currency
      (Art. 279b(1)(b)(i)): adjusted_notional = the *other* leg's notional
      converted to the base currency at spot.
    - If both legs are in non-base currencies (Art. 279b(1)(b)(ii)):
      adjusted_notional = max(|notional_leg1|, |notional_leg2|) after each
      leg is converted to the base currency at spot.

    Direction lives on ``is_long`` / ``delta``; the adjusted-notional value
    itself is taken in absolute terms per the regulatory comparison rule.

    FX rates are sourced from ``FX_RATES_SCHEMA`` rows where
    ``currency_to == base_currency``; an identity row
    ``{currency_from: base_currency, rate: 1.0}`` is added so a leg already
    in the base currency converts trivially. Rows where a required rate is
    missing produce a null ``adjusted_notional`` — the orchestrator is
    responsible for surfacing the CCR data-quality error.

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``currency``, ``notional_leg2``, ``currency_leg2``.
        base_currency: ISO-4217 reporting currency (e.g. ``"GBP"``) — typically
            ``CalculationConfig.base_currency``.
        fx_rates: LazyFrame conforming to ``FX_RATES_SCHEMA`` with columns
            ``currency_from``, ``currency_to``, ``rate``.

    Returns:
        The input LazyFrame with a new ``adjusted_notional: Float64`` column
        populated for ``asset_class == "fx"`` rows only; null elsewhere.

    References:
        - CRR Art. 279b(1)(b)(i): one-leg-is-base case.
        - CRR Art. 279b(1)(b)(ii): both-legs-foreign max-of-converted case.
    """
    # Build the leg-currency -> base-currency lookup with an identity row so
    # legs already in the base currency convert at 1.0.
    fx_to_base = fx_rates.filter(pl.col("currency_to") == pl.lit(base_currency)).select(
        pl.col("currency_from"),
        pl.col("rate").alias("rate_to_base"),
    )
    identity = pl.LazyFrame(
        {"currency_from": [base_currency], "rate_to_base": [1.0]},
        schema={"currency_from": pl.String, "rate_to_base": pl.Float64},
    )
    rate_lookup = pl.concat([fx_to_base, identity], how="vertical_relaxed")

    # Join twice — once for each leg currency. Use left-joins so missing rates
    # propagate as nulls (the orchestrator emits the CCR error downstream).
    enriched = (
        trades.join(
            rate_lookup.rename({"rate_to_base": "_rate_leg1"}),
            left_on="currency",
            right_on="currency_from",
            how="left",
        )
        .join(
            rate_lookup.rename({"rate_to_base": "_rate_leg2"}),
            left_on="currency_leg2",
            right_on="currency_from",
            how="left",
        )
    )

    # Converted absolute notionals per leg.
    abs_leg1 = pl.col("notional").abs() * pl.col("_rate_leg1")
    abs_leg2 = pl.col("notional_leg2").abs() * pl.col("_rate_leg2")

    one_leg_is_base = (pl.col("currency") == pl.lit(base_currency)) | (
        pl.col("currency_leg2") == pl.lit(base_currency)
    )

    # Art. 279b(1)(b)(i): when one leg is the base currency, take the *other*
    # leg converted (which equals its absolute notional × spot). When leg1 is
    # the base, take abs_leg2; when leg2 is the base, take abs_leg1.
    one_leg_value = (
        pl.when(pl.col("currency") == pl.lit(base_currency)).then(abs_leg2).otherwise(abs_leg1)
    )

    # Art. 279b(1)(b)(ii): both legs foreign — take max of converted notionals.
    both_foreign_value = pl.max_horizontal(abs_leg1, abs_leg2)

    fx_adjusted = pl.when(one_leg_is_base).then(one_leg_value).otherwise(both_foreign_value)

    # Gate on asset_class == "fx"; preserve any existing adjusted_notional from
    # the IR branch via coalesce — callers may have run the IR branch first.
    out = enriched.with_columns(
        pl.when(pl.col("asset_class") == "fx")
        .then(fx_adjusted)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_fx_adjusted_notional")
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
    rate = float(SA_CCR_SUPERVISORY_DURATION_RATE)
    s_floor = float(SA_CCR_START_FLOOR_YEARS)
    # SA_CCR_BUSINESS_DAYS_PER_YEAR is the basis of the derived ``s_floor``
    # constant; touching it here keeps the import meaningful.
    _ = SA_CCR_BUSINESS_DAYS_PER_YEAR

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
        pl.when(pl.col("asset_class") == "credit")
        .then(d)
        .otherwise(pl.lit(None, dtype=pl.Float64))
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

        d = abs(market_price * number_of_units)

    Direction lives on ``is_long`` / ``supervisory_delta``; the adjusted-notional
    value itself is taken in absolute terms per the regulatory rule. Null
    ``market_price`` or null ``number_of_units`` propagate as null
    ``adjusted_notional`` — the orchestrator surfaces the CCR data-quality
    error at the pipeline-adapter boundary.

    When the input frame already carries an ``adjusted_notional`` column from a
    prior IR / FX branch, this function coalesces — non-null upstream values
    are preserved and the equity result only overlays where the upstream value
    is null (equity rows).

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``market_price`` and ``number_of_units``.

    Returns:
        The input LazyFrame with an ``adjusted_notional: Float64`` column
        populated for ``asset_class == "equity"`` rows; existing non-null
        values from upstream branches are preserved.

    References:
        - CRR Art. 279b(1)(c): equity adjusted notional d = market_price × units.
    """
    equity_adjusted = (pl.col("market_price") * pl.col("number_of_units")).abs()

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
