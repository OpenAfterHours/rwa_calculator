"""
The Compare page — this return beside another version of it.

Pipeline position:
    browser  ->  these routes  ->  dash.compare.compare_page  ->  compare.html

Key responsibilities:
- Offer the other returns opened this session to compare against, or open a
  new one — an earlier filing, a resubmission — through the same form as the
  Open page, validated as a task with its progress shown as it is there.
- Draw the comparison with every filter in the address, earlier and later
  swappable. The comparison itself is worked out once per pair, by the
  workspace, so filtering never re-evaluates the rules.

References:
- rwa_filer.cli — ``rwa-filer diff`` and ``rwa-filer compare``, which this shows
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.routing import Route

from rwa_filer.dash.compare import compare_page
from rwa_filer.dash.forms import form_values, page_number, read_open_form
from rwa_filer.dash.pages import OPENING_PHASES
from rwa_filer.dash.task_pages import follow
from rwa_filer.release import release_packs, shipped_releases

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.workspace import OpenedReturn
    from rwa_filer.progress import ProgressCallback


def routes(context: DashContext) -> list[Route]:
    """The Compare page, bound to ``context``."""
    pages = ComparePages(context)
    return [
        Route("/returns/{return_id}/compare", pages.compare, name="compare"),
        Route("/returns/{return_id}/compare", pages.open_other, methods=["POST"]),
    ]


class ComparePages:
    """The handlers of the Compare page."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def compare(self, request: Request) -> Response:
        """The comparison with the return the address names, or the choice of one."""
        opened = self.context.opened(request)
        query = request.query_params
        other = self.context.workspace.get(query.get("against", ""))
        if other is None or other.return_id == opened.return_id:
            return self._choose(request, opened)
        swap = query.get("swap") == "1"
        earlier, later = (opened, other) if swap else (other, opened)
        view = compare_page(
            earlier,
            later,
            kind=query.get("kind", ""),
            table=query.get("table", ""),
            page=page_number(query.get("page")),
            category=query.get("category", ""),
            finding=page_number(query.get("finding")) if query.get("finding") else 0,
            comparison=self.context.workspace.comparison(earlier, later),
        )
        return self.context.render(
            request,
            "compare.html",
            working=self.context.workspace.working(opened),
            section="compare",
            view=view,
            swap=swap,
        )

    async def open_other(self, request: Request) -> Response:
        """Open another version to compare this return with.

        Opened as the Open page opens a return: as a task, whose progress is
        shown if it takes a while.
        """
        opened = self.context.opened(request)
        form = await request.form()
        values = form_values(form)
        try:
            asked = await read_open_form(self.context.workspace, form)
        except ValueError as exc:
            return self._choose(request, opened, error=str(exc), values=values, status_code=400)
        workspace = self.context.workspace

        def work(progress: ProgressCallback) -> str:
            other = asked.open(workspace, progress)
            return f"/returns/{opened.return_id}/compare?against={other.return_id}"

        def refused(request: Request, error: str, status_code: int) -> Response:
            return self._choose(
                request, opened, error=error, values=values, status_code=status_code
            )

        task = self.context.tasks.start(
            f"Validating {asked.name} to compare", work, phases=OPENING_PHASES, refused=refused
        )
        return await follow(self.context, request, task)

    def _choose(  # noqa: PLR0913 - the page and the states it can be drawn in
        self,
        request: Request,
        opened: OpenedReturn,
        *,
        error: str | None = None,
        values: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> Response:
        others = [item for item in self.context.workspace.returns() if item is not opened]
        return self.context.render(
            request,
            "compare.html",
            status_code=status_code,
            working=self.context.workspace.working(opened),
            section="compare",
            view=None,
            others=others,
            error=error,
            values=values or {},
            modules=sorted(
                {info.module for version in shipped_releases() for info in release_packs(version)}
            ),
            releases=shipped_releases(),
        )
