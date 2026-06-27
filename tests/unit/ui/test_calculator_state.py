"""
Unit tests for the calculator last-run persistence helper.

Pipeline position:
    ui.app.calculator_state (save/load_calculator_state) — exercised in isolation.

Key responsibilities tested:
- Round-tripping ``CalculatorFormState`` through the JSON state file, including the
  comma-encoded ``output_formats`` list.
- Graceful degradation: a missing, corrupt or partial file loads as ``None`` and
  never raises; saving swallows IO errors.
- The ``RWA_STATE_DIR`` env var redirects the state file (the test seam).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rwa_calc.ui.app.calculator_state import (
    STATE_DIR_ENV_VAR,
    CalculatorFormState,
    _state_file,
    load_calculator_state,
    save_calculator_state,
)


def _sample_state() -> CalculatorFormState:
    return CalculatorFormState(
        data_path="/data/2025-q1",
        reporting_date="2025-03-31",
        framework="BASEL_3_1",
        permission_mode="irb",
        data_format="csv",
        output_folder="/out/rwa",
        output_formats="parquet,csv",
    )


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the state file into tmp so the real home dir is never touched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


def test_round_trip_preserves_all_fields() -> None:
    save_calculator_state(_sample_state())
    assert load_calculator_state() == _sample_state()


def test_formats_property_splits_the_comma_encoded_list() -> None:
    assert _sample_state().formats == ["parquet", "csv"]


def test_empty_formats_property_is_empty_list() -> None:
    state = CalculatorFormState(
        data_path="/d",
        reporting_date="2025-01-01",
        framework="CRR",
        permission_mode="standardised",
        data_format="parquet",
        output_folder="",
        output_formats="",
    )
    assert state.formats == []


def test_missing_file_loads_as_none() -> None:
    assert load_calculator_state() is None


def test_corrupt_json_loads_as_none() -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert load_calculator_state() is None


def test_partial_json_loads_as_none() -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"data_path": "/d"}', encoding="utf-8")
    assert load_calculator_state() is None


def test_env_override_points_state_file_under_tmp(tmp_path: Path) -> None:
    assert _state_file() == tmp_path / "state" / "calculator_last_run.json"


def test_save_swallows_io_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point the state DIR at an existing *file* so mkdir() raises.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(blocker))
    save_calculator_state(_sample_state())  # must not raise
