"""
Unit tests for the credit branch of compute_addon_per_asset_class (P8.35).

Pipeline position:
    compute_adjusted_notional_credit -> compute_supervisory_delta_linear
    -> compute_maturity_factor_unmargined -> assign_hedging_set
    -> compute_addon_per_asset_class  (← this stage, credit branch)

Credit asset-class add-on per CRR Art. 277(2)(c) + Art. 277a + Art. 280a:

    One hedging set per netting set for the credit asset class.
    EN_entity = sum_i (delta_i × d_i × MF_i)  for trades on the same entity.
    AddOn_entity = SF_CR × EN_entity  (signed).

    SF_CR lookup (Art. 280 Table 2):
        Single-name: IG=0.0046, HY=0.013, NON_RATED=0.06
        Index:       IG=0.0038, HY=0.0106

    rho (Art. 280a):
        Single-name: 0.50
        Index:       0.80

    AddOn_credit_HS = sqrt(
        (rho × sum_k AddOn_entity_k)^2
        + (1 - rho^2) × sum_k AddOn_entity_k^2
    )

References:
- CRR Art. 277(2)(c): one credit hedging set per netting set.
- CRR Art. 277a(1)(b): credit add-on aggregation formula.
- CRR Art. 280 Table 2: supervisory factors for credit.
- CRR Art. 280a: credit correlations (0.50 SN / 0.80 IDX).
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class


# Scalars from Art. 280 Table 2 + Art. 280a — mirrored here so each assertion
# can show the regulatory derivation inline.
_SF_SN_IG: float = 0.0046
_SF_SN_HY: float = 0.013
_SF_SN_NON_RATED: float = 0.06
_SF_IDX_IG: float = 0.0038
_SF_IDX_HY: float = 0.0106
_RHO_SN: float = 0.50
_RHO_IDX: float = 0.80


def _enriched_credit_trade(
    *,
    trade_id: str = "T_CR_001",
    netting_set_id: str = "NS_CR_001",
    reference_entity: str = "ACME_LEI_5493001A",
    is_index: bool = False,
    credit_quality: str = "IG",
    adjusted_notional: float = 438_349_124.271,  # full-precision: E = 1826/365.25
    supervisory_delta: float = 1.0,
    maturity_factor: float = 1.0,
    years_to_maturity: float = 4.9993155373,  # full-precision: 1826/365.25
) -> dict[str, object]:
    """Return a row dict for a credit trade pre-enriched with all PFE inputs.

    Fields required by ``assign_hedging_set`` + ``compute_addon_per_asset_class``.
    """
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": "credit",
        "notional": 100_000_000.0,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "reference_entity": reference_entity,
        "is_index": is_index,
        "credit_quality": credit_quality,
        "adjusted_notional": adjusted_notional,
        "supervisory_delta": supervisory_delta,
        "maturity_factor": maturity_factor,
        "years_to_maturity": years_to_maturity,
    }


# ===========================================================================
# 1. Single-name IG — CCR-A3 load-bearing value (2,016,364.569)
# ===========================================================================


def test_credit_addon_single_name_ig_matches_ccr_a3_hand_calc() -> None:
    """CCR-A3: single SN IG CDS → AddOn = SF × |EN| = 0.0046 × 438,349,124.271.

    Full-precision values (E = 1826/365.25 = 4.9993155373):
        d = 100m × SD(0.04, 4.9993155373) = 438,349,124.271 GBP
        AddOn = 0.0046 × 438,349,124.271 = 2,016,405.972

    With one entity in the hedging set the formula collapses to SF × |EN|
    regardless of rho:
        systematic    = (0.50 × 2,016,405.972)^2
        idiosyncratic = 0.75 × 2,016,405.972^2
        sqrt(sys + idi) = 2,016,405.972 (identity for single entity)

    This is the primary load-bearing pin for P8.35.
    """
    # Arrange
    trades = pl.LazyFrame([_enriched_credit_trade()])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — one (NS_CR_001, credit) row with the CCR-A3 add-on.
    cr_row = result.filter(
        (pl.col("netting_set_id") == "NS_CR_001") & (pl.col("asset_class") == "credit")
    )
    assert cr_row.height == 1, f"Expected 1 credit row, got {cr_row.height}."

    en = 1.0 * 438_349_124.271 * 1.0  # delta × d × MF (full-precision: E = 1826/365.25)
    addon_entity = _SF_SN_IG * en
    expected = addon_entity  # single-entity collapse — sqrt(rho²×X² + (1-rho²)×X²) = |X|
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"CCR-A3 hand-calc: AddOn_credit expected {expected:,.3f} GBP, "
        f"got {actual!r}. SF_SN_IG={_SF_SN_IG}, EN={en:,.3f}. "
        "CRR Art. 277a + Art. 280 Table 2."
    )


# ===========================================================================
# 2. Single-name HY: SF = 1.3%
# ===========================================================================


def test_credit_addon_single_name_hy_uses_1_3_pct_sf() -> None:
    """Single-name HY CDS uses SF = 0.013 per Art. 280 Table 2.

    EN = 1.0 × 438,349,124.271 × 1.0 = 438,349,124.271  (full-precision E = 1826/365.25)
    AddOn = 0.013 × 438,349,124.271 ≈ 5,698,538.6
    """
    # Arrange
    trades = pl.LazyFrame([_enriched_credit_trade(credit_quality="HY")])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(pl.col("asset_class") == "credit")

    # Assert
    en = 438_349_124.271  # full-precision: E = 1826/365.25
    expected = _SF_SN_HY * en  # ≈ 5,698,538.6
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"SN HY: expected AddOn ≈ {expected:,.1f} (SF=0.013), "
        f"got {actual!r}. CRR Art. 280 Table 2."
    )


# ===========================================================================
# 3. Single-name NON_RATED: SF = 6%
# ===========================================================================


def test_credit_addon_single_name_non_rated_uses_6_pct_sf() -> None:
    """Single-name NON_RATED CDS uses SF = 0.06 per Art. 280 Table 2.

    EN = 438,349,124.271  (full-precision: E = 1826/365.25)
    AddOn = 0.06 × 438,349,124.271 ≈ 26,300,947.5
    """
    # Arrange
    trades = pl.LazyFrame([_enriched_credit_trade(credit_quality="NON_RATED")])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(pl.col("asset_class") == "credit")

    # Assert
    en = 438_349_124.271  # full-precision: E = 1826/365.25
    expected = _SF_SN_NON_RATED * en  # ≈ 26,300,947.5
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"SN NON_RATED: expected AddOn ≈ {expected:,.1f} (SF=0.06), "
        f"got {actual!r}. CRR Art. 280 Table 2."
    )


# ===========================================================================
# 4. Credit index IG: SF = 0.38%, rho = 0.80, collapses to SF × |EN|
# ===========================================================================


def test_credit_addon_index_ig_uses_0_38_pct_sf_and_0_80_rho() -> None:
    """Credit index IG uses SF=0.0038 and rho=0.80 per Art. 280 Table 2 + 280a.

    For a single-entity (index) hedging set the formula still collapses to
    SF × |EN| because sqrt(rho²×X² + (1-rho²)×X²) = sqrt(X²) = |X|.

    EN = 1.0 × 438,349,124.271 × 1.0 = 438,349,124.271  (full-precision)
    AddOn = 0.0038 × 438,349,124.271 ≈ 1,665,726.7
    """
    # Arrange — index=True so the IDX SF and rho apply.
    trades = pl.LazyFrame(
        [_enriched_credit_trade(is_index=True, credit_quality="IG")]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(pl.col("asset_class") == "credit")

    # Assert
    en = 438_349_124.271  # full-precision: E = 1826/365.25
    expected = _SF_IDX_IG * en  # ≈ 1,665,726.7
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"IDX IG: expected AddOn ≈ {expected:,.1f} (SF=0.0038, rho=0.80), "
        f"got {actual!r}. CRR Art. 280 Table 2 + Art. 280a."
    )


# ===========================================================================
# 5. Credit index HY: SF = 1.06%
# ===========================================================================


def test_credit_addon_index_hy_uses_1_06_pct_sf() -> None:
    """Credit index HY uses SF = 0.0106 per Art. 280 Table 2.

    EN = 438,349,124.271  (full-precision: E = 1826/365.25)
    AddOn = 0.0106 × 438,349,124.271 ≈ 4,646,500.7
    """
    # Arrange
    trades = pl.LazyFrame(
        [_enriched_credit_trade(is_index=True, credit_quality="HY")]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(pl.col("asset_class") == "credit")

    # Assert
    en = 438_349_124.271  # full-precision: E = 1826/365.25
    expected = _SF_IDX_HY * en  # ≈ 4,646,500.7
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"IDX HY: expected AddOn ≈ {expected:,.1f} (SF=0.0106), "
        f"got {actual!r}. CRR Art. 280 Table 2."
    )


# ===========================================================================
# 6. Two entities, same NS — load-bearing anti-degenerate correlation test
# ===========================================================================


def test_credit_addon_two_entities_same_hs_uses_correlation() -> None:
    """Two SN IG entities in one NS: correlation ≠ plain sum — anti-degenerate pin.

    Entity A: delta=+1, adj_notional=10m, MF=1.0 → EN_A = 10m
    Entity B: delta=+1, adj_notional=10m, MF=1.0 → EN_B = 10m

    AddOn_A = 0.0046 × 10m = 46,000
    AddOn_B = 0.0046 × 10m = 46,000
    rho = 0.50

    Art. 280a formula:
        systematic    = (rho × (AddOn_A + AddOn_B))^2 = (0.50 × 92,000)^2 = (46,000)^2
        idiosyncratic = (1 − 0.50^2) × (46,000^2 + 46,000^2)
                      = 0.75 × 2 × 46,000^2
        AddOn = sqrt((46,000)^2 + 0.75 × 2 × 46,000^2)
              = 46,000 × sqrt(1 + 1.5) = 46,000 × sqrt(2.5)
              ≈ 46,000 × 1.58114 ≈ 72,732.5

    Anti-degenerate check: plain sum = 92,000 ≠ 72,732.5.
    The test pins that the engine uses the correlation-aware formula.
    """
    # Arrange — two distinct reference entities in the same NS.
    trades = pl.LazyFrame(
        [
            _enriched_credit_trade(
                trade_id="T_A",
                netting_set_id="NS_TWO",
                reference_entity="ENTITY_A",
                credit_quality="IG",
                is_index=False,
                adjusted_notional=10_000_000.0,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
            _enriched_credit_trade(
                trade_id="T_B",
                netting_set_id="NS_TWO",
                reference_entity="ENTITY_B",
                credit_quality="IG",
                is_index=False,
                adjusted_notional=10_000_000.0,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(
        (pl.col("netting_set_id") == "NS_TWO") & (pl.col("asset_class") == "credit")
    )
    assert cr_row.height == 1, f"Expected 1 credit row for NS_TWO, got {cr_row.height}."

    # Assert — correlated formula result.
    en_a = _SF_SN_IG * 10_000_000.0  # 46,000
    en_b = _SF_SN_IG * 10_000_000.0  # 46,000
    rho = _RHO_SN
    systematic = (rho * (en_a + en_b)) ** 2
    idiosyncratic = (1.0 - rho**2) * (en_a**2 + en_b**2)
    expected = math.sqrt(systematic + idiosyncratic)  # ≈ 72,732.5

    plain_sum = en_a + en_b  # 92,000 — what a naive implementation would return
    actual = cr_row["asset_class_addon"][0]

    assert actual == pytest.approx(expected, rel=1e-6), (
        f"Two-entity NS: expected correlated AddOn ≈ {expected:,.1f} GBP, "
        f"got {actual!r}. Plain sum would be {plain_sum:,.0f}. "
        "CRR Art. 280a: rho=0.50 SN correlation formula."
    )
    # Explicitly verify it is NOT the plain sum.
    assert actual != pytest.approx(plain_sum, rel=1e-6), (
        f"Engine returned plain sum {plain_sum:,.0f} instead of correlated "
        f"formula result {expected:,.1f}. CRR Art. 280a rho correction missing."
    )


# ===========================================================================
# 7. Signed offset within entity nets to zero add-on
# ===========================================================================


def test_credit_addon_signed_offset_within_entity_nets() -> None:
    """Two trades on the same entity with opposite deltas: EN = 0 → AddOn = 0.

    Entity LEI_X: trade T_LONG (delta=+1) and T_SHORT (delta=−1), same |EN|.
    EN_entity = +adj_notional − adj_notional = 0.
    AddOn = SF × 0 = 0.
    """
    # Arrange
    trades = pl.LazyFrame(
        [
            _enriched_credit_trade(
                trade_id="T_LONG",
                netting_set_id="NS_NET",
                reference_entity="LEI_X",
                adjusted_notional=100_000_000.0,
                supervisory_delta=1.0,
                maturity_factor=1.0,
            ),
            _enriched_credit_trade(
                trade_id="T_SHORT",
                netting_set_id="NS_NET",
                reference_entity="LEI_X",
                adjusted_notional=100_000_000.0,
                supervisory_delta=-1.0,
                maturity_factor=1.0,
            ),
        ]
    )
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()
    cr_row = result.filter(
        (pl.col("netting_set_id") == "NS_NET") & (pl.col("asset_class") == "credit")
    )

    # Assert — entity-level EN = 0 → aggregate add-on = 0.
    actual = cr_row["asset_class_addon"][0]
    assert actual == pytest.approx(0.0, abs=1.0), (
        f"Opposite-delta trades on same entity: expected AddOn ≈ 0, "
        f"got {actual!r}. EN_entity = 0 → SF × 0 = 0. CRR Art. 277a."
    )


# ===========================================================================
# 8. Dispatcher emits one row per (NS, asset_class="credit") — contract test
# ===========================================================================


def test_credit_addon_emits_one_row_per_ns_credit() -> None:
    """Dispatcher contract: one (NS, asset_class) row per NS for credit rows.

    Also checks that IR/FX rows in the same frame are preserved — the dispatcher
    must not collapse non-credit rows into the credit output.
    """
    # Arrange — one credit trade in NS_CR, one IR trade in NS_IR.
    ir_trade = {
        "trade_id": "T_IR",
        "netting_set_id": "NS_IR",
        "asset_class": "interest_rate",
        "notional": 100_000_000.0,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "reference_entity": None,
        "is_index": None,
        "credit_quality": None,
        "adjusted_notional": 7.83e8,
        "supervisory_delta": 1.0,
        "maturity_factor": 1.0,
        "years_to_maturity": 10.0,
    }
    cr_trade = _enriched_credit_trade(netting_set_id="NS_CR")

    trades = pl.LazyFrame([ir_trade, cr_trade])
    with_hs = assign_hedging_set(trades)

    # Act
    result = compute_addon_per_asset_class(with_hs).collect()

    # Assert — exactly one credit row (for NS_CR), exactly one IR row (for NS_IR).
    cr_rows = result.filter(pl.col("asset_class") == "credit")
    assert cr_rows.height == 1, (
        f"Expected 1 credit row (NS_CR), got {cr_rows.height}."
    )
    assert cr_rows["netting_set_id"][0] == "NS_CR", (
        f"Credit row must be keyed on NS_CR, got {cr_rows['netting_set_id'][0]!r}."
    )

    ir_rows = result.filter(pl.col("asset_class") == "interest_rate")
    assert ir_rows.height == 1, (
        f"Expected 1 IR row (NS_IR), got {ir_rows.height}."
    )

    # Credit add-on must be populated (not null) after P8.35 lands.
    cr_addon = cr_rows["asset_class_addon"][0]
    assert cr_addon is not None, (
        f"Credit asset_class_addon must not be null after P8.35. "
        f"Got {cr_addon!r}."
    )
