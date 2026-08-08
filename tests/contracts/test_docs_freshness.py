"""
Docs-freshness gates (2026-08-08 docs-infrastructure batch).

Two executable checks that stop the docs estate lying about the code:

- ``docs/data-model/regulatory-tables.md`` is generated from the resolved
  rulepacks by ``scripts/generate_regulatory_tables.py``. A pack edit that
  skips regeneration — or any hand-edit of the page — fails here, because the
  committed page must be byte-identical to a fresh render.
- The docs dead-link count is two-way ratcheted against
  ``scripts/docs_link_baseline.json`` by ``scripts/check_doc_links.py``: a new
  dead link is a regression, and a fixed one must be banked so it cannot
  silently regress back.

References:
- IMPLEMENTATION_PLAN.md P4.56 (link burn-down), P1.309 (anchor sweep)
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
    # Arrange / Act
    result = _run_script("generate_regulatory_tables.py", "--check")

    # Assert
    assert result.returncode == 0, (
        "docs/data-model/regulatory-tables.md no longer matches the resolved "
        "rulepacks. Regenerate it (never hand-edit):\n"
        "  uv run python scripts/generate_regulatory_tables.py\n"
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
