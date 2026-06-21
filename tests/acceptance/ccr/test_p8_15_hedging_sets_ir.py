"""
P8.15 acceptance tests: SA-CCR IR hedging-set partition + asset-class add-on.

Pipeline position:
    fixture (make_p815_trades) -> compute_adjusted_notional_ir
    -> compute_supervisory_delta_linear -> compute_maturity_factor_unmargined
    -> assign_hedging_set -> compute_addon_per_asset_class

Key responsibilities:
- Verify that ``assign_hedging_set`` produces correct ``maturity_bucket`` and
  ``hedging_set_id`` for each IR trade based on residual maturity.
- Verify that ``compute_addon_per_asset_class`` produces the correct
  IR asset-class add-on for a two-trade netting set spanning two non-adjacent
  maturity buckets (GT_5Y and 1Y_5Y) using the Art. 277a(1)(a) cross-bucket
  aggregation formula.

Scenario: NS-IR-01 (two GBP IR trades, unmargined).
    T1: 10y tenor → maturity_bucket = "GT_5Y",
        hedging_set_id = "IR-NS-IR-01-GBP-GT_5Y",
        adjusted_notional ≈ 783_000_000 GBP.
    T2: 3y tenor → maturity_bucket = "1Y_5Y",
        hedging_set_id = "IR-NS-IR-01-GBP-1Y_5Y",
        adjusted_notional ≈ 137_323_478 GBP.

Hand-calc (Art. 277a(1)(a), SF_IR = 0.005, ρ_adj = 0.7 adjacent, ρ_non = 0.3):
    D_B2 = delta_T2 * d_T2 * MF_T2 = -1 * ~137.3M * 1.0 = ~-137.3M
    D_B3 = delta_T1 * d_T1 * MF_T1 = +1 * ~783M * 1.0 = ~+783M
    AddOn_IR = SF_IR * sqrt(
        D_B1^2 + D_B2^2 + D_B3^2
        + 2*ρ_12*D_B1*D_B2 + 2*ρ_23*D_B2*D_B3 + 2*ρ_13*D_B1*D_B3
    )
    = 0.005 * sqrt(0 + (-137.3M)^2 + (783M)^2 + 2*0.7*(-137.3M)*(783M))
    ≈ 3_469_322.89 GBP

References:
    - CRR Art. 277(1)   — hedging-set definition: one per currency within IR
    - CRR Art. 277(2)   — IR maturity bucket thresholds: LT_1Y / 1Y_5Y / GT_5Y
    - CRR Art. 277a(1)  — intra-asset-class add-on aggregation formula
    - CRR Art. 280a     — IR supervisory factor (SF = 0.5%), correlation ρ = 0.7
    - tests/fixtures/ccr/hedging_sets_ir_builder.py — scenario constants and builders
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.ccr.hedging_sets_ir_builder import (
    P815_CURRENCY,
    P815_NETTING_SET_ID,
    P815_START_DATE,
    P815_TRADE_ID_T1,
    P815_TRADE_ID_T2,
    make_p815_trades,
)

# ---------------------------------------------------------------------------
# Subject under test — lazy imports so tests fail at assertion, not at import.
# ---------------------------------------------------------------------------

try:
    from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
except (ImportError, ModuleNotFoundError):
    assign_hedging_set = None  # ty: ignore[invalid-assignment]

try:
    from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class
except (ImportError, ModuleNotFoundError, AttributeError):
    compute_addon_per_asset_class = None  # ty: ignore[invalid-assignment]

# These are already shipped (P8.12 / P8.13 / P8.14) — import must succeed.
from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_ir
from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined
from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_linear

# ---------------------------------------------------------------------------
# Expected values (single source of truth — mirrors fixture module constants).
# ---------------------------------------------------------------------------

_EXPECTED_BUCKET_T1: str = "GT_5Y"
_EXPECTED_BUCKET_T2: str = "1Y_5Y"
_EXPECTED_HSID_T1: str = f"IR-{P815_NETTING_SET_ID}-{P815_CURRENCY}-{_EXPECTED_BUCKET_T1}"
_EXPECTED_HSID_T2: str = f"IR-{P815_NETTING_SET_ID}-{P815_CURRENCY}-{_EXPECTED_BUCKET_T2}"

# Art. 277a(1)(a) hand-calc result (see module docstring for derivation).
_EXPECTED_ADDON: float = 3_469_322.89

# MF for T1 (10y, unmargined, cap=1y): sqrt(min(10, 1) / 1) = 1.0
# MF for T2 (3y,  unmargined, cap=1y): sqrt(min(3, 1) / 1) = 1.0
_MF_T1: float = 1.0
_MF_T2: float = 1.0


# ---------------------------------------------------------------------------
# Helper: build the enriched trade LazyFrame the engine functions expect.
# ---------------------------------------------------------------------------


def _make_enriched_trades() -> pl.LazyFrame:
    """
    Build trades with adjusted_notional, supervisory_delta, years_to_maturity,
    and maturity_factor columns attached.

    This mirrors the pipeline sub-sequence that precedes assign_hedging_set:
        compute_adjusted_notional_ir -> compute_supervisory_delta_linear
        -> add years_to_maturity -> compute_maturity_factor_unmargined
    """
    trades = make_p815_trades()

    # Step 1 — adjusted notional (d_i) per Art. 279b.
    trades = compute_adjusted_notional_ir(trades, reporting_date=P815_START_DATE)

    # Step 2 — supervisory delta (+/-1) per Art. 279a(1).
    trades = compute_supervisory_delta_linear(trades)

    # Step 3 — residual-maturity measures: years_to_maturity (calendar, for the
    # Art. 277 IR maturity buckets) and business_days_to_maturity (for the
    # Art. 279c(1) unmargined maturity factor). Both T1 (10y) and T2 (3y) are
    # well above the 1-year cap, so MF = 1.0 on either basis.
    trades = trades.with_columns(
        ((pl.col("maturity_date") - pl.lit(P815_START_DATE)).dt.total_days() / 365.25).alias(
            "years_to_maturity"
        ),
        pl.business_day_count(pl.lit(P815_START_DATE), pl.col("maturity_date")).alias(
            "business_days_to_maturity"
        ),
    )

    # Step 4 — maturity factor MF per Art. 279c(1): sqrt(min(BD, 250)/250).
    trades = compute_maturity_factor_unmargined(trades)

    return trades


# ===========================================================================
# 1. assign_hedging_set produces exactly two distinct hedging_set_id values.
# ===========================================================================


def test_assign_hedging_set_produces_two_distinct_ids() -> None:
    """assign_hedging_set must produce exactly 2 distinct hedging_set_id values.

    Arrange:
        Two IR GBP trades in NS-IR-01 — T1 (GT_5Y bucket) and T2 (1Y_5Y bucket).

    Act:
        assign_hedging_set(enriched_trades).collect()

    Assert:
        len(result["hedging_set_id"].unique()) == 2.

    References: CRR Art. 277(1) — one hedging set per currency within IR class.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()

    # Act
    result = assign_hedging_set(trades).collect()

    # Assert
    n_distinct = result["hedging_set_id"].n_unique()
    assert n_distinct == 2, (
        f"Expected 2 distinct hedging_set_id values (one per maturity bucket), "
        f"got {n_distinct}. "
        "CRR Art. 277(1): one hedging set per currency-bucket within the IR asset class."
    )


# ===========================================================================
# 2. T1 (10-year trade) maps to the GT_5Y maturity bucket.
# ===========================================================================


def test_t1_bucket_gt_5y() -> None:
    """T1 (10y IR swap) must be assigned maturity_bucket == 'GT_5Y'.

    Arrange:
        T1: start=2026-05-23, maturity=2036-05-23 → residual tenor ≈ 10y > 5y.

    Act:
        assign_hedging_set(enriched_trades).collect()
        filter to T1.

    Assert:
        maturity_bucket == "GT_5Y".

    References: CRR Art. 277(2)(c) — bucket GT_5Y for residual maturity > 5y.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()

    # Act
    result = assign_hedging_set(trades).collect()
    t1_row = result.filter(pl.col("trade_id") == P815_TRADE_ID_T1)

    # Assert
    assert t1_row.height == 1, f"T1 row not found in result (height={t1_row.height})."
    actual_bucket = t1_row["maturity_bucket"][0]
    assert actual_bucket == _EXPECTED_BUCKET_T1, (
        f"T1 (10y tenor): expected maturity_bucket={_EXPECTED_BUCKET_T1!r}, "
        f"got {actual_bucket!r}. "
        "CRR Art. 277(2)(c): residual maturity > 5 years → GT_5Y bucket."
    )


# ===========================================================================
# 3. T2 (3-year trade) maps to the 1Y_5Y maturity bucket.
# ===========================================================================


def test_t2_bucket_1y_5y() -> None:
    """T2 (3y IR swap) must be assigned maturity_bucket == '1Y_5Y'.

    Arrange:
        T2: start=2026-05-23, maturity=2029-05-23 → residual tenor ≈ 3y ∈ [1, 5].

    Act:
        assign_hedging_set(enriched_trades).collect()
        filter to T2.

    Assert:
        maturity_bucket == "1Y_5Y".

    References: CRR Art. 277(2)(b) — bucket 1Y_5Y for 1y ≤ residual maturity ≤ 5y.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()

    # Act
    result = assign_hedging_set(trades).collect()
    t2_row = result.filter(pl.col("trade_id") == P815_TRADE_ID_T2)

    # Assert
    assert t2_row.height == 1, f"T2 row not found in result (height={t2_row.height})."
    actual_bucket = t2_row["maturity_bucket"][0]
    assert actual_bucket == _EXPECTED_BUCKET_T2, (
        f"T2 (3y tenor): expected maturity_bucket={_EXPECTED_BUCKET_T2!r}, "
        f"got {actual_bucket!r}. "
        "CRR Art. 277(2)(b): 1y ≤ residual maturity ≤ 5y → 1Y_5Y bucket."
    )


# ===========================================================================
# 4. T1's hedging_set_id encodes the correct currency and bucket.
# ===========================================================================


def test_t1_hedging_set_id_format() -> None:
    """T1's hedging_set_id must be 'IR-NS-IR-01-GBP-GT_5Y'.

    The format is: 'IR-<netting_set_id>-<currency>-<maturity_bucket>'.

    Arrange:
        T1 belongs to NS-IR-01, currency GBP, bucket GT_5Y.

    Act:
        assign_hedging_set(enriched_trades).collect()
        filter to T1.

    Assert:
        hedging_set_id == "IR-NS-IR-01-GBP-GT_5Y".

    References: CRR Art. 277(1) — hedging sets separated by currency within IR.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()

    # Act
    result = assign_hedging_set(trades).collect()
    t1_row = result.filter(pl.col("trade_id") == P815_TRADE_ID_T1)

    # Assert
    assert t1_row.height == 1, f"T1 row not found in result (height={t1_row.height})."
    actual_hsid = t1_row["hedging_set_id"][0]
    assert actual_hsid == _EXPECTED_HSID_T1, (
        f"T1: expected hedging_set_id={_EXPECTED_HSID_T1!r}, got {actual_hsid!r}. "
        "Format must be 'IR-<netting_set_id>-<currency>-<maturity_bucket>'."
    )


# ===========================================================================
# 5. T2's hedging_set_id encodes the correct currency and bucket.
# ===========================================================================


def test_t2_hedging_set_id_format() -> None:
    """T2's hedging_set_id must be 'IR-NS-IR-01-GBP-1Y_5Y'.

    The format is: 'IR-<netting_set_id>-<currency>-<maturity_bucket>'.

    Arrange:
        T2 belongs to NS-IR-01, currency GBP, bucket 1Y_5Y.

    Act:
        assign_hedging_set(enriched_trades).collect()
        filter to T2.

    Assert:
        hedging_set_id == "IR-NS-IR-01-GBP-1Y_5Y".

    References: CRR Art. 277(1) — hedging sets separated by currency within IR.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()

    # Act
    result = assign_hedging_set(trades).collect()
    t2_row = result.filter(pl.col("trade_id") == P815_TRADE_ID_T2)

    # Assert
    assert t2_row.height == 1, f"T2 row not found in result (height={t2_row.height})."
    actual_hsid = t2_row["hedging_set_id"][0]
    assert actual_hsid == _EXPECTED_HSID_T2, (
        f"T2: expected hedging_set_id={_EXPECTED_HSID_T2!r}, got {actual_hsid!r}. "
        "Format must be 'IR-<netting_set_id>-<currency>-<maturity_bucket>'."
    )


# ===========================================================================
# 6. IR asset-class add-on value for NS-IR-01.
# ===========================================================================


def test_ir_asset_class_addon_value() -> None:
    """compute_addon_per_asset_class must produce asset_class_addon ≈ 3_469_322.89 GBP.

    Hand-calc (CRR Art. 277a(1)(a), SF_IR = 0.005):
        D_B2 = δ_T2 * d_T2 * MF_T2 = -1 * ~137.3M * 1.0 ≈ -137_323_478
        D_B3 = δ_T1 * d_T1 * MF_T1 = +1 * ~783M * 1.0 ≈ +783_000_000
        AddOn_IR = 0.005 * sqrt(
            D_B2^2 + D_B3^2 + 2 * 0.7 * D_B2 * D_B3
        )
               ≈ 3_469_322.89 GBP

    Arrange:
        Two-trade LazyFrame enriched with adjusted_notional, supervisory_delta,
        maturity_factor, maturity_bucket, hedging_set_id.

    Act:
        compute_addon_per_asset_class(enriched_with_hedging_sets).collect()

    Assert:
        Row for NS-IR-01 / interest_rate: asset_class_addon ≈ 3_469_322.89 (abs=1e-2).

    References:
        CRR Art. 277a(1)(a): effective notional per bucket, cross-bucket aggregation.
        CRR Art. 280a: SF_IR = 0.005, adjacency correlation ρ = 0.7.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set is not importable from "
            "rwa_calc.engine.ccr.hedging_sets — module not yet implemented (P8.15). "
            "Cannot build enriched trades for add-on test."
        )
    if compute_addon_per_asset_class is None:
        pytest.fail(
            "compute_addon_per_asset_class is not importable from "
            "rwa_calc.engine.ccr.pfe — function not yet implemented (P8.15)."
        )

    trades = _make_enriched_trades()
    trades_with_hs = assign_hedging_set(trades)

    # Act
    addon_df = compute_addon_per_asset_class(trades_with_hs).collect()

    # Assert: result must have a row for NS-IR-01 + interest_rate asset class.
    ns_ir_row = addon_df.filter(
        (pl.col("netting_set_id") == P815_NETTING_SET_ID)
        & (pl.col("asset_class") == "interest_rate")
    )
    assert ns_ir_row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={P815_NETTING_SET_ID!r} "
        f"and asset_class='interest_rate', got {ns_ir_row.height} rows. "
        "compute_addon_per_asset_class must return one row per (netting_set_id, asset_class)."
    )

    actual_addon = ns_ir_row["asset_class_addon"][0]
    assert actual_addon == pytest.approx(_EXPECTED_ADDON, abs=1e-2), (
        f"IR asset-class add-on for NS-IR-01: expected ≈ {_EXPECTED_ADDON:,.2f} GBP, "
        f"got {actual_addon:,.2f} GBP. "
        "CRR Art. 277a(1)(a): AddOn = SF_IR * sqrt(sum_b(D_b^2) + 2*sum_bc(ρ_bc*D_b*D_c)); "
        "SF_IR=0.005, ρ_adjacent=0.7 (CRR Art. 280a)."
    )
