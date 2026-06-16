"""
Failed-trade (settlement-risk) RWA calculator — CRR Art. 378 / Art. 379.

Pipeline position:
    Standalone CCR sub-stage. Consumes ``FailedTradesBundle.failed_trades``
    (one row per failed settlement) and emits a per-row LazyFrame with the
    own-funds requirement, RWA, and regulatory-band attribution.

Key responsibilities:
- For DvP rows (``settlement_type == "dvp"``): compute
  ``price_difference = max(0, agreed_settlement_price - current_market_value)``
  and look up the Art. 378 Table 1 multiplier by ``working_days_past_due``
  band (5-15, 16-30, 31-45, 46+). Own-funds = price_difference x multiplier;
  RWA = own_funds x 12.5.
- For non-DvP free-delivery rows (``settlement_type ==
  "non_dvp_free_delivery"``) past t+5: compute
  ``exposure_amount = value_transferred + current_positive_exposure``,
  treat as a credit-risk exposure at 1250% RW, so RWA = exposure x 12.5
  and own_funds = exposure (Art. 379(1) Table 2 Column 4).
- Attribute each row to a stable ``regulatory_band`` string for downstream
  audit / aggregation. Bands ``dvp_5_15``, ``dvp_16_30``, ``dvp_31_45``,
  ``dvp_46_plus`` (DvP); ``non_dvp_col4_t5_plus`` (non-DvP Col 4).

The P8.24 implementation covers the in-scope rows of the proposal's hand
calculation. Out-of-scope (left for follow-up tickets, default-False flag
gates already present in the schema):
- Pre-t+5 DvP rows (no capital requirement — currently produce 0 own_funds).
- Non-DvP Columns 2/3 (pre-first-leg, t0-t4) — schema-supported but
  ``regulatory_band`` falls through to the Col 4 path only for t>=5.
- Art. 379(2) immateriality 100% RW alternative.
- Art. 379(3) CET1 deduction election.
- Art. 380 system-wide failure waiver.
- Art. 378 first-paragraph repo / sec-lending exclusion gate.

References:
- CRR Art. 378 + Table 1: DvP multiplier ladder.
- CRR Art. 379(1) + Table 2: non-DvP free-delivery treatment.
- CRR Art. 379(2)-(3): immateriality / CET1-deduction electives (OOS).
- CRR Art. 380: system-wide failure waiver (OOS).
- PRA PS1/26 Art. 92(3)(a), 92(3)(ca): UK onshoring, unchanged numerics.
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Settlement-type discriminators (mirror ``FAILED_TRADE_SCHEMA``).
_SETTLEMENT_TYPE_DVP: str = "dvp"
_SETTLEMENT_TYPE_NON_DVP: str = "non_dvp_free_delivery"

# Failed-trade regulatory multipliers / conversion factor + working-days-past-due
# band lower bounds resolved from the rulepack once at module load (CRR Art. 378 /
# 379 / 92(3)(ca); regime-invariant, resolved against "crr"). The integer band
# bounds feed both this ladder and the regulatory_band strings below.
_PACK = resolve("crr", date(2026, 1, 1))
_DVP_MULT_5_15 = scalar_value(_PACK.scalar_param("failed_trade_dvp_mult_5_15"))
_DVP_MULT_16_30 = scalar_value(_PACK.scalar_param("failed_trade_dvp_mult_16_30"))
_DVP_MULT_31_45 = scalar_value(_PACK.scalar_param("failed_trade_dvp_mult_31_45"))
_DVP_MULT_46_PLUS = scalar_value(_PACK.scalar_param("failed_trade_dvp_mult_46_plus"))
_NON_DVP_COL4_RW_MULTIPLIER = scalar_value(
    _PACK.scalar_param("failed_trade_non_dvp_col4_rw_multiplier")
)
_OWN_FUNDS_TO_RWA_FACTOR = scalar_value(_PACK.scalar_param("own_funds_to_rwa_factor"))
_DVP_BAND_5_15_LOWER = _PACK.int_param("failed_trade_dvp_band_5_15_lower_days").value
_DVP_BAND_16_30_LOWER = _PACK.int_param("failed_trade_dvp_band_16_30_lower_days").value
_DVP_BAND_31_45_LOWER = _PACK.int_param("failed_trade_dvp_band_31_45_lower_days").value
_DVP_BAND_46_PLUS_LOWER = _PACK.int_param("failed_trade_dvp_band_46_plus_lower_days").value
_NON_DVP_COL4_LOWER = _PACK.int_param("failed_trade_non_dvp_col4_lower_days").value


# NOTE: No ``@cites("CRR Art. 378")`` / ``@cites("CRR Art. 379")`` —
# watchfire's bundled rulebook index (rulebook_version 2026-05-15) does not
# yet contain CRR Title V (Settlement Risk) Art. 378-380. Article
# attribution is preserved in the docstring; re-extending the watchfire CRR
# index for Title V is a separate follow-up (mirrors the P8.7 fix-commit
# pattern for Art. 280a/b/c and the existing rc.py / sa_ccr.py waivers for
# Art. 274 / 275).
def compute_failed_trade_rwa(
    failed_trades: pl.LazyFrame,
    config: CalculationConfig,  # noqa: ARG001 — numerics identical under CRR and PS1/26
) -> pl.LazyFrame:
    """Compute own-funds and RWA for failed trades per CRR Art. 378 / 379.

    Args:
        failed_trades: LazyFrame matching ``FAILED_TRADE_SCHEMA`` — one row
            per failed settlement. Required columns: ``failed_trade_id``,
            ``counterparty_reference``, ``settlement_type``,
            ``working_days_past_due``, plus the branch-specific value
            columns (``agreed_settlement_price`` + ``current_market_value``
            for DvP; ``value_transferred`` + ``current_positive_exposure``
            for non-DvP free delivery).
        config: Calculation configuration. The Art. 378/379 numerical
            ladder is identical under CRR and PRA PS1/26, so the framework
            field is not branched on — the parameter is kept for signature
            consistency with sibling CCR calculators.

    Returns:
        LazyFrame with one row per input row, carrying:
        ``failed_trade_id``, ``counterparty_reference``, ``settlement_type``,
        ``working_days_past_due``, ``price_difference`` (DvP-only,
        null otherwise), ``exposure_amount`` (non-DvP-only, null otherwise),
        ``multiplier_or_rw``, ``own_funds_requirement``, ``failed_trade_rwa``,
        ``regulatory_band``.

    References:
        CRR Art. 378 + Table 1 (DvP multiplier ladder);
        CRR Art. 379(1) + Table 2 Col 4 (non-DvP, 1250% RW);
        PRA PS1/26 Art. 92(3)(a), 92(3)(ca).
    """
    is_dvp = pl.col("settlement_type") == _SETTLEMENT_TYPE_DVP
    is_non_dvp = pl.col("settlement_type") == _SETTLEMENT_TYPE_NON_DVP
    days = pl.col("working_days_past_due")

    # DvP price difference: max(0, agreed - mv). Null on non-DvP rows.
    price_difference = (
        pl.when(is_dvp)
        .then(
            pl.max_horizontal(
                pl.col("agreed_settlement_price") - pl.col("current_market_value"),
                pl.lit(0.0),
            )
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("price_difference")
    )

    # Non-DvP exposure: value_transferred + current_positive_exposure.
    # Null on DvP rows.
    exposure_amount = (
        pl.when(is_non_dvp)
        .then(pl.col("value_transferred") + pl.col("current_positive_exposure"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("exposure_amount")
    )

    # DvP Art. 378 Table 1 multiplier ladder (highest band wins). The band
    # BOUNDS are int counts from data/tables; the multipliers come from the
    # rulepack (module-level _DVP_MULT_* above).
    dvp_multiplier = (
        pl.when(days >= _DVP_BAND_46_PLUS_LOWER)
        .then(pl.lit(_DVP_MULT_46_PLUS))
        .when(days >= _DVP_BAND_31_45_LOWER)
        .then(pl.lit(_DVP_MULT_31_45))
        .when(days >= _DVP_BAND_16_30_LOWER)
        .then(pl.lit(_DVP_MULT_16_30))
        .when(days >= _DVP_BAND_5_15_LOWER)
        .then(pl.lit(_DVP_MULT_5_15))
        .otherwise(pl.lit(0.0))
    )

    # Combined multiplier_or_rw: DvP multiplier on DvP rows; the Col-4 RWA
    # multiplier (12.5) on non-DvP rows in Column 4. The own-funds factor
    # against the full exposure on non-DvP Col 4 is 1.0 (RW=1250% =>
    # own_funds = exposure; RWA = exposure * 12.5).
    multiplier_or_rw = (
        pl.when(is_dvp)
        .then(dvp_multiplier)
        .when(is_non_dvp & (days >= _NON_DVP_COL4_LOWER))
        .then(pl.lit(_NON_DVP_COL4_RW_MULTIPLIER))
        .otherwise(pl.lit(0.0))
        .alias("multiplier_or_rw")
    )

    # Regulatory band string (audit / aggregation key).
    regulatory_band = (
        pl.when(is_dvp & (days >= _DVP_BAND_46_PLUS_LOWER))
        .then(pl.lit("dvp_46_plus"))
        .when(is_dvp & (days >= _DVP_BAND_31_45_LOWER))
        .then(pl.lit("dvp_31_45"))
        .when(is_dvp & (days >= _DVP_BAND_16_30_LOWER))
        .then(pl.lit("dvp_16_30"))
        .when(is_dvp & (days >= _DVP_BAND_5_15_LOWER))
        .then(pl.lit("dvp_5_15"))
        .when(is_non_dvp & (days >= _NON_DVP_COL4_LOWER))
        .then(pl.lit("non_dvp_col4_t5_plus"))
        .otherwise(pl.lit("dvp_pre_t5"))
        .alias("regulatory_band")
    )

    # Own-funds: DvP = price_difference * multiplier; non-DvP Col 4 =
    # exposure_amount (1.0 factor against the full exposure).
    own_funds = (
        pl.when(is_dvp)
        .then(pl.col("price_difference") * dvp_multiplier)
        .when(is_non_dvp & (days >= _NON_DVP_COL4_LOWER))
        .then(pl.col("exposure_amount"))
        .otherwise(pl.lit(0.0))
        .alias("own_funds_requirement")
    )

    # RWA: own_funds * 12.5 (CRR Art. 92(3)(ca)).
    failed_trade_rwa = (pl.col("own_funds_requirement") * _OWN_FUNDS_TO_RWA_FACTOR).alias(
        "failed_trade_rwa"
    )

    return (
        failed_trades.with_columns([price_difference, exposure_amount])
        .with_columns([multiplier_or_rw, regulatory_band, own_funds])
        .with_columns([failed_trade_rwa])
        .select(
            [
                "failed_trade_id",
                "counterparty_reference",
                "settlement_type",
                "working_days_past_due",
                "price_difference",
                "exposure_amount",
                "multiplier_or_rw",
                "own_funds_requirement",
                "failed_trade_rwa",
                "regulatory_band",
            ]
        )
    )


__all__ = ["compute_failed_trade_rwa"]
