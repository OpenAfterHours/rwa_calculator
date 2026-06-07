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
- Launch the Marimo edit server on demand for the editable workbench.

Runs locally; packaged via moonlit (entry point ``rwa_calc.ui.app.main:main``).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import polars as pl
import uvicorn
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rwa_calc.api.rest import get_run, register_run
from rwa_calc.api.rest import router as api_router
from rwa_calc.api.service import CreditRiskCalc, get_supported_frameworks
from rwa_calc.api.validation import validate_data_path
from rwa_calc.ui.views import charts
from rwa_calc.ui.views import comparison as comparison_view

if TYPE_CHECKING:
    from rwa_calc.api.models import CalculationResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
_APP_DIR = Path(__file__).parent
_STATIC_DIR = _APP_DIR / "static"
_TEMPLATES_DIR = _APP_DIR / "templates"
_WORKSPACES_DIR = _APP_DIR.parent / "marimo" / "workspaces"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_EDIT_PORT = 8002

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

# Lazily-launched Marimo edit server (the workbench).
_edit_process: subprocess.Popen[bytes] | None = None


# =============================================================================
# App factory
# =============================================================================


def create_app() -> FastAPI:
    """Build the read-only UI app with the REST API mounted alongside."""
    app = FastAPI(title="RWA Calculator")
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(api_router)
    _register_pages(app)
    return app


def main() -> None:
    """Start the RWA Calculator UI server (console script ``rwa-ui``)."""
    from rwa_calc.observability import configure_logging

    configure_logging("INFO", "text")
    app = create_app()
    logger.info("RWA Calculator UI: http://%s:%d", _DEFAULT_HOST, _DEFAULT_PORT)
    try:
        webbrowser.open(f"http://{_DEFAULT_HOST}:{_DEFAULT_PORT}")
    except Exception:  # pragma: no cover - browser launch is best-effort
        logger.debug("could not open browser automatically", exc_info=True)
    try:
        uvicorn.run(app, host=_DEFAULT_HOST, port=_DEFAULT_PORT)
    finally:
        _stop_workbench()


# =============================================================================
# Page routes
# =============================================================================


def _register_pages(app: FastAPI) -> None:
    """Attach the HTML page routes to *app*."""

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
        response = CreditRiskCalc(
            data_path=data_path,
            framework=framework,
            reporting_date=date.fromisoformat(reporting_date),
            permission_mode=permission_mode,
            data_format=data_format,
        ).calculate()
        run_id = register_run(response)
        return RedirectResponse(url=f"/results/{run_id}", status_code=303)

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

    @app.get("/workbench", response_class=HTMLResponse)
    def workbench(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name="workbench.html", context=_nav({"edit_port": _EDIT_PORT})
        )

    @app.post("/workbench/launch", response_class=HTMLResponse)
    def workbench_launch(request: Request) -> HTMLResponse:
        _launch_workbench()
        return templates.TemplateResponse(
            request=request,
            name="workbench_launching.html",
            context=_nav({"edit_port": _EDIT_PORT}),
        )


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
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.comparison import CapitalImpactAnalyzer, DualFrameworkRunner
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


# =============================================================================
# Private helpers
# =============================================================================


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


def _not_found(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        context=_nav({"message": message}),
        status_code=404,
    )


def _launch_workbench() -> None:
    """Start the Marimo edit server (idempotent) for the editable workbench."""
    global _edit_process  # noqa: PLW0603
    if _edit_process is not None and _edit_process.poll() is None:
        return
    _WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("launching workbench (marimo edit) on port %d", _EDIT_PORT)
    _edit_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "edit",
            "--host",
            "127.0.0.1",
            "--port",
            str(_EDIT_PORT),
            "--no-token",
            "--headless",
            str(_WORKSPACES_DIR),
        ],
        cwd=str(_WORKSPACES_DIR),
    )


def _stop_workbench() -> None:
    """Terminate the workbench edit server if it was started."""
    if _edit_process is not None:
        _edit_process.terminate()


if __name__ == "__main__":
    main()
