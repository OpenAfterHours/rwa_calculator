"""
Generator 2 — out-of-domain numerics, driven off the Phase 1 declarations.

Pipeline position:
    corpus portfolio -> one column set outside its declared domain
        -> full pipeline -> triage invariant + error-channel assertion

Driven off the DECLARATION, not off a local table
--------------------------------------------------
Phase 1 landed ``NumericDomain`` on ``ColumnSpec`` (``data/column_spec.py``),
and ``tests/robustness/strategies.py::declared_numeric_domains`` reads it. This
module therefore fuzzes 49 declared columns across nine input tables today and
will fuzz the fiftieth the day it is declared — no edit here. Nothing in this
suite restates a bound; a test that restated one would share the declaration's
mistakes and go stale the first time a bound moved (`.claude/LESSONS.md` B3).

The probe values sit ADJACENT to the bound (``lower - 1``, ``upper + 1``, or the
bound itself where it is exclusive), not far outside it. A validator that
rejects ``1e30`` on a ``[0, 1]`` domain but accepts ``1.0000001`` is the shape a
real feed produces, and an absurd probe would report it as covered.

Two assertions, and the second is the sharper one
-------------------------------------------------
Every example asserts the triage invariant. Where the injected column is one the
pipeline reads, the example additionally asserts that the error channel says
SOMETHING — a row-named error, or the table/column aggregate that clause (c)
recognises. The invariant alone would pass on a silent, plausible, wrong number,
which is the defect class this whole suite exists for.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2, generator 2
- src/rwa_calc/data/column_spec.py — NumericDomain, and why `reason` is mandatory
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from tests.properties.portfolios import ExposureSpec, build_bundle
from tests.robustness.harness import Injection, assert_accounted, run, triage, with_columns
from tests.robustness.strategies import (
    SEARCH_SETTINGS,
    declared_numeric_domains,
    out_of_domain_values,
)

#: ``(table, column, out-of-domain value)`` for every declared numeric domain,
#: one entry per bounded side. Built once at import so the parametrisation and
#: the strategy see the same population.
_PROBES: tuple[tuple[str, str, float], ...] = tuple(
    (table, column, value)
    for table, column, domain in declared_numeric_domains()
    for value in out_of_domain_values(domain)
)

#: The portfolio the deterministic sweep runs against: broad enough to populate
#: every table the probes touch, small enough that 90-odd pipeline runs are
#: affordable. Ratings carry an internal PD so the IRB columns are live.
_BROAD = (
    ExposureSpec(entity_type="corporate", drawn=1_000_000.0, internal_pd=0.01, firm_lgd=0.45),
    ExposureSpec(
        entity_type="individual",
        drawn=300_000.0,
        external_cqs=3,
        collateral_value=500_000.0,
        collateral_property_type="residential",
        guarantee_amount=50_000.0,
        provision_amount=10_000.0,
    ),
    ExposureSpec(
        entity_type="institution",
        drawn=750_000.0,
        external_cqs=2,
        off_bs_nominal=250_000.0,
        off_bs_risk_type="MR",
    ),
)


def test_the_probe_population_is_not_empty() -> None:
    """A sweep over zero probes is a green suite that tested nothing.

    The canary against the whole generator being disarmed by a schema change —
    ``declared_numeric_domains`` raises on the four named columns, this catches
    a wholesale loss of the rest.
    """
    assert len(_PROBES) >= 40, (
        f"only {len(_PROBES)} out-of-domain probes derived from the declarations; "
        "the Phase 1 domain population has shrunk and this generator is nearly idle"
    )


@pytest.mark.parametrize(("table", "column", "value"), _PROBES, ids=lambda v: str(v))
def test_an_out_of_domain_value_accounts_for_every_row(
    table: str, column: str, value: float
) -> None:
    """One declared bound, breached, on a portfolio that populates the table.

    Deterministic rather than generated: the population IS the declaration, so
    every probe should run on every invocation rather than being sampled.
    """
    # Arrange
    bundle = build_bundle(_BROAD)
    frame = getattr(bundle, table, None)
    if frame is None or column not in frame.collect_schema().names():
        pytest.skip(f"the broad portfolio does not populate {table}.{column}")

    # Act
    dtype = frame.collect_schema()[column]
    mutated = with_columns(bundle, table, pl.lit(value).cast(dtype).alias(column))
    result = run(mutated)

    # Assert
    assert_accounted(
        mutated, result, [Injection(table, column, f"declared-domain breach ({value})")]
    )


@SEARCH_SETTINGS
@given(
    portfolio=st.sampled_from([_BROAD]),
    probe=st.sampled_from(_PROBES),
)
def test_a_breached_bound_reaches_the_error_channel(
    portfolio: tuple[ExposureSpec, ...], probe: tuple[str, str, float]
) -> None:
    """A declared bound that is breached must produce SOME error.

    Sharper than the invariant: a row can be finite, in-bounds and completely
    wrong. What is asserted is only that the run says something about the
    injected field — not which code, because the code is the validator's choice
    and pinning it here would make this a test of ``validation.py``'s internals.

    Skipped where the seal drops the column (a declared-but-unemitted optional),
    because there is then nothing to breach.
    """
    # Arrange
    table, column, value = probe
    bundle = build_bundle(portfolio)
    frame = getattr(bundle, table, None)
    # ``assume`` rather than ``pytest.skip``: inside a Hypothesis property a skip
    # on one unlucky example abandons the WHOLE property.
    assume(frame is not None)
    # `assume` is a Hypothesis rejection, not a type-narrowing construct — the
    # re-assertion is what tells the type checker the frame is present.
    assert frame is not None
    assume(column in frame.collect_schema().names())
    dtype = frame.collect_schema()[column]
    assume(dtype != pl.Boolean)

    # Act
    mutated = with_columns(bundle, table, pl.lit(value).cast(dtype).alias(column))
    result = run(mutated)
    round_tripped = getattr(mutated, table).select(pl.col(column)).collect().to_series().to_list()
    assume(any(v == pytest.approx(value) for v in round_tripped if v is not None))

    named = [error for error in result.errors if error.field_name == column]

    # Assert
    injections = [Injection(table, column, f"breach ({value})")]
    report = triage(mutated, result, injections)
    assert report.ok, report.describe(injections)
    assert named, (
        f"{table}.{column} = {value} is outside its DECLARED domain and nothing in "
        f"the run mentions the field. Accumulated codes: "
        f"{sorted({e.code for e in result.errors}) or '<none>'}"
    )


def test_more_violations_than_the_sample_cap_still_accounts_for_every_row() -> None:
    """Clause (c): beyond ``sample_cap=5`` no error names the row individually.

    ``_collect_domain_violations`` emits at most five row-named errors per column
    and then ONE summary carrying the omitted count. On a portfolio of eight
    bad rows, three are covered by the summary alone — and an invariant without
    clause (c) would report those three as unaccounted-for, on correct
    behaviour. That false failure is how a suite gets switched off.
    """
    # Arrange — eight exposures, every one carrying an out-of-domain PD.
    portfolio = tuple(
        ExposureSpec(entity_type="corporate", drawn=1_000_000.0, internal_pd=0.01) for _ in range(8)
    )
    bundle = build_bundle(portfolio)
    mutated = with_columns(bundle, "ratings", pl.lit(1.5).alias("pd"))

    # Act
    injections = [Injection("ratings", "pd", "eight breaches, cap is five")]
    result = run(mutated)
    report = triage(mutated, result, injections)
    summaries = [
        error
        for error in result.errors
        if error.exposure_reference is None and error.field_name == "pd"
    ]

    # Assert
    assert report.ok, report.describe(injections)
    assert summaries, (
        "eight out-of-domain PDs produced no table-level summary error, so three "
        "of the eight rows are named by nothing at all"
    )
