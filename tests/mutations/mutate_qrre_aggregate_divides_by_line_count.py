"""Isolating mutation: the QRRE dedupe divides a facility limit by its LINE count.

The shape of the sibling obligor dedupe in ``engine/classify/attributes.py``
(the optional 0.2% granularity test, ``pl.len().over(...)``) that
``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr`` documents it
must NOT copy. Each QRRE-candidate leg contributes ``facility_limit / n``, where
``n`` counts every leg of the (obligor, parent facility) group, candidate or not.
Where every leg is a candidate this equals the correct one-contribution-per-
facility; where a facility's legs differ in candidacy (a drawn leg with no
undrawn commitment beside a headroom leg that is not unconditionally
cancellable) it halves the facility's contribution and wrongly admits the
individual to QRRE. Only the per-leg contribution column changes; the
per-obligor sum over it is the original.

Session-scoped and self-counting, as ``mutate_qrre_aggregate_counts_no_share_candidate``
is (the tests memoise their pipeline runs).

Run with::

    PYTHONPATH=<this dir> uv run pytest \
      tests/acceptance/reporting/test_qrre_headroom_reporting.py \
      -p mutate_qrre_aggregate_divides_by_line_count
"""

from __future__ import annotations

import polars as pl
import pytest

#: Calls of the mutated aggregate across the session.
_CALLS = [0]


@pytest.fixture(scope="session", autouse=True)
def _qrre_aggregate_divides_by_line_count():
    import rwa_calc.engine.classify.subtypes as module

    original = module.qrre_obligor_aggregate_limit_expr
    deduped_column = module._QRRE_DEDUPED_LIMIT_COLUMN

    def _divides_by_line_count(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        _CALLS[0] += 1
        frame, obligor_sum = original(exposures, is_qrre_candidate, facility_limit, candidate_limit)
        facility_keys = ["counterparty_reference", "parent_facility_reference"]
        per_line = (
            pl.when(is_qrre_candidate)
            .then(candidate_limit / pl.len().over(facility_keys))
            .otherwise(pl.lit(0.0))
        )
        return frame.with_columns(per_line.alias(deduped_column)), obligor_sum

    module.qrre_obligor_aggregate_limit_expr = _divides_by_line_count
    assert module.qrre_obligor_aggregate_limit_expr is not original
    print(f"\nmutate_qrre_aggregate_divides_by_line_count: patched {module.__file__}")  # noqa: T201
    try:
        yield
    finally:
        module.qrre_obligor_aggregate_limit_expr = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutated aggregate was never called."""
    if not _CALLS[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_qrre_aggregate_divides_by_line_count: NOT APPLIED - the QRRE "
            "aggregate was never built in this run, so its colour means nothing."
        )
        return
    print(  # noqa: T201
        f"\nmutate_qrre_aggregate_divides_by_line_count: applied on {_CALLS[0]} "
        "classification call(s)."
    )
