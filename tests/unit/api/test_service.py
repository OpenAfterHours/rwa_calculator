"""Unit tests for the API service module.

Tests cover:
- CreditRiskCalc class
- get_supported_frameworks / get_default_config module functions
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from rwa_calc.api.models import (
    CalculationResponse,
    ValidationResponse,
)
from rwa_calc.api.service import (
    CreditRiskCalc,
    get_default_config,
    get_supported_frameworks,
)

# =============================================================================
# Fixtures
# =============================================================================


# =============================================================================
# CreditRiskCalc Tests
# =============================================================================


class TestCreditRiskCalcInit:
    """Tests for CreditRiskCalc initialization."""

    def test_creates_with_required_fields(self) -> None:
        """Should create instance with required fields."""
        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert calc.data_path == Path("/path/to/data")
        assert calc.framework == "CRR"
        assert calc.reporting_date == date(2024, 12, 31)

    def test_default_values(self) -> None:
        """Default values should be set correctly."""
        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert calc.permission_mode == "standardised"
        assert calc.data_format == "parquet"
        assert calc.base_currency == "GBP"

    def test_creates_internal_components(self) -> None:
        """Should create internal components."""
        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert calc._validator is not None
        assert calc._formatter is not None
        assert calc._cache is not None


class TestCreditRiskCalcValidate:
    """Tests for CreditRiskCalc.validate method."""

    def test_valid_path(self, temp_valid_dir: Path) -> None:
        """Should return valid response for valid path."""
        calc = CreditRiskCalc(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        response = calc.validate()
        assert isinstance(response, ValidationResponse)
        assert response.valid is True

    def test_invalid_path(self, tmp_path: Path) -> None:
        """Should return invalid response for non-existent path."""
        calc = CreditRiskCalc(
            data_path=tmp_path / "nonexistent",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        response = calc.validate()
        assert response.valid is False
        assert len(response.errors) > 0


class TestCreditRiskCalcCalculate:
    """Tests for CreditRiskCalc.calculate method."""

    def test_invalid_path_returns_error(self, tmp_path: Path) -> None:
        """Should return error response for invalid path."""
        calc = CreditRiskCalc(
            data_path=tmp_path / "nonexistent",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            cache_dir=tmp_path / "cache",
        )
        response = calc.calculate()
        assert response.success is False
        assert len(response.errors) > 0

    def test_calculation_response_structure(self, temp_valid_dir: Path) -> None:
        """Should return properly structured response."""
        mock_bundle = MagicMock()
        mock_bundle.results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_final": [1000000.0],
                "rwa_final": [500000.0],
            }
        )
        mock_bundle.sa_results = None
        mock_bundle.irb_results = None
        mock_bundle.slotting_results = None
        mock_bundle.floor_impact = None
        mock_bundle.summary_by_class = None
        mock_bundle.summary_by_approach = None
        mock_bundle.errors = []

        calc = CreditRiskCalc(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )

        with patch.object(calc, "_create_pipeline") as mock_pipeline:
            mock_pipeline.return_value.run.return_value = mock_bundle
            response = calc.calculate()

            assert isinstance(response, CalculationResponse)
            assert response.framework == "CRR"
            assert response.reporting_date == date(2024, 12, 31)


class TestCreditRiskCalcOutputFloorSummary:
    """End-to-end: CalculationResponse.output_floor_summary is the REAL run's
    own output-floor summary, not just a type-level pass-through.

    A real, unmocked pipeline run must actually populate this — the aggregator
    computes ``OutputFloorSummary`` only when the ``output_floor`` pack Feature
    is on (Basel 3.1) and the entity is in floor scope; ResultFormatter must
    carry it onto the response unchanged.
    """

    def test_basel_3_1_run_populates_output_floor_summary(self, tmp_path: Path) -> None:
        from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

        from rwa_calc.contracts.bundles import OutputFloorSummary

        write_mandatory_minimum(tmp_path)
        response = CreditRiskCalc(
            data_path=tmp_path,
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
            cache_dir=tmp_path / "cache",
        ).calculate()

        assert response.success is True
        assert isinstance(response.output_floor_summary, OutputFloorSummary)

    def test_crr_run_leaves_output_floor_summary_none(self, tmp_path: Path) -> None:
        """CRR has no output floor (Art. 92 para 2A is a Basel 3.1 concept)."""
        from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

        write_mandatory_minimum(tmp_path)
        response = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
            cache_dir=tmp_path / "cache",
        ).calculate()

        assert response.success is True
        assert response.output_floor_summary is None


class TestCreditRiskCalcCreateConfig:
    """Tests for CreditRiskCalc._create_config method."""

    def test_crr_config(self) -> None:
        """Should create CRR configuration."""
        from rwa_calc.contracts.config import CalculationConfig

        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        config = calc._create_config()

        assert isinstance(config, CalculationConfig)
        assert config.is_crr

    def test_basel_31_config(self) -> None:
        """Should create Basel 3.1 configuration."""
        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
        )
        config = calc._create_config()
        assert config.is_basel_3_1

    def test_irb_enabled(self) -> None:
        """Should enable IRB permissions when requested."""
        from rwa_calc.domain.enums import PermissionMode

        calc = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="irb",
        )
        config = calc._create_config()
        assert config.permission_mode == PermissionMode.IRB


class TestCreditRiskCalcCreateLoader:
    """Tests for CreditRiskCalc._create_loader method."""

    def test_parquet_loader(self, temp_valid_dir: Path) -> None:
        """Should create ParquetLoader for parquet format."""
        from rwa_calc.engine.loader import ParquetLoader

        calc = CreditRiskCalc(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            data_format="parquet",
        )
        loader = calc._create_loader()
        assert isinstance(loader, ParquetLoader)

    def test_csv_loader(self, temp_valid_dir: Path) -> None:
        """Should create CSVLoader for csv format."""
        from rwa_calc.engine.loader import CSVLoader

        calc = CreditRiskCalc(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            data_format="csv",
        )
        loader = calc._create_loader()
        assert isinstance(loader, CSVLoader)


# =============================================================================
# Module-Level Function Tests
# =============================================================================


class TestGetSupportedFrameworks:
    """Tests for get_supported_frameworks function."""

    def test_returns_frameworks_list(self) -> None:
        """Should return list of supported frameworks."""
        frameworks = get_supported_frameworks()
        assert isinstance(frameworks, list)
        assert len(frameworks) == 2

    def test_includes_crr(self) -> None:
        """Should include CRR framework."""
        frameworks = get_supported_frameworks()
        crr = next((f for f in frameworks if f["id"] == "CRR"), None)
        assert crr is not None
        assert "Basel 3.0" in crr["name"]

    def test_includes_basel_31(self) -> None:
        """Should include Basel 3.1 framework."""
        frameworks = get_supported_frameworks()
        basel = next((f for f in frameworks if f["id"] == "BASEL_3_1"), None)
        assert basel is not None
        assert "Basel 3.1" in basel["name"]


class TestGetDefaultConfig:
    """Tests for get_default_config function."""

    def test_crr_config(self) -> None:
        """Should return CRR default configuration."""
        config = get_default_config(
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert config["framework"] == "CRR"
        assert config["base_currency"] == "GBP"
        assert config["supporting_factors_enabled"] is True
        assert config["output_floor_enabled"] is False

    def test_basel_31_config(self) -> None:
        """Should return Basel 3.1 default configuration."""
        config = get_default_config(
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
        )
        assert config["framework"] == "BASEL_3_1"
        assert config["supporting_factors_enabled"] is False
        assert config["output_floor_enabled"] is True
