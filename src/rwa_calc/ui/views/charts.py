"""
Server-rendered SVG charts (no JavaScript, no build step).

Pipeline position:
    plain Python data -> ui.views.charts -> inline SVG strings

Key responsibilities:
- Render small, responsive, theme-driven charts as inline SVG so the
  read-only UI stays pure-Python and moonlit-clean (no vendored JS blob, no
  CDN). Colours come from CSS classes wired to the --oah-* tokens in app.css,
  so charts follow the docs palette and the light/dark toggle automatically.

Layout:
- Short category labels sit in a fixed left gutter, right-aligned against the
  bar (the compact default — used by the results / reconciliation charts).
- When any label is too wide for that gutter (e.g. the comparison waterfall
  drivers like "Methodology & parameter changes"), the whole chart switches to a
  label-above-bar layout: the label gets the full chart width on its own line and
  the bar sits underneath. This is decided per chart, so a chart whose labels all
  fit renders byte-identical to the compact layout — the common case never moves.

The functions return complete ``<svg>`` strings with a viewBox and
``width:100%`` so they scale to their container. Callers embed the markup
directly in a template (mark it safe — the text inputs are escaped here).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Layout constants (SVG user units; the viewBox scales them to the container).
_LABEL_W = 150
_VALUE_W = 96
_BAR_H = 24
_GAP = 12
_PAD = 8

# Stacked (label-above-bar) layout: the height of the label line drawn above
# each bar, and the baseline offset of the label text within that line.
_LABEL_LINE = 16
_LABEL_BASELINE = 11

# Left gutter available to a right-aligned label (text ends at ``_LABEL_W - 8``
# and grows toward x=0). A label wider than this overruns the viewBox left edge
# and is clipped, so the chart switches to the label-above layout instead.
_GUTTER = _LABEL_W - 8
# Approximate advance width of one monospace glyph at the 11px label font. Held
# deliberately generous so a borderline label stacks rather than risks a clip —
# a false positive only moves a label that would have fit onto its own line.
_LABEL_CHAR_W = 6.8


def horizontal_bar_svg(
    items: list[tuple[str, float]],
    *,
    width: int = 560,
    bar_class: str = "chart-bar",
    value_format: str = "{:,.0f}",
    max_value: float | None = None,
) -> str:
    """
    A horizontal bar chart: one labelled bar per (label, value) pair.

    Bars are scaled to the largest absolute value. Used for RWA/EAD by exposure
    class and the approach split.

    Pass ``max_value`` to fix the bar scale to an external maximum instead of the
    chart's own largest value — the per-methodology sections share one scale this
    way, so a small method's bars read as genuinely small next to a large one
    (a NaN / inf / non-positive override is ignored and the internal max is used).
    """
    # Drop non-finite (NaN / inf) values up front: a single NaN would otherwise
    # poison the scale (NaN sorts as the max), collapsing every other bar to a
    # 1px sliver and rendering literal "nan" labels.
    items = [(label, value) for label, value in items if math.isfinite(value)]
    if not items:
        return _empty("No data")

    scale = _scale(max_value, (abs(v) for _, v in items))
    stacked = _stack_labels(label for label, _ in items)
    height = _chart_height(len(items), stacked=stacked)
    rows: list[str] = []
    for i, (label, value) in enumerate(items):
        row = _row(i, width, stacked=stacked)
        bar_w = max(1.0, abs(value) / scale * row.bar_area)
        rows.append(
            _label(label, row)
            + f'<rect class="{escape(bar_class)}" x="{row.bar_x}" y="{row.bar_y:.1f}" '
            f'width="{bar_w:.1f}" height="{_BAR_H}" rx="3" />'
            f'<text class="chart-value" x="{row.bar_x + bar_w + 8:.1f}" y="{row.value_y:.1f}">'
            f"{value_format.format(value)}</text>"
        )
    return _svg(width, height, "".join(rows))


def grouped_bar_svg(
    items: list[tuple[str, float, float]],
    *,
    series: tuple[str, str] = ("CRR", "Basel 3.1"),
    width: int = 560,
    value_format: str = "{:,.0f}",
    max_value: float | None = None,
) -> str:
    """
    Two bars per category — used for CRR vs Basel 3.1 RWA by exposure class.

    Each tuple is (label, crr_value, b31_value). Pass ``max_value`` to fix the bar
    scale to an external maximum (so per-methodology sections share one scale); a
    non-finite / non-positive override is ignored and the internal max is used.
    """
    if not items:
        return _empty("No data")

    # Coerce non-finite (NaN / inf) series values to 0 so a single bad cell cannot
    # poison the scale or render a literal "nan" bar/label.
    items = [
        (label, a if math.isfinite(a) else 0.0, b if math.isfinite(b) else 0.0)
        for label, a, b in items
    ]
    scale = _scale(max_value, (max(abs(a), abs(b)) for _, a, b in items))
    stacked = _stack_labels(label for label, _, _ in items)
    sub_h = (_BAR_H - 4) / 2
    height = _chart_height(len(items), stacked=stacked)
    rows: list[str] = []
    for i, (label, crr, b31) in enumerate(items):
        row = _row(i, width, stacked=stacked)
        rows.append(_label(label, row))
        for j, (name, value) in enumerate(((series[0], crr), (series[1], b31))):
            by = row.bar_y + j * (sub_h + 4)
            bw = max(1.0, abs(value) / scale * row.bar_area)
            cls = "chart-bar-crr" if j == 0 else "chart-bar-b31"
            rows.append(
                f'<rect class="{cls}" x="{row.bar_x}" y="{by:.1f}" '
                f'width="{bw:.1f}" height="{sub_h:.1f}" rx="2"><title>'
                f"{escape(name)}: {value_format.format(value)}</title></rect>"
            )
    return _svg(width, height, "".join(rows))


def waterfall_svg(
    steps: list[dict],
    *,
    width: int = 560,
    value_format: str = "{:+,.0f}",
) -> str:
    """
    A driver waterfall: one bar per step, coloured by ``direction``.

    Each step dict needs ``driver`` (str), ``impact_rwa`` (float) and
    ``direction`` ("increase" / "decrease" / "neutral"). Bars are scaled to the
    largest absolute impact.
    """
    if not steps:
        return _empty("No drivers")

    max_value = max((abs(s["impact_rwa"]) for s in steps), default=0.0) or 1.0
    stacked = _stack_labels(str(s["driver"]) for s in steps)
    height = _chart_height(len(steps), stacked=stacked)
    rows: list[str] = []
    for i, step in enumerate(steps):
        row = _row(i, width, stacked=stacked)
        impact = float(step["impact_rwa"])
        bar_w = max(1.0, abs(impact) / max_value * row.bar_area)
        cls = f"chart-bar-{escape(str(step.get('direction', 'neutral')))}"
        rows.append(
            _label(str(step["driver"]), row)
            + f'<rect class="{cls}" x="{row.bar_x}" y="{row.bar_y:.1f}" '
            f'width="{bar_w:.1f}" height="{_BAR_H}" rx="3" />'
            f'<text class="chart-value" x="{row.bar_x + bar_w + 8:.1f}" y="{row.value_y:.1f}">'
            f"{value_format.format(impact)}</text>"
        )
    return _svg(width, height, "".join(rows))


# =============================================================================
# Layout helpers
# =============================================================================


@dataclass(frozen=True, slots=True)
class _Row:
    """Resolved geometry for one chart row under the active (compact/stacked) layout."""

    label_x: int
    label_y: float
    label_anchor: str  # "end" (compact, right-aligned in the gutter) or "start" (stacked)
    bar_x: int
    bar_y: float
    bar_area: float
    value_y: float


def _stack_labels(labels: Iterable[str]) -> bool:
    """True when any label is too wide for the left gutter (switch to label-above).

    The width estimate is intentionally generous (see ``_LABEL_CHAR_W``) so a
    borderline label stacks rather than clips.
    """
    return any(len(label) * _LABEL_CHAR_W > _GUTTER for label in labels)


def _row(i: int, width: int, *, stacked: bool) -> _Row:
    """Geometry for row *i*: bar position, label placement and value baseline."""
    if stacked:
        top = _PAD + i * (_LABEL_LINE + _BAR_H + _GAP)
        bar_y = top + _LABEL_LINE
        return _Row(
            label_x=_PAD,
            label_y=top + _LABEL_BASELINE,
            label_anchor="start",
            bar_x=_PAD,
            bar_y=bar_y,
            bar_area=width - _PAD - _VALUE_W,
            value_y=bar_y + _BAR_H * 0.7,
        )
    top = _PAD + i * (_BAR_H + _GAP)
    return _Row(
        label_x=_LABEL_W - 8,
        label_y=top + _BAR_H * 0.7,
        label_anchor="end",
        bar_x=_LABEL_W,
        bar_y=top,
        bar_area=width - _LABEL_W - _VALUE_W,
        value_y=top + _BAR_H * 0.7,
    )


def _label(text: str, row: _Row) -> str:
    """The ``<text>`` markup for a row's category label (escaped)."""
    return (
        f'<text class="chart-label" x="{row.label_x}" y="{row.label_y:.1f}" '
        f'text-anchor="{row.label_anchor}">{escape(str(text))}</text>'
    )


def _chart_height(n: int, *, stacked: bool) -> int:
    """Total chart height for *n* rows under the active layout."""
    unit = (_LABEL_LINE + _BAR_H + _GAP) if stacked else (_BAR_H + _GAP)
    return _PAD * 2 + n * unit - _GAP


# =============================================================================
# Private helpers
# =============================================================================


def _scale(max_value: float | None, values: Iterable[float]) -> float:
    """Resolve the bar-scale denominator: a valid external override, else the max.

    A caller-supplied ``max_value`` fixes the scale (so sibling charts share it);
    a ``None`` / non-finite / non-positive override falls back to the largest
    absolute value in ``values``. Never returns 0 (a 0 scale would divide by zero).
    """
    if max_value is not None and math.isfinite(max_value) and max_value > 0:
        return max_value
    return max((abs(v) for v in values), default=0.0) or 1.0


def _svg(width: int, height: int, body: str) -> str:
    """Wrap chart body in a responsive, accessible SVG element."""
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMinYMin meet" role="img" '
        f'style="width:100%;height:auto">{body}</svg>'
    )


def _empty(message: str) -> str:
    """A small placeholder when there is nothing to plot."""
    return f'<p class="chart-empty">{escape(message)}</p>'
