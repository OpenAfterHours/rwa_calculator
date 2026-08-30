"""Isolating mutation: the TERMS stop counting keys the two sides agree on.

``_terms`` is fed only the pairs whose delta is non-zero, so every ``amount``
is unchanged — an agreeing key contributes ``0.0`` — while every ``keys`` count
collapses to the differing subset. This is the shape of the regression the
per-key derivation exists to prevent: a waterfall whose population counts no
longer describe the drill-down beneath it, with the money still tying out and
``reconciles`` still true.

Changes exactly one thing (what ``_terms`` is given), by wrapping the original
rather than restating it, so a red is attributable to the count and not to a
transcription slip in a reimplementation.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_terms_skip_agreeing_keys
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _terms_ignore_agreeing_keys():
    import rwa_calc.analysis.return_recon as module

    original = module._terms

    def _drivers_only(pairs):  # noqa: ANN001, ANN202
        return original(pair for pair in pairs if pair.delta != 0.0)

    module._terms = _drivers_only
    try:
        yield
    finally:
        module._terms = original
