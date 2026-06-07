"""
Integration test: REST API (library-first HTTP contract).

Pipeline position:
    HTTP client (TestClient) -> rest.router -> CreditRiskCalc -> CalculationResponse

Key responsibilities tested:
- GET  /api/frameworks lists CRR and BASEL_3_1.
- POST /api/validate accepts the mandatory-minimum dataset in standardised mode.
- POST /api/calculate runs a real SA calculation, returns success=True, a
  positive total_rwa, and a run_id.
- GET  /api/results pages the registered run's cached results.
- The OpenAPI schema documents the calculate endpoint.

Uses the mandatory-minimum on-disk fixture (one SA-eligible corporate loan) so
the calculation reaches the engine and produces a non-zero RWA.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rwa_calc.api import create_api_app
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client() -> TestClient:
    """A TestClient over a standalone API app."""
    return TestClient(create_api_app())


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    """Mandatory-minimum SA dataset written to disk; returns the path string."""
    write_mandatory_minimum(tmp_path)
    return str(tmp_path)


# =============================================================================
# Tests
# =============================================================================


def test_frameworks_lists_both(client: TestClient) -> None:
    # Act
    resp = client.get("/api/frameworks")

    # Assert
    assert resp.status_code == 200
    ids = {f["id"] for f in resp.json()}
    assert ids == {"CRR", "BASEL_3_1"}


def test_validate_standardised_is_valid(client: TestClient, data_dir: str) -> None:
    # Act
    resp = client.post(
        "/api/validate",
        json={"data_path": data_dir, "data_format": "parquet", "permission_mode": "standardised"},
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_calculate_returns_run_id_and_positive_rwa(client: TestClient, data_dir: str) -> None:
    # Act
    resp = client.post(
        "/api/calculate",
        json={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": date(2025, 1, 1).isoformat(),
            "permission_mode": "standardised",
        },
    )

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["run_id"]
    assert body["summary"]["total_rwa"] > 0


def test_results_pages_registered_run(client: TestClient, data_dir: str) -> None:
    # Arrange — run a calculation to register a run_id
    run_id = client.post(
        "/api/calculate",
        json={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": date(2025, 1, 1).isoformat(),
            "permission_mode": "standardised",
        },
    ).json()["run_id"]

    # Act
    resp = client.get("/api/results", params={"run_id": run_id, "limit": 50})

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert len(body["rows"]) >= 1
    assert body["columns"]


def test_results_unknown_run_id_is_404(client: TestClient) -> None:
    # Act
    resp = client.get("/api/results", params={"run_id": "does-not-exist"})

    # Assert
    assert resp.status_code == 404


def test_openapi_documents_calculate(client: TestClient) -> None:
    # Act
    schema = client.get("/openapi.json").json()

    # Assert
    assert "/api/calculate" in schema["paths"]
    assert "post" in schema["paths"]["/api/calculate"]
