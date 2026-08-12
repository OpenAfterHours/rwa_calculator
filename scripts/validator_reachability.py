"""
Contracts guard reachability census.

Purpose:
    Report which guards in the ``rwa_calc.contracts`` layer are transitively
    reachable from production code, and which are only ever called by their own
    tests. A validator that no production path invokes is not a guard — it is
    documentation with a green test attached.

Pipeline position:
    Not part of the pipeline. Diagnostic script, and the human-readable face of
    ``arch_check`` check 20 ("every guard in contracts/ is reachable from
    src/"). It prints a census; ``arch_check`` decides pass/fail.

Key responsibilities:
- Print, per contracts module, the production entry points, the reachable
  guards, and the unreachable split with each one's line count
- Report the same measurement the gate enforces, so a developer draining the
  list sees the shape of the problem rather than a pass/fail

Relationship to the gate:
    The measurement lives in ``scripts/arch_check.py``
    (``measure_guard_reachability`` / ``is_measured_guard``) and this script
    reads it from there, so the analysis has exactly one implementation. The
    dependency points diagnostic -> gate and never the other way: the gate runs
    in CI and under the contract tests, and must keep working if this script is
    renamed, broken or deleted.

References:
- docs/plans/test-space-correctness-proposal.md — the review this came from
- docs/plans/engine-defensiveness-boundary-hardening.md — "the
  contracts/validation.py bundle validators were never wired into pipeline.py"
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "rwa_calc"


def main() -> int:
    """Print the reachability census. Returns the count of unreachable guards."""
    arch_check = _load_arch_check()
    measured = arch_check.measure_guard_reachability(PACKAGE_ROOT)

    unreachable_total = 0
    lines_total = 0
    for module, (functions, entry_points, reachable) in sorted(measured.items()):
        guards = [name for name in sorted(functions) if arch_check.is_measured_guard(module, name)]
        if not guards:
            continue
        unreachable = [name for name in guards if name not in reachable]
        unreachable_total += len(unreachable)
        lines_total += sum(_function_line_count(functions[name]) for name in unreachable)
        _print_module_census(module, functions, entry_points, guards, unreachable)

    print(f"\n{lines_total} lines of guard logic no production path can reach.")
    if unreachable_total:
        print("\nThis is arch_check check 20. Wire them into a production path, or delete them.")
    return unreachable_total


def _print_module_census(
    module: Path,
    functions: dict[str, ast.stmt],
    entry_points: set[str],
    guards: list[str],
    unreachable: list[str],
) -> None:
    """Print one module's entry points, reachable guards and unreachable split."""
    print(f"\n=== {module.relative_to(PACKAGE_ROOT).as_posix()} ===")

    print("\nPRODUCTION ENTRY POINTS (referenced in code by another module under src/):")
    for name in sorted(entry_points):
        print(f"   {name}")

    print("\nGUARDS REACHABLE FROM PRODUCTION:")
    for name in guards:
        if name not in unreachable:
            print(f"   {name}")

    print(f"\nGUARDS NOT REACHABLE ({len(unreachable)} of {len(guards)}):")
    for name in unreachable:
        print(f"   {name:<38} ({_function_line_count(functions[name])} lines)")


def _load_arch_check() -> ModuleType:
    """Load scripts/arch_check.py by path, without depending on sys.path or cwd."""
    script_path = REPO_ROOT / "scripts" / "arch_check.py"
    spec = importlib.util.spec_from_file_location("_arch_check", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def _function_line_count(node: ast.stmt) -> int:
    """Source lines spanned by a function definition, decorators included."""
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
    return (node.end_lineno or start) - start + 1


if __name__ == "__main__":
    main()
