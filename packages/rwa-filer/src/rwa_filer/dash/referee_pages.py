"""
The Referee page — have the Arelle XBRL processor check a written instance.

Pipeline position:
    browser  ->  these routes  ->  dash.referee_jobs.JobBoard  ->  referee.html

Key responsibilities:
- Offer the instances this return has: the file itself when it is an XBRL
  instance, and each package a build wrote — never a path the browser names.
- Say up front whether Arelle can run, and how to make it run when it cannot.
- Start a run in the background and show its progress, then its verdict, the
  messages Arelle raised and every rule on which the two engines part.

References:
- rwa_filer.cli — ``rwa-filer referee``, which this mirrors
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import RedirectResponse
from starlette.routing import Route

from rwa_filer.dash.referee_jobs import STATUS_RUNNING, arelle_status
from rwa_filer.referee import RefereeUnavailableError
from rwa_filer.referee.report import is_supported, verdict_line

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.workspace import OpenedReturn

#: Seconds between reloads of a page whose run is still going.
REFRESH_SECONDS = 3


def routes(context: DashContext) -> list[Route]:
    """The Referee page, bound to ``context``."""
    pages = RefereePages(context)
    return [
        Route("/returns/{return_id}/referee", pages.referee, name="referee"),
        Route("/returns/{return_id}/referee", pages.start, methods=["POST"]),
    ]


class RefereePages:
    """The handlers of the Referee page."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def referee(self, request: Request) -> Response:
        """The run the address names, or the form to start one."""
        opened = self.context.opened(request)
        return self._page(request, opened, job_id=request.query_params.get("job", ""))

    async def start(self, request: Request) -> Response:
        """Start a run on one of this return's instances."""
        opened = self.context.opened(request)
        form = await request.form()
        instances = dict(instance_choices(self.context, opened))
        chosen = instances.get(str(form.get("instance") or ""))
        package = str(form.get("package") or "").strip()
        python = str(form.get("python") or "").strip()
        rules = str(form.get("rules") or "").strip() or None
        if chosen is None:
            return self._page(
                request, opened, error="Choose an instance to check.", status_code=400
            )
        if not package:
            return self._page(
                request, opened, error="Give the path of the taxonomy package zip.", status_code=400
            )
        try:
            job = self.context.jobs.start(
                opened.return_id,
                chosen,
                Path(package).expanduser(),
                python=Path(python).expanduser() if python else None,
                rules=rules,
            )
        except (RefereeUnavailableError, ValueError) as exc:
            return self._page(request, opened, error=str(exc), status_code=400)
        return RedirectResponse(
            f"/returns/{opened.return_id}/referee?job={job.job_id}", status_code=303
        )

    def _page(
        self,
        request: Request,
        opened: OpenedReturn,
        *,
        job_id: str = "",
        error: str | None = None,
        status_code: int = 200,
    ) -> Response:
        jobs = self.context.jobs
        job = jobs.get(job_id) if job_id else None
        if job is not None and job.return_id != opened.return_id:
            job = None
        available, detail = arelle_status(Path(jobs.last_python) if jobs.last_python else None)
        result = job.result if job else None
        return self.context.render(
            request,
            "referee.html",
            status_code=status_code,
            current=opened,
            section="referee",
            job=job,
            running=job is not None and job.status == STATUS_RUNNING,
            refresh=REFRESH_SECONDS,
            supported=is_supported(result, job.differential) if job and result else None,
            verdict=verdict_line(result, job.differential) if job and result else None,
            instances=instance_choices(self.context, opened),
            history=jobs.for_return(opened.return_id),
            arelle_available=available,
            arelle_detail=detail,
            last_package=jobs.last_package,
            last_python=jobs.last_python,
            error=error,
        )


def instance_choices(context: DashContext, opened: OpenedReturn) -> list[tuple[str, Path]]:
    """The instances a run may check, by the key the form sends."""
    choices: list[tuple[str, Path]] = []
    if opened.path.suffix.lower() == ".xbrl":
        choices.append(("source", opened.path))
    for index, record in enumerate(context.workspace.builds(opened.return_id)):
        path = record.package.instance_path
        if path is not None and path.is_file():
            choices.append((f"build:{index}", path))
    return choices
