"""
The read-only pages: open a return, its overview, its rules, its templates.

Pipeline position:
    browser  ->  these routes  ->  Workspace / dash.views / dash.grid
        ->  DashContext.render  ->  HTML

Key responsibilities:
- Open a return from an uploaded file or a path on this machine, with the
  header a fact table needs, and say plainly why one could not be opened.
- Draw the overview, the rules and the template viewer for an opened return as
  a build would file it now: with the overrides drafted for it applied, and
  validated again once per change of them (``Workspace.working``).
- Keep every filter in the address, so a page can be bookmarked, reloaded and
  shared with whoever else is looking at the same screen.
- Hand over the evidence behind an opened return's verdict as the file
  ``rwa-filer validate --evidence`` writes.

References:
- rwa_filer.cli — ``rwa-filer validate``, which these pages show the result of
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, RedirectResponse
from starlette.routing import Route

from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.context import THEME_COOKIE, THEMES
from rwa_filer.dash.forms import form_values, open_from_form, page_number
from rwa_filer.dash.grid import template_grid
from rwa_filer.dash.security import served_securely
from rwa_filer.dash.views import overview, rules_page
from rwa_filer.evidence import collect_evidence, write_evidence
from rwa_filer.extras import MissingExtraError
from rwa_filer.release import ReleaseNotFoundError, release_packs, shipped_releases

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext

logger = logging.getLogger(__name__)


# =============================================================================
# Public entry point
# =============================================================================


def routes(context: DashContext) -> list[Route]:
    """The read-only pages, bound to ``context``."""
    pages = ReturnPages(context)
    return [
        Route("/", pages.home, name="home"),
        Route("/open", pages.open_return, methods=["POST"], name="open"),
        Route("/returns/{return_id}", pages.overview, name="overview"),
        Route("/returns/{return_id}/rules", pages.rules, name="rules"),
        Route("/returns/{return_id}/templates", pages.templates, name="templates"),
        Route(
            "/returns/{return_id}/taxonomy",
            pages.switch_taxonomy,
            methods=["POST"],
            name="switch_taxonomy",
        ),
        Route("/returns/{return_id}/evidence.jsonl", pages.evidence, name="evidence"),
        Route("/theme", pages.theme, methods=["POST"], name="theme"),
    ]


class ReturnPages:
    """The handlers of the read-only pages."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def home(self, request: Request) -> Response:
        """The open page: the returns opened so far, and the form to open another."""
        return self._home(request)

    async def open_return(self, request: Request) -> Response:
        """Open the uploaded file, or the file at the given path, and show its overview."""
        form = await request.form()
        try:
            opened = await open_from_form(self.context.workspace, form)
        except (ValueError, ReleaseNotFoundError, MissingExtraError) as exc:
            return self._home(request, error=str(exc), values=form_values(form), status_code=400)
        return RedirectResponse(f"/returns/{opened.return_id}", status_code=303)

    async def switch_taxonomy(self, request: Request) -> Response:
        """Open the return again against the release the form names, and show it."""
        opened = self.context.opened(request)
        form = await request.form()
        version = str(form.get("taxonomy") or "").strip()
        if not version or version == opened.release.version:
            return RedirectResponse(f"/returns/{opened.return_id}", status_code=303)
        try:
            other = await run_in_threadpool(self.context.workspace.reopen, opened, version)
        except (ValueError, ReleaseNotFoundError) as exc:
            return self.context.render(
                request,
                "error.html",
                status_code=400,
                title="The return could not be opened against that release",
                message=str(exc),
            )
        return RedirectResponse(f"/returns/{other.return_id}", status_code=303)

    def overview(self, request: Request) -> Response:
        """Whether the return is fit to file, and the counts behind the answer."""
        working = self.context.working(request)
        return self.context.render(
            request,
            "overview.html",
            working=working,
            section="overview",
            view=overview(working.current),
        )

    def rules(self, request: Request) -> Response:
        """The rules, filtered as the address says, with one picked in full."""
        working = self.context.working(request)
        query = request.query_params
        view = rules_page(
            working.current,
            status=query.get("status", STATUS_FAIL),
            severity=query.get("severity", ""),
            query=query.get("q", ""),
            template=query.get("template", ""),
            rule_id=query.get("rule", ""),
            page=page_number(query.get("page")),
        )
        return self.context.render(
            request, "rules.html", working=working, section="rules", view=view
        )

    def evidence(self, request: Request) -> Response:
        """The evidence behind the verdict the pages show, as the file ``--evidence`` writes.

        That is the return with its drafted overrides applied, as every page of
        it is drawn — so the evidence answers for what a build would file now.
        Collected when asked for, at the accuracy the overview's verdict was
        reached at, and written inside the session's workspace.
        """
        current = self.context.working(request).current
        collected = collect_evidence(
            current.ret,
            release=current.release,
            source_findings=current.reading.findings,
            source=current.validation.source,
        )
        folder = self.context.workspace.directory / "evidence"
        written = write_evidence(collected, folder / f"{current.return_id}.evidence.jsonl")
        name = f"{current.path.stem}.evidence.jsonl"
        return FileResponse(written.path, filename=name, media_type="application/x-ndjson")

    def templates(self, request: Request) -> Response:
        """One table of the return on its grid, with the broken rules' cells marked."""
        working = self.context.working(request)
        query = request.query_params
        grid = template_grid(
            working,
            table=query.get("table", ""),
            sheet=query.get("sheet", ""),
            key=query.get("key", ""),
            row=query.get("row", ""),
            column=query.get("col", ""),
            focus=query.get("focus", ""),
        )
        return self.context.render(
            request,
            "templates.html",
            working=working,
            section="templates",
            grid=grid,
            flash=self.context.take_flash(working.opened.return_id),
        )

    async def theme(self, request: Request) -> Response:
        """Switch between the dark and the light look, and go back where the person was."""
        form = await request.form()
        chosen = str(form.get("theme") or "")
        target = str(form.get("next") or "/")
        if not target.startswith("/") or target.startswith("//"):
            target = "/"
        response = RedirectResponse(target, status_code=303)
        if chosen in THEMES:
            response.set_cookie(
                THEME_COOKIE,
                chosen,
                max_age=365 * 24 * 3600,
                httponly=True,
                secure=served_securely(request),
                samesite="strict",
            )
        return response

    # -- helpers ----------------------------------------------------------------

    def _home(
        self,
        request: Request,
        *,
        error: str | None = None,
        values: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> Response:
        shipped = shipped_releases()
        modules = sorted({info.module for version in shipped for info in release_packs(version)})
        workspace = self.context.workspace
        return self.context.render(
            request,
            "open.html",
            status_code=status_code,
            listed=[workspace.working(opened) for opened in workspace.returns()],
            error=error,
            values=values or {},
            modules=modules,
            releases=shipped,
        )
