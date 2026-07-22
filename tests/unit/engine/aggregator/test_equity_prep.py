"""Unit tests for ``prepare_equity_results`` (aggregator equity-prep helper).

Covers the R4 fix: under Basel 3.1 equity is standardised-only (Art. 147A), so
an equity leg's standardised-equivalent RWA (``sa_rwa``) is its own pre-floor
RWA. ``prepare_equity_results`` must populate ``sa_rwa`` for equity legs when the
output-floor regime is active (``include_sa_equivalent=True``) so the disclosed
S-TREA (OF 02.01 col 0040, C 02.00 col 0020, CMS1/CMS2 col d) does not silently
drop equity — and must NOT mint the column otherwise (CRR frames never carry it).
"""

from __future__ import annotations

import polars as pl

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
