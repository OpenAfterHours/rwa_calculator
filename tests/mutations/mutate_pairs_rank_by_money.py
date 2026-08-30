"""Isolating mutation: the pair table ranked on MONEY instead of on |delta|.

This is the defect the pair table exists to remove — the ordering the compare
page's leg listing used, ``sort(|rwa_final|, descending)``. It changes exactly
one thing: ``_rank``'s sort key. The cap, the terms, the classification, the
placements and the arithmetic are all the module's own, so a red is
attributable to the ordering and to nothing else.

``_rank`` is a four-line function precisely so this mutation does not have to
restate ``cell_pairs``.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_pairs_rank_by_money
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _rank_on_the_biggest_loan():
    import rwa_calc.analysis.return_recon as module

    original = module._rank

    def _by_money(pairs):  # noqa: ANN001, ANN202
        # The side's own figure, exactly as a leg listing reads ``rwa_final``:
        # a key only one side holds is ranked on the money that side reports.
        return sorted(
            pairs,
            key=lambda pair: -abs(pair.ours if pair.ours is not None else (pair.theirs or 0.0)),
        )

    module._rank = _by_money
    try:
        yield
    finally:
        module._rank = original
