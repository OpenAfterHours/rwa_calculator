"""
Unit tests for compute_maturity_factor_margined (P8.14 — margined sub-piece).

Pins the expected behaviour of the margined MF formula per CRR Art. 279c(2):

    MF = (3/2) × sqrt(MPOR_eff / 250)

where MPOR_eff is derived by the Art. 285 cascade:

    Step 1 — base:     5  if ALL trades in NS are SFT/repo else 10
    Step 2 — upgrade:  20 if number_of_trades > 5000
                          OR has_illiquid_collateral_or_hard_to_replace_otc
    Step 3 — dispute:  base × 2 if dispute_count_qtr > 2  (Art. 285(4))
    Step 4 — freq adj: MPOR_eff = base + remargining_frequency_days − 1
    Step 5 — floor:    MPOR_eff = max(MPOR_eff, mpor_days_input)

References:
- CRR Art. 279c(2): MF = (3/2) × sqrt(MPOR_eff / 250)
- CRR Art. 285(2)(a): 5-BD MPOR floor for SFT / repo netting sets
- CRR Art. 285(2)(b): 10-BD MPOR floor for OTC derivative netting sets
- CRR Art. 285(3)(b): 20-BD floor for > 5000 trades or illiquid collateral
- CRR Art. 285(4): double MPOR_base when dispute_count_qtr > 2
- CRR Art. 285(5): MPOR_eff = base + remargining_frequency_days − 1
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.ccr.margined_mf_builder import (
    EXPECTED_MF,
    make_margined_mf_margin_agreements,
    make_margined_mf_netting_sets,
    make_margined_mf_trades,
)

# ---------------------------------------------------------------------------
# Subject under test — will be None until P8.14 (margined) is wired.
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_margined
except (ImportError, ModuleNotFoundError):
    compute_maturity_factor_margined = None  # ty: ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# Shared helper: build the denormalised trade LazyFrame
#
# ``compute_maturity_factor_margined`` is expected to accept a single
# denormalised LazyFrame that already contains the MPOR cascade inputs
# alongside the trade columns.  The test joins the three fixture tables
# on their natural keys to produce this frame.
# ---------------------------------------------------------------------------


def _build_denormalised_lf() -> pl.LazyFrame:
    """
    Join trades × netting_sets × margin_agreements on their natural keys.

    The resulting frame has one row per trade and carries every column that
    the MPOR Art. 285 cascade needs:
        - transaction_type           (from trades)
        - mpor_days_input            (from netting_sets.mpor_days)
        - number_of_trades           (from netting_sets)
        - has_illiquid               (from netting_sets)
        - dispute_count_qtr          (from margin_agreements)
        - remargining_frequency_days (from margin_agreements)
    """
    trades_df = make_margined_mf_trades()
    ns_df = make_margined_mf_netting_sets()
    ma_df = make_margined_mf_margin_agreements()

    # Build the denormalised frame eagerly so join errors surface immediately,
    # then wrap as LazyFrame for the function under test.
    merged = trades_df.join(
        ns_df.select(
            [
                "netting_set_id",
                pl.col("mpor_days").alias("mpor_days_input"),
                "number_of_trades",
                pl.col("has_illiquid_collateral_or_hard_to_replace_otc").alias("has_illiquid"),
                "margin_agreement_id",
                # is_margined=True for all P8.14 rows (all netting sets are margined).
                # P8.54 adds an internal is_margined gate to compute_maturity_factor_margined
                # so the column must be present in the denormalised frame. Adding it now is
                # harmless on the current engine (extra column ignored) and is the only safe
                # ordering — the gate lands before the existing P8.14 unit tests run.
                "is_margined",
            ]
        ),
        on="netting_set_id",
        how="left",
    ).join(
        ma_df.select(
            [
                "margin_agreement_id",
                "remargining_frequency_days",
                "dispute_count_qtr",
            ]
        ),
        on="margin_agreement_id",
        how="left",
    )
    return merged.lazy()


# ===========================================================================
# 1. T1 — canonical OTC derivative, 10-day MPOR floor (BCBS CRE52.51-52)
# ===========================================================================


def test_t1_canonical_bcbs_cre52_otc_floor_10bd() -> None:
    """OTC derivative (T1): MPOR base=10 (OTC floor), MPOR_eff=max(10,5)=10.

    Arrange:
        T1 / NS1 — derivative, 10 trades, no illiquid collateral, 0 disputes,
        remargining_frequency_days=1, mpor_days_input=5.
        base = 10 (OTC, Art. 285(2)(b))
        MPOR_eff = base + 1 − 1 = 10, max(10, 5) = 10
        MF = 1.5 × sqrt(10 / 250) = 0.3 (exact).

    Act: compute_maturity_factor_margined(lf).collect().

    Assert: maturity_factor[T1] == 0.3 (abs=1e-12).

    References: CRR Art. 279c(2), Art. 285(2)(b), BCBS CRE52.51-52.
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "T1")
    actual = row["maturity_factor"][0]
    expected = EXPECTED_MF["T1"]  # 0.3
    assert actual == pytest.approx(expected, abs=1e-12), (
        f"T1 (OTC derivative, MPOR_eff=10): expected MF={expected!r}, got {actual!r}. "
        "CRR Art. 279c(2): MF = 1.5 × sqrt(10/250) = 0.3."
    )


# ===========================================================================
# 2. T2 — SFT netting set, 5-day MPOR floor (Art. 285(2)(a))
# ===========================================================================


def test_t2_sft_netting_set_floor_5bd() -> None:
    """SFT netting set (T2): MPOR base=5 (all trades are SFT, Art. 285(2)(a)).

    Arrange:
        T2 / NS2 — sft, 10 trades, no illiquid, 0 disputes,
        remargining_frequency_days=1, mpor_days_input=5.
        base = 5 (SFT, Art. 285(2)(a))
        MPOR_eff = base + 1 − 1 = 5, max(5, 5) = 5
        MF = 1.5 × sqrt(5 / 250) = 0.21213203435596426.

    Act: compute_maturity_factor_margined(lf).collect().

    Assert: maturity_factor[T2] ≈ 0.21213203435596426 (rel=1e-12).

    References: CRR Art. 279c(2), Art. 285(2)(a).
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "T2")
    actual = row["maturity_factor"][0]
    expected = EXPECTED_MF["T2"]  # 0.21213203435596426
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"T2 (SFT, MPOR_eff=5): expected MF={expected!r}, got {actual!r}. "
        "CRR Art. 279c(2): MF = 1.5 × sqrt(5/250). Art. 285(2)(a): SFT base=5."
    )


# ===========================================================================
# 3. T3 — large netting set (> 5000 trades), 20-day floor (Art. 285(3)(b))
# ===========================================================================


def test_t3_large_netting_set_floor_20bd() -> None:
    """Large NS (T3): number_of_trades=7000 triggers 20-BD MPOR floor.

    Arrange:
        T3 / NS3 — derivative, 7000 trades, no illiquid, 0 disputes,
        remargining_frequency_days=1, mpor_days_input=10.
        base = 10 (OTC, Art. 285(2)(b))
        Upgrade to 20 because number_of_trades 7000 > 5000 (Art. 285(3)(b))
        MPOR_eff = 20 + 1 − 1 = 20, max(20, 10) = 20
        MF = 1.5 × sqrt(20 / 250) = 0.42426406871192857.

    Act: compute_maturity_factor_margined(lf).collect().

    Assert: maturity_factor[T3] ≈ 0.42426406871192857 (rel=1e-12).

    References: CRR Art. 279c(2), Art. 285(3)(b).
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "T3")
    actual = row["maturity_factor"][0]
    expected = EXPECTED_MF["T3"]  # 0.42426406871192857
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"T3 (large NS, MPOR_eff=20): expected MF={expected!r}, got {actual!r}. "
        "CRR Art. 279c(2): MF = 1.5 × sqrt(20/250). Art. 285(3)(b): >5000 trades → 20BD."
    )


# ===========================================================================
# 4. T4 — dispute doubling (Art. 285(4)), resulting in 20-day MPOR_eff
# ===========================================================================


def test_t4_dispute_doubling_floor_20bd() -> None:
    """Dispute doubling (T4): dispute_count_qtr=3 > 2 doubles base 10 → 20.

    Arrange:
        T4 / NS4 — derivative, 10 trades, no illiquid, dispute_count_qtr=3,
        remargining_frequency_days=1, mpor_days_input=10.
        base = 10 (OTC, Art. 285(2)(b))
        dispute_count_qtr 3 > 2 → base = 2 × 10 = 20 (Art. 285(4))
        MPOR_eff = 20 + 1 − 1 = 20, max(20, 10) = 20
        MF = 1.5 × sqrt(20 / 250) = 0.42426406871192857.

    Act: compute_maturity_factor_margined(lf).collect().

    Assert: maturity_factor[T4] ≈ 0.42426406871192857 (rel=1e-12).

    References: CRR Art. 279c(2), Art. 285(4).
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "T4")
    actual = row["maturity_factor"][0]
    expected = EXPECTED_MF["T4"]  # 0.42426406871192857
    assert actual == pytest.approx(expected, rel=1e-12), (
        f"T4 (dispute doubling, MPOR_eff=20): expected MF={expected!r}, got {actual!r}. "
        "CRR Art. 279c(2): MF = 1.5 × sqrt(20/250). Art. 285(4): dispute_count_qtr 3>2 → 2×base."
    )


# ===========================================================================
# 5. maturity_factor column dtype must be Float64
# ===========================================================================


def test_maturity_factor_dtype_float64() -> None:
    """maturity_factor column must be Float64 (not Int32 / Float32 etc.).

    Arrange: full 4-row denormalised LazyFrame.

    Act: compute_maturity_factor_margined(lf).collect().

    Assert: result.schema["maturity_factor"] == pl.Float64.

    References: CLAUDE.md Polars conventions — Float64 for all regulatory
    scalars.
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf).collect()

    # Assert
    dtype = result.schema["maturity_factor"]
    assert dtype == pl.Float64, (
        f"maturity_factor column must be pl.Float64, got {dtype!r}. "
        "Use .cast(pl.Float64) in the implementation if needed."
    )


# ===========================================================================
# 6. Return type — must be LazyFrame (no eager collect inside the function)
# ===========================================================================


def test_returns_lazyframe() -> None:
    """compute_maturity_factor_margined must return pl.LazyFrame.

    Pipeline materialisation is the caller's responsibility per the project's
    LazyFrame-first convention. The function must not call .collect() internally.

    Arrange: full 4-row denormalised LazyFrame.

    Act: call compute_maturity_factor_margined without .collect().

    Assert: return value is pl.LazyFrame.
    """
    # Arrange
    if compute_maturity_factor_margined is None:
        pytest.fail(
            "compute_maturity_factor_margined not importable from "
            "rwa_calc.engine.ccr.maturity_factor — P8.14 (margined) not yet implemented."
        )

    lf = _build_denormalised_lf()

    # Act
    result = compute_maturity_factor_margined(lf)

    # Assert
    assert isinstance(result, pl.LazyFrame), (
        f"compute_maturity_factor_margined must return pl.LazyFrame, "
        f"got {type(result).__name__!r}. Never call .collect() inside the function."
    )
