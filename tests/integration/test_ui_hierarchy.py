"""
Integration test: the reporting-hierarchy page (GET /hierarchy).

Pipeline position:
    TestClient -> FastAPI /hierarchy route -> read_reporting_entities
        -> ui.views.hierarchy -> Jinja tree

Key responsibilities tested:
- A data path with a registry renders the tree: BANK_A / BANK_B nested under the
  GRP apex, with scope-headship badges and the group-apex marker.
- An absent registry renders the friendly empty state (explains what
  config/reporting_entities is), not a crash.
- No data_path renders the prompt state; a bad path renders a graceful error
  callout (never a 500).
- The calculator form links through to the hierarchy page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rwa_calc.api import run_index
from rwa_calc.ui.app.calculator_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.app.main import create_app
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum
from tests.fixtures.multi_entity.multi_entity import save_multi_entity_fixtures


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the per-user state home into tmp so ~/.rwa_calc is untouched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_run_index() -> None:
    """Each test starts with an empty calculation run index (module-level state)."""
    run_index.clear()


@pytest.fixture
def client() -> TestClient:
    # A loopback host so the app's TrustedHostMiddleware accepts the request.
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def multi_entity_dir(tmp_path: Path) -> str:
    root = tmp_path / "data"
    root.mkdir()
    save_multi_entity_fixtures(root)
    return str(root)


@pytest.fixture
def unscoped_dir(tmp_path: Path) -> str:
    # Mandatory-minimum dataset with no config/reporting_entities table.
    root = tmp_path / "data"
    root.mkdir()
    write_mandatory_minimum(root)
    return str(root)


def test_hierarchy_renders_banks_nested_under_apex(
    client: TestClient, multi_entity_dir: str
) -> None:
    # Act
    resp = client.get("/hierarchy", params={"data_path": multi_entity_dir})

    # Assert — 200, both subsidiaries render under the GRP apex.
    assert resp.status_code == 200
    text = resp.text
    assert "BANK_A" in text
    assert "BANK_B" in text
    assert "Group apex" in text  # GRP is the true apex
    # Nesting: the apex card renders before its children.
    assert text.index("GRP") < text.index("BANK_A")
    assert text.index("GRP") < text.index("BANK_B")
    # Scope-headship badges surface (consolidated at the apex, individual leaves).
    assert "Consolidated" in text
    assert "Individual" in text


def test_absent_registry_renders_empty_state(client: TestClient, unscoped_dir: str) -> None:
    # Act
    resp = client.get("/hierarchy", params={"data_path": unscoped_dir})

    # Assert — friendly empty state naming the optional table, not a crash.
    assert resp.status_code == 200
    assert "config/reporting_entities" in resp.text
    assert "unscoped" in resp.text.lower()


def test_no_data_path_renders_prompt(client: TestClient) -> None:
    # Act
    resp = client.get("/hierarchy")

    # Assert — the prompt state asks for a data path.
    assert resp.status_code == 200
    assert "Enter the path to your data directory" in resp.text


def test_bad_data_path_is_graceful_error(client: TestClient) -> None:
    # Act — a path that is not a directory.
    resp = client.get("/hierarchy", params={"data_path": "/no/such/directory/here"})

    # Assert — a friendly callout, never a 500.
    assert resp.status_code == 200
    assert "Not a data directory" in resp.text


def test_calculator_form_links_to_hierarchy(client: TestClient) -> None:
    # Act
    resp = client.get("/calculator")

    # Assert — the scoped-submission helper link is present.
    assert resp.status_code == 200
    assert "/hierarchy" in resp.text
    assert "View reporting hierarchy" in resp.text
