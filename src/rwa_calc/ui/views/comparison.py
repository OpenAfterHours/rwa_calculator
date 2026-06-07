"""
Framework-agnostic comparison views (CRR vs Basel 3.1).

Pipeline position:
    ComparisonBundle / CapitalImpactBundle (engine/comparison.py)
        -> ui.views.comparison -> plain dicts / Polars DataFrames

Key responsibilities:
- Turn the dual-framework comparison bundles into presentation-ready data
  structures (headline metrics, the capital-impact waterfall, sorted summary
  tables) with NO UI-framework imports, so the docs site, the FastAPI/Jinja
  app, and Marimo can all render the same numbers from one source.

All headline totals are read from the top-level ComparisonBundle LazyFrames
(``summary_by_class`` / ``summary_by_approach``) — never the nested
AggregatedResultBundle — so callers and tests stay light.

References:
- PRA PS1/26 Ch.12: output floor transitional period
- CRR Art. 92: own funds requirements; Art. 501/501a: supporting factors
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CapitalImpactBundle, ComparisonBundle

# Preferred column order for the comparison summary tables. Columns absent from
# a given bundle are silently skipped.
_CLASS_DISPLAY_COLS = [
    "exposure_class",
    "exposure_count",
    "total_ead_crr",
    "total_ead_b31",
    "total_rwa_crr",
    "total_rwa_b31",
    "total_delta_rwa",
    "delta_rwa_pct",
]
_APPROACH_DISPLAY_COLS = [
    "approach_applied",
    "exposure_count",
    "total_ead_crr",
    "total_ead_b31",
    "total_rwa_crr",
    "total_rwa_b31",
    "total_delta_rwa",
    "delta_rwa_pct",
]


def executive_summary(bundle: ComparisonBundle) -> dict[str, float]:
    """
    Headline CRR vs Basel 3.1 metrics for the executive summary panel.

    Returns total RWA/EAD for each framework, the absolute and percentage RWA
    delta, and the average risk weight under each framework. All values are
    floats (currency units / ratios) suitable for direct display or charting.
    """
    df = bundle.summary_by_approach.collect()
    crr_rwa = _sum(df, "total_rwa_crr")
    b31_rwa = _sum(df, "total_rwa_b31")
    crr_ead = _sum(df, "total_ead_crr")
    b31_ead = _sum(df, "total_ead_b31")
    delta_rwa = b31_rwa - crr_rwa
    return {
        "crr_rwa": crr_rwa,
        "b31_rwa": b31_rwa,
        "delta_rwa": delta_rwa,
        "delta_pct": (delta_rwa / crr_rwa * 100.0) if crr_rwa else 0.0,
        "crr_ead": crr_ead,
        "b31_ead": b31_ead,
        "crr_avg_rw": (crr_rwa / crr_ead) if crr_ead else 0.0,
        "b31_avg_rw": (b31_rwa / b31_ead) if b31_ead else 0.0,
    }


def waterfall_steps(impact: CapitalImpactBundle) -> list[dict]:
    """
    The capital-impact waterfall as an ordered list of step dicts.

    Each step carries its sequential ``step`` index, the ``driver`` name, the
    additive ``impact_rwa``, the running ``cumulative_rwa``, and a ``direction``
    label ("increase" / "decrease" / "neutral") for styling.
    """
    df = impact.portfolio_waterfall.collect()
    steps: list[dict] = []
    for i in range(df.height):
        impact_rwa = float(df["impact_rwa"][i])
        steps.append(
            {
                "step": int(df["step"][i]),
                "driver": df["driver"][i],
                "impact_rwa": impact_rwa,
                "cumulative_rwa": float(df["cumulative_rwa"][i]),
                "direction": _direction(impact_rwa),
            }
        )
    return steps


def summary_by_class(bundle: ComparisonBundle) -> pl.DataFrame:
    """Comparison summary by exposure class, ordered by RWA delta (desc)."""
    return _ordered_summary(bundle.summary_by_class, _CLASS_DISPLAY_COLS)


def summary_by_approach(bundle: ComparisonBundle) -> pl.DataFrame:
    """Comparison summary by calculation approach, ordered by RWA delta (desc)."""
    return _ordered_summary(bundle.summary_by_approach, _APPROACH_DISPLAY_COLS)


# =============================================================================
# Private helpers
# =============================================================================


def _ordered_summary(lf: pl.LazyFrame, preferred: list[str]) -> pl.DataFrame:
    """Collect *lf*, keep the preferred columns present, sort by RWA delta."""
    df: pl.DataFrame = lf.collect()
    cols = [c for c in preferred if c in df.columns]
    if cols:
        df = df.select(cols)
    if "total_delta_rwa" in df.columns:
        df = df.sort("total_delta_rwa", descending=True)
    return df


def _sum(df: pl.DataFrame, col: str) -> float:
    """Sum a column to a float, tolerating absent columns and nulls."""
    if col in df.columns and df.height > 0:
        total = df[col].sum()
        return float(total) if total is not None else 0.0
    return 0.0


def _direction(impact: float) -> str:
    """Label a waterfall impact for styling."""
    if impact > 0:
        return "increase"
    if impact < 0:
        return "decrease"
    return "neutral"
