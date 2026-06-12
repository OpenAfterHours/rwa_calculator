"""
Architectural linter for RWA Calculator.

Checks machine-verifiable invariants from CLAUDE.md:
1. Every src/ module has `from __future__ import annotations`
2. No ABC imports (Protocol only)
3. No raw .collect().lazy() outside materialise.py (use materialise_edge)
4. No engine= passed to collect/collect_all (engine choice is config-driven)
5. No regulatory scalar literals declared in engine/** (must live in data/tables/)
6. No input-domain string-enum collections declared in engine/** (must live in data/schemas.py)
7. No inline `"col" not in schema.names()` defaulting in engine/** (use
   ensure_columns against a ColumnSpec schema in data/schemas.py instead)
8. Every stage module in engine/** declares `logger = logging.getLogger(__name__)`
   and does not call `print()` or `logging.basicConfig()`.
9. Every `@cites(...)` decorator references an instrument allowed by
   `[tool.watchfire]` and a citation the rulebook index recognises. Parse
   failures, unknown instruments, unknown articles (any instrument), and
   version mismatches are fatal; AST-walker ``unresolved`` findings remain
   soft warnings.
10. Every non-exempt module under engine/ and data/schemas.py carries a
    `References:` block in its module docstring (the CLAUDE.md mandated
    shape). Pure reshape / format / IO helpers are listed in
    ``REFERENCES_REQUIRED_EXEMPT``.
11. Architecture-debt ratchet: measured defensive-surface metrics (engine
    `.fill_null(` sites, string-literal column-presence guards,
    `.collect_schema(` probes, max engine module LOC) may not INCREASE
    above the committed baseline in ``scripts/arch_metrics.json``, and the
    watchfire `@cites(` decorator count may not DECREASE below it.
    Regenerate after an improvement with
    ``python scripts/arch_check.py --update-baseline``.
12. Import direction: contracts/ imports nothing above domain/data;
    engine/ never imports api/ui/reporting/analysis; reporting/ never
    imports api/ui; data/ and domain/ import nothing above themselves.
    Known legacy inversions are allowlisted in
    ``IMPORT_DIRECTION_ALLOWLIST`` and retired by the architecture
    migration phases (docs/plans/target-architecture-migration.md).

Checks 5, 6, 7 enforce the data/engine separation. Check 8 enforces the
observability contract (see docs/specifications/observability.md). Check 9
keeps the watchfire citation matrix honest. Check 10 prevents drift in the
module-docstring citation contract (see docs/development/citation-tracking.md).
Checks 11 and 12 are migration-plan Phase 0 guards (see
docs/plans/target-architecture-migration.md). Rare intentional exceptions
are listed in the ALLOWLIST dicts below; adding a new entry there should be
a deliberate, reviewed decision.

Usage:
    python scripts/arch_check.py [path] [--update-baseline]
    # path defaults to src/rwa_calc/; --update-baseline rewrites
    # scripts/arch_metrics.json from the current measured state

Exit codes:
    0 = all checks pass
    1 = violations found
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

# The abstraction layer itself is allowed to use raw collect patterns
COLLECT_ALLOWLIST = {"materialise.py"}

_PATH_AGGREGATOR_SCHEMAS = "engine/aggregator/_schemas.py"
_PATH_COMPARISON = "engine/comparison.py"
_PATH_UTILS = "engine/utils.py"
_PATH_COLLAPSE = "engine/aggregator/_collapse.py"

# Existing module-level regulatory-like scalars in engine/** that were
# deliberately kept in place (see PR notes next to each). New entries require
# explicit regulatory justification — regulatory values otherwise belong in
# src/rwa_calc/data/tables/.
REGULATORY_SCALAR_ALLOWLIST: dict[str, set[str]] = {
    # float alias of imported Decimal (PR #248)
    "engine/aggregator/_floor.py": {"GCRA_CAP_RATE"},
    # CRR Art. 62(d) 0.6% T2 credit cap — candidate for relocation to data/tables/
    _PATH_AGGREGATOR_SCHEMAS: {"T2_CREDIT_CAP_RATE"},
    # float alias of imported CRR_K_SCALING_FACTOR Decimal (PR #248)
    _PATH_COMPARISON: {"_CRR_SCALING_FACTOR"},
    "engine/equity/calculator.py": {
        "_CIU_THIRD_PARTY_MULTIPLIER",  # Art. 132b(2) 20% uplift multiplier
        "_RW_TO_PERCENT",  # audit formatting constant (not regulatory)
    },
    # Inverse standard-normal at 0.999 used by IRB formulas (mathematical, not reg)
    "engine/irb/formulas.py": {"G_999"},
    # CRR Art. 153(5) short-maturity threshold — candidate for relocation
    "engine/slotting/namespace.py": {"_SHORT_MATURITY_THRESHOLD_YEARS"},
    # Numerical epsilons for parallel-run reconciliation — mathematical
    # tolerances (float exactness / zero-division guards), not regulatory values.
    _PATH_COLLAPSE: {"_EAD_ZERO_GUARD"},
    "engine/reconciliation.py": {"_EXACT_EPSILON", "_ZERO_GUARD"},
}

# Existing engine-side string collections that are internal approach/column/driver
# identifiers, not input-domain validation enums. Adding a new entry should be a
# deliberate, reviewed decision — input-domain validation enums belong in
# src/rwa_calc/data/schemas.py.
VALIDATION_ENUM_ALLOWLIST: dict[str, set[str]] = {
    # ApproachType enum values + aggregator fallback labels (internal routing)
    _PATH_AGGREGATOR_SCHEMAS: {"IRB_APPROACHES", "SA_APPROACHES", "EQUITY_APPROACHES"},
    _PATH_COMPARISON: {
        "_COMPARISON_COLUMNS",  # output column names
        "_OPTIONAL_COLUMNS",  # output column names
        "_IRB_APPROACHES",  # approach IDs
        "_ATTRIBUTION_DRIVERS",  # internal driver labels
    },
    # Art. 231 allocation column mapping (PR #249 — retained as engine config)
    "engine/crm/expressions.py": {"CRM_ALLOC_COLUMNS"},
    # Nullable-partition-key registry for the partition_by_nullable helper.
    # These are engine-internal column names tightly coupled to the helper's
    # AST-level contract test; keeping them in `data/schemas.py` would split
    # the rule from the code that enforces it.
    _PATH_UTILS: {"NULLABLE_PARTITION_KEYS"},
    # Two-site coupling marker for QRRE-related facility columns. Same
    # rationale as NULLABLE_PARTITION_KEYS: these are engine-internal column
    # names that document a within-package coupling between
    # facility_undrawn._undrawn_select_expressions and
    # enrich.propagate_facility_qrre_columns; the constant exists to make the
    # coupling explicit and is pinned by
    # tests/unit/test_p6_26_qrre_coupling_constant.py. Moving it to
    # data/schemas.py would split the rule from the code that enforces it.
    "engine/stages/hierarchy/__init__.py": {"_FACILITY_QRRE_COUPLED_COLUMNS"},
    # Per-row money columns the securitisation residual multiplier scales.
    # These are engine-internal column names (the calculators' own output
    # columns), not input-domain validation enums. Pinned to the aggregator
    # because moving them to data/schemas.py would split the rule from the
    # code that enforces it.
    "engine/aggregator/_securitisation.py": {"MONEY_COLS"},
}

# Engine modules exempt from the check-8 "must declare a module logger" rule.
# These are utility / helper modules (not stage implementations) — they do not
# need their own logger. New stage implementations (loader, classifier,
# calculators, aggregator, etc.) MUST declare `logger = logging.getLogger(__name__)`.
LOGGER_REQUIRED_EXEMPT: set[str] = {
    # Supporting / helper modules that do not correspond to a pipeline stage.
    "engine/ccf.py",
    _PATH_UTILS,
    "engine/crm/collateral.py",
    "engine/crm/expressions.py",
    "engine/crm/guarantees.py",
    "engine/crm/haircuts.py",
    "engine/crm/life_insurance.py",
    "engine/crm/provisions.py",
    "engine/crm/simple_method.py",
    "engine/supporting_factors.py",
    "engine/irb/adjustments.py",
    "engine/irb/formulas.py",
    "engine/irb/guarantee.py",
    "engine/irb/namespace.py",
    "engine/irb/stats_backend.py",
    "engine/sa/namespace.py",
    "engine/slotting/namespace.py",
    "engine/aggregator/_crm_reporting.py",
    "engine/aggregator/_el_summary.py",
    "engine/aggregator/_equity_prep.py",
    "engine/aggregator/_floor.py",
    _PATH_AGGREGATOR_SCHEMAS,
    "engine/aggregator/_summaries.py",
    "engine/aggregator/_supporting_factors.py",
    "engine/aggregator/_utils.py",
    # Pure reshape helper: collapses guarantee/RE sub-rows to a key grain for
    # parallel-run reconciliation. No pipeline-stage telemetry.
    _PATH_COLLAPSE,
}

# Modules exempt from the check-10 "must declare a References: block" rule.
# Reshape / format / IO helpers under engine/ that carry no per-function
# regulatory citations — adding a References block would either duplicate the
# parent stage's citations or invent ones. New stage / calculator / aggregator
# modules under engine/ and the data/schemas.py module MUST carry a
# `References:` block in their module docstring.
REFERENCES_REQUIRED_EXEMPT: set[str] = {
    "engine/aggregator/_summaries.py",
    "engine/aggregator/_utils.py",
    _PATH_COLLAPSE,  # pure sub-row collapse helper, no citations
    "engine/aggregator/_equity_prep.py",
    _PATH_AGGREGATOR_SCHEMAS,
    _PATH_UTILS,
    "engine/fx_rate_sync.py",
    "engine/materialise.py",
    "engine/loader.py",
    "engine/irb/stats_backend.py",
}

# Files where an inline `"col" not in schema.names()` check is a legitimate
# non-defaulting pattern (early-exit guard, optional-output-column detection,
# combined warning+default emission). New entries require explicit justification
# — schema-driven defaults otherwise belong in ensure_columns + ColumnSpec.
SCHEMA_DEFAULTS_ALLOWLIST: set[str] = {
    # Optional-output column detection for COREP comparison frame.
    _PATH_COMPARISON,
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

# ---------------------------------------------------------------------------
# Check 11 — architecture-debt ratchet (migration plan Phase 0)
# ---------------------------------------------------------------------------

# Committed baseline for the defensive-surface metrics. Counts may not
# increase (and @cites may not decrease) relative to this file. After an
# improvement, rewrite it with `python scripts/arch_check.py --update-baseline`
# and commit the change alongside the improvement.
RATCHET_BASELINE_PATH = Path(__file__).resolve().parent / "arch_metrics.json"

# Metrics where the measured value may not INCREASE above the baseline.
RATCHET_MAX_METRICS = (
    "engine_fill_null_sites",
    "engine_presence_guard_sites",
    "engine_collect_schema_sites",
    "engine_eager_collect_sites",
    "max_engine_module_loc",
)

# Metrics where the measured value may not DECREASE below the baseline.
RATCHET_MIN_METRICS = ("cites_decorators",)

# Check 12 — import direction. Maps a top-level package under src/rwa_calc/
# to the rwa_calc module prefixes it must never import (runtime OR
# TYPE_CHECKING — the layering is conceptual, not just a runtime-cycle rule).
IMPORT_DIRECTION_RULES: dict[str, tuple[str, ...]] = {
    "contracts": (
        "rwa_calc.api",
        "rwa_calc.ui",
        "rwa_calc.reporting",
        "rwa_calc.engine",
        "rwa_calc.analysis",
        "rwa_calc.rulebook",
    ),
    "engine": ("rwa_calc.api", "rwa_calc.ui", "rwa_calc.reporting", "rwa_calc.analysis"),
    # The regime seam (migration Phase 4 v0 / Phase 5): sits between
    # contracts and engine — wraps config + data tables, never engine code.
    "rulebook": (
        "rwa_calc.api",
        "rwa_calc.ui",
        "rwa_calc.reporting",
        "rwa_calc.engine",
        "rwa_calc.analysis",
    ),
    "reporting": ("rwa_calc.api", "rwa_calc.ui"),
    "data": (
        "rwa_calc.api",
        "rwa_calc.ui",
        "rwa_calc.reporting",
        "rwa_calc.engine",
        "rwa_calc.contracts",
        "rwa_calc.analysis",
        "rwa_calc.rulebook",
    ),
    "domain": (
        "rwa_calc.api",
        "rwa_calc.ui",
        "rwa_calc.reporting",
        "rwa_calc.engine",
        "rwa_calc.contracts",
        "rwa_calc.data",
        "rwa_calc.analysis",
        "rwa_calc.rulebook",
    ),
}

# Known legacy inversions, allowlisted until the migration phase that retires
# them lands (docs/plans/target-architecture-migration.md). New entries
# require explicit justification.
IMPORT_DIRECTION_ALLOWLIST: dict[str, set[str]] = {
    # TYPE_CHECKING-only: CalculationResponse return type on ResultExporter /
    # report-generator protocols; CollateralLinkAllocation on the CRM
    # protocol. Retired by Phase 4 (protocol diet) / Phase 7 (reporting input
    # = sealed aggregator exit contract).
    "contracts/protocols.py": {
        "rwa_calc.api.models",
        "rwa_calc.engine.crm.link_allocation",
    },
    # TYPE_CHECKING-only CalculationResponse on the generator entry points.
    # Retired by Phase 7 (reporting consumes the sealed aggregator exit).
    "reporting/corep/generator.py": {"rwa_calc.api.models"},
    "reporting/pillar3/generator.py": {"rwa_calc.api.service"},
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
    """No .collect().lazy() outside materialise.py -- use materialise_edge()."""
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
                violations.append(f"  {py_file}:{i}: .collect().lazy() -- use materialise_edge()")
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


def _constant_is_reg_scalar(value: object) -> bool:
    """True when a bare numeric literal qualifies as a regulatory scalar."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value not in (0, 1, -1)
    return False


def _unaryop_is_reg_scalar(node: ast.UnaryOp) -> bool:
    """True when a UnaryOp wrapping a numeric literal qualifies as a regulatory scalar."""
    if not isinstance(node.operand, ast.Constant):
        return False
    val = node.operand.value
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return val not in (0, 1)
    return False


def _call_is_reg_scalar(node: ast.Call) -> bool:
    """True when a Call is a typical regulatory-scalar wrapper (Decimal / float / int)."""
    fn = node.func
    fn_name: str | None = None
    if isinstance(fn, ast.Name):
        fn_name = fn.id
    elif isinstance(fn, ast.Attribute):
        fn_name = fn.attr
    if fn_name == "Decimal":
        return True
    return bool(fn_name in {"float", "int"} and len(node.args) == 1 and not node.keywords)


def _rhs_is_regulatory_scalar(node: ast.AST) -> bool:
    """True when the RHS looks like a hardcoded regulatory scalar literal.

    Covers:
    - bare numeric literals (int/float) other than the trivial 0, 1, -1
    - Decimal("...") / Decimal(...) calls
    - float(...) / int(...) calls with a single argument (typical alias pattern)
    """
    if isinstance(node, ast.Constant):
        return _constant_is_reg_scalar(node.value)
    if isinstance(node, ast.UnaryOp):
        return _unaryop_is_reg_scalar(node)
    if isinstance(node, ast.Call):
        return _call_is_reg_scalar(node)
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


def _line_triggers_schema_default(
    line: str, pattern: re.Pattern[str], exempt_marker: re.Pattern[str]
) -> bool:
    """True when a line is a real inline-schema-default violation (post-exemption)."""
    stripped = line.strip()
    if stripped.startswith(("#", '"""', "'''")):
        return False
    if exempt_marker.search(line):
        return False
    return bool(pattern.search(line))


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
            if _line_triggers_schema_default(line, pattern, exempt_marker):
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


def _check_logger_declared(
    py_file: Path, rel: str, text: str, logger_pattern: re.Pattern[str]
) -> list[str]:
    """Return a violation if a non-exempt engine module lacks the module logger."""
    if rel in LOGGER_REQUIRED_EXEMPT or logger_pattern.search(text):
        return []
    return [
        f"  {py_file}: stage module must declare "
        "`logger = logging.getLogger(__name__)` "
        "(or be added to LOGGER_REQUIRED_EXEMPT if it is a helper module)"
    ]


def _check_no_print_or_basic_config(
    py_file: Path,
    text: str,
    print_pattern: re.Pattern[str],
    basic_config_pattern: re.Pattern[str],
) -> list[str]:
    """Return per-line violations for `print(` and `logging.basicConfig(` usage."""
    violations: list[str] = []
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

        violations.extend(_check_logger_declared(py_file, rel, text, logger_pattern))
        violations.extend(
            _check_no_print_or_basic_config(py_file, text, print_pattern, basic_config_pattern)
        )
    return violations


def check_module_references(path: Path) -> list[str]:
    """Every non-exempt module under engine/ and data/schemas.py carries a
    ``References:`` block in its module docstring.

    The CLAUDE.md docstring contract requires every regulatory module to cite
    the CRR / PRA PS1/26 / BCBS articles it implements. Reshape, format, and
    IO helpers that legitimately have no per-function regulatory citations are
    listed in ``REFERENCES_REQUIRED_EXEMPT``. The check is a literal token
    grep (``References:``) so existing protocol-only References blocks (e.g.
    ``loader.py``-style) remain valid — strict citation-form enforcement is
    the job of watchfire (check 9) on the ``@cites(...)`` decorators.
    """
    violations: list[str] = []
    targets = list(_iter_engine_files(path))
    schemas = path / "data" / "schemas.py"
    if schemas.exists():
        targets.append(schemas)
    for py_file in targets:
        rel = py_file.relative_to(path).as_posix()
        if rel in REFERENCES_REQUIRED_EXEMPT:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        docstring = ast.get_docstring(tree) or ""
        if "References:" not in docstring:
            violations.append(
                f"  {py_file}: module docstring missing `References:` block "
                "(cite CRR / PS1/26 articles, or add to "
                "REFERENCES_REQUIRED_EXEMPT in scripts/arch_check.py if a "
                "pure helper)"
            )
    return violations


# ---------------------------------------------------------------------------
# Check 11 — architecture-debt ratchet (migration plan Phase 0)
# ---------------------------------------------------------------------------

_FILL_NULL_PATTERN = re.compile(r"\.fill_null\(")
_COLLECT_SCHEMA_PATTERN = re.compile(r"\.collect_schema\(")
# String-literal membership test — `"col" in cols` / `"col" not in df.columns`.
# An approximation of "column-presence guard" (also catches dict-key probes),
# but a *consistent* one: the ratchet tracks the trend, not the exact census.
_PRESENCE_GUARD_PATTERN = re.compile(r"""["'][\w .-]+["']\s+(?:not\s+)?in\s+""")
_CITES_PATTERN = re.compile(r"@cites\(")
# Raw eager collects in engine/** (excl. collect_schema). Phase 1 discipline:
# stage-edge collects live in materialise.py; the remaining engine sites are
# small-lookup collects whose census is the allowlist — it may not grow.
_EAGER_COLLECT_PATTERN = re.compile(r"\.collect\(\)|collect_all\(")


def _count_pattern_lines(text: str, pattern: re.Pattern[str]) -> int:
    """Count pattern occurrences, skipping comment-only lines."""
    code_lines = _code_line_numbers(text)
    count = 0
    for lineno, line in enumerate(text.split("\n"), 1):
        if code_lines is not None and lineno not in code_lines:
            continue
        if line.strip().startswith("#"):
            continue
        count += len(pattern.findall(line))
    return count


def _code_line_numbers(text: str) -> set[int] | None:
    """Line numbers carrying actual code tokens (not docstrings/comments).

    A docstring or comment that *mentions* ``.collect()`` or ``.fill_null(``
    must not move the ratchet metrics. Lines whose only tokens are STRING /
    COMMENT / whitespace are excluded; a line like ``"col" in cols`` still
    qualifies because ``in`` and ``cols`` are code tokens on the same line.
    Returns None (count all lines) when tokenisation fails.
    """
    import io
    import tokenize

    non_code = {
        tokenize.COMMENT,
        tokenize.STRING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    code_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in non_code:
                continue
            for lineno in range(tok.start[0], tok.end[0] + 1):
                code_lines.add(lineno)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return code_lines


def _measure_ratchet_metrics(path: Path) -> dict[str, int]:
    """Measure the defensive-surface metrics over `path` (the package root)."""
    fill_null = presence = collect_schema = eager_collects = max_loc = 0
    for py_file in _iter_engine_files(path):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fill_null += _count_pattern_lines(text, _FILL_NULL_PATTERN)
        presence += _count_pattern_lines(text, _PRESENCE_GUARD_PATTERN)
        collect_schema += _count_pattern_lines(text, _COLLECT_SCHEMA_PATTERN)
        if py_file.name != "materialise.py":
            eager_collects += _count_pattern_lines(text, _EAGER_COLLECT_PATTERN)
        max_loc = max(max_loc, text.count("\n") + 1)

    cites = 0
    for py_file in sorted(path.rglob("*.py")):
        if _is_excluded(py_file):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        cites += _count_pattern_lines(text, _CITES_PATTERN)

    return {
        "engine_fill_null_sites": fill_null,
        "engine_presence_guard_sites": presence,
        "engine_collect_schema_sites": collect_schema,
        "engine_eager_collect_sites": eager_collects,
        "max_engine_module_loc": max_loc,
        "cites_decorators": cites,
    }


def write_ratchet_baseline(path: Path) -> dict[str, int]:
    """Measure and persist the ratchet baseline. Returns the metrics written."""
    metrics = _measure_ratchet_metrics(path)
    payload: dict[str, object] = {
        "_comment": (
            "Architecture-debt ratchet baseline (arch_check check 11). "
            "Counts may not increase (cites_decorators may not decrease). "
            "Regenerate after an improvement with: "
            "python scripts/arch_check.py --update-baseline"
        ),
        **metrics,
    }
    RATCHET_BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return metrics


def check_ratchet_metrics(path: Path) -> list[str]:
    """Defensive-surface metrics may not regress vs scripts/arch_metrics.json.

    See docs/plans/target-architecture-migration.md (Phase 0). The baseline is
    a committed file; improvements are banked by rewriting it via
    ``--update-baseline`` in the same commit as the improvement.
    """
    if not (path / "engine").is_dir():
        return []  # not the package root (e.g. a subpath run) — skip
    if not RATCHET_BASELINE_PATH.exists():
        return [
            f"  missing {RATCHET_BASELINE_PATH} — generate it with "
            "`python scripts/arch_check.py --update-baseline` and commit it"
        ]
    try:
        baseline = json.loads(RATCHET_BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"  unreadable {RATCHET_BASELINE_PATH}: {exc}"]

    current = _measure_ratchet_metrics(path)
    violations: list[str] = []
    improvements: list[str] = []
    for metric in RATCHET_MAX_METRICS:
        base = baseline.get(metric)
        if not isinstance(base, int):
            violations.append(f"  baseline missing/invalid metric {metric!r}")
            continue
        if current[metric] > base:
            violations.append(
                f"  {metric}: {current[metric]} > baseline {base} — defensive "
                "surface grew; remove the regression (preferred) or justify a "
                "baseline bump in review"
            )
        elif current[metric] < base:
            improvements.append(metric)
    for metric in RATCHET_MIN_METRICS:
        base = baseline.get(metric)
        if not isinstance(base, int):
            violations.append(f"  baseline missing/invalid metric {metric!r}")
            continue
        if current[metric] < base:
            violations.append(
                f"  {metric}: {current[metric]} < baseline {base} — the "
                "citation matrix may never shrink (restore @cites or justify "
                "a baseline rewrite in review)"
            )
        elif current[metric] > base:
            improvements.append(metric)
    if improvements and not violations:
        print(
            "[NOTE] ratchet metrics improved "
            f"({', '.join(improvements)}) — bank it: "
            "`python scripts/arch_check.py --update-baseline`"
        )
    return violations


# ---------------------------------------------------------------------------
# Check 12 — import direction (migration plan Phase 0)
# ---------------------------------------------------------------------------


def _resolve_relative_import(module_parts: tuple[str, ...], node: ast.ImportFrom) -> str | None:
    """Resolve a relative ImportFrom to an absolute dotted module name."""
    if node.level == 0:
        return node.module
    if node.level > len(module_parts):
        return None
    base = module_parts[: len(module_parts) - node.level]
    if node.module:
        return ".".join((*base, node.module))
    return ".".join(base) if base else None


def _iter_imported_modules(
    tree: ast.Module, module_parts: tuple[str, ...]
) -> Iterator[tuple[int, str]]:
    """Yield (lineno, absolute_module_name) for every import in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative_import(module_parts, node)
            if resolved:
                yield node.lineno, resolved


def check_import_direction(path: Path) -> list[str]:
    """Layer imports must point downward (IMPORT_DIRECTION_RULES).

    Applies to runtime AND ``TYPE_CHECKING`` imports — the layering is
    conceptual, not just a runtime-cycle rule. Known legacy inversions are
    allowlisted in ``IMPORT_DIRECTION_ALLOWLIST`` with the migration phase
    that retires them.
    """
    violations: list[str] = []
    for py_file in sorted(path.rglob("*.py")):
        rel_parts = py_file.relative_to(path).parts
        layer = rel_parts[0] if len(rel_parts) > 1 else None
        if layer not in IMPORT_DIRECTION_RULES:
            continue
        rel = py_file.relative_to(path).as_posix()
        banned = IMPORT_DIRECTION_RULES[layer]
        allowed = IMPORT_DIRECTION_ALLOWLIST.get(rel, set())
        # rwa_calc.<layer>.<subpath> — for resolving relative imports
        module_parts = ("rwa_calc", *rel_parts[:-1], py_file.stem)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for lineno, module in _iter_imported_modules(tree, module_parts):
            for prefix in banned:
                if module == prefix or module.startswith(prefix + "."):
                    if module in allowed or prefix in allowed:
                        continue
                    violations.append(
                        f"  {py_file}:{lineno}: {layer}/ imports {module} — "
                        "layering points downward (see check 12; allowlist "
                        "requires a migration-phase justification)"
                    )
    return violations


def check_no_empty_frame_sentinels(path: Path) -> list[str]:
    """No bare ``pl.LazyFrame()`` / ``pl.DataFrame().lazy()`` sentinels in engine/**.

    Migration Phase 2: optional frames are ``None`` — an empty-LazyFrame
    sentinel conflates "absent input" with "zero-row result", forcing every
    consumer to guess which it has (the root of the presence-guard debt).
    A genuine zero-row frame produced by a filter is fine; what this bans is
    *constructing* an empty frame to stand in for a missing one.
    """
    violations = []
    pattern = re.compile(r"pl\.LazyFrame\(\s*\)|pl\.DataFrame\(\s*\)\s*\.lazy\(\)")
    engine_root = path / "engine"
    if not engine_root.exists():
        return []
    for py_file in sorted(engine_root.rglob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        code_lines = _code_line_numbers(text)
        for i, line in enumerate(text.split("\n"), 1):
            if i not in code_lines:
                continue
            if pattern.search(line):
                violations.append(
                    f"  {py_file}:{i}: empty-LazyFrame sentinel -- optional frames are None"
                )
    return violations


def check_watchfire_citations() -> tuple[list[str], list[str]]:
    """Run `watchfire check` via its Python API.

    Returns ``(fatal, warnings)`` where ``fatal`` blocks the gate (parse
    failures, unknown instruments, unknown articles in any instrument, and
    version mismatches) and ``warnings`` is the soft bucket (AST-walker
    ``unresolved`` cases only — citations the walker couldn't statically
    resolve, not citations that failed index lookup).

    The watchfire 0.3.0 index covers PS1/26 (4,498 PS rows) in addition to
    CRR, so PS / PRA Rulebook citations are no longer downgraded to
    warnings the way they were when the index was sparse.
    """
    try:
        from watchfire.checks import run_check
        from watchfire.config import load_config
    except ImportError as exc:
        return ([f"  watchfire not importable: {exc}"], [])

    config = load_config(Path.cwd())
    report = run_check(config)

    fatal: list[str] = []
    warnings: list[str] = []
    for r in report.results:
        location = f"  {r.file}:{r.line}: {r.function}: {r.kind}: {r.message}"
        if r.kind == "unresolved":
            warnings.append(location)
        else:
            fatal.append(location)

    return fatal, warnings


def _run_checks(
    target: Path,
    checks: list[tuple[str, Callable[[Path], list[str]]]],
) -> list[tuple[str, list[str]]]:
    """Run each (name, fn) pair against `target`, returning (name, violations) for failures."""
    all_violations: list[tuple[str, list[str]]] = []
    for name, fn in checks:
        v = fn(target)
        if v:
            all_violations.append((name, v))
    return all_violations


def _print_watchfire_warnings(watchfire_warnings: list[str], leading_blank: bool) -> None:
    """Print the watchfire [WARN] block. When `leading_blank`, emit a blank line first."""
    if not watchfire_warnings:
        return
    if leading_blank:
        print()
    print(
        f"[WARN] watchfire: {len(watchfire_warnings)} soft finding(s) "
        "(PS / PRA Rulebook citations pending upstream index)"
    )
    for w in watchfire_warnings:
        print(w)


def main() -> int:
    argv = sys.argv[1:]
    update_baseline = "--update-baseline" in argv
    positional = [a for a in argv if not a.startswith("--")]
    target = Path(positional[0]) if positional else Path("src/rwa_calc")
    if not target.exists():
        print(f"Error: {target} does not exist")
        return 1

    if update_baseline:
        metrics = write_ratchet_baseline(target)
        print(f"arch_check: wrote ratchet baseline {RATCHET_BASELINE_PATH}")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

    checks = [
        ("from __future__ import annotations", check_future_annotations),
        ("No ABC imports (use Protocol)", check_no_abc),
        ("No .collect().lazy() (use materialise_edge)", check_no_collect_lazy),
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
        (
            "Engine + data/schemas.py modules carry a `References:` docstring block",
            check_module_references,
        ),
        (
            "Architecture-debt ratchet vs scripts/arch_metrics.json",
            check_ratchet_metrics,
        ),
        (
            "Import direction points downward (contracts/engine/reporting/data/domain)",
            check_import_direction,
        ),
        (
            "No empty-LazyFrame sentinels in engine/ (optional frames are None)",
            check_no_empty_frame_sentinels,
        ),
    ]

    all_violations = _run_checks(target, checks)

    watchfire_fatal, watchfire_warnings = check_watchfire_citations()
    if watchfire_fatal:
        all_violations.append(
            (
                "watchfire: malformed or unknown citations",
                watchfire_fatal,
            )
        )

    if not all_violations:
        print("arch_check: all checks passed")
        _print_watchfire_warnings(watchfire_warnings, leading_blank=True)
        return 0

    print("arch_check: VIOLATIONS FOUND\n")
    for name, violations in all_violations:
        print(f"[FAIL] {name}")
        for v in violations:
            print(v)
        print()

    _print_watchfire_warnings(watchfire_warnings, leading_blank=False)
    if watchfire_warnings:
        print()

    total = sum(len(v) for _, v in all_violations)
    print(f"Total: {total} violation(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
