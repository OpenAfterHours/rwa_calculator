"""
Portfolio-level EL summary with T2 credit cap and Art. 159(3) two-branch rule.

Internal module — not part of the public API.

Includes both IRB and slotting expected loss in the portfolio EL summary.
Slotting is an IRB sub-approach (Art. 153(5) is in the IRB chapter, Part Three,
Title II, Chapter 3), so slotting RWA and EL feed into the T2 credit cap
(Art. 62(d)) and EL shortfall/excess treatment (Art. 158-159).

Art. 159(3) two-branch rule:
    When non-defaulted EL exceeds non-defaulted provisions (A > B) AND
    defaulted provisions exceed defaulted EL (D > C) simultaneously,
    the shortfall and excess must be computed separately for each pool.
    The defaulted excess must NOT offset the non-defaulted shortfall.
    This prevents cross-subsidisation between the defaulted and non-defaulted
    books, which would otherwise understate CET1 deductions.

References:
- CRR Art. 62(d): T2 credit cap (0.6% of IRB credit risk RWA)
- CRR Art. 158(6), Table B: Expected loss rates for slotting exposures
- CRR Art. 158-159: EL shortfall/excess treatment
- CRR Art. 159(3): Two-branch no-cross-offset rule
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


def _aggregate_by_default_status(
    combined: pl.LazyFrame,
    rwa_col: str,
    has_el: bool,
    has_provisions: bool,
) -> tuple[dict[str, float], dict[str, float]]:
    """Split EL aggregation into non-defaulted and defaulted pools.

    Returns two dicts (non_defaulted, defaulted) each with keys:
    el_shortfall, el_excess, irb_rwa, expected_loss, provisions_allocated.

    When is_defaulted column is absent, all exposures are treated as
    non-defaulted (conservative: no defaulted excess to offset shortfall).
    """
    cols = set(combined.collect_schema().names())
    has_default_flag = "is_defaulted" in cols

    # Build the default-status expression
    if has_default_flag:
        default_expr = pl.col("is_defaulted").fill_null(False)
    else:
        default_expr = pl.lit(False).alias("is_defaulted")

    # Build aggregation expressions
    agg_exprs: list[pl.Expr] = [
        pl.col("el_shortfall").sum().alias("el_shortfall"),
        pl.col("el_excess").sum().alias("el_excess"),
        pl.col(rwa_col).sum().alias("irb_rwa"),
    ]
    if has_el:
        agg_exprs.append(pl.col("expected_loss").sum().alias("expected_loss"))
    if has_provisions:
        agg_exprs.append(pl.col("provision_allocated").sum().alias("provisions_allocated"))

    # Group by default status
    grouped = (
        combined.with_columns(default_expr.alias("_is_defaulted"))
        .group_by("_is_defaulted")
        .agg(agg_exprs)
        .collect()
    )

    def _extract(df: pl.DataFrame, is_def: bool) -> dict[str, float]:
        filtered = df.filter(pl.col("_is_defaulted") == is_def)
        if filtered.height == 0:
            return {
                "el_shortfall": 0.0,
                "el_excess": 0.0,
                "irb_rwa": 0.0,
                "expected_loss": 0.0,
                "provisions_allocated": 0.0,
            }
        row = filtered.row(0, named=True)
        return {
            "el_shortfall": float(row.get("el_shortfall") or 0.0),
            "el_excess": float(row.get("el_excess") or 0.0),
            "irb_rwa": float(row.get("irb_rwa") or 0.0),
            "expected_loss": float(row.get("expected_loss", 0.0) or 0.0),
            "provisions_allocated": float(row.get("provisions_allocated", 0.0) or 0.0),
        }

    non_defaulted = _extract(grouped, False)
    defaulted = _extract(grouped, True)
    return non_defaulted, defaulted


def compute_el_portfolio_summary(
    irb_results: pl.LazyFrame | None,
    slotting_results: pl.LazyFrame | None = None,
) -> ELPortfolioSummary | None:
    """
    Compute portfolio-level EL summary with T2 credit cap and Art. 159(3) rule.

    Aggregates per-exposure EL shortfall/excess across all IRB and slotting
    exposures, splits by default status, and applies the Art. 159(3) two-branch
    no-cross-offset rule before computing the T2 credit cap per CRR Art. 62(d).

    Art. 159(3) two-branch rule:
        When non-defaulted EL > non-defaulted provisions (A > B) AND
        defaulted provisions > defaulted EL (D > C) simultaneously, the
        effective shortfall = non-defaulted shortfall (only) and the
        effective excess = defaulted excess (only). The two pools cannot
        cross-offset. When only one condition holds or neither, the standard
        combined approach applies.

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

    # Split aggregation by default status for Art. 159(3)
    non_def, def_pool = _aggregate_by_default_status(combined, rwa_col, has_el, has_provisions)

    # Pool-level shortfall/excess
    nd_shortfall = non_def["el_shortfall"]
    nd_excess = non_def["el_excess"]
    d_shortfall = def_pool["el_shortfall"]
    d_excess = def_pool["el_excess"]

    # Combined totals (always needed for reporting)
    raw_total_shortfall = nd_shortfall + d_shortfall
    raw_total_excess = nd_excess + d_excess
    total_irb_rwa = non_def["irb_rwa"] + def_pool["irb_rwa"]
    total_expected_loss = non_def["expected_loss"] + def_pool["expected_loss"]
    total_provisions = non_def["provisions_allocated"] + def_pool["provisions_allocated"]

    # Art. 159(3) two-branch condition:
    # A > B (non-defaulted EL > non-defaulted provisions) AND
    # D > C (defaulted provisions > defaulted EL)
    # Equivalently: non-defaulted has shortfall AND defaulted has excess
    art_159_3_applies = nd_shortfall > 0.0 and d_excess > 0.0

    if art_159_3_applies:
        # Two-branch: pools cannot cross-offset
        # Effective shortfall = non-defaulted shortfall only
        # Effective excess = defaulted excess only
        # (Non-defaulted excess and defaulted shortfall still net within their pools,
        #  but the cross-pool netting is prohibited)
        effective_shortfall = nd_shortfall
        effective_excess = d_excess
    else:
        # Standard combined approach — single pool
        effective_shortfall = raw_total_shortfall
        effective_excess = raw_total_excess

    # T2 credit cap: 0.6% of total IRB+slotting RWA (CRR Art. 62(d))
    t2_credit_cap = total_irb_rwa * T2_CREDIT_CAP_RATE
    t2_credit = min(effective_excess, t2_credit_cap)

    # EL shortfall deduction: 50% CET1 + 50% T2 (CRR Art. 159)
    cet1_deduction = effective_shortfall * 0.5
    t2_deduction = effective_shortfall * 0.5

    return ELPortfolioSummary(
        total_expected_loss=total_expected_loss,
        total_provisions_allocated=total_provisions,
        total_el_shortfall=effective_shortfall,
        total_el_excess=effective_excess,
        total_irb_rwa=total_irb_rwa,
        t2_credit_cap=t2_credit_cap,
        t2_credit=t2_credit,
        cet1_deduction=cet1_deduction,
        t2_deduction=t2_deduction,
        non_defaulted_el_shortfall=nd_shortfall,
        non_defaulted_el_excess=nd_excess,
        defaulted_el_shortfall=d_shortfall,
        defaulted_el_excess=d_excess,
        art_159_3_applies=art_159_3_applies,
    )
