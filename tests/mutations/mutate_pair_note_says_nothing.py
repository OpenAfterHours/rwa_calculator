"""Isolating mutation: the pair table's note emptied -- a silent cap.

``_pair_note`` is the only thing on the page that says the table is not the
whole population: how much the shown rows carry, how much the scope carries, and
how many exposures are not on the page at all. Emptied, the page renders a
perfectly correct table of 25 rows and nothing whatever says that 14 more
exposures exist. A cap that does not admit to itself hides money exactly as a
silent zero does, and the table LOOKS complete either way -- there is no visual
tell, which is why this needs an assertion rather than a reviewer.

Changes ONE thing: the note string. The table, its ranking, its cap and its
arithmetic are the module's own and are untouched.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_pair_note_says_nothing
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _the_cap_stops_saying_what_it_hid():
    import rwa_calc.ui.views.return_recon as module

    original = module._pair_note

    def _silent(table, label):  # noqa: ANN001, ANN202
        return ""

    module._pair_note = _silent
    try:
        yield
    finally:
        module._pair_note = original
