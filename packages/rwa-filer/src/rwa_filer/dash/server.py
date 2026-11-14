"""
Run the dashboard — pick a port, print the address, open the browser, serve.

Pipeline position:
    rwa-filer dash  ->  serve(workspace)  ->  uvicorn  ->  dash.app

Key responsibilities:
- Listen on the loopback interface unless told otherwise, on the requested
  port or the next free one, so a second dashboard does not fail to start.
- Print the one address that opens the session — it carries the token — and
  open it in the browser unless asked not to.
- Stay quiet otherwise: the server's access log is not the user's business.

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
from rwa_filer.dash.security import LOOPBACK_HOSTS, TOKEN_PARAMETER, new_token

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_filer.dash.workspace import Workspace

logger = logging.getLogger(__name__)

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765
#: How many ports above the requested one are tried before the OS picks one.
_PORT_ATTEMPTS: Final = 20
#: Seconds to wait before opening the browser, so the server is listening.
_BROWSER_DELAY: Final = 0.8


def serve(  # noqa: PLR0913 - each argument is a separate choice about the server
    workspace: Workspace,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    start_path: str = "/",
    announce: Callable[[str], None] = logger.info,
) -> None:
    """Serve the dashboard over ``workspace`` until interrupted."""
    token = new_token()
    bound = free_port(host, port)
    hosts = LOOPBACK_HOSTS if host in LOOPBACK_HOSTS else (*LOOPBACK_HOSTS, host)
    app = create_app(workspace, token=token, allowed_hosts=hosts)
    address = session_address(host, bound, start_path, token)
    announce(f"rwa-filer dash is running at {address}")
    announce("The address carries this session's token: keep it to yourself. Ctrl+C stops it.")
    if open_browser:
        threading.Timer(_BROWSER_DELAY, _open, args=(address,)).start()
    uvicorn.run(app, host=host, port=bound, log_level="warning")


def session_address(host: str, port: int, path: str, token: str) -> str:
    """The address that opens a session: the page, with the token to unlock it."""
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{port}{path}?{TOKEN_PARAMETER}={token}"


def free_port(host: str, port: int) -> int:
    """``port`` if it is free on ``host``, else the next free one, else any.

    There is a moment between this check and the server binding in which
    another program could take the port; uvicorn then says so.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for candidate in range(port, port + _PORT_ATTEMPTS):
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def _open(address: str) -> None:
    try:
        webbrowser.open(address)
    except webbrowser.Error:  # pragma: no cover - a missing browser is not an error
        logger.debug("could not open a browser", exc_info=True)
