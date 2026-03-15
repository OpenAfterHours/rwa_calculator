"""Unit tests for the API validation module.

Tests cover:
- RequiredFiles configuration
- DataPathValidator class
- validate_data_path convenience function
- get_required_files convenience function
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api.models import ValidationRequest
from rwa_calc.api.validation import (
    DataPathValidator,
    get_required_files,
    validate_data_path,
)
from rwa_calc.config.data_sources import DataSourceRegistry

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

    # Create minimal files
    empty_df = pl.DataFrame({"id": []})

    # Counterparty file (mandatory)
    empty_df.write_parquet(tmp_path / "counterparty" / "counterparties.parquet")

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
def temp_partial_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with only some required files."""
    # Create directory structure
    (tmp_path / "counterparty").mkdir()
    (tmp_path / "exposures").mkdir()

    empty_df = pl.DataFrame({"id": []})

    # Only create some files
    empty_df.write_parquet(tmp_path / "counterparty" / "counterparties.parquet")
    empty_df.write_parquet(tmp_path / "exposures" / "facilities.parquet")

    return tmp_path


# =============================================================================
# RequiredFiles Tests
# =============================================================================


class TestDataSourceRegistry:
    """Tests for DataSourceRegistry configuration."""

    def test_parquet_format(self) -> None:
        """Should return parquet file paths."""
        registry = DataSourceRegistry()
        mandatory = registry.get_mandatory("parquet")
        optional = registry.get_optional("parquet")
        assert all(str(f).endswith(".parquet") for f in mandatory)
        assert all(str(f).endswith(".parquet") for f in optional)

    def test_csv_format(self) -> None:
        """Should return csv file paths."""
        registry = DataSourceRegistry()
        mandatory = registry.get_mandatory("csv")
        optional = registry.get_optional("csv")
        assert all(str(f).endswith(".csv") for f in mandatory)
        assert all(str(f).endswith(".csv") for f in optional)

    def test_mandatory_files_include_core(self) -> None:
        """Mandatory files should include all core files."""
        registry = DataSourceRegistry()
        mandatory = set(registry.get_mandatory("parquet"))

        # Check counterparty file
        assert Path("counterparty/counterparties.parquet") in mandatory

        # Check core exposure files
        assert Path("exposures/facilities.parquet") in mandatory
        assert Path("exposures/loans.parquet") in mandatory
        assert Path("exposures/facility_mapping.parquet") in mandatory

        # Check mapping files
        assert Path("mapping/lending_mapping.parquet") in mandatory

    def test_optional_files_include_crm(self) -> None:
        """Optional files should include CRM and other optional files."""
        registry = DataSourceRegistry()
        optional = set(registry.get_optional("parquet"))

        # Check optional CRM files
        assert Path("exposures/contingents.parquet") in optional
        assert Path("collateral/collateral.parquet") in optional
        assert Path("guarantee/guarantee.parquet") in optional
        assert Path("provision/provision.parquet") in optional
        assert Path("ratings/ratings.parquet") in optional

        # Check optional mapping files
        assert Path("mapping/org_mapping.parquet") in optional

    def test_counterparty_file_is_mandatory(self) -> None:
        """Counterparty file should be mandatory."""
        registry = DataSourceRegistry()
        source = registry.get_by_id("counterparties")
        assert source is not None
        from rwa_calc.config.data_sources import RequirementLevel

        assert source.requirement == RequirementLevel.MANDATORY


# =============================================================================
# DataPathValidator Tests
# =============================================================================


class TestDataPathValidator:
    """Tests for DataPathValidator class."""

    def test_validate_valid_directory(self, temp_valid_dir: Path) -> None:
        """Valid directory should pass validation."""
        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=temp_valid_dir))
        assert response.valid is True
        assert len(response.errors) == 0
        assert response.found_count > 0

    def test_validate_nonexistent_path(self, tmp_path: Path) -> None:
        """Non-existent path should fail validation."""
        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=tmp_path / "nonexistent"))
        assert response.valid is False
        assert len(response.errors) > 0
        assert any("does not exist" in e.message for e in response.errors)

    def test_validate_file_not_directory(self, tmp_path: Path) -> None:
        """File path should fail validation."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=file_path))
        assert response.valid is False
        assert any("not a directory" in e.message for e in response.errors)

    def test_validate_partial_directory(self, temp_partial_dir: Path) -> None:
        """Partial directory should report missing files."""
        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=temp_partial_dir))
        assert response.valid is False
        assert response.missing_count > 0
        assert Path("exposures/loans.parquet") in response.files_missing

    def test_validate_csv_format(self, tmp_path: Path) -> None:
        """Should validate CSV format files."""
        # Create CSV directory structure
        (tmp_path / "counterparty").mkdir()
        (tmp_path / "exposures").mkdir()
        (tmp_path / "collateral").mkdir()
        (tmp_path / "guarantee").mkdir()
        (tmp_path / "provision").mkdir()
        (tmp_path / "ratings").mkdir()
        (tmp_path / "mapping").mkdir()

        empty_df = pl.DataFrame({"id": []})

        # Create CSV files
        empty_df.write_csv(tmp_path / "counterparty" / "counterparties.csv")
        empty_df.write_csv(tmp_path / "exposures" / "facilities.csv")
        empty_df.write_csv(tmp_path / "exposures" / "loans.csv")
        empty_df.write_csv(tmp_path / "exposures" / "contingents.csv")
        empty_df.write_csv(tmp_path / "exposures" / "facility_mapping.csv")
        empty_df.write_csv(tmp_path / "collateral" / "collateral.csv")
        empty_df.write_csv(tmp_path / "guarantee" / "guarantee.csv")
        empty_df.write_csv(tmp_path / "provision" / "provision.csv")
        empty_df.write_csv(tmp_path / "ratings" / "ratings.csv")
        empty_df.write_csv(tmp_path / "mapping" / "org_mapping.csv")
        empty_df.write_csv(tmp_path / "mapping" / "lending_mapping.csv")

        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=tmp_path, data_format="csv"))
        # Should pass with at least one counterparty file
        assert response.found_count > 0

    def test_validate_missing_counterparty_file_fails(self, tmp_path: Path) -> None:
        """Should fail when counterparties file is missing."""
        # Create directory structure without counterparty file
        (tmp_path / "counterparty").mkdir()
        (tmp_path / "exposures").mkdir()
        (tmp_path / "collateral").mkdir()
        (tmp_path / "guarantee").mkdir()
        (tmp_path / "provision").mkdir()
        (tmp_path / "ratings").mkdir()
        (tmp_path / "mapping").mkdir()

        empty_df = pl.DataFrame({"id": []})

        # Create all files except counterparties
        empty_df.write_parquet(tmp_path / "exposures" / "facilities.parquet")
        empty_df.write_parquet(tmp_path / "exposures" / "loans.parquet")
        empty_df.write_parquet(tmp_path / "exposures" / "contingents.parquet")
        empty_df.write_parquet(tmp_path / "exposures" / "facility_mapping.parquet")
        empty_df.write_parquet(tmp_path / "collateral" / "collateral.parquet")
        empty_df.write_parquet(tmp_path / "guarantee" / "guarantee.parquet")
        empty_df.write_parquet(tmp_path / "provision" / "provision.parquet")
        empty_df.write_parquet(tmp_path / "ratings" / "ratings.parquet")
        empty_df.write_parquet(tmp_path / "mapping" / "org_mapping.parquet")
        empty_df.write_parquet(tmp_path / "mapping" / "lending_mapping.parquet")

        validator = DataPathValidator()
        response = validator.validate(ValidationRequest(data_path=tmp_path))
        assert response.valid is False
        assert Path("counterparty/counterparties.parquet") in response.files_missing




# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestValidateDataPath:
    """Tests for validate_data_path convenience function."""

    def test_validate_valid_path(self, temp_valid_dir: Path) -> None:
        """Should return valid response for valid path."""
        response = validate_data_path(temp_valid_dir)
        assert response.valid is True

    def test_validate_with_string_path(self, temp_valid_dir: Path) -> None:
        """Should accept string path."""
        response = validate_data_path(str(temp_valid_dir))
        assert response.valid is True

    def test_validate_csv_format(self, temp_valid_dir: Path) -> None:
        """Should validate with csv format."""
        response = validate_data_path(temp_valid_dir, data_format="csv")
        # Will fail because files are parquet, not csv
        assert response.valid is False


class TestGetRequiredFiles:
    """Tests for get_required_files convenience function."""

    def test_parquet_format(self) -> None:
        """Should return parquet files."""
        files = get_required_files("parquet")
        assert len(files) > 0
        assert all(".parquet" in str(f) for f in files)

    def test_csv_format(self) -> None:
        """Should return csv files."""
        files = get_required_files("csv")
        assert len(files) > 0
        assert all(".csv" in str(f) for f in files)
