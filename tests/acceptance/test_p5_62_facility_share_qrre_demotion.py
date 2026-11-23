"""
P5.62 — a facility-share candidate demotes its owner's card out of QRRE: measured.

Pipeline position:
    tests/fixtures/facility_share_qrre_portfolio.py -> PipelineOrchestrator
        -> AggregatedResultBundle (the owner's card row + facility_share_resolution)

What is measured
----------------
Under decision D4 (docs/plans/facility-share-riskiest-member.md) every
facility-share candidate row counts toward its own member's obligor aggregates
with no special-casing. The QRRE aggregate dedupes per (obligor, parent
facility), so the one member whose QRRE aggregate a candidate can move is the
facility OWNER holding no leg of its own under the shared facility — every other
member already carries the facility's limit through the leg that made it a
member. When the owner's candidate pushes the owner over the QRRE limit, EVERY
QRRE row of that owner falls to ``retail_other`` — including its own card, which
survives to the results while the candidate itself loses the share and is
dropped. The card is what these tests measure.

Rule text (verbatim, ``docs/assets/ps126app1.pdf``):
    PS1/26 Art. 147(5A): "Retail exposures shall be assigned to the qualifying
    revolving retail exposures exposure subclass ... if they meet the following
    conditions: (a) the exposures are to individuals; (b) the exposures are
    revolving, unsecured, and to the extent they are not drawn, immediately and
    unconditionally cancellable by the institution ... (c) the largest aggregate
    nominal exposure to a single individual, out of all aggregate nominal
    exposures to individuals in the sub-portfolio, is GBP 90,000 or less;"
    PS1/26 Art. 154(4): "For qualifying revolving retail exposures, as set out in
    Article 147(5A), a coefficient of correlation (R) of 0.04 shall replace the
    figure produced by the coefficient of correlation formula in paragraph 1."
    PS1/26 Art. 164(4)(b): "for unsecured retail exposures: (i) a flat 50% floor
    value for qualifying revolving retail exposures as set out in Article
    147(5A); and (ii) a flat 30% floor value for other unsecured retail
    exposures;"
CRR (watchfire snapshot of legislation.gov.uk — ``docs/assets/crr.pdf`` is empty
in this checkout):
    CRR Art. 154(4): "For qualifying revolving retail exposures in accordance with
    points (a) to (e), a coefficient of correlation R of 0,04 shall replace the
    figure produced by the correlation formula in paragraph 1." (c): "the maximum
    exposure to a single individual in the sub-portfolio is EUR 100 000 or less".

Measured (card EAD 60,000, own-approach RWEA; ``rwa_pre_floor`` under Basel 3.1):

    regime  group     owner PD / LGD   in QRRE      demoted      delta
    ------  --------  ---------------  -----------  -----------  ----------
    CRR     high_pd   10% / 60%        71,141.52    64,060.30    -7,081.22
    CRR     low_lgd    6% / 40%        34,829.02    38,290.60    +3,461.58
    B31     high_pd   10% / 60%        67,114.64    60,434.24    -6,680.39
    B31     low_lgd    6% / 40%        41,071.96    36,123.21    -4,948.75

The direction is regime-specific (LESSONS C7). Under CRR the only lever is the
correlation, and the two cross where the other-retail correlation equals 0.04 —
PD = ln(13)/35, about 7.33%. Under Basel 3.1 demotion ALSO drops the LGD input
floor from the QRRE value to the other-unsecured-retail value, so with a
modelled LGD below the QRRE floor the crossover falls (about 4.74% at a 40%
LGD): the ``low_lgd`` owner's demotion RAISES RWA under CRR and LOWERS it under
Basel 3.1. The SA-equivalent does not move with the QRRE class
(``engine/sa/risk_weights.py`` keys on the retail class and the transactor flag),
so a binding output floor could hide the fall; hence the pre-floor carrier.

Reading the measurement
-----------------------
The demotion is the rule's outcome, not a defect: an owner who may draw the whole
shared line has that line in its aggregate nominal exposure under Art.
147(5A)(c) / 154(4)(c), and ``test_owner_is_demoted_identically_on_an_unshared_facility``
shows the owner is demoted to the penny on an unshared facility with the same
limit. The headroom differs (30,000 shared; 50,000 unshared, where the member's
loan is left unmapped). The result does not, because the aggregate sums each
row's ``facility_limit``, not its headroom, so the owner's candidate contributes
exactly what its own undrawn row would. A change that kept such owners in QRRE
would be RWA-REDUCING at ordinary PDs and would need its own regulatory argument.

Fail-first evidence
-------------------
These pin current behaviour, so they are green on arrival. Their red is the
isolating mutation ``tests/mutations/mutate_qrre_aggregate_counts_no_share_candidate.py``
(candidate rows excluded from the QRRE aggregate), under which the owner's card
stays in QRRE in the ``cancellable`` state, in each regime separately::

    PYTHONPATH=tests/mutations uv run pytest <this file> -p mutate_qrre_aggregate_counts_no_share_candidate

References:
- CRR Art. 154(1), 154(4)(a)-(c); PS1/26 Art. 147(5A), 154(1)(b), 154(4),
  163(1), 164(4)(b).
- docs/specifications/facility-share-allocation.md — the disclosed residual.
- IMPLEMENTATION_PLAN.md: P5.62.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.facility_share_qrre_portfolio import (
    ALL_VARIANTS,
    DRAWN_CARD,
    DRAWN_MEMBER,
    GROUPS,
    HIGH_PD,
    LIMIT_CARD,
    LIMIT_SHARE,
    LOW_LGD,
    FacilityShareQrreVariant,
    OwnerGroup,
    build_facility_share_qrre_bundle,
    facility_share_qrre_config,
)
from tests.oracle.derivations import formulas as oracle

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

FRAMEWORKS = ("CRR", "BASEL_3_1")

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value

#: Own-approach RWEA. CRR has no output floor, so ``rwa_final`` IS the own-approach
#: figure; under Basel 3.1 ``rwa_pre_floor`` keeps the measurement off the S-TREA
#: leg, which a QRRE demotion does not move.
_OWN_RWEA_CARRIER = {"CRR": "rwa_final", "BASEL_3_1": "rwa_pre_floor"}

#: The derivation agrees with the engine to ~1e-11 (statistics.NormalDist against
#: polars-normal-stats), so nothing here needs slack beyond the estate's 1e-9.
RTOL = 1e-9

#: The measured direction of the demotion, per regime and group: -1 lowers the
#: card's RWA, +1 raises it. Stated, not derived, so a sign flip is a failure.
_DIRECTION: dict[tuple[str, str], int] = {
    ("CRR", HIGH_PD.key): -1,
    ("CRR", LOW_LGD.key): +1,
    ("BASEL_3_1", HIGH_PD.key): -1,
    ("BASEL_3_1", LOW_LGD.key): -1,
}


# ---------------------------------------------------------------------------
# Running the portfolio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    """One pipeline run, read into plain Python so absent and null stay distinct."""

    columns: frozenset[str]
    rows: dict[str, dict[str, Any]]
    resolution: tuple[dict[str, Any], ...]


@functools.cache
def _run(framework: str, variant: FacilityShareQrreVariant) -> _Run:
    """Run one (framework, variant) through the full pipeline, memoised per process."""
    result = PipelineOrchestrator().run_with_data(
        build_facility_share_qrre_bundle(variant),
        facility_share_qrre_config(framework),
    )
    # An edge-contract violation reddens results wholesale and would otherwise be
    # misread as a classification finding (LESSONS D3).
    assert not [error for error in result.errors if "contract violated" in error.message]
    frame = result.results.collect()
    resolution = result.facility_share_resolution
    return _Run(
        columns=frozenset(frame.columns),
        rows={row["exposure_reference"]: row for row in frame.to_dicts()},
        resolution=() if resolution is None else tuple(resolution.collect().to_dicts()),
    )


def _card(framework: str, variant: FacilityShareQrreVariant, group: OwnerGroup) -> dict[str, Any]:
    """The owner's card row — the measured, surviving sibling."""
    rows = _run(framework, variant).rows
    assert group.card_loan in rows, (
        f"{group.card_loan} is missing from the {framework}/{variant} results; the "
        "measured row must survive to the output in every variant"
    )
    return rows[group.card_loan]


def _own_rwea(framework: str, variant: FacilityShareQrreVariant, group: OwnerGroup) -> float:
    """The card's own-approach RWEA, read from the regime's carrier (present, non-null)."""
    carrier = _OWN_RWEA_CARRIER[framework]
    assert carrier in _run(framework, variant).columns, (
        f"{carrier} is absent from the {framework} results frame - reading another "
        "carrier in its place would measure a different quantity"
    )
    value = _card(framework, variant, group)[carrier]
    assert value is not None
    return float(value)


# ---------------------------------------------------------------------------
# Hand-calculation — oracle formulas, every value from the run's own rulepack
# ---------------------------------------------------------------------------


@functools.cache
def _pack(framework: str) -> ResolvedRulepack:
    """The resolved rulepack the run itself uses."""
    return RulepackV0.from_config(facility_share_qrre_config(framework)).pack


def _qrre_limit(framework: str) -> float:
    """The Art. 147(5A)(c) / 154(4)(c) per-individual limit in GBP, from the pack."""
    config = facility_share_qrre_config(framework)
    return float(regulatory_threshold(_pack(framework), "qrre_max_limit", config.eur_gbp_rate))


def _retail_risk_weight(framework: str, pd: float, lgd: float, *, qrre: bool) -> float:
    """A-IRB retail risk weight for a non-transactor unsecured revolver, in or out of QRRE.

    PD floor: Art. 163(1) — the QRRE revolver key or the other-retail key. LGD
    input floor: Art. 164(4)(b)(i)/(ii), applied only where the pack's
    ``airb_lgd_floor`` Feature is on (Basel 3.1; CRR has none). Correlation:
    Art. 154(4) fixed QRRE value or the Art. 154(1) other-retail curve. Scaling
    factor: the pack's ``irb_scaling_factor`` (1.06 under CRR, removed by PS1/26).
    """
    pack = _pack(framework)
    pd_floor = pack.formula("pd_floors").params["retail_qrre_revolver" if qrre else "retail_other"]
    pd_applied = max(pd, float(pd_floor))
    lgd_applied = lgd
    if pack.feature("airb_lgd_floor"):
        lgd_floor = pack.formula("lgd_floors").params[
            "retail_qrre_unsecured" if qrre else "retail_other_unsecured"
        ]
        lgd_applied = max(lgd, float(lgd_floor))
    correlation = oracle.CORRELATION_RETAIL_QRRE if qrre else oracle.correlation_retail(pd_applied)
    return oracle.irb_risk_weight_retail(
        pd_value=pd_applied,
        lgd=lgd_applied,
        correlation=correlation,
        scaling_factor=float(pack.scalar("irb_scaling_factor")),
    )


def _expected_card_rwea(framework: str, group: OwnerGroup, *, qrre: bool) -> float:
    """The card's RWEA: drawn balance (no conversion factor) x retail risk weight."""
    return DRAWN_CARD * _retail_risk_weight(framework, group.owner_pd, group.lgd, qrre=qrre)


def _crossover_pd(framework: str, lgd: float) -> float:
    """The owner PD at which demotion leaves the card's RWA unchanged (bisection).

    Below it demotion raises RWA, above it demotion lowers it — on the domain this
    scenario uses, where the other-retail curve starts above 0.04 and decays past
    it. Bracketed on [0.1%, 30%] and checked to change sign across the bracket.
    """

    def demotion_delta(pd: float) -> float:
        return _retail_risk_weight(framework, pd, lgd, qrre=False) - _retail_risk_weight(
            framework, pd, lgd, qrre=True
        )

    low, high = 0.001, 0.30
    assert demotion_delta(low) > 0 > demotion_delta(high), "the bracket holds no crossover"
    for _ in range(200):
        mid = (low + high) / 2.0
        if demotion_delta(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


# ---------------------------------------------------------------------------
# Adequacy — the fixture can express the condition under test (LESSONS C11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_card_alone_is_within_the_qrre_limit_and_card_plus_share_is_not(framework: str) -> None:
    """The owner crosses the limit ONLY by adding the share's limit — in each regime."""
    # Arrange
    limit = _qrre_limit(framework)

    # Act / Assert
    assert limit >= LIMIT_CARD, (
        f"the card limit {LIMIT_CARD:,.0f} exceeds the {framework} QRRE limit "
        f"{limit:,.2f}: the card would be demoted with no share at all"
    )
    assert limit < LIMIT_CARD + LIMIT_SHARE, (
        f"card plus share {LIMIT_CARD + LIMIT_SHARE:,.0f} is within the {framework} "
        f"QRRE limit {limit:,.2f}: the share's limit could never demote the card"
    )
    assert DRAWN_MEMBER < LIMIT_SHARE, "the share has no headroom, so it emits no candidate row"


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_owner_holds_no_leg_under_its_shared_facility(variant: FacilityShareQrreVariant) -> None:
    """The owner's candidate is its ONLY route to the share's limit (input shape).

    A loan or contingent of the owner under the share would inherit the share's
    limit and carry it into the owner's aggregate by itself; the candidate would
    then dedupe to nothing and the scenario would measure that leg instead.
    """
    # Arrange
    bundle = build_facility_share_qrre_bundle(variant)
    loan_owner = dict(
        bundle.loans.select("loan_reference", "counterparty_reference").collect().iter_rows()
    )

    # Act
    under_share = [
        (mapping["parent_facility_reference"], loan_owner.get(mapping["child_reference"]))
        for mapping in bundle.facility_mappings.collect().to_dicts()
    ]

    # Assert
    for group in GROUPS:
        assert (group.share_facility, group.owner) not in under_share, (
            f"{group.owner} holds a leg under {group.share_facility}; its candidate "
            "would dedupe to nothing and this scenario would prove nothing about it"
        )
    contingents = bundle.contingents
    assert contingents is None or contingents.collect().height == 0


@pytest.mark.parametrize("variant", ["cancellable", "not_cancellable"])
@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.key)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_owner_candidate_loses_the_share(
    framework: str, group: OwnerGroup, variant: FacilityShareQrreVariant
) -> None:
    """The owner's candidate is a LOSER: the demotion is caused by a dropped row.

    That is the D4 path in its sharpest form — the row that demotes the card never
    reaches the results — and holding the winner fixed across both states keeps a
    winner change from confounding anything.
    """
    # Arrange
    run = _run(framework, variant)

    # Act
    candidates = {
        row["exposure_reference"]: row
        for row in run.resolution
        if row["facility_share_group"] == group.share_facility
    }

    # Assert
    assert set(candidates) == {group.owner_candidate, group.member_candidate}, (
        f"{group.share_facility} should fan out to its owner and its member, got "
        f"{sorted(candidates)}"
    )
    assert candidates[group.member_candidate]["is_winner"] is True
    assert candidates[group.owner_candidate]["is_winner"] is False
    assert group.owner_candidate not in run.rows
    assert run.rows[group.share_undrawn]["counterparty_reference"] == group.member


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.key)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_card_leaves_qrre_only_when_the_owners_candidate_joins_the_sub_portfolio(
    framework: str, group: OwnerGroup
) -> None:
    """Two states, one toggled input: the owner's card actually flips (LESSONS C11).

    ``not_cancellable``: the candidate fails the Art. 147(5A)(b) gate, so it is not
    in the QRRE sub-portfolio and adds nothing to the aggregate — the card stays
    QRRE. ``cancellable``: the candidate passes, its limit joins the owner's
    aggregate, and the card is demoted.
    """
    # Arrange / Act
    kept = _card(framework, "not_cancellable", group)["exposure_class"]
    demoted = _card(framework, "cancellable", group)["exposure_class"]

    # Assert
    assert (kept, demoted) == (_QRRE, _RETAIL_OTHER), (
        f"{framework}/{group.key}: expected the card to be QRRE without the candidate "
        f"and retail_other with it, got {kept} -> {demoted}"
    )


@pytest.mark.parametrize("variant", ALL_VARIANTS)
@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.key)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_card_rwea_matches_the_hand_calculation(
    framework: str, group: OwnerGroup, variant: FacilityShareQrreVariant
) -> None:
    """Absolute own-approach RWEA of the card, in or out of QRRE, against the oracle."""
    # Arrange
    in_qrre = variant == "not_cancellable"
    expected = _expected_card_rwea(framework, group, qrre=in_qrre)
    card = _card(framework, variant, group)

    # Act
    actual = _own_rwea(framework, variant, group)

    # Assert
    assert card["ead_final"] == pytest.approx(DRAWN_CARD, rel=RTOL)
    assert actual == pytest.approx(expected, rel=RTOL), (
        f"{framework}/{group.key}/{variant}: card RWEA {actual:,.6f} against a "
        f"{'QRRE' if in_qrre else 'retail_other'} hand-calc of {expected:,.6f}"
    )


@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.key)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_demotion_direction_is_regime_specific(framework: str, group: OwnerGroup) -> None:
    """The measured sign of the demotion's RWA effect, per regime and group.

    Paired with the absolute hand-calc above, so this is the headline of the
    measurement rather than a relative assertion standing alone (LESSONS C1).
    """
    # Arrange
    expected_sign = _DIRECTION[(framework, group.key)]

    # Act
    delta = _own_rwea(framework, "cancellable", group) - _own_rwea(
        framework, "not_cancellable", group
    )

    # Assert
    assert delta * expected_sign > 0, (
        f"{framework}/{group.key}: demotion moved the card's RWEA by {delta:+,.2f}, "
        f"expected sign {expected_sign:+d}"
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_owners_sit_where_the_crossovers_put_them(framework: str) -> None:
    """``high_pd`` is above both crossovers; ``low_lgd`` sits between them.

    Under CRR the crossover does not depend on LGD (no LGD floor; the scaling
    factor cancels). Under Basel 3.1 a modelled LGD below the QRRE floor pulls the
    crossover down — the channel the ``low_lgd`` group exists to exercise.
    """
    # Arrange / Act
    high_pd_crossover = _crossover_pd(framework, HIGH_PD.lgd)
    low_lgd_crossover = _crossover_pd(framework, LOW_LGD.lgd)

    # Assert
    assert HIGH_PD.owner_pd > high_pd_crossover
    if framework == "CRR":
        assert LOW_LGD.owner_pd < low_lgd_crossover
    else:
        assert LOW_LGD.owner_pd > low_lgd_crossover
        assert low_lgd_crossover < _crossover_pd("CRR", LOW_LGD.lgd)


@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.key)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_owner_is_demoted_identically_on_an_unshared_facility(
    framework: str, group: OwnerGroup
) -> None:
    """With headroom on the facility, sharing it does not move the owner.

    On an unshared facility the owner's ordinary undrawn row carries the facility
    limit into its aggregate exactly as its candidate does on a shared one, so the
    card's class and RWEA are the same to the penny: the fan-out lowers no owner's
    RWA relative to the same facility unshared. (A share drawn in full by another
    member emits no undrawn row at all — a separate discontinuity this scenario
    deliberately does not lean on.)
    """
    # Arrange
    unshared = _card(framework, "unshared", group)
    rows = _run(framework, "unshared").rows

    # Act
    unshared_rwea = _own_rwea(framework, "unshared", group)
    shared_rwea = _own_rwea(framework, "cancellable", group)

    # Assert
    assert rows[group.share_undrawn]["counterparty_reference"] == group.owner
    assert unshared["exposure_class"] == _RETAIL_OTHER
    assert unshared_rwea == pytest.approx(shared_rwea, rel=RTOL)
