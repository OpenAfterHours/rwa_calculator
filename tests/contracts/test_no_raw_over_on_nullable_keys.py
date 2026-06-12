"""Contract test: no raw ``.over(<nullable_key>)`` outside the helper.

Polars ``.over(key)`` collapses ALL null-keyed rows into a single partition,
so an unguarded window aggregate on a nullable column silently pools
unrelated rows. The :func:`partition_by_nullable` helper in
``rwa_calc.engine.utils`` is the canonical guard.

This test walks every ``*.py`` file under ``src/rwa_calc/engine/``,
parses it with ``ast``, and flags any ``.over(...)`` call whose first
positional argument or ``partition_by`` keyword argument is a string
literal that matches the engine's nullable-key set
(``rwa_calc.engine.utils.NULLABLE_PARTITION_KEYS``). Non-constant first
arguments (variables, ``pl.col(...)``, splats) are flagged as ambiguous —
they MUST either use the helper or be added to the allowlist with
justification.

The helper file itself is the only allowlist entry by default. New
exemptions require a deliberate, reviewed addition.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rwa_calc.engine.utils import NULLABLE_PARTITION_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "src" / "rwa_calc" / "engine"

# Files exempt from the rule. The helper itself defines the canonical
# guarded form, so its own ``.over`` calls are by construction the safe
# ones. New entries here MUST carry a justification comment.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # The guard helper itself — defines the canonical pattern.
        "utils.py",
    }
)

# Line-level allowlist for ``.over(<nullable_key>)`` calls that are provably
# safe in their context (e.g. an upstream ``filter(key.is_not_null())``).
# Format: ``{relative_posix_path: frozenset[int]}``. Each entry MUST carry a
# justification comment naming the filter or invariant that makes the key
# non-null at this site.
LINE_ALLOWLIST: dict[str, frozenset[int]] = {
    # _build_rating_inheritance_lazy: the per_agency_latest filter adds
    # `counterparty_reference.is_not_null()` to the upstream filter, so these
    # `.over("counterparty_reference")` calls operate on a frame with no
    # null-keyed rows. See the comment block above the per_agency_latest
    # filter in engine/hierarchy.py.
    "src/rwa_calc/engine/hierarchy.py": frozenset({433, 434}),
}


class _OverVisitor(ast.NodeVisitor):
    """Collect ``.over(...)`` call sites that risk null-partition collapse.

    Tracks ``partition_by_nullable(...)`` enclosing calls so that ``.over``
    expressions passed as arguments to the helper (the helper's contract is
    that ``agg_expr`` already contains its own ``.over(key)``) are not
    flagged as raw uses.
    """

    def __init__(self, allowed_lines: frozenset[int]) -> None:
        self.violations: list[tuple[int, str]] = []
        self._helper_call_depth: int = 0
        self._allowed_lines = allowed_lines

    def _flag(self, lineno: int, message: str) -> None:
        if self._helper_call_depth > 0:
            return  # ``.over`` inside partition_by_nullable(...) — by-design
        if lineno in self._allowed_lines:
            return  # explicit line-level exemption
        self.violations.append((lineno, message))

    def _flag_arg(self, lineno: int, value: object, position: str) -> None:
        if isinstance(value, str) and value in NULLABLE_PARTITION_KEYS:
            self._flag(lineno, f".over({position}={value!r}) — use partition_by_nullable")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 (ast API)
        # Detect ``partition_by_nullable(...)`` enclosing calls so we don't
        # double-flag the ``.over`` expressions the helper expects as args.
        is_helper = isinstance(node.func, ast.Name) and node.func.id == "partition_by_nullable"
        if is_helper:
            self._helper_call_depth += 1
        try:
            # Match ``<expr>.over(...)`` calls only.
            if isinstance(node.func, ast.Attribute) and node.func.attr == "over":
                self._check_over_call(node)
            self.generic_visit(node)
        finally:
            if is_helper:
                self._helper_call_depth -= 1

    def _check_over_call(self, node: ast.Call) -> None:
        """Flag risky partition keys in a matched ``<expr>.over(...)`` call."""
        # All positional args are partition keys; check each.
        for idx, arg in enumerate(node.args):
            if isinstance(arg, ast.Constant):
                self._flag_arg(node.lineno, arg.value, f"arg[{idx}]")
            else:
                # Variables, pl.col(...), splats — ambiguous from a static AST
                # view. Flag so the author has to opt in via the helper.
                self._flag(
                    node.lineno,
                    f".over(<non-constant arg[{idx}]>) — "
                    "use partition_by_nullable or move to allowlist",
                )
        # Keyword form: ``.over(partition_by="...")``.
        for kw in node.keywords:
            if kw.arg == "partition_by" and isinstance(kw.value, ast.Constant):
                self._flag_arg(node.lineno, kw.value.value, "partition_by")
            elif kw.arg == "partition_by":
                self._flag(
                    node.lineno,
                    ".over(partition_by=<non-constant>) — "
                    "use partition_by_nullable or move to allowlist",
                )


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, message)`` violations found in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(REPO_ROOT).as_posix()
    visitor = _OverVisitor(LINE_ALLOWLIST.get(rel, frozenset()))
    visitor.visit(tree)
    return visitor.violations


def _engine_files() -> list[Path]:
    """All ``.py`` files under ``src/rwa_calc/engine/``."""
    return sorted(p for p in ENGINE_ROOT.rglob("*.py") if p.is_file())


def test_engine_root_exists() -> None:
    """Sanity: the engine directory and helper file are where we expect."""
    assert ENGINE_ROOT.is_dir()
    assert (ENGINE_ROOT / "utils.py").is_file()


def test_no_raw_over_on_nullable_keys() -> None:
    """No ``.over(<nullable_key>)`` outside the ``partition_by_nullable`` helper.

    ``.over()`` collapses null-keyed rows into a single partition, silently
    pooling unrelated exposures into pro-rata aggregates. Any window
    aggregate on a nullable key must use ``partition_by_nullable`` from
    ``rwa_calc.engine.utils``.
    """
    all_violations: list[str] = []
    for path in _engine_files():
        if path.name in ALLOWLIST:
            continue
        for lineno, message in _scan_file(path):
            rel = path.relative_to(REPO_ROOT).as_posix()
            all_violations.append(f"{rel}:{lineno}: {message}")

    assert not all_violations, (
        "Raw .over(<nullable_key>) found outside partition_by_nullable. "
        "Wrap with rwa_calc.engine.utils.partition_by_nullable, or — if the "
        "key is provably non-null in this context — add the file to ALLOWLIST "
        "in tests/contracts/test_no_raw_over_on_nullable_keys.py with a "
        "justification comment.\n\nViolations:\n  " + "\n  ".join(all_violations)
    )


@pytest.mark.parametrize("nullable_key", sorted(NULLABLE_PARTITION_KEYS))
def test_nullable_key_set_is_documented(nullable_key: str) -> None:
    """Each nullable key is documented in the helper's docstring."""
    helper_src = (ENGINE_ROOT / "utils.py").read_text(encoding="utf-8")
    assert nullable_key in helper_src, (
        f"Nullable partition key {nullable_key!r} is not mentioned in "
        f"engine/utils.py — keep the docstring's enumeration in sync with "
        f"NULLABLE_PARTITION_KEYS."
    )
