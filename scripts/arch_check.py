"""
Architectural linter for RWA Calculator.

Checks machine-verifiable invariants from CLAUDE.md:
1. Every src/ module has `from __future__ import annotations`
2. No ABC imports (Protocol only)
3. No raw .collect().lazy() outside materialise.py (use materialise_barrier)
4. No engine= passed to collect/collect_all (engine choice is config-driven)
5. No regulatory scalar literals declared in engine/** (must live in data/tables/)
6. No input-domain string-enum collections declared in engine/** (must live in data/schemas.py)
7. No inline `"col" not in schema.names()` defaulting in engine/** (use
   ensure_columns against a ColumnSpec schema in data/schemas.py instead)
8. Every stage module in engine/** declares `logger = logging.getLogger(__name__)`
   and does not call `print()` or `logging.basicConfig()`.

Checks 5, 6, 7 enforce the data/engine separation. Check 8 enforces the
observability contract (see docs/specifications/observability.md). Rare
intentional exceptions are listed in the ALLOWLIST dicts below; adding a new
entry there should be a deliberate, reviewed decision.

Usage:
    python scripts/arch_check.py [path]  # defaults to src/rwa_calc/

Exit codes:
    0 = all checks pass
    1 = violations found
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

# The abstraction layer itself is allowed to use raw collect patterns
COLLECT_ALLOWLIST = {"materialise.py"}

# Existing module-level regulatory-like scalars in engine/** that were
# deliberately kept in place (see PR notes next to each). New entries require
# explicit regulatory justification — regulatory values otherwise belong in
# src/rwa_calc/data/tables/.
REGULATORY_SCALAR_ALLOWLIST: dict[str, set[str]] = {
    # float alias of imported Decimal (PR #248)
    "engine/aggregator/_floor.py": {"GCRA_CAP_RATE"},
    # CRR Art. 62(d) 0.6% T2 credit cap — candidate for relocation to data/tables/
    "engine/aggregator/_schemas.py": {"T2_CREDIT_CAP_RATE"},
    # float alias of imported CRR_K_SCALING_FACTOR Decimal (PR #248)
    "engine/comparison.py": {"_CRR_SCALING_FACTOR"},
    "engine/equity/calculator.py": {
        "_CIU_THIRD_PARTY_MULTIPLIER",  # Art. 132b(2) 20% uplift multiplier
        "_RW_TO_PERCENT",  # audit formatting constant (not regulatory)
    },
    # Inverse standard-normal at 0.999 used by IRB formulas (mathematical, not reg)
    "engine/irb/formulas.py": {"G_999"},
    # CRR Art. 153(5) short-maturity threshold — candidate for relocation
    "engine/slotting/namespace.py": {"_SHORT_MATURITY_THRESHOLD_YEARS"},
}

# Existing engine-side string collections that are internal approach/column/driver
# identifiers, not input-domain validation enums. Adding a new entry should be a
# deliberate, reviewed decision — input-domain validation enums belong in
# src/rwa_calc/data/schemas.py.
VALIDATION_ENUM_ALLOWLIST: dict[str, set[str]] = {
    # ApproachType enum values + aggregator fallback labels (internal routing)
    "engine/aggregator/_schemas.py": {"IRB_APPROACHES"},
    "engine/comparison.py": {
        "_COMPARISON_COLUMNS",  # output column names
        "_OPTIONAL_COLUMNS",  # output column names
        "_IRB_APPROACHES",  # approach IDs
        "_ATTRIBUTION_DRIVERS",  # internal driver labels
    },
    # Art. 231 allocation column mapping (PR #249 — retained as engine config)
    "engine/crm/expressions.py": {"CRM_ALLOC_COLUMNS"},
}

# Engine modules exempt from the check-8 "must declare a module logger" rule.
# These are utility / helper modules (not stage implementations) — they do not
# need their own logger. New stage implementations (loader, classifier,
# calculators, aggregator, etc.) MUST declare `logger = logging.getLogger(__name__)`.
LOGGER_REQUIRED_EXEMPT: set[str] = {
    # Supporting / helper modules that do not correspond to a pipeline stage.
    "engine/ccf.py",
    "engine/utils.py",
    "engine/crm/collateral.py",
    "engine/crm/expressions.py",
    "engine/crm/guarantees.py",
    "engine/crm/haircuts.py",
    "engine/crm/life_insurance.py",
    "engine/crm/provisions.py",
    "engine/crm/simple_method.py",
    "engine/sa/supporting_factors.py",
    "engine/irb/adjustments.py",
    "engine/irb/formulas.py",
    "engine/irb/guarantee.py",
    "engine/irb/namespace.py",
    "engine/irb/stats_backend.py",
    "engine/slotting/namespace.py",
    "engine/aggregator/_crm_reporting.py",
    "engine/aggregator/_el_summary.py",
    "engine/aggregator/_equity_prep.py",
    "engine/aggregator/_floor.py",
    "engine/aggregator/_schemas.py",
    "engine/aggregator/_summaries.py",
    "engine/aggregator/_supporting_factors.py",
    "engine/aggregator/_utils.py",
}

# Files where an inline `"col" not in schema.names()` check is a legitimate
# non-defaulting pattern (early-exit guard, optional-output-column detection,
# combined warning+default emission). New entries require explicit justification
# — schema-driven defaults otherwise belong in ensure_columns + ColumnSpec.
SCHEMA_DEFAULTS_ALLOWLIST: set[str] = {
    # Optional-output column detection for COREP comparison frame.
    "engine/comparison.py",
    # Early-exit guards (netting / parent-facility detection, CRM output check)
    # — not defaulting.
    "engine/crm/collateral.py",
    "engine/crm/simple_method.py",
    # Combined warning + default emission for PD / LGD under IRB — the warning
    # is part of the data-quality contract and doesn't fit ensure_columns.
    "engine/irb/calculator.py",
    # `ead_final` derivation (fair_value → carrying_value → ead → 0.0) — this
    # is a multi-source fallback, not a simple default.
    "engine/equity/calculator.py",
}


def _is_excluded(py_file: Path) -> bool:
    """Skip __init__.py (re-export modules) and ui/marimo/ (different execution model)."""
    if py_file.name == "__init__.py":
        return True
    parts = py_file.parts
    return bool("ui" in parts and "marimo" in parts)


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
                violations.append(f"  {py_file}:{i}: engine= in collect -- use materialise.py")
    return violations


# ---------------------------------------------------------------------------
# Data/engine separation checks (PRs #244, #246, #247, #248, #249)
# ---------------------------------------------------------------------------


def _is_upper_const_name(name: str) -> bool:
    """True when name is UPPER_SNAKE_CASE (leading underscores allowed)."""
    stripped = name.lstrip("_")
    if not stripped:
        return False
    if not any(c.isalpha() for c in stripped):
        return False
    return stripped == stripped.upper()


def _iter_module_assignments(tree: ast.Module) -> Iterator[tuple[int, str, ast.AST]]:
    """Yield (lineno, target_name, value_node) for top-level `NAME = value` assigns."""
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and stmt.value is not None:
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    yield stmt.lineno, tgt.id, stmt.value
        elif (
            isinstance(stmt, ast.AnnAssign)
            and stmt.value is not None
            and isinstance(stmt.target, ast.Name)
        ):
            yield stmt.lineno, stmt.target.id, stmt.value


def _rhs_is_regulatory_scalar(node: ast.AST) -> bool:
    """True when the RHS looks like a hardcoded regulatory scalar literal.

    Covers:
    - bare numeric literals (int/float) other than the trivial 0, 1, -1
    - Decimal("...") / Decimal(...) calls
    - float(...) / int(...) calls with a single argument (typical alias pattern)
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return False
        if isinstance(node.value, (int, float)):
            return node.value not in (0, 1, -1)
        return False
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        val = node.operand.value
        if isinstance(val, bool):
            return False
        if isinstance(val, (int, float)):
            return val not in (0, 1)
        return False
    if isinstance(node, ast.Call):
        fn = node.func
        fn_name: str | None = None
        if isinstance(fn, ast.Name):
            fn_name = fn.id
        elif isinstance(fn, ast.Attribute):
            fn_name = fn.attr
        if fn_name == "Decimal":
            return True
        if fn_name in {"float", "int"} and len(node.args) == 1 and not node.keywords:
            return True
    return False


def _rhs_is_str_collection(node: ast.AST) -> bool:
    """True when the RHS is a non-trivial all-string-literal collection.

    Matches:
    - list/tuple/set literal with >= 2 string-literal elements
    - dict with >= 2 string-literal keys AND all string-literal values
    - frozenset(...)/set(...)/tuple(...)/list(...) wrapping such a collection
    """
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        elts = node.elts
        if len(elts) < 2:
            return False
        return all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts)
    if isinstance(node, ast.Dict):
        if len(node.keys) < 2:
            return False
        keys_ok = all(
            k is not None and isinstance(k, ast.Constant) and isinstance(k.value, str)
            for k in node.keys
        )
        vals_ok = all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in node.values)
        return keys_ok and vals_ok
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
        and len(node.args) == 1
    ):
        return _rhs_is_str_collection(node.args[0])
    return False


def _iter_engine_files(path: Path) -> Iterator[Path]:
    """Yield every .py file under `<path>/engine/`, skipping __init__.py."""
    engine_root = path / "engine"
    if not engine_root.exists():
        return
    for py_file in sorted(engine_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        yield py_file


def check_no_regulatory_scalars_in_engine(path: Path) -> list[str]:
    """Module-level regulatory scalar literals belong in data/tables/, not engine/**."""
    violations: list[str] = []
    for py_file in _iter_engine_files(path):
        rel = py_file.relative_to(path).as_posix()
        allowed = REGULATORY_SCALAR_ALLOWLIST.get(rel, set())
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for lineno, name, value in _iter_module_assignments(tree):
            if not _is_upper_const_name(name):
                continue
            if name in allowed:
                continue
            if _rhs_is_regulatory_scalar(value):
                violations.append(
                    f"  {py_file}:{lineno}: {name} -- regulatory scalar in engine/ "
                    "(move to src/rwa_calc/data/tables/ or allowlist in arch_check.py)"
                )
    return violations


def check_no_inline_schema_defaults(path: Path) -> list[str]:
    """No inline `"col" not in schema.names()` / `"col" not in df.columns` in engine/**.

    The schema-driven replacement is ``ensure_columns(lf, <SCHEMA>)`` where
    ``<SCHEMA>`` is a ``dict[str, ColumnSpec]`` from ``data/schemas.py`` (or an
    ad-hoc fragment). Exemptions:

    - Per-file: listed in ``SCHEMA_DEFAULTS_ALLOWLIST`` (for files that are
      systematically exempt, e.g. early-exit guards throughout).
    - Per-line: append ``# arch-exempt: <reason>`` to the line to document why
      the inline pattern is the right tool (derivation, multi-source fallback,
      etc.).
    """
    violations: list[str] = []
    pattern = re.compile(
        r'"[^"]+"\s+not\s+in\s+(?:\w+\.collect_schema\(\)\.names\(\)|\w+\.names\(\)|\w+\.columns)'
    )
    exempt_marker = re.compile(r"#\s*arch-exempt\b")
    for py_file in _iter_engine_files(path):
        rel = py_file.relative_to(path).as_posix()
        if rel in SCHEMA_DEFAULTS_ALLOWLIST:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            if exempt_marker.search(line):
                continue
            if pattern.search(line):
                violations.append(
                    f"  {py_file}:{i}: inline `not in schema.names()` -- "
                    "use ensure_columns against a ColumnSpec schema "
                    "(or append '# arch-exempt: <reason>' if intentional)"
                )
    return violations


def check_no_validation_enums_in_engine(path: Path) -> list[str]:
    """Module-level string-enum collections belong in data/schemas.py, not engine/**."""
    violations: list[str] = []
    for py_file in _iter_engine_files(path):
        rel = py_file.relative_to(path).as_posix()
        allowed = VALIDATION_ENUM_ALLOWLIST.get(rel, set())
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for lineno, name, value in _iter_module_assignments(tree):
            if not _is_upper_const_name(name):
                continue
            if name in allowed:
                continue
            if _rhs_is_str_collection(value):
                violations.append(
                    f"  {py_file}:{lineno}: {name} -- string-literal collection in engine/ "
                    "(move to src/rwa_calc/data/schemas.py or allowlist in arch_check.py)"
                )
    return violations


def check_engine_logger_contract(path: Path) -> list[str]:
    """Every non-exempt engine module declares a module logger and avoids
    `print()` / `logging.basicConfig()`.

    Stage modules are expected to emit their operational telemetry through a
    logger — see docs/specifications/observability.md. Helper modules under
    engine/ that do not correspond to a pipeline stage are listed in
    ``LOGGER_REQUIRED_EXEMPT``.
    """
    violations: list[str] = []
    logger_pattern = re.compile(
        r"^\s*logger\s*=\s*logging\.getLogger\(__name__\)\s*$", re.MULTILINE
    )
    print_pattern = re.compile(r"(?<![\w.])print\s*\(")
    basic_config_pattern = re.compile(r"logging\.basicConfig\s*\(")

    for py_file in _iter_engine_files(path):
        rel = py_file.relative_to(path).as_posix()
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if rel not in LOGGER_REQUIRED_EXEMPT and not logger_pattern.search(text):
            violations.append(
                f"  {py_file}: stage module must declare "
                "`logger = logging.getLogger(__name__)` "
                "(or be added to LOGGER_REQUIRED_EXEMPT if it is a helper module)"
            )

        for i, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            if print_pattern.search(line):
                violations.append(f"  {py_file}:{i}: `print(` in engine/ — use a module logger")
            if basic_config_pattern.search(line):
                violations.append(
                    f"  {py_file}:{i}: `logging.basicConfig(` in engine/ — "
                    "use rwa_calc.observability.configure_logging at the entry point"
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
        (
            "No regulatory scalars in engine/ (use data/tables/)",
            check_no_regulatory_scalars_in_engine,
        ),
        (
            "No validation string-enums in engine/ (use data/schemas.py)",
            check_no_validation_enums_in_engine,
        ),
        (
            "No inline `not in schema.names()` in engine/ (use ensure_columns)",
            check_no_inline_schema_defaults,
        ),
        (
            "Engine modules declare a logger + no print()/basicConfig()",
            check_engine_logger_contract,
        ),
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
