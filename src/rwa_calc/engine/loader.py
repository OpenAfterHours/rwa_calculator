"""
Data loader implementations for the RWA calculator.

Pipeline position:
    DataSource -> Loader -> HierarchyResolver

Key responsibilities:
- Load exposure data from Parquet/CSV files as LazyFrames
- Normalize column names and enforce expected schemas
- Return a RawDataBundle for downstream pipeline stages

References:
- LoaderProtocol: contracts/protocols.py

Usage:
    from rwa_calc.engine.loader import ParquetLoader

    loader = ParquetLoader(base_path="/path/to/data")
    raw_data = loader.load()
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

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

type ScanFn = Callable[[Path], pl.LazyFrame]


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
    current_schema = lf.collect_schema()
    current_cols = set(current_schema.names())

    cast_exprs = [
        pl.col(col_name).cast(expected_type, strict=strict).alias(col_name)
        for col_name, expected_type in schema.items()
        if col_name in current_cols and current_schema[col_name] != expected_type
    ]

    if not cast_exprs:
        return lf

    return lf.with_columns(cast_exprs)


def normalize_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Normalize column names to lowercase with underscores.

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
    """

    counterparties_file: Path | None = None
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
    equity_exposures_file: Path | None = None
    specialised_lending_file: Path | None = None
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

        return cls(
            counterparties_file=get_p("counterparties"),
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
            equity_exposures_file=get_p("equity"),
            specialised_lending_file=get_p("specialised_lending"),
            fx_rates_file=get_p("fx_rates"),
            model_permissions_file=get_p("model_permissions"),
        )


class DataLoadError(Exception):
    """Exception raised when data cannot be loaded."""

    def __init__(self, message: str, source: Path | str | None = None) -> None:
        self.source = source
        super().__init__(f"{message}" + (f" (source: {source})" if source else ""))


# ---------------------------------------------------------------------------
# Shared loading helpers — parameterised by scan function
# ---------------------------------------------------------------------------


def _load_file(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    relative_path: str | Path,
    schema: dict[str, pl.DataType] | None = None,
) -> pl.LazyFrame:
    """Load a required file using *scan_fn*, with normalize + schema enforcement."""
    full_path = base_path / relative_path
    try:
        lf = normalize_columns(scan_fn(full_path))
        if enforce_schemas and schema is not None:
            lf = enforce_schema(lf, schema, strict=False)
        return lf
    except FileNotFoundError:
        raise DataLoadError(f"File not found: {full_path}", source=relative_path) from None
    except Exception as e:
        raise DataLoadError(f"Failed to load file: {e}", source=relative_path) from e


def _load_file_optional(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    relative_path: str | Path | None,
    schema: dict[str, pl.DataType] | None = None,
) -> pl.LazyFrame | None:
    """Load an optional file — returns None if missing, empty, or unreadable."""
    if relative_path is None:
        return None
    try:
        lf = normalize_columns(scan_fn(base_path / relative_path))
        if not has_rows(lf):
            return None
        if enforce_schemas and schema is not None:
            lf = enforce_schema(lf, schema, strict=False)
        return lf
    except Exception:
        return None


def _build_bundle(
    load: Callable[[str | Path | None, dict[str, pl.DataType] | None], pl.LazyFrame],
    load_optional: Callable[
        [str | Path | None, dict[str, pl.DataType] | None], pl.LazyFrame | None
    ],
    config: DataSourceConfig,
) -> RawDataBundle:
    """Build a RawDataBundle — single implementation shared by all loaders."""
    return RawDataBundle(
        facilities=load(config.facilities_file, FACILITY_SCHEMA),
        loans=load(config.loans_file, LOAN_SCHEMA),
        counterparties=load(config.counterparties_file, COUNTERPARTY_SCHEMA),
        facility_mappings=load(config.facility_mappings_file, FACILITY_MAPPING_SCHEMA),
        org_mappings=load_optional(config.org_mappings_file, ORG_MAPPING_SCHEMA),
        lending_mappings=load(config.lending_mappings_file, LENDING_MAPPING_SCHEMA),
        contingents=load_optional(config.contingents_file, CONTINGENTS_SCHEMA),
        collateral=load_optional(config.collateral_file, COLLATERAL_SCHEMA),
        guarantees=load_optional(config.guarantees_file, GUARANTEE_SCHEMA),
        provisions=load_optional(config.provisions_file, PROVISION_SCHEMA),
        ratings=load_optional(config.ratings_file, RATINGS_SCHEMA),
        equity_exposures=load_optional(config.equity_exposures_file, EQUITY_EXPOSURE_SCHEMA),
        specialised_lending=load_optional(
            config.specialised_lending_file, SPECIALISED_LENDING_SCHEMA
        ),
        fx_rates=load_optional(config.fx_rates_file, FX_RATES_SCHEMA),
        model_permissions=load_optional(config.model_permissions_file, MODEL_PERMISSIONS_SCHEMA),
    )


# ---------------------------------------------------------------------------
# Public loader classes
# ---------------------------------------------------------------------------


class ParquetLoader:
    """
    Load data from Parquet files.

    Implements LoaderProtocol for loading from a directory structure
    of Parquet files. Uses Polars scan_parquet for lazy evaluation.

    Schema enforcement is applied during loading to ensure all columns
    have the expected data types for downstream calculations.
    """

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None:
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
        return _load_file(
            self.base_path, pl.scan_parquet, self.enforce_schemas, relative_path, schema
        )

    def _load_parquet_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame | None:
        return _load_file_optional(
            self.base_path, pl.scan_parquet, self.enforce_schemas, relative_path, schema
        )

    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        load = partial(_load_file, self.base_path, pl.scan_parquet, self.enforce_schemas)
        load_opt = partial(
            _load_file_optional, self.base_path, pl.scan_parquet, self.enforce_schemas
        )
        return _build_bundle(load, load_opt, self.config)


class CSVLoader:
    """
    Load data from CSV files.

    Implements LoaderProtocol for loading from a directory structure
    of CSV files. Uses Polars scan_csv for lazy evaluation.

    Useful for development and testing when Parquet files are not available.
    """

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None:
        self.base_path = Path(base_path)
        self.config = config or DataSourceConfig.from_registry(extension="csv")
        self.enforce_schemas = enforce_schemas

        if not self.base_path.exists():
            raise DataLoadError(f"Base path does not exist: {self.base_path}")

    @staticmethod
    def _scan_csv(path: Path) -> pl.LazyFrame:
        return pl.scan_csv(path, try_parse_dates=True)

    def _load_csv(
        self,
        relative_path: str | Path,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame:
        return _load_file(
            self.base_path, self._scan_csv, self.enforce_schemas, relative_path, schema
        )

    def _load_csv_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, pl.DataType] | None = None,
    ) -> pl.LazyFrame | None:
        return _load_file_optional(
            self.base_path, self._scan_csv, self.enforce_schemas, relative_path, schema
        )

    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        load = partial(_load_file, self.base_path, self._scan_csv, self.enforce_schemas)
        load_opt = partial(
            _load_file_optional, self.base_path, self._scan_csv, self.enforce_schemas
        )
        return _build_bundle(load, load_opt, self.config)


def create_test_loader(fixture_path: str | Path | None = None) -> ParquetLoader:
    """
    Create a loader configured for test fixtures.

    Args:
        fixture_path: Optional explicit path to fixtures.
                     If None, uses default tests/fixtures location.

    Returns:
        ParquetLoader configured for test fixtures
    """
    if fixture_path is None:
        current = Path(__file__).parent
        while current.parent != current:
            if (current / "pyproject.toml").exists():
                fixture_path = current / "tests" / "fixtures"
                break
            current = current.parent
        else:
            raise DataLoadError("Could not find project root (pyproject.toml)")

    return ParquetLoader(base_path=fixture_path)
