"""Isolating mutation: the sheet total taken over a NON-ADDITIVE column.

``sheet_conservation`` takes the cell rather than a column ref so it can refuse
anything that is not an additive money cell. This mutation tells it every column
is one, by handing it a decomposition whose ``metric`` reads ``"sum"``. Nothing
else moves: the original function does the summing, the leaf scoping and the
verdict.

What comes out is a fabricated number wearing a total's clothes. Measured on
C 08.03 column 0050, an exposure-weighted average PD: the page reports "the
sheet total is +0.0000" and "Column 0050 NETS across this sheet", which is the
most reassuring sentence available about a column that cannot be summed at all.
This is the same class of answer ``decompose_cell`` refuses for the same reason,
and it went out on the first render of this panel -- found by reading the page,
not by a test, which is why the test now exists.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_sheet_total_sums_an_average
"""

from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def _every_column_looks_additive():
    import rwa_calc.ui.views.return_recon as module

    original = module.sheet_conservation

    def _unguarded(recon, template_id, sheet, cell):  # noqa: ANN001, ANN202
        return original(recon, template_id, sheet, replace(cell, kind="rows", metric="sum"))

    module.sheet_conservation = _unguarded
    try:
        yield
    finally:
        module.sheet_conservation = original
