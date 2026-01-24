"""
Data loader implementations for the RWA calculator.

Provides concrete implementations of LoaderProtocol for loading
exposure data from various sources (Parquet, CSV, databases).

Classes:
    ParquetLoader: Load data from Parquet files
    CSVLoader: Load data from CSV files

Usage:
    from rwa_calc.engine.loader import ParquetLoader

    loader = ParquetLoader(base_path="/path/to/data")
    raw_data = loader.load()

The loader returns a RawDataBundle containing all required LazyFrames
for the calculation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle

if TYPE_CHECKING:
    pass


def normalize_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Normalize column names to lowercase with underscores.

    Converts all column names to lowercase and replaces spaces with underscores.
    This ensures consistent column naming regardless of input data formatting.

    Args:
        lf: LazyFrame with columns to normalize

    Returns:
        LazyFrame with normalized column names
    """
    return lf.rename(lambda col: col.lower().replace(" ", "_"))


@dataclass
class DataSourceConfig:
    """
    Configuration for data source paths.

    Defines the expected file paths relative to a base directory.
    Supports both standard fixture layout and custom layouts.

    Attributes:
        counterparty_files: List of counterparty source files to combine
        facilities_file: Path to facilities data
        loans_file: Path to loans data
        contingents_file: Path to contingent/off-balance sheet data
        collateral_file: Path to collateral data
        guarantees_file: Path to guarantees data
        provisions_file: Path to provisions data
        ratings_file: Path to ratings data
        facility_mappings_file: Path to facility hierarchy mappings
        org_mappings_file: Path to organisational hierarchy mappings
        lending_mappings_file: Path to lending group mappings
        specialised_lending_file: Optional path to specialised lending data
        equity_exposures_file: Optional path to equity exposure data
        fx_rates_file: Optional path to FX rates data for currency conversion
    """

    counterparty_files: list[str] = field(default_factory=lambda: [
        "counterparty/sovereign.parquet",
        "counterparty/institution.parquet",
        "counterparty/corporate.parquet",
        "counterparty/retail.parquet",
    ])
    facilities_file: str = "exposures/facilities.parquet"
    loans_file: str = "exposures/loans.parquet"
    contingents_file: str = "exposures/contingents.parquet"
    collateral_file: str = "collateral/collateral.parquet"
    guarantees_file: str = "guarantee/guarantee.parquet"
    provisions_file: str = "provision/provision.parquet"
    ratings_file: str = "ratings/ratings.parquet"
    facility_mappings_file: str = "exposures/facility_mapping.parquet"
    org_mappings_file: str = "mapping/org_mapping.parquet"
    lending_mappings_file: str = "mapping/lending_mapping.parquet"
    specialised_lending_file: str | None = "counterparty/specialised_lending.parquet"
    equity_exposures_file: str | None = None
    fx_rates_file: str | None = "fx_rates/fx_rates.parquet"


class DataLoadError(Exception):
    """Exception raised when data cannot be loaded."""

    def __init__(self, message: str, source: str | None = None) -> None:
        """
        Initialize DataLoadError.

        Args:
            message: Error message
            source: Source file/table that caused the error
        """
        self.source = source
        super().__init__(f"{message}" + (f" (source: {source})" if source else ""))


class ParquetLoader:
    """
    Load data from Parquet files.

    Implements LoaderProtocol for loading from a directory structure
    of Parquet files. Uses Polars scan_parquet for lazy evaluation.

    Attributes:
        base_path: Base directory containing data files
        config: Data source configuration
    """

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
    ) -> None:
        """
        Initialize ParquetLoader.

        Args:
            base_path: Base directory containing data files
            config: Optional data source configuration
        """
        self.base_path = Path(base_path)
        self.config = config or DataSourceConfig()

        if not self.base_path.exists():
            raise DataLoadError(f"Base path does not exist: {self.base_path}")

    def _load_parquet(self, relative_path: str) -> pl.LazyFrame:
        """
        Load a single Parquet file as LazyFrame.

        Args:
            relative_path: Path relative to base_path

        Returns:
            LazyFrame from the Parquet file

        Raises:
            DataLoadError: If file cannot be loaded
        """
        full_path = self.base_path / relative_path
        if not full_path.exists():
            raise DataLoadError(f"File not found: {full_path}", source=relative_path)

        try:
            return normalize_columns(pl.scan_parquet(full_path))
        except Exception as e:
            raise DataLoadError(f"Failed to load parquet: {e}", source=relative_path) from e

    def _load_parquet_optional(self, relative_path: str | None) -> pl.LazyFrame | None:
        """
        Load an optional Parquet file.

        Args:
            relative_path: Path relative to base_path, or None

        Returns:
            LazyFrame if file exists and loads, None otherwise
        """
        if relative_path is None:
            return None

        full_path = self.base_path / relative_path
        if not full_path.exists():
            return None

        try:
            return normalize_columns(pl.scan_parquet(full_path))
        except Exception:
            return None

    def _load_and_combine_counterparties(self) -> pl.LazyFrame:
        """
        Load and combine all counterparty files.

        Returns:
            Combined LazyFrame of all counterparty types
        """
        frames = []
        for file_path in self.config.counterparty_files:
            full_path = self.base_path / file_path
            if full_path.exists():
                try:
                    frames.append(normalize_columns(pl.scan_parquet(full_path)))
                except Exception as e:
                    raise DataLoadError(
                        f"Failed to load counterparty file: {e}",
                        source=file_path
                    ) from e

        if not frames:
            raise DataLoadError("No counterparty files found")

        # Concatenate all counterparty frames
        # Use diagonal_relaxed to handle schema differences
        return pl.concat(frames, how="diagonal_relaxed")

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Returns:
            RawDataBundle containing all input LazyFrames

        Raises:
            DataLoadError: If required data cannot be loaded
        """
        return RawDataBundle(
            facilities=self._load_parquet(self.config.facilities_file),
            loans=self._load_parquet(self.config.loans_file),
            contingents=self._load_parquet(self.config.contingents_file),
            counterparties=self._load_and_combine_counterparties(),
            collateral=self._load_parquet(self.config.collateral_file),
            guarantees=self._load_parquet(self.config.guarantees_file),
            provisions=self._load_parquet(self.config.provisions_file),
            ratings=self._load_parquet(self.config.ratings_file),
            facility_mappings=self._load_parquet(self.config.facility_mappings_file),
            org_mappings=self._load_parquet(self.config.org_mappings_file),
            lending_mappings=self._load_parquet(self.config.lending_mappings_file),
            specialised_lending=self._load_parquet_optional(
                self.config.specialised_lending_file
            ),
            equity_exposures=self._load_parquet_optional(
                self.config.equity_exposures_file
            ),
            fx_rates=self._load_parquet_optional(
                self.config.fx_rates_file
            ),
        )


class CSVLoader:
    """
    Load data from CSV files.

    Implements LoaderProtocol for loading from a directory structure
    of CSV files. Uses Polars scan_csv for lazy evaluation.

    Useful for development and testing when Parquet files are not available.

    Attributes:
        base_path: Base directory containing data files
        config: Data source configuration (paths should end in .csv)
    """

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
    ) -> None:
        """
        Initialize CSVLoader.

        Args:
            base_path: Base directory containing data files
            config: Optional data source configuration
        """
        self.base_path = Path(base_path)
        self.config = config or self._get_csv_config()

        if not self.base_path.exists():
            raise DataLoadError(f"Base path does not exist: {self.base_path}")

    @staticmethod
    def _get_csv_config() -> DataSourceConfig:
        """Get config with CSV file extensions."""
        return DataSourceConfig(
            counterparty_files=[
                "counterparty/sovereign.csv",
                "counterparty/institution.csv",
                "counterparty/corporate.csv",
                "counterparty/retail.csv",
            ],
            facilities_file="exposures/facilities.csv",
            loans_file="exposures/loans.csv",
            contingents_file="exposures/contingents.csv",
            collateral_file="collateral/collateral.csv",
            guarantees_file="guarantee/guarantee.csv",
            provisions_file="provision/provision.csv",
            ratings_file="ratings/ratings.csv",
            facility_mappings_file="exposures/facility_mapping.csv",
            org_mappings_file="mapping/org_mapping.csv",
            lending_mappings_file="mapping/lending_mapping.csv",
            specialised_lending_file="counterparty/specialised_lending.csv",
            equity_exposures_file=None,
            fx_rates_file="fx_rates/fx_rates.csv",
        )

    def _load_csv(self, relative_path: str) -> pl.LazyFrame:
        """
        Load a single CSV file as LazyFrame.

        Args:
            relative_path: Path relative to base_path

        Returns:
            LazyFrame from the CSV file

        Raises:
            DataLoadError: If file cannot be loaded
        """
        full_path = self.base_path / relative_path
        if not full_path.exists():
            raise DataLoadError(f"File not found: {full_path}", source=relative_path)

        try:
            return normalize_columns(pl.scan_csv(full_path, try_parse_dates=True))
        except Exception as e:
            raise DataLoadError(f"Failed to load CSV: {e}", source=relative_path) from e

    def _load_csv_optional(self, relative_path: str | None) -> pl.LazyFrame | None:
        """
        Load an optional CSV file.

        Args:
            relative_path: Path relative to base_path, or None

        Returns:
            LazyFrame if file exists and loads, None otherwise
        """
        if relative_path is None:
            return None

        full_path = self.base_path / relative_path
        if not full_path.exists():
            return None

        try:
            return normalize_columns(pl.scan_csv(full_path, try_parse_dates=True))
        except Exception:
            return None

    def _load_and_combine_counterparties(self) -> pl.LazyFrame:
        """
        Load and combine all counterparty CSV files.

        Returns:
            Combined LazyFrame of all counterparty types
        """
        frames = []
        for file_path in self.config.counterparty_files:
            full_path = self.base_path / file_path
            if full_path.exists():
                try:
                    frames.append(normalize_columns(pl.scan_csv(full_path, try_parse_dates=True)))
                except Exception as e:
                    raise DataLoadError(
                        f"Failed to load counterparty file: {e}",
                        source=file_path
                    ) from e

        if not frames:
            raise DataLoadError("No counterparty files found")

        return pl.concat(frames, how="diagonal_relaxed")

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Returns:
            RawDataBundle containing all input LazyFrames

        Raises:
            DataLoadError: If required data cannot be loaded
        """
        return RawDataBundle(
            facilities=self._load_csv(self.config.facilities_file),
            loans=self._load_csv(self.config.loans_file),
            contingents=self._load_csv(self.config.contingents_file),
            counterparties=self._load_and_combine_counterparties(),
            collateral=self._load_csv(self.config.collateral_file),
            guarantees=self._load_csv(self.config.guarantees_file),
            provisions=self._load_csv(self.config.provisions_file),
            ratings=self._load_csv(self.config.ratings_file),
            facility_mappings=self._load_csv(self.config.facility_mappings_file),
            org_mappings=self._load_csv(self.config.org_mappings_file),
            lending_mappings=self._load_csv(self.config.lending_mappings_file),
            specialised_lending=self._load_csv_optional(
                self.config.specialised_lending_file
            ),
            equity_exposures=self._load_csv_optional(
                self.config.equity_exposures_file
            ),
            fx_rates=self._load_csv_optional(
                self.config.fx_rates_file
            ),
        )


def create_test_loader(fixture_path: str | Path | None = None) -> ParquetLoader:
    """
    Create a loader configured for test fixtures.

    Convenience function for testing that creates a ParquetLoader
    pointing to the test fixtures directory.

    Args:
        fixture_path: Optional explicit path to fixtures.
                     If None, uses default tests/fixtures location.

    Returns:
        ParquetLoader configured for test fixtures
    """
    if fixture_path is None:
        # Find project root by looking for pyproject.toml
        current = Path(__file__).parent
        while current.parent != current:
            if (current / "pyproject.toml").exists():
                fixture_path = current / "tests" / "fixtures"
                break
            current = current.parent
        else:
            raise DataLoadError("Could not find project root (pyproject.toml)")

    return ParquetLoader(base_path=fixture_path)
