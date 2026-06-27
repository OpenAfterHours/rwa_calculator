"""
Unit tests for the reconciliation sign-off store (ui.app.recon_signoff).

Key responsibilities tested:
- Round-tripping a ``Decision`` (status + reason) through the JSON store, keyed by
  ``_recon_key`` within a workspace; upsert overwrites; clear (reopen) removes.
- Workspace isolation: decisions for one dataset never leak into another.
- ``workspace_id`` is deterministic (stable across re-runs) and discriminates
  different datasets / mappings — the property that lets decisions survive a re-run.
- Graceful degradation: a missing or corrupt store loads as empty and never raises;
  a save failure is swallowed so a sign-off click cannot 500.
- Writes are atomic — no stray ``.tmp`` file is left behind.
- The ``RWA_STATE_DIR`` env var redirects the store (keeps the real ~/.rwa_calc safe).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rwa_calc.ui.app.recon_signoff import (
    STATE_DIR_ENV_VAR,
    Decision,
    _state_file,
    clear_all_decisions,
    clear_decision,
    load_decisions,
    upsert_decision,
    workspace_id,
)

_WS = "workspace-a"
_OTHER_WS = "workspace-b"


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the store into tmp so the real home dir is never touched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


# =============================================================================
# Round-trip / mutation
# =============================================================================


def test_upsert_then_load_round_trips_a_decision() -> None:
    # Act
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "FX timing, immaterial")
    loaded = load_decisions(_WS)

    # Assert
    assert "L1" in loaded
    decision = loaded["L1"]
    assert isinstance(decision, Decision)
    assert decision.status == "accepted"
    assert decision.reason == "FX timing, immaterial"
    assert decision.decided_at  # a non-empty ISO stamp


def test_upsert_overwrites_an_existing_decision() -> None:
    # Arrange
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "first call")

    # Act — re-disposition the same key
    upsert_decision(_WS, "/data/q1", "L1", "rejected", "actually a real break")

    # Assert — only the latest decision survives
    decision = load_decisions(_WS)["L1"]
    assert decision.status == "rejected"
    assert decision.reason == "actually a real break"


def test_accept_allows_an_empty_reason() -> None:
    # Act — quick inline accept carries no reason
    upsert_decision(_WS, "/data/q1", "L9", "accepted", "")

    # Assert
    assert load_decisions(_WS)["L9"].reason == ""


def test_clear_removes_a_decision() -> None:
    # Arrange
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "ok")
    assert "L1" in load_decisions(_WS)

    # Act
    clear_decision(_WS, "L1")

    # Assert
    assert "L1" not in load_decisions(_WS)


def test_clear_is_safe_for_unknown_key_and_workspace() -> None:
    # Act / Assert — clearing nothing must not raise
    clear_decision(_WS, "NOPE")
    clear_decision("never-seen", "NOPE")
    assert load_decisions(_WS) == {}


# =============================================================================
# Workspace isolation
# =============================================================================


def test_decisions_are_isolated_per_workspace() -> None:
    # Arrange — same key string in two workspaces
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "ws-a reason")
    upsert_decision(_OTHER_WS, "/data/q2", "L1", "rejected", "ws-b reason")

    # Assert — each workspace sees only its own decision
    assert load_decisions(_WS)["L1"].status == "accepted"
    assert load_decisions(_OTHER_WS)["L1"].status == "rejected"


def test_load_unknown_workspace_is_empty() -> None:
    assert load_decisions("nothing-here") == {}


# =============================================================================
# workspace_id determinism
# =============================================================================


def test_workspace_id_is_stable_for_identical_inputs() -> None:
    a = workspace_id(
        "/data/q1", ("exposure_reference",), ("exposure_reference",), "/data/q1/leg.csv"
    )
    b = workspace_id(
        "/data/q1", ("exposure_reference",), ("exposure_reference",), "/data/q1/leg.csv"
    )
    assert a == b


def test_workspace_id_differs_for_different_data_path() -> None:
    a = workspace_id("/data/q1", ("exposure_reference",), ("exposure_reference",), "/data/leg.csv")
    b = workspace_id("/data/q2", ("exposure_reference",), ("exposure_reference",), "/data/leg.csv")
    assert a != b


def test_workspace_id_differs_for_different_keys() -> None:
    a = workspace_id("/data/q1", ("exposure_reference",), ("exposure_reference",), "/data/leg.csv")
    b = workspace_id(
        "/data/q1",
        ("exposure_reference", "exposure_class"),
        ("exposure_reference", "Asset_Class"),
        "/data/leg.csv",
    )
    assert a != b


# =============================================================================
# Resilience
# =============================================================================


def test_missing_store_loads_as_empty() -> None:
    assert load_decisions(_WS) == {}


def test_corrupt_store_loads_as_empty() -> None:
    # Arrange
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    # Act / Assert — does not raise
    assert load_decisions(_WS) == {}


def test_partial_decision_record_is_skipped_not_fatal() -> None:
    # Arrange — one valid decision, then hand-corrupt a second record
    upsert_decision(_WS, "/data/q1", "GOOD", "accepted", "fine")
    path = _state_file()
    store = json.loads(path.read_text(encoding="utf-8"))
    store[_WS]["decisions"]["BAD"] = {"reason": "missing status"}
    path.write_text(json.dumps(store), encoding="utf-8")

    # Act
    loaded = load_decisions(_WS)

    # Assert — the good record survives, the bad one is dropped
    assert "GOOD" in loaded
    assert "BAD" not in loaded


def test_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        upsert_decision(_WS, "/data/q1", "L1", "maybe", "huh")


def test_save_swallows_io_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — point the state DIR at an existing *file* so mkdir() raises
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(blocker))

    # Act / Assert — must not raise despite the unwritable path
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "ok")


def test_no_temp_file_left_after_save(tmp_path: Path) -> None:
    # Act
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "ok")

    # Assert — only the store file exists, no stray .tmp
    state_dir = tmp_path / "state"
    leftovers = [p.name for p in state_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_env_override_points_store_under_tmp(tmp_path: Path) -> None:
    assert _state_file() == tmp_path / "state" / "reconciliation_signoff.json"


# =============================================================================
# Fingerprint + clear-all
# =============================================================================


def test_upsert_stores_and_loads_the_fingerprint() -> None:
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "ok", "FP-123")
    assert load_decisions(_WS)["L1"].fingerprint == "FP-123"


def test_decision_without_fingerprint_loads_with_empty_string() -> None:
    # A pre-fingerprint record (no "fingerprint" key) must still load.
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"status": "accepted", "reason": "r", "decided_at": "t"}
    path.write_text(json.dumps({_WS: {"decisions": {"L1": record}}}), encoding="utf-8")
    assert load_decisions(_WS)["L1"].fingerprint == ""


def test_clear_all_removes_every_decision_in_the_workspace() -> None:
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "a")
    upsert_decision(_WS, "/data/q1", "L2", "rejected", "b")

    clear_all_decisions(_WS)

    assert load_decisions(_WS) == {}


def test_clear_all_is_isolated_to_one_workspace() -> None:
    upsert_decision(_WS, "/data/q1", "L1", "accepted", "a")
    upsert_decision(_OTHER_WS, "/data/q2", "L1", "accepted", "b")

    clear_all_decisions(_WS)

    assert load_decisions(_WS) == {}
    assert "L1" in load_decisions(_OTHER_WS)


def test_clear_all_is_safe_for_unknown_workspace() -> None:
    clear_all_decisions("never-seen")  # must not raise
    assert load_decisions(_WS) == {}
