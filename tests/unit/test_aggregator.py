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
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.aggregator.aggregator import _detect_non_finite_errors
from tests.fixtures.contract_columns import (
    pad_irb_branch,
    pad_sa_branch,
    pad_slotting_branch,
)

# =============================================================================
# Fixtures
# =============================================================================

# Padded zero-row branch frames mirroring the orchestrator's sealed branch
# collect — empty branches still carry the full edge schema in production.
EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SA = pad_sa_branch(EMPTY)
EMPTY_IRB = pad_irb_branch(EMPTY)
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)


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
    return pad_sa_branch(
        pl.LazyFrame(
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
    )


@pytest.fixture
def irb_results() -> pl.LazyFrame:
    """Sample IRB results with approach_applied and rwa_final already set."""
    return pad_irb_branch(
        pl.LazyFrame(
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
    )


@pytest.fixture
def partially_guaranteed_irb_results() -> pl.LazyFrame:
    """FIRB corporate exposure (EAD=1M) 60% guaranteed by an SA retail guarantor.

    Splits into 400k unguaranteed -> CORPORATE/FIRB and 600k guaranteed ->
    RETAIL/standardised (the guarantor's class/approach).
    """
    return pad_irb_branch(
        pl.LazyFrame(
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
        irb_results = pad_irb_branch(
            pl.LazyFrame(
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
        )

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
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
        irb_results = pad_irb_branch(
            pl.LazyFrame(
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
        )

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
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
        sa_results = pad_sa_branch(
            pl.LazyFrame(
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
        )
        irb_results = pad_irb_branch(
            pl.LazyFrame(
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
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
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

    The output floor phases in over 4 years:
        2027: 60%  |  2028: 65%  |  2029: 70%  |  2030+: 72.5%
    """

    @pytest.fixture
    def aggregator(self) -> OutputAggregator:
        return OutputAggregator()

    @pytest.fixture
    def _floor_data(self) -> pl.LazyFrame:
        """Standard IRB=50m (combined), SA=100m floor test data."""
        return pad_irb_branch(
            pl.LazyFrame(
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
            sa_results=EMPTY_SA,
            irb_results=irb_data,
            slotting_results=EMPTY_SLOTTING,
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
            (2027, 0.60, 60_000_000.0),
            (2028, 0.65, 65_000_000.0),
            (2029, 0.70, 70_000_000.0),
            (2030, 0.725, 72_500_000.0),
        ],
        ids=[
            "2027-60pct",
            "2028-65pct",
            "2029-70pct",
            "2030-72.5pct-fully-phased",
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
        """Exactly on 1 Jan 2028 should use the 2028 floor (65%)."""
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, date(2028, 1, 1))

        assert rwa_final == pytest.approx(65_000_000.0, rel=0.001)

    def test_far_future_fully_phased(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Well after 2030, the floor should remain at 72.5% permanently."""
        rwa_final, _ = self._run_floor_test(aggregator, _floor_data, date(2040, 1, 1))

        assert rwa_final == pytest.approx(72_500_000.0, rel=0.001)

    def test_2027_floor_exceeds_irb_binding(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """In 2027 at 60%, floor_rwa (60m) exceeds IRB_rwa (50m) - binding."""
        _, floor_impact = self._run_floor_test(aggregator, _floor_data, date(2027, 6, 1))

        assert floor_impact is not None
        impact = floor_impact.collect()
        assert impact["is_floor_binding"][0] is True

    def test_floor_impact_rwa_calculation(
        self,
        aggregator: OutputAggregator,
        _floor_data: pl.LazyFrame,
    ) -> None:
        """Floor impact RWA should equal max(0, floor_rwa - irb_rwa).

        At 2030 (72.5%): floor_rwa = 72.5m, irb_rwa = 50m -> impact = 22.5m.
        """
        _, floor_impact = self._run_floor_test(aggregator, _floor_data, date(2030, 6, 1))

        assert floor_impact is not None
        impact = floor_impact.collect()
        assert impact["is_floor_binding"][0] is True
        assert impact["floor_impact_rwa"][0] == pytest.approx(22_500_000.0, rel=0.001)


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
            irb_results=EMPTY_IRB,
            slotting_results=EMPTY_SLOTTING,
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
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class is not None
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
        slotting_results = pad_slotting_branch(
            pl.LazyFrame(
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
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_approach is not None
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
            irb_results=EMPTY_IRB,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_approach is not None
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
        partially_guaranteed_irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Partially guaranteed exposure should split EAD across classes in summary.

        FIRB corporate exposure (EAD=1M) 60% guaranteed by retail guarantor:
        - 400k unguaranteed -> CORPORATE
        - 600k guaranteed -> RETAIL (guarantor's class)
        """
        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=partially_guaranteed_irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class is not None
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
        partially_guaranteed_irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Partially guaranteed IRB exposure with SA guarantor:
        unguaranteed portion -> FIRB, guaranteed portion -> standardised.
        """
        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=partially_guaranteed_irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_approach is not None
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
            irb_results=EMPTY_IRB,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_approach is not None
        summary = result.summary_by_approach.collect()
        sa_row = summary.filter(pl.col("approach_applied") == "SA")

        assert sa_row["total_ead"][0] == pytest.approx(3500000.0, rel=0.01)
        assert sa_row["exposure_count"][0] == 3


class TestNonFiniteOutputDetection:
    """A NaN/inf in a final output column is surfaced as an AGG001 error.

    Polars float ``.sum()`` propagates NaN (not skipped like null), so one
    poisoned row blanks the portfolio totals and charts. The aggregator records
    a non-critical AGG001 error so the gap is visible rather than silent, while
    the run stays successful and the clean rows still report.
    """

    def test_nan_rwa_final_surfaced_as_agg001(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """A NaN rwa_final row produces an AGG001 error naming the exposure."""
        irb_results = pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["GOOD01", "NAN01"],
                    "exposure_class": ["CORPORATE", "CORPORATE"],
                    "approach_applied": ["advanced_irb", "advanced_irb"],
                    "ead_final": [1_000_000.0, 2_000_000.0],
                    "risk_weight": [1.0, 1.0],
                    "rwa_final": [1_000_000.0, float("nan")],
                }
            )
        )

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        agg001 = [e for e in result.errors if e.code == "AGG001"]
        assert agg001, "expected an AGG001 error for the NaN rwa_final row"
        assert any(e.field_name == "rwa_final" for e in agg001)
        assert any("NAN01" in (e.message or "") for e in agg001)

    def test_clean_results_emit_no_agg001(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """A clean portfolio produces no AGG001 error."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert not [e for e in result.errors if e.code == "AGG001"]
        assert not [e for e in result.errors if e.code == "AGG002"]

    def test_nan_pd_input_emits_agg002_warning(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """A non-finite raw PD/LGD input is surfaced as a non-blocking AGG002 warning."""
        irb_results = pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["BADPD"],
                    "exposure_class": ["CORPORATE"],
                    "approach_applied": ["advanced_irb"],
                    "pd": [float("nan")],
                    "lgd": [0.45],
                    "ead_final": [1_000_000.0],
                    "risk_weight": [0.8],
                    "rwa_final": [800_000.0],
                }
            )
        )

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        agg002 = [e for e in result.errors if e.code == "AGG002"]
        assert agg002, "expected an AGG002 warning for the NaN pd input"
        assert all(e.severity.value == "warning" for e in agg002)
        assert any(e.field_name == "pd" and "BADPD" in (e.message or "") for e in agg002)

    def test_reporting_column_nan_deduped_against_output_scan(self) -> None:
        """A reporting-column scan reports only exposures the output scan missed.

        A NaN ``risk_weight`` row also makes its ``reporting_rw`` NaN — that must be
        reported once (under the output column), while a reporting-only NaN (an
        exposure finite in the output frame) is uniquely caught.
        """
        results = pl.DataFrame(
            {
                "exposure_reference": ["A", "B"],
                "rwa_final": [1.0, 2.0],
                "ead_final": [10.0, 20.0],
                "risk_weight": [float("nan"), 0.5],  # A: NaN output
            }
        )
        reporting = pl.DataFrame(
            {
                "exposure_reference": ["A", "A", "C"],  # A split; C reporting-only NaN
                "reporting_rw": [float("nan"), 0.3, float("nan")],
                "reporting_ead": [5.0, 5.0, 7.0],
            }
        )

        errors = _detect_non_finite_errors(results, reporting)

        rw_out = [e for e in errors if e.field_name == "risk_weight"]
        rw_rep = [e for e in errors if e.field_name == "reporting_rw"]
        assert len(rw_out) == 1 and "A" in (rw_out[0].message or "")
        # reporting_rw error names only C (A already flagged by the output scan).
        assert len(rw_rep) == 1
        assert rw_rep[0].actual_value == "1"
        assert "C" in (rw_rep[0].message or "")


class TestSummaryByClassMethod:
    """The (exposure_class, method) summary splits RWA by methodology family.

    Methodology = STD (standardised) / FIRB / AIRB (advanced IRB, retail folded
    in) / SLOTTING / EQUITY. Summing total_rwa over methods within a class must
    reconcile exactly with the by-class summary.
    """

    def test_shape_and_method_labels(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """The frame carries class x method rows with the expected labels."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class_method is not None
        cm = result.summary_by_class_method.collect()
        assert {"exposure_class", "method", "total_ead", "total_rwa", "exposure_count"} <= set(
            cm.columns
        )
        methods = set(cm.get_column("method").to_list())
        assert "STD" in methods  # SA rows
        assert "FIRB" in methods  # foundation_irb / FIRB rows
        assert "AIRB" in methods  # advanced_irb / AIRB rows
        assert "RIRB" not in methods  # retail A-IRB folds into AIRB

    def test_reconciles_with_summary_by_class(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Per-class total_rwa summed over methods equals the by-class total."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class is not None
        assert result.summary_by_class_method is not None
        by_class = result.summary_by_class.collect().select(["exposure_class", "total_rwa"])
        rolled = (
            result.summary_by_class_method.collect()
            .group_by("exposure_class")
            .agg(pl.col("total_rwa").sum().alias("rwa_cm"))
        )
        joined = by_class.join(rolled, on="exposure_class")
        max_diff = joined.select((pl.col("total_rwa") - pl.col("rwa_cm")).abs().max()).item()
        assert max_diff == pytest.approx(0.0, abs=1e-6)

    def test_retail_advanced_irb_labelled_airb(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """A retail advanced-IRB exposure is labelled AIRB (RIRB folded in)."""
        irb_results = pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["R1"],
                    "exposure_class": ["RETAIL_MORTGAGE"],
                    "approach_applied": ["advanced_irb"],
                    "ead_final": [800_000.0],
                    "risk_weight": [0.2],
                    "rwa_final": [160_000.0],
                }
            )
        )

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.summary_by_class_method is not None
        cm = result.summary_by_class_method.collect()
        row = cm.filter(pl.col("exposure_class") == "RETAIL_MORTGAGE")
        assert row["method"].to_list() == ["AIRB"]


# =============================================================================
# Post-CRM Detailed Reporting Tests
# =============================================================================


class TestPostCRMDetailedReportingApproach:
    """Tests for reporting_approach in post-CRM detailed view."""

    def test_reporting_approach_in_detailed_view(
        self,
        aggregator: OutputAggregator,
        partially_guaranteed_irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Post-CRM detailed view should include reporting_approach column."""
        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=partially_guaranteed_irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        assert result.post_crm_detailed is not None
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

    def test_returns_none_when_no_irb_results(self) -> None:
        """Should return None when IRB results have no EL columns.

        Phase 3: sealed branch inputs always carry the EL columns, so the
        column-absence ramp is only reachable through the helper directly
        (aggregate() with sealed empties yields a zero-valued summary).
        """
        el = compute_el_portfolio_summary(EMPTY, EMPTY)
        assert el is None

    def test_returns_none_when_no_el_columns(self) -> None:
        """Should return None when IRB results lack el_shortfall/el_excess columns.

        Phase 3: sealed branch inputs always carry the EL columns, so the
        column-absence ramp is only reachable through the helper directly.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [1000000.0],
            }
        )
        el = compute_el_portfolio_summary(irb, EMPTY)
        assert el is None

    def test_basic_shortfall_computation(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Should compute shortfall totals and 100% CET1 deduction (Art. 36(1)(d))."""
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
            sa_results=EMPTY_SA,
            irb_results=pad_irb_branch(irb),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert float(el.total_el_shortfall) == pytest.approx(40000.0)
        assert float(el.total_el_excess) == pytest.approx(0.0)
        assert float(el.cet1_deduction) == pytest.approx(40000.0)
        assert float(el.t2_deduction) == pytest.approx(0.0)

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
            sa_results=EMPTY_SA,
            irb_results=pad_irb_branch(irb),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert float(el.total_el_excess) == pytest.approx(50000.0)
        assert float(el.total_irb_rwa) == pytest.approx(8000000.0)
        assert float(el.t2_credit_cap) == pytest.approx(48000.0)
        assert float(el.t2_credit) == pytest.approx(48000.0)

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
            sa_results=EMPTY_SA,
            irb_results=pad_irb_branch(irb),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert float(el.t2_credit_cap) == pytest.approx(60000.0)
        assert float(el.t2_credit) == pytest.approx(20000.0)

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
            sa_results=EMPTY_SA,
            irb_results=pad_irb_branch(irb),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert float(el.t2_credit_cap) == pytest.approx(600000.0)
        assert float(el.t2_credit) == pytest.approx(600000.0)

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
            sa_results=EMPTY_SA,
            irb_results=pad_irb_branch(irb),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )

        el = result.el_summary
        assert el is not None
        assert float(el.total_expected_loss) == pytest.approx(80000.0)
        assert float(el.total_provisions_allocated) == pytest.approx(120000.0)
        assert float(el.total_el_shortfall) == pytest.approx(20000.0)
        assert float(el.total_el_excess) == pytest.approx(60000.0)
        assert float(el.total_irb_rwa) == pytest.approx(10000000.0)
        assert float(el.t2_credit_cap) == pytest.approx(60000.0)
        assert float(el.t2_credit) == pytest.approx(60000.0)
        assert float(el.cet1_deduction) == pytest.approx(20000.0)
        assert float(el.t2_deduction) == pytest.approx(0.0)

    def test_uses_rwa_final_fallback(self) -> None:
        """Should fall back to rwa_final when rwa_post_factor is not available.

        Phase 3: sealed branch inputs always carry ``rwa_post_factor``, so
        the fallback ramp is only reachable through the helper directly
        with a frame that genuinely lacks the column.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach_applied": ["FIRB"],
                "rwa_final": [2000000.0],
                "el_shortfall": [0.0],
                "el_excess": [10000.0],
            }
        )

        el = compute_el_portfolio_summary(irb, None)
        assert el is not None
        assert float(el.total_irb_rwa) == pytest.approx(2000000.0)
        assert float(el.t2_credit_cap) == pytest.approx(12000.0)


# =============================================================================
# Reporting Projection Tests (Phase 7 S2 — the canonical per-leg ledger)
# =============================================================================


class TestReportingProjection:
    """Phase 7 S2: the canonical reporting projection sealed on aggregator_exit.

    The results frame IS the per-leg substitution ledger (physical ``__G_`` /
    ``__REM`` legs); these columns name it once so no consumer re-derives
    class/approach/method or sniffs reference suffixes.
    """

    REPORTING_COLUMNS: tuple[str, ...] = (
        "reporting_class",
        "reporting_class_origin",
        "reporting_approach",
        "reporting_approach_origin",
        "reporting_method",
        "reporting_leg_role",
        "reporting_on_balance_sheet",
        "reporting_subclass",
        "reporting_ead",
        "reporting_rw",
    )

    @pytest.fixture
    def guarantee_leg_results(self) -> pl.LazyFrame:
        """Physical guarantee legs as the CRM stage emits them.

        One FIRB corporate exposure 60% guaranteed by an SA retail guarantor,
        already split into its ``__G_`` guaranteed leg (is_guaranteed=True,
        guaranteed_portion=EAD) and ``__REM`` retained leg, plus an Art. 234
        tranched pair (``__REM_FL`` / ``__REM_SEN``) from a second exposure and
        one plain unguaranteed exposure.
        """
        return pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": [
                        "EXPG__G_GUAR01",
                        "EXPG__REM",
                        "EXPT__REM_FL",
                        "EXPT__REM_SEN",
                        "EXP_PLAIN",
                    ],
                    "counterparty_reference": ["B01", "B01", "B02", "B02", "B03"],
                    "exposure_class": ["CORPORATE"] * 5,
                    "approach": ["FIRB"] * 5,
                    "approach_applied": ["FIRB"] * 5,
                    "ead_final": [600000.0, 400000.0, 100000.0, 900000.0, 250000.0],
                    "risk_weight": [0.75, 0.5, 0.5, 0.5, 0.5],
                    "rwa_final": [450000.0, 200000.0, 50000.0, 450000.0, 125000.0],
                    "is_guaranteed": [True, False, False, False, False],
                    "guaranteed_portion": [600000.0, 0.0, 0.0, 0.0, 0.0],
                    "unguaranteed_portion": [0.0, 400000.0, 100000.0, 900000.0, 0.0],
                    "guarantor_approach": ["sa", None, None, None, None],
                    "guarantor_reference": ["GUAR01", None, None, None, None],
                    "pre_crm_exposure_class": ["CORPORATE"] * 5,
                    "post_crm_exposure_class_guaranteed": ["RETAIL", None, None, None, None],
                }
            )
        )

    def _aggregate_irb(
        self,
        aggregator: OutputAggregator,
        frame: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.DataFrame:
        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=frame,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=config,
        )
        return result.results.collect()

    def _aggregate_sa(
        self,
        aggregator: OutputAggregator,
        frame: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.DataFrame:
        result = aggregator.aggregate(
            sa_results=frame,
            irb_results=EMPTY_IRB,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=config,
        )
        return result.results.collect()

    def test_projection_columns_sealed_on_results(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Every projection column is present on the sealed results frame."""
        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=None,
            config=crr_config,
        )
        schema = result.results.collect_schema()
        missing = [c for c in self.REPORTING_COLUMNS if c not in schema.names()]
        assert not missing, f"projection columns missing from aggregator_exit: {missing}"
        assert schema["reporting_on_balance_sheet"] == pl.Boolean
        assert schema["reporting_ead"] == pl.Float64
        assert schema["reporting_rw"] == pl.Float64

    def test_projection_columns_declared_on_edge(self) -> None:
        """The edge contract declares the projection with its citations."""
        from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE

        for name in self.REPORTING_COLUMNS:
            assert name in AGGREGATOR_EXIT_EDGE.columns, name
        assert AGGREGATOR_EXIT_EDGE.columns["reporting_class"].citation == "CRR Art. 235"
        assert AGGREGATOR_EXIT_EDGE.columns["reporting_class_origin"].citation == "CRR Art. 112"
        assert AGGREGATOR_EXIT_EDGE.columns["reporting_leg_role"].citation == "CRR Art. 235"

    def test_aliases_mirror_sealed_sources(
        self,
        aggregator: OutputAggregator,
        guarantee_leg_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """The alias columns equal their sealed sources row-for-row."""
        df = self._aggregate_irb(aggregator, guarantee_leg_results, crr_config)
        for alias, source in (
            ("reporting_class", "exposure_class_post_crm"),
            ("reporting_class_origin", "exposure_class_applied"),
            ("reporting_approach", "approach_post_crm"),
            ("reporting_approach_origin", "approach_applied"),
            ("reporting_subclass", "exposure_subclass"),
            ("reporting_ead", "ead_final"),
            ("reporting_rw", "risk_weight"),
        ):
            assert df[alias].to_list() == df[source].to_list(), (alias, source)

    def test_leg_roles_name_the_physical_guarantee_split(
        self,
        aggregator: OutputAggregator,
        guarantee_leg_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """guaranteed = the __G_ leg; retained = __REM/__REM_FL/__REM_SEN; else whole."""
        df = self._aggregate_irb(aggregator, guarantee_leg_results, crr_config)
        roles = dict(zip(df["exposure_reference"], df["reporting_leg_role"], strict=True))
        assert roles == {
            "EXPG__G_GUAR01": "guaranteed",
            "EXPG__REM": "retained",
            "EXPT__REM_FL": "retained",
            "EXPT__REM_SEN": "retained",
            "EXP_PLAIN": "whole",
        }

    def test_substitution_flows_reconstruct_by_grouping(
        self,
        aggregator: OutputAggregator,
        guarantee_leg_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Outflow/inflow (COREP C 07.00) = two Sum bindings over the ledger."""
        df = self._aggregate_irb(aggregator, guarantee_leg_results, crr_config)
        guaranteed = df.filter(pl.col("reporting_leg_role") == "guaranteed")
        outflow = guaranteed.group_by("reporting_class_origin").agg(pl.col("reporting_ead").sum())
        inflow = guaranteed.group_by("reporting_class").agg(pl.col("reporting_ead").sum())
        assert outflow.to_dicts() == [
            {"reporting_class_origin": "CORPORATE", "reporting_ead": 600000.0}
        ]
        assert inflow.to_dicts() == [{"reporting_class": "RETAIL", "reporting_ead": 600000.0}]

    def test_reporting_method_is_post_substitution(
        self,
        aggregator: OutputAggregator,
        guarantee_leg_results: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Method labels the post-substitution approach: SA-guaranteed leg -> STD."""
        df = self._aggregate_irb(aggregator, guarantee_leg_results, crr_config)
        methods = dict(zip(df["exposure_reference"], df["reporting_method"], strict=True))
        assert methods["EXPG__G_GUAR01"] == "STD"
        assert methods["EXPG__REM"] == "FIRB"
        assert methods["EXP_PLAIN"] == "FIRB"

    def test_on_balance_sheet_derived_from_exposure_type(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """loan -> True; facility/contingent -> False; anything else -> null."""
        frame = pad_sa_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
                    "counterparty_reference": ["C1", "C2", "C3", "C4", "C5"],
                    "exposure_class": ["CORPORATE"] * 5,
                    "approach_applied": ["SA"] * 5,
                    "exposure_type": ["loan", "facility", "contingent", "derivative", None],
                    "ead_final": [1.0, 1.0, 1.0, 1.0, 1.0],
                    "risk_weight": [1.0, 1.0, 1.0, 1.0, 1.0],
                    "rwa_final": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            )
        )
        df = self._aggregate_sa(aggregator, frame, crr_config)
        on_bs = dict(zip(df["exposure_reference"], df["reporting_on_balance_sheet"], strict=True))
        assert on_bs == {"E1": True, "E2": False, "E3": False, "E4": None, "E5": None}
