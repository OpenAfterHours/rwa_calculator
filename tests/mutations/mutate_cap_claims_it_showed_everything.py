"""Isolating mutation: the cap claims the rows it SHOWED carry the whole delta.

``shown_delta`` forced to ``total_delta``, so ``hidden_delta`` — which is
derived as ``total - shown`` — reads ``0.00`` however much money the cap left
off. Nothing else moves: the pairs, their order, ``total_delta`` and
``hidden_keys`` are all the module's own, so the page still reports the right
NUMBER of hidden rows while attributing their money to the rows on screen.

That is the harm, stated as the page would state it. On the probe cell at
``limit=3`` the truth is "the 3 shown carry 35,000.00; 35 more carry 28,000.00";
under this mutation the page prints "the 3 shown carry 63,000.00 of the
63,000.00 difference; 35 more carry 0.00" — 44% of the difference silently
attributed to rows the analyst can see. A silent zero asserted as a positive
claim, which is the failure mode ``analysis/return_recon.py`` exists to prevent.

**This mutation was SILENT when it was written.** Against a 132-passed
baseline it scored 132 passed, exit 0. The suite could not distinguish a correct
``shown_delta`` from ``total_delta`` at all: a spy over the unmutated
``cell_pairs`` across the whole file recorded 7,021 calls, ``shown_delta !=
total_delta`` on ZERO of them and ``hidden_delta == 0.0`` on every one, because
``CELL_PAIRS_LIMIT = 25`` on a 38-key probe puts all seven drivers on the page
and leaves the tail empty. The test that closed it tightens the cap until the
tail carries money, and leads with the adequacy assertion that keeps it from
going vacuous again.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_cap_claims_it_showed_everything
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _shown_delta_swallows_the_tail():
    import rwa_calc.analysis.return_recon as module

    original = module.CellPairs

    def _overstated(**kwargs):  # noqa: ANN003, ANN202
        return original(**{**kwargs, "shown_delta": kwargs["total_delta"]})

    module.CellPairs = _overstated
    try:
        yield
    finally:
        module.CellPairs = original
