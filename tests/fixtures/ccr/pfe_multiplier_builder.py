"""
P8.16 fixture builder: SA-CCR PFE multiplier (under-collateralised netting set).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_p8_16_pfe_multiplier.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/pfe.py::compute_pfe)

Scenario design:
    Single netting set NS-CCR-A2-01 (counterparty CP-CCR-A2), unmargined, legally
    enforceable (Art. 295).  The netting set carries:

        v_net  = -2_000_000.0   (bank owes counterparty — in-the-money to CP)
        c_net  = +500_000.0     (counterparty has posted GBP 500k cash)

    so V − C = -2_500_000, which drives the multiplier strictly below 1.

    Rather than re-deriving add-on from trades (that is P8.10/P8.15 scope),
    the builder injects ``addon_aggregate = 7_830_986.18`` directly on the
    netting-set-grain LazyFrame.  This matches the scenario-architect hand-calc
    (two 100M GBP 10y IR swaps in GT_5Y bucket, both delta=+1, same hedging set).

    A second sub-test frame (scenario B) provides v_net = +3_000_000 / c_net =
    +500_000, so V − C = +2_500_000.  The uncapped multiplier evaluates to
    ≈ 1.174, so min(1, 1.174) = 1.0.  This guards against future regressions
    that drop the ``min(1, ...)`` cap.

Hand calculation — Scenario A (under-collateralised, Art. 278(3)):
    F      = 0.05
    1 − F  = 0.95
    addon  = 7_830_986.18
    denom  = 2 × 0.95 × 7_830_986.18 = 14_878_873.742
    V − C  = -2_500_000
    exp_arg = -2_500_000 / 14_878_873.742 ≈ -0.168023470
    exp_val ≈ 0.845333994
    mul   = 0.05 + 0.95 × 0.845333994 ≈ 0.853067295
    PFE addon = 0.853067295 × 7_830_986.18 ≈ 6_680_358.19
    RC    = max(-2_500_000, 0) = 0.00  (Art. 275(1))
    EAD   = 1.4 × (0 + 6_680_358.19) ≈ 9_352_501.47  (Art. 274(2))
    Note: the scenario-architect proposal used ≈ 0.853064362 with slightly rounded
    intermediate steps; the exact float result 0.8530672945143725 is used here.

Hand calculation — Scenario B (over-collateralised cap):
    V − C  = +2_500_000
    exp_arg ≈ +0.168022847
    uncapped multiplier ≈ 1.174
    multiplier = min(1, 1.174) = 1.0

Module constants are the single source of truth for test-writer assertions.

This module is Python-only: no parquet files are written.  The test-writer
imports the ``make_*`` LazyFrame factories directly.

Exported public names
---------------------
    CCR_A2_NETTING_SET_ID         : str   — "NS-CCR-A2-01"
    CCR_A2_COUNTERPARTY_REF       : str   — "CP-CCR-A2"
    CCR_A2_V_NET                  : float — -2_000_000.0
    CCR_A2_C_NET                  : float — +500_000.0
    CCR_A2_V_MINUS_C              : float — -2_500_000.0
    CCR_A2_ADDON_AGGREGATE        : float — 7_830_986.18
    CCR_A2_EXPECTED_MULTIPLIER    : float — 0.853064362  (Scenario A)
    CCR_A2_EXPECTED_PFE_ADDON     : float — 6_680_855.91
    CCR_A2_EXPECTED_RC            : float — 0.00
    CCR_A2_EXPECTED_EAD           : float — 9_353_198.27

    CCR_A2B_V_NET                 : float — +3_000_000.0
    CCR_A2B_C_NET                 : float — +500_000.0
    CCR_A2B_EXPECTED_MULTIPLIER   : float — 1.0  (capped, Scenario B)
    CCR_A2B_EXPECTED_PFE_ADDON    : float — 7_830_986.18  (= addon × 1.0)

    make_ccr_a2_netting_sets()     -> pl.LazyFrame  (1 row, Scenario A)
    make_ccr_a2b_netting_sets()    -> pl.LazyFrame  (1 row, Scenario B cap sub-test)
    save_pfe_multiplier_fixtures() -> list[tuple[str, int]]  (smoke-check)

References:
    - CRR Art. 274(2) — EAD = α × (RC + PFE), α = 1.4
    - CRR Art. 275(1) — RC_unmargined = max(V_net − C_net, 0)
    - CRR Art. 278(1) — PFE = multiplier × AddOn_aggregate
    - CRR Art. 278(2) — AddOn_aggregate = sum over asset classes of AddOn(a)
    - CRR Art. 278(3) — PFE multiplier formula and F = 0.05 floor
    - BCBS CRE52.20-23 — multiplier definition, V−C semantics, F floor
    - src/rwa_calc/data/tables/sa_ccr_factors.py — PFE_MULTIPLIER_FLOOR_F = 0.05
    - src/rwa_calc/engine/ccr/pfe.py — compute_pfe (new function, P8.16)
"""

from __future__ import annotations

import math

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import NETTING_SET_SCHEMA

from .netting_set_builder import NettingSet, create_netting_sets

# ---------------------------------------------------------------------------
# Scenario A constants — single source of truth for test-writer assertions.
# Under-collateralised: V − C < 0 → multiplier < 1 (load-bearing case).
# ---------------------------------------------------------------------------

CCR_A2_NETTING_SET_ID: str = "NS-CCR-A2-01"
CCR_A2_COUNTERPARTY_REF: str = "CP-CCR-A2"

# Netting-set MtM and collateral (post-haircut) values, GBP.
# CRR Art. 275(1): RC = max(V_net − C_net, 0).
CCR_A2_V_NET: float = -2_000_000.0  # bank owes counterparty
CCR_A2_C_NET: float = 500_000.0  # counterparty has posted GBP 500k

# V − C drives the multiplier exponent (Art. 278(3)).
CCR_A2_V_MINUS_C: float = CCR_A2_V_NET - CCR_A2_C_NET  # = -2_500_000.0

# AddOn_aggregate injected directly (P8.10/P8.15 scope; see module docstring).
# Derived from two 100M GBP 10y IR swaps, same GT_5Y hedging-set bucket:
#   D_B3 = 2 × (+1) × 783_098_618 × 1.0 = 1_566_197_236
#   AddOn_IR = 0.005 × 1_566_197_236 = 7_830_986.18
CCR_A2_ADDON_AGGREGATE: float = 7_830_986.18

# PFE multiplier (Art. 278(3)) — exact Python computation:
# F = 0.05, 1-F = 0.95, denom = 2 × 0.95 × 7_830_986.18 = 14_878_873.742
# exp_arg = -2_500_000 / 14_878_873.742 ≈ -0.168023470
# multiplier = 0.05 + 0.95 × exp(-0.168023470) ≈ 0.853067295
# Note: the scenario-architect proposal used slightly rounded intermediate values
# (exp_arg = -0.168022847) that differ from direct float computation at the 7th
# significant figure.  The exact float result is used here; the accepted tolerance
# in tests is abs=1e-6 for the multiplier, which this satisfies.
CCR_A2_EXPECTED_MULTIPLIER: float = 0.8530672945143725

# pfe_addon = multiplier × addon_aggregate (Art. 278(1))
CCR_A2_EXPECTED_PFE_ADDON: float = CCR_A2_EXPECTED_MULTIPLIER * CCR_A2_ADDON_AGGREGATE

# RC = max(V - C, 0) = max(-2_500_000, 0) = 0.00 (Art. 275(1))
CCR_A2_EXPECTED_RC: float = 0.0

# EAD = α × (RC + PFE) = 1.4 × (0 + pfe_addon) (Art. 274(2))
_ALPHA: float = 1.4
CCR_A2_EXPECTED_EAD: float = _ALPHA * (CCR_A2_EXPECTED_RC + CCR_A2_EXPECTED_PFE_ADDON)

# ---------------------------------------------------------------------------
# Scenario B constants — over-collateralised cap sub-test.
# V − C > 0 → uncapped multiplier > 1 → min(1, ...) = 1.0.
# ---------------------------------------------------------------------------

CCR_A2B_NETTING_SET_ID: str = "NS-CCR-A2-02"

CCR_A2B_V_NET: float = 3_000_000.0  # bank is in-the-money
CCR_A2B_C_NET: float = 500_000.0  # same collateral

CCR_A2B_V_MINUS_C: float = CCR_A2B_V_NET - CCR_A2B_C_NET  # = +2_500_000.0

# multiplier = min(1, 0.05 + 0.95 × exp(+2_500_000 / 14_878_873.742)) = 1.0 (capped)
CCR_A2B_EXPECTED_MULTIPLIER: float = 1.0

# pfe_addon = 1.0 × 7_830_986.18 = 7_830_986.18
CCR_A2B_EXPECTED_PFE_ADDON: float = CCR_A2B_EXPECTED_MULTIPLIER * CCR_A2_ADDON_AGGREGATE


# ---------------------------------------------------------------------------
# Verification: confirm module constants are internally consistent.
# ---------------------------------------------------------------------------


def _verify_hand_calc() -> None:
    """Cross-check module constants against direct Python computation.

    Raises:
        AssertionError: If any module constant deviates by more than the
            documented tolerance from the direct Python calculation.
    """
    f = 0.05
    one_minus_f = 1.0 - f
    denom = 2.0 * one_minus_f * CCR_A2_ADDON_AGGREGATE

    # Scenario A
    exp_a = math.exp(CCR_A2_V_MINUS_C / denom)
    mul_a = min(1.0, f + one_minus_f * exp_a)
    assert abs(mul_a - CCR_A2_EXPECTED_MULTIPLIER) < 1e-6, (
        f"Scenario A multiplier mismatch: computed {mul_a}, constant {CCR_A2_EXPECTED_MULTIPLIER}"
    )
    assert mul_a < 1.0, "Scenario A multiplier must be < 1.0 (under-collateralised)"

    pfe_a = mul_a * CCR_A2_ADDON_AGGREGATE
    assert abs(pfe_a - CCR_A2_EXPECTED_PFE_ADDON) < 1e-2, (
        f"Scenario A pfe_addon mismatch: computed {pfe_a}, constant {CCR_A2_EXPECTED_PFE_ADDON}"
    )

    rc_a = max(CCR_A2_V_MINUS_C, 0.0)
    assert rc_a == CCR_A2_EXPECTED_RC, (
        f"Scenario A RC mismatch: computed {rc_a}, constant {CCR_A2_EXPECTED_RC}"
    )

    ead_a = _ALPHA * (rc_a + pfe_a)
    assert abs(ead_a - CCR_A2_EXPECTED_EAD) < 1e-2, (
        f"Scenario A EAD mismatch: computed {ead_a}, constant {CCR_A2_EXPECTED_EAD}"
    )

    # Scenario B
    exp_b = math.exp(CCR_A2B_V_MINUS_C / denom)
    mul_b = min(1.0, f + one_minus_f * exp_b)
    assert mul_b == CCR_A2B_EXPECTED_MULTIPLIER, (
        f"Scenario B multiplier must be 1.0 (capped); got {mul_b}"
    )
    assert mul_b == 1.0, "Scenario B multiplier must equal 1.0 (cap test)"


# Run at import time so any constant mis-transcription surfaces immediately.
_verify_hand_calc()


# ---------------------------------------------------------------------------
# Netting-set row helpers
# ---------------------------------------------------------------------------


def _scenario_a_netting_set() -> NettingSet:
    """Return the Scenario A netting-set (under-collateralised, V−C < 0)."""
    return NettingSet(
        netting_set_id=CCR_A2_NETTING_SET_ID,
        counterparty_reference=CCR_A2_COUNTERPARTY_REF,
        is_legally_enforceable=True,
        is_margined=False,
    )


def _scenario_b_netting_set() -> NettingSet:
    """Return the Scenario B netting-set (over-collateralised cap sub-test)."""
    return NettingSet(
        netting_set_id=CCR_A2B_NETTING_SET_ID,
        counterparty_reference=CCR_A2_COUNTERPARTY_REF,
        is_legally_enforceable=True,
        is_margined=False,
    )


# ---------------------------------------------------------------------------
# Public LazyFrame factories
# ---------------------------------------------------------------------------


def make_ccr_a2_netting_sets() -> pl.LazyFrame:
    """
    Return a 1-row netting-set LazyFrame for the Scenario A (under-collateralised).

    The frame matches ``NETTING_SET_SCHEMA`` exactly.  Two additional columns
    (``v_net``, ``c_net``) carry the MtM and collateral values required by
    ``compute_pfe``; ``addon_aggregate`` is also pre-populated so the function
    under test does not need to re-derive it from trade-level detail.

    Returns:
        LazyFrame with 1 row and the NETTING_SET_SCHEMA columns plus
        ``v_net``, ``c_net``, ``addon_aggregate``.
    """
    base = create_netting_sets([_scenario_a_netting_set()])
    return base.with_columns(
        [
            pl.lit(CCR_A2_V_NET).alias("v_net"),
            pl.lit(CCR_A2_C_NET).alias("c_net"),
            pl.lit(CCR_A2_ADDON_AGGREGATE).alias("addon_aggregate"),
        ]
    ).lazy()


def make_ccr_a2b_netting_sets() -> pl.LazyFrame:
    """
    Return a 1-row netting-set LazyFrame for the Scenario B (cap sub-test).

    Same structure as ``make_ccr_a2_netting_sets()`` but with
    ``v_net = +3_000_000`` so V − C = +2_500_000 and the multiplier
    is capped at 1.0.

    Returns:
        LazyFrame with 1 row and the NETTING_SET_SCHEMA columns plus
        ``v_net``, ``c_net``, ``addon_aggregate``.
    """
    base = create_netting_sets([_scenario_b_netting_set()])
    return base.with_columns(
        [
            pl.lit(CCR_A2B_V_NET).alias("v_net"),
            pl.lit(CCR_A2B_C_NET).alias("c_net"),
            pl.lit(CCR_A2_ADDON_AGGREGATE).alias("addon_aggregate"),
        ]
    ).lazy()


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py
# ---------------------------------------------------------------------------


def save_pfe_multiplier_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check both P8.16 LazyFrames and return a generation report.

    No parquet files are written — this fixture is Python-only.  The function
    validates the invariants listed in the module docstring and raises
    ``AssertionError`` with a descriptive message if any is violated.

    Returns:
        A single-element list suitable for ``generate_all.py``'s report format:
        ``[("(python-only builder — no parquet)", 0)]``.

    Raises:
        AssertionError: If any schema or data invariant is violated.
    """
    ns_a = make_ccr_a2_netting_sets().collect()
    ns_b = make_ccr_a2b_netting_sets().collect()

    # Invariant 1: each frame has exactly 1 row.
    if ns_a.height != 1:
        raise AssertionError(f"Scenario A: expected 1 netting-set row, got {ns_a.height}")
    if ns_b.height != 1:
        raise AssertionError(f"Scenario B: expected 1 netting-set row, got {ns_b.height}")

    # Invariant 2: netting_set_id is correct on each scenario.
    if ns_a["netting_set_id"][0] != CCR_A2_NETTING_SET_ID:
        raise AssertionError(
            f"Scenario A: netting_set_id must be {CCR_A2_NETTING_SET_ID!r} "
            f"(got {ns_a['netting_set_id'][0]!r})"
        )
    if ns_b["netting_set_id"][0] != CCR_A2B_NETTING_SET_ID:
        raise AssertionError(
            f"Scenario B: netting_set_id must be {CCR_A2B_NETTING_SET_ID!r} "
            f"(got {ns_b['netting_set_id'][0]!r})"
        )

    # Invariant 3: v_net and c_net are propagated correctly.
    if ns_a["v_net"][0] != CCR_A2_V_NET:
        raise AssertionError(f"Scenario A: v_net must be {CCR_A2_V_NET} (got {ns_a['v_net'][0]})")
    if ns_a["c_net"][0] != CCR_A2_C_NET:
        raise AssertionError(f"Scenario A: c_net must be {CCR_A2_C_NET} (got {ns_a['c_net'][0]})")
    if ns_b["v_net"][0] != CCR_A2B_V_NET:
        raise AssertionError(f"Scenario B: v_net must be {CCR_A2B_V_NET} (got {ns_b['v_net'][0]})")

    # Invariant 4: V − C < 0 for Scenario A (the load-bearing under-coll. check).
    v_minus_c_a = ns_a["v_net"][0] - ns_a["c_net"][0]
    if v_minus_c_a >= 0.0:
        raise AssertionError(
            f"Scenario A: V − C must be negative (under-collateralised); got {v_minus_c_a}"
        )

    # Invariant 5: addon_aggregate is present and has the correct value.
    if abs(ns_a["addon_aggregate"][0] - CCR_A2_ADDON_AGGREGATE) > 1e-2:
        raise AssertionError(
            f"Scenario A: addon_aggregate must be {CCR_A2_ADDON_AGGREGATE} "
            f"(got {ns_a['addon_aggregate'][0]})"
        )

    # Invariant 6: expected multiplier is < 1.0 (anti-degenerate CCR-A1 check).
    if CCR_A2_EXPECTED_MULTIPLIER >= 1.0:
        raise AssertionError(
            f"Scenario A: expected multiplier must be < 1.0 (got {CCR_A2_EXPECTED_MULTIPLIER})"
        )

    # Invariant 7: Scenario B expected multiplier == 1.0 (cap guard).
    if CCR_A2B_EXPECTED_MULTIPLIER != 1.0:
        raise AssertionError(
            f"Scenario B: expected multiplier must be 1.0 (capped); "
            f"got {CCR_A2B_EXPECTED_MULTIPLIER}"
        )

    # Invariant 8: both frames share the same counterparty reference.
    if ns_a["counterparty_reference"][0] != CCR_A2_COUNTERPARTY_REF:
        raise AssertionError(
            f"Scenario A: counterparty_reference must be {CCR_A2_COUNTERPARTY_REF!r}"
        )
    if ns_b["counterparty_reference"][0] != CCR_A2_COUNTERPARTY_REF:
        raise AssertionError(
            f"Scenario B: counterparty_reference must be {CCR_A2_COUNTERPARTY_REF!r}"
        )

    # Invariant 9: both frames are unmargined and legally enforceable.
    for label, df in (("A", ns_a), ("B", ns_b)):
        if df["is_margined"][0] is not False:
            raise AssertionError(f"Scenario {label}: is_margined must be False")
        if df["is_legally_enforceable"][0] is not True:
            raise AssertionError(f"Scenario {label}: is_legally_enforceable must be True")

    # Invariant 10: NETTING_SET_SCHEMA columns are all present (schema integrity).
    required_cols = set(dtypes_of(NETTING_SET_SCHEMA).keys())
    for label, df in (("A", ns_a), ("B", ns_b)):
        missing = required_cols - set(df.columns)
        if missing:
            raise AssertionError(
                f"Scenario {label}: missing NETTING_SET_SCHEMA columns: {sorted(missing)}"
            )

    return [("(python-only builder — no parquet)", 0)]
