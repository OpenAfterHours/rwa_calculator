"""
Unit tests for compute_supervisory_delta_option and compute_supervisory_delta_cdo_tranche
(P8.13 option-delta sub-piece).

Pins the expected behaviour of the Black-Scholes Φ(d1) supervisory delta for
European options (CRR Art. 279a(2)) and the CDO-tranche supervisory delta
(CRR Art. 279a(3)) on the seven-row fixture produced by option_delta_builder.

Formula references
------------------
Option delta (Art. 279a(2)):

    For a call:  δ = +Φ(d1)   (long)   or  δ = −Φ(d1)   (short)
    For a put:   δ = −Φ(−d1)  (long)   or  δ = +Φ(−d1)  (short)

    where d1 = (ln(P/K) + 0.5 · σ² · T) / (σ · √T)

    σ is the asset-class supervisory volatility per BCBS CRE52.47:
        interest_rate  → 0.50
        equity         → 0.75
        fx             → 0.15

    T = (maturity_date − reporting_date).days / 365

CDO-tranche delta (Art. 279a(3) / BCBS CRE52.43):

    δ = ±15 / ((1 + 14·A) · (1 + 14·D))

    long tranche → positive; short tranche → negative.

Expected values below are derived from the fixture data in
``tests/fixtures/ccr/option_delta_builder.py`` with reporting_date = START_DATE
(2026-01-15), so T is exact calendar days / 365.

References:
    - CRR Art. 279a(2): Black-Scholes supervisory delta for European options
    - CRR Art. 279a(3): CDO-tranche supervisory delta
    - BCBS CRE52.42–43: option and CDO-tranche delta formulas
    - BCBS CRE52.47: supervisory option volatility table
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.ccr.option_delta_builder import (
    make_cdo_trades_only,
    make_linear_trade,
    make_option_trades_only,
)

# ---------------------------------------------------------------------------
# Guarded import — surfaces as AssertionError at test-run time, not ImportError
# at collection time, so the engine-implementer sees a clean assertion failure.
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_option
except (ImportError, ModuleNotFoundError):
    compute_supervisory_delta_option = None  # type: ignore[assignment]

try:
    from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_cdo_tranche
except (ImportError, ModuleNotFoundError):
    compute_supervisory_delta_cdo_tranche = None  # type: ignore[assignment]


# ===========================================================================
# Helper
# ===========================================================================


def _assert_function_available(fn: object, name: str) -> None:
    """Fail with a clear AssertionError if the function was not importable."""
    assert fn is not None, (
        f"Cannot import {name!r} from rwa_calc.engine.ccr.supervisory_delta. "
        "P8.13 option-delta sub-piece not yet implemented."
    )


# ===========================================================================
# 1. ATM long IR call — OPT_001
#    T=1.0y exactly (365 days), σ=0.50, P=K=0.03, long call → +Φ(d1)
#    d1 = (ln(1) + 0.5·0.50²·1.0) / (0.50·1.0) = 0.25
#    expected δ ≈ +0.598706
# ===========================================================================


def test_atm_long_ir_call_delta_phi_d1() -> None:
    """ATM long IR call returns +Φ(d1) ≈ +0.598706 per Art. 279a(2).

    Arrange:
        OPT_001: IR, long call, P=K=0.03 (ATM), T=1.0y, σ=0.50.
        d1 = (ln(P/K) + 0.5·σ²·T) / (σ·√T) = 0.25
        Expected: +Φ(0.25) ≈ 0.598706.

    Act: compute_supervisory_delta_option(option_trades).collect()

    Assert: supervisory_delta[OPT_001] ≈ +0.598706 (abs=1e-4).

    References: CRR Art. 279a(2); BCBS CRE52.42.
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_option_trades_only()

    # Act
    result = compute_supervisory_delta_option(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "OPT_001")
    assert len(row) == 1, "OPT_001 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(0.598706, abs=1e-4), (
        f"OPT_001 ATM long IR call: expected supervisory_delta≈+0.598706 "
        f"(Φ(d1=0.25), Art. 279a(2)), got {actual!r}."
    )


# ===========================================================================
# 2. ATM long IR put — OPT_002
#    Same T and σ as OPT_001, long put → −Φ(−d1)
#    −Φ(−0.25) = −(1 − Φ(0.25)) ≈ −0.401294
# ===========================================================================


def test_atm_long_ir_put_delta_neg_phi_neg_d1() -> None:
    """ATM long IR put returns −Φ(−d1) ≈ −0.401294 per Art. 279a(2).

    Arrange:
        OPT_002: IR, long put, P=K=0.03 (ATM), T=1.0y, σ=0.50.
        d1 = 0.25, long put → −Φ(−0.25) ≈ −0.401294.

    Act: compute_supervisory_delta_option(option_trades).collect()

    Assert: supervisory_delta[OPT_002] ≈ −0.401294 (abs=1e-4).

    References: CRR Art. 279a(2); BCBS CRE52.42.
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_option_trades_only()

    # Act
    result = compute_supervisory_delta_option(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "OPT_002")
    assert len(row) == 1, "OPT_002 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(-0.401294, abs=1e-4), (
        f"OPT_002 ATM long IR put: expected supervisory_delta≈−0.401294 "
        f"(−Φ(−d1=−0.25), Art. 279a(2)), got {actual!r}."
    )


# ===========================================================================
# 3. OTM short equity call — OPT_003
#    T=91/365≈0.2493y, σ=0.75, P=100, K=110 (OTM), short call → −Φ(d1)
#    d1 = (ln(100/110) + 0.5·0.75²·0.2493) / (0.75·√0.2493) ≈ −0.0673
#    expected δ ≈ −0.47318
# ===========================================================================


def test_otm_short_equity_index_call_delta() -> None:
    """OTM short equity call returns −Φ(d1) ≈ −0.47318 per Art. 279a(2).

    Arrange:
        OPT_003: equity, short call, P=100, K=110, T=91/365y, σ=0.75.
        d1 ≈ −0.0673, short call → −Φ(d1) ≈ −0.47318.

    Act: compute_supervisory_delta_option(option_trades).collect()

    Assert: supervisory_delta[OPT_003] ≈ −0.47318 (abs=1e-4).

    References: CRR Art. 279a(2); BCBS CRE52.42; CRE52.47 (σ=0.75 for equity).
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_option_trades_only()

    # Act
    result = compute_supervisory_delta_option(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "OPT_003")
    assert len(row) == 1, "OPT_003 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(-0.47318, abs=1e-4), (
        f"OPT_003 OTM short equity call: expected supervisory_delta≈−0.47318 "
        f"(−Φ(d1≈−0.0673), short call, Art. 279a(2)), got {actual!r}."
    )


# ===========================================================================
# 4. ITM long FX put — OPT_004
#    T=182/365≈0.4986y, σ=0.15, P=1.20, K=1.30 (ITM put), long put → −Φ(−d1)
#    d1 ≈ −0.7027, −Φ(−d1) = −Φ(0.7027) ≈ −0.75889
# ===========================================================================


def test_itm_long_fx_put_delta() -> None:
    """ITM long FX put returns −Φ(−d1) ≈ −0.75889 per Art. 279a(2).

    Arrange:
        OPT_004: FX, long put, P=1.20, K=1.30, T=182/365y, σ=0.15.
        d1 ≈ −0.7027, long put → −Φ(−d1) ≈ −0.75889.

    Act: compute_supervisory_delta_option(option_trades).collect()

    Assert: supervisory_delta[OPT_004] ≈ −0.75889 (abs=1e-4).

    References: CRR Art. 279a(2); BCBS CRE52.42; CRE52.47 (σ=0.15 for FX).
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_option_trades_only()

    # Act
    result = compute_supervisory_delta_option(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "OPT_004")
    assert len(row) == 1, "OPT_004 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(-0.75889, abs=1e-4), (
        f"OPT_004 ITM long FX put: expected supervisory_delta≈−0.75889 "
        f"(−Φ(−d1≈−0.7027), long put, Art. 279a(2)), got {actual!r}."
    )


# ===========================================================================
# 5. Linear branch preserved after extension — LIN_001
#    A linear (non-option, non-CDO) long IR swap must still emit +1.0.
#    Tests that the new option-delta extension does not break the existing
#    compute_supervisory_delta_linear logic.
# ===========================================================================


def test_linear_branch_preserved_after_extension() -> None:
    """Linear IR swap (no option_type) must retain supervisory_delta = +1.0.

    Passing a linear trade through compute_supervisory_delta_option must not
    corrupt the ±1.0 delta emitted by the linear branch.  This guards against
    an implementation that unconditionally overwrites all rows.

    Arrange:
        LIN_001: IR swap, is_long=True, option_type=null, no cdo fields.

    Act: compute_supervisory_delta_option(linear_trade).collect()

    Assert: supervisory_delta == +1.0.

    References: CRR Art. 279a(1) (linear instruments).
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_linear_trade()

    # Act
    result = compute_supervisory_delta_option(lf).collect()

    # Assert
    actual = result["supervisory_delta"][0]
    assert actual == pytest.approx(1.0, abs=1e-8), (
        f"LIN_001 linear IR swap: expected supervisory_delta=+1.0 "
        f"(Art. 279a(1), option_type=null branch), got {actual!r}."
    )


# ===========================================================================
# 6. CDO long tranche — CDO_001
#    A=0.03, D=0.07, long tranche → +15 / ((1+14·A)·(1+14·D))
#    = 15 / (1.42 · 1.98) = 15 / 2.8116 ≈ +5.335041 (Art. 279a(3) / BCBS CRE52.43)
# ===========================================================================


def test_cdo_long_tranche_delta() -> None:
    """CDO long tranche returns +15 / ((1+14·A)·(1+14·D)) ≈ +5.335041.

    Arrange:
        CDO_001: credit, long tranche, A=0.03, D=0.07.
        Formula (CRR Art. 279a(3) / BCBS CRE52.43):
            δ = ±15 / ((1 + 14·A) · (1 + 14·D))
        (1 + 14·0.03) = 1.42; (1 + 14·0.07) = 1.98
        product = 2.8116; δ = 15 / 2.8116 ≈ +5.335041 (long → positive).

    Act: compute_supervisory_delta_cdo_tranche(cdo_trades).collect()

    Assert: supervisory_delta[CDO_001] ≈ +5.335041 (abs=1e-4).

    References: CRR Art. 279a(3); BCBS CRE52.43.
    """
    # Arrange
    _assert_function_available(
        compute_supervisory_delta_cdo_tranche, "compute_supervisory_delta_cdo_tranche"
    )
    lf = make_cdo_trades_only()

    # Act
    result = compute_supervisory_delta_cdo_tranche(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "CDO_001")
    assert len(row) == 1, "CDO_001 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(5.335041, abs=1e-4), (
        f"CDO_001 long tranche: expected supervisory_delta≈+5.335041 "
        f"(δ=+15/((1+14·A)·(1+14·D)), A=0.03, D=0.07, Art. 279a(3) / BCBS CRE52.43), "
        f"got {actual!r}."
    )


# ===========================================================================
# 7. CDO short tranche — CDO_002
#    A=0.03, D=0.07, short tranche → −15 / ((1+14·A)·(1+14·D)) ≈ −5.335041
# ===========================================================================


def test_cdo_short_tranche_delta() -> None:
    """CDO short tranche returns −15 / ((1+14·A)·(1+14·D)) ≈ −5.335041.

    Arrange:
        CDO_002: credit, short tranche, A=0.03, D=0.07.
        Formula (CRR Art. 279a(3) / BCBS CRE52.43):
            δ = ±15 / ((1 + 14·A) · (1 + 14·D))
        (1 + 14·0.03) = 1.42; (1 + 14·0.07) = 1.98
        product = 2.8116; δ = −15 / 2.8116 ≈ −5.335041 (short → negative).

    Act: compute_supervisory_delta_cdo_tranche(cdo_trades).collect()

    Assert: supervisory_delta[CDO_002] ≈ −5.335041 (abs=1e-4).

    References: CRR Art. 279a(3); BCBS CRE52.43.
    """
    # Arrange
    _assert_function_available(
        compute_supervisory_delta_cdo_tranche, "compute_supervisory_delta_cdo_tranche"
    )
    lf = make_cdo_trades_only()

    # Act
    result = compute_supervisory_delta_cdo_tranche(lf).collect()

    # Assert
    row = result.filter(pl.col("trade_id") == "CDO_002")
    assert len(row) == 1, "CDO_002 row missing from result"
    actual = row["supervisory_delta"][0]
    assert actual == pytest.approx(-5.335041, abs=1e-4), (
        f"CDO_002 short tranche: expected supervisory_delta≈−5.335041 "
        f"(δ=−15/((1+14·A)·(1+14·D)), A=0.03, D=0.07, Art. 279a(3) / BCBS CRE52.43), "
        f"got {actual!r}."
    )


# ===========================================================================
# 8. Dtype guard — supervisory_delta column must be Float64
# ===========================================================================


def test_supervisory_delta_dtype_float64() -> None:
    """compute_supervisory_delta_option must emit supervisory_delta as pl.Float64.

    A naive Polars expression that returns 1 (int literal) would resolve to
    Int64 — this test pins the dtype contract for the option branch.

    Arrange: 4-row option LazyFrame.

    Act: compute_supervisory_delta_option(option_trades).collect_schema()

    Assert: supervisory_delta dtype == pl.Float64.

    References: CRR Art. 279a(2).
    """
    # Arrange
    _assert_function_available(compute_supervisory_delta_option, "compute_supervisory_delta_option")
    lf = make_option_trades_only()

    # Act
    result_lf = compute_supervisory_delta_option(lf)
    schema = result_lf.collect_schema()

    # Assert
    assert "supervisory_delta" in schema, (
        f"'supervisory_delta' column absent from schema. Got columns: {list(schema.names())}"
    )
    assert schema["supervisory_delta"] == pl.Float64, (
        f"'supervisory_delta' must be pl.Float64, got {schema['supervisory_delta']}. "
        "Use pl.lit(value, dtype=pl.Float64) or .cast(pl.Float64) in the expression."
    )
