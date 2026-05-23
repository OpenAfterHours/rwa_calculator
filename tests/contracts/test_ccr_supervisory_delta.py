"""Contract tests for compute_supervisory_delta_linear (P8.13).

Verifies that the linear ±1 supervisory delta sub-piece of Art. 279a(1)
produces the correct scalar output, preserves the pre-existing TRADE_SCHEMA
``delta`` column, operates on a LazyFrame, and returns Float64.

All six tests are expected to FAIL (AssertionError) until the engine-implementer
wave delivers the body in ``rwa_calc.engine.ccr.supervisory_delta``.

References:
    - CRR Art. 279a(1): Supervisory delta for linear instruments = +1 (long) / -1 (short)
"""

from __future__ import annotations

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Helper: guarded import — surfaces as AssertionError, not ImportError, at
# test run time so the engine-implementer sees a clean failure mode.
# ---------------------------------------------------------------------------


def _get_compute_supervisory_delta_linear():  # noqa: ANN201
    """Return compute_supervisory_delta_linear, or fail with a clear AssertionError."""
    try:
        from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_linear
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_supervisory_delta_linear from "
            f"rwa_calc.engine.ccr.supervisory_delta: {exc}. "
            "The module exists (P8.4 scaffold) but the import must succeed without error."
        )
    return compute_supervisory_delta_linear


# ===========================================================================
# 1. Long trade returns +1.0
# ===========================================================================


def test_supervisory_delta_long_row_returns_plus_one() -> None:
    """compute_supervisory_delta_linear must return supervisory_delta = +1.0 for is_long=True.

    CRR Art. 279a(1): delta = +1 for long positions in linear instruments.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001"],
            "is_long": [True],
            "delta": [1.0],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13 (CRR Art. 279a(1))."
        )

    actual = result.collect()["supervisory_delta"][0]

    # Assert
    assert actual == 1.0, (
        f"Expected supervisory_delta=1.0 for is_long=True (Art. 279a(1)), got {actual!r}."
    )


# ===========================================================================
# 2. Short trade returns -1.0
# ===========================================================================


def test_supervisory_delta_short_row_returns_minus_one() -> None:
    """compute_supervisory_delta_linear must return supervisory_delta = -1.0 for is_long=False.

    CRR Art. 279a(1): delta = -1 for short positions in linear instruments.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-002"],
            "is_long": [False],
            "delta": [1.0],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13 (CRR Art. 279a(1))."
        )

    actual = result.collect()["supervisory_delta"][0]

    # Assert
    assert actual == -1.0, (
        f"Expected supervisory_delta=-1.0 for is_long=False (Art. 279a(1)), got {actual!r}."
    )


# ===========================================================================
# 3. Output dtype is Float64 (guards against Int64 regression)
# ===========================================================================


def test_supervisory_delta_output_dtype_is_float64() -> None:
    """supervisory_delta column must be pl.Float64, not pl.Int64.

    A naive pl.when().then(1).otherwise(-1) expression resolves to Int64 in
    Polars — this test catches that regression.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001"],
            "is_long": [True],
            "delta": [1.0],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13."
        )

    schema = result.collect_schema()

    # Assert
    assert "supervisory_delta" in schema, (
        f"Result LazyFrame must contain 'supervisory_delta' column; "
        f"got schema keys: {list(schema.names())}"
    )
    assert schema["supervisory_delta"] == pl.Float64, (
        f"'supervisory_delta' must be pl.Float64 (not {schema['supervisory_delta']}). "
        "Use pl.lit(1.0) / pl.lit(-1.0) or an explicit .cast(pl.Float64) to avoid Int64."
    )


# ===========================================================================
# 4. Return type is LazyFrame (no-eager-collect contract)
# ===========================================================================


def test_supervisory_delta_returns_lazyframe() -> None:
    """compute_supervisory_delta_linear must return a pl.LazyFrame, not a DataFrame.

    Pipeline architecture rule: all engine functions operate on LazyFrames and
    must not materialise the plan internally.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-001"],
            "is_long": [True],
            "delta": [1.0],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13."
        )

    # Assert
    assert isinstance(result, pl.LazyFrame), (
        f"compute_supervisory_delta_linear must return pl.LazyFrame, "
        f"got {type(result).__name__!r}. Do not call .collect() inside the function."
    )


# ===========================================================================
# 5. Pre-existing delta column is preserved unchanged
# ===========================================================================


def test_supervisory_delta_preserves_existing_delta_column() -> None:
    """The pre-existing TRADE_SCHEMA 'delta' column must survive the function call.

    TRADE_SCHEMA line 670: 'delta' is an existing column (defaulting to 1.0).
    compute_supervisory_delta_linear must NOT overwrite or drop it — it writes
    a NEW 'supervisory_delta' column alongside the original.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    original_delta = 0.42  # non-default sentinel value
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-003"],
            "is_long": [True],
            "delta": [original_delta],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13."
        )

    df = result.collect()

    # Assert — 'delta' column still present
    assert "delta" in df.columns, (
        "The existing 'delta' column was dropped. "
        "compute_supervisory_delta_linear must add 'supervisory_delta' without removing 'delta'."
    )

    # Assert — original value is unchanged
    assert df["delta"][0] == original_delta, (
        f"'delta' column value changed: expected {original_delta!r}, got {df['delta'][0]!r}. "
        "compute_supervisory_delta_linear must not overwrite the existing 'delta' column."
    )


# ===========================================================================
# 6. Option row with option_strike returns linear placeholder (+1.0)
#    (deferred: option Φ(d1) sub-piece is out of scope for P8.13)
# ===========================================================================


def test_supervisory_delta_option_row_returns_linear_placeholder_pending_deferred_subpiece() -> (
    None
):
    """For a row with option_strike set, delta must still be +1.0 (is_long=True).

    The option Φ(d1) sub-piece of Art. 279a(2) is deferred to a future P-item.
    P8.13 ships the linear ±1 placeholder only — option rows are treated as
    linear until the option sub-piece lands.  This test name encodes the deferral
    explicitly so reviewers know why +1.0 is the correct expected value here.
    """
    # Arrange
    fn = _get_compute_supervisory_delta_linear()
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-004"],
            "is_long": [True],
            "delta": [1.0],
            "option_strike": [0.035],
        }
    )

    # Act
    try:
        result = fn(lf)
    except NotImplementedError as exc:
        pytest.fail(
            f"compute_supervisory_delta_linear raised NotImplementedError: {exc}. "
            "Implement the linear ±1 body in P8.13 (option Φ(d1) is deferred; "
            "this test expects +1.0 as a linear placeholder)."
        )

    actual = result.collect()["supervisory_delta"][0]

    # Assert — linear placeholder +1.0 (option sub-piece deferred)
    assert actual == 1.0, (
        f"Expected supervisory_delta=1.0 for is_long=True option row (linear placeholder, "
        f"Art. 279a(1)); option Φ(d1) sub-piece is deferred. Got {actual!r}."
    )
