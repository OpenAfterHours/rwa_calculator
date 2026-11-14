"""Fixtures for the dashboard tests: a workspace, a client, and the two small returns."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from dash_builders import BASE_URL, BROKEN_CSV, CLEAN_CSV, HEADER
from rwa_filer.dash import Workspace, create_app

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.dash import OpenedReturn


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace")


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace), base_url=BASE_URL)


@pytest.fixture
def broken_csv(tmp_path: Path) -> Path:
    path = tmp_path / "broken.csv"
    path.write_text(BROKEN_CSV)
    return path


@pytest.fixture
def clean_csv(tmp_path: Path) -> Path:
    path = tmp_path / "clean.csv"
    path.write_text(CLEAN_CSV)
    return path


@pytest.fixture
def broken(workspace: Workspace, broken_csv: Path) -> OpenedReturn:
    return workspace.open(broken_csv, HEADER)
