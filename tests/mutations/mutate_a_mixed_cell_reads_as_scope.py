"""Isolating mutation: a MIXED absent cell reported as pure scope.

One matrix cell can hold a split leg and a genuinely one-sided leg at once — our
legs on the same row, absent from their group for two different reasons. The
label is decided per cell, so ``_absent_basis`` tests ``all`` and then ``any``:
all -> ``same_base_*``, some -> ``mixed_base_*``, none -> the scope class.

Delete only the ``any`` limb and the two-answer cell reports the scope class,
which is the pre-change falsehood back in a narrower form — and this time
against a cell where a scope finding really IS present, so the label reads
plausibly and only the money it drags in with it is wrong. Measured on the
``_combined`` portfolio: cell ``(0030, absent)`` holds ``CLASS_MOVER`` (900,000
of ``ead_final``, on their institution sheet) and ``ONLY_OURS`` (500,000, on
neither of their sheets), so 900,000 of "moved" is reported as "not on their
template at all".

Changes ONE thing: the middle limb of the three-way label. The ``all`` limb and
the fallback are the module's own and run untouched, so the ordinary
``same_base_*`` cells keep their label and the red set is about mixing alone.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_a_mixed_cell_reads_as_scope
"""

from __future__ import annotations

import polars as pl
import pytest

_APPLIED = [0]


@pytest.fixture(autouse=True)
def _a_cell_that_is_both_is_reported_as_scope():
    import rwa_calc.analysis.return_recon as module

    original = module._absent_basis

    def _two_way(side: str) -> pl.Expr:
        _APPLIED[0] += 1
        return (
            pl.when(pl.col("_all_same_base"))
            .then(pl.lit(f"same_base_{side}"))
            .otherwise(pl.lit(f"{side}_only"))
        )

    module._absent_basis = _two_way
    assert module._absent_basis is not original, "the patch did not take"
    try:
        yield
    finally:
        module._absent_basis = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if no matrix was labelled at all in this run."""
    if not _APPLIED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_a_mixed_cell_reads_as_scope: NOT APPLIED - no matrix was built "
            "in this run, so its colour means nothing."
        )
