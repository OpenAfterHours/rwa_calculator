"""
Unit tests for T2 credit cap isolation from output floor (P1.84 / P1.9a).

Tests verify that the T2 credit cap (Art. 62(d)) uses un-floored IRB RWA,
not post-floor TREA.  Art. 62(d) references "risk-weighted exposure amounts
calculated under Chapter 3 of Title II of Part Three" — the IRB chapter.
The output floor (Art. 92(2A)) is a portfolio-level capital requirement in
Part Two, not an IRB calculation, so it must NOT inflate the T2 cap basis.

Using post-floor TREA would also create a circular dependency with the
OF-ADJ formula (Art. 92(2A)): OF-ADJ depends on IRB T2 credit, which
depends on the T2 cap, which would depend on TREA, which depends on OF-ADJ.

Why these tests matter:
If the T2 credit cap were computed on post-floor RWA, it would be overstated
for any bank where the output floor binds.  A higher cap allows more T2 credit
(excess provisions counted toward own funds), which understates the bank's
actual shortfall and overstates its capital position.  For a bank with IRB
RWA of 50m and floored TREA of 72.5m, the cap difference is:
  - Correct (pre-floor):  50m × 0.6% = 300k
  - Wrong (post-floor):   72.5m × 0.6% = 435k  (45% overstatement)

References:
- CRR Art. 62(d): T2 credit cap (0.6% of IRB credit risk RWA)
- PRA PS1/26 Art. 92(2A): Output floor formula (TREA = max(U-TREA, x*S-TREA + OF-ADJ))
- CRR Art. 158-159: EL shortfall/excess treatment
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.aggregator._schemas import T2_CREDIT_CAP_RATE

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Fully-phased Basel 3.1 config (72.5% floor)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))


def _irb_frame_with_el(
    rwa: float = 50_000_000.0,
    sa_rwa: float = 100_000_000.0,
    excess: float = 500_000.0,
) -> pl.LazyFrame:
    """IRB frame with EL columns and SA RWA for floor computation.

    Default values produce a binding floor scenario:
    IRB RWA 50m vs SA RWA 100m × 72.5% = 72.5m floor.
    """
    return pl.LazyFrame({
        "exposure_reference": ["EXP001"],
        "exposure_class": ["CORPORATE"],
        "approach_applied": ["FIRB"],
        "ead_final": [200_000_000.0],
        "risk_weight": [rwa / 200_000_000.0],
        "rwa_post_factor": [rwa],
        "rwa_final": [rwa],
        "sa_rwa": [sa_rwa],
        "expected_loss": [100_000.0],
        "provision_allocated": [100_000.0 + excess],
        "el_shortfall": [0.0],
        "el_excess": [excess],
    })


# =============================================================================
# T2 Cap Uses Pre-Floor IRB RWA (P1.84)
# =============================================================================


class TestT2CapFloorIsolation:
    """T2 credit cap must use un-floored IRB RWA, not post-floor TREA."""

    def test_t2_cap_uses_pre_floor_rwa_when_floor_binds(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Core test: T2 cap = 0.6% of pre-floor IRB RWA, not floored TREA.

        Setup: IRB RWA = 50m, SA RWA = 100m, floor = 72.5%.
        T2 credit = min(excess 500k, cap 300k) = 300k.
        OF-ADJ = 12.5 × (300k - 0 - 0 + 0) = 3.75m.
        Floor threshold = 72.5% × 100m + 3.75m = 76.25m.
        Floor binds: TREA = 76.25m (> 50m).
        T2 cap must be 50m × 0.6% = 300k (not 76.25m × 0.6% = 457.5k).
        """
        irb = _irb_frame_with_el(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        # Verify floor actually binds
        assert result.output_floor_summary is not None
        assert result.output_floor_summary.portfolio_floor_binding is True

        # Verify rwa_final includes OF-ADJ (72.5m base + 3.75m OF-ADJ = 76.25m)
        df = result.results.collect()
        total_rwa_final = df["rwa_final"].sum()
        assert total_rwa_final == pytest.approx(76_250_000.0, rel=0.01)

        # Verify T2 cap uses pre-floor IRB RWA (50m), not post-floor (72.5m)
        el = result.el_summary
        assert el is not None
        pre_floor_rwa = 50_000_000.0
        assert float(el.total_irb_rwa) == pytest.approx(pre_floor_rwa, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(pre_floor_rwa * T2_CREDIT_CAP_RATE, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(300_000.0, rel=0.001)

    def test_t2_cap_equals_pre_floor_irb_rwa_times_rate(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """T2 cap formula: total_irb_rwa × 0.006 (Art. 62(d))."""
        irb = _irb_frame_with_el(rwa=80_000_000.0, sa_rwa=200_000_000.0, excess=1_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        el = result.el_summary
        assert el is not None
        # Pre-floor IRB RWA = 80m
        assert float(el.total_irb_rwa) == pytest.approx(80_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(80_000_000.0 * 0.006, rel=0.001)

    def test_t2_credit_capped_at_pre_floor_rate(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """T2 credit = min(excess, cap).  Cap based on pre-floor RWA.

        Excess = 500k, pre-floor cap = 300k → credit = 300k.
        If cap were wrongly based on post-floor 72.5m, cap = 435k
        and credit = 435k, overstating T2 capital by 135k.
        """
        irb = _irb_frame_with_el(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        el = result.el_summary
        assert el is not None
        assert float(el.t2_credit) == pytest.approx(300_000.0, rel=0.001)
        # Excess 500k exceeds cap 300k → capped
        assert el.t2_credit < el.total_el_excess

    def test_floor_not_binding_t2_cap_unchanged(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """When floor does not bind, T2 cap still uses IRB RWA (same value)."""
        irb = _irb_frame_with_el(rwa=80_000_000.0, sa_rwa=100_000_000.0, excess=200_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        # Floor does not bind: 72.5% × 100m = 72.5m < 80m
        el = result.el_summary
        assert el is not None
        assert float(el.total_irb_rwa) == pytest.approx(80_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(480_000.0, rel=0.001)

    def test_crr_no_floor_t2_cap_uses_irb_rwa(self, aggregator: OutputAggregator) -> None:
        """Under CRR (no floor), T2 cap uses IRB RWA directly."""
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        irb = _irb_frame_with_el(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, crr_config)

        el = result.el_summary
        assert el is not None
        assert float(el.total_irb_rwa) == pytest.approx(50_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(300_000.0, rel=0.001)


class TestT2CapWithSlottingAndFloor:
    """T2 cap includes slotting RWA but excludes floor impact."""

    def test_slotting_rwa_included_in_t2_cap_pre_floor(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Slotting RWA feeds T2 cap denominator (Art. 153(5) is in IRB chapter)."""
        irb = pl.LazyFrame({
            "exposure_reference": ["IRB001"],
            "exposure_class": ["CORPORATE"],
            "approach_applied": ["FIRB"],
            "ead_final": [100_000_000.0],
            "risk_weight": [0.3],
            "rwa_post_factor": [30_000_000.0],
            "rwa_final": [30_000_000.0],
            "sa_rwa": [50_000_000.0],
            "expected_loss": [50_000.0],
            "provision_allocated": [150_000.0],
            "el_shortfall": [0.0],
            "el_excess": [100_000.0],
        })
        slotting = pl.LazyFrame({
            "exposure_reference": ["SL001"],
            "exposure_class": ["SPECIALISED_LENDING"],
            "approach_applied": ["SLOTTING"],
            "ead_final": [50_000_000.0],
            "risk_weight": [0.7],
            "rwa_post_factor": [35_000_000.0],
            "rwa_final": [35_000_000.0],
            "sa_rwa": [50_000_000.0],
            "slotting_el_rate": [0.004],
            "expected_loss": [200_000.0],
            "provision_allocated": [300_000.0],
            "el_shortfall": [0.0],
            "el_excess": [100_000.0],
        })
        result = aggregator.aggregate(EMPTY, irb, slotting, None, b31_config)

        # Floor may or may not bind — doesn't matter for this test
        el = result.el_summary
        assert el is not None
        # Pre-floor IRB + slotting RWA = 30m + 35m = 65m
        assert float(el.total_irb_rwa) == pytest.approx(65_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(65_000_000.0 * 0.006, rel=0.001)


class TestT2CapCapitalImpact:
    """Demonstrate the capital impact of using correct vs incorrect T2 cap basis."""

    def test_capital_overstatement_if_post_floor_rwa_were_used(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Quantify the T2 capital overstatement from using post-floor RWA.

        This is a documentation/demonstration test, not a regression guard.
        It shows why the correct (pre-floor) basis matters.
        """
        irb = _irb_frame_with_el(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        el = result.el_summary
        assert el is not None

        # Correct: pre-floor cap = 50m × 0.006 = 300k
        correct_cap = 50_000_000.0 * T2_CREDIT_CAP_RATE
        assert float(el.t2_credit_cap) == pytest.approx(correct_cap, rel=0.001)

        # Wrong: post-floor cap would be 72.5m × 0.006 = 435k
        wrong_cap = 72_500_000.0 * T2_CREDIT_CAP_RATE
        overstatement = wrong_cap - correct_cap
        assert overstatement == pytest.approx(135_000.0, rel=0.001)
        # 45% overstatement in T2 credit cap
        assert overstatement / correct_cap == pytest.approx(0.45, rel=0.01)

    def test_multiple_irb_exposures_with_binding_floor(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Multi-exposure portfolio: floor binds, T2 cap uses sum of pre-floor IRB RWAs."""
        irb = pl.LazyFrame({
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "exposure_class": ["CORPORATE", "CORPORATE", "INSTITUTION"],
            "approach_applied": ["FIRB", "AIRB", "FIRB"],
            "ead_final": [80_000_000.0, 60_000_000.0, 60_000_000.0],
            "risk_weight": [0.25, 0.20, 0.30],
            "rwa_post_factor": [20_000_000.0, 12_000_000.0, 18_000_000.0],
            "rwa_final": [20_000_000.0, 12_000_000.0, 18_000_000.0],
            "sa_rwa": [80_000_000.0, 45_000_000.0, 60_000_000.0],
            "expected_loss": [40_000.0, 30_000.0, 30_000.0],
            "provision_allocated": [80_000.0, 60_000.0, 60_000.0],
            "el_shortfall": [0.0, 0.0, 0.0],
            "el_excess": [40_000.0, 30_000.0, 30_000.0],
        })
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)

        # Pre-floor IRB RWA = 20m + 12m + 18m = 50m
        # SA RWA = 80m + 45m + 60m = 185m
        # Floor: 72.5% × 185m = 134.125m >> 50m → floor binds hard
        assert result.output_floor_summary is not None
        assert result.output_floor_summary.portfolio_floor_binding is True

        el = result.el_summary
        assert el is not None
        # T2 cap uses pre-floor 50m, not floored 134.125m
        assert float(el.total_irb_rwa) == pytest.approx(50_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(300_000.0, rel=0.001)


class TestT2CapDirectFunction:
    """Test compute_el_portfolio_summary directly for T2 cap correctness."""

    def test_direct_call_uses_input_frame_rwa(self) -> None:
        """compute_el_portfolio_summary uses RWA from the frames it receives."""
        irb = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "approach_applied": ["FIRB"],
            "rwa_post_factor": [50_000_000.0],
            "expected_loss": [100_000.0],
            "provision_allocated": [200_000.0],
            "el_shortfall": [0.0],
            "el_excess": [100_000.0],
        })

        el = compute_el_portfolio_summary(irb)
        assert el is not None
        assert float(el.total_irb_rwa) == pytest.approx(50_000_000.0, rel=0.001)
        assert float(el.t2_credit_cap) == pytest.approx(300_000.0, rel=0.001)

    def test_rate_constant_is_0_006(self) -> None:
        """T2_CREDIT_CAP_RATE must be 0.6% = 0.006 per Art. 62(d)."""
        assert T2_CREDIT_CAP_RATE == pytest.approx(0.006)
