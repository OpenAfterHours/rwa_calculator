"""
Contract: the rwa-filer workspace member is standalone, and the gate that says so works.

``rwa-filer`` is released on its own. ``rwa-calc`` depends on it; the reverse
must never be true, or the "standalone" wheel raises ``ModuleNotFoundError`` for
anyone who installs it without the calculator. Every job in this repository but
one runs in the shared workspace environment, where ``rwa_calc`` is importable
from anywhere — so an inverted import passes the whole suite here. The source
scan in ``scripts/arch_check.py`` check 23 is the gate that does not depend on
which environment is active, and this file holds that gate to four things:

1. it is clean on the real tree;
2. it goes red on each way a module can import ``rwa_calc`` — a plain
   ``import``, a ``from`` import of a submodule, and the two string forms
   (``importlib.import_module`` / ``__import__``);
3. it does not fire on a look-alike name (``rwa_calc_tools``) or on prose that
   merely mentions the calculator;
4. it treats an empty or missing member as a violation rather than a skip, and
   it is actually dispatched by ``main()``.

The member's own suite carries a second, independent source scan
(``packages/rwa-filer/tests/test_independence.py``) and CI's ``rwa-filer
(isolated)`` job proves the environment half. This file tests the gate, not the
package.

References:
- scripts/arch_check.py check 23
- docs/development/workspace.md
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
ARCH_CHECK_PATH: Final = REPO_ROOT / "scripts" / "arch_check.py"
PACKAGE_ROOT: Final = REPO_ROOT / "src" / "rwa_calc"

_CHECK_NAME: Final = "check_filer_is_standalone"
_KNOWN_REGISTERED_CHECK: Final = "check_future_annotations"
_MODULE_HEADER: Final = '"""A member module."""\n\nfrom __future__ import annotations\n\n'


def _load_arch_check():
    """Load ``scripts/arch_check.py`` by path, without polluting ``sys.path``."""
    spec = importlib.util.spec_from_file_location("_arch_check_workspace", ARCH_CHECK_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {ARCH_CHECK_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check_workspace"] = module
    spec.loader.exec_module(module)
    return module


def _run_over_member(
    body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, header: str = _MODULE_HEADER
) -> list[str]:
    """Run check 23 against a throwaway member holding one module with ``body``."""
    arch_check = _load_arch_check()
    member = tmp_path / "rwa_filer"
    member.mkdir()
    (member / "module.py").write_text(header + body, encoding="utf-8")
    monkeypatch.setattr(arch_check, "FILER_PACKAGE_ROOT", member)
    return getattr(arch_check, _CHECK_NAME)(PACKAGE_ROOT)


def test_check_23_is_clean_on_the_real_member() -> None:
    # Arrange
    arch_check = _load_arch_check()

    # Act
    findings = getattr(arch_check, _CHECK_NAME)(PACKAGE_ROOT)

    # Assert — adequacy first: the member the check walks really holds modules.
    assert sorted(arch_check.FILER_PACKAGE_ROOT.rglob("*.py")), (
        "the rwa-filer member holds no module, so a clean result would be vacuous"
    )
    assert findings == []


@pytest.mark.parametrize(
    "statement",
    [
        "import rwa_calc\n",
        "import rwa_calc.reporting\n",
        "from rwa_calc import __version__\n",
        "from rwa_calc.contracts.errors import CalculationError\n",
        "import importlib\n\nmodule = importlib.import_module('rwa_calc.reporting')\n",
        "module = __import__('rwa_calc')\n",
        "def late():\n    from rwa_calc.domain import enums\n    return enums\n",
    ],
    ids=[
        "import",
        "import-submodule",
        "from-package",
        "from-submodule",
        "import_module-string",
        "dunder-import-string",
        "function-local",
    ],
)
def test_check_23_flags_every_way_of_importing_rwa_calc(
    statement: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    findings = _run_over_member(statement, tmp_path, monkeypatch)

    # Assert
    assert len(findings) == 1, findings
    assert "rwa_calc" in findings[0] and "module.py" in findings[0]


@pytest.mark.parametrize(
    "statement",
    [
        "import rwa_calc_tools\n",
        "from rwa_calculator import thing\n",
        "from . import sibling\n",
        "NOTE = 'rwa_calc consumes this through its adapter'\n",
        "import importlib\n\nmodule = importlib.import_module('polars')\n",
    ],
    ids=["look-alike", "repo-name", "relative", "prose", "other-dynamic-import"],
)
def test_check_23_does_not_fire_on_look_alikes(
    statement: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    findings = _run_over_member(statement, tmp_path, monkeypatch)

    # Assert
    assert findings == []


def test_check_23_holds_the_member_to_the_future_annotations_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act — a module with code but without the __future__ import.
    findings = _run_over_member("import json\n", tmp_path, monkeypatch, header="")

    # Assert
    assert len(findings) == 1
    assert "from __future__ import annotations" in findings[0]


def test_check_23_treats_a_missing_member_as_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    arch_check = _load_arch_check()
    monkeypatch.setattr(arch_check, "FILER_PACKAGE_ROOT", tmp_path / "does_not_exist")

    # Act
    findings = getattr(arch_check, _CHECK_NAME)(PACKAGE_ROOT)

    # Assert — an unmeasured invariant must not read as a satisfied one.
    assert len(findings) == 1
    assert "lost its population" in findings[0]


def test_check_23_skips_a_genuine_subpath_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a member that WOULD be flagged, but the run targets engine/ only.
    arch_check = _load_arch_check()
    member = tmp_path / "rwa_filer"
    member.mkdir()
    (member / "module.py").write_text(_MODULE_HEADER + "import rwa_calc\n", encoding="utf-8")
    monkeypatch.setattr(arch_check, "FILER_PACKAGE_ROOT", member)

    # Act
    findings = getattr(arch_check, _CHECK_NAME)(PACKAGE_ROOT / "engine")

    # Assert
    assert findings == []


def test_check_23_is_registered_in_the_arch_check_run() -> None:
    """The check is dispatched by ``main()``, not merely defined."""
    # Arrange
    tree = ast.parse(ARCH_CHECK_PATH.read_text(encoding="utf-8"))
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"), None
    )
    assert main_fn is not None, "scripts/arch_check.py no longer defines main()"

    # Act
    referenced = {n.id for n in ast.walk(main_fn) if isinstance(n, ast.Name)}

    # Assert — adequacy first: the extraction still sees a known registration.
    assert _KNOWN_REGISTERED_CHECK in referenced
    assert _CHECK_NAME in referenced, (
        f"{_CHECK_NAME} is not referenced in scripts/arch_check.py::main(), so the "
        "gate never runs it"
    )
