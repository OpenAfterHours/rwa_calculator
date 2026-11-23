"""
Background UI jobs, read for test isolation.

Pipeline position:
    (no pipeline stage - reads the UI's in-process job registry,
    ``rwa_calc.ui.app.progress._JOBS``, which the calculator and reconciliation
    routes fill and the UI's module-level ``ThreadPoolExecutor`` drains)

Key responsibilities:
- Say which UI jobs exist and which are still ``"running"``, so that a test
  which dispatches a job and returns without waiting for it is named rather
  than left to run on into whatever test comes next. A job left running is a
  full pipeline run on another thread: it is counted by any process-wide Polars
  spy (the collect budget read 2-3.5x its banked counts behind one, P5.74), it
  competes for CPU with timing tests, and it writes the developer's real
  ``~/.rwa_calc`` once the test's ``RWA_STATE_DIR`` monkeypatch is undone.
- Read the registry WITHOUT importing the UI. A process that never imported
  ``rwa_calc.ui.app.progress`` cannot hold a job, so the lookup goes through
  ``sys.modules`` and costs nothing for the tests that never touch the UI. The
  module name is a string here, so a rename would leave every lookup silently
  empty; ``tests/contracts/test_pipeline_collect_budget.py`` registers a job
  through the real ``create_job`` and fails if this module cannot see it.

Why ``"running"`` stands in for "a worker thread is still busy":
    Both UI workers (``ui.app.main._calculation_worker`` and
    ``_reconciliation_worker``) call ``job.finish`` as their LAST statement, and
    ``progress.submit_job`` turns any exception into ``job.fail``, so a job
    leaves ``"running"`` only when its worker has nothing left to do. The proxy
    does not hold for a job created with ``create_job`` and never run to its end
    - one handed to a stubbed ``submit_job``, or to a worker called directly
    that raised. Such a job stays ``"running"`` for the life of the process (the
    registry is never pruned), so a test that stubs ``submit_job`` must close
    the job it is given.

References:
- tests/conftest.py (``_no_leaked_ui_job``, the per-test guard)
- tests/contracts/test_pipeline_collect_budget.py (the measurement precondition)
- src/rwa_calc/ui/app/progress.py (``Job``, ``create_job``, ``submit_job``)
"""

from __future__ import annotations

import sys

#: The module that owns the UI job registry, looked up in ``sys.modules``.
UI_PROGRESS_MODULE = "rwa_calc.ui.app.progress"


def ui_job_ids() -> frozenset[str]:
    """Return the ids of every UI job registered in this process so far."""
    progress = sys.modules.get(UI_PROGRESS_MODULE)
    if progress is None:
        return frozenset()
    with progress._JOBS_LOCK:
        return frozenset(progress._JOBS)


def running_ui_job_ids() -> frozenset[str]:
    """Return the ids of the UI jobs whose status is still ``"running"``."""
    progress = sys.modules.get(UI_PROGRESS_MODULE)
    if progress is None:
        return frozenset()
    with progress._JOBS_LOCK:
        jobs = dict(progress._JOBS)
    return frozenset(job_id for job_id, job in jobs.items() if job.snapshot().status == "running")
