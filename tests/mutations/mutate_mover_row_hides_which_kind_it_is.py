"""Isolating mutation: the drill-down's per-leg verdict column emptied.

A ``mixed_base_*`` cell is honest about the cell and deliberately uninformative
about the legs: some of them sit elsewhere on the other side's template and some
are not on it at all. ``_same_base_note`` is the ONLY place that difference is
stated, so emptying it renders three identical-looking rows under a label that
says "both" and leaves the analyst no way to tell which leg is which.

Note what stays right under this mutation and is therefore not the detector: the
cell's own label, every figure in the table, the counts, the ranking and the
loan links. The panel looks complete. That is the shape of the defect — a column
that goes blank reads as "nothing to say here", which beside a populated row
reads as "the same as the row above".

Changes ONE thing: the per-leg verdict string.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_mover_row_hides_which_kind_it_is
"""

from __future__ import annotations

import pytest

#: Calls, and calls where the original had something to say. The second is the
#: vacuity proof: a corpus with no absent leg would make mutant and original
#: agree on every call the suite makes (README mechanism 4).
_CALLS = [0]
_DIVERGED = [0]


@pytest.fixture(autouse=True)
def _a_leg_stops_saying_what_the_other_side_did_with_it():
    import rwa_calc.ui.views.return_recon as module

    original = module._same_base_note

    def _blank(leg):  # noqa: ANN001, ANN202
        _CALLS[0] += 1
        if original(leg):
            _DIVERGED[0] += 1
        return ""

    module._same_base_note = _blank
    assert module._same_base_note is not original, "the patch did not take"
    try:
        yield
    finally:
        module._same_base_note = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session unless the mutation actually blanked something.

    The note is blank BY DESIGN for a leg both sides hold in the group, so a run
    that only ever rendered diagonal cells would agree with the original on every
    call — undetected and unreachable are indistinguishable from the colour.
    """
    if not _DIVERGED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            f"\nmutate_mover_row_hides_which_kind_it_is: VACUOUS - {_CALLS[0]} call(s), "
            "none of which had a verdict to blank, so its colour means nothing."
        )
