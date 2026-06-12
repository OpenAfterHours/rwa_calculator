"""
Unit tests for TransitionalScheduleRunner (M3.3).

Tests the transitional floor schedule modelling including:
- Timeline structure and column completeness
- Floor percentage progression (60% → 72.5%) matches PRA PS1/26
- Monotonically increasing floor impact as percentage rises
- Custom reporting dates support
- Edge cases (empty data, single date)
- Bundle immutability

Why these tests matter:
    The transitional output floor is the most capital-impactful Basel 3.1
    change for IRB banks. Modelling the year-by-year trajectory from 60%
    (2027) to 72.5% (2030+) is essential for capital planning. An error
    in floor percentage lookup or metric extraction would produce incorrect
    capital trajectory forecasts, potentially leading to capital shortfalls.

References:
- PRA PS1/26 Ch.12: Output floor transitional schedule
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, TransitionalScheduleBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.comparison import (
    _TRANSITIONAL_REPORTING_DATES,
    TransitionalScheduleRunner,
    _build_timeline_lazyframe,
    _extract_floor_metrics,
)
from tests.fixtures.resolved_bundle import make_aggregated_bundle
from tests.unit._minimal_raw_data import make_minimal_raw_data

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def permission_mode() -> PermissionMode:
    """IRB permission mode for transitional schedule tests."""
    return PermissionMode.IRB


@pytest.fixture
def mock_result_with_floor() -> AggregatedResultBundle:
    """Mock pipeline result with floor impact data."""
    return make_aggregated_bundle(
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
    return make_aggregated_bundle(
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

    def test_four_transitional_years(self):
        """PRA PS1/26 defines 4 transitional years (2027-2030)."""
        assert len(_TRANSITIONAL_REPORTING_DATES) == 4

    def test_dates_are_first_of_january(self):
        """Reporting dates must be 1 January per PRA PS1/26 Art. 92(5)."""
        # Arrange: the constant is imported from comparison.py
        # Act: inspect each date in the constant
        # Assert: every date is 1-Jan (fails under buggy June-30 HEAD)
        for d in _TRANSITIONAL_REPORTING_DATES:
            assert d.month == 1, f"Expected month 1 (January), got {d.month} for date {d}"
            assert d.day == 1, f"Expected day 1, got {d.day} for date {d}"

    def test_dates_span_2027_to_2030(self):
        """Dates should cover 2027 through 2030."""
        years = [d.year for d in _TRANSITIONAL_REPORTING_DATES]
        assert years == [2027, 2028, 2029, 2030]


# =============================================================================
# P6.23 — Transitional date correctness (1 Jan per PRA PS1/26 Art. 92(5))
# =============================================================================


class TestTransitionalDatesP623:
    """Behavioural tests verifying the default-path pipeline emits 1-Jan dates.

    The RED assertion: default reporting_dates=None must produce a timeline
    whose reporting_date column contains [date(2027,1,1), date(2028,1,1),
    date(2029,1,1), date(2030,1,1)].  Under the buggy June-30 HEAD this
    fails with AssertionError because the column contains June-30 dates.
    """

    def test_default_path_timeline_reporting_dates_are_first_of_january(self):
        """Default run (reporting_dates=None) must emit 1-Jan dates in timeline.

        Fails RED under the buggy HEAD (comparison.py has June-30 dates).
        Passes after engine-implementer fixes _TRANSITIONAL_REPORTING_DATES.

        References:
        - PRA PS1/26 Art. 92(5): output floor phase-in dates are 1 January
        """
        # Arrange
        runner = TransitionalScheduleRunner()
        expected_dates = [
            date(2027, 1, 1),
            date(2028, 1, 1),
            date(2029, 1, 1),
            date(2030, 1, 1),
        ]

        # Act — reporting_dates=None triggers the default constant path
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=PermissionMode.IRB,
            reporting_dates=None,
        )
        df = result.timeline.collect()
        actual_dates = df["reporting_date"].to_list()

        # Assert — fails under buggy HEAD (June-30 dates)
        assert actual_dates == expected_dates, (
            f"Expected reporting_date column {expected_dates}, got {actual_dates}. "
            "PRA PS1/26 Art. 92(5) requires 1-January dates."
        )

    def test_regulatory_intent_floor_at_2027_jan_1_is_60_pct(self):
        """Floor for Basel 3.1 config with reporting_date=2027-01-01 is 60%.

        This is the regulatory-intent guard — it passes already under the
        buggy HEAD (CalculationConfig.get_output_floor_percentage is correct)
        and continues to pass post-fix. Kept here to prove that the corrected
        boundary date maps to the right floor percentage.
        """
        # Arrange
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

        # Act
        floor_pct = config.get_output_floor_percentage()

        # Assert
        assert floor_pct == Decimal("0.60"), f"Expected floor 0.60 for 2027-01-01, got {floor_pct}"


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
        assert metrics["floor_percentage"] == pytest.approx(0.50, abs=1e-10)
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
        assert metrics["total_floor_impact"] == pytest.approx(0.0, abs=1e-10)
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
            "reporting_date",
            "year",
            "floor_percentage",
            "total_rwa_pre_floor",
            "total_rwa_post_floor",
            "total_floor_impact",
            "floor_binding_count",
            "total_irb_exposure_count",
            "total_ead",
            "total_sa_rwa",
        }
        assert expected_cols == set(df.columns)

    def test_single_row(self):
        """Single row should produce valid timeline."""
        rows = [
            {
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
            }
        ]
        timeline = _build_timeline_lazyframe(rows)
        df = timeline.collect()
        assert df.height == 1
        assert df["year"][0] == 2027
        assert df["floor_percentage"][0] == pytest.approx(0.50)

    def test_multiple_rows_sorted(self):
        """Multiple rows should appear in the LazyFrame in order."""
        rows = [
            {
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
            },
            {
                "reporting_date": date(2032, 6, 30),
                "year": 2032,
                "floor_percentage": 0.725,
                "total_rwa_pre_floor": 0.0,
                "total_rwa_post_floor": 0.0,
                "total_floor_impact": 0.0,
                "floor_binding_count": 0,
                "total_irb_exposure_count": 0,
                "total_ead": 0.0,
                "total_sa_rwa": 0.0,
            },
        ]
        timeline = _build_timeline_lazyframe(rows)
        df = timeline.collect()
        assert df.height == 2
        assert df["year"].to_list() == [2027, 2032]

    def test_column_types(self):
        """Timeline columns should have correct Polars types."""
        rows = [
            {
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
            }
        ]
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

    def test_runner_returns_bundle(self, permission_mode):
        """Runner should return a TransitionalScheduleBundle."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
            reporting_dates=[date(2027, 6, 30)],  # Single date for speed
        )
        assert isinstance(result, TransitionalScheduleBundle)

    def test_runner_timeline_has_correct_columns(self, permission_mode):
        """Timeline should have all expected columns."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
            reporting_dates=[date(2027, 6, 30)],
        )
        df = result.timeline.collect()
        expected_cols = {
            "reporting_date",
            "year",
            "floor_percentage",
            "total_rwa_pre_floor",
            "total_rwa_post_floor",
            "total_floor_impact",
            "floor_binding_count",
            "total_irb_exposure_count",
            "total_ead",
            "total_sa_rwa",
        }
        assert expected_cols == set(df.columns)

    def test_runner_yearly_results_populated(self, permission_mode):
        """yearly_results should contain one entry per reporting date."""
        runner = TransitionalScheduleRunner()
        dates = [date(2027, 6, 30), date(2028, 6, 30)]
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
            reporting_dates=dates,
        )
        assert 2027 in result.yearly_results
        assert 2028 in result.yearly_results
        assert isinstance(result.yearly_results[2027], AggregatedResultBundle)

    def test_runner_floor_percentage_matches_schedule(self, permission_mode):
        """Floor percentage in timeline should match PRA PS1/26 schedule."""
        runner = TransitionalScheduleRunner()
        dates = [date(2027, 6, 30), date(2029, 6, 30), date(2030, 6, 30)]
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
            reporting_dates=dates,
        )
        df = result.timeline.collect()
        pct_by_year = dict(zip(df["year"].to_list(), df["floor_percentage"].to_list(), strict=True))
        assert pct_by_year[2027] == pytest.approx(0.60)
        assert pct_by_year[2029] == pytest.approx(0.70)
        assert pct_by_year[2030] == pytest.approx(0.725)

    def test_runner_custom_dates(self, permission_mode):
        """Runner should accept custom reporting dates."""
        runner = TransitionalScheduleRunner()
        custom_dates = [date(2027, 12, 31), date(2029, 12, 31)]
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
            reporting_dates=custom_dates,
        )
        df = result.timeline.collect()
        assert df.height == 2
        assert df["year"].to_list() == [2027, 2029]

    def test_runner_default_dates_produces_four_rows(self, permission_mode):
        """Default dates should produce 4 timeline rows (2027-2030)."""
        runner = TransitionalScheduleRunner()
        result = runner.run(
            data=make_minimal_raw_data(maturity_date=date(2033, 1, 1)),
            permission_mode=permission_mode,
        )
        df = result.timeline.collect()
        assert df.height == 4
        assert df["year"].to_list() == [2027, 2028, 2029, 2030]
