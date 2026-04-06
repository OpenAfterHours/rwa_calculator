"""
Portfolio-level EL summary with T2 credit cap.

Internal module — not part of the public API.

Includes both IRB and slotting expected loss in the portfolio EL summary.
Slotting is an IRB sub-approach (Art. 153(5) is in the IRB chapter, Part Three,
Title II, Chapter 3), so slotting RWA and EL feed into the T2 credit cap
(Art. 62(d)) and EL shortfall/excess treatment (Art. 158-159).

References:
- CRR Art. 62(d): T2 credit cap (0.6% of IRB credit risk RWA)
- CRR Art. 158(6), Table B: Expected loss rates for slotting exposures
- CRR Art. 158-159: EL shortfall/excess treatment
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import ELPortfolioSummary
from rwa_calc.engine.aggregator._schemas import T2_CREDIT_CAP_RATE
from rwa_calc.engine.aggregator._utils import resolve_rwa_col


def _combine_irb_and_slotting(
    irb_results: pl.LazyFrame | None,
    slotting_results: pl.LazyFrame | None,
) -> pl.LazyFrame | None:
    """Concatenate IRB and slotting results for joint EL summary.

    Only includes slotting results that carry EL columns (el_shortfall, el_excess).
    Falls back to IRB-only when slotting has no EL data.
    """
    frames: list[pl.LazyFrame] = []

    if irb_results is not None:
        irb_cols = set(irb_results.collect_schema().names())
        if "el_shortfall" in irb_cols and "el_excess" in irb_cols:
            frames.append(irb_results)

    if slotting_results is not None:
        sl_cols = set(slotting_results.collect_schema().names())
        if "el_shortfall" in sl_cols and "el_excess" in sl_cols:
            frames.append(slotting_results)

    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    return pl.concat(frames, how="diagonal_relaxed")


def compute_el_portfolio_summary(
    irb_results: pl.LazyFrame | None,
    slotting_results: pl.LazyFrame | None = None,
) -> ELPortfolioSummary | None:
    """
    Compute portfolio-level EL summary with T2 credit cap.

    Aggregates per-exposure EL shortfall/excess across all IRB and slotting
    exposures and applies the T2 credit cap per CRR Art. 62(d).

    Slotting exposures contribute EL via Art. 158(6) Table B rates and their
    RWA is included in the T2 credit cap denominator (Art. 62(d) references
    IRB credit-risk RWA from Part Three, Title II, Chapter 3 which includes
    the slotting approach under Art. 153(5)).
    """
    combined = _combine_irb_and_slotting(irb_results, slotting_results)
    if combined is None:
        return None

    cols = set(combined.collect_schema().names())
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

    agg_df: pl.DataFrame = combined.select(agg_exprs).collect()

    total_el_shortfall = float(agg_df["total_el_shortfall"][0] or 0.0)
    total_el_excess = float(agg_df["total_el_excess"][0] or 0.0)
    total_irb_rwa = float(agg_df["total_irb_rwa"][0] or 0.0)
    total_expected_loss = float(agg_df["total_expected_loss"][0] or 0.0) if has_el else 0.0
    total_provisions = (
        float(agg_df["total_provisions_allocated"][0] or 0.0) if has_provisions else 0.0
    )

    # T2 credit cap: 0.6% of total IRB+slotting RWA (CRR Art. 62(d))
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
