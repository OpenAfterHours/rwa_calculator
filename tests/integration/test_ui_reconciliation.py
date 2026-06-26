"""
Integration test: the server-rendered reconciliation page.

Pipeline position:
    TestClient -> FastAPI /reconciliation routes -> background job
        -> CreditRiskCalc.reconcile() -> ui.views.reconciliation -> Jinja + SVG

Key responsibilities tested:
- GET /reconciliation renders the form pre-filled with the default TOML mapping.
- POST /reconciliation dispatches a background job and redirects to the live
  stage stepper (/reconciling/{job_id}); once the job finishes, the report is
  served under the job_id (/reconciliation/{job_id}) with the four tiers + an
  inline SVG chart.
- The progress stream (SSE) replays stage events, including the reconcile tail,
  and reports completion.
- A bad mapping re-renders the form with an error and a 400 (parsed synchronously
  before any work is dispatched).
- GET /reconciliation/{id}?bucket=… reads the cached result; unknown ids 404.

The legacy output is generated from our own SA results (renamed + one RWA nudged
to force a break) so the reconciliation has comparable components and a worklist.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.app.main import create_app
from rwa_calc.ui.app.recon_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the last-run state file into tmp so the real ~/.rwa_calc is untouched.

    Without this, the form-prefill feature could read a developer's real saved run
    and flake the default-mapping assertion below.
    """
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def recon_dir(tmp_path: Path) -> str:
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
            .then(pl.col("RWA") * 1.5)  # nudge the first row's RWA -> a break
            .otherwise(pl.col("RWA"))
            .alias("RWA")
        )
        .drop("_i")
    )
    legacy.write_csv(tmp_path / "legacy_output.csv")
    return str(tmp_path)


def _form_data(data_path: str, mapping_toml: str = DEFAULT_MAPPING_TOML) -> dict:
    return {
        "data_path": data_path,
        "reporting_date": "2025-01-01",
        "framework": "CRR",
        "permission_mode": "standardised",
        "data_format": "parquet",
        "mapping_toml": mapping_toml,
    }


def _non_default_form(data_path: str) -> dict:
    return {
        "data_path": data_path,
        "reporting_date": "2026-06-30",
        "framework": "BASEL_3_1",
        "permission_mode": "irb",
        "data_format": "parquet",
        "mapping_toml": DEFAULT_MAPPING_TOML + "\n# MY-CUSTOM-MARKER\n",
    }


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    """Poll the job-status endpoint until the run leaves the 'running' state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"reconciliation job {job_id} did not finish within {timeout}s")


def _dispatch_and_wait(client: TestClient, data: dict) -> str:
    """POST the form, assert the 303 to the stepper, and wait for the job to finish."""
    posted = client.post("/reconciliation", data=data, follow_redirects=False)
    assert posted.status_code == 303
    location = posted.headers["location"]
    assert location.startswith("/reconciling/")
    job_id = location.rsplit("/", 1)[1]
    _wait_for_job(client, job_id)
    return job_id


def test_reconciliation_form_renders_with_default_mapping(client: TestClient) -> None:
    resp = client.get("/reconciliation")
    assert resp.status_code == 200
    assert "<textarea" in resp.text
    assert "legacy_file" in resp.text  # the default TOML is pre-filled


def test_reconciliation_dispatches_job_then_report(client: TestClient, recon_dir: str) -> None:
    # Act — POST dispatches a background job and redirects to the stepper page
    posted = client.post("/reconciliation", data=_form_data(recon_dir), follow_redirects=False)

    # Assert — 303 to /reconciling/{job_id}, and the stepper page renders
    assert posted.status_code == 303
    location = posted.headers["location"]
    assert location.startswith("/reconciling/")
    job_id = location.rsplit("/", 1)[1]

    pending = client.get(location)
    assert pending.status_code == 200
    assert "Reconciling" in pending.text
    assert 'data-stage="recon_reconcile"' in pending.text
    assert 'data-result-base="/reconciliation/"' in pending.text
    assert "/static/calculating.js" in pending.text

    # The job finishes in the background; the report is served under the job_id
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"

    report = client.get(f"/reconciliation/{job_id}")
    assert report.status_code == 200
    assert "Headline" in report.text
    assert "Worklist" in report.text
    assert f"/reconciliation/{job_id}/rows" in report.text  # drills into the explorer
    assert '<svg class="chart"' in report.text


def test_reconciliation_progress_stream_replays_recon_tail(
    client: TestClient, recon_dir: str
) -> None:
    # Arrange — dispatch and let the job finish
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))

    # Act — a fresh stream replays every completed stage, then the terminal
    stream = client.get(f"/jobs/{job_id}/events")

    # Assert — the engine stages and the reconcile tail are reported, then done
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "event: stage" in stream.text
    assert "event: done" in stream.text
    assert "recon_reconcile" in stream.text


def test_reconciliation_renders_asset_class_allocation(client: TestClient, tmp_path: Path) -> None:
    # Arrange: a legacy file that carries an asset-class column per line (the
    # default mapping maps exposure_class -> Asset_Class), so the allocation tier
    # is populated and rendered.
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
        .select("exposure_reference", "ead_final", "rwa_final", "exposure_class")
        .collect()
    )
    ours.rename(
        {"ead_final": "EAD", "rwa_final": "RWA", "exposure_class": "Asset_Class"}
    ).write_csv(tmp_path / "legacy_output.csv")

    # Act
    job_id = _dispatch_and_wait(client, _form_data(str(tmp_path)))
    report = client.get(f"/reconciliation/{job_id}")

    # Assert: the asset-class allocation view is present.
    assert report.status_code == 200
    assert "Asset-class allocation" in report.text


def test_reconciliation_overview_offers_explorer_and_worklist(
    client: TestClient, recon_dir: str
) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    report = client.get(f"/reconciliation/{job_id}")
    assert report.status_code == 200
    assert "Worklist" in report.text
    assert "Explore all" in report.text
    assert f"/reconciliation/{job_id}/rows" in report.text


def test_reconciliation_explorer_filters_paginates_and_links_loans(
    client: TestClient, recon_dir: str
) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))

    # One row per page -> the pager appears.
    paged = client.get(f"/reconciliation/{job_id}/rows", params={"page_size": 1})
    assert paged.status_code == 200
    assert "Per-key explorer" in paged.text
    assert "Page 1 of" in paged.text

    # The bucket filter is served by the explorer (reads the cached frame).
    broken = client.get(f"/reconciliation/{job_id}/rows", params={"bucket": "break"})
    assert broken.status_code == 200
    assert f"/reconciliation/{job_id}/loan?key=" in broken.text


def test_reconciliation_explorer_unknown_sort_is_400(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    resp = client.get(f"/reconciliation/{job_id}/rows", params={"sort": "definitely_not_a_column"})
    assert resp.status_code == 400


def test_reconciliation_loan_detail_renders_for_a_key(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    explorer = client.get(f"/reconciliation/{job_id}/rows")
    match = re.search(r"/reconciliation/[^/]+/loan\?key=([^\"&]+)", explorer.text)
    assert match, "expected at least one per-loan link in the explorer"

    key = urllib.parse.unquote(match.group(1))
    loan = client.get(f"/reconciliation/{job_id}/loan", params={"key": key})
    assert loan.status_code == 200
    assert "Loan forensic" in loan.text
    assert "By component" in loan.text


def test_reconciliation_loan_unknown_key_is_404(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    resp = client.get(f"/reconciliation/{job_id}/loan", params={"key": "NOT-A-REAL-KEY"})
    assert resp.status_code == 404


def test_reconciliation_loan_missing_key_is_styled_404(client: TestClient, recon_dir: str) -> None:
    # Omitting ?key= must reach the styled 404, not FastAPI's raw 422.
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    resp = client.get(f"/reconciliation/{job_id}/loan")
    assert resp.status_code == 404


def test_reconciliation_bad_mapping_rerenders_with_error(
    client: TestClient, recon_dir: str
) -> None:
    # The mapping is parsed synchronously, before any job is dispatched.
    resp = client.post("/reconciliation", data=_form_data(recon_dir, mapping_toml="not valid ["))
    assert resp.status_code == 400
    assert "Reconciliation failed" in resp.text


def test_reconciliation_unknown_id_is_404(client: TestClient) -> None:
    assert client.get("/reconciliation/does-not-exist").status_code == 404


def test_unknown_reconciling_page_is_404(client: TestClient) -> None:
    assert client.get("/reconciling/does-not-exist").status_code == 404


def test_reconciliation_prefills_from_last_run(client: TestClient, recon_dir: str) -> None:
    # Arrange — a non-default combo so the prefilled values are unambiguous.
    marked_toml = DEFAULT_MAPPING_TOML + "\n# MY-CUSTOM-MARKER\n"
    submitted = {
        "data_path": recon_dir,
        "reporting_date": "2026-06-30",
        "framework": "BASEL_3_1",
        "permission_mode": "irb",
        "data_format": "parquet",
        "mapping_toml": marked_toml,
    }

    # Act — run it (the worker saves on success), then re-open the blank form.
    _dispatch_and_wait(client, submitted)
    form = client.get("/reconciliation")

    # Assert — every field comes back from the saved run.
    assert form.status_code == 200
    assert recon_dir in form.text
    assert "2026-06-30" in form.text
    assert "# MY-CUSTOM-MARKER" in form.text
    assert 'value="BASEL_3_1" selected' in form.text
    assert 'value="irb" selected' in form.text


def test_reset_button_hidden_until_a_run_is_saved(client: TestClient, recon_dir: str) -> None:
    # Arrange — a fresh form has nothing to reset.
    fresh = client.get("/reconciliation")
    assert "/reconciliation/reset" not in fresh.text

    # Act — a completed run saves state.
    _dispatch_and_wait(client, _non_default_form(recon_dir))

    # Assert — the reset control now appears.
    assert "/reconciliation/reset" in client.get("/reconciliation").text


def test_reset_restores_defaults_and_clears_saved_run(client: TestClient, recon_dir: str) -> None:
    # Arrange — save a non-default run, confirm it is pre-filled.
    _dispatch_and_wait(client, _non_default_form(recon_dir))
    assert "# MY-CUSTOM-MARKER" in client.get("/reconciliation").text

    # Act — reset (303 -> /reconciliation).
    reset = client.get("/reconciliation/reset", follow_redirects=False)
    assert reset.status_code == 303
    assert reset.headers["location"] == "/reconciliation"

    # Assert — the form is back to defaults and the saved run is gone.
    form = client.get("/reconciliation")
    assert "# MY-CUSTOM-MARKER" not in form.text
    assert "./legacy_output.csv" in form.text  # the default mapping TOML
    assert "/reconciliation/reset" not in form.text  # nothing left to reset
