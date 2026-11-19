"""
Failed-trade (settlement-risk) RWA calculator — CRR Art. 378 / Art. 379.

Pipeline position:
    Standalone CCR sub-stage. Consumes ``FailedTradesBundle.failed_trades``
    (one row per failed settlement) and emits a per-row LazyFrame with the
    own-funds requirement, RWA, and regulatory-band attribution;
    ``failed_trade_exposure_rows`` shapes that into the ``ft__`` rows the ccr
    stage appends to the exposure frame.

Key responsibilities:
- DvP rows (``settlement_type`` "dvp", read case-insensitively): the Art. 378
  price difference on the side that can LOSE — ``agreed - MV`` for a sale,
  ``MV - agreed`` for a purchase (``is_purchase``), the absolute difference
  when the side is unknown (the input gate names those rows, CCR031) — times
  the Table 1 multiplier for the ``working_days_past_due`` band (5-15, 16-30,
  31-45, 46+). RWA = own funds x 12.5. The row is an own-funds line.
- Non-DvP free deliveries (``"non_dvp_free_delivery"``), Art. 379(1) Table 2:
  Column 4 (5+ days after the second leg) — exposure = value transferred +
  current positive exposure at 1250%, so own funds = exposure (own-funds
  line); Column 3 (first leg paid, fewer than 5 days) — the same exposure
  "treated as an exposure": an ordinary credit-exposure row risk-weighted
  downstream (SA or IRB, Art. 379(2)), with no own-funds amount here;
  Column 2 (nothing transferred) — no charge.
- Attribute each row to a stable ``regulatory_band``: ``dvp_5_15``,
  ``dvp_16_30``, ``dvp_31_45``, ``dvp_46_plus``, ``dvp_pre_t5`` (DvP);
  ``non_dvp_col4_t5_plus``, ``non_dvp_col3``, ``non_dvp_col2`` (free
  delivery); ``unrecognised_settlement_type`` (no charge; the input gate
  reports the value, DQ006).

Review item CC-09 (2026-11): the price difference used to be ``max(0, agreed -
MV)`` for every trade (a purchase's loss was dropped, a purchase's gain was
charged), Column 3 gave zero under a DvP label, and any spelling but the exact
lower-case type gave zero silently.

Out of scope (default-False flag gates already present in the schema):
- Art. 379(2) immateriality 100% RW alternative and the IRB PD-from-rating
  election (Column 3 rows take the ordinary SA / IRB route).
- Art. 379(3) CET1 deduction election.
- Art. 380 system-wide failure waiver.
- Art. 378 first-paragraph repo / sec-lending exclusion gate.
- Art. 379(1)(b) cross-border one-day condition (no input; charged).

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
from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import FAILED_TRADE_SCHEMA
from rwa_calc.domain.enums import RiskType
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Settlement-type discriminators (mirror ``FAILED_TRADE_SCHEMA``).
_SETTLEMENT_TYPE_DVP: str = "dvp"
_SETTLEMENT_TYPE_NON_DVP: str = "non_dvp_free_delivery"

# Synthetic exposure-row namespace and Column 3 band (stable audit strings).
_ROW_PREFIX: str = "ft__"
_BAND_NON_DVP_COL3: str = "non_dvp_col3"

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
    # ``is_purchase`` is optional input: a caller-built frame may omit it, and a
    # typed null reads as "side unknown".
    failed_trades = ensure_columns(
        failed_trades, {"is_purchase": FAILED_TRADE_SCHEMA["is_purchase"]}
    )
    settlement_type = pl.col("settlement_type").str.to_lowercase()
    is_dvp = settlement_type == _SETTLEMENT_TYPE_DVP
    is_non_dvp = settlement_type == _SETTLEMENT_TYPE_NON_DVP
    days = pl.col("working_days_past_due")
    # Art. 379(1) Table 2: Column 4 from 5 days after the second leg; Column 3
    # from the first leg (something transferred) until then; Column 2 before it.
    is_col4 = is_non_dvp & (days >= _NON_DVP_COL4_LOWER)
    is_col3 = is_non_dvp & (days < _NON_DVP_COL4_LOWER) & (pl.col("value_transferred") > 0.0)

    # Art. 378: "where the difference could involve a loss for the credit
    # institution" — a seller loses when MV < agreed, a purchaser when MV >
    # agreed. An unknown side is charged the absolute difference, the larger of
    # the two readings (the input gate names the row, CCR031). Null on non-DvP.
    seller_loss = pl.col("agreed_settlement_price") - pl.col("current_market_value")
    side = pl.col("is_purchase")
    loss = (
        pl.when(side.eq_missing(True))
        .then(-seller_loss)
        .when(side.eq_missing(False))
        .then(seller_loss)
        .otherwise(seller_loss.abs())
    )
    price_difference = (
        pl.when(is_dvp)
        .then(pl.max_horizontal(loss, pl.lit(0.0)))
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
    # BOUNDS and the multipliers come from the rulepack (module level above).
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
    # multiplier (12.5) on Column 4 rows (RW 1250% => own_funds = exposure).
    # Column 3 is risk-weighted downstream, so it carries none here.
    multiplier_or_rw = (
        pl.when(is_dvp)
        .then(dvp_multiplier)
        .when(is_col4)
        .then(pl.lit(_NON_DVP_COL4_RW_MULTIPLIER))
        .when(is_col3)
        .then(pl.lit(None, dtype=pl.Float64))
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
        .when(is_dvp)
        .then(pl.lit("dvp_pre_t5"))
        .when(is_col4)
        .then(pl.lit("non_dvp_col4_t5_plus"))
        .when(is_col3)
        .then(pl.lit(_BAND_NON_DVP_COL3))
        .when(is_non_dvp)
        .then(pl.lit("non_dvp_col2"))
        .otherwise(pl.lit("unrecognised_settlement_type"))
        .alias("regulatory_band")
    )

    # Own-funds: DvP = price_difference * multiplier; Column 4 = exposure_amount
    # (1.0 factor against the full exposure); Column 3 = none (not an own-funds
    # amount — the exposure is risk-weighted downstream); otherwise 0.
    own_funds = (
        pl.when(is_dvp)
        .then(pl.col("price_difference") * dvp_multiplier)
        .when(is_col4)
        .then(pl.col("exposure_amount"))
        .when(is_col3)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.lit(0.0))
        .alias("own_funds_requirement")
    )

    # RWA: own_funds * 12.5 (CRR Art. 92(3)(ca)); null on Column 3 rows.
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


def failed_trade_exposure_rows(
    failed_trades: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Shape each failed trade into one synthetic ``ft__`` exposure row.

    Two kinds of row, one per trade:

    - An own-funds line (DvP, Column 4, Column 2, unrecognised type):
      ``drawn_amount = own_funds_requirement`` and ``risk_type =
      SETTLEMENT_FAILED_TRADE``, so the SA chain pins the risk weight to 12.5
      and RWEA = own funds x 12.5 (Art. 92(3)(ca)); the classifier keeps it SA
      and CRM gives it nothing (``engine/crm/own_funds_lines.py``).
    - A Column 3 free delivery: ``drawn_amount = exposure_amount`` (value
      transferred + current positive exposure) with no ``risk_type``, so it is
      classified, mitigated and risk-weighted like any drawn exposure to the
      counterparty — Art. 379(1) Table 2 "Treat as an exposure", Art. 379(2)
      SA or IRB. Its residual maturity is nil (value and maturity date are the
      reporting date), so a short-term institution weight applies where due.

    References:
        CRR Art. 378 + Table 1; CRR Art. 379(1) + Table 2, 379(2);
        CRR Art. 92(3)(ca).
    """
    computed = compute_failed_trade_rwa(failed_trades, config)
    is_col3 = pl.col("regulatory_band") == _BAND_NON_DVP_COL3
    reference = pl.concat_str([pl.lit(_ROW_PREFIX), pl.col("failed_trade_id")])
    return computed.select(
        reference.alias("exposure_reference"),
        # Reconciliation base: keep the ``ft__`` namespace (no legacy
        # per-exposure equivalent; avoids collision with a loan reference).
        reference.alias("source_exposure_reference"),
        pl.lit("ccr_failed_trade").alias("exposure_type"),
        pl.col("counterparty_reference"),
        pl.lit(config.reporting_date).alias("value_date"),
        pl.lit(config.reporting_date).alias("maturity_date"),
        pl.when(is_col3)
        .then(pl.col("exposure_amount"))
        .otherwise(pl.col("own_funds_requirement"))
        .alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.lit("senior").alias("seniority"),
        pl.when(is_col3)
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(pl.lit(RiskType.SETTLEMENT_FAILED_TRADE.value))
        .alias("risk_type"),
        pl.lit("failed_trade").alias("ccr_method"),
        # Audit columns reconciling the synthetic row back to Art. 378/379.
        pl.col("regulatory_band"),
        pl.col("multiplier_or_rw"),
        pl.col("own_funds_requirement"),
        pl.col("failed_trade_rwa"),
        pl.col("price_difference"),
        pl.col("exposure_amount"),
    )


__all__ = ["compute_failed_trade_rwa", "failed_trade_exposure_rows"]
