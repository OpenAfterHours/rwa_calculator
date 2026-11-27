"""The Referee page: availability, the instances offered, and a run in the background.

Arelle is an optional extra and is not installed where these tests run, so the
run itself is replaced by one returning verdicts the test chooses. What is
tested is the dashboard's part: what it offers, that it starts the run off the
request thread, and that it sets the verdicts beside the native engine's the
way ``rwa-filer referee`` does.
"""

from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

import pytest

import rwa_filer.dash.referee_jobs as jobs
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.referee import RefereeResult, RefereeUnavailableError, RuleVerdict
from rwa_filer.referee.runner import MODE_FULL

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn


@pytest.fixture
def arelle(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Arelle "installed": a run returns verdicts disagreeing on one broken rule."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "find_arelle_python", lambda python=None: Path("/arelle/python"))

    def fake_run(instance: Path, package: Path, **options: Any) -> RefereeResult:
        calls.append({"instance": instance, "package": package, **options})
        return RefereeResult(
            rules={"boe_b0708": RuleVerdict("boe_b0708", satisfied=1, unsatisfied=0)},
            messages=(),
            skipped=(),
            lost=(),
            chunks=(),
            schema_ref="pra001.xsd",
            filing_indicators=("OF07.00.01",),
            mode=MODE_FULL,
        )

    monkeypatch.setattr(jobs, "run_referee", fake_run)
    return calls


@pytest.fixture
def built(client: TestClient, broken: OpenedReturn, tmp_path: Path) -> Path:
    """The broken return written anyway; the taxonomy package stand-in."""
    client.post(
        f"/returns/{broken.return_id}/build",
        data={"directory": str(tmp_path / "out"), "force": "yes", "author": "A. Preparer"},
    )
    package = tmp_path / "boe-banking-v411.zip"
    package.write_bytes(b"stand-in")
    return package


def _wait(client: TestClient, location: str) -> str:
    for _ in range(100):
        page = client.get(location).text
        if 'data-status="running"' not in page:
            return page
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


def test_without_arelle_the_page_says_how_to_get_it(
    client: TestClient, broken: OpenedReturn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    def missing(python: Path | None = None) -> Path:
        raise RefereeUnavailableError("The referee needs the Arelle XBRL processor")

    monkeypatch.setattr(jobs, "find_arelle_python", missing)

    # Act
    page = client.get(f"/returns/{broken.return_id}/referee").text

    # Assert
    assert 'id="arelle-missing"' in page and "needs the Arelle XBRL processor" in page


def test_a_return_with_no_instance_is_sent_to_build_one(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Act
    page = client.get(f"/returns/{broken.return_id}/referee").text

    # Assert
    assert "build its package first" in page
    assert 'name="instance"' not in page


def test_a_run_checks_the_built_instance_and_shows_where_the_engines_part(
    client: TestClient,
    broken: OpenedReturn,
    built: Path,
    arelle: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — natively boe_b0708 breaks; the stand-in Arelle says it holds.
    report = broken.validation.report
    assert report is not None
    assert any(r.rule_id == "boe_b0708" and r.status == STATUS_FAIL for r in report.results)
    release = Event()
    run = jobs.run_referee

    def delayed_run(instance: Path, package: Path, **options: Any) -> RefereeResult:
        if not release.wait(timeout=20):
            raise AssertionError("the running page did not release the referee")
        return run(instance, package, **options)

    monkeypatch.setattr(jobs, "run_referee", delayed_run)

    # Act
    start = client.post(
        f"/returns/{broken.return_id}/referee",
        data={"instance": "build:0", "package": str(built)},
        follow_redirects=False,
    )
    location = start.headers["location"]
    try:
        running_page = client.get(location)
        assert 'data-status="running"' in running_page.text
        snapshot = running_page.context["job"]
    finally:
        release.set()
    page = _wait(client, location)

    # Assert — the instance the build wrote, the package given, and the disagreement.
    assert start.status_code == 303
    (call,) = arelle
    assert call["instance"].suffix == ".xbrl" and call["package"] == built
    assert 'data-status="done"' in page
    assert snapshot.status == jobs.STATUS_RUNNING
    disagreements = page[page.index('id="disagreements"') :]
    assert "boe_b0708" in disagreements
    assert "DISAGREEMENT" in page


def test_only_an_instance_the_page_offered_can_be_checked(
    client: TestClient,
    broken: OpenedReturn,
    built: Path,
    arelle: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    # Act
    response = client.post(
        f"/returns/{broken.return_id}/referee",
        data={"instance": str(tmp_path / "elsewhere.xbrl"), "package": str(built)},
    )

    # Assert
    assert response.status_code == 400
    assert "Choose an instance" in response.text
    assert arelle == []
