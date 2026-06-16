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


def test_no_numeric_tables_in_engine() -> None:
    """Module-level float-rate collection literals must live in a rulepack pack.

    Sibling of the scalar check for the regulatory-table class checks 5/6 miss
    (a ``{float: float}`` RW map, e.g. the former LIFE_INSURANCE_RW_MAP). Such
    tables go in rulebook/packs and are read back via rwa_calc.rulebook.resolve.
    """
    arch_check = _load_arch_check()
    violations = arch_check.check_no_numeric_tables_in_engine(SRC_ROOT)
    assert not violations, (
        "Regulatory float-rate table declared in engine/** — move it to a "
        "rulepack pack and read it back via resolve (or add to "
        "NUMERIC_TABLE_ALLOWLIST in scripts/arch_check.py with justification):\n"
        + "\n".join(violations)
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


def test_no_engine_data_tables_imports() -> None:
    """engine/** must not import rwa_calc.data.tables (Phase 5 / S13 hard ban).

    The migration relocated every regulatory table module into engine/ (values
    sourced from the rulepack packs) and removed the data/tables package. Any
    engine import of it is a regression — read the cited rulepack pack via
    rwa_calc.rulebook.resolve instead.
    """
    arch_check = _load_arch_check()
    violations = arch_check.check_no_engine_data_tables_imports(SRC_ROOT)
    assert not violations, (
        "engine/** imports rwa_calc.data.tables — the package is retired; read "
        "the rulepack pack via rwa_calc.rulebook.resolve instead:\n" + "\n".join(violations)
    )


def test_no_regime_bool_in_engine() -> None:
    """engine/** must not branch on config.is_crr / config.is_basel_3_1.

    Regime-specific behaviour reads a cited rulepack Feature (pack.feature(...))
    so the regime seam stays in the rulebook. Genuine exceptions (dual-run
    validation, EUR/GBP regime asymmetry, no-pack bootstrap fallbacks) live in
    REGIME_BOOL_ALLOWLIST.
    """
    arch_check = _load_arch_check()
    violations = arch_check.check_no_regime_bool_in_engine(SRC_ROOT)
    assert not violations, (
        "Regime boolean read in engine/** — branch on a rulepack Feature "
        "(pack.feature(...)) instead, or add to REGIME_BOOL_ALLOWLIST in "
        "scripts/arch_check.py with justification:\n" + "\n".join(violations)
    )
