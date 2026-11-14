"""
The dashboard application — the routes, the middleware and the static files.

Pipeline position:
    serve()  ->  create_app(workspace)  ->  Starlette  ->  dash.pages handlers

Key responsibilities:
- Assemble the pages each part of the dashboard contributes into one app.
- Put the session gate, the same-origin check and the host allowlist in front
  of every route.
- Answer an unknown address with the dashboard's own page, not a stack trace.

References:
- Starlette: applications, routing, middleware, static files
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from rwa_filer.dash import (
    compare_pages,
    filing_pages,
    pages,
    referee_pages,
    reference_pages,
)
from rwa_filer.dash.context import STATIC_DIR, DashContext
from rwa_filer.dash.security import LOOPBACK_HOSTS, SameOriginGate, SessionGate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.workspace import Workspace


def create_app(
    workspace: Workspace,
    *,
    token: str | None = None,
    allowed_hosts: Sequence[str] = LOOPBACK_HOSTS,
) -> Starlette:
    """The dashboard over ``workspace``.

    Args:
        workspace: The returns this session opens, and where its files live.
        token: The session token every request must carry; ``None`` leaves the
            app open (tests, or an app mounted inside one that checks itself).
        allowed_hosts: The ``Host`` headers answered — the loopback names unless
            the server was bound elsewhere on purpose.
    """
    context = DashContext(workspace)

    async def not_found(request: Request, exc: Exception) -> Response:
        detail = exc.detail if isinstance(exc, HTTPException) else "Not found."
        return context.render(request, "error.html", status_code=404, message=detail)

    return Starlette(
        routes=[
            *pages.routes(context),
            *filing_pages.routes(context),
            *compare_pages.routes(context),
            *referee_pages.routes(context),
            *reference_pages.routes(context),
            Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
        ],
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts)),
            Middleware(SessionGate, token=token),
            Middleware(SameOriginGate),
        ],
        exception_handlers={404: not_found},
    )
