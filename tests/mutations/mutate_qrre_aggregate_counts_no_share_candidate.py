"""Isolating mutation: facility-share candidate rows stop counting toward the QRRE aggregate.

Decision D4 of the facility-share design counts every candidate row toward its
own member's obligor aggregates with no special-casing. This plugin removes
exactly that for the Art. 147(5A)(c) / Art. 154(4)(c) QRRE aggregate: rows with
``is_facility_share_candidate`` are masked out of the candidate set the
aggregate sums, and nothing else changes — a candidate row's OWN QRRE candidacy
(``is_qrre`` in the caller) still reads the unmutated mask.

Implemented WITHOUT copying ``qrre_obligor_aggregate_limit_expr``: the original
runs unchanged over a narrowed candidate mask and a candidate limit zeroed on
the same rows, which is what an "exclude the fan-out" aggregate would do.

The patch is a ``setattr`` on the module, but the P5.62 acceptance tests memoise
their pipeline runs, so the fixture is SESSION-scoped (README, "The C 07.00
row-scope set": a function-scoped patch lands after the runs it is meant to
mutate) and counts its own applications, failing the session at zero.

It needs ``is_facility_share_candidate`` on the frame, which every hierarchy
exit carries; run it against pipeline-level tests, not hand-built classify
frames.

Run with::

    PYTHONPATH=<this dir> uv run pytest \
      tests/acceptance/test_p5_62_facility_share_qrre_demotion.py \
      -p mutate_qrre_aggregate_counts_no_share_candidate
"""

from __future__ import annotations

import polars as pl
import pytest

#: Calls of the mutated aggregate across the session.
_CALLS = [0]


@pytest.fixture(scope="session", autouse=True)
def _qrre_aggregate_without_share_candidates():
    import rwa_calc.engine.classify.subtypes as module

    original = module.qrre_obligor_aggregate_limit_expr

    def _without_candidates(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        _CALLS[0] += 1
        is_candidate_row = pl.col("is_facility_share_candidate").fill_null(False)
        return original(
            exposures,
            is_qrre_candidate & ~is_candidate_row,
            facility_limit,
            pl.when(is_candidate_row).then(pl.lit(0.0)).otherwise(candidate_limit),
        )

    module.qrre_obligor_aggregate_limit_expr = _without_candidates
    assert module.qrre_obligor_aggregate_limit_expr is not original
    try:
        yield
    finally:
        module.qrre_obligor_aggregate_limit_expr = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session if the mutated aggregate was never called."""
    if not _CALLS[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            "\nmutate_qrre_aggregate_counts_no_share_candidate: NOT APPLIED - the "
            "QRRE aggregate was never built in this run, so its colour means nothing."
        )
        return
    print(  # noqa: T201
        f"\nmutate_qrre_aggregate_counts_no_share_candidate: applied on "
        f"{_CALLS[0]} classification call(s)."
    )
