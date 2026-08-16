"""
Docs-freshness gates (2026-08-08 docs-infrastructure batch).

Executable checks that stop the docs estate — and the agent-facing skills —
lying about the code:

- ``docs/data-model/regulatory-tables.md`` is generated from the resolved
  rulepacks by ``scripts/generate_regulatory_tables.py``. A pack edit that
  skips regeneration — or any hand-edit of the page — fails here, because the
  committed page must be byte-identical to a fresh render.
- The same generator fills marked regions inside the ``basel31`` / ``crr``
  skill reference files, so a skill can no longer state a value the pack
  disagrees with. This is a **graduated lesson**: the corporate CQS5 Basel 3.1
  risk weight was stated as 100% in three separate skill files while the pack,
  the engine and PS1/26 Art. 122(2) Table 6 all said 150%, and the QRRE limit
  was stated as GBP 100k against a pack value of GBP 90k.
- ``scripts/check_skill_values.py`` closes the same gap from the other side: a
  percentage written into skill *prose*, outside the generated regions, fails
  unless it carries a justified allowance.
- The docs dead-link count is two-way ratcheted against
  ``scripts/docs_link_baseline.json`` by ``scripts/check_doc_links.py``: a new
  dead link is a regression, and a fixed one must be banked so it cannot
  silently regress back.
- The generator writes only the targets it declares, and takes those paths from
  a module constant rather than from the mapping it renders. That is the same
  taint-source removal as ``check_distribution.py``'s missing ``type=Path``
  argument, one indirection further out.

References:
- IMPLEMENTATION_PLAN.md P4.56 (link burn-down), P1.309 (anchor sweep)
- CLAUDE.md "The learning loop" — prose that fails twice earns an executable check
- docs/development/escape-log.md — 2026-08-11 note on `pythonsecurity:S8707`,
  and commit a5d34c0d on why guarding a taint flow does not clear it
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_regulatory_tables.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Imported rather than driven through the CLI: the two gates below are about the
# generator's *write set*, which the CLI only ever reports a count of.
from generate_regulatory_tables import TARGET_PATHS, render_targets  # noqa: E402


def _run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_regulatory_tables_page_is_fresh() -> None:
    """The page and every skill fragment must match a fresh render of the packs."""
    # Arrange / Act
    result = _run_script("generate_regulatory_tables.py", "--check")

    # Assert
    assert result.returncode == 0, (
        "A generated target no longer matches the resolved rulepacks — this is "
        "docs/data-model/regulatory-tables.md and/or a .claude/skills fragment. "
        "Regenerate (never hand-edit inside the GENERATED markers):\n"
        "  uv run python scripts/generate_regulatory_tables.py\n"
        f"{result.stderr}"
    )


def test_skill_prose_states_no_regulatory_values() -> None:
    """Skills must name pack entries, never restate their values."""
    # Arrange / Act
    result = _run_script("check_skill_values.py", "--check")

    # Assert
    assert result.returncode == 0, (
        "A .claude/skills file states a regulatory value in prose. Skills are read "
        "by every role-agent before it designs a scenario, so a stale copy sends "
        "agents to a number the engine never used:\n"
        f"{result.stderr}"
    )


def test_docs_dead_link_count_matches_baseline() -> None:
    # Arrange / Act
    result = _run_script("check_doc_links.py", "--check")

    # Assert
    assert result.returncode == 0, (
        "Docs dead-link census moved off the baseline. A higher count is a "
        "regression (fix the new dead link); a lower count must be banked:\n"
        "  uv run python scripts/check_doc_links.py --update-baseline\n"
        f"{result.stdout[-2000:]}\n{result.stderr}"
    )


def test_generator_declares_every_target_it_renders() -> None:
    """`TARGET_PATHS` is the generator's write set, so it must not drift.

    The write loop iterates the constant and looks the content up in the render,
    which is what keeps a file-derived value out of the path. The cost of that
    separation is that the two can disagree, and both directions are silent
    failures worth naming: a `FRAGMENTS` entry whose path is missing from
    `TARGET_PATHS` stops being written at all — the skill region simply goes
    stale — while a stale `TARGET_PATHS` entry raises `KeyError` mid-run, after
    earlier targets have already been written.
    """
    # Arrange / Act
    rendered = set(render_targets())

    # Assert
    assert rendered == set(TARGET_PATHS), (
        "scripts/generate_regulatory_tables.py renders a different set of targets "
        "than TARGET_PATHS declares. Only the declared paths are ever written:\n"
        f"  rendered but not declared: {sorted(p.name for p in rendered - set(TARGET_PATHS))}\n"
        f"  declared but not rendered: {sorted(p.name for p in set(TARGET_PATHS) - rendered)}"
    )
    assert len(TARGET_PATHS) == len(set(TARGET_PATHS)), (
        "TARGET_PATHS repeats a path, so one target would be written twice."
    )


def test_generator_write_paths_do_not_come_from_the_rendered_mapping() -> None:
    """The taint source stays removed — the write path must not be a render key.

    `render_targets()` splices its values out of text read off disk, and a taint
    analyser models a mapping as one container: taking the write path out of that
    mapping's keys made `path.write_text(...)` an arbitrary-file-write sink
    (`pythonsecurity:S2083`, which fails the security quality gate). Commit
    a5d34c0d records that guarding such a flow does not clear it — two correct
    resolve-then-contain guards left the finding standing, one multiplying it —
    so the remedy is structural and this asserts the structure, not the guard.

    Scans the *unparsed* tree rather than the raw file. A substring gate over raw
    source cannot tell code from commentary, and this one duly fired on the
    generator's own comment explaining why the mapping must not be iterated —
    a gate that a correct fix's documentation turns red teaches authors to stop
    writing the documentation. `ast.unparse` drops comments, so what is asserted
    here is what the interpreter would actually run.
    """
    # Arrange / Act
    source = ast.unparse(ast.parse(GENERATOR.read_text(encoding="utf-8")))

    # Assert
    assert "targets.items()" not in source, (
        "scripts/generate_regulatory_tables.py iterates the rendered mapping "
        "again. Take the path from TARGET_PATHS and the content from the mapping "
        "— a path that has been inside the mapping is attacker-controlled as far "
        "as the taint engine is concerned (pythonsecurity:S2083)."
    )
    assert "in TARGET_PATHS:" in source, (
        "Nothing iterates TARGET_PATHS any more. The constant is only a security "
        "property while it is the thing the write loop walks."
    )


def test_generator_write_path_is_bound_directly_from_the_constant() -> None:
    """Every `write_text` sits in a `for ... in TARGET_PATHS:` loop, not one removed.

    Graduated after `pythonsecurity:S2083` survived a first structural fix. That
    fix declared `TARGET_PATHS` and stopped iterating `targets.items()` — and the
    prose gate above passed, because the *read* loop walked the constant while
    the write still walked a list of stale paths collected at runtime. Taint
    provenance does not survive append-then-iterate: every element came from the
    constant, but the analyser cannot see that, so the path arriving at the sink
    was unconstrained again and the finding stayed open. The tell was that
    `read_text`, binding its path directly off the constant, was never flagged.

    A substring assertion cannot tell those two shapes apart, which is why this
    walks the syntax tree and pins the binding at the sink itself.
    """
    # Arrange
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    # Act
    sinks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_text"
        and isinstance(node.func.value, ast.Name)
    ]

    # Assert
    assert sinks, (
        "No `<name>.write_text(...)` call found in the generator. Either it stopped "
        "writing, or the sink moved to a shape this gate no longer inspects."
    )
    for sink in sinks:
        receiver = sink.func.value.id  # type: ignore[union-attr]
        binding_loops = [
            node
            for node in _ancestors(sink, parents)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == receiver
        ]
        assert binding_loops, (
            f"`{receiver}.write_text(...)` is not inside a `for {receiver} in ...:` "
            "loop, so the path reaching the sink has no provenance this gate can "
            "confirm (pythonsecurity:S2083)."
        )
        assert all(
            isinstance(loop.iter, ast.Name) and loop.iter.id == "TARGET_PATHS"
            for loop in binding_loops
        ), (
            f"`{receiver}` at the write sink is bound from "
            f"{[ast.unparse(loop.iter) for loop in binding_loops]}, not directly from "
            "TARGET_PATHS. A path that has passed through any runtime container "
            "arrives at the sink unconstrained — provenance does not survive "
            "append-then-iterate — and pythonsecurity:S2083 reopens. See the "
            "TARGET_PATHS comment in the generator."
        )


def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> Iterator[ast.AST]:
    """Walk from `node` up to the module root, nearest enclosing node first."""
    current = parents.get(node)
    while current is not None:
        yield current
        current = parents.get(current)
