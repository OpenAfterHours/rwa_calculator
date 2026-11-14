"""
``referee.differential.compare`` — the two engines' verdicts, rule by rule.

No Arelle and no taxonomy here: both sides are built by hand, because what is
pinned is the comparison itself — which pairs of standings agree, which
disagree, which prove nothing — and that a differential which compared nothing
is never reported as clean.

References:
- packages/rwa-filer/src/rwa_filer/referee/differential.py
"""

from __future__ import annotations

import pytest

from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS, RuleResult
from rwa_filer.referee.differential import (
    AGREE,
    COUNT_DIFFERS,
    DISAGREE,
    NOT_COMPARED,
    REFEREE_ABSENT,
    REFEREE_LOST,
    REFEREE_SKIPPED,
    compare,
)
from rwa_filer.referee.runner import (
    CHUNK_OK,
    MODE_FULL,
    ChunkStat,
    RefereeResult,
    RuleVerdict,
)


def _native(rule_id: str, satisfied: int = 0, unsatisfied: int = 0) -> RuleResult:
    """A native result whose status follows from its counts, as the engine's does."""
    if unsatisfied:
        status = STATUS_FAIL
    elif satisfied:
        status = STATUS_PASS
    else:
        status = STATUS_NOT_EVALUATED
    return RuleResult(
        rule_id=rule_id,
        severity="ERROR",
        status=status,
        reason="" if satisfied or unsatisfied else "no_data",
        satisfied=satisfied,
        unsatisfied=unsatisfied,
    )


def _referee(
    verdicts: dict[str, tuple[int, int]] | None = None,
    *,
    skipped: tuple[str, ...] = (),
    lost: tuple[str, ...] = (),
    chunk_status: str = CHUNK_OK,
) -> RefereeResult:
    rules = {
        rule_id: RuleVerdict(rule_id=rule_id, satisfied=held, unsatisfied=broken)
        for rule_id, (held, broken) in (verdicts or {}).items()
    }
    chunk = ChunkStat(
        index=0,
        assertions=len(rules),
        assertion_xml_mb=1.0,
        status=chunk_status,
        wall_s=1.0,
        peak_rss_mb=100,
        returncode=0,
    )
    return RefereeResult(
        rules=rules,
        messages=(),
        skipped=skipped,
        lost=lost,
        chunks=(chunk,),
        schema_ref="http://example.test/mod/x.xsd",
        filing_indicators=("T01",),
        mode=MODE_FULL,
    )


class TestVerdictsThatAgree:
    """One verdict from both engines, whatever each calls it."""

    @pytest.mark.parametrize(
        ("native_counts", "referee_counts"),
        [((3, 0), (3, 0)), ((1, 2), (1, 2)), ((0, 0), (0, 0))],
        ids=["both-held", "both-broken", "neither-evaluated"],
    )
    def test_the_same_verdict_and_counts_agree(
        self, native_counts: tuple[int, int], referee_counts: tuple[int, int]
    ) -> None:
        # Act
        diff = compare([_native("r1", *native_counts)], _referee({"r1": referee_counts}))

        # Assert
        assert [item.outcome for item in diff.comparisons] == [AGREE]
        assert diff.is_clean

    def test_a_rule_the_referee_skipped_agrees_with_one_the_native_engine_did_not_evaluate(
        self,
    ) -> None:
        """A false filing-indicator precondition and "template not reported" are one fact."""
        # Act
        diff = compare([_native("r1")], _referee({"r2": (1, 0)}, skipped=("r1",)))

        # Assert
        by_rule = {item.rule_id: item for item in diff.comparisons}
        assert by_rule["r1"].outcome == AGREE
        assert by_rule["r1"].referee == REFEREE_SKIPPED

    def test_one_verdict_over_two_counts_is_reported_but_is_not_a_disagreement(self) -> None:
        # Act
        diff = compare([_native("r1", 0, 38)], _referee({"r1": (0, 42)}))

        # Assert
        (item,) = diff.comparisons
        assert item.outcome == COUNT_DIFFERS
        assert (item.native_counts, item.referee_counts) == ((0, 38), (0, 42))
        assert diff.disagreements == ()
        assert diff.is_clean


class TestVerdictsThatDisagree:
    """Every pair of different verdicts is a finding."""

    @pytest.mark.parametrize(
        ("native_counts", "referee_counts"),
        [
            ((2, 0), (1, 1)),
            ((1, 1), (2, 0)),
            ((0, 2), (0, 0)),
            ((0, 0), (0, 2)),
            ((2, 0), (0, 0)),
            ((0, 0), (2, 0)),
        ],
        ids=[
            "held-vs-broken",
            "broken-vs-held",
            "broken-vs-never-fired",
            "not-evaluated-vs-broken",
            "held-vs-never-fired",
            "not-evaluated-vs-held",
        ],
    )
    def test_different_verdicts_disagree(
        self, native_counts: tuple[int, int], referee_counts: tuple[int, int]
    ) -> None:
        # Act
        diff = compare([_native("r1", *native_counts)], _referee({"r1": referee_counts}))

        # Assert
        assert [item.outcome for item in diff.disagreements] == [DISAGREE]
        assert not diff.is_clean

    def test_a_native_verdict_on_a_rule_the_referee_skipped_disagrees(self) -> None:
        # Act
        diff = compare(
            [_native("r1", 0, 1), _native("r2", 1, 0)], _referee({"r2": (1, 0)}, skipped=("r1",))
        )

        # Assert
        assert [item.rule_id for item in diff.disagreements] == ["r1"]

    def test_a_rule_only_the_referee_evaluated_disagrees(self) -> None:
        """The taxonomy runs a rule the native rule book does not enforce."""
        # Act
        diff = compare([_native("r1", 1, 0)], _referee({"r1": (1, 0), "r9": (0, 1)}))

        # Assert
        (item,) = diff.disagreements
        assert (item.rule_id, item.native) == ("r9", "ABSENT")

    def test_a_rule_only_the_referee_knows_and_never_fired_proves_nothing(self) -> None:
        # Act
        diff = compare([_native("r1", 1, 0)], _referee({"r1": (1, 0), "r9": (0, 0)}))

        # Assert
        assert diff.disagreements == ()
        assert [item.rule_id for item in diff.not_compared] == ["r9"]


class TestWhatCouldNotBeCompared:
    """No verdict from the referee is not agreement."""

    def test_a_rule_the_referee_lost_is_not_compared_and_the_result_is_not_clean(self) -> None:
        # Act
        diff = compare(
            [_native("r1", 1, 0), _native("r2", 1, 0)], _referee({"r1": (1, 0)}, lost=("r2",))
        )

        # Assert
        (item,) = diff.not_compared
        assert (item.rule_id, item.referee, item.outcome) == ("r2", REFEREE_LOST, NOT_COMPARED)
        assert not diff.is_clean

    def test_a_rule_the_referee_was_not_asked_about_leaves_the_rest_clean(self) -> None:
        """``run_referee(rules=...)`` runs a subset; the others are simply absent."""
        # Act
        diff = compare([_native("r1", 1, 0), _native("r2", 0, 1)], _referee({"r1": (1, 0)}))

        # Assert
        (item,) = diff.not_compared
        assert (item.rule_id, item.referee) == ("r2", REFEREE_ABSENT)
        assert diff.is_clean

    def test_nothing_compared_is_never_clean(self) -> None:
        # Act
        diff = compare([_native("r1", 1, 0)], _referee({}))

        # Assert
        assert diff.compared == 0
        assert not diff.is_clean

    def test_an_unfinished_referee_run_is_never_clean(self) -> None:
        # Act
        diff = compare([_native("r1", 1, 0)], _referee({"r1": (1, 0)}, chunk_status="killed"))

        # Assert
        assert diff.disagreements == ()
        assert not diff.is_clean


class TestTheRecord:
    def test_the_record_carries_the_totals_and_every_rule_that_did_not_simply_agree(self) -> None:
        # Arrange
        native = [_native("a", 1, 0), _native("b", 0, 2), _native("c", 0, 3), _native("d", 1, 0)]
        referee = _referee({"a": (1, 0), "b": (2, 0), "c": (0, 5)})

        # Act
        record = compare(native, referee).to_record()

        # Assert
        assert record["outcomes"] == {
            AGREE: 1,
            COUNT_DIFFERS: 1,
            DISAGREE: 1,
            NOT_COMPARED: 1,
        }
        assert record["compared"] == 3
        assert [item["rule"] for item in record["disagreements"]] == ["b"]
        assert record["disagreements"][0]["referee_counts"] == [2, 0]
        assert [item["rule"] for item in record["count_differences"]] == ["c"]
        assert [item["rule"] for item in record["not_compared"]] == ["d"]
        assert record["is_clean"] is False
