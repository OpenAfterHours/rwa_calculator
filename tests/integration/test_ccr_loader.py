"""Integration tests for CCR loader hooks (P8.5).

Verifies that ``ParquetLoader`` correctly reads the four CCR parquet files
(trades, netting_sets, margin_agreements, ccr_collateral), constructs a
``RawCCRBundle`` attached to ``RawDataBundle.ccr``, and handles missing-file
cases gracefully (ccr=None when no files present, DQ007 errors when partially
present).

Also verifies that the four new ``DataSourceFile`` entries exist in
``rwa_calc.config.data_sources.DATA_SOURCES``.

Components wired:
    ParquetLoader (real) -> DataSourceConfig with CCR paths -> RawDataBundle

No mocking — parquets are the canonical CCR fixture files from
``tests/fixtures/ccr/``.

References:
    - CRR Art. 271 (CCR scope — derivatives, SFTs)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement)
    - CRR Art. 295-297 (contractual netting recognition)
    - src/rwa_calc/contracts/bundles.py (RawCCRBundle, TradeBundle, etc.)
    - tests/fixtures/ccr/generate_p8_5_minimal.py (fixture constants)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from rwa_calc.config.data_sources import DATA_SOURCES
from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.loader import DataSourceConfig, ParquetLoader

# ---------------------------------------------------------------------------
# Fixture file paths — canonical CCR parquets produced by fixture-builder
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ccr"

_TRADES_PARQUET = _FIXTURE_DIR / "trades.parquet"
_NETTING_SETS_PARQUET = _FIXTURE_DIR / "netting_sets.parquet"
_MARGIN_AGREEMENTS_PARQUET = _FIXTURE_DIR / "margin_agreements.parquet"
_CCR_COLLATERAL_PARQUET = _FIXTURE_DIR / "ccr_collateral.parquet"

# ---------------------------------------------------------------------------
# Scenario constants imported from fixture generator (single source of truth)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_crr_dataset(base_dir: Path) -> DataSourceConfig:
    """Write the minimum mandatory CRR files so ParquetLoader does not fail
    on missing required files (facilities, loans, counterparties, etc.).

    Returns a DataSourceConfig pointing at the written files.
    """
    # Minimal counterparties
    cp_df = pl.DataFrame(
        {
            "counterparty_reference": ["CP_001"],
            "counterparty_name": ["Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [100_000_000.0],
            "total_assets": [500_000_000.0],
            "default_status": [False],
        }
    )
    # Minimal facilities
    fac_df = pl.DataFrame(
        {
            "facility_reference": ["FAC_001"],
            "counterparty_reference": ["CP_001"],
        }
    )
    # Minimal loans
    loan_df = pl.DataFrame(
        {
            "loan_reference": ["LN_001"],
            "counterparty_reference": ["CP_001"],
            "drawn_amount": [0.0],
        }
    )
    # Minimal facility_mappings
    fm_df = pl.DataFrame(
        {
            "parent_facility_reference": ["FAC_001"],
            "child_reference": ["LN_001"],
        }
    )
    # Minimal lending_mappings (empty)
    lm_df = pl.DataFrame({"member_counterparty_reference": pl.Series([], dtype=pl.String)})

    base_dir.mkdir(parents=True, exist_ok=True)
    cp_path = base_dir / "counterparties.parquet"
    fac_path = base_dir / "facilities.parquet"
    loan_path = base_dir / "loans.parquet"
    fm_path = base_dir / "facility_mappings.parquet"
    lm_path = base_dir / "lending_mappings.parquet"

    cp_df.write_parquet(cp_path)
    fac_df.write_parquet(fac_path)
    loan_df.write_parquet(loan_path)
    fm_df.write_parquet(fm_path)
    lm_df.write_parquet(lm_path)

    return DataSourceConfig(
        counterparties_file=cp_path,
        facilities_file=fac_path,
        loans_file=loan_path,
        facility_mappings_file=fm_path,
        lending_mappings_file=lm_path,
    )


def _add_ccr_files_to_config(
    config: DataSourceConfig,
    trades_file: Path | None = None,
    netting_sets_file: Path | None = None,
    margin_agreements_file: Path | None = None,
    ccr_collateral_file: Path | None = None,
) -> DataSourceConfig:
    """Return a new DataSourceConfig with CCR file paths set.

    Uses dataclasses.replace-style kwarg injection into DataSourceConfig.
    Requires that DataSourceConfig has the four CCR fields added by P8.5.

    Asserts the fields exist before calling dataclasses.replace so that a
    missing field surfaces as AssertionError (FAILED) not TypeError (ERROR).
    """
    import dataclasses

    existing_fields = {f.name for f in dataclasses.fields(config)}
    for field_name in (
        "ccr_trades_file",
        "ccr_netting_sets_file",
        "ccr_margin_agreements_file",
        "ccr_collateral_file",
    ):
        assert field_name in existing_fields, (
            f"DataSourceConfig has no field '{field_name}'. "
            f"Add the four ccr_* fields to DataSourceConfig in "
            f"src/rwa_calc/engine/loader.py (P8.5). "
            f"Current fields: {sorted(existing_fields)}"
        )

    return dataclasses.replace(
        config,
        ccr_trades_file=trades_file,
        ccr_netting_sets_file=netting_sets_file,
        ccr_margin_agreements_file=margin_agreements_file,
        ccr_collateral_file=ccr_collateral_file,
    )


# ===========================================================================
# 1. Data source registry — new entries
# ===========================================================================


def test_data_source_registry_has_ccr_trades_entry() -> None:
    """DATA_SOURCES must contain a DataSourceFile with id='ccr_trades' (P8.5)."""
    # Arrange
    ids = [s.id for s in DATA_SOURCES]

    # Act + Assert
    assert "ccr_trades" in ids, (
        f"DATA_SOURCES does not contain an entry with id='ccr_trades'. "
        f"Add it to src/rwa_calc/config/data_sources.py (P8.5). "
        f"Current IDs: {ids}"
    )


def test_data_source_registry_has_ccr_netting_sets_entry() -> None:
    """DATA_SOURCES must contain a DataSourceFile with id='ccr_netting_sets' (P8.5)."""
    # Arrange
    ids = [s.id for s in DATA_SOURCES]

    # Act + Assert
    assert "ccr_netting_sets" in ids, (
        f"DATA_SOURCES does not contain an entry with id='ccr_netting_sets'. "
        f"Add it to src/rwa_calc/config/data_sources.py (P8.5). "
        f"Current IDs: {ids}"
    )


def test_data_source_registry_has_ccr_margin_agreements_entry() -> None:
    """DATA_SOURCES must contain a DataSourceFile with id='ccr_margin_agreements' (P8.5)."""
    # Arrange
    ids = [s.id for s in DATA_SOURCES]

    # Act + Assert
    assert "ccr_margin_agreements" in ids, (
        f"DATA_SOURCES does not contain an entry with id='ccr_margin_agreements'. "
        f"Add it to src/rwa_calc/config/data_sources.py (P8.5). "
        f"Current IDs: {ids}"
    )


def test_data_source_registry_has_ccr_collateral_entry() -> None:
    """DATA_SOURCES must contain a DataSourceFile with id='ccr_collateral' (P8.5)."""
    # Arrange
    ids = [s.id for s in DATA_SOURCES]

    # Act + Assert
    assert "ccr_collateral" in ids, (
        f"DATA_SOURCES does not contain an entry with id='ccr_collateral'. "
        f"Add it to src/rwa_calc/config/data_sources.py (P8.5). "
        f"Current IDs: {ids}"
    )


# ===========================================================================
# 2. Loader with all four CCR files present
# ===========================================================================


def _load_bundle_with_all_four_ccr_files(tmp_path: Path) -> RawDataBundle:
    """Build and load a bundle with all four CCR files wired in.

    Inline helper (not a fixture) so AssertionError from missing
    DataSourceConfig fields fires inside the test body — counted as FAILED,
    not ERROR.
    """
    config = _write_minimal_crr_dataset(tmp_path)
    config = _add_ccr_files_to_config(
        config,
        trades_file=_TRADES_PARQUET,
        netting_sets_file=_NETTING_SETS_PARQUET,
        margin_agreements_file=_MARGIN_AGREEMENTS_PARQUET,
        ccr_collateral_file=_CCR_COLLATERAL_PARQUET,
    )
    loader = ParquetLoader(tmp_path, config=config)
    return loader.load()


def test_loader_with_all_four_ccr_files_produces_raw_ccr_bundle(tmp_path: Path) -> None:
    """bundle.ccr must be a RawCCRBundle with all four leaf LazyFrames not None."""
    # Arrange + Act
    bundle = _load_bundle_with_all_four_ccr_files(tmp_path)
    ccr = bundle.ccr

    # Assert — ccr is not None
    assert ccr is not None, (
        "bundle.ccr must not be None when all four CCR files are present. "
        "Check that loader.py constructs and attaches a RawCCRBundle (P8.5)."
    )

    # Assert — all four leaf bundles are present
    from rwa_calc.contracts.bundles import RawCCRBundle

    assert isinstance(ccr, RawCCRBundle), (
        f"bundle.ccr must be a RawCCRBundle instance, got {type(ccr).__name__}"
    )
    assert ccr.trades is not None, "RawCCRBundle.trades must not be None"
    assert ccr.netting_sets is not None, "RawCCRBundle.netting_sets must not be None"
    assert ccr.margin_agreements is not None, "RawCCRBundle.margin_agreements must not be None"
    assert ccr.ccr_collateral is not None, "RawCCRBundle.ccr_collateral must not be None"


def test_loader_with_all_four_ccr_files_trade_count_is_one(tmp_path: Path) -> None:
    """trades LazyFrame must contain exactly 1 row (T_001)."""
    # Arrange + Act
    bundle = _load_bundle_with_all_four_ccr_files(tmp_path)
    ccr = bundle.ccr
    assert ccr is not None, "bundle.ccr is None — ccr_* fields not yet added to DataSourceConfig"

    # Act
    count = ccr.trades.trades.collect().shape[0]

    # Assert
    assert count == 1, f"trades LazyFrame must contain 1 row (T_001 from fixture), got {count}"


def test_loader_with_all_four_ccr_files_netting_set_count_is_one(tmp_path: Path) -> None:
    """netting_sets LazyFrame must contain exactly 1 row (NS_001)."""
    # Arrange + Act
    bundle = _load_bundle_with_all_four_ccr_files(tmp_path)
    ccr = bundle.ccr
    assert ccr is not None, "bundle.ccr is None — ccr_* fields not yet added to DataSourceConfig"

    # Act
    count = ccr.netting_sets.netting_sets.collect().shape[0]

    # Assert
    assert count == 1, (
        f"netting_sets LazyFrame must contain 1 row (NS_001 from fixture), got {count}"
    )


def test_loader_with_all_four_ccr_files_margin_agreement_count_is_zero(tmp_path: Path) -> None:
    """margin_agreements LazyFrame must contain 0 rows (CCR-A1: no CSA)."""
    # Arrange + Act
    bundle = _load_bundle_with_all_four_ccr_files(tmp_path)
    ccr = bundle.ccr
    assert ccr is not None, "bundle.ccr is None — ccr_* fields not yet added to DataSourceConfig"

    # Act
    count = ccr.margin_agreements.margin_agreements.collect().shape[0]

    # Assert
    assert count == 0, (
        f"margin_agreements LazyFrame must contain 0 rows (CCR-A1: unmargined), got {count}"
    )


def test_loader_with_all_four_ccr_files_ccr_collateral_count_is_zero(tmp_path: Path) -> None:
    """ccr_collateral LazyFrame must contain 0 rows (CCR-A1: no collateral)."""
    # Arrange + Act
    bundle = _load_bundle_with_all_four_ccr_files(tmp_path)
    ccr = bundle.ccr
    assert ccr is not None, "bundle.ccr is None — ccr_* fields not yet added to DataSourceConfig"

    # Act
    count = ccr.ccr_collateral.ccr_collateral.collect().shape[0]

    # Assert
    assert count == 0, (
        f"ccr_collateral LazyFrame must contain 0 rows (CCR-A1: no collateral), got {count}"
    )


# ===========================================================================
# 3. Loader with no CCR files present
# ===========================================================================


def test_loader_with_no_ccr_files_leaves_bundle_ccr_none(tmp_path: Path) -> None:
    """When none of the four CCR files are configured, bundle.ccr must be None.

    Firms without derivative or SFT books must not be required to provide CCR
    files.  The CCR stage (P8.20) no-ops when ``raw.ccr is None``.
    """
    # Arrange — minimal CRR dataset only, no CCR paths set
    config = _write_minimal_crr_dataset(tmp_path)
    # Do NOT set any ccr_* fields — leaving them at default (None or absent)
    loader = ParquetLoader(tmp_path, config=config)

    # Act
    bundle = loader.load()

    # Assert
    assert bundle.ccr is None, (
        f"bundle.ccr must be None when no CCR files are configured, got {bundle.ccr!r}. "
        f"The loader must only build a RawCCRBundle when at least one CCR file path is set."
    )


# ===========================================================================
# 4. Loader with partial CCR files — DQ007 errors accumulation
# ===========================================================================


def test_loader_with_partial_ccr_files_accumulates_dq007_errors(tmp_path: Path) -> None:
    """When 2 of 4 CCR files exist, the bundle loads but accumulates DQ007 errors.

    Per the architect's P8.5 spec: missing CCR files are treated the same as
    other optional files — ``DQ007`` errors are appended to the bundle's error
    list, not raised as exceptions.  The trade and netting_set leaf frames are
    still populated; the missing margin_agreements and ccr_collateral frames
    produce DQ007 errors.
    """
    # Arrange — provide only trades + netting_sets; omit margin_agreements and ccr_collateral
    config = _write_minimal_crr_dataset(tmp_path)
    config = _add_ccr_files_to_config(
        config,
        trades_file=_TRADES_PARQUET,
        netting_sets_file=_NETTING_SETS_PARQUET,
        margin_agreements_file=None,
        ccr_collateral_file=None,
    )
    loader = ParquetLoader(tmp_path, config=config)

    # Act
    bundle = loader.load()

    # Assert — bundle is returned (no exception raised)
    assert bundle is not None, "loader.load() must return a bundle even with partial CCR files"

    # Assert — CCR sub-bundle present (trades + netting_sets loaded OK)
    assert bundle.ccr is not None, (
        "bundle.ccr must not be None when at least trades and netting_sets are present"
    )

    # Assert — DQ007 errors for the two missing files
    all_errors = bundle.errors + bundle.ccr.errors
    dq007_errors = [e for e in all_errors if getattr(e, "code", None) == "DQ007"]
    assert len(dq007_errors) >= 2, (
        f"Expected at least 2 DQ007 errors for the two missing CCR files "
        f"(margin_agreements, ccr_collateral), got {len(dq007_errors)}. "
        f"All errors: {all_errors}"
    )
