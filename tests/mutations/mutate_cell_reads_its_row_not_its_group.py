"""Isolating mutation: every cell of a row resolved to the ROW's first group.

"A row has one population" — the assumption `reporting/membership.py` was built
to refute, measured at 3.00x (C 07.00 `retail_other`) and 1.86x (C 08.01
`corporate`) over-counts. Under it a narrow column — off-balance-sheet,
defaulted, one CCF bucket — lists and prices every exposure of its row.

Implemented WITHOUT restating `_predicate_key`: the original runs unchanged,
asked for the row's FIRST served column instead of the cell's own. One thing
changes — which column the group is resolved for — and the resolution itself is
the module's.

Because `_cell_money` is shared, this reddens `decompose_cell`'s own tests as
well as the pair table's. That is correct attribution, not spill: the waterfall
and the drill-down read one population by design.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_cell_reads_its_row_not_its_group
"""

from __future__ import annotations

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _one_population_per_row():
    import rwa_calc.analysis.return_recon as module

    original = module._predicate_key

    def _row_first(side, template_id, sheet_key, row_ref, col_ref):  # noqa: ANN001, ANN202
        served = side.membership.columns.filter(
            (pl.col("template_id") == template_id)
            & (pl.col("sheet") == sheet_key)
            & (pl.col("row_ref") == row_ref)
        )
        if served.height == 0:
            return original(side, template_id, sheet_key, row_ref, col_ref)
        return original(side, template_id, sheet_key, row_ref, str(served["col_ref"][0]))

    module._predicate_key = _row_first
    try:
        yield
    finally:
        module._predicate_key = original
