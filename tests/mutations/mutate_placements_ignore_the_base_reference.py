"""Isolating mutation: the placements keyed on the LEG, not on the exposure.

``_placements`` must key on ``_comparison_key`` in lockstep with ``_key_money``
and ``_side_keys``, because a pair's key is the pre-split exposure. Degrade its
key to the leg's own reference and every split exposure's pair renders a blank
placement on our side — silently, because an empty placement is also the honest
shape of a population term.

Implemented WITHOUT restating ``_placements`` or ``_comparison_key``: the
original runs unchanged over a side whose membership base reference is nulled,
so its ladder falls through to ``exposure_reference`` while ``_key_money`` and
``_side_keys`` — which read the real side — keep the collapsed key. That is the
lockstep failure and nothing else.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_placements_ignore_the_base_reference
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _placements_key_on_the_leg():
    import rwa_calc.analysis.return_recon as module

    original = module._placements

    def _leg_keyed(side, key_column, template_id, sheet):  # noqa: ANN001, ANN202
        legs = side.membership.legs
        if module._BASE_KEY_COLUMN in legs.columns:
            legs = legs.with_columns(pl.lit(None, dtype=pl.String()).alias(module._BASE_KEY_COLUMN))
            side = replace(side, membership=replace(side.membership, legs=legs), placements={})
        return original(side, key_column, template_id, sheet)

    module._placements = _leg_keyed
    try:
        yield
    finally:
        module._placements = original
