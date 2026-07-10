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
from decimal import Decimal
from pathlib import Path

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.analysis.reconciliation import ReconciliationRunner
from rwa_calc.api import run_index
from rwa_calc.api.models import (
    CalculationResponse,
    ReconciliationResponse,
    SummaryStatistics,
)
from rwa_calc.api.rest import register_reconciliation_with_id, register_run_with_id
from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.app.main import create_app
from rwa_calc.ui.app.recon_state import (
    STATE_DIR_ENV_VAR,
    ReconciliationFormState,
    save_last_run,
)
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the last-run state file into tmp so the real ~/.rwa_calc is untouched.

    Without this, the form-prefill feature could read a developer's real saved run
    and flake the default-mapping assertion below.
    """
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_run_index() -> None:
    """Each test starts with an empty calculation run index (module-level state)."""
    run_index.clear()


@pytest.fixture
def client() -> TestClient:
    # Loopback base_url so the app's TrustedHostMiddleware accepts test requests.
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def recon_dir(tmp_path: Path) -> str:
    """Mandatory-minimum dataset plus a legacy_output.csv derived from our results.

    Lives in a subdir so the state home (tmp_path/"state", which holds the
    persistent run caches) never sits inside the data path signature.
    """
    root = tmp_path / "data"
    root.mkdir()
    write_mandatory_minimum(root)
    ours = (
        CreditRiskCalc(
            data_path=str(root),
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
    legacy.write_csv(root / "legacy_output.csv")
    return str(root)


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
    # Approach unmapped by default -> the allocation stays combined, and the page
    # tells the analyst how to split it.
    assert "by risk class &amp; method" not in report.text
    assert "[components.approach]" in report.text


def test_reconciliation_splits_asset_class_allocation_by_method(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange: a legacy extract that reports each asset class PER METHOD (as COREP
    # does), so mapping [components.approach] gives the legacy side a method to split
    # on and the allocation renders one chart section + a table row set per method.
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
        .select(
            "exposure_reference", "ead_final", "rwa_final", "exposure_class", "approach_applied"
        )
        .collect()
    )
    ours.rename(
        {
            "ead_final": "EAD",
            "rwa_final": "RWA",
            "exposure_class": "Asset_Class",
            "approach_applied": "Method",
        }
    ).write_csv(tmp_path / "legacy_output.csv")

    mapping_toml = DEFAULT_MAPPING_TOML + '\n[components.approach]\nlegacy_column = "Method"\n'

    # Act
    job_id = _dispatch_and_wait(client, _form_data(str(tmp_path), mapping_toml))
    report = client.get(f"/reconciliation/{job_id}")

    # Assert: the per-method split renders (chart sections + the class x method table),
    # and no REC007 "unresolved method" warning fires -- our own labels round-trip.
    assert report.status_code == 200
    assert "by risk class &amp; method" in report.text
    assert 'class="method-subtitle"' in report.text
    assert "STD" in report.text
    # No REC007: our own approach labels round-trip through method_label_expr. (Match on
    # the message, not the code -- the code is named in the mapping TOML textarea.)
    assert "do not resolve to a methodology" not in report.text


def test_reconciliation_renders_class_method_segment(client: TestClient, recon_dir: str) -> None:
    # Arrange / Act
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    report = client.get(f"/reconciliation/{job_id}")

    # Assert: the Tier-2 class×method segment renders, and the explorer it drills
    # into offers a Method filter (so a class×method cell can pre-narrow on both).
    assert report.status_code == 200
    assert "By exposure class &amp; method" in report.text
    explorer = client.get(f"/reconciliation/{job_id}/rows")
    assert explorer.status_code == 200
    assert 'name="method"' in explorer.text


def test_reconciliation_overview_offers_explorer_and_worklist(
    client: TestClient, recon_dir: str
) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    report = client.get(f"/reconciliation/{job_id}")
    assert report.status_code == 200
    assert "Worklist" in report.text
    assert "Explore open differences" in report.text
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


# =============================================================================
# Materiality toggle — hide zero-gross-exposure rows
# =============================================================================


def _zero_gross_response() -> ReconciliationResponse:
    """A registered reconciliation with one zero-EAD our-only row (Z1, immaterial)
    and one real our-only omission (Z2), plus a matched break (L1). Registering the
    response directly drives the real routes without the heavy background job."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "Z1", "Z2"],
            "exposure_class": ["corporate", "corporate", "retail"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [100.0, 0.0, 300.0],
            "rwa_final": [50.0, 0.0, 150.0],
        }
    )
    legacy = pl.LazyFrame(
        {"exposure_reference": ["L1"], "legacy_ead": [100.0], "legacy_rwa": [80.0]}
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


def test_overview_toggle_hides_zero_gross_rows(client: TestClient) -> None:
    recon_id = "zero-gross-overview"
    register_reconciliation_with_id(recon_id, _zero_gross_response())

    # Default view offers the toggle and does not suppress anything.
    default = client.get(f"/reconciliation/{recon_id}")
    assert default.status_code == 200
    assert "Hide zero-gross-exposure rows" in default.text

    # Toggled view suppresses the single zero-EAD our-only row and says so; the
    # segment drills carry the toggle into the explorer.
    hidden = client.get(f"/reconciliation/{recon_id}", params={"hide_immaterial": "1"})
    assert hidden.status_code == 200
    assert "1 zero-gross-exposure row(s) hidden" in hidden.text
    assert "Show all rows" in hidden.text
    assert "hide_immaterial=1" in hidden.text


def test_explorer_toggle_checkbox_and_query_preserved(client: TestClient) -> None:
    recon_id = "zero-gross-explorer"
    register_reconciliation_with_id(recon_id, _zero_gross_response())
    checkbox = 'name="hide_immaterial" type="checkbox" value="1"'

    default = client.get(f"/reconciliation/{recon_id}/rows", params={"status": "all"})
    assert default.status_code == 200
    assert checkbox in default.text
    assert f"{checkbox} checked" not in default.text

    hidden = client.get(
        f"/reconciliation/{recon_id}/rows", params={"status": "all", "hide_immaterial": "1"}
    )
    assert hidden.status_code == 200
    # The checkbox reflects the active toggle, and the sort/paging links preserve it.
    assert f"{checkbox} checked" in hidden.text
    assert "hide_immaterial=1" in hidden.text


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


# =============================================================================
# Sign-off — accept / reject a difference, persist, filter it out
# =============================================================================


def _open_break_key(client: TestClient, job_id: str) -> str:
    """The _recon_key of an open break, read from the default (Open) explorer."""
    explorer = client.get(f"/reconciliation/{job_id}/rows")
    match = re.search(r"/reconciliation/[^/]+/loan\?key=([^\"&]+)", explorer.text)
    assert match, "expected an open break with a loan link in the default explorer"
    return urllib.parse.unquote(match.group(1))


def _signoff(
    client: TestClient, job_id: str, key: str, status: str, reason: str = ""
) -> httpx.Response:
    return client.post(
        f"/reconciliation/{job_id}/signoff",
        data={
            "key": key,
            "status": status,
            "reason": reason,
            "return_to": f"/reconciliation/{job_id}/rows",
        },
        follow_redirects=False,
    )


def test_signoff_accept_clears_open_and_shows_under_accepted(
    client: TestClient, recon_dir: str
) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)

    posted = _signoff(client, job_id, key, "accepted", "FX timing immaterial")
    assert posted.status_code == 303

    # The accepted break drops out of the default (Open) worklist...
    open_view = client.get(f"/reconciliation/{job_id}/rows")
    assert "No rows match" in open_view.text

    # ...and returns under the Accepted filter, with its reason.
    accepted_view = client.get(f"/reconciliation/{job_id}/rows", params={"status": "accepted"})
    assert "FX timing immaterial" in accepted_view.text
    assert "badge-accepted" in accepted_view.text


def test_signoff_reject_requires_a_reason(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)

    # Reject with only whitespace -> re-rendered loan page with a 400 + error callout.
    resp = client.post(
        f"/reconciliation/{job_id}/signoff",
        data={"key": key, "status": "rejected", "reason": "   ", "return_to": ""},
    )
    assert resp.status_code == 400
    assert "reason is required" in resp.text.lower()


def test_signoff_reject_persists_with_reason(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)

    posted = _signoff(client, job_id, key, "rejected", "legacy applied wrong LGD floor")
    assert posted.status_code == 303

    rejected_view = client.get(f"/reconciliation/{job_id}/rows", params={"status": "rejected"})
    assert "legacy applied wrong LGD floor" in rejected_view.text
    assert "badge-rejected" in rejected_view.text


def test_signoff_accept_allows_empty_reason(client: TestClient, recon_dir: str) -> None:
    # Mirrors the explorer's inline quick-accept (no reason typed).
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)

    posted = _signoff(client, job_id, key, "accepted", "")
    assert posted.status_code == 303
    assert "No rows match" in client.get(f"/reconciliation/{job_id}/rows").text


def test_signoff_reopen_returns_row_to_open(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)
    _signoff(client, job_id, key, "accepted", "on reflection, recheck")
    assert "No rows match" in client.get(f"/reconciliation/{job_id}/rows").text

    # Reopen -> the break is back on the Open worklist.
    reopened = _signoff(client, job_id, key, "open")
    assert reopened.status_code == 303
    assert (
        f"/reconciliation/{job_id}/loan?key=" in client.get(f"/reconciliation/{job_id}/rows").text
    )


def test_signoff_rejects_cross_site_request(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)
    resp = client.post(
        f"/reconciliation/{job_id}/signoff",
        data={"key": key, "status": "accepted", "reason": "x", "return_to": ""},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert resp.status_code == 400


def test_signoff_unknown_recon_is_404(client: TestClient) -> None:
    resp = client.post(
        "/reconciliation/does-not-exist/signoff",
        data={"key": "X", "status": "accepted", "reason": "", "return_to": ""},
    )
    assert resp.status_code == 404


def test_inline_accept_via_fetch_returns_json_progress(client: TestClient, recon_dir: str) -> None:
    # The explorer's inline Accept posts with X-Requested-With: fetch and expects a
    # small JSON payload (fresh burndown) rather than a 303 — so the row can be
    # dropped client-side without a full reload.
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)

    resp = client.post(
        f"/reconciliation/{job_id}/signoff",
        data={"key": key, "status": "accepted", "reason": "", "return_to": ""},
        headers={"x-requested-with": "fetch"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["progress"]["open"] == 0  # the only break is now reviewed
    assert body["progress"]["accepted"] == 1

    # The decision still persisted: the break is off the Open worklist.
    assert "No rows match" in client.get(f"/reconciliation/{job_id}/rows").text


def test_explorer_loads_inline_signoff_script(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    explorer = client.get(f"/reconciliation/{job_id}/rows")
    assert "/static/recon-signoff.js" in explorer.text
    assert 'data-signoff-status="open"' in explorer.text
    # The script is actually served (vendored under static/, shipped as package data).
    assert client.get("/static/recon-signoff.js").status_code == 200


def test_signoff_persists_across_rerun_of_same_dataset(client: TestClient, recon_dir: str) -> None:
    # Arrange — accept the break on the first run.
    job_id_1 = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id_1)
    _signoff(client, job_id_1, key, "accepted", "known data-vendor diff")

    # Act — re-run the *same* dataset + mapping (a fresh recon_id, same workspace).
    job_id_2 = _dispatch_and_wait(client, _form_data(recon_dir))
    assert job_id_2 != job_id_1

    # Assert — the decision (keyed by the stable _recon_key) carries over: the break
    # is already off the new run's Open worklist and visible under Accepted.
    assert "No rows match" in client.get(f"/reconciliation/{job_id_2}/rows").text
    accepted = client.get(f"/reconciliation/{job_id_2}/rows", params={"status": "accepted"})
    assert "known data-vendor diff" in accepted.text


def _move_break(data_path: str) -> None:
    """Make the (already-breaking) first legacy row break *more*, so its difference
    moves materially on the next run — without changing the keys or file path (the
    sign-off workspace is unchanged, so prior decisions still load)."""
    path = Path(data_path) / "legacy_output.csv"
    df = pl.read_csv(path)
    moved = (
        df.with_row_index("_i")
        .with_columns(
            pl.when(pl.col("_i") == 0)
            .then(pl.col("RWA") * 2.0)
            .otherwise(pl.col("RWA"))
            .alias("RWA")
        )
        .drop("_i")
    )
    moved.write_csv(path)


def test_signoff_goes_stale_when_difference_moves_on_rerun(
    client: TestClient, recon_dir: str
) -> None:
    # Arrange — accept the break, confirm it left the Open worklist.
    job_id_1 = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id_1)
    _signoff(client, job_id_1, key, "accepted", "looked immaterial")
    assert "No rows match" in client.get(f"/reconciliation/{job_id_1}/rows").text

    # Act — the SAME break grows on a re-run (one issue "fixed", this one worsened).
    _move_break(recon_dir)
    job_id_2 = _dispatch_and_wait(client, _form_data(recon_dir))

    # Assert — the stale decision is back on the Open worklist, flagged "changed",
    # rather than silently waved through under the old approval.
    open_view = client.get(f"/reconciliation/{job_id_2}/rows")
    assert f"/reconciliation/{job_id_2}/loan?key=" in open_view.text
    assert "badge-stale" in open_view.text

    # The loan page warns it changed since sign-off.
    loan = client.get(f"/reconciliation/{job_id_2}/loan", params={"key": key})
    assert "changed since" in loan.text.lower()


def test_clear_all_returns_every_break_to_open(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)
    _signoff(client, job_id, key, "accepted", "ok")
    assert "No rows match" in client.get(f"/reconciliation/{job_id}/rows").text
    assert "clear-all-signoff" in client.get(f"/reconciliation/{job_id}/rows").text

    # Clear all -> 303 back, and the break is on the Open worklist again.
    cleared = client.post(
        f"/reconciliation/{job_id}/signoff/clear-all",
        data={"return_to": f"/reconciliation/{job_id}/rows"},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    back = client.get(f"/reconciliation/{job_id}/rows")
    assert f"/reconciliation/{job_id}/loan?key=" in back.text
    assert "clear-all-signoff" not in back.text  # no decisions left -> button gone


def test_clear_all_rejects_cross_site_request(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    resp = client.post(
        f"/reconciliation/{job_id}/signoff/clear-all",
        data={"return_to": ""},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert resp.status_code == 400


def test_re_accepting_a_stale_row_clears_the_changed_flag(
    client: TestClient, recon_dir: str
) -> None:
    job_id_1 = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id_1)
    _signoff(client, job_id_1, key, "accepted", "looked immaterial")

    _move_break(recon_dir)
    job_id_2 = _dispatch_and_wait(client, _form_data(recon_dir))
    assert "badge-stale" in client.get(f"/reconciliation/{job_id_2}/rows").text

    # Re-review and re-accept on the new run -> the fingerprint is re-stamped to the
    # current difference, so it is no longer stale and leaves the Open worklist.
    _signoff(client, job_id_2, key, "accepted", "re-reviewed, still acceptable")
    after = client.get(f"/reconciliation/{job_id_2}/rows")
    assert "No rows match" in after.text
    assert "badge-stale" not in after.text


def test_overview_shows_changed_state_after_difference_moves(
    client: TestClient, recon_dir: str
) -> None:
    job_id_1 = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id_1)
    _signoff(client, job_id_1, key, "accepted", "ok")

    _move_break(recon_dir)
    job_id_2 = _dispatch_and_wait(client, _form_data(recon_dir))

    overview = client.get(f"/reconciliation/{job_id_2}")
    assert "changed since sign-off" in overview.text
    # The stale break is back on the overview worklist (a per-loan drill link present).
    assert f"/reconciliation/{job_id_2}/loan?key=" in overview.text


def test_clear_all_from_the_overview(client: TestClient, recon_dir: str) -> None:
    job_id = _dispatch_and_wait(client, _form_data(recon_dir))
    key = _open_break_key(client, job_id)
    _signoff(client, job_id, key, "accepted", "ok")
    assert "clear-all-signoff" in client.get(f"/reconciliation/{job_id}").text

    cleared = client.post(
        f"/reconciliation/{job_id}/signoff/clear-all",
        data={"return_to": f"/reconciliation/{job_id}"},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    assert "clear-all-signoff" not in client.get(f"/reconciliation/{job_id}").text


# =============================================================================
# Calculation reuse — skip the pipeline when a matching run already exists
# =============================================================================


def _seed_reusable_calculation(
    data_dir: Path, results_dir: Path, run_id: str = "reuse-run"
) -> CalculationResponse:
    """Index a manufactured successful run for *data_dir*'s current state.

    The results parquet lives OUTSIDE the data dir (a results file must never be
    part of the input-data signature). Registered both in the run registry and
    the run index, as the calculation worker does.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "last_results.parquet"
    pl.DataFrame(
        {
            "exposure_reference": ["L1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["SA"],
            "ead_final": [100.0],
            "rwa_final": [50.0],
        }
    ).write_parquet(results_path)
    response = CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=results_path,
    )
    fingerprint = run_index.compute_fingerprint(
        data_path=data_dir,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        permission_mode="standardised",
        data_format="parquet",
    )
    run_index.register_calculation(fingerprint, run_id, response)
    register_run_with_id(run_id, response)
    return response


def _seed_recon_form_state(data_dir: Path) -> None:
    """Persist a last-run form state so GET /reconciliation pre-fills *data_dir*."""
    save_last_run(
        ReconciliationFormState(
            data_path=str(data_dir),
            reporting_date="2025-01-01",
            framework="CRR",
            permission_mode="standardised",
            data_format="parquet",
            mapping_toml=DEFAULT_MAPPING_TOML,
        )
    )


@pytest.fixture
def reuse_dir(tmp_path: Path) -> Path:
    """A minimal data dir (one parquet input) plus a matching legacy_output.csv."""
    data_dir = tmp_path / "reuse_data"
    data_dir.mkdir()
    pl.DataFrame({"id": ["1"]}).write_parquet(data_dir / "exposures.parquet")
    pl.DataFrame(
        {"exposure_reference": ["L1"], "EAD": [100.0], "RWA": [75.0]}  # RWA break
    ).write_csv(data_dir / "legacy_output.csv")
    return data_dir


def test_form_offers_reuse_when_matching_run_exists(
    client: TestClient, reuse_dir: Path, tmp_path: Path
) -> None:
    # Arrange — an indexed run matching the form's pre-filled values.
    _seed_reusable_calculation(reuse_dir, tmp_path / "results")
    _seed_recon_form_state(reuse_dir)

    # Act
    form = client.get("/reconciliation")

    # Assert — the reuse option renders, pre-ticked.
    assert form.status_code == 200
    assert 'name="reuse_calculation"' in form.text
    assert "Use results from the calculation completed at" in form.text
    assert "checked" in form.text


def test_form_without_matching_run_has_no_reuse_option(client: TestClient) -> None:
    form = client.get("/reconciliation")
    assert form.status_code == 200
    assert 'name="reuse_calculation"' not in form.text


def test_form_notes_data_changed_when_inputs_modified(
    client: TestClient, reuse_dir: Path, tmp_path: Path
) -> None:
    # Arrange — index a run, then change an input file so the signature misses.
    _seed_reusable_calculation(reuse_dir, tmp_path / "results")
    _seed_recon_form_state(reuse_dir)
    pl.DataFrame({"id": ["1", "2"]}).write_parquet(reuse_dir / "exposures.parquet")

    # Act
    form = client.get("/reconciliation")

    # Assert — a passive will-recompute note, no reuse checkbox.
    assert form.status_code == 200
    assert 'name="reuse_calculation"' not in form.text
    assert "Input data has changed" in form.text


def test_reuse_submit_skips_pipeline_and_renders_report(
    client: TestClient, reuse_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a reusable run; any pipeline re-run would blow up the job.
    _seed_reusable_calculation(reuse_dir, tmp_path / "results")
    monkeypatch.setattr(
        CreditRiskCalc,
        "calculate",
        lambda self: (_ for _ in ()).throw(AssertionError("pipeline re-run")),
    )
    data = _form_data(str(reuse_dir))
    data["reuse_calculation"] = "1"

    # Act
    job_id = _dispatch_and_wait(client, data)

    # Assert — the job completed off the cached run and the report renders,
    # with every engine stage ticked instantly for the stepper replay.
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "done"
    assert status["success"] is True
    assert len(status["completed"]) == status["total_stages"] + 1  # + recon tail
    report = client.get(f"/reconciliation/{job_id}")
    assert report.status_code == 200
    assert "Headline" in report.text


def test_reuse_submit_falls_back_to_full_run_when_stale(
    client: TestClient, recon_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — index a run for the real dataset, then change an input file.
    _seed_reusable_calculation(Path(recon_dir), tmp_path / "results")
    pl.DataFrame({"extra": ["x"]}).write_parquet(Path(recon_dir) / "extra_input.parquet")
    calls: list[int] = []
    original = CreditRiskCalc.calculate

    def _spy(self: CreditRiskCalc) -> CalculationResponse:
        calls.append(1)
        return original(self)

    monkeypatch.setattr(CreditRiskCalc, "calculate", _spy)
    data = _form_data(recon_dir)
    data["reuse_calculation"] = "1"

    # Act — the reuse request silently degrades to a full run.
    job_id = _dispatch_and_wait(client, data)

    # Assert — the pipeline really ran once and the report still renders.
    assert calls == [1]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "done"
    assert client.get(f"/reconciliation/{job_id}").status_code == 200


def test_calculate_then_reconcile_reuses_end_to_end(
    client: TestClient, recon_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a real calculation via the calculator form seeds the index.
    calc_form = {
        "data_path": recon_dir,
        "reporting_date": "2025-01-01",
        "framework": "CRR",
        "permission_mode": "standardised",
        "data_format": "parquet",
        "output_folder": "",
    }
    posted = client.post("/calculate", data=calc_form, follow_redirects=False)
    assert posted.status_code == 303
    calc_job = posted.headers["location"].rsplit("/", 1)[1]
    assert _wait_for_job(client, calc_job)["status"] == "done"

    # The reconciliation form (pre-filled to the same values) offers the reuse.
    _seed_recon_form_state(Path(recon_dir))
    form = client.get("/reconciliation")
    assert 'name="reuse_calculation"' in form.text

    # Act — reconcile with reuse; any pipeline re-run would blow up the job.
    monkeypatch.setattr(
        CreditRiskCalc,
        "calculate",
        lambda self: (_ for _ in ()).throw(AssertionError("pipeline re-run")),
    )
    data = _form_data(recon_dir)
    data["reuse_calculation"] = "1"
    job_id = _dispatch_and_wait(client, data)

    # Assert — reconciliation completed off the cached run.
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "done"
    assert status["success"] is True
    assert "Headline" in client.get(f"/reconciliation/{job_id}").text


def test_full_reconciliation_seeds_reuse_for_next_run(
    client: TestClient, recon_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a recon-first session: the FULL run's embedded calculation must
    # seed the index (and the run registry), so the next reconciliation is free.
    _dispatch_and_wait(client, _form_data(recon_dir))

    # The form (pre-filled from the saved run) now offers the reuse.
    form = client.get("/reconciliation")
    assert 'name="reuse_calculation"' in form.text

    # Act — the second reconciliation reuses; a pipeline re-run would blow up.
    monkeypatch.setattr(
        CreditRiskCalc,
        "calculate",
        lambda self: (_ for _ in ()).throw(AssertionError("pipeline re-run")),
    )
    data = _form_data(recon_dir)
    data["reuse_calculation"] = "1"
    job_id = _dispatch_and_wait(client, data)

    # Assert
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "done"
    assert status["success"] is True


def test_reuse_survives_restart(
    client: TestClient, recon_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a calculation through the calculator route persists its cache
    # and index entry under the state dir.
    posted = client.post(
        "/calculate",
        data={
            "data_path": recon_dir,
            "reporting_date": "2025-01-01",
            "framework": "CRR",
            "permission_mode": "standardised",
            "data_format": "parquet",
            "output_folder": "",
        },
        follow_redirects=False,
    )
    assert posted.status_code == 303
    assert _wait_for_job(client, posted.headers["location"].rsplit("/", 1)[1])["status"] == "done"
    _seed_recon_form_state(Path(recon_dir))

    # Act — simulate a restart: in-memory index gone, a fresh app boots and
    # reloads the persisted index from the state dir.
    run_index.clear()
    client2 = TestClient(create_app(), base_url="http://localhost")
    form = client2.get("/reconciliation")

    # Assert — the reuse offer survived the restart, and reconciling off it
    # completes without a pipeline re-run.
    assert 'name="reuse_calculation"' in form.text
    monkeypatch.setattr(
        CreditRiskCalc,
        "calculate",
        lambda self: (_ for _ in ()).throw(AssertionError("pipeline re-run")),
    )
    data = _form_data(recon_dir)
    data["reuse_calculation"] = "1"
    job_id = _dispatch_and_wait(client2, data)
    assert client2.get(f"/jobs/{job_id}").json()["success"] is True
