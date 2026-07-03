"""
Unit tests: framework-agnostic comparison views.

Verifies that ui.views.comparison turns ComparisonBundle / CapitalImpactBundle
into the presentation-ready structures the UIs consume — headline metrics, the
ordered waterfall, and sorted summary tables — without any UI-framework deps.
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.resolved_bundle import make_aggregated_bundle

from rwa_calc.contracts.bundles import (
    CapitalImpactBundle,
    ComparisonBundle,
)
from rwa_calc.ui.views import comparison as cmp

# =============================================================================
# Helpers
# =============================================================================


def _comparison_bundle(
    *,
    summary_by_approach: pl.LazyFrame | None = None,
    summary_by_class: pl.LazyFrame | None = None,
    exposure_deltas: pl.LazyFrame | None = None,
    baseline_label: str = "crr",
    variant_label: str = "b31",
) -> ComparisonBundle:
    """Build a ComparisonBundle whose only meaningful fields are the summaries."""
    empty = pl.LazyFrame()
    agg = make_aggregated_bundle(results=empty)
    return ComparisonBundle(
        baseline_results=agg,
        variant_results=agg,
        exposure_deltas=exposure_deltas if exposure_deltas is not None else empty,
        summary_by_class=summary_by_class if summary_by_class is not None else empty,
        summary_by_approach=summary_by_approach if summary_by_approach is not None else empty,
        baseline_label=baseline_label,
        variant_label=variant_label,
    )


def _impact_bundle(portfolio_waterfall: pl.LazyFrame) -> CapitalImpactBundle:
    empty = pl.LazyFrame()
    return CapitalImpactBundle(
        exposure_attribution=empty,
        portfolio_waterfall=portfolio_waterfall,
        summary_by_class=empty,
        summary_by_approach=empty,
    )


# =============================================================================
# executive_summary
# =============================================================================


def test_executive_summary_aggregates_totals_and_deltas() -> None:
    # Arrange — two approach rows; totals: crr_rwa=300, b31_rwa=360, ead=1000 both
    by_approach = pl.LazyFrame(
        {
            "approach_applied": ["SA", "IRB"],
            "total_ead_crr": [600.0, 400.0],
            "total_ead_b31": [600.0, 400.0],
            "total_rwa_crr": [200.0, 100.0],
            "total_rwa_b31": [240.0, 120.0],
            "total_delta_rwa": [40.0, 20.0],
        }
    )
    bundle = _comparison_bundle(summary_by_approach=by_approach)

    # Act
    summary = cmp.executive_summary(bundle)

    # Assert
    assert summary["crr_rwa"] == 300.0
    assert summary["b31_rwa"] == 360.0
    assert summary["delta_rwa"] == 60.0
    assert summary["delta_pct"] == 20.0
    assert summary["crr_avg_rw"] == 0.3
    assert summary["b31_avg_rw"] == 0.36


def test_executive_summary_zero_crr_rwa_does_not_divide_by_zero() -> None:
    # Arrange — empty/zero totals
    by_approach = pl.LazyFrame(
        {
            "total_ead_crr": [0.0],
            "total_ead_b31": [0.0],
            "total_rwa_crr": [0.0],
            "total_rwa_b31": [0.0],
        }
    )
    bundle = _comparison_bundle(summary_by_approach=by_approach)

    # Act
    summary = cmp.executive_summary(bundle)

    # Assert — guards return 0.0 rather than raising
    assert summary["delta_pct"] == 0.0
    assert summary["crr_avg_rw"] == 0.0


# =============================================================================
# waterfall_steps
# =============================================================================


def test_waterfall_steps_preserve_order_and_label_direction() -> None:
    # Arrange
    waterfall = pl.LazyFrame(
        {
            "step": [1, 2, 3],
            "driver": ["scaling_factor", "supporting_factor", "output_floor"],
            "impact_rwa": [-50.0, 0.0, 110.0],
            "cumulative_rwa": [950.0, 950.0, 1060.0],
        }
    )
    impact = _impact_bundle(waterfall)

    # Act
    steps = cmp.waterfall_steps(impact)

    # Assert
    assert [s["step"] for s in steps] == [1, 2, 3]
    assert [s["direction"] for s in steps] == ["decrease", "neutral", "increase"]
    assert steps[2]["cumulative_rwa"] == 1060.0


# =============================================================================
# summary_by_class / summary_by_approach
# =============================================================================


def test_summary_by_class_selects_and_sorts_by_delta_desc() -> None:
    # Arrange — unsorted, plus an extra column that must be dropped
    by_class = pl.LazyFrame(
        {
            "exposure_class": ["retail", "corporate"],
            "exposure_count": [10, 5],
            "total_ead_crr": [100.0, 200.0],
            "total_ead_b31": [100.0, 200.0],
            "total_rwa_crr": [50.0, 150.0],
            "total_rwa_b31": [60.0, 240.0],
            "total_delta_rwa": [10.0, 90.0],
            "delta_rwa_pct": [20.0, 60.0],
            "internal_only_column": ["x", "y"],
        }
    )
    bundle = _comparison_bundle(summary_by_class=by_class)

    # Act
    df = cmp.summary_by_class(bundle)

    # Assert — sorted by delta desc, internal column dropped
    assert df["exposure_class"].to_list() == ["corporate", "retail"]
    assert "internal_only_column" not in df.columns
    assert df.columns[0] == "exposure_class"


# =============================================================================
# summary_by_class_method
# =============================================================================


def _deltas_frame() -> pl.LazyFrame:
    """Per-exposure deltas: corporate spans STD+AIRB, retail is STD only."""
    return pl.LazyFrame(
        {
            "exposure_class": ["corporate", "corporate", "retail"],
            "method": ["STD", "AIRB", "STD"],
            "rwa_final_crr": [100.0, 300.0, 50.0],
            "rwa_final_b31": [120.0, 250.0, 60.0],
            "ead_final_crr": [1000.0, 2000.0, 500.0],
            "ead_final_b31": [1000.0, 2000.0, 500.0],
            "delta_rwa": [20.0, -50.0, 10.0],
        }
    )


def test_summary_by_class_method_partitions_class_by_method() -> None:
    # Arrange
    bundle = _comparison_bundle(exposure_deltas=_deltas_frame())

    # Act
    df = cmp.summary_by_class_method(bundle)

    # Assert — one row per (class, method), CRR/B31 suffixed, sorted by delta desc.
    assert set(zip(df["exposure_class"], df["method"], strict=True)) == {
        ("corporate", "STD"),
        ("corporate", "AIRB"),
        ("retail", "STD"),
    }
    assert {"total_rwa_crr", "total_rwa_b31", "total_delta_rwa", "delta_rwa_pct"} <= set(df.columns)
    assert df["total_delta_rwa"].to_list() == [20.0, 10.0, -50.0]  # desc


def test_summary_by_class_method_reconciles_with_summary_by_class() -> None:
    # Arrange: build both views from the SAME deltas frame.
    deltas = _deltas_frame()
    bundle = _comparison_bundle(
        exposure_deltas=deltas,
        summary_by_class=_class_totals(deltas),
    )

    # Act
    by_class = cmp.summary_by_class(bundle)
    by_method = cmp.summary_by_class_method(bundle)

    # Assert — summing the method rows within each class ties, cell-for-cell, to the
    # by-class totals shown alongside them (the core no-drift invariant).
    rolled = by_method.group_by("exposure_class").agg(
        pl.col("total_rwa_crr").sum(),
        pl.col("total_rwa_b31").sum(),
    )
    check = by_class.join(rolled, on="exposure_class", how="full", coalesce=True)
    assert (check["total_rwa_crr"] - check["total_rwa_crr_right"]).abs().max() == 0.0
    assert (check["total_rwa_b31"] - check["total_rwa_b31_right"]).abs().max() == 0.0


def test_summary_by_class_method_missing_columns_returns_empty() -> None:
    # Arrange: an empty (column-less) delta frame — e.g. a failed run.
    bundle = _comparison_bundle(exposure_deltas=pl.LazyFrame())

    # Act / Assert: degrades gracefully so the page still renders.
    assert cmp.summary_by_class_method(bundle).is_empty()


def _class_totals(deltas: pl.LazyFrame) -> pl.LazyFrame:
    """The by-class summary from the same deltas (mirrors analysis._compute_summary)."""
    return deltas.group_by("exposure_class").agg(
        pl.col("rwa_final_crr").sum().alias("total_rwa_crr"),
        pl.col("rwa_final_b31").sum().alias("total_rwa_b31"),
        pl.col("delta_rwa").sum().alias("total_delta_rwa"),
        pl.col("ead_final_crr").sum().alias("total_ead_crr"),
        pl.col("ead_final_b31").sum().alias("total_ead_b31"),
    )
