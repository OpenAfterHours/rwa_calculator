"""Who a running dashboard answers: the session token, the origin check, the host allowlist."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from dash_builders import BASE_URL
from rwa_filer.dash import create_app
from rwa_filer.dash.security import cookie_name

if TYPE_CHECKING:
    from rwa_filer.dash import Workspace

TOKEN = "session-token-for-tests"


@pytest.fixture
def gated(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace, token=TOKEN), base_url=BASE_URL)


def test_a_request_without_the_session_is_refused(gated: TestClient) -> None:
    # Act
    response = gated.get("/")

    # Assert
    assert response.status_code == 403
    assert "Open the address rwa-filer dash printed" in response.text


def test_the_printed_address_opens_the_session_and_drops_the_token(gated: TestClient) -> None:
    # Act
    unlock = gated.get(f"/returns/abc?token={TOKEN}&rule=x", follow_redirects=False)
    after = gated.get("/")

    # Assert — the token leaves the address bar and lives in a cookie for this port only.
    assert unlock.status_code == 303
    assert unlock.headers["location"] == "/returns/abc?rule=x"
    assert f"{cookie_name(8765)}={TOKEN}" in unlock.headers["set-cookie"]
    assert "HttpOnly" in unlock.headers["set-cookie"]
    assert after.status_code == 200


def test_a_wrong_token_is_refused(gated: TestClient) -> None:
    # Act
    response = gated.get("/?token=guess", follow_redirects=False)

    # Assert
    assert response.status_code == 403


def test_the_stylesheets_need_no_session(gated: TestClient) -> None:
    # Act
    response = gated.get("/static/dash.css")

    # Assert
    assert response.status_code == 200
    assert ".t-dark" in response.text


def test_a_cross_site_post_is_refused(client: TestClient) -> None:
    # Act
    response = client.post(
        "/theme", data={"theme": "light"}, headers={"sec-fetch-site": "cross-site"}
    )

    # Assert
    assert response.status_code == 403


def test_a_post_from_another_origin_is_refused(client: TestClient) -> None:
    # Act
    response = client.post(
        "/theme", data={"theme": "light"}, headers={"origin": "http://evil.example"}
    )

    # Assert
    assert response.status_code == 403


def test_a_post_from_the_dashboard_itself_is_accepted(client: TestClient) -> None:
    # Act
    response = client.post(
        "/theme",
        data={"theme": "light", "next": "/"},
        headers={"sec-fetch-site": "same-origin", "origin": BASE_URL},
        follow_redirects=False,
    )

    # Assert
    assert response.status_code == 303


def test_a_host_name_other_than_loopback_is_refused(workspace: Workspace) -> None:
    """A page on another site that rebinds its name to 127.0.0.1 is still another host."""
    # Arrange
    rebound = TestClient(create_app(workspace), base_url="http://attacker.example:8765")

    # Act
    response = rebound.get("/")

    # Assert
    assert response.status_code == 400
