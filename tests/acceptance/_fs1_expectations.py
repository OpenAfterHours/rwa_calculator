"""
FS-1 expectations — every asserted number DERIVED, none transcribed.

Pipeline position:
    (test support) tests/fixtures/facility_share_portfolio.py -> this module
        -> tests/acceptance/test_fs1_facility_share_fanout.py

Why this module exists
----------------------
The FS-1 scenario proposal (`.claude/state/fs1-scenario-proposal.md` Section 3.3)
carries a table of reference risk weights and portfolio totals. Its *previous*
revision carried the same table wrong in the fifth significant figure — roughly
``1e-5`` relative, against goldens compared at ``rtol 1e-9``. A test that
transcribed those literals would have failed against a CORRECT engine, and the
natural repairs (loosen the tolerance, or change the engine) are both wrong.

So nothing here is typed. The F-IRB risk weights are re-derived from
:mod:`statistics`' ``NormalDist`` — an implementation the engine does not use, so
the derivation is a genuine independent referee rather than a circular one — and
every downstream expectation (exposure amounts, ``u_i``, ``s_i``, ``b_i``,
U-TREA, S-TREA, the floor threshold, the pro-rata allocation, the portfolio
totals) is built arithmetically from those weights and the fixture's own input
amounts.

Every PARAMETERISED regulatory value comes from the resolved rulepack, which is
the value home: the supervisory LGD, the IRB scaling factor, the PD floors, the
SA corporate weights by CQS, the two conversion factors, and the output-floor
percentage. Each of those is an entry the pack owns and can change.

The coefficients of the Art. 153(1) risk-weight function itself are written here
as literals, and deliberately so. They are the ``-50.0`` correlation decay, the
``0.12`` / ``0.24`` correlation bounds, the ``0.11852`` / ``0.05478`` maturity-
adjustment coefficients, the ``1.5`` and ``2.5`` terms of the maturity
adjustment, the ``0.999`` confidence level and the ``12.5`` capital-to-RWA
multiplier. **The pack carries no entry for any of them**, so the only in-repo
alternative would be to import them from ``engine/irb/formulas.py`` — which is
the code under test, and would make this referee circular. They are transcribed
from the article text instead, which is the same choice
``tests/oracle/derivations/formulas.py`` makes for the same reason. If the pack
ever gains entries for them, read them from there.

References:
- CRR Art. 153(1) / PS1/26 Art. 153(1): the IRB risk-weight function.
- CRR Art. 161(1)(a) / PS1/26 Art. 161(1)(aa): the F-IRB supervisory LGD.
- CRR Art. 160(1) / PS1/26 Art. 160(1): the PD input floor.
- CRR Art. 122 Table 6 / PS1/26 Art. 122(2) Table 6: the SA corporate weights.
- CRR Art. 111 Annex I / PS1/26 Art. 111(1)(b) Table A1: the SA conversion factor.
- CRR Art. 166(8)(d) / PS1/26 Art. 166C(1): the F-IRB conversion factor.
- PS1/26 Art. 92(2A), 92(5): the output floor and its transitional schedule.
- docs/plans/facility-share-riskiest-member.md: the design of record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

from rwa_calc.domain.enums import CQS
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.facility_share_portfolio import (
    ANCHOR_PD,
    B31_REPORTING_DATE,
    CP_IRB,
    CP_LOW,
    CP_SA,
    CRR_REPORTING_DATE,
    DRAWN_ANCHOR,
    DRAWN_IRB,
    DRAWN_LOW,
    DRAWN_SOLO,
    EFFECTIVE_MATURITY,
    FAC_SHARE,
    FAC_SOLO,
    HEADROOM_SHARE,
    HEADROOM_SOLO,
    LN_ANCHOR,
    LN_IRB,
    LN_LOW,
    LN_SOLO,
    PD_IRB,
)

# ---------------------------------------------------------------------------
# Coefficients of the Art. 153(1) function — transcribed, because the pack has
# no entry for any of them and the only other in-repo source is the code under
# test. See the module docstring.
# ---------------------------------------------------------------------------

#: The supervisory confidence level in the Art. 153(1) conditional-PD term.
_CONFIDENCE = 0.999
#: Own funds -> risk-weighted exposure amount, Art. 92(4): 1 / 8%.
_RWA_PER_K = 12.5
#: Art. 153(1) correlation: R = 0.12.f(PD) + 0.24.(1 - f(PD)), with the
#: exponential weight f(PD) = (1 - e^(-50.PD)) / (1 - e^(-50)).
_CORRELATION_DECAY = -50.0
_CORRELATION_MIN = 0.12
_CORRELATION_MAX = 0.24
#: Art. 153(1) maturity adjustment: b = (0.11852 - 0.05478.ln(PD))^2, applied as
#: (1 + (M - 2.5).b) / (1 - 1.5.b).
_MATURITY_B_INTERCEPT = 0.11852
_MATURITY_B_SLOPE = 0.05478
_MATURITY_PIVOT = 2.5
_MATURITY_DENOMINATOR_FACTOR = 1.5

_CRR_PACK = resolve("crr", CRR_REPORTING_DATE)
_B31_PACK = resolve("b31", B31_REPORTING_DATE)

_PACKS = {"crr": _CRR_PACK, "b31": _B31_PACK}

#: Re-exported so a test can quote a fixture input without a second import.
PD_IRB_VALUE: float = PD_IRB
ANCHOR_PD_BINDING: float = ANCHOR_PD["binding"]


# ---------------------------------------------------------------------------
# Pack reads — the value home, never a literal
# ---------------------------------------------------------------------------


def supervisory_lgd(regime: str) -> float:
    """F-IRB supervisory LGD, senior unsecured, non-financial-sector obligor.

    CRR Art. 161(1)(a) / PS1/26 Art. 161(1)(aa), keyed exactly as the engine
    keys it: ``(collateral bucket, seniority, is_financial_sector_entity)``.
    """
    rows = dict(_PACKS[regime].decision("firb_supervisory_lgd").rows)
    return float(rows[("unsecured", "senior", False)])


def irb_scaling_factor(regime: str) -> float:
    """The Art. 153(1) scaling factor — 1.06 under CRR, removed by PS1/26."""
    return float(_PACKS[regime].scalar("irb_scaling_factor"))


def corporate_pd_floor(regime: str) -> float:
    """The Art. 160(1) corporate PD input floor."""
    return float(_PACKS[regime].formula("pd_floors").params["corporate"])


def corporate_sa_risk_weight(regime: str, cqs: int | None) -> float:
    """SA corporate risk weight by CQS — CRR Art. 122 Table 6 / PS1/26 Art. 122(2).

    ``cqs=None`` is the unrated row, which is what an obligor carrying only an
    internal rating takes for its SA-equivalent weight.
    """
    if regime == "crr":
        entries = dict(_CRR_PACK.lookup("corporate_risk_weights").entries)
        return float(entries[CQS.UNRATED if cqs is None else CQS(cqs)])
    entries = dict(_B31_PACK.lookup("b31_corporate_risk_weights").entries)
    return float(entries[cqs])


def sa_conversion_factor(regime: str) -> float:
    """The medium-risk commitment conversion factor both facilities select.

    CRR Art. 111(1) / Annex I para 2(b)(ii); PS1/26 Art. 111(1)(b) Table A1.
    """
    return float(dict(_PACKS[regime].lookup("sa_ccf").entries)["MR"])


def firb_conversion_factor(regime: str) -> float:
    """The conversion factor an F-IRB commitment takes.

    CRR Art. 166(8)(d) gives credit lines their own 75%. PS1/26 Art. 166C(1)
    routes F-IRB to the Standardised factor instead, which the pack expresses as
    the ``firb_uses_sa_ccf`` Feature — read the Feature, never the regime.
    """
    if _PACKS[regime].feature("firb_uses_sa_ccf"):
        return sa_conversion_factor(regime)
    return float(_PACKS[regime].scalar("firb_credit_line_ccf"))


def output_floor_pct(on: date = B31_REPORTING_DATE) -> float:
    """``x`` in Art. 92(2A), read off the Art. 92(5) transitional Schedule.

    Read at the reporting date exactly as ``aggregator.py::_output_floor_pct``
    reads it, so a Schedule step change moves the test and the engine together.
    """
    return float(_B31_PACK.schedule("output_floor_pct").resolve(on))


# ---------------------------------------------------------------------------
# The Art. 153(1) risk-weight function, re-derived from stdlib
# ---------------------------------------------------------------------------


def firb_risk_weight(regime: str, pd_value: float, maturity: float = EFFECTIVE_MATURITY) -> float:
    """Corporate F-IRB risk weight — CRR Art. 153(1) / PS1/26 Art. 153(1).

    No SME correlation adjustment (revenue is above both thresholds), no
    financial-institution multiplier, senior unsecured supervisory LGD.
    """
    normal = NormalDist()
    pd_floored = max(pd_value, corporate_pd_floor(regime))
    lgd = supervisory_lgd(regime)

    weight = (1.0 - math.exp(_CORRELATION_DECAY * pd_floored)) / (
        1.0 - math.exp(_CORRELATION_DECAY)
    )
    correlation = _CORRELATION_MIN * weight + _CORRELATION_MAX * (1.0 - weight)

    conditional = normal.cdf(
        (1.0 - correlation) ** -0.5 * normal.inv_cdf(pd_floored)
        + (correlation / (1.0 - correlation)) ** 0.5 * normal.inv_cdf(_CONFIDENCE)
    )
    k = lgd * conditional - pd_floored * lgd

    b = (_MATURITY_B_INTERCEPT - _MATURITY_B_SLOPE * math.log(pd_floored)) ** 2
    maturity_adj = (1.0 + (maturity - _MATURITY_PIVOT) * b) / (
        1.0 - _MATURITY_DENOMINATOR_FACTOR * b
    )

    return k * _RWA_PER_K * irb_scaling_factor(regime) * maturity_adj


def expected_loss(regime: str, pd_value: float, ead: float) -> float:
    """CRR Art. 158 expected loss — ``PD x LGD x EAD`` at the supervisory LGD."""
    return max(pd_value, corporate_pd_floor(regime)) * supervisory_lgd(regime) * ead


# ---------------------------------------------------------------------------
# Per-row expectations for the FS-1 portfolio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One member's priced candidate row for the shared facility."""

    counterparty: str
    approach: str
    ead: float
    risk_weight: float
    #: Own-approach pre-floor RWA — the CRR metric and assignment A's.
    u: float
    #: SA-equivalent RWA. ``None`` under CRR, where the column is not produced.
    s: float | None
    #: The floored-branch contribution ``b_i``. ``None`` under CRR.
    b: float | None


def candidates(regime: str) -> dict[str, Candidate]:
    """The three share candidates, keyed by member reference.

    ``b_i`` follows ONE predicate: ``x . s_i`` if and only if the row's applied
    approach is floor-eligible, otherwise ``u_i``. A standardised row sits
    outside the Art. 92(2A) max at full weight, so its floored-branch
    contribution is its own RWA and cannot move with the floor state.
    """
    sa_ccf = sa_conversion_factor(regime)
    firb_ccf = firb_conversion_factor(regime)
    is_b31 = regime == "b31"
    x = output_floor_pct() if is_b31 else None

    def standardised(reference: str, cqs: int) -> Candidate:
        ead = HEADROOM_SHARE * sa_ccf
        weight = corporate_sa_risk_weight(regime, cqs)
        rwa = ead * weight
        return Candidate(reference, "standardised", ead, weight, rwa, rwa if is_b31 else None, rwa)

    ead_irb = HEADROOM_SHARE * firb_ccf
    weight_irb = firb_risk_weight(regime, PD_IRB)
    s_irb = ead_irb * corporate_sa_risk_weight(regime, None) if is_b31 else None
    return {
        CP_SA: standardised(CP_SA, 2),
        CP_LOW: standardised(CP_LOW, 1),
        CP_IRB: Candidate(
            CP_IRB,
            "foundation_irb",
            ead_irb,
            weight_irb,
            ead_irb * weight_irb,
            s_irb,
            None if s_irb is None or x is None else x * s_irb,
        ),
    }


def drawn_rwa(regime: str, variant: str) -> dict[str, float]:
    """Own-approach RWA on the four drawn loans plus the solo facility's undrawn."""
    sa_ccf = sa_conversion_factor(regime)
    return {
        LN_IRB: DRAWN_IRB * firb_risk_weight(regime, PD_IRB),
        LN_LOW: DRAWN_LOW * corporate_sa_risk_weight(regime, 1),
        LN_SOLO: DRAWN_SOLO * corporate_sa_risk_weight(regime, 2),
        LN_ANCHOR: DRAWN_ANCHOR * firb_risk_weight(regime, ANCHOR_PD[variant]),
        f"{FAC_SOLO}_UNDRAWN": HEADROOM_SOLO * sa_ccf * corporate_sa_risk_weight(regime, 2),
    }


def drawn_sa_equivalent(regime: str, variant: str) -> dict[str, float]:
    """SA-equivalent RWA on the same rows — the S-TREA basis. Basel 3.1 only."""
    sa_ccf = sa_conversion_factor(regime)
    unrated = corporate_sa_risk_weight(regime, None)
    return {
        LN_IRB: DRAWN_IRB * unrated,
        LN_LOW: DRAWN_LOW * corporate_sa_risk_weight(regime, 1),
        LN_SOLO: DRAWN_SOLO * corporate_sa_risk_weight(regime, 2),
        LN_ANCHOR: DRAWN_ANCHOR * unrated,
        f"{FAC_SOLO}_UNDRAWN": HEADROOM_SOLO * sa_ccf * corporate_sa_risk_weight(regime, 2),
    }


_MODELLED = (LN_IRB, LN_ANCHOR)


def non_share_totals(regime: str, variant: str) -> tuple[float, float, float]:
    """``(U0, S0, SA0)`` — the book outside the share.

    ``U0``/``S0`` are summed over the floor-eligible rows only; the standardised
    rows sit outside the Art. 92(2A) max at full weight in ``SA0``. That is the
    ENGINE's formula (``_floor.py``), which sums both totals over floor-eligible
    rows and re-adds the SA book unscaled — it agrees with Art. 92(2A) only at
    ``x = 1`` and is more binding otherwise. The deviation is a recorded
    out-of-scope finding (design doc Section 10 item 1); every number here is
    computed against the engine's form deliberately.
    """
    own = drawn_rwa(regime, variant)
    u0 = sum(own[reference] for reference in _MODELLED)
    sa0 = sum(value for reference, value in own.items() if reference not in _MODELLED)
    if regime == "crr":
        return u0, 0.0, sa0
    equivalent = drawn_sa_equivalent(regime, variant)
    return u0, sum(equivalent[reference] for reference in _MODELLED), sa0


@dataclass(frozen=True)
class Assignment:
    """One end-to-end evaluation of the Basel 3.1 book under a chosen winner."""

    winner: str
    u_trea: float
    s_trea: float
    of_adj: float
    floor_threshold: float
    shortfall: float
    floored_modelled_rwa: float
    sa_rwa_total: float
    total_rwa_post_floor: float
    binding: bool
    #: ``{exposure_reference: rwa_final}`` over the floor-eligible rows.
    eligible_rwa: dict[str, float]


def evaluate_b31(variant: str, winner: str) -> Assignment:
    """Evaluate the Basel 3.1 book end-to-end with ``winner`` holding the share.

    Mirrors ``apply_floor_with_impact``: the shortfall is distributed pro-rata by
    each floor-eligible row's SA-equivalent RWA. The OF-ADJ expected-loss channel
    is recomputed per assignment, because Pool B covers the two drawn F-IRB
    loans' expected loss exactly and the winning candidate's own expected loss is
    uncovered (``FACILITY_SCHEMA`` carries no Pool B column) — which is what
    makes the floored branch non-additive and P2 a bound rather than a closed
    form.
    """
    x = output_floor_pct()
    u0, s0, sa0 = non_share_totals("b31", variant)
    candidate = candidates("b31")[winner]
    eligible = candidate.approach != "standardised"

    own = drawn_rwa("b31", variant)
    equivalent = drawn_sa_equivalent("b31", variant)
    share_reference = f"{FAC_SHARE}_UNDRAWN"

    u_trea = u0 + (candidate.u if eligible else 0.0)
    s_trea = s0 + (candidate.s or 0.0 if eligible else 0.0)
    sa_rwa_total = sa0 + (0.0 if eligible else candidate.u)

    # Pool B covers both drawn F-IRB loans exactly; only a MODELLED winner adds
    # uncovered expected loss, and only through the CET1 deduction limb.
    cet1_deduction = expected_loss("b31", PD_IRB, candidate.ead) if eligible else 0.0
    of_adj = _RWA_PER_K * (0.0 - cet1_deduction - 0.0 + 0.0)

    floor_threshold = x * s_trea + of_adj
    shortfall = max(0.0, floor_threshold - u_trea)
    floored = u_trea + shortfall

    basis = {reference: equivalent[reference] for reference in _MODELLED}
    rwa = {reference: own[reference] for reference in _MODELLED}
    if eligible:
        basis[share_reference] = candidate.s or 0.0
        rwa[share_reference] = candidate.u
    total_basis = sum(basis.values())
    eligible_rwa = {
        reference: value + shortfall * basis[reference] / total_basis
        for reference, value in rwa.items()
    }

    return Assignment(
        winner=winner,
        u_trea=u_trea,
        s_trea=s_trea,
        of_adj=of_adj,
        floor_threshold=floor_threshold,
        shortfall=shortfall,
        floored_modelled_rwa=floored,
        sa_rwa_total=sa_rwa_total,
        total_rwa_post_floor=floored + sa_rwa_total,
        binding=shortfall > 0.0,
        eligible_rwa=eligible_rwa,
    )


def assignment_a(variant: str) -> Assignment:
    """Assignment A — every group by ``argmax u_i``, evaluated end-to-end."""
    return evaluate_b31(variant, _argmax(candidates("b31"), lambda c: c.u))


def assignment_b(variant: str) -> Assignment:
    """Assignment B — every group by ``argmax b_i``, evaluated end-to-end."""
    return evaluate_b31(variant, _argmax(candidates("b31"), lambda c: c.b or 0.0))


def chosen_b31(variant: str) -> Assignment:
    """The P2 outcome: the larger of ``TREA(A)`` and ``TREA(B)``, ties to A."""
    first, second = assignment_a(variant), assignment_b(variant)
    return second if second.total_rwa_post_floor > first.total_rwa_post_floor else first


def crr_winner() -> str:
    """The CRR winner — ``argmax u_i``, with no floor and no ``sa_rwa``."""
    return _argmax(candidates("crr"), lambda c: c.u)


def crr_portfolio_total(variant: str) -> float:
    """CRR portfolio total ``rwa_final``: additive, no floor."""
    own = drawn_rwa("crr", variant)
    return sum(own.values()) + candidates("crr")[crr_winner()].u


def crr_cet1_deduction(variant: str) -> float:
    """CRR CET1 deduction — ``max(0, SIGMA EL - Pool B)`` at the CRR LGD.

    Pool B is set on the two drawn F-IRB loans to their BASEL 3.1 expected loss,
    so under CRR (LGD 45% against 40%) a residual shortfall survives, and the
    winning candidate's own expected loss adds to it only when the winner is
    modelled. Asserted rather than assumed: it is the only place the
    drop-before-the-EL-summary requirement is observable under CRR.
    """
    lgd_b31 = supervisory_lgd("b31")
    pool_b = PD_IRB * lgd_b31 * DRAWN_IRB + ANCHOR_PD[variant] * lgd_b31 * DRAWN_ANCHOR
    total_el = expected_loss("crr", PD_IRB, DRAWN_IRB) + expected_loss(
        "crr", ANCHOR_PD[variant], DRAWN_ANCHOR
    )
    winner = candidates("crr")[crr_winner()]
    if winner.approach != "standardised":
        total_el += expected_loss("crr", PD_IRB, winner.ead)
    return max(0.0, total_el - pool_b)


def _argmax(rows: dict[str, Candidate], key) -> str:  # noqa: ANN001 - local sort key
    """``argmax`` over the candidates with the design of record's tie-break tail.

    Own metric desc, then ``risk_weight`` desc, then ``counterparty_reference``
    asc. This portfolio exercises no tie (adequacy assertion 4 pins the margins),
    so the tail is here for shape rather than for effect.
    """
    return min(rows.values(), key=lambda c: (-key(c), -c.risk_weight, c.counterparty)).counterparty


__all__ = [
    "ANCHOR_PD_BINDING",
    "PD_IRB_VALUE",
    "Assignment",
    "Candidate",
    "assignment_a",
    "assignment_b",
    "candidates",
    "chosen_b31",
    "corporate_pd_floor",
    "corporate_sa_risk_weight",
    "crr_cet1_deduction",
    "crr_portfolio_total",
    "crr_winner",
    "drawn_rwa",
    "drawn_sa_equivalent",
    "evaluate_b31",
    "expected_loss",
    "firb_conversion_factor",
    "firb_risk_weight",
    "irb_scaling_factor",
    "non_share_totals",
    "output_floor_pct",
    "sa_conversion_factor",
    "supervisory_lgd",
]
