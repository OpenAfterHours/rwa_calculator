"""Isolating mutation: the QRRE dedupe ordinal is a ROW count, not a candidate count.

``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr`` picks the leg
that carries a facility's limit with ``is_qrre_candidate.cum_sum().over(...) == 1``
— the first CANDIDATE leg of the (obligor, parent facility) group — and its ⚠
note says that is deliberate. This plugin swaps that one ordinal for
``pl.int_range(pl.len()).over(...) == 0`` — the first ROW of the group — and
leaves everything else as the original builds it: the candidate gate around it,
the null-parent fallback, and the per-obligor sum over the column.

Where a facility's first row is a candidate (every single-level facility, whose
drawn loans precede the ``_UNDRAWN`` row in ``engine/hierarchy/unify.py``'s
concat) the two ordinals agree. Where the first row is NOT a candidate — a
multi-option root whose waterfall emits a non-cancellable sub-line's headroom
row ahead of a cancellable one, being sorted by descending SA CCF — the
candidate leg gets zero, the individual's aggregate drops, and the leg is
wrongly admitted to QRRE.

Session-scoped and self-counting, as ``mutate_qrre_aggregate_counts_no_share_candidate``
is (the tests memoise their pipeline runs).

Run with::

    PYTHONPATH=<this dir> uv run pytest \
      tests/acceptance/reporting/test_qrre_headroom_reporting.py \
      -p mutate_qrre_aggregate_takes_first_row
"""

from __future__ import annotations

import polars as pl
import pytest

#: Calls of the mutated aggregate across the session.
_CALLS = [0]


@pytest.fixture(scope="session", autouse=True)
def _qrre_aggregate_takes_first_row():
    import rwa_calc.engine.classify.subtypes as module

    original = module.qrre_obligor_aggregate_limit_expr
    deduped_column = module._QRRE_DEDUPED_LIMIT_COLUMN

    def _takes_first_row(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        _CALLS[0] += 1
        frame, obligor_sum = original(exposures, is_qrre_candidate, facility_limit, candidate_limit)
        facility_keys = ["counterparty_reference", "parent_facility_reference"]
        first_row = (
            pl.when(is_qrre_candidate)
            .then(
                module.partition_by_nullable(
                    pl.when(pl.int_range(pl.len()).over(facility_keys) == 0)
                    .then(candidate_limit.max().over(facility_keys))
                    .otherwise(pl.lit(0.0)),
                    "parent_facility_reference",
                    facility_limit,
                )
            )
            .otherwise(pl.lit(0.0))
        )
        return frame.with_columns(first_row.alias(deduped_column)), obligor_sum

    module.qrre_obligor_aggregate_limit_expr = _takes_first_row
    assert module.qrre_obligor_aggregate_limit_expr is not original
    print(f"\nmutate_qrre_aggregate_takes_first_row: patched {module.__file__}")  # noqa: T201
    try:
        yield
    finally:
        module.qrre_obligor_aggregate_limit_expr = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutated aggregate was never called."""
    if not _CALLS[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_qrre_aggregate_takes_first_row: NOT APPLIED - the QRRE "
            "aggregate was never built in this run, so its colour means nothing."
        )
        return
    print(  # noqa: T201
        f"\nmutate_qrre_aggregate_takes_first_row: applied on {_CALLS[0]} classification call(s)."
    )
