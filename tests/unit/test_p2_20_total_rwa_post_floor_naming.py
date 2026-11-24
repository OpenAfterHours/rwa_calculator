"""
Unit tests for P2.20 — OutputFloorSummary field rename and total_rwa_post_floor
redefinition.

P2.20 makes the following changes to OutputFloorSummary:
- RENAME  ``total_rwa_post_floor``  ->  ``floored_modelled_rwa``  (modelled-only
  scope; arithmetic unchanged: u_trea + shortfall).
- ADD     ``sa_rwa_total: float = 0.0``  (sum of SA RWA across portfolio).
- ADD     ``equity_rwa_total: float = 0.0``  (sum of equity RWA).
- REDEFINE ``total_rwa_post_floor: float`` = floored_modelled_rwa + sa_rwa_total
  + equity_rwa_total  (genuine portfolio total including all approaches).

These tests assert the new field names exist on the dataclass and that the
arithmetic is correct given the hand-calc reference from the architect proposal.

Hand-calc reference (4-row combined frame). Both legs of the Art. 92(2A) max
are whole-book (PS1/26 Art. 92(3) / 92(3A), P1.367), so the SA and equity rows
sit in U-TREA and S-TREA alike:
  SA1   : approach_applied="standardised", rwa_final=100.0, sa_rwa=100.0
  IRB1  : approach_applied="FIRB",         rwa_final=200.0, sa_rwa=S_IRB
  SLOT1 : approach_applied="slotting",     rwa_final=50.0,  sa_rwa=S_SLOT
  EQ1   : approach_applied="equity",       rwa_final=30.0,  sa_rwa=30.0

  U-TREA = 100 + 200 + 50 + 30 = 380.0
  S-TREA chosen so the floor binds by 30: 0.725 * S-TREA = 410.0
      ->  S-TREA = 565.5172, of which the SA and equity rows are 130.0
      ->  S_IRB + S_SLOT = 435.5172; we use S_IRB = 250.0, S_SLOT = 185.5172
  floor_threshold = 0.725 * 565.5172 = 410.0
  shortfall = max(0, 410.0 - 380.0) = 30.0 (carried by IRB1 and SLOT1 only)
  floored_modelled_rwa = 250.0 + 30.0 = 280.0
  sa_rwa_total = 100.0          (SA1's rwa_final)
  equity_rwa_total = 30.0       (EQ1's rwa_final)
  total_rwa_post_floor = 280.0 + 100.0 + 30.0 = 410.0 = max(U-TREA, threshold)

  Before P1.367 the SA and equity rows were left out of both legs: threshold
  0.725 * 435.5172 = 315.75, floored_modelled_rwa 315.75, total 445.75.

References:
- PRA PS1/26 Art. 92 para 2A
- IMPLEMENTATION_PLAN.md item P2.20
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from rwa_calc.contracts.bundles import OutputFloorSummary

# =========================================================================
# Shared test constants (hand-calc from architect proposal)
# =========================================================================

_FLOOR_PCT = 0.725

_SA_RWA_TOTAL = 100.0
_EQUITY_RWA_TOTAL = 30.0
_MODELLED_RWA = 250.0  # IRB1 + SLOT1 own RWEA
_U_TREA = _MODELLED_RWA + _SA_RWA_TOTAL + _EQUITY_RWA_TOTAL  # = 380.0

# We want floor_threshold = 410.0 exactly: 0.725 * S-TREA = 410, S-TREA whole-book.
_S_TREA = 410.0 / _FLOOR_PCT  # ≈ 565.51724138
_S_TREA_MODELLED = _S_TREA - _SA_RWA_TOTAL - _EQUITY_RWA_TOTAL  # ≈ 435.51724138

# Arbitrary split of the modelled SA-equivalent between IRB and slotting.
_S_IRB = 250.0
_S_SLOT = _S_TREA_MODELLED - _S_IRB  # ≈ 185.51724138

_SHORTFALL = 30.0  # max(0, 410 - 380)
_FLOORED_MODELLED_RWA = _MODELLED_RWA + _SHORTFALL  # = 280.0
_TOTAL_RWA_POST_FLOOR = _FLOORED_MODELLED_RWA + _SA_RWA_TOTAL + _EQUITY_RWA_TOTAL  # = 410.0

# =========================================================================
# Helpers
# =========================================================================


def _make_combined() -> pl.LazyFrame:
    """Synthetic 4-row combined frame as described by the architect proposal."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA1", "IRB1", "SLOT1", "EQ1"],
            "approach_applied": ["standardised", "FIRB", "slotting", "equity"],
            "exposure_class": ["CORPORATE", "CORPORATE", "SPECIALISED_LENDING", "EQUITY"],
            "ead_final": [100.0, 200.0, 50.0, 30.0],
            "risk_weight": [1.0, 1.0, 1.0, 1.0],
            "rwa_final": [100.0, 200.0, 50.0, 30.0],
            "sa_rwa": [100.0, _S_IRB, _S_SLOT, 30.0],
        }
    )


def _run_floor(combined: pl.LazyFrame) -> OutputFloorSummary:
    """Call apply_floor_with_impact and return the summary."""
    from rwa_calc.engine.aggregator._floor import apply_floor_with_impact

    _, _, summary = apply_floor_with_impact(
        combined=combined,
        sa_results=combined,
        floor_pct=_FLOOR_PCT,
    )
    return summary


# =========================================================================
# Test 1 — field rename: floored_modelled_rwa exists on OutputFloorSummary
# =========================================================================


class TestFlooredModelledRwaFieldRenamed:
    """P2.20: ``total_rwa_post_floor`` is RENAMED to ``floored_modelled_rwa``."""

    def test_floored_modelled_rwa_field_exists_on_dataclass(self) -> None:
        """OutputFloorSummary must expose a field named ``floored_modelled_rwa``."""
        # Arrange
        field_names = {f.name for f in dataclasses.fields(OutputFloorSummary)}

        # Act / Assert
        assert "floored_modelled_rwa" in field_names, (
            "OutputFloorSummary is missing the 'floored_modelled_rwa' field. "
            "P2.20 renames 'total_rwa_post_floor' (modelled-only) to "
            "'floored_modelled_rwa'."
        )

    def test_sa_rwa_total_field_exists_on_dataclass(self) -> None:
        """OutputFloorSummary must expose a field named ``sa_rwa_total``."""
        # Arrange
        field_names = {f.name for f in dataclasses.fields(OutputFloorSummary)}

        # Act / Assert
        assert "sa_rwa_total" in field_names, (
            "OutputFloorSummary is missing the 'sa_rwa_total' field added by P2.20."
        )

    def test_equity_rwa_total_field_exists_on_dataclass(self) -> None:
        """OutputFloorSummary must expose a field named ``equity_rwa_total``."""
        # Arrange
        field_names = {f.name for f in dataclasses.fields(OutputFloorSummary)}

        # Act / Assert
        assert "equity_rwa_total" in field_names, (
            "OutputFloorSummary is missing the 'equity_rwa_total' field added by P2.20."
        )

    def test_floored_modelled_rwa_value_equals_u_trea_plus_shortfall(self) -> None:
        """``floored_modelled_rwa`` = modelled own RWEA + shortfall (modelled-only scope).

        Hand-calc: modelled RWEA=250, shortfall=30 → floored_modelled_rwa=280.
        """
        # Arrange
        combined = _make_combined()

        # Act
        summary = _run_floor(combined)

        # Assert
        assert summary.floored_modelled_rwa == pytest.approx(_FLOORED_MODELLED_RWA, rel=1e-4), (
            f"Expected floored_modelled_rwa={_FLOORED_MODELLED_RWA}, "
            f"got {summary.floored_modelled_rwa}"
        )


# =========================================================================
# Test 2 — total_rwa_post_floor is the genuine portfolio sum
# =========================================================================


class TestTotalRwaPostFloorSumsAllComponents:
    """P2.20: ``total_rwa_post_floor`` = floored_modelled_rwa + sa_rwa_total + equity_rwa_total."""

    def test_total_rwa_post_floor_includes_sa_rwa(self) -> None:
        """``total_rwa_post_floor`` must include the SA RWA total (100.0)."""
        # Arrange
        combined = _make_combined()

        # Act
        summary = _run_floor(combined)

        # Assert
        assert summary.sa_rwa_total == pytest.approx(_SA_RWA_TOTAL, rel=1e-4), (
            f"Expected sa_rwa_total={_SA_RWA_TOTAL}, got {summary.sa_rwa_total}"
        )

    def test_total_rwa_post_floor_includes_equity_rwa(self) -> None:
        """``total_rwa_post_floor`` must include the equity RWA total (30.0)."""
        # Arrange
        combined = _make_combined()

        # Act
        summary = _run_floor(combined)

        # Assert
        assert summary.equity_rwa_total == pytest.approx(_EQUITY_RWA_TOTAL, rel=1e-4), (
            f"Expected equity_rwa_total={_EQUITY_RWA_TOTAL}, got {summary.equity_rwa_total}"
        )

    def test_total_rwa_post_floor_is_genuine_portfolio_total(self) -> None:
        """``total_rwa_post_floor`` = floored_modelled_rwa + sa_rwa_total + equity_rwa_total.

        Hand-calc: 280 + 100 + 30 = 410 = max(U-TREA 380, threshold 410).
        """
        # Arrange
        combined = _make_combined()

        # Act
        summary = _run_floor(combined)

        # Assert
        assert summary.u_trea == pytest.approx(_U_TREA, rel=1e-9)
        assert summary.s_trea == pytest.approx(_S_TREA, rel=1e-9)
        assert summary.total_rwa_post_floor == pytest.approx(_TOTAL_RWA_POST_FLOOR, rel=1e-4), (
            f"Expected total_rwa_post_floor={_TOTAL_RWA_POST_FLOOR} "
            f"(floored_modelled={_FLOORED_MODELLED_RWA} + "
            f"sa={_SA_RWA_TOTAL} + equity={_EQUITY_RWA_TOTAL}), "
            f"got {summary.total_rwa_post_floor}"
        )

    def test_total_rwa_post_floor_equals_sum_of_components(self) -> None:
        """``total_rwa_post_floor`` == floored_modelled_rwa + sa_rwa_total + equity_rwa_total."""
        # Arrange
        combined = _make_combined()

        # Act
        summary = _run_floor(combined)

        # Assert — algebraic identity, independent of exact hand-calc numbers
        expected = summary.floored_modelled_rwa + summary.sa_rwa_total + summary.equity_rwa_total
        assert summary.total_rwa_post_floor == pytest.approx(expected, rel=1e-4), (
            f"total_rwa_post_floor ({summary.total_rwa_post_floor}) != "
            f"floored_modelled_rwa ({summary.floored_modelled_rwa}) + "
            f"sa_rwa_total ({summary.sa_rwa_total}) + "
            f"equity_rwa_total ({summary.equity_rwa_total})"
        )

    def test_sa_and_equity_rows_move_the_modelled_floor(self) -> None:
        """The SA and equity book is inside both legs, so it changes the floor's bite.

        Removing SA1 and EQ1 leaves U-TREA 250 and S-TREA 435.5172: threshold
        315.75, so the modelled rows carry a 65.75 shortfall. With them in both
        legs (380 vs 410) the shortfall is 30 — the article's (1 - x) of the SA
        and equity book, 0.275 x 130 = 35.75, is the difference.
        """
        # Arrange
        combined_modelled_only = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1", "SLOT1"],
                "approach_applied": ["FIRB", "slotting"],  # canonical/fallback IRB labels
                "exposure_class": ["CORPORATE", "SPECIALISED_LENDING"],
                "ead_final": [200.0, 50.0],
                "risk_weight": [1.0, 1.0],
                "rwa_final": [200.0, 50.0],
                "sa_rwa": [_S_IRB, _S_SLOT],
            }
        )
        combined_full = _make_combined()

        # Act
        summary_modelled_only = _run_floor(combined_modelled_only)
        summary_full = _run_floor(combined_full)

        # Assert
        assert summary_modelled_only.floored_modelled_rwa == pytest.approx(
            _FLOOR_PCT * _S_TREA_MODELLED, rel=1e-9
        )
        assert summary_full.floored_modelled_rwa == pytest.approx(_FLOORED_MODELLED_RWA, rel=1e-9)
        assert (
            summary_modelled_only.floored_modelled_rwa - summary_full.floored_modelled_rwa
        ) == pytest.approx((1 - _FLOOR_PCT) * (_SA_RWA_TOTAL + _EQUITY_RWA_TOTAL), rel=1e-9)
