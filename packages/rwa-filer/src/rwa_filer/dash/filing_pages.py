"""
The write actions: draft a cell override, build the package, sign it off, verify it.

Pipeline position:
    browser form  ->  these routes  ->  dash.filing  ->  filing / workflow.acts
        ->  files on disk (instance, zip, manifest, ledger, sign-off)

Key responsibilities:
- Take each act a preparer can take on the command line — adjust, build, sign
  off, verify — as a form, and say plainly why one was refused.
- Write files only where the person said, and offer for download only the
  files a build recorded — never a path the browser names.
- Keep every refusal on the page it was made from: an override refused on the
  template grid is reported there, not on another page.

References:
- rwa_filer.cli — ``build``, ``signoff`` and ``verify``, which these mirror
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, RedirectResponse
from starlette.routing import Route

from rwa_filer.dash.filing import (
    FILE_KINDS,
    BuildOptions,
    blocked_reason,
    build_file,
    build_package,
    draft_adjustment,
    filing_page,
)
from rwa_filer.taxonomy.pack import PackNotFoundError
from rwa_filer.workflow.acts import ledger_beside, record_signoff

if TYPE_CHECKING:
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.workspace import FilingRecord, OpenedReturn

logger = logging.getLogger(__name__)

#: The accuracies the build form offers for monetary figures.
MONETARY_DECIMALS: Final = (-3, 0, 2)


# =============================================================================
# Public entry point
# =============================================================================


def routes(context: DashContext) -> list[Route]:
    """The write actions, bound to ``context``."""
    pages = FilingPages(context)
    prefix = "/returns/{return_id}"
    return [
        Route(f"{prefix}/filing", pages.filing, name="filing"),
        Route(f"{prefix}/adjustments", pages.draft, methods=["POST"], name="draft"),
        Route(f"{prefix}/adjustments/drop", pages.drop, methods=["POST"], name="drop"),
        Route(f"{prefix}/build", pages.build, methods=["POST"], name="build"),
        Route(f"{prefix}/builds/{{index:int}}/signoff", pages.signoff, methods=["POST"]),
        Route(f"{prefix}/builds/{{index:int}}/files/{{kind}}", pages.download, name="download"),
    ]


class FilingPages:
    """The handlers of the write actions."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def filing(self, request: Request) -> Response:
        """The Build & sign off page."""
        opened = self.context.opened(request)
        return self._page(
            request,
            opened,
            verify=request.query_params.get("verify") == "1",
            preview=request.query_params.get("preview") == "1",
        )

    async def draft(self, request: Request) -> Response:
        """Draft an override of one cell, from the template grid's cell panel."""
        opened = self.context.opened(request)
        form = await request.form()
        back = _local(_text(form, "next"), f"/returns/{opened.return_id}/templates")
        try:
            draft_adjustment(
                self.context.workspace,
                opened,
                cell=_cell(form),
                value=_text(form, "value"),
                remove=_text(form, "remove") == "yes",
                reason=_text(form, "reason"),
                data_type=_text(form, "data_type"),
            )
        except ValueError as exc:
            self.context.flash(opened.return_id, str(exc))
        return RedirectResponse(back, status_code=303)

    async def drop(self, request: Request) -> Response:
        """Withdraw a drafted override."""
        opened = self.context.opened(request)
        form = await request.form()
        self.context.workspace.drop_adjustment(opened.return_id, _cell(form))
        back = _local(_text(form, "next"), f"/returns/{opened.return_id}/filing")
        return RedirectResponse(back, status_code=303)

    async def build(self, request: Request) -> Response:
        """Build the filing package, as ``rwa-filer build`` would."""
        opened = self.context.opened(request)
        form = await request.form()
        try:
            options = _build_options(form)
            await run_in_threadpool(
                build_package,
                self.context.workspace,
                opened,
                options,
                at=datetime.now(UTC),
            )
        except (ValueError, PackNotFoundError, OSError) as exc:
            return self._page(request, opened, error=str(exc), status_code=400)
        return RedirectResponse(f"/returns/{opened.return_id}/filing#build", status_code=303)

    async def signoff(self, request: Request) -> Response:
        """Record an approval of a written package, bound to its checksum."""
        opened = self.context.opened(request)
        record = self._record(request, opened)
        manifest = record.package.manifest_path
        if manifest is None:
            raise HTTPException(status_code=404, detail="That build wrote no package to sign off.")
        form = await request.form()
        try:
            record_signoff(
                manifest,
                ledger=record.ledger or ledger_beside(manifest),
                approver=_text(form, "approver"),
                role=_text(form, "role"),
                at=datetime.now(UTC),
                statement=_text(form, "statement") or None,
                acknowledge_findings=_text(form, "acknowledge") == "yes",
            )
        except ValueError as exc:
            return self._page(request, opened, error=str(exc), status_code=400)
        return RedirectResponse(f"/returns/{opened.return_id}/filing#signoff", status_code=303)

    def download(self, request: Request) -> Response:
        """One file a build wrote — only ever a file the build recorded."""
        opened = self.context.opened(request)
        record = self._record(request, opened)
        kind = str(request.path_params["kind"])
        path = build_file(record, kind) if kind in FILE_KINDS else None
        if path is None:
            raise HTTPException(status_code=404, detail="That build has no such file.")
        return FileResponse(path, filename=path.name)

    # -- helpers ----------------------------------------------------------------

    def _record(self, request: Request, opened: OpenedReturn) -> FilingRecord:
        builds = self.context.workspace.builds(opened.return_id)
        index = int(request.path_params["index"])
        if not 0 <= index < len(builds):
            raise HTTPException(status_code=404, detail="No such build of this return.")
        return builds[index]

    def _page(  # noqa: PLR0913 - the page and the states it can be drawn in
        self,
        request: Request,
        opened: OpenedReturn,
        *,
        error: str | None = None,
        verify: bool = False,
        preview: bool = False,
        status_code: int = 200,
    ) -> Response:
        view = filing_page(self.context.workspace, opened, verify=verify, preview=preview)
        latest = view.latest
        return self.context.render(
            request,
            "filing.html",
            status_code=status_code,
            current=opened,
            section="filing",
            view=view,
            error=error,
            blocked=blocked_reason(latest.record) if latest else None,
            monetary_decimals=MONETARY_DECIMALS,
        )


# =============================================================================
# Private helpers
# =============================================================================


def _text(form: FormData, name: str) -> str:
    value = form.get(name)
    return value.strip() if isinstance(value, str) else ""


def _cell(form: FormData) -> tuple[str, str | None, str | None, str, str]:
    return (
        _text(form, "table"),
        _text(form, "sheet") or None,
        _text(form, "key") or None,
        _text(form, "row"),
        _text(form, "col"),
    )


def _local(target: str, fallback: str) -> str:
    """``target`` if it is an address on this dashboard, else ``fallback``."""
    return target if target.startswith("/") and not target.startswith("//") else fallback


def _build_options(form: FormData) -> BuildOptions:
    """The build form as ``BuildOptions``.

    Raises:
        ValueError: no folder was given, or an accuracy is not a whole number.
    """
    directory = _text(form, "directory")
    if not directory:
        raise ValueError("Say which folder the package should be written to.")
    try:
        monetary = int(_text(form, "monetary_decimals") or "-3")
        percentage = int(_text(form, "percentage_decimals") or "4")
    except ValueError:
        raise ValueError("The accuracies are whole numbers of decimal places.") from None
    return BuildOptions(
        directory=Path(directory).expanduser(),
        name=_text(form, "name") or None,
        monetary_decimals=monetary,
        percentage_decimals=percentage,
        declare_unreported=_text(form, "declare_unreported") == "yes",
        always_zip=_text(form, "always_zip") == "yes",
        reproducible=_text(form, "reproducible") == "yes",
        force=_text(form, "force") == "yes",
        author=_text(form, "author") or None,
    )
