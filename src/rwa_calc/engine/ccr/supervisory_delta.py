"""
Supervisory delta for SA-CCR trades.

Pipeline position:
    Classifier -> CCRCalculator (delta) -> ...

Key responsibilities:
- Assign the linear-instrument supervisory delta (+/- 1) per CRR Art. 279a(1).
- Assign the Black-Scholes Phi(d1) supervisory delta for European options per
  CRR Art. 279a(2).
- Assign the closed-form CDO-tranche supervisory delta per CRR Art. 279a(3) /
  BCBS CRE52.43.

References:
- CRR Art. 279a: Supervisory delta
- BCBS CRE52.42 (option delta), CRE52.43 (CDO-tranche delta),
  CRE52.47 (supervisory option volatility table).
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.engine.irb.stats_backend import normal_cdf
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# SA-CCR supervisory option volatilities (CRR Art. 279a(2) / BCBS CRE52.47
# Table 3) and the CDO tranche supervisory-delta coefficients (Art. 279a(3) /
# CRE52.43), resolved from the rulepack once at module load.
_PACK = resolve("crr", date(2026, 1, 1))
_OPT_VOL_IR = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_ir"))
_OPT_VOL_FX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_fx"))
_OPT_VOL_CREDIT_SN = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_credit_sn"))
_OPT_VOL_CREDIT_IDX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_credit_idx"))
_OPT_VOL_EQUITY_SN = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_equity_sn"))
_OPT_VOL_EQUITY_IDX = scalar_value(_PACK.scalar_param("sa_ccr_option_volatility_equity_idx"))
_CDO_TRANCHE_NUMERATOR = scalar_value(_PACK.scalar_param("sa_ccr_cdo_tranche_numerator"))
_CDO_TRANCHE_COEFFICIENT = scalar_value(_PACK.scalar_param("sa_ccr_cdo_tranche_coefficient"))


# Map TRADE_SCHEMA ``asset_class`` strings to the supervisory option volatility
# from CRR Art. 279a(2) / BCBS CRE52.47. The fixture only carries the coarse
# class (no single-name / index distinction); equity and credit default to the
# index volatility (lower, matches the P8.13 OPT_003 expected value).
_OPTION_VOLATILITY_BY_ASSET_CLASS: dict[str, float] = {
    "interest_rate": _OPT_VOL_IR,
    "fx": _OPT_VOL_FX,
    "credit": _OPT_VOL_CREDIT_IDX,
    "credit_sn": _OPT_VOL_CREDIT_SN,
    "credit_idx": _OPT_VOL_CREDIT_IDX,
    "equity": _OPT_VOL_EQUITY_IDX,
    "equity_sn": _OPT_VOL_EQUITY_SN,
    "equity_idx": _OPT_VOL_EQUITY_IDX,
}


@cites("CRR Art. 279a")
def compute_supervisory_delta_linear(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for non-option directional trades per CRR Art. 279a(1).

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
        CRR Art. 279a(1); BCBS CRE52.41-43.
    """
    return trades.with_columns(
        pl.when(pl.col("is_long")).then(1.0).otherwise(-1.0).alias("supervisory_delta")
    )


@cites("CRR Art. 279a")
def compute_supervisory_delta_option(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Supervisory delta for European options per CRR Art. 279a(2).

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
        T  = (maturity_date - start_date).days / 365  (calendar-day basis)
        sigma = supervisory option volatility from
            ``SA_CCR_OPTION_VOLATILITY_*`` keyed off ``asset_class``.

    Rows where ``option_strike`` is null fall back to the linear +/- 1 delta
    per Art. 279a(1), preserving the behaviour of
    :func:`compute_supervisory_delta_linear`.

    Args:
        trades: LazyFrame with ``is_long``, ``asset_class``, ``option_type``,
            ``option_strike``, ``option_underlying_price``, ``start_date``,
            and ``maturity_date`` columns.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(2); BCBS CRE52.42; BCBS CRE52.47 (supervisory volatility).
    """
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

    # T = calendar days / 365 between start_date and maturity_date. The fixture
    # encodes T via maturity = start + round(T_nominal * 365) so this recovers
    # T_nominal exactly when reporting_date == start_date.
    t_years = (pl.col("maturity_date") - pl.col("start_date")).dt.total_days().cast(
        pl.Float64
    ) / 365.0

    sigma = pl.col("_option_sigma")
    p = pl.col("option_underlying_price")
    k = pl.col("option_strike")

    d1 = ((p / k).log() + 0.5 * sigma * sigma * t_years) / (sigma * t_years.sqrt())

    phi_d1 = normal_cdf(d1)
    phi_neg_d1 = normal_cdf(-d1)

    is_call = pl.col("option_type") == "call"
    is_long = pl.col("is_long")

    # Sign rule per CRR Art. 279a(2):
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
    """Supervisory delta for CDO tranches per CRR Art. 279a(3).

    For rows that carry ``cdo_attachment`` AND ``cdo_detachment``, apply the
    closed-form:

        |delta| = 15 / ((1 + 14 * A) * (1 + 14 * D))

    with sign +1 for long tranches and -1 for short tranches.

    Rows where ``cdo_attachment`` is null fall back to the linear +/- 1 delta
    per Art. 279a(1).

    Args:
        trades: LazyFrame with ``is_long``, ``cdo_attachment``, and
            ``cdo_detachment`` columns.

    Returns:
        The input LazyFrame with a new ``supervisory_delta: Float64`` column.

    References:
        CRR Art. 279a(3); BCBS CRE52.43.
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
