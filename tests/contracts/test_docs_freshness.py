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

References:
- IMPLEMENTATION_PLAN.md P4.56 (link burn-down), P1.309 (anchor sweep)
- CLAUDE.md "The learning loop" — prose that fails twice earns an executable check
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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
