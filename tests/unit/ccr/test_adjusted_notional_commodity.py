"""
Unit tests for compute_adjusted_notional_commodity (P8.37).

Pins the expected behaviour of the commodity adjusted-notional branch per
CRR Art. 279b(1)(c):

    d = market_price × number_of_units

Direction lives on ``is_long`` / ``delta``; the adjusted-notional is always
taken as the product of market_price and number_of_units (both positive scalars
per the regulatory formula — no conversion required as both are in the same
currency as the trade).

The function is coalesce-safe: it must not clobber an already-populated
``adjusted_notional`` from a prior IR or FX branch.

References:
- CRR Art. 279b(1)(c): commodity adjusted notional d = market_price × number_of_units
- BCBS CRE52.46-48
"""

from __future__ import annotations

import polars as pl
import pytest

# ===========================================================================
# 1. Oil forward: d = 50.0 × 20_000.0 = 1_000_000.0 (CCR-A7 hand-calc)
# ===========================================================================


def test_oil_hand_calc() -> None:
    """CCR-A7: d = market_price × number_of_units = 50.0 × 20_000.0 = 1_000_000.0.

    CRR Art. 279b(1)(c): for commodity trades the adjusted notional is the
    product of the current market price (GBP/bbl) and the number of units (bbl).
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_commodity

    # Arrange — single oil-forward row matching the CCR-A7 scenario.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_CO_OIL_001"],
            "asset_class": ["commodity"],
            "notional": [1_000_000.0],
            "currency": ["GBP"],
            "market_price": [50.0],
            "number_of_units": [20_000.0],
            "commodity_type": ["OIL_GAS"],
        }
    )

    # Act
    result = compute_adjusted_notional_commodity(trades).collect()

    # Assert — d = 50.0 × 20_000.0 = 1_000_000.0 GBP.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(1_000_000.0, rel=1e-12), (
        f"CCR-A7 oil forward: expected adjusted_notional = 1_000_000.0 GBP "
        f"(50.0 × 20_000.0), got {actual!r}. CRR Art. 279b(1)(c)."
    )


# ===========================================================================
# 2. Electricity swap: d = 25.0 × 40_000.0 = 1_000_000.0 (CCR-A8 hand-calc)
# ===========================================================================


def test_electricity_hand_calc() -> None:
    """CCR-A8: d = market_price × number_of_units = 25.0 × 40_000.0 = 1_000_000.0.

    CRR Art. 279b(1)(c): same formula for ELECTRICITY bucket; the adjusted
    notional equals market_price × number_of_units regardless of commodity type.
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_commodity

    # Arrange — single electricity-swap row matching the CCR-A8 scenario.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_CO_ELEC_001"],
            "asset_class": ["commodity"],
            "notional": [1_000_000.0],
            "currency": ["GBP"],
            "market_price": [25.0],
            "number_of_units": [40_000.0],
            "commodity_type": ["ELECTRICITY"],
        }
    )

    # Act
    result = compute_adjusted_notional_commodity(trades).collect()

    # Assert — d = 25.0 × 40_000.0 = 1_000_000.0 GBP.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(1_000_000.0, rel=1e-12), (
        f"CCR-A8 electricity swap: expected adjusted_notional = 1_000_000.0 GBP "
        f"(25.0 × 40_000.0), got {actual!r}. CRR Art. 279b(1)(c)."
    )


# ===========================================================================
# 3. Non-commodity row must produce null adjusted_notional
# ===========================================================================


def test_non_commodity_row_returns_null() -> None:
    """Non-commodity rows must receive a null adjusted_notional from this function.

    The commodity branch is selective: only ``asset_class == "commodity"`` rows
    are populated. IR / FX / credit / equity rows must remain null so callers
    can chain branches and coalesce.
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_commodity

    # Arrange — one IR row, one commodity row.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR_001", "T_CO_001"],
            "asset_class": ["interest_rate", "commodity"],
            "notional": [100_000_000.0, 1_000_000.0],
            "currency": ["GBP", "GBP"],
            "market_price": [None, 50.0],
            "number_of_units": [None, 20_000.0],
            "commodity_type": [None, "OIL_GAS"],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
            "commodity_type": pl.String,
        },
    )

    # Act
    result = compute_adjusted_notional_commodity(trades).collect()

    # Assert — IR row stays null.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"].is_null()[0] is True, (
        f"IR row from compute_adjusted_notional_commodity must be null, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — commodity row populated.
    co_row = result.filter(pl.col("asset_class") == "commodity")
    assert co_row["adjusted_notional"][0] == pytest.approx(1_000_000.0, rel=1e-12)


# ===========================================================================
# 4. Return type — must be LazyFrame
# ===========================================================================


def test_returns_lazyframe() -> None:
    """compute_adjusted_notional_commodity must return a pl.LazyFrame (no eager collection)."""
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_commodity

    trades = pl.LazyFrame(
        {
            "trade_id": ["T_CO_OIL_001"],
            "asset_class": ["commodity"],
            "notional": [1_000_000.0],
            "currency": ["GBP"],
            "market_price": [50.0],
            "number_of_units": [20_000.0],
            "commodity_type": ["OIL_GAS"],
        }
    )

    result = compute_adjusted_notional_commodity(trades)

    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_commodity must return pl.LazyFrame, "
        f"got {type(result).__name__!r}."
    )


# ===========================================================================
# 5. Coalesce-safe: prior IR/FX adjusted_notional must be preserved
# ===========================================================================


def test_preserves_prior_branches() -> None:
    """Commodity branch must not clobber an already-populated adjusted_notional.

    When the input already carries an ``adjusted_notional`` column (from a
    prior IR or FX branch), the commodity function must use coalesce semantics:
    preserve non-null values on non-commodity rows and overlay commodity rows
    only where adjusted_notional is currently null.
    """
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_commodity

    # Arrange — IR row has adjusted_notional pre-populated; commodity row is null.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR_001", "T_CO_001"],
            "asset_class": ["interest_rate", "commodity"],
            "notional": [100_000_000.0, 1_000_000.0],
            "currency": ["GBP", "GBP"],
            "market_price": [None, 50.0],
            "number_of_units": [None, 20_000.0],
            "commodity_type": [None, "OIL_GAS"],
            "adjusted_notional": [7.83e8, None],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
            "commodity_type": pl.String,
            "adjusted_notional": pl.Float64,
        },
    )

    # Act
    result = compute_adjusted_notional_commodity(trades).collect()

    # Assert — IR row's prior adjusted_notional is preserved.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"][0] == pytest.approx(7.83e8, rel=1e-12), (
        f"IR row's prior adjusted_notional must survive the commodity branch, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — commodity row populated with d = mp × units.
    co_row = result.filter(pl.col("asset_class") == "commodity")
    assert co_row["adjusted_notional"][0] == pytest.approx(1_000_000.0, rel=1e-12), (
        f"Commodity row must have adjusted_notional = 50.0 × 20_000.0 = 1_000_000.0, "
        f"got {co_row['adjusted_notional'][0]!r}."
    )
