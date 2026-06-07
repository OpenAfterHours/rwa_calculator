"""
Integration test: server-rendered UI app (the rwa-ui surface).

Pipeline position:
    TestClient -> FastAPI page routes -> CreditRiskCalc / ui.views -> Jinja + SVG

Key responsibilities tested:
- The landing / calculator / comparison / workbench pages render.
- POST /calculate runs a real SA calculation and the results page shows the
  headline cards, an inline SVG chart, and the exposure table.
- POST /comparison runs both frameworks and renders the executive summary.
- Invalid data paths re-render the form with an error; unknown run ids 404.
- The REST API and the shared tokens.css are served from the same app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rwa_calc.ui.app.main import create_app
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    write_mandatory_minimum(tmp_path)
    return str(tmp_path)


def test_static_pages_render(client: TestClient) -> None:
    for path in ("/", "/calculator", "/comparison", "/workbench"):
        assert client.get(path).status_code == 200, path


def test_calculate_renders_results_with_chart_and_table(client: TestClient, data_dir: str) -> None:
    # Act — TestClient follows the 303 redirect to /results/{run_id}
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
            "data_format": "parquet",
        },
    )

    # Assert
    assert resp.status_code == 200
    assert "Total RWA" in resp.text
    assert '<svg class="chart"' in resp.text
    assert "exposure_reference" in resp.text


def test_comparison_renders_executive_summary(client: TestClient, data_dir: str) -> None:
    # Act
    resp = client.post(
        "/comparison",
        data={
            "data_path": data_dir,
            "reporting_date": "2027-06-30",
            "permission_mode": "standardised",
            "data_format": "parquet",
        },
    )

    # Assert
    assert resp.status_code == 200
    assert "Executive summary" in resp.text
    assert "Comparison failed" not in resp.text


def test_invalid_path_rerenders_form_with_error(client: TestClient) -> None:
    # Act
    resp = client.post(
        "/calculate",
        data={"data_path": "/no/such/dir", "reporting_date": "2025-01-01"},
    )

    # Assert
    assert resp.status_code == 400
    assert "invalid" in resp.text.lower()


def test_unknown_run_id_is_404(client: TestClient) -> None:
    assert client.get("/results/does-not-exist").status_code == 404


def test_rest_api_and_tokens_served_from_same_app(client: TestClient) -> None:
    assert client.get("/api/frameworks").status_code == 200
    css = client.get("/static/tokens.css")
    assert css.status_code == 200
    assert "--oah-orange" in css.text
