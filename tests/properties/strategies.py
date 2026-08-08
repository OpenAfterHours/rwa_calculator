"""
Hypothesis strategies over the portfolio model.

Key responsibilities:
- Generate portfolios that a firm could plausibly hold, across the SA exposure
  classes, both approaches, on- and off-balance sheet, mitigated and not.
- Keep every generated amount finite and bounded, so a failure is about the
  calculation and not about float overflow.
- Offer narrowed strategies for the perturbation properties, which need a
  portfolio where the perturbed field is meaningful (an LGD perturbation on an
  F-IRB row proves nothing — the supervisory LGD ignores it).

A note on ranges, since they are the coverage this suite actually has:
- PD is generated in ``[0.0003, 0.20]``. The upper bound is deliberate and is
  documented at :data:`MAX_INCREASING_PD` — the Basel IRB capital function peaks
  at PD 0.28 on this engine and is genuinely decreasing above it.
- Retail drawn amounts stay under :data:`portfolios.RETAIL_MAX_DRAWN` so the
  Art. 123 / Art. 123A limit does not reclassify the obligor mid-property.

References:
- CRR Art. 153(1) / CRE31: the IRB risk-weight function
- CRR Art. 123, PS1/26 Art. 123A: the retail exposure limit
"""

from __future__ import annotations

from hypothesis import strategies as st

from tests.properties.portfolios import (
    IRB_ENTITY_TYPES,
    OFF_BS_RISK_TYPES,
    RETAIL_MAX_DRAWN,
    SA_ENTITY_TYPES,
    ExposureSpec,
)

#: The PD ceiling under which the IRB capital function is increasing in PD.
#:
#: K = LGD x N[...] - PD x LGD is an UNEXPECTED-loss measure: as PD approaches 1
#: the loss becomes fully expected and K falls back towards zero. MEASURED on
#: this engine over a 0.02-step sweep, the risk weight peaks at PD 0.28 for every
#: combination of {corporate, institution, sovereign} x M in {0.5, 1, 2.5, 5, 10}
#: under both regimes, and declines above it. Ladders therefore stay at or below
#: :data:`MAX_PD_RUNG`, comfortably inside the increasing arm; the turnover itself
#: is pinned separately (``test_monotonicity.py``) as a feature of the regulation
#: rather than something to be "fixed".
MAX_INCREASING_PD = 0.20

#: The highest PD any perturbation ladder may reach, measured peak 0.28 minus a
#: margin. A rung above this would be testing the decreasing arm of the curve.
MAX_PD_RUNG = 0.25

_AMOUNTS = st.floats(
    min_value=10_000.0, max_value=20_000_000.0, allow_nan=False, allow_infinity=False
)
_SMALL_AMOUNTS = st.floats(
    min_value=10_000.0, max_value=RETAIL_MAX_DRAWN, allow_nan=False, allow_infinity=False
)
_PDS = st.floats(
    min_value=0.0003, max_value=MAX_INCREASING_PD, allow_nan=False, allow_infinity=False
)
_LGDS = st.floats(min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False)
_MATURITIES = st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False)
_CQS = st.integers(min_value=1, max_value=6)
_REVENUE = st.floats(
    min_value=1_000_000.0, max_value=900_000_000.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


@st.composite
def exposure_specs(draw: st.DrawFn) -> ExposureSpec:
    """One arbitrary obligor — any SA class, either approach, on/off balance sheet."""
    entity_type = draw(st.sampled_from(SA_ENTITY_TYPES))
    is_person = entity_type == "individual"
    drawn = draw(_SMALL_AMOUNTS if is_person else _AMOUNTS)

    use_irb = entity_type in IRB_ENTITY_TYPES and draw(st.booleans())
    internal_pd = draw(_PDS) if use_irb else None
    external_cqs = None if use_irb else draw(st.one_of(st.none(), _CQS))
    firm_lgd = draw(st.one_of(st.none(), _LGDS)) if use_irb else None

    off_bs_nominal = draw(st.one_of(st.just(0.0), _AMOUNTS))
    collateral_value = draw(st.one_of(st.just(0.0), _AMOUNTS))
    guarantee_amount = draw(
        st.one_of(
            st.just(0.0),
            st.floats(min_value=10_000.0, max_value=drawn, allow_nan=False, allow_infinity=False),
        )
    )

    return ExposureSpec(
        entity_type=entity_type,
        drawn=drawn,
        off_bs_nominal=off_bs_nominal,
        off_bs_risk_type=draw(st.sampled_from(OFF_BS_RISK_TYPES)),
        maturity_years=draw(_MATURITIES),
        external_cqs=external_cqs,
        internal_pd=internal_pd,
        firm_lgd=firm_lgd,
        annual_revenue=draw(st.one_of(st.none(), _REVENUE)),
        is_defaulted=draw(st.booleans()),
        collateral_value=collateral_value,
        collateral_type=draw(st.sampled_from(("cash", "bond", "real_estate"))),
        guarantee_amount=guarantee_amount,
        guarantor_entity_type="sovereign",
        guarantor_cqs=1,
        provision_amount=0.0,
    )


def portfolios(min_size: int = 1, max_size: int = 5) -> st.SearchStrategy[tuple[ExposureSpec, ...]]:
    """A portfolio of arbitrary obligors, as a hashable tuple."""
    return st.lists(exposure_specs(), min_size=min_size, max_size=max_size).map(tuple)


@st.composite
def irb_corporate_specs(draw: st.DrawFn) -> ExposureSpec:
    """An IRB corporate/institution/sovereign row, unmitigated and drawn.

    The subject of the PD / LGD / maturity perturbations: unmitigated so the
    perturbation is not absorbed by a CRM cap, and never defaulted so the
    Art. 153(1) formula rather than the Art. 158 defaulted branch is under test.
    """
    return ExposureSpec(
        entity_type=draw(st.sampled_from(("corporate", "institution", "sovereign"))),
        drawn=draw(_AMOUNTS),
        maturity_years=draw(_MATURITIES),
        external_cqs=None,
        internal_pd=draw(_PDS),
        firm_lgd=draw(_LGDS),
        annual_revenue=draw(st.one_of(st.none(), _REVENUE)),
        is_defaulted=False,
    )


@st.composite
def unmitigated_specs(draw: st.DrawFn) -> ExposureSpec:
    """An arbitrary obligor with no CRM and no off-balance-sheet leg.

    Used where a property must isolate the exposure amount: with collateral or a
    guarantee present, changing EAD also changes the protected FRACTION, which is
    a second effect and a different statement.
    """
    entity_type = draw(st.sampled_from(SA_ENTITY_TYPES))
    is_person = entity_type == "individual"
    use_irb = entity_type in IRB_ENTITY_TYPES and draw(st.booleans())
    return ExposureSpec(
        entity_type=entity_type,
        drawn=draw(_SMALL_AMOUNTS if is_person else _AMOUNTS),
        maturity_years=draw(_MATURITIES),
        external_cqs=None if use_irb else draw(_CQS),
        internal_pd=draw(_PDS) if use_irb else None,
        firm_lgd=draw(_LGDS) if use_irb else None,
        annual_revenue=draw(st.one_of(st.none(), _REVENUE)),
        is_defaulted=draw(st.booleans()),
    )


@st.composite
def large_corporate_specs(draw: st.DrawFn) -> ExposureSpec:
    """A large (non-SME, non-retail) corporate with no threshold in reach.

    The homogeneity subject. Revenue is above the SME ceiling so no supporting
    factor applies, the obligor is not a natural person so the Art. 123 retail
    limit is not in play, and there is no property collateral so no LTV band can
    move when the amount scales.
    """
    return ExposureSpec(
        entity_type="corporate",
        drawn=draw(_AMOUNTS),
        off_bs_nominal=draw(st.one_of(st.just(0.0), _AMOUNTS)),
        off_bs_risk_type=draw(st.sampled_from(OFF_BS_RISK_TYPES)),
        maturity_years=draw(_MATURITIES),
        external_cqs=draw(st.one_of(st.none(), _CQS)),
        internal_pd=None,
        annual_revenue=900_000_000.0,
        is_defaulted=False,
    )
