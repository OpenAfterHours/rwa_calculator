"""
The read-only pages: open a return, its overview, its rules, its templates.

Pipeline position:
    browser  ->  these routes  ->  Workspace / dash.views / dash.grid
        ->  DashContext.render  ->  HTML

Key responsibilities:
- Open a return from an uploaded file or a path on this machine, with the
  header a fact table needs, and say plainly why one could not be opened.
- Draw the overview, the rules and the template viewer for an opened return
  from the validation it was opened with.
- Keep every filter in the address, so a page can be bookmarked, reloaded and
  shared with whoever else is looking at the same screen.

References:
- rwa_filer.cli — ``rwa-filer validate``, which these pages show the result of
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse
from starlette.routing import Route

from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.context import THEME_COOKIE, THEMES
from rwa_filer.dash.grid import template_grid
from rwa_filer.dash.views import overview, rules_page
from rwa_filer.readers import HeaderFields, carries_header
from rwa_filer.taxonomy.pack import PackNotFoundError, available_packs

if TYPE_CHECKING:
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext

logger = logging.getLogger(__name__)

#: The form fields of the open page, echoed back when a return cannot be opened.
_FORM_FIELDS: Final = ("path", "entity", "reference_date", "module", "currency")


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
        values = {name: str(form.get(name) or "").strip() for name in _FORM_FIELDS}
        try:
            fields = _header_fields(values)
            path, name = await self._source(form, values["path"])
        except ValueError as exc:
            return self._home(request, error=str(exc), values=values, status_code=400)
        if not carries_header(path) and not (
            fields.entity and fields.reference_date and fields.module
        ):
            message = (
                f"{name} is a fact table, which carries no header: give the entity, the "
                "reference date and the module."
            )
            return self._home(request, error=message, values=values, status_code=400)
        try:
            opened = await run_in_threadpool(self.context.workspace.open, path, fields, name=name)
        except (ValueError, PackNotFoundError) as exc:
            return self._home(request, error=str(exc), values=values, status_code=400)
        return RedirectResponse(f"/returns/{opened.return_id}", status_code=303)

    def overview(self, request: Request) -> Response:
        """Whether the return is fit to file, and the counts behind the answer."""
        opened = self.context.opened(request)
        return self.context.render(
            request, "overview.html", current=opened, section="overview", view=overview(opened)
        )

    def rules(self, request: Request) -> Response:
        """The rules, filtered as the address says, with one picked in full."""
        opened = self.context.opened(request)
        query = request.query_params
        view = rules_page(
            opened,
            status=query.get("status", STATUS_FAIL),
            severity=query.get("severity", ""),
            query=query.get("q", ""),
            template=query.get("template", ""),
            rule_id=query.get("rule", ""),
            page=_page_number(query.get("page")),
        )
        return self.context.render(
            request, "rules.html", current=opened, section="rules", view=view
        )

    def templates(self, request: Request) -> Response:
        """One table of the return on its grid, with the broken rules' cells marked."""
        opened = self.context.opened(request)
        query = request.query_params
        grid = template_grid(
            opened,
            table=query.get("table", ""),
            sheet=query.get("sheet", ""),
            key=query.get("key", ""),
            row=query.get("row", ""),
            column=query.get("col", ""),
            focus=query.get("focus", ""),
        )
        return self.context.render(
            request, "templates.html", current=opened, section="templates", grid=grid
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
            response.set_cookie(THEME_COOKIE, chosen, samesite="strict", max_age=365 * 24 * 3600)
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
        modules = sorted({info.module for info in available_packs()})
        return self.context.render(
            request,
            "open.html",
            status_code=status_code,
            error=error,
            values=values or {},
            modules=modules,
        )

    async def _source(self, form: FormData, path_text: str) -> tuple[Path, str]:
        """Where the return to open is, and the name to show it under.

        Raises:
            ValueError: neither a file nor a path was given.
        """
        upload = form.get("file")
        if isinstance(upload, UploadFile) and upload.filename:
            content = await upload.read()
            saved = await run_in_threadpool(
                self.context.workspace.save_upload, upload.filename, content
            )
            return saved, upload.filename
        if path_text:
            path = Path(path_text).expanduser()
            return path, path.name
        raise ValueError("Choose a file to open, or give the path of one on this machine.")


# =============================================================================
# Private helpers
# =============================================================================


def _header_fields(values: dict[str, str]) -> HeaderFields:
    """The header the person typed in.

    Raises:
        ValueError: the reference date is not a date.
    """
    text = values.get("reference_date", "")
    try:
        reference_date = date.fromisoformat(text) if text else None
    except ValueError:
        raise ValueError(f"{text!r} is not a date: write it as YYYY-MM-DD.") from None
    return HeaderFields(
        entity=values.get("entity") or None,
        reference_date=reference_date,
        module=values.get("module") or None,
        currency=values.get("currency") or None,
    )


def _page_number(text: str | None) -> int:
    try:
        return int(text) if text else 1
    except ValueError:
        return 1
