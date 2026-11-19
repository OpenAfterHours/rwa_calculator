"""
SA-CCR collateral: the VM and NICA of each netting set.

Pipeline position:
    ccr_rows_to_exposures: resolve_margin_terms -> value_ccr_collateral ->
    compose_exposure_value (Art. 274(2)/(3), 275, 278)

Key responsibilities:
- Value every ``ccr.ccr_collateral`` item at its volatility-adjusted value with
  the run regime's Art. 224 supervisory haircuts (``HaircutCalculator`` — the
  same tables, maturity bands and Art. 197 eligibility gates as lending CRM):
  received ``C·(1 - HC - Hfx)`` (Art. 223(2)), posted ``C·(1 + HC + Hfx)``
  (Art. 276(2)); received positive, posted negative (Art. 276(1)(c)).
- Liquidation period (Art. 276(3)): the MPOR of a margined netting set; for an
  unmargined one, the longest remaining maturity of its trades capped at one
  business year.
- Recognise Art. 197 eligible financial collateral only (Art. 276(1)(a)/(b)):
  cash, gold, debt securities at the Art. 197(1)(b)/(d) credit quality,
  equities in a main index. Anything else is left out and reported CCR024.
- Split a margined netting set's collateral into VM and NICA by
  ``collateral_role`` (Art. 275(2), 276(1)(e)); on the unmargined basis every
  item is NICA (Art. 275(1)). Segregated, bankruptcy-remote posted collateral
  is not recognised in NICA (Art. 276(1)(g)).
- Currency mismatch (Hfx, Art. 223(2) / Art. 224 Table 4): waived only where
  the item is denominated in the single currency of every trade of its netting
  set. The schema carries no settlement currency, so a multi-currency netting
  set, or an item with no currency, takes Hfx — the larger magnitude for a
  posted item and the smaller relief for a received one.

Before review CC-02 the netting-set C was read from a ``collateral_value``
column the loaded schema never has, so every netting set took C = 0: received
collateral and VM gave no relief and posted collateral added no exposure.

References:
- CCR (CRR) Part Art. 276(1): "(a)/(b) ... only collateral that is eligible
  under Article[s] 197 ... shall be recognised; (c) collateral received from a
  counterparty shall be recognised with a positive sign and collateral posted to
  a counterparty shall be recognised with a negative sign; (d) the
  volatility-adjusted value ... shall be calculated in accordance with Article
  223 ...; (e) the same collateral item shall not be included in both VM and
  NICA at the same time; ... (g) any collateral posted to the counterparty that
  is segregated ... and ... bankruptcy remote ... shall not be recognised in the
  calculation of NICA and NICA MA."
- Art. 276(2): "C VA = C · (1 + H C + H fx)" for collateral posted.
- Art. 276(3): "(a) the longest remaining maturity of transactions in the
  netting set, capped at OneBusinessYear, for the netting sets referred to in
  Article 275(1); (b) the margin period of risk ... for the netting sets
  referred to in Article 275(2) and (3)."
- PS1/26 Annex R leaves Art. 275-276 unamended; the Art. 224 haircut table is
  the regime's (``collateral_haircuts``, PS1/26 Art. 224 under Basel 3.1).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA, SA_CCR_RECOGNISED_COLLATERAL_TYPES
from rwa_calc.engine.ccr.reporting_currency import rebase_to_reporting_currency
from rwa_calc.engine.crm.eligibility import normalise_collateral_type_expr
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

_PACK = resolve("crr", date(2026, 1, 1))
#: OneBusinessYear (Art. 276(3)(a) cap on the unmargined liquidation period).
_ONE_BUSINESS_YEAR = _PACK.int_param("sa_ccr_business_days_per_year").value

#: Sentinels that never equal a currency, so a missing currency takes Hfx.
_NO_CURRENCY = "__none__"
_MIXED_CURRENCIES = "__mixed__"

_COLLATERAL_COLUMNS = {
    name: CCR_COLLATERAL_SCHEMA[name]
    for name in (
        "market_value",
        "is_posted_by_firm",
        "is_segregated",
        "collateral_role",
        "is_main_index",
        "currency",
        "issuer_cqs",
        "issuer_type",
        "residual_maturity_years",
    )
}


def value_ccr_collateral(
    collateral: pl.LazyFrame,
    horizons: pl.LazyFrame,
    rates: pl.LazyFrame | None,
    haircut_config: CalculationConfig,
    haircut_pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Net each netting set's recognised collateral into VM and NICA.

    Args:
        collateral: ``ccr.ccr_collateral`` (CCR_COLLATERAL_SCHEMA).
        horizons: :func:`collateral_horizons` output, one row per netting set.
        rates: Spot rates to the reporting currency
            (``reporting_currency_rates``), or None (no conversion).
        haircut_config: The run configuration (haircut table selection).
        haircut_pack: The run's resolved rulepack, when the caller has it.

    Returns:
        LazyFrame ``(netting_set_id, vm_net, nica_collateral,
        collateral_unmargined)``: the margined-basis VM and itemised NICA
        (Art. 275(2), MPOR liquidation period) and the unmargined-basis net
        collateral, all NICA (Art. 275(1); the Art. 274(3) cap's basis).
    """
    valued = _valued_items(collateral, horizons, rates, haircut_config, haircut_pack).filter(
        pl.col("_attributed")
    )
    in_nica = ~(pl.col("_posted") & pl.col("is_segregated").eq_missing(True))
    is_im = pl.col("_role").eq_missing("im")
    margined = pl.col("_basis") == "margined"
    value = pl.col("_signed_value")
    return valued.group_by("netting_set_id").agg(
        value.filter(margined & ~is_im).sum().alias("vm_net"),
        value.filter(margined & is_im & in_nica).sum().alias("nica_collateral"),
        value.filter(~margined & in_nica).sum().alias("collateral_unmargined"),
    )


def ccr_collateral_findings(
    collateral: pl.LazyFrame,
    netting_sets: pl.LazyFrame,
    stated_netting_set_ids: pl.LazyFrame,
    haircut_config: CalculationConfig,
    haircut_pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Collateral items :func:`value_ccr_collateral` leaves out — the CCR024 plan.

    One row per item that is not Art. 197 eligible, or that names a stated
    netting set the Art. 272(4) enforceability gate split into several
    single-trade netting sets (the item cannot be attributed to one of them).
    An item naming no stated netting set at all is the ``ccr.ccr_collateral``
    foreign key's DQ005, not reported again here. Recognition does not depend on
    the liquidation period or currency, so both are fixed here.

    Args:
        collateral: ``ccr.ccr_collateral`` as the enforceability gate re-keyed it.
        netting_sets: The gated netting sets (``netting_set_id``, ``is_margined``).
        stated_netting_set_ids: ``netting_set_id`` of the netting sets as input
            (before the enforceability gate).
        haircut_config: The run configuration.
        haircut_pack: The run's resolved rulepack, when the caller has it.

    Returns:
        LazyFrame ``(ccr_collateral_reference, netting_set_id, collateral_type,
        issuer_cqs, reason)``.
    """
    horizons = netting_sets.select(
        pl.col("netting_set_id"),
        pl.lit(False).alias("is_margined"),
        pl.lit(_ONE_BUSINESS_YEAR).alias("_horizon_margined"),
        pl.lit(_ONE_BUSINESS_YEAR).alias("_horizon_unmargined"),
        pl.lit(_MIXED_CURRENCIES).alias("_ns_currency"),
    )
    stated = stated_netting_set_ids.select(
        pl.col("netting_set_id").cast(pl.String), pl.lit(True).alias("_stated")
    ).unique(subset="netting_set_id")
    valued = _valued_items(collateral, horizons, None, haircut_config, haircut_pack).filter(
        pl.col("_basis") == "unmargined"
    )
    return (
        valued.join(stated, on="netting_set_id", how="left")
        .filter(
            (pl.col("_attributed") & ~pl.col("_recognised"))
            | (~pl.col("_attributed") & pl.col("_stated").is_not_null())
        )
        .select(
            pl.col("ccr_collateral_reference").cast(pl.String),
            pl.col("netting_set_id").cast(pl.String),
            pl.col("collateral_type").cast(pl.String),
            pl.col("issuer_cqs").cast(pl.Int64),
            pl.when(pl.col("_attributed"))
            .then(pl.lit("not_eligible"))
            .otherwise(pl.lit("not_attributable"))
            .alias("reason"),
        )
        .sort("ccr_collateral_reference", nulls_last=True)
    )


def collateral_horizons(
    netting_sets: pl.LazyFrame,
    trades: pl.LazyFrame,
    mpor_days: pl.Expr,
) -> pl.LazyFrame:
    """Per-netting-set liquidation periods and settlement currency for valuation.

    Args:
        netting_sets: Resolved netting sets (``resolve_margin_terms`` output).
        trades: Trades carrying ``netting_set_id``, ``business_days_to_maturity``,
            ``currency`` and ``currency_leg2``.
        mpor_days: The Art. 285 MPOR expression (``margined_mpor_days()``),
            evaluated on the resolved netting-set frame.

    Returns:
        LazyFrame ``(netting_set_id, is_margined, _horizon_margined,
        _horizon_unmargined, _ns_currency)``.
    """
    trades = ensure_columns(
        trades,
        {
            "currency": ColumnSpec(pl.String, required=False),
            "currency_leg2": ColumnSpec(pl.String, required=False),
        },
    )
    legs = pl.concat(
        [
            trades.select("netting_set_id", pl.col("currency").cast(pl.String)),
            trades.select(
                "netting_set_id", pl.col("currency_leg2").cast(pl.String).alias("currency")
            ).filter(pl.col("currency").is_not_null()),
        ],
        how="vertical",
    )
    leg_currencies = legs.group_by("netting_set_id").agg(
        pl.col("currency").drop_nulls().n_unique().alias("_currency_count"),
        pl.col("currency").null_count().alias("_null_currencies"),
        pl.col("currency").drop_nulls().first().alias("_single_currency"),
    )
    trade_terms = (
        trades.group_by("netting_set_id")
        .agg(pl.col("business_days_to_maturity").max().alias("_longest_bd"))
        .join(leg_currencies, on="netting_set_id", how="left")
    )
    return (
        netting_sets.select(
            pl.col("netting_set_id"),
            pl.col("is_margined"),
            mpor_days.alias("_horizon_margined"),
        )
        .join(trade_terms, on="netting_set_id", how="left")
        .with_columns(
            pl.min_horizontal(
                pl.max_horizontal(pl.col("_longest_bd"), pl.lit(0)), pl.lit(_ONE_BUSINESS_YEAR)
            ).alias("_horizon_unmargined"),
            pl.when((pl.col("_currency_count") == 1) & (pl.col("_null_currencies") == 0))
            .then(pl.col("_single_currency"))
            .otherwise(pl.lit(_MIXED_CURRENCIES))
            .alias("_ns_currency"),
        )
        .select(
            "netting_set_id",
            "is_margined",
            "_horizon_margined",
            "_horizon_unmargined",
            "_ns_currency",
        )
    )


def _valued_items(
    collateral: pl.LazyFrame,
    horizons: pl.LazyFrame,
    rates: pl.LazyFrame | None,
    haircut_config: CalculationConfig,
    haircut_pack: ResolvedRulepack | None,
) -> pl.LazyFrame:
    """Every item on each basis it is valued on, with its signed recognised value.

    The unmargined basis is valued for every attributed item (the Art. 274(3)
    cap needs it for a margined netting set too); the margined basis only for an
    item of a margined netting set. An item whose netting set is not among
    ``horizons`` carries ``_attributed`` False and a zero value.
    """
    items = rebase_to_reporting_currency(
        ensure_columns(collateral, _COLLATERAL_COLUMNS), ("market_value",), rates
    ).join(horizons, on="netting_set_id", how="left")
    attributed = pl.col("is_margined").is_not_null()
    base = items.with_columns(
        attributed.alias("_attributed"),
        pl.col("is_posted_by_firm").eq_missing(True).alias("_posted"),
        # A null or unrecognised role (DQ006) is VM: for a received item VM gives
        # less relief than NICA, which also lowers the TH + MTA - NICA floor.
        pl.col("collateral_role").str.strip_chars().str.to_lowercase().alias("_role"),
    )
    on_bases = pl.concat(
        [
            base.with_columns(
                pl.lit("unmargined").alias("_basis"),
                pl.col("_horizon_unmargined").alias("liquidation_period_days"),
            ),
            base.filter(pl.col("is_margined")).with_columns(
                pl.lit("margined").alias("_basis"),
                pl.col("_horizon_margined").alias("liquidation_period_days"),
            ),
        ],
        how="vertical",
    )
    haircut_input = on_bases.with_columns(
        pl.col("market_value").abs().alias("market_value"),
        pl.col("currency").fill_null(_NO_CURRENCY).alias("original_currency"),
        pl.col("_ns_currency").alias("exposure_currency"),
        pl.lit(False).alias("is_listed"),
        pl.lit(True).alias("is_eligible_financial_collateral"),
    )
    haircut = HaircutCalculator().apply_haircuts(haircut_input, haircut_config, pack=haircut_pack)
    recognised = (
        pl.col("_attributed")
        & pl.col("is_eligible_financial_collateral")
        & normalise_collateral_type_expr().is_in(sorted(SA_CCR_RECOGNISED_COLLATERAL_TYPES))
        & (pl.col("collateral_type").str.to_lowercase() != "credit_linked_note")
    )
    posted_value = -pl.col("market_value") * (
        1.0 + pl.col("collateral_haircut") + pl.col("fx_haircut")
    )
    return haircut.with_columns(recognised.alias("_recognised")).with_columns(
        pl.when(~pl.col("_recognised"))
        .then(pl.lit(0.0))
        .when(pl.col("_posted"))
        .then(posted_value)
        .otherwise(pl.col("value_after_haircut"))
        .alias("_signed_value")
    )
