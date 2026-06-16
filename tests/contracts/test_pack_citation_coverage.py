"""
Pack-data citation coverage contract — the watchfire-validation analogue.

Mirrors ``tests/contracts/test_watchfire_coverage.py`` but for the rulepack:
every resolved-pack ``Citation`` must parse under watchfire and be covered by
the bundled index (or be a documented ``PACK_CITATION_SOFT_ALLOWLIST`` gap).
Guards against (a) a pack citation drifting to an unparseable / uncovered form
as values move into the packs and (b) the distinct-citation count silently
shrinking (a density ratchet — it may grow but never drop).

The validation logic lives in ``scripts/arch_check.py::check_pack_citations``
(the single source, also run by the architectural gate); this test exercises
the same function so a regression surfaces in the pytest run too, not only in
arch_check.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

from rwa_calc.rulebook.audit import pack_citation_index

REPO_ROOT = Path(__file__).resolve().parents[2]

# Density-ratchet floor: distinct pack citations may grow (the Phase 5 table-move
# adds many) but never drop below this. Raise it (never lower without a recorded
# reason) as coverage grows.
MIN_PACK_CITATIONS = 69


def _load_arch_check():
    """Load scripts/arch_check.py as a module without polluting sys.path."""
    script_path = REPO_ROOT / "scripts" / "arch_check.py"
    spec = importlib.util.spec_from_file_location("_arch_check", script_path)
    assert spec is not None and spec.loader is not None, f"cannot load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check"] = module
    spec.loader.exec_module(module)
    return module


def test_every_pack_citation_parses_and_is_covered() -> None:
    """No fatal pack-citation finding: every citation parses, names a known
    instrument, and is index-covered (or a documented soft-allowlist gap)."""
    arch_check = _load_arch_check()
    fatal, _warnings = arch_check.check_pack_citations()
    assert not fatal, "unparseable / uncovered pack citation(s):\n" + "\n".join(fatal)


def test_pack_citation_count_does_not_shrink() -> None:
    """Density ratchet: the distinct-citation count may grow but not shrink."""
    index = pack_citation_index(date(2026, 1, 1))
    assert len(index) >= MIN_PACK_CITATIONS, (
        f"distinct pack citations {len(index)} dropped below floor {MIN_PACK_CITATIONS} — "
        "a citation was removed or merged; lower the floor only with a recorded reason"
    )
