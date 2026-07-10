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

from rwa_calc.api import create_api_app, run_index
from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clean_run_index() -> None:
    """Each test starts with an empty calculation run index (module-level state)."""
    run_index.clear()


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


@pytest.mark.parametrize(
    ("fmt", "media"),
    [("parquet", "zip"), ("csv", "zip"), ("excel", "xlsx"), ("pillar3", "xlsx")],
)
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


# =============================================================================
# Comparison export
# =============================================================================


def _register_small_comparison(comparison_id: str = "test-comparison-id") -> str:
    """Register a small comparison-export result in the shared registry; return its id."""
    from rwa_calc.api.models import ComparisonExportResponse
    from rwa_calc.api.rest import register_comparison_with_id
    from rwa_calc.contracts.bundles import CapitalImpactBundle, ComparisonBundle
    from tests.fixtures.resolved_bundle import make_aggregated_bundle

    agg = make_aggregated_bundle(results=pl.LazyFrame())
    comparison = ComparisonBundle(
        baseline_results=agg,
        variant_results=agg,
        exposure_deltas=pl.LazyFrame({"exposure_reference": ["E1"], "delta_rwa": [100.0]}),
        summary_by_class=pl.LazyFrame(
            {"exposure_class": ["corporate"], "total_delta_rwa": [100.0]}
        ),
        summary_by_approach=pl.LazyFrame(
            {"approach_applied": ["standardised"], "total_delta_rwa": [100.0]}
        ),
        baseline_label="crr",
        variant_label="b31",
    )
    impact = CapitalImpactBundle(
        exposure_attribution=pl.LazyFrame(
            {"exposure_reference": ["E1"], "methodology_impact": [100.0]}
        ),
        portfolio_waterfall=pl.LazyFrame(
            {
                "step": [1],
                "driver": ["Methodology & parameter changes"],
                "impact_rwa": [100.0],
                "cumulative_rwa": [100.0],
            }
        ),
        summary_by_class=pl.LazyFrame({"exposure_class": ["corporate"]}),
        summary_by_approach=pl.LazyFrame({"approach_applied": ["standardised"]}),
    )
    register_comparison_with_id(
        comparison_id,
        ComparisonExportResponse.from_bundles(
            comparison, impact, summary={"crr_rwa": 1.0, "b31_rwa": 2.0}
        ),
    )
    return comparison_id


@pytest.mark.parametrize(("fmt", "media"), [("csv", "zip"), ("parquet", "zip"), ("excel", "xlsx")])
def test_comparison_export_downloads(client: TestClient, fmt: str, media: str) -> None:
    # Arrange
    comparison_id = _register_small_comparison()

    # Act
    resp = client.get(f"/api/comparison/export/{fmt}", params={"comparison_id": comparison_id})

    # Assert — download succeeds; the served filename is a fixed literal (no id)
    assert resp.status_code == 200
    assert resp.content
    disposition = resp.headers.get("content-disposition", "")
    assert comparison_id not in disposition
    assert media in disposition


def test_comparison_export_unknown_id_is_404(client: TestClient) -> None:
    resp = client.get("/api/comparison/export/csv", params={"comparison_id": "nope"})
    assert resp.status_code == 404


def test_openapi_documents_reconcile(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/reconcile" in schema["paths"]
    assert "post" in schema["paths"]["/api/reconcile"]


# =============================================================================
# Reconcile — explicit run_id reuse
# =============================================================================


def _calculate_run_id(client: TestClient, data_dir: str, framework: str = "CRR") -> str:
    """Run /api/calculate and return the registered run_id."""
    resp = client.post(
        "/api/calculate",
        json={
            "data_path": data_dir,
            "framework": framework,
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    return body["run_id"]


def test_reconcile_with_run_id_reuses_registered_run(
    client: TestClient, recon_data_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a registered run; any pipeline re-run would raise.
    run_id = _calculate_run_id(client, recon_data_dir)
    monkeypatch.setattr(
        CreditRiskCalc,
        "calculate",
        lambda self: (_ for _ in ()).throw(AssertionError("pipeline re-run")),
    )
    body = _reconcile_body(recon_data_dir)
    body["run_id"] = run_id

    # Act
    resp = client.post("/api/reconcile", json=body)

    # Assert — reconciled off the cached run (the nudged RWA still breaks).
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["has_breaks"] is True


def test_reconcile_with_unknown_run_id_is_404(client: TestClient, recon_data_dir: str) -> None:
    body = _reconcile_body(recon_data_dir)
    body["run_id"] = "not-a-run"

    resp = client.post("/api/reconcile", json=body)

    assert resp.status_code == 404


def test_reconcile_with_mismatched_run_is_422(client: TestClient, recon_data_dir: str) -> None:
    # An explicit run_id whose framework does not match the request must not be
    # silently recomputed — the caller asked for THAT run.
    run_id = _calculate_run_id(client, recon_data_dir, framework="CRR")
    body = _reconcile_body(recon_data_dir)
    body["framework"] = "BASEL_3_1"
    body["run_id"] = run_id

    resp = client.post("/api/reconcile", json=body)

    assert resp.status_code == 422
    assert "framework" in resp.json()["detail"]


def test_reconcile_with_failed_run_id_is_422(client: TestClient, tmp_path: Path) -> None:
    # A failed calculation is registered too; explicitly reusing it is an error.
    empty = tmp_path / "empty"
    empty.mkdir()
    resp = client.post(
        "/api/calculate",
        json={
            "data_path": str(empty),
            "framework": "CRR",
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
        },
    )
    run_id = resp.json()["run_id"]
    assert resp.json()["success"] is False

    body = _reconcile_body(str(empty))
    body["run_id"] = run_id

    assert client.post("/api/reconcile", json=body).status_code == 422


def test_api_calculate_seeds_run_index(client: TestClient, data_dir: str) -> None:
    run_id = _calculate_run_id(client, data_dir)

    fingerprint = run_index.compute_fingerprint(
        data_path=data_dir,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        permission_mode="standardised",
        data_format="parquet",
    )
    hit = run_index.find_reusable(fingerprint)

    assert hit is not None
    assert hit.run_id == run_id


def test_api_comparison_seeds_run_index_for_both_frameworks(
    client: TestClient, data_dir: str
) -> None:
    resp = client.post(
        "/api/comparison",
        json={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
        },
    )
    assert resp.status_code == 200

    for framework in ("CRR", "BASEL_3_1"):
        fingerprint = run_index.compute_fingerprint(
            data_path=data_dir,
            framework=framework,
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
        )
        assert run_index.find_reusable(fingerprint) is not None, framework
