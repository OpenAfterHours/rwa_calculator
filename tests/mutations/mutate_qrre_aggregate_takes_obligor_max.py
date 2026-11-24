"""Isolating mutation: the QRRE aggregate keeps ONE facility per individual (a ``max``).

The over-deduplicating regression of P1.320: the per-individual aggregate in
``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr`` takes the
largest per-facility contribution instead of summing them, so an individual
with two qualifying facilities whose limits sum past the Art. 147(5A)(c) /
Art. 154(4)(c) ceiling is wrongly admitted to QRRE. The per-(obligor, facility)
dedupe column is unchanged; only its per-obligor ``sum`` becomes a ``max``.

Session-scoped and self-counting, as ``mutate_qrre_aggregate_counts_no_share_candidate``
is (the tests memoise their pipeline runs).

Run with::

    PYTHONPATH=<this dir> uv run pytest \
      tests/acceptance/reporting/test_qrre_headroom_reporting.py \
      -p mutate_qrre_aggregate_takes_obligor_max
"""

from __future__ import annotations

import polars as pl
import pytest

#: Calls of the mutated aggregate across the session.
_CALLS = [0]


@pytest.fixture(scope="session", autouse=True)
def _qrre_aggregate_takes_obligor_max():
    import rwa_calc.engine.classify.subtypes as module

    original = module.qrre_obligor_aggregate_limit_expr
    deduped_column = module._QRRE_DEDUPED_LIMIT_COLUMN

    def _takes_obligor_max(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        _CALLS[0] += 1
        frame, _summed = original(exposures, is_qrre_candidate, facility_limit, candidate_limit)
        return frame, pl.col(deduped_column).max().over("counterparty_reference")

    module.qrre_obligor_aggregate_limit_expr = _takes_obligor_max
    assert module.qrre_obligor_aggregate_limit_expr is not original
    print(f"\nmutate_qrre_aggregate_takes_obligor_max: patched {module.__file__}")  # noqa: T201
    try:
        yield
    finally:
        module.qrre_obligor_aggregate_limit_expr = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutated aggregate was never called."""
    if not _CALLS[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_qrre_aggregate_takes_obligor_max: NOT APPLIED - the QRRE aggregate "
            "was never built in this run, so its colour means nothing."
        )
        return
    print(  # noqa: T201
        f"\nmutate_qrre_aggregate_takes_obligor_max: applied on {_CALLS[0]} classification call(s)."
    )
