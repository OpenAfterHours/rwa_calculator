"""
Homogeneity: scaling the whole book by k scales RWEA by k — except at a threshold.

Pipeline position:
    base portfolio -> multiply every amount by k -> PipelineOrchestrator
        -> compare total RWEA against k x the base total

What this proves:
Away from a threshold, capital is a linear function of size: RWEA = EAD x RW and
the risk weight depends on the obligor, the facility and the protection — none of
which is an amount. So a doubled book needs exactly double the capital, and any
deviation means a size-dependent term has leaked into a weight.

Why the exceptions are asserted rather than avoided:
The regulation contains deliberate discontinuities — the Art. 501 SME supporting
factor's two-tier split, the Art. 123 retail exposure limit — and each is a
policy choice about where a firm's treatment changes. Each is worth pinning in
its OWN right, because a silent change to one is a capital change nobody asked
for. Asserting only the smooth case would leave those thresholds untested; here
the smooth case and each discontinuity are separate, named statements.

References:
- CRR Art. 113(1): RWEA = exposure value x risk weight
- CRR Art. 501: the SME supporting factor and its two-tier EUR 2.5m split
- CRR Art. 123 / PS1/26 Art. 123A: the retail exposure class limit
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings

from tests.properties.portfolios import ExposureSpec, scale_eads, total_rwa
from tests.properties.strategies import large_corporate_specs

#: Relative tolerance on the scaling identity. Both sides are sums over the same
#: population, so only float reassociation separates them.
RELATIVE_TOLERANCE = 1e-9

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

#: Two runs per example.
SCALE_EXAMPLES = 4

#: Scale factors. Both directions, so a term that only leaks in one is caught.
SCALE_FACTORS: tuple[float, ...] = (0.5, 3.0)


# ---------------------------------------------------------------------------
# The smooth case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
@pytest.mark.parametrize("k", SCALE_FACTORS)
@settings(max_examples=SCALE_EXAMPLES)
@given(spec=large_corporate_specs())
def test_scaling_a_threshold_free_book_scales_rwea_proportionally(
    spec: ExposureSpec, k: float, regime: str
):
    """RWEA(k x book) = k x RWEA(book) for a book with no threshold in reach.

    The subject is a large corporate: above the SME revenue ceiling so no
    supporting factor applies, not a natural person so the retail limit is not in
    play, and with no property collateral so no LTV band can move. Under those
    conditions nothing in either framework makes a risk weight depend on size, so
    the identity is exact rather than approximate.
    """
    # Arrange
    base = (spec,)
    scaled = scale_eads(base, k)

    # Act
    base_rwa = total_rwa(base, regime)
    scaled_rwa = total_rwa(scaled, regime)

    # Assert
    assert scaled_rwa == pytest.approx(k * base_rwa, rel=RELATIVE_TOLERANCE, abs=0.005), (
        f"scaling by {k} moved RWEA from {base_rwa:,.2f} to {scaled_rwa:,.2f} under {regime}, "
        f"not to {k * base_rwa:,.2f} — a size-dependent term has reached the risk weight for "
        f"{spec}"
    )


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_scaling_a_mixed_threshold_free_portfolio_scales_rwea_proportionally(regime: str):
    """The same identity across many obligor classes at once, deterministically.

    A multi-class portfolio rather than a single leg, because a size-dependent
    term could live in a portfolio-level step (the output floor's pro-rata
    distribution, the retail granularity denominator) rather than in a leg's own
    weight. Both are linear in the book, so the identity still holds exactly.
    """
    # Arrange
    base = (
        ExposureSpec(entity_type="sovereign", drawn=9_000_000.0, external_cqs=1),
        ExposureSpec(entity_type="institution", drawn=2_000_000.0, external_cqs=2),
        ExposureSpec(
            entity_type="corporate",
            drawn=5_000_000.0,
            external_cqs=3,
            annual_revenue=900_000_000.0,
        ),
        ExposureSpec(
            entity_type="corporate",
            drawn=20_000_000.0,
            external_cqs=None,
            internal_pd=0.01,
            firm_lgd=0.30,
            annual_revenue=900_000_000.0,
        ),
        ExposureSpec(entity_type="covered_bond", drawn=6_000_000.0, external_cqs=1),
    )
    scaled = scale_eads(base, 4.0)

    # Act
    base_rwa = total_rwa(base, regime)
    scaled_rwa = total_rwa(scaled, regime)

    # Assert
    assert scaled_rwa == pytest.approx(4.0 * base_rwa, rel=RELATIVE_TOLERANCE, abs=0.005), (
        f"scaling a mixed book by 4 moved RWEA from {base_rwa:,.2f} to {scaled_rwa:,.2f} under "
        f"{regime}, not to {4.0 * base_rwa:,.2f}"
    )


# ---------------------------------------------------------------------------
# The deliberate discontinuities
# ---------------------------------------------------------------------------


def test_the_sme_supporting_factor_breaks_homogeneity_by_design():
    """Art. 501: an SME book is NOT homogeneous, because the factor is two-tier.

    The supporting factor is 0.7619 on the portion of the exposure up to the
    EUR 2.5m threshold and 0.85 above it, so RWEA per pound rises as the book
    grows through the threshold and a scaled book carries MORE than k times the
    capital. Pinned as its own statement: this is a policy discontinuity, and a
    change to where it bites is a capital change that must be deliberate.

    CRR only — Basel 3.1 removes the supporting factors entirely.
    """
    # Arrange — 2.0m sits below the threshold, 8.0m well above it
    base = (ExposureSpec(entity_type="corporate", drawn=2_000_000.0, annual_revenue=20_000_000.0),)
    scaled = scale_eads(base, 4.0)

    # Act
    base_rwa = total_rwa(base, "CRR")
    scaled_rwa = total_rwa(scaled, "CRR")

    # Assert
    assert scaled_rwa > 4.0 * base_rwa * (1 + 1e-6), (
        "scaling an SME book through the Art. 501 EUR 2.5m threshold no longer costs more per "
        f"pound: {base_rwa:,.2f} x 4 = {4.0 * base_rwa:,.2f} but the scaled book carries "
        f"{scaled_rwa:,.2f}"
    )


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_the_retail_exposure_limit_breaks_homogeneity_by_design(regime: str):
    """Art. 123: a retail book is NOT homogeneous across the exposure limit.

    Below the limit a natural person's exposure takes the 75% retail weight;
    above it the obligor is no longer a regulatory retail exposure and takes the
    corporate weight. So scaling a retail book past the limit costs strictly more
    than k times the capital. Pinned in its own right — the limit is the reason
    the generated retail amounts stay below it elsewhere in this suite.
    """
    # Arrange — 400k is retail under both regimes; 4m is over both limits
    base = (ExposureSpec(entity_type="individual", drawn=400_000.0, external_cqs=None),)
    scaled = scale_eads(base, 10.0)

    # Act
    base_rwa = total_rwa(base, regime)
    scaled_rwa = total_rwa(scaled, regime)

    # Assert
    assert scaled_rwa > 10.0 * base_rwa * (1 + 1e-6), (
        f"scaling a retail obligor past the Art. 123 limit no longer reclassifies it under "
        f"{regime}: {base_rwa:,.2f} x 10 = {10.0 * base_rwa:,.2f} but the scaled book carries "
        f"{scaled_rwa:,.2f}"
    )
