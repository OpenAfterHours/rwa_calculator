"""
Review CC-04: SA-CCR interest-rate hedging sets are per currency (and inflation apart).

Pipeline position:
    compute_addon_per_asset_class (engine/ccr/pfe.py::_compute_addon_ir)

Key responsibilities:
- Pin that IR trades in different currencies never offset each other: each
  currency is its own hedging set and the hedging-set add-ons are summed.
- Pin that inflation-driven IR trades form hedging sets separate from nominal
  ones in the same currency, and that a null ``is_inflation`` reads as nominal.

Rule text (CRR / CCR (CRR) Part Art. 277a(1), unchanged by PS1/26 — Basel 3.1
Annex R amends only Art. 273(3)(b), 274(2)-(2B), 299A, 306(4), 308(3), 309(2)):
    "(a) transactions mapped to the interest rate risk category shall be assigned
    to the same hedging set only where their primary risk driver ... is
    denominated in the same currency; ... For the purposes of point (a) ...,
    transactions mapped to the interest rate risk category that have an
    inflation variable as the primary risk driver shall be assigned to separate
    hedging sets, other than the hedging sets established for transactions
    mapped to the interest rate risk category that do not have an inflation
    variable as the primary risk driver."
Art. 280a(1): AddOn_IR = sum over j of AddOn_IR_j, "j = the index that denotes
all the interest risk rate hedging sets".

Defect pinned: the add-on grouped effective notionals by (netting set, asset
class, maturity bucket) only, so a GBP 100m payer and a USD 100m receiver of the
same tenor produced AddOn_IR = 0 (EAD 0) instead of the sum of two add-ons.

Hand calculation (adjusted notional d = 100,000,000 supplied directly, MF = 1,
SF_IR = 0.5%, one maturity bucket per hedging set, so EffNot_j = |D_j|):
    one hedging set with |D| = 100m:  AddOn = 0.005 × 100,000,000 = 500,000
    two hedging sets (GBP +100m, USD -100m): 500,000 + 500,000 = 1,000,000
    one hedging set (GBP +100m, GBP -100m): 0.005 × |0| = 0

References:
    - CRR Art. 277(4)(a), Art. 277a(1)(a) (+ second sub-paragraph), Art. 280a(1)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

_D = 100_000_000.0
_SF_IR = 0.005
_ONE_SET = _SF_IR * _D  # 500,000


def _ir_trades(rows: list[dict]) -> pl.LazyFrame:
    """IR trades already carrying the per-trade SA-CCR inputs the add-on reads."""
    base = {
        "netting_set_id": "NS1",
        "asset_class": "interest_rate",
        "maturity_bucket": "1Y_5Y",
        "adjusted_notional": _D,
        "maturity_factor": 1.0,
        "is_inflation": False,
        "hedging_set_id": None,
    }
    return pl.LazyFrame(
        [{**base, **row} for row in rows],
        schema_overrides={"is_inflation": pl.Boolean, "hedging_set_id": pl.String},
    )


def _ir_addon(trades: pl.LazyFrame) -> float:
    out = compute_addon_per_asset_class(trades).collect()
    return float(out.filter(pl.col("asset_class") == "interest_rate")["asset_class_addon"][0])


def test_opposite_trades_in_two_currencies_do_not_offset() -> None:
    """GBP +100m and USD -100m: two hedging sets, AddOn = 500,000 + 500,000."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "G", "currency": "GBP", "supervisory_delta": 1.0},
            {"trade_id": "U", "currency": "USD", "supervisory_delta": -1.0},
        ]
    )

    # Act
    addon = _ir_addon(trades)

    # Assert
    assert addon == pytest.approx(2 * _ONE_SET, rel=1e-12), (
        f"AddOn_IR = {addon:,.2f}; a value of 0 means the GBP and USD trades were "
        "pooled into one hedging set (Art. 277a(1)(a) forbids it)"
    )


def test_opposite_trades_in_one_currency_still_offset() -> None:
    """Control: GBP +100m and GBP -100m share a hedging set and net to 0."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "G1", "currency": "GBP", "supervisory_delta": 1.0},
            {"trade_id": "G2", "currency": "GBP", "supervisory_delta": -1.0},
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(0.0, abs=1e-6)


def test_currency_hedging_set_add_ons_are_summed_not_netted() -> None:
    """Three currencies, one short, two long: AddOn = 3 × 500,000 (Art. 280a(1))."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "G", "currency": "GBP", "supervisory_delta": 1.0},
            {"trade_id": "U", "currency": "USD", "supervisory_delta": -1.0},
            {"trade_id": "E", "currency": "EUR", "supervisory_delta": 1.0},
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(3 * _ONE_SET, rel=1e-12)


def test_inflation_trade_is_its_own_hedging_set_in_the_same_currency() -> None:
    """GBP nominal +100m and GBP inflation -100m: separate sets, AddOn = 1,000,000."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "N", "currency": "GBP", "supervisory_delta": 1.0},
            {"trade_id": "I", "currency": "GBP", "supervisory_delta": -1.0, "is_inflation": True},
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(2 * _ONE_SET, rel=1e-12)


def test_inflation_trades_in_one_currency_net_with_each_other() -> None:
    """Two GBP inflation trades of opposite direction share a set and net to 0."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "I1", "currency": "GBP", "supervisory_delta": 1.0, "is_inflation": True},
            {"trade_id": "I2", "currency": "GBP", "supervisory_delta": -1.0, "is_inflation": True},
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(0.0, abs=1e-6)


def test_null_inflation_flag_reads_as_nominal() -> None:
    """is_inflation null nets with an explicit-False nominal trade (one hedging set)."""
    # Arrange
    trades = _ir_trades(
        [
            {"trade_id": "N1", "currency": "GBP", "supervisory_delta": 1.0, "is_inflation": False},
            {"trade_id": "N2", "currency": "GBP", "supervisory_delta": -1.0, "is_inflation": None},
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(0.0, abs=1e-6)


def test_cross_bucket_aggregation_still_applies_within_a_currency() -> None:
    """Within one currency the Art. 280a(3) bucket correlations still apply.

    GBP +100m in bucket 1 (LT_1Y) and GBP +100m in bucket 3 (GT_5Y), rho_13 = 0.3:
    EffNot = sqrt(100m² + 100m² + 2 × 0.3 × 100m × 100m) = 100m × sqrt(2.6);
    AddOn = 0.005 × 100m × sqrt(2.6) = 806,225.77.
    """
    # Arrange
    trades = _ir_trades(
        [
            {
                "trade_id": "B1",
                "currency": "GBP",
                "supervisory_delta": 1.0,
                "maturity_bucket": "LT_1Y",
            },
            {
                "trade_id": "B3",
                "currency": "GBP",
                "supervisory_delta": 1.0,
                "maturity_bucket": "GT_5Y",
            },
        ]
    )

    # Act / Assert
    assert _ir_addon(trades) == pytest.approx(_ONE_SET * 2.6**0.5, rel=1e-12)
