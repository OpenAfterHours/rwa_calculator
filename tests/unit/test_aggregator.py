"""
Unit tests for OutputAggregator.

Tests cover:
- Output floor application (Basel 3.1)
- Supporting factor impact tracking (CRR)
- Summary generation by class and approach
- Pre/post-CRM reporting
- Portfolio-level EL summary with T2 credit cap
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

# =============================================================================
# Fixtures
# =============================================================================

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def aggregator() -> OutputAggregator:
    """OutputAggregator instance."""
    return OutputAggregator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (supporting factors enabled, floor disabled)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration (floor enabled, supporting factors disabled)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))


@pytest.fixture
def sa_results() -> pl.LazyFrame:
    """Sample SA results with approach_applied and rwa_final already set."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "counterparty_reference": ["CP001", "CP002", "CP003"],
            "exposure_class": ["CORPORATE", "RETAIL", "CENTRAL_GOVT_CENTRAL_BANK"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [1000000.0, 500000.0, 2000000.0],
            "risk_weight": [1.0, 0.75, 0.0],
            "rwa_pre_factor": [1000000.0, 375000.0, 0.0],
            "supporting_factor": [0.7619, 1.0, 1.0],
            "rwa_post_factor": [761900.0, 375000.0, 0.0],
            "rwa_final": [761900.0, 375000.0, 0.0],
            "supporting_factor_applied": [True, False, False],
            "is_sme": [True, False, False],
            "is_infrastructure": [False, False, False],
        }
    )


@pytest.fixture
def irb_results() -> pl.LazyFrame:
    """Sample IRB results with approach_applied and rwa_final already set."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP004", "EXP005"],
            "counterparty_reference": ["CP004", "CP005"],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "approach": ["FIRB", "AIRB"],
            "approach_applied": ["FIRB", "AIRB"],
            "ead_final": [5000000.0, 3000000.0],
            "pd_floored": [0.01, 0.005],
            "lgd_floored": [0.45, 0.35],
            "correlation": [0.18, 0.15],
            "k": [0.08, 0.05],
            "maturity_adjustment": [1.1, 1.05],
            "risk_weight": [0.88, 0.525],
            "rwa": [4400000.0, 1575000.0],
            "rwa_final": [4400000.0, 1575000.0],
            "expected_loss": [225000.0, 52500.0],
        }
    )


# =============================================================================
# Output Floor Tests (Basel 3.1)
# =============================================================================


class TestOutputFloor:
    """Tests for output floor via OutputAggregator.aggregate."""

    def test_floor_binding_when_irb_below_floor(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should bind when IRB RWA < 72.5% SA RWA."""
        # IRB RWA = 50m, SA RWA = 100m, Floor = 72.5m
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100000000.0],
                "risk_weight": [0.5],
                "rwa_final": [50000000.0],
                "sa_rwa": [100000000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=basel31_config,
        )

        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")

        # Final RWA should be floor (72.5m), not IRB (50m)
        assert irb_row["rwa_final"][0] == pytest.approx(72500000.0, rel=0.01)

        # Floor impact should show binding
        assert result.floor_impact is not None
        impact = result.floor_impact.collect()
        assert impact["is_floor_binding"][0] is True

    def test_floor_not_binding_when_irb_above_floor(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should not bind when IRB RWA > 72.5% SA RWA."""
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100000000.0],
                "risk_weight": [0.8],
                "rwa_final": [80000000.0],
                "sa_rwa": [100000000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=basel31_config,
        )

        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")

        # Final RWA should be IRB (80m), not floor (72.5m)
        assert irb_row["rwa_final"][0] == pytest.approx(80000000.0, rel=0.01)

        # Floor impact should show not binding
        assert result.floor_impact is not None
        impact = result.floor_impact.collect()
        assert impact["is_floor_binding"][0] is False

    def test_floor_only_applies_to_irb(
        self,
        aggregator: OutputAggregator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Floor should only apply to IRB exposures, not SA."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_SA"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [1000000.0],
                "risk_weight": [1.0],
                "rwa_final": [1000000.0],
                "sa_rwa": [1000000.0],
            }
        )
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_IRB"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100000000.0],
                "risk_weight": [0.5],
                "rwa_final": [50000000.0],
                "sa_rwa": [100000000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=basel31_config,
        )
        df = result.results.collect()

        sa_rows = df.filter(pl.col("approach_applied") == "SA")
        if "is_floor_binding" in sa_rows.columns:
            assert all(not v for v in sa_rows["is_floor_binding"].to_list() if v is not None)


# =============================================================================
# Output Floor Transitional Phase-In Tests (M2.6)
# =============================================================================


class TestOutputFloorTransitionalPhaseIn:
    """Parametrized tests sweeping the full PRA PS1/26 transitional schedule.

    The output floor phases in over 6 years:
        2027: 50%  |  2028: 55%  |  2029: 60%
        2030: 65%  |  2031: 70%  |  2032+: 72.5%
    """

    @pytest.fixture
    def aggregator(self) -> OutputAggregator:
        return OutputAggregator()

    @pytest.fixture
    def _floor_data(self) -> pl.LazyFrame:
        """Standard IRB=50m (combined), SA=100m floor test data."""
        return pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["FIRB"],
                "ead_final": [100_000_000.0],
                "risk_weight": [0.5],
                "rwa_final": [50_000_000.0],
                "sa_rwa": [100_000_000.0],
            }
        )

    def _run_floor_test(
        self,
        aggregator: OutputAggregator,
        irb_data: pl.LazyFrame,
        reporting_date: date,
    ) -> tuple:
        """Run aggregation with floor and return (rwa_final, floor_impact)."""
        config = CalculationConfig.basel_3_1(reporting_date=reporting_date)
        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_data,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )
        df = result.results.collect()
        irb_row = df.filter(pl.col("approach_applied") == "FIRB")
        rwa_final = irb_row["rwa_final"][0] if len(irb_row) > 0 else None
        return rwa_final, result.floor_impact

    @pytest.mark.parametrize(
        ("year", "floor_pct", "expected_rwa"),
        [
            (2027, 0.50, 50_000_000.0),
            (2028, 0.55, 55_000_000.0),
            (2029, 0.60, 60_000_000.0),
            (2030, 0.65, 65_000_000.0),
            (2031, 0.70, 70_000_000.0),
            (2032, 0.725, 72_500_000.0),
        ],
        ids=[
            "2027-50pct",
            "2028-55pct",
            "2029-60pct",
            "2030-65pct",
            "2031-70pct",
            "2032-72.5pct-fully-phased",
        ],
    )
    def test_transitional_year(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
        year: int,
        floor_pct: float,
        expected_rwa: float,
    ) -> None:
        """Each transitional year applies the correct floor percentage."""
        reporting_date = date(year, 6, 15)
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, reporting_date)

        assert rwa_final == pytest.approx(expected_rwa, rel=0.001), (
            f"Year {year}: expected floor RWA {expected_rwa:,.0f} "
            f"({floor_pct:.1%} x 100m), got {rwa_final:,.0f}"
        )

    def test_pre_2027_no_floor_applies(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Before the transitional period, no floor should apply."""
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, date(2026, 12, 31))

        assert rwa_final == pytest.approx(50_000_000.0, rel=0.001)

    def test_exactly_on_transition_date(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Exactly on 1 Jan 2028 should use the 2028 floor (55%)."""
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, date(2028, 1, 1))

        assert rwa_final == pytest.approx(55_000_000.0, rel=0.001)

    def test_far_future_fully_phased(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Well after 2032, the floor should remain at 72.5% permanently."""
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, date(2040, 1, 1))

        assert rwa_final == pytest.approx(72_500_000.0, rel=0.001)

    def test_2027_floor_equals_irb_not_binding(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """In 2027 at 50%, floor_rwa (50m) equals IRB_rwa (50m) - not binding."""
        _, floor_impact = self._run_floor_test(aggregator, _floor_data, date(2027, 6, 1))

        assert floor_impact is not None
        impact = floor_impact.collect()
        assert impact["is_floor_binding"][0] is False

    def test_floor_impact_rwa_calculation(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Floor impact RWA should equal max(0, floor_rwa - irb_rwa).

        At 2030 (65%): floor_rwa = 65m, irb_rwa = 50m -> impact = 15m.
        """
        _, floor_impact = self._run_floor_test(aggregator, _floor_data, date(2030, 6, 1))

        assert floor_impact is not None
        impact = floor_impact.collect()
        assert impact["is_floor_binding"][0] is True
        assert impact["floor_impact_rwa"][0] == pytest.approx(15_000_000.0, rel=0.001)


# =============================================================================
# Supporting Factor Impact Tests (CRR)
# =============================================================================


class TestSupportingFactorImpact:
    """Tests for supporting factor impact via OutputAggregator."""

    def test_supporting_factor_impact_generated(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate supporting factor impact for SA results."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.supporting_factor_impact is not None
        df = result.supporting_factor_impact.collect()

        # Should only include rows where supporting factor was applied
        assert len(df) == 1
        assert df["is_sme"][0] is True
        assert df["supporting_factor"][0] == pytest.approx(0.7619, rel=0.01)


# =============================================================================
# Summary Generation Tests
# =============================================================================


class TestSummaryGeneration:
    """Tests for summary generation via OutputAggregator."""

    def test_summary_by_class_generated(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate summary by exposure class."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_class.collect()
        classes = summary["exposure_class"].to_list()
        assert "CORPORATE" in classes
        assert "RETAIL" in classes
        assert "CENTRAL_GOVT_CENTRAL_BANK" in classes

    def test_summary_by_approach_generated(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should generate summary by approach."""
        slotting_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP006"],
                "counterparty_reference": ["CP006"],
                "exposure_class": ["SPECIALISED_LENDING"],
                "approach_applied": ["SLOTTING"],
                "ead_final": [10000000.0],
                "risk_weight": [0.7],
                "rwa_final": [7000000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_approach.collect()
        approaches = summary["approach_applied"].to_list()
        assert "SA" in approaches
        assert any(a in approaches for a in ["FIRB", "AIRB"])
        assert "SLOTTING" in approaches

    def test_summary_totals_correct(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Summary totals should be correct."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_approach.collect()
        sa_row = summary.filter(pl.col("approach_applied") == "SA")

        # Total EAD = 1000000 + 500000 + 2000000 = 3500000
        assert sa_row["total_ead"][0] == pytest.approx(3500000.0, rel=0.01)
        assert sa_row["exposure_count"][0] == 3


class TestSummaryPostCRMBasis:
    """Tests verifying summaries are based on post-CRM split rows."""

    def test_summary_by_class_splits_guaranteed_exposure(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Partially guaranteed exposure should split EAD across classes in summary.

        FIRB corporate exposure (EAD=1M) 60% guaranteed by retail guarantor:
        - 400k unguaranteed -> CORPORATE
        - 600k guaranteed -> RETAIL (guarantor's class)
        """
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["FIRB"],
                "approach_applied": ["FIRB"],
                "ead_final": [1000000.0],
                "risk_weight": [0.5],
                "rwa": [500000.0],
                "rwa_final": [500000.0],
                "guarantor_approach": ["sa"],
                "guarantee_ratio": [0.6],
                "is_guaranteed": [True],
                "guaranteed_portion": [600000.0],
                "unguaranteed_portion": [400000.0],
                "counterparty_reference": ["BORROWER01"],
                "guarantor_reference": ["GUARANTOR01"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_exposure_class_guaranteed": ["RETAIL"],
                "pre_crm_risk_weight": [0.5],
                "guarantor_rw": [0.75],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_class.collect()
        classes = summary["exposure_class"].to_list()

        assert "CORPORATE" in classes
        assert "RETAIL" in classes

        corp_row = summary.filter(pl.col("exposure_class") == "CORPORATE")
        retail_row = summary.filter(pl.col("exposure_class") == "RETAIL")

        assert corp_row["total_ead"][0] == pytest.approx(400000.0, rel=0.01)
        assert retail_row["total_ead"][0] == pytest.approx(600000.0, rel=0.01)

    def test_summary_by_approach_splits_guaranteed_exposure(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Partially guaranteed IRB exposure with SA guarantor:
        unguaranteed portion -> FIRB, guaranteed portion -> standardised.
        """
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["FIRB"],
                "approach_applied": ["FIRB"],
                "ead_final": [1000000.0],
                "risk_weight": [0.5],
                "rwa": [500000.0],
                "rwa_final": [500000.0],
                "guarantor_approach": ["sa"],
                "guarantee_ratio": [0.6],
                "is_guaranteed": [True],
                "guaranteed_portion": [600000.0],
                "unguaranteed_portion": [400000.0],
                "counterparty_reference": ["BORROWER01"],
                "guarantor_reference": ["GUARANTOR01"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_exposure_class_guaranteed": ["RETAIL"],
                "pre_crm_risk_weight": [0.5],
                "guarantor_rw": [0.75],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_approach.collect()
        approaches = summary["approach_applied"].to_list()

        assert "FIRB" in approaches
        assert "standardised" in approaches

        firb_row = summary.filter(pl.col("approach_applied") == "FIRB")
        sa_row = summary.filter(pl.col("approach_applied") == "standardised")

        assert firb_row["total_ead"][0] == pytest.approx(400000.0, rel=0.01)
        assert sa_row["total_ead"][0] == pytest.approx(600000.0, rel=0.01)

    def test_summary_non_guaranteed_unchanged(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-guaranteed exposures should produce identical summaries."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary = result.summary_by_approach.collect()
        sa_row = summary.filter(pl.col("approach_applied") == "SA")

        assert sa_row["total_ead"][0] == pytest.approx(3500000.0, rel=0.01)
        assert sa_row["exposure_count"][0] == 3


# =============================================================================
# Post-CRM Detailed Reporting Tests
# =============================================================================


class TestPostCRMDetailedReportingApproach:
    """Tests for reporting_approach in post-CRM detailed view."""

    def test_reporting_approach_in_detailed_view(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Post-CRM detailed view should include reporting_approach column."""
        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["CORPORATE"],
                "approach": ["FIRB"],
                "approach_applied": ["FIRB"],
                "ead_final": [1000000.0],
                "risk_weight": [0.5],
                "rwa": [500000.0],
                "rwa_final": [500000.0],
                "guarantor_approach": ["sa"],
                "guarantee_ratio": [0.6],
                "is_guaranteed": [True],
                "guaranteed_portion": [600000.0],
                "unguaranteed_portion": [400000.0],
                "counterparty_reference": ["BORROWER01"],
                "guarantor_reference": ["GUARANTOR01"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_exposure_class_guaranteed": ["RETAIL"],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        df = result.post_crm_detailed.collect()
        assert "reporting_approach" in df.columns

        unguar = df.filter(pl.col("crm_portion_type") == "unguaranteed")
        assert unguar["reporting_approach"][0] == "FIRB"

        guar = df.filter(pl.col("crm_portion_type") == "guaranteed")
        assert guar["reporting_approach"][0] == "standardised"


# =============================================================================
# EL Portfolio Summary with T2 Credit Cap Tests
# =============================================================================


class TestELPortfolioSummary:
    """Tests for EL portfolio summary via OutputAggregator (CRR Art. 62(d), Art. 158-159)."""

    def test_returns_none_when_no_irb_results(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should return None when IRB results have no EL columns."""
        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )
        assert result.el_summary is None

    def test_returns_none_when_no_el_columns(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should return None when IRB results lack el_shortfall/el_excess columns."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [1000000.0],
            }
        )
        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )
        assert result.el_summary is None

    def test_basic_shortfall_computation(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should compute shortfall totals and 50/50 CET1/T2 deduction split."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["FIRB", "AIRB"],
                "rwa_post_factor": [5000000.0, 3000000.0],
                "expected_loss": [50000.0, 30000.0],
                "provision_allocated": [30000.0, 10000.0],
                "el_shortfall": [20000.0, 20000.0],
                "el_excess": [0.0, 0.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.total_el_shortfall == pytest.approx(40000.0)
        assert el.total_el_excess == pytest.approx(0.0)
        assert el.cet1_deduction == pytest.approx(20000.0)
        assert el.t2_deduction == pytest.approx(20000.0)

    def test_basic_excess_computation(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should compute excess totals and T2 credit cap."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["FIRB", "AIRB"],
                "rwa_post_factor": [5000000.0, 3000000.0],
                "expected_loss": [20000.0, 10000.0],
                "provision_allocated": [50000.0, 30000.0],
                "el_shortfall": [0.0, 0.0],
                "el_excess": [30000.0, 20000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.total_el_excess == pytest.approx(50000.0)
        assert el.total_irb_rwa == pytest.approx(8000000.0)
        assert el.t2_credit_cap == pytest.approx(48000.0)
        assert el.t2_credit == pytest.approx(48000.0)

    def test_t2_credit_uncapped(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should not cap T2 credit when excess is below cap."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [10000000.0],
                "expected_loss": [10000.0],
                "provision_allocated": [30000.0],
                "el_shortfall": [0.0],
                "el_excess": [20000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.t2_credit_cap == pytest.approx(60000.0)
        assert el.t2_credit == pytest.approx(20000.0)

    def test_t2_credit_cap_rate(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """T2 credit cap should be exactly 0.6% of total IRB RWA per CRR Art. 62(d)."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [100000000.0],
                "el_shortfall": [0.0],
                "el_excess": [1000000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.t2_credit_cap == pytest.approx(600000.0)
        assert el.t2_credit == pytest.approx(600000.0)

    def test_mixed_shortfall_and_excess(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle portfolio with both shortfall and excess exposures."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002", "EXP003"],
                "approach_applied": ["FIRB", "AIRB", "FIRB"],
                "rwa_post_factor": [4000000.0, 3000000.0, 3000000.0],
                "expected_loss": [50000.0, 10000.0, 20000.0],
                "provision_allocated": [30000.0, 40000.0, 50000.0],
                "el_shortfall": [20000.0, 0.0, 0.0],
                "el_excess": [0.0, 30000.0, 30000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.total_expected_loss == pytest.approx(80000.0)
        assert el.total_provisions_allocated == pytest.approx(120000.0)
        assert el.total_el_shortfall == pytest.approx(20000.0)
        assert el.total_el_excess == pytest.approx(60000.0)
        assert el.total_irb_rwa == pytest.approx(10000000.0)
        assert el.t2_credit_cap == pytest.approx(60000.0)
        assert el.t2_credit == pytest.approx(60000.0)
        assert el.cet1_deduction == pytest.approx(10000.0)
        assert el.t2_deduction == pytest.approx(10000.0)

    def test_uses_rwa_final_fallback(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should fall back to rwa_final when rwa_post_factor is not available."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_final": [2000000.0],
                "el_shortfall": [0.0],
                "el_excess": [10000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert el.total_irb_rwa == pytest.approx(2000000.0)
        assert el.t2_credit_cap == pytest.approx(12000.0)
