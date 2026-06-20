"""Integration tests for the SFT (FCCM) loader dataload (Phase 4).

Verifies that ``ParquetLoader`` reads the SFT trade (+ optional collateral)
parquet files through the STANDARD seal path (``SFT_TABLE_EDGES`` /
``seal_lenient``, NOT ``enforce_schema``), composes a ``RawSFTBundle``
attached to ``RawDataBundle.sft``, and handles the optionality model:

- no ``sft_trades`` file        -> ``bundle.sft is None``    (no SFT scope)
- ``sft_trades`` only           -> ``RawSFTBundle`` with ``collateral=None``
- ``sft_trades`` + collateral   -> ``RawSFTBundle`` with both leaf bundles

The seal path is asserted via the ``raw_sft_*`` brands and the stripping of
an undeclared scratch column — proving SFT inputs get the same treatment as
the 18 traditional tables (the structural fix at the heart of the
separation).

References:
    - CRR Art. 220(1)(a), 223(5), 271(2) (FCCM SFT EAD)
    - docs/plans/sft-fccm-separation.md (Phase 4)
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.config.data_sources import DATA_SOURCES
from rwa_calc.contracts.bundles import RawSFTBundle
from rwa_calc.contracts.edges import sealed_edge_of
from rwa_calc.engine.loader import DataSourceConfig, ParquetLoader

# ---------------------------------------------------------------------------
# Helpers — write SFT parquet fixtures into a temp dir
# ---------------------------------------------------------------------------


def _write_sft_trades(directory: Path) -> Path:
    """Write a one-row SFT trade parquet WITH an undeclared scratch column."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sft_trades.parquet"
    pl.DataFrame(
        {
            "trade_id": ["T_SFT_1"],
            "netting_set_id": ["NS_SFT_1"],
            "counterparty_reference": ["CP_SFT_1"],
            "notional": [1_000_000.0],
            "currency": ["GBP"],
            "maturity_date": [date(2027, 1, 1)],
            "start_date": [date(2026, 1, 1)],
            # Undeclared scratch — the standard seal path must strip it.
            "scratch_derivative_only": [42.0],
        }
    ).write_parquet(path)
    return path


def _write_sft_collateral(directory: Path) -> Path:
    """Write a one-row SFT collateral parquet."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sft_collateral.parquet"
    pl.DataFrame(
        {
            "sft_collateral_reference": ["SC_1"],
            "netting_set_id": ["NS_SFT_1"],
            "collateral_type": ["GOVERNMENT_BOND"],
            "market_value": [900_000.0],
            "currency": ["GBP"],
        }
    ).write_parquet(path)
    return path


def _config_with_sft(
    base_config: DataSourceConfig,
    trades_file: Path | None = None,
    collateral_file: Path | None = None,
) -> DataSourceConfig:
    """Return a DataSourceConfig with the SFT file paths set.

    Asserts the two sft_* fields exist before replace so a missing field
    surfaces as AssertionError (FAILED), not TypeError (ERROR).
    """
    existing = {f.name for f in dataclasses.fields(base_config)}
    for field_name in ("sft_trades_file", "sft_collateral_file"):
        assert field_name in existing, (
            f"DataSourceConfig has no field '{field_name}'. Add the sft_* fields "
            f"to DataSourceConfig in src/rwa_calc/engine/loader.py (Phase 4). "
            f"Current fields: {sorted(existing)}"
        )
    return dataclasses.replace(
        base_config,
        sft_trades_file=trades_file,
        sft_collateral_file=collateral_file,
    )


# ===========================================================================
# 1. Data source registry — new SFT entries
# ===========================================================================


@pytest.mark.parametrize("source_id", ["sft_trades", "sft_collateral"])
def test_data_source_registry_has_sft_entry(source_id: str) -> None:
    """DATA_SOURCES must contain the SFT dataload entries (Phase 4)."""
    ids = [s.id for s in DATA_SOURCES]
    assert source_id in ids, (
        f"DATA_SOURCES has no entry with id='{source_id}'. "
        f"Add it to src/rwa_calc/config/data_sources.py (Phase 4). Current IDs: {ids}"
    )


# ===========================================================================
# 2. Loader with trades + collateral
# ===========================================================================


def test_loader_with_sft_trades_and_collateral_builds_raw_sft_bundle(
    tmp_path: Path,
    write_minimal_crr_dataset: Callable[[Path], DataSourceConfig],
) -> None:
    """bundle.sft is a RawSFTBundle with both leaf bundles populated."""
    config = write_minimal_crr_dataset(tmp_path)
    config = _config_with_sft(
        config,
        trades_file=_write_sft_trades(tmp_path / "ccr"),
        collateral_file=_write_sft_collateral(tmp_path / "ccr"),
    )
    bundle = ParquetLoader(tmp_path, config=config).load()

    assert isinstance(bundle.sft, RawSFTBundle), (
        f"bundle.sft must be a RawSFTBundle, got {type(bundle.sft).__name__}"
    )
    assert bundle.sft.trades.sft_trades.collect().shape[0] == 1
    assert bundle.sft.collateral is not None
    assert bundle.sft.collateral.sft_collateral.collect().shape[0] == 1


def test_loader_seals_sft_trades_via_standard_path(
    tmp_path: Path,
    write_minimal_crr_dataset: Callable[[Path], DataSourceConfig],
) -> None:
    """The trade frame is branded raw_sft_trades and the scratch column stripped."""
    config = write_minimal_crr_dataset(tmp_path)
    config = _config_with_sft(config, trades_file=_write_sft_trades(tmp_path / "ccr"))
    bundle = ParquetLoader(tmp_path, config=config).load()

    assert bundle.sft is not None
    trades = bundle.sft.trades.sft_trades
    assert sealed_edge_of(trades) == "raw_sft_trades"
    columns = trades.collect_schema().names()
    assert "scratch_derivative_only" not in columns, (
        "the standard seal path must strip undeclared columns from SFT trades"
    )
    # The three Art. 223(5) HE inputs are injected as typed nulls (declared
    # but absent in the fixture) — proving edge-contract conform ran.
    assert "exposure_security_cqs" in columns


def test_loader_seals_sft_collateral_via_standard_path(
    tmp_path: Path,
    write_minimal_crr_dataset: Callable[[Path], DataSourceConfig],
) -> None:
    """The collateral frame is branded raw_sft_collateral."""
    config = write_minimal_crr_dataset(tmp_path)
    config = _config_with_sft(
        config,
        trades_file=_write_sft_trades(tmp_path / "ccr"),
        collateral_file=_write_sft_collateral(tmp_path / "ccr"),
    )
    bundle = ParquetLoader(tmp_path, config=config).load()

    assert bundle.sft is not None and bundle.sft.collateral is not None
    assert sealed_edge_of(bundle.sft.collateral.sft_collateral) == "raw_sft_collateral"


# ===========================================================================
# 3. Uncollateralised SFT — trades only, collateral None
# ===========================================================================


def test_loader_with_sft_trades_only_leaves_collateral_none(
    tmp_path: Path,
    write_minimal_crr_dataset: Callable[[Path], DataSourceConfig],
) -> None:
    """An uncollateralised SFT (no collateral file) yields collateral=None."""
    config = write_minimal_crr_dataset(tmp_path)
    config = _config_with_sft(config, trades_file=_write_sft_trades(tmp_path / "ccr"))
    bundle = ParquetLoader(tmp_path, config=config).load()

    assert bundle.sft is not None
    assert bundle.sft.collateral is None, (
        "an uncollateralised SFT must have RawSFTBundle.collateral = None"
    )


# ===========================================================================
# 4. No SFT scope — bundle.sft is None
# ===========================================================================


def test_loader_with_no_sft_files_leaves_bundle_sft_none(
    tmp_path: Path,
    write_minimal_crr_dataset: Callable[[Path], DataSourceConfig],
) -> None:
    """When no SFT trade file is configured, bundle.sft must be None."""
    config = write_minimal_crr_dataset(tmp_path)
    # Explicitly clear the registry-derived sft paths so none resolve.
    config = _config_with_sft(config, trades_file=None, collateral_file=None)
    bundle = ParquetLoader(tmp_path, config=config).load()

    assert bundle.sft is None, (
        f"bundle.sft must be None when no SFT trade file is configured, got {bundle.sft!r}"
    )
