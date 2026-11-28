"""
The read-only pages: open a return, its overview, its rules, its templates.

Pipeline position:
    browser  ->  these routes  ->  Workspace / dash.views / dash.grid
        ->  DashContext.render  ->  HTML

Key responsibilities:
- Open a return from an uploaded file or a path on this machine, with the
  header a fact table needs, and say plainly why one could not be opened.
  The reading and validating run as a dashboard task (``dash.tasks``): a
  return that takes more than a moment shows its progress meanwhile.
- Draw the overview, the rules and the template viewer for an opened return as
  a build would file it now: with the overrides drafted for it applied, and
  validated again once per change of them (``Workspace.working``).
- Keep tab selections in the address and share this browser's review settings
  across the pages of the open return.
- Hand over the evidence behind an opened return's verdict as the file
  ``rwa-filer validate --evidence`` writes.
- For a return opened with breakdown columns, split the picked cell by one of
  them, and set each member's figures beside the return's for the broken
  rules that read it (``dash.breakdown``).

References:
- rwa_filer.cli — ``rwa-filer validate``, which these pages show the result of
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from polars.exceptions import PolarsError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.breakdown import (
    breakdown_summary,
    cell_breakdown,
    pick_dimension,
)
from rwa_filer.dash.context import (
    REVIEW_KEYS,
    SECTIONS,
    THEME_COOKIE,
    THEMES,
    read_review,
    review_of,
    review_query,
    save_review,
)
from rwa_filer.dash.forms import form_values, page_number, read_open_form
from rwa_filer.dash.grid import template_grid
from rwa_filer.dash.rule_exports import FailureReport, markdown, matched_traces, workbook
from rwa_filer.dash.security import served_securely
from rwa_filer.dash.task_pages import follow
from rwa_filer.dash.views import failed_rule_details, overview, rules_page
from rwa_filer.progress import PHASE_READING, PHASE_RULES, PHASE_STRUCTURE
from rwa_filer.readers.detail import breakdown_options
from rwa_filer.release import release_packs, shipped_releases
from rwa_filer.validate.review import SHOW_ALL, ReviewFilter

if TYPE_CHECKING:
    from starlette.requests import Request

    from rwa_filer.dash.breakdown import CellBreakdown
    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.grid import TemplateGrid
    from rwa_filer.dash.workspace import WorkingReturn
    from rwa_filer.progress import ProgressCallback
    from rwa_filer.workflow.attribution import Attribution

logger = logging.getLogger(__name__)

#: The steps of opening a return: read the file, then validate it.
OPENING_PHASES: Final = (PHASE_READING, PHASE_STRUCTURE, PHASE_RULES)


# =============================================================================
# Public entry point
# =============================================================================


def routes(context: DashContext) -> list[Route]:
    """The read-only pages, bound to ``context``."""
    pages = ReturnPages(context)
    return [
        Route("/", pages.home, name="home"),
        Route("/open", pages.open_return, methods=["POST"], name="open"),
        Route("/open/breakdown-options", pages.breakdown_options, methods=["POST"]),
        Route("/returns/{return_id}", pages.overview, name="overview"),
        Route("/returns/{return_id}/rules", pages.rules, name="rules"),
        Route("/returns/{return_id}/rules/export", pages.export_failures, name="export_failures"),
        Route("/returns/{return_id}/review", pages.set_review, methods=["POST"], name="review"),
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

    async def breakdown_options(self, request: Request) -> Response:
        """Offer the actual reporting columns and group codes before validation."""
        async with request.form() as form:
            upload = form.get("file")
            path = Path(str(form.get("path") or "")).expanduser()
            column = str(form.get("breakdown") or "")
            if isinstance(upload, UploadFile) and upload.filename:
                source, suffix = upload.file, Path(upload.filename).suffix
            else:
                source, suffix = path, path.suffix
            try:
                options = await run_in_threadpool(breakdown_options, source, suffix.lower(), column)
            except (OSError, ValueError, PolarsError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(options)

    async def open_return(self, request: Request) -> Response:
        """Open the uploaded file, or the file at the given path, and show its overview.

        What the form itself gets wrong is refused at once; the reading and the
        validation run as a task, whose progress is shown if it takes a while.
        """
        form = await request.form()
        values = form_values(form)
        try:
            asked = await read_open_form(self.context.workspace, form)
        except ValueError as exc:
            return self._home(request, error=str(exc), values=values, status_code=400)
        workspace = self.context.workspace

        def work(progress: ProgressCallback) -> str:
            return f"/returns/{asked.open(workspace, progress).return_id}"

        def refused(request: Request, error: str, status_code: int) -> Response:
            return self._home(request, error=error, values=values, status_code=status_code)

        task = self.context.tasks.start(
            f"Validating {asked.name}", work, phases=OPENING_PHASES, refused=refused
        )
        return await follow(self.context, request, task)

    async def switch_taxonomy(self, request: Request) -> Response:
        """Open the return again against the release the form names, and show it."""
        opened = self.context.opened(request)
        form = await request.form()
        version = str(form.get("taxonomy") or "").strip()
        if not version or version == opened.release.version:
            return RedirectResponse(f"/returns/{opened.return_id}", status_code=303)
        workspace = self.context.workspace

        def work(progress: ProgressCallback) -> str:
            return f"/returns/{workspace.reopen(opened, version, progress=progress).return_id}"

        def refused(request: Request, error: str, status_code: int) -> Response:
            return self.context.render(
                request,
                "error.html",
                status_code=status_code,
                title="The return could not be opened against that release",
                message=error,
            )

        task = self.context.tasks.start(
            f"Validating {opened.name} against taxonomy {version}",
            work,
            phases=OPENING_PHASES,
            refused=refused,
        )
        return await follow(self.context, request, task)

    def overview(self, request: Request) -> Response:
        """Whether the return is fit to file, and the counts behind the answer."""
        working = self.context.working(request)
        detail = working.opened.detail
        return self.context.render(
            request,
            "overview.html",
            working=working,
            section="overview",
            view=overview(working.current, review=review_of(request)),
            breakdown=breakdown_summary(detail) if detail is not None else None,
        )

    def rules(self, request: Request) -> Response:
        """The rules, filtered as the address says, with one picked in full."""
        working = self.context.working(request)
        query = request.query_params
        legacy = any(key in query for key in REVIEW_KEYS)
        try:
            review = read_review(query) if legacy else review_of(request)
        except ValueError as exc:
            return self.context.render(
                request,
                "error.html",
                working=working,
                status_code=400,
                title="Invalid review filter",
                message=str(exc),
            )
        view = rules_page(
            working.current,
            status=query.get("status", STATUS_FAIL),
            severity=query.get("severity", ""),
            query=query.get("q", ""),
            template=query.get("template", ""),
            review=review,
            rule_id=query.get("rule", ""),
            page=page_number(query.get("page")),
        )
        detail = working.opened.detail
        dimensions = detail.dimensions if detail else ()
        by = query.get("by", "")
        dimension = by if by in dimensions else ""
        selected = (view.selected,) if view.selected and view.selected.failures else ()
        attribution = self._rule_attribution(
            working, dimension, tuple(r.row.rule_id for r in selected), review
        )
        response = self.context.render(
            request,
            "rules.html",
            working=working,
            section="rules",
            view=view,
            review=review,
            dimension=dimension,
            dimensions=dimensions,
            attribution=attribution,
            traces=matched_traces(selected, attribution),
        )
        if legacy:
            save_review(request, response, working.opened.return_id, review)
        return response

    def export_failures(self, request: Request) -> Response:
        """Preview or download every visible occurrence from the working return."""
        working = self.context.working(request)
        current = working.current
        params = request.query_params
        try:
            review = (
                read_review(params)
                if any(key in params for key in REVIEW_KEYS)
                else review_of(request)
            )
        except ValueError as exc:
            return self.context.render(
                request,
                "error.html",
                working=working,
                status_code=400,
                title="Invalid review filter",
                message=str(exc),
            )
        severity = "" if review.errors_only else params.get("severity", "")
        template, query = params.get("template", ""), params.get("q", "")
        dimension, download = params.get("by", ""), params.get("download", "")
        detail = working.opened.detail
        dimensions = detail.dimensions if detail else ()
        if download not in ("", "md", "xlsx") or (dimension and dimension not in dimensions):
            return self.context.render(
                request,
                "error.html",
                working=working,
                status_code=400,
                title="Invalid export option",
                message="Choose an available format and reporting column.",
            )
        rules = failed_rule_details(
            current, severity=severity, template=template, query=query, review=review
        )
        header = current.ret.header
        summary = {
            "Return": current.name,
            "Entity": header.entity_identifier,
            "Reference date": str(header.reference_date),
            "Module": header.module,
            "Taxonomy release": current.release.version,
            "Figures": "With drafted overrides" if working.adjusted else "As opened",
            "Status": "Failed",
            "Severity": "ERROR" if review.errors_only else severity or "All",
            "Template": template or "All",
            "Search": query or "All",
            "Warning threshold (money)": f"{review.money} {header.currency}"
            if review.money is not None
            else "None",
            "Warning threshold (bp)": str(review.basis_points)
            if review.basis_points is not None
            else "None",
            "Hide zero-only null checks": "Yes" if review.hide_zero_null else "No",
            "Reporting-unit breakdown": dimension or "Omitted",
        }
        # A preview traces only its sample rule. Downloads use every matching rule.
        ids = tuple(rule.row.rule_id for rule in (rules if download else rules[:1]))
        attribution = self._rule_attribution(working, dimension, ids, review)
        report = FailureReport(summary, rules, dimension, attribution)
        if not download:
            first = rules[0] if rules else None
            trace = (
                matched_traces(rules[:1], attribution).get((first.row.rule_id, 1))
                if first
                else None
            )
            return self.context.render(
                request,
                "rule_export.html",
                section="rules",
                working=working,
                review=review,
                report=report,
                dimensions=dimensions,
                sample=first,
                trace=trace,
                severity=severity,
                template=template,
                query=query,
            )
        if download == "md":
            body, media = markdown(report).encode(), "text/markdown"
        else:
            try:
                body = workbook(report)
            except ValueError as exc:
                return self.context.render(
                    request,
                    "error.html",
                    working=working,
                    status_code=400,
                    title="Workbook could not be exported",
                    message=str(exc),
                )
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"failed-rules-{header.reference_date}.{download}"
        return Response(
            body,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    async def set_review(self, request: Request) -> Response:
        """Save the browser's review settings and return to the same tab and selection."""
        opened = self.context.opened(request)
        form = await request.form()
        try:
            review = (
                SHOW_ALL
                if form.get("reset") == "1"
                else ReviewFilter.from_text(
                    str(form.get("money", "")),
                    str(form.get("bps", "")),
                    form.get("hide_zero") == "1",
                    errors_only=form.get("errors_only") == "1",
                )
            )
        except ValueError as exc:
            return self.context.render(
                request,
                "error.html",
                working=self.context.workspace.working(opened),
                status_code=400,
                title="Invalid review filter",
                message=str(exc),
            )
        suffix = next((s.suffix for s in SECTIONS if s.key == form.get("section")), "/rules")
        query = review_query(str(form.get("query", "")))
        destination = f"/returns/{opened.return_id}{suffix}"
        response = RedirectResponse(
            f"{destination}?{query}" if query else destination, status_code=303
        )
        save_review(request, response, opened.return_id, review)
        return response

    def evidence(self, request: Request) -> Response:
        """The evidence behind the verdict the pages show, as the file ``--evidence`` writes.

        That is the return with its drafted overrides applied, as every page of
        it is drawn — so the evidence answers for what a build would file now.
        Collected the first time it is asked for, at the accuracy the overview's
        verdict was reached at, and written inside the session's workspace once
        per validation (``Workspace.evidence``): a later download, or one asked
        for while it is collected, is handed the same file.
        """
        current = self.context.working(request).current
        written = self.context.workspace.evidence(current)
        name = f"{current.path.stem}.evidence.jsonl"
        return FileResponse(written, filename=name, media_type="application/x-ndjson")

    def templates(self, request: Request) -> Response:
        """One table of the return on its grid, with the broken rules' cells marked."""
        working = self.context.working(request)
        query = request.query_params
        review = review_of(request)
        grid = template_grid(
            working,
            review=review,
            table=query.get("table", ""),
            sheet=query.get("sheet", ""),
            key=query.get("key", ""),
            row=query.get("row", ""),
            column=query.get("col", ""),
            focus=query.get("focus", ""),
        )
        detail = working.opened.detail
        by = pick_dimension(detail, query.get("by", "")) if detail and detail.dimensions else ""
        try:
            breakdown = self._cell_breakdown(working, grid, by, review)
        except Exception:  # Keep the validated grid available if the unit calculation fails.
            logger.exception("cell breakdown failed for %s by %s", working.opened.return_id, by)
            breakdown = None
            breakdown_failed = True
        else:
            breakdown_failed = False
        return self.context.render(
            request,
            "templates.html",
            working=working,
            section="templates",
            grid=grid,
            by=by,
            breakdown=breakdown,
            breakdown_failed=breakdown_failed,
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

    def _rule_attribution(
        self, working: WorkingReturn, dimension: str, ids: tuple[str, ...], review: ReviewFilter
    ) -> Attribution | None:
        if not dimension or not ids:
            return None
        try:
            result = self.context.workspace.attribution(working, dimension, rule_ids=ids)
            return result.reviewed(working.current.validation, review)
        except Exception:
            logger.exception(
                "Rule breakdown failed for %s by %s", working.opened.return_id, dimension
            )
            return None

    def _cell_breakdown(
        self,
        working: WorkingReturn,
        grid: TemplateGrid | None,
        dimension: str,
        review: ReviewFilter,
    ) -> CellBreakdown | None:
        """The picked cell split by ``dimension``, with its broken rules member by member.

        Shares indexed inputs and finished rules with other cells and Investigate.
        """
        if grid is None or grid.cell is None or not dimension:
            return None
        cell = (grid.table, grid.page.sheet, grid.page.open_key, grid.cell.row, grid.cell.column)
        rule_ids = tuple(mark.rule_id for mark in grid.cell.marks)
        attribution = None
        if rule_ids:
            attribution = self.context.workspace.attribution(working, dimension, rule_ids=rule_ids)
            attribution = attribution.reviewed(working.current.validation, review)
        return cell_breakdown(working, cell, dimension, rule_ids, attribution)

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
