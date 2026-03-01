"""
Unit tests for TransitionalScheduleRunner (M3.3).

Tests the transitional floor schedule modelling including:
- Timeline structure and column completeness
- Floor percentage progression (50% → 72.5%) matches PRA PS9/24
- Monotonically increasing floor impact as percentage rises
- Custom reporting dates support
- Edge cases (empty data, single date)
- Bundle immutability

Why these tests matter:
    The transitional output floor is the most capital-impactful Basel 3.1
    change for IRB banks. Modelling the year-by-year trajectory from 50%
    (2027) to 72.5% (2032+) is essential for capital planning. An error
    in floor percentage lookup or metric extraction would produce incorrect
    capital trajectory forecasts, potentially leading to capital shortfalls.

References:
- PRA PS9/24 Ch.12: Output floor transitional schedule
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, TransitionalScheduleBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.comparison import (
    TransitionalScheduleRunner,
    _build_timeline_lazyframe,
    _extract_floor_metrics,
    _TRANSITIONAL_REPORTING_DATES,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def irb_permissions() -> IRBPermissions:
    """F-IRB permissions for transitional schedule tests."""
    return IRBPermissions.firb_only()


@pytest.fixture
def mock_result_with_floor() -> AggregatedResultBundle:
    """Mock pipeline result with floor impact data."""
    return AggregatedResultBundle(
        results=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "exposure_class": ["corporate", "corporate"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "ead_final": [1_000_000.0, 2_000_000.0],
                "risk_weight": [0.25, 0.50],
                "rwa_final": [300_000.0, 1_000_000.0],
            }
        ),
        floor_impact=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "rwa_pre_floor": [250_000.0, 1_000_000.0],
                "floor_rwa": [300_000.0, 800_000.0],
                "is_floor_binding": [True, False],
                "floor_impact_rwa": [50_000.0, 0.0],
                "rwa_post_floor": [300_000.0, 1_000_000.0],
                "output_floor_pct": [0.50, 0.50],
            }
        ),
        summary_by_approach=pl.LazyFrame(
            {
                "approach_applied": ["foundation_irb"],
                "total_ead": [3_000_000.0],
                "total_rwa": [1_300_000.0],
                "exposure_count": [2],
            }
        ),
        errors=[],
    )


@pytest.fixture
def mock_result_no_floor() -> AggregatedResultBundle:
    """Mock pipeline result without floor impact (SA-only)."""
    return AggregatedResultBundle(
        results=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.50],
                "rwa_final": [500_000.0],
            }
        ),
        summary_by_approach=pl.LazyFrame(
            {
                "approach_applied": ["SA"],
                "total_ead": [1_000_000.0],
                "total_rwa": [500_000.0],
                "exposure_count": [1],
            }
        ),
        errors=[],
    )


# =============================================================================
# Transitional Reporting Dates Tests
# =============================================================================


class TestTransitionalDates:
    """Tests for the default transitional reporting dates."""

    def test_six_transitional_years(self):
        """PRA PS9/24 defines 6 transitional years (2027-2032)."""
        assert len(_TRANSITIONAL_REPORTING_DATES) == 6

    def test_dates_are_mid_year(self):
        """Reporting dates should be mid-year (June 30)."""
        for d in _TRANSITIONAL_REPORTING_DATES:
            assert d.month == 6
            assert d.day == 30

    def test_dates_span_2027_to_2032(self):
        """Dates should cover 2027 through 2032."""
        years = [d.year for d in _TRANSITIONAL_REPORTING_DATES]
        assert years == [2027, 2028, 2029, 2030, 2031, 2032]


# =============================================================================
# Floor Metric Extraction Tests
# =============================================================================


class TestExtractFloorMetrics:
    """Tests for _extract_floor_metrics helper."""

    def test_extracts_floor_impact_metrics(self, mock_result_with_floor):
        """Should extract floor binding count, impact, and pre-floor RWA."""
        metrics = _extract_floor_metrics(
            mock_result_with_floor,
            date(2027, 6, 30),
            0.50,
        )
        assert metrics["year"] == 2027
        assert metrics["floor_percentage"] == 0.50
        assert metrics["floor_binding_count"] == 1  # Only EXP001 binds
        assert metrics["total_floor_impact"] == pytest.approx(50_000.0)
        assert metrics["total_rwa_pre_floor"] == pytest.approx(1_250_000.0)
        assert metrics["total_irb_exposure_count"] == 2

    def test_extracts_summary_metrics(self, mock_result_with_floor):
        """Should extract total RWA and EAD from summary_by_approach."""
        metrics = _extract_floor_metrics(
            mock_result_with_floor,
            date(2027, 6, 30),
            0.50,
        )
        assert metrics["total_rwa_post_floor"] == pytest.approx(1_300_000.0)
        assert metrics["total_ead"] == pytest.approx(3_000_000.0)

    def test_handles_no_floor_impact(self, mock_result_no_floor):
        """Should return zero floor metrics when no floor_impact exists."""
        metrics = _extract_floor_metrics(
            mock_result_no_floor,
            date(2030, 6, 30),
            0.65,
        )
        assert metrics["floor_binding_count"] == 0
        assert metrics["total_floor_impact"] == 0.0
        assert metrics["total_irb_exposure_count"] == 0

    def test_sa_rwa_back_calculated(self, mock_result_with_floor):
        """SA RWA should be back-calculated from floor_rwa / floor_pct."""
        metrics = _extract_floor_metrics(
            mock_result_with_floor,
            date(2027, 6, 30),
            0.50,
        )
        # floor_rwa total = 300k + 800k = 1.1M; SA RWA = 1.1M / 0.50 = 2.2M
        assert metrics["total_sa_rwa"] == pytest.approx(2_200_000.0)


# =============================================================================
# Timeline LazyFrame Build Tests
# =============================================================================


class TestBuildTimelineLazyframe:
    """Tests for _build_timeline_lazyframe helper."""

    def test_empty_rows_returns_empty_frame(self):
        """Empty input should produce empty LazyFrame with correct schema."""
        timeline = _build_timeline_lazyframe([])
        df = timeline.collect()
        assert df.height == 0
        expected_cols = {
            "reporting_date", "year", "floor_percentage",
            "total_rwa_pre_floor", "total_rwa_post_floor",
            "total_floor_impact", "floor_binding_count",
            "total_irb_exposure_count", "total_ead", "total_sa_rwa",
        }
        assert expected_cols == set(df.columns)

    def test_single_row(self):
        """Single row should produce valid timeline."""
        rows = [{
            "reporting_date": date(2027, 6, 30),
            "year": 2027,
            "floor_percentage": 0.50,
            "total_rwa_pre_floor": 100_000.0,
            "total_rwa_post_floor": 120_000.0,
            "total_floor_impact": 20_000.0,
            "floor_binding_count": 5,
            "total_irb_exposure_count": 10,
            "total_ead": 500_000.0,
            "total_sa_rwa": 200_000.0,
        }]
        timeline = _build_timeline_lazyframe(rows)
        df = timeline.collect()
        assert df.height == 1
        assert df["year"][0] == 2027
        assert df["floor_percentage"][0] == pytest.approx(0.50)

    def test_multiple_rows_sorted(self):
        """Multiple rows should appear in the LazyFrame in order."""
        rows = [
            {
                "reporting_date": date(2027, 6, 30), "year": 2027,
                "floor_percentage": 0.50, "total_rwa_pre_floor": 0.0,
                "total_rwa_post_floor": 0.0, "total_floor_impact": 0.0,
                "floor_binding_count": 0, "total_irb_exposure_count": 0,
                "total_ead": 0.0, "total_sa_rwa": 0.0,
            },
            {
                "reporting_date": date(2032, 6, 30), "year": 2032,
                "floor_percentage": 0.725, "total_rwa_pre_floor": 0.0,
                "total_rwa_post_floor": 0.0, "total_floor_impact": 0.0,
                "floor_binding_count": 0, "total_irb_exposure_count": 0,
                "total_ead": 0.0, "total_sa_rwa": 0.0,
            },
        ]
        timeline = _build_timeline_lazyframe(rows)
        df = timeline.collect()
        assert df.height == 2
        assert df["year"].to_list() == [2027, 2032]

    def test_column_types(self):
        """Timeline columns should have correct Polars types."""
        rows = [{
            "reporting_date": date(2027, 6, 30),
            "year": 2027,
            "floor_percentage": 0.50,
            "total_rwa_pre_floor": 0.0,
            "total_rwa_post_floor": 0.0,
            "total_floor_impact": 0.0,
            "floor_binding_count": 0,
            "total_irb_exposure_count": 0,
            "total_ead": 0.0,
            "total_sa_rwa": 0.0,
        }]
        timeline = _build_timeline_lazyframe(rows)
        schema = timeline.collect_schema()
        assert schema["reporting_date"] == pl.Date
        assert schema["year"] == pl.Int32
        assert schema["floor_percentage"] == pl.Float64
        assert schema["floor_binding_count"] == pl.UInt32
        assert schema["total_irb_exposure_count"] == pl.UInt32


# =============================================================================
# TransitionalScheduleBundle Tests
# =============================================================================


class TestTransitionalScheduleBundle:
    """Tests for the TransitionalScheduleBundle dataclass."""

    def test_bundle_is_frozen(self):
        """TransitionalScheduleBundle should be immutable."""
        bundle = TransitionalScheduleBundle(
            timeline=pl.LazyFrame(),
            yearly_results={},
            errors=[],
        )
        with pytest.raises(AttributeError):
            bundle.errors = ["new error"]  # type: ignore[misc]

    def test_bundle_default_fields(self):
        """Bundle should have sensible defaults."""
        bundle = TransitionalScheduleBundle(timeline=pl.LazyFrame())
        assert bundle.yearly_results == {}
        assert bundle.errors == []


# =============================================================================
# TransitionalScheduleRunner Integration Tests
# =============================================================================


class TestTransitionalScheduleRunner:
    """Integration tests for TransitionalScheduleRunner.run().

    These use minimal mock data that survives the full pipeline.
    Rich portfolio testing is in acceptance tests.
    """

    def test_runner_returns_bundle(self, irb_permissions):
        """Runner should return a TransitionalScheduleBundle."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
            reporting_dates=[date(2027, 6, 30)],  # Single date for speed
        )
        assert isinstance(result, TransitionalScheduleBundle)

    def test_runner_timeline_has_correct_columns(self, irb_permissions):
        """Timeline should have all expected columns."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
            reporting_dates=[date(2027, 6, 30)],
        )
        df = result.timeline.collect()
        expected_cols = {
            "reporting_date", "year", "floor_percentage",
            "total_rwa_pre_floor", "total_rwa_post_floor",
            "total_floor_impact", "floor_binding_count",
            "total_irb_exposure_count", "total_ead", "total_sa_rwa",
        }
        assert expected_cols == set(df.columns)

    def test_runner_yearly_results_populated(self, irb_permissions):
        """yearly_results should contain one entry per reporting date."""
        runner = TransitionalScheduleRunner()
        dates = [date(2027, 6, 30), date(2028, 6, 30)]
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
            reporting_dates=dates,
        )
        assert 2027 in result.yearly_results
        assert 2028 in result.yearly_results
        assert isinstance(result.yearly_results[2027], AggregatedResultBundle)

    def test_runner_floor_percentage_matches_schedule(self, irb_permissions):
        """Floor percentage in timeline should match PRA PS9/24 schedule."""
        runner = TransitionalScheduleRunner()
        dates = [date(2027, 6, 30), date(2030, 6, 30), date(2032, 6, 30)]
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
            reporting_dates=dates,
        )
        df = result.timeline.collect()
        pct_by_year = dict(zip(df["year"].to_list(), df["floor_percentage"].to_list()))
        assert pct_by_year[2027] == pytest.approx(0.50)
        assert pct_by_year[2030] == pytest.approx(0.65)
        assert pct_by_year[2032] == pytest.approx(0.725)

    def test_runner_custom_dates(self, irb_permissions):
        """Runner should accept custom reporting dates."""
        runner = TransitionalScheduleRunner()
        custom_dates = [date(2027, 12, 31), date(2029, 12, 31)]
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
            reporting_dates=custom_dates,
        )
        df = result.timeline.collect()
        assert df.height == 2
        assert df["year"].to_list() == [2027, 2029]

    def test_runner_default_dates_produces_six_rows(self, irb_permissions):
        """Default dates should produce 6 timeline rows (2027-2032)."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=_make_minimal_raw_data(),
            irb_permissions=irb_permissions,
        )
        df = result.timeline.collect()
        assert df.height == 6
        assert df["year"].to_list() == [2027, 2028, 2029, 2030, 2031, 2032]


# =============================================================================
# Helpers
# =============================================================================


def _make_minimal_raw_data():
    """Create minimal RawDataBundle for runner integration tests."""
    from rwa_calc.contracts.bundles import RawDataBundle

    facilities = pl.LazyFrame(
        {
            "facility_reference": ["FAC001"],
            "counterparty_reference": ["CP001"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["BANK"],
            "currency": ["GBP"],
            "facility_limit": [1_000_000.0],
        }
    )

    loans = pl.LazyFrame(
        {
            "loan_reference": ["LN001"],
            "counterparty_reference": ["CP001"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["BANK"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2033, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500_000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["FR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [None],
        }
    )

    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": ["CP001"],
            "counterparty_name": ["Test Corp"],
            "country_of_incorporation": ["GB"],
            "sector": ["CORPORATE"],
            "entity_type": ["corporate"],
            "is_sme": [False],
            "is_regulated": [False],
            "is_pse": [False],
            "cqs": [2],
            "pd": [0.01],
            "turnover_eur": [100_000_000.0],
        }
    )

    facility_mappings = pl.LazyFrame(
        {
            "facility_reference": ["FAC001"],
            "loan_reference": ["LN001"],
        }
    )

    lending_mappings = pl.LazyFrame(
        {
            "counterparty_reference": ["CP001"],
            "lending_group_id": ["LG001"],
        }
    )

    return RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )
