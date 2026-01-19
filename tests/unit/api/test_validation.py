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
    RequiredFiles,
    get_required_files,
    validate_data_path,
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

    # Create minimal files
    empty_df = pl.DataFrame({"id": []})

    # Counterparty files (at least one required)
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
def temp_partial_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with only some required files."""
    # Create directory structure
    (tmp_path / "counterparty").mkdir()
    (tmp_path / "exposures").mkdir()

    empty_df = pl.DataFrame({"id": []})

    # Only create some files
    empty_df.write_parquet(tmp_path / "counterparty" / "corporate.parquet")
    empty_df.write_parquet(tmp_path / "exposures" / "facilities.parquet")

    return tmp_path


# =============================================================================
# RequiredFiles Tests
# =============================================================================


class TestRequiredFiles:
    """Tests for RequiredFiles configuration."""

    def test_parquet_format(self) -> None:
        """Should return parquet file paths."""
        required = RequiredFiles.for_format("parquet")
        assert all(f.endswith(".parquet") for f in required.mandatory)
        assert all(f.endswith(".parquet") for f in required.optional)

    def test_csv_format(self) -> None:
        """Should return csv file paths."""
        required = RequiredFiles.for_format("csv")
        assert all(f.endswith(".csv") for f in required.mandatory)
        assert all(f.endswith(".csv") for f in required.optional)

    def test_mandatory_files_include_core(self) -> None:
        """Mandatory files should include all core files."""
        required = RequiredFiles.for_format("parquet")
        mandatory = set(required.mandatory)

        # Check core exposure files
        assert "exposures/facilities.parquet" in mandatory
        assert "exposures/loans.parquet" in mandatory
        assert "exposures/contingents.parquet" in mandatory

        # Check CRM files
        assert "collateral/collateral.parquet" in mandatory
        assert "guarantee/guarantee.parquet" in mandatory

    def test_counterparty_files_included(self) -> None:
        """Counterparty files should be in mandatory list."""
        required = RequiredFiles.for_format("parquet")
        mandatory = set(required.mandatory)

        assert "counterparty/sovereign.parquet" in mandatory
        assert "counterparty/institution.parquet" in mandatory
        assert "counterparty/corporate.parquet" in mandatory
        assert "counterparty/retail.parquet" in mandatory


# =============================================================================
# DataPathValidator Tests
# =============================================================================


class TestDataPathValidator:
    """Tests for DataPathValidator class."""

    def test_validate_valid_directory(self, temp_valid_dir: Path) -> None:
        """Valid directory should pass validation."""
        validator = DataPathValidator()
        response = validator.validate(
            ValidationRequest(data_path=temp_valid_dir)
        )
        assert response.valid is True
        assert len(response.errors) == 0
        assert response.found_count > 0

    def test_validate_nonexistent_path(self, tmp_path: Path) -> None:
        """Non-existent path should fail validation."""
        validator = DataPathValidator()
        response = validator.validate(
            ValidationRequest(data_path=tmp_path / "nonexistent")
        )
        assert response.valid is False
        assert len(response.errors) > 0
        assert any("does not exist" in e.message for e in response.errors)

    def test_validate_file_not_directory(self, tmp_path: Path) -> None:
        """File path should fail validation."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        validator = DataPathValidator()
        response = validator.validate(
            ValidationRequest(data_path=file_path)
        )
        assert response.valid is False
        assert any("not a directory" in e.message for e in response.errors)

    def test_validate_partial_directory(self, temp_partial_dir: Path) -> None:
        """Partial directory should report missing files."""
        validator = DataPathValidator()
        response = validator.validate(
            ValidationRequest(data_path=temp_partial_dir)
        )
        assert response.valid is False
        assert response.missing_count > 0
        assert "exposures/loans.parquet" in response.files_missing

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
        empty_df.write_csv(tmp_path / "counterparty" / "corporate.csv")
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
        response = validator.validate(
            ValidationRequest(data_path=tmp_path, data_format="csv")
        )
        # Should pass with at least one counterparty file
        assert response.found_count > 0

    def test_validate_at_least_one_counterparty_required(self, tmp_path: Path) -> None:
        """Should require at least one counterparty file."""
        # Create directory structure without counterparty files
        (tmp_path / "counterparty").mkdir()
        (tmp_path / "exposures").mkdir()
        (tmp_path / "collateral").mkdir()
        (tmp_path / "guarantee").mkdir()
        (tmp_path / "provision").mkdir()
        (tmp_path / "ratings").mkdir()
        (tmp_path / "mapping").mkdir()

        empty_df = pl.DataFrame({"id": []})

        # Create all files except counterparty
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
        response = validator.validate(
            ValidationRequest(data_path=tmp_path)
        )
        assert response.valid is False
        assert any("counterparty" in e.message.lower() for e in response.errors)

    def test_validate_partial_counterparty_files_ok(self, temp_valid_dir: Path) -> None:
        """Should pass with only some counterparty files."""
        # Remove some counterparty files
        (temp_valid_dir / "counterparty" / "sovereign.parquet").unlink()
        (temp_valid_dir / "counterparty" / "institution.parquet").unlink()

        validator = DataPathValidator()
        response = validator.validate(
            ValidationRequest(data_path=temp_valid_dir)
        )
        # Should still pass with corporate and retail counterparty files
        assert response.valid is True


class TestDataPathValidatorCheckFile:
    """Tests for DataPathValidator.check_file_exists method."""

    def test_check_existing_file(self, temp_valid_dir: Path) -> None:
        """Should return True for existing file."""
        validator = DataPathValidator()
        exists, path = validator.check_file_exists(
            temp_valid_dir,
            "exposures/facilities.parquet",
        )
        assert exists is True
        assert path is not None

    def test_check_missing_file(self, temp_valid_dir: Path) -> None:
        """Should return False for missing file."""
        validator = DataPathValidator()
        exists, path = validator.check_file_exists(
            temp_valid_dir,
            "nonexistent/file.parquet",
        )
        assert exists is False
        assert path is None


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
        assert all(".parquet" in f for f in files)

    def test_csv_format(self) -> None:
        """Should return csv files."""
        files = get_required_files("csv")
        assert len(files) > 0
        assert all(".csv" in f for f in files)
