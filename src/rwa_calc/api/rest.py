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
from typing import TYPE_CHECKING, Literal, Self

import polars as pl
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from rwa_calc.api import run_index
from rwa_calc.api.export import ResultExporter
from rwa_calc.api.models import ValidationRequest
from rwa_calc.api.reconciliation import loads_reconciliation_config
from rwa_calc.api.service import CreditRiskCalc, get_supported_frameworks
from rwa_calc.api.validation import DataPathValidator
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.reporting import catalog, lineage
from rwa_calc.reporting.facts import FilingMetadata

if TYPE_CHECKING:
    from rwa_calc.api.models import (
        CalculationResponse,
        ComparisonExportResponse,
        PerformanceMetrics,
        ReconciliationResponse,
        SummaryStatistics,
        ValidationResponse,
    )
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

logger = logging.getLogger(__name__)

# In-process registry of completed runs (local single-process tool). Keyed by a
# generated run_id so results/export endpoints can find the cached parquet.
_RUNS: dict[str, CalculationResponse] = {}

# Parallel registry for reconciliation runs, keyed by a generated recon_id so the
# forensic-tier filter and export endpoints can re-read a cached result without
# recomputing. Same in-process / non-persistent trade-off as ``_RUNS``.
_RECON_RUNS: dict[str, ReconciliationResponse] = {}

# Parallel registry for comparison-export results (CRR vs Basel 3.1), keyed by a
# generated comparison_id so the comparison page's download buttons can stream a
# cached result without re-running both frameworks. Each entry holds only the
# collected export frames (not the lazy bundles), so it stays light; same
# in-process / non-persistent trade-off as ``_RUNS``.
_COMPARISONS: dict[str, ComparisonExportResponse] = {}


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


@dataclasses.dataclass(frozen=True, slots=True)
class TemplateBundles:
    """The COREP and Pillar 3 template bundles generated for one run."""

    corep: COREPTemplateBundle
    pillar3: Pillar3TemplateBundle


# Generated template bundles, keyed by (run_id, prior_run_id). Generating both
# bundles walks the whole results frame, so the viewer caches per run rather than
# regenerating on every page view / template switch. The prior_run_id is part of
# the key — a bundle generated WITH a comparative prior period (CR8's flow rows
# are non-null) must never be served for a request without one, and vice versa.
# Same in-process, non-persistent trade-off as ``_RUNS`` — an entry is only ever a
# pure function of that (run, prior_run) pair's results.
_TEMPLATE_BUNDLES: dict[tuple[str, str | None], TemplateBundles] = {}

_MAX_PAGE = 10_000

# Documents the 404 raised when a run_id (or its summary) is unknown, so it
# appears in the generated OpenAPI schema for the affected endpoints.
_RESP_404: dict[int | str, dict[str, str]] = {404: {"description": "Run or summary not found"}}

router = APIRouter(prefix="/api", tags=["rwa"])


# =============================================================================
# Request models
# =============================================================================


class _ScopedRequest(BaseModel):
    """Base for request bodies carrying an optional reporting scope.

    ``reporting_entity`` is an ``entity_reference`` into the reporting-entities
    registry; ``reporting_basis`` is the consolidation basis, validated against
    ``ReportingBasis`` so a garbage value is a 422 (not a 500). An entity set
    without a basis is a config error surfaced as a 422 here, so it never
    reaches the engine's ``ValueError``. Both blank is the unscoped path,
    byte-identical to pre-feature behaviour.
    """

    reporting_entity: str | None = None
    reporting_basis: ReportingBasis | None = None

    @model_validator(mode="after")
    def _require_basis_with_entity(self) -> Self:
        if self.reporting_entity is not None and self.reporting_basis is None:
            raise ValueError("reporting_entity requires reporting_basis")
        return self


class CalculateRequest(_ScopedRequest):
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


class ComparisonRequest(_ScopedRequest):
    """Body for POST /api/comparison — runs both frameworks over one dataset.

    A configured reporting scope applies identically to both regime runs.
    """

    data_path: str
    reporting_date: date
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"


class ReconcileRequest(_ScopedRequest):
    """Body for POST /api/reconcile — our run vs a mapped legacy output.

    ``mapping_toml`` is the reconciliation config (legacy file path, join keys,
    per-component column mapping) as TOML text; relative ``legacy_file`` paths in
    it resolve against ``data_path``.

    ``run_id`` optionally references an already-registered calculation (from
    ``POST /api/calculate``) to reconcile instead of re-running the pipeline.
    An explicit run_id is an instruction, not a preference: an unknown id is a
    404 and a run that cannot serve this request (framework/date mismatch,
    failed run, vanished results) is a 422 — never a silent recompute.
    """

    data_path: str
    reporting_date: date
    framework: Literal["CRR", "BASEL_3_1"] = "CRR"
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"
    mapping_toml: str
    run_id: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/frameworks")
def frameworks() -> list[dict[str, str]]:
    """List supported regulatory frameworks (for UI form population)."""
    return get_supported_frameworks()


@router.get("/entities")
def entities(data_path: str) -> list[dict]:
    """List the reporting-entities registry rows for a data directory.

    Reads the OPTIONAL ``config/reporting_entities`` table (parquet or csv) and
    returns its rows as JSON — ``entity_reference``, ``entity_name``, ``lei``,
    ``parent_entity_reference``, ``institution_type``, ``core_uk_group`` — for
    the multi-entity scope pickers. An absent registry file is a clean empty
    list (the table is optional); a ``data_path`` that is not an existing
    directory is a 422, mirroring the input-guarding the other endpoints apply.
    """
    root = Path(data_path).expanduser()
    if not data_path.strip() or not root.is_dir():
        raise HTTPException(status_code=422, detail=f"invalid data_path: {data_path!r}")
    return read_reporting_entities(root)


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
    """Run an RWA calculation and register the result under a fresh run_id.

    The run is also indexed for reuse (``rwa_calc.api.run_index``) so a later
    ``POST /api/reconcile`` — or the UI's reconciliation form in the same
    process — can start from it instead of re-running the pipeline.
    """
    logger.info("api calculate framework=%s mode=%s", req.framework, req.permission_mode)
    # Fingerprinted BEFORE the run so a mid-run input change can never be
    # reused against data the run did not read.
    fingerprint = run_index.compute_fingerprint(
        data_path=req.data_path,
        framework=req.framework,
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
        base_currency=req.base_currency,
        eur_gbp_rate=req.eur_gbp_rate,
        reporting_entity=req.reporting_entity,
        reporting_basis=_basis_str(req.reporting_basis),
    )
    response = _run_calc(
        data_path=req.data_path,
        framework=req.framework,
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
        base_currency=req.base_currency,
        eur_gbp_rate=req.eur_gbp_rate,
        reporting_entity=req.reporting_entity,
        reporting_basis=req.reporting_basis,
    )
    run_id = register_run(response)
    run_index.register_calculation(fingerprint, run_id, response)
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


@router.get("/templates", responses=_RESP_404)
def templates_index(run_id: str) -> dict:
    """List the regulatory templates generated for a completed run.

    Only templates with content are listed — a template that did not apply to
    the portfolio or the regime is absent, not empty.
    """
    response = _require_run(run_id)
    bundles = _require_template_bundles(run_id)
    infos = catalog.template_index(bundles.corep, bundles.pillar3)
    return {
        "run_id": run_id,
        "framework": response.framework,
        "templates": [dataclasses.asdict(info) for info in infos],
        "errors": [*bundles.corep.errors, *bundles.pillar3.errors],
    }


@router.get("/templates/{template_id}", responses=_RESP_404)
def template(template_id: str, run_id: str, sheet: str | None = None) -> dict:
    """Return one template sheet: its column headers and its rows, as generated.

    ``sheet`` selects a per-sheet template's key (exposure class / country /
    netting set); omitted, it takes the first sheet. Cells are returned exactly
    as the generator produced them — including the Annex II §1.3 "(-)" sign
    convention and the all-null inert rows. Nothing here recomputes a cell.
    """
    _require_run(run_id)
    bundles = _require_template_bundles(run_id)
    view = catalog.template_sheet(bundles.corep, bundles.pillar3, template_id, sheet)
    if view is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown template or sheet for this run: {template_id}",
        )
    frame = view.frame.fill_nan(None)
    return {
        "run_id": run_id,
        "template": dataclasses.asdict(view.info),
        "sheet": view.sheet,
        "columns": [dataclasses.asdict(col) for col in view.columns],
        "rows": frame.to_dicts(),
    }


@router.get("/lineage", responses=_RESP_404)
def cell_lineage(  # noqa: PLR0913 - the cell key plus paging
    run_id: str,
    template: str,
    row: str,
    col: str,
    sheet: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """Explain one reported template cell: what it means, and which legs produced it.

    The cell is addressed by the key the viewer stamps on it
    (``template``/``sheet``/``row``/``col``). The response echoes the cell's
    metric, its filter criteria and the scope of its population, so it is
    self-describing — and returns ``cell_value`` AS REPORTED (read from the
    generated template, never recomputed) alongside the contributing ledger legs.

    A template with no lineage (still imperative — C 34.x, CCR1-8) or a cell that
    is not on the template is a clean 404, never a re-derived guess.
    """
    response = _require_run(run_id)
    if not lineage.is_instrumented(template):
        raise HTTPException(
            status_code=404,
            detail=f"template {template!r} is not instrumented for lineage",
        )
    resolver = lineage.sheet_lineage(response, template, sheet or None)
    query = resolver.query(row, col) if resolver is not None else None
    if resolver is None or query is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown cell {template}/{sheet or '-'}/{row}/{col}",
        )
    if query.derives_from_prior_period:
        # A distinct refusal (R19 404-with-reason pattern): the cell's value is a
        # prior-period figure, and this drill-down runs on the current-period
        # ledger only — so a 200 would report a null that contradicts the screen.
        raise HTTPException(
            status_code=404,
            detail=(
                f"cell {template}/{row}/{col} derives from the prior period; "
                "drill-down covers the current-period ledger only"
            ),
        )
    if query.reads_unavailable_side_value:
        # Same never-disagree contract for an out-of-frame SideContext (OV1 row
        # 27's OF-ADJ): the reported template is generated WITH the run's
        # output-floor summary, but this drill-down's plan carries no side input,
        # so a 200 would report a null that contradicts the figure on the screen.
        raise HTTPException(
            status_code=404,
            detail=(
                f"cell {template}/{row}/{col} reads an out-of-frame side value "
                "this drill-down does not carry"
            ),
        )
    result = resolver.cell(
        row,
        col,
        run_id=run_id,
        offset=max(0, offset),
        limit=max(1, min(limit, _MAX_PAGE)),
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown cell {template}/{sheet or '-'}/{row}/{col}",
        )

    query = result.query
    rows = result.rows.fill_nan(None)
    return {
        "run_id": run_id,
        "cell": {
            "template": query.template_id,
            "sheet": query.sheet,
            "row_ref": query.row_ref,
            "col_ref": query.col_ref,
            "row_name": query.row_name,
        },
        "kind": query.kind,
        "metric": query.metric,
        "metric_columns": query.metric_columns,
        "missing_columns": query.missing_columns,
        "is_source_backed": query.is_source_backed,
        "filter_terms": [dataclasses.asdict(term) for term in query.filter_terms],
        "scope": query.scope,
        "refs": query.refs,
        "basis": query.basis,
        "sign": query.sign,
        "cell_value": result.cell_value,
        "contribution_total": result.contribution_total,
        "total_rows": result.total_rows,
        "offset": max(0, offset),
        "limit": max(1, min(limit, _MAX_PAGE)),
        "columns": rows.columns,
        "rows": rows.to_dicts(),
    }


@router.post("/comparison")
def comparison(req: ComparisonRequest) -> dict:
    """Run CRR and Basel 3.1 over one dataset and return both with deltas.

    Both runs are indexed for reuse (as ``POST /api/calculate`` does), so a
    later reconciliation over the same data can start from either.
    """
    logger.info("api comparison mode=%s", req.permission_mode)
    fingerprints = {
        fw: run_index.compute_fingerprint(
            data_path=req.data_path,
            framework=fw,
            reporting_date=req.reporting_date,
            permission_mode=req.permission_mode,
            data_format=req.data_format,
            reporting_entity=req.reporting_entity,
            reporting_basis=_basis_str(req.reporting_basis),
        )
        for fw in ("CRR", "BASEL_3_1")
    }
    crr = _run_calc(
        data_path=req.data_path,
        framework="CRR",
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
        reporting_entity=req.reporting_entity,
        reporting_basis=req.reporting_basis,
    )
    b31 = _run_calc(
        data_path=req.data_path,
        framework="BASEL_3_1",
        reporting_date=req.reporting_date,
        permission_mode=req.permission_mode,
        data_format=req.data_format,
        reporting_entity=req.reporting_entity,
        reporting_basis=req.reporting_basis,
    )
    crr_id = register_run(crr)
    b31_id = register_run(b31)
    run_index.register_calculation(fingerprints["CRR"], crr_id, crr)
    run_index.register_calculation(fingerprints["BASEL_3_1"], b31_id, b31)
    return {
        "crr": {"run_id": crr_id, **_serialize_response(crr)},
        "basel_3_1": {"run_id": b31_id, **_serialize_response(b31)},
        "deltas": _summary_deltas(crr.summary, b31.summary),
    }


@router.post("/reconcile", responses=_RESP_404)
def reconcile(req: ReconcileRequest) -> dict:
    """Reconcile our results against a mapped legacy output; register the result.

    Returns the recon_id plus each headline / segment / worklist tier as a
    ``{columns, rows}`` table. The wide per-key forensic frame is not inlined —
    download it via ``GET /api/reconcile/export/{fmt}``.

    With ``run_id`` set, the referenced calculation's cached results are
    reconciled and the pipeline is not re-run (see ``ReconcileRequest``).
    """
    logger.info("api reconcile framework=%s mode=%s", req.framework, req.permission_mode)
    calculation: CalculationResponse | None = None
    if req.run_id is not None:
        calculation = _require_run(req.run_id)
        _require_run_serves_reconcile(calculation, req)
    try:
        settings = loads_reconciliation_config(req.mapping_toml, base_dir=req.data_path or ".")
        response = CreditRiskCalc(
            data_path=req.data_path,
            framework=req.framework,
            reporting_date=req.reporting_date,
            permission_mode=req.permission_mode,
            data_format=req.data_format,
            reporting_entity=req.reporting_entity,
            reporting_basis=req.reporting_basis,
        ).reconcile(settings, calculation=calculation)
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
def export(
    fmt: Literal[
        "parquet",
        "csv",
        "excel",
        "corep",
        "pillar3",
        "corep_facts_parquet",
        "corep_facts_ndjson",
        "pillar3_facts_parquet",
        "pillar3_facts_ndjson",
    ],
    run_id: str,
    entity_identifier: str | None = None,
    prior_run_id: str | None = None,
) -> FileResponse:
    """Export a completed run and stream it back for download.

    All on-disk paths are built from a fresh temp dir plus a filename stamped
    from server-validated run data (framework, reporting date) — the
    user-supplied run_id itself never reaches the filesystem path. The
    ``*_facts_*`` formats stream the flat, keyed cell-fact feed
    (``reporting/facts.py``) instead of a merged-header workbook.
    ``entity_identifier`` (e.g. an LEI) is optional, caller-supplied firm-config
    metadata stamped onto the fact rows and the workbook metadata sheet — NOT
    onto the filename (it is free-form user input; unlike framework/
    reporting_date it is never sanitised for filesystem/path use).

    The Pillar 3 and COREP formats (``pillar3``, ``pillar3_facts_parquet``,
    ``pillar3_facts_ndjson``, ``corep``, ``corep_facts_parquet``,
    ``corep_facts_ndjson``) additionally accept:

    - ``prior_run_id``: an already-registered run to use as the comparative
      prior period for Pillar 3 CR8 / COREP C 08.04's RWEA flow rows.
      Selection is explicit only — an unknown id is a 404, and a run that
      cannot serve as this run's prior period (different framework, or a
      reporting_date not strictly earlier than this run's) is a 422.
      Omitted, CR8 / C 08.04's opening/flow rows stay null (unchanged
      behaviour); there is no auto-selected fallback.

    This run's own output-floor summary is threaded through automatically for
    the Pillar 3 formats — it is the run's own data, not a caller input.
    """
    response = _require_run(run_id)
    tmp = Path(tempfile.mkdtemp(prefix="rwa_export_"))
    metadata = FilingMetadata(
        reporting_date=response.reporting_date,
        framework=response.framework,
        run_id=run_id,
        entity_identifier=entity_identifier,
        # The run's consolidation basis (multi-entity submissions); None on an
        # unscoped run, so the metadata sheet / fact columns / stamped filename
        # stay byte-identical to pre-feature output. ``entity_name`` is left None
        # deliberately: the response carries only the registry ``entity_reference``
        # (a key), not the display name ``FilingMetadata.entity_name`` documents —
        # mislabelling a key as "Entity name" in a regulatory feed is worse than
        # omitting it. Resolving the display name from the reporting-entities
        # registry is a possible later enhancement.
        consolidation_basis=response.reporting_basis,
        entity_name=None,
    )
    exporter = ResultExporter()
    # metadata.stamped_filename() intentionally uses only framework/
    # reporting_date (server-validated, path-safe) — entity_identifier is
    # unsanitised caller input and must never be folded into a filesystem path.

    previous_period_results = _resolve_export_inputs(fmt, response, prior_run_id)

    if fmt in ("parquet", "csv", "excel"):
        return _export_raw(fmt, response, tmp, metadata)
    if fmt.startswith("corep"):
        return _export_corep(fmt, response, tmp, metadata, exporter, previous_period_results)
    return _export_pillar3(fmt, response, tmp, metadata, exporter, previous_period_results)


@router.get("/comparison/export/{fmt}", responses=_RESP_404)
def comparison_export(fmt: Literal["csv", "excel", "parquet"], comparison_id: str) -> FileResponse:
    """Export a registered CRR vs Basel 3.1 comparison and stream it for download.

    Carries the executive-summary headline, the by-class / by-approach delta
    summaries, the capital-impact waterfall and the per-exposure deltas. As with
    ``/export``, on-disk paths use a fresh temp dir plus fixed literal filenames —
    the user-supplied comparison_id never reaches the filesystem path.
    """
    response = _require_comparison(comparison_id)
    tmp = Path(tempfile.mkdtemp(prefix="rwa_comparison_export_"))

    if fmt == "excel":
        out = tmp / "comparison.xlsx"
        response.to_excel(out)
        return _file(out)

    out_dir = tmp / fmt
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        response.to_csv(out_dir)
        zip_path = tmp / "comparison_csv.zip"
    else:
        response.to_parquet(out_dir)
        zip_path = tmp / "comparison_parquet.zip"
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


def get_template_bundles(run_id: str, *, prior_run_id: str | None = None) -> TemplateBundles | None:
    """The run's COREP + Pillar 3 bundles, generating them once and caching.

    Returns None when the run itself is unknown/expired. Shared by the REST
    template endpoints and the UI's template viewer so a run's templates are
    generated at most once per (run_id, prior_run_id) pair per process.

    ``prior_run_id``, when supplied, must reference an already-registered run
    usable as *run_id*'s comparative prior period — see ``_require_prior_run``
    for the exact 404/422 contract (never a silent guess). Its results
    populate the Pillar 3 CR8 / COREP C 08.04 RWEA flow rows; the run's own
    ``output_floor_summary`` is always threaded through to Pillar 3 (it is the
    run's own data, not a caller input).
    """
    response = _RUNS.get(run_id)
    if response is None:
        return None
    cache_key = (run_id, prior_run_id)
    cached = _TEMPLATE_BUNDLES.get(cache_key)
    if cached is not None:
        return cached

    from rwa_calc.reporting.corep.generator import COREPGenerator
    from rwa_calc.reporting.pillar3.generator import Pillar3Generator

    previous_period_results = None
    if prior_run_id is not None:
        previous_period_results = _require_prior_run(prior_run_id, response).scan_results()

    # Both ids are route-parameter strings (see _safe_log_token); prior_run_id's
    # raw content is never interpolated at all — only whether one was supplied.
    logger.info(
        "generating report templates run_id=%s has_prior_period=%s",
        _safe_log_token(run_id),
        prior_run_id is not None,
    )
    bundles = TemplateBundles(
        corep=COREPGenerator().generate(response, previous_period_results=previous_period_results),
        pillar3=Pillar3Generator().generate_from_lazyframe(
            response.scan_results(),
            framework=response.framework,
            output_floor_summary=response.output_floor_summary,
            previous_period_results=previous_period_results,
        ),
    )
    _TEMPLATE_BUNDLES[cache_key] = bundles
    return bundles


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


def register_comparison(response: ComparisonExportResponse) -> str:
    """Register a comparison-export result in the in-process registry; return its id."""
    comparison_id = uuid.uuid4().hex
    _COMPARISONS[comparison_id] = response
    return comparison_id


def register_comparison_with_id(comparison_id: str, response: ComparisonExportResponse) -> None:
    """Register a comparison-export result under a caller-supplied id."""
    _COMPARISONS[comparison_id] = response


def get_comparison(comparison_id: str) -> ComparisonExportResponse | None:
    """Look up a registered comparison-export result, or None if unknown/expired."""
    return _COMPARISONS.get(comparison_id)


def register_recon_workspace(recon_id: str, workspace: ReconWorkspace) -> None:
    """Bind a recon_id to its sign-off workspace (called by the UI recon worker)."""
    _RECON_WORKSPACE[recon_id] = workspace


def get_recon_workspace(recon_id: str) -> ReconWorkspace | None:
    """Look up the sign-off workspace bound to a recon_id, or None if unknown."""
    return _RECON_WORKSPACE.get(recon_id)


# =============================================================================
# Private helpers
# =============================================================================


# The registry columns surfaced by GET /api/entities, in display order. Only
# ``entity_reference`` is guaranteed present (REPORTING_ENTITY_SCHEMA marks the
# rest optional), so a missing column is filled null rather than dropped — the
# feed shape is stable regardless of which optional columns the file carries.
_ENTITY_COLUMNS: tuple[str, ...] = (
    "entity_reference",
    "entity_name",
    "lei",
    "parent_entity_reference",
    "institution_type",
    "core_uk_group",
)


def read_reporting_entities(root: Path) -> list[dict]:
    """Read ``config/reporting_entities`` (parquet, then csv) into row dicts.

    Returns an empty list when neither file exists — the registry is optional,
    so its absence is the un-scoped norm, not an error. Missing optional columns
    are surfaced as null so the row shape is always the six ``_ENTITY_COLUMNS``.
    """
    for extension, reader in ((".parquet", pl.read_parquet), (".csv", pl.read_csv)):
        candidate = root / "config" / f"reporting_entities{extension}"
        if candidate.exists():
            frame = reader(candidate)
            present = set(frame.columns)
            selected = frame.select(
                pl.col(name) if name in present else pl.lit(None).alias(name)
                for name in _ENTITY_COLUMNS
            )
            return selected.to_dicts()
    return []


def _safe_log_token(value: str) -> str:
    """Strip CR/LF (and other control chars) so a caller-supplied id can't
    forge log lines (CWE-117 log injection). Route-parameter strings (run_id,
    prior_run_id, entity_identifier, ...) are tainted from a static-analysis
    standpoint regardless of what they happen to contain at runtime — a
    comment asserting "this one's always a UUID" doesn't clear the gate, so
    every such value is sanitised before it reaches a log call, not just the
    ones a human judges risky.
    """
    return "".join(ch for ch in value if ch.isprintable())


def _run_calc(
    *,
    data_path: str,
    framework: Literal["CRR", "BASEL_3_1"],
    reporting_date: date,
    permission_mode: Literal["standardised", "irb"],
    data_format: Literal["parquet", "csv"],
    base_currency: str = "GBP",
    eur_gbp_rate: Decimal = Decimal("0.8732"),
    reporting_entity: str | None = None,
    reporting_basis: ReportingBasis | None = None,
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
        reporting_entity=reporting_entity,
        reporting_basis=reporting_basis,
    ).calculate()


def _basis_str(basis: ReportingBasis | None) -> str | None:
    """The string value of a ``ReportingBasis`` for the fingerprint field.

    ``compute_fingerprint`` stores ``reporting_basis`` as ``str | None`` (and
    ``CreditRiskCalc`` stamps the same string onto the response), so the enum is
    rendered to its value at every fingerprint call site to keep the two in
    lock-step. None (unscoped) passes through unchanged.
    """
    return basis.value if basis is not None else None


def _require_run(run_id: str) -> CalculationResponse:
    """Look up a registered run or raise 404."""
    response = _RUNS.get(run_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
    return response


def _require_prior_run(prior_run_id: str, current: CalculationResponse) -> CalculationResponse:
    """Look up *prior_run_id* and verify it can serve as *current*'s prior period.

    Mirrors ``_require_run_serves_reconcile``'s explicit-instruction contract: an
    unknown id is a 404 (via ``_require_run``); a run that cannot serve as the
    comparative prior period — it failed, targets a different framework, or its
    reporting_date is not strictly earlier than *current*'s — is a 422. Never a
    silent guess at which run is "the" prior period.

    What this does NOT check: portfolio/book identity. Two runs can pass every
    check here while covering different books or data paths — same as
    ``_require_run_serves_reconcile``, choosing a prior run over the same book
    is the caller's responsibility, not something this function verifies.
    """
    prior = _require_run(prior_run_id)

    def _reject(reason: str) -> HTTPException:
        return HTTPException(
            status_code=422,
            detail=f"run {prior_run_id} not usable as the prior period: {reason}",
        )

    if not prior.success:
        raise _reject("the referenced calculation failed")
    if prior.framework != current.framework:
        raise _reject(
            f"framework {prior.framework!r} does not match the current run's {current.framework!r}"
        )
    if prior.reporting_date >= current.reporting_date:
        raise _reject(
            f"reporting_date {prior.reporting_date.isoformat()} is not strictly earlier "
            f"than the current run's {current.reporting_date.isoformat()}"
        )
    if not Path(prior.results_path).exists():
        raise _reject("its cached results are no longer available")
    return prior


def _resolve_export_inputs(
    fmt: str,
    response: CalculationResponse,
    prior_run_id: str | None,
) -> pl.LazyFrame | None:
    """Resolve the comparative-period input for one ``/export/{fmt}`` call.

    Only the Pillar 3 / COREP format families consult ``prior_run_id`` (via
    ``_require_prior_run`` — the same 404/422 contract either family gets).
    Every other format (parquet/csv/excel) resolves to ``None``.
    """
    is_pillar3 = fmt == "pillar3" or (fmt.startswith("pillar3") and "_facts_" in fmt)
    is_corep = fmt == "corep" or (fmt.startswith("corep") and "_facts_" in fmt)
    if (is_pillar3 or is_corep) and prior_run_id is not None:
        return _require_prior_run(prior_run_id, response).scan_results()
    return None


def _export_raw(
    fmt: str, response: CalculationResponse, tmp: Path, metadata: FilingMetadata
) -> FileResponse:
    """The plain, non-regulatory-template export formats: excel / parquet / csv."""
    if fmt == "excel":
        out = tmp / metadata.stamped_filename("rwa_results", "xlsx")
        response.to_excel(out)
        return _file(out)

    # parquet / csv export to a directory, then zip for a single download.
    out_dir = tmp / ("csv" if fmt == "csv" else "parquet")
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        response.to_csv(out_dir)
        zip_path = tmp / metadata.stamped_filename("rwa_csv", "zip")
    else:
        response.to_parquet(out_dir)
        zip_path = tmp / metadata.stamped_filename("rwa_parquet", "zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir))
    return _file(zip_path)


def _export_corep(
    fmt: str,
    response: CalculationResponse,
    tmp: Path,
    metadata: FilingMetadata,
    exporter: ResultExporter,
    previous_period_results: pl.LazyFrame | None,
) -> FileResponse:
    """The COREP export formats: corep / corep_facts_parquet / corep_facts_ndjson."""
    if fmt == "corep":
        out = tmp / metadata.stamped_filename("rwa_corep", "xlsx")
        exporter.export_to_corep(
            response,
            out,
            metadata=metadata,
            previous_period_results=previous_period_results,
        )
        return _file(out)

    facts_fmt: Literal["parquet", "ndjson"] = "ndjson" if fmt.endswith("ndjson") else "parquet"
    out = tmp / metadata.stamped_filename("rwa_corep_facts", facts_fmt)
    exporter.export_corep_facts(
        response,
        out,
        fmt=facts_fmt,
        metadata=metadata,
        previous_period_results=previous_period_results,
    )
    return _file(out)


def _export_pillar3(
    fmt: str,
    response: CalculationResponse,
    tmp: Path,
    metadata: FilingMetadata,
    exporter: ResultExporter,
    previous_period_results: pl.LazyFrame | None,
) -> FileResponse:
    """The Pillar 3 export formats: pillar3 / pillar3_facts_parquet / pillar3_facts_ndjson."""
    if fmt == "pillar3":
        out = tmp / metadata.stamped_filename("rwa_pillar3", "xlsx")
        exporter.export_to_pillar3(
            response,
            out,
            metadata=metadata,
            previous_period_results=previous_period_results,
            output_floor_summary=response.output_floor_summary,
        )
        return _file(out)

    facts_fmt: Literal["parquet", "ndjson"] = "ndjson" if fmt.endswith("ndjson") else "parquet"
    out = tmp / metadata.stamped_filename("rwa_pillar3_facts", facts_fmt)
    exporter.export_pillar3_facts(
        response,
        out,
        fmt=facts_fmt,
        metadata=metadata,
        previous_period_results=previous_period_results,
        output_floor_summary=response.output_floor_summary,
    )
    return _file(out)


def _require_template_bundles(run_id: str) -> TemplateBundles:
    """The run's generated template bundles, or raise 404 for an unknown run."""
    bundles = get_template_bundles(run_id)
    if bundles is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
    return bundles


def _require_run_serves_reconcile(calculation: CalculationResponse, req: ReconcileRequest) -> None:
    """Verify an explicitly referenced run can serve this reconciliation, else 422.

    The caller asked for THAT run — a run that cannot serve the request must be
    an error, never a silent recompute (contrast the UI's reuse checkbox, which
    is a preference and degrades silently via ``rwa_calc.api.run_index``).
    """

    def _reject(reason: str) -> HTTPException:
        return HTTPException(status_code=422, detail=f"run {req.run_id} not reusable: {reason}")

    if not calculation.success:
        raise _reject("the referenced calculation failed")
    if calculation.framework != req.framework:
        raise _reject(
            f"framework {calculation.framework!r} does not match request {req.framework!r}"
        )
    if calculation.reporting_date != req.reporting_date:
        raise _reject(
            f"reporting_date {calculation.reporting_date.isoformat()} does not match "
            f"request {req.reporting_date.isoformat()}"
        )
    if not Path(calculation.results_path).exists():
        raise _reject("its cached results are no longer available")


def _require_reconciliation(recon_id: str) -> ReconciliationResponse:
    """Look up a registered reconciliation or raise 404."""
    response = _RECON_RUNS.get(recon_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"unknown recon_id: {recon_id}")
    return response


def _require_comparison(comparison_id: str) -> ComparisonExportResponse:
    """Look up a registered comparison-export result or raise 404."""
    response = _COMPARISONS.get(comparison_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"unknown comparison_id: {comparison_id}")
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
