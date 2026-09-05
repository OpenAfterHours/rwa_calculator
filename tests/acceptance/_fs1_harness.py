"""
Shared harness for the FS-1 facility-share acceptance tests.

Pipeline position:
    (test support) tests/fixtures/facility_share_portfolio.py -> this module
        -> tests/acceptance/test_fs1_facility_share_fanout.py
        -> tests/acceptance/test_fs1_facility_share_presence.py

Holds two things the two FS-1 acceptance modules share: a memoised runner that
turns one (framework, variant, election) combination into plain Python, and the
ten adequacy assertions from Section 5 of the scenario of record.

Each adequacy helper is a claim about the FIXTURE, asserted with its reason in
the message. A test whose fixture cannot express the condition under test has
been vacuous since the day it was written (LESSONS C11), and these are what stop
that. They live here rather than in the test modules so that the two modules
cannot drift into asserting different adequacy conditions for the same portfolio.

The results are read into dicts rather than kept as a Polars frame on purpose:
under CRR the floor carriers are ABSENT from the frame, not null, and a dict plus
an explicit column list keeps the difference between "absent" and "null" visible
at every call site.

References:
- .claude/state/fs1-scenario-proposal.md Section 5 — the adequacy assertions.
- docs/plans/facility-share-riskiest-member.md — the design of record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance import _fs1_expectations as fx
from tests.fixtures.facility_share_portfolio import (
    CP_IRB,
    CP_LOW,
    CP_SA,
    DRAWN_ANCHOR,
    DRAWN_IRB,
    FAC_SHARE,
    FAC_SOLO,
    LN_ANCHOR,
    LN_IRB,
    build_facility_share_bundle,
    facility_share_config,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

SHARE_UNDRAWN = f"{FAC_SHARE}_UNDRAWN"
SOLO_UNDRAWN = f"{FAC_SOLO}_UNDRAWN"

#: The floor-eligible rows once the share has been resolved to a modelled member.
ELIGIBLE_WITH_SHARE = (LN_IRB, LN_ANCHOR, SHARE_UNDRAWN)

#: Relative tolerance. The goldens in this estate compare at 1e-9 and the
#: derivation agrees with the engine to ~1e-11, so nothing here needs slack.
RTOL = 1e-9

#: The four registered runs, in the order they appear in the supervisory gate.
ALL_RUNS = [
    ("CRR", "binding"),
    ("CRR", "nonbinding"),
    ("BASEL_3_1", "binding"),
    ("BASEL_3_1", "nonbinding"),
]

# ---------------------------------------------------------------------------
# Running the portfolio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One pipeline run, read into plain Python so absence is visible."""

    framework: str
    variant: str
    metric: str
    columns: tuple[str, ...]
    rows: dict[str, dict[str, Any]]
    total_rwa: float
    result: AggregatedResultBundle

    @property
    def share(self) -> dict[str, Any]:
        """The surviving undrawn row of the SHARED facility."""
        return self.rows[SHARE_UNDRAWN]

    @property
    def resolution(self) -> list[dict[str, Any]] | None:
        """The per-candidate audit frame, or ``None`` when the bundle has none.

        Read through ``getattr`` deliberately: on pre-change code the field does
        not exist on ``AggregatedResultBundle`` at all, and a test that raises
        ``AttributeError`` reports a broken test rather than a missing feature.
        """
        frame = getattr(self.result, "facility_share_resolution", None)
        return None if frame is None else frame.collect().to_dicts()

    def summary_field(self, name: str) -> Any:
        """One field of ``OutputFloorSummary``, ``None`` when absent or unset."""
        return getattr(self.result.output_floor_summary, name, None)


_CACHE: dict[tuple[str, str, str], Case] = {}


def run_case(framework: str, variant: str, metric: str = "floor_aware") -> Case:
    """Run one (framework, variant, election) combination, memoised per module."""
    key = (framework, variant, metric)
    if key in _CACHE:
        return _CACHE[key]

    result = PipelineOrchestrator().run_with_data(
        build_facility_share_bundle(variant),
        facility_share_config(framework, facility_share_metric=metric),
    )
    # An edge-contract violation reddens results wholesale and would otherwise be
    # misread as a facility-share finding (LESSONS D3).
    assert not [error for error in result.errors if "contract violated" in error.message]

    frame = result.results.collect()
    case = Case(
        framework=framework,
        variant=variant,
        metric=metric,
        columns=tuple(frame.columns),
        rows={row["exposure_reference"]: row for row in frame.to_dicts()},
        total_rwa=float(frame["rwa_final"].sum()),
        result=result,
    )
    _CACHE[key] = case
    return case


# ---------------------------------------------------------------------------
# Adequacy assertions — Section 5 of the scenario of record
# ---------------------------------------------------------------------------
#
# Each is a claim about the FIXTURE, asserted with its reason in the message, in
# the shipped ``tests/unit/engine/test_reconciliation.py`` style. A test whose
# fixture cannot express the condition under test has been vacuous since the day
# it was written (LESSONS C11), and these are what stop that.


def adequacy_three_candidates(case: Case) -> None:
    """(1) The share has three candidates and the solo facility has none."""
    resolution = case.resolution
    assert resolution is not None, (
        "the bundle carries no facility_share_resolution frame, so nothing in "
        "this test observes which member was chosen or why - RED until S3 lands"
    )
    share = [row for row in resolution if row["facility_share_group"] == FAC_SHARE]
    assert len(share) == 3, (
        f"expected 3 candidates on {FAC_SHARE}, got {len(share)}: fewer than "
        "three means the facility OWNER was not admitted as a member and "
        "decision D3 is untested - and the owner is assignment A's winner"
    )
    assert not [row for row in resolution if row["facility_share_group"] == FAC_SOLO], (
        f"{FAC_SOLO} has one member and must not be fanned out; a resolution row "
        "for it means the share DETECTION rule admits single-member facilities"
    )


def adequacy_divergence_chain() -> None:
    """(2) ``u_IRB < u_SA < x . s_IRB`` — the whole scenario in one line."""
    members = fx.candidates("b31")
    u_irb = members[CP_IRB].u
    u_sa = members[CP_SA].u
    b_irb = members[CP_IRB].b
    assert b_irb is not None
    assert u_irb < u_sa < b_irb, (
        f"the divergence chain {u_irb:,.6f} < {u_sa:,.2f} < {b_irb:,.2f} is "
        "broken: if it does not hold, assignment A and assignment B pick the "
        "SAME member and the floor-aware metric is untested by this portfolio"
    )
    # Both margins stated, because a chain that holds by a rounding error would
    # make every downstream assertion a coin toss.
    assert (u_sa - u_irb) / u_sa > 0.5, "lower margin below 50% of u_SA"
    assert (b_irb - u_sa) / u_sa > 0.15, "upper margin below 15% of u_SA"


def adequacy_standardised_b_equals_u() -> None:
    """(3) A standardised candidate's floored-branch contribution is its own RWA."""
    for reference in (CP_SA, CP_LOW):
        member = fx.candidates("b31")[reference]
        assert member.b == member.u, (
            f"{reference} is standardised, so it sits OUTSIDE the Art. 92(2A) "
            f"max at full weight and b_i must equal u_i ({member.u:,.2f}); if "
            "the resolver scales it by x the floored branch is wrong"
        )


def adequacy_no_ties() -> None:
    """(4) The three ``u_i`` and the three ``b_i`` are pairwise distinct by >= 10%.

    Stated against the SMALLER of each pair. The tightest pair is the F-IRB
    candidate against the CQS-1 member, whose gap is 15.6% of the smaller value
    but only 13.5% of the larger; a threshold quoted against the larger value
    would fail on that pair at 15%.
    """
    for label, values in (
        ("u_i", sorted(member.u for member in fx.candidates("b31").values())),
        ("b_i", sorted(member.b or 0.0 for member in fx.candidates("b31").values())),
    ):
        for smaller, larger in zip(values, values[1:], strict=False):
            gap = (larger - smaller) / smaller
            assert gap > 0.10, (
                f"{label} pair ({smaller:,.6f}, {larger:,.6f}) differ by only "
                f"{gap:.2%} of the smaller value; the tie-break chain is out of "
                "scope for this portfolio and a near-tie would exercise it silently"
            )


def adequacy_floor_state_matches_variant(case: Case) -> None:
    """(5) The variant name is a claim about the floor state — assert it first."""
    summary = case.result.output_floor_summary
    assert summary is not None, "Basel 3.1 runs must carry an OutputFloorSummary"
    if case.variant == "binding":
        assert summary.portfolio_floor_binding is True, (
            "the 'binding' variant must bind; if it does not, every assertion "
            "downstream of the floor state is about the wrong branch"
        )
        assert summary.shortfall > 0.0
    else:
        assert summary.portfolio_floor_binding is False, (
            "the 'nonbinding' variant must NOT bind; a bound floor here makes "
            "the pair a duplicate rather than the two-leg fixture LESSONS B5 asks for"
        )
        assert summary.shortfall == 0.0


def adequacy_variants_pick_different_members() -> None:
    """(6) The two Basel 3.1 variants pick DIFFERENT members, by stated margins.

    ``binding`` -> FS-CP-IRB, because ``TREA(B)`` exceeds ``TREA(A)`` by exactly
    19,200.00. ``nonbinding`` -> FS-CP-SA, because ``TREA(A)`` exceeds ``TREA(B)``
    by 53,756.13. If the two variants agreed on the winner, the pair would be a
    duplicate: the whole point of the second bundle is that ONE input — the
    non-member anchor's PD — flips the floor state and with it the allocation.

    Derivation-only, so it is green from the day it is written and stays green
    however the engine behaves. That is deliberate. It is a claim about the
    FIXTURE, and if a later edit to the anchor's PD or the members' ratings
    collapsed the two winners into one, every value test downstream would still
    pass while proving half of what it claims.

    The binding margin is EXACT — both floored branches are pinned by
    ``x . S_irb + OF-ADJ``, whose terms are integers on this portfolio — so it is
    asserted to the penny (``abs=1e-6``) rather than to a relative tolerance.

    ``abs=1e-6`` rather than bare ``==`` because the margin is a DIFFERENCE of
    two independently summed TREA totals, each a float accumulation over the
    portfolio: the terms are integers, the summation order is not pinned, and a
    single unit in the last place would fail an exact comparison. This is an
    adequacy assertion, so an ULP failing it would block every value test
    downstream of it at a claim about the fixture rather than about the engine.
    A penny is four orders of magnitude tighter than any real term could move.
    """
    binding_a, binding_b = fx.assignment_a("binding"), fx.assignment_b("binding")
    free_a, free_b = fx.assignment_a("nonbinding"), fx.assignment_b("nonbinding")

    assert fx.chosen_b31("binding").winner != fx.chosen_b31("nonbinding").winner, (
        "the two variants pick the SAME member, so the pair is a duplicate and "
        "the floor-aware metric is not distinguished from the own-approach one"
    )
    assert binding_b.total_rwa_post_floor - binding_a.total_rwa_post_floor == pytest.approx(
        19_200.00, abs=1e-6
    ), (
        f"binding TREA(B) - TREA(A) is "
        f"{binding_b.total_rwa_post_floor - binding_a.total_rwa_post_floor:,.6f}, "
        "not the exact 19,200.00 the integer floored branches give; a non-exact "
        "margin means a term that should be an integer no longer is"
    )
    assert free_a.total_rwa_post_floor - free_b.total_rwa_post_floor > 50_000.0, (
        "the nonbinding margin has narrowed below 50,000; assignment A wins "
        "there only because the floor does not bind, and a thin margin would "
        "make that outcome sensitive to float summation order"
    )


def adequacy_floor_basis_is_non_uniform() -> None:
    """(7) The pro-rata basis is non-uniform, and the headroom is THIN — say so.

    ``rwa_pre_floor / sa_rwa`` is the anchor's own-to-SA-equivalent ratio against
    the share candidate's. If those two were equal, a pro-rata allocation on the
    WRONG basis (uniform ``x . sa_rwa``, say) would land on the same numbers and
    the allocation assertions would prove nothing.

    Only 4.5% of headroom above the asserted minimum of 2.0. If you change
    ``FS-CP-ANCHOR``'s PD, re-measure this ratio in the SAME commit — tuning it
    downward narrows the ratio and silently disarms the check.
    """
    ratio = fx.firb_risk_weight("b31", fx.ANCHOR_PD_BINDING) / fx.firb_risk_weight(
        "b31", fx.PD_IRB_VALUE
    )
    assert ratio > 2.0, (
        f"anchor-to-candidate own/SA-equivalent ratio is {ratio:.4f}; below 2.0 "
        "a wrong pro-rata basis becomes indistinguishable from the right one"
    )


def adequacy_no_pd_floor_and_no_supporting_factor(case: Case) -> None:
    """(8) No PD floor binds and no supporting factor applies."""
    regime = "crr" if case.framework == "CRR" else "b31"
    floor = fx.corporate_pd_floor(regime)
    for reference, row in case.rows.items():
        if row.get("pd_floored") is not None:
            assert row["pd_floored"] > floor, (
                f"{reference} sits at or below the Art. 160(1) PD floor "
                f"({floor}); a floored PD makes the derived risk weight a "
                "function of the floor rather than of the fixture's own input"
            )
        assert row["is_sme"] is False, f"{reference} is an SME — Art. 501 relief is out of scope"
    if case.framework == "CRR":
        for reference, row in case.rows.items():
            if row.get("approach_applied") == "standardised":
                assert row["rwa_pre_factor"] == row["rwa_post_factor"], (
                    f"{reference} carries a supporting factor; the metric is "
                    "post-factor RWA and a live factor would confound it"
                )


def adequacy_retail_granularity_is_inert(case: Case) -> None:
    """(9) Every row is corporate; the Art. 123A limb is a Basel 3.1 concern only.

    Written to the MEASUREMENT, not to the intuition. ``exposure_class`` is
    ``corporate`` on every row in both regimes, and that is the invariant that
    keeps Art. 123A out of the picture. ``qualifies_as_retail`` is pinned False
    on the Basel 3.1 arm ONLY: under CRR it is True on five of the six rows,
    because the CRR flag tracks the Art. 123 SIZE limit and only the 2m anchor
    exceeds it. Pinning it in both regimes would fail before any change is made,
    and an adequacy assertion that fails is one a later wave weakens rather than
    corrects.
    """
    for reference, row in case.rows.items():
        assert row["exposure_class"] == "corporate", (
            f"{reference} is not corporate; a retail row would engage the "
            "Art. 123A(1)(b)(ii) granularity denominator, which this portfolio "
            "structurally cannot carry (retail's 75% exceeds every floor step)"
        )
    if case.framework != "CRR":
        for reference, row in case.rows.items():
            assert row["qualifies_as_retail"] is False, (
                f"{reference} qualifies as retail under Basel 3.1; measured "
                "uniformly False on this portfolio"
            )
        config = facility_share_config("BASEL_3_1")
        assert config.enforce_retail_granularity is True, (
            "the Basel 3.1 arm must run with production's granularity default; "
            "registering this portfolio in the supervisory gate against a config "
            "that softens a feature its assertions describe is LESSONS B5's "
            "third form - registered, wrong config, dead cell"
        )


def adequacy_pool_b_does_not_move_ead(case: Case) -> None:
    """(10) ``other_own_funds_reductions`` is Pool-B-only — measured delta 0.0.

    Kept as a standing guard on a SETTLED fact. If a future change makes the
    column reduce exposure value, every number in this scenario re-bases and the
    proposal's Section 3.5 contingency arithmetic applies instead.
    """
    assert case.rows[LN_IRB]["ead_final"] == DRAWN_IRB
    assert case.rows[LN_ANCHOR]["ead_final"] == DRAWN_ANCHOR
