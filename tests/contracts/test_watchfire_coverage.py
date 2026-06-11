"""Pin the @cites decorator inventory against accidental drift.

The committed snapshot ``tests/contracts/data/citation_snapshot.json`` maps
``"module::attr_path"`` to the canonical citation list each decorated
function carries (outermost decorator first, matching how watchfire builds
``__watchfire__``). It is generated from the live source tree by
``scripts/generate_citation_matrix.py`` — the same script that renders
``docs/development/citation-matrix.md`` — so there is no hand-maintained
whitelist to keep in sync.

Two protections:

1. ``test_function_carries_expected_citations`` — every snapshot row must
   still resolve to a live function carrying exactly the recorded
   citations. Accidental decorator removal (or a changed citation argument)
   surfaces as a named parameterised failure rather than a silent matrix
   shrink.
2. ``test_live_citation_state_matches_snapshot`` — the live decorator
   inventory must equal the snapshot exactly, so added, moved, or renamed
   ``@cites`` functions are pinned the moment they land.

Changed the decorators deliberately? Regenerate the snapshot (and the docs
matrix page) with::

    uv run python scripts/generate_citation_matrix.py
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "citation_snapshot.json"
REGENERATE_HINT = (
    "If the change is intentional, regenerate the snapshot with: "
    "uv run python scripts/generate_citation_matrix.py"
)


def _load_snapshot() -> dict[str, list[str]]:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


SNAPSHOT: dict[str, list[str]] = _load_snapshot()


def _resolve(module_path: str, attr_path: str) -> Any:
    obj: Any = importlib.import_module(module_path)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def test_snapshot_file_exists() -> None:
    """The committed snapshot must exist and be non-empty."""
    assert SNAPSHOT_PATH.exists(), (
        f"missing citation snapshot {SNAPSHOT_PATH} — generate it with: "
        "uv run python scripts/generate_citation_matrix.py"
    )
    assert SNAPSHOT, f"citation snapshot {SNAPSHOT_PATH} is empty. {REGENERATE_HINT}"


@pytest.mark.parametrize("key", sorted(SNAPSHOT))
def test_function_carries_expected_citations(key: str) -> None:
    """Each snapshot row must resolve to a function carrying the recorded citations.

    Verifies (a) the function still exists, (b) ``__watchfire__`` is
    populated, and (c) every citation round-trips to the expected canonical
    string in decorator order.
    """
    expected = SNAPSHOT[key]
    module_path, attr_path = key.split("::", 1)
    func = _resolve(module_path, attr_path)
    citations = getattr(func, "__watchfire__", ())
    actual = [c.canonical() for c in citations]
    assert actual == expected, (
        f"{module_path}.{attr_path}: expected citations {expected}, got {actual} — "
        f"was the @cites decorator removed or its argument changed? {REGENERATE_HINT}"
    )


def test_live_citation_state_matches_snapshot() -> None:
    """The live @cites inventory must equal the committed snapshot exactly.

    Catches both directions of drift: decorators removed without
    regenerating (coverage shrank) and decorators added/moved without
    regenerating (snapshot stale).
    """
    from scripts.generate_citation_matrix import collect_citation_state

    live = collect_citation_state()

    removed = sorted(set(SNAPSHOT) - set(live))
    added = sorted(set(live) - set(SNAPSHOT))
    changed = sorted(key for key in set(SNAPSHOT) & set(live) if SNAPSHOT[key] != live[key])

    problems: list[str] = []
    if removed:
        problems.append("functions in snapshot but no longer cited (coverage shrank):")
        problems.extend(f"  - {key}: {SNAPSHOT[key]}" for key in removed)
    if added:
        problems.append("cited functions missing from snapshot (new/moved decorators):")
        problems.extend(f"  - {key}: {live[key]}" for key in added)
    if changed:
        problems.append("functions whose citations changed:")
        problems.extend(
            f"  - {key}: snapshot {SNAPSHOT[key]} != live {live[key]}" for key in changed
        )

    assert not problems, (
        "live @cites state diverges from tests/contracts/data/citation_snapshot.json\n"
        + "\n".join(problems)
        + f"\n{REGENERATE_HINT}"
    )
