"""
Who may use a running dashboard — the session token and the same-origin check.

Pipeline position:
    browser request  ->  TrustedHostMiddleware  ->  SessionGate  ->  SameOriginGate
        ->  the dashboard's routes

Key responsibilities:
- Answer only the person who started the server. ``rwa-filer dash`` prints an
  address carrying a random token; opening it sets a cookie, and every request
  after that must carry the cookie. Another user of the same machine, or a page
  in the browser that guesses the port, gets a refusal.
- Refuse a state-changing request a page on another origin sends — the
  cross-site form post a token cookie alone would let through.

References:
- rwa_calc.ui.app.main.require_same_origin — the same check in ``rwa-ui``
- OWASP Cross-Site Request Forgery Prevention Cheat Sheet (Fetch Metadata)
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode, urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

#: The host names a loopback server answers to.
LOOPBACK_HOSTS: Final = ("127.0.0.1", "localhost", "::1")
#: The query parameter the printed address carries the token in.
TOKEN_PARAMETER: Final = "token"
#: Methods that change nothing, and so need no origin check.
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
#: Fetch-metadata values a request from this dashboard's own pages carries.
_OWN_SITES: Final = frozenset({"same-origin", "none"})

_LOCKED_PAGE: Final = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>rwa-filer dash</title></head>
<body style="font-family: system-ui, sans-serif; background: #0d0e11; color: #e2e4e8;
padding: 48px; line-height: 1.5">
<h1 style="font-size: 22px">Open the address rwa-filer dash printed</h1>
<p>This dashboard answers only the browser that opened the address printed in the
terminal where it was started, which carries this session's token.</p>
</body></html>
"""


# =============================================================================
# Public entry points
# =============================================================================


class SessionGate(BaseHTTPMiddleware):
    """Require this session's token, given once in the address and kept in a cookie.

    With ``token=None`` the gate is open — for tests, and for an app mounted
    inside another that does its own checking.
    """

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.token is None or request.url.path.startswith("/static/"):
            return await call_next(request)
        cookie = cookie_name(request.url.port)
        given = request.query_params.get(TOKEN_PARAMETER)
        if given is not None and secrets.compare_digest(given, self.token):
            rest = [
                (name, value)
                for name, value in request.query_params.multi_items()
                if name != TOKEN_PARAMETER
            ]
            target = request.url.path + (f"?{urlencode(rest)}" if rest else "")
            response = RedirectResponse(target, status_code=303)
            response.set_cookie(cookie, self.token, httponly=True, samesite="strict")
            return response
        held = request.cookies.get(cookie)
        if held is not None and secrets.compare_digest(held, self.token):
            return await call_next(request)
        return HTMLResponse(_LOCKED_PAGE, status_code=403)


class SameOriginGate(BaseHTTPMiddleware):
    """Refuse a state-changing request that a page on another origin sent."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in _SAFE_METHODS and not is_same_origin(request):
            return PlainTextResponse("cross-site request refused", status_code=403)
        return await call_next(request)


def is_same_origin(request: Request) -> bool:
    """Whether a request came from this dashboard's own pages.

    A browser attaches ``Sec-Fetch-Site`` — and ``Origin`` — to a cross-origin
    form post. A client that is not a browser sends neither and is allowed: it
    already runs as the user.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site in _OWN_SITES
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


def cookie_name(port: int | None) -> str:
    """The session cookie's name. Per port: a browser shares cookies across ports."""
    return f"rwa_filer_dash_{port or 0}"


def new_token() -> str:
    """A fresh session token."""
    return secrets.token_urlsafe(24)
