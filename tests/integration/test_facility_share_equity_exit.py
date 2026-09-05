"""
Integration pin — the facility-share carriers survive the EQUITY path to the seal.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA / IRB / slotting calculators  ->  OutputAggregator (sealed exit)
                    equity calculator  ->  prepare_equity_results  ->  ^

What this file exists to catch
------------------------------
Equity is the ONE producer that reaches the sealed aggregator exit without
passing an SA / IRB / slotting branch seal. ``prepare_equity_results`` output is
concatenated straight onto the combined frame with ``how="diagonal_relaxed"``,
which materialises any column the equity frame lacks as a typed NULL rather than
as the branch seals' False.

``AGGREGATOR_EXIT_EDGE`` declares ``is_facility_share_candidate`` with
``default=False`` but carries no ``fill_null_default``, deliberately: that edge
seals an already-materialised frame and a fill would add a ``with_columns`` node
that ``tests/unit/test_aggregator_eager_views.py`` counts. So the exit's
guarantee rests entirely on every producer resolving the column itself, and
equity is the producer nobody would think of.

A null there is silent in both directions — ``col == True`` drops the row without
complaint and ``~col`` raises on an all-null column — which is the LESSONS B1
shape: a presence guard that is never wrong, on a value that is never right. It
goes live the moment the S3 resolver writes a predicate over the flag.

Mutation these tests detect
---------------------------
Revert the two ``pl.lit(...)`` expressions the S2 slice added to
``src/rwa_calc/engine/aggregator/_equity_prep.py`` — the
``facility_share_group`` / ``is_facility_share_candidate`` pair. Measured on this
portfolio: 1 null in ``is_facility_share_candidate`` at the sealed exit with them
removed, 0 with them present, in BOTH regimes. Every branch-sealed row keeps its
False either way, so the whole SA / IRB / slotting estate stays green and only
this file goes red. The expression-level twin is
``tests/unit/engine/aggregator/test_equity_prep.py::
TestPrepareEquityResultsFacilityShareCarriers``.

Why the portfolio is FS-1 plus one equity holding rather than equity alone: the
claim is about a frame in which BOTH producers are live. A pure-equity portfolio
would show zero nulls under a mutation that dropped the flag everywhere, because
there would be no branch-sealed row to compare against, and a pure-FS-1
portfolio cannot reach the equity path at all.

References:
- docs/plans/facility-share-riskiest-member.md Section 4 (O2), Section 9.
- .claude/state/fs1-scenario-proposal.md Section 6.1 — the edge-contract chain.
- CRR Art. 133 / PS1/26 Art. 133(3) — the listed-equity risk weight the holding
  is priced at. Not asserted here; the holding exists to reach the concat.
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import EQUITY_EXPOSURE_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.facility_share_portfolio import (
    CP_SA,
    FAC_SHARE,
    build_facility_share_bundle,
    facility_share_config,
)
from tests.fixtures.raw_bundle import seal_raw_table

#: One listed equity holding, booked to the facility owner so no counterparty
#: row has to be invented. Listed rather than CIU or unlisted: the simplest row
#: that reaches ``prepare_equity_results``, with no look-through and no
#: transitional branch to make the path conditional.
EQUITY_REFERENCE = "FS-EQ-LISTED"
EQUITY_VALUE = 1_000_000.0

#: The carriers under test, and the dtypes the aggregator exit declares.
SHARE_CARRIERS: dict[str, pl.DataType] = {
    "facility_share_group": pl.String,
    "is_facility_share_candidate": pl.Boolean,
}


def _equity_exposures() -> pl.DataFrame:
    """The one equity row, typed against ``EQUITY_EXPOSURE_SCHEMA``."""
    return pl.DataFrame(
        {
            "exposure_reference": [EQUITY_REFERENCE],
            "counterparty_reference": [CP_SA],
            "equity_type": ["listed"],
            "currency": ["GBP"],
            "carrying_value": [EQUITY_VALUE],
            "fair_value": [EQUITY_VALUE],
            "is_speculative": [False],
            "is_exchange_traded": [True],
            "is_government_supported": [False],
            "is_significant_investment": [False],
            "business_age_years": [10.0],
        },
        schema={
            name: dtype
            for name, dtype in dtypes_of(EQUITY_EXPOSURE_SCHEMA).items()
            if name
            in {
                "exposure_reference",
                "counterparty_reference",
                "equity_type",
                "currency",
                "carrying_value",
                "fair_value",
                "is_speculative",
                "is_exchange_traded",
                "is_government_supported",
                "is_significant_investment",
                "business_age_years",
            }
        },
    )


_CACHE: dict[str, pl.DataFrame] = {}


def _sealed_results(framework: str) -> pl.DataFrame:
    """Run FS-1 plus the equity holding and return the sealed results frame."""
    if framework in _CACHE:
        return _CACHE[framework]

    bundle = dataclasses.replace(
        build_facility_share_bundle("binding"),
        equity_exposures=seal_raw_table(_equity_exposures(), "equity_exposures"),
    )
    result = PipelineOrchestrator().run_with_data(bundle, facility_share_config(framework))
    # An edge-contract violation reddens results wholesale and would otherwise be
    # misread as a facility-share finding (LESSONS D3).
    assert not [error for error in result.errors if "contract violated" in error.message]

    frame = result.results.collect()
    _CACHE[framework] = frame
    return frame


@pytest.fixture(params=["CRR", "BASEL_3_1"])
def results(request: pytest.FixtureRequest) -> pl.DataFrame:
    """The sealed results frame under each regime."""
    return _sealed_results(request.param)


def _adequacy_both_producers_are_live(frame: pl.DataFrame) -> None:
    """Both producers reached the exit, so a null-free frame means something.

    Asserted at the top of every test with the reason in the message. A frame
    with no equity row cannot express the defect, and a frame with no facility-
    share candidate cannot distinguish "every producer resolves the flag" from
    "no producer ever sets it" — the fixture would be vacuous in either
    direction and would stay green through the mutation the module docstring
    names (LESSONS C11).
    """
    approaches = frame["approach_applied"].to_list()
    assert ApproachType.EQUITY.value in approaches, (
        "no equity row reached the sealed exit, so this frame never took the "
        "diagonal concat that injects the null - the test would be vacuous"
    )
    assert EQUITY_REFERENCE in frame["exposure_reference"].to_list(), (
        f"{EQUITY_REFERENCE} is absent from the results; the holding was "
        "dropped before the exit and nothing below observes the equity path"
    )
    assert [a for a in approaches if a != ApproachType.EQUITY.value], (
        "every row is an equity row, so there is no branch-sealed row to "
        "compare against and a flag missing everywhere would look identical"
    )


class TestFacilityShareCarriersOnTheEquityPath:
    """The equity producer resolves both carriers, so the sealed exit is total."""

    def test_no_null_candidate_flag_reaches_the_sealed_exit(self, results: pl.DataFrame) -> None:
        """
        ``is_facility_share_candidate`` is non-null on EVERY row of the exit.

        Arrange: the FS-1 portfolio plus one listed equity holding, under one
                 regime.
        Act:     run the whole pipeline and collect the sealed results.
        Assert:  the flag is present, Boolean, and carries zero nulls.

        Zero, stated as a count rather than as "the equity row is False", because
        the claim is about the COLUMN: a producer added later that bypasses the
        branch seals fails here even though nobody thought to name it.
        """
        # Arrange
        _adequacy_both_producers_are_live(results)

        # Act
        column = "is_facility_share_candidate"

        # Assert — presence, then dtype, then the null count.
        assert column in results.columns, (
            f"{column} is not on the sealed aggregator exit at all; a column "
            "dropped by EdgeContract.conform raises nothing (LESSONS B1)"
        )
        assert results.schema[column] == pl.Boolean
        assert results[column].null_count() == 0, (
            f"{results[column].null_count()} row(s) carry a NULL "
            f"{column} at the sealed exit; the rows are "
            f"{results.filter(pl.col(column).is_null())['exposure_reference'].to_list()}"
        )

    def test_the_group_column_is_string_typed_on_the_exit(self, results: pl.DataFrame) -> None:
        """
        ``facility_share_group`` is declared String and survives the equity concat.

        Arrange: the same frame.
        Act:     read the column's dtype.
        Assert:  ``pl.String``, not ``pl.Null``.

        The group column is legitimately null on a non-share row, so its null
        COUNT proves nothing. Its DTYPE does: an untyped ``pl.lit(None)`` in the
        equity producer lands as ``pl.Null`` and the diagonal concat then widens
        the whole column, which is a dtype violation the sealed edge rejects and
        no unit test on the producer alone can see.
        """
        # Arrange
        _adequacy_both_producers_are_live(results)

        # Act / Assert
        assert "facility_share_group" in results.columns
        assert results.schema["facility_share_group"] == pl.String

    def test_the_equity_row_is_false_and_ungrouped(self, results: pl.DataFrame) -> None:
        """
        The equity holding itself carries ``False`` and a null group.

        Arrange: the same frame.
        Act:     read the equity row.
        Assert:  the flag is exactly ``False`` (not null, not True) and the group
                 is null.

        An equity holding is never a facility-share candidate — the fan-out
        replicates synthetic ``facility_undrawn`` rows only — so False is the
        substantive claim and null the absence of one. The two are different
        claims and this test makes both.
        """
        # Arrange
        _adequacy_both_producers_are_live(results)

        # Act
        row = results.filter(pl.col("exposure_reference") == EQUITY_REFERENCE).to_dicts()[0]

        # Assert
        assert row["is_facility_share_candidate"] is False
        assert row["facility_share_group"] is None
        assert row["rwa_final"] is not None, (
            "the equity row reached the exit unpriced, so it is not the "
            "ordinary equity path this test claims to exercise"
        )

    def test_the_share_candidates_are_flagged_beside_the_equity_row(
        self, results: pl.DataFrame
    ) -> None:
        """
        The facility-share rows still carry their group in the same frame.

        Arrange: the same frame.
        Act:     read the rows whose ``source_exposure_reference`` is the shared
                 facility.
        Assert:  at least one carries the group, and every one of them is
                 flagged ``True``.

        The other half of the two-leg pattern: a mutation that zeroed the flag
        for EVERY producer would satisfy the null-count test above, because
        ``False`` everywhere is also null-free. This leg is what distinguishes
        "resolved by both producers" from "silenced for all of them".

        RED until the S3 resolver lands? No — the fan-out is an S2 emission and
        the candidates are already flagged at the exit. If S3 later drops the
        losers and collapses the winner's reference, the surviving row keeps its
        group and its flag is False, so this assertion is written over the
        group column, which both states carry.
        """
        # Arrange
        _adequacy_both_producers_are_live(results)

        # Act
        share_rows = results.filter(pl.col("source_exposure_reference") == FAC_SHARE).to_dicts()

        # Assert
        assert share_rows, f"no row of {FAC_SHARE} reached the exit"
        grouped = [row for row in share_rows if row["facility_share_group"] == FAC_SHARE]
        assert grouped, (
            f"no row of {FAC_SHARE} carries facility_share_group at the sealed "
            "exit; the carrier was dropped somewhere in the edge chain and the "
            "null-count assertion above would pass on an all-False column"
        )
