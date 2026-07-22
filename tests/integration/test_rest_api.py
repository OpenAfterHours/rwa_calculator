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

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.api import create_api_app, run_index
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.rest import register_run_with_id
from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum
from tests.fixtures.recon_ledger import with_reporting_ledger

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


# =============================================================================
# Report templates (GET /api/templates, GET /api/templates/{template_id})
# =============================================================================


def _run(client: TestClient, data_dir: str) -> str:
    """Run a CRR calculation and return its run_id."""
    run_id: str = client.post(
        "/api/calculate",
        json={
            "data_path": data_dir,
            "framework": "CRR",
            "reporting_date": date(2025, 1, 1).isoformat(),
            "permission_mode": "standardised",
        },
    ).json()["run_id"]
    return run_id


def test_templates_index_lists_the_generated_templates(client: TestClient, data_dir: str) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act
    resp = client.get("/api/templates", params={"run_id": run_id})

    # Assert — the SA corporate loan produces C 07.00, keyed by exposure class.
    assert resp.status_code == 200
    body = resp.json()
    assert body["framework"] == "CRR"
    c07 = next(t for t in body["templates"] if t["id"] == "c07_00")
    assert c07["title"].startswith("C 07.00")
    assert c07["family"] == "corep"
    assert c07["sheets"] == ["corporate"]


def test_template_sheet_returns_headers_and_the_generated_cells(
    client: TestClient, data_dir: str
) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act
    resp = client.get("/api/templates/c07_00", params={"run_id": run_id, "sheet": "corporate"})

    # Assert — col 0220 (RWEA) on row 0010 (total) carries the run's RWA.
    assert resp.status_code == 200
    body = resp.json()
    assert body["sheet"] == "corporate"
    headers = {col["ref"]: col for col in body["columns"]}
    assert headers["0220"]["group"] == "RWEA"
    assert headers["0220"]["name"] != "0220"  # a readable name, not the bare ref
    total = next(row for row in body["rows"] if row["row_ref"] == "0010")
    assert total["0220"] > 0


def test_template_sheet_defaults_to_the_first_sheet(client: TestClient, data_dir: str) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act — no sheet named
    resp = client.get("/api/templates/c07_00", params={"run_id": run_id})

    # Assert
    assert resp.status_code == 200
    assert resp.json()["sheet"] == "corporate"


def test_lineage_explains_a_reported_cell_and_lists_its_contributors(
    client: TestClient, data_dir: str
) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act — C 07.00 / corporate / row 0010 (total) / col 0220 (RWEA)
    resp = client.get(
        "/api/lineage",
        params={
            "run_id": run_id,
            "template": "c07_00",
            "sheet": "corporate",
            "row": "0010",
            "col": "0220",
        },
    )

    # Assert — the cell is self-describing (metric + scope + basis), its value is
    # the REPORTED figure, and the legs shown sum back to it.
    assert resp.status_code == 200
    body = resp.json()
    assert body["cell"]["row_ref"] == "0010"
    assert body["kind"] == "rows"
    assert body["metric"] == "sum"
    assert body["metric_columns"] == ["rwa_final"]
    assert body["basis"] == "aggregator_exit"
    assert body["sign"] == "positive"
    assert body["scope"]
    assert body["cell_value"] > 0
    assert body["contribution_total"] == pytest.approx(body["cell_value"])
    assert body["total_rows"] >= 1
    assert "exposure_reference" in body["columns"]
    assert "reporting_leg_role" in body["columns"]  # a contributor is a LEG
    assert len(body["rows"]) >= 1


def test_lineage_reports_a_cell_whose_sources_are_never_produced(
    client: TestClient, data_dir: str
) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act — col 0020 sums own_funds_deduction_amount, which the engine does not
    # put on the ledger (col 0030 used to be the showcase here, but R9 rebound
    # it to the sealed provision carrier — mirrors test_lineage_tieout.py).
    resp = client.get(
        "/api/lineage",
        params={
            "run_id": run_id,
            "template": "c07_00",
            "sheet": "corporate",
            "row": "0010",
            "col": "0020",
        },
    )

    # Assert — the reported 0.0 is flagged as NOT source-backed, so a reviewer can
    # tell "we computed zero" from "we cannot compute this".
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_source_backed"] is False
    assert body["missing_columns"] == body["metric_columns"]
    assert body["sign"] == "positive"
    assert body["contribution_total"] is None


def test_lineage_unknown_run_template_and_cell_are_404(client: TestClient, data_dir: str) -> None:
    # Arrange
    run_id = _run(client, data_dir)
    cell = {"template": "c07_00", "sheet": "corporate", "row": "0010", "col": "0220"}

    # Act / Assert — an uninstrumented template (C 34.01 is still imperative) and
    # an unknown cell are clean 404s, never a re-derived guess.
    assert client.get("/api/lineage", params={**cell, "run_id": "nope"}).status_code == 404
    assert (
        client.get(
            "/api/lineage", params={**cell, "run_id": run_id, "template": "c34_01"}
        ).status_code
        == 404
    )
    assert (
        client.get("/api/lineage", params={**cell, "run_id": run_id, "row": "9999"}).status_code
        == 404
    )


def test_templates_unknown_run_and_unknown_template_are_404(
    client: TestClient, data_dir: str
) -> None:
    # Arrange
    run_id = _run(client, data_dir)

    # Act / Assert — an uninstrumented cell address is a clean 404, never a guess.
    assert client.get("/api/templates", params={"run_id": "nope"}).status_code == 404
    assert client.get("/api/templates/not_a_template", params={"run_id": run_id}).status_code == 404
    assert (
        client.get(
            "/api/templates/c07_00", params={"run_id": run_id, "sheet": "retail"}
        ).status_code
        == 404
    )


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


@pytest.mark.parametrize(
    ("fmt", "media"),
    [
        ("corep_facts_parquet", "parquet"),
        ("corep_facts_ndjson", "ndjson"),
        ("pillar3_facts_parquet", "parquet"),
        ("pillar3_facts_ndjson", "ndjson"),
    ],
)
def test_export_cell_facts_downloads(
    client: TestClient, data_dir: str, fmt: str, media: str
) -> None:
    """The flat, keyed cell-fact feed (reporting/facts.py) downloads the same
    way as the other export formats, with the same run_id-in-filename guard."""
    # Arrange
    run_id = _run(client, data_dir)

    # Act
    resp = client.get(f"/api/export/{fmt}", params={"run_id": run_id})

    # Assert
    assert resp.status_code == 200
    assert resp.content
    disposition = resp.headers.get("content-disposition", "")
    assert run_id not in disposition
    assert media in disposition


def test_export_filenames_are_stamped_with_framework_and_reporting_date(
    client: TestClient, data_dir: str
) -> None:
    """Filenames now carry server-validated run data (framework, reporting
    date) instead of a bare fixed literal — still never the opaque run_id."""
    # Arrange
    run_id = _run(client, data_dir)

    # Act
    resp = client.get("/api/export/corep", params={"run_id": run_id})

    # Assert
    disposition = resp.headers.get("content-disposition", "")
    assert "CRR" in disposition
    assert "2025-01-01" in disposition
    assert run_id not in disposition


def test_export_entity_identifier_is_stamped_into_corep_facts(
    client: TestClient, data_dir: str
) -> None:
    """The optional entity_identifier query param reaches every fact row."""
    # Arrange
    run_id = _run(client, data_dir)

    # Act
    resp = client.get(
        "/api/export/corep_facts_ndjson",
        params={"run_id": run_id, "entity_identifier": "LEI999"},
    )

    # Assert — every fact row carries the caller-supplied entity id and the run id.
    assert resp.status_code == 200
    records = [json.loads(line) for line in resp.content.decode().splitlines() if line]
    assert records
    assert all(r["entity_identifier"] == "LEI999" for r in records)
    assert all(r["run_id"] == run_id for r in records)


# =============================================================================
# Pillar 3 export — prior_run_id (CR8 comparative period)
# =============================================================================


def _seed_irb_run(
    run_id: str,
    reporting_date: date,
    *,
    firb_rwa: float,
    airb_rwa: float,
    results_dir: Path,
    framework: str = "CRR",
    exposure_class: str | None = None,
) -> None:
    """Register a synthetic IRB-only run so CR8's opening/closing sum has data.

    Bypasses the pipeline: a hand-written results parquet plus a directly
    constructed CalculationResponse, registered straight into the REST run
    registry (mirrors ``_seed_reusable_calculation`` in
    test_ui_reconciliation.py). Only ``approach_applied`` + ``rwa_final``
    matter to CR8 (see tests/fixtures/p2_48/p2_48.py for the same minimal
    shape used by the generator's own unit tests); ``with_reporting_ledger``
    seals the frame to the shape the other Pillar 3 templates (OV1 etc.)
    require, matching the production aggregator-exit contract.

    ``exposure_class``, when supplied, adds an ``exposure_class`` column (so
    ``with_reporting_ledger`` derives a real ``reporting_class_origin`` value)
    — COREP C 08.04 is a per-class sheet keyed on that column, unlike Pillar 3
    CR8 which doesn't split by class and doesn't need it.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "results.parquet"
    columns: dict[str, list[object]] = {
        "exposure_reference": ["EXP-FIRB", "EXP-AIRB"],
        "approach_applied": ["foundation_irb", "advanced_irb"],
        "ead_final": [1_000_000.0, 1_000_000.0],
        "rwa_final": [firb_rwa, airb_rwa],
    }
    if exposure_class is not None:
        columns["exposure_class"] = [exposure_class, exposure_class]
    with_reporting_ledger(pl.LazyFrame(columns)).collect().write_parquet(results_path)
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


def _cr8_opening_value(records: list[dict]) -> object:
    """The CR8 row-1 ("a") cell value from a pillar3_facts_ndjson payload."""
    opening = next(
        r
        for r in records
        if r["template_id"] == "cr8" and r["row_ref"] == "1" and r["col_ref"] == "a"
    )
    return opening["value"]


def test_export_pillar3_with_prior_run_id_populates_cr8_opening_row(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — prior period IRB RWA sums to 1,000,000; current to 1,150,000.
    _seed_irb_run(
        "prior-cr8",
        date(2024, 12, 31),
        firb_rwa=600_000.0,
        airb_rwa=400_000.0,
        results_dir=tmp_path / "prior",
    )
    _seed_irb_run(
        "current-cr8",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "current",
    )

    # Act
    resp = client.get(
        "/api/export/pillar3_facts_ndjson",
        params={"run_id": "current-cr8", "prior_run_id": "prior-cr8"},
    )

    # Assert — CR8 row 1 (opening) is the prior period's IRB rwa_final sum.
    assert resp.status_code == 200
    records = [json.loads(line) for line in resp.content.decode().splitlines() if line]
    assert _cr8_opening_value(records) == pytest.approx(1_000_000.0)


def test_export_pillar3_without_prior_run_id_cr8_opening_is_null(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange
    _seed_irb_run(
        "current-cr8-solo",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "solo",
    )

    # Act — no prior_run_id at all
    resp = client.get("/api/export/pillar3_facts_ndjson", params={"run_id": "current-cr8-solo"})

    # Assert — unchanged behaviour: CR8's opening row stays null.
    assert resp.status_code == 200
    records = [json.loads(line) for line in resp.content.decode().splitlines() if line]
    assert _cr8_opening_value(records) is None


def test_export_pillar3_unknown_prior_run_id_is_404(client: TestClient, tmp_path: Path) -> None:
    # Arrange
    _seed_irb_run(
        "current-cr8-404",
        date(2025, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "c404",
    )

    # Act
    resp = client.get(
        "/api/export/pillar3",
        params={"run_id": "current-cr8-404", "prior_run_id": "does-not-exist"},
    )

    # Assert
    assert resp.status_code == 404


def test_export_pillar3_prior_run_id_mismatched_framework_is_422(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — the prior run targets a different framework than the current run.
    _seed_irb_run(
        "prior-cr8-fw",
        date(2024, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "prior_fw",
        framework="BASEL_3_1",
    )
    _seed_irb_run(
        "current-cr8-fw",
        date(2025, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "current_fw",
        framework="CRR",
    )

    # Act
    resp = client.get(
        "/api/export/pillar3",
        params={"run_id": "current-cr8-fw", "prior_run_id": "prior-cr8-fw"},
    )

    # Assert — an explicit but incompatible prior run must not be silently ignored.
    assert resp.status_code == 422
    assert "framework" in resp.json()["detail"]


def test_export_pillar3_prior_run_id_not_earlier_is_422(client: TestClient, tmp_path: Path) -> None:
    # Arrange — the "prior" run's reporting_date is not earlier than the current run's.
    _seed_irb_run(
        "prior-cr8-late",
        date(2025, 6, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "prior_late",
    )
    _seed_irb_run(
        "current-cr8-early",
        date(2025, 1, 1),
        firb_rwa=1.0,
        airb_rwa=1.0,
        results_dir=tmp_path / "current_early",
    )

    # Act
    resp = client.get(
        "/api/export/pillar3",
        params={"run_id": "current-cr8-early", "prior_run_id": "prior-cr8-late"},
    )

    # Assert
    assert resp.status_code == 422
    assert "reporting_date" in resp.json()["detail"]


# =============================================================================
# COREP export — prior_run_id (C 08.04 comparative period)
# =============================================================================


def _c08_04_opening_value(records: list[dict]) -> object:
    """The C 08.04 row-0010 / col-0010 cell value from a corep_facts_ndjson payload."""
    opening = next(
        r
        for r in records
        if r["template_id"] == "c08_04" and r["row_ref"] == "0010" and r["col_ref"] == "0010"
    )
    return opening["value"]


def test_export_corep_with_prior_run_id_populates_c08_04_opening_row(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — prior period IRB RWA sums to 1,000,000; current to 1,150,000.
    # C 08.04 is a per-class sheet (unlike CR8), so both runs need the same
    # exposure_class so the current+prior populations key onto one sheet.
    _seed_irb_run(
        "prior-c0804",
        date(2024, 12, 31),
        firb_rwa=600_000.0,
        airb_rwa=400_000.0,
        results_dir=tmp_path / "prior",
        exposure_class="corporate",
    )
    _seed_irb_run(
        "current-c0804",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "current",
        exposure_class="corporate",
    )

    # Act
    resp = client.get(
        "/api/export/corep_facts_ndjson",
        params={"run_id": "current-c0804", "prior_run_id": "prior-c0804"},
    )

    # Assert — C 08.04 row 0010 (opening) is the prior period's IRB rwa_final sum.
    assert resp.status_code == 200
    records = [json.loads(line) for line in resp.content.decode().splitlines() if line]
    assert _c08_04_opening_value(records) == pytest.approx(1_000_000.0)


def test_export_corep_without_prior_run_id_c08_04_opening_is_null(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange
    _seed_irb_run(
        "current-c0804-solo",
        date(2025, 1, 1),
        firb_rwa=720_000.0,
        airb_rwa=430_000.0,
        results_dir=tmp_path / "solo",
        exposure_class="corporate",
    )

    # Act — no prior_run_id at all
    resp = client.get("/api/export/corep_facts_ndjson", params={"run_id": "current-c0804-solo"})

    # Assert — unchanged behaviour: C 08.04's opening row stays null.
    assert resp.status_code == 200
    records = [json.loads(line) for line in resp.content.decode().splitlines() if line]
    assert _c08_04_opening_value(records) is None


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
