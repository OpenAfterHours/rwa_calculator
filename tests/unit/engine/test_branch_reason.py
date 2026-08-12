"""
The ``decide`` primitive: does it separate "does not apply" from "do not know"?

``docs/plans/test-space-correctness-proposal.md`` Phase 3 rests on one Polars
fact — ``pl.when(p).then(a).otherwise(b)`` yields ``b`` both when ``p`` is
False and when ``p`` is null — and one obligation on every caller: the value
chain must not move. These tests pin both, because the primitive is worthless
if either fails and the failure of either is silent.

References:
- src/rwa_calc/engine/branch_reason.py
- src/rwa_calc/domain/branch_reasons.py
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.branch_reasons import (
    BRANCH_REASON_VOCABULARIES,
    UNKNOWN_FALLBACK,
    IrbLgdReason,
    SovereignFloorReason,
    reason_dtype,
)
from rwa_calc.engine.branch_reason import BranchCase, decide


@pytest.fixture
def tri_state() -> pl.DataFrame:
    """One row per Kleene outcome of a Boolean predicate: True, False, null."""
    return pl.DataFrame(
        {"flag": [True, False, None], "base": [10.0, 20.0, 30.0]},
        schema={"flag": pl.Boolean, "base": pl.Float64},
    )


class TestNullDetection:
    """The whole point: a null predicate is reported, not absorbed."""

    def test_null_predicate_yields_unknown_fallback_while_value_takes_otherwise(
        self, tri_state: pl.DataFrame
    ) -> None:
        """A null predicate silently takes ``otherwise`` — and now says so.

        Arrange: a predicate that is True, False and null across three rows.
        Act:     decide() with one case.
        Assert:  the values match a plain when/then/otherwise exactly, and the
                 reasons distinguish the False row from the null row.
        """
        # Arrange
        case = BranchCase(SovereignFloorReason.FLOOR_BOUND, pl.col("flag"), pl.lit(1.0))

        # Act
        value, reason = decide(
            (case,),
            otherwise=pl.col("base"),
            otherwise_reason=SovereignFloorReason.FLOOR_NOT_BINDING,
            vocabulary=SovereignFloorReason,
        )
        out = tri_state.with_columns(value.alias("v"), reason.alias("r"))

        # Assert — the value is byte-identical to the uninstrumented chain
        incumbent = tri_state.select(
            pl.when(pl.col("flag")).then(pl.lit(1.0)).otherwise(pl.col("base")).alias("v")
        )
        assert out["v"].to_list() == incumbent["v"].to_list()
        # Assert — and the reason splits what the value cannot
        assert out["r"].cast(pl.String).to_list() == [
            SovereignFloorReason.FLOOR_BOUND.value,
            SovereignFloorReason.FLOOR_NOT_BINDING.value,
            UNKNOWN_FALLBACK,
        ]

    def test_an_earlier_null_wins_over_a_later_match(self) -> None:
        """Once an earlier predicate is indeterminate, the branch is unknown.

        A later case matching does not rescue the row: had the earlier
        predicate been True, THAT limb would have priced it. Reporting the
        later limb's name would assert something the data does not support.

        Arrange: row where case 1 is null and case 2 is True.
        Act:     decide().
        Assert:  reason is UNKNOWN_FALLBACK though the value came from case 2.
        """
        # Arrange
        frame = pl.DataFrame(
            {"first": [None], "second": [True]}, schema={"first": pl.Boolean, "second": pl.Boolean}
        )
        cases = (
            BranchCase(SovereignFloorReason.RATED, pl.col("first"), pl.lit(1.0)),
            BranchCase(SovereignFloorReason.TRADE_EXEMPT, pl.col("second"), pl.lit(2.0)),
        )

        # Act
        value, reason = decide(
            cases,
            otherwise=pl.lit(9.0),
            otherwise_reason=SovereignFloorReason.FLOOR_NOT_BINDING,
            vocabulary=SovereignFloorReason,
        )
        out = frame.with_columns(value.alias("v"), reason.alias("r"))

        # Assert
        assert out["v"].to_list() == [2.0], "value must follow the incumbent chain"
        assert out["r"].cast(pl.String).to_list() == [UNKNOWN_FALLBACK]

    def test_a_false_predicate_is_not_reported_as_unknown(self, tri_state: pl.DataFrame) -> None:
        """ "The rule does not apply" keeps its own name — that is the separation.

        Arrange: the tri-state frame.
        Act:     decide() with a case that is False on row 2.
        Assert:  row 2 carries the named limb, not UNKNOWN_FALLBACK.
        """
        # Arrange / Act
        _, reason = decide(
            (BranchCase(SovereignFloorReason.FLOOR_BOUND, pl.col("flag"), pl.lit(1.0)),),
            otherwise=pl.col("base"),
            otherwise_reason=SovereignFloorReason.DOMESTIC_CURRENCY,
            vocabulary=SovereignFloorReason,
        )
        reasons = tri_state.with_columns(reason.alias("r"))["r"].cast(pl.String).to_list()

        # Assert
        assert reasons[1] == SovereignFloorReason.DOMESTIC_CURRENCY.value
        assert reasons[1] != UNKNOWN_FALLBACK


class TestVocabularyContract:
    """A vocabulary that cannot say "I do not know" is not a vocabulary."""

    def test_vocabulary_without_unknown_fallback_is_rejected(self) -> None:
        """Refusing it here is what stops a silent limb being added later.

        Arrange: a StrEnum with no UNKNOWN_FALLBACK member.
        Act/Assert: decide() raises ValueError.
        """
        # Arrange
        from enum import StrEnum

        class Incomplete(StrEnum):
            ONLY = "only"

        cases = (BranchCase(Incomplete.ONLY, pl.lit(True), pl.lit(1.0)),)
        otherwise = pl.lit(0.0)

        # Act / Assert — decide() is the only call inside the raises block, so a
        # ValueError from building the arguments cannot be mistaken for the one
        # under test.
        with pytest.raises(ValueError, match="declares no UNKNOWN_FALLBACK"):
            decide(
                cases,
                otherwise=otherwise,
                otherwise_reason=Incomplete.ONLY,
                vocabulary=Incomplete,
            )

    def test_reason_outside_the_vocabulary_is_rejected(self) -> None:
        """A reason the dtype cannot hold would become a silent null.

        Arrange: a case naming a member of a DIFFERENT vocabulary.
        Act/Assert: decide() raises ValueError rather than emitting null.
        """
        # Arrange
        cases = (BranchCase(IrbLgdReason.OWN_ESTIMATE, pl.lit(True), pl.lit(1.0)),)
        otherwise = pl.lit(0.0)

        # Act / Assert
        with pytest.raises(ValueError, match="not members of SovereignFloorReason"):
            decide(
                cases,
                otherwise=otherwise,
                otherwise_reason=SovereignFloorReason.RATED,
                vocabulary=SovereignFloorReason,
            )

    def test_empty_cases_are_rejected(self) -> None:
        """An empty chain would emit one constant reason and prove nothing.

        Arrange: no cases.
        Act/Assert: decide() raises ValueError.
        """
        # Arrange
        otherwise = pl.lit(0.0)

        # Act / Assert
        with pytest.raises(ValueError, match="at least one case"):
            decide(
                (),
                otherwise=otherwise,
                otherwise_reason=SovereignFloorReason.RATED,
                vocabulary=SovereignFloorReason,
            )

    @pytest.mark.parametrize("vocabulary", list(BRANCH_REASON_VOCABULARIES.values()))
    def test_every_registered_vocabulary_declares_unknown_fallback(self, vocabulary: type) -> None:
        """Asserted over the registry, so a fifth path inherits the rule.

        Arrange: each registered vocabulary.
        Act:     read its member values.
        Assert:  UNKNOWN_FALLBACK is among them.
        """
        assert UNKNOWN_FALLBACK in {member.value for member in vocabulary}


class TestReasonDtype:
    """The dtype is the declared population — the census reads it, not a list."""

    def test_dtype_categories_are_the_vocabulary_in_declaration_order(self) -> None:
        """A limb nobody reaches is only visible because the dtype declares it.

        Arrange: the sovereign-floor vocabulary.
        Act:     build its dtype.
        Assert:  categories equal the members, in order.
        """
        # Arrange / Act
        dtype = reason_dtype(SovereignFloorReason)

        # Assert
        assert dtype.categories.to_list() == [m.value for m in SovereignFloorReason]

    def test_a_never_reached_limb_is_still_readable_from_the_dtype(self) -> None:
        """The property a String column cannot provide, pinned directly.

        Arrange: a frame where only one limb occurs.
        Act:     read the declared set off the dtype and the reached set off data.
        Assert:  the difference names the limbs no row took.
        """
        # Arrange
        _, reason = decide(
            (BranchCase(SovereignFloorReason.RATED, pl.lit(True), pl.lit(1.0)),),
            otherwise=pl.lit(0.0),
            otherwise_reason=SovereignFloorReason.FLOOR_NOT_BINDING,
            vocabulary=SovereignFloorReason,
        )
        series = pl.DataFrame({"x": [1]}).with_columns(reason.alias("r"))["r"]

        # Act
        declared = set(series.dtype.categories.to_list())
        reached = {v for v in series.unique().to_list() if v is not None}

        # Assert
        assert reached == {SovereignFloorReason.RATED.value}
        assert UNKNOWN_FALLBACK in declared - reached, (
            "the dtype must still declare limbs no row reached — that difference "
            "is what the branch census gates on"
        )
