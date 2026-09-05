"""
FS-1 presence expectations — absence is this estate's dominant escape class.

Pipeline position:
    Loader -> HierarchyResolver (candidate fan-out) -> Classifier -> CRMProcessor
        -> SA / IRB calculators -> OutputAggregator (candidate resolution)
        -> AggregatedResultBundle

Separate from ``test_fs1_facility_share_fanout.py`` by concern: that module
asserts the VALUES the allocation produces, this one asserts that the things
carrying those values exist at all — the audit frame is emitted, both new columns
reach the sealed aggregator exit with the right dtypes, every priced cell on an
undrawn row is non-null rather than merely present, the fan-out grammar does not
leak past the aggregator, and the error channel carries nothing beyond the one
known warning.

The split matters because the two failure modes need different assertions. A
wrong number is loud; a cell that publishes ``null``, a sheet never emitted, a
row never populated are all silent, and this project's measured escape record is
dominated by the second kind (LESSONS B1, B4, B5).

References:
- .claude/state/fs1-scenario-proposal.md Section 7 — the presence expectations.
- docs/plans/facility-share-riskiest-member.md Section 4 — the nine edges.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.errors import ERROR_DUE_DILIGENCE_NOT_PERFORMED
from tests.acceptance import _fs1_expectations as fx
from tests.acceptance._fs1_harness import (
    ALL_RUNS,
    RTOL,
    SHARE_UNDRAWN,
    SOLO_UNDRAWN,
    adequacy_three_candidates,
    run_case,
)
from tests.fixtures.facility_share_portfolio import CP_IRB, CP_LOW, CP_SA, FAC_SHARE, FAC_SOLO

# ---------------------------------------------------------------------------
# Fan-out shape, presence and the error channel
# ---------------------------------------------------------------------------


class TestFacilityShareFanOutShape:
    """Absence is this estate's dominant escape class, so assert what should be there."""

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_owner_is_always_a_member(self, framework: str, variant: str) -> None:
        """
        Decision D3: the facility OWNER is a candidate even with no loan of its own.

        Arrange: FS-FAC-SHARE, whose two mapped loans belong to the two
                 descendants and whose owner has no loan under it at all.
        Act:     read the resolution audit frame.
        Assert:  all three members appear, including the owner.

        Today's detection rule takes distinct counterparties on DESCENDANTS only,
        so the owner is not a member and the candidate set is the two
        descendants. That is not a row-count nicety: the owner is assignment A's
        winner in three of the four cells of the outcome matrix, so omitting it
        changes the winner, the approach and the RWA.

        Mutation it detects (b): revert D3. The candidate set falls to
        {FS-CP-IRB, FS-CP-LOW} — which is exactly today's behaviour — and the
        winner becomes FS-CP-IRB under CRR and under Basel 3.1 ``nonbinding``.
        """
        # Arrange
        case = run_case(framework, variant)

        # Act
        adequacy_three_candidates(case)
        resolution = case.resolution or []

        # Assert
        members = {entry["counterparty_reference"] for entry in resolution}
        assert members == {CP_SA, CP_LOW, CP_IRB}, (
            f"candidate members are {sorted(members)}; the OWNER {CP_SA} is a "
            "legal borrower who can draw the whole headroom and must be ranked"
        )
        for entry in resolution:
            assert entry["original_counterparty_reference"] == CP_SA
            assert (
                entry["exposure_reference"] == f"{SHARE_UNDRAWN}@{entry['counterparty_reference']}"
            )

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_solo_facility_is_not_fanned_out(
        self, framework: str, variant: str
    ) -> None:
        """
        A single-member facility keeps one ordinary undrawn row.

        Arrange: FS-FAC-SOLO, whose only descendant loan belongs to the owner, so
                 its member set is the singleton {FS-CP-SA}.
        Act:     read its undrawn row.
        Assert:  it is present, priced, carries a null ``facility_share_group``
                 and a False candidate flag, and appears in no resolution row.

        This is the control leg of the two-leg pair: it must survive every cell
        of the outcome matrix unchanged, so a change that ZEROED the 50%
        risk-weight band is distinguishable from one that moved a row out of it.
        """
        # Arrange
        case = run_case(framework, variant)

        # Act
        row = case.rows[SOLO_UNDRAWN]

        # Assert — present and priced.
        assert row["exposure_type"] == "facility_undrawn"
        assert row["counterparty_reference"] == CP_SA
        for column in ("ead_final", "ccf", "risk_weight", "rwa_final"):
            assert row[column] is not None, f"{SOLO_UNDRAWN}.{column} is null, not zero"
        regime = "crr" if framework == "CRR" else "b31"
        assert row["rwa_final"] == pytest.approx(
            fx.drawn_rwa(regime, variant)[SOLO_UNDRAWN], rel=RTOL
        )

        # Assert — and NOT a share. Column PRESENCE first: on pre-change code
        # neither column exists at all, and a KeyError reports a broken test
        # rather than a missing feature.
        for column in ("facility_share_group", "is_facility_share_candidate"):
            assert column in case.columns, f"{column} is not on the aggregator exit"
        assert row["facility_share_group"] is None
        assert row["is_facility_share_candidate"] is False

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_exit_carries_one_undrawn_row_per_facility(
        self, framework: str, variant: str
    ) -> None:
        """
        No ``@`` suffix leaks past the aggregator, and every priced cell is non-null.

        Arrange: any FS-1 run.
        Act:     read the two synthetic undrawn rows off the results frame.
        Assert:  exactly one row per facility, keyed on the collapsed reference,
                 with ``source_exposure_reference`` unchanged and every priced
                 cell non-null.

        The aggregator-exit invariant is what keeps COREP, Pillar 3,
        reconciliation and the supervisory register seeing the shape they see
        today. A null and a legitimate zero are different claims, so presence is
        asserted on each cell rather than inferred from the row existing.
        """
        # Arrange
        case = run_case(framework, variant)

        # Act
        undrawn = {
            reference: row
            for reference, row in case.rows.items()
            if row["exposure_type"] == "facility_undrawn"
        }

        # Assert
        assert set(undrawn) == {SHARE_UNDRAWN, SOLO_UNDRAWN}, sorted(undrawn)
        assert case.share["source_exposure_reference"] == FAC_SHARE
        assert case.rows[SOLO_UNDRAWN]["source_exposure_reference"] == FAC_SOLO
        for reference, row in undrawn.items():
            for column in ("ead_final", "ccf", "risk_weight", "rwa_final"):
                assert row[column] is not None, f"{reference}.{column} published a null"
            assert row["ead_final"] > 0.0

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_columns_are_sealed_on_the_aggregator_exit(
        self, framework: str, variant: str
    ) -> None:
        """
        Both new columns reach the sealed aggregator exit with the right dtypes.

        Arrange: any FS-1 run.
        Act:     read the collected results schema.
        Assert:  ``facility_share_group`` is String and
                 ``is_facility_share_candidate`` is Boolean, and the share's
                 surviving row names its group.

        ``EdgeContract.conform`` drops an undeclared column with no error and no
        warning, so one missed edge in the chain turns the whole feature into a
        green no-op (LESSONS B1). This is the observable end of the contract test
        in tests/contracts/test_facility_share_contracts.py.
        """
        # Arrange
        case = run_case(framework, variant)
        schema = case.result.results.collect_schema()

        # Act / Assert
        assert "facility_share_group" in case.columns
        assert "is_facility_share_candidate" in case.columns
        assert schema["facility_share_group"] == pl.String
        assert schema["is_facility_share_candidate"] == pl.Boolean
        assert case.share["facility_share_group"] == FAC_SHARE

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_metric_used_is_populated_in_both_regimes(
        self, framework: str, variant: str
    ) -> None:
        """
        ``metric_used`` is non-null on all three candidate rows, in both regimes.

        Arrange: any FS-1 run.
        Act:     read the audit frame.
        Assert:  every candidate row names the metric that decided the group, and
                 the value is one of the three the contract allows.

        Asserted against the contract's own vocabulary rather than a hand-written
        list of the two this portfolio reaches — a test written from the same
        sentence as the code validates nothing (LESSONS B3).
        """
        # Arrange
        case = run_case(framework, variant)
        adequacy_three_candidates(case)

        # Act
        resolution = case.resolution or []

        # Assert
        for entry in resolution:
            assert entry["metric_used"] in {
                "own_approach",
                "sa_equivalent",
                "fallback_deterministic",
            }, f"unknown metric_used {entry['metric_used']!r}"
        assert sum(1 for entry in resolution if entry["is_winner"]) == 1

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_summary_metric_is_basel_31_only(
        self, framework: str, variant: str
    ) -> None:
        """
        ``OutputFloorSummary.facility_share_metric_used`` exists under Basel 3.1 only.

        Arrange: any FS-1 run.
        Act:     read ``output_floor_summary``.
        Assert:  under CRR the summary is ``None`` outright, so the field is
                 unreachable; under Basel 3.1 it is populated.

        Stated as a scope pin because the field is easy to reach for as the
        election's observable, and under CRR there is nothing to reach.
        """
        # Arrange
        case = run_case(framework, variant)

        # Act / Assert
        if framework == "CRR":
            assert case.result.output_floor_summary is None
            return
        assert case.summary_field("facility_share_metric_used") is not None

    @pytest.mark.parametrize(("framework", "variant"), ALL_RUNS)
    def test_facility_share_reports_no_error_beyond_the_known_due_diligence_warning(
        self, framework: str, variant: str
    ) -> None:
        """
        The run is clean apart from the known Art. 110A due-diligence warning.

        Arrange: any FS-1 run.
        Act:     read ``result.errors``.
        Assert:  nothing outside SA004.

        SA004 is filtered BY CODE, with its reason recorded, rather than widened
        to "no errors of any kind". It fires on every Basel 3.1 run regardless of
        input: ``due_diligence_performed`` survives the loader seal but is not
        declared in ``contracts/edges.py::_hierarchy_resolved_columns``, so
        ``EdgeContract.conform`` strips it before classification, and the guard in
        ``engine/sa/rw_adjustments.py`` tests column PRESENCE rather than value.
        That is an out-of-scope finding of its own (design doc Section 10 item 4,
        LESSONS B1 shape) and the Art. 110A override is unreachable from input
        until it is fixed. Filtering by code keeps a REGRESSION that re-introduced
        SA004 elsewhere attributable, and keeps an unrelated new warning red.
        """
        # Arrange
        case = run_case(framework, variant)

        # Act
        unexpected = [
            error for error in case.result.errors if error.code != ERROR_DUE_DILIGENCE_NOT_PERFORMED
        ]

        # Assert
        assert not unexpected, [(error.code, error.message) for error in unexpected]
