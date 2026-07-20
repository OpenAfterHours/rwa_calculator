"""
Unit tests: UI form plumbing for the reporting scope (multi-entity reporting).

Pipeline position:
    TestClient -> FastAPI page routes (calculate / comparison / reconciliation)

Key responsibilities tested:
- The calculator / comparison / reconciliation forms surface the reporting
  scope, and an entity given without a basis (or an unknown basis) is a friendly
  form re-render — never the config ``ValueError`` surfacing as a 500.
- A scoped comparison folds the scope into BOTH regime runs' fingerprints AND
  stamps it onto the two seeded reuse responses, so a scoped fingerprint never
  resolves to an unscoped cached response (the Wave-1 ``_seed_comparison_runs``
  warning), and the form's reuse offer only matches a run of the same scope.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum
from tests.fixtures.multi_entity.multi_entity import save_multi_entity_fixtures

from rwa_calc.api import run_index
from rwa_calc.ui.app.calculator_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.app.main import _calculation_reuse_context, create_app
from rwa_calc.ui.views.reconciliation import DEFAULT_MAPPING_TOML

_COMPARISON_DATE = date(2026, 6, 30)


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the per-user state home into tmp so ~/.rwa_calc is untouched."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_run_index() -> None:
    """Each test starts with an empty calculation run index (module-level state)."""
    run_index.clear()


@pytest.fixture
def client() -> TestClient:
    # A loopback host so the app's TrustedHostMiddleware accepts the request.
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    # A sibling of the state home so the persistent run caches never land inside
    # the data path (which would change its fingerprint signature).
    root = tmp_path / "data"
    root.mkdir()
    write_mandatory_minimum(root)
    return str(root)


@pytest.fixture
def multi_entity_dir(tmp_path: Path) -> str:
    root = tmp_path / "data"
    root.mkdir()
    save_multi_entity_fixtures(root)
    return str(root)


# =============================================================================
# Friendly form errors (never a 500)
# =============================================================================


def test_calculator_entity_without_basis_is_form_error_not_500(
    client: TestClient, data_dir: str
) -> None:
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "framework": "CRR",
            "permission_mode": "standardised",
            "data_format": "parquet",
            "reporting_entity": "ACME",  # no basis
        },
    )
    assert resp.status_code == 400
    assert "reporting basis" in resp.text.lower()


def test_calculator_unknown_basis_is_form_error(client: TestClient, data_dir: str) -> None:
    resp = client.post(
        "/calculate",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "reporting_basis": "nonsense",
        },
    )
    assert resp.status_code == 400
    assert "reporting basis" in resp.text.lower()


def test_reconciliation_entity_without_basis_is_form_error(
    client: TestClient, data_dir: str
) -> None:
    resp = client.post(
        "/reconciliation",
        data={
            "data_path": data_dir,
            "reporting_date": "2025-01-01",
            "mapping_toml": DEFAULT_MAPPING_TOML,
            "reporting_entity": "ACME",  # no basis
        },
    )
    assert resp.status_code == 400
    assert "reporting basis" in resp.text.lower()


def test_comparison_entity_without_basis_is_form_error(client: TestClient, data_dir: str) -> None:
    # The comparison page re-renders inline (200 with the error banner), never a 500.
    resp = client.post(
        "/comparison",
        data={
            "data_path": data_dir,
            "reporting_date": "2027-06-30",
            "reporting_entity": "ACME",  # no basis
        },
    )
    assert resp.status_code == 200
    assert "reporting basis" in resp.text.lower()


# =============================================================================
# Comparison scope threading + seed stamp (the _seed_comparison_runs warning)
# =============================================================================


def test_comparison_scope_is_threaded_seeded_and_reusable(
    client: TestClient, multi_entity_dir: str
) -> None:
    # Act — a scoped comparison over a real multi-entity dataset (so both runs
    # succeed and are indexed).
    resp = client.post(
        "/comparison",
        data={
            "data_path": multi_entity_dir,
            "reporting_date": _COMPARISON_DATE.isoformat(),
            "permission_mode": "standardised",
            "data_format": "parquet",
            "reporting_entity": "GRP",
            "reporting_basis": "consolidated",
        },
    )
    assert resp.status_code == 200

    # Assert — both embedded runs were seeded, and each seeded RESPONSE carries
    # the scope (the format_response stamp), matching its scoped fingerprint.
    entries = run_index.entries()
    assert len(entries) == 2
    assert all(entry.response.reporting_entity == "GRP" for entry in entries)
    assert all(entry.response.reporting_basis == "consolidated" for entry in entries)

    # A form with the SAME scope resolves the reuse offer; an unscoped form over
    # identical data must NOT (the scoped fingerprint never collides with the
    # unscoped one).
    for framework in ("CRR", "BASEL_3_1"):
        scoped_fp = run_index.compute_fingerprint(
            data_path=multi_entity_dir,
            framework=framework,
            reporting_date=_COMPARISON_DATE,
            permission_mode="standardised",
            data_format="parquet",
            reporting_entity="GRP",
            reporting_basis="consolidated",
        )
        assert run_index.find_reusable(scoped_fp) is not None
        unscoped_fp = run_index.compute_fingerprint(
            data_path=multi_entity_dir,
            framework=framework,
            reporting_date=_COMPARISON_DATE,
            permission_mode="standardised",
            data_format="parquet",
        )
        assert run_index.find_reusable(unscoped_fp) is None


def test_reuse_context_matches_only_same_scope(client: TestClient, multi_entity_dir: str) -> None:
    # Arrange — seed two scoped CRR/B31 runs via a scoped comparison.
    client.post(
        "/comparison",
        data={
            "data_path": multi_entity_dir,
            "reporting_date": _COMPARISON_DATE.isoformat(),
            "permission_mode": "standardised",
            "data_format": "parquet",
            "reporting_entity": "GRP",
            "reporting_basis": "consolidated",
        },
    )

    # Act / Assert — a same-scope form sees the reuse offer.
    scoped = _calculation_reuse_context(
        data_path=multi_entity_dir,
        reporting_date=_COMPARISON_DATE.isoformat(),
        framework="CRR",
        permission_mode="standardised",
        data_format="parquet",
        reporting_entity="GRP",
        reporting_basis="consolidated",
    )
    assert scoped["reusable_run"] is not None

    # An unscoped form over identical data must not match the scoped run.
    unscoped = _calculation_reuse_context(
        data_path=multi_entity_dir,
        reporting_date=_COMPARISON_DATE.isoformat(),
        framework="CRR",
        permission_mode="standardised",
        data_format="parquet",
    )
    assert unscoped["reusable_run"] is None
