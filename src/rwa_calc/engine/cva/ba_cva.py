"""
Basic Approach to CVA risk (BA-CVA) — PRA PS1/26 CVA Part Ch.4.

Pipeline position:
    OutputAggregator -> CVA stage (engine/stages/cva.py) -> AggregatedResultBundle

Key responsibilities:
- Compute the portfolio-level CVA risk-weighted exposure amount (RWEA_CVA).

  Reduced version (no eligible CVA hedges, PS1/26 4.2-4.4):

      DF_NS     = (1 - e^(-rate.M_NS)) / (rate.M_NS)        (PS1/26 4.3, rate=0.05)
      SCVA_c    = (1/alpha) . RW_c . SUM_NS[ M_NS . EAD_NS . DF_NS ]   (PS1/26 4.3)
      K_reduced = sqrt[ (rho.SUM_c SCVA_c)^2 + (1-rho^2).SUM_c SCVA_c^2 ] (PS1/26 4.2)
      OFR_CVA   = DS_BA-CVA . K_reduced                     (PS1/26 4.2, DS=0.65)
      RWEA_CVA  = OFR_CVA . 12.5                            (PS1/26 Own Funds 4(b))

  Full version (eligible CVA hedges present, PS1/26 4.5-4.10):

      SNH_c     = SUM_{h in c}[ r_hc . RW_h . M_h . B_h . DF_h ]  (PS1/26 4.7, NO 1/alpha)
      HMA_c     = SUM_{h in c}[ (1 - r_hc^2) . (RW_h . M_h . B_h . DF_h)^2 ]  (PS1/26 4.9)
      IH        = SUM_i[ (RW_i.0.70) . M_i . B_i . DF_i ]   (PS1/26 4.8, index hedges)
      K_hedged  = sqrt[ (rho.SUM_c(SCVA_c-SNH_c) - IH)^2
                        + (1-rho^2).SUM_c(SCVA_c-SNH_c)^2 + SUM_c HMA_c ]  (PS1/26 4.6)
      K_full    = beta.K_reduced + (1-beta).K_hedged        (PS1/26 4.5, beta=0.25)
      OFR_CVA   = DS_BA-CVA . K_full                        (PS1/26 4.5, DS=0.65)
      RWEA_CVA  = OFR_CVA . 12.5                            (PS1/26 Own Funds 4(b))

- Read every supervisory parameter (DS_BA-CVA, rho, beta, the discount rate,
  alpha, the sector x credit-quality RW table, the r_hc correlation table, the
  index diversification factor, the own-funds -> RWA factor) from the resolved
  rulepack — no engine module-scope regulatory scalars or string-enum
  collections.

The CVA stage joins the BA-CVA counterparty frame onto the SA-CCR synthetic
exposure rows (``exposure_reference`` like ``ccr__<ns_id>``) so EAD_NS is the
same ``ead_final`` the rest of the pipeline carries — the BA-CVA charge is
computed off the live SA-CCR EAD, not a hand-coded value. CVA hedges (when
present) are matched to counterparties via ``counterparty_reference``.

CRITICAL: SNH_c (PS1/26 4.7) carries NO (1/alpha) factor, unlike SCVA_c (4.3).

References:
- PRA PS1/26 CVA Part 4.2 (reduced BA-CVA; DS_BA-CVA = 0.65; rho = 50%).
- PRA PS1/26 CVA Part 4.3 (SCVA_c; DF_NS supervisory discount factor; alpha).
- PRA PS1/26 CVA Part 4.4 (supervisory CVA risk weights, sector x IG/HY-NR).
- PRA PS1/26 CVA Part 4.5 (full BA-CVA; beta = 0.25; K_full blend; page 401).
- PRA PS1/26 CVA Part 4.6 (K_hedged formula; page 401).
- PRA PS1/26 CVA Part 4.7 (SNH_c formula — NO 1/alpha; DF_h; page 402).
- PRA PS1/26 CVA Part 4.8 (IH index-hedge term; 0.70 diversification; page 403).
- PRA PS1/26 CVA Part 4.9 (HMA_c indirect-hedge misalignment; page 403).
- PRA PS1/26 CVA Part 4.10 (r_hc single-name supervisory correlation; page 403).
- PRA PS1/26 Own Funds Part 4(b) (own-funds -> RWEA multiplier = 12.5).
- CRR Art. 274(2) (SA-CCR alpha = 1.4 sourced from the common pack).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple, cast

import polars as pl

from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

import logging

logger = logging.getLogger(__name__)


class BaCvaResult(NamedTuple):
    """Outcome of a BA-CVA portfolio computation.

    Attributes:
        rwea: Portfolio RWEA_CVA, or ``None`` when there is nothing to charge.
        hedges_recognised: ``True`` when at least one eligible CVA hedge fed the
            full-K path (PS1/26 4.5), ``False`` for the reduced path. Carries the
            single discriminator used by the aggregation roll-up so the
            reduced-vs-full distinction is not re-derived in two places.
    """

    rwea: float | None
    hedges_recognised: bool


def compute_ba_cva_rwa(
    cva_counterparties: pl.LazyFrame,
    ccr_exposures: pl.LazyFrame,
    pack: ResolvedRulepack,
    cva_hedges: pl.LazyFrame | None = None,
) -> BaCvaResult:
    """Compute the BA-CVA portfolio RWEA_CVA (reduced or full version).

    Args:
        cva_counterparties: BA-CVA counterparty inputs
            (``CVA_COUNTERPARTY_SCHEMA``) — one row per in-scope counterparty,
            carrying ``counterparty_reference``, ``cva_rw_sector``,
            ``cva_rw_rating_band``, ``cva_effective_maturity_years`` (M_NS) and
            ``cva_in_scope``.
        ccr_exposures: The aggregated results frame restricted (by the caller)
            to the SA-CCR netting-set rows that carry ``ead_final`` and a
            ``counterparty_reference``. The CVA frame is joined onto these so
            EAD_NS is the live SA-CCR EAD.
        pack: The run's resolved rulepack. Sources DS_BA-CVA, rho, beta, the
            discount rate, alpha, the supervisory RW table, the r_hc correlation
            table, the index diversification factor and the own-funds -> RWA
            factor.
        cva_hedges: Optional full BA-CVA hedge inputs (``CVA_HEDGE_SCHEMA``).
            When ``None`` the reduced BA-CVA charge is returned (verbatim
            no-hedge path). When eligible hedges are present the full BA-CVA
            path runs; an all-ineligible hedge frame collapses to the reduced
            result (K_hedged contributions are all zero).

    Returns:
        A :class:`BaCvaResult` carrying the portfolio RWEA_CVA (``None`` when no
        in-scope counterparty has any matching netting-set EAD) and the
        ``hedges_recognised`` flag (``True`` when at least one eligible hedge fed
        the full-K path, ``False`` for the reduced path).

    References:
        PRA PS1/26 CVA Part 4.2-4.10; Own Funds Part 4(b); CRR Art. 274(2).
    """
    ds_ba_cva = scalar_value(pack.scalar_param("ds_ba_cva"))
    rho = scalar_value(pack.scalar_param("cva_ba_supervisory_correlation"))
    discount_rate = scalar_value(pack.scalar_param("cva_ba_supervisory_discount_rate"))
    alpha = scalar_value(pack.scalar_param("sa_ccr_alpha"))
    own_funds_to_rwa = scalar_value(pack.scalar_param("own_funds_to_rwa_factor"))

    rw_rows, rw_default = _supervisory_rw_rows(pack)

    # SCVA_c per counterparty from the live SA-CCR EAD (PS1/26 4.3).
    scva = _scva_per_counterparty(
        cva_counterparties, ccr_exposures, rw_rows, rw_default, alpha, discount_rate
    )

    # Reduced path when no hedge frame is supplied OR every supplied hedge is
    # ineligible (an all-ineligible frame collapses to reduced math, PS1/26 4.5
    # "eligible BA-CVA hedges"). ``hedges_recognised`` carries this single
    # discriminator so the aggregation roll-up never re-derives it.
    hedges_recognised = cva_hedges is not None and _has_eligible_hedge(cva_hedges)

    if not hedges_recognised:
        # Reduced version — SUM SCVA_c terms only (PS1/26 4.2).
        aggregate = _collect_sums(
            scva.select(
                sum_scva=pl.col("_scva_c").sum(),
                sum_scva_sq=(pl.col("_scva_c") ** 2).sum(),
            )
        )
        if aggregate is None:
            return BaCvaResult(rwea=None, hedges_recognised=False)
        sum_scva = float(aggregate.item(0, "sum_scva") or 0.0)
        sum_scva_sq = float(aggregate.item(0, "sum_scva_sq") or 0.0)
        k_reduced = math.sqrt((rho * sum_scva) ** 2 + (1.0 - rho**2) * sum_scva_sq)
        return BaCvaResult(
            rwea=_rwea_or_none(ds_ba_cva * k_reduced * own_funds_to_rwa),
            hedges_recognised=False,
        )

    # Full version (PS1/26 4.5-4.10).
    rwea = _full_rwea(
        scva,
        cast("pl.LazyFrame", cva_hedges),
        pack,
        rw_rows,
        rw_default,
        rho,
        ds_ba_cva,
        own_funds_to_rwa,
        discount_rate,
    )
    return BaCvaResult(rwea=rwea, hedges_recognised=rwea is not None)


# ---------------------------------------------------------------------------
# Supporting functions
# ---------------------------------------------------------------------------


def _supervisory_rw_rows(pack: ResolvedRulepack) -> tuple[dict[tuple[str, str], float], float]:
    """Return the (sector, rating_band) -> RW map and the default RW.

    The Decimal -> float boundary lives here (PS1/26 4.4 supervisory RW table).
    """
    rw_table = pack.decision("cva_ba_supervisory_risk_weights")
    rw_default = float(rw_table.default) if rw_table.default is not None else 0.0
    rw_rows = {
        (str(sector), str(band)): float(value) for (sector, band), value in rw_table.rows
    }
    return rw_rows, rw_default


def _scva_per_counterparty(
    cva_counterparties: pl.LazyFrame,
    ccr_exposures: pl.LazyFrame,
    rw_rows: dict[tuple[str, str], float],
    rw_default: float,
    alpha: float,
    discount_rate: float,
) -> pl.LazyFrame:
    """SCVA_c = (1/alpha) . RW_c . SUM_NS[ M_NS . EAD_NS . DF_NS ] (PS1/26 4.3)."""
    rw_frame = pl.LazyFrame(
        {
            "cva_rw_sector": [sector for sector, _ in rw_rows],
            "cva_rw_rating_band": [band for _, band in rw_rows],
            "_cva_rw_c": list(rw_rows.values()),
        }
    )

    m_ns = pl.col("cva_effective_maturity_years")
    df_ns = (1.0 - (-discount_rate * m_ns).exp()) / (discount_rate * m_ns)
    per_ns_term = (
        m_ns * pl.coalesce(pl.col("ead_final"), pl.lit(0.0)) * df_ns
    ).alias("_cva_ns_term")

    in_scope = cva_counterparties.filter(pl.col("cva_in_scope")).select(
        "counterparty_reference",
        "cva_rw_sector",
        "cva_rw_rating_band",
        "cva_effective_maturity_years",
    )

    return (
        ccr_exposures.select("counterparty_reference", "ead_final")
        .join(in_scope, on="counterparty_reference", how="inner")
        .join(rw_frame, on=["cva_rw_sector", "cva_rw_rating_band"], how="left")
        .with_columns(pl.coalesce(pl.col("_cva_rw_c"), pl.lit(rw_default)).alias("_cva_rw_c"))
        .with_columns(per_ns_term)
        .group_by("counterparty_reference")
        .agg(
            ((1.0 / alpha) * pl.first("_cva_rw_c") * pl.col("_cva_ns_term").sum()).alias(
                "_scva_c"
            )
        )
    )


def _full_rwea(
    scva: pl.LazyFrame,
    cva_hedges: pl.LazyFrame,
    pack: ResolvedRulepack,
    rw_rows: dict[tuple[str, str], float],
    rw_default: float,
    rho: float,
    ds_ba_cva: float,
    own_funds_to_rwa: float,
    discount_rate: float,
) -> float | None:
    """RWEA_CVA = DS_BA-CVA . K_full . 12.5 with K_full = beta.K_reduced +
    (1-beta).K_hedged (PS1/26 4.5-4.10; Own Funds 4(b)).

    All portfolio sums (SCVA_c, SNH_c, HMA_c, IH) are aggregated in a single
    lazy plan and materialised once; the K_hedged / K_full arithmetic runs in
    Python on the resulting scalars.
    """
    beta = scalar_value(pack.scalar_param("cva_ba_beta"))
    index_factor = scalar_value(pack.scalar_param("cva_ba_index_diversification_factor"))
    r_hc_rows, r_hc_default = _hedge_correlation_rows(pack)

    # Common hedge metric H = RW_h . M_h . B_h . DF_h (PS1/26 4.7/4.9), only on
    # eligible hedges (PS1/26 4.5 — "eligible BA-CVA hedges").
    m_h = pl.col("cva_hedge_residual_maturity_years")
    df_h = (1.0 - (-discount_rate * m_h).exp()) / (discount_rate * m_h)
    rw_h = _hedge_rw_expr(rw_rows, rw_default)
    hedges = cva_hedges.filter(pl.col("cva_hedge_eligible")).with_columns(
        (rw_h * m_h * pl.col("cva_hedge_notional") * df_h).alias("_h_metric")
    )

    # Single-name hedges: SNH_c and HMA_c per counterparty (PS1/26 4.7/4.9).
    r_hc = _hedge_correlation_expr(r_hc_rows, r_hc_default)
    single_name = (
        hedges.filter(pl.col("cva_hedge_type") == "SINGLE_NAME")
        .with_columns(r_hc.alias("_r_hc"))
        .group_by("counterparty_reference")
        .agg(
            (pl.col("_r_hc") * pl.col("_h_metric")).sum().alias("_snh_c"),
            ((1.0 - pl.col("_r_hc") ** 2) * pl.col("_h_metric") ** 2).sum().alias("_hma_c"),
        )
    )

    # net_c = SCVA_c - SNH_c, plus HMA_c, per counterparty.
    net = (
        scva.join(single_name, on="counterparty_reference", how="left")
        .with_columns(
            (pl.col("_scva_c") - pl.coalesce(pl.col("_snh_c"), pl.lit(0.0))).alias("_net_c"),
            pl.coalesce(pl.col("_hma_c"), pl.lit(0.0)).alias("_hma_c"),
        )
        .select(
            sum_net=pl.col("_net_c").sum(),
            sum_net_sq=(pl.col("_net_c") ** 2).sum(),
            sum_hma=pl.col("_hma_c").sum(),
            sum_scva=pl.col("_scva_c").sum(),
            sum_scva_sq=(pl.col("_scva_c") ** 2).sum(),
        )
    )

    # IH = SUM_i[ (RW_i.0.70) . M_i . B_i . DF_i ] over index hedges (PS1/26 4.8).
    index_term = hedges.filter(pl.col("cva_hedge_type") == "INDEX").select(
        ih=(index_factor * pl.col("_h_metric")).sum()
    )

    # Materialise every portfolio sum in one collect.
    aggregate = _collect_sums(pl.concat([net, index_term], how="horizontal"))
    if aggregate is None:
        return None

    sum_net = float(aggregate.item(0, "sum_net") or 0.0)
    sum_net_sq = float(aggregate.item(0, "sum_net_sq") or 0.0)
    sum_hma = float(aggregate.item(0, "sum_hma") or 0.0)
    sum_scva = float(aggregate.item(0, "sum_scva") or 0.0)
    sum_scva_sq = float(aggregate.item(0, "sum_scva_sq") or 0.0)
    ih = float(aggregate.item(0, "ih") or 0.0)

    # K_hedged (PS1/26 4.6) and K_reduced (PS1/26 4.2).
    k_hedged = math.sqrt(
        (rho * sum_net - ih) ** 2 + (1.0 - rho**2) * sum_net_sq + sum_hma
    )
    k_reduced = math.sqrt((rho * sum_scva) ** 2 + (1.0 - rho**2) * sum_scva_sq)

    # K_full and RWEA_CVA (PS1/26 4.5; Own Funds 4(b)).
    k_full = beta * k_reduced + (1.0 - beta) * k_hedged
    return _rwea_or_none(ds_ba_cva * k_full * own_funds_to_rwa)


def _hedge_correlation_rows(pack: ResolvedRulepack) -> tuple[dict[str, float], float]:
    """Return the correlation-band -> r_hc map and the default r_hc (PS1/26 4.10)."""
    table = pack.decision("cva_ba_single_name_hedge_correlation")
    default = float(table.default) if table.default is not None else 0.0
    rows = {str(keys[0]): float(value) for keys, value in table.rows}
    return rows, default


def _hedge_rw_expr(rw_rows: dict[tuple[str, str], float], rw_default: float) -> pl.Expr:
    """Map (cva_hedge_rw_sector, cva_hedge_rw_rating_band) -> RW_h (PS1/26 4.4)."""
    expr = pl.lit(rw_default, dtype=pl.Float64)
    sector = pl.col("cva_hedge_rw_sector")
    band = pl.col("cva_hedge_rw_rating_band")
    for (s, b), value in rw_rows.items():
        expr = pl.when((sector == s) & (band == b)).then(pl.lit(value)).otherwise(expr)
    return expr


def _hedge_correlation_expr(rows: dict[str, float], default: float) -> pl.Expr:
    """Map cva_hedge_correlation_band -> r_hc (PS1/26 4.10)."""
    expr = pl.lit(default, dtype=pl.Float64)
    band = pl.col("cva_hedge_correlation_band")
    for key, value in rows.items():
        expr = pl.when(band == key).then(pl.lit(value)).otherwise(expr)
    return expr


def _collect_sums(plan: pl.LazyFrame) -> pl.DataFrame | None:
    """Materialise a single-row portfolio-sum plan; the sole engine collect here.

    Both the reduced (SUM SCVA_c) and full (SUM net_c / HMA_c / IH) aggregates
    funnel through this one materialisation boundary, keeping the eager-collect
    surface flat. Returns ``None`` when the plan yields no rows (no in-scope
    counterparty with matching EAD).
    """
    out = cast(pl.DataFrame, plan.collect())
    return out if out.height else None


def _rwea_or_none(value: float) -> float | None:
    """Return a strictly-positive RWEA, else ``None`` (nothing to charge)."""
    if value is None or value <= 0.0:
        return None
    return float(value)


def _has_eligible_hedge(cva_hedges: pl.LazyFrame) -> bool:
    """Whether at least one hedge row passes the eligibility filter (PS1/26 4.5).

    Mirrors the exact ``cva_hedge_eligible`` filter applied in ``_full_rwea`` so
    the full-vs-reduced discriminator is defined once. An all-ineligible frame
    collapses to the reduced path.
    """
    eligible = _collect_sums(
        cva_hedges.filter(pl.col("cva_hedge_eligible")).select(
            n=pl.len().cast(pl.Int64)
        )
    )
    if eligible is None:
        return False
    return int(eligible.item(0, "n") or 0) > 0


__all__ = ["BaCvaResult", "compute_ba_cva_rwa"]
