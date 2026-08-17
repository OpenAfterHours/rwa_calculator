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
  a module constant rather than from the mapping it renders. This is a
  write-set-drift guard, **not** the fix for a taint finding — see the note on
  the last gate below before reusing that reasoning anywhere.

References:
- IMPLEMENTATION_PLAN.md P4.56 (link burn-down), P1.309 (anchor sweep)
- CLAUDE.md "The learning loop" — prose that fails twice earns an executable check
- docs/development/escape-log.md — 2026-08-11 note on `pythonsecurity:S8707`;
  commit a5d34c0d on why guarding a taint flow does not clear it; and the
  2026-08-17 entry on why the two `S2083` fixes to the generator missed the
  reported flow entirely
"""

from __future__ import annotations

import subprocess
import sys
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
    """The write set stays declared — the write path must not be a render key.

    Taking the write path from `TARGET_PATHS` rather than from `render_targets()`
    keys means the generator can only ever write files it declares at import
    time, which is worth keeping on its own terms: a bug in the render cannot
    invent a target.

    **This is not a taint fix, whatever the commit that added it says.** It was
    introduced to clear `pythonsecurity:S2083` and did not, twice over. The
    reported flow never mentioned the path — it runs from `_splice`'s
    `read_text` (the file *content*) to the `write_text` *data* argument, so no
    path restructuring could move it, and the finding is accepted in the
    SonarCloud platform instead. Do not cite this gate as evidence that a taint
    finding was closed; fetch the `codeFlows` and read the source. See
    docs/development/escape-log.md (2026-08-17) and the `S6549 / S2083` note in
    sonar-project.properties for the retrieval command.
    """
    # Arrange / Act
    source = GENERATOR.read_text(encoding="utf-8")

    # Assert
    assert "targets.items()" not in source, (
        "scripts/generate_regulatory_tables.py iterates the rendered mapping "
        "again. Take the path from TARGET_PATHS and the content from the mapping, "
        "so the write set stays fixed at import time and the render cannot invent "
        "a target."
    )
    assert "in TARGET_PATHS:" in source, (
        "Nothing iterates TARGET_PATHS any more. The constant is only a write-set "
        "guarantee while it is the thing the write loop walks."
    )
