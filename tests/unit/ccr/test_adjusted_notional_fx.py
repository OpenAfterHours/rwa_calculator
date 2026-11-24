"""
Unit tests for compute_adjusted_notional_fx (P8.9).

Pins the expected behaviour of the FX adjusted-notional branch per
CCR (CRR) Part Art. 279b(1)(b) and (3) (unchanged by PS1/26):

    (i)   One payment leg: adjusted_notional equals the contract notional.
    (ii)  One leg in the reporting (base) currency: adjusted_notional equals
          the *other* leg's notional converted to the base currency at spot.
    (iii) Both legs in non-base currencies: adjusted_notional equals the
          larger of the two leg notionals converted to the base currency at
          spot.

A leg with no spot rate enters unconverted and the larger leg is taken
(P1.406), so a missing rate never yields a null adjusted notional.

Direction lives on ``is_long`` / ``delta``; the adjusted-notional comparison
itself is in absolute terms.

References:
- CRR Art. 279b(1)(b)(i): one payment leg.
- CRR Art. 279b(1)(b)(ii): one-leg-is-base case.
- CRR Art. 279b(1)(b)(iii): both-legs-foreign max-of-converted case.
"""

from __future__ import annotations

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
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "notional_leg2": pl.Float64,
            "currency_leg2": pl.String,
        },
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
    trades = _fx_trade_row(
        currency="USD", notional=100_000_000.0, currency_leg2="GBP", notional_leg2=80_000_000.0
    )

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
    trades = _fx_trade_row(
        currency="GBP", notional=80_000_000.0, currency_leg2="USD", notional_leg2=100_000_000.0
    )

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
    trades = _fx_trade_row(
        currency="EUR", notional=100_000_000.0, currency_leg2="USD", notional_leg2=80_000_000.0
    )

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
    trades = _fx_trade_row(
        currency="USD", notional=-100_000_000.0, currency_leg2="GBP", notional_leg2=80_000_000.0
    )

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
# 6. Missing rate / single payment leg — never a null adjusted notional
#    (P1.406; before it each of these returned null and priced a zero add-on)
# ===========================================================================


def test_fx_missing_rates_take_the_largest_unconverted_leg() -> None:
    """Neither leg has a rate: the larger leg notional, unconverted (reported CCR026).

    JPY 1m / SGD 10k with no JPY or SGD rate to GBP: max(1,000,000, 10,000).
    This test used to pin a null result, which priced the FX add-on at zero
    (Art. 278(1) includes the add-on of every risk category a trade maps to).
    """
    # Arrange
    trades = _fx_trade_row(
        currency="JPY", notional=1_000_000.0, currency_leg2="SGD", notional_leg2=10_000.0
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(1_000_000.0, rel=1e-12)


@pytest.mark.parametrize(
    ("currency", "notional", "currency_leg2", "notional_leg2", "expected"),
    [
        # (ii) with the foreign leg's rate missing: max(GBP 80m, CHF 100m unconverted)
        ("GBP", 80_000_000.0, "CHF", 100_000_000.0, 100_000_000.0),
        # same, legs swapped
        ("CHF", 100_000_000.0, "GBP", 80_000_000.0, 100_000_000.0),
        # (ii) with the foreign leg's rate missing, reporting leg the larger
        ("GBP", 120_000_000.0, "CHF", 100_000_000.0, 120_000_000.0),
        # (iii) with one rate missing: max(EUR 90m x 0.85, CHF 100m unconverted)
        ("EUR", 90_000_000.0, "CHF", 100_000_000.0, 100_000_000.0),
        # (iii) with one rate missing, the converted leg the larger
        ("EUR", 200_000_000.0, "CHF", 100_000_000.0, 170_000_000.0),
        # a second leg with no currency at all
        ("GBP", 80_000_000.0, None, 100_000_000.0, 100_000_000.0),
    ],
)
def test_fx_leg_without_a_rate_never_lowers_the_adjusted_notional(
    currency: str,
    notional: float,
    currency_leg2: str | None,
    notional_leg2: float,
    expected: float,
) -> None:
    """A leg with no rate enters unconverted, and the largest leg is taken."""
    # Arrange
    trades = _fx_trade_row(
        currency=currency,
        notional=notional,
        currency_leg2=currency_leg2,
        notional_leg2=notional_leg2,
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        ("GBP", 80_000_000.0),  # reporting-currency single leg: its own notional
        ("USD", 64_000_000.0),  # foreign single leg: converted at spot (Art. 279b(3))
        ("CHF", 80_000_000.0),  # foreign single leg with no rate: unconverted
    ],
)
def test_fx_single_payment_leg_takes_the_contract_notional(currency: str, expected: float) -> None:
    """Art. 279b(1)(b)(i): one payment leg -> the notional of the contract.

    The GBP case returned null before P1.406 (the reporting-currency branch read
    the absent second leg).
    """
    # Arrange
    trades = _fx_trade_row(
        currency=currency, notional=80_000_000.0, currency_leg2=None, notional_leg2=None
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(expected, rel=1e-12)


def test_fx_branch_runs_without_an_fx_rates_table() -> None:
    """No fx_rates table: only the reporting currency converts (identity), the rest unconverted.

    GBP 80m / USD 100m with no table at all: max(80m, 100m) = 100m.
    """
    # Arrange
    trades = _fx_trade_row(
        currency="GBP", notional=80_000_000.0, currency_leg2="USD", notional_leg2=100_000_000.0
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", None).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(100_000_000.0, rel=1e-12)


@pytest.mark.parametrize(
    ("currency", "notional", "currency_leg2", "expected", "own_hedging_set"),
    [
        # second leg in USD stated, its notional null: (ii) needs the USD leg's
        # notional, which is unknown -> the GBP leg's notional, an estimate
        ("GBP", 80_000_000.0, "USD", 80_000_000.0, True),
        # second leg in GBP stated: (ii) is the USD leg's notional at spot,
        # 100m x 0.80 — the complete rule value; the GBP leg's notional is never
        # needed, so the trade nets in the USD/GBP pair
        ("USD", 100_000_000.0, "GBP", 80_000_000.0, False),
        # neither leg in GBP, the first with no rate: unconverted, an estimate
        ("CHF", 100_000_000.0, "USD", 100_000_000.0, True),
    ],
)
def test_fx_stated_second_leg_with_no_notional_takes_the_first_leg(
    currency: str,
    notional: float,
    currency_leg2: str,
    expected: float,
    own_hedging_set: bool,
) -> None:
    """``currency_leg2`` stated, ``notional_leg2`` null: the first leg's notional at spot.

    The input names a second payment leg, so it is not Art. 279b(1)(b)(i)'s one
    payment leg. Where the stated second leg is in the reporting currency,
    Art. 279b(1)(b)(ii) takes "the notional amount of the other payment leg" —
    the first leg, converted at spot — so the value is the rule's and the trade
    nets in its pair. Otherwise the rule needs the second leg's notional, which
    is unknown, and the first leg's — the value the contract exchanges for it —
    is the estimate (reported CCR037; the trade is its own hedging set,
    ``fx_own_hedging_set``). Before P1.406 the GBP case returned null and the
    trade added nothing to the FX add-on.
    """
    # Arrange
    trades = _fx_trade_row(
        currency=currency, notional=notional, currency_leg2=currency_leg2, notional_leg2=None
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp()).collect()

    # Assert
    assert result["adjusted_notional"][0] == pytest.approx(expected, rel=1e-12)
    assert result["fx_own_hedging_set"].to_list() == [own_hedging_set]


@pytest.mark.parametrize("fx_rates", [None, "table"])
def test_fx_branch_reads_a_frame_that_omits_the_second_leg_columns(fx_rates: str | None) -> None:
    """A trades frame with no ``notional_leg2`` / ``currency_leg2`` columns at all.

    The branch runs on every pipeline call (with or without an fx_rates table),
    so an in-memory frame that omits the two optional columns must not fail the
    plan (LESSONS B1 / D2(b): a column pinned as a typed null cannot reproduce
    this path). The IR row keeps its upstream adjusted notional; the FX row is
    one payment leg (Art. 279b(1)(b)(i)): its notional, here in GBP.
    """
    # Arrange
    trades = pl.LazyFrame(
        {
            "trade_id": ["IR1", "FX1"],
            "asset_class": ["interest_rate", "fx"],
            "notional": [10_000_000.0, 80_000_000.0],
            "currency": ["GBP", "GBP"],
            "adjusted_notional": [9_000_000.0, None],
        },
        schema={
            "trade_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "adjusted_notional": pl.Float64,
        },
    )
    assert "notional_leg2" not in trades.collect_schema().names()
    rates = None if fx_rates is None else _fx_rates_to_gbp()

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", rates).collect()

    # Assert
    assert result["adjusted_notional"].to_list() == [9_000_000.0, 80_000_000.0]
    assert result["fx_own_hedging_set"].to_list() == [False, True]


# ===========================================================================
# 7. Return type — LazyFrame, no eager collection
# ===========================================================================


def test_fx_branch_returns_lazyframe() -> None:
    """compute_adjusted_notional_fx must return a pl.LazyFrame (no internal .collect)."""
    trades = _fx_trade_row()
    result = compute_adjusted_notional_fx(trades, "GBP", _fx_rates_to_gbp())
    assert isinstance(result, pl.LazyFrame), (
        f"compute_adjusted_notional_fx must return pl.LazyFrame, got {type(result).__name__!r}."
    )
