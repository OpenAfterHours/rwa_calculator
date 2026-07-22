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

import re
import time
from datetime import date
from decimal import Decimal
from html import unescape
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.api import run_index
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.rest import get_run, register_run_with_id
from rwa_calc.ui.app.calculator_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.app.main import create_app
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum
from tests.fixtures.recon_ledger import with_reporting_ledger


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the calculator last-run state file into tmp so ~/.rwa_calc is untouched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_run_index() -> None:
    """Each test starts with an empty calculation run index (module-level state)."""
    run_index.clear()


@pytest.fixture
def client() -> TestClient:
    # base_url uses a loopback host so the app's TrustedHostMiddleware (which
    # only answers to localhost / 127.0.0.1) accepts the default test requests.
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    # A sibling of the state home (tmp_path/"state"): the persistent run caches
    # must never land inside the data path, or they would change its signature.
    root = tmp_path / "data"
    root.mkdir()
    write_mandatory_minimum(root)
    return str(root)


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
    # No output folder was given, so there is no trailing "Create exports" step.
    assert 'data-stage="write_exports"' not in pending.text

    # The job finishes in the background; results are served under the job_id
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"
    assert status["total_stages"] == 11

    results = client.get(f"/results/{job_id}")
    assert results.status_code == 200
    assert "Total RWA" in results.text
    assert '<svg class="chart"' in results.text
    assert "exposure_reference" in results.text


def test_results_page_splits_rwa_by_class_by_method(client: TestClient, data_dir: str) -> None:
    # Arrange — run a standardised calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act
    page = client.get(f"/results/{job_id}").text

    # Assert — BOTH the RWA-by-class and EAD-by-class panels are split into
    # methodology subsections; the mandatory-minimum dataset is standardised, so
    # each renders a STD subsection (>=2 method-subtitles: one per panel).
    assert "RWA by exposure class" in page
    assert "EAD by exposure class" in page
    assert page.count('class="method-subtitle"') >= 2
    assert ">STD<" in page


def test_results_page_links_the_template_viewer(client: TestClient, data_dir: str) -> None:
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

    # Assert — the viewer is reachable from the run, not just by URL surgery.
    assert f"/results/{job_id}/templates" in page


def test_template_viewer_renders_cells_keyed_for_drilldown(
    client: TestClient, data_dir: str
) -> None:
    # Arrange — run a calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act — C 07.00, corporate sheet (the SA corporate loan's sheet)
    page = client.get(
        f"/results/{job_id}/templates",
        params={"template": "c07_00", "sheet": "corporate"},
    )

    # Assert — every value cell carries its full cell key (template, sheet, row,
    # col). This is the address the lineage drill-down attaches to; it must not
    # regress into an anonymous grid.
    assert page.status_code == 200
    html = page.text
    assert "C 07.00" in html
    cell = re.search(
        r'data-template="c07_00"\s+data-sheet="corporate"\s+'
        r'data-row="0010"\s+data-col="0220">(.*?)</td>',
        html,
        re.S,
    )
    assert cell is not None, "C 07.00 row 0010 / col 0220 is not addressable by its cell key"
    assert re.sub(r"<[^>]+>", "", cell.group(1)).strip(), "the keyed RWEA cell rendered empty"


def test_template_viewer_uses_the_full_width_with_frozen_row_labels(
    client: TestClient, data_dir: str
) -> None:
    # Arrange — run a calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act
    html = client.get(
        f"/results/{job_id}/templates",
        params={"template": "c07_00", "sheet": "corporate"},
    ).text

    # Assert — a 28-column return is unreadable in a 1100px reading measure, and
    # unusable if scrolling right loses the row labels. Both must hold together.
    assert 'class="container container--wide"' in html
    assert 'class="grid-wrap"' in html
    assert html.count("rowhead-ref") > 30  # every row's label cell is frozen
    assert html.count("rowhead-name") > 30
    assert "28 columns" in html  # the width is stated, so it is not a surprise


def test_template_viewer_distinguishes_null_from_reported_zero(
    client: TestClient, data_dir: str
) -> None:
    # Arrange — run a calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act
    html = client.get(
        f"/results/{job_id}/templates",
        params={"template": "c07_00", "sheet": "corporate"},
    ).text

    # Assert — an empty/not-reported cell is marked null and rendered with the
    # null glyph; a reported 0.0 is not. Conflating the two misstates the return.
    assert "is-null" in html
    assert "—" in html
    assert ">0<" in html


def test_clicking_a_template_cell_opens_its_lineage(client: TestClient, data_dir: str) -> None:
    # Arrange — run a calculation to completion
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act — follow the C 07.00 RWEA cell's own link, exactly as a user would
    grid = client.get(
        f"/results/{job_id}/templates",
        params={"template": "c07_00", "sheet": "corporate"},
    ).text
    assert "Click any cell" in grid
    match = re.search(r'data-row="0010"\s+data-col="0220">.*?href="([^"]+)"', grid, re.S)
    assert match is not None, "the RWEA cell is not a drill-down link"
    page = client.get(unescape(match.group(1)))

    # Assert — the journey lands on the cell's lineage: what it means, and the
    # exposure legs that produced it.
    assert page.status_code == 200
    html = page.text
    assert "Cell lineage" in html
    assert "Sum of rwa_final" in html  # the metric
    assert "aggregator_exit" in html  # the basis
    assert "Contributing exposure legs" in html
    assert "reporting_leg_role" in html  # a contributor is a LEG
    assert "reconcile" in html  # legs tie back to the reported figure


def test_uninstrumented_templates_offer_no_dead_drilldown_links(
    client: TestClient, data_dir: str
) -> None:
    # Arrange
    resp = client.post(
        "/calculate",
        data={"data_path": data_dir, "reporting_date": "2025-01-01"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[1]
    _wait_for_job(client, job_id)

    # Act — C 02.00 has no lineage (its cells are not spec-backed)
    grid = client.get(f"/results/{job_id}/templates", params={"template": "c_02_00"}).text
    dead = client.get(
        f"/results/{job_id}/lineage",
        params={"template": "c34_01", "row": "0010", "col": "0010"},
    )

    # Assert — a cell is only offered as a link where there is a truthful answer;
    # asking anyway is a clean 404, never a re-derived guess.
    assert "cell-link" not in grid
    assert dead.status_code == 404


def test_template_viewer_unknown_run_is_not_found(client: TestClient) -> None:
    # Act
    resp = client.get("/results/does-not-exist/templates")

    # Assert
    assert resp.status_code == 404


# =============================================================================
# Templates page — prior_run_id (CR8 comparative period)
# =============================================================================


def _seed_irb_run(
    run_id: str,
    reporting_date: date,
    *,
    firb_rwa: float,
    airb_rwa: float,
    results_dir: Path,
    framework: str = "CRR",
) -> None:
    """Register a synthetic IRB-only run so CR8's opening/closing sum has data.

    Bypasses the pipeline: a hand-written results parquet plus a directly
    constructed CalculationResponse, registered straight into the shared REST
    run registry the UI reads through ``get_run`` / ``get_template_bundles``
    (mirrors the twin helper in test_rest_api.py). ``with_reporting_ledger``
    seals the frame to the shape the other Pillar 3 templates (OV1 etc.)
    require, matching the production aggregator-exit contract.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "results.parquet"
    with_reporting_ledger(
        pl.LazyFrame(
            {
                "exposure_reference": ["EXP-FIRB", "EXP-AIRB"],
                "approach_applied": ["foundation_irb", "advanced_irb"],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "rwa_final": [firb_rwa, airb_rwa],
            }
        )
    ).collect().write_parquet(results_path)
    response = CalculationResponse(
        success=True,
        framework=framework,
        reporting_date=reporting_date,
        summary=SummaryStatistics(
            total_ead=Decimal("2000000"),
            total_rwa=Decimal(str(firb_rwa + airb_rwa)),
            exposure_count=2,
            average_risk_weight=Decimal("0.5"),
        ),
        results_path=results_path,
    )
    register_run_with_id(run_id, response)


def _cr8_opening_cell(html: str) -> str:
    """Strip-tag text of the CR8 row-1 / col-a cell from a rendered templates page."""
    match = re.search(
        r'data-template="cr8"\s+data-sheet=""\s+data-row="1"\s+data-col="a">(.*?)</td>',
        html,
        re.S,
    )
    assert match is not None, "CR8 row 1 / col a is not on the rendered page"
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


def test_templates_page_prior_run_id_populates_cr8_opening_cell(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — prior period IRB RWA sums to 1,000,000.
    _seed_irb_run(
        "ui-prior-cr8",
        date(2024, 12, 31),
        firb_rwa=600_000.0,
        airb_rwa=400_000.0,
        results_dir=tmp_path / "prior",
    )
    _seed_irb_run(
        "ui-current-cr8",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "current",
    )

    # Act
    resp = client.get(
        "/results/ui-current-cr8/templates",
        params={"template": "cr8", "prior_run_id": "ui-prior-cr8"},
    )

    # Assert
    assert resp.status_code == 200
    assert _cr8_opening_cell(resp.text) == "1,000,000"


def test_templates_page_without_prior_run_id_cr8_opening_cell_is_null(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange
    _seed_irb_run(
        "ui-current-cr8-solo",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "solo",
    )

    # Act — no prior_run_id at all
    resp = client.get("/results/ui-current-cr8-solo/templates", params={"template": "cr8"})

    # Assert — unchanged behaviour: CR8's opening row stays null.
    assert resp.status_code == 200
    assert _cr8_opening_cell(resp.text) == "—"


def test_cr8_prior_period_cell_refuses_lineage_instead_of_contradicting_the_report(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — a comparative-period report: prior IRB RWA sums to 1,000,000.
    _seed_irb_run(
        "ui-prior-cr8-lin",
        date(2024, 12, 31),
        firb_rwa=600_000.0,
        airb_rwa=400_000.0,
        results_dir=tmp_path / "prior",
    )
    _seed_irb_run(
        "ui-current-cr8-lin",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "current",
    )

    # The templates page (WITH the prior period) shows a real opening figure...
    page = client.get(
        "/results/ui-current-cr8-lin/templates",
        params={"template": "cr8", "prior_run_id": "ui-prior-cr8-lin"},
    )
    assert page.status_code == 200
    assert _cr8_opening_cell(page.text) == "1,000,000"

    # ...but the drill-down runs on the current-period ledger only. Rather than a
    # panel showing a null that contradicts the 1,000,000 on screen, the opening
    # (row 1, PriorPeriod) and residual (row 8) cells get a DISTINCT refusal.
    for prior_row in ("1", "8"):
        refused = client.get(
            "/results/ui-current-cr8-lin/lineage",
            params={"template": "cr8", "row": prior_row, "col": "a"},
        )
        assert refused.status_code == 404, f"row {prior_row}"
        assert "prior period" in refused.text.lower(), f"row {prior_row}"

    # The closing row (9, current period) still drills down normally.
    closing = client.get(
        "/results/ui-current-cr8-lin/lineage",
        params={"template": "cr8", "row": "9", "col": "a"},
    )
    assert closing.status_code == 200
    assert "Cell lineage" in closing.text


def test_templates_page_cache_key_separates_prior_run_id(
    client: TestClient, tmp_path: Path
) -> None:
    """A bundle generated WITH a prior period must not be served for a request
    without one, and vice versa — the bundle cache is keyed on both ids."""
    # Arrange
    _seed_irb_run(
        "ui-prior-cache",
        date(2024, 12, 31),
        firb_rwa=600_000.0,
        airb_rwa=400_000.0,
        results_dir=tmp_path / "prior_cache",
    )
    _seed_irb_run(
        "ui-current-cache",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "current_cache",
    )

    # Act — request WITHOUT a prior period first, so a run_id-only cache key
    # would poison the second (with-prior) request with the null bundle.
    without_prior = client.get("/results/ui-current-cache/templates", params={"template": "cr8"})
    with_prior = client.get(
        "/results/ui-current-cache/templates",
        params={"template": "cr8", "prior_run_id": "ui-prior-cache"},
    )

    # Assert — each request gets its own correctly-generated bundle.
    assert _cr8_opening_cell(without_prior.text) == "—"
    assert _cr8_opening_cell(with_prior.text) == "1,000,000"


def test_templates_page_unknown_prior_run_id_is_404(client: TestClient, tmp_path: Path) -> None:
    # Arrange
    _seed_irb_run(
        "ui-current-404",
        date(2025, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "ui404",
    )

    # Act
    resp = client.get(
        "/results/ui-current-404/templates", params={"prior_run_id": "does-not-exist"}
    )

    # Assert
    assert resp.status_code == 404


def test_templates_page_prior_run_id_mismatched_framework_is_422(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — the prior run targets a different framework than the current run.
    _seed_irb_run(
        "ui-prior-fw",
        date(2024, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "ui_prior_fw",
        framework="BASEL_3_1",
    )
    _seed_irb_run(
        "ui-current-fw",
        date(2025, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "ui_current_fw",
        framework="CRR",
    )

    # Act
    resp = client.get("/results/ui-current-fw/templates", params={"prior_run_id": "ui-prior-fw"})

    # Assert
    assert resp.status_code == 422
    assert "framework" in resp.json()["detail"]


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
    location = resp.headers["location"]
    run_id = location.rsplit("/", 1)[1]
    # The stepper shows a trailing "Create exports" step for an export-writing run.
    stepper = client.get(location).text
    assert 'data-stage="write_exports"' in stepper
    assert "Create exports" in stepper
    status = _wait_for_job(client, run_id)

    # Assert — file on disk, stage count unchanged (the export write is a synthetic
    # tail step, not a registry stage), and the results page reports what was written.
    assert status["status"] == "done"
    assert status["total_stages"] == 11
    # The trailing export step is ticked off once the files are written.
    assert "write_exports" in status["completed"]
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
    # The by-class delta is also split by methodology (CRR vs B31); the all-SA
    # dataset renders the STD subsection under the class×method panel.
    assert "RWA by exposure class &amp; methodology" in resp.text
    assert 'class="method-subtitle"' in resp.text
    # The comparison is cached and its download buttons are wired to the export API.
    assert "Download comparison" in resp.text
    assert "/api/comparison/export/csv?comparison_id=" in resp.text
    assert "/api/comparison/export/parquet?comparison_id=" in resp.text


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


# =============================================================================
# Calculation reuse — calculator banner + comparison seeding
# =============================================================================


def test_calculator_offers_results_link_when_identical_run_exists(
    client: TestClient, data_dir: str
) -> None:
    # A fresh form offers nothing.
    assert "already ran at" not in client.get("/calculator").text

    # Arrange — run a calculation via the form (the worker saves the form state
    # and seeds the run index).
    posted = client.post(
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
    assert posted.status_code == 303
    job_id = posted.headers["location"].rsplit("/", 1)[1]
    assert _wait_for_job(client, job_id)["status"] == "done"

    # Act — reopen the calculator (pre-filled with the same values).
    form = client.get("/calculator")

    # Assert — a non-blocking banner links straight to the existing results.
    assert "already ran at" in form.text
    assert f"/results/{job_id}" in form.text


def test_comparison_seeds_run_index_for_both_frameworks(client: TestClient, data_dir: str) -> None:
    # Act — a comparison runs both frameworks over one dataset.
    resp = client.post(
        "/comparison",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "permission_mode": "standardised",
            "data_format": "parquet",
        },
    )
    assert resp.status_code == 200

    # Assert — both embedded runs are reusable (e.g. by a reconciliation) and
    # registered for the results endpoints.
    for framework in ("CRR", "BASEL_3_1"):
        fingerprint = run_index.compute_fingerprint(
            data_path=data_dir,
            framework=framework,
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
        )
        hit = run_index.find_reusable(fingerprint)
        assert hit is not None, framework
        assert get_run(hit.run_id) is not None, framework
