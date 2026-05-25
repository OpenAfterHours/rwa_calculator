"""
Materialization strategies for pipeline collect barriers.

Pipeline position:
    Used by CRMProcessor and PipelineOrchestrator at every .collect() barrier

Key responsibilities:
- Replace raw .collect().lazy() with strategy-aware materialization
- Support disk-spill (streaming mode) for out-of-core datasets
- Support in-memory (cpu mode) for backward compatibility
- Manage temp file lifecycle
- Persist opt-in audit artifacts under ``CalculationConfig.audit_cache_dir``

The pipeline has several points where lazy plans must be materialized to prevent
Polars optimizer issues (deep plan re-execution, segfaults on >500-node plans).
Previously these used .collect().lazy() which forces the full dataset into RAM.

This module provides two strategies controlled by config.collect_engine:
- "cpu": .collect().lazy() — existing behavior, full in-memory
- "streaming": sink_parquet → scan_parquet — caps memory at ~1 column batch

It also owns the audit-cache writer ``sink_audit``: a side-effect that drops a
parquet snapshot of a frame under ``<audit_cache_dir>/<run_id>/<name>.parquet``
when the user has opted in via ``CalculationConfig.audit_cache_dir``. Keeping
the sink here preserves the arch-check invariant that ``sink_parquet`` is only
called from ``engine/materialise.py``.

References:
- docs/specifications/audit-cache.md
"""

from __future__ import annotations

import atexit
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.observability.context import current_run_id

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)

# Module-level registry of temp files for cleanup
_spill_files: list[Path] = []


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


def materialise_barrier(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
) -> pl.LazyFrame:
    """
    Materialise a LazyFrame at a pipeline barrier point.

    Replaces the pattern ``lf.collect().lazy()`` with a strategy that
    respects ``config.collect_engine``:

    - ``"cpu"``: In-memory collect (existing behavior).
    - ``"streaming"``: Sink to a temp parquet file, then scan it back.
      This caps peak memory to approximately one column-batch at a time.

    Args:
        lf: LazyFrame to materialise
        config: Calculation configuration (provides collect_engine and spill_dir)
        label: Human-readable label for temp file naming and logging

    Returns:
        A fresh LazyFrame backed by either in-memory data or a parquet scan
    """
    if config.collect_engine == "cpu":
        return lf.collect().lazy()

    # Streaming mode: sink to parquet for out-of-core support
    return _spill_to_disk(lf, config, label)


def materialise_branches(
    branches: list[pl.LazyFrame],
    config: CalculationConfig,
    labels: list[str],
) -> list[pl.DataFrame]:
    """
    Materialise multiple branches, replacing ``pl.collect_all()``.

    - ``"cpu"``: Uses ``pl.collect_all()`` which leverages CSE (Common
      Subexpression Elimination) to compute shared upstream plans once.
    - ``"streaming"``: Sinks each branch to parquet sequentially, then
      reads back as DataFrames. Peak memory = one branch at a time.

    Args:
        branches: LazyFrames to materialise
        config: Calculation configuration
        labels: Human-readable labels for each branch

    Returns:
        List of DataFrames in the same order as input branches
    """
    if config.collect_engine == "cpu":
        result: list[pl.DataFrame] = pl.collect_all(branches)
        return result

    # Streaming mode: sink each branch individually
    results: list[pl.DataFrame] = []
    for lf, label in zip(branches, labels, strict=True):
        scanned = _spill_to_disk(lf, config, label)
        results.append(scanned.collect())
    return results


def cleanup_spill_files() -> None:
    """Remove all temp parquet files created during materialization."""
    for path in _spill_files:
        try:
            if path.exists():
                path.unlink()
                logger.debug("Cleaned up spill file: %s", path)
        except OSError:
            logger.warning("Failed to clean up spill file: %s", path)
    _spill_files.clear()


def _spill_to_disk(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
) -> pl.LazyFrame:
    """Sink a LazyFrame to a temp parquet file and scan it back.

    Falls back to in-memory collect if sink_parquet fails (e.g., unsupported
    expression types in the streaming engine).

    Args:
        lf: LazyFrame to sink
        config: Calculation configuration
        label: Label for temp file naming

    Returns:
        LazyFrame backed by the parquet scan
    """
    spill_dir = config.spill_dir if config.spill_dir is not None else None
    safe_label = label.replace("/", "_").replace(" ", "_")

    try:
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".parquet",
            prefix=f"rwa_{safe_label}_",
            dir=spill_dir,
        )
        # Close the file descriptor — sink_parquet will write to the path
        import os

        os.close(fd)
        tmp_path = Path(tmp_path_str)

        lf.sink_parquet(tmp_path)
        _spill_files.append(tmp_path)
        logger.debug("Spilled %s to %s", label, tmp_path)
        return pl.scan_parquet(tmp_path)
    except Exception:
        logger.warning(
            "sink_parquet failed for %s, falling back to in-memory collect",
            label,
        )
        return lf.collect().lazy()


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


# Register cleanup at interpreter exit as a safety net
atexit.register(cleanup_spill_files)
