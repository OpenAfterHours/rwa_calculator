"""
Opt-in audit-cache writer for pipeline diagnostics.

Pipeline position:
    Cross-cutting — called by CRM stages and the pipeline orchestrator as a
    side-effect at existing hook points. Not part of the regulatory
    calculation itself; it must never perturb a run.

Key responsibilities:
- ``sink_audit``: persist a frame as ``<audit_cache_dir>/<run_id>/<name>.parquet``
  when the user has opted in via ``CalculationConfig.audit_cache_dir``
- ``prune_audit_cache``: trim the cache directory to the
  ``audit_cache_max_runs`` newest run subdirectories
- Atomic writes (``.tmp`` + ``os.replace``) and swallow-and-log failure
  semantics — audit caching must never break a real run

References:
- docs/specifications/audit-cache.md
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.observability.context import current_run_id

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


def sink_audit(
    frame: pl.LazyFrame | pl.DataFrame,
    config: CalculationConfig,
    name: str,
) -> None:
    """Persist a frame as ``<audit_cache_dir>/<run_id>/<name>.parquet``.

    Opt-in side-effect: no-ops when ``config.audit_cache_dir`` is ``None``,
    which is the default. The artifact path is partitioned by the active
    ``run_id`` from ``observability.context.current_run_id`` so each pipeline
    run gets its own subdirectory matching the correlation id on every
    LogRecord. Write is atomic via ``<name>.parquet.tmp`` + ``os.replace``;
    a previous file at the destination is overwritten.

    A ``LazyFrame`` is collected via ``sink_parquet`` (streaming); a
    ``DataFrame`` is written via ``write_parquet``. Failures (disk full,
    permission denied, streaming-unsupported expression) are logged at
    WARNING and swallowed — audit caching must never break a real run.

    See ``docs/specifications/audit-cache.md`` for the canonical layout.
    """
    if config.audit_cache_dir is None:
        return

    run_id = current_run_id()
    if run_id is None:
        logger.warning(
            "sink_audit(%s) skipped: no active run_id (call outside pipeline run?)",
            name,
        )
        return

    safe_name = name.replace("/", "_").replace(" ", "_")
    run_dir = Path(config.audit_cache_dir) / run_id
    final_path = run_dir / f"{safe_name}.parquet"
    tmp_path = run_dir / f"{safe_name}.parquet.tmp"

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(frame, pl.LazyFrame):
            frame.sink_parquet(tmp_path)
        else:
            frame.write_parquet(tmp_path)
        os.replace(tmp_path, final_path)
        logger.info("wrote audit artifact %s", final_path)
    except Exception as exc:
        logger.warning("sink_audit(%s) failed: %s", name, exc)
        # Best-effort cleanup of the half-written .tmp file.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def prune_audit_cache(config: CalculationConfig) -> None:
    """Trim ``audit_cache_dir`` to the ``audit_cache_max_runs`` newest subdirs.

    No-op when either ``audit_cache_dir`` or ``audit_cache_max_runs`` is
    ``None``. Subdirectories are sorted by mtime; the oldest beyond the cap
    are removed. Non-directory entries are left alone. Failures are logged
    at WARNING and swallowed.
    """
    if config.audit_cache_dir is None or config.audit_cache_max_runs is None:
        return
    _prune_audit_cache(Path(config.audit_cache_dir), config.audit_cache_max_runs)


def _prune_audit_cache(audit_dir: Path, max_runs: int) -> None:
    """Delete oldest run subdirectories until at most ``max_runs`` remain."""
    if max_runs <= 0:
        return
    try:
        if not audit_dir.exists():
            return
        run_dirs = [p for p in audit_dir.iterdir() if p.is_dir()]
    except OSError as exc:
        logger.warning("prune_audit_cache: cannot list %s: %s", audit_dir, exc)
        return

    # Newest first; everything past index max_runs - 1 is stale.
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in run_dirs[max_runs:]:
        try:
            for child in stale.iterdir():
                child.unlink()
            stale.rmdir()
            logger.info("pruned audit run dir %s", stale)
        except OSError as exc:
            logger.warning("prune_audit_cache: failed to remove %s: %s", stale, exc)
