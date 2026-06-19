"""
Basic Approach to CVA risk (BA-CVA, reduced version) — PRA PS1/26 CVA Part Ch.4.

Pipeline position:
    OutputAggregator -> CVA stage (engine/stages/cva.py) -> AggregatedResultBundle

Key responsibilities:
- Compute the portfolio-level CVA risk-weighted exposure amount (RWEA_CVA) for
  the reduced version of BA-CVA (a firm that uses no eligible CVA hedges):

      DF_NS     = (1 - e^(-rate.M_NS)) / (rate.M_NS)        (PS1/26 4.3, rate=0.05)
      SCVA_c    = (1/alpha) . RW_c . SUM_NS[ M_NS . EAD_NS . DF_NS ]   (PS1/26 4.3)
      K_reduced = sqrt[ (rho.SUM_c SCVA_c)^2 + (1-rho^2).SUM_c SCVA_c^2 ] (PS1/26 4.2)
      OFR_CVA   = DS_BA-CVA . K_reduced                     (PS1/26 4.2, DS=0.65)
      RWEA_CVA  = OFR_CVA . 12.5                            (PS1/26 Own Funds 4(b))

- Read every supervisory parameter (DS_BA-CVA, rho, the discount rate, alpha,
  the sector x credit-quality RW table, the own-funds -> RWA factor) from the
  resolved rulepack — no engine module-scope regulatory scalars or string-enum
  collections.

The CVA stage joins the BA-CVA counterparty frame onto the SA-CCR synthetic
exposure rows (``exposure_reference`` like ``ccr__<ns_id>``) so EAD_NS is the
same ``ead_final`` the rest of the pipeline carries — the BA-CVA charge is
computed off the live SA-CCR EAD, not a hand-coded value.

References:
- PRA PS1/26 CVA Part 4.2 (reduced BA-CVA; DS_BA-CVA = 0.65; rho = 50%).
- PRA PS1/26 CVA Part 4.3 (SCVA_c; DF_NS supervisory discount factor; alpha).
- PRA PS1/26 CVA Part 4.4 (supervisory CVA risk weights, sector x IG/HY-NR).
- PRA PS1/26 Own Funds Part 4(b) (own-funds -> RWEA multiplier = 12.5).
- CRR Art. 274(2) (SA-CCR alpha = 1.4 sourced from the common pack).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

import logging

logger = logging.getLogger(__name__)


def compute_ba_cva_rwa(
    cva_counterparties: pl.LazyFrame,
    ccr_exposures: pl.LazyFrame,
    pack: ResolvedRulepack,
) -> float | None:
    """Compute the reduced BA-CVA portfolio RWEA_CVA.

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
        pack: The run's resolved rulepack. Sources DS_BA-CVA, rho, the
            discount rate, alpha, the supervisory RW table and the own-funds ->
            RWA factor.

    Returns:
        The portfolio RWEA_CVA as a ``float``, or ``None`` when no in-scope
        counterparty has any matching netting-set EAD (nothing to charge).

    References:
        PRA PS1/26 CVA Part 4.2-4.4; Own Funds Part 4(b); CRR Art. 274(2).
    """
    ds_ba_cva = scalar_value(pack.scalar_param("ds_ba_cva"))
    rho = scalar_value(pack.scalar_param("cva_ba_supervisory_correlation"))
    discount_rate = scalar_value(pack.scalar_param("cva_ba_supervisory_discount_rate"))
    alpha = scalar_value(pack.scalar_param("sa_ccr_alpha"))
    own_funds_to_rwa = scalar_value(pack.scalar_param("own_funds_to_rwa_factor"))

    # Supervisory RW_c table: (sector, rating_band) -> Decimal RW. Build a tiny
    # keyed frame to join against (the Decimal->float boundary lives here).
    rw_table = pack.decision("cva_ba_supervisory_risk_weights")
    rw_default = float(rw_table.default) if rw_table.default is not None else 0.0
    rw_rows = {
        (str(sector), str(band)): float(value)
        for (sector, band), value in rw_table.rows
    }
    rw_frame = pl.LazyFrame(
        {
            "cva_rw_sector": [sector for sector, _ in rw_rows],
            "cva_rw_rating_band": [band for _, band in rw_rows],
            "_cva_rw_c": list(rw_rows.values()),
        }
    )

    # M_NS . EAD_NS . DF_NS per netting-set row, where DF_NS uses M from the
    # counterparty's declared effective maturity.
    m_ns = pl.col("cva_effective_maturity_years")
    df_ns = (1.0 - (-discount_rate * m_ns).exp()) / (discount_rate * m_ns)
    per_ns_term = (m_ns * pl.col("ead_final").fill_null(0.0) * df_ns).alias("_cva_ns_term")

    in_scope = cva_counterparties.filter(pl.col("cva_in_scope")).select(
        "counterparty_reference",
        "cva_rw_sector",
        "cva_rw_rating_band",
        "cva_effective_maturity_years",
    )

    # SCVA_c = (1/alpha) . RW_c . SUM_NS[ M_NS . EAD_NS . DF_NS ] per counterparty.
    scva = (
        ccr_exposures.select("counterparty_reference", "ead_final")
        .join(in_scope, on="counterparty_reference", how="inner")
        .join(rw_frame, on=["cva_rw_sector", "cva_rw_rating_band"], how="left")
        .with_columns(pl.col("_cva_rw_c").fill_null(rw_default))
        .with_columns(per_ns_term)
        .group_by("counterparty_reference")
        .agg(
            ((1.0 / alpha) * pl.first("_cva_rw_c") * pl.col("_cva_ns_term").sum()).alias(
                "_scva_c"
            )
        )
    )

    # RWEA_CVA = DS_BA-CVA . K_reduced . 12.5 where
    # K_reduced = sqrt[ (rho.SUM SCVA_c)^2 + (1-rho^2).SUM SCVA_c^2 ];
    # for a single counterparty this collapses to SCVA_c.
    rwea = (
        scva.select(
            sum_scva=pl.col("_scva_c").sum(),
            sum_scva_sq=(pl.col("_scva_c") ** 2).sum(),
        )
        .select(
            (
                (rho * pl.col("sum_scva")) ** 2 + (1.0 - rho**2) * pl.col("sum_scva_sq")
            ).sqrt()
            * ds_ba_cva
            * own_funds_to_rwa
        )
        .collect()
    )

    if rwea.height == 0:
        return None
    value = rwea.item(0, 0)
    if value is None or value <= 0.0:
        return None
    return float(value)


__all__ = ["compute_ba_cva_rwa"]
