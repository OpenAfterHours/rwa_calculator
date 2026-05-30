"""Contract tests for PS1/26 citation currency in source files.

Enforces the citation hygiene sweep for P1.188: stale ``PS9/24`` references
must be replaced with the correct ``PS1/26`` citation in three source files.

The three files are located via the imported ``rwa_calc`` package so that
these tests pass against whichever src tree is on sys.path — the worktree
during Wave 3, the main tree at the Step-6 gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import rwa_calc

# Resolve to .../src/rwa_calc regardless of which worktree is active.
_ROOT = Path(rwa_calc.__file__).resolve().parent

_IN_SCOPE: list[tuple[str, Path]] = [
    ("contracts/config.py", _ROOT / "contracts" / "config.py"),
    ("data/schemas.py", _ROOT / "data" / "schemas.py"),
    ("engine/irb/adjustments.py", _ROOT / "engine" / "irb" / "adjustments.py"),
]

_IDS = [label for label, _ in _IN_SCOPE]


@pytest.mark.parametrize("label,path", _IN_SCOPE, ids=_IDS)
def test_no_ps9_24_in_file(label: str, path: Path) -> None:
    """The stale 'PS9/24' citation must not appear in any in-scope source file.

    Arrange: read the source file text.
    Act:     search for the stale citation literal.
    Assert:  the literal is absent.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "PS9/24" not in text, (
        f"{label}: found stale citation 'PS9/24' — replace with 'PS1/26' (full path: {path})"
    )


@pytest.mark.parametrize("label,path", _IN_SCOPE, ids=_IDS)
def test_ps1_26_present_in_file(label: str, path: Path) -> None:
    """The correct 'PS1/26' citation must appear in every in-scope source file.

    Arrange: read the source file text.
    Act:     search for the current citation literal.
    Assert:  the literal is present at least once.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "PS1/26" in text, (
        f"{label}: expected citation 'PS1/26' to be present but it was not found "
        f"(full path: {path})"
    )
