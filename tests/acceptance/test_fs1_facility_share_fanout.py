"""
FS-1 — a facility share's undrawn is priced against the riskiest member.

Pipeline position:
    Loader -> HierarchyResolver (candidate FAN-OUT) -> Classifier -> CRMProcessor
        -> SA / IRB calculators -> OutputAggregator (candidate RESOLUTION,
        before the output floor) -> AggregatedResultBundle

What is under test
------------------
Today the winner of a facility share is chosen in the hierarchy stage by an
SA-only *preview* risk weight that knows nothing about the member's approach,
PD/LGD, exposure class, CRM or the output floor. The design of record replaces
it with **compute, then choose**: the hierarchy emits one undrawn candidate row
per member, the candidates are classified, CRM-adjusted and priced as ordinary
rows, and a resolution step at the head of the aggregator keeps one and drops the
rest — before the floor is applied.

The allocation rule itself is **firm policy, not regulation**. Neither CRR nor
PS1/26 defines a facility share or prescribes how to attribute a commitment that
several obligors may draw, so this file carries no ``@cites``-worthy claim of its
own; the EAD it produces cites the conversion-factor articles, and the output
floor arithmetic cites Art. 92(2A).

Under CRR capital is additive and the winner is ``argmax`` own-approach RWA.
Under Basel 3.1 the floor is a portfolio-level ``max``, so "riskiest" is
state-dependent: the engine evaluates two whole-book assignments — every group by
``argmax u_i`` (A) and every group by ``argmax b_i`` (B) — end to end and keeps
the larger. A firm election (``facility_share_metric="own_approach"``) pins A.

Why every number here is DERIVED
--------------------------------
Nothing below is transcribed from the scenario proposal. The F-IRB weights are
re-derived from ``statistics.NormalDist`` plus rulepack values in
``tests/acceptance/_fs1_expectations.py``, and every downstream figure is built
arithmetically from those. The proposal's previous revision carried its whole
expected-output surface wrong at ``1e-5`` relative against an engine that agrees
with an independent derivation to ``3e-11``; a test that transcribed those
literals would have failed against a CORRECT engine.

References:
- docs/plans/facility-share-riskiest-member.md — the design of record (D1-D5).
- .claude/state/fs1-scenario-proposal.md — FS-1 rev. 3, the scenario of record.
- PS1/26 Art. 92(2A), Art. 92(5) — the output floor and its phase-in.
- CRR Art. 166(8)(d) / PS1/26 Art. 166C(1) — the F-IRB conversion factor.
- tests/fixtures/facility_share_portfolio.py — the portfolio.
"""

from __future__ import annotations

import pytest

from tests.acceptance import _fs1_expectations as fx
from tests.acceptance._fs1_harness import (
    ELIGIBLE_WITH_SHARE,
    RTOL,
    SHARE_UNDRAWN,
    adequacy_divergence_chain,
    adequacy_floor_basis_is_non_uniform,
    adequacy_floor_state_matches_variant,
    adequacy_no_pd_floor_and_no_supporting_factor,
    adequacy_no_ties,
    adequacy_pool_b_does_not_move_ead,
    adequacy_retail_granularity_is_inert,
    adequacy_standardised_b_equals_u,
    adequacy_three_candidates,
    adequacy_variants_pick_different_members,
    run_case,
)
from tests.fixtures.facility_share_portfolio import CP_IRB, CP_SA

# ---------------------------------------------------------------------------
# CRR — P0, own-approach RWA, no floor
# ---------------------------------------------------------------------------


class TestFacilityShareUnderCRR:
    """Under CRR capital is additive, so the winner is ``argmax`` own RWA."""

    @pytest.mark.parametrize("variant", ["binding", "nonbinding"])
    def test_facility_share_crr_picks_own_approach_winner(self, variant: str) -> None:
        """
        The CQS-2 OWNER wins on own-approach RWA, ahead of the F-IRB member.

        Arrange: the FS-1 portfolio under CRR at the 2025 reporting date.
        Act:     run the full pipeline.
        Assert:  the surviving undrawn row belongs to FS-CP-SA, is standardised,
                 carries the Art. 111 medium-risk EAD at the Art. 122 CQS-2
                 weight, and the portfolio total is the derived sum.

        Red today: the SA preview ranks the unrated F-IRB member at 100% above
        the CQS-1 member at 20% and hands it the row, which is then priced at its
        true 27.57% F-IRB weight — the anti-conservative case the rule exists for.

        Mutation it detects (a): ``argmax`` -> ``argmin`` on the own-approach
        metric moves the winner to FS-CP-LOW and the undrawn RWA to 40,000.00.
        """
        # Arrange
        case = run_case("CRR", variant)
        adequacy_no_pd_floor_and_no_supporting_factor(case)
        adequacy_retail_granularity_is_inert(case)
        adequacy_pool_b_does_not_move_ead(case)
        adequacy_three_candidates(case)

        winner = fx.candidates("crr")[fx.crr_winner()]

        # Act
        row = case.share

        # Assert — ownership, routing and the priced amount all move together.
        assert row["counterparty_reference"] == CP_SA
        assert row["original_counterparty_reference"] == CP_SA
        assert row["approach_applied"] == "standardised"
        assert row["exposure_class"] == "corporate"
        assert row["ead_final"] == pytest.approx(winner.ead, rel=RTOL)
        assert row["ccf"] == pytest.approx(fx.sa_conversion_factor("crr"), rel=RTOL)
        assert row["risk_weight"] == pytest.approx(winner.risk_weight, rel=RTOL)
        assert row["rwa_final"] == pytest.approx(winner.u, rel=RTOL)
        assert case.total_rwa == pytest.approx(fx.crr_portfolio_total(variant), rel=RTOL)

    @pytest.mark.parametrize("variant", ["binding", "nonbinding"])
    def test_facility_share_crr_undrawn_rwa_is_the_own_approach_winner_amount(
        self, variant: str
    ) -> None:
        """
        The undrawn row's obligor and RWA alone, with no audit frame in the way.

        Arrange: the FS-1 portfolio under CRR.
        Act:     read the surviving FS-FAC-SHARE_UNDRAWN row and the portfolio total.
        Assert:  the obligor is FS-CP-SA and the RWA is its derived own-approach
                 figure, and the portfolio total follows.

        This asserts the SAME outcome as
        ``test_facility_share_crr_picks_own_approach_winner`` and deliberately
        duplicates it, because that test puts the adequacy assertions first and
        the audit-frame precondition is red until the aggregator slice lands. So
        the headline movement — +17,281.27 on the portfolio total — would be
        asserted by nothing OBSERVABLE until then, and a hierarchy slice that
        shipped without moving the winner could pass every red test by making
        them red for a different reason.

        No adequacy call, no ``case.resolution``, nothing that needs the
        resolution step to exist. Red today on the number itself: the undrawn row
        carries 82,718.73 against FS-CP-IRB where the rule gives 100,000.00
        against FS-CP-SA.
        """
        # Arrange
        case = run_case("CRR", variant)
        winner = fx.candidates("crr")[fx.crr_winner()]

        # Act
        row = case.share

        # Assert — the AMOUNT first, so the failure text carries the movement
        # rather than the obligor label that causes it.
        assert row["rwa_final"] == pytest.approx(winner.u, rel=RTOL)
        assert case.total_rwa == pytest.approx(fx.crr_portfolio_total(variant), rel=RTOL)
        assert row["counterparty_reference"] == CP_SA

    @pytest.mark.parametrize("variant", ["binding", "nonbinding"])
    def test_facility_share_crr_produces_no_floor_columns(self, variant: str) -> None:
        """
        Under CRR ``sa_rwa`` is ABSENT from the results frame, not null.

        Arrange: the FS-1 portfolio under CRR.
        Act:     read the results frame's column list.
        Assert:  the three floor carriers are absent and there is no summary.

        This is the resolver's CRR contract, stated on the observable side: a
        resolver that reads ``sa_rwa`` unconditionally raises
        ``ColumnNotFoundError`` on every CRR run (mutation (e)). A presence guard
        written from the Basel 3.1 side alone is the LESSONS B1 shape.

        Green before and after — it pins the branch the CRR runs take.
        """
        # Arrange / Act
        case = run_case("CRR", variant)

        # Assert
        for column in ("sa_rwa", "rwa_pre_floor", "is_floor_binding", "floor_impact_rwa"):
            assert column not in case.columns, (
                f"{column} is present under CRR; the resolver's absent-column "
                "branch would then never be exercised by this portfolio"
            )
        assert case.result.output_floor_summary is None

    @pytest.mark.parametrize("variant", ["binding", "nonbinding"])
    def test_facility_share_own_approach_election_is_inert_under_crr(self, variant: str) -> None:
        """
        The ``own_approach`` election changes nothing under CRR.

        Arrange: the same CRR portfolio run twice, once under each election.
        Act:     compare the winner, every priced cell and the audit frame.
        Assert:  identical, INCLUDING ``metric_used``.

        The election pins P0, and CRR is P0 already, so a firm may set it once
        and run both regimes. ``metric_used`` on the resolution frame is the
        election's ONLY observable under CRR — there is no ``OutputFloorSummary``
        to carry ``facility_share_metric_used``.
        """
        # Arrange
        default = run_case("CRR", variant)
        elected = run_case("CRR", variant, metric="own_approach")

        # Act / Assert — the priced surface is unchanged.
        assert elected.rows.keys() == default.rows.keys()
        for reference, row in default.rows.items():
            other = elected.rows[reference]
            for column in ("counterparty_reference", "approach_applied", "exposure_class"):
                assert other[column] == row[column], f"{reference}.{column} moved"
            for column in ("ead_final", "risk_weight", "rwa_final"):
                assert other[column] == pytest.approx(row[column], rel=RTOL)
        assert elected.total_rwa == pytest.approx(default.total_rwa, rel=RTOL)

        # Assert — and so is the audit frame's metric, the sole CRR observable.
        adequacy_three_candidates(elected)
        for row in elected.resolution or []:
            assert row["metric_used"] == "own_approach", (
                "under CRR the floor Feature is off, so the resolver computes P0 "
                "whichever election is set and must SAY so on every candidate row"
            )

    @pytest.mark.parametrize("variant", ["binding", "nonbinding"])
    def test_facility_share_el_summary_excludes_losing_candidates(self, variant: str) -> None:
        """
        The losing candidates' expected loss never reaches the EL summary.

        Arrange: the FS-1 portfolio under CRR, whose winner is standardised.
        Act:     read ``el_summary.cet1_deduction``.
        Assert:  it equals the derived post-resolution figure.

        This is where the "drop BEFORE the EL summary" requirement is observable
        with no floor in the picture. ``compute_el_portfolio_summary`` reads the
        IRB and slotting BRANCH frames directly, so a resolver that filters only
        the combined frame leaves the losing F-IRB candidate's expected loss
        inside the deduction and every ``rwa_final`` still looks right.

        Red today by 108.00 — the F-IRB candidate's own expected loss at the
        Art. 166(8)(d) conversion factor (``0.0008 x 0.45 x 300,000``), which is
        in the number today because that candidate is today's winner.

        Mutation it detects (c'): losers dropped from ``combined`` but not from
        ``irb_results``.
        """
        # Arrange
        case = run_case("CRR", variant)
        adequacy_pool_b_does_not_move_ead(case)

        # Act
        summary = case.result.el_summary

        # Assert
        assert summary is not None, "the EL summary is produced in both regimes"
        assert float(summary.cet1_deduction) == pytest.approx(
            fx.crr_cet1_deduction(variant), rel=RTOL
        )


# ---------------------------------------------------------------------------
# Basel 3.1 — P2, the two-assignment rule
# ---------------------------------------------------------------------------


class TestFacilityShareUnderBasel31:
    """The floor makes 'riskiest' state-dependent, so two assignments are evaluated."""

    def test_facility_share_binding_default_picks_floored_branch_winner(self) -> None:
        """
        With the floor binding, the F-IRB member wins on the floored branch.

        Arrange: the FS-1 portfolio under Basel 3.1, ``binding`` variant, default
                 ``floor_aware`` election.
        Act:     run the full pipeline.
        Assert:  the winner is FS-CP-IRB, the audit frame holds three candidates,
                 the summary records ``sa_equivalent`` as the metric used and
                 TREA(A) as the alternative, and the undrawn row carries its
                 derived post-floor RWA.

        ``TREA(B) - TREA(A) = 19,200.00`` exactly, because both floored branches
        are pinned by ``x . S_irb + OF-ADJ`` whose terms are integers here.

        Red today ONLY on the audit frame, the candidate rows and the two summary
        fields — NOT on ``rwa_final``. On THIS portfolio the existing preview's
        winner coincides with assignment B's, because the one standardised
        candidate that could beat it carries a full RWA of 100,000.00, below
        ``x . s_IRB = 120,000.00``. That coincidence is a property of these
        inputs, not of the mechanism: a regulatory-retail member at 75% would
        give ``u_SA = 150,000`` and the two orderings would diverge.
        """
        # Arrange
        case = run_case("BASEL_3_1", "binding")
        adequacy_divergence_chain()
        adequacy_standardised_b_equals_u()
        adequacy_no_ties()
        adequacy_variants_pick_different_members()
        adequacy_floor_state_matches_variant(case)
        adequacy_retail_granularity_is_inert(case)
        adequacy_no_pd_floor_and_no_supporting_factor(case)
        adequacy_three_candidates(case)

        chosen = fx.chosen_b31("binding")
        alternative = fx.assignment_a("binding")
        assert chosen.winner == CP_IRB, "derivation says B wins; the test below assumes it"

        # Act
        row = case.share
        resolution = case.resolution or []

        # Assert — the winner, and that it is a MODELLED row.
        assert row["counterparty_reference"] == CP_IRB
        assert row["original_counterparty_reference"] == CP_SA
        assert row["approach_applied"] == "foundation_irb"
        assert row["rwa_final"] == pytest.approx(chosen.eligible_rwa[SHARE_UNDRAWN], rel=RTOL)

        # Assert — the audit frame names every candidate and exactly one winner.
        assert len(resolution) == 3
        assert sum(1 for entry in resolution if entry["is_winner"]) == 1
        winner_row = next(entry for entry in resolution if entry["is_winner"])
        assert winner_row["counterparty_reference"] == CP_IRB
        assert winner_row["collapsed_exposure_reference"] == SHARE_UNDRAWN
        for entry in resolution:
            assert entry["metric_used"] == "sa_equivalent", (
                "the floored branch won, so every candidate row must record the "
                "metric that decided the group - an attribution flip under P2 is "
                "a feature, but it may never be silent"
            )

        # Assert — the summary records both branches, so the flip is auditable.
        assert case.summary_field("facility_share_metric_used") == "sa_equivalent"
        assert case.summary_field("facility_share_trea_alternative") == pytest.approx(
            alternative.total_rwa_post_floor, rel=RTOL
        )
        assert case.total_rwa == pytest.approx(chosen.total_rwa_post_floor, rel=RTOL)

    def test_facility_share_nonbinding_picks_own_approach_winner(self) -> None:
        """
        With the floor NOT binding, the standardised OWNER wins on own RWA.

        Arrange: the FS-1 portfolio under Basel 3.1, ``nonbinding`` variant.
        Act:     run the full pipeline.
        Assert:  the winner is FS-CP-SA, standardised, at the derived RWA; the
                 summary records ``own_approach`` and TREA(B) as the alternative.

        The floor fails to bind on ``x . S_irb`` against ``U_irb`` alone, before
        OF-ADJ is applied, so the conclusion does not rest on the expected-loss
        arithmetic.

        Red today by 53,756.13 on the portfolio total: today's preview hands the
        row to the F-IRB member at 46,243.87 where the rule gives 100,000.00.

        Mutation it detects (a): ``argmax`` -> ``argmin`` on assignment A. Note
        what that produces — A' picks FS-CP-LOW, whose TREA falls BELOW the
        unmutated TREA(B), so the resolver keeps B and the winner becomes
        FS-CP-IRB at 46,243.87, NOT FS-CP-LOW at 40,000.00. A reader expecting
        40,000.00 would misread the mismatch as "the mutation did not apply",
        which is mechanism 2 of LESSONS C12.
        """
        # Arrange
        case = run_case("BASEL_3_1", "nonbinding")
        adequacy_divergence_chain()
        adequacy_variants_pick_different_members()
        adequacy_floor_state_matches_variant(case)
        adequacy_retail_granularity_is_inert(case)
        adequacy_pool_b_does_not_move_ead(case)
        adequacy_three_candidates(case)

        chosen = fx.chosen_b31("nonbinding")
        alternative = fx.assignment_b("nonbinding")
        assert chosen.winner == CP_SA, "derivation says A wins; the test below assumes it"
        winner = fx.candidates("b31")[CP_SA]

        # Act
        row = case.share

        # Assert
        assert row["counterparty_reference"] == CP_SA
        assert row["approach_applied"] == "standardised"
        assert row["ead_final"] == pytest.approx(winner.ead, rel=RTOL)
        assert row["risk_weight"] == pytest.approx(winner.risk_weight, rel=RTOL)
        assert row["rwa_final"] == pytest.approx(winner.u, rel=RTOL)
        assert row["is_floor_binding"] is False
        assert case.total_rwa == pytest.approx(chosen.total_rwa_post_floor, rel=RTOL)
        assert case.summary_field("facility_share_metric_used") == "own_approach"
        assert case.summary_field("facility_share_trea_alternative") == pytest.approx(
            alternative.total_rwa_post_floor, rel=RTOL
        )

    def test_facility_share_nonbinding_undrawn_rwa_is_the_own_approach_winner_amount(
        self,
    ) -> None:
        """
        The undrawn row's obligor and RWA alone, with no audit frame in the way.

        Arrange: the FS-1 portfolio under Basel 3.1, ``nonbinding`` variant.
        Act:     read the surviving FS-FAC-SHARE_UNDRAWN row and the portfolio total.
        Assert:  the obligor is FS-CP-SA, the RWA is its derived own-approach
                 figure, and the portfolio total follows.

        The Basel 3.1 twin of the CRR test above, and it exists for the same
        reason: its sibling
        ``test_facility_share_nonbinding_picks_own_approach_winner`` puts the
        adequacy assertions first, so the +53,756.13 movement on the portfolio
        total is asserted by nothing observable until the aggregator slice lands.

        No adequacy call and no ``case.resolution``. Red today on the number:
        46,243.87 against FS-CP-IRB where the rule gives 100,000.00 against
        FS-CP-SA, and a portfolio total of 2,942,809.997 against 2,996,566.125.

        The floor state is still pinned, because the whole claim is conditional
        on it: with the floor binding, assignment B would win and the expected
        obligor would be the other one.
        """
        # Arrange
        case = run_case("BASEL_3_1", "nonbinding")
        chosen = fx.chosen_b31("nonbinding")
        winner = fx.candidates("b31")[CP_SA]
        assert chosen.winner == CP_SA, "derivation says A wins; the assertions below assume it"

        # Act
        row = case.share

        # Assert
        assert row["is_floor_binding"] is False, (
            "the floor must NOT bind here; with it binding the floored branch "
            "would win and the expected obligor would be the modelled member"
        )
        # The AMOUNT first, so the failure text carries the movement rather than
        # the obligor label that causes it.
        assert row["rwa_final"] == pytest.approx(winner.u, rel=RTOL)
        assert case.total_rwa == pytest.approx(chosen.total_rwa_post_floor, rel=RTOL)
        assert row["counterparty_reference"] == CP_SA

    def test_facility_share_binding_election_output_floor_summary(self) -> None:
        """
        The ``own_approach`` election pins assignment A and every summary field.

        Arrange: the ``binding`` variant with ``facility_share_metric="own_approach"``.
        Act:     read ``OutputFloorSummary`` and the surviving undrawn row.
        Assert:  the winner is the standardised owner, and U-TREA, S-TREA,
                 OF-ADJ, the threshold, the shortfall and the total all match the
                 derived assignment-A figures.

        THIS ELECTION LOWERS RWA — 1,680,000.00 against the default's
        1,699,200.00 and against today's 1,699,200.00. It is opt-in and
        non-default, justified as a stability election for firms whose reporting
        cannot tolerate attribution moving with the floor state, and the
        direction is stated here rather than left to be discovered.

        ``irb_cet1_deduction`` is 0.00 under this assignment and 64.00 under the
        default: the winning candidate is standardised, so its expected loss
        never enters the IRB branch frame at all.

        Mutation it detects (c'): losers dropped from ``combined`` but not from
        ``irb_results`` leaves the dropped F-IRB candidate's 64.00 of expected
        loss in the summary, moving OF-ADJ 0.00 -> -800.00 and the threshold
        1,440,000.00 -> 1,439,200.00.
        """
        # Arrange
        case = run_case("BASEL_3_1", "binding", metric="own_approach")
        adequacy_floor_state_matches_variant(case)
        adequacy_three_candidates(case)
        expected = fx.assignment_a("binding")

        # Act
        summary = case.result.output_floor_summary
        assert summary is not None

        # Assert — the winner is assignment A's.
        assert case.share["counterparty_reference"] == CP_SA
        assert case.share["approach_applied"] == "standardised"
        assert case.share["rwa_final"] == pytest.approx(fx.candidates("b31")[CP_SA].u, rel=RTOL)

        # Assert — every floor input and output.
        assert summary.floor_pct == pytest.approx(fx.output_floor_pct(), rel=RTOL)
        assert summary.u_trea == pytest.approx(expected.u_trea, rel=RTOL)
        assert summary.s_trea == pytest.approx(expected.s_trea, rel=RTOL)
        assert summary.of_adj == pytest.approx(expected.of_adj, abs=1e-9)
        assert summary.irb_t2_credit == pytest.approx(0.0, abs=1e-9)
        assert summary.irb_cet1_deduction == pytest.approx(0.0, abs=1e-9)
        assert summary.gcra_amount == pytest.approx(0.0, abs=1e-9)
        assert summary.sa_t2_credit == pytest.approx(0.0, abs=1e-9)
        assert summary.floor_threshold == pytest.approx(expected.floor_threshold, rel=RTOL)
        assert summary.shortfall == pytest.approx(expected.shortfall, rel=RTOL)
        assert summary.sa_rwa_total == pytest.approx(expected.sa_rwa_total, rel=RTOL)
        assert summary.total_rwa_post_floor == pytest.approx(
            expected.total_rwa_post_floor, rel=RTOL
        )
        assert case.summary_field("facility_share_metric_used") == "own_approach"

    def test_facility_share_binding_election_s_trea_excludes_losing_candidates(self) -> None:
        """
        S-TREA counts the WINNER's SA-equivalent only, never the losers'.

        Arrange: the ``binding`` variant under the ``own_approach`` election,
                 whose winner is standardised and whose losers include the
                 modelled candidate.
        Act:     read ``s_trea`` and ``floor_threshold``.
        Assert:  S-TREA is the non-share book's, with no share contribution.

        Named on THIS run deliberately. Under the default election the winner is
        the F-IRB candidate and both losers are standardised — standardised is
        not in ``FLOOR_ELIGIBLE_APPROACHES``, so ``s_trea`` would not move at all
        there and only ``sa_rwa_total`` would.

        Mutation it detects (c): losers dropped AFTER the floor instead of
        before. Retaining the modelled loser moves S-TREA 2,400,000 -> 2,600,000
        and the threshold by 119,200.00 — not 120,000.00, because the retained
        candidate also drags OF-ADJ to -800.00.
        """
        # Arrange
        case = run_case("BASEL_3_1", "binding", metric="own_approach")
        adequacy_floor_state_matches_variant(case)
        _u0, s0, _sa0 = fx.non_share_totals("b31", "binding")
        loser_sa_equivalent = fx.candidates("b31")[CP_IRB].s
        assert loser_sa_equivalent is not None
        assert loser_sa_equivalent > 0.0, (
            "the losing modelled candidate contributes no SA-equivalent, so "
            "retaining it would not move S-TREA and this test could not "
            "distinguish a correct drop from no drop at all"
        )

        # Act
        summary = case.result.output_floor_summary
        assert summary is not None

        # Assert
        assert summary.s_trea == pytest.approx(s0, rel=RTOL)
        assert summary.floor_threshold == pytest.approx(
            fx.output_floor_pct() * s0 + summary.of_adj, rel=RTOL
        )

    def test_facility_share_binding_floor_allocation_sums_to_threshold(self) -> None:
        """
        The floor add-on foots: eligible RWA sums to the threshold, add-ons to the shortfall.

        Arrange: the ``binding`` variant under the default election, whose winner
                 is the F-IRB candidate, so three rows are floor-eligible.
        Act:     sum ``rwa_final`` and ``floor_impact_rwa`` over those rows.
        Assert:  the first equals ``floored_modelled_rwa`` and ``floor_threshold``;
                 the second equals ``shortfall``; and each row's own add-on
                 matches its derived pro-rata share of the SA-equivalent basis.

        The shares are ``1/13``, ``2/13`` and ``10/13``. The add-on is NOT a
        uniform ``x . sa_rwa``: the anchor's own-to-SA-equivalent ratio differs
        from the candidate's by a factor above 2, so an implementation on the
        wrong basis lands on a different number on every eligible row.

        GREEN TODAY, and deliberately so. On this portfolio the existing preview
        already hands the row to the F-IRB member, so the three eligible rows and
        their allocation are the same before and after (proposal Section 4.6).
        It is a regression guard on the NEW code rather than a driver of it, and
        it discriminates: mutation (c) (drop after the floor rather than before)
        moves the threshold by 119,200.00, and an allocation on a uniform basis
        moves every per-row figure.
        """
        # Arrange
        case = run_case("BASEL_3_1", "binding")
        adequacy_floor_state_matches_variant(case)
        adequacy_floor_basis_is_non_uniform()
        expected = fx.chosen_b31("binding")
        assert expected.winner == CP_IRB

        summary = case.result.output_floor_summary
        assert summary is not None

        # Act
        eligible = [case.rows[reference] for reference in ELIGIBLE_WITH_SHARE]

        # Assert — the two footing identities, not merely their parts.
        assert sum(row["rwa_final"] for row in eligible) == pytest.approx(
            summary.floored_modelled_rwa, rel=RTOL
        )
        assert sum(row["rwa_final"] for row in eligible) == pytest.approx(
            summary.floor_threshold, rel=RTOL
        )
        assert sum(row["floor_impact_rwa"] for row in eligible) == pytest.approx(
            summary.shortfall, rel=RTOL
        )

        # Assert — and the per-row allocation, which is what the basis decides.
        for reference in ELIGIBLE_WITH_SHARE:
            assert case.rows[reference]["rwa_final"] == pytest.approx(
                expected.eligible_rwa[reference], rel=RTOL
            ), f"{reference} carries the wrong pro-rata share of the shortfall"
