"""
Unit tests: form-state persistence of the reporting scope (multi-entity reporting).

The calculator and reconciliation forms remember the optional reporting scope
across runs, and — critically — a state file written *before* the scope fields
existed still loads (the scope opens blank) rather than being discarded, so an
upgrade never wipes a user's remembered form.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rwa_calc.ui.app.calculator_state import (
    STATE_DIR_ENV_VAR,
    CalculatorFormState,
    load_calculator_state,
    save_calculator_state,
)
from rwa_calc.ui.app.recon_state import (
    ReconciliationFormState,
    load_last_run,
    save_last_run,
)


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the per-user state files into tmp so ~/.rwa_calc is untouched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


# =============================================================================
# Calculator form-state
# =============================================================================


def test_calculator_state_round_trips_scope() -> None:
    # Arrange
    save_calculator_state(
        CalculatorFormState(
            data_path="/data",
            reporting_date="2025-01-01",
            framework="CRR",
            permission_mode="standardised",
            data_format="parquet",
            output_folder="",
            output_formats="parquet,csv",
            reporting_entity="ACME",
            reporting_basis="consolidated",
        )
    )

    # Act
    loaded = load_calculator_state()

    # Assert
    assert loaded is not None
    assert loaded.reporting_entity == "ACME"
    assert loaded.reporting_basis == "consolidated"


def test_calculator_state_defaults_scope_blank_when_unset() -> None:
    save_calculator_state(
        CalculatorFormState(
            data_path="/data",
            reporting_date="2025-01-01",
            framework="CRR",
            permission_mode="standardised",
            data_format="parquet",
            output_folder="",
            output_formats="",
        )
    )
    loaded = load_calculator_state()
    assert loaded is not None
    assert loaded.reporting_entity == ""
    assert loaded.reporting_basis == ""


def test_calculator_state_loads_legacy_file_without_scope_keys(
    tmp_path: Path,
) -> None:
    # Arrange — a state file written before the scope fields existed.
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "calculator_last_run.json").write_text(
        json.dumps(
            {
                "data_path": "/legacy",
                "reporting_date": "2024-12-31",
                "framework": "BASEL_3_1",
                "permission_mode": "irb",
                "data_format": "csv",
                "output_folder": "/out",
                "output_formats": "excel",
            }
        ),
        encoding="utf-8",
    )

    # Act
    loaded = load_calculator_state()

    # Assert — the core fields survive; the new scope fields default blank
    # (the file is NOT discarded just because it predates the scope).
    assert loaded is not None
    assert loaded.data_path == "/legacy"
    assert loaded.output_formats == "excel"
    assert loaded.reporting_entity == ""
    assert loaded.reporting_basis == ""


# =============================================================================
# Reconciliation form-state
# =============================================================================


def test_reconciliation_state_round_trips_scope() -> None:
    save_last_run(
        ReconciliationFormState(
            data_path="/data",
            reporting_date="2025-01-01",
            framework="CRR",
            permission_mode="standardised",
            data_format="parquet",
            mapping_toml="x = 1",
            reporting_entity="BETA",
            reporting_basis="sub_consolidated",
        )
    )
    loaded = load_last_run()
    assert loaded is not None
    assert loaded.reporting_entity == "BETA"
    assert loaded.reporting_basis == "sub_consolidated"


def test_reconciliation_state_loads_legacy_file_without_scope_keys(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "reconciliation_last_run.json").write_text(
        json.dumps(
            {
                "data_path": "/legacy",
                "reporting_date": "2024-12-31",
                "framework": "CRR",
                "permission_mode": "standardised",
                "data_format": "parquet",
                "mapping_toml": "y = 2",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_last_run()
    assert loaded is not None
    assert loaded.data_path == "/legacy"
    assert loaded.mapping_toml == "y = 2"
    assert loaded.reporting_entity == ""
    assert loaded.reporting_basis == ""
