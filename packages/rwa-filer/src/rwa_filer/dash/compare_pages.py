"""
The Compare page — this return beside another version of it.

Pipeline position:
    browser  ->  these routes  ->  dash.compare.compare_page  ->  compare.html

Key responsibilities:
- Offer the other returns opened this session to compare against, or open a
  new one — an earlier filing, a resubmission — through the same form as the
  Open page.
- Draw the comparison with every filter in the address, earlier and later
  swappable.

References:
- rwa_filer.cli — ``rwa-filer diff``, which this shows
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import RedirectResponse
from starlette.routing import Route

from rwa_filer.dash.compare import compare_page
from rwa_filer.dash.forms import form_values, open_from_form, page_number
from rwa_filer.taxonomy.pack import PackNotFoundError, available_packs

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.workspace import OpenedReturn


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
        )
        return self.context.render(
            request, "compare.html", current=opened, section="compare", view=view, swap=swap
        )

    async def open_other(self, request: Request) -> Response:
        """Open another version to compare this return with."""
        opened = self.context.opened(request)
        form = await request.form()
        try:
            other = await open_from_form(self.context.workspace, form)
        except (ValueError, PackNotFoundError) as exc:
            return self._choose(
                request, opened, error=str(exc), values=form_values(form), status_code=400
            )
        return RedirectResponse(
            f"/returns/{opened.return_id}/compare?against={other.return_id}", status_code=303
        )

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
            current=opened,
            section="compare",
            view=None,
            others=others,
            error=error,
            values=values or {},
            modules=sorted({info.module for info in available_packs()}),
        )
