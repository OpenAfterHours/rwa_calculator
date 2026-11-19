"""
Facility-currency conversion for undrawn headroom netting.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``facility_undrawn``
    (headroom netting) and ``facility_warnings`` (HIE005). Both run inside
    ``unify``, i.e. BEFORE ``engine/fx`` rebases the unified frame to the
    reporting currency, so every amount here is still in its own currency.

Key responsibilities:
- Express a loan / contingent amount in the currency of the facility whose
  headroom it consumes, at the run's FX rates:
  ``amount x rate(child -> base) / rate(facility -> base)``. The undrawn amount
  is ``limit - utilisation``; that subtraction only means something in one
  currency, and the facility's is the one its limit is advised in.
- Mark an amount whose conversion needs a rate the run does not hold with a
  null factor, so the caller leaves it OUT of the netting (the headroom is never
  reduced by an amount the run cannot measure) and HIE005 can name it.
- Leave the same-currency path byte-for-byte unchanged (factor exactly 1.0), and
  net raw amounts when the run disables FX conversion: then no amount anywhere in
  the run is rebased, so every amount is already in one unit of account.

References:
- CRR Art. 4(1)(56) / PRA PS1/26 Glossary "conversion factor": "... the
  currently undrawn amount of the commitment from that facility, the extent of
  the commitment being determined by the advised limit"
- CRR Art. 111(1) / PRA PS1/26 Art. 111(1)(b): exposure value = nominal value
  x conversion factor
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FacilityFx:
    """The run's FX rates to its reporting currency, as headroom netting reads them.

    ``rates`` is ``None`` when conversion is off (``apply_fx_conversion=False``,
    or no configuration supplied): every factor is then 1.0. Otherwise it holds
    one ``(currency_from, _fx_rate_to_base)`` row per currency with a positive
    rate into ``base_currency`` — possibly none, when the run supplied no FX
    table, in which case every cross-currency amount is unmeasurable.
    """

    rates: pl.LazyFrame | None
    base_currency: str

    @property
    def enabled(self) -> bool:
        """True when cross-currency amounts are converted (and may be unmeasurable)."""
        return self.rates is not None


def build_facility_fx(
    fx_rates: pl.LazyFrame | None,
    config: CalculationConfig | None,
) -> FacilityFx:
    """Resolve the rate table headroom netting uses for this run.

    Reads the same ``fx_rates`` rows ``engine/fx`` later applies — those whose
    ``currency_to`` is the reporting currency — so a drawing is put in its
    facility's currency at exactly the rates that later put both in the
    reporting currency. A non-positive rate is treated as absent (it is outside
    the declared domain, DQ013, and dividing by it would manufacture headroom).
    One row per currency is kept, first in input order, so a duplicated rate can
    never multiply a drawing.
    """
    if config is None or not config.apply_fx_conversion:
        return FacilityFx(rates=None, base_currency="" if config is None else config.base_currency)
    base = config.base_currency
    if fx_rates is None:
        empty = pl.LazyFrame(schema={"currency_from": pl.String, "_fx_rate_to_base": pl.Float64})
        return FacilityFx(rates=empty, base_currency=base)
    rates = (
        fx_rates.filter((pl.col("currency_to") == base) & (pl.col("rate") > 0.0))
        .select(
            pl.col("currency_from"),
            pl.col("rate").cast(pl.Float64).alias("_fx_rate_to_base"),
        )
        .unique(subset=["currency_from"], keep="first", maintain_order=True)
    )
    return FacilityFx(rates=rates, base_currency=base)


@cites("CRR Art. 4(1)")
def with_facility_currency_factor(
    frame: pl.LazyFrame,
    fx: FacilityFx,
    *,
    amount_currency: str,
    facility_currency: str,
    factor: str,
) -> pl.LazyFrame:
    """Add ``factor``: the multiplier that puts an amount in its facility's currency.

    The factor is exactly 1.0 when conversion is off, when the two currencies
    agree, or when either is unknown (null: there is no mismatch to measure). It
    is ``rate(amount_currency -> base) / rate(facility_currency -> base)`` when
    both rates exist (the reporting currency's own rate is 1.0), and null when a
    needed rate is missing — the caller's signal to leave the amount un-netted.

    Args:
        frame: Rows carrying both currency columns.
        fx: The run's resolved rates (:func:`build_facility_fx`).
        amount_currency: Column holding the currency the amount is stated in.
        facility_currency: Column holding the currency to express it in.
        factor: Name of the Float64 column to add.

    Returns:
        ``frame`` with ``factor`` added and no other column changed.
    """
    if fx.rates is None:
        return frame.with_columns(pl.lit(1.0).alias(factor))

    rate_from = f"{factor}_from_rate"
    rate_to = f"{factor}_to_rate"
    from_ccy = pl.col(amount_currency)
    to_ccy = pl.col(facility_currency)
    # Left joins that keep the caller's row order: the netting sums downstream
    # then read the same sequence of values as before this conversion existed.
    with_rates = frame.join(
        fx.rates.rename({"_fx_rate_to_base": rate_from}),
        left_on=amount_currency,
        right_on="currency_from",
        how="left",
        maintain_order="left",
    ).join(
        fx.rates.rename({"_fx_rate_to_base": rate_to}),
        left_on=facility_currency,
        right_on="currency_from",
        how="left",
        maintain_order="left",
    )
    to_base_from = pl.when(from_ccy == fx.base_currency).then(1.0).otherwise(pl.col(rate_from))
    to_base_to = pl.when(to_ccy == fx.base_currency).then(1.0).otherwise(pl.col(rate_to))
    return with_rates.with_columns(
        pl.when(from_ccy.is_null() | to_ccy.is_null() | (from_ccy == to_ccy))
        .then(pl.lit(1.0))
        .otherwise(to_base_from / to_base_to)
        .alias(factor)
    ).drop(rate_from, rate_to)


def facility_currency_lookup(facilities: pl.LazyFrame, *, key: str, currency: str) -> pl.LazyFrame:
    """One ``(key, currency)`` row per facility reference, first in input order.

    De-duplicated so joining it onto loan / contingent rows can never multiply a
    drawing when the facilities table repeats a reference (that duplicate is
    reported separately as DQ004).
    """
    return facilities.select(
        pl.col("facility_reference").alias(key),
        pl.col("currency").alias(currency),
    ).unique(subset=[key], keep="first", maintain_order=True)
