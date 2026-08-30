"""Isolating mutation: every ABSENT bucket labelled a scope finding.

The pre-change behaviour of ``_movement_basis``, exactly: a leg the other side
does not hold in this predicate group is reported as ``ours_only`` /
``theirs_only`` — "their extract has no such exposure" — whatever their extract
actually holds. That claim was false for every split leg on the sheet, because
our sealed ledger reports one exposure as several legs (``L1__G_BANK`` /
``L1__REM``) while a projected extract reports it whole under ``L1``, and the
matrix's grain is the leg.

Measured on the split fixture under this mutation: 100,000 of ``rwa_final`` on
each side lands under the two scope classes (1,000,000 each on ``ead_final``),
against two books that agree to the penny. On a three-substitution review
portfolio the same shape put 210,000 and 270,000 there.

Changes ONE thing: the label. The join, the placement, the pricing and the
conservation arithmetic are the module's own and run untouched — which is the
point, and is why the conservation guards stay GREEN under this mutation. A
mutation that also moved money would have made those two the detectors and told
you nothing about the label.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_absent_is_always_scope
"""

from __future__ import annotations

import polars as pl
import pytest

#: Applications across the session. At SESSION scope because most tests in a run
#: never build a matrix, so a per-test proof would fire on all of them and bury
#: the one signal it exists to give.
_APPLIED = [0]


@pytest.fixture(autouse=True)
def _an_absent_counterpart_is_always_scope():
    import rwa_calc.analysis.return_recon as module

    original = module._absent_basis

    def _scope_only(side: str) -> pl.Expr:
        _APPLIED[0] += 1
        return pl.lit(f"{side}_only")

    module._absent_basis = _scope_only
    assert module._absent_basis is not original, "the patch did not take"
    try:
        yield
    finally:
        module._absent_basis = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if no test in the run ever labelled a matrix cell."""
    if not _APPLIED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_absent_is_always_scope: NOT APPLIED - no matrix was built in "
            "this run, so its colour means nothing."
        )
