"""
Run the dashboard — pick a port, print the address, open the browser, serve.

Pipeline position:
    rwa-filer dash  ->  serve(workspace)  ->  uvicorn  ->  dash.app

Key responsibilities:
- Listen on the loopback interface and nowhere else, on the requested port or
  the next free one, so a second dashboard does not fail to start.
- Print the one address that opens the session — it carries the token — and
  open it in the browser unless asked not to.
- Stay quiet otherwise: the server's access log is not the user's business.

Why loopback only: the server speaks plain HTTP. Bound to a network interface
it would send the session token, and every figure of the return, across that
network unencrypted. There is no option to bind it elsewhere.

References:
- uvicorn: ``uvicorn.run``
"""

from __future__ import annotations

import logging
import socket
import threading
import webbrowser
from typing import TYPE_CHECKING, Final

import uvicorn

from rwa_filer.dash.app import create_app
from rwa_filer.dash.security import TOKEN_PARAMETER, new_token

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_filer.dash.workspace import Workspace

logger = logging.getLogger(__name__)

#: The interface the server binds: this machine only.
LOOPBACK: Final = "127.0.0.1"
#: The address the browser is sent to — the same machine, by the name ``rwa-ui``
#: uses too; the server answers both (``security.LOOPBACK_HOSTS``).
LOCAL_ORIGIN: Final = "http://localhost"
DEFAULT_PORT: Final = 8765
#: How many ports above the requested one are tried before the OS picks one.
_PORT_ATTEMPTS: Final = 20
#: Seconds to wait before opening the browser, so the server is listening.
_BROWSER_DELAY: Final = 0.8


def serve(
    workspace: Workspace,
    *,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    start_path: str = "/",
    announce: Callable[[str], None] = logger.info,
) -> None:
    """Serve the dashboard over ``workspace`` on this machine until interrupted."""
    token = new_token()
    bound = free_port(port)
    app = create_app(workspace, token=token)
    address = session_address(bound, start_path, token)
    announce(f"rwa-filer dash is running at {address}")
    announce("The address carries this session's token: keep it to yourself. Ctrl+C stops it.")
    if open_browser:
        threading.Timer(_BROWSER_DELAY, _open, args=(address,)).start()
    uvicorn.run(app, host=LOOPBACK, port=bound, log_level="warning")


def session_address(port: int, path: str, token: str) -> str:
    """The address that opens a session: the page, with the token to unlock it."""
    return f"{LOCAL_ORIGIN}:{port}{path}?{TOKEN_PARAMETER}={token}"


def free_port(port: int) -> int:
    """``port`` if it is free on the loopback interface, else the next free one, else any.

    There is a moment between this check and the server binding in which
    another program could take the port; uvicorn then says so.
    """
    for candidate in range(port, port + _PORT_ATTEMPTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((LOOPBACK, candidate))
            except OSError:
                continue
            return candidate
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def _open(address: str) -> None:
    try:
        webbrowser.open(address)
    except webbrowser.Error:  # pragma: no cover - a missing browser is not an error
        logger.debug("could not open a browser", exc_info=True)
