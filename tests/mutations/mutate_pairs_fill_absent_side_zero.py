"""Isolating mutation: a pair's absent side filled to ``0.0`` instead of NULL.

The banned Float null-fill, in the one place a pair table invites it: a key only
one side reports would render "theirs 0.00" and read as a measured nil rather
than as an exposure the other side does not hold. ``delta`` is untouched — it is
passed explicitly — so the arithmetic still ties out and only the two money
fields change, which is what makes the wrong reading so easy to miss.

Implemented by wrapping the ``_KeyPair`` constructor, so the classification
itself is the module's own and a red is attributable to the fill.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_pairs_fill_absent_side_zero
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _absent_side_reads_as_a_zero():
    import rwa_calc.analysis.return_recon as module

    original = module._KeyPair

    def _filled(**kwargs):  # noqa: ANN003, ANN202
        return original(
            **{
                **kwargs,
                "ours": 0.0 if kwargs["ours"] is None else kwargs["ours"],
                "theirs": 0.0 if kwargs["theirs"] is None else kwargs["theirs"],
            }
        )

    module._KeyPair = _filled
    try:
        yield
    finally:
        module._KeyPair = original
