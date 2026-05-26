"""
Unit tests for the commodity branch of compute_addon_per_asset_class (P8.37).

Pipeline position:
    compute_adjusted_notional_commodity -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class  (← this stage)

Commodity asset-class add-on per CRR Art. 277(3)(b) + Art. 277a + Art. 280c:

    Per bucket b in {ELECTRICITY, OIL_GAS, METALS, AGRICULTURAL, OTHER}:
        e_i         = δ_i × d_i × MF_i                       (effective notional)
        D_b         = sum_i e_i  (signed sum within bucket b)
        sum_e2_b    = sum_i e_i^2
        AddOn_b     = SF_CM[b] × sqrt(ρ² × D_b² + (1−ρ²) × sum_e2_b)

    AddOn_commodity = sqrt(sum_b AddOn_b²)                     (no cross-bucket ρ)

    ρ = 0.40 (SA_CCR_CORRELATION_COMMODITY per Art. 280c)
    SF_CM: ELECTRICITY=0.40, OIL_GAS=0.18, METALS=0.18, AGRICULTURAL=0.18, OTHER=0.18
           (Art. 280 Table 2 / SA_CCR_SUPERVISORY_FACTORS_COMMODITY)

Single-trade single-bucket collapse:
    sum_e2_b = e^2; D_b = e (assuming all same-sign single trade)
    inner    = ρ² × e² + (1−ρ²) × e² = e²
    AddOn_b  = SF_CM[b] × |e|
    AddOn    = SF_CM[b] × |e|

References:
- CRR Art. 277(3)(b): 5 commodity buckets
- CRR Art. 277a(1): commodity add-on aggregation
- CRR Art. 278: PFE = multiplier × AddOn_aggregate
- CRR Art. 280 Table 2: SF_CM per bucket
- CRR Art. 280c: commodity asset-class add-on
- BCBS CRE52.67-69
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set

# Regulatory scalars (from data/tables/sa_ccr_factors.py — read-only reference).
# Single source of truth: assert these match the data-table module at test import time
# so a data-table change will surface here before the engine runs.
_SF_OIL_GAS = 0.18
_SF_ELECTRICITY = 0.40
_SF_METALS = 0.18
_RHO = 0.40  # within-bucket correlation (Art. 280c)


def _enriched_commodity_trade(
    *,
    trade_id: str = "T_CO_001",
    netting_set_id: str = "NS_CO_001",
    commodity_type: str = "OIL_GAS",
    adjusted_notional: float = 1_000_000.0,
    supervisory_delta: float = 1.0,
    maturity_factor: float = 1.0,
    years_to_maturity: float = 2.0,
) -> dict[str, object]:
    """Return a row dict for a commodity trade pre-enriched with PFE inputs.

    Matches the columns required by ``assign_hedging_set`` +
    ``compute_addon_per_asset_class``; in a full pipeline these would be
    populated by the upstream adjusted-notional / delta / MF stages.
    """
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": "commodity",
        "notional": adjusted_notional,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "adjusted_notional": adjusted_notional,
        "supervisory_delta": supervisory_delta,
        "maturity_factor": maturity_factor,
        "years_to_maturity": years_to_maturity,
        "commodity_type": commodity_type,
    }


# ===========================================================================
# 1. CCR-A7: single OIL_GAS trade, AddOn = SF × |e| = 0.18 × 1_000_000 = 180_000
# ===========================================================================


def test_oil_gas_single_trade_matches_ccr_a7_hand_calc() -> None:
    """CCR-A7 hand-calc: 2y OIL_GAS forward, e=1_000_000, AddOn=0.18×1_000_000=180_000.

    Single-trade single-bucket: formula collapses to SF_CM × |e|.
    MF = sqrt(min(2y, 1y)/1y) = sqrt(1) = 1.0, so e = 1.0 × 1_000_000 × 1.0.
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_commodity_trade(
                trade_id="T_CO_OIL_001",
                commodity_type="OIL_GAS",
                adjusted_notional=1_000_000.0,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            )
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — single (NS, commodity) row with AddOn = 0.18 × 1_000_000 = 180_000.
    co_row = result.filter(
        (pl.col("netting_set_id") == "NS_CO_001") & (pl.col("asset_class") == "commodity")
    )
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"

    expected = _SF_OIL_GAS * 1_000_000.0  # = 180_000
    actual = co_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-6), (
        f"CCR-A7 OIL_GAS hand-calc: AddOn_commodity expected {expected:,.3f}, "
        f"got {actual!r}. CRR Art. 277a(1) + Art. 280 Table 2 (SF_OIL_GAS = 0.18)."
    )


# ===========================================================================
# 2. CCR-A8: single ELECTRICITY trade — LOAD-BEARING: SF = 0.40 ≠ 0.18
# ===========================================================================


def test_electricity_single_trade_matches_ccr_a8_hand_calc() -> None:
    """CCR-A8 hand-calc: 1y ELECTRICITY swap, e≈999_657.706, AddOn≈399_863.080.

    LOAD-BEARING: confirms the ELECTRICITY SF_CM = 0.40 is applied, not the
    0.18 catch-all used for OIL_GAS/METALS/AGRICULTURAL/OTHER.

    MF = sqrt(365/365.25) ≈ 0.999657706
    e = 1.0 × 1_000_000.0 × 0.999657706 ≈ 999_657.706
    AddOn = 0.40 × 999_657.706 ≈ 399_863.080
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    # MF matches CCR-A8 hand-calc: sqrt(365/365.25).
    mf_ccr_a8 = math.sqrt(365 / 365.25)
    e_ccr_a8 = 1_000_000.0 * mf_ccr_a8

    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_commodity_trade(
                trade_id="T_CO_ELEC_001",
                netting_set_id="NS_CO_002",
                commodity_type="ELECTRICITY",
                adjusted_notional=1_000_000.0,
                supervisory_delta=1.0,
                maturity_factor=mf_ccr_a8,
                years_to_maturity=365 / 365.25,
            )
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    co_row = result.filter(
        (pl.col("netting_set_id") == "NS_CO_002") & (pl.col("asset_class") == "commodity")
    )
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"

    expected = _SF_ELECTRICITY * e_ccr_a8  # ≈ 399_863.080
    actual = co_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-6), (
        f"CCR-A8 ELECTRICITY hand-calc: AddOn_commodity expected ≈{expected:,.3f}, "
        f"got {actual!r}. "
        f"LOAD-BEARING: ELECTRICITY SF_CM = 0.40, not 0.18. "
        "CRR Art. 280 Table 2 + Art. 280c."
    )


# ===========================================================================
# 3. Two trades in the same bucket: within-bucket correlation applies
# ===========================================================================


def test_two_trades_same_bucket_apply_within_bucket_correlation() -> None:
    """Two OIL_GAS trades with e₁=e₂=e → AddOn = SF × sqrt(2.32) × e ≈ 1.5232 × SF × e.

    With ρ=0.40 and two same-sign trades each of size e:
        D_b         = e + e = 2e
        sum_e2      = e² + e² = 2e²
        inner       = ρ² × (2e)² + (1−ρ²) × 2e²
                    = 0.16 × 4e² + 0.84 × 2e²
                    = 0.64e² + 1.68e²
                    = 2.32 × e²
        AddOn_b     = SF × sqrt(2.32) × e
        AddOn_commo = AddOn_b (one bucket)
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    e = 1_000_000.0
    rho2 = _RHO**2
    one_minus_rho2 = 1.0 - rho2

    # Arrange — two OIL_GAS trades in the same netting set.
    trades = pl.LazyFrame(
        [
            _enriched_commodity_trade(
                trade_id="T_CO_OIL_001",
                commodity_type="OIL_GAS",
                adjusted_notional=e,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
            _enriched_commodity_trade(
                trade_id="T_CO_OIL_002",
                commodity_type="OIL_GAS",
                adjusted_notional=e,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    co_row = result.filter(
        (pl.col("netting_set_id") == "NS_CO_001") & (pl.col("asset_class") == "commodity")
    )
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"

    # Inner = ρ² × D_b² + (1−ρ²) × sum_e²
    D_b = e + e  # 2e (same sign)
    sum_e2 = e**2 + e**2
    inner = rho2 * D_b**2 + one_minus_rho2 * sum_e2  # = 2.32 × e²
    expected = _SF_OIL_GAS * math.sqrt(inner)

    actual = co_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-6), (
        f"Two same-bucket OIL_GAS trades: within-bucket ρ=0.40 formula expected "
        f"{expected:,.3f}, got {actual!r}. "
        "AddOn_b = SF × sqrt(ρ²×D_b² + (1−ρ²)×∑e_i²). CRR Art. 280c."
    )


# ===========================================================================
# 4. Three buckets — no cross-bucket correlation (LOAD-BEARING)
# ===========================================================================


def test_three_buckets_no_cross_bucket_correlation() -> None:
    """One OIL_GAS + one METALS + one ELECTRICITY each with effective notional e.

    AddOn_commodity = sqrt(sum_b AddOn_b²)  (no cross-bucket ρ per Art. 280c / CRE52.69)

    For a single trade per bucket with MF=1 and δ=1:
        e_i = e (each bucket has single trade)
        D_b = e, sum_e2_b = e²
        inner_b = ρ² × e² + (1−ρ²) × e² = e²  (single-trade collapse)
        AddOn_b = SF[b] × e

    So:
        AddOn_OIL_GAS     = 0.18 × e   → AddOn_OIL_GAS²     = 0.0324 × e²
        AddOn_METALS      = 0.18 × e   → AddOn_METALS²       = 0.0324 × e²
        AddOn_ELECTRICITY = 0.40 × e   → AddOn_ELECTRICITY²  = 0.16   × e²
        AddOn_commodity   = e × sqrt(0.0324 + 0.0324 + 0.16)
                          = e × sqrt(0.2248)
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    e = 1_000_000.0

    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_commodity_trade(
                trade_id="T_CO_OIL",
                netting_set_id="NS_CO_MULTI",
                commodity_type="OIL_GAS",
                adjusted_notional=e,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
            _enriched_commodity_trade(
                trade_id="T_CO_METALS",
                netting_set_id="NS_CO_MULTI",
                commodity_type="METALS",
                adjusted_notional=e,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
            _enriched_commodity_trade(
                trade_id="T_CO_ELEC",
                netting_set_id="NS_CO_MULTI",
                commodity_type="ELECTRICITY",
                adjusted_notional=e,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert
    co_row = result.filter(
        (pl.col("netting_set_id") == "NS_CO_MULTI") & (pl.col("asset_class") == "commodity")
    )
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"

    # Single-trade collapse per bucket: AddOn_b = SF[b] × e.
    addon_oil = _SF_OIL_GAS * e  # = 0.18e
    addon_metals = _SF_METALS * e  # = 0.18e
    addon_elec = _SF_ELECTRICITY * e  # = 0.40e

    # LOAD-BEARING: no cross-bucket correlation (Art. 280c / CRE52.69).
    expected = math.sqrt(addon_oil**2 + addon_metals**2 + addon_elec**2)
    # = e × sqrt(0.0324 + 0.0324 + 0.16) = e × sqrt(0.2248)

    actual = co_row["asset_class_addon"][0]
    assert actual == pytest.approx(expected, rel=1e-6), (
        f"Three-bucket commodity: no cross-bucket ρ expected "
        f"{expected:,.3f} (e × sqrt(0.2248)), got {actual!r}. "
        "LOAD-BEARING: cross-bucket correlation is zero for commodities. "
        "CRR Art. 280c + BCBS CRE52.69."
    )


# ===========================================================================
# 5. Null commodity_type row must emit null (no fallback to OTHER)
# ===========================================================================


def test_null_commodity_type_emits_null() -> None:
    """A commodity row with null commodity_type must emit null asset_class_addon.

    No implicit fallback to the 'OTHER' bucket: the engine must not silently
    assign an unknown commodity to the catch-all bucket.
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    # Arrange — commodity row with commodity_type=null.
    trades = pl.LazyFrame(
        [
            {
                "trade_id": "T_CO_UNKNOWN",
                "netting_set_id": "NS_CO_NULL",
                "asset_class": "commodity",
                "notional": 1_000_000.0,
                "currency": "GBP",
                "notional_leg2": None,
                "currency_leg2": None,
                "adjusted_notional": 1_000_000.0,
                "supervisory_delta": 1.0,
                "maturity_factor": 1.0,
                "years_to_maturity": 1.0,
                "commodity_type": None,
            }
        ],
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "notional_leg2": pl.Float64,
            "currency_leg2": pl.String,
            "adjusted_notional": pl.Float64,
            "supervisory_delta": pl.Float64,
            "maturity_factor": pl.Float64,
            "years_to_maturity": pl.Float64,
            "commodity_type": pl.String,
        },
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — null commodity_type must produce null addon, not a fallback to OTHER.
    co_row = result.filter(pl.col("asset_class") == "commodity")
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"
    assert co_row["asset_class_addon"][0] is None, (
        f"Null commodity_type must not fall back to OTHER bucket, "
        f"got asset_class_addon={co_row['asset_class_addon'][0]!r}."
    )


# ===========================================================================
# 6. Non-commodity rows unchanged: IR and FX dispatcher still produces add-ons
# ===========================================================================


def test_non_commodity_row_unchanged() -> None:
    """IR/FX rows in the same netting set must still emit their own add-ons.

    The commodity dispatcher must not suppress IR or FX add-ons when there
    are also commodity rows present.
    """
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class

    # Arrange — one FX trade + one commodity trade in separate netting sets
    # to avoid cross-asset-class interactions not under test here.
    fx_trade = {
        "trade_id": "T_FX_001",
        "netting_set_id": "NS_FX_001",
        "asset_class": "fx",
        "notional": 80_000_000.0,
        "currency": "USD",
        "notional_leg2": 80_000_000.0,
        "currency_leg2": "GBP",
        "adjusted_notional": 80_000_000.0,
        "supervisory_delta": 1.0,
        "maturity_factor": 1.0,
        "years_to_maturity": 1.0,
        "commodity_type": None,
    }
    co_trade = _enriched_commodity_trade(
        trade_id="T_CO_OIL_001",
        netting_set_id="NS_CO_001",
        commodity_type="OIL_GAS",
        adjusted_notional=1_000_000.0,
    )

    trades = pl.LazyFrame(
        [fx_trade, co_trade],
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "notional": pl.Float64,
            "currency": pl.String,
            "notional_leg2": pl.Float64,
            "currency_leg2": pl.String,
            "adjusted_notional": pl.Float64,
            "supervisory_delta": pl.Float64,
            "maturity_factor": pl.Float64,
            "years_to_maturity": pl.Float64,
            "commodity_type": pl.String,
        },
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — FX row is present and has a positive addon.
    fx_row = result.filter(pl.col("asset_class") == "fx")
    assert fx_row.height == 1, f"Expected 1 FX row, got {fx_row.height}"
    fx_addon = fx_row["asset_class_addon"][0]
    assert fx_addon is not None and fx_addon > 0, (
        f"FX asset_class_addon must be positive, got {fx_addon!r}."
    )

    # Assert — commodity row is present and has a positive addon.
    co_row = result.filter(pl.col("asset_class") == "commodity")
    assert co_row.height == 1, f"Expected 1 commodity row, got {co_row.height}"
    co_addon = co_row["asset_class_addon"][0]
    assert co_addon is not None and co_addon > 0, (
        f"Commodity asset_class_addon must be positive, got {co_addon!r}."
    )
