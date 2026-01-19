"""Unit tests for the API service module.

Tests cover:
- RWAService class
- create_service factory function
- quick_calculate convenience function
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from rwa_calc.api.models import (
    CalculationRequest,
    CalculationResponse,
    ValidationRequest,
    ValidationResponse,
)
from rwa_calc.api.service import (
    RWAService,
    create_service,
    quick_calculate,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_valid_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with all required parquet files."""
    # Create directory structure
    (tmp_path / "counterparty").mkdir()
    (tmp_path / "exposures").mkdir()
    (tmp_path / "collateral").mkdir()
    (tmp_path / "guarantee").mkdir()
    (tmp_path / "provision").mkdir()
    (tmp_path / "ratings").mkdir()
    (tmp_path / "mapping").mkdir()

    # Create minimal files with actual data
    empty_df = pl.DataFrame({"id": ["1"]})

    # Counterparty files
    empty_df.write_parquet(tmp_path / "counterparty" / "sovereign.parquet")
    empty_df.write_parquet(tmp_path / "counterparty" / "institution.parquet")
    empty_df.write_parquet(tmp_path / "counterparty" / "corporate.parquet")
    empty_df.write_parquet(tmp_path / "counterparty" / "retail.parquet")

    # Exposure files
    empty_df.write_parquet(tmp_path / "exposures" / "facilities.parquet")
    empty_df.write_parquet(tmp_path / "exposures" / "loans.parquet")
    empty_df.write_parquet(tmp_path / "exposures" / "contingents.parquet")
    empty_df.write_parquet(tmp_path / "exposures" / "facility_mapping.parquet")

    # CRM files
    empty_df.write_parquet(tmp_path / "collateral" / "collateral.parquet")
    empty_df.write_parquet(tmp_path / "guarantee" / "guarantee.parquet")
    empty_df.write_parquet(tmp_path / "provision" / "provision.parquet")

    # Ratings and mappings
    empty_df.write_parquet(tmp_path / "ratings" / "ratings.parquet")
    empty_df.write_parquet(tmp_path / "mapping" / "org_mapping.parquet")
    empty_df.write_parquet(tmp_path / "mapping" / "lending_mapping.parquet")

    return tmp_path


@pytest.fixture
def service() -> RWAService:
    """Create an RWAService instance."""
    return RWAService()


# =============================================================================
# RWAService Tests
# =============================================================================


class TestRWAServiceInit:
    """Tests for RWAService initialization."""

    def test_creates_with_default_components(self) -> None:
        """Should create service with default components."""
        service = RWAService()
        assert service._validator is not None
        assert service._formatter is not None


class TestRWAServiceValidateDataPath:
    """Tests for RWAService.validate_data_path method."""

    def test_valid_path(self, service: RWAService, temp_valid_dir: Path) -> None:
        """Should return valid response for valid path."""
        response = service.validate_data_path(
            ValidationRequest(data_path=temp_valid_dir)
        )
        assert isinstance(response, ValidationResponse)
        assert response.valid is True

    def test_invalid_path(self, service: RWAService, tmp_path: Path) -> None:
        """Should return invalid response for non-existent path."""
        response = service.validate_data_path(
            ValidationRequest(data_path=tmp_path / "nonexistent")
        )
        assert response.valid is False
        assert len(response.errors) > 0


class TestRWAServiceGetSupportedFrameworks:
    """Tests for RWAService.get_supported_frameworks method."""

    def test_returns_frameworks_list(self, service: RWAService) -> None:
        """Should return list of supported frameworks."""
        frameworks = service.get_supported_frameworks()

        assert isinstance(frameworks, list)
        assert len(frameworks) == 2

    def test_includes_crr(self, service: RWAService) -> None:
        """Should include CRR framework."""
        frameworks = service.get_supported_frameworks()
        crr = next((f for f in frameworks if f["id"] == "CRR"), None)

        assert crr is not None
        assert "Basel 3.0" in crr["name"]

    def test_includes_basel_31(self, service: RWAService) -> None:
        """Should include Basel 3.1 framework."""
        frameworks = service.get_supported_frameworks()
        basel = next((f for f in frameworks if f["id"] == "BASEL_3_1"), None)

        assert basel is not None
        assert "Basel 3.1" in basel["name"]


class TestRWAServiceGetDefaultConfig:
    """Tests for RWAService.get_default_config method."""

    def test_crr_config(self, service: RWAService) -> None:
        """Should return CRR default configuration."""
        config = service.get_default_config(
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )

        assert config["framework"] == "CRR"
        assert config["base_currency"] == "GBP"
        assert config["supporting_factors_enabled"] is True
        assert config["output_floor_enabled"] is False

    def test_basel_31_config(self, service: RWAService) -> None:
        """Should return Basel 3.1 default configuration."""
        config = service.get_default_config(
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
        )

        assert config["framework"] == "BASEL_3_1"
        assert config["supporting_factors_enabled"] is False
        assert config["output_floor_enabled"] is True


class TestRWAServiceCalculate:
    """Tests for RWAService.calculate method."""

    def test_invalid_path_returns_error(self, service: RWAService, tmp_path: Path) -> None:
        """Should return error response for invalid path."""
        request = CalculationRequest(
            data_path=tmp_path / "nonexistent",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )

        response = service.calculate(request)

        assert response.success is False
        assert len(response.errors) > 0

    def test_calculation_response_structure(
        self, service: RWAService, temp_valid_dir: Path
    ) -> None:
        """Should return properly structured response."""
        # Mock the pipeline to avoid full calculation
        mock_bundle = MagicMock()
        mock_bundle.results = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "rwa_final": [500000.0],
        })
        mock_bundle.sa_results = None
        mock_bundle.irb_results = None
        mock_bundle.slotting_results = None
        mock_bundle.floor_impact = None
        mock_bundle.summary_by_class = None
        mock_bundle.summary_by_approach = None
        mock_bundle.errors = []

        with patch.object(service, "_create_pipeline") as mock_pipeline:
            mock_pipeline.return_value.run.return_value = mock_bundle

            request = CalculationRequest(
                data_path=temp_valid_dir,
                framework="CRR",
                reporting_date=date(2024, 12, 31),
            )

            response = service.calculate(request)

            assert isinstance(response, CalculationResponse)
            assert response.framework == "CRR"
            assert response.reporting_date == date(2024, 12, 31)


class TestRWAServiceCreateConfig:
    """Tests for RWAService._create_config method."""

    def test_crr_config(self, service: RWAService) -> None:
        """Should create CRR configuration."""
        from rwa_calc.contracts.config import CalculationConfig

        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )

        config = service._create_config(request)

        assert isinstance(config, CalculationConfig)
        assert config.is_crr

    def test_basel_31_config(self, service: RWAService) -> None:
        """Should create Basel 3.1 configuration."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="BASEL_3_1",
            reporting_date=date(2027, 1, 1),
        )

        config = service._create_config(request)

        assert config.is_basel_3_1

    def test_irb_enabled(self, service: RWAService) -> None:
        """Should enable IRB permissions when requested."""
        request = CalculationRequest(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            enable_irb=True,
        )

        config = service._create_config(request)

        # IRB permissions should allow FIRB and AIRB
        from rwa_calc.domain.enums import ApproachType, ExposureClass
        assert config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )


class TestRWAServiceCreateLoader:
    """Tests for RWAService._create_loader method."""

    def test_parquet_loader(self, service: RWAService, temp_valid_dir: Path) -> None:
        """Should create ParquetLoader for parquet format."""
        from rwa_calc.engine.loader import ParquetLoader

        request = CalculationRequest(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            data_format="parquet",
        )

        loader = service._create_loader(request)

        assert isinstance(loader, ParquetLoader)

    def test_csv_loader(self, service: RWAService, temp_valid_dir: Path) -> None:
        """Should create CSVLoader for csv format."""
        from rwa_calc.engine.loader import CSVLoader

        request = CalculationRequest(
            data_path=temp_valid_dir,
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            data_format="csv",
        )

        loader = service._create_loader(request)

        assert isinstance(loader, CSVLoader)


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateService:
    """Tests for create_service factory function."""

    def test_creates_service_instance(self) -> None:
        """Should create RWAService instance."""
        service = create_service()
        assert isinstance(service, RWAService)


# =============================================================================
# Quick Calculate Tests
# =============================================================================


class TestQuickCalculate:
    """Tests for quick_calculate convenience function."""

    def test_invalid_path(self, tmp_path: Path) -> None:
        """Should return error for invalid path."""
        response = quick_calculate(
            data_path=tmp_path / "nonexistent",
            framework="CRR",
        )

        assert response.success is False

    def test_default_parameters(self, temp_valid_dir: Path) -> None:
        """Should use default parameters when not specified."""
        # Mock to avoid full calculation
        with patch.object(RWAService, "calculate") as mock_calc:
            mock_response = MagicMock()
            mock_response.success = True
            mock_calc.return_value = mock_response

            quick_calculate(temp_valid_dir)

            # Check default values were used
            call_args = mock_calc.call_args[0][0]
            assert call_args.framework == "CRR"
            assert call_args.enable_irb is False
            assert call_args.data_format == "parquet"
