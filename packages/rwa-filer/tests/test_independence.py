"""rwa-filer is standalone: nothing in it may reach into ``rwa_calc``.

Two limbs, because they catch different things:

- the SOURCE limb walks every module of the installed package and fails on an
  ``rwa_calc`` import. It runs everywhere, including the shared workspace
  environment where ``rwa_calc`` happens to be importable.
- the ENVIRONMENT limb runs only where the suite was installed on its own
  (CI's ``uv sync --package rwa-filer`` job sets ``RWA_FILER_ISOLATED=1``) and
  asserts ``rwa_calc`` cannot be found at all — which is what proves the
  declared dependencies are complete, rather than satisfied by accident from
  the other half of the workspace.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

import pytest

import rwa_filer

PACKAGE_ROOT = Path(rwa_filer.__file__).resolve().parent
FORBIDDEN = "rwa_calc"


def _imported_top_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_module_imports_rwa_calc() -> None:
    # Arrange
    modules = sorted(PACKAGE_ROOT.rglob("*.py"))

    # Act
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in modules
        if FORBIDDEN in _imported_top_level_names(ast.parse(path.read_text(encoding="utf-8")))
    ]

    # Assert
    assert modules, "the walk found no modules — the check would be vacuous"
    assert offenders == []


@pytest.mark.skipif(
    os.environ.get("RWA_FILER_ISOLATED") != "1",
    reason="only meaningful in an environment that installed rwa-filer alone",
)
def test_rwa_calc_is_not_installed_in_the_isolated_environment() -> None:
    assert importlib.util.find_spec(FORBIDDEN) is None
