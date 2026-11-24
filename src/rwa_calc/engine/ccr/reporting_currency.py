"""
Reporting-currency rebasing of SA-CCR and SFT input amounts.

Pipeline position:
    HierarchyResolver (FXConverter rebases the lending book) -> ccr_sa_ccr /
    sft_fccm [this module rebases the CCR / SFT amounts the FXConverter never
    sees] -> Classifier

Key responsibilities:
- Build the spot-rate lookup to the reporting currency (an identity row for
  the reporting currency itself) from the run's ``fx_rates`` table.
- Multiply the money columns of a trade or collateral frame by the spot rate of
  the row's own ``currency`` (review CC-05). The ``currency`` column itself is
  left untouched: it keys the Art. 277a(1)(a) interest-rate hedging sets and the
  Art. 224 currency-mismatch haircut, both of which need the denomination.
- A row whose currency has no rate keeps its amounts unconverted — the
  FXConverter's own treatment of a missing rate — and is reported CCR026 from
  :func:`reporting_currency_findings`, which reads the same lookup.
- An FX trade's second payment leg (``currency_leg2``), which the Art. 279b(1)(b)
  branch converts itself, is reported CCR026 from :func:`fx_leg_currency_findings`
  when it has no rate: the branch then takes the leg unconverted and the larger
  of the two legs (``engine/ccr/adjusted_notional.py``; P1.406).
- Stamp a synthetic netting-set row's ``currency`` as the reporting currency
  once its amounts are in it (``original_currency`` keeps the denomination).

Before review CC-05 only the FX-category adjusted notional was converted: a JPY
10bn interest-rate swap reached the GBP totals as an exposure value of about
419m, and an SFT's E* stayed in the trade currency.

References:
- CCR (CRR) Part Art. 279b(3) (unchanged by PS1/26): "Institutions shall convert
  the adjusted notional amount of a transaction into their reporting currency at
  the prevailing spot exchange rate where the adjusted notional amount is
  calculated ... from a contractual notional amount or a market price of the
  number of units of the underlying instrument denominated in another currency."
- CCR (CRR) Part Art. 275 / 276(1)(d): CMV, VM and NICA are netted in one
  currency; CRR Art. 223(5): E* nets E against collateral in one currency.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import polars as pl

from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import TRADE_SCHEMA
from rwa_calc.engine.ccr.risk_categories import map_trade_risk_categories

logger = logging.getLogger(__name__)

#: The joined spot-rate column; dropped again before a frame leaves this module.
_RATE = "_rate_to_reporting"


def rebase_to_reporting_currency(
    frame: pl.LazyFrame,
    amount_columns: Iterable[str],
    rates: pl.LazyFrame | None,
    *,
    keep: pl.Expr | None = None,
) -> pl.LazyFrame:
    """Convert ``amount_columns`` of ``frame`` to the reporting currency.

    Each row's amounts are multiplied by the spot rate of its ``currency``
    (Art. 279b(3)). A row whose currency has no rate, or a null currency, keeps
    its amounts unconverted. ``rates is None`` (conversion disabled for the run)
    returns ``frame`` unchanged.

    Args:
        frame: Trade or collateral frame carrying ``currency`` and the amounts.
        amount_columns: The money columns to convert; absent ones are skipped.
        rates: :func:`reporting_currency_rates` output, or None.
        keep: Optional row predicate whose rows are left unconverted — the
            FX-category trades, whose adjusted notional converts both legs
            itself (Art. 279b(1)(b)).

    Returns:
        ``frame`` with the present amount columns rebased.
    """
    if rates is None:
        return frame
    present = set(frame.collect_schema().names())
    columns = [name for name in amount_columns if name in present]
    if not columns:
        return frame
    convert = pl.col(_RATE).is_not_null()
    if keep is not None:
        convert = convert & ~keep
    return (
        frame.join(
            rates, left_on=pl.col("currency").cast(pl.String), right_on="currency_from", how="left"
        )
        .with_columns(
            pl.when(convert).then(pl.col(name) * pl.col(_RATE)).otherwise(pl.col(name)).alias(name)
            for name in columns
        )
        .drop(_RATE)
    )


def reporting_currency_rates(
    fx_rates: pl.LazyFrame | None,
    base_currency: str,
) -> pl.LazyFrame:
    """Spot rates to ``base_currency``, keyed ``currency_from``, with an identity row.

    Args:
        fx_rates: The run's ``FX_RATES_SCHEMA`` frame, or None (no rates
            supplied: only the reporting currency itself converts).
        base_currency: The reporting currency (``CalculationConfig.base_currency``).

    Returns:
        LazyFrame ``(currency_from, _rate_to_reporting)``, one row per currency.
    """
    identity = pl.LazyFrame(
        {"currency_from": [base_currency], _RATE: [1.0]},
        schema={"currency_from": pl.String, _RATE: pl.Float64},
    )
    if fx_rates is None:
        return identity
    to_base = fx_rates.filter(
        (pl.col("currency_to") == base_currency) & (pl.col("currency_from") != base_currency)
    ).select(pl.col("currency_from").cast(pl.String), pl.col("rate").cast(pl.Float64).alias(_RATE))
    return pl.concat([identity, to_base], how="vertical").unique(
        subset="currency_from", keep="first", maintain_order=True
    )


def stamp_reporting_currency(
    rows: pl.LazyFrame,
    rates: pl.LazyFrame | None,
    base_currency: str,
) -> pl.LazyFrame:
    """Set a synthetic row's ``currency`` to the reporting currency once converted.

    The row's amounts are in the reporting currency exactly when its
    denomination (``original_currency``) has a rate; otherwise the row keeps
    its denomination, as the FXConverter leaves an unconvertible loan.

    Args:
        rows: Synthetic netting-set rows carrying ``original_currency``.
        rates: :func:`reporting_currency_rates` output, or None (no conversion).
        base_currency: The reporting currency.

    Returns:
        ``rows`` with ``currency`` restamped.
    """
    if rates is None:
        return rows
    convertible = rates.select(pl.col("currency_from"), pl.lit(True).alias("_convertible"))
    return (
        rows.join(
            convertible,
            left_on=pl.col("original_currency").cast(pl.String),
            right_on="currency_from",
            how="left",
        )
        .with_columns(
            pl.when(pl.col("_convertible").is_not_null())
            .then(pl.lit(base_currency))
            .otherwise(pl.col("original_currency"))
            .alias("currency")
        )
        .drop("_convertible")
    )


def reporting_currency_findings(
    frames: dict[str, pl.LazyFrame | None],
    rates: pl.LazyFrame | None,
) -> pl.LazyFrame | None:
    """Rows whose amounts :func:`rebase_to_reporting_currency` leaves unconverted.

    One row per (table, record) whose ``currency`` is null or has no (non-null)
    rate to the reporting currency, carrying ``table``, ``record_id``,
    ``netting_set_id`` and ``currency`` — decoded into CCR026 by
    ``contracts/ccr_collateral_checks.py``.

    Args:
        frames: The frames to check, keyed ``"<table name>|<record id column>"``
            (e.g. ``"ccr.trades|trade_id"``); None frames are skipped.
        rates: :func:`reporting_currency_rates` output, or None (conversion
            disabled for the run: nothing is reported).

    Returns:
        The findings plan, or None when there is nothing to check.
    """
    if rates is None:
        return None
    convertible = _convertible(rates)
    plans = []
    for key, frame in frames.items():
        if frame is None:
            continue
        table, _, id_column = key.partition("|")
        plans.append(
            frame.select(
                pl.lit(table).alias("table"),
                pl.col(id_column).cast(pl.String).alias("record_id"),
                pl.col("netting_set_id").cast(pl.String),
                pl.col("currency").cast(pl.String),
            )
            .join(convertible, left_on="currency", right_on="currency_from", how="left")
            .filter(pl.col("_convertible").is_null())
            .drop("_convertible")
        )
    if not plans:
        return None
    return pl.concat(plans, how="vertical").sort("table", "record_id", nulls_last=True)


def fx_leg_currency_findings(
    trades: pl.LazyFrame | None,
    rates: pl.LazyFrame | None,
) -> pl.LazyFrame | None:
    """FX trades whose second payment leg has no spot rate to the reporting currency.

    The Art. 279b(1)(b) branch (``compute_adjusted_notional_fx``) converts both
    legs itself; a ``currency_leg2`` that is null or has no rate enters it
    unconverted and the larger of the two legs is taken. One row per such trade
    — an ``asset_class`` that engine/ccr maps to ``"fx"`` (the same
    ``map_trade_risk_categories`` folding) with a second-leg notional
    (``notional_leg2`` not null: a trade without one is priced on its first leg,
    and reported CCR036 / CCR037 by the input gate,
    ``contracts/ccr_input_checks.py::ccr_fx_second_leg_findings``, where that
    leg's notional is needed) — carrying ``table``, ``record_id``,
    ``netting_set_id`` and the leg's ``currency``; decoded into CCR026 by
    ``contracts/ccr_collateral_checks.py::fx_leg_currency_errors``. The first
    leg is the trade's own ``currency`` and is reported by
    :func:`reporting_currency_findings`.

    Args:
        trades: The derivative trades the adapter prices, or None.
        rates: :func:`reporting_currency_rates` output, or None (conversion
            disabled for the run: nothing is reported, as for CCR026).

    Returns:
        The findings plan, or None when there is nothing to check.
    """
    if trades is None or rates is None:
        return None
    legs = ensure_columns(
        trades,
        {name: TRADE_SCHEMA[name] for name in ("asset_class", "notional_leg2", "currency_leg2")},
    )
    return (
        map_trade_risk_categories(legs)
        .filter((pl.col("asset_class") == "fx") & pl.col("notional_leg2").is_not_null())
        .select(
            pl.lit("ccr.trades").alias("table"),
            pl.col("trade_id").cast(pl.String).alias("record_id"),
            pl.col("netting_set_id").cast(pl.String),
            pl.col("currency_leg2").cast(pl.String).alias("currency"),
        )
        .join(_convertible(rates), left_on="currency", right_on="currency_from", how="left")
        .filter(pl.col("_convertible").is_null())
        .drop("_convertible")
        .sort("record_id", nulls_last=True)
    )


def _convertible(rates: pl.LazyFrame) -> pl.LazyFrame:
    """The currencies :func:`rebase_to_reporting_currency` converts: a non-null rate."""
    return rates.filter(pl.col(_RATE).is_not_null()).select(
        pl.col("currency_from"), pl.lit(True).alias("_convertible")
    )
