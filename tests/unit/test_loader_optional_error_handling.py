"""Unit tests for P6.18: narrow exception handling in _load_file_optional.

Tests verify that:
- FileNotFoundError -> returns None, no DQ007 error appended, no WARNING log.
- Other exceptions (corrupt parquet, OSError) -> returns None, appends DQ007
  CalculationError (severity WARNING, category DATA_QUALITY), emits lazy-
  formatted WARNING log via rwa_calc.engine.loader logger.
- _load_file (required files) -> still raises DataLoadError for corrupt files
  (regression guard).
- Path is None (optional not configured) -> silent None.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts import errors as _errors
from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.loader import (
    DataLoadError,
    DataSourceConfig,
    ParquetLoader,
)

# ---------------------------------------------------------------------------
# Helpers — build a minimal valid required-files layout in tmp_path
# ---------------------------------------------------------------------------


def _write_valid_required_files(base: Path) -> None:
    """Write the four required parquet files (facilities, loans, counterparty, mappings)."""
    (base / "exposures").mkdir(parents=True, exist_ok=True)
    (base / "counterparty").mkdir(parents=True, exist_ok=True)
    (base / "mapping").mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "facility_id": ["FAC001"],
            "counterparty_id": ["CORP001"],
            "facility_type": ["TERM_LOAN"],
        }
    ).write_parquet(base / "exposures" / "facilities.parquet")

    pl.DataFrame(
        {
            "loan_id": ["LOAN001"],
            "facility_id": ["FAC001"],
            "outstanding_balance": [1_000_000.0],
        }
    ).write_parquet(base / "exposures" / "loans.parquet")

    pl.DataFrame(
        {
            "loan_id": ["LOAN001"],
            "facility_id": ["FAC001"],
        }
    ).write_parquet(base / "exposures" / "facility_mapping.parquet")

    pl.DataFrame(
        {
            "counterparty_id": ["SOV001", "CORP001"],
            "counterparty_type": ["SOVEREIGN", "CORPORATE"],
            "name": ["Test Sovereign", "Test Corporate"],
        }
    ).write_parquet(base / "counterparty" / "counterparties.parquet")

    pl.DataFrame(
        {
            "counterparty_id": ["CORP001"],
            "lending_group_id": ["LG001"],
        }
    ).write_parquet(base / "mapping" / "lending_mapping.parquet")


def _write_corrupt_collateral(base: Path) -> None:
    """Write b'not parquet' to the optional collateral file path."""
    (base / "collateral").mkdir(parents=True, exist_ok=True)
    (base / "collateral" / "collateral.parquet").write_bytes(b"not parquet")


# ---------------------------------------------------------------------------
# DataSourceConfig that uses only required files + optional collateral
# ---------------------------------------------------------------------------


def _config_with_collateral(base: Path) -> DataSourceConfig:
    """Return a DataSourceConfig pointing at the minimal required set + collateral."""
    return DataSourceConfig(
        facilities_file=Path("exposures/facilities.parquet"),
        loans_file=Path("exposures/loans.parquet"),
        counterparties_file=Path("counterparty/counterparties.parquet"),
        facility_mappings_file=Path("exposures/facility_mapping.parquet"),
        lending_mappings_file=Path("mapping/lending_mapping.parquet"),
        collateral_file=Path("collateral/collateral.parquet"),
        # all other optionals left as None (not configured)
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOptionalFileCorruptAppendsDQ007:
    """Corrupt optional file -> DQ007 warning in bundle.errors, collateral is None."""

    def test_optional_file_corrupt_appends_dq007_warning_and_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Corrupt optional file -> DQ007 CalculationError appended; bundle.collateral is None.

        Arrange: valid required files + malformed bytes at collateral path.
        Act:     loader.load() -> RawDataBundle.
        Assert:  collateral is None; exactly one DQ007 WARNING DATA_QUALITY error
                 with field_name == "collateral".
        """
        # --- Assert: DQ007 constant exists (will fail today — drives P6.18) ---
        dq007 = getattr(_errors, "ERROR_OPTIONAL_FILE_UNREADABLE", None)
        assert dq007 is not None, (
            "expected rwa_calc.contracts.errors.ERROR_OPTIONAL_FILE_UNREADABLE = 'DQ007' "
            "(see plan item P6.18); not yet implemented"
        )
        assert dq007 == "DQ007"

        # Arrange
        _write_valid_required_files(tmp_path)
        _write_corrupt_collateral(tmp_path)
        loader = ParquetLoader(tmp_path, config=_config_with_collateral(tmp_path))

        # Act
        bundle: RawDataBundle = loader.load()

        # Assert — optional field is None
        assert bundle.collateral is None

        # Assert — exactly one DQ007 error
        dq007_errors = [e for e in bundle.errors if e.code == "DQ007"]
        assert len(dq007_errors) == 1, (
            f"expected exactly 1 DQ007 error; got {len(dq007_errors)}: {bundle.errors}"
        )

        err = dq007_errors[0]
        assert err.severity == ErrorSeverity.WARNING
        assert err.category == ErrorCategory.DATA_QUALITY
        assert err.field_name == "collateral"


class TestOptionalFileMissingNoError:
    """FileNotFoundError (missing optional) -> no DQ007 entry, bundle.collateral is None."""

    def test_optional_file_missing_does_not_append_error(self, tmp_path: Path) -> None:
        """Omitting the optional file entirely must not produce any DQ007 errors.

        Arrange: valid required files only; collateral directory/file absent.
        Act:     loader.load() -> RawDataBundle.
        Assert:  collateral is None; no DQ007 in bundle.errors.
        """
        # Arrange
        _write_valid_required_files(tmp_path)
        # collateral dir deliberately not created — FileNotFoundError path
        loader = ParquetLoader(tmp_path, config=_config_with_collateral(tmp_path))

        # Act
        bundle: RawDataBundle = loader.load()

        # Assert
        assert bundle.collateral is None
        dq007_errors = [e for e in bundle.errors if e.code == "DQ007"]
        assert len(dq007_errors) == 0, (
            f"FileNotFoundError must not produce DQ007; got: {dq007_errors}"
        )


class TestOptionalFileCorruptEmitsLazyFormattedWarningLog:
    """Corrupt optional file -> exactly one WARNING log with lazy %s formatting."""

    def test_optional_file_corrupt_emits_lazy_formatted_warning_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt optional file -> single lazy-formatted WARNING at rwa_calc.engine.loader.

        CLAUDE.md § Logging: use logger.warning("... %s ...", path, exc), not f-strings.
        A lazy-formatted record has non-empty record.args.

        Arrange: valid required files + corrupt collateral.
        Act:     loader.load() inside caplog.at_level(WARNING).
        Assert:  exactly one WARNING record at 'rwa_calc.engine.loader';
                 record.args is non-empty (lazy formatting, not pre-formatted message).
        """
        _write_valid_required_files(tmp_path)
        _write_corrupt_collateral(tmp_path)
        loader = ParquetLoader(tmp_path, config=_config_with_collateral(tmp_path))

        # rwa_calc.observability.configure_logging() sets propagate=False on the
        # `rwa_calc` namespace logger, which prevents caplog (attached to root)
        # from seeing records from descendants like rwa_calc.engine.loader.
        # Temporarily re-enable propagation so the test captures the warning.
        namespace_logger = logging.getLogger("rwa_calc")
        saved_propagate = namespace_logger.propagate
        namespace_logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="rwa_calc.engine.loader"):
                loader.load()
        finally:
            namespace_logger.propagate = saved_propagate

        loader_warnings = [
            r
            for r in caplog.records
            if r.name == "rwa_calc.engine.loader" and r.levelno == logging.WARNING
        ]
        assert len(loader_warnings) == 1, (
            f"expected exactly 1 WARNING from rwa_calc.engine.loader; "
            f"got {len(loader_warnings)}: {[r.getMessage() for r in loader_warnings]}"
        )
        record = loader_warnings[0]
        # Lazy formatting: record.args must be non-empty (not an f-string)
        assert record.args, (
            "logger.warning() must use lazy %s formatting (record.args must be non-empty); "
            "do not use f-strings in warning log calls (CLAUDE.md § Logging)"
        )


class TestRequiredFileCorruptStillRaisesDataLoadError:
    """Regression: corrupt required file -> DataLoadError is still raised (unchanged path)."""

    def test_required_file_corrupt_still_raises_data_load_error(self, tmp_path: Path) -> None:
        """_load_file behaviour is unchanged: corrupt required file raises DataLoadError.

        Arrange: corrupt facilities.parquet (required file).
        Act:     loader.load().
        Assert:  DataLoadError is raised.
        """
        # Write only the required dirs/files minus facilities (which we corrupt)
        _write_valid_required_files(tmp_path)
        # Overwrite facilities with corrupt bytes
        (tmp_path / "exposures" / "facilities.parquet").write_bytes(b"not parquet at all")

        loader = ParquetLoader(
            tmp_path,
            config=DataSourceConfig(
                facilities_file=Path("exposures/facilities.parquet"),
                loans_file=Path("exposures/loans.parquet"),
                counterparties_file=Path("counterparty/counterparties.parquet"),
                facility_mappings_file=Path("exposures/facility_mapping.parquet"),
                lending_mappings_file=Path("mapping/lending_mapping.parquet"),
            ),
        )

        with pytest.raises(DataLoadError):
            loader.load()
