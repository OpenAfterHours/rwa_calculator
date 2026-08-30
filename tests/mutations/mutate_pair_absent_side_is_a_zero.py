"""Isolating mutation: a pair's absent side RENDERED as ``0.00``.

The analysis-side twin (``mutate_pairs_fill_absent_side_zero``) fills the model.
This one leaves the model alone and breaks the RENDERING: ``_pair_side`` is
handed a real ``None`` and turns it into a figure, so the page prints a measured
nil where the side holds no leg for that exposure at all. Nothing else moves --
``delta`` is computed upstream and is untouched, so the table still ranks
correctly and still ties out, which is exactly what makes the wrong reading easy
to miss on screen.

Changes ONE thing: the value ``_pair_side`` is asked to render. The original
function does the rendering, so a red is attributable to the null-fill and not
to a transcribed formatter.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_pair_absent_side_is_a_zero
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _absent_side_renders_as_a_measured_zero():
    import rwa_calc.ui.views.return_recon as module

    original = module._pair_side

    def _filled(value):  # noqa: ANN001, ANN202
        return original(0.0 if value is None else value)

    module._pair_side = _filled
    try:
        yield
    finally:
        module._pair_side = original
