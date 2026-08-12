"""
Generator 1 — unit-scale errors on ratio columns (x100 and /100).

The highest-probability real defect in the estate. A firm's risk feed expresses
PD, LGD or a conversion factor in PERCENT where the engine wants a FRACTION, or
the reverse. ``tests/acceptance/test_percent_scale_pd_feed.py`` is the worked
single-case version of this, pinned end-to-end through ``ParquetLoader``; this
module generalises it to every ratio column the schema declares.

The two directions fail in OPPOSITE ways, and that asymmetry is the finding
-----------------------------------------------------------------------------
Multiplying a ratio by 100 usually leaves its declared domain, so the Phase 0
input gate catches it and names the row.

Dividing a ratio by 100 NEVER leaves its declared domain. Every ratio domain in
``data/schemas.py`` is bounded below at or under zero, so if ``v`` is admissible
then ``v / 100`` is admissible too — proved from the declaration itself in
:func:`test_dividing_a_ratio_by_100_stays_inside_its_declared_domain`, not
asserted from a hand-written table. A range check is therefore structurally
incapable of seeing the /100 direction, and the /100 direction is the one that
UNDERSTATES capital.

Measured on this branch, CRR, one GBP 1,000,000 senior corporate A-IRB exposure
(``internal_pd=0.01``, ``firm_lgd=0.45``, 5y):

=========================  =================  ==============
LGD as supplied            ``rwa_final``      Signal raised
=========================  =================  ==============
``0.45``   (correct)       GBP 1,314,904.00   none (correct)
``45.0``   (x100)          GBP 131,490,351    IRB002 + OUT001
``0.0045`` (/100)          GBP 13,149.04      **none**
=========================  =================  ==============

A **99.0% understatement** with no exception, no null and no
``CalculationError``. It satisfies the triage invariant — the row carries a
finite, in-bounds result — which is exactly why this module states the blind
spot as a separate, provable assertion rather than pretending the invariant
covers it. Closing it needs a plausibility signal (a distribution check against
the portfolio, or a declared expected scale), not a tighter bound.

Pipeline position:
    corpus portfolio -> ratio x k -> full pipeline -> triage invariant

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2, generator 1
- tests/acceptance/test_percent_scale_pd_feed.py — the single-case original
- CRR Art. 160/161: PD and LGD are fractions, not percentages
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from rwa_calc.contracts.errors import ERROR_PD_OUT_OF_RANGE
from tests.properties.portfolios import ExposureSpec, build_bundle
from tests.robustness.harness import (
    Injection,
    assert_accounted,
    present_columns,
    run,
    triage,
    with_columns,
)
from tests.robustness.strategies import (
    SEARCH_SETTINGS,
    UNIT_SCALE_FACTORS,
    base_portfolios,
    declared_numeric_domains,
    ratio_columns,
)

#: The A-IRB exposure the measured table above is built on. A single obligor so
#: the movement is attributable, and A-IRB so the firm's own LGD is the input
#: that moves (an SA exposure ignores ``lgd`` entirely and would measure nothing).
_MEASURED_SPEC = ExposureSpec(
    entity_type="corporate",
    drawn=1_000_000.0,
    internal_pd=0.01,
    firm_lgd=0.45,
    maturity_years=5.0,
)

#: Measured on this branch; see the module docstring.
_MEASURED_RWA_CORRECT = 1_314_904.0
#: The floor a /100 unit error must fall through for the blind spot to be real.
_MATERIAL_UNDERSTATEMENT = 0.90


# =============================================================================
# The structural blind spot, proved from the declaration
# =============================================================================


def test_dividing_a_ratio_by_100_stays_inside_its_declared_domain() -> None:
    """No range check can see a /100 unit error on a ratio column.

    Proved from the declared bounds rather than by probing values: for a domain
    bounded below at or under zero, ``v / 100`` lies between ``0`` and ``v`` for
    every admissible non-negative ``v``, so the image of the domain under /100
    is a subset of the domain.

    This test is the reason the /100 sweep below asserts the triage invariant
    and nothing stronger. If someone lands a plausibility gate that DOES catch
    the direction, this assertion stays true (it is about the declaration, not
    about the gate) and the new gate is free to fire.
    """
    # Arrange
    declared = {(table, column): domain for table, column, domain in declared_numeric_domains()}
    ratios = [pair for pair in ratio_columns() if pair in declared]
    assert ratios, "no ratio column carries a declared domain — the generator would fuzz nothing"

    # Act
    visible = [
        pair for pair in ratios if (lower := declared[pair].lower) is not None and lower > 0.0
    ]

    # Assert
    assert not visible, (
        "these ratio columns are bounded strictly above zero, so /100 CAN leave "
        f"their domain and the blind spot is narrower than documented: {visible}"
    )


def test_a_hundredfold_lgd_unit_error_is_invisible_to_the_invariant() -> None:
    """The /100 direction moves capital by 99% and satisfies every clause.

    Both halves are asserted because both are the finding: the movement is
    material, AND the triage invariant — the whole contract of this suite — is
    satisfied by it. A suite that only asserted the invariant would report this
    portfolio as clean.
    """
    # Arrange
    clean_bundle = build_bundle((_MEASURED_SPEC,))
    clean = run(clean_bundle)
    clean_rwa = float(clean.results.collect()["rwa_final"].sum())

    scaled_bundle = with_columns(clean_bundle, "loans", (pl.col("lgd") * 0.01).alias("lgd"))
    scaled = run(scaled_bundle)
    scaled_rwa = float(scaled.results.collect()["rwa_final"].sum())

    # Act
    report = triage(scaled_bundle, scaled, [Injection("loans", "lgd", "/100 unit error")])
    understatement = 1.0 - (scaled_rwa / clean_rwa)

    # Assert
    assert clean_rwa == pytest.approx(_MEASURED_RWA_CORRECT, rel=1e-6), (
        "the control moved; re-measure the table in this module's docstring "
        f"before reading anything else here (got {clean_rwa:,.2f})"
    )
    assert understatement > _MATERIAL_UNDERSTATEMENT, (
        f"a /100 LGD moved RWA by only {understatement:.1%} "
        f"(GBP {clean_rwa:,.2f} -> GBP {scaled_rwa:,.2f})"
    )
    assert report.ok, (
        "the invariant now catches a /100 unit error — that is good news, but "
        "this test documents it as a BLIND SPOT. Update the module docstring "
        f"and the proposal's Phase 2 notes.\n{report.describe()}"
    )


# =============================================================================
# The sweep
# =============================================================================


@SEARCH_SETTINGS
@given(portfolio=base_portfolios(), factor=st.sampled_from(UNIT_SCALE_FACTORS))
def test_a_unit_scale_error_on_any_ratio_column_accounts_for_every_row(
    portfolio: tuple[ExposureSpec, ...], factor: float
) -> None:
    """Every input row survives a unit-scale error, or something names it.

    A x100 ratio is expected to be REJECTED (the input gate names the row); a
    /100 ratio is expected to be ACCEPTED (it is in domain). Both satisfy the
    invariant. What must never happen — and what this sweep searches for — is a
    row that produces no output at all, or a NaN / inf / out-of-bounds one, with
    nothing said about it.
    """
    # Arrange
    bundle = build_bundle(portfolio)
    targets = present_columns(bundle, ratio_columns())
    # ``assume`` rather than ``pytest.skip``: inside a Hypothesis property a skip
    # on one unlucky example abandons the WHOLE property, so a single portfolio
    # carrying no ratio column would disarm the sweep and report green.
    assume(targets)

    # Act
    mutated = bundle
    for table, column in targets:
        mutated = with_columns(mutated, table, (pl.col(column) * factor).alias(column))
    injections = [Injection(table, column, f"unit-scale x{factor}") for table, column in targets]

    # Assert
    assert_accounted(mutated, run(mutated), injections)


@SEARCH_SETTINGS
@given(portfolio=base_portfolios())
def test_a_percent_scale_pd_that_leaves_the_domain_reaches_the_error_channel(
    portfolio: tuple[ExposureSpec, ...],
) -> None:
    """The measured headline case, over generated portfolios.

    ``pd`` is the column the proposal's evidence table is built on, and its
    declared domain is ``[0, 1]`` — so a feed expressing PD in percent produces
    an out-of-domain value for every PD above 1%. Those must reach the error
    channel, not merely satisfy the invariant.

    The example is skipped where ``pd x 100`` lands at or below 1.0, and that
    skip is itself a finding rather than housekeeping: a firm whose PDs are all
    at or below 1% can send the whole feed in percent and no bound is crossed.
    :func:`test_a_hundredfold_lgd_unit_error_is_invisible_to_the_invariant`
    measures what that costs.
    """
    # Arrange
    bundle = build_bundle(portfolio)
    ratings = bundle.ratings
    assume(ratings is not None)
    # `assume` is a Hypothesis rejection, not a type-narrowing construct — the
    # re-assertion is what tells the type checker the frame is present.
    assert ratings is not None
    assume("pd" in ratings.collect_schema().names())
    worst = ratings.select(pl.col("pd").max()).collect().item()
    assume(worst is not None and worst * 100.0 > 1.0)

    # Act
    mutated = with_columns(bundle, "ratings", (pl.col("pd") * 100.0).alias("pd"))
    result = run(mutated)
    pd_errors = [error for error in result.errors if error.code == ERROR_PD_OUT_OF_RANGE]

    # Assert
    assert_accounted(mutated, result, [Injection("ratings", "pd", "percent-scale PD")])
    assert pd_errors, (
        f"PD x100 reached {worst * 100.0} and nothing flagged it. Accumulated "
        f"codes: {sorted({e.code for e in result.errors}) or '<none>'}"
    )
