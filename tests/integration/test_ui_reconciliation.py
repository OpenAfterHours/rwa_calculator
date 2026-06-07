"""
Integration test: the server-rendered reconciliation page.

Pipeline position:
    TestClient -> FastAPI /reconciliation routes -> CreditRiskCalc.reconcile()
        -> ui.views.reconciliation -> Jinja + SVG

Key responsibilities tested:
- GET /reconciliation renders the form pre-filled with the default TOML mapping.
- POST /reconciliation runs a real reconciliation against a generated legacy file
  and (after the 303) renders the four tiers with an inline SVG chart.
- A bad mapping re-renders the form with an error and a 400.
- GET /reconciliation/{id}?bucket=… reads the cached result; unknown ids 404.

The legacy output is generated from our own SA results (renamed + one RWA nudged
to force a break) so the reconciliation has comparable components and a worklist.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.ui.app.main import create_app
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum


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


def test_reconciliation_form_renders_with_default_mapping(client: TestClient) -> None:
    resp = client.get("/reconciliation")
    assert resp.status_code == 200
    assert "<textarea" in resp.text
    assert "legacy_file" in resp.text  # the default TOML is pre-filled


def test_reconciliation_post_renders_four_tiers(client: TestClient, recon_dir: str) -> None:
    # TestClient follows the 303 to /reconciliation/{id}
    resp = client.post("/reconciliation", data=_form_data(recon_dir))
    assert resp.status_code == 200
    assert "Headline" in resp.text
    assert "Worklist" in resp.text
    assert "Forensic" in resp.text
    assert '<svg class="chart"' in resp.text


def test_reconciliation_bucket_filter_reads_cached_result(
    client: TestClient, recon_dir: str
) -> None:
    posted = client.post("/reconciliation", data=_form_data(recon_dir), follow_redirects=False)
    assert posted.status_code == 303
    location = posted.headers["location"]
    assert location.startswith("/reconciliation/")

    got = client.get(location, params={"bucket": "break"})
    assert got.status_code == 200
    assert "Forensic" in got.text


def test_reconciliation_bad_mapping_rerenders_with_error(
    client: TestClient, recon_dir: str
) -> None:
    resp = client.post("/reconciliation", data=_form_data(recon_dir, mapping_toml="not valid ["))
    assert resp.status_code == 400
    assert "Reconciliation failed" in resp.text


def test_reconciliation_unknown_id_is_404(client: TestClient) -> None:
    assert client.get("/reconciliation/does-not-exist").status_code == 404
