"""
P1.406 unit tests: an FX trade whose adjusted notional is not a complete
two-leg value at spot is its own hedging set.

Pipeline position:
    compute_adjusted_notional_fx (writes ``fx_own_hedging_set``)
    -> assign_hedging_set (isolates the flagged trade)
    -> compute_addon_per_asset_class (FX: SF_FX x |D_HS| per hedging set)

Key responsibilities:
- ``compute_adjusted_notional_fx`` flags exactly the FX trades that must not net
  in a currency pair's hedging set, and no other row:
    * a present leg with no spot rate to the reporting currency (its adjusted
      notional took the leg unconverted — an estimate);
    * ``currency_leg2`` stated with ``notional_leg2`` null (the input names a
      second leg whose notional is unknown — the first leg's notional is an
      estimate; reported CCR037) — except where that stated second leg is in the
      reporting currency: Art. 279b(1)(b)(ii) then takes the first leg's
      notional at spot, the rule value, and the trade nets in its pair;
    * no second leg at all (read as one payment leg, Art. 279b(1)(b)(i), but
      no currency pair is stated to share a hedging set on; reported CCR036).
- ``assign_hedging_set`` gives each flagged trade its own FX hedging set, so its
  effective notional offsets nothing; unflagged trades on the same pair still
  share one hedging set.
- The FX add-on of a hedged pair with a flagged trade is the sum of the trades'
  own add-ons, never the netted value.

Why: netted against the pair's other trades an estimate can lower the netting
set's add-on below its value with complete inputs (measured, reviewer probes:
EUR 90m/USD 100m long + EUR 100m/USD 100m short, no USD rate -> EAD 0.0 against
280,000 with the rate; GBP 80m/USD 100m long + GBP 80m short with
``currency_leg2`` USD and ``notional_leg2`` null -> EAD 0.0 against 4,480,000 at
HEAD, which left the short out). Art. 277a(1)(b) assigns FX trades to the same
hedging set "only where their primary risk driver ... is based on the same
currency pair"; the engine keeps a position it cannot value at spot, or whose
pair is not stated, out of that netting, as CC-06 keeps a trade with an unknown
risk driver out of the other-risks netting
(``engine/ccr/risk_categories.py::compute_addon_other``). Isolation can only
raise the add-on: sum |d_i| >= |sum d_i|.

References:
- CCR (CRR) Part Art. 277a(1)(b), 279b(1)(b), 279b(3), 280b (unamended by PS1/26)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_fx
from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

_SF_FX = 0.04

_TRADE_SCHEMA = {
    "trade_id": pl.String,
    "netting_set_id": pl.String,
    "asset_class": pl.String,
    "notional": pl.Float64,
    "currency": pl.String,
    "notional_leg2": pl.Float64,
    "currency_leg2": pl.String,
    "years_to_maturity": pl.Float64,
}


def _rates() -> pl.LazyFrame:
    """EUR -> GBP 0.85 only: no USD rate."""
    return pl.LazyFrame(
        {"currency_from": ["EUR"], "currency_to": ["GBP"], "rate": [0.85]},
        schema={"currency_from": pl.String, "currency_to": pl.String, "rate": pl.Float64},
    )


def _trade(
    trade_id: str,
    currency: str | None,
    notional: float,
    currency_leg2: str | None,
    notional_leg2: float | None,
    asset_class: str = "fx",
) -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "netting_set_id": "NS1",
        "asset_class": asset_class,
        "notional": notional,
        "currency": currency,
        "notional_leg2": notional_leg2,
        "currency_leg2": currency_leg2,
        "years_to_maturity": 1.0,
    }


@pytest.mark.parametrize(
    ("currency", "currency_leg2", "notional_leg2", "asset_class", "expected"),
    [
        ("GBP", "USD", 100e6, "fx", True),  # (ii) with the foreign leg's rate missing
        ("USD", "GBP", 80e6, "fx", True),  # same, legs swapped
        ("EUR", "USD", 100e6, "fx", True),  # (iii) with one rate missing
        ("GBP", None, 100e6, "fx", True),  # a second leg with no currency
        (None, "GBP", 80e6, "fx", True),  # a first leg with no currency
        ("GBP", "EUR", None, "fx", True),  # second leg stated, its notional null
        # second leg in GBP stated, its notional null: (ii) is the EUR leg at spot,
        # the complete rule value, so the trade nets in its pair
        ("EUR", "GBP", None, "fx", False),
        ("USD", "GBP", None, "fx", True),  # same, but the first leg has no rate
        ("GBP", "GBP", None, "fx", True),  # both legs in GBP: (ii) needs leg 2's notional
        ("GBP", None, None, "fx", True),  # no second leg: no currency pair stated
        ("USD", None, None, "fx", True),  # no second leg, and no rate
        ("GBP", "EUR", 100e6, "fx", False),  # complete: both legs, every rate
        ("EUR", "GBP", 80e6, "fx", False),  # same, legs swapped
        ("USD", None, None, "interest_rate", False),  # not an FX trade
    ],
)
def test_fx_branch_flags_exactly_the_trades_that_must_not_net(
    currency: str | None,
    currency_leg2: str | None,
    notional_leg2: float | None,
    asset_class: str,
    expected: bool,
) -> None:
    """``fx_own_hedging_set`` is False only where the trade carries its rule value.

    That is a complete two-leg FX trade with every rate, or a trade whose stated
    second leg is in the reporting currency with no notional: Art. 279b(1)(b)(ii)
    takes the other (first) leg's notional at spot, so the missing notional is
    never needed.
    """
    # Arrange
    trades = pl.LazyFrame(
        [_trade("T1", currency, 80e6, currency_leg2, notional_leg2, asset_class)],
        schema=_TRADE_SCHEMA,
    )

    # Act
    result = compute_adjusted_notional_fx(trades, "GBP", _rates()).collect()

    # Assert
    assert result["fx_own_hedging_set"].to_list() == [expected]


def test_flagged_fx_trade_is_its_own_hedging_set() -> None:
    """Two EUR/USD trades: the flagged one leaves the pair's hedging set, the other stays."""
    # Arrange
    trades = pl.LazyFrame(
        [
            {**_trade("A", "EUR", 90e6, "USD", 100e6), "fx_own_hedging_set": True},
            {**_trade("B", "EUR", 100e6, "USD", 100e6), "fx_own_hedging_set": False},
            {**_trade("C", "USD", 50e6, "EUR", 45e6), "fx_own_hedging_set": False},
        ]
    )

    # Act
    result = assign_hedging_set(trades).collect()

    # Assert
    hedging_sets = dict(zip(result["trade_id"], result["hedging_set_id"], strict=True))
    assert hedging_sets == {
        "A": "FX-NS1-EUR/USD-trade-A",
        "B": "FX-NS1-EUR/USD",
        "C": "FX-NS1-EUR/USD",
    }


def test_flagged_fx_trade_with_no_currency_still_gets_its_own_hedging_set() -> None:
    """A null leg currency leaves no pair to key on; the trade id still isolates it."""
    # Arrange
    trades = pl.LazyFrame(
        [
            {**_trade("A", None, 90e6, None, 100e6), "fx_own_hedging_set": True},
            {**_trade("B", None, 90e6, None, 100e6), "fx_own_hedging_set": True},
        ],
        schema={**_TRADE_SCHEMA, "fx_own_hedging_set": pl.Boolean},
    )

    # Act
    result = assign_hedging_set(trades).collect()

    # Assert
    assert result["hedging_set_id"].to_list() == ["FX-NS1-trade-A", "FX-NS1-trade-B"]


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        # d_A = 100m long, d_B = 100m short, each its own hedging set
        ((True, True), _SF_FX * (100e6 + 100e6)),
        # only A estimated: A alone, B alone in the pair's hedging set
        ((True, False), _SF_FX * (100e6 + 100e6)),
        # every rate known: the pair nets, |100m - 100m|
        ((False, False), 0.0),
    ],
)
def test_fx_addon_never_nets_a_flagged_trade(flags: tuple[bool, bool], expected: float) -> None:
    """AddOn_FX sums a flagged trade's own |effective notional|; unflagged trades still net."""
    # Arrange
    trades = pl.LazyFrame(
        [
            {
                **_trade("A", "EUR", 90e6, "USD", 100e6),
                "fx_own_hedging_set": flags[0],
                "adjusted_notional": 100e6,
                "supervisory_delta": 1.0,
                "maturity_factor": 1.0,
            },
            {
                **_trade("B", "EUR", 100e6, "USD", 100e6),
                "fx_own_hedging_set": flags[1],
                "adjusted_notional": 100e6,
                "supervisory_delta": -1.0,
                "maturity_factor": 1.0,
            },
        ]
    )

    # Act
    result = compute_addon_per_asset_class(assign_hedging_set(trades)).collect()

    # Assert
    addon = result.filter(pl.col("asset_class") == "fx")["asset_class_addon"][0]
    assert addon == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("short_leg2", "expected"),
    [
        # stated pair, notional_leg2 null: d = 80m each, its own hedging set
        (("USD", None), _SF_FX * (80e6 + 80e6)),
        # no second leg at all: same
        ((None, None), _SF_FX * (80e6 + 80e6)),
        # control, complete: the pair nets, |80m - 80m|
        (("USD", 100e6), 0.0),
    ],
)
def test_fx_trade_with_no_second_leg_notional_never_nets(
    short_leg2: tuple[str | None, float | None], expected: float
) -> None:
    """Composed branch -> hedging set -> add-on: a short with no leg-2 notional offsets nothing.

    Long GBP 80m / USD 100m (USD 0.80: d = 80m by (ii)) against a short GBP 80m
    whose second leg is incomplete. The second P1.406 attempt read the short as
    one payment leg in the GBP/USD hedging set and netted it to zero.
    """
    # Arrange
    rates = pl.LazyFrame(
        {"currency_from": ["USD"], "currency_to": ["GBP"], "rate": [0.80]},
        schema={"currency_from": pl.String, "currency_to": pl.String, "rate": pl.Float64},
    )
    trades = pl.LazyFrame(
        [_trade("A", "GBP", 80e6, "USD", 100e6), _trade("B", "GBP", 80e6, *short_leg2)],
        schema=_TRADE_SCHEMA,
    ).with_columns(
        pl.Series("supervisory_delta", [1.0, -1.0]),
        pl.lit(1.0).alias("maturity_factor"),
    )

    # Act
    priced = assign_hedging_set(compute_adjusted_notional_fx(trades, "GBP", rates))
    result = compute_addon_per_asset_class(priced).collect()

    # Assert
    addon = result.filter(pl.col("asset_class") == "fx")["asset_class_addon"][0]
    assert addon == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    "long_legs",
    [
        ("USD", 100e6, "GBP", 80e6),  # the long's legs in the short's order
        ("GBP", 80e6, "USD", 100e6),  # the long's legs swapped
    ],
    ids=["same_order", "swapped"],
)
def test_fx_trade_with_its_reporting_currency_leg_notional_missing_nets(
    long_legs: tuple[str, float, str, float],
) -> None:
    """A short USD 100m whose stated second leg is GBP with no notional nets in USD/GBP.

    Art. 279b(1)(b)(ii): one leg in the reporting currency -> "the notional amount
    of the other payment leg", the USD leg at spot, 100m x 0.80 = 80m. The GBP
    leg's notional is never needed, so d = 80m is the rule value and the trade is
    in the pair's hedging set (Art. 277a(1)(b)): against the complete long
    (d = 80m) the pair nets to |80m - 80m| = 0. HEAD gave 0.0; the third P1.406
    attempt isolated the short and gave 0.04 x (80m + 80m) = 6,400,000.
    """
    # Arrange
    rates = pl.LazyFrame(
        {"currency_from": ["USD"], "currency_to": ["GBP"], "rate": [0.80]},
        schema={"currency_from": pl.String, "currency_to": pl.String, "rate": pl.Float64},
    )
    trades = pl.LazyFrame(
        [_trade("A", *long_legs), _trade("B", "USD", 100e6, "GBP", None)],
        schema=_TRADE_SCHEMA,
    ).with_columns(
        pl.Series("supervisory_delta", [1.0, -1.0]),
        pl.lit(1.0).alias("maturity_factor"),
    )

    # Act
    priced = assign_hedging_set(compute_adjusted_notional_fx(trades, "GBP", rates))
    result = compute_addon_per_asset_class(priced).collect()

    # Assert
    addon = result.filter(pl.col("asset_class") == "fx")["asset_class_addon"][0]
    assert addon == pytest.approx(0.0, abs=1e-6)
