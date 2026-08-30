"""Isolating mutation: the comparison-key ladder WITHOUT its final rung.

Changes exactly one thing — ``_FALLBACK_KEY_COLUMN`` is dropped from the ladder,
restoring ``coalesce(source_exposure_reference, key_column)``. Everything else
about ``_comparison_key`` (the presence filter, the dedupe, the empty-ladder
guard, the cast and alias) is reproduced verbatim from the module, so a red here
is attributable to the missing rung and to nothing else.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_no_third_rung
"""

from __future__ import annotations

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def _ladder_without_the_fallback():
    import rwa_calc.analysis.return_recon as module

    original = module._comparison_key

    def _two_rung(columns, key_column: str) -> pl.Expr:
        present = set(columns)
        ladder = [
            name for name in dict.fromkeys((module._BASE_KEY_COLUMN, key_column)) if name in present
        ]
        if not ladder:
            return pl.col(key_column).cast(pl.String()).alias("key")
        return pl.coalesce(ladder).cast(pl.String()).alias("key")

    module._comparison_key = _two_rung
    try:
        yield
    finally:
        module._comparison_key = original
