"""Isolating mutation: ``differing_keys`` restated as the term's POPULATION.

Exactly the number the compare page reported before this change — ``keys`` — so
a ``measurement`` term of 35 shared keys behind 4 real breaks says "35
exposures". One field of ``CellTerm`` changes and nothing else: the amounts,
the pairs and the ordering are all the module's own.

Implemented by wrapping the ``CellTerm`` constructor rather than by restating
``_terms``, so the count under test is the only difference.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_terms_differing_is_population
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _differing_keys_counts_everything():
    import rwa_calc.analysis.return_recon as module

    original = module.CellTerm

    def _overstated(**kwargs):  # noqa: ANN003, ANN202
        return original(**{**kwargs, "differing_keys": kwargs["keys"]})

    module.CellTerm = _overstated
    try:
        yield
    finally:
        module.CellTerm = original
