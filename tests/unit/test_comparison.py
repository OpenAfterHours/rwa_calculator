"""
Unit tests for DualFrameworkRunner comparison engine.

Tests the comparison module including:
- Config validation (wrong framework types rejected)
- Dual pipeline execution and result joining
- Delta computation (positive = B31 higher than CRR)
- Summary aggregation by exposure class and approach
- Error accumulation from both pipeline runs

Why these tests matter:
    DualFrameworkRunner is the foundation for M3.1 (side-by-side comparison),
    M3.2 (capital impact analysis), and M3.3 (transitional floor modelling).
    Correctness of the delta join and aggregation logic is critical — an error
    here would propagate into every downstream impact analysis.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, ComparisonBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.comparison import (
    DualFrameworkRunner,
    _compute_exposure_deltas,
    _compute_summary_by_approach,
    _compute_summary_by_class,
    _validate_configs,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration for comparison tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration for comparison tests."""
    return CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))


@pytest.fixture
def mock_crr_results() -> AggregatedResultBundle:
    """Mock CRR pipeline results with 3 exposures."""
    return AggregatedResultBundle(
        results=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002", "EXP003"],
                "exposure_class": ["corporate", "retail_mortgage", "institution"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [1_000_000.0, 500_000.0, 2_000_000.0],
                "risk_weight": [1.0, 0.35, 0.20],
                "rwa_final": [1_000_000.0, 175_000.0, 400_000.0],
            }
        ),
        errors=[],
    )


@pytest.fixture
def mock_b31_results() -> AggregatedResultBundle:
    """Mock Basel 3.1 pipeline results (same exposures, different values)."""
    return AggregatedResultBundle(
        results=pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002", "EXP003"],
                "exposure_class": ["corporate", "retail_mortgage", "institution"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [1_000_000.0, 500_000.0, 2_000_000.0],
                "risk_weight": [0.65, 0.25, 0.30],
                "rwa_final": [650_000.0, 125_000.0, 600_000.0],
            }
        ),
        errors=[],
    )


# =============================================================================
# Config Validation Tests
# =============================================================================


class TestConfigValidation:
    """Tests for config type validation."""

    def test_valid_configs_pass(self, crr_config, b31_config):
        """Valid CRR + B31 configs should not raise."""
        _validate_configs(crr_config, b31_config)

    def test_swapped_configs_raises(self, crr_config, b31_config):
        """Swapping CRR/B31 configs should raise ValueError."""
        with pytest.raises(ValueError, match="crr_config must use CRR"):
            _validate_configs(b31_config, crr_config)

    def test_both_crr_raises(self, crr_config):
        """Two CRR configs should raise ValueError."""
        with pytest.raises(ValueError, match="b31_config must use Basel 3.1"):
            _validate_configs(crr_config, crr_config)

    def test_both_b31_raises(self, b31_config):
        """Two B31 configs should raise ValueError."""
        with pytest.raises(ValueError, match="crr_config must use CRR"):
            _validate_configs(b31_config, b31_config)


# =============================================================================
# Exposure Delta Computation Tests
# =============================================================================


class TestExposureDeltas:
    """Tests for per-exposure delta computation."""

    def test_delta_columns_present(self, mock_crr_results, mock_b31_results):
        """Delta LazyFrame should contain all expected columns."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        df = deltas.collect()

        expected_cols = {
            "exposure_reference",
            "exposure_class",
            "approach_applied",
            "rwa_final_crr",
            "rwa_final_b31",
            "delta_rwa",
            "delta_risk_weight",
            "delta_ead",
            "delta_rwa_pct",
        }
        assert expected_cols.issubset(set(df.columns))

    def test_delta_rwa_positive_means_b31_higher(self, mock_crr_results, mock_b31_results):
        """Positive delta_rwa means B31 requires more capital than CRR."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        df = deltas.collect()

        # EXP001: B31 RWA 650k < CRR RWA 1M → negative delta (B31 lower)
        exp001 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["delta_rwa"][0] == pytest.approx(-350_000.0)

        # EXP003: B31 RWA 600k > CRR RWA 400k → positive delta (B31 higher)
        exp003 = df.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["delta_rwa"][0] == pytest.approx(200_000.0)

    def test_delta_risk_weight_computed(self, mock_crr_results, mock_b31_results):
        """Delta risk weight should be B31 RW - CRR RW."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        df = deltas.collect()

        # EXP001: B31 RW 0.65 - CRR RW 1.0 = -0.35
        exp001 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["delta_risk_weight"][0] == pytest.approx(-0.35)

    def test_delta_pct_relative_to_crr(self, mock_crr_results, mock_b31_results):
        """Delta percentage should be relative to CRR RWA."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        df = deltas.collect()

        # EXP001: delta = -350k, CRR = 1M → -35%
        exp001 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["delta_rwa_pct"][0] == pytest.approx(-35.0)

        # EXP003: delta = 200k, CRR = 400k → 50%
        exp003 = df.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["delta_rwa_pct"][0] == pytest.approx(50.0)

    def test_same_exposure_count(self, mock_crr_results, mock_b31_results):
        """All exposures from both frameworks should appear in join."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        df = deltas.collect()
        assert df.height == 3

    def test_zero_delta_when_identical(self):
        """Identical results should produce zero deltas."""
        results = AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": ["EXP001"],
                    "exposure_class": ["corporate"],
                    "approach_applied": ["SA"],
                    "ead_final": [1_000_000.0],
                    "risk_weight": [1.0],
                    "rwa_final": [1_000_000.0],
                }
            ),
            errors=[],
        )
        deltas = _compute_exposure_deltas(results, results)
        df = deltas.collect()
        assert df["delta_rwa"][0] == pytest.approx(0.0)
        assert df["delta_risk_weight"][0] == pytest.approx(0.0)
        assert df["delta_ead"][0] == pytest.approx(0.0)
        assert df["delta_rwa_pct"][0] == pytest.approx(0.0)

    def test_full_outer_join_handles_mismatched_exposures(self):
        """Exposures in only one framework should still appear with nulls filled."""
        crr = AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": ["EXP001", "CRR_ONLY"],
                    "exposure_class": ["corporate", "corporate"],
                    "approach_applied": ["SA", "SA"],
                    "ead_final": [1_000_000.0, 500_000.0],
                    "risk_weight": [1.0, 1.0],
                    "rwa_final": [1_000_000.0, 500_000.0],
                }
            ),
            errors=[],
        )
        b31 = AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": ["EXP001", "B31_ONLY"],
                    "exposure_class": ["corporate", "institution"],
                    "approach_applied": ["SA", "SA"],
                    "ead_final": [1_000_000.0, 200_000.0],
                    "risk_weight": [0.65, 0.30],
                    "rwa_final": [650_000.0, 60_000.0],
                }
            ),
            errors=[],
        )
        deltas = _compute_exposure_deltas(crr, b31)
        df = deltas.collect()
        assert df.height == 3  # EXP001 + CRR_ONLY + B31_ONLY

        crr_only = df.filter(pl.col("exposure_reference") == "CRR_ONLY")
        assert crr_only["rwa_final_crr"][0] == pytest.approx(500_000.0)
        assert crr_only["delta_rwa"][0] == pytest.approx(-500_000.0)  # B31 has 0

        b31_only = df.filter(pl.col("exposure_reference") == "B31_ONLY")
        assert b31_only["rwa_final_b31"][0] == pytest.approx(60_000.0)
        assert b31_only["delta_rwa"][0] == pytest.approx(60_000.0)  # CRR has 0


# =============================================================================
# Summary Aggregation Tests
# =============================================================================


class TestSummaryByClass:
    """Tests for summary aggregation by exposure class."""

    def test_summary_groups_by_class(self, mock_crr_results, mock_b31_results):
        """Summary should have one row per exposure class."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        summary = _compute_summary_by_class(deltas)
        df = summary.collect()
        assert df.height == 3  # corporate, retail_mortgage, institution

    def test_summary_totals_correct(self, mock_crr_results, mock_b31_results):
        """Summary totals should match sum of individual deltas."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        summary = _compute_summary_by_class(deltas)
        df = summary.collect()

        corp = df.filter(pl.col("exposure_class") == "corporate")
        assert corp["total_rwa_crr"][0] == pytest.approx(1_000_000.0)
        assert corp["total_rwa_b31"][0] == pytest.approx(650_000.0)
        assert corp["total_delta_rwa"][0] == pytest.approx(-350_000.0)
        assert corp["exposure_count"][0] == 1

    def test_summary_delta_pct(self, mock_crr_results, mock_b31_results):
        """Summary delta percentage should be relative to total CRR RWA."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        summary = _compute_summary_by_class(deltas)
        df = summary.collect()

        inst = df.filter(pl.col("exposure_class") == "institution")
        # delta = 200k, crr = 400k → 50%
        assert inst["delta_rwa_pct"][0] == pytest.approx(50.0)


class TestSummaryByApproach:
    """Tests for summary aggregation by approach."""

    def test_summary_groups_by_approach(self, mock_crr_results, mock_b31_results):
        """Summary should have one row per approach."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        summary = _compute_summary_by_approach(deltas)
        df = summary.collect()
        assert df.height == 1  # All SA in mock data

    def test_approach_totals_sum_correctly(self, mock_crr_results, mock_b31_results):
        """Total RWA across all approaches should match sum of all exposures."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        summary = _compute_summary_by_approach(deltas)
        df = summary.collect()

        sa_row = df.filter(pl.col("approach_applied") == "SA")
        # CRR: 1M + 175k + 400k = 1.575M
        assert sa_row["total_rwa_crr"][0] == pytest.approx(1_575_000.0)
        # B31: 650k + 125k + 600k = 1.375M
        assert sa_row["total_rwa_b31"][0] == pytest.approx(1_375_000.0)


# =============================================================================
# ComparisonBundle Structure Tests
# =============================================================================


class TestComparisonBundle:
    """Tests for ComparisonBundle dataclass structure."""

    def test_bundle_is_frozen(self, mock_crr_results, mock_b31_results):
        """ComparisonBundle should be immutable (frozen dataclass)."""
        deltas = _compute_exposure_deltas(mock_crr_results, mock_b31_results)
        bundle = ComparisonBundle(
            crr_results=mock_crr_results,
            b31_results=mock_b31_results,
            exposure_deltas=deltas,
            summary_by_class=_compute_summary_by_class(deltas),
            summary_by_approach=_compute_summary_by_approach(deltas),
            errors=[],
        )
        with pytest.raises(AttributeError):
            bundle.errors = ["new error"]  # type: ignore[misc]

    def test_bundle_error_accumulation(self):
        """Bundle should accumulate errors from both pipelines."""
        crr = AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": ["EXP001"],
                    "exposure_class": ["corporate"],
                    "approach_applied": ["SA"],
                    "ead_final": [1_000_000.0],
                    "risk_weight": [1.0],
                    "rwa_final": [1_000_000.0],
                }
            ),
            errors=["crr_error_1"],
        )
        b31 = AggregatedResultBundle(
            results=pl.LazyFrame(
                {
                    "exposure_reference": ["EXP001"],
                    "exposure_class": ["corporate"],
                    "approach_applied": ["SA"],
                    "ead_final": [1_000_000.0],
                    "risk_weight": [0.65],
                    "rwa_final": [650_000.0],
                }
            ),
            errors=["b31_error_1", "b31_error_2"],
        )
        deltas = _compute_exposure_deltas(crr, b31)
        bundle = ComparisonBundle(
            crr_results=crr,
            b31_results=b31,
            exposure_deltas=deltas,
            summary_by_class=_compute_summary_by_class(deltas),
            summary_by_approach=_compute_summary_by_approach(deltas),
            errors=list(crr.errors) + list(b31.errors),
        )
        assert len(bundle.errors) == 3


# =============================================================================
# DualFrameworkRunner Integration Tests
# =============================================================================


class TestDualFrameworkRunner:
    """Integration tests for DualFrameworkRunner.compare()."""

    def test_runner_validates_configs(self, crr_config, b31_config):
        """Runner should reject swapped configs."""
        runner = DualFrameworkRunner()
        # Swapped configs should raise
        with pytest.raises(ValueError, match="crr_config must use CRR"):
            runner.compare(
                data=_make_minimal_raw_data(),
                crr_config=b31_config,
                b31_config=crr_config,
            )

    def test_runner_returns_comparison_bundle(self, crr_config, b31_config):
        """Runner should return a ComparisonBundle with all fields populated."""
        runner = DualFrameworkRunner()
        result = runner.compare(
            data=_make_minimal_raw_data(),
            crr_config=crr_config,
            b31_config=b31_config,
        )
        assert isinstance(result, ComparisonBundle)
        assert isinstance(result.crr_results, AggregatedResultBundle)
        assert isinstance(result.b31_results, AggregatedResultBundle)
        assert isinstance(result.exposure_deltas, pl.LazyFrame)
        assert isinstance(result.summary_by_class, pl.LazyFrame)
        assert isinstance(result.summary_by_approach, pl.LazyFrame)

    def test_runner_exposure_deltas_collectible(self, crr_config, b31_config):
        """Exposure deltas should be a valid LazyFrame that can be collected."""
        runner = DualFrameworkRunner()
        result = runner.compare(
            data=_make_minimal_raw_data(),
            crr_config=crr_config,
            b31_config=b31_config,
        )
        df = result.exposure_deltas.collect()
        assert "delta_rwa" in df.columns
        assert "delta_risk_weight" in df.columns
        assert "delta_rwa_pct" in df.columns

    def test_runner_graceful_with_minimal_data(self):
        """Minimal mock data may not survive full pipeline — verify graceful result.

        The full pipeline requires rich input data (counterparties with ratings,
        facility mappings, etc.) to produce classified and calculated exposures.
        Minimal data is expected to produce zero result rows but no exceptions.
        Full pipeline coverage is in acceptance tests with real fixture data.
        """
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        b31_config = CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))

        runner = DualFrameworkRunner()
        result = runner.compare(
            data=_make_minimal_raw_data(),
            crr_config=crr_config,
            b31_config=b31_config,
        )
        df = result.exposure_deltas.collect()
        assert isinstance(df, pl.DataFrame)
        assert "delta_rwa" in df.columns


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
            "maturity_date": [date(2028, 1, 1)],
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
