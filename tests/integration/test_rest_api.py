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

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.api import create_api_app
from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
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


@pytest.fixture
def recon_data_dir(tmp_path: Path) -> str:
    """Mandatory-minimum dataset plus a legacy_output.csv derived from our results."""
    write_mandatory_minimum(tmp_path)
    ours = (
        CreditRiskCalc(
            data_path=str(tmp_path),
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
        )
        .calculate()
        .scan_results()
        .select("exposure_reference", "ead_final", "rwa_final")
        .collect()
    )
    legacy = (
        ours.rename({"ead_final": "EAD", "rwa_final": "RWA"})
        .with_row_index("_i")
        .with_columns(
            pl.when(pl.col("_i") == 0)
            .then(pl.col("RWA") * 1.5)
            .otherwise(pl.col("RWA"))
            .alias("RWA")
        )
        .drop("_i")
    )
    legacy.write_csv(tmp_path / "legacy_output.csv")
    return str(tmp_path)


def _reconcile_body(data_dir: str) -> dict:
    return {
        "data_path": data_dir,
        "reporting_date": "2025-01-01",
        "framework": "CRR",
        "permission_mode": "standardised",
        "data_format": "parquet",
        "mapping_toml": DEFAULT_MAPPING_TOML,
    }


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


def test_openapi_documents_results_404(client: TestClient) -> None:
    # Assert — the 404 is documented in the OpenAPI schema (SonarQube fix)
    schema = client.get("/openapi.json").json()
    assert "404" in schema["paths"]["/api/results"]["get"]["responses"]


@pytest.mark.parametrize(("fmt", "media"), [("parquet", "zip"), ("excel", "xlsx")])
def test_export_downloads_with_fixed_filename(
    client: TestClient, data_dir: str, fmt: str, media: str
) -> None:
    # Arrange
    run_id = client.post(
        "/api/calculate",
        json={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
        },
    ).json()["run_id"]

    # Act
    resp = client.get(f"/api/export/{fmt}", params={"run_id": run_id})

    # Assert — download succeeds; the served filename is a fixed literal (no run_id)
    assert resp.status_code == 200
    assert resp.content
    disposition = resp.headers.get("content-disposition", "")
    assert run_id not in disposition
    assert media in disposition


# =============================================================================
# Reconciliation
# =============================================================================


def test_reconcile_returns_id_and_tiers(client: TestClient, recon_data_dir: str) -> None:
    # Act
    resp = client.post("/api/reconcile", json=_reconcile_body(recon_data_dir))

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["recon_id"]
    assert body["success"] is True
    assert body["has_breaks"] is True  # the nudged RWA breaks
    assert body["totals_tie_out"]["columns"]
    assert body["summary_by_component"]["rows"]
    assert "breaks_detail" in body


def test_reconcile_invalid_config_is_422(client: TestClient, recon_data_dir: str) -> None:
    # Arrange — invalid TOML in the mapping
    body = _reconcile_body(recon_data_dir)
    body["mapping_toml"] = "not valid ["

    # Act
    resp = client.post("/api/reconcile", json=body)

    # Assert
    assert resp.status_code == 422


@pytest.mark.parametrize(("fmt", "media"), [("csv", "zip"), ("excel", "xlsx")])
def test_reconcile_export_downloads(
    client: TestClient, recon_data_dir: str, fmt: str, media: str
) -> None:
    # Arrange
    recon_id = client.post("/api/reconcile", json=_reconcile_body(recon_data_dir)).json()[
        "recon_id"
    ]

    # Act
    resp = client.get(f"/api/reconcile/export/{fmt}", params={"recon_id": recon_id})

    # Assert — download succeeds; the served filename is a fixed literal (no recon_id)
    assert resp.status_code == 200
    assert resp.content
    disposition = resp.headers.get("content-disposition", "")
    assert recon_id not in disposition
    assert media in disposition


def test_reconcile_export_unknown_id_is_404(client: TestClient) -> None:
    assert client.get("/api/reconcile/export/csv", params={"recon_id": "nope"}).status_code == 404


def test_openapi_documents_reconcile(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/reconcile" in schema["paths"]
    assert "post" in schema["paths"]["/api/reconcile"]
