"""Contract tests for data/engine separation.

Enforces the architectural invariant established by PRs #244, #246, #247,
#248, #249:

- Regulatory values (risk weights, LGDs, CCFs, floors, scaling factors) live
  in ``src/rwa_calc/data/tables/``.
- Input-domain validation enums (eligible type strings, category maps) live
  in ``src/rwa_calc/data/schemas.py``.
- ``engine/**`` imports these values; it must not declare its own regulatory
  scalar literals or string-enum collections at module scope.

These tests re-use the check functions from ``scripts/arch_check.py`` so the
rules and their allowlists live in exactly one place. A failure here means a
new module-level constant was introduced in ``engine/**`` that needs to move
to ``data/tables/`` or ``data/schemas.py`` (or — if genuinely engine-internal
— be added to the relevant allowlist in ``scripts/arch_check.py``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"


def _load_arch_check():
    """Load scripts/arch_check.py as a module without polluting sys.path."""
    script_path = REPO_ROOT / "scripts" / "arch_check.py"
    spec = importlib.util.spec_from_file_location("_arch_check", script_path)
    assert spec is not None and spec.loader is not None, f"cannot load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def test_no_regulatory_scalars_in_engine() -> None:
    """Regulatory scalar literals must live in src/rwa_calc/data/tables/."""
    arch_check = _load_arch_check()
    violations = arch_check.check_no_regulatory_scalars_in_engine(SRC_ROOT)
    assert not violations, (
        "Regulatory scalar literal declared in engine/** — move to "
        "src/rwa_calc/data/tables/ (or add to REGULATORY_SCALAR_ALLOWLIST in "
        "scripts/arch_check.py with justification):\n" + "\n".join(violations)
    )


def test_no_validation_enums_in_engine() -> None:
    """Input-domain string-enum collections must live in src/rwa_calc/data/schemas.py."""
    arch_check = _load_arch_check()
    violations = arch_check.check_no_validation_enums_in_engine(SRC_ROOT)
    assert not violations, (
        "String-literal collection declared in engine/** — move to "
        "src/rwa_calc/data/schemas.py (or add to VALIDATION_ENUM_ALLOWLIST in "
        "scripts/arch_check.py with justification):\n" + "\n".join(violations)
    )
