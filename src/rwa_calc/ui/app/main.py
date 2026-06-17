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

from rwa_calc.api.reconciliation import loads_reconciliation_config
from rwa_calc.api.rest import get_reconciliation, get_run, register_reconciliation, register_run
from rwa_calc.api.rest import router as api_router
from rwa_calc.api.service import CreditRiskCalc, get_supported_frameworks
from rwa_calc.api.validation import validate_data_path
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
    from rwa_calc.api.models import CalculationResponse, ReconciliationResponse

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
    logger.info("RWA Calculator UI: %s", _LOCAL_URL)
    try:
        webbrowser.open(_LOCAL_URL)
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
        try:
            settings = loads_reconciliation_config(mapping_toml, base_dir=data_path or ".")
            response = CreditRiskCalc(
                data_path=data_path,
                framework=framework,
                reporting_date=date.fromisoformat(reporting_date),
                permission_mode=permission_mode,
                data_format=data_format,
            ).reconcile(settings)
        except Exception as exc:  # noqa: BLE001 - surface any parse/run failure to the page
            logger.warning("reconciliation failed: %s", exc)
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
        recon_id = register_reconciliation(response)
        save_last_run(
            ReconciliationFormState(
                data_path=data_path,
                reporting_date=reporting_date,
                framework=framework,
                permission_mode=permission_mode,
                data_format=data_format,
                mapping_toml=mapping_toml,
            )
        )
        return RedirectResponse(url=f"/reconciliation/{recon_id}", status_code=303)

    @app.get("/reconciliation/reset")
    def reconciliation_reset() -> Response:
        # Registered before "/reconciliation/{recon_id}" so the literal path wins.
        clear_last_run()
        return RedirectResponse(url="/reconciliation", status_code=303)

    @app.get("/reconciliation/{recon_id}", response_class=HTMLResponse)
    def reconciliation_result(
        request: Request, recon_id: str, bucket: str = "break"
    ) -> HTMLResponse:
        response = get_reconciliation(recon_id)
        if response is None:
            return _not_found(request, "That reconciliation has expired or does not exist.")
        context = _reconciliation_form_context()
        context["result"] = _reconciliation_result(recon_id, response, bucket)
        return templates.TemplateResponse(
            request=request, name="reconciliation.html", context=_nav(context)
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


def _reconciliation_result(recon_id: str, response: ReconciliationResponse, bucket: str) -> dict:
    """Build the four-tier result context for a registered reconciliation."""
    warnings = [f"[{e.code}] {e.message}" for e in response.errors]
    if not response.success:
        return {"recon_id": recon_id, "success": False, "warnings": warnings}

    if bucket not in reconciliation_view.BUCKET_CHOICES:
        bucket = "break"
    segments = reconciliation_view.segment_tables(response)
    breaks = reconciliation_view.breaks_table(response)
    f_cols, f_rows, f_total = reconciliation_view.forensic_table(response, bucket)
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
        # Tier 2 — segment
        "bucket_table": _table(segments["by_bucket"]),
        "allocation_table": _table(reconciliation_view.class_allocation_table(response)),
        "chart_allocation": charts.grouped_bar_svg(
            reconciliation_view.class_allocation_chart_items(response), series=("Legacy", "Ours")
        ),
        "class_table": _table(segments["by_class"]),
        "approach_table": _table(segments["by_approach"]),
        # Tier 3 — worklist
        "break_count": breaks.height,
        "breaks_table": _table(breaks),
        # Tier 4 — forensic
        "bucket_choices": reconciliation_view.BUCKET_CHOICES,
        "active_bucket": bucket,
        "forensic": {
            "columns": f_cols,
            "rows": f_rows,
            "total": f_total,
            "shown": len(f_rows),
        },
        "export_csv_url": f"/api/reconcile/export/csv?recon_id={recon_id}",
        "export_excel_url": f"/api/reconcile/export/excel?recon_id={recon_id}",
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
