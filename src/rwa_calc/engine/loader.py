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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl

from rwa_calc.config.data_sources import DataSourceRegistry
from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.edges import (
    RAW_TABLE_EDGES,
    SFT_TABLE_EDGES,
    EdgeContract,
    brand,
    seal_lenient,
)
from rwa_calc.contracts.errors import (
    CalculationError,
    missing_required_column_error,
    optional_file_load_error,
)
from rwa_calc.contracts.protocols import LoaderProtocol
from rwa_calc.data.column_spec import (
    ColumnSpec,
    apply_boolean_column_defaults,
    dtypes_of,
    ensure_columns,
)
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.engine.utils import has_rows

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

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
    schema: dict[str, PolarsDataType] | dict[str, ColumnSpec],
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

    def _dtype(entry: PolarsDataType | ColumnSpec) -> PolarsDataType:
        return entry.dtype if isinstance(entry, ColumnSpec) else entry

    is_column_spec_schema = any(isinstance(entry, ColumnSpec) for entry in schema.values())
    if is_column_spec_schema:
        lf = ensure_columns(lf, cast("Mapping[str, ColumnSpec]", schema))

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
        lf = apply_boolean_column_defaults(lf, cast("Mapping[str, ColumnSpec]", schema))

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


# Legacy input-column spellings, translated to canonical names at load.
# The loader is the ONLY place input aliases are translated (migration
# Phase 3: alias translation happens here exactly once) — downstream
# stages see canonical names only.
_INPUT_COLUMN_ALIASES: dict[str, dict[str, str]] = {
    "facility_mappings": {"node_type": "child_type"},
}


def _translate_input_aliases(lf: pl.LazyFrame, field_name: str) -> pl.LazyFrame:
    """Rename legacy column spellings on an input table to canonical names.

    ``strict=False`` makes the rename a no-op when the legacy spelling is
    absent — no schema probe needed. A file carrying BOTH spellings is
    structurally ambiguous: the rename collides at schema resolution and
    the load wrappers surface it (required table → ``DataLoadError``;
    optional table → DQ007 + treated as absent).
    """
    aliases = _INPUT_COLUMN_ALIASES.get(field_name)
    if not aliases:
        return lf
    return lf.rename(dict(aliases), strict=False)


def _seal_table(
    lf: pl.LazyFrame,
    field_name: str,
    enforce_schemas: bool,
    errors: list[CalculationError],
) -> pl.LazyFrame:
    """Seal one input table against its loader edge contract.

    Lenient by design — the loader is the data-quality boundary: missing
    required columns become typed nulls plus one DQ001 error each, dtype
    mismatches are cast with invalid values nulled, undeclared columns
    are stripped, Boolean defaults filled, and the frame is branded for
    bundle ``__post_init__`` validation.
    """
    edge = RAW_TABLE_EDGES[field_name]
    if not enforce_schemas:
        # RWA_ALLOW_UNSAFE_LOAD escape hatch (env-gated, test-only): brand
        # without conforming so bundle construction still works. The brand
        # on this path is attested, not verified.
        return brand(lf, edge.name)
    sealed, missing = seal_lenient(lf, edge)
    errors.extend(
        missing_required_column_error(table=field_name, column=column) for column in missing
    )
    return sealed


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
    collateral_links_file: Path | None = None
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
    # SFT (FCCM) inputs (SFT/FCCM separation Phase 4) — composed into
    # ``RawSFTBundle`` and attached to ``RawDataBundle.sft``. ``sft_trades``
    # is the single primary dataload; ``sft_collateral`` is optional and
    # appears only when securities are posted. Firms without an SFT book
    # leave ``sft_trades_file`` at None and the SFT bundle stays None.
    sft_trades_file: Path | None = None
    sft_collateral_file: Path | None = None
    # Multi-entity reporting inputs — two OPTIONAL registries consumed by the
    # scope-resolver stage (group / sub-consolidated / solo submissions,
    # CRR Art. 6 / 11-18). Loaded into ``RawDataBundle.reporting_entities`` /
    # ``RawDataBundle.book_entity_mappings`` via the shared optional-table path.
    # Both None → the pipeline runs unscoped exactly as today.
    reporting_entities_file: Path | None = None
    book_entity_mappings_file: Path | None = None

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
            collateral_links_file=get_p("collateral_links"),
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
            sft_trades_file=get_p("sft_trades"),
            sft_collateral_file=get_p("sft_collateral"),
            reporting_entities_file=get_p("reporting_entities"),
            book_entity_mappings_file=get_p("book_entity_mapping"),
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
    errors: list[CalculationError],
    field_name: str,
    relative_path: str | Path,
) -> pl.LazyFrame:
    """Load a required table: normalize + alias translation + edge seal.

    Missing required COLUMNS accumulate DQ001 errors via the lenient seal;
    a missing FILE remains a hard ``DataLoadError`` (the pipeline cannot
    run without the required tables).
    """
    full_path = base_path / relative_path
    try:
        lf = _translate_input_aliases(normalize_columns(scan_fn(full_path)), field_name)
        return _seal_table(lf, field_name, enforce_schemas, errors)
    except DataLoadError:
        raise
    except FileNotFoundError:
        raise DataLoadError(f"File not found: {full_path}", source=relative_path) from None
    except Exception as e:
        raise DataLoadError(f"Failed to load file: {e}", source=relative_path) from e


def _load_table_standalone(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    relative_path: str | Path,
    schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
) -> pl.LazyFrame:
    """Standalone single-file load (no bundle field): normalize + enforce.

    Pre-seal behaviour, kept for the loaders' public single-table
    convenience methods — there is no ``RawDataBundle`` field (and so no
    edge contract) on this path.
    """
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
) -> pl.LazyFrame | None:
    """Load an optional table — None if missing, empty, or unreadable.

    A missing file (``FileNotFoundError``) is the legitimate
    "optional not configured" case and is logged at DEBUG only.
    Any other failure (corrupt parquet, OSError, PermissionError,
    Polars ``ComputeError``, schema-cast failure, ambiguous alias
    columns) appends a single DQ007 ``CalculationError`` to *errors*
    and emits one WARNING log line — the field is still treated as
    absent so the pipeline can continue. A present table is sealed
    against its loader edge contract (alias translation + lenient
    conform + brand).
    """
    if relative_path is None:
        return None
    try:
        lf = _translate_input_aliases(
            normalize_columns(scan_fn(base_path / relative_path)), field_name
        )
        # Force schema resolution so corrupt parquet / scan failures
        # surface here rather than being swallowed by ``has_rows``'
        # broad except clause downstream.
        lf.collect_schema()
        if not has_rows(lf):
            return None
        return _seal_table(lf, field_name, enforce_schemas, errors)
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


def _load_table_standalone_optional(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    relative_path: str | Path | None,
    schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
) -> pl.LazyFrame | None:
    """Standalone optional load (no bundle field): None if missing/empty.

    Pre-seal behaviour, kept for the loaders' public single-table
    convenience methods — no ``RawDataBundle`` field means no edge
    contract and no error accumulation target on this path.
    """
    if relative_path is None:
        return None
    try:
        lf = normalize_columns(scan_fn(base_path / relative_path))
        # No corrupt-surface schema probe here: this path has no error
        # accumulation target, so ``has_rows``' broad except yielding None
        # is the same outcome either way.
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


def _seal_sft_table(
    lf: pl.LazyFrame,
    edge: EdgeContract,
    field_name: str,
    enforce_schemas: bool,
    errors: list[CalculationError],
) -> pl.LazyFrame:
    """Seal one SFT input table against its dedicated edge contract.

    Mirrors ``_seal_table`` but resolves the edge from ``SFT_TABLE_EDGES``
    (passed explicitly) rather than ``RAW_TABLE_EDGES``. The structural
    fix at the heart of the SFT/FCCM separation: SFT inputs get the same
    brand + undeclared-column-strip + lenient missing-column accounting as
    the 18 traditional tables — NOT the ``enforce_schema`` bypass the CCR
    leaf frames use.
    """
    if not enforce_schemas:
        return brand(lf, edge.name)
    sealed, missing = seal_lenient(lf, edge)
    errors.extend(
        missing_required_column_error(table=field_name, column=column) for column in missing
    )
    return sealed


def _load_sft_file_optional(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    errors: list[CalculationError],
    field_name: str,
    relative_path: str | Path | None,
) -> pl.LazyFrame | None:
    """Load an optional SFT file via the standard seal path — None if absent.

    Same None-on-missing/empty semantics as the generic
    ``_load_file_optional`` (a missing FILE is the legitimate "optional not
    configured" case logged at DEBUG; any other failure appends one DQ007
    and is treated as absent), but seals against ``SFT_TABLE_EDGES`` instead
    of ``RAW_TABLE_EDGES``. Used for both SFT leaf frames; the caller maps a
    None ``sft_collateral`` to ``RawSFTBundle.collateral = None``.
    """
    if relative_path is None:
        return None
    try:
        lf = normalize_columns(scan_fn(base_path / relative_path))
        # Force schema resolution so corrupt parquet / scan failures surface
        # here rather than being swallowed by ``has_rows``' broad except.
        lf.collect_schema()
        if not has_rows(lf):
            return None
        return _seal_sft_table(lf, SFT_TABLE_EDGES[field_name], field_name, enforce_schemas, errors)
    except FileNotFoundError:
        logger.debug("optional SFT input %s not present; treating as absent", relative_path)
        return None
    except Exception as exc:
        logger.warning(
            "optional SFT input %s could not be loaded (%s: %s); treating as absent",
            relative_path,
            type(exc).__name__,
            exc,
        )
        errors.append(
            optional_file_load_error(relative_path=relative_path, field_name=field_name, exc=exc)
        )
        return None


def _build_raw_sft_bundle(
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
    config: DataSourceConfig,
    load_errors: list[CalculationError],
) -> RawSFTBundle | None:
    """Compose ``RawSFTBundle`` from the SFT file paths on *config*.

    Returns ``None`` when no SFT trade file is configured — the legitimate
    "no SFT scope" case (mirrors ``_build_raw_ccr_bundle`` returning None
    for "no CCR scope"). Otherwise:

    - ``trades``: sealed via the STANDARD seal path
      (``SFT_TABLE_EDGES`` / ``seal_lenient``), NOT ``enforce_schema``. A
      configured-but-zero-row / absent trade file yields an empty sealed
      frame so the mandatory ``trades`` leaf is always constructable.
    - ``collateral``: OPTIONAL. ``None`` when the collateral file is absent,
      empty, or unconfigured — the common uncollateralised SFT (CCR-A11).
      A populated collateral file yields a ``SftCollateralBundle`` (CCR-A12).
    """
    if config.sft_trades_file is None:
        return None

    trades_lf = _load_sft_file_optional(
        base_path, scan_fn, enforce_schemas, load_errors, "sft_trades", config.sft_trades_file
    )
    if trades_lf is None:
        # Configured but absent / zero-row: keep the mandatory trades leaf
        # constructable with an empty sealed frame (CCR-style tolerance).
        trades_lf = SFT_TABLE_EDGES["sft_trades"].empty_frame()

    collateral_lf = _load_sft_file_optional(
        base_path,
        scan_fn,
        enforce_schemas,
        load_errors,
        "sft_collateral",
        config.sft_collateral_file,
    )
    collateral_bundle = (
        SftCollateralBundle(sft_collateral=collateral_lf) if collateral_lf is not None else None
    )

    return RawSFTBundle(
        trades=SftTradeBundle(sft_trades=trades_lf),
        collateral=collateral_bundle,
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
    load: Callable[[list[CalculationError], str, str | Path], pl.LazyFrame],
    load_optional: Callable[
        [list[CalculationError], str, str | Path | None],
        pl.LazyFrame | None,
    ],
    config: DataSourceConfig,
    base_path: Path,
    scan_fn: ScanFn,
    enforce_schemas: bool,
) -> RawDataBundle:
    """Build a RawDataBundle — single implementation shared by all loaders.

    Every table is sealed against its loader edge contract
    (``RAW_TABLE_EDGES``) on load: alias translation, lenient conform
    (missing required columns → DQ001 errors + typed nulls), scratch
    strip, brand. Optional-file load failures (corrupt parquet, OSError,
    etc.) are accumulated into ``load_errors`` via ``_load_file_optional``
    and merged with the categorical-validation errors before constructing
    the final bundle. The CCR composite bundle (P8.5) is wired via
    ``_build_raw_ccr_bundle`` which uses *base_path* / *scan_fn* directly
    because it needs zero-row tolerance — generic ``_load_file_optional``
    collapses empty frames to ``None``.
    """
    load_errors: list[CalculationError] = []

    def _req(field_name: str, relative_path: str | Path | None) -> pl.LazyFrame:
        if relative_path is None:
            raise DataLoadError(f"Required table '{field_name}' has no configured path")
        return load(load_errors, field_name, relative_path)

    def _opt(field_name: str, relative_path: str | Path | None) -> pl.LazyFrame | None:
        return load_optional(load_errors, field_name, relative_path)

    ccr_bundle = _build_raw_ccr_bundle(base_path, scan_fn, enforce_schemas, config, load_errors)
    sft_bundle = _build_raw_sft_bundle(base_path, scan_fn, enforce_schemas, config, load_errors)

    bundle = RawDataBundle(
        facilities=_req("facilities", config.facilities_file),
        loans=_req("loans", config.loans_file),
        counterparties=_req("counterparties", config.counterparties_file),
        facility_mappings=_req("facility_mappings", config.facility_mappings_file),
        org_mappings=_opt("org_mappings", config.org_mappings_file),
        lending_mappings=_opt("lending_mappings", config.lending_mappings_file),
        contingents=_opt("contingents", config.contingents_file),
        collateral=_opt("collateral", config.collateral_file),
        collateral_links=_opt("collateral_links", config.collateral_links_file),
        guarantees=_opt("guarantees", config.guarantees_file),
        provisions=_opt("provisions", config.provisions_file),
        ratings=_opt("ratings", config.ratings_file),
        equity_exposures=_opt("equity_exposures", config.equity_exposures_file),
        ciu_holdings=_opt("ciu_holdings", config.ciu_holdings_file),
        specialised_lending=_opt("specialised_lending", config.specialised_lending_file),
        fx_rates=_opt("fx_rates", config.fx_rates_file),
        model_permissions=_opt("model_permissions", config.model_permissions_file),
        securitisation_allocations=_opt(
            "securitisation_allocations", config.securitisation_allocations_file
        ),
        # Multi-entity reporting registries (CRR Art. 6 / 11-18). Loaded via the
        # same optional-table path as every other optional frame: absent file →
        # None, non-blocking validation, sealed against RAW_TABLE_EDGES.
        reporting_entities=_opt("reporting_entities", config.reporting_entities_file),
        book_entity_mappings=_opt("book_entity_mappings", config.book_entity_mappings_file),
        ccr=ccr_bundle,
        sft=sft_bundle,
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
        schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
    ) -> pl.LazyFrame:
        return _load_table_standalone(
            self.base_path, pl.scan_parquet, self.enforce_schemas, relative_path, schema
        )

    def _load_parquet_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
    ) -> pl.LazyFrame | None:
        # Standalone convenience entry point — no bundle field, no edge seal.
        return _load_table_standalone_optional(
            self.base_path,
            pl.scan_parquet,
            self.enforce_schemas,
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
        schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
    ) -> pl.LazyFrame:
        return _load_table_standalone(
            self.base_path, self._scan_csv, self.enforce_schemas, relative_path, schema
        )

    def _load_csv_optional(
        self,
        relative_path: str | Path | None,
        schema: dict[str, PolarsDataType] | dict[str, ColumnSpec] | None = None,
    ) -> pl.LazyFrame | None:
        # Standalone convenience entry point — no bundle field, no edge seal.
        return _load_table_standalone_optional(
            self.base_path,
            self._scan_csv,
            self.enforce_schemas,
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
