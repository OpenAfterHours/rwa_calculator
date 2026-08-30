"""Isolating mutation: ``_group_legs`` keyed on the BASE reference.

This is the "tidy up the two inconsistent key expressions" change the module
forbids in prose. ``_group_legs`` prices each key with ``pl.col(money).first()``
because one leg legitimately appears on several ROWS of a group; collapsing two
DISTINCT legs onto one base key therefore keeps one leg's money and silently
discards the other's.

Implemented WITHOUT copying any of ``_group_legs``' logic: the original runs
unchanged, over a side whose membership legs have ``key_column`` rewritten to
the collapsed value. That is exactly what grouping on the base key would do, and
it keeps the mutation to one thing.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_collapse_group_legs
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _group_legs_on_the_base_key():
    import rwa_calc.analysis.return_recon as module

    original = module._group_legs

    def _collapsed(side, key_column, template_id, sheet, predicate_key, money_column, label):  # noqa: ANN001, ANN202, PLR0913
        legs = side.membership.legs
        if module._BASE_KEY_COLUMN in legs.columns:
            legs = legs.with_columns(
                pl.coalesce(module._BASE_KEY_COLUMN, key_column).alias(key_column)
            )
            side = replace(side, membership=replace(side.membership, legs=legs))
        return original(side, key_column, template_id, sheet, predicate_key, money_column, label)

    module._group_legs = _collapsed
    try:
        yield
    finally:
        module._group_legs = original
