"""
Unit tests for compute_adjusted_notional_ir (P8.12).

Pins the expected behaviour of the IR adjusted notional formula per
CRR Art. 279b:

    d_i = N * (exp(-0.05 * S) - exp(-0.05 * E)) / 0.05

where:
    S = max(calendar_days(reporting → start) / 365, 10 / 250)  [floor = 0.04y]
    E = calendar_days(reporting → maturity) / 365

References:
- CRR Art. 279b: Adjusted notional amount (interest-rate and FX trades)
- CRR Art. 279b(1)(a): SD = (exp(-0.05*S) - exp(-0.05*E)) / 0.05
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Subject under test — will raise NotImplementedError until P8.12 is wired
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_ir
except (ImportError, ModuleNotFoundError) as _import_err:
    pytest.fail(
        f"Cannot import compute_adjusted_notional_ir from "
        f"rwa_calc.engine.ccr.adjusted_notional: {_import_err}. "
        "Check that the CCR engine scaffold (P8.4) is in place."
    )


# ===========================================================================
# 1. Spot-start 10-year trade — canonical example
# ===========================================================================


def test_adjusted_notional_ir_spot_start_ten_year() -> None:
    """Spot-start 10y IR trade: adjusted_notional = N * SD where S is floored.

    Arrange:
        notional = 100_000_000, start = reporting_date (spot), maturity = +10y.
        S_raw = 0 → clamped to 10BD/250 = 0.04y.
        E ≈ 3652 / 365 ≈ 10.005479y.
        SD = (exp(-0.05*0.04) - exp(-0.05*10.005479)) / 0.05 ≈ 7.832750.
        Expected adjusted_notional ≈ 7.833e8.

    Act: compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()

    Assert: adjusted_notional[0] ≈ 7.833e8 (rel=1e-3).

    References: CRR Art. 279b.
    """
    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001"],
            "asset_class": ["interest_rate"],
            "notional": [100_000_000.0],
            "start_date": [date(2026, 1, 15)],
            "maturity_date": [date(2036, 1, 15)],
        }
    )

    # Act
    try:
        result = compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_adjusted_notional_ir raised NotImplementedError: {exc}. "
            "P8.12 body not yet implemented."
        )

    # Assert
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(7.832750e8, rel=1e-3), (
        f"Spot-start 10y trade: expected adjusted_notional ≈ 7.833e8 "
        f"(N=1e8, S=0.04, E≈10.005y), got {actual!r}. "
        "CRR Art. 279b: d_i = N * (exp(-0.05*S) - exp(-0.05*E)) / 0.05."
    )


# ===========================================================================
# 2. S-floor clamp — 1-day-forward 5y trade
# ===========================================================================


def test_adjusted_notional_ir_start_floor_applies() -> None:
    """1-day-forward 5y trade: S_raw < floor so S clamps to 0.04y.

    Arrange:
        notional = 50_000_000, start = reporting + 1 day, maturity = +5y1d.
        S_raw = 1/365 ≈ 0.002740y < 0.04 → S = 0.04y.
        E ≈ 1827 / 365 ≈ 5.005479y.
        Expected adjusted_notional ≈ 2.194e8.

    Act: compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()

    Assert: adjusted_notional[0] ≈ 2.194e8 (rel=1e-3).

    References: CRR Art. 279b.
    """
    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-002"],
            "asset_class": ["interest_rate"],
            "notional": [50_000_000.0],
            "start_date": [date(2026, 1, 16)],
            "maturity_date": [date(2031, 1, 16)],
        }
    )

    # Act
    try:
        result = compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_adjusted_notional_ir raised NotImplementedError: {exc}. "
            "P8.12 body not yet implemented."
        )

    # Assert
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(2.193e8, rel=1e-3), (
        f"1-day-forward 5y trade: expected adjusted_notional ≈ 2.193e8 "
        f"(N=5e7, S=0.04 [floored], E≈5.005y), got {actual!r}. "
        "CRR Art. 279b: S floor = 10BD/250 = 0.04y."
    )


# ===========================================================================
# 3. Forward-start trade — S_raw above floor, no clamping
# ===========================================================================


def test_adjusted_notional_ir_forward_start() -> None:
    """2y-forward-start 5y trade: S_raw > floor, no S clamping.

    Arrange:
        notional = 10_000_000, start = reporting + 2y, maturity = +7y.
        S_raw = 730/365 = 2.000y > 0.04 → S = 2.000y (no clamp).
        E ≈ 2557 / 365 ≈ 7.005479y.
        Expected adjusted_notional ≈ 4.007e7.

    Act: compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()

    Assert: adjusted_notional[0] ≈ 4.007e7 (rel=1e-3).

    References: CRR Art. 279b.
    """
    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-003"],
            "asset_class": ["interest_rate"],
            "notional": [10_000_000.0],
            "start_date": [date(2028, 1, 15)],
            "maturity_date": [date(2033, 1, 15)],
        }
    )

    # Act
    try:
        result = compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_adjusted_notional_ir raised NotImplementedError: {exc}. "
            "P8.12 body not yet implemented."
        )

    # Assert
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(4.006e7, rel=1e-3), (
        f"2y-forward 5y trade: expected adjusted_notional ≈ 4.006e7 "
        f"(N=1e7, S=2.0y [no floor clamp], E≈7.005y), got {actual!r}. "
        "CRR Art. 279b."
    )


# ===========================================================================
# 4. Non-IR rows — adjusted_notional must be null
# ===========================================================================


def test_adjusted_notional_non_ir_row_returns_null() -> None:
    """Non-IR rows (e.g. FX) must have null adjusted_notional.

    The function only computes the IR branch; other asset classes receive
    a null in the adjusted_notional column.

    Arrange:
        2-row LazyFrame: 1 IR row + 1 FX row.

    Act: compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()

    Assert: the FX row's adjusted_notional is null.

    References: CRR Art. 279b(1) — formula applies to IR asset class only.
    """
    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001", "T-002"],
            "asset_class": ["interest_rate", "fx"],
            "notional": [100_000_000.0, 5_000_000.0],
            "start_date": [date(2026, 1, 15), date(2026, 1, 15)],
            "maturity_date": [date(2036, 1, 15), date(2028, 1, 15)],
        }
    )

    # Act
    try:
        result = compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15)).collect()
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_adjusted_notional_ir raised NotImplementedError: {exc}. "
            "P8.12 body not yet implemented."
        )

    # Assert
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row["adjusted_notional"].is_null()[0] is True, (
        f"FX row must have null adjusted_notional (function handles IR branch only). "
        f"Got {fx_row['adjusted_notional'][0]!r}. CRR Art. 279b."
    )


# ===========================================================================
# 5. Return type — must be LazyFrame (no eager collection inside the function)
# ===========================================================================


def test_adjusted_notional_returns_lazyframe() -> None:
    """compute_adjusted_notional_ir must return a pl.LazyFrame.

    The function must NOT call .collect() internally — pipeline materialisation
    is the caller's responsibility per the project's LazyFrame-first convention.

    Arrange: minimal 1-row IR LazyFrame.

    Act: call compute_adjusted_notional_ir without .collect().

    Assert: return value is pl.LazyFrame.
    """
    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001"],
            "asset_class": ["interest_rate"],
            "notional": [10_000_000.0],
            "start_date": [date(2026, 1, 15)],
            "maturity_date": [date(2031, 1, 15)],
        }
    )

    # Act
    try:
        result = compute_adjusted_notional_ir(lf, reporting_date=date(2026, 1, 15))
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_adjusted_notional_ir raised NotImplementedError: {exc}. "
            "P8.12 body not yet implemented."
        )

    # Assert
    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_ir must return pl.LazyFrame, got {type(result).__name__!r}. "
        "Never call .collect() inside the function."
    )
