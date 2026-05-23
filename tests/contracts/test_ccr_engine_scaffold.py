"""
Contract tests for the CCR engine subpackage scaffold (P8.4).

Pins the required module structure, logger declarations, Polars namespace
registration, and public function signatures for ``rwa_calc.engine.ccr``.

All tests in this file are expected to FAIL until the engine-implementer wave
delivers the 8 module files described in the scenario proposal.

References:
    - CRR Art. 274-280: SA-CCR EAD calculation
    - CRR Art. 275(1): RC = max(V - C, 0) for unmargined netting sets
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
# 9. compute_maturity_factor_unmargined — NotImplementedError (stub, P8.14)
# ===========================================================================


def test_compute_maturity_factor_unmargined_raises_not_implemented() -> None:
    """compute_maturity_factor_unmargined must raise NotImplementedError (stub until P8.14)."""
    # Arrange
    try:
        from rwa_calc.engine.ccr.maturity_factor import compute_maturity_factor_unmargined
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_maturity_factor_unmargined from "
            f"rwa_calc.engine.ccr.maturity_factor: {exc}. "
            "Add the stub in P8.4."
        )

    lf = pl.LazyFrame({"netting_set_id": ["NS-001"]})

    # Act + Assert
    with pytest.raises(NotImplementedError):
        compute_maturity_factor_unmargined(lf)


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
# 11. compute_ead — NotImplementedError (stub, P8.17)
# ===========================================================================


def test_compute_ead_raises_not_implemented() -> None:
    """compute_ead must raise NotImplementedError (stub until P8.17)."""
    # Arrange
    try:
        from rwa_calc.engine.ccr.sa_ccr import compute_ead
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(
            f"Cannot import compute_ead from rwa_calc.engine.ccr.sa_ccr: {exc}. "
            "Add the stub in P8.4."
        )

    lf = pl.LazyFrame({"netting_set_id": ["NS-001"]})

    # Act + Assert
    with pytest.raises(NotImplementedError):
        compute_ead(lf)
