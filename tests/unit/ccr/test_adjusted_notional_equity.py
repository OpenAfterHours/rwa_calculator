"""
Unit tests for compute_adjusted_notional_equity (P8.36).

Pins the expected behaviour of the equity adjusted-notional branch per
CRR Art. 279b(1)(c):

    d = abs(market_price × number_of_units)      when both are supplied
    d = abs(notional)                            otherwise (P1.406: the
                                                 article's notional limb)

Direction lives on ``is_long`` / ``delta``; the adjusted-notional value
itself is an absolute quantity.

References:
- CRR Art. 279b(1)(c): Equity adjusted notional d = market_price × number_of_units
"""

from __future__ import annotations

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _equity_trade_row(
    *,
    trade_id: str = "T_EQ_001",
    asset_class: str = "equity",
    market_price: float | None = 50.0,
    number_of_units: float | None = 1_000_000.0,
    notional: float | None = 0.0,
) -> pl.LazyFrame:
    """Single-row equity trade LazyFrame in the canonical CCR-A5 shape."""
    return pl.LazyFrame(
        {
            "trade_id": [trade_id],
            "asset_class": [asset_class],
            "notional": [notional],
            "currency": ["GBP"],
            "market_price": [market_price],
            "number_of_units": [number_of_units],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )


# ===========================================================================
# 1. Equity adjusted notional = market_price × number_of_units
# ===========================================================================


def test_equity_adjusted_notional_matches_market_price_times_units() -> None:
    """CCR-A5 load-bearing: d = 50.0 × 1_000_000 = 50_000_000 GBP (FP-exact).

    CRR Art. 279b(1)(c) defines the equity adjusted notional as the product
    of the market price per unit and the number of units. For the CCR-A5
    golden scenario this resolves to exactly 50_000_000.0 GBP.
    """
    # Arrange
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = _equity_trade_row(market_price=50.0, number_of_units=1_000_000.0)

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(50_000_000.0, rel=1e-12), (
        f"CCR-A5: expected adjusted_notional = 50_000_000.0 GBP "
        f"(market_price=50 × units=1m), got {actual!r}. CRR Art. 279b(1)(c)."
    )


# ===========================================================================
# 2. Absolute value — negative market_price must be treated as |price|
# ===========================================================================


def test_equity_adjusted_notional_uses_absolute_value() -> None:
    """Negative market_price must be treated as |market_price| × units.

    CRR Art. 279b(1)(c) gives d = |market_price × units|; sign lives on
    supervisory_delta (is_long / delta fields), not on the notional.
    """
    # Arrange
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = _equity_trade_row(market_price=-50.0, number_of_units=1_000_000.0)

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert — |−50 × 1_000_000| = 50_000_000.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(50_000_000.0, rel=1e-12), (
        f"Absolute-value: expected |−50 × 1m| = 50_000_000, "
        f"got {actual!r}. CRR Art. 279b(1)(c) is absolute-value."
    )


# ===========================================================================
# 3. Non-equity rows produce null adjusted_notional
# ===========================================================================


def test_equity_branch_emits_null_for_non_equity_rows() -> None:
    """compute_adjusted_notional_equity must only populate the equity branch.

    IR / FX / credit / commodity rows must still see null adjusted_notional
    so callers can chain the IR → FX → equity branches and coalesce.
    """
    # Arrange — one IR row, one equity row.
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR", "T_EQ"],
            "asset_class": ["interest_rate", "equity"],
            "notional": [100_000_000.0, 0.0],
            "currency": ["GBP", "GBP"],
            "market_price": [None, 50.0],
            "number_of_units": [None, 1_000_000.0],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert — IR row stays null.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"].is_null()[0] is True, (
        f"IR row from compute_adjusted_notional_equity must be null, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — equity row populated correctly.
    eq_row = result.filter(pl.col("asset_class") == "equity")
    assert eq_row["adjusted_notional"][0] == pytest.approx(50_000_000.0, rel=1e-12)


# ===========================================================================
# 4. Coalesce with prior IR/FX adjusted_notional — must not clobber upstream
# ===========================================================================


def test_equity_branch_coalesces_with_prior_ir_and_fx_adjusted_notional() -> None:
    """If the input already has adjusted_notional (from IR/FX branch), preserve it.

    The orchestrator chains IR → FX → equity; the equity branch must not
    clobber IR or FX rows' already-computed adjusted_notional.
    """
    # Arrange — IR row already has adjusted_notional=7.83e8; FX row has 80m;
    # equity row has null (not yet computed).
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR", "T_FX", "T_EQ"],
            "asset_class": ["interest_rate", "fx", "equity"],
            "notional": [100_000_000.0, 100_000_000.0, 0.0],
            "currency": ["GBP", "USD", "GBP"],
            "market_price": [None, None, 50.0],
            "number_of_units": [None, None, 1_000_000.0],
            "adjusted_notional": [7.83e8, 80_000_000.0, None],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
            "adjusted_notional": pl.Float64,
        },
    )

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert — IR row's prior value is preserved.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"][0] == pytest.approx(7.83e8, rel=1e-12), (
        f"IR row's prior adjusted_notional must survive the equity branch, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — FX row's prior value is preserved.
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row["adjusted_notional"][0] == pytest.approx(80_000_000.0, rel=1e-12)

    # Assert — equity row populated.
    eq_row = result.filter(pl.col("asset_class") == "equity")
    assert eq_row["adjusted_notional"][0] == pytest.approx(50_000_000.0, rel=1e-12)


# ===========================================================================
# 5-6. No market price x units -> the contractual notional (Art. 279b(1)(c))
#      (P1.406; these tests used to pin a null result, which priced the
#      equity add-on at zero with no error)
# ===========================================================================


@pytest.mark.parametrize(
    ("market_price", "number_of_units"),
    [(None, 1_000_000.0), (50.0, None), (None, None)],
)
def test_equity_without_price_times_units_takes_the_notional(
    market_price: float | None, number_of_units: float | None
) -> None:
    """A trade expressed as a notional amount: d = |notional| (reported CCR035).

    Art. 279b(1)(c): "where a transaction mapped to the equity risk category or
    commodity risk category is contractually expressed as a notional amount,
    institutions shall use the notional amount of the transaction".
    """
    # Arrange
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = _equity_trade_row(
        market_price=market_price, number_of_units=number_of_units, notional=-40_000_000.0
    )

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(40_000_000.0, rel=1e-12)


def test_equity_price_times_units_takes_precedence_over_the_notional() -> None:
    """Both limbs supplied: market price x units is used (CCR-A5 / A6 do not move)."""
    # Arrange
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = _equity_trade_row(market_price=50.0, number_of_units=1_000_000.0, notional=1.0)

    # Act
    result = compute_adjusted_notional_equity(trades).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(50_000_000.0, rel=1e-12)


# ===========================================================================
# 7. Return type — LazyFrame, no eager collection
# ===========================================================================


def test_equity_branch_returns_lazyframe() -> None:
    """compute_adjusted_notional_equity must return a pl.LazyFrame (no internal .collect)."""
    from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_equity

    trades = _equity_trade_row()
    result = compute_adjusted_notional_equity(trades)
    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_equity must return pl.LazyFrame, got {type(result).__name__!r}."
    )
