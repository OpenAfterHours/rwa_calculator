"""
Monotonicity: perturb one risk driver, hold the rest, and check the direction.

Pipeline position:
    base portfolio -> perturb ONE field -> PipelineOrchestrator (once per rung)
        -> compare the portfolio total along the ladder

What this proves:
Each of these is an independent statement of regulatory intent, not an arithmetic
consequence of the code. More exposure, a worse borrower, a worse recovery or a
longer horizon cannot require LESS capital; more eligible protection cannot
require MORE. A direction reversal is a defect even when every individual number
looks plausible, and no recorded expected value can detect one.

Each property is checked along a LADDER rather than on a single pair, so one
example buys several comparisons and a reversal is localised to its rung.

WHICH QUANTITY THE DIRECTION IS STATED ON — this is the load-bearing decision in
this module. The IRB parameter properties are stated on the OWN FUNDS REQUIREMENT
(8% of TREA plus the Art. 36(1)(d) EL-shortfall CET1 deduction), not on RWEA
alone. RWEA alone is genuinely NOT monotone in PD under Basel 3.1: when the
output floor binds, PS1/26 Art. 92 para 2A sets the threshold at
``floor_pct x S-TREA + OF-ADJ`` with ``OF-ADJ = 12.5 x (... - CET1 deduction ...)``,
so a higher PD produces a larger EL shortfall, a more negative OF-ADJ, a LOWER
floor, and therefore LOWER published RWEA. Measured: PD 0.00195 -> 0.00293 moved
RWEA from 5,902.34 down to 5,853.52 while own funds stayed at exactly 480.00 in
both cases. That exactness is the tell — the OF-ADJ term is designed to cancel
the deduction, so the correct invariant is on capital, and asserting it on RWEA
would have been asserting against Art. 92 para 2A. Pinned below in
``test_own_funds_is_flat_in_pd_while_the_output_floor_binds``.

Directions deliberately NOT asserted, because the regulation does not imply them:
- Capital is NOT non-decreasing in PD across the whole [0, 1] range. K = LGD x
  N[...] - PD x LGD is an UNEXPECTED-loss measure, so as default approaches
  certainty the loss becomes expected — provisioned, not capitalised — and K
  falls back towards zero. Measured on this engine over a 0.02-step sweep, the
  risk weight peaks at PD 0.28 for every combination of class and maturity tried,
  under both regimes. Ladders therefore stay at or below
  ``strategies.MAX_PD_RUNG``; the turnover is pinned separately.
- RWEA is NOT unconditionally non-increasing in guarantee amount. CRR Art. 235
  substitution is mandatory, not elective, so a WORSE guarantor raises RWEA. Only
  the lower-risk-weight limb is asserted.

References:
- CRR Art. 153(1) / CRE31.1-6: the IRB risk-weight function and its inputs
- CRR Art. 162: effective maturity, and the maturity adjustment b(PD)
- CRR Art. 36(1)(d), Art. 159: the expected-loss shortfall CET1 deduction
- CRR Art. 193-194, 222-223: recognition of funded credit protection
- CRR Art. 235: substitution of the protection provider's risk weight
- PRA PS1/26 Art. 92 para 2A: the output floor and OF-ADJ
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import assume, given, settings

from tests.properties.portfolios import ExposureSpec, own_funds_requirement, total_rwa
from tests.properties.strategies import MAX_PD_RUNG, irb_corporate_specs, unmitigated_specs

#: Relative tolerance on a comparison of two portfolio totals. Both sides are
#: sums over the same population under the same code path, so only float
#: reassociation separates them; a real reversal is orders of magnitude larger.
RELATIVE_TOLERANCE = 1e-9

#: Absolute floor on the tolerance, so a comparison of two near-zero totals does
#: not turn float dust into a direction reversal.
ABSOLUTE_TOLERANCE = 0.005

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

#: Perturbation properties run three pipeline runs per example, so the example
#: count is set per test rather than inherited from the profile.
LADDER_EXAMPLES = 3

#: Multipliers applied to the perturbed amount. Wide enough to cross a threshold
#: if one is in reach, which is the point — a discontinuity that reverses the
#: direction is exactly what this is looking for.
AMOUNT_STEPS: tuple[float, ...] = (1.0, 2.0, 5.0)
PD_STEPS: tuple[float, ...] = (1.0, 1.5, 2.0)
LGD_STEPS: tuple[float, ...] = (1.0, 1.3, 1.8)
MATURITY_RUNGS: tuple[float, ...] = (1.0, 2.5, 5.0)
COLLATERAL_SHARES: tuple[float, ...] = (0.0, 0.25, 0.60)
GUARANTEE_SHARES: tuple[float, ...] = (0.0, 0.3, 0.7)


# ---------------------------------------------------------------------------
# Exposure amount
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=unmitigated_specs())
def test_rwa_is_non_decreasing_in_exposure_amount(spec: ExposureSpec, regime: str):
    """Lending more to the same borrower cannot require less capital.

    RWEA = EAD x RW and the risk weight is a property of the obligor and the
    facility, not of the amount — except where a threshold intervenes (the
    Art. 123 retail limit, the Art. 501 SME supporting factor's two-tier split).
    Every one of those moves the weight UP or leaves it flat as the amount grows,
    so the direction survives them, and RWEA itself is the right quantity here:
    the floor scales with the book rather than cutting across it.
    """
    # Arrange
    ladder = [replace(spec, drawn=spec.drawn * step) for step in AMOUNT_STEPS]

    # Act
    totals = [total_rwa((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_decreasing(totals, AMOUNT_STEPS, "drawn amount", regime, spec)


# ---------------------------------------------------------------------------
# IRB risk parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=irb_corporate_specs())
def test_own_funds_is_non_decreasing_in_pd(spec: ExposureSpec, regime: str):
    """A worse borrower cannot require less capital, below the IRB curve's peak.

    The conditional-default term N[(N^-1(PD) + sqrt(R) N^-1(0.999)) / sqrt(1-R)]
    rises faster than the PD x LGD expected-loss deduction over the low-PD range
    where lending actually happens. Stated on own funds rather than RWEA for the
    Art. 92 para 2A reason in the module docstring.
    """
    # Arrange
    assert spec.internal_pd is not None
    ladder = [replace(spec, internal_pd=min(spec.internal_pd * f, MAX_PD_RUNG)) for f in PD_STEPS]

    # Act
    totals = [own_funds_requirement((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_decreasing(totals, PD_STEPS, "PD", regime, spec)


@settings(max_examples=LADDER_EXAMPLES)
@given(spec=irb_corporate_specs())
def test_rwa_is_non_decreasing_in_pd_where_no_output_floor_applies(spec: ExposureSpec):
    """The same direction on RWEA itself, under CRR — which has no output floor.

    Kept as well as the own-funds form so the RWEA statement is still asserted
    somewhere: under CRR nothing can absorb a reversal, so a defect in the IRB
    risk-weight function has nowhere to hide.
    """
    # Arrange
    assert spec.internal_pd is not None
    ladder = [replace(spec, internal_pd=min(spec.internal_pd * f, MAX_PD_RUNG)) for f in PD_STEPS]

    # Act
    totals = [total_rwa((rung,), "CRR") for rung in ladder]

    # Assert
    _assert_non_decreasing(totals, PD_STEPS, "PD", "CRR", spec)


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=irb_corporate_specs())
def test_own_funds_is_non_decreasing_in_lgd(spec: ExposureSpec, regime: str):
    """A worse recovery cannot require less capital.

    K is linear in LGD — K = LGD x (N[...] - PD) x maturity adjustment, and the
    bracket is non-negative because the conditional default rate is never below
    the unconditional one. Where the supervisory LGD applies instead of the firm's
    (F-IRB, Art. 161), the perturbation is simply ignored and the ladder is flat,
    which a non-decreasing property admits.
    """
    # Arrange
    assert spec.firm_lgd is not None
    ladder = [replace(spec, firm_lgd=min(spec.firm_lgd * f, 1.0)) for f in LGD_STEPS]

    # Act
    totals = [own_funds_requirement((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_decreasing(totals, LGD_STEPS, "LGD", regime, spec)


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=irb_corporate_specs())
def test_own_funds_is_non_decreasing_in_maturity(spec: ExposureSpec, regime: str):
    """A longer horizon cannot require less capital.

    The Art. 162 maturity adjustment (1 + (M - 2.5) b) / (1 - 1.5 b) is increasing
    in M for every b > 0, and b = (0.11852 - 0.05478 ln PD)^2 is positive
    everywhere. Retail carries no maturity adjustment at all, so the ladder is
    flat there rather than rising — also admitted.
    """
    # Arrange
    ladder = [replace(spec, maturity_years=years) for years in MATURITY_RUNGS]

    # Act
    totals = [own_funds_requirement((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_decreasing(totals, MATURITY_RUNGS, "effective maturity", regime, spec)


# ---------------------------------------------------------------------------
# Credit risk mitigation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=unmitigated_specs())
def test_rwa_is_non_increasing_in_eligible_collateral(spec: ExposureSpec, regime: str):
    """More eligible cash collateral cannot require more capital.

    Under the financial collateral comprehensive method the exposure after CRM is
    E* = max(0, E(1 + He) - C(1 - Hc - Hfx)) (Art. 223), non-increasing in C;
    under the F-IRB collateral method a larger C can only lower LGD*. Cash is used
    deliberately: it carries a zero supervisory haircut and a zero risk weight, so
    no substitution can make the covered portion WORSE than the obligor — which is
    the one way this direction could legitimately reverse.
    """
    # Arrange
    _assume_the_baseline_can_move(spec, regime)
    ladder = [
        replace(spec, collateral_value=spec.drawn * share, collateral_type="cash")
        for share in COLLATERAL_SHARES
    ]

    # Act
    totals = [total_rwa((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_increasing(totals, COLLATERAL_SHARES, "collateral value", regime, spec)


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=unmitigated_specs())
def test_rwa_is_non_increasing_in_guarantee_amount_from_a_better_guarantor(
    spec: ExposureSpec, regime: str
):
    """More cover from a 0%-weighted guarantor cannot require more capital.

    Art. 235 substitutes the protection provider's risk weight on the covered
    portion. The guarantor here is a CQS 1 central government (Art. 114(2), 0%),
    so every additional pound of cover moves exposure from the obligor's weight to
    zero. The conditional matters: substitution is mandatory, so a WORSE guarantor
    raises RWEA and the unconditional form of this property is false.
    """
    # Arrange
    _assume_the_baseline_can_move(spec, regime)
    ladder = [
        replace(
            spec,
            guarantee_amount=spec.drawn * share,
            guarantor_entity_type="sovereign",
            guarantor_cqs=1,
        )
        for share in GUARANTEE_SHARES
    ]

    # Act
    totals = [total_rwa((rung,), regime) for rung in ladder]

    # Assert
    _assert_non_increasing(totals, GUARANTEE_SHARES, "guarantee amount", regime, spec)


@pytest.mark.parametrize("regime", REGIME_NAMES)
@settings(max_examples=LADDER_EXAMPLES)
@given(spec=unmitigated_specs())
def test_a_strictly_better_guarantor_cannot_increase_rwa(spec: ExposureSpec, regime: str):
    """Swapping a guarantor for a strictly lower-weighted one cannot raise RWEA.

    Both legs carry the same cover amount, so the only difference is the weight
    substituted onto the covered portion: a CQS 1 central government (0% under
    Art. 114(2)) against a CQS 3 institution. This is the directional core of
    Art. 235 stated without reference to any amount.
    """
    # Arrange
    _assume_the_baseline_can_move(spec, regime)
    cover = spec.drawn * 0.5
    worse = replace(
        spec, guarantee_amount=cover, guarantor_entity_type="institution", guarantor_cqs=3
    )
    better = replace(
        spec, guarantee_amount=cover, guarantor_entity_type="sovereign", guarantor_cqs=1
    )

    # Act
    rwa_worse = total_rwa((worse,), regime)
    rwa_better = total_rwa((better,), regime)

    # Assert
    assert rwa_better <= rwa_worse * (1 + RELATIVE_TOLERANCE) + ABSOLUTE_TOLERANCE, (
        f"a 0%-weighted sovereign guarantor produced MORE capital ({rwa_better:,.2f}) than a "
        f"CQS 3 institution guarantor ({rwa_worse:,.2f}) under {regime} for {spec}"
    )


# ---------------------------------------------------------------------------
# Recorded features that look like non-monotonicities and are not defects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_the_irb_curve_turns_over_at_high_pd_by_construction(regime: str):
    """Pinned: capital FALLS as PD approaches certainty, and that is correct.

    Recorded so nobody "fixes" it. K is unexpected loss only — the PD x LGD term
    is expected loss, covered by provisions rather than by capital — so at
    PD = 0.99 a senior unsecured corporate needs roughly LGD x 0.01 of capital.
    A property suite that asserted PD monotonicity across the whole range would be
    asserting against CRR Art. 153(1) itself.
    """
    # Arrange
    base = ExposureSpec(
        entity_type="corporate",
        drawn=10_000_000.0,
        external_cqs=None,
        internal_pd=0.25,
        firm_lgd=0.45,
        maturity_years=5.0,
        annual_revenue=900_000_000.0,
    )

    # Act
    at_peak = total_rwa((base,), regime)
    near_certainty = total_rwa((replace(base, internal_pd=0.99),), regime)

    # Assert
    assert near_certainty < at_peak, (
        "the IRB capital function no longer falls back towards zero as PD approaches 1 — "
        f"PD 0.25 gave {at_peak:,.2f} and PD 0.99 gave {near_certainty:,.2f} under {regime}"
    )


def test_own_funds_is_flat_in_pd_while_the_output_floor_binds():
    """Pinned: with the floor binding, capital is EXACTLY 8% x floor_pct x S-TREA.

    The reason the PD properties above are stated on own funds. Substituting
    ``OF-ADJ = -12.5 x CET1 deduction`` into
    ``0.08 x (floor_pct x S-TREA + OF-ADJ) + CET1 deduction`` cancels the deduction
    identically, leaving ``0.08 x floor_pct x S-TREA`` — a figure with no IRB
    parameter in it. So while the floor binds, published RWEA falls as PD rises
    and the capital requirement does not move at all. That is Art. 92 para 2A
    working, not a defect; this test exists so a future reader meeting the falling
    RWEA does not "correct" it.
    """
    # Arrange — a book small and modelled enough that the floor binds at both rungs
    base = ExposureSpec(
        entity_type="corporate",
        drawn=10_000.0,
        maturity_years=0.5,
        external_cqs=None,
        internal_pd=0.001953125,
        firm_lgd=0.5,
    )
    worse = replace(base, internal_pd=0.0029296875)

    # Act
    rwa_base = total_rwa((base,), "B31")
    rwa_worse = total_rwa((worse,), "B31")
    capital_base = own_funds_requirement((base,), "B31")
    capital_worse = own_funds_requirement((worse,), "B31")

    # Assert
    assert rwa_worse < rwa_base, (
        "the floor-binding RWEA no longer falls as PD rises — re-derive the OF-ADJ cancellation "
        f"before changing this test ({rwa_base:,.2f} -> {rwa_worse:,.2f})"
    )
    assert abs(capital_worse - capital_base) <= ABSOLUTE_TOLERANCE, (
        "own funds moved while the output floor was binding, so OF-ADJ no longer cancels the "
        f"EL-shortfall deduction: {capital_base:,.4f} -> {capital_worse:,.4f}"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _assume_the_baseline_can_move(spec: ExposureSpec, regime: str) -> None:
    """Discard an example whose unmitigated RWEA is already zero.

    A mitigation property is VACUOUS on a 0%-weighted obligor: measured, a
    sovereign, a listed MDB (Art. 117(2)), an international organisation
    (Art. 118) and a UK RGLA all carry 0.00 of RWEA at every collateral level, so
    "adding protection did not increase capital" is true of a quantity that was
    never non-zero. Those examples would count as passes and evidence nothing —
    `.claude/LESSONS.md` C2, applied to this suite rather than to the estate.

    ``assume`` DISCARDS the example rather than asserting on it, so the property's
    reported passes are only the ones where a reversal was possible.
    """
    assume(total_rwa((replace(spec, collateral_value=0.0, guarantee_amount=0.0),), regime) > 0.0)


def _assert_non_decreasing(
    totals: list[float],
    rungs: tuple[float, ...],
    driver: str,
    regime: str,
    spec: ExposureSpec,
) -> None:
    """Fail naming the rung where the ladder went the wrong way."""
    for i in range(len(totals) - 1):
        assert totals[i + 1] >= totals[i] * (1 - RELATIVE_TOLERANCE) - ABSOLUTE_TOLERANCE, (
            f"capital FELL when {driver} rose from {rungs[i]} to {rungs[i + 1]} under {regime}: "
            f"{totals[i]:,.2f} -> {totals[i + 1]:,.2f} for {spec}"
        )


def _assert_non_increasing(
    totals: list[float],
    rungs: tuple[float, ...],
    driver: str,
    regime: str,
    spec: ExposureSpec,
) -> None:
    """Fail naming the rung where the ladder went the wrong way."""
    for i in range(len(totals) - 1):
        assert totals[i + 1] <= totals[i] * (1 + RELATIVE_TOLERANCE) + ABSOLUTE_TOLERANCE, (
            f"capital ROSE when {driver} rose from {rungs[i]} to {rungs[i + 1]} under {regime}: "
            f"{totals[i]:,.2f} -> {totals[i + 1]:,.2f} for {spec}"
        )
