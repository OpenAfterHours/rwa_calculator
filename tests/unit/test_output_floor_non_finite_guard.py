"""
Unit tests — the output floor must not spread one row's NaN portfolio-wide.

Pre-guard, ``apply_floor_with_impact`` summed ``rwa_pre_floor`` / ``sa_rwa``
over all floor-eligible rows: Polars float ``.sum()`` propagates NaN, so a
single poisoned row turned U-TREA/S-TREA — and hence the pro-rata
``floor_impact_rwa`` and post-floor ``rwa_final`` of EVERY eligible row — into
NaN (observed live: one NaN guarantee input blanked a whole B31 portfolio).

The guard excludes rows with a non-finite ``rwa_pre_floor`` or ``sa_rwa`` from
the floor computation entirely: they take no shortfall share, contribute
nothing to the totals, and keep their own (already AGG001-flagged) value.

Hand-calc (mirrors test_p2_20 fixture + one poisoned row):
  SA1  : standardised, rwa 100
  IRB1 : FIRB, rwa 200, sa_rwa 250
  SLOT1: slotting, rwa 50, sa_rwa 386.2069 - 250
  BAD1 : FIRB, rwa NaN, sa_rwa NaN            (excluded from the floor)
  U-TREA = 250, S-TREA = 386.2069, threshold = 0.725 x S-TREA = 280,
  shortfall = 30 — identical to the clean fixture.

References:
- PRA PS1/26 Art. 92 para 2A (portfolio floor)
- engine/aggregator/_floor.py::apply_floor_with_impact (unit under test)
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.engine.aggregator._floor import apply_floor_with_impact

_FLOOR_PCT = 0.725
_S_TREA_MODELLED = 280.0 / 0.725
_S_IRB = 250.0
_S_SLOT = _S_TREA_MODELLED - _S_IRB
NAN = float("nan")


def _combined_with_poisoned_row() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA1", "IRB1", "SLOT1", "BAD1"],
            "approach_applied": ["standardised", "FIRB", "slotting", "FIRB"],
            "exposure_class": ["CORPORATE"] * 4,
            "ead_final": [100.0, 200.0, 50.0, 75.0],
            "risk_weight": [1.0, 1.0, 1.0, NAN],
            "rwa_final": [100.0, 200.0, 50.0, NAN],
            "sa_rwa": [100.0, _S_IRB, _S_SLOT, NAN],
        }
    )


@pytest.fixture(scope="module")
def floored() -> tuple[pl.DataFrame, pl.DataFrame, object]:
    result, impact, summary = apply_floor_with_impact(
        combined=_combined_with_poisoned_row(),
        sa_results=pl.LazyFrame(schema={"exposure_reference": pl.String}),
        floor_pct=_FLOOR_PCT,
    )
    return result.collect(), impact.collect(), summary


class TestFloorSummaryIgnoresNonFiniteRows:
    """Portfolio totals are computed from the finite rows only."""

    def test_u_trea_excludes_poisoned_row(self, floored) -> None:
        _, _, summary = floored
        assert summary.u_trea == pytest.approx(250.0)

    def test_s_trea_excludes_poisoned_row(self, floored) -> None:
        _, _, summary = floored
        assert summary.s_trea == pytest.approx(_S_TREA_MODELLED)

    def test_shortfall_matches_clean_fixture(self, floored) -> None:
        _, _, summary = floored
        assert summary.shortfall == pytest.approx(30.0)
        assert summary.portfolio_floor_binding is True

    def test_summary_totals_are_finite(self, floored) -> None:
        _, _, summary = floored
        for field in ("u_trea", "s_trea", "floor_threshold", "shortfall", "total_rwa_post_floor"):
            assert math.isfinite(getattr(summary, field)), f"{field} must stay finite"


class TestHealthyRowsStayFinite:
    """The shortfall is distributed across the finite eligible rows only."""

    def test_healthy_rows_receive_full_shortfall(self, floored) -> None:
        result, _, _ = floored
        healthy = result.filter(pl.col("exposure_reference").is_in(["IRB1", "SLOT1"]))
        assert healthy.get_column("rwa_final").is_finite().all()
        total_impact = healthy.get_column("floor_impact_rwa").sum()
        assert total_impact == pytest.approx(30.0)

    def test_irb1_pro_rata_share(self, floored) -> None:
        result, _, _ = floored
        irb1 = result.filter(pl.col("exposure_reference") == "IRB1")
        expected = 200.0 + 30.0 * (_S_IRB / _S_TREA_MODELLED)
        assert irb1.get_column("rwa_final")[0] == pytest.approx(expected)

    def test_sa_row_untouched(self, floored) -> None:
        result, _, _ = floored
        sa1 = result.filter(pl.col("exposure_reference") == "SA1")
        assert sa1.get_column("rwa_final")[0] == pytest.approx(100.0)


class TestPoisonedRowStaysFlaggedNotSpread:
    """The poisoned row keeps its NaN (AGG001's job) but takes no floor share."""

    def test_bad_row_rwa_final_stays_nan(self, floored) -> None:
        result, _, _ = floored
        bad = result.filter(pl.col("exposure_reference") == "BAD1")
        assert bad.get_column("rwa_final").is_nan()[0], (
            "the poisoned row's own NaN must survive for AGG001 to report"
        )

    def test_bad_row_takes_no_shortfall_share(self, floored) -> None:
        result, _, _ = floored
        bad = result.filter(pl.col("exposure_reference") == "BAD1")
        assert bad.get_column("floor_impact_rwa")[0] == 0.0
        assert bad.get_column("is_floor_binding")[0] is False


class TestNonFiniteSaRwaOnly:
    """A finite-RWA row with NaN sa_rwa is excluded from the floor, not poisoned."""

    def test_finite_rwa_nan_sa_rwa_keeps_pre_floor_value(self) -> None:
        combined = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1", "BAD_SA"],
                "approach_applied": ["FIRB", "FIRB"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "ead_final": [200.0, 100.0],
                "risk_weight": [1.0, 1.0],
                "rwa_final": [200.0, 100.0],
                "sa_rwa": [_S_TREA_MODELLED, NAN],
            }
        )
        result, _, summary = apply_floor_with_impact(
            combined=combined,
            sa_results=pl.LazyFrame(schema={"exposure_reference": pl.String}),
            floor_pct=_FLOOR_PCT,
        )
        df = result.collect()

        assert summary.s_trea == pytest.approx(_S_TREA_MODELLED)
        bad = df.filter(pl.col("exposure_reference") == "BAD_SA")
        assert bad.get_column("rwa_final")[0] == pytest.approx(100.0), (
            "a row excluded from the floor keeps its pre-floor RWA"
        )
        good = df.filter(pl.col("exposure_reference") == "IRB1")
        assert math.isfinite(good.get_column("rwa_final")[0])
