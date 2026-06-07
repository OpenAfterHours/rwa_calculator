"""
Server-rendered SVG charts (no JavaScript, no build step).

Pipeline position:
    plain Python data -> ui.views.charts -> inline SVG strings

Key responsibilities:
- Render small, responsive, theme-driven charts as inline SVG so the
  read-only UI stays pure-Python and moonlit-clean (no vendored JS blob, no
  CDN). Colours come from CSS classes wired to the --oah-* tokens in app.css,
  so charts follow the docs palette and the light/dark toggle automatically.

The functions return complete ``<svg>`` strings with a viewBox and
``width:100%`` so they scale to their container. Callers embed the markup
directly in a template (mark it safe — the text inputs are escaped here).
"""

from __future__ import annotations

from html import escape

# Layout constants (SVG user units; the viewBox scales them to the container).
_LABEL_W = 150
_VALUE_W = 96
_BAR_H = 24
_GAP = 12
_PAD = 8


def horizontal_bar_svg(
    items: list[tuple[str, float]],
    *,
    width: int = 560,
    bar_class: str = "chart-bar",
    value_format: str = "{:,.0f}",
) -> str:
    """
    A horizontal bar chart: one labelled bar per (label, value) pair.

    Bars are scaled to the largest absolute value. Used for RWA/EAD by exposure
    class and the approach split.
    """
    if not items:
        return _empty("No data")

    max_value = max((abs(v) for _, v in items), default=0.0) or 1.0
    bar_area = width - _LABEL_W - _VALUE_W
    height = _PAD * 2 + len(items) * (_BAR_H + _GAP) - _GAP
    rows: list[str] = []
    for i, (label, value) in enumerate(items):
        y = _PAD + i * (_BAR_H + _GAP)
        bar_w = max(1.0, abs(value) / max_value * bar_area)
        text_y = y + _BAR_H * 0.7
        rows.append(
            f'<text class="chart-label" x="{_LABEL_W - 8}" y="{text_y:.1f}" '
            f'text-anchor="end">{escape(str(label))}</text>'
            f'<rect class="{escape(bar_class)}" x="{_LABEL_W}" y="{y}" '
            f'width="{bar_w:.1f}" height="{_BAR_H}" rx="3" />'
            f'<text class="chart-value" x="{_LABEL_W + bar_w + 8:.1f}" y="{text_y:.1f}">'
            f"{value_format.format(value)}</text>"
        )
    return _svg(width, height, "".join(rows))


def grouped_bar_svg(
    items: list[tuple[str, float, float]],
    *,
    series: tuple[str, str] = ("CRR", "Basel 3.1"),
    width: int = 560,
    value_format: str = "{:,.0f}",
) -> str:
    """
    Two bars per category — used for CRR vs Basel 3.1 RWA by exposure class.

    Each tuple is (label, crr_value, b31_value).
    """
    if not items:
        return _empty("No data")

    max_value = max((max(abs(a), abs(b)) for _, a, b in items), default=0.0) or 1.0
    bar_area = width - _LABEL_W - _VALUE_W
    sub_h = (_BAR_H - 4) / 2
    height = _PAD * 2 + len(items) * (_BAR_H + _GAP) - _GAP
    rows: list[str] = []
    for i, (label, crr, b31) in enumerate(items):
        y = _PAD + i * (_BAR_H + _GAP)
        rows.append(
            f'<text class="chart-label" x="{_LABEL_W - 8}" y="{y + _BAR_H * 0.7:.1f}" '
            f'text-anchor="end">{escape(str(label))}</text>'
        )
        for j, (name, value) in enumerate(((series[0], crr), (series[1], b31))):
            by = y + j * (sub_h + 4)
            bw = max(1.0, abs(value) / max_value * bar_area)
            cls = "chart-bar-crr" if j == 0 else "chart-bar-b31"
            rows.append(
                f'<rect class="{cls}" x="{_LABEL_W}" y="{by:.1f}" '
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
    bar_area = width - _LABEL_W - _VALUE_W
    height = _PAD * 2 + len(steps) * (_BAR_H + _GAP) - _GAP
    rows: list[str] = []
    for i, step in enumerate(steps):
        y = _PAD + i * (_BAR_H + _GAP)
        impact = float(step["impact_rwa"])
        bar_w = max(1.0, abs(impact) / max_value * bar_area)
        text_y = y + _BAR_H * 0.7
        cls = f"chart-bar-{escape(str(step.get('direction', 'neutral')))}"
        rows.append(
            f'<text class="chart-label" x="{_LABEL_W - 8}" y="{text_y:.1f}" '
            f'text-anchor="end">{escape(str(step["driver"]))}</text>'
            f'<rect class="{cls}" x="{_LABEL_W}" y="{y}" '
            f'width="{bar_w:.1f}" height="{_BAR_H}" rx="3" />'
            f'<text class="chart-value" x="{_LABEL_W + bar_w + 8:.1f}" y="{text_y:.1f}">'
            f"{value_format.format(impact)}</text>"
        )
    return _svg(width, height, "".join(rows))


# =============================================================================
# Private helpers
# =============================================================================


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
