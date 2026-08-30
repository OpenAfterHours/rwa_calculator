"""Isolating mutation: restore the PRE-FIX population keying.

Changes exactly one thing — ``_comparison_key`` stops coalescing through
``source_exposure_reference`` and reads the named join key literally, which is
what the module did before the split-leg fix. ``_key_money`` and ``_side_keys``
both route through it, so this reverts both in lockstep and nothing else.

Run with::

    PYTHONPATH=.:src:<this dir> uv run pytest <tests> -p mutate_prefix_key
"""

from __future__ import annotations

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _pre_fix_keying():
    import rwa_calc.analysis.return_recon as module

    original = module._comparison_key
    module._comparison_key = lambda columns, key_column: (
        pl.col(key_column).cast(pl.String()).alias("key")
    )
    try:
        yield
    finally:
        module._comparison_key = original
