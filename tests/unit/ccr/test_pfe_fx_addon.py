"""
Unit tests for the FX branch of compute_addon_per_asset_class (P8.19).

Pipeline position:
    compute_adjusted_notional_fx -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class  (← this stage)

FX asset-class add-on per CRR Art. 277(3)(a) + Art. 277a + BCBS CRE52.55:

    Hedging set    : one per currency pair within a netting set.
    D_HS           : signed sum of (delta * adjusted_notional * MF) within HS.
    AddOn_HS       : SF_FX * |D_HS|       (Art. 277a(2)).
    AddOn_FX       : sum over HS of AddOn_HS  (CRE52.55 — no cross-HS rho for FX).

SF_FX = 0.04 (Art. 280 Table 1).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

# SF_FX from CRR Art. 280 Table 1 — referenced as the multiplier in the
# hand-calc expressions below; sourced directly so the test stays self-contained
# but recomputes the same value the engine reads.
_SF_FX = 0.04


def _enriched_fx_trade(
    *,
    trade_id: str = "T_FX_001",
    netting_set_id: str = "NS_FX_001",
    notional: float = 100_000_000.0,
    currency: str = "USD",
    notional_leg2: float | None = 80_000_000.0,
    currency_leg2: str | None = "GBP",
    adjusted_notional: float = 80_000_000.0,
    supervisory_delta: float = 1.0,
    maturity_factor: float = 1.0,
    years_to_maturity: float = 1.0,
) -> dict[str, object]:
    """Return a row dict for an FX trade pre-enriched with the PFE inputs.

    These are the columns required by ``assign_hedging_set`` +
    ``compute_addon_per_asset_class``; in a full pipeline they would be
    populated by the upstream stages.
    """
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": "fx",
        "notional": notional,
        "currency": currency,
        "notional_leg2": notional_leg2,
        "currency_leg2": currency_leg2,
        "adjusted_notional": adjusted_notional,
        "supervisory_delta": supervisory_delta,
        "maturity_factor": maturity_factor,
        "years_to_maturity": years_to_maturity,
    }


# ===========================================================================
# 1. CCR-A2 single-trade FX-forward: AddOn_FX = SF_FX * |D_HS| = 3.2m GBP
# ===========================================================================


def test_fx_addon_single_trade_matches_ccr_a2_hand_calc() -> None:
    """CCR-A2 hand-calc: 1y USD/GBP forward, D_HS=80m, AddOn_FX = 0.04*80m = 3.2m.

    With one trade in one hedging set the formula collapses to SF_FX × |D_HS|.
    """
    # Arrange
    trades = pl.LazyFrame([_enriched_fx_trade()])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — single (NS, asset_class="fx") row with the expected add-on.
    fx_row = result.filter(
        (pl.col("netting_set_id") == "NS_FX_001") & (pl.col("asset_class") == "fx")
    )
    assert fx_row.height == 1, f"Expected 1 FX row, got {fx_row.height}"

    expected = _SF_FX * 80_000_000.0  # = 3_200_000
    actual = fx_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"CCR-A2 hand-calc: AddOn_FX expected {expected:,.2f}, got {actual!r}. "
        "CRR Art. 277a(2) + BCBS CRE52.55."
    )


# ===========================================================================
# 2. Two-trade single-hedging-set: signed sum within HS (perfect netting)
# ===========================================================================


def test_fx_addon_two_trades_same_pair_net_within_hedging_set() -> None:
    """Two opposite-direction trades on the same currency pair net inside the HS.

    Trade 1: long  USD 100m / sell GBP 80m, adjusted_notional = +80m, delta = +1.
    Trade 2: short USD  60m / buy  GBP 48m, adjusted_notional = +48m, delta = −1.

    Signed sum within the GBP/USD hedging set = 80 − 48 = 32m.
    AddOn_FX = SF_FX × |32m| = 0.04 × 32m = 1.28m.
    """
    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_fx_trade(
                trade_id="T_LONG", adjusted_notional=80_000_000.0, supervisory_delta=1.0
            ),
            _enriched_fx_trade(
                trade_id="T_SHORT",
                notional=60_000_000.0,
                notional_leg2=48_000_000.0,
                adjusted_notional=48_000_000.0,
                supervisory_delta=-1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    actual = result.filter(pl.col("asset_class") == "fx")["asset_class_addon"][0]
    expected = _SF_FX * abs(80_000_000.0 - 48_000_000.0)  # = 1_280_000
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"Signed-sum within HS: expected {expected:,.2f}, got {actual!r}. "
        "Trades in the same currency-pair hedging set net perfectly (Art. 277a(2))."
    )


# ===========================================================================
# 3. Two trades on different pairs: simple sum across hedging sets (no rho)
# ===========================================================================


def test_fx_addon_two_pairs_sum_across_hedging_sets_no_correlation() -> None:
    """Two trades on different pairs sum across hedging sets without correlation.

    Trade A: GBP/USD pair, D_HS_A = +80m  → AddOn_A = 0.04 × 80m = 3.2m
    Trade B: EUR/GBP pair, D_HS_B = +50m  → AddOn_B = 0.04 × 50m = 2.0m

    AddOn_FX = AddOn_A + AddOn_B = 5.2m  (BCBS CRE52.55: simple sum for FX).
    """
    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_fx_trade(
                trade_id="T_A", currency="USD", currency_leg2="GBP",
                adjusted_notional=80_000_000.0,
            ),
            _enriched_fx_trade(
                trade_id="T_B", currency="EUR", currency_leg2="GBP",
                notional=50_000_000.0, notional_leg2=42_500_000.0,
                adjusted_notional=50_000_000.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — single (NS, fx) row aggregating across the two hedging sets.
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row.height == 1, f"Expected 1 FX row per NS, got {fx_row.height}"

    expected = _SF_FX * (80_000_000.0 + 50_000_000.0)  # = 5_200_000
    actual = fx_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"Two-pair AddOn_FX expected {expected:,.2f} (3.2m + 2.0m), got {actual!r}. "
        "BCBS CRE52.55: FX asset-class add-on is a plain sum across hedging sets."
    )


# ===========================================================================
# 4. Order-independence: EUR/USD and USD/EUR collapse into one hedging set
# ===========================================================================


def test_fx_addon_currency_pair_is_order_independent() -> None:
    """Two trades with the legs in opposite order must collapse into one HS.

    Trade A: leg1=EUR / leg2=USD  → pair "EUR/USD"
    Trade B: leg1=USD / leg2=EUR  → pair "EUR/USD" (after min/max normalisation)

    Both should land in the same hedging set and net within it.
    """
    # Arrange — both rows have D_i = +80m so they sum to 160m and produce
    # AddOn = SF_FX × 160m = 6.4m IF they share a hedging set. If they were
    # treated as separate sets each would contribute 3.2m, summing to the same
    # 6.4m — so we additionally verify the unique hedging_set_id.
    trades = pl.LazyFrame(
        [
            _enriched_fx_trade(
                trade_id="T_A", currency="EUR", currency_leg2="USD",
                adjusted_notional=80_000_000.0,
            ),
            _enriched_fx_trade(
                trade_id="T_B", currency="USD", currency_leg2="EUR",
                adjusted_notional=80_000_000.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Assert — both trades carry the same hedging_set_id.
    hs_df = with_hs.select("trade_id", "hedging_set_id").collect()
    assert hs_df["hedging_set_id"][0] == hs_df["hedging_set_id"][1], (
        f"Order-independence violated: EUR/USD and USD/EUR landed in different "
        f"hedging sets: {hs_df['hedging_set_id'].to_list()}"
    )
    assert "EUR/USD" in hs_df["hedging_set_id"][0], (
        f"FX hedging-set id must contain the alphabetised currency pair "
        f"'EUR/USD', got {hs_df['hedging_set_id'][0]!r}."
    )


# ===========================================================================
# 5. Mixed IR + FX: dispatcher emits both asset-class rows independently
# ===========================================================================


def test_mixed_ir_and_fx_emit_independent_asset_class_rows() -> None:
    """Dispatcher must compute both IR and FX add-ons for a mixed-asset netting set.

    The PFE asset-class output contract (one row per (NS, asset_class)) holds
    when the netting set carries trades of multiple asset classes.
    """
    # Arrange — one IR trade in NS_MIX, one FX trade in NS_MIX.
    ir_trade = {
        "trade_id": "T_IR",
        "netting_set_id": "NS_MIX",
        "asset_class": "interest_rate",
        "notional": 100_000_000.0,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "adjusted_notional": 7.83e8,
        "supervisory_delta": 1.0,
        "maturity_factor": 1.0,
        "years_to_maturity": 10.0,
    }
    fx_trade = _enriched_fx_trade(trade_id="T_FX", netting_set_id="NS_MIX")
    trades = pl.LazyFrame([ir_trade, fx_trade])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — two rows for NS_MIX, one per asset_class, both populated.
    ns_rows = result.filter(pl.col("netting_set_id") == "NS_MIX")
    assert ns_rows.height == 2, (
        f"Mixed NS must emit 2 (asset_class) rows, got {ns_rows.height}. "
        f"Result: {result.to_dicts()}"
    )

    asset_classes = sorted(ns_rows["asset_class"].to_list())
    assert asset_classes == ["fx", "interest_rate"], (
        f"Expected asset_class rows ['fx', 'interest_rate'], got {asset_classes}."
    )

    # FX row uses the CCR-A2 hand-calc.
    fx_addon = ns_rows.filter(pl.col("asset_class") == "fx")["asset_class_addon"][0]
    assert fx_addon == pytest.approx(_SF_FX * 80_000_000.0, rel=1e-12)

    # IR row is non-null (concrete IR formula tested elsewhere).
    ir_addon = ns_rows.filter(pl.col("asset_class") == "interest_rate")["asset_class_addon"][0]
    assert ir_addon is not None and ir_addon > 0, (
        f"IR asset-class add-on must be a positive float, got {ir_addon!r}."
    )


# ===========================================================================
# 6. Non-FX / non-IR rows still emit null (contract for credit/equity/commodity)
# ===========================================================================


def test_credit_asset_class_row_emits_null_addon() -> None:
    """Credit / equity / commodity rows must still emit null asset_class_addon.

    These asset classes are deferred to subsequent batches; the dispatcher's
    contract is to anchor every (NS, asset_class) combination present in the
    input and leave non-implemented branches null.
    """
    # Arrange — single credit-derivative row, no FX / IR.
    trades = pl.LazyFrame(
        [
            {
                "trade_id": "T_CR",
                "netting_set_id": "NS_CR",
                "asset_class": "credit",
                "notional": 50_000_000.0,
                "currency": "GBP",
                "notional_leg2": None,
                "currency_leg2": None,
                "adjusted_notional": 50_000_000.0,
                "supervisory_delta": 1.0,
                "maturity_factor": 1.0,
                "years_to_maturity": 5.0,
            }
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    cr_row = result.filter(pl.col("asset_class") == "credit")
    assert cr_row.height == 1, "Credit row must still be anchored in the output."
    assert cr_row["asset_class_addon"][0] is None, (
        f"Credit asset-class add-on must be null (deferred), "
        f"got {cr_row['asset_class_addon'][0]!r}."
    )
