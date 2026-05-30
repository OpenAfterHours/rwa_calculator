"""Contract tests for CRR Art. 123 payroll citation correctness in source files.

Enforces the citation hygiene sweep for P1.175: the stale ``123(3)(a-b)``
payroll/pension-loan paragraph must be replaced with the corrected ``123(4)``
form in all in-scope source files.

NOTE: The ``123(3)(c)`` citation (non-regulatory retail 100% RW) is CORRECT
and intentionally left in place — this test does NOT assert its absence.

Files are located via the imported ``rwa_calc`` package so that these tests
pass against whichever src tree is on sys.path — the worktree during Wave 3,
the main tree at the Step-6 gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import rwa_calc

# Resolve to .../src/rwa_calc regardless of which worktree is active.
_ROOT = Path(rwa_calc.__file__).resolve().parent

_IN_SCOPE: list[tuple[str, Path]] = [
    ("data/schemas.py", _ROOT / "data" / "schemas.py"),
    ("data/tables/b31_risk_weights.py", _ROOT / "data" / "tables" / "b31_risk_weights.py"),
    ("engine/sa/namespace.py", _ROOT / "engine" / "sa" / "namespace.py"),
]

_IDS = [label for label, _ in _IN_SCOPE]


@pytest.mark.parametrize("label,path", _IN_SCOPE, ids=_IDS)
def test_stale_art123_payroll_paragraph_absent(label: str, path: Path) -> None:
    """The stale '123(3)(a-b)' citation must not appear in any in-scope source file.

    Arrange: read the source file text.
    Act:     search for the stale citation literal.
    Assert:  the literal is absent.

    Note: '123(3)(c)' (non-regulatory retail) is a separate, correct citation
    and is NOT checked here.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "123(3)(a-b)" not in text, (
        f"{label}: found stale citation '123(3)(a-b)' — replace with '123(4)' (full path: {path})"
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
