"""
Architectural linter for RWA Calculator.

Checks machine-verifiable invariants from CLAUDE.md:
1. Every src/ module has `from __future__ import annotations`
2. No ABC imports (Protocol only)
3. No raw .collect().lazy() outside materialise.py (use materialise_barrier)
4. No engine= passed to collect/collect_all (engine choice is config-driven)

Usage:
    python scripts/arch_check.py [path]  # defaults to src/rwa_calc/

Exit codes:
    0 = all checks pass
    1 = violations found
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The abstraction layer itself is allowed to use raw collect patterns
COLLECT_ALLOWLIST = {"materialise.py"}


def _is_excluded(py_file: Path) -> bool:
    """Skip __init__.py (re-export modules) and ui/marimo/ (different execution model)."""
    if py_file.name == "__init__.py":
        return True
    parts = py_file.parts
    if "ui" in parts and "marimo" in parts:
        return True
    return False


def check_future_annotations(path: Path) -> list[str]:
    """Every .py file with code must have `from __future__ import annotations`."""
    violations = []
    for py_file in sorted(path.rglob("*.py")):
        if _is_excluded(py_file):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        # Only check files that contain imports, defs, or classes
        has_code = any(
            line.strip().startswith(("import ", "from ", "def ", "class ", "@"))
            for line in text.split("\n")
            if not line.strip().startswith("#")
        )
        if not has_code:
            continue
        if "from __future__ import annotations" not in text:
            violations.append(f"  {py_file}: missing `from __future__ import annotations`")
    return violations


def check_no_abc(path: Path) -> list[str]:
    """No ABC imports -- use Protocol instead."""
    violations = []
    pattern = re.compile(r"^\s*(from\s+abc\s+import|import\s+abc\b)")
    for py_file in sorted(path.rglob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            if pattern.match(line):
                violations.append(f"  {py_file}:{i}: ABC import -- use Protocol instead")
    return violations


def check_no_collect_lazy(path: Path) -> list[str]:
    """No .collect().lazy() outside materialise.py -- use materialise_barrier()."""
    violations = []
    pattern = re.compile(r"\.collect\(\)\s*\.lazy\(\)")
    for py_file in sorted(path.rglob("*.py")):
        if py_file.name in COLLECT_ALLOWLIST:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            if pattern.search(line):
                violations.append(
                    f"  {py_file}:{i}: .collect().lazy() -- use materialise_barrier()"
                )
    return violations


def check_no_engine_arg(path: Path) -> list[str]:
    """No engine= in collect calls -- engine choice is config-driven via materialise.py."""
    violations = []
    pattern = re.compile(r"(\.collect|collect_all)\([^)]*engine\s*=")
    for py_file in sorted(path.rglob("*.py")):
        if py_file.name in COLLECT_ALLOWLIST:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            if pattern.search(line):
                violations.append(
                    f"  {py_file}:{i}: engine= in collect -- use materialise.py"
                )
    return violations


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/rwa_calc")
    if not target.exists():
        print(f"Error: {target} does not exist")
        return 1

    checks = [
        ("from __future__ import annotations", check_future_annotations),
        ("No ABC imports (use Protocol)", check_no_abc),
        ("No .collect().lazy() (use materialise_barrier)", check_no_collect_lazy),
        ("No engine= in collect (use materialise.py)", check_no_engine_arg),
    ]

    all_violations: list[tuple[str, list[str]]] = []
    for name, fn in checks:
        v = fn(target)
        if v:
            all_violations.append((name, v))

    if not all_violations:
        print("arch_check: all checks passed")
        return 0

    print("arch_check: VIOLATIONS FOUND\n")
    for name, violations in all_violations:
        print(f"[FAIL] {name}")
        for v in violations:
            print(v)
        print()

    total = sum(len(v) for _, v in all_violations)
    print(f"Total: {total} violation(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
