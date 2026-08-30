"""Isolating mutation: ``_rank`` ordered on ``|delta|`` with NO tie-break.

Deletes exactly one component of the sort key — the ``pair.key or ""`` that
``_rank``'s docstring calls on to make the order "total and stable". The
magnitude ordering is untouched, so every driver still ranks above every
agreeing key and every published figure is unchanged.

WHAT THAT COSTS, AND WHY IT IS NOT A TIDINESS POINT. Python's sort is stable, so
without the tie-break the residual order among tied keys is whatever
``_classify`` produced — which is polars ``group_by`` output order, and that is
implementation-defined and thread-scheduling dependent. It is not merely
arbitrary but UNSTABLE ACROSS PROCESSES: two runs of the same cell produced two
different pages, one of them showing a key (``SPLIT_FILL_A1``) the correct
ordering never puts on screen at all.

So the analyst refreshes one cell and sees a different 18 of the 30 tied
exposures, in a different order, with no change of data. Every driver stays on
the page and every total still ties out, so **nothing looks wrong** — which is
precisely why no assertion caught it. Someone comparing two screenshots of one
cell sees an inventory that moved under them.

**This mutation was SILENT when it was written**: 132 passed, exit 0. The
divergence was reachable all along — a spy over the unmutated ``_rank``
computing both orderings on every call the suite makes recorded 2,986 calls,
the two orders differing on 126 of them, and on 18 of those the SET of the top
25 differs, with up to 20 of the 25 rendered rows moving in a single call. The
suite reached the wrong answer 126 times and asserted on it zero times.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_rank_without_the_tie_break
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _rank_leaves_ties_to_polars():
    import rwa_calc.analysis.return_recon as module

    original = module._rank

    def _magnitude_only(pairs):  # noqa: ANN001, ANN202
        return sorted(pairs, key=lambda pair: -abs(pair.delta))

    module._rank = _magnitude_only
    try:
        yield
    finally:
        module._rank = original
