"""
Contract tests for the CCR engine subpackage scaffold (P8.4).

Pins the required module structure, logger declarations, Polars namespace
registration, and public function signatures for ``rwa_calc.engine.ccr``.

P8.4 scaffold is fully implemented; per-formula bodies (P8.12, P8.13, P8.14,
P8.17) have landed in subsequent batches with dedicated test files alongside.

Deferred stubs (still raise NotImplementedError until their P-item lands):
    - compute_pfe_ir_singleton          (P8.16)

References:
    - CRR Art. 274-280: SA-CCR EAD calculation
    - CRR Art. 275(1): RC = max(V - C, 0) for unmargined netting sets
    - CRR Art. 279c(1): MF_i = sqrt(min(M_i, 1y) / 1y) for unmargined trades
    - CRR Art. 295-297: Contractual netting recognition
"""

from __future__ import annotations

import importlib
import logging

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Module inventory
# ---------------------------------------------------------------------------

# Non-init module names (imported as rwa_calc.engine.ccr.<name>).
_CCR_SUB_MODULES: tuple[str, ...] = (
    "sa_ccr",
    "rc",
    "pfe",
    "adjusted_notional",
    "supervisory_delta",
    "maturity_factor",
    "namespace",
)

# Full list including __init__ (represented by the empty string sentinel).
_ALL_MODULE_NAMES: tuple[str, ...] = ("__init__",) + _CCR_SUB_MODULES


# ===========================================================================
# 1. Package importability
# ===========================================================================


def test_ccr_subpackage_imports() -> None:
    """rwa_calc.engine.ccr must be importable as a package (P8.4 scaffold)."""
    # Arrange — nothing

    # Act + Assert
    try:
        import rwa_calc.engine.ccr  # noqa: F401
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"rwa_calc.engine.ccr is not importable: {exc}. "
            "Add src/rwa_calc/engine/ccr/__init__.py (P8.4)."
        )


# ===========================================================================
# 2. Individual module existence
# ===========================================================================


@pytest.mark.parametrize("modname", _ALL_MODULE_NAMES)
def test_ccr_module_exists(modname: str) -> None:
    """Each of the 8 CCR engine modules must be importable (P8.4 scaffold).

    ``__init__`` is checked via the package import; all other modules are
    checked via ``importlib.import_module``.
    """
    # Arrange
    if modname == "__init__":
        full_name = "rwa_calc.engine.ccr"
    else:
        full_name = f"rwa_calc.engine.ccr.{modname}"

    # Act + Assert
    try:
        importlib.import_module(full_name)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"Module '{full_name}' is not importable: {exc}. "
            f"Add src/rwa_calc/engine/ccr/{modname}.py (P8.4)."
        )


# ===========================================================================
# 3. Logger declarations
# ===========================================================================


@pytest.mark.parametrize("modname", _ALL_MODULE_NAMES)
def test_ccr_module_declares_logger(modname: str) -> None:
    """Each CCR engine module must declare ``logger = logging.getLogger(__name__)``.

    Mirrors the assertion shape of ``tests/contracts/test_logging_contract.py``
    lines 33-43. The expected logger name is ``rwa_calc.engine.ccr`` for
    ``__init__`` and ``rwa_calc.engine.ccr.<modname>`` for all sub-modules.
    """
    # Arrange
    if modname == "__init__":
        full_name = "rwa_calc.engine.ccr"
        expected_logger_name = "rwa_calc.engine.ccr"
    else:
        full_name = f"rwa_calc.engine.ccr.{modname}"
        expected_logger_name = full_name

    try:
        module = importlib.import_module(full_name)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"Cannot import '{full_name}' to check logger: {exc}. Run test_ccr_module_exists first."
        )

    # Act
    logger = getattr(module, "logger", None)

    # Assert — attribute existence and type
    assert isinstance(logger, logging.Logger), (
        f"{full_name} must declare `logger = logging.getLogger(__name__)` — "
        f"got {logger!r} (type {type(logger).__name__})"
    )

    # Assert — correct __name__ binding
    assert logger.name == expected_logger_name, (
        f"{full_name}.logger has name {logger.name!r}; "
        f"expected {expected_logger_name!r}. "
        f"Use `logger = logging.getLogger(__name__)`."
    )


# ===========================================================================
# 4. Polars LazyFrame namespace registration
# ===========================================================================


def test_ccr_lazyframe_namespace_registered() -> None:
    """Importing rwa_calc.engine.ccr must register the ``ccr`` Polars namespace.

    Mirrors the ``lf.sa`` registration pattern in
    ``rwa_calc.engine.sa.namespace``.  After import the attribute
    ``pl.LazyFrame.ccr`` must exist.
    """
    # Arrange — trigger namespace registration
    try:
        import rwa_calc.engine.ccr  # noqa: F401
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"rwa_calc.engine.ccr is not importable: {exc}. "
            "Cannot test namespace registration until P8.4 scaffold is in place."
        )

    # Act + Assert
    assert hasattr(pl.LazyFrame, "ccr"), (
        "After `import rwa_calc.engine.ccr`, `pl.LazyFrame` must expose a `ccr` attribute. "
        "Register the namespace with "
        "`@pl.api.register_lazyframe_namespace('ccr')` in namespace.py (P8.4)."
    )


# ===========================================================================
# 5. compute_rc_unmargined — clean case (Art. 275(1): RC = max(V - C, 0))
# ===========================================================================


def test_compute_rc_unmargined_clean_case() -> None:
    """compute_rc_unmargined must return RC = V - C = 100.0 - 20.0 = 80.0.

    CRR Art. 275(1): RC_unmargined = max(V_net - C_net, 0).
    """
    # Arrange
    try:
        from rwa_calc.engine.ccr.rc import compute_rc_unmargined
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_rc_unmargined from rwa_calc.engine.ccr.rc: {exc}. "
            "Add the function in P8.4."
        )

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-001"],
            "counterparty_reference": ["CP-001"],
            "v_net": [100.0],
            "c_net": [20.0],
            "is_legally_enforceable": [True],
            "is_margined": [False],
        }
    )

    # Act
    result = compute_rc_unmargined(lf).collect()

    # Assert — column presence
    assert "rc_unmargined" in result.columns, (
        f"Result must contain 'rc_unmargined' column; got columns: {result.columns}"
    )

    # Assert — dtype is Float64
    assert result.schema["rc_unmargined"] == pl.Float64, (
        f"'rc_unmargined' must be pl.Float64, got {result.schema['rc_unmargined']}"
    )

    # Assert — correct value: 100.0 - 20.0 = 80.0
    actual = result["rc_unmargined"][0]
    assert actual == 80.0, (
        f"compute_rc_unmargined: expected rc_unmargined=80.0 (V_net - C_net = 100 - 20), "
        f"got {actual!r}. CRR Art. 275(1): RC = max(V - C, 0)."
    )


# ===========================================================================
# 6. compute_rc_unmargined — floor at zero (Art. 275(1): RC >= 0)
# ===========================================================================


def test_compute_rc_unmargined_clamps_at_zero() -> None:
    """compute_rc_unmargined must return RC = 0.0 when C_net > V_net.

    CRR Art. 275(1): RC_unmargined = max(V_net - C_net, 0).
    When C_net = 120.0 > V_net = 50.0, RC = max(-70, 0) = 0.
    """
    # Arrange
    try:
        from rwa_calc.engine.ccr.rc import compute_rc_unmargined
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_rc_unmargined from rwa_calc.engine.ccr.rc: {exc}. "
            "Add the function in P8.4."
        )

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-002"],
            "counterparty_reference": ["CP-001"],
            "v_net": [50.0],
            "c_net": [120.0],
            "is_legally_enforceable": [True],
            "is_margined": [False],
        }
    )

    # Act
    result = compute_rc_unmargined(lf).collect()

    # Assert — zero floor
    actual = result["rc_unmargined"][0]
    assert actual == 0.0, (
        f"compute_rc_unmargined: expected rc_unmargined=0.0 (floor at zero when C > V), "
        f"got {actual!r}. CRR Art. 275(1): RC = max(V - C, 0)."
    )


# ===========================================================================
# 9. compute_maturity_factor_unmargined — three regimes (P8.14)
# ===========================================================================


def test_compute_maturity_factor_unmargined_three_rows() -> None:
    """MF_i = sqrt(min(M_i, 1y) / 1y) — three regimes (above-cap, sub-year, exact-quarter).

    CRR Art. 279c(1): MF_i = sqrt(min(M_i, 1y) / 1y) for unmargined trades.
    Row 0 (T-10Y): min(10.0, 1.0) / 1.0 = 1.0  -> sqrt(1.0)  = 1.0
    Row 1 (T-6M):  min(0.5,  1.0) / 1.0 = 0.5  -> sqrt(0.5)  ≈ 0.7071...
    Row 2 (T-3M):  min(0.25, 1.0) / 1.0 = 0.25 -> sqrt(0.25) = 0.5
    """
    from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined

    # Arrange
    lf = pl.LazyFrame(
        {
            "trade_id": ["T-10Y", "T-6M", "T-3M"],
            "netting_set_id": ["NS-001", "NS-001", "NS-002"],
            "years_to_maturity": [10.0, 0.5, 0.25],
        }
    )

    # Act
    result = compute_maturity_factor_unmargined(lf).collect()

    # Assert — column + dtype
    assert "maturity_factor" in result.columns
    assert result.schema["maturity_factor"] == pl.Float64

    # Assert — values
    actual = result["maturity_factor"].to_list()
    assert actual[0] == pytest.approx(1.0, rel=1e-12)
    assert actual[1] == pytest.approx(0.7071067811865476, rel=1e-12)
    assert actual[2] == pytest.approx(0.5, rel=1e-12)


# ===========================================================================
# 10. compute_pfe_ir_singleton — NotImplementedError (stub, P8.16)
# ===========================================================================


def test_compute_pfe_ir_singleton_raises_not_implemented() -> None:
    """compute_pfe_ir_singleton must raise NotImplementedError (stub until P8.16)."""
    # Arrange
    try:
        from rwa_calc.engine.ccr.pfe import compute_pfe_ir_singleton
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_pfe_ir_singleton from rwa_calc.engine.ccr.pfe: {exc}. "
            "Add the stub in P8.4."
        )

    lf = pl.LazyFrame({"netting_set_id": ["NS-001"]})

    # Act + Assert
    with pytest.raises(NotImplementedError):
        compute_pfe_ir_singleton(lf)


# ===========================================================================
# 11. compute_ead — returns LazyFrame with ead_ccr column (P8.17)
# ===========================================================================


def test_compute_ead_returns_lazyframe_with_ead_column() -> None:
    """P8.17 — compute_ead now returns LazyFrame with ead_ccr column; α=1.4 default."""
    from rwa_calc.engine.ccr.sa_ccr import compute_ead

    lf = pl.LazyFrame(
        {
            "netting_set_id": ["NS-A"],
            "rc_unmargined": [100.0],
            "pfe_addon": [50.0],
        }
    )
    result = compute_ead(lf)
    assert isinstance(result, pl.LazyFrame)
    collected = result.collect()
    assert "ead_ccr" in collected.columns
    assert collected["ead_ccr"][0] == pytest.approx(1.4 * 150.0, rel=1e-9)
