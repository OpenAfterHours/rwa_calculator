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

from rwa_calc.config.data_sources import DataSourceRegistry
from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    ORG_MAPPING_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.engine.utils import has_rows

if TYPE_CHECKING:
    pass


def enforce_schema(
    lf: pl.LazyFrame,
    schema: dict[str, pl.DataType],
    strict: bool = False,
) -> pl.LazyFrame:
    """
    Enforce a schema on a LazyFrame by casting columns to expected types.

    This ensures data loaded from external sources matches the expected types,
    preventing type mismatch errors in downstream calculations.

    Args:
        lf: LazyFrame to enforce schema on
        schema: Dictionary mapping column names to expected Polars types
        strict: If True, raise errors on invalid casts. If False (default),
                invalid values become null.

    Returns:
        LazyFrame with columns cast to expected types
    """
    # Get current schema
    current_schema = lf.collect_schema()
    current_cols = set(current_schema.names())

    # Build cast expressions for columns that exist and need casting
    cast_exprs = []
    for col_name, expected_type in schema.items():
        if col_name not in current_cols:
            continue

        current_type = current_schema[col_name]

        # Skip if already the correct type
        if current_type == expected_type:
            continue

        # Cast to expected type
        cast_exprs.append(pl.col(col_name).cast(expected_type, strict=strict).alias(col_name))

    if not cast_exprs:
        return lf

    return lf.with_columns(cast_exprs)


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
        model_permissions_file: Optional path to per-model IRB permissions
    """

    counterparty_files: list[Path] = field(default_factory=list)
    facilities_file: Path | None = None
    loans_file: Path | None = None
    contingents_file: Path | None = None
    collateral_file: Path | None = None
    guarantees_file: Path | None = None
    provisions_file: Path | None = None
    ratings_file: Path | None = None
    facility_mappings_file: Path | None = None
    org_mappings_file: Path | None = None
    lending_mappings_file: Path | None = None
    specialised_lending_file: Path | None = None
    equity_exposures_file: Path | None = None
    fx_rates_file: Path | None = None
    model_permissions_file: Path | None = None

    @classmethod
    def from_registry(
        cls, extension: str = "parquet", registry: DataSourceRegistry | None = None
    ) -> DataSourceConfig:
        """
        Create a DataSourceConfig from the central registry.

        Args:
            extension: File extension to use (default parquet)
            registry: Optional custom registry instance

        Returns:
            Populated DataSourceConfig
        """
        reg = registry or DataSourceRegistry()

        def get_p(id_str: str) -> Path | None:
            source = reg.get_by_id(id_str)
            return source.get_path(extension) if source else None

        # Counterparty group
        cp_group = reg.get_groups().get("counterparty", [])
        cp_files = [s.get_path(extension) for s in cp_group]

        return cls(
            counterparty_files=cp_files,
            facilities_file=get_p("facilities"),
            loans_file=get_p("loans"),
            contingents_file=get_p("contingents"),
            collateral_file=get_p("collateral"),
            guarantees_file=get_p("guarantee"),
            provisions_file=get_p("provision"),
            ratings_file=get_p("ratings"),
            facility_mappings_file=get_p("facility_mapping"),
            org_mappings_file=get_p("org_mapping"),
            lending_mappings_file=get_p("lending_mapping"),
            specialised_lending_file=get_p("specialised_lending"),
            equity_exposures_file=get_p("equity"),
            fx_rates_file=get_p("fx_rates"),
            model_permissions_file=get_p("model_permissions"),
        )


class DataLoadError(Exception):
    """Exception raised when data cannot be loaded."""

    def __init__(self, message: str, source: Path | str | None = None) -> None:
        """
        Initialize DataLoadError.

        Args:
            message: Error message
            source: Source file/table that caused the error (str or Path)
        """
        self.source = source
        super().__init__(f"{message}" + (f" (source: {source})" if source else ""))


class ParquetLoader:
    """
    Load data from Parquet files.

    Implements LoaderProtocol for loading from a directory structure
    of Parquet files. Uses Polars scan_parquet for lazy evaluation.

    Schema enforcement is applied during loading to ensure all columns
    have the expected data types, preventing type mismatch errors in
    downstream calculations.

    Attributes:
        base_path: Base directory containing data files
        config: Data source configuration
        enforce_schemas: Whether to cast columns to expected types (default True)
    """

    # Mapping of file config attributes to their schemas
    _SCHEMA_MAP: dict[str, dict[str, pl.DataType]] = {
        "facilities_file": FACILITY_SCHEMA,
        "loans_file": LOAN_SCHEMA,
        "contingents_file": CONTINGENTS_SCHEMA,
        "collateral_file": COLLATERAL_SCHEMA,
        "guarantees_file": GUARANTEE_SCHEMA,
        "provisions_file": PROVISION_SCHEMA,
        "ratings_file": RATINGS_SCHEMA,
        "facility_mappings_file": FACILITY_MAPPING_SCHEMA,
        "org_mappings_file": ORG_MAPPING_SCHEMA,
        "lending_mappings_file": LENDING_MAPPING_SCHEMA,
        "specialised_lending_file": SPECIALISED_LENDING_SCHEMA,
        "equity_exposures_file": EQUITY_EXPOSURE_SCHEMA,
        "fx_rates_file": FX_RATES_SCHEMA,
        "model_permissions_file": MODEL_PERMISSIONS_SCHEMA,
    }

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None:
        """
        Initialize ParquetLoader.

        Args:
            base_path: Base directory containing data files
            config: Optional data source configuration
            enforce_schemas: Whether to enforce type casting based on schemas.
                           Set to False to load raw types from files.
        """
        self.base_path = Path(base_path)
        self.config = config or DataSourceConfig.from_registry(extension="parquet")
        self.enforce_schemas = enforce_schemas

        if not self.base_path.exists():
            raise DataLoadError(f"Base path does not exist: {self.base_path}")

    def _load_parquet(
        self,
        relative_path: str | Path,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame:
        """
        Load a single Parquet file as LazyFrame with optional schema enforcement.

        Args:
            relative_path: Path relative to base_path
            schema: Optional schema to enforce on the loaded data

        Returns:
            LazyFrame from the Parquet file with schema enforced

        Raises:
            DataLoadError: If file cannot be loaded
        """
        full_path = self.base_path / relative_path
        if not full_path.exists():
            raise DataLoadError(f"File not found: {full_path}", source=relative_path)

        try:
            lf = normalize_columns(pl.scan_parquet(full_path))

            # Apply schema enforcement if enabled and schema provided
            if self.enforce_schemas and schema is not None:
                lf = enforce_schema(lf, schema, strict=False)

            return lf
        except Exception as e:
            raise DataLoadError(f"Failed to load parquet: {e}", source=relative_path) from e

    def _load_parquet_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame | None:
        """
        Load an optional Parquet file with optional schema enforcement.

        Returns None if:
        - relative_path is None
        - File doesn't exist
        - File exists but has no rows
        - File cannot be loaded

        This ensures downstream code can rely on a simple `is not None` check
        to determine if valid data is available for processing.

        Args:
            relative_path: Path relative to base_path, or None
            schema: Optional schema to enforce on the loaded data

        Returns:
            LazyFrame if file exists, loads, and has data; None otherwise
        """
        if relative_path is None:
            return None

        full_path = self.base_path / relative_path
        if not full_path.exists():
            return None

        try:
            lf = normalize_columns(pl.scan_parquet(full_path))
            # Check if file has any rows - return None for empty files
            if not has_rows(lf):
                return None

            # Apply schema enforcement if enabled and schema provided
            if self.enforce_schemas and schema is not None:
                lf = enforce_schema(lf, schema, strict=False)

            return lf
        except Exception:
            return None

    def _load_and_combine_counterparties(self) -> pl.LazyFrame:
        """
        Load and combine all counterparty files with schema enforcement.

        Returns:
            Combined LazyFrame of all counterparty types
        """
        frames = []
        for file_path in self.config.counterparty_files:
            full_path = self.base_path / file_path
            if full_path.exists():
                try:
                    lf = normalize_columns(pl.scan_parquet(full_path))

                    # Apply schema enforcement if enabled
                    if self.enforce_schemas:
                        lf = enforce_schema(lf, COUNTERPARTY_SCHEMA, strict=False)

                    frames.append(lf)
                except Exception as e:
                    raise DataLoadError(
                        f"Failed to load counterparty file: {e}", source=file_path
                    ) from e

        if not frames:
            raise DataLoadError("No counterparty files found")

        # Concatenate all counterparty frames
        # Use diagonal_relaxed to handle schema differences
        return pl.concat(frames, how="diagonal_relaxed")

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Schema enforcement is applied to all loaded data when enforce_schemas=True,
        ensuring columns have the correct data types for downstream calculations.

        Returns:
            RawDataBundle containing all input LazyFrames

        Raises:
            DataLoadError: If required data cannot be loaded
        """
        contingents = self._load_parquet_optional(self.config.contingents_file, CONTINGENTS_SCHEMA)

        return RawDataBundle(
            facilities=self._load_parquet(self.config.facilities_file, FACILITY_SCHEMA),
            loans=self._load_parquet(self.config.loans_file, LOAN_SCHEMA),
            counterparties=self._load_and_combine_counterparties(),
            facility_mappings=self._load_parquet(
                self.config.facility_mappings_file, FACILITY_MAPPING_SCHEMA
            ),
            org_mappings=self._load_parquet_optional(
                self.config.org_mappings_file, ORG_MAPPING_SCHEMA
            ),
            lending_mappings=self._load_parquet(
                self.config.lending_mappings_file, LENDING_MAPPING_SCHEMA
            ),
            contingents=contingents,
            collateral=self._load_parquet_optional(self.config.collateral_file, COLLATERAL_SCHEMA),
            guarantees=self._load_parquet_optional(self.config.guarantees_file, GUARANTEE_SCHEMA),
            provisions=self._load_parquet_optional(self.config.provisions_file, PROVISION_SCHEMA),
            ratings=self._load_parquet_optional(self.config.ratings_file, RATINGS_SCHEMA),
            specialised_lending=self._load_parquet_optional(
                self.config.specialised_lending_file, SPECIALISED_LENDING_SCHEMA
            ),
            equity_exposures=self._load_parquet_optional(
                self.config.equity_exposures_file, EQUITY_EXPOSURE_SCHEMA
            ),
            fx_rates=self._load_parquet_optional(self.config.fx_rates_file, FX_RATES_SCHEMA),
            model_permissions=self._load_parquet_optional(
                self.config.model_permissions_file, MODEL_PERMISSIONS_SCHEMA
            ),
        )


class CSVLoader:
    """
    Load data from CSV files.

    Implements LoaderProtocol for loading from a directory structure
    of CSV files. Uses Polars scan_csv for lazy evaluation.

    Useful for development and testing when Parquet files are not available.

    Schema enforcement is applied during loading to ensure all columns
    have the expected data types, preventing type mismatch errors in
    downstream calculations.

    Attributes:
        base_path: Base directory containing data files
        config: Data source configuration (paths should end in .csv)
        enforce_schemas: Whether to cast columns to expected types (default True)
    """

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None:
        """
        Initialize CSVLoader.

        Args:
            base_path: Base directory containing data files
            config: Optional data source configuration
            enforce_schemas: Whether to enforce type casting based on schemas.
                           Set to False to load raw types from files.
        """
        self.base_path = Path(base_path)
        self.config = config or self._get_csv_config()
        self.enforce_schemas = enforce_schemas

        if not self.base_path.exists():
            raise DataLoadError(f"Base path does not exist: {self.base_path}")

    @staticmethod
    def _get_csv_config() -> DataSourceConfig:
        """Get config with CSV file extensions."""
        return DataSourceConfig.from_registry(extension="csv")

    def _load_csv(
        self,
        relative_path: str | Path,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame:
        """
        Load a single CSV file as LazyFrame with optional schema enforcement.

        Args:
            relative_path: Path relative to base_path
            schema: Optional schema to enforce on the loaded data

        Returns:
            LazyFrame from the CSV file with schema enforced

        Raises:
            DataLoadError: If file cannot be loaded
        """
        full_path = self.base_path / relative_path
        if not full_path.exists():
            raise DataLoadError(f"File not found: {full_path}", source=relative_path)

        try:
            lf = normalize_columns(pl.scan_csv(full_path, try_parse_dates=True))

            # Apply schema enforcement if enabled and schema provided
            if self.enforce_schemas and schema is not None:
                lf = enforce_schema(lf, schema, strict=False)

            return lf
        except Exception as e:
            raise DataLoadError(f"Failed to load CSV: {e}", source=relative_path) from e

    def _load_csv_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame | None:
        """
        Load an optional CSV file with optional schema enforcement.

        Returns None if:
        - relative_path is None
        - File doesn't exist
        - File exists but has no rows
        - File cannot be loaded

        This ensures downstream code can rely on a simple `is not None` check
        to determine if valid data is available for processing.

        Args:
            relative_path: Path relative to base_path, or None
            schema: Optional schema to enforce on the loaded data

        Returns:
            LazyFrame if file exists, loads, and has data; None otherwise
        """
        if relative_path is None:
            return None

        full_path = self.base_path / relative_path
        if not full_path.exists():
            return None

        try:
            lf = normalize_columns(pl.scan_csv(full_path, try_parse_dates=True))
            # Check if file has any rows - return None for empty files
            if not has_rows(lf):
                return None

            # Apply schema enforcement if enabled and schema provided
            if self.enforce_schemas and schema is not None:
                lf = enforce_schema(lf, schema, strict=False)

            return lf
        except Exception:
            return None

    def _load_and_combine_counterparties(self) -> pl.LazyFrame:
        """
        Load and combine all counterparty CSV files with schema enforcement.

        Returns:
            Combined LazyFrame of all counterparty types
        """
        frames = []
        for file_path in self.config.counterparty_files:
            full_path = self.base_path / file_path
            if full_path.exists():
                try:
                    lf = normalize_columns(pl.scan_csv(full_path, try_parse_dates=True))

                    # Apply schema enforcement if enabled
                    if self.enforce_schemas:
                        lf = enforce_schema(lf, COUNTERPARTY_SCHEMA, strict=False)

                    frames.append(lf)
                except Exception as e:
                    raise DataLoadError(
                        f"Failed to load counterparty file: {e}", source=file_path
                    ) from e

        if not frames:
            raise DataLoadError("No counterparty files found")

        return pl.concat(frames, how="diagonal_relaxed")

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Schema enforcement is applied to all loaded data when enforce_schemas=True,
        ensuring columns have the correct data types for downstream calculations.

        Returns:
            RawDataBundle containing all input LazyFrames

        Raises:
            DataLoadError: If required data cannot be loaded
        """
        contingents = self._load_csv_optional(self.config.contingents_file, CONTINGENTS_SCHEMA)

        return RawDataBundle(
            facilities=self._load_csv(self.config.facilities_file, FACILITY_SCHEMA),
            loans=self._load_csv(self.config.loans_file, LOAN_SCHEMA),
            counterparties=self._load_and_combine_counterparties(),
            facility_mappings=self._load_csv(
                self.config.facility_mappings_file, FACILITY_MAPPING_SCHEMA
            ),
            org_mappings=self._load_csv_optional(self.config.org_mappings_file, ORG_MAPPING_SCHEMA),
            lending_mappings=self._load_csv(
                self.config.lending_mappings_file, LENDING_MAPPING_SCHEMA
            ),
            contingents=contingents,
            collateral=self._load_csv_optional(self.config.collateral_file, COLLATERAL_SCHEMA),
            guarantees=self._load_csv_optional(self.config.guarantees_file, GUARANTEE_SCHEMA),
            provisions=self._load_csv_optional(self.config.provisions_file, PROVISION_SCHEMA),
            ratings=self._load_csv_optional(self.config.ratings_file, RATINGS_SCHEMA),
            specialised_lending=self._load_csv_optional(
                self.config.specialised_lending_file, SPECIALISED_LENDING_SCHEMA
            ),
            equity_exposures=self._load_csv_optional(
                self.config.equity_exposures_file, EQUITY_EXPOSURE_SCHEMA
            ),
            fx_rates=self._load_csv_optional(self.config.fx_rates_file, FX_RATES_SCHEMA),
            model_permissions=self._load_csv_optional(
                self.config.model_permissions_file, MODEL_PERMISSIONS_SCHEMA
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
