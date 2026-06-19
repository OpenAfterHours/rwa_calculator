"""
Unit tests: P6.33 — compute_pfe RC delegation refactor.

P6.33 is a calculation-neutral de-duplication refactor: ``compute_pfe`` in
``src/rwa_calc/engine/ccr/pfe.py`` currently inlines
``pl.max_horizontal(v_minus_c, pl.lit(0.0)).alias("rc_unmargined")`` instead of
delegating to the canonical ``compute_rc_unmargined`` from
``src/rwa_calc/engine/ccr/rc.py``.  Wave-4 will refactor ``compute_pfe`` to call
``compute_rc_unmargined``.

Test structure
--------------
1. **Delegation contract** (FAIL today, PASS after Wave-4 refactor):
   ``test_compute_pfe_delegates_to_compute_rc_unmargined`` — source-level
   assertion that ``compute_pfe``'s source text references
   ``compute_rc_unmargined``.

2. **Value-golden quartet on NS-P6.33-01** (PASS today, regression pins):
   - ``test_p6_33_rc_unmargined_is_active`` — RC = 150_000 (V−C > 0 path).
   - ``test_p6_33_pfe_multiplier_capped`` — multiplier capped at 1.0.
   - ``test_p6_33_pfe_addon_value`` — PFE addon = 7_830_986.18.
   - ``test_p6_33_ead_ccr_includes_rc`` — EAD = 11_173_380.652.

3. **Delegation-equivalence** (PASS today, regression pin):
   ``test_p6_33_rc_unmargined_equals_canonical_compute_rc_unmargined`` —
   ``compute_pfe`` RC column equals ``compute_rc_unmargined`` for the same frame.

References:
    - CRR Art. 274(2) — EAD = α × (RC + PFE), α = 1.4
    - CRR Art. 275(1) — RC_unmargined = max(V_net − C_net, 0)
    - CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate
    - CRR Art. 278(3) — PFE multiplier formula and F = 0.05 floor
    - tests/fixtures/ccr/pfe_multiplier_builder.py — scenario constants and builders
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from tests.fixtures.ccr.pfe_multiplier_builder import (
    CCR_P6_33_EXPECTED_EAD,
    CCR_P6_33_EXPECTED_MULTIPLIER,
    CCR_P6_33_EXPECTED_PFE_ADDON,
    CCR_P6_33_EXPECTED_RC,
    CCR_P6_33_NETTING_SET_ID,
    make_ccr_p6_33_netting_sets,
)

# ---------------------------------------------------------------------------
# Subject under test — lazy import so failure is at assertion, not at module load.
# ---------------------------------------------------------------------------

try:
    from rwa_calc.engine.ccr.pfe import compute_pfe
except (ImportError, ModuleNotFoundError, AttributeError):
    compute_pfe = None  # ty: ignore[invalid-assignment]

try:
    from rwa_calc.engine.ccr.rc import compute_rc_unmargined
except (ImportError, ModuleNotFoundError, AttributeError):
    compute_rc_unmargined = None  # ty: ignore[invalid-assignment]

try:
    import rwa_calc.engine.ccr.pfe as pfe_mod
except (ImportError, ModuleNotFoundError):
    pfe_mod = None  # ty: ignore[invalid-assignment]


# ===========================================================================
# 1. Delegation contract — FAIL today, PASS after Wave-4 refactor.
# ===========================================================================


def test_compute_pfe_delegates_to_compute_rc_unmargined() -> None:
    """compute_pfe source must reference compute_rc_unmargined (P6.33 delegation contract).

    This test is the FAIL-FIRST driver for the Wave-4 refactor.  Today
    ``compute_pfe`` inlines ``pl.max_horizontal(v_minus_c, pl.lit(0.0)).alias(
    "rc_unmargined")``; after the refactor it must call the canonical
    ``compute_rc_unmargined`` from ``rwa_calc.engine.ccr.rc``.

    Arrange:
        Import the ``pfe`` module and inspect source of ``compute_pfe``.

    Act:
        Extract source text via ``inspect.getsource(pfe_mod.compute_pfe)``.

    Assert:
        The string ``"compute_rc_unmargined"`` is present in the source.

    References: CRR Art. 275(1) — RC = max(V−C, 0) is the canonical
    compute_rc_unmargined contract.
    """
    # Arrange
    if pfe_mod is None:
        pytest.fail(
            "rwa_calc.engine.ccr.pfe is not importable — "
            "module missing or broken before the delegation contract can be tested."
        )

    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )

    # Act
    src = inspect.getsource(pfe_mod.compute_pfe)

    # Assert
    assert "compute_rc_unmargined" in src, (
        "compute_pfe must delegate unmargined RC to the canonical compute_rc_unmargined "
        "(CRR Art. 275(1)), not inline pl.max_horizontal(...).alias('rc_unmargined'). "
        "Refactor compute_pfe to call compute_rc_unmargined from rwa_calc.engine.ccr.rc "
        "before computing the PFE multiplier and EAD columns (P6.33)."
    )


# ===========================================================================
# 2. Value-golden quartet on NS-P6.33-01 — regression pins (PASS today).
# ===========================================================================


def test_p6_33_rc_unmargined_is_active() -> None:
    """compute_pfe must produce rc_unmargined = 150_000.0 for NS-P6.33-01.

    This exercises the non-zero RC code path (V − C = +150_000 > 0).
    The existing CCR-A2 Scenario A always returns RC = 0 (V − C < 0),
    so this scenario is the sole regression pin for the RC-active branch.

    Arrange:
        NS-P6.33-01: v_net = +2_000_000, c_net = +1_850_000 → V−C = +150_000.
        addon_aggregate = 7_830_986.18 (injected).

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-P6.33-01.

    Assert:
        rc_unmargined == CCR_P6_33_EXPECTED_RC (= 150_000.0, exact).

    References: CRR Art. 275(1) — RC = max(V_net − C_net, 0).
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )

    netting_sets = make_ccr_p6_33_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_P6_33_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_P6_33_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_rc = row["rc_unmargined"][0]
    assert actual_rc == CCR_P6_33_EXPECTED_RC, (
        f"P6.33: rc_unmargined expected {CCR_P6_33_EXPECTED_RC} (= max(+150_000, 0)), "
        f"got {actual_rc!r}. "
        "V − C = +150_000 > 0; CRR Art. 275(1): RC = max(V−C, 0) must be non-zero."
    )


def test_p6_33_pfe_multiplier_capped() -> None:
    """compute_pfe must produce pfe_multiplier = 1.0 for NS-P6.33-01 (cap binds).

    V − C = +150_000 > 0: the uncapped formula evaluates to > 1, so
    min(1, ...) clamps the result to 1.0.

    Arrange:
        NS-P6.33-01: v_net = +2_000_000, c_net = +1_850_000.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-P6.33-01.

    Assert:
        pfe_multiplier == CCR_P6_33_EXPECTED_MULTIPLIER (= 1.0, exact).

    References: CRR Art. 278(3) — min(1, F + (1−F)×exp(...)) caps at 1.0.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )

    netting_sets = make_ccr_p6_33_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_P6_33_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_P6_33_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_multiplier = row["pfe_multiplier"][0]
    assert actual_multiplier == CCR_P6_33_EXPECTED_MULTIPLIER, (
        f"P6.33: pfe_multiplier expected {CCR_P6_33_EXPECTED_MULTIPLIER} (capped at 1.0), "
        f"got {actual_multiplier!r}. "
        "V − C = +150_000 > 0; CRR Art. 278(3): min(1, ...) must clamp to 1.0."
    )


def test_p6_33_pfe_addon_value() -> None:
    """compute_pfe must produce pfe_addon ≈ 7_830_986.18 for NS-P6.33-01.

    multiplier = 1.0 → pfe_addon = 1.0 × addon_aggregate = addon_aggregate exactly.

    Arrange:
        NS-P6.33-01: addon_aggregate = 7_830_986.18, multiplier = 1.0.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-P6.33-01.

    Assert:
        pfe_addon == approx(CCR_P6_33_EXPECTED_PFE_ADDON, abs=1e-2).

    References: CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )

    netting_sets = make_ccr_p6_33_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_P6_33_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_P6_33_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_pfe_addon = row["pfe_addon"][0]
    assert actual_pfe_addon == pytest.approx(CCR_P6_33_EXPECTED_PFE_ADDON, abs=1e-2), (
        f"P6.33: pfe_addon expected ≈ {CCR_P6_33_EXPECTED_PFE_ADDON:,.2f}, "
        f"got {actual_pfe_addon!r}. "
        "CRR Art. 278(1): PFE = 1.0 × AddOn_aggregate (full pass-through when capped)."
    )


def test_p6_33_ead_ccr_includes_rc() -> None:
    """compute_pfe must produce ead_ccr ≈ 11_173_380.652 for NS-P6.33-01.

    EAD = 1.4 × (RC + PFE) = 1.4 × (150_000 + 7_830_986.18) = 11_173_380.652.
    This is the load-bearing test for the non-zero RC contribution to EAD.

    Arrange:
        NS-P6.33-01: RC = 150_000, PFE = 7_830_986.18.

    Act:
        compute_pfe(netting_sets).collect(), filter to NS-P6.33-01.

    Assert:
        ead_ccr == approx(CCR_P6_33_EXPECTED_EAD, abs=1e-2).

    References: CRR Art. 274(2) — EAD = α × (RC + PFE), α = 1.4.
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )

    netting_sets = make_ccr_p6_33_netting_sets()

    # Act
    result = compute_pfe(netting_sets).collect()
    row = result.filter(pl.col("netting_set_id") == CCR_P6_33_NETTING_SET_ID)

    assert row.height == 1, (
        f"Expected exactly 1 row for netting_set_id={CCR_P6_33_NETTING_SET_ID!r}, got {row.height}."
    )

    # Assert
    actual_ead = row["ead_ccr"][0]
    assert actual_ead == pytest.approx(CCR_P6_33_EXPECTED_EAD, abs=1e-2), (
        f"P6.33: ead_ccr expected ≈ {CCR_P6_33_EXPECTED_EAD:,.3f}, "
        f"got {actual_ead!r}. "
        "CRR Art. 274(2): EAD = 1.4 × (RC + PFE) = 1.4 × (150_000 + 7_830_986.18). "
        "The RC term must be non-zero when V − C > 0."
    )


# ===========================================================================
# 3. Delegation-equivalence — regression pin (PASS today).
# ===========================================================================


def test_p6_33_rc_unmargined_equals_canonical_compute_rc_unmargined() -> None:
    """rc_unmargined from compute_pfe must equal compute_rc_unmargined element-wise.

    This regression pin locks the invariance: after the Wave-4 refactor that
    makes compute_pfe call compute_rc_unmargined internally, numeric outputs
    for rc_unmargined must be identical.  The test passes both before and after
    the refactor — it can never regress to a different value.

    Arrange:
        NS-P6.33-01 frame from make_ccr_p6_33_netting_sets().

    Act:
        a) compute_pfe(frame, config).collect()["rc_unmargined"]
        b) compute_rc_unmargined(frame).collect()["rc_unmargined"]

    Assert:
        Column (a) equals column (b) element-wise (exact float equality).

    References:
        CRR Art. 275(1) — both functions implement max(V_net − C_net, 0).
    """
    # Arrange
    if compute_pfe is None:
        pytest.fail(
            "compute_pfe is not importable from rwa_calc.engine.ccr.pfe — "
            "function not yet implemented."
        )
    if compute_rc_unmargined is None:
        pytest.fail(
            "compute_rc_unmargined is not importable from rwa_calc.engine.ccr.rc — "
            "canonical function missing (prerequisite for P6.33 delegation)."
        )

    netting_sets = make_ccr_p6_33_netting_sets()

    # Act
    pfe_result = compute_pfe(netting_sets).collect()
    rc_result = compute_rc_unmargined(netting_sets).collect()

    pfe_rc_col = pfe_result["rc_unmargined"]
    canonical_rc_col = rc_result["rc_unmargined"]

    # Assert — element-wise exact equality (both implement the same floor formula)
    assert pfe_rc_col.to_list() == canonical_rc_col.to_list(), (
        "rc_unmargined produced by compute_pfe must equal compute_rc_unmargined "
        "element-wise. "
        f"compute_pfe gave: {pfe_rc_col.to_list()!r}, "
        f"compute_rc_unmargined gave: {canonical_rc_col.to_list()!r}. "
        "CRR Art. 275(1): RC = max(V_net − C_net, 0) is the canonical formula; "
        "both paths must produce identical results."
    )
