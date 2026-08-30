"""Isolating mutation: a pair's ``row_refs`` span the TEMPLATE, not the sheet.

``_placements`` nulls ``row_ref`` outside the cell's own sheet, so a key the
other side placed elsewhere reports an empty row list — which is exactly what a
``sheet_placement`` finding says. Remove that scoping and their rows on another
sheet are reported as if they were rows of this one, which reads as a row
placement on a page that has just been told the cause is a sheet placement.

Implemented WITHOUT restating ``_placements``: the original runs unchanged over
a side whose membership rows are all relabelled onto the cell's sheet, which is
precisely what "do not scope the rows" means. The carriers are untouched.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_placements_rows_span_the_template
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _every_row_counts_as_this_sheet():
    import rwa_calc.analysis.return_recon as module

    original = module._placements

    def _unscoped(side, key_column, template_id, sheet):  # noqa: ANN001, ANN202
        if sheet is not None:
            legs = side.membership.legs.with_columns(
                pl.lit(sheet, dtype=pl.String()).alias("sheet")
            )
            side = replace(side, membership=replace(side.membership, legs=legs), placements={})
        return original(side, key_column, template_id, sheet)

    module._placements = _unscoped
    try:
        yield
    finally:
        module._placements = original
