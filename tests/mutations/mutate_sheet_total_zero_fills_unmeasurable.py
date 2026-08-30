"""Isolating mutation: an unmeasurable leaf counted as ``0.0`` in the sheet total.

``_leaf_delta`` returns ``None`` for a cell one side cannot measure, which makes
the whole column ``decidable=False`` -- no figure, no verdict, and a note saying
which rows blocked it. Zero-filled instead, the column reports a confident total
built over PART of itself, and a partial total reads exactly like a complete
one: same format, same sign, same "the sheet nets" verdict at the end.

This is the sheet-level form of the false zero the coverage guard exists for. On
a thin mapping every cell of the column is unmeasurable, so the mutant reports
the sheet as netting to ``0`` -- the most reassuring thing the page could say
about a column their engine was never asked for.

Changes ONE thing: what an unmeasurable leaf contributes. The leaf scoping, the
counts and the verdict are the module's own.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_sheet_total_zero_fills_unmeasurable
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _an_unmeasurable_leaf_is_a_zero():
    import rwa_calc.ui.views.return_recon as module

    original = module._leaf_delta

    def _zero_filled(record):  # noqa: ANN001, ANN202
        value = original(record)
        return 0.0 if value is None else value

    module._leaf_delta = _zero_filled
    try:
        yield
    finally:
        module._leaf_delta = original
