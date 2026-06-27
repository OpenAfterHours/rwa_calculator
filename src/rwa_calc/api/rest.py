"""
REST API for the RWA Calculator — the library-first HTTP contract.

Pipeline position:
    HTTP client -> rest.router -> CreditRiskCalc -> CalculationResponse

Key responsibilities:
- Expose the engine's public Python API (``CreditRiskCalc``) over HTTP/JSON so
  the reference UI and external embedders consume one shared contract.
- Run calculations and validations, page cached results, run CRR vs Basel 3.1
  comparisons, and stream exports (parquet/csv/excel/corep).

Design notes:
- Results are never held in memory: a calculation registers its
  ``CalculationResponse`` in an in-process registry keyed by ``run_id`` and the
  result rows are scanned lazily from the cached parquet on demand. This suits
  the local, single-process tool the UI ships as.
- Decimal summary metrics are emitted as floats for chart-friendliness; the
  underlying engine retains full Decimal precision.

References:
- src/rwa_calc/api/service.py (CreditRiskCalc)
- docs/specifications/interfaces.md (FR-6.x)
"""

from __future__ import annotations

import dataclasses
import logging
import tempfile
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from rwa_calc.api.models import ValidationRequest
from rwa_calc.api.reconciliation import loads_reconciliation_config
from rwa_calc.api.service import CreditRiskCalc, get_supported_frameworks
from rwa_calc.api.validation import DataPathValidator

if TYPE_CHECKING:
    from rwa_calc.api.models import (
        CalculationResponse,
        PerformanceMetrics,
        ReconciliationResponse,
        SummaryStatistics,
        ValidationResponse,
    )

logger = logging.getLogger(__name__)

# In-process registry of completed runs (local single-process tool). Keyed by a
# generated run_id so results/export endpoints can find the cached parquet.
_RUNS: dict[str, CalculationResponse] = {}

# Parallel registry for reconciliation runs, keyed by a generated recon_id so the
# forensic-tier filter and export endpoints can re-read a cached result without
# recomputing. Same in-process / non-persistent trade-off as ``_RUNS``.
_RECON_RUNS: dict[str, ReconciliationResponse] = {}


@dataclasses.dataclass(frozen=True, slots=True)
class ReconWorkspace:
    """The stable sign-off scope bound to one reconciliation run.

    ``workspace_id`` is the per-dataset hash (data path + mapping keys) under which
    ``ui.app.recon_signoff`` persists this run's accept/reject decisions;
    ``data_path`` is carried so an upsert can record it for the operator's reference.
    """

    workspace_id: str
    data_path: str


# Binds an (ephemeral) recon_id to its (persistent) sign-off workspace, so the
# sign-off routes can locate this run's stored decisions. The decisions live on
# disk (see ui.app.recon_signoff); this map is the in-process recon_id -> workspace
# lookup, cleared on restart like ``_RECON_RUNS``.
_RECON_WORKSPACE: dict[str, ReconWorkspace] = {}

_MAX_PAGE = 10_000

# Documents the 404 raised when a run_id (or its summary) is unknown, so it
# appears in the generated OpenAPI schema for the affected endpoints.
_RESP_404: dict[int | str, dict[str, str]] = {404: {"description": "Run or summary not found"}}

router = APIRouter(prefix="/api", tags=["rwa"])


# =============================================================================
# Request models
# =============================================================================


class CalculateRequest(BaseModel):
    """Body for POST /api/calculate."""

    data_path: str
    framework: Literal["CRR", "BASEL_3_1"] = "CRR"
    reporting_date: date
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"
    base_currency: str = "GBP"
    eur_gbp_rate: Decimal = Decimal("0.8732")


class ValidateRequest(BaseModel):
    """Body for POST /api/validate."""

    data_path: str
    data_format: Literal["parquet", "csv"] = "parquet"
    permission_mode: Literal["standardised", "irb"] = "standardised"


class ComparisonRequest(BaseModel):
    """Body for POST /api/comparison — runs both frameworks over one dataset."""

    data_path: str
    reporting_date: date
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"


class ReconcileRequest(BaseModel):
    """Body for POST /api/reconcile — our run vs a mapped legacy output.

    ``mapping_toml`` is the reconciliation config (legacy file path, join keys,
    per-component column mapping) as TOML text; relative ``legacy_file`` paths in
    it resolve against ``data_path``.
    """

    data_path: str
    reporting_date: date
    framework: Literal["CRR", "BASEL_3_1"] = "CRR"
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"
    mapping_toml: str


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/frameworks")
def frameworks() -> list[dict[str, str]]:
    """List supported regulatory frameworks (for UI form population)."""
    return get_supported_frameworks()


@router.post("/validate")
def validate(req: ValidateRequest) -> dict:
    """Validate a data directory for calculation readiness."""
    response = DataPathValidator().validate(
        ValidationRequest(
            data_path=req.data_path,
            data_format=req.data_format,
            permission_mode=req.permission_mode,
        )
    )
    return _serialize_validation(response)


@router.post("/calculate")
def calculate(req: CalculateRequest) -> dict:
    """Run an RWA calculation and register the result under a fresh run_id."""
    logger.info("api calculate framework=%s mode=%s", req.framework, req.permission_mode)
    response = _run_calc(
        data_path=req.data_path,
        framework=req.framework,
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
        base_currency=req.base_currency,
        eur_gbp_rate=req.eur_gbp_rate,
    )
    run_id = register_run(response)
    return {"run_id": run_id, **_serialize_response(response)}


@router.get("/results", responses=_RESP_404)
def results(run_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Page through the exposure-level results for a completed run."""
    response = _require_run(run_id)
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    lf = response.scan_results()
    total = int(lf.select(pl.len()).collect().item())
    page = lf.slice(offset, limit).collect().fill_nan(None)
    return {
        "run_id": run_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": page.columns,
        "rows": page.to_dicts(),
    }


@router.get("/results/summary/{dimension}", responses=_RESP_404)
def results_summary(dimension: Literal["class", "approach"], run_id: str) -> dict:
    """Return a portfolio summary (by exposure class or by approach) for charts."""
    response = _require_run(run_id)
    lf = (
        response.scan_summary_by_class()
        if dimension == "class"
        else response.scan_summary_by_approach()
    )
    if lf is None:
        raise HTTPException(status_code=404, detail=f"no summary by {dimension} for this run")
    df = lf.collect().fill_nan(None)
    return {"run_id": run_id, "dimension": dimension, "columns": df.columns, "rows": df.to_dicts()}


@router.post("/comparison")
def comparison(req: ComparisonRequest) -> dict:
    """Run CRR and Basel 3.1 over one dataset and return both with deltas."""
    logger.info("api comparison mode=%s", req.permission_mode)
    crr = _run_calc(
        data_path=req.data_path,
        framework="CRR",
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
    )
    b31 = _run_calc(
        data_path=req.data_path,
        framework="BASEL_3_1",
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
    )
    crr_id = register_run(crr)
    b31_id = register_run(b31)
    return {
        "crr": {"run_id": crr_id, **_serialize_response(crr)},
        "basel_3_1": {"run_id": b31_id, **_serialize_response(b31)},
        "deltas": _summary_deltas(crr.summary, b31.summary),
    }


@router.post("/reconcile")
def reconcile(req: ReconcileRequest) -> dict:
    """Reconcile our results against a mapped legacy output; register the result.

    Returns the recon_id plus each headline / segment / worklist tier as a
    ``{columns, rows}`` table. The wide per-key forensic frame is not inlined —
    download it via ``GET /api/reconcile/export/{fmt}``.
    """
    logger.info("api reconcile framework=%s mode=%s", req.framework, req.permission_mode)
    try:
        settings = loads_reconciliation_config(req.mapping_toml, base_dir=req.data_path or ".")
        response = CreditRiskCalc(
            data_path=req.data_path,
            framework=req.framework,
            reporting_date=req.reporting_date,
            permission_mode=req.permission_mode,
            data_format=req.data_format,
        ).reconcile(settings)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid reconciliation config: {exc}"
        ) from exc

    recon_id = register_reconciliation(response)
    return {
        "recon_id": recon_id,
        "success": response.success,
        "has_breaks": response.has_breaks,
        "totals_tie_out": _df(response.collect_totals_tie_out()),
        "summary_by_component": _df(response.collect_summary_by_component()),
        "summary_by_bucket": _df(response.collect_summary_by_bucket()),
        "summary_by_exposure_class": _df(response.collect_summary_by_exposure_class()),
        "summary_by_approach": _df(response.collect_summary_by_approach()),
        "breaks_detail": _df(response.collect_breaks_detail()),
        "errors": [dataclasses.asdict(e) for e in response.errors],
    }


@router.get("/reconcile/export/{fmt}", responses=_RESP_404)
def reconcile_export(fmt: Literal["csv", "excel"], recon_id: str) -> FileResponse:
    """Export a registered reconciliation and stream it back for download.

    As with ``/export``, on-disk paths use a fresh temp dir plus fixed literal
    filenames — the user-supplied recon_id never reaches the filesystem path.
    """
    response = _require_reconciliation(recon_id)
    tmp = Path(tempfile.mkdtemp(prefix="rwa_recon_export_"))

    if fmt == "excel":
        out = tmp / "reconciliation.xlsx"
        response.to_excel(out)
        return _file(out)

    out_dir = tmp / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    response.to_csv(out_dir)
    zip_path = tmp / "reconciliation_csv.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir))
    return _file(zip_path)


@router.get("/export/{fmt}", responses=_RESP_404)
def export(fmt: Literal["parquet", "csv", "excel", "corep"], run_id: str) -> FileResponse:
    """Export a completed run and stream it back for download.

    All on-disk paths are built from a fresh temp dir plus fixed, literal
    filenames — the user-supplied run_id never reaches the filesystem path.
    """
    response = _require_run(run_id)
    tmp = Path(tempfile.mkdtemp(prefix="rwa_export_"))

    if fmt == "excel":
        out = tmp / "rwa_results.xlsx"
        response.to_excel(out)
        return _file(out)
    if fmt == "corep":
        out = tmp / "rwa_corep.xlsx"
        response.to_corep(out)
        return _file(out)

    # parquet / csv export to a directory, then zip for a single download.
    out_dir = tmp / ("csv" if fmt == "csv" else "parquet")
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        response.to_csv(out_dir)
        zip_path = tmp / "rwa_csv.zip"
    else:
        response.to_parquet(out_dir)
        zip_path = tmp / "rwa_parquet.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir))
    return _file(zip_path)


# =============================================================================
# App factory
# =============================================================================


def create_api_app() -> FastAPI:
    """Build a standalone FastAPI app exposing the RWA router (for tests / dev)."""
    app = FastAPI(title="RWA Calculator API")
    app.include_router(router)
    return app


# =============================================================================
# Run registry (shared by the REST API and the server-rendered UI)
# =============================================================================


def register_run(response: CalculationResponse) -> str:
    """Register a completed run in the in-process registry; return its run_id."""
    run_id = uuid.uuid4().hex
    _RUNS[run_id] = response
    return run_id


def register_run_with_id(run_id: str, response: CalculationResponse) -> None:
    """Register a completed run under a caller-supplied id.

    Used by the UI's background-job flow so the job_id minted at dispatch (and
    shown in the ``/calculating/{id}`` progress URL) is the same id the results
    page is served under — one identifier from submit to results.
    """
    _RUNS[run_id] = response


def get_run(run_id: str) -> CalculationResponse | None:
    """Look up a registered run, or None if it is unknown/expired."""
    return _RUNS.get(run_id)


def register_reconciliation(response: ReconciliationResponse) -> str:
    """Register a reconciliation result in the in-process registry; return its id."""
    recon_id = uuid.uuid4().hex
    _RECON_RUNS[recon_id] = response
    return recon_id


def register_reconciliation_with_id(recon_id: str, response: ReconciliationResponse) -> None:
    """Register a reconciliation result under a caller-supplied id.

    Mirrors ``register_run_with_id``: the UI's background-job flow reuses the
    job_id minted at dispatch (shown in ``/reconciling/{id}``) as the result id,
    so the ``done`` event navigates to ``/reconciliation/{id}`` — one identifier
    from submit to results.
    """
    _RECON_RUNS[recon_id] = response


def get_reconciliation(recon_id: str) -> ReconciliationResponse | None:
    """Look up a registered reconciliation, or None if it is unknown/expired."""
    return _RECON_RUNS.get(recon_id)


def register_recon_workspace(recon_id: str, workspace: ReconWorkspace) -> None:
    """Bind a recon_id to its sign-off workspace (called by the UI recon worker)."""
    _RECON_WORKSPACE[recon_id] = workspace


def get_recon_workspace(recon_id: str) -> ReconWorkspace | None:
    """Look up the sign-off workspace bound to a recon_id, or None if unknown."""
    return _RECON_WORKSPACE.get(recon_id)


# =============================================================================
# Private helpers
# =============================================================================


def _run_calc(
    *,
    data_path: str,
    framework: Literal["CRR", "BASEL_3_1"],
    reporting_date: date,
    permission_mode: Literal["standardised", "irb"],
    data_format: Literal["parquet", "csv"],
    base_currency: str = "GBP",
    eur_gbp_rate: Decimal = Decimal("0.8732"),
) -> CalculationResponse:
    """Construct CreditRiskCalc and run a single calculation."""
    return CreditRiskCalc(
        data_path=data_path,
        framework=framework,
        reporting_date=reporting_date,
        permission_mode=permission_mode,
        data_format=data_format,
        base_currency=base_currency,
        eur_gbp_rate=eur_gbp_rate,
    ).calculate()


def _require_run(run_id: str) -> CalculationResponse:
    """Look up a registered run or raise 404."""
    response = _RUNS.get(run_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
    return response


def _require_reconciliation(recon_id: str) -> ReconciliationResponse:
    """Look up a registered reconciliation or raise 404."""
    response = _RECON_RUNS.get(recon_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"unknown recon_id: {recon_id}")
    return response


def _df(df: pl.DataFrame) -> dict:
    """Serialize a DataFrame as a JSON-friendly ``{columns, rows}`` table."""
    clean = df.fill_nan(None)
    return {"columns": clean.columns, "rows": clean.to_dicts()}


def _file(path: Path) -> FileResponse:
    """Stream a file back as an attachment."""
    return FileResponse(path, filename=path.name)


def _serialize_response(r: CalculationResponse) -> dict:
    """Convert a CalculationResponse into a JSON-friendly dict."""
    by_class = r.summary_by_class_path
    by_approach = r.summary_by_approach_path
    return {
        "success": r.success,
        "framework": r.framework,
        "reporting_date": r.reporting_date.isoformat(),
        "summary": _serialize_summary(r.summary),
        "errors": [dataclasses.asdict(e) for e in r.errors],
        "performance": _serialize_perf(r.performance),
        "has_results": r.results_path is not None,
        "has_summary_by_class": by_class is not None and Path(by_class).exists(),
        "has_summary_by_approach": by_approach is not None and Path(by_approach).exists(),
    }


def _serialize_summary(s: SummaryStatistics) -> dict:
    """Flatten SummaryStatistics, casting Decimals to float for charts."""
    return {
        k: (float(v) if isinstance(v, Decimal) else v) for k, v in dataclasses.asdict(s).items()
    }


def _serialize_perf(p: PerformanceMetrics | None) -> dict | None:
    """Serialize performance metrics, or None when absent."""
    if p is None:
        return None
    return {
        "started_at": p.started_at.isoformat(),
        "completed_at": p.completed_at.isoformat(),
        "duration_seconds": p.duration_seconds,
        "exposure_count": p.exposure_count,
        "exposures_per_second": p.exposures_per_second,
    }


def _serialize_validation(v: ValidationResponse) -> dict:
    """Convert a ValidationResponse into a JSON-friendly dict."""
    return {
        "valid": v.valid,
        "data_path": str(v.data_path),
        "files_found": [str(p) for p in v.files_found],
        "files_missing": [str(p) for p in v.files_missing],
        "errors": [dataclasses.asdict(e) for e in v.errors],
        "cached_path": str(v.cached_path) if v.cached_path is not None else None,
    }


def _summary_deltas(crr: SummaryStatistics, b31: SummaryStatistics) -> dict:
    """Per-metric Basel 3.1 minus CRR deltas for the headline figures."""
    metrics = (
        "total_ead",
        "total_rwa",
        "total_rwa_sa",
        "total_rwa_irb",
        "total_rwa_slotting",
    )
    return {m: float(getattr(b31, m) - getattr(crr, m)) for m in metrics}
