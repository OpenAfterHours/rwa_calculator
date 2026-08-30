"""Isolating mutation: ``CellTerm.__post_init__`` removed.

The constructor bound — ``0 <= differing_keys <= keys`` — replaced by a no-op,
so a term claiming 5 of its 3 keys differ constructs silently again. Nothing
else changes: the fields, the aggregation in ``_terms`` and every published
figure are the module's own.

WHY THE GUARD EXISTS. Making ``differing_keys`` required turned OMISSION into a
``TypeError``; it did nothing about INCONSISTENCY, which still passed. The
argument for requiring the field was that it "turns that inconsistency into an
error at construction", and without the bound that argument is false — which is
the kind of gap that survives precisely because the field looks guarded.

FAILS CLOSED. Removing a method is a more indirect patch than ``setattr`` on a
module, and the method may not exist yet (it is landing in a separate change),
so the fixture asserts the attribute is there before removing it and fails the
session outright when it is not — per rule 3 in this directory's README. A
green run under a mutation that never applied is the failure mode that rule
exists for.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_cell_term_stops_validating
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _constructor_accepts_any_counts():
    import rwa_calc.analysis.return_recon as module

    original = module.CellTerm.__dict__.get("__post_init__")
    if original is None:
        pytest.fail(
            "CellTerm defines no __post_init__, so there is no constructor bound to "
            "remove — this mutation cannot apply and must not report a green run"
        )

    module.CellTerm.__post_init__ = lambda self: None
    try:
        yield
    finally:
        module.CellTerm.__post_init__ = original
