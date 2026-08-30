"""Isolating mutation: the cap stops saying how many rows it left off.

``hidden_keys`` forced to ``0`` on every ``CellPairs``, so a capped table reads
as the whole population — the silent-cap form of a silent zero. Nothing else
changes: the pairs, their order, ``shown_delta`` and ``total_delta`` are all the
module's own, and ``hidden_delta`` stays the property it always was (it is
derived from the two deltas, so it does NOT move with this mutation — which is
the point: a page trusting the count alone would report "nothing hidden" while
the money says otherwise).

Implemented by wrapping the ``CellPairs`` constructor rather than by restating
``cell_pairs``, so exactly one field of the result changes.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_pairs_silent_cap
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _cap_reports_nothing_hidden():
    import rwa_calc.analysis.return_recon as module

    original = module.CellPairs

    def _silent(**kwargs):  # noqa: ANN003, ANN202
        return original(**{**kwargs, "hidden_keys": 0})

    module.CellPairs = _silent
    try:
        yield
    finally:
        module.CellPairs = original
