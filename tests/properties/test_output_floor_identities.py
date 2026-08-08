"""
Output floor identities, and the post-floor discipline downstream of it.

Pipeline position:
    portfolio -> IRB / slotting calculators -> output floor -> aggregator exit
        -> every consumer of ``rwa_final``

What this proves:
- The floor never releases capital. ``TREA = max(U-TREA, x x S-TREA + OF-ADJ)``
  (PRA PS1/26 Art. 92 para 2A) is a maximum, so post-floor RWEA is at least the
  modelled figure and at least the threshold.
- The multiplier is the published one. ``x`` phases in under Art. 92(5) and
  reaches 72.5% on 1 January 2030; the fully-phased-in value is asserted against
  the regulation, not read back from the engine.
- ``rwa_final`` is ALREADY post-floor. The shortfall is distributed pro-rata over
  the floor-eligible legs, so summing ``rwa_final`` and then adding the floor
  impact again double-counts it. This is a recorded trap (`.claude/LESSONS.md`),
  and it is asserted here rather than left as prose.
- The floor binds on the PORTFOLIO, not on a leg. A leg's post-floor RWEA can
  exceed its own SA-equivalent, and that is correct — so the naive per-leg form
  of the identity is deliberately NOT asserted.

Why the guard matters (`LESSONS.md` D1): every ``engine/sa/`` transform runs
unconditionally so each leg carries an SA-equivalent risk weight for this floor.
A change that lowers an SA-equivalent lowers the floor wherever it binds, which
makes it RWA-reducing. This module is the standing check on that coupling.

References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x x S-TREA + OF-ADJ)
- PRA PS1/26 Art. 92(5): the transitional phase-in of x
- CRE99.1-8: the Basel output floor
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given, settings

from tests.properties.corpus import CORPUS, IRB_MIX
from tests.properties.portfolios import ExposureSpec, corep_bundle, results_df, run
from tests.properties.strategies import portfolios

#: The fully-phased-in output floor multiplier. Taken from PS1/26 Art. 92 — NOT
#: read back from the pack — so a change to the pack value fails this test rather
#: than being silently confirmed by it.
FULLY_PHASED_IN_FLOOR_PCT = 0.725

#: Reporting date after 1 January 2030, so the Art. 92(5) phase-in is complete.
FULLY_PHASED_IN_REGIME = "B31_FLOORED"

#: Regimes with an output floor at all. CRR has none.
FLOORED_REGIMES: tuple[str, ...] = ("B31", "B31_FLOORED")

MONEY_TOLERANCE = 0.005

#: Two runs per example; the floor only exists on one regime here.
FLOOR_EXAMPLES = 4


# ---------------------------------------------------------------------------
# The floor identity itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", FLOORED_REGIMES)
@pytest.mark.parametrize("portfolio_name", tuple(CORPUS))
def test_the_floor_never_reduces_modelled_capital(portfolio_name: str, regime: str):
    """Post-floor modelled RWEA is at least the un-floored modelled RWEA.

    ``max(U-TREA, threshold) >= U-TREA`` by construction. Asserted anyway because
    the floor is applied by distributing a shortfall pro-rata across legs, and a
    distribution can lose or misplace an amount without the maximum ever being
    evaluated wrongly.
    """
    # Arrange
    summary = run(CORPUS[portfolio_name], regime).output_floor_summary
    if summary is None:
        pytest.skip("no floor-eligible exposure in this portfolio")

    # Assert
    assert summary.floored_modelled_rwa >= summary.u_trea - MONEY_TOLERANCE, (
        f"the output floor REDUCED modelled RWEA under {regime}: "
        f"{summary.u_trea:,.2f} -> {summary.floored_modelled_rwa:,.2f}"
    )


@pytest.mark.parametrize("regime", FLOORED_REGIMES)
@pytest.mark.parametrize("portfolio_name", tuple(CORPUS))
def test_post_floor_rwea_is_at_least_the_published_threshold(portfolio_name: str, regime: str):
    """Post-floor modelled RWEA is at least ``x x S-TREA + OF-ADJ``.

    The other limb of the Art. 92 para 2A maximum. Stated with OF-ADJ included
    rather than as the bare ``0.725 x S-TREA`` shorthand: OF-ADJ can be negative
    (it subtracts 12.5x the IRB CET1 deduction), so the bare form is not the
    regulation's own inequality and would fail on a book with an EL shortfall.
    """
    # Arrange
    summary = run(CORPUS[portfolio_name], regime).output_floor_summary
    if summary is None:
        pytest.skip("no floor-eligible exposure in this portfolio")

    # Assert
    assert summary.floored_modelled_rwa >= summary.floor_threshold - MONEY_TOLERANCE, (
        f"post-floor modelled RWEA {summary.floored_modelled_rwa:,.2f} is below the Art. 92 "
        f"para 2A threshold {summary.floor_threshold:,.2f} under {regime}"
    )


def test_the_fully_phased_in_floor_multiplier_is_72_point_5_percent():
    """``x`` = 72.5% once the Art. 92(5) transitional phase-in has completed.

    The multiplier is a published number, so it is written here as one. Reading it
    from the pack and comparing it to itself would confirm nothing.
    """
    # Arrange
    summary = run(IRB_MIX, FULLY_PHASED_IN_REGIME).output_floor_summary
    assert summary is not None, "the floored regime produced no output floor summary"

    # Assert
    assert summary.floor_pct == pytest.approx(FULLY_PHASED_IN_FLOOR_PCT), (
        f"the fully-phased-in output floor multiplier is {summary.floor_pct}, not "
        f"{FULLY_PHASED_IN_FLOOR_PCT}"
    )


def test_the_transitional_multiplier_is_below_the_fully_phased_in_one():
    """Art. 92(5): before 2030 the multiplier is lower, so the floor bites less.

    Pinned because a phase-in that silently jumped to its end state would raise
    capital across the industry on a date nobody chose.
    """
    # Arrange
    transitional = run(IRB_MIX, "B31").output_floor_summary
    final = run(IRB_MIX, FULLY_PHASED_IN_REGIME).output_floor_summary
    assert transitional is not None
    assert final is not None

    # Assert
    assert transitional.floor_pct < final.floor_pct, (
        f"the 2027 transitional multiplier ({transitional.floor_pct}) is not below the "
        f"fully-phased-in one ({final.floor_pct})"
    )


# ---------------------------------------------------------------------------
# Post-floor discipline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", FLOORED_REGIMES)
@pytest.mark.parametrize("portfolio_name", tuple(CORPUS))
def test_rwa_final_already_carries_the_floor_shortfall(portfolio_name: str, regime: str):
    """The ledger total equals the floor summary's own post-floor total.

    ``rwa_final`` is post-floor: the shortfall has already been distributed across
    the floor-eligible legs. So the portfolio sum must reconcile to
    ``total_rwa_post_floor``, and anything downstream that adds a floor impact on
    top is counting the same capital twice.
    """
    # Arrange
    portfolio = CORPUS[portfolio_name]
    summary = run(portfolio, regime).output_floor_summary
    if summary is None:
        pytest.skip("no floor-eligible exposure in this portfolio")
    ledger_total = float(results_df(portfolio, regime)["rwa_final"].fill_null(0.0).sum())

    # Assert
    assert ledger_total == pytest.approx(summary.total_rwa_post_floor, rel=1e-9, abs=0.005), (
        f"the ledger totals {ledger_total:,.2f} but the floor summary reports "
        f"{summary.total_rwa_post_floor:,.2f} post-floor under {regime} — one of them is not "
        f"post-floor, and adding a floor impact to the other would double-count it"
    )


@pytest.mark.parametrize("regime", FLOORED_REGIMES)
@pytest.mark.parametrize("portfolio_name", tuple(CORPUS))
def test_the_floor_shortfall_lands_only_on_floor_eligible_legs(portfolio_name: str, regime: str):
    """Standardised legs carry no floor add-on: their RWEA is their own.

    The floor compares modelled capital to its standardised equivalent, so a leg
    that IS standardised has nothing to floor. If a pro-rata distribution reached
    it, the floor would be re-weighting exposures the floor does not apply to.
    """
    # Arrange
    portfolio = CORPUS[portfolio_name]
    summary = run(portfolio, regime).output_floor_summary
    if summary is None:
        pytest.skip("no floor-eligible exposure in this portfolio")
    df = results_df(portfolio, regime)

    # Act
    sa_rwa = float(
        df.filter(pl.col("reporting_approach") == "standardised")["rwa_final"].fill_null(0.0).sum()
    )

    # Assert
    assert sa_rwa == pytest.approx(summary.sa_rwa_total, rel=1e-9, abs=0.005), (
        f"the standardised legs total {sa_rwa:,.2f} but the floor summary recorded "
        f"{summary.sa_rwa_total:,.2f} as un-floorable under {regime}"
    )


def test_the_published_trea_is_not_floored_a_second_time():
    """C 02.00 row 0010 equals the ledger sum — no floor add-on is applied twice.

    The portfolio is built so the floor definitely BINDS (very low PD and LGD
    against a 100%-weighted standardised equivalent), because the identity is
    trivially true when it does not — a vacuous pass here would look exactly like
    a real one. Row 0010 is the published total risk exposure amount; ``rwa_final``
    already carries the distributed shortfall, so a template that added
    ``floor_impact_rwa`` on top would report the same capital twice.
    """
    # Arrange
    portfolio = tuple(
        ExposureSpec(
            entity_type="corporate",
            drawn=drawn,
            external_cqs=None,
            internal_pd=0.0005,
            firm_lgd=0.05,
            maturity_years=1.0,
            annual_revenue=900_000_000.0,
        )
        for drawn in (10_000_000.0, 20_000_000.0, 30_000_000.0)
    )
    summary = run(portfolio, FULLY_PHASED_IN_REGIME).output_floor_summary
    assert summary is not None
    assert summary.portfolio_floor_binding, (
        "the floor no longer binds on this portfolio, so the test would pass vacuously — "
        f"u_trea {summary.u_trea:,.2f} vs threshold {summary.floor_threshold:,.2f}"
    )
    ledger_total = float(
        results_df(portfolio, FULLY_PHASED_IN_REGIME)["rwa_final"].fill_null(0.0).sum()
    )

    # Act
    c02 = corep_bundle(portfolio, FULLY_PHASED_IN_REGIME).c_02_00
    assert c02 is not None, "C 02.00 was not emitted at all"
    published = c02.filter(pl.col("row_ref") == "0010")["0010"][0]

    # Assert
    assert float(published) == pytest.approx(ledger_total, rel=1e-9, abs=0.005), (
        f"C 02.00 row 0010 publishes {float(published):,.2f} against a post-floor ledger total "
        f"of {ledger_total:,.2f}; the floor shortfall of {summary.shortfall:,.2f} has been "
        f"counted twice"
    )


@settings(max_examples=FLOOR_EXAMPLES)
@given(portfolio=portfolios())
def test_post_floor_rwea_is_never_below_the_modelled_total_on_generated_books(
    portfolio: tuple[ExposureSpec, ...],
):
    """The floor identity on portfolios nobody designed.

    ``rwa_pre_floor`` is the per-leg modelled figure the floor stage consumed;
    summing it and comparing to ``rwa_final`` states the Art. 92 para 2A maximum
    at the level a consumer actually reads.
    """
    # Arrange
    df = results_df(portfolio, FULLY_PHASED_IN_REGIME)
    if "rwa_pre_floor" not in df.columns:
        pytest.skip("no floor-eligible exposure in this portfolio")

    # Act
    pre_floor = float(df["rwa_pre_floor"].fill_null(0.0).sum())
    post_floor = float(df["rwa_final"].fill_null(0.0).sum())

    # Assert
    assert post_floor >= pre_floor - MONEY_TOLERANCE, (
        f"post-floor RWEA {post_floor:,.2f} is below the modelled total {pre_floor:,.2f} — the "
        f"output floor released capital"
    )
