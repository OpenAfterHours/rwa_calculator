"""
Contract tests for the CCR engine subpackage scaffold (P8.4).

Pins the required module structure, logger declarations, the public
free-function surface, and public function signatures for
``rwa_calc.engine.ccr``.

P8.4 scaffold is fully implemented; per-formula bodies (P8.12, P8.13, P8.14,
P8.17) have landed in subsequent batches with dedicated test files alongside.

All former deferred stubs have been removed:
    - compute_pfe_ir_singleton was removed in P6.30 (dead stub, never filled).

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
# The former ``namespace`` module (Polars ``lf.ccr`` shim) was deleted in
# Phase 4 Slice 7 — callers use the free functions directly.
_CCR_SUB_MODULES: tuple[str, ...] = (
    "sa_ccr",
    "rc",
    "pfe",
    "adjusted_notional",
    "supervisory_delta",
    "maturity_factor",
)

# Public free-function surface of the package — the scaffold contract pins
# this instead of the retired ``lf.ccr`` namespace registration.
_CCR_PUBLIC_FUNCTIONS: tuple[str, ...] = (
    "apply_legal_enforceability_gate",
    "apply_wwr_gate",
    "assign_hedging_set",
    "assign_ir_maturity_bucket",
    "ccr_rows_to_exposures",
    "compute_addon_per_asset_class",
    "compute_adjusted_notional_ir",
    "compute_ead",
    "compute_maturity_factor_margined",
    "compute_maturity_factor_unmargined",
    "compute_rc_margined",
    "compute_rc_unmargined",
    "compute_supervisory_delta_cdo_tranche",
    "compute_supervisory_delta_linear",
    "compute_supervisory_delta_option",
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
    """Each of the 7 CCR engine modules must be importable (P8.4 scaffold).

    ``__init__`` is checked via the package import; all other modules are
    checked via ``importlib.import_module``.
    """
    # Arrange
    full_name = "rwa_calc.engine.ccr" if modname == "__init__" else f"rwa_calc.engine.ccr.{modname}"

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
# 4. Public free-function surface (replaces the retired ``lf.ccr`` namespace)
# ===========================================================================


def test_ccr_free_function_surface_pinned() -> None:
    """rwa_calc.engine.ccr must expose exactly the pinned free-function surface.

    The ``ccr`` Polars LazyFrame namespace was retired in Phase 4 Slice 7
    (it was a pure delegation shim with zero call sites); the scaffold
    contract now pins the package's public free functions instead.
    """
    # Arrange
    import rwa_calc.engine.ccr as ccr_pkg

    # Assert — __all__ matches the pinned surface exactly
    assert tuple(ccr_pkg.__all__) == _CCR_PUBLIC_FUNCTIONS, (
        "rwa_calc.engine.ccr.__all__ must match the pinned free-function surface. "
        f"Expected {_CCR_PUBLIC_FUNCTIONS}, got {tuple(ccr_pkg.__all__)}."
    )

    # Assert — every pinned name is present on the package and callable
    for name in _CCR_PUBLIC_FUNCTIONS:
        fn = getattr(ccr_pkg, name, None)
        assert callable(fn), (
            f"rwa_calc.engine.ccr.{name} must be a callable free function; got {fn!r}."
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
# 10. compute_pfe_ir_singleton — REMOVED in P6.30 (dead stub never filled)
# ===========================================================================


def test_compute_pfe_ir_singleton_removed() -> None:
    """compute_pfe_ir_singleton must no longer exist anywhere in the CCR engine (P6.30).

    The function was a dead stub that raised NotImplementedError; P6.30 removes it
    surgically without touching the surrounding compute_pfe or namespace methods.

    Assertions (all five must hold):
    1. ``from rwa_calc.engine.ccr import compute_pfe_ir_singleton`` raises ImportError.
    2. ``from rwa_calc.engine.ccr.pfe import compute_pfe_ir_singleton`` raises ImportError.
    3. ``"compute_pfe_ir_singleton"`` is absent from ``rwa_calc.engine.ccr.__all__``.
    4. The ``pfe`` module does NOT expose a ``compute_pfe_ir_singleton`` attribute.
    5. Positive control: ``compute_pfe`` and ``compute_ead`` ARE importable.
    """
    import rwa_calc.engine.ccr  # Arrange

    # -----------------------------------------------------------------------
    # Assert 1 — symbol not re-exported from the package __init__
    # -----------------------------------------------------------------------
    with pytest.raises(ImportError):
        from rwa_calc.engine.ccr import (
            compute_pfe_ir_singleton,  # noqa: F401  # ty: ignore[unresolved-import]
        )

    # -----------------------------------------------------------------------
    # Assert 2 — symbol not defined in pfe.py
    # -----------------------------------------------------------------------
    with pytest.raises(ImportError):
        from rwa_calc.engine.ccr.pfe import (
            compute_pfe_ir_singleton,  # noqa: F401  # ty: ignore[unresolved-import]
        )

    # -----------------------------------------------------------------------
    # Assert 3 — symbol absent from __all__
    # -----------------------------------------------------------------------
    assert "compute_pfe_ir_singleton" not in rwa_calc.engine.ccr.__all__, (
        "'compute_pfe_ir_singleton' must be removed from rwa_calc.engine.ccr.__all__ (P6.30). "
        f"Current __all__: {rwa_calc.engine.ccr.__all__}"
    )

    # -----------------------------------------------------------------------
    # Assert 4 — pfe module attribute pfe_ir_singleton is gone
    # -----------------------------------------------------------------------
    import rwa_calc.engine.ccr.pfe as pfe_module

    assert not hasattr(pfe_module, "compute_pfe_ir_singleton"), (
        "``rwa_calc.engine.ccr.pfe.compute_pfe_ir_singleton`` must be removed (P6.30)."
    )

    # -----------------------------------------------------------------------
    # Assert 5 — positive control: sibling symbols are still present
    # -----------------------------------------------------------------------
    from rwa_calc.engine.ccr.pfe import compute_pfe  # noqa: F401 — must not raise
    from rwa_calc.engine.ccr.sa_ccr import compute_ead

    assert callable(compute_ead), (
        "``rwa_calc.engine.ccr.sa_ccr.compute_ead`` must still exist after P6.30 — "
        "only the singleton stub is removed."
    )


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
