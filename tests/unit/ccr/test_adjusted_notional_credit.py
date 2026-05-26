"""
Unit tests for compute_adjusted_notional_credit (P8.35).

Pins the expected behaviour of the credit adjusted notional formula per
CRR Art. 279b(1)(a):

    d = N × SD(S, E)
    SD(S, E) = (exp(-0.05 × S) − exp(-0.05 × E)) / 0.05

where S is the years-to-start floored at 10 business days (10/250 = 0.04y)
and E is the years-to-maturity. The formula is structurally identical to the
IR supervisory-duration formula — credit shares the same ``SD(S, E)`` kernel.

References:
- CRR Art. 279b(1)(a): adjusted notional for IR and credit derivatives.
- BCBS CRE52.41-43: supervisory duration shared with IR.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest


# ---------------------------------------------------------------------------
# Subject under test — imported inside tests to convert ImportError to
# assertion failure (not collection error), per test-writer convention.
# ---------------------------------------------------------------------------


# ===========================================================================
# Helpers
# ===========================================================================


def _credit_trade_row(
    *,
    trade_id: str = "T_CR_001",
    notional: float = 100_000_000.0,
    start_date: date = date(2026, 1, 15),
    maturity_date: date = date(2031, 1, 15),
    asset_class: str = "credit",
) -> pl.LazyFrame:
    """Return a minimal single-row credit-trade LazyFrame."""
    return pl.LazyFrame(
        {
            "trade_id": [trade_id],
            "asset_class": [asset_class],
            "notional": [notional],
            "start_date": [start_date],
            "maturity_date": [maturity_date],
        }
    )


# ===========================================================================
# 1. Spot-start 5-year credit trade — CCR-A3 load-bearing value
# ===========================================================================


def test_adjusted_notional_credit_spot_start_five_year() -> None:
    """CCR-A3: spot-start 5y CDS gives adjusted_notional ≈ 438,349,124.271 GBP.

    Arrange:
        notional = 100m, start = reporting_date = 2026-01-15 (spot),
        maturity = 2031-01-15 (1826 calendar days away).
        S_raw = 0 → clamped to 0.04y (10 BD / 250).
        E = 1826 / 365.25 = 4.9993155373y  (full-precision 365.25 convention).
        SD(0.04, 4.9993155373)
            = (exp(-0.002) − exp(-0.24996578)) / 0.05
            ≈ (0.998002 − 0.778716) / 0.05 ≈ 4.3834912427.
        d = 100m × 4.3834912427 ≈ 438,349,124.271 GBP.

    Act: compute_adjusted_notional_credit(lf, reporting_date=date(2026, 1, 15))

    Assert: adjusted_notional ≈ 4.383e8 (rel=1e-4 to allow full-precision match).

    References: CRR Art. 279b(1)(a); BCBS CRE52.41.
    """
    # Arrange
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_credit

    lf = _credit_trade_row(
        start_date=date(2026, 1, 15),
        maturity_date=date(2031, 1, 15),
    )

    # Act
    result = compute_adjusted_notional_credit(lf, reporting_date=date(2026, 1, 15)).collect()

    # Assert — CCR-A3 load-bearing number: d = N × SD(S, E).
    actual = result["adjusted_notional"][0]
    expected = 438_349_124.271  # full-precision: E = 1826/365.25 = 4.9993155373
    assert actual == pytest.approx(expected, rel=1e-4), (
        f"CCR-A3 spot-start 5y: expected adjusted_notional ≈ {expected:,.3f} GBP, "
        f"got {actual!r}. d = N × SD(0.04, 4.9993155373). CRR Art. 279b(1)(a)."
    )


# ===========================================================================
# 2. 1-day-fwd start: S_raw < 0.04 → floor applies
# ===========================================================================


def test_adjusted_notional_credit_start_floor_applies() -> None:
    """1-day-fwd 3y CDS: S_raw ≈ 0.00274 < 0.04 so S is clamped to 0.04.

    Arrange:
        start_date = reporting_date + 1 calendar day.
        maturity_date = reporting_date + 3 years.
        S_raw = 1 / 365.25 ≈ 0.00274 < floor 0.04 → S_used = 0.04.

    Assert: the computed adjusted_notional equals the value computed with S=0.04,
    not with S=0.00274. We verify this by checking that the result is strictly
    less than the value that would arise from S=0 (which equals reporting_date start).

    References: CRR Art. 279b(1)(a) (10-BD floor on S).
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_credit

    # Arrange — start 1 day after reporting date (sub-floor).
    reporting = date(2026, 1, 15)
    lf = _credit_trade_row(
        start_date=date(2026, 1, 16),   # S_raw = 1/365.25 ≈ 0.00274
        maturity_date=date(2029, 1, 15),  # E = 3y
    )

    # Act
    result = compute_adjusted_notional_credit(lf, reporting_date=reporting).collect()
    actual = result["adjusted_notional"][0]

    # Assert: S is clamped to 0.04, so SD(0.04, 3y) < SD(0, 3y).
    # SD(0.04, 3y) = (exp(-0.002) − exp(-0.15)) / 0.05 ≈ (0.998002 − 0.860708) / 0.05 ≈ 2.74587
    # If floor did NOT apply, SD(0.00274, 3y) would be slightly larger.
    # The key invariant is: result == SD(0.04, E) × N — the floor clamps S.
    import math
    s_floored = 0.04
    e = (date(2029, 1, 15) - reporting).days / 365.25
    rate = 0.05
    sd_with_floor = (math.exp(-rate * s_floored) - math.exp(-rate * e)) / rate
    expected_with_floor = 100_000_000.0 * sd_with_floor

    sd_without_floor = (math.exp(-rate * (1 / 365.25)) - math.exp(-rate * e)) / rate
    expected_without_floor = 100_000_000.0 * sd_without_floor

    # The computed value must match the floored calculation, not the raw one.
    assert actual == pytest.approx(expected_with_floor, rel=1e-6), (
        f"1-day-fwd 3y: expected floor to apply (S=0.04), "
        f"expected_with_floor={expected_with_floor:,.2f}, "
        f"expected_without_floor={expected_without_floor:,.2f}, "
        f"got {actual!r}. CRR Art. 279b(1)(a) floor."
    )
    # Sanity: without-floor would give a different answer.
    assert not pytest.approx(expected_without_floor, rel=1e-6) == actual or abs(
        expected_with_floor - expected_without_floor
    ) < 1.0, (
        "Floor and non-floor values are unexpectedly equal — test is not discriminating."
    )


# ===========================================================================
# 3. Forward-start 2y → 5y: S = 2.0 (no clamping)
# ===========================================================================


def test_adjusted_notional_credit_forward_start() -> None:
    """2y-fwd 5y CDS: S = 2.0 (above floor), no clamping.

    Arrange:
        start_date = reporting_date + 2 years = 2028-01-15.
        maturity_date = reporting_date + 5 years = 2031-01-15.
        S ≈ 2.0y (well above floor), E ≈ 5.0y.
        SD(2.0, 5.0) = (exp(-0.1) − exp(-0.25)) / 0.05 ≈ (0.904837 − 0.778801) / 0.05
                     ≈ 2.520716.
        d = 100m × 2.520716 ≈ 252,071,600 GBP.

    References: CRR Art. 279b(1)(a).
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_credit
    import math

    reporting = date(2026, 1, 15)
    lf = _credit_trade_row(
        start_date=date(2028, 1, 15),
        maturity_date=date(2031, 1, 15),
    )

    # Act
    result = compute_adjusted_notional_credit(lf, reporting_date=reporting).collect()
    actual = result["adjusted_notional"][0]

    # Compute expected using exact same formula.
    e = (date(2031, 1, 15) - reporting).days / 365.25
    s = (date(2028, 1, 15) - reporting).days / 365.25
    s_used = max(s, 0.04)  # floor — but s ≈ 2.0 so no effect
    rate = 0.05
    sd = (math.exp(-rate * s_used) - math.exp(-rate * e)) / rate
    expected = 100_000_000.0 * sd

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"2y-fwd 5y CDS: expected adjusted_notional ≈ {expected:,.0f} GBP, "
        f"got {actual!r}. S ≈ 2.0 (no floor). CRR Art. 279b(1)(a)."
    )


# ===========================================================================
# 4. Non-credit row returns null
# ===========================================================================


def test_adjusted_notional_non_credit_row_returns_null() -> None:
    """Non-credit rows must receive null adjusted_notional from this branch.

    The credit branch, like the IR branch, is gated on asset_class == "credit".
    FX / IR / equity / commodity rows must remain null so callers can coalesce.

    References: CRR Art. 279b (each sub-article covers exactly one asset class).
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_credit

    # Arrange — one IR row, one FX row, one credit row.
    lf = pl.LazyFrame(
        {
            "trade_id": ["T_IR", "T_FX", "T_CR"],
            "asset_class": ["interest_rate", "fx", "credit"],
            "notional": [100_000_000.0, 100_000_000.0, 100_000_000.0],
            "start_date": [date(2026, 1, 15), date(2026, 1, 15), date(2026, 1, 15)],
            "maturity_date": [date(2031, 1, 15), date(2031, 1, 15), date(2031, 1, 15)],
        }
    )

    # Act
    result = compute_adjusted_notional_credit(lf, reporting_date=date(2026, 1, 15)).collect()

    # Assert — non-credit rows stay null.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"][0] is None, (
        f"IR row from compute_adjusted_notional_credit must be null, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row["adjusted_notional"][0] is None, (
        f"FX row from compute_adjusted_notional_credit must be null, "
        f"got {fx_row['adjusted_notional'][0]!r}."
    )

    # Credit row should be populated.
    cr_row = result.filter(pl.col("asset_class") == "credit")
    assert cr_row["adjusted_notional"][0] is not None, (
        "Credit row from compute_adjusted_notional_credit must not be null."
    )


# ===========================================================================
# 5. Return type — LazyFrame, no eager collection
# ===========================================================================


def test_adjusted_notional_credit_returns_lazyframe() -> None:
    """compute_adjusted_notional_credit must return a pl.LazyFrame (no internal .collect)."""
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_credit

    lf = _credit_trade_row()
    result = compute_adjusted_notional_credit(lf, reporting_date=date(2026, 1, 15))
    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_credit must return pl.LazyFrame, "
        f"got {type(result).__name__!r}."
    )
