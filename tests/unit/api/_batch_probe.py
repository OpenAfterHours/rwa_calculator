"""Picklable stand-ins for ``rwa_calc.api.batch._run_scope``.

Why this is a module and not a closure in ``test_batch.py``: ``_run_parallel``
resolves ``_run_scope`` from the batch module's globals at call time and hands
it to ``executor.submit``, which pickles it **by reference**. A monkeypatched
replacement therefore has to be a module-level function the spawned child can
import by name. pytest puts ``tests/unit/api`` on ``sys.path`` (there is no
``__init__.py`` there, so it is the basedir for ``test_batch.py``) and
``multiprocessing.spawn`` copies ``sys.path`` into every child, which is what
makes ``_batch_probe`` importable on the far side.

The point of the stagger is to force a real pool's completion order to differ
from its submission order, so that "results come back in input order" is
actually tested rather than true by coincidence.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from rwa_calc.api.batch import _JobOutcome
from rwa_calc.api.models import CalculationResponse, PerformanceMetrics, SummaryStatistics

if TYPE_CHECKING:
    from rwa_calc.api.batch import _ScopeJob

# Seconds each scope sleeps AFTER the barrier below, by ``reporting_entity``,
# so that the last submitted finishes first. The test asserts the inversion
# actually happened by reading ``performance.completed_at`` back, so a stagger
# that stopped working fails rather than silently passing.
STAGGER_SECONDS: dict[str, float] = {"E1": 0.9, "E2": 0.45, "E3": 0.0}

# How many workers ``staggered_run`` waits for. Must equal the number of scopes
# in the test that uses it, and that test must give every scope its own worker —
# otherwise a scope that has not been dispatched yet can never arrive.
BARRIER_SIZE = 3
BARRIER_TIMEOUT_SECONDS = 60.0

# The scope that takes its worker down HARD. ``os._exit`` skips every finally,
# atexit hook and exception path, which is the closest reproduction of the
# SIGSEGV that engine/materialise.py documents Polars hitting on deep plans —
# and unlike a raised exception it breaks the whole pool.
CRASH_ENTITY = "E-CRASH"

# How long the healthy scopes dawdle, so the crash lands while at least one of
# them is genuinely in flight rather than after they have all finished.
HEALTHY_SECONDS = 0.5


def crashing_run(job: _ScopeJob) -> _JobOutcome:
    """Kill this worker outright for ``CRASH_ENTITY``; run normally otherwise."""
    if job.reporting_entity == CRASH_ENTITY:
        os._exit(70)
    time.sleep(HEALTHY_SECONDS)
    return _outcome(job)


def staggered_run(job: _ScopeJob) -> _JobOutcome:
    """Wait for every sibling worker, then sleep per ``STAGGER_SECONDS``.

    The barrier is the load-bearing part. Sleeping for a fixed time from the
    moment each worker happens to start does NOT order the completions: every
    worker pays ~2s to spawn and import Polars, and under a loaded box (eight
    xdist workers, say) that skew comfortably exceeds the 0.45s gaps — so the
    "last submitted finishes first" property was flaky and failed in a full-suite
    run. Waiting until all ``BARRIER_SIZE`` workers have arrived starts every
    sleep from one instant, which makes the completion order deterministic.

    Rendezvous is through the filesystem because the workers share nothing else:
    ``cache_dir`` is ``<cache_root>/<run_id>``, so its parent is the batch-wide
    directory every scope can see. The timeout only bounds a hang — if it fires,
    the ordering assertion fails, which is the correct outcome for a barrier
    that did not hold.

    ``performance.completed_at`` is stamped after the sleep, so the parent can
    read back the order in which the workers actually finished.
    """
    if job.cache_dir is not None:
        _wait_for_siblings(Path(job.cache_dir).parent, job.reporting_entity or "?")
    time.sleep(STAGGER_SECONDS.get(job.reporting_entity or "", 0.0))
    return _outcome(job)


def _wait_for_siblings(rendezvous: Path, name: str) -> None:
    """Announce this worker under *rendezvous*, then wait for ``BARRIER_SIZE``."""
    rendezvous.mkdir(parents=True, exist_ok=True)
    (rendezvous / f"arrived-{name}").write_text("1", encoding="utf-8")
    deadline = time.monotonic() + BARRIER_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if len(list(rendezvous.glob("arrived-*"))) >= BARRIER_SIZE:
            return
        time.sleep(0.01)


def _outcome(job: _ScopeJob) -> _JobOutcome:
    """A successful outcome tagged with the scope, stamped at completion time."""
    finished = datetime.now()
    return _JobOutcome(
        response=CalculationResponse(
            success=True,
            framework=job.framework,
            reporting_date=job.reporting_date,
            summary=SummaryStatistics(
                total_ead=Decimal("100"),
                total_rwa=Decimal("50"),
                exposure_count=1,
                average_risk_weight=Decimal("0.5"),
            ),
            results_path=Path("no-such-results.parquet"),
            performance=PerformanceMetrics(
                started_at=finished,
                completed_at=finished,
                duration_seconds=0.0,
                exposure_count=1,
            ),
            reporting_entity=job.reporting_entity,
        ),
        worker_pid=os.getpid(),
    )
