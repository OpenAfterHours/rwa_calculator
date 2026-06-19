"""
Unit tests: SA-CCR PFE multiplier (P8.16 / CCR-A2).

Scenario CCR-A2 — single netting set, unmargined, under-collateralised.

    NS-CCR-A2-01: v_net = -2_000_000, c_net = +500_000
                  V − C = -2_500_000  (negative → multiplier < 1)
    AddOn_aggregate = 7_830_986.18 (injected; derived in P8.10/P8.15)

Hand-calc (CRR Art. 278(3)):
    F      = 0.05,  1-F = 0.95
    denom  = 2 × 0.95 × 7_830_986.18 = 14_878_873.742
    exp    = exp(-2_500_000 / 14_878_873.742) ≈ 0.845334
    mul    = min(1,  0.05 + 0.95 × 0.845334) ≈ 0.853067
    pfe    = 0.853067 × 7_830_986.18 ≈ 6_680_358.19
    rc     = max(-2_500_000, 0) = 0.00  (Art. 275(1))
    EAD    = 1.4 × (0 + 6_680_358.19) ≈ 9_352_501.47  (Art. 274(2))

Scenario B (over-collateralised cap):
    v_net = +3_000_000, c_net = +500_000  →  V − C = +2_500_000
    uncapped multiplier > 1  →  min(1, ...) = 1.0
    pfe_addon = 1.0 × 7_830_986.18 = 7_830_986.18

References:
    - CRR Art. 274(2) — EAD = α × (RC + PFE), α = 1.4
    - CRR Art. 275(1) — RC_unmargined = max(V_net − C_net, 0)
    - CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate
    - CRR Art. 278(2) — AddOn_aggregate = sum over asset classes
    - CRR Art. 278(3) — PFE multiplier formula and F = 0.05 floor
    - BCBS CRE52.20-23 — multiplier definition, V−C semantics, F floor
    - tests/fixtures/ccr/pfe_multiplier_builder.py — scenario constants and builders
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.ccr.pfe_multiplier_builder import (
    CCR_A2_ADDON_AGGREGATE,
    CCR_A2_EXPECTED_EAD,
    CCR_A2_EXPECTED_MULTIPLIER,
    CCR_A2_EXPECTED_PFE_ADDON,
    CCR_A2_EXPECTED_RC,
    CCR_A2_NETTING_SET_ID,
    CCR_A2B_EXPECTED_MULTIPLIER,
    CCR_A2B_EXPECTED_PFE_ADDON,
    CCR_A2B_NETTING_SET_ID,
    make_ccr_a2_netting_sets,
    make_ccr_a2b_netting_sets,
)

# ---------------------------------------------------------------------------
# Subject under test — lazy import so failure is at assertion, not at module load.
# If compute_pfe is not yet exported, the test body calls compute_pfe(...)
# which will raise a NameError / TypeError on None, giving a clean failure.
# ---------------------------------------------------------------------------

try:
    from rwa_calc.engine.ccr.pfe import compute_pfe
except (ImportError, ModuleNotFoundError, AttributeError):
    compute_pfe = None  # ty: ignore[invalid-assignment]


# ===========================================================================
# 1. Scenario A — under-collateralised: pfe_multiplier is strictly < 1.
# ===========================================================================


def test_ccr_a2_pfe_multiplier_under_collateralised() -> None:
    """compute_pfe must produce pfe_multiplier ≈ 0.8530672945143725 for CCR-A2.

    Reviewer-gate constraint: multiplier must be < 1.0 (anti-degenerate check).

    Arrange:
        NS-CCR-A2-01: v_net=-2_000_000, c_net=+500_000 → V−C = -2_500_000.
        addon_aggregate = 7_830_986.18 (injected).

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-01.

    Assert:
        pfe_multiplier == approx(CCR_A2_EXPECTED_MULTIPLIER, abs=1e-9).
        pfe_multiplier < 1.0.  (reviewer-gate: anti-degenerate check)

    References: CRR Art. 278(3) — multiplier = min(1, F + (1−F) × exp(...)).
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert — exact multiplier value
    actual_multiplier = row["pfe_multiplier"][0]
    assert actual_multiplier == pytest.approx(CCR_A2_EXPECTED_MULTIPLIER, abs=1e-9), (
        f"CCR-A2: pfe_multiplier expected ≈ {CCR_A2_EXPECTED_MULTIPLIER}, "
        f"got {actual_multiplier!r}. "
        "CRR Art. 278(3): multiplier = min(1, F + (1−F) × exp((V−C) / (2(1−F)×AddOn)))."
    )

    # Assert — reviewer-gate: multiplier must be strictly below 1 for under-collateralised NS
    assert actual_multiplier < 1.0, (
        f"CCR-A2 (under-collateralised): pfe_multiplier must be < 1.0, "
        f"got {actual_multiplier!r}. "
        "V − C = -2_500_000 < 0 drives the exponential below 1, so the formula "
        "must return a multiplier strictly less than 1. "
        "CRR Art. 278(3): the min(1, ...) cap only binds when multiplier ≥ 1."
    )


# ===========================================================================
# 2. Scenario A — pfe_addon (= multiplier × addon_aggregate).
# ===========================================================================


def test_ccr_a2_pfe_addon_value() -> None:
    """compute_pfe must produce pfe_addon ≈ CCR_A2_EXPECTED_PFE_ADDON for CCR-A2.

    Arrange:
        NS-CCR-A2-01 as above.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-01.

    Assert:
        pfe_addon == approx(CCR_A2_EXPECTED_PFE_ADDON, abs=1e-2).

    References: CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_pfe_addon = row["pfe_addon"][0]
    assert actual_pfe_addon == pytest.approx(CCR_A2_EXPECTED_PFE_ADDON, abs=1e-2), (
        f"CCR-A2: pfe_addon expected ≈ {CCR_A2_EXPECTED_PFE_ADDON:,.2f}, "
        f"got {actual_pfe_addon!r}. "
        "CRR Art. 278(1): PFE = multiplier × AddOn_aggregate = "
        f"{CCR_A2_EXPECTED_MULTIPLIER:.6f} × {CCR_A2_ADDON_AGGREGATE:,.2f}."
    )


# ===========================================================================
# 3. Scenario A — rc_unmargined = 0.0 (V−C < 0 → floor at zero).
# ===========================================================================


def test_ccr_a2_rc_unmargined_zero() -> None:
    """compute_pfe must produce rc_unmargined == 0.0 when V − C < 0.

    Arrange:
        NS-CCR-A2-01: V − C = -2_500_000 < 0.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-01.

    Assert:
        rc_unmargined == 0.0.

    References: CRR Art. 275(1) — RC = max(V_net − C_net, 0); floored at zero.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_rc = row["rc_unmargined"][0]
    assert actual_rc == CCR_A2_EXPECTED_RC, (
        f"CCR-A2: rc_unmargined expected {CCR_A2_EXPECTED_RC} (zero floor), "
        f"got {actual_rc!r}. "
        "V − C = -2_500_000 < 0; CRR Art. 275(1): RC = max(V−C, 0) = 0."
    )


# ===========================================================================
# 4. Scenario A — ead_ccr = α × (RC + PFE) = 1.4 × pfe_addon.
# ===========================================================================


def test_ccr_a2_ead_ccr_value() -> None:
    """compute_pfe must produce ead_ccr ≈ CCR_A2_EXPECTED_EAD for CCR-A2.

    Arrange:
        NS-CCR-A2-01 as above.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-01.

    Assert:
        ead_ccr == approx(CCR_A2_EXPECTED_EAD, abs=1e-2).

    References: CRR Art. 274(2) — EAD = α × (RC + PFE), α = 1.4.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_ead = row["ead_ccr"][0]
    assert actual_ead == pytest.approx(CCR_A2_EXPECTED_EAD, abs=1e-2), (
        f"CCR-A2: ead_ccr expected ≈ {CCR_A2_EXPECTED_EAD:,.2f}, "
        f"got {actual_ead!r}. "
        "CRR Art. 274(2): EAD = 1.4 × (RC + PFE) = 1.4 × (0 + pfe_addon)."
    )


# ===========================================================================
# 5. Scenario B — over-collateralised: pfe_multiplier is capped at 1.0.
# ===========================================================================


def test_ccr_a2b_pfe_multiplier_capped_at_one() -> None:
    """compute_pfe must cap pfe_multiplier at 1.0 when V − C > 0.

    Regression guard against dropping the min(1, ...) cap in the formula.

    Arrange:
        NS-CCR-A2-02: v_net=+3_000_000, c_net=+500_000 → V−C = +2_500_000.
        addon_aggregate = 7_830_986.18.
        Uncapped multiplier ≈ 1.174 → min(1, 1.174) = 1.0.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-02.

    Assert:
        pfe_multiplier == 1.0.

    References: CRR Art. 278(3) — min(1, ...) ensures multiplier never exceeds 1.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2b_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2B_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2B_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_multiplier = row["pfe_multiplier"][0]
    assert actual_multiplier == CCR_A2B_EXPECTED_MULTIPLIER, (
        f"CCR-A2B (over-collateralised): pfe_multiplier expected "
        f"{CCR_A2B_EXPECTED_MULTIPLIER} (capped at 1.0), "
        f"got {actual_multiplier!r}. "
        "V − C = +2_500_000 > 0; uncapped formula gives > 1; "
        "CRR Art. 278(3): min(1, ...) must clamp the result to 1.0."
    )


# ===========================================================================
# 6. Scenario B — pfe_addon is the full addon_aggregate (multiplier = 1.0).
# ===========================================================================


def test_ccr_a2b_pfe_addon_full_pass_through() -> None:
    """compute_pfe must pass through addon_aggregate unchanged when multiplier = 1.0.

    When pfe_multiplier is capped at 1.0, pfe_addon == addon_aggregate exactly
    (no multiplier discount applied).

    Arrange:
        NS-CCR-A2-02: multiplier = 1.0 (capped, over-collateralised).

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-CCR-A2-02.

    Assert:
        pfe_addon == approx(CCR_A2B_EXPECTED_PFE_ADDON, abs=1e-2).
        (CCR_A2B_EXPECTED_PFE_ADDON == addon_aggregate == 7_830_986.18)

    References: CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate = 1.0 × AddOn.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2b_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_A2B_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_A2B_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_pfe_addon = row["pfe_addon"][0]
    assert actual_pfe_addon == pytest.approx(CCR_A2B_EXPECTED_PFE_ADDON, abs=1e-2), (
        f"CCR-A2B: pfe_addon expected ≈ {CCR_A2B_EXPECTED_PFE_ADDON:,.2f} "
        f"(= addon_aggregate, full pass-through), got {actual_pfe_addon!r}. "
        "CRR Art. 278(1): PFE = 1.0 × AddOn_aggregate — no discount when capped."
    )


# ===========================================================================
# 7. Return type — compute_pfe must return a pl.LazyFrame.
# ===========================================================================


def test_ccr_a2_compute_pfe_returns_lazyframe() -> None:
    """compute_pfe must return a pl.LazyFrame (no internal .collect()).

    The pipeline's LazyFrame-first convention forbids calling .collect()
    inside engine functions.

    Arrange: 1-row LazyFrame from make_ccr_a2_netting_sets().

    Act: call compute_pfe(netting_sets) without calling .collect().

    Assert: return value is an instance of pl.LazyFrame.

    References: CLAUDE.md § Polars Conventions — LazyFrame first.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented (P8.16)."
        )

    netting_sets = make_ccr_a2_netting_sets()

    # Act
    result = compute_pfe(netting_sets)

    # Assert
    assert isinstance(result, pl.LazyFrame), (
        f"compute_pfe must return pl.LazyFrame, got {type(result).__name__!r}. "
        "Never call .collect() inside the function. CLAUDE.md § Polars Conventions."
    )
