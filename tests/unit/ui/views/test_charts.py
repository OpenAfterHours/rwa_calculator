"""
Unit tests: server-rendered SVG chart builders.

Pins the two label layouts in ui.views.charts so a future change cannot silently
regress them:
- short labels keep the compact, right-aligned-in-the-gutter layout (the look the
  results / reconciliation pages rely on), and
- a label too wide for the gutter switches the whole chart to label-above-bar,
  so the comparison waterfall's long driver names ("Methodology & parameter
  changes") render in full instead of clipping at the card's left edge.
"""

from __future__ import annotations

import math
from html import escape

from rwa_calc.ui.views import charts

# A label that comfortably exceeds the ~142-unit gutter (see charts._GUTTER); the
# real offender is the comparison waterfall driver below. The ``&`` is rendered
# HTML-escaped in the SVG, so assertions compare against ``escape(_LONG_LABEL)``.
_LONG_LABEL = "Methodology & parameter changes"
_LONG_LABEL_ESC = escape(_LONG_LABEL)
_SHORT_ITEMS = [("CORPORATE", 100.0), ("RETAIL", 60.0)]


# =============================================================================
# horizontal_bar_svg — the layout switch
# =============================================================================


def test_short_labels_use_compact_gutter_layout() -> None:
    # Arrange / Act
    svg = charts.horizontal_bar_svg(_SHORT_ITEMS)

    # Assert: labels stay right-aligned in the fixed gutter, bars at _LABEL_W.
    assert 'text-anchor="end"' in svg
    assert f'x="{charts._LABEL_W - 8}"' in svg  # label anchored at the gutter edge (142)
    assert 'text-anchor="start"' not in svg


def test_long_label_switches_to_label_above_layout() -> None:
    # Arrange / Act
    svg = charts.horizontal_bar_svg([(_LONG_LABEL, 100.0), ("RETAIL", 60.0)])

    # Assert: every label is left-anchored above its bar; none clipped in the gutter.
    assert 'text-anchor="start"' in svg
    assert 'text-anchor="end"' not in svg
    assert _LONG_LABEL_ESC in svg  # the full driver name, head and all


def test_long_label_layout_is_taller_than_compact() -> None:
    # Arrange / Act: same row count, only the label length differs.
    compact = charts.horizontal_bar_svg(_SHORT_ITEMS)
    stacked = charts.horizontal_bar_svg([(_LONG_LABEL, 100.0), ("RETAIL", 60.0)])

    # Assert: the stacked layout adds a label line per row, so the viewBox is taller.
    assert _viewbox_height(stacked) > _viewbox_height(compact)


def test_value_text_emitted_in_both_layouts() -> None:
    # Arrange / Act
    compact = charts.horizontal_bar_svg(_SHORT_ITEMS)
    stacked = charts.horizontal_bar_svg([(_LONG_LABEL, 1234.0)])

    # Assert: the formatted value is rendered regardless of layout.
    assert "100" in compact
    assert "1,234" in stacked


def test_empty_items_render_placeholder() -> None:
    # Arrange / Act / Assert
    assert 'class="chart-empty"' in charts.horizontal_bar_svg([])


def test_horizontal_bar_drops_non_finite_values() -> None:
    # Arrange: the same two finite bars, with NaN/inf rows appended.
    clean = charts.horizontal_bar_svg(_SHORT_ITEMS)
    with_bad = charts.horizontal_bar_svg([*_SHORT_ITEMS, ("BAD", math.nan), ("WORSE", math.inf)])

    # Assert: the bad rows are dropped, so no "nan"/"inf" leaks and the finite
    # bars keep their exact scale (a NaN must not collapse max_value).
    assert "nan" not in with_bad.lower()
    assert "inf" not in with_bad.lower()
    assert with_bad == clean


def test_grouped_bar_coerces_non_finite_to_zero() -> None:
    # Arrange / Act: one series cell is NaN.
    svg = charts.grouped_bar_svg([("CORPORATE", 100.0, math.nan), ("RETAIL", 60.0, 50.0)])

    # Assert: the category still renders, with no "nan" leaking into the markup.
    assert "nan" not in svg.lower()
    assert "CORPORATE" in svg


# =============================================================================
# grouped_bar_svg — short vs long category labels
# =============================================================================


def test_grouped_bar_short_labels_stay_compact() -> None:
    # Arrange / Act
    svg = charts.grouped_bar_svg([("CORPORATE", 10.0, 12.0), ("RETAIL", 5.0, 6.0)])

    # Assert
    assert 'text-anchor="end"' in svg
    assert 'text-anchor="start"' not in svg


def test_grouped_bar_long_label_stacks() -> None:
    # Arrange / Act
    svg = charts.grouped_bar_svg([(_LONG_LABEL, 10.0, 12.0)])

    # Assert
    assert 'text-anchor="start"' in svg
    assert _LONG_LABEL_ESC in svg


# =============================================================================
# max_value — the shared bar scale for per-methodology sections
# =============================================================================


def test_horizontal_bar_external_max_value_shrinks_bar() -> None:
    # Arrange / Act: the same bar drawn against its own max vs a larger shared max.
    own = charts.horizontal_bar_svg([("CORPORATE", 100.0)])
    shared = charts.horizontal_bar_svg([("CORPORATE", 100.0)], max_value=200.0)

    # Assert: the shared (larger) scale draws the bar at half width — so a small
    # method reads as genuinely small next to a large one.
    assert _first_bar_width(shared) < _first_bar_width(own)


def test_horizontal_bar_ignores_non_positive_or_non_finite_max_value() -> None:
    # Arrange / Act: a 0 / NaN override must fall back to the internal max.
    own = charts.horizontal_bar_svg([("CORPORATE", 100.0)])

    # Assert: identical markup — the bad override is ignored, not divided by.
    assert charts.horizontal_bar_svg([("CORPORATE", 100.0)], max_value=0.0) == own
    assert charts.horizontal_bar_svg([("CORPORATE", 100.0)], max_value=math.nan) == own


def test_grouped_bar_external_max_value_shrinks_bars() -> None:
    # Arrange / Act
    own = charts.grouped_bar_svg([("CORPORATE", 100.0, 100.0)])
    shared = charts.grouped_bar_svg([("CORPORATE", 100.0, 100.0)], max_value=400.0)

    # Assert
    assert _first_bar_width(shared) < _first_bar_width(own)


# =============================================================================
# waterfall_svg — the reported regression
# =============================================================================


def test_waterfall_long_driver_renders_in_full() -> None:
    # Arrange: the four real comparison drivers, the longest of which clipped before.
    steps = [
        {"driver": "Scaling factor removal (1.06x)", "impact_rwa": -100.0, "direction": "decrease"},
        {
            "driver": "Supporting factor removal (SME/infrastructure)",
            "impact_rwa": 50.0,
            "direction": "increase",
        },
        {"driver": _LONG_LABEL, "impact_rwa": 30.0, "direction": "increase"},
        {"driver": "Output floor impact", "impact_rwa": 20.0, "direction": "increase"},
    ]

    # Act
    svg = charts.waterfall_svg(steps)

    # Assert: full driver names, left-anchored above their bars (never clipped).
    assert 'text-anchor="start"' in svg
    assert "Supporting factor removal (SME/infrastructure)" in svg
    assert _LONG_LABEL_ESC in svg


def test_waterfall_empty_renders_placeholder() -> None:
    # Arrange / Act / Assert
    assert 'class="chart-empty"' in charts.waterfall_svg([])


# =============================================================================
# Helpers
# =============================================================================


def _viewbox_height(svg: str) -> int:
    """Parse the height out of ``viewBox="0 0 {width} {height}"``."""
    marker = 'viewBox="0 0 '
    start = svg.index(marker) + len(marker)
    end = svg.index('"', start)
    return int(svg[start:end].split()[1])


def _first_bar_width(svg: str) -> float:
    """Parse the ``width`` of the first data-bar ``<rect>`` in the chart."""
    bar = svg.index("<rect")
    marker = 'width="'
    start = svg.index(marker, bar) + len(marker)
    end = svg.index('"', start)
    return float(svg[start:end])
