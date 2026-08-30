"""Isolating mutation: a pair's placement carriers scoped to the cell's SHEET.

The natural-looking tidy-up — "the cell is on one sheet, so read one sheet" —
and it blanks the single most useful field on a ``sheet_placement`` pair: the
class the other side moved the exposure TO lives on the sheet it moved to. The
pair then reports an empty class, an empty approach and an empty leg role for
the other side, which is indistinguishable from "they do not hold this exposure
at all" — a population finding wearing a sheet-placement label.

Implemented WITHOUT restating ``_placements``: the original runs unchanged over
a side whose membership legs are filtered to the cell's sheet, which is exactly
what the scoping would do.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_placements_carriers_scoped_to_sheet
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _carriers_read_one_sheet_only():
    import rwa_calc.analysis.return_recon as module

    original = module._placements

    def _scoped(side, key_column, template_id, sheet):  # noqa: ANN001, ANN202
        if sheet is not None:
            legs = side.membership.legs.filter(pl.col("sheet") == sheet)
            side = replace(side, membership=replace(side.membership, legs=legs), placements={})
        return original(side, key_column, template_id, sheet)

    module._placements = _scoped
    try:
        yield
    finally:
        module._placements = original
