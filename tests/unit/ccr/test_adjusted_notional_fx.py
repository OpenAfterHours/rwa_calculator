"""
Unit tests for compute_adjusted_notional_fx (P8.9).

Pins the expected behaviour of the FX adjusted-notional branch per
CRR Art. 279b(1)(b):

    (i)  If one leg is the reporting (base) currency, adjusted_notional
         equals the *other* leg's notional converted to the base currency
         at the prevailing spot rate.
    (ii) If both legs are denominated in non-base currencies, adjusted_notional
         equals the larger of the two leg notionals converted to the base
         currency at spot.

Direction lives on ``is_long`` / ``delta``; the adjusted-notional comparison
itself is in absolute terms.

References:
- CRR Art. 279b(1)(b)(i): one-leg-is-base case.
- CRR Art. 279b(1)(b)(ii): both-legs-foreign max-of-converted case.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_fx


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fx_rates_to_gbp() -> pl.LazyFrame:
    """Minimal FX-rates LazyFrame: USD -> GBP at 0.80, EUR -> GBP at 0.85."""
    return pl.LazyFrame(
        {
            "currency_from": ["USD", "EUR"],
            "currency_to": ["GBP", "GBP"],
            "rate": [0.80, 0.85],
        },
        schema={"currency_from": pl.String, "currency_to": pl.String, "rate": pl.Float64},
    )


def _fx_trade_row(
    *,
    trade_id: str = "T_FX_001",
    notional: float = 100_000_000.0,
    currency: str = "USD",
    notional_leg2: float | None = 80_000_000.0,
    currency_leg2: str | None = "GBP",
) -> pl.LazyFrame:
    """Single-row FX trade LazyFrame in the canonical CCR-A2 shape."""
    return pl.LazyFrame(
        {
            "trade_id": [trade_id],
            "asset_class": ["fx"],
            "notional": [notional],
            "currency": [currency],
            "notional_leg2": [notional_leg2],
            "currency_leg2": [currency_leg2],
        }
    )


# ===========================================================================
# 1. One leg is reporting currency — Art. 279b(1)(b)(i)
# ===========================================================================


def test_fx_adjusted_notional_leg2_is_base_takes_leg1_converted() -> None:
    """CCR-A2 default: buy USD 100m / sell GBP 80m, base=GBP → 80m GBP.

    Leg2 is GBP (base) so Art. 279b(1)(b)(i) takes the *other* leg's notional
    converted to GBP at spot: 100m USD × 0.80 USD→GBP = 80m GBP.
    """
    # Arrange
    trades = _fx_trade_row(currency="USD", notional=100_000_000.0,
                            currency_leg2="GBP", notional_leg2=80_000_000.0)

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — Art. 279b(1)(b)(i): take USD leg converted = 100m × 0.80 = 80m GBP.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(80_000_000.0, rel=1e-12), (
        f"One-leg-base FX trade (USD/GBP, base=GBP): expected adjusted_notional "
        f"= 80m GBP (USD leg converted), got {actual!r}. CRR Art. 279b(1)(b)(i)."
    )


def test_fx_adjusted_notional_leg1_is_base_takes_leg2_converted() -> None:
    """Mirror-image: leg1 = GBP (base) → take leg2 (USD) converted to GBP.

    Should produce the same answer as the previous test up to the leg ordering.
    """
    # Arrange — same trade with legs swapped: sell GBP 80m / buy USD 100m.
    trades = _fx_trade_row(currency="GBP", notional=80_000_000.0,
                            currency_leg2="USD", notional_leg2=100_000_000.0)

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — Art. 279b(1)(b)(i): take USD leg (leg2) converted = 100m × 0.80 = 80m GBP.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(80_000_000.0, rel=1e-12), (
        f"Leg-swap FX trade (GBP/USD, base=GBP): expected adjusted_notional "
        f"= 80m GBP (USD leg converted), got {actual!r}. CRR Art. 279b(1)(b)(i)."
    )


# ===========================================================================
# 2. Both legs non-base — Art. 279b(1)(b)(ii) max-of-converted
# ===========================================================================


def test_fx_adjusted_notional_both_legs_foreign_takes_max() -> None:
    """Both legs foreign: take max(leg1 converted, leg2 converted) per Art. 279b(1)(b)(ii).

    EUR 100m vs USD 80m with base=GBP:
        EUR converted: 100m × 0.85 = 85m GBP
        USD converted:  80m × 0.80 = 64m GBP
    max = 85m GBP (EUR leg dominates).
    """
    # Arrange
    trades = _fx_trade_row(currency="EUR", notional=100_000_000.0,
                            currency_leg2="USD", notional_leg2=80_000_000.0)

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — Art. 279b(1)(b)(ii): max(85m, 64m) = 85m GBP.
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(85_000_000.0, rel=1e-12), (
        f"Both-foreign FX trade (EUR/USD, base=GBP): expected adjusted_notional "
        f"= max(85m, 64m) = 85m GBP, got {actual!r}. CRR Art. 279b(1)(b)(ii)."
    )


# ===========================================================================
# 3. Negative notional — direction lives on is_long, not on |notional|
# ===========================================================================


def test_fx_adjusted_notional_uses_absolute_value() -> None:
    """Negative notional must be treated as |notional| — sign lives on is_long/delta.

    Art. 279b(1)(b) speaks of "the notional amount of the leg" without sign;
    the comparison is in absolute terms and the directional sign flows
    through ``supervisory_delta`` further down the pipeline.
    """
    # Arrange — short USD leg (negative notional) should still convert as 80m GBP.
    trades = _fx_trade_row(currency="USD", notional=-100_000_000.0,
                            currency_leg2="GBP", notional_leg2=80_000_000.0)

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert
    actual = result["adjusted_notional"][0]
    assert actual == pytest.approx(80_000_000.0, rel=1e-12), (
        f"Negative-notional FX trade: expected |−100m| × 0.80 = 80m GBP, "
        f"got {actual!r}. CRR Art. 279b(1)(b) is absolute-value."
    )


# ===========================================================================
# 4. Non-FX rows produce null adjusted_notional
# ===========================================================================


def test_fx_branch_emits_null_for_non_fx_rows() -> None:
    """compute_adjusted_notional_fx must only populate the FX branch.

    IR / credit / equity / commodity rows must still see null adjusted_notional
    so callers can chain the IR branch and coalesce.
    """
    # Arrange — one IR row, one FX row.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR", "T_FX"],
            "asset_class": ["interest_rate", "fx"],
            "notional": [100_000_000.0, 100_000_000.0],
            "currency": ["GBP", "USD"],
            "notional_leg2": [None, 80_000_000.0],
            "currency_leg2": [None, "GBP"],
        }
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — IR row stays null.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"].is_null()[0] is True, (
        f"IR row from compute_adjusted_notional_fx must be null, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — FX row populated correctly.
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row["adjusted_notional"][0] == pytest.approx(80_000_000.0, rel=1e-12)


# ===========================================================================
# 5. Coalesce with prior IR-branch output
# ===========================================================================


def test_fx_branch_coalesces_with_prior_ir_adjusted_notional() -> None:
    """If the input already has adjusted_notional (from the IR branch), preserve it.

    The orchestrator chains IR -> FX; the FX branch must not clobber IR rows'
    already-computed adjusted_notional.
    """
    # Arrange — IR row already has adjusted_notional=7.83e8, FX row has null.
    trades = pl.LazyFrame(
        {
            "trade_id": ["T_IR", "T_FX"],
            "asset_class": ["interest_rate", "fx"],
            "notional": [100_000_000.0, 100_000_000.0],
            "currency": ["GBP", "USD"],
            "notional_leg2": [None, 80_000_000.0],
            "currency_leg2": [None, "GBP"],
            "adjusted_notional": [7.83e8, None],
        }
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — IR row's prior value is preserved.
    ir_row = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_row["adjusted_notional"][0] == pytest.approx(7.83e8, rel=1e-12), (
        f"IR row's prior adjusted_notional must survive the FX branch, "
        f"got {ir_row['adjusted_notional'][0]!r}."
    )

    # Assert — FX row populated.
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row["adjusted_notional"][0] == pytest.approx(80_000_000.0, rel=1e-12)


# ===========================================================================
# 6. Missing-rate join leaves adjusted_notional null
# ===========================================================================


def test_fx_missing_rate_yields_null_adjusted_notional() -> None:
    """If neither leg has a rate in fx_rates, adjusted_notional must be null.

    The orchestrator detects the null at the pipeline-adapter boundary and
    emits the CCR data-quality error — this function stays LazyFrame-pure.
    """
    # Arrange — JPY/SGD pair with no rates supplied to the base currency.
    trades = _fx_trade_row(currency="JPY", notional=1_000_000.0,
                            currency_leg2="SGD", notional_leg2=10_000.0)

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert — no usable rate so the converted values are null → adjusted_notional is null.
    actual = result["adjusted_notional"][0]
    assert actual is None, (
        f"Missing FX rate must produce null adjusted_notional (orchestrator "
        f"emits CCR error), got {actual!r}."
    )


# ===========================================================================
# 7. Return type — LazyFrame, no eager collection
# ===========================================================================


def test_fx_branch_returns_lazyframe() -> None:
    """compute_adjusted_notional_fx must return a pl.LazyFrame (no internal .collect)."""
    trades = _fx_trade_row()
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp())
    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_fx must return pl.LazyFrame, "
        f"got {type(result).__name__!r}."
    )
