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

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

import polars as pl

from rwa_calc.config.data_sources import DataSourceRegistry
from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.contracts.errors import CalculationError, optional_file_load_error
from rwa_calc.contracts.protocols import LoaderProtocol
from rwa_calc.data.column_spec import (
    ColumnSpec,
    apply_boolean_column_defaults,
    dtypes_of,
    ensure_columns,
)
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    CIU_HOLDINGS_SCHEMA,
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
    MARGIN_AGREEMENT_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    NETTING_SET_SCHEMA,
    ORG_MAPPING_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
    SECURITISATION_ALLOCATION_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.engine.utils import has_rows

logger = logging.getLogger(__name__)

UNSAFE_LOAD_ENV_VAR = "RWA_ALLOW_UNSAFE_LOAD"


def _check_enforce_schemas_flag(enforce_schemas: bool, loader_name: str) -> None:
    """Reject ``enforce_schemas=False`` unless the unsafe-load env var is set.

    Skipping schema enforcement bypasses the regulatory column-default
    fills (committed, is_obs_commitment, is_revolving, is_qrre_transactor)
    applied by ``apply_boolean_column_defaults``. A null cell in any of
    those columns silently changes RWA — wrong-direction for committed
    flags. This guard fails fast in production; legitimate test paths
    that need the unsafe behaviour set ``RWA_ALLOW_UNSAFE_LOAD=1``
    explicitly via ``monkeypatch.setenv`` and document why.
    """
    if enforce_schemas:
        return
    if os.environ.get(UNSAFE_LOAD_ENV_VAR) == "1":
        return
    raise ValueError(
        f"{loader_name}(enforce_schemas=False) bypasses regulatory column-default "
        f"fills (committed, is_obs_commitment, is_revolving, is_qrre_transactor) "
        f"and silently changes RWA. Set {UNSAFE_LOAD_ENV_VAR}=1 in the environment "
        f"to authorise the unsafe path; this should only be used by tests that "
        f"explicitly cover null-tolerant behaviour."
    )


type ScanFn = Callable[[Path], pl.LazyFrame]


def enforce_schema(
    lf: pl.LazyFrame,
    schema: dict[str, pl.DataType] | dict[str, ColumnSpec],
    strict: bool = False,
) -> pl.LazyFrame:
    """
    Enforce a schema on a LazyFrame by casting columns to expected types.

    This ensures data loaded from external sources matches the expected types,
    preventing type mismatch errors in downstream calculations.

    Args:
        lf: LazyFrame to enforce schema on
        schema: Dict mapping column names to expected Polars dtypes or
            ColumnSpec entries. Raw dtype entries are treated as required.
        strict: If True, raise errors on invalid casts. If False (default),
                invalid values become null.

    Returns:
        LazyFrame with columns cast to expected types
    """

    def _dtype(entry: pl.DataType | ColumnSpec) -> pl.DataType:
        return entry.dtype if isinstance(entry, ColumnSpec) else entry

    is_column_spec_schema = any(isinstance(entry, ColumnSpec) for entry in schema.values())
    if is_column_spec_schema:
        lf = ensure_columns(lf, schema)  # type: ignore[arg-type]

    current_schema = lf.collect_schema()
    current_cols = set(current_schema.names())

    cast_exprs = [
        pl.col(col_name).cast(_dtype(entry), strict=strict).alias(col_name)
        for col_name, entry in schema.items()
        if col_name in current_cols and current_schema[col_name] != _dtype(entry)
    ]

    if cast_exprs:
        lf = lf.with_columns(cast_exprs)

    # Apply Boolean-column null fills strictly AFTER cast — ordering is
    # load-bearing. An inferred pl.Null column must be cast to pl.Boolean
    # first so the subsequent fill_null can type-coerce its literal cleanly.
    # Float/String defaults are intentionally excluded; see
    # ``apply_boolean_column_defaults`` for rationale.
    if is_column_spec_schema:
        lf = apply_boolean_column_defaults(lf, schema)  # type: ignore[arg-type]

    return lf


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
    ciu_holdings_file: Path | None = None
    specialised_lending_file: Path | None = None
    fx_rates_file: Path | None = None
    model_permissions_file: Path | None = None
    securitisation_allocations_file: Path | None = None
    # CCR inputs (P8.5) — composed into ``RawCCRBundle`` and attached to
    # ``RawDataBundle.ccr``. All four are optional at the firm level; firms
    # without derivative or SFT books leave them at None and the CCR stage
    # no-ops. Empty (zero-row) parquets are valid — they round-trip as
    # empty LazyFrames inside the leaf bundles (NOT collapsed to None).
    ccr_trades_file: Path | None = None
    ccr_netting_sets_file: Path | None = None
    ccr_margin_agreements_file: Path | None = None
    ccr_collateral_file: Path | None = None

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
            ciu_holdings_file=get_p("ciu_holdings"),
            specialised_lending_file=get_p("specialised_lending"),
            fx_rates_file=get_p("fx_rates"),
            model_permissions_file=get_p("model_permissions"),
            securitisation_allocations_file=get_p("securitisation_allocations"),
            ccr_trades_file=get_p("ccr_trades"),
            ccr_netting_sets_file=get_p("ccr_netting_sets"),
            ccr_margin_agreements_file=get_p("ccr_margin_agreements"),
            ccr_collateral_file=get_p("ccr_collateral"),
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
    errors: list[CalculationError],
    field_name: str,
    relative_path: str | Path | None,
    schema: dict[str, pl.DataType] | None = None,
) -> pl.LazyFrame | None:
    """Load an optional file — returns None if missing, empty, or unreadable.

    A missing file (``FileNotFoundError``) is the legitimate
    "optional not configured" case and is logged at DEBUG only.
    Any other failure (corrupt parquet, OSError, PermissionError,
    Polars ``ComputeError``, schema-cast failure) appends a single
    DQ007 ``CalculationError`` to *errors* and emits one WARNING
    log line — the field is still treated as absent so the
    pipeline can continue.
    """
    if relative_path is None:
        return None
    try:
        lf = normalize_columns(scan_fn(base_path / relative_path))
        # Force schema resolution so corrupt parquet / scan failures
        # surface here rather than being swallowed by ``has_rows``'
        # broad except clause downstream.
        lf.collect_schema()
        if not has_rows(lf):
            return None
        if enforce_schemas and schema is not None:
            lf = enforce_schema(lf, schema, strict=False)
        return lf
    except FileNotFoundError:
        logger.debug("optional input %s not present; treating as absent", relative_path)
        return None
    except Exception as exc:
        logger.warning(
            "optional input %s could not be loaded (%s: %s); treating as absent",
            relative_path,
            type(exc).__name__,
            exc,
        )
        errors.append(
            optional_file_load_error(relative_path=relative_path, field_name=field_name, exc=exc)
        )
        return None


def _load_ccr_file_optional(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    errors: list[CalculationError],
    field_name: str,
    relative_path: str | Path | None,
    schema: dict[str, ColumnSpec],
) -> pl.LazyFrame | None:
    """Load a CCR optional file with zero-row tolerance.

    Differs from ``_load_file_optional`` in three ways tailored to the CCR
    composite bundle:

    1. A zero-row parquet returns an EMPTY LazyFrame (schema applied), not
       ``None``. The CCR pipeline composes four leaf bundles into
       ``RawCCRBundle`` — an empty ``margin_agreements`` / ``ccr_collateral``
       table is the canonical CCR-A1 case and must round-trip as a frame.
    2. ``None`` is returned only for ``relative_path is None`` (caller's
       responsibility to translate to DQ007 if other CCR files are present).
    3. ``FileNotFoundError`` returns ``None`` with a DEBUG log — same as the
       generic helper.

    Any other failure (corrupt parquet, OSError, ComputeError) emits one
    DQ007 ``CalculationError`` and returns ``None``.
    """
    if relative_path is None:
        return None
    try:
        lf = normalize_columns(scan_fn(base_path / relative_path))
        # Force schema resolution so corrupt parquet / scan failures
        # surface here rather than being swallowed downstream.
        lf.collect_schema()
        if enforce_schemas:
            lf = enforce_schema(lf, schema, strict=False)
        return lf
    except FileNotFoundError:
        logger.debug("optional CCR input %s not present; treating as absent", relative_path)
        return None
    except Exception as exc:
        logger.warning(
            "optional CCR input %s could not be loaded (%s: %s); treating as absent",
            relative_path,
            type(exc).__name__,
            exc,
        )
        errors.append(
            optional_file_load_error(relative_path=relative_path, field_name=field_name, exc=exc)
        )
        return None


def _empty_ccr_lazyframe(schema: dict[str, ColumnSpec]) -> pl.LazyFrame:
    """Return an empty LazyFrame conforming to ``schema``.

    Used by ``_build_raw_ccr_bundle`` to fill in a leaf frame when the
    corresponding CCR file is unconfigured but another CCR file IS present
    (the partial-files case — DQ007 errors are accumulated separately by
    the caller).
    """
    return pl.LazyFrame(schema=dtypes_of(schema))


def _build_raw_ccr_bundle(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    config: DataSourceConfig,
    load_errors: list[CalculationError],
) -> RawCCRBundle | None:
    """Compose ``RawCCRBundle`` from the four CCR file paths on *config*.

    Returns ``None`` when none of the four ccr_*_file fields are set — the
    legitimate "no CCR scope" case. Otherwise constructs a ``RawCCRBundle``
    with one leaf bundle per CCR input:

    - A populated file yields a leaf bundle around a non-empty LazyFrame.
    - A zero-row file yields a leaf bundle around an empty LazyFrame.
    - A ``None`` path (partial-files case) yields a leaf bundle around an
      empty LazyFrame AND appends a DQ007 error to *load_errors* so the
      missing input is visible in the audit trail.
    """
    ccr_paths: dict[str, tuple[Path | None, dict[str, ColumnSpec]]] = {
        "ccr_trades": (config.ccr_trades_file, TRADE_SCHEMA),
        "ccr_netting_sets": (config.ccr_netting_sets_file, NETTING_SET_SCHEMA),
        "ccr_margin_agreements": (config.ccr_margin_agreements_file, MARGIN_AGREEMENT_SCHEMA),
        "ccr_collateral": (config.ccr_collateral_file, CCR_COLLATERAL_SCHEMA),
    }
    if all(path is None for path, _ in ccr_paths.values()):
        return None

    leaf_frames: dict[str, pl.LazyFrame] = {}
    for field_name, (path, schema) in ccr_paths.items():
        if path is None:
            # Partial-files case: another CCR file is set, but this one is
            # not. Emit DQ007 (matches optional_file_load_error wording) and
            # carry an empty LazyFrame so the leaf bundle stays schema-shaped.
            load_errors.append(
                optional_file_load_error(
                    relative_path=f"<missing {field_name}>",
                    field_name=field_name,
                    exc=FileNotFoundError(
                        f"CCR file '{field_name}' not configured but other CCR files are present"
                    ),
                )
            )
            leaf_frames[field_name] = _empty_ccr_lazyframe(schema)
            continue
        lf = _load_ccr_file_optional(
            base_path,
            scan_fn,
            enforce_schemas,
            load_errors,
            field_name,
            path,
            schema,
        )
        leaf_frames[field_name] = lf if lf is not None else _empty_ccr_lazyframe(schema)

    return RawCCRBundle(
        trades=TradeBundle(trades=leaf_frames["ccr_trades"]),
        netting_sets=NettingSetBundle(netting_sets=leaf_frames["ccr_netting_sets"]),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=leaf_frames["ccr_margin_agreements"]
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=leaf_frames["ccr_collateral"]),
    )


def _run_bundle_validation(bundle: RawDataBundle) -> list[CalculationError]:
    """Validate categorical column values in a loaded bundle.

    Wraps ``validate_bundle_values`` with exception handling so that
    validation failures never prevent the bundle from being returned.
    """
    try:
        from rwa_calc.contracts.validation import validate_bundle_values

        return validate_bundle_values(bundle)
    except Exception as e:
        logger.warning("Bundle value validation failed: %s", e)
        return []


def _build_bundle(
    load: Callable[[str | Path | None, dict[str, pl.DataType] | None], pl.LazyFrame],
    load_optional: Callable[
        [list[CalculationError], str, str | Path | None, dict[str, pl.DataType] | None],
        pl.LazyFrame | None,
    ],
    config: DataSourceConfig,
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
) -> RawDataBundle:
    """Build a RawDataBundle — single implementation shared by all loaders.

    Optional-file load failures (corrupt parquet, OSError, etc.) are
    accumulated into ``load_errors`` via ``_load_file_optional`` and
    merged with the categorical-validation errors before constructing
    the final bundle. The CCR composite bundle (P8.5) is wired via
    ``_build_raw_ccr_bundle`` which uses *base_path* / *scan_fn* directly
    because it needs zero-row tolerance — generic ``_load_file_optional``
    collapses empty frames to ``None``.
    """
    load_errors: list[CalculationError] = []

    def _opt(
        field_name: str,
        relative_path: str | Path | None,
        schema: dict[str, pl.DataType] | None,
    ) -> pl.LazyFrame | None:
        return load_optional(load_errors, field_name, relative_path, schema)

    ccr_bundle = _build_raw_ccr_bundle(base_path, scan_fn, enforce_schemas, config, load_errors)

    bundle = RawDataBundle(
        facilities=load(config.facilities_file, FACILITY_SCHEMA),
        loans=load(config.loans_file, LOAN_SCHEMA),
        counterparties=load(config.counterparties_file, COUNTERPARTY_SCHEMA),
        facility_mappings=load(config.facility_mappings_file, FACILITY_MAPPING_SCHEMA),
        org_mappings=_opt("org_mappings", config.org_mappings_file, ORG_MAPPING_SCHEMA),
        lending_mappings=load(config.lending_mappings_file, LENDING_MAPPING_SCHEMA),
        contingents=_opt("contingents", config.contingents_file, CONTINGENTS_SCHEMA),
        collateral=_opt("collateral", config.collateral_file, COLLATERAL_SCHEMA),
        guarantees=_opt("guarantees", config.guarantees_file, GUARANTEE_SCHEMA),
        provisions=_opt("provisions", config.provisions_file, PROVISION_SCHEMA),
        ratings=_opt("ratings", config.ratings_file, RATINGS_SCHEMA),
        equity_exposures=_opt(
            "equity_exposures", config.equity_exposures_file, EQUITY_EXPOSURE_SCHEMA
        ),
        ciu_holdings=_opt("ciu_holdings", config.ciu_holdings_file, CIU_HOLDINGS_SCHEMA),
        specialised_lending=_opt(
            "specialised_lending",
            config.specialised_lending_file,
            SPECIALISED_LENDING_SCHEMA,
        ),
        fx_rates=_opt("fx_rates", config.fx_rates_file, FX_RATES_SCHEMA),
        model_permissions=_opt(
            "model_permissions", config.model_permissions_file, MODEL_PERMISSIONS_SCHEMA
        ),
        securitisation_allocations=_opt(
            "securitisation_allocations",
            config.securitisation_allocations_file,
            SECURITISATION_ALLOCATION_SCHEMA,
        ),
        ccr=ccr_bundle,
    )
    validation_errors = _run_bundle_validation(bundle)
    combined = load_errors + validation_errors
    return replace(bundle, errors=combined) if combined else bundle


# ---------------------------------------------------------------------------
# Public loader classes
# ---------------------------------------------------------------------------


class ParquetLoader(LoaderProtocol):
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
        _check_enforce_schemas_flag(enforce_schemas, "ParquetLoader")
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
        # Standalone convenience entry point — discard any DQ007 since
        # there is no bundle to attach to in this path.
        return _load_file_optional(
            self.base_path,
            pl.scan_parquet,
            self.enforce_schemas,
            [],
            "",
            relative_path,
            schema,
        )

    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        load = partial(_load_file, self.base_path, pl.scan_parquet, self.enforce_schemas)
        load_opt = partial(
            _load_file_optional, self.base_path, pl.scan_parquet, self.enforce_schemas
        )
        return _build_bundle(
            load,
            load_opt,
            self.config,
            self.base_path,
            pl.scan_parquet,
            self.enforce_schemas,
        )


class CSVLoader(LoaderProtocol):
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
        _check_enforce_schemas_flag(enforce_schemas, "CSVLoader")
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
        # Standalone convenience entry point — discard any DQ007 since
        # there is no bundle to attach to in this path.
        return _load_file_optional(
            self.base_path,
            self._scan_csv,
            self.enforce_schemas,
            [],
            "",
            relative_path,
            schema,
        )

    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        load = partial(_load_file, self.base_path, self._scan_csv, self.enforce_schemas)
        load_opt = partial(
            _load_file_optional, self.base_path, self._scan_csv, self.enforce_schemas
        )
        return _build_bundle(
            load,
            load_opt,
            self.config,
            self.base_path,
            self._scan_csv,
            self.enforce_schemas,
        )


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
