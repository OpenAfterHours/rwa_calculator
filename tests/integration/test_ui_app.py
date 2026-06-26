"""
Integration test: server-rendered UI app (the rwa-ui surface).

Pipeline position:
    TestClient -> FastAPI page routes -> CreditRiskCalc / ui.views -> Jinja + SVG

Key responsibilities tested:
- The landing / calculator / comparison / workbench pages render.
- POST /calculate dispatches a background job and redirects to the stage
  stepper; once the job finishes, the results page shows the headline cards,
  an inline SVG chart, and the exposure table.
- The progress stream (SSE) replays stage events and reports completion.
- POST /comparison runs both frameworks and renders the executive summary.
- Invalid data paths re-render the form with an error; unknown run ids 404.
- The REST API and the shared tokens.css are served from the same app.
"""

from __future__ import annotations

import time
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


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    """Poll the job-status endpoint until the run leaves the 'running' state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_calculate_dispatches_job_then_results_become_available(
    client: TestClient, data_dir: str
) -> None:
    # Act — POST dispatches a background job and redirects to the stepper page
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
            "data_format": "parquet",
        },
        follow_redirects=False,
    )

    # Assert — 303 to /calculating/{job_id}, and the stepper page renders
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/calculating/")
    job_id = location.rsplit("/", 1)[1]

    pending = client.get(location)
    assert pending.status_code == 200
    assert "Calculating" in pending.text
    assert 'data-stage="calculators"' in pending.text
    assert "/static/calculating.js" in pending.text

    # The job finishes in the background; results are served under the job_id
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"
    assert status["total_stages"] == 10

    results = client.get(f"/results/{job_id}")
    assert results.status_code == 200
    assert "Total RWA" in results.text
    assert '<svg class="chart"' in results.text
    assert "exposure_reference" in results.text


def test_progress_stream_replays_stages_and_completes(client: TestClient, data_dir: str) -> None:
    # Arrange — dispatch and let the job finish
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act — connecting after completion replays every stage, sends the terminal
    # event, and closes the stream (so the read does not hang)
    stream = client.get(f"/jobs/{job_id}/events")

    # Assert
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "event: stage" in stream.text
    assert "event: done" in stream.text
    assert "calculators" in stream.text


def test_unknown_job_status_is_404(client: TestClient) -> None:
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_unknown_calculating_page_is_404(client: TestClient) -> None:
    assert client.get("/calculating/does-not-exist").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/public-files-sw.js?v=2",
        "/results/public-files-sw.js?v=2",
        "/calculator/public-files-sw.js?v=2",
        "/a/b/public-files-sw.js",
    ],
)
def test_stale_marimo_service_worker_is_tombstoned(client: TestClient, path: str) -> None:
    # The old Marimo UI registered "./public-files-sw.js" relative to the open
    # page, leaving stale registrations at the root AND nested scopes that
    # re-fetch the worker on every navigation. We serve a self-unregistering
    # worker at every such path instead of 404ing (nested paths must not be
    # swallowed by the /results/{run_id}, /calculating/{job_id}, … routes).
    resp = client.get(path)

    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "self.registration.unregister()" in resp.text


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


def test_landing_hosts_bear_constellation(client: TestClient) -> None:
    # Arrange / Act
    page = client.get("/").text
    js = client.get("/static/bear-constellation.js")

    # Assert — the landing page wires up the animated background and the
    # vendored script is served from the same app.
    assert 'class="constellation-bg"' in page
    assert "/static/bear-constellation.js" in page
    assert js.status_code == 200
    assert "URSA POLARIS" in js.text
