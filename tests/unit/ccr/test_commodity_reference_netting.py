"""
Unit tests locking the commodity same-reference netting methodology (Art. 280c).

Pipeline position:
    compute_adjusted_notional_commodity -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class  (← _compute_addon_commodity, this stage)

Methodology under test (CRR Art. 280c / BCBS CRE52.68): within a commodity
bucket, trades that reference the SAME individual commodity (``commodity_reference``)
are fully netted into one effective notional ``D_k`` BEFORE the ρ=0.40 within-bucket
aggregation — exactly as the credit / equity add-ons net by ``reference_entity``.

    e_i        = δ_i × d_i × MF_i                          (per trade)
    D_k        = Σ_i e_i within commodity reference k        (full netting)
    AddOn_b    = SF_CM[b] × sqrt(ρ²·(Σ_k D_k)² + (1−ρ²)·Σ_k D_k²)

Fallback: a null ``commodity_reference`` falls back to ``trade_id``, so each
trade is its own reference and the per-trade behaviour is preserved exactly.

NOTE: these are FRESH figures — deliberately not reusing any earlier worked
example — so the methodology is pinned independently.

References:
- CRR Art. 277(3)(b): 5 commodity buckets.
- CRR Art. 280c: within-bucket ρ=0.40; per-commodity netting unit.
- CRR Art. 280 Table 2: SF_CM (OIL_GAS = 0.18).
- BCBS CRE52.67-69.
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

_SF_OIL_GAS = 0.18
_RHO = 0.40
_RHO2 = _RHO**2
_ONE_MINUS_RHO2 = 1.0 - _RHO2
_NS = "NS_CO_REF"


def _co_trade(
    *,
    trade_id: str,
    commodity_reference: str | None,
    adjusted_notional: float,
    supervisory_delta: float = 1.0,
    maturity_factor: float = 1.0,
    commodity_type: str = "OIL_GAS",
) -> dict[str, object]:
    """Return an enriched commodity-trade row dict for compute_addon_per_asset_class."""
    return {
        "trade_id": trade_id,
        "netting_set_id": _NS,
        "asset_class": "commodity",
        "notional": adjusted_notional,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "adjusted_notional": adjusted_notional,
        "supervisory_delta": supervisory_delta,
        "maturity_factor": maturity_factor,
        "years_to_maturity": 2.0,
        "commodity_type": commodity_type,
        "commodity_reference": commodity_reference,
    }


def _commodity_addon(trades: pl.LazyFrame) -> float:
    """Run the add-on stage and return the commodity asset_class_addon for _NS."""
    result = compute_addon_per_asset_class(assign_hedging_set(trades)).collect()
    row = result.filter((pl.col("netting_set_id") == _NS) & (pl.col("asset_class") == "commodity"))
    assert row.height == 1, f"expected 1 commodity row, got {row.height}"
    return row["asset_class_addon"][0]


def test_same_reference_trades_net_before_correlation() -> None:
    """Two BRENT + one WTI (same OIL_GAS bucket): BRENT legs net into one D_k first.

    Fresh figures: e_BRENT1 = 2.0m, e_BRENT2 = 1.5m, e_WTI = 3.0m (all δ=+1, MF=1.0).
        D_BRENT = 3.5m, D_WTI = 3.0m
        AddOn   = 0.18 × sqrt(0.16·(6.5m)² + 0.84·(3.5m² + 3.0m²)) ≈ 892,952.35
    This is strictly LARGER than the per-trade treatment (≈ 796,335) because the
    same-direction BRENT legs aggregate before the partial ρ=0.40 correlation.
    """
    trades = pl.LazyFrame(
        [
            _co_trade(trade_id="T1", commodity_reference="BRENT", adjusted_notional=2_000_000.0),
            _co_trade(trade_id="T2", commodity_reference="BRENT", adjusted_notional=1_500_000.0),
            _co_trade(trade_id="T3", commodity_reference="WTI", adjusted_notional=3_000_000.0),
        ]
    )

    actual = _commodity_addon(trades)

    d_brent, d_wti = 3_500_000.0, 3_000_000.0
    d_bucket = d_brent + d_wti
    sum_dk2 = d_brent**2 + d_wti**2
    expected = _SF_OIL_GAS * math.sqrt(_RHO2 * d_bucket**2 + _ONE_MINUS_RHO2 * sum_dk2)

    # Per-trade (no same-reference netting) value, for the contrast assertion.
    per_trade_sum_e2 = 2_000_000.0**2 + 1_500_000.0**2 + 3_000_000.0**2
    per_trade = _SF_OIL_GAS * math.sqrt(_RHO2 * d_bucket**2 + _ONE_MINUS_RHO2 * per_trade_sum_e2)

    assert actual == pytest.approx(expected, rel=1e-9), (
        f"Same-reference netting expected {expected:,.4f}, got {actual!r}. "
        "BRENT legs must net into one D_k before the ρ=0.40 step (CRR Art. 280c)."
    )
    assert actual > per_trade, (
        f"Same-reference netting ({actual:,.2f}) must exceed the per-trade treatment "
        f"({per_trade:,.2f}) for same-direction legs on one commodity."
    )


def test_null_reference_falls_back_to_per_trade() -> None:
    """Null commodity_reference → trade_id fallback → per-trade behaviour preserved.

    Fresh figures: two OIL_GAS trades (2.5m, 1.0m), both commodity_reference=None.
    Expected add-on uses the per-trade idiosyncratic term Σ e_i² (NOT a netted D_k²).
    """
    trades = pl.LazyFrame(
        [
            _co_trade(trade_id="T_A", commodity_reference=None, adjusted_notional=2_500_000.0),
            _co_trade(trade_id="T_B", commodity_reference=None, adjusted_notional=1_000_000.0),
        ]
    )

    actual = _commodity_addon(trades)

    d_bucket = 3_500_000.0
    sum_e2 = 2_500_000.0**2 + 1_000_000.0**2
    expected = _SF_OIL_GAS * math.sqrt(_RHO2 * d_bucket**2 + _ONE_MINUS_RHO2 * sum_e2)

    assert actual == pytest.approx(expected, rel=1e-9), (
        f"Null-reference fallback expected per-trade value {expected:,.4f}, got {actual!r}. "
        "A null commodity_reference must fall back to trade_id (per-trade granularity)."
    )


def test_same_reference_opposite_direction_fully_offsets() -> None:
    """Two equal-and-opposite legs on the SAME commodity fully offset to a zero add-on.

    Fresh figures: BRENT long 2.0m and BRENT short 2.0m (δ = +1 / −1, MF = 1.0).
        D_BRENT = 2.0m − 2.0m = 0 → AddOn = SF × sqrt(0) = 0.
    Under the old per-trade treatment the idiosyncratic Σ e_i² term would leave a
    non-zero residual; same-commodity netting correctly collapses it to zero.
    """
    trades = pl.LazyFrame(
        [
            _co_trade(
                trade_id="T_LONG",
                commodity_reference="BRENT",
                adjusted_notional=2_000_000.0,
                supervisory_delta=1.0,
            ),
            _co_trade(
                trade_id="T_SHORT",
                commodity_reference="BRENT",
                adjusted_notional=2_000_000.0,
                supervisory_delta=-1.0,
            ),
        ]
    )

    actual = _commodity_addon(trades)

    assert actual == pytest.approx(0.0, abs=1e-6), (
        f"Equal-and-opposite legs on one commodity must fully offset to add-on 0.0, "
        f"got {actual!r}. CRR Art. 280c (per-commodity netting before ρ)."
    )
