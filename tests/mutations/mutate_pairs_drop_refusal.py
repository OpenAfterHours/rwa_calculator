"""Isolating mutation: a refused cell's pair table loses its refusal.

The empty table still comes back — the refusal path in ``_decompose`` is
structural and this does not touch it — but ``refusal`` is ``None``, so the
result is indistinguishable from a decomposable cell in which no exposure
differs. That is the whole hazard: a page reading ``pairs == ()`` alone tells
an analyst "no contracts drive this difference" about a cell whose difference
is not a number anyone should read.

Changes exactly one field of ``_no_pairs``' result, by wrapping the original
rather than restating it.

WHAT THIS DOES **NOT** PROVE. It does not show that a refused cell would
otherwise be paired: the refusal short-circuit and the empty ``()`` come from
the same return in ``_decompose``, so no mutation of ``cell_pairs`` alone can
put pairs behind a refusal without reimplementing the function. The property
"refused implies no pairs" is structural here, and the assertions that pin it
guard against a future reimplementation, not against this mutation.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_pairs_drop_refusal
"""

from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def _empty_table_says_nothing():
    import rwa_calc.analysis.return_recon as module

    original = module._no_pairs

    def _silent(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return replace(original(*args, **kwargs), refusal=None)

    module._no_pairs = _silent
    try:
        yield
    finally:
        module._no_pairs = original
