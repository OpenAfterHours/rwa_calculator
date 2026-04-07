"""
Unit tests for portfolio-level output floor (Art. 92 para 2A).

Tests cover:
- Portfolio floor binding vs not binding
- Pro-rata shortfall distribution across multiple exposures
- Slotting exposures included in floor scope
- SA exposures excluded from floor
- Mixed portfolios (SA + IRB + slotting)
- Edge cases (zero sa_rwa, single exposure, empty portfolio)
- OutputFloorSummary correctness
- Comparison with old per-exposure approach

Why these tests matter:
The output floor is THE defining feature of Basel 3.1. It constrains IRB
capital benefits by requiring TREA >= x * S-TREA at portfolio level. The
prior per-exposure max(irb_rwa, floor_pct * sa_rwa) systematically overstated
capital for portfolios near but above the aggregate floor threshold.

References:
- PRA PS1/26 Art. 92 para 2A
- CRE99.1-8: Output floor (Basel 3.1)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Fully-phased Basel 3.1 config (72.5% floor)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))


# =============================================================================
# Portfolio-Level Floor Binding
# =============================================================================


class TestPortfolioLevelFloorBinding:
    """Portfolio-level floor: TREA = max(U-TREA, x * S-TREA)."""

    def test_portfolio_floor_binds_single_exposure(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Single IRB exposure where floor binds: rwa_final = floor_threshold."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()
        # Floor: 72.5% * 100k = 72.5k > IRB 50k → binds
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)

    def test_portfolio_floor_not_binding(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Single IRB exposure where floor does not bind."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.8],
                "rwa_final": [80_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()
        # Floor: 72.5% * 100k = 72.5k < IRB 80k → doesn't bind
        assert df["rwa_final"][0] == pytest.approx(80_000.0, rel=0.001)

    def test_portfolio_floor_binds_multiple_exposures(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Two IRB exposures, portfolio floor binds, shortfall distributed pro-rata.

        EXP1: IRB=30k, SA=100k   (individually would bind)
        EXP2: IRB=80k, SA=100k   (individually would NOT bind)

        Portfolio: U-TREA=110k, S-TREA=200k
        Floor threshold: 72.5% * 200k = 145k
        Shortfall: 145k - 110k = 35k
        Pro-rata by sa_rwa: EXP1 share=50%, EXP2 share=50%
        EXP1 add-on: 17.5k → rwa_final = 30k + 17.5k = 47.5k
        EXP2 add-on: 17.5k → rwa_final = 80k + 17.5k = 97.5k
        Total: 47.5k + 97.5k = 145k ✓
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1", "EXP2"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "AIRB"],
                "ead_final": [100_000.0, 100_000.0],
                "risk_weight": [0.3, 0.8],
                "rwa_final": [30_000.0, 80_000.0],
                "sa_rwa": [100_000.0, 100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect().sort("exposure_reference")

        assert df["rwa_final"][0] == pytest.approx(47_500.0, rel=0.001)  # EXP1
        assert df["rwa_final"][1] == pytest.approx(97_500.0, rel=0.001)  # EXP2

        # Verify total matches floor threshold
        total_rwa = df["rwa_final"].sum()
        assert total_rwa == pytest.approx(145_000.0, rel=0.001)

    def test_portfolio_floor_not_binding_mixed_exposures(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Two IRB exposures, one individually would bind but portfolio doesn't.

        EXP1: IRB=10k, SA=100k   (individually would bind: 72.5k > 10k)
        EXP2: IRB=200k, SA=100k  (individually wouldn't bind)

        Portfolio: U-TREA=210k, S-TREA=200k
        Floor threshold: 72.5% * 200k = 145k
        210k > 145k → floor does NOT bind at portfolio level

        Under old per-exposure approach, EXP1 would have been floored to 72.5k,
        total = 72.5k + 200k = 272.5k (overstated by 62.5k).
        Under portfolio approach, total = 210k (correct).
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1", "EXP2"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "AIRB"],
                "ead_final": [100_000.0, 100_000.0],
                "risk_weight": [0.1, 2.0],
                "rwa_final": [10_000.0, 200_000.0],
                "sa_rwa": [100_000.0, 100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect().sort("exposure_reference")

        # Portfolio floor doesn't bind — both keep original RWA
        assert df["rwa_final"][0] == pytest.approx(10_000.0, rel=0.001)  # EXP1
        assert df["rwa_final"][1] == pytest.approx(200_000.0, rel=0.001)  # EXP2
        total_rwa = df["rwa_final"].sum()
        assert total_rwa == pytest.approx(210_000.0, rel=0.001)


# =============================================================================
# Pro-Rata Distribution
# =============================================================================


class TestProRataDistribution:
    """Pro-rata shortfall distribution proportional to sa_rwa."""

    def test_unequal_sa_rwa_shares(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Shortfall distributed proportionally to sa_rwa, not equally.

        EXP1: sa_rwa=300k (75% share), IRB=20k
        EXP2: sa_rwa=100k (25% share), IRB=30k

        U-TREA=50k, S-TREA=400k
        Floor: 72.5% * 400k = 290k, shortfall = 240k
        EXP1 add-on: 240k * 0.75 = 180k → rwa_final = 200k
        EXP2 add-on: 240k * 0.25 = 60k → rwa_final = 90k
        Total: 290k ✓
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1", "EXP2"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "FIRB"],
                "ead_final": [300_000.0, 100_000.0],
                "risk_weight": [0.067, 0.3],
                "rwa_final": [20_000.0, 30_000.0],
                "sa_rwa": [300_000.0, 100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect().sort("exposure_reference")

        assert df["rwa_final"][0] == pytest.approx(200_000.0, rel=0.001)  # EXP1 (75%)
        assert df["rwa_final"][1] == pytest.approx(90_000.0, rel=0.001)  # EXP2 (25%)
        assert df["rwa_final"].sum() == pytest.approx(290_000.0, rel=0.001)

    def test_floor_impact_rwa_columns(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """floor_impact_rwa reflects the pro-rata add-on per exposure."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        impact = result.floor_impact.collect()

        # Shortfall = 72.5k - 50k = 22.5k, 100% to this exposure
        assert impact["floor_impact_rwa"][0] == pytest.approx(22_500.0, rel=0.001)
        assert impact["rwa_post_floor"][0] == pytest.approx(72_500.0, rel=0.001)
        assert impact["rwa_pre_floor"][0] == pytest.approx(50_000.0, rel=0.001)

    def test_floor_impact_zero_when_not_binding(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """floor_impact_rwa is 0 when portfolio floor doesn't bind."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.8],
                "rwa_final": [80_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        impact = result.floor_impact.collect()

        assert impact["floor_impact_rwa"][0] == pytest.approx(0.0, abs=0.01)
        assert impact["is_floor_binding"][0] is False


# =============================================================================
# Slotting Exposures in Floor Scope
# =============================================================================


class TestSlottingInFloorScope:
    """Slotting exposures are IRB-chapter (Art. 153(5)) and should be floor-eligible."""

    def test_slotting_included_in_portfolio_floor(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Slotting exposure participates in portfolio-level floor comparison."""
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SLOT1"],
                "exposure_class": ["SPECIALISED_LENDING"],
                "approach_applied": ["slotting"],
                "ead_final": [100_000.0],
                "risk_weight": [0.7],
                "rwa_final": [70_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, EMPTY, slotting, None, b31_config)
        df = result.results.collect()

        # Floor: 72.5% * 100k = 72.5k > slotting 70k → binds
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)

    def test_slotting_plus_irb_combined_floor(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """IRB + slotting combined for portfolio-level floor comparison.

        IRB: IRB_rwa=50k, sa_rwa=100k
        Slotting: slot_rwa=40k, sa_rwa=100k

        U-TREA=90k, S-TREA=200k, floor=145k, shortfall=55k
        IRB share=50%, slotting share=50%
        IRB rwa_final = 50k + 27.5k = 77.5k
        Slotting rwa_final = 40k + 27.5k = 67.5k
        Total = 145k ✓
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SLOT1"],
                "exposure_class": ["SPECIALISED_LENDING"],
                "approach_applied": ["slotting"],
                "ead_final": [100_000.0],
                "risk_weight": [0.4],
                "rwa_final": [40_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, slotting, None, b31_config)
        df = result.results.collect().sort("exposure_reference")

        assert df["rwa_final"][0] == pytest.approx(77_500.0, rel=0.001)  # IRB1
        assert df["rwa_final"][1] == pytest.approx(67_500.0, rel=0.001)  # SLOT1
        assert df["rwa_final"].sum() == pytest.approx(145_000.0, rel=0.001)

    def test_slotting_floor_impact_has_binding_flag(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Slotting exposures appear in floor_impact with is_floor_binding."""
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SLOT1"],
                "exposure_class": ["SPECIALISED_LENDING"],
                "approach_applied": ["slotting"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, EMPTY, slotting, None, b31_config)
        impact = result.floor_impact.collect()

        assert len(impact) == 1
        assert impact["approach_applied"][0] == "slotting"
        assert impact["is_floor_binding"][0] is True


# =============================================================================
# SA Exposures Excluded
# =============================================================================


class TestSAExcludedFromFloor:
    """SA exposures should be unaffected by the output floor."""

    def test_sa_rwa_unchanged_when_floor_binds(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """SA exposures retain original RWA even when portfolio floor binds."""
        sa = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [100_000.0],
                "risk_weight": [1.0],
                "rwa_final": [100_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.3],
                "rwa_final": [30_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(sa, irb, EMPTY, None, b31_config)
        df = result.results.collect().sort("exposure_reference")

        # IRB floor binds: 72.5k > 30k
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")
        assert irb_row["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)

        # SA unchanged
        sa_row = df.filter(pl.col("approach_applied") == "SA")
        assert sa_row["rwa_final"][0] == pytest.approx(100_000.0, rel=0.001)

    def test_sa_not_in_floor_impact(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """SA exposures should not appear in the floor_impact LazyFrame."""
        sa = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [100_000.0],
                "risk_weight": [1.0],
                "rwa_final": [100_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(sa, EMPTY, EMPTY, None, b31_config)
        impact = result.floor_impact.collect()
        assert len(impact) == 0


# =============================================================================
# OutputFloorSummary
# =============================================================================


class TestOutputFloorSummary:
    """Tests for the portfolio-level OutputFloorSummary dataclass."""

    def test_summary_when_floor_binds(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """OutputFloorSummary reports correct U-TREA, S-TREA, shortfall."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        summary = result.output_floor_summary

        assert summary is not None
        assert isinstance(summary, OutputFloorSummary)
        assert summary.u_trea == pytest.approx(50_000.0, rel=0.001)
        assert summary.s_trea == pytest.approx(100_000.0, rel=0.001)
        assert summary.floor_pct == pytest.approx(0.725, rel=0.001)
        assert summary.floor_threshold == pytest.approx(72_500.0, rel=0.001)
        assert summary.shortfall == pytest.approx(22_500.0, rel=0.001)
        assert summary.portfolio_floor_binding is True
        assert summary.total_rwa_post_floor == pytest.approx(72_500.0, rel=0.001)

    def test_summary_when_floor_not_binding(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """OutputFloorSummary shows zero shortfall when floor doesn't bind."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.8],
                "rwa_final": [80_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        summary = result.output_floor_summary

        assert summary is not None
        assert summary.u_trea == pytest.approx(80_000.0, rel=0.001)
        assert summary.s_trea == pytest.approx(100_000.0, rel=0.001)
        assert summary.shortfall == pytest.approx(0.0, abs=0.01)
        assert summary.portfolio_floor_binding is False
        assert summary.total_rwa_post_floor == pytest.approx(80_000.0, rel=0.001)

    def test_summary_excludes_sa_from_totals(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """U-TREA and S-TREA only include floor-eligible (IRB+slotting), not SA."""
        sa = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [500_000.0],
                "risk_weight": [1.0],
                "rwa_final": [500_000.0],
                "sa_rwa": [500_000.0],
            }
        )
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(sa, irb, EMPTY, None, b31_config)
        summary = result.output_floor_summary

        # U-TREA and S-TREA should only reflect the IRB exposure
        assert summary.u_trea == pytest.approx(50_000.0, rel=0.001)
        assert summary.s_trea == pytest.approx(100_000.0, rel=0.001)

    def test_summary_includes_slotting(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Slotting RWA is included in U-TREA and S-TREA."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SLOT1"],
                "exposure_class": ["SPECIALISED_LENDING"],
                "approach_applied": ["slotting"],
                "ead_final": [100_000.0],
                "risk_weight": [0.7],
                "rwa_final": [70_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, slotting, None, b31_config)
        summary = result.output_floor_summary

        assert summary.u_trea == pytest.approx(120_000.0, rel=0.001)  # 50k + 70k
        assert summary.s_trea == pytest.approx(200_000.0, rel=0.001)  # 100k + 100k

    def test_no_summary_when_floor_disabled(self, aggregator: OutputAggregator) -> None:
        """CRR config (floor disabled) → no OutputFloorSummary."""
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        result = aggregator.aggregate(EMPTY, EMPTY, EMPTY, None, crr_config)
        assert result.output_floor_summary is None


# =============================================================================
# Edge Cases
# =============================================================================


class TestPortfolioFloorEdgeCases:
    """Edge cases for portfolio-level floor."""

    def test_empty_portfolio(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Empty portfolio (no exposures) should produce default summary."""
        result = aggregator.aggregate(EMPTY, EMPTY, EMPTY, None, b31_config)
        summary = result.output_floor_summary

        assert summary is not None
        assert summary.u_trea == pytest.approx(0.0, abs=0.01)
        assert summary.s_trea == pytest.approx(0.0, abs=0.01)
        assert summary.shortfall == pytest.approx(0.0, abs=0.01)
        assert summary.portfolio_floor_binding is False

    def test_zero_sa_rwa_no_division_error(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Zero sa_rwa should not cause division by zero."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [0.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()

        # Floor: 72.5% * 0 = 0 < IRB 50k → doesn't bind
        assert df["rwa_final"][0] == pytest.approx(50_000.0, rel=0.001)
        summary = result.output_floor_summary
        assert summary.portfolio_floor_binding is False

    def test_null_sa_rwa_treated_as_zero(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Null sa_rwa (missing column data) treated as 0 → no floor impact."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [None],
            }
        ).cast({"sa_rwa": pl.Float64})
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()

        assert df["rwa_final"][0] == pytest.approx(50_000.0, rel=0.001)

    def test_portfolio_vs_per_exposure_difference(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """Demonstrate portfolio-level floor < per-exposure floor for mixed portfolio.

        This is the key correctness test. Under per-exposure max, EXP1 would be
        individually floored. Under portfolio-level, the surplus from EXP2 offsets
        the deficit from EXP1, so no floor add-on is needed.

        EXP1: IRB=10k, SA=100k → per-exposure floor: max(10k, 72.5k) = 72.5k
        EXP2: IRB=200k, SA=100k → per-exposure floor: max(200k, 72.5k) = 200k
        Per-exposure total: 72.5k + 200k = 272.5k

        Portfolio: U-TREA=210k, S-TREA=200k, threshold=145k → no shortfall
        Portfolio total: 210k (correct, lower than per-exposure 272.5k by 62.5k)
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1", "EXP2"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "FIRB"],
                "ead_final": [100_000.0, 100_000.0],
                "risk_weight": [0.1, 2.0],
                "rwa_final": [10_000.0, 200_000.0],
                "sa_rwa": [100_000.0, 100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()
        total = df["rwa_final"].sum()

        # Portfolio-level: 210k (no floor add-on)
        assert total == pytest.approx(210_000.0, rel=0.001)

        # This would have been 272.5k under the old per-exposure max approach —
        # 62.5k of unnecessary capital overstatement eliminated.

    def test_all_sa_portfolio_no_floor(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """All-SA portfolio should have no floor impact."""
        sa = pl.LazyFrame(
            {
                "exposure_reference": ["SA1", "SA2"],
                "exposure_class": ["CORPORATE", "RETAIL"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [100_000.0, 50_000.0],
                "risk_weight": [1.0, 0.75],
                "rwa_final": [100_000.0, 37_500.0],
                "sa_rwa": [100_000.0, 37_500.0],
            }
        )
        result = aggregator.aggregate(sa, EMPTY, EMPTY, None, b31_config)
        summary = result.output_floor_summary

        assert summary.u_trea == pytest.approx(0.0, abs=0.01)
        assert summary.s_trea == pytest.approx(0.0, abs=0.01)
        assert summary.portfolio_floor_binding is False

    def test_floor_rwa_column_still_per_exposure(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """floor_rwa column still shows per-exposure SA * floor_pct for COREP."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000.0],
                "sa_rwa": [100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        df = result.results.collect()

        # floor_rwa = sa_rwa * floor_pct (per-exposure benchmark)
        assert df["floor_rwa"][0] == pytest.approx(72_500.0, rel=0.001)

    def test_is_floor_binding_same_for_all_eligible(
        self, aggregator: OutputAggregator, b31_config: CalculationConfig
    ) -> None:
        """is_floor_binding is a portfolio-level flag — same for all eligible rows."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP1", "EXP2"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "AIRB"],
                "ead_final": [100_000.0, 100_000.0],
                "risk_weight": [0.3, 0.3],
                "rwa_final": [30_000.0, 30_000.0],
                "sa_rwa": [100_000.0, 100_000.0],
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, b31_config)
        impact = result.floor_impact.collect()

        # Both should be True (portfolio floor binds)
        assert all(impact["is_floor_binding"].to_list())
