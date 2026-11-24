"""Isolating mutation: the QRRE aggregate sums every leg's facility limit (pre-P1.320).

Restores the leg multiplication P1.320 removed from
``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``: the
per-individual aggregate becomes the sum of ``candidate_limit`` over EVERY
QRRE-candidate leg of the obligor, so a facility the hierarchy splits into a
drawn loan and an ``_UNDRAWN`` headroom row contributes its limit twice. The
original still runs (so the helper column the caller drops still exists); only
the returned aggregate expression is replaced, and nothing else changes.

Session-scoped and self-counting, as ``mutate_qrre_aggregate_counts_no_share_candidate``
is: the tests memoise their pipeline runs, so a function-scoped patch would land
after the runs it is meant to mutate.

Run with::

    PYTHONPATH=<this dir> uv run pytest \
      tests/acceptance/reporting/test_qrre_headroom_reporting.py \
      -p mutate_qrre_aggregate_sums_every_leg
"""

from __future__ import annotations

import polars as pl
import pytest

#: Calls of the mutated aggregate across the session.
_CALLS = [0]


@pytest.fixture(scope="session", autouse=True)
def _qrre_aggregate_sums_every_leg():
    import rwa_calc.engine.classify.subtypes as module

    original = module.qrre_obligor_aggregate_limit_expr

    def _sums_every_leg(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        _CALLS[0] += 1
        frame, _deduped = original(exposures, is_qrre_candidate, facility_limit, candidate_limit)
        return frame, candidate_limit.sum().over("counterparty_reference")

    module.qrre_obligor_aggregate_limit_expr = _sums_every_leg
    assert module.qrre_obligor_aggregate_limit_expr is not original
    print(f"\nmutate_qrre_aggregate_sums_every_leg: patched {module.__file__}")  # noqa: T201
    try:
        yield
    finally:
        module.qrre_obligor_aggregate_limit_expr = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutated aggregate was never called."""
    if not _CALLS[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_qrre_aggregate_sums_every_leg: NOT APPLIED - the QRRE aggregate "
            "was never built in this run, so its colour means nothing."
        )
        return
    print(  # noqa: T201
        f"\nmutate_qrre_aggregate_sums_every_leg: applied on {_CALLS[0]} classification call(s)."
    )
