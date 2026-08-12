"""
Marker wiring for the robustness suite.

Key responsibilities:
- Mark every test under ``tests/robustness/`` ``robustness``, so a new file
  cannot join the suite without the marker that keeps it out of the dev loop.

Hypothesis configuration is NOT here, and that is deliberate
------------------------------------------------------------
The obvious shape — copy ``tests/properties/conftest.py``'s
``register_profile`` / ``load_profile`` block — is a trap, because Hypothesis
profiles are process-global and a ``conftest.py`` is imported during collection
**whether or not its tests are selected**. Registering ``"dev"`` and
``"thorough"`` here would silently REBIND the property suite's profiles of the
same names, and the trailing ``load_profile`` would then set the whole session's
default from whichever conftest imported last. The measured consequence would be
that ``pytest tests/`` — which never runs a single robustness test — quietly ran
``tests/properties/`` at this suite's example budget instead of its own.

So this suite carries its budget as an EXPLICIT ``settings`` object,
``tests/robustness/strategies.py::SEARCH_SETTINGS``, applied per property.
Explicit settings on a ``@given`` take precedence over the global default, so
neither suite can move the other's coverage in either direction, and the
dependency is greppable rather than ambient.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2
- tests/robustness/strategies.py — SEARCH_SETTINGS and its determinism reasoning
"""

from __future__ import annotations

from pathlib import Path

import pytest

#: This suite's directory. Used to scope the marker hook below — see its
#: docstring for why an unscoped hook silently emptied the whole dev loop.
_SUITE_ROOT = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything under ``tests/robustness/`` ``robustness``.

    Applied here rather than as a ``pytestmark`` in each module so that a new
    test file cannot join the suite WITHOUT the marker — which would put it in
    the dev loop, where a search suite does not belong and where its runtime
    would be blamed on whatever change happened to be in flight. The dev-loop
    and CI filters both exclude ``-m robustness``; see ``pyproject.toml``'s
    ``addopts`` and ``.github/workflows/ci.yml``.

    **The path filter is the whole point of the loop body, and omitting it is a
    trap worth stating.** ``pytest_collection_modifyitems`` implemented in a
    SUBDIRECTORY conftest is still called once per session with the ENTIRE
    session's item list — not with this directory's items. The first draft of
    this hook had no filter, and the measured effect was that
    ``pytest tests/`` collected ``no tests collected (12239 deselected)``: every
    test in the repository had been marked ``robustness`` and the dev loop's own
    ``not robustness`` filter then deselected all of it. A green, instant, empty
    suite — the exact silent-absence shape ``.claude/LESSONS.md`` B4 is about,
    and it would have been introduced by the change whose purpose was to keep
    this suite OUT of the dev loop.
    """
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and _SUITE_ROOT in Path(path).parents:
            item.add_marker(pytest.mark.robustness)
