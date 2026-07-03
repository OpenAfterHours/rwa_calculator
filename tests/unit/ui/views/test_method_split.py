"""
Unit tests: per-methodology chart sections (ui.views.method_split).

Pins the shared helper that splits an exposure-class view into one chart section
per methodology (STD/FIRB/AIRB/SLOTTING/EQUITY) — the ordering, the empty-frame
tolerance, the single vs grouped series shapes, and the shared bar scale across a
chart-set — so the results, comparison and reconciliation tabs render a
consistent split.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.ui.views import method_split


def _class_method_df() -> pl.DataFrame:
    """A class x method summary spanning several methodologies (scrambled order)."""
    return pl.DataFrame(
        {
            "exposure_class": ["corporate", "corporate", "retail", "equity"],
            "method": ["AIRB", "STD", "STD", "EQUITY"],
            "total_rwa": [300.0, 100.0, 50.0, 20.0],
            "total_ead": [2000.0, 1000.0, 500.0, 10.0],
        }
    )


# =============================================================================
# single_series_sections
# =============================================================================


def test_single_series_sections_orders_methods_canonically() -> None:
    # Arrange: methods present out of order, plus an unrecognised label.
    df = pl.DataFrame(
        {
            "exposure_class": ["a", "a", "a", "a"],
            "method": ["EQUITY", "STD", "ZZZ", "AIRB"],
            "total_rwa": [1.0, 2.0, 3.0, 4.0],
        }
    )

    # Act
    sections = method_split.single_series_sections(df, "total_rwa")

    # Assert: METHOD_ORDER first, then unknowns alphabetically — nothing dropped.
    assert [s["method"] for s in sections] == ["STD", "AIRB", "EQUITY", "ZZZ"]


def test_single_series_sections_build_rwa_and_ead_from_one_frame() -> None:
    # Arrange
    df = _class_method_df()

    # Act: the same frame drives both the RWA and the EAD split (EAD is free).
    rwa = method_split.single_series_sections(df, "total_rwa")
    ead = method_split.single_series_sections(df, "total_ead")

    # Assert: same methodologies surface for both value columns, canonical order.
    assert [s["method"] for s in rwa] == ["STD", "AIRB", "EQUITY"]
    assert [s["method"] for s in ead] == ["STD", "AIRB", "EQUITY"]
    assert all("<svg" in s["chart"] for s in rwa + ead)


def test_single_series_sections_missing_value_column_returns_empty() -> None:
    # Arrange: no total_ead column present.
    df = pl.DataFrame({"exposure_class": ["a"], "method": ["STD"], "total_rwa": [1.0]})

    # Act / Assert: callers fall back to the combined chart.
    assert method_split.single_series_sections(df, "total_ead") == []


def test_single_series_sections_none_or_empty_returns_empty() -> None:
    # Act / Assert
    assert method_split.single_series_sections(None, "total_rwa") == []
    empty = pl.DataFrame(schema={"exposure_class": pl.String, "method": pl.String})
    assert method_split.single_series_sections(empty, "total_rwa") == []


def test_single_series_shared_scale_shrinks_small_method_bars() -> None:
    # Arrange: STD is large (100), EQUITY tiny (2) — one class each so one bar each.
    df = pl.DataFrame(
        {
            "exposure_class": ["a", "b"],
            "method": ["STD", "EQUITY"],
            "total_rwa": [100.0, 2.0],
        }
    )

    # Act: shared scale (default) vs each section self-scaled.
    shared = method_split.single_series_sections(df, "total_rwa")
    independent = method_split.single_series_sections(df, "total_rwa", shared_scale=False)

    # Assert: with a shared scale the tiny EQUITY bar is far narrower than when it
    # is rescaled to its own max (which would make it as wide as STD's).
    eq_shared = _first_bar_width(_chart_for(shared, "EQUITY"))
    eq_independent = _first_bar_width(_chart_for(independent, "EQUITY"))
    assert eq_shared < eq_independent


# =============================================================================
# grouped_series_sections
# =============================================================================


def test_grouped_series_sections_two_series_per_method() -> None:
    # Arrange
    df = pl.DataFrame(
        {
            "exposure_class": ["corporate", "retail"],
            "method": ["AIRB", "STD"],
            "total_rwa_crr": [300.0, 50.0],
            "total_rwa_b31": [250.0, 60.0],
        }
    )

    # Act
    sections = method_split.grouped_series_sections(
        df, left_col="total_rwa_crr", right_col="total_rwa_b31"
    )

    # Assert: canonical order, each an SVG grouped bar.
    assert [s["method"] for s in sections] == ["STD", "AIRB"]
    assert all("<svg" in s["chart"] for s in sections)


def test_grouped_series_sections_missing_column_returns_empty() -> None:
    # Arrange: only one of the two series columns present.
    df = pl.DataFrame({"exposure_class": ["a"], "method": ["STD"], "total_rwa_crr": [1.0]})

    # Act / Assert
    assert (
        method_split.grouped_series_sections(
            df, left_col="total_rwa_crr", right_col="total_rwa_b31"
        )
        == []
    )


# =============================================================================
# Helpers
# =============================================================================


def _chart_for(sections: list[dict], method: str) -> str:
    return next(s["chart"] for s in sections if s["method"] == method)


def _first_bar_width(svg: str) -> float:
    bar = svg.index("<rect")
    marker = 'width="'
    start = svg.index(marker, bar) + len(marker)
    end = svg.index('"', start)
    return float(svg[start:end])
