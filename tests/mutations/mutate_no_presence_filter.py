"""Isolating mutation: ``_key_rungs`` without its ``if name in present`` filter.

Changes exactly one thing — the ladder stops being narrowed to the columns the
frame actually carries. Everything else (the members, the ``dict.fromkeys``
dedupe, the order) is reproduced verbatim from the module.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_no_presence_filter
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _unfiltered_key_rungs():
    import rwa_calc.analysis.return_recon as module

    original = module._key_rungs

    def _unfiltered(columns, key_column: str) -> list[str]:  # noqa: ANN001, ARG001
        return list(
            dict.fromkeys((module._BASE_KEY_COLUMN, key_column, module._FALLBACK_KEY_COLUMN))
        )

    module._key_rungs = _unfiltered
    try:
        yield
    finally:
        module._key_rungs = original
