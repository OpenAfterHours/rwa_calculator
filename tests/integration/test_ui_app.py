"""
Integration test: server-rendered UI app (the rwa-ui surface).

Pipeline position:
    TestClient -> FastAPI page routes -> CreditRiskCalc / ui.views -> Jinja + SVG

Key responsibilities tested:
- The landing / calculator / comparison pages render.
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

from rwa_calc.ui.app.calculator_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.app.main import create_app
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the calculator last-run state file into tmp so ~/.rwa_calc is untouched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture
def client() -> TestClient:
    # base_url uses a loopback host so the app's TrustedHostMiddleware (which
    # only answers to localhost / 127.0.0.1) accepts the default test requests.
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    write_mandatory_minimum(tmp_path)
    return str(tmp_path)


def test_static_pages_render(client: TestClient) -> None:
    for path in ("/", "/calculator", "/comparison"):
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


def test_results_page_offers_download_buttons(client: TestClient, data_dir: str) -> None:
    # Arrange — run a calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act
    page = client.get(f"/results/{job_id}").text

    # Assert — the dependency-free formats are offered as real download links to
    # the existing export endpoint (not just inert REST-API text).
    assert f"/api/export/parquet?run_id={job_id}" in page
    assert f"/api/export/csv?run_id={job_id}" in page
    # The Pillar III disclosure export is offered alongside COREP (label always
    # present; the link itself is gated on xlsxwriter being installed).
    assert "Pillar III" in page


def _run_to_completion(client: TestClient, data_dir: str) -> str:
    """Dispatch a calculation and return its run_id once the job finishes."""
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    run_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, run_id)
    return run_id


def test_save_to_folder_writes_both_parquet_and_csv_with_data(
    client: TestClient, data_dir: str, tmp_path: Path
) -> None:
    # Arrange
    run_id = _run_to_completion(client, data_dir)
    out = tmp_path / "exports"
    out.mkdir()

    # Act — request BOTH formats; the full result set has nested columns.
    resp = client.post(
        f"/results/{run_id}/save",
        data={"output_folder": str(out), "output_formats": ["parquet", "csv"]},
    )

    # Assert — both formats land in the run-stamped subfolder, and the CSV is not
    # the old blank file: nested columns are JSON-encoded so it carries data.
    assert resp.status_code == 200
    subdir = out / f"rwa_export_{run_id}"
    assert (subdir / "results.parquet").exists()
    csv_path = subdir / "results.csv"
    assert csv_path.exists()
    assert csv_path.stat().st_size > 0
    assert (subdir / "summary_by_class.csv").exists()


def test_calculate_with_output_folder_writes_files(
    client: TestClient, data_dir: str, tmp_path: Path
) -> None:
    # Arrange
    out = tmp_path / "calc_out"
    out.mkdir()

    # Act — request an output folder up front; the worker writes after the run.
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "output_folder": str(out),
            "output_formats": ["parquet"],
        },
        follow_redirects=False,
    )
    run_id = resp.headers["location"].rsplit("/", 1)[1]
    status = _wait_for_job(client, run_id)

    # Assert — file on disk, stage count unchanged (write is outside STAGE_SEQUENCE),
    # and the results page reports what was written.
    assert status["status"] == "done"
    assert status["total_stages"] == 10
    assert (out / f"rwa_export_{run_id}" / "results.parquet").exists()
    assert "Wrote" in client.get(f"/results/{run_id}").text


def test_calculator_prefills_last_output_folder(
    client: TestClient, data_dir: str, tmp_path: Path
) -> None:
    out = tmp_path / "remember_out"
    out.mkdir()
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "output_folder": str(out),
            "output_formats": ["parquet"],
        },
        follow_redirects=False,
    )
    _wait_for_job(client, resp.headers["location"].rsplit("/", 1)[1])

    # The next calculator render remembers the chosen folder.
    assert str(out) in client.get("/calculator").text


def test_calculate_invalid_output_folder_rerenders_form(client: TestClient, data_dir: str) -> None:
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "permission_mode": "irb",
            "output_folder": "relative/out",
            "output_formats": ["parquet"],
        },
    )

    assert resp.status_code == 400
    assert "absolute" in resp.text.lower()
    assert 'value="irb" selected' in resp.text  # the chosen mode survives the bounce
    assert 'value="relative/out"' in resp.text  # the typed folder is echoed back


def test_save_to_folder_csv_carries_data_despite_nested_columns(
    client: TestClient, data_dir: str, tmp_path: Path
) -> None:
    # The full result set has nested columns CSV cannot natively hold; they are
    # JSON-encoded so the CSV carries data instead of being written blank.
    run_id = _run_to_completion(client, data_dir)
    out = tmp_path / "exports_csv"
    out.mkdir()

    resp = client.post(
        f"/results/{run_id}/save",
        data={"output_folder": str(out), "output_formats": ["csv"]},
    )

    assert resp.status_code == 200
    csv_path = out / f"rwa_export_{run_id}" / "results.csv"
    assert csv_path.exists()
    assert csv_path.stat().st_size > 0
    assert "could not export" not in resp.text


def test_save_to_folder_unknown_run_is_404(client: TestClient, tmp_path: Path) -> None:
    resp = client.post(
        "/results/does-not-exist/save",
        data={"output_folder": str(tmp_path), "output_formats": ["parquet"]},
    )
    assert resp.status_code == 404


def test_save_to_folder_invalid_folder_is_400(client: TestClient, data_dir: str) -> None:
    run_id = _run_to_completion(client, data_dir)
    resp = client.post(
        f"/results/{run_id}/save",
        data={"output_folder": "relative/out", "output_formats": ["parquet"]},
    )
    assert resp.status_code == 400


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


def test_invalid_host_header_is_rejected(client: TestClient) -> None:
    # A rebound DNS name (evil.com -> 127.0.0.1) must not pass the host allowlist.
    resp = client.get("/", headers={"host": "evil.example.com"})
    assert resp.status_code == 400


def test_cross_origin_calculate_is_rejected(client: TestClient, data_dir: str) -> None:
    # A form POST is a CORS "simple request"; a page on another origin must not be
    # able to silently drive the disk-writing calculate route.
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        headers={"Origin": "http://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


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
