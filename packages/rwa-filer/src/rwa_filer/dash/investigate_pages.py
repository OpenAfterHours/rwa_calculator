"""
The Investigate page — which part of a return each broken rule comes from.

Pipeline position:
    browser  ->  these routes  ->  Workspace.attribution (workflow.attribution)
        ->  dash.breakdown.investigate_page  ->  investigate.html

Key responsibilities:
- Show, for a return opened with breakdown columns, every broken rule against
  the members of one column: who breaks it on their own figures, by how much,
  and what the total hides.
- Work the attribution out behind the progress page the first time it is asked
  for — it runs the rules again on every member — and draw the page from the
  kept result after that, and for every member picked on it.
- Hand over the traced evaluations as CSV, for one member or all.
- Open a return again with breakdown columns chosen from the ones its file
  carries, when it was opened without them.

References:
- rwa_filer.workflow.attribution — what a member breaking a rule means
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from rwa_filer.dash.breakdown import (
    breaks_csv,
    investigate_page,
    pick_dimension,
)
from rwa_filer.dash.context import review_of
from rwa_filer.dash.task_pages import follow
from rwa_filer.progress import PHASE_BREAKDOWN, PHASE_READING, PHASE_RULES, PHASE_STRUCTURE
from rwa_filer.readers import DetailSpec

if TYPE_CHECKING:
    from starlette.requests import Request

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.workspace import WorkingReturn
    from rwa_filer.progress import ProgressCallback

logger = logging.getLogger(__name__)

#: The steps of opening a return again with other breakdown columns.
REOPENING_PHASES: Final = (PHASE_READING, PHASE_STRUCTURE, PHASE_RULES)


def routes(context: DashContext) -> list[Route]:
    """The Investigate page and its downloads, bound to ``context``."""
    pages = InvestigatePages(context)
    return [
        Route("/returns/{return_id}/investigate", pages.investigate, name="investigate"),
        Route("/returns/{return_id}/investigate.csv", pages.download, name="investigate_download"),
        Route(
            "/returns/{return_id}/breakdown",
            pages.break_down,
            methods=["POST"],
            name="break_down",
        ),
    ]


class InvestigatePages:
    """The handlers of the Investigate page."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    async def investigate(self, request: Request) -> Response:
        """The members against the broken rules, worked out behind the progress page once."""
        working = self.context.working(request)
        detail = working.opened.detail
        if detail is None:
            return self._render(request, working)
        dimension = pick_dimension(detail, request.query_params.get("by", ""))
        kept = self.context.workspace.kept_attribution(working, dimension)
        if kept is not None:
            picked = _index(request.query_params.get("m"))
            kept = kept.reviewed(working.current.validation, review_of(request))
            return self._render(
                request, working, view=investigate_page(working.current, kept, picked)
            )
        workspace = self.context.workspace
        destination = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")

        def work(progress: ProgressCallback) -> str:
            workspace.attribution(working, dimension, progress=progress)
            return destination

        def refused(request: Request, error: str, status_code: int) -> Response:
            return self.context.render(
                request,
                "error.html",
                status_code=status_code,
                title="The breaks could not be worked out by that column",
                message=error,
            )

        task = self.context.tasks.start(
            f"Breaking {working.opened.name} down by {dimension}",
            work,
            phases=(PHASE_BREAKDOWN,),
            refused=refused,
        )
        return await follow(self.context, request, task)

    def download(self, request: Request) -> Response:
        """Every traced evaluation, member by member, as CSV; one member's with ``m``."""
        working = self.context.working(request)
        detail = working.opened.detail
        if detail is None:
            return RedirectResponse(f"/returns/{working.opened.return_id}/investigate", 303)
        dimension = pick_dimension(detail, request.query_params.get("by", ""))
        attribution = self.context.workspace.attribution(working, dimension)
        attribution = attribution.reviewed(working.current.validation, review_of(request))
        picked = _index(request.query_params.get("m"))
        name = f"{working.opened.path.stem}.breaks-by-{_safe(dimension)}.csv"
        return Response(
            breaks_csv(attribution, picked),
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )

    async def break_down(self, request: Request) -> Response:
        """Open the return's file again with the breakdown columns the form names."""
        opened = self.context.opened(request)
        form = await request.form()
        chosen = [str(value).strip() for value in form.getlist("breakdown") if str(value).strip()]
        line_ref = str(form.get("line_ref") or "").strip() or None
        on_repeat = str(form.get("on_repeat") or "").strip() or None
        try:
            spec = DetailSpec.from_text(
                ",".join(chosen),
                line_ref,
                on_repeat,
                str(form.get("group_code") or "").strip() or None,
            )
        except ValueError as exc:
            return self._refuse(request, str(exc), 400)
        if not spec.active:
            return self._refuse(
                request, "Choose at least one column to break the return down by.", 400
            )
        workspace = self.context.workspace
        version = opened.release.version

        def work(progress: ProgressCallback) -> str:
            again = workspace.reopen(opened, version, progress=progress, detail=spec)
            return f"/returns/{again.return_id}/investigate"

        task = self.context.tasks.start(
            f"Opening {opened.name} broken down by {', '.join(spec.breakdown) or spec.line_ref}",
            work,
            phases=REOPENING_PHASES,
            refused=self._refuse,
        )
        return await follow(self.context, request, task)

    # -- helpers ----------------------------------------------------------------

    def _render(self, request: Request, working: WorkingReturn, **context: Any) -> Response:
        return self.context.render(
            request, "investigate.html", working=working, section="investigate", **context
        )

    def _refuse(self, request: Request, error: str, status_code: int) -> Response:
        return self.context.render(
            request,
            "error.html",
            status_code=status_code,
            title="The return could not be broken down",
            message=error,
        )


def _index(text: str | None) -> int | None:
    """A member's index from the address; ``None`` for anything that is not one."""
    try:
        return int(text) if text not in (None, "") else None
    except ValueError:
        return None


def _safe(name: str) -> str:
    """A column name fit for a file name."""
    return "".join(character if character.isalnum() else "-" for character in name).strip("-")
