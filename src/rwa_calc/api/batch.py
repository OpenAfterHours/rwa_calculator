"""
Batch driver for N independent scoped RWA calculations.

Pipeline position:
    caller -> run_batch -> ProcessPoolExecutor -> CreditRiskCalc.calculate() (xN)
                        -> rwa_calc.api.run_index (fingerprint / dedup / register)

Key responsibilities:
- Fan a list of reporting scopes (a group submission plus its solo entities, or
  the same book under both frameworks) out over a process pool and return one
  result handle per scope, **in input order**.
- Isolate per-scope failures: one bad scope must not lose the other N-1
  results — including when it dies HARD (segfault / OOM kill), which breaks the
  whole pool and would otherwise take its innocent neighbours with it. See
  ``_run_parallel`` and ``_recover_lost_scopes`` for how that is contained.
  Data-quality problems already travel inside ``CalculationResponse`` as
  ``APIError``; this module only has to convert the *dispatch* failures into
  the same shape.
- Bound the fan-out. Memory, not cores, is the binding constraint — each worker
  holds a full result frame — so the default is deliberately far below the core
  count (see ``resolve_max_workers``).
- Collapse duplicate work through the existing run index rather than a second
  cache: a scope already run in this process is served from
  ``rwa_calc.api.run_index`` and never dispatched.

Why processes and not threads:
    A single pipeline run captures almost none of the machine — 1.16x from 16
    Polars threads on a 10k book, against 4.9x for a genuinely data-parallel
    control workload on the same box. The serial cost is Python and Polars
    *plan construction*, both GIL-bound, so N runs in N processes scale nearly
    linearly where N runs in N threads would not.
    (docs/plans/architecture-review-2026-08-29.md sections 4.1 and 4.3.)

What crosses the process boundary:
    OUT — one ``_ScopeJob`` per scope: strings, a ``date``, a ``Decimal`` and
    two directory paths (the data root and the run's parquet cache home). No
    ``CalculationConfig``, no loader, no ``RawDataBundle``, no LazyFrame. The
    config, the loader and the pipeline are all constructed *inside* the worker
    by ``CreditRiskCalc``.
    BACK — one ``_JobOutcome``: a ``CalculationResponse`` (paths, a
    ``SummaryStatistics`` of Decimals, ``APIError`` records, timings, the
    output-floor summary) plus the worker pid. ``CalculationResponse`` holds
    *paths* to parquet, never a frame, so the results themselves stay on disk
    and are scanned lazily by whichever process wants them.
    Every one of those types is a module-level frozen dataclass or a builtin,
    which is what Windows ``spawn`` requires; ``_run_scope`` is a module-level
    function for the same reason.

Capping Polars inside the workers:
    Each worker is capped to one Polars thread by a ``ProcessPoolExecutor``
    ``initializer`` (see ``_make_executor``). Nothing in *this* process's
    environment is touched, so concurrent batches on different threads cannot
    steal each other's cap. What makes the initializer land in time is where it
    lives: a spawned child imports the initializer's module during bootstrap,
    so an initializer defined in a module that transitively imports Polars is
    genuinely too late — Polars would already have sized its pool. It therefore
    lives in ``rwa_calc.worker_bootstrap``, whose whole import budget is ``os``.

Caller requirement on Windows:
    ``spawn`` re-imports the parent's ``__main__`` module in every child, so a
    *script* that calls ``run_batch`` at module scope re-runs its own batch in
    each worker. Put the call behind ``if __name__ == "__main__":``. Long-lived
    hosts (the REST app, a pytest session, an interactive shell) are unaffected
    — ``multiprocessing`` skips the re-import when ``__main__`` has no importable
    path — and the serial path has no such constraint at all.

Serial fallback:
    ``max_workers=1``, or ``RWA_BATCH_SERIAL=1`` in the environment, runs the
    same ``_run_scope`` in-process. A process pool is unusable inside a
    pytest-xdist worker and in some deployment sandboxes, and a pool that
    cannot be *created* degrades to the serial path with a batch-level warning
    rather than raising. Both paths call the same function with the same job,
    so the two cannot diverge.

References:
- docs/plans/architecture-review-2026-08-29.md section 4.3 (P1)
- tests/conftest.py — the Polars-threads-versus-memory trade this mirrors
"""

from __future__ import annotations

import dataclasses
import logging
import os
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rwa_calc.api import run_index
from rwa_calc.api.errors import create_api_error
from rwa_calc.api.models import APIError, CalculationResponse
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.worker_bootstrap import configure_worker_process

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from concurrent.futures import Future

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default worker ceiling, deliberately below the core count. The reference box
# is 16 cores to 7.8 GB, and every worker holds a full interpreter, its own
# Polars runtime and one run's result frame — the same reasoning
# tests/conftest.py records for the xdist fleet, where the binding constraint
# was RAM and not cores.
DEFAULT_MAX_WORKERS = 4

# Polars threads inside each worker. Capping to 1 costs ~16% on one run (3,254
# ms against 2,802 ms at 10k) and buys back the per-pool thread buffers that
# made the uncapped test fleet peak at 7.3 GB against 4.35 GB capped. With N
# runs already in flight, in-run Polars threading is the parallelism we can most
# afford to lose. NEVER 0 — Polars accepts 0 at import and panics at compute
# time with "Worker threads cannot be set to 0".
DEFAULT_WORKER_POLARS_THREADS = 1

# Deployment kill-switch for environments that cannot spawn at all. Set to any
# of ``_TRUTHY`` to force the serial path regardless of ``max_workers``.
SERIAL_ENV_VAR = "RWA_BATCH_SERIAL"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# A scope's own worker raised. The calculation never produced a response.
ERROR_SCOPE_FAILED = "BATCH001"
# Somebody else's worker died and took this scope's future down with it, AND
# the re-run could not be attempted either. A bystander that recovers never
# reaches the caller with this code — it reaches them with its result.
ERROR_POOL_BROKEN = "BATCH002"
# The pool could not be created at all; the batch ran serially instead.
ERROR_POOL_UNAVAILABLE = "BATCH003"
# A planned scope has no outcome and no cached response — a bookkeeping defect
# in this module, not anything the pool or the calculation did. Distinct from
# BATCH002 so the two are never confused in a log or a support ticket.
ERROR_SCOPE_NOT_DISPATCHED = "BATCH004"
# This scope, re-run ALONE in its own worker, terminated that worker: a hard
# exit (segfault / OOM kill / os._exit), not a raised exception. It is the scope
# that broke the batch, which is the finding — BATCH002's bystanders are not.
ERROR_WORKER_DIED = "BATCH005"

_CATEGORY = "Batch"


# =============================================================================
# Public request / result models
# =============================================================================


@dataclass(frozen=True)
class ScopeSpec:
    """One reporting scope to calculate.

    Attributes:
        reporting_entity: ``entity_reference`` into the reporting-entities
            registry, or None for an un-scoped (whole-book) run.
        reporting_basis: Consolidation basis for the scope. Required whenever
            ``reporting_entity`` is set — the same rule the REST layer enforces
            as a 422, applied here at construction so a malformed scope can
            never reach a worker.
        framework: Per-scope framework override. None takes the batch's
            framework, which is the normal multi-entity case; setting it is how
            a CRR-versus-Basel-3.1 comparison of one book becomes two scopes.
    """

    reporting_entity: str | None = None
    reporting_basis: ReportingBasis | None = None
    framework: Literal["CRR", "BASEL_3_1"] | None = None

    def __post_init__(self) -> None:
        if self.reporting_entity is not None and self.reporting_basis is None:
            raise ValueError("reporting_entity requires reporting_basis")


@dataclass(frozen=True)
class BatchRequest:
    """The scopes to run plus the inputs every scope shares.

    Every field except ``scopes`` mirrors a ``CreditRiskCalc`` parameter, so a
    one-scope batch is the calculation a direct ``CreditRiskCalc`` call would
    have produced.

    Attributes:
        scopes: The scopes to calculate, in the order results are wanted.
        data_path: Shared input directory — read independently by each worker.
        cache_root: Optional parent for the per-run parquet caches. Each run
            gets its own ``<cache_root>/<run_id>`` subdirectory: ``ResultsCache``
            writes fixed filenames (``last_results.parquet``), so scopes sharing
            one directory would overwrite each other. When the run index has
            persistence configured its own per-run home wins over this.
        max_workers: Requested worker count, or None for the default. Always
            bounded — see ``resolve_max_workers``.
        worker_polars_threads: ``POLARS_MAX_THREADS`` for the workers, or None
            to leave the environment alone.
        reuse_runs: Participate in the shared run index — read it before
            dispatching a scope, write successful runs back to it, and collapse
            duplicate scopes within this batch to a single run. False makes
            every scope an independent, unindexed run.
    """

    scopes: tuple[ScopeSpec, ...]
    data_path: str | Path
    reporting_date: date
    framework: Literal["CRR", "BASEL_3_1"] = "CRR"
    permission_mode: Literal["standardised", "irb"] = "standardised"
    data_format: Literal["parquet", "csv"] = "parquet"
    base_currency: str = "GBP"
    eur_gbp_rate: Decimal = Decimal("0.8732")
    cache_root: Path | None = None
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    max_workers: int | None = None
    worker_polars_threads: int | None = DEFAULT_WORKER_POLARS_THREADS
    reuse_runs: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", tuple(self.scopes))
        if self.max_workers is not None and self.max_workers < 1:
            raise ValueError(
                f"max_workers must be >= 1 (1 selects the serial path), got {self.max_workers}"
            )
        if self.worker_polars_threads is not None and self.worker_polars_threads < 1:
            raise ValueError(
                "worker_polars_threads must be >= 1 or None; Polars accepts 0 at "
                f"import and then panics at compute time (got {self.worker_polars_threads})"
            )


@dataclass(frozen=True)
class ScopeResult:
    """One scope's outcome. Every batch returns exactly one, in input order.

    Attributes:
        scope: The spec this result answers.
        response: The calculation's own response, or None when the scope never
            produced one (its worker died, or the pool broke before it ran).
            A response with ``success=False`` is a calculation that ran and
            failed — a different thing from None, and its own errors say why.
        error: The dispatch-level failure, when there was one.
        run_id: The id this scope is indexed under in ``rwa_calc.api.run_index``.
        reused: True when the run index served this scope and nothing was
            dispatched for it.
        worker_pid: The pid that executed the run. This process on the serial
            path, another on the parallel one — which is how a caller (or a
            test) tells a real pool from a silent degradation to serial.
    """

    scope: ScopeSpec
    response: CalculationResponse | None = None
    error: APIError | None = None
    run_id: str | None = None
    reused: bool = False
    worker_pid: int | None = None

    @property
    def success(self) -> bool:
        """True only when a calculation ran and reported success."""
        return self.response is not None and self.response.success

    @property
    def errors(self) -> list[APIError]:
        """Every error attributable to this scope, dispatch-level first."""
        dispatch = [self.error] if self.error is not None else []
        calculation = list(self.response.errors) if self.response is not None else []
        return dispatch + calculation


@dataclass(frozen=True)
class BatchResult:
    """The batch's per-scope results plus how it was actually executed.

    Attributes:
        results: One ``ScopeResult`` per requested scope, in input order.
        max_workers: The bound actually applied (never more than the number of
            distinct runs, nor the core count). 1 on the serial path.
        parallel: False when the batch ran serially — because it was asked to,
            because there was only one run, or because the pool would not start.
        errors: Batch-level errors (e.g. the pool being unavailable). Per-scope
            problems live on the ``ScopeResult``, never here.
    """

    results: tuple[ScopeResult, ...]
    max_workers: int
    parallel: bool
    errors: tuple[APIError, ...] = ()

    def __iter__(self) -> Iterator[ScopeResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> tuple[ScopeResult, ...]:
        """The scopes whose calculation ran and reported success."""
        return tuple(result for result in self.results if result.success)

    @property
    def failed(self) -> tuple[ScopeResult, ...]:
        """The scopes that did not, whether they failed or never ran."""
        return tuple(result for result in self.results if not result.success)


# =============================================================================
# Entry point
# =============================================================================


def run_batch(request: BatchRequest) -> BatchResult:
    """Run every scope in *request* and return one result per scope, in order.

    Never raises for a scope-level problem: a worker that dies, a pool that
    breaks and a calculation that fails all come back as a ``ScopeResult``
    carrying errors, so the surviving scopes' results are still returned.
    ``ValueError`` from ``BatchRequest`` / ``ScopeSpec`` construction is the
    only expected exception, and it happens before anything runs.

    Args:
        request: The scopes and the inputs they share.

    Returns:
        A ``BatchResult`` whose ``results`` are positionally aligned with
        ``request.scopes``.
    """
    if not request.scopes:
        logger.info("batch requested with no scopes; nothing to run")
        return BatchResult(results=(), max_workers=1, parallel=False)

    plan = _plan_batch(request)
    max_workers = resolve_max_workers(request.max_workers, len(plan.jobs))
    serial = max_workers == 1 or _serial_forced()
    logger.info(
        "batch of %d scope(s): %d run(s) to dispatch, %d served from the run index, "
        "max_workers=%d, mode=%s",
        len(request.scopes),
        len(plan.jobs),
        sum(1 for slot in plan.slots if slot.reused_response is not None),
        1 if serial else max_workers,
        "serial" if serial else "parallel",
    )

    batch_errors: tuple[APIError, ...] = ()
    if serial or not plan.jobs:
        outcomes = _run_serial(plan.jobs)
        parallel = False
    else:
        outcomes, pool_error = _run_parallel(plan.jobs, max_workers, request.worker_polars_threads)
        parallel = pool_error is None
        if pool_error is not None:
            batch_errors = (pool_error,)
            outcomes = _run_serial(plan.jobs)

    if request.reuse_runs:
        _register_runs(plan, outcomes)

    return BatchResult(
        results=tuple(_assemble(slot, outcomes) for slot in plan.slots),
        max_workers=max_workers if parallel else 1,
        parallel=parallel,
        errors=batch_errors,
    )


def resolve_max_workers(requested: int | None, run_count: int) -> int:
    """The worker count actually used for *run_count* dispatched runs.

    Bounded three ways, and the tightest wins:

    - by ``run_count`` — spawning an interpreter with nothing to give it is
      pure cost;
    - by ``os.cpu_count()`` — more resident sets than cores cannot buy
      throughput on a workload that is already CPU-bound;
    - by ``DEFAULT_MAX_WORKERS`` when the caller did not ask for a specific
      number. This is the memory bound, and it is why the default is 4 rather
      than the core count: on the 16-core / 7.8 GB reference box every worker
      holds an interpreter, a Polars runtime and one run's result frame, and
      ``tests/conftest.py`` records the same constraint biting the test fleet
      long before the cores ran out. A caller who knows its box has more
      headroom passes ``max_workers`` explicitly.

    Args:
        requested: The caller's ``max_workers``, or None for the default.
        run_count: How many distinct runs the batch actually has to dispatch.

    Returns:
        A worker count of at least 1. 1 means the serial path.

    Raises:
        ValueError: If *requested* is below 1 (a programming error — the serial
            path is ``max_workers=1``, not 0).
    """
    if requested is not None and requested < 1:
        raise ValueError(f"max_workers must be >= 1 (1 selects the serial path), got {requested}")
    if run_count <= 1:
        return 1
    cpus = os.cpu_count() or 1
    if requested is None:
        ceiling = min(cpus, DEFAULT_MAX_WORKERS)
    else:
        ceiling = min(requested, cpus)
        if requested > cpus:
            logger.warning(
                "max_workers=%d exceeds the %d available core(s); capped to %d",
                requested,
                cpus,
                cpus,
            )
    return max(1, min(ceiling, run_count))


# =============================================================================
# Worker entry point — module-level and picklable (Windows spawn)
# =============================================================================


@dataclass(frozen=True)
class _ScopeJob:
    """Everything one worker needs, and nothing that holds a frame.

    Deliberately flat: strings, a ``date``, a ``Decimal`` and two directory
    paths. ``CreditRiskCalc`` builds the config, the loader and the pipeline on
    the far side, so none of those has to be picklable.
    """

    run_id: str
    data_path: str
    framework: Literal["CRR", "BASEL_3_1"]
    reporting_date: date
    permission_mode: Literal["standardised", "irb"]
    data_format: Literal["parquet", "csv"]
    base_currency: str
    eur_gbp_rate: Decimal
    cache_dir: str | None
    log_level: str
    log_format: Literal["text", "json"]
    reporting_entity: str | None
    reporting_basis: str | None


@dataclass(frozen=True)
class _JobOutcome:
    """One dispatched run's outcome, as seen by the parent process."""

    response: CalculationResponse | None = None
    worker_pid: int | None = None
    error: APIError | None = None


def _run_scope(job: _ScopeJob) -> _JobOutcome:
    """Run one scope. Executes in a worker process on the parallel path.

    Imports ``CreditRiskCalc`` lazily so the import cost lands in the worker
    that needs it. ``CreditRiskCalc.calculate`` already converts every data and
    pipeline failure into a failed ``CalculationResponse``, so the only way out
    of here is a return value — an exception would mean a programming error,
    and the parent turns that into ``BATCH001`` rather than losing the batch.
    """
    from rwa_calc.api.service import CreditRiskCalc

    basis = ReportingBasis(job.reporting_basis) if job.reporting_basis is not None else None
    response = CreditRiskCalc(
        data_path=job.data_path,
        framework=job.framework,
        reporting_date=job.reporting_date,
        permission_mode=job.permission_mode,
        data_format=job.data_format,
        base_currency=job.base_currency,
        eur_gbp_rate=job.eur_gbp_rate,
        cache_dir=Path(job.cache_dir) if job.cache_dir is not None else None,
        log_level=job.log_level,
        log_format=job.log_format,
        reporting_entity=job.reporting_entity,
        reporting_basis=basis,
    ).calculate()
    return _JobOutcome(response=response, worker_pid=os.getpid())


# =============================================================================
# Planning — fingerprint, dedup, job construction
# =============================================================================


@dataclass(frozen=True)
class _Slot:
    """One input position: the scope, the run it maps to, and any cached hit."""

    scope: ScopeSpec
    run_id: str
    reused_response: CalculationResponse | None


@dataclass(frozen=True)
class _BatchPlan:
    """What the batch will dispatch, and how results map back to input order."""

    slots: tuple[_Slot, ...]
    jobs: tuple[_ScopeJob, ...]
    fingerprints: dict[str, run_index.CalculationFingerprint]


def _plan_batch(request: BatchRequest) -> _BatchPlan:
    """Fingerprint every scope, drop the duplicates, and build the jobs.

    The data signature is computed **once** and copied onto each scope's
    fingerprint: the scopes differ only in framework / entity / basis, and
    re-walking a multi-GB input tree once per entity would cost more than the
    lookup saves. Fingerprinting before the batch (rather than per scope as
    each is dispatched) is also the conservative direction — it is the same
    pre-run convention ``run_index`` documents, so an input file changed
    mid-batch invalidates the whole batch's reuse rather than half of it.
    """
    base = run_index.compute_fingerprint(
        data_path=request.data_path,
        framework=request.framework,
        reporting_date=request.reporting_date,
        permission_mode=request.permission_mode,
        data_format=request.data_format,
        base_currency=request.base_currency,
        eur_gbp_rate=request.eur_gbp_rate,
    )
    slots: list[_Slot] = []
    jobs: list[_ScopeJob] = []
    fingerprints: dict[str, run_index.CalculationFingerprint] = {}
    dispatched: dict[run_index.CalculationFingerprint, str] = {}

    for scope in request.scopes:
        fingerprint = dataclasses.replace(
            base,
            framework=scope.framework or request.framework,
            reporting_entity=scope.reporting_entity,
            reporting_basis=_basis_value(scope.reporting_basis),
        )
        if request.reuse_runs:
            already = dispatched.get(fingerprint)
            if already is not None:
                slots.append(_Slot(scope=scope, run_id=already, reused_response=None))
                continue
            cached = run_index.find_reusable(fingerprint)
            if cached is not None:
                logger.debug("batch scope served from the run index (run %s)", cached.run_id)
                slots.append(
                    _Slot(scope=scope, run_id=cached.run_id, reused_response=cached.response)
                )
                continue
        run_id = uuid.uuid4().hex
        jobs.append(_build_job(request, scope, run_id))
        fingerprints[run_id] = fingerprint
        dispatched[fingerprint] = run_id
        slots.append(_Slot(scope=scope, run_id=run_id, reused_response=None))

    return _BatchPlan(slots=tuple(slots), jobs=tuple(jobs), fingerprints=fingerprints)


def _build_job(request: BatchRequest, scope: ScopeSpec, run_id: str) -> _ScopeJob:
    """Flatten the shared request and one scope into a picklable job."""
    cache_dir = run_index.run_cache_dir(run_id)
    if cache_dir is None and request.cache_root is not None:
        cache_dir = request.cache_root / run_id
    return _ScopeJob(
        run_id=run_id,
        data_path=str(request.data_path),
        framework=scope.framework or request.framework,
        reporting_date=request.reporting_date,
        permission_mode=request.permission_mode,
        data_format=request.data_format,
        base_currency=request.base_currency,
        eur_gbp_rate=request.eur_gbp_rate,
        cache_dir=None if cache_dir is None else str(cache_dir),
        log_level=request.log_level,
        log_format=request.log_format,
        reporting_entity=scope.reporting_entity,
        reporting_basis=_basis_value(scope.reporting_basis),
    )


# =============================================================================
# Execution — serial and parallel, over the same _run_scope
# =============================================================================


def _run_serial(jobs: Sequence[_ScopeJob]) -> dict[str, _JobOutcome]:
    """Run every job in this process, one after another.

    The mandatory fallback: a process pool is unusable inside a pytest-xdist
    worker and in sandboxes that forbid spawning. Calls the same ``_run_scope``
    the pool calls, with the same job, so the two paths cannot diverge.
    """
    outcomes: dict[str, _JobOutcome] = {}
    for job in jobs:
        try:
            outcomes[job.run_id] = _run_scope(job)
        except Exception as exc:
            logger.exception("batch scope failed in-process")
            outcomes[job.run_id] = _JobOutcome(error=_scope_failed_error(exc))
    return outcomes


def _run_parallel(
    jobs: Sequence[_ScopeJob], max_workers: int, polars_threads: int | None
) -> tuple[dict[str, _JobOutcome], APIError | None]:
    """Run every job over a process pool, recovering the bystanders of a crash.

    Returns the outcomes and, when the pool could not be created at all, the
    batch-level error that sends the caller to the serial path.

    A pool that starts and then *breaks* is the case worth spelling out. A
    worker that RAISES fails one future. A worker that dies HARD — segfault,
    OOM kill, ``os._exit`` — fails **every pending future in the pool** with
    ``BrokenProcessPool``, so taking those at face value would lose the
    innocent N-1 along with the guilty one. That is not a theoretical concern
    here: ``engine/materialise.py`` documents Polars crashing the process with
    SIGSEGV on deep plans, and a batch is exactly where one pathological
    portfolio runs beside healthy ones.

    So the scopes marked broken are handed to ``_recover_lost_scopes``, which
    re-runs each ONE AT A TIME in its own fresh worker. A bystander comes back
    with a real result; the scope that actually killed the worker kills its own
    dedicated worker again and is reported as ``BATCH005``, naming it as the
    cause rather than as a casualty.
    """
    outcomes: dict[str, _JobOutcome] = {}
    try:
        executor = _make_executor(max_workers, polars_threads)
    except (OSError, ValueError, ImportError, NotImplementedError) as exc:
        logger.warning("process pool unavailable (%s); falling back to the serial path", exc)
        return {}, _pool_unavailable_error(exc)
    with executor:
        futures: dict[Future[_JobOutcome], _ScopeJob] = {}
        for job in jobs:
            try:
                futures[executor.submit(_run_scope, job)] = job
            except (BrokenProcessPool, RuntimeError) as exc:
                logger.error("could not dispatch a batch scope: %s", exc)
                outcomes[job.run_id] = _JobOutcome(error=_pool_broken_error(exc))
        for future in as_completed(futures):
            job = futures[future]
            try:
                outcomes[job.run_id] = future.result()
            except BrokenProcessPool as exc:
                logger.error("worker pool broke before a scope completed: %s", exc)
                outcomes[job.run_id] = _JobOutcome(error=_pool_broken_error(exc))
            except Exception as exc:
                logger.exception("batch scope failed in its worker")
                outcomes[job.run_id] = _JobOutcome(error=_scope_failed_error(exc))

    lost = tuple(job for job in jobs if _was_lost_to_a_broken_pool(outcomes.get(job.run_id)))
    if lost:
        logger.warning(
            "the worker pool broke; re-running %d of %d scope(s) one at a time",
            len(lost),
            len(jobs),
        )
        outcomes.update(_recover_lost_scopes(lost, polars_threads))
    return outcomes, None


def _was_lost_to_a_broken_pool(outcome: _JobOutcome | None) -> bool:
    """True for a scope whose only failure was that somebody else's worker died."""
    return outcome is None or (
        outcome.error is not None and outcome.error.code == ERROR_POOL_BROKEN
    )


def _recover_lost_scopes(
    jobs: Sequence[_ScopeJob], polars_threads: int | None
) -> dict[str, _JobOutcome]:
    """Re-run each lost scope alone in a fresh worker. Exactly once, never twice.

    One scope per pool is what makes the isolation structural rather than
    hopeful: with a single future outstanding, a ``BrokenProcessPool`` can only
    ever be about the scope in front of it. That costs one process spawn per
    lost scope (~2s on Windows, dominated by re-importing Polars), which is why
    this runs only after a crash and never on the healthy path.

    **The bound is the loop.** There is no retry: a plain ``for`` over the lost
    scopes, one attempt each. Re-running a scope that segfaults segfaults again,
    so anything that retried until success would spin forever — a scope that
    kills its second worker is recorded as ``BATCH005`` and the loop moves on.

    Note a recovered scope's calculation runs twice in total. That is safe: the
    only side effect is its own per-run parquet cache, which the second run
    overwrites in the same run-scoped directory.
    """
    outcomes: dict[str, _JobOutcome] = {}
    for job in jobs:
        try:
            with _make_executor(1, polars_threads) as executor:
                outcomes[job.run_id] = executor.submit(_run_scope, job).result()
        except BrokenProcessPool as exc:
            logger.error("a scope terminated its own dedicated worker: %s", exc)
            outcomes[job.run_id] = _JobOutcome(error=_worker_died_error(exc))
        except (OSError, ValueError, ImportError, NotImplementedError) as exc:
            logger.error("could not start a recovery worker: %s", exc)
            outcomes[job.run_id] = _JobOutcome(error=_pool_broken_error(exc))
        except Exception as exc:
            logger.exception("recovered batch scope failed in its worker")
            outcomes[job.run_id] = _JobOutcome(error=_scope_failed_error(exc))
    return outcomes


def _make_executor(max_workers: int, polars_threads: int | None) -> ProcessPoolExecutor:
    """The pool, with each worker's Polars thread pool capped on the way up.

    ``concurrent.futures.process._process_worker`` calls ``initializer(*initargs)``
    *before* its first ``call_queue.get()``, and the work item is what drags
    ``rwa_calc.api.batch`` — and with it Polars — into the child. So the cap
    lands before Polars is imported and sizes its pool, and this process's own
    environment is never touched. That matters: holding the cap in the parent's
    environ for the pool's lifetime would let two batches on different threads
    (``ui/app/progress.py`` runs a 4-thread job executor) overwrite each other's
    value and leave a worker uncapped, silently.

    The one thing that makes the initializer land in time is *where it lives*:
    a spawned child imports the initializer's module during bootstrap, so an
    initializer defined in a module that transitively imports Polars really
    would be too late. ``rwa_calc.worker_bootstrap`` imports ``os`` and nothing
    else, precisely so that it is not (see that module's docstring).

    Args:
        max_workers: Worker count, already bounded by ``resolve_max_workers``.
        polars_threads: Per-worker Polars threads, or None to leave the
            workers uncapped (they then size to the child's core count).
    """
    if polars_threads is None:
        return ProcessPoolExecutor(max_workers=max_workers)
    return ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=configure_worker_process,
        initargs=(polars_threads,),
    )


# =============================================================================
# Private helpers
# =============================================================================


def _assemble(slot: _Slot, outcomes: dict[str, _JobOutcome]) -> ScopeResult:
    """Turn one planned slot plus its outcome into the caller's result handle."""
    if slot.reused_response is not None:
        return ScopeResult(
            scope=slot.scope,
            response=slot.reused_response,
            run_id=slot.run_id,
            reused=True,
        )
    outcome = outcomes.get(slot.run_id)
    if outcome is None:
        # Only reachable if a planned job vanished between planning and
        # execution — our bug, not the pool's, hence its own code.
        logger.error("planned scope %s produced no outcome", slot.run_id)
        return ScopeResult(
            scope=slot.scope,
            error=_scope_not_dispatched_error(slot.run_id),
            run_id=slot.run_id,
        )
    return ScopeResult(
        scope=slot.scope,
        response=outcome.response,
        error=outcome.error,
        run_id=slot.run_id,
        worker_pid=outcome.worker_pid,
    )


def _register_runs(plan: _BatchPlan, outcomes: dict[str, _JobOutcome]) -> None:
    """Index the successful runs so a later scope or reconciliation reuses them.

    ``register_calculation`` ignores unsuccessful responses, so this is
    unconditional per job. Note the index is capped at
    ``run_index.MAX_INDEXED_RUNS`` — a batch wider than the cap evicts its own
    earliest entries, which costs a recompute and never a wrong answer.
    """
    for job in plan.jobs:
        outcome = outcomes.get(job.run_id)
        if outcome is None or outcome.response is None:
            continue
        run_index.register_calculation(plan.fingerprints[job.run_id], job.run_id, outcome.response)


def _serial_forced() -> bool:
    """True when the deployment has switched the process pool off."""
    return os.environ.get(SERIAL_ENV_VAR, "").strip().lower() in _TRUTHY


def _basis_value(basis: ReportingBasis | None) -> str | None:
    """The string value of a ``ReportingBasis``, for the fingerprint and the job.

    ``compute_fingerprint`` stores the basis as ``str | None`` and
    ``CreditRiskCalc`` stamps the same string onto the response, so the enum is
    rendered exactly once, here, and the two stay in lock-step.
    """
    return None if basis is None else basis.value


def _scope_failed_error(exc: BaseException) -> APIError:
    """The scope's worker raised — a programming error, reported not raised."""
    return create_api_error(
        code=ERROR_SCOPE_FAILED,
        message=f"Batch scope failed before producing a response: {exc}",
        severity="critical",
        category=_CATEGORY,
        detail=str(exc),
    )


def _pool_broken_error(exc: BaseException) -> APIError:
    """The pool died before this scope came back; the others are unaffected."""
    return create_api_error(
        code=ERROR_POOL_BROKEN,
        message=(
            f"Batch worker pool broke before this scope completed ({exc}); "
            "re-submit this scope on its own"
        ),
        severity="critical",
        category=_CATEGORY,
        detail=str(exc),
    )


def _worker_died_error(exc: BaseException) -> APIError:
    """This scope killed its own dedicated worker — it is the pathological one."""
    return create_api_error(
        code=ERROR_WORKER_DIED,
        message=(
            f"This scope terminated its worker process outright ({exc}). Re-run "
            "alone it did the same thing, so the fault is in this scope's data "
            "or plan, not in the batch — every other scope in the batch is "
            "unaffected and its result stands"
        ),
        severity="critical",
        category=_CATEGORY,
        detail=str(exc),
    )


def _scope_not_dispatched_error(run_id: str) -> APIError:
    """A planned scope reached assembly with no outcome — a defect in here."""
    return create_api_error(
        code=ERROR_SCOPE_NOT_DISPATCHED,
        message=(
            "Batch bookkeeping error: this scope was planned but never "
            "dispatched, so it has no result. Re-run the batch and report this."
        ),
        severity="critical",
        category=_CATEGORY,
        detail=run_id,
    )


def _pool_unavailable_error(exc: BaseException) -> APIError:
    """The pool would not start; the batch ran serially instead."""
    return create_api_error(
        code=ERROR_POOL_UNAVAILABLE,
        message=f"Batch worker pool unavailable ({exc}); the batch ran serially",
        severity="warning",
        category=_CATEGORY,
        detail=str(exc),
    )
