"""Tests for P6.32: hoist inline 0.5 A-IRB floor multipliers out of engine/ccf.py.

Two assertions:

1. PRIMARY (AST scan): no bare 0.5 float literals remain inside the
   ``_compute_ccf`` and ``_compute_ead`` function bodies in engine/ccf.py.
   This test FAILS RED today because the literals are still inline.

2. SECONDARY (import check): ``src/rwa_calc/data/tables/airb_floors.py``
   exposes ``AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER`` and
   ``AIRB_OBS_FLOOR_B_MULTIPLIER``, both equal to ``Decimal('0.5')``.
   This test FAILS RED today because the module does not exist.

References:
    - BCBS CRE32.27: A-IRB revolving CCF floor at 50% of SA CCF
    - PRA PS1/26 Art. 166D(5)(b): facility EAD floor multiplier of 50%
"""

from __future__ import annotations

import ast
import importlib
from decimal import Decimal
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CCF_ENGINE_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "rwa_calc"
    / "engine"
    / "ccf.py"
)

_AIRB_FLOORS_MODULE = "rwa_calc.data.tables.airb_floors"

# ---------------------------------------------------------------------------
# Test 1 — PRIMARY: no bare 0.5 float literals in _compute_ccf / _compute_ead
# ---------------------------------------------------------------------------


def _collect_float_literals_in_function(tree: ast.Module, func_name: str) -> list[float]:
    """Return all ast.Constant values == 0.5 inside the named FunctionDef body."""
    found: list[float] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, float)
                    and child.value == 0.5
                ):
                    found.append(child.value)
    return found


def test_p6_32_no_bare_0_5_literal_in_compute_ccf() -> None:
    """_compute_ccf must not contain a bare 0.5 float literal after P6.32.

    Arrange: parse engine/ccf.py with the ast module.
    Act:     walk the _compute_ccf FunctionDef body for ast.Constant nodes
             whose value is exactly 0.5.
    Assert:  the list is empty — the literal must have been replaced by the
             AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER constant from
             data/tables/airb_floors.py.
    """
    # Arrange
    source = _CCF_ENGINE_PATH.read_text()
    tree = ast.parse(source)

    # Act
    literals = _collect_float_literals_in_function(tree, "_compute_ccf")

    # Assert
    assert literals == [], (
        f"Found {len(literals)} bare 0.5 float literal(s) in _compute_ccf "
        f"in {_CCF_ENGINE_PATH}. "
        "P6.32 requires replacing this with AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER "
        "from rwa_calc.data.tables.airb_floors (CRE32.27)."
    )


def test_p6_32_no_bare_0_5_literal_in_compute_ead() -> None:
    """_compute_ead must not contain a bare 0.5 float literal after P6.32.

    Arrange: parse engine/ccf.py with the ast module.
    Act:     walk the _compute_ead FunctionDef body for ast.Constant nodes
             whose value is exactly 0.5.
    Assert:  the list is empty — the literal must have been replaced by the
             AIRB_OBS_FLOOR_B_MULTIPLIER constant from
             data/tables/airb_floors.py.
    """
    # Arrange
    source = _CCF_ENGINE_PATH.read_text()
    tree = ast.parse(source)

    # Act
    literals = _collect_float_literals_in_function(tree, "_compute_ead")

    # Assert
    assert literals == [], (
        f"Found {len(literals)} bare 0.5 float literal(s) in _compute_ead "
        f"in {_CCF_ENGINE_PATH}. "
        "P6.32 requires replacing this with AIRB_OBS_FLOOR_B_MULTIPLIER "
        "from rwa_calc.data.tables.airb_floors (PRA PS1/26 Art. 166D(5)(b))."
    )


# ---------------------------------------------------------------------------
# Test 2 — SECONDARY: new module exists and exports correct Decimal constants
# ---------------------------------------------------------------------------


def test_p6_32_airb_floors_module_exports_revolving_ccf_floor() -> None:
    """AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER must equal Decimal('0.5').

    Arrange: import rwa_calc.data.tables.airb_floors (module under test).
    Act:     read AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER.
    Assert:  value equals Decimal('0.5').
    """
    # Arrange / Act
    try:
        module = importlib.import_module(_AIRB_FLOORS_MODULE)
    except ModuleNotFoundError:
        pytest.fail(
            f"Module '{_AIRB_FLOORS_MODULE}' not found. "
            "P6.32 requires creating src/rwa_calc/data/tables/airb_floors.py "
            "with AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER = Decimal('0.5')."
        )

    # Assert
    assert hasattr(module, "AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER"), (
        f"'{_AIRB_FLOORS_MODULE}' has no attribute AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER"
    )
    value = module.AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER
    assert value == Decimal("0.5"), (
        f"AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER = {value!r}, expected Decimal('0.5') "
        "(BCBS CRE32.27: A-IRB revolving CCF floor = 50% x SA CCF)"
    )


def test_p6_32_airb_floors_module_exports_obs_floor_b_multiplier() -> None:
    """AIRB_OBS_FLOOR_B_MULTIPLIER must equal Decimal('0.5').

    Arrange: import rwa_calc.data.tables.airb_floors (module under test).
    Act:     read AIRB_OBS_FLOOR_B_MULTIPLIER.
    Assert:  value equals Decimal('0.5').
    """
    # Arrange / Act
    try:
        module = importlib.import_module(_AIRB_FLOORS_MODULE)
    except ModuleNotFoundError:
        pytest.fail(
            f"Module '{_AIRB_FLOORS_MODULE}' not found. "
            "P6.32 requires creating src/rwa_calc/data/tables/airb_floors.py "
            "with AIRB_OBS_FLOOR_B_MULTIPLIER = Decimal('0.5')."
        )

    # Assert
    assert hasattr(module, "AIRB_OBS_FLOOR_B_MULTIPLIER"), (
        f"'{_AIRB_FLOORS_MODULE}' has no attribute AIRB_OBS_FLOOR_B_MULTIPLIER"
    )
    value = module.AIRB_OBS_FLOOR_B_MULTIPLIER
    assert value == Decimal("0.5"), (
        f"AIRB_OBS_FLOOR_B_MULTIPLIER = {value!r}, expected Decimal('0.5') "
        "(PRA PS1/26 Art. 166D(5)(b): facility EAD floor multiplier)"
    )
