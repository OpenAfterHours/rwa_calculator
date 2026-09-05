"""Contract test for arch_check check 21 — no nested Polars window expressions.

Polars evaluates a window function's INPUT inside the outer group-by context.
So an expression of the form::

    inner.max().over(["cp", "fac"]).sum().over("cp")

re-runs the inner window once per outer group. The cost stops being a function
of row count alone and becomes a function of row count times group count, which
looks fine on a fixture and catastrophic on a book.

This is the executable form of a defect that shipped. Commit ``8ec7d302``
(P1.320) put two windows into the input of a third in
``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``; the
classify stage went from 0.5 s to 5.6 s at 374k rows and stayed that way from
v0.3.27 to v0.3.32. Nothing in the estate could see it: every correctness gate
was green, and the benchmark job is deselected from both the dev loop and the
CI test job.

The check's contract, which the implementation must honour
----------------------------------------------------------
``scripts/arch_check.py`` defines::

    check_no_nested_window_expressions(path: Path) -> list[str]

- ``path`` is a PACKAGE ROOT (``src/rwa_calc``), matching every sibling check.
  The scan covers ``path / "engine"`` recursively, and returns ``[]`` when that
  directory does not exist.
- Each returned string identifies one offending OUTER ``.over(...)`` call and
  contains the file path and its line number, in the ``"  {file}:{line}: ..."``
  shape the other checks use.
- Detection follows a local-name binding in the same function body: the shipped
  defect binds the nested-window expression to a local first and only then
  applies the outer window, so a scan that looks at one expression node in
  isolation cannot see it.
- The check is registered in ``main()``'s ``checks`` list, so
  ``uv run python scripts/arch_check.py`` reports it like any other check.

The tests below exercise the function directly with tmp-file samples (the same
pattern as ``test_arch_migration_gates.py``, which loads the script by path
rather than importing it), and separately assert the registration by parsing
``main()``.

References:
- ``.claude/LESSONS.md`` B9: an alarm that fires on everything carries no
  information — hence the two must-not-flag samples and the real-file control.
- ``.claude/LESSONS.md`` C11: a control is only a control while it can still
  express the condition — hence the adequacy assertions on each sample.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "rwa_calc"
ARCH_CHECK_PATH = REPO_ROOT / "scripts" / "arch_check.py"

_CHECK_NAME = "check_no_nested_window_expressions"

#: A check known to be registered today. Used as an adequacy control on the
#: registration test: if the extraction below stops finding THIS name, the
#: registration test has stopped measuring registration.
_KNOWN_REGISTERED_CHECK = "check_no_polars_namespace_registrations"

#: The engine module whose expression the check exists to flag.
_DEFECT_MODULE = SRC_ROOT / "engine" / "classify" / "subtypes.py"

#: A real engine module carrying a SINGLE, non-nested ``.over()`` that a naive
#: name resolver mis-flags: the statement applying the window rebinds the frame
#: name (``exposures = exposures.with_columns(... .over(...) ...)``), and the
#: window's receiver reaches that same name through a chain of local bindings
#: (``drawn_in_e_star`` -> ``drawn_expr`` -> ``has_drawn`` -> ``names`` ->
#: ``schema`` -> ``exposures``). Resolving bindings without respecting source
#: order makes the outer window find ITSELF and reports a violation that is not
#: there. This module is the control that pins the difference.
_FALSE_POSITIVE_CONTROL = SRC_ROOT / "engine" / "supporting_factors.py"


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

#: (a) Direct nesting — both windows in one expression, no local binding.
SAMPLE_DIRECT_NESTING = '''\
"""Sample: a window nested directly in another window's input."""

from __future__ import annotations

import polars as pl


def direct_nesting(group_limit: pl.Expr) -> pl.Expr:
    """The inner .over runs once per outer group."""
    return group_limit.max().over("parent_facility_reference").sum().over("counterparty_reference")
'''

#: (b) The shipped shape — the nesting only exists once the local binding is
#: followed. This is a faithful reduction of
#: ``qrre_obligor_aggregate_limit_expr`` at commit 8ec7d302.
SAMPLE_LOCAL_BINDING = '''\
"""Sample: the shipped P1.320 shape — nesting through a local name."""

from __future__ import annotations

import polars as pl

from rwa_calc.engine.utils import partition_by_nullable


def obligor_aggregate(candidate: pl.Expr, limit: pl.Expr, cand_limit: pl.Expr) -> pl.Expr:
    """One contribution per (obligor, facility), summed per obligor."""
    keys = ["counterparty_reference", "parent_facility_reference"]
    deduped_limit = (
        pl.when(candidate)
        .then(
            partition_by_nullable(
                pl.when(candidate.cast(pl.UInt32).cum_sum().over(keys) == 1)
                .then(cand_limit.max().over(keys))
                .otherwise(pl.lit(0.0)),
                "parent_facility_reference",
                limit,
            )
        )
        .otherwise(pl.lit(0.0))
    )
    return partition_by_nullable(
        deduped_limit.sum().over("counterparty_reference"),
        "counterparty_reference",
        cand_limit,
    )
'''

#: (c) The two-step fix — the inner result becomes a helper COLUMN in a
#: preceding ``with_columns``, so the outer window's input is a plain
#: ``pl.col()`` read. Must NOT be flagged, or the check bans its own remedy.
SAMPLE_TWO_STEP = '''\
"""Sample: the two-step remedy — helper column, then a plain window."""

from __future__ import annotations

import polars as pl

from rwa_calc.engine.utils import partition_by_nullable


def obligor_aggregate(
    exposures: pl.LazyFrame,
    candidate: pl.Expr,
    limit: pl.Expr,
    cand_limit: pl.Expr,
) -> pl.LazyFrame:
    """Same result, evaluated once per row instead of once per group."""
    keys = ["counterparty_reference", "parent_facility_reference"]
    deduped_limit = (
        pl.when(candidate)
        .then(
            partition_by_nullable(
                pl.when(candidate.cast(pl.UInt32).cum_sum().over(keys) == 1)
                .then(cand_limit.max().over(keys))
                .otherwise(pl.lit(0.0)),
                "parent_facility_reference",
                limit,
            )
        )
        .otherwise(pl.lit(0.0))
    )
    with_helper = exposures.with_columns(deduped_limit.alias("_qrre_deduped_limit"))
    return with_helper.with_columns(
        partition_by_nullable(
            pl.col("_qrre_deduped_limit").sum().over("counterparty_reference"),
            "counterparty_reference",
            cand_limit,
        ).alias("obligor_aggregate_limit")
    ).drop("_qrre_deduped_limit")
'''

#: (d) Two sibling windows in one ``with_columns`` — neither is in the other's
#: input. Must NOT be flagged; banning this would ban the ordinary use.
SAMPLE_SIBLING_WINDOWS = '''\
"""Sample: two independent windows in one with_columns."""

from __future__ import annotations

import polars as pl


def sibling_windows(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Neither window appears in the other's input."""
    return exposures.with_columns(
        pl.col("facility_limit").max().over("counterparty_reference").alias("cp_max_limit"),
        pl.col("ead").sum().over("counterparty_reference").alias("cp_total_ead"),
    )
'''

# ---------------------------------------------------------------------------
# (e) and (f) — the same local name bound TWICE.
#
# These two are a matched pair, and only the pair pins the rule. Between them
# they differ in exactly one thing: which of the two bindings carries a window.
# A resolver that picks the wrong binding gets BOTH wrong, in opposite
# directions, so a check that passes one and fails the other has not chosen a
# rule at all - it has chosen a coin flip that happens to land right once.
#
# The rule that satisfies both: a name resolves to the LAST binding whose
# statement ENDS STRICTLY BEFORE the outer window's own line. That is what
# Python does at runtime, and it is the only reading under which (e) nests and
# (f) does not.
# ---------------------------------------------------------------------------

#: (e) The window arrives on the SECOND binding. Must be flagged: by the time
#: the outer window runs, the name holds a windowed expression.
SAMPLE_REBOUND_NAME = '''\
"""Sample: the nested window arrives on the second binding of a name."""

from __future__ import annotations

import polars as pl


def rebound_name(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """``group_limit`` is a plain column when first bound and a window when rebound."""
    group_limit = pl.col("facility_limit")
    group_limit = pl.col("facility_limit").max().over("parent_facility_reference")
    return exposures.with_columns(
        group_limit.sum().over("counterparty_reference").alias("obligor_aggregate_limit")
    )
'''

#: (f) The window is on the FIRST binding, materialised as a helper column, and
#: the name is then rebound to a plain read of that column. Must NOT be
#: flagged: this is sample (c)'s remedy written through one reused name.
SAMPLE_REUSED_NAME_TWO_STEP = '''\
"""Sample: the two-step remedy written through a single reused local name."""

from __future__ import annotations

import polars as pl


def reused_name(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """The window is materialised, then read back through the same name."""
    contribution = pl.col("facility_limit").max().over("parent_facility_reference")
    exposures = exposures.with_columns(contribution.alias("_deduped_limit"))
    contribution = pl.col("_deduped_limit")
    return exposures.with_columns(
        contribution.sum().over("counterparty_reference").alias("obligor_aggregate_limit")
    ).drop("_deduped_limit")
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_arch_check():
    """Load scripts/arch_check.py as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location("_arch_check", ARCH_CHECK_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {ARCH_CHECK_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def _nested_window_check():
    """Return the check function, failing on an ASSERTION when it is absent.

    ``getattr`` rather than attribute access so a missing check reports as a
    failure with the contract in the message, not as an ``AttributeError``
    traceback that says nothing about what to build.
    """
    arch_check = _load_arch_check()
    check = getattr(arch_check, _CHECK_NAME, None)
    assert check is not None, (
        f"scripts/arch_check.py does not define {_CHECK_NAME}(path: Path) -> list[str]. "
        "Check 21 bans a Polars `.over()` inside the input of another "
        "`.over()`-bearing aggregate anywhere under src/rwa_calc/engine/, "
        "including through a local-name binding in the same function body. "
        "See this module's docstring for the full contract."
    )
    return check


def _scan_sample(tmp_path: Path, name: str, source: str) -> list[str]:
    """Write ``source`` into a throwaway package root and run the check on it."""
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir(parents=True, exist_ok=True)
    (engine_dir / f"{name}.py").write_text(source, encoding="utf-8")
    check = _nested_window_check()
    violations = check(tmp_path)
    assert isinstance(violations, list), (
        f"{_CHECK_NAME} must return a list of violation strings, got {type(violations)!r}"
    )
    return violations


def _self_rebinding_window_lines(path: Path) -> list[int]:
    """Lines where an assignment REBINDS its own target and contains ``.over``.

    This is the exact shape that traps a name resolver which ignores source
    order: following the receiver's bindings eventually reaches the frame name,
    whose latest binding is the statement holding the outer window itself.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value_names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
        has_over = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "over"
            for n in ast.walk(node.value)
        )
        if target.id in value_names and has_over:
            found.append(node.lineno)
    return found


def _name_bindings(source: str, function_name: str, name: str) -> list[tuple[int, bool]]:
    """``(end_line, carries_a_window)`` per assignment to ``name``, in SOURCE order.

    Read from the sample's own AST rather than asserted as a literal, so the
    adequacy checks below describe whatever the sample actually says. A sample
    edited until it no longer binds the name twice, or until both bindings
    carry a window, stops discriminating - and these tests then fail on the
    adequacy assertion with the reason, instead of passing vacuously
    (LESSONS C11).
    """
    tree = ast.parse(source)
    function = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function_name),
        None,
    )
    assert function is not None, f"the sample no longer defines {function_name}()"
    bindings: list[tuple[int, bool]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != name:
            continue
        carries_window = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "over"
            for n in ast.walk(node.value)
        )
        bindings.append((node.end_lineno or node.lineno, carries_window))
    return sorted(bindings)


# ---------------------------------------------------------------------------
# The check exists and is wired in
# ---------------------------------------------------------------------------


def test_arch_check_defines_the_nested_window_check() -> None:
    """scripts/arch_check.py exposes check_no_nested_window_expressions."""
    # Arrange / Act / Assert
    assert _nested_window_check() is not None


def test_nested_window_check_is_registered_in_the_arch_check_run() -> None:
    """The check is in ``main()``'s checks list, so the CLI gate reports it.

    A check function nobody calls is a guard that was built and never wired -
    the estate's dominant meta-pattern, and the reason arch_check grew check 20.
    Asserted by parsing ``main()`` rather than grepping the file, so a mention
    in a docstring or a comment cannot satisfy it.
    """
    # Arrange
    tree = ast.parse(ARCH_CHECK_PATH.read_text(encoding="utf-8"))
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None, "scripts/arch_check.py no longer defines main()"

    # Act
    referenced = {n.id for n in ast.walk(main_fn) if isinstance(n, ast.Name)}

    # Assert — adequacy first: the extraction still sees a known registration.
    assert _KNOWN_REGISTERED_CHECK in referenced, (
        f"{_KNOWN_REGISTERED_CHECK} is registered today but this test cannot "
        "see it, so main() no longer dispatches checks as bare name references "
        "and this assertion has stopped measuring registration - repoint it"
    )
    assert _CHECK_NAME in referenced, (
        f"{_CHECK_NAME} is not referenced in scripts/arch_check.py::main(), so "
        "`uv run python scripts/arch_check.py` never runs it. Add it to the "
        "`checks` list with a name like 'No nested Polars window expressions "
        "in engine/ (compute the inner window as its own column)'."
    )


# ---------------------------------------------------------------------------
# Must be flagged
# ---------------------------------------------------------------------------


def test_directly_nested_window_is_flagged(tmp_path: Path) -> None:
    """``x.max().over(k).sum().over(cp)`` is a violation."""
    # Arrange / Act
    violations = _scan_sample(tmp_path, "direct_nesting", SAMPLE_DIRECT_NESTING)

    # Assert
    assert violations, (
        "a window applied directly to the result of another window was not "
        "flagged - Polars re-evaluates the inner window once per outer group"
    )
    assert any("direct_nesting.py" in v for v in violations), (
        f"violation does not name the offending file: {violations}"
    )


def test_nested_window_through_a_local_binding_is_flagged(tmp_path: Path) -> None:
    """The shipped P1.320 shape is a violation, reached via the local name.

    Adequacy (LESSONS C11): the sample is only proof that the check FOLLOWS the
    binding while no single source line carries both windows. If a reformat
    ever collapses them onto one line, a line-local scan would catch it and
    this test would stop proving anything about binding resolution.
    """
    # Arrange
    lines = SAMPLE_LOCAL_BINDING.splitlines()
    assert not any(line.count(".over(") > 1 for line in lines), (
        "the sample now carries two .over( calls on one line, so a line-local "
        "scan would find it and this test no longer proves the check resolves "
        "the local binding"
    )
    assert sum(line.count(".over(") for line in lines) >= 2, (
        "the sample no longer contains two windows and cannot express nesting"
    )

    # Act
    violations = _scan_sample(tmp_path, "local_binding", SAMPLE_LOCAL_BINDING)

    # Assert
    assert violations, (
        "the shipped P1.320 shape was not flagged: the outer "
        "`deduped_limit.sum().over(...)` takes its input from a LOCAL NAME "
        "whose bound expression contains two windows. A check that only "
        "inspects one expression node in isolation cannot see this, and this "
        "is the exact shape that reached production"
    )
    assert any("local_binding.py" in v for v in violations), (
        f"violation does not name the offending file: {violations}"
    )


def test_nested_window_through_a_rebound_name_is_flagged(tmp_path: Path) -> None:
    """A name REBOUND to a windowed expression still nests.

    The name is bound twice and only the LATER binding carries a window, so the
    check sees the nesting only if it resolves the name to its last binding
    before the outer window's line. Resolve to the first and the violation
    disappears: a real nested window ships, silently, past a green gate.
    """
    # Arrange — adequacy: two bindings, window on the SECOND one.
    bindings = _name_bindings(SAMPLE_REBOUND_NAME, "rebound_name", "group_limit")
    assert len(bindings) == 2, (
        f"the sample binds 'group_limit' {len(bindings)} time(s), not 2, so it "
        "no longer exercises binding ORDER and this test proves nothing"
    )
    assert bindings[0][1] is False and bindings[1][1] is True, (
        "the sample must carry its window on the LATER binding only "
        f"(got carries_window={[carries for _, carries in bindings]}); with a "
        "window on both bindings, or on the earlier one, a resolver that picks "
        "either binding passes and the control cannot discriminate"
    )

    # Act
    violations = _scan_sample(tmp_path, "rebound_name", SAMPLE_REBOUND_NAME)

    # Assert
    assert violations, (
        "a window nested through the SECOND binding of a local name was not "
        "flagged. The name resolves to its first binding, which is a plain "
        "pl.col() and carries no window, so the nesting is invisible. "
        "_local_name_bindings collects bindings in _scope_owned_nodes order, "
        "and that is a stack walk, so the list is in REVERSE source order "
        "while _resolve_binding's `candidates[-1]` assumes source order. Sort "
        "the candidates by end line, or have _scope_owned_nodes yield in "
        "source order. See the matched sibling "
        "test_two_step_remedy_through_a_reused_name_is_not_flagged: the two "
        "fail in opposite directions and only the last-binding rule satisfies "
        "both"
    )
    assert any("rebound_name.py" in v for v in violations), (
        f"violation does not name the offending file: {violations}"
    )


def test_engine_has_no_nested_window_expressions() -> None:
    """No ``.over()`` sits in another ``.over()``'s input under engine/.

    This is the durable gate, and it is the red-on-HEAD evidence: at the time
    of writing it fails naming
    ``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``, the
    expression that shipped the v0.3.27-v0.3.32 slowdown. It goes green when
    that expression is rewritten to compute its deduplicated per-leg
    contribution as its own column.
    """
    # Arrange
    check = _nested_window_check()

    # Act
    violations = check(SRC_ROOT)

    # Assert
    assert not violations, (
        "Nested Polars window expression in engine/ - Polars evaluates a "
        "window's input inside the outer group-by context, so the inner "
        "window re-runs once per outer group and per-row cost becomes a "
        "function of row count. Compute the inner result as its own column in "
        "a preceding with_columns and read it back with pl.col():\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Must NOT be flagged — the check's discriminating power
# ---------------------------------------------------------------------------


def test_two_step_helper_column_is_not_flagged(tmp_path: Path) -> None:
    """The remedy must pass, or the check bans the only way out of it."""
    # Arrange / Act
    violations = _scan_sample(tmp_path, "two_step", SAMPLE_TWO_STEP)

    # Assert
    assert not violations, (
        "the two-step remedy was flagged. The inner window is materialised as "
        "a helper column by a preceding with_columns, and the outer window's "
        "input is a plain pl.col() read - there is no nesting here. A check "
        "that flags this leaves no compliant way to write the expression:\n" + "\n".join(violations)
    )


def test_two_step_remedy_through_a_reused_name_is_not_flagged(tmp_path: Path) -> None:
    """The remedy still passes when it reuses one local name for both steps.

    Same remedy as ``test_two_step_helper_column_is_not_flagged``, written with
    the helper expression and the column read bound to the SAME name. The name
    is bound twice and only the EARLIER binding carries a window, so a check
    that resolves the name to its first binding rejects a correct fix. This is
    the direction that costs a working engineer a day: the gate demands a
    rewrite of code that is already right.
    """
    # Arrange — adequacy: two bindings, window on the FIRST one only.
    bindings = _name_bindings(SAMPLE_REUSED_NAME_TWO_STEP, "reused_name", "contribution")
    assert len(bindings) == 2, (
        f"the sample binds 'contribution' {len(bindings)} time(s), not 2, so it "
        "no longer exercises binding ORDER and this test proves nothing"
    )
    assert bindings[0][1] is True and bindings[1][1] is False, (
        "the sample must carry its window on the EARLIER binding only "
        f"(got carries_window={[carries for _, carries in bindings]}); this is "
        "what makes it the mirror of the rebound-name control, and without the "
        "mirror a resolver could satisfy one of the two by luck"
    )

    # Act
    violations = _scan_sample(tmp_path, "reused_name", SAMPLE_REUSED_NAME_TWO_STEP)

    # Assert
    assert not violations, (
        "the two-step remedy was flagged because it reuses one local name. By "
        "the time the outer window runs, the name holds pl.col('_deduped_limit'), "
        "a plain column read; the windowed expression it held earlier was "
        "already materialised by the intervening with_columns. The name "
        "resolves to its FIRST binding instead of its last: "
        "_local_name_bindings collects in _scope_owned_nodes order, which is a "
        "stack walk and therefore reverse source order, while "
        "_resolve_binding's `candidates[-1]` assumes source order. Sort the "
        "candidates by end line, or have _scope_owned_nodes yield in source "
        "order:\n" + "\n".join(violations)
    )


def test_sibling_windows_in_one_with_columns_are_not_flagged(tmp_path: Path) -> None:
    """Two independent windows in one ``with_columns`` are ordinary use."""
    # Arrange / Act
    violations = _scan_sample(tmp_path, "sibling_windows", SAMPLE_SIBLING_WINDOWS)

    # Assert
    assert not violations, (
        "two windows that appear side by side in one with_columns were "
        "flagged. Neither is in the other's input; banning this would ban "
        "the ordinary use of .over() across the engine:\n" + "\n".join(violations)
    )


def test_single_window_reached_through_a_binding_chain_is_not_flagged() -> None:
    """A real engine module with one non-nested window stays clean.

    ``engine/supporting_factors.py`` is the production control for the
    false-positive that a naive implementation produces. Its single window is
    applied in a statement that REBINDS the frame name, and the window's
    receiver reaches that same name through a chain of local bindings, so a
    resolver that ignores source order makes the window find itself.

    Adequacy (LESSONS C11): the control is only a control while that shape is
    still in the file, so the shape is asserted from the file's own AST rather
    than assumed.
    """
    # Arrange
    assert _FALSE_POSITIVE_CONTROL.is_file(), (
        f"{_FALSE_POSITIVE_CONTROL} has moved - repoint the false-positive control"
    )
    trap_lines = _self_rebinding_window_lines(_FALSE_POSITIVE_CONTROL)
    assert trap_lines, (
        f"{_FALSE_POSITIVE_CONTROL.name} no longer contains a self-rebinding "
        "assignment whose value carries a .over() call, so it can no longer "
        "trap a source-order-blind resolver and has stopped being a control. "
        "Find another module with that shape, or drop this test deliberately"
    )
    check = _nested_window_check()

    # Act
    violations = check(SRC_ROOT)
    flagged = [v for v in violations if _FALSE_POSITIVE_CONTROL.name in v]

    # Assert
    assert not flagged, (
        f"{_FALSE_POSITIVE_CONTROL.name} was flagged, but its windows are not "
        f"nested - the only .over() sites are single windows (self-rebinding "
        f"assignments at line(s) {trap_lines}). Resolve a local name to the "
        "last binding that ENDS STRICTLY BEFORE the outer .over()'s own line, "
        "so the statement applying the window cannot be followed back into "
        "itself:\n" + "\n".join(flagged)
    )


@pytest.mark.parametrize(
    ("name", "source"),
    [("two_step", SAMPLE_TWO_STEP), ("sibling_windows", SAMPLE_SIBLING_WINDOWS)],
    ids=["two_step", "sibling_windows"],
)
def test_a_clean_engine_tree_returns_no_violations(tmp_path: Path, name: str, source: str) -> None:
    """The check returns an empty list, not a truthy sentinel, when clean."""
    # Arrange / Act
    violations = _scan_sample(tmp_path, name, source)

    # Assert
    assert violations == [], f"expected [] for a clean tree, got {violations}"
