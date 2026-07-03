"""
Per-methodology chart sections (split an exposure-class view by STD/FIRB/AIRB/…).

Pipeline position:
    (exposure_class, method, value) DataFrame -> ui.views.method_split
        -> list of {method, chart} sections (inline SVG)

Key responsibilities:
- Turn a class x method summary frame into one chart section per methodology,
  in a stable presentation order (STD, FIRB, AIRB, SLOTTING, EQUITY, then any
  unrecognised label alphabetically), dropping methods with nothing to plot.
- Share ONE bar scale across a chart-set's sections so a small method reads as
  genuinely small next to a large one (cross-method comparability), rather than
  each section rescaling to its own max.

This is the single home for the methodology display vocabulary/order on the UI
side, reused by the results tab (RWA + EAD by class), the comparison tab (CRR vs
Basel 3.1 by class), and the reconciliation tab, so they cannot drift. The
methodology LABELS themselves are produced upstream by the engine's single
mapping (``engine/aggregator/_summaries.py::_method_expr``) and consumed here
verbatim — this module only fixes their display order and section layout.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, SupportsFloat, cast

import polars as pl

from rwa_calc.ui.views import charts

if TYPE_CHECKING:
    from collections.abc import Iterable

# Presentation order of the methodology sections. Labels present in the data but
# not listed here (an unexpected approach) are appended alphabetically so nothing
# is dropped. Mirrors the engine's method vocabulary but is display-order only —
# never the approach->label mapping (that lives in the aggregator).
METHOD_ORDER: tuple[str, ...] = ("STD", "FIRB", "AIRB", "SLOTTING", "EQUITY")


def single_series_sections(
    df: pl.DataFrame | None,
    value_col: str,
    *,
    label_col: str = "exposure_class",
    method_col: str = "method",
    shared_scale: bool = True,
) -> list[dict]:
    """One horizontal-bar section per methodology for a single value column.

    ``df`` is a class x method summary (e.g. columns ``exposure_class``,
    ``method``, ``total_rwa`` / ``total_ead``). Returns ``[{method, chart}]`` in
    ``METHOD_ORDER``, one per method that has at least one row to plot. Returns
    ``[]`` when the frame is empty or missing a required column, so callers fall
    back to the single combined chart.
    """
    if df is None or df.is_empty() or not {method_col, label_col, value_col} <= set(df.columns):
        return []
    scale = _shared_max(df, [value_col]) if shared_scale else None
    sections: list[dict] = []
    for method in _ordered_methods(df, method_col):
        items = _series_items(df.filter(pl.col(method_col) == method), label_col, value_col)
        if items:
            chart = charts.horizontal_bar_svg(items, max_value=scale)
            sections.append({"method": method, "chart": chart})
    return sections


def grouped_series_sections(
    df: pl.DataFrame | None,
    *,
    left_col: str,
    right_col: str,
    label_col: str = "exposure_class",
    method_col: str = "method",
    series: tuple[str, str] = ("CRR", "Basel 3.1"),
    shared_scale: bool = True,
) -> list[dict]:
    """One grouped-bar (two-series) section per methodology.

    ``df`` is a class x method summary carrying two comparable value columns
    (e.g. ``total_rwa_crr`` / ``total_rwa_b31``). Returns ``[{method, chart}]`` in
    ``METHOD_ORDER``; ``[]`` when the frame is empty or a required column is
    absent. The two series share one scale across all sections when
    ``shared_scale`` so methods stay visually comparable.
    """
    required = {method_col, label_col, left_col, right_col}
    if df is None or df.is_empty() or not required <= set(df.columns):
        return []
    scale = _shared_max(df, [left_col, right_col]) if shared_scale else None
    sections: list[dict] = []
    for method in _ordered_methods(df, method_col):
        items = _grouped_items(
            df.filter(pl.col(method_col) == method), label_col, left_col, right_col
        )
        if items:
            chart = charts.grouped_bar_svg(items, series=series, max_value=scale)
            sections.append({"method": method, "chart": chart})
    return sections


# =============================================================================
# Private helpers
# =============================================================================


def _ordered_methods(df: pl.DataFrame, method_col: str) -> list[str]:
    """Distinct methods present, in METHOD_ORDER then unknowns alphabetically."""
    present = [m for m in df.get_column(method_col).unique().to_list() if m is not None]
    ordered = [m for m in METHOD_ORDER if m in present]
    ordered += sorted(m for m in present if m not in METHOD_ORDER)
    return ordered


def _series_items(df: pl.DataFrame, label_col: str, value_col: str) -> list[tuple[str, float]]:
    """(label, value) tuples sorted by value desc; null -> 0.0, non-finite dropped.

    Mirrors the results-tab item builder so a single poisoned IRB row cannot
    collapse the shared bar scale.
    """
    items: list[tuple[str, float]] = []
    for row in df.sort(value_col, descending=True).to_dicts():
        raw = row[value_col]
        if raw is None:
            items.append((str(row[label_col]), 0.0))
            continue
        value = float(raw)
        if not math.isfinite(value):
            continue
        items.append((str(row[label_col]), value))
    return items


def _grouped_items(
    df: pl.DataFrame, label_col: str, left_col: str, right_col: str
) -> list[tuple[str, float, float]]:
    """(label, left, right) tuples ordered by the larger side desc; nulls -> 0.0."""
    items: list[tuple[str, float, float]] = []
    for row in df.to_dicts():
        left = _finite(row.get(left_col))
        right = _finite(row.get(right_col))
        items.append((str(row[label_col]), left, right))
    items.sort(key=lambda it: max(abs(it[1]), abs(it[2])), reverse=True)
    return items


def _shared_max(df: pl.DataFrame, value_cols: Iterable[str]) -> float:
    """Largest finite absolute value across ``value_cols`` (1.0 when none)."""
    best = 0.0
    for col in value_cols:
        if col not in df.columns:
            continue
        for raw in df.get_column(col).to_list():
            if raw is None:
                continue
            value = abs(float(raw))
            if math.isfinite(value) and value > best:
                best = value
    return best or 1.0


def _finite(raw: object) -> float:
    """Coerce a cell to a finite float (null / non-finite -> 0.0)."""
    if raw is None:
        return 0.0
    value = float(cast("SupportsFloat", raw))
    return value if math.isfinite(value) else 0.0
