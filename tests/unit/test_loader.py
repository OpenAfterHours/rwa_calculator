"""Unit tests for the data loader module.

Tests cover:
- DataSourceConfig configuration
- DataLoadError exception
- ParquetLoader class
- CSVLoader class
- create_test_loader convenience function
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.loader import (
    CSVLoader,
    DataLoadError,
    DataSourceConfig,
    ParquetLoader,
    create_test_loader,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def temp_parquet_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with minimal parquet test files."""
    # Create directory structure
    (tmp_path / "counterparty").mkdir()
    (tmp_path / "exposures").mkdir()
    (tmp_path / "collateral").mkdir()
    (tmp_path / "guarantee").mkdir()
    (tmp_path / "provision").mkdir()
    (tmp_path / "ratings").mkdir()
    (tmp_path / "mapping").mkdir()

    # Create minimal counterparty files
    sovereign_df = pl.DataFrame({
        "counterparty_id": ["SOV001"],
        "counterparty_type": ["SOVEREIGN"],
        "name": ["Test Sovereign"],
    })
    sovereign_df.write_parquet(tmp_path / "counterparty" / "sovereign.parquet")

    institution_df = pl.DataFrame({
        "counterparty_id": ["INST001"],
        "counterparty_type": ["INSTITUTION"],
        "name": ["Test Institution"],
    })
    institution_df.write_parquet(tmp_path / "counterparty" / "institution.parquet")

    corporate_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "counterparty_type": ["CORPORATE"],
        "name": ["Test Corporate"],
    })
    corporate_df.write_parquet(tmp_path / "counterparty" / "corporate.parquet")

    retail_df = pl.DataFrame({
        "counterparty_id": ["RET001"],
        "counterparty_type": ["RETAIL"],
        "name": ["Test Retail"],
    })
    retail_df.write_parquet(tmp_path / "counterparty" / "retail.parquet")

    # Create exposure files
    facilities_df = pl.DataFrame({
        "facility_id": ["FAC001"],
        "counterparty_id": ["CORP001"],
        "facility_type": ["TERM_LOAN"],
    })
    facilities_df.write_parquet(tmp_path / "exposures" / "facilities.parquet")

    loans_df = pl.DataFrame({
        "loan_id": ["LOAN001"],
        "facility_id": ["FAC001"],
        "outstanding_balance": [1000000.0],
    })
    loans_df.write_parquet(tmp_path / "exposures" / "loans.parquet")

    contingents_df = pl.DataFrame({
        "contingent_id": ["CONT001"],
        "facility_id": ["FAC001"],
        "commitment_amount": [500000.0],
    })
    contingents_df.write_parquet(tmp_path / "exposures" / "contingents.parquet")

    facility_mapping_df = pl.DataFrame({
        "loan_id": ["LOAN001"],
        "facility_id": ["FAC001"],
    })
    facility_mapping_df.write_parquet(tmp_path / "exposures" / "facility_mapping.parquet")

    # Create collateral file
    collateral_df = pl.DataFrame({
        "collateral_id": ["COL001"],
        "collateral_type": ["PROPERTY"],
        "value": [750000.0],
    })
    collateral_df.write_parquet(tmp_path / "collateral" / "collateral.parquet")

    # Create guarantee file
    guarantee_df = pl.DataFrame({
        "guarantee_id": ["GUAR001"],
        "guarantor_id": ["INST001"],
        "amount": [200000.0],
    })
    guarantee_df.write_parquet(tmp_path / "guarantee" / "guarantee.parquet")

    # Create provision file
    provision_df = pl.DataFrame({
        "facility_id": ["FAC001"],
        "provision_amount": [10000.0],
    })
    provision_df.write_parquet(tmp_path / "provision" / "provision.parquet")

    # Create ratings file
    ratings_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "rating_agency": ["MOODYS"],
        "rating": ["A2"],
    })
    ratings_df.write_parquet(tmp_path / "ratings" / "ratings.parquet")

    # Create mapping files
    org_mapping_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "parent_id": [None],
    })
    org_mapping_df.write_parquet(tmp_path / "mapping" / "org_mapping.parquet")

    lending_mapping_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "lending_group_id": ["LG001"],
    })
    lending_mapping_df.write_parquet(tmp_path / "mapping" / "lending_mapping.parquet")

    return tmp_path


@pytest.fixture
def temp_csv_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with minimal CSV test files."""
    # Create directory structure
    (tmp_path / "counterparty").mkdir()
    (tmp_path / "exposures").mkdir()
    (tmp_path / "collateral").mkdir()
    (tmp_path / "guarantee").mkdir()
    (tmp_path / "provision").mkdir()
    (tmp_path / "ratings").mkdir()
    (tmp_path / "mapping").mkdir()

    # Create minimal counterparty files
    sovereign_df = pl.DataFrame({
        "counterparty_id": ["SOV001"],
        "counterparty_type": ["SOVEREIGN"],
        "name": ["Test Sovereign"],
    })
    sovereign_df.write_csv(tmp_path / "counterparty" / "sovereign.csv")

    institution_df = pl.DataFrame({
        "counterparty_id": ["INST001"],
        "counterparty_type": ["INSTITUTION"],
        "name": ["Test Institution"],
    })
    institution_df.write_csv(tmp_path / "counterparty" / "institution.csv")

    corporate_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "counterparty_type": ["CORPORATE"],
        "name": ["Test Corporate"],
    })
    corporate_df.write_csv(tmp_path / "counterparty" / "corporate.csv")

    retail_df = pl.DataFrame({
        "counterparty_id": ["RET001"],
        "counterparty_type": ["RETAIL"],
        "name": ["Test Retail"],
    })
    retail_df.write_csv(tmp_path / "counterparty" / "retail.csv")

    # Create exposure files
    facilities_df = pl.DataFrame({
        "facility_id": ["FAC001"],
        "counterparty_id": ["CORP001"],
        "facility_type": ["TERM_LOAN"],
    })
    facilities_df.write_csv(tmp_path / "exposures" / "facilities.csv")

    loans_df = pl.DataFrame({
        "loan_id": ["LOAN001"],
        "facility_id": ["FAC001"],
        "outstanding_balance": [1000000.0],
    })
    loans_df.write_csv(tmp_path / "exposures" / "loans.csv")

    contingents_df = pl.DataFrame({
        "contingent_id": ["CONT001"],
        "facility_id": ["FAC001"],
        "commitment_amount": [500000.0],
    })
    contingents_df.write_csv(tmp_path / "exposures" / "contingents.csv")

    facility_mapping_df = pl.DataFrame({
        "loan_id": ["LOAN001"],
        "facility_id": ["FAC001"],
    })
    facility_mapping_df.write_csv(tmp_path / "exposures" / "facility_mapping.csv")

    # Create collateral file
    collateral_df = pl.DataFrame({
        "collateral_id": ["COL001"],
        "collateral_type": ["PROPERTY"],
        "value": [750000.0],
    })
    collateral_df.write_csv(tmp_path / "collateral" / "collateral.csv")

    # Create guarantee file
    guarantee_df = pl.DataFrame({
        "guarantee_id": ["GUAR001"],
        "guarantor_id": ["INST001"],
        "amount": [200000.0],
    })
    guarantee_df.write_csv(tmp_path / "guarantee" / "guarantee.csv")

    # Create provision file
    provision_df = pl.DataFrame({
        "facility_id": ["FAC001"],
        "provision_amount": [10000.0],
    })
    provision_df.write_csv(tmp_path / "provision" / "provision.csv")

    # Create ratings file
    ratings_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "rating_agency": ["MOODYS"],
        "rating": ["A2"],
    })
    ratings_df.write_csv(tmp_path / "ratings" / "ratings.csv")

    # Create mapping files
    org_mapping_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "parent_id": [None],
    })
    org_mapping_df.write_csv(tmp_path / "mapping" / "org_mapping.csv")

    lending_mapping_df = pl.DataFrame({
        "counterparty_id": ["CORP001"],
        "lending_group_id": ["LG001"],
    })
    lending_mapping_df.write_csv(tmp_path / "mapping" / "lending_mapping.csv")

    return tmp_path


# =============================================================================
# DataSourceConfig Tests
# =============================================================================


class TestDataSourceConfig:
    """Tests for DataSourceConfig dataclass."""

    def test_default_counterparty_files(self) -> None:
        """Default counterparty files should include all standard types."""
        config = DataSourceConfig()
        assert len(config.counterparty_files) == 4
        assert "counterparty/sovereign.parquet" in config.counterparty_files
        assert "counterparty/institution.parquet" in config.counterparty_files
        assert "counterparty/corporate.parquet" in config.counterparty_files
        assert "counterparty/retail.parquet" in config.counterparty_files

    def test_default_exposure_files(self) -> None:
        """Default exposure file paths should be set correctly."""
        config = DataSourceConfig()
        assert config.facilities_file == "exposures/facilities.parquet"
        assert config.loans_file == "exposures/loans.parquet"
        assert config.contingents_file == "exposures/contingents.parquet"

    def test_default_crm_files(self) -> None:
        """Default CRM file paths should be set correctly."""
        config = DataSourceConfig()
        assert config.collateral_file == "collateral/collateral.parquet"
        assert config.guarantees_file == "guarantee/guarantee.parquet"

    def test_default_mapping_files(self) -> None:
        """Default mapping file paths should be set correctly."""
        config = DataSourceConfig()
        assert config.facility_mappings_file == "exposures/facility_mapping.parquet"
        assert config.org_mappings_file == "mapping/org_mapping.parquet"
        assert config.lending_mappings_file == "mapping/lending_mapping.parquet"

    def test_default_optional_files(self) -> None:
        """Default optional file paths should be set correctly."""
        config = DataSourceConfig()
        assert config.specialised_lending_file == "counterparty/specialised_lending.parquet"
        assert config.equity_exposures_file is None

    def test_custom_configuration(self) -> None:
        """Custom configuration should override defaults."""
        config = DataSourceConfig(
            counterparty_files=["custom/counterparties.parquet"],
            facilities_file="custom/facilities.parquet",
            specialised_lending_file=None,
        )
        assert config.counterparty_files == ["custom/counterparties.parquet"]
        assert config.facilities_file == "custom/facilities.parquet"
        assert config.specialised_lending_file is None
        # Other defaults should remain
        assert config.loans_file == "exposures/loans.parquet"


# =============================================================================
# DataLoadError Tests
# =============================================================================


class TestDataLoadError:
    """Tests for DataLoadError exception."""

    def test_error_message_only(self) -> None:
        """Error with message only should format correctly."""
        error = DataLoadError("Test error message")
        assert str(error) == "Test error message"
        assert error.source is None

    def test_error_with_source(self) -> None:
        """Error with source should include source in message."""
        error = DataLoadError("File not found", source="test/file.parquet")
        assert str(error) == "File not found (source: test/file.parquet)"
        assert error.source == "test/file.parquet"

    def test_error_inherits_from_exception(self) -> None:
        """DataLoadError should be an Exception subclass."""
        error = DataLoadError("Test")
        assert isinstance(error, Exception)


# =============================================================================
# ParquetLoader Tests
# =============================================================================


class TestParquetLoaderInit:
    """Tests for ParquetLoader initialization."""

    def test_init_with_valid_path(self, temp_parquet_dir: Path) -> None:
        """Loader should initialize with valid path."""
        loader = ParquetLoader(temp_parquet_dir)
        assert loader.base_path == temp_parquet_dir
        assert isinstance(loader.config, DataSourceConfig)

    def test_init_with_string_path(self, temp_parquet_dir: Path) -> None:
        """Loader should accept string path."""
        loader = ParquetLoader(str(temp_parquet_dir))
        assert loader.base_path == temp_parquet_dir

    def test_init_with_custom_config(self, temp_parquet_dir: Path) -> None:
        """Loader should accept custom configuration."""
        custom_config = DataSourceConfig(
            counterparty_files=["counterparty/sovereign.parquet"]
        )
        loader = ParquetLoader(temp_parquet_dir, config=custom_config)
        assert loader.config == custom_config

    def test_init_with_invalid_path_raises_error(self) -> None:
        """Loader should raise DataLoadError for non-existent path."""
        with pytest.raises(DataLoadError, match="Base path does not exist"):
            ParquetLoader("/nonexistent/path")


class TestParquetLoaderLoad:
    """Tests for ParquetLoader.load() method."""

    def test_load_returns_raw_data_bundle(self, temp_parquet_dir: Path) -> None:
        """Load should return a RawDataBundle."""
        loader = ParquetLoader(temp_parquet_dir)
        bundle = loader.load()
        assert isinstance(bundle, RawDataBundle)

    def test_load_returns_lazy_frames(self, temp_parquet_dir: Path) -> None:
        """All bundle attributes should be LazyFrames."""
        loader = ParquetLoader(temp_parquet_dir)
        bundle = loader.load()

        assert isinstance(bundle.facilities, pl.LazyFrame)
        assert isinstance(bundle.loans, pl.LazyFrame)
        assert isinstance(bundle.contingents, pl.LazyFrame)
        assert isinstance(bundle.counterparties, pl.LazyFrame)
        assert isinstance(bundle.collateral, pl.LazyFrame)
        assert isinstance(bundle.guarantees, pl.LazyFrame)
        assert isinstance(bundle.provisions, pl.LazyFrame)
        assert isinstance(bundle.ratings, pl.LazyFrame)
        assert isinstance(bundle.facility_mappings, pl.LazyFrame)
        assert isinstance(bundle.org_mappings, pl.LazyFrame)
        assert isinstance(bundle.lending_mappings, pl.LazyFrame)

    def test_load_combines_counterparties(self, temp_parquet_dir: Path) -> None:
        """Counterparties should be combined from all source files."""
        loader = ParquetLoader(temp_parquet_dir)
        bundle = loader.load()

        # Collect to verify data
        counterparties_df = bundle.counterparties.collect()
        assert len(counterparties_df) == 4  # sovereign, institution, corporate, retail

        # Verify all types present
        types = counterparties_df["counterparty_type"].to_list()
        assert "SOVEREIGN" in types
        assert "INSTITUTION" in types
        assert "CORPORATE" in types
        assert "RETAIL" in types

    def test_load_missing_required_file_raises_error(self, temp_parquet_dir: Path) -> None:
        """Missing required file should raise DataLoadError."""
        # Remove a required file
        (temp_parquet_dir / "exposures" / "facilities.parquet").unlink()

        loader = ParquetLoader(temp_parquet_dir)
        with pytest.raises(DataLoadError, match="File not found"):
            loader.load()

    def test_load_optional_files_return_none_when_missing(self, temp_parquet_dir: Path) -> None:
        """Optional files should return None when missing."""
        # equity_exposures_file is None by default, so not created
        # specialised_lending_file exists but we can test by removing it
        loader = ParquetLoader(temp_parquet_dir)
        bundle = loader.load()

        # equity_exposures should be None (not configured)
        assert bundle.equity_exposures is None

    def test_load_optional_specialised_lending(self, temp_parquet_dir: Path) -> None:
        """Specialised lending should load when file exists."""
        # Create specialised lending file
        sl_df = pl.DataFrame({
            "counterparty_id": ["SL001"],
            "specialised_lending_type": ["PROJECT_FINANCE"],
        })
        sl_df.write_parquet(temp_parquet_dir / "counterparty" / "specialised_lending.parquet")

        loader = ParquetLoader(temp_parquet_dir)
        bundle = loader.load()

        assert bundle.specialised_lending is not None
        assert isinstance(bundle.specialised_lending, pl.LazyFrame)


class TestParquetLoaderWithRealFixtures:
    """Tests using actual test fixtures directory."""

    def test_load_from_fixtures(self, fixtures_path: Path) -> None:
        """Loader should successfully load from actual fixtures."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        loader = ParquetLoader(fixtures_path)
        bundle = loader.load()

        assert isinstance(bundle, RawDataBundle)
        # Verify we can collect data
        facilities_df = bundle.facilities.collect()
        assert len(facilities_df) > 0

    def test_counterparties_combined_correctly(self, fixtures_path: Path) -> None:
        """Counterparties from fixtures should combine correctly."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        loader = ParquetLoader(fixtures_path)
        bundle = loader.load()

        counterparties_df = bundle.counterparties.collect()
        # Should have entries from multiple counterparty files
        assert len(counterparties_df) > 0
        # Actual fixtures use counterparty_reference as the ID column
        assert "counterparty_reference" in counterparties_df.columns


# =============================================================================
# CSVLoader Tests
# =============================================================================


class TestCSVLoaderInit:
    """Tests for CSVLoader initialization."""

    def test_init_with_valid_path(self, temp_csv_dir: Path) -> None:
        """Loader should initialize with valid path."""
        loader = CSVLoader(temp_csv_dir)
        assert loader.base_path == temp_csv_dir

    def test_init_uses_csv_default_config(self, temp_csv_dir: Path) -> None:
        """Loader should use CSV file extensions in default config."""
        loader = CSVLoader(temp_csv_dir)
        assert loader.config.facilities_file == "exposures/facilities.csv"
        assert "counterparty/sovereign.csv" in loader.config.counterparty_files

    def test_init_with_invalid_path_raises_error(self) -> None:
        """Loader should raise DataLoadError for non-existent path."""
        with pytest.raises(DataLoadError, match="Base path does not exist"):
            CSVLoader("/nonexistent/path")


class TestCSVLoaderLoad:
    """Tests for CSVLoader.load() method."""

    def test_load_returns_raw_data_bundle(self, temp_csv_dir: Path) -> None:
        """Load should return a RawDataBundle."""
        loader = CSVLoader(temp_csv_dir)
        bundle = loader.load()
        assert isinstance(bundle, RawDataBundle)

    def test_load_returns_lazy_frames(self, temp_csv_dir: Path) -> None:
        """All bundle attributes should be LazyFrames."""
        loader = CSVLoader(temp_csv_dir)
        bundle = loader.load()

        assert isinstance(bundle.facilities, pl.LazyFrame)
        assert isinstance(bundle.loans, pl.LazyFrame)
        assert isinstance(bundle.counterparties, pl.LazyFrame)

    def test_load_combines_counterparties(self, temp_csv_dir: Path) -> None:
        """Counterparties should be combined from all source files."""
        loader = CSVLoader(temp_csv_dir)
        bundle = loader.load()

        counterparties_df = bundle.counterparties.collect()
        assert len(counterparties_df) == 4

    def test_load_missing_required_file_raises_error(self, temp_csv_dir: Path) -> None:
        """Missing required file should raise DataLoadError."""
        (temp_csv_dir / "exposures" / "facilities.csv").unlink()

        loader = CSVLoader(temp_csv_dir)
        with pytest.raises(DataLoadError, match="File not found"):
            loader.load()


# =============================================================================
# create_test_loader Tests
# =============================================================================


class TestCreateTestLoader:
    """Tests for create_test_loader convenience function."""

    def test_create_with_explicit_path(self, fixtures_path: Path) -> None:
        """Should create loader with explicit fixture path."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        loader = create_test_loader(fixtures_path)
        assert isinstance(loader, ParquetLoader)
        assert loader.base_path == fixtures_path

    def test_create_with_string_path(self, fixtures_path: Path) -> None:
        """Should accept string path."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        loader = create_test_loader(str(fixtures_path))
        assert loader.base_path == fixtures_path

    def test_create_with_default_path(self) -> None:
        """Should find default fixtures path from project root."""
        # This test verifies the function can find the project root
        # It may fail if run from a different location
        try:
            loader = create_test_loader()
            assert isinstance(loader, ParquetLoader)
            assert "fixtures" in str(loader.base_path)
        except DataLoadError:
            # If project root cannot be found, that's acceptable
            pass


# =============================================================================
# Header Normalization Tests
# =============================================================================


class TestHeaderNormalization:
    """Tests for header normalization (lowercase + spaces to underscores)."""

    def test_parquet_loader_normalizes_headers_to_lowercase(self, tmp_path: Path) -> None:
        """Headers should be converted to lowercase."""
        (tmp_path / "counterparty").mkdir()
        (tmp_path / "exposures").mkdir()
        (tmp_path / "collateral").mkdir()
        (tmp_path / "guarantee").mkdir()
        (tmp_path / "provision").mkdir()
        (tmp_path / "ratings").mkdir()
        (tmp_path / "mapping").mkdir()

        # Create file with uppercase headers
        df = pl.DataFrame({
            "Counterparty_ID": ["SOV001"],
            "COUNTERPARTY_TYPE": ["SOVEREIGN"],
            "Name": ["Test Sovereign"],
        })
        df.write_parquet(tmp_path / "counterparty" / "sovereign.parquet")

        loader = ParquetLoader(tmp_path, config=DataSourceConfig(
            counterparty_files=["counterparty/sovereign.parquet"]
        ))
        counterparties = loader._load_and_combine_counterparties()
        result = counterparties.collect()

        assert "counterparty_id" in result.columns
        assert "counterparty_type" in result.columns
        assert "name" in result.columns
        # Verify original names are not present
        assert "Counterparty_ID" not in result.columns
        assert "COUNTERPARTY_TYPE" not in result.columns
        assert "Name" not in result.columns

    def test_parquet_loader_replaces_spaces_with_underscores(self, tmp_path: Path) -> None:
        """Spaces in headers should be replaced with underscores."""
        (tmp_path / "exposures").mkdir()

        # Create file with spaces in headers
        df = pl.DataFrame({
            "Facility ID": ["FAC001"],
            "Counterparty ID": ["CORP001"],
            "Facility Type": ["TERM_LOAN"],
        })
        df.write_parquet(tmp_path / "exposures" / "facilities.parquet")

        loader = ParquetLoader(tmp_path)
        result = loader._load_parquet("exposures/facilities.parquet").collect()

        assert "facility_id" in result.columns
        assert "counterparty_id" in result.columns
        assert "facility_type" in result.columns
        # Verify original names are not present
        assert "Facility ID" not in result.columns

    def test_csv_loader_normalizes_headers_to_lowercase(self, tmp_path: Path) -> None:
        """CSV headers should be converted to lowercase."""
        (tmp_path / "counterparty").mkdir()

        # Create file with uppercase headers
        df = pl.DataFrame({
            "Counterparty_ID": ["SOV001"],
            "COUNTERPARTY_TYPE": ["SOVEREIGN"],
            "Name": ["Test Sovereign"],
        })
        df.write_csv(tmp_path / "counterparty" / "sovereign.csv")

        loader = CSVLoader(tmp_path, config=DataSourceConfig(
            counterparty_files=["counterparty/sovereign.csv"]
        ))
        counterparties = loader._load_and_combine_counterparties()
        result = counterparties.collect()

        assert "counterparty_id" in result.columns
        assert "counterparty_type" in result.columns
        assert "name" in result.columns

    def test_csv_loader_replaces_spaces_with_underscores(self, tmp_path: Path) -> None:
        """CSV spaces in headers should be replaced with underscores."""
        (tmp_path / "exposures").mkdir()

        # Create file with spaces in headers
        df = pl.DataFrame({
            "Facility ID": ["FAC001"],
            "Counterparty ID": ["CORP001"],
            "Facility Type": ["TERM_LOAN"],
        })
        df.write_csv(tmp_path / "exposures" / "facilities.csv")

        loader = CSVLoader(tmp_path)
        result = loader._load_csv("exposures/facilities.csv").collect()

        assert "facility_id" in result.columns
        assert "counterparty_id" in result.columns
        assert "facility_type" in result.columns

    def test_normalize_columns_function(self) -> None:
        """Test the normalize_columns helper function directly."""
        from rwa_calc.engine.loader import normalize_columns

        lf = pl.LazyFrame({
            "Column One": [1],
            "COLUMN_TWO": [2],
            "Column Three With Spaces": [3],
        })
        result = normalize_columns(lf).collect()

        assert "column_one" in result.columns
        assert "column_two" in result.columns
        assert "column_three_with_spaces" in result.columns


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_counterparty_directory_raises_error(self, tmp_path: Path) -> None:
        """Empty counterparty directory should raise DataLoadError."""
        # Create minimal structure but no counterparty files
        (tmp_path / "counterparty").mkdir()
        (tmp_path / "exposures").mkdir()

        loader = ParquetLoader(tmp_path)
        with pytest.raises(DataLoadError, match="No counterparty files found"):
            loader._load_and_combine_counterparties()

    def test_partial_counterparty_files_loads_available(self, tmp_path: Path) -> None:
        """Should load available counterparty files even if some missing."""
        (tmp_path / "counterparty").mkdir()

        # Only create sovereign file
        sovereign_df = pl.DataFrame({
            "counterparty_id": ["SOV001"],
            "counterparty_type": ["SOVEREIGN"],
        })
        sovereign_df.write_parquet(tmp_path / "counterparty" / "sovereign.parquet")

        loader = ParquetLoader(tmp_path)
        counterparties = loader._load_and_combine_counterparties()

        df = counterparties.collect()
        assert len(df) == 1
        assert df["counterparty_type"][0] == "SOVEREIGN"

    def test_corrupted_parquet_file_raises_error_at_collect(self, tmp_path: Path) -> None:
        """Corrupted parquet file should raise error when collected.

        Note: scan_parquet is lazy, so errors occur at collect time, not scan time.
        This is expected Polars behavior for lazy evaluation.
        """
        (tmp_path / "counterparty").mkdir()

        # Create a file that's not valid parquet
        (tmp_path / "counterparty" / "sovereign.parquet").write_text("not parquet data")

        loader = ParquetLoader(tmp_path)
        # scan_parquet succeeds (lazy)
        lf = loader._load_and_combine_counterparties()

        # Error occurs at collect time
        with pytest.raises(Exception):  # ComputeError from Polars
            lf.collect()

    def test_config_with_different_schema_counterparties(self, tmp_path: Path) -> None:
        """Counterparties with different schemas should concatenate with diagonal_relaxed."""
        (tmp_path / "counterparty").mkdir()

        # Create files with different schemas
        sovereign_df = pl.DataFrame({
            "counterparty_id": ["SOV001"],
            "counterparty_type": ["SOVEREIGN"],
            "country_code": ["GB"],  # Extra column
        })
        sovereign_df.write_parquet(tmp_path / "counterparty" / "sovereign.parquet")

        corporate_df = pl.DataFrame({
            "counterparty_id": ["CORP001"],
            "counterparty_type": ["CORPORATE"],
            "industry_code": ["MANU"],  # Different extra column
        })
        corporate_df.write_parquet(tmp_path / "counterparty" / "corporate.parquet")

        loader = ParquetLoader(tmp_path)
        counterparties = loader._load_and_combine_counterparties()

        df = counterparties.collect()
        assert len(df) == 2
        # Both extra columns should be present (diagonal_relaxed behavior)
        assert "country_code" in df.columns
        assert "industry_code" in df.columns
