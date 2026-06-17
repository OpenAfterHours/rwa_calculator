"""
Unit tests for _compute_portfolio_waterfall LazyFrame contract (P6.21).

Tests that the portfolio waterfall helper:
- Contains no eager mid-pipeline .collect() in its body (FAIL-first driver)
- Returns a pl.LazyFrame (regression pin)
- Produces the correct 4-row waterfall with accurate cumulative sums (regression pin)

Why these tests matter:
    The pipeline convention is LazyFrame-first; .collect() must only happen at the
    final output boundary. _compute_portfolio_waterfall currently performs an eager
    materialisation at line ~762 to extract scalar totals. P6.21 removes that
    collect so the function is fully lazy. The no-eager-collect test FAILS today
    and PASSES after the Wave-4 refactor; the return-type and value-invariance
    tests PASS both before and after, pinning the observable contract.
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from rwa_calc.analysis import comparison as cmp_mod
from rwa_calc.analysis.comparison import (
    _DRIVER_FLOOR,
    _DRIVER_METHODOLOGY,
    _DRIVER_SCALING,
    _DRIVER_SUPPORTING,
    _compute_portfolio_waterfall,
)

# =============================================================================
# Shared inline attribution frame
# =============================================================================
#
# Two rows whose column sums produce clean totals:
#   total_rwa_crr       = 1 000.0
#   total_scaling       =   -60.0   (scaling_factor_impact)
#   total_supporting    =   -40.0   (supporting_factor_impact)
#   total_methodology   =   100.0
#   total_floor         =   200.0
#   total_rwa_b31       = 1 200.0   (must equal crr + scaling + supporting + methodology + floor)
#
# Cumulative waterfall (additive, in driver order: scaling → supporting → methodology → floor):
#   step 1 (scaling):     1000 + (-60)          = 940.0
#   step 2 (supporting):  940  + (-40)          = 900.0
#   step 3 (methodology): 900  + 100            = 1000.0
#   step 4 (floor):       1000 + 200            = 1200.0

_ATTRIBUTION_DATA: dict[str, list[float]] = {
    "rwa_crr": [600.0, 400.0],
    "scaling_factor_impact": [-36.0, -24.0],
    "supporting_factor_impact": [-24.0, -16.0],
    "methodology_impact": [60.0, 40.0],
    "output_floor_impact": [120.0, 80.0],
    "rwa_b31": [720.0, 480.0],
}


@pytest.fixture()
def attribution_lf() -> pl.LazyFrame:
    """Inline attribution LazyFrame with six required columns and two rows."""
    return pl.LazyFrame(_ATTRIBUTION_DATA)


# =============================================================================
# Tests
# =============================================================================


def test_compute_portfolio_waterfall_no_eager_collect() -> None:
    """_compute_portfolio_waterfall must contain no mid-pipeline .collect() (P6.21).

    The function currently materialises the LazyFrame at line ~762 to extract
    scalar totals. This test FAILS today and PASSES after the Wave-4 refactor
    that makes the function fully lazy.
    """
    # Arrange
    src = inspect.getsource(cmp_mod._compute_portfolio_waterfall)

    # Act / Assert
    assert ".collect(" not in src, (
        "_compute_portfolio_waterfall must be fully lazy (LazyFrame-first): "
        "no mid-pipeline .collect() in its body (P6.21)"
    )


def test_compute_portfolio_waterfall_returns_lazy_frame(
    attribution_lf: pl.LazyFrame,
) -> None:
    """_compute_portfolio_waterfall must return a pl.LazyFrame (regression pin).

    This passes today (the function re-wraps with .lazy() at the end) and must
    continue to pass after the Wave-4 refactor.
    """
    # Arrange — attribution_lf provided by fixture

    # Act
    result = _compute_portfolio_waterfall(attribution_lf)

    # Assert
    assert isinstance(result, pl.LazyFrame), f"Expected pl.LazyFrame, got {type(result).__name__}"


def test_compute_portfolio_waterfall_value_invariance(
    attribution_lf: pl.LazyFrame,
) -> None:
    """Waterfall rows match hand-derived expected values (regression pin, P6.21).

    Confirms step order (scaling → supporting → methodology → floor), impact_rwa
    per step, cumulative_rwa arithmetic, and that the final cumulative_rwa equals
    total_rwa_b31 (1200.0).  This must hold both before and after the Wave-4 refactor.
    """
    # Arrange
    expected_steps = [1, 2, 3, 4]
    expected_drivers = [
        _DRIVER_SCALING,
        _DRIVER_SUPPORTING,
        _DRIVER_METHODOLOGY,
        _DRIVER_FLOOR,
    ]
    expected_impact = [-60.0, -40.0, 100.0, 200.0]
    expected_cumulative = [940.0, 900.0, 1000.0, 1200.0]
    expected_final_b31 = 1200.0

    # Act
    result = _compute_portfolio_waterfall(attribution_lf)
    df = result.collect()

    # Assert — schema
    assert set(df.columns) >= {"step", "driver", "impact_rwa", "cumulative_rwa"}, (
        f"Unexpected schema: {df.columns}"
    )
    assert df.schema["step"] == pl.Int32, "step column must be Int32"
    assert df.schema["driver"] == pl.String, "driver column must be String"
    assert df.schema["impact_rwa"] == pl.Float64, "impact_rwa column must be Float64"
    assert df.schema["cumulative_rwa"] == pl.Float64, "cumulative_rwa must be Float64"

    # Assert — row count
    assert len(df) == 4, f"Expected 4 waterfall rows, got {len(df)}"

    # Assert — step numbers
    assert df["step"].to_list() == expected_steps, f"Step order mismatch: {df['step'].to_list()}"

    # Assert — driver labels
    assert df["driver"].to_list() == expected_drivers, (
        f"Driver label mismatch: {df['driver'].to_list()}"
    )

    # Assert — impact_rwa values
    actual_impact = df["impact_rwa"].to_list()
    for i, (actual, expected) in enumerate(zip(actual_impact, expected_impact, strict=True)):
        assert abs(actual - expected) < 1e-9, f"impact_rwa[{i}]: expected {expected}, got {actual}"

    # Assert — cumulative_rwa values
    actual_cumulative = df["cumulative_rwa"].to_list()
    cumulative_pairs = zip(actual_cumulative, expected_cumulative, strict=True)
    for i, (actual, expected) in enumerate(cumulative_pairs):
        assert abs(actual - expected) < 1e-9, (
            f"cumulative_rwa[{i}]: expected {expected}, got {actual}"
        )

    # Assert — final cumulative_rwa equals total_rwa_b31
    assert abs(actual_cumulative[-1] - expected_final_b31) < 1e-9, (
        f"Final cumulative_rwa {actual_cumulative[-1]} != total_rwa_b31 {expected_final_b31}"
    )
