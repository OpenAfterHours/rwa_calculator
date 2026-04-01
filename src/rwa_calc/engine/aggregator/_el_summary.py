"""
Portfolio-level EL summary with T2 credit cap.

Internal module — not part of the public API.

References:
- CRR Art. 62(d): T2 credit cap (0.6% of IRB RWA)
- CRR Art. 158-159: EL shortfall/excess treatment
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import ELPortfolioSummary
from rwa_calc.engine.aggregator._schemas import T2_CREDIT_CAP_RATE
from rwa_calc.engine.aggregator._utils import resolve_rwa_col


def compute_el_portfolio_summary(
    irb_results: pl.LazyFrame | None,
) -> ELPortfolioSummary | None:
    """
    Compute portfolio-level EL summary with T2 credit cap.

    Aggregates per-exposure EL shortfall/excess across all IRB exposures
    and applies the T2 credit cap per CRR Art. 62(d).
    """
    if irb_results is None:
        return None

    cols = set(irb_results.collect_schema().names())
    if "el_shortfall" not in cols or "el_excess" not in cols:
        return None

    rwa_col = resolve_rwa_col(cols)
    if not rwa_col:
        return None

    has_el = "expected_loss" in cols
    has_provisions = "provision_allocated" in cols

    agg_exprs: list[pl.Expr] = [
        pl.col("el_shortfall").sum().alias("total_el_shortfall"),
        pl.col("el_excess").sum().alias("total_el_excess"),
        pl.col(rwa_col).sum().alias("total_irb_rwa"),
    ]
    if has_el:
        agg_exprs.append(pl.col("expected_loss").sum().alias("total_expected_loss"))
    if has_provisions:
        agg_exprs.append(pl.col("provision_allocated").sum().alias("total_provisions_allocated"))

    agg_df: pl.DataFrame = irb_results.select(agg_exprs).collect()

    total_el_shortfall = float(agg_df["total_el_shortfall"][0] or 0.0)
    total_el_excess = float(agg_df["total_el_excess"][0] or 0.0)
    total_irb_rwa = float(agg_df["total_irb_rwa"][0] or 0.0)
    total_expected_loss = float(agg_df["total_expected_loss"][0] or 0.0) if has_el else 0.0
    total_provisions = (
        float(agg_df["total_provisions_allocated"][0] or 0.0) if has_provisions else 0.0
    )

    # T2 credit cap: 0.6% of total IRB RWA (CRR Art. 62(d))
    t2_credit_cap = total_irb_rwa * T2_CREDIT_CAP_RATE
    t2_credit = min(total_el_excess, t2_credit_cap)

    # EL shortfall deduction: 50% CET1 + 50% T2 (CRR Art. 159)
    cet1_deduction = total_el_shortfall * 0.5
    t2_deduction = total_el_shortfall * 0.5

    return ELPortfolioSummary(
        total_expected_loss=total_expected_loss,
        total_provisions_allocated=total_provisions,
        total_el_shortfall=total_el_shortfall,
        total_el_excess=total_el_excess,
        total_irb_rwa=total_irb_rwa,
        t2_credit_cap=t2_credit_cap,
        t2_credit=t2_credit,
        cet1_deduction=cet1_deduction,
        t2_deduction=t2_deduction,
    )
