"""
SA-CCR pipeline adapter: netting-set-grain CCR EAD as synthetic exposure rows.

Pipeline position:
    HierarchyResolver -> [CCR pipeline adapter] -> Classifier
        -> CRMProcessor -> SA/IRB/Slotting Calculators

Key responsibilities:
- Chain the existing SA-CCR engine functions
  (adjusted notional, supervisory delta, maturity factor, hedging set,
  asset-class add-on, PFE multiplier, EAD) over a ``RawCCRBundle`` to
  produce one ``ead_ccr`` value per netting set.
- Shape each netting-set row into a synthetic exposure row compatible
  with the unified ``RAW_EXPOSURE_SCHEMA`` (extended with provenance
  columns ``source_netting_set_id`` and ``ccr_method``) so the rest of
  the pipeline (Classifier -> CRM -> SA calculator -> Aggregator) can
  consume the CCR EAD without any CCR-aware special-cases downstream.
- Stay LazyFrame-first: the netting-set frame and the synthetic-exposure
  frame returned by ``ccr_rows_to_exposures`` are both ``pl.LazyFrame``.

References:
- CRR Art. 271: scope (one EAD row per netting set / counterparty pair)
- CRR Art. 272(4): netting-set definition + legal-enforceability fallback
- CRR Art. 274(2): EAD = alpha * (RC + PFE)
- CRR Art. 275(1): replacement cost (unmargined)
- CRR Art. 277(1)-(2): hedging-set and IR maturity-bucket partition
- CRR Art. 277a(1)(a): intra-asset-class add-on aggregation
- CRR Art. 278(1)-(3): PFE multiplier + add-on
- CRR Art. 279a-c: supervisory delta / adjusted notional / maturity factor
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawCCRBundle
from rwa_calc.contracts.config import CCRConfig
from rwa_calc.engine.ccr.adjusted_notional import (
    compute_adjusted_notional_credit,
    compute_adjusted_notional_fx,
    compute_adjusted_notional_ir,
)
from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class, compute_pfe
from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_linear

logger = logging.getLogger(__name__)


# =============================================================================
# Public API
# =============================================================================


def ccr_rows_to_exposures(
    raw_ccr: RawCCRBundle,
    config_ccr: CCRConfig,
    reporting_date: date,
    *,
    base_currency: str = "GBP",
    fx_rates: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """Shape SA-CCR netting-set EADs into synthetic exposure rows.

    Drives the full SA-CCR chain over the legally-enforceable trades and
    netting sets in ``raw_ccr`` and emits one row per netting set with
    columns compatible with the unified ``RAW_EXPOSURE_SCHEMA``:

        exposure_reference    = "ccr__<netting_set_id>"
        exposure_type         = "ccr_netting_set"
        counterparty_reference= from NETTING_SET_SCHEMA
        risk_type             = "CCR_DERIVATIVE"
        drawn_amount          = ead_ccr  (alpha * (RC + PFE))
        interest              = 0.0
        undrawn_amount        = 0.0
        nominal_amount        = 0.0
        currency              = first trade currency in the NS
        value_date            = config.reporting_date
        maturity_date         = max(trade maturity in the NS)
        seniority             = "senior"   (conservative default)
        source_netting_set_id = <netting_set_id>
        ccr_method            = "sa_ccr"
        addon_aggregate       = per-NS asset-class add-on aggregate
        pfe_multiplier        = Art. 278(3) multiplier
        pfe_addon             = Art. 278(1) PFE
        rc_unmargined         = Art. 275(1) replacement cost
        ead_ccr               = Art. 274(2) EAD at alpha

    The downstream concat in the orchestrator uses ``how="diagonal_relaxed"``
    so any other ``RAW_EXPOSURE_SCHEMA`` columns absent here are filled with
    nulls; the CCR row then flows through Classifier / CRM / SA Calculator
    as a vanilla unsecured corporate-style exposure where drawn_amount is
    already the post-CCR EAD.

    Args:
        raw_ccr: CCR bundle whose legal-enforceability gate has already been
            applied upstream (non-enforceable netting sets are split into
            single-trade NSes per Art. 272(4)).
        config_ccr: CCR configuration (controls alpha for compute_pfe).
        reporting_date: As-of date for the calculation; used to compute
            ``years_to_maturity`` and ``adjusted_notional`` per Art. 279b
            and is written to the synthetic exposure row's ``value_date``.
        base_currency: Reporting currency for FX adjusted notional per
            Art. 279b(1)(b); typically ``CalculationConfig.base_currency``.
            Used only when ``fx_rates`` is supplied and the trade book contains
            ``asset_class == "fx"`` rows. Defaults to ``"GBP"``.
        fx_rates: Optional FX-rates LazyFrame conforming to ``FX_RATES_SCHEMA``
            (``currency_from``, ``currency_to``, ``rate``). When None the FX
            adjusted-notional branch is skipped — FX trades will have null
            ``adjusted_notional`` and therefore no PFE contribution, matching
            the pre-P8.9 behaviour for firms with no derivatives FX book.

    Returns:
        LazyFrame at netting-set grain with one synthetic exposure row per
        netting set in ``raw_ccr``. Empty (zero-row) frame when the trades
        bundle is empty.

    References:
        CRR Art. 271; CRR Art. 274; CRR Art. 277-279c; CRR Art. 278.
    """
    trades_lf = raw_ccr.trades.trades
    netting_sets_lf = raw_ccr.netting_sets.netting_sets

    # 1) Enrich trade-level frame with years_to_maturity, then chain the
    #    per-trade SA-CCR components in regulatory order.
    trades_enriched = trades_lf.with_columns(
        ((pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25).alias(
            "years_to_maturity"
        )
    )
    trades_enriched = compute_adjusted_notional_ir(trades_enriched, reporting_date)
    # FX adjusted notional per Art. 279b(1)(b) — overlays the FX branch on top
    # of the IR output via coalesce so non-FX rows pass through unchanged.
    if fx_rates is not None:
        trades_enriched = compute_adjusted_notional_fx(
            trades_enriched, base_currency, fx_rates
        )
    # Credit adjusted notional per Art. 279b(1)(a) — shares the IR supervisory-
    # duration kernel and overlays via coalesce; no gate needed (no-op for
    # non-credit rows).
    trades_enriched = compute_adjusted_notional_credit(trades_enriched, reporting_date)
    trades_enriched = compute_supervisory_delta_linear(trades_enriched)
    trades_enriched = compute_maturity_factor_unmargined(trades_enriched)
    trades_enriched = assign_hedging_set(trades_enriched)

    # 2) Per-(NS, asset_class) add-on, then aggregate to per-NS sum.
    addon_per_class = compute_addon_per_asset_class(trades_enriched)
    addon_per_ns = addon_per_class.group_by("netting_set_id").agg(
        pl.col("asset_class_addon").fill_null(0.0).sum().alias("addon_aggregate")
    )

    # 3) Per-NS v_net (sum of mtm_value over trades) and trade-level metadata
    #    needed for synthetic-exposure rows (currency, max maturity).
    ns_trade_aggregates = trades_lf.group_by("netting_set_id").agg(
        [
            pl.col("mtm_value").fill_null(0.0).sum().alias("v_net"),
            pl.col("currency").first().alias("_trade_currency"),
            pl.col("maturity_date").max().alias("_trade_max_maturity"),
        ]
    )

    # 4) CCR collateral: per-NS c_net. CCR-A1 has zero rows -> all NS see c_net=0.
    ccr_collateral_lf = raw_ccr.ccr_collateral.ccr_collateral
    ccr_collateral_cols = ccr_collateral_lf.collect_schema().names()
    if "netting_set_id" in ccr_collateral_cols and "collateral_value" in ccr_collateral_cols:
        c_net_per_ns = ccr_collateral_lf.group_by("netting_set_id").agg(
            pl.col("collateral_value").fill_null(0.0).sum().alias("c_net")
        )
    else:
        # Empty-collateral path: derive an empty c_net frame keyed by netting set.
        c_net_per_ns = netting_sets_lf.select(
            pl.col("netting_set_id"),
            pl.lit(0.0).alias("c_net"),
        )

    # 5) Compose NS-grain frame for compute_pfe: v_net, c_net, addon_aggregate.
    ns_frame = (
        netting_sets_lf.join(ns_trade_aggregates, on="netting_set_id", how="left")
        .join(addon_per_ns, on="netting_set_id", how="left")
        .join(c_net_per_ns, on="netting_set_id", how="left")
        .with_columns(
            [
                pl.col("v_net").fill_null(0.0),
                pl.col("c_net").fill_null(0.0),
                pl.col("addon_aggregate").fill_null(0.0),
            ]
        )
    )

    ns_with_ead = compute_pfe(ns_frame, config_ccr)

    # 6) Shape into synthetic exposure rows. drawn_amount = ead_ccr so that
    #    the CRM `_initialize_ead` produces ead_pre_crm = ead_ccr (no CCF /
    #    no collateral / no guarantee match) and the SA calculator then
    #    routes it through Classifier's INSTITUTION class at CQS 2 -> 50%.
    return ns_with_ead.select(
        [
            pl.concat_str([pl.lit("ccr__"), pl.col("netting_set_id")]).alias("exposure_reference"),
            pl.lit("ccr_netting_set").alias("exposure_type"),
            pl.col("counterparty_reference"),
            pl.lit(reporting_date).alias("value_date"),
            pl.col("_trade_max_maturity").alias("maturity_date"),
            pl.col("_trade_currency").alias("currency"),
            pl.col("ead_ccr").alias("drawn_amount"),
            pl.lit(0.0).alias("interest"),
            pl.lit(0.0).alias("undrawn_amount"),
            pl.lit(0.0).alias("nominal_amount"),
            pl.lit("senior").alias("seniority"),
            pl.lit("CCR_DERIVATIVE").alias("risk_type"),
            pl.col("netting_set_id").alias("source_netting_set_id"),
            pl.lit("sa_ccr").alias("ccr_method"),
            # Preserve the SA-CCR component columns so downstream tests /
            # COREP exports can reconcile the EAD back to RC + PFE without
            # re-running the chain.
            pl.col("addon_aggregate"),
            pl.col("pfe_multiplier"),
            pl.col("pfe_addon"),
            pl.col("rc_unmargined"),
            pl.col("ead_ccr"),
        ]
    )
