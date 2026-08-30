"""Isolating mutation: the sheet total taken over EVERY row, parents included.

``sheet_conservation`` sums a column across the sheet's provable leaf rows, and
skips a row whose ``_parent_flag`` is anything but ``False``. Forcing that flag
to ``False`` makes every emitted row a leaf, so a PD band and the parent band
containing it are both added and every leg reported under both is counted twice.

The number that comes out is still a plausible one -- same sign, same order of
magnitude -- and the verdict it produces ("nets" / "does not net") can flip
either way depending on which rows overlap. That is the whole hazard: this row
axis is hierarchical and nothing about a doubled total looks doubled.

Changes ONE thing: the tri-state parent flag. The summation, the tolerance and
the verdict are the module's own.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_sheet_total_sums_every_row
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _every_row_is_a_leaf():
    import rwa_calc.ui.views.return_recon as module

    original = module._parent_flag

    def _all_leaves(recon, template_id, sheet, row_ref, predicate_key):  # noqa: ANN001, ANN202, PLR0913
        return False

    module._parent_flag = _all_leaves
    try:
        yield
    finally:
        module._parent_flag = original
