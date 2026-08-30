"""Isolating mutation: a term's AMOUNT no longer equals the sum of its pairs.

The detector for the one invariant the whole pair table rests on — a drill-down
that does not sum to the waterfall row it explains is worse than none. Half of
``measurement``'s amount is moved into ``row_placement`` AFTER ``_terms`` has
run, so the waterfall attributes money to the wrong cause while every other
observable stays right.

WHAT IT DELIBERATELY DOES NOT DISTURB, and why that is the whole point:

- The TOTAL is preserved (``(m - s) + (r + s) == m + r``), so ``explained``
  still equals the reported delta and ``reconciles`` stays TRUE.
- The KEY COUNTS are untouched, so ``keys`` and ``differing_keys`` still
  describe the pairs exactly.
- The PAIRS themselves are untouched — ``_decompose`` returns the tuple
  ``_classify`` built, and this wraps only the aggregation over it.

So the pre-existing four-way additivity census cannot see this: its identity is
a statement about the SUM of the terms, and the sum is unchanged. Only an
assertion that each term equals its OWN pairs can, which is exactly the
contract ``test_every_terms_pairs_sum_to_that_term_on_every_additive_cell``
states. A mis-attributed term is the shape of the defect this batch already
paid for once — two population terms that summed to the right number for the
wrong reason, with ``reconciles`` true throughout.

Implemented by wrapping ``_terms``' RESULT rather than restating it, so the
classification, the aggregation and the counts are all the module's own and a
red is attributable to the amounts alone.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_terms_amount_drifts_from_its_pairs
"""

from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def _measurement_leaks_into_row_placement():
    import rwa_calc.analysis.return_recon as module

    original = module._terms

    def _misattributed(pairs):  # noqa: ANN001, ANN202
        terms = original(pairs)
        amounts = {term.name: term.amount for term in terms}
        shift = amounts.get("measurement", 0.0) * 0.5
        if shift == 0.0:
            return terms
        return tuple(
            replace(term, amount=term.amount - shift)
            if term.name == "measurement"
            else replace(term, amount=term.amount + shift)
            if term.name == "row_placement"
            else term
            for term in terms
        )

    module._terms = _misattributed
    try:
        yield
    finally:
        module._terms = original
