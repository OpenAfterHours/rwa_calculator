"""
Background-job + live-progress plumbing for the calculator page.

Pipeline position:
    POST /calculate -> submit_job() -> ThreadPoolExecutor worker -> CreditRiskCalc
    stage_timer log records -> _ProgressLogHandler -> Job -> SSE / status poll

Key responsibilities:
- Run a calculation off the request thread so the browser gets immediate
  feedback (a stage-by-stage stepper) instead of a frozen tab.
- Tap the pipeline's existing per-stage telemetry: every registered stage is
  wrapped in ``stage_timer`` (engine/orchestrator.py), which emits an INFO
  "<stage> completed in N ms" record carrying ``record.stage`` /
  ``record.elapsed_ms``. A logging.Handler attached to the ``rwa_calc``
  namespace logger routes those records to the active ``Job``.
- Correlate records to a job WITHOUT touching the engine: each worker runs in a
  copied ``contextvars`` context with ``_active_job`` set, so the handler (which
  runs synchronously in the emitting thread) reads the right job. This mirrors
  the ContextVar side-channel pattern already used by ``engine/materialise.py``.

Honest-progress note:
    The pipeline is lazy Polars; the real compute is concentrated at a handful
    of ``.collect()`` boundaries, dominated by the ``calculators`` branch
    collect. The stepper is therefore driven off stage *order* (which stage has
    completed), never a synthesised percentage — the spinner honestly parks on
    the heavy "calculators" step rather than racing a bar to 90% and hanging.

References:
- src/rwa_calc/engine/registry.py (PIPELINE_STAGES — the ordered stage list)
- src/rwa_calc/observability/context.py (stage_timer, the event source)
"""

from __future__ import annotations

import contextvars
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rwa_calc.engine.registry import PIPELINE_STAGES

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# =============================================================================
# Stage sequence (single source of truth: the literal pipeline registry)
# =============================================================================


@dataclass(frozen=True)
class StageInfo:
    """One step in the on-screen stepper, derived from a registry StageSpec."""

    name: str
    label: str
    heavy: bool


# Friendly labels for the stepper. Falls back to the raw stage name for any
# stage added to the registry without a label here, so the count always tracks
# PIPELINE_STAGES even if a label is momentarily missing.
_STAGE_LABELS: dict[str, str] = {
    "securitisation_allocator": "Securitisation",
    "hierarchy_resolver": "Hierarchy & exposures",
    "ccr_sa_ccr": "Counterparty credit risk (SA-CCR)",
    "sft_fccm": "Securities financing (FCCM)",
    "classifier": "Classification",
    "crm_processor": "Credit risk mitigation",
    "re_splitter": "Real-estate split",
    "calculators": "Risk-weight calculators",
    "equity_calculator": "Equity",
    "aggregator": "Aggregation & output floor",
}

# The long pole: the calculators branch collect holds the majority of wall time.
# Flagged so the stepper can label it honestly ("the heavy step").
_HEAVY_STAGES: frozenset[str] = frozenset({"calculators"})

STAGE_SEQUENCE: tuple[StageInfo, ...] = tuple(
    StageInfo(
        name=spec.name,
        label=_STAGE_LABELS.get(spec.name, spec.name),
        heavy=spec.name in _HEAVY_STAGES,
    )
    for spec in PIPELINE_STAGES
)

STAGE_INDEX: dict[str, int] = {info.name: i for i, info in enumerate(STAGE_SEQUENCE)}
KNOWN_STAGE_NAMES: frozenset[str] = frozenset(STAGE_INDEX)

# Reconciliation runs the SAME engine pipeline (so every engine stage above
# streams for free via the logging tap) and then a reconcile tail: load the
# legacy file, join it to our side and bucket every component. That tail is a
# plain function, not a registry stage, so the background worker marks it
# DIRECTLY (``job.mark_stage("recon_reconcile")``) after it has warmed the
# result frames — which is also where the heavy lazy join actually executes. The
# stepper therefore parks honestly on this final step while the join runs.
RECON_STAGE_NAME = "recon_reconcile"
RECON_STAGE_SEQUENCE: tuple[StageInfo, ...] = (
    *STAGE_SEQUENCE,
    StageInfo(name=RECON_STAGE_NAME, label="Reconcile & summarise", heavy=False),
)

# A calculation can optionally write the selected export formats to a folder
# AFTER calculate() returns (see ui.app.main._calculation_worker). That write is
# a plain function, not a registry stage, so when a run has exports configured the
# worker marks this synthetic tail step DIRECTLY once the files are written — so
# the stepper parks honestly on "Create exports" instead of appearing to hang on
# the last pipeline stage while the workbook(s)/files write. Shown only when the
# run actually writes exports (Job.writes_exports); a plain run ends at the
# aggregator with no trailing step.
EXPORT_STAGE_NAME = "write_exports"
EXPORT_STAGE_SEQUENCE: tuple[StageInfo, ...] = (
    *STAGE_SEQUENCE,
    StageInfo(name=EXPORT_STAGE_NAME, label="Create exports", heavy=False),
)


# =============================================================================
# Job state
# =============================================================================


@dataclass(frozen=True)
class JobSnapshot:
    """An immutable read of a Job's state, taken under its lock."""

    completed: tuple[str, ...]
    status: str  # "running" | "done" | "error"
    success: bool | None
    error: str | None


@dataclass
class Job:
    """A single background calculation, mutated by its worker thread + handler.

    Not a frozen pipeline bundle — this is mutable UI state guarded by a lock,
    living entirely outside the engine's immutable-context contract.
    """

    job_id: str
    # Whether this run writes export files after calculate() returns. Drives the
    # trailing "Create exports" step on the stepper; set once at creation, read by
    # the /calculating page render. Plain immutable flag, no lock needed.
    writes_exports: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _completed: list[str] = field(default_factory=list, repr=False)
    _status: str = "running"
    _success: bool | None = None
    _error: str | None = None

    def mark_stage(self, name: str) -> None:
        """Record that *name* finished (idempotent, preserves first-seen order)."""
        with self._lock:
            if name not in self._completed:
                self._completed.append(name)

    def finish(self, *, success: bool) -> None:
        """Mark the run complete; *success* reflects ``response.success``."""
        with self._lock:
            self._status = "done"
            self._success = success

    def fail(self, message: str) -> None:
        """Mark the run failed with an unexpected error message."""
        with self._lock:
            self._status = "error"
            self._success = False
            self._error = message

    def snapshot(self) -> JobSnapshot:
        """Take a consistent, immutable read of the current state."""
        with self._lock:
            return JobSnapshot(
                completed=tuple(self._completed),
                status=self._status,
                success=self._success,
                error=self._error,
            )


# =============================================================================
# In-process job registry (local single-process tool, mirrors rest._RUNS)
# =============================================================================

_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def create_job(*, writes_exports: bool = False) -> Job:
    """Create and register a fresh running job; return it.

    ``writes_exports`` marks a run that will write export files after the
    pipeline finishes, so the stepper shows the trailing "Create exports" step.
    """
    job = Job(job_id=uuid.uuid4().hex, writes_exports=writes_exports)
    with _JOBS_LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    """Look up a registered job, or None if unknown/expired."""
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# =============================================================================
# Dispatch — run the worker off the request thread, context-isolated
# =============================================================================

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rwa-calc-job")

# The job a worker thread is currently running, read by _ProgressLogHandler.
# Default None so synchronous request handlers (which never set it) are ignored.
_active_job: ContextVar[Job | None] = ContextVar("rwa_ui_active_job", default=None)


def submit_job(job: Job, work: Callable[[Job], None]) -> None:
    """Run ``work(job)`` on the executor in a context where this job is active.

    A copied context isolates ``_active_job`` (and the pipeline's own run_id
    ContextVar) per task, so pooled threads never leak progress between jobs.
    """

    def _run() -> None:
        _active_job.set(job)
        try:
            work(job)
        except Exception as exc:  # noqa: BLE001 — a worker crash must still close the job
            logger.warning("calculation job %s crashed: %s", job.job_id, exc)
            job.fail(str(exc))

    ctx = contextvars.copy_context()
    _EXECUTOR.submit(ctx.run, _run)


# =============================================================================
# Logging tap — route stage_timer records to the active job
# =============================================================================

_NAMESPACE = "rwa_calc"
_HANDLER_ATTR = "_rwa_progress_handler"


class _ProgressLogHandler(logging.Handler):
    """Mark a stage complete on the active job for each stage_timer exit record.

    A stage-completion record carries ``record.stage`` (one of the registry
    stage names) and ``record.elapsed_ms``. Records for the run as a whole use
    ``stage="pipeline"`` (not in KNOWN_STAGE_NAMES) and are ignored, as are all
    records emitted outside a background job (``_active_job`` is None).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            job = _active_job.get()
            if job is None:
                return
            stage = getattr(record, "stage", None)
            if stage in KNOWN_STAGE_NAMES and getattr(record, "elapsed_ms", None) is not None:
                job.mark_stage(stage)
        except Exception:  # noqa: BLE001 — a logging handler must never raise
            pass


def attach_progress_handler() -> None:
    """Attach the progress tap to the ``rwa_calc`` logger (idempotent).

    Safe alongside ``observability.configure_logging`` — that helper only ever
    manages its own handler, so an extra handler added here survives
    reconfiguration. Child loggers (e.g. ``rwa_calc.engine.orchestrator``)
    propagate their records up to this namespace logger.
    """
    namespace_logger = logging.getLogger(_NAMESPACE)
    if getattr(namespace_logger, _HANDLER_ATTR, None) is not None:
        return
    handler = _ProgressLogHandler(level=logging.INFO)
    namespace_logger.addHandler(handler)
    setattr(namespace_logger, _HANDLER_ATTR, handler)
