"""
Supervisory delta for SA-CCR trades.

Pipeline position:
    Classifier -> CCRCalculator (delta) -> ...

Key responsibilities:
- Assign the linear-instrument supervisory delta (+/- 1) per CCR (CRR) Part
  Art. 279a(1)(c), with long / short as defined in Art. 279a(2).
- Assign the Black-Scholes Phi(d1) supervisory delta for European options per
  Art. 279a(1)(a), with T the time from the reporting (calculation) date to the
  option's expiry.
- Assign the closed-form CDO-tranche supervisory delta per Art. 279a(1)(b) /
  BCBS CRE52.43.

References:
- PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 279a: Supervisory
  delta (unchanged by PS1/26; the same text applies to both regimes).
- BCBS CRE52.42 (option delta), CRE52.43 (CDO-tranche delta),
  CRE52.47 (supervisory option volatility table).
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import TRADE_SCHEMA
from rwa_calc.engine.irb.stats_backend import normal_cdf
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# SA-CCR supervisory option volatilities (Art. 279a(1)(a) Table 1 / BCBS
# CRE52.47) and the CDO tranche supervisory-delta coefficients (Art. 279a(1)(b)
# / CRE52.43), resolved from the rulepack once at module load.
_PACK = resolve("crr", date(2026, 1, 1))
_OPT_VOL_IR = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_ir"))
_OPT_VOL_FX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_fx"))
_OPT_VOL_CREDIT_SN = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_credit_sn"))
_OPT_VOL_CREDIT_IDX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_credit_idx"))
_OPT_VOL_EQUITY_SN = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_equity_sn"))
_OPT_VOL_EQUITY_IDX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_equity_idx"))
_OPT_VOL_COMMODITY_ELECTRICITY = scalar_value(
    _PACK.scalar_param("sa_ccr_option_volatility_commodity_electricity")
)
_OPT_VOL_COMMODITY_OTHER = scalar_value(
    _PACK.scalar_param("sa_ccr_option_volatility_commodity_other")
)
_OPT_VOL_OTHER = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_other"))
_CDO_TRANCHE_NUMERATOR = scalar_value(_PACK.scalar_param("sa_ccr_cdo_tranche_numerator"))
_CDO_TRANCHE_COEFFICIENT = scalar_value(_PACK.scalar_param("sa_ccr_cdo_tranche_coefficient"))


# Map TRADE_SCHEMA ``asset_class`` strings to the supervisory option volatility
# from Art. 279a(1)(a) Table 1 / BCBS CRE52.47. The fixture only carries the coarse
# class (no single-name / index distinction); equity and credit default to the
# index volatility (lower, matches the P8.13 OPT_003 expected value). Commodity
# is not keyed here: its volatility depends on ``commodity_type`` (electricity vs
# every other commodity) and is selected in compute_supervisory_delta_option.
_OPTION_VOLATILITY_BY_ASSET_CLASS: dict[str, float] = {
    "interest_rate": _OPT_VOL_IR,
    "fx": _OPT_VOL_FX,
    "credit": _OPT_VOL_CREDIT_IDX,
    "credit_sn": _OPT_VOL_CREDIT_SN,
    "credit_idx": _OPT_VOL_CREDIT_IDX,
    "equity": _OPT_VOL_EQUITY_IDX,
    "equity_sn": _OPT_VOL_EQUITY_SN,
    "equity_idx": _OPT_VOL_EQUITY_IDX,
    "other": _OPT_VOL_OTHER,
}

# Optional TRADE_SCHEMA column the commodity volatility reads; minimal unit-test
# frames may omit it, so it is injected as a typed null.
_COMMODITY_TYPE_COLUMN = {"commodity_type": TRADE_SCHEMA["commodity_type"]}


@cites("CRR Art. 279a")
def compute_supervisory_delta_linear(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for non-option directional trades per Art. 279a(1)(c).

    delta = +1 for long positions in the primary risk driver
    delta = -1 for short positions in the primary risk driver

    The European-option Black-Scholes Phi(d1) branch (rows where
    ``option_strike`` is not null) and the CDO-tranche formula are handled by
    :func:`compute_supervisory_delta_option` and
    :func:`compute_supervisory_delta_cdo_tranche` respectively.

    Args:
        trades: LazyFrame containing an ``is_long`` Boolean column.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(1)(c) and (2); BCBS CRE52.41-43.
    """
    return trades.with_columns(
        pl.when(pl.col("is_long")).then(1.0).otherwise(-1.0).alias("supervisory_delta")
    )


@cites("CRR Art. 279a")
def compute_supervisory_delta_option(trades: pl.LazyFrame, reporting_date: date) -> pl.LazyFrame:
    """Supervisory delta for European options per Art. 279a(1)(a).

    For rows that carry ``option_strike`` AND ``option_underlying_price``,
    apply the Black-Scholes Phi(d1) formula:

        d1 = (ln(P/K) + 0.5 * sigma^2 * T) / (sigma * sqrt(T))

        long  call:  delta = +Phi(d1)
        short call:  delta = -Phi(d1)
        long  put:   delta = -Phi(-d1)
        short put:   delta = +Phi(-d1)

    where:
        P  = ``option_underlying_price``
        K  = ``option_strike``
        T  = (maturity_date - reporting_date).days / 365, floored at 0.
            Art. 279a(1)(a): "T = the period between the expiry date of the
            option (Texp) and the calculation date". It is the option's
            REMAINING life, not its original tenor, so a seasoned option (start
            before the reporting date) or a forward-start one (start after it)
            takes the delta of a fresh option with the same expiry.
            ``maturity_date`` stands in for Texp: right for a European option
            whose expiry is its maturity; not for an option on a derivative
            whose expiry precedes the underlying's end (a swaption), for which
            TRADE_SCHEMA holds no exercise date.
            The basis is calendar days / 365; the article says "expressed in
            years using business days" (a recorded residual, shared with the
            Art. 279b S / E measures, which are calendar-based too).
        sigma = supervisory option volatility from
            ``sa_ccr_option_volatility_*`` keyed off ``asset_class`` — for a
            commodity option, off ``commodity_type`` instead (CCR (CRR) Part
            Art. 279a(1)(a) Table 1: "Commodity | Electricity | 150%", "Other
            commodities (excluding electricity) | 70%"; "Others | All | 150%").

    At or past expiry (T = 0 after the floor) the formula divides by zero —
    d1 = ln(P/K) / 0, which is 0 / 0 (NaN) at the money and +/-inf otherwise —
    so the delta takes its limit as T -> 0+:
    Phi(d1) -> 1 where P > K, 0 where P < K and Phi(0) = 0.5 where P = K, with
    Phi(-d1) = 1 - Phi(d1) — never NaN. The sign rule above applies as usual, so
    an expired in-the-money option keeps |delta| = 1 and an out-of-the-money one
    takes 0.

    Rows where ``option_strike`` is null fall back to the linear +/- 1 delta
    per Art. 279a(1)(c), preserving the behaviour of
    :func:`compute_supervisory_delta_linear`.

    Args:
        trades: LazyFrame with ``is_long``, ``asset_class``, ``option_type``,
            ``option_strike``, ``option_underlying_price`` and
            ``maturity_date`` columns (``commodity_type`` optional).
        reporting_date: The calculation date T is measured from.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(1)(a); BCBS CRE52.42; BCBS CRE52.47 (supervisory volatility).
    """
    trades = ensure_columns(trades, _COMMODITY_TYPE_COLUMN)
    # Asset-class -> sigma lookup as a small in-memory frame for join.
    sigma_lookup = pl.LazyFrame(
        {
            "asset_class": list(_OPTION_VOLATILITY_BY_ASSET_CLASS.keys()),
            "_option_sigma": list(_OPTION_VOLATILITY_BY_ASSET_CLASS.values()),
        },
        schema={"asset_class": pl.Utf8, "_option_sigma": pl.Float64},
    )

    is_option = (
        pl.col("option_strike").is_not_null() & pl.col("option_underlying_price").is_not_null()
    )

    t_years = _years_to_expiry(reporting_date)

    # Commodity sigma by commodity_type (Art. 279a(1)(a) Table 1). Before the
    # skeptic review of CC-06 commodity had no entry, so every commodity option
    # (including a CCR022 fallback trade) carried a null delta and no add-on.
    is_electricity = (
        pl.col("commodity_type").cast(pl.String).str.strip_chars().str.to_uppercase()
        == "ELECTRICITY"
    )
    sigma = (
        pl.when(pl.col("asset_class") == "commodity")
        .then(
            pl.when(is_electricity)
            .then(pl.lit(_OPT_VOL_COMMODITY_ELECTRICITY))
            .otherwise(pl.lit(_OPT_VOL_COMMODITY_OTHER))
        )
        .otherwise(pl.col("_option_sigma"))
    )
    p = pl.col("option_underlying_price")
    k = pl.col("option_strike")
    log_moneyness = (p / k).log()

    d1 = (log_moneyness + 0.5 * sigma * sigma * t_years) / (sigma * t_years.sqrt())

    # T = 0 (at or past expiry): the limit of Phi(d1) as T -> 0+ (docstring).
    # A null T (no maturity_date) falls through both branches to a null delta.
    phi_d1_at_expiry = (
        pl.when(log_moneyness > 0.0).then(1.0).when(log_moneyness < 0.0).then(0.0).otherwise(0.5)
    )
    phi_d1 = pl.when(t_years > 0.0).then(normal_cdf(d1)).when(t_years == 0.0).then(phi_d1_at_expiry)
    phi_neg_d1 = (
        pl.when(t_years > 0.0)
        .then(normal_cdf(-d1))
        .when(t_years == 0.0)
        .then(1.0 - phi_d1_at_expiry)
    )

    is_call = pl.col("option_type") == "call"
    is_long = pl.col("is_long")

    # Sign rule per Art. 279a(1)(a) (sign x type):
    #   long  call -> +Phi(d1)
    #   short call -> -Phi(d1)
    #   long  put  -> -Phi(-d1)
    #   short put  -> +Phi(-d1)
    option_delta = (
        pl.when(is_call & is_long)
        .then(phi_d1)
        .when(is_call & ~is_long)
        .then(-phi_d1)
        .when(~is_call & is_long)
        .then(-phi_neg_d1)
        .otherwise(phi_neg_d1)
    )

    linear_delta = pl.when(is_long).then(1.0).otherwise(-1.0)

    return (
        trades.join(sigma_lookup, on="asset_class", how="left")
        .with_columns(
            pl.when(is_option)
            .then(option_delta)
            .otherwise(linear_delta)
            .cast(pl.Float64)
            .alias("supervisory_delta")
        )
        .drop("_option_sigma")
    )


@cites("CRR Art. 279a")
def compute_supervisory_delta_cdo_tranche(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for CDO tranches per Art. 279a(1)(b).

    For rows that carry ``cdo_attachment`` AND ``cdo_detachment``, apply the
    closed-form:

        |delta| = 15 / ((1 + 14 * A) * (1 + 14 * D))

    with sign +1 for long tranches and -1 for short tranches.

    Rows where ``cdo_attachment`` is null fall back to the linear +/- 1 delta
    per Art. 279a(1)(c).

    Args:
        trades: LazyFrame with ``is_long``, ``cdo_attachment``, and
            ``cdo_detachment`` columns.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(1)(b); BCBS CRE52.43.
    """
    is_cdo = pl.col("cdo_attachment").is_not_null() & pl.col("cdo_detachment").is_not_null()

    a = pl.col("cdo_attachment")
    d = pl.col("cdo_detachment")

    numerator = _CDO_TRANCHE_NUMERATOR
    coefficient = _CDO_TRANCHE_COEFFICIENT

    magnitude = numerator / ((1.0 + coefficient * a) * (1.0 + coefficient * d))

    cdo_delta = pl.when(pl.col("is_long")).then(magnitude).otherwise(-magnitude)
    linear_delta = pl.when(pl.col("is_long")).then(1.0).otherwise(-1.0)

    return trades.with_columns(
        pl.when(is_cdo)
        .then(cdo_delta)
        .otherwise(linear_delta)
        .cast(pl.Float64)
        .alias("supervisory_delta")
    )


# =============================================================================
# Private helpers
# =============================================================================


def _years_to_expiry(reporting_date: date) -> pl.Expr:
    """Art. 279a(1)(a) T: reporting date to ``maturity_date`` (Texp), floored at 0.

    Calendar days / 365 — the single place the option-delta day-count basis is
    set, so moving it to the article's business-day basis is a one-line change.
    """
    days_to_expiry = (pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days()
    return (days_to_expiry.cast(pl.Float64) / 365.0).clip(lower_bound=0.0)
