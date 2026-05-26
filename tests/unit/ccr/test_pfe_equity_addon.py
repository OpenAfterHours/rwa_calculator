"""
Unit tests for the equity branch of compute_addon_per_asset_class (P8.36).

Pipeline position:
    compute_adjusted_notional_equity -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class  (← this stage)

Equity asset-class add-on per CRR Art. 277(2)(d) + Art. 277a + Art. 280b:

    Hedging set : "EQ-<netting_set_id>" — one per asset class per NS.
    EN_i        : supervisory_delta_i × adjusted_notional_i × MF_i  (per entity)
    D_k         : sum of EN_i for each distinct reference_entity k within (NS, is_index).
    sum_D       : sum over k of D_k
    sum_D_sq    : sum over k of D_k^2

    AddOn_HS = SF × sqrt((rho × sum_D)^2 + (1 − rho^2) × sum_D_sq)

    is_index=False: SF = 0.32,  rho = 0.50  (single-name)
    is_index=True:  SF = 0.20,  rho = 0.80  (index)

    Mixed SN + IDX in the same NS sums two sub-class add-ons (no cross-correlation).

References:
- CRR Art. 277(2)(d): equity hedging set = one per asset class per NS
- CRR Art. 277a + Art. 280b: equity add-on formula
- CRR Art. 280 Table 2: SF_EQ_SN = 0.32, SF_EQ_IDX = 0.20
- CRR Art. 280b: rho_SN = 0.50, rho_IDX = 0.80
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

# Supervisory factors from CRR Art. 280 Table 2.
_SF_EQ_SN: float = 0.32
_SF_EQ_IDX: float = 0.20
# Correlations from CRR Art. 280b.
_RHO_SN: float = 0.50
_RHO_IDX: float = 0.80


def _addon_hs(sf: float, rho: float, d_values: list[float]) -> float:
    """Hand-calc AddOn_HS = SF × sqrt((rho × sum_D)^2 + (1−rho^2) × sum_D_sq)."""
    sum_d = sum(d_values)
    sum_d_sq = sum(d**2 for d in d_values)
    return sf * math.sqrt((rho * sum_d) ** 2 + (1 - rho**2) * sum_d_sq)


def _enriched_equity_trade(
    *,
    trade_id: str = "T_EQ_001",
    netting_set_id: str = "NS_EQ_001",
    reference_entity: str = "GB00B16GWD56",
    is_index: bool = False,
    adjusted_notional: float = 50_000_000.0,
    supervisory_delta: float = 1.0,
    maturity_factor: float = 0.99965770,
    years_to_maturity: float = 0.999315537,
) -> dict[str, object]:
    """Return a row dict for an equity trade pre-enriched with the PFE inputs.

    These are the columns required by ``assign_hedging_set`` +
    ``compute_addon_per_asset_class``; in a full pipeline they would be
    populated by the upstream stages.
    """
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": "equity",
        "notional": 0.0,
        "currency": "GBP",
        "adjusted_notional": adjusted_notional,
        "supervisory_delta": supervisory_delta,
        "maturity_factor": maturity_factor,
        "years_to_maturity": years_to_maturity,
        "reference_entity": reference_entity,
        "is_index": is_index,
        # FX leg columns needed by assign_hedging_set schema.
        "notional_leg2": None,
        "currency_leg2": None,
        # IR bucket needed by assign_hedging_set.
        "maturity_bucket": None,
        # Commodity type.
        "commodity_type": None,
    }


# ===========================================================================
# 1. CCR-A5 single-name single-trade hand-calc
# ===========================================================================


def test_equity_addon_single_name_single_trade_matches_ccr_a5_hand_calc() -> None:
    """CCR-A5 load-bearing: single SN trade, EN=49_982_885.30, AddOn=15_994_523.295317.

    Single-trade collapse: sum_D = sum_D^2^0.5 = EN = 49_982_885.30.
    AddOn = 0.32 × sqrt((0.5 × EN)^2 + 0.75 × EN^2) = 0.32 × EN = 15_994_523.295317.
    """
    # Arrange — EN = delta × adjusted_notional × MF
    # delta=1.0, adjusted_notional=50_000_000.0, MF=0.99965770...
    # EN = 49_982_885.297867... (matches CCR-A5 hand-calc)
    trades = pl.LazyFrame([_enriched_equity_trade()])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    eq_row = result.filter(
        (pl.col("netting_set_id") == "NS_EQ_001") & (pl.col("asset_class") == "equity")
    )
    assert eq_row.height == 1, f"Expected 1 equity row, got {eq_row.height}"

    en = 1.0 * 50_000_000.0 * 0.99965770  # approx effective notional
    expected = _addon_hs(_SF_EQ_SN, _RHO_SN, [en])  # ≈ 0.32 × EN = 15_994_523.30
    actual = eq_row["asset_class_addon"][0]
    assert actual == pytest.approx(15_994_523.295317, rel=1e-6), (
        f"CCR-A5 hand-calc: AddOn_EQ expected ≈ 15_994_523.30, got {actual!r}. "
        "CRR Art. 277a + Art. 280b (SF_SN=0.32, rho_SN=0.50)."
    )


# ===========================================================================
# 2. Index trade uses 20% SF and 0.80 rho
# ===========================================================================


def test_equity_addon_index_single_trade_uses_20pct_sf_and_080_rho() -> None:
    """Index equity trade: SF=0.20, rho=0.80 → AddOn = 0.20 × EN = 9_996_577.06.

    For is_index=True the formula collapses the same way as SN but with
    different supervisory factors (CRR Art. 280 Table 2 + Art. 280b).
    """
    # Arrange — same EN as CCR-A5 but is_index=True.
    trades = pl.LazyFrame(
        [_enriched_equity_trade(trade_id="T_IDX", is_index=True)]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    eq_row = result.filter(pl.col("asset_class") == "equity")
    actual = eq_row["asset_class_addon"][0]
    assert actual == pytest.approx(9_996_577.06, rel=1e-6), (
        f"Index trade: AddOn_EQ expected ≈ 9_996_577.06, got {actual!r}. "
        "CRR Art. 280 Table 2 (SF_IDX=0.20) + Art. 280b (rho_IDX=0.80)."
    )


# ===========================================================================
# 3. Two distinct entities diversify under rho (anti-degenerate)
# ===========================================================================


def test_equity_addon_two_distinct_entities_diversifies_under_rho() -> None:
    """Two SN trades on different entities → AddOn < 2 × single_trade_addon.

    With D_1=D_2=50m:
      sum_D = 100m, sum_D_sq = 50m^2 + 50m^2 = 5e15
      AddOn = 0.32 × sqrt((0.5×100m)^2 + 0.75×5e15) = 25_298_221.28

    This is LESS than 2 × 15_994_523.295317 = 31_989_046.59 — the anti-degenerate
    load-bearing assertion proving the rho-based diversification is in effect.
    """
    # Arrange — two single-name trades, different reference entities, same NS.
    trades = pl.LazyFrame(
        [
            _enriched_equity_trade(
                trade_id="T_EQ_001",
                reference_entity="GB00B16GWD56",
                adjusted_notional=50_000_000.0,
                maturity_factor=1.0,   # simpler: MF=1 so EN=d exactly.
            ),
            _enriched_equity_trade(
                trade_id="T_EQ_002",
                reference_entity="GB00B16GWD99",  # different entity
                adjusted_notional=50_000_000.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — diversified add-on is strictly less than the degenerate sum.
    eq_row = result.filter(pl.col("asset_class") == "equity")
    actual = eq_row["asset_class_addon"][0]
    degenerate_sum = 2 * _SF_EQ_SN * 50_000_000.0  # 31_989_046.59 approx
    assert actual == pytest.approx(25_298_221.28, rel=1e-6), (
        f"Two-entity diversification: expected AddOn ≈ 25_298_221.28, got {actual!r}. "
        "CRR Art. 277a: rho-based aggregation diversifies across distinct entities."
    )
    assert actual < degenerate_sum, (
        f"Anti-degenerate assertion: diversified AddOn {actual:,.2f} must be "
        f"< simple sum {degenerate_sum:,.2f}. CRR Art. 280b rho=0.50 for SN."
    )


# ===========================================================================
# 4. Two trades on the same entity collapse to single aggregated D
# ===========================================================================


def test_equity_addon_two_trades_same_entity_collapse_to_single_aggregated_d() -> None:
    """Two SN trades on the same entity collapse to D_k = sum of their EN_i.

    Entity-level aggregation per CRR Art. 277(2)(d): trades sharing the same
    reference_entity within a hedging set sum their D_i before the sqrt step.
    The result must equal the single-entity formula applied to D_k = D_1 + D_2.
    """
    # Arrange — two trades, same entity, D_1=D_2=25m → D_k=50m.
    trades = pl.LazyFrame(
        [
            _enriched_equity_trade(
                trade_id="T_EQ_001",
                reference_entity="GB00B16GWD56",
                adjusted_notional=25_000_000.0,
                maturity_factor=1.0,
            ),
            _enriched_equity_trade(
                trade_id="T_EQ_002",
                reference_entity="GB00B16GWD56",  # same entity
                adjusted_notional=25_000_000.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — same result as one trade with D=50m.
    actual = result.filter(pl.col("asset_class") == "equity")["asset_class_addon"][0]
    expected_single = _addon_hs(_SF_EQ_SN, _RHO_SN, [50_000_000.0])  # collapse
    assert actual == pytest.approx(expected_single, rel=1e-9), (
        f"Same-entity collapse: expected AddOn = {expected_single:,.2f}, "
        f"got {actual!r}. Two trades on the same entity sum their EN before the sqrt step."
    )


# ===========================================================================
# 5. Single-name and index in same NS sum across sub-classes
# ===========================================================================


def test_equity_addon_single_name_and_index_in_same_ns_sum_across_sub_classes() -> None:
    """Mixed SN + IDX within the same NS: AddOn_EQ = AddOn_SN + AddOn_IDX.

    CRR Art. 280b: no cross-sub-class correlation for equity; the two sub-class
    add-ons are summed (same logic as FX cross-hedging-set simple sum).
    """
    # Arrange — one SN trade, one IDX trade, both in NS_EQ_001.
    sn_d = 50_000_000.0
    idx_d = 50_000_000.0
    trades = pl.LazyFrame(
        [
            _enriched_equity_trade(
                trade_id="T_SN",
                reference_entity="GB00B16GWD56",
                is_index=False,
                adjusted_notional=sn_d,
                maturity_factor=1.0,
            ),
            _enriched_equity_trade(
                trade_id="T_IDX",
                reference_entity="FTSE100",
                is_index=True,
                adjusted_notional=idx_d,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — one equity row (combined), value = AddOn_SN + AddOn_IDX.
    eq_row = result.filter(pl.col("asset_class") == "equity")
    assert eq_row.height == 1, (
        f"Mixed SN+IDX in same NS must produce exactly 1 equity row, got {eq_row.height}."
    )
    actual = eq_row["asset_class_addon"][0]
    addon_sn = _addon_hs(_SF_EQ_SN, _RHO_SN, [sn_d])
    addon_idx = _addon_hs(_SF_EQ_IDX, _RHO_IDX, [idx_d])
    expected = addon_sn + addon_idx
    assert actual == pytest.approx(expected, rel=1e-9), (
        f"SN+IDX mixed NS: expected AddOn_SN + AddOn_IDX = {expected:,.2f}, "
        f"got {actual!r}. CRR Art. 280b: no cross-sub-class correlation."
    )


# ===========================================================================
# 6. Mixed equity + FX emit independent asset-class rows
# ===========================================================================


def test_mixed_equity_and_fx_emit_independent_asset_class_rows() -> None:
    """Dispatcher must compute both EQ and FX add-ons for a mixed-asset netting set.

    The PFE asset-class output contract (one row per (NS, asset_class)) holds
    when the netting set carries trades of multiple asset classes.
    """
    # Arrange — one equity trade, one FX trade, same netting set NS_MIX.
    eq_trade = _enriched_equity_trade(
        trade_id="T_EQ", netting_set_id="NS_MIX",
        adjusted_notional=50_000_000.0, maturity_factor=1.0,
    )
    fx_trade = {
        "trade_id": "T_FX",
        "netting_set_id": "NS_MIX",
        "asset_class": "fx",
        "notional": 100_000_000.0,
        "currency": "USD",
        "notional_leg2": 80_000_000.0,
        "currency_leg2": "GBP",
        "adjusted_notional": 80_000_000.0,
        "supervisory_delta": 1.0,
        "maturity_factor": 1.0,
        "years_to_maturity": 1.0,
        "reference_entity": None,
        "is_index": None,
        "maturity_bucket": None,
        "commodity_type": None,
    }
    trades = pl.LazyFrame([eq_trade, fx_trade])
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
    assert asset_classes == ["equity", "fx"], (
        f"Expected asset_class rows ['equity', 'fx'], got {asset_classes}."
    )

    # Both rows must be non-null and positive.
    for row in ns_rows.to_dicts():
        assert row["asset_class_addon"] is not None and row["asset_class_addon"] > 0, (
            f"asset_class_addon must be positive for {row['asset_class']!r}, "
            f"got {row['asset_class_addon']!r}."
        )


# ===========================================================================
# 7. Credit and commodity rows still emit null addon (regression)
# ===========================================================================


def test_credit_and_commodity_asset_class_rows_still_emit_null_addon() -> None:
    """Credit / commodity rows must still emit null asset_class_addon (regression).

    Adding the equity branch must not break the contract for not-yet-implemented
    asset classes; credit and commodity rows should remain null.
    """
    # Arrange — one credit row, one commodity row (no FX / IR / equity).
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
                "reference_entity": "GB00B16GWD56",
                "is_index": False,
                "maturity_bucket": None,
                "commodity_type": None,
            },
            {
                "trade_id": "T_CO",
                "netting_set_id": "NS_CO",
                "asset_class": "commodity",
                "notional": 10_000_000.0,
                "currency": "GBP",
                "notional_leg2": None,
                "currency_leg2": None,
                "adjusted_notional": 10_000_000.0,
                "supervisory_delta": 1.0,
                "maturity_factor": 1.0,
                "years_to_maturity": 2.0,
                "reference_entity": None,
                "is_index": None,
                "maturity_bucket": None,
                "commodity_type": "OIL_GAS",
            },
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — credit row null.
    cr_row = result.filter(pl.col("asset_class") == "credit")
    assert cr_row.height == 1, "Credit row must be anchored in the output."
    assert cr_row["asset_class_addon"][0] is None, (
        f"Credit asset_class_addon must be null (deferred), "
        f"got {cr_row['asset_class_addon'][0]!r}."
    )

    # Assert — commodity row null.
    co_row = result.filter(pl.col("asset_class") == "commodity")
    assert co_row.height == 1, "Commodity row must be anchored in the output."
    assert co_row["asset_class_addon"][0] is None, (
        f"Commodity asset_class_addon must be null (deferred), "
        f"got {co_row['asset_class_addon'][0]!r}."
    )
