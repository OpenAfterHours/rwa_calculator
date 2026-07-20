"""
Unit tests: REST reporting-scope plumbing (multi-entity reporting).

Pipeline position:
    TestClient -> rest.router (calculate / comparison / entities)

Key responsibilities tested:
- ``/api/calculate`` and ``/api/comparison`` fold the reporting scope into
  EVERY paired ``compute_fingerprint`` call, so a scoped run can never collide
  with an unscoped one over identical data (the Wave-1 fail-silent fingerprint
  trap) — and the stamped response carries the same scope as its fingerprint.
- Request validation: an unknown ``reporting_basis`` is a 422; an entity given
  without a basis is a 422 (never the engine's ``ValueError`` surfacing as a
  500); a basis alone stays valid.
- ``GET /api/entities`` reads the optional reporting-entities registry: rows
  when present, an empty list when absent, a 422 for a bad data path.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

from rwa_calc.api import create_api_app, run_index

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


def _calc_body(data_dir: str, **extra: object) -> dict:
    """A minimal calculate/comparison body, with scope overrides merged in."""
    body: dict = {
        "data_path": data_dir,
        "reporting_date": "2025-01-01",
        "framework": "CRR",
        "permission_mode": "standardised",
        "data_format": "parquet",
    }
    body.update(extra)
    return body


def _fingerprint_spy(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture every ``(fingerprint, response)`` the endpoint registers.

    The spy appends *before* delegating, so a captured fingerprint reflects
    exactly what the endpoint computed — independent of whether the underlying
    run succeeded (a failed scoped run over a registry-less dataset is still
    fingerprinted, and that fingerprint must still carry the scope).
    """
    captured: list = []
    real = run_index.register_calculation

    def spy(fingerprint: object, run_id: str, response: object) -> None:
        captured.append((fingerprint, response))
        return real(fingerprint, run_id, response)  # type: ignore[arg-type]

    monkeypatch.setattr(run_index, "register_calculation", spy)
    return captured


# =============================================================================
# Fingerprint distinctness — the fail-silent scope trap
# =============================================================================


def test_scoped_calculate_fingerprints_distinctly_from_unscoped(
    client: TestClient, data_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    captured = _fingerprint_spy(monkeypatch)

    # Act — the SAME data, once unscoped, once scoped.
    r1 = client.post("/api/calculate", json=_calc_body(data_dir))
    r2 = client.post(
        "/api/calculate",
        json=_calc_body(data_dir, reporting_entity="ACME", reporting_basis="consolidated"),
    )

    # Assert
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(captured) == 2
    (unscoped_fp, unscoped_resp), (scoped_fp, scoped_resp) = captured
    assert unscoped_fp.reporting_entity is None
    assert unscoped_fp.reporting_basis is None
    assert scoped_fp.reporting_entity == "ACME"
    assert scoped_fp.reporting_basis == "consolidated"
    # The whole point: identical data, but the two fingerprints must not collide.
    assert unscoped_fp != scoped_fp
    # And the response indexed under the scoped fingerprint carries the same scope.
    assert scoped_resp.reporting_entity == "ACME"
    assert scoped_resp.reporting_basis == "consolidated"
    assert unscoped_resp.reporting_entity is None


def test_comparison_threads_one_scope_into_both_fingerprints(
    client: TestClient, data_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    captured = _fingerprint_spy(monkeypatch)

    # Act — one scope applies to both regime runs.
    resp = client.post(
        "/api/comparison",
        json=_calc_body(data_dir, reporting_entity="ACME", reporting_basis="individual"),
    )

    # Assert
    assert resp.status_code == 200
    assert len(captured) == 2
    for fingerprint, response in captured:
        assert fingerprint.reporting_entity == "ACME"
        assert fingerprint.reporting_basis == "individual"
        assert response.reporting_entity == "ACME"
        assert response.reporting_basis == "individual"
    # The two frameworks still fingerprint distinctly from each other.
    assert captured[0][0] != captured[1][0]


# =============================================================================
# Request validation
# =============================================================================


def test_calculate_rejects_entity_without_basis(client: TestClient, data_dir: str) -> None:
    # A config error surfaced as a 422 here, never the engine ValueError as a 500.
    resp = client.post("/api/calculate", json=_calc_body(data_dir, reporting_entity="ACME"))
    assert resp.status_code == 422


def test_calculate_rejects_unknown_basis(client: TestClient, data_dir: str) -> None:
    resp = client.post("/api/calculate", json=_calc_body(data_dir, reporting_basis="not_a_basis"))
    assert resp.status_code == 422


def test_basis_alone_is_accepted(client: TestClient, data_dir: str) -> None:
    # A reporting basis without an entity remains valid (floor-applicability semantics).
    resp = client.post("/api/calculate", json=_calc_body(data_dir, reporting_basis="consolidated"))
    assert resp.status_code == 200


def test_comparison_rejects_entity_without_basis(client: TestClient, data_dir: str) -> None:
    resp = client.post("/api/comparison", json=_calc_body(data_dir, reporting_entity="ACME"))
    assert resp.status_code == 422


# =============================================================================
# GET /api/entities
# =============================================================================


def _write_entities(data_dir: str) -> None:
    config = Path(data_dir) / "config"
    config.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "entity_reference": ["ACME-GRP", "ACME-BANK"],
            "entity_name": ["Acme Group", "Acme Bank plc"],
            "lei": ["LEI-1", None],
            "parent_entity_reference": [None, "ACME-GRP"],
            "institution_type": ["non_ring_fenced", "ring_fenced_body"],
            "core_uk_group": [True, False],
        }
    ).write_parquet(config / "reporting_entities.parquet")


def test_entities_returns_registry_rows(client: TestClient, data_dir: str) -> None:
    # Arrange
    _write_entities(data_dir)

    # Act
    resp = client.get("/api/entities", params={"data_path": data_dir})

    # Assert
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert set(rows[0]) == {
        "entity_reference",
        "entity_name",
        "lei",
        "parent_entity_reference",
        "institution_type",
        "core_uk_group",
    }
    assert rows[0]["entity_reference"] == "ACME-GRP"
    assert rows[1]["parent_entity_reference"] == "ACME-GRP"


def test_entities_empty_when_registry_absent(client: TestClient, data_dir: str) -> None:
    # The dataset has the mandatory minimum but no reporting-entities registry.
    resp = client.get("/api/entities", params={"data_path": data_dir})
    assert resp.status_code == 200
    assert resp.json() == []


def test_entities_rejects_bad_data_path(client: TestClient, tmp_path: Path) -> None:
    resp = client.get("/api/entities", params={"data_path": str(tmp_path / "does-not-exist")})
    assert resp.status_code == 422
