"""Contract tests for CRR Art. 114 paragraph citation correctness in source files.

Enforces the citation hygiene sweep for P1.175: the stale ``114(3)/(4)``
paragraph compound must be replaced with the corrected ``114(4)/(7)`` form
(or, in eu_sovereign.py, with the split ``114(4)`` + ``114(7)`` form) in all
in-scope source files.

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

# Files that carry the "114(3)/(4)" compound and must switch to "114(4)/(7)".
# The former engine/sa/namespace.py entry split with the module: the override
# chains live in risk_weights.py, the guarantee-substitution helpers in
# rw_adjustments.py — both carry Art. 114(4)/(7) citations.
_STANDARD_SCOPE: list[tuple[str, Path]] = [
    ("engine/sa/risk_weights.py", _ROOT / "engine" / "sa" / "risk_weights.py"),
    ("engine/sa/rw_adjustments.py", _ROOT / "engine" / "sa" / "rw_adjustments.py"),
    (
        "engine/stages/classify/approach.py",
        _ROOT / "engine" / "stages" / "classify" / "approach.py",
    ),
    ("engine/irb/guarantee.py", _ROOT / "engine" / "irb" / "guarantee.py"),
]

_STANDARD_IDS = [label for label, _ in _STANDARD_SCOPE]

# eu_sovereign.py uses the *split* form ("114(4)" + "114(7)") rather than the
# combined slash notation, so it gets its own parametrized set.
_EU_SOV_PATH = _ROOT / "data" / "tables" / "eu_sovereign.py"


@pytest.mark.parametrize("label,path", _STANDARD_SCOPE, ids=_STANDARD_IDS)
def test_stale_art114_compound_absent(label: str, path: Path) -> None:
    """The stale '114(3)/(4)' citation must not appear in any in-scope source file.

    Arrange: read the source file text.
    Act:     search for the stale citation literal.
    Assert:  the literal is absent.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "114(3)/(4)" not in text, (
        f"{label}: found stale citation '114(3)/(4)' — replace with '114(4)/(7)' "
        f"(full path: {path})"
    )


@pytest.mark.parametrize("label,path", _STANDARD_SCOPE, ids=_STANDARD_IDS)
def test_corrected_art114_compound_present(label: str, path: Path) -> None:
    """The corrected '114(4)/(7)' citation must appear in every in-scope source file.

    Arrange: read the source file text.
    Act:     search for the corrected citation literal.
    Assert:  the literal is present at least once.
    """
    # Arrange
    text = path.read_text(encoding="utf-8")

    # Act / Assert
    assert "114(4)/(7)" in text, (
        f"{label}: expected corrected citation '114(4)/(7)' to be present but it was not found "
        f"(full path: {path})"
    )


def test_eu_sovereign_stale_art114_compound_absent() -> None:
    """The stale '114(3)/(4)' compound must not appear in eu_sovereign.py.

    Arrange: read eu_sovereign.py.
    Act:     search for the stale citation literal.
    Assert:  the literal is absent.
    """
    # Arrange
    text = _EU_SOV_PATH.read_text(encoding="utf-8")

    # Act / Assert
    assert "114(3)/(4)" not in text, (
        "data/tables/eu_sovereign.py: found stale citation '114(3)/(4)' — "
        "replace with split '114(4)' and '114(7)' forms "
        f"(full path: {_EU_SOV_PATH})"
    )


def test_eu_sovereign_art114_4_present() -> None:
    """The citation '114(4)' must appear in eu_sovereign.py.

    Arrange: read eu_sovereign.py.
    Act:     search for '114(4)'.
    Assert:  the literal is present at least once.
    """
    # Arrange
    text = _EU_SOV_PATH.read_text(encoding="utf-8")

    # Act / Assert
    assert "114(4)" in text, (
        "data/tables/eu_sovereign.py: expected citation '114(4)' to be present but it was not found "
        f"(full path: {_EU_SOV_PATH})"
    )


def test_eu_sovereign_art114_7_present() -> None:
    """The citation '114(7)' must appear in eu_sovereign.py.

    Arrange: read eu_sovereign.py.
    Act:     search for '114(7)'.
    Assert:  the literal is present at least once.
    """
    # Arrange
    text = _EU_SOV_PATH.read_text(encoding="utf-8")

    # Act / Assert
    assert "114(7)" in text, (
        "data/tables/eu_sovereign.py: expected citation '114(7)' to be present but it was not found "
        f"(full path: {_EU_SOV_PATH})"
    )
