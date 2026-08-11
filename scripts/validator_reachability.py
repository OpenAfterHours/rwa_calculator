"""
Validator reachability census.

Purpose:
    Report which public validators in ``rwa_calc.contracts.validation`` are
    transitively reachable from production code, and which are only ever called
    by their own tests. A validator that no production path invokes is not a
    guard — it is documentation with a green test attached.

Pipeline position:
    Not part of the pipeline. Diagnostic script, and the working seed for a
    proposed ``arch_check`` check 20 ("every public validator must be reachable
    from src/").

Key responsibilities:
- Parse ``contracts/validation.py`` and collect its public functions
- Find the entry points: validators named anywhere else under ``src/``
- Take the transitive closure over intra-module calls from those entry points
- Print the reachable / unreachable split, with the line count of each
  unreachable validator

References:
- docs/plans/test-space-correctness-proposal.md — the review this came from
- docs/plans/engine-defensiveness-boundary-hardening.md — "the
  contracts/validation.py bundle validators were never wired into pipeline.py"
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATION_MODULE = REPO_ROOT / "src" / "rwa_calc" / "contracts" / "validation.py"


def main() -> int:
    """Print the reachability census. Returns the count of unreachable validators."""
    source = VALIDATION_MODULE.read_text()
    tree = ast.parse(source)

    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    public = [name for name in functions if not name.startswith("_")]

    calls_within = _intra_module_calls(functions)
    entry_points = _production_entry_points(functions)
    reachable = _closure(entry_points, calls_within)

    unreachable = sorted(name for name in public if name not in reachable)

    print("PRODUCTION ENTRY POINTS (named outside validation.py):")
    for name in sorted(entry_points):
        print(f"   {name}")

    print("\nPUBLIC VALIDATORS REACHABLE FROM PRODUCTION:")
    for name in sorted(name for name in public if name in reachable):
        print(f"   {name}")

    print(f"\nPUBLIC VALIDATORS NOT REACHABLE ({len(unreachable)} of {len(public)}):")
    total_lines = 0
    for name in unreachable:
        segment = ast.get_source_segment(source, functions[name]) or ""
        lines = len(segment.splitlines())
        total_lines += lines
        print(f"   {name:<38} ({lines} lines)")

    print(f"\n{total_lines} lines of validation logic no production path can reach.")
    return len(unreachable)


def _intra_module_calls(functions: dict[str, ast.FunctionDef]) -> dict[str, set[str]]:
    """Map each function to the sibling functions it calls within the module."""
    calls: dict[str, set[str]] = {}
    for name, node in functions.items():
        called = {
            sub.func.id
            for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id in functions
        }
        calls[name] = called
    return calls


def _production_entry_points(functions: dict[str, ast.FunctionDef]) -> set[str]:
    """Validators named anywhere under src/ other than validation.py itself.

    ``contracts/__init__.py`` is excluded: re-exporting a name is not calling it.
    """
    candidates = [
        path
        for path in (REPO_ROOT / "src").rglob("*.py")
        if path != VALIDATION_MODULE and path.name != "__init__.py"
    ]
    entry: set[str] = set()
    for name in functions:
        pattern = re.compile(rf"\b{name}\s*\(")
        if any(pattern.search(p.read_text(errors="ignore")) for p in candidates):
            entry.add(name)
    return entry


def _closure(entry: set[str], calls: dict[str, set[str]]) -> set[str]:
    """Transitive closure of the call graph from the entry set."""
    reached: set[str] = set()
    stack = list(entry)
    while stack:
        current = stack.pop()
        if current in reached:
            continue
        reached.add(current)
        stack.extend(calls.get(current, ()))
    return reached


if __name__ == "__main__":
    main()
