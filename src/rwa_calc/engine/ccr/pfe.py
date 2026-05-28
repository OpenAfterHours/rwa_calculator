"""
Potential Future Exposure (PFE) skeleton for SA-CCR.

Pipeline position:
    Classifier -> CCRCalculator (PFE) -> CRMProcessor

Key responsibilities:
- Aggregate per-trade adjusted-notional / delta / maturity-factor /
  supervisory-factor terms into per-netting-set add-ons and apply the
  PFE multiplier per CRR Art. 278.
- Per CRR Art. 277a(1)(a), aggregate per-bucket effective notionals
  D_b into per-asset-class add-ons using the supervisory cross-bucket
  correlation matrix.

This batch (P8.4) ships the stub signature only; the body lands across
P8.10 (sub-piece aggregation) and P8.16 (full PFE with multiplier).

References:
- CRR Art. 277a(1)(a): asset-class add-on cross-bucket aggregation.
- CRR Art. 278: Potential future exposure (multiplier + add-on)
- CRR Art. 280-280f: Asset-class add-ons (IR singleton path scoped here)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.contracts.config import CCRConfig
from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import TRADE_SCHEMA
from rwa_calc.data.tables.sa_ccr_factors import (
    PFE_AGGREGATE_DENOM_COEFF,
    PFE_MULTIPLIER_FLOOR_F,
    SA_CCR_CORRELATION_COMMODITY,
    SA_CCR_CORRELATION_CREDIT_IDX,
    SA_CCR_CORRELATION_CREDIT_SN,
    SA_CCR_CORRELATION_EQUITY_IDX,
    SA_CCR_CORRELATION_EQUITY_SN,
    SA_CCR_IR_BUCKET_CORRELATION_12,
    SA_CCR_IR_BUCKET_CORRELATION_13,
    SA_CCR_IR_BUCKET_CORRELATION_23,
    SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX,
    SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN,
    SA_CCR_SUPERVISORY_FACTOR_FX,
    SA_CCR_SUPERVISORY_FACTOR_IR,
    SA_CCR_SUPERVISORY_FACTORS_COMMODITY,
    SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX,
    SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN,
)

logger = logging.getLogger(__name__)


@cites("CRR Art. 278")
def compute_pfe(
    netting_sets: pl.LazyFrame,
    config: CCRConfig | None = None,
) -> pl.LazyFrame:
    """SA-CCR PFE multiplier and aggregate PFE per CRR Art. 278(3).

    Implements the netting-set-grain PFE composition layer:

        multiplier = min(1, F + (1 − F) × exp((V − C) / (2 × (1 − F) × AddOn_agg)))
        pfe_addon  = multiplier × AddOn_aggregate          (Art. 278(1))
        rc_unmarg  = max(V_net − C_net, 0)                 (Art. 275(1))
        ead_ccr    = α × (rc_unmarg + pfe_addon)           (Art. 274(2))

    where ``F = 0.05`` (``PFE_MULTIPLIER_FLOOR_F``) and the ``2`` in the
    denominator is ``PFE_AGGREGATE_DENOM_COEFF``. The ``min(1, ...)`` cap
    binds whenever ``V − C ≥ 0`` (over-collateralised / in-the-money).

    Args:
        netting_sets: LazyFrame at netting-set grain with at minimum
            ``v_net: Float64``, ``c_net: Float64`` and
            ``addon_aggregate: Float64`` columns.
        config: Optional CCRConfig; when provided ``config.alpha`` overrides
            the default α=1.4 (CRR Art. 274(2)).

    Returns:
        Input LazyFrame with four new columns:

        - ``pfe_multiplier: Float64`` — Art. 278(3) multiplier.
        - ``pfe_addon: Float64``      — Art. 278(1) PFE.
        - ``rc_unmargined: Float64``  — Art. 275(1) replacement cost.
        - ``ead_ccr: Float64``        — Art. 274(2) EAD at α = 1.4.

    References:
        CRR Art. 274(2); CRR Art. 275(1); CRR Art. 278(1)-(3);
        BCBS CRE52.20-23.
    """
    alpha_value = float(config.alpha) if config is not None else 1.4
    floor_f = float(PFE_MULTIPLIER_FLOOR_F)
    denom_coeff = float(PFE_AGGREGATE_DENOM_COEFF)
    one_minus_f = 1.0 - floor_f

    v_minus_c = pl.col("v_net") - pl.col("c_net")
    denom = denom_coeff * one_minus_f * pl.col("addon_aggregate")
    uncapped = floor_f + one_minus_f * (v_minus_c / denom).exp()

    return (
        netting_sets.with_columns(
            pl.min_horizontal(pl.lit(1.0), uncapped).alias("pfe_multiplier"),
        )
        .with_columns(
            [
                (pl.col("pfe_multiplier") * pl.col("addon_aggregate")).alias("pfe_addon"),
                pl.max_horizontal(v_minus_c, pl.lit(0.0)).alias("rc_unmargined"),
            ]
        )
        .with_columns(
            (pl.lit(alpha_value) * (pl.col("rc_unmargined") + pl.col("pfe_addon"))).alias("ead_ccr")
        )
    )


# Watchfire's bundled CRR index does not yet contain Art. 277a; collapse the
# ``@cites`` to the parent Art. 277 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 277")
def compute_addon_per_asset_class(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Per-asset-class SA-CCR add-on aggregated from per-trade effective notionals.

    Dispatches to asset-class-specific helpers and unions the results onto a
    keys frame that anchors every ``(netting_set_id, asset_class)`` combination
    present in the input. Asset classes without an implementation (credit /
    equity / commodity) keep their ``asset_class_addon`` as null — that's the
    contract callers downstream depend on.

    Implemented asset classes:

    - ``interest_rate``: three IR maturity buckets aggregated per Art. 277a(1)(a)
      via :func:`_compute_addon_ir`.
    - ``fx``: per-currency-pair hedging sets summed with no cross-set
      correlation per BCBS CRE52.55 via :func:`_compute_addon_fx`.
    - ``credit``: per-entity effective notionals aggregated inside a single
      credit hedging set via the supervisory-correlation formula per
      Art. 277a + Art. 280a via :func:`_compute_addon_credit`.
    - ``equity``: single hedging set per NS with SN/IDX sub-class aggregation
      per Art. 277a + Art. 280b via :func:`_compute_addon_equity`.
    - ``commodity``: five commodity buckets (ELECTRICITY / OIL_GAS / METALS /
      AGRICULTURAL / OTHER) with within-bucket correlation ρ=0.40
      (Art. 280c) and no cross-bucket correlation (CRE52.69) via
      :func:`_compute_addon_commodity`.

    Args:
        trades: LazyFrame at trade grain with at minimum ``netting_set_id``,
            ``asset_class``, ``hedging_set_id``, ``maturity_bucket``,
            ``supervisory_delta``, ``adjusted_notional`` and ``maturity_factor``
            columns.

    Returns:
        LazyFrame with one row per (``netting_set_id``, ``asset_class``)
        and columns ``netting_set_id``, ``asset_class``,
        ``asset_class_addon: Float64``.

    References:
        CRR Art. 277a(1)(a) (IR); CRR Art. 277(3)(a) + BCBS CRE52.55 (FX);
        CRR Art. 277(2)(c) + Art. 277a + Art. 280a (credit);
        CRR Art. 277(2)(d) + Art. 280b (equity);
        CRR Art. 277(3)(b) + Art. 280c + BCBS CRE52.67-69 (commodity);
        CRR Art. 280 Table 1/2 (SF_IR=0.5%, SF_FX=4%, SF_EQ_SN=32%, SF_EQ_IDX=20%,
            SF_CR by quality/index, SF_CM per bucket).
    """
    keys = trades.select(["netting_set_id", "asset_class"]).unique()

    ir_addon = _compute_addon_ir(trades).rename({"asset_class_addon": "_ir_addon"})
    fx_addon = _compute_addon_fx(trades).rename({"asset_class_addon": "_fx_addon"})
    credit_addon = _compute_addon_credit(trades).rename({"asset_class_addon": "_credit_addon"})
    eq_addon = _compute_addon_equity(trades).rename({"asset_class_addon": "_eq_addon"})
    co_addon = _compute_addon_commodity(trades).rename({"asset_class_addon": "_co_addon"})

    return (
        keys.join(ir_addon, on=["netting_set_id", "asset_class"], how="left")
        .join(fx_addon, on=["netting_set_id", "asset_class"], how="left")
        .join(credit_addon, on=["netting_set_id", "asset_class"], how="left")
        .join(eq_addon, on=["netting_set_id", "asset_class"], how="left")
        .join(co_addon, on=["netting_set_id", "asset_class"], how="left")
        .with_columns(
            pl.coalesce(
                pl.col("_ir_addon"),
                pl.col("_fx_addon"),
                pl.col("_credit_addon"),
                pl.col("_eq_addon"),
                pl.col("_co_addon"),
            ).alias("asset_class_addon")
        )
        .select(["netting_set_id", "asset_class", "asset_class_addon"])
    )


def _compute_addon_ir(trades: pl.LazyFrame) -> pl.LazyFrame:
    """IR asset-class add-on per CRR Art. 277a(1)(a).

    Aggregates per-trade effective notionals ``delta * d * MF`` into per-bucket
    sums ``D_b``, then composes the asset-class add-on via the three-bucket
    correlation matrix:

        AddOn_IR = SF_IR * sqrt(
            D_B1^2 + D_B2^2 + D_B3^2
            + 2 * rho_12 * D_B1 * D_B2
            + 2 * rho_23 * D_B2 * D_B3
            + 2 * rho_13 * D_B1 * D_B3
        )

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="interest_rate"``)
        with ``asset_class_addon: Float64``. Non-IR rows are filtered out.
    """
    rho_12 = float(SA_CCR_IR_BUCKET_CORRELATION_12)
    rho_23 = float(SA_CCR_IR_BUCKET_CORRELATION_23)
    rho_13 = float(SA_CCR_IR_BUCKET_CORRELATION_13)
    sf_ir = float(SA_CCR_SUPERVISORY_FACTOR_IR)

    ir_trades = trades.filter(pl.col("asset_class") == "interest_rate")

    # Per-trade effective notional = delta * d * MF (Art. 277a(1)(a)).
    trade_terms = ir_trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # D_b per (netting_set_id, asset_class, maturity_bucket).
    d_b = trade_terms.group_by(["netting_set_id", "asset_class", "maturity_bucket"]).agg(
        pl.col("effective_notional_trade").sum().alias("d_bucket")
    )

    # Pivot the three IR buckets into wide columns per (netting_set_id, asset_class).
    d_lt_1y = d_b.filter(pl.col("maturity_bucket") == "LT_1Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b1")]
    )
    d_1y_5y = d_b.filter(pl.col("maturity_bucket") == "1Y_5Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b2")]
    )
    d_gt_5y = d_b.filter(pl.col("maturity_bucket") == "GT_5Y").select(
        ["netting_set_id", "asset_class", pl.col("d_bucket").alias("d_b3")]
    )

    keys = ir_trades.select(["netting_set_id", "asset_class"]).unique()

    joined = (
        keys.join(d_lt_1y, on=["netting_set_id", "asset_class"], how="left")
        .join(d_1y_5y, on=["netting_set_id", "asset_class"], how="left")
        .join(d_gt_5y, on=["netting_set_id", "asset_class"], how="left")
        .with_columns(
            [
                pl.col("d_b1").fill_null(0.0),
                pl.col("d_b2").fill_null(0.0),
                pl.col("d_b3").fill_null(0.0),
            ]
        )
    )

    inner = (
        pl.col("d_b1") ** 2
        + pl.col("d_b2") ** 2
        + pl.col("d_b3") ** 2
        + 2.0 * rho_12 * pl.col("d_b1") * pl.col("d_b2")
        + 2.0 * rho_23 * pl.col("d_b2") * pl.col("d_b3")
        + 2.0 * rho_13 * pl.col("d_b1") * pl.col("d_b3")
    )

    return joined.with_columns((sf_ir * inner.sqrt()).alias("asset_class_addon")).select(
        ["netting_set_id", "asset_class", "asset_class_addon"]
    )


def _compute_addon_fx(trades: pl.LazyFrame) -> pl.LazyFrame:
    """FX asset-class add-on per CRR Art. 277a + BCBS CRE52.55.

    For each FX hedging set (one per currency pair within a netting set):

        D_HS     = sum_i ( delta_i * d_i * MF_i )  (signed within the HS)
        AddOn_HS = SF_FX * |D_HS|
        AddOn_FX = sum over HS of AddOn_HS              (no cross-HS correlation)

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="fx"``) with
        ``asset_class_addon: Float64``. Non-FX rows are filtered out.

    References:
        CRR Art. 277(3)(a) (FX hedging set = currency pair); CRR Art. 277a(2);
        BCBS CRE52.55 (FX asset-class aggregation is a simple sum).
    """
    sf_fx = float(SA_CCR_SUPERVISORY_FACTOR_FX)

    fx_trades = trades.filter(pl.col("asset_class") == "fx")

    trade_terms = fx_trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # D_HS = signed sum within hedging set (no internal cancellation across pairs).
    d_hs = trade_terms.group_by(["netting_set_id", "asset_class", "hedging_set_id"]).agg(
        pl.col("effective_notional_trade").sum().alias("d_hs")
    )

    # AddOn_HS = SF_FX * |D_HS|; sum across hedging sets to get AddOn_FX.
    return (
        d_hs.with_columns((sf_fx * pl.col("d_hs").abs()).alias("addon_hs"))
        .group_by(["netting_set_id", "asset_class"])
        .agg(pl.col("addon_hs").sum().alias("asset_class_addon"))
        .select(["netting_set_id", "asset_class", "asset_class_addon"])
    )


def _compute_addon_credit(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Credit asset-class add-on per CRR Art. 277(2)(c) + Art. 277a + Art. 280a.

    One hedging set per netting set for the credit asset class (Art. 277(2)(c)).
    Per (``netting_set_id``, ``reference_entity``, ``credit_quality``, ``is_index``):

        EN_entity    = sum_i ( delta_i * d_i * MF_i )       (signed within entity)
        SF_CR        = SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN[quality]   if not index
                       SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX[quality]  if is_index
        rho          = SA_CCR_CORRELATION_CREDIT_SN  (0.50) for single-name
                     = SA_CCR_CORRELATION_CREDIT_IDX (0.80) for indices
        AddOn_entity = SF_CR * EN_entity                    (signed)

    Per netting set (single credit HS per Art. 277(2)(c)):

        systematic    = ( sum_k rho_k * AddOn_entity_k )^2
        idiosyncratic = sum_k ( 1 - rho_k^2 ) * AddOn_entity_k^2
        AddOn_credit  = sqrt(systematic + idiosyncratic)

    Single-entity case collapses to SF x |EN| (sqrt(rho^2 + (1 - rho^2)) = 1).

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="credit"``) with
        ``asset_class_addon: Float64``. Non-credit rows are filtered out.

    References:
        CRR Art. 277(2)(c) (one credit HS per NS);
        CRR Art. 277a(1)(b) (credit aggregation);
        CRR Art. 280 Table 2 (SF_CR by quality / index);
        CRR Art. 280a (rho_CR = 0.50 SN / 0.80 IDX).
    """
    rho_sn = float(SA_CCR_CORRELATION_CREDIT_SN)
    rho_idx = float(SA_CCR_CORRELATION_CREDIT_IDX)
    sf_sn_ig = float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN["IG"])
    sf_sn_hy = float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN["HY"])
    sf_sn_nr = float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN["NON_RATED"])
    sf_idx_ig = float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX["IG"])
    sf_idx_hy = float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX["HY"])

    # Defensive: upstream IR / FX call-sites pre-date the credit branch and
    # may pass frames without the credit-specific discriminator columns. Inject
    # them as all-null so the lazy plan resolves; the ``asset_class == credit``
    # filter discards them anyway. Mirrors the ``commodity_type`` pattern in
    # ``assign_hedging_set``.
    schema_names = trades.collect_schema().names()
    if "reference_entity" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Utf8).alias("reference_entity"))
    if "credit_quality" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Utf8).alias("credit_quality"))
    if "is_index" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Boolean).alias("is_index"))

    cr_trades = trades.filter(pl.col("asset_class") == "credit")

    # Per-trade effective notional = delta * d * MF (Art. 277a(1)(b)).
    trade_terms = cr_trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # EN_entity = signed sum within (NS, entity, quality, is_index) group.
    en_entity = trade_terms.group_by(
        ["netting_set_id", "asset_class", "reference_entity", "credit_quality", "is_index"]
    ).agg(pl.col("effective_notional_trade").sum().alias("en_entity"))

    # SF_CR by (is_index, credit_quality).
    sf_cr = (
        pl.when(pl.col("is_index").fill_null(False) & (pl.col("credit_quality") == "IG"))
        .then(pl.lit(sf_idx_ig))
        .when(pl.col("is_index").fill_null(False) & (pl.col("credit_quality") == "HY"))
        .then(pl.lit(sf_idx_hy))
        .when(pl.col("credit_quality") == "IG")
        .then(pl.lit(sf_sn_ig))
        .when(pl.col("credit_quality") == "HY")
        .then(pl.lit(sf_sn_hy))
        .when(pl.col("credit_quality") == "NON_RATED")
        .then(pl.lit(sf_sn_nr))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )

    # rho by single-name vs index (Art. 280a).
    rho = (
        pl.when(pl.col("is_index").fill_null(False)).then(pl.lit(rho_idx)).otherwise(pl.lit(rho_sn))
    )

    # AddOn_entity = SF_CR * EN_entity (signed).
    per_entity = en_entity.with_columns(
        [
            (sf_cr * pl.col("en_entity")).alias("addon_entity"),
            rho.alias("rho_entity"),
        ]
    )

    # Aggregate to NS via Art. 277a(1)(b) systematic + idiosyncratic formula.
    per_ns = per_entity.group_by(["netting_set_id", "asset_class"]).agg(
        [
            (pl.col("rho_entity") * pl.col("addon_entity")).sum().alias("_sys_inner"),
            ((1.0 - pl.col("rho_entity") ** 2) * pl.col("addon_entity") ** 2)
            .sum()
            .alias("_idiosyncratic"),
        ]
    )

    return per_ns.with_columns(
        (pl.col("_sys_inner") ** 2 + pl.col("_idiosyncratic")).sqrt().alias("asset_class_addon")
    ).select(["netting_set_id", "asset_class", "asset_class_addon"])


def _compute_addon_commodity(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Commodity asset-class add-on per CRR Art. 277(3)(b) + Art. 277a + Art. 280c.

    Per-bucket aggregation across the five commodity buckets
    (ELECTRICITY / OIL_GAS / METALS / AGRICULTURAL / OTHER):

        e_i           = δ_i × d_i × MF_i                          (per trade)
        D_b           = sum_i e_i within bucket b                 (signed sum)
        sum_e2_b      = sum_i e_i²
        AddOn_b       = SF_CM[b] × sqrt(ρ² × D_b² + (1−ρ²) × sum_e2_b)
        AddOn_commod  = sqrt(sum_b AddOn_b²)                      (CRE52.69)

    where ρ = 0.40 within-bucket (Art. 280c / CRE52.68) and SF_CM[b] is the
    bucket-specific supervisory factor from Art. 280 Table 2
    (ELECTRICITY=0.40, OIL_GAS/METALS/AGRICULTURAL/OTHER=0.18).

    Critical: ``commodity_type`` values are UPPER-CASE per the schema enum at
    ``schemas.py`` COLUMN_VALUE_CONSTRAINTS. Rows with null commodity_type are
    filtered out (no implicit fallback to the OTHER bucket) — that means a
    netting set whose only commodity rows have null commodity_type emits a
    null asset_class_addon.

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="commodity"``)
        with ``asset_class_addon: Float64``. Non-commodity rows are filtered out.

    References:
        CRR Art. 277(3)(b) (5 buckets); CRR Art. 277a(1) (intra-class agg);
        CRR Art. 280c (within-bucket ρ=0.40, no cross-bucket); CRR Art. 280
        Table 2 (SF_CM per bucket); BCBS CRE52.67-69.
    """
    rho = float(SA_CCR_CORRELATION_COMMODITY)
    rho2 = rho * rho
    one_minus_rho2 = 1.0 - rho2

    # Build SF_CM lookup as a LazyFrame keyed on commodity_type (UPPER-CASE
    # bucket names) so we can join rather than chain when/then ladders.
    sf_cm_lookup = pl.LazyFrame(
        {
            "commodity_type": list(SA_CCR_SUPERVISORY_FACTORS_COMMODITY.keys()),
            "_sf_cm": [float(v) for v in SA_CCR_SUPERVISORY_FACTORS_COMMODITY.values()],
        },
        schema={"commodity_type": pl.Utf8, "_sf_cm": pl.Float64},
    )

    # Defensive: upstream IR / FX / equity callers may pass frames without a
    # commodity_type column or with the column inferred as null dtype (when
    # the only rows are non-commodity with None). Coerce to Utf8 so the
    # downstream join against sf_cm_lookup's String key resolves cleanly.
    trades = ensure_columns(trades, {"commodity_type": TRADE_SCHEMA["commodity_type"]})
    schema = trades.collect_schema()
    if schema["commodity_type"] != pl.Utf8:
        trades = trades.with_columns(pl.col("commodity_type").cast(pl.Utf8))

    # Commodity rows with a populated commodity_type only — null commodity_type
    # does not fall back to OTHER per the regulatory contract.
    co_trades = trades.filter(
        (pl.col("asset_class") == "commodity") & pl.col("commodity_type").is_not_null()
    )

    # Per-trade effective notional e_i = δ × d × MF (Art. 277a(1)).
    trade_terms = co_trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # Bucket-level aggregates D_b (signed sum) and sum_e2_b (sum of squares).
    d_b = trade_terms.group_by(["netting_set_id", "asset_class", "commodity_type"]).agg(
        [
            pl.col("effective_notional_trade").sum().alias("d_bucket"),
            (pl.col("effective_notional_trade") ** 2).sum().alias("sum_e2_bucket"),
        ]
    )

    # AddOn_b = SF_CM[b] × sqrt(ρ² × D_b² + (1−ρ²) × sum_e2_b).
    with_sf = d_b.join(sf_cm_lookup, on="commodity_type", how="left").with_columns(
        (
            pl.col("_sf_cm")
            * (rho2 * pl.col("d_bucket") ** 2 + one_minus_rho2 * pl.col("sum_e2_bucket")).sqrt()
        ).alias("addon_bucket")
    )

    # AddOn_commodity = sqrt(sum_b AddOn_b²) — no cross-bucket correlation.
    return (
        with_sf.group_by(["netting_set_id", "asset_class"])
        .agg((pl.col("addon_bucket") ** 2).sum().sqrt().alias("asset_class_addon"))
        .select(["netting_set_id", "asset_class", "asset_class_addon"])
    )


def _compute_addon_equity(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Equity asset-class add-on per CRR Art. 277a + Art. 280b.

    Per Art. 277(2)(d) there is one hedging set per asset class per netting
    set. Within that hedging set, single-name (``is_index=False``) and index
    (``is_index=True``) trades form two sub-classes; per Art. 280b there is
    no cross-sub-class correlation, so the two sub-class add-ons are summed.

    Within each (``netting_set_id``, ``is_index``) sub-class:

        EN_i  = supervisory_delta_i * adjusted_notional_i * MF_i  (per trade)
        D_k   = sum of EN_i for each distinct ``reference_entity`` k
        sum_D = sum_k D_k
        sum_D_sq = sum_k D_k^2

        AddOn_HS = SF * sqrt((rho * sum_D)^2 + (1 - rho^2) * sum_D_sq)

    where:

        is_index=False: SF = SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN  (0.32)
                        rho = SA_CCR_CORRELATION_EQUITY_SN        (0.50)
        is_index=True:  SF = SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX (0.20)
                        rho = SA_CCR_CORRELATION_EQUITY_IDX       (0.80)

    Mixed SN + IDX in the same NS sums two sub-class add-ons.

    Returns:
        LazyFrame keyed on (``netting_set_id``, ``asset_class="equity"``)
        with ``asset_class_addon: Float64``. Non-equity rows are filtered out.

    References:
        CRR Art. 277(2)(d); CRR Art. 277a; CRR Art. 280 Table 2;
        CRR Art. 280b; BCBS CRE52.65-66.
    """
    sf_sn = float(SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN)
    sf_idx = float(SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX)
    rho_sn = float(SA_CCR_CORRELATION_EQUITY_SN)
    rho_idx = float(SA_CCR_CORRELATION_EQUITY_IDX)

    # Defensive: upstream frames that pre-date the equity branch (e.g. FX/IR-
    # only acceptance tests) may not carry ``is_index`` / ``reference_entity``.
    # Both columns are required only for equity rows; treat missing ones as
    # all-null so the equity filter below resolves to an empty frame for the
    # non-equity workloads. Polars evaluates the dispatch ladder eagerly at
    # plan-resolve time, so the columns must exist on the schema.
    schema_names = trades.collect_schema().names()
    if "is_index" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Boolean).alias("is_index"))
    if "reference_entity" not in schema_names:
        trades = trades.with_columns(pl.lit(None, dtype=pl.Utf8).alias("reference_entity"))

    eq_trades = trades.filter(pl.col("asset_class") == "equity")

    # Per-trade effective notional EN_i = delta * d * MF.
    trade_terms = eq_trades.with_columns(
        (
            pl.col("supervisory_delta") * pl.col("adjusted_notional") * pl.col("maturity_factor")
        ).alias("effective_notional_trade")
    )

    # D_k per (netting_set_id, is_index, reference_entity): collapse same-entity
    # trades into a single signed sum before the sqrt step (Art. 277a entity
    # aggregation).
    d_k = trade_terms.group_by(
        ["netting_set_id", "asset_class", "is_index", "reference_entity"]
    ).agg(pl.col("effective_notional_trade").sum().alias("d_k"))

    # Per (NS, is_index) sub-class: sum_D, sum_D_sq, and the supervisory
    # factor / correlation selected by ``is_index``.
    sf_expr = pl.when(pl.col("is_index")).then(pl.lit(sf_idx)).otherwise(pl.lit(sf_sn))
    rho_expr = pl.when(pl.col("is_index")).then(pl.lit(rho_idx)).otherwise(pl.lit(rho_sn))

    sub_class = d_k.group_by(["netting_set_id", "asset_class", "is_index"]).agg(
        [
            pl.col("d_k").sum().alias("sum_d"),
            (pl.col("d_k") ** 2).sum().alias("sum_d_sq"),
        ]
    )

    sub_class_addon = sub_class.with_columns(
        [sf_expr.alias("_sf"), rho_expr.alias("_rho")]
    ).with_columns(
        (
            pl.col("_sf")
            * (
                (pl.col("_rho") * pl.col("sum_d")) ** 2
                + (1.0 - pl.col("_rho") ** 2) * pl.col("sum_d_sq")
            ).sqrt()
        ).alias("addon_sub_class")
    )

    # AddOn_EQ = sum over sub-classes (SN + IDX) within each NS — Art. 280b.
    return (
        sub_class_addon.group_by(["netting_set_id", "asset_class"])
        .agg(pl.col("addon_sub_class").sum().alias("asset_class_addon"))
        .select(["netting_set_id", "asset_class", "asset_class_addon"])
    )
