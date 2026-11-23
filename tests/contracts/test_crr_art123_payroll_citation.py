"""Contract tests for CRR Art. 123 payroll citation correctness in source and test files.

Enforces the citation hygiene sweep for P1.175, widened by P5.59: the stale
``123(3)(a-b)`` payroll/pension-loan paragraph must be replaced with the
corrected ``123(4)`` form. Paragraph 3 (a) and (b) of the Basel 3.1 retail
article are the transactor 45% and the regulatory-retail 75% limbs; the 35%
payroll/pension limb is paragraph 4, which paragraph 3 opens "Subject to".

Two halves, deliberately scoped differently:

- **Absence** is checked across the whole ``rwa_calc`` source tree AND the whole
  ``tests/`` tree. The P1.175 sweep scoped it to three named source files, so the
  stale form survived four times in ``tests/unit/test_b31_sa_risk_weights.py``
  where the gate never looked (P5.59). This file is excluded from the scan: it
  must name the literal to ban it.
- **Presence** of ``123(4)`` stays on the three source files that carry the
  payroll branch. Widened to a whole tree it would fail on every file that never
  discusses payroll.

``docs/`` is not scanned: the changelog quotes the old form as history.

The source tree is located via the imported ``rwa_calc`` package and the test
tree via this file's own path, so these tests pass against whichever checkout
is active — the worktree during Wave 3, the main tree at the Step-6 gate.

NOTE: The ``123(3)(c)`` citation (non-regulatory retail 100% RW) is CORRECT
and intentionally left in place — this test does NOT assert its absence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import rwa_calc

_STALE = "123(3)(a-b)"

# Resolve to .../src/rwa_calc regardless of which worktree is active.
_ROOT = Path(rwa_calc.__file__).resolve().parent

# Resolve to .../tests of the checkout that holds this file.
_THIS_FILE = Path(__file__).resolve()
_TESTS_ROOT = _THIS_FILE.parents[1]

# engine/sa/risk_weights.py hosts the retail branch chains that carry the
# Art. 123(4) payroll citation (formerly engine/sa/namespace.py).
_IN_SCOPE: list[tuple[str, Path]] = [
    ("data/schemas.py", _ROOT / "data" / "schemas.py"),
    (
        "engine/sa/b31_risk_weight_tables.py",
        _ROOT / "engine" / "sa" / "b31_risk_weight_tables.py",
    ),
    ("engine/sa/risk_weights.py", _ROOT / "engine" / "sa" / "risk_weights.py"),
]

_IDS = [label for label, _ in _IN_SCOPE]

# The test file whose four stale citations this gate was widened to catch.
_PAYROLL_TEST_FILE = _TESTS_ROOT / "unit" / "test_b31_sa_risk_weights.py"


def test_stale_art123_payroll_paragraph_absent_from_src_and_tests() -> None:
    """The stale '123(3)(a-b)' citation must not appear in any src or tests .py file.

    Arrange: collect every ``.py`` file under ``src/rwa_calc`` and ``tests/``,
             less this file, and check the population reaches both trees.
    Act:     record every line carrying the stale citation literal.
    Assert:  no line does; a failure lists every offending ``path:line``.

    Note: '123(3)(c)' (non-regulatory retail) is a separate, correct citation
    and is NOT checked here.
    """
    # Arrange
    scanned = _scanned_files()
    assert _PAYROLL_TEST_FILE.resolve() in scanned, (
        f"the scan does not reach the test tree ({_TESTS_ROOT}) - it would be "
        "blind to the file this gate was widened for"
    )
    assert all(path.resolve() in scanned for _, path in _IN_SCOPE), (
        f"the scan does not reach the source tree ({_ROOT})"
    )
    assert _THIS_FILE not in scanned, "the gate would match its own ban and never go green"

    # Act
    hits = [
        f"{path}:{lineno}"
        for path in sorted(scanned)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _STALE in line
    ]

    # Assert
    assert hits == [], (
        f"found stale citation '{_STALE}' - the payroll/pension 35% limb is "
        f"Art. 123(4); replace it at: {hits}"
    )


@pytest.mark.parametrize("label,path", _IN_SCOPE, ids=_IDS)
def test_corrected_art123_payroll_paragraph_present(label: str, path: Path) -> None:
    """The corrected '123(4)' citation must appear in every in-scope source file.

    Arrange: read the source file text.
    Act:     search for the corrected citation literal.
    Assert:  the literal is present at least once.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "123(4)" in text, (
        f"{label}: expected corrected citation '123(4)' to be present but it was not found "
        f"(full path: {path})"
    )


def _scanned_files() -> set[Path]:
    """Every ``.py`` file under the active ``rwa_calc`` and ``tests/`` trees, bar this one."""
    files = {path.resolve() for path in _ROOT.rglob("*.py")}
    files |= {path.resolve() for path in _TESTS_ROOT.rglob("*.py")}
    files.discard(_THIS_FILE)
    return files
