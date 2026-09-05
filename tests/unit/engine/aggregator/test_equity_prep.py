"""Unit tests for ``prepare_equity_results`` (aggregator equity-prep helper).

Covers the R4 fix: under Basel 3.1 equity is standardised-only (Art. 147A), so
an equity leg's standardised-equivalent RWA (``sa_rwa``) is its own pre-floor
RWA. ``prepare_equity_results`` must populate ``sa_rwa`` for equity legs when the
output-floor regime is active (``include_sa_equivalent=True``) so the disclosed
S-TREA (OF 02.01 col 0040, C 02.00 col 0020, CMS1/CMS2 col d) does not silently
drop equity — and must NOT mint the column otherwise (CRR frames never carry it).

Also covers the facility-share carriers. Equity is the ONE producer that reaches
the sealed aggregator exit without passing an SA / IRB / slotting branch seal —
it is concatenated straight onto the combined frame with ``how="diagonal_relaxed"``
— so nothing upstream resolves ``facility_share_group`` or
``is_facility_share_candidate`` for an equity row, and the diagonal concat would
inject a NULL where the branch seals inject False. ``AGGREGATOR_EXIT_EDGE``
carries no ``fill_null_default``, so a null flag would reach the sealed ledger
and ``~col`` on it raises while ``col == True`` passes silently (LESSONS B1).
``prepare_equity_results`` therefore emits both columns itself.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.aggregator._equity_prep import prepare_equity_results


def _equity_frame() -> pl.LazyFrame:
    """One listed equity leg: EAD 1,000,000 x 250% = 2,500,000 RWA (B31 SA)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EQ1"],
            "equity_type": ["listed"],
            "ead_final": [1_000_000.0],
            "risk_weight": [2.5],
            "rwa": [2_500_000.0],
            "rwa_final": [2_500_000.0],
        }
    )


class TestPrepareEquityResultsSaEquivalent:
    """The ``include_sa_equivalent`` gate on ``sa_rwa``."""

    def test_sa_rwa_populated_when_output_floor_active(self) -> None:
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert — equity's standardised-equivalent RWA is its own pre-floor RWA.
        assert "sa_rwa" in prepared.columns
        assert prepared["sa_rwa"].to_list() == [2_500_000.0]

    def test_sa_rwa_equals_own_pre_floor_rwa(self) -> None:
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert — sa_rwa mirrors the ``rwa`` (pre-floor) carrier, not a re-derived value.
        assert prepared["sa_rwa"][0] == prepared["rwa"][0]

    def test_no_sa_rwa_column_when_gate_off(self) -> None:
        # Arrange
        frame = _equity_frame()

        # Act — the CRR path: sa_rwa is never computed, so no column is minted.
        prepared = prepare_equity_results(frame, include_sa_equivalent=False).collect()

        # Assert
        assert "sa_rwa" not in prepared.columns

    def test_default_does_not_mint_sa_rwa(self) -> None:
        # Arrange
        frame = _equity_frame()

        # Act — the default is the conservative CRR-safe behaviour.
        prepared = prepare_equity_results(frame).collect()

        # Assert
        assert "sa_rwa" not in prepared.columns

    def test_sa_rwa_falls_back_to_rwa_final_when_rwa_absent(self) -> None:
        # Arrange — a frame carrying only rwa_final (the PD/LGD equity path aliases both).
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["EQ1"],
                "ead_final": [1_000_000.0],
                "rwa_final": [1_900_000.0],
            }
        )

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert
        assert prepared["sa_rwa"].to_list() == [1_900_000.0]

    def test_equity_tag_and_rwa_final_still_set(self) -> None:
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert — the existing contract is untouched by the new column.
        assert prepared["approach_applied"].to_list() == [ApproachType.EQUITY.value]
        assert prepared["rwa_final"].to_list() == [2_500_000.0]
        assert prepared["source_exposure_reference"].to_list() == ["EQ1"]


class TestPrepareEquityResultsFacilityShareCarriers:
    """The two facility-share carriers, which only this producer can resolve.

    Mutation these detect: delete the two ``pl.lit(...)`` expressions from
    ``engine/aggregator/_equity_prep.py`` — i.e. revert the columns the S2 slice
    added. Every branch-sealed row keeps its False, so the whole SA / IRB /
    slotting estate stays green; only equity rows go null, and only at the
    sealed exit, where nothing today reads the flag. The pipeline-level twin is
    ``tests/integration/test_facility_share_equity_exit.py``.
    """

    @pytest.mark.parametrize("include_sa_equivalent", [True, False])
    def test_both_carriers_are_emitted_whatever_the_floor_gate(
        self, include_sa_equivalent: bool
    ) -> None:
        """Both columns are present under CRR and under Basel 3.1.

        The ``include_sa_equivalent`` gate governs ``sa_rwa`` alone. Binding the
        share carriers to it would leave the CRR frame short two columns that
        ``AGGREGATOR_EXIT_EDGE`` declares, so the parametrisation is the guard
        against a future edit folding them into that ``if``.
        """
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(
            frame, include_sa_equivalent=include_sa_equivalent
        ).collect()

        # Assert — presence first: absence and a wrong value are different claims.
        assert "facility_share_group" in prepared.columns
        assert "is_facility_share_candidate" in prepared.columns

    def test_group_is_a_typed_null_string(self) -> None:
        """``facility_share_group`` is String-typed and null on every equity row.

        Null rather than an empty string: null is what every non-share row in the
        estate carries, and the aggregator exit declares the column ``pl.String``.
        An untyped ``pl.lit(None)`` would land as Null dtype and violate the seal.
        """
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert
        assert prepared.schema["facility_share_group"] == pl.String
        assert prepared["facility_share_group"].null_count() == len(prepared)

    def test_candidate_flag_is_boolean_false_never_null(self) -> None:
        """``is_facility_share_candidate`` is Boolean False on every equity row.

        False, not null: an equity holding is never a facility-share candidate
        (the fan-out replicates synthetic ``facility_undrawn`` rows only), and a
        null would make the column three-state on the sealed exit — where
        ``filter(~col)`` raises on an all-null column and ``col == True`` drops
        the row silently.
        """
        # Arrange
        frame = _equity_frame()

        # Act
        prepared = prepare_equity_results(frame, include_sa_equivalent=True).collect()

        # Assert
        assert prepared.schema["is_facility_share_candidate"] == pl.Boolean
        assert prepared["is_facility_share_candidate"].null_count() == 0
        assert prepared["is_facility_share_candidate"].to_list() == [False]
