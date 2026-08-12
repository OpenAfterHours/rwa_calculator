"""
Generator 6 — structural extremes: empty tables, one row, absent files, 1M rows.

Pipeline position:
    degenerate / very large RawDataBundle -> full pipeline -> triage invariant

What each shape is for
----------------------
- **Every table empty.** The shape a first-time integration produces before any
  data is mapped. It must return an empty result frame, not raise, and not
  fabricate a row.
- **One row.** The shape a smoke test produces, and the one where a ``group_by``
  or a window function that assumes ``n > 1`` shows up.
- **Optional tables absent, one at a time.** ``RawDataBundle`` allows ``None``
  for every optional frame, and the loader returns ``None`` for a file it was
  not configured with. Each absent table is a different set of joins the engine
  must not need.
- **1M rows** (``slow``). The scale at which a silent join fan-out or a
  ``group_by`` collapse costs real capital and at which the triage invariant is
  the only affordable check. Marked ``slow`` so it is excluded even from the
  nightly robustness leg unless asked for; run it with
  ``-m 'robustness and slow'``.

The 1M case counts rows through :func:`triage` rather than comparing totals: a
count identity is the assertion that survives at scale, and it is the one
``tests/acceptance/stress/test_stress_pipeline.py::TestRowCountPreservation``
already makes on a CLEAN portfolio. This module makes it on a degenerate one.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2, generator 6
- tests/acceptance/stress/conftest.py — build_stress_dataset, called fresh
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from tests.acceptance.stress.conftest import build_stress_dataset, create_raw_bundle
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.properties.portfolios import ExposureSpec, build_bundle, config_for
from tests.robustness.harness import assert_accounted, inject, run, run_with, triage

if TYPE_CHECKING:
    from tests.properties.portfolios import Portfolio

#: Optional frame fields a credit-risk bundle may legitimately arrive without.
#: ``loans`` / ``counterparties`` / ``facilities`` / ``facility_mappings`` are
#: excluded: ``make_raw_bundle`` substitutes an empty sealed frame for those
#: rather than ``None``, so "absent" is already the empty-table case above.
_OPTIONAL_TABLES: tuple[str, ...] = (
    "contingents",
    "collateral",
    "collateral_links",
    "guarantees",
    "provisions",
    "ratings",
    "specialised_lending",
    "org_mappings",
    "lending_mappings",
    "model_permissions",
    "fx_rates",
)

#: A portfolio exercising every optional table at once, so dropping one is a
#: measurable subtraction rather than a no-op.
_FULL: Portfolio = (
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        internal_pd=0.01,
        firm_lgd=0.45,
        off_bs_nominal=250_000.0,
        collateral_value=400_000.0,
        guarantee_amount=100_000.0,
        provision_amount=25_000.0,
    ),
    ExposureSpec(entity_type="individual", drawn=200_000.0, external_cqs=3),
    ExposureSpec(
        entity_type="corporate", drawn=500_000.0, external_cqs=2, is_specialised_lending=True
    ),
)


# =============================================================================
# Degenerate shapes
# =============================================================================


def test_an_entirely_empty_bundle_returns_an_empty_result_without_raising() -> None:
    """The first-integration shape: every table present, every table empty."""
    # Arrange
    bundle = make_raw_bundle()

    # Act
    result = run(bundle)
    frame = result.results.collect()

    # Assert
    assert frame.height == 0, f"an empty bundle fabricated {frame.height} result row(s)"
    assert triage(bundle, result).ok


def test_a_single_row_portfolio_is_accounted_for() -> None:
    """The smoke-test shape, where an ``n > 1`` assumption would show."""
    # Arrange
    bundle = build_bundle((ExposureSpec(entity_type="corporate", drawn=1.0, external_cqs=3),))

    # Act / Assert
    assert_accounted(bundle, run(bundle))


def test_a_zero_amount_exposure_is_accounted_for() -> None:
    """Zero is a legal amount and must not be confused with an absent one."""
    # Arrange
    bundle = build_bundle((ExposureSpec(entity_type="corporate", drawn=0.0, external_cqs=3),))

    # Act / Assert
    assert_accounted(bundle, run(bundle))


@pytest.mark.parametrize("table", _OPTIONAL_TABLES)
def test_dropping_one_optional_table_accounts_for_every_row(table: str) -> None:
    """Each optional table absent in turn — the missing-file case, in memory."""
    # Arrange
    bundle = build_bundle(_FULL)
    if getattr(bundle, table, None) is None:
        pytest.skip(f"the full portfolio does not populate {table}")
    without = _drop_table(bundle, table)

    # Act / Assert
    assert_accounted(without, run(without))


def test_dropping_every_optional_table_at_once_accounts_for_every_row() -> None:
    """The minimal viable feed: loans and counterparties, nothing else."""
    # Arrange
    bundle = build_bundle(_FULL)
    stripped = bundle
    for table in _OPTIONAL_TABLES:
        stripped = _drop_table(stripped, table)

    # Act / Assert
    assert_accounted(stripped, run(stripped))


def test_an_empty_loans_table_with_populated_dependants_is_accounted_for() -> None:
    """Collateral, guarantees and ratings that reference loans which do not exist.

    The mirror image of the orphan foreign key in
    ``test_referential_integrity.py``: there the exposure points at nothing, here
    the mitigation does. Nothing should be fabricated from the dangling side.
    """
    # Arrange
    bundle = build_bundle(_FULL)
    emptied = inject(bundle, loans=bundle.loans.clear())

    # Act
    result = run(emptied)
    frame = result.results.collect()

    # Assert
    assert triage(emptied, result).ok
    assert frame.filter(pl.col("exposure_type") == "loan").height == 0, (
        "loan rows appeared in the output from an empty loans table"
    )


# =============================================================================
# Scale
# =============================================================================


def test_a_stress_generated_portfolio_accounts_for_every_row() -> None:
    """The stress generator's own shape, at a size the nightly can afford.

    Not redundant with the 1M case below and not a weaker version of it: this is
    what makes the 1M test's CODE PATH exercised on every run. A `slow`-marked
    test is deselected everywhere except a deliberate invocation, so if the only
    stress-scale coverage were the 1M one, a break in
    ``build_stress_dataset`` -> ``create_raw_bundle`` -> :func:`triage` would sit
    undetected until someone remembered to run it.

    Built FRESH rather than from ``tests/acceptance/stress/conftest.py``'s
    ``*_result_10k`` fixtures, which cache at session scope — right for the
    stress suite and wrong here, because this suite corrupts its inputs and a
    shared cached bundle would leak a mutation between tests
    (`.claude/LESSONS.md` G: a stray mutation cost three agents an hour).
    """
    # Arrange — 3k obligors gives ~9k loans and ~1.5k contingents.
    dataset = build_stress_dataset(3_000, seed=7)
    bundle = create_raw_bundle(dataset, irb=False)

    # Act
    result = run_with(bundle, config_for("CRR"))
    report = triage(bundle, result)

    # Assert
    assert report.input_rows >= 10_000, (
        f"expected at least 10k input exposure rows, built {report.input_rows}"
    )
    assert report.ok, report.describe()


@pytest.mark.slow
def test_a_million_row_portfolio_accounts_for_every_row() -> None:
    """The 1M-row case — the scale escalation of the test above.

    ~333k counterparties gives ~1M loans at the generator's
    three-loans-per-obligor ratio.

    **NOT RUN on the reference dev box, and that is recorded rather than
    implied.** Generating and running 1M exposures needs more than the 7.8 GB the
    box carries, and the agent harness hard-kills a background task at ~600s, so
    the run was started and killed rather than completed. It is `slow`-marked so
    it is excluded from the nightly legs too — run it deliberately, on a machine
    that can hold it:

        uv run pytest tests/robustness/ -m 'robustness and slow' -o addopts=

    The sibling test above exercises every line of this one at 1/100th the size,
    so what is unverified here is the SCALE, not the code.
    """
    # Arrange
    dataset = build_stress_dataset(333_334, seed=7)
    bundle = create_raw_bundle(dataset, irb=False)

    # Act
    result = run_with(bundle, config_for("CRR"))
    report = triage(bundle, result)

    # Assert
    assert report.input_rows >= 1_000_000, (
        f"expected at least 1M input exposure rows, built {report.input_rows}"
    )
    assert report.ok, report.describe()


# =============================================================================
# Private helpers
# =============================================================================


def _drop_table(bundle: RawDataBundle, table: str) -> RawDataBundle:
    """A copy of ``bundle`` with one optional frame set to ``None``.

    Not routed through :func:`tests.robustness.harness.inject` because
    ``make_raw_bundle`` substitutes an empty sealed frame for a required table
    passed as ``None``, which is a different shape from absence. Re-sealing is
    unnecessary here: every OTHER frame is already sealed and unchanged.
    """
    fields = {
        field.name: getattr(bundle, field.name) for field in dataclasses.fields(RawDataBundle)
    }
    fields[table] = None
    return RawDataBundle(**fields)
