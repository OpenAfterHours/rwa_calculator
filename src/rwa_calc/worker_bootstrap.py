"""
Process-pool worker bootstrap — the one module a batch worker imports first.

Pipeline position:
    api/batch.py::_run_parallel -> ProcessPoolExecutor(initializer=...)
        -> worker process -> configure_worker_process -> (then the work item)

Key responsibilities:
- Set ``POLARS_MAX_THREADS`` inside a freshly spawned worker, *before* that
  worker imports Polars.

Why this is a top-level module and not part of ``api/``:
    ``ProcessPoolExecutor`` pickles its initializer by reference, so a spawned
    child imports the initializer's module during bootstrap — and importing
    anything under ``rwa_calc.api`` runs ``rwa_calc/api/__init__.py``, which
    reaches Polars. Polars sizes its thread pool at import, so an initializer
    living there would be set *after* the pool it is trying to size.
    ``rwa_calc/__init__.py`` is a docstring and three dunders, so
    ``rwa_calc.worker_bootstrap`` costs the child ``os`` and nothing else, and
    ``concurrent.futures.process._process_worker`` runs the initializer before
    its first ``call_queue.get()`` — which is where the work item (and with it
    ``rwa_calc.api.batch``, and with that Polars) is unpickled.

    **This module must therefore import nothing that transitively imports
    Polars.** ``os`` is the whole budget. Adding an ``rwa_calc`` import here
    silently uncaps every batch worker.

References:
- docs/plans/architecture-review-2026-08-29.md section 4.3 (P1)
- tests/conftest.py — the same Polars-threads-versus-memory trade, for xdist
"""

from __future__ import annotations

import os

POLARS_THREADS_ENV_VAR = "POLARS_MAX_THREADS"


def configure_worker_process(polars_max_threads: int) -> None:
    """Cap this worker's Polars thread pool. Runs once per worker process.

    Args:
        polars_max_threads: Threads for this worker's Polars runtime. Must be
            at least 1 — Polars accepts 0 at import and then panics at compute
            time with "Worker threads cannot be set to 0", i.e. one stage into
            the run rather than here.

    Raises:
        ValueError: If *polars_max_threads* is below 1. Not an ``assert``: this
            module exists to guarantee the cap, and ``-O`` would delete an
            assert while leaving the uncapped worker behind.
    """
    if polars_max_threads < 1:
        raise ValueError(f"{POLARS_THREADS_ENV_VAR} must be >= 1, got {polars_max_threads}")
    os.environ[POLARS_THREADS_ENV_VAR] = str(polars_max_threads)
