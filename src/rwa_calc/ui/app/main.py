"""
RWA Calculator — server-rendered read-only UI (the ``rwa-ui`` entry point).

Pipeline position:
    browser -> FastAPI (this app) -> CreditRiskCalc / ui.views -> Jinja + SVG

Key responsibilities:
- Serve the polished read-only surface (landing, calculator, results explorer,
  CRR vs Basel 3.1 comparison), styled with the shared --oah-* tokens so it
  matches the Zensical docs site.
- Mount the REST API (``rwa_calc.api.rest``) in the same process — the
  library-first contract the UI itself consumes.

Runs locally; packaged via moonlit (entry point ``rwa_calc.ui.app.main:main``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import urlencode

import polars as pl
import uvicorn
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rwa_calc.api.reconciliation import loads_reconciliation_config
from rwa_calc.api.rest import (
    get_reconciliation,
    get_run,
    register_reconciliation_with_id,
    register_run_with_id,
)
from rwa_calc.api.rest import router as api_router
from rwa_calc.api.service import CreditRiskCalc, get_supported_frameworks
from rwa_calc.api.validation import validate_data_path
from rwa_calc.ui.app.progress import (
    RECON_STAGE_NAME,
    RECON_STAGE_SEQUENCE,
    STAGE_INDEX,
    STAGE_SEQUENCE,
    Job,
    attach_progress_handler,
    create_job,
    get_job,
    submit_job,
)
from rwa_calc.ui.app.recon_state import (
    ReconciliationFormState,
    clear_last_run,
    load_last_run,
    save_last_run,
)
from rwa_calc.ui.views import charts
from rwa_calc.ui.views import comparison as comparison_view
from rwa_calc.ui.views import reconciliation as reconciliation_view

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from rwa_calc.api.models import CalculationResponse, ReconciliationResponse
    from rwa_calc.api.reconciliation import ReconciliationSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
_APP_DIR = Path(__file__).parent
_STATIC_DIR = _APP_DIR / "static"
_TEMPLATES_DIR = _APP_DIR / "templates"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000

# Cadence at which the SSE stream re-reads job state (in-memory; cheap).
_SSE_POLL_SECONDS = 0.15

# Tombstone for a stale Marimo service worker. The previous Marimo-based UI ran
# on this same port and registered a worker at ``./public-files-sw.js`` relative
# to whichever page was open; those registrations outlive the app, so the
# browser re-fetches the script on every in-scope navigation (404 noise) and
# keeps the dead worker installed. Serving this self-unregistering worker lets
# the browser's update check replace it with one that simply unregisters itself.
# We deliberately do NOT reload any tab: forcing a reload would also reload
# unrelated in-scope tabs (e.g. an old ``/results/<id>`` page from a previous
# server run, whose in-memory result is gone) and they would then 404. The
# registration finishes uninstalling when its controlled pages next navigate or
# close; until then this worker has no fetch handler, so it intercepts nothing.
# A no-op for browsers that never had the old worker.
_TOMBSTONE_SERVICE_WORKER = """\
self.addEventListener('install', function () {
  self.skipWaiting();
});
self.addEventListener('activate', function (event) {
  event.waitUntil(self.registration.unregister().catch(function () {}));
});
"""

# User-facing loopback URL. The literal "localhost" host keeps this a recognised
# loopback address (no TLS applies to a local dev server); binding still uses the
# 127.0.0.1 literal above.
_LOCAL_URL = f"http://localhost:{_DEFAULT_PORT}"

# Form-field Literal types as module-level aliases. Referenced by name in the
# route signatures so the values FastAPI validates against survive ruff's
# annotation rewriting under `from __future__ import annotations`.
FrameworkArg = Literal["CRR", "BASEL_3_1"]
PermissionArg = Literal["standardised", "irb"]
FormatArg = Literal["parquet", "csv"]

# Readable subset of the wide results frame for the on-screen table.
_RESULT_TABLE_COLS = [
    "exposure_reference",
    "exposure_class",
    "approach_applied",
    "ead_final",
    "risk_weight",
    "rwa_final",
]

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# =============================================================================
# App factory
# =============================================================================


def create_app() -> FastAPI:
    """Build the read-only UI app with the REST API mounted alongside."""
    app = FastAPI(title="RWA Calculator")
    attach_progress_handler()
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(api_router)
    _register_pages(app)
    return app


def main() -> None:
    """Start the RWA Calculator UI server (console script ``rwa-ui``)."""
    from rwa_calc.observability import configure_logging

    configure_logging("INFO", "text")
    app = create_app()
    logger.info("RWA Calculator UI: %s", _LOCAL_URL)
    try:
        webbrowser.open(_LOCAL_URL)
    except Exception:  # pragma: no cover - browser launch is best-effort
        logger.debug("could not open browser automatically", exc_info=True)
    uvicorn.run(app, host=_DEFAULT_HOST, port=_DEFAULT_PORT)


# =============================================================================
# Page routes
# =============================================================================


def _register_pages(app: FastAPI) -> None:
    """Attach the HTML page routes to *app*."""

    # Service-worker tombstones are registered FIRST so they win over the
    # "/results/{run_id}", "/calculating/{job_id}", … parameter routes. The old
    # Marimo UI registered "./public-files-sw.js" *relative to whichever page
    # was open*, so stale registrations can sit at the root scope AND under
    # nested scopes (/results/, /calculator/, …). Serving the self-unregistering
    # worker (see _TOMBSTONE_SERVICE_WORKER) at every such path lets each scope's
    # update check clean itself up instead of 404ing forever.
    @app.get("/public-files-sw.js", include_in_schema=False)
    def public_files_service_worker() -> Response:
        return _sw_tombstone_response()

    @app.get("/{sw_scope:path}/public-files-sw.js", include_in_schema=False)
    def scoped_public_files_service_worker(sw_scope: str) -> Response:
        del sw_scope  # the path only distinguishes the dead worker's scope
        return _sw_tombstone_response()

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="landing.html", context=_nav())

    @app.get("/calculator", response_class=HTMLResponse)
    def calculator(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="calculator.html",
            context=_nav(
                {
                    "frameworks": get_supported_frameworks(),
                    "default_path": _default_data_path(),
                    "default_date": "2025-01-01",
                    "error": None,
                }
            ),
        )

    @app.post("/calculate", response_class=HTMLResponse)
    def run_calculation(
        request: Request,
        data_path: Annotated[str, Form()],
        reporting_date: Annotated[str, Form()],
        framework: Annotated[FrameworkArg, Form()] = "CRR",
        permission_mode: Annotated[PermissionArg, Form()] = "standardised",
        data_format: Annotated[FormatArg, Form()] = "parquet",
    ) -> Response:
        validation = validate_data_path(data_path=data_path, data_format=data_format)
        if not validation.valid:
            missing = ", ".join(str(f) for f in validation.files_missing[:5])
            return templates.TemplateResponse(
                request=request,
                name="calculator.html",
                context=_nav(
                    {
                        "frameworks": get_supported_frameworks(),
                        "default_path": data_path,
                        "default_date": reporting_date,
                        "error": f"Data path invalid. Missing: {missing or 'see logs'}",
                    }
                ),
                status_code=400,
            )
        # Run off the request thread so the browser gets a live, stage-by-stage
        # stepper instead of a frozen tab. The job_id doubles as the eventual
        # results id (see _calculation_worker -> register_run_with_id).
        job = create_job()
        submit_job(
            job,
            _calculation_worker(
                data_path=data_path,
                framework=framework,
                reporting_date=date.fromisoformat(reporting_date),
                permission_mode=permission_mode,
                data_format=data_format,
            ),
        )
        return RedirectResponse(url=f"/calculating/{job.job_id}", status_code=303)

    @app.get("/calculating/{job_id}", response_class=HTMLResponse)
    def calculating(request: Request, job_id: str) -> HTMLResponse:
        if get_job(job_id) is None:
            return _not_found(request, "That calculation has expired or does not exist.")
        return templates.TemplateResponse(
            request=request,
            name="calculating.html",
            context=_nav({"job_id": job_id, "stages": STAGE_SEQUENCE}),
        )

    @app.get("/jobs/{job_id}")
    def job_status(job_id: str) -> JSONResponse:
        job = get_job(job_id)
        if job is None:
            return JSONResponse({"detail": f"unknown job_id: {job_id}"}, status_code=404)
        snap = job.snapshot()
        return JSONResponse(
            {
                "job_id": job_id,
                "status": snap.status,
                "success": snap.success,
                "error": snap.error,
                "completed": list(snap.completed),
                "total_stages": len(STAGE_SEQUENCE),
            }
        )

    @app.get("/jobs/{job_id}/events")
    async def job_events(request: Request, job_id: str) -> Response:
        job = get_job(job_id)
        if job is None:
            return Response(status_code=404)
        return StreamingResponse(
            _stage_event_stream(request, job),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/results/{run_id}", response_class=HTMLResponse)
    def results(request: Request, run_id: str) -> HTMLResponse:
        response = get_run(run_id)
        if response is None:
            return _not_found(request, "That result has expired or does not exist.")
        return templates.TemplateResponse(
            request=request,
            name="results.html",
            context=_nav(_results_context(run_id, response)),
        )

    @app.get("/comparison", response_class=HTMLResponse)
    def comparison_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="comparison.html",
            context=_nav(
                {
                    "default_path": _default_data_path(),
                    "default_date": "2027-06-30",
                    "error": None,
                    "result": None,
                }
            ),
        )

    @app.post("/comparison", response_class=HTMLResponse)
    def run_comparison(
        request: Request,
        data_path: Annotated[str, Form()],
        reporting_date: Annotated[str, Form()],
        permission_mode: Annotated[PermissionArg, Form()] = "standardised",
        data_format: Annotated[FormatArg, Form()] = "parquet",
    ) -> HTMLResponse:
        try:
            result = _compute_comparison(
                data_path, date.fromisoformat(reporting_date), permission_mode, data_format
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - surface any run failure to the page
            logger.warning("comparison failed: %s", exc)
            result, error = None, str(exc)
        return templates.TemplateResponse(
            request=request,
            name="comparison.html",
            context=_nav(
                {
                    "default_path": data_path,
                    "default_date": reporting_date,
                    "error": error,
                    "result": result,
                }
            ),
        )

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="reconciliation.html",
            context=_nav(_reconciliation_form_context()),
        )

    @app.post("/reconciliation", response_class=HTMLResponse)
    def run_reconciliation(
        request: Request,
        data_path: Annotated[str, Form()],
        reporting_date: Annotated[str, Form()],
        mapping_toml: Annotated[str, Form()],
        framework: Annotated[FrameworkArg, Form()] = "CRR",
        permission_mode: Annotated[PermissionArg, Form()] = "standardised",
        data_format: Annotated[FormatArg, Form()] = "parquet",
    ) -> Response:
        # Parse the mapping (and date) synchronously so a bad config re-renders
        # the form with an error before any work is dispatched.
        try:
            settings = loads_reconciliation_config(mapping_toml, base_dir=data_path or ".")
            parsed_date = date.fromisoformat(reporting_date)
        except Exception as exc:  # noqa: BLE001 - surface any parse failure to the page
            logger.warning("reconciliation config invalid: %s", exc)
            context = _reconciliation_form_context(
                default_path=data_path,
                default_date=reporting_date,
                mapping_toml=mapping_toml,
                selected_framework=framework,
                selected_permission=permission_mode,
                selected_format=data_format,
            )
            context["error"] = str(exc)
            return templates.TemplateResponse(
                request=request, name="reconciliation.html", context=_nav(context), status_code=400
            )
        # Run the reconciliation (a full pipeline run + the legacy join) off the
        # request thread so the browser gets the live stage stepper instead of a
        # frozen tab. The job_id doubles as the recon result id (see
        # _reconciliation_worker -> register_reconciliation_with_id).
        job = create_job()
        submit_job(
            job,
            _reconciliation_worker(
                settings=settings,
                data_path=data_path,
                framework=framework,
                reporting_date=parsed_date,
                permission_mode=permission_mode,
                data_format=data_format,
                form_state=ReconciliationFormState(
                    data_path=data_path,
                    reporting_date=reporting_date,
                    framework=framework,
                    permission_mode=permission_mode,
                    data_format=data_format,
                    mapping_toml=mapping_toml,
                ),
            ),
        )
        return RedirectResponse(url=f"/reconciling/{job.job_id}", status_code=303)

    @app.get("/reconciling/{job_id}", response_class=HTMLResponse)
    def reconciling(request: Request, job_id: str) -> HTMLResponse:
        if get_job(job_id) is None:
            return _not_found(request, "That reconciliation has expired or does not exist.")
        return templates.TemplateResponse(
            request=request,
            name="reconciling.html",
            context=_nav({"job_id": job_id, "stages": RECON_STAGE_SEQUENCE}),
        )

    @app.get("/reconciliation/reset")
    def reconciliation_reset() -> Response:
        # Registered before "/reconciliation/{recon_id}" so the literal path wins.
        clear_last_run()
        return RedirectResponse(url="/reconciliation", status_code=303)

    @app.get("/reconciliation/{recon_id}", response_class=HTMLResponse)
    def reconciliation_result(request: Request, recon_id: str) -> HTMLResponse:
        response = get_reconciliation(recon_id)
        if response is None:
            return _not_found(request, "That reconciliation has expired or does not exist.")
        context = _reconciliation_form_context()
        context["result"] = _reconciliation_result(recon_id, response)
        return templates.TemplateResponse(
            request=request, name="reconciliation.html", context=_nav(context)
        )

    @app.get("/reconciliation/{recon_id}/rows", response_class=HTMLResponse)
    def reconciliation_rows(
        request: Request,
        recon_id: str,
        bucket: str = "",
        exposure_class: str = "",
        approach: str = "",
        worst_component: str = "",
        q: str = "",
        sort: str = "",
        sort_dir: str = "desc",
        page: int = 1,
        page_size: int = reconciliation_view.DEFAULT_PAGE_SIZE,
    ) -> HTMLResponse:
        response = get_reconciliation(recon_id)
        if response is None or not response.success:
            return _not_found(request, "That reconciliation has expired or does not exist.")
        filters = reconciliation_view.ForensicFilters(
            bucket=bucket or None,
            exposure_class=exposure_class or None,
            approach=approach or None,
            worst_component=worst_component or None,
            query=q or None,
            sort=sort or None,
            descending=(sort_dir != "asc"),
            page=page,
            page_size=page_size,
        )
        try:
            result_page = reconciliation_view.forensic_page(response, filters)
        except ValueError as exc:
            return _bad_request(request, str(exc))
        return templates.TemplateResponse(
            request=request,
            name="recon_explorer.html",
            context=_nav(_reconciliation_explorer(recon_id, response, filters, result_page)),
        )

    @app.get("/reconciliation/{recon_id}/loan", response_class=HTMLResponse)
    def reconciliation_loan(request: Request, recon_id: str, key: str = "") -> HTMLResponse:
        response = get_reconciliation(recon_id)
        if response is None or not response.success:
            return _not_found(request, "That reconciliation has expired or does not exist.")
        # ``key`` defaults to "" so an omitted ?key= reaches the handler and gets
        # the styled 404 below (loan_detail returns None for an empty/unknown key)
        # rather than FastAPI's raw 422 for a missing required query param.
        detail = reconciliation_view.loan_detail(response, key) if key else None
        if detail is None:
            return _not_found(request, "No reconciliation row matches that key.")
        return templates.TemplateResponse(
            request=request,
            name="recon_loan.html",
            context=_nav(_reconciliation_loan(recon_id, response, detail)),
        )


# =============================================================================
# Background calculation jobs (the live-progress stepper backend)
# =============================================================================


def _calculation_worker(
    *,
    data_path: str,
    framework: FrameworkArg,
    reporting_date: date,
    permission_mode: PermissionArg,
    data_format: FormatArg,
) -> Callable[[Job], None]:
    """Build the background worker that runs one calculation for a job.

    Runs on the progress executor, off the request thread. The job_id is reused
    as the results id, so the ``/calculating/{id}`` progress URL and the
    ``/results/{id}`` page share one identifier. ``CreditRiskCalc.calculate``
    captures its own failures as ``success=False``, so an error result is still
    registered and rendered; ``submit_job`` only catches a truly unexpected
    crash (-> ``job.fail``).
    """

    def _work(job: Job) -> None:
        response = CreditRiskCalc(
            data_path=data_path,
            framework=framework,
            reporting_date=reporting_date,
            permission_mode=permission_mode,
            data_format=data_format,
        ).calculate()
        register_run_with_id(job.job_id, response)
        job.finish(success=response.success)

    return _work


def _reconciliation_worker(
    *,
    settings: ReconciliationSettings,
    data_path: str,
    framework: FrameworkArg,
    reporting_date: date,
    permission_mode: PermissionArg,
    data_format: FormatArg,
    form_state: ReconciliationFormState,
) -> Callable[[Job], None]:
    """Build the background worker that runs one reconciliation for a job.

    Mirrors ``_calculation_worker``: runs on the progress executor, off the
    request thread, and the job_id is reused as the recon result id (so
    ``/reconciling/{id}`` and ``/reconciliation/{id}`` share one identifier). The
    embedded ``calculate()`` streams every engine stage to the progress tap for
    free; the worker then *warms* the lazy bundle frames so the heavy full-outer
    join runs here — under the stepper — instead of freezing the result page on
    its first collect, and marks the ``recon_reconcile`` tail step done.
    """

    def _work(job: Job) -> None:
        response = CreditRiskCalc(
            data_path=data_path,
            framework=framework,
            reporting_date=reporting_date,
            permission_mode=permission_mode,
            data_format=data_format,
        ).reconcile(settings)
        _warm_reconciliation_frames(response)
        job.mark_stage(RECON_STAGE_NAME)
        register_reconciliation_with_id(job.job_id, response)
        save_last_run(form_state)
        job.finish(success=response.success)

    return _work


def _warm_reconciliation_frames(response: ReconciliationResponse) -> None:
    """Force the lazy reconcile join to execute, caching every result frame.

    The ``ReconciliationBundle`` is lazy; its full-outer join + bucketing fires on
    the first ``collect_*`` call (``api/models.py``). Warming the cache on the
    worker thread keeps that heavy compute under the progress stepper and makes
    the subsequent overview render hit the cache instead of freezing.

    The small summary frames and the ranked break worklist are warmed (they back
    the aggregates-first overview); the wide ``component_reconciliation`` frame is
    deliberately left lazy — the overview never touches it, and it is collected
    on the first explorer/loan drill so a large portfolio is never materialised
    just to show the summary page.
    """
    response.collect_totals_tie_out()
    response.collect_summary_by_component()
    response.collect_summary_by_bucket()
    response.collect_summary_by_exposure_class()
    response.collect_summary_by_approach()
    response.collect_class_allocation()
    response.collect_breaks_detail()


async def _stage_event_stream(request: Request, job: Job) -> AsyncIterator[str]:
    """Stream Server-Sent Events as pipeline stages complete, then a terminal.

    Driven off completed-stage *order* (never a synthesised percentage): the
    client ticks each stage off a fixed checklist and the spinner honestly
    parks on the heavy ``calculators`` collect. Replays every stage completed so
    far on each (re)connection, so EventSource auto-reconnect stays idempotent.
    """
    sent = 0
    yield ": connected\n\n"
    while True:
        if await request.is_disconnected():
            return
        snap = job.snapshot()
        while sent < len(snap.completed):
            name = snap.completed[sent]
            yield _sse("stage", {"name": name, "index": STAGE_INDEX.get(name, -1)})
            sent += 1
        if snap.status == "done":
            yield _sse("done", {"run_id": job.job_id, "success": snap.success})
            return
        if snap.status == "error":
            yield _sse("failed", {"error": snap.error or "Calculation failed."})
            return
        await asyncio.sleep(_SSE_POLL_SECONDS)


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame (``event:`` name + JSON ``data:``)."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# =============================================================================
# View-context builders
# =============================================================================


def _results_context(run_id: str, response: CalculationResponse) -> dict:
    """Build the template context for the results page."""
    rwa_by_class, ead_by_class = _class_chart_items(response)
    approach_split = _approach_chart_items(response)
    return {
        "run_id": run_id,
        "success": response.success,
        "framework": response.framework,
        "summary": response.summary,
        "errors": response.errors,
        "chart_rwa_by_class": charts.horizontal_bar_svg(rwa_by_class),
        "chart_ead_by_class": charts.horizontal_bar_svg(ead_by_class),
        "chart_approach": charts.horizontal_bar_svg(approach_split),
        "table_columns": _RESULT_TABLE_COLS,
        "table_rows": _result_rows(response),
    }


def _compute_comparison(
    data_path: str, reporting_date: date, permission_mode: str, data_format: str
) -> dict:
    """Run both frameworks and build the comparison template context."""
    from rwa_calc.analysis.comparison import CapitalImpactAnalyzer, DualFrameworkRunner
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.loader import CSVLoader, ParquetLoader

    base = Path(data_path)
    loader = CSVLoader(base_path=base) if data_format == "csv" else ParquetLoader(base_path=base)
    raw = loader.load()
    mode = PermissionMode(permission_mode)
    crr_cfg = CalculationConfig.crr(reporting_date=reporting_date, permission_mode=mode)
    b31_cfg = CalculationConfig.basel_3_1(reporting_date=reporting_date, permission_mode=mode)

    bundle = DualFrameworkRunner().compare(raw, crr_cfg, b31_cfg)
    impact = CapitalImpactAnalyzer().analyze(bundle)

    summary = comparison_view.executive_summary(bundle)
    steps = comparison_view.waterfall_steps(impact)
    by_class = comparison_view.summary_by_class(bundle)
    grouped = [
        (row["exposure_class"], row.get("total_rwa_crr", 0.0), row.get("total_rwa_b31", 0.0))
        for row in by_class.to_dicts()
        if "exposure_class" in row
    ]
    return {
        "summary": summary,
        "chart_waterfall": charts.waterfall_svg(steps),
        "chart_by_class": charts.grouped_bar_svg(grouped),
        "class_columns": by_class.columns,
        "class_rows": by_class.to_dicts(),
    }


def _reconciliation_form_context(
    *,
    default_path: str | None = None,
    default_date: str | None = None,
    mapping_toml: str | None = None,
    selected_framework: str | None = None,
    selected_permission: str | None = None,
    selected_format: str | None = None,
) -> dict:
    """Base template context for the reconciliation page (form fields + no result).

    Each field resolves with the precedence: explicit override (a failure
    re-render) > the last completed run > the built-in default. The three
    ``selected_*`` keys drive the ``<select>`` pre-selection in the template.
    """
    saved = load_last_run()

    def _pick(override: str | None, saved_value: str | None, fallback: str) -> str:
        if override is not None:
            return override
        if saved_value is not None:
            return saved_value
        return fallback

    return {
        "frameworks": get_supported_frameworks(),
        "default_path": _pick(
            default_path, saved.data_path if saved else None, _default_data_path()
        ),
        "default_date": _pick(default_date, saved.reporting_date if saved else None, "2025-01-01"),
        "mapping_toml": _pick(
            mapping_toml,
            saved.mapping_toml if saved else None,
            reconciliation_view.DEFAULT_MAPPING_TOML,
        ),
        "selected_framework": _pick(selected_framework, saved.framework if saved else None, "CRR"),
        "selected_permission": _pick(
            selected_permission, saved.permission_mode if saved else None, "standardised"
        ),
        "selected_format": _pick(selected_format, saved.data_format if saved else None, "parquet"),
        "has_saved_run": saved is not None,
        "error": None,
        "result": None,
    }


def _reconciliation_result(recon_id: str, response: ReconciliationResponse) -> dict:
    """Build the aggregates-first overview context for a registered reconciliation.

    The overview renders only the small pre-aggregated frames (headline tie-out,
    per-component summary, the segment tables) plus a ranked "biggest breaks"
    top-N — it never collects the wide per-key frame, so it renders in constant
    time and constant DOM for any portfolio size. The full row-level diff is
    reached by drilling into the explorer (``/rows``) and a single loan
    (``/loan``); the segment rows carry the filter that pre-narrows the explorer.
    """
    warnings = [f"[{e.code}] {e.message}" for e in response.errors]
    if not response.success:
        return {"recon_id": recon_id, "success": False, "warnings": warnings}

    segments = reconciliation_view.segment_tables(response)
    by_bucket = segments["by_bucket"]
    total_rows = (
        int(by_bucket.get_column("count").sum() or 0) if "count" in by_bucket.columns else 0
    )
    return {
        "recon_id": recon_id,
        "success": True,
        "warnings": warnings,
        "has_breaks": response.has_breaks,
        # Tier 1 — headline
        "headline": reconciliation_view.headline_stats(response),
        "chart_abs_delta": charts.horizontal_bar_svg(
            reconciliation_view.abs_delta_chart_items(response)
        ),
        "chart_tie_out": charts.grouped_bar_svg(
            reconciliation_view.tie_out_chart_items(response), series=("Legacy", "Ours")
        ),
        "component_table": _table(reconciliation_view.summary_by_component_table(response)),
        # Tier 2 — segment (each row drills into the explorer, pre-filtered)
        "bucket_table": _table(by_bucket),
        "allocation_table": _table(reconciliation_view.class_allocation_table(response)),
        "chart_allocation": charts.grouped_bar_svg(
            reconciliation_view.class_allocation_chart_items(response), series=("Legacy", "Ours")
        ),
        "class_table": _table(segments["by_class"]),
        "approach_table": _table(segments["by_approach"]),
        # Tier 3 — ranked worklist (top-N; the full diff lives in the explorer)
        "biggest_breaks": _table(reconciliation_view.biggest_breaks(response)),
        "biggest_n": reconciliation_view.BIGGEST_BREAKS_LIMIT,
        "break_count": response.collect_breaks_detail().height,
        "total_rows": total_rows,
        # Navigation
        "explorer_url": f"/reconciliation/{recon_id}/rows",
        "loan_url_base": f"/reconciliation/{recon_id}/loan",
        "export_csv_url": f"/api/reconcile/export/csv?recon_id={recon_id}",
        "export_excel_url": f"/api/reconcile/export/excel?recon_id={recon_id}",
    }


def _reconciliation_explorer(
    recon_id: str,
    response: ReconciliationResponse,
    filters: reconciliation_view.ForensicFilters,
    page: reconciliation_view.ForensicPage,
) -> dict:
    """Build the per-key explorer context (one filtered/sorted/paged window).

    ``query_base`` is the active filter set (sans sort/page) pre-encoded, so the
    template's sortable-header and prev/next links preserve the filters without
    re-assembling the query string by hand.
    """
    by_bucket = response.collect_summary_by_bucket()
    grand_total = (
        int(by_bucket.get_column("count").sum() or 0) if "count" in by_bucket.columns else 0
    )
    base_params = {
        "bucket": filters.bucket,
        "exposure_class": filters.exposure_class,
        "approach": filters.approach,
        "worst_component": filters.worst_component,
        "q": filters.query,
        "page_size": page.page_size,
    }
    query_base = urlencode({k: v for k, v in base_params.items() if v})
    return {
        "recon_id": recon_id,
        "framework": response.framework,
        "columns": page.columns,
        "rows": page.rows,
        "total": page.total,
        "grand_total": grand_total,
        "page": page.page,
        "pages": page.pages,
        "page_size": page.page_size,
        "max_page_size": reconciliation_view.MAX_PAGE_SIZE,
        "first_row": page.offset + 1 if page.rows else 0,
        "last_row": page.offset + len(page.rows),
        "sort": page.sort,
        "sort_dir": "desc" if page.descending else "asc",
        "filters": {
            "bucket": filters.bucket or "",
            "exposure_class": filters.exposure_class or "",
            "approach": filters.approach or "",
            "worst_component": filters.worst_component or "",
            "q": filters.query or "",
        },
        "options": reconciliation_view.forensic_filter_options(response),
        "key_column": "_recon_key",
        "explorer_path": f"/reconciliation/{recon_id}/rows",
        "query_base": query_base,
        "loan_url_base": f"/reconciliation/{recon_id}/loan",
        "report_url": f"/reconciliation/{recon_id}",
        "export_csv_url": f"/api/reconcile/export/csv?recon_id={recon_id}",
        "export_excel_url": f"/api/reconcile/export/excel?recon_id={recon_id}",
    }


def _reconciliation_loan(recon_id: str, response: ReconciliationResponse, detail: dict) -> dict:
    """Build the single-loan forensic context."""
    return {
        "recon_id": recon_id,
        "framework": response.framework,
        "detail": detail,
        "report_url": f"/reconciliation/{recon_id}",
        "explorer_url": f"/reconciliation/{recon_id}/rows",
    }


# =============================================================================
# Private helpers
# =============================================================================


def _table(df: pl.DataFrame) -> dict:
    """Convert a DataFrame to a template-friendly ``{columns, rows}`` table."""
    clean = df.fill_nan(None)
    return {"columns": clean.columns, "rows": clean.to_dicts()}


def _class_chart_items(
    response: CalculationResponse,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """(rwa_by_class, ead_by_class) item lists from the class summary."""
    lf = response.scan_summary_by_class()
    if lf is None:
        return [], []
    df = lf.collect()
    rwa = _items(df, "exposure_class", "total_rwa")
    ead = _items(df, "exposure_class", "total_ead")
    return rwa, ead


def _approach_chart_items(response: CalculationResponse) -> list[tuple[str, float]]:
    """RWA-by-approach item list from the approach summary."""
    lf = response.scan_summary_by_approach()
    if lf is None:
        return []
    return _items(lf.collect(), "approach_applied", "total_rwa")


def _items(df: pl.DataFrame, label_col: str, value_col: str) -> list[tuple[str, float]]:
    """Build (label, value) tuples from two columns, tolerating absence."""
    if label_col not in df.columns or value_col not in df.columns:
        return []
    return [
        (str(row[label_col]), float(row[value_col] or 0.0))
        for row in df.sort(value_col, descending=True).to_dicts()
    ]


def _result_rows(response: CalculationResponse) -> list[dict]:
    """A small, display-ready sample of the exposure-level results."""
    lf = response.scan_results()
    available = [c for c in _RESULT_TABLE_COLS if c in lf.collect_schema().names()]
    if not available:
        return []
    df: pl.DataFrame = lf.select(available).head(100).collect().fill_nan(None)
    return df.to_dicts()


def _default_data_path() -> str:
    """Repo fixtures path when present (dev), else empty (installed)."""
    candidate = _APP_DIR.parents[3] / "tests" / "fixtures"
    return str(candidate) if candidate.exists() else ""


def _nav(extra: dict | None = None) -> dict:
    """Common template context (active nav handled in the template)."""
    context: dict = {"docs_url": "https://openafterhours.github.io/rwa_calculator/"}
    if extra:
        context.update(extra)
    return context


def _sw_tombstone_response() -> Response:
    """Serve the self-unregistering service-worker tombstone (see the constant)."""
    return Response(
        content=_TOMBSTONE_SERVICE_WORKER,
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def _not_found(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        context=_nav({"message": message}),
        status_code=404,
    )


def _bad_request(request: Request, message: str) -> HTMLResponse:
    """Render the lightweight error page with a 400 (e.g. an invalid sort column)."""
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        context=_nav({"message": message}),
        status_code=400,
    )


if __name__ == "__main__":
    main()
