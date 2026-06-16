"""Tests for the A-IRB 0.5 floor multipliers (originally P6.32).

Two assertions:

1. PRIMARY (AST scan): no bare 0.5 float literals remain inside the
   ``_compute_ccf`` and ``_compute_ead`` function bodies in engine/ccf.py.
   The multipliers must be sourced from the rulepack, not inlined.

2. SECONDARY (pack check): the Basel 3.1 rulepack exposes
   ``airb_revolving_ccf_floor_multiplier`` and ``airb_obs_floor_b_multiplier``,
   both equal to ``Decimal('0.5')`` — the regulatory value-home after the
   Phase 5 S12-05 table-move out of ``data/tables/airb_floors.py``.

References:
    - BCBS CRE32.27: A-IRB revolving CCF floor at 50% of SA CCF
    - PRA PS1/26 Art. 166D(5)(b): facility EAD floor multiplier of 50%
"""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from rwa_calc.rulebook.resolve import resolve

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CCF_ENGINE_PATH = Path(__file__).parent.parent.parent / "src" / "rwa_calc" / "engine" / "ccf.py"

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
    Assert:  the list is empty — the literal must be sourced from the
             ``airb_revolving_ccf_floor_multiplier`` rulepack scalar (CRE32.27).
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
        "P6.32 requires sourcing this from the airb_revolving_ccf_floor_multiplier "
        "rulepack scalar (CRE32.27)."
    )


def test_p6_32_no_bare_0_5_literal_in_compute_ead() -> None:
    """_compute_ead must not contain a bare 0.5 float literal after P6.32.

    Arrange: parse engine/ccf.py with the ast module.
    Act:     walk the _compute_ead FunctionDef body for ast.Constant nodes
             whose value is exactly 0.5.
    Assert:  the list is empty — the literal must be sourced from the
             ``airb_obs_floor_b_multiplier`` rulepack scalar (Art. 166D(5)(b)).
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
        "P6.32 requires sourcing this from the airb_obs_floor_b_multiplier "
        "rulepack scalar (PRA PS1/26 Art. 166D(5)(b))."
    )


# ---------------------------------------------------------------------------
# Test 2 — SECONDARY: the rulepack holds the floor multipliers (value-home)
# ---------------------------------------------------------------------------


def test_airb_revolving_ccf_floor_multiplier_resolves_to_half() -> None:
    """The b31 pack ``airb_revolving_ccf_floor_multiplier`` equals 0.5.

    Arrange: resolve the Basel 3.1 rulepack.
    Act:     read the ``airb_revolving_ccf_floor_multiplier`` scalar.
    Assert:  value equals Decimal('0.5') (BCBS CRE32.27 own-estimate CCF floor).
    """
    # Arrange / Act
    value = resolve("b31", date(2027, 1, 1)).scalar("airb_revolving_ccf_floor_multiplier")

    # Assert
    assert value == Decimal("0.5"), (
        f"airb_revolving_ccf_floor_multiplier = {value!r}, expected Decimal('0.5') "
        "(BCBS CRE32.27: A-IRB revolving CCF floor = 50% x SA CCF)"
    )


def test_airb_obs_floor_b_multiplier_resolves_to_half() -> None:
    """The b31 pack ``airb_obs_floor_b_multiplier`` equals 0.5.

    Arrange: resolve the Basel 3.1 rulepack.
    Act:     read the ``airb_obs_floor_b_multiplier`` scalar.
    Assert:  value equals Decimal('0.5') (PRA PS1/26 Art. 166D(5)(b)).
    """
    # Arrange / Act
    value = resolve("b31", date(2027, 1, 1)).scalar("airb_obs_floor_b_multiplier")

    # Assert
    assert value == Decimal("0.5"), (
        f"airb_obs_floor_b_multiplier = {value!r}, expected Decimal('0.5') "
        "(PRA PS1/26 Art. 166D(5)(b): facility EAD floor multiplier)"
    )
