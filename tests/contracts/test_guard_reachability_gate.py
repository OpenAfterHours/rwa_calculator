"""Contract tests for arch_check check 20 — contracts-layer guard reachability.

Check 20 is the graduated form of this project's dominant meta-pattern: build
the instrument, stop before wiring it. Three entries in
``docs/development/escape-log.md`` are classed ``gate-not-run`` for exactly
that, and the input contract was the fifth measured instance — 10 of the 14
public validators in ``contracts/validation.py`` (402 lines, all carrying green
unit tests) were unreachable from any production path, so a feed sending
PD = 1.5 to mean "1.5%" returned an RWA understated by 99.9%, silently.

Four things are asserted here, in ascending order of how easy they are to
break by accident:

- **The gate is wired.** ``check_guard_reachability`` is registered in
  ``arch_check.main()``. A check that exists and is not registered is the very
  failure mode check 20 exists to close, so it would be absurd for check 20 to
  arrive unregistered.
- **Every arch_check check is wired**, not only this one — the general form of
  the same rule, and the reason this file is worth more than one assertion.
- **The analysis has exactly one implementation.**
  ``scripts/validator_reachability.py`` reports the census and
  ``scripts/arch_check.py`` decides pass/fail, but both read one measurement.
  Two copies that drift is the failure mode this project keeps paying for.
- **No guard in ``contracts/`` is unreachable** — the substantive gate.

These tests re-use the check functions from ``scripts/arch_check.py`` so the
rule, the population and the allowlist live in exactly one place (the same
pattern as ``test_arch_migration_gates.py``).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"
ARCH_CHECK_PATH = REPO_ROOT / "scripts" / "arch_check.py"
CENSUS_PATH = REPO_ROOT / "scripts" / "validator_reachability.py"


def _load_arch_check() -> ModuleType:
    """Load scripts/arch_check.py as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location("_arch_check", ARCH_CHECK_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {ARCH_CHECK_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def _module_functions(path: Path) -> dict[str, ast.FunctionDef]:
    """Module-level function definitions in a script, by name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _names_referenced_in(node: ast.AST) -> set[str]:
    """Every bare name loaded anywhere inside an AST subtree."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Ids of the Constant nodes that are docstrings rather than data."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            ids.add(id(first.value))
    return ids


def _code_references_census(path: Path) -> list[str]:
    """Imports or string literals naming the census script, docstrings excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and "validator_reachability" in node.module
        ):
            found.append(f"line {node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Import):
            found.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if "validator_reachability" in alias.name
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "validator_reachability" in node.value
            and id(node) not in docstrings
        ):
            found.append(f"line {node.lineno}: string literal {node.value!r}")
    return found


def test_check_20_is_registered_in_arch_check() -> None:
    """check_guard_reachability is invoked by arch_check.main(), not merely defined."""
    main_fn = _module_functions(ARCH_CHECK_PATH)["main"]

    assert "check_guard_reachability" in _names_referenced_in(main_fn), (
        "check 20 (check_guard_reachability) is defined in scripts/arch_check.py but "
        "not referenced in main(), so `python scripts/arch_check.py` never runs it. "
        "An unwired gate has exactly the same effect on a defect as no gate — which "
        "is the escape class check 20 itself exists to close. Add it to the `checks` "
        "list in main()."
    )


def test_every_arch_check_check_is_registered() -> None:
    """No arch_check check may exist without main() invoking it.

    The general form of the test above. ``check_watchfire_citations`` and
    ``check_pack_citations`` take no path argument and are invoked directly
    rather than through the ``checks`` list, so the assertion is *referenced
    somewhere in main()* rather than *present in that list*.
    """
    functions = _module_functions(ARCH_CHECK_PATH)
    declared = {name for name in functions if name.startswith("check_")}
    referenced = _names_referenced_in(functions["main"])

    unwired = sorted(declared - referenced)
    assert not unwired, (
        "scripts/arch_check.py defines check functions that main() never invokes: "
        f"{', '.join(unwired)}. A written-but-unregistered check reads as coverage "
        "and enforces nothing (docs/development/escape-log.md, escape class "
        "`gate-not-run`). Register it in main(), or delete it."
    )


def test_the_reachability_analysis_has_one_implementation() -> None:
    """The census script reads the gate's measurement instead of keeping its own.

    Asserted three ways: the census calls the shared entry points, the gate
    does not depend on the census (so the dependency cannot become a cycle,
    and the gate keeps working if the diagnostic is deleted), and the two
    agree on the population.
    """
    census_source = CENSUS_PATH.read_text(encoding="utf-8")
    census_tree = ast.parse(census_source)
    census_names = _names_referenced_in(census_tree) | {
        node.attr for node in ast.walk(census_tree) if isinstance(node, ast.Attribute)
    }

    for shared in ("measure_guard_reachability", "is_measured_guard"):
        assert shared in census_names, (
            f"scripts/validator_reachability.py does not use arch_check.{shared}. "
            "The census and the gate must read one measurement — a second copy of "
            "the reachability analysis is free to drift, and a diagnostic that "
            "disagrees with the gate is worse than no diagnostic."
        )

    assert not _code_references_census(ARCH_CHECK_PATH), (
        "scripts/arch_check.py loads scripts/validator_reachability.py in code. The "
        "dependency points diagnostic -> gate and never the other way: the gate runs "
        "in CI and under these tests, and must keep working if the census script is "
        "renamed, broken or deleted. (Naming it in a docstring is fine — this is "
        "about imports and loads.)"
    )

    arch_check = _load_arch_check()
    measured = arch_check.measure_guard_reachability(SRC_ROOT)
    unreachable = {
        f"{module.name}::{name}"
        for module, (functions, _entry, reachable) in measured.items()
        for name in functions
        if arch_check.is_measured_guard(module, name) and name not in reachable
    }
    census = importlib.util.spec_from_file_location("_validator_reachability", CENSUS_PATH)
    assert census is not None and census.loader is not None
    census_module = importlib.util.module_from_spec(census)
    sys.modules["_validator_reachability"] = census_module
    census.loader.exec_module(census_module)

    assert census_module.main() == len(unreachable), (
        "scripts/validator_reachability.py reports a different number of unreachable "
        "guards than arch_check check 20 measures. They have forked."
    )


def test_every_contracts_guard_is_reachable_from_production() -> None:
    """Check 20 itself: no guard in contracts/ is dead code shaped like a guard."""
    arch_check = _load_arch_check()
    violations = arch_check.check_guard_reachability(SRC_ROOT)
    assert not violations, (
        "Contracts-layer guard reachability violated (arch_check check 20, Phase 0 of "
        "docs/plans/test-space-correctness-proposal.md). A guard no production path "
        "invokes is not a guard — it reads as coverage while customer data flows past "
        "it. Wire it into a production path, or delete it:\n" + "\n".join(violations)
    )
