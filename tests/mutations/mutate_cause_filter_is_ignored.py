"""Isolating mutation: the waterfall's cause filter silently ignored.

``_selected_term`` resolves ``?term=`` to one of ``TERM_NAMES`` or to ``None``
for every cause. Forced to ``None``, every waterfall link still renders, every
click still returns 200, and the table that comes back is the WHOLE cell --
which is a superset of what was asked for and therefore looks entirely
plausible. This is the failure mode a smoke test cannot see: the page works, it
just does not do the one thing the click means.

Changes ONE thing: the resolved filter. The fallback path it mimics is real --
an unrecognised term legitimately widens to every cause -- so the mutation is
indistinguishable from the supported behaviour except by asserting on WHICH
causes come back.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_cause_filter_is_ignored
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _every_cause_is_selected():
    import rwa_calc.ui.views.return_recon as module

    original = module._selected_term

    def _unfiltered(term):  # noqa: ANN001, ANN202
        return None

    module._selected_term = _unfiltered
    try:
        yield
    finally:
        module._selected_term = original
