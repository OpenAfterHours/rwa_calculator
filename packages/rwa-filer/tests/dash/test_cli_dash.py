"""``rwa-filer dash`` on the command line, and the server helpers it uses."""

from __future__ import annotations

import socket
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

import rwa_filer.dash
from dash_builders import HEADER_FORM
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main
from rwa_filer.dash.server import LOOPBACK, free_port, session_address

if TYPE_CHECKING:
    from pathlib import Path

HEADER_ARGS = [
    "--entity",
    HEADER_FORM["entity"],
    "--reference-date",
    HEADER_FORM["reference_date"],
    "--module",
    HEADER_FORM["module"],
]


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record what ``serve`` was asked to do instead of starting a server."""
    calls: list[dict[str, Any]] = []

    def fake_serve(workspace: Any, **options: Any) -> None:
        calls.append({"workspace": workspace, **options})

    monkeypatch.setattr(rwa_filer.dash, "serve", fake_serve)
    return calls


def test_dash_opens_the_file_given_and_starts_on_its_overview(
    tmp_path: Path, broken_csv: Path, served: list[dict[str, Any]]
) -> None:
    # Act
    code = main(
        ["dash", str(broken_csv), *HEADER_ARGS, "--no-browser", "--workdir", str(tmp_path / "w")]
    )

    # Assert
    assert code == EXIT_OK
    (call,) = served
    (opened,) = call["workspace"].returns()
    assert call["start_path"] == f"/returns/{opened.return_id}"
    assert call["open_browser"] is False
    assert "host" not in call


def test_dash_without_a_file_starts_on_the_open_page(
    tmp_path: Path, served: list[dict[str, Any]]
) -> None:
    # Act
    code = main(["dash", "--no-browser", "--workdir", str(tmp_path / "w")])

    # Assert
    assert code == EXIT_OK
    assert served[0]["start_path"] == "/"


def test_dash_with_a_file_it_cannot_open_fails_before_serving(
    tmp_path: Path, served: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["dash", str(tmp_path / "absent.csv"), "--workdir", str(tmp_path / "w")])

    # Assert
    assert code == EXIT_FAILED
    assert served == []
    assert "file not found" in capsys.readouterr().err


def test_a_taken_port_moves_to_the_next_free_one() -> None:
    # Arrange — hold a port open.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind((LOOPBACK, 0))
        held.listen()
        taken = held.getsockname()[1]

        # Act
        chosen = free_port(taken)

    # Assert
    assert chosen != taken


def test_the_session_address_is_this_machine_with_the_token() -> None:
    assert session_address(8765, "/returns/ab", "t") == "http://localhost:8765/returns/ab?token=t"


def test_there_is_no_option_to_listen_beyond_this_machine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain HTTP on a network interface would carry the token in clear."""
    # Act
    with pytest.raises(SystemExit):
        main(["dash", "--host", "192.0.2.1", "--workdir", str(tmp_path)])

    # Assert
    assert "unrecognized arguments: --host" in capsys.readouterr().err


def test_no_command_but_dash_loads_the_web_stack() -> None:
    """The web stack is a dependency, but validating or filing never imports it."""
    # Act — a fresh interpreter, so nothing this test session imported counts.
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, rwa_filer.cli, rwa_filer.filing, rwa_filer.validate.returns;"
            "print(sorted(m for m in ('starlette', 'uvicorn', 'jinja2') if m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Assert
    assert loaded == "[]"
