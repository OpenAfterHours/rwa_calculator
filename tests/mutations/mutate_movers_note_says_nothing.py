"""Isolating mutation: the drill-down's note emptied.

``_movers_note`` is the only thing on the panel that distinguishes three states
a reader cannot otherwise tell apart: a complete list, a capped one, and a pair
NO LEG OCCUPIES. Emptied, a capped list renders 25 perfectly correct rows with
nothing saying more legs exist, and an empty panel renders as a blank — which
reads as "nothing moved between these rows" when the truth is "that is not a
cell of this matrix".

Both failures are the same one the pair table already paid for: a cap that does
not admit to itself hides money exactly as a silent zero does, and there is no
visual tell either way.

Changes ONE thing: the note string. The list, its ranking, its cap and the
``shown`` / ``total`` / ``hidden`` counts are the module's own.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_movers_note_says_nothing
"""

from __future__ import annotations

import pytest

_APPLIED = [0]


@pytest.fixture(autouse=True)
def _the_drill_down_stops_saying_what_it_hid():
    import rwa_calc.ui.views.return_recon as module

    original = module._movers_note

    def _silent(shown, hidden):  # noqa: ANN001, ANN202, ARG001
        _APPLIED[0] += 1
        return ""

    module._movers_note = _silent
    assert module._movers_note is not original, "the patch did not take"
    try:
        yield
    finally:
        module._movers_note = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if no drill-down panel was built in this run."""
    if not _APPLIED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_movers_note_says_nothing: NOT APPLIED - no drill-down panel was "
            "built in this run, so its colour means nothing."
        )
